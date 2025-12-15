import time
import logging
import platform

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
        self._load_interpreter()
            
    def _load_interpreter(self):
        # 1. Try Loading Labels
        try:
            self.labels = self.load_labels(self.labels_path)
        except Exception as e:
            print(f"[TFLite] Error loading labels: {e}")
            raise e

        # 2. Try Loading Model (TPU First if requested)
        if self.backend == 'tpu':
            try:
                self._load_tpu_model()
                print(f"[TFLite] Initialized TPU Backend using {self.model_path_tpu}")
                return
            except Exception as e:
                print(f"[TFLite] TPU init failed: {e}. Checking fallback...")
                if self.fallback == 'cpu':
                    self.backend = 'cpu'
                    print("[TFLite] Falling back to CPU backend")
                elif self.fallback == 'mock':
                    raise Exception("TPU failed and fallback is mock")
                else:
                    raise e # No fallback defined or unknown
        
        # 3. Load CPU Model (If requested or fell back)
        if self.backend == 'cpu':
            try:
                self._load_cpu_model()
                print(f"[TFLite] Initialized CPU Backend using {self.model_path_cpu}")
            except Exception as e:
                print(f"[TFLite] CPU init failed: {e}")
                raise e

    def _load_tpu_model(self):
        if not self.model_path_tpu:
            raise ValueError("model_path_tpu not defined in config")
        
        print(f"[TFLite] Loading TPU Delegate: {self.delegate_path}")
        try:
            delegate = tflite.load_delegate(self.delegate_path)
            self.interpreter = tflite.Interpreter(
                model_path=self.model_path_tpu,
                experimental_delegates=[delegate]
            )
            self._allocate()
        except Exception as e:
            # Re-raise to trigger fallback
            raise e

    def _load_cpu_model(self):
        if not self.model_path_cpu:
            raise ValueError("model_path (CPU) not defined in config")
        
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
        with open(path, 'r', encoding='utf-8') as f:
            return {i: line.strip() for i, line in enumerate(f.readlines())}

    def get_latest_detections(self):
        return self.latest_detections

    def process_frame(self, frame_bytes):
        """
        Run inference on a single frame. Throttled by FPS limit.
        """
        if not self.interpreter:
            return

        # Throttling
        now = time.time()
        if now - self.last_inference_time < self.min_interval:
            return # Skip frame
        self.last_inference_time = now

        try:
            # Preprocess
            image = Image.open(frame_bytes)
            img_resized = image.resize((self.width, self.height))
            input_data = np.expand_dims(img_resized, axis=0)

            # Normalize if Float model
            if self.input_details[0]['dtype'] == np.float32:
                input_data = (np.float32(input_data) - 127.5) / 127.5
            
            # Inference
            self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
            self.interpreter.invoke()

            # Results
            boxes = self.interpreter.get_tensor(self.output_details[0]['index'])[0]
            classes = self.interpreter.get_tensor(self.output_details[1]['index'])[0]
            scores = self.interpreter.get_tensor(self.output_details[2]['index'])[0]
            
            detections = []
            orig_w, orig_h = image.size
            
            target_classes = self.config.get('target_classes', [])

            for i in range(len(scores)):
                if scores[i] >= self.threshold:
                    ymin, xmin, ymax, xmax = boxes[i]
                    
                    left = int(xmin * orig_w)
                    top = int(ymin * orig_h)
                    right = int(xmax * orig_w)
                    bottom = int(ymax * orig_h)
                    
                    class_id = int(classes[i])
                    label = self.labels.get(class_id, "unknown")
                    
                    if target_classes and label not in target_classes:
                        continue
                    
                    detections.append({
                        "x": left,
                        "y": top,
                        "w": right - left,
                        "h": bottom - top,
                        "class": label,
                        "score": float(scores[i])
                    })
            
            self.latest_detections = detections
                    
        except Exception as e:
            print(f"[TFLite] Inference Error: {e}")
            # Don't clear detections on error, just keep old ones?
            # Or clear to indicate failure?
            # Usually keep old is safer to prevent flickering, but might be stuck.
            # Lets clear to be safe.
            self.latest_detections = []
