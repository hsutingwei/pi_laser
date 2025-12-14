import time
import io
import threading
try:
    import picamera
except ImportError:
    print("[Camera] picamera not found, using MockCamera")
    picamera = None

class CameraStreamer:
    def __init__(self, config_data, detector=None):
        self.config = config_data.get('camera', {})
        self.detector = detector
        self.fps = self.config.get('stream_fps_cap', 15)
        self.running = False
        self.thread = None
        self.current_frame = None
        self.lock = threading.Lock()

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print("[Camera] Streamer Started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        print("[Camera] Streamer Stopped")

    def get_frame(self):
        with self.lock:
            return self.current_frame

    def _capture_loop(self):
        if not picamera:
            self._mock_loop()
            return

        with picamera.PiCamera() as camera:
            camera.resolution = (640, 480)
            camera.framerate = self.fps
            time.sleep(2) # Warmup
            
            stream = io.BytesIO()
            for _ in camera.capture_continuous(stream, 'jpeg', use_video_port=True):
                if not self.running:
                    break
                
                # Get bytes
                stream.seek(0)
                frame = stream.read()
                
                # Update shared frame
                with self.lock:
                    self.current_frame = frame
                
                # Run Detection
                if self.detector:
                    # We pass the rewinded stream bytes
                    stream.seek(0)
                    self.detector.process_frame(stream)
                
                # Reset stream
                stream.seek(0)
                stream.truncate()

    def _mock_loop(self):
        """Fallback for non-Pi environments"""
        while self.running:
            time.sleep(1.0 / self.fps)
            # Create a black image or noise
            # For now, just None or dummy bytes is fine to prevent crash, 
            # but visual debugging needs something.
            # Let's generate a tiny valid JPEG? No, too complex.
            # Just keep current_frame as None or static placeholder.
            pass
