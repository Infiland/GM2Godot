extends Node2D
# Converted objects with a collision mask: every instance starts with its
# object's mask in mask_index and collides with that mask instead of its
# sprite. GML code can read and assign mask_index; -1 brings back the sprite.
# Expected boxes follow the HTML5 runner (compatibility mode): the box spans
# x - xorigin + bbox_left to x - xorigin + bbox_right.

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _failures = []


func _expect(label, actual, expected):
	if typeof(actual) in [TYPE_INT, TYPE_FLOAT] and typeof(expected) in [TYPE_INT, TYPE_FLOAT]:
		if abs(float(actual) - float(expected)) <= 0.0005:
			return
	elif typeof(actual) == typeof(expected) and actual == expected:
		return
	_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])


func _make(object_name, x, y):
	var handle = GMRuntime.gml_instance_create_layer(x, y, "Instances", GMRuntime.gml_asset_get_index(object_name), self)
	return GMRuntime.gml_handle_resolve(handle)


func _bbox(inst):
	return [
		GMRuntime.gml_struct_get(inst, "bbox_left"),
		GMRuntime.gml_struct_get(inst, "bbox_top"),
		GMRuntime.gml_struct_get(inst, "bbox_right"),
		GMRuntime.gml_struct_get(inst, "bbox_bottom"),
	]


func _ready():
	var layer = Node2D.new()
	layer.name = "Instances"
	add_child(layer)
	call_deferred("_run")


func _run():
	_run_initial_masks()
	_run_mask_assignments()
	if _failures.is_empty():
		print("OBJECT_COLLISION_MASKS_OK")
		get_tree().quit(0)
		return
	for failure in _failures:
		print("FAIL " + failure)
	get_tree().quit(1)


func _run_initial_masks():
	var hitbox = GMRuntime.gml_asset_get_index("spr_hitbox")
	var masked = _make("o_masked", 100, 100)
	var plain = _make("o_plain", 100, 200)
	var target = _make("o_target", 112, 100)
	var o_target = GMRuntime.gml_asset_get_index("o_target")
	_expect("object mask starts in mask_index", masked.mask_index, hitbox)
	_expect("mask_index reads through the runtime", GMRuntime.gml_variable_instance_get(masked, "mask_index"), hitbox)
	_expect("objects without a mask start at -1", plain.mask_index, -1)
	_expect("the mask does not replace the sprite", GMRuntime.gml_sprite_get_name(masked.sprite_index), "spr_body")
	_expect("bbox comes from the object mask", _bbox(masked), [96.0, 96.0, 103.0, 103.0])
	_expect("bbox of an object without a mask comes from its sprite", _bbox(plain), [84.0, 184.0, 115.0, 215.0])
	_expect("masked instance misses what only its sprite covers", GMRuntime.gml_place_meeting(masked, 100, 100, o_target), false)
	_expect("sprite mask reaches the target", GMRuntime.gml_place_meeting(plain, 100, 100, o_target), true)
	var o_masked = GMRuntime.gml_asset_get_index("o_masked")
	var inside = GMRuntime.gml_instance_position(self, 97, 100, o_masked)
	_expect("instance_position inside the mask", GMRuntime.gml_eq(inside, masked.id), true)
	var outside = GMRuntime.gml_instance_position(self, 90, 100, o_masked)
	_expect("instance_position on the sprite outside the mask", GMRuntime.gml_eq(outside, GMRuntime.gml_instance_noone()), true)
	for inst in [masked, plain, target]:
		GMRuntime.gml_instance_destroy(inst)


func _run_mask_assignments():
	var hitbox = GMRuntime.gml_asset_get_index("spr_hitbox")
	var o_target = GMRuntime.gml_asset_get_index("o_target")
	var masked = _make("o_masked", 100, 100)
	var target = _make("o_target", 112, 100)
	masked.mask_index = -1
	_expect("mask_index = -1 collides with the sprite", GMRuntime.gml_place_meeting(masked, 100, 100, o_target), true)
	_expect("mask_index = -1 bbox", _bbox(masked), [84.0, 84.0, 115.0, 115.0])
	GMRuntime.gml_selector_set(masked, "mask_index", hitbox)
	_expect("mask_index set from another instance", masked.mask_index, hitbox)
	_expect("mask_index set from another instance collides with the mask", GMRuntime.gml_place_meeting(masked, 100, 100, o_target), false)
	var plain = _make("o_plain", 100, 200)
	GMRuntime.gml_variable_instance_set(plain, "mask_index", hitbox)
	_expect("mask_index set in a with block", plain.mask_index, hitbox)
	_expect("mask assigned to an object without one", _bbox(plain), [96.0, 196.0, 103.0, 203.0])
	for inst in [masked, target, plain]:
		GMRuntime.gml_instance_destroy(inst)
