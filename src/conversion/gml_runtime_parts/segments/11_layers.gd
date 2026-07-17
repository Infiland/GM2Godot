const GML_TILEMAP_EMPTY_SENTINEL = -2147483648
const GML_TILEMAP_INDEX_MASK = 0x0007ffff
const GML_TILEMAP_MIRROR = 0x10000000
const GML_TILEMAP_FLIP = 0x20000000
const GML_TILEMAP_ROTATE = 0x40000000
const GML_TILEMAP_GODOT_FLIP_H = 1 << 12
const GML_TILEMAP_GODOT_FLIP_V = 1 << 13
const GML_TILEMAP_GODOT_TRANSPOSE = 1 << 14


static func gml_layer_register_scene(scene, clear_existing = true):
	if clear_existing:
		_gml_layer_clear_registry()
	if not (scene is Node):
		return false
	for node in _gml_layer_tree_nodes(scene):
		if node == scene:
			continue
		if _gml_layer_node_has_metadata(node):
			_gml_layer_register_node(node)
	return true


static func gml_layer_exists(layer):
	return gml_handle_is_valid(_gml_layer_resolve_handle(layer))


static func gml_layer_get_id(layer_name):
	return _gml_layer_resolve_handle(layer_name)


static func gml_layer_get_id_at_depth(depth):
	_gml_layer_register_current_scene()
	var target_depth = int(_to_real(depth))
	for handle in _gml_layer_all_handles():
		if _gml_layer_handle_depth(handle) == target_depth:
			return handle
	return gml_handle_invalid(GML_LAYER_HANDLE_KIND)


static func gml_layer_get_name(layer):
	var handle = _gml_layer_resolve_handle(layer)
	if not gml_handle_is_valid(handle):
		return ""
	return _gml_layer_handle_name(handle)


static func gml_layer_get_all():
	_gml_layer_register_current_scene()
	return _gml_layer_all_handles()


static func gml_layer_get_depth(layer):
	var handle = _gml_layer_resolve_handle(layer)
	if not gml_handle_is_valid(handle):
		return 0
	return _gml_layer_handle_depth(handle)


static func gml_layer_get_x(layer):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return 0
	return _gml_layer_node_axis(node, "x")


static func gml_layer_get_y(layer):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return 0
	return _gml_layer_node_axis(node, "y")


static func gml_layer_get_hspeed(layer):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return 0
	return _gml_layer_node_speed(node, "h")


static func gml_layer_get_vspeed(layer):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return 0
	return _gml_layer_node_speed(node, "v")


static func gml_layer_depth(layer, depth):
	var handle = _gml_layer_resolve_handle(layer)
	if not gml_handle_is_valid(handle):
		return false
	var node = handle.reference
	if not (node is CanvasItem):
		return false
	var resolved_depth = int(_to_real(depth))
	node.z_index = -resolved_depth
	node.set_meta("gamemaker_layer_depth", resolved_depth)
	return true


static func gml_layer_x(layer, x):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return false
	var value = _to_real(x)
	_gml_layer_set_node_axis(node, "x", value)
	return true


static func gml_layer_y(layer, y):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return false
	var value = _to_real(y)
	_gml_layer_set_node_axis(node, "y", value)
	return true


static func gml_layer_hspeed(layer, speed):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return false
	node.set_meta("gamemaker_layer_hspeed", _to_real(speed))
	return true


static func gml_layer_vspeed(layer, speed):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return false
	node.set_meta("gamemaker_layer_vspeed", _to_real(speed))
	return true


static func gml_layer_set_visible(layer, visible):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return false
	var resolved_visible = gml_bool(visible)
	if node is CanvasItem:
		node.visible = resolved_visible
	node.set_meta("gamemaker_layer_visible", resolved_visible)
	return true


static func gml_layer_get_visible(layer):
	var node = _gml_layer_resolve_node(layer)
	if node == null:
		return false
	if node.has_meta("gamemaker_layer_visible"):
		return bool(node.get_meta("gamemaker_layer_visible"))
	if node is CanvasItem:
		return bool(node.visible)
	return true


static func gml_layer_create(depth, layer_name = ""):
	var parent = _gml_layer_current_scene()
	if parent == null:
		return gml_handle_invalid(GML_LAYER_HANDLE_KIND)
	var resolved_depth = int(_to_real(depth))
	var name = _gml_layer_unique_name(str(layer_name))
	var node = Node2D.new()
	node.name = name
	node.z_index = -resolved_depth
	node.set_meta("gamemaker_layer_name", name)
	node.set_meta("gamemaker_layer_node_name", name)
	node.set_meta("gamemaker_layer_type", "runtime")
	node.set_meta("gamemaker_layer_depth", resolved_depth)
	node.set_meta("gamemaker_layer_visible", true)
	node.set_meta("gamemaker_layer_x", 0)
	node.set_meta("gamemaker_layer_y", 0)
	node.set_meta("gamemaker_layer_hspeed", 0)
	node.set_meta("gamemaker_layer_vspeed", 0)
	node.set_meta("gamemaker_placeholder", true)
	parent.add_child(node)
	return _gml_layer_register_node(node)


static func gml_layer_destroy(layer):
	var handle = _gml_layer_resolve_handle(layer)
	if not gml_handle_is_valid(handle):
		return false
	var node = handle.reference
	if not (node is Node):
		_gml_layer_unregister_handle(handle)
		return false
	for child in _gml_layer_tree_nodes(node):
		var instance_handle = _gml_instance_handle_for_node(child)
		if gml_handle_is_valid(instance_handle):
			gml_instance_unregister(instance_handle)
		var element_handle = _gml_layer_element_handle_for_node(child)
		if gml_handle_is_valid(element_handle):
			_gml_layer_element_unregister_handle(element_handle)
		if child != node and _gml_layer_node_has_metadata(child):
			var child_layer = _gml_layer_handle_for_node(child)
			if gml_handle_is_valid(child_layer):
				_gml_layer_unregister_handle(child_layer)
	_gml_layer_unregister_handle(handle)
	if node.is_inside_tree():
		node.queue_free()
	else:
		node.free()
	return true


static func gml_layer_add_instance(layer, instance):
	var handle = _gml_layer_resolve_handle(layer)
	if not gml_handle_is_valid(handle):
		return false
	var layer_node = handle.reference
	if not (layer_node is Node):
		return false
	var entry: Variant = _gml_instance_entry(instance)
	if entry == null:
		return false
	var instance_node = entry["instance"]
	if not (instance_node is Node):
		return false
	if instance_node.get_parent() == layer_node:
		return true
	if instance_node.get_parent() != null:
		instance_node.reparent(layer_node, true)
	else:
		layer_node.add_child(instance_node)
	return true


static func gml_layer_get_all_elements(layer):
	var handle = _gml_layer_resolve_handle(layer)
	if not gml_handle_is_valid(handle):
		return []
	var node = handle.reference
	if not (node is Node):
		return []
	var elements = []
	for child in node.get_children():
		if _gml_layer_node_has_metadata(child):
			continue
		elements.append(_gml_layer_element_register(child))
	return elements


static func gml_layer_tilemap_get_id(layer):
	var layer_node = _gml_layer_resolve_node(layer)
	if not (layer_node is Node):
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	for child in layer_node.get_children():
		if child is TileMapLayer or (
			child is Object and child.has_meta("gamemaker_tile_layer")
		):
			return _gml_layer_element_register(child)
	return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)


static func gml_layer_tilemap_create(layer, x, y, tileset, width, height):
	var layer_node = _gml_layer_resolve_node(layer)
	if not (layer_node is Node):
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	var tile_set = _gml_draw_tileset_resource(tileset)
	if not (tile_set is TileSet):
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	var resolved_width = int(_to_real(width))
	var resolved_height = int(_to_real(height))
	if resolved_width <= 0 or resolved_height <= 0:
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	var node = TileMapLayer.new()
	node.name = "TileMap"
	node.position = Vector2(_to_real(x), _to_real(y))
	node.tile_set = tile_set
	node.set_meta("gamemaker_layer_element_type", "tilemap")
	node.set_meta("gamemaker_tile_layer", true)
	node.set_meta("gamemaker_tileset", tileset)
	node.set_meta("gamemaker_tile_width", resolved_width)
	node.set_meta("gamemaker_tile_height", resolved_height)
	node.set_meta("gamemaker_tile_raw_cells", {})
	layer_node.add_child(node)
	return _gml_layer_element_register(node)


static func gml_tilemap_set(tilemap_element_id, tiledata, xcell, ycell):
	var node = _gml_layer_element_resolve_node(tilemap_element_id)
	if not (node is TileMapLayer):
		return false
	var coords = Vector2i(int(_to_real(xcell)), int(_to_real(ycell)))
	if not _gml_tilemap_coords_in_bounds(node, coords):
		return false
	var tile_value = int(_to_real(tiledata))
	var raw_cells: Dictionary = node.get_meta("gamemaker_tile_raw_cells", {})
	var tile_index = tile_value & GML_TILEMAP_INDEX_MASK
	if tile_value == GML_TILEMAP_EMPTY_SENTINEL or tile_index == 0:
		node.erase_cell(coords)
		raw_cells[coords] = tile_value
		node.set_meta("gamemaker_tile_raw_cells", raw_cells)
		return true
	var layout = _gml_tilemap_atlas_layout(node.tile_set)
	if layout.is_empty():
		return false
	var atlas_index = tile_index - 1
	var atlas_coords = Vector2i(
		atlas_index % int(layout["columns"]),
		int(floor(float(atlas_index) / float(layout["columns"])))
	)
	var source = layout["source"]
	if source is TileSetAtlasSource and not source.has_tile(atlas_coords):
		return false
	var alternative_tile = _gml_tilemap_transform_to_godot(tile_value)
	node.set_cell(coords, int(layout["source_id"]), atlas_coords, alternative_tile)
	raw_cells[coords] = tile_value
	node.set_meta("gamemaker_tile_raw_cells", raw_cells)
	return true


static func gml_tilemap_get(tilemap_element_id, xcell, ycell):
	var node = _gml_layer_element_resolve_node(tilemap_element_id)
	if not (node is TileMapLayer):
		return -1
	var coords = Vector2i(int(_to_real(xcell)), int(_to_real(ycell)))
	if not _gml_tilemap_coords_in_bounds(node, coords):
		return -1
	var raw_cells: Dictionary = node.get_meta("gamemaker_tile_raw_cells", {})
	if raw_cells.has(coords):
		return int(raw_cells[coords])
	var authored_values = node.get_meta("gamemaker_tile_raw_values", [])
	var authored_index = coords.y * int(node.get_meta("gamemaker_tile_width", 0)) + coords.x
	if authored_values is Array and authored_index >= 0 and authored_index < authored_values.size():
		return int(authored_values[authored_index])
	var source_id = node.get_cell_source_id(coords)
	if source_id < 0:
		return 0
	var layout = _gml_tilemap_atlas_layout(node.tile_set)
	if layout.is_empty():
		return -1
	var atlas_coords = node.get_cell_atlas_coords(coords)
	var tile_value = atlas_coords.y * int(layout["columns"]) + atlas_coords.x + 1
	var alternative_tile = node.get_cell_alternative_tile(coords)
	tile_value |= _gml_tilemap_transform_from_godot(alternative_tile)
	return tile_value


static func gml_tilemap_get_width(tilemap_element_id):
	var node = _gml_layer_element_resolve_node(tilemap_element_id)
	if not (node is TileMapLayer):
		return -1
	return int(node.get_meta("gamemaker_tile_width", 0))


static func gml_tilemap_get_height(tilemap_element_id):
	var node = _gml_layer_element_resolve_node(tilemap_element_id)
	if not (node is TileMapLayer):
		return -1
	return int(node.get_meta("gamemaker_tile_height", 0))


static func gml_layer_element_move(element, layer):
	var element_node = _gml_layer_element_resolve_node(element)
	var layer_node = _gml_layer_resolve_node(layer)
	if element_node == null or layer_node == null:
		return false
	if element_node == layer_node:
		return false
	if not (element_node is Node) or not (layer_node is Node):
		return false
	if element_node.get_parent() == layer_node:
		return true
	if element_node.get_parent() != null:
		element_node.reparent(layer_node, true)
	else:
		layer_node.add_child(element_node)
	_gml_layer_element_register(element_node)
	return true


static func gml_layer_get_element_type(element):
	var node = _gml_layer_element_resolve_node(element)
	if node == null:
		return "undefined"
	if node.has_meta("gamemaker_layer_element_type"):
		return str(node.get_meta("gamemaker_layer_element_type"))
	if (
		node.has_meta("gamemaker_instance_name")
		or node.has_meta("_gm2godot_instance_id")
		or (node is Object and _object_has_property(node, "object_index"))
		or gml_handle_is_valid(_gml_instance_handle_for_node(node))
	):
		return "instance"
	if node.has_meta("gamemaker_tile_layer") or node is TileMapLayer:
		return "tilemap"
	if node.has_meta("gamemaker_background_visual"):
		return "background"
	if node is GPUParticles2D:
		return "particle_system"
	if node.has_meta("gamemaker_sequence_instance"):
		return "sequence"
	if node.has_meta("gamemaker_asset_name"):
		var asset_type = str(node.get_meta("gamemaker_asset_type", ""))
		return _gml_layer_element_type_for_asset_type(asset_type)
	return "undefined"


static func gml_layer_background_get_id(layer):
	var layer_node = _gml_layer_resolve_node(layer)
	if layer_node == null:
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	if _gml_layer_node_is_background(layer_node):
		return _gml_layer_element_register(layer_node)
	if not (layer_node is Node):
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	for child in layer_node.get_children():
		if _gml_layer_node_is_background(child):
			return _gml_layer_element_register(child)
	return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)


static func gml_layer_background_alpha(background, alpha):
	var node = _gml_layer_background_resolve_node(background)
	if node == null:
		return false
	var resolved_alpha = clamp(_to_real(alpha), 0.0, 1.0)
	if node is CanvasItem:
		var color = node.modulate
		color.a = resolved_alpha
		node.modulate = color
	node.set_meta("gamemaker_background_alpha", resolved_alpha)
	return true


static func gml_layer_background_blend(background, color):
	var node = _gml_layer_background_resolve_node(background)
	if node == null:
		return false
	var resolved_color = _gml_layer_background_color(color)
	if node is CanvasItem:
		var modulate = node.modulate
		modulate.r = resolved_color.r
		modulate.g = resolved_color.g
		modulate.b = resolved_color.b
		node.modulate = modulate
	node.set_meta("gamemaker_background_blend", int(_to_real(color)))
	return true


static func _gml_layer_register_current_scene():
	var scene = _gml_layer_current_scene()
	if scene != null:
		gml_layer_register_scene(scene, false)


static func _gml_layer_clear_registry():
	for handle in _gml_layer_handles_by_index.values():
		if handle is GMLHandle:
			gml_handle_invalidate(handle)
	for handle in _gml_layer_element_handles_by_index.values():
		if handle is GMLHandle:
			gml_handle_invalidate(handle)
	_gml_layer_handles_by_index.clear()
	_gml_layer_handles_by_node_id.clear()
	_gml_layer_handles_by_name.clear()
	_gml_layer_element_handles_by_index.clear()
	_gml_layer_element_handles_by_node_id.clear()


static func _gml_layer_register_node(node):
	if not (node is Node):
		return gml_handle_invalid(GML_LAYER_HANDLE_KIND)
	var existing = _gml_layer_handle_for_node(node)
	if gml_handle_is_valid(existing):
		return existing
	var handle = gml_handle_register(GML_LAYER_HANDLE_KIND, node, _gml_layer_node_display_name(node))
	_gml_layer_store_handle(handle)
	node.set_meta("_gm2godot_layer_id", handle.index)
	return handle


static func _gml_layer_store_handle(handle):
	if not gml_handle_is_valid(handle):
		return
	var node = handle.reference
	_gml_layer_handles_by_index[handle.index] = handle
	if node is Object:
		_gml_layer_handles_by_node_id[node.get_instance_id()] = handle
	for name in _gml_layer_names_for_node(node):
		_gml_layer_handles_by_name[name] = handle


static func _gml_layer_resolve_handle(layer):
	_gml_layer_prune_invalid()
	if is_handle(layer):
		if layer.kind == GML_LAYER_HANDLE_KIND and gml_handle_is_valid(layer):
			return layer
		return gml_handle_invalid(GML_LAYER_HANDLE_KIND)
	if layer is Node:
		return _gml_layer_register_node(layer)
	if is_string(layer):
		var parsed = gml_handle_parse(layer)
		if is_handle(parsed) and parsed.kind == GML_LAYER_HANDLE_KIND and gml_handle_is_valid(parsed):
			return parsed
		var layer_name = str(layer)
		if _gml_layer_handles_by_name.has(layer_name):
			var named_handle = _gml_layer_handles_by_name[layer_name]
			if gml_handle_is_valid(named_handle):
				return named_handle
		var node = _gml_layer_find_node_by_name(layer_name)
		if node != null:
			return _gml_layer_register_node(node)
		return gml_handle_invalid(GML_LAYER_HANDLE_KIND)
	if is_numeric(layer):
		var handle = gml_handle_get(GML_LAYER_HANDLE_KIND, _to_int64_value(layer))
		if gml_handle_is_valid(handle):
			return handle
	return gml_handle_invalid(GML_LAYER_HANDLE_KIND)


static func _gml_layer_resolve_node(layer):
	var handle = _gml_layer_resolve_handle(layer)
	if gml_handle_is_valid(handle) and handle.reference is Node:
		return handle.reference
	return null


static func _gml_layer_all_handles():
	_gml_layer_prune_invalid()
	var handles = []
	for handle in _gml_layer_handles_by_index.values():
		if gml_handle_is_valid(handle):
			handles.append(handle)
	handles.sort_custom(_gml_layer_handle_order_less)
	return handles


static func _gml_layer_handle_order_less(left, right):
	var left_depth = _gml_layer_handle_depth(left)
	var right_depth = _gml_layer_handle_depth(right)
	if left_depth == right_depth:
		return _gml_layer_handle_name(left) < _gml_layer_handle_name(right)
	return left_depth < right_depth


static func _gml_layer_handle_depth(handle):
	if not gml_handle_is_valid(handle):
		return 0
	var node = handle.reference
	if node is Object and node.has_meta("gamemaker_layer_depth"):
		return int(node.get_meta("gamemaker_layer_depth"))
	if node is CanvasItem:
		return -int(node.z_index)
	return 0


static func _gml_layer_node_axis(node, axis):
	var key = "gamemaker_layer_" + str(axis)
	if node.has_meta(key):
		return _to_real(node.get_meta(key))
	if node is Node2D:
		return node.position.x if str(axis) == "x" else node.position.y
	return 0


static func _gml_layer_set_node_axis(node, axis, value):
	var key = "gamemaker_layer_" + str(axis)
	if node is Node2D:
		if str(axis) == "x":
			node.position.x = value
		else:
			node.position.y = value
	node.set_meta(key, value)


static func _gml_layer_node_speed(node, axis):
	var key = "gamemaker_layer_hspeed" if str(axis) == "h" else "gamemaker_layer_vspeed"
	if node.has_meta(key):
		return _to_real(node.get_meta(key))
	return 0


static func _gml_layer_element_type_for_asset_type(asset_type):
	var normalized = str(asset_type).to_lower()
	if normalized.find("sprite") >= 0:
		return "sprite"
	if normalized.find("sequence") >= 0:
		return "sequence"
	if normalized.find("particle") >= 0:
		return "particle_system"
	if normalized.find("oldtile") >= 0 or normalized.find("old_tile") >= 0:
		return "old_tilemap"
	if normalized.find("tilemap") >= 0 or normalized.find("tile_map") >= 0:
		return "tilemap"
	if normalized.ends_with("tile") or normalized.find("tilegraphic") >= 0:
		return "tile"
	return "undefined"


static func _gml_layer_handle_name(handle):
	if not gml_handle_is_valid(handle):
		return ""
	return _gml_layer_node_display_name(handle.reference)


static func _gml_layer_node_display_name(node):
	if node is Object and node.has_meta("gamemaker_layer_name"):
		return str(node.get_meta("gamemaker_layer_name"))
	if node is Object and node.has_meta("gamemaker_layer_node_name"):
		return str(node.get_meta("gamemaker_layer_node_name"))
	if node is Node:
		return str(node.name)
	return ""


static func _gml_layer_names_for_node(node):
	var names = []
	if node is Object and node.has_meta("gamemaker_layer_name"):
		names.append(str(node.get_meta("gamemaker_layer_name")))
	if node is Object and node.has_meta("gamemaker_layer_node_name"):
		names.append(str(node.get_meta("gamemaker_layer_node_name")))
	if node is Node:
		names.append(str(node.name))
	var unique_names = []
	for name in names:
		if str(name) != "" and not unique_names.has(str(name)):
			unique_names.append(str(name))
	return unique_names


static func _gml_layer_find_node_by_name(layer_name):
	var scene = _gml_layer_current_scene()
	if scene == null:
		return null
	for node in _gml_layer_tree_nodes(scene):
		if node == scene:
			continue
		if str(node.name) == str(layer_name):
			return node
		if node.has_meta("gamemaker_layer_name") and str(node.get_meta("gamemaker_layer_name")) == str(layer_name):
			return node
		if node.has_meta("gamemaker_layer_node_name") and str(node.get_meta("gamemaker_layer_node_name")) == str(layer_name):
			return node
	return null


static func _gml_layer_handle_for_node(node):
	if node is Object:
		var node_id = node.get_instance_id()
		if _gml_layer_handles_by_node_id.has(node_id):
			var handle = _gml_layer_handles_by_node_id[node_id]
			if gml_handle_is_valid(handle):
				return handle
	return gml_handle_invalid(GML_LAYER_HANDLE_KIND)


static func _gml_layer_unregister_handle(handle, invalidate = true):
	if not (handle is GMLHandle):
		return
	var handle_index = handle.index
	var node = handle.reference
	_gml_layer_handles_by_index.erase(handle_index)
	if node is Object:
		_gml_layer_handles_by_node_id.erase(node.get_instance_id())
	for name in _gml_layer_handles_by_name.keys():
		var named_handle = _gml_layer_handles_by_name[name]
		if named_handle is GMLHandle and named_handle.index == handle_index:
			_gml_layer_handles_by_name.erase(name)
	if invalidate:
		gml_handle_invalidate(handle)


static func _gml_layer_prune_invalid():
	for handle in _gml_layer_handles_by_index.values():
		if not gml_handle_is_valid(handle):
			_gml_layer_unregister_handle(handle, false)
	for handle in _gml_layer_element_handles_by_index.values():
		if not gml_handle_is_valid(handle):
			_gml_layer_element_unregister_handle(handle, false)


static func _gml_layer_node_has_metadata(node):
	return (
		node is Object
		and (
			node.has_meta("gamemaker_layer_name")
			or node.has_meta("gamemaker_layer_node_name")
			or node.has_meta("gamemaker_layer_depth")
		)
	)


static func _gml_layer_unique_name(requested_name):
	var base = str(requested_name)
	if base == "":
		base = "Layer_" + str(_gml_handle_next_indices.get(GML_LAYER_HANDLE_KIND, 0))
	base = base.replace("/", "_")
	var candidate = base
	var suffix = 2
	while _gml_layer_resolve_handle(candidate).valid:
		candidate = base + "_" + str(suffix)
		suffix += 1
	return candidate


static func _gml_layer_current_scene():
	var loop = Engine.get_main_loop()
	if loop is SceneTree and loop.current_scene is Node:
		return loop.current_scene
	return null


static func _gml_layer_tree_nodes(root_node):
	var nodes = []
	if root_node == null:
		return nodes
	var pending = [root_node]
	while not pending.is_empty():
		var node = pending.pop_front()
		nodes.append(node)
		for child in node.get_children():
			pending.append(child)
	return nodes


static func _gml_layer_element_register(node):
	if not (node is Node):
		return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)
	var existing = _gml_layer_element_handle_for_node(node)
	if gml_handle_is_valid(existing):
		return existing
	var handle = gml_handle_register(GML_LAYER_ELEMENT_HANDLE_KIND, node, _gml_layer_element_name(node))
	_gml_layer_element_handles_by_index[handle.index] = handle
	_gml_layer_element_handles_by_node_id[node.get_instance_id()] = handle
	return handle


static func _gml_layer_element_name(node):
	if node is Object and node.has_meta("gamemaker_background_visual"):
		return str(node.get_meta("gamemaker_layer_name", str(node.name)))
	if node is Object and node.has_meta("gamemaker_instance_name"):
		return str(node.get_meta("gamemaker_instance_name"))
	if node is Object and node.has_meta("gamemaker_asset_name"):
		return str(node.get_meta("gamemaker_asset_name"))
	if node is Node:
		return str(node.name)
	return ""


static func _gml_layer_element_resolve_node(element):
	if is_handle(element):
		if element.kind == GML_LAYER_ELEMENT_HANDLE_KIND and gml_handle_is_valid(element):
			return element.reference
		if element.kind == GML_INSTANCE_HANDLE_KIND and gml_handle_is_valid(element):
			return element.reference
	if element is Node:
		return element
	if is_numeric(element):
		var handle = gml_handle_get(GML_LAYER_ELEMENT_HANDLE_KIND, _to_int64_value(element))
		if gml_handle_is_valid(handle):
			return handle.reference
	return null


static func _gml_layer_element_handle_for_node(node):
	if node is Object:
		var node_id = node.get_instance_id()
		if _gml_layer_element_handles_by_node_id.has(node_id):
			var handle = _gml_layer_element_handles_by_node_id[node_id]
			if gml_handle_is_valid(handle):
				return handle
	return gml_handle_invalid(GML_LAYER_ELEMENT_HANDLE_KIND)


static func _gml_layer_element_unregister_handle(handle, invalidate = true):
	if not (handle is GMLHandle):
		return
	var handle_index = handle.index
	var node = handle.reference
	_gml_layer_element_handles_by_index.erase(handle_index)
	if node is Object:
		_gml_layer_element_handles_by_node_id.erase(node.get_instance_id())
	if invalidate:
		gml_handle_invalidate(handle)


static func _gml_tilemap_coords_in_bounds(node, coords):
	if not (node is TileMapLayer):
		return false
	var width = int(node.get_meta("gamemaker_tile_width", 0))
	var height = int(node.get_meta("gamemaker_tile_height", 0))
	return coords.x >= 0 and coords.y >= 0 and coords.x < width and coords.y < height


static func _gml_tilemap_transform_to_godot(tile_value):
	var mirror = (tile_value & GML_TILEMAP_MIRROR) != 0
	var flip = (tile_value & GML_TILEMAP_FLIP) != 0
	var rotate = (tile_value & GML_TILEMAP_ROTATE) != 0
	if not rotate:
		var unrotated = 0
		if mirror:
			unrotated |= GML_TILEMAP_GODOT_FLIP_H
		if flip:
			unrotated |= GML_TILEMAP_GODOT_FLIP_V
		return unrotated
	var rotated = GML_TILEMAP_GODOT_TRANSPOSE
	if not flip:
		rotated |= GML_TILEMAP_GODOT_FLIP_H
	if mirror:
		rotated |= GML_TILEMAP_GODOT_FLIP_V
	return rotated


static func _gml_tilemap_transform_from_godot(alternative_tile):
	var flip_h = (alternative_tile & GML_TILEMAP_GODOT_FLIP_H) != 0
	var flip_v = (alternative_tile & GML_TILEMAP_GODOT_FLIP_V) != 0
	var transpose = (alternative_tile & GML_TILEMAP_GODOT_TRANSPOSE) != 0
	if not transpose:
		var unrotated = 0
		if flip_h:
			unrotated |= GML_TILEMAP_MIRROR
		if flip_v:
			unrotated |= GML_TILEMAP_FLIP
		return unrotated
	var rotated = GML_TILEMAP_ROTATE
	if flip_v:
		rotated |= GML_TILEMAP_MIRROR
	if not flip_h:
		rotated |= GML_TILEMAP_FLIP
	return rotated


static func _gml_tilemap_atlas_layout(tile_set):
	if not (tile_set is TileSet) or tile_set.get_source_count() <= 0:
		return {}
	var cached_layout = tile_set.get_meta("_gm2godot_tilemap_atlas_layout", {})
	if (
		cached_layout is Dictionary
		and cached_layout.get("source") is TileSetAtlasSource
		and int(cached_layout.get("columns", 0)) > 0
	):
		return cached_layout
	var source_id = tile_set.get_source_id(0)
	var source = tile_set.get_source(source_id)
	if not (source is TileSetAtlasSource):
		return {}
	var columns = int(tile_set.get_meta("gamemaker_tileset_out_columns", 0))
	if columns <= 0:
		var grid_size = source.get_atlas_grid_size()
		if grid_size.x <= 0:
			return {}
		columns = grid_size.x
	var layout = {
		"source_id": source_id,
		"source": source,
		"columns": columns,
	}
	tile_set.set_meta("_gm2godot_tilemap_atlas_layout", layout)
	return layout


static func _gml_layer_node_is_background(node):
	return node is Object and node.has_meta("gamemaker_background_visual")


static func _gml_layer_background_resolve_node(background):
	var node = _gml_layer_element_resolve_node(background)
	if _gml_layer_node_is_background(node):
		return node
	return null


static func _gml_layer_background_color(color):
	if color is Color:
		return color
	var value = int(_to_real(color))
	return Color(
		float(value & 0xff) / 255.0,
		float((value >> 8) & 0xff) / 255.0,
		float((value >> 16) & 0xff) / 255.0,
		1.0
	)
