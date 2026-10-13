const GML_TILEMAP_EMPTY_SENTINEL = -2147483648
const GML_TILEMAP_INDEX_MASK = 0x0007ffff
const GML_TILEMAP_MIRROR = 0x10000000
const GML_TILEMAP_FLIP = 0x20000000
const GML_TILEMAP_ROTATE = 0x40000000
const GML_TILEMAP_GODOT_FLIP_H = 1 << 12
const GML_TILEMAP_GODOT_FLIP_V = 1 << 13
const GML_TILEMAP_GODOT_TRANSPOSE = 1 << 14
# A managed layer node holds the instances and particle systems GameMaker puts
# on its managed layer at one depth; the room root lists them by depth.
const GML_MANAGED_LAYER_DEPTH_META = &"_gm2godot_managed_layer_depth"
const GML_MANAGED_LAYERS_META = &"_gm2godot_managed_layers"


static func gml_layer_register_scene(scene, clear_existing = true):
	if clear_existing:
		_gml_layer_clear_registry()
		_gml_depth_room_reset()
	if not (scene is Node):
		return false
	for node in _gml_layer_tree_nodes(scene):
		if node == scene:
			continue
		if _gml_layer_node_has_metadata(node):
			_gml_layer_register_node(node)
	if clear_existing:
		_gml_depth_flush()
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
	var resolved_depth = gml_depth_truncate(depth)
	# GameMaker leaves a layer already at that depth where it is; at another
	# depth the layer goes behind the layers there (ChangeLayerDepth).
	if node.has_meta("gamemaker_layer_depth") and gml_depth_truncate(node.get_meta("gamemaker_layer_depth")) == resolved_depth:
		return true
	node.set_meta("gamemaker_layer_depth", resolved_depth)
	_gml_depth_track(node, resolved_depth)
	_gml_room_place_layer_node(node.get_parent(), node)
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
	var resolved_depth = gml_depth_truncate(depth)
	var name = _gml_layer_unique_name(str(layer_name))
	var node = Node2D.new()
	node.name = name
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
	_gml_room_add_layer_node(parent, node)
	return _gml_layer_register_node(node)


static func gml_layer_destroy(layer):
	var handle = _gml_layer_resolve_handle(layer)
	if not gml_handle_is_valid(handle):
		return false
	var node = handle.reference
	if not (node is Node):
		_gml_layer_unregister_handle(handle)
		return false
	# The instances on the layer are destroyed, as with instance_destroy (the
	# runner's RemoveLayer calls RemoveInstanceElement for each one).
	_gml_instances_destroy_under(node)
	for child in _gml_layer_tree_nodes(node):
		_gml_depth_forget(child.get_instance_id())
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
	_gml_instance_move_to_parent(instance_node, layer_node, true)
	# The instance now has the layer's depth instead of one assigned earlier.
	if instance_node.has_meta(GML_EXPLICIT_DEPTH_META):
		instance_node.remove_meta(GML_EXPLICIT_DEPTH_META)
		_gml_draw_pending_depths.erase(instance_node.get_instance_id())
		_gml_depth_forget(instance_node.get_instance_id())
		if instance_node is CanvasItem:
			instance_node.z_as_relative = true
			instance_node.z_index = 0
	return true


# --- Layer order at one depth and managed layers --------------------------------
#
# GameMaker keeps a room's layers in one list sorted by depth. A layer it adds
# goes after every layer of the same depth (yyOList.Add, used by layer_create,
# AddDynamicLayer and ChangeLayerDepth), and DrawRoomLayers and
# ExecuteDrawEvent (yyRoom.js) walk that list from its end, so of the layers
# that share a depth the one added last draws first, behind the others. Godot
# draws canvas items that share a z_index in tree order, so a layer node added
# at a depth goes before every room child at that depth.
#
# An instance or particle system that leaves its layer for a depth goes to the
# room's managed layer at that depth (LayerManager.AddInstance and
# AddNewElementAtDepth: GetLayerWithDepth looks at managed layers only, then
# AddDynamicLayer). GameMaker keeps a managed layer, even empty, until the room
# ends, so a later move to that depth joins it where it is. Here a managed layer
# is a Node2D under the room root; what it holds draws at its depth's z_index.

# The room's managed layer at a truncated depth, added when there is none.
static func _gml_managed_layer(room_root, depth):
	var layers = room_root.get_meta(GML_MANAGED_LAYERS_META, {})
	var layer = layers.get(depth, null)
	if is_instance_valid(layer):
		return layer
	layer = Node2D.new()
	# Its depth can change (ChangeLayerDepth), so its name does not give one.
	layer.name = "GMManagedLayer"
	layer.set_meta(GML_MANAGED_LAYER_DEPTH_META, depth)
	layers[depth] = layer
	room_root.set_meta(GML_MANAGED_LAYERS_META, layers)
	_gml_room_add_layer_node(room_root, layer)
	return layer


# Puts an instance or particle system on the room's managed layer at a
# truncated depth, after what is already there. With alone_moves_layer, an
# instance alone on its managed layer takes that layer to the new depth
# instead (yyRoom.js ProcessDepthList2): ChangeLayerDepth puts the layer behind
# every layer of that depth and merges the managed layer there into it.
static func _gml_managed_layer_add(room_root, node, depth, alone_moves_layer = false):
	var current = node.get_parent()
	if alone_moves_layer and current != null and current.get_parent() == room_root and current.has_meta(GML_MANAGED_LAYER_DEPTH_META) and _gml_managed_layer_holds_only(current, node):
		_gml_managed_layer_set_depth(room_root, current, depth)
		return
	var layer = _gml_managed_layer(room_root, depth)
	if current != layer:
		_gml_instance_move_to_parent(node, layer)


static func _gml_managed_layer_holds_only(layer, node):
	for child in layer.get_children():
		if child != node and not child.is_queued_for_deletion():
			return false
	return true


static func _gml_managed_layer_set_depth(room_root, layer, depth):
	var layers = room_root.get_meta(GML_MANAGED_LAYERS_META, {})
	var old_depth = int(layer.get_meta(GML_MANAGED_LAYER_DEPTH_META))
	if old_depth == depth:
		return
	if layers.get(old_depth, null) == layer:
		layers.erase(old_depth)
	var merged = layers.get(depth, null)
	layer.set_meta(GML_MANAGED_LAYER_DEPTH_META, depth)
	layers[depth] = layer
	room_root.set_meta(GML_MANAGED_LAYERS_META, layers)
	_gml_room_place_layer_node(room_root, layer)
	if is_instance_valid(merged) and merged != layer:
		# The merged layer's nodes follow this layer's own, in their order.
		for child in merged.get_children():
			_gml_instance_move_to_parent(child, layer)
		if merged.get_child_count() == 0:
			merged.queue_free()


# Adds a layer node to a room behind every room child at its depth. A room
# still adding its own children takes it at the end of the frame.
static func _gml_room_add_layer_node(room_root, node):
	if room_root.is_node_ready():
		room_root.add_child(node, true)
		_gml_room_place_layer_node(room_root, node)
		return
	room_root.add_child.call_deferred(node, true)
	(func(): _gml_room_place_layer_node(room_root, node, false)).call_deferred()


# Moves a room's layer node before every other room child at its depth; a
# room still adding its own children is reordered at the end of the frame.
# Nested layers stay in their parent layer.
static func _gml_room_place_layer_node(room_root, node, may_wait = true):
	if not is_instance_valid(room_root) or not is_instance_valid(node) or node.get_parent() != room_root:
		return
	if room_root.has_meta(&"gamemaker_layer_depth"):
		return
	if not room_root.is_node_ready():
		if may_wait:
			(func(): _gml_room_place_layer_node(room_root, node, false)).call_deferred()
		return
	var depth = _gml_room_layer_node_depth(node)
	if depth == null:
		return
	for child in room_root.get_children():
		if child == node:
			return
		if _gml_room_child_has_depth(child, depth):
			room_root.move_child(node, child.get_index())
			return


static func _gml_room_layer_node_depth(node):
	if node.has_meta(GML_MANAGED_LAYER_DEPTH_META):
		return int(node.get_meta(GML_MANAGED_LAYER_DEPTH_META))
	if node.has_meta(&"gamemaker_layer_depth"):
		return gml_depth_truncate(node.get_meta(&"gamemaker_layer_depth"))
	return null


# Whether a room child is, or nests, a layer at the depth.
static func _gml_room_child_has_depth(node, depth):
	var node_depth = _gml_room_layer_node_depth(node)
	if node_depth == null:
		return false
	if node_depth == depth:
		return true
	if node.has_meta(GML_MANAGED_LAYER_DEPTH_META):
		return false
	for child in node.get_children():
		if child.has_meta(&"gamemaker_layer_depth") and _gml_room_child_has_depth(child, depth):
			return true
	return false


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
	node.position = Vector2(_to_real(x), _to_real(y)) + _gml_layer_node_offset(layer_node)
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
	# Tile N is cell N of the tileset sprite's own grid; tile 0 is the empty
	# top-left cell (tilemap_set rejects tile_index >= the tileset's tile count).
	var atlas_coords = Vector2i(
		tile_index % int(layout["columns"]),
		int(floor(float(tile_index) / float(layout["columns"])))
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
	var tile_value = atlas_coords.y * int(layout["columns"]) + atlas_coords.x
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
	var old_layer = element_node.get_parent()
	if old_layer == layer_node:
		return true
	# The element keeps its own position and is drawn at the new layer's
	# offset instead of the old one.
	var shift = _gml_layer_element_offset(layer_node, element_node) - _gml_layer_element_offset(old_layer, element_node)
	if old_layer != null:
		_gml_instance_reparent(element_node, layer_node)
	else:
		layer_node.add_child(element_node)
	if element_node is Node2D:
		element_node.position += shift
	_gml_layer_element_register(element_node)
	return true


static func gml_layer_get_element_type(element):
	var node = _gml_layer_element_resolve_node(element)
	if node == null:
		return "undefined"
	return _gml_layer_node_element_type(node)


static func _gml_layer_node_element_type(node):
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
	if node is CanvasItem and node.has_meta("gamemaker_layer_depth"):
		_gml_depth_track(node, gml_depth_truncate(node.get_meta("gamemaker_layer_depth")))
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
	var offset = _gml_layer_node_offset(node)
	if str(axis) == "x":
		offset.x = value
	else:
		offset.y = value
	_gml_layer_set_node_offset(node, offset)


static func _gml_layer_node_offset(node):
	return Vector2(_gml_layer_node_axis(node, "x"), _gml_layer_node_axis(node, "y"))


# GameMaker draws a layer's backgrounds, sprites, tilemaps and sequences at
# their own position plus the layer offset (yyRoom.js DrawLayer*Element add
# m_xoffset/m_yoffset), but instances at their own x/y
# (DrawLayerInstanceElement) and particle systems at their own position
# (yyParticle.js ParticleSystem_Update). A layer node therefore stays at the
# room origin, so whatever joins it later keeps its position, and each
# element that follows the offset is placed at its own position plus the
# offset.
const GML_LAYER_OFFSET_ELEMENT_TYPES = ["background", "sprite", "tilemap", "sequence"]


static func _gml_layer_set_node_offset(node, offset):
	var delta = offset - _gml_layer_node_offset(node)
	node.set_meta("gamemaker_layer_x", offset.x)
	node.set_meta("gamemaker_layer_y", offset.y)
	if delta == Vector2.ZERO:
		return
	for child in node.get_children():
		if _gml_layer_element_follows_offset(child):
			child.position += delta


static func _gml_layer_element_follows_offset(element):
	# Nested layers have offsets of their own.
	return (
		element is Node2D
		and not _gml_layer_node_has_metadata(element)
		and GML_LAYER_OFFSET_ELEMENT_TYPES.has(_gml_layer_node_element_type(element))
	)


# How far `element` on `layer_node` is drawn from its own position.
static func _gml_layer_element_offset(layer_node, element):
	if _gml_layer_node_has_metadata(layer_node) and _gml_layer_element_follows_offset(element):
		return _gml_layer_node_offset(layer_node)
	return Vector2.ZERO


static func _gml_layer_step_scroll():
	# GameMaker's LayerManager.UpdateLayers (Function_Layers.js), run each
	# step after the instances' images update and before Begin Step: every
	# layer's offset moves by its speed (layer_hspeed/layer_vspeed, which
	# start at the Room Editor's speed of a background layer).
	for handle in _gml_layer_handles_by_index.values():
		if not gml_handle_is_valid(handle) or not (handle.reference is Node):
			continue
		var node = handle.reference
		var speed = Vector2(_gml_layer_node_speed(node, "h"), _gml_layer_node_speed(node, "v"))
		if speed != Vector2.ZERO:
			_gml_layer_set_node_offset(node, _gml_layer_node_offset(node) + speed)
	return null


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
	# GameMaker numbers tiles by cell of the tileset sprite's own grid, which is
	# the converted atlas's grid. The tileset's out_columns describe the compiled
	# texture page tileset_get_info reports, not the numbering.
	var columns = int(source.get_atlas_grid_size().x)
	if columns <= 0:
		columns = int(tile_set.get_meta("gamemaker_tileset_source_columns", 0))
	if columns <= 0:
		return {}
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


# --- Drawing background layer elements -----------------------------------
#
# GameMaker draws every background element each frame over the part of the
# room being drawn (yyRoom.js DrawLayerBackgroundElement). A colour fills
# that area whatever the layer offset. A sprite is drawn from its top-left
# corner (backgrounds ignore the sprite origin) at the layer offset, scaled
# by the element's xscale/yscale, or by room size / sprite size when it is
# stretched, and along each tiled axis it repeats every scaled sprite width
# or height across the area (yyWebGL.js WebGL_TextureDrawTiled_RELEASE). A
# converted colour element is a ColorRect kept over the visible area; a
# sprite element draws the current frame of its hidden sprite scene through
# the region of a repeating Sprite2D (one quad, however many tiles).

const GML_BACKGROUND_PARTS_META = "_gm2godot_background_parts"

static var _gml_background_scene_id = 0
static var _gml_background_nodes = []


# The background elements of a room scene, found once per scene.
static func _gml_layer_background_nodes(scene):
	var scene_id = scene.get_instance_id()
	if scene_id == _gml_background_scene_id:
		var valid = true
		for node in _gml_background_nodes:
			if not is_instance_valid(node):
				valid = false
				break
		if valid:
			return _gml_background_nodes
	_gml_background_scene_id = scene_id
	_gml_background_nodes = []
	for node in _gml_layer_tree_nodes(scene):
		if node != scene and node is CanvasItem and _gml_layer_node_is_background(node):
			_gml_background_nodes.append(node)
	return _gml_background_nodes


static func _gml_layer_background_draw(node):
	if not node.is_visible_in_tree():
		return
	if node is Control:
		_gml_layer_background_fill(node)
		return
	var parts = _gml_layer_background_parts(node)
	if not parts.is_empty():
		_gml_layer_background_tile(node, parts)


# The viewport's visible area in `item`'s local coordinates (the bounding box
# when the view is rotated).
static func _gml_layer_background_visible_region(item):
	var viewport = item.get_viewport()
	if viewport == null:
		return Rect2()
	var transform = item.get_global_transform_with_canvas()
	if absf(transform.determinant()) <= 0.0000001:
		return Rect2()
	var rect = viewport.get_visible_rect()
	var to_local = transform.affine_inverse()
	var region = Rect2(to_local * rect.position, Vector2.ZERO)
	region = region.expand(to_local * Vector2(rect.end.x, rect.position.y))
	region = region.expand(to_local * rect.end)
	return region.expand(to_local * Vector2(rect.position.x, rect.end.y))


static func _gml_layer_background_fill(rect_node):
	var region = _gml_layer_background_visible_region(rect_node)
	if not region.has_area():
		return
	var start = (rect_node.position + region.position).floor()
	var size = (rect_node.position + region.end).ceil() - start
	if rect_node.position != start:
		rect_node.position = start
	if rect_node.size != size:
		rect_node.size = size


# [tiles Sprite2D, frame source (Sprite2D or AnimatedSprite2D), sprite scene].
static func _gml_layer_background_parts(node):
	if node.has_meta(GML_BACKGROUND_PARTS_META):
		var cached = node.get_meta(GML_BACKGROUND_PARTS_META)
		if is_instance_valid(cached[0]) and is_instance_valid(cached[1]) and is_instance_valid(cached[2]):
			return cached
	var tiles = null
	var scene = null
	for child in node.get_children():
		if child is Sprite2D and child.has_meta("gamemaker_background_tiles"):
			tiles = child
		elif child.has_meta("gamemaker_background_frames"):
			scene = child
	if tiles == null or scene == null:
		return []
	var source = scene if (scene is Sprite2D or scene is AnimatedSprite2D) else scene.find_child("AnimatedSprite2D", true, false)
	if source == null:
		source = scene.find_child("Sprite2D", true, false)
	if source == null:
		return []
	var parts = [tiles, source, scene]
	node.set_meta(GML_BACKGROUND_PARTS_META, parts)
	return parts


static func _gml_layer_background_tile(node, parts):
	var tiles = parts[0]
	var texture = _gml_layer_background_frame_texture(parts[1])
	var size = Vector2.ZERO
	if texture != null:
		var scene = parts[2]
		size = Vector2(
			_to_real(scene.get_meta("gamemaker_width", texture.get_width())),
			_to_real(scene.get_meta("gamemaker_height", texture.get_height()))
		)
	var scale = _gml_layer_background_scale(node, size)
	var region = _gml_layer_background_visible_region(node)
	var across = _gml_layer_background_axis(bool(node.get_meta("gamemaker_background_htiled", false)), size.x, scale.x, region.position.x, region.end.x)
	var down = _gml_layer_background_axis(bool(node.get_meta("gamemaker_background_vtiled", false)), size.y, scale.y, region.position.y, region.end.y)
	if texture == null or across.is_empty() or down.is_empty() or not region.has_area():
		tiles.visible = false
		return
	if tiles.texture != texture:
		tiles.texture = texture
	var source = Rect2(Vector2.ZERO, size * Vector2(across[1], down[1]))
	if tiles.region_rect != source:
		tiles.region_rect = source
	var position = Vector2(across[0], down[0])
	if tiles.position != position:
		tiles.position = position
	if tiles.scale != scale:
		tiles.scale = scale
	tiles.visible = true


static func _gml_layer_background_frame_texture(source):
	if source is AnimatedSprite2D:
		var frames = source.sprite_frames
		if frames == null or not frames.has_animation(source.animation):
			return null
		if frames.get_frame_count(source.animation) <= 0:
			return null
		return frames.get_frame_texture(source.animation, source.frame)
	if source is Sprite2D:
		return source.texture
	return null


static func _gml_layer_background_scale(node, size):
	if bool(node.get_meta("gamemaker_background_stretch", false)) and size.x > 0.0 and size.y > 0.0:
		var room_size = Vector2(
			_to_real(_gml_builtin_globals.get("room_width", 0)),
			_to_real(_gml_builtin_globals.get("room_height", 0))
		)
		if room_size.x > 0.0 and room_size.y > 0.0:
			return room_size / size
	return Vector2(
		_to_real(node.get_meta("gamemaker_background_xscale", 1.0)),
		_to_real(node.get_meta("gamemaker_background_yscale", 1.0))
	)


# [position, copies] of the strip along one axis: the sprite once from the
# element's origin, or, when tiled, the copies on the grid anchored at the
# origin that cover [low, high]. A negative scale mirrors each copy towards
# lower coordinates, so the strip then starts from its far end.
static func _gml_layer_background_axis(tiled, size, scale, low, high):
	var step = absf(size * scale)
	if step <= 0.0:
		return []
	if not tiled:
		return [0.0, 1]
	var start = floor(low / step) * step
	var copies = maxi(int(ceil((high - start) / step)), 1)
	return [start + copies * step if scale < 0.0 else start, copies]


# --- Sprite elements on asset layers -------------------------------------

static func _gml_layer_is_sprite_element(node):
	return node.has_meta("gamemaker_layer_element_type") and str(node.get_meta("gamemaker_layer_element_type")) == "sprite"


static func _gml_layer_sprite_element_start(node):
	# A sprite placed in the Room Editor starts at its initial frame
	# (headPosition) and plays at its animation speed times the sprite's
	# (Function_Layers.js: NewSprite.m_imageIndex = sImageIndex,
	# m_imageSpeed = sImageSpeed). The head wraps into the sprite's frames
	# like a looping sprite sequence (yySequence.js HandleSequenceWrapping),
	# so -1 is the last frame.
	var visual = node.get_node_or_null("AnimatedSprite2D")
	if not (visual is AnimatedSprite2D) or visual.sprite_frames == null:
		return
	var count = visual.sprite_frames.get_frame_count(visual.animation)
	if count <= 0:
		return
	var head = _to_real(node.get_meta("gamemaker_asset_head_position", 0))
	visual.frame = posmod(int(floor(head)), count)
	visual.speed_scale = _to_real(node.get_meta("gamemaker_asset_animation_speed", 1))
