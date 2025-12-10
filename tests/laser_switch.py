import RPi.GPIO as GPIO
import time

LASER_PIN = 18    # 雷射 S 接這裡
SWITCH_PIN = 23   # 開關 S 接這裡

GPIO.setmode(GPIO.BCM)

GPIO.setup(LASER_PIN, GPIO.OUT)
# 假設開關模組輸出「按下 = 拉低」，用內建上拉
GPIO.setup(SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

laser_on = False
GPIO.output(LASER_PIN, laser_on)

print("Ready. Press the switch to toggle the laser.")

try:
    while True:
        # 開關被按下時，腳位會從 HIGH 變成 LOW
        if GPIO.input(SWITCH_PIN) == GPIO.LOW:
            # 切換雷射狀態
            laser_on = not laser_on
            GPIO.output(LASER_PIN, laser_on)
            print("Laser", "ON" if laser_on else "OFF")

            # 簡單防彈跳：等按鍵放開才繼續偵測
            while GPIO.input(SWITCH_PIN) == GPIO.LOW:
                time.sleep(0.02)

        time.sleep(0.02)

except KeyboardInterrupt:
    print("Exit")
finally:
    GPIO.cleanup()
