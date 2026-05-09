import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestPathEndedEvent(unittest.TestCase):
    def test_maps_path_ended_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 8})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_path_ended")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_8.gml")

    def test_generates_path_ended_stub(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 8}])

        self.assertIn("func _on_path_ended():", content)
        self.assertIn("\tpass", content)
        self.assertNotIn("func _on_other_8():", content)


if __name__ == "__main__":
    unittest.main()
