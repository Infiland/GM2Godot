import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestRoomBoundaryMappings(unittest.TestCase):
    def test_outside_room_mapping(self):
        mapping = map_event({"eventType": 7, "eventNum": 0})

        self.assertEqual(mapping.godot_func, "_on_outside_room")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_0.gml")

    def test_intersect_boundary_mapping(self):
        mapping = map_event({"eventType": 7, "eventNum": 1})

        self.assertEqual(mapping.godot_func, "_on_intersect_boundary")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_1.gml")

    def test_outside_view_mapping(self):
        mapping = map_event({"eventType": 7, "eventNum": 43})

        self.assertEqual(mapping.godot_func, "_on_outside_view_3")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_43.gml")

    def test_intersect_view_boundary_mapping(self):
        mapping = map_event({"eventType": 7, "eventNum": 56})

        self.assertEqual(mapping.godot_func, "_on_intersect_view_6_boundary")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_56.gml")

    def test_generated_script_uses_room_boundary_stubs(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": 0},
            {"eventType": 7, "eventNum": 42},
            {"eventType": 7, "eventNum": 55},
        ])

        self.assertIn("func _on_outside_room():", content)
        self.assertIn("func _on_outside_view_2():", content)
        self.assertIn("func _on_intersect_view_5_boundary():", content)
        self.assertEqual(content.count("\tpass"), 3)


if __name__ == "__main__":
    unittest.main()
