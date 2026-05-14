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


static func gml_input_begin_frame():
	_gml_input_key_pressed = {}
	_gml_input_key_released = {}
	_gml_input_mouse_pressed = {}
	_gml_input_mouse_released = {}
	_gml_input_gamepad_pressed = {}
	_gml_input_gamepad_released = {}
	_gml_input_mouse_wheel_up = false
	_gml_input_mouse_wheel_down = false
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
