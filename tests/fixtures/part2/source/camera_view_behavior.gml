// Fixture: legacy view arrays synced with camera helpers and GUI display size.
var cam = camera_create_view(0, 0, 320, 180, 0, noone, -1, -1, 0, 0);
view_camera[0] = cam;
view_enabled = true;
view_visible[0] = true;

view_xview[0] = 100;
view_yview[0] = 200;
camera_set_view_pos(cam, 300, 400);
camera_set_view_size(cam, 320, 180);
camera_set_view_angle(cam, 15);

display_set_gui_size(800, 450);
global.fixture_camera = [
    camera_get_view_x(cam),
    camera_get_view_y(cam),
    display_get_gui_width(),
    display_get_gui_height(),
];
