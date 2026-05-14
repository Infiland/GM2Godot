const GML_SURFACE_HANDLE_KIND = "surface"
const GML_SURFACE_FORMAT_RGBA8UNORM = 0

static var _gml_surface_target_stack = []
static var _gml_application_surface_handle = null
static var _gml_application_surface_enabled = true
static var _gml_application_surface_draw_enabled = true


static func gml_application_surface():
	_gml_application_surface_ensure()
	return _gml_application_surface_handle


static func gml_application_surface_enable(enable):
	_gml_application_surface_enabled = gml_bool(enable)
	_gml_application_surface_ensure()
	return null


static func gml_application_surface_is_enabled():
	return _gml_application_surface_enabled


static func gml_application_surface_draw_enable(flag):
	_gml_application_surface_draw_enabled = gml_bool(flag)
	return null


static func gml_application_surface_is_draw_enabled():
	return _gml_application_surface_draw_enabled


static func gml_application_get_position():
	var size = _gml_application_surface_size()
	return [0, 0, size.x, size.y]


static func gml_surface_create(width, height, format = GML_SURFACE_FORMAT_RGBA8UNORM):
	var surface_width = max(int(_to_real(width)), 1)
	var surface_height = max(int(_to_real(height)), 1)
	var surface = _gml_surface_make(surface_width, surface_height, false, format)
	return gml_handle_register(GML_SURFACE_HANDLE_KIND, surface)


static func gml_surface_exists(surface):
	return _gml_surface_resolve(surface) != null


static func gml_surface_free(surface):
	var handle = gml_handle_from_value(GML_SURFACE_HANDLE_KIND, surface)
	var resolved_surface = _gml_surface_resolve(handle)
	if resolved_surface == null:
		return null
	if bool(resolved_surface.get("application", false)):
		return null
	resolved_surface["valid"] = false
	_gml_surface_remove_target(handle)
	gml_handle_invalidate(handle)
	return null


static func gml_surface_set_target(surface, depth = null):
	var handle = gml_handle_from_value(GML_SURFACE_HANDLE_KIND, surface)
	var resolved_surface = _gml_surface_resolve(handle)
	if resolved_surface == null:
		return false
	_gml_surface_target_stack.append(handle)
	return true


static func gml_surface_reset_target():
	if _gml_surface_target_stack.is_empty():
		return false
	_gml_surface_target_stack.pop_back()
	return true


static func gml_surface_get_width(surface):
	var resolved_surface = _gml_surface_resolve(surface)
	if resolved_surface == null:
		return 0
	return int(resolved_surface["width"])


static func gml_surface_get_height(surface):
	var resolved_surface = _gml_surface_resolve(surface)
	if resolved_surface == null:
		return 0
	return int(resolved_surface["height"])


static func gml_draw_surface(surface, x, y):
	return gml_draw_surface_ext(surface, x, y, 1, 1, 0, 0xffffff, 1)


static func gml_draw_surface_ext(surface, x, y, xscale, yscale, rot, colour, alpha):
	var handle = gml_handle_from_value(GML_SURFACE_HANDLE_KIND, surface)
	var resolved_surface = _gml_surface_resolve(handle)
	if resolved_surface == null:
		return null
	var active_handle = _gml_surface_active_handle()
	if active_handle != null and active_handle.index == handle.index:
		return null
	if active_handle != null:
		var target_surface = _gml_surface_resolve(active_handle)
		if target_surface != null:
			_gml_surface_blit(target_surface, resolved_surface, int(_to_real(x)), int(_to_real(y)))
		return null
	var source = Rect2(Vector2.ZERO, Vector2(resolved_surface["width"], resolved_surface["height"]))
	_gml_draw_texture_part(resolved_surface["texture"], source, x, y, xscale, yscale, rot, colour, alpha, Vector2.ZERO)
	return null


static func gml_surface_copy(destination, x, y, source):
	var destination_surface = _gml_surface_resolve(destination)
	var source_surface = _gml_surface_resolve(source)
	if destination_surface == null or source_surface == null:
		return null
	_gml_surface_blit(destination_surface, source_surface, int(_to_real(x)), int(_to_real(y)))
	return null


static func gml_surface_save(surface, filename):
	var resolved_surface = _gml_surface_resolve(surface)
	if resolved_surface == null:
		return null
	var save_path = str(filename)
	if not save_path.contains("://"):
		save_path = "user://" + save_path
	var error = resolved_surface["image"].save_png(save_path)
	if error != OK:
		push_warning("GM surface_save failed for " + save_path + " with error " + str(error))
	return null


static func _gml_application_surface_ensure():
	if _gml_application_surface_handle != null and gml_handle_is_valid(_gml_application_surface_handle):
		return
	var size = _gml_application_surface_size()
	var surface = _gml_surface_make(int(size.x), int(size.y), true, GML_SURFACE_FORMAT_RGBA8UNORM)
	_gml_application_surface_handle = gml_handle_register(GML_SURFACE_HANDLE_KIND, surface, "application_surface")
	_gml_builtin_globals["application_surface"] = _gml_application_surface_handle


static func _gml_application_surface_size():
	var width = 0.0
	var height = 0.0
	if _gml_builtin_globals.has("room_width"):
		width = _to_real(_gml_builtin_globals["room_width"])
	if _gml_builtin_globals.has("room_height"):
		height = _to_real(_gml_builtin_globals["room_height"])
	var target = _gml_draw_current_context_target()
	if target is CanvasItem and (width <= 0.0 or height <= 0.0):
		var viewport_size = target.get_viewport_rect().size
		width = viewport_size.x if width <= 0.0 else width
		height = viewport_size.y if height <= 0.0 else height
	if width <= 0.0:
		width = 640.0
	if height <= 0.0:
		height = 480.0
	return Vector2(width, height)


static func _gml_surface_make(width, height, is_application, format):
	var image = Image.create(width, height, false, Image.FORMAT_RGBA8)
	image.fill(Color(0, 0, 0, 0))
	var texture = ImageTexture.create_from_image(image)
	return {
		"width": int(width),
		"height": int(height),
		"image": image,
		"texture": texture,
		"valid": true,
		"application": bool(is_application),
		"format": int(_to_real(format)) if is_numeric(format) else GML_SURFACE_FORMAT_RGBA8UNORM
	}


static func _gml_surface_resolve(surface):
	if typeof(surface) == TYPE_DICTIONARY:
		if bool(surface.get("valid", false)):
			return surface
		return null
	var handle = gml_handle_from_value(GML_SURFACE_HANDLE_KIND, surface)
	if not gml_handle_is_valid(handle):
		return null
	if typeof(handle.reference) == TYPE_DICTIONARY and bool(handle.reference.get("valid", false)):
		return handle.reference
	return null


static func _gml_surface_active_handle():
	while not _gml_surface_target_stack.is_empty():
		var handle = _gml_surface_target_stack[_gml_surface_target_stack.size() - 1]
		if gml_handle_is_valid(handle) and _gml_surface_resolve(handle) != null:
			return handle
		_gml_surface_target_stack.pop_back()
	return null


static func _gml_surface_has_active_target():
	return _gml_surface_active_handle() != null


static func _gml_surface_clear_active_target(color, alpha):
	var raw_surface = _gml_surface_resolve(_gml_surface_active_handle())
	if typeof(raw_surface) != TYPE_DICTIONARY:
		return false
	var active_surface: Dictionary = raw_surface
	active_surface["image"].fill(_gml_draw_modulate(color, alpha))
	active_surface["texture"].update(active_surface["image"])
	return true


static func _gml_surface_blit(destination_surface, source_surface, x, y):
	var source_image = source_surface["image"]
	var destination_image = destination_surface["image"]
	var source_rect = Rect2i(Vector2i.ZERO, Vector2i(int(source_surface["width"]), int(source_surface["height"])))
	destination_image.blit_rect(source_image, source_rect, Vector2i(int(x), int(y)))
	destination_surface["texture"].update(destination_image)


static func _gml_surface_remove_target(handle):
	if not is_handle(handle):
		return
	for index in range(_gml_surface_target_stack.size() - 1, -1, -1):
		var target_handle = _gml_surface_target_stack[index]
		if is_handle(target_handle) and target_handle.kind == handle.kind and target_handle.index == handle.index:
			_gml_surface_target_stack.remove_at(index)
