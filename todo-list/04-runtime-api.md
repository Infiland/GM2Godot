# Runtime API Checklist

This file tracks the generated GML compatibility runtime needed inside Godot.

## Runtime Packaging

- [x] Generate `res://gm2godot/gml_runtime.gd` by concatenating ordered GDScript runtime segments.
- [x] Generate `res://gm2godot/gml_asset_registry.gd`.
- [x] Generate script and path registries where needed.
- [x] Preload runtime helpers in generated scripts.
- [ ] Add explicit runtime segment dependency declarations.
- [ ] Test for duplicate functions/constants across runtime segments.
- [ ] Add generated runtime function index from manifest API name to segment, test, status, and docs URL.
- [ ] Consider autoload runtime managers for instance, room, draw, input, audio, async, and compatibility state.

## Foundation And Types

- [x] GML undefined wrapper.
- [x] Pointer/handle wrappers.
- [x] Method wrappers.
- [x] Exception helpers.
- [x] Global state storage.
- [x] Instance registration and lookup.
- [x] Asset registry lookup.
- [ ] Full GameMaker handle reuse semantics.
- [ ] Full pointer/address compatibility policy.
- [ ] Leak tracking for dynamic handles such as DS, buffers, surfaces, time sources, particles, and audio.

## Math, Numbers, Strings, Arrays, Structs

- [x] Maths and numbers compatibility subset.
- [x] Random helpers compatibility subset.
- [x] Array helpers.
- [x] Struct helpers.
- [x] Variable helpers.
- [x] Static/type/clone/hash helpers.
- [x] String helpers compatibility subset.
- [ ] Dedicated string conformance tests for Unicode, bytes, search, copy, delete, insert, replace, and conversion edge cases.
- [ ] Exact random determinism compatibility.
- [ ] Exact GameMaker date/time numeric encoding compatibility.
- [ ] Exact degree/radian behavior for all trig APIs.

## Data Structures

- [x] DS list create/destroy/basic operations.
- [x] DS stack create/destroy/basic operations.
- [x] DS queue create/destroy/basic operations.
- [x] DS priority create/destroy/basic operations.
- [x] DS map create/destroy/basic operations.
- [x] DS grid create/destroy/basic operations.
- [x] DS accessors integrate with transpiled accessors.
- [ ] Full DS serialization read/write parity.
- [ ] Full nested DS marking and JSON conversion behavior.
- [ ] Full destroyed-handle and handle-reuse behavior.
- [ ] Full sort/shuffle/find behavior for every DS type.

## Files, INI, JSON, Buffers

- [x] File, path, INI, and JSON runtime segment.
- [x] Buffer create/read/write/seek core operations.
- [x] Buffer save/load/base64/hash subset.
- [x] Runtime files use Godot `user://` where appropriate.
- [ ] Full GameMaker sandbox path behavior.
- [ ] Full included file path behavior.
- [ ] Full binary buffer alignment and endianness conformance.
- [ ] Full buffer compression APIs.
- [ ] Full buffer async save/load dispatch.
- [ ] Full file dialogs and file picker APIs.

## Networking, HTTP, Async

- [x] Async HTTP bridge.
- [x] TCP/UDP networking subset using Godot networking primitives.
- [x] Frame-polled networking event collection.
- [ ] Full WebSocket creation and dispatch behavior.
- [ ] UDP broadcast support.
- [ ] Exact packet framing and buffer behavior.
- [ ] HTTP headers/status/result map compatibility.
- [ ] HTML5 CORS and browser limitations documentation.
- [ ] Deterministic async event queue order.
- [ ] Async dispatch to all listening instances.
- [ ] Full `async_load` DS map lifecycle.

## Audio

- [x] Non-positional playback through `AudioStreamPlayer`.
- [x] Audio handle lifecycle subset.
- [x] Stop, pause, resume, is-playing, gain, pitch, and global volume subset.
- [x] Legacy `sound_*` aliases subset.
- [ ] Audio emitters.
- [ ] Audio listeners.
- [ ] 2D/3D falloff.
- [ ] Streaming music semantics.
- [ ] Audio queues.
- [ ] Audio buffers.
- [ ] Audio recording.
- [ ] Audio sync groups.
- [ ] Async audio event payloads.
- [ ] Full audio group load/unload/preload behavior.

## Drawing, GPU, Surfaces

- [x] Draw context and draw state subset.
- [x] Basic forms draw subset.
- [x] Sprite draw subset.
- [x] Text draw subset.
- [x] Tile/basic primitive draw subset.
- [x] GPU/draw state subset.
- [x] Shader helper subset.
- [x] Surface handle, size, free, target, draw, save subset.
- [ ] Exact application surface lifecycle.
- [ ] Surface volatility/lost surface behavior.
- [ ] Surface target stack parity.
- [ ] Surface depth/stencil/format variants.
- [ ] Surface-to-sprite APIs.
- [ ] Full blend mode and separate alpha blend mode behavior.
- [ ] Full GPU state push/pop, z-test/write, culling, filtering, repeat, scissor, stencil, alpha test, and color write behavior.
- [ ] Full primitive and vertex buffer APIs.
- [ ] Full lighting/depth/stencil APIs.
- [ ] Full video playback drawing APIs.

## Sprites, Textures, Texture Groups

- [ ] Full sprite info APIs.
- [ ] Full sprite dynamic add/delete/replace APIs.
- [ ] Full sprite collision APIs.
- [ ] Full texture handle APIs.
- [ ] Full texture prefetch and flush APIs.
- [ ] Full texture group runtime behavior.
- [ ] Full texture UV/cropping behavior.
- [ ] Full skeletal sprite APIs.
- [ ] Full sprite broadcast message dispatch.

## Cameras, Display, Window

- [x] Camera/display core subset.
- [x] Legacy view arrays subset.
- [x] GUI size subset.
- [ ] Full camera create/destroy/set position/size/angle/projection APIs.
- [ ] Full documented view arrays and view slot behavior.
- [ ] Multiple active views and viewports.
- [ ] View surfaces.
- [ ] Camera follow-object behavior with borders and speeds.
- [ ] Window size/position/fullscreen APIs.
- [ ] Display orientation/DPI APIs.
- [ ] Screen save/GIF APIs.

## Input

- [x] Keyboard polling subset.
- [x] Mouse polling subset.
- [x] Gamepad polling subset.
- [ ] Full pressed/released state timing.
- [ ] Full input event dispatch.
- [ ] GUI mouse coordinate conversions.
- [ ] Gamepad connected/vibration parity.
- [ ] Touch/device APIs.
- [ ] Gesture APIs and event payloads.
- [ ] Input simulation caveats.
- [ ] IME/text input/dialog input support.

## Room And Game Flow

- [x] Room enter scene runtime hook.
- [x] Room goto/restart/next/previous subset.
- [x] Project main scene setting.
- [x] Time and alarm helper subset.
- [ ] Full persistent room behavior.
- [ ] Full persistent instance behavior.
- [ ] Full runtime room mutation APIs.
- [ ] Full room creation code execution.
- [ ] Full instance creation code execution.
- [ ] Full room speed/fps timing model.
- [ ] Full room start/end/game start/game end ordering.

## Movement, Collision, Paths

- [x] Motion variable sync subset.
- [x] Motion helper subset.
- [x] Path registry and path-following subset.
- [x] Collision query subset.
- [ ] Exact mask-based collision checks.
- [ ] Pixel-perfect collision masks.
- [ ] Parent object collision behavior.
- [ ] Collision event pair scheduling.
- [ ] Tilemap collision integration.
- [ ] `move_contact_*`, `move_bounce_*`, and `move_random` full parity.
- [ ] MP grid full path planning behavior.
- [ ] Real path resources and exact interpolation/orientation/point speed behavior.

## Physics

- [x] Physics fixture binding/forces/joints subset.
- [ ] Full physics world settings.
- [ ] Full gravity and pixels-to-meters behavior.
- [ ] Full fixtures and shapes.
- [ ] Full sensors and collision filters.
- [ ] Full damping, density, restitution, friction.
- [ ] Full prismatic, pulley, gear, weld, rope, wheel, and friction joints.
- [ ] Physics particles.
- [ ] Physics collision callbacks.
- [ ] Physics debug draw.
- [ ] Compatibility policy for Godot physics divergence from GameMaker/Box2D.

## Particles, Sequences, Timelines, Flex Panels

- [x] Particle compatibility subset.
- [x] Sequence/timeline compatibility subset.
- [x] Flex panel compatibility subset.
- [ ] Full authored particle system asset conversion.
- [ ] Full `part_*` and effect APIs.
- [ ] Full sequence asset conversion.
- [ ] Full sequence track/keyframe authoring APIs.
- [ ] Full sequence object override/get-object APIs.
- [ ] Full timeline asset conversion and frame moment scheduler.
- [ ] Full Yoga-equivalent flex panel layout semantics.

## OS, Debug, GC, Platform Services

- [x] OS/debug/GC helper subset.
- [x] Platform service hook framework.
- [x] Unsupported platform hooks fail explicitly or return controlled fallbacks.
- [ ] Full callstack/error handler behavior.
- [ ] Full modal dialog behavior.
- [ ] Full weak reference behavior.
- [ ] Full OS/device/media APIs.
- [ ] Microphone/video/device sensor/permission APIs.
- [ ] Steam, IAP, cloud, achievements, leaderboards, ads, analytics, push notifications, Xbox/UWP, HTML5, console, mobile, and live wallpaper SDK integrations.
- [ ] Native external calls through GDExtension/plugin bindings.
