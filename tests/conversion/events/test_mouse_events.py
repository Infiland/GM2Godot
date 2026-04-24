import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import is_input_event, map_event
from src.conversion.script_generator import generate_script_content


class TestMouseEvents(unittest.TestCase):
    def test_mouse_event_ranges_merge_into_input(self):
        event_nums = list(range(12)) + list(range(50, 59)) + [60, 61]

        for event_num in event_nums:
            with self.subTest(event_num=event_num):
                self.assertTrue(is_input_event({"eventType": 6, "eventNum": event_num}))
                self.assertIsNone(map_event({"eventType": 6, "eventNum": event_num}))

    def test_generates_one_input_stub_for_mouse_family(self):
        content = generate_script_content([
            {"eventType": 6, "eventNum": event_num}
            for event_num in list(range(12)) + list(range(50, 59)) + [60, 61]
        ])

        self.assertIn("func _input(event):", content)
        self.assertEqual(content.count("func _input"), 1)


if __name__ == "__main__":
    unittest.main()
