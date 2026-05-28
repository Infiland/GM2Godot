static var _gml_async_next_request_id_value = 1
static var _gml_async_event_log = []
static var _gml_async_queue = []
static var _gml_async_next_queue_sequence = 1
static var _gml_async_dispatch_sequence = 0
static var _gml_async_active_depth = 0
static var _gml_async_flush_scheduled = false
static var _gml_async_unsupported_diagnostics = []
static var _gml_async_pending_http = {}

const GML_ASYNC_HANDLER_DEFAULTS = {
	"http": "_on_async_http",
	"networking": "_on_async_networking",
	"dialog": "_on_async_dialog",
	"image_loaded": "_on_async_image_loaded",
	"sound_loaded": "_on_async_sound_loaded",
	"save_load": "_on_async_save_load",
	"steam": "_on_async_steam",
	"in_app_purchase": "_on_async_in_app_purchase",
	"cloud_save": "_on_async_cloud_save",
	"social": "_on_async_social",
	"push_notification": "_on_async_push_notification",
	"system": "_on_async_system",
	"audio_recording": "_on_audio_recording_async",
	"audio_playback": "_on_audio_playback_async",
	"audio_playback_ended": "_on_audio_playback_ended_async",
	"extension": "_on_async_extension",
}

const GML_ASYNC_HANDLER_ALIASES = {
	"http": ["_on_http_request_completed"],
}

const GML_ASYNC_PAYLOAD_SCHEMAS = {
	"default": {
		"required": ["id", "event_type"],
		"optional": ["status", "result", "diagnostic"],
		"lifetime": "async_load is set only while a matching Async event callback is running and is cleared before dispatch returns.",
	},
	"http": {
		"required": ["id", "event_type", "status", "result", "url"],
		"optional": ["http_status", "body", "body_raw", "headers", "response_headers", "network_result", "diagnostic"],
		"handler": "_on_async_http",
	},
	"networking": {
		"required": ["id", "event_type", "type", "socket", "protocol"],
		"optional": ["message_type", "network_type", "buffer", "size", "ip", "port", "status", "diagnostic"],
		"handler": "_on_async_networking",
	},
	"dialog": {
		"required": ["id", "event_type", "status"],
		"optional": ["result", "button", "value", "diagnostic"],
		"handler": "_on_async_dialog",
	},
	"save_load": {
		"required": ["id", "event_type", "status", "filename"],
		"optional": ["buffer", "result", "diagnostic"],
		"handler": "_on_async_save_load",
	},
	"image_loaded": {
		"required": ["id", "event_type", "status"],
		"optional": ["filename", "asset_index", "sprite_index", "diagnostic"],
		"handler": "_on_async_image_loaded",
	},
	"sound_loaded": {
		"required": ["id", "event_type", "status"],
		"optional": ["filename", "asset_index", "sound_index", "diagnostic"],
		"handler": "_on_async_sound_loaded",
	},
	"audio_recording": {
		"required": ["id", "event_type", "status"],
		"optional": ["buffer", "channel", "diagnostic"],
		"handler": "_on_audio_recording_async",
	},
	"audio_playback": {
		"required": ["id", "event_type", "status"],
		"optional": ["queue_id", "sound_id", "diagnostic"],
		"handler": "_on_audio_playback_async",
	},
	"audio_playback_ended": {
		"required": ["id", "event_type", "status"],
		"optional": ["queue_id", "sound_id", "diagnostic"],
		"handler": "_on_audio_playback_ended_async",
	},
	"steam": {
		"required": ["id", "event_type", "status"],
		"optional": ["result", "diagnostic"],
		"handler": "_on_async_steam",
	},
	"in_app_purchase": {
		"required": ["id", "event_type", "status"],
		"optional": ["product_id", "result", "diagnostic"],
		"handler": "_on_async_in_app_purchase",
	},
	"cloud_save": {
		"required": ["id", "event_type", "status"],
		"optional": ["filename", "result", "diagnostic"],
		"handler": "_on_async_cloud_save",
	},
	"social": {
		"required": ["id", "event_type", "status"],
		"optional": ["result", "diagnostic"],
		"handler": "_on_async_social",
	},
	"push_notification": {
		"required": ["id", "event_type"],
		"optional": ["message", "payload", "status", "diagnostic"],
		"handler": "_on_async_push_notification",
	},
	"system": {
		"required": ["id", "event_type", "status"],
		"optional": ["result", "diagnostic"],
		"handler": "_on_async_system",
	},
	"extension": {
		"required": ["id", "event_type", "extension", "callback"],
		"optional": ["schema", "status", "result", "diagnostic"],
		"handler": "_on_async_extension",
	},
}


static func gml_async_next_request_id():
	var request_id = _gml_async_next_request_id_value
	_gml_async_next_request_id_value += 1
	return request_id


static func gml_async_dispatch(kind, payload, handler_name = ""):
	var request_id = _gml_async_enqueue(kind, payload, handler_name, false)
	if _gml_async_active_depth == 0:
		gml_async_queue_flush()
	else:
		_gml_async_schedule_flush()
	return request_id


static func gml_async_enqueue(kind, payload, handler_name = ""):
	return _gml_async_enqueue(kind, payload, handler_name, true)


static func gml_async_enqueue_from_signal(kind, payload, handler_name = ""):
	return _gml_async_enqueue(kind, payload, handler_name, true)


static func gml_async_queue_flush(max_events = -1):
	var limit = _to_int64_value(max_events)
	var dispatched = 0
	_gml_async_flush_scheduled = false
	while not _gml_async_queue.is_empty():
		if limit >= 0 and dispatched >= limit:
			break
		var event = _gml_async_queue.pop_front()
		_gml_async_deliver(event)
		dispatched += 1
	return dispatched


static func gml_async_queue_size():
	return _gml_async_queue.size()


static func gml_async_queue_snapshot():
	return _gml_clone_value(_gml_async_queue, 16)


static func gml_async_event_log():
	return _gml_clone_value(_gml_async_event_log, 16)


static func gml_async_event_log_clear():
	_gml_async_event_log.clear()
	return null


static func gml_async_payload_schema(kind = ""):
	var key = str(kind)
	if key == "":
		return _gml_clone_value(GML_ASYNC_PAYLOAD_SCHEMAS, 16)
	return _gml_clone_value(GML_ASYNC_PAYLOAD_SCHEMAS.get(key, GML_ASYNC_PAYLOAD_SCHEMAS["default"]), 16)


static func gml_async_unsupported_diagnostics():
	return _gml_clone_value(_gml_async_unsupported_diagnostics, 16)


static func gml_async_dispatch_unsupported(kind, api_name, service_name = "", handler_name = "", detail = ""):
	var resolved_kind = str(kind)
	if resolved_kind == "":
		resolved_kind = "system"
	var message = "Unsupported async API: " + str(api_name)
	if str(service_name) != "":
		message += " for service " + str(service_name)
	if str(detail) != "":
		message += ". " + str(detail)
	var diagnostic = {
		"severity": "unsupported",
		"api": str(api_name),
		"service": str(service_name),
		"event_type": resolved_kind,
		"message": message,
		"detail": str(detail),
	}
	_gml_async_unsupported_diagnostics.append(diagnostic)
	return gml_async_dispatch(resolved_kind, {
		"id": gml_async_next_request_id(),
		"status": -1,
		"result": "unsupported",
		"diagnostic": diagnostic,
	}, handler_name)


static func gml_http_get(url):
	return _gml_http_request(str(url), "GET", [], "")


static func gml_http_post_string(url, data):
	return _gml_http_request(str(url), "POST", ["Content-Type: application/x-www-form-urlencoded"], gml_string(data))


static func gml_http_request(url, method, headers, body):
	return _gml_http_request(str(url), str(method), headers, gml_string(body))


static func _gml_http_request(url, method, headers, body):
	var request_id = gml_async_next_request_id()
	var main_loop = Engine.get_main_loop()
	if not (main_loop is SceneTree):
		_gml_http_complete(request_id, url, ERR_UNAVAILABLE, 0, [], PackedByteArray())
		return request_id

	var request_node = HTTPRequest.new()
	request_node.name = "GM2GodotHTTPRequest_" + str(request_id)
	main_loop.root.add_child(request_node)
	_gml_async_pending_http[request_id] = request_node
	request_node.request_completed.connect(func(result, response_code, response_headers, body_bytes):
		_gml_async_pending_http.erase(request_id)
		_gml_http_complete(request_id, url, result, response_code, response_headers, body_bytes)
		if is_instance_valid(request_node):
			request_node.queue_free()
	)
	var err = request_node.request(
		url,
		_gml_http_headers(headers),
		_gml_http_method(method),
		gml_string(body),
	)
	if err != OK:
		_gml_async_pending_http.erase(request_id)
		_gml_http_complete(request_id, url, err, 0, [], PackedByteArray())
		request_node.queue_free()
	return request_id


static func _gml_http_complete(request_id, url, result, response_code, response_headers, body_bytes):
	var body_text = body_bytes.get_string_from_utf8() if body_bytes is PackedByteArray else ""
	gml_async_enqueue_from_signal("http", {
		"id": request_id,
		"status": int(response_code),
		"http_status": int(response_code),
		"result": body_text,
		"body": body_text,
		"body_raw": body_bytes,
		"response_headers": response_headers,
		"headers": response_headers,
		"url": str(url),
		"network_result": int(result),
	}, "_on_async_http")


static func _gml_async_enqueue(kind, payload, handler_name, schedule_flush):
	var resolved_kind = str(kind)
	var resolved_payload = _gml_async_normalize_payload(resolved_kind, payload)
	var request_id = resolved_payload["id"]
	var event = {
		"kind": resolved_kind,
		"handler": _gml_async_resolve_handler(resolved_kind, handler_name),
		"payload": resolved_payload,
		"queue_sequence": _gml_async_next_queue_sequence,
	}
	_gml_async_next_queue_sequence += 1
	_gml_async_queue.append(event)
	if schedule_flush:
		_gml_async_schedule_flush()
	return request_id


static func _gml_async_normalize_payload(kind, payload):
	var resolved_payload = _gml_clone_value(payload, 16) if payload is Dictionary else {}
	if not resolved_payload.has("id"):
		resolved_payload["id"] = gml_async_next_request_id()
	resolved_payload["event_type"] = str(kind)
	return resolved_payload


static func _gml_async_resolve_handler(kind, handler_name):
	var resolved_handler = str(handler_name)
	if resolved_handler != "":
		return resolved_handler
	return str(GML_ASYNC_HANDLER_DEFAULTS.get(str(kind), "_on_async_" + str(kind)))


static func _gml_async_handler_names(kind, handler_name):
	var names = []
	var primary = str(handler_name)
	if primary != "":
		names.append(primary)
	var default_handler = _gml_async_resolve_handler(kind, "")
	if default_handler != "" and not names.has(default_handler):
		names.append(default_handler)
	var aliases = GML_ASYNC_HANDLER_ALIASES.get(str(kind), [])
	if aliases is Array:
		for alias in aliases:
			var alias_name = str(alias)
			if alias_name != "" and not names.has(alias_name):
				names.append(alias_name)
	return names


static func _gml_async_schedule_flush():
	if _gml_async_flush_scheduled or _gml_async_queue.is_empty():
		return
	var main_loop = Engine.get_main_loop()
	if not (main_loop is SceneTree):
		return
	_gml_async_flush_scheduled = true
	main_loop.process_frame.connect(func():
		gml_async_queue_flush()
	, CONNECT_ONE_SHOT)


static func _gml_async_deliver(event):
	_gml_async_dispatch_sequence += 1
	var payload = event.get("payload", {})
	var kind = str(event.get("kind", ""))
	var handler_name = str(event.get("handler", ""))
	var handler_names = _gml_async_handler_names(kind, handler_name)
	var listener_count = 0
	_gml_async_active_depth += 1
	_gml_builtin_globals["async_load"] = payload
	var main_loop = Engine.get_main_loop()
	if main_loop is SceneTree:
		listener_count = _gml_async_dispatch_node(main_loop.root, handler_names)
	_gml_async_active_depth -= 1
	_gml_async_event_log.append({
		"kind": kind,
		"handler": handler_name,
		"handlers": handler_names,
		"payload": _gml_clone_value(payload, 16),
		"queue_sequence": event.get("queue_sequence", 0),
		"dispatch_sequence": _gml_async_dispatch_sequence,
		"listener_count": listener_count,
	})
	if _gml_async_active_depth == 0:
		_gml_builtin_globals["async_load"] = {}
	return listener_count


static func _gml_async_dispatch_node(node, handler_names):
	if node == null:
		return 0
	var count = 0
	for handler_name in handler_names:
		if node.has_method(str(handler_name)):
			node.call(str(handler_name))
			count += 1
			break
	for child in node.get_children():
		count += _gml_async_dispatch_node(child, handler_names)
	return count


static func _gml_http_headers(headers):
	var result = PackedStringArray()
	if headers is PackedStringArray:
		return headers
	if headers is Array:
		for header in headers:
			result.append(str(header))
	elif headers is Dictionary:
		for key in headers.keys():
			result.append(str(key) + ": " + str(headers[key]))
	elif is_handle(headers):
		var map_value = _gml_resolve_ds_map(headers)
		if map_value is Dictionary:
			for key in map_value.keys():
				result.append(str(key) + ": " + str(map_value[key]))
	return result


static func _gml_http_method(method):
	var text = str(method).to_upper()
	if text == "POST":
		return HTTPClient.METHOD_POST
	if text == "PUT":
		return HTTPClient.METHOD_PUT
	if text == "DELETE":
		return HTTPClient.METHOD_DELETE
	if text == "PATCH":
		return HTTPClient.METHOD_PATCH
	if text == "HEAD":
		return HTTPClient.METHOD_HEAD
	return HTTPClient.METHOD_GET
