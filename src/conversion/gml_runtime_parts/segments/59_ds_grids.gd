# --- Data Structures: Grids ---

static func gml_ds_grid_create(w, h):
	var grid = {"data": [], "width": 0, "height": 0}
	_gml_ds_grid_do_resize(grid, _to_int64_value(w), _to_int64_value(h))
	return gml_handle_register(GML_DS_GRID_HANDLE_KIND, grid)

static func gml_ds_grid_destroy(id_value):
	var handle = gml_handle_from_value(GML_DS_GRID_HANDLE_KIND, id_value)
	if gml_handle_is_valid(handle):
		gml_handle_invalidate(handle)

static func gml_ds_grid_width(id_value):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		return grid["width"]
	return 0

static func gml_ds_grid_height(id_value):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		return grid["height"]
	return 0

static func gml_ds_grid_clear(id_value, val = null):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var data = grid["data"]
		for i in range(data.size()):
			for j in range(data[i].size()):
				# Cells hold 0, not null, unless a value is given (typeof, not
				# == null: a destroyed instance compares equal to null).
				data[i][j] = 0 if typeof(val) == TYPE_NIL else val

static func gml_ds_grid_resize(id_value, w, h, val = 0):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		_gml_ds_grid_do_resize(grid, _to_int64_value(w), _to_int64_value(h))

static func _gml_ds_grid_do_resize(grid, w, h):
	var old_w = grid["width"]
	var old_h = grid["height"]
	grid["width"] = w
	grid["height"] = h
	grid["data"].resize(h)
	for y in range(h):
		if y < old_h:
			# Cells the grid gains hold 0 (the runner's yyGrid fills a new
			# grid with 0 and ds_grid_resize copies the old cells into it).
			if w > old_w:
				_gml_array_grow(grid["data"][y], w)
			else:
				grid["data"][y].resize(w)
		else:
			var row = []
			row.resize(w)
			row.fill(0)
			grid["data"][y] = row

static func gml_ds_grid_set(id_value, x, y, val):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi = _to_int64_value(x)
		var yi = _to_int64_value(y)
		var data = grid["data"]
		if yi >= 0 and yi < data.size():
			var row = data[yi]
			if xi >= 0 and xi < row.size():
				row[xi] = val
				return val
	return gml_undefined()

static func gml_ds_grid_get(id_value, x, y):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi = _to_int64_value(x)
		var yi = _to_int64_value(y)
		var data = grid["data"]
		if yi >= 0 and yi < data.size():
			var row = data[yi]
			if xi >= 0 and xi < row.size():
				return row[xi]
	return gml_undefined()

static func gml_ds_grid_add(id_value, x, y, val):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi = _to_int64_value(x)
		var yi = _to_int64_value(y)
		var data = grid["data"]
		if yi >= 0 and yi < data.size():
			var row = data[yi]
			if xi >= 0 and xi < row.size():
				row[xi] = _gml_ds_grid_added(row[xi], val)
				return row[xi]
	return gml_undefined()

static func gml_ds_grid_multiply(id_value, x, y, val):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi = _to_int64_value(x)
		var yi = _to_int64_value(y)
		var data = grid["data"]
		if yi >= 0 and yi < data.size():
			var row = data[yi]
			if xi >= 0 and xi < row.size():
				row[xi] = _gml_ds_grid_multiplied(row[xi], val)
				return row[xi]
	return gml_undefined()

static func gml_ds_grid_set_region(id_value, x1, y1, x2, y2, val):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi1 = max(0, _to_int64_value(x1))
		var yi1 = max(0, _to_int64_value(y1))
		var xi2 = min(grid["width"] - 1, _to_int64_value(x2))
		var yi2 = min(grid["height"] - 1, _to_int64_value(y2))
		var data = grid["data"]
		for y in range(yi1, yi2 + 1):
			var row = data[y]
			for x in range(xi1, xi2 + 1):
				row[x] = val

static func gml_ds_grid_get_region(id_value, x1, y1, x2, y2):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi1 = max(0, _to_int64_value(x1))
		var yi1 = max(0, _to_int64_value(y1))
		var xi2 = min(grid["width"] - 1, _to_int64_value(x2))
		var yi2 = min(grid["height"] - 1, _to_int64_value(y2))
		var result = _gml_ds_grid_create_unregistered(xi2 - xi1 + 1, yi2 - yi1 + 1)
		var rdata = result["data"]
		var data = grid["data"]
		for y in range(yi1, yi2 + 1):
			var src_row = data[y]
			var dst_row = rdata[y - yi1]
			for x in range(xi1, xi2 + 1):
				dst_row[x - xi1] = src_row[x]
		return gml_handle_register(GML_DS_GRID_HANDLE_KIND, result)
	return gml_undefined()

static func gml_ds_grid_clear_region(id_value, x1, y1, x2, y2, val = 0):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi1 = max(0, _to_int64_value(x1))
		var yi1 = max(0, _to_int64_value(y1))
		var xi2 = min(grid["width"] - 1, _to_int64_value(x2))
		var yi2 = min(grid["height"] - 1, _to_int64_value(y2))
		var data = grid["data"]
		for y in range(yi1, yi2 + 1):
			var row = data[y]
			for x in range(xi1, xi2 + 1):
				row[x] = val

static func gml_ds_grid_add_region(id_value, x1, y1, x2, y2, val):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi1 = max(0, _to_int64_value(x1))
		var yi1 = max(0, _to_int64_value(y1))
		var xi2 = min(grid["width"] - 1, _to_int64_value(x2))
		var yi2 = min(grid["height"] - 1, _to_int64_value(y2))
		var data = grid["data"]
		for y in range(yi1, yi2 + 1):
			var row = data[y]
			for x in range(xi1, xi2 + 1):
				row[x] = _gml_ds_grid_added(row[x], val)

static func gml_ds_grid_multiply_region(id_value, x1, y1, x2, y2, val):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary:
		var xi1 = max(0, _to_int64_value(x1))
		var yi1 = max(0, _to_int64_value(y1))
		var xi2 = min(grid["width"] - 1, _to_int64_value(x2))
		var yi2 = min(grid["height"] - 1, _to_int64_value(y2))
		var data = grid["data"]
		for y in range(yi1, yi2 + 1):
			var row = data[y]
			for x in range(xi1, xi2 + 1):
				row[x] = _gml_ds_grid_multiplied(row[x], val)

static func gml_ds_grid_value_exists(id_value, x1, y1, x2, y2, val):
	return _gml_ds_grid_value_find(id_value, x1, y1, x2, y2, val).x >= 0

static func gml_ds_grid_value_x(id_value, x1, y1, x2, y2, val):
	return GMLInt64.new(_gml_ds_grid_value_find(id_value, x1, y1, x2, y2, val).x)

static func gml_ds_grid_value_y(id_value, x1, y1, x2, y2, val):
	return GMLInt64.new(_gml_ds_grid_value_find(id_value, x1, y1, x2, y2, val).y)

# The first cell of the region (row by row, as in the runner's
# ds_grid_value_common) that holds val, or (-1, -1): the corners may come in
# either order and the region is cut to the grid. Two numbers match within
# the runner's precision (1e-7), anything else by GML equality, which
# also compares values of different types without failing.
static func _gml_ds_grid_value_find(id_value, x1, y1, x2, y2, val):
	var grid = _gml_resolve_ds_grid(id_value)
	if grid is Dictionary and grid["width"] > 0 and grid["height"] > 0:
		var xa = _to_int64_value(x1)
		var xb = _to_int64_value(x2)
		var ya = _to_int64_value(y1)
		var yb = _to_int64_value(y2)
		var xi1 = clampi(mini(xa, xb), 0, grid["width"] - 1)
		var xi2 = clampi(maxi(xa, xb), 0, grid["width"] - 1)
		var yi1 = clampi(mini(ya, yb), 0, grid["height"] - 1)
		var yi2 = clampi(maxi(ya, yb), 0, grid["height"] - 1)
		var data = grid["data"]
		var val_is_number = is_number(val)
		for y in range(yi1, yi2 + 1):
			var row = data[y]
			for x in range(xi1, xi2 + 1):
				var cell = row[x]
				if val_is_number and is_number(cell):
					if absf(float(cell) - float(val)) < GML_DS_GRID_VALUE_PRECISION:
						return Vector2i(x, y)
				elif _gml_is_equal(cell, val):
					return Vector2i(x, y)
	return Vector2i(-1, -1)

const GML_DS_GRID_VALUE_PRECISION = 0.0000001

# What a cell holds after ds_grid_add and the add_region variants add val to
# it, as in the runner: two numbers add, two strings join, two other values
# that are numeric (64-bit integers) add as reals and anything else is
# replaced by val.
static func _gml_ds_grid_added(cell, val):
	if is_number(cell) and is_number(val):
		return cell + val
	if is_string(cell) and is_string(val):
		return str(cell) + str(val)
	if typeof(cell) == TYPE_OBJECT and typeof(val) == TYPE_OBJECT and is_numeric(cell) and is_numeric(val):
		return _to_real(cell) + _to_real(val)
	return val

# ds_grid_multiply and the multiply_region variants leave a cell alone when
# it or the factor is a string and multiply anything else as reals.
static func _gml_ds_grid_multiplied(cell, val):
	if is_number(cell) and is_number(val):
		return cell * val
	if is_string(cell) or is_string(val):
		return cell
	return _to_real(cell) * _to_real(val)

static func gml_ds_grid_copy(id_dest, id_src):
	var dest = _gml_resolve_ds_grid(id_dest)
	var src = _gml_resolve_ds_grid(id_src)
	if dest is Dictionary and src is Dictionary:
		var sw = src["width"]
		var sh = src["height"]
		_gml_ds_grid_do_resize(dest, sw, sh)
		var sdata = src["data"]
		var ddata = dest["data"]
		for y in range(sh):
			var srow = sdata[y]
			var drow = ddata[y]
			for x in range(sw):
				drow[x] = srow[x]

static func gml_ds_grid_read(id_value, str_val, legacy = false):
	_gml_ds_read(GML_DS_GRID_HANDLE_KIND, id_value, str_val, legacy)

static func gml_ds_grid_write(id_value):
	return _gml_ds_write(GML_DS_GRID_HANDLE_KIND, id_value)

static func _gml_resolve_ds_grid(id_value):
	if is_handle(id_value) or is_numeric(id_value) or is_string(id_value):
		return gml_handle_resolve_for_kind(GML_DS_GRID_HANDLE_KIND, id_value)
	return id_value

static func _gml_ds_grid_create_unregistered(w, h):
	var grid = {"data": [], "width": w, "height": h}
	for y in range(h):
		var row = []
		row.resize(w)
		row.fill(0)
		grid["data"].append(row)
	return grid
