const GML_FILE_TEXT_HANDLE_KIND = "file_text"
const GML_FILE_BINARY_HANDLE_KIND = "file_binary"
const GML_FILE_USER_ROOT = "user://gm2godot"
const GML_FILE_INCLUDED_FILES_ROOT = "res://included_files"
const GML_INCLUDED_FILE_REGISTRY_PATH = "res://gm2godot/gml_included_file_registry.gd"
const GML_INCLUDED_FILE_TRANSACTION_PATH = "res://.gm2godot-included-files-transaction.json"
const GML_INCLUDED_FILE_HASH_CHUNK_SIZE = 1048576
const GML_FILE_BIN_READ = 0
const GML_FILE_BIN_WRITE = 1
const GML_FILE_BIN_READ_WRITE = 2

# The open INI file: its sections by name, each holding its keys and their
# value text, in file order.
static var _gml_ini_sections = {}
static var _gml_ini_path = ""
static var _gml_ini_open = false
static var _gml_ini_changed = false
static var _gml_included_file_registry_loaded = false
static var _gml_included_file_registry_available = false
static var _gml_included_file_registry_requires_content_receipts = false
static var _gml_included_file_exact_paths = {}
static var _gml_included_file_canonical_paths = {}
static var _gml_included_file_ambiguous_paths = {}
static var _gml_included_file_integrity_entries = []
static var _gml_included_file_integrity_established = false
static var _gml_included_file_integrity_hash_attempts = 0
static var _gml_included_file_integrity_hash_payload_bytes = 0
static var _gml_included_file_integrity_hash_elapsed_usec = 0
static var _gml_included_file_verified_payloads = {}


static func gml_file_resolve_path(path, write = false):
	return _gml_file_resolve_path(path, write)


static func gml_working_directory():
	return GML_FILE_USER_ROOT + "/"


static func gml_program_directory():
	return "res://"


static func gml_temp_directory():
	return "user://tmp/"


static func gml_file_exists(path):
	return FileAccess.file_exists(_gml_file_resolve_path(path, false))


static func gml_file_delete(path):
	var resolved = _gml_file_resolve_path(path, true)
	if not FileAccess.file_exists(resolved):
		return false
	return DirAccess.remove_absolute(resolved) == OK


static func gml_directory_exists(path):
	return DirAccess.dir_exists_absolute(_gml_file_resolve_path(path, false, true))


static func gml_directory_create(path):
	var resolved = _gml_file_resolve_path(path, true)
	return DirAccess.make_dir_recursive_absolute(resolved) == OK


static func gml_directory_destroy(path):
	var resolved = _gml_file_resolve_path(path, true)
	if not DirAccess.dir_exists_absolute(resolved):
		return false
	return DirAccess.remove_absolute(resolved) == OK


static func gml_file_text_open_read(path):
	var resolved = _gml_file_resolve_path(path, false)
	if not FileAccess.file_exists(resolved):
		return gml_error("GML file_text_open_read missing file: " + gml_string(path))
	var file = FileAccess.open(resolved, FileAccess.READ)
	if file == null:
		return gml_error("GML file_text_open_read failed: " + gml_string(path))
	return gml_handle_register(GML_FILE_TEXT_HANDLE_KIND, {
		"file": file,
		"mode": "read",
		"path": resolved
	})


static func gml_file_text_open_write(path):
	var resolved = _gml_file_resolve_path(path, true)
	_gml_file_ensure_parent_directory(resolved)
	var file = FileAccess.open(resolved, FileAccess.WRITE)
	if file == null:
		return gml_error("GML file_text_open_write failed: " + gml_string(path))
	return gml_handle_register(GML_FILE_TEXT_HANDLE_KIND, {
		"file": file,
		"mode": "write",
		"path": resolved
	})


static func gml_file_text_open_append(path):
	var resolved = _gml_file_resolve_path(path, true)
	_gml_file_ensure_parent_directory(resolved)
	var file = FileAccess.open(resolved, FileAccess.READ_WRITE)
	if file == null:
		file = FileAccess.open(resolved, FileAccess.WRITE)
	if file == null:
		return gml_error("GML file_text_open_append failed: " + gml_string(path))
	file.seek_end()
	return gml_handle_register(GML_FILE_TEXT_HANDLE_KIND, {
		"file": file,
		"mode": "append",
		"path": resolved
	})


static func gml_file_text_close(file_id):
	var handle = gml_handle_from_value(GML_FILE_TEXT_HANDLE_KIND, file_id)
	if not gml_handle_is_valid(handle):
		return null
	var state = handle.reference
	if state is Dictionary and state.get("file") is FileAccess:
		state["file"].close()
	gml_handle_invalidate(handle)
	return null


static func gml_file_text_eof(file_id):
	var file = _gml_file_text_file(file_id)
	if file == null:
		return true
	return file.get_position() >= file.get_length()


static func gml_file_text_read_string(file_id):
	var file = _gml_file_text_file(file_id)
	if file == null or file.eof_reached():
		return ""
	return file.get_line()


static func gml_file_text_readln(file_id):
	return gml_file_text_read_string(file_id)


static func gml_file_text_read_real(file_id):
	var text = gml_file_text_read_string(file_id).strip_edges()
	if text == "":
		return 0
	if text.is_valid_int():
		return int(text)
	return text.to_float()


static func gml_file_text_write_string(file_id, value):
	var file = _gml_file_text_file(file_id)
	if file == null:
		return null
	file.store_string(gml_string(value))
	return null


static func gml_file_text_write_real(file_id, value):
	return gml_file_text_write_string(file_id, value)


static func gml_file_text_writeln(file_id):
	var file = _gml_file_text_file(file_id)
	if file == null:
		return null
	file.store_string("\n")
	return null


static func gml_file_bin_open(path, mode):
	var mode_value = _to_int64_value(mode)
	var write_enabled = mode_value != GML_FILE_BIN_READ
	var resolved = _gml_file_resolve_path(path, write_enabled)
	var access_mode = FileAccess.READ
	if mode_value == GML_FILE_BIN_WRITE:
		_gml_file_ensure_parent_directory(resolved)
		access_mode = FileAccess.WRITE_READ
	elif mode_value == GML_FILE_BIN_READ_WRITE:
		_gml_file_ensure_parent_directory(resolved)
		access_mode = FileAccess.READ_WRITE if FileAccess.file_exists(resolved) else FileAccess.WRITE_READ
	elif not FileAccess.file_exists(resolved):
		_gml_file_ensure_parent_directory(resolved)
		var created_file = FileAccess.open(resolved, FileAccess.WRITE_READ)
		if created_file == null:
			return gml_error("GML file_bin_open failed: " + gml_string(path))
		created_file.close()
	var file = FileAccess.open(resolved, access_mode)
	if file == null:
		return gml_error("GML file_bin_open failed: " + gml_string(path))
	return gml_handle_register(GML_FILE_BINARY_HANDLE_KIND, {
		"file": file,
		"mode": mode_value,
		"path": resolved
	})


static func gml_file_bin_rewrite(file_id):
	var state = _gml_file_bin_state(file_id)
	if not (state is Dictionary):
		return null
	var path = str(state.get("path", ""))
	if path == "":
		return null
	var current_file = state.get("file", null)
	if current_file is FileAccess:
		current_file.close()
	_gml_file_ensure_parent_directory(path)
	state["file"] = FileAccess.open(path, FileAccess.WRITE_READ)
	state["mode"] = GML_FILE_BIN_READ_WRITE
	return null


static func gml_file_bin_close(file_id):
	var handle = gml_handle_from_value(GML_FILE_BINARY_HANDLE_KIND, file_id)
	if not gml_handle_is_valid(handle):
		return null
	var state = handle.reference
	if state is Dictionary and state.get("file") is FileAccess:
		state["file"].close()
	gml_handle_invalidate(handle)
	return null


static func gml_file_bin_size(file_id):
	var file = _gml_file_bin_file(file_id)
	if file == null:
		return 0
	return file.get_length()


static func gml_file_bin_position(file_id):
	var file = _gml_file_bin_file(file_id)
	if file == null:
		return 0
	return file.get_position()


static func gml_file_bin_seek(file_id, position):
	var file = _gml_file_bin_file(file_id)
	if file == null:
		return null
	file.seek(max(0, _to_int64_value(position)))
	return null


static func gml_file_bin_read_byte(file_id):
	var file = _gml_file_bin_file(file_id)
	if file == null or file.eof_reached():
		return 0
	return file.get_8()


static func gml_file_bin_write_byte(file_id, byte_value):
	var file = _gml_file_bin_file(file_id)
	if file == null:
		return null
	file.store_8(int(_to_int64_value(byte_value)) & 0xff)
	return null


static func gml_filename_name(path):
	var file_name = _gml_file_plain_path(path).get_file()
	var extension = file_name.get_extension()
	if extension == "":
		return file_name
	return file_name.substr(0, file_name.length() - extension.length() - 1)


static func gml_filename_ext(path):
	var extension = _gml_file_plain_path(path).get_extension()
	if extension == "":
		return ""
	return "." + extension


static func gml_filename_dir(path):
	return _gml_file_plain_path(path).get_base_dir()


static func gml_filename_path(path):
	var directory = gml_filename_dir(path)
	if directory == "":
		return ""
	return directory.trim_suffix("/") + "/"


static func gml_filename_change_ext(path, extension):
	var base = _gml_file_plain_path(path).get_basename()
	var ext = str(extension)
	if ext != "" and not ext.begins_with("."):
		ext = "." + ext
	return base + ext


# INI files follow GameMaker's format and rules: every value is kept as
# text, a file is only written by ini_close after something changed it, and
# opening an INI file closes the one still open. ini_open reads the save
# area first and falls back to the included file of the same name.
static func gml_ini_open(path):
	if _gml_ini_open:
		gml_ini_close()
	var write_path = _gml_file_resolve_path(path, true)
	var sections = _gml_ini_load_sections(write_path)
	if sections.is_empty():
		var read_path = _gml_file_resolve_path(path, false)
		if read_path != write_path:
			sections = _gml_ini_load_sections(read_path)
	_gml_ini_begin(sections, write_path)
	return null


static func gml_ini_open_from_string(content):
	if _gml_ini_open:
		gml_ini_close()
	# An INI opened from a string has no file; ini_close only returns it.
	_gml_ini_begin(_gml_ini_parse(gml_string(content)), "")
	return null


static func gml_ini_close():
	if not _gml_ini_open:
		return gml_undefined()
	var text = _gml_ini_text(_gml_ini_sections)
	if _gml_ini_changed and _gml_ini_path != "":
		_gml_file_ensure_parent_directory(_gml_ini_path)
		var file = FileAccess.open(_gml_ini_path, FileAccess.WRITE)
		if file != null:
			file.store_string(text)
			file.close()
	_gml_ini_begin({}, "")
	_gml_ini_open = false
	return text


static func gml_ini_read_string(section, key, default_value):
	var value: Variant = _gml_ini_value(section, key)
	if value == null:
		return gml_string(default_value)
	return value


static func gml_ini_read_real(section, key, default_value):
	var value: Variant = _gml_ini_value(section, key)
	if value == null:
		if is_string(default_value):
			return _gml_ini_text_to_real(default_value)
		return float(_to_real(default_value))
	return _gml_ini_text_to_real(value)


static func gml_ini_write_string(section, key, value):
	_gml_ini_set_value(section, key, gml_string(value))
	return null


static func gml_ini_write_real(section, key, value):
	_gml_ini_set_value(section, key, _gml_ini_real_text(_to_real(value)))
	return null


static func gml_ini_section_exists(section):
	return _gml_ini_open and _gml_ini_sections.has(gml_string(section))


static func gml_ini_key_exists(section, key):
	return _gml_ini_value(section, key) != null


static func gml_ini_key_delete(section, key):
	if _gml_ini_value(section, key) == null:
		return false
	_gml_ini_sections[gml_string(section)].erase(gml_string(key))
	_gml_ini_changed = true
	return true


static func gml_ini_section_delete(section):
	var name = gml_string(section)
	if not _gml_ini_open or not _gml_ini_sections.has(name):
		return false
	_gml_ini_sections.erase(name)
	_gml_ini_changed = true
	return true


static func gml_json_encode(value):
	return JSON.stringify(_gml_json_compatible(value))


static func gml_json_decode(text):
	var decoded = JSON.parse_string(str(text))
	if decoded == null and str(text).strip_edges() != "null":
		return gml_undefined()
	return decoded


static func gml_json_stringify(value):
	return gml_json_encode(value)


static func gml_json_parse(text):
	var decoded = gml_json_decode(text)
	# A decoded null needs the text to contain "null" (inside a string too,
	# which only costs the walk), so most documents are not walked at all.
	if not str(text).contains("null"):
		return decoded
	return _gml_json_nulls_to_undefined(decoded)


# json_parse turns every JSON null into undefined (the runner's reviver makes
# it pointer_null and json_convert_pointer_null then replaces those with
# undefined, top-level value and nested members and elements alike), since a
# GML value is never a raw null.
static func _gml_json_nulls_to_undefined(value):
	var value_type = typeof(value)
	if value_type == TYPE_NIL:
		return gml_undefined()
	if value_type == TYPE_ARRAY:
		for index in range(value.size()):
			var item = value[index]
			if typeof(item) == TYPE_NIL:
				value[index] = gml_undefined()
			elif typeof(item) == TYPE_ARRAY or typeof(item) == TYPE_DICTIONARY:
				_gml_json_nulls_to_undefined(item)
	elif value_type == TYPE_DICTIONARY:
		for key in value.keys():
			var item = value[key]
			if typeof(item) == TYPE_NIL:
				value[key] = gml_undefined()
			elif typeof(item) == TYPE_ARRAY or typeof(item) == TYPE_DICTIONARY:
				_gml_json_nulls_to_undefined(item)
	return value


static func _gml_file_text_file(file_id):
	var handle = gml_handle_from_value(GML_FILE_TEXT_HANDLE_KIND, file_id)
	if not gml_handle_is_valid(handle):
		return null
	var state = handle.reference
	if state is Dictionary and state.get("file") is FileAccess:
		return state["file"]
	return null


static func _gml_file_bin_state(file_id):
	var handle = gml_handle_from_value(GML_FILE_BINARY_HANDLE_KIND, file_id)
	if not gml_handle_is_valid(handle):
		return null
	return handle.reference


static func _gml_file_bin_file(file_id):
	var state = _gml_file_bin_state(file_id)
	if state is Dictionary and state.get("file") is FileAccess:
		return state["file"]
	return null


static func _gml_file_resolve_path(path, write = false, expect_directory = false):
	var text = _gml_file_plain_path(path)
	if text.begins_with("user://"):
		return text
	if text.begins_with("res://"):
		if write:
			return GML_FILE_USER_ROOT + "/res/" + text.substr(6).trim_prefix("/")
		return text
	var relative = _gml_file_relative_path(text)
	var user_path = GML_FILE_USER_ROOT + "/" + relative
	if write:
		return user_path
	if expect_directory and DirAccess.dir_exists_absolute(user_path):
		return user_path
	if not expect_directory and FileAccess.file_exists(user_path):
		return user_path
	# A durable transaction journal means the two public paths are being
	# recovered. Relative GML lookups must not observe either transient path.
	if (
		FileAccess.file_exists(GML_INCLUDED_FILE_TRANSACTION_PATH)
		or DirAccess.dir_exists_absolute(GML_INCLUDED_FILE_TRANSACTION_PATH)
	):
		return user_path
	var logical_path = _gml_file_registry_logical_path(relative)
	var packaged_relative = _gml_file_packaged_relative_path(
		logical_path if logical_path != "" else relative
	)
	var packaged_path = GML_FILE_INCLUDED_FILES_ROOT + "/" + packaged_relative
	if expect_directory:
		if DirAccess.dir_exists_absolute(packaged_path):
			return packaged_path
		return user_path

	_gml_included_file_registry_ensure_loaded()
	if _gml_included_file_registry_available and logical_path != "":
		if _gml_included_file_exact_paths.has(logical_path):
			var exact_path = _gml_included_file_registry_output_path(
				_gml_included_file_exact_paths[logical_path]
			)
			if exact_path != "" and FileAccess.file_exists(exact_path):
				return exact_path
			return user_path
		if _gml_included_file_ambiguous_paths.has(packaged_relative):
			return user_path
		if _gml_included_file_canonical_paths.has(packaged_relative):
			var canonical_path = _gml_included_file_registry_output_path(
				_gml_included_file_canonical_paths[packaged_relative]
			)
			if canonical_path != "" and FileAccess.file_exists(canonical_path):
				return canonical_path
			return user_path
		if _gml_included_file_registry_requires_content_receipts:
			return user_path

	if (
		_gml_included_file_registry_available
		and not _gml_included_file_registry_requires_content_receipts
		and FileAccess.file_exists(packaged_path)
	):
		return packaged_path
	return user_path


static func gml_included_file_integrity_prewarm():
	_gml_included_file_registry_ensure_loaded()
	if not _gml_included_file_registry_available:
		return false
	if not _gml_included_file_registry_requires_content_receipts:
		return true
	if _gml_included_file_integrity_established:
		return true
	_gml_included_file_verified_payloads = {}
	if _gml_included_file_transaction_present():
		return false
	for entry in _gml_included_file_integrity_entries:
		if not _gml_included_file_registry_verify_entry(entry):
			_gml_included_file_verified_payloads = {}
			return false
	if _gml_included_file_transaction_present():
		_gml_included_file_verified_payloads = {}
		return false
	_gml_included_file_integrity_established = true
	return true


static func gml_included_file_integrity_status():
	_gml_included_file_registry_ensure_loaded()
	return {
		"registry_available": _gml_included_file_registry_available,
		"requires_content_receipts": _gml_included_file_registry_requires_content_receipts,
		"integrity_established": _gml_included_file_integrity_established,
		"entry_count": _gml_included_file_integrity_entries.size(),
		"verified_count": _gml_included_file_verified_payloads.size(),
		"hash_attempts": _gml_included_file_integrity_hash_attempts,
		"hash_payload_bytes": _gml_included_file_integrity_hash_payload_bytes,
		"hash_elapsed_usec": _gml_included_file_integrity_hash_elapsed_usec,
	}


static func _gml_included_file_registry_ensure_loaded():
	if _gml_included_file_registry_loaded:
		return
	_gml_included_file_registry_loaded = true
	_gml_included_file_registry_available = false
	_gml_included_file_registry_requires_content_receipts = false
	_gml_included_file_exact_paths = {}
	_gml_included_file_canonical_paths = {}
	_gml_included_file_ambiguous_paths = {}
	_gml_included_file_integrity_entries = []
	_gml_included_file_integrity_established = false
	_gml_included_file_verified_payloads = {}
	if not ResourceLoader.exists(GML_INCLUDED_FILE_REGISTRY_PATH):
		return
	var registry_script = load(GML_INCLUDED_FILE_REGISTRY_PATH)
	if registry_script == null or not registry_script.has_method("gml_included_file_registry_entries"):
		return
	var format_version = 1
	if registry_script.has_method("gml_included_file_registry_format_version"):
		format_version = int(
			registry_script.gml_included_file_registry_format_version()
		)
	if format_version != 2:
		return
	var requires_content_receipts = true
	var entries = registry_script.gml_included_file_registry_entries()
	if not (entries is Array):
		return
	var exact_paths = {}
	var canonical_candidates = {}
	var integrity_entries = []
	var assigned_paths = {}
	for entry in entries:
		if typeof(entry) != TYPE_DICTIONARY:
			if requires_content_receipts:
				return
			continue
		if (
			requires_content_receipts
			and (
				typeof(entry.get("logical_path", null)) != TYPE_STRING
				or typeof(entry.get("canonical_path", null)) != TYPE_STRING
				or typeof(entry.get("assigned_path", null)) != TYPE_STRING
				or typeof(entry.get("emitted", null)) != TYPE_BOOL
			)
		):
			return
		var logical_path = _gml_file_registry_logical_path(
			str(entry.get("logical_path", ""))
		)
		var canonical_path = str(entry.get("canonical_path", ""))
		var assigned_path = str(entry.get("assigned_path", ""))
		var emitted = bool(entry.get("emitted", true))
		if (
			logical_path == ""
			or canonical_path == ""
			or assigned_path == ""
			or canonical_path != _gml_file_packaged_relative_path(logical_path)
			or _gml_file_registry_logical_path(assigned_path) != assigned_path
		):
			if requires_content_receipts:
				return
			continue
		if (
			requires_content_receipts
			and (
				exact_paths.has(logical_path)
				or assigned_paths.has(assigned_path)
			)
		):
			return
		var normalized_entry = {
			"assigned_path": assigned_path,
			"emitted": emitted,
			"byte_count": int(entry.get("byte_count", -1)),
			"content_sha256": str(entry.get("content_sha256", "")).to_lower()
		}
		if (
			requires_content_receipts
			and emitted
			and (
				typeof(entry.get("byte_count", null)) != TYPE_INT
				or int(entry.get("byte_count", -1)) < 0
				or typeof(entry.get("content_sha256", null)) != TYPE_STRING
				or not _gml_file_valid_sha256(
					str(entry.get("content_sha256", "")).to_lower()
				)
			)
		):
			return
		exact_paths[logical_path] = normalized_entry
		assigned_paths[assigned_path] = true
		if requires_content_receipts and emitted:
			integrity_entries.append(normalized_entry)
		if not canonical_candidates.has(canonical_path):
			canonical_candidates[canonical_path] = []
		canonical_candidates[canonical_path].append(normalized_entry)
	var canonical_paths = {}
	var ambiguous_paths = {}
	for candidate_key in canonical_candidates:
		var candidates = canonical_candidates[candidate_key]
		if candidates.size() == 1:
			canonical_paths[candidate_key] = candidates[0]
		else:
			ambiguous_paths[candidate_key] = true
	_gml_included_file_registry_requires_content_receipts = requires_content_receipts
	_gml_included_file_exact_paths = exact_paths
	_gml_included_file_canonical_paths = canonical_paths
	_gml_included_file_ambiguous_paths = ambiguous_paths
	_gml_included_file_integrity_entries = integrity_entries
	_gml_included_file_registry_available = true


static func _gml_included_file_registry_output_path(entry):
	if typeof(entry) != TYPE_DICTIONARY or not bool(entry.get("emitted", false)):
		return ""
	var assigned_path = str(entry.get("assigned_path", ""))
	if (
		assigned_path == ""
		or _gml_file_registry_logical_path(assigned_path) != assigned_path
	):
		return ""
	var output_path = GML_FILE_INCLUDED_FILES_ROOT + "/" + assigned_path
	if not _gml_included_file_registry_requires_content_receipts:
		return output_path
	if not _gml_included_file_integrity_established:
		return ""
	var verification_key = _gml_included_file_registry_verification_key(
		entry,
		output_path
	)
	if (
		verification_key == ""
		or not _gml_included_file_verified_payloads.has(verification_key)
	):
		return ""
	var expected_size = int(entry.get("byte_count", -1))
	if (
		not FileAccess.file_exists(output_path)
		or FileAccess.get_size(output_path) != expected_size
	):
		return ""
	return output_path


static func _gml_included_file_registry_verify_entry(entry):
	var assigned_path = str(entry.get("assigned_path", ""))
	if (
		assigned_path == ""
		or _gml_file_registry_logical_path(assigned_path) != assigned_path
	):
		return false
	var output_path = GML_FILE_INCLUDED_FILES_ROOT + "/" + assigned_path
	var verification_key = _gml_included_file_registry_verification_key(
		entry,
		output_path
	)
	if verification_key == "":
		return false
	var expected_size = int(entry.get("byte_count", -1))
	if (
		not FileAccess.file_exists(output_path)
		or FileAccess.get_size(output_path) != expected_size
	):
		return false
	_gml_included_file_integrity_hash_attempts += 1
	var hash_started_usec = Time.get_ticks_usec()
	var actual_sha256 = _gml_included_file_sha256(output_path, expected_size)
	_gml_included_file_integrity_hash_elapsed_usec += (
		Time.get_ticks_usec() - hash_started_usec
	)
	if actual_sha256 != str(entry.get("content_sha256", "")).to_lower():
		return false
	_gml_included_file_verified_payloads[verification_key] = true
	return true


static func _gml_included_file_registry_verification_key(entry, output_path):
	var expected_size = int(entry.get("byte_count", -1))
	var expected_sha256 = str(entry.get("content_sha256", "")).to_lower()
	if expected_size < 0 or not _gml_file_valid_sha256(expected_sha256):
		return ""
	return output_path + "\n" + str(expected_size) + "\n" + expected_sha256


static func _gml_included_file_sha256(path, expected_size):
	var file = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return ""
	if file.get_length() != expected_size:
		file.close()
		return ""
	var context = HashingContext.new()
	if context.start(HashingContext.HASH_SHA256) != OK:
		file.close()
		return ""
	var remaining = expected_size
	while remaining > 0:
		var read_size = min(remaining, GML_INCLUDED_FILE_HASH_CHUNK_SIZE)
		var chunk = file.get_buffer(read_size)
		if chunk.size() != read_size:
			file.close()
			return ""
		_gml_included_file_integrity_hash_payload_bytes += chunk.size()
		if context.update(chunk) != OK:
			file.close()
			return ""
		remaining -= chunk.size()
	if file.get_position() != expected_size or file.get_length() != expected_size:
		file.close()
		return ""
	file.close()
	var digest = context.finish()
	if digest.size() != 32:
		return ""
	return digest.hex_encode()


static func _gml_included_file_transaction_present():
	return (
		FileAccess.file_exists(GML_INCLUDED_FILE_TRANSACTION_PATH)
		or DirAccess.dir_exists_absolute(GML_INCLUDED_FILE_TRANSACTION_PATH)
	)


static func _gml_file_valid_sha256(value):
	var text = str(value)
	if text.length() != 64:
		return false
	for character in text:
		if not "0123456789abcdef".contains(character):
			return false
	return true


static func _gml_file_registry_logical_path(path):
	var components = []
	for component in str(path).replace("\\", "/").split("/", false):
		if component == ".":
			continue
		if component == "..":
			if components.is_empty():
				return ""
			components.pop_back()
			continue
		components.append(component)
	var normalized = ""
	for component in components:
		if normalized != "":
			normalized += "/"
		normalized += str(component)
	return normalized


static func _gml_file_packaged_relative_path(path):
	var text = str(path)
	var normalized = ""
	for index in range(text.length()):
		var code = text.unicode_at(index)
		if code >= 65 and code <= 90:
			normalized += char(code + 32)
		elif code == 32:
			normalized += "_"
		else:
			normalized += char(code)
	return normalized


static func _gml_file_plain_path(path):
	return str(path).replace("\\", "/")


static func _gml_file_relative_path(path):
	var relative = str(path).replace("\\", "/")
	while relative.begins_with("./"):
		relative = relative.substr(2)
	while relative.begins_with("/"):
		relative = relative.substr(1)
	if relative == "":
		return "root"
	return relative


static func _gml_file_ensure_parent_directory(path):
	var directory = str(path).get_base_dir()
	if directory != "":
		DirAccess.make_dir_recursive_absolute(directory)


static func _gml_ini_begin(sections, path):
	_gml_ini_sections = sections
	_gml_ini_path = path
	_gml_ini_open = true
	_gml_ini_changed = false


static func _gml_ini_value(section, key):
	if not _gml_ini_open:
		return null
	var keys = _gml_ini_sections.get(gml_string(section), null)
	if keys == null:
		return null
	return keys.get(gml_string(key), null)


static func _gml_ini_set_value(section, key, text):
	if not _gml_ini_open:
		# GameMaker stops with an error here; keep the value in a default file.
		_gml_ini_begin({}, GML_FILE_USER_ROOT + "/default.ini")
	var name = gml_string(section)
	if not _gml_ini_sections.has(name):
		_gml_ini_sections[name] = {}
	_gml_ini_sections[name][gml_string(key)] = text
	_gml_ini_changed = true


static func _gml_ini_load_sections(path):
	if path == "" or not FileAccess.file_exists(path):
		return {}
	return _gml_ini_parse(FileAccess.get_file_as_string(path))


# Reads INI text the way GameMaker does: [section] headers, key=value lines
# and comment lines starting with ; or #. A value in double or single quotes
# runs to the closing quote; an unquoted value runs to the end of the line or
# to a ; or # comment (a backslash keeps the next character) and loses its
# surrounding spaces; a value starting with [ or { runs to the end of the
# line. Lines before the first section and keys without a value are ignored.
static func _gml_ini_parse(text):
	var sections = {}
	var current = null
	var source = str(text).trim_prefix(char(0xfeff))
	for raw_line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
		var line = raw_line.strip_edges(true, false)
		if line == "" or line.begins_with(";") or line.begins_with("#"):
			continue
		if line.begins_with("["):
			var close = line.find("]")
			if close < 0:
				continue
			var name = line.substr(1, close - 1)
			if not sections.has(name):
				sections[name] = {}
			current = sections[name]
			continue
		var equals = line.find("=")
		if current == null or equals < 0:
			continue
		var value: Variant = _gml_ini_parse_value(line.substr(equals + 1))
		if value != null:
			current[line.substr(0, equals).strip_edges(false, true)] = value
	return sections


static func _gml_ini_parse_value(text):
	var value = text.strip_edges(true, false)
	if value == "" or value.begins_with(";") or value.begins_with("#"):
		return null
	var first = value.substr(0, 1)
	if first == "\"" or first == "'":
		var close = value.find(first, 1)
		return value.substr(1) if close < 0 else value.substr(1, close - 1)
	if first == "[" or first == "{":
		return value.strip_edges(false, true)
	var end = 0
	while end < value.length():
		var character = value.substr(end, 1)
		if character == ";" or character == "#":
			break
		end += 2 if character == "\\" else 1
	return value.substr(0, end).strip_edges(false, true)


# Writes INI text as GameMaker does: values in double quotes, or in single
# quotes when they contain a double quote, with CR LF line ends.
static func _gml_ini_text(sections):
	var lines = []
	for name in sections.keys():
		lines.append("[" + str(name) + "]")
		var keys = sections[name]
		for key in keys.keys():
			var value = str(keys[key])
			if not value.contains("\""):
				value = "\"" + value + "\""
			elif not value.contains("'"):
				value = "'" + value + "'"
			lines.append(str(key) + "=" + value)
	var text = ""
	for line in lines:
		text += line + "\r\n"
	return text


# The number at the start of the text, like GameMaker's number parsing for
# INI values; text that does not start with a number reads as 0.
# The runner reads an INI real with JavaScript's parseFloat (yyIniFile.js):
# after leading white space, the decimal number or signed "Infinity" the
# text starts with, and NaN when it starts with neither.
static func _gml_ini_text_to_real(text):
	var matched = _gml_ini_number_pattern().search(str(text).strip_edges(true, false))
	if matched == null:
		return NAN
	var number = matched.get_string()
	if number.ends_with("Infinity"):
		return -INF if number.begins_with("-") else INF
	return number.to_float()


static var _gml_ini_number_regex = null


static func _gml_ini_number_pattern():
	if _gml_ini_number_regex == null:
		_gml_ini_number_regex = RegEx.create_from_string("^[+-]?(Infinity|(\\d+\\.?\\d*|\\.\\d+)([eE][+-]?\\d+)?)")
	return _gml_ini_number_regex


# ini_write_real stores the shortest text that reads back as the same number,
# as GameMaker does: whole numbers have no decimals.
static func _gml_ini_real_text(value):
	var number = float(value)
	if is_nan(number):
		return "NaN"
	if is_inf(number):
		return "Infinity" if number > 0.0 else "-Infinity"
	if number == floor(number) and abs(number) < 1e18:
		return str(int(number))
	return var_to_str(number)


static func _gml_json_compatible(value):
	if is_undefined(value):
		return null
	if value == null:
		return null
	if is_nan_value(value) or is_infinity(value):
		return null
	if is_int64(value):
		return value.value
	if is_ptr(value):
		return gml_string(value)
	if is_handle(value):
		if value.kind == GML_DS_LIST_HANDLE_KIND:
			return _gml_json_compatible_ds_list(value)
		if value.kind == GML_DS_MAP_HANDLE_KIND:
			return _gml_json_compatible_ds_map(value)
		return gml_string(value)
	var value_type = typeof(value)
	if value_type == TYPE_ARRAY:
		var arr = []
		for item in value:
			arr.append(_gml_json_compatible(item))
		return arr
	if value_type == TYPE_DICTIONARY:
		var result = {}
		for key in _gml_struct_visible_keys(value):
			result[gml_string(key)] = _gml_json_compatible(value[key])
		return result
	if value_type == TYPE_OBJECT:
		return gml_string(value)
	return value


static func _gml_json_compatible_ds_list(handle):
	var ds = _gml_resolve_ds_list(handle)
	if not (ds is Dictionary):
		return []
	var result = []
	var data = ds.get("data", [])
	var marks = ds.get("marks", {})
	for index in range(data.size()):
		var value = data[index]
		if marks.get(index) == "list":
			result.append(_gml_json_compatible_ds_list(value))
		elif marks.get(index) == "map":
			result.append(_gml_json_compatible_ds_map(value))
		else:
			result.append(_gml_json_compatible(value))
	return result


static func _gml_json_compatible_ds_map(handle):
	var ds = _gml_resolve_ds_map(handle)
	if not (ds is Dictionary):
		return {}
	var result = {}
	for stored_key in ds.keys():
		var key = _gml_ds_map_external_key(stored_key)
		result[gml_string(key)] = _gml_json_compatible(ds[stored_key])
	return result
