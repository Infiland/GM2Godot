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
	var resolved = _gml_mp_grid_resolve(grid)
	if resolved == null:
		return false
	var start = _gml_mp_grid_cell_for_point(resolved, Vector2(_to_real(xstart), _to_real(ystart)))
	var goal = _gml_mp_grid_cell_for_point(resolved, Vector2(_to_real(xgoal), _to_real(ygoal)))
	var route = _gml_mp_grid_find_route(resolved, start, goal, gml_bool(allowdiag))
	if route.is_empty():
		return false
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return false
	var points = []
	for cell in route:
		var center = _gml_mp_grid_cell_center(resolved, cell)
		points.append({"x": center.x, "y": center.y, "speed": 100.0})
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


static func _gml_mp_grid_cell_center(grid, cell):
	return Vector2(
		_to_real(grid["left"]) + (cell.x + 0.5) * _to_real(grid["cellwidth"]),
		_to_real(grid["top"]) + (cell.y + 0.5) * _to_real(grid["cellheight"])
	)


static func _gml_mp_grid_find_route(grid, start, goal, allowdiag):
	if not _gml_mp_grid_cell_inside(grid, start) or not _gml_mp_grid_cell_inside(grid, goal):
		return []
	if _gml_mp_grid_cell_blocked(grid, start) or _gml_mp_grid_cell_blocked(grid, goal):
		return []
	var frontier = [start]
	var came_from = {_gml_mp_grid_cell_key(start): null}
	while not frontier.is_empty():
		var current = frontier.pop_front()
		if current == goal:
			break
		for next in _gml_mp_grid_neighbors(grid, current, allowdiag):
			var key = _gml_mp_grid_cell_key(next)
			if came_from.has(key):
				continue
			came_from[key] = current
			frontier.append(next)
	var goal_key = _gml_mp_grid_cell_key(goal)
	if not came_from.has(goal_key):
		return []
	var route = []
	var current = goal
	while current != null:
		route.push_front(current)
		current = came_from[_gml_mp_grid_cell_key(current)]
	return route


static func _gml_mp_grid_neighbors(grid, cell, allowdiag):
	var offsets = [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]
	if allowdiag:
		offsets.append(Vector2i(1, 1))
		offsets.append(Vector2i(1, -1))
		offsets.append(Vector2i(-1, 1))
		offsets.append(Vector2i(-1, -1))
	var neighbors = []
	for offset in offsets:
		var next = cell + offset
		if _gml_mp_grid_cell_inside(grid, next) and not _gml_mp_grid_cell_blocked(grid, next):
			neighbors.append(next)
	return neighbors


static func _gml_mp_grid_cell_inside(grid, cell):
	return cell.x >= 0 and cell.y >= 0 and cell.x < int(grid["hcells"]) and cell.y < int(grid["vcells"])


static func _gml_mp_grid_cell_blocked(grid, cell):
	return grid["blocked"].has(_gml_mp_grid_cell_key(cell))


static func _gml_mp_grid_cell_key(cell):
	return str(cell.x) + ":" + str(cell.y)
