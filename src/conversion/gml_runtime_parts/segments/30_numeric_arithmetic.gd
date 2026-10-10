# The operators below start with the common case of two plain numbers (int
# or float, not bool), which they handle exactly as the general code further
# down does, without its type checks.

static func gml_div(left, right):
	var left_type = typeof(left)
	var right_type = typeof(right)
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		return _gml_real_divide(float(left), float(right))
	if is_ptr(left) or is_ptr(right):
		return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)
	if _returns_int64_arithmetic_result(left, right):
		var right_int = _to_int64_value(right)
		if right_int == 0:
			return gml_error("GML int64 division by zero")
		return GMLInt64.new(int(_to_int64_value(left) / right_int))
	# GML `/` is always real division, even when both operands hold whole
	# numbers (5 / 2 == 2.5); only int64 / int64 keeps integer semantics.
	if not _is_arithmetic_real_operand(left) or not _is_arithmetic_real_operand(right):
		return gml_unsupported_binary_type_error("GML divide", left, right)
	return _gml_real_divide(_to_real(left), _to_real(right))


static func _gml_real_divide(left_value, right_value):
	if right_value == 0.0:
		if left_value == 0.0:
			return NAN
		return INF if left_value > 0.0 else -INF
	return left_value / right_value


static func gml_int_div(left, right):
	var left_type = typeof(left)
	var right_type = typeof(right)
	if left_type == TYPE_INT and right_type == TYPE_INT and _gml_int32_pair(left, right):
		if right == 0:
			return gml_error("GML int32 division by zero")
		return int(left / right)
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		return int(float(left) / float(right))
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
		# Like comparisons, sqrt uses math_set_epsilon: a negative value no
		# further from 0 than the epsilon counts as 0.
		if real_value >= -_gml_math_epsilon:
			return 0.0
		return NAN
	return sqrt(real_value)


# Whether two ints are both int32 values, which GML adds, subtracts,
# multiplies and divides as int32 (other numbers as reals).
static func _gml_int32_pair(left, right):
	return left >= -2147483648 and left <= 2147483647 and right >= -2147483648 and right <= 2147483647


static func gml_add(left, right):
	var left_type = typeof(left)
	var right_type = typeof(right)
	if left_type == TYPE_FLOAT:
		if right_type == TYPE_FLOAT or right_type == TYPE_INT:
			return left + float(right)
	elif left_type == TYPE_INT:
		if right_type == TYPE_INT:
			return left + right if _gml_int32_pair(left, right) else float(left) + float(right)
		if right_type == TYPE_FLOAT:
			return float(left) + right
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
	var left_type = typeof(left)
	var right_type = typeof(right)
	if left_type == TYPE_FLOAT:
		if right_type == TYPE_FLOAT or right_type == TYPE_INT:
			return left - float(right)
	elif left_type == TYPE_INT:
		if right_type == TYPE_INT:
			return left - right if _gml_int32_pair(left, right) else float(left) - float(right)
		if right_type == TYPE_FLOAT:
			return float(left) - right
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
	var left_type = typeof(left)
	var right_type = typeof(right)
	if left_type == TYPE_FLOAT:
		if right_type == TYPE_FLOAT or right_type == TYPE_INT:
			return left * float(right)
	elif left_type == TYPE_INT:
		if right_type == TYPE_INT:
			return left * right if _gml_int32_pair(left, right) else float(left) * float(right)
		if right_type == TYPE_FLOAT:
			return float(left) * right
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
	var left_type = typeof(left)
	var right_type = typeof(right)
	if left_type == TYPE_INT and right_type == TYPE_INT and _gml_int32_pair(left, right):
		if right == 0:
			return gml_error("GML int32 modulo by zero")
		return left % right
	if (left_type == TYPE_FLOAT or left_type == TYPE_INT) and (right_type == TYPE_FLOAT or right_type == TYPE_INT):
		return fmod(float(left), float(right))
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


