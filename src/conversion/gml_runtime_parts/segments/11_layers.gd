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


static func gml_layer_get_element_type(element):
	var node = _gml_layer_element_resolve_node(element)
	if node == null:
		return "undefined"
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
		if asset_type.findn("sprite") >= 0:
			return "sprite"
		return "asset"
	return "undefined"


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
