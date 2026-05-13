static func gml_array_get(array_value, index):
	var resolved_index = _to_array_index(index)
	if resolved_index < 0:
		return gml_undefined()
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array access", array_value)
	if resolved_index >= array_value.size():
		return gml_error("GML array index out of bounds")
	return array_value[resolved_index]


static func gml_array_set(array_value, index, value):
	if GML_ARRAY_COPY_ON_WRITE_ENABLED:
		return gml_error(GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC)
	var resolved_index = _to_array_index(index)
	if resolved_index < 0:
		return gml_undefined()
	array_value[resolved_index] = value
	return value


static func gml_array_push(array_value, ...values):
	if GML_ARRAY_COPY_ON_WRITE_ENABLED:
		return gml_error(GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC)
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_push", array_value)
	if values.size() == 0:
		return gml_error("GML array_push requires at least one value")
	for value in values:
		array_value.append(value)
	return null


static func gml_array_equals(left, right):
	if typeof(left) != TYPE_ARRAY or typeof(right) != TYPE_ARRAY:
		return false
	if left.size() != right.size():
		return false
	for index in range(left.size()):
		if not _gml_values_equal_for_array(left[index], right[index]):
			return false
	return true


static func gml_struct(fields = {}):
	if typeof(fields) != TYPE_DICTIONARY:
		return gml_unsupported_type_error("GML struct literal", fields)
	for key in fields.keys():
		if typeof(fields[key]) == TYPE_CALLABLE:
			fields[key] = gml_method(fields, fields[key])
	return fields


static func gml_enum(fields = {}):
	if typeof(fields) != TYPE_DICTIONARY:
		return gml_unsupported_type_error("GML enum declaration", fields)
	var enum_fields = {}
	for key in fields.keys():
		enum_fields[key] = gml_int64(fields[key])
	return enum_fields


static func gml_struct_get(struct_value, member_name):
	var key = str(member_name)
	if typeof(struct_value) == TYPE_DICTIONARY:
		if struct_value.has(key):
			return struct_value[key]
		return gml_undefined()
	if typeof(struct_value) == TYPE_OBJECT:
		if _object_has_property(struct_value, key):
			return struct_value.get(key)
		return gml_undefined()
	return gml_unsupported_type_error("GML struct access", struct_value)


static func gml_variable_struct_get(struct_value, member_name):
	return gml_struct_get(struct_value, member_name)


static func gml_variable_instance_get(instance_value, member_name):
	return gml_selector_get(instance_value, member_name)


static func gml_variable_instance_exists(instance_value, member_name):
	return gml_selector_exists(instance_value, member_name)


static func gml_variable_instance_set(instance_value, member_name, value):
	return gml_selector_set(instance_value, member_name, value)


static func gml_variable_instance_get_names(instance_value):
	return gml_selector_get_names(instance_value)


static func gml_variable_instance_names_count(instance_value):
	return gml_selector_names_count(instance_value)


static func gml_selector_get(target, member_name, current_self = null, current_other = null):
	var targets = gml_with_targets(target, current_self, current_other)
	if targets.is_empty():
		return gml_undefined()
	return gml_struct_get(targets[0], member_name)


static func gml_selector_exists(target, member_name, current_self = null, current_other = null):
	for instance in gml_with_targets(target, current_self, current_other):
		if gml_struct_exists(instance, member_name):
			return true
	return false


static func gml_selector_set(target, member_name, value, current_self = null, current_other = null):
	var targets = gml_with_targets(target, current_self, current_other)
	if targets.is_empty():
		return gml_undefined()
	for instance in targets:
		gml_struct_set(instance, member_name, value)
	return value


static func gml_selector_update(target, member_name, update_callable, current_self = null, current_other = null):
	var targets = gml_with_targets(target, current_self, current_other)
	if targets.is_empty():
		return gml_undefined()
	var result = gml_undefined()
	for instance in targets:
		result = update_callable.call(gml_struct_get(instance, member_name))
		gml_struct_set(instance, member_name, result)
	return result


static func gml_selector_set_if_nullish(target, member_name, value_callable, current_self = null, current_other = null):
	var targets = gml_with_targets(target, current_self, current_other)
	if targets.is_empty():
		return gml_undefined()
	var result = gml_undefined()
	for instance in targets:
		var current_value = gml_struct_get(instance, member_name)
		if gml_is_nullish(current_value):
			result = gml_struct_set(instance, member_name, value_callable.call())
		else:
			result = current_value
	return result


static func gml_selector_get_names(target, current_self = null, current_other = null):
	var targets = gml_with_targets(target, current_self, current_other)
	if targets.is_empty():
		return []
	return gml_struct_get_names(targets[0])


static func gml_selector_names_count(target, current_self = null, current_other = null):
	var targets = gml_with_targets(target, current_self, current_other)
	if targets.is_empty():
		return -1
	return gml_struct_names_count(targets[0])


static func gml_variable_global_exists(member_name):
	return gml_struct_exists(gml_global_scope(), member_name)


static func gml_variable_global_get(member_name):
	return gml_struct_get(gml_global_scope(), member_name)


static func gml_variable_global_set(member_name, value):
	return gml_struct_set(gml_global_scope(), member_name, value)


static func gml_ds_map_find_value(map_value, key):
	var resolved_map = _gml_resolve_ds_map(map_value)
	if typeof(resolved_map) == TYPE_DICTIONARY:
		if resolved_map.has(key):
			return resolved_map[key]
		return gml_undefined()
	return gml_unsupported_type_error("GML ds_map access", resolved_map)


static func gml_ds_map_exists(map_value, key):
	var resolved_map = _gml_resolve_ds_map(map_value)
	if typeof(resolved_map) == TYPE_DICTIONARY:
		return resolved_map.has(key)
	return false


static func gml_ds_map_set(map_value, key, value):
	var resolved_map = _gml_resolve_ds_map(map_value)
	if typeof(resolved_map) == TYPE_DICTIONARY:
		resolved_map[key] = value
		return value
	return gml_unsupported_type_error("GML ds_map access", resolved_map)


static func gml_struct_exists(struct_value, member_name):
	var key = str(member_name)
	if typeof(struct_value) == TYPE_DICTIONARY:
		return struct_value.has(key)
	if typeof(struct_value) == TYPE_OBJECT:
		return _object_has_property(struct_value, key)
	return false


static func gml_struct_set(struct_value, member_name, value):
	var key = str(member_name)
	if typeof(struct_value) == TYPE_DICTIONARY:
		struct_value[key] = value
		return value
	if typeof(struct_value) == TYPE_OBJECT:
		struct_value.set(key, value)
		return value
	return gml_unsupported_type_error("GML struct access", struct_value)


static func gml_struct_remove(struct_value, member_name):
	var key = str(member_name)
	if typeof(struct_value) == TYPE_DICTIONARY:
		struct_value.erase(key)
		return gml_undefined()
	return gml_unsupported_type_error("GML mutable struct access", struct_value)


static func gml_struct_get_names(struct_value):
	if typeof(struct_value) == TYPE_DICTIONARY:
		return struct_value.keys()
	if typeof(struct_value) == TYPE_OBJECT:
		var names = []
		for property in struct_value.get_property_list():
			names.append(property.get("name"))
		return names
	return []


static func gml_struct_names_count(struct_value):
	if typeof(struct_value) == TYPE_DICTIONARY:
		return struct_value.size()
	if typeof(struct_value) == TYPE_OBJECT:
		return struct_value.get_property_list().size()
	return -1


static func gml_struct_foreach(struct_value, callback):
	if not is_struct(struct_value):
		return gml_unsupported_type_error("GML struct_foreach", struct_value)
	if not is_method(callback):
		return gml_unsupported_type_error("GML struct_foreach callback", callback)
	for member_name in gml_struct_get_names(struct_value):
		var member_value = gml_struct_get(struct_value, member_name)
		gml_method_call(callback, [member_name, member_value])
	return null


static func gml_variable_get_hash(name):
	var key = str(name)
	var hash = _gml_hash_string(key)
	_gml_variable_hash_names[hash] = key
	return hash


static func gml_struct_get_from_hash(struct_value, member_hash):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return member_name
	return gml_struct_get(struct_value, member_name)


static func gml_struct_set_from_hash(struct_value, member_hash, value):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return gml_error("Unknown GML variable hash " + str(member_hash))
	return gml_struct_set(struct_value, member_name, value)


static func gml_struct_exists_from_hash(struct_value, member_hash):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return false
	return gml_struct_exists(struct_value, member_name)


static func gml_struct_remove_from_hash(struct_value, member_hash):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return member_name
	return gml_struct_remove(struct_value, member_name)
