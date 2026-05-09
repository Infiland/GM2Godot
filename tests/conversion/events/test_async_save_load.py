import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestAsyncSaveLoadEvent(unittest.TestCase):
    def test_maps_async_save_load_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 72})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_async_save_load")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_72.gml")

    def test_generates_async_save_load_stub(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 72}])

        self.assertIn("func _on_async_save_load():", content)
        self.assertIn("\tpass", content)
        self.assertNotIn("_on_other_72", content)


if __name__ == "__main__":
    unittest.main()
