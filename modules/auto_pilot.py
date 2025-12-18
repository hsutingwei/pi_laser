import time
import threading
import random
import os
import math
from . import safety

"""
1. MANUAL (手動模式)
    意義：自動導航完全關閉。
    行為：
        AutoPilot執行緒雖然在跑，但只會空轉 (sleep)。
        使用者可以透過鍵盤/搖桿完全控制雲台。
        雷射開關由使用者控制。
    進入條件：系統啟動預設，或使用者手動切換。
2. ROAM (漫遊模式)
    意義：正常運作中。模擬獵物在地上爬行。
    行為：
        選點：挑選一個安全的目的地。
        移動：雷射開啟，雲台慢慢轉向目標。
        監控：移動過程中，隨時檢查是否會撞到貓。
    進入條件：使用者開啟自動模式，或從 COOLDOWN 結束後自動進入。
3. EVADE (閃避模式)
    意義：緊急迴避。發現危險（雷射碰到貓）。
    行為：
        雷射：強制關閉。
        動作：計算反方向或隨機大跳躍，迅速移開。
        時長：這是一個「瞬間」的狀態，執行完閃避動作後，下一幀就會馬上切換到 COOLDOWN。
    進入條件：在 ROAM 模式中偵測到危險 (_check_danger_and_evade 回傳 True)。
4. COOLDOWN (冷卻模式)
    意義：躲藏中。剛閃避完，暫時不出來。
    行為：
        雷射：保持關閉。
        動作：什麼都不做，等待計時器倒數。
    時長：預設 2 秒 (evade_cooldown_ms)。
    進入條件：從 EVADE 狀態結束後自動進入。
    離開條件：時間到後，自動切回 ROAM，重新開始漫遊。
"""
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
            self.state = 'ROAM'
            print("[AutoPilot] Switched to ROAM")
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
                    if (now - self.evade_start_time) * 1000 > self.evade_cooldown_ms:
                        self.state = 'ROAM'
                        print("[AutoPilot] Cooldown finished -> ROAM")
                    else:
                        time.sleep(0.1)
                    continue

                # --- 2. EVADE STATE ---
                if self.state == 'EVADE':
                    if self.laser.state: self.laser.off()
                    self.state = 'COOLDOWN'
                    self.evade_start_time = now
                    continue

                # --- 3. ROAM STATE (Active Roaming) ---
                if self.state == 'ROAM':
                    # A. Safety Check (ALWAYS FIRST)
                    if self._check_danger_and_evade():
                        continue

                    # B. Roaming Logic
                    # If we are settled (reached target or just started), pick a new target
                    if not hasattr(self, 'target_pan') or self._has_reached_target():
                        self._pick_new_roam_target()
                        # Pause briefly at the destination to simulate "observing"
                        time.sleep(random.uniform(0.2, 0.8))
                        continue
                    
                    # C. Move towards target (Interpolation)
                    self._move_towards_target()
                    
                    # D. Laser Control
                    # In ROAM mode, laser should be ON unless we are moving too fast (optional)
                    # For this "creepy crawl" effect, we keep it ON.
                    if not self.laser.state:
                        self.laser.on()
                        self.laser_on_start_time = now
                    
                    # Max Laser On Time Check (Optional: blink or reset to prevent overheating if needed)
                    # For now, we let it roam continuously.

            except Exception as e:
                print(f"[AutoPilot] Loop Error: {e}")
                time.sleep(1.0)
            
            time.sleep(0.02) # 50Hz loop

    def _check_danger_and_evade(self):
        """負責移動中的即時安全檢查
        若偵測到危險且狀態切換至 EVADE 迴避，則返回 True"""
        # 1. Get Prediction
        roi_center = self.calibration.predict(self.servos.current_pan, self.servos.current_tilt)
        if not roi_center: return False
        
        # 2. Get Detections
        bboxes = self.detector.get_latest_detections()
        
        # 3. Check Overlap
        laser_bbox = [
            roi_center[0] - self.roi_radius,
            roi_center[1] - self.roi_radius,
            roi_center[0] + self.roi_radius,
            roi_center[1] + self.roi_radius
        ]
        
        for det in bboxes:
            cat_bbox = det.get('bbox')
            if not cat_bbox: continue
            
            danger_zone = safety.expand_bbox(cat_bbox, self.danger_margin)
            
            if safety.rect_intersects(laser_bbox, danger_zone):
                print(f"[AutoPilot] DANGER! Overlap with {det.get('label')}")
                self.laser.off()
                self._perform_evade(cat_bbox, roi_center)
                self.state = 'EVADE'
                return True
        return False

    def _pick_new_roam_target(self):
        """負責挑選安全落點"""
        # Try to find a safe point
        for _ in range(10):
            # Randomly pick a point within limits
            t_pan = random.uniform(self.pan_limits[0], self.pan_limits[1])
            t_tilt = random.uniform(self.tilt_limits[0], self.tilt_limits[1])
            
            # Predict where this is
            pred_pt = self.calibration.predict(t_pan, t_tilt)
            if not pred_pt: continue
            
            # Check if this potential target is near any cat
            bboxes = self.detector.get_latest_detections()
            is_safe = True
            for det in bboxes:
                cat_bbox = det.get('bbox')
                if not cat_bbox: continue
                
                # Check if target is inside danger zone
                danger_zone = safety.expand_bbox(cat_bbox, self.danger_margin + 20) # Extra margin for target
                
                # Simple point-in-rect check
                px, py = pred_pt
                if (danger_zone[0] < px < danger_zone[2]) and (danger_zone[1] < py < danger_zone[3]):
                    is_safe = False
                    break
            
            if is_safe:
                self.target_pan = t_pan
                self.target_tilt = t_tilt
                # print(f"[AutoPilot] New Target: {t_pan:.1f}, {t_tilt:.1f}")
                return

        # If we failed to find a safe point, just stay put or pick current
        self.target_pan = self.servos.current_pan
        self.target_tilt = self.servos.current_tilt

    def _has_reached_target(self):
        if not hasattr(self, 'target_pan'): return True
        d_pan = abs(self.servos.current_pan - self.target_pan)
        d_tilt = abs(self.servos.current_tilt - self.target_tilt)
        return d_pan < 1.0 and d_tilt < 1.0

    def _move_towards_target(self):
        """負責平滑移動到目標"""
        step_size = 0.5 # Degrees per loop (adjust for speed)
        
        c_pan = self.servos.current_pan
        c_tilt = self.servos.current_tilt
        
        # Calculate direction
        diff_pan = self.target_pan - c_pan
        diff_tilt = self.target_tilt - c_tilt
        
        dist = math.sqrt(diff_pan**2 + diff_tilt**2)
        if dist < step_size:
            # Just finish
            self.servos.set_pan(self.target_pan)
            self.servos.set_tilt(self.target_tilt)
        else:
            # Move step
            ratio = step_size / dist
            new_pan = c_pan + diff_pan * ratio
            new_tilt = c_tilt + diff_tilt * ratio
            self.servos.set_pan(new_pan)
            self.servos.set_tilt(new_tilt)

    def _perform_evade(self, cat_bbox, current_roi):
        """Calculate safe point away from cat and move there"""
        if not current_roi: return
        
        # Calculate repulsion target
        tx, ty = safety.get_repulsion_target(cat_bbox, current_roi, safe_dist=200)
        
        # Since we don't have inverse kinematics, we use a large random jump
        # But we try to bias it if possible. For now, large random jump is safest fallback.
        print("[AutoPilot] Evading...")
        
        # Force a large random move immediately
        retarget = self.config.get('retarget', {})
        j_pan = retarget.get('pan_jitter_deg', 20) * 2 # Double jitter for evade
        j_tilt = retarget.get('tilt_jitter_deg', 12) * 2
        
        dp = random.uniform(-j_pan, j_pan)
        dt = random.uniform(-j_tilt, j_tilt)
        self.servos.move_relative(dp, dt)
        
        # Reset target so Roam picks a new one after cooldown
        if hasattr(self, 'target_pan'): del self.target_pan

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
