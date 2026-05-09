import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestLifecycleEvents(unittest.TestCase):
    def test_maps_game_and_room_lifecycle_events(self):
        cases = [
            (2, "_on_game_start", "Other_2.gml"),
            (3, "_on_game_end", "Other_3.gml"),
            (4, "_on_room_start", "Other_4.gml"),
            (5, "_on_room_end", "Other_5.gml"),
        ]

        for event_num, godot_func, gml_filename in cases:
            with self.subTest(event_num=event_num):
                mapping = map_event({"eventType": 7, "eventNum": event_num})
                assert mapping is not None

                self.assertEqual(mapping.godot_func, godot_func)
                self.assertEqual(mapping.params, "")
                self.assertEqual(mapping.sort_key, 14)
                self.assertEqual(mapping.gml_filename, gml_filename)

    def test_generates_lifecycle_stubs(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": 2},
            {"eventType": 7, "eventNum": 3},
            {"eventType": 7, "eventNum": 4},
            {"eventType": 7, "eventNum": 5},
        ])

        self.assertIn("func _on_game_start():", content)
        self.assertIn("func _on_game_end():", content)
        self.assertIn("func _on_room_start():", content)
        self.assertIn("func _on_room_end():", content)
        self.assertNotIn("func _on_other_2():", content)
        self.assertNotIn("func _on_other_5():", content)


if __name__ == "__main__":
    unittest.main()
