import threading
import time
import math
import random

class WobbleEngine:
    def __init__(self, servo_ctrl):
        self.servo_ctrl = servo_ctrl
        self.running = False
        self.thread = None
        self.pattern = "random"
        self.center_pan = 90
        self.center_tilt = 80
        
    def start(self, pattern="random"):
        if self.running:
            return
        self.running = True
        self.pattern = pattern
        # Update center to current position so it wobbles AROUND where we are
        self.center_pan = self.servo_ctrl.current_pan
        self.center_tilt = self.servo_ctrl.current_tilt
        
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

    def _loop(self):
        t = 0
        while self.running:
            if self.pattern == "circle":
                # Circle radius 10 degrees, speed 2 rad/s
                radius = 10
                speed = 2.0
                offset_x = radius * math.cos(t * speed)
                offset_y = radius * math.sin(t * speed)
                self.servo_ctrl.set_pan(self.center_pan + offset_x)
                self.servo_ctrl.set_tilt(self.center_tilt + offset_y)
                
            elif self.pattern == "figure_8":
                # Lemniscate
                scale = 15
                speed = 2.0
                offset_x = scale * math.cos(t * speed)
                offset_y = scale * math.sin(2 * t * speed) / 2
                self.servo_ctrl.set_pan(self.center_pan + offset_x)
                self.servo_ctrl.set_tilt(self.center_tilt + offset_y)
                
            elif self.pattern == "small_random":
                # Jittery random movement
                offset_x = random.uniform(-5, 5)
                offset_y = random.uniform(-5, 5)
                self.servo_ctrl.set_pan(self.center_pan + offset_x)
                self.servo_ctrl.set_tilt(self.center_tilt + offset_y)
                # Sleep is part of the rhythm here
                time.sleep(0.1) 
                t += 0.1
                continue

            time.sleep(0.05)
            t += 0.05
