const GML_SOUND_HANDLE_KIND = "sound"
const GML_AUDIO_EMITTER_HANDLE_KIND = "audio_emitter"
const GML_AUDIO_QUEUE_HANDLE_KIND = "audio_queue"
const GML_AUDIO_SYNC_GROUP_HANDLE_KIND = "audio_sync_group"
const GML_AUDIO_MANAGER_NODE_NAME = "_GM2GodotAudioRuntime"
const GML_AUDIO_MIN_PITCH = 0.0001
const GML_AUDIO_DEFAULT_CHANNEL_COUNT = 128
const GML_AUDIO_CHANNEL_MONO = 1
const GML_AUDIO_CHANNEL_STEREO = 2
const GML_AUDIO_CHANNEL_3D = 3

static var _gml_audio_root = null
static var _gml_audio_instances = {}
static var _gml_audio_instances_by_asset = {}
static var _gml_audio_asset_state = {}
static var _gml_audio_group_state = {}
static var _gml_audio_master_gain = 1.0
static var _gml_audio_channel_limit = GML_AUDIO_DEFAULT_CHANNEL_COUNT
static var _gml_audio_emitters = {}
static var _gml_audio_listener_state = {}
static var _gml_audio_global_listener_mask = 1
static var _gml_audio_queues = {}
static var _gml_audio_sync_groups = {}
static var _gml_audio_diagnostics = []
static var _gml_audio_throw_on_error = false


static func gml_audio_play_sound(sound, priority, loop, gain = null, offset = null, pitch = null, listener_mask = null):
	var queue_entry = _gml_audio_queue_entry(sound)
	if queue_entry != null:
		return _gml_audio_play_queue_sound(queue_entry, priority, loop, gain, offset, pitch, listener_mask)
	return _gml_audio_play_sound_instance(sound, priority, loop, gain, offset, pitch, listener_mask)


static func gml_audio_play_sound_at(sound, x, y, z, falloff_ref, falloff_max, falloff_factor, loop, priority, gain = null, offset = null, pitch = null, listener_mask = null):
	var spatial_state = _gml_audio_spatial_state(x, y, z, 0.0, 0.0, 0.0, 1.0, 1.0, listener_mask, falloff_ref, falloff_max, falloff_factor, -1)
	return _gml_audio_play_sound_instance(sound, priority, loop, gain, offset, pitch, listener_mask, spatial_state)


static func gml_audio_play_sound_on(emitter, sound, loop, priority, gain = null, offset = null, pitch = null, listener_mask = null):
	var emitter_entry = _gml_audio_emitter_entry(emitter)
	if emitter_entry == null:
		return gml_handle_invalid(GML_SOUND_HANDLE_KIND)
	var spatial_state = _gml_audio_spatial_state_from_emitter(emitter_entry, listener_mask)
	return _gml_audio_play_sound_instance(sound, priority, loop, gain, offset, pitch, listener_mask, spatial_state)


static func gml_audio_stop_sound(sound):
	for entry in _gml_audio_target_entries(sound):
		_gml_audio_unregister_instance(entry["handle"].index, true)
	return null


static func gml_audio_stop_all():
	var instance_indices = []
	for entry in _gml_audio_instances.values():
		instance_indices.append(entry["handle"].index)
	for instance_index in instance_indices:
		_gml_audio_unregister_instance(instance_index, true)
	return null


static func gml_audio_pause_sound(sound):
	for entry in _gml_audio_target_entries(sound):
		var player = entry["player"]
		if _gml_audio_player_is_valid(player):
			player.stream_paused = true
	return null


static func gml_audio_pause_all():
	for entry in _gml_audio_instances.values():
		var player = entry["player"]
		if _gml_audio_player_is_valid(player):
			player.stream_paused = true
	return null


static func gml_audio_resume_sound(sound):
	for entry in _gml_audio_target_entries(sound):
		var player = entry["player"]
		if _gml_audio_player_is_valid(player):
			player.stream_paused = false
	return null


static func gml_audio_resume_all():
	for entry in _gml_audio_instances.values():
		var player = entry["player"]
		if _gml_audio_player_is_valid(player):
			player.stream_paused = false
	return null


static func gml_audio_is_playing(sound):
	var saw_inactive = []
	for entry in _gml_audio_target_entries(sound):
		if _gml_audio_instance_is_active(entry):
			return true
		saw_inactive.append(entry["handle"].index)
	for instance_index in saw_inactive:
		_gml_audio_unregister_instance(instance_index, false)
	return false


static func gml_audio_is_paused(sound):
	for entry in _gml_audio_target_entries(sound):
		var player = entry["player"]
		if _gml_audio_player_is_valid(player) and bool(player.stream_paused):
			return true
	return false


static func gml_audio_sound_gain(sound, gain, time = 0):
	var gain_value = max(_to_real(gain), 0.0)
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		handle_entry["instance_gain"] = gain_value
		_gml_audio_apply_entry_volume(handle_entry)
		return null
	var sound_entry = _gml_audio_sound_entry(sound)
	if sound_entry == null:
		return null
	var asset_state = _gml_audio_asset_state_for_entry(sound_entry)
	asset_state["gain"] = gain_value
	for entry in _gml_audio_entries_for_asset(int(sound_entry["id"])):
		entry["asset_gain"] = gain_value
		_gml_audio_apply_entry_volume(entry)
	return null


static func gml_audio_sound_get_gain(sound):
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		return _to_real(handle_entry.get("instance_gain", 1.0))
	var sound_entry = _gml_audio_sound_entry(sound)
	if sound_entry == null:
		return 0.0
	return _to_real(_gml_audio_asset_state_for_entry(sound_entry).get("gain", 1.0))


static func gml_audio_sound_pitch(sound, pitch):
	var pitch_value = max(_to_real(pitch), GML_AUDIO_MIN_PITCH)
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		handle_entry["instance_pitch"] = pitch_value
		_gml_audio_apply_entry_pitch(handle_entry)
		return null
	var sound_entry = _gml_audio_sound_entry(sound)
	if sound_entry == null:
		return null
	var asset_state = _gml_audio_asset_state_for_entry(sound_entry)
	asset_state["pitch"] = pitch_value
	for entry in _gml_audio_entries_for_asset(int(sound_entry["id"])):
		entry["asset_pitch"] = pitch_value
		_gml_audio_apply_entry_pitch(entry)
	return null


static func gml_audio_sound_get_pitch(sound):
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		return _to_real(handle_entry.get("instance_pitch", 1.0))
	var sound_entry = _gml_audio_sound_entry(sound)
	if sound_entry == null:
		return 0.0
	return _to_real(_gml_audio_asset_state_for_entry(sound_entry).get("pitch", 1.0))


static func gml_audio_sound_loop(sound, loop):
	for entry in _gml_audio_target_entries(sound):
		entry["loop"] = bool(loop)
	return null


static func gml_audio_sound_get_loop(sound):
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		return bool(handle_entry.get("loop", false))
	var entries = _gml_audio_target_entries(sound)
	for entry in entries:
		if bool(entry.get("loop", false)):
			return true
	return false


static func gml_audio_sound_set_listener_mask(sound, listener_mask):
	var mask = int(_to_real(listener_mask))
	for entry in _gml_audio_target_entries(sound):
		entry["listener_mask"] = mask
	return null


static func gml_audio_sound_get_listener_mask(sound):
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		return int(handle_entry.get("listener_mask", 1))
	return 0


static func gml_audio_sound_get_asset(sound):
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		return int(handle_entry.get("asset_id", -1))
	var sound_entry = _gml_audio_sound_entry(sound)
	if sound_entry == null:
		return -1
	return int(sound_entry["id"])


static func gml_audio_channel_num(num_channels):
	_gml_audio_channel_limit = max(int(_to_real(num_channels)), 1)
	_gml_audio_enforce_channel_limit()
	return null


static func gml_audio_master_gain(gain):
	return gml_audio_set_master_gain(gain)


static func gml_audio_set_master_gain(gain):
	_gml_audio_master_gain = max(_to_real(gain), 0.0)
	for entry in _gml_audio_instances.values():
		_gml_audio_apply_entry_volume(entry)
	return null


static func gml_audio_get_master_gain():
	return _gml_audio_master_gain


static func gml_audio_throw_on_error(enable):
	_gml_audio_throw_on_error = bool(enable)
	return null


static func gml_audio_runtime_diagnostics():
	return _gml_clone_value(_gml_audio_diagnostics, 16)


static func gml_audio_emitter_create():
	var entry = _gml_audio_emitter_default_state()
	var handle = gml_handle_register(GML_AUDIO_EMITTER_HANDLE_KIND, entry, "audio_emitter")
	entry["handle"] = handle
	_gml_audio_emitters[handle.index] = entry
	return handle


static func gml_audio_emitter_exists(emitter):
	return _gml_audio_emitter_entry(emitter) != null


static func gml_audio_emitter_free(emitter):
	var entry = _gml_audio_emitter_entry(emitter)
	if entry == null:
		return false
	var handle = entry["handle"]
	_gml_audio_emitters.erase(handle.index)
	gml_handle_invalidate(handle)
	return true


static func gml_audio_emitter_position(emitter, x, y, z):
	var entry = _gml_audio_emitter_entry(emitter)
	if entry == null:
		return null
	entry["x"] = _to_real(x)
	entry["y"] = _to_real(y)
	entry["z"] = _to_real(z)
	_gml_audio_apply_emitter_to_active_entries(entry)
	return null


static func gml_audio_emitter_velocity(emitter, vx, vy, vz):
	var entry = _gml_audio_emitter_entry(emitter)
	if entry == null:
		return null
	entry["vx"] = _to_real(vx)
	entry["vy"] = _to_real(vy)
	entry["vz"] = _to_real(vz)
	return null


static func gml_audio_emitter_falloff(emitter, falloff_ref, falloff_max, falloff_factor):
	var entry = _gml_audio_emitter_entry(emitter)
	if entry == null:
		return null
	entry["falloff_ref"] = max(_to_real(falloff_ref), 0.0)
	entry["falloff_max"] = max(_to_real(falloff_max), 0.0)
	entry["falloff_factor"] = max(_to_real(falloff_factor), 0.0)
	_gml_audio_apply_emitter_to_active_entries(entry)
	return null


static func gml_audio_emitter_gain(emitter, gain):
	var entry = _gml_audio_emitter_entry(emitter)
	if entry == null:
		return null
	entry["gain"] = max(_to_real(gain), 0.0)
	for sound_entry in _gml_audio_entries_for_emitter(entry["handle"].index):
		sound_entry["emitter_gain"] = entry["gain"]
		_gml_audio_apply_entry_volume(sound_entry)
	return null


static func gml_audio_emitter_get_gain(emitter):
	var entry = _gml_audio_emitter_entry(emitter)
	return _to_real(entry.get("gain", 0.0)) if entry != null else 0.0


static func gml_audio_emitter_pitch(emitter, pitch):
	var entry = _gml_audio_emitter_entry(emitter)
	if entry == null:
		return null
	entry["pitch"] = max(_to_real(pitch), GML_AUDIO_MIN_PITCH)
	for sound_entry in _gml_audio_entries_for_emitter(entry["handle"].index):
		sound_entry["emitter_pitch"] = entry["pitch"]
		_gml_audio_apply_entry_pitch(sound_entry)
	return null


static func gml_audio_emitter_get_pitch(emitter):
	var entry = _gml_audio_emitter_entry(emitter)
	return _to_real(entry.get("pitch", 0.0)) if entry != null else 0.0


static func gml_audio_emitter_set_listener_mask(emitter, listener_mask):
	var entry = _gml_audio_emitter_entry(emitter)
	if entry == null:
		return null
	entry["listener_mask"] = int(_to_real(listener_mask))
	for sound_entry in _gml_audio_entries_for_emitter(entry["handle"].index):
		sound_entry["listener_mask"] = entry["listener_mask"]
	return null


static func gml_audio_emitter_get_listener_mask(emitter):
	var entry = _gml_audio_emitter_entry(emitter)
	return int(entry.get("listener_mask", 0)) if entry != null else 0


static func gml_audio_emitter_get_x(emitter):
	var entry = _gml_audio_emitter_entry(emitter)
	return _to_real(entry.get("x", 0.0)) if entry != null else 0.0


static func gml_audio_emitter_get_y(emitter):
	var entry = _gml_audio_emitter_entry(emitter)
	return _to_real(entry.get("y", 0.0)) if entry != null else 0.0


static func gml_audio_emitter_get_z(emitter):
	var entry = _gml_audio_emitter_entry(emitter)
	return _to_real(entry.get("z", 0.0)) if entry != null else 0.0


static func gml_audio_listener_position(x, y, z):
	return gml_audio_listener_set_position(0, x, y, z)


static func gml_audio_listener_velocity(vx, vy, vz):
	return gml_audio_listener_set_velocity(0, vx, vy, vz)


static func gml_audio_listener_orientation(lookat_x, lookat_y, lookat_z, up_x, up_y, up_z):
	return gml_audio_listener_set_orientation(0, lookat_x, lookat_y, lookat_z, up_x, up_y, up_z)


static func gml_audio_listener_set_position(index, x, y, z):
	var entry = _gml_audio_listener_entry(index)
	entry["x"] = _to_real(x)
	entry["y"] = _to_real(y)
	entry["z"] = _to_real(z)
	return null


static func gml_audio_listener_set_velocity(index, vx, vy, vz):
	var entry = _gml_audio_listener_entry(index)
	entry["vx"] = _to_real(vx)
	entry["vy"] = _to_real(vy)
	entry["vz"] = _to_real(vz)
	return null


static func gml_audio_listener_set_orientation(index, lookat_x, lookat_y, lookat_z, up_x, up_y, up_z):
	var entry = _gml_audio_listener_entry(index)
	entry["lookat_x"] = _to_real(lookat_x)
	entry["lookat_y"] = _to_real(lookat_y)
	entry["lookat_z"] = _to_real(lookat_z)
	entry["up_x"] = _to_real(up_x)
	entry["up_y"] = _to_real(up_y)
	entry["up_z"] = _to_real(up_z)
	return null


static func gml_audio_get_listener_count():
	return 1


static func gml_audio_get_listener_info(num):
	var index = int(_to_real(num))
	return {
		"name": "default" if index == 0 else "listener_" + str(index),
		"mask": 1 << max(index, 0),
		"index": index,
	}


static func gml_audio_get_listener_mask():
	return _gml_audio_global_listener_mask


static func gml_audio_set_listener_mask(mask):
	_gml_audio_global_listener_mask = int(_to_real(mask))
	return null


static func gml_audio_listener_state(index = 0):
	return _gml_clone_value(_gml_audio_listener_entry(index), 8)


static func gml_audio_create_play_queue(queue_format, queue_rate, queue_channels):
	var entry = {
		"format": int(_to_real(queue_format)),
		"rate": clamp(_to_real(queue_rate), 1000.0, 48000.0),
		"channels": int(_to_real(queue_channels)),
		"buffers": [],
		"shutdown": false,
		"stream": AudioStreamGenerator.new(),
	}
	entry["stream"].mix_rate = entry["rate"]
	var handle = gml_handle_register(GML_AUDIO_QUEUE_HANDLE_KIND, entry, "audio_queue")
	entry["handle"] = handle
	_gml_audio_queues[handle.index] = entry
	return handle


static func gml_audio_queue_sound(queue, buffer_id, offset, length):
	var entry = _gml_audio_queue_entry(queue)
	if entry == null:
		return false
	var queued = {
		"buffer_id": buffer_id,
		"offset": max(_to_real(offset), 0.0),
		"length": max(_to_real(length), 0.0),
	}
	entry["buffers"].append(queued)
	var diagnostic = _gml_audio_report_diagnostic("audio_queue_sound", "Audio queue buffer lifecycle is modelled, but PCM queue streaming is not synthesized by the compatibility runtime.")
	gml_async_dispatch("audio_playback", {
		"id": gml_async_next_request_id(),
		"status": 0,
		"queue_id": entry["handle"].index,
		"buffer_id": buffer_id,
		"queue_shutdown": 0,
		"diagnostic": diagnostic,
	}, "_on_audio_playback_async")
	return true


static func gml_audio_free_play_queue(queue):
	var entry = _gml_audio_queue_entry(queue)
	if entry == null:
		return false
	var handle = entry["handle"]
	entry["shutdown"] = true
	gml_async_dispatch("audio_playback", {
		"id": gml_async_next_request_id(),
		"status": 0,
		"queue_id": handle.index,
		"buffer_id": -1,
		"queue_shutdown": 1,
	}, "_on_audio_playback_async")
	_gml_audio_queues.erase(handle.index)
	gml_handle_invalidate(handle)
	return true


static func gml_audio_get_recorder_count():
	return 0


static func gml_audio_get_recorder_info(recorder_index):
	return {
		"name": "unsupported_recorder_" + str(int(_to_real(recorder_index))),
		"index": int(_to_real(recorder_index)),
		"available": false,
	}


static func gml_audio_start_recording(recorder_index):
	var channel_index = int(_to_real(recorder_index))
	var diagnostic = _gml_audio_report_unsupported("audio_start_recording", "Godot microphone capture requires project-specific AudioEffectCapture setup and platform permissions.")
	gml_async_dispatch("audio_recording", {
		"id": gml_async_next_request_id(),
		"status": -1,
		"buffer_id": -1,
		"buffer": -1,
		"channel_index": channel_index,
		"channel": channel_index,
		"data_len": 0,
		"diagnostic": diagnostic,
	}, "_on_audio_recording_async")
	return -1


static func gml_audio_stop_recording(channel_index):
	_gml_audio_report_unsupported("audio_stop_recording", "No compatible recording channel is active in the generated runtime.")
	return false


static func gml_audio_create_stream(filename):
	var resource_path = str(filename)
	if resource_path == "":
		return -1
	if not resource_path.begins_with("res://") and not resource_path.begins_with("user://"):
		resource_path = "res://" + resource_path
	if not ResourceLoader.exists(resource_path):
		_gml_audio_report_diagnostic("audio_create_stream", "Stream resource not found: " + resource_path)
		return -1
	var stream = load(resource_path)
	if not (stream is AudioStream):
		_gml_audio_report_diagnostic("audio_create_stream", "Resource is not a Godot AudioStream: " + resource_path)
		return -1
	var stream_name = resource_path.get_file().get_basename()
	var asset_id = gml_asset_register_dynamic(stream_name, "sound", stream, ["audio_stream"])
	var entry: Variant = _gml_asset_resolve(asset_id)
	if entry != null:
		entry["godot_path"] = resource_path
		entry["metadata"] = {"audio_group": "audiogroup_default", "streamed": true}
	return asset_id


static func gml_audio_destroy_stream(sound):
	return gml_asset_release(sound)


static func gml_audio_create_sync_group(loop):
	var entry = {
		"loop": bool(loop),
		"sounds": [],
		"handles": [],
		"playing": false,
		"paused": false,
	}
	var handle = gml_handle_register(GML_AUDIO_SYNC_GROUP_HANDLE_KIND, entry, "audio_sync_group")
	entry["handle"] = handle
	_gml_audio_sync_groups[handle.index] = entry
	return handle


static func gml_audio_play_in_sync_group(group_index, sound_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null or _gml_audio_sound_entry(sound_index) == null:
		return -1
	entry["sounds"].append(sound_index)
	return entry["sounds"].size() - 1


static func gml_audio_start_sync_group(group_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null:
		return false
	_gml_audio_report_diagnostic("audio_start_sync_group", "Sync groups are started in one runtime tick; sample-accurate sync depends on Godot stream scheduling.")
	entry["handles"].clear()
	for sound in entry["sounds"]:
		var handle = gml_audio_play_sound(sound, 0, bool(entry["loop"]))
		if gml_handle_is_valid(handle):
			entry["handles"].append(handle)
	entry["playing"] = not entry["handles"].is_empty()
	entry["paused"] = false
	return bool(entry["playing"])


static func gml_audio_stop_sync_group(group_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null:
		return false
	for handle in entry["handles"]:
		gml_audio_stop_sound(handle)
	entry["handles"].clear()
	entry["playing"] = false
	entry["paused"] = false
	return true


static func gml_audio_pause_sync_group(group_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null:
		return false
	for handle in entry["handles"]:
		gml_audio_pause_sound(handle)
	entry["paused"] = true
	return true


static func gml_audio_resume_sync_group(group_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null:
		return false
	for handle in entry["handles"]:
		gml_audio_resume_sound(handle)
	entry["paused"] = false
	return true


static func gml_audio_sync_group_is_playing(group_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null:
		return false
	for handle in entry["handles"]:
		if gml_audio_is_playing(handle):
			return true
	entry["playing"] = false
	return false


static func gml_audio_sync_group_get_track_pos(group_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null:
		return 0.0
	for handle in entry["handles"]:
		var sound_entry = _gml_audio_handle_entry(handle)
		if sound_entry != null:
			var player = sound_entry["player"]
			if _gml_audio_player_is_valid(player):
				return player.get_playback_position()
	return 0.0


static func gml_audio_destroy_sync_group(group_index):
	var entry = _gml_audio_sync_group_entry(group_index)
	if entry == null:
		return false
	gml_audio_stop_sync_group(group_index)
	var handle = entry["handle"]
	_gml_audio_sync_groups.erase(handle.index)
	gml_handle_invalidate(handle)
	return true


static func _gml_audio_play_sound_instance(sound, priority, loop, gain = null, offset = null, pitch = null, listener_mask = null, spatial_state = null):
	var sound_entry = _gml_audio_sound_entry(sound)
	if sound_entry == null:
		return gml_handle_invalid(GML_SOUND_HANDLE_KIND)
	var stream = _gml_audio_stream_for_entry(sound_entry)
	if stream == null:
		return gml_handle_invalid(GML_SOUND_HANDLE_KIND)
	var manager = _gml_audio_root_node()
	if manager == null:
		return gml_handle_invalid(GML_SOUND_HANDLE_KIND)
	var asset_id = int(sound_entry["id"])
	var asset_state = _gml_audio_asset_state_for_entry(sound_entry)
	var audio_group = _gml_audio_group_for_entry(sound_entry)
	if not _gml_audio_group_is_loaded_name(audio_group):
		return gml_handle_invalid(GML_SOUND_HANDLE_KIND)
	var group_state = _gml_audio_group_state_for_name(audio_group)
	var instance_gain = max(_to_real(gain), 0.0) if gain != null else 1.0
	var instance_pitch = max(_to_real(pitch), GML_AUDIO_MIN_PITCH) if pitch != null else 1.0
	var use_spatial = typeof(spatial_state) == TYPE_DICTIONARY
	var player = AudioStreamPlayer2D.new() if use_spatial else AudioStreamPlayer.new()
	player.name = "_gm_sound_" + str(asset_id) + "_" + str(_gml_handle_next_indices.get(GML_SOUND_HANDLE_KIND, 0))
	player.stream = _gml_audio_stream_for_playback(stream, loop)
	player.bus = _gml_audio_bus_for_group(audio_group)
	var emitter_gain = _to_real(spatial_state.get("gain", 1.0)) if use_spatial else 1.0
	var emitter_pitch = _to_real(spatial_state.get("pitch", 1.0)) if use_spatial else 1.0
	player.volume_linear = _gml_audio_final_gain(asset_state["gain"], group_state["gain"], instance_gain, emitter_gain)
	player.pitch_scale = _gml_audio_final_pitch(asset_state["pitch"], instance_pitch, emitter_pitch)
	player.max_polyphony = 1
	if use_spatial:
		_gml_audio_apply_spatial_state_to_player(player, spatial_state)
	var handle = gml_handle_register(GML_SOUND_HANDLE_KIND, player, str(sound_entry["name"]))
	var entry = {
		"handle": handle,
		"player": player,
		"asset_id": asset_id,
		"asset_name": str(sound_entry["name"]),
		"audio_group": audio_group,
		"priority": _to_real(priority),
		"loop": bool(loop),
		"listener_mask": listener_mask,
		"asset_gain": asset_state["gain"],
		"group_gain": group_state["gain"],
		"asset_pitch": asset_state["pitch"],
		"instance_gain": instance_gain,
		"instance_pitch": instance_pitch,
		"emitter_index": int(spatial_state.get("emitter_index", -1)) if use_spatial else -1,
		"emitter_gain": emitter_gain,
		"emitter_pitch": emitter_pitch,
		"spatial_state": _gml_clone_value(spatial_state, 8) if use_spatial else {},
		"pending_play": not manager.is_inside_tree()
	}
	_gml_audio_instances[handle.index] = entry
	if not _gml_audio_instances_by_asset.has(asset_id):
		_gml_audio_instances_by_asset[asset_id] = []
	_gml_audio_instances_by_asset[asset_id].append(handle.index)
	player.finished.connect(func(): _gml_audio_player_finished(handle.index))
	var play_offset = max(_to_real(offset), 0.0) if offset != null else 0.0
	if manager.is_inside_tree():
		manager.add_child(player)
		player.play(play_offset)
	else:
		manager.call_deferred("add_child", player)
		player.call_deferred("play", play_offset)
	_gml_audio_enforce_channel_limit()
	return handle


static func _gml_audio_play_queue_sound(queue_entry, priority, loop, gain = null, offset = null, pitch = null, listener_mask = null):
	var manager = _gml_audio_root_node()
	if manager == null:
		return gml_handle_invalid(GML_SOUND_HANDLE_KIND)
	var group_state = _gml_audio_group_state_for_name("audiogroup_default")
	var instance_gain = max(_to_real(gain), 0.0) if gain != null else 1.0
	var instance_pitch = max(_to_real(pitch), GML_AUDIO_MIN_PITCH) if pitch != null else 1.0
	var player = AudioStreamPlayer.new()
	player.name = "_gm_audio_queue_" + str(queue_entry["handle"].index) + "_" + str(_gml_handle_next_indices.get(GML_SOUND_HANDLE_KIND, 0))
	player.stream = queue_entry["stream"]
	player.bus = "Master"
	player.volume_linear = _gml_audio_final_gain(1.0, group_state["gain"], instance_gain)
	player.pitch_scale = _gml_audio_final_pitch(1.0, instance_pitch)
	player.max_polyphony = 1
	var handle = gml_handle_register(GML_SOUND_HANDLE_KIND, player, "audio_queue_" + str(queue_entry["handle"].index))
	var entry = {
		"handle": handle,
		"player": player,
		"asset_id": -queue_entry["handle"].index - 1,
		"asset_name": "audio_queue_" + str(queue_entry["handle"].index),
		"queue_id": queue_entry["handle"].index,
		"audio_group": "audiogroup_default",
		"priority": _to_real(priority),
		"loop": bool(loop),
		"listener_mask": listener_mask if listener_mask != null else _gml_audio_global_listener_mask,
		"asset_gain": 1.0,
		"group_gain": group_state["gain"],
		"asset_pitch": 1.0,
		"instance_gain": instance_gain,
		"instance_pitch": instance_pitch,
		"emitter_index": -1,
		"emitter_gain": 1.0,
		"emitter_pitch": 1.0,
		"spatial_state": {},
		"pending_play": not manager.is_inside_tree()
	}
	_gml_audio_instances[handle.index] = entry
	player.finished.connect(func(): _gml_audio_player_finished(handle.index))
	var play_offset = max(_to_real(offset), 0.0) if offset != null else 0.0
	if manager.is_inside_tree():
		manager.add_child(player)
		player.play(play_offset)
	else:
		manager.call_deferred("add_child", player)
		player.call_deferred("play", play_offset)
	_gml_audio_enforce_channel_limit()
	return handle


static func gml_sound_play(sound):
	return gml_audio_play_sound(sound, 0, false)


static func gml_sound_loop(sound):
	return gml_audio_play_sound(sound, 0, true)


static func gml_sound_stop(sound):
	return gml_audio_stop_sound(sound)


static func gml_sound_pause(sound):
	return gml_audio_pause_sound(sound)


static func gml_sound_resume(sound):
	return gml_audio_resume_sound(sound)


static func gml_sound_isplaying(sound):
	return gml_audio_is_playing(sound)


static func gml_sound_volume(sound, volume):
	return gml_audio_sound_gain(sound, volume, 0)


static func gml_sound_pitch(sound, pitch):
	return gml_audio_sound_pitch(sound, pitch)


static func gml_sound_global_volume(volume):
	_gml_audio_master_gain = max(_to_real(volume), 0.0)
	for entry in _gml_audio_instances.values():
		_gml_audio_apply_entry_volume(entry)
	return null


static func gml_audio_group_load(group_id):
	var group = _gml_audio_group_name(group_id)
	if group == "" or not _gml_audio_group_exists(group):
		return false
	var state = _gml_audio_group_state_for_name(group)
	if bool(state["loaded"]) or bool(state["loading"]):
		return false
	state["loading"] = true
	state["progress"] = 1.0
	state["loaded"] = true
	state["loading"] = false
	return true


static func gml_audio_group_unload(group_id):
	var group = _gml_audio_group_name(group_id)
	if group == "" or group == "audiogroup_default" or not _gml_audio_group_exists(group):
		return false
	var state = _gml_audio_group_state_for_name(group)
	if not bool(state["loaded"]) and not bool(state["loading"]):
		return false
	gml_audio_group_stop_all(group)
	state["loaded"] = false
	state["loading"] = false
	state["progress"] = 0.0
	return true


static func gml_audio_group_is_loaded(group_id):
	var group = _gml_audio_group_name(group_id)
	if group == "" or not _gml_audio_group_exists(group):
		return false
	return _gml_audio_group_is_loaded_name(group)


static func gml_audio_group_load_progress(group_id):
	var group = _gml_audio_group_name(group_id)
	if group == "" or not _gml_audio_group_exists(group):
		return 0.0
	return _to_real(_gml_audio_group_state_for_name(group).get("progress", 0.0))


static func gml_audio_group_name(group_id):
	var group = _gml_audio_group_name(group_id)
	return group if _gml_audio_group_exists(group) else ""


static func gml_audio_group_stop_all(group_id):
	var group = _gml_audio_group_name(group_id)
	if group == "" or not _gml_audio_group_exists(group):
		return false
	var instance_indices = []
	for entry in _gml_audio_instances.values():
		if str(entry.get("audio_group", "audiogroup_default")) == group:
			instance_indices.append(entry["handle"].index)
	for instance_index in instance_indices:
		_gml_audio_unregister_instance(instance_index, true)
	return true


static func gml_audio_group_set_gain(group_id, gain, time = 0):
	var group = _gml_audio_group_name(group_id)
	if group == "" or not _gml_audio_group_exists(group):
		return false
	var state = _gml_audio_group_state_for_name(group)
	var gain_value = max(_to_real(gain), 0.0)
	state["gain"] = gain_value
	for entry in _gml_audio_entries_for_group(group):
		entry["group_gain"] = gain_value
		_gml_audio_apply_entry_volume(entry)
	return true


static func gml_audio_group_get_gain(group_id):
	var group = _gml_audio_group_name(group_id)
	if group == "" or not _gml_audio_group_exists(group):
		return 0.0
	return _to_real(_gml_audio_group_state_for_name(group).get("gain", 1.0))


static func _gml_audio_root_node():
	if _gml_audio_root != null and is_instance_valid(_gml_audio_root):
		return _gml_audio_root
	var main_loop = Engine.get_main_loop()
	if not (main_loop is SceneTree):
		return null
	var root = main_loop.root
	if root == null:
		return null
	var existing = root.get_node_or_null(GML_AUDIO_MANAGER_NODE_NAME)
	if existing != null:
		_gml_audio_root = existing
		return _gml_audio_root
	var manager = Node.new()
	manager.name = GML_AUDIO_MANAGER_NODE_NAME
	root.call_deferred("add_child", manager)
	_gml_audio_root = manager
	return _gml_audio_root


static func _gml_audio_sound_entry(sound):
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(sound)
	if entry == null:
		return null
	if not entry.has("type") or str(entry["type"]) != "sound":
		return null
	return entry


static func _gml_audio_stream_for_entry(sound_entry):
	if sound_entry.has("resource") and sound_entry["resource"] is AudioStream:
		return sound_entry["resource"]
	var godot_path = str(sound_entry["godot_path"]) if sound_entry.has("godot_path") else ""
	if godot_path == "":
		return null
	if not ResourceLoader.exists(godot_path):
		return null
	var stream = load(godot_path)
	if stream is AudioStream:
		return stream
	return null


static func _gml_audio_stream_for_playback(stream, loop):
	return stream


static func _gml_audio_bus_for_group(audio_group):
	if audio_group == "" or audio_group == "audiogroup_default":
		return "Master"
	return audio_group


static func _gml_audio_asset_state_for_entry(sound_entry):
	var asset_id = int(sound_entry["id"])
	if not _gml_audio_asset_state.has(asset_id):
		var metadata = _gml_audio_metadata(sound_entry)
		var volume = _to_real(metadata["volume"]) if metadata.has("volume") else 1.0
		_gml_audio_asset_state[asset_id] = {
			"gain": max(volume, 0.0),
			"pitch": 1.0
		}
	return _gml_audio_asset_state[asset_id]


static func _gml_audio_metadata(sound_entry):
	if sound_entry.has("metadata") and typeof(sound_entry["metadata"]) == TYPE_DICTIONARY:
		return sound_entry["metadata"]
	return {}


static func _gml_audio_handle_entry(sound):
	if is_handle(sound) and sound.kind == GML_SOUND_HANDLE_KIND and _gml_audio_instances.has(sound.index):
		return _gml_audio_instances[sound.index]
	var handle = gml_handle_from_value(GML_SOUND_HANDLE_KIND, sound)
	if gml_handle_is_valid(handle) and _gml_audio_instances.has(handle.index):
		return _gml_audio_instances[handle.index]
	return null


static func _gml_audio_target_entries(sound):
	var handle_entry = _gml_audio_handle_entry(sound)
	if handle_entry != null:
		return [handle_entry]
	var sound_entry: Variant = _gml_audio_sound_entry(sound)
	if sound_entry == null:
		return []
	return _gml_audio_entries_for_asset(int(sound_entry["id"]))


static func _gml_audio_entries_for_asset(asset_id):
	var entries = []
	if not _gml_audio_instances_by_asset.has(asset_id):
		return entries
	var instance_indices = []
	for instance_index in _gml_audio_instances_by_asset[asset_id]:
		instance_indices.append(instance_index)
	for instance_index in instance_indices:
		if _gml_audio_instances.has(instance_index):
			entries.append(_gml_audio_instances[instance_index])
	return entries


static func _gml_audio_apply_entry_volume(entry):
	var player = entry["player"]
	if _gml_audio_player_is_valid(player):
		player.volume_linear = _gml_audio_final_gain(
			entry["asset_gain"],
			entry["group_gain"],
			entry["instance_gain"],
			entry.get("emitter_gain", 1.0)
		)


static func _gml_audio_apply_entry_pitch(entry):
	var player = entry["player"]
	if _gml_audio_player_is_valid(player):
		player.pitch_scale = _gml_audio_final_pitch(
			entry["asset_pitch"],
			entry["instance_pitch"],
			entry.get("emitter_pitch", 1.0)
		)


static func _gml_audio_final_gain(asset_gain, group_gain, instance_gain, emitter_gain = 1.0):
	return max(_to_real(asset_gain), 0.0) * max(_to_real(group_gain), 0.0) * max(_to_real(instance_gain), 0.0) * max(_to_real(emitter_gain), 0.0) * _gml_audio_master_gain


static func _gml_audio_final_pitch(asset_pitch, instance_pitch, emitter_pitch = 1.0):
	return max(_to_real(asset_pitch) * _to_real(instance_pitch) * _to_real(emitter_pitch), GML_AUDIO_MIN_PITCH)


static func _gml_audio_instance_is_active(entry):
	var player = entry["player"]
	if not _gml_audio_player_is_valid(player):
		return false
	return bool(entry.get("pending_play", false)) or bool(player.playing) or bool(player.stream_paused)


static func _gml_audio_player_finished(instance_index):
	if not _gml_audio_instances.has(instance_index):
		return
	var entry = _gml_audio_instances[instance_index]
	var player = entry["player"]
	if bool(entry["loop"]) and _gml_audio_player_is_valid(player):
		player.play(0.0)
		return
	gml_async_enqueue_from_signal("audio_playback_ended", {
		"id": gml_async_next_request_id(),
		"status": 0,
		"sound_id": entry["handle"],
		"asset_id": entry["asset_id"],
		"asset_name": entry["asset_name"]
	}, "_on_audio_playback_ended_async")
	_gml_audio_unregister_instance(instance_index, false)


static func _gml_audio_unregister_instance(instance_index, stop_player):
	if not _gml_audio_instances.has(instance_index):
		return false
	var entry = _gml_audio_instances[instance_index]
	_gml_audio_instances.erase(instance_index)
	var asset_id = int(entry["asset_id"])
	if _gml_audio_instances_by_asset.has(asset_id):
		_gml_audio_instances_by_asset[asset_id].erase(instance_index)
		if _gml_audio_instances_by_asset[asset_id].is_empty():
			_gml_audio_instances_by_asset.erase(asset_id)
	var player = entry["player"]
	if _gml_audio_player_is_valid(player):
		if bool(stop_player):
			player.stop()
		if player.is_inside_tree():
			player.queue_free()
	var handle = entry["handle"]
	gml_handle_invalidate(handle)
	return true


static func _gml_audio_group_for_entry(sound_entry):
	var metadata = _gml_audio_metadata(sound_entry)
	return str(metadata["audio_group"]) if metadata.has("audio_group") else "audiogroup_default"


static func _gml_audio_group_name(group_id):
	if is_string(group_id):
		return str(group_id)
	if typeof(group_id) == TYPE_DICTIONARY and group_id.has("name"):
		return str(group_id["name"])
	return str(group_id)


static func _gml_audio_group_exists(group):
	var group_name = str(group)
	if group_name == "audiogroup_default":
		return true
	if _gml_audio_group_registry_entry(group_name) != null:
		return true
	_gml_asset_registry_ensure_loaded()
	for entry in _gml_asset_entries:
		if str(entry.get("type", "")) != "sound":
			continue
		if _gml_audio_group_for_entry(entry) == group_name:
			return true
	return false


static func _gml_audio_group_is_loaded_name(group):
	return bool(_gml_audio_group_state_for_name(group).get("loaded", false))


static func _gml_audio_group_state_for_name(group):
	var group_name = str(group)
	if not _gml_audio_group_state.has(group_name):
		var registry_entry = _gml_audio_group_registry_entry(group_name)
		var has_registry_entry = typeof(registry_entry) == TYPE_DICTIONARY
		var loaded = group_name == "audiogroup_default"
		var gain = 1.0
		if has_registry_entry:
			loaded = bool(registry_entry.get("loaded", loaded))
			gain = _to_real(registry_entry.get("gain", 1.0))
		elif group_name != "":
			loaded = true
		_gml_audio_group_state[group_name] = {
			"loaded": loaded,
			"loading": false,
			"progress": 1.0 if loaded else 0.0,
			"gain": max(gain, 0.0)
		}
	return _gml_audio_group_state[group_name]


static func _gml_audio_entries_for_group(group):
	var group_name = str(group)
	var entries = []
	var instance_indices = []
	for entry in _gml_audio_instances.values():
		if str(entry.get("audio_group", "audiogroup_default")) == group_name:
			instance_indices.append(entry["handle"].index)
	for instance_index in instance_indices:
		if _gml_audio_instances.has(instance_index):
			entries.append(_gml_audio_instances[instance_index])
	return entries


static func _gml_audio_player_is_valid(player):
	if not is_instance_valid(player):
		return false
	return player is AudioStreamPlayer or player is AudioStreamPlayer2D or player is AudioStreamPlayer3D


static func _gml_audio_emitter_default_state():
	return {
		"handle": null,
		"x": 0.0,
		"y": 0.0,
		"z": 0.0,
		"vx": 0.0,
		"vy": 0.0,
		"vz": 0.0,
		"falloff_ref": 100.0,
		"falloff_max": 2000.0,
		"falloff_factor": 1.0,
		"gain": 1.0,
		"pitch": 1.0,
		"listener_mask": _gml_audio_global_listener_mask,
	}


static func _gml_audio_emitter_entry(emitter):
	if is_handle(emitter) and emitter.kind == GML_AUDIO_EMITTER_HANDLE_KIND and _gml_audio_emitters.has(emitter.index):
		return _gml_audio_emitters[emitter.index]
	var handle = gml_handle_from_value(GML_AUDIO_EMITTER_HANDLE_KIND, emitter)
	if gml_handle_is_valid(handle) and _gml_audio_emitters.has(handle.index):
		return _gml_audio_emitters[handle.index]
	return null


static func _gml_audio_listener_entry(index = 0):
	var listener_index = max(int(_to_real(index)), 0)
	if not _gml_audio_listener_state.has(listener_index):
		_gml_audio_listener_state[listener_index] = {
			"index": listener_index,
			"mask": 1 << listener_index,
			"x": 0.0,
			"y": 0.0,
			"z": 0.0,
			"vx": 0.0,
			"vy": 0.0,
			"vz": 0.0,
			"lookat_x": 0.0,
			"lookat_y": 0.0,
			"lookat_z": -1.0,
			"up_x": 0.0,
			"up_y": 1.0,
			"up_z": 0.0,
		}
	return _gml_audio_listener_state[listener_index]


static func _gml_audio_queue_entry(queue):
	if is_handle(queue) and queue.kind == GML_AUDIO_QUEUE_HANDLE_KIND and _gml_audio_queues.has(queue.index):
		return _gml_audio_queues[queue.index]
	var handle = gml_handle_from_value(GML_AUDIO_QUEUE_HANDLE_KIND, queue)
	if gml_handle_is_valid(handle) and _gml_audio_queues.has(handle.index):
		return _gml_audio_queues[handle.index]
	return null


static func _gml_audio_sync_group_entry(group_index):
	if is_handle(group_index) and group_index.kind == GML_AUDIO_SYNC_GROUP_HANDLE_KIND and _gml_audio_sync_groups.has(group_index.index):
		return _gml_audio_sync_groups[group_index.index]
	var handle = gml_handle_from_value(GML_AUDIO_SYNC_GROUP_HANDLE_KIND, group_index)
	if gml_handle_is_valid(handle) and _gml_audio_sync_groups.has(handle.index):
		return _gml_audio_sync_groups[handle.index]
	return null


static func _gml_audio_spatial_state(x, y, z, vx, vy, vz, gain, pitch, listener_mask, falloff_ref, falloff_max, falloff_factor, emitter_index):
	return {
		"x": _to_real(x),
		"y": _to_real(y),
		"z": _to_real(z),
		"vx": _to_real(vx),
		"vy": _to_real(vy),
		"vz": _to_real(vz),
		"gain": max(_to_real(gain), 0.0),
		"pitch": max(_to_real(pitch), GML_AUDIO_MIN_PITCH),
		"listener_mask": int(_to_real(listener_mask)) if listener_mask != null else _gml_audio_global_listener_mask,
		"falloff_ref": max(_to_real(falloff_ref), 0.0),
		"falloff_max": max(_to_real(falloff_max), 0.0),
		"falloff_factor": max(_to_real(falloff_factor), 0.0),
		"emitter_index": int(emitter_index),
	}


static func _gml_audio_spatial_state_from_emitter(emitter_entry, listener_mask = null):
	var handle = emitter_entry["handle"]
	return _gml_audio_spatial_state(
		emitter_entry.get("x", 0.0),
		emitter_entry.get("y", 0.0),
		emitter_entry.get("z", 0.0),
		emitter_entry.get("vx", 0.0),
		emitter_entry.get("vy", 0.0),
		emitter_entry.get("vz", 0.0),
		emitter_entry.get("gain", 1.0),
		emitter_entry.get("pitch", 1.0),
		listener_mask if listener_mask != null else emitter_entry.get("listener_mask", _gml_audio_global_listener_mask),
		emitter_entry.get("falloff_ref", 100.0),
		emitter_entry.get("falloff_max", 2000.0),
		emitter_entry.get("falloff_factor", 1.0),
		handle.index if is_handle(handle) else -1
	)


static func _gml_audio_apply_spatial_state_to_player(player, spatial_state):
	if not _gml_audio_player_is_valid(player):
		return
	if player is Node2D:
		player.position = Vector2(_to_real(spatial_state.get("x", 0.0)), _to_real(spatial_state.get("y", 0.0)))
		player.max_distance = max(_to_real(spatial_state.get("falloff_max", 2000.0)), 0.0)
		player.attenuation = max(_to_real(spatial_state.get("falloff_factor", 1.0)), 0.0)
		player.area_mask = max(int(_to_real(spatial_state.get("listener_mask", 1))), 1)
	elif player is Node3D:
		player.position = Vector3(
			_to_real(spatial_state.get("x", 0.0)),
			_to_real(spatial_state.get("y", 0.0)),
			_to_real(spatial_state.get("z", 0.0))
		)
		player.max_distance = max(_to_real(spatial_state.get("falloff_max", 2000.0)), 0.0)
		player.attenuation_filter_cutoff_hz = max(_to_real(spatial_state.get("falloff_ref", 100.0)), 0.0)


static func _gml_audio_apply_emitter_to_active_entries(emitter_entry):
	var handle = emitter_entry["handle"]
	if not is_handle(handle):
		return
	for sound_entry in _gml_audio_entries_for_emitter(handle.index):
		var spatial_state = _gml_audio_spatial_state_from_emitter(emitter_entry, sound_entry.get("listener_mask", null))
		sound_entry["spatial_state"] = _gml_clone_value(spatial_state, 8)
		_gml_audio_apply_spatial_state_to_player(sound_entry["player"], spatial_state)


static func _gml_audio_entries_for_emitter(emitter_index):
	var entries = []
	var requested_index = int(_to_real(emitter_index))
	for entry in _gml_audio_instances.values():
		if int(entry.get("emitter_index", -1)) == requested_index:
			entries.append(entry)
	return entries


static func _gml_audio_enforce_channel_limit():
	var active_entries = []
	for entry in _gml_audio_instances.values():
		if _gml_audio_instance_is_active(entry):
			active_entries.append(entry)
	if active_entries.size() <= _gml_audio_channel_limit:
		return
	active_entries.sort_custom(func(a, b):
		var priority_a = _to_real(a.get("priority", 0.0))
		var priority_b = _to_real(b.get("priority", 0.0))
		if priority_a == priority_b:
			return int(a["handle"].index) < int(b["handle"].index)
		return priority_a < priority_b
	)
	var remove_count = active_entries.size() - _gml_audio_channel_limit
	for i in range(remove_count):
		_gml_audio_unregister_instance(active_entries[i]["handle"].index, true)


static func _gml_audio_report_diagnostic(api_name, detail, severity = "partial"):
	var diagnostic = {
		"severity": str(severity),
		"api": str(api_name),
		"message": str(detail),
	}
	_gml_audio_diagnostics.append(diagnostic)
	if bool(_gml_audio_throw_on_error):
		push_error("GM2Godot audio runtime " + str(severity) + ": " + str(api_name) + ": " + str(detail))
	return diagnostic


static func _gml_audio_report_unsupported(api_name, detail):
	return _gml_audio_report_diagnostic(api_name, detail, "unsupported")
