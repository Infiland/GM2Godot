const GML_PHYSICS_FIXTURE_HANDLE_KIND = "physics_fixture"

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


static func _gml_physics_fixture_resolve(fixture):
	var handle = gml_handle_from_value(GML_PHYSICS_FIXTURE_HANDLE_KIND, fixture)
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
