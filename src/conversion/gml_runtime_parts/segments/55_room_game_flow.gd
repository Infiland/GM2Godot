const GML_ROOM_PERSISTENT_ROOT_NAME = "_GM2GodotPersistentInstances"
const GML_ROOM_UNSUPPORTED_EXIT_MESSAGE = "GM2Godot maps game_end to SceneTree.quit(); platform-specific close prompts and window behavior are not emulated."

static var _gml_room_current_id = -1
static var _gml_room_previous_id = -1
static var _gml_room_game_started = false
static var _gml_room_game_ended = false
static var _gml_room_suppress_auto_enter = false
static var _gml_room_pending_entry = null
static var _gml_room_transition_log = []


static func gml_room_enter_scene(scene, force = false):
	if scene == null:
		return false
	if _gml_room_suppress_auto_enter and not bool(force):
		return false
	var entry = _gml_room_pending_entry if _gml_room_pending_entry != null else _gml_room_entry_for_scene(scene)
	if entry == null:
		return false
	_gml_room_pending_entry = null
	gml_layer_register_scene(scene)
	_gml_view_register_scene(scene)
	_gml_room_update_current(entry, scene)
	_gml_room_warn_persistent_room(scene)
	_gml_room_run_instance_creation_code(scene)
	if not _gml_room_game_started:
		_gml_room_game_started = true
		_gml_room_dispatch_lifecycle(scene, "_on_game_start")
	_gml_room_run_room_creation_code(scene)
	_gml_room_dispatch_lifecycle(scene, "_on_room_start")
	return true


static func gml_room_goto(room_asset):
	var entry = _gml_room_entry(room_asset)
	if entry == null:
		return false
	return _gml_room_change_to_entry(entry, false)


static func gml_room_goto_next():
	var entries = _gml_room_ordered_entries()
	var current_index = _gml_room_order_position(_gml_room_current_id, entries)
	if current_index < 0 or current_index + 1 >= entries.size():
		return false
	return _gml_room_change_to_entry(entries[current_index + 1], false)


static func gml_room_goto_previous():
	var entries = _gml_room_ordered_entries()
	var current_index = _gml_room_order_position(_gml_room_current_id, entries)
	if current_index <= 0:
		return false
	return _gml_room_change_to_entry(entries[current_index - 1], false)


static func gml_room_restart():
	var entry = _gml_room_entry(_gml_room_current_id)
	if entry == null:
		return false
	return _gml_room_change_to_entry(entry, true)


static func gml_game_set_speed(speed, type):
	var resolved_speed = max(int(_to_real(speed)), 0)
	_gml_builtin_globals["room_speed"] = resolved_speed
	if int(_to_real(type)) == 0:
		Engine.max_fps = resolved_speed
	return null


static func gml_game_restart():
	var entries = _gml_room_ordered_entries()
	if entries.is_empty():
		return false
	var tree = _gml_room_tree()
	if tree != null and tree.current_scene != null:
		_gml_room_dispatch_lifecycle(tree.current_scene, "_on_game_end")
	_gml_room_game_started = false
	_gml_room_game_ended = false
	return _gml_room_change_to_entry(entries[0], true)


static func gml_game_end():
	if _gml_room_game_ended:
		return null
	_gml_room_game_ended = true
	var tree = _gml_room_tree()
	if tree != null and tree.current_scene != null:
		_gml_room_dispatch_lifecycle(tree.current_scene, "_on_room_end")
		_gml_room_dispatch_lifecycle(tree.current_scene, "_on_game_end")
		push_warning(GML_ROOM_UNSUPPORTED_EXIT_MESSAGE)
		tree.quit(0)
	else:
		push_warning(GML_ROOM_UNSUPPORTED_EXIT_MESSAGE)
	return null


static func gml_room_exists(room_asset):
	return _gml_room_entry(room_asset) != null


static func gml_room_get_name(room_asset):
	var entry = _gml_room_entry(room_asset)
	if entry == null:
		return ""
	return str(entry["name"])


static func gml_room_get_info(room_asset):
	var entry = _gml_room_entry(room_asset)
	if entry == null:
		return {}
	var metadata = _gml_room_metadata(entry)
	return {
		"id": int(entry["id"]),
		"name": str(entry["name"]),
		"caption": str(entry["name"]),
		"path": str(entry["godot_path"]) if entry.has("godot_path") else "",
		"source_path": str(entry["source_path"]) if entry.has("source_path") else "",
		"order": _gml_room_order_index(entry),
		"width": int(metadata["width"]) if metadata.has("width") else 0,
		"height": int(metadata["height"]) if metadata.has("height") else 0,
		"persistent": bool(metadata["persistent"]) if metadata.has("persistent") else false,
		"volume": _to_real(metadata["volume"]) if metadata.has("volume") else 1.0,
	}


static func gml_room_transition_log():
	return _gml_room_transition_log


static func _gml_room_process_scene(scene, delta):
	if not (scene is Node):
		return false
	_gml_camera_update_visible_views()
	_gml_room_update_background_layers(scene, delta)
	return true


static func _gml_room_change_to_entry(entry, restarting):
	var tree = _gml_room_tree()
	if tree == null:
		return false
	var root = tree.root
	if root == null:
		return false
	var scene_path = str(entry["godot_path"]) if entry.has("godot_path") else ""
	if scene_path == "" or not ResourceLoader.exists(scene_path):
		return false
	var packed_scene = load(scene_path)
	if packed_scene == null or not packed_scene.has_method("instantiate"):
		return false
	var old_scene = tree.current_scene
	if old_scene != null:
		_gml_room_dispatch_lifecycle(old_scene, "_on_room_end")
		_gml_room_capture_persistent_instances(old_scene)
		root.remove_child(old_scene)
		old_scene.queue_free()
	var new_scene = packed_scene.instantiate()
	_gml_room_pending_entry = entry
	_gml_room_suppress_auto_enter = true
	root.add_child(new_scene)
	tree.current_scene = new_scene
	_gml_room_restore_persistent_instances(new_scene)
	_gml_room_suppress_auto_enter = false
	gml_room_enter_scene(new_scene, true)
	_gml_room_transition_log.append({
		"room": str(entry["name"]),
		"room_id": int(entry["id"]),
		"restart": bool(restarting),
	})
	return true


static func _gml_room_update_current(entry, scene):
	_gml_room_previous_id = _gml_room_current_id
	_gml_room_current_id = int(entry["id"])
	_gml_builtin_globals["room"] = _gml_room_current_id
	var metadata = _gml_room_metadata(entry)
	var width = int(metadata["width"]) if metadata.has("width") else 0
	var height = int(metadata["height"]) if metadata.has("height") else 0
	if scene != null and scene.has_meta("gamemaker_room_width"):
		width = int(scene.get_meta("gamemaker_room_width"))
	if scene != null and scene.has_meta("gamemaker_room_height"):
		height = int(scene.get_meta("gamemaker_room_height"))
	_gml_builtin_globals["room_width"] = width
	_gml_builtin_globals["room_height"] = height


static func _gml_room_update_background_layers(scene, delta):
	if not (scene is Node):
		return
	var step_scale = _gml_room_step_scale(delta)
	for node in _gml_layer_tree_nodes(scene):
		if node == scene:
			continue
		if node is Object and node.has_meta("gamemaker_background_visual"):
			_gml_room_update_background_node(node, step_scale)


static func _gml_room_update_background_node(node, step_scale):
	var hspeed = _gml_room_background_speed(node, "h")
	var vspeed = _gml_room_background_speed(node, "v")
	if abs(hspeed) < 0.0001 and abs(vspeed) < 0.0001:
		return
	var motion = Vector2(hspeed * step_scale, vspeed * step_scale)
	if node is Parallax2D:
		node.scroll_offset += motion
	elif node is Node2D:
		node.position += motion


static func _gml_room_background_speed(node, axis):
	var background_key = "gamemaker_background_hspeed" if axis == "h" else "gamemaker_background_vspeed"
	var layer_key = "gamemaker_layer_hspeed" if axis == "h" else "gamemaker_layer_vspeed"
	if node is Object and node.has_meta(background_key):
		return _to_real(node.get_meta(background_key))
	if node is Object and node.has_meta(layer_key):
		return _to_real(node.get_meta(layer_key))
	return 0.0


static func _gml_room_step_scale(delta):
	var room_speed = _to_real(_gml_builtin_globals.get("room_speed", 0))
	if room_speed <= 0.0:
		room_speed = float(Engine.max_fps)
	if room_speed <= 0.0:
		room_speed = 60.0
	return max(_to_real(delta), 0.0) * room_speed


static func _gml_room_dispatch_lifecycle(root_node, method_name):
	for node in _gml_room_tree_nodes(root_node):
		if node != null and node.has_method(method_name):
			node.call(method_name)


static func _gml_room_run_instance_creation_code(scene):
	if scene == null or not scene.has_method("_gm2godot_run_instance_creation_code"):
		return
	for entry in _gml_room_instance_creation_code_entries(scene):
		var node = entry["node"]
		if _gml_room_node_was_restored_persistent(node):
			_gml_room_warn_persistent_instance_creation_code(node)
			continue
		scene.call("_gm2godot_run_instance_creation_code", node)


static func _gml_room_run_room_creation_code(scene):
	if scene != null and scene.has_method("_gm2godot_room_creation_code"):
		scene.call("_gm2godot_room_creation_code")


static func _gml_room_instance_creation_code_entries(root_node):
	var entries = []
	var traversal_order = 0
	for node in _gml_room_tree_nodes(root_node):
		if node == root_node:
			continue
		if not node.has_meta("gamemaker_has_creation_code") or not bool(node.get_meta("gamemaker_has_creation_code")):
			continue
		if node.has_meta("gamemaker_creation_code_file_exists") and not bool(node.get_meta("gamemaker_creation_code_file_exists")):
			continue
		var order_index = 1073741824
		if node.has_meta("gamemaker_instance_creation_order_index"):
			var metadata_order = node.get_meta("gamemaker_instance_creation_order_index")
			if metadata_order != null:
				order_index = int(metadata_order)
		entries.append({
			"node": node,
			"order_index": order_index,
			"traversal_order": traversal_order,
		})
		traversal_order += 1
	entries.sort_custom(_gml_room_creation_code_entry_less)
	return entries


static func _gml_room_creation_code_entry_less(left, right):
	var left_order = int(left["order_index"])
	var right_order = int(right["order_index"])
	if left_order == right_order:
		return int(left["traversal_order"]) < int(right["traversal_order"])
	return left_order < right_order


static func _gml_room_tree_nodes(root_node):
	var nodes = []
	if root_node == null:
		return nodes
	var pending = [root_node]
	while not pending.is_empty():
		var node = pending.pop_front()
		nodes.append(node)
		for child in node.get_children():
			pending.append(child)
	return nodes


static func _gml_room_capture_persistent_instances(scene):
	var persistent_root = _gml_room_persistent_root()
	if persistent_root == null:
		return
	for node in _gml_room_tree_nodes(scene):
		if node == scene or not _gml_room_node_is_persistent(node):
			continue
		if node.get_parent() == null:
			continue
		node.set_meta("_gm2godot_room_preserving_persistent", true)
		node.reparent(persistent_root, true)


static func _gml_room_restore_persistent_instances(scene):
	var persistent_root = _gml_room_persistent_root()
	if persistent_root == null or scene == null:
		return
	for node in persistent_root.get_children():
		node.reparent(scene, true)
		node.set_meta("_gm2godot_room_preserving_persistent", false)
		node.set_meta("_gm2godot_room_restored_persistent", true)


static func _gml_room_node_is_persistent(node):
	if node == null:
		return false
	if node.has_meta("gamemaker_persistent") and bool(node.get_meta("gamemaker_persistent")):
		return true
	if node is Object and _object_has_property(node, "persistent"):
		return bool(node.get("persistent"))
	return false


static func _gml_room_node_was_restored_persistent(node):
	return (
		node != null
		and node.has_meta("_gm2godot_room_restored_persistent")
		and bool(node.get_meta("_gm2godot_room_restored_persistent"))
	)


static func _gml_room_warn_persistent_instance_creation_code(node):
	if node == null:
		return
	if node.has_meta("_gm2godot_persistent_creation_code_warning_emitted") and bool(node.get_meta("_gm2godot_persistent_creation_code_warning_emitted")):
		return
	node.set_meta("_gm2godot_persistent_creation_code_warning_emitted", true)
	var instance_name = str(node.name)
	if node.has_meta("gamemaker_instance_name"):
		instance_name = str(node.get_meta("gamemaker_instance_name"))
	push_warning("GM2Godot preserves persistent instance " + instance_name + " across room transitions; its instance creation code is not rerun after restore.")


static func _gml_room_warn_persistent_room(scene):
	if scene == null:
		return
	if not scene.has_meta("gamemaker_room_persistent") or not bool(scene.get_meta("gamemaker_room_persistent")):
		return
	if scene.has_meta("_gm2godot_persistent_room_warning_emitted") and bool(scene.get_meta("_gm2godot_persistent_room_warning_emitted")):
		return
	scene.set_meta("_gm2godot_persistent_room_warning_emitted", true)
	push_warning("GM2Godot does not preserve full persistent room state; room lifecycle code runs when the generated Godot scene enters.")


static func _gml_room_persistent_root():
	var tree = _gml_room_tree()
	if tree == null or tree.root == null:
		return null
	var root = tree.root
	var existing = root.get_node_or_null(GML_ROOM_PERSISTENT_ROOT_NAME)
	if existing != null:
		return existing
	var persistent_root = Node2D.new()
	persistent_root.name = GML_ROOM_PERSISTENT_ROOT_NAME
	root.add_child(persistent_root)
	return persistent_root


static func _gml_room_tree():
	var main_loop = Engine.get_main_loop()
	if main_loop is SceneTree:
		return main_loop
	return null


static func _gml_room_entry(room_asset):
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(room_asset)
	if entry == null:
		return null
	if not entry.has("type") or str(entry["type"]) != "room":
		return null
	return entry


static func _gml_room_entry_for_scene(scene):
	if scene == null:
		return null
	var scene_name = str(scene.name)
	var entry = _gml_room_entry(scene_name)
	if entry != null:
		return entry
	_gml_asset_registry_ensure_loaded()
	for asset_entry in _gml_asset_entries:
		if str(asset_entry["type"]) == "room" and str(asset_entry["godot_path"]).ends_with("/" + scene_name + ".tscn"):
			return asset_entry
	return null


static func _gml_room_ordered_entries():
	_gml_asset_registry_ensure_loaded()
	var entries = []
	for entry in _gml_asset_entries:
		if entry.has("type") and str(entry["type"]) == "room":
			entries.append(entry)
	entries.sort_custom(_gml_room_entry_order_less)
	return entries


static func _gml_room_entry_order_less(left, right):
	var left_index = _gml_room_order_index(left)
	var right_index = _gml_room_order_index(right)
	if left_index == right_index:
		return str(left["name"]) < str(right["name"])
	return left_index < right_index


static func _gml_room_order_position(room_id, entries):
	for index in range(entries.size()):
		if int(entries[index]["id"]) == int(room_id):
			return index
	return -1


static func _gml_room_order_index(entry):
	var metadata = _gml_room_metadata(entry)
	if metadata.has("room_order") and int(metadata["room_order"]) >= 0:
		return int(metadata["room_order"])
	return 999999


static func _gml_room_metadata(entry):
	if entry.has("metadata") and typeof(entry["metadata"]) == TYPE_DICTIONARY:
		return entry["metadata"]
	return {}
