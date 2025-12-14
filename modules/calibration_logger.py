import json
import time
import os
import numpy as np

CALIBRATION_FILE = 'config/laser_calibration.json'

class CalibrationLogger:
    def __init__(self, filepath=CALIBRATION_FILE):
        self.filepath = filepath
        self.params = {"ax": 0.0, "bx": 0.0, "ay": 0.0, "by": 0.0}
        self.samples_x = []
        self.samples_y = []
        self.calibrated = False
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)
                    self.params = data.get('params', self.params)
                    self.samples_x = data.get('samples_x', [])
                    self.samples_y = data.get('samples_y', [])
                    self.calibrated = data.get('calibrated', False)
                    print(f"Calibration loaded: {self.calibrated}")
            except Exception as e:
                print(f"Error loading calibration: {e}")

    def save(self):
        data = {
            "calibrated": self.calibrated,
            "params": self.params,
            "samples_x": self.samples_x,
            "samples_y": self.samples_y
        }
        try:
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=4)
            print("Calibration saved.")
        except Exception as e:
            print(f"Error saving calibration: {e}")

    def add_sample(self, pan, tilt, x, y, sample_type):
        """
        sample_type: 'x_calib' (fix tilt, vary pan) or 'y_calib' (fix pan, vary tilt)
        """
        sample = {
            "pan": pan,
            "tilt": tilt,
            "x": x,
            "y": y,
            "ts": time.time(),
            "type": sample_type
        }
        
        if sample_type == 'x_calib':
            self.samples_x.append(sample)
            print(f"Added X-Sample: x={x} at pan={pan}")
        elif sample_type == 'y_calib':
            self.samples_y.append(sample)
            print(f"Added Y-Sample: y={y} at tilt={tilt}")
            
        self.save()

    def fit(self):
        """Compute linear regression for X and Y axes independently"""
        # Fit X: x = ax * pan + bx
        if len(self.samples_x) == 1:
            # Single point (FPV mode) -> Constant X
            self.params['ax'] = 0.0
            self.params['bx'] = float(self.samples_x[0]['x'])
        elif len(self.samples_x) >= 2:
            pans = np.array([s['pan'] for s in self.samples_x])
            xs = np.array([s['x'] for s in self.samples_x])
            # Linear Fit (degree 1)
            ax, bx = np.polyfit(pans, xs, 1)
            self.params['ax'] = float(ax)
            self.params['bx'] = float(bx)
        
        # Fit Y: y = ay * tilt + by
        if len(self.samples_y) == 1:
             # Single point (FPV mode) -> Constant Y
            self.params['ay'] = 0.0
            self.params['by'] = float(self.samples_y[0]['y'])
        elif len(self.samples_y) >= 2:
            tilts = np.array([s['tilt'] for s in self.samples_y])
            ys = np.array([s['y'] for s in self.samples_y])
            ay, by = np.polyfit(tilts, ys, 1)
            self.params['ay'] = float(ay)
            self.params['by'] = float(by)
            
        # Check if we have enough data (at least 1 point per axis)
        if len(self.samples_x) >= 1 and len(self.samples_y) >= 1:
            self.calibrated = True
            
        self.save()
        return self.params

    def predict(self, pan, tilt):
        if not self.calibrated:
            return None
        
        # x = ax * pan + bx
        # y = ay * tilt + by
        x = self.params['ax'] * pan + self.params['bx']
        y = self.params['ay'] * tilt + self.params['by']
        return (x, y)

    def clear(self):
        self.samples_x = []
        self.samples_y = []
        self.calibrated = False
        self.params = {"ax": 0.0, "bx": 0.0, "ay": 0.0, "by": 0.0}
        self.save()
