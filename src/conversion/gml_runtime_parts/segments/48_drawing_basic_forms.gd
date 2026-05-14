const GML_DRAW_DEFAULT_FONT_SIZE = 16
const GML_FA_LEFT = 0
const GML_FA_CENTER = 1
const GML_FA_RIGHT = 2
const GML_FA_TOP = 0
const GML_FA_MIDDLE = 1
const GML_FA_BOTTOM = 2
const GML_TILE_MIRROR = 0x10000000
const GML_TILE_FLIP = 0x20000000
const GML_TILE_ROTATE = 0x40000000
const GML_TILE_INDEX_MASK = 0x000fffff

static var _gml_draw_context_stack = []
static var _gml_draw_sprite_cache = {}
static var _gml_draw_font_cache = {}
static var _gml_draw_tileset_cache = {}
static var _gml_draw_state = {
	"color": 0xffffff,
	"alpha": 1.0,
	"line_width": 1.0,
	"font": -1,
	"halign": GML_FA_LEFT,
	"valign": GML_FA_TOP,
	"blend_mode": 0
}


static func gml_draw_begin(target, context_name = "draw"):
	_gml_draw_context_stack.append({
		"target": target,
		"context": str(context_name),
		"state": _gml_draw_state_copy()
	})
	if str(context_name) == "_draw":
		_gml_draw_hide_default_sprite(target)
	return null


static func gml_draw_end():
	if _gml_draw_context_stack.is_empty():
		return null
	var context = _gml_draw_context_stack.pop_back()
	_gml_draw_state = context["state"]
	return null


static func gml_draw_self(instance):
	var sprite = _gml_object_get(instance, "sprite_index", -1)
	if _gml_draw_is_no_sprite(sprite):
		return null
	return gml_draw_sprite_ext(
		sprite,
		_gml_object_get(instance, "image_index", 0),
		0,
		0,
		_gml_object_get(instance, "image_xscale", 1),
		_gml_object_get(instance, "image_yscale", 1),
		_gml_object_get(instance, "image_angle", 0),
		_gml_object_get(instance, "image_blend", 0xffffff),
		_gml_object_get(instance, "image_alpha", 1)
	)


static func gml_draw_sprite(sprite, subimg, x, y):
	return gml_draw_sprite_ext(sprite, subimg, x, y, 1, 1, 0, 0xffffff, 1)


static func gml_draw_sprite_ext(sprite, subimg, x, y, xscale, yscale, rot, colour, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = Rect2(Vector2.ZERO, frame["size"])
	_gml_draw_texture_part(frame["texture"], source, x, y, xscale, yscale, rot, colour, alpha, frame["origin"])
	return null


static func gml_draw_sprite_part(sprite, subimg, left, top, width, height, x, y):
	return gml_draw_sprite_part_ext(sprite, subimg, left, top, width, height, x, y, 1, 1, 0xffffff, 1)


static func gml_draw_sprite_part_ext(sprite, subimg, left, top, width, height, x, y, xscale, yscale, colour, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = _gml_draw_source_rect(left, top, width, height, frame["size"])
	_gml_draw_texture_part(frame["texture"], source, x, y, xscale, yscale, 0, colour, alpha, Vector2.ZERO)
	return null


static func gml_draw_sprite_general(sprite, subimg, left, top, width, height, x, y, xscale, yscale, rot, c1, c2, c3, c4, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = _gml_draw_source_rect(left, top, width, height, frame["size"])
	var blend = _gml_draw_average_colour([c1, c2, c3, c4], alpha)
	_gml_draw_texture_part(frame["texture"], source, x, y, xscale, yscale, rot, blend, alpha, Vector2.ZERO)
	return null


static func gml_draw_sprite_pos(sprite, subimg, x1, y1, x2, y2, x3, y3, x4, y4, alpha):
	var target = _gml_draw_target()
	if target == null:
		return null
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var texture = frame["texture"]
	var size = frame["size"]
	var points = PackedVector2Array([
		Vector2(_to_real(x1), _to_real(y1)),
		Vector2(_to_real(x2), _to_real(y2)),
		Vector2(_to_real(x3), _to_real(y3)),
		Vector2(_to_real(x4), _to_real(y4))
	])
	var uvs = PackedVector2Array([
		Vector2(0, 0),
		Vector2(size.x, 0),
		Vector2(size.x, size.y),
		Vector2(0, size.y)
	])
	var modulate = _gml_draw_modulate(0xffffff, alpha)
	target.draw_polygon(points, PackedColorArray([modulate, modulate, modulate, modulate]), uvs, texture)
	return null


static func gml_draw_sprite_tiled(sprite, subimg, x, y):
	return gml_draw_sprite_tiled_ext(sprite, subimg, x, y, 1, 1, 0xffffff, 1)


static func gml_draw_sprite_tiled_ext(sprite, subimg, x, y, xscale, yscale, colour, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var size = frame["size"]
	var tile_width = abs(size.x * _to_real(xscale))
	var tile_height = abs(size.y * _to_real(yscale))
	if tile_width <= 0.0 or tile_height <= 0.0:
		return null
	var bounds = _gml_draw_room_size()
	var start_x = _to_real(x)
	var start_y = _to_real(y)
	while start_x > 0.0:
		start_x -= tile_width
	while start_y > 0.0:
		start_y -= tile_height
	var source = Rect2(Vector2.ZERO, size)
	var draw_y = start_y
	while draw_y < bounds.y:
		var draw_x = start_x
		while draw_x < bounds.x:
			_gml_draw_texture_part(frame["texture"], source, draw_x, draw_y, xscale, yscale, 0, colour, alpha, Vector2.ZERO)
			draw_x += tile_width
		draw_y += tile_height
	return null


static func gml_draw_tile(tileset, tiledata, frame, x, y):
	var tile = _gml_draw_tileset_tile(tileset, tiledata, frame)
	if tile == null:
		return null
	_gml_draw_texture_part(
		tile["texture"],
		tile["source"],
		x,
		y,
		tile["xscale"],
		tile["yscale"],
		tile["rotation"],
		0xffffff,
		1,
		tile["origin"]
	)
	return null


static func gml_draw_tilemap(tilemap_element_id, x, y):
	if tilemap_element_id is Node2D:
		tilemap_element_id.position = Vector2(_to_real(x), _to_real(y))
		tilemap_element_id.visible = true
	return null


static func gml_draw_set_font(font):
	_gml_draw_state["font"] = font
	return null


static func gml_draw_get_font():
	if is_undefined(_gml_draw_state["font"]):
		return -1
	return _gml_draw_state["font"]


static func gml_draw_set_halign(halign):
	_gml_draw_state["halign"] = int(_to_real(halign))
	return null


static func gml_draw_get_halign():
	return _gml_draw_state["halign"]


static func gml_draw_set_valign(valign):
	_gml_draw_state["valign"] = int(_to_real(valign))
	return null


static func gml_draw_get_valign():
	return _gml_draw_state["valign"]


static func gml_draw_text(x, y, text):
	_gml_draw_text_at(x, y, text, -1, -1)
	return null


static func gml_draw_text_ext(x, y, text, sep, width):
	_gml_draw_text_at(x, y, text, sep, width)
	return null


static func gml_draw_text_transformed(x, y, text, xscale, yscale, angle):
	var target = _gml_draw_target()
	if target == null:
		return null
	target.draw_set_transform(Vector2(_to_real(x), _to_real(y)), deg_to_rad(-_to_real(angle)), Vector2(_to_real(xscale), _to_real(yscale)))
	_gml_draw_text_at(0, 0, text, -1, -1)
	target.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	return null


static func gml_string_width(text):
	return _gml_draw_text_metrics(text, -1, -1).x


static func gml_string_height(text):
	return _gml_draw_text_metrics(text, -1, -1).y


static func gml_string_width_ext(text, sep, width):
	return _gml_draw_text_metrics(text, sep, width).x


static func gml_string_height_ext(text, sep, width):
	return _gml_draw_text_metrics(text, sep, width).y


static func gml_draw_set_color(color):
	_gml_draw_state["color"] = int(_to_real(color))
	return null


static func gml_draw_get_color():
	return _gml_draw_state["color"]


static func gml_draw_set_alpha(alpha):
	_gml_draw_state["alpha"] = clamp(_to_real(alpha), 0.0, 1.0)
	return null


static func gml_draw_get_alpha():
	return _gml_draw_state["alpha"]


static func gml_draw_set_line_width(width):
	_gml_draw_state["line_width"] = max(_to_real(width), 1.0)
	return null


static func gml_draw_get_line_width():
	return _gml_draw_state["line_width"]


static func gml_draw_clear(color):
	var target = _gml_draw_target()
	if target == null:
		return null
	var rect = Rect2(Vector2(-100000.0, -100000.0), Vector2(200000.0, 200000.0))
	target.draw_rect(rect, _gml_draw_color(color), true)
	return null


static func gml_draw_line(x1, y1, x2, y2):
	var target = _gml_draw_target()
	if target == null:
		return null
	target.draw_line(
		Vector2(_to_real(x1), _to_real(y1)),
		Vector2(_to_real(x2), _to_real(y2)),
		_gml_draw_current_color(),
		_gml_draw_line_width()
	)
	return null


static func gml_draw_rectangle(x1, y1, x2, y2, outline):
	var target = _gml_draw_target()
	if target == null:
		return null
	var left = min(_to_real(x1), _to_real(x2))
	var top = min(_to_real(y1), _to_real(y2))
	var right = max(_to_real(x1), _to_real(x2))
	var bottom = max(_to_real(y1), _to_real(y2))
	var rect = Rect2(Vector2(left, top), Vector2(right - left, bottom - top))
	target.draw_rect(rect, _gml_draw_current_color(), not gml_bool(outline), _gml_draw_line_width())
	return null


static func gml_draw_circle(x, y, radius, outline):
	var target = _gml_draw_target()
	if target == null:
		return null
	var center = Vector2(_to_real(x), _to_real(y))
	var resolved_radius = abs(_to_real(radius))
	if gml_bool(outline):
		target.draw_arc(center, resolved_radius, 0.0, TAU, 64, _gml_draw_current_color(), _gml_draw_line_width())
	else:
		target.draw_circle(center, resolved_radius, _gml_draw_current_color())
	return null


static func gml_draw_triangle(x1, y1, x2, y2, x3, y3, outline):
	var target = _gml_draw_target()
	if target == null:
		return null
	var points = PackedVector2Array([
		Vector2(_to_real(x1), _to_real(y1)),
		Vector2(_to_real(x2), _to_real(y2)),
		Vector2(_to_real(x3), _to_real(y3))
	])
	if gml_bool(outline):
		var outline_points = PackedVector2Array([points[0], points[1], points[2], points[0]])
		target.draw_polyline(outline_points, _gml_draw_current_color(), _gml_draw_line_width())
	else:
		target.draw_colored_polygon(points, _gml_draw_current_color())
	return null


static func gml_draw_point(x, y):
	var target = _gml_draw_target()
	if target == null:
		return null
	target.draw_circle(
		Vector2(_to_real(x), _to_real(y)),
		max(_gml_draw_line_width() * 0.5, 1.0),
		_gml_draw_current_color()
	)
	return null


static func _gml_draw_target():
	if _gml_draw_context_stack.is_empty():
		return null
	var target = _gml_draw_context_stack[_gml_draw_context_stack.size() - 1]["target"]
	if target is CanvasItem:
		return target
	return null


static func _gml_draw_current_context_target():
	if _gml_draw_context_stack.is_empty():
		return null
	return _gml_draw_context_stack[_gml_draw_context_stack.size() - 1]["target"]


static func _gml_draw_current_color():
	return _gml_draw_color(_gml_draw_state["color"])


static func _gml_draw_color(color):
	return _gml_draw_modulate(color, 1.0)


static func _gml_draw_modulate(color, alpha):
	var resolved_alpha = clamp(_to_real(alpha) * _to_real(_gml_draw_state["alpha"]), 0.0, 1.0)
	if color is Color:
		var color_value = color
		color_value.a = resolved_alpha
		return color_value
	var value = int(_to_real(color))
	var red = float(value & 0xff) / 255.0
	var green = float((value >> 8) & 0xff) / 255.0
	var blue = float((value >> 16) & 0xff) / 255.0
	return Color(red, green, blue, resolved_alpha)


static func _gml_draw_average_colour(colours, alpha):
	if colours.is_empty():
		return _gml_draw_modulate(0xffffff, alpha)
	var red = 0.0
	var green = 0.0
	var blue = 0.0
	for colour in colours:
		var color_value = _gml_draw_modulate(colour, alpha)
		red += color_value.r
		green += color_value.g
		blue += color_value.b
	var count = float(colours.size())
	return Color(red / count, green / count, blue / count, clamp(_to_real(alpha), 0.0, 1.0))


static func _gml_draw_line_width():
	return max(_to_real(_gml_draw_state["line_width"]), 1.0)


static func _gml_draw_texture_part(texture, source, x, y, xscale, yscale, rot, colour, alpha, origin):
	var target = _gml_draw_target()
	if target == null or texture == null:
		return null
	var scale = Vector2(_to_real(xscale), _to_real(yscale))
	if abs(scale.x) <= 0.00001 or abs(scale.y) <= 0.00001:
		return null
	var draw_origin = origin
	if not (draw_origin is Vector2):
		draw_origin = Vector2.ZERO
	var rect = Rect2(-draw_origin, source.size)
	target.draw_set_transform(Vector2(_to_real(x), _to_real(y)), deg_to_rad(-_to_real(rot)), scale)
	target.draw_texture_rect_region(texture, rect, source, _gml_draw_modulate(colour, alpha), false, true)
	target.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	return null


static func _gml_draw_source_rect(left, top, width, height, frame_size):
	var source_left = clamp(_to_real(left), 0.0, frame_size.x)
	var source_top = clamp(_to_real(top), 0.0, frame_size.y)
	var source_width = clamp(_to_real(width), 0.0, frame_size.x - source_left)
	var source_height = clamp(_to_real(height), 0.0, frame_size.y - source_top)
	return Rect2(Vector2(source_left, source_top), Vector2(source_width, source_height))


static func _gml_draw_sprite_frame(sprite, subimg):
	var data = _gml_draw_sprite_data(sprite)
	if data == null:
		return null
	var textures = data["textures"]
	if textures.is_empty():
		return null
	var frame_index = _gml_draw_subimage_index(subimg, textures.size())
	var texture = textures[frame_index]
	if texture == null:
		return null
	return {
		"texture": texture,
		"origin": data["origin"],
		"size": texture.get_size()
	}


static func _gml_draw_subimage_index(subimg, frame_count):
	if frame_count <= 0:
		return 0
	var resolved_subimg = subimg
	if is_numeric(subimg) and int(_to_real(subimg)) == -1:
		resolved_subimg = _gml_object_get(_gml_draw_current_context_target(), "image_index", 0)
	var frame_index = int(floor(_to_real(resolved_subimg)))
	return ((frame_index % frame_count) + frame_count) % frame_count


static func _gml_draw_sprite_data(sprite):
	if sprite is Texture2D:
		return {"textures": [sprite], "origin": sprite.get_size() * 0.5}
	_gml_asset_registry_ensure_loaded()
	var raw_entry = _gml_asset_resolve(sprite)
	if typeof(raw_entry) != TYPE_DICTIONARY:
		return null
	var entry: Dictionary = raw_entry
	if str(entry.get("type", "")) != "sprite":
		return null
	var asset_id = int(entry.get("id", -1))
	if _gml_draw_sprite_cache.has(asset_id):
		return _gml_draw_sprite_cache[asset_id]
	var resource = entry.get("resource", null)
	if resource == null and str(entry.get("godot_path", "")) != "":
		resource = load(str(entry.get("godot_path", "")))
	var data = _gml_draw_sprite_data_from_resource(resource)
	if data != null:
		_gml_draw_sprite_cache[asset_id] = data
	return data


static func _gml_draw_sprite_data_from_resource(resource):
	if resource is Texture2D:
		return {"textures": [resource], "origin": resource.get_size() * 0.5}
	if resource is PackedScene:
		var root = resource.instantiate()
		var data = _gml_draw_sprite_data_from_node(root)
		root.free()
		return data
	if resource is Node:
		return _gml_draw_sprite_data_from_node(resource)
	return null


static func _gml_draw_sprite_data_from_node(root):
	var visual = _gml_draw_find_sprite_visual(root)
	if visual == null:
		return null
	var textures = []
	if visual is AnimatedSprite2D:
		if visual.sprite_frames != null and visual.sprite_frames.has_animation(visual.animation):
			var frame_count = visual.sprite_frames.get_frame_count(visual.animation)
			for index in range(frame_count):
				var frame_texture = visual.sprite_frames.get_frame_texture(visual.animation, index)
				if frame_texture != null:
					textures.append(frame_texture)
	elif visual is Sprite2D and visual.texture != null:
		textures.append(visual.texture)
	if textures.is_empty():
		return null
	var first_size = textures[0].get_size()
	return {
		"textures": textures,
		"origin": _gml_draw_origin_from_node(root, visual, first_size)
	}


static func _gml_draw_find_sprite_visual(root):
	if root is Sprite2D or root is AnimatedSprite2D:
		return root
	if not (root is Node):
		return null
	var animated = root.find_child("AnimatedSprite2D", true, false)
	if animated != null:
		return animated
	return root.find_child("Sprite2D", true, false)


static func _gml_draw_origin_from_node(root, visual, texture_size):
	if root is Node and root.has_meta("gamemaker_origin_x") and root.has_meta("gamemaker_origin_y"):
		return Vector2(_to_real(root.get_meta("gamemaker_origin_x")), _to_real(root.get_meta("gamemaker_origin_y")))
	if visual is Sprite2D and visual.centered:
		return texture_size * 0.5
	return Vector2.ZERO


static func _gml_draw_hide_default_sprite(target):
	var visual = _gml_draw_instance_visual_node(target)
	if visual is CanvasItem:
		visual.visible = false


static func _gml_draw_instance_visual_node(target):
	if not (target is Node):
		return null
	for child in target.get_children():
		if child is Sprite2D or child is AnimatedSprite2D:
			return child
		if child is Node:
			var visual = _gml_draw_find_sprite_visual(child)
			if visual != null:
				return visual
	return null


static func _gml_draw_tileset_tile(tileset, tiledata, frame):
	var tile_set = _gml_draw_tileset_resource(tileset)
	if tile_set == null:
		return null
	var tile_value = int(_to_real(tiledata))
	var tile_index = tile_value & GML_TILE_INDEX_MASK
	if tile_set.get_source_count() <= 0:
		return null
	var source = tile_set.get_source(tile_set.get_source_id(0))
	if source == null or not source.has_method("get_tile_texture_region"):
		return null
	var texture = source.texture
	if texture == null:
		return null
	var tile_size = tile_set.tile_size
	var texture_size = texture.get_size()
	var columns = max(int(floor(texture_size.x / max(float(tile_size.x), 1.0))), 1)
	var atlas_coords = Vector2i(tile_index % columns, int(floor(float(tile_index) / float(columns))))
	var source_rect = source.get_tile_texture_region(atlas_coords)
	if source_rect.size == Vector2.ZERO:
		source_rect = Rect2(Vector2(atlas_coords.x * tile_size.x, atlas_coords.y * tile_size.y), Vector2(tile_size.x, tile_size.y))
	var xscale = -1 if (tile_value & GML_TILE_MIRROR) != 0 else 1
	var yscale = -1 if (tile_value & GML_TILE_FLIP) != 0 else 1
	var origin = Vector2(source_rect.size.x if xscale < 0 else 0, source_rect.size.y if yscale < 0 else 0)
	return {
		"texture": texture,
		"source": source_rect,
		"xscale": xscale,
		"yscale": yscale,
		"rotation": 90 if (tile_value & GML_TILE_ROTATE) != 0 else 0,
		"origin": origin
	}


static func _gml_draw_tileset_resource(tileset):
	_gml_asset_registry_ensure_loaded()
	var raw_entry = _gml_asset_resolve(tileset)
	if typeof(raw_entry) != TYPE_DICTIONARY:
		return null
	var entry: Dictionary = raw_entry
	if str(entry.get("type", "")) != "tileset":
		return null
	var asset_id = int(entry.get("id", -1))
	if _gml_draw_tileset_cache.has(asset_id):
		return _gml_draw_tileset_cache[asset_id]
	var resource = entry.get("resource", null)
	if resource == null and str(entry.get("godot_path", "")) != "":
		resource = load(str(entry.get("godot_path", "")))
	if resource is TileSet:
		_gml_draw_tileset_cache[asset_id] = resource
		return resource
	return null


static func _gml_draw_text_at(x, y, text, sep, width):
	var target = _gml_draw_target()
	if target == null:
		return
	var font_info = _gml_draw_font_info()
	var font = font_info["font"]
	var font_size = int(font_info["font_size"])
	var text_value = gml_string(text)
	var lines = _gml_draw_wrapped_lines(text_value, font, font_size, sep, width)
	var metrics = _gml_draw_line_metrics(lines, font, font_size, sep)
	var top_left = _gml_draw_aligned_text_origin(Vector2(_to_real(x), _to_real(y)), metrics)
	var line_step = _gml_draw_line_step(font, font_size, sep)
	var baseline_y = top_left.y + font.get_ascent(font_size)
	for line in lines:
		var line_width = font.get_string_size(line, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
		var line_x = top_left.x
		if int(_gml_draw_state["halign"]) == GML_FA_CENTER:
			line_x -= line_width * 0.5
		elif int(_gml_draw_state["halign"]) == GML_FA_RIGHT:
			line_x -= line_width
		target.draw_string(font, Vector2(line_x, baseline_y), line, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, _gml_draw_current_color())
		baseline_y += line_step


static func _gml_draw_text_metrics(text, sep, width):
	var font_info = _gml_draw_font_info()
	var font = font_info["font"]
	var font_size = int(font_info["font_size"])
	var lines = _gml_draw_wrapped_lines(gml_string(text), font, font_size, sep, width)
	return _gml_draw_line_metrics(lines, font, font_size, sep)


static func _gml_draw_line_metrics(lines, font, font_size, sep):
	var max_width = 0.0
	for line in lines:
		max_width = max(max_width, font.get_string_size(line, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x)
	var height = font.get_height(font_size)
	if lines.size() > 1:
		height += _gml_draw_line_step(font, font_size, sep) * float(lines.size() - 1)
	return Vector2(max_width, height)


static func _gml_draw_line_step(font, font_size, sep):
	var base_height = max(font.get_height(font_size), 1.0)
	if is_numeric(sep) and _to_real(sep) >= 0.0:
		return base_height + _to_real(sep)
	return base_height


static func _gml_draw_aligned_text_origin(position, metrics):
	var origin = position
	if int(_gml_draw_state["valign"]) == GML_FA_MIDDLE:
		origin.y -= metrics.y * 0.5
	elif int(_gml_draw_state["valign"]) == GML_FA_BOTTOM:
		origin.y -= metrics.y
	return origin


static func _gml_draw_wrapped_lines(text, font, font_size, sep, width):
	var wrap_width = _to_real(width) if is_numeric(width) else -1.0
	var lines = []
	for paragraph in str(text).split("\n"):
		if wrap_width < 0.0:
			lines.append(str(paragraph))
		else:
			lines.append_array(_gml_draw_wrap_paragraph(str(paragraph), font, font_size, wrap_width))
	if lines.is_empty():
		lines.append("")
	return lines


static func _gml_draw_wrap_paragraph(paragraph, font, font_size, width):
	if paragraph == "":
		return [""]
	var words = paragraph.split(" ", false)
	if words.is_empty():
		return [paragraph]
	var lines = []
	var current = ""
	for word in words:
		var candidate = word if current == "" else current + " " + word
		if current != "" and font.get_string_size(candidate, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x > width:
			lines.append(current)
			current = word
		else:
			current = candidate
	if current != "":
		lines.append(current)
	return lines


static func _gml_draw_font_info():
	var font_value = _gml_draw_state["font"]
	if is_undefined(font_value) or (is_numeric(font_value) and int(_to_real(font_value)) == -1):
		return _gml_draw_default_font_info()
	var key = str(font_value)
	if _gml_draw_font_cache.has(key):
		return _gml_draw_font_cache[key]
	_gml_asset_registry_ensure_loaded()
	var raw_entry = _gml_asset_resolve(font_value)
	if typeof(raw_entry) != TYPE_DICTIONARY:
		return _gml_draw_default_font_info()
	var entry: Dictionary = raw_entry
	if str(entry.get("type", "")) != "font":
		return _gml_draw_default_font_info()
	var resource = entry.get("resource", null)
	if resource == null and str(entry.get("godot_path", "")) != "":
		resource = load(str(entry.get("godot_path", "")))
	if not (resource is Font):
		return _gml_draw_default_font_info()
	var info = {
		"font": resource,
		"font_size": ThemeDB.fallback_font_size,
		"asset": int(entry.get("id", -1))
	}
	_gml_draw_font_cache[key] = info
	return info


static func _gml_draw_default_font_info():
	return {
		"font": ThemeDB.fallback_font,
		"font_size": ThemeDB.fallback_font_size if ThemeDB.fallback_font_size > 0 else GML_DRAW_DEFAULT_FONT_SIZE,
		"asset": -1
	}


static func _gml_object_get(object_value, member_name, fallback):
	if object_value == null:
		return fallback
	var value = gml_variable_instance_get(object_value, member_name)
	if is_undefined(value):
		return fallback
	return value


static func _gml_draw_is_no_sprite(sprite):
	if is_undefined(sprite) or sprite == null:
		return true
	if is_numeric(sprite) and int(_to_real(sprite)) == -1:
		return true
	return false


static func _gml_draw_room_size():
	var width = 0.0
	var height = 0.0
	if _gml_builtin_globals.has("room_width"):
		width = _to_real(_gml_builtin_globals["room_width"])
	if _gml_builtin_globals.has("room_height"):
		height = _to_real(_gml_builtin_globals["room_height"])
	var target = _gml_draw_target()
	if target != null and (width <= 0.0 or height <= 0.0):
		var viewport_size = target.get_viewport_rect().size
		width = viewport_size.x if width <= 0.0 else width
		height = viewport_size.y if height <= 0.0 else height
	if width <= 0.0:
		width = 4096.0
	if height <= 0.0:
		height = 4096.0
	return Vector2(width, height)


static func _gml_draw_state_copy():
	return {
		"color": _gml_draw_state["color"],
		"alpha": _gml_draw_state["alpha"],
		"line_width": _gml_draw_state["line_width"],
		"font": _gml_draw_state["font"],
		"halign": _gml_draw_state["halign"],
		"valign": _gml_draw_state["valign"],
		"blend_mode": _gml_draw_state["blend_mode"]
	}
