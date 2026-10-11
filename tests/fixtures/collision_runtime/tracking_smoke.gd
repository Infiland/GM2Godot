extends Node2D
# The runtime keeps converted instances' collision states, and the bounding
# boxes of object instance lists, between queries. Every query here is
# checked against the same query worked out from scratch (a new state for
# every instance, in instance order) after each kind of change GML code can
# make: moving an instance (x/y, motion, its node leaving and re-entering the
# scene tree), changing sprite_index, mask_index, image_xscale, image_yscale
# or image_angle, and creating or destroying instances. GameMaker answers
# with the first instance in creation order, whichever instance moved last.

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

const QUERY_POINT = 1
const QUERY_RECTANGLE = 2
const QUERY_ELLIPSE = 3
const QUERY_LINE = 4
const QUERY_INSTANCE = 5

var _failures = []
var _layer = null
var _checks = 0


func _ready():
	_layer = Node2D.new()
	_layer.name = "Instances"
	add_child(_layer)
	call_deferred("_run")


func _make(object_name, x, y):
	var handle = GMRuntime.gml_instance_create_layer(x, y, "Instances", GMRuntime.gml_asset_get_index(object_name), self)
	return GMRuntime.gml_handle_resolve(handle)


func _index(object_name):
	return GMRuntime.gml_asset_get_index(object_name)


func _name(value):
	if value == null:
		return "noone"
	if value is Node:
		return str(value.get_meta("probe_name", value.name))
	if GMRuntime.is_handle(value):
		if not GMRuntime.gml_handle_is_valid(value):
			return "noone"
		return _name(GMRuntime.gml_handle_resolve(value))
	return str(value)


func _expect(label, actual, expected):
	_checks += 1
	if typeof(actual) == typeof(expected) and actual == expected:
		return
	_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])


# The query worked out from scratch: a new state for every listed instance,
# each one tested in list order.
func _reference(kind, query, target, current_self, notme, prec, every):
	var hits = []
	var entries = GMRuntime._gml_instance_target_entries(target)
	if entries == null:
		return hits if every else null
	for entry in entries:
		var inst = entry["instance"]
		if typeof(inst) != TYPE_OBJECT or not is_instance_valid(inst):
			continue
		if notme and is_same(inst, current_self):
			continue
		var fresh = GMRuntime._gml_collision_current_state(inst, null)
		if not GMRuntime._gml_collision_query_hits(kind, query, fresh, prec):
			continue
		if not every:
			return inst
		hits.append(inst)
	return hits if every else null


# distance_to_object worked out from scratch: the gap to the nearest listed
# instance's new state (the instance itself included).
func _reference_distance(current_self, target):
	var self_state = GMRuntime._gml_collision_current_state(current_self, null)
	var best = 10000000000.0
	var entries = GMRuntime._gml_instance_target_entries(target)
	if entries == null:
		return best
	for entry in entries:
		var inst = entry["instance"]
		if typeof(inst) != TYPE_OBJECT or not is_instance_valid(inst):
			continue
		var distance = GMRuntime._gml_collision_bbox_gap(self_state, GMRuntime._gml_collision_current_state(inst, null))
		if distance < best:
			best = distance
	return best


func _list_names(list_id):
	var names = []
	for index in range(GMRuntime.gml_ds_list_size(list_id)):
		names.append(_name(GMRuntime.gml_ds_list_find_value(list_id, index)))
	return names


func _names(instances):
	var names = []
	for inst in instances:
		names.append(_name(inst))
	return names


# Queries around a bounding box: its corners, the pixels just outside them,
# its middle, and lines and rectangles across it.
func _add_box_queries(box, lines, rects, points, places):
	var left = box[0]
	var top = box[1]
	var right = box[2]
	var bottom = box[3]
	var middle_x = (left + right) * 0.5
	var middle_y = (top + bottom) * 0.5
	for point in [[left, top], [right, bottom], [left - 1, top], [right + 1, bottom + 1], [middle_x, middle_y]]:
		points.append(point)
	lines.append([left - 20, middle_y, right + 20, middle_y])
	lines.append([middle_x, top - 20, middle_x, bottom + 20])
	lines.append([left - 1, top - 1, left - 30, top - 30])
	# Lines along the edges and past the corners, on and just outside the
	# box (the runner reaches up to a pixel past the right and bottom edges
	# in compatibility mode), at a slant too.
	for gap in [0.0, 0.5, 1.0, 1.5, 2.5]:
		lines.append([left - 20, top - gap, right + 20, top - gap])
		lines.append([left - 20, bottom + gap, right + 20, bottom + gap])
		lines.append([left - gap, top - 20, left - gap, bottom + 20])
		lines.append([right + gap, top - 20, right + gap, bottom + 20])
		lines.append([left - gap - 20, top - gap + 20, left - gap + 20, top - gap - 20])
		lines.append([right + gap - 20, top - gap - 20, right + gap + 20, top - gap + 20])
		lines.append([left - gap - 20, bottom + gap - 20, left - gap + 20, bottom + gap + 20])
		lines.append([right + gap - 20, bottom + gap + 20, right + gap + 20, bottom + gap - 20])
		lines.append([right + gap - 5, bottom + gap + 15, right + gap + 5, bottom + gap - 15])
		lines.append([left - gap - 15, top - gap + 5, left - gap + 15, top - gap - 5])
	rects.append([left + 1, top + 1, right - 1, bottom - 1])
	rects.append([right + 1, top, right + 10, bottom])
	places.append([middle_x, middle_y])
	places.append([left - 12, middle_y])


func _fresh_box(inst):
	var fresh = GMRuntime._gml_collision_current_state(inst, null)
	return [fresh["left"], fresh["top"], fresh["right"], fresh["bottom"]]


# Changes an instance and checks the queries, including queries around the
# instance's bounding box from before and after the change.
func _change(stage, probe, inst, change):
	var before = _fresh_box(inst)
	change.call()
	_check_queries(stage, probe, [before, _fresh_box(inst)])


func _check_queries(stage, probe, boxes = []):
	var targets = {"o_wall": _index("o_wall"), "o_post": _index("o_post"), "all": GMRuntime.GML_INSTANCE_ALL_INDEX}
	var lines = [[0, 0, 300, 220], [10, 100, 290, 100], [150, 0, 150, 300], [-50, -50, -10, -10], [40, 200, 260, 20]]
	var rects = [[30, 30, 80, 90], [0, 0, 400, 400], [140, 90, 160, 110], [500, 500, 520, 520]]
	var points = [[50, 50], [100, 100], [150, 100], [200, 150], [8, 8], [260, 40]]
	var places = [[50, 50], [100, 100], [180, 60], [240, 180], [0, 0]]
	for box in boxes:
		_add_box_queries(box, lines, rects, points, places)
	var list_id = GMRuntime.gml_ds_list_create()
	var selves = [probe]
	for entry in GMRuntime._gml_instance_target_entries(_index("o_post")):
		selves.append(entry["instance"])
	for target_name in targets.keys():
		var target = targets[target_name]
		for current_self in selves:
			var label = "%s distance_to_object from %s at %s" % [stage, _name(current_self), target_name]
			_expect(label, GMRuntime.gml_distance_to_object(current_self, target), _reference_distance(current_self, target))
		for line in lines:
			var label = "%s line %s at %s" % [stage, str(line), target_name]
			var actual = GMRuntime.gml_collision_line(probe, line[0], line[1], line[2], line[3], target, false, false)
			_expect(label, _name(actual), _name(_reference(QUERY_LINE, [float(line[0]), float(line[1]), float(line[2]), float(line[3])], target, probe, false, false, false)))
			GMRuntime.gml_ds_list_clear(list_id)
			GMRuntime.gml_collision_line_list(probe, line[0], line[1], line[2], line[3], target, false, true, list_id, false)
			_expect(label + " list", _list_names(list_id), _names(_reference(QUERY_LINE, [float(line[0]), float(line[1]), float(line[2]), float(line[3])], target, probe, true, false, true)))
		for rect in rects:
			var label = "%s rectangle %s at %s" % [stage, str(rect), target_name]
			var query = [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]
			_expect(label, _name(GMRuntime.gml_collision_rectangle(probe, rect[0], rect[1], rect[2], rect[3], target, false, false)), _name(_reference(QUERY_RECTANGLE, query, target, probe, false, false, false)))
			_expect(label + " ellipse", _name(GMRuntime.gml_collision_ellipse(probe, rect[0], rect[1], rect[2], rect[3], target, false, false)), _name(_reference(QUERY_ELLIPSE, query, target, probe, false, false, false)))
		for point in points:
			var label = "%s point %s at %s" % [stage, str(point), target_name]
			_expect(label, _name(GMRuntime.gml_collision_point(probe, point[0], point[1], target, true, false)), _name(_reference(QUERY_POINT, [float(point[0]), float(point[1])], target, probe, false, true, false)))
		for place in places:
			var label = "%s instance_place %s at %s" % [stage, str(place), target_name]
			var fresh_self = GMRuntime._gml_collision_current_state(probe, null)
			var moved = GMRuntime._gml_collision_make_state(probe, float(place[0]), float(place[1]), fresh_self["signature"])
			_expect(label, _name(GMRuntime.gml_instance_place(probe, place[0], place[1], target)), _name(_reference(QUERY_INSTANCE, moved, target, probe, true, true, false)))
			_expect(label + " meeting", GMRuntime.gml_place_meeting(probe, place[0], place[1], target), _reference(QUERY_INSTANCE, moved, target, probe, true, true, false) != null)
	GMRuntime.gml_ds_list_destroy(list_id)


func _run():
	var walls = []
	for row in range(3):
		for column in range(4):
			var wall = _make("o_wall", 30 + column * 70, 30 + row * 70)
			wall.set_meta("probe_name", "wall%d" % walls.size())
			walls.append(wall)
	var posts = []
	for index in range(3):
		var post = _make("o_post", 60 + index * 90, 100)
		post.set_meta("probe_name", "post%d" % index)
		posts.append(post)
	var probe = _make("o_probe", 0, 0)
	probe.set_meta("probe_name", "probe")
	_check_queries("start", probe)
	_check_queries("unchanged", probe)

	# Two overlapping walls: the first created is the one found.
	var first = walls[5]
	var second = walls[6]
	second.position = first.position + Vector2(4, 0)
	var place_at = first.position
	_expect("overlap finds the first created", _name(GMRuntime.gml_collision_point(probe, place_at.x + 2, place_at.y, _index("o_wall"), false, false)), "wall5")
	first.position.x += 200
	_expect("then the other one once the first moved away", _name(GMRuntime.gml_collision_point(probe, place_at.x + 2, place_at.y, _index("o_wall"), false, false)), "wall6")
	first.position.x -= 200
	_expect("and the first again once it is back", _name(GMRuntime.gml_collision_point(probe, place_at.x + 2, place_at.y, _index("o_wall"), false, false)), "wall5")
	_check_queries("overlap", probe)

	_change("moved by position", probe, walls[3], func(): walls[3].position.x += 37)
	_change("moved through y", probe, walls[4], func(): GMRuntime.gml_variable_instance_set(walls[4], "y", 151))
	_change("moved through x", probe, walls[4], func(): GMRuntime.gml_variable_instance_set(walls[4], "x", 99.5))
	_change("moved by global_position", probe, walls[7], func(): walls[7].global_position = Vector2(12, 190))
	_change("sprite_index", probe, walls[8], func(): walls[8].sprite_index = _index("spr_big"))
	_change("mask_index", probe, walls[9], func(): walls[9].mask_index = _index("spr_thin"))
	_change("mask_index through the runtime", probe, walls[9], func(): GMRuntime.gml_variable_instance_set(walls[9], "mask_index", _index("spr_post")))
	_change("mask_index back to the sprite", probe, walls[9], func(): walls[9].mask_index = -1)
	_change("image_xscale", probe, walls[10], func(): walls[10].image_xscale = 3)
	_change("image_yscale", probe, walls[10], func(): walls[10].image_yscale = 0.5)
	_change("image_angle", probe, walls[11], func(): walls[11].image_angle = 45)
	_change("image_xscale through the runtime", probe, walls[0], func(): GMRuntime.gml_variable_instance_set(walls[0], "image_xscale", -2))

	var added = _make("o_wall", 148, 102)
	added.set_meta("probe_name", "added")
	_check_queries("created", probe, [_fresh_box(added)])
	var destroyed_box = _fresh_box(walls[1])
	GMRuntime.gml_instance_destroy(walls[1])
	_check_queries("destroyed", probe, [destroyed_box])
	var added_box = _fresh_box(added)
	GMRuntime.gml_instance_destroy(added)
	_check_queries("created one destroyed", probe, [added_box])

	GMRuntime.gml_motion_set(walls[2], 180, 25)
	_change("moved by motion", probe, walls[2], func(): GMRuntime.gml_motion_step(walls[2]))
	GMRuntime.gml_motion_set(walls[2], 0, 0)

	_change("listed under its parent", probe, posts[1], func(): posts[1].position.y -= 60)

	# A node outside the scene tree reports no transform changes. (Persistent
	# instances stay registered while the room changes; this meta keeps the
	# instance registered outside the tree in the same way.)
	var wall = walls[3]
	wall.set_meta("_gm2godot_room_preserving_persistent", true)
	_change("outside the tree", probe, wall, func():
		_layer.remove_child(wall)
		wall.position = Vector2(150, 100))
	_change("moved outside the tree", probe, wall, func(): wall.position = Vector2(220, 160))
	_change("back in the tree", probe, wall, func(): _layer.add_child(wall))
	_change("moved while outside the tree", probe, wall, func():
		_layer.remove_child(wall)
		wall.position = Vector2(30, 30)
		_layer.add_child(wall))
	_change("mask_index while outside the tree", probe, wall, func():
		_layer.remove_child(wall)
		wall.mask_index = _index("spr_thin")
		_layer.add_child(wall))
	_expect("the instance stayed registered", GMRuntime.gml_instance_exists(wall), true)
	wall.remove_meta("_gm2godot_room_preserving_persistent")

	_change("probe moved", probe, probe, func(): probe.position = Vector2(150, 100))
	_change("probe grown", probe, probe, func(): probe.sprite_index = _index("spr_big"))
	_change("probe masked", probe, probe, func(): probe.mask_index = _index("spr_thin"))
	if _failures.is_empty():
		print("COLLISION_TRACKING_OK %d" % _checks)
		get_tree().quit(0)
		return
	for failure in _failures.slice(0, 40):
		print("FAIL " + failure)
	print("FAILURES %d of %d" % [_failures.size(), _checks])
	get_tree().quit(1)
