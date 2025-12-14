import time
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Servo
import math

# Configuration from JSON
PIN_PAN = 27
PIN_TILT = 17

# Standard SG90 Pulse Widths (approximate, tuning may be needed)
MIN_PULSE = 0.5/1000
MAX_PULSE = 2.5/1000

# Angle Limits from JSON (Calibrated)
PAN_MIN_ANGLE = 0
PAN_MAX_ANGLE = 180
TILT_MIN_ANGLE = 0
TILT_MAX_ANGLE = 180

class ServoController:
    def __init__(self, factory=None):
        self.factory = factory
        if self.factory is None:
            # Fallback or local testing hack
            try:
                self.factory = PiGPIOFactory()
            except Exception as e:
                print(f"Warning: Could not connect to pigpio: {e}")
                self.factory = None

        self.pan_servo = None
        self.tilt_servo = None
        
        if self.factory:
            self.pan_servo = Servo(PIN_PAN, min_pulse_width=MIN_PULSE, max_pulse_width=MAX_PULSE, pin_factory=self.factory)
            self.tilt_servo = Servo(PIN_TILT, min_pulse_width=MIN_PULSE, max_pulse_width=MAX_PULSE, pin_factory=self.factory)
        
        self.current_pan = 90
        self.current_tilt = 90
        
        # Move to center initially
        self.set_pan(90)
        self.set_tilt(80) # Calibrated Center

    def _map_angle_to_value(self, angle):
        """Maps 0-180 degree to -1 to 1 value for gpiozero"""
        # gpiozero: -1 = min_pulse, 1 = max_pulse
        # We assume 0 deg = min_pulse (-1), 180 deg = max_pulse (1)
        # value = (angle - 90) / 90
        return (angle - 90) / 90.0

    def set_pan(self, angle):
        """Safely set Pan angle within limits"""
        clamped = max(PAN_MIN_ANGLE, min(angle, PAN_MAX_ANGLE))
        self.current_pan = clamped
        if self.pan_servo:
            val = self._map_angle_to_value(clamped)
            self.pan_servo.value = val
        return clamped

    def set_tilt(self, angle):
        """Safely set Tilt angle within limits"""
        clamped = max(TILT_MIN_ANGLE, min(angle, TILT_MAX_ANGLE))
        self.current_tilt = clamped
        if self.tilt_servo:
            val = self._map_angle_to_value(clamped)
            self.tilt_servo.value = val
        return clamped

    def move_relative(self, d_pan, d_tilt):
        """Move relative to current position (useful for joystick integration)"""
        new_pan = self.current_pan + d_pan
        new_tilt = self.current_tilt + d_tilt
        
        actual_pan = self.set_pan(new_pan)
        actual_tilt = self.set_tilt(new_tilt)
        
        return actual_pan, actual_tilt
