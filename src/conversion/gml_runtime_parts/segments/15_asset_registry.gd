const GML_ASSET_REGISTRY_PATH = "res://gm2godot/gml_asset_registry.gd"
const GML_DYNAMIC_ASSET_ID_START = 1073741824
const GML_ASSET_TYPE_ALIASES = {
	"sprite": "sprite",
	"sprites": "sprite",
	"sound": "sound",
	"sounds": "sound",
	"room": "room",
	"rooms": "room",
	"object": "object",
	"objects": "object",
	"script": "script",
	"scripts": "script",
	"font": "font",
	"fonts": "font",
	"path": "path",
	"paths": "path",
	"shader": "shader",
	"shaders": "shader",
	"tileset": "tileset",
	"tilesets": "tileset",
	"timeline": "timeline",
	"timelines": "timeline",
	"sequence": "sequence",
	"sequences": "sequence",
	"included_file": "included_file",
	"included_files": "included_file"
}
const GML_ASSET_TYPE_NAMES = {
	"sprite": "Sprite",
	"sound": "Sound",
	"room": "Room",
	"object": "Object",
	"script": "Script",
	"font": "Font",
	"path": "Path",
	"shader": "Shader",
	"tileset": "Tile Set",
	"timeline": "Timeline",
	"sequence": "Sequence",
	"included_file": "Included File"
}

static var _gml_asset_registry_loaded = false
static var _gml_asset_entries = []
static var _gml_asset_by_name = {}
static var _gml_asset_by_id = {}
static var _gml_asset_by_legacy_id = {}
static var _gml_asset_ids_by_type = {}
static var _gml_asset_dynamic_ids = {}
static var _gml_asset_next_dynamic_id = GML_DYNAMIC_ASSET_ID_START
static var _gml_texture_group_entries = {}
static var _gml_audio_group_entries = {}


static func gml_asset_registry_set(entries):
	_gml_asset_registry_loaded = true
	_gml_asset_entries = []
	_gml_asset_by_name = {}
	_gml_asset_by_id = {}
	_gml_asset_by_legacy_id = {}
	_gml_asset_ids_by_type = {}
	_gml_asset_dynamic_ids = {}
	_gml_asset_next_dynamic_id = GML_DYNAMIC_ASSET_ID_START
	for entry in entries:
		_gml_asset_add_entry(entry)
	return null


static func gml_texture_group_registry_set(entries):
	_gml_texture_group_entries = {}
	for entry in entries:
		if typeof(entry) != TYPE_DICTIONARY:
			continue
		var name = str(entry.get("name", ""))
		if name == "":
			continue
		_gml_texture_group_entries[name] = entry
	return null


static func gml_texture_group_registry_entries():
	_gml_asset_registry_ensure_loaded()
	var entries = []
	var names = _gml_texture_group_entries.keys()
	names.sort()
	for name in names:
		entries.append(_gml_texture_group_entries[name])
	return entries


static func gml_audio_group_registry_set(entries):
	_gml_audio_group_entries = {}
	for entry in entries:
		if typeof(entry) != TYPE_DICTIONARY:
			continue
		var name = str(entry.get("name", ""))
		if name == "":
			continue
		_gml_audio_group_entries[name] = entry
	return null


static func gml_audio_group_registry_entries():
	_gml_asset_registry_ensure_loaded()
	var entries = []
	var names = _gml_audio_group_entries.keys()
	names.sort()
	for name in names:
		entries.append(_gml_audio_group_entries[name])
	return entries


static func gml_asset_registry_entries():
	_gml_asset_registry_ensure_loaded()
	return _gml_asset_entries


static func gml_asset_get_index(asset_name):
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(asset_name)
	if entry == null:
		return -1
	return int(entry["id"])


static func gml_asset_get_type(asset):
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(asset)
	if entry == null:
		return -1
	return str(entry["type"])


static func gml_asset_get_ids(asset_type = null):
	_gml_asset_registry_ensure_loaded()
	if asset_type == null:
		var all_ids = []
		for entry in _gml_asset_entries:
			all_ids.append(entry["legacy_id"])
		return all_ids
	var type_key = _gml_asset_type_key(asset_type)
	if not _gml_asset_ids_by_type.has(type_key):
		return []
	var ids = []
	for asset_id in _gml_asset_ids_by_type[type_key]:
		var entry = _gml_asset_by_id[asset_id]
		ids.append(entry["legacy_id"])
	return ids


static func gml_asset_get_type_name(asset_or_type):
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(asset_or_type)
	if entry != null:
		return str(entry["type_name"])
	var type_key = _gml_asset_type_key(asset_or_type)
	if GML_ASSET_TYPE_NAMES.has(type_key):
		return GML_ASSET_TYPE_NAMES[type_key]
	return ""


static func gml_asset_get_index_from_id(asset_id):
	_gml_asset_registry_ensure_loaded()
	var key = str(asset_id)
	if _gml_asset_by_legacy_id.has(key):
		return int(_gml_asset_by_legacy_id[key]["id"])
	if is_numeric(asset_id):
		var numeric_id = _to_int64_value(asset_id)
		if _gml_asset_by_id.has(numeric_id):
			return numeric_id
	return -1


static func gml_asset_has_any_tag(asset, tags):
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(asset)
	if entry == null:
		return false
	var entry_tags = entry["tags"] if entry.has("tags") else []
	if is_string(tags):
		return entry_tags.has(str(tags))
	if typeof(tags) == TYPE_ARRAY:
		for tag in tags:
			if entry_tags.has(str(tag)):
				return true
	return false


static func gml_asset_register_dynamic(asset_name, asset_type, godot_resource = null, tags = []):
	_gml_asset_registry_ensure_loaded()
	var asset_id = _gml_asset_next_dynamic_id
	_gml_asset_next_dynamic_id += 1
	var type_key = _gml_asset_type_key(asset_type)
	var entry = {
		"id": asset_id,
		"name": str(asset_name),
		"kind": type_key,
		"type": type_key,
		"type_name": gml_asset_get_type_name(type_key),
		"source_path": "",
		"godot_path": str(godot_resource) if is_string(godot_resource) else "",
		"legacy_id": "dynamic:" + str(asset_id),
		"tags": _gml_asset_tag_array(tags),
		"dynamic": true,
		"metadata": {},
		"resource": godot_resource
	}
	_gml_asset_add_entry(entry)
	_gml_asset_dynamic_ids[asset_id] = true
	return asset_id


static func gml_asset_release(asset):
	_gml_asset_registry_ensure_loaded()
	var entry = _gml_asset_resolve(asset)
	if entry == null:
		return false
	var asset_id = int(entry["id"])
	if not _gml_asset_dynamic_ids.has(asset_id):
		return false
	_gml_asset_remove_entry(entry)
	return true


static func _gml_asset_registry_ensure_loaded():
	if _gml_asset_registry_loaded:
		return
	_gml_asset_registry_loaded = true
	if not ResourceLoader.exists(GML_ASSET_REGISTRY_PATH):
		return
	var registry_script = load(GML_ASSET_REGISTRY_PATH)
	if registry_script == null:
		return
	if registry_script.has_method("gml_asset_registry_entries"):
		gml_asset_registry_set(registry_script.gml_asset_registry_entries())
	if registry_script.has_method("gml_texture_group_registry_entries"):
		gml_texture_group_registry_set(registry_script.gml_texture_group_registry_entries())
	if registry_script.has_method("gml_audio_group_registry_entries"):
		gml_audio_group_registry_set(registry_script.gml_audio_group_registry_entries())


static func _gml_asset_add_entry(entry):
	if typeof(entry) != TYPE_DICTIONARY:
		return
	if not entry.has("id") or not entry.has("name") or not entry.has("type"):
		return
	var asset_id = int(entry["id"])
	var asset_name = str(entry["name"])
	var type_key = _gml_asset_type_key(entry["type"])
	var type_name = str(entry["type_name"]) if entry.has("type_name") else ""
	if type_name == "":
		type_name = GML_ASSET_TYPE_NAMES[type_key] if GML_ASSET_TYPE_NAMES.has(type_key) else type_key
	var legacy_id = str(entry["legacy_id"]) if entry.has("legacy_id") and str(entry["legacy_id"]) != "" else str(asset_id)
	var normalized_entry = {
		"id": asset_id,
		"name": asset_name,
		"kind": str(entry["kind"]) if entry.has("kind") else type_key,
		"type": type_key,
		"type_name": type_name,
		"source_path": str(entry["source_path"]) if entry.has("source_path") else "",
		"godot_path": str(entry["godot_path"]) if entry.has("godot_path") else "",
		"legacy_id": legacy_id,
		"tags": entry["tags"] if entry.has("tags") else [],
		"dynamic": bool(entry["dynamic"]) if entry.has("dynamic") else false,
		"metadata": entry["metadata"] if entry.has("metadata") and typeof(entry["metadata"]) == TYPE_DICTIONARY else {}
	}
	if entry.has("resource"):
		normalized_entry["resource"] = entry["resource"]
	_gml_asset_entries.append(normalized_entry)
	_gml_asset_by_id[asset_id] = normalized_entry
	_gml_asset_by_name[asset_name] = normalized_entry
	_gml_asset_by_legacy_id[legacy_id] = normalized_entry
	if not _gml_asset_ids_by_type.has(type_key):
		_gml_asset_ids_by_type[type_key] = []
	_gml_asset_ids_by_type[type_key].append(asset_id)


static func _gml_asset_remove_entry(entry):
	var asset_id = int(entry["id"])
	var asset_name = str(entry["name"])
	var type_key = _gml_asset_type_key(entry["type"])
	_gml_asset_entries.erase(entry)
	_gml_asset_by_id.erase(asset_id)
	_gml_asset_by_name.erase(asset_name)
	if entry.has("legacy_id"):
		_gml_asset_by_legacy_id.erase(str(entry["legacy_id"]))
	if _gml_asset_ids_by_type.has(type_key):
		_gml_asset_ids_by_type[type_key].erase(asset_id)
	_gml_asset_dynamic_ids.erase(asset_id)


static func _gml_asset_resolve(asset):
	if typeof(asset) == TYPE_DICTIONARY and asset.has("id"):
		return asset
	if is_string(asset):
		var key = str(asset)
		if _gml_asset_by_name.has(key):
			return _gml_asset_by_name[key]
		if _gml_asset_by_legacy_id.has(key):
			return _gml_asset_by_legacy_id[key]
	if is_numeric(asset):
		var asset_id = _to_int64_value(asset)
		if _gml_asset_by_id.has(asset_id):
			return _gml_asset_by_id[asset_id]
	return null


static func _gml_asset_type_key(asset_type):
	var key = str(asset_type)
	if GML_ASSET_TYPE_ALIASES.has(key):
		return GML_ASSET_TYPE_ALIASES[key]
	return key


static func _gml_texture_group_registry_entry(groupname):
	_gml_asset_registry_ensure_loaded()
	var group = str(groupname)
	if _gml_texture_group_entries.has(group):
		return _gml_texture_group_entries[group]
	return null


static func _gml_texture_group_registry_names():
	_gml_asset_registry_ensure_loaded()
	var names = _gml_texture_group_entries.keys()
	names.sort()
	return names


static func _gml_audio_group_registry_entry(groupname):
	_gml_asset_registry_ensure_loaded()
	var group = str(groupname)
	if _gml_audio_group_entries.has(group):
		return _gml_audio_group_entries[group]
	return null


static func _gml_audio_group_registry_names():
	_gml_asset_registry_ensure_loaded()
	var names = _gml_audio_group_entries.keys()
	names.sort()
	return names


static func _gml_asset_tag_array(tags):
	if is_string(tags):
		return [str(tags)]
	if typeof(tags) != TYPE_ARRAY:
		return []
	var tag_values = []
	for tag in tags:
		tag_values.append(str(tag))
	return tag_values
