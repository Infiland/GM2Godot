# --- Time: Alarms, Time Sources, Callbacks, and Scheduler ---

const GML_ALARM_COUNT = 12
const GML_TIME_SOURCE_UNITS_FRAMES = 0
const GML_TIME_SOURCE_UNITS_SECONDS = 1
const GML_TIME_SOURCE_STATE_INITIAL = 0
const GML_TIME_SOURCE_STATE_ACTIVE = 1
const GML_TIME_SOURCE_STATE_PAUSED = 2
const GML_TIME_SOURCE_STATE_STOPPED = 3
const GML_TIME_SOURCE_EXPIRY_AFTER = 0
const GML_TIME_SOURCE_EXPIRY_NEAREST = 1
const GML_TIME_SOURCE_HANDLE_KIND = "time_source"
const GML_EVENT_PHASE_ORDER = [
	"begin_step",
	"time_sources",
	"alarms",
	"step",
	"motion",
	"collision",
	"end_step"
]

static var _gml_time_sources = {}
static var _gml_time_source_next_id = 1
static var _gml_event_scheduler_enabled = true
static var _gml_event_scheduler_frame_index = 0
static var _gml_event_scheduler_trace = []


static func gml_event_scheduler_set_enabled(enabled):
	_gml_event_scheduler_enabled = bool(enabled)
	return null


static func gml_event_scheduler_is_enabled():
	return _gml_event_scheduler_enabled


static func gml_event_scheduler_phase_order():
	return _gml_clone_value(GML_EVENT_PHASE_ORDER, 2)


static func gml_event_scheduler_trace():
	return _gml_clone_value(_gml_event_scheduler_trace, 16)


static func gml_event_scheduler_trace_clear():
	_gml_event_scheduler_trace.clear()
	return null


static func gml_event_scheduler_frame(delta_seconds = 0.0, delta_frames = 1):
	if not _gml_event_scheduler_enabled:
		return null
	var frame = _gml_event_scheduler_frame_index
	_gml_event_scheduler_frame_index += 1
	var frames = max(1, int(delta_frames))
	var seconds = float(delta_seconds)
	gml_event_scheduler_dispatch_phase("begin_step", "_on_begin_step", _gml_event_scheduler_live_instances(), frame)
	gml_time_source_tick_all(seconds, frames)
	_gml_event_scheduler_record_phase("time_sources", "", null, frame)
	gml_event_scheduler_tick_alarms(_gml_event_scheduler_live_instances(), frames, frame)
	gml_sequence_timeline_scheduler_frame(
		seconds,
		frames,
		_gml_event_scheduler_live_instances(),
		frame
	)
	gml_event_scheduler_dispatch_phase("step", "_on_step", _gml_event_scheduler_live_instances(), frame)
	_gml_event_scheduler_dispatch_motion(_gml_event_scheduler_live_instances(), frame)
	gml_collision_event_dispatch_frame(_gml_event_scheduler_live_instances(), frame)
	gml_event_scheduler_dispatch_phase("end_step", "_on_end_step", _gml_event_scheduler_live_instances(), frame)
	return frame


static func gml_event_scheduler_dispatch_phase(phase, method_name, instances = null, frame = -1):
	var targets = instances if instances is Array else _gml_event_scheduler_live_instances()
	for inst in targets:
		if not _gml_event_scheduler_instance_valid(inst):
			continue
		if inst.has_method(str(method_name)):
			_gml_event_scheduler_record_phase(phase, method_name, inst, frame)
			inst.call(str(method_name))
	return null


static func gml_event_scheduler_tick_alarms(instances = null, delta_frames = 1, frame = -1):
	var targets = instances if instances is Array else _gml_event_scheduler_live_instances()
	var frames = max(1, int(delta_frames))
	for _frame in range(frames):
		for inst in targets:
			if _gml_event_scheduler_instance_valid(inst):
				_gml_alarm_tick_instance(inst, frame)
	return null


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


static func _gml_alarm_tick_instance(inst, frame):
	var alarms = _gml_alarm_array(inst)
	for i in range(GML_ALARM_COUNT):
		if alarms[i] < 0:
			continue
		if alarms[i] == 0:
			alarms[i] = -1
			continue
		alarms[i] -= 1
		if alarms[i] == 0:
			var method_name = "_on_alarm_" + str(i)
			if inst.has_method(method_name):
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


static func _gml_event_scheduler_dispatch_motion(instances, frame):
	for inst in instances:
		if not _gml_event_scheduler_instance_valid(inst):
			continue
		if inst.has_method("_gm_apply_motion_step"):
			_gml_event_scheduler_record_phase("motion", "_gm_apply_motion_step", inst, frame)
			inst.call("_gm_apply_motion_step")
	return null


static func _gml_event_scheduler_live_instances():
	var instances = []
	for entry in _gml_live_instance_entries():
		var inst = entry["instance"]
		if _gml_event_scheduler_instance_valid(inst):
			instances.append(inst)
	return instances


static func _gml_event_scheduler_instance_valid(inst):
	return inst != null and is_instance_valid(inst)


static func _gml_event_scheduler_record_phase(phase, method_name = "", inst = null, frame = -1):
	var entry = {
		"frame": frame,
		"phase": str(phase),
		"method": str(method_name),
		"instance": ""
	}
	if inst != null:
		entry["instance"] = str(inst.name) if inst is Node else str(inst)
	_gml_event_scheduler_trace.append(entry)


static func gml_time_source_create(parent, period, units, callback, args = null, reps = 1, expiry_type = 0):
	var ts_id = _gml_time_source_next_id
	_gml_time_source_next_id += 1
	var handle = gml_handle_register(GML_TIME_SOURCE_HANDLE_KIND, ts_id)
	var ts = {
		"id": ts_id,
		"handle": handle,
		"parent": parent,
		"period": _to_real(period),
		"units": int(units),
		"callback": callback,
		"args": args if args != null else [],
		"reps": int(reps),
		"expiry_type": int(expiry_type),
		"state": GML_TIME_SOURCE_STATE_INITIAL,
		"elapsed": 0.0,
		"reps_done": 0,
		"children": [],
	}
	_gml_time_sources[ts_id] = ts
	return handle


static func gml_time_source_start(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return
	ts["state"] = GML_TIME_SOURCE_STATE_ACTIVE
	ts["elapsed"] = 0.0
	ts["reps_done"] = 0
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if typeof(child) == TYPE_DICTIONARY and child["state"] == GML_TIME_SOURCE_STATE_INITIAL:
			child["state"] = GML_TIME_SOURCE_STATE_ACTIVE
			child["elapsed"] = 0.0
			child["reps_done"] = 0


static func gml_time_source_stop(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return
	ts["state"] = GML_TIME_SOURCE_STATE_STOPPED
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if typeof(child) == TYPE_DICTIONARY:
			child["state"] = GML_TIME_SOURCE_STATE_STOPPED


static func gml_time_source_pause(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return
	if ts["state"] == GML_TIME_SOURCE_STATE_ACTIVE:
		ts["state"] = GML_TIME_SOURCE_STATE_PAUSED
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if typeof(child) == TYPE_DICTIONARY and child["state"] == GML_TIME_SOURCE_STATE_ACTIVE:
			child["state"] = GML_TIME_SOURCE_STATE_PAUSED


static func gml_time_source_resume(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return
	if ts["state"] == GML_TIME_SOURCE_STATE_PAUSED:
		ts["state"] = GML_TIME_SOURCE_STATE_ACTIVE
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if typeof(child) == TYPE_DICTIONARY and child["state"] == GML_TIME_SOURCE_STATE_PAUSED:
			child["state"] = GML_TIME_SOURCE_STATE_ACTIVE


static func gml_time_source_destroy(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return
	for child_id in ts["children"]:
		var child = _gml_time_sources.get(child_id)
		if typeof(child) == TYPE_DICTIONARY:
			_gml_time_sources.erase(child_id)
	_gml_time_sources.erase(ts["id"])
	gml_handle_invalidate(handle)


static func gml_time_source_get_state(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return GML_TIME_SOURCE_STATE_STOPPED
	return ts["state"]


static func gml_time_source_get_period(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return 0
	return ts["period"]


static func gml_time_source_get_reps_completed(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return 0
	return ts["reps_done"]


static func gml_time_source_get_reps_remaining(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return 0
	var total = ts["reps"]
	if total < 0:
		return -1
	return max(0, total - ts["reps_done"])


static func gml_time_source_get_time_remaining(handle):
	var ts = _gml_time_source_resolve(handle)
	if typeof(ts) != TYPE_DICTIONARY:
		return 0
	return max(0.0, ts["period"] - ts["elapsed"])


static func gml_call_later(period, units, callback, repeat = false):
	var reps = -1 if bool(repeat) else 1
	var handle = gml_time_source_create(null, period, units, callback, [], reps, GML_TIME_SOURCE_EXPIRY_AFTER)
	gml_time_source_start(handle)
	return handle


static func gml_call_cancel(handle):
	gml_time_source_stop(handle)
	gml_time_source_destroy(handle)


static func gml_time_source_tick_all(delta_seconds, delta_frames):
	var finished = []
	for ts_id in _gml_time_sources:
		var ts = _gml_time_sources[ts_id]
		if ts["state"] != GML_TIME_SOURCE_STATE_ACTIVE:
			continue
		var increment = delta_seconds if ts["units"] == GML_TIME_SOURCE_UNITS_SECONDS else delta_frames
		ts["elapsed"] += increment
		if ts["elapsed"] >= ts["period"]:
			ts["elapsed"] -= ts["period"]
			ts["reps_done"] += 1
			_gml_time_source_invoke(ts)
			var total = ts["reps"]
			if total >= 0 and ts["reps_done"] >= total:
				ts["state"] = GML_TIME_SOURCE_STATE_STOPPED
				finished.append(ts_id)
	for ts_id in finished:
		if _gml_time_sources.has(ts_id):
			var ts = _gml_time_sources[ts_id]
			if ts["state"] == GML_TIME_SOURCE_STATE_STOPPED:
				pass


static func _gml_time_source_invoke(ts):
	var cb = ts["callback"]
	var args = ts["args"]
	if cb == null:
		return
	if cb is Callable:
		if args is Array and not args.is_empty():
			cb.callv(args)
		else:
			cb.call()
	elif typeof(cb) == TYPE_DICTIONARY and cb.has("_gml_method_callable"):
		var real_callable = cb["_gml_method_callable"]
		if real_callable is Callable:
			if args is Array and not args.is_empty():
				real_callable.callv(args)
			else:
				real_callable.call()


static func _gml_time_source_resolve(handle):
	if handle == null:
		return null
	if not gml_handle_is_valid(handle):
		return null
	var ts_id = handle.reference
	if ts_id == null:
		return null
	return _gml_time_sources.get(ts_id)
