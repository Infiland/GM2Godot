extends Node2D
# Collision masks of converted sprites: a rectangle mask ignores transparent
# pixels, a precise mask merges every frame, and a precise per-frame mask
# follows image_index for queries and collision events alike. The sprites are
# 4x4 with their origin at (2, 2); frame 0 sets pixel (0, 0) and frame 1 sets
# pixel (3, 3). Like GameMaker, precise point checks round the point to whole
# pixels and centre mask pixels on whole room coordinates, so an instance at
# (50, 20) has pixel (0, 0) at (48, 18).

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
const Instance = preload("res://instance.gd")
const Actor = preload("res://precise_actor.gd")

var _failures = []
var _spawned = []


func _expect(label, actual, expected):
	if typeof(actual) != typeof(expected) or actual != expected:
		_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])


func _make(script, object_name, x, y, sprite, extra = {}):
	var node = script.new()
	node.position = Vector2(x, y)
	node.sprite_index = sprite
	for key in extra.keys():
		node.set(key, extra[key])
	add_child(node)
	GMRuntime.gml_instance_register(node, object_name, [])
	_spawned.append(node)
	return node


func _point(x, y, inst, precise):
	var handle = GMRuntime._gml_collision_handle_for_instance(inst)
	return GMRuntime.gml_handle_is_valid(GMRuntime.gml_collision_point(null, x, y, handle, precise, false))


func _ready():
	call_deferred("_run")


func _run():
	_expect("projects default to exact collisions", GMRuntime._gml_collision_compatibility(), false)
	_check_masks("exact")
	GMRuntime._gml_collision_set_compatibility_mode(true)
	_check_masks("compat")
	if _failures.is_empty():
		print("PRECISE_COLLISION_MASKS_OK")
		get_tree().quit(0)
		return
	for failure in _failures:
		print("FAIL " + failure)
	get_tree().quit(1)


func _check_masks(mode):
	var rectangle = _make(Instance, "rectangle", 10, 20, "spr_rectangle")
	_expect(mode + " rectangle mask covers a transparent pixel", _point(10.5, 20.5, rectangle, true), true)
	_expect(mode + " rectangle mask ends at its bounding box", _point(12.5, 20.5, rectangle, true), false)

	var upright = _make(Instance, "precise_static", 50, 20, "spr_precise_static")
	_expect(mode + " precise mask has frame 0's pixel", _point(48, 18, upright, true), true)
	_expect(mode + " precise mask has frame 1's pixel", _point(51, 21, upright, true), true)
	_expect(mode + " precise point rounds to whole pixels", _point(51.4, 20.6, upright, true), true)
	_expect(mode + " precise point rounds halves to even", _point(51.5, 21, upright, true), false)
	_expect(mode + " precise mask skips transparent pixels", _point(49, 19, upright, true), false)
	_expect(mode + " non-precise query uses the bounding box", _point(49, 19, upright, false), true)

	# Scaled by 2 along x and turned 90 degrees counter-clockwise: sprite x
	# runs up the room and sprite y runs to the right.
	var turned = _make(Instance, "precise_static", 30, 20, "spr_precise_static", {"image_xscale": 2, "image_angle": 90})
	_expect(mode + " turned mask has pixel (0, 0) bottom left", _point(28, 23, turned, true), true)
	_expect(mode + " turned mask has pixel (3, 3) top right", _point(31, 17, turned, true), true)
	_expect(mode + " turned mask skips transparent pixels", _point(29, 21, turned, true), false)
	_expect(mode + " turned bounding box", _point(29, 21, turned, false), true)

	var subject = _make(Actor, "subject", 60, 20, "spr_precise_per_frame")
	var target = _make(Instance, "target", 61.5, 21.5, "spr_rectangle")
	_expect(mode + " per-frame mask hides the inactive frame", _point(61, 21, subject, true), false)
	_expect(mode + " per-frame mask shows the active frame", _point(58, 18, subject, true), true)
	_expect(mode + " collision event ignores the inactive frame", GMRuntime.gml_collision_event_dispatch_frame([subject, target], 1), 0)
	subject.image_index = 1
	_expect(mode + " image_index selects the frame mask", _point(61, 21, subject, true), true)
	_expect(mode + " the inactive frame is gone", _point(58, 18, subject, true), false)
	_expect(mode + " collision event uses the active frame", GMRuntime.gml_collision_event_dispatch_frame([subject, target], 2), 1)
	_expect(mode + " collision event ran once", subject.hits, 1)

	for node in _spawned:
		GMRuntime.gml_instance_destroy(node)
	_spawned.clear()
