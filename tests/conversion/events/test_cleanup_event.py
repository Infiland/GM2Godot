import unittest

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestCleanupEvent(unittest.TestCase):
    def test_maps_cleanup_event_to_on_clean_up(self):
        # Not _exit_tree: nodes also leave the tree when persistent instances
        # move between rooms, and GameMaker runs Clean Up right after Destroy.
        mapping = map_event({"eventType": 12, "eventNum": 0})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_clean_up")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 5)
        self.assertEqual(mapping.gml_filename, "CleanUp_0.gml")

    def test_generates_on_clean_up_stub(self):
        content = generate_script_content([{"eventType": 12, "eventNum": 0}])

        self.assertIn("func _on_clean_up():", content)
        self.assertNotIn("func _exit_tree():", content)


if __name__ == "__main__":
    unittest.main()
