import time
import threading
import random
import os
import logging
from .safety import rect_intersects, expand_bbox, get_head_anchor, get_repulsion_target, get_random_annulus_point
from .pid_controller import PIDController

logger = logging.getLogger("AutoPilot")

class AutoPilot:
    def __init__(self, config_data, servos, laser, detector, calibration):
        self.config = config_data.get('auto_loop', {})
        self.safety_config = config_data.get('safety', {})
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
        self.cooldown_sec = self.config.get('cooldown_sec', 1.0)
        self.settle_ms = self.config.get('safety', {}).get('servo_settle_ms', 250)
        self.max_laser_on_ms = config_data.get('laser', {}).get('max_on_ms', 800)
        
        self.danger_margin = self.safety_config.get('danger_margin_px', 50)
        self.evade_cooldown_ms = self.safety_config.get('cooldown_ms', 2000)
        
        # PID Controllers (One for Pan, One for Tilt)
        # Conservative starting values
        self.pid_pan = PIDController(kp=0.1, ki=0.0, kd=0.01)
        self.pid_tilt = PIDController(kp=0.1, ki=0.0, kd=0.01)
        
        self.target_pan = 90
        self.target_tilt = 90

    def start(self):
        if self.running: return
        
        # Safety for Flask reloader
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not os.environ.get('WERKZEUG_RUN_MAIN'):
             pass

        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("Started Control Loop")

    def stop(self):
        self.running = False
        self.state = 'MANUAL'
        if self.thread:
            self.thread.join(timeout=1.0)
        logger.info("Stopped")

    def set_mode(self, mode):
        if mode == 'auto':
            self.state = 'TRACK'
            self.target_pan = self.servos.current_pan
            self.target_tilt = self.servos.current_tilt
            self.pid_pan.reset()
            self.pid_tilt.reset()
            logger.info("Switched to TRACK")
        else:
            self.state = 'MANUAL'
            self.laser.off()
            logger.info("Switched to MANUAL")

    def _loop(self):
        while self.running:
            try:
                if self.state == 'MANUAL':
                    time.sleep(0.1)
                    continue

                now = time.time()
                
                # --- 1. SENSE ---
                # Get current state
                current_pan = self.servos.current_pan
                current_tilt = self.servos.current_tilt
                
                # Predict Laser Position (ROI Center)
                roi_center = self.calibration.predict(current_pan, current_tilt)
                
                # Get Detections
                bboxes = self.detector.get_latest_detections()
                
                # --- 2. THINK (FSM) ---
                
                # Check Safety Violation (Global Check)
                unsafe = False
                cat_bbox = None
                
                if roi_center and bboxes:
                    # ROI Rect: [x-r, y-r, x+r, y+r]
                    rx, ry = roi_center
                    r = self.roi_radius
                    laser_rect = [rx-r, ry-r, rx+r, ry+r]
                    
                    for det in bboxes:
                        bbox = det.get('bbox') # [x1, y1, x2, y2]
                        if not bbox: continue
                        
                        # Expand Danger Zone
                        danger_zone = expand_bbox(bbox, self.danger_margin)
                        
                        if rect_intersects(laser_rect, danger_zone):
                            unsafe = True
                            cat_bbox = bbox
                            break
                
                # State Transitions
                if unsafe and self.state != 'EVADE' and self.state != 'COOLDOWN':
                    logger.warning("SAFETY VIOLATION! EVADING!")
                    self.state = 'EVADE'
                    self.laser.off()
                    
                    # Calculate Repulsion Target
                    if cat_bbox and roi_center:
                        tx, ty = get_repulsion_target(cat_bbox, roi_center)
                        # Inverse Kinematics (Pixels -> Angles)
                        # This is tricky without full inverse calibration. 
                        # Approximation: Move proportional to pixel diff?
                        # Or just pick a random safe point?
                        # Let's use the random annulus for simplicity + safety guarantee
                        # But repulsion is better.
                        # Let's try to map pixel target back to angles if possible?
                        # Since we don't have inverse calib, let's just move servos AWAY.
                        # Heuristic: If cat is left, move right.
                        
                        # Simpler: Just pick a random point in annulus that is NOT intersecting cat?
                        # Let's use the annulus sampler but filter for safety.
                        pass

                # --- STATE HANDLERS ---
                
                if self.state == 'EVADE':
                    self.laser.off()
                    # Pick a new target immediately
                    # Random "Safe" Jump
                    # We don't have inverse kinematics (Pixels -> Pan/Tilt), so we jitter angles blindly?
                    # Or we use the current calibration to guess?
                    # Let's just do a large random jump for now to break the lock.
                    
                    # Better: Move servos to a "Safe Home" or random large offset?
                    j_pan = random.uniform(-40, 40)
                    j_tilt = random.uniform(-20, 20)
                    
                    self.target_pan = current_pan + j_pan
                    self.target_tilt = current_tilt + j_tilt
                    
                    self.state = 'COOLDOWN'
                    self.evade_start_time = now
                    logger.info(f"Evading to P={self.target_pan:.1f}, T={self.target_tilt:.1f}")

                elif self.state == 'COOLDOWN':
                    self.laser.off()
                    if (now - self.evade_start_time) * 1000 > self.evade_cooldown_ms:
                        self.state = 'TRACK'
                        logger.info("Cooldown finished -> TRACK")
                        # Reset PIDs
                        self.pid_pan.reset()
                        self.pid_tilt.reset()

                elif self.state == 'TRACK':
                    # Normal Play Logic
                    
                    # Check Settle
                    is_settled = (now - self.last_move_time) * 1000 > self.settle_ms
                    
                    # Laser Control
                    if is_settled:
                        if not self.laser.state:
                            self.laser.on()
                            self.laser_on_start_time = now
                    else:
                        if self.laser.state:
                            self.laser.off()
                            
                    # Max Laser Time
                    if self.laser.state and (now - self.laser_on_start_time) * 1000 > self.max_laser_on_ms:
                        logger.info("Max Laser Time -> Retargeting")
                        self._perform_retarget()
                        
                    # Hit Test (Game Logic)
                    if is_settled and roi_center and bboxes:
                        for det in bboxes:
                            bbox = det.get('bbox')
                            if self._check_hit(bbox, roi_center, self.roi_radius):
                                logger.info(f"HIT! {det.get('label')}")
                                self._perform_retarget()
                                break

                # --- 3. ACT (PID Control) ---
                # Smoothly move towards target_pan/tilt
                
                # Update PID
                out_pan = self.pid_pan.update(self.target_pan, current_pan)
                out_tilt = self.pid_tilt.update(self.target_tilt, current_tilt)
                
                # PID output is usually a correction, but here we want it to drive velocity or position?
                # Standard PID: Output = Control Signal (e.g. Power).
                # For Servo, we set Position.
                # So we want: NewPosition = CurrentPosition + PID_Output
                
                # Let's treat PID output as "Velocity" (Delta Angle)
                # Error = Target - Current
                # Output = Delta
                
                next_pan = current_pan + out_pan
                next_tilt = current_tilt + out_tilt
                
                # Move Servos
                # Only move if significant change (reduce jitter)
                if abs(out_pan) > 0.1 or abs(out_tilt) > 0.1:
                    self.servos.set_pan(next_pan)
                    self.servos.set_tilt(next_tilt)
                    self.last_move_time = now
            
            except Exception as e:
                logger.error(f"Loop Error: {e}")
                time.sleep(1.0)
            
            time.sleep(0.02) # 50Hz loop for smoother PID

    def _perform_retarget(self):
        """Pick a new random target near current position"""
        self.laser.off()
        
        retarget = self.config.get('retarget', {})
        j_pan = retarget.get('pan_jitter_deg', 10)
        j_tilt = retarget.get('tilt_jitter_deg', 6)
        
        # Update Target, let PID smooth it
        self.target_pan = self.servos.current_pan + random.uniform(-j_pan, j_pan)
        self.target_tilt = self.servos.current_tilt + random.uniform(-j_tilt, j_tilt)

    def _check_hit(self, bbox, roi_center, roi_radius):
        """Hit Test: Center-in-ROI (XYXY format)"""
        if not roi_center: return False

        # bbox is [x1, y1, x2, y2]
        x1, y1, x2, y2 = bbox
        bcx = (x1 + x2) / 2
        bcy = (y1 + y2) / 2
        
        rcx, rcy = roi_center
        dist_sq = (bcx - rcx)**2 + (bcy - rcy)**2
        
        return dist_sq < (roi_radius**2)
        
    def get_status(self):
        roi = None
        if self.calibration.calibrated:
             roi = self.calibration.predict(self.servos.current_pan, self.servos.current_tilt)
             
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
