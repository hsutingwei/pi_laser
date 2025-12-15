from flask import Flask, render_template, Response, request, jsonify
from flask_socketio import SocketIO, emit
from modules.servo_controller import ServoController
from modules.laser_controller import LaserController
# from modules.wobble_engine import WobbleEngine # Deprecated
from modules.camera import CameraStreamer
from modules.calibration_logger import CalibrationLogger
from modules.detector import MockDetector
from modules.auto_pilot import AutoPilot
from gpiozero.pins.pigpio import PiGPIOFactory
import time
import json
import os

# --- Setup ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Load Config
CONFIG_PATH = 'config/config.json'
HARDWARE_CONFIG_PATH = 'config/hardware.json'

try:
    with open(CONFIG_PATH, 'r') as f:
        CONFIG = json.load(f)
except Exception as e:
    print(f"Error loading config: {e}. Using defaults.")
    CONFIG = {}

# Overlay Hardware Config (Git-ignored local overrides)
if os.path.exists(HARDWARE_CONFIG_PATH):
    try:
        with open(HARDWARE_CONFIG_PATH, 'r') as f:
            hw_conf = json.load(f)
            # Deep merge servos config
            if 'servos' not in CONFIG: CONFIG['servos'] = {}
            if 'servos' in hw_conf:
                for k, v in hw_conf['servos'].items():
                    CONFIG['servos'][k] = v
            print(f"Loaded Hardware Config from {HARDWARE_CONFIG_PATH}")
    except Exception as e:
        print(f"Error loading hardware config: {e}")

# Initialize Hardware
try:
    factory = PiGPIOFactory()
except:
    print("MOCK: Could not connect to pigpio. Running in MOCK mode.")
    factory = None

servos = ServoController(factory)

# Apply Limits from Config (including hardware overrides)
p_lim = CONFIG.get('servos', {}).get('pan_limits_deg', [0, 180])
t_lim = CONFIG.get('servos', {}).get('tilt_limits_deg', [0, 180])
servos.set_limits(p_lim, t_lim)

# Apply Center if defined
center = CONFIG.get('servos', {}).get('center_deg')
if center:
    servos.set_pan(center[0])
    servos.set_tilt(center[1])

laser = LaserController(factory)

# Initialize Logic Modules
calibration = CalibrationLogger('config/laser_calibration.json')

def create_detector(config):
    det_type = config.get('detector', {}).get('current', 'mock')
    
    if det_type == 'tflite':
        try:
            # Lazy Import to prevent crash if module is broken
            from modules.detector_tflite import TFLiteDetector
            
            # This might raise ImportError (missing deps) or Exception (bad model path)
            det = TFLiteDetector(config)
            print("Using TFLite Detector")
            return det
            
        except ImportError as e:
            print(f"[Warning] TFLite dependencies missing: {e}. Falling back to MOCK.")
        except Exception as e:
            print(f"[Warning] Failed to initialize TFLite: {e}. Falling back to MOCK.")
            
    # Default Fallback
    print("Using Mock Detector (Default or Fallback)")
    return MockDetector(config)

detector = create_detector(CONFIG)

autopilot = AutoPilot(CONFIG, servos, laser, detector, calibration)

# Initialize Camera Streamer - PLACEHOLDER
camera_streamer = None

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html', version=int(time.time()))

@app.route('/video_feed')
def video_feed():
    client_ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    print(f"[Video Feed] Client connected: {client_ip} ({user_agent})")
    
    def stream_generator():
        try:
            if not camera_streamer:
                while True:
                    time.sleep(1)
                    yield b''
            
            while True:
                frame = camera_streamer.get_frame()
                if frame:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                else:
                    time.sleep(0.05)
        except GeneratorExit:
            print(f"[Video Feed] Client disconnected: {client_ip}")
        except Exception as e:
            print(f"[Video Feed] Error: {e}")

    return Response(stream_generator(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- API Routes for Calibration & Mock ---
@app.route('/api/calibration/sample', methods=['POST'])
def add_sample():
    data = request.json
    x = data.get('x')
    y = data.get('y')
    s_type = data.get('type') # 'x_calib' or 'y_calib'
    
    # Capture current servo state
    pan = servos.current_pan
    tilt = servos.current_tilt
    
    calibration.add_sample(pan, tilt, x, y, s_type)
    return jsonify({"status": "ok", "pan": pan, "tilt": tilt})

@app.route('/api/calibration/fit', methods=['POST'])
def fit_calibration():
    res = calibration.fit()
    if res.get('success'):
        print(f"[Calibration] Fit succeeded: {res.get('params')}")
    else:
        print(f"[Calibration] Fit failed: {res.get('msg')}")
    return jsonify(res)

@app.route('/api/limits/set', methods=['POST'])
def set_limits():
    """
    Sets a servo limit to the CURRENT angle or a specific value.
    Payload: { "axis": "tilt", "type": "min" } -> Sets Tilt Min to current tilt
    """
    data = request.json
    axis = data.get('axis') # 'pan' or 'tilt'
    lim_type = data.get('type') # 'min' or 'max'
    
    current_val = 0
    if axis == 'pan': current_val = servos.current_pan
    elif axis == 'tilt': current_val = servos.current_tilt
    
    # Update Config Object (Memory Only - Waiting for Save)
    if 'servos' not in CONFIG: CONFIG['servos'] = {}
    
    # Get current or create default
    if axis == 'pan':
        if 'pan_limits_deg' not in CONFIG['servos']: CONFIG['servos']['pan_limits_deg'] = [0, 180]
        limits = CONFIG['servos']['pan_limits_deg']
    else:
        if 'tilt_limits_deg' not in CONFIG['servos']: CONFIG['servos']['tilt_limits_deg'] = [0, 180]
        limits = CONFIG['servos']['tilt_limits_deg']
        
    # Modify
    if lim_type == 'min': limits[0] = current_val
    elif lim_type == 'max': limits[1] = current_val
    
    # Update AutoPilot (so it respects new limits immediately)
    if autopilot:
        p_lim = CONFIG['servos'].get('pan_limits_deg', [0, 180])
        t_lim = CONFIG['servos'].get('tilt_limits_deg', [0, 180])
        autopilot.pan_limits = p_lim
        autopilot.tilt_limits = t_lim

    print(f"[Limits] Updated {axis} {lim_type} to {current_val} (Pending Save)")
    return jsonify({"status": "ok", "limits": limits, "val": current_val})

@app.route('/api/center/set', methods=['POST'])
def set_center():
    """
    Sets the current Pan/Tilt as the Mechanical Center.
    """
    pan = servos.current_pan
    tilt = servos.current_tilt
    
    if 'servos' not in CONFIG: CONFIG['servos'] = {}
    CONFIG['servos']['center_deg'] = [pan, tilt]
    
    # Apply immediately (re-center based on new center? No, Center is just a reference point usually)
    # But user might expect "Home" to be this.
    
    print(f"[Center] Updated Center to P:{pan}, T:{tilt} (Pending Save)")
    return jsonify({"status": "ok", "center": [pan, tilt]})

def save_hardware_config():
    hw_keys = ['pan_limits_deg', 'tilt_limits_deg', 'center_deg']
    hw_data = {'servos': {}}
    
    servos_conf = CONFIG.get('servos', {})
    for k in hw_keys:
        if k in servos_conf:
            hw_data['servos'][k] = servos_conf[k]
            
    with open(HARDWARE_CONFIG_PATH, 'w') as f:
        json.dump(hw_data, f, indent=4)
        
    return hw_data

@app.route('/api/config/save', methods=['POST'])
def save_config_all():
    """Saves Config (splitting Hardware vs Main) and Calibration"""
    try:
        # 1. Save Hardware Config
        hw_data = save_hardware_config()
        print("[Config] Hardware Settings saved to hardware.json")
        
        # 2. Save Main Config (Exclude Hardware Keys to avoid Git pollution)
        # We assume CONFIG has everything. We want to save everything EXCEPT hw keys to config.json
        # But wait, CONFIG structure might be complex. 
        # Deep copy is safest.
        import copy
        main_conf = copy.deepcopy(CONFIG)
        
        # Remove hardware keys from main config copy
        hw_keys = ['pan_limits_deg', 'tilt_limits_deg', 'center_deg']
        if 'servos' in main_conf:
            for k in hw_keys:
                if k in main_conf['servos']:
                    del main_conf['servos'][k]
                    
        with open(CONFIG_PATH, 'w') as f:
            json.dump(main_conf, f, indent=4)
        print("[Config] Main Settings saved to config.json (Hardware keys excluded)")
        
        # 3. Save Calibration
        calibration.save()
        print("[Calibration] Saved to disk")
        
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"[Save] Error: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/mock_detection', methods=['POST'])
def mock_detection():
    data = request.json
    # client sends: x, y, w, h, display_w, display_h
    x = data.get('x')
    y = data.get('y')
    w = data.get('w', 50) # default size if missing
    h = data.get('h', 50)
    dw = data.get('display_w')
    dh = data.get('display_h')
    
    # If using dynamic resolution, we should fetch from camera_streamer
    FW, FH = 640, 480
    if camera_streamer:
        FW, FH = camera_streamer.resolution
    
    detector.set_detection(x, y, w, h, FW, FH)
    return jsonify({"status": "ok"})

# --- WebSocket Events ---

@socketio.on('connect')
def handle_connect():
    print("Client connected")
    emit('server_status', {'msg': 'Connected to Pi Controller'})
    # Sync initial state
    emit('gimbal_state', {
        'pan': servos.current_pan, 
        'tilt': servos.current_tilt,
        'laser': laser.state,
        'mode': autopilot.state
    })

@socketio.on('joystick_control')
def handle_joystick(data):
    if autopilot.state != 'MANUAL':
        return # Ignore joystick in auto modes
    
    pan_input = data.get('pan_axis', 0.0)
    tilt_input = data.get('tilt_axis', 0.0)
    
    if abs(pan_input) < 0.1: pan_input = 0
    if abs(tilt_input) < 0.1: tilt_input = 0
    
    SPEED = 2.0 
    
    d_pan = pan_input * -SPEED # Inverted Pan
    d_tilt = tilt_input * SPEED # Inverted Tilt 
    
    # Safe move (manual mode allows laser on, and now ignores software limits for setup)
    real_pan, real_tilt = servos.move_relative(d_pan, d_tilt, ignore_limits=True)
    
    # Emit back is handled by periodic status, but fast feedback is good
    emit('gimbal_state', {'pan': real_pan, 'tilt': real_tilt})

@socketio.on('toggle_laser')
def handle_laser_toggle():
    # Emergency Intervention: If in Auto, Switch to Manual and OFF
    if autopilot.state != 'MANUAL':
        print("[Emergency] Gamepad Override: Switching to MANUAL")
        autopilot.set_mode('manual')
        laser.off()
        emit('gimbal_state', {'mode': 'manual', 'laser': False})
        return

    new_state = laser.toggle()
    emit('gimbal_state', {'laser': new_state})

@socketio.on('set_mode')
def handle_set_mode(data):
    mode = data.get('mode') # 'manual' or 'auto'
    autopilot.set_mode(mode)
    emit('gimbal_state', {'mode': autopilot.state})

# --- Background Status Loop ---
def background_status_thread():
    print("[Status Loop] Started")
    while True:
        try:
            status = autopilot.get_status()
            if camera_streamer:
                status['frame_size'] = camera_streamer.resolution
            else:
                status['frame_size'] = [640, 480]
            socketio.emit('auto_status', status)
        except Exception as e:
            print(f"Status Loop Error: {e}")
        time.sleep(0.1) # 10Hz broadcast

if __name__ == '__main__':
    # Initialize Camera HERE (Single Instance Check)
    print("Initializing Camera Streamer...")
    try:
        camera_streamer = CameraStreamer(CONFIG, detector)
        camera_streamer.start()
    except Exception as e:
        print(f"Warning: Camera init failed: {e}")
        camera_streamer = None

    # Start AutoPilot
    autopilot.start()
    
    # Start Status Broadcast
    socketio.start_background_task(background_status_thread)

    # Listen on all interfaces
    # use_reloader=False is critical to prevent double-init of threads
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
