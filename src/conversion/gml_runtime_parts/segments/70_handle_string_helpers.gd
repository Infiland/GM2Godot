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
	for handle in _gml_handle_registry.values():
		if handle.kind == GML_INSTANCE_HANDLE_KIND and gml_handle_is_valid(handle):
			targets.append(handle.reference)
	return targets


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


static func _object_has_property(object_value, property_name):
	for property in object_value.get_property_list():
		if property.get("name") == property_name:
			return true
	return false


