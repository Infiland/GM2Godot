# --- Paths (yyPath.js, Function_Path.js) ---
#
# A path is a dictionary: its defining points ("points", each {"x", "y",
# "speed"}), "kind" (1 is smooth, anything else straight), "closed" and
# "precision", and the internal points GameMaker follows, which
# _gml_path_compute_internal derives from those: the defining points of a
# straight path, or the subdivided curve of a smooth one, plus the first
# point again at the end of a closed path. "ix", "iy" and "ispeed" hold the
# internal points and "il" their distance along the path; "length" is the
# whole length. Positions along a path (0 to 1) interpolate the internal
# points by distance, and so do their speed factors (100 is path_speed).
const GML_PATH_REGISTRY_PATH = "res://gm2godot/gml_path_registry.gd"
const GML_MP_GRID_HANDLE_KIND = "mp_grid"
# A smooth path's pieces stop dividing once a control leg is no longer than
# 4 pixels (HandlePiece compares squared lengths with 16).
const GML_PATH_SMOOTH_MIN_SQUARED = 16.0
# mp_grid_path's search looks left, right, up, down, then down-left,
# up-left, down-right and up-right; a diagonal needs the two straight
# neighbours (indices into the same list) free. Its walk back from the goal
# tries the diagonals in another order.
const GML_MP_GRID_SEARCH_OFFSETS = [
	Vector2i(-1, 0), Vector2i(1, 0), Vector2i(0, -1), Vector2i(0, 1),
	Vector2i(-1, 1), Vector2i(-1, -1), Vector2i(1, 1), Vector2i(1, -1)
]
const GML_MP_GRID_DIAGONAL_SIDES = [[3, 0], [2, 0], [3, 1], [2, 1]]
const GML_MP_GRID_BACK_OFFSETS = [
	Vector2i(-1, 0), Vector2i(1, 0), Vector2i(0, -1), Vector2i(0, 1),
	Vector2i(-1, 1), Vector2i(1, 1), Vector2i(-1, -1), Vector2i(1, -1)
]
# Where an instance's path starts in the room (the runner's path_xstart and
# path_ystart): path_start sets it, path_action_continue moves it on. Kept
# as node metadata, out of GML's sight.
const GML_PATH_START_META = "_gm_path_start"

static var _gml_path_registry_loaded = false
static var _gml_paths_by_id = {}
static var _gml_paths_by_name = {}


static func gml_path_registry_set(entries):
	_gml_path_registry_loaded = true
	_gml_paths_by_id = {}
	_gml_paths_by_name = {}
	for entry in entries:
		_gml_path_add_entry(entry)
	return null


static func gml_path_start(current_self, path, speed, endaction, absolute):
	var speed_value = _gml_path_real(speed)
	var action = _gml_path_int(endaction)
	var is_absolute = gml_bool(absolute)
	for instance in _gml_motion_instances(current_self):
		_gml_path_assign(instance, path, speed_value, 1.0, 0.0, is_absolute, action)
	return null


static func gml_path_end(current_self):
	# The runner's Assign_Path(-1, ...): the instance no longer follows a
	# path; path_speed, path_position and the rest keep their values.
	for instance in _gml_motion_instances(current_self):
		_gml_motion_write(instance, "path_index", -1)
	return null


static func gml_path_step(current_self):
	# Moves each instance one step along its path (Adapt_Path) and runs its
	# Path End event when it got to an end of the path.
	for instance in _gml_motion_instances(current_self):
		if _gml_path_adapt(instance):
			_gml_path_dispatch_end(instance)
	return null


static func gml_path_exists(path):
	if is_undefined(path):
		return false
	return _gml_path_resolve(path) != null


static func gml_path_get_name(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return ""
	return entry["name"]


static func gml_path_get_length(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return 0.0
	return entry["length"]


static func gml_path_get_kind(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return 0
	return entry["kind"]


static func gml_path_get_closed(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return true
	return entry["closed"]


static func gml_path_get_precision(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return 8
	return entry["precision"]


static func gml_path_get_number(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return 0
	return entry["points"].size()


static func gml_path_get_point_x(path, n):
	return _gml_path_point_field(path, n, "x")


static func gml_path_get_point_y(path, n):
	return _gml_path_point_field(path, n, "y")


static func gml_path_get_point_speed(path, n):
	return _gml_path_point_field(path, n, "speed")


static func gml_path_get_x(path, pos):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return -1
	return _gml_path_position(entry, _to_real(pos))[0]


static func gml_path_get_y(path, pos):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return -1
	return _gml_path_position(entry, _to_real(pos))[1]


static func gml_path_get_speed(path, pos):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return -1
	return _gml_path_position(entry, _to_real(pos))[2]


static func gml_path_add():
	# A new empty path (yyPath()): straight, closed, precision 4, no name.
	_gml_path_registry_ensure_loaded()
	var path_id = gml_asset_register_dynamic("path_" + str(_gml_asset_next_dynamic_id), "path")
	_gml_paths_by_id[path_id] = _gml_path_new(path_id, "")
	return path_id


static func gml_path_delete(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	_gml_paths_by_id.erase(entry["id"])
	for name in _gml_paths_by_name.keys():
		if is_same(_gml_paths_by_name[name], entry):
			_gml_paths_by_name.erase(name)
	gml_asset_release(entry["id"])
	return null


static func gml_path_duplicate(path):
	# A new path with the points and settings of path (name included), or
	# -1 when path does not exist.
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return -1
	var path_id = gml_path_add()
	_gml_path_copy(_gml_paths_by_id[path_id], entry)
	return path_id


static func gml_path_assign(path, source):
	var entry: Variant = _gml_path_resolve(path)
	var from: Variant = _gml_path_resolve(source)
	if entry != null and from != null:
		_gml_path_copy(entry, from)
	return null


static func gml_path_append(path, source):
	# Adds copies of source's points to the end of path.
	var entry: Variant = _gml_path_resolve(path)
	var from: Variant = _gml_path_resolve(source)
	if entry == null or from == null or from["points"].is_empty():
		return null
	entry["points"].append_array(_gml_path_points_copy(from["points"]))
	_gml_path_compute_internal(entry)
	return null


static func gml_path_add_point(path, x, y, speed):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	entry["points"].append(_gml_path_point(x, y, speed))
	_gml_path_compute_internal(entry)
	return null


static func gml_path_insert_point(path, n, x, y, speed):
	# Inserts the point before point n; n may be the number of points.
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var index = _gml_path_int(n)
	if index < 0 or index > entry["points"].size():
		return null
	entry["points"].insert(index, _gml_path_point(x, y, speed))
	_gml_path_compute_internal(entry)
	return null


static func gml_path_change_point(path, n, x, y, speed):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var index = _gml_path_int(n)
	if index < 0 or index >= entry["points"].size():
		return null
	entry["points"][index] = _gml_path_point(x, y, speed)
	_gml_path_compute_internal(entry)
	return null


static func gml_path_delete_point(path, n):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var index = _gml_path_int(n)
	if index < 0 or index >= entry["points"].size():
		return null
	entry["points"].remove_at(index)
	_gml_path_compute_internal(entry)
	return null


static func gml_path_clear_points(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	entry["points"] = []
	_gml_path_compute_internal(entry)
	return null


static func gml_path_set_kind(path, kind):
	# 1 is smooth; any other kind than 0 or 1 is straight (0). -1 when path
	# does not exist.
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return -1
	var value = _gml_path_int(kind)
	entry["kind"] = value if value == 0 or value == 1 else 0
	_gml_path_compute_internal(entry)
	return null


static func gml_path_set_closed(path, closed):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return -1
	entry["closed"] = gml_bool(closed)
	_gml_path_compute_internal(entry)
	return null


static func gml_path_set_precision(path, precision):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return -1
	entry["precision"] = clampi(_gml_path_int(precision), 0, 8)
	_gml_path_compute_internal(entry)
	return null


static func gml_path_shift(path, xoff, yoff):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var dx = _gml_path_real(xoff)
	var dy = _gml_path_real(yoff)
	for point in entry["points"]:
		point["x"] = point["x"] + dx
		point["y"] = point["y"] + dy
	_gml_path_compute_internal(entry)
	return null


static func gml_path_rescale(path, xscale, yscale):
	# Scales the points from the centre of their bounding box.
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var sx = _gml_path_real(xscale)
	var sy = _gml_path_real(yscale)
	var center = _gml_path_center(entry)
	for point in entry["points"]:
		point["x"] = (point["x"] - center.x) * sx + center.x
		point["y"] = (point["y"] - center.y) * sy + center.y
	_gml_path_compute_internal(entry)
	return null


static func gml_path_rotate(path, angle):
	# Turns the points angle degrees counterclockwise around the centre of
	# their bounding box.
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var radians = _gml_path_real(angle) * PI / 180.0
	var center = _gml_path_center(entry)
	for point in entry["points"]:
		var xx = point["x"] - center.x
		var yy = point["y"] - center.y
		point["x"] = xx * cos(radians) + yy * sin(radians) + center.x
		point["y"] = yy * cos(radians) - xx * sin(radians) + center.y
	_gml_path_compute_internal(entry)
	return null


static func gml_path_reverse(path):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null or entry["points"].size() <= 1:
		return null
	entry["points"].reverse()
	_gml_path_compute_internal(entry)
	return null


static func gml_path_flip(path):
	# Flips the points vertically around the centre of their bounding box.
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var center = _gml_path_center(entry)
	for point in entry["points"]:
		point["y"] = -(point["y"] - center.y) + center.y
	_gml_path_compute_internal(entry)
	return null


static func gml_path_mirror(path):
	# Mirrors the points horizontally around the centre of their bounding
	# box.
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return null
	var center = _gml_path_center(entry)
	for point in entry["points"]:
		point["x"] = -(point["x"] - center.x) + center.x
	_gml_path_compute_internal(entry)
	return null


static func gml_mp_grid_create(left, top, hcells, vcells, cellwidth, cellheight):
	var grid = {
		"left": _to_real(left),
		"top": _to_real(top),
		"hcells": max(0, int(_to_real(hcells))),
		"vcells": max(0, int(_to_real(vcells))),
		"cellwidth": max(_to_real(cellwidth), 1.0),
		"cellheight": max(_to_real(cellheight), 1.0),
		"blocked": {}
	}
	return gml_handle_register(GML_MP_GRID_HANDLE_KIND, grid)


static func gml_mp_grid_destroy(grid):
	var handle = gml_handle_from_value(GML_MP_GRID_HANDLE_KIND, grid)
	if gml_handle_is_valid(handle):
		gml_handle_invalidate(handle)
	return null


static func gml_mp_grid_clear_all(grid):
	var resolved = _gml_mp_grid_resolve(grid)
	if resolved == null:
		return null
	resolved["blocked"] = {}
	return null


static func gml_mp_grid_add_cell(grid, h, v):
	var resolved = _gml_mp_grid_resolve(grid)
	if resolved == null:
		return null
	_gml_mp_grid_set_cell(resolved, int(_to_real(h)), int(_to_real(v)), true)
	return null


static func gml_mp_grid_clear_cell(grid, h, v):
	var resolved = _gml_mp_grid_resolve(grid)
	if resolved == null:
		return null
	_gml_mp_grid_set_cell(resolved, int(_to_real(h)), int(_to_real(v)), false)
	return null


static func gml_mp_grid_add_rectangle(grid, left, top, right, bottom):
	var resolved = _gml_mp_grid_resolve(grid)
	if resolved == null:
		return null
	var start = _gml_mp_grid_cell_for_point(resolved, Vector2(_to_real(left), _to_real(top)))
	var finish = _gml_mp_grid_cell_for_point(resolved, Vector2(_to_real(right), _to_real(bottom)))
	for h in range(min(start.x, finish.x), max(start.x, finish.x) + 1):
		for v in range(min(start.y, finish.y), max(start.y, finish.y) + 1):
			_gml_mp_grid_set_cell(resolved, h, v, true)
	return null


static func gml_mp_grid_path(grid, path, xstart, ystart, xgoal, ygoal, allowdiag):
	# The runner's mp_grid_path: a breadth-first search from the start cell
	# to the goal cell. The path it writes (open, kind unchanged) runs from
	# the start position through the centres of the cells in between to the
	# goal position; positions are whole numbers. false, leaving the path as
	# it was, when there is no way, or the start or goal is off the grid or
	# in a blocked cell.
	var resolved = _gml_mp_grid_resolve(grid)
	var entry: Variant = _gml_path_resolve(path)
	if resolved == null or entry == null:
		return false
	var start_x = _gml_path_int(xstart)
	var start_y = _gml_path_int(ystart)
	var goal_x = _gml_path_int(xgoal)
	var goal_y = _gml_path_int(ygoal)
	var start = _gml_mp_grid_path_cell(resolved, start_x, start_y)
	var goal = _gml_mp_grid_path_cell(resolved, goal_x, goal_y)
	if start == null or goal == null:
		return false
	var diagonal = gml_bool(allowdiag)
	var steps = _gml_mp_grid_path_search(resolved, start, goal, diagonal)
	if steps.is_empty():
		return false
	var points = [{"x": float(goal_x), "y": float(goal_y), "speed": 100.0}]
	var cell = goal
	while cell != start:
		cell = _gml_mp_grid_path_back(resolved, steps, cell, diagonal)
		if cell == null:
			break
		if cell != start:
			var center = _gml_mp_grid_path_center(resolved, cell)
			points.append({"x": center.x, "y": center.y, "speed": 100.0})
	points.append({"x": float(start_x), "y": float(start_y), "speed": 100.0})
	points.reverse()
	entry["closed"] = false
	entry["points"] = points
	_gml_path_compute_internal(entry)
	return true


static func _gml_path_assign(instance, path, speed, scale, orientation, absolute, endaction):
	# Assign_Path: whatever path the instance followed stops; a path that
	# does not exist or has no length does not start. Positive speeds start
	# at the beginning of the path, negative ones at its end. An absolute
	# path starts where it lies in the room; a relative one puts its start
	# where the instance is.
	if not (instance is Node2D):
		return
	_gml_motion_write(instance, "path_index", -1)
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return
	if entry["length"] <= 0.0 or scale < 0.0:
		return
	_gml_motion_write(instance, "path_index", entry["id"])
	_gml_motion_write(instance, "path_speed", speed)
	var position = 0.0 if speed >= 0.0 else 1.0
	_gml_motion_write(instance, "path_position", position)
	_gml_motion_write(instance, "path_positionprevious", position)
	_gml_motion_write(instance, "path_scale", scale)
	_gml_motion_write(instance, "path_orientation", orientation)
	_gml_motion_write(instance, "path_endaction", endaction)
	if absolute:
		var at = _gml_path_position(entry, position)
		_gml_motion_set_position(instance, Vector2(at[0], at[1]))
		var first = _gml_path_position(entry, 0.0)
		instance.set_meta(GML_PATH_START_META, [first[0], first[1]])
	else:
		var current = _gml_motion_position(instance)
		instance.set_meta(GML_PATH_START_META, [current.x, current.y])


static func _gml_path_adapt(instance):
	# Adapt_Path: advances path_position by path_speed times the speed factor
	# at the current position (scaled by path_scale), applies the end action
	# when the position passes either end, and places the instance there,
	# scaled and turned by path_orientation around the path's start. The
	# move also sets direction; speed, hspeed and vspeed end up 0. Returns
	# whether the instance got to an end with a nonzero path_speed.
	if not (instance is Node2D):
		return false
	var path_index = _gml_path_real(_gml_motion_read(instance, "path_index", -1))
	if path_index < 0.0:
		return false
	var entry: Variant = _gml_path_resolve(path_index)
	if entry == null:
		return false
	var length = entry["length"]
	if length <= 0.0:
		return false
	var scale = _gml_path_real(_gml_motion_read(instance, "path_scale", 1.0))
	var radians = _gml_path_real(_gml_motion_read(instance, "path_orientation", 0.0)) * PI / 180.0
	var speed = _gml_path_real(_gml_motion_read(instance, "path_speed", 0.0))
	var position = _gml_path_real(_gml_motion_read(instance, "path_position", 0.0))
	var factor = _gml_path_position(entry, position)[2] / (100.0 * scale)
	position = position + speed * factor / length
	var first = _gml_path_position(entry, 0.0)
	var start = _gml_path_start_of(instance)
	var at_end = false
	if position >= 1.0 or position <= 0.0:
		at_end = speed != 0.0
		match _gml_path_int(_gml_motion_read(instance, "path_endaction", 0)):
			0:
				# path_action_stop
				if speed != 0.0:
					position = 1.0
					_gml_motion_write(instance, "path_index", -1)
			1:
				# path_action_restart: on from the other end.
				position = position + 1.0 if position < 0.0 else position - 1.0
			2:
				# path_action_continue: the path starts again where it ended.
				var last = _gml_path_position(entry, 1.0)
				var dx = last[0] - first[0]
				var dy = last[1] - first[1]
				var shift_x = scale * (dx * cos(radians) + dy * sin(radians))
				var shift_y = scale * (dy * cos(radians) - dx * sin(radians))
				if position < 0.0:
					start = [start[0] - shift_x, start[1] - shift_y]
					position = position + 1.0
				else:
					start = [start[0] + shift_x, start[1] + shift_y]
					position = position - 1.0
				instance.set_meta(GML_PATH_START_META, start)
			3:
				# path_action_reverse
				if position < 0.0:
					position = -position
					speed = absf(speed)
				else:
					position = 2.0 - position
					speed = -absf(speed)
				_gml_motion_write(instance, "path_speed", speed)
			_:
				position = 1.0
				_gml_motion_write(instance, "path_index", -1)
	_gml_motion_write(instance, "path_position", position)
	var node = _gml_path_position(entry, position)
	var xx = node[0] - first[0]
	var yy = node[1] - first[1]
	var new_x = start[0] + scale * (xx * cos(radians) + yy * sin(radians))
	var new_y = start[1] + scale * (yy * cos(radians) - xx * sin(radians))
	# The runner sets hspeed/vspeed to the move, which turns direction
	# along the path, then speed to 0, which zeroes hspeed/vspeed again.
	var current = _gml_motion_position(instance)
	_gml_motion_assign_hspeed(instance, new_x - current.x)
	_gml_motion_assign_vspeed(instance, new_y - current.y)
	_gml_motion_assign_speed(instance, 0.0)
	_gml_motion_set_position(instance, Vector2(new_x, new_y))
	return at_end


static func _gml_path_follows(instance):
	# Whether the instance follows a path: path_index is a path, not -1.
	var path_index = instance.get(&"path_index")
	if path_index == null:
		path_index = _gml_motion_read(instance, "path_index", -1)
	return (path_index is int or path_index is float) and path_index >= 0


static func _gml_path_motion_step(instance):
	# The runner's UpdatePositions for an instance on a path: friction and
	# gravity, then the path (which leaves speed 0), then Path End, then the
	# move by hspeed/vspeed, so only a speed set in Path End moves it.
	_gml_motion_adapt_speed(instance)
	if _gml_path_adapt(instance):
		_gml_path_dispatch_end(instance)
		if not is_instance_valid(instance):
			return
	var hspeed_value = _gml_motion_real(instance, "hspeed", 0.0)
	var vspeed_value = _gml_motion_real(instance, "vspeed", 0.0)
	if hspeed_value != 0.0 or vspeed_value != 0.0:
		var position = _gml_motion_position(instance)
		_gml_motion_set_position(instance, Vector2(position.x + hspeed_value, position.y + vspeed_value))


static func _gml_path_dispatch_end(instance):
	# Path End is an Other event: after a room change request only persistent
	# instances (or every instance of a persistent room) still get it.
	if instance.has_method("_on_path_ended") and not _gml_event_scheduler_event_blocked(instance, true):
		instance.call("_on_path_ended")


static func _gml_path_start_of(instance):
	if instance.has_meta(GML_PATH_START_META):
		return instance.get_meta(GML_PATH_START_META)
	return [0.0, 0.0]


static func _gml_path_real(value):
	# A path number read the way the runner's setters store it; 0 for a value
	# that is not a number (the runner reports an error there).
	if value is float:
		return value
	if value is int:
		return float(value)
	var number = _to_real(value)
	return number if number is float else 0.0


static func _gml_path_int(value):
	# yyGetInt32: the whole part of a number, 0 for NaN and infinities.
	var number = _gml_path_real(value)
	if not is_finite(number):
		return 0
	return int(number)


static func _gml_path_resolve(path):
	# The path a GML value names: a path id (asset or path_add), or a path
	# asset's name. null when no such path exists.
	_gml_path_registry_ensure_loaded()
	if is_undefined(path):
		return null
	if is_numeric(path):
		return _gml_paths_by_id.get(int(_to_real(path)))
	if is_string(path):
		var name = str(path)
		if _gml_paths_by_name.has(name):
			return _gml_paths_by_name[name]
		var asset_id = gml_asset_get_index(name)
		if is_numeric(asset_id) and int(asset_id) != -1:
			return _gml_paths_by_id.get(int(asset_id))
	return null


static func _gml_path_registry_ensure_loaded():
	if _gml_path_registry_loaded:
		return
	_gml_path_registry_loaded = true
	_gml_paths_by_id = {}
	_gml_paths_by_name = {}
	if ResourceLoader.exists(GML_PATH_REGISTRY_PATH):
		var registry = load(GML_PATH_REGISTRY_PATH)
		if registry != null and registry.has_method("entries"):
			for entry in registry.entries():
				_gml_path_add_entry(entry)


static func _gml_path_add_entry(entry):
	# A path asset as the registry lists it (CreatePathFromStorage).
	if typeof(entry) != TYPE_DICTIONARY or not entry.has("id"):
		return
	var path = _gml_path_new(int(entry["id"]), str(entry.get("name", "")))
	path["kind"] = int(_to_real(entry.get("kind", 0)))
	path["closed"] = bool(entry.get("closed", false))
	path["precision"] = int(_to_real(entry.get("precision", 4)))
	for point in entry.get("points", []):
		path["points"].append(_gml_path_point_from(point))
	_gml_path_compute_internal(path)
	_gml_paths_by_id[path["id"]] = path
	if path["name"] != "":
		_gml_paths_by_name[path["name"]] = path


static func _gml_path_new(path_id, name):
	# An empty path as yyPath() makes it: straight, closed, precision 4.
	return {
		"id": path_id,
		"name": name,
		"kind": 0,
		"closed": true,
		"precision": 4,
		"points": [],
		"ix": [],
		"iy": [],
		"ispeed": [],
		"il": [],
		"length": 0.0
	}


static func _gml_path_point_from(point):
	if typeof(point) == TYPE_DICTIONARY:
		return {
			"x": _to_real(point.get("x", 0.0)),
			"y": _to_real(point.get("y", 0.0)),
			"speed": _to_real(point.get("speed", 100.0))
		}
	if typeof(point) == TYPE_ARRAY and point.size() >= 2:
		return {"x": _to_real(point[0]), "y": _to_real(point[1]), "speed": _to_real(point[2]) if point.size() >= 3 else 100.0}
	return {"x": 0.0, "y": 0.0, "speed": 100.0}


static func _gml_path_point(x, y, speed):
	return {"x": _gml_path_real(x), "y": _gml_path_real(y), "speed": _gml_path_real(speed)}


static func _gml_path_copy(path, source):
	# yyPath.Assign: everything but the id, the name included.
	path["name"] = source["name"]
	path["kind"] = source["kind"]
	path["closed"] = source["closed"]
	path["precision"] = source["precision"]
	path["points"] = _gml_path_points_copy(source["points"])
	_gml_path_compute_internal(path)


static func _gml_path_points_copy(points):
	var copy = []
	for point in points:
		copy.append({"x": point["x"], "y": point["y"], "speed": point["speed"]})
	return copy


static func _gml_path_center(path):
	# Center: the middle of the bounding box of the defining points.
	var xmin = 100000000.0
	var xmax = -100000000.0
	var ymin = 100000000.0
	var ymax = -100000000.0
	for point in path["points"]:
		xmin = min(xmin, point["x"])
		xmax = max(xmax, point["x"])
		ymin = min(ymin, point["y"])
		ymax = max(ymax, point["y"])
	return Vector2((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)


static func _gml_path_point_field(path, n, field):
	# path_get_point_x/y/speed: 0 for a missing path or point.
	var index = int(_to_real(n))
	if index < 0:
		return 0
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return 0
	var points = entry["points"]
	if index >= points.size():
		return 0
	return points[index][field]


static func _gml_path_compute_internal(path):
	# ComputeInternal: the internal points of a smooth or straight path, then
	# their distances along it.
	var internal = [[], [], []]
	if int(path["kind"]) == 1:
		_gml_path_compute_curved(path, internal)
	else:
		_gml_path_compute_linear(path, internal)
	var ix = internal[0]
	var iy = internal[1]
	var distances = []
	var length = 0.0
	if not ix.is_empty():
		distances.append(0.0)
	for i in range(1, ix.size()):
		var dx = ix[i] - ix[i - 1]
		var dy = iy[i] - iy[i - 1]
		length = length + sqrt(dx * dx + dy * dy)
		distances.append(length)
	path["ix"] = ix
	path["iy"] = iy
	path["ispeed"] = internal[2]
	path["il"] = distances
	path["length"] = length


static func _gml_path_add_internal(internal, x, y, speed):
	internal[0].append(x)
	internal[1].append(y)
	internal[2].append(speed)


static func _gml_path_compute_linear(path, internal):
	var points = path["points"]
	if points.is_empty():
		return
	for point in points:
		_gml_path_add_internal(internal, point["x"], point["y"], point["speed"])
	if path["closed"]:
		_gml_path_add_internal(internal, points[0]["x"], points[0]["y"], points[0]["speed"])


static func _gml_path_compute_curved(path, internal):
	# ComputeCurved: each defining point bends a quadratic piece between the
	# midpoints of its two legs; an open path keeps its two end points.
	var points = path["points"]
	var count = points.size()
	if count <= 0:
		return
	var closed = path["closed"]
	if not closed:
		_gml_path_add_internal(internal, points[0]["x"], points[0]["y"], points[0]["speed"])
	var last_piece = count - 1 if closed else count - 3
	for i in range(last_piece + 1):
		var point1 = points[i % count]
		var point2 = points[(i + 1) % count]
		var point3 = points[(i + 2) % count]
		_gml_path_handle_piece(
			internal, int(path["precision"]),
			(point1["x"] + point2["x"]) / 2.0, (point1["y"] + point2["y"]) / 2.0, (point1["speed"] + point2["speed"]) / 2.0,
			point2["x"], point2["y"], point2["speed"],
			(point2["x"] + point3["x"]) / 2.0, (point2["y"] + point3["y"]) / 2.0, (point2["speed"] + point3["speed"]) / 2.0
		)
	if not closed:
		var last = points[count - 1]
		_gml_path_add_internal(internal, last["x"], last["y"], last["speed"])
	elif not internal[0].is_empty():
		_gml_path_add_internal(internal, internal[0][0], internal[1][0], internal[2][0])


static func _gml_path_handle_piece(internal, depth, x1, y1, s1, x2, y2, s2, x3, y3, s3):
	# HandlePiece: subdivides the piece until it is fine enough or the
	# precision runs out, adding the piece's middle point in between.
	if depth == 0:
		return
	var mx = (x1 + x2 + x2 + x3) / 4.0
	var my = (y1 + y2 + y2 + y3) / 4.0
	var ms = (s1 + s2 + s2 + s3) / 4.0
	if (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1) > GML_PATH_SMOOTH_MIN_SQUARED:
		_gml_path_handle_piece(internal, depth - 1, x1, y1, s1, (x2 + x1) / 2.0, (y2 + y1) / 2.0, (s2 + s1) / 2.0, mx, my, ms)
	_gml_path_add_internal(internal, mx, my, ms)
	if (x2 - x3) * (x2 - x3) + (y2 - y3) * (y2 - y3) > GML_PATH_SMOOTH_MIN_SQUARED:
		_gml_path_handle_piece(internal, depth - 1, mx, my, ms, (x3 + x2) / 2.0, (y3 + y2) / 2.0, (s3 + s2) / 2.0, x3, y3, s3)


static func _gml_path_position(path, pos):
	# GetPosition: [x, y, speed factor] at pos (0 to 1) along the path,
	# interpolated by distance between the internal points around it.
	var ix = path["ix"]
	var count = ix.size()
	if count <= 0:
		return [0.0, 0.0, 0.0]
	var iy = path["iy"]
	var ispeed = path["ispeed"]
	var length = path["length"]
	if count == 1 or length == 0.0 or pos <= 0.0:
		return [ix[0], iy[0], ispeed[0]]
	if pos >= 1.0:
		return [ix[count - 1], iy[count - 1], ispeed[count - 1]]
	var distances = path["il"]
	var target = length * pos
	# The last internal point at or before the target distance, and never
	# the final one.
	var index = clampi(distances.bsearch(target, false) - 1, 0, count - 2)
	target = target - distances[index]
	var width = distances[index + 1] - distances[index]
	if width == 0.0:
		return [ix[index], iy[index], ispeed[index]]
	return [
		ix[index] + target * (ix[index + 1] - ix[index]) / width,
		iy[index] + target * (iy[index + 1] - iy[index]) / width,
		ispeed[index] + target * (ispeed[index + 1] - ispeed[index]) / width
	]


static func _gml_mp_grid_resolve(grid):
	if is_handle(grid):
		if grid.kind != GML_MP_GRID_HANDLE_KIND:
			return null
		return grid.reference if gml_handle_is_valid(grid) else null
	if is_numeric(grid) or is_string(grid):
		return gml_handle_resolve_for_kind(GML_MP_GRID_HANDLE_KIND, grid)
	if typeof(grid) == TYPE_DICTIONARY:
		return grid
	return null


static func _gml_mp_grid_set_cell(grid, h, v, blocked):
	if not _gml_mp_grid_cell_inside(grid, Vector2i(h, v)):
		return
	var key = _gml_mp_grid_cell_key(Vector2i(h, v))
	if blocked:
		grid["blocked"][key] = true
	else:
		grid["blocked"].erase(key)


static func _gml_mp_grid_cell_for_point(grid, point):
	return Vector2i(
		int(floor((_to_real(point.x) - _to_real(grid["left"])) / _to_real(grid["cellwidth"]))),
		int(floor((_to_real(point.y) - _to_real(grid["top"])) / _to_real(grid["cellheight"])))
	)


static func _gml_mp_grid_path_cell(grid, x, y):
	# The cell of a start or goal position, or null when the position is off
	# the grid or its cell is blocked.
	var left = _to_real(grid["left"])
	var top = _to_real(grid["top"])
	var width = _to_real(grid["cellwidth"])
	var height = _to_real(grid["cellheight"])
	if x < left or x >= left + int(grid["hcells"]) * width:
		return null
	if y < top or y >= top + int(grid["vcells"]) * height:
		return null
	var cell = Vector2i(int((x - left) / width), int((y - top) / height))
	if _gml_mp_grid_cell_blocked(grid, cell):
		return null
	return cell


static func _gml_mp_grid_path_center(grid, cell):
	# The centre of a cell on a planned path, truncated to whole numbers.
	var width = _to_real(grid["cellwidth"])
	var height = _to_real(grid["cellheight"])
	return Vector2(
		int(_to_real(grid["left"]) + cell.x * width + width / 2.0),
		int(_to_real(grid["top"]) + cell.y * height + height / 2.0)
	)


static func _gml_mp_grid_path_search(grid, start, goal, diagonal):
	# The runner's search: every cell reached gets its distance from the
	# start (1 there, 0 unreached, -1 blocked). A cell looks left, right, up
	# and down, then, when diagonal, at the diagonals whose two neighbouring
	# cells it found free. Returns the distances, or [] when the goal is not
	# reached.
	var hcells = int(grid["hcells"])
	var vcells = int(grid["vcells"])
	var steps = PackedInt32Array()
	steps.resize(hcells * vcells)
	for h in range(hcells):
		for v in range(vcells):
			steps[h * vcells + v] = -1 if _gml_mp_grid_cell_blocked(grid, Vector2i(h, v)) else 0
	steps[start.x * vcells + start.y] = 1
	var queue = [start]
	var head = 0
	while head < queue.size():
		var cell = queue[head]
		head += 1
		if cell == goal:
			return steps
		var distance = steps[cell.x * vcells + cell.y] + 1
		var free = []
		for offset in GML_MP_GRID_SEARCH_OFFSETS:
			var next = cell + offset
			free.append(_gml_mp_grid_cell_inside(grid, next) and steps[next.x * vcells + next.y] == 0)
		for i in range(GML_MP_GRID_SEARCH_OFFSETS.size()):
			if not free[i]:
				continue
			if i >= 4:
				var sides = GML_MP_GRID_DIAGONAL_SIDES[i - 4]
				if not (diagonal and free[sides[0]] and free[sides[1]]):
					continue
			var next = cell + GML_MP_GRID_SEARCH_OFFSETS[i]
			steps[next.x * vcells + next.y] = distance
			queue.append(next)
	return PackedInt32Array()


static func _gml_mp_grid_path_back(grid, steps, cell, diagonal):
	# One step of the walk back from the goal: the first neighbour one step
	# nearer the start, straight ones first (the runner's order).
	var vcells = int(grid["vcells"])
	var nearer = steps[cell.x * vcells + cell.y] - 1
	for offset in GML_MP_GRID_BACK_OFFSETS:
		if not diagonal and offset.x != 0 and offset.y != 0:
			continue
		var next = cell + offset
		if _gml_mp_grid_cell_inside(grid, next) and steps[next.x * vcells + next.y] == nearer:
			return next
	return null


static func _gml_mp_grid_cell_inside(grid, cell):
	return cell.x >= 0 and cell.y >= 0 and cell.x < int(grid["hcells"]) and cell.y < int(grid["vcells"])


static func _gml_mp_grid_cell_blocked(grid, cell):
	return grid["blocked"].has(_gml_mp_grid_cell_key(cell))


static func _gml_mp_grid_cell_key(cell):
	return str(cell.x) + ":" + str(cell.y)
