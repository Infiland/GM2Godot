# --- Time: Alarms, Time Sources, Callbacks, and Scheduler ---

const GML_ALARM_COUNT = 12
# GameMaker's time-source values (HTML5 runner yyTime.js).
const GML_TIME_SOURCE_GLOBAL = 0
const GML_TIME_SOURCE_GAME = 1
const GML_TIME_SOURCE_CALL_LATER = 2
const GML_TIME_SOURCE_UNITS_SECONDS = 0
const GML_TIME_SOURCE_UNITS_FRAMES = 1
const GML_TIME_SOURCE_STATE_INITIAL = 0
const GML_TIME_SOURCE_STATE_ACTIVE = 1
const GML_TIME_SOURCE_STATE_PAUSED = 2
const GML_TIME_SOURCE_STATE_STOPPED = 3
const GML_TIME_SOURCE_EXPIRY_NEAREST = 0
const GML_TIME_SOURCE_EXPIRY_AFTER = 1
const GML_TIME_SOURCE_KIND_BASIC = 0
const GML_TIME_SOURCE_KIND_STATEFUL = 1
const GML_TIME_SOURCE_KIND_CONFIGURABLE = 2
const GML_TIME_SOURCE_KIND_SELF_DESTRUCTING = 3
const GML_TIME_SOURCE_HANDLE_KIND = "time_source"
# GameMaker's step order (HTML5 runner GameMaker_DoAStep): the input state is
# latched first, then every phase below runs for all instances. When an
# event requests a room change (room_goto and friends, room_restart,
# game_restart, game_end), no further step events run and the step stops
# after the current phase (motion and Other events count as one phase);
# Draw is skipped for that step.
const GML_EVENT_PHASE_ORDER = [
	"animation",
	"layers",
	"begin_step",
	"async",
	"timelines",
	"time_sources",
	"alarms",
	"keyboard",
	"mouse",
	"sequences",
	"step",
	"motion",
	"other",
	"collision",
	"end_step"
]
const GML_ALARM_EVENT_METHODS = [
	&"_on_alarm_0",
	&"_on_alarm_1",
	&"_on_alarm_2",
	&"_on_alarm_3",
	&"_on_alarm_4",
	&"_on_alarm_5",
	&"_on_alarm_6",
	&"_on_alarm_7",
	&"_on_alarm_8",
	&"_on_alarm_9",
	&"_on_alarm_10",
	&"_on_alarm_11",
]
# gml_event_scheduler_trace() returns at most this many of the latest records.
const GML_EVENT_SCHEDULER_TRACE_LIMIT = 1024

static var _gml_time_sources = _gml_time_source_builtins()
static var _gml_time_source_next_id = 3
static var _gml_time_source_listed = {GML_TIME_SOURCE_GLOBAL: true, GML_TIME_SOURCE_GAME: true}
static var _gml_event_scheduler_enabled = true
static var _gml_event_scheduler_frame_index = 0
# While tracing is on, the scheduler records every event it runs
# (gml_event_scheduler_trace), the input runtime every input event
# (gml_input_dispatch_trace), the collision runtime every collision event
# and solid move back (gml_collision_event_trace), the async runtime every
# async event it delivers (gml_async_event_log) and the room runtime every
# room change (gml_room_transition_log); each keeps only its latest records.
# Tracing is off by default: games run thousands of events per second,
# GameMaker keeps no such record, and only tests and debugging read them.
static var _gml_event_scheduler_tracing = false
static var _gml_event_scheduler_trace = []


static func gml_event_scheduler_set_enabled(enabled):
	_gml_event_scheduler_enabled = bool(enabled)
	return null


static func gml_event_scheduler_is_enabled():
	return _gml_event_scheduler_enabled


static func gml_event_scheduler_phase_order():
	return _gml_clone_value(GML_EVENT_PHASE_ORDER, 2)


static func gml_event_scheduler_set_tracing(enabled):
	_gml_event_scheduler_tracing = gml_bool(enabled)
	return null


static func gml_event_scheduler_tracing():
	return _gml_event_scheduler_tracing


static func gml_event_scheduler_trace():
	# The latest records, oldest first.
	var trace = _gml_event_scheduler_trace
	if trace.size() > GML_EVENT_SCHEDULER_TRACE_LIMIT:
		trace = trace.slice(trace.size() - GML_EVENT_SCHEDULER_TRACE_LIMIT)
	return _gml_clone_value(trace, 16)


static func gml_event_scheduler_trace_clear():
	_gml_event_scheduler_trace.clear()
	return null


static func gml_event_scheduler_frame(delta_seconds = 0.0, delta_frames = 1):
	# Runs one GameMaker step. Returns the step's frame number, or null when
	# the scheduler is disabled.
	if not _gml_event_scheduler_enabled:
		return null
	var frame = _gml_event_scheduler_frame_index
	_gml_event_scheduler_frame_index += 1
	var frames = max(1, int(delta_frames))
	var seconds = max(float(delta_seconds), 0.0)
	gml_input_begin_step()
	# The step's instance list; instances created by a phase join it before
	# the next phase (see 74_game_step.gd).
	_gml_step_collect_instances()
	for phase in GML_EVENT_PHASE_ORDER:
		_gml_event_scheduler_run_phase(phase, seconds, frames, frame)
		# GameMaker moves the instances and runs HandleOther before it looks
		# for a room change again, so a change requested by a Path End event
		# still lets persistent instances get their Outside Room events.
		if phase != "motion" and gml_room_change_pending():
			break
		_gml_step_join_created_instances()
	_gml_step_finish()
	return frame


static func _gml_event_scheduler_run_phase(phase, seconds, frames, frame):
	match phase:
		"animation":
			_gml_step_update_images(frame)
		"layers":
			_gml_layer_step_scroll()
		"begin_step":
			_gml_step_dispatch_method("begin_step", &"_on_begin_step", frame)
		"async":
			_gml_event_scheduler_record_phase("async", "", null, frame)
			gml_async_step_flush()
		"timelines":
			_gml_event_scheduler_record_phase("timelines", "", null, frame)
			gml_timeline_scheduler_frame(frames, _gml_step_timeline_instances())
		"time_sources":
			gml_time_source_step(_gml_builtin_globals.get("delta_time", 0))
			_gml_event_scheduler_record_phase("time_sources", "", null, frame)
		"alarms":
			_gml_step_tick_alarms(frames, frame)
		"keyboard":
			_gml_event_scheduler_record_phase("keyboard", "", null, frame)
			# Keyboard events for held keys, then pressed, then released keys.
			gml_input_dispatch_frame(null, [5, 9, 10])
		"mouse":
			_gml_event_scheduler_record_phase("mouse", "", null, frame)
			gml_input_dispatch_frame(null, [6, 13])
		"sequences":
			_gml_event_scheduler_record_phase("sequences", "", null, frame)
			# Sequences advance by their playback speed per step of game time.
			gml_sequence_scheduler_frame(1.0 / max(_to_real(gml_game_speed_fps()), 1.0), frames)
		"step":
			_gml_step_dispatch_method("step", &"_on_step", frame)
		"motion":
			_gml_step_apply_motion(frame)
		"other":
			_gml_step_handle_other(frame)
		"collision":
			# Every registered instance: the step's list holds the same ones
			# once the phases before have joined their new instances.
			gml_collision_event_dispatch_frame(null, frame)
		"end_step":
			_gml_step_dispatch_method("end_step", &"_on_end_step", frame)
	return null


static func gml_event_scheduler_dispatch_phase(phase, method_name, instances = null, frame = -1):
	var targets = instances if instances is Array else _gml_event_scheduler_live_instances()
	var method = StringName(str(method_name))
	for inst in targets:
		if gml_room_change_pending():
			break
		if not _gml_event_scheduler_instance_valid(inst):
			continue
		if inst.has_method(method):
			_gml_event_scheduler_record_phase(phase, method_name, inst, frame)
			inst.call(method)
	return null


static func gml_event_scheduler_tick_alarms(instances = null, delta_frames = 1, frame = -1):
	var targets = instances if instances is Array else _gml_event_scheduler_live_instances()
	var frames = max(1, int(delta_frames))
	for _frame in range(frames):
		for inst in targets:
			if _gml_event_scheduler_instance_valid(inst):
				_gml_alarm_tick_instance(inst, frame)
	return null


static func _gml_event_scheduler_event_blocked(inst, persistent_exempt = false):
	# Once a room change is pending, GameMaker runs no further events. Only
	# Create, Destroy, Alarm and Other events (persistent_exempt) still run
	# for persistent instances and for every instance of a persistent room.
	if not gml_room_change_pending():
		return false
	if not bool(persistent_exempt):
		return true
	return not (_gml_room_node_is_persistent(inst) or _gml_room_current_is_persistent())


static func gml_alarm_get(inst, index):
	var idx = int(index)
	if idx < 0 or idx >= GML_ALARM_COUNT:
		return -1
	if inst == null:
		return -1
	var alarms = _gml_alarm_array(inst)
	return alarms[idx]


static func gml_alarm_set(inst, index, value):
	var idx = int(index)
	if idx < 0 or idx >= GML_ALARM_COUNT:
		return
	if inst == null:
		return
	var alarms = _gml_alarm_array(inst)
	alarms[idx] = int(value)


static func gml_alarm_tick(inst, delta_frames):
	if inst == null:
		return
	var frames = max(1, int(delta_frames))
	for _frame in range(frames):
		_gml_alarm_tick_instance(inst, -1)


static func _gml_alarm_tick_instance(inst, frame, alarm_events = null):
	# Like GameMaker, only alarms that have an Alarm event count down. An
	# alarm runs its event in the step it reaches 0 and becomes -1 (inactive)
	# on the following step. alarm_events lists the alarm numbers the
	# instance's object has events for.
	var events = alarm_events if alarm_events is Array else _gml_step_script_info(inst).alarm_events
	if events.is_empty():
		return
	var alarms = _gml_alarm_array(inst)
	for i in events:
		if alarms[i] < 0:
			continue
		alarms[i] -= 1
		if alarms[i] == 0 and not _gml_event_scheduler_event_blocked(inst, true):
			var method_name = GML_ALARM_EVENT_METHODS[i]
			if _gml_event_scheduler_tracing:
				_gml_event_scheduler_record_phase("alarms", method_name, inst, frame)
			inst.call(method_name)


static func _gml_alarm_array(inst):
	if inst == null:
		return []
	if not inst.has_meta("_gml_alarms"):
		var alarms = []
		alarms.resize(GML_ALARM_COUNT)
		for i in range(GML_ALARM_COUNT):
			alarms[i] = -1
		inst.set_meta("_gml_alarms", alarms)
	return inst.get_meta("_gml_alarms")


static func _gml_event_scheduler_live_instances():
	var instances = []
	for entry in _gml_live_instance_entries():
		var inst = entry["instance"]
		if _gml_event_scheduler_instance_valid(inst):
			instances.append(inst)
	return instances


static func _gml_event_scheduler_instance_valid(inst):
	# Destroyed instances stop receiving events for the rest of the step.
	if inst == null or not is_instance_valid(inst):
		return false
	if inst is Node and inst.is_queued_for_deletion():
		return false
	var entry = _gml_instance_entry(inst)
	return entry == null or not bool(entry["destroyed"])


static func _gml_event_scheduler_record_phase(phase, method_name = "", inst = null, frame = -1):
	if not _gml_event_scheduler_tracing:
		return
	var entry = {
		"frame": frame,
		"phase": str(phase),
		"method": str(method_name),
		"instance": ""
	}
	if inst != null:
		entry["instance"] = str(inst.name) if inst is Node else str(inst)
	_gml_event_scheduler_trace.append(entry)
	# Trimmed in batches, so recording stays cheap.
	if _gml_event_scheduler_trace.size() >= GML_EVENT_SCHEDULER_TRACE_LIMIT * 2:
		_gml_event_scheduler_trace = _gml_event_scheduler_trace.slice(-GML_EVENT_SCHEDULER_TRACE_LIMIT)


# --- Time sources ---
#
# A port of GameMaker's time sources (HTML5 runner yyTime.js and
# Function_Time.js). Time sources form trees under three roots: the global
# source, the game source (which can be paused) and the invisible parent of
# the call_later sources. Every time source is a dictionary in
# _gml_time_sources by id; a tree links its sources by id in "children".
# The time_source_* functions find only the built-in global and game sources
# and the sources time_source_create made (GameMaker's g_TimeSourceMap).
# Seconds-based periods and times are kept in microseconds, frame-based ones
# in frames.


static func _gml_time_source_new(ts_id, kind):
	return {
		"id": ts_id,
		"kind": kind,
		"parent": -1,
		"children": [],
		"dt": 0.0,
		"state": GML_TIME_SOURCE_STATE_ACTIVE,
		"locked": false,
		"marked": false,
	}


static func _gml_time_source_builtins():
	return {
		GML_TIME_SOURCE_GLOBAL: _gml_time_source_new(GML_TIME_SOURCE_GLOBAL, GML_TIME_SOURCE_KIND_BASIC),
		GML_TIME_SOURCE_GAME: _gml_time_source_new(GML_TIME_SOURCE_GAME, GML_TIME_SOURCE_KIND_STATEFUL),
		GML_TIME_SOURCE_CALL_LATER: _gml_time_source_new(GML_TIME_SOURCE_CALL_LATER, GML_TIME_SOURCE_KIND_BASIC),
	}


static func gml_time_source_create(parent, period, units, callback, args = null, reps = 1, expiry_type = GML_TIME_SOURCE_EXPIRY_AFTER):
	var parent_source = _gml_time_source_find(parent)
	if parent_source == null:
		_gml_time_source_missing(parent)
		return -1
	var ts = _gml_time_source_add_child(
		parent_source,
		GML_TIME_SOURCE_KIND_CONFIGURABLE,
		[period, units, callback, [] if args == null else args, reps, expiry_type]
	)
	if ts == null:
		return -1
	_gml_time_source_listed[ts["id"]] = true
	return ts["handle"]


static func gml_call_later(period, units, callback, repeat = false):
	# A self-destructing time source: it starts at once, cannot be used with
	# the time_source_* functions and is removed after its last callback.
	var reps = -1 if gml_bool(repeat) else 1
	var ts = _gml_time_source_add_child(
		_gml_time_sources[GML_TIME_SOURCE_CALL_LATER],
		GML_TIME_SOURCE_KIND_SELF_DESTRUCTING,
		[period, units, callback, [], reps, GML_TIME_SOURCE_EXPIRY_AFTER]
	)
	if ts == null:
		return -1
	ts["state"] = GML_TIME_SOURCE_STATE_ACTIVE
	return ts["handle"]


static func gml_call_cancel(handle):
	var ts = _gml_time_source_find_below(
		_gml_time_sources[GML_TIME_SOURCE_CALL_LATER],
		_gml_time_source_id(handle)
	)
	if ts == null:
		return _gml_time_source_missing(handle)
	if not _gml_time_source_is_configurable(ts):
		return gml_error("Cannot destroy a built-in time source")
	if ts["locked"]:
		ts["marked"] = true
	else:
		_gml_time_source_destroy_now(ts)
	return null


static func gml_time_source_destroy(handle, destroy_tree = false):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if gml_bool(destroy_tree):
		_gml_time_source_unlist(ts)
		if _gml_time_source_find_locked(ts) != null:
			# A callback in the tree is running: the tree goes after it.
			_gml_time_source_mark(ts, true)
		else:
			_gml_time_source_destroy_now(ts)
		return null
	if not _gml_time_source_is_configurable(ts):
		return gml_error("Cannot destroy a built-in time source")
	if not ts["children"].is_empty():
		return gml_error(
			"Cannot destroy the time source (index " + str(ts["id"]) + ") until its children have been destroyed"
		)
	_gml_time_source_unlist(ts)
	if ts["locked"]:
		_gml_time_source_mark(ts, false)
	else:
		_gml_time_source_destroy_now(ts)
	return null


static func gml_time_source_start(handle):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if ts["kind"] == GML_TIME_SOURCE_KIND_BASIC:
		return gml_error("Cannot change the state of a stateless built-in time source")
	if _gml_time_source_is_configurable(ts) and ts["reps_remaining"] == 0:
		# It has run out: it restarts with the same configuration.
		ts["state"] = GML_TIME_SOURCE_STATE_INITIAL
		ts["t"] = 0.0
		ts["reps_remaining"] = ts["reps"]
	_gml_time_source_propagate_state(ts, GML_TIME_SOURCE_STATE_ACTIVE)
	return null


static func gml_time_source_stop(handle):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if not _gml_time_source_is_configurable(ts):
		return gml_error("Cannot stop a built-in time source")
	_gml_time_source_stop_tree(ts)
	return null


static func gml_time_source_pause(handle):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if ts["kind"] == GML_TIME_SOURCE_KIND_BASIC:
		return gml_error("Cannot change the state of a stateless built-in time source")
	_gml_time_source_switch_state(ts, GML_TIME_SOURCE_STATE_ACTIVE, GML_TIME_SOURCE_STATE_PAUSED)
	return null


static func gml_time_source_resume(handle):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if ts["kind"] == GML_TIME_SOURCE_KIND_BASIC:
		return gml_error("Cannot change the state of a stateless built-in time source")
	_gml_time_source_switch_state(ts, GML_TIME_SOURCE_STATE_PAUSED, GML_TIME_SOURCE_STATE_ACTIVE)
	return null


static func gml_time_source_reset(handle):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if not _gml_time_source_is_configurable(ts):
		return gml_error("Cannot reset a built-in time source")
	_gml_time_source_reset(ts)
	return null


static func gml_time_source_reconfigure(handle, period, units, callback, args = null, reps = 1, expiry_type = GML_TIME_SOURCE_EXPIRY_AFTER):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if not _gml_time_source_is_configurable(ts):
		return gml_error("Cannot reset a built-in time source")
	_gml_time_source_configure(ts, [period, units, callback, [] if args == null else args, reps, expiry_type])
	return null


static func gml_time_source_exists(handle):
	return _gml_time_source_find(handle) != null


static func gml_time_source_get_state(handle):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	if ts["kind"] == GML_TIME_SOURCE_KIND_BASIC:
		return gml_undefined()
	return ts["state"]


static func gml_time_source_get_period(handle):
	var ts = _gml_time_source_configurable(handle)
	if ts == null:
		return gml_undefined()
	return _gml_time_source_in_units(ts, ts["period"])


static func gml_time_source_get_units(handle):
	var ts = _gml_time_source_configurable(handle)
	if ts == null:
		return gml_undefined()
	return ts["units"]


static func gml_time_source_get_reps_completed(handle):
	var ts = _gml_time_source_configurable(handle)
	if ts == null:
		return gml_undefined()
	return ts["reps_completed"]


static func gml_time_source_get_reps_remaining(handle):
	var ts = _gml_time_source_configurable(handle)
	if ts == null:
		return gml_undefined()
	return ts["reps_remaining"]


static func gml_time_source_get_time_remaining(handle):
	var ts = _gml_time_source_configurable(handle)
	if ts == null:
		return gml_undefined()
	return _gml_time_source_in_units(ts, max(ts["period"] - ts["t"], 0.0))


static func gml_time_source_get_parent(handle):
	var ts = _gml_time_source_configurable(handle)
	if ts == null:
		return gml_undefined()
	return _gml_time_source_value(_gml_time_sources.get(ts["parent"]))


static func gml_time_source_get_children(handle):
	var ts = _gml_time_source_find(handle)
	if ts == null:
		return _gml_time_source_missing(handle)
	var children = []
	for child_id in ts["children"]:
		children.append(_gml_time_source_value(_gml_time_sources.get(child_id)))
	return children


static func gml_time_bpm_to_seconds(bpm):
	var value = _to_real(bpm)
	return 60.0 / value if value > 0.0 else INF


static func gml_time_seconds_to_bpm(seconds):
	var value = _to_real(seconds)
	return 60.0 / value if value > 0.0 else INF


static func gml_time_source_frame_tick(real_usec):
	# GameMaker_Tick: every frame the global source and the parent of the
	# call_later sources take the real time that passed, in microseconds.
	# They hand it on in the time-source phase of the next step.
	var elapsed = max(_to_real(real_usec), 0.0)
	_gml_time_sources[GML_TIME_SOURCE_GLOBAL]["dt"] += elapsed
	_gml_time_sources[GML_TIME_SOURCE_CALL_LATER]["dt"] += elapsed
	return null


static func gml_time_source_step(game_usec):
	# HandleTimeSources: first every time source takes the time that passed
	# (the game source the step's delta_time), then the time sources that
	# expired run their callbacks, global ones first. A time source created
	# by a callback took no time yet, so it does not expire in this step.
	var global_source = _gml_time_sources[GML_TIME_SOURCE_GLOBAL]
	var call_later_source = _gml_time_sources[GML_TIME_SOURCE_CALL_LATER]
	var game_source = _gml_time_sources[GML_TIME_SOURCE_GAME]
	_gml_time_source_tick_children(global_source)
	_gml_time_source_tick_children(call_later_source)
	game_source["dt"] += max(_to_real(game_usec), 0.0)
	_gml_time_source_tick_children(game_source)
	_gml_time_source_check_children(global_source)
	_gml_time_source_check_children(call_later_source)
	_gml_time_source_check_children(game_source)
	return null


static func gml_time_source_clear_call_later():
	# game_restart removes every pending call_later source.
	_gml_time_source_destroy_now(_gml_time_sources[GML_TIME_SOURCE_CALL_LATER])
	return null


static func _gml_time_source_shutdown():
	# Releases the callbacks; their bound instances may be freed already.
	_gml_time_sources = _gml_time_source_builtins()
	_gml_time_source_listed = {GML_TIME_SOURCE_GLOBAL: true, GML_TIME_SOURCE_GAME: true}
	return null


static func _gml_time_source_tick(ts, dt):
	# A configurable source counts the time only while it is active: seconds
	# as microseconds, frames as one per step.
	ts["dt"] = dt
	if ts["state"] == GML_TIME_SOURCE_STATE_ACTIVE:
		ts["t"] += dt if ts["units"] == GML_TIME_SOURCE_UNITS_SECONDS else 1.0
	_gml_time_source_tick_children(ts)


static func _gml_time_source_tick_children(ts):
	var dt = ts["dt"]
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			_gml_time_source_tick(child, dt)
	ts["dt"] = 0.0


static func _gml_time_source_check(ts):
	# GameMaker also lets a seconds-based time_source_expire_nearest source
	# expire a step early, by the time the source took in this step; by then
	# that time has been handed on to its children and is 0, so it expires
	# when its period has passed, like time_source_expire_after.
	if ts["state"] == GML_TIME_SOURCE_STATE_ACTIVE and ts["t"] >= ts["period"]:
		_gml_time_source_expire(ts)
	_gml_time_source_check_children(ts)


static func _gml_time_source_check_children(ts):
	# Over a copy of the children: a callback can create and destroy time
	# sources. A child destroyed by a sibling is skipped, and a child marked
	# for destruction (during its own callback, or a call_later source that
	# ran out) is removed after its check.
	for child_id in ts["children"].slice(0):
		if not ts["children"].has(child_id):
			continue
		var child = _gml_time_sources.get(child_id)
		if child == null:
			continue
		if not child["marked"]:
			_gml_time_source_check(child)
		if child["marked"]:
			_gml_time_source_remove_child(ts, child)


static func _gml_time_source_expire(ts):
	ts["reps_completed"] += 1
	if ts["reps_remaining"] > 0:
		ts["reps_remaining"] -= 1
	if ts["reps_remaining"] == 0:
		ts["t"] = ts["period"]
		if ts["kind"] == GML_TIME_SOURCE_KIND_SELF_DESTRUCTING:
			ts["marked"] = true
		else:
			ts["state"] = GML_TIME_SOURCE_STATE_STOPPED
	else:
		# The time past the period carries over to the next repetition.
		ts["t"] = fmod(ts["t"], ts["period"])
	var callback = ts["callback"]
	if callback == null:
		return
	# Callbacks run with global as self and other; a method keeps its own
	# self.
	ts["locked"] = true
	gml_call_value(callback, ts["args"], _gml_global_scope, _gml_global_scope)
	ts["locked"] = false


static func _gml_time_source_add_child(parent, kind, configuration):
	var ts = _gml_time_source_new(_gml_time_source_next_id, kind)
	if not _gml_time_source_configure(ts, configuration):
		return null
	_gml_time_source_next_id += 1
	ts["parent"] = parent["id"]
	ts["handle"] = _gml_make_handle(GML_TIME_SOURCE_HANDLE_KIND, ts["id"], ts["id"], "", true)
	_gml_time_sources[ts["id"]] = ts
	parent["children"].append(ts["id"])
	return ts


static func _gml_time_source_configure(ts, configuration):
	# CConfigurableTimeSource.Reconfigure: [period, units, callback, args,
	# repetitions, expiry type]; it resets the source.
	var period = _to_real(configuration[0])
	var units = int(_to_real(configuration[1]))
	var callback = configuration[2]
	var args = configuration[3]
	var reps = int(_to_real(configuration[4]))
	var expiry_type = int(_to_real(configuration[5]))
	if units != GML_TIME_SOURCE_UNITS_SECONDS and units != GML_TIME_SOURCE_UNITS_FRAMES:
		gml_error("Illegal time source unit type: " + str(units))
		return false
	if not _gml_time_source_callable(callback):
		gml_error("Time source callback must be a method or function")
		return false
	if typeof(args) != TYPE_ARRAY:
		gml_error("Time source callback arguments must be an array")
		return false
	if reps < -1:
		gml_error("Illegal time source repetition value: " + str(reps))
		return false
	if expiry_type != GML_TIME_SOURCE_EXPIRY_NEAREST and expiry_type != GML_TIME_SOURCE_EXPIRY_AFTER:
		gml_error("Illegal time source expiry type: " + str(expiry_type))
		return false
	# Seconds are counted in whole microseconds (at least 1) and frames in
	# whole frames (at least 1).
	ts["period"] = (
		floor(max(period, 0.000001) * 1000000.0)
		if units == GML_TIME_SOURCE_UNITS_SECONDS
		else floor(max(period, 1.0))
	)
	ts["units"] = units
	ts["callback"] = callback
	ts["args"] = args.slice(0)
	ts["reps"] = reps
	ts["expiry_type"] = expiry_type
	_gml_time_source_reset(ts)
	return true


static func _gml_time_source_reset(ts):
	_gml_time_source_propagate_state(ts, GML_TIME_SOURCE_STATE_INITIAL)
	ts["t"] = 0.0
	ts["reps_remaining"] = ts["reps"]
	ts["reps_completed"] = 0


static func _gml_time_source_callable(callback):
	if is_method(callback):
		return true
	if typeof(callback) == TYPE_DICTIONARY:
		return callback.has("callable")
	return (is_numeric(callback) or is_handle(callback)) and _gml_script_resolve(callback) != null


static func _gml_time_source_propagate_state(ts, state):
	ts["state"] = state
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			_gml_time_source_propagate_state(child, state)


static func _gml_time_source_switch_state(ts, from_state, to_state):
	# Pause and resume: the source and every source below it that is in
	# from_state.
	if ts["state"] == from_state:
		ts["state"] = to_state
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			_gml_time_source_switch_state(child, from_state, to_state)


static func _gml_time_source_stop_tree(ts):
	# A source that was started and has not run out stops and starts over.
	if ts["state"] != GML_TIME_SOURCE_STATE_INITIAL and ts["reps_remaining"] != 0:
		ts["state"] = GML_TIME_SOURCE_STATE_STOPPED
		ts["t"] = 0.0
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			_gml_time_source_stop_tree(child)


static func _gml_time_source_mark(ts, mark_children):
	# Marked sources are removed by their parent once their callback ended.
	if _gml_time_source_is_configurable(ts):
		ts["marked"] = true
	if not mark_children:
		return
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			_gml_time_source_mark(child, true)


static func _gml_time_source_destroy_now(ts):
	# A built-in source loses all its children; any other source is removed
	# from its parent.
	if not _gml_time_source_is_configurable(ts):
		for child_id in ts["children"]:
			_gml_time_source_forget(child_id)
		ts["children"] = []
		return
	var parent = _gml_time_sources.get(ts["parent"])
	if parent != null:
		_gml_time_source_remove_child(parent, ts)


static func _gml_time_source_remove_child(parent, child):
	parent["children"].erase(child["id"])
	_gml_time_source_forget(child["id"])


static func _gml_time_source_forget(ts_id):
	# Drops a removed source and its whole tree.
	var ts = _gml_time_sources.get(ts_id)
	if ts == null:
		return
	for child_id in ts["children"]:
		_gml_time_source_forget(child_id)
	# Its handle no longer refers to a time source.
	if ts.has("handle"):
		ts["handle"].valid = false
	_gml_time_sources.erase(ts_id)
	_gml_time_source_listed.erase(ts_id)


static func _gml_time_source_unlist(ts):
	# EraseFromMap: the time_source_* functions no longer find the source or
	# any source below it; the built-in sources stay.
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			_gml_time_source_unlist(child)
	if _gml_time_source_is_configurable(ts):
		_gml_time_source_listed.erase(ts["id"])


static func _gml_time_source_find_locked(ts):
	# The source of the tree whose callback is running, if any.
	if ts["locked"]:
		return ts
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			var locked = _gml_time_source_find_locked(child)
			if locked != null:
				return locked
	return null


static func _gml_time_source_find_below(ts, ts_id):
	# The source with the id in the tree of ts, ts included.
	if ts["id"] == ts_id:
		return ts
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if child != null:
			var found = _gml_time_source_find_below(child, ts_id)
			if found != null:
				return found
	return null


static func _gml_time_source_is_configurable(ts):
	return (
		ts["kind"] == GML_TIME_SOURCE_KIND_CONFIGURABLE
		or ts["kind"] == GML_TIME_SOURCE_KIND_SELF_DESTRUCTING
	)


static func _gml_time_source_configurable(handle):
	# The configurable source a getter asks about, or null: undefined for a
	# built-in source, and an error as well when it does not exist.
	var ts = _gml_time_source_find(handle)
	if ts == null:
		_gml_time_source_missing(handle)
		return null
	return ts if _gml_time_source_is_configurable(ts) else null


static func _gml_time_source_in_units(ts, value):
	if ts["units"] == GML_TIME_SOURCE_UNITS_SECONDS:
		return value / 1000000.0
	return value


static func _gml_time_source_value(ts):
	# The GML value of a time source: the number of a built-in one, the
	# handle of any other.
	if ts == null:
		return gml_undefined()
	return ts["handle"] if ts.has("handle") else ts["id"]


static func _gml_time_source_id(value):
	if is_handle(value):
		return value.index if value.kind == GML_TIME_SOURCE_HANDLE_KIND else -1
	if is_numeric(value):
		return int(_to_real(value))
	return -1


static func _gml_time_source_find(value):
	# GetTimeSourceWithId.
	var ts_id = _gml_time_source_id(value)
	if not _gml_time_source_listed.has(ts_id):
		return null
	return _gml_time_sources.get(ts_id)


static func _gml_time_source_missing(value):
	return gml_error("Index " + gml_string(value) + " does not correspond to an existing time source")
