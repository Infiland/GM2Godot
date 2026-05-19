# --- Data Structures: Grids ---

static func gml_ds_grid_create(w, h):
	var grid = {"data": [], "width": 0, "height": 0}
	_gml_ds_grid_do_resize(grid, _to_int64_value(w), _to_int64_value(h))
	return gml_handle_register(GML_DS_GRID_HANDLE_KIND, grid)

static func gml_ds_grid_destroy(id_value):
	var handle = gml_handle_get(GML_DS_GRID_HANDLE_KIND, id_value)
	if handle != null:
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
				if val == null:
					data[i][j] = 0
				else:
					data[i][j] = val

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
			grid["data"][y].resize(w)
		else:
			var row = []
			row.resize(w)
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
				row[xi] = row[xi] + val
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
				row[xi] = row[xi] * val
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
				row[x] = row[x] + val

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
				row[x] = row[x] * val

static func gml_ds_grid_value_exists(id_value, x1, y1, x2, y2, val):
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
				if row[x] == val:
					return true
	return false

static func gml_ds_grid_value_x(id_value, x1, y1, x2, y2, val):
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
				if row[x] == val:
					return GMLInt64.new(x)
	return gml_undefined()

static func gml_ds_grid_value_y(id_value, x1, y1, x2, y2, val):
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
				if row[x] == val:
					return GMLInt64.new(y)
	return gml_undefined()

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
		var resolved = gml_handle_resolve_for_kind(GML_DS_GRID_HANDLE_KIND, id_value)
		if resolved != null:
			return resolved
	return id_value

static func _gml_ds_grid_create_unregistered(w, h):
	var grid = {"data": [], "width": w, "height": h}
	for y in range(h):
		var row = []
		row.resize(w)
		grid["data"].append(row)
	return grid
