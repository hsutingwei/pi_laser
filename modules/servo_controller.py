import time
import logging
from .servo_driver import ServoDriverPigpio, ServoDriverGPIO

logger = logging.getLogger("ServoController")

# Configuration from JSON
PIN_PAN = 27
PIN_TILT = 17

# Standard SG90 Pulse Widths
MIN_PULSE = 0.5/1000
MAX_PULSE = 2.5/1000

# Angle Limits from JSON (Calibrated)
PAN_MIN_ANGLE = 0
PAN_MAX_ANGLE = 180
TILT_MIN_ANGLE = 0
TILT_MAX_ANGLE = 180

class ServoController:
    def __init__(self, config_data=None):
        self.driver = None
        
        # Config
        driver_type = 'gpio'
        if config_data:
             driver_type = config_data.get('servos', {}).get('driver', 'gpio')
        
        # Initialize Driver
        if driver_type == 'pigpio':
            try:
                self.driver = ServoDriverPigpio(PIN_PAN, PIN_TILT, MIN_PULSE, MAX_PULSE)
            except Exception as e:
                logger.error(f"Failed to init pigpio: {e}. Falling back to GPIO.")
                self.driver = ServoDriverGPIO(PIN_PAN, PIN_TILT, MIN_PULSE, MAX_PULSE)
        else:
            self.driver = ServoDriverGPIO(PIN_PAN, PIN_TILT, MIN_PULSE, MAX_PULSE)

        # Initialize Limits (Dynamic)
        self.pan_limits = [PAN_MIN_ANGLE, PAN_MAX_ANGLE]
        self.tilt_limits = [TILT_MIN_ANGLE, TILT_MAX_ANGLE]
        
        self.current_pan = 90
        self.current_tilt = 90
        
        # Move to center initially
        self.set_pan(90)
        self.set_tilt(80) # Calibrated Center

    def set_limits(self, pan_limits=None, tilt_limits=None):
        if pan_limits: self.pan_limits = pan_limits
        if tilt_limits: self.tilt_limits = tilt_limits
        logger.info(f"Limits updated: Pan={self.pan_limits}, Tilt={self.tilt_limits}")

    def set_pan(self, angle, ignore_limits=False):
        """Safely set Pan angle within limits"""
        limits = [0, 180] if ignore_limits else self.pan_limits
        clamped = max(limits[0], min(angle, limits[1]))
        
        self.current_pan = clamped
        if self.driver:
            self.driver.set_angle('pan', clamped)
        return clamped

    def set_tilt(self, angle, ignore_limits=False):
        """Safely set Tilt angle within limits"""
        limits = [0, 180] if ignore_limits else self.tilt_limits
        clamped = max(limits[0], min(angle, limits[1]))
        
        self.current_tilt = clamped
        if self.driver:
            self.driver.set_angle('tilt', clamped)
        return clamped

    def move_relative(self, d_pan, d_tilt, ignore_limits=False):
        """Move relative to current position"""
        new_pan = self.current_pan + d_pan
        new_tilt = self.current_tilt + d_tilt
        
        actual_pan = self.set_pan(new_pan, ignore_limits=ignore_limits)
        actual_tilt = self.set_tilt(new_tilt, ignore_limits=ignore_limits)
        
        return actual_pan, actual_tilt

    def detach(self):
        """Stop sending pulses to servos"""
        if self.driver:
            self.driver.cleanup()
        logger.info("Detached")
