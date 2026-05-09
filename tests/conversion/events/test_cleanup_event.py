import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestCleanupEvent(unittest.TestCase):
    def test_maps_cleanup_event_to_exit_tree(self):
        mapping = map_event({"eventType": 12, "eventNum": 0})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_exit_tree")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 5)
        self.assertEqual(mapping.gml_filename, "CleanUp_0.gml")

    def test_generates_exit_tree_stub(self):
        content = generate_script_content([{"eventType": 12, "eventNum": 0}])

        self.assertIn("func _exit_tree():", content)


if __name__ == "__main__":
    unittest.main()
