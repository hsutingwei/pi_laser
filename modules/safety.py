from shapely.geometry import Polygon, Point, box

class SafetyModule:
    def __init__(self):
        self.static_zones = [] # List of Polygons
        self.human_zones = []  # List of Polygons (inflated bboxes)

    def add_static_zone(self, points):
        # points: List of (x, y) tuples
        self.static_zones.append(Polygon(points))

    def update_human_zones(self, detections):
        # TODO: Convert human detections to inflated Polygons
        pass

    def is_safe(self, x, y):
        # TODO: Check if point (x, y) is inside any static or human zone
        # point = Point(x, y)
        # Check intersection
        return True
