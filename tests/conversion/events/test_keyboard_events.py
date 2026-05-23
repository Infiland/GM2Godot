import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import is_input_event, map_event, map_input_event
from src.conversion.script_generator import generate_script_content


class TestKeyboardEvents(unittest.TestCase):
    def test_keyboard_event_families_merge_into_input(self):
        for event_type in (5, 9, 10):
            with self.subTest(event_type=event_type):
                self.assertTrue(is_input_event({"eventType": event_type, "eventNum": 65}))
                self.assertIsNone(map_event({"eventType": event_type, "eventNum": 65}))
                self.assertIsNotNone(map_input_event({"eventType": event_type, "eventNum": 65}))

    def test_keyboard_special_keys_merge_into_one_input_stub(self):
        content = generate_script_content([
            {"eventType": 5, "eventNum": 0},
            {"eventType": 5, "eventNum": 1},
            {"eventType": 9, "eventNum": 37},
            {"eventType": 10, "eventNum": 112},
        ])

        self.assertIn("func _gm_input_event_bindings():", content)
        self.assertIn("func _gm_input_keyboard_0():", content)
        self.assertIn("func _gm_input_key_press_37():", content)
        self.assertIn("func _gm_input_key_release_112():", content)
        self.assertNotIn("func _input(event):", content)


if __name__ == "__main__":
    unittest.main()
