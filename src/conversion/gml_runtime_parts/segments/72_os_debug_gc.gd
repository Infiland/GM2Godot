const GML_OS_WINDOWS = "windows"
const GML_OS_GXGAMES = "gxgames"
const GML_OS_LINUX = "linux"
const GML_OS_MACOSX = "macosx"
const GML_OS_IOS = "ios"
const GML_OS_TVOS = "tvos"
const GML_OS_ANDROID = "android"
const GML_OS_PS4 = "ps4"
const GML_OS_PS5 = "ps5"
const GML_OS_GDK = "gdk"
const GML_OS_SWITCH = "switch"
const GML_OS_UNKNOWN = "unknown"
const GML_BROWSER_NOT_A_BROWSER = "not_a_browser"
const GML_DEVICE_IOS_UNKNOWN = "ios_unknown"
const GML_WEAK_REF_MARKER = "__gm2godot_weak_ref"

static var _gml_gc_enabled = true
static var _gml_gc_target_frame_time = 100.0
static var _gml_gc_frame = 0
static var _gml_unhandled_exception_handler = null


static func gml_os_type():
	var os_name = OS.get_name()
	if os_name == "Windows":
		return GML_OS_WINDOWS
	if os_name == "macOS":
		return GML_OS_MACOSX
	if os_name == "Linux" or os_name == "FreeBSD" or os_name == "NetBSD" or os_name == "OpenBSD" or os_name == "BSD":
		return GML_OS_LINUX
	if os_name == "Android":
		return GML_OS_ANDROID
	if os_name == "iOS":
		return GML_OS_IOS
	if os_name == "Web":
		return GML_OS_GXGAMES
	return GML_OS_UNKNOWN


static func gml_os_browser():
	return GML_BROWSER_NOT_A_BROWSER if not OS.has_feature("web") else "unknown"


static func gml_os_device():
	return GML_DEVICE_IOS_UNKNOWN


static func gml_os_version():
	return _gml_os_version_code(OS.get_version())


static func gml_os_is_paused():
	return false


static func gml_os_is_network_connected(attempt_connection = 0):
	return true


static func gml_os_get_config():
	var config = ProjectSettings.get_setting("application/config/gm2godot_configuration", "")
	return str(config)


static func gml_os_get_language():
	var locale = TranslationServer.get_locale()
	if locale.length() < 2:
		return ""
	return locale.substr(0, 2).to_lower()


static func gml_os_get_region():
	var locale = TranslationServer.get_locale()
	var separator = locale.find("_")
	if separator < 0:
		separator = locale.find("-")
	if separator < 0 or separator + 1 >= locale.length():
		return ""
	return locale.substr(separator + 1, 2).to_upper()


static func gml_os_get_info():
	return gml_struct({
		"os_name": OS.get_name(),
		"os_type": gml_os_type(),
		"version_string": OS.get_version(),
		"is64bit": true,
		"processor_count": OS.get_processor_count(),
		"locale": TranslationServer.get_locale(),
		"godot_version": Engine.get_version_info()
	})


static func gml_environment_get_variable(name):
	return OS.get_environment(str(name))


static func gml_parameter_count():
	return max(OS.get_cmdline_args().size() - 1, 0)


static func gml_parameter_string(index):
	var args = OS.get_cmdline_args()
	var resolved_index = int(_to_real(index))
	if resolved_index < 0 or resolved_index >= args.size():
		return ""
	return str(args[resolved_index])


static func gml_code_is_compiled():
	return not OS.has_feature("editor")


static func gml_debug_get_callstack(maxdepth = -1):
	var frames = []
	var depth = int(_to_real(maxdepth))
	for frame in get_stack():
		if depth >= 0 and frames.size() >= depth:
			break
		var source = str(frame.get("source", ""))
		var line = int(frame.get("line", 0))
		frames.append(source + ":" + str(line))
	frames.append(0)
	return frames


static func gml_exception_unhandled_handler(user_handler):
	var previous = gml_undefined() if _gml_unhandled_exception_handler == null else _gml_unhandled_exception_handler
	_gml_unhandled_exception_handler = gml_undefined() if is_undefined(user_handler) else user_handler
	return previous


static func gml_show_debug_message_ext(value_or_format, values_array):
	var message = gml_string(value_or_format)
	if is_array(values_array):
		for index in range(values_array.size()):
			message = message.replace("{" + str(index) + "}", gml_string(values_array[index]))
	print(message)
	return null


static func gml_show_message(message):
	print(gml_string(message))
	return null


static func gml_show_error(message, abort):
	push_error(gml_string(message))
	if gml_bool(abort):
		push_warning("GM2Godot show_error abort requests are reported but do not terminate the SceneTree automatically.")
	return null


static func gml_gc_enable(enable):
	_gml_gc_enabled = gml_bool(enable)
	return null


static func gml_gc_is_enabled():
	return _gml_gc_enabled


static func gml_gc_collect():
	_gml_gc_frame += 1
	return null


static func gml_gc_target_frame_time(time):
	_gml_gc_target_frame_time = float(_to_real(time))
	return null


static func gml_gc_get_target_frame_time():
	return _gml_gc_target_frame_time


static func gml_gc_get_stats():
	return gml_struct({
		"objects_touched": 0,
		"objects_collected": 0,
		"traversal_time": 0,
		"collection_time": 0,
		"gc_frame": _gml_gc_frame,
		"generation_collected": 0,
		"num_generations": 1,
		"num_objects_in_generation": [0]
	})


static func gml_weak_ref_create(value):
	var weak_data = gml_struct({
		GML_WEAK_REF_MARKER: true,
		"ref": value
	})
	if value is Object:
		weak_data["_weak"] = weakref(value)
	return weak_data


static func gml_weak_ref_alive(weak_ref):
	if not _gml_is_weak_ref(weak_ref):
		return gml_undefined()
	if weak_ref.has("_weak"):
		var object_ref = weak_ref["_weak"].get_ref()
		weak_ref["ref"] = object_ref if object_ref != null else gml_undefined()
		return object_ref != null
	return not is_undefined(weak_ref.get("ref", gml_undefined()))


static func gml_weak_ref_any_alive(values, index = 0, length = -1):
	if not is_array(values):
		return gml_undefined()
	var start = clampi(int(_to_real(index)), 0, values.size())
	var count = int(_to_real(length))
	var end = values.size() if count < 0 else min(start + count, values.size())
	for i in range(start, end):
		var alive = gml_weak_ref_alive(values[i])
		if is_undefined(alive):
			return gml_undefined()
		if alive:
			return true
	return false


static func _gml_is_weak_ref(value):
	return typeof(value) == TYPE_DICTIONARY and value.has(GML_WEAK_REF_MARKER)


static func _gml_os_version_code(version_text):
	var parts = str(version_text).split(".")
	if parts.size() < 2:
		return 0
	var major = int(parts[0])
	var minor = int(parts[1])
	if gml_os_type() == GML_OS_WINDOWS:
		return major * 65536 + minor
	return major * 16777216 + minor * 4096
