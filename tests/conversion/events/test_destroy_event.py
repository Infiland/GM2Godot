import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestDestroyEvent(unittest.TestCase):
    def test_maps_destroy_event_to_destroy_callback(self):
        mapping = map_event({"eventType": 1, "eventNum": 0})

        self.assertEqual(mapping.godot_func, "_on_destroy")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 10)
        self.assertEqual(mapping.gml_filename, "Destroy_0.gml")

    def test_generates_destroy_stub(self):
        content = generate_script_content([{"eventType": 1, "eventNum": 0}])

        self.assertIn("func _on_destroy():", content)


if __name__ == "__main__":
    unittest.main()
