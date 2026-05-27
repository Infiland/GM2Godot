# Part 2 Full-Game Compatibility Fixtures

This directory tracks the staged compatibility fixtures for issue #518. Each fixture has a minimal GameMaker source expectation in `source/`, manifest entries for the runtime/API surface it exercises, and one or more headless Godot assertion paths in `fixtures.json`.

The fixture catalog covers the required P0 buckets:

- `movement_collisions`: top-down movement, instance registration, blocking collision, and collision query assertions.
- `multi_room_transitions`: room order, room restart/goto helpers, room metadata, and persistent lifecycle assertions.
- `draw_text_surface`: draw context, text drawing, surface targets, copy/draw/free behavior, and application surface state.
- `audio_playback`: imported sound metadata, modern audio helpers, and legacy sound aliases.
- `ds_collections_save_files`: DS lists/maps/grids, text files, included file mapping, INI persistence, and JSON encoding/decoding.
- `async_http`: HTTP GET/POST/custom requests, async event dispatch, and async buffer save.
- `camera_view`: camera helper state, legacy view array synchronization, Camera2D transforms, and GUI display sizing.
- `multi_view_viewports`: multi-view viewport rectangles, view mouse coordinate conversion, view-surface state, and backend diagnostics.

Unsupported APIs discovered by a fixture must be added to that fixture's `unsupported_api_issue_refs` list with the manifest API name and issue number. Empty lists mean the current fixture path did not encounter a new unsupported API.
