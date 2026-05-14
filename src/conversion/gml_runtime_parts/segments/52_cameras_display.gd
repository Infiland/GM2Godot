const GML_CAMERA_HANDLE_KIND = "camera"
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
static var _gml_display_gui_size = Vector2.ZERO


static func gml_camera_create_view(x, y, w, h, angle, object, hborder, vborder, hspeed, vspeed):
	var camera = _gml_camera_make(
		_to_real(x),
		_to_real(y),
		_to_real(w),
		_to_real(h),
		_to_real(angle),
		object,
		_to_real(hborder),
		_to_real(vborder),
		_to_real(hspeed),
		_to_real(vspeed),
		-1
	)
	return gml_handle_register(GML_CAMERA_HANDLE_KIND, camera)


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


static func _gml_camera_make(x, y, width, height, angle, object, hborder, vborder, hspeed, vspeed, view_index):
	return {
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
		"node": null
	}


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
	camera["angle"] = node.rotation_degrees


static func _gml_camera_apply_state(camera):
	var node = camera["node"]
	if not (node is Camera2D):
		return
	node.position = Vector2(_to_real(camera["x"]) + (_to_real(camera["width"]) * 0.5), _to_real(camera["y"]) + (_to_real(camera["height"]) * 0.5))
	node.rotation_degrees = _to_real(camera["angle"])
	node.limit_left = int(_to_real(camera["x"]))
	node.limit_top = int(_to_real(camera["y"]))
	node.limit_right = int(_to_real(camera["x"]) + _to_real(camera["width"]))
	node.limit_bottom = int(_to_real(camera["y"]) + _to_real(camera["height"]))


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
