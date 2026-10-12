const GML_DRAW_SPACE_INSTANCE = "instance"
const GML_DRAW_SPACE_PRE_DRAW = "pre_draw"
const GML_DRAW_SPACE_BEGIN = "draw_begin"
const GML_DRAW_SPACE_END = "draw_end"
const GML_DRAW_SPACE_POST_DRAW = "post_draw"
const GML_DRAW_SPACE_GUI = "gui"
const GML_DRAW_SINK_CHILD_DRAW_INDEX = 1 << 28
const GML_DRAW_EVENT_TRACE_LIMIT = 4096
# Every registered instance joins this group so SceneTree returns them in tree
# order without sorting in GDScript.
const GML_DRAW_INSTANCE_GROUP = &"_gm2godot_draw_instances"
# Set on an instance once its depth has been assigned; until then it has its
# layer's depth.
const GML_EXPLICIT_DEPTH_META = &"_gm2godot_explicit_depth"
# Set while an instance moves to another layer node. It stays the same live
# instance, so the generated _exit_tree (CleanUp, unregistering) and the draw
# sink release do not run for the move.
const GML_LAYER_MOVE_META = &"_gm2godot_moving_layers"
const GML_DRAW_GUI_LAYER_NAME = "GMGUI"
const GML_DRAW_GUI_LAYER_INDEX = 1000
# The draw phases that draw the room through its views.
const GML_DRAW_ROOM_PHASES = ["draw_begin", "draw", "draw_end"]
const GML_DRAW_PHASE_SPACES = {
	"pre_draw": GML_DRAW_SPACE_PRE_DRAW,
	"draw_begin": GML_DRAW_SPACE_BEGIN,
	"draw": GML_DRAW_SPACE_INSTANCE,
	"draw_end": GML_DRAW_SPACE_END,
	"post_draw": GML_DRAW_SPACE_POST_DRAW,
	"draw_gui_begin": GML_DRAW_SPACE_GUI,
	"draw_gui": GML_DRAW_SPACE_GUI,
	"draw_gui_end": GML_DRAW_SPACE_GUI,
}
const GML_DRAW_CONTEXT_PHASES = {
	"_on_pre_draw": "pre_draw",
	"_on_draw_begin": "draw_begin",
	"_on_draw": "draw",
	"_draw": "draw",
	"_on_draw_end": "draw_end",
	"_on_post_draw": "post_draw",
	"_on_draw_gui_begin": "draw_gui_begin",
	"_on_draw_gui": "draw_gui",
	"_on_draw_gui_end": "draw_gui_end",
}
# Runtime-owned CanvasLayers for the draw phases that do not render inside the
# room's layer hierarchy. Draw Begin/End follow the room camera; Pre/Post Draw
# use window space. GUI phases render into the room's GMGUI CanvasLayer.
const GML_DRAW_SPACE_LAYER_SPECS = {
	"pre_draw": {"name": "_GM2GodotPreDraw", "layer": -2, "follow_viewport": false, "room_space": false},
	"draw_begin": {"name": "_GM2GodotDrawBegin", "layer": -1, "follow_viewport": true, "room_space": true},
	"draw_end": {"name": "_GM2GodotDrawEnd", "layer": 1, "follow_viewport": true, "room_space": true},
	"post_draw": {"name": "_GM2GodotPostDraw", "layer": 999, "follow_viewport": false, "room_space": false},
}
# Godot's CanvasItem z_index range is -4096..4096.
const GML_DEPTH_Z_LIMIT = 4096
# Truncated depths are 64-bit integers; larger magnitudes saturate.
const GML_DEPTH_INTEGER_LIMIT = 9.0e18

static var _gml_draw_sinks = {}
static var _gml_draw_space_layers = {}
static var _gml_draw_frame_serial = 0
static var _gml_draw_dispatch_active = false
static var _gml_draw_dispatch_context = null
static var _gml_draw_gpu_version = 0
static var _gml_draw_gpu_state_cache = null
static var _gml_draw_gpu_state_cache_version = -1
static var _gml_draw_blend_materials = {}
static var _gml_draw_used_materials = {}
static var _gml_draw_material_pool = {}
static var _gml_draw_script_methods = {}
static var _gml_draw_hidden_visuals = {}
static var _gml_draw_pending_depths = {}
# GameMaker gives every distinct depth its own layer and draws layers from the
# highest depth to the lowest, so two different depths never tie. Every node
# whose absolute z_index stands for a depth (layers, instances with an assigned
# depth, particle systems) is tracked here by instance id. While all depths in
# use fit Godot's z_index range the z_index is -depth; once one does not, the
# distinct depths in use are ranked into the range (_gml_depth_flush).
static var _gml_depth_nodes = {}
static var _gml_depth_values = {}
static var _gml_depth_ranked = false
static var _gml_depth_ranked_z = {}
static var _gml_depth_dirty = false
static var _gml_draw_trace_enabled = false
static var _gml_draw_group_scan_counter = -1
# Dispatch is not re-entrant, so every dispatched event reuses this context.
static var _gml_draw_invoke_context = {"target": null, "context": "", "phase": "", "sink": null}


# A draw sink owns RenderingServer canvas items for one draw space (one
# instance's Draw event, or a shared phase layer). Commands are appended in call
# order; a GPU state change (blend mode, shader, texture filter/repeat) starts a
# new child canvas item with the next draw index so earlier commands keep their
# state. The method names mirror CanvasItem's draw_* API.
class GMLDrawSink:
	var key = ""
	var registry_key = null
	var space = ""
	var root = RID()
	var parent = RID()
	var draw_index = 0
	var root_transform = Transform2D.IDENTITY
	var z_index = 0
	var z_relative = true
	var host_id = 0
	var host_exit_callable = null
	var viewport_source = null
	var space_node = null
	var segments = []
	var segment_states = []
	var segment_versions = []
	var segment_materials = []
	var segment_filters = []
	var segment_repeats = []
	var segment_transforms = []
	var segment_commands = []
	var cursor = -1
	var frame = -1
	var transform = Transform2D.IDENTITY
	var gpu_state = null
	var gpu_version = -1
	var used_materials = null

	func _init(sink_key = "", sink_space = "", used_material_registry = null):
		key = str(sink_key)
		registry_key = key
		space = str(sink_space)
		used_materials = used_material_registry
		root = RenderingServer.canvas_item_create()

	func is_valid():
		return root.is_valid()

	func attach(parent_rid, index, xform, z = 0, relative = true):
		if not root.is_valid():
			return
		if parent_rid != parent:
			RenderingServer.canvas_item_set_parent(root, parent_rid)
			parent = parent_rid
			RenderingServer.canvas_item_set_draw_index(root, index)
			draw_index = index
		elif index != draw_index:
			RenderingServer.canvas_item_set_draw_index(root, index)
			draw_index = index
		if xform != root_transform:
			RenderingServer.canvas_item_set_transform(root, xform)
			root_transform = xform
		if z != z_index:
			RenderingServer.canvas_item_set_z_index(root, z)
			z_index = z
		if relative != z_relative:
			RenderingServer.canvas_item_set_z_as_relative_to_parent(root, relative)
			z_relative = relative

	func detach():
		attach(RID(), draw_index, root_transform, z_index, z_relative)

	func begin_frame(serial):
		if frame == serial:
			return
		frame = serial
		for index in range(segments.size()):
			if int(segment_commands[index]) > 0 or segment_transforms[index] != Transform2D.IDENTITY:
				RenderingServer.canvas_item_clear(segments[index])
				segment_commands[index] = 0
				segment_transforms[index] = Transform2D.IDENTITY
		cursor = -1
		transform = Transform2D.IDENTITY

	func set_gpu_state(version, state):
		gpu_version = version
		gpu_state = state

	func command_count():
		var total = 0
		for count in segment_commands:
			total += int(count)
		return total

	func get_canvas_item():
		return _item()

	func get_viewport_rect():
		var source = viewport_source.get_ref() if viewport_source is WeakRef else null
		if source is CanvasItem and source.is_inside_tree():
			return source.get_viewport_rect()
		if source is Node and source.is_inside_tree():
			return source.get_viewport().get_visible_rect()
		var loop = Engine.get_main_loop()
		if loop is SceneTree and loop.root != null:
			return loop.root.get_visible_rect()
		return Rect2()

	# The part of the viewport this sink can draw on, in its command coordinates.
	func visible_region():
		var viewport_rect = get_viewport_rect()
		var node = space_node.get_ref() if space_node is WeakRef else null
		var to_viewport = null
		if node is CanvasItem and node.is_inside_tree():
			to_viewport = node.get_global_transform_with_canvas() * root_transform
		elif node is CanvasLayer and node.is_inside_tree():
			to_viewport = node.get_final_transform() * root_transform
		if to_viewport == null or abs(to_viewport.determinant()) <= 0.0000001:
			return viewport_rect
		var inverse = to_viewport.affine_inverse()
		var region = Rect2(inverse * viewport_rect.position, Vector2.ZERO)
		region = region.expand(inverse * Vector2(viewport_rect.end.x, viewport_rect.position.y))
		region = region.expand(inverse * viewport_rect.end)
		region = region.expand(inverse * Vector2(viewport_rect.position.x, viewport_rect.end.y))
		return region

	func draw_set_transform(position, rotation = 0.0, scale = Vector2.ONE):
		transform = Transform2D(float(rotation), scale, 0.0, position)

	func draw_set_transform_matrix(xform):
		transform = xform

	func draw_rect(rect, color, filled = true, width = -1.0, antialiased = false):
		var area = rect.abs()
		if filled:
			RenderingServer.canvas_item_add_rect(_item(), area, color, antialiased)
			return
		var points = PackedVector2Array([
			area.position,
			Vector2(area.end.x, area.position.y),
			area.end,
			Vector2(area.position.x, area.end.y),
			area.position,
		])
		RenderingServer.canvas_item_add_polyline(_item(), points, PackedColorArray([color]), width, antialiased)

	func draw_line(from, to, color, width = -1.0, antialiased = false):
		RenderingServer.canvas_item_add_line(_item(), from, to, color, width, antialiased)

	func draw_polyline(points, color, width = -1.0, antialiased = false):
		if points.size() < 2:
			return
		RenderingServer.canvas_item_add_polyline(_item(), points, PackedColorArray([color]), width, antialiased)

	func draw_polyline_colors(points, colors, width = -1.0, antialiased = false):
		if points.size() < 2:
			return
		RenderingServer.canvas_item_add_polyline(_item(), points, colors, width, antialiased)

	func draw_multiline(points, color, width = -1.0, antialiased = false):
		if points.size() < 2:
			return
		RenderingServer.canvas_item_add_multiline(_item(), points, PackedColorArray([color]), width, antialiased)

	func draw_polygon(points, colors, uvs = PackedVector2Array(), texture = null):
		if points.size() < 3:
			return
		var texture_rid = texture.get_rid() if texture is Texture2D else RID()
		RenderingServer.canvas_item_add_polygon(_item(), points, colors, uvs, texture_rid)

	func draw_colored_polygon(points, color, uvs = PackedVector2Array(), texture = null):
		draw_polygon(points, PackedColorArray([color]), uvs, texture)

	func draw_primitive(points, colors, uvs, texture = null):
		var texture_rid = texture.get_rid() if texture is Texture2D else RID()
		RenderingServer.canvas_item_add_primitive(_item(), points, colors, uvs, texture_rid)

	func draw_triangles(points, colors, uvs = PackedVector2Array(), texture_rid = RID(), indices = PackedInt32Array()):
		if points.size() < 3:
			return
		var resolved_indices = indices
		if resolved_indices.is_empty():
			resolved_indices = PackedInt32Array()
			for index in range(points.size() - points.size() % 3):
				resolved_indices.append(index)
		var resolved_colors = colors
		if resolved_colors.size() == 1 and points.size() > 1:
			resolved_colors = PackedColorArray()
			resolved_colors.resize(points.size())
			resolved_colors.fill(colors[0])
		RenderingServer.canvas_item_add_triangle_array(
			_item(),
			resolved_indices,
			points,
			resolved_colors,
			uvs,
			PackedInt32Array(),
			PackedFloat32Array(),
			texture_rid
		)

	func draw_circle(position, radius, color, filled = true, width = -1.0, antialiased = false):
		if filled:
			RenderingServer.canvas_item_add_circle(_item(), position, radius, color, antialiased)
			return
		draw_arc(position, radius, 0.0, TAU, 64, color, width, antialiased)

	func draw_arc(center, radius, start_angle, end_angle, point_count, color, width = -1.0, antialiased = false):
		var count = max(int(point_count), 2)
		var points = PackedVector2Array()
		for index in range(count):
			var angle = lerpf(float(start_angle), float(end_angle), float(index) / float(count - 1))
			points.append(center + Vector2(cos(angle), sin(angle)) * float(radius))
		draw_polyline(points, color, width, antialiased)

	func draw_texture(texture, position, modulate = Color(1, 1, 1, 1)):
		if texture is Texture2D:
			texture.draw(_item(), position, modulate, false)

	func draw_texture_rect(texture, rect, tile, modulate = Color(1, 1, 1, 1), transpose = false):
		if texture is Texture2D:
			texture.draw_rect(_item(), rect, tile, modulate, transpose)

	func draw_texture_rect_region(texture, rect, src_rect, modulate = Color(1, 1, 1, 1), transpose = false, clip_uv = true):
		if texture is Texture2D:
			texture.draw_rect_region(_item(), rect, src_rect, modulate, transpose, clip_uv)

	# Repeats `texture` across `rect` from its corner, in a segment with texture
	# repeat enabled whatever the current repeat state is.
	func draw_texture_repeated(texture, rect, modulate = Color(1, 1, 1, 1)):
		if not (texture is Texture2D):
			return
		var saved_state = gpu_state
		var saved_version = gpu_version
		var material = null
		var filter = RenderingServer.CANVAS_ITEM_TEXTURE_FILTER_DEFAULT
		if saved_state is Array and saved_state.size() >= 3:
			material = saved_state[0]
			filter = int(saved_state[1])
		gpu_state = [material, filter, RenderingServer.CANVAS_ITEM_TEXTURE_REPEAT_ENABLED]
		gpu_version = -2
		RenderingServer.canvas_item_add_texture_rect(_item(), rect, texture.get_rid(), true, modulate, false)
		gpu_state = saved_state
		gpu_version = saved_version

	func draw_string(font, pos, text, alignment = HORIZONTAL_ALIGNMENT_LEFT, width = -1, font_size = 16, modulate = Color(1, 1, 1, 1), justification_flags = 3, direction = 0, orientation = 0):
		if font is Font:
			font.draw_string(_item(), pos, str(text), alignment, width, font_size, modulate, justification_flags, direction, orientation)

	func draw_multiline_string(font, pos, text, alignment = HORIZONTAL_ALIGNMENT_LEFT, width = -1, font_size = 16, max_lines = -1, modulate = Color(1, 1, 1, 1), brk_flags = 3, justification_flags = 3, direction = 0, orientation = 0):
		if font is Font:
			font.draw_multiline_string(_item(), pos, str(text), alignment, width, font_size, max_lines, modulate, brk_flags, justification_flags, direction, orientation)

	func draw_string_outline(font, pos, text, alignment = HORIZONTAL_ALIGNMENT_LEFT, width = -1, font_size = 16, size = 1, modulate = Color(1, 1, 1, 1), justification_flags = 3, direction = 0, orientation = 0):
		if font is Font:
			font.draw_string_outline(_item(), pos, str(text), alignment, width, font_size, size, modulate, justification_flags, direction, orientation)

	func draw_char(font, pos, character, font_size = 16, modulate = Color(1, 1, 1, 1)):
		var text = str(character)
		if font is Font and text != "":
			font.draw_char(_item(), pos, text.unicode_at(0), font_size, modulate)

	func free_rids():
		for item in segments:
			if item.is_valid():
				RenderingServer.free_rid(item)
		if root.is_valid():
			RenderingServer.free_rid(root)
		segments.clear()
		segment_states.clear()
		segment_versions.clear()
		segment_materials.clear()
		segment_filters.clear()
		segment_repeats.clear()
		segment_transforms.clear()
		segment_commands.clear()
		root = RID()
		parent = RID()
		cursor = -1
		used_materials = null
		viewport_source = null
		space_node = null

	func snapshot():
		var segment_info = []
		for index in range(segments.size()):
			var material = segment_materials[index]
			var material_kind = "none"
			var blend_mode = 0
			if material is ShaderMaterial:
				material_kind = "shader"
			elif material is CanvasItemMaterial:
				material_kind = "canvas_item"
				blend_mode = int(material.blend_mode)
			segment_info.append({
				"commands": int(segment_commands[index]),
				"material": material_kind,
				"material_ref": material,
				"blend_mode": blend_mode,
				"texture_filter": int(segment_filters[index]),
				"texture_repeat": int(segment_repeats[index]),
			})
		return {
			"key": key,
			"space": space,
			"root": root,
			"parent": parent,
			"draw_index": draw_index,
			"transform": root_transform,
			"z_index": z_index,
			"z_relative": z_relative,
			"host_id": host_id,
			"frame": frame,
			"commands": command_count(),
			"segments": segment_info,
		}

	func _item():
		if cursor < 0 or int(segment_versions[cursor]) != gpu_version:
			_select_segment()
		var item = segments[cursor]
		if segment_transforms[cursor] != transform:
			RenderingServer.canvas_item_add_set_transform(item, transform)
			segment_transforms[cursor] = transform
		segment_commands[cursor] = int(segment_commands[cursor]) + 1
		var material = segment_materials[cursor]
		if material is ShaderMaterial and used_materials is Dictionary:
			used_materials[material.get_instance_id()] = true
		return item

	func _select_segment():
		if cursor >= 0 and _states_match(segment_states[cursor], gpu_state):
			segment_versions[cursor] = gpu_version
			return
		if cursor < 0 or int(segment_commands[cursor]) > 0:
			cursor += 1
		if cursor >= segments.size():
			_create_segment()
		_apply_state(cursor)

	func _create_segment():
		var item = RenderingServer.canvas_item_create()
		RenderingServer.canvas_item_set_parent(item, root)
		RenderingServer.canvas_item_set_draw_index(item, segments.size())
		segments.append(item)
		segment_states.append(null)
		segment_versions.append(-1)
		segment_materials.append(null)
		segment_filters.append(-1)
		segment_repeats.append(-1)
		segment_transforms.append(Transform2D.IDENTITY)
		segment_commands.append(0)

	func _apply_state(index):
		var material = null
		var filter = RenderingServer.CANVAS_ITEM_TEXTURE_FILTER_DEFAULT
		var repeat = RenderingServer.CANVAS_ITEM_TEXTURE_REPEAT_DEFAULT
		if gpu_state is Array and gpu_state.size() >= 3:
			material = gpu_state[0]
			filter = int(gpu_state[1])
			repeat = int(gpu_state[2])
		var item = segments[index]
		if not is_same(segment_materials[index], material):
			RenderingServer.canvas_item_set_material(item, material.get_rid() if material is Material else RID())
			segment_materials[index] = material
		if int(segment_filters[index]) != filter:
			RenderingServer.canvas_item_set_default_texture_filter(item, filter)
			segment_filters[index] = filter
		if int(segment_repeats[index]) != repeat:
			RenderingServer.canvas_item_set_default_texture_repeat(item, repeat)
			segment_repeats[index] = repeat
		segment_states[index] = gpu_state
		segment_versions[index] = gpu_version

	static func _states_match(left, right):
		if not (left is Array) or not (right is Array):
			return left == null and right == null
		if left.size() != right.size():
			return false
		for index in range(left.size()):
			if typeof(left[index]) != typeof(right[index]):
				return false
			if left[index] is Object or right[index] is Object:
				if not is_same(left[index], right[index]):
					return false
			elif left[index] != right[index]:
				return false
		return true


# Generated draw events open with gml_draw_begin(self, "<event method>") and
# close with gml_draw_end(). Inside a dispatched event the begin call shares the
# dispatcher's context; otherwise it opens a context of its own.
static func gml_draw_begin(target, context_name = "draw"):
	var phase = _gml_draw_context_phase(context_name)
	var dispatch = _gml_draw_dispatch_context
	if dispatch is Dictionary and is_same(dispatch.get("target", null), target) and str(dispatch.get("phase", "")) == phase:
		_gml_draw_context_stack.append(dispatch)
		return null
	if not _gml_draw_dispatch_active:
		_gml_camera_update_visible_views()
	_gml_draw_context_stack.append({
		"target": target,
		"context": str(context_name),
		"phase": phase,
		"sink": null
	})
	return null


static func gml_draw_end():
	if not _gml_draw_context_stack.is_empty():
		_gml_draw_context_stack.pop_back()
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


# The dispatch trace is a debugging aid; recording it costs time every frame, so
# it is off until enabled.
static func gm2godot_draw_event_trace_enable(enabled = true):
	_gml_draw_trace_enabled = bool(enabled)
	return null


# Runs one GameMaker draw frame: every phase in GameMaker order, instances in
# depth order (deepest first, then layer/tree order). Draw state set with
# draw_set_* persists across instances, events and frames like GameMaker.
static func gml_draw_event_dispatch_frame(instances = null):
	if _gml_draw_dispatch_active:
		return 0
	_gml_draw_dispatch_active = true
	_gml_draw_frame_serial += 1
	_gml_draw_used_materials.clear()
	if gml_application_surface_is_enabled():
		_gml_application_surface_apply_pending_resize()
		_gml_application_surface_ensure()
	_gml_camera_update_visible_views()
	# Backgrounds are drawn over the area of the view in every Draw of the
	# room (yyRoom.js DrawLayerBackgroundElement), also in the first frame
	# of a room entered during this frame's step, whose own _process has not
	# run yet.
	_gml_room_update_background_layers(_gml_draw_scene_root())
	_gml_draw_sinks_begin_frame()
	_gml_depth_flush()
	if _gml_draw_trace_enabled:
		_gml_draw_trace_trim()
	var creation_mark = _gml_instance_creation_counter
	var plan = _gml_draw_frame_plan(instances)
	var phase_lists = plan["phases"]
	var dispatched = 0
	# Draw Begin, Draw and Draw End run for the room's views; with views
	# enabled and none visible they do not run (yyRoom.js DrawViews).
	var room_drawn = _gml_view_room_drawn(_gml_view_active_state())
	for index in range(GML_DRAW_EVENT_PHASES.size()):
		var phase = GML_DRAW_EVENT_PHASES[index]
		if not room_drawn and GML_DRAW_ROOM_PHASES.has(phase["phase"]):
			continue
		dispatched += _gml_draw_dispatch_phase(phase, phase_lists[index], plan)
	_gml_draw_frame_finish(plan["drawers"], creation_mark)
	_gml_draw_dispatch_active = false
	_gml_draw_apply_pending_depths()
	_gml_depth_flush()
	return dispatched


static func gm2godot_draw_runtime_shutdown():
	for key in _gml_draw_sinks.keys():
		_gml_draw_release_sink(key)
	_gml_draw_sinks.clear()
	_gml_draw_space_layers.clear()
	_gml_draw_context_stack.clear()
	_gml_draw_dispatch_context = null
	_gml_draw_dispatch_active = false
	_gml_draw_used_materials.clear()
	_gml_draw_blend_materials.clear()
	_gml_draw_material_pool.clear()
	_gml_draw_script_methods.clear()
	_gml_draw_hidden_visuals.clear()
	_gml_draw_pending_depths.clear()
	_gml_depth_nodes.clear()
	_gml_depth_values.clear()
	_gml_depth_ranked = false
	_gml_depth_ranked_z.clear()
	_gml_depth_dirty = false
	_gml_draw_group_scan_counter = -1
	_gml_draw_gpu_state_cache = null
	_gml_draw_gpu_state_cache_version = -1
	return null


static func gm2godot_draw_debug_snapshot():
	var sinks = []
	for key in _gml_draw_sinks.keys():
		var sink = _gml_draw_sinks[key]
		if sink is GMLDrawSink:
			sinks.append(sink.snapshot())
	return sinks


static func gm2godot_draw_debug_sink_for(target, phase = "draw"):
	var space = str(GML_DRAW_PHASE_SPACES.get(str(phase), GML_DRAW_SPACE_INSTANCE))
	var key = "space:" + space
	if space == GML_DRAW_SPACE_INSTANCE and target is Object:
		key = target.get_instance_id()
	var sink = _gml_draw_sinks.get(key, null)
	if sink is GMLDrawSink:
		return sink.snapshot()
	return {}


# Numeric draw arguments are almost always plain numbers; those skip the type
# dispatch in _to_real, everything else goes through it.
static func _gml_draw_real(value):
	var value_type = typeof(value)
	if value_type == TYPE_FLOAT:
		return value
	if value_type == TYPE_INT or value_type == TYPE_BOOL:
		return float(value)
	return _to_real(value)


# GameMaker depth is an integer: fractional depths are truncated toward zero.
static func gml_depth_truncate(depth):
	var value = _gml_draw_real(depth)
	if is_nan(value):
		return 0
	return int(clamp(value, -GML_DEPTH_INTEGER_LIMIT, GML_DEPTH_INTEGER_LIMIT))


# The absolute z_index a GameMaker depth draws at.
static func gml_depth_to_z_index(depth):
	return _gml_depth_z(gml_depth_truncate(depth))


static func _gml_depth_z(depth):
	if _gml_depth_ranked:
		var z_value = _gml_depth_ranked_z.get(depth, null)
		if z_value != null:
			return z_value
	return clampi(-depth, -GML_DEPTH_Z_LIMIT, GML_DEPTH_Z_LIMIT)


# Gives node the absolute z_index of a truncated GameMaker depth and tracks it.
# A depth beyond Godot's z_index range, or one the ranking has no z_index for
# yet, re-ranks the depths in use before the next frame is drawn.
static func _gml_depth_track(node, depth):
	var node_id = node.get_instance_id()
	var previous = _gml_depth_values.get(node_id, null)
	if previous != depth:
		if previous == null:
			_gml_depth_nodes[node_id] = node
		_gml_depth_values[node_id] = depth
		if _gml_depth_ranked:
			if not _gml_depth_ranked_z.has(depth):
				_gml_depth_dirty = true
		elif depth < -GML_DEPTH_Z_LIMIT or depth > GML_DEPTH_Z_LIMIT:
			_gml_depth_dirty = true
	if node.z_as_relative:
		node.z_as_relative = false
	var z_value = _gml_depth_z(depth)
	if node.z_index != z_value:
		node.z_index = z_value


static func _gml_depth_forget(node_id):
	if _gml_depth_values.erase(node_id):
		_gml_depth_nodes.erase(node_id)


# Each distinct depth in use keeps -depth where the depths around it leave
# room in Godot's z_index range and is ranked into the range where they do
# not, so distinct depths stay strictly ordered (up to 8193 at once, the size
# of the range). The converter ranks room layers the same way.
static func _gml_depth_flush():
	if not _gml_depth_dirty:
		return
	_gml_depth_dirty = false
	var in_use = {}
	for node_id in _gml_depth_values.keys():
		if not is_instance_valid(_gml_depth_nodes[node_id]):
			_gml_depth_forget(node_id)
			continue
		in_use[_gml_depth_values[node_id]] = true
	var depths = in_use.keys()
	depths.sort()
	var count = depths.size()
	_gml_depth_ranked = count > 0 and (depths[0] < -GML_DEPTH_Z_LIMIT or depths[count - 1] > GML_DEPTH_Z_LIMIT)
	_gml_depth_ranked_z = {}
	if _gml_depth_ranked:
		for index in range(count):
			var depth = depths[index]
			# index depths draw above this one and count - 1 - index below it.
			var lowest = -GML_DEPTH_Z_LIMIT + count - 1 - index
			var z_value = lowest if -depth < lowest else mini(-depth, GML_DEPTH_Z_LIMIT - index)
			_gml_depth_ranked_z[depth] = clampi(z_value, -GML_DEPTH_Z_LIMIT, GML_DEPTH_Z_LIMIT)
	for node_id in _gml_depth_values.keys():
		var node = _gml_depth_nodes[node_id]
		var z_value = _gml_depth_z(_gml_depth_values[node_id])
		if node.z_index != z_value:
			node.z_index = z_value


# A new room keeps the tracked nodes that still exist (persistent instances);
# its layers are then registered and the depths in use ranked again.
static func _gml_depth_room_reset():
	for node_id in _gml_depth_values.keys():
		if not is_instance_valid(_gml_depth_nodes[node_id]):
			_gml_depth_forget(node_id)
	_gml_depth_dirty = true


# Assigning depth moves a GameMaker instance to (a layer at) that depth.
# GameMaker only does this when the value differs from what depth reads
# (yyInstance.js depth setter). GameMaker applies a depth set while drawing
# after the draw events, so the instance keeps its place for the rest of that
# frame. Returns the stored depth value.
static func gml_instance_depth_assign(instance, value, current = null):
	var resolved = _to_real(value)
	if current != null and is_numeric(current) and gml_instance_depth_get(instance, _to_real(current)) == resolved:
		return current
	if instance is Object:
		instance.set_meta(GML_EXPLICIT_DEPTH_META, true)
	if instance is CanvasItem:
		if _gml_draw_dispatch_active:
			_gml_draw_pending_depths[instance.get_instance_id()] = resolved
		else:
			_gml_instance_apply_depth_z(instance, resolved)
	return resolved


# GameMaker moves an instance whose depth no longer truncates to its layer's
# depth off that layer onto the managed layer at the new depth (yyRoom.js
# ProcessDepthList2, LayerManager.AddInstance): the room layer's visibility,
# position and layer_destroy no longer affect it. Here it moves to the room's
# managed layer node, keeping x and y, and draws at its depth's own z_index.
# An instance a sequence plays stays in the sequence.
static func _gml_instance_apply_depth_z(instance, depth):
	var truncated = gml_depth_truncate(depth)
	if not bool(instance.get_meta("gamemaker_in_sequence", false)):
		var parent = instance.get_parent()
		if parent != null and parent.has_meta(GML_MANAGED_LAYER_DEPTH_META):
			if int(parent.get_meta(GML_MANAGED_LAYER_DEPTH_META)) != truncated and parent.get_parent() != null:
				_gml_managed_layer_add(parent.get_parent(), instance, truncated, true)
		else:
			var layer_depth = _gml_instance_layer_depth(instance)
			if layer_depth != null and gml_depth_truncate(layer_depth) == truncated:
				return
			var room_root = _gml_instance_layer_room_root(instance)
			if room_root != null:
				_gml_managed_layer_add(room_root, instance, truncated)
	_gml_depth_track(instance, truncated)


# The node holding the outermost layer node an instance is on.
static func _gml_instance_layer_room_root(instance):
	var room_root = null
	var node = instance.get_parent()
	while node != null:
		if node.has_meta(&"gm2godot_room_root_policy"):
			return node
		if node.has_meta(&"gamemaker_layer_depth") or node.has_meta(GML_MANAGED_LAYER_DEPTH_META):
			room_root = node.get_parent()
		node = node.get_parent()
	return room_root


# Moves an instance node between layer nodes without ending it. A parent that
# is still adding its children cannot lose or gain one, so the move then waits
# until the end of the frame.
static func _gml_instance_move_to_parent(instance, parent, keep_global_transform = false):
	var current_parent = instance.get_parent()
	if current_parent == parent:
		return
	var busy = (current_parent != null and not current_parent.is_node_ready()) or not parent.is_node_ready()
	if busy:
		(func(): _gml_instance_move_now(instance, parent, keep_global_transform)).call_deferred()
		return
	_gml_instance_move_now(instance, parent, keep_global_transform)


static func _gml_instance_move_now(instance, parent, keep_global_transform):
	if not is_instance_valid(instance) or not is_instance_valid(parent) or instance.is_queued_for_deletion():
		return
	var current_parent = instance.get_parent()
	if current_parent == parent:
		return
	instance.set_meta(GML_LAYER_MOVE_META, true)
	if current_parent != null:
		instance.reparent(parent, keep_global_transform)
	else:
		parent.add_child(instance)
	instance.remove_meta(GML_LAYER_MOVE_META)


static func _gml_draw_apply_pending_depths():
	if _gml_draw_pending_depths.is_empty():
		return
	var pending = _gml_draw_pending_depths
	_gml_draw_pending_depths = {}
	for instance_id in pending.keys():
		var instance = instance_from_id(instance_id)
		if instance is CanvasItem:
			_gml_instance_apply_depth_z(instance, pending[instance_id])


# An instance on a layer has that layer's depth until depth is assigned (which
# moves it to its own depth), so layer_depth changes show through.
static func gml_instance_depth_get(instance, current = 0.0):
	if not (instance is Node) or instance.has_meta(GML_EXPLICIT_DEPTH_META):
		return current
	var layer_depth = _gml_instance_layer_depth(instance)
	return current if layer_depth == null else layer_depth


static func gml_instance_depth_initial(instance, current = 0.0):
	if instance is Object and instance.has_meta(GML_EXPLICIT_DEPTH_META):
		return current
	var layer_depth = _gml_instance_layer_depth(instance)
	if layer_depth != null:
		return layer_depth
	return current


static func _gml_instance_layer_depth(instance):
	if not (instance is Node):
		return null
	var node = instance.get_parent()
	while node != null:
		if node.has_meta(&"gamemaker_layer_depth"):
			return _gml_draw_real(node.get_meta(&"gamemaker_layer_depth"))
		if node.has_meta(&"gm2godot_room_root_policy"):
			return null
		node = node.get_parent()
	return null


static func _gml_draw_target():
	if _gml_draw_context_stack.is_empty():
		return null
	if _gml_surface_has_active_target():
		return null
	var context = _gml_draw_context_stack[_gml_draw_context_stack.size() - 1]
	var sink = context.get("sink", null)
	if not (sink is GMLDrawSink) or not sink.is_valid():
		sink = _gml_draw_sink_for(context.get("target", null), str(context.get("phase", "draw")))
		context["sink"] = sink
	if not (sink is GMLDrawSink):
		return null
	sink.begin_frame(_gml_draw_frame_serial)
	sink.set_gpu_state(_gml_draw_gpu_version, _gml_draw_gpu_state())
	return sink


static func _gml_draw_current_context_target():
	if _gml_draw_context_stack.is_empty():
		return null
	return _gml_draw_context_stack[_gml_draw_context_stack.size() - 1]["target"]


static func _gml_draw_context_phase(context_name):
	var name = str(context_name)
	if GML_DRAW_CONTEXT_PHASES.has(name):
		return str(GML_DRAW_CONTEXT_PHASES[name])
	if GML_DRAW_PHASE_SPACES.has(name):
		return name
	return "draw"


static func _gml_draw_sink_for(target, phase):
	var space = str(GML_DRAW_PHASE_SPACES.get(str(phase), GML_DRAW_SPACE_INSTANCE))
	if space != GML_DRAW_SPACE_INSTANCE:
		return _gml_draw_space_sink(space)
	if target is CanvasItem and is_instance_valid(target) and target.is_inside_tree():
		return _gml_draw_instance_sink(target)
	return _gml_draw_space_sink(GML_DRAW_SPACE_END)


# Instance sinks are keyed by the instance id, phase sinks by "space:<name>".
static func _gml_draw_instance_sink(inst):
	var key = inst.get_instance_id()
	var sink = _gml_draw_sinks.get(key, null)
	if not (sink is GMLDrawSink) or not sink.is_valid():
		sink = GMLDrawSink.new("instance:" + str(key), GML_DRAW_SPACE_INSTANCE, _gml_draw_used_materials)
		sink.registry_key = key
		sink.viewport_source = weakref(inst)
		_gml_draw_sinks[key] = sink
		_gml_draw_watch_sink_host(sink, inst)
	_gml_draw_attach_instance_sink(sink, inst)
	return sink


# Instance Draw output is parented under the instance's own canvas item so it
# sorts exactly where the instance sorts (its layer z, then tree order). The sink
# transform undoes the instance transform, so commands use the coordinates the
# instance's x and y are in: its parent's (layer) space, or canvas space for
# instances driven by a sequence.
static func _gml_draw_attach_instance_sink(sink, inst):
	if not (inst is CanvasItem) or not inst.is_inside_tree():
		sink.detach()
		return
	var local = inst.get_transform()
	if bool(inst.get_meta("gamemaker_in_sequence", false)):
		local = inst.get_global_transform()
	if abs(local.determinant()) > 0.0000001:
		if not (sink.space_node is WeakRef) or not is_same(sink.space_node.get_ref(), inst):
			sink.space_node = weakref(inst)
		sink.attach(inst.get_canvas_item(), GML_DRAW_SINK_CHILD_DRAW_INDEX, local.affine_inverse(), 0, true)
		return
	var parent = inst.get_parent()
	if parent is CanvasItem:
		sink.space_node = weakref(parent)
		sink.attach(parent.get_canvas_item(), inst.get_index(), Transform2D.IDENTITY, inst.z_index, inst.z_as_relative)
		return
	sink.space_node = null
	sink.attach(inst.get_canvas(), inst.get_index(), Transform2D.IDENTITY, inst.z_index, inst.z_as_relative)


static func _gml_draw_space_sink(space):
	var key = "space:" + str(space)
	var host = _gml_draw_space_layer(space)
	var sink = _gml_draw_sinks.get(key, null)
	if sink is GMLDrawSink and host != null and sink.host_id != host.get_instance_id():
		_gml_draw_release_sink(key)
		sink = null
	if not (sink is GMLDrawSink) or not sink.is_valid():
		sink = GMLDrawSink.new(key, space, _gml_draw_used_materials)
		_gml_draw_sinks[key] = sink
		if host != null:
			sink.viewport_source = weakref(host)
			sink.space_node = weakref(host)
			_gml_draw_watch_sink_host(sink, host)
	if host == null:
		sink.detach()
		return sink
	var xform = Transform2D.IDENTITY
	var spec = GML_DRAW_SPACE_LAYER_SPECS.get(str(space), {})
	if bool(spec.get("room_space", false)):
		var scene = host.get_parent()
		if scene is CanvasItem:
			xform = scene.get_global_transform()
	sink.attach(host.get_canvas(), GML_DRAW_SINK_CHILD_DRAW_INDEX, xform, 0, true)
	return sink


static func _gml_draw_scene_root():
	var loop = Engine.get_main_loop()
	if not (loop is SceneTree):
		return null
	var scene = loop.current_scene
	if scene is Node and is_instance_valid(scene) and scene.is_inside_tree():
		return scene
	return null


static func _gml_draw_space_layer(space):
	var scene = _gml_draw_scene_root()
	if scene == null:
		return null
	var cached = _gml_draw_space_layers.get(str(space), null)
	if cached is WeakRef:
		var node = cached.get_ref()
		if node is CanvasLayer and node.is_inside_tree() and is_same(node.get_parent(), scene) and not node.is_queued_for_deletion():
			return node
	var layer = null
	if str(space) == GML_DRAW_SPACE_GUI:
		layer = _gml_draw_gui_layer(scene)
	elif GML_DRAW_SPACE_LAYER_SPECS.has(str(space)):
		layer = _gml_draw_phase_layer(scene, GML_DRAW_SPACE_LAYER_SPECS[str(space)], str(space))
	if layer != null:
		_gml_draw_space_layers[str(space)] = weakref(layer)
	return layer


static func _gml_draw_phase_layer(scene, spec, space):
	var layer = scene.get_node_or_null(NodePath(str(spec["name"])))
	if layer is CanvasLayer and not layer.is_queued_for_deletion():
		return layer
	layer = CanvasLayer.new()
	layer.name = str(spec["name"])
	layer.layer = int(spec["layer"])
	layer.follow_viewport_enabled = bool(spec["follow_viewport"])
	if not bool(spec["room_space"]):
		layer.transform = _gml_display_window_to_viewport_transform()
	layer.set_meta("gm2godot_draw_space", space)
	scene.add_child(layer, false, Node.INTERNAL_MODE_BACK)
	return layer


static func _gml_draw_gui_layer(scene):
	var layer = scene.get_node_or_null(NodePath(GML_DRAW_GUI_LAYER_NAME))
	if layer is CanvasLayer and not layer.is_queued_for_deletion():
		return layer
	for child in scene.get_children():
		if child is CanvasLayer and child.has_meta("gm2godot_gui_layer_policy") and not child.is_queued_for_deletion():
			return child
	layer = CanvasLayer.new()
	layer.name = GML_DRAW_GUI_LAYER_NAME
	layer.layer = GML_DRAW_GUI_LAYER_INDEX
	layer.set_meta("gm2godot_gui_layer_policy", "gm_gui_canvas_layer")
	layer.set_meta("gamemaker_layer_element_type", "draw_gui")
	layer.set_meta("gamemaker_event_queue", "GMDraw")
	scene.add_child(layer)
	return layer


static func _gml_draw_watch_sink_host(sink, host):
	if not (host is Node):
		return
	sink.host_id = host.get_instance_id()
	var key = sink.registry_key
	var callable = func(): _gml_draw_sink_host_exiting(key)
	host.tree_exiting.connect(callable)
	sink.host_exit_callable = callable


# An instance moving to another layer keeps drawing into its sink: the sink
# hangs off the instance's own canvas item, which the move keeps.
static func _gml_draw_sink_host_exiting(key):
	var sink = _gml_draw_sinks.get(key, null)
	if sink is GMLDrawSink and sink.host_id != 0:
		var host = instance_from_id(sink.host_id)
		if host is Node and host.has_meta(GML_LAYER_MOVE_META):
			return
	_gml_draw_release_sink(key)


static func _gml_draw_release_sink(key):
	var sink = _gml_draw_sinks.get(key, null)
	_gml_draw_sinks.erase(key)
	if not (sink is GMLDrawSink):
		return
	var host = instance_from_id(sink.host_id) if sink.host_id != 0 else null
	var callable = sink.host_exit_callable
	if host is Node and callable is Callable and host.tree_exiting.is_connected(callable):
		host.tree_exiting.disconnect(callable)
	sink.host_exit_callable = null
	sink.free_rids()


static func _gml_draw_sinks_begin_frame():
	for key in _gml_draw_sinks.keys():
		var sink = _gml_draw_sinks.get(key, null)
		if not (sink is GMLDrawSink):
			_gml_draw_sinks.erase(key)
			continue
		var host = instance_from_id(sink.host_id) if sink.host_id != 0 else null
		if not (host is Node) or not host.is_inside_tree():
			_gml_draw_release_sink(key)
			continue
		sink.begin_frame(_gml_draw_frame_serial)
	for instance_id in _gml_draw_hidden_visuals.keys():
		if instance_from_id(instance_id) == null:
			_gml_draw_hidden_visuals.erase(instance_id)


# The frame's instances in draw order, split per phase into the instances that
# have that event. Instances without a Draw event are default-drawn by their
# generated sprite node.
static func _gml_draw_frame_plan(instances):
	var phase_lists = []
	for _phase in GML_DRAW_EVENT_PHASES:
		phase_lists.append([])
	var drawers = []
	var defaults = []
	for inst in _gml_draw_ordered_instances(instances):
		var info = _gml_draw_instance_event_info(inst)
		for index in info["phases"]:
			phase_lists[index].append(inst)
		if info["draw"]:
			drawers.append(inst)
		else:
			defaults.append(inst)
	return {"phases": phase_lists, "drawers": drawers, "defaults": defaults}


static func _gml_draw_ordered_instances(instances):
	var nodes = []
	if instances is Array:
		for inst in instances:
			if is_instance_valid(inst) and inst is Node and inst.is_inside_tree() and not nodes.has(inst):
				nodes.append(inst)
		nodes.sort_custom(_gml_draw_tree_order_less)
	else:
		nodes = _gml_draw_registered_instances()
	return _gml_draw_sort_by_depth(nodes)


static func _gml_draw_tree_order_less(left, right):
	return right.is_greater_than(left)


# Live registered instances in scene tree order.
static func _gml_draw_registered_instances():
	var loop = Engine.get_main_loop()
	if not (loop is SceneTree):
		return []
	# New registrations bump the creation counter; a group count that differs
	# from the registry also triggers a rescan (instances outside the tree).
	if _gml_draw_group_scan_counter != _gml_instance_creation_counter or loop.get_node_count_in_group(GML_DRAW_INSTANCE_GROUP) != _gml_instance_entries.size():
		_gml_draw_group_scan_counter = _gml_instance_creation_counter
		for entry in _gml_instance_entries.values():
			var inst = entry["instance"]
			if is_instance_valid(inst) and inst is Node and not inst.is_in_group(GML_DRAW_INSTANCE_GROUP):
				inst.add_to_group(GML_DRAW_INSTANCE_GROUP)
	var nodes = []
	for inst in loop.get_nodes_in_group(GML_DRAW_INSTANCE_GROUP):
		var handle = _gml_instance_handles_by_node_id.get(inst.get_instance_id(), null)
		var entry = _gml_instance_entries.get(handle.index, null) if handle != null else null
		if entry == null:
			inst.remove_from_group(GML_DRAW_INSTANCE_GROUP)
			continue
		if bool(entry["destroyed"]) or inst.is_queued_for_deletion():
			continue
		nodes.append(inst)
	return nodes


# Orders nodes from the highest depth to the lowest; nodes at the same
# (truncated) depth keep their given (tree) order. Instances that draw with
# their layer (relative z_index) have its depth, looked up once per parent
# node; the others draw at their own depth's z_index.
static func _gml_draw_sort_by_depth(nodes):
	var buckets = {}
	var depths = []
	var layer_depths = {}
	for inst in nodes:
		var depth = null
		if not (inst is CanvasItem) or inst.z_as_relative:
			var parent = inst.get_parent()
			if layer_depths.has(parent):
				depth = layer_depths[parent]
			else:
				depth = _gml_instance_layer_depth(inst)
				if depth != null:
					depth = gml_depth_truncate(depth)
				layer_depths[parent] = depth
		if depth == null:
			depth = gml_depth_truncate(_gml_draw_instance_depth(inst))
		var bucket = buckets.get(depth, null)
		if bucket == null:
			bucket = []
			buckets[depth] = bucket
			depths.append(depth)
		bucket.append(inst)
	if depths.size() <= 1:
		return nodes
	depths.sort()
	var ordered = []
	for index in range(depths.size() - 1, -1, -1):
		ordered.append_array(buckets[depths[index]])
	return ordered


static func _gml_draw_instance_depth(inst):
	var value = inst.get("depth") if inst is Object else null
	var value_type = typeof(value)
	if value_type == TYPE_FLOAT:
		return 0.0 if is_nan(value) else value
	if value_type == TYPE_INT:
		return float(value)
	if value != null and is_numeric(value):
		var depth = _to_real(value)
		return 0.0 if is_nan(depth) else depth
	if inst is CanvasItem:
		return -float(_gml_draw_effective_z(inst))
	return 0.0


static func _gml_draw_effective_z(item):
	var z_value = 0
	var node = item
	while node is CanvasItem:
		z_value += int(node.z_index)
		if not node.z_as_relative:
			break
		node = node.get_parent()
	return z_value


static func _gml_draw_instance_drawable(inst):
	if inst == null or not is_instance_valid(inst):
		return false
	if inst is Node and (not inst.is_inside_tree() or inst.is_queued_for_deletion()):
		return false
	if inst is CanvasItem:
		return inst.is_visible_in_tree()
	var value = gml_struct_get(inst, "visible")
	if not is_undefined(value) and not gml_bool(value):
		return false
	return true


# Which draw events an instance has (own or inherited), cached per script.
static func _gml_draw_instance_event_info(inst):
	var script = inst.get_script()
	var script_id = script.get_instance_id() if script is Script else 0
	if script_id != 0:
		var cached = _gml_draw_script_methods.get(script_id, null)
		if cached != null:
			return cached
	var phase_indices = []
	for index in range(GML_DRAW_EVENT_PHASES.size()):
		if inst.has_method(str(GML_DRAW_EVENT_PHASES[index]["method"])):
			phase_indices.append(index)
	var info = {
		"phases": phase_indices,
		"draw": inst.has_method("_on_draw"),
		"visual_method": inst.has_method("_gm_sprite_visual_node"),
	}
	if script_id != 0:
		_gml_draw_script_methods[script_id] = info
	return info


static func _gml_draw_dispatch_phase(phase, instances, plan):
	var phase_name = str(phase["phase"])
	var method_name = str(phase["method"])
	if _gml_draw_trace_enabled:
		_gml_draw_record_event(phase_name, "", null, "phase")
	var dispatched = 0
	if phase_name == "draw":
		dispatched += _gml_draw_count_default_draws(plan["defaults"])
	for inst in instances:
		if not _gml_draw_instance_drawable(inst):
			continue
		if _gml_draw_trace_enabled:
			_gml_draw_record_event(phase_name, method_name, inst, "custom")
		_gml_draw_invoke(inst, method_name, phase_name)
		dispatched += 1
	return dispatched


static func _gml_draw_count_default_draws(instances):
	var count = 0
	for inst in instances:
		if is_instance_valid(inst) and (not (inst is CanvasItem) or inst.is_visible_in_tree()):
			count += 1
			if _gml_draw_trace_enabled:
				_gml_draw_record_event("draw", "draw_self", inst, "default")
	return count


# The event's draw sink is resolved by the first draw call, so events that draw
# nothing create no canvas items or phase layers.
static func _gml_draw_invoke(inst, method_name, phase_name):
	var stack_size = _gml_draw_context_stack.size()
	var previous_dispatch = _gml_draw_dispatch_context
	var context = _gml_draw_invoke_context
	context["target"] = inst
	context["context"] = method_name
	context["phase"] = phase_name
	context["sink"] = null
	_gml_draw_dispatch_context = context
	_gml_draw_context_stack.append(context)
	inst.call(method_name)
	if _gml_draw_context_stack.size() > stack_size:
		_gml_draw_context_stack.resize(stack_size)
	_gml_draw_dispatch_context = previous_dispatch
	context["target"] = null
	context["sink"] = null


# After the Draw events ran: refresh the transform of instance sinks (the event
# may have moved the instance) and hide the sprite visual of every instance
# with a Draw event, including instances created while drawing.
static func _gml_draw_frame_finish(drawers, creation_mark):
	for inst in drawers:
		_gml_draw_finish_instance(inst)
	if _gml_instance_creation_counter == creation_mark:
		return
	var created_before = creation_mark if _gml_instance_creation_counter > creation_mark else 0
	for entry in _gml_instance_entries.values():
		if int(entry["creation_order"]) < created_before or bool(entry["destroyed"]):
			continue
		var inst = entry["instance"]
		if is_instance_valid(inst) and inst is CanvasItem and _gml_draw_instance_event_info(inst)["draw"]:
			_gml_draw_finish_instance(inst)


static func _gml_draw_finish_instance(inst):
	if not is_instance_valid(inst) or not (inst is CanvasItem) or not inst.is_inside_tree():
		return
	_gml_draw_hide_instance_sprite(inst)
	var sink = _gml_draw_sinks.get(inst.get_instance_id(), null)
	if sink is GMLDrawSink and sink.frame == _gml_draw_frame_serial:
		_gml_draw_attach_instance_sink(sink, inst)


# Instances with a Draw event (own or inherited) are not default-drawn, so the
# generated sprite visual is hidden; collision shapes keep working.
static func _gml_draw_hide_instance_sprite(inst):
	var instance_id = inst.get_instance_id()
	var cached = _gml_draw_hidden_visuals.get(instance_id, null)
	var visual = cached.get_ref() if cached is WeakRef else null
	if not (visual is CanvasItem) or visual.is_queued_for_deletion() or not inst.is_ancestor_of(visual):
		visual = _gml_draw_instance_visual(inst)
		if not (visual is CanvasItem):
			_gml_draw_hidden_visuals.erase(instance_id)
			return
		_gml_draw_hidden_visuals[instance_id] = weakref(visual)
	if visual.visible:
		visual.visible = false


static func _gml_draw_instance_visual(inst):
	if _gml_draw_instance_event_info(inst)["visual_method"]:
		var generated_visual = inst.call("_gm_sprite_visual_node")
		return generated_visual if generated_visual is CanvasItem else null
	for child in inst.get_children():
		if child is Sprite2D or child is AnimatedSprite2D:
			return child
		var visual = _gml_draw_find_sprite_visual(child)
		if visual != null:
			return visual
	return null


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
		entry["depth"] = int(_gml_draw_instance_depth(inst))
	_gml_draw_event_trace.append(entry)
	return null


static func _gml_draw_trace_trim():
	if _gml_draw_event_trace.size() > GML_DRAW_EVENT_TRACE_LIMIT:
		_gml_draw_event_trace = _gml_draw_event_trace.slice(_gml_draw_event_trace.size() - int(GML_DRAW_EVENT_TRACE_LIMIT / 2))


# GPU state setters call this; the next draw command starts a new canvas item
# segment when the effective state differs from the current segment's state.
static func _gml_draw_apply_gpu_state(_target = null):
	_gml_draw_gpu_version += 1
	return null


static func _gml_draw_gpu_state():
	if _gml_draw_gpu_state_cache_version == _gml_draw_gpu_version and _gml_draw_gpu_state_cache is Array:
		return _gml_draw_gpu_state_cache
	_gml_draw_defaults_resolve()
	var material = null
	var shader_material = _gml_draw_state["shader_material"]
	if shader_material is ShaderMaterial:
		material = shader_material
	else:
		material = _gml_draw_blend_material(_gml_draw_state["blend_mode"])
	var filter = RenderingServer.CANVAS_ITEM_TEXTURE_FILTER_LINEAR if bool(_gml_draw_state["texture_filter"]) else RenderingServer.CANVAS_ITEM_TEXTURE_FILTER_NEAREST
	var repeat = RenderingServer.CANVAS_ITEM_TEXTURE_REPEAT_ENABLED if bool(_gml_draw_state["texture_repeat"]) else RenderingServer.CANVAS_ITEM_TEXTURE_REPEAT_DISABLED
	_gml_draw_gpu_state_cache = [material, filter, repeat]
	_gml_draw_gpu_state_cache_version = _gml_draw_gpu_version
	return _gml_draw_gpu_state_cache


static func _gml_draw_blend_material(blend_mode):
	var mode = _gml_draw_canvas_blend_mode(blend_mode)
	if mode == CanvasItemMaterial.BLEND_MODE_MIX:
		return null
	if not _gml_draw_blend_materials.has(mode):
		var material = CanvasItemMaterial.new()
		material.blend_mode = mode
		_gml_draw_blend_materials[mode] = material
	return _gml_draw_blend_materials[mode]


# Shader uniforms apply per draw call in GameMaker. When the active shader
# material already rendered commands this frame, later uniform changes go to a
# copy so the earlier commands keep the values they were drawn with.
static func _gml_draw_shader_material_for_write(material):
	if not (material is ShaderMaterial):
		return material
	if not is_same(_gml_draw_state["shader_material"], material):
		return material
	if not _gml_draw_used_materials.has(material.get_instance_id()):
		return material
	var copy = _gml_draw_material_copy(material)
	_gml_draw_state["shader_material"] = copy
	_gml_draw_apply_gpu_state()
	return copy


# Copies are pooled per base material and reused on later frames, after the
# commands that used them were cleared.
static func _gml_draw_material_copy(material):
	var base = material.get_meta("_gm2godot_material_base", material)
	if not (base is ShaderMaterial):
		base = material
	var base_id = base.get_instance_id()
	var pool = _gml_draw_material_pool.get(base_id, null)
	if not (pool is Dictionary) or pool.get("frame", -1) != _gml_draw_frame_serial:
		var copies = pool.get("copies", []) if pool is Dictionary else []
		pool = {"frame": _gml_draw_frame_serial, "copies": copies, "cursor": 0}
		_gml_draw_material_pool[base_id] = pool
	var copies = pool["copies"]
	var cursor = int(pool["cursor"])
	pool["cursor"] = cursor + 1
	var copy = null
	if cursor < copies.size():
		copy = copies[cursor]
	else:
		copy = ShaderMaterial.new()
		copy.set_meta("_gm2godot_material_base", base)
		copies.append(copy)
	copy.shader = material.shader
	var uniforms = material.shader.get_shader_uniform_list() if material.shader is Shader else []
	for uniform in uniforms:
		var name = str(uniform.get("name", ""))
		if name != "":
			copy.set_shader_parameter(name, material.get_shader_parameter(name))
	return copy
