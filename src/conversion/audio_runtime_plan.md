# GM2Godot Audio Runtime Plan

Issue #495 implements the 2D-neutral audio bridge first: converted sound assets resolve through the asset registry, each playback creates an independent `AudioStreamPlayer`, audio groups map to Godot buses, and sound handles can be stopped, paused, resumed, queried, and adjusted.

Remaining positional audio work should build on the same handle and asset-state model:

1. Positional emitters: represent GameMaker emitters as runtime handles backed by `AudioStreamPlayer2D` nodes, with emitter gain, pitch, velocity, and listener-mask state stored separately from sound-asset defaults.
2. Listeners: map active GameMaker listeners to generated `AudioListener2D` or camera-attached listener nodes, preserving listener masks where Godot can represent them and warning where a target lacks multi-listener support.
3. Falloff: translate GameMaker falloff reference, max distance, and rolloff factor into Godot 2D attenuation settings, with documented approximation for formulas that do not match directly.
4. Streaming music: mark long or streamed GameMaker sounds in asset metadata, prefer streamed Godot audio imports for those assets, and add tests that verify playback control without loading entire tracks into memory.
