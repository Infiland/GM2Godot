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
static var _gml_input_gamepad_colors = {}
static var _gml_input_mouse_position = Vector2.ZERO
static var _gml_input_mouse_wheel_up = false
static var _gml_input_mouse_wheel_down = false
static var _gml_input_keyboard_key = 0
static var _gml_input_keyboard_lastkey = 0
static var _gml_input_keyboard_string = ""
static var _gml_input_gesture_events = []
# Input events run while tracing is on (gml_event_scheduler_set_tracing);
# gml_input_dispatch_trace() returns at most GML_INPUT_TRACE_LIMIT of the
# latest records.
static var _gml_input_dispatch_trace = []
const GML_INPUT_TRACE_LIMIT = 256
# The binding table of every live instance, and the instance creation counter
# it was built at.
static var _gml_input_live_table = []
static var _gml_input_live_table_mark = -1
# Input timing follows GameMaker's IO start of step: device events and the
# simulated keyboard_key_press/keyboard_key_release update the raw state below
# whenever they arrive, and gml_input_begin_step() latches that raw state into
# the per-step state read by keyboard_check*, mouse_check_button*,
# gamepad_button_check* and the keyboard/mouse events. Pressed and released
# edges therefore stay true for the whole step, including Draw and Draw GUI,
# and are replaced when the next step starts. Edges that arrive between two
# steps are kept until the next latch, so a press and release inside one frame
# still produce one pressed and one released step. Without the frame pump
# (unit tests and tools) every change is published to the step state at once
# and gml_input_end_frame() clears the edges.
static var _gml_input_step_latching = false
static var _gml_input_raw_keys = {"down": {}, "pressed": {}, "released": {}}
static var _gml_input_raw_mouse = {"down": {}, "pressed": {}, "released": {}}
static var _gml_input_raw_gamepad = {"down": {}, "pressed": {}, "released": {}}
static var _gml_input_raw_wheel_delta = 0
static var _gml_input_raw_gesture_events = []
static var _gml_input_raw_last_key = 0
# Keys cleared with keyboard_clear() while held, until they are released.
static var _gml_input_key_suppressed = {}
# Keyboard state, keyboard_key, keyboard_lastkey and the keyboard events use
# GameMaker's virtual key codes (the vk_* constants, and ord() for A-Z and
# 0-9). This table gives the code of every Godot key whose key code differs;
# letters, digits and space are the same in both. Godot keys without a
# GameMaker code are kept above 255 so they cannot be mistaken for one.
const GML_INPUT_GAMEMAKER_KEY_CODES = {
	KEY_BACKSPACE: 8,
	KEY_TAB: 9,
	KEY_ENTER: 13,
	KEY_KP_ENTER: 13,
	KEY_SHIFT: 16,
	KEY_CTRL: 17,
	KEY_ALT: 18,
	KEY_PAUSE: 19,
	KEY_CAPSLOCK: 20,
	KEY_ESCAPE: 27,
	KEY_PAGEUP: 33,
	KEY_PAGEDOWN: 34,
	KEY_END: 35,
	KEY_HOME: 36,
	KEY_LEFT: 37,
	KEY_UP: 38,
	KEY_RIGHT: 39,
	KEY_DOWN: 40,
	KEY_PRINT: 44,
	KEY_INSERT: 45,
	KEY_DELETE: 46,
	KEY_META: 91,
	KEY_MENU: 93,
	KEY_KP_0: 96,
	KEY_KP_1: 97,
	KEY_KP_2: 98,
	KEY_KP_3: 99,
	KEY_KP_4: 100,
	KEY_KP_5: 101,
	KEY_KP_6: 102,
	KEY_KP_7: 103,
	KEY_KP_8: 104,
	KEY_KP_9: 105,
	KEY_KP_MULTIPLY: 106,
	KEY_KP_ADD: 107,
	KEY_KP_SUBTRACT: 109,
	KEY_KP_PERIOD: 110,
	KEY_KP_DIVIDE: 111,
	KEY_F1: 112,
	KEY_F2: 113,
	KEY_F3: 114,
	KEY_F4: 115,
	KEY_F5: 116,
	KEY_F6: 117,
	KEY_F7: 118,
	KEY_F8: 119,
	KEY_F9: 120,
	KEY_F10: 121,
	KEY_F11: 122,
	KEY_F12: 123,
	KEY_F13: 124,
	KEY_F14: 125,
	KEY_F15: 126,
	KEY_F16: 127,
	KEY_NUMLOCK: 144,
	KEY_SCROLLLOCK: 145,
	KEY_SEMICOLON: 186,
	KEY_EQUAL: 187,
	KEY_PLUS: 187,
	KEY_COMMA: 188,
	KEY_MINUS: 189,
	KEY_PERIOD: 190,
	KEY_SLASH: 191,
	KEY_QUOTELEFT: 192,
	KEY_BRACKETLEFT: 219,
	KEY_BACKSLASH: 220,
	KEY_BRACKETRIGHT: 221,
	KEY_APOSTROPHE: 222,
	KEY_LESS: 226,
}
# vk_shift/vk_control/vk_alt and their left and right codes.
const GML_INPUT_SIDED_KEY_CODES = {
	16: [160, 161],
	17: [162, 163],
	18: [164, 165],
}
const GML_INPUT_UNMAPPED_KEY_OFFSET = 256
static var _gml_input_godot_key_codes = {}


static func gml_input_set_step_latching(enabled):
	var latching = gml_bool(enabled)
	if latching == _gml_input_step_latching:
		return null
	_gml_input_step_latching = latching
	_gml_input_raw_keys = {"down": _gml_input_state_copy(_gml_input_key_current), "pressed": {}, "released": {}}
	_gml_input_raw_mouse = {"down": _gml_input_state_copy(_gml_input_mouse_current), "pressed": {}, "released": {}}
	_gml_input_raw_gamepad = {"down": _gml_input_state_copy(_gml_input_gamepad_current), "pressed": {}, "released": {}}
	_gml_input_raw_wheel_delta = 0
	_gml_input_raw_gesture_events = []
	_gml_input_raw_last_key = 0
	_gml_input_key_suppressed = {}
	return null


static func gml_input_step_latching():
	return _gml_input_step_latching


static func gml_input_begin_step():
	if not _gml_input_step_latching:
		return null
	_gml_input_key_current = _gml_input_state_copy(_gml_input_raw_keys["down"])
	for key_code in _gml_input_key_suppressed.keys():
		_gml_input_key_current[key_code] = false
	_gml_input_key_pressed = _gml_input_raw_keys["pressed"]
	_gml_input_key_released = _gml_input_raw_keys["released"]
	_gml_input_mouse_current = _gml_input_state_copy(_gml_input_raw_mouse["down"])
	_gml_input_mouse_pressed = _gml_input_raw_mouse["pressed"]
	_gml_input_mouse_released = _gml_input_raw_mouse["released"]
	_gml_input_gamepad_current = _gml_input_state_copy(_gml_input_raw_gamepad["down"])
	_gml_input_gamepad_pressed = _gml_input_raw_gamepad["pressed"]
	_gml_input_gamepad_released = _gml_input_raw_gamepad["released"]
	for channel in [_gml_input_raw_keys, _gml_input_raw_mouse, _gml_input_raw_gamepad]:
		channel["pressed"] = {}
		channel["released"] = {}
	_gml_input_mouse_wheel_up = _gml_input_raw_wheel_delta > 0
	_gml_input_mouse_wheel_down = _gml_input_raw_wheel_delta < 0
	_gml_input_raw_wheel_delta = 0
	_gml_input_gesture_events = _gml_input_raw_gesture_events
	_gml_input_raw_gesture_events = []
	_gml_input_latch_keyboard_key()
	return null


static func _gml_input_state_copy(state):
	var copy = {}
	for code in state.keys():
		copy[code] = state[code]
	return copy


static func _gml_input_latch_keyboard_key():
	# keyboard_key is the key pressed most recently and resets to 0 at the
	# start of the first step in which that key is no longer held;
	# keyboard_lastkey keeps the value keyboard_key had before it changed.
	# Like GameMaker, a keyboard_key of 0 counts as "held" only while no key
	# is held (vk_nokey), so holding another key then sets keyboard_lastkey
	# to 0.
	if _gml_input_raw_last_key != 0:
		if _gml_input_keyboard_key != 0:
			_gml_input_keyboard_lastkey = _gml_input_keyboard_key
		_gml_input_keyboard_key = _gml_input_raw_last_key
		_gml_input_raw_last_key = 0
	elif not gml_keyboard_check(_gml_input_keyboard_key):
		_gml_input_keyboard_lastkey = _gml_input_keyboard_key
		_gml_input_keyboard_key = 0
	return null


static func gml_input_begin_frame():
	if _gml_input_step_latching:
		return gml_input_begin_step()
	return _gml_input_clear_frame_edges()


static func gml_input_end_frame():
	# With step latching the edges belong to the step that latched them and
	# stay readable until the next step starts, so the end of a frame keeps
	# them.
	if _gml_input_step_latching:
		return null
	return _gml_input_clear_frame_edges()


static func _gml_input_clear_frame_edges():
	# keyboard_clear(vk_nokey/vk_anykey) marks last for one frame only.
	_gml_input_key_current.erase(0)
	_gml_input_key_current.erase(1)
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


static func _gml_input_raw_transition(channel, step_state, code, is_down):
	var was_down = bool(channel["down"].get(code, false))
	channel["down"][code] = is_down
	var pressed = is_down and not was_down
	var released = was_down and not is_down
	if _gml_input_step_latching:
		if pressed:
			channel["pressed"][code] = true
		if released:
			channel["released"][code] = true
		return pressed
	step_state[0][code] = is_down
	if pressed:
		step_state[1][code] = true
	if released:
		step_state[2][code] = true
	return pressed


static func gml_input_set_key_state(key, down, location = KEY_LOCATION_UNSPECIFIED):
	# Records a Godot key (key code and, for Shift, Ctrl and Alt, the
	# KeyLocation telling left from right) under its GameMaker key code.
	var key_code = _gml_input_gamemaker_key(key)
	var is_down = gml_bool(down)
	var sided_codes = GML_INPUT_SIDED_KEY_CODES.get(key_code)
	var side = int(location)
	if sided_codes != null and (side == KEY_LOCATION_LEFT or side == KEY_LOCATION_RIGHT):
		_gml_input_set_gamemaker_key_state(sided_codes[0 if side == KEY_LOCATION_LEFT else 1], is_down, false)
		# vk_shift (and vk_control, vk_alt) stay held while either side is.
		is_down = bool(_gml_input_raw_keys["down"].get(sided_codes[0], false)) or bool(_gml_input_raw_keys["down"].get(sided_codes[1], false))
	return _gml_input_set_gamemaker_key_state(key_code, is_down)


static func _gml_input_set_gamemaker_key_state(key_code, is_down, sets_keyboard_key = true):
	if _gml_input_key_suppressed.has(int(key_code)):
		# A key cleared with keyboard_clear() while held stays up until it is
		# released, and that release is not reported.
		if bool(is_down):
			return null
		_gml_input_key_suppressed.erase(int(key_code))
		_gml_input_raw_keys["down"][int(key_code)] = false
		if not _gml_input_step_latching:
			_gml_input_key_current[int(key_code)] = false
		return null
	var step_state = [_gml_input_key_current, _gml_input_key_pressed, _gml_input_key_released]
	if _gml_input_raw_transition(_gml_input_raw_keys, step_state, int(key_code), bool(is_down)) and sets_keyboard_key:
		if _gml_input_step_latching:
			_gml_input_raw_last_key = int(key_code)
		else:
			_gml_input_keyboard_key = int(key_code)
			_gml_input_keyboard_lastkey = int(key_code)
	return null


static func _gml_input_gamemaker_key(godot_key):
	# The GameMaker virtual key code of a Godot key code.
	var code = int(_to_real(godot_key))
	if GML_INPUT_GAMEMAKER_KEY_CODES.has(code):
		return int(GML_INPUT_GAMEMAKER_KEY_CODES[code])
	if code == KEY_SPACE or (code >= KEY_0 and code <= KEY_9) or (code >= KEY_A and code <= KEY_Z):
		return code
	return code + GML_INPUT_UNMAPPED_KEY_OFFSET


static func _gml_input_godot_key(key_code):
	# The Godot key code of a GameMaker virtual key code, or KEY_NONE.
	var code = int(key_code)
	if code == KEY_SPACE or (code >= KEY_0 and code <= KEY_9) or (code >= KEY_A and code <= KEY_Z):
		return code
	if code >= GML_INPUT_UNMAPPED_KEY_OFFSET:
		return code - GML_INPUT_UNMAPPED_KEY_OFFSET
	if _gml_input_godot_key_codes.is_empty():
		for godot_key in GML_INPUT_GAMEMAKER_KEY_CODES.keys():
			var gamemaker_key = int(GML_INPUT_GAMEMAKER_KEY_CODES[godot_key])
			if not _gml_input_godot_key_codes.has(gamemaker_key):
				_gml_input_godot_key_codes[gamemaker_key] = int(godot_key)
	return int(_gml_input_godot_key_codes.get(code, KEY_NONE))


static func gml_input_set_mouse_button_state(button, down):
	# Records a Godot mouse button under its GameMaker code (mb_left 1,
	# mb_right 2, mb_middle 3, mb_side1 4, mb_side2 5).
	var step_state = [_gml_input_mouse_current, _gml_input_mouse_pressed, _gml_input_mouse_released]
	_gml_input_raw_transition(_gml_input_raw_mouse, step_state, _gml_input_gamemaker_mouse_button(button), gml_bool(down))
	return null


static func _gml_input_gamemaker_mouse_button(godot_button):
	var button = int(_to_real(godot_button))
	if button == MOUSE_BUTTON_XBUTTON1:
		return 4
	if button == MOUSE_BUTTON_XBUTTON2:
		return 5
	return button


static func _gml_input_godot_mouse_button(button):
	var code = int(button)
	if code == 4:
		return MOUSE_BUTTON_XBUTTON1
	if code == 5:
		return MOUSE_BUTTON_XBUTTON2
	return code


static func gml_input_set_gamepad_button_state(device, button, down):
	var step_state = [_gml_input_gamepad_current, _gml_input_gamepad_pressed, _gml_input_gamepad_released]
	_gml_input_raw_transition(_gml_input_raw_gamepad, step_state, _gml_gamepad_button_key(device, button), gml_bool(down))
	return null


static func gml_input_set_gamepad_axis_value(device, axis, value):
	_gml_input_gamepad_axis_values[_gml_gamepad_axis_key(device, axis)] = _to_real(value)
	return null


static func gml_input_set_mouse_position(x, y):
	_gml_input_mouse_position = Vector2(_to_real(x), _to_real(y))
	return null


static func gml_input_set_mouse_wheel(up, down):
	var wheel_up = gml_bool(up)
	var wheel_down = gml_bool(down)
	if _gml_input_step_latching:
		_gml_input_raw_wheel_delta = 1 if wheel_up and not wheel_down else (-1 if wheel_down and not wheel_up else 0)
		return null
	_gml_input_mouse_wheel_up = wheel_up
	_gml_input_mouse_wheel_down = wheel_down
	return null


static func _gml_input_add_wheel_notch(direction):
	if _gml_input_step_latching:
		_gml_input_raw_wheel_delta += direction
		return null
	if direction > 0:
		_gml_input_mouse_wheel_up = true
	elif direction < 0:
		_gml_input_mouse_wheel_down = true
	return null


static func gml_input_append_text(text):
	_gml_input_keyboard_string += str(text)
	return null


static func gml_input_dispatch_trace():
	var trace = _gml_input_dispatch_trace
	if trace.size() > GML_INPUT_TRACE_LIMIT:
		trace = trace.slice(trace.size() - GML_INPUT_TRACE_LIMIT)
	return _gml_clone_value(trace, 16)


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
			gml_input_set_key_state(key_code, bool(event.pressed), int(event.location))
		if bool(event.pressed) and int(event.unicode) > 0:
			gml_input_append_text(char(int(event.unicode)))
		return null
	if event is InputEventMouseButton:
		gml_input_set_mouse_position(event.position.x, event.position.y)
		var button_index = int(event.button_index)
		if button_index == MOUSE_BUTTON_WHEEL_UP or button_index == MOUSE_BUTTON_WHEEL_DOWN:
			# Each wheel notch arrives as a press followed by a release; only
			# the press counts as wheel movement.
			if bool(event.pressed):
				_gml_input_add_wheel_notch(1 if button_index == MOUSE_BUTTON_WHEEL_UP else -1)
			return null
		gml_input_set_mouse_button_state(button_index, bool(event.pressed))
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
	var gesture = {
		"event_type": 13,
		"event_num": int(_to_real(event_num)),
		"payload": _gml_input_normalize_gesture_payload(resolved_payload),
		"global": gml_bool(global_event),
	}
	if _gml_input_step_latching:
		_gml_input_raw_gesture_events.append(gesture)
	else:
		_gml_input_gesture_events.append(gesture)
	return null


static func gml_input_dispatch_frame(instances = null, event_types = null):
	# Runs one step's input events in GameMaker's order: the Keyboard, Key
	# Press and Key Release events (_gml_input_dispatch_keyboard), then the
	# mouse events (_gml_input_dispatch_mouse) and the gesture events.
	# event_types limits the run to those event types (5 Keyboard, 9 Key
	# Press, 10 Key Release, 6 Mouse, 13 Gesture). Without an instance list
	# every live instance takes part; like GameMaker, an instance created by
	# one input event takes part in the events that run after it. Returns how
	# many events ran.
	var dispatched = 0
	for event_type in [5, 9, 10, 6, 13]:
		if event_types is Array and not event_types.has(event_type):
			continue
		if event_type == 6:
			dispatched += _gml_input_dispatch_mouse(instances)
		elif event_type == 13:
			dispatched += _gml_input_dispatch_gestures(_gml_input_binding_table(instances))
		else:
			dispatched += _gml_input_dispatch_keyboard(instances, event_type)
	_gml_builtin_globals["event_data"] = {}
	# Latched gestures belong to the step and are replaced by the next latch.
	if not _gml_input_step_latching and (not (event_types is Array) or event_types.has(13)):
		_gml_input_gesture_events = []
	if _gml_input_dispatch_trace.size() >= GML_INPUT_TRACE_LIMIT * 2:
		_gml_input_dispatch_trace = _gml_input_dispatch_trace.slice(-GML_INPUT_TRACE_LIMIT)
	return dispatched


static func gml_keyboard_check(key):
	var key_code = _gml_input_key_code(key)
	if key_code == 0 or key_code == 1:
		return _gml_input_special_key_check(_gml_input_key_current, key_code)
	if _gml_input_key_current.has(key_code):
		return bool(_gml_input_key_current[key_code])
	# The step state is authoritative while the frame pump latches input;
	# otherwise keys this runtime never saw fall back to the engine.
	if _gml_input_step_latching:
		return false
	var godot_key = _gml_input_godot_key(key_code)
	return godot_key != KEY_NONE and Input.is_key_pressed(godot_key)


static func gml_keyboard_check_pressed(key):
	var key_code = _gml_input_key_code(key)
	if key_code == 0 or key_code == 1:
		return _gml_input_special_key_check(_gml_input_key_pressed, key_code)
	return bool(_gml_input_key_pressed.get(key_code, false))


static func gml_keyboard_check_released(key):
	var key_code = _gml_input_key_code(key)
	if key_code == 0 or key_code == 1:
		return _gml_input_special_key_check(_gml_input_key_released, key_code)
	return bool(_gml_input_key_released.get(key_code, false))


static func _gml_input_special_key_check(state, key_code):
	# vk_nokey (0) is true when no key is in the state, vk_anykey (1) when
	# some key is. keyboard_clear() of either leaves a false entry that makes
	# the check false for the rest of the step.
	if state.has(key_code):
		return false
	return _gml_input_any_key_in(state) == (key_code == 1)


static func _gml_input_any_key_in(state):
	for code in state.keys():
		if int(code) >= 2 and bool(state[code]):
			return true
	return false


static func gml_keyboard_clear(key):
	# Like GameMaker, a cleared key reads as up at once and, while it stays
	# held, is not recognised again until it is released (which raises no
	# Key Release event) and pressed again. Clearing vk_nokey or vk_anykey
	# only clears that check for the rest of the step. Cleared keys are
	# stored as up so the engine's key state cannot report them as held.
	var key_code = _gml_input_key_code(key)
	_gml_input_key_current[key_code] = false
	_gml_input_key_pressed[key_code] = false
	_gml_input_key_released[key_code] = false
	if key_code >= 2 and bool(_gml_input_raw_keys["down"].get(key_code, false)):
		_gml_input_key_suppressed[key_code] = true
	return null


static func gml_keyboard_key_press(key):
	# Simulates a press of a GameMaker key code; like a real key press, the
	# step that starts next sees it.
	return _gml_input_set_gamemaker_key_state(_gml_input_key_code(key), true)


static func gml_keyboard_key_release(key):
	return _gml_input_set_gamemaker_key_state(_gml_input_key_code(key), false)


static func gml_mouse_check_button(button):
	var button_code = _gml_input_mouse_button(button)
	if button_code == -1 or button_code == 0:
		# mb_any / mb_none
		return _gml_input_any_button_in(_gml_input_mouse_current) == (button_code == -1)
	if _gml_input_mouse_current.has(button_code):
		return bool(_gml_input_mouse_current[button_code])
	if _gml_input_step_latching or button_code < 1 or button_code > 5:
		return false
	return Input.is_mouse_button_pressed(_gml_input_godot_mouse_button(button_code))


static func gml_mouse_check_button_pressed(button):
	var button_code = _gml_input_mouse_button(button)
	if button_code == -1 or button_code == 0:
		return _gml_input_any_button_in(_gml_input_mouse_pressed) == (button_code == -1)
	return bool(_gml_input_mouse_pressed.get(button_code, false))


static func gml_mouse_check_button_released(button):
	var button_code = _gml_input_mouse_button(button)
	if button_code == -1 or button_code == 0:
		return _gml_input_any_button_in(_gml_input_mouse_released) == (button_code == -1)
	return bool(_gml_input_mouse_released.get(button_code, false))


static func _gml_input_any_button_in(state):
	for value in state.values():
		if bool(value):
			return true
	return false


static func gml_display_mouse_get_x():
	return _gml_display_mouse_screen_position().x


static func gml_display_mouse_get_y():
	return _gml_display_mouse_screen_position().y


static func gml_device_mouse_x_to_gui(device):
	return int(_gml_mouse_room_to_gui(_gml_input_mouse_position).x)


static func gml_device_mouse_y_to_gui(device):
	return int(_gml_mouse_room_to_gui(_gml_input_mouse_position).y)


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


static func gml_gamepad_set_color(device, color):
	_gml_input_gamepad_colors[int(_to_real(device))] = int(_to_real(color)) & 0xffffff
	return null


static func _gml_input_key_code(key):
	return int(_to_real(key))


static func _gml_input_mouse_button(button):
	return int(_to_real(button))


static func _gml_gamepad_button_key(device, button):
	return str(int(_to_real(device))) + ":" + str(int(_to_real(button)))


static func _gml_gamepad_axis_key(device, axis):
	return str(int(_to_real(device))) + ":" + str(int(_to_real(axis)))


# Input positions are in viewport (application surface) coordinates.
static func _gml_mouse_room_to_gui(position):
	return _gml_display_viewport_to_gui(position)


static func _gml_input_binding_table(instances):
	# One row per instance with input events: the instance, its registry
	# entry, its events as {event_type: {event_num: binding}}, and its object
	# and creation order for GameMaker's mouse event order. Without an
	# instance list the rows cover every live instance; that table is kept
	# until an instance is created, and destroyed instances are skipped when
	# an event runs.
	if instances is Array:
		var table = []
		var position = 0
		for inst in instances:
			position += 1
			if typeof(inst) == TYPE_OBJECT and is_instance_valid(inst):
				var events = _gml_input_instance_events(inst)
				if not events.is_empty():
					table.append(_gml_input_row(inst, _gml_instance_entry(inst), events, position))
		return table
	if _gml_step_running:
		_gml_step_join_created_instances()
	if _gml_input_live_table_mark == _gml_instance_creation_counter:
		return _gml_input_live_table
	var live_table = []
	if _gml_step_running:
		for i in range(_gml_step_entries.size()):
			var events = _gml_step_infos[i].input_events
			if events.is_empty():
				continue
			var entry = _gml_step_entries[i]
			if not entry["destroyed"] and is_instance_valid(entry["instance"]):
				live_table.append(_gml_input_row(entry["instance"], entry, events, 0))
	else:
		for entry in _gml_live_instance_entries():
			var inst = entry["instance"]
			if is_instance_valid(inst):
				var events = _gml_input_instance_events(inst)
				if not events.is_empty():
					live_table.append(_gml_input_row(inst, entry, events, 0))
	_gml_input_live_table = live_table
	_gml_input_live_table_mark = _gml_instance_creation_counter
	return live_table


static func _gml_input_row(inst, entry, events, position):
	return {
		"instance": inst,
		"entry": entry,
		"events": events,
		"object_id": int(entry["object_id"]) if entry != null else -1,
		"object_name": str(entry["object_name"]) if entry != null else "",
		"order": int(entry["creation_order"]) if entry != null else position,
	}


static func _gml_input_instance_events(inst):
	# The instance's input event bindings by event type and number, read once
	# per object script.
	if typeof(inst) != TYPE_OBJECT or not is_instance_valid(inst):
		return {}
	return _gml_step_script_info(inst).input_events


static func _gml_input_read_event_bindings(inst):
	var events = {}
	if not inst.has_method("_gm_input_event_bindings"):
		return events
	var bindings = inst._gm_input_event_bindings()
	if bindings is Array:
		for binding in bindings:
			if not (binding is Dictionary):
				continue
			var event_type = int(_to_real(binding.get("event_type", -1)))
			if not events.has(event_type):
				events[event_type] = {}
			events[event_type][int(_to_real(binding.get("event_num", 0)))] = binding
	return events


static func _gml_input_dispatch_event(instances, event_type, event_num):
	# Runs one input event for every instance that has it.
	var dispatched = 0
	for row in _gml_input_binding_table(instances):
		var events = row["events"].get(event_type)
		if events != null and events.has(event_num):
			dispatched += _gml_input_perform(row, events[event_num])
	return dispatched


static func _gml_input_perform(row, binding):
	# Once a room change is pending no further events run, and destroyed
	# instances get no more events.
	if gml_room_change_pending():
		return 0
	var entry = row["entry"]
	if entry != null and bool(entry["destroyed"]):
		return 0
	var inst = row["instance"]
	if not _gml_event_scheduler_instance_valid(inst):
		return 0
	return _gml_input_dispatch_binding(inst, binding)


static func _gml_input_dispatch_binding(inst, binding):
	var method_name = str(binding.get("method", ""))
	if method_name == "" or not inst.has_method(method_name):
		return 0
	var event_type = int(_to_real(binding.get("event_type", -1)))
	var event_num = int(_to_real(binding.get("event_num", 0)))
	var previous_event_data = _gml_builtin_globals["event_data"] if _gml_builtin_globals.has("event_data") else {}
	var payload = _gml_input_binding_payload(inst, binding)
	_gml_builtin_globals["event_data"] = payload
	if _gml_event_scheduler_tracing:
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


static func _gml_input_dispatch_keyboard(instances, event_type):
	# GameMaker's keyboard handling for one event type (5 Keyboard, 9 Key
	# Press, 10 Key Release): key by key in key code order, every instance
	# with an event for a held (pressed, released) key runs it; then the
	# <Any Key> event runs if any key was held (pressed, released) and the
	# <No Key> event otherwise.
	var state = _gml_input_keyboard_event_state(event_type)
	var codes = []
	for code in state.keys():
		if int(code) >= 2 and bool(state[code]):
			codes.append(int(code))
	codes.sort()
	var any_key = false
	var dispatched = 0
	for code in codes:
		# An earlier event may have cleared the key with keyboard_clear().
		if not bool(_gml_input_keyboard_event_state(event_type).get(code, false)):
			continue
		any_key = true
		dispatched += _gml_input_dispatch_event(instances, event_type, code)
	dispatched += _gml_input_dispatch_event(instances, event_type, 1 if any_key else 0)
	return dispatched


static func _gml_input_keyboard_event_state(event_type):
	if event_type == 9:
		return _gml_input_key_pressed
	if event_type == 10:
		return _gml_input_key_released
	return _gml_input_key_current


static func _gml_input_dispatch_mouse(instances):
	# GameMaker's mouse handling. Object by object in object index order, and
	# newest instance first, every instance with an instance mouse event that
	# is under the mouse runs its held button events (left, right, middle),
	# then its pressed and its released button events, <No Button> when no
	# button is held or pressed, and Mouse Enter when the mouse was not over
	# it before; an instance the mouse has left runs Mouse Leave. Then every
	# instance runs its global held, pressed and released button events,
	# followed by the mouse wheel up and down events.
	var rows = []
	for row in _gml_input_binding_table(instances):
		if _gml_input_has_instance_mouse_event(row["events"].get(6, {})):
			rows.append(row)
	rows.sort_custom(_gml_input_mouse_order_less)
	var dispatched = 0
	for row in rows:
		dispatched += _gml_input_dispatch_instance_mouse(row)
	for button in [1, 2, 3]:
		if gml_mouse_check_button(button):
			dispatched += _gml_input_dispatch_event(instances, 6, 49 + button)
	for button in [1, 2, 3]:
		if gml_mouse_check_button_pressed(button):
			dispatched += _gml_input_dispatch_event(instances, 6, 52 + button)
	for button in [1, 2, 3]:
		if gml_mouse_check_button_released(button):
			dispatched += _gml_input_dispatch_event(instances, 6, 55 + button)
	if _gml_input_mouse_wheel_up:
		dispatched += _gml_input_dispatch_event(instances, 6, 60)
	if _gml_input_mouse_wheel_down:
		dispatched += _gml_input_dispatch_event(instances, 6, 61)
	return dispatched


static func _gml_input_has_instance_mouse_event(mouse_events):
	for event_num in mouse_events.keys():
		if int(event_num) >= 0 and int(event_num) <= 11:
			return true
	return false


static func _gml_input_mouse_order_less(left, right):
	# Object index order, then the newest instance first.
	if int(left["object_id"]) != int(right["object_id"]):
		return int(left["object_id"]) < int(right["object_id"])
	if str(left["object_name"]) != str(right["object_name"]):
		return str(left["object_name"]) < str(right["object_name"])
	return int(left["order"]) > int(right["order"])


static func _gml_input_dispatch_instance_mouse(row):
	var inst = row["instance"]
	var mouse_events = row["events"][6]
	var entry = row["entry"]
	if entry != null and bool(entry["destroyed"]):
		return 0
	if not _gml_event_scheduler_instance_valid(inst) or not _gml_input_mouse_test_needed(mouse_events):
		return 0
	var was_over = inst.has_meta("_gml_mouse_over") and bool(inst.get_meta("_gml_mouse_over"))
	var dispatched = 0
	if not _gml_input_mouse_over_instance(inst):
		if was_over:
			inst.set_meta("_gml_mouse_over", false)
			dispatched += _gml_input_perform_mouse_event(row, mouse_events, 11)
		return dispatched
	var no_button = true
	for button in [1, 2, 3]:
		if gml_mouse_check_button(button):
			no_button = false
			dispatched += _gml_input_perform_mouse_event(row, mouse_events, button - 1)
	for button in [1, 2, 3]:
		if gml_mouse_check_button_pressed(button):
			no_button = false
			dispatched += _gml_input_perform_mouse_event(row, mouse_events, button + 3)
	for button in [1, 2, 3]:
		if gml_mouse_check_button_released(button):
			dispatched += _gml_input_perform_mouse_event(row, mouse_events, button + 6)
	if no_button:
		dispatched += _gml_input_perform_mouse_event(row, mouse_events, 3)
	if not was_over:
		inst.set_meta("_gml_mouse_over", true)
		dispatched += _gml_input_perform_mouse_event(row, mouse_events, 10)
	return dispatched


static func _gml_input_mouse_test_needed(mouse_events):
	# Whether any of the instance's mouse events could run this step; the
	# hit test is skipped otherwise. Mouse Enter/Leave and <No Button>
	# need it every step.
	for event_num in [3, 10, 11]:
		if mouse_events.has(event_num):
			return true
	for button in [1, 2, 3]:
		if mouse_events.has(button - 1) and gml_mouse_check_button(button):
			return true
		if mouse_events.has(button + 3) and gml_mouse_check_button_pressed(button):
			return true
		if mouse_events.has(button + 6) and gml_mouse_check_button_released(button):
			return true
	return false


static func _gml_input_mouse_over_instance(inst):
	# Like GameMaker, the mouse position in the room (through the views, as
	# window_views_mouse_get_x/y report it) is tested against the
	# instance's collision mask. Instances with their own hit test keep it.
	var entry = _gml_instance_entry(inst)
	if entry == null or inst.has_method("_gm_input_contains_point") or inst is Control or inst.has_meta("gamemaker_collision_radius"):
		return _gml_input_instance_contains_mouse(inst)
	var hit = gml_collision_point(
		inst,
		gml_window_views_mouse_get_x(),
		gml_window_views_mouse_get_y(),
		entry["handle"],
		true,
		false
	)
	return gml_handle_is_valid(hit)


static func _gml_input_perform_mouse_event(row, mouse_events, event_num):
	if not mouse_events.has(event_num):
		return 0
	return _gml_input_perform(row, mouse_events[event_num])


static func _gml_input_dispatch_gestures(table):
	var dispatched = 0
	for row in table:
		var gesture_events = row["events"].get(13, {})
		for event_num in gesture_events.keys():
			var binding = gesture_events[event_num]
			if _gml_input_gesture_event_matches(row["instance"], event_num, binding):
				dispatched += _gml_input_perform(row, binding)
	return dispatched


static func _gml_input_instance_contains_mouse(inst):
	# GameMaker runs an instance's mouse events while the mouse (mouse_x and
	# mouse_y, in room coordinates) is over the instance's collision mask,
	# tested precisely when the mask is precise. Instances without a sprite or
	# mask never get them.
	if inst == null:
		return false
	var mouse_room_position = _gml_mouse_room_position()
	if inst.has_method("_gm_input_contains_point"):
		return bool(inst.call("_gm_input_contains_point", mouse_room_position.x, mouse_room_position.y))
	if inst is Control:
		return inst.get_global_rect().has_point(mouse_room_position)
	return _gml_collision_instance_contains_point(inst, mouse_room_position.x, mouse_room_position.y)


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
	var room_position = _gml_mouse_room_position()
	var window_position = _gml_display_window_mouse_position()
	if not result.has("posX"):
		result["posX"] = room_position.x
	if not result.has("posY"):
		result["posY"] = room_position.y
	if not result.has("rawposX"):
		result["rawposX"] = window_position.x
	if not result.has("rawposY"):
		result["rawposY"] = window_position.y
	var gui_position = _gml_mouse_room_to_gui(_gml_input_mouse_position)
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
	var room_position = _gml_view_viewport_to_room(event.position)
	var window_position = _gml_display_viewport_to_window_transform() * event.position
	var payload = {
		"gesture": 0,
		"touch": int(event.index),
		"posX": room_position.x,
		"posY": room_position.y,
		"rawposX": window_position.x,
		"rawposY": window_position.y,
		"name": str(gesture_name),
	}
	var gui_position = _gml_mouse_room_to_gui(event.position)
	payload["guiposX"] = gui_position.x
	payload["guiposY"] = gui_position.y
	return payload
