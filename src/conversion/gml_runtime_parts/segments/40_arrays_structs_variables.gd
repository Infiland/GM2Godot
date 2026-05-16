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


static func gml_array_create(size, value = null):
	var resolved_size = int(_to_real(size))
	if resolved_size < 0:
		return gml_error("GML array_create requires a non-negative size, got " + str(resolved_size))
	var arr = []
	if resolved_size > 0:
		arr.resize(resolved_size)
		if value != null:
			for i in range(resolved_size):
				arr[i] = value
	return arr


static func gml_array_length_1d(array_value):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_length_1d", array_value)
	return array_value.size()


static func gml_array_resize(array_value, size):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_resize", array_value)
	var resolved_size = int(_to_real(size))
	if resolved_size < 0:
		return gml_error("GML array_resize requires a non-negative size")
	array_value.resize(resolved_size)
	return resolved_size


static func gml_array_push_back(array_value, value):
	return gml_array_push(array_value, value)


static func gml_array_pop(array_value):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_pop", array_value)
	if array_value.is_empty():
		return gml_undefined()
	return array_value.pop_back()


static func gml_array_insert(array_value, index, value):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_insert", array_value)
	var resolved_index = int(_to_real(index))
	if resolved_index < 0:
		resolved_index = max(0, array_value.size() + resolved_index)
	array_value.insert(resolved_index, value)
	return value


static func gml_array_delete(array_value, index):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_delete", array_value)
	var resolved_index = _to_array_index(index)
	if resolved_index < 0:
		return gml_undefined()
	if resolved_index >= array_value.size():
		return gml_undefined()
	array_value.remove_at(resolved_index)
	return array_value


static func gml_array_sort(array_value):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_sort", array_value)
	array_value.sort()
	return array_value


static func gml_array_shuffle(array_value):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_shuffle", array_value)
	array_value.shuffle()
	return array_value


static func gml_array_copy(dest, dest_index, src, src_index, length):
	if typeof(dest) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_copy dest", dest)
	if typeof(src) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_copy src", src)
	var resolved_dest_index = int(_to_real(dest_index))
	var resolved_src_index = int(_to_real(src_index))
	var resolved_length = int(_to_real(length))
	if resolved_dest_index < 0:
		resolved_dest_index = max(0, dest.size() + resolved_dest_index)
	if resolved_src_index < 0:
		resolved_src_index = max(0, src.size() + resolved_src_index)
	for i in range(resolved_length):
		var src_idx = resolved_src_index + i
		var dest_idx = resolved_dest_index + i
		if src_idx >= src.size():
			break
		if dest_idx >= dest.size():
			dest.resize(dest_idx + 1)
		dest[dest_idx] = src[src_idx]
	return dest


static func gml_array_concat(array1, array2):
	if typeof(array1) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_concat array1", array1)
	if typeof(array2) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_concat array2", array2)
	var result = []
	for i in range(array1.size()):
		result.append(array1[i])
	for i in range(array2.size()):
		result.append(array2[i])
	return result


static func gml_array_contains(array_value, value):
	if typeof(array_value) != TYPE_ARRAY:
		return false
	return array_value.has(value)


static func gml_array_find_index(array_value, value):
	if typeof(array_value) != TYPE_ARRAY:
		return -1
	return array_value.find(value)


static func gml_array_filter(array_value, callback):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_filter", array_value)
	if not is_method(callback):
		return gml_unsupported_type_error("GML array_filter callback", callback)
	var result = []
	for i in range(array_value.size()):
		var element = array_value[i]
		if gml_method_call(callback, [element, i, array_value]):
			result.append(element)
	return result


static func gml_array_map(array_value, callback):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_map", array_value)
	if not is_method(callback):
		return gml_unsupported_type_error("GML array_map callback", callback)
	var result = []
	for i in range(array_value.size()):
		var element = array_value[i]
		result.append(gml_method_call(callback, [element, i, array_value]))
	return result


static func gml_array_reduce(array_value, callback, initial_value = null):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_reduce", array_value)
	if not is_method(callback):
		return gml_unsupported_type_error("GML array_reduce callback", callback)
	var has_initial = initial_value != null
	if array_value.is_empty():
		if has_initial:
			return initial_value
		return gml_error("GML array_reduce requires initial_value for empty array")
	var accumulator = initial_value if has_initial else array_value[0]
	var start_index = 0 if has_initial else 1
	for i in range(start_index, array_value.size()):
		var element = array_value[i]
		accumulator = gml_method_call(callback, [accumulator, element, i, array_value])
	return accumulator


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
