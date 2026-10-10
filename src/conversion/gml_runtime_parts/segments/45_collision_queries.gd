# GameMaker collision model.
#
# Collisions follow the GameMaker runner rather than Godot physics: every
# instance gets the bounding box GameMaker computes from its collision sprite
# (mask_index, else sprite_index), origin, image_xscale, image_yscale and
# image_angle, and queries test that box first. Sprites whose collision kind is
# precise, precise per frame, ellipse or diamond carry a pixel mask that
# precise checks sample; "rectangle with rotation" sprites use a separating
# axis test. Instances without a collision sprite never collide.
#
# The project option "collision compatibility mode" switches to the pre-2.3
# rules: whole-pixel bounding boxes with inclusive right/bottom edges, so
# instances whose boxes only touch collide. Without it boxes keep fractional
# edges and touching boxes do not collide.
const GML_COLLISION_CHECK_AXIS_ALIGNED = 0
const GML_COLLISION_CHECK_PRECISE = 1
const GML_COLLISION_CHECK_ROTATED = 2
const GML_COLLISION_NO_INSTANCE_DISTANCE = 10000000000.0
const GML_COLLISION_TRACE_LIMIT = 256
const GML_COLLISION_COMPATIBILITY_SETTING = "application/config/gm2godot_collision_compatibility"
const GML_COLLISION_UNKNOWN_OBJECT_ORDER = 1000000000
const GML_COLLISION_EVENT_PREFIX = "_on_collision_"

static var _gml_collision_event_trace = []
static var _gml_collision_compatibility_mode = null
static var _gml_collision_sprite_cache = {}
static var _gml_collision_state_cache = {}
static var _gml_collision_script_event_cache = {}
static var _gml_collision_object_order_cache = null
static var _gml_collision_object_order_source = null
static var _gml_collision_registry_objects = {}
static var _gml_collision_registered_scripts = {}
static var _gml_collision_registry_table = null


static func gml_distance_to_object(current_self, target):
	var self_state = _gml_collision_state(current_self)
	if self_state == null:
		return GML_COLLISION_NO_INSTANCE_DISTANCE
	var best_distance = GML_COLLISION_NO_INSTANCE_DISTANCE
	for inst in _gml_collision_targets(target, current_self, false):
		var other_state = _gml_collision_state(inst)
		if other_state == null:
			continue
		var distance = _gml_collision_bbox_gap(self_state, other_state)
		if distance < best_distance:
			best_distance = distance
	return best_distance


static func gml_distance_to_point(current_self, x, y):
	var state = _gml_collision_state(current_self)
	if state == null:
		return 0.0
	var px = _to_real(x)
	var py = _to_real(y)
	var xd = 0.0
	var yd = 0.0
	if px > state["right"]:
		xd = px - state["right"]
	if px < state["left"]:
		xd = px - state["left"]
	if py > state["bottom"]:
		yd = py - state["bottom"]
	if py < state["top"]:
		yd = py - state["top"]
	return sqrt(xd * xd + yd * yd)


static func gml_place_meeting(current_self, x, y, target):
	return gml_handle_is_valid(gml_instance_place(current_self, x, y, target))


static func gml_place_empty(current_self, x, y, target = null):
	var resolved_target = gml_instance_all() if target == null else target
	return not gml_place_meeting(current_self, x, y, resolved_target)


static func gml_place_free(current_self, x, y):
	var self_state = _gml_collision_state_at(current_self, x, y)
	if self_state == null:
		return true
	for inst in _gml_collision_targets(gml_instance_all(), current_self, true):
		if not _gml_collision_instance_solid(inst):
			continue
		if _gml_collision_states_collide(self_state, _gml_collision_state(inst), true):
			return false
	return true


static func gml_instance_place(current_self, x, y, target):
	var self_state = _gml_collision_state_at(current_self, x, y)
	if self_state == null:
		return gml_instance_noone()
	for inst in _gml_collision_targets(target, current_self, true):
		if _gml_collision_states_collide(_gml_collision_state(inst), self_state, true):
			return _gml_collision_handle_for_instance(inst)
	return gml_instance_noone()


static func gml_instance_place_list(current_self, x, y, target, list_id, ordered):
	var hits = []
	var self_state = _gml_collision_state_at(current_self, x, y)
	if self_state != null:
		for inst in _gml_collision_targets(target, current_self, true):
			if _gml_collision_states_collide(_gml_collision_state(inst), self_state, true):
				hits.append(inst)
	return _gml_collision_write_list(list_id, hits, ordered, _to_real(x), _to_real(y))


static func gml_position_meeting(current_self, x, y, target):
	return gml_handle_is_valid(gml_instance_position(current_self, x, y, target))


static func gml_position_empty(current_self, x, y):
	return not gml_handle_is_valid(gml_instance_position(current_self, x, y, gml_instance_all()))


static func gml_instance_position(current_self, x, y, target):
	return gml_collision_point(current_self, x, y, target, true, false)


static func gml_instance_position_list(current_self, x, y, target, list_id, ordered):
	return gml_collision_point_list(current_self, x, y, target, true, false, list_id, ordered)


static func gml_collision_point(current_self, x, y, target, precise = false, notme = false):
	var px = _to_real(x)
	var py = _to_real(y)
	var prec = gml_bool(precise)
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_point(_gml_collision_state(inst), px, py, prec):
			return _gml_collision_handle_for_instance(inst)
	return gml_instance_noone()


static func gml_collision_point_list(current_self, x, y, target, precise, notme, list_id, ordered):
	var px = _to_real(x)
	var py = _to_real(y)
	var prec = gml_bool(precise)
	var hits = []
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_point(_gml_collision_state(inst), px, py, prec):
			hits.append(inst)
	return _gml_collision_write_list(list_id, hits, ordered, px, py)


static func gml_collision_rectangle(current_self, x1, y1, x2, y2, target, precise = false, notme = false):
	var rect = [_to_real(x1), _to_real(y1), _to_real(x2), _to_real(y2)]
	var prec = gml_bool(precise)
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_rectangle(_gml_collision_state(inst), rect[0], rect[1], rect[2], rect[3], prec):
			return _gml_collision_handle_for_instance(inst)
	return gml_instance_noone()


static func gml_collision_rectangle_list(current_self, x1, y1, x2, y2, target, precise, notme, list_id, ordered):
	var rect = [_to_real(x1), _to_real(y1), _to_real(x2), _to_real(y2)]
	var prec = gml_bool(precise)
	var hits = []
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_rectangle(_gml_collision_state(inst), rect[0], rect[1], rect[2], rect[3], prec):
			hits.append(inst)
	return _gml_collision_write_list(list_id, hits, ordered, (rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5)


static func gml_collision_ellipse(current_self, x1, y1, x2, y2, target, precise = false, notme = false):
	var rect = [_to_real(x1), _to_real(y1), _to_real(x2), _to_real(y2)]
	var prec = gml_bool(precise)
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_ellipse(_gml_collision_state(inst), rect[0], rect[1], rect[2], rect[3], prec):
			return _gml_collision_handle_for_instance(inst)
	return gml_instance_noone()


static func gml_collision_ellipse_list(current_self, x1, y1, x2, y2, target, precise, notme, list_id, ordered):
	var rect = [_to_real(x1), _to_real(y1), _to_real(x2), _to_real(y2)]
	var prec = gml_bool(precise)
	var hits = []
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_ellipse(_gml_collision_state(inst), rect[0], rect[1], rect[2], rect[3], prec):
			hits.append(inst)
	return _gml_collision_write_list(list_id, hits, ordered, (rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5)


static func gml_collision_circle(current_self, x, y, radius, target, precise = false, notme = false):
	var cx = _to_real(x)
	var cy = _to_real(y)
	var r = _to_real(radius)
	return gml_collision_ellipse(current_self, cx - r, cy - r, cx + r, cy + r, target, precise, notme)


static func gml_collision_circle_list(current_self, x, y, radius, target, precise, notme, list_id, ordered):
	var cx = _to_real(x)
	var cy = _to_real(y)
	var r = _to_real(radius)
	return gml_collision_ellipse_list(current_self, cx - r, cy - r, cx + r, cy + r, target, precise, notme, list_id, ordered)


static func gml_collision_line(current_self, x1, y1, x2, y2, target, precise = false, notme = false):
	var line = [_to_real(x1), _to_real(y1), _to_real(x2), _to_real(y2)]
	var prec = gml_bool(precise)
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_line(_gml_collision_state(inst), line[0], line[1], line[2], line[3], prec):
			return _gml_collision_handle_for_instance(inst)
	return gml_instance_noone()


static func gml_collision_line_list(current_self, x1, y1, x2, y2, target, precise, notme, list_id, ordered):
	var line = [_to_real(x1), _to_real(y1), _to_real(x2), _to_real(y2)]
	var prec = gml_bool(precise)
	var hits = []
	for inst in _gml_collision_targets(target, current_self, gml_bool(notme)):
		if _gml_collision_state_line(_gml_collision_state(inst), line[0], line[1], line[2], line[3], prec):
			hits.append(inst)
	return _gml_collision_write_list(list_id, hits, ordered, line[0], line[1])


static func gml_collision_event_trace():
	return _gml_clone_value(_gml_collision_event_trace, 16)


static func gml_collision_event_trace_clear():
	_gml_collision_event_trace = []
	return null


# Runs the collision events of one step the way the GameMaker runner does.
# Collision pairs are registered per object: a pair already registered from
# the other side, or through a parent, is not registered again. Objects are
# visited in asset order; for every instance of the first object (children
# included) each registered target object is tested against all of its
# instances (children included). A colliding pair first moves both instances
# back to their previous position when either is solid, then runs the first
# instance's event and the second instance's event. Instances destroyed
# earlier in the step are skipped, instances created during the collision
# events wait for the next step, and an instance pair runs its events at
# most once per step.
static func gml_collision_event_dispatch_frame(instances = null, frame = -1):
	_gml_event_scheduler_record_phase("collision", "", null, frame)
	var context = _gml_collision_dispatch_context(instances, frame)
	if context["pool"].size() < 2:
		return 0
	var table = _gml_collision_registered_table()
	var dispatched = 0
	for first_name in table["order"]:
		var first_indices = context["by_object"].get(first_name, null)
		if first_indices == null:
			continue
		var targets = table["targets"][first_name]
		for first_index in first_indices:
			dispatched += _gml_collision_dispatch_instance(context, first_index, targets)
	return dispatched


static func _gml_collision_dispatch_context(instances, frame):
	var source = instances if instances is Array else _gml_collision_live_instances()
	var context = {
		"pool": [],
		"entries": [],
		"chains": [],
		"states": [],
		"by_object": {},
		"handled": {},
		"frame": frame,
	}
	var seen = {}
	for inst in source:
		if not _gml_collision_instance_valid(inst):
			continue
		var entry: Variant = _gml_instance_entry(inst)
		if entry == null or entry["destroyed"]:
			continue
		var key = inst.get_instance_id()
		if seen.has(key):
			continue
		seen[key] = true
		var chain = _gml_collision_entry_object_chain(entry)
		if chain.is_empty():
			continue
		var pool_index = context["pool"].size()
		context["pool"].append(inst)
		context["entries"].append(entry)
		context["chains"].append(chain)
		context["states"].append(null)
		for object_name in chain:
			if not context["by_object"].has(object_name):
				context["by_object"][object_name] = []
			context["by_object"][object_name].append(pool_index)
		_gml_collision_register_instance_events(inst, chain)
	return context


static func _gml_collision_dispatch_instance(context, first_index, targets):
	var dispatched = 0
	var chains = context["chains"]
	var pool_size = context["pool"].size()
	for second_name in targets:
		var second_indices = context["by_object"].get(second_name, null)
		if second_indices == null:
			continue
		for second_index in second_indices:
			if not _gml_collision_context_live(context, first_index):
				return dispatched
			if second_index == first_index or not _gml_collision_context_live(context, second_index):
				continue
			# Two instances of the same object are tested once, in pool order.
			if second_index < first_index and chains[second_index][0] == chains[first_index][0]:
				continue
			var pair_key = min(first_index, second_index) * pool_size + max(first_index, second_index)
			if context["handled"].has(pair_key):
				continue
			var first_state = _gml_collision_context_state(context, first_index)
			var second_state = _gml_collision_context_state(context, second_index)
			if not _gml_collision_states_collide(first_state, second_state, true):
				continue
			context["handled"][pair_key] = true
			dispatched += _gml_collision_dispatch_pair(
				context["pool"][first_index],
				chains[first_index],
				context["pool"][second_index],
				chains[second_index],
				context["frame"]
			)
			# Events may move, change or destroy any instance.
			context["states"].fill(null)
	return dispatched


static func _gml_collision_context_live(context, index):
	return not context["entries"][index]["destroyed"] and is_instance_valid(context["pool"][index])


static func _gml_collision_context_state(context, index):
	var state = context["states"][index]
	if state == null:
		state = _gml_collision_state(context["pool"][index])
		context["states"][index] = state
	return state


static func _gml_collision_dispatch_pair(first, first_chain, second, second_chain, frame):
	var solid = _gml_collision_instance_solid(first) or _gml_collision_instance_solid(second)
	if solid:
		_gml_collision_restore_previous_position(first, second)
		_gml_collision_restore_previous_position(second, first)
	var dispatched = 0
	dispatched += _gml_collision_perform_event(first, second, second_chain, frame)
	dispatched += _gml_collision_perform_event(second, first, first_chain, frame)
	if solid and _gml_collision_compatibility():
		# Compatibility mode lets both instances try their motion again and
		# moves them back only when they still overlap.
		_gml_collision_step_by_speed(first)
		_gml_collision_step_by_speed(second)
		if _gml_collision_states_collide(_gml_collision_state(first), _gml_collision_state(second), true):
			_gml_collision_restore_previous_position(first, second)
			_gml_collision_restore_previous_position(second, first)
	return dispatched


# The step loop stops running events once a room change is pending; it hooks
# that check in here. Until then every collision event runs.
static func _gml_collision_events_blocked():
	return false


static func _gml_collision_perform_event(inst, other_inst, other_chain, frame):
	# The event for the other instance's object wins over an event for one of
	# its parents; GDScript inheritance already resolves this instance's own
	# parents.
	if not _gml_collision_instance_valid(inst) or not _gml_collision_instance_valid(other_inst):
		return 0
	if _gml_collision_events_blocked():
		return 0
	for object_name in other_chain:
		var method_name = GML_COLLISION_EVENT_PREFIX + str(object_name)
		if not inst.has_method(method_name):
			continue
		var has_other = "other" in inst
		var previous_other = inst.get("other") if has_other else null
		if has_other:
			inst.set("other", other_inst)
		_gml_collision_trace_append({
			"event": "collision",
			"frame": frame,
			"instance": str(inst.name) if inst is Node else "",
			"other": str(other_inst.name) if other_inst is Node else "",
			"method": method_name,
			"target_object": str(object_name),
		})
		_gml_event_scheduler_record_phase("collision", method_name, inst, frame)
		inst.call(method_name)
		if has_other and _gml_collision_instance_valid(inst):
			inst.set("other", previous_other)
		return 1
	return 0


static func _gml_collision_restore_previous_position(inst, other_inst):
	if not _gml_collision_instance_valid(inst) or not (inst is Node2D):
		return
	var xprevious = inst.get("xprevious")
	var yprevious = inst.get("yprevious")
	if xprevious == null or yprevious == null:
		return
	var previous = Vector2(_to_real(xprevious), _to_real(yprevious))
	if previous == _gml_collision_instance_xy(inst):
		return
	_gml_collision_set_instance_xy(inst, previous)
	if "path_positionprevious" in inst and "path_position" in inst:
		inst.set("path_position", inst.get("path_positionprevious"))
	_gml_collision_trace_append({
		"event": "solid_rollback",
		"instance": str(inst.name),
		"other": str(other_inst.name) if other_inst is Node else "",
		"x": previous.x,
		"y": previous.y,
	})


static func _gml_collision_step_by_speed(inst):
	if not _gml_collision_instance_valid(inst) or not (inst is Node2D):
		return
	var hspeed_value = inst.get("hspeed")
	var vspeed_value = inst.get("vspeed")
	var h = _to_real(hspeed_value) if hspeed_value != null else 0.0
	var v = _to_real(vspeed_value) if vspeed_value != null else 0.0
	var position = _gml_collision_instance_xy(inst)
	_gml_collision_set_instance_xy(inst, Vector2(position.x + h, position.y + v))


static func _gml_collision_trace_append(record):
	_gml_collision_event_trace.append(record)
	if _gml_collision_event_trace.size() > GML_COLLISION_TRACE_LIMIT:
		_gml_collision_event_trace.remove_at(0)


static func _gml_collision_live_instances():
	var instances = []
	for entry in _gml_live_instance_entries():
		var inst = entry["instance"]
		if _gml_collision_instance_valid(inst):
			instances.append(inst)
	return instances


static func _gml_collision_instance_valid(inst):
	return inst is Object and is_instance_valid(inst)


static func _gml_collision_instance_live(inst):
	# Destroyed instances stay valid Godot objects until the end of the frame
	# but GameMaker stops matching them as soon as they are destroyed.
	if not _gml_collision_instance_valid(inst):
		return false
	var entry: Variant = _gml_instance_entry(inst)
	if entry == null:
		return not _gml_instance_handles_by_node_id.has(inst.get_instance_id()) and not inst.has_meta("_gm2godot_instance_id")
	return not entry["destroyed"]


static func _gml_collision_instance_solid(inst):
	if not _gml_collision_instance_valid(inst):
		return false
	var value = inst.get("solid")
	if value == null or is_undefined(value):
		return false
	return gml_bool(value)


# --- Collision event registry -------------------------------------------------

static func _gml_collision_entry_object_chain(entry):
	var chain = []
	for selector_name in entry.get("selector_names", []):
		var object_name = str(selector_name)
		if object_name != "" and not chain.has(object_name):
			chain.append(object_name)
	if chain.is_empty() and str(entry.get("object_name", "")) != "":
		chain.append(str(entry["object_name"]))
	return chain


static func _gml_collision_register_instance_events(inst, chain):
	# Each converted object script declares its own collision events as
	# _on_collision_<object> methods; a child script extends its parent's
	# script, so the events an object declares itself are the methods its
	# script adds to its base script.
	var script = inst.get_script()
	if not (script is Script) or _gml_collision_registered_scripts.has(script.get_instance_id()):
		return
	_gml_collision_registered_scripts[script.get_instance_id()] = true
	var chain_index = 0
	while script is Script and chain_index < chain.size():
		var object_name = _gml_collision_script_object_name(script, chain, chain_index)
		chain_index = chain.find(object_name) + 1
		if not _gml_collision_registry_objects.has(object_name):
			var parent_name = chain[chain_index] if chain_index < chain.size() else ""
			_gml_collision_registry_objects[object_name] = {
				"parent": parent_name,
				"events": _gml_collision_script_own_events(script),
			}
			_gml_collision_registry_table = null
		script = script.get_base_script()


static func _gml_collision_script_object_name(script, chain, chain_index):
	var file_name = str(script.resource_path).get_file().get_basename()
	if file_name != "" and chain.has(file_name):
		return file_name
	return chain[chain_index]


static func _gml_collision_script_own_events(script):
	var key = script.get_instance_id()
	if _gml_collision_script_event_cache.has(key):
		return _gml_collision_script_event_cache[key]
	var counts = {}
	for method in script.get_script_method_list():
		var method_name = str(method.get("name", ""))
		counts[method_name] = int(counts.get(method_name, 0)) + 1
	var base_script = script.get_base_script()
	if base_script is Script:
		for method in base_script.get_script_method_list():
			var method_name = str(method.get("name", ""))
			counts[method_name] = int(counts.get(method_name, 0)) - 1
	var events = []
	for method_name in counts.keys():
		if int(counts[method_name]) <= 0:
			continue
		if not str(method_name).begins_with(GML_COLLISION_EVENT_PREFIX):
			continue
		var target_object = str(method_name).substr(GML_COLLISION_EVENT_PREFIX.length())
		if target_object != "":
			events.append(target_object)
	events.sort_custom(_gml_collision_object_less)
	_gml_collision_script_event_cache[key] = events
	return events


static func _gml_collision_registered_table():
	if _gml_collision_registry_table != null and is_same(_gml_collision_object_order_source, _gml_asset_entries):
		return _gml_collision_registry_table
	# Mirrors GameMaker's collision table: objects are visited in asset order,
	# a parent before its children, and a pair is skipped when the other
	# object (or one of its parents) already collides with this object (or
	# one of its parents).
	var targets = {}
	var done = {}
	var object_names = _gml_collision_registry_objects.keys()
	object_names.sort_custom(_gml_collision_object_less)
	for object_name in object_names:
		_gml_collision_add_object_pairs(object_name, targets, done)
	var order = targets.keys()
	order.sort_custom(_gml_collision_object_less)
	_gml_collision_registry_table = {"order": order, "targets": targets}
	return _gml_collision_registry_table


static func _gml_collision_add_object_pairs(object_name, table, done):
	if done.has(object_name) or not _gml_collision_registry_objects.has(object_name):
		return
	done[object_name] = true
	var info = _gml_collision_registry_objects[object_name]
	if str(info["parent"]) != "":
		_gml_collision_add_object_pairs(str(info["parent"]), table, done)
	for target_name in info["events"]:
		if table.has(target_name) and table[target_name].has(object_name):
			continue
		if _gml_collision_pair_registered_from_other_side(object_name, target_name, table):
			continue
		if not table.has(object_name):
			table[object_name] = []
		table[object_name].append(target_name)


static func _gml_collision_pair_registered_from_other_side(object_name, target_name, table):
	for own_name in _gml_collision_registry_chain(object_name):
		for other_name in _gml_collision_registry_chain(target_name):
			if table.has(other_name) and table[other_name].has(own_name):
				return true
	return false


static func _gml_collision_registry_chain(object_name):
	var chain = []
	var current = str(object_name)
	while current != "" and not chain.has(current):
		chain.append(current)
		if not _gml_collision_registry_objects.has(current):
			break
		current = str(_gml_collision_registry_objects[current]["parent"])
	return chain


static func _gml_collision_object_less(left, right):
	var left_order = _gml_collision_object_order(left)
	var right_order = _gml_collision_object_order(right)
	if left_order != right_order:
		return left_order < right_order
	return str(left) < str(right)


static func _gml_collision_object_order(object_name):
	_gml_asset_registry_ensure_loaded()
	# Rebuilt when the asset registry is replaced; the collision table is
	# ordered by it.
	if _gml_collision_object_order_cache == null or not is_same(_gml_collision_object_order_source, _gml_asset_entries):
		_gml_collision_object_order_cache = {}
		_gml_collision_object_order_source = _gml_asset_entries
		_gml_collision_registry_table = null
		var order = 0
		for entry in _gml_asset_entries:
			if str(entry.get("type", "")) == "object":
				_gml_collision_object_order_cache[str(entry["name"])] = order
				order += 1
	return int(_gml_collision_object_order_cache.get(str(object_name), GML_COLLISION_UNKNOWN_OBJECT_ORDER))


# --- Targets and results ------------------------------------------------------

static func _gml_collision_targets(target, current_self, notme):
	var candidates = []
	if target is Array:
		for element in target:
			for inst in _gml_collision_targets(element, current_self, notme):
				if not candidates.has(inst):
					candidates.append(inst)
		return candidates
	if target == null or is_undefined(target):
		return candidates
	for inst in gml_with_targets(target, current_self, null):
		if not _gml_collision_instance_live(inst):
			continue
		if notme and _gml_collision_same_instance(inst, current_self):
			continue
		candidates.append(inst)
	return candidates


static func _gml_collision_write_list(list_id, instances, ordered, origin_x, origin_y):
	var records = []
	for index in range(instances.size()):
		var inst = instances[index]
		var position = _gml_collision_instance_xy(inst)
		var dx = position.x - origin_x
		var dy = position.y - origin_y
		records.append({
			"handle": _gml_collision_handle_for_instance(inst),
			"distance": dx * dx + dy * dy,
			"order": index,
		})
	return _gml_collision_append_hits_to_list(list_id, records, ordered)


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
	var left_distance = float(left["distance"])
	var right_distance = float(right["distance"])
	if left_distance != right_distance:
		return left_distance < right_distance
	return int(left.get("order", 0)) < int(right.get("order", 0))


static func _gml_collision_handle_for_instance(instance):
	var entry: Variant = _gml_instance_entry(instance)
	if entry == null:
		return gml_instance_noone()
	return entry["handle"]


static func _gml_collision_same_instance(left, right):
	if left == null or right == null:
		return false
	if left is Object and right is Object and left == right:
		return true
	var left_entry: Variant = _gml_instance_entry(left)
	var right_entry: Variant = _gml_instance_entry(right)
	if left_entry == null or right_entry == null:
		return false
	return left_entry["handle"].index == right_entry["handle"].index


# --- Instance bounding boxes -------------------------------------------------

static func _gml_collision_compatibility():
	if _gml_collision_compatibility_mode == null:
		_gml_collision_compatibility_mode = bool(ProjectSettings.get_setting(GML_COLLISION_COMPATIBILITY_SETTING, false))
	return _gml_collision_compatibility_mode


static func _gml_collision_set_compatibility_mode(enabled):
	_gml_collision_compatibility_mode = null if enabled == null else gml_bool(enabled)
	_gml_collision_state_cache.clear()
	return null


# GameMaker's bbox_left/top/right/bottom for an instance, or null when it has
# no collision sprite (GameMaker then reports its x and y).
static func _gml_collision_instance_bbox(inst):
	var state = _gml_collision_state(inst)
	if state == null or state["data"] == null:
		return null
	return {
		"left": state["left"],
		"top": state["top"],
		"right": state["right"],
		"bottom": state["bottom"],
	}


static func _gml_collision_instance_bbox_value(inst, field_name):
	var state = _gml_collision_state(inst)
	if state == null:
		return 0.0
	return state[str(field_name).trim_prefix("bbox_")]


static func _gml_collision_instance_contains_point(inst, x, y):
	if not _gml_collision_instance_live(inst):
		return false
	return _gml_collision_state_point(_gml_collision_state(inst), _to_real(x), _to_real(y), true)


# An instance's GML x/y: its position, or its room position while a sequence
# drives it.
static func _gml_collision_instance_xy(inst):
	if not (inst is Node2D):
		return Vector2.ZERO
	if bool(inst.get_meta("gamemaker_in_sequence", false)):
		return inst.global_position
	return inst.position


static func _gml_collision_set_instance_xy(inst, position):
	if not (inst is Node2D):
		return
	if bool(inst.get_meta("gamemaker_in_sequence", false)):
		inst.global_position = position
	else:
		inst.position = position


# Kept for callers that still think in polygons: the instance's bounding box
# as one rectangle whose far edges sit one pixel past bbox_right/bbox_bottom.
static func _gml_collision_polygons_for_instance(instance, _use_precise = true):
	var bbox = _gml_collision_instance_bbox(instance)
	if bbox == null:
		return []
	var left = float(bbox["left"])
	var top = float(bbox["top"])
	var right = float(bbox["right"]) + 1.0
	var bottom = float(bbox["bottom"]) + 1.0
	return [PackedVector2Array([
		Vector2(left, top),
		Vector2(right, top),
		Vector2(right, bottom),
		Vector2(left, bottom),
	])]


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


static func _gml_collision_state(inst):
	if not _gml_collision_instance_valid(inst):
		return null
	var position = _gml_collision_instance_xy(inst)
	var signature = [
		position,
		inst.get("sprite_index"),
		inst.get("mask_index"),
		inst.get("image_xscale"),
		inst.get("image_yscale"),
		inst.get("image_angle"),
		_gml_collision_compatibility(),
	]
	var key = inst.get_instance_id()
	var cached = _gml_collision_state_cache.get(key, null)
	if cached != null and cached["signature"] == signature:
		return cached
	var state = _gml_collision_make_state(inst, position.x, position.y, signature)
	_gml_collision_state_cache[key] = state
	if _gml_collision_state_cache.size() > 4096:
		_gml_collision_prune_state_cache()
	return state


static func _gml_collision_state_at(inst, x, y):
	var state = _gml_collision_state(inst)
	if state == null:
		return null
	var px = _to_real(x)
	var py = _to_real(y)
	if px == state["x"] and py == state["y"]:
		return state
	return _gml_collision_make_state(inst, px, py, state["signature"])


static func _gml_collision_prune_state_cache():
	for key in _gml_collision_state_cache.keys():
		var state = _gml_collision_state_cache[key]
		if not _gml_collision_instance_valid(state["inst"]):
			_gml_collision_state_cache.erase(key)


static func _gml_collision_make_state(inst, x, y, signature):
	var state = {
		"inst": inst,
		"x": float(x),
		"y": float(y),
		"xscale": _gml_collision_real_or(signature[3], 1.0),
		"yscale": _gml_collision_real_or(signature[4], 1.0),
		"angle": _gml_collision_real_or(signature[5], 0.0),
		"data": _gml_collision_mask_sprite(signature[1], signature[2]),
		"signature": signature,
	}
	_gml_collision_compute_bbox(state)
	return state


static func _gml_collision_real_or(value, fallback):
	if value == null or is_undefined(value):
		return fallback
	if typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT or typeof(value) == TYPE_BOOL:
		return float(value)
	return _to_real(value)


static func _gml_collision_mask_sprite(sprite_index, mask_index):
	# mask_index wins when it holds a sprite; -1 (or no value) means "use
	# sprite_index".
	if mask_index != null and not is_undefined(mask_index):
		if not (_gml_collision_is_number(mask_index) and _to_real(mask_index) < 0.0):
			return _gml_collision_sprite_data(mask_index)
	return _gml_collision_sprite_data(sprite_index)


static func _gml_collision_is_number(value):
	var value_type = typeof(value)
	return value_type == TYPE_INT or value_type == TYPE_FLOAT or value_type == TYPE_BOOL or is_int64(value)


static func _gml_collision_compute_bbox(state):
	var data = state["data"]
	var x = state["x"]
	var y = state["y"]
	if data == null:
		state["left"] = x
		state["right"] = x
		state["top"] = y
		state["bottom"] = y
		state["colcheck"] = GML_COLLISION_CHECK_AXIS_ALIGNED
		return
	state["colcheck"] = data["colcheck"]
	if state["angle"] == 0.0:
		_gml_collision_compute_axis_aligned_bbox(state, data)
	else:
		_gml_collision_compute_rotated_bbox(state, data)


static func _gml_collision_compute_axis_aligned_bbox(state, data):
	var compat = _gml_collision_compatibility()
	var xscale = state["xscale"]
	var yscale = state["yscale"]
	var width = float(data["right"] + 1 - data["left"])
	var height = float(data["bottom"] + 1 - data["top"])
	var left = state["x"] + xscale * (float(data["left"]) - data["xorigin"])
	var top = state["y"] + yscale * (float(data["top"]) - data["yorigin"])
	var right = 0.0
	var bottom = 0.0
	if compat:
		left = _gml_collision_round(left)
		right = _gml_collision_round(left + xscale * width)
		top = _gml_collision_round(top)
		bottom = _gml_collision_round(top + yscale * height)
	else:
		right = left + xscale * width
		bottom = top + yscale * height
	if left > right:
		var swap_x = left
		left = right
		right = swap_x
	if top > bottom:
		var swap_y = top
		top = bottom
		bottom = swap_y
	if compat:
		right -= 1.0
		bottom -= 1.0
	state["left"] = left
	state["top"] = top
	state["right"] = right
	state["bottom"] = bottom


static func _gml_collision_compute_rotated_bbox(state, data):
	var compat = _gml_collision_compatibility()
	var xscale = state["xscale"]
	var yscale = state["yscale"]
	var xmin = xscale * (float(data["left"]) - data["xorigin"])
	var xmax = xscale * (float(data["right"]) - data["xorigin"] + 1.0)
	var ymin = yscale * (float(data["top"]) - data["yorigin"])
	var ymax = yscale * (float(data["bottom"]) - data["yorigin"] + 1.0)
	var radians = state["angle"] * PI / 180.0
	var cc = cos(radians)
	var ss = sin(radians)
	var cc_xmax = cc * xmax
	var cc_xmin = cc * xmin
	var ss_ymax = ss * ymax
	var ss_ymin = ss * ymin
	if cc_xmax < cc_xmin:
		var swap_a = cc_xmin
		cc_xmin = cc_xmax
		cc_xmax = swap_a
	if ss_ymax < ss_ymin:
		var swap_b = ss_ymin
		ss_ymin = ss_ymax
		ss_ymax = swap_b
	var cc_ymax = cc * ymax
	var cc_ymin = cc * ymin
	var ss_xmax = ss * xmax
	var ss_xmin = ss * xmin
	if cc_ymax < cc_ymin:
		var swap_c = cc_ymin
		cc_ymin = cc_ymax
		cc_ymax = swap_c
	if ss_xmax < ss_xmin:
		var swap_d = ss_xmin
		ss_xmin = ss_xmax
		ss_xmax = swap_d
	var x = state["x"]
	var y = state["y"]
	if compat:
		state["left"] = floor(x + cc_xmin + ss_ymin + 0.5)
		state["right"] = floor(x + cc_xmax + ss_ymax - 0.5)
		state["top"] = floor(y + cc_ymin - ss_xmax + 0.5)
		state["bottom"] = floor(y + cc_ymax - ss_xmin - 0.5)
	else:
		state["left"] = x + cc_xmin + ss_ymin
		state["right"] = x + cc_xmax + ss_ymax
		state["top"] = y + cc_ymin - ss_xmax
		state["bottom"] = y + cc_ymax - ss_xmin


static func _gml_collision_round(value):
	# GameMaker's Round: halves go to the even neighbour.
	var floor_value = floor(value)
	var fraction = value - floor_value
	if fraction > 0.5 or (fraction == 0.5 and fmod(floor_value, 2.0) != 0.0):
		floor_value += 1.0
	return floor_value


static func _gml_collision_bbox_gap(self_state, other_state):
	var xd = 0.0
	var yd = 0.0
	if other_state["left"] > self_state["right"]:
		xd = other_state["left"] - self_state["right"]
	if other_state["right"] < self_state["left"]:
		xd = other_state["right"] - self_state["left"]
	if other_state["top"] > self_state["bottom"]:
		yd = other_state["top"] - self_state["bottom"]
	if other_state["bottom"] < self_state["top"]:
		yd = other_state["bottom"] - self_state["top"]
	return sqrt(xd * xd + yd * yd)


# --- Collision sprites ---------------------------------------------------------

static func _gml_collision_sprite_data(sprite):
	if sprite == null or is_undefined(sprite):
		return null
	if _gml_collision_is_number(sprite) and _to_real(sprite) < 0.0:
		return null
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(sprite)
	if entry == null or str(entry.get("type", "")) != "sprite":
		return null
	var asset_id = int(entry["id"])
	var cached = _gml_collision_sprite_cache.get(asset_id, null)
	if cached != null and is_same(cached["entry"], entry):
		return cached["data"]
	var data = _gml_collision_build_sprite_data(entry)
	_gml_collision_sprite_cache[asset_id] = {"entry": entry, "data": data}
	return data


static func _gml_collision_build_sprite_data(entry):
	var resource = entry.get("resource", null)
	var godot_path = str(entry.get("godot_path", ""))
	if resource == null and godot_path != "" and ResourceLoader.exists(godot_path):
		resource = load(godot_path)
	var info = null
	if resource is PackedScene:
		info = _gml_collision_scene_info(resource.get_state())
	elif resource is Node:
		info = _gml_collision_node_info(resource)
	elif resource is Texture2D:
		var texture_size = resource.get_size()
		info = {"meta": {}, "rects": [], "frames": 1, "size": texture_size, "origin": texture_size * 0.5}
	if info == null:
		return null
	var registry_metadata = entry.get("metadata", {})
	if registry_metadata is Dictionary and registry_metadata.has("frame_count"):
		info["frames"] = max(int(_to_real(registry_metadata["frame_count"])), int(info["frames"]))
	if info["meta"].has("gamemaker_mask_frame_count"):
		info["frames"] = max(int(info["meta"]["gamemaker_mask_frame_count"]), int(info["frames"]))
	return _gml_collision_sprite_data_from_info(info)


static func _gml_collision_scene_info(state):
	var info = {"meta": {}, "rects": [], "frames": 0, "size": Vector2.ZERO, "origin": Vector2.ZERO}
	for node_index in range(state.get_node_count()):
		var properties = {}
		for property_index in range(state.get_node_property_count(node_index)):
			properties[str(state.get_node_property_name(node_index, property_index))] = state.get_node_property_value(node_index, property_index)
		if node_index == 0:
			for property_name in properties.keys():
				if str(property_name).begins_with("metadata/"):
					info["meta"][str(property_name).substr(9)] = properties[property_name]
			continue
		_gml_collision_info_add_node(info, str(state.get_node_type(node_index)), properties)
	return info


static func _gml_collision_node_info(root):
	var info = {"meta": {}, "rects": [], "frames": 0, "size": Vector2.ZERO, "origin": Vector2.ZERO}
	for meta_name in root.get_meta_list():
		info["meta"][str(meta_name)] = root.get_meta(meta_name)
	for child in root.get_children():
		var properties = {}
		for property in child.get_property_list():
			var property_name = str(property.get("name", ""))
			if property_name in ["position", "shape", "sprite_frames", "animation", "texture", "hframes", "vframes", "centered", "offset"]:
				properties[property_name] = child.get(property_name)
		for meta_name in child.get_meta_list():
			properties["metadata/" + str(meta_name)] = child.get_meta(meta_name)
		_gml_collision_info_add_node(info, child.get_class(), properties)
	return info


static func _gml_collision_info_add_node(info, node_type, properties):
	if properties.has("metadata/gamemaker_precise_mask"):
		var shape = properties.get("shape", null)
		if shape is RectangleShape2D:
			var center = properties.get("position", Vector2.ZERO)
			info["rects"].append({
				"x": center.x - shape.size.x * 0.5,
				"y": center.y - shape.size.y * 0.5,
				"w": shape.size.x,
				"h": shape.size.y,
				"frame": int(properties.get("metadata/gamemaker_mask_frame", -1)),
			})
		return
	if node_type == "AnimatedSprite2D":
		var frames = properties.get("sprite_frames", null)
		if frames is SpriteFrames:
			var animation = str(properties.get("animation", "default"))
			if not frames.has_animation(animation):
				animation = "default"
			if frames.has_animation(animation):
				info["frames"] = frames.get_frame_count(animation)
				var first_texture = frames.get_frame_texture(animation, 0) if info["frames"] > 0 else null
				if first_texture != null:
					info["size"] = first_texture.get_size()
					info["origin"] = info["size"] * 0.5 - properties.get("position", Vector2.ZERO)
	elif node_type == "Sprite2D":
		var texture = properties.get("texture", null)
		if texture is Texture2D:
			var hframes = max(int(properties.get("hframes", 1)), 1)
			var vframes = max(int(properties.get("vframes", 1)), 1)
			info["frames"] = hframes * vframes
			info["size"] = Vector2(texture.get_width() / float(hframes), texture.get_height() / float(vframes))
			var origin = -properties.get("position", Vector2.ZERO) - properties.get("offset", Vector2.ZERO)
			if bool(properties.get("centered", true)):
				origin += info["size"] * 0.5
			info["origin"] = origin


static func _gml_collision_sprite_data_from_info(info):
	var meta = info["meta"]
	var data = {}
	if meta.has("gamemaker_width") and meta.has("gamemaker_bbox_right"):
		data["width"] = int(meta["gamemaker_width"])
		data["height"] = int(meta.get("gamemaker_height", 0))
		data["xorigin"] = float(meta.get("gamemaker_origin_x", 0))
		data["yorigin"] = float(meta.get("gamemaker_origin_y", 0))
		data["left"] = int(meta.get("gamemaker_bbox_left", 0))
		data["top"] = int(meta.get("gamemaker_bbox_top", 0))
		data["right"] = int(meta.get("gamemaker_bbox_right", 0))
		data["bottom"] = int(meta.get("gamemaker_bbox_bottom", 0))
		data["kind"] = int(meta.get("gamemaker_collision_kind", 1))
	else:
		var size = info["size"]
		if size.x <= 0.0 or size.y <= 0.0:
			return null
		data["width"] = int(size.x)
		data["height"] = int(size.y)
		data["xorigin"] = float(info["origin"].x)
		data["yorigin"] = float(info["origin"].y)
		data["left"] = 0
		data["top"] = 0
		data["right"] = int(size.x) - 1
		data["bottom"] = int(size.y) - 1
		data["kind"] = 1
	data["numb"] = max(int(info["frames"]), 1)
	data["mask_width"] = max(data["right"] - data["left"] + 1, 0)
	data["mask_height"] = max(data["bottom"] - data["top"] + 1, 0)
	data["colcheck"] = GML_COLLISION_CHECK_AXIS_ALIGNED
	data["rects"] = info["rects"]
	var mask_count = 0
	var kind = int(data["kind"])
	if kind == 5:
		data["colcheck"] = GML_COLLISION_CHECK_ROTATED
	elif kind == 0 or kind == 2 or kind == 3 or kind == 4:
		data["colcheck"] = GML_COLLISION_CHECK_PRECISE
		if kind == 2 or kind == 3:
			mask_count = 1
		elif not info["rects"].is_empty():
			mask_count = 1
			if kind == 4:
				for rect in info["rects"]:
					if int(rect["frame"]) >= 0:
						mask_count = data["numb"]
						break
	data["mask_count"] = mask_count
	var masks = []
	masks.resize(mask_count)
	data["masks"] = masks
	return data


static func _gml_collision_frame_mask(data, image_index):
	var count = int(data["mask_count"])
	if count <= 0:
		return null
	var frame = int(image_index) % count
	if frame < 0:
		frame += count
	var mask = data["masks"][frame]
	if mask == null:
		mask = _gml_collision_build_mask(data, frame)
		data["masks"][frame] = mask
	return mask


static func _gml_collision_build_mask(data, frame):
	var mask_width = int(data["mask_width"])
	var mask_height = int(data["mask_height"])
	var mask = PackedByteArray()
	mask.resize(mask_width * mask_height)
	var kind = int(data["kind"])
	if kind == 2 or kind == 3:
		_gml_collision_fill_shape_mask(data, mask, kind == 2)
		return mask
	var per_frame = int(data["mask_count"]) > 1
	for rect in data["rects"]:
		if per_frame and int(rect["frame"]) != frame:
			continue
		var x0 = int(round(rect["x"] + data["xorigin"])) - int(data["left"])
		var y0 = int(round(rect["y"] + data["yorigin"])) - int(data["top"])
		var x1 = x0 + int(round(rect["w"]))
		var y1 = y0 + int(round(rect["h"]))
		for my in range(max(y0, 0), min(y1, mask_height)):
			var row = my * mask_width
			for mx in range(max(x0, 0), min(x1, mask_width)):
				mask[row + mx] = 1
	return mask


static func _gml_collision_fill_shape_mask(data, mask, ellipse):
	# Ellipse and diamond masks are built from the bounding box exactly like
	# GameMaker's TMaskCreate.
	var left = int(data["left"])
	var top = int(data["top"])
	var right = int(data["right"])
	var bottom = int(data["bottom"])
	var mask_width = int(data["mask_width"])
	var mid_x = float(left + right) / 2.0
	var dx = mid_x - left + 0.5
	var mid_y = float(top + bottom) / 2.0
	var dy = mid_y - top + 0.5
	if dx <= 0.0 or dy <= 0.0:
		return
	for py in range(top, bottom + 1):
		for px in range(left, right + 1):
			var u = (px - mid_x) / dx
			var v = (py - mid_y) / dy
			var inside = (u * u + v * v < 1.0) if ellipse else (abs(u) + abs(v) < 1.0)
			if inside:
				mask[(py - top) * mask_width + (px - left)] = 1


static func _gml_collision_mask_set(data, mask, u, v, floor_input):
	if mask == null:
		return true
	if not is_finite(u) or not is_finite(v):
		return false
	var iu = int(floor(u)) if floor_input else int(u)
	var iv = int(floor(v)) if floor_input else int(v)
	if iu < data["left"] or iu > data["right"]:
		return false
	if iv < data["top"] or iv > data["bottom"]:
		return false
	return mask[(iv - data["top"]) * data["mask_width"] + (iu - data["left"])] != 0


static func _gml_collision_state_image(state, use_floor):
	var value = state["inst"].get("image_index") if _gml_collision_instance_valid(state["inst"]) else null
	var image = _gml_collision_real_or(value, 0.0)
	if not is_finite(image):
		return 0
	return int(floor(image)) if use_floor else int(image)


# --- Collision primitives (one instance against a shape) ----------------------

static func _gml_collision_state_point(state, px, py, prec):
	if state == null:
		return false
	var col_delta = 1.0 if _gml_collision_compatibility() else -0.00001
	if px >= state["right"] + col_delta or px < state["left"]:
		return false
	if py >= state["bottom"] + col_delta or py < state["top"]:
		return false
	if state["colcheck"] == GML_COLLISION_CHECK_ROTATED and not _gml_collision_sat_point(state, px, py):
		return false
	var data = state["data"]
	if data == null:
		return false
	if not prec or state["colcheck"] == GML_COLLISION_CHECK_AXIS_ALIGNED:
		return true
	return _gml_collision_precise_point(state, _gml_collision_round(px), _gml_collision_round(py))


static func _gml_collision_state_rectangle(state, x1, y1, x2, y2, prec):
	if state == null:
		return false
	var compat = _gml_collision_compatibility()
	var col_delta = 1.0 if compat else 0.0
	var bl = min(x1, x2)
	var br = max(x1, x2)
	var bt = min(y1, y2)
	var bb = max(y1, y2)
	if bl >= state["right"] + col_delta or br < state["left"]:
		return false
	if bt >= state["bottom"] + col_delta or bb < state["top"]:
		return false
	if state["data"] == null:
		return false
	if state["colcheck"] == GML_COLLISION_CHECK_ROTATED and not _gml_collision_sat_box(state, x1, y1, x2, y2):
		return false
	if not prec or state["colcheck"] == GML_COLLISION_CHECK_AXIS_ALIGNED:
		if not compat:
			var l = max(bl, state["left"])
			var t = max(bt, state["top"])
			var r = min(br, state["right"])
			var b = min(bb, state["bottom"])
			if floor(l + 0.5) == floor(r + 0.5) or floor(t + 0.5) == floor(b + 0.5):
				return false
		return true
	var rect = {
		"left": _gml_collision_round(bl),
		"top": _gml_collision_round(bt),
		"right": _gml_collision_round(br),
		"bottom": _gml_collision_round(bb),
	}
	return _gml_collision_precise_rectangle(state, _gml_collision_state_image(state, true), _gml_collision_round(state["x"]), _gml_collision_round(state["y"]), rect)


static func _gml_collision_state_ellipse(state, x1, y1, x2, y2, prec):
	if state == null:
		return false
	if _gml_collision_compatibility():
		x1 = _gml_collision_round(x1)
		y1 = _gml_collision_round(y1)
		x2 = _gml_collision_round(x2)
		y2 = _gml_collision_round(y2)
	var min_x = min(x1, x2)
	var max_x = max(x1, x2)
	var min_y = min(y1, y2)
	var max_y = max(y1, y2)
	if min_x >= state["right"] or max_x < state["left"]:
		return false
	if min_y >= state["bottom"] or max_y < state["top"]:
		return false
	if x1 == x2 or y1 == y2:
		return _gml_collision_state_rectangle(state, x1, y1, x2, y2, prec)
	var cx = (x1 + x2) * 0.5
	var cy = (y1 + y2) * 0.5
	if not (state["left"] <= cx and state["right"] >= cx) and not (state["top"] <= cy and state["bottom"] >= cy):
		var px = state["right"] if state["right"] <= cx else state["left"]
		var py = state["bottom"] if state["bottom"] <= cy else state["top"]
		if not _gml_collision_point_in_ellipse(x1, y1, x2, y2, px, py):
			return false
	if state["data"] == null:
		return false
	if state["colcheck"] == GML_COLLISION_CHECK_ROTATED and not _gml_collision_sat_ellipse(state, x1, y1, x2, y2):
		return false
	if not prec or state["colcheck"] == GML_COLLISION_CHECK_AXIS_ALIGNED:
		return true
	var rect = {"left": min_x, "top": min_y, "right": max_x, "bottom": max_y}
	return _gml_collision_precise_ellipse(state, rect)


static func _gml_collision_point_in_ellipse(x1, y1, x2, y2, px, py):
	var mx = (x1 + x2) * 0.5
	var my = (y1 + y2) * 0.5
	var ww = (x2 - x1) * 0.5
	var hh = (y2 - y1) * 0.5
	var a = (px - mx) / ww
	var b = (py - my) / hh
	return a * a + b * b <= 1.0


static func _gml_collision_state_line(state, x1, y1, x2, y2, prec):
	if state == null:
		return false
	var compat = _gml_collision_compatibility()
	var box_delta = 1.0 if compat else 0.0
	if min(x1, x2) >= state["right"] + box_delta or max(x1, x2) < state["left"]:
		return false
	if min(y1, y2) >= state["bottom"] + box_delta or max(y1, y2) < state["top"]:
		return false
	# The runner clips against a right edge nudged inwards outside
	# compatibility mode.
	var col_delta = 1.0 if compat else -0.00001
	if x2 < x1:
		var swap_x = x2
		x2 = x1
		x1 = swap_x
		var swap_y = y2
		y2 = y1
		y1 = swap_y
	# Clip the segment to the box horizontally, then reject it when the
	# clipped part lies above or below the box.
	if x1 < state["left"]:
		y1 = y1 + (state["left"] - x1) * (y2 - y1) / (x2 - x1)
		x1 = state["left"]
	if x2 > state["right"] + col_delta:
		y2 = y2 + (state["right"] + col_delta - x2) * (y2 - y1) / (x2 - x1)
		x2 = state["right"] + col_delta
	if y1 < state["top"] and y2 < state["top"]:
		return false
	if compat:
		if y1 >= state["bottom"] + col_delta and y2 >= state["bottom"] + col_delta:
			return false
	elif y1 > state["bottom"] and y2 > state["bottom"]:
		return false
	if state["data"] == null:
		return false
	if state["colcheck"] == GML_COLLISION_CHECK_ROTATED and not _gml_collision_sat_line(state, x1, y1, x2, y2):
		return false
	if not prec or state["colcheck"] == GML_COLLISION_CHECK_AXIS_ALIGNED:
		return true
	return _gml_collision_precise_line(
		state,
		_gml_collision_round(x1),
		_gml_collision_round(y1),
		_gml_collision_round(x2),
		_gml_collision_round(y2)
	)


# One instance against another: `this_state` plays GameMaker's "this" and
# `other_state` the instance passed to Collision_Instance.
static func _gml_collision_states_collide(this_state, other_state, prec):
	if this_state == null or other_state == null:
		return false
	if this_state["inst"] == other_state["inst"]:
		return false
	var compat = _gml_collision_compatibility()
	var col_delta = 1.0 if compat else 0.0
	if other_state["left"] >= this_state["right"] + col_delta:
		return false
	if other_state["right"] + col_delta <= this_state["left"]:
		return false
	if other_state["top"] >= this_state["bottom"] + col_delta:
		return false
	if other_state["bottom"] + col_delta <= this_state["top"]:
		return false
	if this_state["colcheck"] == GML_COLLISION_CHECK_ROTATED or other_state["colcheck"] == GML_COLLISION_CHECK_ROTATED:
		if not _gml_collision_sat_check(_gml_collision_sat_points(this_state), _gml_collision_sat_points(other_state)):
			return false
	if this_state["data"] == null or other_state["data"] == null:
		return false
	var both_boxes = this_state["colcheck"] == GML_COLLISION_CHECK_AXIS_ALIGNED and other_state["colcheck"] == GML_COLLISION_CHECK_AXIS_ALIGNED
	if not prec or both_boxes:
		if not compat:
			var l = max(other_state["left"], this_state["left"])
			var t = max(other_state["top"], this_state["top"])
			var r = min(other_state["right"], this_state["right"])
			var b = min(other_state["bottom"], this_state["bottom"])
			if floor(l + 0.5) == floor(r + 0.5) or floor(t + 0.5) == floor(b + 0.5):
				return false
		return true
	if compat:
		return _gml_collision_precise_pair_compat(this_state, other_state)
	return _gml_collision_precise_pair(this_state, other_state)


# --- Separating axis tests for "rectangle with rotation" masks ---------------

static func _gml_collision_sat_points(state):
	# The four corners of the instance's rotated mask rectangle, shifted by
	# half a pixel like the GameMaker runner.
	var data = state["data"]
	if data == null:
		var px = state["x"]
		var py = state["y"]
		return [px, py, px, py, px, py, px, py]
	var xmin = state["xscale"] * (float(data["left"]) - data["xorigin"])
	var xmax = state["xscale"] * (float(data["right"]) - data["xorigin"] + 1.0)
	var ymin = state["yscale"] * (float(data["top"]) - data["yorigin"])
	var ymax = state["yscale"] * (float(data["bottom"]) - data["yorigin"] + 1.0)
	var radians = -state["angle"] * PI / 180.0
	var cc = cos(radians)
	var ss = sin(radians)
	var ix = state["x"] - 0.5
	var iy = state["y"] - 0.5
	return [
		ix + cc * xmin - ss * ymin, iy + cc * ymin + ss * xmin,
		ix + cc * xmax - ss * ymin, iy + cc * ymin + ss * xmax,
		ix + cc * xmax - ss * ymax, iy + cc * ymax + ss * xmax,
		ix + cc * xmin - ss * ymax, iy + cc * ymax + ss * xmin,
	]


static func _gml_collision_sat_axes(points):
	var axes = []
	for i in range(2):
		var ax = points[(i + 1) * 2] - points[i * 2]
		var ay = points[(i + 1) * 2 + 1] - points[i * 2 + 1]
		var length = sqrt(ax * ax + ay * ay)
		axes.append([-ay / length, ax / length])
	return axes


static func _gml_collision_sat_projection(points, axis):
	var lowest = INF
	var highest = -INF
	for i in range(0, points.size(), 2):
		var projection = points[i] * axis[0] + points[i + 1] * axis[1]
		lowest = min(lowest, projection)
		highest = max(highest, projection)
	return [lowest, highest]


static func _gml_collision_sat_gap(left_points, right_points, axis):
	var left_projection = _gml_collision_sat_projection(left_points, axis)
	var right_projection = _gml_collision_sat_projection(right_points, axis)
	return left_projection[1] <= right_projection[0] or right_projection[1] <= left_projection[0]


static func _gml_collision_sat_check(left_points, right_points):
	for axis in _gml_collision_sat_axes(left_points):
		if _gml_collision_sat_gap(left_points, right_points, axis):
			return false
	for axis in _gml_collision_sat_axes(right_points):
		if _gml_collision_sat_gap(left_points, right_points, axis):
			return false
	return true


static func _gml_collision_sat_point(state, px, py):
	var points = _gml_collision_sat_points(state)
	for axis in _gml_collision_sat_axes(points):
		var projection = _gml_collision_sat_projection(points, axis)
		var point_projection = px * axis[0] + py * axis[1]
		if projection[1] <= point_projection or point_projection <= projection[0]:
			return false
	return true


static func _gml_collision_sat_box(state, x1, y1, x2, y2):
	# The runner lists the box corners in this (non-perimeter) order, which
	# makes its second test axis a diagonal; kept for identical results.
	return _gml_collision_sat_check(_gml_collision_sat_points(state), [x1, y1, x2, y1, x1, y2, x2, y2])


static func _gml_collision_sat_line(state, x1, y1, x2, y2):
	var points = _gml_collision_sat_points(state)
	var line = [x1, y1, x2, y2]
	for axis in _gml_collision_sat_axes(points):
		if _gml_collision_sat_gap(points, line, axis):
			return false
	var dx = x2 - x1
	var dy = y2 - y1
	var length = sqrt(dx * dx + dy * dy)
	return not _gml_collision_sat_gap(points, line, [-dy / length, dx / length])


static func _gml_collision_sat_ellipse(state, x1, y1, x2, y2):
	# Scale x so the ellipse becomes a circle of radius ry, then test the
	# rectangle's axes against it.
	var rx = abs(x1 - x2) * 0.5
	var ry = abs(y1 - y2) * 0.5
	var sx = abs(ry / rx)
	var points = _gml_collision_sat_points(state)
	for i in range(4):
		points[i * 2] *= sx
	var cx = (x1 + x2) * 0.5 * sx
	var cy = (y1 + y2) * 0.5
	for axis in _gml_collision_sat_axes(points):
		var projection = _gml_collision_sat_projection(points, axis)
		var center_projection = cx * axis[0] + cy * axis[1]
		if projection[1] <= center_projection - ry or center_projection + ry <= projection[0]:
			return false
	return true


# --- Precise (per-pixel) tests -------------------------------------------------

static func _gml_collision_precise_point(state, px, py):
	var data = state["data"]
	if int(data["mask_count"]) <= 0:
		return true
	var mask = _gml_collision_frame_mask(data, _gml_collision_state_image(state, true))
	var x1 = _gml_collision_round(state["x"]) - 0.5
	var y1 = _gml_collision_round(state["y"]) - 0.5
	var xx = 0.0
	var yy = 0.0
	if abs(state["angle"]) < 0.0001:
		xx = (px - x1) / state["xscale"] + data["xorigin"]
		yy = (py - y1) / state["yscale"] + data["yorigin"]
	else:
		var radians = -state["angle"] * PI / 180.0
		var ss = sin(radians)
		var cc = cos(radians)
		xx = (cc * (px - x1) + ss * (py - y1)) / state["xscale"] + data["xorigin"]
		yy = (cc * (py - y1) - ss * (px - x1)) / state["yscale"] + data["yorigin"]
	return _gml_collision_mask_set(data, mask, xx, yy, true)


static func _gml_collision_precise_rectangle(state, image, x1, y1, rect):
	var data = state["data"]
	if int(data["mask_count"]) <= 0:
		return true
	var mask = _gml_collision_frame_mask(data, image)
	var l = max(state["left"], rect["left"])
	var r = min(state["right"], rect["right"])
	var t = max(state["top"], rect["top"])
	var b = min(state["bottom"], rect["bottom"])
	x1 -= 0.5
	y1 -= 0.5
	var width = float(data["width"])
	var height = float(data["height"])
	var unscaled = state["xscale"] == 1.0 and state["yscale"] == 1.0 and abs(state["angle"]) < 0.0001
	var radians = -state["angle"] * PI / 180.0
	var ss = sin(radians)
	var cc = cos(radians)
	var i = l
	while i <= r:
		var j = t
		while j <= b:
			var xx = 0.0
			var yy = 0.0
			if unscaled:
				xx = i - x1 + data["xorigin"]
				yy = j - y1 + data["yorigin"]
			else:
				xx = (cc * (i - x1) + ss * (j - y1)) / state["xscale"] + data["xorigin"]
				yy = (cc * (j - y1) - ss * (i - x1)) / state["yscale"] + data["yorigin"]
			if xx >= 0.0 and xx < width and yy >= 0.0 and yy < height:
				if _gml_collision_mask_set(data, mask, xx, yy, not unscaled):
					return true
			j += 1.0
		i += 1.0
	return false


static func _gml_collision_precise_ellipse(state, rect):
	var data = state["data"]
	if int(data["mask_count"]) <= 0:
		return true
	var mask = _gml_collision_frame_mask(data, _gml_collision_state_image(state, true))
	var x1 = _gml_collision_round(state["x"])
	var y1 = _gml_collision_round(state["y"])
	var l = max(state["left"], rect["left"])
	var r = min(state["right"], rect["right"])
	var t = max(state["top"], rect["top"])
	var b = min(state["bottom"], rect["bottom"])
	var mx = (rect["right"] + rect["left"]) / 2.0
	var my = (rect["bottom"] + rect["top"]) / 2.0
	var ww = 1.0 / ((rect["right"] - rect["left"]) / 2.0)
	var hh = 1.0 / ((rect["bottom"] - rect["top"]) / 2.0)
	var width = float(data["width"])
	var height = float(data["height"])
	var unscaled = state["xscale"] == 1.0 and state["yscale"] == 1.0 and abs(state["angle"]) < 0.0001
	var radians = -state["angle"] * PI / 180.0
	var ss = sin(radians)
	var cc = cos(radians)
	var i = l
	while i <= r:
		var tx = (i - mx) * ww
		var j = t
		while j <= b:
			var ty = (j - my) * hh
			if tx * tx + ty * ty <= 1.0:
				var xx = 0.0
				var yy = 0.0
				if unscaled:
					xx = i - x1 + data["xorigin"]
					yy = j - y1 + data["yorigin"]
				else:
					xx = (cc * (i - x1) + ss * (j - y1)) / state["xscale"] + data["xorigin"]
					yy = (cc * (j - y1) - ss * (i - x1)) / state["yscale"] + data["yorigin"]
				if xx >= 0.0 and xx < width and yy >= 0.0 and yy < height:
					if _gml_collision_mask_set(data, mask, xx, yy, false):
						return true
			j += 1.0
		i += 1.0
	return false


static func _gml_collision_precise_line(state, xl, yl, xr, yr):
	var data = state["data"]
	if int(data["mask_count"]) <= 0:
		return true
	var image = _gml_collision_state_image(state, false)
	var x1 = _gml_collision_round(state["x"])
	var y1 = _gml_collision_round(state["y"])
	if xl == xr or yl == yr:
		var rect = {"left": xl, "top": min(yl, yr), "right": xr, "bottom": max(yl, yr)}
		return _gml_collision_precise_rectangle(state, image, x1, y1, rect)
	var mask = _gml_collision_frame_mask(data, image)
	var radians = -state["angle"] * PI / 180.0
	var ss = sin(radians)
	var cc = cos(radians)
	x1 -= 0.5
	y1 -= 0.5
	if abs(xr - xl) >= abs(yr - yl):
		if xr < xl:
			var swap_x = xr
			xr = xl
			xl = swap_x
			var swap_y = yr
			yr = yl
			yl = swap_y
		var slope = (yr - yl) / (xr - xl)
		var i = max(state["left"], xl)
		while i <= min(state["right"], xr):
			var ly = yl + (i - xl) * slope
			var xx = (cc * (i - x1) + ss * (ly - y1)) / state["xscale"] + data["xorigin"]
			var yy = (cc * (ly - y1) - ss * (i - x1)) / state["yscale"] + data["yorigin"]
			if _gml_collision_mask_set(data, mask, xx, yy, true):
				return true
			i += 1.0
	else:
		if yr < yl:
			var swap_y2 = yr
			yr = yl
			yl = swap_y2
			var swap_x2 = xr
			xr = xl
			xl = swap_x2
		var inverse_slope = (xr - xl) / (yr - yl)
		var j = max(state["top"], yl)
		while j <= min(state["bottom"], yr):
			var lx = xl + (j - yl) * inverse_slope
			var xx2 = (cc * (lx - x1) + ss * (j - y1)) / state["xscale"] + data["xorigin"]
			var yy2 = (cc * (j - y1) - ss * (lx - x1)) / state["yscale"] + data["yorigin"]
			if _gml_collision_mask_set(data, mask, xx2, yy2, true):
				return true
			j += 1.0
	return false


static func _gml_collision_precise_edges(data):
	# A precise mask cannot reach outside the sprite image, so its edges are
	# clamped to the image; box masks may extend past it.
	var edges = [float(data["left"]), float(data["right"]) + 1.0, float(data["top"]), float(data["bottom"]) + 1.0]
	if data["colcheck"] == GML_COLLISION_CHECK_PRECISE:
		edges[0] = max(edges[0], 0.0)
		edges[1] = min(edges[1], float(data["width"]))
		edges[2] = max(edges[2], 0.0)
		edges[3] = min(edges[3], float(data["height"]))
	return edges


# How one instance samples its sprite during an instance/instance test.
static func _gml_collision_pixel_probe(state):
	var data = state["data"]
	if data == null or int(data["numb"]) <= 0:
		return null
	var angle = state["angle"]
	var radians = -angle * PI / 180.0
	return {
		"data": data,
		"mask": _gml_collision_frame_mask(data, _gml_collision_state_image(state, false)),
		"edges": _gml_collision_precise_edges(data),
		"x": _gml_collision_round(state["x"]),
		"y": _gml_collision_round(state["y"]),
		"inv_x": 1.0 / state["xscale"],
		"inv_y": 1.0 / state["yscale"],
		"xorigin": data["xorigin"],
		"yorigin": data["yorigin"],
		"rotated": angle > _gml_math_epsilon or angle < -_gml_math_epsilon,
		"ss": sin(radians),
		"cc": cos(radians),
		"precise": data["colcheck"] == GML_COLLISION_CHECK_PRECISE,
		"masked": int(data["mask_count"]) > 0,
	}


static func _gml_collision_probe_u_inside(probe, u):
	return u >= probe["edges"][0] and u < probe["edges"][1]


static func _gml_collision_probe_v_hit(probe, u, v):
	if v < probe["edges"][2] or v >= probe["edges"][3]:
		return false
	if probe["precise"] and probe["masked"]:
		return _gml_collision_mask_set(probe["data"], probe["mask"], u, v, false)
	return true


static func _gml_collision_probe_unrotated_row_hit(probe, u, j):
	# Without rotation the runner checks the rows of precise sprites only.
	if not probe["precise"]:
		return true
	return _gml_collision_probe_v_hit(probe, u, (j - probe["y"]) * probe["inv_y"] + probe["yorigin"])


static func _gml_collision_probe_column_open(probe, i):
	if probe["rotated"]:
		return true
	return _gml_collision_probe_u_inside(probe, (i - probe["x"]) * probe["inv_x"] + probe["xorigin"])


static func _gml_collision_probe_rotated_hit(probe, i, j):
	var dx = i - probe["x"]
	var dy = j - probe["y"]
	if not probe["rotated"]:
		return _gml_collision_probe_v_hit(probe, dx * probe["inv_x"] + probe["xorigin"], dy * probe["inv_y"] + probe["yorigin"])
	var u = (probe["cc"] * dx + probe["ss"] * dy) * probe["inv_x"] + probe["xorigin"]
	if not _gml_collision_probe_u_inside(probe, u):
		return false
	var v = (probe["cc"] * dy - probe["ss"] * dx) * probe["inv_y"] + probe["yorigin"]
	return _gml_collision_probe_v_hit(probe, u, v)


# Instance against instance with at least one precise mask: pixel centres of
# the overlapping boxes are mapped back into both sprites.
static func _gml_collision_precise_pair(first, second):
	var probe1 = _gml_collision_pixel_probe(first)
	var probe2 = _gml_collision_pixel_probe(second)
	if probe1 == null or probe2 == null:
		return false
	var l = floor(max(first["left"], second["left"])) + 0.5
	var r = min(first["right"], second["right"])
	var t = floor(max(first["top"], second["top"])) + 0.5
	var b = min(first["bottom"], second["bottom"])
	if not probe1["rotated"] and not probe2["rotated"]:
		return _gml_collision_precise_pair_unrotated(probe1, probe2, l, r, t, b)
	var i = l
	while i < r:
		if _gml_collision_probe_column_open(probe1, i) and _gml_collision_probe_column_open(probe2, i):
			var j = t
			while j < b:
				if _gml_collision_probe_rotated_hit(probe1, i, j) and _gml_collision_probe_rotated_hit(probe2, i, j):
					return true
				j += 1.0
		i += 1.0
	return false


static func _gml_collision_precise_pair_unrotated(probe1, probe2, l, r, t, b):
	var i = l
	while i < r:
		var u1 = (i - probe1["x"]) * probe1["inv_x"] + probe1["xorigin"]
		var u2 = (i - probe2["x"]) * probe2["inv_x"] + probe2["xorigin"]
		if _gml_collision_probe_u_inside(probe1, u1) and _gml_collision_probe_u_inside(probe2, u2):
			var j = t
			while j < b:
				if _gml_collision_probe_unrotated_row_hit(probe1, u1, j) and _gml_collision_probe_unrotated_row_hit(probe2, u2, j):
					return true
				j += 1.0
		i += 1.0
	return false


# The pre-2.3 version of the test above, used in collision compatibility
# mode: whole pixels of the inclusive boxes, without the half-pixel shift.
static func _gml_collision_precise_pair_compat(first, second):
	var data1 = first["data"]
	var data2 = second["data"]
	if int(data1["numb"]) <= 0 or int(data2["numb"]) <= 0:
		return false
	var mask1 = _gml_collision_frame_mask(data1, _gml_collision_state_image(first, false))
	var mask2 = _gml_collision_frame_mask(data2, _gml_collision_state_image(second, false))
	var x1 = _gml_collision_round(first["x"])
	var y1 = _gml_collision_round(first["y"])
	var x2 = _gml_collision_round(second["x"])
	var y2 = _gml_collision_round(second["y"])
	var inv1x = 1.0 / first["xscale"]
	var inv1y = 1.0 / first["yscale"]
	var inv2x = 1.0 / second["xscale"]
	var inv2y = 1.0 / second["yscale"]
	var l = max(first["left"], second["left"])
	var r = min(first["right"], second["right"])
	var t = max(first["top"], second["top"])
	var b = min(first["bottom"], second["bottom"])
	var plain = inv1x == 1.0 and inv2x == 1.0 and inv1y == 1.0 and inv2y == 1.0 and first["angle"] == 0.0 and second["angle"] == 0.0
	var radians1 = -first["angle"] * PI / 180.0
	var radians2 = -second["angle"] * PI / 180.0
	var ss1 = sin(radians1)
	var cc1 = cos(radians1)
	var ss2 = sin(radians2)
	var cc2 = cos(radians2)
	var i = l
	while i <= r:
		var j = t
		while j <= b:
			var u1 = (cc1 * (i - x1) + ss1 * (j - y1)) * inv1x + data1["xorigin"]
			var v1 = (cc1 * (j - y1) - ss1 * (i - x1)) * inv1y + data1["yorigin"]
			var u2 = (cc2 * (i - x2) + ss2 * (j - y2)) * inv2x + data2["xorigin"]
			var v2 = (cc2 * (j - y2) - ss2 * (i - x2)) * inv2y + data2["yorigin"]
			if first["angle"] == 0.0 and second["angle"] == 0.0:
				u1 = (i - x1) * inv1x + data1["xorigin"]
				v1 = (j - y1) * inv1y + data1["yorigin"]
				u2 = (i - x2) * inv2x + data2["xorigin"]
				v2 = (j - y2) * inv2y + data2["yorigin"]
			if _gml_collision_compat_pixel_hit(data1, mask1, u1, v1, not plain) and _gml_collision_compat_pixel_hit(data2, mask2, u2, v2, not plain):
				return true
			j += 1.0
		i += 1.0
	return false


static func _gml_collision_compat_pixel_hit(data, mask, u, v, floor_input):
	if u < 0.0 or u >= float(data["width"]) or v < 0.0 or v >= float(data["height"]):
		return false
	if int(data["mask_count"]) <= 0:
		return true
	return _gml_collision_mask_set(data, mask, u, v, floor_input)
