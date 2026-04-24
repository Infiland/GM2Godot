import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestStepEvents(unittest.TestCase):
    def test_maps_step_events(self):
        cases = [
            (0, "_process", "delta", 1, "Step_0.gml"),
            (1, "_physics_process", "delta", 2, "Step_1.gml"),
            (2, "_on_end_step", "", 12, "Step_2.gml"),
        ]

        for event_num, godot_func, params, sort_key, gml_filename in cases:
            with self.subTest(event_num=event_num):
                mapping = map_event({"eventType": 3, "eventNum": event_num})

                self.assertEqual(mapping.godot_func, godot_func)
                self.assertEqual(mapping.params, params)
                self.assertEqual(mapping.sort_key, sort_key)
                self.assertEqual(mapping.gml_filename, gml_filename)

    def test_generates_step_stubs(self):
        content = generate_script_content([
            {"eventType": 3, "eventNum": 0},
            {"eventType": 3, "eventNum": 1},
            {"eventType": 3, "eventNum": 2},
        ])

        self.assertIn("func _process(delta):", content)
        self.assertIn("func _physics_process(delta):", content)
        self.assertIn("func _on_end_step():", content)


if __name__ == "__main__":
    unittest.main()
