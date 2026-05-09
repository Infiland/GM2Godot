import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestDrawEvents(unittest.TestCase):
    def test_maps_draw_event_family(self):
        cases = [
            (0, "_draw", 3, "Draw_0.gml"),
            (64, "_on_draw_gui", 15, "Draw_64.gml"),
            (65, "_on_resize", 6, "Draw_65.gml"),
            (72, "_on_draw_begin", 16, "Draw_72.gml"),
            (73, "_on_draw_end", 16, "Draw_73.gml"),
            (74, "_on_draw_gui_begin", 15, "Draw_74.gml"),
            (75, "_on_draw_gui_end", 15, "Draw_75.gml"),
            (76, "_on_pre_draw", 16, "Draw_76.gml"),
            (77, "_on_post_draw", 16, "Draw_77.gml"),
        ]

        for event_num, godot_func, sort_key, gml_filename in cases:
            with self.subTest(event_num=event_num):
                mapping = map_event({"eventType": 8, "eventNum": event_num})
                assert mapping is not None

                self.assertEqual(mapping.godot_func, godot_func)
                self.assertEqual(mapping.params, "")
                self.assertEqual(mapping.sort_key, sort_key)
                self.assertEqual(mapping.gml_filename, gml_filename)

    def test_generates_draw_event_stubs(self):
        content = generate_script_content([
            {"eventType": 8, "eventNum": event_num}
            for event_num in (0, 64, 65, 72, 73, 74, 75, 76, 77)
        ])

        for function_name in (
            "_draw",
            "_on_draw_gui",
            "_on_resize",
            "_on_draw_begin",
            "_on_draw_end",
            "_on_draw_gui_begin",
            "_on_draw_gui_end",
            "_on_pre_draw",
            "_on_post_draw",
        ):
            self.assertIn(f"func {function_name}():", content)


if __name__ == "__main__":
    unittest.main()
