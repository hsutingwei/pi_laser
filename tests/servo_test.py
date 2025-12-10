import RPi.GPIO as GPIO
import time

PAN_PIN = 27
TILT_PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(PAN_PIN, GPIO.OUT)
GPIO.setup(TILT_PIN, GPIO.OUT)

pan = GPIO.PWM(PAN_PIN, 50)
tilt = GPIO.PWM(TILT_PIN, 50)

pan.start(0)
tilt.start(0)

def set_angle(pwm, angle):
    duty = 2 + (angle / 18)
    pwm.ChangeDutyCycle(duty)
    time.sleep(0.35)
    pwm.ChangeDutyCycle(0)

try:
    while True:
        print("PAN → LEFT")
        set_angle(pan, 30)

        print("PAN → RIGHT")
        set_angle(pan, 150)

        print("TILT → UP")
        set_angle(tilt, 40)

        print("TILT → DOWN")
        set_angle(tilt, 120)

except KeyboardInterrupt:
    pass

pan.stop()
tilt.stop()
GPIO.cleanup()