# --- GameMaker step loop: frame pump, image animation, and Other events ---
#
# The GMEvents autoload attaches the frame pump. Every Godot frame then runs
# one GameMaker tick: a step in GameMaker's phase order (see
# gml_event_scheduler_frame) and, when that step requested a room change, the
# room switch followed by the new room's step in the same tick. Draw events
# run only after a step that finished without a pending room change,
# game_restart or game_end.

const GML_STEP_MAX_STEPS_PER_TICK = 10
const GML_STEP_VIEW_COUNT = 8
const GML_STEP_DEFAULT_SPRITE_SPEED = 30.0

static var _gml_step_pump_attached = false
static var _gml_step_frame_drawable = true
static var _gml_step_other_event_handlers = {}


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


static func _gml_step_update_images(instances, frame):
	# GameMaker's RememberOldPositions/Animate followed by UpdateImages: every
	# instance stores xprevious/yprevious and advances image_index, then
	# image_index is wrapped into 0..image_number and Animation End runs for
	# each instance whose animation wrapped.
	var fps = gml_game_speed_fps()
	for inst in instances:
		if not _gml_event_scheduler_instance_valid(inst):
			continue
		_gml_step_remember_old_position(inst)
		_gml_step_animate_instance(inst, fps)
	for inst in instances:
		if _gml_event_scheduler_instance_valid(inst):
			_gml_step_wrap_image_index(inst, frame)
	return null


static func _gml_step_remember_old_position(inst):
	if inst.get("xprevious") == null or inst.get("yprevious") == null:
		return
	var position = _gml_instance_position(inst)
	inst.set("xprevious", position.x)
	inst.set("yprevious", position.y)


static func _gml_step_animate_instance(inst, fps):
	if not inst.has_method("_gm_apply_image_index"):
		return
	var image_speed = _to_real(inst.get("image_speed"))
	if image_speed == 0.0:
		return
	var increment = image_speed
	var animation = _gml_step_sprite_animation(inst.get("sprite_index"))
	if animation != null:
		# Same arithmetic as GameMaker: image_speed * (speed / game speed).
		var sprite_speed = _to_real(animation["speed"])
		if int(animation["speed_type"]) != 1:
			sprite_speed /= max(_to_real(fps), 1.0)
		increment = image_speed * sprite_speed
	if increment == 0.0:
		return
	inst.set("image_index", _to_real(inst.get("image_index")) + increment)


static func _gml_step_sprite_animation(sprite):
	# Playback settings of a sprite asset: {"speed", "speed_type"} where
	# speed_type 0 is frames per second and 1 is frames per game frame.
	# Returns null when there is no sprite.
	if sprite == null or sprite is GMLUndefined:
		return null
	if is_numeric(sprite) and _to_real(sprite) < 0.0:
		return null
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(sprite)
	if typeof(entry) != TYPE_DICTIONARY or str(entry.get("type", "")) != "sprite":
		return {"speed": GML_STEP_DEFAULT_SPRITE_SPEED, "speed_type": 0}
	var metadata = entry.get("metadata", {})
	if typeof(metadata) != TYPE_DICTIONARY or not metadata.has("playback_speed"):
		return {"speed": GML_STEP_DEFAULT_SPRITE_SPEED, "speed_type": 0}
	return {
		"speed": _to_real(metadata["playback_speed"]),
		"speed_type": int(_to_real(metadata.get("playback_speed_type", 0))),
	}


static func _gml_step_wrap_image_index(inst, frame):
	if not inst.has_method("_gm_apply_image_index"):
		return
	var image_number = int(_to_real(inst.get("image_number")))
	if image_number <= 0:
		return
	var image_index = _to_real(inst.get("image_index"))
	if image_index >= image_number:
		inst.set("image_index", image_index - image_number)
	elif image_index < 0.0:
		inst.set("image_index", image_index + image_number)
	else:
		return
	_gml_step_dispatch_other_event(inst, "animation", "_on_animation_end", frame)


static func _gml_step_dispatch_other_event(inst, phase, method_name, frame):
	if not inst.has_method(method_name):
		return false
	if _gml_event_scheduler_event_blocked(inst, true):
		return false
	_gml_event_scheduler_record_phase(phase, method_name, inst, frame)
	inst.call(method_name)
	return true


static func _gml_step_handle_other(instances, frame):
	# GameMaker's HandleOther, run after instances moved: Outside Room (once
	# when the instance leaves the room), Intersect Boundary, and the Outside
	# View / Intersect View Boundary events of visible views. Instances with a
	# collision mask are tested by their bounding box, others by x/y.
	_gml_event_scheduler_record_phase("other", "", null, frame)
	var room_size = Vector2(
		_to_real(_gml_builtin_globals.get("room_width", 0)),
		_to_real(_gml_builtin_globals.get("room_height", 0))
	)
	for inst in instances:
		if not _gml_event_scheduler_instance_valid(inst):
			continue
		var handlers = _gml_step_other_handlers(inst)
		if handlers.is_empty():
			continue
		var bounds = _gml_step_instance_bounds(inst)
		if handlers.has("outside_room"):
			var outside = _gml_step_outside_area(bounds, inst, Rect2(Vector2.ZERO, room_size))
			var previously_outside = bool(inst.get_meta("_gml_outside_room", false))
			inst.set_meta("_gml_outside_room", outside)
			if outside and not previously_outside:
				_gml_step_dispatch_other_event(inst, "other", "_on_outside_room", frame)
		if handlers.has("boundary") and _gml_step_bounds_cross_room_edge(bounds, inst, room_size):
			_gml_step_dispatch_other_event(inst, "other", "_on_intersect_boundary", frame)
		if handlers.has("views"):
			_gml_step_handle_view_events(inst, bounds, handlers["views"], frame)
	return null


static func _gml_step_handle_view_events(inst, bounds, view_handlers, frame):
	for view_index in view_handlers.keys():
		if not _gml_event_scheduler_instance_valid(inst):
			return
		var view_rect = _gml_step_view_rect(view_index)
		if view_rect == null:
			continue
		var handler_kinds = view_handlers[view_index]
		if handler_kinds.has("outside") and _gml_step_outside_area(bounds, inst, view_rect):
			_gml_step_dispatch_other_event(inst, "other", "_on_outside_view_" + str(view_index), frame)
		if handler_kinds.has("boundary") and bounds != null and _gml_step_bounds_cross_view_edge(bounds, view_rect):
			_gml_step_dispatch_other_event(inst, "other", "_on_intersect_view_" + str(view_index) + "_boundary", frame)


static func _gml_step_other_handlers(inst):
	var script = inst.get_script()
	var key = script.get_instance_id() if script != null else 0
	if _gml_step_other_event_handlers.has(key):
		return _gml_step_other_event_handlers[key]
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
	_gml_step_other_event_handlers[key] = handlers
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
