static func gml_div(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)
	if _returns_int64_arithmetic_result(left, right):
		var right_int = _to_int64_value(right)
		if right_int == 0:
			return gml_error("GML int64 division by zero")
		return GMLInt64.new(int(_to_int64_value(left) / right_int))
	if _returns_int32_arithmetic_result(left, right):
		var right_int = _to_int32_value(right)
		if right_int == 0:
			return gml_error("GML int32 division by zero")
		return int(_to_int32_value(left) / right_int)
	if not _is_arithmetic_real_operand(left) or not _is_arithmetic_real_operand(right):
		return gml_unsupported_binary_type_error("GML divide", left, right)
	var left_value = _to_real(left)
	var right_value = _to_real(right)
	if right_value == 0.0:
		if left_value == 0.0:
			return NAN
		return INF if left_value > 0.0 else -INF
	return left_value / right_value


static func gml_int_div(left, right):
	if _returns_int64_arithmetic_result(left, right):
		var right_int = _to_int64_value(right)
		if right_int == 0:
			return gml_error("GML int64 division by zero")
		return GMLInt64.new(int(_to_int64_value(left) / right_int))
	if _returns_int32_arithmetic_result(left, right):
		var right_int = _to_int32_value(right)
		if right_int == 0:
			return gml_error("GML int32 division by zero")
		return int(_to_int32_value(left) / right_int)
	if not _is_arithmetic_real_operand(left) or not _is_arithmetic_real_operand(right):
		return gml_unsupported_binary_type_error("GML integer divide", left, right)
	return int(_to_real(left) / _to_real(right))


static func gml_real(value):
	return _to_real(value)


static func gml_int64(value):
	if is_handle(value):
		return GMLInt64.new(value.index)
	if is_int64(value):
		return GMLInt64.new(value.value)
	if is_ptr(value):
		return GMLInt64.new(value.value)
	if is_string(value):
		var int64_value = _gml_string_to_int64(value)
		if is_undefined(int64_value):
			return int64_value
		return GMLInt64.new(int64_value)
	if is_number(value):
		return GMLInt64.new(value)
	return gml_unsupported_type_error("GML int64 conversion", value)


static func gml_repeat_count(value):
	return max(0, int(round(_to_real(value))))


static func gml_sqrt(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML sqrt", value)
	var real_value = _to_real(value)
	if real_value < 0.0:
		return NAN
	return sqrt(real_value)


static func gml_add(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)
	if _returns_int64_arithmetic_result(left, right):
		return GMLInt64.new(_to_int64_value(left) + _to_int64_value(right))
	if _returns_int32_arithmetic_result(left, right):
		return _to_int32_value(left) + _to_int32_value(right)
	if is_string(right):
		if is_string(left):
			return str(left) + str(right)
		if _is_arithmetic_real_operand(left):
			return gml_string(left) + str(right)
		return gml_unsupported_binary_type_error("GML add", left, right)
	if is_string(left):
		return gml_unsupported_binary_type_error("GML add", left, right)
	if _is_arithmetic_real_operand(left) and _is_arithmetic_real_operand(right):
		return _to_real(left) + _to_real(right)
	return gml_unsupported_binary_type_error("GML add", left, right)


static func gml_sub(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)
	if _returns_int64_arithmetic_result(left, right):
		return GMLInt64.new(_to_int64_value(left) - _to_int64_value(right))
	if _returns_int32_arithmetic_result(left, right):
		return _to_int32_value(left) - _to_int32_value(right)
	if not _is_arithmetic_real_operand(left) or not _is_arithmetic_real_operand(right):
		return gml_unsupported_binary_type_error("GML subtract", left, right)
	return _to_real(left) - _to_real(right)


static func gml_mul(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)
	if is_string(right):
		if is_number(left):
			return str(right).repeat(max(0, int(_to_real(left))))
		return gml_unsupported_binary_type_error("GML multiply", left, right)
	if is_string(left):
		return gml_unsupported_binary_type_error("GML multiply", left, right)
	if _returns_int64_arithmetic_result(left, right):
		return GMLInt64.new(_to_int64_value(left) * _to_int64_value(right))
	if _returns_int32_arithmetic_result(left, right):
		return _to_int32_value(left) * _to_int32_value(right)
	if not _is_arithmetic_real_operand(left) or not _is_arithmetic_real_operand(right):
		return gml_unsupported_binary_type_error("GML multiply", left, right)
	return _to_real(left) * _to_real(right)


static func gml_mod(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)
	if _returns_int64_arithmetic_result(left, right):
		var right_int = _to_int64_value(right)
		if right_int == 0:
			return gml_error("GML int64 modulo by zero")
		return GMLInt64.new(_to_int64_value(left) % right_int)
	if _returns_int32_arithmetic_result(left, right):
		var right_int = _to_int32_value(right)
		if right_int == 0:
			return gml_error("GML int32 modulo by zero")
		return _to_int32_value(left) % right_int
	if not _is_arithmetic_real_operand(left) or not _is_arithmetic_real_operand(right):
		return gml_unsupported_binary_type_error("GML modulo", left, right)
	return fmod(_to_real(left), _to_real(right))


