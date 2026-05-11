import os


GML_RUNTIME_RELATIVE_PATH = os.path.join("gm2godot", "gml_runtime.gd")
GML_RUNTIME_RESOURCE_PATH = "res://gm2godot/gml_runtime.gd"

GML_RUNTIME_SCRIPT = """extends RefCounted

const GML_TYPE_UNDEFINED = "undefined"
const GML_TYPE_NULL = "null"
const GML_TYPE_BOOL = "bool"
const GML_TYPE_NUMBER = "number"
const GML_TYPE_INT32 = "int32"
const GML_TYPE_INT64 = "int64"
const GML_TYPE_POINTER = "ptr"
const GML_TYPE_STRING = "string"
const GML_TYPE_ARRAY = "array"
const GML_TYPE_STRUCT = "struct"
const GML_TYPE_METHOD = "method"
const GML_TYPE_HANDLE = "ref"
const GML_TYPE_UNKNOWN = "unknown"
const GML_ARRAY_COPY_ON_WRITE_ENABLED = false
const GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC = "Legacy GML array copy-on-write mode is not supported by GM2Godot"
const GML_HANDLE_TYPE_SHIFT = 32
const GML_HANDLE_INDEX_MASK = 0xffffffff
const GML_HANDLE_INVALID_INDEX = -1
const GML_INSTANCE_SELF_INDEX = -1
const GML_INSTANCE_OTHER_INDEX = -2
const GML_INSTANCE_ALL_INDEX = -3
const GML_INSTANCE_INVALID_INDEX = -4
const GML_INSTANCE_HANDLE_KIND = "instance"
const GML_DS_MAP_HANDLE_KIND = "ds_map"
const GML_REFERENCE_HANDLE_KIND = "dbgref"
const GML_VARIABLE_HASH_ALGORITHM = "fnv1a32"
const GML_BUILTIN_ARRAY_SIZE = 8


class GMLInt64:
	var _value = 0
	var value:
		get:
			return _value
		set(_new_value):
			push_error("GML int64 values are immutable")

	func _init(initial_value = 0):
		if initial_value is GMLInt64:
			_value = int(initial_value.value)
		else:
			_value = int(initial_value)


class GMLPointer:
	var value = 0
	var invalid = false

	func _init(initial_value = 0, is_invalid = false):
		value = initial_value
		invalid = is_invalid


class GMLHandle:
	var kind = ""
	var index = -1
	var reference = null
	var valid = false
	var name = ""
	var type_id = 0
	var value = 0

	func _init(handle_kind = "", handle_index = -1, handle_reference = null, handle_name = "", is_valid = false, handle_type_id = 0, encoded_value = 0):
		kind = str(handle_kind)
		index = int(handle_index)
		reference = handle_reference
		name = str(handle_name)
		valid = bool(is_valid)
		type_id = int(handle_type_id)
		value = int(encoded_value)


class GMLMethod:
	var bound_self = null
	var function_value = null

	func _init(method_self = null, method_function = null):
		bound_self = method_self
		function_value = method_function

	func callv(args):
		if bound_self is Object and is_method(function_value):
			var method_name = function_value.get_method()
			if str(method_name) != "":
				return Callable(bound_self, method_name).callv(args)
		return function_value.callv(args)


class GMLUndefined:
	pass


static var _gml_undefined = GMLUndefined.new()
static var _gml_pointer_null = GMLPointer.new(0)
static var _gml_pointer_invalid = GMLPointer.new(-1, true)
static var _gml_handle_registry = {}
static var _gml_handle_next_indices = {}
static var _gml_handle_type_ids = {}
static var _gml_handle_next_type_id = 1
static var _gml_static_root = {}
static var _gml_static_registry = []
static var _gml_variable_hash_names = {}
static var _gml_global_scope = {}
static var _gml_builtin_arrays = {}
static var _gml_builtin_globals = {
	"argument": [],
	"argument_count": 0,
	"async_load": {},
	"event_data": {},
	"instance_count": 0,
	"room": _gml_undefined,
	"room_height": 0,
	"room_width": 0
}


static func gml_undefined():
	return _gml_undefined


static func gml_pointer_null():
	return _gml_pointer_null


static func gml_pointer_invalid():
	return _gml_pointer_invalid


static func gml_global_scope():
	return _gml_global_scope


static func gml_builtin_array(name):
	var key = str(name)
	if not _gml_builtin_arrays.has(key):
		var values = []
		for _index in range(GML_BUILTIN_ARRAY_SIZE):
			values.append(gml_undefined())
		_gml_builtin_arrays[key] = values
	return _gml_builtin_arrays[key]


static func gml_builtin_global(name):
	var key = str(name)
	if _gml_builtin_globals.has(key):
		return _gml_builtin_globals[key]
	return gml_undefined()


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


static func is_handle(value):
	return value is GMLHandle


static func is_numeric(value):
	return is_real(value) or is_int64(value) or is_bool(value)


static func is_array(value):
	return typeof(value) == TYPE_ARRAY


static func is_struct(value):
	return typeof(value) == TYPE_DICTIONARY or typeof(value) == TYPE_OBJECT


static func is_method(value):
	return value is GMLMethod or typeof(value) == TYPE_CALLABLE


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
	if is_string(value):
		var pointer_value = _gml_string_to_int64(value)
		if is_undefined(pointer_value):
			return pointer_value
		return GMLPointer.new(pointer_value)
	if is_number(value):
		return GMLPointer.new(int(value))
	return gml_unsupported_type_error("GML ptr conversion", value)


static func gml_handle_register(kind, reference, name = ""):
	var handle_kind = str(kind)
	var handle_index = _gml_next_handle_index(handle_kind)
	var handle = _gml_make_handle(handle_kind, handle_index, reference, str(name), true)
	_gml_handle_registry[_gml_handle_key(handle_kind, handle_index)] = handle
	return handle


static func gml_handle_get(kind, index):
	var handle_kind = str(kind)
	var handle_index = _to_int64_value(index)
	if _gml_is_invalid_handle_index(handle_kind, handle_index):
		return _gml_make_handle(handle_kind, handle_index, null, "", false)
	var key = _gml_handle_key(handle_kind, handle_index)
	if _gml_handle_registry.has(key):
		return _gml_handle_registry[key]
	return _gml_make_handle(handle_kind, handle_index, null, "", false)


static func gml_handle_invalid(kind = "", invalid_index = GML_HANDLE_INVALID_INDEX):
	return _gml_make_handle(str(kind), int(invalid_index), null, "", false)


static func gml_instance_noone():
	return gml_handle_invalid(GML_INSTANCE_HANDLE_KIND, GML_INSTANCE_INVALID_INDEX)


static func gml_instance_all():
	return gml_handle_invalid(GML_INSTANCE_HANDLE_KIND, GML_INSTANCE_ALL_INDEX)


static func gml_handle_is_valid(handle):
	if not is_handle(handle):
		return false
	if _gml_is_invalid_handle_index(handle.kind, handle.index):
		return false
	if not handle.valid:
		return false
	if handle.reference is Object and not is_instance_valid(handle.reference):
		gml_handle_invalidate(handle)
		return false
	return true


static func gml_handle_parse(value):
	var parts = str(value).split(" ", false)
	if parts.size() != 3 or parts[0] != "ref":
		return gml_handle_invalid()
	var kind = parts[1]
	var identifier = parts[2]
	if _gml_string_is_int(identifier):
		return gml_handle_get(kind, int(identifier))
	return _gml_handle_get_by_name(kind, identifier)


static func gml_ref_create(target, member_or_index, array_index = null):
	var descriptor = {
		"target": target,
		"member_or_index": member_or_index,
		"has_array_index": array_index != null,
		"array_index": array_index
	}
	return gml_handle_register(GML_REFERENCE_HANDLE_KIND, descriptor)


static func gml_handle_from_value(kind, value):
	var handle_kind = str(kind)
	if is_handle(value):
		if value.kind == handle_kind:
			return value
		return gml_handle_invalid(handle_kind)
	if is_string(value):
		var parsed = gml_handle_parse(value)
		if is_handle(parsed) and parsed.kind == handle_kind:
			return parsed
		return gml_handle_invalid(handle_kind)
	if is_numeric(value):
		return gml_handle_get(handle_kind, _to_int64_value(value))
	return gml_handle_invalid(handle_kind)


static func gml_handle_resolve_for_kind(kind, value):
	return gml_handle_resolve(gml_handle_from_value(kind, value))


static func gml_handle_resolve(handle):
	if gml_handle_is_valid(handle):
		return handle.reference
	return null


static func gml_handle_invalidate(handle):
	if handle is GMLHandle:
		var old_key = _gml_handle_key(handle.kind, handle.index)
		handle.valid = false
		handle.reference = null
		handle.index = _gml_invalid_handle_index(handle.kind)
		handle.value = _gml_encode_handle_value(handle.type_id, handle.index)
		_gml_handle_registry.erase(old_key)
	return handle


static func gml_method_call(method, array_args = null, offset = 0, num_args = null):
	if not is_method(method):
		return gml_unsupported_type_error("GML method_call", method)
	var call_args = _gml_method_call_args(array_args, offset, num_args)
	if is_undefined(call_args):
		return call_args
	return method.callv(call_args)


static func gml_method(scope, func_or_method):
	if not is_method(func_or_method):
		return gml_unsupported_type_error("GML method", func_or_method)
	var function_value = gml_method_get_index(func_or_method)
	if is_undefined(function_value):
		return function_value
	return GMLMethod.new(scope, function_value)


static func gml_method_get_self(method):
	if not is_method(method):
		return gml_unsupported_type_error("GML method_get_self", method)
	if method is GMLMethod:
		if is_undefined(method.bound_self):
			return gml_undefined()
		return method.bound_self
	var bound_self = method.get_object()
	if bound_self == null:
		return gml_undefined()
	return bound_self


static func gml_method_get_index(method):
	if not is_method(method):
		return gml_unsupported_type_error("GML method_get_index", method)
	if method is GMLMethod:
		return method.function_value
	return method


static func _gml_method_call_args(array_args, offset, num_args):
	var source = [] if array_args == null else array_args
	if typeof(source) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML method_call arguments", source)
	var source_size = source.size()
	var start = int(_to_real(offset))
	if start < 0:
		start = source_size + start
	var count = source_size - start if num_args == null else int(_to_real(num_args))
	if count == 0:
		return []
	if source_size == 0 or start < 0 or start >= source_size:
		return gml_error("GML method_call offset out of range")
	var step = -1 if count < 0 else 1
	var remaining = abs(count)
	var args = []
	var index = start
	while remaining > 0:
		if index < 0 or index >= source_size:
			return gml_error("GML method_call argument range out of bounds")
		args.append(source[index])
		index += step
		remaining -= 1
	return args


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


static func gml_array_get(array_value, index):
	var resolved_index = _to_array_index(index)
	if resolved_index < 0:
		return gml_undefined()
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array access", array_value)
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


static func gml_array_push(array_value, ...values):
	if GML_ARRAY_COPY_ON_WRITE_ENABLED:
		return gml_error(GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC)
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML array_push", array_value)
	if values.size() == 0:
		return gml_error("GML array_push requires at least one value")
	for value in values:
		array_value.append(value)
	return null


static func gml_array_equals(left, right):
	if typeof(left) != TYPE_ARRAY or typeof(right) != TYPE_ARRAY:
		return false
	if left.size() != right.size():
		return false
	for index in range(left.size()):
		if not _gml_values_equal_for_array(left[index], right[index]):
			return false
	return true


static func gml_struct(fields = {}):
	if typeof(fields) != TYPE_DICTIONARY:
		return gml_unsupported_type_error("GML struct literal", fields)
	for key in fields.keys():
		if typeof(fields[key]) == TYPE_CALLABLE:
			fields[key] = gml_method(fields, fields[key])
	return fields


static func gml_enum(fields = {}):
	if typeof(fields) != TYPE_DICTIONARY:
		return gml_unsupported_type_error("GML enum declaration", fields)
	var enum_fields = {}
	for key in fields.keys():
		enum_fields[key] = gml_int64(fields[key])
	return enum_fields


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
	return gml_unsupported_type_error("GML struct access", struct_value)


static func gml_variable_struct_get(struct_value, member_name):
	return gml_struct_get(struct_value, member_name)


static func gml_variable_instance_get(instance_value, member_name):
	var resolved_instance = _gml_resolve_instance(instance_value)
	if resolved_instance == null:
		return gml_undefined()
	return gml_struct_get(resolved_instance, member_name)


static func gml_variable_instance_exists(instance_value, member_name):
	var resolved_instance = _gml_resolve_instance(instance_value)
	if resolved_instance == null:
		return false
	return gml_struct_exists(resolved_instance, member_name)


static func gml_variable_instance_set(instance_value, member_name, value):
	var resolved_instance = _gml_resolve_instance(instance_value)
	if resolved_instance == null:
		return gml_undefined()
	return gml_struct_set(resolved_instance, member_name, value)


static func gml_variable_instance_get_names(instance_value):
	var resolved_instance = _gml_resolve_instance(instance_value)
	if resolved_instance == null:
		return []
	return gml_struct_get_names(resolved_instance)


static func gml_variable_instance_names_count(instance_value):
	var resolved_instance = _gml_resolve_instance(instance_value)
	if resolved_instance == null:
		return -1
	return gml_struct_names_count(resolved_instance)


static func gml_variable_global_exists(member_name):
	return gml_struct_exists(gml_global_scope(), member_name)


static func gml_variable_global_get(member_name):
	return gml_struct_get(gml_global_scope(), member_name)


static func gml_variable_global_set(member_name, value):
	return gml_struct_set(gml_global_scope(), member_name, value)


static func gml_ds_map_find_value(map_value, key):
	var resolved_map = _gml_resolve_ds_map(map_value)
	if typeof(resolved_map) == TYPE_DICTIONARY:
		if resolved_map.has(key):
			return resolved_map[key]
		return gml_undefined()
	return gml_unsupported_type_error("GML ds_map access", resolved_map)


static func gml_ds_map_exists(map_value, key):
	var resolved_map = _gml_resolve_ds_map(map_value)
	if typeof(resolved_map) == TYPE_DICTIONARY:
		return resolved_map.has(key)
	return false


static func gml_ds_map_set(map_value, key, value):
	var resolved_map = _gml_resolve_ds_map(map_value)
	if typeof(resolved_map) == TYPE_DICTIONARY:
		resolved_map[key] = value
		return value
	return gml_unsupported_type_error("GML ds_map access", resolved_map)


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
	return gml_unsupported_type_error("GML struct access", struct_value)


static func gml_struct_remove(struct_value, member_name):
	var key = str(member_name)
	if typeof(struct_value) == TYPE_DICTIONARY:
		struct_value.erase(key)
		return gml_undefined()
	return gml_unsupported_type_error("GML mutable struct access", struct_value)


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


static func gml_struct_foreach(struct_value, callback):
	if not is_struct(struct_value):
		return gml_unsupported_type_error("GML struct_foreach", struct_value)
	if not is_method(callback):
		return gml_unsupported_type_error("GML struct_foreach callback", callback)
	for member_name in gml_struct_get_names(struct_value):
		var member_value = gml_struct_get(struct_value, member_name)
		gml_method_call(callback, [member_name, member_value])
	return null


static func gml_variable_get_hash(name):
	var key = str(name)
	var hash = _gml_hash_string(key)
	_gml_variable_hash_names[hash] = key
	return hash


static func gml_struct_get_from_hash(struct_value, member_hash):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return member_name
	return gml_struct_get(struct_value, member_name)


static func gml_struct_set_from_hash(struct_value, member_hash, value):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return gml_error("Unknown GML variable hash " + str(member_hash))
	return gml_struct_set(struct_value, member_name, value)


static func gml_struct_exists_from_hash(struct_value, member_hash):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return false
	return gml_struct_exists(struct_value, member_name)


static func gml_struct_remove_from_hash(struct_value, member_hash):
	var member_name = _gml_struct_name_from_hash(struct_value, member_hash)
	if is_undefined(member_name):
		return member_name
	return gml_struct_remove(struct_value, member_name)


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
		var resolved_map = gml_handle_resolve_for_kind(GML_DS_MAP_HANDLE_KIND, map_value)
		if resolved_map != null:
			return resolved_map
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


static func _gml_next_handle_index(kind):
	var next_index = int(_gml_handle_next_indices.get(kind, 0))
	_gml_handle_next_indices[kind] = next_index + 1
	return next_index


static func _gml_handle_key(kind, index):
	return str(kind) + ":" + str(int(index))


static func _gml_handle_to_string(handle):
	var label = handle.name if str(handle.name) != "" else str(handle.index)
	return "ref " + str(handle.kind) + " " + str(label)


static func _gml_handle_get_by_name(kind, name):
	var handle_kind = str(kind)
	var handle_name = str(name)
	for handle in _gml_handle_registry.values():
		if handle.kind == handle_kind and handle.name == handle_name:
			return handle
	return gml_handle_invalid(handle_kind)


static func _gml_make_handle(kind, index, reference, name, is_valid):
	var handle_kind = str(kind)
	var handle_index = int(index)
	var handle_type_id = _gml_handle_type_id(handle_kind)
	var encoded_value = _gml_encode_handle_value(handle_type_id, handle_index)
	return GMLHandle.new(handle_kind, handle_index, reference, str(name), bool(is_valid), handle_type_id, encoded_value)


static func _gml_invalid_handle_index(kind):
	return GML_INSTANCE_INVALID_INDEX if str(kind) == GML_INSTANCE_HANDLE_KIND else GML_HANDLE_INVALID_INDEX


static func _gml_is_invalid_handle_index(kind, index):
	return int(index) == _gml_invalid_handle_index(kind)


static func _gml_handle_eq(left, right):
	if is_handle(left) and is_handle(right):
		return left.kind == right.kind and left.index == right.index
	if is_handle(left) and is_numeric(right):
		return left.index == _to_int64_value(right)
	if is_handle(right) and is_numeric(left):
		return _to_int64_value(left) == right.index
	return false


static func _gml_handle_type_id(kind):
	var handle_kind = str(kind)
	if not _gml_handle_type_ids.has(handle_kind):
		_gml_handle_type_ids[handle_kind] = _gml_handle_next_type_id
		_gml_handle_next_type_id += 1
	return int(_gml_handle_type_ids[handle_kind])


static func _gml_encode_handle_value(type_id, index):
	return (int(type_id) << GML_HANDLE_TYPE_SHIFT) | (int(index) & GML_HANDLE_INDEX_MASK)


static func _gml_string_is_int(value):
	var text = str(value)
	if text == "":
		return false
	var start = 1 if text.begins_with("-") else 0
	if start >= text.length():
		return false
	for index in range(start, text.length()):
		var code = text.unicode_at(index)
		if code < 48 or code > 57:
			return false
	return true


static func _gml_string_to_real(value):
	var text = str(value).strip_edges()
	if text.to_lower().is_valid_hex_number(true):
		return float(_gml_hex_string_to_int(text))
	if text.is_valid_float():
		return text.to_float()
	return gml_error("GML real conversion does not support string " + text)


static func _gml_string_to_int64(value):
	var text = str(value).strip_edges()
	if text.to_lower().is_valid_hex_number(true):
		return _gml_hex_string_to_int(text)
	if text.is_valid_float():
		return int(text.to_float())
	return gml_error("GML int64 conversion does not support string " + text)


static func _gml_hex_string_to_int(value):
	var text = str(value).strip_edges()
	var sign = 1
	if text.begins_with("-"):
		sign = -1
		text = text.substr(1)
	elif text.begins_with("+"):
		text = text.substr(1)
	if text.to_lower().begins_with("0x"):
		text = text.substr(2)
	var result = 0
	for index in range(text.length()):
		result = result * 16 + _gml_hex_digit_value(text.unicode_at(index))
	return sign * result


static func _gml_hex_digit_value(code):
	if code >= 48 and code <= 57:
		return code - 48
	if code >= 65 and code <= 70:
		return code - 55
	if code >= 97 and code <= 102:
		return code - 87
	return 0


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


static func _gml_static_ensure(value):
	var static_struct = _gml_static_lookup(value)
	if static_struct != null:
		return static_struct
	static_struct = {}
	var constructor_name = _gml_static_constructor_name(value)
	_gml_static_set_parent(value, static_struct, constructor_name)
	_gml_static_set_parent(static_struct, _gml_static_root, constructor_name)
	return static_struct


static func _gml_static_lookup(value):
	for entry in _gml_static_registry:
		if _gml_static_same(entry["target"], value):
			return entry["static"]
	return null


static func _gml_static_set_parent(value, static_struct, constructor_name = ""):
	for entry in _gml_static_registry:
		if _gml_static_same(entry["target"], value):
			entry["static"] = static_struct
			if constructor_name != "":
				entry["constructor_name"] = constructor_name
			return
	var entry = {"target": value, "static": static_struct}
	if constructor_name != "":
		entry["constructor_name"] = constructor_name
	_gml_static_registry.append(entry)


static func _gml_static_name(value):
	for entry in _gml_static_registry:
		if _gml_static_same(entry["target"], value) and entry.has("constructor_name"):
			return entry["constructor_name"]
	return ""


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


static func _gml_static_same(left, right):
	if _is_gml_reference_value(left) or _is_gml_reference_value(right):
		return _is_gml_reference_value(left) and _is_gml_reference_value(right) and is_same(left, right)
	return left == right


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
