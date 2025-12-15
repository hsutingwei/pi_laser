import time
import threading
import random
import os

class AutoPilot:
    def __init__(self, config_data, servos, laser, detector, calibration):
        self.config = config_data.get('auto_loop', {})
        self.servos = servos
        self.laser = laser
        self.detector = detector
        self.calibration = calibration
        
        # State
        self.state = 'MANUAL' # MANUAL, AUTO_READY, AUTO_COOLDOWN
        self.running = False
        self.thread = None
        self.last_move_time = 0
        self.last_hit_time = 0
        self.laser_on_start_time = 0
        
        # Config params
        self.roi_radius = config_data.get('calibration', {}).get('roi_radius_px', 35)
        self.cooldown_sec = self.config.get('cooldown_sec', 1.0)
        self.settle_ms = self.config.get('safety', {}).get('servo_settle_ms', 250)
        self.max_laser_on_ms = config_data.get('laser', {}).get('max_on_ms', 800)
        
        self.pan_limits = config_data.get('servos', {}).get('pan_limits_deg', [0, 180])
        self.tilt_limits = config_data.get('servos', {}).get('tilt_limits_deg', [0, 180])

    def start(self):
        if self.running:
            return
        
        # Safety: Prevent double start in debug reloader
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not os.environ.get('WERKZEUG_RUN_MAIN'):
             # Logic is tricky here with Flask reloader. 
             # We rely on app.py calling this only in the right context.
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
        # mode: 'manual' or 'auto'
        if mode == 'auto':
            self.state = 'AUTO_READY'
            print("[AutoPilot] Switched to AUTO_READY")
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

                # --- AUTO_COOLDOWN ---
                if self.state == 'AUTO_COOLDOWN':
                    if now - self.last_hit_time > self.cooldown_sec:
                        self.state = 'AUTO_READY'
                        print("[AutoPilot] Cooldown finished -> READY")
                    else:
                        time.sleep(0.1)
                    continue

                # --- AUTO_READY ---
                if self.state == 'AUTO_READY':
                    # 1. Safety Check: Move Settle
                    is_settled = (now - self.last_move_time) * 1000 > self.settle_ms
                    
                    # 2. Safety Check: Max Laser On
                    # If laser has been on too long, force a retarget (cooldown)
                    if self.laser.state and (now - self.laser_on_start_time) * 1000 > self.max_laser_on_ms:
                         print("[AutoPilot] Max Laser Time Reached -> Retargeting")
                         self._perform_retarget()
                         self.state = 'AUTO_COOLDOWN'
                         self.last_hit_time = now # Treat as hit to trigger cooldown
                         continue

                    # 3. Laser Control
                    if is_settled:
                        if not self.laser.state:
                            self.laser.on()
                            self.laser_on_start_time = now
                    else:
                        if self.laser.state:
                            self.laser.off()

                    # 4. Detection & Hit Test
                    # Only check hit if laser is actually ON (or about to be) and we are settled
                    if is_settled:
                        # Get Predicted ROI
                        pan = self.servos.current_pan
                        tilt = self.servos.current_tilt
                        roi_center = self.calibration.predict(pan, tilt)
                        
                        if roi_center:
                            # Get Detections (Mock or Real)
                            # Note: detector.detect() creates new bboxes based on logic
                            # For MockDetector, it returns bbox if valid
                            bboxes = self.detector.detect(None)
                            
                            for det in bboxes:
                                bbox = det.get('bbox')
                                if not bbox: continue
                                
                                if self._check_hit(bbox, roi_center, self.roi_radius):
                                    print(f"[AutoPilot] HIT! {det.get('label')} ({det.get('score'):.2f})")
                                    self._perform_retarget()
                                    self.state = 'AUTO_COOLDOWN'
                                    self.last_hit_time = now
                                    break
            
            except Exception as e:
                print(f"[AutoPilot] Error: {e}")
                time.sleep(1.0) # Prevent tight loop fail
            
            time.sleep(0.05) # 20Hz loop

    def _perform_retarget(self):
        """Turn laser off, move random amount"""
        self.laser.off()
        
        # Parse params
        retarget = self.config.get('retarget', {})
        j_pan = retarget.get('pan_jitter_deg', 10)
        j_tilt = retarget.get('tilt_jitter_deg', 6)
        min_move = retarget.get('min_move_deg', 2.0)
        
        # Current
        c_pan = self.servos.current_pan
        c_tilt = self.servos.current_tilt
        
        # Retry loop for valid move
        for _ in range(5):
             dp = random.uniform(-j_pan, j_pan)
             dt = random.uniform(-j_tilt, j_tilt)
             
             # Check minimum move
             if abs(dp) < min_move and abs(dt) < min_move:
                 continue
                 
             # Check limits (simple clamp check, ServoController clamps too but we want to avoid sticky edges)
             t_pan = c_pan + dp
             t_tilt = c_tilt + dt
             
             # Apply
             self.servos.move_relative(dp, dt)
             self.last_move_time = time.time()
             break

    def _check_hit(self, bbox, roi_center, roi_radius):
        """
        Hit Test: Center-in-ROI
        Check if the center of the bounding box is within the ROI circle.
        """
        if not roi_center:
            return False

        # BBox Center (Frame Coords)
        bx, by, bw, bh = bbox
        bcx = bx + bw / 2
        bcy = by + bh / 2
        
        # ROI Center
        rcx, rcy = roi_center
        
        # Euclidean Distance Squared
        dist_sq = (bcx - rcx)**2 + (bcy - rcy)**2
        
        return dist_sq < (roi_radius**2)
        
    def get_status(self):
        # Prepare status payload for WebSocket
        # Predicted ROI
        roi = None
        if self.calibration.calibrated:
             roi = self.calibration.predict(self.servos.current_pan, self.servos.current_tilt)
             
        # Detector BBox (For viz)
        bboxes = self.detector.detect(None)
        
        return {
            "state": self.state,
            "roi": roi, # (x, y) center
            "roi_radius": self.roi_radius,
            "bboxes": bboxes,
            "laser": self.laser.state,
            "pan": self.servos.current_pan,
            "tilt": self.servos.current_tilt
        }
