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


static func gml_instance_noone():
	return gml_handle_invalid(GML_INSTANCE_HANDLE_KIND, GML_INSTANCE_INVALID_INDEX)


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
		"object_id": object_id,
		"object_name": object_name,
		"selector_ids": selector_ids,
		"selector_names": selector_names,
		"destroyed": false,
		"creation_order": _gml_instance_creation_counter
	}
	_gml_instance_creation_counter += 1
	_gml_instance_entries[handle.index] = entry
	if instance is Object:
		_gml_instance_handles_by_node_id[instance.get_instance_id()] = handle
		_gml_instance_set_meta(instance, "_gm2godot_instance_id", handle.index)
	for selector_id in selector_ids:
		_gml_instance_index_add(_gml_instance_ids_by_object, selector_id, handle.index)
	for selector_name in selector_names:
		_gml_instance_index_add(_gml_instance_ids_by_object_name, selector_name, handle.index)
	_gml_builtin_globals["instance_count"] = _gml_live_instance_entries().size()
	return handle


static func gml_instance_unregister(instance_or_handle):
	var entry = _gml_instance_entry(instance_or_handle)
	if entry == null:
		return false
	entry["destroyed"] = true
	var handle = entry["handle"]
	var instance = entry["instance"]
	_gml_instance_entries.erase(handle.index)
	if instance is Object:
		_gml_instance_handles_by_node_id.erase(instance.get_instance_id())
	for selector_id in entry["selector_ids"]:
		_gml_instance_index_remove(_gml_instance_ids_by_object, selector_id, handle.index)
	for selector_name in entry["selector_names"]:
		_gml_instance_index_remove(_gml_instance_ids_by_object_name, selector_name, handle.index)
	gml_handle_invalidate(handle)
	_gml_builtin_globals["instance_count"] = _gml_live_instance_entries().size()
	return true


static func gml_instance_destroy(target = null):
	var destroy_target = target if target != null else gml_instance_noone()
	for instance in gml_with_targets(destroy_target):
		var entry = _gml_instance_entry(instance)
		if entry == null or entry["destroyed"]:
			continue
		entry["destroyed"] = true
		if instance != null and instance.has_method("_on_destroy"):
			instance.call("_on_destroy")
		gml_instance_unregister(entry["handle"])
		if instance is Node and instance.is_inside_tree():
			instance.queue_free()
	return null


static func gml_instance_exists(target):
	return gml_with_targets(target).size() > 0


static func gml_instance_find(target, index):
	var targets = gml_with_targets(target)
	var target_index = int(_to_real(index))
	if target_index < 0 or target_index >= targets.size():
		return gml_instance_noone()
	var entry = _gml_instance_entry(targets[target_index])
	if entry == null:
		return gml_instance_noone()
	return entry["handle"]


static func gml_instance_number(target):
	return gml_with_targets(target).size()


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
	if handle.reference is Object and not is_instance_valid(handle.reference):
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

