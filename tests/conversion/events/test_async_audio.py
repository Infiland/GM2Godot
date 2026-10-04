import unittest

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestAsyncAudioEvents(unittest.TestCase):
    def test_maps_async_audio_recording_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 73})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_audio_recording_async")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_73.gml")

    def test_maps_async_audio_playback_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 74})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_audio_playback_async")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_74.gml")

    def test_maps_async_audio_playback_ended_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 80})
        assert mapping is not None

        self.assertEqual(mapping.godot_func, "_on_audio_playback_ended_async")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_80.gml")

    def test_generates_async_audio_handler_stubs(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": 73},
            {"eventType": 7, "eventNum": 74},
            {"eventType": 7, "eventNum": 80},
        ])

        self.assertIn("func _on_audio_recording_async():", content)
        self.assertIn("func _on_audio_playback_async():", content)
        self.assertIn("func _on_audio_playback_ended_async():", content)
        self.assertEqual(content.count("\tpass"), 3)


if __name__ == "__main__":
    unittest.main()
