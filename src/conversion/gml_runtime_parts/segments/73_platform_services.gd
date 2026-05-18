static var _gml_platform_service_hooks = {}


static func gml_platform_service_register(service_name, hook):
	var key = str(service_name)
	if is_undefined(hook) or hook == null:
		_gml_platform_service_hooks.erase(key)
	else:
		_gml_platform_service_hooks[key] = hook
	return null


static func gml_platform_service_is_available(service_name):
	return _gml_platform_service_hooks.has(str(service_name))


static func gml_platform_service_has_api(service_name, api_name):
	var hook = _gml_platform_service_hooks.get(str(service_name), null)
	if hook == null:
		return false
	var method_name = str(api_name)
	if typeof(hook) == TYPE_DICTIONARY:
		return typeof(hook.get(method_name, null)) == TYPE_CALLABLE
	return hook is Object and hook.has_method(method_name)


static func gml_platform_service_call(service_name, api_name, args = []):
	var hook = _gml_platform_service_hooks.get(str(service_name), null)
	if hook == null:
		return gml_platform_service_unsupported(api_name, service_name)
	var method_name = str(api_name)
	if typeof(hook) == TYPE_DICTIONARY:
		var callback = hook.get(method_name, null)
		if typeof(callback) == TYPE_CALLABLE:
			return callback.callv(args)
	if hook is Object and hook.has_method(method_name):
		return hook.callv(method_name, args)
	return gml_platform_service_unsupported(api_name, service_name)


static func gml_platform_service_unsupported(api_name, service_name, detail = ""):
	var message = (
		"GML platform-service API "
		+ str(api_name)
		+ " requires an optional "
		+ str(service_name)
		+ " addon/plugin or closed platform SDK integration."
	)
	if str(detail) != "":
		message += " " + str(detail)
	return gml_error(message)


static func _gml_platform_service_try_call(service_name, api_name, args, fallback):
	if gml_platform_service_has_api(service_name, api_name):
		return gml_platform_service_call(service_name, api_name, args)
	return fallback


static func _gml_platform_service_required_call(service_name, api_name, args):
	return gml_platform_service_call(service_name, api_name, args)


static func gml_steam_is_initialized():
	return gml_bool(_gml_platform_service_try_call("steam", "steam_is_initialized", [], false))


static func gml_browser_width():
	return _gml_platform_service_try_call("web", "browser_width", [], DisplayServer.window_get_size().x)


static func gml_browser_height():
	return _gml_platform_service_try_call("web", "browser_height", [], DisplayServer.window_get_size().y)


static func gml_browser_input_capture(enable):
	return _gml_platform_service_try_call("web", "browser_input_capture", [enable], null)


static func gml_webgl_enabled():
	return gml_bool(_gml_platform_service_try_call("web", "webgl_enabled", [], true))


static func gml_url_get_domain(url = ""):
	if gml_platform_service_has_api("web", "url_get_domain"):
		return gml_platform_service_call("web", "url_get_domain", [])
	var text = str(url)
	if text == "":
		return ""
	var scheme_index = text.find("://")
	if scheme_index >= 0:
		text = text.substr(scheme_index + 3)
	var slash_index = text.find("/")
	if slash_index >= 0:
		text = text.substr(0, slash_index)
	var at_index = text.rfind("@")
	if at_index >= 0:
		text = text.substr(at_index + 1)
	var colon_index = text.find(":")
	if colon_index >= 0:
		text = text.substr(0, colon_index)
	return text


static func gml_url_open(url):
	if gml_platform_service_has_api("web", "url_open"):
		return gml_platform_service_call("web", "url_open", [url])
	var error = OS.shell_open(str(url))
	if error != OK:
		push_warning("GM2Godot url_open failed for " + str(url) + " with error " + str(error))
	return null


static func gml_url_open_ext(url, target):
	if gml_platform_service_has_api("web", "url_open_ext"):
		return gml_platform_service_call("web", "url_open_ext", [url, target])
	return gml_url_open(url)


static func gml_url_open_full(url, target, options):
	if gml_platform_service_has_api("web", "url_open_full"):
		return gml_platform_service_call("web", "url_open_full", [url, target, options])
	return gml_url_open(url)


static func gml_xboxlive_user_is_signed_in():
	return gml_bool(_gml_platform_service_try_call("xboxlive", "xboxlive_user_is_signed_in", [], false))


static func gml_xboxlive_user_is_signing_in():
	return gml_bool(_gml_platform_service_try_call("xboxlive", "xboxlive_user_is_signing_in", [], false))


static func gml_xboxlive_gamertag_for_user():
	return _gml_platform_service_try_call("xboxlive", "xboxlive_gamertag_for_user", [], "")


static func gml_xboxlive_show_account_picker():
	return _gml_platform_service_required_call("xboxlive", "xboxlive_show_account_picker", [])


static func gml_wallpaper_set_config(settings_array):
	return _gml_platform_service_required_call("wallpaper", "wallpaper_set_config", [settings_array])


static func gml_wallpaper_set_subscriptions(subscriptions):
	return _gml_platform_service_required_call("wallpaper", "wallpaper_set_subscriptions", [subscriptions])


static func gml_cloud_synchronise():
	return _gml_platform_service_required_call("cloud", "cloud_synchronise", [])


static func gml_cloud_string_save(data, description):
	return _gml_platform_service_required_call("cloud", "cloud_string_save", [data, description])


static func gml_cloud_file_save(path, description):
	return _gml_platform_service_required_call("cloud", "cloud_file_save", [path, description])
