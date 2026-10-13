extends Node2D
# move_and_collide, mp_linear_step, mp_potential_step and
# mp_grid_add_instances on generated objects with a 16x16 box sprite whose
# origin is its centre (o_corners has a 32x32 precise mask with two opaque
# 4x4 corners). Expected positions come from the HTML5 runner's arithmetic
# (Function_Movement.js and Function_MotionPlanning.js).

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
const POSITION_TOLERANCE = 0.001

var _failures = []


func _expect(label, actual, expected, tolerance = 0.000001):
	if typeof(actual) in [TYPE_INT, TYPE_FLOAT] and typeof(expected) in [TYPE_INT, TYPE_FLOAT]:
		if abs(float(actual) - float(expected)) <= tolerance:
			return
	elif typeof(actual) == typeof(expected) and actual == expected:
		return
	_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])


func _expect_position(label, inst, x, y):
	_expect(label + " x", inst.position.x, x, POSITION_TOLERANCE)
	_expect(label + " y", inst.position.y, y, POSITION_TOLERANCE)


func _expect_hits(label, hits, expected):
	var found = []
	for hit in hits:
		found.append(GMRuntime.gml_handle_resolve(hit))
	if found.size() != expected.size():
		_failures.append("%s: expected %d instances, got %d" % [label, expected.size(), found.size()])
		return
	for index in range(expected.size()):
		if not is_same(found[index], expected[index]):
			_failures.append("%s: instance %d is not the expected one" % [label, index])


func _make(object_name, x, y, extra = {}):
	var handle = GMRuntime.gml_instance_create_layer(x, y, "Instances", GMRuntime.gml_asset_get_index(object_name), self)
	var inst = GMRuntime.gml_handle_resolve(handle)
	for key in extra.keys():
		inst.set(key, extra[key])
	return inst


func _object(object_name):
	return GMRuntime.gml_asset_get_index(object_name)


func _clear():
	for object_name in ["o_mover", "o_wall", "o_block", "o_corners"]:
		GMRuntime.gml_instance_destroy(_object(object_name))


func _ready():
	var layer = Node2D.new()
	layer.name = "Instances"
	add_child(layer)
	call_deferred("_run")


func _run():
	_run_move_and_collide()
	_run_linear_steps()
	_run_potential_steps()
	_run_grid_instances()
	if _failures.is_empty():
		print("MOTION_PLANNING_OK")
		get_tree().quit(0)
		return
	for failure in _failures:
		print("FAIL " + failure)
	get_tree().quit(1)


func _run_move_and_collide():
	var wall = _object("o_wall")
	var mover = _make("o_mover", 100, 100)
	_expect_hits("free move", GMRuntime.gml_move_and_collide(mover, 20, 0, wall), [])
	_expect_position("free move", mover, 120, 100)
	_clear()

	# The third of four 5 pixel steps meets the wall, and no step turned
	# 45 degrees or more either way is free: the instance stops after two
	# steps and the wall is returned once.
	mover = _make("o_mover", 100, 100)
	var head_on = _make("o_wall", 127, 100)
	_expect_hits("blocked move", GMRuntime.gml_move_and_collide(mover, 20, 0, wall), [head_on])
	_expect_position("blocked move", mover, 110, 100)
	_clear()

	# A wall above the path: the step turned 45 degrees upwards is blocked,
	# the one turned downwards is free and counts as one step, then the last
	# step goes straight on.
	mover = _make("o_mover", 100, 100)
	var above = _make("o_wall", 127, 87)
	_expect_hits("slide past", GMRuntime.gml_move_and_collide(mover, 20, 0, wall), [above])
	_expect_position("slide past", mover, 118.5355339, 103.5355339)
	_clear()

	# xoff/yoff replace the two perpendiculars with one direction; upwards
	# stays blocked, so the instance stops.
	mover = _make("o_mover", 100, 100)
	above = _make("o_wall", 127, 87)
	_expect_hits("slide upwards only", GMRuntime.gml_move_and_collide(mover, 20, 0, wall, 4, 0, -1), [above])
	_expect_position("slide upwards only", mover, 110, 100)
	_clear()

	# max_x_move and max_y_move hold the instance within that distance of
	# where it started.
	mover = _make("o_mover", 100, 100)
	_expect_hits("limited move", GMRuntime.gml_move_and_collide(mover, 20, 10, wall, 4, 0, 0, 6, 3), [])
	_expect_position("limited move", mover, 106, 103)
	_clear()

	# An instance that already overlaps does not move.
	mover = _make("o_mover", 120, 100)
	head_on = _make("o_wall", 127, 100)
	_expect_hits("start inside", GMRuntime.gml_move_and_collide(mover, 20, 0, wall), [head_on])
	_expect_position("start inside", mover, 120, 100)
	_expect_hits("noone", GMRuntime.gml_move_and_collide(mover, 20, 0, GMRuntime.gml_instance_noone()), [])
	_expect_hits("noone by number", GMRuntime.gml_move_and_collide(mover, 20, 0, -4), [])
	_expect_position("noone", mover, 120, 100)
	_clear()

	# Any instance of the object blocks, solid or not; other objects do not.
	mover = _make("o_mover", 100, 100)
	var block = _make("o_block", 127, 100)
	_expect_hits("other object", GMRuntime.gml_move_and_collide(mover, 20, 0, wall), [])
	_expect_position("other object", mover, 120, 100)
	GMRuntime.gml_instance_destroy(mover)
	mover = _make("o_mover", 100, 100)
	_expect_hits("all", GMRuntime.gml_move_and_collide(mover, 20, 0, GMRuntime.gml_instance_all()), [block])
	_expect_position("all", mover, 110, 100)
	_clear()


func _run_linear_steps():
	var mover = _make("o_mover", 200, 200)
	_expect("linear step on the way", GMRuntime.gml_mp_linear_step(mover, 200, 170, 4, false), false)
	_expect_position("linear step on the way", mover, 200, 196)
	_expect("linear step sets direction", mover.direction, 90.0)
	_expect("linear step reaches goal", GMRuntime.gml_mp_linear_step(mover, 200, 194, 4, false), true)
	_expect_position("linear step reaches goal", mover, 200, 194)
	_expect("linear step at goal", GMRuntime.gml_mp_linear_step(mover, 200, 194, 4, false), true)
	_clear()

	# A solid wall blocks every call; a non-solid instance only blocks with
	# checkall, or as the object of mp_linear_step_object.
	mover = _make("o_mover", 200, 200)
	_make("o_wall", 200, 180)
	_expect("linear step blocked", GMRuntime.gml_mp_linear_step(mover, 200, 150, 10, false), false)
	_expect_position("linear step blocked", mover, 200, 200)
	_expect("blocked step keeps direction", mover.direction, 0.0)
	_expect("blocked goal still counts as reached", GMRuntime.gml_mp_linear_step(mover, 200, 190, 20, false), true)
	_expect_position("blocked goal", mover, 200, 200)
	_clear()

	mover = _make("o_mover", 200, 200)
	_make("o_block", 200, 180)
	_expect("checkall blocks", GMRuntime.gml_mp_linear_step(mover, 200, 150, 10, true), false)
	_expect_position("checkall blocks", mover, 200, 200)
	_expect("object blocks", GMRuntime.gml_mp_linear_step_object(mover, 200, 150, 10, _object("o_block")), false)
	_expect_position("object blocks", mover, 200, 200)
	_expect("other object does not block", GMRuntime.gml_mp_linear_step_object(mover, 200, 150, 10, _object("o_wall")), false)
	_expect_position("other object does not block", mover, 200, 190)
	_expect("non-solid does not block", GMRuntime.gml_mp_linear_step(mover, 200, 150, 10, false), false)
	_expect_position("non-solid does not block", mover, 200, 180)
	_clear()


func _run_potential_steps():
	var mover = _make("o_mover", 300, 300)
	_expect("potential step free", GMRuntime.gml_mp_potential_step(mover, 340, 300, 4, false), false)
	_expect_position("potential step free", mover, 304, 300)
	GMRuntime.gml_instance_destroy(mover)
	mover = _make("o_mover", 338, 300, {"direction": 90.0})
	_expect("potential step reaches goal", GMRuntime.gml_mp_potential_step(mover, 340, 300, 4, false), true)
	_expect_position("potential step reaches goal", mover, 340, 300)
	_expect("potential step faces goal", mover.direction, 0.0)
	_clear()

	# Straight on and 10 and 20 degrees either way are blocked three steps
	# ahead; 30 degrees upwards is free, the most the direction may turn.
	mover = _make("o_mover", 300, 300)
	_make("o_wall", 325, 310.75)
	_expect("potential step turns", GMRuntime.gml_mp_potential_step(mover, 360, 300, 4, false), false)
	_expect_position("potential step turns", mover, 303.4641016, 298)
	_expect("potential step turns direction", mover.direction, 30.0)
	_clear()

	# Nothing within 30 degrees is free: the instance turns on the spot.
	mover = _make("o_mover", 300, 300)
	_make("o_wall", 325, 300, {"image_yscale": 3.0})
	_expect("potential step stuck", GMRuntime.gml_mp_potential_step(mover, 360, 300, 4, false), false)
	_expect_position("potential step stuck", mover, 300, 300)
	_expect("stuck instance turns on the spot", mover.direction, 30.0)
	GMRuntime.gml_instance_destroy(mover)
	mover = _make("o_mover", 300, 300)
	GMRuntime.gml_mp_potential_settings(mover, 30, 10, 3, false)
	_expect("without onspot", GMRuntime.gml_mp_potential_step(mover, 360, 300, 4, false), false)
	_expect_position("without onspot", mover, 300, 300)
	_expect("without onspot the direction stays", mover.direction, 0.0)
	_clear()

	# With a larger maxrot and rotstep the instance can turn further: one
	# step ahead is blocked straight on but free at 90 degrees.
	mover = _make("o_mover", 300, 300)
	_make("o_wall", 317, 300, {"image_yscale": 3.0})
	GMRuntime.gml_mp_potential_settings(mover, 90, 90, 1, true)
	_expect("wide turn", GMRuntime.gml_mp_potential_step(mover, 360, 300, 4, false), false)
	_expect_position("wide turn", mover, 300, 304)
	_expect("wide turn direction", mover.direction, 270.0)
	_clear()

	GMRuntime.gml_mp_potential_settings(null, 0, -5, 0.5, true)
	_expect("maxrot at least 1", GMRuntime._gml_mp_potential_maxrot, 1.0)
	_expect("rotstep at least 1", GMRuntime._gml_mp_potential_rotstep, 1.0)
	_expect("ahead at least 1", GMRuntime._gml_mp_potential_ahead, 1.0)
	GMRuntime.gml_mp_potential_settings(null, 30, 10, 3, true)

	# A non-solid instance only blocks with checkall or as the object.
	mover = _make("o_mover", 300, 300)
	_make("o_block", 325, 300)
	_expect("non-solid not in the way", GMRuntime.gml_mp_potential_step(mover, 360, 300, 4, false), false)
	_expect_position("non-solid not in the way", mover, 304, 300)
	GMRuntime.gml_instance_destroy(mover)
	mover = _make("o_mover", 300, 300)
	_expect("object in the way", GMRuntime.gml_mp_potential_step_object(mover, 360, 300, 4, _object("o_block")), false)
	_expect_position("object in the way", mover, 300, 300)
	_expect("object in the way turns on the spot", mover.direction, 30.0)
	_clear()


func _blocked_cells(grid):
	var resolved = GMRuntime._gml_mp_grid_resolve(grid)
	var cells = []
	for v in range(int(resolved["vcells"])):
		for h in range(int(resolved["hcells"])):
			if GMRuntime._gml_mp_grid_cell_blocked(resolved, Vector2i(h, v)):
				cells.append(Vector2i(h, v))
	return cells


func _run_grid_instances():
	# The box of an instance at (24, 24) runs from 16 to 32: its right and
	# bottom edges lie on cell borders and stay out of the next cells.
	var grid = GMRuntime.gml_mp_grid_create(0, 0, 6, 6, 16, 16)
	_make("o_wall", 24, 24)
	_make("o_block", 72, 44)
	GMRuntime.gml_mp_grid_add_instances(grid, _object("o_wall"), false)
	_expect("instances of the object", _blocked_cells(grid), [Vector2i(1, 1)])
	GMRuntime.gml_mp_grid_add_instances(grid, GMRuntime.gml_instance_all(), false)
	_expect("all instances", _blocked_cells(grid), [Vector2i(1, 1), Vector2i(4, 2), Vector2i(4, 3)])
	GMRuntime.gml_mp_grid_destroy(grid)
	_clear()

	# The precise mask at (16, 16) covers four cells with its bounding box,
	# but its opaque corners only touch two of them.
	grid = GMRuntime.gml_mp_grid_create(0, 0, 6, 6, 16, 16)
	_make("o_corners", 16, 16)
	GMRuntime.gml_mp_grid_add_instances(grid, _object("o_corners"), true)
	_expect("precise cells", _blocked_cells(grid), [Vector2i(1, 1), Vector2i(2, 2)])
	GMRuntime.gml_mp_grid_add_instances(grid, _object("o_corners"), false)
	_expect("bounding box cells", _blocked_cells(grid), [Vector2i(1, 1), Vector2i(2, 1), Vector2i(1, 2), Vector2i(2, 2)])
	GMRuntime.gml_mp_grid_destroy(grid)
	_clear()

	# Collision compatibility mode does not keep edges out of the next cell:
	# the box at (25, 24) runs from 17 to 32 there.
	GMRuntime._gml_collision_set_compatibility_mode(true)
	grid = GMRuntime.gml_mp_grid_create(0, 0, 6, 6, 16, 16)
	_make("o_wall", 25, 24)
	GMRuntime.gml_mp_grid_add_instances(grid, _object("o_wall"), false)
	_expect("compatibility mode cells", _blocked_cells(grid), [Vector2i(1, 1), Vector2i(2, 1)])
	GMRuntime.gml_mp_grid_destroy(grid)
	_clear()
	GMRuntime._gml_collision_set_compatibility_mode(null)
