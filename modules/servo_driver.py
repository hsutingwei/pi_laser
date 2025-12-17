import time
import logging

logger = logging.getLogger("ServoDriver")

class ServoDriver:
    """Abstract Base Class for Servo Drivers"""
    def __init__(self, pin_pan, pin_tilt, min_pulse=0.0005, max_pulse=0.0025):
        self.pin_pan = pin_pan
        self.pin_tilt = pin_tilt
        self.min_pulse = min_pulse
        self.max_pulse = max_pulse

    def set_angle(self, channel, angle):
        """
        Set angle for a channel ('pan' or 'tilt').
        angle: 0-180
        """
        raise NotImplementedError

    def cleanup(self):
        raise NotImplementedError

class ServoDriverPigpio(ServoDriver):
    """
    Uses pigpio daemon for hardware-timed PWM.
    Requires 'pigpiod' to be running on the system.
    """
    def __init__(self, pin_pan, pin_tilt, min_pulse=0.0005, max_pulse=0.0025):
        super().__init__(pin_pan, pin_tilt, min_pulse, max_pulse)
        import pigpio
        self.pi = pigpio.pi()
        
        if not self.pi.connected:
            raise RuntimeError("Could not connect to pigpio daemon")
            
        logger.info("ServoDriver: Connected to pigpio")
        
        # Initialize pins
        self.pi.set_mode(self.pin_pan, pigpio.OUTPUT)
        self.pi.set_mode(self.pin_tilt, pigpio.OUTPUT)

    def set_angle(self, channel, angle):
        pin = self.pin_pan if channel == 'pan' else self.pin_tilt
        
        # Map 0-180 to pulse width (microseconds)
        # min_pulse (s) * 1000000 -> us
        min_us = self.min_pulse * 1000000
        max_us = self.max_pulse * 1000000
        
        pulse_width = min_us + (angle / 180.0) * (max_us - min_us)
        
        self.pi.set_servo_pulsewidth(pin, pulse_width)

    def cleanup(self):
        if self.pi and self.pi.connected:
            self.pi.set_servo_pulsewidth(self.pin_pan, 0) # Off
            self.pi.set_servo_pulsewidth(self.pin_tilt, 0) # Off
            self.pi.stop()
            logger.info("ServoDriver: pigpio cleanup done")

class ServoDriverGPIO(ServoDriver):
    """
    Fallback using RPi.GPIO (Software PWM).
    Note: Will have jitter.
    """
    def __init__(self, pin_pan, pin_tilt, min_pulse=0.0005, max_pulse=0.0025):
        super().__init__(pin_pan, pin_tilt, min_pulse, max_pulse)
        try:
            import RPi.GPIO as GPIO
        except ImportError:
             # Mock for non-Pi dev
            from unittest.mock import MagicMock
            GPIO = MagicMock()
            GPIO.BCM = 11
            GPIO.OUT = 0
            
        self.GPIO = GPIO
        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setup(self.pin_pan, self.GPIO.OUTPUT)
        self.GPIO.setup(self.pin_tilt, self.GPIO.OUTPUT)
        
        self.pwm_pan = self.GPIO.PWM(self.pin_pan, 50) # 50Hz
        self.pwm_tilt = self.GPIO.PWM(self.pin_tilt, 50)
        
        self.pwm_pan.start(0)
        self.pwm_tilt.start(0)
        logger.info("ServoDriver: Initialized RPi.GPIO (Fallback)")

    def set_angle(self, channel, angle):
        pwm = self.pwm_pan if channel == 'pan' else self.pwm_tilt
        
        # Duty Cycle Calculation
        # Period = 20ms (50Hz)
        # Duty = Pulse / 20ms * 100
        
        min_ms = self.min_pulse * 1000
        max_ms = self.max_pulse * 1000
        
        pulse_ms = min_ms + (angle / 180.0) * (max_ms - min_ms)
        duty = (pulse_ms / 20.0) * 100.0
        
        pwm.ChangeDutyCycle(duty)
        
        # Software PWM requires continuous signal to hold, but we can turn off to save jitter if needed
        # For now, keep it simple.

    def cleanup(self):
        self.pwm_pan.stop()
        self.pwm_tilt.stop()
        # self.GPIO.cleanup() # Careful not to kill other GPIOs
