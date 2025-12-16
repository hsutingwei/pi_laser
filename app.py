from gevent import monkey
try:
    monkey.patch_all()
    print("[System] Gevent Monkey Patched")
except ImportError:
    pass

from flask import Flask, render_template, Response, request, jsonify
from flask_socketio import SocketIO, emit
from modules.servo_controller import ServoController
from modules.laser_controller import LaserController
from modules.camera import CameraStreamer
from modules.calibration_logger import CalibrationLogger
from modules.detector import create_detector
from modules.auto_pilot import AutoPilot
from gpiozero.pins.pigpio import PiGPIOFactory
import time
import json
import os
import atexit
import signal
import sys

# --- Async Mode Selection ---
async_mode = None
try:
    import gevent
    import geventwebsocket
    async_mode = 'gevent'
except ImportError:
    async_mode = 'threading'
    print("[System] Warning: Gevent/Gevent-Websocket not found. Using Threading mode.")

print(f"[System] Async Mode: {async_mode}")

# --- Setup ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)

# Load Config
CONFIG_PATH = 'config/config.json'
HARDWARE_CONFIG_PATH = 'config/hardware.json'

try:
    with open(CONFIG_PATH, 'r') as f:
        CONFIG = json.load(f)
except Exception as e:
    print(f"Error loading config: {e}. Using defaults.")
    CONFIG = {}

# Overlay Hardware Config
if os.path.exists(HARDWARE_CONFIG_PATH):
    try:
        with open(HARDWARE_CONFIG_PATH, 'r') as f:
            hw_conf = json.load(f)
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

# Apply Limits
p_lim = CONFIG.get('servos', {}).get('pan_limits_deg', [0, 180])
t_lim = CONFIG.get('servos', {}).get('tilt_limits_deg', [0, 180])
servos.set_limits(p_lim, t_lim)

# Apply Center
center = CONFIG.get('servos', {}).get('center_deg')
if center:
    servos.set_pan(center[0])
    servos.set_tilt(center[1])

laser = LaserController(factory)

# Initialize Logic Modules
calibration = CalibrationLogger('config/laser_calibration.json')

# Create Detector (Using Factory)
detector = create_detector(CONFIG)

# AutoPilot
autopilot = AutoPilot(CONFIG, servos, laser, detector, calibration)

# Camera (Deferred Init)
camera_streamer = None

# --- Routes ---
@app.route('/')
def index():
    # Force client to update cache
    return render_template('index.html', version=int(time.time()))

@app.route('/video_feed')
def video_feed():
    def stream_generator():
        while True:
            if camera_streamer:
                frame = camera_streamer.get_frame()
                if frame:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                else:
                    time.sleep(0.05)
            else:
                time.sleep(1)
                yield b''

    return Response(stream_generator(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- API Routes ---

@app.route('/api/health')
def health():
    cam_status = camera_streamer.get_status() if camera_streamer else {"status": "uninitialized"}
    
    # Check if detector is real TFLite or Mock
    det_mode = "mock"
    if detector.__class__.__name__ == 'TFLiteDetector':
        det_mode = "tflite"

    return jsonify({
        "status": "ok",
        "camera": cam_status,
        "detector": {
            "mode": det_mode,
            "type": detector.__class__.__name__
        },
        "autopilot": autopilot.state
    })

@app.route('/api/detections')
def get_detections():
    return jsonify(detector.get_latest_detections())

@app.route('/api/calibration/sample', methods=['POST'])
def add_sample():
    data = request.json
    x = data.get('x')
    y = data.get('y')
    s_type = data.get('type')
    
    pan = servos.current_pan
    tilt = servos.current_tilt
    
    calibration.add_sample(pan, tilt, x, y, s_type)
    return jsonify({"status": "ok", "pan": pan, "tilt": tilt})

@app.route('/api/calibration/fit', methods=['POST'])
def fit_calibration():
    res = calibration.fit()
    return jsonify(res)

@app.route('/api/calibration/clear', methods=['POST'])
def clear_calibration():
    calibration.clear()
    return jsonify({"status": "ok"})

@app.route('/api/limits/set', methods=['POST'])
def set_limits():
    data = request.json
    axis = data.get('axis')
    lim_type = data.get('type')
    
    current_val = 0
    if axis == 'pan': current_val = servos.current_pan
    elif axis == 'tilt': current_val = servos.current_tilt
    
    if 'servos' not in CONFIG: CONFIG['servos'] = {}
    
    if axis == 'pan':
        if 'pan_limits_deg' not in CONFIG['servos']: CONFIG['servos']['pan_limits_deg'] = [0, 180]
        limits = CONFIG['servos']['pan_limits_deg']
    else:
        if 'tilt_limits_deg' not in CONFIG['servos']: CONFIG['servos']['tilt_limits_deg'] = [0, 180]
        limits = CONFIG['servos']['tilt_limits_deg']
        
    if lim_type == 'min': limits[0] = current_val
    elif lim_type == 'max': limits[1] = current_val
    
    if autopilot:
        autopilot.pan_limits = CONFIG['servos'].get('pan_limits_deg', [0, 180])
        autopilot.tilt_limits = CONFIG['servos'].get('tilt_limits_deg', [0, 180])

    print(f"[Limits] Updated {axis} {lim_type} to {current_val}")
    return jsonify({"status": "ok", "limits": limits, "val": current_val})

@app.route('/api/center/set', methods=['POST'])
def set_center():
    pan = servos.current_pan
    tilt = servos.current_tilt
    
    if 'servos' not in CONFIG: CONFIG['servos'] = {}
    CONFIG['servos']['center_deg'] = [pan, tilt]
    
    print(f"[Center] Updated Center to P:{pan}, T:{tilt}")
    return jsonify({"status": "ok", "center": [pan, tilt]})

@app.route('/api/config/save', methods=['POST'])
def save_config_all():
    try:
        # Save Hardware
        hw_keys = ['pan_limits_deg', 'tilt_limits_deg', 'center_deg']
        hw_data = {'servos': {}}
        servos_conf = CONFIG.get('servos', {})
        for k in hw_keys:
            if k in servos_conf:
                hw_data['servos'][k] = servos_conf[k]
        
        with open(HARDWARE_CONFIG_PATH, 'w') as f:
            json.dump(hw_data, f, indent=4)
            
        # Save Main Config (Exclude HW keys)
        import copy
        main_conf = copy.deepcopy(CONFIG)
        if 'servos' in main_conf:
            for k in hw_keys:
                if k in main_conf['servos']:
                    del main_conf['servos'][k]
                    
        with open(CONFIG_PATH, 'w') as f:
            json.dump(main_conf, f, indent=4)
        
        calibration.save()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/mock_detection', methods=['POST'])
def mock_detection():
    data = request.json
    x = data.get('x')
    y = data.get('y')
    w = data.get('w', 50)
    h = data.get('h', 50)
    
    FW, FH = 640, 480
    if camera_streamer:
        FW, FH = camera_streamer.resolution
    
    if hasattr(detector, 'set_detection'):
        detector.set_detection(x, y, w, h, FW, FH)
        return jsonify({"status": "ok"})
    else:
        return jsonify({"status": "error", "msg": "Detector does not support simulation"}), 400

# --- WebSocket Events ---
@socketio.on('connect')
def handle_connect():
    emit('gimbal_state', {
        'pan': servos.current_pan, 
        'tilt': servos.current_tilt,
        'laser': laser.state,
        'mode': autopilot.state
    })

@socketio.on('joystick_control')
def handle_joystick(data):
    if autopilot.state != 'MANUAL': return
    
    pan_input = data.get('pan_axis', 0.0)
    tilt_input = data.get('tilt_axis', 0.0)
    
    if abs(pan_input) < 0.1: pan_input = 0
    if abs(tilt_input) < 0.1: tilt_input = 0
    
    SPEED = 2.0 
    d_pan = pan_input * -SPEED 
    d_tilt = tilt_input * SPEED 
    
    real_pan, real_tilt = servos.move_relative(d_pan, d_tilt, ignore_limits=True)
    emit('gimbal_state', {'pan': real_pan, 'tilt': real_tilt})

@socketio.on('toggle_laser')
def handle_laser_toggle():
    if autopilot.state != 'MANUAL':
        autopilot.set_mode('manual')
        laser.off()
        emit('gimbal_state', {'mode': 'manual', 'laser': False})
        return

    new_state = laser.toggle()
    emit('gimbal_state', {'laser': new_state})

@socketio.on('set_mode')
def handle_set_mode(data):
    mode = data.get('mode')
    autopilot.set_mode(mode)
    emit('gimbal_state', {'mode': autopilot.state})

# --- Background Status Loop ---
def background_status_thread():
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
        time.sleep(0.1) 

def cleanup():
    print("Cleaning up...")
    if camera_streamer: camera_streamer.stop()
    if autopilot: autopilot.stop()
    if laser: laser.off()
    if servos: servos.detach()

atexit.register(cleanup)
signal.signal(signal.SIGTERM, lambda num, frame: sys.exit(0))
signal.signal(signal.SIGINT, lambda num, frame: sys.exit(0))

if __name__ == '__main__':
    print("Initializing Camera Streamer...")
    try:
        camera_streamer = CameraStreamer(CONFIG, detector)
        camera_streamer.start()
    except Exception as e:
        print(f"Warning: Camera init failed: {e}")
        camera_streamer = None

    autopilot.start()
    socketio.start_background_task(background_status_thread)
    
    # Run
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
