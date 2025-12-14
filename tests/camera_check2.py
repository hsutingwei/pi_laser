from picamera import PiCamera
from time import sleep
cam = PiCamera()
cam.resolution = (640, 480)
sleep(2)
cam.capture('test_picamera.jpg')
print("saved test_picamera.jpg")