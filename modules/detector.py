import time
import logging
import sys

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Detector")

class BaseDetector:
    """
    Abstract Base Class for Detectors.
    Interface:
    - process_frame(frame_bytes): Process a new frame (async or sync).
    - get_latest_detections(): Return list of dicts:
      [{
         'bbox': [x1, y1, x2, y2], # Pixel coordinates
         'label': str,
         'score': float
      }]
    """
    def process_frame(self, frame_bytes):
        pass

    def get_latest_detections(self):
        return []
    
    def detect(self, frame):
        # Legacy/Testing alias
        return self.get_latest_detections()

class MockDetector(BaseDetector):
    def __init__(self, config):
        self.config = config.get('detector', {}).get('mock', {})
        self.ttl = self.config.get('ttl_ms', 500) / 1000.0
        self.current_det = None
        self.last_update = 0
        logger.info("MockDetector initialized")

    def set_detection(self, x, y, w, h, fw, fh):
        """
        Triggered by UI to simulate a detection.
        Params are consistent with previous logical arguments (likely center x,y).
        """
        # Previous logic: client x,y were raw, scaled to fw/fh
        # We assume caller has handled scaling to frame coords OR we do it.
        # Let's support the existing signature usage from app.py
        
        # Logic: x,y are Center. w,h are Dimensions.
        # Convert to [x1, y1, x2, y2]
        x1 = max(0, int(x - w / 2))
        y1 = max(0, int(y - h / 2))
        x2 = min(fw, int(x + w / 2))
        y2 = min(fh, int(y + h / 2))
        
        self.current_det = {
            "bbox": [x1, y1, x2, y2],
            "label": "mock_cat",
            "score": 1.0
        }
        self.last_update = time.time()
        logger.info(f"Mock Detection Set: {self.current_det['bbox']}")

    def get_latest_detections(self):
        if self.current_det and (time.time() - self.last_update < self.ttl):
            return [self.current_det]
        return []
        
    def process_frame(self, frame):
        # Mock doesn't process frames
        pass

import os

def create_detector(config):
    det_config = config.get('detector', {})
    method = det_config.get('current') 
    
    # Auto-detect if not specified
    if not method:
        # Check if tflite model exists
        model_path = det_config.get('tflite', {}).get('model_path')
        if model_path and os.path.exists(model_path):
             logger.info(f"Auto-selecting TFLite (Model found: {model_path})")
             method = 'tflite'
        else:
             logger.info("Auto-selecting Mock (No TFLite config/model found)")
             method = 'mock'
    
    logger.info(f"Factory: Creating detector for mode '{method}'")
    
    if method == 'tflite':
        try:
            from .detector_tflite import TFLiteDetector
            return TFLiteDetector(config)
        except Exception as e:
            logger.error(f"Failed to load TFLiteDetector: {e}. Falling back to Mock.")
            # Fallthrough to mock
            
    return MockDetector(config)

