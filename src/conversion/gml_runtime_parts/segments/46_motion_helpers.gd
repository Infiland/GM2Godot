static func gml_motion_set(current_self, direction, speed):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_set_polar(instance, direction, speed)
	return null


static func gml_motion_add(current_self, direction, speed):
	for instance in _gml_motion_instances(current_self):
		var current = Vector2(
			_gml_motion_real(instance, "hspeed", 0.0),
			_gml_motion_real(instance, "vspeed", 0.0)
		)
		var added = _gml_motion_vector_from_polar(direction, speed)
		_gml_motion_set_components(instance, current.x + added.x, current.y + added.y)
	return null


static func gml_motion_set_speed(target, value):
	var result = _to_real(value)
	for instance in _gml_motion_instances(target):
		_gml_motion_set_polar(instance, _gml_motion_real(instance, "direction", 0.0), result)
	return result


static func gml_motion_set_direction(target, value):
	var result = _gml_motion_normalize_direction(value)
	for instance in _gml_motion_instances(target):
		_gml_motion_set_polar(instance, result, _gml_motion_real(instance, "speed", 0.0))
	return result


static func gml_motion_set_hspeed(target, value):
	var result = _to_real(value)
	for instance in _gml_motion_instances(target):
		_gml_motion_set_components(instance, result, _gml_motion_real(instance, "vspeed", 0.0))
	return result


static func gml_motion_set_vspeed(target, value):
	var result = _to_real(value)
	for instance in _gml_motion_instances(target):
		_gml_motion_set_components(instance, _gml_motion_real(instance, "hspeed", 0.0), result)
	return result


static func gml_motion_sync_from_speed_direction(target):
	for instance in _gml_motion_instances(target):
		_gml_motion_set_polar(
			instance,
			_gml_motion_real(instance, "direction", 0.0),
			_gml_motion_real(instance, "speed", 0.0)
		)
	return null


static func gml_motion_step(current_self):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_step_instance(instance)
	return null


static func gml_move_towards_point(current_self, x, y, speed):
	for instance in _gml_motion_instances(current_self):
		var direction = _gml_motion_point_direction(_gml_instance_position(instance), Vector2(_to_real(x), _to_real(y)))
		_gml_motion_set_polar(instance, direction, speed)
	return null


static func gml_move_contact_solid(current_self, direction, maxdist):
	return _gml_move_contact(current_self, direction, maxdist, true)


static func gml_move_contact_all(current_self, direction, maxdist):
	return _gml_move_contact(current_self, direction, maxdist, false)


static func gml_move_bounce_solid(current_self, advanced):
	return _gml_move_bounce(current_self, gml_bool(advanced), true)


static func gml_move_bounce_all(current_self, advanced):
	return _gml_move_bounce(current_self, gml_bool(advanced), false)


static func gml_move_random(current_self, hsnap, vsnap):
	var room_w = max(_gml_builtin_global_real("room_width", 0.0), 0.0)
	var room_h = max(_gml_builtin_global_real("room_height", 0.0), 0.0)
	for instance in _gml_motion_instances(current_self):
		var target = Vector2(randf_range(0.0, room_w), randf_range(0.0, room_h))
		_gml_motion_set_position(instance, _gml_motion_snap_position(target, hsnap, vsnap))
	return null


static func gml_move_snap(current_self, hsnap, vsnap):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_set_position(
			instance,
			_gml_motion_snap_position(_gml_instance_position(instance), hsnap, vsnap)
		)
	return null


static func gml_place_snapped(current_self, hsnap, vsnap):
	var instances = _gml_motion_instances(current_self)
	if instances.is_empty():
		return false
	var position = _gml_instance_position(instances[0])
	return position.distance_squared_to(_gml_motion_snap_position(position, hsnap, vsnap)) <= 0.000001


static func _gml_motion_instances(target):
	var instances = []
	for instance in gml_with_targets(target):
		if instance != null:
			instances.append(instance)
	return instances


static func _gml_motion_step_instance(instance):
	if not (instance is Node2D):
		return
	var previous = _gml_instance_position(instance)
	_gml_motion_write(instance, "xprevious", previous.x)
	_gml_motion_write(instance, "yprevious", previous.y)

	var hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
	var vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)
	var gravity_value = _gml_motion_real(instance, "gravity", 0.0)
	if abs(gravity_value) > 0.000001:
		var gravity_vector = _gml_motion_vector_from_polar(
			_gml_motion_real(instance, "gravity_direction", 270.0),
			gravity_value
		)
		hspeed_value += gravity_vector.x
		vspeed_value += gravity_vector.y
		_gml_motion_set_components(instance, hspeed_value, vspeed_value)

	var friction_value = abs(_gml_motion_real(instance, "friction", 0.0))
	var speed_value = _gml_motion_real(instance, "speed", 0.0)
	if friction_value > 0.000001 and abs(speed_value) > 0.000001:
		var next_speed = max(abs(speed_value) - friction_value, 0.0)
		_gml_motion_set_polar(instance, _gml_motion_real(instance, "direction", 0.0), next_speed)
		hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
		vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)

	_gml_motion_set_position(instance, previous + Vector2(hspeed_value, vspeed_value))


static func _gml_move_contact(current_self, direction, maxdist, solid_only):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_move_contact_instance(instance, direction, maxdist, solid_only)
	return null


static func _gml_motion_move_contact_instance(instance, direction, maxdist, solid_only):
	if not (instance is Node2D):
		return
	var distance = _to_real(maxdist)
	if distance < 0.0:
		distance = 1000.0
	var unit = _gml_motion_vector_from_polar(direction, 1.0)
	if unit.length_squared() <= 0.000001:
		return
	var remaining = distance
	while remaining > 0.000001:
		var step = min(1.0, remaining)
		var next_position = _gml_instance_position(instance) + unit * step
		if gml_handle_is_valid(_gml_motion_first_collision_at(instance, next_position, solid_only)):
			return
		_gml_motion_set_position(instance, next_position)
		remaining -= step


static func _gml_move_bounce(current_self, advanced, solid_only):
	for instance in _gml_motion_instances(current_self):
		_gml_motion_bounce_instance(instance, advanced, solid_only)
	return null


static func _gml_motion_bounce_instance(instance, advanced, solid_only):
	if not (instance is Node2D):
		return
	var hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
	var vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)
	if abs(hspeed_value) <= 0.000001 and abs(vspeed_value) <= 0.000001:
		return
	var current_position = _gml_instance_position(instance)
	var full_position = current_position + Vector2(hspeed_value, vspeed_value)
	if not gml_handle_is_valid(_gml_motion_first_collision_at(instance, full_position, solid_only)):
		return
	var horizontal_hit = (
		abs(hspeed_value) > 0.000001
		and gml_handle_is_valid(
			_gml_motion_first_collision_at(instance, current_position + Vector2(hspeed_value, 0.0), solid_only)
		)
	)
	var vertical_hit = (
		abs(vspeed_value) > 0.000001
		and gml_handle_is_valid(
			_gml_motion_first_collision_at(instance, current_position + Vector2(0.0, vspeed_value), solid_only)
		)
	)
	if horizontal_hit:
		hspeed_value = -hspeed_value
	if vertical_hit:
		vspeed_value = -vspeed_value
	if not horizontal_hit and not vertical_hit:
		hspeed_value = -hspeed_value
		vspeed_value = -vspeed_value
	_gml_motion_set_components(instance, hspeed_value, vspeed_value)


static func _gml_motion_first_collision_at(instance, position, solid_only):
	var subject_polygons = _gml_collision_polygons_for_instance(instance, true)
	if subject_polygons.is_empty():
		return gml_instance_noone()
	var delta = position - _gml_instance_position(instance)
	return _gml_motion_first_polygon_hit(
		_gml_collision_translate_polygons(subject_polygons, delta),
		instance,
		solid_only
	)


static func _gml_motion_first_polygon_hit(query_polygons, current_self, solid_only):
	for instance in gml_with_targets(gml_instance_all(), current_self, null):
		if _gml_collision_same_instance(instance, current_self):
			continue
		if solid_only and not gml_bool(_gml_motion_read(instance, "solid", false)):
			continue
		for query_polygon in query_polygons:
			for target_polygon in _gml_collision_polygons_for_instance(instance, true):
				if _gml_collision_polygons_intersect(query_polygon, target_polygon):
					return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_motion_set_polar(instance, direction, speed):
	var direction_value = _gml_motion_normalize_direction(direction)
	var speed_value = _to_real(speed)
	var vector = _gml_motion_vector_from_polar(direction_value, speed_value)
	_gml_motion_write(instance, "direction", direction_value)
	_gml_motion_write(instance, "speed", speed_value)
	_gml_motion_write(instance, "hspeed", vector.x)
	_gml_motion_write(instance, "vspeed", vector.y)


static func _gml_motion_set_components(instance, hspeed_value, vspeed_value):
	var h = _to_real(hspeed_value)
	var v = _to_real(vspeed_value)
	var previous_direction = _gml_motion_real(instance, "direction", 0.0)
	var speed_value = sqrt(h * h + v * v)
	var direction_value = _gml_motion_direction_from_vector(h, v, previous_direction)
	_gml_motion_write(instance, "hspeed", h)
	_gml_motion_write(instance, "vspeed", v)
	_gml_motion_write(instance, "speed", speed_value)
	_gml_motion_write(instance, "direction", direction_value)


static func _gml_motion_vector_from_polar(direction, speed):
	var radians = deg_to_rad(_to_real(direction))
	var speed_value = _to_real(speed)
	return Vector2(cos(radians) * speed_value, -sin(radians) * speed_value)


static func _gml_motion_direction_from_vector(hspeed_value, vspeed_value, fallback_direction):
	if abs(hspeed_value) <= 0.000001 and abs(vspeed_value) <= 0.000001:
		return _gml_motion_normalize_direction(fallback_direction)
	return fposmod(rad_to_deg(atan2(-vspeed_value, hspeed_value)), 360.0)


static func _gml_motion_point_direction(start, finish):
	return _gml_motion_direction_from_vector(finish.x - start.x, finish.y - start.y, 0.0)


static func _gml_motion_normalize_direction(direction):
	return fposmod(_to_real(direction), 360.0)


static func _gml_motion_snap_position(position, hsnap, vsnap):
	return Vector2(
		_gml_motion_snap_axis(position.x, hsnap),
		_gml_motion_snap_axis(position.y, vsnap)
	)


static func _gml_motion_snap_axis(value, snap):
	var snap_value = abs(_to_real(snap))
	if snap_value <= 0.000001:
		return value
	return round(value / snap_value) * snap_value


static func _gml_motion_set_position(instance, position):
	if instance is Node2D:
		instance.global_position = position
		return
	if instance is Object:
		gml_struct_set(instance, "x", position.x)
		gml_struct_set(instance, "y", position.y)


static func _gml_motion_read(instance, member_name, default_value):
	var value = gml_struct_get(instance, member_name)
	if is_undefined(value):
		return default_value
	return value


static func _gml_motion_real(instance, member_name, default_value):
	return _to_real(_gml_motion_read(instance, member_name, default_value))


static func _gml_motion_write(instance, member_name, value):
	if typeof(instance) == TYPE_DICTIONARY:
		instance[str(member_name)] = value
		return value
	if instance is Object:
		if _object_has_property(instance, str(member_name)):
			instance.set(str(member_name), value)
		return value
	return value


static func _gml_builtin_global_real(member_name, default_value):
	var value = gml_builtin_global(member_name)
	if is_undefined(value):
		return default_value
	return _to_real(value)
