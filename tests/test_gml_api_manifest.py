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
        random_entry = get_gml_api_entry("random")
        self.assertIsNotNone(random_entry)
        assert random_entry is not None
        self.assertEqual(random_entry.status, "implemented")
        self.assertEqual(random_entry.issue_number, 504)
        point_direction = get_gml_api_entry("point_direction")
        self.assertIsNotNone(point_direction)
        assert point_direction is not None
        self.assertEqual(point_direction.status, "implemented")
        self.assertEqual(point_direction.issue_number, 504)
        file_exists = get_gml_api_entry("file_exists")
        self.assertIsNotNone(file_exists)
        assert file_exists is not None
        self.assertEqual(file_exists.status, "implemented")
        self.assertEqual(file_exists.issue_number, 505)
        ini_open = get_gml_api_entry("ini_open")
        self.assertIsNotNone(ini_open)
        assert ini_open is not None
        self.assertEqual(ini_open.status, "implemented")
        self.assertEqual(ini_open.issue_number, 505)
        json_encode = get_gml_api_entry("json_encode")
        self.assertIsNotNone(json_encode)
        assert json_encode is not None
        self.assertEqual(json_encode.status, "implemented")
        self.assertEqual(json_encode.issue_number, 505)
        buffer_create = get_gml_api_entry("buffer_create")
        self.assertIsNotNone(buffer_create)
        assert buffer_create is not None
        self.assertEqual(buffer_create.status, "implemented")
        self.assertEqual(buffer_create.issue_number, 506)
        buffer_save_async = get_gml_api_entry("buffer_save_async")
        self.assertIsNotNone(buffer_save_async)
        assert buffer_save_async is not None
        self.assertEqual(buffer_save_async.status, "partial")
        self.assertEqual(buffer_save_async.issue_number, 506)
        http_get = get_gml_api_entry("http_get")
        self.assertIsNotNone(http_get)
        assert http_get is not None
        self.assertEqual(http_get.status, "implemented")
        self.assertEqual(http_get.issue_number, 507)
        show_message_async = get_gml_api_entry("show_message_async")
        self.assertIsNotNone(show_message_async)
        assert show_message_async is not None
        self.assertEqual(show_message_async.status, "unsupported")
        self.assertEqual(show_message_async.issue_number, 507)
        network_create_socket = get_gml_api_entry("network_create_socket")
        self.assertIsNotNone(network_create_socket)
        assert network_create_socket is not None
        self.assertEqual(network_create_socket.status, "implemented")
        self.assertEqual(network_create_socket.issue_number, 508)
        network_send_packet = get_gml_api_entry("network_send_packet")
        self.assertIsNotNone(network_send_packet)
        assert network_send_packet is not None
        self.assertEqual(network_send_packet.status, "partial")
        self.assertEqual(network_send_packet.issue_number, 508)
        network_send_broadcast = get_gml_api_entry("network_send_broadcast")
        self.assertIsNotNone(network_send_broadcast)
        assert network_send_broadcast is not None
        self.assertEqual(network_send_broadcast.status, "unsupported")
        self.assertEqual(network_send_broadcast.issue_number, 508)
        gpu_set_blendmode = get_gml_api_entry("gpu_set_blendmode")
        self.assertIsNotNone(gpu_set_blendmode)
        assert gpu_set_blendmode is not None
        self.assertEqual(gpu_set_blendmode.status, "implemented")
        self.assertEqual(gpu_set_blendmode.issue_number, 509)
        sprite_get_texture = get_gml_api_entry("sprite_get_texture")
        self.assertIsNotNone(sprite_get_texture)
        assert sprite_get_texture is not None
        self.assertEqual(sprite_get_texture.status, "implemented")
        self.assertEqual(sprite_get_texture.issue_number, 509)
        part_system_create = get_gml_api_entry("part_system_create")
        self.assertIsNotNone(part_system_create)
        assert part_system_create is not None
        self.assertEqual(part_system_create.status, "planned")
        self.assertEqual(part_system_create.issue_number, 509)
        effect_create_above = get_gml_api_entry("effect_create_above")
        self.assertIsNotNone(effect_create_above)
        assert effect_create_above is not None
        self.assertEqual(effect_create_above.status, "unsupported")
        self.assertEqual(effect_create_above.issue_number, 509)
        shader_set = get_gml_api_entry("shader_set")
        self.assertIsNotNone(shader_set)
        assert shader_set is not None
        self.assertEqual(shader_set.status, "implemented")
        self.assertEqual(shader_set.issue_number, 510)
        shader_set_uniform_f = get_gml_api_entry("shader_set_uniform_f")
        self.assertIsNotNone(shader_set_uniform_f)
        assert shader_set_uniform_f is not None
        self.assertEqual(shader_set_uniform_f.status, "implemented")
        self.assertEqual(shader_set_uniform_f.issue_number, 510)
        shader_set_uniform_matrix = get_gml_api_entry("shader_set_uniform_matrix")
        self.assertIsNotNone(shader_set_uniform_matrix)
        assert shader_set_uniform_matrix is not None
        self.assertEqual(shader_set_uniform_matrix.status, "planned")
        self.assertEqual(shader_set_uniform_matrix.issue_number, 510)
        physics_world_create = get_gml_api_entry("physics_world_create")
        self.assertIsNotNone(physics_world_create)
        assert physics_world_create is not None
        self.assertEqual(physics_world_create.status, "implemented")
        self.assertEqual(physics_world_create.issue_number, 511)
        physics_apply_force = get_gml_api_entry("physics_apply_force")
        self.assertIsNotNone(physics_apply_force)
        assert physics_apply_force is not None
        self.assertEqual(physics_apply_force.status, "implemented")
        self.assertEqual(physics_apply_force.issue_number, 511)
        physics_joint_distance_create = get_gml_api_entry("physics_joint_distance_create")
        self.assertIsNotNone(physics_joint_distance_create)
        assert physics_joint_distance_create is not None
        self.assertEqual(physics_joint_distance_create.status, "planned")
        self.assertEqual(physics_joint_distance_create.issue_number, 511)
        script_execute = get_gml_api_entry("script_execute")
        self.assertIsNotNone(script_execute)
        assert script_execute is not None
        self.assertEqual(script_execute.status, "implemented")
        self.assertEqual(script_execute.issue_number, 512)
        global_function = get_gml_api_entry("global_function")
        self.assertIsNotNone(global_function)
        assert global_function is not None
        self.assertEqual(global_function.status, "implemented")
        self.assertEqual(global_function.issue_number, 512)
        external_call = get_gml_api_entry("external_call")
        self.assertIsNotNone(external_call)
        assert external_call is not None
        self.assertEqual(external_call.status, "unsupported")
        self.assertEqual(external_call.issue_number, 512)
        extension_mapping = get_gml_api_entry("extension_function_mapping")
        self.assertIsNotNone(extension_mapping)
        assert extension_mapping is not None
        self.assertEqual(extension_mapping.status, "partial")
        self.assertEqual(extension_mapping.issue_number, 517)
        region = get_gml_api_entry("#region")
        self.assertIsNotNone(region)
        assert region is not None
        self.assertEqual(region.status, "implemented")
        self.assertEqual(region.issue_number, 513)
        define = get_gml_api_entry("#define")
        self.assertIsNotNone(define)
        assert define is not None
        self.assertEqual(define.status, "implemented")
        self.assertEqual(define.issue_number, 513)
        import_directive = get_gml_api_entry("#import")
        self.assertIsNotNone(import_directive)
        assert import_directive is not None
        self.assertEqual(import_directive.status, "unsupported")
        self.assertEqual(import_directive.issue_number, 513)
        flexpanel_create_node = get_gml_api_entry("flexpanel_create_node")
        self.assertIsNotNone(flexpanel_create_node)
        assert flexpanel_create_node is not None
        self.assertEqual(flexpanel_create_node.status, "implemented")
        self.assertEqual(flexpanel_create_node.issue_number, 514)
        flexpanel_calculate_layout = get_gml_api_entry("flexpanel_calculate_layout")
        self.assertIsNotNone(flexpanel_calculate_layout)
        assert flexpanel_calculate_layout is not None
        self.assertEqual(flexpanel_calculate_layout.status, "partial")
        self.assertEqual(flexpanel_calculate_layout.issue_number, 514)
        flexpanel_measure = get_gml_api_entry("flexpanel_node_set_measure_function")
        self.assertIsNotNone(flexpanel_measure)
        assert flexpanel_measure is not None
        self.assertEqual(flexpanel_measure.status, "unsupported")
        self.assertEqual(flexpanel_measure.issue_number, 514)
        os_type = get_gml_api_entry("os_type")
        self.assertIsNotNone(os_type)
        assert os_type is not None
        self.assertEqual(os_type.status, "implemented")
        self.assertEqual(os_type.issue_number, 515)
        show_debug_message_ext = get_gml_api_entry("show_debug_message_ext")
        self.assertIsNotNone(show_debug_message_ext)
        assert show_debug_message_ext is not None
        self.assertEqual(show_debug_message_ext.status, "implemented")
        self.assertEqual(show_debug_message_ext.issue_number, 515)
        show_question = get_gml_api_entry("show_question")
        self.assertIsNotNone(show_question)
        assert show_question is not None
        self.assertEqual(show_question.status, "unsupported")
        self.assertEqual(show_question.issue_number, 515)
        weak_ref_create = get_gml_api_entry("weak_ref_create")
        self.assertIsNotNone(weak_ref_create)
        assert weak_ref_create is not None
        self.assertEqual(weak_ref_create.status, "partial")
        self.assertEqual(weak_ref_create.issue_number, 515)
        gml_pragma = get_gml_api_entry("gml_pragma")
        self.assertIsNotNone(gml_pragma)
        assert gml_pragma is not None
        self.assertEqual(gml_pragma.status, "unsupported")
        self.assertEqual(gml_pragma.issue_number, 515)
        steam_is_initialized = get_gml_api_entry("steam_is_initialized")
        self.assertIsNotNone(steam_is_initialized)
        assert steam_is_initialized is not None
        self.assertEqual(steam_is_initialized.status, "partial")
        self.assertEqual(steam_is_initialized.issue_number, 516)
        browser_input_capture = get_gml_api_entry("browser_input_capture")
        self.assertIsNotNone(browser_input_capture)
        assert browser_input_capture is not None
        self.assertEqual(browser_input_capture.status, "partial")
        self.assertEqual(browser_input_capture.issue_number, 516)
        iap_activate = get_gml_api_entry("iap_activate")
        self.assertIsNotNone(iap_activate)
        assert iap_activate is not None
        self.assertEqual(iap_activate.status, "unsupported")
        self.assertEqual(iap_activate.issue_number, 516)
        self.assertTrue(is_known_gml_api("draw_sprite"))
        self.assertTrue(is_known_gml_api("working_directory"))
        self.assertFalse(is_known_gml_api("project_local_function"))
        self.assertEqual(godot_docs_root(), "https://docs.godotengine.org/en/stable")

    def test_known_unimplemented_gml_builtin_gets_diagnostic(self):
        diagnostic = diagnostic_for_unimplemented_gml_api("collision_point_list")

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertIn("collision_point_list", diagnostic)
        self.assertIn("#487", diagnostic)

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
            "abs",
            "clamp",
            "point_direction",
            "lengthdir_y",
            "random",
            "irandom_range",
            "choose",
            "random_set_seed",
            "random_get_seed",
            "file_exists",
            "file_text_open_read",
            "file_text_write_string",
            "ini_open",
            "ini_read_string",
            "json_encode",
            "json_decode",
            "buffer_create",
            "buffer_write",
            "buffer_read",
            "buffer_seek",
            "buffer_base64_encode",
            "buffer_md5",
            "http_get",
            "http_post_string",
            "http_request",
            "network_create_socket",
            "network_create_server",
            "network_connect",
            "network_send_raw",
            "network_send_packet",
            "network_send_udp_raw",
            "network_destroy",
            "gpu_set_blendmode",
            "gpu_get_blendmode",
            "gpu_set_texfilter",
            "gpu_set_texrepeat",
            "gpu_set_colorwriteenable",
            "gpu_set_alphatestref",
            "sprite_get_texture",
            "surface_get_texture",
            "texture_get_width",
            "shader_set",
            "shader_reset",
            "shader_get_uniform",
            "shader_set_uniform_f",
            "shader_set_uniform_i",
            "texture_set_stage",
            "physics_world_create",
            "physics_world_gravity",
            "physics_fixture_create",
            "physics_fixture_bind",
            "physics_apply_force",
            "physics_apply_impulse",
            "script_execute",
            "script_exists",
            "script_get_name",
            "script_get_callable",
            "global_function",
            "flexpanel_create_node",
            "flexpanel_calculate_layout",
            "flexpanel_node_style_set_width",
            "flexpanel_node_style_set_flex_direction",
            "flexpanel_node_style_get_position",
            "flexpanel_node_set_measure_function",
            "os_get_info",
            "os_get_language",
            "environment_get_variable",
            "show_debug_message_ext",
            "code_is_compiled",
            "gc_collect",
            "gc_get_stats",
            "weak_ref_create",
            "weak_ref_any_alive",
            "steam_is_initialized",
            "browser_input_capture",
            "url_open",
            "url_get_domain",
            "xboxlive_user_is_signed_in",
            "wallpaper_set_config",
            "cloud_synchronise",
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
            "ds_grid_create",
            "ds_grid_destroy",
            "ds_grid_set",
            "ds_grid_get",
            "ds_grid_width",
            "ds_grid_height",
        ):
            with self.subTest(name=name):
                self.assertIn(name, descriptor_names)

    def test_flex_panel_manifest_classifies_full_api_surface(self):
        flex_entries = {
            entry.name: entry
            for entry in iter_gml_api_entries()
            if entry.category == "Flex Panels"
        }

        expected_names = {
            "flexpanel_create_node",
            "flexpanel_delete_node",
            "flexpanel_node_insert_child",
            "flexpanel_node_remove_child",
            "flexpanel_node_remove_all_children",
            "flexpanel_calculate_layout",
            "flexpanel_node_set_name",
            "flexpanel_node_layout_get_position",
            "flexpanel_node_get_num_children",
            "flexpanel_node_get_child",
            "flexpanel_node_get_child_hash",
            "flexpanel_node_get_parent",
            "flexpanel_node_get_name",
            "flexpanel_node_get_data",
            "flexpanel_node_get_struct",
            "flexpanel_node_set_measure_function",
            "flexpanel_node_get_measure_function",
            "flexpanel_node_style_set_width",
            "flexpanel_node_style_set_height",
            "flexpanel_node_style_set_min_width",
            "flexpanel_node_style_set_max_width",
            "flexpanel_node_style_set_min_height",
            "flexpanel_node_style_set_max_height",
            "flexpanel_node_style_set_aspect_ratio",
            "flexpanel_node_style_set_position",
            "flexpanel_node_style_set_position_type",
            "flexpanel_node_style_set_margin",
            "flexpanel_node_style_set_padding",
            "flexpanel_node_style_set_border",
            "flexpanel_node_style_set_gap",
            "flexpanel_node_style_set_direction",
            "flexpanel_node_style_set_flex_direction",
            "flexpanel_node_style_set_flex_wrap",
            "flexpanel_node_style_set_flex_basis",
            "flexpanel_node_style_set_flex_grow",
            "flexpanel_node_style_set_flex_shrink",
            "flexpanel_node_style_set_flex",
            "flexpanel_node_style_set_justify_content",
            "flexpanel_node_style_set_align_items",
            "flexpanel_node_style_set_align_self",
            "flexpanel_node_style_set_align_content",
            "flexpanel_node_style_set_display",
            "flexpanel_node_style_get_width",
            "flexpanel_node_style_get_height",
            "flexpanel_node_style_get_min_width",
            "flexpanel_node_style_get_max_width",
            "flexpanel_node_style_get_min_height",
            "flexpanel_node_style_get_max_height",
            "flexpanel_node_style_get_aspect_ratio",
            "flexpanel_node_style_get_position",
            "flexpanel_node_style_get_position_type",
            "flexpanel_node_style_get_margin",
            "flexpanel_node_style_get_padding",
            "flexpanel_node_style_get_border",
            "flexpanel_node_style_get_gap",
            "flexpanel_node_style_get_direction",
            "flexpanel_node_style_get_flex_direction",
            "flexpanel_node_style_get_flex_wrap",
            "flexpanel_node_style_get_flex_basis",
            "flexpanel_node_style_get_flex_grow",
            "flexpanel_node_style_get_flex_shrink",
            "flexpanel_node_style_get_flex",
            "flexpanel_node_style_get_justify_content",
            "flexpanel_node_style_get_align_items",
            "flexpanel_node_style_get_align_self",
            "flexpanel_node_style_get_align_content",
            "flexpanel_node_style_get_display",
        }

        self.assertEqual(set(flex_entries), expected_names)
        self.assertTrue(all(entry.issue_number == 514 for entry in flex_entries.values()))

    def test_os_debug_gc_manifest_classifies_safe_and_unsupported_surfaces(self):
        entries = {
            entry.name: entry
            for entry in iter_gml_api_entries()
            if entry.category == "OS Compiler Debug GC"
        }

        for name in (
            "os_type",
            "os_get_info",
            "debug_mode",
            "fps_real",
            "show_debug_message_ext",
            "gc_collect",
            "weak_ref_alive",
            "show_question",
            "gml_pragma",
            "GM_runtime_version",
            "clipboard_get_text",
        ):
            with self.subTest(name=name):
                self.assertIn(name, entries)
                self.assertEqual(entries[name].issue_number, 515)

    def test_platform_services_manifest_represents_hooked_and_closed_platform_surfaces(self):
        entries = {
            entry.name: entry
            for entry in iter_gml_api_entries()
            if entry.category == "Platform Services"
        }

        for name in (
            "steam_is_initialized",
            "url_open_full",
            "browser_width",
            "webgl_enabled",
            "iap_activate",
            "clickable_add",
            "xboxlive_matchmaking_create",
            "wallpaper_set_config",
            "cloud_synchronise",
            "async_push_notification_event",
            "async_cloud_save_event",
            "async_social_event",
            "wallpaper_subscription_data_event",
            "push_notifications_extension",
        ):
            with self.subTest(name=name):
                self.assertIn(name, entries)
                self.assertEqual(entries[name].issue_number, 516)

        self.assertEqual(entries["steam_is_initialized"].status, "partial")
        self.assertEqual(entries["browser_width"].runtime_support, "partial")
        self.assertEqual(entries["iap_activate"].status, "unsupported")
        self.assertEqual(entries["xboxlive_matchmaking_create"].status, "unsupported")

    def test_extensions_manifest_tracks_discovery_mapping_and_security_policy(self):
        entries = {
            entry.name: entry
            for entry in iter_gml_api_entries()
            if entry.category == "Extensions"
        }

        for name in (
            "external_define",
            "extension_function_discovery",
            "extension_function_mapping",
            "extension_unmapped_diagnostic",
            "extension_native_security_policy",
        ):
            with self.subTest(name=name):
                self.assertIn(name, entries)
                self.assertEqual(entries[name].issue_number, 517)

        self.assertEqual(entries["extension_function_mapping"].status, "partial")
        self.assertEqual(entries["extension_unmapped_diagnostic"].status, "implemented")
        self.assertIn("native", entries["extension_native_security_policy"].notes)

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
        with self.assertRaisesRegex(GMLTranspileError, "collision_point_list.*planned"):
            transpile_gml_expression("collision_point_list()")
        with self.assertRaisesRegex(GMLTranspileError, "show_message_async.*unsupported"):
            transpile_gml_expression('show_message_async("Hello")')
        with self.assertRaisesRegex(GMLTranspileError, "network_send_broadcast.*unsupported"):
            transpile_gml_expression("network_send_broadcast(sock, 6502, buf, 4)")
        with self.assertRaisesRegex(GMLTranspileError, "part_system_create.*planned"):
            transpile_gml_expression("part_system_create()")
        with self.assertRaisesRegex(GMLTranspileError, "effect_create_above.*unsupported"):
            transpile_gml_expression("effect_create_above(0, 0, 0, 0, 0, 0)")
        with self.assertRaisesRegex(GMLTranspileError, "shader_set_uniform_matrix.*planned"):
            transpile_gml_expression("shader_set_uniform_matrix(u, matrix)")
        with self.assertRaisesRegex(GMLTranspileError, "physics_joint_distance_create.*planned"):
            transpile_gml_expression("physics_joint_distance_create()")
        with self.assertRaisesRegex(GMLTranspileError, "external_call.*unsupported"):
            transpile_gml_expression("external_call('native_ext', 'fn')")
        with self.assertRaisesRegex(GMLTranspileError, "iap_activate.*unsupported.*#516.*store"):
            transpile_gml_expression("iap_activate()")
        with self.assertRaisesRegex(GMLTranspileError, "clickable_add.*unsupported.*#516.*HTML5"):
            transpile_gml_expression("clickable_add(0, 0, 100, 40, 'https://example.com')")
        with self.assertRaisesRegex(GMLTranspileError, "xboxlive_matchmaking_create.*unsupported.*#516.*Xbox"):
            transpile_gml_expression("xboxlive_matchmaking_create()")

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
