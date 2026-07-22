const GML_SCRIPT_REGISTRY_PATH = "res://gm2godot/gml_script_registry.gd"

static var _gml_script_registry_loaded = false
static var _gml_script_registry_initializers_running = false
static var _gml_script_registry_initializers_complete = false
static var _gml_script_registry = {}
static var _gml_script_names = {}
static var _gml_script_argument_stack = []


static func _gml_shutdown_container_seen(container, seen_containers):
	# Arrays and Dictionaries do not expose Object instance IDs. Compare their
	# backing storage by identity so recursive/shared containers never invoke
	# deep equality or get traversed more than once.
	for seen_container in seen_containers:
		if is_same(seen_container, container):
			return true
	seen_containers.append(container)
	return false


static func _gml_shutdown_detach_method(method, pending, seen_objects):
	var object_id = method.get_instance_id()
	if seen_objects.has(object_id):
		return
	seen_objects[object_id] = true
	pending.append(method.bound_self)
	pending.append(method.function_value)
	pending.append(method.callable_owner)
	method.bound_self = null
	method.function_value = null
	method.callable_owner = null


static func _gml_shutdown_detach_methods(roots):
	# Use an explicit worklist to remain stack-safe for deeply nested GML data.
	# The identity list keeps cyclic Array/Dictionary graphs finite without
	# cloning or rebuilding their shared structure. Method slots are nulled only
	# during shutdown so the detached GMLMethod objects can also be released.
	var pending = []
	pending.append_array(roots)
	var seen_containers = []
	var seen_objects = {}
	while not pending.is_empty():
		var value = pending.pop_back()
		if value is GMLMethod:
			_gml_shutdown_detach_method(value, pending, seen_objects)
			continue
		if value is GMLException:
			var exception_id = value.get_instance_id()
			if seen_objects.has(exception_id):
				continue
			seen_objects[exception_id] = true
			if value.value is GMLMethod:
				_gml_shutdown_detach_method(value.value, pending, seen_objects)
				value.value = null
			else:
				pending.append(value.value)
			continue
		if value is GMLHandle:
			var handle_id = value.get_instance_id()
			if seen_objects.has(handle_id):
				continue
			seen_objects[handle_id] = true
			if value.reference is GMLMethod:
				_gml_shutdown_detach_method(value.reference, pending, seen_objects)
				value.reference = null
			else:
				pending.append(value.reference)
			continue
		var value_type = typeof(value)
		if value_type != TYPE_ARRAY and value_type != TYPE_DICTIONARY:
			continue
		if _gml_shutdown_container_seen(value, seen_containers):
			continue
		if value_type == TYPE_ARRAY:
			for index in range(value.size()):
				var element = value[index]
				if element is GMLMethod:
					_gml_shutdown_detach_method(element, pending, seen_objects)
					value[index] = null
				else:
					pending.append(element)
			continue
		for key in value.keys():
			var element = value[key]
			if element is GMLMethod:
				_gml_shutdown_detach_method(element, pending, seen_objects)
				value[key] = null
			else:
				pending.append(element)
			if key is GMLMethod:
				_gml_shutdown_detach_method(key, pending, seen_objects)
				value.erase(key)
			else:
				pending.append(key)


static func gm2godot_runtime_shutdown():
	# Script/static registries can form RefCounted cycles through a method's
	# bound receiver or Callable. Detach those edges before clearing the
	# containers so Godot can release generated script instances at shutdown.
	gml_sequence_runtime_cleanup_all()
	_gml_shutdown_detach_methods([
		_gml_script_registry,
		_gml_script_argument_stack,
		_gml_static_registry,
		_gml_static_named_scopes,
		_gml_static_root,
		_gml_global_scope,
		_gml_builtin_arrays,
		_gml_builtin_globals,
	])
	_gml_script_registry.clear()
	_gml_script_names.clear()
	_gml_script_argument_stack.clear()
	_gml_script_registry_loaded = false
	_gml_script_registry_initializers_running = false
	_gml_script_registry_initializers_complete = false
	_gml_static_registry.clear()
	_gml_static_named_scopes.clear()
	_gml_static_root.clear()
	_gml_global_scope.clear()


static func gml_method_call(
	method,
	array_args = null,
	offset = 0,
	num_args = null,
	caller_self = null,
	caller_other = null
):
	var resolved_method = method
	if not is_method(resolved_method):
		var script_descriptor: Variant = _gml_script_resolve(resolved_method)
		if typeof(script_descriptor) == TYPE_DICTIONARY:
			resolved_method = script_descriptor.get(
				"scoped_callable",
				script_descriptor.get("callable", null)
			)
	if not is_method(resolved_method):
		return gml_unsupported_type_error("GML method_call", method)
	var call_args = _gml_method_call_args(array_args, offset, num_args)
	if is_undefined(call_args):
		return call_args
	return (
		resolved_method.gml_callv(call_args, caller_self, caller_other)
		if resolved_method is GMLMethod
		else resolved_method.callv(call_args)
	)


static func gml_call_value(function_value, args = [], caller_self = null, caller_other = null, function_name = ""):
	var call_args = args if typeof(args) == TYPE_ARRAY else [args]
	if is_method(function_value):
		return (
			function_value.gml_callv(call_args, caller_self, caller_other)
			if function_value is GMLMethod
			else function_value.callv(call_args)
		)
	if typeof(function_value) == TYPE_DICTIONARY and function_value.has("callable"):
		return gml_script_call(function_value, call_args, caller_self, caller_other)
	var descriptor: Variant = _gml_script_resolve(function_value)
	if descriptor != null:
		return gml_script_call(descriptor, call_args, caller_self, caller_other)
	if str(function_name) != "":
		descriptor = _gml_script_resolve(str(function_name))
		if descriptor != null:
			return gml_script_call(descriptor, call_args, caller_self, caller_other)
	return gml_unsupported_type_error("GML dynamic function call", function_value)


static func gml_script_execute(script, args = [], caller_self = null, caller_other = null):
	var descriptor: Variant = _gml_script_resolve(script)
	if descriptor == null:
		return gml_unsupported_type_error("GML script_execute", script)
	return gml_script_call(descriptor, args, caller_self, caller_other)


static func gml_script_call(script_or_callable, args = [], caller_self = null, caller_other = null):
	var call_args = args if typeof(args) == TYPE_ARRAY else [args]
	var callable = script_or_callable
	var use_legacy_arguments = false
	var uses_scoped_callable = false
	var has_caller_scope = caller_self != null and not is_undefined(caller_self)
	if not is_method(script_or_callable) and not (
		typeof(script_or_callable) == TYPE_DICTIONARY and script_or_callable.has("callable")
	):
		var resolved_descriptor: Variant = _gml_script_resolve(script_or_callable)
		if resolved_descriptor != null:
			script_or_callable = resolved_descriptor
			callable = resolved_descriptor
	if typeof(script_or_callable) == TYPE_DICTIONARY and script_or_callable.has("callable"):
		if has_caller_scope and script_or_callable.has("scoped_callable"):
			callable = script_or_callable["scoped_callable"]
			uses_scoped_callable = true
		else:
			callable = script_or_callable["callable"]
		use_legacy_arguments = bool(script_or_callable.get("legacy_arguments", false))
	if not is_method(callable):
		return gml_unsupported_type_error("GML script callable", callable)
	_gml_script_push_arguments(call_args)
	var runtime_args = []
	# Older generated registries expose a scoped callable without receiver
	# metadata, so retain their explicit prefix. New generated callables inject
	# their declared receiver arguments in GMLMethod.gml_callv instead.
	if uses_scoped_callable:
		var needs_legacy_scope_prefix = not (callable is GMLMethod)
		if callable is GMLMethod:
			needs_legacy_scope_prefix = (
				callable.receiver_argument_count
				== GML_RECEIVER_ARGUMENTS_NONE
			)
		if needs_legacy_scope_prefix:
			runtime_args.append(caller_self)
			runtime_args.append(
				caller_other
				if caller_other != null and not is_undefined(caller_other)
				else caller_self
			)
	if not use_legacy_arguments:
		runtime_args.append_array(call_args)
	var result = null
	result = (
		callable.gml_callv(runtime_args, caller_self, caller_other)
		if callable is GMLMethod
		else callable.callv(runtime_args)
	)
	_gml_script_pop_arguments()
	return result


static func gml_script_register(script, callable, legacy_arguments = false, scoped_callable = null):
	if not is_method(callable):
		return false
	var key = _gml_script_key(script)
	if key == "":
		return false
	var name = _gml_script_name(script)
	_gml_script_registry[key] = {
		"callable": callable,
		"scoped_callable": scoped_callable if is_method(scoped_callable) else callable,
		"name": name,
		"legacy_arguments": gml_bool(legacy_arguments)
	}
	_gml_script_names[name] = key
	return true


static func gml_script_registry_set(entries):
	if _gml_script_registry_initializers_running:
		return null
	_gml_script_registry_loaded = true
	_gml_script_registry = {}
	_gml_script_names = {}
	if typeof(entries) != TYPE_ARRAY:
		return null
	var initializers = []
	for entry in entries:
		if typeof(entry) != TYPE_DICTIONARY or not entry.has("callable"):
			continue
		var script = entry["id"] if entry.has("id") else entry.get("name", "")
		gml_script_register(
			script,
			entry["callable"],
			bool(entry.get("legacy_arguments", false)),
			entry.get("scoped_callable", null)
		)
		var initializer: Variant = entry.get("initializer", null)
		if is_method(initializer) and not initializers.has(initializer):
			initializers.append(initializer)
	if _gml_script_registry_initializers_complete:
		return null
	_gml_script_registry_initializers_running = true
	for initializer in initializers:
		if initializer is GMLMethod:
			initializer.gml_callv([])
		else:
			initializer.call()
	_gml_script_registry_initializers_running = false
	_gml_script_registry_initializers_complete = true
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
			"scoped_callable": entry.get("scoped_callable", entry["callable"]),
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
	return descriptor.get("scoped_callable", descriptor["callable"])


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


static func _gml_method_has_bound_self(scope):
	return scope != null and not is_undefined(scope)


static func gml_method(scope, func_or_method, method_is_constructor = null):
	if not is_method(func_or_method):
		var script_descriptor: Variant = _gml_script_resolve(func_or_method)
		if typeof(script_descriptor) == TYPE_DICTIONARY:
			func_or_method = script_descriptor.get(
				"scoped_callable",
				script_descriptor.get("callable", null)
			)
	if not is_method(func_or_method):
		return gml_unsupported_type_error("GML method", func_or_method)
	var function_value = gml_method_get_index(func_or_method)
	if is_undefined(function_value):
		return function_value
	var receiver_argument_count = GML_RECEIVER_ARGUMENTS_NONE
	var resolved_is_constructor = (
		bool(method_is_constructor)
		if method_is_constructor != null
		else false
	)
	if func_or_method is GMLMethod:
		receiver_argument_count = func_or_method.receiver_argument_count
		if method_is_constructor == null:
			resolved_is_constructor = func_or_method.is_constructor
	elif typeof(function_value) == TYPE_CALLABLE and function_value.is_custom():
		return gml_error(
			"GML method cannot bind a custom Godot Callable without explicit receiver metadata"
		)
	if resolved_is_constructor and receiver_argument_count == GML_RECEIVER_ARGUMENTS_NONE:
		receiver_argument_count = GML_RECEIVER_ARGUMENTS_SELF
	return GMLMethod.new(
		scope,
		function_value,
		resolved_is_constructor,
		receiver_argument_count,
		_gml_method_has_bound_self(scope)
	)


static func gml_receiver_method(scope, callable):
	if typeof(callable) != TYPE_CALLABLE:
		return gml_unsupported_type_error("GML receiver-aware method", callable)
	return GMLMethod.new(
		scope,
		callable,
		false,
		GML_RECEIVER_ARGUMENTS_SELF_OTHER,
		_gml_method_has_bound_self(scope)
	)


static func gml_receiver_constructor(scope, callable):
	if typeof(callable) != TYPE_CALLABLE:
		return gml_unsupported_type_error("GML receiver-aware constructor", callable)
	var constructor_method = GMLMethod.new(
		scope,
		callable,
		true,
		GML_RECEIVER_ARGUMENTS_SELF_OTHER,
		_gml_method_has_bound_self(scope)
	)
	gml_static_get(constructor_method)
	return constructor_method


static func gml_constructor(scope, func_or_method):
	var constructor_method = gml_method(scope, func_or_method, true)
	if constructor_method is GMLMethod:
		gml_static_get(constructor_method)
	return constructor_method


static func _gml_constructor_resolve(constructor):
	if constructor is GMLMethod:
		return constructor
	var descriptor: Variant = _gml_script_resolve(constructor)
	if typeof(descriptor) == TYPE_DICTIONARY:
		var callable = descriptor.get("callable", null)
		if callable is GMLMethod:
			return callable
	return null


static func _gml_constructor_invoke(constructor, instance, args, constructor_other):
	var call_args = []
	if constructor.receiver_argument_count == GML_RECEIVER_ARGUMENTS_SELF:
		call_args.append(instance)
	elif constructor.receiver_argument_count == GML_RECEIVER_ARGUMENTS_SELF_OTHER:
		call_args.append(instance)
		call_args.append(constructor_other)
	else:
		return gml_error("GML constructor is missing explicit receiver metadata")
	if typeof(args) == TYPE_ARRAY:
		call_args.append_array(args)
	else:
		call_args.append(args)
	return constructor.function_value.callv(call_args)


static func gml_new(constructor, args = [], caller_self = null, caller_other = null):
	constructor = _gml_constructor_resolve(constructor)
	if not (constructor is GMLMethod):
		return gml_unsupported_type_error("GML new constructor", constructor)
	if not constructor.is_constructor:
		return gml_unsupported_type_error("GML new constructor", constructor)
	if typeof(constructor.function_value) != TYPE_CALLABLE:
		return gml_unsupported_type_error("GML constructor callable", constructor.function_value)
	if constructor.receiver_argument_count not in [
		GML_RECEIVER_ARGUMENTS_SELF,
		GML_RECEIVER_ARGUMENTS_SELF_OTHER,
	]:
		return gml_error("GML constructor is missing explicit receiver metadata")
	var instance = gml_struct({})
	var constructor_static = gml_static_get(constructor)
	if not is_undefined(constructor_static):
		gml_static_set(instance, constructor_static)
	# GameMaker's bound-constructor exception uses the constructor's bound
	# scope as other. An unbound script constructor uses the scope that called new.
	var constructor_other = constructor.bound_self if constructor.has_bound_self else caller_self
	if constructor_other == null:
		constructor_other = caller_other
	_gml_constructor_invoke(constructor, instance, args, constructor_other)
	return instance


static func gml_constructor_inherit(
	instance,
	constructor,
	args = [],
	caller_self = null,
	caller_other = null
):
	constructor = _gml_constructor_resolve(constructor)
	if not (constructor is GMLMethod):
		return gml_unsupported_type_error("GML parent constructor", constructor)
	if not constructor.is_constructor:
		return gml_unsupported_type_error("GML parent constructor", constructor)
	if typeof(constructor.function_value) != TYPE_CALLABLE:
		return gml_unsupported_type_error("GML constructor callable", constructor.function_value)
	if constructor.receiver_argument_count not in [
		GML_RECEIVER_ARGUMENTS_SELF,
		GML_RECEIVER_ARGUMENTS_SELF_OTHER,
	]:
		return gml_error("GML constructor is missing explicit receiver metadata")
	var parent_static = gml_static_get(constructor)
	if not is_undefined(parent_static):
		var current_static = gml_static_get(instance)
		if not is_undefined(current_static):
			gml_static_set(current_static, parent_static)
	var constructor_other = constructor.bound_self if constructor.has_bound_self else caller_other
	if constructor_other == null:
		constructor_other = caller_self
	_gml_constructor_invoke(constructor, instance, args, constructor_other)
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
