const GML_RANDOM_DEFAULT_SEED = 0x13579bdf
const GML_RANDOM_MASK = 0xffffffff
const GML_RANDOM_UNIT_DENOMINATOR = 4294967296.0

const GML_MATH_DEFAULT_EPSILON = 0.00001
const GML_MATH_MINIMUM_EPSILON = 0.00000000001
const GML_COMPARE_UNORDERED = -2
# The value of pi, of pi / 180 and of 180 / pi that GameMaker's runner uses
# in point_direction and lengthdir_*, in degtorad and dsin, dcos and dtan, and
# in radtodeg and darcsin, darccos, darctan and darctan2.
const GML_RUNNER_PI = 3.14159265
const GML_RUNNER_DEGREES_TO_RADIANS = 0.0174532925
const GML_RUNNER_RADIANS_TO_DEGREES = 57.2957795

static var _gml_random_seed = GML_RANDOM_DEFAULT_SEED
static var _gml_random_state = GML_RANDOM_DEFAULT_SEED
static var _gml_math_epsilon = GML_MATH_DEFAULT_EPSILON


static func gml_abs(value):
	if is_int64(value):
		return GMLInt64.new(abs(value.value))
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML abs", value)
	if typeof(value) == TYPE_INT:
		# A whole number stays one: a round trip through a real turns
		# 2^63 - 1 into INT64_MIN, and the magnitude of INT64_MIN is 2^63,
		# which only a real holds.
		if value == GML_INT64_MIN:
			return -float(value)
		return abs(value)
	return abs(_to_real(value))


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
	return _gml_whole_real(floor(_to_real(value)))


static func gml_ceil(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML ceil", value)
	return _gml_whole_real(ceil(_to_real(value)))


static func gml_round(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML round", value)
	var real_value = _to_real(value)
	if is_nan(real_value) or is_inf(real_value):
		return real_value
	# GameMaker rounds exact halves to the nearest even integer (banker's
	# rounding): round(2.5) == 2, round(3.5) == 4, round(-2.5) == -2.
	var floor_value = floor(real_value)
	var fraction = real_value - floor_value
	if fraction > 0.5 or (fraction == 0.5 and fmod(floor_value, 2.0) != 0.0):
		floor_value += 1.0
	return _gml_whole_real(floor_value)


# A whole real (from floor, ceil or round) as an int when a 64-bit integer
# holds it, else as the real it is: the runner's Math.floor, Math.ceil and
# round return an infinity, NaN or a value of 2^63 or more unchanged.
static func _gml_whole_real(value):
	if absf(value) < 9223372036854775808.0:
		return int(value)
	return value


static func gml_math_set_epsilon(value):
	var epsilon = _to_real(value)
	if epsilon >= 0.0 and epsilon < 1.0:
		_gml_math_epsilon = GML_MATH_MINIMUM_EPSILON if epsilon == 0.0 else epsilon
	return gml_undefined()


static func gml_math_get_epsilon():
	return _gml_math_epsilon


static func _gml_compare_reals(left_value, right_value):
	# GameMaker compares reals with an epsilon (math_set_epsilon, 0.00001 by
	# default): values that close compare equal for ==, !=, <, <=, > and >=.
	# NaN is unordered, while two infinities of the same sign compare equal.
	var difference = left_value - right_value
	if is_nan(difference):
		if is_inf(left_value) and is_inf(right_value):
			return 0
		return GML_COMPARE_UNORDERED
	if absf(difference) <= _gml_math_epsilon:
		return 0
	return -1 if difference < 0.0 else 1


static func gml_frac(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML frac", value)
	# The runner's frac is x - ~~x. The truncation stays a real (an int
	# overflows past 2^63), and an infinity truncates to 0, as ~~ does.
	var real_value = _to_real(value)
	return real_value - _gml_truncate_real(real_value)


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
	var real_value = _gml_unit_range_real("arcsin", value)
	return asin(real_value) if typeof(real_value) == TYPE_FLOAT else real_value


static func gml_arccos(value):
	var real_value = _gml_unit_range_real("arccos", value)
	return acos(real_value) if typeof(real_value) == TYPE_FLOAT else real_value


# The runner's arcsin and arccos take a value within the comparison epsilon
# (math_set_epsilon) of -1 or 1 as exactly that and raise an error for any
# other value outside [-1, 1] (Function_Maths.js).
static func _gml_unit_range_real(api_name, value):
	var real_value = _gml_math_real("GML " + api_name, value)
	if typeof(real_value) != TYPE_FLOAT:
		return real_value
	if absf(real_value + 1.0) <= _gml_math_epsilon:
		return -1.0
	if absf(real_value - 1.0) <= _gml_math_epsilon:
		return 1.0
	if real_value < -1.0 or real_value > 1.0:
		return gml_error("Value " + gml_string(real_value) + " is not within valid range [-1.0, 1.0]: " + api_name + "()")
	return real_value


static func gml_arctan(value):
	return atan(_gml_math_real("GML arctan", value))


static func gml_arctan2(y, x):
	if not _is_real_convertible(y) or not _is_real_convertible(x):
		return gml_error("GML arctan2 requires real-convertible arguments")
	return atan2(_to_real(y), _to_real(x))


static func gml_dsin(value):
	return sin(_gml_math_real("GML dsin", value) * GML_RUNNER_DEGREES_TO_RADIANS)


static func gml_dcos(value):
	return cos(_gml_math_real("GML dcos", value) * GML_RUNNER_DEGREES_TO_RADIANS)


static func gml_dtan(value):
	return tan(_gml_math_real("GML dtan", value) * GML_RUNNER_DEGREES_TO_RADIANS)


static func gml_darcsin(value):
	var radians = gml_arcsin(value)
	return radians * GML_RUNNER_RADIANS_TO_DEGREES if typeof(radians) == TYPE_FLOAT else radians


static func gml_darccos(value):
	var radians = gml_arccos(value)
	return radians * GML_RUNNER_RADIANS_TO_DEGREES if typeof(radians) == TYPE_FLOAT else radians


static func gml_darctan(value):
	return atan(_gml_math_real("GML darctan", value)) * GML_RUNNER_RADIANS_TO_DEGREES


static func gml_darctan2(y, x):
	if not _is_real_convertible(y) or not _is_real_convertible(x):
		return gml_error("GML darctan2 requires real-convertible arguments")
	return atan2(_to_real(y), _to_real(x)) * GML_RUNNER_RADIANS_TO_DEGREES


static func gml_degtorad(value):
	if not _is_real_convertible(value):
		return gml_unsupported_type_error("GML degtorad", value)
	# The runner multiplies by its rounded pi / 180.
	return _to_real(value) * GML_RUNNER_DEGREES_TO_RADIANS


static func gml_radtodeg(value):
	return _gml_math_real("GML radtodeg", value) * GML_RUNNER_RADIANS_TO_DEGREES


static func gml_point_distance(x1, y1, x2, y2):
	if not _gml_math_all_real([x1, y1, x2, y2]):
		return gml_error("GML point_distance requires real-convertible arguments")
	return Vector2(_to_real(x1), _to_real(y1)).distance_to(Vector2(_to_real(x2), _to_real(y2)))


# GameMaker's point_in_rectangle (Function_Collision.js): whether the point is
# inside the rectangle from (x1, y1) to (x2, y2), edges included.
static func gml_point_in_rectangle(px, py, x1, y1, x2, y2):
	var point_x = _to_real(px)
	var point_y = _to_real(py)
	return point_x >= _to_real(x1) and point_x <= _to_real(x2) and point_y >= _to_real(y1) and point_y <= _to_real(y2)


static func gml_point_direction(x1, y1, x2, y2):
	if not (_is_real_convertible(x1) and _is_real_convertible(y1) and _is_real_convertible(x2) and _is_real_convertible(y2)):
		return gml_error("GML point_direction requires real-convertible arguments")
	# GameMaker's point_direction: a vertical vector points exactly up (90)
	# or down (270), no vector gives 0, and other angles are rounded to six
	# decimals (computed with the runner's value of pi) through a 32-bit
	# integer, as the runner's ~~round(dd * 1000000) does.
	var dx = _to_real(x2) - _to_real(x1)
	var dy = _to_real(y2) - _to_real(y1)
	if dx == 0.0:
		if dy > 0.0:
			return 270.0
		if dy < 0.0:
			return 90.0
		return 0.0
	var degrees = float(_gml_runner_int32(_gml_collision_round(180.0 * atan2(dy, dx) / GML_RUNNER_PI * 1000000.0))) / 1000000.0
	# (The runner returns -dd, so a vector straight right gives -0.)
	return -degrees if degrees <= 0.0 else 360.0 - degrees


static func gml_lengthdir_x(length, direction):
	if not _is_real_convertible(length) or not _is_real_convertible(direction):
		return gml_error("GML lengthdir_x requires real-convertible arguments")
	return _gml_lengthdir_snap(_to_real(length) * cos(_to_real(direction) * GML_RUNNER_PI / 180.0))


static func gml_lengthdir_y(length, direction):
	if not _is_real_convertible(length) or not _is_real_convertible(direction):
		return gml_error("GML lengthdir_y requires real-convertible arguments")
	return _gml_lengthdir_snap(-(_to_real(length) * sin(_to_real(direction) * GML_RUNNER_PI / 180.0)))


# The runner's lengthdir_x and lengthdir_y (computed with its value of pi)
# return Math.round(value) when the value is within 0.0001 of it. Math.round
# rounds halves up and gives -0 for values from -0.5 to -0.
static func _gml_lengthdir_snap(value):
	var nearest = floor(value + 0.5)
	if absf(value - nearest) < 0.0001:
		return nearest if nearest != 0.0 else value * 0.0
	return value


# GameMaker colours are 0xBBGGRR integers. The colour functions follow the
# runner (Function_Graphics.js): integer arguments are truncated toward zero
# and wrapped to 32 bits like its yyGetInt32 and ~~, and channels are packed
# without clamping, so a channel outside 0..255 spills into its neighbours.
static func gml_make_color_rgb(red, green, blue):
	return _gml_colour_int32(_gml_colour_int32(red) | (_gml_colour_int32(green) << 8) | (_gml_colour_int32(blue) << 16))


static func gml_color_get_red(colour):
	return _gml_colour_int32(colour) & 0xff


static func gml_color_get_green(colour):
	return (_gml_colour_int32(colour) >> 8) & 0xff


static func gml_color_get_blue(colour):
	return (_gml_colour_int32(colour) >> 16) & 0xff


# Hue, saturation and value are reals on a 0..255 scale (Color_RGBtoHSV).
static func gml_color_get_hue(colour):
	return _gml_colour_to_hsv(colour)[0]


static func gml_color_get_saturation(colour):
	return _gml_colour_to_hsv(colour)[1]


static func gml_color_get_value(colour):
	return _gml_colour_to_hsv(colour)[2]


# Each channel moves from col1 towards col2 by amount, which is not clamped,
# and is truncated toward zero.
static func gml_merge_color(col1, col2, amount):
	var first = _gml_colour_int32(col1)
	var second = _gml_colour_int32(col2)
	var factor = _to_real(amount)
	if typeof(factor) != TYPE_FLOAT:
		factor = 0.0
	var keep = 1.0 - factor
	var merged = 0
	for shift in [16, 8, 0]:
		var start = (first >> shift) & 0xff
		var finish = (second >> shift) & 0xff
		merged |= (_gml_colour_int32(start * keep + finish * factor) << shift) & (0xff << shift)
	return merged


# Hue, saturation and value are on a 0..255 scale; each channel is rounded and
# clamped to 0..255.
static func gml_make_color_hsv(hue, saturation, value):
	var hh = _gml_colour_real(hue) * 360.0 / 255.0
	if hh == 360.0:
		hh = 0.0
	var ss = _gml_colour_real(saturation) / 255.0
	var vv = _gml_colour_real(value) / 255.0
	var channels = [vv, vv, vv]
	if ss != 0.0:
		hh = hh / 60.0
		var sector = floor(hh)
		var f = hh - sector
		var p = vv * (1.0 - ss)
		var q = vv * (1.0 - ss * f)
		var t = vv * (1.0 - ss * (1.0 - f))
		match int(sector):
			0:
				channels = [vv, t, p]
			1:
				channels = [q, vv, p]
			2:
				channels = [p, vv, t]
			3:
				channels = [p, q, vv]
			4:
				channels = [t, p, vv]
			_:
				channels = [vv, p, q]
	var packed = 0
	for index in range(3):
		var level = floor(channels[index] * 255.0 + 0.5)
		if not is_nan(level):
			packed |= int(clamp(level, 0.0, 255.0)) << (8 * index)
	return packed


static func _gml_colour_to_hsv(colour):
	var packed = _gml_colour_int32(colour)
	var rr = float(packed & 0xff) / 255.0
	var gg = float((packed >> 8) & 0xff) / 255.0
	var bb = float((packed >> 16) & 0xff) / 255.0
	var low = min(min(rr, gg), bb)
	var vv = max(max(rr, gg), bb)
	var d = vv - low
	var ss = 0.0 if vv == 0.0 else d / vv
	var hh = 0.0
	if ss != 0.0:
		if rr == vv:
			hh = 60.0 * (gg - bb) / d
		elif gg == vv:
			hh = 120.0 + 60.0 * (bb - rr) / d
		else:
			hh = 240.0 + 60.0 * (rr - gg) / d
	if hh < 0.0:
		hh += 360.0
	return [
		clamp(hh * 255.0 / 360.0, 0.0, 255.0),
		clamp(ss * 255.0, 0.0, 255.0),
		clamp(vv * 255.0, 0.0, 255.0),
	]


# yyGetReal for a colour argument; a value that is not a number has already
# raised its GML error and counts as 0.
static func _gml_colour_real(value):
	var real_value = _to_real(value)
	if typeof(real_value) != TYPE_FLOAT:
		return 0.0
	return real_value


# yyGetInt32 / JavaScript ~~: truncate toward zero and wrap into a signed
# 32-bit integer; NaN and infinities give 0.
static func _gml_colour_int32(value):
	var real_value = _gml_colour_real(value)
	if is_nan(real_value) or is_inf(real_value):
		return 0
	var wrapped = int(fmod(real_value - fmod(real_value, 1.0), 4294967296.0))
	if wrapped >= 2147483648:
		return wrapped - 4294967296
	if wrapped < -2147483648:
		return wrapped + 4294967296
	return wrapped


# GameMaker's LookAtLH view matrix (row vectors, left-handed): right = up x
# look, up = look x right, translation = -(eye . axis).
static func gml_matrix_build_lookat(xfrom, yfrom, zfrom, xto, yto, zto, xup, yup, zup):
	var origin = Vector3(_to_real(xfrom), _to_real(yfrom), _to_real(zfrom))
	var target = Vector3(_to_real(xto), _to_real(yto), _to_real(zto))
	var look = (target - origin).normalized()
	if look.length_squared() <= 0.000001:
		look = Vector3(0.0, 0.0, 1.0)
	var up = Vector3(_to_real(xup), _to_real(yup), _to_real(zup)).normalized()
	if up.length_squared() <= 0.000001:
		up = Vector3(0.0, 1.0, 0.0)
	var right = up.cross(look).normalized()
	if right.length_squared() <= 0.000001:
		right = Vector3(1.0, 0.0, 0.0)
	up = look.cross(right).normalized()
	return [
		right.x, up.x, look.x, 0.0,
		right.y, up.y, look.y, 0.0,
		right.z, up.z, look.z, 0.0,
		-origin.dot(right), -origin.dot(up), -origin.dot(look), 1.0
	]


# GameMaker's OrthoLH projection; a zero size or depth gives the identity.
static func gml_matrix_build_projection_ortho(width, height, znear, zfar):
	var resolved_width = _to_real(width)
	var resolved_height = _to_real(height)
	var near_z = _to_real(znear)
	var far_z = _to_real(zfar)
	if resolved_width == 0.0 or resolved_height == 0.0 or near_z == far_z:
		return [
			1.0, 0.0, 0.0, 0.0,
			0.0, 1.0, 0.0, 0.0,
			0.0, 0.0, 1.0, 0.0,
			0.0, 0.0, 0.0, 1.0
		]
	return [
		2.0 / resolved_width, 0.0, 0.0, 0.0,
		0.0, 2.0 / resolved_height, 0.0, 0.0,
		0.0, 0.0, 1.0 / (far_z - near_z), 0.0,
		0.0, 0.0, near_z / (near_z - far_z), 1.0
	]


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
