/// Fixture: resource matrix coverage for Milestone 7 issue #610.
#macro MATRIX_SPEED 4

shader_set(shd_matrix);
path_start(path_patrol, MATRIX_SPEED, path_action_stop, false);
timeline_index = tl_intro;
audio_play_sound(snd_click, 0, false);
physics_apply_impulse(x, y, 1, 0);
part_system_create();
draw_set_color(c_white);
draw_text(8, 8, "matrix");
