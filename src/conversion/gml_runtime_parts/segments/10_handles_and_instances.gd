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
		# Deactivated (instance_deactivate_*): out of the live lists until
		# activated again (see 75_instance_activation.gd).
		"deactivated": false,
		"creation_order": _gml_instance_creation_counter,
		# The creation order the step list took the instance in, or -1 while
		# it is not in the step list (see _gml_step_collect_instances).
		"step_order": -1,
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
	_gml_instance_forget_deactivated(entry)
	_gml_instance_order_erase(_gml_instance_live_order, entry)
	for selector_id in entry["selector_ids"]:
		_gml_instance_index_remove(_gml_instance_live_by_object, selector_id, entry)
	for selector_name in entry["selector_names"]:
		_gml_instance_index_remove(_gml_instance_live_by_object_name, selector_name, entry)
	gml_handle_invalidate(handle)
	_gml_builtin_globals["instance_count"] = _gml_instance_live_order.size()
	return true


static func gml_instance_destroy(target = null):
	var destroy_target = target if target != null else gml_instance_noone()
	for instance in gml_with_targets(destroy_target):
		var entry = _gml_instance_entry(instance)
		if entry == null or entry["destroyed"]:
			continue
		entry["destroyed"] = true
		# After a room change request GameMaker skips the Destroy event,
		# unless the instance or the current room is persistent.
		if instance != null and instance.has_method("_on_destroy") and not _gml_event_scheduler_event_blocked(instance, true):
			instance.call("_on_destroy")
		gml_instance_unregister(entry["handle"])
		if instance is Node and instance.is_inside_tree():
			instance.queue_free()
	return null


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


static func gml_instance_create_layer(x, y, layer, object_selector, current_self = null):
	return _gml_instance_create_at(x, y, layer, null, object_selector, current_self)


static func gml_instance_create_depth(x, y, depth_value, object_selector, current_self = null):
	return _gml_instance_create_at(x, y, null, depth_value, object_selector, current_self)


static func gml_with_targets(target, current_self = null, current_other = null):
	# with and the instance functions do not see deactivated instances.
	return _gml_instance_targets_active(_gml_with_targets_any(target, current_self, current_other))


static func _gml_with_targets_any(target, current_self = null, current_other = null):
	if typeof(target) == TYPE_DICTIONARY:
		# A struct, whatever members it has (an id or a handle too).
		return [target]
	if typeof(target) == TYPE_OBJECT:
		if not is_instance_valid(target):
			# An instance whose node was freed no longer exists.
			return []
		if target is Node:
			# The instance itself (self, other, a stored instance).
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
		handle.reference = null
		handle.index = _gml_invalid_handle_index(handle.kind)
		handle.value = _gml_encode_handle_value(handle.type_id, handle.index)
		_gml_handle_registry.erase(old_key)
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
