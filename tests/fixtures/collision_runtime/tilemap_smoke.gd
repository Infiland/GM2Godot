extends Node2D
# GameMaker collision functions given tilemap elements. tilemap_cases.json
# holds points, rectangles, lines, ellipses and instance placements with the
# HTML5 runner's own answers for two tilemaps: one whose tileset sprite has a
# precise mask, built the way the room converter writes tile layers (behind
# an invisible layer with an offset), and one whose tileset sprite has a
# rectangle mask, made with layer_tilemap_create and tilemap_set. The checks
# after them cover what the functions return for tilemaps, arrays mixing
# tilemaps and objects, and tilemaps that move or change.

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
const Instance = preload("res://instance.gd")

var _failures = []
var _scene = {}
var _tilemaps = {}
var _tileset_ids = {}
var _probe = null


func _norm(value):
	if value is Object and "kind" in value and "index" in value:
		return "handle:%s:%d" % [str(value.kind), int(value.index)]
	return value


func _expect(label, actual, expected):
	var left = _norm(actual)
	var right = _norm(expected)
	if typeof(left) != typeof(right) or left != right:
		_failures.append("%s: expected %s, got %s" % [label, str(right), str(left)])


func _make(object_name, x, y, sprite):
	var node = Instance.new()
	node.position = Vector2(x, y)
	node.sprite_index = sprite
	add_child(node)
	GMRuntime.gml_instance_register(node, object_name, [])
	return node


func _noone():
	return GMRuntime.gml_instance_noone()


func _ready():
	call_deferred("_run")


func _run():
	_scene = JSON.parse_string(FileAccess.get_file_as_string("res://tilemap_cases.json"))
	GMRuntime._gml_collision_set_compatibility_mode(false)
	_build_tilemaps()
	_probe = _make("o_probe", -1000, -1000, "spr_box16")
	_run_runner_cases()
	_run_result_checks()
	_run_array_checks()
	_run_changing_tilemap_checks()
	if _failures.is_empty():
		print("TILEMAP_COLLISIONS_OK")
		get_tree().quit(0)
		return
	for failure in _failures.slice(0, 60):
		print("FAIL " + failure)
	print("FAILURES %d" % _failures.size())
	get_tree().quit(1)


func _tileset(name, sprite):
	var image = Image.create(64, 32, false, Image.FORMAT_RGBA8)
	image.fill(Color(1, 1, 1, 1))
	var atlas = TileSetAtlasSource.new()
	atlas.texture = ImageTexture.create_from_image(image)
	atlas.texture_region_size = Vector2i(16, 16)
	for index in range(8):
		atlas.create_tile(Vector2i(index % 4, index / 4))
	var tile_set = TileSet.new()
	tile_set.tile_size = Vector2i(16, 16)
	tile_set.add_source(atlas, 0)
	tile_set.set_meta("gamemaker_tileset_out_columns", 4)
	tile_set.set_meta("gamemaker_tileset_tile_count", 8)
	if sprite != "":
		tile_set.set_meta("gamemaker_tileset_sprite", sprite)
	_tileset_ids[name] = GMRuntime.gml_asset_register_dynamic(name, "tileset", tile_set)
	return tile_set


func _layer(name, depth, offset):
	var node = Node2D.new()
	node.name = name
	node.set_meta("gamemaker_layer_name", name)
	node.set_meta("gamemaker_layer_node_name", name)
	node.set_meta("gamemaker_layer_depth", depth)
	node.set_meta("gamemaker_layer_type", "GMRTileLayer")
	node.set_meta("gamemaker_layer_x", offset[0])
	node.set_meta("gamemaker_layer_y", offset[1])
	node.set_meta("gamemaker_layer_visible", false)
	node.visible = false
	add_child(node)
	return node


func _build_tilemaps():
	var precise = _scene["tilemaps"]["precise"]
	var precise_set = _tileset("ts_precise", precise["sprite"])
	# The converter's tile layer: a TileMapLayer at the layer offset plus the
	# element position, holding the authored tile data as metadata.
	var layer = _layer("TilesPrecise", 200, precise["layer"])
	var tiles = TileMapLayer.new()
	tiles.name = "TileMap"
	tiles.tile_set = precise_set
	tiles.position = Vector2(precise["element"][0] + precise["layer"][0], precise["element"][1] + precise["layer"][1])
	tiles.set_meta("gamemaker_layer_element_type", "tilemap")
	tiles.set_meta("gamemaker_tile_layer", true)
	tiles.set_meta("gamemaker_tileset", "ts_precise")
	tiles.set_meta("gamemaker_tile_width", int(precise["width"]))
	tiles.set_meta("gamemaker_tile_height", int(precise["height"]))
	var raw_values = []
	for value in precise["tiles"]:
		raw_values.append(int(value))
	tiles.set_meta("gamemaker_tile_raw_values", raw_values)
	layer.add_child(tiles)
	GMRuntime.gml_layer_register_scene(self)
	_tilemaps["precise"] = GMRuntime.gml_layer_tilemap_get_id("TilesPrecise")
	# A tilemap made at run time.
	var box = _scene["tilemaps"]["box"]
	_tileset("ts_box", box["sprite"])
	var box_layer = GMRuntime.gml_layer_create(150, "TilesBox")
	var box_map = GMRuntime.gml_layer_tilemap_create(box_layer, box["element"][0], box["element"][1], _tileset_ids["ts_box"], box["width"], box["height"])
	for index in range(box["tiles"].size()):
		var value = int(box["tiles"][index])
		if value != 0:
			GMRuntime.gml_tilemap_set(box_map, value, index % int(box["width"]), index / int(box["width"]))
	_tilemaps["box"] = box_map
	_expect("precise tilemap handle", GMRuntime.gml_handle_is_valid(_tilemaps["precise"]), true)
	_expect("runtime tilemap handle", GMRuntime.gml_handle_is_valid(box_map), true)


func _hit(expected, tilemap):
	return tilemap if expected else _noone()


func _run_runner_cases():
	var instances = {}
	var index = 0
	for case in _scene["cases"]:
		index += 1
		var kind = str(case[0])
		var tilemap = _tilemaps[str(case[1])]
		var args = case[3]
		var expected = bool(case[4])
		var label = "case %d %s %s %s %s" % [index, kind, str(case[1]), str(case[2]), str(args)]
		match kind:
			"point":
				var precise = bool(case[2])
				_expect(label, GMRuntime.gml_collision_point(_probe, args[0], args[1], tilemap, precise, false), _hit(expected, tilemap))
				if precise:
					# instance_position and position_meeting always test precisely.
					_expect(label + " instance_position", GMRuntime.gml_instance_position(_probe, args[0], args[1], tilemap), _hit(expected, tilemap))
					_expect(label + " position_meeting", GMRuntime.gml_position_meeting(_probe, args[0], args[1], tilemap), expected)
			"rectangle":
				_expect(label, GMRuntime.gml_collision_rectangle(_probe, args[0], args[1], args[2], args[3], tilemap, bool(case[2]), false), _hit(expected, tilemap))
			"line":
				_expect(label, GMRuntime.gml_collision_line(_probe, args[0], args[1], args[2], args[3], tilemap, bool(case[2]), false), _hit(expected, tilemap))
			"ellipse":
				_expect(label, GMRuntime.gml_collision_ellipse(_probe, args[0], args[1], args[2], args[3], tilemap, bool(case[2]), false), _hit(expected, tilemap))
			"place":
				var key = "%s %s" % [str(case[2]), str(args.slice(2))]
				if not instances.has(key):
					var inst = _make("o_probe", -1000, -1000, str(case[2]))
					inst.image_xscale = args[2]
					inst.image_yscale = args[3]
					inst.image_angle = args[4]
					inst.image_index = args[5]
					instances[key] = inst
				var placed = instances[key]
				_expect(label, GMRuntime.gml_place_meeting(placed, args[0], args[1], tilemap), expected)
				_expect(label + " instance_place", GMRuntime.gml_instance_place(placed, args[0], args[1], tilemap), _hit(expected, tilemap))
			_:
				_failures.append("unknown case kind " + kind)
	for inst in instances.values():
		GMRuntime.gml_instance_unregister(inst)
		inst.queue_free()


func _run_result_checks():
	var tilemap = _tilemaps["box"]
	var other_handle = GMRuntime.gml_layer_tilemap_get_id("TilesBox")
	_expect("layer_tilemap_get_id gives the created tilemap", _norm(other_handle), _norm(tilemap))
	var mover = _make("o_probe", 0, 0, "spr_box16")
	# Box tile 1 fills cell (0, 0): 0..16 x 0..16.
	_expect("place_meeting on a tile", GMRuntime.gml_place_meeting(mover, 8, 8, tilemap), true)
	_expect("instance_place returns the tilemap", GMRuntime.gml_instance_place(mover, 8, 8, tilemap), tilemap)
	_expect("place_empty with a tilemap", GMRuntime.gml_place_empty(mover, 8, 8, tilemap), false)
	_expect("place_empty away from tiles", GMRuntime.gml_place_empty(mover, 24, 8, tilemap), true)
	# Boxes that only touch a tile's cell do not meet it.
	_expect("place_meeting next to tiles", GMRuntime.gml_place_meeting(mover, 24, 8, tilemap), false)
	# Only instances count for place_free and place_empty without a target.
	_expect("place_free ignores tilemaps", GMRuntime.gml_place_free(mover, 8, 8), true)
	_expect("place_empty without a target ignores tilemaps", GMRuntime.gml_place_empty(mover, 8, 8), true)
	var list = GMRuntime.gml_ds_list_create()
	_expect("instance_place_list count", GMRuntime.gml_instance_place_list(mover, 8, 8, tilemap, list, false), 1)
	_expect("instance_place_list adds the tilemap", GMRuntime.gml_ds_list_find_value(list, 0), tilemap)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_point_list count", GMRuntime.gml_collision_point_list(mover, 3, 3, tilemap, false, false, list, false), 1)
	_expect("collision_point_list adds the tilemap", GMRuntime.gml_ds_list_find_value(list, 0), tilemap)
	GMRuntime.gml_ds_list_clear(list)
	_expect("instance_position_list count", GMRuntime.gml_instance_position_list(mover, 3, 3, tilemap, list, false), 1)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_rectangle_list count", GMRuntime.gml_collision_rectangle_list(mover, 1, 1, 40, 4, tilemap, false, false, list, false), 1)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_circle_list count", GMRuntime.gml_collision_circle_list(mover, 8, 8, 4, tilemap, false, false, list, false), 1)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_ellipse_list count", GMRuntime.gml_collision_ellipse_list(mover, 2, 2, 12, 12, tilemap, false, false, list, false), 1)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_line_list count", GMRuntime.gml_collision_line_list(mover, 0, 8, 40, 8, tilemap, false, false, list, false), 1)
	GMRuntime.gml_ds_list_clear(list)
	_expect("collision_line_list misses", GMRuntime.gml_collision_line_list(mover, 20, 40, 30, 44, tilemap, false, false, list, false), 0)
	_expect("collision_circle", GMRuntime.gml_collision_circle(mover, 8, 8, 4, tilemap, false, false), tilemap)
	_expect("collision_circle misses", GMRuntime.gml_collision_circle(mover, 24, 8, 4, tilemap, false, false), _noone())
	# An instance without a collision sprite never meets a tilemap.
	var bare = _make("o_probe", 0, 0, -1)
	_expect("instance without a mask", GMRuntime.gml_place_meeting(bare, 8, 8, tilemap), false)
	# A tileset without a sprite has nothing to collide with.
	var spriteless_layer = GMRuntime.gml_layer_create(140, "TilesSpriteless")
	_tileset("ts_spriteless", "")
	var spriteless = GMRuntime.gml_layer_tilemap_create(spriteless_layer, 0, 0, _tileset_ids["ts_spriteless"], 2, 2)
	GMRuntime.gml_tilemap_set(spriteless, 1, 0, 0)
	_expect("tileset without a sprite", GMRuntime.gml_place_meeting(mover, 8, 8, spriteless), false)
	_expect("point on a tileset without a sprite", GMRuntime.gml_position_meeting(mover, 3, 3, spriteless), false)
	GMRuntime.gml_ds_list_destroy(list)
	for inst in [mover, bare]:
		GMRuntime.gml_instance_unregister(inst)
		inst.queue_free()


func _run_array_checks():
	var tilemap = _tilemaps["box"]
	var mover = _make("o_probe", 0, 0, "spr_box16")
	var wall = _make("o_wall", 8, 8, "spr_box16")
	var wall_handle = GMRuntime._gml_collision_handle_for_instance(wall)
	var wall_object = GMRuntime.gml_asset_get_index("o_wall")
	# Arrays are gone through in order, tilemaps and objects alike.
	_expect("object first", GMRuntime.gml_instance_place(mover, 8, 8, [wall_object, tilemap]), wall_handle)
	_expect("tilemap first", GMRuntime.gml_instance_place(mover, 8, 8, [tilemap, wall_object]), tilemap)
	_expect("array with a tilemap meets", GMRuntime.gml_place_meeting(mover, 8, 8, [tilemap]), true)
	_expect("array falls through to the tilemap", GMRuntime.gml_instance_place(mover, 40, 8, [wall_object, tilemap]), tilemap)
	_expect("array of misses", GMRuntime.gml_instance_place(mover, 24, 40, [wall_object, tilemap]), _noone())
	_expect("collision_point in array order", GMRuntime.gml_collision_point(mover, 3, 3, [tilemap, wall_object], false, false), tilemap)
	_expect("instance_position in array order", GMRuntime.gml_instance_position(mover, 3, 3, [wall_object, tilemap]), wall_handle)
	var list = GMRuntime.gml_ds_list_create()
	_expect("list with both", GMRuntime.gml_instance_place_list(mover, 8, 8, [tilemap, wall_object], list, false), 2)
	_expect("list keeps array order 0", GMRuntime.gml_ds_list_find_value(list, 0), tilemap)
	_expect("list keeps array order 1", GMRuntime.gml_ds_list_find_value(list, 1), wall_handle)
	GMRuntime.gml_ds_list_destroy(list)
	for inst in [mover, wall]:
		GMRuntime.gml_instance_unregister(inst)
		inst.queue_free()


func _run_changing_tilemap_checks():
	var tilemap = _tilemaps["box"]
	var mover = _make("o_probe", 0, 0, "spr_box16")
	# Cell (1, 0) is empty, then holds a tile, then is cleared again.
	_expect("empty cell", GMRuntime.gml_place_meeting(mover, 24, 8, tilemap), false)
	GMRuntime.gml_tilemap_set(tilemap, 7, 1, 0)
	_expect("tile set at run time", GMRuntime.gml_place_meeting(mover, 24, 8, tilemap), true)
	GMRuntime.gml_tilemap_set(tilemap, 0, 1, 0)
	_expect("tile cleared at run time", GMRuntime.gml_place_meeting(mover, 24, 8, tilemap), false)
	# The layer offset moves the tilemap: the precise map's full tile 1 sits
	# in cell (1, 0), at 124..140 x 40..56 with the layer at (100, 40).
	var precise = _tilemaps["precise"]
	_expect("precise tile at the layer offset", GMRuntime.gml_position_meeting(mover, 130, 45, precise), true)
	GMRuntime.gml_layer_x("TilesPrecise", 132)
	_expect("layer moved away", GMRuntime.gml_position_meeting(mover, 130, 45, precise), false)
	_expect("layer moved here", GMRuntime.gml_position_meeting(mover, 162, 45, precise), true)
	GMRuntime.gml_layer_x("TilesPrecise", 100)
	_expect("layer moved back", GMRuntime.gml_position_meeting(mover, 130, 45, precise), true)
	GMRuntime.gml_instance_unregister(mover)
	mover.queue_free()
