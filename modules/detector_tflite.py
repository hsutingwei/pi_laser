import time
import logging

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
        self.model_path = self.config.get('model_path')
        self.labels_path = self.config.get('labels_path')
        self.threshold = self.config.get('threshold', 0.5)
        self.labels = {}
        
        self.interpreter = None
        self.input_details = None
        self.output_details = None
        self.height = 300
        self.width = 300
        
        self.latest_detections = []
        
        if self.model_path:
            self.load_model()
            
    def load_model(self):
        try:
            print(f"[TFLite] Loading model: {self.model_path}")
            self.labels = self.load_labels(self.labels_path)
            
            self.interpreter = tflite.Interpreter(model_path=self.model_path)
            self.interpreter.allocate_tensors()
            
            self.input_details = self.interpreter.get_input_details()
            self.output_details = self.interpreter.get_output_details()
            
            self.height = self.input_details[0]['shape'][1]
            self.width = self.input_details[0]['shape'][2]
            
            print(f"[TFLite] Model loaded. Input Shape: {self.width}x{self.height}")
        except Exception as e:
            print(f"[TFLite] Error loading model: {e}")
            raise e

    def load_labels(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return {i: line.strip() for i, line in enumerate(f.readlines())}

    def get_latest_detections(self):
        return self.latest_detections

    def process_frame(self, frame_bytes):
        """
        Run inference on a single frame (JPEG bytes or PIL Image).
        Updates self.latest_detections.
        """
        if not self.interpreter:
            return

        try:
            # Preprocess Image
            img = Image.open(frame_bytes)
            img_resized = img.resize((self.width, self.height))
            input_data = np.expand_dims(img_resized, axis=0)

            # Floating point models require normalization? MobileNet V1 Quant is uint8 usually.
            # Let's check dtype.
            if self.input_details[0]['dtype'] == np.float32:
                input_data = (np.float32(input_data) - 127.5) / 127.5
            
            self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
            self.interpreter.invoke()

            # Retrieve Results
            boxes = self.interpreter.get_tensor(self.output_details[0]['index'])[0]
            classes = self.interpreter.get_tensor(self.output_details[1]['index'])[0]
            scores = self.interpreter.get_tensor(self.output_details[2]['index'])[0]
            
            detections = []
            
            # Map back to original frame size
            orig_w, orig_h = img.size
            
            target_classes = self.config.get('target_classes', ['cat', 'person', 'dog'])

            for i in range(len(scores)):
                if scores[i] >= self.threshold:
                    ymin, xmin, ymax, xmax = boxes[i]
                    
                    # Convert [0,1] to pixels
                    left = int(xmin * orig_w)
                    top = int(ymin * orig_h)
                    right = int(xmax * orig_w)
                    bottom = int(ymax * orig_h)
                    
                    class_id = int(classes[i])
                    label = self.labels.get(class_id, "unknown")
                    
                    # Filter target classes
                    # Note: We rely on exact string match used in config vs labels file
                    # Commonly: 'person', 'cat', 'dog'
                    # If target_classes is defined, filter. If empty, allow all.
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
            self.latest_detections = []
