import math
import random

def rect_intersects(rectA, rectB):
    """
    Check if two rectangles intersect.
    Rect format: [x1, y1, x2, y2] (Left, Top, Right, Bottom)
    """
    ax1, ay1, ax2, ay2 = rectA
    bx1, by1, bx2, by2 = rectB
    
    # Check for non-overlap
    if ax2 < bx1 or ax1 > bx2: return False
    if ay2 < by1 or ay1 > by2: return False
    
    return True

def expand_bbox(bbox, margin):
    """
    Expand bbox by margin pixels.
    bbox: [x1, y1, x2, y2]
    """
    x1, y1, x2, y2 = bbox
    return [x1 - margin, y1 - margin, x2 + margin, y2 + margin]

def get_head_anchor(bbox):
    """
    Heuristic for cat head: Center X, Top 25% Y.
    bbox: [x1, y1, x2, y2]
    Returns: (cx, cy)
    """
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2
    h = y2 - y1
    cy = y1 + (h * 0.25)
    return (cx, cy)

def get_random_annulus_point(center, r_min, r_max, bounds=(640, 480)):
    """
    Sample a random point within an annulus (ring) around center.
    Uses Inverse Transform Sampling for uniform distribution.
    center: (cx, cy)
    bounds: (width, height)
    """
    cx, cy = center
    bw, bh = bounds
    
    # Random angle
    theta = random.uniform(0, 2 * math.pi)
    
    # Random radius (uniform area)
    # r = sqrt(u * (R^2 - r^2) + r^2)
    u = random.random()
    r = math.sqrt(u * (r_max**2 - r_min**2) + r_min**2)
    
    # Convert to Cartesian
    x = cx + r * math.cos(theta)
    y = cy + r * math.sin(theta)
    
    # Clamp to bounds
    x = max(0, min(x, bw))
    y = max(0, min(y, bh))
    
    return (x, y)

def get_repulsion_target(cat_bbox, current_laser_pos, safe_dist=150, bounds=(640, 480)):
    """
    Calculate a target point away from the cat.
    cat_bbox: [x1, y1, x2, y2]
    current_laser_pos: (lx, ly)
    """
    # Cat Center
    cx = (cat_bbox[0] + cat_bbox[2]) / 2
    cy = (cat_bbox[1] + cat_bbox[3]) / 2
    
    lx, ly = current_laser_pos
    
    # Vector from Cat to Laser
    dx = lx - cx
    dy = ly - cy
    
    # If laser is exactly on center (rare), pick random direction
    if dx == 0 and dy == 0:
        dx = random.choice([-1, 1])
        dy = random.choice([-1, 1])
        
    # Normalize
    mag = math.sqrt(dx**2 + dy**2)
    dx /= mag
    dy /= mag
    
    # Project out by safe_dist
    tx = cx + dx * (mag + safe_dist) # Push further away
    ty = cy + dy * (mag + safe_dist)
    
    # Clamp
    bw, bh = bounds
    tx = max(0, min(tx, bw))
    ty = max(0, min(ty, bh))
    
    return (tx, ty)
