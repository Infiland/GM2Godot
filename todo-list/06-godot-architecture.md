# Godot Architecture Checklist

This file tracks the Godot-side architecture needed for high-fidelity generated projects.

## Generated Project Structure

- [x] Generate stable project folders such as `sprites/`, `sounds/`, `fonts/`, `objects/`, `rooms/`, and `gm2godot/`.
- [x] Generate `project.godot` main scene setting.
- [x] Generate runtime and registry files under `gm2godot/`.
- [ ] Standardize generated paths to Godot-friendly `snake_case` while preserving original GameMaker names in metadata.
- [ ] Avoid case-only path differences for exported PCK compatibility.
- [ ] Add deterministic resource path, scene ID, and ext_resource ID rules.
- [ ] Generate a compatibility manifest as `.tres`, JSON, or both.
- [ ] Add `.gdignore` only where resources must not be imported.

## Recommended Runtime Managers

- [ ] `GMRuntime` manager for global compatibility state.
- [ ] `GMAssets` manager for asset IDs, names, paths, and dynamic resources.
- [ ] `GMRooms` manager for room order, transitions, persistent rooms, and room mutation.
- [ ] `GMInstances` manager for instance IDs, object groups, parent queries, lifecycle, and activation.
- [ ] `GMEvents` scheduler for Create, Step, Draw, Collision, Async, Destroy, Clean Up, and user events.
- [ ] `GMDraw` manager for draw state, surfaces, application surface, GUI draw, and renderer backend.
- [ ] `GMInput` manager for polling, events, gamepads, gestures, and per-step pressed/released state.
- [ ] `GMAudio` manager for channels, emitters, listeners, buses, and async audio callbacks.
- [ ] `GMAsync` manager for HTTP, files, dialogs, platform hooks, and `async_load` maps.
- [ ] `GMPlatform` manager for optional plugins and target-platform service bridges.

## Scenes And Nodes

- [x] Rooms become `.tscn` scenes.
- [x] Objects become `.tscn` scenes and `.gd` scripts.
- [x] Sprites become scenes/resources with `Sprite2D` or `AnimatedSprite2D` behavior in many cases.
- [ ] Use a custom `GMRoom extends Node2D` or equivalent room root consistently.
- [ ] Use deterministic room child hierarchy matching GameMaker layer/depth order.
- [ ] Use `CanvasLayer` for GUI layers and draw GUI behavior.
- [ ] Use `TileMapLayer` or Godot 4 equivalent for tile layers where compatible.
- [ ] Use `Parallax2D`/background controllers for scrolling/tiled backgrounds where compatible.
- [ ] Use `Path2D`/`Curve2D` for converted paths where compatible.
- [ ] Use `AnimationPlayer`, `Animation`, and `AnimationLibrary` for sequences where compatible.
- [ ] Use generated runtime schedulers when native Godot nodes would change GameMaker semantics.

## Resource And Asset Loading

- [x] Use `res://` resource paths for generated project assets.
- [x] Use copied/imported files for images, sounds, fonts, and shaders.
- [x] Use runtime registries for many asset lookups.
- [ ] Use `preload()` for static generated dependencies where stable.
- [ ] Use `load()` or `ResourceLoader.load()` for dynamic lookups through runtime registry.
- [ ] Use `user://` only for writable runtime save/config/generated-at-runtime files.
- [ ] Keep generated assets near related scenes where practical.
- [ ] Document which generated files users may safely edit.
- [ ] Add source metadata to generated resources for traceability.

## GDScript Generation

- [x] Generate GDScript for objects, scripts, rooms, and runtime helpers.
- [x] Use runtime helper calls to emulate many GML operations.
- [ ] Add generated source maps and comments linking GDScript back to GML file/event/line.
- [ ] Add deterministic formatting rules.
- [ ] Add headless Godot parser validation.
- [ ] Prefer typed GDScript in runtime internals where it does not hurt GML dynamic compatibility.
- [ ] Use `Variant` and dictionary-backed dynamic fields for GML dynamic variables.
- [ ] Avoid relying on unordered dictionary iteration in generated output.
- [ ] Generate safe identifiers for reserved words and invalid Godot names.
- [ ] Add compatibility wrappers for integer division, modulo, truthiness, arrays, dictionaries, and reference/value behavior.

## Event Architecture

- [x] Some Godot callbacks are generated directly, such as `_ready`, `_process`, `_physics_process`, `_draw`, and `_exit_tree` mappings.
- [ ] Centralize event order in `GMEvents` instead of relying only on Godot callback order.
- [ ] Use Godot `_process` as a frame pump, not as the final GameMaker Step semantic.
- [ ] Use `_physics_process` carefully because GameMaker Begin Step is not identical to Godot fixed physics order.
- [ ] Wrap Godot signals such as `body_entered`, `area_entered`, `request_completed`, `animation_finished`, and `timeout` into deterministic GameMaker event queues.
- [ ] Add event trace logging for debugging compatibility.

## Rendering Architecture

- [x] Use Godot `CanvasItem` draw APIs for many draw functions.
- [x] Use sprite nodes for normal sprite display.
- [x] Use basic surface emulation.
- [ ] Decide renderer backend per project or per room: node-rendered, canvas draw manager, or high-fidelity surface/viewport renderer.
- [ ] Use `queue_redraw()` consistently when GameMaker draw state requires redraw.
- [ ] Use `SubViewport` and `ViewportTexture` for surfaces where needed.
- [ ] Use `BackBufferCopy` or viewport passes for backbuffer-style effects.
- [ ] Use `ShaderMaterial` with `canvas_item` shaders for GameMaker shader mappings.
- [ ] Preserve texture filtering, repeat, mipmap, blend, and pixel-perfect settings.
- [ ] Preserve GameMaker color encoding and alpha behavior.

## Collision And Physics Architecture

- [x] Implement query-style collision compatibility subset.
- [x] Implement physics compatibility subset using Godot 2D primitives.
- [ ] Decide exact-mask custom collision backend versus Godot-native body/area backend per project.
- [ ] Use `Area2D` for overlap events where compatible.
- [ ] Use `PhysicsDirectSpaceState2D` for point/rectangle/circle/line query APIs where compatible.
- [ ] Avoid changing GameMaker semantics by overusing `move_and_slide()` or Godot body callbacks.
- [ ] Generate collision layer/mask names and mapping docs.
- [ ] Generate direct shape dimensions rather than scaling collision shapes where possible.
- [ ] Add pixel-perfect mask data backend for precise collision projects.

## Audio Architecture

- [x] Use `AudioStreamPlayer` for non-positional audio playback subset.
- [x] Generate audio buses for audio groups.
- [ ] Pool audio players to model GameMaker sound handles/channels.
- [ ] Use `AudioStreamPlayer2D` for positional audio where needed.
- [ ] Use `AudioServer` and bus effects for group/effect behavior.
- [ ] Preserve loop, pitch, gain, group, paused, and stopped state per sound handle.
- [ ] Integrate audio async callbacks through `GMAsync`.

## File, Buffer, Network Architecture

- [x] Use Godot file APIs for runtime file helpers.
- [x] Use PackedByteArray-like buffer runtime behavior.
- [x] Use Godot TCP/UDP primitives for networking subset.
- [ ] Use `FileAccess` and `DirAccess` with explicit sandbox path mapping.
- [ ] Use `PackedByteArray` with explicit endian/alignment helpers for all buffer operations.
- [ ] Use `HTTPRequest` or `HTTPClient` with a deterministic async event queue for HTTP.
- [ ] Use `StreamPeerTCP`, `TCPServer`, `PacketPeerUDP`, and `WebSocketPeer` wrappers with GameMaker packet/event semantics.
- [ ] Document that Godot multiplayer APIs are not a direct replacement for GameMaker socket APIs.

## Platform Services

- [x] Provide platform hook framework and explicit unsupported behavior.
- [ ] Add optional Godot plugins/GDExtensions for Steam, IAP, ads, cloud, achievements, leaderboards, analytics, mobile permissions, and web JS bridge.
- [ ] Add target-platform export preset checks.
- [ ] Add permission/capability generation for mobile and web targets.
- [ ] Add HTML5 storage, browser, URL, and CORS compatibility notes.

## Validation

- [ ] Open generated project in target Godot version headlessly.
- [ ] Confirm all imports complete without missing resources.
- [ ] Parse all generated GDScript.
- [ ] Load all generated scenes.
- [ ] Run room startup order tests.
- [ ] Run event-order tests.
- [ ] Run draw-order/depth tests.
- [ ] Run collision mask tests.
- [ ] Run alarm/timeline/async ordering tests.
- [ ] Run surface/shader compatibility tests.
- [ ] Run export checks for desktop, web, and mobile targets where feasible.
