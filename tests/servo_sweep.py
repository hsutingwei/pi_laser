import sys
import os
import json
import time

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

try:
    import RPi.GPIO as GPIO
    from modules.servo_pwm import ServoPWM
except ImportError:
    print("WARNING: RPi.GPIO not found.")
    sys.exit(1)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '../config/calibration.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def sweep_axis(servo, start, end, step=1, delay=0.02):
    print(f"Sweeping {start} -> {end}...")
    # Determine direction
    if start < end:
        r = range(start, end + 1, step)
    else:
        r = range(start, end - 1, -step)
        
    for angle in r:
        servo.set_angle(angle, settle_sec=0)
        time.sleep(delay)

def main():
    print("=== Servo Sweep Verification ===")
    if not os.path.exists(CONFIG_PATH):
        print("Config not found. Please run calibrate_servos.py first.")
        return

    params = load_config()
    pan_cfg = params['pan']
    tilt_cfg = params['tilt']
    
    print(f"Loaded Limits:")
    print(f"  Pan: {pan_cfg['min_angle']}-{pan_cfg['max_angle']} (Center: {pan_cfg['center']})")
    print(f"  Tilt: {tilt_cfg['min_angle']}-{tilt_cfg['max_angle']} (Center: {tilt_cfg['center']})")

    try:
        pan_servo = ServoPWM(params['pins']['pan'], 
                           duty_min=params['duty']['min'], 
                           duty_max=params['duty']['max'])
        tilt_servo = ServoPWM(params['pins']['tilt'], 
                            duty_min=params['duty']['min'], 
                            duty_max=params['duty']['max'])
        
        pan_servo.attach()
        tilt_servo.attach()
        
        # Go to Center
        print("Moving to Center...")
        pan_servo.set_angle(pan_cfg['center'], settle_sec=0.5)
        tilt_servo.set_angle(tilt_cfg['center'], settle_sec=0.5)
        
        # Sweep Pan
        print("\n--- Testing PAN Axis ---")
        sweep_axis(pan_servo, pan_cfg['center'], pan_cfg['min_angle'])
        time.sleep(0.5)
        sweep_axis(pan_servo, pan_cfg['min_angle'], pan_cfg['max_angle'])
        time.sleep(0.5)
        sweep_axis(pan_servo, pan_cfg['max_angle'], pan_cfg['center'])
        
        # Sweep Tilt
        print("\n--- Testing TILT Axis ---")
        sweep_axis(tilt_servo, tilt_cfg['center'], tilt_cfg['min_angle'])
        time.sleep(0.5)
        sweep_axis(tilt_servo, tilt_cfg['min_angle'], tilt_cfg['max_angle'])
        time.sleep(0.5)
        sweep_axis(tilt_servo, tilt_cfg['max_angle'], tilt_cfg['center'])
        
        print("\n✅ Sweep Complete.")
        
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        pan_servo.cleanup()
        tilt_servo.cleanup()
        GPIO.cleanup()

if __name__ == '__main__':
    main()
