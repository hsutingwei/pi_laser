import json
import time
import os
import numpy as np

CALIBRATION_FILE = 'config/laser_calibration.json'

class CalibrationLogger:
    def __init__(self, filepath=CALIBRATION_FILE):
        self.filepath = filepath
        # 2D Regression Params: x = c1*P + c2*T + c3, y = c4*P + c5*T + c6
        self.params = {
            "c1": 0.0, "c2": 0.0, "c3": 0.0,
            "c4": 0.0, "c5": 0.0, "c6": 0.0
        }
        self.samples = [] # Verified samples list
        self.calibrated = False
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)
                    self.params = data.get('params', self.params)
                    # Support legacy migration if needed, but for now just load 'samples'
                    # If legacy 'samples_x' exists, merge them?
                    if 'samples' in data:
                        self.samples = data['samples']
                    else:
                        # Migration from old format
                        sx = data.get('samples_x', [])
                        sy = data.get('samples_y', [])
                        self.samples = sx + sy
                        
                    self.calibrated = data.get('calibrated', False)
                    print(f"Calibration loaded: {self.calibrated} ({len(self.samples)} samples)")
            except Exception as e:
                print(f"Error loading calibration: {e}")

    def save(self):
        data = {
            "calibrated": self.calibrated,
            "params": self.params,
            "samples": self.samples
        }
        try:
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=4)
            print("Calibration saved.")
        except Exception as e:
            print(f"Error saving calibration: {e}")

    def add_sample(self, pan, tilt, x, y, sample_type="general"):
        """
        sample_type: 'x_calib', 'y_calib', or 'general'
        """
        sample = {
            "pan": pan,
            "tilt": tilt,
            "x": x,
            "y": y,
            "ts": time.time(),
            "type": sample_type
        }
        self.samples.append(sample)
        print(f"Added Sample: P={pan:.1f}, T={tilt:.1f} -> X={x:.1f}, Y={y:.1f}")
        self.save()

    def fit(self):
        """Compute 2D Multivariate Linear Regression"""
        # Requirements: min 3 points for plane, but user recommends 8-12
        if len(self.samples) < 3:
            print("[Calibration] Not enough samples (min 3 required).")
            return {"success": False, "msg": "Not enough samples"}
            
        try:
            # Prepare Data Matrices
            P = np.array([s['pan'] for s in self.samples])
            T = np.array([s['tilt'] for s in self.samples])
            X = np.array([s['x'] for s in self.samples])
            Y = np.array([s['y'] for s in self.samples])
            
            # Form Design Matrix A: [P, T, 1]
            A = np.column_stack((P, T, np.ones(len(P))))
            
            # Solve for X coefficients: [c1, c2, c3]
            # lstsq returns: x, residuals, rank, s
            sol_x, resid_x, rank_x, s_x = np.linalg.lstsq(A, X, rcond=None)
            
            # Solve for Y coefficients: [c4, c5, c6]
            sol_y, resid_y, rank_y, s_y = np.linalg.lstsq(A, Y, rcond=None)
            
            # Check Rank (must be 3 for P, T, 1 to be independent)
            if rank_x < 3:
                print(f"[Calibration] Rank Deficient ({rank_x}). Points may be collinear.")
                # We can fallback to simple mean or abort. 
                # User spec: "Return 'not calibrated' if failed, preserve old coeffs"
                return {"success": False, "msg": "Points Collinear (Rank Deficient)"}

            # Update Params
            self.params = {
                "c1": float(sol_x[0]), "c2": float(sol_x[1]), "c3": float(sol_x[2]),
                "c4": float(sol_y[0]), "c5": float(sol_y[1]), "c6": float(sol_y[2])
            }
            self.calibrated = True
            self.save()
            print(f"[Calibration] Success! Params: {self.params}")
            return {"success": True, "params": self.params}

        except np.linalg.LinAlgError as e:
            print(f"[Calibration] LinAlgError: {e}")
            return {"success": False, "msg": str(e)}
        except Exception as e:
            print(f"[Calibration] Error: {e}")
            return {"success": False, "msg": str(e)}

    def predict(self, pan, tilt):
        if not self.calibrated:
            return None
        
        # x = c1*P + c2*T + c3
        x = self.params['c1'] * pan + self.params['c2'] * tilt + self.params['c3']
        # y = c4*P + c5*T + c6
        y = self.params['c4'] * pan + self.params['c5'] * tilt + self.params['c6']
        
        return (x, y)

    def clear(self):
        self.samples = []
        self.calibrated = False
        self.params = {
            "c1": 0.0, "c2": 0.0, "c3": 0.0,
            "c4": 0.0, "c5": 0.0, "c6": 0.0
        }
        self.save()
