// Fixture: multi-view viewport compatibility state and diagnostics.
view_enabled = true;
view_visible[0] = true;
view_visible[1] = true;

view_set_visible(0, true);
view_set_visible(1, true);
view_set_xport(1, 400);
view_set_yport(1, 20);
view_set_wport(1, 640);
view_set_hport(1, 360);

window_mouse_set(410, 120);
var view_mouse_x = window_view_mouse_get_x(1);
var view_mouse_y = window_view_mouse_get_y(1);
display_set_gui_size(800, 450);
var gui_mouse_x = device_mouse_x_to_gui(0);
var gui_mouse_y = device_mouse_y_to_gui(0);

var surf = surface_create(64, 64);
view_set_surface_id(1, surf);

global.fixture_multiview = [
    view_get_visible(0),
    view_get_visible(1),
    view_get_xport(1),
    view_get_yport(1),
    view_get_wport(1),
    view_get_hport(1),
    view_mouse_x,
    view_mouse_y,
    gui_mouse_x,
    gui_mouse_y,
    view_get_surface_id(1),
];
