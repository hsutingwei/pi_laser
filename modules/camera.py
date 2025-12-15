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
        self.resolution = (640, 480) # Default Source of Truth

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

        try:
            with picamera.PiCamera() as camera:
                camera.resolution = (640, 480)
                camera.framerate = self.fps
                
                # Apply Rotation
                rot = self.config.get('rotation', 0)
                camera.rotation = rot
                
                time.sleep(2) # Warmup
                print(f"[Camera] PiCamera initialized. Res: {camera.resolution}, Rotation: {rot}")
                
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
        except Exception as e:
            print(f"[Camera] Hardware Error: {e}. Switching to Mock Mode.")
            self._mock_loop()

    def _mock_loop(self):
        """Fallback for non-Pi environments or broken camera config"""
        print("[Camera] Running in MOCK mode (Synthetic Video)")
        
        # Try to use PIL to generate a nice placeholder
        try:
            from PIL import Image, ImageDraw
            use_pil = True
        except ImportError:
            use_pil = False
            print("[Camera] PIL not found, using static placeholder")

        # 1x1 Black Pixel JPEG (Minimal fallback)
        fallback_frame = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x03\x02\x02\x03\x02\x02\x03\x03\x03\x03\x04\x03\x03\x04\x05\x08\x05\x05\x04\x04\x05\n\x07\x07\x06\x08\x0c\n\x0c\x0c\x0b\n\x0b\x0b\r\x0e\x12\x10\r\x0e\x11\x0e\x0b\x0b\x10\x16\x10\x11\x13\x14\x15\x15\x15\x0c\x0f\x17\x18\x16\x14\x18\x12\x14\x15\x14\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x15\x00\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xbf\x00\xff\xd9'

        w, h = 640, 480
        frame_count = 0

        while self.running:
            start_time = time.time()
            
            if use_pil:
                # Generate dynamic frame
                img = Image.new('RGB', (w, h), color=(10, 10, 10))
                d = ImageDraw.Draw(img)
                
                # Draw simple crosshair or bouncing box
                cx, cy = w//2, h//2
                d.line((cx-20, cy, cx+20, cy), fill='white')
                d.line((cx, cy-20, cx, cy+20), fill='white')
                
                # Bouncing box
                bx = (frame_count * 5) % w
                d.rectangle([bx, h-50, bx+40, h-10], outline='red', width=2)
                
                # Timestamp
                d.text((10, 10), f"NO CAMERA SIGNAL {frame_count}", fill='yellow')
                
                # Compress to JPEG
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=50)
                frame = buf.getvalue()
            else:
                frame = fallback_frame

            with self.lock:
                self.current_frame = frame
            
            # Feed Detector (even validation data needs to go to detector to prevent crashes)
            if self.detector:
                try:
                    self.detector.process_frame(frame)
                except Exception as e:
                    print(f"[Camera] Mock Detect Error: {e}")

            frame_count += 1
            elapsed = time.time() - start_time
            sleep_time = max(0, (1.0 / self.fps) - elapsed)
            time.sleep(sleep_time)
