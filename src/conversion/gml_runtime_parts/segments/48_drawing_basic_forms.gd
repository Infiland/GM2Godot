const GML_DRAW_DEFAULT_FONT_SIZE = 16
const GML_FA_LEFT = 0
const GML_FA_CENTER = 1
const GML_FA_RIGHT = 2
const GML_FA_TOP = 0
const GML_FA_MIDDLE = 1
const GML_FA_BOTTOM = 2
const GML_TEXTURE_HANDLE_KIND = "texture"
const GML_SHADER_UNIFORM_HANDLE_KIND = "shader_uniform"
const GML_BLEND_NORMAL = 0
const GML_BLEND_ADD = 1
const GML_BLEND_MAX = 2
const GML_BLEND_SUBTRACT = 3
const GML_BLEND_MIN = 4
const GML_BLEND_REVERSE_SUBTRACT = 5
const GML_CULL_NO_CULLING = 0
const GML_CULL_CLOCKWISE = 1
const GML_CULL_COUNTERCLOCKWISE = 2
const GML_TEXTUREGROUP_STATUS_UNLOADED = 0
const GML_TEXTUREGROUP_STATUS_LOADING = 1
const GML_TEXTUREGROUP_STATUS_LOADED = 2
const GML_TEXTUREGROUP_STATUS_FETCHED = 3
const GML_VIDEO_MANAGER_NODE_NAME = "_GM2GodotVideoRuntime"
const GML_VIDEO_STATUS_CLOSED = 0
const GML_VIDEO_STATUS_PREPARING = 1
const GML_VIDEO_STATUS_PLAYING = 2
const GML_VIDEO_STATUS_PAUSED = 3
const GML_VIDEO_FORMAT_RGBA = 0
const GML_VIDEO_FORMAT_YUV = 1
const GML_DRAW_TILED_LIMIT = 65536
const GML_DRAW_EVENT_PHASES = [
	{"phase": "pre_draw", "method": "_on_pre_draw"},
	{"phase": "draw_begin", "method": "_on_draw_begin"},
	{"phase": "draw", "method": "_on_draw"},
	{"phase": "draw_end", "method": "_on_draw_end"},
	{"phase": "post_draw", "method": "_on_post_draw"},
	{"phase": "draw_gui_begin", "method": "_on_draw_gui_begin"},
	{"phase": "draw_gui", "method": "_on_draw_gui"},
	{"phase": "draw_gui_end", "method": "_on_draw_gui_end"},
]

static var _gml_draw_context_stack = []
static var _gml_draw_event_trace = []
static var _gml_draw_sprite_cache = {}
static var _gml_draw_font_cache = {}
static var _gml_draw_tileset_cache = {}
static var _gml_shader_material_cache = {}
static var _gml_shader_uniform_cache = {}
static var _gml_texturegroup_status = {}
static var _gml_texturegroup_mode = {
	"explicit": false,
	"debug": false,
	"default_sprite": -1,
	"global_scale": 1
}
static var _gml_video_state = {
	"player": null,
	"status": GML_VIDEO_STATUS_CLOSED,
	"format": GML_VIDEO_FORMAT_RGBA,
	"volume": 1.0,
	"loop": false,
	"source": "",
	"surface_handle": null
}
static var _gml_video_diagnostics = []
static var _gml_draw_state = {
	"color": 0xffffff,
	"alpha": 1.0,
	"line_width": 1.0,
	"font": -1,
	"halign": GML_FA_LEFT,
	"valign": GML_FA_TOP,
	"blend_mode": GML_BLEND_NORMAL,
	"blend_mode_ext": [GML_BLEND_NORMAL, GML_BLEND_NORMAL],
	"texture_filter": false,
	"texture_repeat": false,
	"color_write": [true, true, true, true],
	"cull_mode": GML_CULL_NO_CULLING,
	"alpha_test_enabled": false,
	"alpha_test_ref": 0.0,
	"shader": null,
	"shader_material": null,
	"circle_precision": 24,
	"legacy_primitives": true
}
static var _gml_draw_defaults_resolved = false


# draw_self and the default Draw event draw the instance's sprite with its
# image_* values at the instance position, in room coordinates.
static func gml_draw_self(instance):
	if instance == null:
		return null
	var sprite = _gml_draw_instance_value(instance, "sprite_index", -1)
	if _gml_draw_is_no_sprite(sprite):
		return null
	var position = _gml_draw_instance_position(instance)
	return gml_draw_sprite_ext(
		sprite,
		_gml_draw_instance_value(instance, "image_index", 0),
		position.x,
		position.y,
		_gml_draw_instance_value(instance, "image_xscale", 1),
		_gml_draw_instance_value(instance, "image_yscale", 1),
		_gml_draw_instance_value(instance, "image_angle", 0),
		_gml_draw_instance_value(instance, "image_blend", 0xffffff),
		_gml_draw_instance_value(instance, "image_alpha", 1)
	)


# draw_sprite and the other non-ext forms use white and the draw alpha;
# the _ext forms use their own colour and alpha (GameMaker ignores draw alpha).
static func gml_draw_sprite(sprite, subimg, x, y):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = Rect2(Vector2.ZERO, frame["size"])
	_gml_draw_texture_part(frame["texture"], source, x, y, 1, 1, 0, 0xffffff, 1, frame["origin"], true)
	return null


static func gml_draw_sprite_ext(sprite, subimg, x, y, xscale, yscale, rot, colour, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = Rect2(Vector2.ZERO, frame["size"])
	_gml_draw_texture_part(frame["texture"], source, x, y, xscale, yscale, rot, colour, alpha, frame["origin"])
	return null


static func gml_draw_sprite_part(sprite, subimg, left, top, width, height, x, y):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = _gml_draw_source_rect(left, top, width, height, frame["size"])
	_gml_draw_texture_part(frame["texture"], source, x, y, 1, 1, 0, 0xffffff, 1, Vector2.ZERO, true)
	return null


static func gml_draw_sprite_part_ext(sprite, subimg, left, top, width, height, x, y, xscale, yscale, colour, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = _gml_draw_source_rect(left, top, width, height, frame["size"])
	_gml_draw_texture_part(frame["texture"], source, x, y, xscale, yscale, 0, colour, alpha, Vector2.ZERO)
	return null


# The part's top-left corner lands on (x, y) and rotation turns around it; the
# four colours apply to the top-left, top-right, bottom-right and bottom-left
# corners.
static func gml_draw_sprite_general(sprite, subimg, left, top, width, height, x, y, xscale, yscale, rot, c1, c2, c3, c4, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var source = _gml_draw_source_rect(left, top, width, height, frame["size"])
	if source.size.x <= 0.0 or source.size.y <= 0.0:
		return null
	var origin = Vector2(_gml_draw_real(x), _gml_draw_real(y))
	var angle = deg_to_rad(-_gml_draw_real(rot))
	var across = Vector2(source.size.x * _gml_draw_real(xscale), 0.0).rotated(angle)
	var down = Vector2(0.0, source.size.y * _gml_draw_real(yscale)).rotated(angle)
	var points = PackedVector2Array([origin, origin + across, origin + across + down, origin + down])
	var colours = PackedColorArray([
		_gml_draw_colour_value(c1, alpha),
		_gml_draw_colour_value(c2, alpha),
		_gml_draw_colour_value(c3, alpha),
		_gml_draw_colour_value(c4, alpha),
	])
	_gml_draw_textured_quad(frame["texture"], source, points, colours)
	return null


# The four points are the top-left, top-right, bottom-right and bottom-left
# corners of the whole frame; the sprite origin is ignored.
static func gml_draw_sprite_pos(sprite, subimg, x1, y1, x2, y2, x3, y3, x4, y4, alpha):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var points = PackedVector2Array([
		Vector2(_gml_draw_real(x1), _gml_draw_real(y1)),
		Vector2(_gml_draw_real(x2), _gml_draw_real(y2)),
		Vector2(_gml_draw_real(x3), _gml_draw_real(y3)),
		Vector2(_gml_draw_real(x4), _gml_draw_real(y4)),
	])
	var colour = _gml_draw_colour_value(0xffffff, alpha)
	var colours = PackedColorArray([colour, colour, colour, colour])
	_gml_draw_textured_quad(frame["texture"], Rect2(Vector2.ZERO, frame["size"]), points, colours)
	return null


static func gml_draw_sprite_stretched(sprite, subimg, x, y, w, h):
	return _gml_draw_sprite_stretched(sprite, subimg, x, y, w, h, _gml_draw_colour_value(0xffffff, 1, true))


static func gml_draw_sprite_stretched_ext(sprite, subimg, x, y, w, h, colour, alpha):
	return _gml_draw_sprite_stretched(sprite, subimg, x, y, w, h, _gml_draw_colour_value(colour, alpha))


static func gml_draw_sprite_tiled(sprite, subimg, x, y):
	return _gml_draw_sprite_tiled(sprite, subimg, x, y, 1, 1, _gml_draw_colour_value(0xffffff, 1, true))


static func gml_draw_sprite_tiled_ext(sprite, subimg, x, y, xscale, yscale, colour, alpha):
	return _gml_draw_sprite_tiled(sprite, subimg, x, y, xscale, yscale, _gml_draw_colour_value(colour, alpha))


# Tiles are drawn with the draw colour and alpha, like GameMaker's tile layers.
static func gml_draw_tile(tileset, tiledata, frame, x, y):
	var target = _gml_draw_target()
	if target == null:
		return null
	var tile_set = _gml_draw_tileset_resource(tileset)
	if tile_set == null:
		return null
	var tile_value = int(_gml_draw_real(tiledata))
	var tile_index = tile_value & GML_TILEMAP_INDEX_MASK
	if tile_value == GML_TILEMAP_EMPTY_SENTINEL or tile_index <= 0:
		return null
	var layout = _gml_tilemap_atlas_layout(tile_set)
	if layout.is_empty():
		return null
	var atlas_index = tile_index - 1
	var columns = int(layout["columns"])
	var atlas_coords = Vector2i(atlas_index % columns, int(floor(float(atlas_index) / float(columns))))
	var source = layout["source"]
	if not source.has_tile(atlas_coords):
		return null
	var alternative = _gml_tilemap_transform_to_godot(tile_value)
	var frame_index = 0
	var frame_count = int(source.get_tile_animation_frames_count(atlas_coords))
	if frame_count > 1:
		frame_index = posmod(int(floor(_gml_draw_real(frame))), frame_count)
	var region = source.get_tile_texture_region(atlas_coords, frame_index)
	var colour = _gml_draw_colour_value(_gml_draw_state["color"], 1, true)
	_gml_draw_tile_region(target, source.texture, region, Vector2(_gml_draw_real(x), _gml_draw_real(y)), alternative, colour)
	return null


# Draws every cell of a tilemap layer element with its top-left corner at
# (x, y), as well as the layer's own rendering.
static func gml_draw_tilemap(tilemap_element_id, x, y):
	var target = _gml_draw_target()
	if target == null:
		return null
	var node = _gml_layer_element_resolve_node(tilemap_element_id)
	if not (node is TileMapLayer) or not (node.tile_set is TileSet):
		return null
	var tile_set = node.tile_set
	var tile_size = Vector2(tile_set.tile_size)
	var origin = Vector2(_to_real(x), _to_real(y))
	var colour = _gml_draw_colour_value(0xffffff, 1, true) * node.self_modulate
	for coords in node.get_used_cells():
		var source = tile_set.get_source(node.get_cell_source_id(coords))
		if not (source is TileSetAtlasSource) or source.texture == null:
			continue
		var atlas_coords = node.get_cell_atlas_coords(coords)
		var region = source.get_tile_texture_region(atlas_coords)
		var cell_position = origin + Vector2(coords) * tile_size
		_gml_draw_tile_region(target, source.texture, region, cell_position, node.get_cell_alternative_tile(coords), colour)
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
	_gml_draw_text_with(x, y, text, -1, -1, xscale, yscale, angle, null)
	return null


static func gml_draw_text_ext_transformed(x, y, text, sep, width, xscale, yscale, angle):
	_gml_draw_text_with(x, y, text, sep, width, xscale, yscale, angle, null)
	return null


static func gml_draw_text_color(x, y, text, c1, c2, c3, c4, alpha):
	_gml_draw_text_with(x, y, text, -1, -1, 1, 1, 0, [c1, c2, c3, c4, alpha])
	return null


static func gml_draw_text_ext_color(x, y, text, sep, width, c1, c2, c3, c4, alpha):
	_gml_draw_text_with(x, y, text, sep, width, 1, 1, 0, [c1, c2, c3, c4, alpha])
	return null


static func gml_draw_text_transformed_color(x, y, text, xscale, yscale, angle, c1, c2, c3, c4, alpha):
	_gml_draw_text_with(x, y, text, -1, -1, xscale, yscale, angle, [c1, c2, c3, c4, alpha])
	return null


static func gml_draw_text_ext_transformed_color(x, y, text, sep, width, xscale, yscale, angle, c1, c2, c3, c4, alpha):
	_gml_draw_text_with(x, y, text, sep, width, xscale, yscale, angle, [c1, c2, c3, c4, alpha])
	return null


# Transformed text scales and rotates (counter-clockwise degrees) around (x, y).
# The colour forms draw with their own colour and alpha instead of the draw
# colour and alpha; text is drawn in one colour, so the four corner colours
# are averaged.
static func _gml_draw_text_with(x, y, text, sep, width, xscale, yscale, angle, colours):
	var target = _gml_draw_target()
	if target == null:
		return
	var saved_colour = _gml_draw_state["color"]
	var saved_alpha = _gml_draw_state["alpha"]
	if colours is Array:
		_gml_draw_state["color"] = _gml_draw_average_colour_value([colours[0], colours[1], colours[2], colours[3]])
		_gml_draw_state["alpha"] = clamp(_to_real(colours[4]), 0.0, 1.0)
	var previous = target.transform
	var scale = Vector2(_to_real(xscale), _to_real(yscale))
	var rotation = _to_real(angle)
	if scale == Vector2.ONE and rotation == 0.0:
		_gml_draw_text_at(x, y, text, sep, width)
	else:
		target.draw_set_transform_matrix(previous * Transform2D(deg_to_rad(-rotation), scale, 0.0, Vector2(_to_real(x), _to_real(y))))
		_gml_draw_text_at(0, 0, text, sep, width)
		target.draw_set_transform_matrix(previous)
	_gml_draw_state["color"] = saved_colour
	_gml_draw_state["alpha"] = saved_alpha


static func _gml_draw_average_colour_value(colours):
	var red = 0
	var green = 0
	var blue = 0
	for colour in colours:
		var value = int(_to_real(colour))
		red += value & 0xff
		green += (value >> 8) & 0xff
		blue += (value >> 16) & 0xff
	var count = max(colours.size(), 1)
	return int(round(float(red) / count)) | (int(round(float(green) / count)) << 8) | (int(round(float(blue) / count)) << 16)


static func gml_string_width(text):
	return _gml_draw_text_metrics(text, -1, -1).x


static func gml_string_height(text):
	return _gml_draw_text_metrics(text, -1, -1).y


static func gml_string_width_ext(text, sep, width):
	return _gml_draw_text_metrics(text, sep, width).x


static func gml_string_height_ext(text, sep, width):
	return _gml_draw_text_metrics(text, sep, width).y


static func gml_draw_set_color(color):
	_gml_draw_defaults_resolve()
	_gml_draw_state["color"] = int(_gml_draw_real(color))
	return null


static func gml_draw_get_color():
	_gml_draw_defaults_resolve()
	return _gml_draw_state["color"]


static func gml_draw_set_alpha(alpha):
	_gml_draw_state["alpha"] = clamp(_gml_draw_real(alpha), 0.0, 1.0)
	return null


static func gml_draw_get_alpha():
	return _gml_draw_state["alpha"]


static func gml_draw_set_line_width(width):
	_gml_draw_state["line_width"] = max(_gml_draw_real(width), 1.0)
	return null


static func gml_draw_get_line_width():
	return _gml_draw_state["line_width"]


static func gml_gpu_set_blendmode(mode):
	_gml_draw_state["blend_mode"] = int(_to_real(mode))
	_gml_draw_apply_gpu_state()
	return null


static func gml_gpu_get_blendmode():
	return int(_gml_draw_state["blend_mode"])


static func gml_draw_set_blend_mode(mode):
	return gml_gpu_set_blendmode(mode)


static func gml_draw_get_blend_mode():
	return gml_gpu_get_blendmode()


static func gml_gpu_set_texfilter(linear):
	_gml_draw_defaults_resolve()
	_gml_draw_state["texture_filter"] = gml_bool(linear)
	_gml_draw_apply_gpu_state()
	return null


static func gml_gpu_get_texfilter():
	_gml_draw_defaults_resolve()
	return bool(_gml_draw_state["texture_filter"])


static func gml_texture_set_interpolation(linear):
	return gml_gpu_set_texfilter(linear)


static func gml_texture_get_interpolation():
	return gml_gpu_get_texfilter()


static func gml_gpu_set_texrepeat(repeat):
	_gml_draw_state["texture_repeat"] = gml_bool(repeat)
	_gml_draw_apply_gpu_state()
	return null


static func gml_gpu_get_texrepeat():
	return bool(_gml_draw_state["texture_repeat"])


static func gml_texture_set_repeat(repeat):
	return gml_gpu_set_texrepeat(repeat)


static func gml_texture_get_repeat():
	return gml_gpu_get_texrepeat()


# Takes the four channel flags, or one array of them like the one
# gpu_get_colourwriteenable returns.
static func gml_gpu_set_colorwriteenable(red, green = true, blue = true, alpha = true):
	var channels = red if red is Array else [red, green, blue, alpha]
	var flags = []
	for index in range(4):
		flags.append(gml_bool(channels[index]) if index < channels.size() else true)
	_gml_draw_state["color_write"] = flags
	return null


static func gml_gpu_get_colorwriteenable():
	var state = _gml_draw_state["color_write"]
	return [bool(state[0]), bool(state[1]), bool(state[2]), bool(state[3])]


static func gml_gpu_set_cullmode(mode):
	_gml_draw_state["cull_mode"] = int(_to_real(mode))
	return null


static func gml_gpu_get_cullmode():
	return int(_gml_draw_state["cull_mode"])


static func gml_gpu_set_alphatestenable(enable):
	_gml_draw_state["alpha_test_enabled"] = gml_bool(enable)
	return null


static func gml_gpu_get_alphatestenable():
	return bool(_gml_draw_state["alpha_test_enabled"])


static func gml_gpu_set_alphatestref(reference):
	_gml_draw_state["alpha_test_ref"] = clamp(_to_real(reference), 0.0, 255.0) / 255.0
	return null


static func gml_gpu_get_alphatestref():
	return int(round(_to_real(_gml_draw_state["alpha_test_ref"]) * 255.0))


static func gml_sprite_get_texture(sprite, subimg):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return gml_handle_invalid(GML_TEXTURE_HANDLE_KIND)
	return gml_handle_register(GML_TEXTURE_HANDLE_KIND, frame["texture"])


static func gml_sprite_get_uvs(sprite, subimg):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return []
	return _gml_texture_uvs(frame["texture"])


static func gml_sprite_get_width(sprite):
	var data = _gml_draw_sprite_data(sprite)
	if data == null:
		return 0
	if data.has("size"):
		return int(data["size"].x)
	var textures = data["textures"]
	if textures.is_empty() or textures[0] == null:
		return 0
	return int(textures[0].get_width())


static func gml_sprite_get_height(sprite):
	var data = _gml_draw_sprite_data(sprite)
	if data == null:
		return 0
	if data.has("size"):
		return int(data["size"].y)
	var textures = data["textures"]
	if textures.is_empty() or textures[0] == null:
		return 0
	return int(textures[0].get_height())


static func gml_sprite_set_offset(sprite, xoff, yoff):
	var data = _gml_draw_sprite_data(sprite)
	if data != null:
		data["origin"] = Vector2(_to_real(xoff), _to_real(yoff))
		data.erase("frames")
	return null


static func gml_sprite_delete(sprite):
	return gml_asset_release(sprite)


static func gml_surface_get_texture(surface):
	var resolved_surface = _gml_surface_resolve(surface)
	if resolved_surface == null:
		return gml_handle_invalid(GML_TEXTURE_HANDLE_KIND)
	return gml_handle_register(GML_TEXTURE_HANDLE_KIND, resolved_surface["texture"])


static func gml_texture_exists(texture):
	return _gml_texture_resolve(texture) != null


static func gml_texture_get_width(texture):
	var resolved_texture = _gml_texture_resolve(texture)
	if resolved_texture == null:
		return 0
	return int(resolved_texture.get_width())


static func gml_texture_get_height(texture):
	var resolved_texture = _gml_texture_resolve(texture)
	if resolved_texture == null:
		return 0
	return int(resolved_texture.get_height())


static func gml_texture_get_texel_width(texture):
	var width = gml_texture_get_width(texture)
	if width <= 0:
		return 0.0
	return 1.0 / float(width)


static func gml_texture_get_texel_height(texture):
	var height = gml_texture_get_height(texture)
	if height <= 0:
		return 0.0
	return 1.0 / float(height)


static func gml_texture_get_uvs(texture):
	var resolved_texture = _gml_texture_resolve(texture)
	if resolved_texture == null:
		return []
	return _gml_texture_uvs(resolved_texture)


static func gml_texture_is_ready(texture):
	return gml_texture_exists(texture)


static func gml_texture_prefetch(texture):
	return gml_texture_exists(texture)


static func gml_texture_flush(texture):
	return gml_texture_exists(texture)


static func gml_sprite_prefetch(sprite):
	var entry = _gml_asset_resolve(sprite)
	if typeof(entry) == TYPE_DICTIONARY:
		var group = _gml_texturegroup_name_for_entry(entry)
		if group != "":
			_gml_texturegroup_status[group] = GML_TEXTUREGROUP_STATUS_FETCHED
	return _gml_draw_sprite_data(sprite) != null


static func gml_sprite_flush(sprite):
	var entry = _gml_asset_resolve(sprite)
	if typeof(entry) == TYPE_DICTIONARY:
		_gml_draw_sprite_cache.erase(int(entry.get("id", -1)))
	return _gml_asset_resolve(sprite) != null


static func gml_sprite_prefetch_multi(sprites):
	return _gml_sprite_texture_multi(sprites, true)


static func gml_sprite_flush_multi(sprites):
	return _gml_sprite_texture_multi(sprites, false)


static func gml_draw_texture_flush():
	_gml_draw_sprite_cache.clear()
	_gml_draw_tileset_cache.clear()
	return null


static func gml_draw_flush():
	return null


static func gml_texture_global_scale(pow2integer):
	_gml_texturegroup_mode["global_scale"] = max(1, int(_to_real(pow2integer)))
	return null


static func gml_texture_debug_messages(enable):
	_gml_texturegroup_mode["debug"] = gml_bool(enable)
	return null


static func gml_texturegroup_set_mode(explicit, debug = false, default_sprite = -1):
	_gml_texturegroup_mode["explicit"] = gml_bool(explicit)
	_gml_texturegroup_mode["debug"] = gml_bool(debug)
	_gml_texturegroup_mode["default_sprite"] = default_sprite
	return null


static func gml_texturegroup_load(groupname):
	var group = str(groupname)
	if not _gml_texturegroup_exists(group):
		return false
	_gml_texturegroup_status[group] = GML_TEXTUREGROUP_STATUS_LOADED
	return true


static func gml_texturegroup_unload(groupname):
	var group = str(groupname)
	if not _gml_texturegroup_exists(group):
		return false
	_gml_texturegroup_status[group] = GML_TEXTUREGROUP_STATUS_UNLOADED
	_gml_texturegroup_flush_assets(group)
	return true


static func gml_texturegroup_get_status(groupname):
	var group = str(groupname)
	if not _gml_texturegroup_names().has(group):
		return GML_TEXTUREGROUP_STATUS_UNLOADED
	return int(_gml_texturegroup_status.get(group, GML_TEXTUREGROUP_STATUS_FETCHED))


static func gml_texturegroup_get_names():
	return _gml_texturegroup_names()


static func gml_texturegroup_get_sprites(groupname):
	return _gml_texturegroup_asset_ids(groupname, "sprite")


static func gml_texturegroup_get_fonts(groupname):
	return _gml_texturegroup_asset_ids(groupname, "font")


static func gml_texturegroup_get_tilesets(groupname):
	return _gml_texturegroup_asset_ids(groupname, "tileset")


static func gml_texturegroup_get_textures(groupname):
	var textures = []
	for asset_id in _gml_texturegroup_asset_ids(groupname, "sprite"):
		var texture_handle = gml_sprite_get_texture(asset_id, 0)
		if gml_handle_is_valid(texture_handle):
			textures.append(texture_handle)
	return textures


static func gml_video_open(path):
	gml_video_close()
	var stream = _gml_video_stream_for_source(path)
	if stream == null:
		_gml_video_report_diagnostic("video_open", "Video source could not be resolved as a Godot VideoStream. Godot supports Ogg Theora by default; other formats need a GDExtension-backed VideoStream.")
		return null
	var player = VideoStreamPlayer.new()
	player.name = "_gm_video_player"
	player.visible = false
	player.expand = false
	player.stream = stream
	player.volume = _to_real(_gml_video_state.get("volume", 1.0))
	player.loop = bool(_gml_video_state.get("loop", false))
	player.finished.connect(func(): _gml_video_finished())
	var root = _gml_video_root_node()
	if root != null:
		root.add_child(player)
	_gml_video_state["player"] = player
	_gml_video_state["status"] = GML_VIDEO_STATUS_PREPARING
	_gml_video_state["format"] = GML_VIDEO_FORMAT_RGBA
	_gml_video_state["source"] = str(path)
	if player.is_inside_tree():
		player.play()
	else:
		player.call_deferred("play")
	_gml_video_state["status"] = GML_VIDEO_STATUS_PLAYING
	return null


static func gml_video_close():
	var player = _gml_video_player()
	if player != null:
		player.stop()
		if player.is_inside_tree():
			player.queue_free()
	var surface_handle = _gml_video_state.get("surface_handle", null)
	if gml_handle_is_valid(surface_handle):
		var surface = surface_handle.reference
		if typeof(surface) == TYPE_DICTIONARY:
			surface["valid"] = false
		gml_handle_invalidate(surface_handle)
	_gml_video_state["player"] = null
	_gml_video_state["surface_handle"] = null
	_gml_video_state["status"] = GML_VIDEO_STATUS_CLOSED
	_gml_video_state["source"] = ""
	return null


static func gml_video_draw():
	var player = _gml_video_player()
	if player == null:
		return [-1]
	var texture = player.get_video_texture()
	var surface_handle = _gml_video_surface_handle(texture)
	if not gml_handle_is_valid(surface_handle):
		return [-1]
	return [0, surface_handle]


static func gml_video_set_volume(volume):
	var volume_value = max(_to_real(volume), 0.0)
	_gml_video_state["volume"] = volume_value
	var player = _gml_video_player()
	if player != null:
		player.volume = volume_value
	return null


static func gml_video_pause():
	var player = _gml_video_player()
	if player == null:
		return null
	player.paused = true
	_gml_video_state["status"] = GML_VIDEO_STATUS_PAUSED
	return null


static func gml_video_resume():
	var player = _gml_video_player()
	if player == null:
		return null
	player.paused = false
	if not player.is_playing():
		player.play()
	_gml_video_state["status"] = GML_VIDEO_STATUS_PLAYING
	return null


static func gml_video_enable_loop(enable):
	var loop_enabled = gml_bool(enable)
	_gml_video_state["loop"] = loop_enabled
	var player = _gml_video_player()
	if player != null:
		player.loop = loop_enabled
	return null


static func gml_video_seek_to(position):
	var position_value = max(_to_real(position), 0.0)
	var player = _gml_video_player()
	if player != null:
		player.stream_position = position_value
	return null


static func gml_video_is_looping():
	var player = _gml_video_player()
	if player != null:
		return bool(player.loop)
	return bool(_gml_video_state.get("loop", false))


static func gml_video_get_volume():
	var player = _gml_video_player()
	if player != null:
		return _to_real(player.volume)
	return _to_real(_gml_video_state.get("volume", 1.0))


static func gml_video_get_duration():
	var player = _gml_video_player()
	if player == null:
		return 0.0
	return max(_to_real(player.get_stream_length()), 0.0)


static func gml_video_get_position():
	var player = _gml_video_player()
	if player == null:
		return 0.0
	return max(_to_real(player.stream_position), 0.0)


static func gml_video_get_status():
	var player = _gml_video_player()
	if player == null:
		return GML_VIDEO_STATUS_CLOSED
	if bool(player.paused):
		return GML_VIDEO_STATUS_PAUSED
	if player.is_playing() or int(_gml_video_state.get("status", GML_VIDEO_STATUS_CLOSED)) == GML_VIDEO_STATUS_PLAYING:
		return GML_VIDEO_STATUS_PLAYING
	return int(_gml_video_state.get("status", GML_VIDEO_STATUS_PREPARING))


static func gml_video_get_format():
	if _gml_video_player() == null:
		return GML_VIDEO_FORMAT_RGBA
	return int(_gml_video_state.get("format", GML_VIDEO_FORMAT_RGBA))


static func gml_video_runtime_diagnostics():
	return _gml_clone_value(_gml_video_diagnostics, 16)


static func gml_shader_set(shader):
	var material = _gml_shader_material(shader)
	if material == null:
		return false
	_gml_draw_state["shader"] = _gml_shader_entry(shader)
	_gml_draw_state["shader_material"] = material
	_gml_draw_apply_gpu_state()
	return true


static func gml_shader_reset():
	_gml_draw_state["shader"] = null
	_gml_draw_state["shader_material"] = null
	_gml_draw_apply_gpu_state()
	return null


static func gml_shader_get_name(shader):
	var entry = _gml_shader_entry(shader)
	if entry == null:
		return ""
	return str(entry["name"])


static func gml_shader_is_compiled(shader):
	return _gml_shader_resource(shader) != null


static func gml_shader_get_uniform(shader, uniform_name):
	return _gml_shader_uniform_handle(shader, uniform_name)


static func gml_shader_get_sampler_index(shader, sampler_name):
	return _gml_shader_uniform_handle(shader, sampler_name)


static func gml_shader_set_uniform_f(uniform, x, y = null, z = null, w = null):
	return _gml_shader_set_uniform_value(uniform, _gml_shader_uniform_float_value(x, y, z, w))


static func gml_shader_set_uniform_i(uniform, x, y = null, z = null, w = null):
	return _gml_shader_set_uniform_value(uniform, _gml_shader_uniform_int_value(x, y, z, w))


static func gml_shader_set_uniform_f_array(uniform, values):
	var array = PackedFloat32Array()
	for value in _gml_shader_uniform_array(values):
		array.append(_to_real(value))
	return _gml_shader_set_uniform_value(uniform, array)


static func gml_shader_set_uniform_i_array(uniform, values):
	var array = PackedInt32Array()
	for value in _gml_shader_uniform_array(values):
		array.append(int(_to_real(value)))
	return _gml_shader_set_uniform_value(uniform, array)


static func gml_shader_set_uniform_matrix(uniform):
	return _gml_shader_set_uniform_value(uniform, _gml_shader_current_matrix())


static func gml_texture_set_stage(uniform, texture):
	var resolved_texture = _gml_texture_resolve(texture)
	if resolved_texture == null:
		return false
	return _gml_shader_set_uniform_value(uniform, resolved_texture)


static func gml_draw_clear(color):
	if _gml_surface_clear_active_target(color, 1.0):
		return null
	_gml_draw_fill_target(color)
	return null


# The application surface is composited without blending, so a cleared screen
# shows the clear colour whatever its alpha.
static func gml_draw_clear_alpha(color, alpha):
	if _gml_surface_clear_active_target(color, alpha):
		return null
	_gml_draw_fill_target(color)
	return null


static func gml_draw_line(x1, y1, x2, y2):
	var colour = _gml_draw_current_color()
	_gml_draw_line_quad(x1, y1, x2, y2, 1.0, colour, colour)
	return null


static func gml_draw_line_width(x1, y1, x2, y2, width):
	var colour = _gml_draw_current_color()
	_gml_draw_line_quad(x1, y1, x2, y2, width, colour, colour)
	return null


static func gml_draw_line_color(x1, y1, x2, y2, col1, col2):
	_gml_draw_line_quad(x1, y1, x2, y2, 1.0, _gml_draw_colour_value(col1, 1, true), _gml_draw_colour_value(col2, 1, true))
	return null


static func gml_draw_line_width_color(x1, y1, x2, y2, width, col1, col2):
	_gml_draw_line_quad(x1, y1, x2, y2, width, _gml_draw_colour_value(col1, 1, true), _gml_draw_colour_value(col2, 1, true))
	return null


static func gml_draw_rectangle(x1, y1, x2, y2, outline):
	var colour = _gml_draw_current_color()
	_gml_draw_rectangle_shape(x1, y1, x2, y2, [colour, colour, colour, colour], gml_bool(outline))
	return null


# Corner colours are top-left, top-right, bottom-right and bottom-left; they
# blend across the rectangle like GameMaker's vertex colours.
static func gml_draw_rectangle_color(x1, y1, x2, y2, col1, col2, col3, col4, outline):
	var colours = [
		_gml_draw_colour_value(col1, 1, true),
		_gml_draw_colour_value(col2, 1, true),
		_gml_draw_colour_value(col3, 1, true),
		_gml_draw_colour_value(col4, 1, true),
	]
	_gml_draw_rectangle_shape(x1, y1, x2, y2, colours, gml_bool(outline))
	return null


static func gml_draw_roundrect(x1, y1, x2, y2, outline):
	var colour = _gml_draw_current_color()
	_gml_draw_roundrect_shape(x1, y1, x2, y2, null, null, colour, colour, gml_bool(outline))
	return null


static func gml_draw_roundrect_ext(x1, y1, x2, y2, xrad, yrad, outline):
	var colour = _gml_draw_current_color()
	_gml_draw_roundrect_shape(x1, y1, x2, y2, xrad, yrad, colour, colour, gml_bool(outline))
	return null


static func gml_draw_roundrect_color(x1, y1, x2, y2, col1, col2, outline):
	_gml_draw_roundrect_shape(x1, y1, x2, y2, null, null, _gml_draw_colour_value(col1, 1, true), _gml_draw_colour_value(col2, 1, true), gml_bool(outline))
	return null


static func gml_draw_roundrect_color_ext(x1, y1, x2, y2, xrad, yrad, col1, col2, outline):
	_gml_draw_roundrect_shape(x1, y1, x2, y2, xrad, yrad, _gml_draw_colour_value(col1, 1, true), _gml_draw_colour_value(col2, 1, true), gml_bool(outline))
	return null


static func gml_draw_circle(x, y, radius, outline):
	var colour = _gml_draw_current_color()
	var r = abs(_gml_draw_real(radius))
	_gml_draw_ellipse_shape(_gml_draw_real(x), _gml_draw_real(y), r, r, colour, colour, gml_bool(outline))
	return null


# The centre takes the first colour and the edge the second.
static func gml_draw_circle_color(x, y, radius, col1, col2, outline):
	var r = abs(_gml_draw_real(radius))
	_gml_draw_ellipse_shape(_gml_draw_real(x), _gml_draw_real(y), r, r, _gml_draw_colour_value(col1, 1, true), _gml_draw_colour_value(col2, 1, true), gml_bool(outline))
	return null


static func gml_draw_ellipse(x1, y1, x2, y2, outline):
	var colour = _gml_draw_current_color()
	_gml_draw_ellipse_in_rect(x1, y1, x2, y2, colour, colour, gml_bool(outline))
	return null


static func gml_draw_ellipse_color(x1, y1, x2, y2, col1, col2, outline):
	_gml_draw_ellipse_in_rect(x1, y1, x2, y2, _gml_draw_colour_value(col1, 1, true), _gml_draw_colour_value(col2, 1, true), gml_bool(outline))
	return null


static func gml_draw_set_circle_precision(precision):
	var value = int(_to_real(precision))
	value = clamp(value - value % 4, 4, 64)
	_gml_draw_state["circle_precision"] = value
	return null


static func gml_draw_triangle(x1, y1, x2, y2, x3, y3, outline):
	var colour = _gml_draw_current_color()
	_gml_draw_triangle_shape(x1, y1, x2, y2, x3, y3, [colour, colour, colour], gml_bool(outline))
	return null


static func gml_draw_triangle_color(x1, y1, x2, y2, x3, y3, col1, col2, col3, outline):
	var colours = [
		_gml_draw_colour_value(col1, 1, true),
		_gml_draw_colour_value(col2, 1, true),
		_gml_draw_colour_value(col3, 1, true),
	]
	_gml_draw_triangle_shape(x1, y1, x2, y2, x3, y3, colours, gml_bool(outline))
	return null


static func gml_draw_point(x, y):
	_gml_draw_point_colour(x, y, _gml_draw_current_color())
	return null


static func gml_draw_point_color(x, y, col1):
	_gml_draw_point_colour(x, y, _gml_draw_colour_value(col1, 1, true))
	return null


static func gml_draw_arrow(x1, y1, x2, y2, size):
	var start = Vector2(_gml_draw_real(x1), _gml_draw_real(y1))
	var finish = Vector2(_gml_draw_real(x2), _gml_draw_real(y2))
	var length = start.distance_to(finish)
	if length <= 0.0:
		return null
	var colour = _gml_draw_current_color()
	_gml_draw_line_quad(start.x, start.y, finish.x, finish.y, 1.0, colour, colour)
	var head = min(abs(_gml_draw_real(size)), length)
	var direction = (finish - start) / length
	var normal = Vector2(-direction.y, direction.x)
	var base = finish - direction * head
	var points = [finish, base + normal * head / 3.0, base - normal * head / 3.0]
	_gml_draw_triangle_shape(points[0].x, points[0].y, points[1].x, points[1].y, points[2].x, points[2].y, [colour, colour, colour], false)
	return null


# Health bars fill from `direction` (0 left, 1 right, 2 top, 3 bottom) with a
# colour blended from mincol to maxcol by amount (0..100).
static func gml_draw_healthbar(x1, y1, x2, y2, amount, backcol, mincol, maxcol, direction, showback, showborder):
	var left = _gml_draw_real(x1)
	var top = _gml_draw_real(y1)
	var right = _gml_draw_real(x2)
	var bottom = _gml_draw_real(y2)
	var black = _gml_draw_colour_value(0x000000, 1, true)
	var black_corners = [black, black, black, black]
	if gml_bool(showback):
		var back = _gml_draw_colour_value(backcol, 1, true)
		_gml_draw_rectangle_shape(left, top, right, bottom, [back, back, back, back], false)
		if gml_bool(showborder):
			_gml_draw_rectangle_shape(left, top, right, bottom, black_corners, true)
	var resolved_amount = clamp(_gml_draw_real(amount), 0.0, 100.0)
	var fraction = resolved_amount / 100.0
	var bar = [left, top, left + fraction * (right - left), bottom]
	match int(_gml_draw_real(direction)):
		1:
			bar = [right - fraction * (right - left), top, right, bottom]
		2:
			bar = [left, top, right, top + fraction * (bottom - top)]
		3:
			bar = [left, bottom - fraction * (bottom - top), right, bottom]
	var middle = _gml_draw_merge_colour(mincol, maxcol, 0.5)
	var bar_colour = _gml_draw_merge_colour(middle, maxcol, (resolved_amount - 50.0) / 50.0)
	if resolved_amount <= 50.0:
		bar_colour = _gml_draw_merge_colour(mincol, middle, resolved_amount / 50.0)
	var fill = _gml_draw_colour_value(bar_colour, 1, true)
	_gml_draw_rectangle_shape(bar[0], bar[1], bar[2], bar[3], [fill, fill, fill, fill], false)
	if gml_bool(showborder):
		_gml_draw_rectangle_shape(bar[0], bar[1], bar[2], bar[3], black_corners, true)
	return null


static func _gml_draw_current_color():
	return _gml_draw_colour_value(_gml_draw_state["color"], 1, true)


static func _gml_draw_color(color):
	return _gml_draw_colour_value(color, 1, true)


# A colour whose alpha is multiplied by the draw alpha (draw_set_alpha).
static func _gml_draw_modulate(color, alpha):
	return _gml_draw_colour_value(color, alpha, true)


# GameMaker colours are 0xBBGGRR integers. Draw functions that take their own
# alpha ignore the draw alpha; the others pass apply_global_alpha.
static func _gml_draw_colour_value(color, alpha, apply_global_alpha = false):
	var resolved_alpha = _gml_draw_real(alpha)
	if apply_global_alpha:
		resolved_alpha *= _gml_draw_real(_gml_draw_state["alpha"])
	var colour_value = Color(1.0, 1.0, 1.0, 1.0)
	if color is Color:
		colour_value = color
	else:
		var value = int(_gml_draw_real(color))
		colour_value = Color(
			float(value & 0xff) / 255.0,
			float((value >> 8) & 0xff) / 255.0,
			float((value >> 16) & 0xff) / 255.0,
			1.0
		)
	colour_value.a = clamp(resolved_alpha, 0.0, 1.0)
	return _gml_draw_apply_colour_write(colour_value)


# Canvas items cannot mask colour channels, so a disabled red, green or blue
# write drops that channel's contribution and a fully disabled colour mask
# draws nothing. A disabled alpha write keeps normal blending: the screen has
# no destination alpha for it to protect.
static func _gml_draw_apply_colour_write(colour_value):
	var color_write = _gml_draw_state["color_write"]
	if color_write[0] and color_write[1] and color_write[2]:
		return colour_value
	if not bool(color_write[0]) and not bool(color_write[1]) and not bool(color_write[2]):
		colour_value.a = 0.0
		return colour_value
	if not bool(color_write[0]):
		colour_value.r = 0.0
	if not bool(color_write[1]):
		colour_value.g = 0.0
	if not bool(color_write[2]):
		colour_value.b = 0.0
	return colour_value


static func _gml_draw_merge_colour(col1, col2, amount):
	var first = int(_to_real(col1))
	var second = int(_to_real(col2))
	var factor = clamp(_to_real(amount), 0.0, 1.0)
	var merged = 0
	for shift in [0, 8, 16]:
		var start = (first >> shift) & 0xff
		var finish = (second >> shift) & 0xff
		merged |= (int(start + (finish - start) * factor) & 0xff) << shift
	return merged


static func _gml_draw_line_width():
	return max(_gml_draw_real(_gml_draw_state["line_width"]), 1.0)


# Legacy primitive drawing, GameMaker's behaviour for projects that predate the
# option, treats rectangle corners as inclusive pixels.
static func _gml_draw_primitive_extent():
	_gml_draw_defaults_resolve()
	return 1.0 if bool(_gml_draw_state["legacy_primitives"]) else 0.0


# Initial draw state that GameMaker takes from the game options: texture
# interpolation (written to Godot's default canvas texture filter), the draw
# colour and the primitive drawing mode.
static func _gml_draw_defaults_resolve():
	if _gml_draw_defaults_resolved:
		return
	_gml_draw_defaults_resolved = true
	var default_filter = int(ProjectSettings.get_setting("rendering/textures/canvas_textures/default_texture_filter", 1))
	_gml_draw_state["texture_filter"] = default_filter == 1 or default_filter == 2
	_gml_draw_state["legacy_primitives"] = bool(ProjectSettings.get_setting("gm2godot/draw/legacy_primitive_drawing", true))
	var initial_colour = ProjectSettings.get_setting("gm2godot/draw/initial_colour", null)
	if initial_colour != null and is_numeric(initial_colour):
		_gml_draw_state["color"] = int(initial_colour) & 0xffffff
	_gml_draw_apply_gpu_state()


static func _gml_draw_fill_target(color):
	var target = _gml_draw_target()
	if target == null:
		return
	var state = _gml_draw_gpu_state()
	target.set_gpu_state(-1, [null, state[1], state[2]])
	target.draw_rect(target.visible_region().grow(1.0), _gml_draw_colour_value(color, 1.0), true)
	target.set_gpu_state(_gml_draw_gpu_version, state)


# Lines are quads `width` wide through the pixel centres of the end points and
# reach half a pixel past the end point, so both end pixels are covered.
static func _gml_draw_line_quad(x1, y1, x2, y2, width, col1, col2):
	var target = _gml_draw_target()
	if target == null:
		return
	var start = Vector2(_gml_draw_real(x1) + 0.5, _gml_draw_real(y1) + 0.5)
	var finish = Vector2(_gml_draw_real(x2) + 0.5, _gml_draw_real(y2) + 0.5)
	var delta = finish - start
	var length = delta.length()
	if length < 0.0001:
		return
	var direction = delta / length
	finish += direction * 0.5
	var normal = Vector2(-direction.y, direction.x) * (abs(_gml_draw_real(width)) * 0.5)
	var points = PackedVector2Array([start - normal, finish - normal, finish + normal, start + normal])
	target.draw_triangles(points, PackedColorArray([col1, col2, col2, col1]), PackedVector2Array(), RID(), PackedInt32Array([0, 1, 2, 2, 3, 0]))


static func _gml_draw_rectangle_shape(x1, y1, x2, y2, colours, outline):
	var target = _gml_draw_target()
	if target == null:
		return
	var extent = _gml_draw_primitive_extent()
	var left = min(_gml_draw_real(x1), _gml_draw_real(x2))
	var top = min(_gml_draw_real(y1), _gml_draw_real(y2))
	var right = max(_gml_draw_real(x1), _gml_draw_real(x2)) + extent
	var bottom = max(_gml_draw_real(y1), _gml_draw_real(y2)) + extent
	var width = _gml_draw_line_width()
	if not outline or right - left <= width * 2.0 or bottom - top <= width * 2.0:
		var corners = PackedVector2Array([Vector2(left, top), Vector2(right, top), Vector2(right, bottom), Vector2(left, bottom)])
		target.draw_triangles(corners, PackedColorArray(colours), PackedVector2Array(), RID(), PackedInt32Array([0, 1, 2, 2, 3, 0]))
		return
	# Four non-overlapping edge strips inside the rectangle.
	var points = PackedVector2Array([
		Vector2(left, top), Vector2(right, top), Vector2(right, top + width), Vector2(left, top + width),
		Vector2(right - width, top + width), Vector2(right, top + width), Vector2(right, bottom - width), Vector2(right - width, bottom - width),
		Vector2(left, bottom - width), Vector2(right, bottom - width), Vector2(right, bottom), Vector2(left, bottom),
		Vector2(left, top + width), Vector2(left + width, top + width), Vector2(left + width, bottom - width), Vector2(left, bottom - width),
	])
	var tl = colours[0]
	var tr = colours[1]
	var br = colours[2]
	var bl = colours[3]
	var strip_colours = PackedColorArray([tl, tr, tr, tl, tr, tr, br, br, bl, br, br, bl, tl, tl, bl, bl])
	var indices = PackedInt32Array()
	for strip in range(4):
		var base = strip * 4
		indices.append_array([base, base + 1, base + 2, base + 2, base + 3, base])
	target.draw_triangles(points, strip_colours, PackedVector2Array(), RID(), indices)


static func _gml_draw_point_colour(x, y, colour):
	var target = _gml_draw_target()
	if target == null:
		return
	var corner = Vector2(_gml_draw_real(x), _gml_draw_real(y))
	var points = PackedVector2Array([corner, corner + Vector2(1, 0), corner + Vector2(1, 1), corner + Vector2(0, 1)])
	target.draw_triangles(points, PackedColorArray([colour]), PackedVector2Array(), RID(), PackedInt32Array([0, 1, 2, 2, 3, 0]))


static func _gml_draw_triangle_shape(x1, y1, x2, y2, x3, y3, colours, outline):
	var target = _gml_draw_target()
	if target == null:
		return
	var points = PackedVector2Array([
		Vector2(_gml_draw_real(x1), _gml_draw_real(y1)),
		Vector2(_gml_draw_real(x2), _gml_draw_real(y2)),
		Vector2(_gml_draw_real(x3), _gml_draw_real(y3)),
	])
	if not outline:
		target.draw_triangles(points, PackedColorArray(colours))
		return
	var width = _gml_draw_line_width()
	for edge in [[0, 1], [1, 2], [2, 0]]:
		var from_point = points[edge[0]]
		var to_point = points[edge[1]]
		_gml_draw_line_quad(from_point.x, from_point.y, to_point.x, to_point.y, width, colours[edge[0]], colours[edge[1]])


static func _gml_draw_circle_steps():
	return int(_gml_draw_state.get("circle_precision", 24))


static func _gml_draw_ellipse_in_rect(x1, y1, x2, y2, centre_colour, edge_colour, outline):
	var left = _gml_draw_real(x1)
	var top = _gml_draw_real(y1)
	var right = _gml_draw_real(x2)
	var bottom = _gml_draw_real(y2)
	_gml_draw_ellipse_shape((left + right) * 0.5, (top + bottom) * 0.5, abs(right - left) * 0.5, abs(bottom - top) * 0.5, centre_colour, edge_colour, outline)


# Circles and ellipses use draw_set_circle_precision segments: a fan from the
# centre colour to the edge colour, or an edge-coloured outline.
static func _gml_draw_ellipse_shape(cx, cy, rx, ry, centre_colour, edge_colour, outline):
	var target = _gml_draw_target()
	if target == null:
		return
	var steps = _gml_draw_circle_steps()
	var centre = Vector2(cx, cy)
	var rim = PackedVector2Array()
	for index in range(steps):
		var angle = TAU * float(index) / float(steps)
		rim.append(centre + Vector2(cos(angle) * rx, sin(angle) * ry))
	_gml_draw_fan_or_outline(target, centre, rim, centre_colour, edge_colour, outline)


static func _gml_draw_roundrect_shape(x1, y1, x2, y2, xrad, yrad, centre_colour, edge_colour, outline):
	var target = _gml_draw_target()
	if target == null:
		return
	var left = min(_gml_draw_real(x1), _gml_draw_real(x2))
	var top = min(_gml_draw_real(y1), _gml_draw_real(y2))
	var right = max(_gml_draw_real(x1), _gml_draw_real(x2))
	var bottom = max(_gml_draw_real(y1), _gml_draw_real(y2))
	var radius_x = min(abs(_gml_draw_real(xrad)) if xrad != null else 10.0, (right - left) * 0.5)
	var radius_y = min(abs(_gml_draw_real(yrad)) if yrad != null else 10.0, (bottom - top) * 0.5)
	var corner_steps = max(int(_gml_draw_circle_steps() / 4), 1)
	var centres = [
		Vector2(right - radius_x, top + radius_y),
		Vector2(left + radius_x, top + radius_y),
		Vector2(left + radius_x, bottom - radius_y),
		Vector2(right - radius_x, bottom - radius_y),
	]
	var rim = PackedVector2Array()
	for corner in range(4):
		for step in range(corner_steps + 1):
			var angle = (float(corner) + float(step) / float(corner_steps)) * PI * 0.5
			rim.append(centres[corner] + Vector2(cos(angle) * radius_x, -sin(angle) * radius_y))
	_gml_draw_fan_or_outline(target, Vector2((left + right) * 0.5, (top + bottom) * 0.5), rim, centre_colour, edge_colour, outline)


static func _gml_draw_fan_or_outline(target, centre, rim, centre_colour, edge_colour, outline):
	var count = rim.size()
	if count < 2:
		return
	if outline:
		var closed = PackedVector2Array(rim)
		closed.append(rim[0])
		target.draw_polyline(closed, edge_colour, _gml_draw_line_width())
		return
	var points = PackedVector2Array([centre])
	points.append_array(rim)
	var colours = PackedColorArray([centre_colour])
	for index in range(count):
		colours.append(edge_colour)
	var indices = PackedInt32Array()
	for index in range(count):
		indices.append_array([0, 1 + index, 1 + (index + 1) % count])
	target.draw_triangles(points, colours, PackedVector2Array(), RID(), indices)


# draw_self reads the instance's own members directly; dynamic members fall
# back to the GameMaker variable lookup.
static func _gml_draw_instance_value(instance, member_name, fallback):
	if instance is Object:
		var value = instance.get(member_name)
		if value != null:
			return value
	return _gml_object_get(instance, member_name, fallback)


static func _gml_draw_instance_position(instance):
	if instance is Node2D:
		if bool(instance.get_meta("gamemaker_in_sequence", false)):
			return instance.global_position
		return instance.position
	return Vector2(_gml_draw_real(_gml_object_get(instance, "x", 0)), _gml_draw_real(_gml_object_get(instance, "y", 0)))


static func _gml_draw_texture_part(texture, source, x, y, xscale, yscale, rot, colour, alpha, origin, apply_global_alpha = false):
	var colour_value = _gml_draw_colour_value(colour, alpha, apply_global_alpha)
	_gml_draw_texture_rect(texture, source, Vector2(_gml_draw_real(x), _gml_draw_real(y)), Vector2(_gml_draw_real(xscale), _gml_draw_real(yscale)), _gml_draw_real(rot), origin, colour_value)
	return null


# Draws `source` (texture pixels) so that `origin` (in source pixels) lands on
# `position`; scale and rotation (degrees, counter-clockwise on screen) apply
# around it.
static func _gml_draw_texture_rect(texture, source, position, scale, rot, origin, colour):
	var target = _gml_draw_target()
	if target == null or not (texture is Texture2D):
		return
	if not _gml_draw_alpha_test_passes(colour.a):
		return
	if scale.x == 0.0 or scale.y == 0.0 or source.size.x <= 0.0 or source.size.y <= 0.0:
		return
	var draw_origin = origin if origin is Vector2 else Vector2.ZERO
	if fmod(rot, 360.0) == 0.0 and not (texture is AtlasTexture):
		var corner = position - draw_origin * scale
		var size = source.size * scale
		# A negative size mirrors the texture inside the rect, which starts at the
		# smaller edge.
		var rect = Rect2(Vector2(min(corner.x, corner.x + size.x), min(corner.y, corner.y + size.y)), size)
		target.draw_texture_rect_region(texture, rect, source, colour, false, true)
		return
	var previous = target.transform
	target.draw_set_transform_matrix(previous * Transform2D(deg_to_rad(-rot), scale, 0.0, position))
	target.draw_texture_rect_region(texture, Rect2(-draw_origin, source.size), source, colour, false, true)
	target.draw_set_transform_matrix(previous)


# Draws `source` of `texture` onto the quad `points` (top-left, top-right,
# bottom-right, bottom-left) with per-corner colours.
static func _gml_draw_textured_quad(texture, source, points, colours):
	var target = _gml_draw_target()
	if target == null or not (texture is Texture2D):
		return
	if not _gml_draw_alpha_test_passes(colours[0].a):
		return
	var mapping = _gml_draw_texture_uv(texture, source)
	if mapping.is_empty():
		return
	var uv = mapping[1]
	var uvs = PackedVector2Array([uv.position, Vector2(uv.end.x, uv.position.y), uv.end, Vector2(uv.position.x, uv.end.y)])
	target.draw_triangles(points, colours, uvs, mapping[0], PackedInt32Array([0, 1, 2, 2, 3, 0]))


# Texture RID and normalized UV rect for raw vertex drawing; atlas textures map
# into their atlas.
static func _gml_draw_texture_uv(texture, source):
	var base = texture
	var region = source
	if texture is AtlasTexture and texture.atlas is Texture2D:
		base = texture.atlas
		region = Rect2(texture.region.position + source.position, source.size)
	var size = base.get_size()
	if size.x <= 0.0 or size.y <= 0.0:
		return []
	return [base.get_rid(), Rect2(region.position / size, region.size / size)]


static func _gml_draw_sprite_stretched(sprite, subimg, x, y, w, h, colour):
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var size = frame["size"]
	if size.x <= 0.0 or size.y <= 0.0:
		return null
	var scale = Vector2(_gml_draw_real(w), _gml_draw_real(h)) / size
	_gml_draw_texture_rect(frame["texture"], Rect2(Vector2.ZERO, size), Vector2(_gml_draw_real(x), _gml_draw_real(y)), scale, 0.0, Vector2.ZERO, colour)
	return null


# Tiles the frame over the visible part of the current draw space so that one
# tile's origin sits on (x, y), like GameMaker's view-sized tiling. A whole
# texture draws as one repeating rect; an atlas region draws a rect per tile.
static func _gml_draw_sprite_tiled(sprite, subimg, x, y, xscale, yscale, colour):
	var target = _gml_draw_target()
	if target == null or not _gml_draw_alpha_test_passes(colour.a):
		return null
	var frame = _gml_draw_sprite_frame(sprite, subimg)
	if frame == null:
		return null
	var size = frame["size"]
	var scale = Vector2(_gml_draw_real(xscale), _gml_draw_real(yscale))
	var step = (size * scale).abs()
	if step.x <= 0.0 or step.y <= 0.0:
		return null
	var region = target.visible_region()
	var anchor = Vector2(_gml_draw_real(x), _gml_draw_real(y)) - frame["origin"] * scale
	var corner = Vector2(
		_gml_draw_tiling_start(anchor.x, step.x, scale.x, region.position.x, region.end.x),
		_gml_draw_tiling_start(anchor.y, step.y, scale.y, region.position.y, region.end.y)
	)
	var columns = int(ceil(region.size.x / step.x)) + 1
	var rows = int(ceil(region.size.y / step.y)) + 1
	var texture = frame["texture"]
	var previous = target.transform
	target.draw_set_transform_matrix(previous * Transform2D(0.0, scale, 0.0, corner))
	if not (texture is AtlasTexture):
		target.draw_texture_repeated(texture, Rect2(Vector2.ZERO, size * Vector2(columns, rows)), colour)
	elif columns * rows <= GML_DRAW_TILED_LIMIT:
		var source = Rect2(Vector2.ZERO, size)
		for row in range(rows):
			for column in range(columns):
				target.draw_texture_rect_region(texture, Rect2(Vector2(column, row) * size, size), source, colour, false, true)
	target.draw_set_transform_matrix(previous)
	return null


# Where the tile corner holding texture coordinate 0 goes along one axis, so
# that tiles laid out in the scale's direction cover [low, high].
static func _gml_draw_tiling_start(anchor, step, scale, low, high):
	if scale >= 0.0:
		return anchor + floor((low - anchor) / step) * step
	return anchor + ceil((high - anchor) / step) * step


# Draws one tileset cell with its top-left at `position`; `alternative` holds
# Godot's tile flip/transpose flags, applied the way TileMapLayer draws them.
static func _gml_draw_tile_region(target, texture, region, position, alternative, colour):
	if not (texture is Texture2D) or region.size.x <= 0.0 or region.size.y <= 0.0:
		return
	var transpose = (alternative & GML_TILEMAP_GODOT_TRANSPOSE) != 0
	var size = region.size
	if transpose:
		size = Vector2(size.y, size.x)
	var rect = Rect2(position, size)
	if (alternative & GML_TILEMAP_GODOT_FLIP_H) != 0:
		rect.size.x = -rect.size.x
	if (alternative & GML_TILEMAP_GODOT_FLIP_V) != 0:
		rect.size.y = -rect.size.y
	target.draw_texture_rect_region(texture, rect, region, colour, transpose, true)


# Alpha testing discards pixels below the reference alpha; a draw whose alpha is
# already below it cannot produce any pixel.
static func _gml_draw_alpha_test_passes(alpha):
	if not bool(_gml_draw_state["alpha_test_enabled"]):
		return true
	return clamp(_gml_draw_real(alpha), 0.0, 1.0) >= _gml_draw_real(_gml_draw_state["alpha_test_ref"])


static func _gml_texture_resolve(texture):
	if texture is Texture2D:
		return texture
	var handle = gml_handle_from_value(GML_TEXTURE_HANDLE_KIND, texture)
	if gml_handle_is_valid(handle) and handle.reference is Texture2D:
		return handle.reference
	return null


static func _gml_texture_uvs(texture):
	if texture == null:
		return []
	return [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0]


static func _gml_sprite_texture_multi(sprites, prefetch):
	if typeof(sprites) != TYPE_ARRAY:
		return false
	var ok = true
	for sprite in sprites:
		if bool(prefetch):
			ok = gml_sprite_prefetch(sprite) and ok
		else:
			ok = gml_sprite_flush(sprite) and ok
	return ok


static func _gml_texturegroup_names():
	_gml_asset_registry_ensure_loaded()
	var names = _gml_texture_group_registry_names()
	for entry in _gml_asset_entries:
		var group = _gml_texturegroup_name_for_entry(entry)
		if group != "" and not names.has(group):
			names.append(group)
	names.sort()
	return names


static func _gml_texturegroup_exists(groupname):
	return _gml_texturegroup_names().has(str(groupname))


static func _gml_texturegroup_asset_ids(groupname, asset_type):
	_gml_asset_registry_ensure_loaded()
	var group = str(groupname)
	var type_key = _gml_asset_type_key(asset_type)
	var ids = []
	for entry in _gml_asset_entries:
		if str(entry.get("type", "")) != type_key:
			continue
		if _gml_texturegroup_name_for_entry(entry) == group:
			ids.append(int(entry.get("id", -1)))
	return ids


static func _gml_texturegroup_flush_assets(groupname):
	var group = str(groupname)
	for asset_id in _gml_texturegroup_asset_ids(group, "sprite"):
		_gml_draw_sprite_cache.erase(asset_id)
	for asset_id in _gml_texturegroup_asset_ids(group, "font"):
		_gml_draw_font_cache.erase(asset_id)
	for asset_id in _gml_texturegroup_asset_ids(group, "tileset"):
		_gml_draw_tileset_cache.erase(asset_id)
	return null


static func _gml_texturegroup_name_for_entry(entry):
	if typeof(entry) != TYPE_DICTIONARY:
		return ""
	var asset_type = str(entry.get("type", ""))
	if not ["sprite", "font", "tileset"].has(asset_type):
		return ""
	var metadata = entry.get("metadata", {})
	if typeof(metadata) == TYPE_DICTIONARY and str(metadata.get("texture_group", "")) != "":
		return str(metadata.get("texture_group", ""))
	return "Default"


static func _gml_video_root_node():
	var main_loop = Engine.get_main_loop()
	if not (main_loop is SceneTree):
		return null
	var root = main_loop.root
	if root == null:
		return null
	var existing = root.get_node_or_null(GML_VIDEO_MANAGER_NODE_NAME)
	if existing != null:
		return existing
	var manager = Node.new()
	manager.name = GML_VIDEO_MANAGER_NODE_NAME
	root.add_child(manager)
	return manager


static func _gml_video_player():
	var player = _gml_video_state.get("player", null)
	if player is VideoStreamPlayer and is_instance_valid(player):
		return player
	return null


static func _gml_video_stream_for_source(source):
	if source is VideoStream:
		return source
	if typeof(source) == TYPE_DICTIONARY:
		_gml_video_report_diagnostic("video_open", "Camera/constraint video sources require platform-specific permission and capture bridges.")
		return null
	var source_path = str(source)
	if source_path.strip_edges() == "":
		return null
	var candidates = []
	if source_path.contains("://"):
		candidates.append(source_path)
	else:
		candidates.append("res://" + source_path)
		candidates.append("user://" + source_path)
	for candidate in candidates:
		if ResourceLoader.exists(candidate):
			var loaded = load(candidate)
			if loaded is VideoStream:
				return loaded
	if source_path.get_extension().to_lower() == "ogv":
		var stream = VideoStreamTheora.new()
		stream.file = candidates[0]
		return stream
	return null


static func _gml_video_surface_handle(texture):
	var size = Vector2(1, 1)
	if texture is Texture2D:
		var texture_size = texture.get_size()
		if texture_size.x > 0 and texture_size.y > 0:
			size = texture_size
	var surface_handle = _gml_video_state.get("surface_handle", null)
	if gml_handle_is_valid(surface_handle) and typeof(surface_handle.reference) == TYPE_DICTIONARY:
		var surface = surface_handle.reference
		if int(surface.get("width", 0)) == int(size.x) and int(surface.get("height", 0)) == int(size.y):
			if texture is Texture2D:
				surface["texture"] = texture
			return surface_handle
		surface["valid"] = false
		gml_handle_invalidate(surface_handle)
	var new_surface = _gml_surface_make(int(size.x), int(size.y), false, 0)
	if texture is Texture2D:
		new_surface["texture"] = texture
	var handle = gml_handle_register("surface", new_surface, "video_surface")
	_gml_video_state["surface_handle"] = handle
	return handle


static func _gml_video_finished():
	if bool(_gml_video_state.get("loop", false)):
		_gml_video_state["status"] = GML_VIDEO_STATUS_PLAYING
	else:
		_gml_video_state["status"] = GML_VIDEO_STATUS_CLOSED
	return null


static func _gml_video_report_diagnostic(api_name, detail):
	var diagnostic = {
		"severity": "partial",
		"api": str(api_name),
		"message": str(detail),
	}
	_gml_video_diagnostics.append(diagnostic)
	push_warning("GM2Godot video runtime: " + str(api_name) + ": " + str(detail))
	return diagnostic


static func _gml_shader_entry(shader):
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(shader)
	if entry == null:
		return null
	if not entry.has("type") or str(entry["type"]) != "shader":
		return null
	return entry


static func _gml_shader_resource(shader):
	var entry = _gml_shader_entry(shader)
	if entry == null:
		return null
	var godot_path = str(entry["godot_path"]) if entry.has("godot_path") else ""
	if godot_path == "":
		return null
	if not ResourceLoader.exists(godot_path):
		return null
	var resource = load(godot_path)
	if resource is Shader:
		return resource
	return null


static func _gml_shader_material(shader):
	var entry = _gml_shader_entry(shader)
	if entry == null:
		return null
	var shader_id = int(entry["id"])
	if _gml_shader_material_cache.has(shader_id):
		var cached: Variant = _gml_shader_material_cache[shader_id]
		if cached is ShaderMaterial and cached.shader is Shader:
			return cached
	var shader_resource = _gml_shader_resource(shader)
	if shader_resource == null:
		return null
	var material = ShaderMaterial.new()
	material.shader = shader_resource
	_gml_shader_material_cache[shader_id] = material
	return material


static func _gml_shader_uniform_handle(shader, uniform_name):
	var entry = _gml_shader_entry(shader)
	if entry == null:
		return gml_handle_invalid(GML_SHADER_UNIFORM_HANDLE_KIND)
	var name = str(uniform_name)
	if name == "":
		return gml_handle_invalid(GML_SHADER_UNIFORM_HANDLE_KIND)
	var key = str(entry["id"]) + "::" + name
	if _gml_shader_uniform_cache.has(key):
		var cached: Variant = _gml_shader_uniform_cache[key]
		if gml_handle_is_valid(cached):
			return cached
	var uniform = {
		"shader_id": int(entry["id"]),
		"shader": entry,
		"name": name
	}
	var handle = gml_handle_register(GML_SHADER_UNIFORM_HANDLE_KIND, uniform, name)
	_gml_shader_uniform_cache[key] = handle
	return handle


static func _gml_shader_uniform_resolve(uniform):
	var handle = gml_handle_from_value(GML_SHADER_UNIFORM_HANDLE_KIND, uniform)
	if gml_handle_is_valid(handle) and typeof(handle.reference) == TYPE_DICTIONARY:
		return handle.reference
	return null


static func _gml_shader_set_uniform_value(uniform, value):
	var resolved_uniform: Variant = _gml_shader_uniform_resolve(uniform)
	if resolved_uniform == null:
		return false
	var material = _gml_draw_shader_material_for_write(_gml_shader_material_for_uniform(resolved_uniform))
	if material == null:
		return false
	material.set_shader_parameter(str(resolved_uniform["name"]), value)
	return true


static func _gml_shader_material_for_uniform(uniform):
	var active_entry = _gml_draw_state["shader"]
	var active_material = _gml_draw_state["shader_material"]
	if active_entry != null and active_material is ShaderMaterial:
		if int(active_entry["id"]) == int(uniform["shader_id"]):
			return active_material
	return _gml_shader_material(uniform["shader"])


static func _gml_shader_uniform_float_value(x, y, z, w):
	if w != null:
		return Vector4(_to_real(x), _to_real(y), _to_real(z), _to_real(w))
	if z != null:
		return Vector3(_to_real(x), _to_real(y), _to_real(z))
	if y != null:
		return Vector2(_to_real(x), _to_real(y))
	return _to_real(x)


static func _gml_shader_uniform_int_value(x, y, z, w):
	if w != null:
		return Vector4i(int(_to_real(x)), int(_to_real(y)), int(_to_real(z)), int(_to_real(w)))
	if z != null:
		return Vector3i(int(_to_real(x)), int(_to_real(y)), int(_to_real(z)))
	if y != null:
		return Vector2i(int(_to_real(x)), int(_to_real(y)))
	return int(_to_real(x))


static func _gml_shader_uniform_array(values):
	if typeof(values) == TYPE_ARRAY:
		return values
	if is_handle(values):
		var buffer = _gml_buffer_resolve(values)
		if buffer != null:
			var result = []
			for index in range(buffer.used_size):
				result.append(_gml_buffer_read_u8(buffer, index))
			return result
	return []


static func _gml_shader_current_matrix():
	return Projection.IDENTITY


# Canvas materials have no max/min/reverse-subtract equations: bm_max keeps
# its additive look and bm_min its darkening one, and bm_reverse_subtract
# (source minus destination) falls back to normal blending.
static func _gml_draw_canvas_blend_mode(blend_mode):
	var resolved = int(_to_real(blend_mode))
	if resolved == GML_BLEND_ADD or resolved == GML_BLEND_MAX:
		return CanvasItemMaterial.BLEND_MODE_ADD
	if resolved == GML_BLEND_SUBTRACT:
		return CanvasItemMaterial.BLEND_MODE_SUB
	if resolved == GML_BLEND_MIN:
		return CanvasItemMaterial.BLEND_MODE_MUL
	return CanvasItemMaterial.BLEND_MODE_MIX


static func _gml_draw_alpha_test_allows(alpha):
	if not bool(_gml_draw_state["alpha_test_enabled"]):
		return true
	var resolved_alpha = clamp(_gml_draw_real(alpha) * _gml_draw_real(_gml_draw_state["alpha"]), 0.0, 1.0)
	return resolved_alpha >= _gml_draw_real(_gml_draw_state["alpha_test_ref"])


static func _gml_draw_source_rect(left, top, width, height, frame_size):
	var source_left = clamp(_gml_draw_real(left), 0.0, frame_size.x)
	var source_top = clamp(_gml_draw_real(top), 0.0, frame_size.y)
	var source_width = clamp(_gml_draw_real(width), 0.0, frame_size.x - source_left)
	var source_height = clamp(_gml_draw_real(height), 0.0, frame_size.y - source_top)
	return Rect2(Vector2(source_left, source_top), Vector2(source_width, source_height))


static func _gml_draw_sprite_frame(sprite, subimg):
	var data = _gml_draw_sprite_data(sprite)
	if data == null:
		return null
	var textures = data["textures"]
	if textures.is_empty():
		return null
	var frame_index = _gml_draw_subimage_index(subimg, textures.size())
	# Frame records are built once per sprite frame (sprite_set_offset drops
	# them); callers must not modify them.
	var frames = data.get("frames", null)
	if not (frames is Array) or frames.size() != textures.size():
		frames = []
		frames.resize(textures.size())
		data["frames"] = frames
	var frame = frames[frame_index]
	if frame != null:
		return frame
	var texture = textures[frame_index]
	if texture == null:
		return null
	frame = {
		"texture": texture,
		"origin": data["origin"],
		"size": texture.get_size()
	}
	frames[frame_index] = frame
	return frame


# A negative sub-image draws the calling instance's image_index; frames wrap.
static func _gml_draw_subimage_index(subimg, frame_count):
	if frame_count <= 0:
		return 0
	var value = _gml_draw_real(subimg)
	if value < 0.0:
		value = _gml_draw_real(_gml_draw_instance_value(_gml_draw_current_context_target(), "image_index", 0))
	var frame_index = int(floor(value))
	return ((frame_index % frame_count) + frame_count) % frame_count


static func _gml_draw_sprite_data(sprite):
	# Sprite indices are usually plain asset ids: reuse the cached data while the
	# id still names the registry entry it was built from.
	if typeof(sprite) == TYPE_INT:
		var cached = _gml_draw_sprite_cache.get(sprite, null)
		if cached != null and is_same(cached.get("entry", null), _gml_asset_by_id.get(sprite, null)):
			return cached
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
		data["entry"] = entry
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
	if is_numeric(sprite) and int(_gml_draw_real(sprite)) == -1:
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
