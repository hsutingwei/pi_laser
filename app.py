from flask import Flask, render_template, Response, request, jsonify
from flask_socketio import SocketIO, emit
from modules.servo_controller import ServoController
from modules.laser_controller import LaserController
# from modules.wobble_engine import WobbleEngine # Deprecated
from modules.camera_streamer import CameraStreamer
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
try:
    with open(CONFIG_PATH, 'r') as f:
        CONFIG = json.load(f)
except Exception as e:
    print(f"Error loading config: {e}. Using defaults.")
    CONFIG = {}

# Initialize Hardware
try:
    factory = PiGPIOFactory()
except:
    print("MOCK: Could not connect to pigpio. Running in MOCK mode.")
    factory = None

servos = ServoController(factory)
laser = LaserController(factory)

# Initialize Logic Modules
calibration = CalibrationLogger('config/laser_calibration.json')
detector = MockDetector(CONFIG) 
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
    return jsonify(res)

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
    
    # We assume frame size is 640x480 (standard PiCamera)
    # If using dynamic resolution, we should fetch from camera_streamer
    FW, FH = 640, 480
    
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
    
    # Safe move (manual mode allows laser on)
    real_pan, real_tilt = servos.move_relative(d_pan, d_tilt)
    
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
            status['frame_size'] = [640, 480] # Send frame size for frontend scaling
            socketio.emit('auto_status', status)
        except Exception as e:
            print(f"Status Loop Error: {e}")
        time.sleep(0.1) # 10Hz broadcast

if __name__ == '__main__':
    # Initialize Camera HERE (Single Instance Check)
    print("Initializing Camera Streamer...")
    try:
        camera_streamer = CameraStreamer()
    except Exception as e:
        print(f"Warning: Camera init failed: {e}")
        camera_streamer = None

    # Start AutoPilot
    autopilot.start()
    
    # Start Status Broadcast
    socketio.start_background_task(background_status_thread)

    # Listen on all interfaces
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
