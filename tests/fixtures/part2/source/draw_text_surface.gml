// Fixture: draw event text plus offscreen surface target.
draw_set_color(c_white);
draw_set_alpha(1);
draw_text(8, 8, "score " + string(global.score));

if (!surface_exists(global.fixture_surface)) {
    global.fixture_surface = surface_create(32, 16);
}

surface_set_target(global.fixture_surface);
draw_clear(c_black);
draw_text(2, 2, "ok");
surface_reset_target();
draw_surface_ext(global.fixture_surface, 0, 0, 1, 1, 0, c_white, 1);
