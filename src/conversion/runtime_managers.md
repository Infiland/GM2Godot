# GM2Godot Runtime Managers

Converted projects keep `res://gm2godot/gml_runtime.gd` as the compatibility facade so generated scripts can continue to call `GMRuntime.gml_*` helpers. New generated projects also receive deterministic autoload managers under `res://gm2godot/managers/`.

The generated autoloads are:

- `GMRuntime`: root registry and compatibility lifecycle.
- `GMAssets`: asset registry, texture groups, audio groups, and dynamic assets.
- `GMRooms`: room order, current room, transitions, and layers.
- `GMInstances`: live instances, handles, object indices, and creation order.
- `GMEvents`: frame events, alarms, timelines, and sequences. This manager owns the generated `_process` frame pump: its `_ready()` calls `GMRuntime.gml_event_scheduler_pump_attach()` and every frame calls `GMRuntime.gml_event_scheduler_game_frame(delta)`, which runs one GameMaker step in GameMaker's phase order (including keyboard and mouse events), so Step phases do not depend on individual node callback order.
- `GMDraw`: draw state, surfaces, shader cache, and texture-group state. This manager owns the generated draw-phase pump for Pre Draw, Draw Begin, Draw, Draw End, Post Draw, and GUI phases. It skips the frame when `GMRuntime.gml_event_scheduler_frame_drawable()` is false, because GameMaker does not draw a step that ended with a room change, `game_restart()` or `game_end()`.
- `GMInput`: keyboard, mouse, gamepad, and gesture state. This manager owns the generated `_input(event)` capture hook, which translates Godot keys and mouse buttons into GameMaker key and button codes; converted object scripts expose `_gm_input_event_bindings()` (including the input events inherited from parent objects) plus `_gm_input_*` methods, which `GMRuntime.gml_input_dispatch_frame()` runs in GameMaker's keyboard and mouse event order.
- `GMAudio`: audio instances, groups, emitters, and listeners.
- `GMAsync`: async_load, HTTP, buffer, networking, platform, and extension queues. This manager owns the generated async queue pump (`GMRuntime.gml_async_frame_pump()`) so callback delivery is FIFO and `async_load` is scoped to each Async event. While the `GMEvents` frame pump is attached, Async events are delivered in the step's async phase instead.
- `GMPlatform`: service hooks, extension callback schemas, OS/debug, and GC state.

`project.godot` registers the managers in that order in `[autoload]`. Godot loads autoload nodes before the main scene and evaluates them in project order, which gives the runtime a stable startup sequence for later event, room, draw, input, audio, async, and platform migrations.

The CLI static report pipeline writes `gm2godot/platform_capability_report.json` and `.md`. These reports list target-specific permission, export-preset, and optional plugin checks for browser hooks, mobile microphone/camera/sensor APIs, Steam, IAP, cloud, push notifications, Xbox Live, and live wallpaper integrations.

Trustworthy successful and partial conversions receive `gm2godot/conversion_manifest.json`, a format-v2 record of the generated output with the conversion outcome, named requested/executed/completed/skipped/failed steps, resource source paths, generated Godot paths, source-map files, file hashes, and stable-suffix collision diagnostics. A partial canonical requires every requested converter step to complete; its partiality comes from skipped or failed resources. In the step ledger, completed/skipped/failed partition requested work, completed and failed imply execution, and a step interrupted by cancellation is both executed and skipped.

After destination preflight succeeds, every terminal attempt also writes format-v1 `gm2godot/conversion_attempt.json`, including failed and cancelled attempts. Unsafe destinations refused during preflight are never modified. Attempt state and canonical trust are independent because a late failure or cancellation can be observed after a trustworthy canonical commit. The `canonical_manifest` record has exactly three combinations: `updated=true`, `status=updated`, `current_output=verified`, and the expected digest for a new canonical in this generation; `updated=false`, `status=preserved`, `current_output=unverified`, and a digest for an existing regular file retained by this generation; or `updated=false`, `status=absent`, `current_output=unavailable`, and `sha256=null`. Before either public file changes, GM2Godot durably records the complete prior and desired pair, then replaces the attempt and optional manifest and switches one persistent generation pointer. Recovery under a project-local operating-system lock restores the prior pair before that switch or verifies the new pair afterward. Consumers must still verify `canonical_manifest.sha256` against later replacement or corruption, but a mismatch is rejected recovery state rather than a normal interrupted-publication result. Status is transaction-relative, not a whole-run provenance marker: a preserved file may come from an earlier run or an earlier phase of the same invocation. Consumers must inspect the latest attempt before treating it as a description of the destination.

`GM2Godot validate` can write `gm2godot/godot_validation_report.json` by loading generated `.gd`, `.tscn`, `.tres`, and `.gdshader` resources through headless Godot when `GODOT_BIN` or `--godot-bin` is available.

Generated projects also receive `gm2godot/architecture_policy.json`. The report records the selected room root, layer/depth, renderer, collision, audio, file/buffer/network, runtime-manager, and signal-queue policies described in `src/conversion/godot_architecture_policy.md`.

The `GMRuntime` autoload records each manager in `manager_registry_snapshot()` and exposes `manager_order()`. Each manager owns named state buckets so future runtime slices can move domain state out of the static compatibility facade without changing generated GML helper call sites.

Collision events are dispatched by the central scheduler after motion/path updates and before End Step, matching the relevant GameMaker event-order window: https://manual.gamemaker.io/lts/en/The_Asset_Editors/Object_Properties/Event_Order.htm. Imported Precise and Precise Per Frame sprites contribute alpha-derived pixel rectangles; frame, origin, scale, rotation and sprite/image changes select and transform the active polygons. Collision events, motion checks and query APIs use those polygons when precise behavior applies, while non-precise queries use the transformed generated bounds. A conversion-time `GM2GD-SPRITE-PRECISE-MASK-FALLBACK` diagnostic identifies source masks that cannot be represented exactly. Runtime-authored masks, `mask_index`, skeletal/tile masks and physics fixtures remain separate compatibility areas. The generated shapes follow Godot 4.7.2 `CollisionShape2D`: https://docs.godotengine.org/en/4.7/classes/class_collisionshape2d.html.

## Compatibility

The manager layer is enabled by default when `write_gml_runtime()` runs and `project.godot` exists. Existing generated scripts remain compatible because they still preload and call `res://gm2godot/gml_runtime.gd`.

Projects can remove or override the generated `GM*` autoloads while keeping the static compatibility facade for tests or incremental migrations. New runtime code should prefer manager `state_bucket()` ownership for persistent domain state and keep `GMRuntime.gml_*` helpers as stable call-site facades.

## Event Order And Deviations

GameMaker event order is coordinated through `GMEvents` and generated object
methods rather than relying on individual Godot node callback order. The runtime
dispatches Create/room-enter behavior during room scene setup, then every frame
runs one GameMaker step in the order of the GameMaker runner
(`GML_EVENT_PHASE_ORDER`): input latch, `xprevious`/`yprevious` and image
animation with Animation End, Begin Step, Async events, timelines, time sources,
alarms, keyboard events, mouse events, sequences, Step, motion/paths, Outside
Room/Intersect Boundary/view events, collisions and End Step, followed by the
draw phases. Keyboard and mouse pressed/released states are latched at the start
of the step and stay valid until the next step, including in Draw and Draw GUI.

`room_goto()`, `room_goto_next()`, `room_goto_previous()`, `room_restart()`,
`game_restart()` and `game_end()` only record the request while the frame pump
is attached. The current event finishes and that step is not drawn. No further
events run, apart from the Create, Destroy, Alarm and Other events of
persistent instances or of a persistent room: instances created after the
request get no Create event (generated Create code asks
`GMRuntime.gml_event_create_blocked()`), and `instance_destroy()` runs no
Destroy event.
The change happens before the next step; after a room switch the new room steps
and draws in the same frame. Without the frame pump (tests and tools that call
the static runtime directly) these functions act immediately and input edges
last until `gml_input_end_frame()`. Tests that depend on these phases should
assert the generated method names or manager queues rather than incidental
node order.

A step keeps one list of live instances in creation order, carried over from
the previous step: instances created during a phase join it before the next
phase, destroyed instances are skipped. Which events, alarms, input bindings
and Other events an object has is looked up once per object script. The
scheduler records the events it runs (`gml_event_scheduler_trace()`) and the
input runtime its input events (`gml_input_dispatch_trace()`) only while
`gml_event_scheduler_set_tracing(true)` is in effect; both keep only their
latest records.

Supported authored sequences are normalized into managed descriptors and advanced
by `GMEvents` using either frames-per-second or frames-per-game-frame speed.
Track/key order, assign/linear interpolation, nested state, mapped audio effects,
moments, broadcasts, and legacy timeline GML moments are evaluated
deterministically. Unsupported track/key/effect/action types make the source
resource partial with a source-linked diagnostic; the runtime never guesses their
semantics.

Known semantic differences must be documented where they are introduced. Current
examples include precise pixel collision masks falling back to Godot collision
shape bounds, shader-language differences between GLSL ES and Godot shaders,
platform-service calls routed through `GMPlatform`, and target permissions that
cannot be inferred from GameMaker options alone.

## State, Globals, And Persistence

Runtime state has three ownership levels:

- Static compatibility state in `gml_runtime.gd` for helper functions that are
  still called directly by generated scripts.
- Autoload manager state buckets for generated projects, exposed through stable
  manager names such as `GMAssets`, `GMRooms`, `GMInstances`, `GMEvents`,
  `GMDraw`, `GMInput`, `GMAudio`, `GMAsync`, and `GMPlatform`.
- Scene-local room/object state for generated room scenes and object instances.

Global variables, asset ids, handles, room order, persistent instances, async
queues, and audio handles must survive the same transitions that GameMaker keeps
alive. Room-local layers, transient draw state, one-frame input edges, collision
pairs, and non-persistent instances should be reset at the documented frame or
room boundary. Add regression tests whenever a runtime change moves state between
these levels.
