import time

class PIDController:
    def __init__(self, kp, ki, kd, output_limits=None):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_limits = output_limits # (min, max)
        
        self.prev_error = 0
        self.integral = 0
        self.last_time = time.time()
        
    def update(self, setpoint, measured_value):
        now = time.time()
        dt = now - self.last_time
        if dt <= 0: dt = 1e-16 # Avoid div by zero
        
        error = setpoint - measured_value
        
        # Proportional
        p_term = self.kp * error
        
        # Integral
        self.integral += error * dt
        i_term = self.ki * self.integral
        
        # Derivative
        derivative = (error - self.prev_error) / dt
        d_term = self.kd * derivative
        
        output = p_term + i_term + d_term
        
        # Clamp output
        if self.output_limits:
            low, high = self.output_limits
            output = max(low, min(output, high))
            
        self.prev_error = error
        self.last_time = now
        
        return output

    def reset(self):
        self.prev_error = 0
        self.integral = 0
        self.last_time = time.time()
