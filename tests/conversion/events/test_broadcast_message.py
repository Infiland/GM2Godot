import unittest

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestBroadcastMessageEvent(unittest.TestCase):
    def test_maps_broadcast_message_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 76})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_broadcast_message")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_76.gml")

    def test_generates_broadcast_message_stub(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 76}])

        self.assertIn("func _on_broadcast_message():", content)
        self.assertIn("\tpass", content)


if __name__ == "__main__":
    unittest.main()
