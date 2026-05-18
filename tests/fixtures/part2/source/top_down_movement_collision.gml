// Fixture: top-down movement with blocking collision.
// Object o_player Create event.
move_speed = 4;
motion_set(0, move_speed);

// Object o_player Step event.
var next_x = x + hspeed;
if (place_meeting(next_x, y, o_wall)) {
    move_contact_solid(0, 64);
    move_bounce_solid(true);
} else {
    x = next_x;
}

var hit_wall = collision_rectangle(x - 8, y - 8, x + 8, y + 8, o_wall, false, true);
global.fixture_result = hit_wall != noone && speed == move_speed;
