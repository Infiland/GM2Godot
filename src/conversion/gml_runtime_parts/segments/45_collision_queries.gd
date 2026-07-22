static var _gml_collision_event_trace = []


static func gml_distance_to_object(current_self, target):
	if current_self == null:
		return -1
	var origin = _gml_instance_position(current_self)
	var best_distance = -1.0
	for instance in gml_with_targets(target, current_self, null):
		if instance == null or not is_instance_valid(instance):
			continue
		var distance = origin.distance_to(_gml_instance_position(instance))
		if best_distance < 0.0 or distance < best_distance:
			best_distance = distance
	return best_distance


static func gml_place_meeting(current_self, x, y, target):
	return gml_handle_is_valid(gml_instance_place(current_self, x, y, target))


static func gml_position_meeting(current_self, x, y, target):
	return gml_handle_is_valid(gml_instance_position(current_self, x, y, target))


static func gml_instance_place(current_self, x, y, target):
	if current_self == null:
		return gml_instance_noone()
	var subject_polygons = _gml_collision_polygons_for_instance(current_self, true)
	if subject_polygons.is_empty():
		return gml_instance_noone()
	var target_position = Vector2(_to_real(x), _to_real(y))
	var delta = target_position - _gml_instance_position(current_self)
	return _gml_collision_first_polygon_hit(
		_gml_collision_translate_polygons(subject_polygons, delta),
		target,
		current_self,
		true,
		true
	)


static func gml_instance_position(current_self, x, y, target):
	return _gml_collision_first_point_hit(
		Vector2(_to_real(x), _to_real(y)),
		target,
		current_self,
		false,
		true
	)


static func gml_collision_point(current_self, x, y, target, precise = false, notme = false):
	return _gml_collision_first_point_hit(
		Vector2(_to_real(x), _to_real(y)),
		target,
		current_self,
		gml_bool(notme),
		gml_bool(precise)
	)


static func gml_collision_rectangle(current_self, x1, y1, x2, y2, target, precise = false, notme = false):
	var query_rect = _gml_collision_rect_from_bounds(x1, y1, x2, y2)
	return _gml_collision_first_polygon_hit(
		[_gml_collision_polygon_from_rect(query_rect)],
		target,
		current_self,
		gml_bool(notme),
		gml_bool(precise)
	)


static func gml_collision_line(current_self, x1, y1, x2, y2, target, precise = false, notme = false):
	return _gml_collision_first_line_hit(
		Vector2(_to_real(x1), _to_real(y1)),
		Vector2(_to_real(x2), _to_real(y2)),
		target,
		current_self,
		gml_bool(notme),
		gml_bool(precise)
	)


static func gml_collision_circle(current_self, x, y, radius, target, precise = false, notme = false):
	return _gml_collision_first_circle_hit(
		Vector2(_to_real(x), _to_real(y)),
		abs(_to_real(radius)),
		target,
		current_self,
		gml_bool(notme),
		gml_bool(precise)
	)


static func gml_collision_point_list(current_self, x, y, target, precise, notme, list_id, ordered):
	var point = Vector2(_to_real(x), _to_real(y))
	var hits = _gml_collision_collect_point_hits(
		point,
		target,
		current_self,
		gml_bool(notme),
		point,
		gml_bool(precise)
	)
	return _gml_collision_append_hits_to_list(list_id, hits, ordered)


static func gml_collision_rectangle_list(current_self, x1, y1, x2, y2, target, precise, notme, list_id, ordered):
	var query_rect = _gml_collision_rect_from_bounds(x1, y1, x2, y2)
	var origin = query_rect.position + query_rect.size * 0.5
	var hits = _gml_collision_collect_polygon_hits(
		[_gml_collision_polygon_from_rect(query_rect)],
		target,
		current_self,
		gml_bool(notme),
		origin,
		gml_bool(precise)
	)
	return _gml_collision_append_hits_to_list(list_id, hits, ordered)


static func gml_collision_line_list(current_self, x1, y1, x2, y2, target, precise, notme, list_id, ordered):
	var start = Vector2(_to_real(x1), _to_real(y1))
	var finish = Vector2(_to_real(x2), _to_real(y2))
	var hits = _gml_collision_collect_line_hits(
		start,
		finish,
		target,
		current_self,
		gml_bool(notme),
		start,
		gml_bool(precise)
	)
	return _gml_collision_append_hits_to_list(list_id, hits, ordered)


static func gml_collision_circle_list(current_self, x, y, radius, target, precise, notme, list_id, ordered):
	var center = Vector2(_to_real(x), _to_real(y))
	var hits = _gml_collision_collect_circle_hits(
		center,
		abs(_to_real(radius)),
		target,
		current_self,
		gml_bool(notme),
		center,
		gml_bool(precise)
	)
	return _gml_collision_append_hits_to_list(list_id, hits, ordered)


static func gml_collision_event_trace():
	return _gml_clone_value(_gml_collision_event_trace, 16)


static func gml_collision_event_trace_clear():
	_gml_collision_event_trace = []
	return null


static func gml_collision_event_dispatch_frame(instances = null, frame = -1):
	var targets = instances if instances is Array else _gml_collision_live_instances()
	_gml_event_scheduler_record_phase("collision", "", null, frame)
	var dispatched = 0
	for inst in targets:
		if not _gml_collision_instance_valid(inst):
			continue
		if not inst.has_method("_gm_collision_event_bindings"):
			continue
		var bindings = inst._gm_collision_event_bindings()
		if not (bindings is Array):
			continue
		for binding in bindings:
			if not (binding is Dictionary):
				continue
			for other_inst in targets:
				if not _gml_collision_instance_valid(inst):
					break
				if not _gml_collision_instance_valid(other_inst):
					continue
				if _gml_collision_same_instance(inst, other_inst):
					continue
				if not _gml_collision_binding_target_matches(other_inst, binding):
					continue
				if not _gml_collision_pair_intersects(inst, other_inst):
					continue
				_gml_collision_restore_solid_contact(inst, other_inst)
				dispatched += _gml_collision_dispatch_binding(inst, other_inst, binding, frame)
	return dispatched


static func _gml_collision_live_instances():
	var instances = []
	for entry in _gml_live_instance_entries():
		var inst = entry["instance"]
		if _gml_collision_instance_valid(inst):
			instances.append(inst)
	return instances


static func _gml_collision_instance_valid(inst):
	return inst != null and is_instance_valid(inst)


static func _gml_collision_binding_target_matches(other_inst, binding):
	var target_object = str(binding.get("target_object", ""))
	if target_object == "":
		return true
	var entry: Variant = _gml_instance_entry(other_inst)
	if entry == null:
		return false
	if str(entry.get("object_name", "")) == target_object:
		return true
	for selector_name in entry.get("selector_names", []):
		if str(selector_name) == target_object:
			return true
	return false


static func _gml_collision_pair_intersects(left, right):
	var left_polygons = _gml_collision_polygons_for_instance(left, true)
	if left_polygons.is_empty():
		return false
	var right_polygons = _gml_collision_polygons_for_instance(right, true)
	if right_polygons.is_empty():
		return false
	for left_polygon in left_polygons:
		for right_polygon in right_polygons:
			if _gml_collision_polygons_intersect(left_polygon, right_polygon):
				return true
	return false


static func _gml_collision_restore_solid_contact(inst, other_inst):
	if not _gml_collision_instance_solid(other_inst):
		return null
	if not (inst is Node2D):
		return null
	var previous = Vector2(
		_gml_motion_real(inst, "xprevious", inst.global_position.x),
		_gml_motion_real(inst, "yprevious", inst.global_position.y)
	)
	if previous == inst.global_position:
		return null
	_gml_motion_set_position(inst, previous)
	_gml_collision_event_trace.append({
		"event": "solid_rollback",
		"instance": str(inst.name) if inst is Node else "",
		"other": str(other_inst.name) if other_inst is Node else "",
		"x": previous.x,
		"y": previous.y,
	})
	return null


static func _gml_collision_instance_solid(inst):
	var value = gml_struct_get(inst, "solid")
	if is_undefined(value):
		return false
	return gml_bool(value)


static func _gml_collision_dispatch_binding(inst, other_inst, binding, frame):
	var method_name = str(binding.get("method", ""))
	if method_name == "" or not inst.has_method(method_name):
		return 0
	var previous_other = gml_struct_get(inst, "other")
	gml_struct_set(inst, "other", other_inst)
	_gml_collision_event_trace.append({
		"event": "collision",
		"frame": frame,
		"instance": str(inst.name) if inst is Node else "",
		"other": str(other_inst.name) if other_inst is Node else "",
		"method": method_name,
		"target_object": str(binding.get("target_object", "")),
	})
	_gml_event_scheduler_record_phase("collision", method_name, inst, frame)
	inst.call(method_name)
	if _gml_collision_instance_valid(inst):
		gml_struct_set(inst, "other", previous_other)
	return 1


static func _gml_collision_first_point_hit(point, target, current_self, notme, target_precise):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for polygon in _gml_collision_polygons_for_instance(instance, target_precise):
			if _gml_collision_polygon_has_point(polygon, point):
				return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_first_polygon_hit(query_polygons, target, current_self, notme, target_precise):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		var target_polygons = _gml_collision_polygons_for_instance(instance, target_precise)
		for query_polygon in query_polygons:
			for target_polygon in target_polygons:
				if _gml_collision_polygons_intersect(query_polygon, target_polygon):
					return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_first_line_hit(start, finish, target, current_self, notme, target_precise):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for polygon in _gml_collision_polygons_for_instance(instance, target_precise):
			if _gml_collision_line_intersects_polygon(start, finish, polygon):
				return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_first_circle_hit(center, radius, target, current_self, notme, target_precise):
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for polygon in _gml_collision_polygons_for_instance(instance, target_precise):
			if _gml_collision_circle_intersects_polygon(center, radius, polygon):
				return _gml_collision_handle_for_instance(instance)
	return gml_instance_noone()


static func _gml_collision_collect_point_hits(point, target, current_self, notme, order_origin, target_precise):
	var hits = []
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for polygon in _gml_collision_polygons_for_instance(instance, target_precise):
			if _gml_collision_polygon_has_point(polygon, point):
				hits.append(_gml_collision_hit_record(instance, order_origin))
				break
	return hits


static func _gml_collision_collect_polygon_hits(query_polygons, target, current_self, notme, order_origin, target_precise):
	var hits = []
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		var target_polygons = _gml_collision_polygons_for_instance(instance, target_precise)
		var hit = false
		for query_polygon in query_polygons:
			for target_polygon in target_polygons:
				if _gml_collision_polygons_intersect(query_polygon, target_polygon):
					hit = true
					break
			if hit:
				break
		if hit:
			hits.append(_gml_collision_hit_record(instance, order_origin))
	return hits


static func _gml_collision_collect_line_hits(start, finish, target, current_self, notme, order_origin, target_precise):
	var hits = []
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for polygon in _gml_collision_polygons_for_instance(instance, target_precise):
			if _gml_collision_line_intersects_polygon(start, finish, polygon):
				hits.append(_gml_collision_hit_record(instance, order_origin))
				break
	return hits


static func _gml_collision_collect_circle_hits(center, radius, target, current_self, notme, order_origin, target_precise):
	var hits = []
	for instance in _gml_collision_candidate_instances(target, current_self, notme):
		for polygon in _gml_collision_polygons_for_instance(instance, target_precise):
			if _gml_collision_circle_intersects_polygon(center, radius, polygon):
				hits.append(_gml_collision_hit_record(instance, order_origin))
				break
	return hits


static func _gml_collision_hit_record(instance, order_origin):
	return {
		"handle": _gml_collision_handle_for_instance(instance),
		"distance": order_origin.distance_squared_to(_gml_instance_position(instance))
	}


static func _gml_collision_append_hits_to_list(list_id, hits, ordered):
	var ds = _gml_resolve_ds_list(list_id)
	if not (ds is Dictionary):
		return 0
	if gml_bool(ordered):
		hits.sort_custom(_gml_collision_hit_distance_less)
	for hit in hits:
		ds["data"].append(hit["handle"])
	return hits.size()


static func _gml_collision_hit_distance_less(left, right):
	return float(left["distance"]) < float(right["distance"])


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
	for polygon in _gml_collision_polygons_for_instance(instance, true):
		var rect = _gml_collision_polygon_bounds(polygon)
		if rect != null:
			rects.append(rect)
	return rects


static func _gml_collision_polygons_for_instance(instance, use_precise = true):
	var polygons = []
	if not (instance is Node):
		return polygons
	_gml_collision_collect_shape_polygons(instance, polygons, gml_bool(use_precise))
	return polygons


static func _gml_collision_collect_shape_polygons(node, polygons, use_precise):
	if node is CollisionShape2D:
		var is_precise = node.has_meta("gamemaker_precise_mask")
		var is_bounds = node.has_meta("gamemaker_collision_bounds")
		var include_shape = false
		var preserve_rotation = false
		if is_bounds:
			include_shape = not use_precise
		elif is_precise:
			var active_mask = not node.disabled
			if node.has_meta("gamemaker_mask_frame"):
				var mask_root = node.get_parent()
				var active_frame = 0
				if mask_root != null:
					active_frame = int(mask_root.get_meta("gamemaker_active_mask_frame", 0))
				active_mask = int(node.get_meta("gamemaker_mask_frame")) == active_frame
			include_shape = use_precise and active_mask
			preserve_rotation = include_shape
		elif not node.disabled:
			include_shape = true
		if include_shape:
			var polygon = _gml_collision_polygon_for_shape_node(node, preserve_rotation)
			if not polygon.is_empty():
				polygons.append(polygon)
	for child in node.get_children():
		if child is Node:
			_gml_collision_collect_shape_polygons(child, polygons, use_precise)


static func _gml_collision_rect_for_shape_node(shape_node):
	var polygon = _gml_collision_polygon_for_shape_node(shape_node, false)
	return _gml_collision_polygon_bounds(polygon)


static func _gml_collision_polygon_for_shape_node(shape_node, preserve_rotation):
	if shape_node.shape == null:
		return PackedVector2Array()
	if abs(shape_node.global_transform.determinant()) <= 0.000001:
		return PackedVector2Array()
	var local_points = _gml_collision_local_points_for_shape(shape_node.shape)
	if local_points.is_empty():
		return PackedVector2Array()
	var polygon = PackedVector2Array()
	for point in local_points:
		polygon.append(shape_node.global_transform * point)
	if preserve_rotation:
		return polygon
	var bounds = _gml_collision_polygon_bounds(polygon)
	if bounds == null:
		return PackedVector2Array()
	return _gml_collision_polygon_from_rect(bounds)


static func _gml_collision_local_points_for_shape(shape):
	if shape == null:
		return PackedVector2Array()
	if shape is RectangleShape2D:
		var half_size = shape.size * 0.5
		return PackedVector2Array([
			Vector2(-half_size.x, -half_size.y),
			Vector2(half_size.x, -half_size.y),
			Vector2(half_size.x, half_size.y),
			Vector2(-half_size.x, half_size.y)
		])
	if shape is CircleShape2D:
		var radius = shape.radius
		return PackedVector2Array([
			Vector2(-radius, -radius),
			Vector2(radius, -radius),
			Vector2(radius, radius),
			Vector2(-radius, radius)
		])
	if shape is CapsuleShape2D:
		var half_width = shape.radius
		var half_height = shape.height * 0.5
		return PackedVector2Array([
			Vector2(-half_width, -half_height),
			Vector2(half_width, -half_height),
			Vector2(half_width, half_height),
			Vector2(-half_width, half_height)
		])
	if shape is ConvexPolygonShape2D:
		return shape.points
	return PackedVector2Array()


static func _gml_collision_polygon_bounds(polygon):
	if polygon == null or polygon.is_empty():
		return null
	var min_x = INF
	var min_y = INF
	var max_x = -INF
	var max_y = -INF
	for point in polygon:
		min_x = min(min_x, point.x)
		min_y = min(min_y, point.y)
		max_x = max(max_x, point.x)
		max_y = max(max_y, point.y)
	return Rect2(Vector2(min_x, min_y), Vector2(max_x - min_x, max_y - min_y))


static func _gml_collision_polygon_from_rect(rect):
	return PackedVector2Array([
		rect.position,
		rect.position + Vector2(rect.size.x, 0),
		rect.position + rect.size,
		rect.position + Vector2(0, rect.size.y)
	])


static func _gml_collision_translate_rects(rects, delta):
	var translated = []
	for rect in rects:
		translated.append(Rect2(rect.position + delta, rect.size))
	return translated


static func _gml_collision_translate_polygons(polygons, delta):
	var translated = []
	for polygon in polygons:
		var moved = PackedVector2Array()
		for point in polygon:
			moved.append(point + delta)
		translated.append(moved)
	return translated


static func _gml_collision_polygons_intersect(left, right):
	if left.size() < 3 or right.size() < 3:
		return false
	var left_bounds = _gml_collision_polygon_bounds(left)
	var right_bounds = _gml_collision_polygon_bounds(right)
	if left_bounds == null or right_bounds == null:
		return false
	if not left_bounds.intersects(right_bounds, true):
		return false
	return (
		not _gml_collision_polygon_has_separating_axis(left, left, right)
		and not _gml_collision_polygon_has_separating_axis(right, left, right)
	)


static func _gml_collision_polygon_has_separating_axis(axis_polygon, left, right):
	for index in range(axis_polygon.size()):
		var start = axis_polygon[index]
		var finish = axis_polygon[(index + 1) % axis_polygon.size()]
		var edge = finish - start
		if edge.length_squared() <= 0.000000000001:
			continue
		var axis = Vector2(-edge.y, edge.x)
		var left_min = INF
		var left_max = -INF
		for point in left:
			var projection = point.dot(axis)
			left_min = min(left_min, projection)
			left_max = max(left_max, projection)
		var right_min = INF
		var right_max = -INF
		for point in right:
			var projection = point.dot(axis)
			right_min = min(right_min, projection)
			right_max = max(right_max, projection)
		if left_max < right_min - 0.000001 or right_max < left_min - 0.000001:
			return true
	return false


static func _gml_collision_polygon_has_point(polygon, point):
	if polygon.size() < 3:
		return false
	var winding_sign = 0
	for index in range(polygon.size()):
		var start = polygon[index]
		var finish = polygon[(index + 1) % polygon.size()]
		var cross = (finish - start).cross(point - start)
		if abs(cross) <= 0.000001:
			continue
		var edge_sign = 1 if cross > 0.0 else -1
		if winding_sign != 0 and edge_sign != winding_sign:
			return false
		winding_sign = edge_sign
	return winding_sign != 0


static func _gml_collision_line_intersects_polygon(start, finish, polygon):
	if (
		_gml_collision_polygon_has_point(polygon, start)
		or _gml_collision_polygon_has_point(polygon, finish)
	):
		return true
	for index in range(polygon.size()):
		if _gml_collision_segments_intersect(
			start,
			finish,
			polygon[index],
			polygon[(index + 1) % polygon.size()]
		):
			return true
	return false


static func _gml_collision_circle_intersects_polygon(center, radius, polygon):
	if _gml_collision_polygon_has_point(polygon, center):
		return true
	var radius_squared = radius * radius
	for index in range(polygon.size()):
		if _gml_collision_point_segment_distance_squared(
			center,
			polygon[index],
			polygon[(index + 1) % polygon.size()]
		) <= radius_squared:
			return true
	return false


static func _gml_collision_point_segment_distance_squared(point, start, finish):
	var segment = finish - start
	var length_squared = segment.length_squared()
	if length_squared <= 0.000000000001:
		return point.distance_squared_to(start)
	var amount = clamp((point - start).dot(segment) / length_squared, 0.0, 1.0)
	return point.distance_squared_to(start + segment * amount)


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
