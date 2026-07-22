# GM2Godot Generated Godot Architecture Policy

This policy is generated into `gm2godot/architecture_policy.json` and mirrored in
`gm2godot/conversion_manifest.json` so conversion output records the backend
choices used for a project.

## Room And Layer Policy

- Rooms use `Node2D` roots with `res://gm2godot/gml_room_node.gd`.
- The first GameMaker `RoomOrderNodes` entry becomes `run/main_scene`.
- GameMaker layers become `Node2D` children with `z_index = -depth`.
- Every generated room has a `GMGUI` `CanvasLayer` reserved for Draw GUI phases.
- Tile layers use Godot 4 `TileMapLayer` when the source tile data can be decoded.
- Native Godot callbacks and signals do not define GameMaker event order; runtime
  managers queue and pump GameMaker phases.

## Backend Policy

- Renderer mode is selected from project features:
  - `godot_node_scene` for projects without explicit Draw or surface code.
  - `central_canvas_draw_manager` when Draw, shader, GPU state, or effect-layer
    code needs ordered `CanvasItem` dispatch.
  - `surface_viewport` when surface/application-surface APIs require a
    `SubViewport`/`ViewportTexture` path.
- Collision mode is selected from room, script, and sprite features:
  - `generated_bounds_idle` when no collision use is detected.
  - `generated_bounds_direct_queries` for GameMaker query-style collision APIs.
  - `godot_physics_world_bridge` when a GameMaker physics room is enabled.
  - Imported Precise and Precise Per Frame sprites use generated alpha-mask
    geometry shared by collision events, movement, and direct query helpers.
    Unsupported source masks emit a structured rectangle-fallback diagnostic.
- Audio uses pooled `AudioStreamPlayer`/`AudioStreamPlayer2D` nodes, audio buses,
  and `AudioServer` state through `GMAudio`; playback-ended signals are queued
  into `GMAsync`.
- File, buffer, HTTP, and socket work uses `FileAccess`, `DirAccess`,
  `PackedByteArray`, `HTTPRequest`/`HTTPClient`, `StreamPeerTCP`, `TCPServer`,
  `PacketPeerUDP`, and `WebSocketPeer` wrappers. Godot multiplayer is not treated
  as a direct replacement for GameMaker socket APIs.

## Signal Queue Policy

Signals that can affect GameMaker event order are recorded in runtime manager
metadata and queued through managers:

- `GMEvents`: collision, animation, and timer-style signals.
- `GMAsync`: HTTP completion, process-frame flushes, and audio playback-ended
  signals.

## Research Sources

- Godot autoloads: https://docs.godotengine.org/en/stable/getting_started/step_by_step/singletons_autoload.html
- Godot CanvasLayer: https://docs.godotengine.org/en/stable/tutorials/2d/canvas_layers.html
- Godot 4.7.1 CollisionShape2D: https://docs.godotengine.org/en/4.7/classes/class_collisionshape2d.html
- Godot 4.7.1 Transform2D: https://docs.godotengine.org/en/4.7/classes/class_transform2d.html
- Godot AudioServer: https://docs.godotengine.org/en/stable/classes/class_audioserver.html
- Godot HTTPRequest: https://docs.godotengine.org/en/stable/classes/class_httprequest.html
- GameMaker LTS collision masks: https://manual.gamemaker.io/lts/en/The_Asset_Editors/Sprites.htm
- GameMaker LTS event order: https://manual.gamemaker.io/lts/en/The_Asset_Editors/Object_Properties/Event_Order.htm
