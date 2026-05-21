static func gml_static_get(value):
	if value is GMLMethod:
		return gml_static_get(value.function_value)
	if is_method(value):
		return _gml_static_ensure(value)
	if not is_struct(value):
		return gml_unsupported_type_error("GML static_get", value)
	if is_same(value, _gml_static_root):
		return gml_undefined()
	var static_struct = _gml_static_lookup(value)
	if static_struct != null:
		return static_struct
	return _gml_static_root


static func gml_static_scope(scope_id):
	if not _gml_static_named_scopes.has(scope_id):
		_gml_static_named_scopes[scope_id] = {}
	return _gml_static_named_scopes[scope_id]


static func gml_static_bind(value, scope_id, constructor_name = ""):
	var static_struct = gml_static_scope(scope_id)
	if value is GMLMethod:
		_gml_static_set_parent(value.function_value, static_struct, constructor_name)
	elif is_method(value):
		_gml_static_set_parent(value, static_struct, constructor_name)
	else:
		return gml_unsupported_type_error("GML static bind", value)
	return value


static func gml_static_initialize(static_struct, initializers):
	if not is_struct(static_struct):
		return gml_unsupported_type_error("GML static initialize", static_struct)
	if static_struct.has("__gml_static_initialized"):
		return null
	static_struct["__gml_static_initialized"] = true
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
	if not is_struct(static_struct):
		return gml_unsupported_type_error("GML static_set static struct", static_struct)
	_gml_static_set_parent(struct_value, static_struct)
	return null


static func gml_is_instanceof(struct_value, constructor):
	if not is_struct(struct_value):
		return false
	if not is_method(constructor):
		return false
	var constructor_static = gml_static_get(constructor)
	if is_undefined(constructor_static):
		return false
	var current_static = gml_static_get(struct_value)
	while not is_undefined(current_static):
		if _gml_static_same(current_static, constructor_static):
			return true
		current_static = gml_static_get(current_static)
	return false


static func gml_instanceof(struct_value):
	if not is_struct(struct_value):
		return gml_undefined()
	if typeof(struct_value) == TYPE_OBJECT:
		return "instance"
	var static_struct = gml_static_get(struct_value)
	if is_undefined(static_struct) or _gml_static_same(static_struct, _gml_static_root):
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
	if is_undefined(left) or is_undefined(right):
		return is_undefined(left) and is_undefined(right)
	if is_ptr(left) or is_ptr(right):
		return is_ptr(left) and is_ptr(right) and left.value == right.value and left.invalid == right.invalid
	if is_handle(left) or is_handle(right):
		return _gml_handle_eq(left, right)
	if is_nan_value(left) or is_nan_value(right):
		return false
	if is_numeric(left) and is_numeric(right):
		return _to_real(left) == _to_real(right)
	if _is_gml_reference_value(left) or _is_gml_reference_value(right):
		return _is_gml_reference_value(left) and _is_gml_reference_value(right) and is_same(left, right)
	return left == right


static func gml_ne(left, right):
	return not gml_eq(left, right)


static func gml_lt(left, right):
	if is_nan_value(left) or is_nan_value(right):
		return false
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		return _to_real(left) < _to_real(right)
	if is_string(left) and is_string(right):
		return str(left) < str(right)
	return gml_unsupported_binary_type_error("GML less-than comparison", left, right)


static func gml_lte(left, right):
	if is_nan_value(left) or is_nan_value(right):
		return false
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		return _to_real(left) <= _to_real(right)
	if is_string(left) and is_string(right):
		return str(left) <= str(right)
	return gml_unsupported_binary_type_error("GML less-than-or-equal comparison", left, right)


static func gml_gt(left, right):
	if is_nan_value(left) or is_nan_value(right):
		return false
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		return _to_real(left) > _to_real(right)
	if is_string(left) and is_string(right):
		return str(left) > str(right)
	return gml_unsupported_binary_type_error("GML greater-than comparison", left, right)


static func gml_gte(left, right):
	if is_nan_value(left) or is_nan_value(right):
		return false
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		return _to_real(left) >= _to_real(right)
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


static func gml_typeof(value):
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
	var value_type = typeof(value)
	if value_type == TYPE_BOOL:
		return GML_TYPE_BOOL
	if is_int32(value):
		return GML_TYPE_INT32
	if value_type == TYPE_INT or value_type == TYPE_FLOAT:
		return GML_TYPE_NUMBER
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
	if is_ptr(value):
		if value.invalid:
			return "pointer_invalid"
		if value.value == 0:
			return "pointer_null"
		return str(value.value)
	if typeof(value) == TYPE_DICTIONARY:
		if value.has("toString") and is_method(value["toString"]):
			return gml_string(gml_method_call(value["toString"]))
		return str(value)
	return str(value)


static func gml_bool(value):
	if is_undefined(value):
		return false
	if is_ptr(value):
		return not value.invalid and value.value != 0
	if is_handle(value):
		return gml_handle_is_valid(value)
	if is_int64(value):
		return float(value.value) > 0.5
	if is_number(value):
		return float(value) > 0.5
	return bool(value)


static func gml_is_nullish(value):
	return is_undefined(value) or (is_ptr(value) and value.value == 0)


static func gml_type_name(value):
	var gml_type = gml_typeof(value)
	if gml_type != GML_TYPE_UNKNOWN:
		return gml_type
	return "godot_type_" + str(typeof(value))
