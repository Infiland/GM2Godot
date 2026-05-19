const GML_PHYSICS_FIXTURE_HANDLE_KIND = "physics_fixture"
const GML_PHYSICS_JOINT_HANDLE_KIND = "physics_joint"

static var _gml_physics_world_enabled = false
static var _gml_physics_pixels_to_meters = 0.1
static var _gml_physics_world_gravity = Vector2(0.0, 10.0)
static var _gml_physics_fixture_bindings = {}


static func gml_physics_world_create(pixels_to_meters = 0.1):
	_gml_physics_world_enabled = true
	_gml_physics_pixels_to_meters = max(_to_real(pixels_to_meters), 0.0001)
	return null


static func gml_physics_world_gravity(xgravity, ygravity):
	_gml_physics_world_gravity = Vector2(_to_real(xgravity), _to_real(ygravity))
	return null


static func gml_physics_world_gravity_get():
	return [_gml_physics_world_gravity.x, _gml_physics_world_gravity.y]


static func gml_physics_world_update_speed(_speed):
	return null


static func gml_physics_pause_enable(_enable):
	return null


static func gml_physics_fixture_create():
	var fixture = {
		"shape_kind": "box",
		"width": 1.0,
		"height": 1.0,
		"radius": 1.0,
			"density": 0.0,
			"friction": 0.2,
			"restitution": 0.0,
			"linear_damping": 0.0,
			"angular_damping": 0.0,
			"sensor": false,
			"valid": true
	}
	return gml_handle_register(GML_PHYSICS_FIXTURE_HANDLE_KIND, fixture)


static func gml_physics_fixture_delete(fixture):
	var handle = gml_handle_from_value(GML_PHYSICS_FIXTURE_HANDLE_KIND, fixture)
	var resolved = _gml_physics_fixture_resolve(handle)
	if resolved == null:
		return null
	resolved["valid"] = false
	_gml_physics_fixture_remove_bindings(handle)
	gml_handle_invalidate(handle)
	return null


static func gml_physics_fixture_set_box_shape(fixture, half_width, half_height):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved == null:
		return null
	resolved["shape_kind"] = "box"
	resolved["width"] = max(_to_real(half_width) * 2.0, 0.001)
	resolved["height"] = max(_to_real(half_height) * 2.0, 0.001)
	return null


static func gml_physics_fixture_set_circle_shape(fixture, radius):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved == null:
		return null
	resolved["shape_kind"] = "circle"
	resolved["radius"] = max(_to_real(radius), 0.001)
	return null


static func gml_physics_fixture_set_density(fixture, density):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved != null:
		resolved["density"] = max(_to_real(density), 0.0)
	return null


static func gml_physics_fixture_set_friction(fixture, friction):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved != null:
		resolved["friction"] = max(_to_real(friction), 0.0)
	return null


static func gml_physics_fixture_set_restitution(fixture, restitution):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved != null:
		resolved["restitution"] = max(_to_real(restitution), 0.0)
	return null


static func gml_physics_fixture_set_linear_damping(fixture, damping):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved != null:
		resolved["linear_damping"] = max(_to_real(damping), 0.0)
	return null


static func gml_physics_fixture_set_angular_damping(fixture, damping):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved != null:
		resolved["angular_damping"] = max(_to_real(damping), 0.0)
	return null


static func gml_physics_fixture_set_sensor(fixture, sensor):
	var resolved = _gml_physics_fixture_resolve(fixture)
	if resolved != null:
		resolved["sensor"] = gml_bool(sensor)
	return null


static func gml_physics_fixture_bind(fixture, target):
	var handle = gml_handle_from_value(GML_PHYSICS_FIXTURE_HANDLE_KIND, fixture)
	var resolved = _gml_physics_fixture_resolve(handle)
	if resolved == null:
		return false
	var body = _gml_physics_body(target)
	if body == null:
		return false
	var collision_shape = CollisionShape2D.new()
	collision_shape.name = "_gm_physics_fixture_" + str(handle.index)
	collision_shape.shape = _gml_physics_shape_for_fixture(resolved)
	collision_shape.disabled = bool(resolved["sensor"])
	body.add_child(collision_shape)
	if body is RigidBody2D:
		body.physics_material_override = _gml_physics_material_for_fixture(resolved)
		body.linear_damp = max(_to_real(resolved["linear_damping"]), 0.0)
		body.angular_damp = max(_to_real(resolved["angular_damping"]), 0.0)
	if not _gml_physics_fixture_bindings.has(handle.index):
		_gml_physics_fixture_bindings[handle.index] = []
	_gml_physics_fixture_bindings[handle.index].append(collision_shape)
	return true


static func gml_physics_apply_force(xpos, ypos, xforce, yforce, current_self = null):
	for body in _gml_physics_bodies(current_self):
		body.apply_force(Vector2(_to_real(xforce), _to_real(yforce)), Vector2(_to_real(xpos), _to_real(ypos)))
	return null


static func gml_physics_apply_impulse(xpos, ypos, ximpulse, yimpulse, current_self = null):
	for body in _gml_physics_bodies(current_self):
		body.apply_impulse(Vector2(_to_real(ximpulse), _to_real(yimpulse)), Vector2(_to_real(xpos), _to_real(ypos)))
	return null


static func gml_physics_apply_local_force(xlocal, ylocal, xforce, yforce, current_self = null):
	for body in _gml_physics_bodies(current_self):
		var local_position = Vector2(_to_real(xlocal), _to_real(ylocal))
		body.apply_force(body.global_transform.basis_xform(Vector2(_to_real(xforce), _to_real(yforce))), local_position)
	return null


static func gml_physics_apply_local_impulse(xlocal, ylocal, ximpulse, yimpulse, current_self = null):
	for body in _gml_physics_bodies(current_self):
		var local_position = Vector2(_to_real(xlocal), _to_real(ylocal))
		body.apply_impulse(body.global_transform.basis_xform(Vector2(_to_real(ximpulse), _to_real(yimpulse))), local_position)
	return null


static func gml_physics_apply_angular_impulse(impulse, current_self = null):
	for body in _gml_physics_bodies(current_self):
		body.apply_torque_impulse(_to_real(impulse))
	return null


static func gml_physics_apply_torque(torque, current_self = null):
	for body in _gml_physics_bodies(current_self):
		body.apply_torque(_to_real(torque))
	return null


static func gml_physics_joint_distance_create(inst1, inst2, w_anchor1_x, w_anchor1_y, w_anchor2_x, w_anchor2_y, col):
	var body_a = _gml_physics_body(inst1)
	var body_b = _gml_physics_body(inst2)
	if body_a == null or body_b == null:
		return gml_handle_invalid(GML_PHYSICS_JOINT_HANDLE_KIND)
	var anchor_a = Vector2(_to_real(w_anchor1_x), _to_real(w_anchor1_y))
	var anchor_b = Vector2(_to_real(w_anchor2_x), _to_real(w_anchor2_y))
	var joint = DampedSpringJoint2D.new()
	joint.name = "_gm_physics_distance_joint"
	joint.length = max(anchor_a.distance_to(anchor_b), 0.001)
	joint.rest_length = joint.length
	joint.damping = 1.0
	joint.stiffness = 20.0
	joint.global_position = (anchor_a + anchor_b) / 2.0
	_gml_physics_attach_joint(joint, body_a, body_b, col)
	return _gml_physics_register_joint("distance", joint, body_a, body_b, {
		"anchor_a": anchor_a,
		"anchor_b": anchor_b,
		"collide": gml_bool(col),
		"length": joint.length
	})


static func gml_physics_joint_revolute_create(inst1, inst2, w_anchor_x, w_anchor_y, ang_min_limit, ang_max_limit, ang_limit, max_motor_torque, motor_speed, motor, col):
	var body_a = _gml_physics_body(inst1)
	var body_b = _gml_physics_body(inst2)
	if body_a == null or body_b == null:
		return gml_handle_invalid(GML_PHYSICS_JOINT_HANDLE_KIND)
	var anchor = Vector2(_to_real(w_anchor_x), _to_real(w_anchor_y))
	var joint = PinJoint2D.new()
	joint.name = "_gm_physics_revolute_joint"
	joint.global_position = anchor
	_gml_physics_attach_joint(joint, body_a, body_b, col)
	return _gml_physics_register_joint("revolute", joint, body_a, body_b, {
		"anchor": anchor,
		"angle_min": _to_real(ang_min_limit),
		"angle_max": _to_real(ang_max_limit),
		"angle_limit": gml_bool(ang_limit),
		"max_motor_torque": _to_real(max_motor_torque),
		"motor_speed": _to_real(motor_speed),
		"motor": gml_bool(motor),
		"collide": gml_bool(col)
	})


static func gml_physics_joint_delete(joint_id):
	var handle = gml_handle_from_value(GML_PHYSICS_JOINT_HANDLE_KIND, joint_id)
	var record = _gml_physics_joint_resolve(handle)
	if record == null:
		return null
	record["valid"] = false
	var node = record.get("node", null)
	if node is Node and is_instance_valid(node):
		if node.is_inside_tree():
			node.queue_free()
		else:
			node.free()
	gml_handle_invalidate(handle)
	return null


static func gml_physics_joint_get_value(joint_id, field):
	var record = _gml_physics_joint_resolve(joint_id)
	if record == null:
		return 0
	var data = record.get("data", {})
	var key = str(field)
	if key == "anchor_1_x":
		return data.get("anchor_a", Vector2.ZERO).x
	if key == "anchor_1_y":
		return data.get("anchor_a", Vector2.ZERO).y
	if key == "anchor_2_x":
		return data.get("anchor_b", data.get("anchor", Vector2.ZERO)).x
	if key == "anchor_2_y":
		return data.get("anchor_b", data.get("anchor", Vector2.ZERO)).y
	if key == "length":
		return data.get("length", 0)
	if data.has(key):
		return data[key]
	return 0


static func gml_physics_joint_set_value(joint_id, field, value):
	var record = _gml_physics_joint_resolve(joint_id)
	if record == null:
		return null
	var data = record.get("data", {})
	var key = str(field)
	data[key] = _to_real(value)
	if key == "length":
		data["length"] = max(_to_real(value), 0.001)
		var node = record.get("node", null)
		if node is DampedSpringJoint2D:
			node.length = data["length"]
			node.rest_length = data["length"]
	record["data"] = data
	return null


static func gml_physics_joint_enable_motor(joint_id, motor):
	var record = _gml_physics_joint_resolve(joint_id)
	if record == null:
		return null
	var data = record.get("data", {})
	data["motor"] = gml_bool(motor)
	record["data"] = data
	return null


static func gml_physics_mass_properties(mass, local_center_x, local_center_y, inertia, current_self = null):
	for body in _gml_physics_bodies(current_self):
		if body is RigidBody2D:
			body.mass = max(_to_real(mass), 0.001)
			body.center_of_mass_mode = RigidBody2D.CENTER_OF_MASS_MODE_CUSTOM
			body.center_of_mass = Vector2(_to_real(local_center_x), _to_real(local_center_y))
			body.inertia = max(_to_real(inertia), 0.0)
			body.set_meta("_gm2godot_mass_properties", {
				"mass": body.mass,
				"local_center": body.center_of_mass,
				"inertia": body.inertia
			})
	return null


static func _gml_physics_fixture_resolve(fixture):
	var handle = gml_handle_from_value(GML_PHYSICS_FIXTURE_HANDLE_KIND, fixture)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY and bool(handle.reference.get("valid", false)):
		return handle.reference
	return null


static func _gml_physics_joint_resolve(joint_id):
	var handle = gml_handle_from_value(GML_PHYSICS_JOINT_HANDLE_KIND, joint_id)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY and bool(handle.reference.get("valid", false)):
		return handle.reference
	return null


static func _gml_physics_shape_for_fixture(fixture):
	if str(fixture["shape_kind"]) == "circle":
		var circle = CircleShape2D.new()
		circle.radius = max(_to_real(fixture["radius"]), 0.001)
		return circle
	var rectangle = RectangleShape2D.new()
	rectangle.size = Vector2(max(_to_real(fixture["width"]), 0.001), max(_to_real(fixture["height"]), 0.001))
	return rectangle


static func _gml_physics_material_for_fixture(fixture):
	var material = PhysicsMaterial.new()
	material.friction = max(_to_real(fixture["friction"]), 0.0)
	material.bounce = max(_to_real(fixture["restitution"]), 0.0)
	return material


static func _gml_physics_fixture_remove_bindings(handle):
	if not is_handle(handle) or not _gml_physics_fixture_bindings.has(handle.index):
		return
	for node in _gml_physics_fixture_bindings[handle.index]:
		if node is Node and is_instance_valid(node):
			node.queue_free()
		_gml_physics_fixture_bindings.erase(handle.index)


static func _gml_physics_attach_joint(joint, body_a, body_b, col):
	var parent = _gml_physics_joint_parent(body_a, body_b)
	if parent != null:
		parent.add_child(joint)
	joint.node_a = joint.get_path_to(body_a)
	joint.node_b = joint.get_path_to(body_b)
	joint.disable_collision = not gml_bool(col)


static func _gml_physics_joint_parent(body_a, body_b):
	if body_a is Node and body_a.get_parent() is Node:
		return body_a.get_parent()
	if body_b is Node and body_b.get_parent() is Node:
		return body_b.get_parent()
	var loop = Engine.get_main_loop()
	if loop is SceneTree and loop.current_scene is Node:
		return loop.current_scene
	return null


static func _gml_physics_register_joint(kind, node, body_a, body_b, data):
	var record = {
		"kind": str(kind),
		"node": node,
		"body_a": body_a,
		"body_b": body_b,
		"data": data,
		"valid": true
	}
	var handle = gml_handle_register(GML_PHYSICS_JOINT_HANDLE_KIND, record)
	if node is Node:
		node.name = "_gm_physics_" + str(kind) + "_joint_" + str(handle.index)
	return handle


static func _gml_physics_bodies(target):
	var bodies = []
	var targets = [target] if target != null else []
	for candidate in targets:
		var body = _gml_physics_body(candidate)
		if body is RigidBody2D and not bodies.has(body):
			bodies.append(body)
	return bodies


static func _gml_physics_body(target):
	if target is RigidBody2D:
		return target
	if target is PhysicsBody2D:
		return target
	if is_handle(target):
		var resolved = gml_handle_resolve(target)
		if resolved != null:
			return _gml_physics_body(resolved)
	if target is Node:
		for child in target.get_children():
			if child is PhysicsBody2D:
				return child
	return null
