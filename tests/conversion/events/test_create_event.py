import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestCreateEvent(unittest.TestCase):
    def test_maps_create_event_to_ready(self):
        mapping = map_event({"eventType": 0, "eventNum": 0})

        self.assertEqual(mapping.godot_func, "_ready")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 0)
        self.assertEqual(mapping.gml_filename, "Create_0.gml")

    def test_generates_ready_stub(self):
        content = generate_script_content([{"eventType": 0, "eventNum": 0}])

        self.assertIn("func _ready():", content)
        self.assertIn("\tpass", content)


if __name__ == "__main__":
    unittest.main()
