static var _gml_input_key_current = {}
static var _gml_input_key_pressed = {}
static var _gml_input_key_released = {}
static var _gml_input_mouse_current = {}
static var _gml_input_mouse_pressed = {}
static var _gml_input_mouse_released = {}
static var _gml_input_gamepad_current = {}
static var _gml_input_gamepad_pressed = {}
static var _gml_input_gamepad_released = {}
static var _gml_input_gamepad_axis_values = {}
static var _gml_input_gamepad_axis_deadzones = {}
static var _gml_input_mouse_position = Vector2.ZERO
static var _gml_input_mouse_wheel_up = false
static var _gml_input_mouse_wheel_down = false
static var _gml_input_keyboard_key = 0
static var _gml_input_keyboard_lastkey = 0
static var _gml_input_keyboard_string = ""
static var _gml_input_gesture_events = []
static var _gml_input_dispatch_trace = []


static func gml_input_begin_frame():
	return _gml_input_clear_frame_edges()


static func gml_input_end_frame():
	return _gml_input_clear_frame_edges()


static func _gml_input_clear_frame_edges():
	_gml_input_key_pressed = {}
	_gml_input_key_released = {}
	_gml_input_mouse_pressed = {}
	_gml_input_mouse_released = {}
	_gml_input_gamepad_pressed = {}
	_gml_input_gamepad_released = {}
	_gml_input_mouse_wheel_up = false
	_gml_input_mouse_wheel_down = false
	_gml_input_gesture_events = []
	return null


static func gml_input_set_key_state(key, down):
	var key_code = _gml_input_key_code(key)
	var is_down = gml_bool(down)
	var was_down = bool(_gml_input_key_current.get(key_code, false))
	_gml_input_key_current[key_code] = is_down
	if is_down and not was_down:
		_gml_input_key_pressed[key_code] = true
		_gml_input_keyboard_key = key_code
		_gml_input_keyboard_lastkey = key_code
	if not is_down and was_down:
		_gml_input_key_released[key_code] = true
	return null


static func gml_input_set_mouse_button_state(button, down):
	var button_code = _gml_input_mouse_button(button)
	var is_down = gml_bool(down)
	var was_down = bool(_gml_input_mouse_current.get(button_code, false))
	_gml_input_mouse_current[button_code] = is_down
	if is_down and not was_down:
		_gml_input_mouse_pressed[button_code] = true
	if not is_down and was_down:
		_gml_input_mouse_released[button_code] = true
	return null


static func gml_input_set_gamepad_button_state(device, button, down):
	var key = _gml_gamepad_button_key(device, button)
	var is_down = gml_bool(down)
	var was_down = bool(_gml_input_gamepad_current.get(key, false))
	_gml_input_gamepad_current[key] = is_down
	if is_down and not was_down:
		_gml_input_gamepad_pressed[key] = true
	if not is_down and was_down:
		_gml_input_gamepad_released[key] = true
	return null


static func gml_input_set_gamepad_axis_value(device, axis, value):
	_gml_input_gamepad_axis_values[_gml_gamepad_axis_key(device, axis)] = _to_real(value)
	return null


static func gml_input_set_mouse_position(x, y):
	_gml_input_mouse_position = Vector2(_to_real(x), _to_real(y))
	return null


static func gml_input_set_mouse_wheel(up, down):
	_gml_input_mouse_wheel_up = gml_bool(up)
	_gml_input_mouse_wheel_down = gml_bool(down)
	return null


static func gml_input_append_text(text):
	_gml_input_keyboard_string += str(text)
	return null


static func gml_input_dispatch_trace():
	return _gml_clone_value(_gml_input_dispatch_trace, 16)


static func gml_input_dispatch_trace_clear():
	_gml_input_dispatch_trace = []
	return null


static func gml_input_event_capture(event):
	if event == null:
		return null
	if event is InputEventKey:
		var key_code = int(event.keycode)
		if key_code == 0:
			key_code = int(event.physical_keycode)
		if key_code != 0 and not bool(event.echo):
			gml_input_set_key_state(key_code, bool(event.pressed))
		if bool(event.pressed) and int(event.unicode) > 0:
			gml_input_append_text(char(int(event.unicode)))
		return null
	if event is InputEventMouseButton:
		gml_input_set_mouse_position(event.position.x, event.position.y)
		if int(event.button_index) == MOUSE_BUTTON_WHEEL_UP:
			gml_input_set_mouse_wheel(bool(event.pressed), _gml_input_mouse_wheel_down)
			return null
		if int(event.button_index) == MOUSE_BUTTON_WHEEL_DOWN:
			gml_input_set_mouse_wheel(_gml_input_mouse_wheel_up, bool(event.pressed))
			return null
		gml_input_set_mouse_button_state(int(event.button_index), bool(event.pressed))
		return null
	if event is InputEventMouseMotion:
		gml_input_set_mouse_position(event.position.x, event.position.y)
		return null
	if event is InputEventJoypadButton:
		gml_input_set_gamepad_button_state(int(event.device), int(event.button_index), bool(event.pressed))
		return null
	if event is InputEventJoypadMotion:
		gml_input_set_gamepad_axis_value(int(event.device), int(event.axis), _to_real(event.axis_value))
		return null
	if event is InputEventScreenTouch:
		gml_input_set_mouse_position(event.position.x, event.position.y)
		gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, bool(event.pressed))
		if bool(event.pressed):
			gml_input_enqueue_gesture(0, _gml_input_touch_payload(event, "tap"), false)
		return null
	if event is InputEventScreenDrag:
		gml_input_set_mouse_position(event.position.x, event.position.y)
		gml_input_enqueue_gesture(2, _gml_input_touch_payload(event, "drag"), false)
		return null
	return null


static func gml_input_enqueue_gesture(event_num, payload = null, global_event = false):
	var resolved_payload = payload if payload is Dictionary else {}
	_gml_input_gesture_events.append({
		"event_type": 13,
		"event_num": int(_to_real(event_num)),
		"payload": _gml_input_normalize_gesture_payload(resolved_payload),
		"global": gml_bool(global_event),
	})
	return null


static func gml_input_dispatch_frame(instances = null):
	var instance_snapshot = _gml_input_instance_snapshot(instances)
	var dispatched = 0
	for inst in instance_snapshot:
		if not _gml_input_instance_valid(inst):
			continue
		if not inst.has_method("_gm_input_event_bindings"):
			continue
		var bindings = inst._gm_input_event_bindings()
		if not (bindings is Array):
			continue
		for binding in bindings:
			if not (binding is Dictionary):
				continue
			if not _gml_input_binding_matches(inst, binding):
				continue
			dispatched += _gml_input_dispatch_binding(inst, binding)
	_gml_builtin_globals["event_data"] = {}
	_gml_input_gesture_events = []
	return dispatched


static func gml_keyboard_check(key):
	var key_code = _gml_input_key_code(key)
	if key_code == 0:
		for value in _gml_input_key_current.values():
			if bool(value):
				return true
		return Input.is_anything_pressed()
	if _gml_input_key_current.has(key_code):
		return bool(_gml_input_key_current[key_code])
	return Input.is_key_pressed(key_code)


static func gml_keyboard_check_pressed(key):
	var key_code = _gml_input_key_code(key)
	if key_code == 0:
		return not _gml_input_key_pressed.is_empty()
	if _gml_input_key_pressed.has(key_code):
		return true
	return Input.is_key_label_pressed(key_code) and not bool(_gml_input_key_current.get(key_code, false))


static func gml_keyboard_check_released(key):
	var key_code = _gml_input_key_code(key)
	if key_code == 0:
		return not _gml_input_key_released.is_empty()
	return bool(_gml_input_key_released.get(key_code, false))


static func gml_keyboard_clear(key):
	var key_code = _gml_input_key_code(key)
	if key_code == 0:
		_gml_input_key_current = {}
		_gml_input_key_pressed = {}
		_gml_input_key_released = {}
	else:
		_gml_input_key_current.erase(key_code)
		_gml_input_key_pressed.erase(key_code)
		_gml_input_key_released.erase(key_code)
	_gml_input_keyboard_key = 0
	_gml_input_keyboard_string = ""
	return null


static func gml_keyboard_key_press(key):
	return gml_input_set_key_state(key, true)


static func gml_keyboard_key_release(key):
	return gml_input_set_key_state(key, false)


static func gml_mouse_check_button(button):
	var button_code = _gml_input_mouse_button(button)
	if button_code == -1:
		for value in _gml_input_mouse_current.values():
			if bool(value):
				return true
		return false
	if _gml_input_mouse_current.has(button_code):
		return bool(_gml_input_mouse_current[button_code])
	return Input.is_mouse_button_pressed(button_code)


static func gml_mouse_check_button_pressed(button):
	var button_code = _gml_input_mouse_button(button)
	if button_code == -1:
		return not _gml_input_mouse_pressed.is_empty()
	return bool(_gml_input_mouse_pressed.get(button_code, false))


static func gml_mouse_check_button_released(button):
	var button_code = _gml_input_mouse_button(button)
	if button_code == -1:
		return not _gml_input_mouse_released.is_empty()
	return bool(_gml_input_mouse_released.get(button_code, false))


static func gml_display_mouse_get_x():
	return _gml_input_mouse_position.x


static func gml_display_mouse_get_y():
	return _gml_input_mouse_position.y


static func gml_device_mouse_x_to_gui(device):
	return _gml_mouse_room_to_gui(_gml_input_mouse_position).x


static func gml_device_mouse_y_to_gui(device):
	return _gml_mouse_room_to_gui(_gml_input_mouse_position).y


static func gml_gamepad_is_connected(device):
	return Input.is_joy_known(int(_to_real(device)))


static func gml_gamepad_button_check(device, button):
	var key = _gml_gamepad_button_key(device, button)
	if _gml_input_gamepad_current.has(key):
		return bool(_gml_input_gamepad_current[key])
	return Input.is_joy_button_pressed(int(_to_real(device)), int(_to_real(button)))


static func gml_gamepad_button_check_pressed(device, button):
	return bool(_gml_input_gamepad_pressed.get(_gml_gamepad_button_key(device, button), false))


static func gml_gamepad_button_check_released(device, button):
	return bool(_gml_input_gamepad_released.get(_gml_gamepad_button_key(device, button), false))


static func gml_gamepad_axis_value(device, axis):
	var key = _gml_gamepad_axis_key(device, axis)
	var value = _to_real(_gml_input_gamepad_axis_values.get(key, Input.get_joy_axis(int(_to_real(device)), int(_to_real(axis)))))
	var deadzone = _to_real(_gml_input_gamepad_axis_deadzones.get(int(_to_real(device)), 0.0))
	return 0.0 if abs(value) < deadzone else value


static func gml_gamepad_set_axis_deadzone(device, deadzone):
	_gml_input_gamepad_axis_deadzones[int(_to_real(device))] = clamp(_to_real(deadzone), 0.0, 1.0)
	return null


static func gml_gamepad_get_axis_deadzone(device):
	return _to_real(_gml_input_gamepad_axis_deadzones.get(int(_to_real(device)), 0.0))


static func gml_gamepad_set_vibration(device, left_motor, right_motor):
	push_warning("GM gamepad_set_vibration is a compatibility stub in this runtime")
	return null


static func _gml_input_key_code(key):
	return int(_to_real(key))


static func _gml_input_mouse_button(button):
	return int(_to_real(button))


static func _gml_gamepad_button_key(device, button):
	return str(int(_to_real(device))) + ":" + str(int(_to_real(button)))


static func _gml_gamepad_axis_key(device, axis):
	return str(int(_to_real(device))) + ":" + str(int(_to_real(axis)))


static func _gml_mouse_room_to_gui(position):
	var gui_size = _gml_display_gui_dimensions()
	var app_size = _gml_application_surface_size()
	var scale_x = gui_size.x / app_size.x if app_size.x > 0.0 else 1.0
	var scale_y = gui_size.y / app_size.y if app_size.y > 0.0 else 1.0
	return Vector2(position.x * scale_x, position.y * scale_y)


static func _gml_input_instance_snapshot(instances):
	if instances is Array:
		var provided = []
		for inst in instances:
			provided.append(inst)
		return provided
	var snapshot = []
	for entry in _gml_live_instance_entries():
		var inst = entry.get("instance")
		if inst != null:
			snapshot.append(inst)
	return snapshot


static func _gml_input_instance_valid(inst):
	if inst == null:
		return false
	if inst is Object and not is_instance_valid(inst):
		return false
	return true


static func _gml_input_binding_matches(inst, binding):
	var event_type = int(_to_real(binding.get("event_type", -1)))
	var event_num = int(_to_real(binding.get("event_num", 0)))
	if event_type == 5:
		return _gml_input_keyboard_held_matches(event_num)
	if event_type == 9:
		return _gml_input_keyboard_pressed_matches(event_num)
	if event_type == 10:
		return _gml_input_keyboard_released_matches(event_num)
	if event_type == 6:
		return _gml_input_mouse_event_matches(inst, event_num)
	if event_type == 13:
		return _gml_input_gesture_event_matches(inst, event_num, binding)
	return false


static func _gml_input_dispatch_binding(inst, binding):
	var method_name = str(binding.get("method", ""))
	if method_name == "" or not inst.has_method(method_name):
		return 0
	var event_type = int(_to_real(binding.get("event_type", -1)))
	var event_num = int(_to_real(binding.get("event_num", 0)))
	var previous_event_data = _gml_builtin_globals["event_data"] if _gml_builtin_globals.has("event_data") else {}
	var payload = _gml_input_binding_payload(inst, binding)
	_gml_builtin_globals["event_data"] = payload
	_gml_input_dispatch_trace.append({
		"instance": str(inst.name) if inst is Node else "",
		"event_type": event_type,
		"event_num": event_num,
		"method": method_name,
	})
	inst.call(method_name)
	_gml_builtin_globals["event_data"] = previous_event_data
	return 1


static func _gml_input_binding_payload(inst, binding):
	var event_type = int(_to_real(binding.get("event_type", -1)))
	if event_type != 13:
		return {}
	var event_num = int(_to_real(binding.get("event_num", 0)))
	for gesture in _gml_input_gesture_events:
		if not (gesture is Dictionary):
			continue
		if int(_to_real(gesture.get("event_num", -1))) != event_num:
			continue
		if gml_bool(gesture.get("global", false)) or _gml_input_instance_contains_mouse(inst):
			var payload = gesture.get("payload", {})
			return payload if payload is Dictionary else {}
	return {}


static func _gml_input_keyboard_held_matches(event_num):
	if event_num == 0:
		return not _gml_input_any_key_down()
	if event_num == 1:
		return _gml_input_any_key_down()
	return gml_keyboard_check(event_num)


static func _gml_input_keyboard_pressed_matches(event_num):
	if event_num == 0:
		return false
	if event_num == 1:
		return not _gml_input_key_pressed.is_empty()
	return gml_keyboard_check_pressed(event_num)


static func _gml_input_keyboard_released_matches(event_num):
	if event_num == 0:
		return false
	if event_num == 1:
		return not _gml_input_key_released.is_empty()
	return gml_keyboard_check_released(event_num)


static func _gml_input_any_key_down():
	for value in _gml_input_key_current.values():
		if bool(value):
			return true
	return Input.is_anything_pressed()


static func _gml_input_mouse_event_matches(inst, event_num):
	var button_event = _gml_input_mouse_event_button_and_phase(event_num)
	if button_event["phase"] == "none":
		return false
	if not gml_bool(button_event["global"]) and not _gml_input_instance_contains_mouse(inst):
		return false
	var phase = str(button_event["phase"])
	var button = int(_to_real(button_event["button"]))
	if phase == "held":
		return gml_mouse_check_button(button)
	if phase == "pressed":
		return gml_mouse_check_button_pressed(button)
	if phase == "released":
		return gml_mouse_check_button_released(button)
	if phase == "no_button":
		return not _gml_input_any_mouse_button_down()
	if phase == "enter":
		return _gml_input_instance_contains_mouse(inst)
	if phase == "leave":
		return false
	if phase == "wheel_up":
		return _gml_input_mouse_wheel_up
	if phase == "wheel_down":
		return _gml_input_mouse_wheel_down
	return false


static func _gml_input_mouse_event_button_and_phase(event_num):
	var mapping = {
		0: {"button": MOUSE_BUTTON_LEFT, "phase": "held", "global": false},
		1: {"button": MOUSE_BUTTON_RIGHT, "phase": "held", "global": false},
		2: {"button": MOUSE_BUTTON_MIDDLE, "phase": "held", "global": false},
		3: {"button": -1, "phase": "no_button", "global": false},
		4: {"button": MOUSE_BUTTON_LEFT, "phase": "pressed", "global": false},
		5: {"button": MOUSE_BUTTON_RIGHT, "phase": "pressed", "global": false},
		6: {"button": MOUSE_BUTTON_MIDDLE, "phase": "pressed", "global": false},
		7: {"button": MOUSE_BUTTON_LEFT, "phase": "released", "global": false},
		8: {"button": MOUSE_BUTTON_RIGHT, "phase": "released", "global": false},
		9: {"button": MOUSE_BUTTON_MIDDLE, "phase": "released", "global": false},
		10: {"button": -1, "phase": "enter", "global": false},
		11: {"button": -1, "phase": "leave", "global": false},
		50: {"button": MOUSE_BUTTON_LEFT, "phase": "held", "global": true},
		51: {"button": MOUSE_BUTTON_RIGHT, "phase": "held", "global": true},
		52: {"button": MOUSE_BUTTON_MIDDLE, "phase": "held", "global": true},
		53: {"button": MOUSE_BUTTON_LEFT, "phase": "pressed", "global": true},
		54: {"button": MOUSE_BUTTON_RIGHT, "phase": "pressed", "global": true},
		55: {"button": MOUSE_BUTTON_MIDDLE, "phase": "pressed", "global": true},
		56: {"button": MOUSE_BUTTON_LEFT, "phase": "released", "global": true},
		57: {"button": MOUSE_BUTTON_RIGHT, "phase": "released", "global": true},
		58: {"button": MOUSE_BUTTON_MIDDLE, "phase": "released", "global": true},
		60: {"button": -1, "phase": "wheel_up", "global": true},
		61: {"button": -1, "phase": "wheel_down", "global": true},
	}
	return mapping.get(int(_to_real(event_num)), {"button": -1, "phase": "none", "global": false})


static func _gml_input_any_mouse_button_down():
	for value in _gml_input_mouse_current.values():
		if bool(value):
			return true
	return false


static func _gml_input_instance_contains_mouse(inst):
	if inst == null:
		return false
	if inst.has_method("_gm_input_contains_point"):
		return bool(inst.call("_gm_input_contains_point", _gml_input_mouse_position.x, _gml_input_mouse_position.y))
	if inst is Control:
		return inst.get_global_rect().has_point(_gml_input_mouse_position)
	if inst is Node2D:
		var radius = 0.0
		if inst.has_meta("gamemaker_collision_radius"):
			radius = max(_to_real(inst.get_meta("gamemaker_collision_radius")), 0.0)
		if radius > 0.0:
			return inst.global_position.distance_to(_gml_input_mouse_position) <= radius
	_gml_input_dispatch_trace.append({
		"diagnostic": "missing_mouse_mask",
		"instance": str(inst.name) if inst is Node else "",
	})
	return true


static func _gml_input_gesture_event_matches(inst, event_num, binding):
	for gesture in _gml_input_gesture_events:
		if not (gesture is Dictionary):
			continue
		if int(_to_real(gesture.get("event_num", -1))) != int(_to_real(event_num)):
			continue
		if gml_bool(gesture.get("global", false)) or _gml_input_instance_contains_mouse(inst):
			return true
	return false


static func _gml_input_normalize_gesture_payload(payload):
	var result = {}
	for key in payload.keys():
		result[key] = payload[key]
	if not result.has("posX"):
		result["posX"] = _gml_input_mouse_position.x
	if not result.has("posY"):
		result["posY"] = _gml_input_mouse_position.y
	if not result.has("rawposX"):
		result["rawposX"] = result["posX"]
	if not result.has("rawposY"):
		result["rawposY"] = result["posY"]
	var gui_position = _gml_mouse_room_to_gui(Vector2(_to_real(result["posX"]), _to_real(result["posY"])))
	if not result.has("guiposX"):
		result["guiposX"] = gui_position.x
	if not result.has("guiposY"):
		result["guiposY"] = gui_position.y
	if not result.has("touch"):
		result["touch"] = 0
	if not result.has("gesture"):
		result["gesture"] = 0
	return result


static func _gml_input_touch_payload(event, gesture_name):
	var payload = {
		"gesture": 0,
		"touch": int(event.index),
		"posX": event.position.x,
		"posY": event.position.y,
		"rawposX": event.position.x,
		"rawposY": event.position.y,
		"name": str(gesture_name),
	}
	var gui_position = _gml_mouse_room_to_gui(event.position)
	payload["guiposX"] = gui_position.x
	payload["guiposY"] = gui_position.y
	return payload
