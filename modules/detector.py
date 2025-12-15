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

    # ... set_detection ...

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
