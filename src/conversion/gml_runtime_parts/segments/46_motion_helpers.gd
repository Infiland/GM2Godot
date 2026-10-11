# GameMaker motion built-ins.
#
# speed/direction and hspeed/vspeed are two views of one motion vector.
# Assigning one pair recomputes the other the way the GameMaker runner does:
# cos/sin are truncated to six decimals and results within 0.0001 of a whole
# number snap to it, so instances moving at whole speeds keep whole-pixel
# positions. Each step applies friction, then gravity, then moves the
# instance by hspeed/vspeed.
const GML_MOTION_DEGREES_TO_RADIANS = 0.0174532925
const GML_MOTION_WHOLE_SNAP = 0.0001
const GML_MOTION_SYNCED_FIELDS = ["direction", "hspeed", "speed", "vspeed"]
const GML_MOTION_DEFAULT_STEPS = 1000
const GML_MOTION_RANDOM_ATTEMPTS = 99
const GML_MOTION_BOUNCE_ANGLES = 35

# Whether a script declares direction, speed, hspeed, vspeed, friction and
# gravity (converted objects do): their instances' motion members are then
# read and written directly instead of by name.
static var _gml_motion_member_scripts = {}


static func gml_motion_set(current_self, direction, speed):
	if _gml_motion_is_instance(current_self):
		_gml_motion_assign_direction(current_self, direction)
		_gml_motion_assign_speed(current_self, speed)
		return null
	for instance in _gml_motion_instances(current_self):
		_gml_motion_assign_direction(instance, direction)
		_gml_motion_assign_speed(instance, speed)
	return null


static func gml_motion_add(current_self, direction, speed):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_add_to_speed(instance, _to_real(direction), _to_real(speed))
	return null


static func gml_motion_set_speed(target, value):
	var result = _to_real(value)
	if _gml_motion_is_instance(target):
		_gml_motion_assign_speed(target, result)
		return result
	for instance in _gml_motion_instances(target):
		_gml_motion_assign_speed(instance, result)
	return result


static func gml_motion_set_direction(target, value):
	var result = _gml_motion_wrap_direction(_to_real(value))
	if _gml_motion_is_instance(target):
		_gml_motion_assign_direction(target, result)
		return result
	for instance in _gml_motion_instances(target):
		_gml_motion_assign_direction(instance, result)
	return result


static func gml_motion_set_hspeed(target, value):
	var result = _to_real(value)
	for instance in _gml_motion_instances(target):
		_gml_motion_assign_hspeed(instance, result)
	return result


static func gml_motion_set_vspeed(target, value):
	var result = _to_real(value)
	for instance in _gml_motion_instances(target):
		_gml_motion_assign_vspeed(instance, result)
	return result


static func gml_motion_sync_from_speed_direction(target):
	for instance in _gml_motion_instances(target):
		_gml_motion_compute_components(instance)
	return null


static func gml_motion_step(current_self):
	if _gml_motion_is_instance(current_self):
		_gml_motion_step_instance(current_self)
		return null
	for instance in _gml_motion_instances(current_self):
		_gml_motion_step_instance(instance)
	return null


static func gml_move_towards_point(current_self, x, y, speed):
	for instance in _gml_motion_instances(current_self):
		var position = _gml_motion_position(instance)
		_gml_motion_assign_hspeed(instance, _to_real(x) - position.x)
		_gml_motion_assign_vspeed(instance, _to_real(y) - position.y)
		_gml_motion_assign_speed(instance, speed)
	return null


static func gml_move_contact_solid(current_self, direction, maxdist):
	return _gml_move_contact(current_self, direction, maxdist, false)


static func gml_move_contact_all(current_self, direction, maxdist):
	return _gml_move_contact(current_self, direction, maxdist, true)


static func gml_move_outside_solid(current_self, direction, maxdist):
	return _gml_move_outside(current_self, direction, maxdist, false)


static func gml_move_outside_all(current_self, direction, maxdist):
	return _gml_move_outside(current_self, direction, maxdist, true)


static func gml_move_bounce_solid(current_self, advanced):
	return _gml_move_bounce(current_self, gml_bool(advanced), false)


static func gml_move_bounce_all(current_self, advanced):
	return _gml_move_bounce(current_self, gml_bool(advanced), true)


static func gml_move_random(current_self, hsnap, vsnap):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_random_instance(instance, _gml_collision_round(_to_real(hsnap)), _gml_collision_round(_to_real(vsnap)))
	return null


static func gml_move_snap(current_self, hsnap, vsnap):
	var hsnap_value = _to_real(hsnap)
	var vsnap_value = _to_real(vsnap)
	for instance in _gml_motion_instances(current_self):
		var position = _gml_motion_position(instance)
		if hsnap_value > 0.0:
			position.x = _gml_collision_round(position.x / hsnap_value) * hsnap_value
		if vsnap_value > 0.0:
			position.y = _gml_collision_round(position.y / vsnap_value) * vsnap_value
		_gml_motion_set_position(instance, position)
	return null


static func gml_move_wrap(current_self, horizontal, vertical, margin):
	var margin_value = _to_real(margin)
	var room_w = _gml_builtin_global_real("room_width", 0.0)
	var room_h = _gml_builtin_global_real("room_height", 0.0)
	for instance in _gml_motion_instances(current_self):
		var position = _gml_motion_position(instance)
		if gml_bool(horizontal):
			if position.x < -margin_value:
				position.x += room_w + 2.0 * margin_value
			if position.x > room_w + margin_value:
				position.x -= room_w + 2.0 * margin_value
		if gml_bool(vertical):
			if position.y < -margin_value:
				position.y += room_h + 2.0 * margin_value
			if position.y > room_h + margin_value:
				position.y -= room_h + 2.0 * margin_value
		_gml_motion_set_position(instance, position)
	return null


static func gml_place_snapped(current_self, hsnap, vsnap):
	var instances = _gml_motion_instances(current_self)
	if instances.is_empty():
		return false
	var position = _gml_motion_position(instances[0])
	var hsnap_value = _to_real(hsnap)
	var vsnap_value = _to_real(vsnap)
	if hsnap_value > 0.0 and abs(position.x - hsnap_value * _gml_collision_round(position.x / hsnap_value)) >= 0.001:
		return false
	if vsnap_value > 0.0 and abs(position.y - vsnap_value * _gml_collision_round(position.y / vsnap_value)) >= 0.001:
		return false
	return true


# Whether the target is an instance itself (self, other, a stored instance):
# gml_with_targets then gives just that instance.
static func _gml_motion_is_instance(target):
	return typeof(target) == TYPE_OBJECT and is_instance_valid(target) and target is Node


static func _gml_motion_instances(target):
	if _gml_motion_is_instance(target):
		return [target]
	var instances = []
	for instance in gml_with_targets(target):
		if instance != null:
			instances.append(instance)
	return instances


static func _gml_motion_step_instance(instance):
	if not (instance is Node2D):
		return
	# xprevious/yprevious hold the position from the start of the step; the
	# step loop records them before Begin Step.

	if _gml_motion_declares_members(instance):
		# Without friction and gravity the instance just moves by
		# hspeed/vspeed, as below.
		var member_friction = instance.friction
		var member_gravity = instance.gravity
		var member_hspeed = instance.hspeed
		var member_vspeed = instance.vspeed
		if (
			typeof(member_friction) == TYPE_FLOAT and member_friction == 0.0
			and typeof(member_gravity) == TYPE_FLOAT and member_gravity == 0.0
			and typeof(member_hspeed) == TYPE_FLOAT and typeof(member_vspeed) == TYPE_FLOAT
		):
			if member_hspeed != 0.0 or member_vspeed != 0.0:
				var member_position = _gml_motion_position(instance)
				_gml_motion_set_position(instance, Vector2(member_position.x + member_hspeed, member_position.y + member_vspeed))
			return
	var hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
	var vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)
	# Friction and gravity change the motion before the instance moves.
	if _gml_motion_adapt_speed(instance):
		hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
		vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)
	if hspeed_value != 0.0 or vspeed_value != 0.0:
		var position = _gml_motion_position(instance)
		_gml_motion_set_position(instance, Vector2(position.x + hspeed_value, position.y + vspeed_value))


static func _gml_motion_adapt_speed(instance):
	# Friction slows the instance towards a standstill without reversing it;
	# gravity then adds its vector. Returns whether the motion may have
	# changed.
	var changed = false
	var friction_value = _gml_motion_real(instance, "friction", 0.0)
	if friction_value != 0.0:
		var speed_value = _gml_motion_real(instance, "speed", 0.0)
		var next_speed = speed_value - friction_value if speed_value > 0.0 else speed_value + friction_value
		if (speed_value > 0.0 and next_speed < 0.0) or (speed_value < 0.0 and next_speed > 0.0):
			_gml_motion_assign_speed(instance, 0.0)
			changed = true
		elif speed_value != 0.0:
			_gml_motion_assign_speed(instance, next_speed)
			changed = true
	var gravity_value = _gml_motion_real(instance, "gravity", 0.0)
	if gravity_value != 0.0:
		_gml_motion_add_to_speed(instance, _gml_motion_real(instance, "gravity_direction", 270.0), gravity_value)
		changed = true
	return changed


static func _gml_move_contact(current_self, direction, maxdist, use_all):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_move_contact_instance(instance, direction, maxdist, use_all)
	return null


static func _gml_motion_move_contact_instance(instance, direction, maxdist, use_all):
	# Moves one pixel at a time in the direction until the next pixel would
	# collide; an instance that already collides does not move.
	var steps = _gml_motion_contact_steps(maxdist)
	var radians = _to_real(direction) * PI / 180.0
	var dx = cos(radians)
	var dy = -sin(radians)
	# The path is followed in full precision; only the end point is stored.
	var start = _gml_motion_position(instance)
	var px = float(start.x)
	var py = float(start.y)
	if not _gml_motion_contact_free(instance, px, py, use_all):
		return
	var moved = false
	for _step in range(steps):
		if not _gml_motion_contact_free(instance, px + dx, py + dy, use_all):
			break
		px += dx
		py += dy
		moved = true
	if moved:
		_gml_motion_set_position(instance, Vector2(px, py))


static func _gml_move_outside(current_self, direction, maxdist, use_all):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_move_outside_instance(instance, direction, maxdist, use_all)
	return null


static func _gml_motion_move_outside_instance(instance, direction, maxdist, use_all):
	var steps = _gml_motion_contact_steps(maxdist)
	var radians = _to_real(direction) * PI / 180.0
	var dx = cos(radians)
	var dy = -sin(radians)
	var start = _gml_motion_position(instance)
	var px = float(start.x)
	var py = float(start.y)
	if _gml_motion_contact_free(instance, px, py, use_all):
		return
	for _step in range(steps):
		px += dx
		py += dy
		if _gml_motion_contact_free(instance, px, py, use_all):
			break
	_gml_motion_set_position(instance, Vector2(px, py))


static func _gml_motion_contact_steps(maxdist):
	var distance = _to_real(maxdist)
	if distance <= 0.0:
		return GML_MOTION_DEFAULT_STEPS
	return int(_gml_collision_round(distance))


static func _gml_motion_contact_free(instance, x, y, use_all):
	if use_all:
		return gml_place_empty(instance, x, y)
	return gml_place_free(instance, x, y)


static func _gml_move_bounce(current_self, advanced, use_all):
	for instance in _gml_motion_instances(current_self):
		if advanced:
			_gml_motion_bounce_advanced(instance, use_all)
		else:
			_gml_motion_bounce_simple(instance, use_all)
	return null


static func _gml_motion_bounce_restore(instance, use_all):
	# An instance that already collides first goes back to its previous
	# position.
	var position = _gml_motion_position(instance)
	if _gml_motion_contact_free(instance, position.x, position.y, use_all):
		return false
	_gml_motion_set_position(
		instance,
		Vector2(_gml_motion_real(instance, "xprevious", position.x), _gml_motion_real(instance, "yprevious", position.y))
	)
	return true


static func _gml_motion_bounce_simple(instance, use_all):
	_gml_motion_bounce_restore(instance, use_all)
	var position = _gml_motion_position(instance)
	var hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
	var vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)
	var free_h = _gml_motion_contact_free(instance, position.x + hspeed_value, position.y, use_all)
	var free_v = _gml_motion_contact_free(instance, position.x, position.y + vspeed_value, use_all)
	var free_both = _gml_motion_contact_free(instance, position.x + hspeed_value, position.y + vspeed_value, use_all)
	if (not free_h and not free_v) or (free_h and free_v and not free_both):
		_gml_motion_assign_hspeed(instance, -_gml_motion_real(instance, "hspeed", 0.0))
		_gml_motion_assign_vspeed(instance, -_gml_motion_real(instance, "vspeed", 0.0))
	elif not free_h:
		_gml_motion_assign_hspeed(instance, -_gml_motion_real(instance, "hspeed", 0.0))
	elif not free_v:
		_gml_motion_assign_vspeed(instance, -_gml_motion_real(instance, "vspeed", 0.0))


static func _gml_motion_bounce_advanced(instance, use_all):
	# Searches 10 degree steps to both sides of the current direction for
	# the first free direction and mirrors the motion between the two.
	var did_bounce = _gml_motion_bounce_restore(instance, use_all)
	var position = _gml_motion_position(instance)
	var speed_value = _gml_motion_real(instance, "speed", 0.0)
	var direction_value = 10.0 * floor(_gml_motion_real(instance, "direction", 0.0) / 10.0 + 0.5)
	var left_direction = direction_value
	var right_direction = direction_value
	for _step in range(GML_MOTION_BOUNCE_ANGLES):
		left_direction -= 10.0
		if _gml_motion_bounce_direction_free(instance, position, speed_value, left_direction, use_all):
			break
		did_bounce = true
	for _step in range(GML_MOTION_BOUNCE_ANGLES):
		right_direction += 10.0
		if _gml_motion_bounce_direction_free(instance, position, speed_value, right_direction, use_all):
			break
		did_bounce = true
	if did_bounce:
		_gml_motion_assign_direction(instance, 180.0 + left_direction + right_direction - direction_value)


static func _gml_motion_bounce_direction_free(instance, position, speed_value, direction, use_all):
	var radians = direction * PI / 180.0
	return _gml_motion_contact_free(
		instance,
		position.x + speed_value * cos(radians),
		position.y - speed_value * sin(radians),
		use_all
	)


static func _gml_motion_random_instance(instance, hsnap, vsnap):
	var xmin = 0.0
	var xmax = _gml_builtin_global_real("room_width", 0.0)
	var ymin = 0.0
	var ymax = _gml_builtin_global_real("room_height", 0.0)
	var position = _gml_motion_position(instance)
	var bbox = _gml_collision_instance_bbox(instance)
	if bbox != null:
		xmin = _gml_collision_round(position.x - bbox["left"])
		xmax = _gml_collision_round(xmax + position.x - bbox["right"])
		ymin = _gml_collision_round(position.y - bbox["top"])
		ymax = _gml_collision_round(ymax + position.y - bbox["bottom"])
	for _attempt in range(GML_MOTION_RANDOM_ATTEMPTS):
		var x = xmin + _to_real(gml_random(xmax - xmin))
		if hsnap > 0.0:
			x = hsnap * floor(x / hsnap)
		var y = ymin + _to_real(gml_random(ymax - ymin))
		if vsnap > 0.0:
			y = vsnap * floor(y / vsnap)
		if gml_place_free(instance, x, y):
			_gml_motion_set_position(instance, Vector2(x, y))
			return


# --- Keeping speed/direction and hspeed/vspeed in step ---------------------------

static func _gml_motion_is_synced_field(member_name):
	return GML_MOTION_SYNCED_FIELDS.has(str(member_name))


static func _gml_motion_assign_field(instance, member_name, value):
	match str(member_name):
		"direction":
			_gml_motion_assign_direction(instance, value)
		"speed":
			_gml_motion_assign_speed(instance, value)
		"hspeed":
			_gml_motion_assign_hspeed(instance, value)
		"vspeed":
			_gml_motion_assign_vspeed(instance, value)
	return value


static func _gml_motion_assign_hspeed(instance, value):
	var hspeed_value = _to_real(value)
	if hspeed_value == _gml_motion_real(instance, "hspeed", 0.0):
		return
	_gml_motion_write(instance, "hspeed", hspeed_value)
	_gml_motion_compute_polar(instance)


static func _gml_motion_assign_vspeed(instance, value):
	var vspeed_value = _to_real(value)
	if vspeed_value == _gml_motion_real(instance, "vspeed", 0.0):
		return
	_gml_motion_write(instance, "vspeed", vspeed_value)
	_gml_motion_compute_polar(instance)


static func _gml_motion_assign_speed(instance, value):
	var speed_value = _to_real(value)
	if _gml_motion_declares_members(instance):
		var current_speed = instance.speed
		if typeof(current_speed) != TYPE_FLOAT:
			current_speed = _gml_motion_real(instance, "speed", 0.0)
		if speed_value == current_speed:
			return
		instance.speed = speed_value
		_gml_motion_compute_components(instance)
		return
	if speed_value == _gml_motion_real(instance, "speed", 0.0):
		return
	_gml_motion_write(instance, "speed", speed_value)
	_gml_motion_compute_components(instance)


static func _gml_motion_assign_direction(instance, value):
	var direction_value = _gml_motion_wrap_direction(_to_real(value))
	if _gml_motion_declares_members(instance):
		instance.direction = direction_value
	else:
		_gml_motion_write(instance, "direction", direction_value)
	_gml_motion_compute_components(instance)


static func _gml_motion_add_to_speed(instance, direction, amount):
	var radians = direction * GML_MOTION_DEGREES_TO_RADIANS
	_gml_motion_assign_hspeed(instance, _gml_motion_real(instance, "hspeed", 0.0) + amount * _gml_motion_clamp_float(cos(radians)))
	_gml_motion_assign_vspeed(instance, _gml_motion_real(instance, "vspeed", 0.0) - amount * _gml_motion_clamp_float(sin(radians)))
	_gml_motion_compute_polar(instance)


static func _gml_motion_compute_components(instance):
	if _gml_motion_declares_members(instance):
		# The members below hold reals unless GML code stored something else
		# in them; anything else is read the general way.
		var member_speed = instance.speed
		if typeof(member_speed) != TYPE_FLOAT:
			member_speed = _gml_motion_real(instance, "speed", 0.0)
		var member_direction = instance.direction
		if typeof(member_direction) != TYPE_FLOAT:
			member_direction = _gml_motion_real(instance, "direction", 0.0)
		var member_radians: float = member_direction * GML_MOTION_DEGREES_TO_RADIANS
		# _gml_motion_snap_whole(speed * _gml_motion_clamp_float(cos)) and the
		# same with -sin, written out.
		var cosine: float = cos(member_radians)
		cosine = float(int(cosine * 1000000.0)) / 1000000.0 if is_finite(cosine) else 0.0
		var sine: float = sin(member_radians)
		sine = float(int(sine * 1000000.0)) / 1000000.0 if is_finite(sine) else 0.0
		var horizontal: float = member_speed * cosine
		var vertical: float = -member_speed * sine
		var whole: float = floor(horizontal)
		var fraction: float = horizontal - whole
		if fraction > 0.5 or (fraction == 0.5 and fmod(whole, 2.0) != 0.0):
			whole += 1.0
		if absf(horizontal - whole) < GML_MOTION_WHOLE_SNAP:
			horizontal = whole
		whole = floor(vertical)
		fraction = vertical - whole
		if fraction > 0.5 or (fraction == 0.5 and fmod(whole, 2.0) != 0.0):
			whole += 1.0
		if absf(vertical - whole) < GML_MOTION_WHOLE_SNAP:
			vertical = whole
		instance.hspeed = horizontal
		instance.vspeed = vertical
		return
	var speed_value = _gml_motion_real(instance, "speed", 0.0)
	var radians = _gml_motion_real(instance, "direction", 0.0) * GML_MOTION_DEGREES_TO_RADIANS
	_gml_motion_write(instance, "hspeed", _gml_motion_snap_whole(speed_value * _gml_motion_clamp_float(cos(radians))))
	_gml_motion_write(instance, "vspeed", _gml_motion_snap_whole(-speed_value * _gml_motion_clamp_float(sin(radians))))


static func _gml_motion_declares_members(instance):
	if typeof(instance) != TYPE_OBJECT:
		return false
	var script = instance.get_script()
	if script == null:
		return false
	var declared = _gml_motion_member_scripts.get(script)
	if declared == null:
		declared = (
			"direction" in instance and "speed" in instance and "hspeed" in instance and "vspeed" in instance
			and "friction" in instance and "gravity" in instance
		)
		_gml_motion_member_scripts[script] = declared
	return declared


static func _gml_motion_compute_polar(instance):
	var hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
	var vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)
	var direction_value = _gml_motion_real(instance, "direction", 0.0)
	if hspeed_value == 0.0:
		# Straight up or down; a standstill keeps the old direction.
		if vspeed_value > 0.0:
			direction_value = 270.0
		elif vspeed_value < 0.0:
			direction_value = 90.0
	else:
		var degrees = _gml_motion_clamp_float(180.0 * atan2(vspeed_value, hspeed_value) / PI)
		direction_value = -degrees if degrees <= 0.0 else 360.0 - degrees
	_gml_motion_write(instance, "direction", fmod(_gml_motion_snap_whole(direction_value), 360.0))
	_gml_motion_write(instance, "speed", _gml_motion_snap_whole(sqrt(hspeed_value * hspeed_value + vspeed_value * vspeed_value)))


static func _gml_motion_clamp_float(value):
	# Truncates to six decimals.
	if not is_finite(value):
		return 0.0
	return float(int(value * 1000000.0)) / 1000000.0


static func _gml_motion_snap_whole(value):
	var whole = _gml_collision_round(value)
	if abs(value - whole) < GML_MOTION_WHOLE_SNAP:
		return whole
	return value


static func _gml_motion_wrap_direction(value):
	if not is_finite(value):
		return value
	var direction = value
	if direction < 0.0:
		direction = fmod(direction, 360.0) + 360.0
	return fmod(direction, 360.0)


static func _gml_motion_vector_from_polar(direction, speed):
	var radians = deg_to_rad(_to_real(direction))
	var speed_value = _to_real(speed)
	return Vector2(cos(radians) * speed_value, -sin(radians) * speed_value)


static func _gml_motion_direction_from_vector(hspeed_value, vspeed_value, fallback_direction):
	if abs(hspeed_value) <= 0.000001 and abs(vspeed_value) <= 0.000001:
		return _gml_motion_wrap_direction(_to_real(fallback_direction))
	return fposmod(rad_to_deg(atan2(-vspeed_value, hspeed_value)), 360.0)


static func _gml_motion_point_direction(start, finish):
	return _gml_motion_direction_from_vector(finish.x - start.x, finish.y - start.y, 0.0)


static func _gml_motion_position(instance):
	if instance is Node2D:
		return _gml_collision_instance_xy(instance)
	return _gml_instance_position(instance)


static func _gml_motion_set_position(instance, position):
	if instance is Node2D:
		_gml_collision_set_instance_xy(instance, position)
		return
	if instance is Object:
		gml_struct_set(instance, "x", position.x)
		gml_struct_set(instance, "y", position.y)


static func _gml_motion_read(instance, member_name, default_value):
	var key = str(member_name)
	var value = null
	if instance is Object:
		value = instance.get(key)
		if value == null:
			value = _gml_object_dynamic_fields(instance).get(key, null)
	elif typeof(instance) == TYPE_DICTIONARY:
		value = instance.get(key, null)
	if value == null or is_undefined(value):
		return default_value
	return value


static func _gml_motion_real(instance, member_name, default_value):
	return _to_real(_gml_motion_read(instance, member_name, default_value))


static func _gml_motion_write(instance, member_name, value):
	if typeof(instance) == TYPE_DICTIONARY:
		instance[str(member_name)] = value
		return value
	if instance is Object:
		var key = str(member_name)
		if key in instance:
			instance.set(key, value)
		else:
			_gml_object_dynamic_fields(instance, true)[key] = value
		return value
	return value


static func _gml_builtin_global_real(member_name, default_value):
	var value = gml_builtin_global(member_name)
	if is_undefined(value):
		return default_value
	return _to_real(value)
