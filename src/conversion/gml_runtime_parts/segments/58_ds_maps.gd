# --- Data Structures: Maps ---

static func gml_ds_map_create():
	var ds = {}
	return gml_handle_register(GML_DS_MAP_HANDLE_KIND, ds)

static func gml_ds_map_destroy(id_value):
	var handle = gml_handle_get(GML_DS_MAP_HANDLE_KIND, id_value)
	if handle != null:
		gml_handle_invalidate(handle)

static func gml_ds_map_clear(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		ds.clear()

static func gml_ds_map_empty(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		return ds.is_empty()
	return true

static func gml_ds_map_size(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		return ds.size()
	return 0

static func gml_ds_map_add(id_value, key, value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			return false
		ds[key] = value
		return true
	return false

static func gml_ds_map_set(id_value, key, value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		ds[key] = value
		return value
	return gml_undefined()

static func gml_ds_map_replace(id_value, key, value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			ds[key] = value
			return value
	return gml_undefined()

static func gml_ds_map_delete(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			ds.erase(key)

static func gml_ds_map_exists(id_value, key):
	var resolved_map = _gml_resolve_ds_map(id_value)
	if resolved_map is Dictionary:
		return resolved_map.has(key)
	return false

static func gml_ds_map_find_value(id_value, key):
	var resolved_map = _gml_resolve_ds_map(id_value)
	if resolved_map is Dictionary:
		if resolved_map.has(key):
			return resolved_map[key]
		return gml_undefined()
	return gml_undefined()

static func gml_ds_map_find_first(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if not ds.is_empty():
			var keys = ds.keys()
			return keys[0]
	return gml_undefined()

static func gml_ds_map_find_last(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if not ds.is_empty():
			var keys = ds.keys()
			return keys[keys.size() - 1]
	return gml_undefined()

static func gml_ds_map_find_next(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			var keys = ds.keys()
			var idx = keys.find(key)
			if idx >= 0 and idx < keys.size() - 1:
				return keys[idx + 1]
	return gml_undefined()

static func gml_ds_map_find_previous(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			var keys = ds.keys()
			var idx = keys.find(key)
			if idx > 0:
				return keys[idx - 1]
	return gml_undefined()

static func gml_ds_map_keys(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		return ds.keys()
	return []

static func gml_ds_map_values(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		return ds.values()
	return []

static func gml_ds_map_copy(id_dest, id_src):
	var dest = _gml_resolve_ds_map(id_dest)
	var src = _gml_resolve_ds_map(id_src)
	if dest is Dictionary and src is Dictionary:
		var new_map = {}
		for key in src:
			new_map[key] = src[key]
		dest.clear()
		for key in new_map:
			dest[key] = new_map[key]

static func gml_ds_map_merge(id_value, source_id):
	var dest = _gml_resolve_ds_map(id_value)
	var src = _gml_resolve_ds_map(source_id)
	if dest is Dictionary and src is Dictionary:
		dest.merge(src, true)

static func gml_ds_map_read(id_value, str_val, legacy = false):
	_gml_ds_read(GML_DS_MAP_HANDLE_KIND, id_value, str_val, legacy)

static func gml_ds_map_write(id_value):
	return _gml_ds_write(GML_DS_MAP_HANDLE_KIND, id_value)

static func gml_ds_map_add_list(id_value, key, list_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		ds[key] = list_id

static func gml_ds_map_add_map(id_value, key, map_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		ds[key] = map_id

static func gml_ds_map_replace_list(id_value, key, list_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			ds[key] = list_id

static func gml_ds_map_replace_map(id_value, key, map_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			ds[key] = map_id

static func gml_ds_map_is_list(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			var val = ds[key]
			if is_handle(val):
				var handle = gml_handle_get(GML_DS_LIST_HANDLE_KIND, val)
				return handle != null
	return false

static func gml_ds_map_is_map(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if ds.has(key):
			var val = ds[key]
			if is_handle(val):
				var handle = gml_handle_get(GML_DS_MAP_HANDLE_KIND, val)
				return handle != null
	return false
