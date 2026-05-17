static var _gml_async_next_request_id_value = 1
static var _gml_async_event_log = []
static var _gml_async_pending_http = {}


static func gml_async_next_request_id():
	var request_id = _gml_async_next_request_id_value
	_gml_async_next_request_id_value += 1
	return request_id


static func gml_async_dispatch(kind, payload, handler_name):
	var resolved_payload = payload if payload is Dictionary else {}
	if not resolved_payload.has("id"):
		resolved_payload["id"] = gml_async_next_request_id()
	resolved_payload["event_type"] = str(kind)
	_gml_builtin_globals["async_load"] = resolved_payload
	_gml_async_event_log.append({
		"kind": str(kind),
		"handler": str(handler_name),
		"payload": resolved_payload
	})
	var main_loop = Engine.get_main_loop()
	if main_loop is SceneTree:
		_gml_async_dispatch_node(main_loop.root, str(handler_name))
	return resolved_payload["id"]


static func gml_async_event_log():
	return _gml_clone_value(_gml_async_event_log, 16)


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
	gml_async_dispatch("http", {
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


static func _gml_async_dispatch_node(node, handler_name):
	if node == null:
		return
	if node.has_method(handler_name):
		node.call(handler_name)
	for child in node.get_children():
		_gml_async_dispatch_node(child, handler_name)


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
