extends Node2D
# GameMaker collision queries against the HTML5 runner's rules: bounding
# boxes in both collision modes, precise, per-frame, ellipse, diamond and
# rotated masks, result lists, built-in bbox variables and mouse hit tests.

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
const Instance = preload("res://instance.gd")

var _failures = []


func _norm(value):
	if value is Object and "kind" in value and "index" in value:
		return "handle:%s:%d" % [str(value.kind), int(value.index)]
	return value


func _same(actual, expected):
	actual = _norm(actual)
	expected = _norm(expected)
	if typeof(actual) in [TYPE_INT, TYPE_FLOAT] and typeof(expected) in [TYPE_INT, TYPE_FLOAT]:
		return abs(float(actual) - float(expected)) <= 0.0005
	if typeof(actual) == TYPE_ARRAY and typeof(expected) == TYPE_ARRAY:
		if actual.size() != expected.size():
			return false
		for index in range(actual.size()):
			if not _same(actual[index], expected[index]):
				return false
		return true
	return typeof(actual) == typeof(expected) and actual == expected


func _expect(label, actual, expected):
	if not _same(actual, expected):
		_failures.append("%s: expected %s, got %s" % [label, str(_norm(expected)), str(_norm(actual))])


func _make(object_name, x, y, sprite, extra = {}):
	var node = Instance.new()
	node.position = Vector2(x, y)
	node.sprite_index = sprite
	for key in extra.keys():
		node.set(key, extra[key])
	add_child(node)
	GMRuntime.gml_instance_register(node, object_name, [])
	return node


func _handle(inst):
	return GMRuntime._gml_collision_handle_for_instance(inst)


func _noone():
	return GMRuntime.gml_instance_noone()


func _bbox(inst):
	var box = GMRuntime._gml_collision_instance_bbox(inst)
	if box == null:
		return null
	return [box["left"], box["top"], box["right"], box["bottom"]]


func _ready():
	call_deferred("_run")


func _run():
	_expect("project setting turns on compatibility mode", GMRuntime._gml_collision_compatibility(), true)
	_run_bbox_checks()
	_run_builtin_bbox_variables()
	_run_compat_queries()
	_run_exact_queries()
	_run_precise_checks()
	_run_list_checks()
	_run_indexed_object_checks()
	_run_mouse_checks()
	GMRuntime._gml_collision_set_compatibility_mode(null)
	_expect("compatibility mode falls back to the project setting", GMRuntime._gml_collision_compatibility(), true)
	if _failures.is_empty():
		print("COLLISION_QUERIES_OK")
		get_tree().quit(0)
		return
	for failure in _failures:
		print("FAIL " + failure)
	get_tree().quit(1)


func _run_bbox_checks():
	GMRuntime._gml_collision_set_compatibility_mode(true)
	var a = _make("o_a", 10.3, 20.5, "spr_box16")
	_expect("compat bbox rounds edges", _bbox(a), [2.0, 12.0, 17.0, 27.0])
	a.image_xscale = -1
	_expect("compat bbox mirrored", _bbox(a), [2.0, 12.0, 17.0, 27.0])
	a.image_xscale = 2
	a.position = Vector2(10, 20)
	_expect("compat bbox scaled", _bbox(a), [-6.0, 12.0, 25.0, 27.0])
	a.image_yscale = -2
	_expect("compat bbox scaled and flipped", _bbox(a), [-6.0, 4.0, 25.0, 35.0])
	a.image_xscale = 1
	a.image_yscale = 1
	a.image_angle = 90
	_expect("compat bbox rotated 90", _bbox(a), [2.0, 12.0, 17.0, 27.0])
	a.position = Vector2(0, 0)
	a.image_angle = 45
	_expect("compat bbox rotated 45", _bbox(a), [-11.0, -11.0, 10.0, 10.0])
	a.mask_index = "spr_box2"
	a.image_angle = 0
	_expect("mask_index replaces the sprite mask", _bbox(a), [0.0, 0.0, 1.0, 1.0])
	a.mask_index = GMRuntime.gml_asset_get_index("spr_box2")
	_expect("mask_index holding a sprite index", _bbox(a), [0.0, 0.0, 1.0, 1.0])
	a.sprite_index = -1
	_expect("mask_index alone gives a mask", _bbox(a), [0.0, 0.0, 1.0, 1.0])
	a.sprite_index = "spr_box16"
	GMRuntime._gml_collision_set_compatibility_mode(false)
	a.mask_index = -1
	a.position = Vector2(10.3, 20.5)
	_expect("exact bbox keeps fractions", _bbox(a), [2.3, 12.5, 18.3, 28.5])
	a.position = Vector2(0, 0)
	a.image_angle = 45
	var box = _bbox(a)
	_expect("exact bbox rotated 45 left", box[0], -11.3137)
	_expect("exact bbox rotated 45 bottom", box[3], 11.3137)
	var none = _make("o_none", 5, 6, -1)
	_expect("no sprite bbox is null", _bbox(none), null)
	_expect("no sprite bbox_left is x", GMRuntime._gml_collision_instance_bbox_value(none, "bbox_left"), 5.0)
	_expect("no sprite bbox_bottom is y", GMRuntime._gml_collision_instance_bbox_value(none, "bbox_bottom"), 6.0)
	GMRuntime.gml_instance_destroy(a)
	GMRuntime.gml_instance_destroy(none)


func _run_builtin_bbox_variables():
	GMRuntime._gml_collision_set_compatibility_mode(true)
	var a = _make("o_a", 10, 20, "spr_box16")
	_expect("bbox_left reads the mask", GMRuntime.gml_struct_get(a, "bbox_left"), 2.0)
	_expect("bbox_top reads the mask", GMRuntime.gml_struct_get(a, "bbox_top"), 12.0)
	_expect("other.bbox_right reads the mask", GMRuntime.gml_selector_get(a, "bbox_right"), 17.0)
	_expect("with-block bbox_bottom reads the mask", GMRuntime.gml_variable_instance_get(a, "bbox_bottom"), 27.0)
	a.position = Vector2(30, 20)
	_expect("bbox follows the instance", GMRuntime.gml_struct_get(a, "bbox_left"), 22.0)
	GMRuntime.gml_struct_set(a, "bbox_left", 99)
	_expect("bbox variables are read-only", GMRuntime.gml_struct_get(a, "bbox_left"), 22.0)
	_expect("writing bbox adds no instance variable", GMRuntime._gml_object_dynamic_fields(a).has("bbox_left"), false)
	var none = _make("o_none", 5, 6, -1)
	_expect("spriteless bbox_right is x", GMRuntime.gml_struct_get(none, "bbox_right"), 5.0)
	_expect("spriteless bbox_top is y", GMRuntime.gml_struct_get(none, "bbox_top"), 6.0)
	GMRuntime.gml_instance_destroy(a)
	GMRuntime.gml_instance_destroy(none)


func _run_compat_queries():
	GMRuntime._gml_collision_set_compatibility_mode(true)
	var a = _make("o_a", 0, 0, "spr_box16")
	var b = _make("o_b", 16, 0, "spr_box16")
	_expect("compat adjacent boxes do not meet", GMRuntime.gml_place_meeting(a, 0, 0, "o_b"), false)
	_expect("compat one pixel overlap meets", GMRuntime.gml_place_meeting(a, 1, 0, "o_b"), true)
	_expect("compat fractional overlap rounds", GMRuntime.gml_place_meeting(a, 0.4, 0, "o_b"), false)
	_expect("compat 0.6 rounds into overlap", GMRuntime.gml_place_meeting(a, 0.6, 0, "o_b"), true)
	_expect("compat banker's rounding of 0.5", GMRuntime.gml_place_meeting(a, 0.5, 0, "o_b"), false)
	_expect("compat 1.5 rounds to 2", GMRuntime.gml_place_meeting(a, -14.5, 0, "o_b"), false)
	_expect("place_meeting leaves the instance in place", a.position, Vector2(0, 0))
	_expect("instance_place returns the handle", GMRuntime.gml_instance_place(a, 1, 0, "o_b"), _handle(b))
	_expect("instance_place misses", GMRuntime.gml_instance_place(a, 0, 0, "o_b"), _noone())
	_expect("instance_place with an instance target", GMRuntime.gml_instance_place(a, 1, 0, _handle(b)), _handle(b))
	_expect("instance_place with an array target", GMRuntime.gml_instance_place(a, 1, 0, ["o_none", "o_b"]), _handle(b))
	_expect("place_meeting with all", GMRuntime.gml_place_meeting(a, 1, 0, GMRuntime.gml_instance_all()), true)
	_expect("place_meeting never meets itself", GMRuntime.gml_place_meeting(a, 0, 0, "o_a"), false)
	b.position = Vector2(40, 0)
	_expect("compat distance_to_object", GMRuntime.gml_distance_to_object(a, "o_b"), 25.0)
	_expect("distance_to_object of own object includes self", GMRuntime.gml_distance_to_object(a, "o_a"), 0.0)
	_expect("distance_to_object with no instances", GMRuntime.gml_distance_to_object(a, "o_none"), 10000000000.0)
	_expect("compat distance_to_point", GMRuntime.gml_distance_to_point(a, 10, 0), 3.0)
	_expect("compat point inside last column", GMRuntime.gml_position_meeting(a, 7.9, 0, "o_a"), true)
	_expect("compat point past right edge", GMRuntime.gml_position_meeting(a, 8, 0, "o_a"), false)
	_expect("compat point on left edge", GMRuntime.gml_position_meeting(a, -8, 0, "o_a"), true)
	_expect("compat point left of edge", GMRuntime.gml_position_meeting(a, -8.1, 0, "o_a"), false)
	_expect("compat rectangle past edge", GMRuntime.gml_collision_rectangle(null, 8, 0, 20, 5, "o_a", false, false), _noone())
	_expect("compat rectangle on last column", GMRuntime.gml_collision_rectangle(null, 7, 0, 20, 5, "o_a", false, false), _handle(a))
	_expect("compat line below box", GMRuntime.gml_collision_line(null, -20, 8, 20, 8, "o_a", false, false), _noone())
	_expect("compat line on last row", GMRuntime.gml_collision_line(null, -20, 7, 20, 7, "o_a", false, false), _handle(a))
	_expect("compat diagonal line", GMRuntime.gml_collision_line(null, -20, -20, 20, 20, "o_a", false, false), _handle(a))
	_expect("compat line right of box", GMRuntime.gml_collision_line(null, 8, -20, 20, 20, "o_a", false, false), _noone())
	_expect("notme skips the caller", GMRuntime.gml_collision_line(a, -20, 0, 20, 0, "o_a", false, true), _noone())
	_expect("compat circle touching last column misses", GMRuntime.gml_collision_circle(null, 20, 0, 13, "o_a", false, false), _noone())
	_expect("compat circle reaching into box", GMRuntime.gml_collision_circle(null, 20, 0, 13.6, "o_a", false, false), _handle(a))
	_expect("ellipse corner miss", GMRuntime.gml_collision_ellipse(null, 4, 4, 36, 36, "o_a", false, false), _noone())
	_expect("ellipse corner hit", GMRuntime.gml_collision_ellipse(null, 1, 1, 39, 39, "o_a", false, false), _handle(a))
	var none = _make("o_none", 20, 0, -1)
	_expect("no sprite never meets", GMRuntime.gml_place_meeting(a, 20, 0, "o_none"), false)
	_expect("no sprite point miss", GMRuntime.gml_position_meeting(null, 20, 0, "o_none"), false)
	_expect("distance to spriteless instance uses its position", GMRuntime.gml_distance_to_object(a, "o_none"), 13.0)
	_expect("place_free ignores non-solid", GMRuntime.gml_place_free(a, 40, 0), true)
	b.solid = true
	_expect("place_free sees solid", GMRuntime.gml_place_free(a, 40, 0), false)
	_expect("place_empty sees any", GMRuntime.gml_place_empty(a, 40, 0), false)
	_expect("place_empty with object", GMRuntime.gml_place_empty(a, 40, 0, "o_none"), true)
	_expect("position_empty", GMRuntime.gml_position_empty(a, 40, 0), false)
	_expect("position_empty miss", GMRuntime.gml_position_empty(a, 100, 100), true)
	b.solid = false
	GMRuntime.gml_instance_destroy(b)
	_expect("destroyed instances are skipped at once", GMRuntime.gml_place_meeting(a, 40, 0, "o_b"), false)
	GMRuntime.gml_instance_destroy(a)
	GMRuntime.gml_instance_destroy(none)


func _run_exact_queries():
	GMRuntime._gml_collision_set_compatibility_mode(false)
	var a = _make("o_a", 0, 0, "spr_box16")
	var b = _make("o_b", 16, 0, "spr_box16")
	_expect("exact adjacent boxes do not meet", GMRuntime.gml_place_meeting(a, 0, 0, "o_b"), false)
	_expect("exact overlap short of a pixel centre does not meet", GMRuntime.gml_place_meeting(a, 0.4, 0, "o_b"), false)
	_expect("exact overlap reaching a pixel centre meets", GMRuntime.gml_place_meeting(a, 0.5, 0, "o_b"), true)
	b.position = Vector2(15.5, 0)
	_expect("exact half pixel overlap at the left does not meet", GMRuntime.gml_place_meeting(a, 0, 0, "o_b"), false)
	b.position = Vector2(15.4, 0)
	_expect("exact overlap covering a pixel centre meets", GMRuntime.gml_place_meeting(a, 0, 0, "o_b"), true)
	b.position = Vector2(40, 0)
	_expect("exact distance_to_object", GMRuntime.gml_distance_to_object(a, "o_b"), 24.0)
	_expect("exact point inside", GMRuntime.gml_position_meeting(a, 7.9, 0, "o_a"), true)
	_expect("exact point at right edge", GMRuntime.gml_position_meeting(a, 7.99999, 0, "o_a"), false)
	_expect("exact rectangle half pixel", GMRuntime.gml_collision_rectangle(null, 7.6, 0, 20, 5, "o_a", false, false), _noone())
	_expect("exact rectangle over pixel centre", GMRuntime.gml_collision_rectangle(null, 7.4, 0, 20, 5, "o_a", false, false), _handle(a))
	_expect("exact line on bottom edge", GMRuntime.gml_collision_line(null, -20, 8, 20, 8, "o_a", false, false), _noone())
	_expect("exact line inside", GMRuntime.gml_collision_line(null, -20, 7.9, 20, 7.9, "o_a", false, false), _handle(a))
	_expect("exact circle touching", GMRuntime.gml_collision_circle(null, 20, 0, 12, "o_a", false, false), _noone())
	_expect("exact circle overlapping", GMRuntime.gml_collision_circle(null, 20, 0, 12.5, "o_a", false, false), _handle(a))
	GMRuntime.gml_instance_destroy(a)
	GMRuntime.gml_instance_destroy(b)


func _run_precise_checks():
	GMRuntime._gml_collision_set_compatibility_mode(true)
	var dots = _make("o_shape", 10, 10, "spr_dots")
	_expect("precise point on set pixel", GMRuntime.gml_collision_point(null, 10, 10, "o_shape", true, false), _handle(dots))
	_expect("precise point on clear pixel", GMRuntime.gml_collision_point(null, 11, 11, "o_shape", true, false), _noone())
	_expect("box point on clear pixel", GMRuntime.gml_collision_point(null, 11, 11, "o_shape", false, false), _handle(dots))
	_expect("precise point rounds down", GMRuntime.gml_collision_point(null, 10.4, 10, "o_shape", true, false), _handle(dots))
	_expect("precise point rounds up", GMRuntime.gml_collision_point(null, 10.6, 10, "o_shape", true, false), _noone())
	_expect("precise far pixel", GMRuntime.gml_position_meeting(null, 13, 13, "o_shape"), true)
	_expect("precise rectangle miss", GMRuntime.gml_collision_rectangle(null, 11, 11, 12, 12, "o_shape", true, false), _noone())
	_expect("precise rectangle hit", GMRuntime.gml_collision_rectangle(null, 12, 12, 13, 13, "o_shape", true, false), _handle(dots))
	var small = _make("o_b", 11, 11, "spr_box2")
	_expect("precise instance miss inside bbox", GMRuntime.gml_place_meeting(dots, 10, 10, "o_b"), false)
	_expect("precise instance hit", GMRuntime.gml_place_meeting(dots, 9, 9, "o_b"), true)
	GMRuntime._gml_collision_set_compatibility_mode(false)
	_expect("exact precise instance miss", GMRuntime.gml_place_meeting(dots, 10, 10, "o_b"), false)
	_expect("exact precise instance hit", GMRuntime.gml_place_meeting(dots, 9, 9, "o_b"), true)
	GMRuntime._gml_collision_set_compatibility_mode(true)
	GMRuntime.gml_instance_destroy(small)
	GMRuntime.gml_instance_destroy(dots)

	var frames = _make("o_shape", 0, 0, "spr_frames")
	_expect("frame 0 pixel", GMRuntime.gml_position_meeting(null, 0, 0, "o_shape"), true)
	_expect("frame 0 other pixel", GMRuntime.gml_position_meeting(null, 1, 1, "o_shape"), false)
	frames.image_index = 1
	_expect("frame 1 pixel", GMRuntime.gml_position_meeting(null, 1, 1, "o_shape"), true)
	_expect("frame 1 other pixel", GMRuntime.gml_position_meeting(null, 0, 0, "o_shape"), false)
	frames.image_index = 2.7
	_expect("image_index wraps", GMRuntime.gml_position_meeting(null, 0, 0, "o_shape"), true)
	GMRuntime.gml_instance_destroy(frames)

	var ellipse = _make("o_shape", 0, 0, "spr_ellipse")
	_expect("ellipse corner clear", GMRuntime.gml_position_meeting(null, 0, 0, "o_shape"), false)
	_expect("ellipse edge set", GMRuntime.gml_position_meeting(null, 0, 3, "o_shape"), true)
	_expect("ellipse box check", GMRuntime.gml_collision_point(null, 0, 0, "o_shape", false, false), _handle(ellipse))
	GMRuntime.gml_instance_destroy(ellipse)
	var diamond = _make("o_shape", 0, 0, "spr_diamond")
	_expect("diamond edge clear", GMRuntime.gml_position_meeting(null, 0, 3, "o_shape"), false)
	_expect("diamond inner set", GMRuntime.gml_position_meeting(null, 1, 3, "o_shape"), true)
	_expect("diamond top clear", GMRuntime.gml_position_meeting(null, 3, 0, "o_shape"), false)
	_expect("diamond top inner", GMRuntime.gml_position_meeting(null, 3, 1, "o_shape"), true)
	GMRuntime.gml_instance_destroy(diamond)

	var bar = _make("o_shape", 0, 0, "spr_bar", {"image_angle": 45})
	_expect("rotated bar bbox", _bbox(bar), [-7.0, -7.0, 6.0, 6.0])
	_expect("rotated bar along its axis", GMRuntime.gml_position_meeting(null, 5, -5, "o_shape"), true)
	_expect("rotated bar off its axis", GMRuntime.gml_position_meeting(null, 5, 5, "o_shape"), false)
	var probe = _make("o_b", 4, 4, "spr_box2")
	_expect("rotated bar against box off axis", GMRuntime.gml_place_meeting(probe, 4, 4, "o_shape"), false)
	_expect("rotated bar against box on axis", GMRuntime.gml_place_meeting(probe, 4, -5, "o_shape"), true)
	GMRuntime.gml_instance_destroy(probe)
	GMRuntime.gml_instance_destroy(bar)


func _run_list_checks():
	GMRuntime._gml_collision_set_compatibility_mode(true)
	var far = _make("o_a", 30, 0, "spr_box16")
	var near = _make("o_a", 10, 0, "spr_box16")
	var list = GMRuntime.gml_ds_list_create()
	var count = GMRuntime.gml_collision_rectangle_list(null, -100, -100, 100, 100, "o_a", false, false, list, false)
	_expect("unordered list count", count, 2)
	_expect("unordered list keeps instance order", GMRuntime.gml_ds_list_find_value(list, 0), _handle(far))
	GMRuntime.gml_ds_list_clear(list)
	GMRuntime.gml_collision_rectangle_list(null, -10, -10, 10, 10, "o_a", false, false, list, true)
	_expect("ordered list sorts by distance", GMRuntime.gml_ds_list_find_value(list, 0), _handle(near))
	GMRuntime.gml_ds_list_clear(list)
	var mover = _make("o_b", 0, 0, "spr_box16")
	_expect("instance_place_list", GMRuntime.gml_instance_place_list(mover, 15, 0, "o_a", list, true), 2)
	_expect("instance_place_list order", GMRuntime.gml_ds_list_find_value(list, 0), _handle(near))
	GMRuntime.gml_ds_list_clear(list)
	_expect("instance_position_list", GMRuntime.gml_instance_position_list(mover, 25, 0, "o_a", list, false), 1)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_circle_list", GMRuntime.gml_collision_circle_list(null, 10, 0, 1, "o_a", false, false, list, false), 1)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_line_list", GMRuntime.gml_collision_line_list(null, -50, 0, 50, 0, "o_a", false, false, list, true), 2)
	_expect("line list orders from the start point", GMRuntime.gml_ds_list_find_value(list, 0), _handle(near))
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_point_list", GMRuntime.gml_collision_point_list(null, 5, 0, ["o_a", "o_b"], false, false, list, false), 2)
	GMRuntime.gml_ds_list_destroy(list)
	GMRuntime.gml_instance_destroy(far)
	GMRuntime.gml_instance_destroy(near)
	GMRuntime.gml_instance_destroy(mover)


func _run_indexed_object_checks():
	# Converted code names objects by index. Queries against an object keep
	# each instance's collision state between queries, so whatever the
	# bounding box depends on has to show in the very next query.
	GMRuntime._gml_collision_set_compatibility_mode(false)
	var o_a = GMRuntime.gml_asset_get_index("o_a")
	var o_b = GMRuntime.gml_asset_get_index("o_b")
	var b = _make("o_b", 100.3, 100, "spr_box16")
	_expect("indexed object hit", GMRuntime.gml_collision_point(null, 108.1, 95, o_b, false, false), _handle(b))
	GMRuntime._gml_collision_set_compatibility_mode(true)
	_expect("switching the collision mode drops kept states", GMRuntime.gml_collision_point(null, 108.1, 95, o_b, false, false), _noone())
	GMRuntime._gml_collision_set_compatibility_mode(false)
	b.position = Vector2(200, 200)
	_expect("moved instance leaves its old place", GMRuntime.gml_collision_point(null, 95, 95, o_b, false, false), _noone())
	_expect("moved instance is found at its new place", GMRuntime.gml_collision_point(null, 195, 195, o_b, false, false), _handle(b))
	b.image_xscale = 3
	_expect("scaled instance", GMRuntime.gml_collision_point(null, 180, 195, o_b, false, false), _handle(b))
	b.image_xscale = 1
	_expect("unscaled instance", GMRuntime.gml_collision_point(null, 180, 195, o_b, false, false), _noone())
	b.image_angle = 45
	_expect("rotated instance", GMRuntime.gml_collision_point(null, 189, 200, o_b, false, false), _handle(b))
	b.image_angle = 0
	_expect("unrotated instance", GMRuntime.gml_collision_point(null, 189, 200, o_b, false, false), _noone())
	b.mask_index = "spr_box2"
	_expect("mask change", GMRuntime.gml_collision_point(null, 195, 195, o_b, false, false), _noone())
	_expect("new mask", GMRuntime.gml_collision_point(null, 201, 201, o_b, false, false), _handle(b))
	b.mask_index = -1
	b.sprite_index = "spr_box2"
	_expect("sprite change", GMRuntime.gml_collision_point(null, 195, 195, o_b, false, false), _noone())
	b.sprite_index = "spr_box16"
	_expect("sprite change back", GMRuntime.gml_collision_point(null, 195, 195, o_b, false, false), _handle(b))
	_expect("indexed distance_to_object", GMRuntime.gml_distance_to_object(b, o_b), 0.0)
	GMRuntime.gml_instance_destroy(b)

	# Instances of an object, children included, in creation order.
	var first = _make("o_a", 300, 300, "spr_box16")
	var child = Instance.new()
	child.position = Vector2(300, 300)
	child.sprite_index = "spr_box16"
	add_child(child)
	GMRuntime.gml_instance_register(child, "o_shape", ["o_a"])
	var second = _make("o_a", 300, 300, "spr_box16")
	_expect("first instance in creation order", GMRuntime.gml_collision_point(null, 300, 300, o_a, false, false), _handle(first))
	_expect("notme skips the caller", GMRuntime.gml_collision_point(first, 300, 300, o_a, false, true), _handle(child))
	_expect("all by keyword", GMRuntime.gml_collision_point(null, 300, 300, GMRuntime.gml_instance_all(), false, false), _handle(first))
	_expect("all by index", GMRuntime.gml_collision_point(null, 300, 300, GMRuntime.GML_INSTANCE_ALL_INDEX, false, false), _handle(first))
	GMRuntime.gml_instance_destroy(first)
	_expect("children count as the parent's instances", GMRuntime.gml_collision_point(null, 300, 300, o_a, false, false), _handle(child))
	var list = GMRuntime.gml_ds_list_create()
	_expect("indexed list count", GMRuntime.gml_collision_point_list(null, 300, 300, o_a, false, false, list, false), 2)
	_expect("indexed list order", [GMRuntime.gml_ds_list_find_value(list, 0), GMRuntime.gml_ds_list_find_value(list, 1)], [_handle(child), _handle(second)])
	GMRuntime.gml_ds_list_destroy(list)
	var mover = _make("o_b", 0, 0, "spr_box16")
	_expect("place_free without solid instances", GMRuntime.gml_place_free(mover, 300, 300), true)
	second.solid = true
	_expect("place_free with a solid instance", GMRuntime.gml_place_free(mover, 300, 300), false)
	second.solid = false
	# The place a place function tests is kept too.
	_expect("instance at a tested place", GMRuntime.gml_instance_place(mover, 300, 310, o_a), _handle(child))
	mover.mask_index = "spr_box2"
	_expect("tested place with a changed mask", GMRuntime.gml_instance_place(mover, 300, 310, o_a), _noone())
	mover.mask_index = -1
	_expect("tested place with the mask back", GMRuntime.gml_place_meeting(mover, 300, 310, o_a), true)
	# A node freed without being unregistered is passed over.
	child.free()
	_expect("freed instance is passed over", GMRuntime.gml_collision_point(null, 300, 300, o_a, false, false), _handle(second))
	GMRuntime.gml_instance_destroy(second)
	GMRuntime.gml_instance_destroy(mover)
	_expect("no instances left", GMRuntime.gml_collision_point(null, 300, 300, o_a, false, false), _noone())


func _run_mouse_checks():
	GMRuntime._gml_collision_set_compatibility_mode(true)
	var button = _make("o_a", 100, 100, "spr_box16")
	var dots = _make("o_shape", 200, 200, "spr_dots")
	var none = _make("o_none", 300, 300, -1)
	GMRuntime.gml_input_set_mouse_position(95, 107)
	_expect("mouse inside the mask", GMRuntime._gml_input_instance_contains_mouse(button), true)
	GMRuntime.gml_input_set_mouse_position(108, 100)
	_expect("mouse past the mask", GMRuntime._gml_input_instance_contains_mouse(button), false)
	GMRuntime.gml_input_set_mouse_position(201, 201)
	_expect("mouse on a clear pixel of a precise mask", GMRuntime._gml_input_instance_contains_mouse(dots), false)
	GMRuntime.gml_input_set_mouse_position(203, 203)
	_expect("mouse on a set pixel of a precise mask", GMRuntime._gml_input_instance_contains_mouse(dots), true)
	GMRuntime.gml_input_set_mouse_position(300, 300)
	_expect("instances without a mask never see the mouse", GMRuntime._gml_input_instance_contains_mouse(none), false)
	GMRuntime.gml_instance_destroy(button)
	GMRuntime.gml_instance_destroy(dots)
	GMRuntime.gml_instance_destroy(none)
