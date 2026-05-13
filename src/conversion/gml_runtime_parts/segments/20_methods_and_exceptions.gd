static func gml_method_call(method, array_args = null, offset = 0, num_args = null):
	if not is_method(method):
		return gml_unsupported_type_error("GML method_call", method)
	var call_args = _gml_method_call_args(array_args, offset, num_args)
	if is_undefined(call_args):
		return call_args
	return method.gml_callv(call_args)


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

