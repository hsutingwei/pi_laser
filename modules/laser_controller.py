from gpiozero import LED
from gpiozero.pins.pigpio import PiGPIOFactory

PIN_LASER = 18

class LaserController:
    def __init__(self, factory=None):
        self.laser = None
        if factory:
            self.laser = LED(PIN_LASER, pin_factory=factory)
            self.laser.off()
        self.state = False

    def on(self):
        if self.laser:
            self.laser.on()
        self.state = True

    def off(self):
        if self.laser:
            self.laser.off()
        self.state = False

    def toggle(self):
        if self.state:
            self.off()
        else:
            self.on()
        return self.state
