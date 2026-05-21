const GML_SCRIPT_REGISTRY_PATH = "res://gm2godot/gml_script_registry.gd"

static var _gml_script_registry_loaded = false
static var _gml_script_registry = {}
static var _gml_script_names = {}
static var _gml_script_argument_stack = []


static func gml_method_call(method, array_args = null, offset = 0, num_args = null):
	if not is_method(method):
		return gml_unsupported_type_error("GML method_call", method)
	var call_args = _gml_method_call_args(array_args, offset, num_args)
	if is_undefined(call_args):
		return call_args
	return method.gml_callv(call_args) if method is GMLMethod else method.callv(call_args)


static func gml_script_execute(script, args = []):
	var descriptor: Variant = _gml_script_resolve(script)
	if descriptor == null:
		return gml_unsupported_type_error("GML script_execute", script)
	return gml_script_call(descriptor, args)


static func gml_script_call(script_or_callable, args = []):
	var call_args = args if typeof(args) == TYPE_ARRAY else [args]
	var callable = script_or_callable
	var use_legacy_arguments = false
	if typeof(script_or_callable) == TYPE_DICTIONARY and script_or_callable.has("callable"):
		callable = script_or_callable["callable"]
		use_legacy_arguments = bool(script_or_callable.get("legacy_arguments", false))
	if not is_method(callable):
		return gml_unsupported_type_error("GML script callable", callable)
	_gml_script_push_arguments(call_args)
	var result = null
	if use_legacy_arguments:
		result = callable.gml_callv([]) if callable is GMLMethod else callable.callv([])
	else:
		result = callable.gml_callv(call_args) if callable is GMLMethod else callable.callv(call_args)
	_gml_script_pop_arguments()
	return result


static func gml_script_register(script, callable, legacy_arguments = false):
	if not is_method(callable):
		return false
	var key = _gml_script_key(script)
	if key == "":
		return false
	var name = _gml_script_name(script)
	_gml_script_registry[key] = {
		"callable": callable,
		"name": name,
		"legacy_arguments": gml_bool(legacy_arguments)
	}
	_gml_script_names[name] = key
	return true


static func gml_script_registry_set(entries):
	_gml_script_registry_loaded = true
	_gml_script_registry = {}
	_gml_script_names = {}
	if typeof(entries) != TYPE_ARRAY:
		return null
	for entry in entries:
		if typeof(entry) != TYPE_DICTIONARY or not entry.has("callable"):
			continue
		var script = entry["id"] if entry.has("id") else entry.get("name", "")
		gml_script_register(script, entry["callable"], bool(entry.get("legacy_arguments", false)))
	return null


static func gml_script_registry_entries():
	_gml_script_registry_ensure_loaded()
	var entries = []
	for key in _gml_script_registry.keys():
		var entry: Variant = _gml_script_registry[key]
		entries.append({
			"id": int(key) if is_numeric(key) else key,
			"name": str(entry.get("name", key)),
			"callable": entry["callable"],
			"legacy_arguments": bool(entry.get("legacy_arguments", false))
		})
	return entries


static func gml_script_exists(script):
	return _gml_script_entry(script) != null


static func gml_script_get_name(script):
	return _gml_script_name(script)


static func gml_script_get_callable(script):
	var descriptor: Variant = _gml_script_resolve(script)
	if descriptor == null:
		return gml_undefined()
	return descriptor["callable"]


static func gml_global_function(name):
	return gml_script_get_callable(name)


static func gml_argument(index):
	var args = _gml_builtin_globals["argument"] if _gml_builtin_globals.has("argument") else []
	var resolved_index = int(_to_real(index))
	if typeof(args) == TYPE_ARRAY and resolved_index >= 0 and resolved_index < args.size():
		return args[resolved_index]
	return gml_undefined()


static func gml_argument_count():
	return int(_gml_builtin_globals["argument_count"]) if _gml_builtin_globals.has("argument_count") else 0


static func gml_method(scope, func_or_method, method_is_constructor = false):
	if not is_method(func_or_method):
		return gml_unsupported_type_error("GML method", func_or_method)
	var function_value = gml_method_get_index(func_or_method)
	if is_undefined(function_value):
		return function_value
	return GMLMethod.new(scope, function_value, method_is_constructor)


static func gml_constructor(scope, func_or_method):
	var constructor_method = gml_method(scope, func_or_method, true)
	if constructor_method is GMLMethod:
		gml_static_get(constructor_method)
	return constructor_method


static func gml_new(constructor, args = []):
	if not (constructor is GMLMethod):
		return gml_unsupported_type_error("GML new constructor", constructor)
	if not constructor.is_constructor:
		return gml_unsupported_type_error("GML new constructor", constructor)
	var instance = gml_struct({})
	var constructor_static = gml_static_get(constructor)
	if not is_undefined(constructor_static):
		gml_static_set(instance, constructor_static)
	var call_args = [instance]
	if typeof(args) == TYPE_ARRAY:
		call_args.append_array(args)
	else:
		call_args.append(args)
	constructor.function_value.callv(call_args)
	return instance


static func gml_constructor_inherit(instance, constructor, args = []):
	if not (constructor is GMLMethod):
		return gml_unsupported_type_error("GML parent constructor", constructor)
	if not constructor.is_constructor:
		return gml_unsupported_type_error("GML parent constructor", constructor)
	var parent_static = gml_static_get(constructor)
	if not is_undefined(parent_static):
		var current_static = gml_static_get(instance)
		if not is_undefined(current_static):
			gml_static_set(current_static, parent_static)
	var call_args = [instance]
	if typeof(args) == TYPE_ARRAY:
		call_args.append_array(args)
	else:
		call_args.append(args)
	constructor.function_value.callv(call_args)
	return instance


static func gml_throw(value):
	return GMLException.new(value)


static func gml_exception_value(exception):
	if exception is GMLException:
		return exception.value
	return gml_undefined()


static func gml_exception_struct(exception):
	if not (exception is GMLException):
		return gml_struct({
			"message": gml_string(exception),
			"longMessage": gml_string(exception),
			"script": "",
			"stacktrace": []
		})
	if is_struct(exception.value):
		return exception.value
	var message = gml_string(exception.value)
	return gml_struct({
		"message": message,
		"longMessage": message,
		"script": "",
		"stacktrace": []
	})


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


static func _gml_method_same(left, right):
	if not is_method(left) or not is_method(right):
		return false
	var left_self = gml_method_get_self(left)
	var right_self = gml_method_get_self(right)
	if not gml_eq(left_self, right_self):
		return false
	var left_index = gml_method_get_index(left)
	var right_index = gml_method_get_index(right)
	if typeof(left_index) == TYPE_CALLABLE or typeof(right_index) == TYPE_CALLABLE:
		return typeof(left_index) == TYPE_CALLABLE and typeof(right_index) == TYPE_CALLABLE and left_index == right_index
	return gml_eq(left_index, right_index)


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


static func _gml_script_resolve(script):
	_gml_script_registry_ensure_loaded()
	var key = _gml_script_key(script)
	if key != "" and _gml_script_registry.has(key):
		return _gml_script_registry[key]
	if is_method(script):
		return {"callable": script, "name": "", "legacy_arguments": false}
	return null


static func _gml_script_registry_ensure_loaded():
	if _gml_script_registry_loaded:
		return
	_gml_script_registry_loaded = true
	if not ResourceLoader.exists(GML_SCRIPT_REGISTRY_PATH):
		return
	var registry_script = load(GML_SCRIPT_REGISTRY_PATH)
	if registry_script == null:
		return
	if registry_script.has_method("gml_script_registry_entries"):
		gml_script_registry_set(registry_script.gml_script_registry_entries())


static func _gml_script_entry(script):
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(script)
	if entry != null and entry.has("type") and str(entry["type"]) == "script":
		return entry
	return null


static func _gml_script_key(script):
	var entry: Variant = _gml_script_entry(script)
	if entry != null:
		return str(entry["id"])
	if is_numeric(script):
		return str(_to_int64_value(script))
	var name = str(script)
	if _gml_script_names.has(name):
		return str(_gml_script_names[name])
	if name != "":
		return name
	return ""


static func _gml_script_name(script):
	var entry: Variant = _gml_script_entry(script)
	if entry != null:
		return str(entry["name"])
	var key = _gml_script_key(script)
	if key != "" and _gml_script_registry.has(key):
		return str(_gml_script_registry[key].get("name", key))
	return str(script)


static func _gml_script_push_arguments(args):
	_gml_script_argument_stack.append({
		"argument": _gml_builtin_globals["argument"] if _gml_builtin_globals.has("argument") else [],
		"argument_count": _gml_builtin_globals["argument_count"] if _gml_builtin_globals.has("argument_count") else 0
	})
	_gml_builtin_globals["argument"] = args
	_gml_builtin_globals["argument_count"] = args.size()


static func _gml_script_pop_arguments():
	if _gml_script_argument_stack.is_empty():
		_gml_builtin_globals["argument"] = []
		_gml_builtin_globals["argument_count"] = 0
		return
	var previous: Variant = _gml_script_argument_stack.pop_back()
	_gml_builtin_globals["argument"] = previous["argument"]
	_gml_builtin_globals["argument_count"] = previous["argument_count"]
