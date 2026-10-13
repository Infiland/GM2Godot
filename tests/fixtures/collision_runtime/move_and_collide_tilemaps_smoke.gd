extends Node2D
# move_and_collide, mp_linear_step_object and place_empty given tilemap
# elements, alone or in arrays with objects and instances. Each case of
# move_and_collide_tilemap_cases.json places an instance, makes the same call
# once per game step and compares where the instance ends up and what the
# call returns with the HTML5 runner's answers for the same scene: two
# tilemaps built the way the room converter writes tile layers (one with a
# precise tileset mask holding slopes, steps and flipped, mirrored and
# rotated tiles, one with the same tiles and a rectangle mask), a tilemap
# made with layer_tilemap_create and two wall instances.

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
const Instance = preload("res://instance.gd")
const POSITION_TOLERANCE = 0.001

var _failures = []
var _scene = {}
var _tilemaps = {}
var _tileset_ids = {}
var _walls = []


func _norm(value):
	if value is Object and "kind" in value and "index" in value:
		return "handle:%s:%d" % [str(value.kind), int(value.index)]
	return value


func _make(object_name, x, y, sprite):
	var node = Instance.new()
	node.position = Vector2(x, y)
	node.sprite_index = sprite
	add_child(node)
	GMRuntime.gml_instance_register(node, object_name, [])
	return node


func _ready():
	call_deferred("_run")


func _run():
	_scene = JSON.parse_string(FileAccess.get_file_as_string("res://move_and_collide_tilemap_cases.json"))
	GMRuntime._gml_collision_set_compatibility_mode(false)
	_build_tilemaps()
	for wall in _scene["walls"]:
		_walls.append(_make("o_wall", wall[0], wall[1], "spr_box16"))
	for case in _scene["cases"]:
		_run_case(case)
	if _failures.is_empty():
		print("MOVE_AND_COLLIDE_TILEMAPS_OK")
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
	tile_set.set_meta("gamemaker_tileset_sprite", sprite)
	_tileset_ids[name] = GMRuntime.gml_asset_register_dynamic(name, "tileset", tile_set)
	return tile_set


# The converter's tile layer: a TileMapLayer at the layer offset plus the
# element position, behind a layer node, holding the authored tile data as
# metadata.
func _scene_tilemap(layer_name, spec, tile_set):
	var layer = Node2D.new()
	layer.name = layer_name
	layer.set_meta("gamemaker_layer_name", layer_name)
	layer.set_meta("gamemaker_layer_node_name", layer_name)
	layer.set_meta("gamemaker_layer_depth", int(spec["depth"]))
	layer.set_meta("gamemaker_layer_type", "GMRTileLayer")
	layer.set_meta("gamemaker_layer_x", spec["layer"][0])
	layer.set_meta("gamemaker_layer_y", spec["layer"][1])
	add_child(layer)
	var tiles = TileMapLayer.new()
	tiles.name = "TileMap"
	tiles.tile_set = tile_set
	tiles.position = Vector2(spec["element"][0] + spec["layer"][0], spec["element"][1] + spec["layer"][1])
	tiles.set_meta("gamemaker_layer_element_type", "tilemap")
	tiles.set_meta("gamemaker_tile_layer", true)
	tiles.set_meta("gamemaker_tileset", str(spec["tileset"]))
	tiles.set_meta("gamemaker_tile_width", int(spec["width"]))
	tiles.set_meta("gamemaker_tile_height", int(spec["height"]))
	var raw_values = []
	for value in spec["tiles"]:
		raw_values.append(int(value))
	tiles.set_meta("gamemaker_tile_raw_values", raw_values)
	layer.add_child(tiles)


func _build_tilemaps():
	var tile_sets = {}
	for name in _scene["tilesets"].keys():
		tile_sets[name] = _tileset(name, str(_scene["tilesets"][name]))
	var scene_layers = {}
	for name in _scene["tilemaps"].keys():
		var spec = _scene["tilemaps"][name]
		if not spec.get("runtime", false):
			scene_layers[name] = "Tiles_" + name
			_scene_tilemap(scene_layers[name], spec, tile_sets[str(spec["tileset"])])
	GMRuntime.gml_layer_register_scene(self)
	for name in scene_layers.keys():
		_tilemaps[name] = GMRuntime.gml_layer_tilemap_get_id(scene_layers[name])
	for name in _scene["tilemaps"].keys():
		var spec = _scene["tilemaps"][name]
		if not spec.get("runtime", false):
			continue
		var layer = GMRuntime.gml_layer_create(int(spec["depth"]), "Tiles_" + name)
		var width = int(spec["width"])
		var tilemap = GMRuntime.gml_layer_tilemap_create(layer, spec["element"][0], spec["element"][1], _tileset_ids[str(spec["tileset"])], width, int(spec["height"]))
		for index in range(spec["tiles"].size()):
			var value = int(spec["tiles"][index])
			if value != 0:
				GMRuntime.gml_tilemap_set(tilemap, value, index % width, index / width)
		_tilemaps[name] = tilemap
	for name in _tilemaps.keys():
		if not GMRuntime.gml_handle_is_valid(_tilemaps[name]):
			_failures.append("tilemap %s has no valid element" % name)


func _target(spec):
	if spec is Array:
		var targets = []
		for element in spec:
			targets.append(_target(element))
		return targets
	if spec.has("tilemap"):
		return _tilemaps[str(spec["tilemap"])]
	if spec.has("object"):
		return GMRuntime.gml_asset_get_index(str(spec["object"]))
	return GMRuntime._gml_collision_handle_for_instance(_walls[int(spec["wall"])])


# What a returned handle stands for, named as in the cases file.
func _label(hit):
	var key = _norm(hit)
	for name in _tilemaps.keys():
		if key == _norm(_tilemaps[name]):
			return "tilemap:" + name
	for index in range(_walls.size()):
		if key == _norm(GMRuntime._gml_collision_handle_for_instance(_walls[index])):
			return "wall:%d" % index
	return "unknown:" + str(key)


func _move_and_collide(actor, args, target):
	var dx = args[0]
	var dy = args[1]
	match args.size():
		3:
			return GMRuntime.gml_move_and_collide(actor, dx, dy, target)
		4:
			return GMRuntime.gml_move_and_collide(actor, dx, dy, target, args[3])
		6:
			return GMRuntime.gml_move_and_collide(actor, dx, dy, target, args[3], args[4], args[5])
		8:
			return GMRuntime.gml_move_and_collide(actor, dx, dy, target, args[3], args[4], args[5], args[6], args[7])
	_failures.append("unsupported move_and_collide arguments %s" % str(args))
	return []


func _call(actor, call):
	var function_name = str(call[0])
	var args = call.slice(1)
	match function_name:
		"move_and_collide":
			var hits = []
			for hit in _move_and_collide(actor, args, _target(args[2])):
				hits.append(_label(hit))
			return {"hits": hits}
		"mp_linear_step_object":
			return {"result": GMRuntime.gml_mp_linear_step_object(actor, args[0], args[1], args[2], _target(args[3]))}
		"place_empty":
			return {"result": GMRuntime.gml_place_empty(actor, args[0], args[1], _target(args[2]))}
	_failures.append("unknown call " + function_name)
	return {}


func _run_case(case):
	var actor = _make("o_actor", case["x"], case["y"], str(case["sprite"]))
	actor.image_xscale = case["xscale"]
	actor.image_yscale = case["yscale"]
	var expected = case["expected"]
	for step in range(int(case["repeat"])):
		var label = "%s, step %d" % [str(case["name"]), step + 1]
		var record = _call(actor, case["call"])
		var want = expected[step]
		if want.has("hits") and record.get("hits") != want["hits"]:
			_failures.append("%s: returned %s, expected %s" % [label, str(record.get("hits")), str(want["hits"])])
		if want.has("result") and record.get("result") != want["result"]:
			_failures.append("%s: returned %s, expected %s" % [label, str(record.get("result")), str(want["result"])])
		var position = actor.position
		if abs(position.x - want["x"]) > POSITION_TOLERANCE or abs(position.y - want["y"]) > POSITION_TOLERANCE:
			_failures.append("%s: at (%s, %s), expected (%s, %s)" % [label, str(position.x), str(position.y), str(want["x"]), str(want["y"])])
			# Later steps start from a different place.
			break
	GMRuntime.gml_instance_unregister(actor)
	actor.queue_free()
