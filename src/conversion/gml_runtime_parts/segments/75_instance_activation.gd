# --- Instance deactivation and activation ---
#
# GameMaker keeps a room's instances in an active and a deactivated list
# (HTML5 runner: yyRoom.js m_Active/m_Deactive, DeactivateInstance and
# ActivateInstance; Function_Instance.js instance_deactivate_* and
# instance_activate_*). Deactivating an instance takes it out of the live
# instance lists at once, so with, the instance functions, collisions and
# every event stop seeing it; it stays registered, so its id still reads
# and writes its variables. Activating it lists it again at the end of the
# live lists, the place of a newly created instance: its creation order is
# renumbered. Deactivated instances are kept by node id in
# _gml_instance_deactivated, in deactivation order (Dictionary order).
#
# The Godot node of a deactivated instance leaves the draw pipeline's
# instance group at once. At the end of the frame it stops processing, which
# also takes its collision area out of the physics space, and stops being
# rendered (its visibility layer is cleared; GML visible is left alone),
# only when its state changed: deactivating everything and activating a
# region every step costs nothing on the Godot side for the instances that
# stay as they were.

const GML_INSTANCE_DEACTIVATED_META = &"_gm2godot_deactivated_node_state"

# Deactivated instance entries by node id, in deactivation order.
static var _gml_instance_deactivated = {}
# Entries whose node state is updated at the end of the frame, by node id.
static var _gml_instance_activation_pending = {}
# The deactivated instances of the persistent rooms that were left, by node
# id: each room keeps its own deactivated list, out of reach of
# instance_activate_* in other rooms, and an id that names one of them
# still names a deactivated instance.
static var _gml_instance_parked_deactivated = {}
# Counts the calls that deactivated or activated instances; the step list
# drops such instances when it changed (_gml_step_collect_instances).
static var _gml_instance_activation_changes = 0
static var _gml_instance_activation_flush_queued = false


# instance_deactivate_all: every active instance; the calling one too unless
# notme is true. The collision space argument (UI layers) is ignored.
static func gml_instance_deactivate_all(current_self = null, notme = false, _collision_space = null):
	var kept = current_self if gml_bool(notme) else null
	_gml_instance_deactivate_entries(_gml_instance_live_order.slice(0), kept)
	return null


# instance_deactivate_object: the active instances of an object (children
# included), one instance, or all of them; the calling instance too when it
# is one of them.
static func gml_instance_deactivate_object(target, _collision_space = null):
	_gml_instance_deactivate_entries(_gml_instance_activation_targets(target, false), null)
	return null


# instance_deactivate_region: the active instances inside the region (inside
# true) or outside it, but the calling one when notme is true.
static func gml_instance_deactivate_region(current_self, left, top, width, height, inside, notme, _collision_space = null):
	var kept = current_self if gml_bool(notme) else null
	var entries = _gml_instance_region_entries(_gml_instance_live_order, left, top, width, height, inside)
	_gml_instance_deactivate_entries(entries, kept)
	return null


# instance_deactivate_layer: every instance on the layer (by name or id).
static func gml_instance_deactivate_layer(layer):
	_gml_instance_deactivate_entries(_gml_instance_layer_entries(layer), null)
	return null


static func gml_instance_activate_all(_collision_space = null):
	_gml_instance_activate_entries(_gml_instance_deactivated.values())
	return null


# instance_activate_object: the deactivated instances of an object (children
# included), one instance, or all of them. A destroyed instance stays
# destroyed.
static func gml_instance_activate_object(target, _collision_space = null):
	_gml_instance_activate_entries(_gml_instance_activation_targets(target, true))
	return null


# instance_activate_region: the deactivated instances inside the region
# (inside true) or outside it.
static func gml_instance_activate_region(left, top, width, height, inside, _collision_space = null):
	var entries = _gml_instance_region_entries(_gml_instance_deactivated.values(), left, top, width, height, inside)
	_gml_instance_activate_entries(entries)
	return null


static func gml_instance_activate_layer(layer):
	_gml_instance_activate_entries(_gml_instance_layer_entries(layer))
	return null


# The entries instance_deactivate_object (deactivated false) or
# instance_activate_object (deactivated true) looks at: every listed one for
# all, the entry of one instance (id, handle or instance), or an object's
# instances, in list order.
static func _gml_instance_activation_targets(target, deactivated):
	var all = false
	if is_handle(target):
		all = target.kind == GML_INSTANCE_HANDLE_KIND and target.index == GML_INSTANCE_ALL_INDEX
	elif is_numeric(target):
		all = _to_int64_value(target) == GML_INSTANCE_ALL_INDEX
	if all:
		return _gml_instance_deactivated.values() if deactivated else _gml_instance_live_order.slice(0)
	var entry: Variant = _gml_instance_entry(target)
	if entry != null:
		return [entry]
	if typeof(target) == TYPE_OBJECT or is_handle(target) or is_undefined(target):
		return []
	if not deactivated:
		var listed: Variant = _gml_instance_object_entries(target)
		return [] if listed == null else listed.slice(0)
	var object_id = _gml_object_selector_id(target)
	var object_name = _gml_object_selector_name(target)
	var entries = []
	for deactivated_entry in _gml_instance_deactivated.values():
		if deactivated_entry["selector_ids"].has(object_id) or deactivated_entry["selector_names"].has(object_name):
			entries.append(deactivated_entry)
	return entries


# The entries whose bounding box (x and y without a collision mask) is inside
# the region or, for inside false, completely outside it. The region's right
# and bottom edges are left + width - 1 and top + height - 1.
static func _gml_instance_region_entries(entries, left, top, width, height, inside):
	var region_left = _to_real(left)
	var region_top = _to_real(top)
	var region_right = region_left + _to_real(width) - 1.0
	var region_bottom = region_top + _to_real(height) - 1.0
	var want_inside = gml_bool(inside)
	var selected = []
	for entry in entries:
		var inst = entry["instance"]
		if not is_instance_valid(inst):
			continue
		var state = null
		if entry["collision_tracked"]:
			# _gml_collision_tracked_state's test, inline: regions are
			# checked against many instances every step.
			state = inst._gm_collision_state
			if state == null or inst._gm_collision_dirty or _gml_sequence_instances_exist or state["position"] != inst.position:
				state = _gml_collision_tracked_state(inst)
		elif inst is Node2D:
			state = _gml_collision_state(inst)
		else:
			continue
		var outside = false
		if state != null and state["data"] != null:
			outside = (
				state["right"] < region_left
				or state["left"] > region_right
				or state["bottom"] < region_top
				or state["top"] > region_bottom
			)
		else:
			var position = _gml_collision_instance_xy(inst)
			outside = position.x > region_right or position.x < region_left or position.y > region_bottom or position.y < region_top
		if outside != want_inside:
			selected.append(entry)
	return selected


# The entries of the instances on a layer, in the layer's order.
static func _gml_instance_layer_entries(layer):
	var layer_node = _gml_layer_resolve_node(layer)
	if not (layer_node is Node):
		return []
	var entries = []
	for child in layer_node.get_children():
		var entry: Variant = _gml_instance_entry(child)
		if entry != null:
			entries.append(entry)
	return entries


static func _gml_instance_deactivate_entries(entries, kept_instance):
	var deactivated = []
	for entry in entries:
		if entry["deactivated"] or entry["destroyed"]:
			continue
		var inst = entry["instance"]
		if typeof(inst) != TYPE_OBJECT or not is_instance_valid(inst) or is_same(inst, kept_instance):
			continue
		entry["deactivated"] = true
		_gml_instance_deactivated[entry["node_id"]] = entry
		if inst is Node and inst.is_in_group(GML_DRAW_INSTANCE_GROUP):
			inst.remove_from_group(GML_DRAW_INSTANCE_GROUP)
		_gml_collision_forget_box_lists(entry)
		_gml_instance_activation_queue(entry)
		deactivated.append(entry)
	if deactivated.is_empty():
		return
	_gml_instance_activation_changes += 1
	_gml_instance_unlist_entries(deactivated)
	_gml_builtin_globals["instance_count"] = _gml_instance_live_order.size()


static func _gml_instance_activate_entries(entries):
	var activated = false
	var counter_before = _gml_instance_creation_counter
	for entry in entries:
		if not entry["deactivated"] or entry["destroyed"]:
			continue
		var inst = entry["instance"]
		if typeof(inst) == TYPE_OBJECT and not is_instance_valid(inst):
			# Its node was freed: it is gone.
			gml_instance_unregister(entry)
			continue
		entry["deactivated"] = false
		_gml_instance_deactivated.erase(entry["node_id"])
		# Listed again at the end, like a new instance.
		entry["creation_order"] = _gml_instance_creation_counter
		_gml_instance_creation_counter += 1
		_gml_instance_live_order.append(entry)
		# The selectors were checked when the instance was registered.
		for selector_id in entry["selector_ids"]:
			_gml_instance_list_append(_gml_instance_live_by_object, selector_id, entry)
		for selector_name in entry["selector_names"]:
			_gml_instance_list_append(_gml_instance_live_by_object_name, selector_name, entry)
		if inst is Node:
			inst.add_to_group(GML_DRAW_INSTANCE_GROUP)
		_gml_collision_forget_box_lists(entry)
		_gml_instance_activation_queue(entry)
		activated = true
	if not activated:
		return
	_gml_instance_activation_changes += 1
	_gml_builtin_globals["instance_count"] = _gml_instance_live_order.size()
	if _gml_draw_group_scan_counter == counter_before:
		# The renumbering is no registration, and the activated instances
		# joined the draw group above: the group needs no rescan.
		_gml_draw_group_scan_counter = _gml_instance_creation_counter


static func _gml_instance_list_append(index_map, selector, entry):
	var entries = index_map.get(selector)
	if entries == null:
		index_map[selector] = [entry]
	else:
		entries.append(entry)


# Takes newly deactivated entries out of the live lists: one by one when
# there are a few, otherwise in one pass over each list concerned.
static func _gml_instance_unlist_entries(entries):
	if entries.size() <= 8:
		for entry in entries:
			_gml_instance_order_erase(_gml_instance_live_order, entry)
			for selector_id in entry["selector_ids"]:
				_gml_instance_index_remove(_gml_instance_live_by_object, selector_id, entry)
			for selector_name in entry["selector_names"]:
				_gml_instance_index_remove(_gml_instance_live_by_object_name, selector_name, entry)
		return
	_gml_instance_drop_deactivated(_gml_instance_live_order)
	var selector_ids = {}
	var selector_names = {}
	for entry in entries:
		for selector_id in entry["selector_ids"]:
			selector_ids[selector_id] = true
		for selector_name in entry["selector_names"]:
			selector_names[selector_name] = true
	for selector_id in selector_ids:
		_gml_instance_index_drop_deactivated(_gml_instance_live_by_object, selector_id)
	for selector_name in selector_names:
		_gml_instance_index_drop_deactivated(_gml_instance_live_by_object_name, selector_name)


static func _gml_instance_index_drop_deactivated(index_map, selector):
	var entries = index_map.get(selector)
	if entries == null:
		return
	_gml_instance_drop_deactivated(entries)
	if entries.is_empty():
		index_map.erase(selector)


# Removes the deactivated entries of a list in place, keeping its order.
static func _gml_instance_drop_deactivated(entries):
	var kept = 0
	for i in range(entries.size()):
		var entry = entries[i]
		if not entry["deactivated"]:
			entries[kept] = entry
			kept += 1
	entries.resize(kept)


# Called when an instance is unregistered (destroyed, or its node freed).
static func _gml_instance_forget_deactivated(entry):
	if _gml_instance_deactivated.is_empty():
		return
	if is_same(_gml_instance_deactivated.get(entry["node_id"]), entry):
		_gml_instance_deactivated.erase(entry["node_id"])


# Whether a node is a deactivated instance (of the current room or of a
# persistent room that was left).
static func _gml_instance_node_deactivated(node):
	if _gml_instance_deactivated.is_empty() and _gml_instance_parked_deactivated.is_empty():
		return false
	if typeof(node) != TYPE_OBJECT or not is_instance_valid(node):
		return false
	var node_id = node.get_instance_id()
	return _gml_instance_deactivated.has(node_id) or _gml_instance_parked_deactivated.has(node_id)


# with and the instance functions do not see a deactivated instance, even
# one given by its id: the targets without it. Object and all targets come
# from the live lists, which only hold active instances.
static func _gml_instance_targets_active(targets):
	if targets.size() != 1 or (_gml_instance_deactivated.is_empty() and _gml_instance_parked_deactivated.is_empty()):
		return targets
	if _gml_instance_node_deactivated(targets[0]):
		return []
	return targets


# The deactivated instance that a variable access names (the instance, its id
# or handle, or self/other), as a one-element array, or []. GameMaker finds
# an instance by id whether it is active or not, so o.x and o.x = 1 still
# work on it.
static func _gml_instance_deactivated_targets(target, current_self = null, current_other = null):
	if _gml_instance_deactivated.is_empty():
		return []
	var instance = target
	var keyword = GML_INSTANCE_INVALID_INDEX
	if is_handle(target) and target.kind == GML_INSTANCE_HANDLE_KIND:
		keyword = target.index
	elif typeof(target) == TYPE_INT:
		keyword = target
	if keyword == GML_INSTANCE_SELF_INDEX:
		instance = current_self
	elif keyword == GML_INSTANCE_OTHER_INDEX:
		instance = current_other
	var entry: Variant = _gml_instance_entry(instance)
	if entry == null or not entry["deactivated"]:
		return []
	return [entry["instance"]]


# Whether a variable_instance_* argument names a deactivated instance by its
# id or handle (or self/other): those functions only find active instances
# (yyVariable.js passes over instances that are not active), while o.x still
# reads a deactivated one. An instance node given as it is is read as it is.
static func _gml_variable_instance_names_deactivated(instance_value):
	if _gml_instance_deactivated.is_empty() and _gml_instance_parked_deactivated.is_empty():
		return false
	if typeof(instance_value) == TYPE_OBJECT and instance_value is Node:
		return false
	if not _gml_instance_deactivated_targets(instance_value).is_empty():
		return true
	# One deactivated in a persistent room that was left.
	return _gml_instance_node_deactivated(_gml_selector_direct_target(instance_value))


# Leaving a persistent room: its deactivated instances leave the current
# room's list and stay deactivated with the room. Returns them in
# deactivation order.
static func _gml_instance_park_deactivated(scene):
	var parked = []
	for entry in _gml_instance_deactivated.values():
		var node = entry["instance"]
		if typeof(node) == TYPE_OBJECT and is_instance_valid(node) and _gml_room_scene_holds(scene, node):
			parked.append(entry)
	for entry in parked:
		_gml_instance_deactivated.erase(entry["node_id"])
		_gml_instance_parked_deactivated[entry["node_id"]] = entry
	return parked


# Entering the room again: its deactivated instances, registered again, are
# the current room's deactivated list once more, in their order.
static func _gml_instance_resume_deactivated(entries):
	for entry in entries:
		_gml_instance_parked_deactivated.erase(entry["node_id"])
		if is_same(_gml_instance_entries.get(entry["handle"].index), entry):
			_gml_instance_deactivated[entry["node_id"]] = entry


# A parked room dropped (game_restart, program exit): its deactivated
# instances go with it.
static func _gml_instance_drop_parked_deactivated(entries):
	for entry in entries:
		_gml_instance_parked_deactivated.erase(entry["node_id"])


# The deactivated instances of a room that is not persistent, persistent
# ones too, are deleted without any event when the room ends (yyRoom.js
# ClearInstances; persistent instances are only carried over from the active
# list). A persistent room keeps them (see _gml_instance_park_deactivated).
static func _gml_instance_discard_deactivated(scene):
	if _gml_instance_deactivated.is_empty() or not (scene is Node):
		return
	for entry in _gml_instance_deactivated.values():
		var node = entry["instance"]
		if typeof(node) != TYPE_OBJECT or not is_instance_valid(node) or not scene.is_ancestor_of(node):
			continue
		gml_instance_unregister(entry)
		var parent = node.get_parent()
		if parent != null:
			# Taken out of the tree the way a layer move does it, which
			# skips the Clean Up event.
			node.set_meta(GML_LAYER_MOVE_META, true)
			parent.remove_child(node)
			node.remove_meta(GML_LAYER_MOVE_META)
		node.queue_free()


static func _gml_instance_activation_queue(entry):
	_gml_instance_activation_pending[entry["node_id"]] = entry
	if _gml_instance_activation_flush_queued:
		return
	_gml_instance_activation_flush_queued = true
	(func(): _gml_instance_activation_flush()).call_deferred()


# Brings the nodes of the instances (de)activated during the frame in line
# with their state.
static func _gml_instance_activation_flush():
	_gml_instance_activation_flush_queued = false
	var pending = _gml_instance_activation_pending
	_gml_instance_activation_pending = {}
	for entry in pending.values():
		var node = entry["instance"]
		if typeof(node) != TYPE_OBJECT or not is_instance_valid(node) or not (node is Node) or entry["destroyed"]:
			continue
		_gml_instance_apply_node_state(node, entry["deactivated"])


static func _gml_instance_apply_node_state(node, deactivated):
	if deactivated == node.has_meta(GML_INSTANCE_DEACTIVATED_META):
		return
	if deactivated:
		var visibility_layer = node.visibility_layer if node is CanvasItem else 0
		node.set_meta(GML_INSTANCE_DEACTIVATED_META, [node.process_mode, visibility_layer])
		node.process_mode = Node.PROCESS_MODE_DISABLED
		if node is CanvasItem:
			node.visibility_layer = 0
		return
	var saved = node.get_meta(GML_INSTANCE_DEACTIVATED_META)
	node.remove_meta(GML_INSTANCE_DEACTIVATED_META)
	node.process_mode = saved[0]
	if node is CanvasItem:
		node.visibility_layer = saved[1]
