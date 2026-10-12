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

static var _gml_path_registry_loaded = false
static var _gml_paths_by_id = {}
static var _gml_paths_by_name = {}
static var _gml_path_states = {}


static func gml_path_registry_set(entries):
	_gml_path_registry_loaded = true
	_gml_paths_by_id = {}
	_gml_paths_by_name = {}
	for entry in entries:
		_gml_path_add_entry(entry)
	return null


static func gml_path_start(current_self, path, speed, endaction, absolute):
	var entry: Variant = _gml_path_resolve(path)
	if entry == null:
		return gml_undefined()
	for instance in _gml_motion_instances(current_self):
		if not (instance is Node2D):
			continue
		if entry["ix"].is_empty():
			continue
		var path_id = int(entry["id"])
		var first_node = _gml_path_position(entry, 0.0)
		var first = Vector2(first_node[0], first_node[1])
		var is_absolute = gml_bool(absolute)
		var origin = Vector2.ZERO if is_absolute else _gml_instance_position(instance) - first
		_gml_path_states[_gml_path_state_key(instance)] = {
			"path_id": path_id,
			"origin": origin,
			"absolute": is_absolute,
			"endaction": int(_to_real(endaction)),
			"direction": 1
		}
		_gml_motion_write(instance, "path_index", path_id)
		_gml_motion_write(instance, "path_position", 0.0)
		_gml_motion_write(instance, "path_speed", _to_real(speed))
		_gml_motion_set_position(instance, origin + first)
	return null


static func gml_path_end(current_self):
	for instance in _gml_motion_instances(current_self):
		_gml_path_stop_instance(instance)
	return null


static func gml_path_step(current_self):
	if _gml_path_states.is_empty():
		# No instance follows a path.
		return null
	for instance in _gml_motion_instances(current_self):
		_gml_path_step_instance(instance)
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


static func _gml_path_step_instance(instance):
	var key = _gml_path_state_key(instance)
	if not _gml_path_states.has(key):
		return
	var path_id = int(_gml_motion_real(instance, "path_index", -1.0))
	var entry: Variant = _gml_path_resolve(path_id)
	if entry == null:
		_gml_path_stop_instance(instance)
		return
	var length = entry["length"]
	if length <= 0.000001:
		_gml_path_finish_instance(instance, entry)
		return
	var speed = _gml_motion_real(instance, "path_speed", 0.0)
	if abs(speed) <= 0.000001:
		return
	var state = _gml_path_states[key]
	var direction = int(state.get("direction", 1))
	var next_position = _gml_motion_real(instance, "path_position", 0.0) + (speed / length) * direction
	if next_position >= 1.0 or next_position <= 0.0:
		_gml_motion_write(instance, "path_position", clamp(next_position, 0.0, 1.0))
		_gml_motion_set_position(instance, state["origin"] + _gml_path_vector_at(entry, clamp(next_position, 0.0, 1.0)))
		_gml_path_finish_instance(instance, entry)
		return
	_gml_motion_write(instance, "path_position", next_position)
	_gml_motion_set_position(instance, state["origin"] + _gml_path_vector_at(entry, next_position))


static func _gml_path_finish_instance(instance, entry):
	# Path End is an Other event: after a room change request only persistent
	# instances (or every instance of a persistent room) still get it.
	if instance != null and instance.has_method("_on_path_ended") and not _gml_event_scheduler_event_blocked(instance, true):
		instance.call("_on_path_ended")
	var key = _gml_path_state_key(instance)
	if not _gml_path_states.has(key):
		return
	var state = _gml_path_states[key]
	if int(state.get("endaction", 0)) == 1:
		_gml_motion_write(instance, "path_position", 0.0)
		_gml_motion_set_position(instance, state["origin"] + _gml_path_vector_at(entry, 0.0))
		return
	_gml_path_stop_instance(instance)


static func _gml_path_stop_instance(instance):
	_gml_path_states.erase(_gml_path_state_key(instance))
	_gml_motion_write(instance, "path_index", gml_undefined())
	_gml_motion_write(instance, "path_speed", 0.0)


static func _gml_path_state_key(instance):
	if instance is Object:
		return instance.get_instance_id()
	return 0


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


static func _gml_path_vector_at(path, pos):
	var node = _gml_path_position(path, pos)
	return Vector2(node[0], node[1])


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
