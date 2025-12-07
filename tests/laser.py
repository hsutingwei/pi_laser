import RPi.GPIO as GPIO
import time

LASER_PIN = 18  # 接在 S pin

GPIO.setmode(GPIO.BCM)
GPIO.setup(LASER_PIN, GPIO.OUT)

try:
    while True:
        GPIO.output(LASER_PIN, True)
        print("Laser ON")
        time.sleep(1)

        GPIO.output(LASER_PIN, False)
        print("Laser OFF")
        time.sleep(1)

except KeyboardInterrupt:
    GPIO.cleanup()
