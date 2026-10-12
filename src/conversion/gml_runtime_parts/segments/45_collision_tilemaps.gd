# GameMaker collisions with tilemaps.
#
# GameMaker's collision functions also take a tilemap element
# (layer_tilemap_get_id), alone or in an array next to objects and
# instances: place_meeting, place_empty, instance_place(_list),
# position_meeting, instance_position(_list), collision_point, _rectangle,
# _circle, _ellipse, _line and their _list versions, and move_and_collide.
# A hit reports the tilemap element: instance_place and collision_* return
# it and the _list functions add it. place_free, position_empty and
# distance_to_object only look at instances.
#
# The tests below are the runner's Tilemap_PointPlace,
# Tilemap_CollisionRectangle, Tilemap_CollisionLine,
# Tilemap_CollisionEllipse and Tilemap_InstancePlace (Function_Instance.js)
# with the yySprite tilemap tests they call, step for step:
# - Only the cells under the query's box are read. The box is put in cells
#   by truncating towards zero, so a box less than a cell to the left of or
#   above the tilemap reaches its first column or row.
# - A cell holding tile 0, or a tile past the tileset's tile count, is
#   empty. The tilemap's place is its x/y plus its layer's offset; whether
#   the layer is visible plays no part.
# - Tiles collide through the collision mask of the tileset's sprite: a
#   tileset without a sprite never collides. When that mask is not precise,
#   or the test is not precise, a tile fills its cell. Otherwise the test
#   reads the tile's part of the sprite's mask, mirrored, flipped and
#   rotated with the tile. An instance test is always precise and also goes
#   pixel by pixel when the instance's own mask is precise.
# Tiles do not animate here, so a tile collides as its first frame
# (GetAnimatedTileIndex at frame 0).
const GML_TILESET_SPRITE_META = "gamemaker_tileset_sprite"
const GML_TILESET_TILE_COUNT_META = "gamemaker_tileset_tile_count"
# The tile data bits the runner keeps: those of its global tile data mask
# (all) and of the tilemap's own (all but TileInherit).
const GML_TILEMAP_COLLISION_DATA_MASK = 0x7fffffff
# What JavaScript's ~~ gives is only followed up to here.
const GML_TILEMAP_COLLISION_INT_LIMIT = 2147483647.0


# The tilemap node a collision target names, or null.
static func _gml_collision_tilemap_node(target):
	if not is_handle(target) or target.kind != GML_LAYER_ELEMENT_HANDLE_KIND or not gml_handle_is_valid(target):
		return null
	var node = target.reference
	return node if node is TileMapLayer else null


static func _gml_collision_has_tilemap(target):
	if typeof(target) == TYPE_ARRAY:
		for element in target:
			if _gml_collision_has_tilemap(element):
				return true
		return false
	return _gml_collision_tilemap_node(target) != null


# The tilemap element a tilemap hit (see _gml_collision_find_with_tilemaps)
# stands for, or noone.
static func _gml_collision_tilemap_handle(node):
	if typeof(node) == TYPE_OBJECT and is_instance_valid(node) and node is TileMapLayer:
		var handle = _gml_layer_element_handle_for_node(node)
		if gml_handle_is_valid(handle):
			return handle
	return gml_instance_noone()


# _gml_collision_find for a tilemap or an array holding one. The runner goes
# through an array in order, testing each element, tilemap or not, in turn,
# so the first hit is that of the first element that has one, and a list
# gets the hits element after element. A tilemap hit is given as
# {"inst": the tilemap node, "tilemap": its element}.
static func _gml_collision_find_with_tilemaps(kind, query, target, current_self, notme, prec, every):
	if typeof(target) == TYPE_ARRAY:
		var hits = []
		for element in target:
			var found = _gml_collision_find(kind, query, element, current_self, notme, prec, every)
			if every:
				hits.append_array(found)
			elif found != null:
				return found
		return hits if every else null
	var node = _gml_collision_tilemap_node(target)
	if not _gml_tilemap_collision_test(kind, query, node, prec):
		return [] if every else null
	var hit = {"inst": node, "tilemap": target}
	return [hit] if every else hit


static func _gml_tilemap_collision_test(kind, query, node, prec):
	var tilemap = _gml_tilemap_collision_map(node)
	if tilemap == null:
		return false
	match kind:
		GML_COLLISION_QUERY_POINT:
			return _gml_tilemap_point_hit(tilemap, query[0], query[1], prec)
		GML_COLLISION_QUERY_RECTANGLE, GML_COLLISION_QUERY_ELLIPSE:
			return _gml_tilemap_area_hit(tilemap, kind, query[0], query[1], query[2], query[3], prec)
		GML_COLLISION_QUERY_LINE:
			# The line is made to run left to right first.
			if query[2] < query[0]:
				return _gml_tilemap_area_hit(tilemap, kind, query[2], query[3], query[0], query[1], prec)
			return _gml_tilemap_area_hit(tilemap, kind, query[0], query[1], query[2], query[3], prec)
		GML_COLLISION_QUERY_INSTANCE:
			return _gml_tilemap_instance_hit(tilemap, query)
	return false


# What the tests read from a tilemap, or null when it cannot collide.
static func _gml_tilemap_collision_map(node):
	var tile_set = node.tile_set
	if not (tile_set is TileSet):
		return null
	if not tile_set.has_meta(GML_TILESET_SPRITE_META):
		return null
	var sprite = _gml_collision_sprite_data(tile_set.get_meta(GML_TILESET_SPRITE_META))
	var tile_size = tile_set.tile_size
	if sprite == null or tile_size.x <= 0 or tile_size.y <= 0:
		return null
	var separation = Vector2i.ZERO
	if tile_set.get_source_count() > 0:
		var source = tile_set.get_source(tile_set.get_source_id(0))
		if source is TileSetAtlasSource:
			separation = source.separation
	var cells = node.get_meta("gamemaker_tile_raw_cells", {})
	var tiles = node.get_meta("gamemaker_tile_raw_values", [])
	return {
		"node": node,
		"cells": cells if cells is Dictionary else {},
		"tiles": tiles if tiles is Array else [],
		"width": int(node.get_meta("gamemaker_tile_width", 0)),
		"height": int(node.get_meta("gamemaker_tile_height", 0)),
		"left": float(node.position.x),
		"top": float(node.position.y),
		"tile_width": float(tile_size.x),
		"tile_height": float(tile_size.y),
		"step_u": tile_size.x + separation.x,
		"step_v": tile_size.y + separation.y,
		# The runner's numtilesperrow: not rounded.
		"per_row": float(sprite["width"]) / float(tile_size.x + separation.x),
		"tile_count": int(tile_set.get_meta(GML_TILESET_TILE_COUNT_META, -1)),
		"sprite": sprite,
		"mask": _gml_collision_frame_mask(sprite, 0),
		"precise": sprite["colcheck"] == GML_COLLISION_CHECK_PRECISE,
	}


# A cell's tile data, read as gml_tilemap_get reads it.
static func _gml_tilemap_collision_data(tilemap, x, y):
	var coords = Vector2i(x, y)
	var cells = tilemap["cells"]
	if cells.has(coords):
		return int(cells[coords])
	var tiles = tilemap["tiles"]
	var index = y * tilemap["width"] + x
	if index < tiles.size():
		return int(tiles[index])
	return max(int(gml_tilemap_get(tilemap["node"], x, y)), 0)


# The tile a cell's data shows, or 0 when the cell is empty for collisions.
static func _gml_tilemap_collision_index(tilemap, data):
	var index = data & GML_TILEMAP_INDEX_MASK
	var count = tilemap["tile_count"]
	if count >= 0 and index >= count:
		# Past the tileset's frame data (GetAnimatedTileIndex is undefined).
		return 0
	return index


# JavaScript's ~~value: towards zero, NaN and the infinities giving 0.
static func _gml_tilemap_collision_trunc(value):
	if not is_finite(value):
		return 0
	return int(clampf(value, -GML_TILEMAP_COLLISION_INT_LIMIT, GML_TILEMAP_COLLISION_INT_LIMIT))


# The runner's yymax and yymin (a NaN first argument gives the second).
static func _gml_tilemap_collision_max(a, b):
	return a if a > b else b


static func _gml_tilemap_collision_min(a, b):
	return a if a < b else b


# The cell's corners in room space: [left, top, right, bottom].
static func _gml_tilemap_collision_cell(tilemap, x, y):
	var left = tilemap["left"] + tilemap["tile_width"] * x
	var top = tilemap["top"] + tilemap["tile_height"] * y
	return [left, top, left + tilemap["tile_width"], top + tilemap["tile_height"]]


# How a precise test maps room positions in a cell to the tileset sprite
# (GenerateTileMapUVs and the scales the yySprite tests derive from it): the
# sprite position at the cell's top-left corner, how it changes along x and
# along y, and the part of the sprite the tile covers.
static func _gml_tilemap_collision_texels(tilemap, index, data, cell):
	var row = _gml_tilemap_collision_trunc(float(index) / tilemap["per_row"])
	var column = _gml_tilemap_collision_trunc(fmod(float(index), tilemap["per_row"]))
	var u0 = float(column * tilemap["step_u"])
	var v0 = float(row * tilemap["step_v"])
	# Top-left, top-right, bottom-right and bottom-left corners.
	var u = [u0, u0 + tilemap["tile_width"], u0 + tilemap["tile_width"], u0]
	var v = [v0, v0, v0 + tilemap["tile_height"], v0 + tilemap["tile_height"]]
	if (data & GML_TILEMAP_MIRROR) != 0:
		_gml_tilemap_collision_swap(u, v, 0, 1)
		_gml_tilemap_collision_swap(u, v, 2, 3)
	if (data & GML_TILEMAP_FLIP) != 0:
		_gml_tilemap_collision_swap(u, v, 3, 0)
		_gml_tilemap_collision_swap(u, v, 2, 1)
	if (data & GML_TILEMAP_ROTATE) != 0:
		u = [u[3], u[0], u[1], u[2]]
		v = [v[3], v[0], v[1], v[2]]
	var width = cell[2] - cell[0]
	var height = cell[3] - cell[1]
	return {
		"u": u[0],
		"v": v[0],
		"ux": (u[1] - u[0]) / width,
		"uy": (u[3] - u[0]) / height,
		"vx": (v[1] - v[0]) / width,
		"vy": (v[3] - v[0]) / height,
		"u_min": min(u[0], u[1], u[2]),
		"u_max": max(u[0], u[1], u[2]),
		"v_min": min(v[0], v[1], v[2]),
		"v_max": max(v[0], v[1], v[2]),
		"corners": [u, v],
	}


static func _gml_tilemap_collision_swap(u, v, first, second):
	var swap_u = u[first]
	u[first] = u[second]
	u[second] = swap_u
	var swap_v = v[first]
	v[first] = v[second]
	v[second] = swap_v


# Whether the tileset sprite's mask is set at a sprite position inside the
# tile (yySprite.ColMaskSet after the tile's bounds check).
static func _gml_tilemap_collision_texel(tilemap, texels, u, v):
	if v < texels["v_min"] or v >= texels["v_max"]:
		return false
	if u < texels["u_min"] or u >= texels["u_max"]:
		return false
	return _gml_collision_mask_set(tilemap["sprite"], tilemap["mask"], u, v, false)


# The same test for room position (i, j) in the cell.
static func _gml_tilemap_collision_texel_at(tilemap, texels, cell, i, j):
	var u = _gml_tilemap_collision_u(texels, cell, i, j)
	var v = _gml_tilemap_collision_v(texels, cell, i, j)
	return _gml_tilemap_collision_texel(tilemap, texels, u, v)


# --- Points --------------------------------------------------------------------

static func _gml_tilemap_point_hit(tilemap, px, py, prec):
	var tile_width = tilemap["tile_width"]
	var tile_height = tilemap["tile_height"]
	var x = _gml_tilemap_collision_trunc((px - tilemap["left"]) * (1.0 / tile_width))
	var y = _gml_tilemap_collision_trunc((py - tilemap["top"]) * (1.0 / tile_height))
	if x < 0 or y < 0 or x >= tilemap["width"] or y >= tilemap["height"]:
		return false
	var data = _gml_tilemap_collision_data(tilemap, x, y) & GML_TILEMAP_COLLISION_DATA_MASK
	var index = _gml_tilemap_collision_index(tilemap, data)
	if index <= 0:
		return false
	if not (prec and tilemap["precise"]):
		return true
	var cell = _gml_tilemap_collision_cell(tilemap, x, y)
	var corners = _gml_tilemap_collision_texels(tilemap, index, data, cell)["corners"]
	var u = corners[0]
	var v = corners[1]
	# The point is taken to the pixel it rounds to.
	var xfrac = ((px + 0.5) - cell[0]) / tile_width
	var yfrac = ((py + 0.5) - cell[1]) / tile_height
	var ui = _gml_tilemap_collision_trunc(u[0] + xfrac * (u[1] - u[0]) + yfrac * (u[3] - u[0]))
	var vi = _gml_tilemap_collision_trunc(v[0] + xfrac * (v[1] - v[0]) + yfrac * (v[3] - v[0]))
	var sprite = tilemap["sprite"]
	if ui < 0 or ui >= int(sprite["width"]) or vi < 0 or vi >= int(sprite["height"]):
		return false
	return _gml_collision_mask_set(sprite, tilemap["mask"], ui, vi, false)


# --- Rectangles, ellipses and lines ------------------------------------------

# The cells under the box with corners (x1, y1) and (x2, y2): [left, top,
# right, bottom], inclusive.
static func _gml_tilemap_collision_cells(tilemap, x1, y1, x2, y2):
	var rcp_width = 1.0 / tilemap["tile_width"]
	var rcp_height = 1.0 / tilemap["tile_height"]
	var l = (x1 - tilemap["left"]) * rcp_width
	var r = (x2 - tilemap["left"]) * rcp_width
	var t = (y1 - tilemap["top"]) * rcp_height
	var b = (y2 - tilemap["top"]) * rcp_height
	if r < l:
		var swap_x = l
		l = r
		r = swap_x
	if t > b:
		var swap_y = t
		t = b
		b = swap_y
	return [
		_gml_tilemap_collision_trunc(_gml_tilemap_collision_max(l, 0.0)),
		_gml_tilemap_collision_trunc(_gml_tilemap_collision_max(t, 0.0)),
		_gml_tilemap_collision_trunc(_gml_tilemap_collision_min(r, float(tilemap["width"] - 1))),
		_gml_tilemap_collision_trunc(_gml_tilemap_collision_min(b, float(tilemap["height"] - 1))),
	]


static func _gml_tilemap_area_hit(tilemap, kind, x1, y1, x2, y2, prec):
	var cells = _gml_tilemap_collision_cells(tilemap, x1, y1, x2, y2)
	var precise = prec and tilemap["precise"]
	for x in range(cells[0], cells[2] + 1):
		for y in range(cells[1], cells[3] + 1):
			var data = _gml_tilemap_collision_data(tilemap, x, y) & GML_TILEMAP_COLLISION_DATA_MASK
			var index = _gml_tilemap_collision_index(tilemap, data)
			if index <= 0:
				continue
			if kind == GML_COLLISION_QUERY_RECTANGLE and not precise:
				return true
			var cell = _gml_tilemap_collision_cell(tilemap, x, y)
			var texels = _gml_tilemap_collision_texels(tilemap, index, data, cell) if precise else null
			if _gml_tilemap_area_cell_hit(tilemap, kind, cell, texels, x1, y1, x2, y2):
				return true
	return false


static func _gml_tilemap_area_cell_hit(tilemap, kind, cell, texels, x1, y1, x2, y2):
	match kind:
		GML_COLLISION_QUERY_RECTANGLE:
			return _gml_tilemap_precise_rectangle(tilemap, cell, texels, x1, y1, x2, y2)
		GML_COLLISION_QUERY_ELLIPSE:
			return _gml_tilemap_ellipse(tilemap, cell, texels, x1, y1, x2, y2)
		GML_COLLISION_QUERY_LINE:
			if texels == null:
				return _gml_tilemap_line(cell, x1, y1, x2, y2)
			return _gml_tilemap_precise_line(tilemap, cell, texels, x1, y1, x2, y2)
	return false


# The sprite position a precise test samples at (i, j) in a cell, in the
# runner's order of operations.
static func _gml_tilemap_collision_u(texels, cell, i, j):
	return ((i - cell[0]) * texels["ux"] + texels["u"]) + ((j - cell[1]) * texels["uy"])


static func _gml_tilemap_collision_v(texels, cell, i, j):
	return ((j - cell[1]) * texels["vy"] + texels["v"]) + ((i - cell[0]) * texels["vx"])


# yySprite.PreciseCollisionTilemapRect: the rectangle's whole pixels in the
# cell, from its first corner towards its second.
static func _gml_tilemap_precise_rectangle(tilemap, cell, texels, xl, yl, xr, yr):
	var l = _gml_tilemap_collision_trunc(floor(_gml_tilemap_collision_max(xl, cell[0])) + 0.5)
	var r = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(xr, cell[2]))
	var t = _gml_tilemap_collision_trunc(floor(_gml_tilemap_collision_max(yl, cell[1])) + 0.5)
	var b = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(yr, cell[3]))
	if l >= r or t >= b:
		return false
	if tilemap["mask"] == null:
		return true
	for i in range(l, r):
		var u = _gml_tilemap_collision_u(texels, cell, i, t)
		var v = _gml_tilemap_collision_v(texels, cell, i, t)
		for j in range(t, b):
			if _gml_tilemap_collision_texel(tilemap, texels, u, v):
				return true
			v += texels["vy"]
			u += texels["uy"]
	return false


# yySprite.CollisionTilemapEllipse and PreciseCollisionTilemapEllipse: the
# whole pixels of the cell (and the one past its right and bottom edges)
# inside the ellipse.
static func _gml_tilemap_ellipse(tilemap, cell, texels, xl, yl, xr, yr):
	var l = _gml_tilemap_collision_trunc(floor(_gml_tilemap_collision_max(xl, cell[0])) + 0.5)
	var r = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(xr, cell[2]))
	var t = _gml_tilemap_collision_trunc(floor(_gml_tilemap_collision_max(yl, cell[1])) + 0.5)
	var b = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(yr, cell[3]))
	var mx = (xl + xr) / 2.0
	var my = (yl + yr) / 2.0
	var ww = (xr - xl) / 2.0
	var hh = (yr - yl) / 2.0
	for i in range(l, r + 1):
		var u = 0.0
		var v = 0.0
		if texels != null:
			u = _gml_tilemap_collision_u(texels, cell, i, t)
			v = _gml_tilemap_collision_v(texels, cell, i, t)
		for j in range(t, b + 1):
			var a = (i - mx) / ww
			var c = (j - my) / hh
			# A NaN (an ellipse without width or height) is never "outside".
			if not (a * a + c * c > 1.0):
				if texels == null or _gml_tilemap_collision_texel(tilemap, texels, u, v):
					return true
			if texels != null:
				v += texels["vy"]
				u += texels["uy"]
	return false


# yySprite.CollisionTilemapLine: the line, running left to right, sampled at
# every whole x (or, when steep, every whole y) from where it meets the
# cell. As in the runner, the start of that walk decides on the other axis.
static func _gml_tilemap_line(cell, xl, yl, xr, yr):
	if xr - xl == 0.0 and yr - yl == 0.0:
		return xl >= cell[0] and xl < cell[2] and yr >= cell[1] and yr < cell[3]
	if absf(xr - xl) >= absf(yr - yl):
		var sx = _gml_tilemap_collision_trunc(_gml_tilemap_collision_max(cell[0], xl))
		if sx < cell[0] or sx >= cell[2]:
			return false
		var sy = yl + ((sx - xl) / (xr - xl)) * (yr - yl)
		var ex = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(cell[2], xr))
		var dy = (yl - yr) / (xl - xr)
		for i in range(sx, ex + 1):
			if sy >= cell[1] and sy < cell[3]:
				return true
			sy += dy
		return false
	if yr < yl:
		var swap_y = yr
		yr = yl
		yl = swap_y
		var swap_x = xr
		xr = xl
		xl = swap_x
	var start_y = _gml_tilemap_collision_trunc(_gml_tilemap_collision_max(cell[1], yl))
	if start_y < cell[1] or start_y >= cell[3]:
		return false
	var line_x = xl + ((start_y - yl) / (yr - yl)) * (xr - xl)
	var end_y = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(cell[3], yr))
	var dx = (xr - xl) / (yr - yl)
	for i in range(start_y, end_y + 1):
		if line_x >= cell[0] and line_x < cell[2]:
			return true
		line_x += dx
	return false


# yySprite.PreciseCollisionTilemapLine: the same walk, testing the tile's
# mask at each step.
static func _gml_tilemap_precise_line(tilemap, cell, texels, xl, yl, xr, yr):
	if xr - xl == 0.0 and yr - yl == 0.0:
		return _gml_tilemap_collision_texel_at(tilemap, texels, cell, xr, yr)
	if absf(xr - xl) >= absf(yr - yl):
		var sx = _gml_tilemap_collision_trunc(_gml_tilemap_collision_max(cell[0], xl))
		var sy = yl + ((sx - xl) / (xr - xl)) * (yr - yl)
		var ex = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(cell[2], xr))
		var dy = (yl - yr) / (xl - xr)
		for i in range(sx, ex + 1):
			if _gml_tilemap_collision_texel_at(tilemap, texels, cell, i, sy):
				return true
			sy += dy
		return false
	if yr < yl:
		var swap_y = yr
		yr = yl
		yl = swap_y
		var swap_x = xr
		xr = xl
		xl = swap_x
	var start_y = _gml_tilemap_collision_trunc(_gml_tilemap_collision_max(cell[1], yl))
	var line_x = xl + ((start_y - yl) / (yr - yl)) * (xr - xl)
	var end_y = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(cell[3], yr))
	var dx = (xr - xl) / (yr - yl)
	for i in range(start_y, end_y + 1):
		if _gml_tilemap_collision_texel_at(tilemap, texels, cell, line_x, i):
			return true
		line_x += dx
	return false


# --- Instances -----------------------------------------------------------------

# Tilemap_InstancePlace: the instance (already at the place tested) against
# the cells under its bounding box.
static func _gml_tilemap_instance_hit(tilemap, state):
	var data = state["data"]
	if data == null:
		return false
	var tile_width = tilemap["tile_width"]
	var tile_height = tilemap["tile_height"]
	var map_right = tilemap["left"] + (tilemap["width"] * tile_width)
	var map_bottom = tilemap["top"] + (tilemap["height"] * tile_height)
	var l = (_gml_tilemap_collision_max(state["left"], tilemap["left"]) - tilemap["left"]) * (1.0 / tile_width)
	var r = (_gml_tilemap_collision_min(state["right"], map_right) - tilemap["left"]) * (1.0 / tile_width)
	var t = (_gml_tilemap_collision_max(state["top"], tilemap["top"]) - tilemap["top"]) * (1.0 / tile_height)
	var b = (_gml_tilemap_collision_min(state["bottom"], map_bottom) - tilemap["top"]) * (1.0 / tile_height)
	var right = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(r, float(tilemap["width"] - 1)))
	var bottom = _gml_tilemap_collision_trunc(_gml_tilemap_collision_min(b, float(tilemap["height"] - 1)))
	var left = _gml_tilemap_collision_trunc(_gml_tilemap_collision_max(l, 0.0))
	var top = _gml_tilemap_collision_trunc(_gml_tilemap_collision_max(t, 0.0))
	var precise = tilemap["precise"] or data["colcheck"] == GML_COLLISION_CHECK_PRECISE
	var probe = null
	for x in range(left, right + 1):
		for y in range(top, bottom + 1):
			var tile_data = _gml_tilemap_collision_data(tilemap, x, y) & GML_TILEMAP_COLLISION_DATA_MASK
			var index = _gml_tilemap_collision_index(tilemap, tile_data)
			if index <= 0:
				continue
			var cell = _gml_tilemap_collision_cell(tilemap, x, y)
			if not precise:
				if _gml_tilemap_box_overlap(state, cell):
					return true
				continue
			if probe == null:
				probe = _gml_tilemap_instance_probe(state)
			var texels = _gml_tilemap_collision_texels(tilemap, index, tile_data, cell)
			if _gml_tilemap_precise_instance(tilemap, probe, cell, texels):
				return true
	return false


# ValidBBoxOverlap: the overlap of the instance's box and the cell crosses a
# pixel centre.
static func _gml_tilemap_box_overlap(state, cell):
	var l = _gml_tilemap_collision_max(state["left"], cell[0])
	var t = _gml_tilemap_collision_max(state["top"], cell[1])
	var r = _gml_tilemap_collision_min(state["right"], cell[2])
	var b = _gml_tilemap_collision_min(state["bottom"], cell[3])
	if floor(l + 0.49999) == floor(r + 0.5):
		return false
	if floor(t + 0.49999) == floor(b + 0.5):
		return false
	return true


# How the instance samples its own mask in yySprite.PreciseCollisionTilemap:
# at its unrounded position, through its mask for the current image when
# the mask is precise.
static func _gml_tilemap_instance_probe(state):
	var data = state["data"]
	var angle = state["angle"]
	var radians = -angle * PI / 180.0
	var mask = null
	if data["colcheck"] == GML_COLLISION_CHECK_PRECISE:
		mask = _gml_collision_frame_mask(data, _gml_collision_state_image(state, false))
	return {
		"data": data,
		"mask": mask,
		"edges": _gml_collision_precise_edges(data),
		"box": [state["left"], state["top"], state["right"], state["bottom"]],
		"x": state["x"],
		"y": state["y"],
		"inv_x": 1.0 / state["xscale"],
		"inv_y": 1.0 / state["yscale"],
		"rotated": angle > _gml_math_epsilon or angle < -_gml_math_epsilon,
		"ss": sin(radians),
		"cc": cos(radians),
	}


# yySprite.PreciseCollisionTilemap: the pixel centres where the instance's
# box overlaps the cell, mapped into the instance's mask and into the tile.
static func _gml_tilemap_precise_instance(tilemap, probe, cell, texels):
	var box = probe["box"]
	var l = floor(_gml_tilemap_collision_max(box[0], cell[0])) + 0.5
	var r = _gml_tilemap_collision_min(box[2], cell[2])
	var t = floor(_gml_tilemap_collision_max(box[1], cell[1])) + 0.5
	var b = _gml_tilemap_collision_min(box[3], cell[3])
	if probe["rotated"]:
		return _gml_tilemap_precise_instance_rotated(tilemap, probe, cell, texels, [l, t, r, b])
	var data = probe["data"]
	var edges = probe["edges"]
	var tile_mask = tilemap["mask"]
	var u1 = (l - probe["x"]) * probe["inv_x"] + data["xorigin"]
	var i = l
	while i < r:
		if u1 >= edges[0] and u1 < edges[1]:
			var u2 = _gml_tilemap_collision_u(texels, cell, i, t)
			var v2 = _gml_tilemap_collision_v(texels, cell, i, t)
			var j = t
			while j < b:
				if (
					_gml_tilemap_instance_row_hit(probe, u1, j)
					and (tile_mask == null or _gml_tilemap_collision_texel(tilemap, texels, u2, v2))
				):
					return true
				j += 1.0
				v2 += texels["vy"]
				u2 += texels["uy"]
		i += 1.0
		u1 += probe["inv_x"]
	return false


# Without rotation the runner only looks at the rows of a precise mask.
static func _gml_tilemap_instance_row_hit(probe, u1, j):
	if probe["mask"] == null:
		return true
	var data = probe["data"]
	var v1 = (j - probe["y"]) * probe["inv_y"] + data["yorigin"]
	if v1 < probe["edges"][2] or v1 >= probe["edges"][3]:
		return false
	return _gml_collision_mask_set(data, probe["mask"], u1, v1, false)


static func _gml_tilemap_precise_instance_rotated(tilemap, probe, cell, texels, area):
	var data = probe["data"]
	var edges = probe["edges"]
	var tile_mask = tilemap["mask"]
	var cc = probe["cc"]
	var ss = probe["ss"]
	var i = area[0]
	while i < area[2]:
		var u2 = _gml_tilemap_collision_u(texels, cell, i, area[1])
		var v2 = _gml_tilemap_collision_v(texels, cell, i, area[1])
		var j = area[1]
		while j < area[3]:
			var u1 = (cc * (i - probe["x"]) + ss * (j - probe["y"])) * probe["inv_x"] + data["xorigin"]
			var v1 = (cc * (j - probe["y"]) - ss * (i - probe["x"])) * probe["inv_y"] + data["yorigin"]
			if (
				u1 >= edges[0] and u1 < edges[1] and v1 >= edges[2] and v1 < edges[3]
				and (probe["mask"] == null or _gml_collision_mask_set(data, probe["mask"], u1, v1, false))
				and (tile_mask == null or _gml_tilemap_collision_texel(tilemap, texels, u2, v2))
			):
				return true
			j += 1.0
			v2 += texels["vy"]
			u2 += texels["uy"]
		i += 1.0
	return false
