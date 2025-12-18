import time
import threading
import random
import os
from . import safety

class AutoPilot:
    def __init__(self, config_data, servos, laser, detector, calibration):
        self.config = config_data.get('auto_loop', {})
        self.servos = servos
        self.laser = laser
        self.detector = detector
        self.calibration = calibration
        
        # State
        self.state = 'MANUAL' # MANUAL, TRACK, EVADE, COOLDOWN
        self.running = False
        self.thread = None
        self.last_move_time = 0
        self.last_hit_time = 0
        self.laser_on_start_time = 0
        self.evade_start_time = 0
        
        # Config params
        self.roi_radius = config_data.get('calibration', {}).get('roi_radius_px', 35)
        self.cooldown_sec = self.config.get('cooldown_sec', 1.2)
        self.settle_ms = self.config.get('safety', {}).get('servo_settle_ms', 250)
        self.max_laser_on_ms = config_data.get('laser', {}).get('max_on_ms', 800)
        self.danger_margin = config_data.get('safety', {}).get('danger_margin_px', 50)
        self.evade_cooldown_ms = config_data.get('safety', {}).get('cooldown_ms', 2000)
        
        self.pan_limits = config_data.get('servos', {}).get('pan_limits_deg', [20, 160])
        self.tilt_limits = config_data.get('servos', {}).get('tilt_limits_deg', [20, 140])

    def start(self):
        if self.running: return
        
        # Safety for Flask reloader
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not os.environ.get('WERKZEUG_RUN_MAIN'):
             pass

        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[AutoPilot] Started Control Loop")

    def stop(self):
        self.running = False
        self.state = 'MANUAL'
        if self.thread:
            self.thread.join(timeout=1.0)
        print("[AutoPilot] Stopped")

    def set_mode(self, mode):
        if mode == 'auto':
            self.state = 'TRACK'
            print("[AutoPilot] Switched to TRACK")
        else:
            self.state = 'MANUAL'
            self.laser.off()
            print("[AutoPilot] Switched to MANUAL")

    def _loop(self):
        while self.running:
            try:
                if self.state == 'MANUAL':
                    time.sleep(0.1)
                    continue

                now = time.time()
                
                # --- 1. COOLDOWN STATE ---
                if self.state == 'COOLDOWN':
                    # Wait for evade cooldown
                    if (now - self.evade_start_time) * 1000 > self.evade_cooldown_ms:
                        self.state = 'TRACK'
                        print("[AutoPilot] Cooldown finished -> TRACK")
                    else:
                        time.sleep(0.1)
                    continue

                # --- 2. EVADE STATE ---
                if self.state == 'EVADE':
                    # Logic handled in transition, just ensure laser is off
                    if self.laser.state: self.laser.off()
                    self.state = 'COOLDOWN'
                    self.evade_start_time = now
                    continue

                # --- 3. TRACK STATE (Normal Operation) ---
                if self.state == 'TRACK':
                    # A. Move Settle Check
                    is_settled = (now - self.last_move_time) * 1000 > self.settle_ms
                    
                    # B. Get Laser Position (ROI)
                    roi_center = None
                    if is_settled:
                        roi_center = self.calibration.predict(self.servos.current_pan, self.servos.current_tilt)
                    
                    # C. Get Detections
                    bboxes = self.detector.get_latest_detections()
                    # Sort by score
                    bboxes.sort(key=lambda x: x.get('score', 0), reverse=True)
                    
                    # D. Safety Check (CRITICAL)
                    danger_detected = False
                    target_cat_bbox = None
                    
                    if roi_center:
                        laser_bbox = [
                            roi_center[0] - self.roi_radius,
                            roi_center[1] - self.roi_radius,
                            roi_center[0] + self.roi_radius,
                            roi_center[1] + self.roi_radius
                        ]
                        
                        for det in bboxes:
                            cat_bbox = det.get('bbox') # [x1, y1, x2, y2]
                            if not cat_bbox: continue
                            
                            # Expand cat bbox for safety margin
                            danger_zone = safety.expand_bbox(cat_bbox, self.danger_margin)
                            
                            if safety.rect_intersects(laser_bbox, danger_zone):
                                print(f"[AutoPilot] DANGER! Laser overlapping with {det.get('label')}")
                                danger_detected = True
                                target_cat_bbox = cat_bbox
                                break
                    
                    if danger_detected:
                        self.laser.off()
                        self._perform_evade(target_cat_bbox, roi_center)
                        self.state = 'EVADE'
                        continue

                    # E. Laser Control (If safe)
                    if is_settled and not danger_detected:
                        # Max On Time Check
                        if self.laser.state and (now - self.laser_on_start_time) * 1000 > self.max_laser_on_ms:
                             print("[AutoPilot] Max Laser Time -> Retargeting")
                             self._perform_retarget() # Random move
                             self.laser_on_start_time = now # Reset timer
                        elif not self.laser.state:
                            self.laser.on()
                            self.laser_on_start_time = now
                    else:
                        if self.laser.state: self.laser.off()

            except Exception as e:
                print(f"[AutoPilot] Loop Error: {e}")
                time.sleep(1.0)
            
            time.sleep(0.02) # 50Hz loop for faster reaction

    def _perform_evade(self, cat_bbox, current_roi):
        """Calculate safe point away from cat and move there"""
        if not current_roi: return
        
        # Calculate repulsion target
        tx, ty = safety.get_repulsion_target(cat_bbox, current_roi, safe_dist=200)
        
        # Convert back to Pan/Tilt (Inverse Kinematics - approximated or via calibration)
        # Since we don't have inverse calibration, we use a heuristic or random if complex
        # For now, let's use a robust random retarget that biases away if possible, 
        # or just simple random retargeting if inverse mapping is hard.
        
        # Given we only have Forward Calibration (Pan/Tilt -> Pixels), 
        # we can't easily go Pixels -> Pan/Tilt without a solver.
        # So we will use a simpler approach: Large Random Jump.
        
        print("[AutoPilot] Evading...")
        self._perform_retarget(magnitude_multiplier=2.0)

    def _perform_retarget(self, magnitude_multiplier=1.0):
        """Turn laser off, move random amount"""
        self.laser.off()
        
        retarget = self.config.get('retarget', {})
        j_pan = retarget.get('pan_jitter_deg', 10) * magnitude_multiplier
        j_tilt = retarget.get('tilt_jitter_deg', 6) * magnitude_multiplier
        min_move = retarget.get('min_move_deg', 2.0)
        
        for _ in range(5):
             dp = random.uniform(-j_pan, j_pan)
             dt = random.uniform(-j_tilt, j_tilt)
             if abs(dp) < min_move and abs(dt) < min_move: continue
                 
             self.servos.move_relative(dp, dt)
             self.last_move_time = time.time()
             break

    def get_status(self):
        roi = None
        if self.calibration.calibrated:
             roi = self.calibration.predict(self.servos.current_pan, self.servos.current_tilt)
             
        # Detector BBox (For viz) - PASSIVE READ
        bboxes = self.detector.get_latest_detections()
        
        return {
            "state": self.state,
            "roi": roi, 
            "roi_radius": self.roi_radius,
            "bboxes": bboxes,
            "laser": self.laser.state,
            "pan": self.servos.current_pan,
            "tilt": self.servos.current_tilt
        }
