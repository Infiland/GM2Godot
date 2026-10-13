# The Callable a function's static struct is kept under, or null when the value
# is not a function: a method or a function value, or a script asset (a script's
# name gives its index, which is how GML code names a constructor).
static func _gml_static_function_key(value):
	if value is GMLMethod:
		return value.function_value
	if typeof(value) == TYPE_CALLABLE:
		return value
	if is_numeric(value) and _gml_script_entry(value) != null:
		var descriptor: Variant = _gml_script_resolve(value)
		if typeof(descriptor) == TYPE_DICTIONARY:
			var callable: Variant = descriptor.get("callable", null)
			if callable is GMLMethod:
				return callable.function_value
			if typeof(callable) == TYPE_CALLABLE:
				return callable
	return null


static func gml_static_get(value):
	if typeof(value) == TYPE_DICTIONARY:
		if is_same(value, _gml_static_root):
			return gml_undefined()
		var static_struct = value.get(GML_STATIC_LINK_KEY)
		return _gml_static_root if static_struct == null else static_struct
	var function_key = _gml_static_function_key(value)
	if function_key != null:
		return _gml_static_ensure(function_key)
	if not is_struct(value):
		return gml_unsupported_type_error("GML static_get", value)
	# An instance of an object has no static struct of its own.
	return _gml_static_root


static func gml_static_scope(scope_id):
	if not _gml_static_named_scopes.has(scope_id):
		_gml_static_named_scopes[scope_id] = _gml_static_new_struct()
	return _gml_static_named_scopes[scope_id]


static func gml_static_bind(value, scope_id, constructor_name = ""):
	var static_struct = gml_static_scope(scope_id)
	if constructor_name != "":
		static_struct[GML_STATIC_NAME_KEY] = constructor_name
	var function_key = _gml_static_function_key(value)
	if function_key == null:
		return gml_unsupported_type_error("GML static bind", value)
	_gml_static_functions[function_key] = static_struct
	return value


static func gml_static_initialize(static_struct, initializers):
	if typeof(static_struct) != TYPE_DICTIONARY:
		return gml_unsupported_type_error("GML static initialize", static_struct)
	if static_struct.has(GML_STATIC_INITIALIZED_KEY):
		return null
	static_struct[GML_STATIC_INITIALIZED_KEY] = true
	for initializer in initializers:
		var static_name = initializer[0]
		var initializer_function = initializer[1]
		static_struct[static_name] = initializer_function.call()
	return null


static func gml_static_set(struct_value, static_struct):
	if struct_value is GMLMethod:
		return null
	if is_method(struct_value):
		return gml_unsupported_type_error("GML static_set", struct_value)
	if not is_struct(struct_value):
		return gml_unsupported_type_error("GML static_set", struct_value)
	if typeof(static_struct) != TYPE_DICTIONARY:
		return gml_unsupported_type_error("GML static_set static struct", static_struct)
	if typeof(struct_value) == TYPE_DICTIONARY and not is_same(struct_value, _gml_static_root):
		# instanceof reports the type the struct was made as (the runner's
		# __type), which the new static struct does not change.
		if not struct_value.has(GML_STATIC_TYPE_KEY) and not struct_value.has(GML_STATIC_NAME_KEY):
			struct_value[GML_STATIC_TYPE_KEY] = gml_instanceof(struct_value)
		struct_value[GML_STATIC_LINK_KEY] = static_struct
	return null


# Whether a struct has the constructor's static struct anywhere in its static
# chain (the runner's YYIsInstanceof walks the struct's prototypes). The
# constructor is a script asset, or a function or method value.
static func gml_is_instanceof(struct_value, constructor):
	if typeof(struct_value) != TYPE_DICTIONARY:
		return false
	var function_key = _gml_static_function_key(constructor)
	if function_key == null:
		return false
	var constructor_static = _gml_static_functions.get(function_key)
	if constructor_static == null:
		return false
	var current_static = struct_value.get(GML_STATIC_LINK_KEY)
	var links = 0
	while current_static != null and links < GML_STATIC_CHAIN_LIMIT:
		if is_same(current_static, constructor_static):
			return true
		current_static = current_static.get(GML_STATIC_LINK_KEY)
		links += 1
	return false


# The name of the constructor a struct was made by: "struct" for a struct
# literal, "instance" for an instance, "weakref" for a weak reference, and
# undefined for anything else (the runner's YYInstanceof reads __type).
static func gml_instanceof(struct_value):
	if not is_struct(struct_value):
		return gml_undefined()
	if typeof(struct_value) == TYPE_OBJECT:
		return "instance"
	if struct_value.has(GML_WEAK_REF_MARKER):
		return "weakref"
	var type_name = struct_value.get(GML_STATIC_TYPE_KEY)
	if type_name != null:
		return type_name
	var static_struct = struct_value.get(GML_STATIC_LINK_KEY)
	if static_struct == null or is_same(static_struct, _gml_static_root):
		return "struct"
	var constructor_name = _gml_static_name(static_struct)
	if constructor_name != "":
		return constructor_name
	return gml_undefined()


static func gml_variable_clone(value, depth = 128):
	return _gml_clone_value(value, max(0, int(_to_real(depth))))


static func _gml_resolve_instance(instance_value):
	if is_handle(instance_value) or is_numeric(instance_value) or is_string(instance_value):
		return gml_handle_resolve_for_kind(GML_INSTANCE_HANDLE_KIND, instance_value)
	return instance_value


static func _gml_resolve_ds_map(map_value):
	if is_handle(map_value) or is_numeric(map_value) or is_string(map_value):
		return gml_handle_resolve_for_kind(GML_DS_MAP_HANDLE_KIND, map_value)
	return map_value


static func gml_bit_and(left, right):
	return GMLInt64.new(_to_int64_value(left) & _to_int64_value(right))


static func gml_bit_or(left, right):
	return GMLInt64.new(_to_int64_value(left) | _to_int64_value(right))


static func gml_bit_xor(left, right):
	return GMLInt64.new(_to_int64_value(left) ^ _to_int64_value(right))


static func gml_bit_not(value):
	return GMLInt64.new(~_to_int64_value(value))


static func gml_shift_left(left, right):
	return GMLInt64.new(_to_int64_value(left) << _to_int64_value(right))


static func gml_shift_right(left, right):
	return GMLInt64.new(_to_int64_value(left) >> _to_int64_value(right))


static func gml_eq(left, right):
	# Two plain numbers (the common case) compare with GameMaker's epsilon and
	# two strings by their text, exactly as the general checks below do.
	var left_type = typeof(left)
	var right_type = typeof(right)
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		return _gml_compare_reals(float(left), float(right)) == 0
	if left_type == TYPE_STRING and right_type == TYPE_STRING:
		return left == right
	if is_undefined(left) or is_undefined(right):
		return is_undefined(left) and is_undefined(right)
	if is_ptr(left) or is_ptr(right):
		return is_ptr(left) and is_ptr(right) and left.value == right.value and left.invalid == right.invalid
	if is_handle(left) or is_handle(right):
		return _gml_handle_eq(left, right)
	if is_method(left) or is_method(right):
		return _gml_method_same(left, right)
	if is_numeric(left) and is_numeric(right):
		return _gml_compare_numeric(left, right) == 0
	if _is_gml_reference_value(left) or _is_gml_reference_value(right):
		return _is_gml_reference_value(left) and _is_gml_reference_value(right) and is_same(left, right)
	if is_string(left) and is_string(right):
		return str(left) == str(right)
	if left == null or right == null:
		return left == right
	# Values of different GML types (a string and a number, say) are never
	# equal; Godot would raise "Invalid operands" for such a comparison.
	if typeof(left) != typeof(right):
		return false
	return left == right


static func gml_ne(left, right):
	return not gml_eq(left, right)


static func _gml_compare_numeric(left, right):
	if is_int64(left) and is_int64(right):
		return signi(left.value - right.value)
	return _gml_compare_reals(_to_real(left), _to_real(right))


static func gml_lt(left, right):
	var left_type = typeof(left)
	var right_type = typeof(right)
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		var real_order = _gml_compare_reals(float(left), float(right))
		return real_order != GML_COMPARE_UNORDERED and real_order < 0
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		var order = _gml_compare_numeric(left, right)
		return order != GML_COMPARE_UNORDERED and order < 0
	if is_string(left) and is_string(right):
		return str(left) < str(right)
	return gml_unsupported_binary_type_error("GML less-than comparison", left, right)


static func gml_lte(left, right):
	var left_type = typeof(left)
	var right_type = typeof(right)
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		var real_order = _gml_compare_reals(float(left), float(right))
		return real_order != GML_COMPARE_UNORDERED and real_order <= 0
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		var order = _gml_compare_numeric(left, right)
		return order != GML_COMPARE_UNORDERED and order <= 0
	if is_string(left) and is_string(right):
		return str(left) <= str(right)
	return gml_unsupported_binary_type_error("GML less-than-or-equal comparison", left, right)


static func gml_gt(left, right):
	var left_type = typeof(left)
	var right_type = typeof(right)
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		var real_order = _gml_compare_reals(float(left), float(right))
		return real_order != GML_COMPARE_UNORDERED and real_order > 0
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		var order = _gml_compare_numeric(left, right)
		return order != GML_COMPARE_UNORDERED and order > 0
	if is_string(left) and is_string(right):
		return str(left) > str(right)
	return gml_unsupported_binary_type_error("GML greater-than comparison", left, right)


static func gml_gte(left, right):
	var left_type = typeof(left)
	var right_type = typeof(right)
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		var real_order = _gml_compare_reals(float(left), float(right))
		return real_order != GML_COMPARE_UNORDERED and real_order >= 0
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		var order = _gml_compare_numeric(left, right)
		return order != GML_COMPARE_UNORDERED and order >= 0
	if is_string(left) and is_string(right):
		return str(left) >= str(right)
	return gml_unsupported_binary_type_error("GML greater-than-or-equal comparison", left, right)


static func _is_gml_reference_value(value):
	if is_undefined(value) or is_int64(value) or is_ptr(value) or is_handle(value):
		return false
	var value_type = typeof(value)
	return value_type == TYPE_ARRAY or value_type == TYPE_DICTIONARY or value_type == TYPE_OBJECT


static func _gml_values_equal_for_array(left, right):
	if typeof(left) == TYPE_ARRAY and typeof(right) == TYPE_ARRAY:
		return gml_array_equals(left, right)
	return gml_eq(left, right)


# The runner's typeof: every number is "number", whether Godot holds it as an
# int or a float; the manual's "int32" is not supported on HTML5.
static func gml_typeof(value):
	var value_type = typeof(value)
	if value_type == TYPE_INT or value_type == TYPE_FLOAT:
		return GML_TYPE_NUMBER
	if is_undefined(value):
		return GML_TYPE_UNDEFINED
	if value == null:
		return GML_TYPE_NULL
	if is_handle(value):
		return GML_TYPE_HANDLE
	if is_int64(value):
		return GML_TYPE_INT64
	if is_ptr(value):
		return GML_TYPE_POINTER
	if value_type == TYPE_BOOL:
		return GML_TYPE_BOOL
	if value_type == TYPE_STRING or value_type == TYPE_STRING_NAME:
		return GML_TYPE_STRING
	if value_type == TYPE_ARRAY:
		return GML_TYPE_ARRAY
	if is_method(value):
		return GML_TYPE_METHOD
	if value_type == TYPE_DICTIONARY:
		return GML_TYPE_STRUCT
	if value_type == TYPE_OBJECT:
		return GML_TYPE_STRUCT
	return GML_TYPE_UNKNOWN


static func gml_string(value):
	if is_undefined(value):
		return GML_TYPE_UNDEFINED
	if is_string(value):
		return str(value)
	if is_bool(value):
		return "true" if value else "false"
	if is_handle(value):
		return _gml_handle_to_string(value)
	if is_int64(value):
		return str(value.value)
	if is_infinity(value):
		return "-infinity" if float(value) < 0.0 else "infinity"
	if is_nan_value(value):
		return "NaN"
	if typeof(value) == TYPE_FLOAT:
		var real_value = float(value)
		if real_value == 0.0:
			return "0"
		if real_value == floor(real_value):
			return "%.0f" % real_value
		return "%.2f" % real_value
	if is_ptr(value):
		if value.invalid:
			return "pointer_invalid"
		if value.value == 0:
			return "pointer_null"
		return str(value.value)
	if typeof(value) == TYPE_DICTIONARY:
		return _gml_struct_text(value)
	if typeof(value) == TYPE_ARRAY:
		return str(_gml_text_value(value, 0))
	return str(value)


# string(struct) and the debug output of one: its toString method, which it
# holds itself or finds in its static chain, or else its members.
static func _gml_struct_text(struct_value):
	var to_string = gml_struct_get(struct_value, "toString")
	if is_method(to_string):
		return gml_string(gml_call_value(to_string, [], struct_value, struct_value))
	return str(_gml_text_value(struct_value, 0))


const GML_TEXT_DEPTH_LIMIT = 32


# A struct or array as the text shows it: without the members the runtime
# keeps in a struct (static links hold whole static structs and their methods).
static func _gml_text_value(value, depth):
	if depth > GML_TEXT_DEPTH_LIMIT:
		return value
	var value_type = typeof(value)
	if value_type == TYPE_ARRAY:
		var needs_copy = false
		for element in value:
			var element_type = typeof(element)
			if element_type == TYPE_DICTIONARY or element_type == TYPE_ARRAY:
				needs_copy = true
				break
		if not needs_copy:
			return value
		var array_copy = []
		for element in value:
			array_copy.append(_gml_text_value(element, depth + 1))
		return array_copy
	if value_type == TYPE_DICTIONARY:
		var struct_copy = {}
		for key in _gml_struct_visible_keys(value):
			struct_copy[key] = _gml_text_value(value[key], depth + 1)
		return struct_copy
	return value


static func gml_bool(value):
	var value_type = typeof(value)
	if value_type == TYPE_BOOL:
		return value
	if value_type == TYPE_FLOAT or value_type == TYPE_INT:
		return float(value) > 0.5
	if value_type == TYPE_OBJECT and is_instance_valid(value) and value is GMLHandle:
		# Most often an instance (or noone) from a query. A destroyed
		# instance's id is still a positive number, so true.
		return gml_handle_is_valid(value) or (value.kind == GML_INSTANCE_HANDLE_KIND and value.index >= 0)
	if is_undefined(value):
		return false
	if is_ptr(value):
		return not value.invalid and value.value != 0
	if is_int64(value):
		return float(value.value) > 0.5
	if is_number(value):
		return float(value) > 0.5
	return _gml_bool_other(value, value_type)


# The rest of the runner's yyGetBool: an instance (a node here, even a freed
# one, as a destroyed instance's id stays a number), a struct and a function
# are true; "true", "false" and text that starts with a number read as such;
# anything else (an array, other text) is an error, and false.
static func _gml_bool_other(value, value_type):
	if value_type == TYPE_NIL:
		return false
	if value_type == TYPE_OBJECT or value_type == TYPE_DICTIONARY or value_type == TYPE_CALLABLE:
		return true
	if value_type == TYPE_STRING or value_type == TYPE_STRING_NAME:
		var text = str(value)
		if text == "true":
			return true
		if text == "false":
			return false
		var matched = _gml_bool_number_pattern().search(text)
		if matched != null:
			return matched.get_string().to_float() > 0.5
	gml_error("unable to convert " + gml_string(value) + " to a boolean")
	return false


static var _gml_bool_number_regex = null


# The runner's g_NumberRE: a sign, digits with an optional fraction and an
# exponent up to 29, at the start of the text.
static func _gml_bool_number_pattern():
	if _gml_bool_number_regex == null:
		_gml_bool_number_regex = RegEx.create_from_string("^[-+]?(?:[0-9]{0,30}\\.)?[0-9]{1,30}(?:[Ee][-+]?[1-2]?[0-9])?")
	return _gml_bool_number_regex


# The runner's __yy_is_nullish is `v == undefined || v == null`: a variable
# that was never assigned counts as nullish for ?? and ??=. The instance
# variables an object's scripts and events assign are members of its script,
# which read null until they are first assigned.
static func gml_is_nullish(value):
	var value_type = typeof(value)
	if value_type == TYPE_NIL:
		return true
	if value_type != TYPE_OBJECT:
		return false
	return is_undefined(value) or (is_ptr(value) and value.value == 0)


static func gml_type_name(value):
	var gml_type = gml_typeof(value)
	if gml_type != GML_TYPE_UNKNOWN:
		return gml_type
	return "godot_type_" + str(typeof(value))
