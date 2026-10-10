"""Godot smoke tests for GameMaker views, cameras, window, GUI and mouse space.

Each scenario runs a small project whose root viewport uses the converter's
``viewport`` stretch mode with the application surface size as its base size,
and whose room scenes carry the converter's room and view metadata.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.json_values import JsonArray, JsonObject, JsonValue
from src.conversion.room_display import room_view_entries
from src.conversion.rooms import render_room_runtime_script
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)


def _gd(source: str) -> str:
    """Dedent GDScript written with 4-space indentation and indent it with tabs."""
    lines: list[str] = []
    for line in textwrap.dedent(source).splitlines():
        stripped = line.lstrip(" ")
        depth = (len(line) - len(stripped)) // 4
        lines.append("\t" * depth + stripped)
    return "\n".join(lines) + "\n"


_CHECK_HELPERS = """
func _check(condition, message):
    if not condition:
        push_error("CHECK FAILED: " + str(message))
        Engine.get_main_loop().quit(1)
        return false
    return true

func _near(value, expected, tolerance = 0.01):
    if value is Vector2:
        return value.distance_to(expected) <= tolerance
    return abs(float(value) - float(expected)) <= tolerance

func _frame():
    await Engine.get_main_loop().process_frame
    GMRuntime._gml_camera_update_visible_views()
"""


def _project_godot(width: int, height: int, main_scene: str, aspect: str = "keep") -> str:
    return (
        "config_version=5\n\n"
        "[application]\n"
        'config/name="CameraDisplaySmoke"\n'
        f'run/main_scene="{main_scene}"\n\n'
        "[display]\n"
        f"window/size/viewport_width={width}\n"
        f"window/size/viewport_height={height}\n"
        'window/stretch/mode="viewport"\n'
        f'window/stretch/aspect="{aspect}"\n'
    )


def _room_scene(
    name: str,
    width: int,
    height: int,
    views: list[JsonObject] | None,
    *,
    enable_views: bool,
    persistent: bool = False,
    script_path: str = "res://room.gd",
    extra_resources: str = "",
    children: str = "",
) -> str:
    source_views: JsonArray = [*(views or [])]
    entries = room_view_entries(source_views, {"Width": width, "Height": height})
    view_settings = {"enableViews": enable_views, "clearViewBackground": False, "clearDisplayBuffer": True}
    return (
        "[gd_scene format=3]\n\n"
        f'[ext_resource type="Script" path="{script_path}" id="room"]\n'
        '[ext_resource type="Script" path="res://controller.gd" id="controller"]\n'
        f"{extra_resources}\n"
        f'[node name="{name}" type="Node2D"]\n'
        'script = ExtResource("room")\n'
        f"metadata/gamemaker_room_width = {width}\n"
        f"metadata/gamemaker_room_height = {height}\n"
        f"metadata/gamemaker_room_persistent = {json.dumps(persistent)}\n"
        f"metadata/gamemaker_view_settings = {json.dumps(view_settings)}\n"
        f"metadata/gamemaker_views = {json.dumps(entries)}\n\n"
        '[node name="GMGUI" type="CanvasLayer" parent="."]\n'
        "layer = 1000\n"
        'metadata/gm2godot_gui_layer_policy = "gm_gui_canvas_layer"\n\n'
        f"{children}"
    )


def _view(**values: JsonValue) -> JsonObject:
    view: JsonObject = {
        "visible": True,
        "xview": 0,
        "yview": 0,
        "wview": 100,
        "hview": 100,
        "xport": 0,
        "yport": 0,
        "wport": 100,
        "hport": 100,
        "objectId": None,
        "hborder": 32,
        "vborder": 32,
        "hspeed": -1,
        "vspeed": -1,
    }
    view.update(values)
    return view


_ROOM_SCRIPT = _gd(
    """
    extends Node2D

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    func _enter_tree():
        GMRuntime._gml_view_room_prepare(self)
    """
)


def _controller(body: str, extends: str = "Node") -> str:
    return _gd(
        f"""
        extends {extends}

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        """
    ) + _gd(_CHECK_HELPERS) + _gd(
        """
        func _ready():
            call_deferred("_run")
        """
    ) + _gd(body)


_VIEW_ROOM_CONTROLLER = """
func _cam0():
    return GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_camera"), 0)

func _run():
    var room = get_parent()
    var camera_node = room.get_node("ViewCamera")
    var gui = room.get_node("GMGUI")
    await _frame()

    # Room Editor view state and the converted Camera2D.
    if not _check(GMRuntime.gml_builtin_global("view_enabled") == true, "view_enabled should be true"):
        return
    if not _check(GMRuntime.gml_builtin_global("view_current") == 0, "view_current should be 0"):
        return
    var cam = _cam0()
    if not _check(GMRuntime.gml_handle_is_valid(cam), "view_camera[0] should be a camera"):
        return
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 100 and GMRuntime.gml_camera_get_view_y(cam) == 50, "view position mismatch"):
        return
    if not _check(GMRuntime.gml_camera_get_view_width(cam) == 160 and GMRuntime.gml_camera_get_view_height(cam) == 90, "view size mismatch"):
        return
    if not _check(GMRuntime.gml_camera_get_view_border_x(cam) == 32 and GMRuntime.gml_camera_get_view_speed_x(cam) == -1, "Room Editor follow defaults mismatch"):
        return
    if not _check(camera_node.is_current(), "ViewCamera should be the current camera"):
        return
    if not _check(_near(camera_node.position, Vector2(180, 95)) and _near(camera_node.zoom, Vector2(2, 2)), "initial view presentation mismatch: " + str(camera_node.position) + " " + str(camera_node.zoom)):
        return
    if not _check(_near(camera_node.rotation, 0.0), "initial view rotation mismatch"):
        return

    # camera_set_view_* changes show on the next presentation in the same frame.
    GMRuntime.gml_camera_set_view_pos(cam, 200, 100)
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.position, Vector2(280, 145)), "camera_set_view_pos not presented: " + str(camera_node.position)):
        return
    GMRuntime.gml_camera_set_view_angle(cam, 30)
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.rotation, deg_to_rad(30.0), 0.0001) and _near(camera_node.position, Vector2(280, 145)), "camera_set_view_angle not presented"):
        return

    # The same transform through custom view/projection matrices.
    var view_matrix = GMRuntime.gml_camera_get_view_mat(cam)
    var projection_matrix = GMRuntime.gml_camera_get_proj_mat(cam)
    if not _check(view_matrix.size() == 16 and _near(view_matrix[14], 16000.0) and _near(projection_matrix[0], 2.0 / 160.0, 0.000001), "Build2DView matrices mismatch: " + str(view_matrix) + " " + str(projection_matrix)):
        return
    GMRuntime.gml_camera_set_view_mat(cam, view_matrix)
    GMRuntime.gml_camera_set_proj_mat(cam, projection_matrix)
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.rotation, deg_to_rad(30.0), 0.0001) and _near(camera_node.position, Vector2(280, 145)) and _near(camera_node.zoom, Vector2(2, 2)), "matrix presentation differs from the built-in view"):
        return

    # Orthographic matrices centred on (500, 400) showing 400x300.
    GMRuntime.gml_camera_set_view_mat(cam, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -500, -400, 16000, 1])
    GMRuntime.gml_camera_set_proj_mat(cam, [2.0 / 400.0, 0, 0, 0, 0, 2.0 / 300.0, 0, 0, 0, 0, 1.0 / 31999.0, 0, 0, 0, -1.0 / 31999.0, 1])
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.position, Vector2(500, 400)) and _near(camera_node.zoom, Vector2(0.8, 0.6), 0.0001) and _near(camera_node.rotation, 0.0), "ortho matrix presentation mismatch: " + str(camera_node.position) + " " + str(camera_node.zoom)):
        return

    # matrix_build_lookat/matrix_build_projection_ortho build GameMaker's
    # left-handed camera: room x stays to the right, room y down.
    GMRuntime.gml_camera_set_view_mat(cam, GMRuntime.gml_matrix_build_lookat(500, 400, -10, 500, 400, 0, 0, 1, 0))
    GMRuntime.gml_camera_set_proj_mat(cam, GMRuntime.gml_matrix_build_projection_ortho(400, 300, 1, 10000))
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.position, Vector2(500, 400)) and _near(camera_node.zoom, Vector2(0.8, 0.6), 0.0001) and _near(camera_node.rotation, 0.0), "matrix_build_lookat presentation mismatch"):
        return
    GMRuntime.gml_input_set_mouse_position(240, 45)
    if not _check(GMRuntime.gml_builtin_global("mouse_x") == 600 and GMRuntime.gml_builtin_global("mouse_y") == 325, "mouse through custom matrices mismatch: " + str(GMRuntime.gml_builtin_global("mouse_x")) + "," + str(GMRuntime.gml_builtin_global("mouse_y"))):
        return

    # Perspective camera 100 units from the z = 0 plane, 90 degree fov, 16:9.
    GMRuntime.gml_camera_set_view_mat(cam, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -500, -400, 100, 1])
    GMRuntime.gml_camera_set_proj_mat(cam, [0.5625, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1000.0 / 999.0, 1, 0, 0, -1000.0 / 999.0, 0])
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.position, Vector2(500, 400)) and _near(camera_node.zoom, Vector2(0.9, 0.9), 0.0001), "perspective presentation mismatch: " + str(camera_node.position) + " " + str(camera_node.zoom)):
        return

    # camera_set_view_pos rebuilds the 2D matrices (custom matrices are dropped).
    GMRuntime.gml_camera_set_view_angle(cam, 0)
    GMRuntime.gml_camera_set_view_pos(cam, 100, 50)
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.position, Vector2(180, 95)) and _near(camera_node.zoom, Vector2(2, 2)), "view rectangle did not replace custom matrices"):
        return

    # Legacy view arrays stay in step with the view camera.
    GMRuntime.gml_array_set(GMRuntime.gml_builtin_array("view_xview"), 0, 120)
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 120, "view_xview did not reach the camera"):
        return
    GMRuntime.gml_camera_set_view_pos(cam, 100, 50)
    if not _check(GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_xview"), 0) == 100, "camera x did not reach view_xview"):
        return
    if not _check(GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_wport"), 0) == 320, "view_wport should come from the room"):
        return

    # Default GUI: 1:1 with the application surface.
    if not _check(GMRuntime.gml_display_get_gui_width() == 320 and GMRuntime.gml_display_get_gui_height() == 180, "default GUI size should be the application surface"):
        return
    if not _check(gui.transform == Transform2D.IDENTITY, "default GUI layer transform should be identity"):
        return
    GMRuntime.gml_display_set_gui_size(640, 360)
    if not _check(GMRuntime.gml_display_get_gui_width() == 640 and GMRuntime.gml_display_get_gui_height() == 360, "display_set_gui_size not reported"):
        return
    if not _check(_near(gui.transform.get_scale(), Vector2(0.5, 0.5)) and _near(gui.transform.origin, Vector2.ZERO), "GUI layer not scaled onto the application surface"):
        return

    # Resizing the window keeps the application surface and letterboxes it.
    GMRuntime.gml_window_set_size(640, 640)
    await _frame()
    if not _check(GMRuntime.gml_window_get_width() == 640 and GMRuntime.gml_window_get_height() == 640, "window_set_size not reported"):
        return
    if not _check(GMRuntime._gml_display_application_surface_size() == Vector2(320, 180), "application surface changed with the window"):
        return
    var app_position = GMRuntime.gml_application_get_position()
    if not _check(_near(app_position[0], 0) and _near(app_position[1], 140) and _near(app_position[2], 640) and _near(app_position[3], 500), "application_get_position mismatch: " + str(app_position)):
        return
    if not _check(_near(gui.transform.get_scale(), Vector2(0.5, 0.5)), "GUI layer changed with the window"):
        return

    # Mouse: window pixels -> application surface -> room through view 0.
    GMRuntime.gml_window_mouse_set(100, 240)
    if not _check(GMRuntime.gml_window_mouse_get_x() == 100 and GMRuntime.gml_window_mouse_get_y() == 240, "window mouse mismatch"):
        return
    if not _check(GMRuntime.gml_builtin_global("mouse_x") == 125 and GMRuntime.gml_builtin_global("mouse_y") == 75, "mouse_x/y through the view mismatch: " + str(GMRuntime.gml_builtin_global("mouse_x")) + "," + str(GMRuntime.gml_builtin_global("mouse_y"))):
        return
    if not _check(GMRuntime.gml_window_view_mouse_get_x(0) == 125 and GMRuntime.gml_device_mouse_x(0) == 125, "view mouse helpers mismatch"):
        return
    if not _check(GMRuntime.gml_device_mouse_x_to_gui(0) == 100 and GMRuntime.gml_device_mouse_y_to_gui(0) == 100, "GUI mouse mismatch: " + str(GMRuntime.gml_device_mouse_x_to_gui(0)) + "," + str(GMRuntime.gml_device_mouse_y_to_gui(0))):
        return
    if not _check(GMRuntime.gml_display_mouse_get_x() == GMRuntime.gml_window_get_x() + 100, "display mouse should be window position + window mouse"):
        return

    # GUI maximised to the window with scale and offset.
    GMRuntime.gml_display_set_gui_maximise(2, 2, 10, 20)
    if not _check(GMRuntime.gml_display_get_gui_width() == 320 and GMRuntime.gml_display_get_gui_height() == 320, "maximised GUI size should be window / scale"):
        return
    if not _check(_near(gui.transform * Vector2(0, 0), Vector2(5, -60)) and _near(gui.transform * Vector2(10, 10), Vector2(15, -50)), "maximised GUI layer transform mismatch: " + str(gui.transform)):
        return
    if not _check(GMRuntime.gml_device_mouse_x_to_gui(0) == 45 and GMRuntime.gml_device_mouse_y_to_gui(0) == 110, "maximised GUI mouse mismatch"):
        return
    GMRuntime.gml_display_set_gui_maximise()
    if not _check(GMRuntime.gml_display_get_gui_width() == 640 and GMRuntime.gml_display_get_gui_height() == 640, "display_set_gui_maximise() should match the window"):
        return
    GMRuntime.gml_display_set_gui_maximise(-1, -1)
    if not _check(GMRuntime.gml_display_get_gui_width() == 320 and gui.transform == Transform2D.IDENTITY, "display_set_gui_maximise(-1, -1) should reset the GUI"):
        return

    # Assigning view_enabled (a global built-in) turns views off for the room.
    GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "view_enabled", false)
    if not _check(GMRuntime.gml_builtin_global("view_enabled") == false, "view_enabled assignment ignored"):
        return
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.position, Vector2(500, 400)) and _near(camera_node.zoom, Vector2(0.32, 0.225), 0.0001), "room without views should fill the application surface"):
        return
    GMRuntime.gml_input_set_mouse_position(50, 50)
    if not _check(GMRuntime.gml_builtin_global("mouse_x") == 156 and GMRuntime.gml_builtin_global("mouse_y") == 222, "mouse without views should scale the room"):
        return
    GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "view_enabled", true)

    # Two visible views share the application surface; the mouse resolves
    # through the last visible view that contains it.
    GMRuntime.gml_view_set_wport(0, 160)
    GMRuntime.gml_view_set_visible(1, true)
    GMRuntime.gml_view_set_xport(1, 160)
    GMRuntime.gml_view_set_yport(1, 0)
    GMRuntime.gml_view_set_wport(1, 160)
    GMRuntime.gml_view_set_hport(1, 180)
    var cam1 = GMRuntime.gml_view_get_camera(1)
    GMRuntime.gml_camera_set_view_pos(cam1, 600, 400)
    GMRuntime.gml_camera_set_view_size(cam1, 80, 90)
    GMRuntime.gml_input_set_mouse_position(200, 50)
    if not _check(GMRuntime.gml_builtin_global("mouse_x") == 620 and GMRuntime.gml_builtin_global("mouse_y") == 425, "second view mouse mismatch: " + str(GMRuntime.gml_builtin_global("mouse_x")) + "," + str(GMRuntime.gml_builtin_global("mouse_y"))):
        return
    GMRuntime.gml_input_set_mouse_position(50, 50)
    if not _check(GMRuntime.gml_builtin_global("mouse_x") == 150 and GMRuntime.gml_builtin_global("mouse_y") == 75, "first view mouse mismatch"):
        return
    GMRuntime._gml_camera_update_visible_views()
    if not _check(_near(camera_node.zoom, Vector2(1, 2)) and _near(camera_node.position, Vector2(260, 95)), "first of two views should be presented in its port: " + str(camera_node.position) + " " + str(camera_node.zoom)):
        return
    var multi_view_diagnostic = false
    for diagnostic in GMRuntime.gml_view_backend_diagnostics():
        if str(diagnostic).find("multiple active GameMaker views") >= 0:
            multi_view_diagnostic = true
    if not _check(multi_view_diagnostic, "multiple visible views should be reported"):
        return

    # Camera handles.
    var created = GMRuntime.gml_camera_create_view(1, 2, 3, 4)
    if not _check(GMRuntime.gml_camera_get_view_x(created) == 1 and GMRuntime.gml_camera_get_view_height(created) == 4 and GMRuntime.gml_camera_get_view_target(created) == -1, "camera_create_view mismatch"):
        return
    GMRuntime.gml_view_set_camera(1, created)
    if not _check(GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_camera"), 1) == created, "view_set_camera did not update view_camera"):
        return
    GMRuntime.gml_camera_apply(created)
    if not _check(GMRuntime.gml_camera_get_active() == created, "camera_apply did not set the active camera"):
        return
    GMRuntime.gml_camera_destroy(created)
    if not _check(not GMRuntime.gml_handle_is_valid(created), "camera_destroy did not free the camera"):
        return
    var empty = GMRuntime.gml_camera_create()
    if not _check(GMRuntime.gml_handle_is_valid(empty) and GMRuntime.gml_camera_get_view_width(empty) == 0, "camera_create mismatch"):
        return
    var surface = GMRuntime.gml_surface_create(32, 16)
    GMRuntime.gml_view_set_surface_id(1, surface)
    if not _check(GMRuntime.gml_view_get_surface_id(1) == surface, "view_surface_id not stored"):
        return
    GMRuntime.gml_view_set_surface_id(1, -1)
    GMRuntime.gml_surface_free(surface)

    # Window colour is the clear colour (GameMaker BGR).
    GMRuntime.gml_window_set_colour(0x0000FF)
    if not _check(GMRuntime.gml_window_get_colour() == 0x0000FF and _near(RenderingServer.get_default_clear_color().r, 1.0), "window colour mismatch"):
        return

    print("VIEW_ROOM_SMOKE_OK")
    get_tree().quit(0)
"""


_FOLLOW_ROOM_CONTROLLER = """
func _run():
    var room = get_parent()
    var camera_node = room.get_node("ViewCamera")
    var target = room.get_node("Target")
    var cam = GMRuntime.gml_view_get_camera(0)

    target.position = Vector2(300, 20)
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 210 and GMRuntime.gml_camera_get_view_y(cam) == 0, "border follow mismatch: " + str(GMRuntime.gml_camera_get_view_x(cam)) + "," + str(GMRuntime.gml_camera_get_view_y(cam))):
        return
    if not _check(_near(camera_node.position, Vector2(260, 50)) and _near(camera_node.zoom, Vector2(2, 2)), "followed view not presented"):
        return

    target.position = Vector2(5, 799.5)
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 0 and GMRuntime.gml_camera_get_view_y(cam) == 700, "room clamp mismatch: " + str(GMRuntime.gml_camera_get_view_x(cam)) + "," + str(GMRuntime.gml_camera_get_view_y(cam))):
        return

    GMRuntime.gml_camera_set_view_speed(cam, 50, 25)
    target.position = Vector2(500, 300)
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 50 and GMRuntime.gml_camera_get_view_y(cam) == 675, "speed limit mismatch"):
        return
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 100 and GMRuntime.gml_camera_get_view_y(cam) == 650, "speed limit second step mismatch"):
        return

    # Borders of at least half the view centre the view on the target.
    GMRuntime.gml_camera_set_view_speed(cam, -1, -1)
    GMRuntime.gml_camera_set_view_border(cam, 60, 60)
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 450 and GMRuntime.gml_camera_get_view_y(cam) == 250, "centred follow mismatch"):
        return

    # Following runs once per frame; later changes in the frame are presented.
    GMRuntime.gml_camera_set_view_pos(cam, 10, 20)
    GMRuntime._gml_camera_update_visible_views()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 10 and _near(camera_node.position, Vector2(60, 70)), "same-frame view change not presented"):
        return

    # Follow an instance id, then stop following.
    GMRuntime.gml_camera_set_view_border(cam, 10, 10)
    GMRuntime.gml_camera_set_view_target(cam, target.get("_gm_handle"))
    target.position = Vector2(700, 300)
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 610, "instance target follow mismatch: " + str(GMRuntime.gml_camera_get_view_x(cam))):
        return
    GMRuntime.gml_camera_set_view_target(cam, -4)
    target.position = Vector2(100, 100)
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 610, "noone target should not follow"):
        return

    # Views that are not visible do not follow.
    GMRuntime.gml_camera_set_view_target(cam, "o_player")
    GMRuntime.gml_view_set_visible(0, false)
    await _frame()
    if not _check(GMRuntime.gml_camera_get_view_x(cam) == 610, "invisible view should not follow"):
        return

    print("FOLLOW_ROOM_SMOKE_OK")
    get_tree().quit(0)
"""


_TARGET_SCRIPT = _gd(
    """
    extends Node2D

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    var _gm_handle = GMRuntime.gml_instance_noone()

    func _enter_tree():
        _gm_handle = GMRuntime.gml_instance_register(self, "o_player", [])

    func _exit_tree():
        GMRuntime.gml_instance_unregister(_gm_handle)
    """
)


_ROOM_SWITCH_CONTROLLER = """
func _run():
    var tree = get_tree()
    var first = tree.current_scene
    var first_camera = GMRuntime.gml_view_get_camera(0)
    if not _check(GMRuntime.gml_handle_is_valid(first_camera), "first room camera missing"):
        return
    if not _check(GMRuntime.gml_view_get_enabled() == true, "first room has views enabled"):
        return
    GMRuntime.gml_display_set_gui_size(1280, 720)
    var second = load("res://second.tscn").instantiate()
    first.get_parent().remove_child(first)
    tree.root.add_child(second)
    tree.current_scene = second
    if not _check(not GMRuntime.gml_handle_is_valid(first_camera), "non-persistent room cameras should be destroyed with the room"):
        return
    var second_camera = GMRuntime.gml_view_get_camera(0)
    if not _check(GMRuntime.gml_handle_is_valid(second_camera) and not GMRuntime._gml_camera_handles_match(second_camera, first_camera), "second room camera missing"):
        return
    if not _check(GMRuntime.gml_view_get_enabled() == false, "second room has views disabled"):
        return
    var gui = second.get_node("GMGUI")
    if not _check(_near(gui.transform.get_scale(), Vector2(0.5, 0.5)), "GUI size should persist across rooms"):
        return
    await _frame()
    var camera_node = second.get_node("ViewCamera")
    if not _check(camera_node.is_current() and _near(camera_node.position, Vector2(160, 120)) and _near(camera_node.zoom, Vector2(2, 1.5), 0.0001), "room without views should be presented whole: " + str(camera_node.position) + " " + str(camera_node.zoom)):
        return
    first.queue_free()
    print("ROOM_SWITCH_SMOKE_OK")
    tree.quit(0)
"""


class TestCamerasDisplayGodotSmoke(unittest.TestCase):
    def _run_project(self, files: dict[str, str], main_scene: str, marker: str) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            write_gml_runtime(str(project_dir))
            for relative_path, content in files.items():
                _write_text(project_dir / relative_path, content)

            godot_env = dict(os.environ)
            godot_env["HOME"] = str(project_dir)
            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--log-file",
                    str(project_dir / "godot.log"),
                    "--path",
                    str(project_dir),
                    "--scene",
                    main_scene,
                    "--quit-after",
                    "120",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=godot_env,
            )
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn(marker, output)
        self.assertIsNone(re.search(r"SCRIPT ERROR|Parse Error|CHECK FAILED", output), output)

    def test_views_cameras_window_gui_and_mouse(self) -> None:
        views = [
            _view(xview=100, yview=50, wview=160, hview=90, wport=320, hport=180),
            _view(visible=False),
        ]
        controller = _controller(_VIEW_ROOM_CONTROLLER)
        room = _room_scene(
            "r_view",
            1000,
            800,
            views,
            enable_views=True,
            children=(
                '[node name="ViewCamera" type="Camera2D" parent="."]\n'
                "position = Vector2(180, 95)\n"
                "ignore_rotation = false\n"
                "limit_enabled = false\n"
                "zoom = Vector2(2, 2)\n"
                "metadata/gamemaker_view_camera = true\n\n"
                '[node name="Controller" type="Node" parent="."]\n'
                'script = ExtResource("controller")\n'
            ),
        )
        self._run_project(
            {
                "project.godot": _project_godot(320, 180, "res://room.tscn"),
                "room.gd": _ROOM_SCRIPT,
                "controller.gd": controller,
                "room.tscn": room,
            },
            "res://room.tscn",
            "VIEW_ROOM_SMOKE_OK",
        )

    def test_view_follows_target_with_borders_room_clamp_and_speed(self) -> None:
        views = [
            _view(
                wview=100,
                hview=100,
                wport=200,
                hport=200,
                objectId={"name": "o_player", "path": "objects/o_player/o_player.yy"},
                hborder=10,
                vborder=10,
            ),
        ]
        room = _room_scene(
            "r_follow",
            1000,
            800,
            views,
            enable_views=True,
            script_path="res://gm2godot/gml_room_node.gd",
            extra_resources='[ext_resource type="Script" path="res://target.gd" id="target"]\n',
            children=(
                '[node name="Target" type="Node2D" parent="."]\n'
                "position = Vector2(300, 20)\n"
                'script = ExtResource("target")\n\n'
                '[node name="Controller" type="Node" parent="."]\n'
                'script = ExtResource("controller")\n'
            ),
        )
        self._run_project(
            {
                "project.godot": _project_godot(200, 200, "res://room.tscn"),
                "gm2godot/gml_room_node.gd": render_room_runtime_script(),
                "target.gd": _TARGET_SCRIPT,
                "controller.gd": _controller(_FOLLOW_ROOM_CONTROLLER),
                "room.tscn": room,
            },
            "res://room.tscn",
            "FOLLOW_ROOM_SMOKE_OK",
        )

    def test_room_switch_replaces_view_state_and_keeps_gui_settings(self) -> None:
        first = _room_scene(
            "r_first",
            640,
            480,
            [_view(wport=320, hport=240)],
            enable_views=True,
            children=(
                '[node name="Controller" type="Node" parent="."]\n'
                'script = ExtResource("controller")\n'
            ),
        )
        second = _room_scene("r_second", 320, 240, None, enable_views=False)
        self._run_project(
            {
                "project.godot": _project_godot(640, 360, "res://first.tscn"),
                "room.gd": _ROOM_SCRIPT,
                "controller.gd": _controller(_ROOM_SWITCH_CONTROLLER),
                "first.tscn": first,
                "second.tscn": second,
            },
            "res://first.tscn",
            "ROOM_SWITCH_SMOKE_OK",
        )


if __name__ == "__main__":
    unittest.main()
