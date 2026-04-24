import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestAsyncAudioEvents(unittest.TestCase):
    def test_maps_async_audio_recording_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 73})

        self.assertEqual(mapping.godot_func, "_on_audio_recording_async")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_73.gml")

    def test_maps_async_audio_playback_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 74})

        self.assertEqual(mapping.godot_func, "_on_audio_playback_async")
        self.assertEqual(mapping.params, "")
        self.assertEqual(mapping.sort_key, 14)
        self.assertEqual(mapping.gml_filename, "Other_74.gml")

    def test_maps_async_audio_playback_ended_event(self):
        mapping = map_event({"eventType": 7, "eventNum": 80})

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
