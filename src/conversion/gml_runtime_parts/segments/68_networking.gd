const GML_NETWORK_HANDLE_KIND = "network_socket"
const GML_NETWORK_SOCKET_TCP = 0
const GML_NETWORK_SOCKET_UDP = 1
const GML_NETWORK_SOCKET_WS = 2
const GML_NETWORK_SOCKET_WSS = 3
const GML_NETWORK_TYPE_CONNECT = 1
const GML_NETWORK_TYPE_DISCONNECT = 2
const GML_NETWORK_TYPE_DATA = 3

static var _gml_network_entries = {}
static var _gml_network_poll_scheduled = false


static func gml_network_create_socket(socket_type):
	var protocol = _gml_network_protocol(socket_type)
	if protocol == "tcp":
		return _gml_network_register({
			"protocol": protocol,
			"role": "client",
			"peer": StreamPeerTCP.new(),
			"connected": false,
			"connecting": false,
			"remote_host": "",
			"remote_port": 0
		})
	if protocol == "udp":
		var peer = PacketPeerUDP.new()
		return _gml_network_register({
			"protocol": protocol,
			"role": "socket",
			"peer": peer,
			"connected": false,
			"connecting": false,
			"remote_host": "",
			"remote_port": 0
		})
	return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)


static func gml_network_create_socket_ext(socket_type, port):
	var handle = gml_network_create_socket(socket_type)
	var entry: Variant = _gml_network_entry(handle)
	if entry == null:
		return handle
	if entry["protocol"] == "udp":
		var err = entry["peer"].bind(max(0, _to_int64_value(port)), "*")
		if err != OK:
			gml_network_destroy(handle)
			return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)
	return handle


static func gml_network_create_server(socket_type, port, max_clients = 32):
	var protocol = _gml_network_protocol(socket_type)
	if protocol == "tcp":
		var server = TCPServer.new()
		var err = server.listen(max(0, _to_int64_value(port)), "*")
		if err != OK:
			return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)
		return _gml_network_register({
			"protocol": protocol,
			"role": "server",
			"server": server,
			"max_clients": max(1, _to_int64_value(max_clients)),
			"connected": true,
			"connecting": false,
			"remote_host": "",
			"remote_port": max(0, _to_int64_value(port))
		})
	if protocol == "udp":
		var peer = PacketPeerUDP.new()
		var err = peer.bind(max(0, _to_int64_value(port)), "*")
		if err != OK:
			return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)
		return _gml_network_register({
			"protocol": protocol,
			"role": "server",
			"peer": peer,
			"connected": true,
			"connecting": false,
			"remote_host": "",
			"remote_port": max(0, _to_int64_value(port))
		})
	return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)


static func gml_network_create_server_raw(socket_type, port, max_clients = 32):
	return gml_network_create_server(socket_type, port, max_clients)


static func gml_network_connect(socket, host, port):
	var entry: Variant = _gml_network_entry(socket)
	if entry == null:
		return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)
	var resolved_host = str(host)
	var resolved_port = max(0, _to_int64_value(port))
	entry["remote_host"] = resolved_host
	entry["remote_port"] = resolved_port
	if entry["protocol"] == "tcp" and entry.has("peer") and entry["peer"] is StreamPeerTCP:
		var err = entry["peer"].connect_to_host(resolved_host, resolved_port)
		if err != OK:
			_gml_network_dispatch(entry, GML_NETWORK_TYPE_DISCONNECT, {
				"status": int(err),
				"ip": resolved_host,
				"port": resolved_port
			})
			return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)
		entry["connecting"] = true
		_gml_network_schedule_poll()
		return entry["handle"]
	if entry["protocol"] == "udp" and entry.has("peer") and entry["peer"] is PacketPeerUDP:
		var err = entry["peer"].set_dest_address(resolved_host, resolved_port)
		if err != OK:
			return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)
		entry["connected"] = true
		_gml_network_dispatch(entry, GML_NETWORK_TYPE_CONNECT, {
			"status": OK,
			"ip": resolved_host,
			"port": resolved_port
		})
		_gml_network_schedule_poll()
		return entry["handle"]
	return gml_handle_invalid(GML_NETWORK_HANDLE_KIND)


static func gml_network_connect_async(socket, host, port):
	return gml_network_connect(socket, host, port)


static func gml_network_connect_raw(socket, host, port):
	return gml_network_connect(socket, host, port)


static func gml_network_connect_raw_async(socket, host, port):
	return gml_network_connect(socket, host, port)


static func gml_network_send_raw(socket, buffer_id, size):
	return _gml_network_send_buffer(socket, buffer_id, size)


static func gml_network_send_packet(socket, buffer_id, size):
	return _gml_network_send_buffer(socket, buffer_id, size)


static func gml_network_send_udp(socket, host, port, buffer_id, size):
	return _gml_network_send_udp(socket, host, port, buffer_id, size)


static func gml_network_send_udp_raw(socket, host, port, buffer_id, size):
	return _gml_network_send_udp(socket, host, port, buffer_id, size)


static func gml_network_send_broadcast(socket, port, buffer_id, size):
	return _gml_network_send_udp(socket, "255.255.255.255", port, buffer_id, size, true)


static func gml_network_destroy(socket):
	var handle = gml_handle_from_value(GML_NETWORK_HANDLE_KIND, socket)
	if not gml_handle_is_valid(handle) or not _gml_network_entries.has(handle.index):
		return false
	var child_handles = []
	var entry: Variant = _gml_network_entries[handle.index]
	if entry.has("role") and str(entry["role"]) == "server":
		for child_index in _gml_network_entries.keys():
			if child_index == handle.index:
				continue
			var child_entry: Variant = _gml_network_entries[child_index]
			if child_entry.has("server_handle") and child_entry["server_handle"] is GMLHandle:
				if child_entry["server_handle"].index == handle.index:
					child_handles.append(child_entry["handle"])
	for child_handle in child_handles:
		gml_network_destroy(child_handle)
	if not _gml_network_entries.has(handle.index):
		return true
	entry = _gml_network_entries[handle.index]
	if entry.has("server") and entry["server"] is TCPServer:
		entry["server"].stop()
	if entry.has("peer"):
		var peer = entry["peer"]
		if peer is StreamPeerTCP:
			peer.disconnect_from_host()
		elif peer is PacketPeerUDP:
			peer.close()
		elif peer is WebSocketPeer:
			peer.close()
	_gml_network_entries.erase(handle.index)
	gml_handle_invalidate(handle)
	return true


static func gml_network_poll():
	var indices = []
	for index in _gml_network_entries.keys():
		indices.append(index)
	for index in indices:
		if not _gml_network_entries.has(index):
			continue
		var entry: Variant = _gml_network_entries[index]
		if entry.has("server") and entry["server"] is TCPServer:
			_gml_network_poll_tcp_server(entry)
		if not _gml_network_entries.has(index):
			continue
		entry = _gml_network_entries[index]
		if entry.has("peer") and entry["peer"] is StreamPeerTCP:
			_gml_network_poll_tcp_peer(entry)
		elif entry.has("peer") and entry["peer"] is PacketPeerUDP:
			_gml_network_poll_udp_peer(entry)
	return null


static func _gml_network_register(entry):
	var handle = gml_handle_register(GML_NETWORK_HANDLE_KIND, entry)
	entry["handle"] = handle
	entry["id"] = handle.value
	_gml_network_entries[handle.index] = entry
	_gml_network_schedule_poll()
	return handle


static func _gml_network_entry(socket):
	var handle = gml_handle_from_value(GML_NETWORK_HANDLE_KIND, socket)
	if gml_handle_is_valid(handle) and _gml_network_entries.has(handle.index):
		return _gml_network_entries[handle.index]
	return null


static func _gml_network_protocol(socket_type):
	var resolved_type = _to_int64_value(socket_type)
	if resolved_type == GML_NETWORK_SOCKET_TCP:
		return "tcp"
	if resolved_type == GML_NETWORK_SOCKET_UDP:
		return "udp"
	if resolved_type == GML_NETWORK_SOCKET_WS:
		return "websocket"
	if resolved_type == GML_NETWORK_SOCKET_WSS:
		return "websocket_tls"
	return ""


static func _gml_network_schedule_poll():
	if _gml_network_poll_scheduled or _gml_network_entries.is_empty():
		return
	var main_loop = Engine.get_main_loop()
	if not (main_loop is SceneTree):
		return
	_gml_network_poll_scheduled = true
	main_loop.process_frame.connect(func():
		_gml_network_poll_scheduled = false
		gml_network_poll()
		if not _gml_network_entries.is_empty():
			_gml_network_schedule_poll()
	, CONNECT_ONE_SHOT)


static func _gml_network_poll_tcp_server(entry):
	var server = entry["server"]
	var accepted = 0
	while server.is_connection_available() and accepted < int(entry["max_clients"]):
		var peer = server.take_connection()
		if peer == null:
			break
		var connection: Variant = {
			"protocol": "tcp",
			"role": "server_client",
			"peer": peer,
			"server_handle": entry["handle"],
			"connected": true,
			"connecting": false,
			"remote_host": _gml_network_peer_host(peer),
			"remote_port": _gml_network_peer_port(peer)
		}
		_gml_network_register(connection)
		_gml_network_dispatch(connection, GML_NETWORK_TYPE_CONNECT, {
			"status": OK,
			"ip": connection["remote_host"],
			"port": connection["remote_port"],
			"server": entry["handle"]
		})
		accepted += 1


static func _gml_network_poll_tcp_peer(entry):
	var peer = entry["peer"]
	var err = peer.poll()
	if err != OK:
		_gml_network_mark_disconnected(entry, err)
		return
	var status = peer.get_status()
	if status == StreamPeerTCP.STATUS_CONNECTED:
		if not bool(entry["connected"]):
			entry["connected"] = true
			entry["connecting"] = false
			_gml_network_dispatch(entry, GML_NETWORK_TYPE_CONNECT, {
				"status": OK,
				"ip": _gml_network_peer_host(peer, entry["remote_host"]),
				"port": _gml_network_peer_port(peer, entry["remote_port"])
			})
		var available = peer.get_available_bytes()
		if available > 0:
			var result = peer.get_data(available)
			if result.size() >= 2 and int(result[0]) == OK:
				_gml_network_dispatch_data(entry, result[1])
	elif status == StreamPeerTCP.STATUS_ERROR:
		_gml_network_mark_disconnected(entry, ERR_CONNECTION_ERROR)
	elif status == StreamPeerTCP.STATUS_NONE:
		if bool(entry["connected"]) or bool(entry["connecting"]):
			_gml_network_mark_disconnected(entry, OK)


static func _gml_network_poll_udp_peer(entry):
	var peer = entry["peer"]
	while peer.get_available_packet_count() > 0:
		var bytes = peer.get_packet()
		var remote_host = peer.get_packet_ip()
		var remote_port = peer.get_packet_port()
		entry["remote_host"] = remote_host
		entry["remote_port"] = remote_port
		entry["connected"] = true
		_gml_network_dispatch_data(entry, bytes, remote_host, remote_port)


static func _gml_network_send_buffer(socket, buffer_id, size):
	var entry: Variant = _gml_network_entry(socket)
	if entry == null:
		return -1
	var bytes = _gml_network_bytes_from_buffer(buffer_id, size)
	if entry.has("peer") and entry["peer"] is StreamPeerTCP:
		var peer = entry["peer"]
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			peer.poll()
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			return -1
		var err = peer.put_data(bytes)
		return bytes.size() if err == OK else -1
	if entry.has("peer") and entry["peer"] is PacketPeerUDP:
		var err = entry["peer"].put_packet(bytes)
		return bytes.size() if err == OK else -1
	return -1


static func _gml_network_send_udp(socket, host, port, buffer_id, size, broadcast = false):
	var entry: Variant = _gml_network_entry(socket)
	if entry == null or not entry.has("peer") or not (entry["peer"] is PacketPeerUDP):
		return -1
	var bytes = _gml_network_bytes_from_buffer(buffer_id, size)
	var resolved_host = str(host)
	var resolved_port = max(0, _to_int64_value(port))
	if bool(broadcast) and entry["peer"].has_method("set_broadcast_enabled"):
		entry["peer"].set_broadcast_enabled(true)
	var err = entry["peer"].set_dest_address(resolved_host, resolved_port)
	if err != OK:
		return -1
	entry["remote_host"] = resolved_host
	entry["remote_port"] = resolved_port
	entry["connected"] = true
	err = entry["peer"].put_packet(bytes)
	return bytes.size() if err == OK else -1


static func _gml_network_bytes_from_buffer(buffer_id, size):
	var buffer: Variant = _gml_buffer_resolve(buffer_id)
	if buffer == null:
		return PackedByteArray()
	var byte_count = max(0, _to_int64_value(size))
	return _gml_buffer_read_bytes(buffer, 0, min(byte_count, buffer.used_size))


static func _gml_network_buffer_from_bytes(bytes):
	var handle = gml_buffer_create(bytes.size(), GML_BUFFER_GROW, 1)
	var buffer: Variant = _gml_buffer_resolve(handle)
	if buffer != null:
		_gml_buffer_write_bytes(buffer, 0, bytes)
	return handle


static func _gml_network_dispatch_data(entry, bytes, remote_host = null, remote_port = null):
	var buffer = _gml_network_buffer_from_bytes(bytes)
	_gml_network_dispatch(entry, GML_NETWORK_TYPE_DATA, {
		"buffer": buffer,
		"size": bytes.size(),
		"ip": str(remote_host) if remote_host != null else _gml_network_peer_host(entry["peer"], entry["remote_host"]),
		"port": int(remote_port) if remote_port != null else _gml_network_peer_port(entry["peer"], entry["remote_port"]),
		"status": OK
	})


static func _gml_network_dispatch(entry, message_type, payload):
	var resolved_payload = payload if payload is Dictionary else {}
	resolved_payload["id"] = entry["id"]
	resolved_payload["socket"] = entry["handle"]
	resolved_payload["type"] = int(message_type)
	resolved_payload["message_type"] = int(message_type)
	resolved_payload["network_type"] = int(message_type)
	resolved_payload["protocol"] = entry["protocol"]
	gml_async_dispatch("networking", resolved_payload, "_on_async_networking")


static func _gml_network_mark_disconnected(entry, status):
	if not bool(entry["connected"]) and not bool(entry["connecting"]):
		return
	entry["connected"] = false
	entry["connecting"] = false
	_gml_network_dispatch(entry, GML_NETWORK_TYPE_DISCONNECT, {
		"status": int(status),
		"ip": entry["remote_host"],
		"port": entry["remote_port"]
	})


static func _gml_network_peer_host(peer, fallback = ""):
	if peer != null and peer.has_method("get_connected_host"):
		var host = str(peer.get_connected_host())
		if host != "":
			return host
	return str(fallback)


static func _gml_network_peer_port(peer, fallback = 0):
	if peer != null and peer.has_method("get_connected_port"):
		var port = int(peer.get_connected_port())
		if port > 0:
			return port
	return int(fallback)
