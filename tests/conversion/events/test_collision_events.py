import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestCollisionEvents(unittest.TestCase):
    def test_maps_collision_with_target_object(self):
        mapping = map_event({
            "eventType": 4,
            "eventNum": 0,
            "collisionObjectId": {"name": "o_enemy"},
        })
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_collision_o_enemy")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 13)
        self.assertEqual(mapping.gml_filename, "Collision_0.gml")

    def test_maps_collision_without_target_object(self):
        mapping = map_event({"eventType": 4, "eventNum": 0})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_collision")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 13)
        self.assertEqual(mapping.gml_filename, "Collision_0.gml")

    def test_generates_collision_stubs(self):
        content = generate_script_content([
            {
                "eventType": 4,
                "eventNum": 0,
                "collisionObjectId": {"name": "o_enemy"},
            },
            {"eventType": 4, "eventNum": 0},
        ])

        self.assertIn("func _on_collision_o_enemy():", content)
        self.assertIn("func _on_collision():", content)


if __name__ == "__main__":
    unittest.main()
