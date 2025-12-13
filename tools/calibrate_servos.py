#!/usr/bin/env python3
import sys
import os
import json
import time
import termios
import tty

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

try:
    import RPi.GPIO as GPIO
    from modules.servo_pwm import ServoPWM
except ImportError:
    print("WARNING: RPi.GPIO not found. Run this on a Raspberry Pi.")
    sys.exit(1)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '../config/calibration.json')

# --- Helper for getting single key press (Linux) ---
def getch():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Config not found at {CONFIG_PATH}, using defaults.")
        return {
            "pins": {"pan": 27, "tilt": 17},
            "pwm_hz": 50,
            "duty": {"min": 2.5, "max": 12.5},
            "pan": {"min_angle": 30, "max_angle": 150, "center": 90},
            "tilt": {"min_angle": 40, "max_angle": 120, "center": 80}
        }
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def save_config(params):
    start_time = time.time()
    with open(CONFIG_PATH, 'w') as f:
        json.dump(params, f, indent=2)
    print(f"\n[Saved] Configuration written to {CONFIG_PATH}")
    time.sleep(0.5)

def main():
    print("=== Servo Calibration Tool ===")
    print("Loading config...")
    params = load_config()
    
    pan_pin = params['pins']['pan']
    tilt_pin = params['pins']['tilt']
    
    # Initialize Servos with WIDE limits initially to allow calibration
    # We use the config's duty cycle
    duty_min = params['duty']['min']
    duty_max = params['duty']['max']
    
    try:
        pan_servo = ServoPWM(pan_pin, duty_min=duty_min, duty_max=duty_max, min_angle=0, max_angle=180)
        tilt_servo = ServoPWM(tilt_pin, duty_min=duty_min, duty_max=duty_max, min_angle=0, max_angle=180)
        
        pan_servo.attach()
        tilt_servo.attach()
        
        # Initial Position (Center from config)
        curr_pan = params['pan'].get('center', 90)
        curr_tilt = params['tilt'].get('center', 90)
        
        pan_servo.set_angle(curr_pan, settle_sec=0)
        tilt_servo.set_angle(curr_tilt, settle_sec=0)
        
    except Exception as e:
        print(f"Error initializing GPIO: {e}")
        return

    print("\nControls:")
    print("  w/s : Tilt Up/Down (+1/-1)")
    print("  a/d : Pan Left/Right (-1/+1)")
    print("  i/k : Tilt Up/Down Fast (+5/-5)")
    print("  j/l : Pan Left/Right Fast (-5/+5)")
    print("  [/] : Duty Min -/+ 0.05")
    print("  {/} : Duty Max -/+ 0.05")
    print("  1/2 : Set Pan Min/Max")
    print("  3/4 : Set Tilt Min/Max")
    print("  c   : Set Center")
    print("  p   : Save to disk")
    print("  q   : Quit")

    try:
        while True:
            # Refresh servo params if duty changed
            pan_servo.duty_min = params['duty']['min']
            pan_servo.duty_max = params['duty']['max']
            tilt_servo.duty_min = params['duty']['min']
            tilt_servo.duty_max = params['duty']['max']

            # Display Status
            print(f"\r\033[KPan: {curr_pan:>3}° | Tilt: {curr_tilt:>3}° | "
                  f"Duty: {params['duty']['min']:.2f}-{params['duty']['max']:.2f} | "
                  f"P-Lim: {params['pan']['min_angle']}-{params['pan']['max_angle']} | "
                  f"T-Lim: {params['tilt']['min_angle']}-{params['tilt']['max_angle']}", end='', flush=True)

            key = getch()
            
            # --- Pan Adjust ---
            if key == 'a': curr_pan -= 1
            if key == 'd': curr_pan += 1
            if key == 'j': curr_pan -= 5
            if key == 'l': curr_pan += 5
            
            # --- Tilt Adjust ---
            if key == 's': curr_tilt -= 1
            if key == 'w': curr_tilt += 1
            if key == 'k': curr_tilt -= 5
            if key == 'i': curr_tilt += 5
            
            # --- Duty Adjust ---
            if key == '[': params['duty']['min'] -= 0.05
            if key == ']': params['duty']['min'] += 0.05
            if key == '{': params['duty']['max'] -= 0.05
            if key == '}': params['duty']['max'] += 0.05
            
            # --- Clamp Loop Values ---
            curr_pan = max(0, min(180, curr_pan))
            curr_tilt = max(0, min(180, curr_tilt))
            
            # --- Set Limits ---
            if key == '1': 
                params['pan']['min_angle'] = curr_pan
                print(f"\n[SET] Pan Min: {curr_pan}")
            if key == '2': 
                params['pan']['max_angle'] = curr_pan
                print(f"\n[SET] Pan Max: {curr_pan}")
            if key == '3': 
                params['tilt']['min_angle'] = curr_tilt
                print(f"\n[SET] Tilt Min: {curr_tilt}")
            if key == '4': 
                params['tilt']['max_angle'] = curr_tilt
                print(f"\n[SET] Tilt Max: {curr_tilt}")
            if key == 'c':
                params['pan']['center'] = curr_pan
                params['tilt']['center'] = curr_tilt
                print(f"\n[SET] Center: {curr_pan}, {curr_tilt}")
            
            # --- Persistence ---
            if key == 'p':
                save_config(params)
                
            # --- Quit ---
            if key == 'q':
                break
                
            # Apply to servos
            pan_servo.set_angle(curr_pan, settle_sec=0)
            tilt_servo.set_angle(curr_tilt, settle_sec=0)
            
    except KeyboardInterrupt:
        pass
    finally:
        print("\nCleaning up...")
        pan_servo.cleanup()
        tilt_servo.cleanup()
        GPIO.cleanup()
        print("Done.")

if __name__ == '__main__':
    main()
