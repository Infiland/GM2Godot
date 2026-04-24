import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestAnimationEvents(unittest.TestCase):
    def test_maps_animation_events(self):
        cases = [
            (7, "_on_animation_end", "Other_7.gml"),
            (58, "_on_animation_update", "Other_58.gml"),
            (59, "_on_animation_event", "Other_59.gml"),
        ]

        for event_num, godot_func, gml_filename in cases:
            with self.subTest(event_num=event_num):
                mapping = map_event({"eventType": 7, "eventNum": event_num})

                self.assertEqual(mapping.godot_func, godot_func)
                self.assertEqual(mapping.params, "")
                self.assertEqual(mapping.sort_key, 14)
                self.assertEqual(mapping.gml_filename, gml_filename)

    def test_generates_animation_event_stubs(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": 7},
            {"eventType": 7, "eventNum": 58},
            {"eventType": 7, "eventNum": 59},
        ])

        self.assertIn("func _on_animation_end():", content)
        self.assertIn("func _on_animation_update():", content)
        self.assertIn("func _on_animation_event():", content)
        self.assertEqual(content.count("\tpass"), 3)


if __name__ == "__main__":
    unittest.main()
