# --- Data Structures: Lists, Stacks, Queues, Priority Queues ---

static func _gml_resolve_ds_list(id_value):
	if is_handle(id_value) or is_numeric(id_value) or is_string(id_value):
		var resolved = gml_handle_resolve_for_kind(GML_DS_LIST_HANDLE_KIND, id_value)
		if resolved != null:
			return resolved
	return id_value

static func _gml_resolve_ds_stack(id_value):
	if is_handle(id_value) or is_numeric(id_value) or is_string(id_value):
		var resolved = gml_handle_resolve_for_kind(GML_DS_STACK_HANDLE_KIND, id_value)
		if resolved != null:
			return resolved
	return id_value

static func _gml_resolve_ds_queue(id_value):
	if is_handle(id_value) or is_numeric(id_value) or is_string(id_value):
		var resolved = gml_handle_resolve_for_kind(GML_DS_QUEUE_HANDLE_KIND, id_value)
		if resolved != null:
			return resolved
	return id_value

static func _gml_resolve_ds_priority(id_value):
	if is_handle(id_value) or is_numeric(id_value) or is_string(id_value):
		var resolved = gml_handle_resolve_for_kind(GML_DS_PRIORITY_HANDLE_KIND, id_value)
		if resolved != null:
			return resolved
	return id_value


static func _gml_is_equal(a, b):
	if typeof(a) == typeof(b):
		return a == b
	if is_numeric(a) and is_numeric(b):
		return float(a) == float(b)
	return false


static func _gml_is_ds_handle_kind(kind):
	return str(kind) in [
		GML_DS_LIST_HANDLE_KIND,
		GML_DS_STACK_HANDLE_KIND,
		GML_DS_QUEUE_HANDLE_KIND,
		GML_DS_PRIORITY_HANDLE_KIND,
		GML_DS_MAP_HANDLE_KIND,
		GML_DS_GRID_HANDLE_KIND
	]


static func _gml_empty_ds_reference_for_kind(kind):
	if kind == GML_DS_LIST_HANDLE_KIND:
		return {"data": [], "marks": {}}
	if kind == GML_DS_STACK_HANDLE_KIND or kind == GML_DS_QUEUE_HANDLE_KIND:
		return {"data": []}
	if kind == GML_DS_PRIORITY_HANDLE_KIND:
		return {"data": []}
	if kind == GML_DS_MAP_HANDLE_KIND:
		return {}
	if kind == GML_DS_GRID_HANDLE_KIND:
		return {"data": [], "width": 0, "height": 0}
	return null


static func _gml_resolve_ds_for_kind(kind, id_value):
	if kind == GML_DS_LIST_HANDLE_KIND:
		return _gml_resolve_ds_list(id_value)
	if kind == GML_DS_STACK_HANDLE_KIND:
		return _gml_resolve_ds_stack(id_value)
	if kind == GML_DS_QUEUE_HANDLE_KIND:
		return _gml_resolve_ds_queue(id_value)
	if kind == GML_DS_PRIORITY_HANDLE_KIND:
		return _gml_resolve_ds_priority(id_value)
	if kind == GML_DS_MAP_HANDLE_KIND:
		return _gml_resolve_ds_map(id_value)
	if kind == GML_DS_GRID_HANDLE_KIND:
		return _gml_resolve_ds_grid(id_value)
	return null


static func _gml_ds_write(kind, id_value):
	var ds = _gml_resolve_ds_for_kind(kind, id_value)
	if not (ds is Dictionary):
		return ""
	var envelope = {
		"gm2godot_ds_format": 1,
		"kind": str(kind),
		"payload": _gml_ds_serialize_reference(kind, ds, {})
	}
	return JSON.stringify(envelope)


static func _gml_ds_read(kind, id_value, str_val, _legacy = false):
	var ds = _gml_resolve_ds_for_kind(kind, id_value)
	if not (ds is Dictionary):
		return
	var parsed = JSON.parse_string(str(str_val))
	if not (parsed is Dictionary):
		return
	if int(parsed.get("gm2godot_ds_format", 0)) != 1:
		return
	if str(parsed.get("kind", "")) != str(kind):
		return
	var payload = parsed.get("payload", {})
	if payload is Dictionary:
		_gml_ds_apply_payload(kind, ds, payload)


static func _gml_ds_serialize_reference(kind, ds, seen):
	if kind == GML_DS_LIST_HANDLE_KIND:
		var data = []
		for item in ds["data"]:
			data.append(_gml_ds_serialize_value(item, seen))
		var marks = []
		for index in ds["marks"].keys():
			marks.append({"index": int(index), "kind": str(ds["marks"][index])})
		return {"data": data, "marks": marks}
	if kind == GML_DS_STACK_HANDLE_KIND or kind == GML_DS_QUEUE_HANDLE_KIND:
		var data = []
		for item in ds["data"]:
			data.append(_gml_ds_serialize_value(item, seen))
		return {"data": data}
	if kind == GML_DS_PRIORITY_HANDLE_KIND:
		var entries = []
		for item in ds["data"]:
			entries.append({
				"value": _gml_ds_serialize_value(item.get("val", gml_undefined()), seen),
				"priority": _to_real(item.get("prio", 0))
			})
		return {"data": entries}
	if kind == GML_DS_MAP_HANDLE_KIND:
		var entries = []
		for key in ds.keys():
			entries.append({
				"key": _gml_ds_serialize_value(key, seen),
				"value": _gml_ds_serialize_value(ds[key], seen)
			})
		return {"entries": entries}
	if kind == GML_DS_GRID_HANDLE_KIND:
		var rows = []
		for row in ds["data"]:
			var serialized_row = []
			for value in row:
				serialized_row.append(_gml_ds_serialize_value(value, seen))
			rows.append(serialized_row)
		return {"width": int(ds["width"]), "height": int(ds["height"]), "data": rows}
	return {}


static func _gml_ds_serialize_value(value, seen):
	if is_undefined(value):
		return {"type": "undefined"}
	if is_int64(value):
		return {"type": "int64", "value": int(value.value)}
	if is_ptr(value):
		return {"type": "ptr", "value": int(value.value), "invalid": bool(value.invalid)}
	if typeof(value) == TYPE_INT:
		return {"type": "int", "value": int(value)}
	if typeof(value) == TYPE_FLOAT:
		return {"type": "real", "value": float(value)}
	if is_handle(value):
		if _gml_is_ds_handle_kind(value.kind) and gml_handle_is_valid(value):
			var handle_key = _gml_handle_key(value.kind, value.index)
			if not seen.has(handle_key):
				seen[handle_key] = true
				var nested = gml_handle_resolve(value)
				if nested is Dictionary:
					return {
						"type": "ds",
						"kind": str(value.kind),
						"name": str(value.name),
						"payload": _gml_ds_serialize_reference(value.kind, nested, seen)
					}
		return {
			"type": "handle",
			"kind": str(value.kind),
			"index": int(value.index),
			"name": str(value.name),
			"valid": bool(value.valid)
		}
	if value is Array:
		var items = []
		for item in value:
			items.append(_gml_ds_serialize_value(item, seen))
		return {"type": "array", "items": items}
	if value is Dictionary:
		var entries = []
		for key in value.keys():
			entries.append({
				"key": _gml_ds_serialize_value(key, seen),
				"value": _gml_ds_serialize_value(value[key], seen)
			})
		return {"type": "struct", "entries": entries}
	if value == null or is_bool(value) or is_number(value) or is_string(value):
		return {"type": "value", "value": value}
	return {"type": "string", "value": str(value)}


static func _gml_ds_deserialize_value(payload):
	if not (payload is Dictionary):
		return payload
	var payload_type = str(payload.get("type", "value"))
	if payload_type == "undefined":
		return gml_undefined()
	if payload_type == "int64":
		return GMLInt64.new(payload.get("value", 0))
	if payload_type == "ptr":
		return GMLPointer.new(payload.get("value", 0), payload.get("invalid", false))
	if payload_type == "int":
		return int(payload.get("value", 0))
	if payload_type == "real":
		return float(payload.get("value", 0))
	if payload_type == "handle":
		var handle_kind = str(payload.get("kind", ""))
		if bool(payload.get("valid", false)):
			return gml_handle_get(handle_kind, payload.get("index", GML_HANDLE_INVALID_INDEX))
		return gml_handle_invalid(handle_kind, payload.get("index", GML_HANDLE_INVALID_INDEX))
	if payload_type == "ds":
		var nested_kind = str(payload.get("kind", ""))
		var nested_reference = _gml_empty_ds_reference_for_kind(nested_kind)
		if nested_reference is Dictionary and payload.get("payload", {}) is Dictionary:
			_gml_ds_apply_payload(nested_kind, nested_reference, payload["payload"])
			return gml_handle_register(nested_kind, nested_reference, str(payload.get("name", "")))
		return gml_handle_invalid(nested_kind)
	if payload_type == "array":
		var result = []
		for item in payload.get("items", []):
			result.append(_gml_ds_deserialize_value(item))
		return result
	if payload_type == "struct":
		var result = {}
		for entry in payload.get("entries", []):
			if entry is Dictionary:
				result[_gml_ds_deserialize_value(entry.get("key", null))] = _gml_ds_deserialize_value(entry.get("value", null))
		return result
	return payload.get("value", null)


static func _gml_ds_apply_payload(kind, ds, payload):
	if kind == GML_DS_LIST_HANDLE_KIND:
		ds["data"].clear()
		ds["marks"].clear()
		for item in payload.get("data", []):
			ds["data"].append(_gml_ds_deserialize_value(item))
		for mark in payload.get("marks", []):
			if mark is Dictionary:
				ds["marks"][int(mark.get("index", 0))] = str(mark.get("kind", ""))
	elif kind == GML_DS_STACK_HANDLE_KIND or kind == GML_DS_QUEUE_HANDLE_KIND:
		ds["data"].clear()
		for item in payload.get("data", []):
			ds["data"].append(_gml_ds_deserialize_value(item))
	elif kind == GML_DS_PRIORITY_HANDLE_KIND:
		ds["data"].clear()
		for item in payload.get("data", []):
			if item is Dictionary:
				ds["data"].append({
					"val": _gml_ds_deserialize_value(item.get("value", null)),
					"prio": _to_real(item.get("priority", 0))
				})
	elif kind == GML_DS_MAP_HANDLE_KIND:
		ds.clear()
		for entry in payload.get("entries", []):
			if entry is Dictionary:
				ds[_gml_ds_deserialize_value(entry.get("key", null))] = _gml_ds_deserialize_value(entry.get("value", null))
	elif kind == GML_DS_GRID_HANDLE_KIND:
		ds["width"] = int(payload.get("width", 0))
		ds["height"] = int(payload.get("height", 0))
		ds["data"].clear()
		for row in payload.get("data", []):
			var decoded_row = []
			for value in row:
				decoded_row.append(_gml_ds_deserialize_value(value))
			ds["data"].append(decoded_row)

# --- DS List ---

static func gml_ds_list_create():
	var ds = {"data": [], "marks": {}}
	return gml_handle_register(GML_DS_LIST_HANDLE_KIND, ds)

static func gml_ds_list_destroy(id_value):
	var handle = gml_handle_get(GML_DS_LIST_HANDLE_KIND, id_value)
	if handle != null:
		gml_handle_invalidate(handle)

static func gml_ds_list_clear(id_value):
	var ds = _gml_resolve_ds_list(id_value)
	if ds is Dictionary:
		ds["data"].clear()
		ds["marks"].clear()

static func gml_ds_list_empty(id_value):
	var ds = _gml_resolve_ds_list(id_value)
	if ds is Dictionary:
		return ds["data"].is_empty()
	return true

static func gml_ds_list_size(id_value):
	var ds = _gml_resolve_ds_list(id_value)
	if ds is Dictionary:
		return ds["data"].size()
	return 0

static func gml_ds_list_add(id_value, args):
	var ds = _gml_resolve_ds_list(id_value)
	if ds is Dictionary:
		for arg in args:
			ds["data"].append(arg)

static func gml_ds_list_set(id_value, pos, value):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		if idx >= 0:
			var arr = ds["data"]
			if idx >= arr.size():
				arr.resize(idx + 1)
			arr[idx] = value
	return value

static func gml_ds_list_delete(id_value, pos):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		if idx >= 0 and idx < ds["data"].size():
			ds["data"].remove_at(idx)
			var new_marks = {}
			for k in ds["marks"].keys():
				if k < idx:
					new_marks[k] = ds["marks"][k]
				elif k > idx:
					new_marks[k - 1] = ds["marks"][k]
			ds["marks"] = new_marks

static func gml_ds_list_find_index(id_value, val):
	var ds = _gml_resolve_ds_list(id_value)
	if ds is Dictionary:
		var arr = ds["data"]
		for i in range(arr.size()):
			if _gml_is_equal(arr[i], val):
				return GMLInt64.new(i)
	return GMLInt64.new(-1)

static func gml_ds_list_find_value(id_value, pos):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		if idx >= 0 and idx < ds["data"].size():
			return ds["data"][idx]
	return gml_undefined()

static func gml_ds_list_insert(id_value, pos, val):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		if idx >= 0:
			var arr = ds["data"]
			if idx >= arr.size():
				arr.resize(idx)
				arr.append(val)
			else:
				arr.insert(idx, val)
			var new_marks = {}
			for k in ds["marks"].keys():
				if k < idx:
					new_marks[k] = ds["marks"][k]
				else:
					new_marks[k + 1] = ds["marks"][k]
			ds["marks"] = new_marks

static func gml_ds_list_replace(id_value, pos, val):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		if idx >= 0 and idx < ds["data"].size():
			ds["data"][idx] = val

static func gml_ds_list_shuffle(id_value):
	var ds = _gml_resolve_ds_list(id_value)
	if ds is Dictionary:
		var arr = ds["data"]
		ds["marks"].clear()
		for i in range(arr.size() - 1, 0, -1):
			var j = randi() % (i + 1)
			var tmp = arr[i]
			arr[i] = arr[j]
			arr[j] = tmp

static func gml_ds_list_sort(id_value, ascend):
	var ds = _gml_resolve_ds_list(id_value)
	if ds is Dictionary:
		ds["marks"].clear()
		var arr = ds["data"]
		if bool(ascend):
			arr.sort_custom(func(a, b): return _gml_less_than(a, b))
		else:
			arr.sort_custom(func(a, b): return _gml_greater_than(a, b))

static func _gml_less_than(a, b):
	if typeof(a) == typeof(b) and (typeof(a) == TYPE_INT or typeof(a) == TYPE_FLOAT):
		return a < b
	elif is_numeric(a) and is_numeric(b):
		return _to_real(a) < _to_real(b)
	elif is_string(a) and is_string(b):
		return str(a) < str(b)
	return false

static func _gml_greater_than(a, b):
	if typeof(a) == typeof(b) and (typeof(a) == TYPE_INT or typeof(a) == TYPE_FLOAT):
		return a > b
	elif is_numeric(a) and is_numeric(b):
		return _to_real(a) > _to_real(b)
	elif is_string(a) and is_string(b):
		return str(a) > str(b)
	return false

static func gml_ds_list_copy(id_dest, id_src):
	var dest = _gml_resolve_ds_list(id_dest)
	var src = _gml_resolve_ds_list(id_src)
	if dest is Dictionary and src is Dictionary:
		var new_data = []; for item in src["data"]: new_data.append(item); dest["data"] = new_data
		var new_marks = {}; for k in src["marks"]: new_marks[k] = src["marks"][k]; dest["marks"] = new_marks

static func gml_ds_list_read(id_value, str_val, legacy = false):
	_gml_ds_read(GML_DS_LIST_HANDLE_KIND, id_value, str_val, legacy)

static func gml_ds_list_write(id_value):
	return _gml_ds_write(GML_DS_LIST_HANDLE_KIND, id_value)

static func gml_ds_list_mark_as_list(id_value, pos):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		if idx >= 0 and idx < ds["data"].size():
			ds["marks"][idx] = "list"

static func gml_ds_list_mark_as_map(id_value, pos):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		if idx >= 0 and idx < ds["data"].size():
			ds["marks"][idx] = "map"

static func gml_ds_list_is_list(id_value, pos):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		return ds["marks"].get(idx) == "list"
	return false

static func gml_ds_list_is_map(id_value, pos):
	var ds = _gml_resolve_ds_list(id_value)
	var idx = _to_int64_value(pos)
	if ds is Dictionary:
		return ds["marks"].get(idx) == "map"
	return false


# --- DS Stack ---

static func gml_ds_stack_create():
	var ds = {"data": []}
	return gml_handle_register(GML_DS_STACK_HANDLE_KIND, ds)

static func gml_ds_stack_destroy(id_value):
	var handle = gml_handle_get(GML_DS_STACK_HANDLE_KIND, id_value)
	if handle != null:
		gml_handle_invalidate(handle)

static func gml_ds_stack_clear(id_value):
	var ds = _gml_resolve_ds_stack(id_value)
	if ds is Dictionary:
		ds["data"].clear()

static func gml_ds_stack_empty(id_value):
	var ds = _gml_resolve_ds_stack(id_value)
	if ds is Dictionary:
		return ds["data"].is_empty()
	return true

static func gml_ds_stack_size(id_value):
	var ds = _gml_resolve_ds_stack(id_value)
	if ds is Dictionary:
		return ds["data"].size()
	return 0

static func gml_ds_stack_push(id_value, args):
	var ds = _gml_resolve_ds_stack(id_value)
	if ds is Dictionary:
		for arg in args:
			ds["data"].append(arg)

static func gml_ds_stack_pop(id_value):
	var ds = _gml_resolve_ds_stack(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			return ds["data"].pop_back()
	return gml_undefined()

static func gml_ds_stack_top(id_value):
	var ds = _gml_resolve_ds_stack(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			return ds["data"].back()
	return gml_undefined()

static func gml_ds_stack_copy(id_dest, id_src):
	var dest = _gml_resolve_ds_stack(id_dest)
	var src = _gml_resolve_ds_stack(id_src)
	if dest is Dictionary and src is Dictionary:
		var new_data = []; for item in src["data"]: new_data.append(item); dest["data"] = new_data

static func gml_ds_stack_read(id_value, str_val):
	_gml_ds_read(GML_DS_STACK_HANDLE_KIND, id_value, str_val)

static func gml_ds_stack_write(id_value):
	return _gml_ds_write(GML_DS_STACK_HANDLE_KIND, id_value)


# --- DS Queue ---

static func gml_ds_queue_create():
	var ds = {"data": []}
	return gml_handle_register(GML_DS_QUEUE_HANDLE_KIND, ds)

static func gml_ds_queue_destroy(id_value):
	var handle = gml_handle_get(GML_DS_QUEUE_HANDLE_KIND, id_value)
	if handle != null:
		gml_handle_invalidate(handle)

static func gml_ds_queue_clear(id_value):
	var ds = _gml_resolve_ds_queue(id_value)
	if ds is Dictionary:
		ds["data"].clear()

static func gml_ds_queue_empty(id_value):
	var ds = _gml_resolve_ds_queue(id_value)
	if ds is Dictionary:
		return ds["data"].is_empty()
	return true

static func gml_ds_queue_size(id_value):
	var ds = _gml_resolve_ds_queue(id_value)
	if ds is Dictionary:
		return ds["data"].size()
	return 0

static func gml_ds_queue_enqueue(id_value, args):
	var ds = _gml_resolve_ds_queue(id_value)
	if ds is Dictionary:
		for arg in args:
			ds["data"].append(arg)

static func gml_ds_queue_dequeue(id_value):
	var ds = _gml_resolve_ds_queue(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			return ds["data"].pop_front()
	return gml_undefined()

static func gml_ds_queue_head(id_value):
	var ds = _gml_resolve_ds_queue(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			return ds["data"].front()
	return gml_undefined()

static func gml_ds_queue_tail(id_value):
	var ds = _gml_resolve_ds_queue(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			return ds["data"].back()
	return gml_undefined()

static func gml_ds_queue_copy(id_dest, id_src):
	var dest = _gml_resolve_ds_queue(id_dest)
	var src = _gml_resolve_ds_queue(id_src)
	if dest is Dictionary and src is Dictionary:
		var new_data = []; for item in src["data"]: new_data.append(item); dest["data"] = new_data

static func gml_ds_queue_read(id_value, str_val):
	_gml_ds_read(GML_DS_QUEUE_HANDLE_KIND, id_value, str_val)

static func gml_ds_queue_write(id_value):
	return _gml_ds_write(GML_DS_QUEUE_HANDLE_KIND, id_value)


# --- DS Priority ---

static func gml_ds_priority_create():
	var ds = {"data": []}
	return gml_handle_register(GML_DS_PRIORITY_HANDLE_KIND, ds)

static func gml_ds_priority_destroy(id_value):
	var handle = gml_handle_get(GML_DS_PRIORITY_HANDLE_KIND, id_value)
	if handle != null:
		gml_handle_invalidate(handle)

static func gml_ds_priority_clear(id_value):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		ds["data"].clear()

static func gml_ds_priority_empty(id_value):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		return ds["data"].is_empty()
	return true

static func gml_ds_priority_size(id_value):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		return ds["data"].size()
	return 0

static func gml_ds_priority_add(id_value, val, prio):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		ds["data"].append({"val": val, "prio": _to_real(prio)})

static func gml_ds_priority_change_priority(id_value, val, prio):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		for item in ds["data"]:
			if _gml_is_equal(item["val"], val):
				item["prio"] = _to_real(prio)
				return

static func gml_ds_priority_delete_max(id_value):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			var arr = ds["data"]
			var max_idx = 0
			var max_prio = arr[0]["prio"]
			for i in range(1, arr.size()):
				if arr[i]["prio"] > max_prio:
					max_prio = arr[i]["prio"]
					max_idx = i
			var val = arr[max_idx]["val"]
			arr.remove_at(max_idx)
			return val
	return gml_undefined()

static func gml_ds_priority_delete_min(id_value):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			var arr = ds["data"]
			var min_idx = 0
			var min_prio = arr[0]["prio"]
			for i in range(1, arr.size()):
				if arr[i]["prio"] < min_prio:
					min_prio = arr[i]["prio"]
					min_idx = i
			var val = arr[min_idx]["val"]
			arr.remove_at(min_idx)
			return val
	return gml_undefined()

static func gml_ds_priority_delete_value(id_value, val):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		var arr = ds["data"]
		for i in range(arr.size() - 1, -1, -1):
			if _gml_is_equal(arr[i]["val"], val):
				arr.remove_at(i)

static func gml_ds_priority_find_max(id_value):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			var arr = ds["data"]
			var max_val = arr[0]["val"]
			var max_prio = arr[0]["prio"]
			for i in range(1, arr.size()):
				if arr[i]["prio"] > max_prio:
					max_prio = arr[i]["prio"]
					max_val = arr[i]["val"]
			return max_val
	return gml_undefined()

static func gml_ds_priority_find_min(id_value):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		if not ds["data"].is_empty():
			var arr = ds["data"]
			var min_val = arr[0]["val"]
			var min_prio = arr[0]["prio"]
			for i in range(1, arr.size()):
				if arr[i]["prio"] < min_prio:
					min_prio = arr[i]["prio"]
					min_val = arr[i]["val"]
			return min_val
	return gml_undefined()

static func gml_ds_priority_find_priority(id_value, val):
	var ds = _gml_resolve_ds_priority(id_value)
	if ds is Dictionary:
		for item in ds["data"]:
			if _gml_is_equal(item["val"], val):
				return item["prio"]
	return gml_undefined()

static func gml_ds_priority_copy(id_dest, id_src):
	var dest = _gml_resolve_ds_priority(id_dest)
	var src = _gml_resolve_ds_priority(id_src)
	if dest is Dictionary and src is Dictionary:
		var new_data = []; for item in src["data"]: new_data.append(item); dest["data"] = new_data

static func gml_ds_priority_read(id_value, str_val):
	_gml_ds_read(GML_DS_PRIORITY_HANDLE_KIND, id_value, str_val)

static func gml_ds_priority_write(id_value):
	return _gml_ds_write(GML_DS_PRIORITY_HANDLE_KIND, id_value)
