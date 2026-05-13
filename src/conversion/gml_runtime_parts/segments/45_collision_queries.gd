static func gml_place_meeting(current_self, x, y, target):
	return gml_handle_is_valid(gml_instance_place(current_self, x, y, target))


static func gml_position_meeting(current_self, x, y, target):
	return gml_handle_is_valid(gml_instance_position(current_self, x, y, target))


static func gml_instance_place(current_self, x, y, target):
	if current_self == null:
		return gml_instance_noone()
	var subject_rects = _gml_collision_rects_for_instance(current_self)
	if subject_rects.is_empty():
		return gml_instance_noone()
	var target_position = Vector2(_to_real(x), _to_real(y))
	var delta = target_position - _gml_instance_position(current_self)
	return _gml_collision_first_rect_hit(
		_gml_collision_translate_rects(subject_rects, delta),
		target,
		current_self,
		true
	)


static func gml_instance_position(current_self, x, y, target):
	return _gml_collision_first_point_hit(Vector2(_to_real(x), _to_real(y)), target, current_self, false)


static func gml_collision_point(current_self, x, y, target, precise = false, notme = false):
	_gml_collision_warn_precise_approximation(precise)
	return _gml_collision_first_point_hit(
		Vector2(_to_real(x), _to_real(y)),
		target,
		current_self,
		gml_bool(notme)
	)


static func gml_collision_rectangle(current_self, x1, y1, x2, y2, target, precise = false, notme = false):
	_gml_collision_warn_precise_approximation(precise)
	var query_rect = _gml_collision_rect_from_bounds(x1, y1, x2, y2)
	return _gml_collision_first_rect_hit([query_rect], target, current_self, gml_bool(notme))


static func gml_collision_line(current_self, x1, y1, x2, y2, target, precise = false, notme = false):
	_gml_collision_warn_precise_approximation(precise)
	return _gml_collision_first_line_hit(
		Vector2(_to_real(x1), _to_real(y1)),
		Vector2(_to_real(x2), _to_real(y2)),
		target,
		current_self,
		gml_bool(notme)
	)


static func gml_collision_circle(current_self, x, y, radius, target, precise = false, notme = false):
	_gml_collision_warn_precise_approximation(precise)
	return _gml_collision_first_circle_hit(
		Vector2(_to_real(x), _to_real(y)),
		abs(_to_real(radius)),
		target,
		current_self,
		gml_bool(notme)
	)


static func _gml_collision_warn_precise_approximation(precise):
	if not gml_bool(precise):
		return
	if _gml_collision_precise_warning_emitted:
		return
	_gml_collision_precise_warning_emitted = true
	push_warning("GML precise collision masks are approximated with generated collision shape bounds")


static func _gml_collision_first_point_hit(point, target, current_self, notme):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for rect in _gml_collision_rects_for_instance(instance):
			if _gml_collision_rect_has_point(rect, point):
				return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_first_rect_hit(query_rects, target, current_self, notme):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		var target_rects = _gml_collision_rects_for_instance(instance)
		for query_rect in query_rects:
			for target_rect in target_rects:
				if query_rect.intersects(target_rect, true):
					return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_first_line_hit(start, finish, target, current_self, notme):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for rect in _gml_collision_rects_for_instance(instance):
			if _gml_collision_line_intersects_rect(start, finish, rect):
				return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_first_circle_hit(center, radius, target, current_self, notme):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for rect in _gml_collision_rects_for_instance(instance):
			if _gml_collision_circle_intersects_rect(center, radius, rect):
				return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_candidate_instances(target, current_self, notme):
	var candidates = []
	for instance in gml_with_targets(target, current_self, null):
		if notme and _gml_collision_same_instance(instance, current_self):
			continue
		candidates.append(instance)
	return candidates


static func _gml_collision_handle_for_instance(instance):
	var entry: Variant = _gml_instance_entry(instance)
	if entry == null:
		return gml_instance_noone()
	return entry["handle"]


static func _gml_collision_same_instance(left, right):
	if left == null or right == null:
		return false
	if left == right:
		return true
	var left_entry: Variant = _gml_instance_entry(left)
	var right_entry: Variant = _gml_instance_entry(right)
	if left_entry == null or right_entry == null:
		return false
	return left_entry["handle"].index == right_entry["handle"].index


static func _gml_collision_rects_for_instance(instance):
	var rects = []
	if not (instance is Node):
		return rects
	_gml_collision_collect_shape_rects(instance, rects)
	return rects


static func _gml_collision_collect_shape_rects(node, rects):
	if node is CollisionShape2D:
		var rect = _gml_collision_rect_for_shape_node(node)
		if rect != null:
			rects.append(rect)
	for child in node.get_children():
		if child is Node:
			_gml_collision_collect_shape_rects(child, rects)


static func _gml_collision_rect_for_shape_node(shape_node):
	if shape_node.disabled:
		return null
	var shape = shape_node.shape
	if shape == null:
		return null
	if shape is RectangleShape2D:
		var half_size = shape.size * 0.5
		return _gml_collision_rect_from_local_points(shape_node, [
			Vector2(-half_size.x, -half_size.y),
			Vector2(half_size.x, -half_size.y),
			Vector2(half_size.x, half_size.y),
			Vector2(-half_size.x, half_size.y)
		])
	if shape is CircleShape2D:
		var radius = shape.radius
		return _gml_collision_rect_from_local_points(shape_node, [
			Vector2(-radius, -radius),
			Vector2(radius, -radius),
			Vector2(radius, radius),
			Vector2(-radius, radius)
		])
	if shape is CapsuleShape2D:
		var half_width = shape.radius
		var half_height = shape.height * 0.5
		return _gml_collision_rect_from_local_points(shape_node, [
			Vector2(-half_width, -half_height),
			Vector2(half_width, -half_height),
			Vector2(half_width, half_height),
			Vector2(-half_width, half_height)
		])
	if shape is ConvexPolygonShape2D:
		return _gml_collision_rect_from_local_points(shape_node, shape.points)
	return null


static func _gml_collision_rect_from_local_points(node, points):
	if points.is_empty():
		return null
	var min_x = INF
	var min_y = INF
	var max_x = -INF
	var max_y = -INF
	for point in points:
		var global_point = node.global_transform * point
		min_x = min(min_x, global_point.x)
		min_y = min(min_y, global_point.y)
		max_x = max(max_x, global_point.x)
		max_y = max(max_y, global_point.y)
	return Rect2(Vector2(min_x, min_y), Vector2(max_x - min_x, max_y - min_y))


static func _gml_collision_translate_rects(rects, delta):
	var translated = []
	for rect in rects:
		translated.append(Rect2(rect.position + delta, rect.size))
	return translated


static func _gml_collision_rect_from_bounds(x1, y1, x2, y2):
	var left = min(_to_real(x1), _to_real(x2))
	var right = max(_to_real(x1), _to_real(x2))
	var top = min(_to_real(y1), _to_real(y2))
	var bottom = max(_to_real(y1), _to_real(y2))
	return Rect2(Vector2(left, top), Vector2(right - left, bottom - top))


static func _gml_collision_rect_has_point(rect, point):
	return (
		point.x >= rect.position.x
		and point.y >= rect.position.y
		and point.x <= rect.position.x + rect.size.x
		and point.y <= rect.position.y + rect.size.y
	)


static func _gml_collision_line_intersects_rect(start, finish, rect):
	if _gml_collision_rect_has_point(rect, start) or _gml_collision_rect_has_point(rect, finish):
		return true
	var top_left = rect.position
	var top_right = rect.position + Vector2(rect.size.x, 0)
	var bottom_right = rect.position + rect.size
	var bottom_left = rect.position + Vector2(0, rect.size.y)
	return (
		_gml_collision_segments_intersect(start, finish, top_left, top_right)
		or _gml_collision_segments_intersect(start, finish, top_right, bottom_right)
		or _gml_collision_segments_intersect(start, finish, bottom_right, bottom_left)
		or _gml_collision_segments_intersect(start, finish, bottom_left, top_left)
	)


static func _gml_collision_segments_intersect(a, b, c, d):
	var denominator = (b.x - a.x) * (d.y - c.y) - (b.y - a.y) * (d.x - c.x)
	if abs(denominator) < 0.000001:
		return (
			_gml_collision_point_on_segment(a, c, b)
			or _gml_collision_point_on_segment(a, d, b)
			or _gml_collision_point_on_segment(c, a, d)
			or _gml_collision_point_on_segment(c, b, d)
		)
	var t = ((c.x - a.x) * (d.y - c.y) - (c.y - a.y) * (d.x - c.x)) / denominator
	var u = ((c.x - a.x) * (b.y - a.y) - (c.y - a.y) * (b.x - a.x)) / denominator
	return t >= 0.0 and t <= 1.0 and u >= 0.0 and u <= 1.0


static func _gml_collision_point_on_segment(start, point, finish):
	var cross = (point.y - start.y) * (finish.x - start.x) - (point.x - start.x) * (finish.y - start.y)
	if abs(cross) > 0.000001:
		return false
	var dot = (point.x - start.x) * (finish.x - start.x) + (point.y - start.y) * (finish.y - start.y)
	if dot < 0.0:
		return false
	var length_squared = start.distance_squared_to(finish)
	return dot <= length_squared


static func _gml_collision_circle_intersects_rect(center, radius, rect):
	var nearest_x = clamp(center.x, rect.position.x, rect.position.x + rect.size.x)
	var nearest_y = clamp(center.y, rect.position.y, rect.position.y + rect.size.y)
	return center.distance_squared_to(Vector2(nearest_x, nearest_y)) <= radius * radius
