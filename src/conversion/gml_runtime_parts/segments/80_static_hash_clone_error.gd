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
	var index = _gml_static_find(value)
	if index >= 0:
		return _gml_static_registry[index]["static"]
	return null


# The registry index of a function or struct, or -1. The structs a loop goes
# through are mostly registered in the order it visits them, so each search
# starts where the last one found its target.
static func _gml_static_find(value):
	var count = _gml_static_registry.size()
	var index = _gml_static_cursor
	if index >= count:
		index = 0
	for _step in range(count):
		if is_same(_gml_static_registry[index]["target"], value):
			_gml_static_cursor = index
			return index
		index += 1
		if index == count:
			index = 0
	return -1


static func _gml_static_set_parent(value, static_struct, constructor_name = ""):
	if typeof(static_struct) == TYPE_DICTIONARY:
		_gml_static_note_struct(static_struct)
	var index = _gml_static_find(value)
	if index >= 0:
		var entry = _gml_static_registry[index]
		entry["static"] = static_struct
		if constructor_name != "":
			entry["constructor_name"] = constructor_name
		return
	var entry = {"target": value, "static": static_struct}
	if constructor_name != "":
		entry["constructor_name"] = constructor_name
	_gml_static_registry.append(entry)


# A new struct has no registry entry yet, so it is not searched for.
static func _gml_static_link_new(value, static_struct):
	_gml_static_cursor = _gml_static_registry.size()
	_gml_static_registry.append({"target": value, "static": static_struct})


static func _gml_static_note_struct(static_struct):
	for known in _gml_static_structs:
		if is_same(known, static_struct):
			return
	_gml_static_structs.append(static_struct)


# The struct of a static chain that holds a variable the struct itself does
# not have, or null: a dot access looks up the struct's own variables, then
# the first static struct of its chain with that name (manual: GML Overview >
# Structs > Static Struct, "How the Dot Operator Looks Up a Variable Name").
static func _gml_static_chain_owner(struct_value, member_name):
	var named = false
	for static_struct in _gml_static_structs:
		if static_struct.has(member_name):
			named = true
			break
	if not named:
		return null
	var current = _gml_static_lookup(struct_value)
	var links = 0
	while current != null and links < GML_STATIC_CHAIN_LIMIT:
		if typeof(current) == TYPE_DICTIONARY and current.has(member_name):
			return current
		current = _gml_static_lookup(current)
		links += 1
	return null


static func _gml_static_name(value):
	var index = _gml_static_find(value)
	if index >= 0 and _gml_static_registry[index].has("constructor_name"):
		return _gml_static_registry[index]["constructor_name"]
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
