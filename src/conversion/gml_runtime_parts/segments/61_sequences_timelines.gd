const GML_SEQUENCE_TRACKS_UNSUPPORTED_MESSAGE = "GM2Godot preserves sequence playback metadata, but authored track/keyframe evaluation is not yet converted to AnimationPlayer tracks."


static func gml_timeline_exists(timeline):
	return _gml_timeline_asset_entry(timeline) != null


static func gml_timeline_get_name(timeline):
	var entry = _gml_timeline_asset_entry(timeline)
	if entry == null:
		return ""
	return str(entry["name"])


static func gml_timeline_moment_add_script(timeline, step, script):
	var entry = _gml_timeline_asset_entry(timeline)
	if entry == null:
		return false
	var asset_id = int(entry["id"])
	var moment = int(_to_real(step))
	if not _gml_timeline_moments_by_asset_id.has(asset_id):
		_gml_timeline_moments_by_asset_id[asset_id] = {}
	var moments = _gml_timeline_moments_by_asset_id[asset_id]
	if not moments.has(moment):
		moments[moment] = []
	moments[moment].append(script)
	return true


static func gml_timeline_moment_clear(timeline, step):
	var entry = _gml_timeline_asset_entry(timeline)
	if entry == null:
		return false
	var asset_id = int(entry["id"])
	if not _gml_timeline_moments_by_asset_id.has(asset_id):
		return true
	_gml_timeline_moments_by_asset_id[asset_id].erase(int(_to_real(step)))
	return true


static func gml_timeline_clear(timeline):
	var entry = _gml_timeline_asset_entry(timeline)
	if entry == null:
		return false
	_gml_timeline_moments_by_asset_id.erase(int(entry["id"]))
	return true


static func gml_timeline_size(timeline):
	var moments = _gml_timeline_moments(timeline)
	return moments.size() if moments != null else 0


static func gml_timeline_max_moment(timeline):
	var moments = _gml_timeline_moments(timeline)
	if moments == null or moments.is_empty():
		return -1
	var max_moment = -1
	for moment in moments.keys():
		max_moment = max(max_moment, int(moment))
	return max_moment


static func gml_timeline_step(instance):
	var state = _gml_timeline_state(instance)
	if state == null:
		return false
	if not bool(state.get("running", false)):
		return true
	var timeline = state.get("index", -1)
	if not gml_timeline_exists(timeline):
		return false
	var position = _to_real(state.get("position", 0.0))
	var speed_value = _to_real(state.get("speed", 1.0))
	var previous_position = position
	position += speed_value
	var max_moment = gml_timeline_max_moment(timeline)
	if bool(state.get("loop", false)) and max_moment >= 0 and position > float(max_moment):
		position = 0.0
	state["position"] = position
	_gml_timeline_apply_state(instance, state)
	_gml_timeline_dispatch_between(instance, timeline, previous_position, position, speed_value)
	return true


static func gml_sequence_exists(sequence):
	return _gml_sequence_asset_entry(sequence) != null or _gml_sequence_resolve_object(sequence) != null or gml_handle_is_valid(gml_handle_from_value(GML_SEQUENCE_HANDLE_KIND, sequence))


static func gml_sequence_get(sequence):
	var existing = _gml_sequence_resolve_object(sequence)
	if existing != null:
		return existing
	var entry = _gml_sequence_asset_entry(sequence)
	if entry == null:
		return {}
	var object = _gml_sequence_object_from_entry(entry)
	_gml_sequence_objects_by_id[int(object["id"])] = object
	return object


static func gml_sequence_create():
	var sequence_id = gml_asset_register_dynamic("sequence_" + str(_gml_asset_next_dynamic_id), "sequence")
	var object = _gml_sequence_object_from_entry(_gml_asset_resolve(sequence_id))
	object["dynamic"] = true
	_gml_sequence_objects_by_id[int(object["id"])] = object
	return object


static func gml_sequence_destroy(sequence):
	var object = _gml_sequence_resolve_object(sequence)
	if object == null:
		return false
	var sequence_id = int(object["id"])
	_gml_sequence_objects_by_id.erase(sequence_id)
	gml_asset_release(sequence_id)
	return true


static func gml_layer_sequence_create(layer, x, y, sequence):
	var layer_node = _gml_layer_resolve_node(layer)
	if layer_node == null:
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	var sequence_object = gml_sequence_get(sequence)
	if typeof(sequence_object) != TYPE_DICTIONARY or sequence_object.is_empty():
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	var node = Node2D.new()
	node.name = "Sequence_" + str(sequence_object.get("name", sequence_object.get("id", "dynamic")))
	node.position = Vector2(_to_real(x), _to_real(y))
	node.set_meta("gamemaker_sequence_instance", true)
	node.set_meta("gamemaker_sequence_asset", sequence_object.get("id", -1))
	node.set_meta("gamemaker_sequence_name", sequence_object.get("name", ""))
	layer_node.add_child(node)
	var instance = _gml_sequence_instance_record(node, sequence_object)
	var handle = _gml_layer_element_register(node)
	instance["elementID"] = handle
	_gml_sequence_elements_by_index[handle.index] = instance
	if _gml_sequence_has_tracks(sequence_object):
		push_warning(GML_SEQUENCE_TRACKS_UNSUPPORTED_MESSAGE)
	return handle


static func gml_layer_sequence_destroy(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return false
	var element = instance.get("elementID", null)
	var node = _gml_layer_element_resolve_node(element)
	if element is GMLHandle:
		_gml_sequence_elements_by_index.erase(element.index)
		_gml_layer_element_unregister_handle(element)
	if node is Node:
		if node.is_inside_tree():
			node.queue_free()
		else:
			node.free()
	return true


static func gml_layer_sequence_get_instance(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return {}
	return instance


static func gml_layer_sequence_headpos(sequence_element_id, position):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return false
	instance["headPosition"] = _gml_sequence_clamp_head_position(instance, _to_real(position))
	return true


static func gml_layer_sequence_get_headpos(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return 0.0
	return _to_real(instance.get("headPosition", 0.0))


static func gml_layer_sequence_speedscale(sequence_element_id, speedscale):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return false
	instance["speedScale"] = _to_real(speedscale)
	return true


static func gml_layer_sequence_get_speedscale(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return 0.0
	return _to_real(instance.get("speedScale", 1.0))


static func gml_layer_sequence_headdir(sequence_element_id, direction):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return false
	var resolved_direction = -1 if _to_real(direction) < 0.0 else 1
	instance["headDirection"] = resolved_direction
	return true


static func gml_layer_sequence_get_headdir(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return 1
	return int(instance.get("headDirection", 1))


static func gml_layer_sequence_pause(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return false
	instance["paused"] = true
	return true


static func gml_layer_sequence_play(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return false
	instance["paused"] = false
	instance["finished"] = false
	return true


static func gml_layer_sequence_is_paused(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	return bool(instance.get("paused", false)) if instance != null else false


static func gml_layer_sequence_is_finished(sequence_element_id):
	var instance = _gml_sequence_instance(sequence_element_id)
	return bool(instance.get("finished", false)) if instance != null else false


static func gml_layer_sequence_step(sequence_element_id, frames = 1.0):
	var instance = _gml_sequence_instance(sequence_element_id)
	if instance == null:
		return false
	if bool(instance.get("paused", false)) or bool(instance.get("finished", false)):
		return true
	var delta = _to_real(frames) * _to_real(instance.get("speedScale", 1.0)) * float(instance.get("headDirection", 1))
	var previous_position = _to_real(instance.get("headPosition", 0.0))
	var next_position = _to_real(instance.get("headPosition", 0.0)) + delta
	instance["headPosition"] = _gml_sequence_clamp_head_position(instance, next_position)
	_gml_sequence_dispatch_between(instance, previous_position, _to_real(instance["headPosition"]), delta)
	return true


static func _gml_timeline_asset_entry(timeline):
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(timeline)
	if entry == null or str(entry.get("type", "")) != "timeline":
		return null
	return entry


static func _gml_timeline_moments(timeline):
	var entry = _gml_timeline_asset_entry(timeline)
	if entry == null:
		return null
	var asset_id = int(entry["id"])
	if not _gml_timeline_moments_by_asset_id.has(asset_id):
		_gml_timeline_moments_by_asset_id[asset_id] = _gml_timeline_seed_moments(entry)
	return _gml_timeline_moments_by_asset_id[asset_id]


static func _gml_timeline_state(instance):
	if instance == null:
		return null
	var key = instance.get_instance_id() if instance is Object else int(_to_real(instance))
	if _gml_timeline_moments_by_asset_id == null:
		return null
	if not _gml_timeline_states_by_instance_id.has(key):
		_gml_timeline_states_by_instance_id[key] = {
			"index": _gml_object_timeline_get(instance, "timeline_index", -1),
			"position": _gml_object_timeline_get(instance, "timeline_position", 0.0),
			"speed": _gml_object_timeline_get(instance, "timeline_speed", 1.0),
			"running": _gml_object_timeline_get(instance, "timeline_running", false),
			"loop": _gml_object_timeline_get(instance, "timeline_loop", false),
		}
	return _gml_timeline_states_by_instance_id[key]


static func _gml_timeline_apply_state(instance, state):
	if instance is Object:
		if _object_has_property(instance, "timeline_index"):
			instance.set("timeline_index", state["index"])
		if _object_has_property(instance, "timeline_position"):
			instance.set("timeline_position", state["position"])
		if _object_has_property(instance, "timeline_speed"):
			instance.set("timeline_speed", state["speed"])
		if _object_has_property(instance, "timeline_running"):
			instance.set("timeline_running", state["running"])
		if _object_has_property(instance, "timeline_loop"):
			instance.set("timeline_loop", state["loop"])


static func _gml_timeline_dispatch_between(instance, timeline, previous_position, position, speed_value):
	var moments = _gml_timeline_moments(timeline)
	if moments == null:
		return
	var ordered_moments = moments.keys()
	ordered_moments.sort()
	if speed_value < 0.0:
		ordered_moments.reverse()
	for moment in ordered_moments:
		var moment_value = float(moment)
		if speed_value >= 0.0 and (moment_value <= previous_position or moment_value > position):
			continue
		if speed_value < 0.0 and (moment_value >= previous_position or moment_value < position):
			continue
		for action in moments[moment]:
			_gml_sequence_timeline_dispatch_action(instance, action)


static func _gml_object_timeline_get(instance, member_name, fallback):
	if instance is Object and _object_has_property(instance, member_name):
		return instance.get(member_name)
	return fallback


static func _gml_sequence_asset_entry(sequence):
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(sequence)
	if entry == null or str(entry.get("type", "")) != "sequence":
		return null
	return entry


static func _gml_sequence_resolve_object(sequence):
	if typeof(sequence) == TYPE_DICTIONARY and sequence.has("id"):
		return sequence
	var entry = _gml_sequence_asset_entry(sequence)
	if entry != null:
		var asset_id = int(entry["id"])
		if _gml_sequence_objects_by_id.has(asset_id):
			return _gml_sequence_objects_by_id[asset_id]
		return _gml_sequence_object_from_entry(entry)
	if is_numeric(sequence):
		var sequence_id = _to_int64_value(sequence)
		if _gml_sequence_objects_by_id.has(sequence_id):
			return _gml_sequence_objects_by_id[sequence_id]
	return null


static func _gml_sequence_object_from_entry(entry):
	if entry == null:
		return {}
	var metadata = entry.get("metadata", {}) if entry.has("metadata") else {}
	var length = _to_real(metadata.get("length", 0.0)) if typeof(metadata) == TYPE_DICTIONARY else 0.0
	var playback_speed = _to_real(metadata.get("playback_speed", 1.0)) if typeof(metadata) == TYPE_DICTIONARY else 1.0
	var loopmode = int(metadata.get("loopmode", 0)) if typeof(metadata) == TYPE_DICTIONARY else 0
	return {
		"id": int(entry["id"]),
		"name": str(entry["name"]),
		"asset": int(entry["id"]),
		"length": length,
		"playbackSpeed": playback_speed,
		"loopmode": loopmode,
		"tracks": metadata.get("tracks", []) if typeof(metadata) == TYPE_DICTIONARY else [],
		"moments": metadata.get("moments", []) if typeof(metadata) == TYPE_DICTIONARY else [],
		"broadcasts": metadata.get("broadcasts", []) if typeof(metadata) == TYPE_DICTIONARY else [],
		"metadata": metadata,
	}


static func _gml_sequence_instance_record(node, sequence_object):
	return {
		"sequence": sequence_object,
		"sequence_id": int(sequence_object.get("id", -1)),
		"elementID": gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND),
		"node": node,
		"owner": _gml_sequence_owner_for_node(node),
		"headPosition": 0.0,
		"headDirection": 1,
		"speedScale": 1.0,
		"paused": false,
		"finished": false,
		"activeTracks": [],
		"eventLog": [],
	}


static func _gml_sequence_instance(sequence_element_id):
	if is_handle(sequence_element_id):
		if sequence_element_id.kind == GML_LAYER_ELEMENT_HANDLE_KIND and _gml_sequence_elements_by_index.has(sequence_element_id.index):
			return _gml_sequence_elements_by_index[sequence_element_id.index]
		return null
	if is_numeric(sequence_element_id):
		var handle = gml_handle_get(GML_LAYER_ELEMENT_HANDLE_KIND, _to_int64_value(sequence_element_id))
		if gml_handle_is_valid(handle) and _gml_sequence_elements_by_index.has(handle.index):
			return _gml_sequence_elements_by_index[handle.index]
	return null


static func _gml_sequence_clamp_head_position(instance, position):
	var sequence_object = instance.get("sequence", {})
	var length = _to_real(sequence_object.get("length", 0.0)) if typeof(sequence_object) == TYPE_DICTIONARY else 0.0
	if length <= 0.0:
		return max(_to_real(position), 0.0)
	var loopmode = int(sequence_object.get("loopmode", 0)) if typeof(sequence_object) == TYPE_DICTIONARY else 0
	if loopmode == 1:
		return fposmod(_to_real(position), length)
	var clamped = clamp(_to_real(position), 0.0, length)
	instance["finished"] = clamped >= length
	return clamped


static func _gml_sequence_has_tracks(sequence_object):
	return typeof(sequence_object) == TYPE_DICTIONARY and sequence_object.has("tracks") and not sequence_object["tracks"].is_empty()


static func _gml_timeline_seed_moments(entry):
	var seeded = {}
	var metadata = entry.get("metadata", {}) if entry.has("metadata") else {}
	if typeof(metadata) != TYPE_DICTIONARY:
		return seeded
	var authored_moments = metadata.get("moments", [])
	if typeof(authored_moments) != TYPE_ARRAY:
		return seeded
	for moment in authored_moments:
		if typeof(moment) != TYPE_DICTIONARY:
			continue
		var frame = int(_to_real(moment.get("frame", 0)))
		if not seeded.has(frame):
			seeded[frame] = []
		var actions = moment.get("actions", [])
		if typeof(actions) == TYPE_ARRAY:
			for action in actions:
				seeded[frame].append(action)
	return seeded


static func _gml_sequence_dispatch_between(instance, previous_position, position, speed_value):
	var sequence_object = instance.get("sequence", {})
	if typeof(sequence_object) != TYPE_DICTIONARY:
		return
	var actions = []
	for key in ["moments", "broadcasts"]:
		var events = sequence_object.get(key, [])
		if typeof(events) != TYPE_ARRAY:
			continue
		for event in events:
			if typeof(event) != TYPE_DICTIONARY:
				continue
			var frame = _to_real(event.get("frame", 0.0))
			if speed_value >= 0.0 and (frame <= previous_position or frame > position):
				continue
			if speed_value < 0.0 and (frame >= previous_position or frame < position):
				continue
			var event_action = {}
			for event_key in event.keys():
				event_action[event_key] = event[event_key]
			event_action["kind"] = key.trim_suffix("s")
			event_action["owner"] = instance.get("owner", null)
			event_action["node"] = instance.get("node", null)
			actions.append(event_action)
	actions.sort_custom(_gml_sequence_event_sort)
	for action in actions:
		instance["eventLog"].append(action)
		_gml_sequence_timeline_dispatch_action(instance.get("owner", null), action)


static func _gml_sequence_event_sort(left, right):
	var left_frame = _to_real(left.get("frame", 0.0)) if typeof(left) == TYPE_DICTIONARY else 0.0
	var right_frame = _to_real(right.get("frame", 0.0)) if typeof(right) == TYPE_DICTIONARY else 0.0
	if left_frame == right_frame:
		return str(left.get("kind", "")) < str(right.get("kind", ""))
	return left_frame < right_frame


static func _gml_sequence_timeline_dispatch_action(instance, action):
	if action is Callable:
		gml_script_execute(action, [instance])
		return
	if typeof(action) != TYPE_DICTIONARY:
		gml_script_execute(action, [instance])
		return
	var owner = action.get("owner", instance)
	var callable_name = action.get("callable", "")
	if is_string(callable_name) and owner is Object and owner.has_method(str(callable_name)):
		owner.call(str(callable_name), instance, action)
		return
	var script_path = action.get("script_path", "")
	if is_string(script_path) and str(script_path) != "":
		_gml_sequence_timeline_execute_script_path(str(script_path), instance)
		return
	var script = action.get("script", null)
	if script != null:
		gml_script_execute(script, [instance])


static func _gml_sequence_timeline_execute_script_path(script_path, instance):
	var script_resource = load(script_path)
	if script_resource != null and script_resource.has_method("execute"):
		script_resource.execute(instance)


static func _gml_sequence_owner_for_node(node):
	if node is Node and node.is_inside_tree() and node.get_tree().current_scene is Node:
		return node.get_tree().current_scene
	if node is Node:
		var parent = node.get_parent()
		while parent is Node:
			if parent.get_parent() == null:
				return parent
			parent = parent.get_parent()
	return node
