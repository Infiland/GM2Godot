import unittest

from src.conversion.events import map_event
from src.conversion.instance_change_events import (
    event_runs_rest_after_instance_change,
    source_may_continue_instance_change,
)


def _mapped_function(event_type: int, event_num: int) -> str:
    mapping = map_event({"eventType": event_type, "eventNum": event_num})
    if mapping is None:
        raise AssertionError(f"event {event_type}/{event_num} has no mapping")
    return mapping.godot_func


class TestInstanceChangeEvents(unittest.TestCase):
    def test_events_the_runtime_calls_by_itself_run_the_rest_after_the_change(self):
        for function in (
            "_ready",
            "_on_begin_step",
            "_on_step",
            "_on_end_step",
            "_on_alarm_0",
            "_on_alarm_11",
            "_on_collision",
            "_on_collision_o_wall",
            "_on_game_start",
            "_on_room_start",
            "_on_animation_end",
            "_gm_input_keyboard_37",
            "_gm_input_mouse_0",
            "_gm_input_mouse_-1",
            "_gm_input_key_press_13",
            "_gm_input_key_release_13",
            "_gm_input_gesture_0",
        ):
            with self.subTest(function=function):
                self.assertTrue(event_runs_rest_after_instance_change(function))

    def test_events_called_from_code_of_the_instance_keep_the_change_waiting(self):
        # The Destroy and Clean Up events run inside the code that destroys the
        # instance, the user events inside the event that raised them, and
        # the draw events inside the draw pass that goes on with the node.
        for function in (
            "_on_destroy",
            "_exit_tree",
            "_notification",
            "_user_event_3",
            "_on_event_3_10",
            "_on_event_11_2",
            "_on_room_end",
            "_on_game_end",
            "_on_draw",
            "_on_draw_gui",
            "_on_async_http",
            "_gm_input_event_bindings",
            "_on_step_extra",
            "ready",
            "",
        ):
            with self.subTest(function=function):
                self.assertFalse(event_runs_rest_after_instance_change(function))

    def test_the_object_event_mapping_agrees(self):
        # Every event the mapping names is either dispatched by the runtime
        # (Create, Step, Alarm, Collision) or one of those that are not.
        dispatched = {
            (0, 0): "_ready",
            (3, 0): "_on_step",
            (3, 1): "_on_begin_step",
            (3, 2): "_on_end_step",
            (2, 4): "_on_alarm_4",
            (4, 0): "_on_collision",
            (7, 2): "_on_game_start",
            (7, 4): "_on_room_start",
            (7, 7): "_on_animation_end",
        }
        for (event_type, event_num), function in dispatched.items():
            self.assertEqual(_mapped_function(event_type, event_num), function)
            self.assertTrue(event_runs_rest_after_instance_change(function))
        for event_type, event_num in ((1, 0), (7, 10), (7, 5), (7, 3), (8, 0), (12, 0)):
            function = _mapped_function(event_type, event_num)
            self.assertFalse(event_runs_rest_after_instance_change(function), function)

    def test_a_child_event_ends_with_event_inherited_only_where_an_ancestor_may_change_the_object(self):
        source = "var s = sprite_index;\ninstance_change(o_b, true);\nsprite_index = s;\n"
        self.assertTrue(source_may_continue_instance_change("_on_step", source))
        self.assertTrue(source_may_continue_instance_change("_ready", "if (a) instance_change (o_b, 1);"))
        # Events the converter keeps waiting for the return of, and code that
        # does not call instance_change.
        self.assertFalse(source_may_continue_instance_change("_on_destroy", source))
        self.assertFalse(source_may_continue_instance_change("_user_event_0", source))
        self.assertFalse(source_may_continue_instance_change("_on_step", "x += 1;\nevent_inherited();"))
        self.assertFalse(source_may_continue_instance_change("_on_step", "my_instance_change(o_b);"))


if __name__ == "__main__":
    unittest.main()
