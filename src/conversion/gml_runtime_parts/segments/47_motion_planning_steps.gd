# --- move_and_collide, mp_linear_step, mp_potential_step and
# mp_grid_add_instances ---
#
# Like the HTML5 runner: move_and_collide in Function_Movement.js, and
# mp_linear_step_common, mp_potential_step_common (with TestFree, TryDir and
# DiffDir), mp_potential_settings and mp_grid_add_instances in
# Function_MotionPlanning.js. Positions are worked out in full precision and
# only the final one is stored.

const GML_MOVE_AND_COLLIDE_ITERATIONS = 4
const GML_MOVE_AND_COLLIDE_ROOT2OVER2 = 0.70710678118654

# mp_potential_settings, with GameMaker's defaults: how far the direction may
# turn in one step, the angle between the directions tried, how many steps
# ahead a direction must be free, and whether a stuck instance turns on the
# spot. Like the runner's, they apply to every instance.
static var _gml_mp_potential_maxrot = 30.0
static var _gml_mp_potential_rotstep = 10.0
static var _gml_mp_potential_ahead = 3.0
static var _gml_mp_potential_onspot = true


static func gml_move_and_collide(current_self, dx, dy, obj, num_iterations = GML_MOVE_AND_COLLIDE_ITERATIONS, xoff = null, yoff = null, max_x_move = null, max_y_move = null):
	# Moves the instance by (dx, dy) in num_iterations steps, going around
	# instances of obj, and returns the instances that blocked a step, each
	# once.
	var hits = []
	if not _gml_motion_is_instance(current_self) or _gml_move_and_collide_noone(obj):
		return hits
	var start = _gml_motion_position(current_self)
	var hit = _gml_move_and_collide_test(current_self, start.x, start.y, obj)
	if hit != null:
		hits.append(hit)
		return hits
	var move_x = _to_real(dx)
	var move_y = _to_real(dy)
	if move_x == 0.0 and move_y == 0.0:
		return hits
	var move = _gml_move_and_collide_context(current_self, obj, start, max_x_move, max_y_move, xoff, yoff, hits)
	var steps = _to_real(num_iterations)
	var length = sqrt(move_x * move_x + move_y * move_y)
	var ndx = move_x / length
	var ndy = move_y / length
	var step_dist = length / steps
	var dist_to_travel = length
	var i = 0
	while i < steps:
		var this_step = step_dist
		if dist_to_travel < this_step:
			this_step = dist_to_travel
			if this_step <= 0.0:
				break
		if _gml_move_and_collide_try(move, move["x"] + ndx * this_step, move["y"] + ndy * this_step):
			dist_to_travel -= this_step
		else:
			var sidestep = _gml_move_and_collide_sidestep(move, ndx, ndy, this_step, steps - i)
			if sidestep == 0:
				break
			dist_to_travel -= this_step * sidestep
		i += 1
	if move["x"] != float(start.x) or move["y"] != float(start.y):
		_gml_motion_set_position(current_self, Vector2(move["x"], move["y"]))
	return hits


static func _gml_move_and_collide_context(inst, obj, start, max_x_move, max_y_move, xoff, yoff, hits):
	var move = {
		"inst": inst,
		"obj": obj,
		"hits": hits,
		"x": float(start.x),
		"y": float(start.y),
		"limit_x": -1.0 if max_x_move == null else _to_real(max_x_move),
		"limit_y": -1.0 if max_y_move == null else _to_real(max_y_move),
		"start_x": float(start.x),
		"start_y": float(start.y),
		"perpendicular": true,
		"offset_x": 0.0,
		"offset_y": 0.0,
	}
	if xoff != null and yoff != null:
		var offset_x = _to_real(xoff)
		var offset_y = _to_real(yoff)
		if not (offset_x == 0.0 and offset_y == 0.0):
			var offset_length = sqrt(offset_x * offset_x + offset_y * offset_y)
			move["perpendicular"] = false
			move["offset_x"] = offset_x / offset_length
			move["offset_y"] = offset_y / offset_length
	return move


static func _gml_move_and_collide_sidestep(move, ndx, ndy, this_step, attempts):
	# After a blocked step, the runner tries steps turned 45 degrees and more
	# towards the perpendiculars (or towards xoff/yoff); returns how many step
	# lengths the move that worked counts for, or 0 when none did.
	var scale = GML_MOVE_AND_COLLIDE_ROOT2OVER2 * this_step
	var j = 1
	while j < attempts + 1:
		if move["perpendicular"]:
			if _gml_move_and_collide_try(move, move["x"] + scale * (ndx + j * ndy), move["y"] + scale * (ndy - j * ndx)):
				return j
			if _gml_move_and_collide_try(move, move["x"] + scale * (ndx - j * ndy), move["y"] + scale * (ndy + j * ndx)):
				return j
		elif _gml_move_and_collide_try(move, move["x"] + scale * (ndx + j * move["offset_x"]), move["y"] + scale * (ndy + j * move["offset_y"])):
			return j
		j += 1
	return 0


static func _gml_move_and_collide_try(move, x, y):
	# Moves to (x, y), held within max_x_move/max_y_move of the start, when
	# nothing blocks it there; otherwise records what blocks it.
	if move["limit_x"] >= 0.0:
		x = clamp(x, move["start_x"] - move["limit_x"], move["start_x"] + move["limit_x"])
	if move["limit_y"] >= 0.0:
		y = clamp(y, move["start_y"] - move["limit_y"], move["start_y"] + move["limit_y"])
	var hit = _gml_move_and_collide_test(move["inst"], x, y, move["obj"])
	if hit == null:
		move["x"] = x
		move["y"] = y
		return true
	if not move["hits"].has(hit):
		move["hits"].append(hit)
	return false


static func _gml_move_and_collide_test(inst, x, y, obj):
	# The runner's PerformColTest: the instance of obj the instance would
	# meet at (x, y), or null.
	var state = _gml_collision_state_at(inst, x, y)
	if state == null:
		return null
	var found = _gml_collision_find(GML_COLLISION_QUERY_INSTANCE, state, obj, inst, true, true, false)
	if found == null:
		return null
	return _gml_collision_handle_for_instance(found["inst"])


static func _gml_move_and_collide_noone(obj):
	if is_handle(obj):
		return obj.kind == GML_INSTANCE_HANDLE_KIND and obj.index == GML_INSTANCE_INVALID_INDEX
	return is_numeric(obj) and _to_real(obj) == GML_INSTANCE_INVALID_INDEX


static func gml_mp_linear_step(current_self, x, y, stepsize, checkall):
	return _gml_mp_linear_step(current_self, x, y, stepsize, null, gml_bool(checkall))


static func gml_mp_linear_step_object(current_self, x, y, stepsize, obj):
	return _gml_mp_linear_step(current_self, x, y, stepsize, obj, true)


static func _gml_mp_linear_step(inst, x, y, stepsize, obj, checkall):
	# One step straight towards (x, y), taken only when the new position is
	# free; returns whether it reaches the goal (or is there already).
	if not _gml_motion_is_instance(inst):
		return false
	var goal_x = _to_real(x)
	var goal_y = _to_real(y)
	var step = _to_real(stepsize)
	var position = _gml_motion_position(inst)
	var px = float(position.x)
	var py = float(position.y)
	if px == goal_x and py == goal_y:
		return true
	var distance = sqrt((px - goal_x) * (px - goal_x) + (py - goal_y) * (py - goal_y))
	var reached = distance <= step
	var new_x = goal_x if reached else px + step * (goal_x - px) / distance
	var new_y = goal_y if reached else py + step * (goal_y - py) / distance
	if not _gml_mp_free(inst, new_x, new_y, obj, checkall):
		return reached
	_gml_motion_assign_direction(inst, gml_point_direction(px, py, new_x, new_y))
	_gml_motion_set_position(inst, Vector2(new_x, new_y))
	return reached


static func gml_mp_potential_step(current_self, x, y, stepsize, checkall):
	return _gml_mp_potential_step(current_self, x, y, stepsize, null, gml_bool(checkall))


static func gml_mp_potential_step_object(current_self, x, y, stepsize, obj):
	return _gml_mp_potential_step(current_self, x, y, stepsize, obj, true)


static func gml_mp_potential_settings(_current_self, maxrot, rotstep, ahead, onspot):
	_gml_mp_potential_maxrot = max(1.0, _to_real(maxrot))
	_gml_mp_potential_rotstep = max(1.0, _to_real(rotstep))
	_gml_mp_potential_ahead = max(1.0, _to_real(ahead))
	_gml_mp_potential_onspot = gml_bool(onspot)
	return null


static func _gml_mp_potential_step(inst, x, y, stepsize, obj, checkall):
	# A step towards (x, y) that turns away from obstacles: the directions
	# closest to the goal are tried first, alternating sides, as long as the
	# instance's direction does not turn by more than maxrot; returns
	# whether the goal is reached.
	if not _gml_motion_is_instance(inst):
		return false
	var goal_x = _to_real(x)
	var goal_y = _to_real(y)
	var step = _to_real(stepsize)
	var position = _gml_motion_position(inst)
	var px = float(position.x)
	var py = float(position.y)
	if px == goal_x and py == goal_y:
		return true
	var distance = sqrt((px - goal_x) * (px - goal_x) + (py - goal_y) * (py - goal_y))
	if distance <= step:
		if _gml_mp_free(inst, goal_x, goal_y, obj, checkall):
			_gml_motion_assign_direction(inst, gml_point_direction(px, py, goal_x, goal_y))
			_gml_motion_set_position(inst, Vector2(goal_x, goal_y))
		return true
	var goal_direction = _to_real(gml_point_direction(px, py, goal_x, goal_y))
	var turn = 0.0
	while turn < 180.0:
		if _gml_mp_try_direction(inst, px, py, goal_direction - turn, step, obj, checkall):
			return false
		if _gml_mp_try_direction(inst, px, py, goal_direction + turn, step, obj, checkall):
			return false
		turn += _gml_mp_potential_rotstep
	if _gml_mp_potential_onspot:
		_gml_motion_assign_direction(inst, _gml_motion_real(inst, "direction", 0.0) + _gml_mp_potential_maxrot)
	return false


static func _gml_mp_try_direction(inst, px, py, direction, step, obj, checkall):
	# The runner's TryDir: steps in the direction when it turns the
	# instance's direction by at most maxrot and both the position `ahead`
	# steps away and the next one are free.
	if _gml_mp_direction_difference(direction, _gml_motion_real(inst, "direction", 0.0)) > _gml_mp_potential_maxrot:
		return false
	var cos_value = cos(PI * direction / 180.0)
	var sin_value = sin(PI * direction / 180.0)
	var ahead = step * _gml_mp_potential_ahead
	if not _gml_mp_free(inst, px + ahead * cos_value, py - ahead * sin_value, obj, checkall):
		return false
	var new_x = px + step * cos_value
	var new_y = py - step * sin_value
	if not _gml_mp_free(inst, new_x, new_y, obj, checkall):
		return false
	_gml_motion_assign_direction(inst, direction)
	_gml_motion_set_position(inst, Vector2(new_x, new_y))
	return true


static func _gml_mp_direction_difference(first, second):
	# The runner's DiffDir: the angle between two directions, 0 to 180.
	while first <= 0.0:
		first += 360.0
	while first >= 360.0:
		first -= 360.0
	while second < 0.0:
		second += 360.0
	while second >= 360.0:
		second -= 360.0
	var difference = abs(second - first)
	if difference > 180.0:
		difference = 360.0 - difference
	return difference


static func _gml_mp_free(inst, x, y, obj, checkall):
	# The runner's TestFree: without an object, free of solid instances, or
	# of any instance with checkall; with one, free of its instances.
	if obj == null:
		return gml_place_empty(inst, x, y) if checkall else gml_place_free(inst, x, y)
	return _gml_move_and_collide_test(inst, x, y, obj) == null


static func gml_mp_grid_add_instances(grid, obj, prec):
	# Marks the cells an instance's bounding box covers, or with prec only
	# those whose rectangle the instance's mask touches.
	var resolved = _gml_mp_grid_resolve(grid)
	if resolved == null:
		return gml_error("Error: invalid mp_grid ID (mp_grid_add_instances)")
	var precise = gml_bool(prec)
	# Keeps an edge that lies on a cell border out of the next cell, except
	# in collision compatibility mode.
	var col_delta = 0.0 if _gml_collision_compatibility() else 0.0001
	for inst in gml_with_targets(obj):
		if not _gml_collision_instance_live(inst):
			continue
		var state = _gml_collision_state(inst)
		if state != null:
			_gml_mp_grid_add_instance(resolved, state, precise, col_delta)
	return null


static func _gml_mp_grid_add_instance(grid, state, precise, col_delta):
	var left = float(grid["left"])
	var top = float(grid["top"])
	var cell_width = float(grid["cellwidth"])
	var cell_height = float(grid["cellheight"])
	var first_h = max(int((state["left"] + col_delta - left) / cell_width), 0)
	var last_h = min(int((state["right"] - col_delta - left) / cell_width), int(grid["hcells"]) - 1)
	var first_v = max(int((state["top"] + col_delta - top) / cell_height), 0)
	var last_v = min(int((state["bottom"] - col_delta - top) / cell_height), int(grid["vcells"]) - 1)
	for h in range(first_h, last_h + 1):
		for v in range(first_v, last_v + 1):
			if precise:
				if _gml_mp_grid_cell_blocked(grid, Vector2i(h, v)):
					continue
				var cell_left = left + h * cell_width
				var cell_top = top + v * cell_height
				if not _gml_collision_state_rectangle(state, cell_left, cell_top, cell_left + cell_width - 1.0, cell_top + cell_height - 1.0, true):
					continue
			_gml_mp_grid_set_cell(grid, h, v, true)
