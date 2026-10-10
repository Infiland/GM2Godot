extends Node2D
# GameMaker motion on generated objects: the speed/direction and
# hspeed/vspeed setters, one step of friction, gravity and movement, and the
# move_* helpers against solid instances. Expected values come from the
# HTML5 runner's arithmetic.

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _failures = []


func _expect(label, actual, expected, tolerance = 0.000001):
	if typeof(actual) in [TYPE_INT, TYPE_FLOAT] and typeof(expected) in [TYPE_INT, TYPE_FLOAT]:
		if abs(float(actual) - float(expected)) <= tolerance:
			return
	elif typeof(actual) == typeof(expected) and actual == expected:
		return
	_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])


func _expect_motion(label, inst, h, v, direction, speed):
	_expect(label + " hspeed", inst.hspeed, h)
	_expect(label + " vspeed", inst.vspeed, v)
	_expect(label + " direction", inst.direction, direction)
	_expect(label + " speed", inst.speed, speed)


func _make(object_name, x, y, extra = {}):
	var handle = GMRuntime.gml_instance_create_layer(x, y, "Instances", GMRuntime.gml_asset_get_index(object_name), self)
	var inst = GMRuntime.gml_handle_resolve(handle)
	for key in extra.keys():
		inst.set(key, extra[key])
	return inst


func _ready():
	var layer = Node2D.new()
	layer.name = "Instances"
	add_child(layer)
	call_deferred("_run")


func _run():
	_run_setters()
	_run_field_writes()
	_run_steps()
	_run_moves()
	if _failures.is_empty():
		print("MOTION_OK")
		get_tree().quit(0)
		return
	for failure in _failures:
		print("FAIL " + failure)
	get_tree().quit(1)


func _run_setters():
	var a = _make("o_mover", 0, 0)
	_expect("instance_create_layer sets xprevious", a.xprevious, 0.0)
	GMRuntime.gml_motion_set_speed(a, 3)
	GMRuntime.gml_motion_set_direction(a, 90)
	_expect_motion("speed then direction", a, 0.0, -3.0, 90.0, 3.0)
	var b = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set(b, 45, 1)
	_expect_motion("motion_set truncates cos and sin", b, 0.707106, -0.707106, 45.0, 1.0)
	var c = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_hspeed(c, 3)
	GMRuntime.gml_motion_set_vspeed(c, 4)
	_expect_motion("components give direction and speed", c, 3.0, 4.0, 306.869898, 5.0)
	var d = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_hspeed(d, 3)
	GMRuntime.gml_motion_add(d, 90, 2)
	_expect_motion("motion_add", d, 3.0, -2.0, 33.690067, 3.605551275463989)
	var h = _make("o_mover", 0, 0)
	GMRuntime.gml_move_towards_point(h, 30, 40, 2)
	_expect_motion("move_towards_point", h, 1.2, 1.599998, 306.869898, 2.0)
	var j = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_direction(j, -90)
	_expect("negative direction wraps", j.direction, 270.0)
	GMRuntime.gml_motion_set_direction(j, 725)
	_expect("large direction wraps", j.direction, 5.0)
	var k = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_speed(k, 2)
	GMRuntime.gml_motion_set_direction(k, 180)
	_expect_motion("whole speeds snap", k, -2.0, 0.0, 180.0, 2.0)
	var l = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_hspeed(l, -1)
	GMRuntime.gml_motion_set_vspeed(l, -1)
	_expect_motion("diagonal components", l, -1.0, -1.0, 135.0, 1.4142135623730951)
	var m = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_speed(m, 1)
	GMRuntime.gml_motion_set_direction(m, 33.3)
	_expect_motion("fractional direction", m, 0.835807, -0.549022, 33.3, 1.0)
	var standstill = _make("o_mover", 0, 0, {"direction": 77.0})
	GMRuntime.gml_motion_set_hspeed(standstill, 0)
	_expect("unchanged hspeed keeps direction", standstill.direction, 77.0)
	GMRuntime.gml_motion_set_vspeed(standstill, 0)
	_expect("standstill keeps direction", standstill.direction, 77.0)
	for inst in [a, b, c, d, h, j, k, l, m, standstill]:
		GMRuntime.gml_instance_destroy(inst)


# Assignments from other instances (other.speed = 3, with (o) direction = 90)
# go through the runtime and must keep the motion variables in step too.
func _run_field_writes():
	var a = _make("o_mover", 0, 0)
	GMRuntime.gml_struct_set(a, "speed", 3)
	_expect_motion("speed written from outside", a, 3.0, 0.0, 0.0, 3.0)
	GMRuntime.gml_selector_set(GMRuntime.gml_asset_get_index("o_mover"), "direction", 90)
	_expect_motion("direction written through with", a, 0.0, -3.0, 90.0, 3.0)
	GMRuntime.gml_selector_update(a, "hspeed", func(value): return GMRuntime.gml_add(value, 4))
	_expect_motion("hspeed updated from outside", a, 4.0, -3.0, 36.869898, 5.0)
	GMRuntime.gml_struct_set(a, "x", 12)
	_expect("x written from outside moves the node", a.position.x, 12.0)
	_expect("x reads the node position", GMRuntime.gml_struct_get(a, "x"), 12.0)
	GMRuntime.gml_struct_set(a, "image_xscale", 2)
	_expect("image_xscale written from outside reaches the instance variable", a.image_xscale, 2.0)
	_expect("image_xscale written from outside scales the instance", a.scale.x, 2.0)
	GMRuntime.gml_instance_destroy(a)


func _run_steps():
	var e = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_speed(e, 5)
	e.friction = 1.0
	GMRuntime.gml_motion_step(e)
	_expect_motion("friction before moving", e, 4.0, 0.0, 0.0, 4.0)
	_expect("friction step x", e.position.x, 4.0)
	var f = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_speed(f, 0.5)
	f.friction = 1.0
	GMRuntime.gml_motion_step(f)
	_expect_motion("friction stops at zero", f, 0.0, 0.0, 0.0, 0.0)
	_expect("friction stop x", f.position.x, 0.0)
	var g = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_hspeed(g, 4)
	g.gravity = 0.5
	GMRuntime.gml_motion_step(g)
	_expect_motion("gravity step 1", g, 4.0, 0.5, 352.874984, 4.031128874149275)
	_expect("gravity step 1 y", g.position.y, 0.5)
	GMRuntime.gml_motion_step(g)
	_expect_motion("gravity step 2", g, 4.0, 1.0, 345.963757, 4.123105625617661)
	_expect("gravity step 2 x", g.position.x, 8.0)
	_expect("gravity step 2 y", g.position.y, 1.5)
	var i = _make("o_mover", 0, 0)
	GMRuntime.gml_motion_set_speed(i, -2)
	i.friction = 0.5
	GMRuntime.gml_motion_step(i)
	_expect_motion("friction on negative speed", i, -1.5, 0.0, 0.0, -1.5)
	_expect("negative speed step x", i.position.x, -1.5)
	for inst in [e, f, g, i]:
		GMRuntime.gml_instance_destroy(inst)


func _run_moves():
	var wall = _make("o_wall", 40, 0)
	_expect("generated wall is solid", wall.solid, true)
	var mover = _make("o_mover", 0, 0)
	GMRuntime.gml_move_contact_solid(mover, 0, 100)
	_expect("move_contact_solid stops before the wall", mover.position.x, 24.0)
	mover.position = Vector2(0, 0)
	GMRuntime.gml_move_contact_solid(mover, 0, 10)
	_expect("move_contact_solid moves at most maxdist", mover.position.x, 10.0)
	mover.position = Vector2(0, 0)
	GMRuntime.gml_move_contact_solid(mover, 135, 10)
	_expect("diagonal move_contact x", mover.position.x, -7.0710678, 0.00001)
	_expect("diagonal move_contact y", mover.position.y, -7.0710678, 0.00001)
	mover.position = Vector2(0, 0)
	GMRuntime.gml_move_contact_all(mover, 0, -1)
	_expect("move_contact_all with no limit", mover.position.x, 24.0)
	mover.position = Vector2(30, 0)
	GMRuntime.gml_move_contact_solid(mover, 0, 100)
	_expect("move_contact_solid does not move a colliding instance", mover.position.x, 30.0)
	GMRuntime.gml_move_outside_solid(mover, 180, 100)
	_expect("move_outside_solid", mover.position.x, 24.0)
	GMRuntime.gml_move_outside_solid(mover, 180, 100)
	_expect("move_outside_solid leaves a free instance alone", mover.position.x, 24.0)
	mover.position = Vector2(40, 0)
	GMRuntime.gml_move_outside_all(mover, 90, 5)
	_expect("move_outside_all stops after maxdist", mover.position.y, -5.0)

	mover.position = Vector2(24, 0)
	GMRuntime.gml_motion_set_hspeed(mover, 2)
	GMRuntime.gml_motion_set_vspeed(mover, 0)
	GMRuntime.gml_move_bounce_solid(mover, false)
	_expect_motion("simple bounce", mover, -2.0, 0.0, 180.0, 2.0)
	mover.position = Vector2(24, 0)
	GMRuntime.gml_motion_set_hspeed(mover, 2)
	GMRuntime.gml_move_bounce_solid(mover, true)
	_expect_motion("advanced bounce", mover, -2.0, 0.0, 180.0, 2.0)
	mover.position = Vector2(30, 0)
	mover.xprevious = 20.0
	mover.yprevious = 0.0
	GMRuntime.gml_motion_set_hspeed(mover, 2)
	GMRuntime.gml_move_bounce_all(mover, false)
	_expect("bounce moves a colliding instance back", mover.position.x, 20.0)
	_expect("bounce from the previous position", mover.hspeed, 2.0)

	mover.position = Vector2(13, 18)
	GMRuntime.gml_move_snap(mover, 16, 16)
	_expect("move_snap x", mover.position.x, 16.0)
	_expect("move_snap y", mover.position.y, 16.0)
	mover.position = Vector2(24, 40)
	GMRuntime.gml_move_snap(mover, 16, 0)
	_expect("move_snap rounds halves to even", mover.position.x, 32.0)
	_expect("move_snap leaves zero snap alone", mover.position.y, 40.0)
	_expect("place_snapped", GMRuntime.gml_place_snapped(mover, 16, 8), true)
	_expect("place_snapped off grid", GMRuntime.gml_place_snapped(mover, 16, 16), false)

	GMRuntime._gml_builtin_globals["room_width"] = 100
	GMRuntime._gml_builtin_globals["room_height"] = 80
	mover.position = Vector2(-5, 90)
	GMRuntime.gml_move_wrap(mover, true, false, 0)
	_expect("move_wrap horizontal", mover.position.x, 95.0)
	_expect("move_wrap leaves vertical", mover.position.y, 90.0)
	GMRuntime.gml_move_wrap(mover, false, true, 4)
	_expect("move_wrap with margin", mover.position.y, 90.0 - 80.0 - 8.0)
	mover.position = Vector2(50, 50)
	GMRuntime.gml_move_random(mover, 4, 4)
	_expect("move_random snaps x", fmod(mover.position.x, 4.0), 0.0)
	_expect("move_random snaps y", fmod(mover.position.y, 4.0), 0.0)
	_expect("move_random keeps the box inside", mover.position.x >= 8.0 and mover.position.x <= 92.0, true)
	_expect("move_random picks a free place", GMRuntime.gml_place_free(mover, mover.position.x, mover.position.y), true)
	GMRuntime.gml_instance_destroy(wall)
	GMRuntime.gml_instance_destroy(mover)
