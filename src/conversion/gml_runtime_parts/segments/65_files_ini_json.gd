const GML_FILE_TEXT_HANDLE_KIND = "file_text"
const GML_FILE_USER_ROOT = "user://gm2godot"
const GML_FILE_DATAFILES_ROOT = "res://datafiles"

static var _gml_ini_config = ConfigFile.new()
static var _gml_ini_path = ""
static var _gml_ini_open = false


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
	return DirAccess.dir_exists_absolute(_gml_file_resolve_path(path, false))


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


static func gml_ini_open(path):
	var read_path = _gml_file_resolve_path(path, false)
	var write_path = _gml_file_resolve_path(path, true)
	_gml_ini_config = ConfigFile.new()
	if FileAccess.file_exists(read_path):
		var err = _gml_ini_config.load(read_path)
		if err != OK:
			return gml_error("GML ini_open failed: " + gml_string(path))
	_gml_ini_path = write_path
	_gml_ini_open = true
	return null


static func gml_ini_close():
	if _gml_ini_open and _gml_ini_path != "":
		_gml_file_ensure_parent_directory(_gml_ini_path)
		_gml_ini_config.save(_gml_ini_path)
	_gml_ini_config = ConfigFile.new()
	_gml_ini_path = ""
	_gml_ini_open = false
	return null


static func gml_ini_read_string(section, key, default_value):
	if not _gml_ini_open:
		return default_value
	return str(_gml_ini_config.get_value(str(section), str(key), default_value))


static func gml_ini_read_real(section, key, default_value):
	if not _gml_ini_open:
		return default_value
	var value = _gml_ini_config.get_value(str(section), str(key), default_value)
	if is_number(value):
		return value
	var text = str(value).strip_edges()
	if text.is_valid_int():
		return int(text)
	return text.to_float()


static func gml_ini_write_string(section, key, value):
	_gml_ini_ensure_open()
	_gml_ini_config.set_value(str(section), str(key), gml_string(value))
	return null


static func gml_ini_write_real(section, key, value):
	_gml_ini_ensure_open()
	_gml_ini_config.set_value(str(section), str(key), _to_real(value))
	return null


static func gml_ini_section_exists(section):
	if not _gml_ini_open:
		return false
	return _gml_ini_config.has_section(str(section))


static func gml_ini_key_exists(section, key):
	if not _gml_ini_open:
		return false
	return _gml_ini_config.has_section_key(str(section), str(key))


static func gml_ini_key_delete(section, key):
	if _gml_ini_open:
		_gml_ini_config.erase_section_key(str(section), str(key))
	return null


static func gml_ini_section_delete(section):
	if _gml_ini_open:
		_gml_ini_config.erase_section(str(section))
	return null


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
	return gml_json_decode(text)


static func _gml_file_text_file(file_id):
	var handle = gml_handle_from_value(GML_FILE_TEXT_HANDLE_KIND, file_id)
	if not gml_handle_is_valid(handle):
		return null
	var state = handle.reference
	if state is Dictionary and state.get("file") is FileAccess:
		return state["file"]
	return null


static func _gml_file_resolve_path(path, write = false):
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
	if FileAccess.file_exists(user_path) or DirAccess.dir_exists_absolute(user_path):
		return user_path
	var data_path = GML_FILE_DATAFILES_ROOT + "/" + relative
	if FileAccess.file_exists(data_path) or DirAccess.dir_exists_absolute(data_path):
		return data_path
	return user_path


static func _gml_file_plain_path(path):
	return str(path).replace("\\", "/").strip_edges()


static func _gml_file_relative_path(path):
	var relative = str(path).replace("\\", "/").strip_edges()
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


static func _gml_ini_ensure_open():
	if not _gml_ini_open:
		_gml_ini_config = ConfigFile.new()
		_gml_ini_path = GML_FILE_USER_ROOT + "/default.ini"
		_gml_ini_open = true


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
		for key in value.keys():
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
	for key in ds.keys():
		result[gml_string(key)] = _gml_json_compatible(ds[key])
	return result
