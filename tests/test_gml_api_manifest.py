# pyright: reportPrivateUsage=false
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_transpiler import (
    GMLTranspileError,
    category_issue_numbers,
    diagnostic_for_unimplemented_gml_api,
    generate_gml_api_compatibility_report,
    get_gml_api_entry,
    get_gml_function_descriptor,
    godot_docs_root,
    is_known_gml_api,
    iter_gml_api_entries,
    iter_gml_function_descriptors,
    transpile_gml_expression,
    validate_gml_function_arity,
)


class TestGMLAPIManifest(unittest.TestCase):
    def test_report_lists_every_part_2_category_bucket_with_counts(self):
        report = generate_gml_api_compatibility_report()
        issue_numbers = category_issue_numbers()

        self.assertEqual({row.category for row in report}, set(issue_numbers))
        self.assertEqual({row.issue_number for row in report}, set(issue_numbers.values()))

        for row in report:
            with self.subTest(category=row.category):
                self.assertGreater(row.total, 0)
                self.assertEqual(
                    row.total,
                    row.implemented
                    + row.partial
                    + row.planned
                    + row.unsupported
                    + row.out_of_scope,
                )

    def test_manifest_entries_have_owner_issue_module_and_docs(self):
        entries = tuple(iter_gml_api_entries())
        issue_numbers = set(category_issue_numbers().values())

        self.assertGreater(len(entries), 50)
        for entry in entries:
            with self.subTest(api=entry.name):
                self.assertIn(entry.issue_number, issue_numbers)
                self.assertTrue(entry.owner_module)
                self.assertTrue(entry.docs_url.startswith("https://manual.gamemaker.io/monthly/en/"))

    def test_manifest_exposes_implemented_and_planned_apis(self):
        array_push = get_gml_api_entry("array_push")
        asset_get_index = get_gml_api_entry("asset_get_index")
        instance_create_layer = get_gml_api_entry("instance_create_layer")
        place_meeting = get_gml_api_entry("place_meeting")
        motion_set = get_gml_api_entry("motion_set")
        path_start = get_gml_api_entry("path_start")
        draw_line = get_gml_api_entry("draw_line")
        draw_sprite = get_gml_api_entry("draw_sprite")
        surface_create = get_gml_api_entry("surface_create")
        camera_create_view = get_gml_api_entry("camera_create_view")

        self.assertIsNotNone(array_push)
        self.assertIsNotNone(asset_get_index)
        self.assertIsNotNone(instance_create_layer)
        self.assertIsNotNone(place_meeting)
        self.assertIsNotNone(motion_set)
        self.assertIsNotNone(path_start)
        self.assertIsNotNone(draw_line)
        self.assertIsNotNone(draw_sprite)
        self.assertIsNotNone(surface_create)
        self.assertIsNotNone(camera_create_view)
        assert array_push is not None
        assert asset_get_index is not None
        assert instance_create_layer is not None
        assert place_meeting is not None
        assert motion_set is not None
        assert path_start is not None
        assert draw_line is not None
        assert draw_sprite is not None
        assert surface_create is not None
        assert camera_create_view is not None

        self.assertEqual(array_push.status, "implemented")
        self.assertEqual(array_push.issue_number, 502)
        self.assertEqual(asset_get_index.status, "implemented")
        self.assertEqual(asset_get_index.issue_number, 484)
        self.assertEqual(instance_create_layer.status, "implemented")
        self.assertEqual(instance_create_layer.issue_number, 485)
        self.assertEqual(place_meeting.status, "partial")
        self.assertEqual(place_meeting.issue_number, 487)
        self.assertEqual(motion_set.status, "implemented")
        self.assertEqual(motion_set.issue_number, 488)
        self.assertEqual(path_start.status, "partial")
        self.assertEqual(path_start.issue_number, 489)
        self.assertEqual(draw_line.status, "implemented")
        self.assertEqual(draw_line.issue_number, 490)
        self.assertEqual(draw_sprite.status, "implemented")
        self.assertEqual(draw_sprite.issue_number, 491)
        self.assertEqual(surface_create.status, "partial")
        self.assertEqual(surface_create.issue_number, 492)
        self.assertEqual(camera_create_view.status, "partial")
        self.assertEqual(camera_create_view.issue_number, 493)
        audio_play_sound = get_gml_api_entry("audio_play_sound")
        self.assertIsNotNone(audio_play_sound)
        assert audio_play_sound is not None
        self.assertEqual(audio_play_sound.status, "implemented")
        self.assertEqual(audio_play_sound.issue_number, 495)
        room_goto = get_gml_api_entry("room_goto")
        self.assertIsNotNone(room_goto)
        assert room_goto is not None
        self.assertEqual(room_goto.status, "implemented")
        self.assertEqual(room_goto.issue_number, 496)
        alarm_set = get_gml_api_entry("alarm_set")
        self.assertIsNotNone(alarm_set)
        assert alarm_set is not None
        self.assertEqual(alarm_set.status, "implemented")
        self.assertEqual(alarm_set.issue_number, 497)
        time_source_create = get_gml_api_entry("time_source_create")
        self.assertIsNotNone(time_source_create)
        assert time_source_create is not None
        self.assertEqual(time_source_create.status, "implemented")
        self.assertEqual(time_source_create.issue_number, 497)
        self.assertTrue(is_known_gml_api("draw_sprite"))
        self.assertFalse(is_known_gml_api("project_local_function"))
        self.assertEqual(godot_docs_root(), "https://docs.godotengine.org/en/stable")

    def test_known_unimplemented_gml_builtin_gets_diagnostic(self):
        diagnostic = diagnostic_for_unimplemented_gml_api("ds_grid_create")

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertIn("ds_grid_create", diagnostic)
        self.assertIn("#500", diagnostic)

    def test_function_descriptors_include_lowering_metadata_and_issue_urls(self):
        descriptor = get_gml_function_descriptor("array_push")

        self.assertIsNotNone(descriptor)
        assert descriptor is not None
        self.assertEqual(descriptor.category, "Arrays")
        self.assertEqual(descriptor.min_args, 2)
        self.assertIsNone(descriptor.max_args)
        self.assertEqual(descriptor.lowering_kind, "runtime")
        self.assertEqual(descriptor.lowering_target, "gml_array_push")
        self.assertEqual(descriptor.issue_url, "https://github.com/Infiland/GM2Godot/issues/502")

    def test_function_descriptors_cover_current_implemented_call_helpers(self):
        descriptor_names = {descriptor.name for descriptor in iter_gml_function_descriptors()}

        for name in (
            "array_push",
            "asset_get_index",
            "asset_get_ids",
            "bool",
            "instance_create_layer",
            "instance_destroy",
            "place_meeting",
            "collision_rectangle",
            "motion_set",
            "move_contact_solid",
            "path_start",
            "mp_grid_path",
            "draw_line",
            "draw_set_color",
            "audio_play_sound",
            "room_goto",
            "alarm_set",
            "alarm_get",
            "time_source_create",
            "call_later",
            "call_cancel",
            "keyboard_check",
            "method",
            "show_debug_message",
            "struct_get",
            "variable_instance_get",
            "ds_map_create",
            "ds_map_destroy",
            "ds_map_set",
            "ds_map_find_value",
            "ds_map_exists",
            "ds_map_keys",
            "ds_map_values",
            "ds_map_add",
            "ds_map_add_list",
            "ds_map_add_map",
        ):
            with self.subTest(name=name):
                self.assertIn(name, descriptor_names)

    def test_function_descriptor_arity_validation_is_deterministic(self):
        descriptor = get_gml_function_descriptor("struct_set")

        self.assertIsNotNone(descriptor)
        assert descriptor is not None
        diagnostic = validate_gml_function_arity(descriptor, 2)

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertIn("struct_set", diagnostic)
        self.assertIn("expects 3", diagnostic)
        self.assertIn("#483", diagnostic)

    def test_transpiler_rejects_known_unimplemented_gml_builtin_calls(self):
        with self.assertRaisesRegex(GMLTranspileError, "ds_grid_create.*#500"):
            transpile_gml_expression("ds_grid_create()")

    def test_transpiler_rejects_wrong_arity_for_known_helpers(self):
        with self.assertRaisesRegex(GMLTranspileError, "real.*expects 1.*got 0"):
            transpile_gml_expression("real()")
        with self.assertRaisesRegex(GMLTranspileError, "array_push.*at least 2.*got 1"):
            transpile_gml_expression("array_push(items)")

    def test_unknown_project_local_function_calls_still_pass_through(self):
        self.assertEqual(
            transpile_gml_expression("project_local_function(score + 1)"),
            "project_local_function(GMRuntime.gml_add(score, 1))",
        )


if __name__ == "__main__":
    unittest.main()
