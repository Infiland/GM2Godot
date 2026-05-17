const GML_FLEXPANEL_NODE_MARKER = "__gm2godot_flexpanel_node"


static func gml_flexpanel_unit():
	return gml_struct({"point": "point", "percent": "percent", "auto": "auto"})


static func gml_flexpanel_direction():
	return gml_struct({"inherit": "inherit", "LTR": "ltr", "RTL": "rtl"})


static func gml_flexpanel_flex_direction():
	return gml_struct({
		"column": "column",
		"row": "row",
		"column_reverse": "column-reverse",
		"row_reverse": "row-reverse"
	})


static func gml_flexpanel_justify():
	return gml_struct({
		"start": "flex-start",
		"flex_start": "flex-start",
		"flex_end": "flex-end",
		"center": "center",
		"space_between": "space-between",
		"space_around": "space-around",
		"space_evenly": "space-evenly"
	})


static func gml_flexpanel_align():
	return gml_struct({
		"auto": "auto",
		"flex_start": "flex-start",
		"flex_end": "flex-end",
		"center": "center",
		"stretch": "stretch",
		"baseline": "baseline"
	})


static func gml_flexpanel_edge():
	return gml_struct({
		"all_edges": "all",
		"left": "left",
		"right": "right",
		"top": "top",
		"bottom": "bottom",
		"horizontal": "horizontal",
		"vertical": "vertical",
		"start": "left",
		"end": "right"
	})


static func gml_flexpanel_gutter():
	return gml_struct({"all_gutters": "all", "row": "row", "column": "column"})


static func gml_flexpanel_position_type():
	return gml_struct({"relative": "relative", "absolute": "absolute", "static": "static"})


static func gml_flexpanel_wrap():
	return gml_struct({"no_wrap": "no-wrap", "wrap": "wrap", "reverse": "wrap-reverse"})


static func gml_flexpanel_display():
	return gml_struct({"flex": "flex", "none": "none"})


static func gml_flexpanel_create_node(struct_or_json = null):
	var config = _gml_flexpanel_config(struct_or_json)
	if _gml_flexpanel_is_node(config):
		return config
	var node = config if typeof(config) == TYPE_DICTIONARY else {}
	_gml_flexpanel_initialize_node(node)
	_gml_flexpanel_apply_config(node, config)
	return node


static func gml_flexpanel_delete_node(node):
	if not _gml_flexpanel_is_node(node):
		return false
	var parent = node["parent"]
	if _gml_flexpanel_is_node(parent):
		gml_flexpanel_node_remove_child(parent, node)
	for child in node["children"]:
		if _gml_flexpanel_is_node(child):
			child["parent"] = null
	node["children"] = []
	node["deleted"] = true
	return true


static func gml_flexpanel_node_insert_child(node, child, index):
	if not _gml_flexpanel_is_node(node) or not _gml_flexpanel_is_node(child):
		return false
	var children = node["children"]
	var old_parent = child["parent"]
	if _gml_flexpanel_is_node(old_parent):
		gml_flexpanel_node_remove_child(old_parent, child)
	var insert_index = clampi(int(_to_real(index)), 0, children.size())
	children.insert(insert_index, child)
	child["parent"] = node
	return true


static func gml_flexpanel_node_remove_child(node, child_or_index):
	if not _gml_flexpanel_is_node(node):
		return false
	var children = node["children"]
	var index = -1
	if _gml_flexpanel_is_node(child_or_index):
		index = children.find(child_or_index)
	elif is_numeric(child_or_index):
		index = int(_to_real(child_or_index))
	if index < 0 or index >= children.size():
		return false
	var child = children[index]
	children.remove_at(index)
	if _gml_flexpanel_is_node(child):
		child["parent"] = null
	return true


static func gml_flexpanel_node_remove_all_children(node):
	if not _gml_flexpanel_is_node(node):
		return false
	for child in node["children"]:
		if _gml_flexpanel_is_node(child):
			child["parent"] = null
	node["children"] = []
	return true


static func gml_flexpanel_calculate_layout(root, width, height, direction, dirty = true):
	if not _gml_flexpanel_is_node(root):
		return false
	var root_width = _gml_flexpanel_resolve_size(root, "width", width, width)
	var root_height = _gml_flexpanel_resolve_size(root, "height", height, height)
	var left = _gml_flexpanel_resolve_size(root, "left", root_width, 0)
	var top = _gml_flexpanel_resolve_size(root, "top", root_height, 0)
	_gml_flexpanel_layout_node(root, left, top, root_width, root_height, left, top, _gml_flexpanel_direction_value(direction), root_width, root_height)
	return null


static func gml_flexpanel_node_set_name(node, name):
	if not _gml_flexpanel_is_node(node):
		return false
	node["name"] = str(name)
	return null


static func gml_flexpanel_node_layout_get_position(node, relative = true):
	if not _gml_flexpanel_is_node(node):
		return _gml_flexpanel_empty_layout()
	var layout = node["layout"]
	var left = float(layout["left"]) if gml_bool(relative) else float(layout["absolute_left"])
	var top = float(layout["top"]) if gml_bool(relative) else float(layout["absolute_top"])
	return gml_struct({
		"left": left,
		"top": top,
		"width": float(layout["width"]),
		"height": float(layout["height"]),
		"right": float(layout["right"]),
		"bottom": float(layout["bottom"]),
		"hadOverflow": bool(layout["hadOverflow"]),
		"direction": str(layout["direction"]),
		"paddingLeft": float(layout["paddingLeft"]),
		"paddingRight": float(layout["paddingRight"]),
		"paddingTop": float(layout["paddingTop"]),
		"paddingBottom": float(layout["paddingBottom"]),
		"marginLeft": float(layout["marginLeft"]),
		"marginRight": float(layout["marginRight"]),
		"marginTop": float(layout["marginTop"]),
		"marginBottom": float(layout["marginBottom"])
	})


static func gml_flexpanel_node_get_num_children(node):
	return node["children"].size() if _gml_flexpanel_is_node(node) else 0


static func gml_flexpanel_node_get_child(node, index):
	if not _gml_flexpanel_is_node(node):
		return gml_undefined()
	var resolved_index = int(_to_real(index))
	if resolved_index < 0 or resolved_index >= node["children"].size():
		return gml_undefined()
	return node["children"][resolved_index]


static func gml_flexpanel_node_get_child_hash(node, index):
	var child = gml_flexpanel_node_get_child(node, index)
	return hash(child) if _gml_flexpanel_is_node(child) else 0


static func gml_flexpanel_node_get_parent(node):
	return node["parent"] if _gml_flexpanel_is_node(node) and _gml_flexpanel_is_node(node["parent"]) else gml_undefined()


static func gml_flexpanel_node_get_name(node):
	return str(node["name"]) if _gml_flexpanel_is_node(node) else ""


static func gml_flexpanel_node_get_data(node):
	return node["data"] if _gml_flexpanel_is_node(node) else gml_struct({})


static func gml_flexpanel_node_get_struct(node):
	return node if _gml_flexpanel_is_node(node) else gml_undefined()


static func gml_flexpanel_node_set_measure_function(node, callback):
	return _gml_flexpanel_unsupported_feature("flexpanel_node_set_measure_function", "Custom measure callbacks require a full Yoga-compatible layout pass.")


static func gml_flexpanel_node_get_measure_function(node):
	return gml_undefined()


static func gml_flexpanel_node_style_set_width(node, width, unit):
	return _gml_flexpanel_set_unit_style(node, "width", width, unit)


static func gml_flexpanel_node_style_get_width(node):
	return _gml_flexpanel_get_unit_style(node, "width")


static func gml_flexpanel_node_style_set_height(node, height, unit):
	return _gml_flexpanel_set_unit_style(node, "height", height, unit)


static func gml_flexpanel_node_style_get_height(node):
	return _gml_flexpanel_get_unit_style(node, "height")


static func gml_flexpanel_node_style_set_min_width(node, width, unit):
	return _gml_flexpanel_set_unit_style(node, "minWidth", width, unit)


static func gml_flexpanel_node_style_get_min_width(node):
	return _gml_flexpanel_get_unit_style(node, "minWidth")


static func gml_flexpanel_node_style_set_max_width(node, width, unit):
	return _gml_flexpanel_set_unit_style(node, "maxWidth", width, unit)


static func gml_flexpanel_node_style_get_max_width(node):
	return _gml_flexpanel_get_unit_style(node, "maxWidth")


static func gml_flexpanel_node_style_set_min_height(node, height, unit):
	return _gml_flexpanel_set_unit_style(node, "minHeight", height, unit)


static func gml_flexpanel_node_style_get_min_height(node):
	return _gml_flexpanel_get_unit_style(node, "minHeight")


static func gml_flexpanel_node_style_set_max_height(node, height, unit):
	return _gml_flexpanel_set_unit_style(node, "maxHeight", height, unit)


static func gml_flexpanel_node_style_get_max_height(node):
	return _gml_flexpanel_get_unit_style(node, "maxHeight")


static func gml_flexpanel_node_style_set_aspect_ratio(node, ratio):
	return _gml_flexpanel_set_style(node, "aspectRatio", float(_to_real(ratio)))


static func gml_flexpanel_node_style_get_aspect_ratio(node):
	return float(_gml_flexpanel_get_style(node, "aspectRatio", 0.0))


static func gml_flexpanel_node_style_set_position(node, edge, value, unit):
	if not _gml_flexpanel_is_node(node):
		return false
	var unit_value = _gml_flexpanel_unit_value(value, unit)
	for key in _gml_flexpanel_position_style_keys(edge):
		node["style"][key] = unit_value
	return null


static func gml_flexpanel_node_style_get_position(node, edge):
	if not _gml_flexpanel_is_node(node):
		return _gml_flexpanel_unit_value(0)
	var keys = _gml_flexpanel_position_style_keys(edge)
	if keys.is_empty():
		return _gml_flexpanel_unit_value(0)
	return node["style"].get(keys[0], _gml_flexpanel_unit_value(0))


static func gml_flexpanel_node_style_set_position_type(node, position_type):
	return _gml_flexpanel_set_style(node, "positionType", _gml_flexpanel_keyword(position_type))


static func gml_flexpanel_node_style_get_position_type(node):
	return _gml_flexpanel_get_style(node, "positionType", "relative")


static func gml_flexpanel_node_style_set_flex_direction(node, flex_direction):
	return _gml_flexpanel_set_style(node, "flexDirection", _gml_flexpanel_direction_name(flex_direction))


static func gml_flexpanel_node_style_get_flex_direction(node):
	return _gml_flexpanel_get_style(node, "flexDirection", "column")


static func gml_flexpanel_node_style_set_justify_content(node, justify):
	return _gml_flexpanel_set_style(node, "justifyContent", _gml_flexpanel_keyword(justify))


static func gml_flexpanel_node_style_get_justify_content(node):
	return _gml_flexpanel_get_style(node, "justifyContent", "flex-start")


static func gml_flexpanel_node_style_set_align_items(node, align):
	return _gml_flexpanel_set_style(node, "alignItems", _gml_flexpanel_keyword(align))


static func gml_flexpanel_node_style_get_align_items(node):
	return _gml_flexpanel_get_style(node, "alignItems", "stretch")


static func gml_flexpanel_node_style_set_align_self(node, align):
	return _gml_flexpanel_set_style(node, "alignSelf", _gml_flexpanel_keyword(align))


static func gml_flexpanel_node_style_get_align_self(node):
	return _gml_flexpanel_get_style(node, "alignSelf", "auto")


static func gml_flexpanel_node_style_set_align_content(node, align):
	var value = _gml_flexpanel_keyword(align)
	if value != "flex-start":
		return _gml_flexpanel_unsupported_feature("flexpanel_node_style_set_align_content", "alignContent only affects wrapped flex lines, and wrapping is not implemented.")
	return _gml_flexpanel_set_style(node, "alignContent", value)


static func gml_flexpanel_node_style_get_align_content(node):
	return _gml_flexpanel_get_style(node, "alignContent", "flex-start")


static func gml_flexpanel_node_style_set_display(node, display):
	return _gml_flexpanel_set_style(node, "display", _gml_flexpanel_keyword(display))


static func gml_flexpanel_node_style_get_display(node):
	return _gml_flexpanel_get_style(node, "display", "flex")


static func gml_flexpanel_node_style_set_flex(node, flex):
	return _gml_flexpanel_set_style(node, "flex", float(_to_real(flex)))


static func gml_flexpanel_node_style_get_flex(node):
	return float(_gml_flexpanel_get_style(node, "flex", 0.0))


static func gml_flexpanel_node_style_set_flex_grow(node, grow):
	return _gml_flexpanel_set_style(node, "flexGrow", float(_to_real(grow)))


static func gml_flexpanel_node_style_get_flex_grow(node):
	return float(_gml_flexpanel_get_style(node, "flexGrow", 0.0))


static func gml_flexpanel_node_style_set_flex_shrink(node, shrink):
	return _gml_flexpanel_set_style(node, "flexShrink", float(_to_real(shrink)))


static func gml_flexpanel_node_style_get_flex_shrink(node):
	return float(_gml_flexpanel_get_style(node, "flexShrink", 1.0))


static func gml_flexpanel_node_style_set_flex_basis(node, value, unit):
	return _gml_flexpanel_set_unit_style(node, "flexBasis", value, unit)


static func gml_flexpanel_node_style_get_flex_basis(node):
	return _gml_flexpanel_get_unit_style(node, "flexBasis")


static func gml_flexpanel_node_style_set_flex_wrap(node, wrap):
	var value = _gml_flexpanel_keyword(wrap)
	if value != "no-wrap":
		return _gml_flexpanel_unsupported_feature("flexpanel_node_style_set_flex_wrap", "Wrapped and reverse-wrapped multi-line layouts require the full Yoga solver.")
	return _gml_flexpanel_set_style(node, "flexWrap", value)


static func gml_flexpanel_node_style_get_flex_wrap(node):
	return _gml_flexpanel_get_style(node, "flexWrap", "no-wrap")


static func gml_flexpanel_node_style_set_gap(node, gutter, size):
	if not _gml_flexpanel_is_node(node):
		return false
	var gutter_name = _gml_flexpanel_keyword(gutter)
	var size_value = float(_to_real(size))
	if gutter_name == "row" or gutter_name == "all":
		node["style"]["gapRow"] = size_value
	if gutter_name == "column" or gutter_name == "all":
		node["style"]["gapColumn"] = size_value
	return null


static func gml_flexpanel_node_style_get_gap(node, gutter):
	if not _gml_flexpanel_is_node(node):
		return 0.0
	var gutter_name = _gml_flexpanel_keyword(gutter)
	if gutter_name == "column":
		return float(_gml_flexpanel_get_style(node, "gapColumn", 0.0))
	return float(_gml_flexpanel_get_style(node, "gapRow", 0.0))


static func gml_flexpanel_node_style_set_padding(node, edge, size, unit = "point"):
	return _gml_flexpanel_set_edge_style(node, "padding", edge, size, unit)


static func gml_flexpanel_node_style_get_padding(node, edge):
	return _gml_flexpanel_get_edge_style(node, "padding", edge)


static func gml_flexpanel_node_style_set_border(node, edge, size):
	return _gml_flexpanel_set_edge_style(node, "border", edge, size, "point")


static func gml_flexpanel_node_style_get_border(node, edge):
	return _gml_flexpanel_get_edge_style(node, "border", edge)


static func gml_flexpanel_node_style_set_margin(node, edge, size, unit = "point"):
	return _gml_flexpanel_set_edge_style(node, "margin", edge, size, unit)


static func gml_flexpanel_node_style_get_margin(node, edge):
	return _gml_flexpanel_get_edge_style(node, "margin", edge)


static func gml_flexpanel_node_style_set_direction(node, direction):
	return _gml_flexpanel_set_style(node, "direction", _gml_flexpanel_direction_value(direction))


static func gml_flexpanel_node_style_get_direction(node):
	return _gml_flexpanel_get_style(node, "direction", "inherit")


static func _gml_flexpanel_config(value):
	if is_string(value):
		var decoded = gml_json_decode(value)
		return {} if is_undefined(decoded) else decoded
	if typeof(value) == TYPE_DICTIONARY:
		return value
	return {}


static func _gml_flexpanel_initialize_node(node):
	if node.has(GML_FLEXPANEL_NODE_MARKER):
		return
	node[GML_FLEXPANEL_NODE_MARKER] = true
	node["style"] = {}
	node["children"] = []
	node["parent"] = null
	node["name"] = str(node.get("name", ""))
	node["data"] = node.get("data", gml_struct({}))
	node["layout"] = _gml_flexpanel_empty_layout()
	node["deleted"] = false


static func _gml_flexpanel_apply_config(node, config):
	if typeof(config) != TYPE_DICTIONARY:
		return
	for key in config.keys():
		if key in [GML_FLEXPANEL_NODE_MARKER, "style", "children", "parent", "layout", "deleted"]:
			continue
		if key == "nodes":
			continue
		if key == "name":
			node["name"] = str(config[key])
		elif key == "data":
			node["data"] = config[key] if typeof(config[key]) == TYPE_DICTIONARY else gml_struct({})
		else:
			_gml_flexpanel_apply_style_property(node, str(key), config[key])
	if config.has("nodes") and typeof(config["nodes"]) == TYPE_ARRAY:
		for child_config in config["nodes"]:
			gml_flexpanel_node_insert_child(node, gml_flexpanel_create_node(child_config), node["children"].size())


static func _gml_flexpanel_apply_style_property(node, key, value):
	if key in ["width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight", "flexBasis"]:
		node["style"][key] = _gml_flexpanel_unit_value(value)
	elif key in ["left", "right", "top", "bottom", "start", "end"]:
		for position_key in _gml_flexpanel_position_style_keys(key):
			node["style"][position_key] = _gml_flexpanel_unit_value(value)
	elif key in ["padding", "margin", "border"]:
		_gml_flexpanel_set_edge_style(node, key, "all", value, "point")
	elif key in [
		"paddingLeft", "paddingRight", "paddingTop", "paddingBottom", "paddingStart", "paddingEnd", "paddingHorizontal", "paddingVertical",
		"marginLeft", "marginRight", "marginTop", "marginBottom", "marginStart", "marginEnd", "marginInline", "marginHorizontal", "marginVertical",
		"borderLeft", "borderRight", "borderTop", "borderBottom", "borderStart", "borderEnd", "borderHorizontal", "borderVertical"
	]:
		_gml_flexpanel_apply_edge_style_property(node, key, value)
	elif key == "gap":
		node["style"]["gapRow"] = float(_to_real(value))
		node["style"]["gapColumn"] = float(_to_real(value))
	elif key in ["gapRow", "gapColumn", "aspectRatio", "flex", "flexGrow", "flexShrink"]:
		node["style"][key] = float(_to_real(value))
	elif key == "position":
		node["style"]["positionType"] = _gml_flexpanel_keyword(value)
	elif key in ["flexWrap", "alignContent"] and _gml_flexpanel_keyword(value) not in ["no-wrap", "flex-start"]:
		_gml_flexpanel_unsupported_feature("Flex Panel " + key, "This compatibility layout pass supports single-line flex layouts only.")
		node["style"][key] = _gml_flexpanel_keyword(value)
	elif key in ["alignItems", "alignSelf", "justifyContent", "direction", "display", "positionType", "flexWrap", "flexDirection"]:
		node["style"][key] = _gml_flexpanel_keyword(value)
	else:
		node["style"][key] = value


static func _gml_flexpanel_is_node(value):
	return typeof(value) == TYPE_DICTIONARY and value.has(GML_FLEXPANEL_NODE_MARKER)


static func _gml_flexpanel_apply_edge_style_property(node, key, value):
	var prefix = ""
	if key.begins_with("padding"):
		prefix = "padding"
	elif key.begins_with("margin"):
		prefix = "margin"
	elif key.begins_with("border"):
		prefix = "border"
	if prefix == "":
		return
	var edge_name = key.substr(prefix.length())
	if edge_name == "Inline":
		edge_name = "Horizontal"
	_gml_flexpanel_set_edge_style(node, prefix, edge_name, value, "point")


static func _gml_flexpanel_unit_value(value, unit = "point"):
	if typeof(value) == TYPE_DICTIONARY and value.has("value") and value.has("unit"):
		return gml_struct({"value": value["value"], "unit": str(value["unit"])})
	if is_string(value):
		var text = str(value).strip_edges()
		if text.ends_with("%"):
			return gml_struct({"value": float(text.substr(0, text.length() - 1)), "unit": "percent"})
		if text.to_lower() == "auto":
			return gml_struct({"value": 0.0, "unit": "auto"})
	return gml_struct({"value": float(_to_real(value)), "unit": _gml_flexpanel_unit_name(unit)})


static func _gml_flexpanel_unit_name(unit):
	var text = str(unit)
	if text in ["percent", "%", "1"]:
		return "percent"
	if text in ["auto", "2"]:
		return "auto"
	return "point"


static func _gml_flexpanel_direction_name(value):
	var text = _gml_flexpanel_keyword(value)
	if text in ["row", "row-reverse", "column", "column-reverse"]:
		return text
	return "column"


static func _gml_flexpanel_direction_value(value):
	var text = str(value)
	if text in ["LTR", "ltr", "left-to-right"]:
		return "ltr"
	if text in ["RTL", "rtl", "right-to-left"]:
		return "rtl"
	if text == "inherit":
		return "inherit"
	return "ltr"


static func _gml_flexpanel_keyword(value):
	var raw_text = str(value).strip_edges()
	if raw_text in ["LTR", "ltr"]:
		return "ltr"
	if raw_text in ["RTL", "rtl"]:
		return "rtl"
	var text = raw_text.replace("_", "-").to_lower()
	if text in ["all-edges", "all-gutters"]:
		return "all"
	if text == "no-wrap":
		return "no-wrap"
	if text == "wrap-reverse" or text == "reverse":
		return "wrap-reverse"
	if text in ["flex-start", "start"]:
		return "flex-start"
	if text == "flex-end":
		return "flex-end"
	if text == "margin-inline":
		return "horizontal"
	return text


static func _gml_flexpanel_set_style(node, key, value):
	if not _gml_flexpanel_is_node(node):
		return false
	node["style"][key] = value
	return null


static func _gml_flexpanel_get_style(node, key, default_value = null):
	if not _gml_flexpanel_is_node(node):
		return default_value
	return node["style"].get(key, default_value)


static func _gml_flexpanel_set_unit_style(node, key, value, unit):
	if not _gml_flexpanel_is_node(node):
		return false
	node["style"][key] = _gml_flexpanel_unit_value(value, unit)
	return null


static func _gml_flexpanel_get_unit_style(node, key):
	if not _gml_flexpanel_is_node(node):
		return _gml_flexpanel_unit_value("auto")
	return node["style"].get(key, _gml_flexpanel_unit_value("auto"))


static func _gml_flexpanel_set_edge_style(node, prefix, edge, size, unit):
	if not _gml_flexpanel_is_node(node):
		return false
	var unit_value = _gml_flexpanel_unit_value(size, unit)
	for key in _gml_flexpanel_edge_style_keys(prefix, edge):
		node["style"][key] = unit_value
	return null


static func _gml_flexpanel_get_edge_style(node, prefix, edge):
	if not _gml_flexpanel_is_node(node):
		return _gml_flexpanel_unit_value(0)
	var keys = _gml_flexpanel_edge_style_keys(prefix, edge)
	if keys.is_empty():
		return _gml_flexpanel_unit_value(0)
	return node["style"].get(keys[0], _gml_flexpanel_unit_value(0))


static func _gml_flexpanel_edge_style_keys(prefix, edge):
	var edge_name = _gml_flexpanel_keyword(edge)
	var title_prefix = "padding" if prefix == "padding" else "margin"
	if prefix == "border":
		title_prefix = "border"
	if edge_name == "all":
		return [title_prefix + "Left", title_prefix + "Right", title_prefix + "Top", title_prefix + "Bottom"]
	if edge_name == "horizontal":
		return [title_prefix + "Left", title_prefix + "Right"]
	if edge_name == "vertical":
		return [title_prefix + "Top", title_prefix + "Bottom"]
	var suffix = _gml_flexpanel_edge_suffix(edge_name)
	if suffix != "":
		return [title_prefix + suffix]
	return []


static func _gml_flexpanel_position_style_keys(edge):
	var edge_name = _gml_flexpanel_keyword(edge)
	var suffix = _gml_flexpanel_edge_suffix(edge_name)
	if suffix == "":
		return []
	return [suffix.substr(0, 1).to_lower() + suffix.substr(1)]


static func _gml_flexpanel_edge_suffix(edge_name):
	if edge_name == "left" or edge_name == "start":
		return "Left"
	if edge_name == "right" or edge_name == "end":
		return "Right"
	if edge_name == "top":
		return "Top"
	if edge_name == "bottom":
		return "Bottom"
	return ""


static func _gml_flexpanel_resolve_size(node, key, containing_size, default_value = 0.0):
	if is_undefined(containing_size):
		containing_size = 0.0
	var unit_value = node["style"].get(key, null) if _gml_flexpanel_is_node(node) else null
	var resolved = 0.0
	if unit_value == null:
		resolved = float(_to_real(default_value)) if not is_undefined(default_value) else 0.0
	else:
		var unit = str(unit_value.get("unit", "point"))
		if unit == "percent":
			resolved = float(_to_real(containing_size)) * float(_to_real(unit_value.get("value", 0.0))) / 100.0
		elif unit == "auto":
			resolved = float(_to_real(default_value)) if not is_undefined(default_value) else 0.0
		else:
			resolved = float(_to_real(unit_value.get("value", 0.0)))
	return _gml_flexpanel_clamp_dimension(node, key, resolved, containing_size)


static func _gml_flexpanel_clamp_dimension(node, key, value, containing_size):
	if value < 0.0:
		return value
	if key == "width":
		if node["style"].has("minWidth"):
			value = max(value, _gml_flexpanel_resolve_unit_value(node["style"]["minWidth"], containing_size))
		if node["style"].has("maxWidth"):
			value = min(value, _gml_flexpanel_resolve_unit_value(node["style"]["maxWidth"], containing_size))
	elif key == "height":
		if node["style"].has("minHeight"):
			value = max(value, _gml_flexpanel_resolve_unit_value(node["style"]["minHeight"], containing_size))
		if node["style"].has("maxHeight"):
			value = min(value, _gml_flexpanel_resolve_unit_value(node["style"]["maxHeight"], containing_size))
	return value


static func _gml_flexpanel_layout_node(node, left, top, width, height, absolute_left, absolute_top, direction, parent_width = 0.0, parent_height = 0.0):
	var padding_left = _gml_flexpanel_edge_pixels(node, "paddingLeft", width)
	var padding_right = _gml_flexpanel_edge_pixels(node, "paddingRight", width)
	var padding_top = _gml_flexpanel_edge_pixels(node, "paddingTop", height)
	var padding_bottom = _gml_flexpanel_edge_pixels(node, "paddingBottom", height)
	var border_left = _gml_flexpanel_edge_pixels(node, "borderLeft", width)
	var border_right = _gml_flexpanel_edge_pixels(node, "borderRight", width)
	var border_top = _gml_flexpanel_edge_pixels(node, "borderTop", height)
	var border_bottom = _gml_flexpanel_edge_pixels(node, "borderBottom", height)
	var margin_left = _gml_flexpanel_edge_pixels(node, "marginLeft", width)
	var margin_right = _gml_flexpanel_edge_pixels(node, "marginRight", width)
	var margin_top = _gml_flexpanel_edge_pixels(node, "marginTop", height)
	var margin_bottom = _gml_flexpanel_edge_pixels(node, "marginBottom", height)
	var node_direction = _gml_flexpanel_direction_value(node["style"].get("direction", direction))
	if node_direction == "inherit":
		node_direction = direction
	node["layout"] = gml_struct({
		"left": float(left),
		"top": float(top),
		"absolute_left": float(absolute_left),
		"absolute_top": float(absolute_top),
		"width": float(width),
		"height": float(height),
		"right": max(float(parent_width) - float(left) - float(width), 0.0),
		"bottom": max(float(parent_height) - float(top) - float(height), 0.0),
		"hadOverflow": false,
		"direction": node_direction,
		"paddingLeft": padding_left,
		"paddingRight": padding_right,
		"paddingTop": padding_top,
		"paddingBottom": padding_bottom,
		"marginLeft": margin_left,
		"marginRight": margin_right,
		"marginTop": margin_top,
		"marginBottom": margin_bottom
	})
	if not _gml_flexpanel_is_displayed(node):
		return
	var content_left = padding_left + border_left
	var content_top = padding_top + border_top
	var content_width = max(float(width) - padding_left - padding_right - border_left - border_right, 0.0)
	var content_height = max(float(height) - padding_top - padding_bottom - border_top - border_bottom, 0.0)
	var flex_direction = str(node["style"].get("flexDirection", "column"))
	var row_layout = flex_direction.begins_with("row")
	var reverse_layout = flex_direction.ends_with("reverse")
	var children = []
	var absolute_children = []
	for child in node["children"]:
		if not _gml_flexpanel_is_node(child) or not _gml_flexpanel_is_displayed(child):
			continue
		if str(child["style"].get("positionType", "relative")) == "absolute":
			absolute_children.append(child)
		else:
			children.append(child)
	if reverse_layout:
		children.reverse()
	var gap = float(node["style"].get("gapColumn" if row_layout else "gapRow", 0.0))
	var cursor = content_left if row_layout else content_top
	var main_available = content_width if row_layout else content_height
	var main_used = 0.0
	var flex_total = 0.0
	for child in children:
		var explicit_main = _gml_flexpanel_child_main_size(child, row_layout, main_available)
		if explicit_main >= 0:
			main_used += explicit_main
		else:
			flex_total += float(child["style"].get("flex", child["style"].get("flexGrow", 0.0)))
	main_used += max(children.size() - 1, 0) * gap
	var remaining = max(main_available - main_used, 0.0)
	if flex_total <= 0.0:
		var justify = str(node["style"].get("justifyContent", "flex-start"))
		if justify == "center":
			cursor += remaining / 2.0
		elif justify == "flex-end":
			cursor += remaining
		elif justify == "space-between" and children.size() > 1:
			gap += remaining / float(children.size() - 1)
		elif justify == "space-around" and children.size() > 0:
			var edge_gap = remaining / float(children.size())
			cursor += edge_gap / 2.0
			gap += edge_gap
		elif justify == "space-evenly" and children.size() > 0:
			var edge_gap = remaining / float(children.size() + 1)
			cursor += edge_gap
			gap += edge_gap
	for child in children:
		var child_width = _gml_flexpanel_resolve_size(child, "width", content_width, -1)
		var child_height = _gml_flexpanel_resolve_size(child, "height", content_height, -1)
		var explicit_main = _gml_flexpanel_child_main_size(child, row_layout, main_available)
		var flex_value = float(child["style"].get("flex", child["style"].get("flexGrow", 0.0)))
		if row_layout and explicit_main >= 0:
			child_width = explicit_main
		if not row_layout and explicit_main >= 0:
			child_height = explicit_main
		if row_layout and child_width < 0:
			child_width = remaining * flex_value / flex_total if flex_total > 0 else 0.0
		if not row_layout and child_height < 0:
			child_height = remaining * flex_value / flex_total if flex_total > 0 else 0.0
		var sizes = _gml_flexpanel_apply_aspect_ratio(child, child_width, child_height)
		child_width = sizes[0]
		child_height = sizes[1]
		var align = _gml_flexpanel_child_align(child, node)
		if child_width < 0:
			child_width = content_width if (not row_layout and align == "stretch") else 0.0
		if child_height < 0:
			child_height = content_height if (row_layout and align == "stretch") else 0.0
		var child_left = cursor if row_layout else content_left
		var child_top = content_top if row_layout else cursor
		if row_layout:
			child_top = _gml_flexpanel_cross_position(align, content_top, content_height, child_height)
		else:
			child_left = _gml_flexpanel_cross_position(align, content_left, content_width, child_width)
		if str(child["style"].get("positionType", "relative")) == "relative":
			child_left += _gml_flexpanel_resolve_size(child, "left", content_width, 0.0)
			child_top += _gml_flexpanel_resolve_size(child, "top", content_height, 0.0)
		_gml_flexpanel_layout_node(child, child_left, child_top, child_width, child_height, absolute_left + child_left, absolute_top + child_top, node_direction, width, height)
		cursor += (child_width if row_layout else child_height) + gap
		if cursor > (content_left + content_width if row_layout else content_top + content_height):
			node["layout"]["hadOverflow"] = true
	for child in absolute_children:
		_gml_flexpanel_layout_absolute_child(child, content_left, content_top, content_width, content_height, absolute_left, absolute_top, node_direction, width, height)
		var child_layout = child["layout"]
		if (
			float(child_layout["left"]) < content_left
			or float(child_layout["top"]) < content_top
			or float(child_layout["left"]) + float(child_layout["width"]) > content_left + content_width
			or float(child_layout["top"]) + float(child_layout["height"]) > content_top + content_height
		):
			node["layout"]["hadOverflow"] = true


static func _gml_flexpanel_is_displayed(node):
	return str(node["style"].get("display", "flex")) != "none"


static func _gml_flexpanel_child_main_size(child, row_layout, main_available):
	if child["style"].has("flexBasis"):
		return _gml_flexpanel_resolve_size(child, "flexBasis", main_available, -1)
	return _gml_flexpanel_resolve_size(child, "width" if row_layout else "height", main_available, -1)


static func _gml_flexpanel_apply_aspect_ratio(child, width, height):
	var ratio = float(child["style"].get("aspectRatio", 0.0))
	if ratio <= 0.0:
		return [width, height]
	if width < 0.0 and height >= 0.0:
		width = height * ratio
	elif height < 0.0 and width >= 0.0:
		height = width / ratio
	return [width, height]


static func _gml_flexpanel_child_align(child, parent):
	var align = str(child["style"].get("alignSelf", "auto"))
	if align == "auto":
		align = str(parent["style"].get("alignItems", "stretch"))
	return align


static func _gml_flexpanel_cross_position(align, content_start, content_size, child_size):
	if align == "center":
		return content_start + max(content_size - child_size, 0.0) / 2.0
	if align == "flex-end":
		return content_start + max(content_size - child_size, 0.0)
	return content_start


static func _gml_flexpanel_layout_absolute_child(child, content_left, content_top, content_width, content_height, absolute_left, absolute_top, direction, parent_width, parent_height):
	var left_value = _gml_flexpanel_resolve_size(child, "left", content_width, 0.0)
	var right_value = _gml_flexpanel_resolve_size(child, "right", content_width, 0.0)
	var top_value = _gml_flexpanel_resolve_size(child, "top", content_height, 0.0)
	var bottom_value = _gml_flexpanel_resolve_size(child, "bottom", content_height, 0.0)
	var child_width = _gml_flexpanel_resolve_size(child, "width", content_width, -1)
	var child_height = _gml_flexpanel_resolve_size(child, "height", content_height, -1)
	if child_width < 0.0 and child["style"].has("left") and child["style"].has("right"):
		child_width = max(content_width - left_value - right_value, 0.0)
	if child_height < 0.0 and child["style"].has("top") and child["style"].has("bottom"):
		child_height = max(content_height - top_value - bottom_value, 0.0)
	var sizes = _gml_flexpanel_apply_aspect_ratio(child, child_width, child_height)
	child_width = max(sizes[0], 0.0)
	child_height = max(sizes[1], 0.0)
	var child_left = content_left + left_value
	if not child["style"].has("left") and child["style"].has("right"):
		child_left = content_left + content_width - right_value - child_width
	var child_top = content_top + top_value
	if not child["style"].has("top") and child["style"].has("bottom"):
		child_top = content_top + content_height - bottom_value - child_height
	_gml_flexpanel_layout_node(child, child_left, child_top, child_width, child_height, absolute_left + child_left, absolute_top + child_top, direction, parent_width, parent_height)


static func _gml_flexpanel_edge_pixels(node, key, containing_size):
	var value = node["style"].get(key, _gml_flexpanel_unit_value(0))
	return _gml_flexpanel_resolve_unit_value(value, containing_size)


static func _gml_flexpanel_resolve_unit_value(unit_value, containing_size):
	if typeof(unit_value) != TYPE_DICTIONARY:
		return float(_to_real(unit_value))
	var unit = str(unit_value.get("unit", "point"))
	if unit == "percent":
		return float(_to_real(containing_size)) * float(_to_real(unit_value.get("value", 0.0))) / 100.0
	if unit == "auto":
		return 0.0
	return float(_to_real(unit_value.get("value", 0.0)))


static func _gml_flexpanel_empty_layout():
	return gml_struct({
		"left": 0.0,
		"top": 0.0,
		"absolute_left": 0.0,
		"absolute_top": 0.0,
		"width": 0.0,
		"height": 0.0,
		"right": 0.0,
		"bottom": 0.0,
		"hadOverflow": false,
		"direction": "LTR",
		"paddingLeft": 0.0,
		"paddingRight": 0.0,
		"paddingTop": 0.0,
		"paddingBottom": 0.0,
		"marginLeft": 0.0,
		"marginRight": 0.0,
		"marginTop": 0.0,
		"marginBottom": 0.0
	})


static func _gml_flexpanel_unsupported_feature(api_name, reason):
	return gml_error(str(api_name) + " is not supported by GM2Godot Flex Panel compatibility runtime: " + str(reason))
