from flask import Flask, render_template, Response
from flask_socketio import SocketIO, emit
from modules.servo_controller import ServoController
from modules.laser_controller import LaserController
from modules.wobble_engine import WobbleEngine
from modules.camera_streamer import CameraStreamer
from gpiozero.pins.pigpio import PiGPIOFactory
import time

# --- Setup ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize Hardware
try:
    factory = PiGPIOFactory()
except:
    print("MOCK: Could not connect to pigpio. Running in MOCK mode.")
    factory = None

servos = ServoController(factory)
laser = LaserController(factory)
wobble = WobbleEngine(servos)

# Initialize Camera Streamer - PLACEHOLDER
# Actual initialization happens in __main__ to avoid double-open by reloader
camera_streamer = None

# State
APP_STATE = {
    "mode": "manual", # or "auto" (wobble)
    "laser": False
}

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

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

# --- WebSocket Events ---

@socketio.on('connect')
def handle_connect():
    print("Client connected")
    emit('server_status', {'msg': 'Connected to Pi Controller'})
    # Sync state
    emit('gimbal_state', {
        'pan': servos.current_pan, 
        'tilt': servos.current_tilt,
        'laser': laser.state,
        'mode': APP_STATE['mode']
    })

@socketio.on('joystick_control')
def handle_joystick(data):
    print(f"[DEBUG] Joystick Event Received: {data}") # Debug Log
    if APP_STATE['mode'] != 'manual':
        print(f"[DEBUG] Ignored: Mode is {APP_STATE['mode']}")
        return # Ignore joystick in auto mode

    # Data: {'pan': float (-1~1), 'tilt': float (-1~1)}
    # Rate Control
    
    pan_input = data.get('pan_axis', 0.0)
    tilt_input = data.get('tilt_axis', 0.0)
    
    # Deadzone
    if abs(pan_input) < 0.1: pan_input = 0
    if abs(tilt_input) < 0.1: tilt_input = 0
    
    # Speed factor (degrees per tick)
    SPEED = 2.0 
    
    d_pan = pan_input * -SPEED # Inverted Pan
    d_tilt = tilt_input * SPEED # Inverted Tilt 
    
    real_pan, real_tilt = servos.move_relative(d_pan, d_tilt)
    
    # Emit back for UI update
    emit('gimbal_state', {'pan': real_pan, 'tilt': real_tilt})

@socketio.on('toggle_laser')
def handle_laser_toggle():
    new_state = laser.toggle()
    emit('gimbal_state', {'laser': new_state})

@socketio.on('toggle_wobble')
def handle_wobble_toggle():
    if APP_STATE['mode'] == 'manual':
        APP_STATE['mode'] = 'auto'
        wobble.start(pattern="circle") # Default to circle
    else:
        APP_STATE['mode'] = 'manual'
        wobble.stop()
    
    emit('gimbal_state', {'mode': APP_STATE['mode']})

@socketio.on('set_mode')
def handle_set_mode(data):
    mode = data.get('mode')
    if mode == 'auto':
        APP_STATE['mode'] = 'auto'
        wobble.start(pattern="random")
    else:
        APP_STATE['mode'] = 'manual'
        wobble.stop()
    emit('gimbal_state', {'mode': APP_STATE['mode']})

if __name__ == '__main__':
    # Initialize Camera HERE (Single Instance Check)
    print("Initializing Camera Streamer...")
    try:
        camera_streamer = CameraStreamer()
    except Exception as e:
        print(f"Warning: Camera init failed: {e}")
        camera_streamer = None

    # Listen on all interfaces
    # CRITICAL: debug=False, use_reloader=False to prevent ENOSPC (double cam init)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
