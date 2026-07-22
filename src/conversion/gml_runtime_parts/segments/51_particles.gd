const GML_PARTICLE_SYSTEM_HANDLE_KIND = "particle_system"
const GML_PARTICLE_TYPE_HANDLE_KIND = "particle_type"
const GML_PARTICLE_EMITTER_HANDLE_KIND = "particle_emitter"
const GML_PARTICLE_DESCRIPTOR_FORMAT_VERSION = 1


static func gml_part_system_exists(system):
	return _gml_particle_system_resolve(system) != null


static func gml_part_system_create(partsys = null):
	return _gml_particle_system_create(0, false, partsys)


static func gml_part_system_create_layer(layer, persistent, partsys = null):
	return _gml_particle_system_create(layer, persistent, partsys)


static func gml_part_system_get_layer(system):
	var record = _gml_particle_system_resolve(system)
	if record == null:
		return 0
	return record.get("layer", 0)


static func gml_part_system_layer(system, layer):
	var record = _gml_particle_system_resolve(system)
	if record == null:
		return null
	record["layer"] = layer
	var node = record.get("node", null)
	if node is Node:
		var parent = _gml_particle_parent_for_layer(layer)
		if parent != null and node.get_parent() != parent:
			if node.get_parent() is Node:
				node.get_parent().remove_child(node)
			parent.add_child(node)
	return null


static func gml_part_system_depth(system, depth):
	var record = _gml_particle_system_resolve(system)
	if record == null:
		return null
	var depth_value = _to_real(depth)
	record["depth"] = depth_value
	var node = record.get("node", null)
	if node is Node2D:
		node.z_index = int(round(-depth_value))
	return null


static func gml_part_system_position(system, x, y):
	var record = _gml_particle_system_resolve(system)
	if record == null:
		return null
	var position = Vector2(_to_real(x), _to_real(y))
	record["position"] = position
	var node = record.get("node", null)
	if node is Node2D:
		node.position = position
	return null


static func _gml_particle_system_create(layer, persistent, partsys = null):
	var record = {
		"asset": partsys,
		"asset_name": "",
		"layer": layer,
		"persistent": gml_bool(persistent),
		"depth": 0.0,
		"position": Vector2.ZERO,
		"xorigin": 0.0,
		"yorigin": 0.0,
		"draw_order": "old_to_new",
		"node": null,
		"emitters": {},
		"owned_types": [],
		"particle_count": 0,
		"valid": true
	}
	var handle = gml_handle_register(GML_PARTICLE_SYSTEM_HANDLE_KIND, record)
	var node = Node2D.new()
	node.name = "_gm_particle_system_" + str(handle.index)
	record["node"] = node
	_gml_particle_attach_node(node, layer)
	if (
		partsys != null
		and not _gml_particle_apply_asset(handle, record, partsys)
	):
		record["valid"] = false
		_gml_particle_free_node(node)
		gml_handle_invalidate(handle)
	return handle


static func gml_part_system_destroy(system):
	var handle = gml_handle_from_value(GML_PARTICLE_SYSTEM_HANDLE_KIND, system)
	var record = _gml_particle_system_resolve(handle)
	if record == null:
		return null
	var emitter_handles = []
	for emitter_handle in record["emitters"].values():
		emitter_handles.append(emitter_handle)
	for emitter_handle in emitter_handles:
		_gml_particle_emitter_destroy_record(record, emitter_handle)
	var owned_types = []
	for particle_type in record.get("owned_types", []):
		owned_types.append(particle_type)
	for particle_type in owned_types:
		gml_part_type_destroy(particle_type)
	record["owned_types"] = []
	record.set("valid", false)
	_gml_particle_free_node(record["node"])
	gml_handle_invalidate(handle)
	return null


static func gml_part_system_clear(system):
	var record = _gml_particle_system_resolve(system)
	if record != null:
		record["particle_count"] = 0
		for emitter_handle in record["emitters"].values():
			var emitter_record = _gml_particle_emitter_resolve_any(emitter_handle)
			if emitter_record != null:
				emitter_record["emitted_count"] = 0
				_gml_particle_reset_emitter_node(emitter_record)
	return null


static func gml_part_particles_clear(system):
	return gml_part_system_clear(system)


static func gml_part_particles_count(system):
	var record = _gml_particle_system_resolve(system)
	if record == null:
		return 0
	return int(record["particle_count"])


static func gml_part_particles_create(system, x, y, particle_type, number):
	var system_record = _gml_particle_system_resolve(system)
	var type_record = _gml_particle_type_resolve(particle_type)
	if system_record == null or type_record == null:
		return null
	var amount = _gml_particle_amount(number)
	system_record["particle_count"] = int(system_record["particle_count"]) + amount
	_gml_particle_emit_transient(system_record, x, y, type_record, amount)
	return null


static func gml_part_type_exists(particle_type):
	return _gml_particle_type_resolve(particle_type) != null


static func gml_part_type_create():
	var record = {
		"shape": "pixel",
		"size_min": 1.0,
		"size_max": 1.0,
		"size_incr": 0.0,
		"size_wiggle": 0.0,
		"scale_x": 1.0,
		"scale_y": 1.0,
		"life_min": 1.0,
		"life_max": 1.0,
		"speed_min": 0.0,
		"speed_max": 0.0,
		"speed_incr": 0.0,
		"speed_wiggle": 0.0,
		"direction_min": 0.0,
		"direction_max": 0.0,
		"direction_incr": 0.0,
		"direction_wiggle": 0.0,
		"gravity_amount": 0.0,
		"gravity_direction": 270.0,
		"orientation_min": 0.0,
		"orientation_max": 0.0,
		"orientation_incr": 0.0,
		"orientation_wiggle": 0.0,
		"orientation_relative": false,
		"colours": [0xffffff],
		"alphas": [1.0],
		"blend_additive": false,
		"sprite": null,
		"sprite_frame": 0.0,
		"sprite_animate": false,
		"sprite_stretch": false,
		"sprite_random": false,
		"spawn_on_death": {"count": 0.0, "id": null, "preset": null},
		"spawn_on_update": {"count": 0.0, "id": null, "preset": null},
		"valid": true
	}
	return gml_handle_register(GML_PARTICLE_TYPE_HANDLE_KIND, record)


static func gml_part_type_destroy(particle_type):
	var handle = gml_handle_from_value(GML_PARTICLE_TYPE_HANDLE_KIND, particle_type)
	var record = _gml_particle_type_resolve(handle)
	if record != null:
		record.set("valid", false)
		gml_handle_invalidate(handle)
	return null


static func gml_part_type_shape(particle_type, shape):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["shape"] = shape
	return null


static func gml_part_type_size(particle_type, size_min, size_max, size_incr, size_wiggle):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["size_min"] = _to_real(size_min)
		record["size_max"] = _to_real(size_max)
		record["size_incr"] = _to_real(size_incr)
		record["size_wiggle"] = _to_real(size_wiggle)
	return null


static func gml_part_type_scale(particle_type, xscale, yscale):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["scale_x"] = _to_real(xscale)
		record["scale_y"] = _to_real(yscale)
	return null


static func gml_part_type_life(particle_type, life_min, life_max):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["life_min"] = max(_to_real(life_min), 1.0)
		record["life_max"] = max(_to_real(life_max), 1.0)
	return null


static func gml_part_type_speed(particle_type, speed_min, speed_max, speed_incr, speed_wiggle):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["speed_min"] = _to_real(speed_min)
		record["speed_max"] = _to_real(speed_max)
		record["speed_incr"] = _to_real(speed_incr)
		record["speed_wiggle"] = _to_real(speed_wiggle)
	return null


static func gml_part_type_direction(particle_type, dir_min, dir_max, dir_incr, dir_wiggle):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["direction_min"] = _to_real(dir_min)
		record["direction_max"] = _to_real(dir_max)
		record["direction_incr"] = _to_real(dir_incr)
		record["direction_wiggle"] = _to_real(dir_wiggle)
	return null


static func gml_part_type_gravity(particle_type, gravity_amount, gravity_direction):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["gravity_amount"] = _to_real(gravity_amount)
		record["gravity_direction"] = _to_real(gravity_direction)
	return null


static func gml_part_type_orientation(particle_type, orient_min, orient_max, orient_incr, orient_wiggle, orient_relative):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["orientation_min"] = _to_real(orient_min)
		record["orientation_max"] = _to_real(orient_max)
		record["orientation_incr"] = _to_real(orient_incr)
		record["orientation_wiggle"] = _to_real(orient_wiggle)
		record["orientation_relative"] = gml_bool(orient_relative)
	return null


static func gml_part_type_colour1(particle_type, colour1):
	return _gml_particle_type_colours(particle_type, [colour1])


static func gml_part_type_colour2(particle_type, colour1, colour2):
	return _gml_particle_type_colours(particle_type, [colour1, colour2])


static func gml_part_type_colour3(particle_type, colour1, colour2, colour3):
	return _gml_particle_type_colours(particle_type, [colour1, colour2, colour3])


static func gml_part_type_alpha1(particle_type, alpha1):
	return _gml_particle_type_alphas(particle_type, [alpha1])


static func gml_part_type_alpha2(particle_type, alpha1, alpha2):
	return _gml_particle_type_alphas(particle_type, [alpha1, alpha2])


static func gml_part_type_alpha3(particle_type, alpha1, alpha2, alpha3):
	return _gml_particle_type_alphas(particle_type, [alpha1, alpha2, alpha3])


static func gml_part_type_blend(particle_type, additive):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["blend_additive"] = gml_bool(additive)
	return null


static func gml_part_type_sprite(particle_type, sprite, animate, stretch, random):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		record["sprite"] = sprite
		record["sprite_animate"] = gml_bool(animate)
		record["sprite_stretch"] = gml_bool(stretch)
		record["sprite_random"] = gml_bool(random)
	return null


static func gml_part_emitter_exists(system, emitter):
	return _gml_particle_emitter_resolve(system, emitter) != null


static func gml_part_emitter_create(system):
	var system_handle = gml_handle_from_value(GML_PARTICLE_SYSTEM_HANDLE_KIND, system)
	var system_record = _gml_particle_system_resolve(system_handle)
	if system_record == null:
		return gml_handle_invalid(GML_PARTICLE_EMITTER_HANDLE_KIND)
	var node = GPUParticles2D.new()
	node.name = "_gm_particle_emitter_pending"
	node.amount = 1
	node.emitting = false
	node.process_material = ParticleProcessMaterial.new()
	node.local_coords = false
	if system_record["node"] is Node:
		system_record["node"].add_child(node)
	var record = {
		"system_index": system_handle.index,
		"node": node,
		"name": "",
		"enabled": true,
		"relative": false,
		"origin": Vector2(
			_to_real(system_record.get("xorigin", 0.0)),
			_to_real(system_record.get("yorigin", 0.0))
		),
		"draw_order": system_record.get("draw_order", "old_to_new"),
		"region": {
			"xmin": 0.0,
			"xmax": 0.0,
			"ymin": 0.0,
			"ymax": 0.0,
			"shape": "rectangle",
			"distribution": "linear"
		},
		"stream_type": null,
		"stream_number": 0,
		"authored_mode": "",
		"authored_timing": {},
		"emitted_count": 0,
		"valid": true
	}
	var handle = gml_handle_register(GML_PARTICLE_EMITTER_HANDLE_KIND, record)
	node.name = "_gm_particle_emitter_" + str(handle.index)
	_gml_particle_apply_draw_order(node, record["draw_order"])
	system_record["emitters"][handle.index] = handle
	return handle


static func gml_part_emitter_region(system, emitter, xmin, xmax, ymin, ymax, shape, distribution):
	var record = _gml_particle_emitter_resolve(system, emitter)
	if record != null:
		record["region"] = {
			"xmin": _to_real(xmin),
			"xmax": _to_real(xmax),
			"ymin": _to_real(ymin),
			"ymax": _to_real(ymax),
			"shape": shape,
			"distribution": distribution
		}
		_gml_particle_apply_emitter_region(record)
	return null


static func gml_part_emitter_relative(system, emitter, enable):
	var record = _gml_particle_emitter_resolve(system, emitter)
	if record != null:
		record["relative"] = gml_bool(enable)
	return null


static func gml_part_emitter_destroy(system, emitter):
	var system_record = _gml_particle_system_resolve(system)
	if system_record != null:
		_gml_particle_emitter_destroy_record(system_record, emitter)
	return null


static func gml_part_emitter_destroy_all(system):
	var system_record = _gml_particle_system_resolve(system)
	if system_record == null:
		return null
	var emitter_handles = []
	for emitter_handle in system_record["emitters"].values():
		emitter_handles.append(emitter_handle)
	for emitter_handle in emitter_handles:
		_gml_particle_emitter_destroy_record(system_record, emitter_handle)
	return null


static func gml_part_emitter_clear(system, emitter):
	var record = _gml_particle_emitter_resolve(system, emitter)
	if record != null:
		record["stream_type"] = null
		record["stream_number"] = 0
		record["emitted_count"] = 0
		record["enabled"] = true
		_gml_particle_reset_emitter_node(record)
	return null


static func gml_part_emitter_enable(system, emitter, enable):
	var record = _gml_particle_emitter_resolve(system, emitter)
	if record != null:
		record["enabled"] = gml_bool(enable)
		_gml_particle_apply_stream(record)
	return null


static func gml_part_emitter_burst(system, emitter, particle_type, number):
	var system_record = _gml_particle_system_resolve(system)
	var emitter_record = _gml_particle_emitter_resolve(system, emitter)
	var type_record = _gml_particle_type_resolve(particle_type)
	if system_record == null or emitter_record == null or type_record == null or not bool(emitter_record["enabled"]):
		return null
	var amount = _gml_particle_amount(number)
	if bool(emitter_record.get("relative", false)):
		amount = _gml_particle_relative_amount(emitter_record, amount)
	system_record["particle_count"] = int(system_record["particle_count"]) + amount
	emitter_record["emitted_count"] = int(emitter_record["emitted_count"]) + amount
	_gml_particle_apply_type_to_node(emitter_record["node"], type_record)
	_gml_particle_burst_emitter_node(emitter_record, amount)
	return null


static func gml_part_emitter_stream(system, emitter, particle_type, number):
	var emitter_record = _gml_particle_emitter_resolve(system, emitter)
	if emitter_record == null or _gml_particle_type_resolve(particle_type) == null:
		return null
	var type_record = _gml_particle_type_resolve(particle_type)
	emitter_record["stream_type"] = particle_type
	emitter_record["stream_number"] = _to_real(number)
	_gml_particle_apply_type_to_node(emitter_record["node"], type_record)
	_gml_particle_apply_stream(emitter_record)
	return null


static func _gml_particle_apply_asset(system_handle, system_record, partsys):
	if partsys == null:
		return true
	var descriptor = _gml_particle_asset_descriptor(partsys)
	if descriptor == null:
		return false
	system_record["asset_name"] = str(descriptor.get("name", ""))
	system_record["xorigin"] = _to_real(descriptor.get("xorigin", 0.0))
	system_record["yorigin"] = _to_real(descriptor.get("yorigin", 0.0))
	system_record["draw_order"] = str(descriptor.get("draw_order", "old_to_new"))
	var type_handles = []
	var raw_types = descriptor.get("types", [])
	if typeof(raw_types) == TYPE_ARRAY:
		for raw_type in raw_types:
			if typeof(raw_type) != TYPE_DICTIONARY:
				type_handles.append(null)
				continue
			var type_handle = _gml_particle_type_from_descriptor(raw_type)
			type_handles.append(type_handle)
			system_record["owned_types"].append(type_handle)
	var raw_emitters = descriptor.get("emitters", [])
	if typeof(raw_emitters) != TYPE_ARRAY:
		return true
	for raw_emitter in raw_emitters:
		if typeof(raw_emitter) != TYPE_DICTIONARY:
			continue
		var type_index = int(_to_real(raw_emitter.get("type_index", -1)))
		if type_index < 0 or type_index >= type_handles.size():
			continue
		var type_handle = type_handles[type_index]
		if _gml_particle_type_resolve(type_handle) == null:
			continue
		var emitter_handle = gml_part_emitter_create(system_handle)
		var emitter_record = _gml_particle_emitter_resolve(system_handle, emitter_handle)
		if emitter_record == null:
			continue
		_gml_particle_emitter_apply_descriptor(emitter_record, raw_emitter)
		var authored_mode = str(raw_emitter.get("mode", "stream"))
		var authored_number = _to_real(raw_emitter.get("number", 0.0))
		emitter_record["authored_mode"] = authored_mode
		if authored_mode == "burst":
			gml_part_emitter_burst(
				system_handle,
				emitter_handle,
				type_handle,
				authored_number
			)
		else:
			gml_part_emitter_stream(
				system_handle,
				emitter_handle,
				type_handle,
				authored_number
			)
	return true


static func _gml_particle_asset_descriptor(partsys):
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(partsys)
	if entry == null or str(entry.get("type", "")) != "particle_system":
		return null
	var resource_path = str(entry.get("godot_path", ""))
	if resource_path != "" and ResourceLoader.exists(resource_path):
		var resource = load(resource_path)
		if resource is Resource and resource.has_meta("gamemaker_particle_descriptor"):
			var resource_descriptor = resource.get_meta("gamemaker_particle_descriptor")
			if _gml_particle_descriptor_is_supported(resource_descriptor):
				return resource_descriptor
	var metadata = entry.get("metadata", {})
	if _gml_particle_descriptor_is_supported(metadata):
		return metadata
	return null


static func _gml_particle_descriptor_is_supported(descriptor):
	return (
		typeof(descriptor) == TYPE_DICTIONARY
		and int(_to_real(descriptor.get("descriptor_format_version", 0)))
			== GML_PARTICLE_DESCRIPTOR_FORMAT_VERSION
	)


static func _gml_particle_type_from_descriptor(descriptor):
	var type_handle = gml_part_type_create()
	var record = _gml_particle_type_resolve(type_handle)
	if record == null:
		return type_handle
	record["name"] = str(descriptor.get("name", ""))
	record["shape"] = descriptor.get("shape", "pixel")
	record["sprite"] = descriptor.get("sprite", null)
	record["sprite_frame"] = _to_real(descriptor.get("sprite_frame", 0.0))
	record["sprite_animate"] = gml_bool(descriptor.get("sprite_animate", false))
	record["sprite_stretch"] = gml_bool(descriptor.get("sprite_stretch", false))
	record["sprite_random"] = gml_bool(descriptor.get("sprite_random", false))
	record["size_min"] = _to_real(descriptor.get("size_min", 1.0))
	record["size_max"] = _to_real(descriptor.get("size_max", 1.0))
	record["size_incr"] = _to_real(descriptor.get("size_increase", 0.0))
	record["size_wiggle"] = _to_real(descriptor.get("size_wiggle", 0.0))
	record["scale_x"] = _to_real(descriptor.get("scale_x", 1.0))
	record["scale_y"] = _to_real(descriptor.get("scale_y", 1.0))
	record["life_min"] = max(_to_real(descriptor.get("life_min", 1.0)), 1.0)
	record["life_max"] = max(_to_real(descriptor.get("life_max", 1.0)), 1.0)
	record["speed_min"] = _to_real(descriptor.get("speed_min", 0.0))
	record["speed_max"] = _to_real(descriptor.get("speed_max", 0.0))
	record["speed_incr"] = _to_real(descriptor.get("speed_increase", 0.0))
	record["speed_wiggle"] = _to_real(descriptor.get("speed_wiggle", 0.0))
	record["direction_min"] = _to_real(descriptor.get("direction_min", 0.0))
	record["direction_max"] = _to_real(descriptor.get("direction_max", 0.0))
	record["direction_incr"] = _to_real(descriptor.get("direction_increase", 0.0))
	record["direction_wiggle"] = _to_real(descriptor.get("direction_wiggle", 0.0))
	record["gravity_amount"] = _to_real(descriptor.get("gravity_amount", 0.0))
	record["gravity_direction"] = _to_real(descriptor.get("gravity_direction", 270.0))
	record["orientation_min"] = _to_real(descriptor.get("orientation_min", 0.0))
	record["orientation_max"] = _to_real(descriptor.get("orientation_max", 0.0))
	record["orientation_incr"] = _to_real(descriptor.get("orientation_increase", 0.0))
	record["orientation_wiggle"] = _to_real(descriptor.get("orientation_wiggle", 0.0))
	record["orientation_relative"] = gml_bool(
		descriptor.get("orientation_relative", false)
	)
	var colours = descriptor.get("colours", [0xffffff])
	record["colours"] = colours if typeof(colours) == TYPE_ARRAY else [0xffffff]
	var alphas = descriptor.get("alphas", [1.0])
	record["alphas"] = alphas if typeof(alphas) == TYPE_ARRAY else [1.0]
	record["blend_additive"] = gml_bool(descriptor.get("blend_additive", false))
	var spawn_on_death = descriptor.get(
		"spawn_on_death",
		{"count": 0.0, "id": null, "preset": null}
	)
	record["spawn_on_death"] = (
		spawn_on_death
		if typeof(spawn_on_death) == TYPE_DICTIONARY
		else {"count": 0.0, "id": null, "preset": null}
	)
	var spawn_on_update = descriptor.get(
		"spawn_on_update",
		{"count": 0.0, "id": null, "preset": null}
	)
	record["spawn_on_update"] = (
		spawn_on_update
		if typeof(spawn_on_update) == TYPE_DICTIONARY
		else {"count": 0.0, "id": null, "preset": null}
	)
	return type_handle


static func _gml_particle_emitter_apply_descriptor(record, descriptor):
	record["name"] = str(descriptor.get("name", ""))
	record["enabled"] = gml_bool(descriptor.get("enabled", true))
	record["relative"] = gml_bool(descriptor.get("relative", false))
	var region = descriptor.get("region", {})
	if typeof(region) == TYPE_DICTIONARY:
		record["region"] = region
	record["authored_timing"] = {
		"delay_min": _to_real(descriptor.get("delay_min", 0.0)),
		"delay_max": _to_real(descriptor.get("delay_max", 0.0)),
		"delay_unit": int(_to_real(descriptor.get("delay_unit", 0))),
		"interval_min": _to_real(descriptor.get("interval_min", 0.0)),
		"interval_max": _to_real(descriptor.get("interval_max", 0.0)),
		"interval_unit": int(_to_real(descriptor.get("interval_unit", 0)))
	}
	var node = record.get("node", null)
	if node is Node:
		node.name = _gml_particle_node_name(record["name"], node.name)
	_gml_particle_apply_emitter_region(record)


static func _gml_particle_node_name(value, fallback):
	var normalized = str(value).strip_edges()
	if normalized == "":
		return str(fallback)
	var output = ""
	for character in normalized:
		if (
			(character >= "a" and character <= "z")
			or (character >= "A" and character <= "Z")
			or (character >= "0" and character <= "9")
			or character == "_"
			or character == "-"
		):
			output += character
		else:
			output += "_"
	return output if output != "" else str(fallback)


static func _gml_particle_room_enter_scene(scene):
	if not (scene is Node):
		return
	var candidates = [scene]
	candidates.append_array(scene.find_children("*", "", true, false))
	for node in candidates:
		if (
			not (node is Node2D)
			or not bool(node.get_meta("gamemaker_particle_system_layer_element", false))
		):
			continue
		var current_handle = (
			node.get_meta("gamemaker_particle_system_handle")
			if node.has_meta("gamemaker_particle_system_handle")
			else null
		)
		if current_handle != null and gml_part_system_exists(current_handle):
			continue
		var asset_name = str(node.get_meta("gamemaker_particle_system_name", ""))
		if asset_name == "":
			continue
		var system_handle = gml_part_system_create_layer(node, false, asset_name)
		if not gml_part_system_exists(system_handle):
			continue
		node.set_meta("gamemaker_particle_system_handle", system_handle)
		var cleanup_callable = _gml_particle_room_layer_exiting.bind(node)
		if not node.tree_exiting.is_connected(cleanup_callable):
			node.tree_exiting.connect(cleanup_callable)


static func _gml_particle_room_layer_exiting(node):
	if not (node is Node):
		return
	var system_handle = node.get_meta("gamemaker_particle_system_handle", null)
	node.remove_meta("gamemaker_particle_system_handle")
	if system_handle != null and gml_part_system_exists(system_handle):
		gml_part_system_destroy(system_handle)


static func _gml_particle_system_resolve(system):
	var handle = gml_handle_from_value(GML_PARTICLE_SYSTEM_HANDLE_KIND, system)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY and bool(handle.reference.get("valid", false)):
		return _gml_particle_value(handle.reference)
	return null


static func _gml_particle_type_resolve(particle_type):
	var handle = gml_handle_from_value(GML_PARTICLE_TYPE_HANDLE_KIND, particle_type)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY and bool(handle.reference.get("valid", false)):
		return _gml_particle_value(handle.reference)
	return null


static func _gml_particle_emitter_resolve(system, emitter):
	var system_handle = gml_handle_from_value(GML_PARTICLE_SYSTEM_HANDLE_KIND, system)
	var system_record = _gml_particle_system_resolve(system_handle)
	if system_record == null:
		return null
	var emitter_handle = gml_handle_from_value(GML_PARTICLE_EMITTER_HANDLE_KIND, emitter)
	var emitter_record = _gml_particle_emitter_resolve_any(emitter_handle)
	if emitter_record == null or int(emitter_record["system_index"]) != system_handle.index:
		return null
	var emitters = system_record.get("emitters", {})
	if typeof(emitters) != TYPE_DICTIONARY or not emitters.has(emitter_handle.index):
		return null
	return emitter_record


static func _gml_particle_emitter_resolve_any(emitter):
	var handle = gml_handle_from_value(GML_PARTICLE_EMITTER_HANDLE_KIND, emitter)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY and bool(handle.reference.get("valid", false)):
		return _gml_particle_value(handle.reference)
	return null


static func _gml_particle_value(value):
	return value


static func _gml_particle_type_colours(particle_type, colours):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		var values = []
		for colour in colours:
			values.append(int(_to_real(colour)))
		record.set("colours", values)
	return null


static func _gml_particle_type_alphas(particle_type, alphas):
	var record = _gml_particle_type_resolve(particle_type)
	if record != null:
		var values = []
		for alpha in alphas:
			values.append(clamp(_to_real(alpha), 0.0, 1.0))
		record.set("alphas", values)
	return null


static func _gml_particle_emitter_destroy_record(system_record, emitter):
	var handle = gml_handle_from_value(GML_PARTICLE_EMITTER_HANDLE_KIND, emitter)
	var record = _gml_particle_emitter_resolve_any(handle)
	if typeof(record) != TYPE_DICTIONARY:
		return
	record.set("valid", false)
	if typeof(system_record) == TYPE_DICTIONARY:
		var emitters = system_record.get("emitters", {})
		if typeof(emitters) == TYPE_DICTIONARY:
			emitters.erase(handle.index)
	_gml_particle_free_node(record.get("node", null))
	gml_handle_invalidate(handle)


static func _gml_particle_attach_node(node, layer = 0):
	var parent = _gml_particle_parent_for_layer(layer)
	if parent != null:
		parent.add_child(node)


static func _gml_particle_parent_for_layer(layer):
	if layer is Node:
		return layer
	var resolved_layer = _gml_layer_resolve_node(layer)
	if resolved_layer != null:
		return resolved_layer
	var scene_parent = _gml_particle_scene_parent()
	if is_string(layer) and scene_parent != null:
		var layer_node = scene_parent.find_child(str(layer), true, false)
		if layer_node is Node:
			return layer_node
	return scene_parent


static func _gml_particle_scene_parent():
	var loop = Engine.get_main_loop()
	if loop is SceneTree and loop.current_scene is Node:
		return loop.current_scene
	return null


static func _gml_particle_free_node(node):
	if node is Node and is_instance_valid(node):
		if node.is_inside_tree():
			node.queue_free()
		else:
			node.free()


static func _gml_particle_amount(number):
	return max(0, int(round(_to_real(number))))


static func _gml_particle_relative_amount(record, amount):
	var region = record.get("region", {})
	if typeof(region) != TYPE_DICTIONARY:
		return amount
	var area = abs(_to_real(region.get("xmax", 0.0)) - _to_real(region.get("xmin", 0.0))) * abs(_to_real(region.get("ymax", 0.0)) - _to_real(region.get("ymin", 0.0)))
	if area <= 0.0:
		return amount
	return max(0, int(round(area * float(amount) / 100.0)))


static func _gml_particle_reset_emitter_node(record):
	var node = record["node"]
	if node is GPUParticles2D and is_instance_valid(node):
		node.emitting = false
		node.one_shot = false
		node.amount = 1


static func _gml_particle_apply_emitter_region(record):
	var node = record.get("node", null)
	var region = record.get("region", {})
	if not (node is GPUParticles2D) or not is_instance_valid(node) or typeof(region) != TYPE_DICTIONARY:
		return
	var xmin = _to_real(region.get("xmin", 0.0))
	var xmax = _to_real(region.get("xmax", 0.0))
	var ymin = _to_real(region.get("ymin", 0.0))
	var ymax = _to_real(region.get("ymax", 0.0))
	var left = min(xmin, xmax)
	var top = min(ymin, ymax)
	var width = abs(xmax - xmin)
	var height = abs(ymax - ymin)
	var origin = record.get("origin", Vector2.ZERO)
	if not (origin is Vector2):
		origin = Vector2.ZERO
	node.position = Vector2(left + width / 2.0, top + height / 2.0) - origin
	node.visibility_rect = Rect2(Vector2(-width / 2.0, -height / 2.0), Vector2(max(width, 1.0), max(height, 1.0)))
	_gml_particle_apply_emission_shape(
		_gml_particle_process_material(node),
		str(region.get("shape", "rectangle")),
		width,
		height
	)


static func _gml_particle_apply_emission_shape(material, shape, width, height):
	if not (material is ParticleProcessMaterial):
		return
	var half_width = max(_to_real(width) / 2.0, 0.0)
	var half_height = max(_to_real(height) / 2.0, 0.0)
	material.emission_shape_scale = Vector3.ONE
	if half_width <= 0.0 and half_height <= 0.0:
		material.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_POINT
		return
	match str(shape):
		"ellipse", "diamond":
			var radius = max(half_width, half_height)
			material.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
			material.emission_sphere_radius = radius
			material.emission_shape_scale = Vector3(
				half_width / radius if radius > 0.0 else 1.0,
				half_height / radius if radius > 0.0 else 1.0,
				1.0
			)
		"line":
			material.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
			material.emission_box_extents = Vector3(
				max(half_width, 0.001),
				max(half_height, 0.001),
				1.0
			)
		_:
			material.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
			material.emission_box_extents = Vector3(
				max(half_width, 0.001),
				max(half_height, 0.001),
				1.0
			)


static func _gml_particle_process_material(node):
	if not (node is GPUParticles2D):
		return null
	var material = node.process_material
	if material is ParticleProcessMaterial:
		return material
	material = ParticleProcessMaterial.new()
	node.process_material = material
	return material


static func _gml_particle_apply_draw_order(node, draw_order):
	if not (node is GPUParticles2D):
		return
	node.draw_order = (
		GPUParticles2D.DRAW_ORDER_INDEX
		if str(draw_order) == "old_to_new"
		else GPUParticles2D.DRAW_ORDER_REVERSE_LIFETIME
	)


static func _gml_particle_apply_type_to_node(node, type_record):
	if not (node is GPUParticles2D) or not is_instance_valid(node) or typeof(type_record) != TYPE_DICTIONARY:
		return
	var steps_per_second = _gml_particle_steps_per_second()
	var life_min = _to_real(type_record.get("life_min", 1.0))
	var life_max = _to_real(type_record.get("life_max", 1.0))
	var average_life_steps = max((life_min + life_max) / 2.0, 1.0)
	node.lifetime = max(average_life_steps / steps_per_second, 0.001)
	node.randomness = clamp(
		abs(life_max - life_min) / max(life_min + life_max, 1.0),
		0.0,
		1.0
	)
	node.fixed_fps = max(1, int(round(steps_per_second)))
	var size_min = _to_real(type_record.get("size_min", 1.0))
	var size_max = _to_real(type_record.get("size_max", size_min))
	var scale_x = _to_real(type_record.get("scale_x", 1.0))
	var scale_y = _to_real(type_record.get("scale_y", 1.0))
	node.scale = Vector2(scale_x, scale_y)
	var process_material = _gml_particle_process_material(node)
	process_material.particle_flag_disable_z = true
	process_material.scale_min = max(min(size_min, size_max), 0.001)
	process_material.scale_max = max(max(size_min, size_max), 0.001)
	process_material.scale_curve = _gml_particle_scale_curve(
		average_life_steps,
		(size_min + size_max) / 2.0,
		_to_real(type_record.get("size_incr", 0.0))
	)
	var speed_min = _to_real(type_record.get("speed_min", 0.0))
	var speed_max = _to_real(type_record.get("speed_max", speed_min))
	process_material.initial_velocity_min = min(speed_min, speed_max) * steps_per_second
	process_material.initial_velocity_max = max(speed_min, speed_max) * steps_per_second
	var direction_min = _to_real(type_record.get("direction_min", 0.0))
	var direction_max = _to_real(type_record.get("direction_max", direction_min))
	var direction_center = (direction_min + direction_max) / 2.0
	var direction_radians = deg_to_rad(direction_center)
	process_material.direction = Vector3(
		cos(direction_radians),
		-sin(direction_radians),
		0.0
	)
	process_material.spread = min(abs(direction_max - direction_min) / 2.0, 180.0)
	var gravity_amount = _to_real(type_record.get("gravity_amount", 0.0))
	var gravity_radians = deg_to_rad(
		_to_real(type_record.get("gravity_direction", 270.0))
	)
	process_material.gravity = Vector3(
		cos(gravity_radians),
		-sin(gravity_radians),
		0.0
	) * gravity_amount * steps_per_second * steps_per_second
	process_material.angle_min = _to_real(type_record.get("orientation_min", 0.0))
	process_material.angle_max = _to_real(type_record.get("orientation_max", 0.0))
	var angular_velocity = (
		_to_real(type_record.get("orientation_incr", 0.0))
		* steps_per_second
	)
	var angular_wiggle = (
		abs(_to_real(type_record.get("orientation_wiggle", 0.0)))
		* steps_per_second
	)
	process_material.angular_velocity_min = angular_velocity - angular_wiggle
	process_material.angular_velocity_max = angular_velocity + angular_wiggle
	var colours = type_record.get("colours", [0xffffff])
	var alphas = type_record.get("alphas", [1.0])
	var colour = colours[0] if typeof(colours) == TYPE_ARRAY and not colours.is_empty() else 0xffffff
	var alpha = alphas[0] if typeof(alphas) == TYPE_ARRAY and not alphas.is_empty() else 1.0
	node.modulate = Color.WHITE
	var colour_ramp = _gml_particle_colour_ramp(colours, alphas)
	process_material.color = (
		Color.WHITE
		if colour_ramp != null
		else _gml_draw_modulate(colour, alpha)
	)
	process_material.color_ramp = colour_ramp
	var sprite = type_record.get("sprite", null)
	if sprite != null:
		var frame = _gml_draw_sprite_frame(
			sprite,
			int(round(_to_real(type_record.get("sprite_frame", 0.0))))
		)
		if frame != null and frame.has("texture"):
			node.texture = frame["texture"]
		else:
			node.texture = _gml_particle_builtin_texture(
				str(type_record.get("shape", "pixel"))
			)
	else:
		node.texture = _gml_particle_builtin_texture(
			str(type_record.get("shape", "pixel"))
		)
	var canvas_material = CanvasItemMaterial.new()
	canvas_material.blend_mode = (
		CanvasItemMaterial.BLEND_MODE_ADD
		if bool(type_record.get("blend_additive", false))
		else CanvasItemMaterial.BLEND_MODE_MIX
	)
	canvas_material.particles_animation = bool(
		type_record.get("sprite_animate", false)
	)
	node.material = canvas_material
	node.set_meta(
		"gamemaker_spawn_on_death",
		type_record.get("spawn_on_death", {})
	)
	node.set_meta(
		"gamemaker_spawn_on_update",
		type_record.get("spawn_on_update", {})
	)


static func _gml_particle_steps_per_second():
	var room_speed = _to_real(_gml_builtin_globals.get("room_speed", 0.0))
	if room_speed <= 0.0:
		room_speed = float(Engine.max_fps)
	if room_speed <= 0.0:
		room_speed = 60.0
	return room_speed


static func _gml_particle_scale_curve(life_steps, initial_size, size_increase):
	if abs(_to_real(size_increase)) <= 0.000001:
		return null
	var start_size = max(abs(_to_real(initial_size)), 0.001)
	var end_scale = max(
		0.0,
		(start_size + _to_real(size_increase) * _to_real(life_steps))
			/ start_size
	)
	var curve = Curve.new()
	curve.min_value = min(0.0, end_scale)
	curve.max_value = max(1.0, end_scale)
	curve.add_point(Vector2(0.0, 1.0))
	curve.add_point(Vector2(1.0, end_scale))
	var texture = CurveTexture.new()
	texture.curve = curve
	return texture


static func _gml_particle_colour_ramp(colours, alphas):
	if typeof(colours) != TYPE_ARRAY or colours.size() <= 1:
		return null
	var gradient_colours = PackedColorArray()
	var offsets = PackedFloat32Array()
	for index in range(colours.size()):
		var alpha = (
			alphas[index]
			if typeof(alphas) == TYPE_ARRAY and index < alphas.size()
			else alphas.back()
			if typeof(alphas) == TYPE_ARRAY and not alphas.is_empty()
			else 1.0
		)
		gradient_colours.append(
			_gml_draw_modulate(colours[index], clamp(_to_real(alpha), 0.0, 1.0))
		)
		offsets.append(
			float(index) / float(max(colours.size() - 1, 1))
		)
	var gradient = Gradient.new()
	gradient.offsets = offsets
	gradient.colors = gradient_colours
	var texture = GradientTexture1D.new()
	texture.gradient = gradient
	return texture


static func _gml_particle_builtin_texture(shape):
	var normalized_shape = str(shape)
	if normalized_shape == "pixel":
		var pixel_image = Image.create(1, 1, false, Image.FORMAT_RGBA8)
		pixel_image.set_pixel(0, 0, Color.WHITE)
		return ImageTexture.create_from_image(pixel_image)
	var image = Image.create(16, 16, false, Image.FORMAT_RGBA8)
	for y in range(16):
		for x in range(16):
			var normalized_x = (float(x) - 7.5) / 7.5
			var normalized_y = (float(y) - 7.5) / 7.5
			var alpha = _gml_particle_shape_alpha(
				normalized_shape,
				normalized_x,
				normalized_y
			)
			image.set_pixel(x, y, Color(1.0, 1.0, 1.0, alpha))
	return ImageTexture.create_from_image(image)


static func _gml_particle_shape_alpha(shape, x, y):
	var radius = sqrt(x * x + y * y)
	match str(shape):
		"square":
			return 1.0
		"line":
			return 1.0 if abs(y) <= 0.12 else 0.0
		"circle":
			return 1.0 if abs(radius - 0.78) <= 0.12 else 0.0
		"ring":
			return 1.0 if radius >= 0.48 and radius <= 0.92 else 0.0
		"star":
			var star_limit = 0.38 + 0.42 * abs(cos(atan2(y, x) * 5.0))
			return 1.0 if radius <= star_limit else 0.0
		"flare":
			var flare = max(0.0, 1.0 - radius)
			return clamp(flare + max(0.0, 0.18 - min(abs(x), abs(y))), 0.0, 1.0)
		"spark":
			return 1.0 if min(abs(x), abs(y)) <= 0.1 and radius <= 1.0 else 0.0
		"explosion":
			var edge = 0.72 + 0.16 * sin(float(int((x + 1.0) * 17.0 + (y + 1.0) * 31.0)))
			return clamp((edge - radius) * 6.0, 0.0, 1.0)
		"cloud":
			var cloud = max(
				max(
					1.0 - Vector2(x + 0.32, y).length(),
					1.0 - Vector2(x - 0.32, y).length()
				),
				1.0 - Vector2(x, y + 0.24).length()
			)
			return clamp(cloud * 2.0, 0.0, 1.0)
		"smoke":
			return clamp((1.0 - radius) * 1.35, 0.0, 0.85)
		"snow":
			var angle = atan2(y, x)
			var spoke = min(
				abs(sin(angle)),
				abs(sin(angle + PI / 3.0)),
				abs(sin(angle - PI / 3.0))
			)
			return 1.0 if spoke <= 0.1 and radius <= 0.95 else 0.0
		"disk", "sphere":
			return clamp((1.0 - radius) * 8.0, 0.0, 1.0)
		_:
			return clamp((1.0 - radius) * 2.0, 0.0, 1.0)


static func _gml_particle_burst_emitter_node(record, amount):
	var node = record["node"]
	if node is GPUParticles2D and is_instance_valid(node):
		node.amount = max(1, int(amount))
		node.one_shot = true
		node.explosiveness = 1.0
		node.emitting = int(amount) > 0
		if int(amount) > 0:
			node.restart()


static func _gml_particle_apply_stream(record):
	var node = record["node"]
	if node is GPUParticles2D and is_instance_valid(node):
		var stream_number = _to_real(record["stream_number"])
		var particles_per_step = abs(stream_number)
		if stream_number < 0.0:
			particles_per_step = 1.0 / max(abs(stream_number), 1.0)
		if bool(record.get("relative", false)):
			particles_per_step = float(
				_gml_particle_relative_amount(
					record,
					max(0, int(round(particles_per_step)))
				)
			)
		var cycle_amount = int(round(
			particles_per_step
			* _gml_particle_steps_per_second()
			* max(node.lifetime, 0.001)
		))
		node.amount = max(1, cycle_amount)
		node.one_shot = false
		node.explosiveness = 0.0
		node.emitting = bool(record["enabled"]) and stream_number != 0.0


static func _gml_particle_emit_transient(system_record, x, y, _type_record, amount):
	if int(amount) <= 0 or not (system_record["node"] is Node):
		return
	var node = GPUParticles2D.new()
	node.name = "_gm_particle_direct"
	node.amount = max(1, int(amount))
	node.one_shot = true
	node.emitting = true
	node.position = Vector2(_to_real(x), _to_real(y))
	node.process_material = ParticleProcessMaterial.new()
	_gml_particle_apply_draw_order(
		node,
		system_record.get("draw_order", "old_to_new")
	)
	_gml_particle_apply_type_to_node(node, _type_record)
	system_record["node"].add_child(node)
	node.finished.connect(_gml_particle_transient_finished.bind(node))
	node.restart()


static func _gml_particle_transient_finished(node):
	_gml_particle_free_node(node)
