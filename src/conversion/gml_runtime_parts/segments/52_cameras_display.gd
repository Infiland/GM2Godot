const GML_CAMERA_HANDLE_KIND = "camera"
const GML_VIEW_INVALID_INDEX = -1
const GML_VIEW_COUNT = 8
const GML_VIEW_CAMERA_NODE_NAME = "ViewCamera"
const GML_VIEW_CAMERA_NODE_PATH = ^"ViewCamera"
const GML_VIEW_PRESENTER_READY_META = "_gm2godot_view_presenter"
const GML_VIEW_CAMERA_NODE_META = "gamemaker_view_camera"
const GML_VIEW_STATE_META = "_gm2godot_view_state"
const GML_VIEW_GUI_LAYER_NAME = "GMGUI"
const GML_VIEW_GUI_LAYER_PATH = ^"GMGUI"
const GML_VIEW_GUI_LAYER_POLICY_META = "gm2godot_gui_layer_policy"
# GameMaker 2D cameras: LookAtLH from z = -16000 and OrthoLH(w, h, 1, 32000).
const GML_CAMERA_2D_EYE_Z = -16000.0
const GML_CAMERA_2D_ZNEAR = 1.0
const GML_CAMERA_2D_ZFAR = 32000.0
const GML_CAMERA_EPSILON = 0.000001
# Real GameMaker view arrays: the per-room viewport state is stored directly in them.
const GML_VIEW_PORT_ARRAY_NAMES = [
	"view_camera",
	"view_visible",
	"view_xport",
	"view_yport",
	"view_wport",
	"view_hport",
	"view_surface_id",
]
# Pre-camera (GameMaker 1.x) view arrays, mirrored from each view's camera.
const GML_VIEW_LEGACY_CAMERA_FIELDS = {
	"view_xview": "x",
	"view_yview": "y",
	"view_wview": "width",
	"view_hview": "height",
	"view_angle": "angle",
	"view_object": "object",
	"view_hborder": "hborder",
	"view_vborder": "vborder",
	"view_hspeed": "hspeed",
	"view_vspeed": "vspeed",
}
const GML_VIEW_LEGACY_RECT_FIELDS = {"x": true, "y": true, "width": true, "height": true, "angle": true}

# The active room's view state: {"scene", "enabled", "room_size", "persistent", "arrays", "room_cameras"}.
static var _gml_view_state = null
static var _gml_view_follow_frame = -1
static var _gml_view_legacy_active = false
static var _gml_view_legacy_shadow = {}
static var _gml_active_camera_handle = null
static var _gml_default_camera_handle = null
static var _gml_view_backend_diagnostics = []
static var _gml_view_backend_diagnostic_keys = {}
static var _gml_display_gui_size = Vector2.ZERO
static var _gml_display_gui_maximised = false
static var _gml_display_gui_scale = Vector2.ONE
static var _gml_display_gui_offset = Vector2.ZERO
static var _gml_display_aa = 0
static var _gml_display_timing_method = 1
static var _gml_display_sleep_margin = 10
static var _gml_display_ui_visibility = 0
static var _gml_window_fullscreen = null
static var _gml_window_borderless_fullscreen = false
static var _gml_window_cursor = 0


# -----------------------------------------------------------------------------
# Cameras
# -----------------------------------------------------------------------------


static func gml_camera_create():
	# An "empty" camera: no view rectangle, identity matrices, Room Editor
	# follow defaults (no object, 32 pixel borders, instant speed).
	var camera = _gml_camera_make(0.0, 0.0, 0.0, 0.0, 0.0, -1, 32.0, 32.0, -1.0, -1.0)
	camera["view_matrix"] = _gml_camera_identity_matrix()
	camera["projection_matrix"] = _gml_camera_identity_matrix()
	camera["matrices_custom"] = true
	return gml_handle_register(GML_CAMERA_HANDLE_KIND, camera)


static func gml_camera_create_view(x, y, w, h, angle = 0, object = -1, x_speed = -1, y_speed = -1, x_border = 0, y_border = 0):
	var camera = _gml_camera_make(
		_gml_camera_real(x),
		_gml_camera_real(y),
		_gml_camera_real(w),
		_gml_camera_real(h),
		_gml_camera_real(angle),
		object,
		_gml_camera_real(x_border),
		_gml_camera_real(y_border),
		_gml_camera_real(x_speed),
		_gml_camera_real(y_speed)
	)
	return gml_handle_register(GML_CAMERA_HANDLE_KIND, camera)


static func gml_camera_destroy(camera):
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if not gml_handle_is_valid(handle):
		return null
	if _gml_camera_handles_match(_gml_active_camera_handle, handle):
		_gml_active_camera_handle = null
	if _gml_camera_handles_match(_gml_default_camera_handle, handle):
		_gml_default_camera_handle = null
	gml_handle_invalidate(handle)
	return null


static func gml_camera_apply(camera):
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if not gml_handle_is_valid(handle) or typeof(handle.reference) != TYPE_DICTIONARY:
		return null
	_gml_active_camera_handle = handle
	return null


static func gml_camera_get_active():
	if gml_handle_is_valid(_gml_active_camera_handle):
		return _gml_active_camera_handle
	var state = _gml_view_active_state()
	if bool(state["enabled"]):
		var primary = _gml_view_primary_index(state)
		if primary < 0:
			return -1
		return state["arrays"]["view_camera"][primary]
	return gml_camera_get_default()


static func gml_camera_get_default():
	if gml_handle_is_valid(_gml_default_camera_handle):
		return _gml_default_camera_handle
	var room_size = _gml_view_room_size(_gml_view_active_state())
	var camera = _gml_camera_make(0.0, 0.0, room_size.x, room_size.y, 0.0, -1, 32.0, 32.0, -1.0, -1.0)
	_gml_default_camera_handle = gml_handle_register(GML_CAMERA_HANDLE_KIND, camera, "default")
	return _gml_default_camera_handle


static func gml_camera_set_default(camera):
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY:
		_gml_default_camera_handle = handle
	return null


static func gml_camera_copy_transforms(dest, source):
	var destination_camera = _gml_camera_resolve(dest)
	var source_camera = _gml_camera_resolve(source)
	if destination_camera == null or source_camera == null or is_same(destination_camera, source_camera):
		return null
	for key in ["x", "y", "width", "height", "angle", "object", "hborder", "vborder", "hspeed", "vspeed", "matrices_custom"]:
		destination_camera[key] = source_camera[key]
	destination_camera["view_matrix"] = _gml_clone_value(source_camera["view_matrix"], 0)
	destination_camera["projection_matrix"] = _gml_clone_value(source_camera["projection_matrix"], 0)
	return null


static func gml_camera_set_view_mat(camera, matrix):
	var camera_state = _gml_camera_resolve(camera)
	var values = _gml_camera_matrix_values(matrix)
	if camera_state == null or values.is_empty():
		return null
	camera_state["view_matrix"] = values
	camera_state["matrices_custom"] = true
	return null


static func gml_camera_get_view_mat(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return -1
	return _gml_clone_value(camera_state["view_matrix"], 0)


static func gml_camera_set_proj_mat(camera, matrix):
	var camera_state = _gml_camera_resolve(camera)
	var values = _gml_camera_matrix_values(matrix)
	if camera_state == null or values.is_empty():
		return null
	camera_state["projection_matrix"] = values
	camera_state["matrices_custom"] = true
	return null


static func gml_camera_get_proj_mat(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return -1
	return _gml_clone_value(camera_state["projection_matrix"], 0)


static func gml_camera_set_view_target(camera, target):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["object"] = target
	return null


static func gml_camera_get_view_target(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return -1
	return camera_state["object"]


static func gml_camera_set_view_speed(camera, x_speed, y_speed):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["hspeed"] = _gml_camera_real(x_speed)
	camera_state["vspeed"] = _gml_camera_real(y_speed)
	return null


static func gml_camera_get_view_speed_x(camera):
	return _gml_camera_get_field(camera, "hspeed")


static func gml_camera_get_view_speed_y(camera):
	return _gml_camera_get_field(camera, "vspeed")


static func gml_camera_set_view_border(camera, x_border, y_border):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["hborder"] = _gml_camera_real(x_border)
	camera_state["vborder"] = _gml_camera_real(y_border)
	return null


static func gml_camera_get_view_border_x(camera):
	return _gml_camera_get_field(camera, "hborder")


static func gml_camera_get_view_border_y(camera):
	return _gml_camera_get_field(camera, "vborder")


static func gml_camera_set_view_pos(camera, x, y):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["x"] = _gml_camera_real(x)
	camera_state["y"] = _gml_camera_real(y)
	_gml_camera_build_2d_view(camera_state)
	return null


static func gml_camera_set_view_size(camera, w, h):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["width"] = _gml_camera_real(w)
	camera_state["height"] = _gml_camera_real(h)
	_gml_camera_build_2d_view(camera_state)
	return null


static func gml_camera_set_view_angle(camera, angle):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["angle"] = _gml_camera_real(angle)
	_gml_camera_build_2d_view(camera_state)
	return null


static func gml_camera_get_view_x(camera):
	return _gml_camera_get_field(camera, "x")


static func gml_camera_get_view_y(camera):
	return _gml_camera_get_field(camera, "y")


static func gml_camera_get_view_width(camera):
	return _gml_camera_get_field(camera, "width")


static func gml_camera_get_view_height(camera):
	return _gml_camera_get_field(camera, "height")


static func gml_camera_get_view_angle(camera):
	return _gml_camera_get_field(camera, "angle")


# -----------------------------------------------------------------------------
# Views
# -----------------------------------------------------------------------------


static func gml_view_get_enabled():
	return bool(_gml_view_active_state()["enabled"])


static func gml_view_set_enabled(enabled):
	_gml_view_active_state()["enabled"] = gml_bool(enabled)
	return null


static func gml_view_get_current():
	var state = _gml_view_active_state()
	if not bool(state["enabled"]):
		return 0
	return max(_gml_view_primary_index(state), 0)


static func gml_view_get_camera(view_port):
	return _gml_view_array_get(view_port, "view_camera", -1)


static func gml_view_set_camera(view_port, camera):
	_gml_view_array_set(view_port, "view_camera", camera)
	return null


static func gml_view_get_surface_id(view_port):
	return _gml_view_array_get(view_port, "view_surface_id", -1)


static func gml_view_set_surface_id(view_port, surface):
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return null
	_gml_view_array_set(view_index, "view_surface_id", surface)
	if not _gml_is_invalid_view_reference(surface):
		_gml_view_backend_record_diagnostic(
			"view_surface_id:" + str(view_index),
			"GM2Godot presents view " + str(view_index) + " (view_surface_id) on the screen; rendering a view into a surface requires a custom SubViewport pipeline."
		)
	return null


static func gml_view_get_visible(view_port):
	return gml_bool(_gml_view_array_get(view_port, "view_visible", false))


static func gml_view_set_visible(view_port, visible):
	_gml_view_array_set(view_port, "view_visible", gml_bool(visible))
	return null


static func gml_view_get_xport(view_port):
	return _gml_view_array_get(view_port, "view_xport", 0)


static func gml_view_get_yport(view_port):
	return _gml_view_array_get(view_port, "view_yport", 0)


static func gml_view_get_wport(view_port):
	return _gml_view_array_get(view_port, "view_wport", 0)


static func gml_view_get_hport(view_port):
	return _gml_view_array_get(view_port, "view_hport", 0)


static func gml_view_set_xport(view_port, value):
	_gml_view_array_set(view_port, "view_xport", int(_to_real(value)))
	return null


static func gml_view_set_yport(view_port, value):
	_gml_view_array_set(view_port, "view_yport", int(_to_real(value)))
	return null


static func gml_view_set_wport(view_port, value):
	_gml_view_array_set(view_port, "view_wport", int(_to_real(value)))
	return null


static func gml_view_set_hport(view_port, value):
	_gml_view_array_set(view_port, "view_hport", int(_to_real(value)))
	return null


static func gml_view_backend_diagnostics():
	return _gml_clone_value(_gml_view_backend_diagnostics, 8)


# Called from each converted room root's _enter_tree, before any instance runs
# its Create event: every view slot gets its own camera built from the Room
# Editor values, exactly like GameMaker's room start.
static func _gml_view_room_prepare(scene):
	if not (scene is Node):
		return false
	_gml_view_activate_scene(scene)
	_gml_view_ensure_presenter(scene, true)
	_gml_view_present(_gml_view_state)
	_gml_display_apply_gui_layer(scene)
	return true


static func _gml_view_register_scene(scene):
	if not (scene is Node):
		return false
	_gml_view_activate_scene(scene)
	_gml_view_ensure_presenter(scene, scene.is_node_ready())
	_gml_view_present(_gml_view_state)
	_gml_display_apply_gui_layer(scene)
	return true


# Runs GameMaker's per-frame view update (camera following for the visible
# views, after End Step and before drawing) at most once per process frame,
# then presents the current view state on the room's Camera2D. Safe to call
# from every draw entry point; later calls in the same frame only re-present.
static func _gml_camera_update_visible_views():
	var state = _gml_view_active_state()
	var frame = Engine.get_process_frames()
	if _gml_view_follow_frame != frame:
		_gml_view_follow_frame = frame
		_gml_active_camera_handle = null
		_gml_view_update_cameras(state)
	var scene = state["scene"]
	if scene is Node and is_instance_valid(scene):
		_gml_view_ensure_presenter(scene, scene.is_node_ready())
		_gml_display_apply_gui_layer(scene)
	_gml_view_present(state)
	return null


# -----------------------------------------------------------------------------
# GUI layer
# -----------------------------------------------------------------------------


static func gml_display_get_gui_width():
	return _gml_display_gui_dimensions().x


static func gml_display_get_gui_height():
	return _gml_display_gui_dimensions().y


static func gml_display_set_gui_size(width, height):
	_gml_display_gui_maximised = false
	_gml_display_gui_scale = Vector2.ONE
	_gml_display_gui_offset = Vector2.ZERO
	_gml_display_gui_size = Vector2(int(_to_real(width)), int(_to_real(height)))
	_gml_display_apply_gui_layer(_gml_view_active_state()["scene"])
	return null


static func gml_display_set_gui_maximise(xscale = 1.0, yscale = 1.0, xoffset = 0.0, yoffset = 0.0):
	_gml_display_gui_size = Vector2.ZERO
	if _to_real(xscale) == -1.0 and _to_real(yscale) == -1.0:
		# Reset to the default: 1:1 with the application surface, at its origin.
		_gml_display_gui_maximised = false
		_gml_display_gui_scale = Vector2.ONE
		_gml_display_gui_offset = Vector2.ZERO
	else:
		_gml_display_gui_maximised = true
		_gml_display_gui_scale = Vector2(_to_real(xscale), _to_real(yscale))
		_gml_display_gui_offset = Vector2(_to_real(xoffset), _to_real(yoffset))
	_gml_display_apply_gui_layer(_gml_view_active_state()["scene"])
	return null


static func gml_display_set_gui_maximize(xscale = 1.0, yscale = 1.0, xoffset = 0.0, yoffset = 0.0):
	return gml_display_set_gui_maximise(xscale, yscale, xoffset, yoffset)


# -----------------------------------------------------------------------------
# Window
# -----------------------------------------------------------------------------


static func gml_window_center():
	var window = _gml_display_root_window()
	if window == null or gml_window_get_fullscreen():
		return null
	var screen = window.current_screen if not _gml_display_is_headless() else 0
	var screen_size = DisplayServer.screen_get_size(screen)
	if screen_size.x <= 0 or screen_size.y <= 0:
		return null
	window.position = DisplayServer.screen_get_position(screen) + (screen_size - window.size) / 2
	return null


static func gml_window_get_fullscreen():
	if _gml_display_is_headless():
		return _gml_window_headless_fullscreen()
	var window = _gml_display_root_window()
	if window == null:
		return false
	return window.mode == Window.MODE_FULLSCREEN or window.mode == Window.MODE_EXCLUSIVE_FULLSCREEN


static func gml_window_set_fullscreen(full):
	var fullscreen = gml_bool(full)
	_gml_window_fullscreen = fullscreen
	var window = _gml_display_root_window()
	if window == null or _gml_display_is_headless():
		return null
	if fullscreen:
		window.mode = Window.MODE_FULLSCREEN if _gml_window_borderless_fullscreen else Window.MODE_EXCLUSIVE_FULLSCREEN
	else:
		window.mode = Window.MODE_WINDOWED
	return null


static func gml_window_enable_borderless_fullscreen(enable):
	_gml_window_borderless_fullscreen = gml_bool(enable)
	return null


static func gml_window_get_borderless_fullscreen():
	return _gml_window_borderless_fullscreen


static func gml_window_get_width():
	return int(_gml_display_window_size().x)


static func gml_window_get_height():
	return int(_gml_display_window_size().y)


static func gml_window_get_x():
	return float(_gml_display_window_position().x)


static func gml_window_get_y():
	return float(_gml_display_window_position().y)


static func gml_window_get_visible_rects():
	var rects = []
	for index in range(DisplayServer.get_screen_count()):
		var screen_position = DisplayServer.screen_get_position(index)
		var screen_size = DisplayServer.screen_get_size(index)
		rects.append([screen_position.x, screen_position.y, screen_size.x, screen_size.y])
	return rects


static func gml_window_has_focus():
	var window = _gml_display_root_window()
	if window == null or _gml_display_is_headless():
		return true
	return window.has_focus()


static func gml_window_set_caption(caption):
	var window = _gml_display_root_window()
	if window != null:
		window.title = gml_string(caption)
	return null


static func gml_window_get_caption():
	var window = _gml_display_root_window()
	if window == null:
		return ""
	return window.title


static func gml_window_set_position(x, y):
	var window = _gml_display_root_window()
	if window == null or gml_window_get_fullscreen():
		return null
	window.position = Vector2i(int(_to_real(x)), int(_to_real(y)))
	return null


static func gml_window_set_size(w, h):
	var window = _gml_display_root_window()
	if window == null or gml_window_get_fullscreen():
		return null
	# Only the window changes: the application surface keeps its size and is
	# scaled into the new window by the root viewport's stretch settings.
	window.size = Vector2i(max(int(_to_real(w)), 1), max(int(_to_real(h)), 1))
	return null


static func gml_window_set_rectangle(x, y, w, h):
	gml_window_set_position(x, y)
	gml_window_set_size(w, h)
	return null


static func gml_window_set_cursor(cursor):
	_gml_window_cursor = int(_to_real(cursor))
	if _gml_window_cursor == -1:
		Input.set_mouse_mode(Input.MOUSE_MODE_HIDDEN)
		return null
	Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)
	Input.set_default_cursor_shape(_gml_window_cursor_shape(_gml_window_cursor))
	return null


static func gml_window_get_cursor():
	return _gml_window_cursor


static func gml_window_set_colour(colour):
	# The window colour clears the back buffer and the parts of the
	# application surface no visible view covers: Godot's default clear colour.
	var packed = int(_to_real(colour)) & 0xFFFFFF
	RenderingServer.set_default_clear_color(Color8(packed & 0xFF, (packed >> 8) & 0xFF, (packed >> 16) & 0xFF))
	return null


static func gml_window_get_colour():
	var clear_colour = RenderingServer.get_default_clear_color()
	return clear_colour.r8 | (clear_colour.g8 << 8) | (clear_colour.b8 << 16)


static func gml_window_set_min_width(w):
	var window = _gml_display_root_window()
	if window != null:
		window.min_size = Vector2i(max(int(_to_real(w)), 0), window.min_size.y)
	return null


static func gml_window_set_max_width(w):
	var window = _gml_display_root_window()
	if window != null:
		window.max_size = Vector2i(max(int(_to_real(w)), 0), window.max_size.y)
	return null


static func gml_window_set_min_height(h):
	var window = _gml_display_root_window()
	if window != null:
		window.min_size = Vector2i(window.min_size.x, max(int(_to_real(h)), 0))
	return null


static func gml_window_set_max_height(h):
	var window = _gml_display_root_window()
	if window != null:
		window.max_size = Vector2i(window.max_size.x, max(int(_to_real(h)), 0))
	return null


static func gml_window_minimise():
	var window = _gml_display_root_window()
	if window != null and not _gml_display_is_headless():
		window.mode = Window.MODE_MINIMIZED
	return null


static func gml_window_restore():
	var window = _gml_display_root_window()
	if window != null and not _gml_display_is_headless() and (window.mode == Window.MODE_MINIMIZED or window.mode == Window.MODE_MAXIMIZED):
		window.mode = Window.MODE_WINDOWED
	return null


static func gml_window_mouse_get_x():
	return _gml_display_window_mouse_position().x


static func gml_window_mouse_get_y():
	return _gml_display_window_mouse_position().y


static func gml_window_mouse_set(x, y):
	var window_position = Vector2(_to_real(x), _to_real(y))
	var viewport_position = _gml_display_window_to_viewport_transform() * window_position
	gml_input_set_mouse_position(viewport_position.x, viewport_position.y)
	if not _gml_display_is_headless():
		Input.warp_mouse(window_position)
	return null


static func gml_window_view_mouse_get_x(view_port):
	return _gml_view_mouse_in_view(view_port).x


static func gml_window_view_mouse_get_y(view_port):
	return _gml_view_mouse_in_view(view_port).y


static func gml_window_views_mouse_get_x():
	return _gml_mouse_room_position().x


static func gml_window_views_mouse_get_y():
	return _gml_mouse_room_position().y


static func gml_device_mouse_x(device):
	return _gml_mouse_room_position().x


static func gml_device_mouse_y(device):
	return _gml_mouse_room_position().y


static func gml_device_mouse_raw_x(device):
	return _gml_display_window_mouse_position().x


static func gml_device_mouse_raw_y(device):
	return _gml_display_window_mouse_position().y


# -----------------------------------------------------------------------------
# Display
# -----------------------------------------------------------------------------


static func gml_display_get_width():
	return int(_gml_display_screen_size().x)


static func gml_display_get_height():
	return int(_gml_display_screen_size().y)


static func gml_display_get_dpi_x():
	return _gml_display_dpi()


static func gml_display_get_dpi_y():
	return _gml_display_dpi()


static func gml_display_get_orientation():
	if _gml_display_is_headless():
		return 0
	return DisplayServer.screen_get_orientation(DisplayServer.window_get_current_screen())


static func gml_display_set_orientation(orientation):
	if is_numeric(orientation) and not _gml_display_is_headless():
		DisplayServer.screen_set_orientation(int(_to_real(orientation)), DisplayServer.window_get_current_screen())
	return null


static func gml_display_get_frequency():
	var rate = DisplayServer.screen_get_refresh_rate()
	if rate <= 0.0:
		return 60
	return int(round(rate))


static func gml_display_reset(aa, vsync):
	_gml_display_aa = int(_to_real(aa))
	_gml_builtin_globals["display_aa"] = _gml_display_aa
	if not _gml_display_is_headless():
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_ENABLED if gml_bool(vsync) else DisplayServer.VSYNC_DISABLED)
	return 0


static func gml_display_get_timing_method():
	return _gml_display_timing_method


static func gml_display_set_timing_method(method):
	if is_numeric(method):
		_gml_display_timing_method = int(_to_real(method))
	return null


static func gml_display_get_sleep_margin():
	return _gml_display_sleep_margin


static func gml_display_set_sleep_margin(margin):
	if is_numeric(margin):
		_gml_display_sleep_margin = max(int(_to_real(margin)), 0)
	return null


static func gml_display_mouse_set(x, y):
	var window_position = Vector2(_to_real(x), _to_real(y)) - _gml_display_window_position()
	return gml_window_mouse_set(window_position.x, window_position.y)


static func gml_display_set_ui_visibility(flags):
	_gml_display_ui_visibility = int(_to_real(flags))
	return null


# -----------------------------------------------------------------------------
# Screenshot helpers
# -----------------------------------------------------------------------------


static func gml_screen_save(fname):
	var img = _gml_capture_screen_image()
	if img == null:
		return -1
	var path = _gml_screen_save_path(fname)
	if path.is_empty():
		return -1
	var err = img.save_png(path)
	return 0 if err == OK else -1


static func gml_screen_save_part(fname, x, y, w, h):
	var capture = _gml_capture_screen_image()
	if capture == null:
		return -1
	var path = _gml_screen_save_path(fname)
	if path.is_empty():
		return -1
	var region = Rect2i(max(int(_to_real(x)), 0), max(int(_to_real(y)), 0), max(int(_to_real(w)), 1), max(int(_to_real(h)), 1))
	var img = capture.get_region(region)
	var err = img.save_png(path)
	return 0 if err == OK else -1


# -----------------------------------------------------------------------------
# Application surface, window and coordinate helpers used by other segments
# -----------------------------------------------------------------------------


# Size of the GameMaker application surface: the root viewport's base size,
# which the converter sets from the first room (viewport stretch mode).
static func _gml_display_application_surface_size():
	var window = _gml_display_root_window()
	if window != null:
		var size = window.get_visible_rect().size
		if size.x > 0.0 and size.y > 0.0:
			return size
	var width = float(ProjectSettings.get_setting("display/window/size/viewport_width", 0))
	var height = float(ProjectSettings.get_setting("display/window/size/viewport_height", 0))
	if width > 0.0 and height > 0.0:
		return Vector2(width, height)
	return Vector2(1024.0, 768.0)


# surface_resize(application_surface, w, h): the base size of the stretched
# root viewport is GameMaker's application surface size.
static func _gml_display_application_surface_resize(width, height):
	var window = _gml_display_root_window()
	if window == null:
		return false
	window.content_scale_size = Vector2i(max(int(_to_real(width)), 1), max(int(_to_real(height)), 1))
	return true


# application_get_position(): the application surface rectangle in window
# pixels as [left, top, right, bottom] (letterboxed when keeping aspect).
static func _gml_display_application_position():
	var transform = _gml_display_viewport_to_window_transform()
	var size = _gml_display_application_surface_size()
	var top_left = transform * Vector2.ZERO
	var bottom_right = transform * size
	return [top_left.x, top_left.y, bottom_right.x, bottom_right.y]


# Transform from viewport (application surface) coordinates to window pixels.
static func _gml_display_viewport_to_window_transform():
	var window = _gml_display_root_window()
	if window == null:
		return Transform2D.IDENTITY
	return window.get_final_transform()


# Transform from window pixels to viewport (application surface) coordinates; the transform
# a window-space CanvasLayer (Pre/Post Draw) needs.
static func _gml_display_window_to_viewport_transform():
	return _gml_display_viewport_to_window_transform().affine_inverse()


# Transform from GUI coordinates to viewport coordinates; applied to the room's GMGUI layer.
static func _gml_display_gui_to_viewport_transform():
	if _gml_display_gui_maximised:
		var gui_scale = _gml_display_gui_effective_scale()
		var window_from_gui = Transform2D(Vector2(gui_scale.x, 0.0), Vector2(0.0, gui_scale.y), _gml_display_gui_offset)
		return _gml_display_window_to_viewport_transform() * window_from_gui
	var app = _gml_display_application_surface_size()
	var gui = _gml_display_gui_dimensions()
	return Transform2D(Vector2(app.x / gui.x, 0.0), Vector2(0.0, app.y / gui.y), Vector2.ZERO)


static func _gml_display_viewport_to_gui(position):
	return _gml_display_gui_to_viewport_transform().affine_inverse() * Vector2(position)


static func _gml_display_gui_dimensions():
	if _gml_display_gui_maximised:
		var window_size = _gml_display_window_size()
		var gui_scale = _gml_display_gui_effective_scale()
		return Vector2(window_size.x / gui_scale.x, window_size.y / gui_scale.y)
	var app = _gml_display_application_surface_size()
	return Vector2(
		_gml_display_gui_size.x if _gml_display_gui_size.x > 0.0 else app.x,
		_gml_display_gui_size.y if _gml_display_gui_size.y > 0.0 else app.y
	)


static func _gml_display_gui_effective_scale():
	return Vector2(
		_gml_display_gui_scale.x if _gml_display_gui_scale.x != 0.0 else 1.0,
		_gml_display_gui_scale.y if _gml_display_gui_scale.y != 0.0 else 1.0
	)


static func _gml_display_apply_gui_layer(scene):
	var layer = _gml_display_gui_layer(scene)
	if layer == null:
		return
	var transform = _gml_display_gui_to_viewport_transform()
	if layer.transform != transform:
		layer.transform = transform


# The room's Draw GUI CanvasLayer: the converter's GMGUI node, or a layer the
# draw pipeline created with the GUI layer policy metadata.
static func _gml_display_gui_layer(scene):
	if not (scene is Node) or not is_instance_valid(scene):
		return null
	var layer = scene.get_node_or_null(GML_VIEW_GUI_LAYER_PATH)
	if layer is CanvasLayer:
		return layer
	for child in scene.get_children():
		if child is CanvasLayer and child.has_meta(GML_VIEW_GUI_LAYER_POLICY_META):
			return child
	return null


static func _gml_display_root_window():
	var loop = Engine.get_main_loop()
	if loop is SceneTree:
		return loop.root
	return null


static func _gml_display_is_headless():
	return DisplayServer.get_name() == "headless"


static func _gml_display_window_size():
	var window = _gml_display_root_window()
	if window != null:
		return Vector2(window.size)
	return Vector2(DisplayServer.window_get_size())


static func _gml_display_window_position():
	var window = _gml_display_root_window()
	if window != null:
		return Vector2(window.position)
	return Vector2(DisplayServer.window_get_position())


static func _gml_display_screen_size():
	if not _gml_display_is_headless():
		var screen_size = DisplayServer.screen_get_size(DisplayServer.window_get_current_screen())
		if screen_size.x > 0 and screen_size.y > 0:
			return Vector2(screen_size)
	return _gml_display_window_size()


static func _gml_display_dpi():
	if _gml_display_is_headless():
		return 96.0
	return max(float(DisplayServer.screen_get_dpi()), 96.0)


static func _gml_display_window_mouse_position():
	var window_position = _gml_display_viewport_to_window_transform() * _gml_input_mouse_position
	return Vector2(round(window_position.x), round(window_position.y))


static func _gml_display_mouse_screen_position():
	return _gml_display_window_position() + _gml_display_window_mouse_position()


# mouse_x / mouse_y: the room position under the mouse, through the visible
# views (last visible view first), like GameMaker's window_views_mouse_get_*.
static func _gml_mouse_room_position():
	return _gml_view_viewport_to_room(_gml_input_mouse_position)


# Converts a viewport (application surface) position to a room position through the views.
static func _gml_view_viewport_to_room(position):
	var state = _gml_view_active_state()
	var mouse = Vector2(position)
	if not bool(state["enabled"]):
		return _gml_view_mouse_default_room_position(state, mouse)
	var display_scale = _gml_view_display_scale(state, _gml_display_application_surface_size())
	var visible = state["arrays"]["view_visible"]
	var cameras = state["arrays"]["view_camera"]
	for view_index in range(GML_VIEW_COUNT - 1, -1, -1):
		if not _gml_view_flag(visible[view_index]):
			continue
		var camera = _gml_camera_resolve(cameras[view_index])
		if camera == null:
			continue
		var world = _gml_view_mouse_world(state, view_index, camera, mouse, display_scale)
		if world == null:
			continue
		world = world.floor()
		if world.x >= camera["x"] and world.x < camera["x"] + camera["width"] and world.y >= camera["y"] and world.y < camera["y"] + camera["height"]:
			return world
	return _gml_view_viewport_to_view(mouse, 0)


# -----------------------------------------------------------------------------
# Private view helpers
# -----------------------------------------------------------------------------


static func _gml_view_is_builtin_array(name):
	var key = str(name)
	return GML_VIEW_PORT_ARRAY_NAMES.has(key) or GML_VIEW_LEGACY_CAMERA_FIELDS.has(key)


static func _gml_view_builtin_array(name):
	var key = str(name)
	var state = _gml_view_active_state()
	if GML_VIEW_LEGACY_CAMERA_FIELDS.has(key):
		_gml_view_legacy_active = true
		_gml_view_legacy_sync(state)
		return _gml_builtin_arrays[key]
	return state["arrays"][key]


# The view state of the running room. Converted rooms prepare it from their
# _enter_tree hook; any other current scene is prepared on first use.
static func _gml_view_active_state():
	var current_scene = null
	var loop = Engine.get_main_loop()
	if loop is SceneTree and is_instance_valid(loop.current_scene):
		current_scene = loop.current_scene
	var state_is_current = false
	if _gml_view_state != null:
		var scene = _gml_view_state["scene"]
		if scene != null and is_instance_valid(scene) and scene.is_inside_tree():
			state_is_current = true
		elif scene == null and current_scene == null:
			state_is_current = true
	if not state_is_current:
		if current_scene != null:
			_gml_view_activate_scene(current_scene)
		else:
			_gml_view_activate_state(_gml_view_state_create(null))
	# Assignments to the view_enabled built-in land in the global scope.
	if _gml_global_scope.has("view_enabled"):
		_gml_view_state["enabled"] = gml_bool(_gml_global_scope["view_enabled"])
		_gml_global_scope.erase("view_enabled")
	return _gml_view_state


static func _gml_view_activate_scene(scene):
	if _gml_view_state != null and is_same(_gml_view_state["scene"], scene):
		return
	var state = scene.get_meta(GML_VIEW_STATE_META) if scene.has_meta(GML_VIEW_STATE_META) else null
	if not (state is Dictionary):
		state = _gml_view_state_create(scene)
		scene.set_meta(GML_VIEW_STATE_META, state)
	_gml_view_activate_state(state)


static func _gml_view_activate_state(state):
	var previous = _gml_view_state
	if previous is Dictionary and not is_same(previous, state) and not bool(previous["persistent"]):
		# GameMaker destroys the cameras it created for a room's views when the
		# room ends (unless the room is persistent).
		for handle in previous["room_cameras"]:
			if gml_handle_is_valid(handle) and not _gml_camera_handles_match(handle, _gml_default_camera_handle):
				gml_handle_invalidate(handle)
	_gml_view_state = state
	_gml_active_camera_handle = null
	_gml_view_legacy_shadow = {}
	for name in GML_VIEW_PORT_ARRAY_NAMES:
		_gml_builtin_arrays[name] = state["arrays"][name]


static func _gml_view_state_create(scene):
	var room_size = _gml_view_metadata_room_size(scene)
	var room_size_known = room_size.x > 0.0 and room_size.y > 0.0
	if not room_size_known:
		room_size = _gml_view_builtin_room_size()
	var enabled = false
	var persistent = false
	var entries = []
	if scene is Node:
		var settings = scene.get_meta("gamemaker_view_settings") if scene.has_meta("gamemaker_view_settings") else {}
		if settings is Dictionary:
			enabled = gml_bool(settings.get("enableViews", false))
		var metadata_entries = scene.get_meta("gamemaker_views") if scene.has_meta("gamemaker_views") else []
		if metadata_entries is Array:
			entries = metadata_entries
		if scene.has_meta("gamemaker_room_persistent"):
			persistent = gml_bool(scene.get_meta("gamemaker_room_persistent"))
	var arrays = {}
	for name in GML_VIEW_PORT_ARRAY_NAMES:
		arrays[name] = []
	var cameras = []
	for view_index in range(GML_VIEW_COUNT):
		var entry = entries[view_index] if view_index < entries.size() and entries[view_index] is Dictionary else {}
		var camera = _gml_camera_from_view_entry(entry, room_size)
		var handle = gml_handle_register(GML_CAMERA_HANDLE_KIND, camera)
		cameras.append(handle)
		arrays["view_camera"].append(handle)
		arrays["view_visible"].append(gml_bool(entry.get("visible", false)))
		arrays["view_xport"].append(int(_to_real(entry.get("xport", 0))))
		arrays["view_yport"].append(int(_to_real(entry.get("yport", 0))))
		arrays["view_wport"].append(int(_to_real(entry.get("wport", room_size.x))))
		arrays["view_hport"].append(int(_to_real(entry.get("hport", room_size.y))))
		arrays["view_surface_id"].append(-1)
	return {
		"scene": scene,
		"enabled": enabled,
		"room_size": room_size if room_size_known else Vector2.ZERO,
		"persistent": persistent,
		"arrays": arrays,
		"room_cameras": cameras,
	}


static func _gml_view_metadata_room_size(scene):
	if not (scene is Node):
		return Vector2.ZERO
	if not scene.has_meta("gamemaker_room_width") or not scene.has_meta("gamemaker_room_height"):
		return Vector2.ZERO
	return Vector2(_to_real(scene.get_meta("gamemaker_room_width")), _to_real(scene.get_meta("gamemaker_room_height")))


static func _gml_view_builtin_room_size():
	var width = _to_real(_gml_builtin_globals.get("room_width", 0))
	var height = _to_real(_gml_builtin_globals.get("room_height", 0))
	if width > 0.0 and height > 0.0:
		return Vector2(width, height)
	return _gml_display_application_surface_size()


# The running room's size: from the room scene's metadata, or the room_width /
# room_height built-ins for scenes that are not converted rooms.
static func _gml_view_room_size(state):
	var room_size = state["room_size"]
	if room_size.x > 0.0 and room_size.y > 0.0:
		return room_size
	return _gml_view_builtin_room_size()


static func _gml_camera_from_view_entry(entry, room_size):
	var object = -1
	var object_name = entry.get("object", null)
	if object_name is String and object_name != "":
		object = gml_asset_get_index(object_name)
		if is_numeric(object) and _to_real(object) < 0.0:
			# Not in the asset registry: follow instances registered by name.
			object = object_name
	return _gml_camera_make(
		_to_real(entry.get("xview", 0)),
		_to_real(entry.get("yview", 0)),
		_to_real(entry.get("wview", room_size.x)),
		_to_real(entry.get("hview", room_size.y)),
		0.0,
		object,
		_to_real(entry.get("hborder", 32)),
		_to_real(entry.get("vborder", 32)),
		_to_real(entry.get("hspeed", -1)),
		_to_real(entry.get("vspeed", -1))
	)


static func _gml_view_index(view_port):
	if not is_numeric(view_port):
		return GML_VIEW_INVALID_INDEX
	var view_index = int(_to_real(view_port))
	if view_index < 0 or view_index >= GML_VIEW_COUNT:
		return GML_VIEW_INVALID_INDEX
	return view_index


static func _gml_view_array_get(view_port, name, fallback):
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return fallback
	var values = _gml_view_active_state()["arrays"][name]
	if view_index >= values.size():
		return fallback
	return values[view_index]


static func _gml_view_array_set(view_port, name, value):
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return
	var values = _gml_view_active_state()["arrays"][name]
	if view_index < values.size():
		values[view_index] = value


static func _gml_is_invalid_view_reference(value):
	if is_undefined(value) or value == null:
		return true
	if is_numeric(value):
		return int(_to_real(value)) == -1
	return false


# The view presented on screen: the first visible view rendering to the
# application surface, else the first visible view rendering to a surface.
static func _gml_view_primary_index(state):
	var arrays = state["arrays"]
	var surface_view = -1
	var visible_count = 0
	var primary = -1
	var visible = arrays["view_visible"]
	for view_index in range(GML_VIEW_COUNT):
		if not _gml_view_flag(visible[view_index]):
			continue
		visible_count += 1
		if primary >= 0 or _gml_camera_resolve(arrays["view_camera"][view_index]) == null:
			continue
		if _gml_is_invalid_view_reference(arrays["view_surface_id"][view_index]):
			primary = view_index
		elif surface_view < 0:
			surface_view = view_index
	if visible_count > 1:
		_gml_view_backend_record_diagnostic(
			"multi_view",
			"GM2Godot stores multiple active GameMaker views as compatibility state; render-backed split viewports require a custom SubViewport pipeline."
		)
	return primary if primary >= 0 else surface_view


# GameMaker scales the visible viewports so that their bounding box fills the
# application surface (UpdateViews: display scale = app size / port extent);
# each port is then multiplied by that scale.
static func _gml_view_display_scale(state, app):
	var arrays = state["arrays"]
	var visible = arrays["view_visible"]
	var left = INF
	var top = INF
	var right = -INF
	var bottom = -INF
	for index in range(GML_VIEW_COUNT):
		if not _gml_view_flag(visible[index]):
			continue
		var x = _gml_view_number(arrays["view_xport"][index])
		var y = _gml_view_number(arrays["view_yport"][index])
		left = minf(left, x)
		top = minf(top, y)
		right = maxf(right, x + _gml_view_number(arrays["view_wport"][index]))
		bottom = maxf(bottom, y + _gml_view_number(arrays["view_hport"][index]))
	if right > left and bottom > top:
		return Vector2(app.x / (right - left), app.y / (bottom - top))
	return Vector2.ONE


static func _gml_view_port_rect(state, view_index, display_scale):
	var arrays = state["arrays"]
	var port_position = Vector2(_gml_view_number(arrays["view_xport"][view_index]), _gml_view_number(arrays["view_yport"][view_index]))
	var port_size = Vector2(_gml_view_number(arrays["view_wport"][view_index]), _gml_view_number(arrays["view_hport"][view_index]))
	return Rect2(port_position * display_scale, port_size * display_scale)


# View array values are usually plain bools and numbers; skip the general GML
# conversions for them.
static func _gml_view_flag(value):
	if typeof(value) == TYPE_BOOL:
		return value
	return gml_bool(value)


static func _gml_view_number(value):
	var value_type = typeof(value)
	if value_type == TYPE_FLOAT:
		return value
	if value_type == TYPE_INT:
		return float(value)
	return _to_real(value)


# Camera fields always hold floats: values GML cannot convert keep the fallback.
static func _gml_camera_real(value, fallback = 0.0):
	var number = _gml_view_number(value)
	if typeof(number) == TYPE_FLOAT:
		return number
	return float(fallback)


# Per-frame camera update for the visible views (GameMaker's UpdateViews).
static func _gml_view_update_cameras(state):
	if _gml_view_legacy_active:
		_gml_view_legacy_sync(state)
	var room_size = _gml_view_room_size(state)
	if bool(state["enabled"]):
		var arrays = state["arrays"]
		for view_index in range(GML_VIEW_COUNT):
			if not gml_bool(arrays["view_visible"][view_index]):
				continue
			var camera = _gml_camera_resolve(arrays["view_camera"][view_index])
			if camera != null:
				_gml_camera_follow(camera, room_size)
	else:
		# Rooms without views draw through the default camera covering the room.
		var default_camera = _gml_camera_resolve(gml_camera_get_default())
		if default_camera != null:
			default_camera["x"] = 0.0
			default_camera["y"] = 0.0
			default_camera["width"] = room_size.x
			default_camera["height"] = room_size.y
			default_camera["angle"] = 0.0
			if _gml_camera_is_2d(default_camera):
				_gml_camera_build_2d_view(default_camera)
	if _gml_view_legacy_active:
		_gml_view_legacy_sync(state)


# CCamera::Update: follow the first active instance of the target object (or
# the target instance) with GameMaker's border, room-clamp and speed rules.
static func _gml_camera_follow(camera, room_size):
	var target = camera["object"]
	if not _gml_camera_target_is_set(target) or not _gml_camera_is_2d(camera):
		return
	var targets = gml_with_targets(target)
	if targets.is_empty():
		return
	var target_position = _gml_instance_position(targets[0])
	var ix = floor(target_position.x)
	var iy = floor(target_position.y)
	var view_x = _to_real(camera["x"])
	var view_y = _to_real(camera["y"])
	var view_w = _to_real(camera["width"])
	var view_h = _to_real(camera["height"])
	var left = _gml_camera_follow_axis(view_x, view_w, ix, _to_real(camera["hborder"]))
	var top = _gml_camera_follow_axis(view_y, view_h, iy, _to_real(camera["vborder"]))
	if left < 0.0:
		left = 0.0
	if left + view_w > room_size.x:
		left = room_size.x - view_w
	if top < 0.0:
		top = 0.0
	if top + view_h > room_size.y:
		top = room_size.y - view_h
	camera["x"] = _gml_camera_limit_speed(view_x, left, _to_real(camera["hspeed"]))
	camera["y"] = _gml_camera_limit_speed(view_y, top, _to_real(camera["vspeed"]))
	_gml_camera_build_2d_view(camera)


static func _gml_camera_follow_axis(view_start, view_size, target, border):
	if 2.0 * border >= view_size:
		return target - view_size * 0.5
	if target - border < view_start:
		return target - border
	if target + border > view_start + view_size:
		return target + border - view_size
	return view_start


static func _gml_camera_limit_speed(current, desired, speed):
	if speed < 0.0:
		return desired
	if desired < current and current - desired > speed:
		return current - speed
	if desired > current and desired - current > speed:
		return current + speed
	return desired


static func _gml_camera_target_is_set(target):
	if is_undefined(target) or target == null:
		return false
	if is_numeric(target):
		return _to_real(target) >= 0.0
	if is_handle(target):
		return gml_handle_is_valid(target)
	return true


# Presents the view state on the room's Camera2D: the primary view's camera
# mapped onto its scaled port, or the whole room onto the application surface
# when views are disabled.
static func _gml_view_present(state):
	if not (state is Dictionary):
		return
	var camera_node = _gml_view_presenter(state["scene"])
	if camera_node == null:
		return
	var app = _gml_display_application_surface_size()
	var room_size = _gml_view_room_size(state)
	var view = {"center": room_size * 0.5, "size": room_size, "angle": 0.0}
	var port = Rect2(Vector2.ZERO, app)
	if bool(state["enabled"]):
		var primary = _gml_view_primary_index(state)
		if primary >= 0:
			var camera = _gml_camera_resolve(state["arrays"]["view_camera"][primary])
			var camera_view = _gml_camera_presentation(camera)
			if not camera_view.is_empty():
				view = camera_view
				if _gml_is_invalid_view_reference(state["arrays"]["view_surface_id"][primary]):
					port = _gml_view_port_rect(state, primary, _gml_view_display_scale(state, app))
	var view_size = view["size"]
	if view_size.x <= GML_CAMERA_EPSILON or view_size.y <= GML_CAMERA_EPSILON:
		return
	if port.size.x <= GML_CAMERA_EPSILON or port.size.y <= GML_CAMERA_EPSILON:
		return
	var zoom = port.size / view_size
	var angle = float(view["angle"])
	var port_offset = (port.get_center() - app * 0.5) / zoom
	var position = view["center"] - port_offset.rotated(angle)
	_gml_view_configure_presenter(camera_node)
	var changed = false
	if camera_node.zoom != zoom:
		camera_node.zoom = zoom
		changed = true
	if not is_equal_approx(camera_node.rotation, angle):
		camera_node.rotation = angle
		changed = true
	if camera_node.position != position:
		camera_node.position = position
		changed = true
	if not camera_node.enabled:
		camera_node.enabled = true
	if camera_node.is_inside_tree():
		if not camera_node.is_current():
			camera_node.make_current()
			changed = true
		if changed:
			camera_node.force_update_scroll()


# One-time Camera2D setup: GameMaker views have no limits, smoothing or drag,
# and rotate with the view angle.
static func _gml_view_configure_presenter(camera_node):
	if camera_node.has_meta(GML_VIEW_PRESENTER_READY_META):
		return
	camera_node.ignore_rotation = false
	camera_node.limit_enabled = false
	camera_node.position_smoothing_enabled = false
	camera_node.rotation_smoothing_enabled = false
	camera_node.drag_horizontal_enabled = false
	camera_node.drag_vertical_enabled = false
	camera_node.anchor_mode = Camera2D.ANCHOR_MODE_DRAG_CENTER
	camera_node.offset = Vector2.ZERO
	camera_node.set_meta(GML_VIEW_PRESENTER_READY_META, true)


static func _gml_view_presenter(scene):
	if not (scene is Node) or not is_instance_valid(scene):
		return null
	var node = scene.get_node_or_null(GML_VIEW_CAMERA_NODE_PATH)
	if node is Camera2D:
		return node
	for child in scene.get_children():
		if child is Camera2D and child.has_meta(GML_VIEW_CAMERA_NODE_META):
			return child
	return null


static func _gml_view_ensure_presenter(scene, can_add_child):
	if _gml_view_presenter(scene) != null or not can_add_child:
		return
	if not (scene is Node2D) or not is_instance_valid(scene):
		return
	var camera_node = Camera2D.new()
	camera_node.name = GML_VIEW_CAMERA_NODE_NAME
	camera_node.set_meta(GML_VIEW_CAMERA_NODE_META, true)
	_gml_view_configure_presenter(camera_node)
	scene.add_child(camera_node)


static func _gml_view_mouse_world(state, view_index, camera, mouse, display_scale):
	var port = _gml_view_port_rect(state, view_index, display_scale)
	if port.size.x == 0.0 or port.size.y == 0.0:
		return null
	var clip = ((mouse - port.position) / port.size) * 2.0 - Vector2.ONE
	return _gml_camera_clip_to_world(camera, clip)


static func _gml_view_mouse_in_view(view_port):
	return _gml_view_viewport_to_view(_gml_input_mouse_position, view_port)


static func _gml_view_viewport_to_view(position, view_port):
	var state = _gml_view_active_state()
	var mouse = Vector2(position)
	if not bool(state["enabled"]):
		return _gml_view_mouse_default_room_position(state, mouse)
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return Vector2.ZERO
	var camera = _gml_camera_resolve(state["arrays"]["view_camera"][view_index])
	if camera == null:
		return Vector2.ZERO
	var display_scale = _gml_view_display_scale(state, _gml_display_application_surface_size())
	var world = _gml_view_mouse_world(state, view_index, camera, mouse, display_scale)
	if world == null:
		return Vector2.ZERO
	return world.floor()


static func _gml_view_mouse_default_room_position(state, mouse):
	var app = _gml_display_application_surface_size()
	var room_size = _gml_view_room_size(state)
	if app.x <= 0.0 or app.y <= 0.0:
		return mouse.floor()
	return (mouse * room_size / app).floor()


static func _gml_view_backend_record_diagnostic(key, message):
	if _gml_view_backend_diagnostic_keys.has(key):
		return
	_gml_view_backend_diagnostic_keys[key] = true
	_gml_view_backend_diagnostics.append(str(message))
	push_warning(str(message))


# Keeps the GameMaker 1.x view arrays (view_xview, ...) in step with the view
# cameras: values written into an array since the last sync are applied to
# that view's camera, then every array is refreshed from its camera.
static func _gml_view_legacy_sync(state):
	var cameras = state["arrays"]["view_camera"]
	var rebuild = {}
	for name in GML_VIEW_LEGACY_CAMERA_FIELDS.keys():
		var field = GML_VIEW_LEGACY_CAMERA_FIELDS[name]
		var values = _gml_builtin_arrays.get(name, null)
		var shadow = _gml_view_legacy_shadow.get(name, null)
		if not (values is Array) or not (shadow is Array):
			continue
		for view_index in range(min(values.size(), shadow.size())):
			if _gml_view_values_equal(values[view_index], shadow[view_index]):
				continue
			var camera = _gml_camera_resolve(cameras[view_index])
			if camera == null:
				continue
			camera[field] = values[view_index] if field == "object" else _gml_camera_real(values[view_index], camera[field])
			if GML_VIEW_LEGACY_RECT_FIELDS.has(field):
				rebuild[view_index] = camera
	for camera in rebuild.values():
		_gml_camera_build_2d_view(camera)
	for name in GML_VIEW_LEGACY_CAMERA_FIELDS.keys():
		var field = GML_VIEW_LEGACY_CAMERA_FIELDS[name]
		var values = []
		for view_index in range(GML_VIEW_COUNT):
			var camera = _gml_camera_resolve(cameras[view_index])
			if camera == null:
				values.append(-1 if field == "object" else 0)
			else:
				values.append(camera[field])
		var target = _gml_builtin_arrays.get(name, null)
		if target is Array:
			target.resize(GML_VIEW_COUNT)
			for view_index in range(GML_VIEW_COUNT):
				target[view_index] = values[view_index]
		else:
			_gml_builtin_arrays[name] = _gml_clone_value(values, 0)
		_gml_view_legacy_shadow[name] = values


static func _gml_view_values_equal(left, right):
	if is_numeric(left) and is_numeric(right):
		return _to_real(left) == _to_real(right)
	if typeof(left) != typeof(right):
		return false
	if left is Object:
		return is_same(left, right)
	return left == right


# -----------------------------------------------------------------------------
# Private camera helpers
# -----------------------------------------------------------------------------


static func _gml_camera_make(x, y, width, height, angle, object, hborder, vborder, hspeed, vspeed):
	var camera = {
		"x": float(x),
		"y": float(y),
		"width": float(width),
		"height": float(height),
		"angle": float(angle),
		"object": object,
		"hborder": float(hborder),
		"vborder": float(vborder),
		"hspeed": float(hspeed),
		"vspeed": float(vspeed),
		"view_matrix": [],
		"projection_matrix": [],
		"matrices_custom": false,
	}
	_gml_camera_build_2d_view(camera)
	return camera


# The camera's state dictionary, or null for anything that is not a live camera.
static func _gml_camera_resolve(camera):
	var camera_state: Variant = null
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY:
		camera_state = handle.reference
	return camera_state


static func _gml_camera_get_field(camera, field):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return -1
	if _gml_view_legacy_active:
		_gml_view_legacy_sync(_gml_view_active_state())
	return camera_state[field]


static func _gml_camera_handles_match(left, right):
	if not is_handle(left) or not is_handle(right):
		return false
	return left.kind == right.kind and left.index == right.index and left.type_id == right.type_id


static func _gml_camera_matrix_values(matrix):
	if not (matrix is Array) or matrix.size() < 16:
		return []
	var values = []
	for index in range(16):
		values.append(_to_real(matrix[index]))
	return values


# CCamera::Build2DView: LookAtLH from (cx, cy, -16000) to (cx, cy, 0) with
# up = (sin(-angle), cos(-angle), 0), and OrthoLH(width, height, 1, 32000).
static func _gml_camera_build_2d_view(camera):
	var width = _to_real(camera["width"])
	var height = _to_real(camera["height"])
	var center_x = _to_real(camera["x"]) + width * 0.5
	var center_y = _to_real(camera["y"]) + height * 0.5
	var radians = deg_to_rad(-_to_real(camera["angle"]))
	var up_x = sin(radians)
	var up_y = cos(radians)
	var right_x = up_y
	var right_y = -up_x
	camera["view_matrix"] = [
		right_x, up_x, 0.0, 0.0,
		right_y, up_y, 0.0, 0.0,
		0.0, 0.0, 1.0, 0.0,
		-(right_x * center_x + right_y * center_y), -(up_x * center_x + up_y * center_y), -GML_CAMERA_2D_EYE_Z, 1.0
	]
	camera["projection_matrix"] = _gml_camera_ortho_lh(width, height, GML_CAMERA_2D_ZNEAR, GML_CAMERA_2D_ZFAR)
	camera["matrices_custom"] = false


static func _gml_camera_ortho_lh(width, height, znear, zfar):
	if width == 0.0 or height == 0.0 or znear == zfar:
		return _gml_camera_identity_matrix()
	return [
		2.0 / width, 0.0, 0.0, 0.0,
		0.0, 2.0 / height, 0.0, 0.0,
		0.0, 0.0, 1.0 / (zfar - znear), 0.0,
		0.0, 0.0, znear / (znear - zfar), 1.0
	]


static func _gml_camera_identity_matrix():
	return [
		1.0, 0.0, 0.0, 0.0,
		0.0, 1.0, 0.0, 0.0,
		0.0, 0.0, 1.0, 0.0,
		0.0, 0.0, 0.0, 1.0
	]


# CCamera::Update2D: following only applies to cameras with a 2D (orthographic,
# unsheared, axis-aligned in z) projection.
static func _gml_camera_is_2d(camera):
	var projection = camera["projection_matrix"]
	var view = camera["view_matrix"]
	if projection.size() < 16 or view.size() < 16:
		return false
	if projection[11] != 0.0:
		return false
	for index in [1, 2, 4, 6, 8, 9]:
		if projection[index] != 0.0:
			return false
	return view[2] == 0.0 and view[6] == 0.0


# The room-space rectangle a camera shows: {center, size, angle (radians)}.
# Built-in 2D cameras use their stored view; custom view/projection matrices
# are inverted (perspective cameras are intersected with the z = 0 plane).
static func _gml_camera_presentation(camera):
	if camera == null:
		return {}
	var width = float(camera["width"])
	var height = float(camera["height"])
	if not bool(camera["matrices_custom"]) and width > 0.0 and height > 0.0:
		return {
			"center": Vector2(float(camera["x"]) + width * 0.5, float(camera["y"]) + height * 0.5),
			"size": Vector2(width, height),
			"angle": deg_to_rad(float(camera["angle"])),
		}
	# Matrices are replaced, never edited in place: cache by array identity.
	var cache = camera.get("presentation_cache", null)
	if cache is Array and is_same(cache[0], camera["view_matrix"]) and is_same(cache[1], camera["projection_matrix"]):
		return cache[2]
	var presentation = _gml_camera_matrix_presentation(camera)
	camera["presentation_cache"] = [camera["view_matrix"], camera["projection_matrix"], presentation]
	return presentation


static func _gml_camera_matrix_presentation(camera):
	var inverse = _gml_camera_inverse_view_projection(camera)
	if inverse.is_empty():
		return {}
	var perspective = camera["projection_matrix"][11] != 0.0
	var center = _gml_camera_unproject(inverse, 0.0, 0.0, perspective)
	var across = _gml_camera_unproject(inverse, 1.0, 0.0, perspective) - _gml_camera_unproject(inverse, -1.0, 0.0, perspective)
	var down = _gml_camera_unproject(inverse, 0.0, 1.0, perspective) - _gml_camera_unproject(inverse, 0.0, -1.0, perspective)
	var size = Vector2(across.length(), down.length())
	if not center.is_finite() or not size.is_finite() or size.x <= GML_CAMERA_EPSILON or size.y <= GML_CAMERA_EPSILON:
		return {}
	return {"center": center, "size": size, "angle": atan2(-down.x, down.y)}


# Converts a clip-space point (x right, y down, -1..1 across the port) to a room position,
# the way GameMaker back-projects mouse coordinates (z = 0, w = 1).
static func _gml_camera_clip_to_world(camera, clip):
	var width = float(camera["width"])
	var height = float(camera["height"])
	if not bool(camera["matrices_custom"]) and width > 0.0 and height > 0.0:
		var center = Vector2(float(camera["x"]) + width * 0.5, float(camera["y"]) + height * 0.5)
		return center + (clip * Vector2(width, height) * 0.5).rotated(deg_to_rad(float(camera["angle"])))
	var inverse = _gml_camera_inverse_view_projection(camera)
	if inverse.is_empty():
		return null
	return _gml_camera_unproject(inverse, clip.x, clip.y, false)


static func _gml_camera_inverse_view_projection(camera):
	var view = camera["view_matrix"]
	var projection = camera["projection_matrix"]
	if view.size() < 16 or projection.size() < 16:
		return []
	var cache = camera.get("inverse_cache", null)
	if cache is Array and is_same(cache[0], view) and is_same(cache[1], projection):
		return cache[2]
	var inverse = _gml_camera_matrix_inverse(_gml_camera_matrix_multiply(view, projection))
	camera["inverse_cache"] = [view, projection, inverse]
	return inverse


static func _gml_camera_unproject(inverse, clip_x, clip_y, perspective):
	var near = _gml_camera_matrix_transform(inverse, clip_x, clip_y, 0.0)
	if not perspective:
		return Vector2(near[0], near[1])
	var far = _gml_camera_matrix_transform(inverse, clip_x, clip_y, 1.0)
	if near[3] == 0.0 or far[3] == 0.0:
		return Vector2(INF, INF)
	var near_point = Vector3(near[0], near[1], near[2]) / near[3]
	var far_point = Vector3(far[0], far[1], far[2]) / far[3]
	var depth = far_point.z - near_point.z
	if abs(depth) <= GML_CAMERA_EPSILON:
		return Vector2(near_point.x, near_point.y)
	var t = -near_point.z / depth
	return Vector2(near_point.x + (far_point.x - near_point.x) * t, near_point.y + (far_point.y - near_point.y) * t)


# Row-vector [x, y, z, 1] * m for a flat 16-element GameMaker matrix.
static func _gml_camera_matrix_transform(m, x, y, z):
	return [
		x * m[0] + y * m[4] + z * m[8] + m[12],
		x * m[1] + y * m[5] + z * m[9] + m[13],
		x * m[2] + y * m[6] + z * m[10] + m[14],
		x * m[3] + y * m[7] + z * m[11] + m[15],
	]


static func _gml_camera_matrix_multiply(a, b):
	var result = []
	result.resize(16)
	for row in range(4):
		for column in range(4):
			var total = 0.0
			for k in range(4):
				total += float(a[row * 4 + k]) * float(b[k * 4 + column])
			result[row * 4 + column] = total
	return result


static func _gml_camera_matrix_inverse(m):
	var s0 = m[0] * m[5] - m[4] * m[1]
	var s1 = m[0] * m[6] - m[4] * m[2]
	var s2 = m[0] * m[7] - m[4] * m[3]
	var s3 = m[1] * m[6] - m[5] * m[2]
	var s4 = m[1] * m[7] - m[5] * m[3]
	var s5 = m[2] * m[7] - m[6] * m[3]
	var c5 = m[10] * m[15] - m[14] * m[11]
	var c4 = m[9] * m[15] - m[13] * m[11]
	var c3 = m[9] * m[14] - m[13] * m[10]
	var c2 = m[8] * m[15] - m[12] * m[11]
	var c1 = m[8] * m[14] - m[12] * m[10]
	var c0 = m[8] * m[13] - m[12] * m[9]
	var determinant = s0 * c5 - s1 * c4 + s2 * c3 + s3 * c2 - s4 * c1 + s5 * c0
	if determinant == 0.0 or is_nan(determinant) or is_inf(determinant):
		return []
	var inv = 1.0 / determinant
	return [
		(m[5] * c5 - m[6] * c4 + m[7] * c3) * inv,
		(-m[1] * c5 + m[2] * c4 - m[3] * c3) * inv,
		(m[13] * s5 - m[14] * s4 + m[15] * s3) * inv,
		(-m[9] * s5 + m[10] * s4 - m[11] * s3) * inv,
		(-m[4] * c5 + m[6] * c2 - m[7] * c1) * inv,
		(m[0] * c5 - m[2] * c2 + m[3] * c1) * inv,
		(-m[12] * s5 + m[14] * s2 - m[15] * s1) * inv,
		(m[8] * s5 - m[10] * s2 + m[11] * s1) * inv,
		(m[4] * c4 - m[5] * c2 + m[7] * c0) * inv,
		(-m[0] * c4 + m[1] * c2 - m[3] * c0) * inv,
		(m[12] * s4 - m[13] * s2 + m[15] * s0) * inv,
		(-m[8] * s4 + m[9] * s2 - m[11] * s0) * inv,
		(-m[4] * c3 + m[5] * c1 - m[6] * c0) * inv,
		(m[0] * c3 - m[1] * c1 + m[2] * c0) * inv,
		(-m[12] * s3 + m[13] * s1 - m[14] * s0) * inv,
		(m[8] * s3 - m[9] * s1 + m[10] * s0) * inv,
	]


# -----------------------------------------------------------------------------
# Private window helpers
# -----------------------------------------------------------------------------


static func _gml_window_headless_fullscreen():
	if _gml_window_fullscreen == null:
		_gml_window_fullscreen = int(ProjectSettings.get_setting("display/window/size/mode", 0)) >= Window.MODE_FULLSCREEN
	return bool(_gml_window_fullscreen)


static func _gml_window_cursor_shape(cursor_id):
	if cursor_id == 2:
		return Input.CURSOR_IBEAM
	if cursor_id == 3:
		return Input.CURSOR_CROSS
	if cursor_id == 6:
		return Input.CURSOR_POINTING_HAND
	if cursor_id == 9:
		return Input.CURSOR_MOVE
	if cursor_id == 10:
		return Input.CURSOR_BDIAGSIZE
	if cursor_id == 11:
		return Input.CURSOR_VSIZE
	if cursor_id == 12:
		return Input.CURSOR_FDIAGSIZE
	if cursor_id == 13:
		return Input.CURSOR_HSIZE
	if cursor_id == 1 or cursor_id == 4:
		return Input.CURSOR_WAIT
	return Input.CURSOR_ARROW


static func _gml_capture_screen_image():
	if _gml_display_is_headless():
		return null
	return DisplayServer.screen_get_image_rect(Rect2i(Vector2i.ZERO, DisplayServer.screen_get_size()))


static func _gml_screen_save_path(fname):
	var path = str(fname).replace("\\", "/").strip_edges()
	if path.is_empty():
		return ""
	if not path.contains("://"):
		path = "user://" + path
	var directory = path.get_base_dir()
	if not directory.is_empty():
		DirAccess.make_dir_recursive_absolute(directory)
	return path
