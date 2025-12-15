import time
import io
import threading
import logging

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Camera")

try:
    import picamera
except ImportError:
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
        self.resolution = (640, 480) 
        
        # Status
        self.frame_count = 0
        self.start_time = 0
        self.backend = 'none' # picamera, mock
        self.error_msg = None

    def start(self):
        if self.running: return
        self.running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        logger.info("Camera Streamer Thread Started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info("Camera Streamer Stopped")

    def get_frame(self):
        with self.lock:
            return self.current_frame

    def get_status(self):
        elapsed = time.time() - self.start_time
        fps = self.frame_count / elapsed if elapsed > 0 else 0
        return {
            "backend": self.backend,
            "fps": round(fps, 1),
            "frames": self.frame_count,
            "error": self.error_msg
        }

    def _capture_loop(self):
        if picamera:
            try:
                self.backend = 'picamera'
                logger.info("Attempting to initialize PiCamera...")
                self._picamera_loop()
            except Exception as e:
                self.error_msg = str(e)
                logger.error(f"PiCamera Critical Error: {e}. Fallback to Mock.")
                self.backend = 'mock'
                self._mock_loop()
        else:
            self.backend = 'mock'
            logger.warning("PiCamera library not found. Using Mock.")
            self._mock_loop()

    def _picamera_loop(self):
        # We must protect the 'with' block
        # If PiCamera() hangs, this thread hangs. 
        # App continues but stream is dead.
        with picamera.PiCamera() as camera:
            camera.resolution = (640, 480)
            camera.framerate = self.fps
            rot = self.config.get('rotation', 0)
            camera.rotation = rot
            
            logger.info("PiCamera Warming up (2s)...")
            time.sleep(2) 
            logger.info(f"PiCamera Running. Res: {camera.resolution}")
            
            self.resolution = camera.resolution
            stream = io.BytesIO()
            
            for _ in camera.capture_continuous(stream, 'jpeg', use_video_port=True):
                if not self.running: break
                
                stream.seek(0)
                frame = stream.read()
                
                with self.lock:
                    self.current_frame = frame
                
                if self.detector:
                    stream.seek(0)
                    self.detector.process_frame(stream)
                
                stream.seek(0)
                stream.truncate()
                self.frame_count += 1

    def _mock_loop(self):
        """Fallback for non-Pi environments"""
        logger.info("Entering Mock Camera Loop")
        
        # Try to use PIL
        try:
            from PIL import Image, ImageDraw
            use_pil = True
        except ImportError:
            use_pil = False
            logger.warning("PIL not found. Using static mock frame.")

        fallback_frame = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x03\x02\x02\x03\x02\x02\x03\x03\x03\x03\x04\x03\x03\x04\x05\x08\x05\x05\x04\x04\x05\n\x07\x07\x06\x08\x0c\n\x0c\x0c\x0b\n\x0b\x0b\r\x0e\x12\x10\r\x0e\x11\x0e\x0b\x0b\x10\x16\x10\x11\x13\x14\x15\x15\x15\x0c\x0f\x17\x18\x16\x14\x18\x12\x14\x15\x14\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x15\x00\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xbf\x00\xff\xd9'

        w, h = 640, 480
        
        while self.running:
            start_t = time.time()
            
            if use_pil:
                img = Image.new('RGB', (w, h), color=(20, 20, 20))
                d = ImageDraw.Draw(img)
                cx, cy = w//2, h//2
                d.line((cx-20, cy, cx+20, cy), fill='white')
                d.line((cx, cy-20, cx, cy+20), fill='white')
                
                # Moving box
                bx = (self.frame_count * 10) % w
                d.rectangle([bx, h-50, bx+40, h-10], outline='cyan', width=2)
                d.text((10, 10), f"MOCK CAMERA: {self.frame_count}", fill='yellow')
                
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=40)
                frame = buf.getvalue()
            else:
                frame = fallback_frame

            with self.lock:
                self.current_frame = frame
            
            # Important: Feed detector even in mock
            if self.detector:
                try:
                    self.detector.process_frame(frame)
                except Exception:
                    pass

            self.frame_count += 1
            
            # FPS Sleep
            elapsed = time.time() - start_t
            delay = max(0, (1.0 / self.fps) - elapsed)
            time.sleep(delay)
