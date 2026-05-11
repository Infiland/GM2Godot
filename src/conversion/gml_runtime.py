import os


GML_RUNTIME_RELATIVE_PATH = os.path.join("gm2godot", "gml_runtime.gd")
GML_RUNTIME_RESOURCE_PATH = "res://gm2godot/gml_runtime.gd"

GML_RUNTIME_SCRIPT = """extends RefCounted

const GML_TYPE_UNDEFINED = "undefined"
const GML_TYPE_BOOL = "bool"
const GML_TYPE_NUMBER = "number"
const GML_TYPE_INT64 = "int64"
const GML_TYPE_POINTER = "ptr"
const GML_TYPE_STRING = "string"
const GML_TYPE_ARRAY = "array"
const GML_TYPE_STRUCT = "struct"
const GML_TYPE_METHOD = "method"
const GML_TYPE_UNKNOWN = "unknown"
const GML_ARRAY_COPY_ON_WRITE_ENABLED = false
const GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC = "Legacy GML array copy-on-write mode is not supported by GM2Godot"


class GMLInt64:
	var value = 0

	func _init(initial_value = 0):
		if initial_value is GMLInt64:
			value = initial_value.value
		else:
			value = int(initial_value)


class GMLPointer:
	var value = 0
	var invalid = false

	func _init(initial_value = 0, is_invalid = false):
		value = initial_value
		invalid = is_invalid


class GMLUndefined:
	pass


static var _gml_undefined = GMLUndefined.new()
static var _gml_pointer_null = GMLPointer.new(0)
static var _gml_pointer_invalid = GMLPointer.new(-1, true)


static func gml_undefined():
	return _gml_undefined


static func gml_pointer_null():
	return _gml_pointer_null


static func gml_pointer_invalid():
	return _gml_pointer_invalid


static func is_undefined(value):
	return value is GMLUndefined


static func is_bool(value):
	return typeof(value) == TYPE_BOOL


static func is_string(value):
	var value_type = typeof(value)
	return value_type == TYPE_STRING or value_type == TYPE_STRING_NAME


static func is_number(value):
	var value_type = typeof(value)
	return value_type == TYPE_INT or value_type == TYPE_FLOAT


static func is_real(value):
	return is_number(value)


static func is_int32(value):
	return typeof(value) == TYPE_INT and int(value) >= -2147483648 and int(value) <= 2147483647


static func is_int64(value):
	return value is GMLInt64


static func is_ptr(value):
	return value is GMLPointer


static func is_numeric(value):
	return is_real(value) or is_int64(value)


static func is_array(value):
	return typeof(value) == TYPE_ARRAY


static func is_struct(value):
	return typeof(value) == TYPE_DICTIONARY or typeof(value) == TYPE_OBJECT


static func is_method(value):
	return typeof(value) == TYPE_CALLABLE


static func is_callable(value):
	return is_method(value)


static func is_nan_value(value):
	return is_number(value) and is_nan(float(value))


static func is_infinity(value):
	return is_number(value) and is_inf(float(value))


static func gml_ptr(value):
	if is_ptr(value):
		return value
	if is_int64(value):
		return GMLPointer.new(value.value)
	if is_number(value) or is_string(value):
		return GMLPointer.new(value)
	return gml_error("GML ptr conversion requires a real, string, int64, int32, or pointer")


static func gml_div(left, right):
	var left_value = _to_real(left)
	var right_value = _to_real(right)
	if right_value == 0.0:
		if left_value == 0.0:
			return NAN
		return INF if left_value > 0.0 else -INF
	return left_value / right_value


static func gml_int_div(left, right):
	return int(_to_real(left) / _to_real(right))


static func gml_real(value):
	return _to_real(value)


static func gml_int64(value):
	return GMLInt64.new(value)


static func gml_repeat_count(value):
	return max(0, int(round(_to_real(value))))


static func gml_sqrt(value):
	var real_value = _to_real(value)
	if real_value < 0.0:
		return NAN
	return sqrt(real_value)


static func gml_add(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_error("GML pointer arithmetic is not supported")
	if is_numeric(left) and is_numeric(right):
		return _to_real(left) + _to_real(right)
	if is_string(left) and is_string(right):
		return str(left) + str(right)
	if is_string(right) and (is_numeric(left) or is_bool(left)):
		return gml_string(left) + str(right)
	if is_string(left) and (is_numeric(right) or is_bool(right)):
		return gml_error("Invalid GML string concatenation")
	return left + right


static func gml_sub(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_error("GML pointer arithmetic is not supported")
	return _to_real(left) - _to_real(right)


static func gml_mul(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_error("GML pointer arithmetic is not supported")
	return _to_real(left) * _to_real(right)


static func gml_mod(left, right):
	if is_ptr(left) or is_ptr(right):
		return gml_error("GML pointer arithmetic is not supported")
	return fmod(_to_real(left), _to_real(right))


static func gml_array_get(array_value, index):
	var resolved_index = _to_array_index(index)
	if resolved_index < 0:
		return gml_undefined()
	if typeof(array_value) != TYPE_ARRAY:
		return gml_error("GML array access requires an array")
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


static func gml_struct(fields = {}):
	if typeof(fields) != TYPE_DICTIONARY:
		return gml_error("GML struct literal requires a dictionary")
	return fields


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
	return gml_error("GML struct access requires a struct")


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
	return gml_error("GML struct access requires a struct")


static func gml_struct_remove(struct_value, member_name):
	var key = str(member_name)
	if typeof(struct_value) == TYPE_DICTIONARY:
		struct_value.erase(key)
		return gml_undefined()
	return gml_error("GML struct access requires a mutable struct")


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


static func gml_variable_clone(value, depth = 128):
	return _gml_clone_value(value, max(0, int(_to_real(depth))))


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
	if is_nan_value(left) or is_nan_value(right):
		return false
	if is_numeric(left) and is_numeric(right):
		return _to_real(left) == _to_real(right)
	return left == right


static func gml_ne(left, right):
	return not gml_eq(left, right)


static func gml_typeof(value):
	if is_undefined(value):
		return GML_TYPE_UNDEFINED
	if is_int64(value):
		return GML_TYPE_INT64
	if is_ptr(value):
		return GML_TYPE_POINTER
	var value_type = typeof(value)
	if value_type == TYPE_BOOL:
		return GML_TYPE_BOOL
	if value_type == TYPE_INT or value_type == TYPE_FLOAT:
		return GML_TYPE_NUMBER
	if value_type == TYPE_STRING or value_type == TYPE_STRING_NAME:
		return GML_TYPE_STRING
	if value_type == TYPE_ARRAY:
		return GML_TYPE_ARRAY
	if value_type == TYPE_DICTIONARY:
		return GML_TYPE_STRUCT
	if value_type == TYPE_CALLABLE:
		return GML_TYPE_METHOD
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
		if value.has("toString") and typeof(value["toString"]) == TYPE_CALLABLE:
			return gml_string(value["toString"].call())
		return str(value)
	return str(value)


static func gml_bool(value):
	if is_undefined(value):
		return false
	if is_ptr(value):
		return not value.invalid and value.value != 0
	if is_int64(value):
		return float(value.value) > 0.5
	if is_number(value):
		return float(value) > 0.5
	return bool(value)


static func gml_is_nullish(value):
	return is_undefined(value) or (is_ptr(value) and value.value == 0)


static func _to_real(value):
	if is_ptr(value):
		return gml_error("GML pointer numeric conversion is not supported")
	if is_int64(value):
		return float(value.value)
	return float(value)


static func _to_int64_value(value):
	if is_ptr(value):
		return gml_error("GML pointer bitwise conversion is not supported")
	if is_int64(value):
		return int(value.value)
	return int(value)


static func _to_array_index(value):
	var resolved_index = int(_to_real(value))
	if resolved_index < 0:
		gml_error("Negative GML array index")
		return -1
	return resolved_index


static func _object_has_property(object_value, property_name):
	for property in object_value.get_property_list():
		if property.get("name") == property_name:
			return true
	return false


static func _gml_clone_value(value, depth):
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
"""


def write_gml_runtime(godot_project_path: str) -> str:
    runtime_path = os.path.join(godot_project_path, GML_RUNTIME_RELATIVE_PATH)
    os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
    with open(runtime_path, "w", encoding="utf-8") as f:
        f.write(GML_RUNTIME_SCRIPT)
    return runtime_path
