extends Node2D
# Converted object hierarchies: every instance starts with its own object's
# sprite (-1 for none), whatever its ancestors' sprites are, and keeps it
# through the ancestors' Create events that event_inherited() runs (or that
# run because the object has no Create event of its own). A room instance's
# image values from the room editor are set before its Create event, which
# can change them (HTML5 yyRoom.js CreateInstance, yyInstance.js
# UpdateSpriteIndex(pObject.SpriteIndex)).

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


# A room instance: the room scene holds the object's scene with the room
# editor's values as metadata.
func _place(object_name, x, y, image_speed):
	var inst = load("res://objects/%s/%s.tscn" % [object_name, object_name]).instantiate()
	inst.position = Vector2(x, y)
	inst.set_meta("gamemaker_image_speed", image_speed)
	inst.set_meta("gamemaker_image_index", 0)
	inst.set_meta("gamemaker_image_xscale", 1.0)
	inst.set_meta("gamemaker_image_yscale", 1.0)
	get_node("Instances").add_child(inst)
	return inst


func _bbox(inst):
	return [
		GMRuntime.gml_struct_get(inst, "bbox_left"),
		GMRuntime.gml_struct_get(inst, "bbox_top"),
		GMRuntime.gml_struct_get(inst, "bbox_right"),
		GMRuntime.gml_struct_get(inst, "bbox_bottom"),
	]


func _sprite_nodes(inst):
	var names = []
	for child in inst.get_children():
		if str(child.name).begins_with("spr_"):
			names.append(str(child.name))
	return names


func _sprite_name(inst):
	return GMRuntime.gml_sprite_asset_name(GMRuntime.gml_struct_get(inst, "sprite_index"))


func _expect_sprite(label, inst, sprite_name, bbox):
	_expect(label + " sprite_index", _sprite_name(inst), sprite_name)
	_expect(label + " sprite node", _sprite_nodes(inst), [sprite_name] if sprite_name != "" else [])
	_expect(label + " image_number", GMRuntime.gml_struct_get(inst, "image_number"), 1 if sprite_name != "" else 0)
	if not bbox.is_empty():
		_expect(label + " bbox", _bbox(inst), bbox)


func _ready():
	var layer = Node2D.new()
	layer.name = "Instances"
	add_child(layer)
	call_deferred("_run")


func _run():
	_run_created_instances()
	_run_room_instance()
	if _failures.is_empty():
		print("SPRITE_INHERITANCE_OK")
		get_tree().quit(0)
		return
	for failure in _failures:
		print("FAIL " + failure)
	get_tree().quit(1)


func _run_created_instances():
	var base = _make("o_base", 100, 100)
	_expect_sprite("o_base", base, "spr_base", [84.0, 84.0, 115.0, 115.0])
	var mid = _make("o_mid", 100, 100)
	_expect_sprite("o_mid (no sprite)", mid, "", [])
	_expect("o_mid ran its Create", [GMRuntime.gml_struct_get(mid, "base_ran"), GMRuntime.gml_struct_get(mid, "mid_ran")], [1, 1])

	# A leaf with a sprite under a middle object without one.
	var leaf = _make("o_leaf", 100, 100)
	_expect_sprite("o_leaf (no Create)", leaf, "spr_leaf", [96.0, 96.0, 103.0, 103.0])
	_expect("o_leaf ran the inherited Create", [GMRuntime.gml_struct_get(leaf, "base_ran"), GMRuntime.gml_struct_get(leaf, "mid_ran")], [1, 1])
	var target = _make("o_target", 100, 100)
	_expect("o_leaf collides with its own sprite", GMRuntime.gml_place_meeting(leaf, 100, 100, GMRuntime.gml_asset_get_index("o_target")), true)
	_expect("o_leaf misses where only the parent sprite would reach", GMRuntime.gml_place_meeting(leaf, 88, 100, GMRuntime.gml_asset_get_index("o_target")), false)
	GMRuntime.gml_instance_destroy(target)

	var leaf_create = _make("o_leaf_create", 100, 100)
	_expect_sprite("o_leaf_create (event_inherited)", leaf_create, "spr_leaf", [96.0, 96.0, 103.0, 103.0])
	_expect("o_leaf_create ran every Create", [GMRuntime.gml_struct_get(leaf_create, "base_ran"), GMRuntime.gml_struct_get(leaf_create, "mid_ran"), GMRuntime.gml_struct_get(leaf_create, "leaf_ran")], [1, 1, 1])

	# A Create event that changes the sprite before event_inherited() keeps it.
	var switcher = _make("o_switcher", 100, 100)
	_expect_sprite("o_switcher (sprite set before event_inherited)", switcher, "spr_base", [])
	_expect("o_switcher image_xscale", GMRuntime.gml_struct_get(switcher, "image_xscale"), 2.0)

	# A leaf without a sprite under objects with sprites has none.
	var bare = _make("o_bare", 100, 100)
	_expect_sprite("o_bare (no sprite under spr_base)", bare, "", [])

	# A middle object with a sprite of its own does not replace the leaf's.
	var under_sprite = _make("o_leaf_under_sprite", 100, 100)
	_expect_sprite("o_leaf_under_sprite", under_sprite, "spr_leaf", [96.0, 96.0, 103.0, 103.0])
	for inst in [base, mid, leaf, leaf_create, switcher, bare, under_sprite]:
		GMRuntime.gml_instance_destroy(inst)


func _run_room_instance():
	# The room editor's image_speed comes before the Create event, which sets
	# image_speed and image_xscale before event_inherited().
	var placed = _place("o_switcher", 100, 100, 1.0)
	_expect_sprite("placed o_switcher", placed, "spr_base", [])
	_expect("placed o_switcher image_speed", GMRuntime.gml_struct_get(placed, "image_speed"), 0.5)
	_expect("placed o_switcher image_xscale", GMRuntime.gml_struct_get(placed, "image_xscale"), 2.0)
	GMRuntime.gml_instance_destroy(placed)
