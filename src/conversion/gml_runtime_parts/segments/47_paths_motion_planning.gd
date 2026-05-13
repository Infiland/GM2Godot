const GML_PATH_REGISTRY_PATH = "res://gm2godot/gml_path_registry.gd"
const GML_MP_GRID_HANDLE_KIND = "mp_grid"

static var _gml_path_registry_loaded = false
static var _gml_paths_by_id = {}
static var _gml_paths_by_name = {}
static var _gml_dynamic_paths = {}
static var _gml_path_states = {}


static func gml_path_registry_set(entries):
	_gml_path_registry_loaded = true
	_gml_paths_by_id = {}
	_gml_paths_by_name = {}
	_gml_dynamic_paths = {}
	for entry in entries:
		_gml_path_add_entry(entry)
	return null


static func gml_path_start(current_self, path, speed, endaction, absolute):
	var entry = _gml_path_resolve(path)
	if entry == null:
		return gml_undefined()
	for instance in _gml_motion_instances(current_self):
		if not (instance is Node2D):
			continue
		var points = entry.get("points", [])
		if points.is_empty():
			continue
		var path_id = int(entry["id"])
		var first = _gml_path_point_position(points[0])
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
	for instance in _gml_motion_instances(current_self):
		_gml_path_step_instance(instance)
	return null


static func gml_path_get_length(path):
	var entry = _gml_path_resolve(path)
	if entry == null:
		return 0.0
	return _gml_path_total_length(entry)


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
	var points = []
	for cell in route:
		var center = _gml_mp_grid_cell_center(resolved, cell)
		points.append({"x": center.x, "y": center.y, "speed": 100.0})
	_gml_path_set_dynamic(path, points, false)
	return true


static func _gml_path_step_instance(instance):
	var key = _gml_path_state_key(instance)
	if not _gml_path_states.has(key):
		return
	var path_id = int(_gml_motion_real(instance, "path_index", -1.0))
	var entry = _gml_path_resolve(path_id)
	if entry == null:
		_gml_path_stop_instance(instance)
		return
	var length = _gml_path_total_length(entry)
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
		_gml_motion_set_position(instance, state["origin"] + _gml_path_position_at(entry, clamp(next_position, 0.0, 1.0)))
		_gml_path_finish_instance(instance, entry)
		return
	_gml_motion_write(instance, "path_position", next_position)
	_gml_motion_set_position(instance, state["origin"] + _gml_path_position_at(entry, next_position))


static func _gml_path_finish_instance(instance, entry):
	if instance != null and instance.has_method("_on_path_ended"):
		instance.call("_on_path_ended")
	var key = _gml_path_state_key(instance)
	if not _gml_path_states.has(key):
		return
	var state = _gml_path_states[key]
	if int(state.get("endaction", 0)) == 1:
		_gml_motion_write(instance, "path_position", 0.0)
		_gml_motion_set_position(instance, state["origin"] + _gml_path_position_at(entry, 0.0))
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
	_gml_path_registry_ensure_loaded()
	if is_undefined(path):
		return null
	if is_numeric(path):
		var path_id = int(_to_real(path))
		if _gml_dynamic_paths.has(path_id):
			return _gml_dynamic_paths[path_id]
		return _gml_paths_by_id.get(path_id)
	if is_string(path):
		var name = str(path)
		if _gml_paths_by_name.has(name):
			return _gml_paths_by_name[name]
		var asset_id = gml_asset_get_index(name)
		if asset_id != -1:
			return _gml_path_resolve(asset_id)
	if typeof(path) == TYPE_DICTIONARY and path.has("points"):
		return path
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
	if typeof(entry) != TYPE_DICTIONARY or not entry.has("id"):
		return
	var normalized = {
		"id": int(entry["id"]),
		"name": str(entry.get("name", "")),
		"closed": bool(entry.get("closed", false)),
		"precision": int(entry.get("precision", 4)),
		"points": entry.get("points", [])
	}
	_gml_paths_by_id[normalized["id"]] = normalized
	if str(normalized["name"]) != "":
		_gml_paths_by_name[normalized["name"]] = normalized


static func _gml_path_set_dynamic(path, points, closed):
	var path_id = _gml_path_id_for_output(path)
	if path_id == -1:
		return
	var entry = {
		"id": path_id,
		"name": "",
		"closed": bool(closed),
		"precision": 4,
		"points": points
	}
	_gml_dynamic_paths[path_id] = entry


static func _gml_path_id_for_output(path):
	if is_numeric(path):
		return int(_to_real(path))
	if is_string(path):
		return int(gml_asset_get_index(path))
	return -1


static func _gml_path_total_length(entry):
	var points = entry.get("points", [])
	if points.size() < 2:
		return 0.0
	var length = 0.0
	for index in range(points.size() - 1):
		length += _gml_path_point_position(points[index]).distance_to(_gml_path_point_position(points[index + 1]))
	if bool(entry.get("closed", false)) and points.size() > 2:
		length += _gml_path_point_position(points[points.size() - 1]).distance_to(_gml_path_point_position(points[0]))
	return length


static func _gml_path_position_at(entry, path_position):
	var points = entry.get("points", [])
	if points.is_empty():
		return Vector2.ZERO
	if points.size() == 1:
		return _gml_path_point_position(points[0])
	var total_length = _gml_path_total_length(entry)
	if total_length <= 0.000001:
		return _gml_path_point_position(points[0])
	var target_distance = clamp(_to_real(path_position), 0.0, 1.0) * total_length
	var previous = _gml_path_point_position(points[0])
	for index in range(1, points.size()):
		var current = _gml_path_point_position(points[index])
		var segment_length = previous.distance_to(current)
		if target_distance <= segment_length or index == points.size() - 1:
			var ratio = 0.0 if segment_length <= 0.000001 else target_distance / segment_length
			return previous.lerp(current, clamp(ratio, 0.0, 1.0))
		target_distance -= segment_length
		previous = current
	if bool(entry.get("closed", false)) and points.size() > 2:
		var first = _gml_path_point_position(points[0])
		var segment_length = previous.distance_to(first)
		var ratio = 0.0 if segment_length <= 0.000001 else target_distance / segment_length
		return previous.lerp(first, clamp(ratio, 0.0, 1.0))
	return previous


static func _gml_path_point_position(point):
	if typeof(point) == TYPE_DICTIONARY:
		return Vector2(_to_real(point.get("x", 0.0)), _to_real(point.get("y", 0.0)))
	if typeof(point) == TYPE_ARRAY and point.size() >= 2:
		return Vector2(_to_real(point[0]), _to_real(point[1]))
	return Vector2.ZERO


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
