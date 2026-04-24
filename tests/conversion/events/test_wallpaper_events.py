import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


WALLPAPER_EVENTS = [
    (79, "_on_wallpaper_config", "Other_79.gml"),
    (81, "_on_wallpaper_subscription_data", "Other_81.gml"),
]


class TestWallpaperEvents(unittest.TestCase):
    def test_maps_wallpaper_events(self):
        for event_num, godot_func, gml_filename in WALLPAPER_EVENTS:
            with self.subTest(event_num=event_num):
                mapping = map_event({"eventType": 7, "eventNum": event_num})

                self.assertEqual(mapping.godot_func, godot_func)
                self.assertEqual(mapping.params, "")
                self.assertEqual(mapping.sort_key, 14)
                self.assertEqual(mapping.gml_filename, gml_filename)

    def test_generates_wallpaper_event_stubs(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": event_num}
            for event_num, _godot_func, _gml_filename in WALLPAPER_EVENTS
        ])

        for _event_num, godot_func, _gml_filename in WALLPAPER_EVENTS:
            with self.subTest(godot_func=godot_func):
                self.assertIn(f"func {godot_func}():", content)

        self.assertEqual(content.count("\tpass"), 2)


if __name__ == "__main__":
    unittest.main()
