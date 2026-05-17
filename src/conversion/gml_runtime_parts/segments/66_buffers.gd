const GML_BUFFER_HANDLE_KIND = "buffer"
const GML_BUFFER_FIXED = 0
const GML_BUFFER_GROW = 1
const GML_BUFFER_WRAP = 2
const GML_BUFFER_FAST = 3
const GML_BUFFER_SEEK_START = 0
const GML_BUFFER_SEEK_RELATIVE = 1
const GML_BUFFER_SEEK_END = 2
const GML_BUFFER_U8 = 1
const GML_BUFFER_S8 = 2
const GML_BUFFER_U16 = 3
const GML_BUFFER_S16 = 4
const GML_BUFFER_U32 = 5
const GML_BUFFER_S32 = 6
const GML_BUFFER_F32 = 7
const GML_BUFFER_F64 = 8
const GML_BUFFER_BOOL = 9
const GML_BUFFER_STRING = 10
const GML_BUFFER_TEXT = 11

static var _gml_buffer_async_next_id = 1


class GMLBuffer:
	var data = PackedByteArray()
	var cursor = 0
	var alignment = 1
	var buffer_type = GML_BUFFER_GROW
	var used_size = 0
	var valid = true

	func _init(size = 0, type_value = GML_BUFFER_GROW, alignment_value = 1):
		var initial_size = max(0, int(size))
		data.resize(initial_size)
		cursor = 0
		alignment = max(1, int(alignment_value))
		buffer_type = int(type_value)
		used_size = 0
		valid = true


static func gml_buffer_create(size, type_value, alignment):
	var buffer = GMLBuffer.new(_to_int64_value(size), _to_int64_value(type_value), _to_int64_value(alignment))
	return gml_handle_register(GML_BUFFER_HANDLE_KIND, buffer)


static func gml_buffer_delete(buffer_id):
	var handle = gml_handle_from_value(GML_BUFFER_HANDLE_KIND, buffer_id)
	if gml_handle_is_valid(handle):
		if handle.reference is GMLBuffer:
			handle.reference.valid = false
		gml_handle_invalidate(handle)
	return null


static func gml_buffer_exists(buffer_id):
	var buffer = _gml_buffer_resolve(buffer_id)
	return buffer != null and buffer.valid


static func gml_buffer_tell(buffer_id):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return 0
	return buffer.cursor


static func gml_buffer_seek(buffer_id, base, offset):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return 0
	var base_value = _to_int64_value(base)
	var offset_value = _to_int64_value(offset)
	if base_value == GML_BUFFER_SEEK_RELATIVE:
		buffer.cursor = max(0, buffer.cursor + offset_value)
	elif base_value == GML_BUFFER_SEEK_END:
		buffer.cursor = max(0, buffer.used_size + offset_value)
	else:
		buffer.cursor = max(0, offset_value)
	return buffer.cursor


static func gml_buffer_get_size(buffer_id):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return 0
	return buffer.data.size()


static func gml_buffer_get_used_size(buffer_id):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return 0
	return buffer.used_size


static func gml_buffer_resize(buffer_id, size):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return 0
	var resolved_size = max(0, _to_int64_value(size))
	buffer.data.resize(resolved_size)
	buffer.used_size = min(buffer.used_size, resolved_size)
	buffer.cursor = min(buffer.cursor, resolved_size)
	return resolved_size


static func gml_buffer_write(buffer_id, value_type, value):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return gml_undefined()
	var bytes_written = _gml_buffer_write_value(buffer, buffer.cursor, _to_int64_value(value_type), value)
	if bytes_written < 0:
		return gml_undefined()
	buffer.cursor = _gml_buffer_align_position(buffer.cursor + bytes_written, buffer.alignment)
	return null


static func gml_buffer_read(buffer_id, value_type):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return gml_undefined()
	var start = buffer.cursor
	var result = _gml_buffer_read_value(buffer, start, _to_int64_value(value_type))
	buffer.cursor = _gml_buffer_align_position(start + _gml_buffer_value_size(buffer, start, _to_int64_value(value_type)), buffer.alignment)
	return result


static func gml_buffer_peek(buffer_id, offset, value_type):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return gml_undefined()
	return _gml_buffer_read_value(buffer, max(0, _to_int64_value(offset)), _to_int64_value(value_type))


static func gml_buffer_poke(buffer_id, offset, value_type, value):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return gml_undefined()
	_gml_buffer_write_value(buffer, max(0, _to_int64_value(offset)), _to_int64_value(value_type), value)
	return null


static func gml_buffer_fill(buffer_id, offset, value_type, value, count):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return gml_undefined()
	var position = max(0, _to_int64_value(offset))
	var value_kind = _to_int64_value(value_type)
	for _index in range(max(0, _to_int64_value(count))):
		var written = _gml_buffer_write_value(buffer, position, value_kind, value)
		if written < 0:
			return gml_undefined()
		position += written
	return null


static func gml_buffer_copy(src_buffer_id, src_offset, size, dest_buffer_id, dest_offset):
	var src = _gml_buffer_resolve(src_buffer_id)
	var dest = _gml_buffer_resolve(dest_buffer_id)
	if src == null or dest == null:
		return gml_undefined()
	var bytes = _gml_buffer_read_bytes(src, max(0, _to_int64_value(src_offset)), max(0, _to_int64_value(size)))
	_gml_buffer_write_bytes(dest, max(0, _to_int64_value(dest_offset)), bytes)
	return null


static func gml_buffer_save(buffer_id, path):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return false
	var resolved = _gml_file_resolve_path(path, true)
	_gml_file_ensure_parent_directory(resolved)
	var file = FileAccess.open(resolved, FileAccess.WRITE)
	if file == null:
		return false
	file.store_buffer(_gml_buffer_used_bytes(buffer))
	file.close()
	return true


static func gml_buffer_load(path):
	var resolved = _gml_file_resolve_path(path, false)
	if not FileAccess.file_exists(resolved):
		return gml_error("GML buffer_load missing file: " + gml_string(path))
	var file = FileAccess.open(resolved, FileAccess.READ)
	if file == null:
		return gml_error("GML buffer_load failed: " + gml_string(path))
	var bytes = file.get_buffer(file.get_length())
	file.close()
	var handle = gml_buffer_create(bytes.size(), GML_BUFFER_GROW, 1)
	var buffer = _gml_buffer_resolve(handle)
	if buffer != null:
		buffer.data = bytes
		buffer.used_size = bytes.size()
	return handle


static func gml_buffer_save_async(buffer_id, path, offset = 0, size = -1):
	var buffer = _gml_buffer_resolve(buffer_id)
	var async_id = _gml_buffer_next_async_id()
	var status = -1
	if buffer != null:
		var byte_count = _to_int64_value(size)
		var bytes = _gml_buffer_read_bytes(
			buffer,
			max(0, _to_int64_value(offset)),
			buffer.used_size if byte_count < 0 else max(0, byte_count),
		)
		var resolved = _gml_file_resolve_path(path, true)
		_gml_file_ensure_parent_directory(resolved)
		var file = FileAccess.open(resolved, FileAccess.WRITE)
		if file != null:
			file.store_buffer(bytes)
			file.close()
			status = 0
	gml_async_dispatch("save_load", {
		"id": async_id,
		"status": status,
		"filename": gml_string(path)
	}, "_on_async_save_load")
	return async_id


static func gml_buffer_load_async(path):
	var async_id = _gml_buffer_next_async_id()
	var buffer = gml_buffer_load(path)
	gml_async_dispatch("save_load", {
		"id": async_id,
		"status": 0 if gml_buffer_exists(buffer) else -1,
		"filename": gml_string(path),
		"buffer": buffer
	}, "_on_async_save_load")
	return async_id


static func gml_buffer_base64_encode(buffer_id, offset, size):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return ""
	var bytes = _gml_buffer_read_bytes(buffer, max(0, _to_int64_value(offset)), max(0, _to_int64_value(size)))
	return Marshalls.raw_to_base64(bytes)


static func gml_buffer_base64_decode(value):
	var bytes = Marshalls.base64_to_raw(str(value))
	var handle = gml_buffer_create(bytes.size(), GML_BUFFER_GROW, 1)
	var buffer = _gml_buffer_resolve(handle)
	if buffer != null:
		buffer.data = bytes
		buffer.used_size = bytes.size()
	return handle


static func gml_buffer_md5(buffer_id, offset, size):
	return _gml_buffer_hash(buffer_id, offset, size, HashingContext.HASH_MD5)


static func gml_buffer_sha1(buffer_id, offset, size):
	return _gml_buffer_hash(buffer_id, offset, size, HashingContext.HASH_SHA1)


static func gml_buffer_sha256(buffer_id, offset, size):
	return _gml_buffer_hash(buffer_id, offset, size, HashingContext.HASH_SHA256)


static func gml_buffer_crc32(buffer_id, offset, size):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return 0
	var bytes = _gml_buffer_read_bytes(buffer, max(0, _to_int64_value(offset)), max(0, _to_int64_value(size)))
	var crc = 0xffffffff
	for byte in bytes:
		crc = crc ^ int(byte)
		for _bit in range(8):
			if (crc & 1) != 0:
				crc = (crc >> 1) ^ 0xedb88320
			else:
				crc = crc >> 1
	return int((crc ^ 0xffffffff) & 0xffffffff)


static func _gml_buffer_resolve(buffer_id):
	var handle = gml_handle_from_value(GML_BUFFER_HANDLE_KIND, buffer_id)
	if gml_handle_is_valid(handle) and handle.reference is GMLBuffer:
		return handle.reference
	return null


static func _gml_buffer_next_async_id():
	var async_id = _gml_buffer_async_next_id
	_gml_buffer_async_next_id += 1
	return async_id


static func _gml_buffer_hash(buffer_id, offset, size, hash_type):
	var buffer = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return ""
	var bytes = _gml_buffer_read_bytes(buffer, max(0, _to_int64_value(offset)), max(0, _to_int64_value(size)))
	var ctx = HashingContext.new()
	ctx.start(hash_type)
	ctx.update(bytes)
	return ctx.finish().hex_encode()


static func _gml_buffer_used_bytes(buffer):
	return _gml_buffer_read_bytes(buffer, 0, buffer.used_size)


static func _gml_buffer_value_size(buffer, offset, value_type):
	if value_type == GML_BUFFER_STRING:
		var length = 0
		while offset + length < buffer.used_size and _gml_buffer_read_u8(buffer, offset + length) != 0:
			length += 1
		return length + 1
	if value_type == GML_BUFFER_TEXT:
		return max(0, buffer.used_size - offset)
	if value_type == GML_BUFFER_F64:
		return 8
	if value_type in [GML_BUFFER_U32, GML_BUFFER_S32, GML_BUFFER_F32]:
		return 4
	if value_type in [GML_BUFFER_U16, GML_BUFFER_S16]:
		return 2
	return 1


static func _gml_buffer_read_value(buffer, offset, value_type):
	if value_type == GML_BUFFER_U8:
		return _gml_buffer_read_u8(buffer, offset)
	if value_type == GML_BUFFER_S8:
		return _gml_buffer_sign_extend(_gml_buffer_read_uint(buffer, offset, 1), 8)
	if value_type == GML_BUFFER_U16:
		return _gml_buffer_read_uint(buffer, offset, 2)
	if value_type == GML_BUFFER_S16:
		return _gml_buffer_sign_extend(_gml_buffer_read_uint(buffer, offset, 2), 16)
	if value_type == GML_BUFFER_U32:
		return _gml_buffer_read_uint(buffer, offset, 4)
	if value_type == GML_BUFFER_S32:
		return _gml_buffer_sign_extend(_gml_buffer_read_uint(buffer, offset, 4), 32)
	if value_type == GML_BUFFER_F32:
		var bytes = _gml_buffer_read_bytes(buffer, offset, 4)
		return bytes.decode_float(0)
	if value_type == GML_BUFFER_F64:
		var bytes = _gml_buffer_read_bytes(buffer, offset, 8)
		return bytes.decode_double(0)
	if value_type == GML_BUFFER_BOOL:
		return _gml_buffer_read_u8(buffer, offset) != 0
	if value_type == GML_BUFFER_STRING:
		var bytes = PackedByteArray()
		var index = 0
		while offset + index < buffer.used_size:
			var byte = _gml_buffer_read_u8(buffer, offset + index)
			if byte == 0:
				break
			bytes.append(byte)
			index += 1
		return bytes.get_string_from_utf8()
	if value_type == GML_BUFFER_TEXT:
		return _gml_buffer_read_bytes(buffer, offset, max(0, buffer.used_size - offset)).get_string_from_utf8()
	return _gml_buffer_read_u8(buffer, offset)


static func _gml_buffer_write_value(buffer, offset, value_type, value):
	if value_type == GML_BUFFER_U8 or value_type == GML_BUFFER_S8:
		_gml_buffer_write_uint(buffer, offset, _to_int64_value(value), 1)
		return 1
	if value_type == GML_BUFFER_U16 or value_type == GML_BUFFER_S16:
		_gml_buffer_write_uint(buffer, offset, _to_int64_value(value), 2)
		return 2
	if value_type == GML_BUFFER_U32 or value_type == GML_BUFFER_S32:
		_gml_buffer_write_uint(buffer, offset, _to_int64_value(value), 4)
		return 4
	if value_type == GML_BUFFER_F32:
		var bytes = PackedByteArray()
		bytes.resize(4)
		bytes.encode_float(0, _to_real(value))
		_gml_buffer_write_bytes(buffer, offset, bytes)
		return 4
	if value_type == GML_BUFFER_F64:
		var bytes = PackedByteArray()
		bytes.resize(8)
		bytes.encode_double(0, _to_real(value))
		_gml_buffer_write_bytes(buffer, offset, bytes)
		return 8
	if value_type == GML_BUFFER_BOOL:
		_gml_buffer_write_uint(buffer, offset, 1 if gml_bool(value) else 0, 1)
		return 1
	if value_type == GML_BUFFER_STRING:
		var bytes = gml_string(value).to_utf8_buffer()
		bytes.append(0)
		_gml_buffer_write_bytes(buffer, offset, bytes)
		return bytes.size()
	if value_type == GML_BUFFER_TEXT:
		var bytes = gml_string(value).to_utf8_buffer()
		_gml_buffer_write_bytes(buffer, offset, bytes)
		return bytes.size()
	_gml_buffer_write_uint(buffer, offset, _to_int64_value(value), 1)
	return 1


static func _gml_buffer_read_uint(buffer, offset, byte_count):
	var value = 0
	for index in range(byte_count):
		value |= _gml_buffer_read_u8(buffer, offset + index) << (8 * index)
	return value


static func _gml_buffer_write_uint(buffer, offset, value, byte_count):
	var bytes = PackedByteArray()
	for index in range(byte_count):
		bytes.append((int(value) >> (8 * index)) & 0xff)
	_gml_buffer_write_bytes(buffer, offset, bytes)


static func _gml_buffer_read_u8(buffer, offset):
	if buffer.data.size() == 0:
		return 0
	var index = _gml_buffer_index(buffer, offset)
	if index < 0 or index >= buffer.data.size():
		return 0
	return int(buffer.data[index])


static func _gml_buffer_read_bytes(buffer, offset, size):
	var bytes = PackedByteArray()
	for index in range(max(0, size)):
		bytes.append(_gml_buffer_read_u8(buffer, offset + index))
	return bytes


static func _gml_buffer_write_bytes(buffer, offset, bytes):
	var end = offset + bytes.size()
	if not _gml_buffer_ensure_capacity(buffer, end):
		return false
	for index in range(bytes.size()):
		var target = _gml_buffer_index(buffer, offset + index)
		if target >= 0 and target < buffer.data.size():
			buffer.data[target] = int(bytes[index]) & 0xff
	buffer.used_size = min(max(buffer.used_size, end), buffer.data.size()) if buffer.buffer_type == GML_BUFFER_WRAP else max(buffer.used_size, end)
	return true


static func _gml_buffer_ensure_capacity(buffer, end):
	if end <= buffer.data.size():
		return true
	if buffer.buffer_type == GML_BUFFER_WRAP and buffer.data.size() > 0:
		return true
	if buffer.buffer_type == GML_BUFFER_GROW or buffer.buffer_type == GML_BUFFER_FAST:
		var new_size = max(end, max(buffer.data.size() * 2, 1))
		buffer.data.resize(new_size)
		return true
	return false


static func _gml_buffer_index(buffer, offset):
	var index = int(offset)
	if buffer.buffer_type == GML_BUFFER_WRAP and buffer.data.size() > 0:
		return posmod(index, buffer.data.size())
	return index


static func _gml_buffer_align_position(position, alignment):
	var resolved_alignment = max(1, int(alignment))
	if resolved_alignment <= 1:
		return position
	var remainder = int(position) % resolved_alignment
	if remainder == 0:
		return position
	return position + (resolved_alignment - remainder)


static func _gml_buffer_sign_extend(value, bits):
	var sign_bit = 1 << (bits - 1)
	var mask = (1 << bits) - 1
	var masked = int(value) & mask
	if (masked & sign_bit) != 0:
		return masked - (1 << bits)
	return masked
