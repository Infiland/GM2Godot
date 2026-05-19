const GML_PARTICLE_SYSTEM_HANDLE_KIND = "particle_system"
const GML_PARTICLE_TYPE_HANDLE_KIND = "particle_type"
const GML_PARTICLE_EMITTER_HANDLE_KIND = "particle_emitter"


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
		"layer": layer,
		"persistent": gml_bool(persistent),
		"depth": 0.0,
		"position": Vector2.ZERO,
		"node": null,
		"emitters": {},
		"particle_count": 0,
		"valid": true
	}
	var handle = gml_handle_register(GML_PARTICLE_SYSTEM_HANDLE_KIND, record)
	var node = Node2D.new()
	node.name = "_gm_particle_system_" + str(handle.index)
	record["node"] = node
	_gml_particle_attach_node(node, layer)
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
		"sprite_animate": false,
		"sprite_stretch": false,
		"sprite_random": false,
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
	if system_record["node"] is Node:
		system_record["node"].add_child(node)
	var record = {
		"system_index": system_handle.index,
		"node": node,
		"enabled": true,
		"relative": false,
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
		"emitted_count": 0,
		"valid": true
	}
	var handle = gml_handle_register(GML_PARTICLE_EMITTER_HANDLE_KIND, record)
	node.name = "_gm_particle_emitter_" + str(handle.index)
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
	node.position = Vector2(left + width / 2.0, top + height / 2.0)
	node.visibility_rect = Rect2(Vector2(-width / 2.0, -height / 2.0), Vector2(max(width, 1.0), max(height, 1.0)))


static func _gml_particle_apply_type_to_node(node, type_record):
	if not (node is GPUParticles2D) or not is_instance_valid(node) or typeof(type_record) != TYPE_DICTIONARY:
		return
	var life_min = _to_real(type_record.get("life_min", 1.0))
	var life_max = _to_real(type_record.get("life_max", 1.0))
	node.lifetime = max((life_min + life_max) / 120.0, 0.016)
	var size_min = _to_real(type_record.get("size_min", 1.0))
	var size_max = _to_real(type_record.get("size_max", size_min))
	var scale_x = _to_real(type_record.get("scale_x", 1.0))
	var scale_y = _to_real(type_record.get("scale_y", 1.0))
	var size = max((size_min + size_max) / 2.0, 0.001)
	node.scale = Vector2(scale_x * size, scale_y * size)
	var colours = type_record.get("colours", [0xffffff])
	var alphas = type_record.get("alphas", [1.0])
	var colour = colours[0] if typeof(colours) == TYPE_ARRAY and not colours.is_empty() else 0xffffff
	var alpha = alphas[0] if typeof(alphas) == TYPE_ARRAY and not alphas.is_empty() else 1.0
	node.modulate = _gml_draw_modulate(colour, alpha)
	var sprite = type_record.get("sprite", null)
	if sprite != null:
		var frame = _gml_draw_sprite_frame(sprite, 0)
		if frame != null and frame.has("texture"):
			node.texture = frame["texture"]


static func _gml_particle_burst_emitter_node(record, amount):
	var node = record["node"]
	if node is GPUParticles2D and is_instance_valid(node):
		node.amount = max(1, int(amount))
		node.one_shot = true
		node.emitting = int(amount) > 0
		if int(amount) > 0:
			node.restart()


static func _gml_particle_apply_stream(record):
	var node = record["node"]
	if node is GPUParticles2D and is_instance_valid(node):
		var amount = abs(int(round(_to_real(record["stream_number"]))))
		node.amount = max(1, amount)
		node.one_shot = false
		node.emitting = bool(record["enabled"]) and _to_real(record["stream_number"]) != 0.0


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
	_gml_particle_apply_type_to_node(node, _type_record)
	system_record["node"].add_child(node)
	node.restart()
