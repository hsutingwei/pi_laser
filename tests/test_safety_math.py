import unittest
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.safety import rect_intersects, expand_bbox, get_head_anchor, get_repulsion_target, get_random_annulus_point

class TestSafetyMath(unittest.TestCase):
    def test_rect_intersects(self):
        # A: [0, 0, 10, 10]
        # B: [5, 5, 15, 15] -> Overlap
        self.assertTrue(rect_intersects([0,0,10,10], [5,5,15,15]))
        
        # C: [20, 20, 30, 30] -> No Overlap
        self.assertFalse(rect_intersects([0,0,10,10], [20,20,30,30]))
        
        # Touching edges (usually counts as overlap or not depending on strictness, here strict < >)
        # Implementation uses < and > so touching is False? 
        # ax2 < bx1: 10 < 10 is False. 
        # So touching IS intersection in this logic if not using <=
        # Let's check logic: if ax2 < bx1 return False. 10 < 10 is False. So it continues.
        # So touching is considered intersection.
        self.assertTrue(rect_intersects([0,0,10,10], [10,0,20,10]))

    def test_expand_bbox(self):
        bbox = [10, 10, 20, 20]
        margin = 5
        expanded = expand_bbox(bbox, margin)
        self.assertEqual(expanded, [5, 5, 25, 25])

    def test_get_repulsion_target(self):
        # Cat at [100, 100, 200, 200] -> Center (150, 150)
        cat_bbox = [100, 100, 200, 200]
        
        # Laser at (100, 150) -> Left of center
        laser_pos = (100, 150)
        
        # Vector Cat->Laser: (-50, 0)
        # Repulsion should be further Left
        target = get_repulsion_target(cat_bbox, laser_pos, safe_dist=100)
        
        tx, ty = target
        self.assertLess(tx, 100) # Should be further left
        self.assertAlmostEqual(ty, 150) # Should stay on same Y

    def test_annulus_sampling(self):
        center = (300, 300)
        r_min = 50
        r_max = 100
        
        for _ in range(100):
            pt = get_random_annulus_point(center, r_min, r_max)
            dx = pt[0] - center[0]
            dy = pt[1] - center[1]
            dist = (dx**2 + dy**2)**0.5
            
            self.assertGreaterEqual(dist, r_min - 0.1)
            self.assertLessEqual(dist, r_max + 0.1)

if __name__ == '__main__':
    unittest.main()
