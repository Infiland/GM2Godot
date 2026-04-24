import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestAsyncSystemEvent(unittest.TestCase):
    def test_maps_async_system_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 75})

        self.assertEqual(mapping.godot_func, "_on_async_system")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.gml_filename, "Other_75.gml")

    def test_generates_async_system_stub(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 75}])

        self.assertIn("func _on_async_system():", content)
        self.assertIn("\tpass", content)
        self.assertNotIn("func _notification(what):", content)


if __name__ == "__main__":
    unittest.main()
