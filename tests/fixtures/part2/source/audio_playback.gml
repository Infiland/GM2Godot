// Fixture: play, inspect, and stop an imported sound asset.
var sound_handle = audio_play_sound(snd_hit, 10, false, 0.5, 0, 1);
global.fixture_audio_started = audio_is_playing(snd_hit);
audio_sound_gain(sound_handle, 0.25, 0);
audio_sound_pitch(sound_handle, 1.25);
audio_stop_sound(sound_handle);
global.fixture_audio_stopped = !audio_is_playing(sound_handle);
