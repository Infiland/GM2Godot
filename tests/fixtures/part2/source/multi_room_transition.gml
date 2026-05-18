// Fixture: ordered room transition with persistent controller lifecycle.
// Object o_controller Create event.
persistent = true;
global.fixture_events = ["create"];

// Object o_controller Room Start event.
array_push(global.fixture_events, "room_start:" + room_get_name(room));
if (room == r_one && room_exists(r_two)) {
    room_goto_next();
} else if (room == r_two) {
    room_restart();
    room_goto_previous();
}

// Object o_controller Room End event.
array_push(global.fixture_events, "room_end:" + room_get_name(room));
