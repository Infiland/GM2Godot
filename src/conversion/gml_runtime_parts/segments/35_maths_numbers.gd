const GML_RANDOM_DEFAULT_SEED = 0x13579bdf
const GML_RANDOM_MASK = 0xffffffff
const GML_RANDOM_UNIT_DENOMINATOR = 4294967296.0

static var _gml_random_seed = GML_RANDOM_DEFAULT_SEED
static var _gml_random_state = GML_RANDOM_DEFAULT_SEED


static func gml_abs(value):
	if is_int64(value):
		return GMLInt64.new(abs(value.value))
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML abs", value)
	var real_value = _to_real(value)
	if typeof(value) == TYPE_INT:
		return abs(int(real_value))
	return abs(real_value)


static func gml_sign(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML sign", value)
	var real_value = _to_real(value)
	if real_value > 0.0:
		return 1
	if real_value < 0.0:
		return -1
	return 0


static func gml_floor(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML floor", value)
	return int(floor(_to_real(value)))


static func gml_ceil(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML ceil", value)
	return int(ceil(_to_real(value)))


static func gml_round(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML round", value)
	return int(round(_to_real(value)))


static func gml_frac(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML frac", value)
	var real_value = _to_real(value)
	return real_value - int(real_value)


static func gml_sqr(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML sqr", value)
	var real_value = _to_real(value)
	return real_value * real_value


static func gml_power(base, exponent):
	if not _is_real_convertible(base) or not _is_real_convertible(exponent):
		return gml_unsupported_binary_type_error("GML power", base, exponent)
	return pow(_to_real(base), _to_real(exponent))


static func gml_exp(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML exp", value)
	return exp(_to_real(value))


static func gml_ln(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML ln", value)
	return log(_to_real(value))


static func gml_log2(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML log2", value)
	return log(_to_real(value)) / log(2.0)


static func gml_log10(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML log10", value)
	return log(_to_real(value)) / log(10.0)


static func gml_clamp(value, min_value, max_value):
	if not _is_real_convertible(value) or not _is_real_convertible(min_value) or not _is_real_convertible(max_value):
		return gml_error("GML clamp requires real-convertible arguments")
	var lower = min(_to_real(min_value), _to_real(max_value))
	var upper = max(_to_real(min_value), _to_real(max_value))
	return clamp(_to_real(value), lower, upper)


static func gml_lerp(a, b, amount):
	if not _is_real_convertible(a) or not _is_real_convertible(b) or not _is_real_convertible(amount):
		return gml_error("GML lerp requires real-convertible arguments")
	return _to_real(a) + ((_to_real(b) - _to_real(a)) * _to_real(amount))


static func gml_min(values):
	if values.size() == 0:
		return gml_error("GML min requires at least one value")
	var best = values[0]
	var best_real = _to_real(best)
	for index in range(1, values.size()):
		var candidate = values[index]
		var candidate_real = _to_real(candidate)
		if candidate_real < best_real:
			best = candidate
			best_real = candidate_real
	return best


static func gml_max(values):
	if values.size() == 0:
		return gml_error("GML max requires at least one value")
	var best = values[0]
	var best_real = _to_real(best)
	for index in range(1, values.size()):
		var candidate = values[index]
		var candidate_real = _to_real(candidate)
		if candidate_real > best_real:
			best = candidate
			best_real = candidate_real
	return best


static func gml_sin(value):
	return sin(_gml_math_real("GML sin", value))


static func gml_cos(value):
	return cos(_gml_math_real("GML cos", value))


static func gml_tan(value):
	return tan(_gml_math_real("GML tan", value))


static func gml_arcsin(value):
	return asin(_gml_math_real("GML arcsin", value))


static func gml_arccos(value):
	return acos(_gml_math_real("GML arccos", value))


static func gml_arctan(value):
	return atan(_gml_math_real("GML arctan", value))


static func gml_arctan2(y, x):
	if not _is_real_convertible(y) or not _is_real_convertible(x):
		return gml_error("GML arctan2 requires real-convertible arguments")
	return atan2(_to_real(y), _to_real(x))


static func gml_dsin(value):
	return sin(deg_to_rad(_gml_math_real("GML dsin", value)))


static func gml_dcos(value):
	return cos(deg_to_rad(_gml_math_real("GML dcos", value)))


static func gml_dtan(value):
	return tan(deg_to_rad(_gml_math_real("GML dtan", value)))


static func gml_darcsin(value):
	return rad_to_deg(asin(_gml_math_real("GML darcsin", value)))


static func gml_darccos(value):
	return rad_to_deg(acos(_gml_math_real("GML darccos", value)))


static func gml_darctan(value):
	return rad_to_deg(atan(_gml_math_real("GML darctan", value)))


static func gml_darctan2(y, x):
	if not _is_real_convertible(y) or not _is_real_convertible(x):
		return gml_error("GML darctan2 requires real-convertible arguments")
	return rad_to_deg(atan2(_to_real(y), _to_real(x)))


static func gml_degtorad(value):
	return deg_to_rad(_gml_math_real("GML degtorad", value))


static func gml_radtodeg(value):
	return rad_to_deg(_gml_math_real("GML radtodeg", value))


static func gml_point_distance(x1, y1, x2, y2):
	if not _gml_math_all_real([x1, y1, x2, y2]):
		return gml_error("GML point_distance requires real-convertible arguments")
	return Vector2(_to_real(x1), _to_real(y1)).distance_to(Vector2(_to_real(x2), _to_real(y2)))


static func gml_point_direction(x1, y1, x2, y2):
	if not _gml_math_all_real([x1, y1, x2, y2]):
		return gml_error("GML point_direction requires real-convertible arguments")
	var angle = rad_to_deg(atan2(_to_real(y1) - _to_real(y2), _to_real(x2) - _to_real(x1)))
	return _gml_angle_normalize(angle)


static func gml_lengthdir_x(length, direction):
	if not _is_real_convertible(length) or not _is_real_convertible(direction):
		return gml_error("GML lengthdir_x requires real-convertible arguments")
	return _to_real(length) * cos(deg_to_rad(_to_real(direction)))


static func gml_lengthdir_y(length, direction):
	if not _is_real_convertible(length) or not _is_real_convertible(direction):
		return gml_error("GML lengthdir_y requires real-convertible arguments")
	return -_to_real(length) * sin(deg_to_rad(_to_real(direction)))


static func gml_angle_difference(angle1, angle2):
	if not _is_real_convertible(angle1) or not _is_real_convertible(angle2):
		return gml_error("GML angle_difference requires real-convertible arguments")
	return fposmod(_to_real(angle1) - _to_real(angle2) + 180.0, 360.0) - 180.0


static func gml_dot_product(x1, y1, x2, y2):
	if not _gml_math_all_real([x1, y1, x2, y2]):
		return gml_error("GML dot_product requires real-convertible arguments")
	return (_to_real(x1) * _to_real(x2)) + (_to_real(y1) * _to_real(y2))


static func gml_dot_product_3d(x1, y1, z1, x2, y2, z2):
	if not _gml_math_all_real([x1, y1, z1, x2, y2, z2]):
		return gml_error("GML dot_product_3d requires real-convertible arguments")
	return (_to_real(x1) * _to_real(x2)) + (_to_real(y1) * _to_real(y2)) + (_to_real(z1) * _to_real(z2))


static func gml_dot_product_normalised(x1, y1, x2, y2):
	if not _gml_math_all_real([x1, y1, x2, y2]):
		return gml_error("GML dot_product_normalised requires real-convertible arguments")
	var left = Vector2(_to_real(x1), _to_real(y1))
	var right = Vector2(_to_real(x2), _to_real(y2))
	if left.length() == 0.0 or right.length() == 0.0:
		return 0.0
	return left.normalized().dot(right.normalized())


static func gml_dot_product_3d_normalised(x1, y1, z1, x2, y2, z2):
	if not _gml_math_all_real([x1, y1, z1, x2, y2, z2]):
		return gml_error("GML dot_product_3d_normalised requires real-convertible arguments")
	var left = Vector3(_to_real(x1), _to_real(y1), _to_real(z1))
	var right = Vector3(_to_real(x2), _to_real(y2), _to_real(z2))
	if left.length() == 0.0 or right.length() == 0.0:
		return 0.0
	return left.normalized().dot(right.normalized())


static func gml_random(maximum):
	if not _is_real_convertible(maximum):
		return gml_unsupported_type_error("GML random", maximum)
	return _gml_random_unit() * _to_real(maximum)


static func gml_irandom(maximum):
	if not _is_real_convertible(maximum):
		return gml_unsupported_type_error("GML irandom", maximum)
	return _gml_random_int_range(0, int(_to_real(maximum)))


static func gml_random_range(minimum, maximum):
	if not _is_real_convertible(minimum) or not _is_real_convertible(maximum):
		return gml_error("GML random_range requires real-convertible arguments")
	var lower = min(_to_real(minimum), _to_real(maximum))
	var upper = max(_to_real(minimum), _to_real(maximum))
	return lower + (_gml_random_unit() * (upper - lower))


static func gml_irandom_range(minimum, maximum):
	if not _is_real_convertible(minimum) or not _is_real_convertible(maximum):
		return gml_error("GML irandom_range requires real-convertible arguments")
	return _gml_random_int_range(int(_to_real(minimum)), int(_to_real(maximum)))


static func gml_choose(values):
	if values.size() == 0:
		return gml_error("GML choose requires at least one value")
	return values[gml_irandom(values.size() - 1)]


static func gml_randomize():
	var ticks = int(Time.get_ticks_usec()) & GML_RANDOM_MASK
	if ticks == _gml_random_state:
		ticks = int(ticks + 1) & GML_RANDOM_MASK
	_gml_random_seed = ticks
	_gml_random_state = ticks
	return null


static func gml_randomise():
	return gml_randomize()


static func gml_random_set_seed(seed):
	_gml_random_seed = _gml_random_seed_value(seed)
	_gml_random_state = _gml_random_seed
	return null


static func gml_random_get_seed():
	return _gml_random_state


static func _gml_math_real(api_name, value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error(api_name, value)
	return _to_real(value)


static func _gml_math_all_real(values):
	for value in values:
		if not _is_real_convertible(value):
			return false
	return true


static func _gml_angle_normalize(value):
	return fposmod(value, 360.0)


static func _gml_random_seed_value(seed):
	if not _is_int64_convertible(seed):
		return 0
	return int(_to_int64_value(seed)) & GML_RANDOM_MASK


static func _gml_random_next_u32():
	_gml_random_state = int((int(_gml_random_state) * 1664525 + 1013904223) & GML_RANDOM_MASK)
	return _gml_random_state


static func _gml_random_unit():
	return float(_gml_random_next_u32()) / GML_RANDOM_UNIT_DENOMINATOR


static func _gml_random_int_range(minimum, maximum):
	var lower = min(minimum, maximum)
	var upper = max(minimum, maximum)
	var span = upper - lower + 1
	if span <= 0:
		return lower
	return lower + int(floor(_gml_random_unit() * span))
