import time
import os
from gpiozero import Servo, LED
from gpiozero.pins.pigpio import PiGPIOFactory
from signal import pause

# ==========================================
# CONFIGURATION
# ==========================================
# GPIO Pins (BCM numbering)
PIN_LASER = 17
PIN_PAN = 18
PIN_TILT = 13

# Servo Pulse Widths (Standard SG90)
# Adjust these if your servos hit limits or buzz
MIN_PULSE = 0.5/1000  # 0.5ms
MAX_PULSE = 2.5/1000  # 2.5ms

# ==========================================
# SETUP
# ==========================================

def check_pigpiod():
    """Check if pigpiod daemon is running."""
    val = os.system('pgrep pigpiod > /dev/null')
    if val != 0:
        print("❌ Error: pigpiod daemon is NOT running!")
        print("   Please run: sudo pigpiod")
        print("   Then try again.")
        exit(1)
    print("✅ pigpiod daemon is running.")

def main():
    print("=== Hardware Validation Script ===")
    check_pigpiod()

    # Initialize Pin Factory
    # This is CRITICAL for jitter-free operation on RPi
    try:
        factory = PiGPIOFactory()
        print("✅ PiGPIOFactory connected.")
    except Exception as e:
        print(f"❌ Failed to connect to pigpio daemon: {e}")
        return

    # Initialize Components
    try:
        print(f"Initializing Laser on GPIO {PIN_LASER}...")
        # Active HIGH for NPN base
        laser = LED(PIN_LASER, pin_factory=factory)
        
        print(f"Initializing Pan Servo on GPIO {PIN_PAN}...")
        pan = Servo(PIN_PAN, min_pulse_width=MIN_PULSE, max_pulse_width=MAX_PULSE, pin_factory=factory)
        
        print(f"Initializing Tilt Servo on GPIO {PIN_TILT}...")
        tilt = Servo(PIN_TILT, min_pulse_width=MIN_PULSE, max_pulse_width=MAX_PULSE, pin_factory=factory)

    except Exception as e:
        print(f"❌ Error initializing components: {e}")
        return

    try:
        # 1. Test Laser
        print("\n--- Testing Laser ---")
        for i in range(3):
            print(f"Laser ON ({i+1}/3)")
            laser.on()
            time.sleep(0.5)
            print(f"Laser OFF ({i+1}/3)")
            laser.off()
            time.sleep(0.5)
        
        # 2. Test Pan Servo
        print("\n--- Testing Pan Servo ---")
        print("Moving to MIN (-1)")
        pan.min()
        time.sleep(1)
        print("Moving to MAX (1)")
        pan.max()
        time.sleep(1)
        print("Moving to CENTER (0)")
        pan.mid()
        time.sleep(1)

        # 3. Test Tilt Servo
        print("\n--- Testing Tilt Servo ---")
        print("Moving to MIN (-1)")
        tilt.min()
        time.sleep(1)
        print("Moving to MAX (1)")
        tilt.max()
        time.sleep(1)
        print("Moving to CENTER (0)")
        tilt.mid()
        time.sleep(1)

        print("\n✅ Hardware Check Complete!")
        print("Verify that:")
        print("1. Laser blinked 3 times.")
        print("2. Servos moved smoothly without jitter when stopped.")
        print("3. Servos reached expected limits.")

    except KeyboardInterrupt:
        print("\nUser interrupted.")
    except Exception as e:
        print(f"\n❌ Runtime Error: {e}")
    finally:
        # Safety Cleanup
        print("\nCleaning up...")
        laser.off()
        # Detach servos to stop sending PWM (prevents heating/jitter)
        pan.detach()
        tilt.detach()
        print("Done.")

if __name__ == "__main__":
    main()
