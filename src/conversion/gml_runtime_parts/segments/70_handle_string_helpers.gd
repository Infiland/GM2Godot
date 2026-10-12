static func _gml_next_handle_index(kind):
	var next_index = int(_gml_handle_next_indices.get(kind, 0))
	_gml_handle_next_indices[kind] = next_index + 1
	return next_index


static func _gml_handle_key(kind, index):
	return str(kind) + ":" + str(int(index))


static func _gml_handle_to_string(handle):
	var label = handle.name if str(handle.name) != "" else str(handle.index)
	return "ref " + str(handle.kind) + " " + str(label)


static func _gml_handle_get_by_name(kind, name):
	var handle_kind = str(kind)
	var handle_name = str(name)
	for handle in _gml_handle_registry.values():
		if handle.kind == handle_kind and handle.name == handle_name:
			return handle
	return gml_handle_invalid(handle_kind)


static func _gml_make_handle(kind, index, reference, name, is_valid):
	var handle_kind = str(kind)
	var handle_index = int(index)
	var handle_type_id = _gml_handle_type_id(handle_kind)
	var encoded_value = _gml_encode_handle_value(handle_type_id, handle_index)
	return GMLHandle.new(handle_kind, handle_index, reference, str(name), bool(is_valid), handle_type_id, encoded_value)


static func _gml_invalid_handle_index(kind):
	return GML_INSTANCE_INVALID_INDEX if str(kind) == GML_INSTANCE_HANDLE_KIND else GML_HANDLE_INVALID_INDEX


static func _gml_instance_keyword_targets(handle, current_self = null, current_other = null):
	var keyword_targets = _gml_legacy_instance_keyword_targets(handle.index, current_self, current_other)
	if keyword_targets != null:
		return keyword_targets
	var resolved_instance = gml_handle_resolve(handle)
	if resolved_instance == null:
		return []
	return [resolved_instance]


static func _gml_legacy_instance_keyword_targets(keyword_index, current_self, current_other):
	if keyword_index == GML_INSTANCE_SELF_INDEX:
		return [] if current_self == null else [current_self]
	if keyword_index == GML_INSTANCE_OTHER_INDEX:
		return [] if current_other == null else [current_other]
	if keyword_index == GML_INSTANCE_ALL_INDEX:
		return _gml_all_instance_targets()
	if keyword_index == GML_INSTANCE_INVALID_INDEX:
		return []
	return null


static func _gml_all_instance_targets():
	var targets = []
	for entry in _gml_live_instance_entries():
		targets.append(entry["instance"])
	return targets


static func _gml_live_instance_entries():
	# The registered instances in creation order; nodes freed without being
	# unregistered are forgotten on the way.
	var entries = []
	var freed = []
	for entry in _gml_instance_live_order:
		var instance = entry["instance"]
		if typeof(instance) == TYPE_OBJECT and not is_instance_valid(instance):
			freed.append(entry)
		else:
			entries.append(entry)
	for entry in freed:
		gml_instance_unregister(entry)
	return entries


static func _gml_instance_entry_order_less(left, right):
	return int(left["creation_order"]) < int(right["creation_order"])


static func _gml_instance_entry(instance_or_handle):
	var value_type = typeof(instance_or_handle)
	if value_type == TYPE_INT:
		# A raw instance id (keywords are negative and never registered).
		var id_entry = _gml_instance_entries.get(instance_or_handle)
		if id_entry != null and gml_handle_is_valid(id_entry["handle"]):
			return id_entry
		return null
	if value_type == TYPE_OBJECT:
		if not is_instance_valid(instance_or_handle):
			return null
		if instance_or_handle is Node:
			var node_handle = _gml_instance_handles_by_node_id.get(instance_or_handle.get_instance_id())
			return null if node_handle == null else _gml_instance_entries.get(node_handle.index)
	if value_type == TYPE_DICTIONARY and instance_or_handle.has("handle"):
		return instance_or_handle
	if is_handle(instance_or_handle):
		if instance_or_handle.kind == GML_INSTANCE_HANDLE_KIND and _gml_instance_entries.has(instance_or_handle.index):
			return _gml_instance_entries[instance_or_handle.index]
		return null
	if is_numeric(instance_or_handle) or is_string(instance_or_handle):
		var handle = gml_handle_from_value(GML_INSTANCE_HANDLE_KIND, instance_or_handle)
		if gml_handle_is_valid(handle) and _gml_instance_entries.has(handle.index):
			return _gml_instance_entries[handle.index]
		return null
	if instance_or_handle is Object:
		var node_id = instance_or_handle.get_instance_id()
		if _gml_instance_handles_by_node_id.has(node_id):
			var handle = _gml_instance_handles_by_node_id[node_id]
			if _gml_instance_entries.has(handle.index):
				return _gml_instance_entries[handle.index]
	return null


static func _gml_instance_handle_for_node(instance):
	if typeof(instance) == TYPE_OBJECT and is_instance_valid(instance):
		var node_id = instance.get_instance_id()
		if _gml_instance_handles_by_node_id.has(node_id):
			return _gml_instance_handles_by_node_id[node_id]
	return gml_instance_noone()


static func _gml_instance_selector_targets(selector):
	if is_handle(selector) and selector.kind == GML_INSTANCE_HANDLE_KIND:
		var keyword_targets = _gml_instance_keyword_targets(selector)
		if keyword_targets != null:
			return keyword_targets
	if is_numeric(selector):
		var keyword_index = _to_int64_value(selector)
		var keyword_targets = _gml_legacy_instance_keyword_targets(keyword_index, null, null)
		if keyword_targets != null:
			return keyword_targets
	# A registered instance exists until it is unregistered, which happens
	# right after its Destroy event: like GameMaker, the event still sees it.
	var entry: Variant = _gml_instance_entry(selector)
	if entry != null:
		return [entry["instance"]]
	var object_entries: Variant = _gml_instance_object_entries(selector)
	if object_entries != null:
		return _gml_instance_entry_targets(object_entries)
	if _gml_object_asset_entry(selector) != null:
		# An object without instances.
		return []
	return null


static func _gml_instance_index_add(index_map, selector, entry):
	if selector == null:
		return
	if is_numeric(selector) and _to_int64_value(selector) == -1:
		return
	if is_string(selector) and str(selector) == "":
		return
	if not index_map.has(selector):
		index_map[selector] = []
	index_map[selector].append(entry)


static func _gml_instance_index_remove(index_map, selector, entry):
	if selector == null or not index_map.has(selector):
		return
	_gml_instance_order_erase(index_map[selector], entry)
	if index_map[selector].is_empty():
		index_map.erase(selector)


static func _gml_object_selector_id(selector):
	var entry: Variant = _gml_object_asset_entry(selector)
	if entry != null:
		return int(entry["id"])
	if is_numeric(selector):
		return _to_int64_value(selector)
	return -1


static func _gml_object_selector_name(selector):
	var entry: Variant = _gml_object_asset_entry(selector)
	if entry != null:
		return str(entry["name"])
	if is_string(selector):
		return str(selector)
	return ""


static func _gml_object_selector_id_array(selectors):
	var ids = []
	for selector in selectors:
		var selector_id = _gml_object_selector_id(selector)
		if selector_id != -1 and not ids.has(selector_id):
			ids.append(selector_id)
	return ids


static func _gml_object_selector_name_array(selectors):
	var names = []
	for selector in selectors:
		var selector_name = _gml_object_selector_name(selector)
		if selector_name != "" and not names.has(selector_name):
			names.append(selector_name)
	return names


static func _gml_object_asset_entry(selector):
	_gml_asset_registry_ensure_loaded()
	var entry: Variant = _gml_asset_resolve(selector)
	if entry == null:
		return null
	if str(entry["type"]) != "object":
		return null
	return entry


static func _gml_instance_distance_extreme(x, y, target, nearest):
	# GameMaker's instance_nearest/instance_furthest: the distance from (x, y)
	# to an instance's x and y has to beat 10000000000 (nearest) or
	# -10000000000 (furthest) and every distance before it, so the first
	# instance wins a tie.
	var px = _to_real(x)
	var py = _to_real(y)
	var best_distance = 10000000000.0 if nearest else -10000000000.0
	var best_entry = null
	var entries: Variant = _gml_instance_target_entries(target)
	if entries == null:
		entries = []
		for instance in gml_with_targets(target):
			var instance_entry: Variant = _gml_instance_entry(instance)
			if instance_entry != null:
				entries.append(instance_entry)
	for entry in entries:
		var instance = entry["instance"]
		if typeof(instance) == TYPE_OBJECT and not is_instance_valid(instance):
			continue
		var position = (
			instance.position
			if instance is Node2D and not _gml_sequence_instances_exist
			else _gml_instance_position(instance)
		)
		var xx = px - position.x
		var yy = py - position.y
		var distance = sqrt(xx * xx + yy * yy)
		if (distance < best_distance) if nearest else (distance > best_distance):
			best_distance = distance
			best_entry = entry
	if best_entry == null:
		return gml_instance_noone()
	return best_entry["handle"]


static func _gml_instance_position(instance):
	if instance is Node2D:
		return _gml_collision_instance_xy(instance)
	if instance is Object:
		var x_value = gml_variable_instance_get(instance, "x")
		var y_value = gml_variable_instance_get(instance, "y")
		if is_numeric(x_value) and is_numeric(y_value):
			return Vector2(_to_real(x_value), _to_real(y_value))
	return Vector2.ZERO


static func _gml_instance_create_at(x, y, layer, depth_value, object_selector, current_self = null):
	var entry: Variant = _gml_object_asset_entry(object_selector)
	if entry == null:
		return gml_instance_noone()
	if not entry.has("godot_path"):
		return gml_instance_noone()
	var godot_path = str(entry["godot_path"])
	if godot_path == "":
		return gml_instance_noone()
	var scene = load(godot_path)
	if scene == null or not scene.has_method("instantiate"):
		return gml_instance_noone()
	var instance = scene.instantiate()
	if instance is Node2D:
		instance.position = Vector2(_to_real(x), _to_real(y))
	if depth_value != null:
		_gml_instance_apply_depth(instance, depth_value)
	var parent = _gml_instance_creation_parent(current_self, layer)
	if parent == null:
		return gml_instance_noone()
	if layer == null and depth_value != null and parent == _gml_layer_current_scene():
		# GameMaker puts it on the room's managed layer at its depth.
		parent = _gml_managed_layer(parent, gml_depth_truncate(depth_value))
	parent.add_child(instance)
	var handle = _gml_instance_handle_for_node(instance)
	if not gml_handle_is_valid(handle):
		handle = gml_instance_register(instance, int(entry["id"]), [])
	return handle


static func _gml_instance_creation_parent(current_self, layer):
	if layer != null:
		var resolved_layer = _gml_layer_resolve_node(layer)
		if resolved_layer != null:
			return resolved_layer
	if current_self is Node:
		var tree = current_self.get_tree()
		if tree != null and tree.current_scene != null:
			return tree.current_scene
		var current_parent = current_self.get_parent()
		if current_parent != null:
			return current_parent
		return current_self
	return null


static func _gml_instance_apply_depth(instance, depth_value):
	var resolved_depth = _to_real(depth_value)
	if instance is Object:
		instance.set("depth", resolved_depth)
	gml_instance_depth_assign(instance, resolved_depth)


static func _gml_instance_set_meta(instance, key, value):
	if instance is Object and instance.has_method("set_meta"):
		instance.set_meta(str(key), value)


static func _gml_is_invalid_handle_index(kind, index):
	return int(index) == _gml_invalid_handle_index(kind)


static func _gml_handle_eq(left, right):
	if is_handle(left) and is_handle(right):
		return left.kind == right.kind and left.index == right.index
	if is_handle(left) and is_numeric(right):
		return left.index == _to_int64_value(right)
	if is_handle(right) and is_numeric(left):
		return _to_int64_value(left) == right.index
	return false


static func _gml_handle_type_id(kind):
	var handle_kind = str(kind)
	if not _gml_handle_type_ids.has(handle_kind):
		_gml_handle_type_ids[handle_kind] = _gml_handle_next_type_id
		_gml_handle_next_type_id += 1
	return int(_gml_handle_type_ids[handle_kind])


static func _gml_encode_handle_value(type_id, index):
	return (int(type_id) << GML_HANDLE_TYPE_SHIFT) | (int(index) & GML_HANDLE_INDEX_MASK)


static func _gml_string_is_int(value):
	var text = str(value)
	if text == "":
		return false
	var start = 1 if text.begins_with("-") else 0
	if start >= text.length():
		return false
	for index in range(start, text.length()):
		var code = text.unicode_at(index)
		if code < 48 or code > 57:
			return false
	return true


static func _gml_string_to_real(value):
	var text = str(value).strip_edges()
	if text.to_lower().is_valid_hex_number(true):
		return float(_gml_hex_string_to_int(text))
	if text.is_valid_float():
		return text.to_float()
	return gml_error("GML real conversion does not support string " + text)


static func _gml_string_to_int64(value):
	var text = str(value).strip_edges()
	if text.to_lower().is_valid_hex_number(true):
		return _gml_hex_string_to_int(text)
	if text.is_valid_float():
		return int(text.to_float())
	return gml_error("GML int64 conversion does not support string " + text)


static func _gml_hex_string_to_int(value):
	var text = str(value).strip_edges()
	var sign = 1
	if text.begins_with("-"):
		sign = -1
		text = text.substr(1)
	elif text.begins_with("+"):
		text = text.substr(1)
	if text.to_lower().begins_with("0x"):
		text = text.substr(2)
	var result = 0
	for index in range(text.length()):
		result = result * 16 + _gml_hex_digit_value(text.unicode_at(index))
	return sign * result


static func _gml_hex_digit_value(code):
	if code >= 48 and code <= 57:
		return code - 48
	if code >= 65 and code <= 70:
		return code - 55
	if code >= 97 and code <= 102:
		return code - 87
	return 0


static func _to_array_index(value):
	var resolved_index = int(_to_real(value))
	if resolved_index < 0:
		gml_error("Negative GML array index")
		return -1
	return resolved_index


static var _gml_script_property_names_cache = {}


static func _object_has_property(object_value, property_name):
	# get_property_list() allocates every property description, so scripted
	# objects (all converted instances) cache their names per class + script.
	# Scriptless objects keep the full scan: some built-in classes expose
	# per-instance properties (e.g. shader parameters).
	var script = object_value.get_script()
	if script == null:
		for property in object_value.get_property_list():
			if property.get("name") == property_name:
				return true
		return false
	var class_names = _gml_script_property_names_cache.get(script)
	if class_names == null:
		class_names = {}
		_gml_script_property_names_cache[script] = class_names
	var class_name_value = object_value.get_class()
	var names = class_names.get(class_name_value)
	if names == null:
		names = {}
		for property in object_value.get_property_list():
			names[str(property.get("name"))] = true
		class_names[class_name_value] = names
	return names.has(str(property_name))


static func _gml_one_based_index(value):
	var resolved = int(_to_real(value))
	return resolved - 1


static func gml_string_length(value):
	var s = gml_string(value)
	return s.length()


static func gml_string_byte_length(value):
	return gml_string(value).to_utf8_buffer().size()


static func gml_string_char_at(value, index):
	var s = gml_string(value)
	var pos = _gml_one_based_index(index)
	if pos < 0 or pos >= s.length():
		return ""
	return s[pos]


static func gml_string_ord_at(value, index):
	var s = gml_string(value)
	var pos = _gml_one_based_index(index)
	if pos < 0 or pos >= s.length():
		return 0
	return s.unicode_at(pos)


static func gml_string_copy(value, index, count):
	var s = gml_string(value)
	var pos = _gml_one_based_index(index)
	var length = int(_to_real(count))
	if pos < 0:
		pos = 0
	if pos >= s.length() or length <= 0:
		return ""
	return s.substr(pos, length)


static func gml_string_pos(subvalue, value):
	var s = gml_string(value)
	var sub = gml_string(subvalue)
	var found = s.find(sub)
	if found == -1:
		return 0
	return found + 1


static func gml_string_replace(value, old_char, new_str):
	var s = gml_string(value)
	var old = gml_string(old_char)
	var new_s = gml_string(new_str)
	return s.replace(old, new_s)


static func gml_string_replace_all(value, old_char, new_str):
	var s = gml_string(value)
	var old = gml_string(old_char)
	var new_s = gml_string(new_str)
	return s.replace(old, new_s)


static func gml_string_hash_to_newline(value):
	return gml_string(value).replace("#", "\n")


static func gml_string_delete(value, index, count):
	var s = gml_string(value)
	var pos = _gml_one_based_index(index)
	var length = int(_to_real(count))
	if pos < 0:
		pos = 0
	if pos >= s.length() or length <= 0:
		return s
	return s.left(pos) + s.substr(pos + length)


static func gml_string_insert(subvalue, value, index):
	var s = gml_string(value)
	var sub = gml_string(subvalue)
	var pos = _gml_one_based_index(index)
	if pos < 0:
		pos = 0
	if pos >= s.length():
		return s + sub
	return s.left(pos) + sub + s.substr(pos)


static func gml_string_lower(value):
	var s = gml_string(value)
	return s.to_lower()


static func gml_string_upper(value):
	var s = gml_string(value)
	return s.to_upper()


static func gml_string_trim(value):
	var s = gml_string(value)
	return s.strip_edges()


static func gml_string_repeat(value, count):
	var s = gml_string(value)
	var n = int(_to_real(count))
	if n <= 0:
		return ""
	var result = ""
	for i in range(n):
		result += s
	return result


static func gml_string_digits(value):
	var s = gml_string(value)
	var result = ""
	for i in range(s.length()):
		var c = s[i]
		if c >= "0" and c <= "9":
			result += c
	return result


static func gml_string_letters(value):
	var s = gml_string(value)
	var result = ""
	for i in range(s.length()):
		var c = s[i]
		if (c >= "a" and c <= "z") or (c >= "A" and c <= "Z"):
			result += c
	return result


static func gml_string_lettersdigits(value):
	var s = gml_string(value)
	var result = ""
	for i in range(s.length()):
		var c = s[i]
		if (c >= "a" and c <= "z") or (c >= "A" and c <= "Z") or (c >= "0" and c <= "9"):
			result += c
	return result


static func gml_string_split(value, delimiter):
	var s = gml_string(value)
	var delim = gml_string(delimiter)
	var result = []
	var start = 0
	while true:
		var found = s.find(delim, start)
		if found == -1:
			result.append(s.substr(start))
			break
		result.append(s.substr(start, found - start))
		start = found + delim.length()
	return result


static func gml_string_join(array_value, delimiter):
	if typeof(array_value) != TYPE_ARRAY:
		return gml_unsupported_type_error("GML string_join array", array_value)
	var delim = gml_string(delimiter)
	var parts = []
	for i in range(array_value.size()):
		parts.append(gml_string(array_value[i]))
	return delim.join(parts)


# string_join(delimiter, value1, ...): each value as string() gives it,
# joined by the delimiter (Function_String.js string_join).
static func gml_string_join_values(delimiter, values):
	var parts = []
	for value in values:
		parts.append(gml_string(value))
	return gml_string(delimiter).join(parts)


static func gml_chr(code):
	var n = int(_to_real(code))
	if n < 0 or n > 0x10FFFF:
		return ""
	return char(n)


static func gml_ord(value):
	var s = gml_string(value)
	if s.is_empty():
		return 0
	return s.unicode_at(0)


static func gml_ansi_char(code):
	var n = int(_to_real(code))
	if n < 0 or n > 255:
		return ""
	return char(n)
