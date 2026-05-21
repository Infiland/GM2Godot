const GML_SOUND_HANDLE_KIND = "sound"
const GML_AUDIO_MANAGER_NODE_NAME = "_GM2GodotAudioRuntime"
const GML_AUDIO_MIN_PITCH = 0.0001

static var _gml_audio_root = null
static var _gml_audio_instances = {}
static var _gml_audio_instances_by_asset = {}
static var _gml_audio_asset_state = {}
static var _gml_audio_group_state = {}
static var _gml_audio_master_gain = 1.0


static func gml_audio_play_sound(sound, priority, loop, gain = null, offset = null, pitch = null, listener_mask = null):
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
	var player = AudioStreamPlayer.new()
	player.name = "_gm_sound_" + str(asset_id) + "_" + str(_gml_handle_next_indices.get(GML_SOUND_HANDLE_KIND, 0))
	player.stream = _gml_audio_stream_for_playback(stream, loop)
	player.bus = _gml_audio_bus_for_group(audio_group)
	player.volume_linear = _gml_audio_final_gain(asset_state["gain"], group_state["gain"], instance_gain)
	player.pitch_scale = _gml_audio_final_pitch(asset_state["pitch"], instance_pitch)
	player.max_polyphony = 1
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
	return handle


static func gml_audio_stop_sound(sound):
	for entry in _gml_audio_target_entries(sound):
		_gml_audio_unregister_instance(entry["handle"].index, true)
	return null


static func gml_audio_pause_sound(sound):
	for entry in _gml_audio_target_entries(sound):
		var player = entry["player"]
		if player is AudioStreamPlayer and is_instance_valid(player):
			player.stream_paused = true
	return null


static func gml_audio_resume_sound(sound):
	for entry in _gml_audio_target_entries(sound):
		var player = entry["player"]
		if player is AudioStreamPlayer and is_instance_valid(player):
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
	if player is AudioStreamPlayer and is_instance_valid(player):
		player.volume_linear = _gml_audio_final_gain(entry["asset_gain"], entry["group_gain"], entry["instance_gain"])


static func _gml_audio_apply_entry_pitch(entry):
	var player = entry["player"]
	if player is AudioStreamPlayer and is_instance_valid(player):
		player.pitch_scale = _gml_audio_final_pitch(entry["asset_pitch"], entry["instance_pitch"])


static func _gml_audio_final_gain(asset_gain, group_gain, instance_gain):
	return max(_to_real(asset_gain), 0.0) * max(_to_real(group_gain), 0.0) * max(_to_real(instance_gain), 0.0) * _gml_audio_master_gain


static func _gml_audio_final_pitch(asset_pitch, instance_pitch):
	return max(_to_real(asset_pitch) * _to_real(instance_pitch), GML_AUDIO_MIN_PITCH)


static func _gml_audio_instance_is_active(entry):
	var player = entry["player"]
	if not (player is AudioStreamPlayer) or not is_instance_valid(player):
		return false
	return bool(entry.get("pending_play", false)) or bool(player.playing) or bool(player.stream_paused)


static func _gml_audio_player_finished(instance_index):
	if not _gml_audio_instances.has(instance_index):
		return
	var entry = _gml_audio_instances[instance_index]
	var player = entry["player"]
	if bool(entry["loop"]) and player is AudioStreamPlayer and is_instance_valid(player):
		player.play(0.0)
		return
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
	if player is AudioStreamPlayer and is_instance_valid(player):
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
