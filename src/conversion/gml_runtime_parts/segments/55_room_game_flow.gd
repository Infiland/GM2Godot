const GML_ROOM_PERSISTENT_ROOT_NAME = "_GM2GodotPersistentInstances"
const GML_ROOM_UNSUPPORTED_EXIT_MESSAGE = "GM2Godot maps game_end to SceneTree.quit(); platform-specific close prompts and window behavior are not emulated."
const GML_ROOM_PREPARED_META = "_gm2godot_room_prepared"
const GML_ROOM_HELD_INSTANCES_META = "_gm2godot_room_held_instances"
const GML_ROOM_UNORDERED_INSTANCE = 1073741824

static var _gml_room_current_id = -1
static var _gml_room_previous_id = -1
static var _gml_room_game_started = false
static var _gml_room_game_ended = false
static var _gml_room_suppress_auto_enter = false
static var _gml_room_pending_entry = null
static var _gml_room_transition_log = []
# GameMaker only records room_goto/room_goto_next/room_goto_previous/
# room_restart/game_restart/game_end requests; the current event finishes,
# no further step events run, and the change happens before the next step
# (the last request of a step wins). The GameMaker frame pump enables this
# deferral. Without the pump, requests are performed immediately.
static var _gml_room_defer_changes = false
static var _gml_room_requested_change = null


static func gml_room_set_deferred_changes(enabled):
	_gml_room_defer_changes = gml_bool(enabled)
	if not _gml_room_defer_changes:
		_gml_room_requested_change = null
	return null


static func gml_room_change_pending():
	return _gml_room_requested_change != null


static func gml_room_apply_pending_change():
	# Performs the requested change and returns what happened: "room" for a
	# room switch (including room_restart), "game_restart", "game_end", or ""
	# when nothing was requested.
	var request = _gml_room_requested_change
	if request == null:
		return ""
	_gml_room_requested_change = null
	var kind = str(request.get("kind", ""))
	if kind == "game_end":
		_gml_game_end_now()
		return kind
	if kind == "game_restart":
		_gml_game_restart_now()
		return kind
	_gml_room_change_to_entry(request["entry"], kind == "room_restart")
	return "room"


static func _gml_room_request_change(entry, restarting):
	if not _gml_room_defer_changes:
		return _gml_room_change_to_entry(entry, restarting)
	_gml_room_requested_change = {
		"kind": "room_restart" if bool(restarting) else "room",
		"entry": entry,
	}
	return true


static func gml_room_enter_scene(scene, force = false):
	if scene == null:
		return false
	if _gml_room_suppress_auto_enter and not bool(force):
		return false
	var entry = _gml_room_pending_entry if _gml_room_pending_entry != null else _gml_room_entry_for_scene(scene)
	if entry == null:
		_gml_room_create_instances(scene)
		return false
	_gml_room_pending_entry = null
	gml_layer_register_scene(scene)
	_gml_view_register_scene(scene)
	_gml_particle_room_enter_scene(scene)
	_gml_room_update_current(entry, scene)
	_gml_room_warn_persistent_room(scene)
	_gml_room_create_instances(scene)
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
	return _gml_room_request_change(entry, false)


static func gml_room_goto_next():
	var entries = _gml_room_ordered_entries()
	var current_index = _gml_room_order_position(_gml_room_current_id, entries)
	if current_index < 0 or current_index + 1 >= entries.size():
		return false
	return _gml_room_request_change(entries[current_index + 1], false)


static func gml_room_goto_previous():
	var entries = _gml_room_ordered_entries()
	var current_index = _gml_room_order_position(_gml_room_current_id, entries)
	if current_index <= 0:
		return false
	return _gml_room_request_change(entries[current_index - 1], false)


static func gml_room_restart():
	var entry = _gml_room_entry(_gml_room_current_id)
	if entry == null:
		return false
	return _gml_room_request_change(entry, true)


static func gml_game_set_speed(speed, type):
	var resolved_speed = max(int(_to_real(speed)), 0)
	_gml_builtin_globals["room_speed"] = resolved_speed
	if int(_to_real(type)) == 0:
		Engine.max_fps = resolved_speed
	return null


static func gml_game_restart():
	if _gml_room_ordered_entries().is_empty():
		return false
	if _gml_room_defer_changes:
		_gml_room_requested_change = {"kind": "game_restart"}
		return true
	return _gml_game_restart_now()


static func _gml_game_restart_now():
	var entries = _gml_room_ordered_entries()
	if entries.is_empty():
		return false
	var tree = _gml_room_tree()
	if tree != null and tree.current_scene != null:
		_gml_room_dispatch_lifecycle(tree.current_scene, "_on_game_end")
	_gml_room_game_started = false
	_gml_room_game_ended = false
	return _gml_room_change_to_entry(entries[0], true, true)


static func gml_game_end():
	if _gml_room_game_ended:
		return null
	if _gml_room_defer_changes:
		_gml_room_requested_change = {"kind": "game_end"}
		return null
	return _gml_game_end_now()


static func _gml_game_end_now():
	if _gml_room_game_ended:
		return null
	_gml_room_game_ended = true
	var tree = _gml_room_tree()
	if tree != null and tree.current_scene != null:
		_gml_room_dispatch_lifecycle(tree.current_scene, "_on_room_end")
		_gml_room_dispatch_lifecycle(tree.current_scene, "_on_game_end")
		_gml_instances_clean_up(null)
		push_warning(GML_ROOM_UNSUPPORTED_EXIT_MESSAGE)
		tree.quit(0)
	else:
		push_warning(GML_ROOM_UNSUPPORTED_EXIT_MESSAGE)
	return null


# Closing the game window ends the game: every instance runs its Clean Up
# event before Godot quits.
static func gml_game_window_close():
	_gml_instances_clean_up(null)
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


# game_restarting: the game restarts, so every instance leaves the game, the
# persistent ones too.
static func _gml_room_change_to_entry(entry, restarting, game_restarting = false):
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
		# Clean Up comes after Room End. The instances left in a room that is
		# not persistent leave the game (the persistent ones have just moved
		# out); on a game restart every instance does.
		if game_restarting:
			_gml_instances_clean_up(null)
		elif not _gml_room_current_is_persistent():
			_gml_instances_clean_up(old_scene)
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
		if node == null or not node.has_method(method_name):
			continue
		# Game/room start and end are Other events: after a room change
		# request only persistent instances still receive them.
		if _gml_event_scheduler_event_blocked(node, true):
			continue
		node.call(method_name)


static func _gml_room_current_is_persistent():
	var tree = _gml_room_tree()
	if tree == null or tree.current_scene == null:
		return false
	var scene = tree.current_scene
	return scene.has_meta("gamemaker_room_persistent") and bool(scene.get_meta("gamemaker_room_persistent"))


# GameMaker starts a room by creating every instance placed in it first, and
# only then runs their Create events and creation code, one instance at a time
# in the room's creation order; Game Start, the room creation code and Room
# Start follow. The room node calls this when its scene enters the tree,
# before the instances do: the placed instances are registered in creation
# order, so instance_exists, instance_number and with see all of them from the
# first Create event on, and they are held out of the tree until
# gml_room_enter_scene adds them back one at a time, after the room, its
# layers and its views are current.
static func gml_room_prepare_scene(scene):
	if not (scene is Node) or scene.has_meta(GML_ROOM_PREPARED_META):
		return false
	scene.set_meta(GML_ROOM_PREPARED_META, true)
	var preserved_names = _gml_room_preserved_persistent_names()
	var held = []
	var parents = {}
	var traversal_order = 0
	for node in _gml_room_tree_nodes(scene):
		if node == scene or not _gml_room_node_is_placed_instance(node):
			continue
		var parent = node.get_parent()
		if not parents.has(parent.get_instance_id()):
			parents[parent.get_instance_id()] = {"parent": parent, "children": parent.get_children()}
		if preserved_names.has(_gml_room_instance_name(node)):
			# The persistent instance kept from an earlier visit stands in for it.
			parent.remove_child(node)
			node.queue_free()
			continue
		held.append({
			"node": node,
			"parent": parent,
			"order_index": _gml_room_creation_order_index(node),
			"traversal_order": traversal_order,
		})
		traversal_order += 1
	held.sort_custom(_gml_room_creation_code_entry_less)
	for record in held:
		record["node"].call("_gm_register_instance")
	for record in held:
		record["parent"].remove_child(record["node"])
		# Re-added later; the scene becomes its owner again then.
		record["node"].owner = null
	scene.set_meta(GML_ROOM_HELD_INSTANCES_META, {"instances": held, "parents": parents.values()})
	return true


static func _gml_room_node_is_placed_instance(node):
	return (
		node is Node
		and node.has_meta("gamemaker_layer_element_type")
		and str(node.get_meta("gamemaker_layer_element_type")) == "instance"
		and node.has_method("_gm_register_instance")
	)


static func _gml_room_instance_name(node):
	if node is Node and node.has_meta("gamemaker_instance_name") and node.get_meta("gamemaker_instance_name") != null:
		return str(node.get_meta("gamemaker_instance_name"))
	return ""


static func _gml_room_creation_order_index(node):
	if node.has_meta("gamemaker_instance_creation_order_index"):
		var metadata_order = node.get_meta("gamemaker_instance_creation_order_index")
		if metadata_order != null:
			return int(metadata_order)
	return GML_ROOM_UNORDERED_INSTANCE


static func _gml_room_preserved_persistent_names():
	var names = {}
	var tree = _gml_room_tree()
	if tree == null or tree.root == null:
		return names
	var persistent_root = tree.root.get_node_or_null(GML_ROOM_PERSISTENT_ROOT_NAME)
	if persistent_root == null:
		return names
	for node in persistent_root.get_children():
		var instance_name = _gml_room_instance_name(node)
		if instance_name != "":
			names[instance_name] = true
	return names


# Adds the held instances back in creation order: each runs its Create event
# as it joins the scene, then its instance creation code, before the next
# instance is created. Instances the scene did not hold back (restored
# persistent instances, hand-made scenes) only run their creation code.
static func _gml_room_create_instances(scene):
	var held = {"instances": [], "parents": []}
	if scene.has_meta(GML_ROOM_HELD_INSTANCES_META):
		held = scene.get_meta(GML_ROOM_HELD_INSTANCES_META)
		scene.remove_meta(GML_ROOM_HELD_INSTANCES_META)
	var steps = []
	steps.append_array(held["instances"])
	steps.append_array(_gml_room_instance_creation_code_entries(scene))
	steps.sort_custom(_gml_room_creation_code_entry_less)
	for step in steps:
		var node = step["node"]
		if not is_instance_valid(node):
			continue
		if step.has("parent") and not _gml_room_add_held_instance(scene, node, step["parent"]):
			continue
		_gml_room_run_instance_creation_code(scene, node)
	_gml_room_restore_child_order(held["parents"])


static func _gml_room_add_held_instance(scene, node, parent):
	# An instance destroyed before its turn (by an earlier Create event or
	# creation code) never joins the room and runs no Create event; neither
	# does one whose room was left meanwhile. (GameMaker's HTML5 runner still
	# runs the Create event and creation code of such an instance, which it
	# only removes at the end of the step; a destroyed instance cannot run
	# events here without being registered again.)
	var entry: Variant = _gml_instance_entry(node)
	if entry == null or entry["destroyed"] or not scene.is_inside_tree():
		if entry != null:
			gml_instance_unregister(node)
		node.queue_free()
		return false
	if not is_instance_valid(parent) or not parent.is_inside_tree():
		parent = scene
	parent.add_child(node)
	if scene.is_ancestor_of(node):
		node.owner = scene
	return true


static func _gml_room_run_instance_creation_code(scene, node):
	if not scene.has_method("_gm2godot_run_instance_creation_code") or not _gml_room_node_has_creation_code(node):
		return
	# A persistent instance brought along from another room was created
	# there; like GameMaker, its creation code does not run again.
	if _gml_room_node_was_restored_persistent(node):
		return
	scene.call("_gm2godot_run_instance_creation_code", node)


# Puts the room's own nodes back in their scene order (the room editor's
# order within each layer); instances created meanwhile follow them.
static func _gml_room_restore_child_order(parents):
	for record in parents:
		var parent = record["parent"]
		if not is_instance_valid(parent):
			continue
		var index = 0
		for child in record["children"]:
			if is_instance_valid(child) and child.get_parent() == parent:
				parent.move_child(child, index)
				index += 1


static func _gml_room_run_room_creation_code(scene):
	if scene != null and scene.has_method("_gm2godot_room_creation_code"):
		scene.call("_gm2godot_room_creation_code")


static func _gml_room_instance_creation_code_entries(root_node):
	var entries = []
	var traversal_order = 0
	for node in _gml_room_tree_nodes(root_node):
		if node == root_node or not _gml_room_node_has_creation_code(node):
			continue
		entries.append({
			"node": node,
			"order_index": _gml_room_creation_order_index(node),
			"traversal_order": traversal_order,
		})
		traversal_order += 1
	entries.sort_custom(_gml_room_creation_code_entry_less)
	return entries


static func _gml_room_node_has_creation_code(node):
	if not node.has_meta("gamemaker_has_creation_code") or not bool(node.get_meta("gamemaker_has_creation_code")):
		return false
	return not (node.has_meta("gamemaker_creation_code_file_exists") and not bool(node.get_meta("gamemaker_creation_code_file_exists")))


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
