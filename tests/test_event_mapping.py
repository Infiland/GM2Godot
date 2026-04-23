import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import (
    EventMapping, map_event, is_input_event,
    INPUT_EVENT_TYPES, INPUT_MERGED_MAPPING,
)


class TestIsInputEvent(unittest.TestCase):
    """Test is_input_event for input and non-input event types."""

    def test_keyboard_event(self):
        self.assertTrue(is_input_event({"eventType": 5, "eventNum": 65}))

    def test_mouse_event(self):
        self.assertTrue(is_input_event({"eventType": 6, "eventNum": 4}))

    def test_key_press_event(self):
        self.assertTrue(is_input_event({"eventType": 9, "eventNum": 32}))

    def test_key_release_event(self):
        self.assertTrue(is_input_event({"eventType": 10, "eventNum": 13}))

    def test_gesture_event(self):
        self.assertTrue(is_input_event({"eventType": 13, "eventNum": 3}))

    def test_create_event_not_input(self):
        self.assertFalse(is_input_event({"eventType": 0, "eventNum": 0}))

    def test_step_event_not_input(self):
        self.assertFalse(is_input_event({"eventType": 3, "eventNum": 0}))

    def test_missing_event_type(self):
        self.assertFalse(is_input_event({}))


class TestMapEventStatic(unittest.TestCase):
    """Test map_event for events in the static lookup table."""

    def test_create_event(self):
        m = map_event({"eventType": 0, "eventNum": 0})
        self.assertEqual(m.godot_func, "_ready")
        self.assertEqual(m.params, "")
        self.assertEqual(m.sort_key, 0)
        self.assertEqual(m.gml_filename, "Create_0.gml")

    def test_step_event(self):
        m = map_event({"eventType": 3, "eventNum": 0})
        self.assertEqual(m.godot_func, "_process")
        self.assertEqual(m.params, "delta")
        self.assertEqual(m.sort_key, 1)
        self.assertEqual(m.gml_filename, "Step_0.gml")

    def test_begin_step(self):
        m = map_event({"eventType": 3, "eventNum": 1})
        self.assertEqual(m.godot_func, "_physics_process")
        self.assertEqual(m.params, "delta")
        self.assertEqual(m.sort_key, 2)

    def test_end_step(self):
        m = map_event({"eventType": 3, "eventNum": 2})
        self.assertEqual(m.godot_func, "_on_end_step")
        self.assertEqual(m.sort_key, 12)

    def test_draw_event(self):
        m = map_event({"eventType": 8, "eventNum": 0})
        self.assertEqual(m.godot_func, "_draw")
        self.assertEqual(m.sort_key, 3)
        self.assertEqual(m.gml_filename, "Draw_0.gml")

    def test_draw_gui_event(self):
        m = map_event({"eventType": 8, "eventNum": 64})
        self.assertEqual(m.godot_func, "_on_draw_gui")
        self.assertEqual(m.sort_key, 15)

    def test_cleanup_event(self):
        m = map_event({"eventType": 12, "eventNum": 0})
        self.assertEqual(m.godot_func, "_exit_tree")
        self.assertEqual(m.sort_key, 5)
        self.assertEqual(m.gml_filename, "CleanUp_0.gml")

    def test_destroy_event(self):
        m = map_event({"eventType": 1, "eventNum": 0})
        self.assertEqual(m.godot_func, "_on_destroy")
        self.assertEqual(m.sort_key, 10)


class TestMapEventDynamic(unittest.TestCase):
    """Test map_event for events handled by dynamic logic."""

    def test_alarm_event(self):
        m = map_event({"eventType": 2, "eventNum": 3})
        self.assertEqual(m.godot_func, "_on_alarm_3")
        self.assertEqual(m.sort_key, 11)
        self.assertEqual(m.gml_filename, "Alarm_3.gml")

    def test_alarm_zero(self):
        m = map_event({"eventType": 2, "eventNum": 0})
        self.assertEqual(m.godot_func, "_on_alarm_0")

    def test_collision_with_object(self):
        m = map_event({
            "eventType": 4, "eventNum": 0,
            "collisionObjectId": {"name": "o_bullet"},
        })
        self.assertEqual(m.godot_func, "_on_collision_o_bullet")
        self.assertEqual(m.sort_key, 13)
        self.assertEqual(m.gml_filename, "Collision_0.gml")

    def test_collision_without_object(self):
        m = map_event({"eventType": 4, "eventNum": 0})
        self.assertEqual(m.godot_func, "_on_collision")

    def test_collision_with_null_object(self):
        m = map_event({"eventType": 4, "eventNum": 0, "collisionObjectId": None})
        self.assertEqual(m.godot_func, "_on_collision")

    def test_other_event(self):
        m = map_event({"eventType": 7, "eventNum": 5})
        self.assertEqual(m.godot_func, "_on_other_5")
        self.assertEqual(m.sort_key, 14)
        self.assertEqual(m.gml_filename, "Other_5.gml")

    def test_draw_variant(self):
        m = map_event({"eventType": 8, "eventNum": 72})
        self.assertEqual(m.godot_func, "_on_draw_72")
        self.assertEqual(m.sort_key, 16)
        self.assertEqual(m.gml_filename, "Draw_72.gml")

    def test_create_nonzero_eventnum(self):
        """eventType 0 with any eventNum should still map to _ready."""
        m = map_event({"eventType": 0, "eventNum": 5})
        self.assertEqual(m.godot_func, "_ready")

    def test_destroy_nonzero_eventnum(self):
        """eventType 1 with any eventNum should still map to _on_destroy."""
        m = map_event({"eventType": 1, "eventNum": 3})
        self.assertEqual(m.godot_func, "_on_destroy")

    def test_cleanup_nonzero_eventnum(self):
        """eventType 12 with any eventNum should still map to _exit_tree."""
        m = map_event({"eventType": 12, "eventNum": 5})
        self.assertEqual(m.godot_func, "_exit_tree")


class TestMapEventInputReturnsNone(unittest.TestCase):
    """Input events should return None (they are merged by the script generator)."""

    def test_mouse_returns_none(self):
        self.assertIsNone(map_event({"eventType": 6, "eventNum": 4}))

    def test_keyboard_returns_none(self):
        self.assertIsNone(map_event({"eventType": 5, "eventNum": 65}))

    def test_key_press_returns_none(self):
        self.assertIsNone(map_event({"eventType": 9, "eventNum": 32}))

    def test_key_release_returns_none(self):
        self.assertIsNone(map_event({"eventType": 10, "eventNum": 13}))

    def test_gesture_returns_none(self):
        self.assertIsNone(map_event({"eventType": 13, "eventNum": 3}))


class TestMapEventUnknown(unittest.TestCase):
    """Unknown event types should produce safe fallback names."""

    def test_unknown_event(self):
        m = map_event({"eventType": 99, "eventNum": 5})
        self.assertEqual(m.godot_func, "_on_event_99_5")
        self.assertEqual(m.sort_key, 20)

    def test_unknown_event_gml_filename(self):
        m = map_event({"eventType": 99, "eventNum": 5})
        self.assertEqual(m.gml_filename, "Event99_5.gml")

    def test_step_unknown_eventnum(self):
        """eventType 3 with eventNum > 2 should fall to unknown."""
        m = map_event({"eventType": 3, "eventNum": 5})
        self.assertEqual(m.godot_func, "_on_event_3_5")

    def test_missing_keys(self):
        m = map_event({})
        self.assertEqual(m.godot_func, "_on_event_-1_0")


class TestEventMappingFrozen(unittest.TestCase):
    """EventMapping instances should be immutable."""

    def test_cannot_modify(self):
        m = map_event({"eventType": 0, "eventNum": 0})
        with self.assertRaises(AttributeError):
            m.godot_func = "changed"

    def test_input_merged_mapping(self):
        self.assertEqual(INPUT_MERGED_MAPPING.godot_func, "_input")
        self.assertEqual(INPUT_MERGED_MAPPING.params, "event")
        self.assertEqual(INPUT_MERGED_MAPPING.sort_key, 4)


if __name__ == "__main__":
    unittest.main()
