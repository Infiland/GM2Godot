import os


GML_RUNTIME_RELATIVE_PATH = os.path.join("gm2godot", "gml_runtime.gd")
GML_RUNTIME_RESOURCE_PATH = "res://gm2godot/gml_runtime.gd"

GML_RUNTIME_SCRIPT = """extends RefCounted

const GML_TYPE_UNDEFINED = "undefined"
const GML_TYPE_BOOL = "bool"
const GML_TYPE_NUMBER = "number"
const GML_TYPE_STRING = "string"
const GML_TYPE_ARRAY = "array"
const GML_TYPE_STRUCT = "struct"
const GML_TYPE_METHOD = "method"
const GML_TYPE_UNKNOWN = "unknown"


static func gml_undefined():
	return null


static func is_undefined(value):
	return value == null


static func is_bool(value):
	return typeof(value) == TYPE_BOOL


static func is_number(value):
	var value_type = typeof(value)
	return value_type == TYPE_INT or value_type == TYPE_FLOAT


static func is_nan_value(value):
	return is_number(value) and is_nan(float(value))


static func is_infinity(value):
	return is_number(value) and is_inf(float(value))


static func gml_div(left, right):
	return float(left) / float(right)


static func gml_eq(left, right):
	if is_undefined(left) or is_undefined(right):
		return is_undefined(left) and is_undefined(right)
	if is_nan_value(left) or is_nan_value(right):
		return false
	return left == right


static func gml_ne(left, right):
	return not gml_eq(left, right)


static func gml_typeof(value):
	if is_undefined(value):
		return GML_TYPE_UNDEFINED
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
	if is_infinity(value):
		return "-infinity" if float(value) < 0.0 else "infinity"
	if is_nan_value(value):
		return "NaN"
	return str(value)


static func gml_bool(value):
	if is_undefined(value):
		return false
	if is_number(value):
		return float(value) > 0.5
	return bool(value)


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
