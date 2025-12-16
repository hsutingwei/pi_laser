import time
import logging
import os
import sys

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Detector")

class BaseDetector:
    """
    Abstract Base Class for Detectors.
    Interface:
    - process_frame(frame_bytes): Process a new frame (async output update).
    - get_latest_detections(): Return list of dicts: [{'bbox':[x1,y1,x2,y2], 'label':str, 'score':float}]
    - status(): Return dict for health check.
    """
    def process_frame(self, frame_bytes):
        pass

    def get_latest_detections(self):
        return []
    
    def status(self):
        return {"mode": "base", "ready": False}

class MockDetector(BaseDetector):
    def __init__(self, config):
        self.config = config.get('detector', {}).get('mock', {})
        self.ttl = self.config.get('ttl_ms', 500) / 1000.0
        self.current_det = None
        self.last_update = 0
        logger.info("MockDetector initialized")

    def set_detection(self, x, y, w, h, fw, fh):
        """Simulate detection logic."""
        # x,y are Center. w,h are Dimensions.
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
        
    def status(self):
        return {
            "mode": "mock",
            "ready": True,
            "last_update": self.last_update
        }

def create_detector(config):
    det_config = config.get('detector', {})
    method = det_config.get('current') 
    
    # Auto-detect logic
    if not method:
        model_path = det_config.get('tflite', {}).get('model_path')
        if model_path and os.path.exists(model_path):
             logger.info(f"Auto-selecting TFLite (Model found: {model_path})")
             method = 'tflite'
        else:
             if model_path:
                 logger.warning(f"Model path {model_path} implies TFLite, but file not found. Fallback to Mock.")
             else:
                 logger.info("No model path configured. Using Mock.")
             method = 'mock'
    
    logger.info(f"Factory: Creating detector for mode '{method}'")
    
    if method == 'tflite':
        try:
            from .detector_tflite import TFLiteDetector
            logger.info("Attempting TFLite Init...")
            return TFLiteDetector(config)
        except Exception as e:
            logger.error(f"TFLite Init Failed: {e}. Fallback to Mock.")
            # Fallthrough intentionally
            
    return MockDetector(config)

