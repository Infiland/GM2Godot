static func gml_unsupported_type_error(api_name, value):
	return gml_error(str(api_name) + " does not support value of type " + gml_type_name(value))


static func gml_unsupported_binary_type_error(api_name, left, right):
	return gml_error(
		str(api_name)
		+ " does not support values of type "
		+ gml_type_name(left)
		+ " and "
		+ gml_type_name(right)
	)


static func _is_real_convertible(value):
	return is_handle(value) or is_int64(value) or is_number(value) or is_bool(value) or is_string(value)


static func _is_int64_convertible(value):
	return is_handle(value) or is_int64(value) or is_number(value) or is_bool(value) or is_string(value)


static func _is_arithmetic_real_operand(value):
	return is_handle(value) or is_int64(value) or is_number(value) or is_bool(value)


static func _to_real(value):
	if is_ptr(value):
		return gml_unsupported_type_error("GML numeric conversion", value)
	if is_handle(value):
		return float(value.index)
	if is_int64(value):
		return float(value.value)
	if is_string(value):
		return _gml_string_to_real(value)
	if _is_real_convertible(value):
		return float(value)
	return gml_unsupported_type_error("GML numeric conversion", value)


static func _to_int64_value(value):
	if is_ptr(value):
		return gml_unsupported_type_error("GML bitwise conversion", value)
	if is_handle(value):
		return int(value.value)
	if is_int64(value):
		return int(value.value)
	if is_string(value):
		return _gml_string_to_int64(value)
	if _is_int64_convertible(value):
		return int(value)
	return gml_unsupported_type_error("GML bitwise conversion", value)


static func _returns_int64_arithmetic_result(left, right):
	return (
		(is_int64(left) and (is_int64(right) or is_int32(right)))
		or (is_int64(right) and is_int32(left))
	)


static func _returns_int32_arithmetic_result(left, right):
	return is_int32(left) and is_int32(right)


static func _to_int32_value(value):
	return int(value)


