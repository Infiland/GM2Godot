import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.script_generator import ObjectRuntimeConfig, SpriteRuntimeConfig, generate_script_content


class TestScriptGeneratorBasic(unittest.TestCase):
    """Basic output shape tests."""

    def test_empty_event_list(self):
        self.assertEqual(generate_script_content([]), "extends Node2D\n")

    def test_none_event_list_treated_as_empty(self):
        self.assertEqual(generate_script_content(None), "extends Node2D\n")

    def test_starts_with_extends(self):
        content = generate_script_content([{"eventType": 0, "eventNum": 0}])
        self.assertTrue(content.startswith("extends Node2D"))

    def test_parent_script_path_replaces_node_base(self):
        content = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            base_script_path="res://objects/o_parent/o_parent.gd",
        )
        self.assertTrue(content.startswith('extends "res://objects/o_parent/o_parent.gd"'))

    def test_parent_script_path_preserved_without_local_events(self):
        self.assertEqual(
            generate_script_content([], base_script_path="res://objects/o_parent/o_parent.gd"),
            'extends "res://objects/o_parent/o_parent.gd"\n',
        )

    def test_object_runtime_registers_and_unregisters_instances(self):
        content = generate_script_content(
            [],
            object_runtime=ObjectRuntimeConfig(
                object_name="o_child",
                parent_object_names=("o_parent",),
            ),
        )

        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn("var id = GMRuntime.gml_instance_noone()", content)
        self.assertIn('var object_index = GMRuntime.gml_asset_get_index("o_child")', content)
        self.assertIn("func _gm_register_instance():\n\tif GMRuntime.gml_handle_is_valid(id):", content)
        self.assertIn('GMRuntime.gml_instance_register(self, "o_child", ["o_parent"])', content)
        self.assertIn("var solid = false", content)
        self.assertIn("var speed = 0.0", content)
        self.assertIn(
            "func _gm_apply_motion_step():\n\tGMRuntime.gml_path_step(self)\n\tGMRuntime.gml_motion_step(self)",
            content,
        )
        self.assertIn("func _ready():\n\t_gm_register_instance()", content)
        self.assertIn("\t_gm_initialize_motion_runtime()", content)
        self.assertIn("func _process(delta):\n\t_gm_apply_motion_step()", content)
        self.assertIn("func _exit_tree():\n\t_gm_unregister_instance()", content)

    def test_object_runtime_preserves_inherited_lifecycle_when_no_local_event(self):
        content = generate_script_content(
            [],
            object_runtime=ObjectRuntimeConfig(
                object_name="o_child",
                parent_object_names=("o_parent",),
                inherit_ready=True,
                inherit_exit_tree=True,
            ),
            base_script_path="res://objects/o_parent/o_parent.gd",
        )

        self.assertTrue(content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertNotIn("const GMRuntime = preload", content)
        self.assertNotIn("\n\nvar id =", content)
        self.assertNotIn("\nvar object_index =", content)
        self.assertNotIn("\nvar depth = 0", content)
        self.assertIn(
            "func _ready():\n\t_gm_register_instance()\n\t_gm_initialize_motion_runtime()\n\tsuper._ready()",
            content,
        )
        self.assertIn("func _exit_tree():\n\tsuper._exit_tree()\n\t_gm_unregister_instance()", content)

    def test_object_runtime_records_solid_metadata_for_motion_contact(self):
        content = generate_script_content(
            [],
            object_runtime=ObjectRuntimeConfig(object_name="o_wall", solid=True),
        )

        self.assertIn("var solid = true", content)
        self.assertIn("\tsolid = true", content)
        self.assertIn('GMRuntime.gml_variable_instance_set(self, "solid", solid)', content)


class TestScriptGeneratorEvents(unittest.TestCase):
    """Test that events produce correct function stubs."""

    def test_create_event(self):
        content = generate_script_content([{"eventType": 0, "eventNum": 0}])
        self.assertIn("func _ready():", content)
        self.assertIn("pass", content)

    def test_step_event(self):
        content = generate_script_content([{"eventType": 3, "eventNum": 0}])
        self.assertIn("func _process(delta):", content)

    def test_begin_step(self):
        content = generate_script_content([{"eventType": 3, "eventNum": 1}])
        self.assertIn("func _physics_process(delta):", content)

    def test_draw_event(self):
        content = generate_script_content([{"eventType": 8, "eventNum": 0}])
        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn("func _draw():", content)
        self.assertIn('GMRuntime.gml_draw_begin(self, "_draw")', content)
        self.assertIn("GMRuntime.gml_draw_end()", content)

    def test_cleanup_event(self):
        content = generate_script_content([{"eventType": 12, "eventNum": 0}])
        self.assertIn("func _exit_tree():", content)

    def test_destroy_event(self):
        content = generate_script_content([{"eventType": 1, "eventNum": 0}])
        self.assertIn("func _on_destroy():", content)

    def test_alarm_event(self):
        content = generate_script_content([{"eventType": 2, "eventNum": 3}])
        self.assertIn("func _on_alarm_3():", content)

    def test_collision_event(self):
        content = generate_script_content([{
            "eventType": 4, "eventNum": 0,
            "collisionObjectId": {"name": "o_bullet"},
        }])
        self.assertIn("func _on_collision_o_bullet():", content)

    def test_other_event(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 26}])
        self.assertIn("func _on_other_26():", content)

    def test_no_more_lives_event(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 6}])
        self.assertIn("var lives = 0:", content)
        self.assertIn("if lives <= 0:", content)
        self.assertIn("_on_no_more_lives()", content)
        self.assertIn("func _on_no_more_lives():", content)

    def test_no_more_health_event(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 9}])
        self.assertIn("var health = 100:", content)
        self.assertIn("if health <= 0:", content)
        self.assertIn("_on_no_more_health()", content)
        self.assertIn("func _on_no_more_health():", content)

    def test_close_button_event(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 30}])
        self.assertIn("func _ready():", content)
        self.assertIn("get_tree().auto_accept_quit = false", content)
        self.assertIn("func _notification(what):", content)
        self.assertIn("if what == NOTIFICATION_WM_CLOSE_REQUEST:", content)

    def test_close_button_event_wraps_code_body(self):
        content = generate_script_content(
            [{"eventType": 7, "eventNum": 30}],
            code_bodies={"_notification": "\tget_tree().quit()"},
        )
        self.assertIn(
            "\tif what == NOTIFICATION_WM_CLOSE_REQUEST:\n\t\tget_tree().quit()",
            content,
        )

    def test_close_button_uses_existing_ready_event(self):
        content = generate_script_content([
            {"eventType": 0, "eventNum": 0},
            {"eventType": 7, "eventNum": 30},
        ])
        self.assertEqual(content.count("func _ready"), 1)
        self.assertIn("get_tree().auto_accept_quit = false", content)

    def test_draw_gui_event(self):
        content = generate_script_content([{"eventType": 8, "eventNum": 64}])
        self.assertIn("func _on_draw_gui():", content)

    def test_draw_family_events(self):
        content = generate_script_content([
            {"eventType": 8, "eventNum": 72},
            {"eventType": 8, "eventNum": 73},
            {"eventType": 8, "eventNum": 74},
            {"eventType": 8, "eventNum": 75},
            {"eventType": 8, "eventNum": 76},
            {"eventType": 8, "eventNum": 77},
        ])

        for function_name in (
            "_on_draw_begin",
            "_on_draw_end",
            "_on_draw_gui_begin",
            "_on_draw_gui_end",
            "_on_pre_draw",
            "_on_post_draw",
        ):
            self.assertIn(f"func {function_name}():", content)

    def test_resize_event_connects_viewport_size_changed(self):
        content = generate_script_content([{"eventType": 8, "eventNum": 65}])

        self.assertIn("func _ready():", content)
        self.assertIn("get_viewport().size_changed.connect(_on_resize)", content)
        self.assertIn("func _on_resize():", content)

    def test_unknown_event(self):
        content = generate_script_content([{"eventType": 99, "eventNum": 5}])
        self.assertIn("func _on_event_99_5():", content)

    def test_generated_callbacks_keep_any_values_untyped(self):
        content = generate_script_content(
            [{"eventType": 0, "eventNum": 0}, {"eventType": 3, "eventNum": 0}],
            code_bodies={
                "_ready": '\tpayload = GMRuntime.gml_struct({"items": [1, "x"]})',
                "_process": "\tlast_delta = delta",
            },
            instance_variables=["payload", "last_delta"],
        )

        self.assertIn("var payload\n", content)
        self.assertIn("var last_delta\n", content)
        self.assertIn("func _ready():", content)
        self.assertIn("func _process(delta):", content)
        self.assertNotIn("var payload:", content)
        self.assertNotIn("var last_delta:", content)
        self.assertNotIn("func _process(delta:", content)
        self.assertNotIn(" -> ", content)


class TestScriptGeneratorInputMerging(unittest.TestCase):
    """Input events (mouse, keyboard) should merge into a single _input."""

    def test_keyboard_event_produces_input(self):
        content = generate_script_content([{"eventType": 5, "eventNum": 65}])
        self.assertIn("func _input(event):", content)

    def test_mouse_event_produces_input(self):
        content = generate_script_content([{"eventType": 6, "eventNum": 4}])
        self.assertIn("func _input(event):", content)

    def test_mouse_event_ranges_produce_input(self):
        content = generate_script_content([
            {"eventType": 6, "eventNum": 0},
            {"eventType": 6, "eventNum": 11},
            {"eventType": 6, "eventNum": 50},
            {"eventType": 6, "eventNum": 58},
            {"eventType": 6, "eventNum": 60},
            {"eventType": 6, "eventNum": 61},
        ])
        self.assertIn("func _input(event):", content)
        self.assertEqual(content.count("func _input"), 1)

    def test_gesture_event_produces_input(self):
        content = generate_script_content([
            {"eventType": 13, "eventNum": event_num}
            for event_num in range(13)
        ])
        self.assertIn("func _input(event):", content)
        self.assertEqual(content.count("func _input"), 1)

    def test_multiple_input_events_merged(self):
        content = generate_script_content([
            {"eventType": 5, "eventNum": 65},
            {"eventType": 6, "eventNum": 4},
            {"eventType": 9, "eventNum": 32},
            {"eventType": 10, "eventNum": 13},
            {"eventType": 13, "eventNum": 3},
        ])
        self.assertIn("func _input(event):", content)
        self.assertEqual(content.count("func _input"), 1)

    def test_input_mixed_with_lifecycle(self):
        content = generate_script_content([
            {"eventType": 0, "eventNum": 0},
            {"eventType": 6, "eventNum": 4},
        ])
        self.assertIn("func _ready():", content)
        self.assertIn("func _input(event):", content)


class TestScriptGeneratorOrdering(unittest.TestCase):
    """Functions should be in canonical order."""

    def test_lifecycle_before_input_before_custom(self):
        content = generate_script_content([
            {"eventType": 2, "eventNum": 0},   # Alarm (custom)
            {"eventType": 6, "eventNum": 4},   # Mouse (input)
            {"eventType": 3, "eventNum": 0},   # Step (lifecycle)
            {"eventType": 0, "eventNum": 0},   # Create (lifecycle)
        ])
        ready_pos = content.index("_ready")
        process_pos = content.index("_process")
        input_pos = content.index("_input")
        alarm_pos = content.index("_on_alarm")
        self.assertLess(ready_pos, process_pos)
        self.assertLess(process_pos, input_pos)
        self.assertLess(input_pos, alarm_pos)


class TestScriptGeneratorDeduplication(unittest.TestCase):
    """Duplicate events should produce only one function."""

    def test_duplicate_create_events(self):
        content = generate_script_content([
            {"eventType": 0, "eventNum": 0},
            {"eventType": 0, "eventNum": 0},
        ])
        self.assertEqual(content.count("func _ready"), 1)

    def test_duplicate_input_events(self):
        content = generate_script_content([
            {"eventType": 6, "eventNum": 0},
            {"eventType": 6, "eventNum": 4},
        ])
        self.assertEqual(content.count("func _input"), 1)


class TestScriptGeneratorCodeBodies(unittest.TestCase):
    """Test the code_bodies transpiler seam."""

    def test_default_body_is_pass(self):
        content = generate_script_content([{"eventType": 0, "eventNum": 0}])
        self.assertIn("\tpass", content)

    def test_custom_body_replaces_pass(self):
        content = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            code_bodies={"_ready": "\tvar x = 1"},
        )
        self.assertIn("\tvar x = 1", content)
        self.assertNotIn("\tpass", content)

    def test_runtime_prelude_added_when_body_uses_runtime(self):
        content = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            code_bodies={"_ready": "\tvalue = GMRuntime.gml_div(1, 0)"},
        )

        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn("\tvalue = GMRuntime.gml_div(1, 0)", content)

    def test_partial_code_bodies(self):
        """Functions not in code_bodies should still get pass."""
        content = generate_script_content(
            [
                {"eventType": 0, "eventNum": 0},
                {"eventType": 3, "eventNum": 0},
            ],
            code_bodies={"_ready": "\tprint('hello')"},
        )
        self.assertIn("\tprint('hello')", content)
        # _process should still have pass
        process_idx = content.index("func _process")
        after_process = content[process_idx:]
        self.assertIn("pass", after_process)

    def test_empty_code_bodies_dict(self):
        content = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            code_bodies={},
        )
        self.assertIn("\tpass", content)


class TestScriptGeneratorSpriteRuntime(unittest.TestCase):
    """GameMaker sprite_index and image_index runtime support."""

    def test_sprite_runtime_generates_ready_and_helpers_without_events(self):
        content = generate_script_content(
            [],
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name="s_player",
                sprite_scene_paths={
                    "s_enemy": "res://sprites/s_enemy/s_enemy.tscn",
                    "s_player": "res://sprites/s_player/s_player.tscn",
                },
            ),
        )

        self.assertIn('const s_enemy = "s_enemy"', content)
        self.assertIn('const s_player = "s_player"', content)
        self.assertIn('"s_enemy": preload("res://sprites/s_enemy/s_enemy.tscn")', content)
        self.assertIn('var sprite_index = "s_player":', content)
        self.assertIn('var image_index = 0.0:', content)
        self.assertIn('func _gm_apply_sprite_index():', content)
        self.assertIn('func _gm_apply_image_index():', content)
        self.assertIn('if has_meta("gamemaker_image_index"):', content)
        self.assertIn('func _ready():\n\t_gm_initialize_sprite_runtime()', content)

    def test_sprite_runtime_uses_gml_body_without_duplicate_builtin_vars(self):
        content = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            code_bodies={"_ready": "\timage_index = 2\n\tsprite_index = s_enemy"},
            instance_variables={"image_index", "score", "sprite_index"},
            sprite_runtime=SpriteRuntimeConfig(
                sprite_scene_paths={"s_enemy": "res://sprites/s_enemy/s_enemy.tscn"},
            ),
        )

        self.assertIn('const s_enemy = "s_enemy"', content)
        self.assertIn("\t_gm_initialize_sprite_runtime()\n\timage_index = 2", content)
        self.assertIn("\tsprite_index = s_enemy", content)
        self.assertIn("\n\nvar score\n", content)
        self.assertNotIn("\n\nvar image_index\n", content)
        self.assertNotIn("\n\nvar sprite_index\n", content)


if __name__ == "__main__":
    unittest.main()
