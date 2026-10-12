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
	var value_type = typeof(value)
	if value_type == TYPE_FLOAT or value_type == TYPE_INT or value_type == TYPE_BOOL or value_type == TYPE_STRING:
		return true
	return is_handle(value) or is_int64(value) or is_string(value)


static func _is_int64_convertible(value):
	return is_handle(value) or is_int64(value) or is_number(value) or is_bool(value) or is_string(value)


static func _is_arithmetic_real_operand(value):
	var value_type = typeof(value)
	if value_type == TYPE_FLOAT or value_type == TYPE_INT or value_type == TYPE_BOOL:
		return true
	return is_handle(value) or is_int64(value)


static func _to_real(value):
	var value_type = typeof(value)
	if value_type == TYPE_FLOAT:
		return value
	if value_type == TYPE_INT:
		return float(value)
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




# The functions gml_unsupported_call has reported, by name.
static var _gml_unsupported_calls_reported = {}


# A call the converted game cannot run (a GameMaker function GM2Godot does not
# support, or an extension function with no Godot mapping). Like the HTML5
# runner's ErrorFunction it reports the function once and returns undefined;
# the rest of the calling code keeps running.
static func gml_unsupported_call(function_name, reason = "", _args = []):
	var name = str(function_name)
	if not _gml_unsupported_calls_reported.has(name):
		_gml_unsupported_calls_reported[name] = true
		gml_error("GML function '" + name + "' cannot run in the converted game: " + str(reason))
	return gml_undefined()
