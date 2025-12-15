import time

class BaseDetector:
    def process_frame(self, frame):
        """Run inference on frame and update internal state."""
        pass

    def get_latest_detections(self):
        """Return latest cached detections."""
        return []

    def detect(self, frame):
        """Legacy alias: Returns latest detections (ignores frame)."""
        return self.get_latest_detections()

class MockDetector(BaseDetector):
    def __init__(self, config):
        self.ttl_ms = config.get('mock', {}).get('ttl_ms', 500)
        self.current_bbox = None
        self.last_detection_time = 0
        self.frame_count = 0

    def set_detection(self, client_x, client_y, client_w, client_h, frame_w, frame_h):
        """
        Receive a simulated detection from frontend (click).
        Convert client coordinates to frame coordinates.
        """
        if client_w <= 0 or client_h <= 0:
            return 

        scale_x = frame_w / client_w
        scale_y = frame_h / client_h
        
        # Center the bbox on the click
        bbox_w = int(50 * scale_x) # Arbitrary mock size (e.g. 50px simulated cat)
        bbox_h = int(50 * scale_y)
        
        center_x = int(client_x * scale_x)
        center_y = int(client_y * scale_y)
        
        x = max(0, center_x - bbox_w // 2)
        y = max(0, center_y - bbox_h // 2)
        
        self.current_bbox = [x, y, bbox_w, bbox_h]
        self.last_detection_time = time.time()
        print(f"[MockDetector] Set bbox at ({x}, {y}) for {self.ttl_ms}ms")

    def process_frame(self, frame):
        self.frame_count += 1
        if self.frame_count % 30 == 0:
             print(f"[MockDetector] Heartbeat: Frame {self.frame_count} (Mock Mode)")

    def get_latest_detections(self):
        """
        Return current bbox if within TTL.
        """
        if not self.current_bbox:
            return []

        # Check TTL
        if (time.time() - self.last_detection_time) * 1000 > self.ttl_ms:
            self.current_bbox = None
            return []

        return [{
            "bbox": self.current_bbox,
            "label": "mock_cat",
            "score": 1.0
        }]
