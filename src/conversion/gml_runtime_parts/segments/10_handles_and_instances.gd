static func gml_ptr(value):
	if is_ptr(value):
		return value
	if is_int64(value):
		return GMLPointer.new(value.value)
	if is_string(value):
		var pointer_value = _gml_string_to_int64(value)
		if is_undefined(pointer_value):
			return pointer_value
		return GMLPointer.new(pointer_value)
	if is_number(value):
		return GMLPointer.new(int(value))
	return gml_unsupported_type_error("GML ptr conversion", value)


static func gml_handle_register(kind, reference, name = ""):
	var handle_kind = str(kind)
	var handle_index = _gml_next_handle_index(handle_kind)
	var handle = _gml_make_handle(handle_kind, handle_index, reference, str(name), true)
	_gml_handle_registry[_gml_handle_key(handle_kind, handle_index)] = handle
	return handle


static func gml_handle_get(kind, index):
	var handle_kind = str(kind)
	var handle_index = _to_int64_value(index)
	if _gml_is_invalid_handle_index(handle_kind, handle_index):
		return _gml_make_handle(handle_kind, handle_index, null, "", false)
	var key = _gml_handle_key(handle_kind, handle_index)
	if _gml_handle_registry.has(key):
		return _gml_handle_registry[key]
	return _gml_make_handle(handle_kind, handle_index, null, "", false)


static func gml_handle_invalid(kind = "", invalid_index = GML_HANDLE_INVALID_INDEX):
	return _gml_make_handle(str(kind), int(invalid_index), null, "", false)


# noone is one shared handle, made once: nothing changes it (invalidating it
# leaves it as it is).
static var _gml_instance_noone_handle = null


static func gml_instance_noone():
	if _gml_instance_noone_handle == null:
		_gml_instance_noone_handle = gml_handle_invalid(GML_INSTANCE_HANDLE_KIND, GML_INSTANCE_INVALID_INDEX)
	return _gml_instance_noone_handle


static func gml_instance_all():
	return gml_handle_invalid(GML_INSTANCE_HANDLE_KIND, GML_INSTANCE_ALL_INDEX)


static func gml_instance_register(instance, object_selector = null, parent_selectors = []):
	if instance == null:
		return gml_instance_noone()
	var existing_handle = _gml_instance_handle_for_node(instance)
	if gml_handle_is_valid(existing_handle):
		return existing_handle
	var object_id = _gml_object_selector_id(object_selector)
	var object_name = _gml_object_selector_name(object_selector)
	var handle = gml_handle_register(GML_INSTANCE_HANDLE_KIND, instance, object_name)
	var selector_ids = _gml_object_selector_id_array([object_selector] + parent_selectors)
	var selector_names = _gml_object_selector_name_array([object_selector] + parent_selectors)
	var entry = {
		"handle": handle,
		"instance": instance,
		# Kept so the instance can be forgotten after its node is freed.
		"node_id": instance.get_instance_id() if instance is Object else 0,
		"object_id": object_id,
		"object_name": object_name,
		"selector_ids": selector_ids,
		"selector_names": selector_names,
		"destroyed": false,
		"cleaned_up": false,
		"creation_order": _gml_instance_creation_counter,
		# Whether the instance keeps its own collision state (see
		# _gml_collision_tracked_state).
		"collision_tracked": instance is Object and _gml_collision_tracks(instance)
	}
	_gml_instance_creation_counter += 1
	_gml_instance_entries[handle.index] = entry
	if entry["collision_tracked"]:
		# Its script reports transform changes (see _gml_collision_tracked_state).
		instance.set_notify_local_transform(true)
	_gml_collision_forget_box_lists(entry)
	if instance is Object:
		_gml_instance_handles_by_node_id[instance.get_instance_id()] = handle
		_gml_instance_set_meta(instance, "_gm2godot_instance_id", handle.index)
	_gml_instance_live_order.append(entry)
	for selector_id in selector_ids:
		_gml_instance_index_add(_gml_instance_live_by_object, selector_id, entry)
	for selector_name in selector_names:
		_gml_instance_index_add(_gml_instance_live_by_object_name, selector_name, entry)
	_gml_builtin_globals["instance_count"] = _gml_instance_live_order.size()
	if instance is Object:
		# The collision events of the instance's object (and its parents)
		# join the collision table as soon as the object is first seen.
		_gml_collision_register_instance_events(instance, _gml_collision_entry_object_chain(entry))
	return handle


static func gml_instance_unregister(instance_or_handle):
	var entry = _gml_instance_entry(instance_or_handle)
	if entry == null:
		return false
	entry["destroyed"] = true
	var handle = entry["handle"]
	if not is_same(_gml_instance_entries.get(handle.index), entry):
		# Already forgotten.
		return false
	_gml_instance_entries.erase(handle.index)
	_gml_instance_handles_by_node_id.erase(entry["node_id"])
	_gml_depth_forget(entry["node_id"])
	_gml_collision_forget_box_lists(entry)
	_gml_instance_order_erase(_gml_instance_live_order, entry)
	for selector_id in entry["selector_ids"]:
		_gml_instance_index_remove(_gml_instance_live_by_object, selector_id, entry)
	for selector_name in entry["selector_names"]:
		_gml_instance_index_remove(_gml_instance_live_by_object_name, selector_name, entry)
	gml_handle_invalidate(handle)
	_gml_builtin_globals["instance_count"] = _gml_instance_live_order.size()
	return true


# With execute_event false the Destroy event is skipped; Clean Up still runs.
static func gml_instance_destroy(target = null, execute_event = true):
	var destroy_target = target if target != null else gml_instance_noone()
	var run_destroy_event = gml_bool(execute_event)
	for instance in gml_with_targets(destroy_target):
		var entry = _gml_instance_entry(instance)
		if entry == null or entry["destroyed"]:
			continue
		entry["destroyed"] = true
		# A destroyed instance is never registered again, not even by the rest
		# of its Create event (event_inherited) or by instance_create_*.
		_gml_instance_set_meta(instance, "_gm2godot_instance_destroyed", true)
		# After a room change request GameMaker skips the Destroy event,
		# unless the instance or the current room is persistent.
		if run_destroy_event and instance != null and instance.has_method("_on_destroy") and not _gml_event_scheduler_event_blocked(instance, true):
			_gml_instance_perform_own_event(instance, "_on_destroy")
		_gml_instance_clean_up(instance, entry)
		gml_instance_unregister(entry["handle"])
		if instance is Node and instance.is_inside_tree():
			instance.queue_free()
	return null


# GameMaker runs an instance's Clean Up event once, as the instance leaves the
# game: right after its Destroy event (before instance_destroy returns), when
# a room that is not persistent ends, and when the game ends or restarts;
# never when a persistent instance moves on to the next room. A pending room
# change does not hold it back.
static func _gml_instance_clean_up(instance, entry):
	if entry["cleaned_up"]:
		return
	entry["cleaned_up"] = true
	if typeof(instance) == TYPE_OBJECT and is_instance_valid(instance) and instance.has_method("_on_clean_up"):
		_gml_instance_perform_own_event(instance, "_on_clean_up")


# Moves a node to another parent, such as an instance to another layer. The
# node leaves the tree and comes back, which must not count as the instance
# leaving the game (its _exit_tree unregisters it otherwise).
static func _gml_instance_reparent(node, new_parent):
	var preserving = node.get_meta("_gm2godot_room_preserving_persistent", false)
	node.set_meta("_gm2godot_room_preserving_persistent", true)
	node.reparent(new_parent, true)
	node.set_meta("_gm2godot_room_preserving_persistent", preserving)


# Runs an event that GameMaker performs on an instance by itself (Destroy,
# Clean Up) with other being the instance, also when a collision event (where
# other is the instance collided with) set it off; the caller's other comes
# back afterwards.
static func _gml_instance_perform_own_event(instance, method_name):
	_gml_instance_call_event(instance, method_name, instance)


# Calls an event method of an instance with other_value as its other, then
# gives the instance its own other back.
static func _gml_instance_call_event(instance, method_name, other_value):
	var has_other = "other" in instance
	var previous_other = instance.get("other") if has_other else null
	if has_other:
		instance.set("other", other_value)
	instance.call(method_name)
	if has_other and is_instance_valid(instance):
		instance.set("other", previous_other)


# The generated methods of the events event_perform can name, by event type
# and number (src/conversion/events/mappings names them).
const GML_EVENT_STEP_METHODS = {0: "_on_step", 1: "_on_begin_step", 2: "_on_end_step"}
const GML_EVENT_OTHER_METHODS = {
	0: "_on_outside_room",
	1: "_on_intersect_boundary",
	2: "_on_game_start",
	3: "_on_game_end",
	4: "_on_room_start",
	5: "_on_room_end",
	6: "_on_no_more_lives",
	7: "_on_animation_end",
	8: "_on_path_ended",
	9: "_on_no_more_health",
	58: "_on_animation_update",
	59: "_on_animation_event",
	76: "_on_broadcast_message",
}
const GML_EVENT_DRAW_METHODS = {
	0: "_on_draw",
	64: "_on_draw_gui",
	65: "_on_resize",
	72: "_on_draw_begin",
	73: "_on_draw_end",
	74: "_on_draw_gui_begin",
	75: "_on_draw_gui_end",
	76: "_on_pre_draw",
	77: "_on_post_draw",
}
const GML_EVENT_INPUT_METHOD_PREFIXES = {
	5: "_gm_input_keyboard_",
	6: "_gm_input_mouse_",
	9: "_gm_input_key_press_",
	10: "_gm_input_key_release_",
	13: "_gm_input_gesture_",
}


# event_user(number) runs the instance's User Event number (0 to 15), as
# event_perform(ev_other, ev_user0 + number) does.
static func gml_event_user(number, current_self = null, current_other = null):
	var user_number = int(_to_real(number))
	if user_number < 0 or user_number > 15:
		return null
	return gml_event_perform(7, 10 + user_number, current_self, current_other)


# event_perform(type, number) runs the code of one of the instance's events
# (an inherited one too) at once, with the caller's self and other, and does
# nothing else: performing the Destroy event destroys nothing. Nothing runs
# for an event the object does not have, nor for one GameMaker holds back
# once a room change is pending (HTML5 runner: event_perform in
# Function_Game.js calls PerformEvent(event, index, self, other)).
static func gml_event_perform(event_type, event_number, current_self = null, current_other = null):
	var type_value = int(_to_real(event_type))
	var method_name = _gml_event_method_name(type_value, event_number)
	if method_name == "" or not (current_self is Node) or not is_instance_valid(current_self):
		return null
	if not current_self.has_method(method_name):
		return null
	# Clean Up always runs; Create, Pre-Create, Destroy, Alarm and Other events
	# still run for persistent instances.
	if type_value != 12 and _gml_event_scheduler_event_blocked(current_self, type_value in [0, 1, 2, 7, 14]):
		return null
	_gml_instance_call_event(current_self, method_name, current_other if current_other != null else current_self)
	return null


static func _gml_event_method_name(type_value, event_number):
	if type_value == 4:
		# The number is the object collided with.
		var object_name = _gml_object_selector_name(event_number)
		return GML_COLLISION_EVENT_PREFIX + object_name if object_name != "" else ""
	var number = int(_to_real(event_number))
	if GML_EVENT_INPUT_METHOD_PREFIXES.has(type_value):
		return GML_EVENT_INPUT_METHOD_PREFIXES[type_value] + str(number)
	match type_value:
		0:
			# The Create event; the generated _ready also sets xstart, ystart,
			# xprevious and yprevious to the current position again.
			return "_ready"
		1:
			return "_on_destroy"
		2:
			return "_on_alarm_" + str(number)
		3:
			return GML_EVENT_STEP_METHODS.get(number, "")
		7:
			if number >= 10 and number <= 25:
				return "_user_event_" + str(number - 10)
			if number >= 40 and number <= 47:
				return "_on_outside_view_" + str(number - 40)
			if number >= 50 and number <= 57:
				return "_on_intersect_view_" + str(number - 50) + "_boundary"
			return GML_EVENT_OTHER_METHODS.get(number, "_on_other_" + str(number))
		8:
			return GML_EVENT_DRAW_METHODS.get(number, "_on_draw_" + str(number))
		12:
			return "_on_clean_up"
	return ""


# Runs the Clean Up event of the instances under root_node (every instance
# when root_node is null), in instance order.
static func _gml_instances_clean_up(root_node):
	for entry in _gml_instance_live_order.slice(0):
		var instance = entry["instance"]
		if entry["destroyed"] or typeof(instance) != TYPE_OBJECT or not is_instance_valid(instance):
			continue
		if root_node != null and not (instance is Node and root_node.is_ancestor_of(instance)):
			continue
		_gml_instance_clean_up(instance, entry)


# Destroys the instances under root_node (a layer or a sequence that is
# destroyed), in tree order: each one runs its Destroy and then its Clean Up
# event, and so does an instance that those events create under root_node
# (the runner removes a layer's elements until none is left).
static func _gml_instances_destroy_under(root_node):
	var visited = {}
	var found = true
	while found:
		found = false
		for node in _gml_layer_tree_nodes(root_node):
			if visited.has(node):
				continue
			visited[node] = true
			found = true
			var handle = _gml_instance_handle_for_node(node)
			if gml_handle_is_valid(handle):
				gml_instance_destroy(handle)


static func gml_instance_exists(target):
	if _gml_instance_object_first(target) != null:
		return true
	return gml_with_targets(target).size() > 0


static func gml_instance_find(target, index):
	var target_index = int(_to_real(index))
	var entries: Variant = _gml_instance_target_entries(target)
	if entries != null:
		# The n-th live instance, passing over nodes that were freed.
		for entry in entries:
			var instance = entry["instance"]
			if typeof(instance) == TYPE_OBJECT and not is_instance_valid(instance):
				continue
			if target_index == 0:
				return entry["handle"]
			target_index -= 1
		return gml_instance_noone()
	var targets = gml_with_targets(target)
	if target_index < 0 or target_index >= targets.size():
		return gml_instance_noone()
	var entry = _gml_instance_entry(targets[target_index])
	if entry == null:
		return gml_instance_noone()
	return entry["handle"]


static func gml_instance_number(target):
	var entries: Variant = _gml_instance_target_entries(target)
	if entries == null:
		return gml_with_targets(target).size()
	var count = 0
	for entry in entries:
		var instance = entry["instance"]
		if typeof(instance) != TYPE_OBJECT or is_instance_valid(instance):
			count += 1
	return count


static func gml_instance_id_get(index):
	var entries = _gml_live_instance_entries()
	var target_index = int(_to_real(index))
	if target_index < 0 or target_index >= entries.size():
		return gml_instance_noone()
	return entries[target_index]["handle"]


static func gml_instance_nearest(x, y, target):
	return _gml_instance_distance_extreme(x, y, target, true)


static func gml_instance_furthest(x, y, target):
	return _gml_instance_distance_extreme(x, y, target, false)


static func gml_instance_create_layer(x, y, layer, object_selector, current_self = null, var_struct = null):
	return _gml_instance_create_at(x, y, layer, null, object_selector, current_self, var_struct)


static func gml_instance_create_depth(x, y, depth_value, object_selector, current_self = null, var_struct = null):
	return _gml_instance_create_at(x, y, null, depth_value, object_selector, current_self, var_struct)


static func gml_with_targets(target, current_self = null, current_other = null):
	if typeof(target) == TYPE_DICTIONARY:
		# A struct, whatever members it has (an id or a handle too).
		return [target]
	if typeof(target) == TYPE_OBJECT:
		if not is_instance_valid(target):
			# An instance whose node was freed no longer exists.
			return []
		if target is Node:
			# The instance itself (self, other, a stored instance), unless it
			# was destroyed: it was registered once and no longer is.
			if target.has_meta("_gm2godot_instance_id") and not _gml_instance_handles_by_node_id.has(target.get_instance_id()):
				return []
			return [target]
	if is_undefined(target):
		return []
	if is_handle(target) and target.kind == GML_INSTANCE_HANDLE_KIND:
		return _gml_instance_keyword_targets(target, current_self, current_other)
	if is_numeric(target):
		var keyword_index = _to_int64_value(target)
		var keyword_targets = _gml_legacy_instance_keyword_targets(keyword_index, current_self, current_other)
		if keyword_targets != null:
			return keyword_targets
	var selector_targets = _gml_instance_selector_targets(target)
	if selector_targets != null:
		return selector_targets
	var resolved_instance = _gml_resolve_instance(target)
	if resolved_instance == null:
		return []
	return [resolved_instance]


static func gml_handle_is_valid(handle):
	if not is_handle(handle):
		return false
	if _gml_is_invalid_handle_index(handle.kind, handle.index):
		return false
	if not handle.valid:
		return false
	if typeof(handle.reference) == TYPE_OBJECT and not is_instance_valid(handle.reference):
		# What the handle referred to was freed: forget it everywhere.
		if handle.kind == GML_INSTANCE_HANDLE_KIND and _gml_instance_entries.has(handle.index):
			gml_instance_unregister(handle)
		else:
			gml_handle_invalidate(handle)
		return false
	return true


static func gml_handle_parse(value):
	var parts = str(value).split(" ", false)
	if parts.size() != 3 or parts[0] != "ref":
		return gml_handle_invalid()
	var kind = parts[1]
	var identifier = parts[2]
	if _gml_string_is_int(identifier):
		return gml_handle_get(kind, int(identifier))
	return _gml_handle_get_by_name(kind, identifier)


static func gml_ref_create(target, member_or_index, array_index = null):
	var descriptor = {
		"target": target,
		"member_or_index": member_or_index,
		"has_array_index": array_index != null,
		"array_index": array_index
	}
	return gml_handle_register(GML_REFERENCE_HANDLE_KIND, descriptor)


static func gml_handle_from_value(kind, value):
	var handle_kind = str(kind)
	if is_handle(value):
		if value.kind == handle_kind:
			return value
		return gml_handle_invalid(handle_kind)
	if is_string(value):
		var parsed = gml_handle_parse(value)
		if is_handle(parsed) and parsed.kind == handle_kind:
			return parsed
		return gml_handle_invalid(handle_kind)
	if is_numeric(value):
		return gml_handle_get(handle_kind, _to_int64_value(value))
	return gml_handle_invalid(handle_kind)


static func gml_handle_resolve_for_kind(kind, value):
	return gml_handle_resolve(gml_handle_from_value(kind, value))


static func gml_handle_resolve(handle):
	if gml_handle_is_valid(handle):
		return handle.reference
	return null


static func gml_handle_invalidate(handle):
	if handle is GMLHandle:
		var old_key = _gml_handle_key(handle.kind, handle.index)
		handle.valid = false
		_gml_handle_registry.erase(old_key)
		if handle.kind == GML_INSTANCE_HANDLE_KIND:
			# A destroyed instance keeps its id: stored references never turn
			# into noone, and they still reach the instance's variables until
			# its node is freed at the end of the step (GameMaker only marks
			# the instance; instance lookups skip it).
			return handle
		handle.reference = null
		handle.index = _gml_invalid_handle_index(handle.kind)
		handle.value = _gml_encode_handle_value(handle.type_id, handle.index)
	return handle



# --- Live instance lists -------------------------------------------------------
#
# Every registered instance is listed in creation order in
# _gml_instance_live_order, and under each of its object selectors (its object
# and parents, by id and by name) in _gml_instance_live_by_object(_name), as
# GameMaker keeps an object's instances, children included, in creation
# order. An instance stays listed until it is unregistered: right after its
# Destroy event, or when its node leaves the tree. A node freed without being
# unregistered is forgotten the next time a list meets it.

# The first listed instance of an object given by its index, or null when
# the value is not such an object (or an instance id), so callers fall back
# to gml_with_targets.
static func _gml_instance_object_first(target):
	if typeof(target) != TYPE_INT or _gml_instance_entries.has(target):
		return null
	var entries = _gml_instance_live_by_object.get(target)
	if entries == null:
		return null
	for entry in entries:
		var instance = entry["instance"]
		if typeof(instance) != TYPE_OBJECT or is_instance_valid(instance):
			return instance
	return null


# The live instance list of a target that is an object given by its index
# (children included) or `all`, or null for any other target (and for an
# object without instances). The array is the list itself: callers only
# read it, and skip nodes that were freed.
static func _gml_instance_target_entries(target):
	if typeof(target) == TYPE_INT:
		if target == GML_INSTANCE_ALL_INDEX:
			return _gml_instance_live_order
		if _gml_instance_entries.has(target):
			# An instance id.
			return null
		return _gml_instance_live_by_object.get(target)
	if is_handle(target) and target.kind == GML_INSTANCE_HANDLE_KIND and target.index == GML_INSTANCE_ALL_INDEX:
		return _gml_instance_live_order
	return null


# The listed instances of an object (by index or name), or null when none are
# listed. The array is the list itself: callers copy before changing it.
static func _gml_instance_object_entries(selector):
	if typeof(selector) == TYPE_INT:
		var by_index = _gml_instance_live_by_object.get(selector)
		if by_index != null:
			return by_index
	var object_id = _gml_object_selector_id(selector)
	if object_id != -1 and _gml_instance_live_by_object.has(object_id):
		return _gml_instance_live_by_object[object_id]
	var object_name = _gml_object_selector_name(selector)
	if object_name != "" and _gml_instance_live_by_object_name.has(object_name):
		return _gml_instance_live_by_object_name[object_name]
	return null


# The instances of listed entries, without nodes that were freed (which are
# unregistered on the way).
static func _gml_instance_entry_targets(entries):
	var targets = []
	var freed = []
	for entry in entries:
		var instance = entry["instance"]
		if typeof(instance) == TYPE_OBJECT and not is_instance_valid(instance):
			freed.append(entry)
		else:
			targets.append(instance)
	for entry in freed:
		gml_instance_unregister(entry)
	return targets


# Removes an entry from a list kept in creation order.
static func _gml_instance_order_erase(entries, entry):
	var order = int(entry["creation_order"])
	var low = 0
	var high = entries.size() - 1
	while low <= high:
		var middle = (low + high) >> 1
		var middle_order = int(entries[middle]["creation_order"])
		if middle_order < order:
			low = middle + 1
		elif middle_order > order:
			high = middle - 1
		else:
			if is_same(entries[middle], entry):
				entries.remove_at(middle)
			return
