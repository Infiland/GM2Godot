extends RefCounted

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
const GML_LAYER_HANDLE_KIND = "layer"
const GML_LAYER_ELEMENT_HANDLE_KIND = "layer_element"
const GML_SEQUENCE_HANDLE_KIND = "sequence"
const GML_TIMELINE_HANDLE_KIND = "timeline"
const GML_DS_MAP_HANDLE_KIND = "ds_map"
const GML_DS_LIST_HANDLE_KIND = "ds_list"
const GML_DS_STACK_HANDLE_KIND = "ds_stack"
const GML_DS_QUEUE_HANDLE_KIND = "ds_queue"
const GML_DS_PRIORITY_HANDLE_KIND = "ds_priority"
const GML_DS_GRID_HANDLE_KIND = "ds_grid"
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


const GML_RECEIVER_ARGUMENTS_NONE = 0
const GML_RECEIVER_ARGUMENTS_SELF = 1
const GML_RECEIVER_ARGUMENTS_SELF_OTHER = 2


class GMLMethod:
	var bound_self = null
	var function_value = null
	var callable_owner = null
	var is_constructor = false
	var receiver_argument_count = GML_RECEIVER_ARGUMENTS_NONE
	var has_bound_self = true

	func _init(
		method_self = null,
		method_function = null,
		method_is_constructor = false,
		method_receiver_argument_count = GML_RECEIVER_ARGUMENTS_NONE,
		method_has_bound_self = true
	):
		bound_self = method_self
		function_value = method_function
		if typeof(method_function) == TYPE_CALLABLE and method_function.is_standard():
			callable_owner = method_function.get_object()
		is_constructor = bool(method_is_constructor)
		receiver_argument_count = int(method_receiver_argument_count)
		has_bound_self = bool(method_has_bound_self)

	func gml_callv(args, caller_self = null, caller_other = null):
		# Generated receiver-aware callables declare their hidden arity explicitly.
		# Callable custom/standard status does not describe a GML receiver contract:
		# lambdas, bound arguments, Variant methods, and RPC callables are all custom.
		if receiver_argument_count != GML_RECEIVER_ARGUMENTS_NONE:
			var method_self = bound_self if has_bound_self else caller_self
			var method_other = caller_self if has_bound_self else caller_other
			if method_other == null:
				method_other = method_self
			var call_args = [method_self]
			if receiver_argument_count == GML_RECEIVER_ARGUMENTS_SELF_OTHER:
				call_args.append(method_other)
			call_args.append_array(args)
			return function_value.callv(call_args)
		if bound_self is Object and typeof(function_value) == TYPE_CALLABLE and function_value.is_standard():
			var method_name = function_value.get_method()
			if str(method_name) != "" and bound_self.has_method(method_name):
				return Callable(bound_self, method_name).callv(args)
		return function_value.callv(args)


class GMLException:
	var value = null

	func _init(exception_value = null):
		value = exception_value


class GMLUndefined:
	pass


static var _gml_undefined = GMLUndefined.new()
static var _gml_pointer_null = GMLPointer.new(0)
static var _gml_pointer_invalid = GMLPointer.new(-1, true)
static var _gml_handle_registry = {}
static var _gml_handle_next_indices = {}
static var _gml_handle_type_ids = {}
static var _gml_handle_next_type_id = 1
static var _gml_instance_entries = {}
static var _gml_instance_handles_by_node_id = {}
static var _gml_instance_ids_by_object = {}
static var _gml_instance_ids_by_object_name = {}
static var _gml_instance_creation_counter = 0
static var _gml_layer_handles_by_index = {}
static var _gml_layer_handles_by_node_id = {}
static var _gml_layer_handles_by_name = {}
static var _gml_layer_element_handles_by_index = {}
static var _gml_layer_element_handles_by_node_id = {}
static var _gml_sequence_objects_by_id = {}
static var _gml_sequence_elements_by_index = {}
static var _gml_timeline_states_by_instance_id = {}
static var _gml_timeline_moments_by_asset_id = {}
static var _gml_static_root = {}
static var _gml_static_registry = []
static var _gml_static_named_scopes = {}
static var _gml_variable_hash_names = {}
static var _gml_global_scope = {
	"health": 100,
	"lives": 0,
	"score": 0
}
static var _gml_builtin_arrays = {}
static var _gml_builtin_globals = {
	"application_surface": _gml_undefined,
	"argument": [],
	"argument_count": 0,
	"async_load": {},
	"display_aa": 0,
	"event_data": {},
	"instance_count": 0,
	"room": _gml_undefined,
	"room_height": 0,
	"room_speed": 0,
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
	if _gml_view_is_builtin_array(key):
		return _gml_view_builtin_array(key)
	if not _gml_builtin_arrays.has(key):
		var values = []
		for _index in range(GML_BUILTIN_ARRAY_SIZE):
			values.append(gml_undefined())
		_gml_builtin_arrays[key] = values
	return _gml_builtin_arrays[key]


static func gml_builtin_global(name):
	var key = str(name)
	if key == "application_surface":
		return gml_application_surface()
	if key == "keyboard_key":
		return _gml_input_keyboard_key
	if key == "keyboard_lastkey":
		return _gml_input_keyboard_lastkey
	if key == "keyboard_string":
		return _gml_input_keyboard_string
	if key == "mouse_x":
		return gml_display_mouse_get_x()
	if key == "mouse_y":
		return gml_display_mouse_get_y()
	if key == "mouse_wheel_up":
		return _gml_input_mouse_wheel_up
	if key == "mouse_wheel_down":
		return _gml_input_mouse_wheel_down
	if key == "program_directory":
		return gml_program_directory()
	if key == "temp_directory":
		return gml_temp_directory()
	if key == "working_directory":
		return gml_working_directory()
	if key == "current_time":
		return Time.get_ticks_msec()
	if key == "current_year":
		return int(Time.get_datetime_dict_from_system().get("year", 0))
	if key == "current_month":
		return int(Time.get_datetime_dict_from_system().get("month", 0))
	if key == "current_day":
		return int(Time.get_datetime_dict_from_system().get("day", 0))
	if key == "current_minute":
		return int(Time.get_datetime_dict_from_system().get("minute", 0))
	if key == "current_second":
		return int(Time.get_datetime_dict_from_system().get("second", 0))
	if key == "debug_mode":
		return OS.is_debug_build()
	if key == "fps":
		return int(Engine.get_frames_per_second())
	if key == "fps_real":
		return Engine.get_frames_per_second()
	if key == "browser_height":
		return gml_browser_height()
	if key == "browser_width":
		return gml_browser_width()
	if key == "webgl_enabled":
		return gml_webgl_enabled()
	if key == "os_browser":
		return gml_os_browser()
	if key == "os_device":
		return gml_os_device()
	if key == "os_type":
		return gml_os_type()
	if key == "os_version":
		return gml_os_version()
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


static func is_gml_exception(value):
	return value is GMLException


static func is_nan_value(value):
	return is_number(value) and is_nan(float(value))


static func is_infinity(value):
	return is_number(value) and is_inf(float(value))
