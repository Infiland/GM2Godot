# The static struct of a function (a constructor, or a function with static
# variables), found by the function's Callable. It is created empty the first
# time something asks for it.
static func _gml_static_ensure(function_key):
	var static_struct = _gml_static_functions.get(function_key)
	if static_struct != null:
		return static_struct
	static_struct = _gml_static_new_struct(_gml_static_constructor_name(function_key))
	_gml_static_functions[function_key] = static_struct
	return static_struct


# A static struct holds the static variables of a function and links to the
# static struct of its parent constructor, the root one for a function without
# a parent. A struct made by new links to its constructor's static struct the
# same way, through a member GML code never sees, so the link costs one lookup
# and goes away with the struct.
static func _gml_static_new_struct(constructor_name = ""):
	var static_struct = {GML_STATIC_LINK_KEY: _gml_static_root}
	if constructor_name != "":
		static_struct[GML_STATIC_NAME_KEY] = constructor_name
	return static_struct


# The constructor that is running joins the static struct of the constructor
# it inherits from to its own. That is the innermost constructor on the stack,
# not the struct's own static struct: a constructor between the struct's and
# the root one (Square : Rect : Shape) is the child of the next one up.
static func _gml_static_join_parent(instance, parent_function):
	var child_static = null
	if not _gml_constructor_stack.is_empty():
		child_static = _gml_static_ensure(_gml_constructor_stack[-1])
	elif typeof(instance) == TYPE_DICTIONARY:
		child_static = instance.get(GML_STATIC_LINK_KEY)
	if child_static == null:
		return
	var parent_static = _gml_static_ensure(parent_function)
	if not is_same(child_static.get(GML_STATIC_LINK_KEY), parent_static) and not is_same(child_static, parent_static):
		child_static[GML_STATIC_LINK_KEY] = parent_static


# The struct of a static chain that holds a variable, starting at the first
# static struct of a struct's chain, or null: a dot access looks up the
# struct's own variables, then the first static struct of its chain with that
# name (manual: GML Overview > Structs > Static Struct, "How the Dot Operator
# Looks Up a Variable Name").
static func _gml_static_chain_owner(static_struct, member_name):
	var links = 0
	while static_struct != null and links < GML_STATIC_CHAIN_LIMIT:
		if static_struct.has(member_name):
			return static_struct
		static_struct = static_struct.get(GML_STATIC_LINK_KEY)
		links += 1
	return null


static func _gml_static_name(static_struct):
	if typeof(static_struct) != TYPE_DICTIONARY:
		return ""
	return static_struct.get(GML_STATIC_NAME_KEY, "")


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
		var has_hidden = value.has(GML_STATIC_LINK_KEY)
		for key in value.keys():
			if has_hidden and _gml_static_is_hidden_key(key):
				# The clone shares the original's static chain, as the runner's
				# clone keeps the struct's prototype.
				clone[key] = value[key]
			else:
				clone[key] = _gml_clone_value(value[key], depth - 1) if depth > 0 else value[key]
		return clone
	return value


static func gml_error(message):
	push_error("GML runtime error: " + gml_string(message))
	return gml_undefined()
