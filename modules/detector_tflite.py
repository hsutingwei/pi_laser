import time
import logging
import io
import platform

logger = logging.getLogger(__name__)

available = True
missing_deps = []

try:
    import numpy as np
except ImportError:
    available = False
    missing_deps.append('numpy')
    np = None

try:
    from PIL import Image
except ImportError:
    available = False
    missing_deps.append('Pillow')
    Image = None

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    try:
        import tensorflow.lite as tflite
    except ImportError:
        available = False
        missing_deps.append('tflite_runtime')
        tflite = None

from .detector import BaseDetector

class TFLiteDetector(BaseDetector):
    def __init__(self, config):
        if not available:
            raise ImportError(f"Missing dependencies: {', '.join(missing_deps)}")

        self.config = config.get('detector', {}).get('tflite', {})
        self.labels_path = self.config.get('labels_path')
        self.threshold = self.config.get('threshold', 0.5)
        
        # Paths
        self.model_path_cpu = self.config.get('model_path')
        self.model_path_tpu = self.config.get('model_path_tpu')
        self.delegate_path = self.config.get('edgetpu_delegate', 'libedgetpu.so.1')
        
        # Backend Config
        self.backend = self.config.get('backend', 'cpu') 
        self.fallback = self.config.get('fallback_backend', 'cpu')
        
        # Throttling
        self.inference_fps = self.config.get('inference_fps', 10)
        self.min_interval = 1.0 / self.inference_fps
        self.last_inference_time = 0
        
        # Stats
        self.inference_ms = 0.0
        self.frame_count = 0
        
        self.labels = {}
        self.interpreter = None
        self.input_details = None
        self.output_details = None
        self.height = 300
        self.width = 300
        
        self.latest_detections = []
        
        # Initialize
        self._load_interpreter_safe()
            
    def _load_interpreter_safe(self):
        try:
            self.labels = self.load_labels(self.labels_path)
            logger.info(f"Loaded {len(self.labels)} labels.")
            
            # Label Check
            target_classes = self.config.get('target_classes', [])
            has_cat = any('cat' in val.lower() for val in self.labels.values())
            if not has_cat:
                logger.warning("'cat' not found in labels!")

            # Backend Selection
            if self.backend == 'tpu':
                try:
                    self._load_tpu_model()
                    logger.info(f"Initialized TPU Backend: {self.model_path_tpu}")
                    return
                except Exception as e:
                    logger.error(f"TPU init failed: {e}. Fallback to {self.fallback}")
                    if self.fallback == 'cpu':
                        self.backend = 'cpu'
                        # Fall through to cpu
                    else:
                        raise e

            if self.backend == 'cpu':
                self._load_cpu_model()
                logger.info(f"Initialized CPU Backend: {self.model_path_cpu}")

        except Exception as e:
            logger.critical(f"TFLite Init Fatal Error: {e}")
            raise e

    def _load_tpu_model(self):
        if not self.model_path_tpu:
             raise ValueError("model_path_tpu not defined")
        
        logger.info(f"Loading TPU Delegate: {self.delegate_path}")
        delegate = tflite.load_delegate(self.delegate_path)
        self.interpreter = tflite.Interpreter(
            model_path=self.model_path_tpu,
            experimental_delegates=[delegate]
        )
        self._allocate()

    def _load_cpu_model(self):
        if not self.model_path_cpu:
            raise ValueError("model_path (CPU) not defined")
        self.interpreter = tflite.Interpreter(model_path=self.model_path_cpu)
        self._allocate()
        
    def _allocate(self):
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.height = self.input_details[0]['shape'][1]
        self.width = self.input_details[0]['shape'][2]
        self.manual_detections = [] # Init storage

    def load_labels(self, path):
        if not path: return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return {i: line.strip() for i, line in enumerate(f.readlines()) if line.strip()}
        except Exception as e:
            logger.error(f"Label load error: {e}")
            return {}
            
    def status(self):
        return {
            "mode": "tflite",
            "backend": self.backend,
            "last_inference_ms": round(self.inference_ms, 1),
            "ready": True
        }

    def get_latest_detections(self):
        # Merge inference and manual
        res = list(self.latest_detections)
        
        # Add manual if valid (TTL 1s)
        if self.manual_detections:
            valid = []
            for d in self.manual_detections:
                if time.time() - d['ts'] < 1.0:
                    valid.append(d)
            self.manual_detections = valid
            res.extend(valid)
            
        return res

    def process_frame(self, frame_bytes):
        if not self.interpreter: return

        # Throttling
        now = time.time()
        if now - self.last_inference_time < self.min_interval:
            return 
        self.last_inference_time = now
        
        self.frame_count += 1
        start_time = time.time()

        try:
            # Decode & Preprocess
            if isinstance(frame_bytes, bytes):
                stream = io.BytesIO(frame_bytes)
            else:
                stream = frame_bytes 
            
            image = Image.open(stream).convert('RGB')
            img_resized = image.resize((self.width, self.height), Image.BILINEAR)
            
            input_dtype = self.input_details[0]['dtype']
            input_data = np.expand_dims(np.array(img_resized, dtype=input_dtype), axis=0)

            # Normalize (Float models usually -1..1)
            if input_dtype == np.float32:
                input_data = (input_data - 127.5) / 127.5
            
            # Inference
            self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
            self.interpreter.invoke()

            # Parse Output
            boxes = self.interpreter.get_tensor(self.output_details[0]['index'])[0]
            classes = self.interpreter.get_tensor(self.output_details[1]['index'])[0]
            scores = self.interpreter.get_tensor(self.output_details[2]['index'])[0]
            
            detections = []
            orig_w, orig_h = image.size
            target_classes = [t.lower() for t in self.config.get('target_classes', [])]

            for i in range(len(scores)):
                score = float(scores[i])
                if score >= self.threshold:
                    ymin, xmin, ymax, xmax = boxes[i]
                    
                    # Convert to [x1, y1, x2, y2]
                    left = int(max(0, xmin * orig_w))
                    top = int(max(0, ymin * orig_h))
                    right = int(min(orig_w, xmax * orig_w))
                    bottom = int(min(orig_h, ymax * orig_h))
                    
                    class_id = int(classes[i])
                    label = self.labels.get(class_id, "unknown")
                    
                    if target_classes and label.lower() not in target_classes:
                        continue
                    
                    detections.append({
                        "bbox": [left, top, right, bottom], # [x1, y1, x2, y2]
                        "label": label,
                        "score": score
                    })
            
            self.latest_detections = detections
            self.inference_ms = (time.time() - start_time) * 1000
            
            if self.frame_count % 30 == 0:
                logger.info(f"Inf: {self.inference_ms:.1f}ms | Dets: {len(detections)}")
                    
        except Exception as e:
            logger.error(f"Inference Error: {e}")
            self.latest_detections = []


