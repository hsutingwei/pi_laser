import time
import logging
import platform
import io

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
            raise ImportError(f"Missing dependencies for TFLiteDetector: {', '.join(missing_deps)}")

        self.config = config.get('detector', {}).get('tflite', {})
        self.labels_path = self.config.get('labels_path')
        self.threshold = self.config.get('threshold', 0.5)
        
        # Paths
        self.model_path_cpu = self.config.get('model_path')
        self.model_path_tpu = self.config.get('model_path_tpu')
        self.delegate_path = self.config.get('edgetpu_delegate', 'libedgetpu.so.1')
        
        # Backend Config
        self.backend = self.config.get('backend', 'cpu') # 'cpu' or 'tpu'
        self.fallback = self.config.get('fallback_backend', 'cpu')
        
        # Throttling
        self.inference_fps = self.config.get('inference_fps', 10)
        self.min_interval = 1.0 / self.inference_fps
        self.last_inference_time = 0
        
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
            print(f"[TFLite] Loaded {len(self.labels)} labels.")
            
            # Label Check
            target_classes = self.config.get('target_classes', [])
            print(f"[TFLite] Target Classes: {target_classes}")
            
            # Check for 'cat'
            has_cat = any('cat' in val.lower() for val in self.labels.values())
            if not has_cat:
                print("[TFLite] WARNING: 'cat' not found in labels! Detection might fail.")
                
            # Backend Selection
            if self.backend == 'tpu':
                try:
                    self._load_tpu_model()
                    print(f"[TFLite] SUCCESS: TPU Backend initialized. Model: {self.model_path_tpu}")
                    return
                except Exception as e:
                    print(f"[TFLite] TPU init failed: {e}. Trying fallback...")
                    if self.fallback == 'cpu':
                        self.backend = 'cpu'
                        print("[TFLite] Falling back to CPU.")
                    elif self.fallback == 'mock':
                        print("[TFLite] Falling back to MOCK (Upstream handle).")
                        raise Exception("TPU Failed, Fallback Mock")
                    else:
                        raise e

            if self.backend == 'cpu':
                self._load_cpu_model()
                print(f"[TFLite] SUCCESS: CPU Backend initialized. Model: {self.model_path_cpu}")

        except Exception as e:
            print(f"[TFLite] Init Fatal Error: {e}")
            raise e

    def _load_tpu_model(self):
        if not self.model_path_tpu:
            raise ValueError("model_path_tpu not defined")
        
        print(f"[TFLite] Loading TPU Delegate: {self.delegate_path}")
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

    def load_labels(self, path):
        if not path: return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                # Filter removes empty lines
                return {i: line.strip() for i, line in enumerate(f.readlines()) if line.strip()}
        except Exception as e:
            print(f"[TFLite] Label load error: {e}")
            return {}

    def get_latest_detections(self):
        return self.latest_detections

    def process_frame(self, frame_bytes):
        """
        Run inference. Throttled.
        frame_bytes: bytes or io.BytesIO
        """
        if not self.interpreter: return

        # Throttling
        now = time.time()
        if now - self.last_inference_time < self.min_interval:
            return 
        self.last_inference_time = now

        try:
            # Decode Frame
            if isinstance(frame_bytes, bytes):
                stream = io.BytesIO(frame_bytes)
            else:
                stream = frame_bytes # Assume file-like
            
            image = Image.open(stream)
            img_resized = image.resize((self.width, self.height))
            input_data = np.expand_dims(img_resized, axis=0)

            # Normalize (assuming Float model needs -1..1 or 0..1 depending on meta? 
            # Usually MobileNet is 0-255 uint8 or -1..1 float.
            # Config doesn't specify mean/std. Assuming simple -1..1 for float, 0..255 for Quantized.
            if self.input_details[0]['dtype'] == np.float32:
                input_data = (np.float32(input_data) - 127.5) / 127.5
            
            self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
            self.interpreter.invoke()

            # Parse Output
            # COCO SSD usually: [boxes, classes, scores, count]
            boxes = self.interpreter.get_tensor(self.output_details[0]['index'])[0]
            classes = self.interpreter.get_tensor(self.output_details[1]['index'])[0]
            scores = self.interpreter.get_tensor(self.output_details[2]['index'])[0]
            
            detections = []
            orig_w, orig_h = image.size
            target_classes = self.config.get('target_classes', [])

            for i in range(len(scores)):
                score = float(scores[i])
                if score >= self.threshold:
                    ymin, xmin, ymax, xmax = boxes[i]
                    
                    left = int(max(0, xmin * orig_w))
                    top = int(max(0, ymin * orig_h))
                    right = int(min(orig_w, xmax * orig_w))
                    bottom = int(min(orig_h, ymax * orig_h))
                    
                    class_id = int(classes[i])
                    label = self.labels.get(class_id, "unknown")
                    
                    # Filter
                    if target_classes and label not in target_classes:
                        continue
                    
                    # New Standard Format
                    detections.append({
                        "bbox": [left, top, right - left, bottom - top], # [x, y, w, h]
                        "label": label,
                        "score": score
                    })
            
            self.latest_detections = detections
                    
        except Exception as e:
            print(f"[TFLite] Inference Error: {e}")
            # On error, maybe keep old detections or clear?
            # self.latest_detections = [] # Clearing is safer
            pass

