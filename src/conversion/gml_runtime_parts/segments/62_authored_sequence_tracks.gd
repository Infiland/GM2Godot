const GML_SEQUENCE_MAX_NESTING_DEPTH = 16
const GML_SEQUENCE_TRACK_NODE_PREFIX = "GMSequenceTrack_"


static func gml_sequence_timeline_scheduler_frame(delta_seconds = 0.0, delta_frames = 1, timeline_instances = null, frame = -1):
	var sequence_indices = _gml_sequence_elements_by_index.keys()
	sequence_indices.sort()
	var frames = max(1, int(delta_frames))
	for sequence_index in sequence_indices:
		if not _gml_sequence_elements_by_index.has(sequence_index):
			continue
		var instance = _gml_sequence_elements_by_index[sequence_index]
		if typeof(instance) != TYPE_DICTIONARY:
			continue
		var sequence_node = instance.get("node", null)
		if (
			not (sequence_node is Node)
			or not is_instance_valid(sequence_node)
			or sequence_node.is_queued_for_deletion()
		):
			_gml_sequence_release_element_record(sequence_index, instance)
			continue
		if bool(instance.get("paused", false)) or bool(instance.get("finished", false)):
			continue
		var sequence_object = instance.get("sequence", {})
		if typeof(sequence_object) != TYPE_DICTIONARY:
			continue
		var playback_speed = max(_to_real(sequence_object.get("playbackSpeed", 1.0)), 0.0)
		var playback_speed_type = int(sequence_object.get("playbackSpeedType", 0))
		var base_delta = (
			playback_speed * max(_to_real(delta_seconds), 0.0)
			if playback_speed_type == 0
			else playback_speed * float(frames)
		)
		var delta = (
			base_delta
			* _to_real(instance.get("speedScale", 1.0))
			* float(instance.get("headDirection", 1))
		)
		_gml_sequence_advance_instance(instance, delta)
	var targets = (
		timeline_instances
		if timeline_instances is Array
		else _gml_event_scheduler_live_instances()
	)
	for _frame_index in range(frames):
		for target in targets:
			if not _gml_event_scheduler_instance_valid(target):
				continue
			if not bool(_gml_object_timeline_get(target, "timeline_running", false)):
				continue
			gml_timeline_step(target)
	if frame >= 0:
		_gml_event_scheduler_record_phase(
			"sequences_timelines",
			"gml_sequence_timeline_scheduler_frame",
			null,
			frame
		)
	return null


static func _gml_sequence_prepare_instance(instance):
	if typeof(instance) != TYPE_DICTIONARY:
		return
	var existing_node = instance.get("node", null)
	var existing_owner = instance.get("owner", null)
	_gml_sequence_cleanup_instance(instance)
	instance["node"] = existing_node
	instance["owner"] = existing_owner
	var sequence_object = instance.get("sequence", {})
	var node = instance.get("node", null)
	if typeof(sequence_object) != TYPE_DICTIONARY or not (node is Node):
		instance["trackStates"] = []
		instance["activeTracks"] = []
		return
	var descriptors = sequence_object.get("tracks", [])
	if typeof(descriptors) != TYPE_ARRAY:
		descriptors = []
	var states = []
	var track_count = descriptors.size()
	for track_index in range(track_count):
		var descriptor = descriptors[track_index]
		if typeof(descriptor) != TYPE_DICTIONARY:
			continue
		var state = _gml_sequence_prepare_track(
			instance,
			descriptor,
			node,
			track_index,
			track_count,
			0,
			true
		)
		if state == null:
			continue
		states.append(state)
	instance["trackStates"] = states
	instance["activeTracks"] = []


static func _gml_sequence_prepare_track(instance, descriptor, parent_node, track_index, track_count, nesting_depth, root_track):
	if typeof(descriptor) != TYPE_DICTIONARY or not (parent_node is Node):
		return null
	var track_node = Node2D.new()
	track_node.name = GML_SEQUENCE_TRACK_NODE_PREFIX + str(track_index)
	track_node.z_index = track_count - track_index
	track_node.visible = false
	track_node.set_meta("gamemaker_sequence_track_name", str(descriptor.get("name", "")))
	track_node.set_meta("gamemaker_sequence_track_path", str(descriptor.get("path", "")))
	track_node.set_meta("gamemaker_sequence_track_kind", str(descriptor.get("kind", "")))
	parent_node.add_child(track_node)
	var evaluation = {
		"track": descriptor,
		"parent": instance,
		"activeTracks": [],
		"posx": 0.0,
		"posy": 0.0,
		"rotation": 0.0,
		"xorigin": 0.0,
		"yorigin": 0.0,
		"scalex": 1.0,
		"scaley": 1.0,
		"colourmultiply": [1.0, 1.0, 1.0, 1.0],
	}
	var state = {
		"instance": instance,
		"descriptor": descriptor,
		"node": track_node,
		"evaluation": evaluation,
		"contents": {},
		"nested": {},
		"children": [],
		"active_key": -1,
		"audio_key": -1,
		"audio_bus": "",
		"audio_effects": [],
		"nesting_depth": nesting_depth,
		"root_track": root_track,
	}
	if str(descriptor.get("kind", "")) == "audio":
		_gml_sequence_prepare_audio_bus(state)
	var child_descriptors = descriptor.get("children", [])
	if child_descriptors is Array:
		var child_count = child_descriptors.size()
		for child_index in range(child_count):
			var child_descriptor = child_descriptors[child_index]
			if typeof(child_descriptor) != TYPE_DICTIONARY:
				continue
			var child_state = _gml_sequence_prepare_track(
				instance,
				child_descriptor,
				track_node,
				child_index,
				child_count,
				nesting_depth,
				false
			)
			if child_state != null:
				state["children"].append(child_state)
				evaluation["activeTracks"].append(child_state["evaluation"])
	if str(descriptor.get("kind", "")) == "instance":
		var keyframes = descriptor.get("keyframes", [])
		if keyframes is Array:
			for key_index in range(keyframes.size()):
				_gml_sequence_track_content(state, key_index)
	return state


static func _gml_sequence_evaluate_instance(instance):
	if typeof(instance) != TYPE_DICTIONARY:
		return
	var position = _to_real(instance.get("headPosition", 0.0))
	var states = instance.get("trackStates", [])
	if not (states is Array):
		return
	if instance.get("activeTracks", []).is_empty() and not states.is_empty():
		var active_tracks = []
		for state in states:
			if typeof(state) == TYPE_DICTIONARY:
				active_tracks.append(state["evaluation"])
		instance["activeTracks"] = active_tracks
	for state in states:
		_gml_sequence_evaluate_track(instance, state, position, true)


static func _gml_sequence_evaluate_track(instance, state, position, parent_active):
	if typeof(state) != TYPE_DICTIONARY:
		return
	var descriptor = state.get("descriptor", {})
	var track_node = state.get("node", null)
	if typeof(descriptor) != TYPE_DICTIONARY or not (track_node is Node2D):
		return
	var keyframes = descriptor.get("keyframes", [])
	var active_key = _gml_sequence_active_key_index(keyframes, position)
	var track_active = (
		parent_active
		and bool(descriptor.get("enabled", true))
		and bool(descriptor.get("visible", true))
		and active_key >= 0
	)
	state["active_key"] = active_key
	track_node.visible = track_active
	var content = null
	if active_key >= 0:
		content = _gml_sequence_track_content(state, active_key)
	elif (
		str(descriptor.get("kind", "")) == "instance"
		and not state["contents"].is_empty()
	):
		content = state["contents"].values()[0]
	for key_index in state["contents"].keys():
		var key_content = state["contents"][key_index]
		if key_content is CanvasItem:
			key_content.visible = track_active and int(key_index) == active_key
	var values = _gml_sequence_track_values(descriptor, position)
	_gml_sequence_apply_track_values(
		instance,
		state,
		content,
		values,
		position,
		track_active
	)
	for child_state in state.get("children", []):
		_gml_sequence_evaluate_track(
			instance,
			child_state,
			position,
			track_active
		)


static func _gml_sequence_track_content(state, key_index):
	if typeof(state) != TYPE_DICTIONARY:
		return null
	if state["contents"].has(key_index):
		var existing = state["contents"][key_index]
		return existing if existing == null or is_instance_valid(existing) else null
	var descriptor = state.get("descriptor", {})
	var keyframes = descriptor.get("keyframes", [])
	if not (keyframes is Array) or key_index < 0 or key_index >= keyframes.size():
		return null
	var keyframe = keyframes[key_index]
	if typeof(keyframe) != TYPE_DICTIONARY or bool(keyframe.get("disabled", false)):
		state["contents"][key_index] = null
		return null
	var kind = str(descriptor.get("kind", ""))
	var content = _gml_sequence_create_content(kind, keyframe, state)
	state["contents"][key_index] = content
	return content


static func _gml_sequence_create_content(kind, keyframe, state):
	var track_node = state.get("node", null)
	if not (track_node is Node):
		return null
	var content = null
	var asset_name = str(keyframe.get("asset", ""))
	var entry = _gml_asset_resolve(asset_name) if asset_name != "" else null
	if kind == "text":
		var label = Label.new()
		label.mouse_filter = Control.MOUSE_FILTER_IGNORE
		label.text = str(keyframe.get("text", ""))
		label.clip_text = true
		label.autowrap_mode = (
			TextServer.AUTOWRAP_WORD_SMART
			if bool(keyframe.get("wrap", false))
			else TextServer.AUTOWRAP_OFF
		)
		label.horizontal_alignment = int(keyframe.get("alignment_h", 0))
		label.vertical_alignment = int(keyframe.get("alignment_v", 0))
		_gml_sequence_apply_text_font(label, entry)
		content = label
	elif kind == "audio":
		var player = AudioStreamPlayer2D.new()
		if entry != null:
			player.stream = _gml_audio_stream_for_entry(entry)
		var bus_name = str(state.get("audio_bus", ""))
		if bus_name != "":
			player.bus = bus_name
		content = player
	elif kind == "sequence":
		var nested_node = Node2D.new()
		nested_node.name = "NestedSequence"
		content = nested_node
	elif kind in ["sprite", "instance"]:
		content = _gml_sequence_instantiate_asset_content(entry, kind)
	if content == null:
		content = Node2D.new()
	content.name = "Key_" + str(int(keyframe.get("order", 0)))
	track_node.add_child(content)
	if content is CanvasItem:
		content.visible = false
	if kind == "instance":
		content.set_meta("gamemaker_in_sequence", true)
		var object_selector = asset_name
		if entry != null and entry.has("id"):
			object_selector = int(entry.get("id", -1))
		var handle = _gml_instance_handle_for_node(content)
		if not gml_handle_is_valid(handle):
			handle = gml_instance_register(content, object_selector, [])
		content.set_meta("gamemaker_sequence_instance_handle", handle)
		gml_variable_instance_set(content, "in_sequence", true)
		gml_variable_instance_set(content, "drawn_by_sequence", true)
		gml_variable_instance_set(
			content,
			"sequence_instance",
			state.get("instance", {})
		)
	elif kind == "sequence":
		_gml_sequence_prepare_nested_content(state, keyframe, content)
	return content


static func _gml_sequence_instantiate_asset_content(entry, kind):
	if entry == null:
		return null
	var resource = entry.get("resource", null)
	var resource_path = str(entry.get("godot_path", ""))
	if resource == null and resource_path != "" and ResourceLoader.exists(resource_path):
		resource = load(resource_path)
	if resource is PackedScene:
		var instantiated = resource.instantiate()
		if instantiated is Node:
			if kind == "sprite" and instantiated is Area2D:
				instantiated.collision_layer = 0
				instantiated.collision_mask = 0
				instantiated.monitoring = false
				instantiated.monitorable = false
			return instantiated
	if kind == "sprite" and resource is Texture2D:
		var sprite = Sprite2D.new()
		sprite.texture = resource
		return sprite
	return null


static func _gml_sequence_prepare_nested_content(state, keyframe, content):
	var nesting_depth = int(state.get("nesting_depth", 0))
	if nesting_depth >= GML_SEQUENCE_MAX_NESTING_DEPTH:
		content.set_meta("gamemaker_sequence_nesting_rejected", true)
		return
	var nested_entry = _gml_sequence_asset_entry(keyframe.get("asset", ""))
	if nested_entry == null:
		return
	var nested_object = _gml_sequence_object_from_entry(nested_entry)
	var nested_instance = _gml_sequence_instance_record(content, nested_object)
	nested_instance["owner"] = _gml_sequence_owner_for_node(content)
	nested_instance["nestingDepth"] = nesting_depth + 1
	_gml_sequence_prepare_instance_with_depth(
		nested_instance,
		nesting_depth + 1
	)
	state["nested"][int(keyframe.get("order", 0))] = nested_instance


static func _gml_sequence_prepare_instance_with_depth(instance, nesting_depth):
	if typeof(instance) != TYPE_DICTIONARY:
		return
	var sequence_object = instance.get("sequence", {})
	var node = instance.get("node", null)
	if typeof(sequence_object) != TYPE_DICTIONARY or not (node is Node):
		return
	var descriptors = sequence_object.get("tracks", [])
	if not (descriptors is Array):
		return
	var states = []
	var active_tracks = []
	for track_index in range(descriptors.size()):
		var descriptor = descriptors[track_index]
		if typeof(descriptor) != TYPE_DICTIONARY:
			continue
		var state = _gml_sequence_prepare_track(
			instance,
			descriptor,
			node,
			track_index,
			descriptors.size(),
			nesting_depth,
			true
		)
		if state != null:
			states.append(state)
			active_tracks.append(state["evaluation"])
	instance["trackStates"] = states
	instance["activeTracks"] = active_tracks
	_gml_sequence_evaluate_instance(instance)


static func _gml_sequence_apply_track_values(instance, state, content, values, position, track_active):
	var track_node = state["node"]
	var evaluation = state["evaluation"]
	var pos = values["position"]
	var origin = values["origin"]
	var scale_value = values["scale"]
	var colour = values["colour"]
	var track_position = Vector2(_to_real(pos[0]), _to_real(pos[1]))
	if bool(state.get("root_track", false)):
		var sequence_object = instance.get("sequence", {})
		if typeof(sequence_object) == TYPE_DICTIONARY:
			track_position -= Vector2(
				_to_real(sequence_object.get("xorigin", 0.0)),
				_to_real(sequence_object.get("yorigin", 0.0))
			)
	track_node.position = track_position
	track_node.rotation_degrees = -_to_real(values["rotation"])
	track_node.scale = Vector2(_to_real(scale_value[0]), _to_real(scale_value[1]))
	track_node.modulate = Color(
		clamp(_to_real(colour[1]), 0.0, 1.0),
		clamp(_to_real(colour[2]), 0.0, 1.0),
		clamp(_to_real(colour[3]), 0.0, 1.0),
		clamp(_to_real(colour[0]), 0.0, 1.0)
	)
	if content is Node2D:
		content.position = -Vector2(_to_real(origin[0]), _to_real(origin[1]))
	elif content is Control:
		content.position = -Vector2(_to_real(origin[0]), _to_real(origin[1]))
	evaluation["posx"] = _to_real(pos[0])
	evaluation["posy"] = _to_real(pos[1])
	evaluation["rotation"] = _to_real(values["rotation"])
	evaluation["xorigin"] = _to_real(origin[0])
	evaluation["yorigin"] = _to_real(origin[1])
	evaluation["scalex"] = _to_real(scale_value[0])
	evaluation["scaley"] = _to_real(scale_value[1])
	evaluation["matrix"] = track_node.transform
	evaluation["colourmultiply"] = _gml_clone_value(colour, 8)
	var descriptor = state["descriptor"]
	var kind = str(descriptor.get("kind", ""))
	var active_key = int(state.get("active_key", -1))
	var keyframe = null
	var keyframes = descriptor.get("keyframes", [])
	if keyframes is Array and active_key >= 0 and active_key < keyframes.size():
		keyframe = keyframes[active_key]
	if kind == "sprite":
		_gml_sequence_apply_sprite_values(content, values)
		evaluation["spriteIndex"] = (
			gml_asset_get_index(keyframe.get("asset", ""))
			if keyframe != null
			else -1
		)
		evaluation["imageindex"] = _to_real(values["image_index"])
		evaluation["imagespeed"] = _to_real(values["image_speed"])
	elif kind == "instance":
		evaluation["instanceID"] = content
		evaluation["imageindex"] = _to_real(values["image_index"])
		evaluation["imagespeed"] = _to_real(values["image_speed"])
		_gml_sequence_apply_sprite_values(content, values)
	elif kind == "text":
		evaluation["frameSizeX"] = _to_real(values["frameSize"][0])
		evaluation["frameSizeY"] = _to_real(values["frameSize"][1])
		evaluation["characterSpacing"] = _to_real(values["characterSpacing"])
		evaluation["lineSpacing"] = _to_real(values["lineSpacing"])
		evaluation["paragraphSpacing"] = _to_real(values["paragraphSpacing"])
		evaluation["effectsEnabled"] = (
			bool(keyframe.get("effects_enabled", false))
			if keyframe != null
			else false
		)
		evaluation["glowEnabled"] = (
			bool(keyframe.get("glow_enabled", false))
			if keyframe != null
			else false
		)
		evaluation["outlineEnabled"] = (
			bool(keyframe.get("outline_enabled", false))
			if keyframe != null
			else false
		)
		evaluation["dropShadowEnabled"] = (
			bool(keyframe.get("shadow_enabled", false))
			if keyframe != null
			else false
		)
		_gml_sequence_apply_text_values(content, keyframe, values)
	elif kind == "audio":
		evaluation["gain"] = _to_real(values["gain"])
		evaluation["pitch"] = _to_real(values["pitch"])
		evaluation["falloff"] = _to_real(values["falloff"][2])
		evaluation["falloffRef"] = _to_real(values["falloff"][0])
		evaluation["falloffMax"] = _to_real(values["falloff"][1])
		evaluation["falloffFactor"] = _to_real(values["falloff"][2])
		_gml_sequence_apply_audio_values(
			instance,
			state,
			content,
			keyframe,
			values,
			position,
			track_active
		)
	elif kind == "sequence":
		evaluation["sequenceID"] = (
			gml_asset_get_index(keyframe.get("asset", ""))
			if keyframe != null
			else -1
		)
		_gml_sequence_apply_nested_values(
			state,
			keyframe,
			position,
			track_active
		)


static func _gml_sequence_track_values(descriptor, position):
	var values = {
		"position": [0.0, 0.0],
		"rotation": 0.0,
		"origin": [0.0, 0.0],
		"scale": [1.0, 1.0],
		"colour": [1.0, 1.0, 1.0, 1.0],
		"image_index": 0.0,
		"image_speed": 1.0,
		"gain": 1.0,
		"pitch": 1.0,
		"falloff": [1.0, 100000.0, 1.0],
		"frameSize": [0.0, 0.0],
		"characterSpacing": 0.0,
		"lineSpacing": 0.0,
		"paragraphSpacing": 0.0,
		"text_effects": {},
	}
	var parameters = descriptor.get("parameters", [])
	if not (parameters is Array):
		return values
	for parameter in parameters:
		if typeof(parameter) != TYPE_DICTIONARY:
			continue
		if not bool(parameter.get("enabled", true)):
			continue
		if str(parameter.get("kind", "")) == "audio_effect":
			continue
		var evaluated = _gml_sequence_parameter_value(parameter, position)
		if not (evaluated is Array) or evaluated.is_empty():
			continue
		var name = str(parameter.get("name", ""))
		if name == "position":
			values["position"] = _gml_sequence_vector_values(evaluated, [0.0, 0.0])
		elif name == "rotation":
			values["rotation"] = _to_real(evaluated[0])
		elif name == "origin":
			values["origin"] = _gml_sequence_vector_values(evaluated, [0.0, 0.0])
		elif name == "scale":
			values["scale"] = _gml_sequence_vector_values(evaluated, [1.0, 1.0])
		elif name == "blend_multiply":
			if evaluated[0] is Array and evaluated[0].size() >= 4:
				values["colour"] = _gml_clone_value(evaluated[0], 8)
		elif name == "image_index":
			values["image_index"] = _to_real(evaluated[0])
		elif name == "image_speed":
			values["image_speed"] = _to_real(evaluated[0])
		elif name in ["gain", "volume"]:
			values["gain"] = _to_real(evaluated[0])
		elif name == "pitch":
			values["pitch"] = _to_real(evaluated[0])
		elif name == "falloff":
			values["falloff"] = _gml_sequence_vector_values(
				evaluated,
				[1.0, 100000.0, 1.0]
			)
		elif name == "frameSize":
			values["frameSize"] = _gml_sequence_vector_values(
				evaluated,
				[0.0, 0.0]
			)
		elif name in ["characterSpacing", "lineSpacing", "paragraphSpacing"]:
			values[name] = _to_real(evaluated[0])
		else:
			values["text_effects"][name] = evaluated[0]
	return values


static func _gml_sequence_parameter_value(parameter, position):
	var keyframes = parameter.get("keyframes", [])
	if not (keyframes is Array):
		return []
	var enabled_keys = []
	for keyframe in keyframes:
		if typeof(keyframe) == TYPE_DICTIONARY and not bool(keyframe.get("disabled", false)):
			enabled_keys.append(keyframe)
	if enabled_keys.is_empty():
		return []
	var left_index = -1
	for index in range(enabled_keys.size()):
		if _to_real(enabled_keys[index].get("frame", 0.0)) <= position:
			left_index = index
		else:
			break
	if left_index < 0:
		return []
	var left = enabled_keys[left_index]
	var left_values = left.get("values", [])
	if not (left_values is Array):
		return []
	if int(parameter.get("interpolation", 1)) == 0:
		return _gml_clone_value(left_values, 8)
	if left_index + 1 >= enabled_keys.size():
		return _gml_clone_value(left_values, 8)
	var right = enabled_keys[left_index + 1]
	var right_values = right.get("values", [])
	if not (right_values is Array):
		return _gml_clone_value(left_values, 8)
	var left_frame = _to_real(left.get("frame", 0.0))
	var hold_end = left_frame + max(_to_real(left.get("length", 1.0)), 0.0)
	if bool(left.get("stretch", false)):
		hold_end = _to_real(right.get("frame", hold_end))
	if position <= hold_end:
		return _gml_clone_value(left_values, 8)
	var right_frame = _to_real(right.get("frame", hold_end))
	if right_frame <= hold_end:
		return _gml_clone_value(right_values, 8)
	var weight = clamp((position - hold_end) / (right_frame - hold_end), 0.0, 1.0)
	return _gml_sequence_lerp_values(left_values, right_values, weight)


static func _gml_sequence_lerp_values(left, right, weight):
	var result = []
	var value_count = max(left.size(), right.size())
	for index in range(value_count):
		var left_value = left[index] if index < left.size() else 0.0
		var right_value = right[index] if index < right.size() else left_value
		if is_numeric(left_value) and is_numeric(right_value):
			result.append(lerp(_to_real(left_value), _to_real(right_value), weight))
		elif left_value is Array and right_value is Array:
			result.append(_gml_sequence_lerp_values(left_value, right_value, weight))
		else:
			result.append(left_value)
	return result


static func _gml_sequence_vector_values(values, defaults):
	var result = _gml_clone_value(defaults, 8)
	for index in range(min(values.size(), result.size())):
		result[index] = _to_real(values[index])
	return result


static func _gml_sequence_active_key_index(keyframes, position):
	if not (keyframes is Array):
		return -1
	var active_index = -1
	for index in range(keyframes.size()):
		var keyframe = keyframes[index]
		if typeof(keyframe) != TYPE_DICTIONARY or bool(keyframe.get("disabled", false)):
			continue
		var frame = _to_real(keyframe.get("frame", 0.0))
		var end_frame = frame + max(_to_real(keyframe.get("length", 1.0)), 0.0)
		if bool(keyframe.get("stretch", false)):
			end_frame = _gml_sequence_next_key_frame(keyframes, index, end_frame)
		if position >= frame and (
			position < end_frame
			or (end_frame == frame and is_equal_approx(position, frame))
		):
			active_index = index
	return active_index


static func _gml_sequence_next_key_frame(keyframes, index, fallback):
	for next_index in range(index + 1, keyframes.size()):
		var next_key = keyframes[next_index]
		if typeof(next_key) == TYPE_DICTIONARY and not bool(next_key.get("disabled", false)):
			return _to_real(next_key.get("frame", fallback))
	return fallback


static func _gml_sequence_apply_sprite_values(content, values):
	var visual = _gml_sequence_find_sprite_visual(content)
	if visual == null:
		return
	var image_index = max(0, int(floor(_to_real(values["image_index"]))))
	var image_speed = _to_real(values["image_speed"])
	if visual is AnimatedSprite2D:
		var frame_count = 0
		if visual.sprite_frames != null and visual.sprite_frames.has_animation(visual.animation):
			frame_count = visual.sprite_frames.get_frame_count(visual.animation)
		if frame_count > 0:
			visual.frame = image_index % frame_count
		if is_zero_approx(image_speed):
			visual.pause()
		else:
			var base_speed = visual.sprite_frames.get_animation_speed(visual.animation)
			visual.speed_scale = (
				image_speed / base_speed
				if not is_zero_approx(base_speed)
				else image_speed
			)
			visual.play()


static func _gml_sequence_find_sprite_visual(content):
	if content is Sprite2D or content is AnimatedSprite2D:
		return content
	if not (content is Node):
		return null
	var animated = content.find_child("AnimatedSprite2D", true, false)
	if animated is AnimatedSprite2D:
		return animated
	var sprite = content.find_child("Sprite2D", true, false)
	return sprite if sprite is Sprite2D else null


static func _gml_sequence_apply_text_font(label, entry):
	if not (label is Label) or entry == null:
		return
	var path = str(entry.get("godot_path", ""))
	if path == "" or not ResourceLoader.exists(path):
		return
	var font = load(path)
	if font is Font:
		label.add_theme_font_override("font", font)


static func _gml_sequence_apply_text_values(content, keyframe, values):
	if not (content is Label):
		return
	if keyframe != null:
		content.text = str(keyframe.get("text", ""))
		content.autowrap_mode = (
			TextServer.AUTOWRAP_WORD_SMART
			if bool(keyframe.get("wrap", false))
			else TextServer.AUTOWRAP_OFF
		)
		content.horizontal_alignment = int(keyframe.get("alignment_h", 0))
		content.vertical_alignment = int(keyframe.get("alignment_v", 0))
	var frame_size = values["frameSize"]
	if _to_real(frame_size[0]) > 0.0 or _to_real(frame_size[1]) > 0.0:
		content.custom_minimum_size = Vector2(
			max(_to_real(frame_size[0]), 0.0),
			max(_to_real(frame_size[1]), 0.0)
		)
		content.size = content.custom_minimum_size
	content.add_theme_constant_override(
		"line_spacing",
		int(round(_to_real(values["lineSpacing"])))
	)
	content.add_theme_constant_override(
		"paragraph_spacing",
		int(round(_to_real(values["paragraphSpacing"])))
	)
	_gml_sequence_apply_character_spacing(
		content,
		int(round(_to_real(values["characterSpacing"])))
	)
	var effects = values["text_effects"]
	if typeof(effects) != TYPE_DICTIONARY:
		return
	var effects_enabled = (
		keyframe != null
		and bool(keyframe.get("effects_enabled", false))
	)
	if effects_enabled and (
		effects.has("coreColour") or effects.has("coreColor")
	):
		content.add_theme_color_override(
			"font_color",
			_gml_sequence_argb_colour(
				effects.get("coreColour", effects.get("coreColor"))
			)
		)
	var outline_enabled = (
		effects_enabled
		and bool(keyframe.get("outline_enabled", false))
	)
	if outline_enabled and (
		effects.has("outlineColour") or effects.has("outlineColor")
	):
		content.add_theme_color_override(
			"font_outline_color",
			_gml_sequence_argb_colour(
				effects.get("outlineColour", effects.get("outlineColor"))
			)
		)
	if outline_enabled and effects.has("outlineDist"):
		content.add_theme_constant_override(
			"outline_size",
			max(0, int(round(_to_real(effects["outlineDist"]))))
		)
	var shadow_enabled = (
		effects_enabled
		and bool(keyframe.get("shadow_enabled", false))
	)
	if shadow_enabled and (
		effects.has("shadowColour") or effects.has("shadowColor")
	):
		content.add_theme_color_override(
			"font_shadow_color",
			_gml_sequence_argb_colour(
				effects.get("shadowColour", effects.get("shadowColor"))
			)
		)
	for pair in [
		["shadowOffsetX", "shadow_offset_x"],
		["shadowOffsetY", "shadow_offset_y"],
		["shadowSoftness", "shadow_outline_size"],
	]:
		if shadow_enabled and effects.has(pair[0]):
			content.add_theme_constant_override(
				pair[1],
				int(round(_to_real(effects[pair[0]])))
			)


static func _gml_sequence_apply_character_spacing(label, spacing):
	if not (label is Label):
		return
	var variation = (
		label.get_meta("gamemaker_sequence_font_variation")
		if label.has_meta("gamemaker_sequence_font_variation")
		else null
	)
	if not (variation is FontVariation):
		variation = FontVariation.new()
		var base_font = label.get_theme_font("font")
		if base_font is Font:
			variation.base_font = base_font
		label.add_theme_font_override("font", variation)
		label.set_meta("gamemaker_sequence_font_variation", variation)
	variation.spacing_glyph = spacing


static func _gml_sequence_argb_colour(value):
	if value is Array and value.size() >= 4:
		return Color(
			clamp(_to_real(value[1]), 0.0, 1.0),
			clamp(_to_real(value[2]), 0.0, 1.0),
			clamp(_to_real(value[3]), 0.0, 1.0),
			clamp(_to_real(value[0]), 0.0, 1.0)
		)
	return Color.WHITE


static func _gml_sequence_apply_audio_values(instance, state, content, keyframe, values, position, track_active):
	var active_key = int(state.get("active_key", -1))
	if int(state.get("audio_key", -1)) != active_key:
		for player_content in state["contents"].values():
			if player_content is AudioStreamPlayer2D:
				player_content.stop()
		state["audio_key"] = active_key
	if content is AudioStreamPlayer2D:
		content.volume_linear = max(
			_to_real(instance.get("sequence", {}).get("volume", 1.0))
			* _to_real(values["gain"]),
			0.0
		)
		content.pitch_scale = max(_to_real(values["pitch"]), 0.0001)
		content.max_distance = max(_to_real(values["falloff"][1]), 0.0)
		content.attenuation = max(_to_real(values["falloff"][2]), 0.0)
		if track_active and not content.playing and content.stream != null:
			var key_frame = _to_real(keyframe.get("frame", 0.0)) if keyframe != null else position
			var sequence_speed = max(
				_to_real(instance.get("sequence", {}).get("playbackSpeed", 1.0)),
				0.0001
			)
			content.play(max(position - key_frame, 0.0) / sequence_speed)
			if (
				keyframe != null
				and int(keyframe.get("playback_mode", 1)) == 0
			):
				var replay = Callable(content, "play")
				if not content.finished.is_connected(replay):
					content.finished.connect(replay)
		elif not track_active and content.playing:
			content.stop()
	_gml_sequence_apply_audio_effects(state, position)


static func _gml_sequence_prepare_audio_bus(state):
	var descriptor = state.get("descriptor", {})
	var parameters = descriptor.get("parameters", [])
	if not (parameters is Array):
		return
	var effect_descriptors = []
	for parameter in parameters:
		if (
			typeof(parameter) == TYPE_DICTIONARY
			and str(parameter.get("kind", "")) == "audio_effect"
		):
			effect_descriptors.append(parameter)
	if effect_descriptors.is_empty():
		return
	var track_node = state.get("node", null)
	if not (track_node is Node):
		return
	var bus_name = (
		"GMSequence_"
		+ str(track_node.get_instance_id())
		+ "_"
		+ str(descriptor.get("order", 0))
	)
	AudioServer.add_bus()
	var bus_index = AudioServer.bus_count - 1
	AudioServer.set_bus_name(bus_index, bus_name)
	state["audio_bus"] = bus_name
	for effect_descriptor in effect_descriptors:
		var effect = _gml_sequence_create_audio_effect(
			str(effect_descriptor.get("effect_type", ""))
		)
		if effect == null:
			continue
		AudioServer.add_bus_effect(bus_index, effect)
		var slot = AudioServer.get_bus_effect_count(bus_index) - 1
		var effect_state = {
			"descriptor": effect_descriptor,
			"effect": effect,
			"slot": slot,
		}
		state["audio_effects"].append(effect_state)
		_gml_sequence_apply_audio_effect_state(
			state,
			effect_state,
			0.0
		)


static func _gml_sequence_create_audio_effect(effect_type):
	if effect_type == "gain":
		return AudioEffectAmplify.new()
	if effect_type == "reverb1":
		return AudioEffectReverb.new()
	if effect_type == "delay":
		return AudioEffectDelay.new()
	if effect_type == "compressor":
		return AudioEffectCompressor.new()
	if effect_type == "lpf2":
		return AudioEffectLowPassFilter.new()
	if effect_type == "hpf2":
		return AudioEffectHighPassFilter.new()
	if effect_type == "hishelf":
		return AudioEffectHighShelfFilter.new()
	if effect_type == "loshelf":
		return AudioEffectLowShelfFilter.new()
	return null


static func _gml_sequence_apply_audio_effects(state, position):
	for effect_state in state.get("audio_effects", []):
		_gml_sequence_apply_audio_effect_state(
			state,
			effect_state,
			position
		)


static func _gml_sequence_apply_audio_effect_state(state, effect_state, position):
	var descriptor = effect_state.get("descriptor", {})
	var effect = effect_state.get("effect", null)
	if typeof(descriptor) != TYPE_DICTIONARY or not (effect is AudioEffect):
		return
	var properties = {}
	var defaults = descriptor.get("defaults", {})
	if typeof(defaults) == TYPE_DICTIONARY:
		for key in defaults.keys():
			properties[str(key)] = defaults[key]
	var parameters = descriptor.get("parameters", [])
	if parameters is Array:
		for parameter in parameters:
			if typeof(parameter) != TYPE_DICTIONARY:
				continue
			var evaluated = _gml_sequence_parameter_value(parameter, position)
			if evaluated is Array and not evaluated.is_empty():
				properties[str(parameter.get("name", ""))] = evaluated[0]
	_gml_sequence_set_audio_effect_properties(
		effect,
		str(descriptor.get("effect_type", "")),
		properties
	)
	var bus_name = str(state.get("audio_bus", ""))
	var bus_index = AudioServer.get_bus_index(bus_name)
	if bus_index >= 0:
		AudioServer.set_bus_effect_enabled(
			bus_index,
			int(effect_state.get("slot", 0)),
			bool(descriptor.get("enabled", true))
			and not bool(properties.get("bypass", false))
		)


static func _gml_sequence_set_audio_effect_properties(effect, effect_type, properties):
	if effect_type == "gain" and effect is AudioEffectAmplify:
		if properties.has("gain"):
			effect.volume_linear = max(_to_real(properties["gain"]), 0.0)
	elif effect_type == "reverb1" and effect is AudioEffectReverb:
		if properties.has("size"):
			effect.room_size = clamp(_to_real(properties["size"]), 0.0, 1.0)
		if properties.has("damp"):
			effect.damping = clamp(_to_real(properties["damp"]), 0.0, 1.0)
		if properties.has("mix"):
			var mix = clamp(_to_real(properties["mix"]), 0.0, 1.0)
			effect.wet = mix
			effect.dry = 1.0 - mix
	elif effect_type == "delay" and effect is AudioEffectDelay:
		var mix = clamp(_to_real(properties.get("mix", 0.5)), 0.0, 1.0)
		effect.dry = 1.0 - mix
		effect.tap1_active = mix > 0.0
		effect.tap2_active = false
		effect.tap1_level_db = linear_to_db(max(mix, 0.0001))
		if properties.has("time"):
			var delay_ms = clamp(_to_real(properties["time"]) * 1000.0, 0.0, 1500.0)
			effect.tap1_delay_ms = delay_ms
			effect.feedback_delay_ms = delay_ms
		if properties.has("feedback"):
			var feedback = clamp(_to_real(properties["feedback"]), 0.0, 1.0)
			effect.feedback_active = feedback > 0.0
			effect.feedback_level_db = linear_to_db(max(feedback, 0.001))
	elif effect_type == "compressor" and effect is AudioEffectCompressor:
		if properties.has("threshold"):
			effect.threshold = linear_to_db(
				max(_to_real(properties["threshold"]), 0.001)
			)
		if properties.has("ratio"):
			effect.ratio = max(_to_real(properties["ratio"]), 1.0)
		if properties.has("attack"):
			effect.attack_us = clamp(
				_to_real(properties["attack"]) * 1000000.0,
				20.0,
				2000.0
			)
		if properties.has("release"):
			effect.release_ms = clamp(
				_to_real(properties["release"]) * 1000.0,
				20.0,
				2000.0
			)
		if properties.has("outgain"):
			effect.gain = linear_to_db(
				max(_to_real(properties["outgain"]), 0.0001)
			)
	elif effect is AudioEffectFilter:
		if properties.has("cutoff"):
			effect.cutoff_hz = clamp(
				_to_real(properties["cutoff"]),
				1.0,
				20500.0
			)
		elif properties.has("freq"):
			effect.cutoff_hz = clamp(
				_to_real(properties["freq"]),
				1.0,
				20500.0
			)
		if (
			effect_type in ["hishelf", "loshelf"]
			and properties.has("gain")
		):
			effect.gain = clamp(_to_real(properties["gain"]), 0.0, 4.0)


static func _gml_sequence_apply_nested_values(state, keyframe, position, track_active):
	if keyframe == null:
		return
	var key_order = int(keyframe.get("order", 0))
	if not state["nested"].has(key_order):
		return
	var nested = state["nested"][key_order]
	if typeof(nested) != TYPE_DICTIONARY:
		return
	if not track_active:
		return
	var local_position = max(
		position - _to_real(keyframe.get("frame", 0.0)),
		0.0
	)
	var previous = _to_real(nested.get("headPosition", 0.0))
	_gml_sequence_advance_instance(nested, local_position - previous)
	state["evaluation"]["sequence"] = nested.get("sequence", {})


static func _gml_sequence_advance_instance(instance, delta):
	if typeof(instance) != TYPE_DICTIONARY:
		return
	var sequence_object = instance.get("sequence", {})
	if typeof(sequence_object) != TYPE_DICTIONARY:
		return
	var length = max(_to_real(sequence_object.get("length", 0.0)), 0.0)
	var movement = _to_real(delta)
	if is_zero_approx(movement) or length <= 0.0:
		_gml_sequence_evaluate_instance(instance)
		return
	var loopmode = int(sequence_object.get("loopmode", 0))
	var position = clamp(
		_to_real(instance.get("headPosition", 0.0)),
		0.0,
		length
	)
	if loopmode == 0:
		var target = clamp(position + movement, 0.0, length)
		_gml_sequence_dispatch_between(instance, position, target, movement)
		instance["headPosition"] = target
		instance["finished"] = (
			target >= length if movement > 0.0 else target <= 0.0
		)
		_gml_sequence_evaluate_instance(instance)
		return
	instance["finished"] = false
	var direction = 1 if movement > 0.0 else -1
	var remaining = abs(movement)
	var guard = 0
	while remaining > 0.000001 and guard < 1024:
		guard += 1
		var boundary = length if direction > 0 else 0.0
		var distance = abs(boundary - position)
		if remaining < distance or is_zero_approx(distance) and remaining <= 0.000001:
			var target = position + float(direction) * remaining
			_gml_sequence_dispatch_between(
				instance,
				position,
				target,
				float(direction)
			)
			position = target
			remaining = 0.0
			break
		if distance > 0.0:
			_gml_sequence_dispatch_between(
				instance,
				position,
				boundary,
				float(direction)
			)
			remaining -= distance
		position = boundary
		if loopmode == 1:
			if direction > 0:
				position = 0.0
				_gml_sequence_dispatch_between(
					instance,
					-0.000001,
					0.0,
					1.0
				)
			else:
				position = length
			if is_zero_approx(remaining):
				break
		else:
			direction *= -1
			instance["headDirection"] = direction
			if is_zero_approx(remaining):
				break
	instance["headPosition"] = clamp(position, 0.0, length)
	_gml_sequence_evaluate_instance(instance)


static func _gml_sequence_emit_broadcast(instance, action):
	var payload = {
		"event_type": "sequence event",
		"message": str(action.get("message", "")),
		"element_id": action.get(
			"element_id",
			instance.get("elementID", null)
			if typeof(instance) == TYPE_DICTIONARY
			else null
		),
	}
	var previous_event_data = (
		_gml_builtin_globals["event_data"]
		if _gml_builtin_globals.has("event_data")
		else {}
	)
	_gml_builtin_globals["event_data"] = payload
	for target in _gml_event_scheduler_live_instances():
		if (
			_gml_event_scheduler_instance_valid(target)
			and target.has_method("_on_broadcast_message")
		):
			target.call("_on_broadcast_message")
	_gml_builtin_globals["event_data"] = previous_event_data


static func _gml_sequence_cleanup_instance(instance):
	if typeof(instance) != TYPE_DICTIONARY:
		return
	var states = instance.get("trackStates", [])
	if states is Array:
		for state in states:
			_gml_sequence_cleanup_track(state)
	instance["trackStates"] = []
	instance["activeTracks"] = []
	instance["node"] = null
	instance["owner"] = null


static func gml_sequence_runtime_cleanup_all():
	var sequence_indices = _gml_sequence_elements_by_index.keys()
	for sequence_index in sequence_indices:
		if not _gml_sequence_elements_by_index.has(sequence_index):
			continue
		_gml_sequence_release_element_record(
			sequence_index,
			_gml_sequence_elements_by_index[sequence_index]
		)
	_gml_sequence_objects_by_id.clear()
	return null


static func _gml_sequence_release_element_record(sequence_index, instance):
	_gml_sequence_cleanup_instance(instance)
	var element = (
		instance.get("elementID", null)
		if typeof(instance) == TYPE_DICTIONARY
		else null
	)
	_gml_sequence_elements_by_index.erase(sequence_index)
	if element is GMLHandle:
		_gml_layer_element_unregister_handle(element)


static func _gml_sequence_cleanup_track(state):
	if typeof(state) != TYPE_DICTIONARY:
		return
	for child in state.get("children", []):
		_gml_sequence_cleanup_track(child)
	for nested in state.get("nested", {}).values():
		_gml_sequence_cleanup_instance(nested)
	for content in state.get("contents", {}).values():
		if content is Object and not is_instance_valid(content):
			continue
		if content is AudioStreamPlayer2D:
			content.stop()
		if (
			content is Object
			and content.has_meta("gamemaker_sequence_instance_handle")
		):
			gml_variable_instance_set(content, "in_sequence", false)
			gml_variable_instance_set(content, "drawn_by_sequence", false)
			gml_variable_instance_set(content, "sequence_instance", null)
			gml_instance_unregister(
				content.get_meta("gamemaker_sequence_instance_handle")
			)
	var bus_name = str(state.get("audio_bus", ""))
	if bus_name != "":
		var bus_index = AudioServer.get_bus_index(bus_name)
		if bus_index >= 0:
			AudioServer.remove_bus(bus_index)
	state["audio_bus"] = ""
	state["audio_effects"] = []
	state["instance"] = null
	state["descriptor"] = {}
	state["node"] = null
	state["evaluation"] = {}
	state["contents"] = {}
	state["nested"] = {}
	state["children"] = []
