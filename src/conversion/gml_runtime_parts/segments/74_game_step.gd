# --- GameMaker step loop: frame pump, image animation, and Other events ---
#
# The GMEvents autoload attaches the frame pump. Every Godot frame then runs
# one GameMaker tick: a step in GameMaker's phase order (see
# gml_event_scheduler_frame) and, when that step requested a room change, the
# room switch followed by the new room's step in the same tick. Draw events
# run only after a step that finished without a pending room change,
# game_restart or game_end. A change requested by a Draw event is carried
# out right after the draw (gml_event_scheduler_after_draw), and the new room
# steps and draws in the same frame.
#
# A step works on one list of instances in creation order, like GameMaker's
# active instance list: instances created during a phase join it for the
# following phases, and destroyed instances are skipped. The list is kept
# from step to step; each step drops the instances destroyed since the last
# one and adds the ones created since. What the step needs to know about an
# object (which events it has, whether it has a sprite or motion runtime) is
# looked up once per script and kept in a GMLStepScriptInfo.

const GML_STEP_MAX_STEPS_PER_TICK = 10
const GML_STEP_VIEW_COUNT = 8
const GML_STEP_DEFAULT_SPRITE_SPEED = 30.0
# The built-ins the motion step reads; scripts that declare all of them can
# skip the motion step while the instance stands still.
const GML_STEP_MOTION_MEMBERS = ["hspeed", "vspeed", "speed", "friction", "gravity", "path_index"]

static var _gml_step_pump_attached = false
static var _gml_step_frame_drawable = true
# Room changes carried out after a draw in the current Godot frame.
static var _gml_step_redraw_frame = -1
static var _gml_step_redraws = 0
# The step's instances (instance registry entries, in creation order) and
# the GMLStepScriptInfo of each; _gml_step_creation_mark is the creation
# counter when the list last took in new instances, and
# _gml_step_removal_mark the number of instances unregistered when it last
# dropped the ones that are gone.
static var _gml_step_entries = []
static var _gml_step_infos = []
static var _gml_step_creation_mark = 0
static var _gml_step_removal_mark = 0
# The list positions of the instances whose script has an event method, by
# method name, for the methods _gml_step_dispatch_method runs. Each is
# worked out on the method's first dispatch and kept up to date as the list
# changes.
static var _gml_step_method_positions = {}
static var _gml_step_running = false
# GMLStepScriptInfo by script, or by class name for nodes without a script.
static var _gml_step_script_infos = {}
# [playback speed, speed type] by sprite reference, or false when the
# reference is not a sprite.
static var _gml_step_sprite_playback_cache = {}


class GMLStepScriptInfo:
	# The step-relevant members of one object script.
	var tracks_previous = false
	var animates = false
	var moves = false
	var motion_members = false
	var has_timeline = false
	var alarm_events = []
	var other_handlers = {}
	var input_events = {}
	# Whether the script has an event method, by method name; filled on
	# first use.
	var methods = {}


static func gml_event_scheduler_pump_attach():
	# Switches the runtime to GameMaker frame timing: input is latched at the
	# start of each step, room changes wait for a phase boundary, and async
	# events are delivered in the step's async phase.
	_gml_step_pump_attached = true
	gml_input_set_step_latching(true)
	gml_room_set_deferred_changes(true)
	return null


static func gml_event_scheduler_pump_detach():
	_gml_step_pump_attached = false
	_gml_step_frame_drawable = true
	gml_input_set_step_latching(false)
	gml_room_set_deferred_changes(false)
	return null


static func gml_event_scheduler_pump_attached():
	return _gml_step_pump_attached


static func gml_event_scheduler_game_frame(delta_seconds = 0.0):
	# One GameMaker tick. A room change requested outside a step (for example
	# by a Draw event or room creation code) happens before the step. After a
	# step that requested a room switch, the new room steps in the same tick,
	# up to GML_STEP_MAX_STEPS_PER_TICK steps. Returns the last change
	# performed ("", "room", "game_restart" or "game_end").
	_gml_step_frame_drawable = false
	var outcome = _gml_step_run_tick(max(_to_real(delta_seconds), 0.0))
	# Without the pump's step latching, input edges last one frame.
	gml_input_end_frame()
	return outcome


static func _gml_step_run_tick(seconds):
	var outcome = gml_room_apply_pending_change()
	if outcome == "game_end" or outcome == "game_restart":
		return outcome
	for _step in range(GML_STEP_MAX_STEPS_PER_TICK):
		gml_event_scheduler_frame(seconds, 1)
		# Repeated steps inside one tick do not advance real time.
		seconds = 0.0
		outcome = gml_room_apply_pending_change()
		if outcome == "":
			_gml_step_frame_drawable = true
			return outcome
		if outcome != "room":
			return outcome
	return outcome


static func gml_event_scheduler_frame_drawable():
	# False when the last tick ended without a finished step (room change
	# limit reached, game_restart or game_end): GameMaker skips Draw then.
	return _gml_step_frame_drawable


static func gml_event_scheduler_after_draw():
	# GameMaker draws at the end of the step, so a room change, game_restart
	# or game_end requested by a Draw event is carried out right after the
	# draw, and the new room steps and draws in the same frame. The draw pump
	# calls this after drawing; it returns whether to draw again.
	if not _gml_step_pump_attached or not gml_room_change_pending():
		return false
	var frame = Engine.get_process_frames()
	if frame != _gml_step_redraw_frame:
		_gml_step_redraw_frame = frame
		_gml_step_redraws = 0
	_gml_step_redraws += 1
	if _gml_step_redraws > GML_STEP_MAX_STEPS_PER_TICK:
		return false
	_gml_step_frame_drawable = false
	_gml_step_run_tick(0.0)
	return _gml_step_frame_drawable


static func gml_event_create_blocked(inst):
	# Generated Create events ask this first. Like GameMaker, an instance
	# created after a room change was requested gets no Create event unless
	# it or the current room is persistent; it still exists until the room
	# ends.
	return _gml_event_scheduler_event_blocked(inst, true)


static func gml_game_speed_fps():
	# The game speed in steps per second: room_speed once the game has set
	# it, otherwise the configured frame rate (option_game_speed).
	var room_speed = _to_real(_gml_builtin_globals.get("room_speed", 0))
	if room_speed > 0.0:
		return room_speed
	if Engine.max_fps > 0:
		return float(Engine.max_fps)
	var configured_fps = int(ProjectSettings.get_setting("application/run/max_fps", 0))
	if configured_fps > 0:
		return float(configured_fps)
	return 60.0


static func gml_image_frame_for_index(image_index, image_number):
	# The sub-image GameMaker shows for image_index: the integer part
	# (truncated toward zero) wrapped into 0..image_number-1.
	var count = int(_to_real(image_number))
	if count <= 0:
		return 0
	var frame_index = int(_to_real(image_index)) % count
	if frame_index < 0:
		frame_index += count
	return frame_index


static func gml_sprite_reference(sprite_name):
	# The sprite_index value of an object's own sprite: the sprite's asset
	# index, which is what sprite constants evaluate to in GML, or the name
	# itself when the asset registry does not list the sprite.
	var index = gml_asset_get_index(sprite_name)
	if is_numeric(index) and _to_real(index) >= 0.0:
		return index
	return str(sprite_name)


static func gml_sprite_asset_name(sprite):
	# The asset name of a sprite reference (asset index or name), or "" when
	# the value does not name a sprite.
	if sprite == null or sprite is GMLUndefined:
		return ""
	if is_string(sprite):
		return str(sprite)
	if not is_numeric(sprite) or _to_real(sprite) < 0.0:
		return ""
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(sprite)
	if typeof(entry) != TYPE_DICTIONARY or str(entry.get("type", "")) != "sprite":
		return ""
	return str(entry.get("name", ""))


static func _gml_step_script_info(inst):
	# The GMLStepScriptInfo of an instance's script, looked up once per script.
	var script = inst.get_script()
	var key = script if script != null else inst.get_class()
	var info = _gml_step_script_infos.get(key)
	if info != null:
		return info
	info = GMLStepScriptInfo.new()
	info.tracks_previous = "xprevious" in inst and "yprevious" in inst
	info.animates = inst.has_method("_gm_apply_image_index")
	info.moves = inst.has_method("_gm_apply_motion_step")
	info.motion_members = true
	for member in GML_STEP_MOTION_MEMBERS:
		if not (member in inst):
			info.motion_members = false
	info.has_timeline = "timeline_running" in inst
	for i in range(GML_ALARM_COUNT):
		if inst.has_method(GML_ALARM_EVENT_METHODS[i]):
			info.alarm_events.append(i)
	info.other_handlers = _gml_step_find_other_handlers(inst)
	info.input_events = _gml_input_read_event_bindings(inst)
	_gml_step_script_infos[key] = info
	return info


static func _gml_step_has_method(info, inst, method_name):
	var available = info.methods.get(method_name)
	if available == null:
		available = inst.has_method(method_name)
		info.methods[method_name] = available
	return available


static func _gml_step_collect_instances():
	# The instance list of a new step: the last step's instances that still
	# exist, then the instances created since. Creation order only grows, so
	# this is every live instance in creation order. Every phase passes over
	# instances that are gone, so the list only drops them after instances
	# were unregistered (registering counts up the creation counter and
	# unregistering shrinks the registry, so their difference grows with
	# every instance unregistered).
	var removal_mark = _gml_instance_creation_counter - _gml_instance_entries.size()
	if removal_mark != _gml_step_removal_mark:
		_gml_step_removal_mark = removal_mark
		_gml_step_drop_inactive()
	_gml_step_join_created_instances()
	_gml_step_running = true
	return null


static func _gml_step_drop_inactive():
	var entries = _gml_step_entries
	var infos = _gml_step_infos
	_gml_step_entries = []
	_gml_step_infos = []
	for method_name in _gml_step_method_positions.keys():
		_gml_step_method_positions[method_name] = []
	for i in range(entries.size()):
		if _gml_step_entry_active(entries[i]):
			_gml_step_append(entries[i], infos[i])
	return null


static func _gml_step_finish():
	_gml_step_running = false
	return null


static func _gml_step_add_entry(entry):
	var inst = entry["instance"]
	if typeof(inst) != TYPE_OBJECT or not is_instance_valid(inst) or inst.is_queued_for_deletion():
		return
	_gml_step_append(entry, _gml_step_script_info(inst))


static func _gml_step_append(entry, info):
	var position = _gml_step_entries.size()
	_gml_step_entries.append(entry)
	_gml_step_infos.append(info)
	for method_name in _gml_step_method_positions:
		if _gml_step_has_method(info, entry["instance"], method_name):
			_gml_step_method_positions[method_name].append(position)


static func _gml_step_join_created_instances():
	# Adds the instances created since the list was last updated, like
	# GameMaker's active list between phases.
	if _gml_instance_creation_counter == _gml_step_creation_mark:
		return null
	var created = []
	for entry in _gml_instance_entries.values():
		if int(entry["creation_order"]) >= _gml_step_creation_mark and not bool(entry["destroyed"]) and gml_handle_is_valid(entry["handle"]):
			created.append(entry)
	created.sort_custom(_gml_instance_entry_order_less)
	for entry in created:
		_gml_step_add_entry(entry)
	_gml_step_creation_mark = _gml_instance_creation_counter
	return null


static func _gml_step_entry_active(entry):
	# Whether a step list entry still takes part: not destroyed or freed.
	if bool(entry["destroyed"]):
		return false
	var inst = entry["instance"]
	return is_instance_valid(inst) and not inst.is_queued_for_deletion()


static func _gml_step_timeline_instances():
	var instances = []
	for i in range(_gml_step_entries.size()):
		if _gml_step_infos[i].has_timeline and _gml_step_entry_active(_gml_step_entries[i]):
			instances.append(_gml_step_entries[i]["instance"])
	return instances


static func _gml_step_dispatch_method(phase, method_name, frame):
	# Runs one event method for every instance of the step that has it, in
	# list order; instances that join the list during the phase wait for
	# the next phase.
	var positions = _gml_step_method_positions.get(method_name)
	if positions == null:
		positions = _gml_step_find_method_positions(method_name)
	for k in range(positions.size()):
		if _gml_room_requested_change != null:
			break
		var entry = _gml_step_entries[positions[k]]
		if bool(entry["destroyed"]):
			continue
		var inst = entry["instance"]
		if not is_instance_valid(inst) or inst.is_queued_for_deletion():
			continue
		if _gml_event_scheduler_tracing:
			_gml_event_scheduler_record_phase(phase, method_name, inst, frame)
		inst.call(method_name)
	return null


static func _gml_step_find_method_positions(method_name):
	var positions = []
	for i in range(_gml_step_entries.size()):
		var entry = _gml_step_entries[i]
		if _gml_step_entry_active(entry) and _gml_step_has_method(_gml_step_infos[i], entry["instance"], method_name):
			positions.append(i)
	_gml_step_method_positions[method_name] = positions
	return positions


static func _gml_step_tick_alarms(frames, frame):
	for _repeat in range(frames):
		for i in range(_gml_step_entries.size()):
			var alarm_events = _gml_step_infos[i].alarm_events
			if alarm_events.is_empty() or not _gml_step_entry_active(_gml_step_entries[i]):
				continue
			_gml_alarm_tick_instance(_gml_step_entries[i]["instance"], frame, alarm_events)
	return null


static func _gml_step_apply_motion(frame):
	# GameMaker's UpdateInstancePositions: friction, gravity, paths and speed
	# for every instance. This runs for every instance in every step, so the
	# checks are written out here.
	for i in range(_gml_step_entries.size()):
		var info = _gml_step_infos[i]
		if not info.moves:
			continue
		var entry = _gml_step_entries[i]
		var inst = entry["instance"]
		if entry["destroyed"] or not is_instance_valid(inst) or inst.is_queued_for_deletion():
			continue
		if info.motion_members and _gml_step_motion_idle(inst):
			continue
		if _gml_event_scheduler_tracing:
			_gml_event_scheduler_record_phase("motion", "_gm_apply_motion_step", inst, frame)
		inst._gm_apply_motion_step()
	return null


static func _gml_step_motion_idle(inst):
	# Whether UpdateInstancePositions would leave the instance alone: no
	# hspeed/vspeed, no gravity, no speed for friction to reduce, and no path
	# (path_index undefined or negative). Anything but plain numbers there
	# takes the full motion step. Each member is read once, without helper
	# calls: most instances stand still in most steps.
	var hspeed = inst.hspeed
	if not ((hspeed is float or hspeed is int) and hspeed == 0):
		return false
	var vspeed = inst.vspeed
	if not ((vspeed is float or vspeed is int) and vspeed == 0):
		return false
	var gravity = inst.gravity
	if not ((gravity is float or gravity is int) and gravity == 0):
		return false
	var path_index = inst.path_index
	if path_index is int or path_index is float:
		if path_index >= 0:
			return false
	elif not (path_index == null or path_index is GMLUndefined):
		return false
	var friction = inst.friction
	if (friction is float or friction is int) and friction == 0:
		return true
	var speed = inst.speed
	return (speed is float or speed is int) and speed == 0


static func _gml_step_update_images(frame):
	# GameMaker's RememberOldPositions/Animate followed by UpdateImages: every
	# instance stores xprevious/yprevious and advances image_index, then
	# image_index is wrapped into 0..image_number and Animation End runs for
	# each instance whose animation wrapped. This runs for every instance in
	# every step, so it reads the members directly.
	var fps = max(_gml_step_real(gml_game_speed_fps()), 1.0)
	var count = _gml_step_entries.size()
	# The positions of the instances that Animate left outside their frames.
	var outside = []
	for i in range(count):
		var info = _gml_step_infos[i]
		if not (info.tracks_previous or info.animates):
			continue
		var entry = _gml_step_entries[i]
		var inst = entry["instance"]
		if entry["destroyed"] or not is_instance_valid(inst) or inst.is_queued_for_deletion():
			continue
		if info.tracks_previous:
			# In the space of x and y, which the motion step and solid
			# rollback use too: an offset layer node does not move them.
			var position = inst.position if inst is Node2D and not _gml_sequence_instances_exist else _gml_instance_position(inst)
			inst.xprevious = position.x
			inst.yprevious = position.y
		if info.animates and _gml_step_animate_instance(inst, fps):
			outside.append(i)
	_gml_step_wrap_images(outside, count, frame)
	return null


static func _gml_step_wrap_images(outside, count, frame):
	# UpdateImages, in list order. No game code runs before the first
	# Animation End event, so until then only the instances Animate left
	# outside their frames can wrap; after it, every later instance is
	# looked at again.
	for i in outside:
		if _gml_step_wrap_entry(i, frame):
			for later in range(i + 1, count):
				_gml_step_wrap_entry(later, frame)
			return null
	return null


static func _gml_step_wrap_entry(i, frame):
	# Whether wrapping the instance at list position i ran its Animation End.
	var info = _gml_step_infos[i]
	if not info.animates:
		return false
	var entry = _gml_step_entries[i]
	var inst = entry["instance"]
	if entry["destroyed"] or not is_instance_valid(inst) or inst.is_queued_for_deletion():
		return false
	return _gml_step_wrap_image_index(inst, info, frame)


static func _gml_step_real(value):
	# _to_real for the common case of a member that already holds a number.
	if value is float:
		return value
	if value is int:
		return float(value)
	return _to_real(value)


static func _gml_step_animate_instance(inst, fps):
	# GameMaker's Animate; returns whether image_index is now outside the
	# sprite's frames, where UpdateImages wraps it.
	var image_speed = _gml_step_real(inst.image_speed)
	if image_speed != 0.0:
		var increment = image_speed
		var playback = _gml_step_sprite_playback(inst.sprite_index)
		if playback is Array:
			# Same arithmetic as GameMaker: image_speed * (speed / game speed),
			# or image_speed * speed for frames per game frame.
			increment = image_speed * (playback[0] if playback[1] == 1 else playback[0] / fps)
		if increment != 0.0:
			inst.image_index = _gml_step_real(inst.image_index) + increment
	var image_number = int(_gml_step_real(inst.image_number))
	if image_number <= 0:
		return false
	var image_index = _gml_step_real(inst.image_index)
	return image_index >= image_number or image_index < 0.0


static func _gml_step_sprite_playback(sprite):
	# [playback speed, speed type] of a sprite reference, where speed type 0
	# is frames per second and 1 frames per game frame; false when there is
	# no sprite. Sprites the registry does not describe play at 30 FPS.
	if sprite == null or sprite is GMLUndefined:
		return false
	var cached = _gml_step_sprite_playback_cache.get(sprite)
	if cached != null:
		return cached
	var playback = false
	if not (is_numeric(sprite) and _to_real(sprite) < 0.0):
		playback = [GML_STEP_DEFAULT_SPRITE_SPEED, 0]
		_gml_asset_registry_ensure_loaded()
		var entry = _gml_asset_resolve(sprite)
		if typeof(entry) == TYPE_DICTIONARY and str(entry.get("type", "")) == "sprite":
			var metadata = entry.get("metadata", {})
			if typeof(metadata) == TYPE_DICTIONARY and metadata.has("playback_speed"):
				playback = [
					_to_real(metadata["playback_speed"]),
					int(_to_real(metadata.get("playback_speed_type", 0))),
				]
	_gml_step_sprite_playback_cache[sprite] = playback
	return playback


static func _gml_step_wrap_image_index(inst, info, frame):
	# Whether the instance's Animation End event ran.
	var image_number = int(_gml_step_real(inst.image_number))
	if image_number <= 0:
		return false
	var image_index = _gml_step_real(inst.image_index)
	if image_index >= image_number:
		inst.image_index = image_index - image_number
	elif image_index < 0.0:
		inst.image_index = image_index + image_number
	else:
		return false
	if _gml_step_has_method(info, inst, &"_on_animation_end"):
		return _gml_step_dispatch_other_event(inst, "animation", &"_on_animation_end", frame)
	return false


static func _gml_step_dispatch_other_event(inst, phase, method_name, frame):
	if _gml_event_scheduler_event_blocked(inst, true):
		return false
	if _gml_event_scheduler_tracing:
		_gml_event_scheduler_record_phase(phase, method_name, inst, frame)
	inst.call(method_name)
	return true


static func _gml_step_handle_other(frame):
	# GameMaker's HandleOther, run after instances moved: Outside Room (once
	# when the instance leaves the room), Intersect Boundary, and, while the
	# room has views enabled, the Outside View / Intersect View Boundary
	# events of visible views. Instances with a collision mask are tested by
	# their bounding box, others by x/y.
	_gml_event_scheduler_record_phase("other", "", null, frame)
	var room_size = null
	var views_enabled = false
	for i in range(_gml_step_entries.size()):
		var handlers = _gml_step_infos[i].other_handlers
		if handlers.is_empty() or not _gml_step_entry_active(_gml_step_entries[i]):
			continue
		if room_size == null:
			room_size = Vector2(
				_to_real(_gml_builtin_globals.get("room_width", 0)),
				_to_real(_gml_builtin_globals.get("room_height", 0))
			)
			# Read once per step, like the runner's m_enableviews.
			views_enabled = gml_view_get_enabled()
		_gml_step_handle_other_instance(_gml_step_entries[i]["instance"], handlers, room_size, views_enabled, frame)
	return null


static func _gml_step_handle_other_instance(inst, handlers, room_size, views_enabled, frame):
	var bounds = _gml_step_instance_bounds(inst)
	if handlers.has("outside_room"):
		var outside = _gml_step_outside_area(bounds, inst, Rect2(Vector2.ZERO, room_size))
		var previously_outside = bool(inst.get_meta("_gml_outside_room", false))
		inst.set_meta("_gml_outside_room", outside)
		if outside and not previously_outside:
			_gml_step_dispatch_other_event(inst, "other", &"_on_outside_room", frame)
	# Like GameMaker, the instance's remaining Other events run even when an
	# earlier one destroyed it.
	if handlers.has("boundary") and is_instance_valid(inst) and _gml_step_bounds_cross_room_edge(bounds, inst, room_size):
		_gml_step_dispatch_other_event(inst, "other", &"_on_intersect_boundary", frame)
	if views_enabled and handlers.has("views"):
		_gml_step_handle_view_events(inst, bounds, handlers["views"], frame)


static func _gml_step_handle_view_events(inst, bounds, view_handlers, frame):
	for view_index in view_handlers.keys():
		if not is_instance_valid(inst):
			return
		var view_rect = _gml_step_view_rect(view_index)
		if view_rect == null:
			continue
		var handler_kinds = view_handlers[view_index]
		if handler_kinds.has("outside") and _gml_step_outside_area(bounds, inst, view_rect):
			_gml_step_dispatch_other_event(inst, "other", "_on_outside_view_" + str(view_index), frame)
		if handler_kinds.has("boundary") and bounds != null and _gml_step_bounds_cross_view_edge(bounds, view_rect):
			_gml_step_dispatch_other_event(inst, "other", "_on_intersect_view_" + str(view_index) + "_boundary", frame)


static func _gml_step_find_other_handlers(inst):
	# The Outside Room, Intersect Boundary and view events an object has.
	var handlers = {}
	if inst.has_method("_on_outside_room"):
		handlers["outside_room"] = true
	if inst.has_method("_on_intersect_boundary"):
		handlers["boundary"] = true
	var views = {}
	for view_index in range(GML_STEP_VIEW_COUNT):
		var kinds = []
		if inst.has_method("_on_outside_view_" + str(view_index)):
			kinds.append("outside")
		if inst.has_method("_on_intersect_view_" + str(view_index) + "_boundary"):
			kinds.append("boundary")
		if not kinds.is_empty():
			views[view_index] = kinds
	if not views.is_empty():
		handlers["views"] = views
	return handlers


static func _gml_step_instance_bounds(inst):
	# GameMaker's bbox as left/top/right/bottom with inclusive right and
	# bottom edges, or null when the instance has no collision mask.
	var bounds = null
	for polygon in _gml_collision_polygons_for_instance(inst, false):
		var rect = _gml_collision_polygon_bounds(polygon)
		if rect == null:
			continue
		bounds = rect if bounds == null else bounds.merge(rect)
	if bounds == null:
		return null
	return {
		"left": bounds.position.x,
		"top": bounds.position.y,
		"right": bounds.end.x - 1.0,
		"bottom": bounds.end.y - 1.0,
	}


static func _gml_step_outside_area(bounds, inst, area):
	if bounds == null:
		var position = _gml_instance_position(inst)
		return (
			position.x < area.position.x
			or position.x > area.end.x
			or position.y < area.position.y
			or position.y > area.end.y
		)
	return (
		bounds["right"] < area.position.x
		or bounds["left"] > area.end.x
		or bounds["bottom"] < area.position.y
		or bounds["top"] > area.end.y
	)


static func _gml_step_bounds_cross_room_edge(bounds, inst, room_size):
	if bounds == null:
		var position = _gml_instance_position(inst)
		return position.x < 0.0 or position.x > room_size.x or position.y < 0.0 or position.y > room_size.y
	return (
		bounds["left"] < 0.0
		or bounds["right"] > room_size.x
		or bounds["top"] < 0.0
		or bounds["bottom"] > room_size.y
	)


static func _gml_step_bounds_cross_view_edge(bounds, view_rect):
	var fully_outside = (
		bounds["right"] < view_rect.position.x
		or bounds["left"] > view_rect.end.x
		or bounds["bottom"] < view_rect.position.y
		or bounds["top"] > view_rect.end.y
	)
	if fully_outside:
		return false
	var fully_inside = (
		bounds["right"] < view_rect.end.x
		and bounds["left"] > view_rect.position.x
		and bounds["bottom"] < view_rect.end.y
		and bounds["top"] > view_rect.position.y
	)
	return not fully_inside


static func _gml_step_view_rect(view_index):
	if not gml_bool(gml_view_get_visible(view_index)):
		return null
	var camera = gml_view_get_camera(view_index)
	if is_numeric(camera) and _to_real(camera) < 0.0:
		return null
	return Rect2(
		_to_real(gml_camera_get_view_x(camera)),
		_to_real(gml_camera_get_view_y(camera)),
		_to_real(gml_camera_get_view_width(camera)),
		_to_real(gml_camera_get_view_height(camera))
	)
