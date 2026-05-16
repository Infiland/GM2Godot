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

static func gml_ds_list_read(id_value, str_val):
	pass

static func gml_ds_list_write(id_value):
	return ""

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
	pass

static func gml_ds_stack_write(id_value):
	return ""


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
	pass

static func gml_ds_queue_write(id_value):
	return ""


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
	pass

static func gml_ds_priority_write(id_value):
	return ""
