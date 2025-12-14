import io
import time
import threading
from picamera import PiCamera

class CameraStreamer:
    """
    Background thread that captures frames from PiCamera
    and stores the latest frame in memory for clients to retrieve.
    """
    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._capture_thread)
        self.thread.daemon = True
        self.thread.start()

    def _capture_thread(self):
        # Initialize PiCamera
        # Note: PiCamera cannot be opened more than once.
        # This class should be instantiated only once in the app.
        print("📷 Starting PiCamera Streamer...")
        try:
            with PiCamera() as camera:
                camera.resolution = (640, 480)
                camera.rotation = 90 # Correcting to 90 based on user feedback
                camera.framerate = 15 # Reduced from 24 to save bandwidth for iPad
                # Warmup
                time.sleep(2.0)
                
                stream = io.BytesIO()
                # Use 'use_video_port=True' for faster capture
                for _ in camera.capture_continuous(stream, 'jpeg', use_video_port=True):
                    if not self.running:
                        break
                    
                    # Store current frame
                    stream.seek(0)
                    with self.lock:
                        self.frame = stream.read()
                    
                    # Reset stream for next frame
                    stream.seek(0)
                    stream.truncate()
        except Exception as e:
            print(f"❌ Camera Error: {e}")
            self.running = False

    def get_frame(self):
        """Return the latest frame in bytes, or None if not ready"""
        with self.lock:
            return self.frame

    def stop(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)
