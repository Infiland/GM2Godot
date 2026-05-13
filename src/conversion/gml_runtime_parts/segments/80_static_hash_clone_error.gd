static func _gml_static_ensure(value):
	var static_struct = _gml_static_lookup(value)
	if static_struct != null:
		return static_struct
	static_struct = {}
	var constructor_name = _gml_static_constructor_name(value)
	_gml_static_set_parent(value, static_struct, constructor_name)
	_gml_static_set_parent(static_struct, _gml_static_root, constructor_name)
	return static_struct


static func _gml_static_lookup(value):
	for entry in _gml_static_registry:
		if _gml_static_same(entry["target"], value):
			return entry["static"]
	return null


static func _gml_static_set_parent(value, static_struct, constructor_name = ""):
	for entry in _gml_static_registry:
		if _gml_static_same(entry["target"], value):
			entry["static"] = static_struct
			if constructor_name != "":
				entry["constructor_name"] = constructor_name
			return
	var entry = {"target": value, "static": static_struct}
	if constructor_name != "":
		entry["constructor_name"] = constructor_name
	_gml_static_registry.append(entry)


static func _gml_static_name(value):
	for entry in _gml_static_registry:
		if _gml_static_same(entry["target"], value) and entry.has("constructor_name"):
			return entry["constructor_name"]
	return ""


static func _gml_static_constructor_name(value):
	if value is GMLMethod:
		return _gml_static_constructor_name(value.function_value)
	if typeof(value) == TYPE_CALLABLE:
		var method_name = str(value.get_method())
		if method_name != "":
			return method_name
	return ""


static func _gml_struct_name_from_hash(struct_value, member_hash):
	var hash = _to_int64_value(member_hash)
	if is_struct(struct_value):
		for member_name in gml_struct_get_names(struct_value):
			if _gml_hash_string(member_name) == hash:
				return str(member_name)
	if _gml_variable_hash_names.has(hash):
		return _gml_variable_hash_names[hash]
	return gml_undefined()


static func _gml_hash_string(value):
	var text = str(value)
	var hash = 2166136261
	for index in range(text.length()):
		var code = text.unicode_at(index)
		hash = int((hash ^ code) * 16777619) & 0xffffffff
	return hash


static func _gml_static_same(left, right):
	if _is_gml_reference_value(left) or _is_gml_reference_value(right):
		return _is_gml_reference_value(left) and _is_gml_reference_value(right) and is_same(left, right)
	return left == right


static func _gml_clone_value(value, depth):
	if is_handle(value):
		return value
	var value_type = typeof(value)
	if value_type == TYPE_ARRAY:
		var clone = []
		for element in value:
			clone.append(_gml_clone_value(element, depth - 1) if depth > 0 else element)
		return clone
	if value_type == TYPE_DICTIONARY:
		var clone = {}
		for key in value.keys():
			clone[key] = _gml_clone_value(value[key], depth - 1) if depth > 0 else value[key]
		return clone
	return value


static func gml_error(message):
	push_error("GML runtime error: " + gml_string(message))
	return gml_undefined()
