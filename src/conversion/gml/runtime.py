import os


GML_RUNTIME_RELATIVE_PATH = os.path.join("gm2godot", "gml_runtime.gd")
GML_RUNTIME_RESOURCE_PATH = "res://gm2godot/gml_runtime.gd"

GML_RUNTIME_SCRIPT = """extends RefCounted

static func gml_div(left, right):
	return float(left) / float(right)


static func is_infinity(value):
	return _is_number(value) and is_inf(float(value))


static func gml_typeof(value):
	var value_type = typeof(value)
	if value_type == TYPE_NIL:
		return "undefined"
	if value_type == TYPE_BOOL:
		return "bool"
	if value_type == TYPE_INT or value_type == TYPE_FLOAT:
		return "number"
	if value_type == TYPE_STRING or value_type == TYPE_STRING_NAME:
		return "string"
	if value_type == TYPE_ARRAY:
		return "array"
	if value_type == TYPE_DICTIONARY:
		return "struct"
	if value_type == TYPE_CALLABLE:
		return "method"
	if value_type == TYPE_OBJECT:
		return "struct"
	return "unknown"


static func gml_string(value):
	if is_infinity(value):
		return "-infinity" if float(value) < 0.0 else "infinity"
	if _is_nan_number(value):
		return "NaN"
	return str(value)


static func gml_bool(value):
	if _is_number(value):
		return float(value) > 0.5
	return bool(value)


static func _is_number(value):
	var value_type = typeof(value)
	return value_type == TYPE_INT or value_type == TYPE_FLOAT


static func _is_nan_number(value):
	return _is_number(value) and is_nan(float(value))
"""


def write_gml_runtime(godot_project_path):
    runtime_path = os.path.join(godot_project_path, GML_RUNTIME_RELATIVE_PATH)
    os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
    with open(runtime_path, "w", encoding="utf-8") as f:
        f.write(GML_RUNTIME_SCRIPT)
    return runtime_path
