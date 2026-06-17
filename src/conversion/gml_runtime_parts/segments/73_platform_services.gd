static var _gml_platform_service_hooks = {}
static var _gml_extension_async_schemas = {}
static var _gml_platform_service_async_defaults = {
	"steam": {"kind": "steam", "handler": "_on_async_steam"},
	"iap": {"kind": "in_app_purchase", "handler": "_on_async_in_app_purchase"},
	"cloud": {"kind": "cloud_save", "handler": "_on_async_cloud_save"},
	"xboxlive": {"kind": "social", "handler": "_on_async_social"},
	"push_notifications": {"kind": "push_notification", "handler": "_on_async_push_notification"},
	"wallpaper": {"kind": "wallpaper_subscription_data", "handler": "_on_wallpaper_subscription_data"}
}
static var _gml_platform_service_contracts = {
	"steam": {
		"steam_is_initialized": {"args": [], "result": "bool", "async_kind": "steam", "handler": "_on_async_steam"},
		"steam_set_achievement": {"args": ["achievement_name"], "result": "bool_or_request_id", "async_kind": "steam", "handler": "_on_async_steam"},
		"steam_get_achievement": {"args": ["achievement_name"], "result": "bool_or_request_id", "async_kind": "steam", "handler": "_on_async_steam"},
		"steam_upload_score": {"args": ["leaderboard_name", "score"], "result": "request_id", "async_kind": "steam", "handler": "_on_async_steam"},
		"steam_download_scores": {"args": ["leaderboard_name", "start", "end"], "result": "request_id", "async_kind": "steam", "handler": "_on_async_steam"}
	},
	"iap": {
		"iap_activate": {"args": [], "result": "request_id_or_status", "async_kind": "in_app_purchase", "handler": "_on_async_in_app_purchase"},
		"iap_acquire": {"args": ["product_id", "payload"], "result": "request_id", "async_kind": "in_app_purchase", "handler": "_on_async_in_app_purchase"},
		"iap_consume": {"args": ["product_id"], "result": "request_id", "async_kind": "in_app_purchase", "handler": "_on_async_in_app_purchase"},
		"iap_restore_all": {"args": [], "result": "request_id", "async_kind": "in_app_purchase", "handler": "_on_async_in_app_purchase"}
	},
	"cloud": {
		"cloud_synchronise": {"args": [], "result": "request_id", "async_kind": "cloud_save", "handler": "_on_async_cloud_save"},
		"cloud_string_save": {"args": ["data", "description"], "result": "request_id", "async_kind": "cloud_save", "handler": "_on_async_cloud_save"},
		"cloud_file_save": {"args": ["path", "description"], "result": "request_id", "async_kind": "cloud_save", "handler": "_on_async_cloud_save"}
	},
	"xboxlive": {
		"xboxlive_achievements_set_progress": {"args": ["user_id", "achievement", "progress"], "result": "request_id_or_null", "async_kind": "social", "handler": "_on_async_social"},
		"xboxlive_stats_get_leaderboard": {"args": ["leaderboard_name"], "result": "request_id", "async_kind": "social", "handler": "_on_async_social"},
		"xboxlive_read_player_leaderboard": {"args": ["leaderboard_name", "user_id", "num_items", "friend_filter"], "result": "request_id", "async_kind": "social", "handler": "_on_async_social"},
		"xboxlive_matchmaking_create": {"args": [], "result": "request_id", "async_kind": "social", "handler": "_on_async_social"}
	},
	"push_notifications": {
		"push_notifications_extension": {"args": ["payload"], "result": "request_id", "async_kind": "push_notification", "handler": "_on_async_push_notification"}
	},
	"wallpaper": {
		"wallpaper_set_config": {"args": ["settings_array"], "result": "request_id_or_null", "async_kind": "wallpaper_config", "handler": "_on_wallpaper_config"},
		"wallpaper_set_subscriptions": {"args": ["subscriptions"], "result": "request_id_or_null", "async_kind": "wallpaper_subscription_data", "handler": "_on_wallpaper_subscription_data"}
	}
}


static func gml_platform_service_register(service_name, hook):
	var key = str(service_name)
	if is_undefined(hook) or hook == null:
		_gml_platform_service_hooks.erase(key)
	else:
		_gml_platform_service_hooks[key] = hook
	return null


static func gml_platform_service_is_available(service_name):
	return _gml_platform_service_hooks.has(str(service_name))


static func gml_platform_service_contracts():
	return _gml_clone_value(_gml_platform_service_contracts, 16)


static func gml_platform_service_contract(service_name, api_name):
	var contract = _gml_platform_service_contract(str(service_name), str(api_name))
	if contract.is_empty():
		return {}
	return _gml_clone_value(contract, 8)


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
			return _gml_platform_service_process_result(str(service_name), method_name, callback.callv(args))
	if hook is Object and hook.has_method(method_name):
		return _gml_platform_service_process_result(str(service_name), method_name, hook.callv(method_name, args))
	return gml_platform_service_unsupported(api_name, service_name)


static func gml_platform_service_unsupported(api_name, service_name, detail = ""):
	var contract = _gml_platform_service_contract(str(service_name), str(api_name))
	var message = (
		"GML platform-service API "
		+ str(api_name)
		+ " requires an optional "
		+ str(service_name)
		+ " addon/plugin or closed platform SDK integration."
	)
	if str(detail) != "":
		message += " " + str(detail)
	var async_kind = str(contract.get("async_kind", ""))
	if async_kind != "":
		gml_async_dispatch_unsupported(
			async_kind,
			api_name,
			service_name,
			str(contract.get("handler", "")),
			message,
		)
	return gml_error(message)


static func _gml_platform_service_try_call(service_name, api_name, args, fallback):
	if gml_platform_service_has_api(service_name, api_name):
		return gml_platform_service_call(service_name, api_name, args)
	return fallback


static func _gml_platform_service_required_call(service_name, api_name, args):
	return gml_platform_service_call(service_name, api_name, args)


static func gml_platform_service_dispatch_async(service_name, payload, kind = "", handler_name = ""):
	var defaults = _gml_platform_service_async_defaults.get(str(service_name), {})
	var resolved_kind = str(kind)
	if resolved_kind == "":
		resolved_kind = str(defaults.get("kind", str(service_name)))
	var resolved_handler = str(handler_name)
	if resolved_handler == "":
		resolved_handler = str(defaults.get("handler", "_on_async_" + str(service_name)))
	var resolved_payload = payload if payload is Dictionary else {}
	return gml_async_dispatch(resolved_kind, resolved_payload, resolved_handler)


static func gml_extension_async_schema_register(extension_name, callback_name, schema):
	var extension_key = str(extension_name)
	var callback_key = str(callback_name)
	if is_undefined(schema) or schema == null:
		var existing_callbacks = _gml_extension_async_schemas.get(extension_key, {})
		if typeof(existing_callbacks) == TYPE_DICTIONARY:
			existing_callbacks.erase(callback_key)
			if existing_callbacks.is_empty():
				_gml_extension_async_schemas.erase(extension_key)
		return null
	if not _gml_extension_async_schemas.has(extension_key):
		_gml_extension_async_schemas[extension_key] = {}
	_gml_extension_async_schemas[extension_key][callback_key] = schema if schema is Dictionary else {"schema": schema}
	return null


static func gml_extension_async_schema(extension_name, callback_name):
	var callbacks = _gml_extension_async_schemas.get(str(extension_name), {})
	if typeof(callbacks) != TYPE_DICTIONARY:
		return {}
	var schema = callbacks.get(str(callback_name), {})
	if typeof(schema) != TYPE_DICTIONARY:
		return {}
	return _gml_clone_value(schema, 8)


static func gml_extension_async_dispatch(extension_name, callback_name, payload):
	var extension_key = str(extension_name)
	var callback_key = str(callback_name)
	var schema = gml_extension_async_schema(extension_key, callback_key)
	var resolved_kind = str(schema.get("kind", schema.get("async_kind", "extension")))
	if resolved_kind == "":
		resolved_kind = "extension"
	var resolved_handler = str(schema.get("handler", schema.get("handler_name", "")))
	if resolved_handler == "":
		resolved_handler = "_on_async_extension" if callback_key == "" else "_on_async_" + callback_key
	var resolved_payload = payload if payload is Dictionary else {}
	resolved_payload["extension"] = extension_key
	resolved_payload["callback"] = callback_key
	resolved_payload["schema"] = schema
	return gml_platform_service_dispatch_async(extension_key, resolved_payload, resolved_kind, resolved_handler)


static func _gml_platform_service_process_result(service_name, api_name, result):
	if typeof(result) != TYPE_DICTIONARY:
		return result
	var async_payload = result.get("async_payload", result.get("async", null))
	if typeof(async_payload) != TYPE_DICTIONARY:
		return result
	var contract = _gml_platform_service_contract(service_name, api_name)
	var event_kind = str(result.get("async_kind", contract.get("async_kind", "")))
	var handler_name = str(result.get("handler", contract.get("handler", "")))
	var dispatch_id = gml_platform_service_dispatch_async(service_name, async_payload, event_kind, handler_name)
	if result.has("result"):
		return result["result"]
	if result.has("return_value"):
		return result["return_value"]
	return dispatch_id


static func _gml_platform_service_contract(service_name, api_name):
	var service_contracts = _gml_platform_service_contracts.get(str(service_name), {})
	if typeof(service_contracts) != TYPE_DICTIONARY:
		return {}
	var contract = service_contracts.get(str(api_name), {})
	if typeof(contract) != TYPE_DICTIONARY:
		return {}
	return contract


static func gml_steam_is_initialized():
	return gml_bool(_gml_platform_service_try_call("steam", "steam_is_initialized", [], false))


static func gml_admob_extension_call(api_name, args = []):
	var api = str(api_name)
	var resolved_args = args if typeof(args) == TYPE_ARRAY else []
	if gml_platform_service_has_api("admob", api):
		return gml_platform_service_call("admob", api, resolved_args)
	if api.ends_with("_IsLoaded") or api.ends_with("_IsFormAvailable") or api.ends_with("_IsEnabled"):
		return false
	if api.ends_with("_GetWidth") or api.ends_with("_GetHeight") or api.ends_with("_GetStatus") or api.ends_with("_GetType") or api.ends_with("_Instances_Count"):
		return 0
	if api.ends_with("_Create") or api.ends_with("_Load") or api.ends_with("_Show") or api.ends_with("_Hide") or api.ends_with("_Remove") or api.ends_with("_Initialize"):
		return 0
	return null


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
