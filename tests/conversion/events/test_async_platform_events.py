import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


ASYNC_PLATFORM_EVENTS = [
    (66, "_on_async_in_app_purchase", "Other_66.gml"),
    (67, "_on_async_cloud_save", "Other_67.gml"),
    (70, "_on_async_social", "Other_70.gml"),
    (71, "_on_async_push_notification", "Other_71.gml"),
]


class TestAsyncPlatformEvents(unittest.TestCase):
    def test_maps_async_platform_events(self):
        for event_num, godot_func, gml_filename in ASYNC_PLATFORM_EVENTS:
            with self.subTest(event_num=event_num):
                mapping = map_event({"eventType": 7, "eventNum": event_num})

                self.assertEqual(mapping.godot_func, godot_func)
                self.assertEqual(mapping.params, "")
                self.assertEqual(mapping.sort_key, 14)
                self.assertEqual(mapping.gml_filename, gml_filename)

    def test_generates_async_platform_event_stubs(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": event_num}
            for event_num, _godot_func, _gml_filename in ASYNC_PLATFORM_EVENTS
        ])

        for _event_num, godot_func, _gml_filename in ASYNC_PLATFORM_EVENTS:
            with self.subTest(godot_func=godot_func):
                self.assertIn(f"func {godot_func}():", content)


if __name__ == "__main__":
    unittest.main()
