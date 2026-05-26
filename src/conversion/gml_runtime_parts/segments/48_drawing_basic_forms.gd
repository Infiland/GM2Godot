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
const GML_TEXTURE_HANDLE_KIND = "texture"
const GML_SHADER_UNIFORM_HANDLE_KIND = "shader_uniform"
const GML_BLEND_NORMAL = 0
const GML_BLEND_ADD = 1
const GML_BLEND_SUBTRACT = 2
const GML_BLEND_MULTIPLY = 3
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
const GML_DRAW_EVENT_PHASES = [
	{"phase": "pre_draw", "method": "_on_pre_draw"},
	{"phase": "draw_begin", "method": "_on_draw_begin"},
	{"phase": "draw", "method": "_draw"},
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
	"shader_material": null
}


static func gml_draw_begin(target, context_name = "draw"):
	_gml_camera_update_visible_views()
	_gml_draw_context_stack.append({
		"target": target,
		"context": str(context_name),
		"state": _gml_draw_state_copy()
	})
	if str(context_name) == "_draw":
		_gml_draw_hide_default_sprite(target)
	_gml_draw_apply_gpu_state(target)
	return null


static func gml_draw_end():
	if _gml_draw_context_stack.is_empty():
		return null
	var context = _gml_draw_context_stack.pop_back()
	_gml_draw_state = context["state"]
	_gml_draw_apply_gpu_state(context["target"])
	return null


static func gml_draw_event_phase_order():
	var phases = []
	for phase in GML_DRAW_EVENT_PHASES:
		phases.append(phase["phase"])
	return phases


static func gml_draw_event_trace():
	return _gml_clone_value(_gml_draw_event_trace, 16)


static func gml_draw_event_trace_clear():
	_gml_draw_event_trace = []
	return null


static func gml_draw_event_dispatch_frame(instances = null):
	if gml_application_surface_is_enabled():
		_gml_application_surface_ensure()
	var targets = _gml_draw_sorted_instances(instances)
	var dispatched = 0
	for phase in GML_DRAW_EVENT_PHASES:
		var phase_name = str(phase["phase"])
		var method_name = str(phase["method"])
		_gml_draw_record_event(phase_name, "", null, "phase")
		for inst in targets:
			if not _gml_draw_instance_visible(inst):
				continue
			if method_name == "_draw" and not inst.has_method(method_name):
				_gml_draw_record_event(phase_name, "draw_self", inst, "default")
				dispatched += 1
				continue
			if inst.has_method(method_name):
				_gml_draw_record_event(phase_name, method_name, inst, "custom")
				inst.call(method_name)
				dispatched += 1
	return dispatched


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
	_gml_draw_state["texture_filter"] = gml_bool(linear)
	_gml_draw_apply_gpu_state()
	return null


static func gml_gpu_get_texfilter():
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


static func gml_gpu_set_colorwriteenable(red, green, blue, alpha):
	_gml_draw_state["color_write"] = [gml_bool(red), gml_bool(green), gml_bool(blue), gml_bool(alpha)]
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
	if _gml_surface_has_active_target():
		return null
	var target = _gml_draw_context_stack[_gml_draw_context_stack.size() - 1]["target"]
	if target is CanvasItem:
		_gml_draw_apply_gpu_state(target)
		return target
	return null


static func _gml_draw_current_context_target():
	if _gml_draw_context_stack.is_empty():
		return null
	return _gml_draw_context_stack[_gml_draw_context_stack.size() - 1]["target"]


static func _gml_draw_sorted_instances(instances):
	var targets = []
	if instances is Array:
		for inst in instances:
			if inst != null and is_instance_valid(inst):
				targets.append(inst)
	else:
		for entry in _gml_live_instance_entries():
			var inst = entry["instance"]
			if inst != null and is_instance_valid(inst):
				targets.append(inst)
	targets.sort_custom(_gml_draw_instance_order_less)
	return targets


static func _gml_draw_instance_order_less(left, right):
	var left_depth = _gml_draw_instance_depth(left)
	var right_depth = _gml_draw_instance_depth(right)
	if left_depth == right_depth:
		return _gml_draw_instance_creation_order(left) < _gml_draw_instance_creation_order(right)
	return left_depth > right_depth


static func _gml_draw_instance_depth(inst):
	var value = gml_struct_get(inst, "depth")
	if not is_undefined(value):
		return int(_to_real(value))
	if inst is CanvasItem:
		return -int(inst.z_index)
	return 0


static func _gml_draw_instance_creation_order(inst):
	var entry: Variant = _gml_instance_entry(inst)
	if entry == null:
		return 0
	return int(entry.get("creation_order", 0))


static func _gml_draw_instance_visible(inst):
	if inst == null or not is_instance_valid(inst):
		return false
	var value = gml_struct_get(inst, "visible")
	if not is_undefined(value):
		if not gml_bool(value):
			return false
	if inst is CanvasItem and not inst.visible:
		return false
	return true


static func _gml_draw_record_event(phase, method_name, inst, kind):
	var entry = {
		"phase": str(phase),
		"method": str(method_name),
		"kind": str(kind),
		"instance": "",
		"depth": 0,
	}
	if inst != null:
		entry["instance"] = str(inst.name) if inst is Node else str(inst)
		entry["depth"] = _gml_draw_instance_depth(inst)
	_gml_draw_event_trace.append(entry)
	return null


static func _gml_draw_current_color():
	return _gml_draw_color(_gml_draw_state["color"])


static func _gml_draw_color(color):
	return _gml_draw_modulate(color, 1.0)


static func _gml_draw_modulate(color, alpha):
	var resolved_alpha = clamp(_to_real(alpha) * _to_real(_gml_draw_state["alpha"]), 0.0, 1.0)
	var color_write = _gml_draw_state["color_write"]
	if color is Color:
		var color_value = color
		if not bool(color_write[0]):
			color_value.r = 0.0
		if not bool(color_write[1]):
			color_value.g = 0.0
		if not bool(color_write[2]):
			color_value.b = 0.0
		color_value.a = resolved_alpha if bool(color_write[3]) else 0.0
		return color_value
	var value = int(_to_real(color))
	var red = float(value & 0xff) / 255.0
	var green = float((value >> 8) & 0xff) / 255.0
	var blue = float((value >> 16) & 0xff) / 255.0
	if not bool(color_write[0]):
		red = 0.0
	if not bool(color_write[1]):
		green = 0.0
	if not bool(color_write[2]):
		blue = 0.0
	if not bool(color_write[3]):
		resolved_alpha = 0.0
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
	if not _gml_draw_alpha_test_allows(_to_real(alpha)):
		return null
	var scale = Vector2(_to_real(xscale), _to_real(yscale))
	if abs(scale.x) <= 0.00001 or abs(scale.y) <= 0.00001:
		return null
	var draw_origin = origin
	if not (draw_origin is Vector2):
		draw_origin = Vector2.ZERO
	var rect = Rect2(-draw_origin, source.size)
	target.draw_set_transform(Vector2(_to_real(x), _to_real(y)), deg_to_rad(-_to_real(rot)), scale)
	target.draw_texture_rect_region(texture, rect, source, _gml_draw_modulate(colour, alpha), bool(_gml_draw_state["texture_repeat"]), true)
	target.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	return null


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
	var material = _gml_shader_material_for_uniform(resolved_uniform)
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


static func _gml_draw_apply_gpu_state(target = null):
	var resolved_target = target if target != null else _gml_draw_current_context_target()
	if not (resolved_target is CanvasItem):
		return null
	if _object_has_property(resolved_target, "texture_filter"):
		resolved_target.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR if bool(_gml_draw_state["texture_filter"]) else CanvasItem.TEXTURE_FILTER_NEAREST
	if _object_has_property(resolved_target, "texture_repeat"):
		resolved_target.texture_repeat = CanvasItem.TEXTURE_REPEAT_ENABLED if bool(_gml_draw_state["texture_repeat"]) else CanvasItem.TEXTURE_REPEAT_DISABLED
	var shader_material = _gml_draw_state["shader_material"]
	if shader_material is ShaderMaterial:
		resolved_target.material = shader_material
		return null
	var material: Variant = resolved_target.material
	if not (material is CanvasItemMaterial):
		material = CanvasItemMaterial.new()
		resolved_target.material = material
	material.blend_mode = _gml_draw_canvas_blend_mode(_gml_draw_state["blend_mode"])
	return null


static func _gml_draw_canvas_blend_mode(blend_mode):
	var resolved = int(_to_real(blend_mode))
	if resolved == GML_BLEND_ADD:
		return CanvasItemMaterial.BLEND_MODE_ADD
	if resolved == GML_BLEND_SUBTRACT:
		return CanvasItemMaterial.BLEND_MODE_SUB
	if resolved == GML_BLEND_MULTIPLY:
		return CanvasItemMaterial.BLEND_MODE_MUL
	return CanvasItemMaterial.BLEND_MODE_MIX


static func _gml_draw_alpha_test_allows(alpha):
	if not bool(_gml_draw_state["alpha_test_enabled"]):
		return true
	var resolved_alpha = clamp(_to_real(alpha) * _to_real(_gml_draw_state["alpha"]), 0.0, 1.0)
	return resolved_alpha >= _to_real(_gml_draw_state["alpha_test_ref"])


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
	var color_write = _gml_draw_state["color_write"]
	var blend_ext = _gml_draw_state["blend_mode_ext"]
	return {
		"color": _gml_draw_state["color"],
		"alpha": _gml_draw_state["alpha"],
		"line_width": _gml_draw_state["line_width"],
		"font": _gml_draw_state["font"],
		"halign": _gml_draw_state["halign"],
		"valign": _gml_draw_state["valign"],
		"blend_mode": _gml_draw_state["blend_mode"],
		"blend_mode_ext": [blend_ext[0], blend_ext[1]],
		"texture_filter": _gml_draw_state["texture_filter"],
		"texture_repeat": _gml_draw_state["texture_repeat"],
		"color_write": [color_write[0], color_write[1], color_write[2], color_write[3]],
		"cull_mode": _gml_draw_state["cull_mode"],
		"alpha_test_enabled": _gml_draw_state["alpha_test_enabled"],
		"alpha_test_ref": _gml_draw_state["alpha_test_ref"],
		"shader": _gml_draw_state["shader"],
		"shader_material": _gml_draw_state["shader_material"]
	}
