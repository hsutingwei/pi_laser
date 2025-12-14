import time
try:
    import RPi.GPIO as GPIO
except ImportError:
    # Mock for development on non-Pi environment
    from unittest.mock import MagicMock
    GPIO = MagicMock()
    GPIO.BCM = 11
    GPIO.OUT = 0

class ServoPWM:
    """
    Servo control using RPi.GPIO PWM.
    
    IMPORTANT: Servos must be powered by an EXTERNAL 5V supply.
    Connect External Ground to Pi Ground (Common Ground).
    """
    
    def __init__(self, pin, duty_min=2.5, duty_max=12.5, min_angle=0, max_angle=180, frequency=50):
        self.pin = pin
        self.duty_min = duty_min
        self.duty_max = duty_max
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.frequency = frequency
        
        self.pwm = None
        self.current_angle = None
        
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT)
        
    def attach(self):
        """Initialize PWM on the pin."""
        if self.pwm is None:
            self.pwm = GPIO.PWM(self.pin, self.frequency)
            self.pwm.start(0) # Start with 0 duty (off)
            
    def detach(self):
        """Stop sending PWM signal to reduce jitter/heating when idle."""
        if self.pwm:
            self.pwm.ChangeDutyCycle(0)
            # In RPi.GPIO, usually 0 duty stops pulses. 
            # To fully detach, we might stop(), but then start() is needed again.
            
    def cleanup(self):
        """Clean up GPIO resources."""
        if self.pwm:
            self.pwm.stop()
            self.pwm = None
            
    def set_angle(self, angle, settle_sec=0.25):
        """
        Move servo to specified angle.
        
        Args:
            angle (float): Target angle (0-180 usually).
            settle_sec (float): Time to wait for servo to move.
        """
        # Safety Clamp
        if self.min_angle is not None:
            angle = max(self.min_angle, angle)
        if self.max_angle is not None:
            angle = min(self.max_angle, angle)
            
        self.current_angle = angle
        
        # Calculate Duty Cycle
        # Map 0-180 to duty_min-duty_max
        duty = self.duty_min + (angle / 180.0) * (self.duty_max - self.duty_min)
        
        if self.pwm is None:
            self.attach()
            
        self.pwm.ChangeDutyCycle(duty)
        
        if settle_sec > 0:
            time.sleep(settle_sec)
