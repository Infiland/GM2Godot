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
		# Cells hold 0, not null, unless a value is given (typeof, not
		# == null: a destroyed instance compares equal to null).
		var clear_value = 0 if typeof(val) == TYPE_NIL else val
		for row in grid["data"]:
			row.fill(clear_value)

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
				var cell = row[xi]
				if (cell is int or cell is float) and (val is int or val is float):
					cell += val
				else:
					cell = _gml_ds_grid_added(cell, val)
				row[xi] = cell
				return cell
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
				var cell = row[xi]
				if (cell is int or cell is float) and (val is int or val is float):
					cell *= val
				else:
					cell = _gml_ds_grid_multiplied(cell, val)
				row[xi] = cell
				return cell
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
		# The kind of val is worked out once; a number is added to the numbers
		# in place and everything else goes through _gml_ds_grid_added.
		if val is int or val is float:
			for y in range(yi1, yi2 + 1):
				var row = data[y]
				for x in range(xi1, xi2 + 1):
					var cell = row[x]
					if cell is int:
						row[x] = cell + val
					elif cell is float:
						row[x] = cell + val
					else:
						row[x] = _gml_ds_grid_added(cell, val)
		elif val is String:
			for y in range(yi1, yi2 + 1):
				var row = data[y]
				for x in range(xi1, xi2 + 1):
					var cell = row[x]
					if cell is String:
						row[x] = cell + val
					else:
						row[x] = _gml_ds_grid_added(cell, val)
		else:
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
		if val is int or val is float:
			for y in range(yi1, yi2 + 1):
				var row = data[y]
				for x in range(xi1, xi2 + 1):
					var cell = row[x]
					if cell is int:
						row[x] = cell * val
					elif cell is float:
						row[x] = cell * val
					else:
						row[x] = _gml_ds_grid_multiplied(cell, val)
		else:
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
		# What val is, worked out once for every row: the number it is
		# compared as, and the one int a cell can hold to be within the
		# precision of it (NAN when there is none, and no int equals NAN).
		var number = 0.0
		var int_cell = NAN
		if val is int or val is float:
			number = float(val)
			if absf(number - roundf(number)) < GML_DS_GRID_VALUE_PRECISION and absf(number) < GML_DS_GRID_EXACT_INT_LIMIT:
				int_cell = int(roundf(number))
		for y in range(yi1, yi2 + 1):
			var x = _gml_ds_grid_row_find(data[y], xi1, xi2, val, number, int_cell)
			if x >= 0:
				return Vector2i(x, y)
	return Vector2i(-1, -1)

# The first index from first to last in row that holds val, or -1. The
# common case, no cell holds val, is settled by a scan that tests each
# cell's type inline and that never answers no wrongly; only a row it
# cannot rule out is scanned again, cell by cell, for the index.
static func _gml_ds_grid_row_find(row, first, last, val, number, int_cell):
	if not _gml_ds_grid_row_may_hold(row, first, last, val, number, int_cell):
		return -1
	for x in range(first, last + 1):
		if _gml_ds_grid_cell_holds(row[x], val, number):
			return x
	return -1

static func _gml_ds_grid_cell_holds(cell, val, number):
	if (cell is int or cell is float) and (val is int or val is float):
		return absf(cell - number) < GML_DS_GRID_VALUE_PRECISION
	return _gml_is_equal(cell, val)

static func _gml_ds_grid_row_may_hold(row, first, last, val, number, int_cell):
	var cells = row if (first == 0 and last == row.size() - 1) else row.slice(first, last + 1)
	if val is int or val is float:
		return _gml_ds_grid_cells_may_hold_number(cells, val, number, int_cell)
	if val is String:
		return _gml_ds_grid_cells_may_hold_string(cells, val)
	if val is bool:
		return _gml_ds_grid_cells_may_hold_bool(cells, val)
	if typeof(val) == TYPE_OBJECT and not is_int64(val):
		return _gml_ds_grid_cells_may_hold_object(cells, val)
	return _gml_ds_grid_cells_may_hold_value(cells, val)

static func _gml_ds_grid_cells_may_hold_number(cells, val, number, int_cell):
	# Past 2^53 several ints share one real, so no int is ruled out.
	if absf(number) >= GML_DS_GRID_EXACT_INT_LIMIT:
		return true
	# A real is within the precision of number inside this wider window.
	var low = number - GML_DS_GRID_VALUE_PRECISION * 2.0
	var high = number + GML_DS_GRID_VALUE_PRECISION * 2.0
	for cell in cells:
		if cell is int:
			if cell == int_cell:
				return true
		elif cell is float:
			if cell >= low and cell <= high:
				return true
		elif _gml_is_equal(cell, val):
			return true
	return false

# A number is never equal to a string.
static func _gml_ds_grid_cells_may_hold_string(cells, val):
	for cell in cells:
		if cell is String:
			if cell == val:
				return true
		elif not (cell is int or cell is float) and _gml_is_equal(cell, val):
			return true
	return false

# A boolean equals a number that is 1 or 0 as it is.
static func _gml_ds_grid_cells_may_hold_bool(cells, val):
	var as_number = 1 if val else 0
	for cell in cells:
		if cell is bool:
			if cell == val:
				return true
		elif cell is int or cell is float:
			if cell == as_number:
				return true
		elif _gml_is_equal(cell, val):
			return true
	return false

# An object (an instance, a handle) equals only itself; is_same, unlike ==,
# takes a value of another type without failing.
static func _gml_ds_grid_cells_may_hold_object(cells, val):
	for cell in cells:
		if cell is int:
			continue
		if is_same(cell, val):
			return true
	return false

# Any other value: a number only equals a 64-bit integer.
static func _gml_ds_grid_cells_may_hold_value(cells, val):
	var skip_numbers = not is_numeric(val)
	for cell in cells:
		if skip_numbers and (cell is int or cell is float):
			continue
		if _gml_is_equal(cell, val):
			return true
	return false

const GML_DS_GRID_VALUE_PRECISION = 0.0000001
# Every int up to 2^53 is its own real.
const GML_DS_GRID_EXACT_INT_LIMIT = 9007199254740992.0

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
