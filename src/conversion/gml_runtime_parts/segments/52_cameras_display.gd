const GML_CAMERA_HANDLE_KIND = "camera"
const GML_VIEW_INVALID_INDEX = -1
const GML_VIEW_ARRAY_NAMES = {
	"view_angle": true,
	"view_camera": true,
	"view_current": true,
	"view_enabled": true,
	"view_hborder": true,
	"view_hport": true,
	"view_hspeed": true,
	"view_hview": true,
	"view_object": true,
	"view_surface_id": true,
	"view_vborder": true,
	"view_visible": true,
	"view_vspeed": true,
	"view_wport": true,
	"view_wview": true,
	"view_xport": true,
	"view_xview": true,
	"view_yport": true,
	"view_yview": true
}

static var _gml_camera_entries_by_index = {}
static var _gml_active_camera_handle = null
static var _gml_default_camera_handle = null
static var _gml_display_gui_size = Vector2.ZERO


static func gml_camera_create():
	var size = _gml_application_surface_size()
	var camera = _gml_camera_make(0, 0, size.x, size.y, 0, -1, -1, -1, -1, -1, GML_VIEW_INVALID_INDEX)
	return gml_handle_register(GML_CAMERA_HANDLE_KIND, camera)


static func gml_camera_create_view(x, y, w, h, angle, object, x_speed, y_speed, x_border, y_border):
	var camera = _gml_camera_make(
		_to_real(x),
		_to_real(y),
		_to_real(w),
		_to_real(h),
		_to_real(angle),
		object,
		_to_real(x_border),
		_to_real(y_border),
		_to_real(x_speed),
		_to_real(y_speed),
		-1
	)
	return gml_handle_register(GML_CAMERA_HANDLE_KIND, camera)


static func gml_camera_destroy(camera):
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if not gml_handle_is_valid(handle):
		return null
	if _gml_builtin_arrays.has("view_camera"):
		for view_index in range(GML_BUILTIN_ARRAY_SIZE):
			var assigned_camera = _gml_array_get_default("view_camera", view_index, -1)
			if _gml_camera_handles_match(assigned_camera, handle):
				_gml_array_set_default("view_camera", view_index, -1)
				_gml_camera_entries_by_index.erase(view_index)
	if _gml_camera_handles_match(_gml_active_camera_handle, handle):
		_gml_active_camera_handle = null
	if _gml_camera_handles_match(_gml_default_camera_handle, handle):
		_gml_default_camera_handle = null
	var camera_state = handle.reference
	if typeof(camera_state) == TYPE_DICTIONARY:
		var node = camera_state.get("node", null)
		if node is Camera2D and is_instance_valid(node):
			node.enabled = false
	gml_handle_invalidate(handle)
	return null


static func gml_camera_apply(camera):
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if not gml_handle_is_valid(handle) or typeof(handle.reference) != TYPE_DICTIONARY:
		return null
	var camera_state = handle.reference
	_gml_camera_sync_from_view_arrays(camera_state)
	_gml_camera_update_follow(camera_state)
	_gml_camera_apply_state(camera_state)
	_gml_active_camera_handle = handle
	var node = camera_state.get("node", null)
	if node is Camera2D and is_instance_valid(node):
		node.enabled = true
		if node.is_inside_tree():
			node.make_current()
	return null


static func gml_camera_get_active():
	if gml_handle_is_valid(_gml_active_camera_handle):
		return _gml_active_camera_handle
	var view_index = int(_gml_array_get_default("view_current", 0, 0))
	var view_camera = gml_view_get_camera(view_index)
	if _gml_is_invalid_view_reference(view_camera):
		return gml_camera_get_default()
	return view_camera


static func gml_camera_get_default():
	if gml_handle_is_valid(_gml_default_camera_handle):
		return _gml_default_camera_handle
	_gml_default_camera_handle = _gml_camera_create_default()
	return _gml_default_camera_handle


static func gml_camera_set_default(camera):
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY:
		_gml_default_camera_handle = handle
	return null


static func gml_camera_set_view_mat(camera, matrix):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["view_matrix"] = _gml_clone_value(matrix, 16)
	camera_state["view_matrix_custom"] = true
	return null


static func gml_camera_get_view_mat(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return _gml_camera_identity_matrix()
	_gml_camera_refresh_matrices(camera_state, false)
	return _gml_clone_value(camera_state["view_matrix"], 16)


static func gml_camera_set_proj_mat(camera, matrix):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["projection_matrix"] = _gml_clone_value(matrix, 16)
	camera_state["projection_matrix_custom"] = true
	return null


static func gml_camera_get_proj_mat(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return _gml_camera_identity_matrix()
	_gml_camera_refresh_matrices(camera_state, false)
	return _gml_clone_value(camera_state["projection_matrix"], 16)


static func gml_camera_set_view_target(camera, target):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["object"] = target
	_gml_camera_sync_view_arrays(camera_state)
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
	camera_state["hspeed"] = _to_real(x_speed)
	camera_state["vspeed"] = _to_real(y_speed)
	_gml_camera_sync_view_arrays(camera_state)
	return null


static func gml_camera_get_view_speed_x(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	return camera_state["hspeed"]


static func gml_camera_get_view_speed_y(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	return camera_state["vspeed"]


static func gml_camera_set_view_border(camera, x_border, y_border):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["hborder"] = _to_real(x_border)
	camera_state["vborder"] = _to_real(y_border)
	_gml_camera_sync_view_arrays(camera_state)
	return null


static func gml_camera_get_view_border_x(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	return camera_state["hborder"]


static func gml_camera_get_view_border_y(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	return camera_state["vborder"]


static func gml_camera_set_view_pos(camera, x, y):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["x"] = _to_real(x)
	camera_state["y"] = _to_real(y)
	_gml_camera_sync_view_arrays(camera_state)
	_gml_camera_apply_state(camera_state)
	return null


static func gml_camera_set_view_size(camera, w, h):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["width"] = max(_to_real(w), 1.0)
	camera_state["height"] = max(_to_real(h), 1.0)
	_gml_camera_sync_view_arrays(camera_state)
	_gml_camera_apply_state(camera_state)
	return null


static func gml_camera_get_view_x(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	_gml_camera_sync_from_view_arrays(camera_state)
	return camera_state["x"]


static func gml_camera_get_view_y(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	_gml_camera_sync_from_view_arrays(camera_state)
	return camera_state["y"]


static func gml_camera_get_view_width(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	_gml_camera_sync_from_view_arrays(camera_state)
	return camera_state["width"]


static func gml_camera_get_view_height(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	_gml_camera_sync_from_view_arrays(camera_state)
	return camera_state["height"]


static func gml_camera_set_view_angle(camera, angle):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return null
	camera_state["angle"] = _to_real(angle)
	_gml_camera_sync_view_arrays(camera_state)
	_gml_camera_apply_state(camera_state)
	return null


static func gml_camera_get_view_angle(camera):
	var camera_state = _gml_camera_resolve(camera)
	if camera_state == null:
		return 0
	_gml_camera_sync_from_view_arrays(camera_state)
	return camera_state["angle"]


static func gml_view_get_camera(view_port):
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return -1
	var camera = _gml_array_get_default("view_camera", view_index, -1)
	if _gml_is_invalid_view_reference(camera):
		return -1
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if gml_handle_is_valid(handle):
		return handle
	_gml_array_set_default("view_camera", view_index, -1)
	_gml_camera_entries_by_index.erase(view_index)
	return -1


static func gml_view_set_camera(view_port, camera):
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return null
	if _gml_is_invalid_view_reference(camera):
		_gml_array_set_default("view_camera", view_index, -1)
		_gml_camera_entries_by_index.erase(view_index)
		return null
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if not gml_handle_is_valid(handle) or typeof(handle.reference) != TYPE_DICTIONARY:
		return null
	var camera_state = handle.reference
	camera_state["view_index"] = view_index
	_gml_camera_entries_by_index[view_index] = {"handle": handle, "camera": camera_state}
	_gml_array_set_default("view_camera", view_index, handle)
	_gml_camera_sync_view_arrays(camera_state)
	_gml_camera_apply_state(camera_state)
	return null


static func gml_view_get_surface_id(view_port):
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return -1
	var surface = _gml_array_get_default("view_surface_id", view_index, -1)
	if _gml_is_invalid_view_reference(surface):
		return -1
	if gml_surface_exists(surface):
		return surface
	_gml_array_set_default("view_surface_id", view_index, -1)
	return -1


static func gml_view_set_surface_id(view_port, surface):
	var view_index = _gml_view_index(view_port)
	if view_index < 0:
		return -1
	if _gml_is_invalid_view_reference(surface):
		_gml_array_set_default("view_surface_id", view_index, -1)
		return -1
	if not gml_surface_exists(surface):
		_gml_array_set_default("view_surface_id", view_index, -1)
		return -1
	_gml_array_set_default("view_surface_id", view_index, surface)
	return surface


static func gml_display_get_gui_width():
	return _gml_display_gui_dimensions().x


static func gml_display_get_gui_height():
	return _gml_display_gui_dimensions().y


static func gml_display_set_gui_size(width, height):
	_gml_display_gui_size = Vector2(max(_to_real(width), 1.0), max(_to_real(height), 1.0))
	return null


static func _gml_view_is_builtin_array(name):
	return GML_VIEW_ARRAY_NAMES.has(str(name))


static func _gml_view_builtin_array(name):
	var key = str(name)
	if not _gml_builtin_arrays.has(key):
		var values = []
		for index in range(GML_BUILTIN_ARRAY_SIZE):
			values.append(_gml_view_default_value(key, index))
		_gml_builtin_arrays[key] = values
	return _gml_builtin_arrays[key]


static func _gml_view_default_value(name, index):
	var size = _gml_application_surface_size()
	if name == "view_camera":
		return _gml_view_camera_handle(index)
	if name == "view_current":
		return 0
	if name == "view_visible" or name == "view_enabled":
		return false
	if name == "view_wview" or name == "view_wport":
		return size.x
	if name == "view_hview" or name == "view_hport":
		return size.y
	if name == "view_object" or name == "view_surface_id":
		return -1
	return 0


static func _gml_view_camera_handle(index):
	var view_index = int(index)
	if _gml_camera_entries_by_index.has(view_index):
		return _gml_camera_entries_by_index[view_index]["handle"]
	var camera_node = _gml_view_find_camera_node(view_index)
	var camera = _gml_camera_make(
		_to_real(_gml_array_get_default("view_xview", view_index, 0)),
		_to_real(_gml_array_get_default("view_yview", view_index, 0)),
		_to_real(_gml_array_get_default("view_wview", view_index, _gml_application_surface_size().x)),
		_to_real(_gml_array_get_default("view_hview", view_index, _gml_application_surface_size().y)),
		_to_real(_gml_array_get_default("view_angle", view_index, 0)),
		_gml_array_get_default("view_object", view_index, -1),
		_to_real(_gml_array_get_default("view_hborder", view_index, 0)),
		_to_real(_gml_array_get_default("view_vborder", view_index, 0)),
		_to_real(_gml_array_get_default("view_hspeed", view_index, 0)),
		_to_real(_gml_array_get_default("view_vspeed", view_index, 0)),
		view_index
	)
	camera["node"] = camera_node
	if camera_node != null:
		_gml_camera_sync_from_node(camera, camera_node)
	var handle = gml_handle_register(GML_CAMERA_HANDLE_KIND, camera, "view_" + str(view_index))
	_gml_camera_entries_by_index[view_index] = {"handle": handle, "camera": camera}
	_gml_camera_sync_view_arrays(camera)
	_gml_camera_apply_state(camera)
	return handle


static func _gml_view_index(view_port):
	var view_index = int(_to_real(view_port))
	if view_index < 0 or view_index >= GML_BUILTIN_ARRAY_SIZE:
		return GML_VIEW_INVALID_INDEX
	return view_index


static func _gml_is_invalid_view_reference(value):
	if is_undefined(value) or value == null:
		return true
	if is_numeric(value):
		return int(_to_real(value)) == -1
	return false


static func _gml_camera_handles_match(left, right):
	if not is_handle(left) or not is_handle(right):
		return false
	return left.kind == right.kind and left.index == right.index and left.type_id == right.type_id


static func _gml_camera_make(x, y, width, height, angle, object, hborder, vborder, hspeed, vspeed, view_index):
	var camera = {
		"x": float(x),
		"y": float(y),
		"width": max(float(width), 1.0),
		"height": max(float(height), 1.0),
		"angle": float(angle),
		"object": object,
		"hborder": float(hborder),
		"vborder": float(vborder),
		"hspeed": float(hspeed),
		"vspeed": float(vspeed),
		"view_index": int(view_index),
		"node": null,
		"view_matrix": [],
		"projection_matrix": [],
		"view_matrix_custom": false,
		"projection_matrix_custom": false
	}
	_gml_camera_refresh_matrices(camera, true)
	return camera


static func _gml_camera_resolve(camera):
	var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, camera)
	if not gml_handle_is_valid(handle):
		return null
	if typeof(handle.reference) == TYPE_DICTIONARY:
		return handle.reference
	return null


static func _gml_camera_sync_view_arrays(camera):
	var view_index = int(camera["view_index"])
	if view_index < 0:
		return
	_gml_array_set_default("view_xview", view_index, camera["x"])
	_gml_array_set_default("view_yview", view_index, camera["y"])
	_gml_array_set_default("view_wview", view_index, camera["width"])
	_gml_array_set_default("view_hview", view_index, camera["height"])
	_gml_array_set_default("view_angle", view_index, camera["angle"])
	_gml_array_set_default("view_object", view_index, camera["object"])
	_gml_array_set_default("view_hborder", view_index, camera["hborder"])
	_gml_array_set_default("view_vborder", view_index, camera["vborder"])
	_gml_array_set_default("view_hspeed", view_index, camera["hspeed"])
	_gml_array_set_default("view_vspeed", view_index, camera["vspeed"])
	if _gml_builtin_arrays.has("view_camera"):
		_gml_array_set_default("view_camera", view_index, _gml_camera_entries_by_index[view_index]["handle"])


static func _gml_camera_sync_from_view_arrays(camera):
	var view_index = int(camera["view_index"])
	if view_index < 0:
		return
	camera["x"] = _to_real(_gml_array_get_default("view_xview", view_index, camera["x"]))
	camera["y"] = _to_real(_gml_array_get_default("view_yview", view_index, camera["y"]))
	camera["width"] = max(_to_real(_gml_array_get_default("view_wview", view_index, camera["width"])), 1.0)
	camera["height"] = max(_to_real(_gml_array_get_default("view_hview", view_index, camera["height"])), 1.0)
	camera["angle"] = _to_real(_gml_array_get_default("view_angle", view_index, camera["angle"]))
	camera["object"] = _gml_array_get_default("view_object", view_index, camera["object"])
	camera["hborder"] = _to_real(_gml_array_get_default("view_hborder", view_index, camera["hborder"]))
	camera["vborder"] = _to_real(_gml_array_get_default("view_vborder", view_index, camera["vborder"]))
	camera["hspeed"] = _to_real(_gml_array_get_default("view_hspeed", view_index, camera["hspeed"]))
	camera["vspeed"] = _to_real(_gml_array_get_default("view_vspeed", view_index, camera["vspeed"]))
	_gml_camera_refresh_matrices(camera, false)


static func _gml_camera_sync_from_node(camera, node):
	if not (node is Camera2D):
		return
	if node.has_meta("gamemaker_view_xview"):
		camera["x"] = _to_real(node.get_meta("gamemaker_view_xview"))
	if node.has_meta("gamemaker_view_yview"):
		camera["y"] = _to_real(node.get_meta("gamemaker_view_yview"))
	if node.has_meta("gamemaker_view_wview"):
		camera["width"] = max(_to_real(node.get_meta("gamemaker_view_wview")), 1.0)
	if node.has_meta("gamemaker_view_hview"):
		camera["height"] = max(_to_real(node.get_meta("gamemaker_view_hview")), 1.0)
	if node.has_meta("gamemaker_view_object_id") and not _gml_is_invalid_view_reference(node.get_meta("gamemaker_view_object_id")):
		camera["object"] = node.get_meta("gamemaker_view_object_id")
	elif node.has_meta("gamemaker_view_object_name") and str(node.get_meta("gamemaker_view_object_name")) != "":
		camera["object"] = str(node.get_meta("gamemaker_view_object_name"))
	if node.has_meta("gamemaker_view_hborder"):
		camera["hborder"] = _to_real(node.get_meta("gamemaker_view_hborder"))
	if node.has_meta("gamemaker_view_vborder"):
		camera["vborder"] = _to_real(node.get_meta("gamemaker_view_vborder"))
	if node.has_meta("gamemaker_view_hspeed"):
		camera["hspeed"] = _to_real(node.get_meta("gamemaker_view_hspeed"))
	if node.has_meta("gamemaker_view_vspeed"):
		camera["vspeed"] = _to_real(node.get_meta("gamemaker_view_vspeed"))
	camera["angle"] = node.rotation_degrees
	_gml_camera_refresh_matrices(camera, false)


static func _gml_camera_apply_state(camera):
	var node = camera["node"]
	_gml_camera_refresh_matrices(camera, false)
	if not (node is Camera2D):
		return
	node.position = Vector2(_to_real(camera["x"]) + (_to_real(camera["width"]) * 0.5), _to_real(camera["y"]) + (_to_real(camera["height"]) * 0.5))
	node.rotation_degrees = _to_real(camera["angle"])
	node.limit_left = int(_to_real(camera["x"]))
	node.limit_top = int(_to_real(camera["y"]))
	node.limit_right = int(_to_real(camera["x"]) + _to_real(camera["width"]))
	node.limit_bottom = int(_to_real(camera["y"]) + _to_real(camera["height"]))


static func _gml_camera_update_visible_views():
	if not _gml_builtin_arrays.has("view_camera"):
		return null
	var values = _gml_builtin_arrays["view_camera"]
	for view_index in range(min(values.size(), GML_BUILTIN_ARRAY_SIZE)):
		var handle = gml_handle_from_value(GML_CAMERA_HANDLE_KIND, values[view_index])
		if not gml_handle_is_valid(handle) or typeof(handle.reference) != TYPE_DICTIONARY:
			continue
		var camera = handle.reference
		if _gml_camera_update_follow(camera):
			_gml_camera_apply_state(camera)
	return null


static func _gml_camera_update_follow(camera):
	if typeof(camera) != TYPE_DICTIONARY:
		return false
	var target = camera.get("object", -1)
	if _gml_is_invalid_view_reference(target):
		return false
	var targets = gml_with_targets(target)
	if targets.is_empty():
		return false
	var target_position = _gml_instance_position(targets[0])
	var next_x = _gml_camera_follow_axis(camera["x"], camera["width"], target_position.x, camera["hborder"], camera["hspeed"])
	var next_y = _gml_camera_follow_axis(camera["y"], camera["height"], target_position.y, camera["vborder"], camera["vspeed"])
	if abs(float(next_x) - float(camera["x"])) < 0.0001 and abs(float(next_y) - float(camera["y"])) < 0.0001:
		return false
	camera["x"] = next_x
	camera["y"] = next_y
	_gml_camera_refresh_matrices(camera, true)
	_gml_camera_sync_view_arrays(camera)
	return true


static func _gml_camera_follow_axis(position, size, target_position, border, speed):
	var current = _to_real(position)
	var span = max(_to_real(size), 1.0)
	var safe_border = max(_to_real(border), 0.0)
	var desired = current
	if _to_real(target_position) < current + safe_border:
		desired = _to_real(target_position) - safe_border
	elif _to_real(target_position) > current + span - safe_border:
		desired = _to_real(target_position) + safe_border - span
	var delta = desired - current
	if abs(delta) < 0.0001:
		return current
	var max_speed = _to_real(speed)
	if max_speed < 0:
		return desired
	if max_speed == 0:
		return current
	return current + sign(delta) * min(abs(delta), max_speed)


static func _gml_camera_create_default():
	var size = _gml_application_surface_size()
	var camera = _gml_camera_make(0, 0, size.x, size.y, 0, -1, -1, -1, -1, -1, GML_VIEW_INVALID_INDEX)
	return gml_handle_register(GML_CAMERA_HANDLE_KIND, camera, "default")


static func _gml_camera_refresh_matrices(camera, force_generated):
	if force_generated or not bool(camera.get("view_matrix_custom", false)):
		camera["view_matrix"] = _gml_camera_build_view_matrix(camera)
		camera["view_matrix_custom"] = false
	if force_generated or not bool(camera.get("projection_matrix_custom", false)):
		camera["projection_matrix"] = _gml_camera_build_projection_matrix(camera)
		camera["projection_matrix_custom"] = false


static func _gml_camera_build_view_matrix(camera):
	var angle = deg_to_rad(-_to_real(camera.get("angle", 0)))
	var cosine = cos(angle)
	var sine = sin(angle)
	var x = _to_real(camera.get("x", 0))
	var y = _to_real(camera.get("y", 0))
	return [
		cosine, -sine, 0.0, 0.0,
		sine, cosine, 0.0, 0.0,
		0.0, 0.0, 1.0, 0.0,
		-x, -y, 0.0, 1.0
	]


static func _gml_camera_build_projection_matrix(camera):
	var width = max(_to_real(camera.get("width", 1)), 1.0)
	var height = max(_to_real(camera.get("height", 1)), 1.0)
	return [
		2.0 / width, 0.0, 0.0, 0.0,
		0.0, -2.0 / height, 0.0, 0.0,
		0.0, 0.0, 1.0, 0.0,
		-1.0, 1.0, 0.0, 1.0
	]


static func _gml_camera_identity_matrix():
	return [
		1.0, 0.0, 0.0, 0.0,
		0.0, 1.0, 0.0, 0.0,
		0.0, 0.0, 1.0, 0.0,
		0.0, 0.0, 0.0, 1.0
	]


static func _gml_view_find_camera_node(view_index):
	var target = _gml_draw_current_context_target()
	if not (target is Node) or not target.is_inside_tree():
		return null
	var scene = target.get_tree().current_scene
	if scene == null:
		scene = target
	return _gml_find_camera_node_recursive(scene, int(view_index))


static func _gml_find_camera_node_recursive(node, view_index):
	if node is Camera2D and node.has_meta("gamemaker_view_index") and int(node.get_meta("gamemaker_view_index")) == view_index:
		return node
	if not (node is Node):
		return null
	for child in node.get_children():
		var result = _gml_find_camera_node_recursive(child, view_index)
		if result != null:
			return result
	return null


static func _gml_array_get_default(name, index, fallback):
	var values = _gml_view_builtin_array(name)
	var resolved_index = int(index)
	if resolved_index < 0 or resolved_index >= values.size():
		return fallback
	var value = values[resolved_index]
	if is_undefined(value):
		return fallback
	return value


static func _gml_array_set_default(name, index, value):
	var values = _gml_view_builtin_array(name)
	var resolved_index = int(index)
	if resolved_index < 0:
		return
	while resolved_index >= values.size():
		values.append(_gml_view_default_value(name, values.size()))
	values[resolved_index] = value


static func _gml_display_gui_dimensions():
	if _gml_display_gui_size.x > 0.0 and _gml_display_gui_size.y > 0.0:
		return _gml_display_gui_size
	return _gml_application_surface_size()
