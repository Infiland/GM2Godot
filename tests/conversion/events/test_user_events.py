import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestUserEventMappings(unittest.TestCase):
    def test_user_event_lower_bound(self):
        mapping = map_event({"eventType": 7, "eventNum": 10})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_user_event_0")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_10.gml")

    def test_user_event_middle(self):
        mapping = map_event({"eventType": 7, "eventNum": 17})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_user_event_7")
        self.assertEqual(mapping.gml_filename, "Other_17.gml")

    def test_user_event_upper_bound(self):
        mapping = map_event({"eventType": 7, "eventNum": 25})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_user_event_15")
        self.assertEqual(mapping.gml_filename, "Other_25.gml")


class TestUserEventScriptGeneration(unittest.TestCase):
    def test_generates_user_event_stubs(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": 10},
            {"eventType": 7, "eventNum": 17},
            {"eventType": 7, "eventNum": 25},
        ])

        self.assertIn("func _user_event_0():", content)
        self.assertIn("func _user_event_7():", content)
        self.assertIn("func _user_event_15():", content)

    def test_user_event_code_body_uses_generated_name(self):
        content = generate_script_content(
            [{"eventType": 7, "eventNum": 12}],
            code_bodies={"_user_event_2": "\tprint('user event')"},
        )

        self.assertIn("func _user_event_2():", content)
        self.assertIn("\tprint('user event')", content)
        self.assertNotIn("func _on_other_12():", content)


if __name__ == "__main__":
    unittest.main()
