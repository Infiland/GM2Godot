static var _gml_draw_context_stack = []
static var _gml_draw_state = {
	"color": 0xffffff,
	"alpha": 1.0,
	"line_width": 1.0,
	"font": gml_undefined(),
	"halign": 0,
	"valign": 0,
	"blend_mode": 0
}


static func gml_draw_begin(target, context_name = "draw"):
	_gml_draw_context_stack.append({
		"target": target,
		"context": str(context_name),
		"state": _gml_draw_state_copy()
	})
	return null


static func gml_draw_end():
	if _gml_draw_context_stack.is_empty():
		return null
	var context = _gml_draw_context_stack.pop_back()
	_gml_draw_state = context["state"]
	return null


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


static func _gml_draw_current_color():
	return _gml_draw_color(_gml_draw_state["color"])


static func _gml_draw_color(color):
	if color is Color:
		var color_value = color
		color_value.a = clamp(_to_real(_gml_draw_state["alpha"]), 0.0, 1.0)
		return color_value
	var value = int(_to_real(color))
	var red = float(value & 0xff) / 255.0
	var green = float((value >> 8) & 0xff) / 255.0
	var blue = float((value >> 16) & 0xff) / 255.0
	return Color(red, green, blue, clamp(_to_real(_gml_draw_state["alpha"]), 0.0, 1.0))


static func _gml_draw_line_width():
	return max(_to_real(_gml_draw_state["line_width"]), 1.0)


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
