# --- Data Structures: Maps ---

class GMLDSMapReferenceKey extends RefCounted:
	var value

	func _init(reference_value):
		value = reference_value


static func _gml_ds_map_find_internal_key(ds, key):
	for stored_key in ds.keys():
		if stored_key is GMLDSMapReferenceKey:
			if _is_gml_reference_value(key) and is_same(stored_key.value, key):
				return stored_key
		elif gml_eq(stored_key, key):
			return stored_key
	return gml_undefined()


static func _gml_ds_map_internal_key_for_set(ds, key):
	var stored_key = _gml_ds_map_find_internal_key(ds, key)
	if not is_undefined(stored_key):
		return stored_key
	if _is_gml_reference_value(key):
		return GMLDSMapReferenceKey.new(key)
	return key


static func _gml_ds_map_external_key(stored_key):
	return stored_key.value if stored_key is GMLDSMapReferenceKey else stored_key


static func _gml_ds_map_set_value(ds, key, value):
	ds[_gml_ds_map_internal_key_for_set(ds, key)] = value
	return value


static func gml_ds_map_create():
	var ds = {}
	return gml_handle_register(GML_DS_MAP_HANDLE_KIND, ds)

static func gml_ds_map_destroy(id_value):
	var handle = gml_handle_from_value(GML_DS_MAP_HANDLE_KIND, id_value)
	if gml_handle_is_valid(handle):
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
		if not is_undefined(_gml_ds_map_find_internal_key(ds, key)):
			return false
		_gml_ds_map_set_value(ds, key, value)
		return true
	return false

static func gml_ds_map_set(id_value, key, value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		return _gml_ds_map_set_value(ds, key, value)
	return gml_undefined()

static func gml_ds_map_replace(id_value, key, value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			ds[stored_key] = value
			return value
	return gml_undefined()

static func gml_ds_map_delete(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			ds.erase(stored_key)

static func gml_ds_map_exists(id_value, key):
	var resolved_map = _gml_resolve_ds_map(id_value)
	if resolved_map is Dictionary:
		return not is_undefined(_gml_ds_map_find_internal_key(resolved_map, key))
	return false

static func gml_ds_map_find_value(id_value, key):
	var resolved_map = _gml_resolve_ds_map(id_value)
	if resolved_map is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(resolved_map, key)
		if not is_undefined(stored_key):
			return resolved_map[stored_key]
		return gml_undefined()
	return gml_undefined()

static func gml_ds_map_find_first(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if not ds.is_empty():
			var keys = ds.keys()
			return _gml_ds_map_external_key(keys[0])
	return gml_undefined()

static func gml_ds_map_find_last(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		if not ds.is_empty():
			var keys = ds.keys()
			return _gml_ds_map_external_key(keys[keys.size() - 1])
	return gml_undefined()

static func gml_ds_map_find_next(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			var keys = ds.keys()
			var idx = keys.find(stored_key)
			if idx >= 0 and idx < keys.size() - 1:
				return _gml_ds_map_external_key(keys[idx + 1])
	return gml_undefined()

static func gml_ds_map_find_previous(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			var keys = ds.keys()
			var idx = keys.find(stored_key)
			if idx > 0:
				return _gml_ds_map_external_key(keys[idx - 1])
	return gml_undefined()

static func gml_ds_map_keys(id_value):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var keys = []
		for stored_key in ds.keys():
			keys.append(_gml_ds_map_external_key(stored_key))
		return keys
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
		var entries = []
		for stored_key in src.keys():
			entries.append({
				"key": _gml_ds_map_external_key(stored_key),
				"value": src[stored_key]
			})
		dest.clear()
		for entry in entries:
			_gml_ds_map_set_value(
				dest,
				entry["key"],
				entry["value"]
			)

static func gml_ds_map_merge(id_value, source_id):
	var dest = _gml_resolve_ds_map(id_value)
	var src = _gml_resolve_ds_map(source_id)
	if dest is Dictionary and src is Dictionary:
		for stored_key in src.keys():
			_gml_ds_map_set_value(
				dest,
				_gml_ds_map_external_key(stored_key),
				src[stored_key]
			)

static func gml_ds_map_read(id_value, str_val, legacy = false):
	_gml_ds_read(GML_DS_MAP_HANDLE_KIND, id_value, str_val, legacy)

static func gml_ds_map_write(id_value):
	return _gml_ds_write(GML_DS_MAP_HANDLE_KIND, id_value)

static func gml_ds_map_add_list(id_value, key, list_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		_gml_ds_map_set_value(ds, key, gml_handle_from_value(GML_DS_LIST_HANDLE_KIND, list_id))

static func gml_ds_map_add_map(id_value, key, map_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		_gml_ds_map_set_value(ds, key, gml_handle_from_value(GML_DS_MAP_HANDLE_KIND, map_id))

static func gml_ds_map_replace_list(id_value, key, list_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			ds[stored_key] = gml_handle_from_value(GML_DS_LIST_HANDLE_KIND, list_id)

static func gml_ds_map_replace_map(id_value, key, map_id):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			ds[stored_key] = gml_handle_from_value(GML_DS_MAP_HANDLE_KIND, map_id)

static func gml_ds_map_is_list(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			var val = ds[stored_key]
			if is_handle(val):
				var handle = gml_handle_get(GML_DS_LIST_HANDLE_KIND, val)
				return handle != null
	return false

static func gml_ds_map_is_map(id_value, key):
	var ds = _gml_resolve_ds_map(id_value)
	if ds is Dictionary:
		var stored_key = _gml_ds_map_find_internal_key(ds, key)
		if not is_undefined(stored_key):
			var val = ds[stored_key]
			if is_handle(val):
				var handle = gml_handle_get(GML_DS_MAP_HANDLE_KIND, val)
				return handle != null
	return false
