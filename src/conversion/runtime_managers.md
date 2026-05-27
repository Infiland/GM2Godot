# GM2Godot Runtime Managers

Converted projects keep `res://gm2godot/gml_runtime.gd` as the compatibility facade so generated scripts can continue to call `GMRuntime.gml_*` helpers. New generated projects also receive deterministic autoload managers under `res://gm2godot/managers/`.

The generated autoloads are:

- `GMRuntime`: root registry and compatibility lifecycle.
- `GMAssets`: asset registry, texture groups, audio groups, and dynamic assets.
- `GMRooms`: room order, current room, transitions, and layers.
- `GMInstances`: live instances, handles, object indices, and creation order.
- `GMEvents`: frame events, alarms, timelines, and sequences. This manager owns the generated `_process` frame pump, dispatches queued GMInput events, calls `GMRuntime.gml_event_scheduler_frame()`, then clears one-frame input edges so Step phases do not depend on individual node callback order.
- `GMDraw`: draw state, surfaces, shader cache, and texture-group state. This manager owns the generated draw-phase pump for Pre Draw, Draw Begin, Draw, Draw End, Post Draw, and GUI phases.
- `GMInput`: keyboard, mouse, gamepad, and gesture state. This manager owns the generated `_input(event)` capture hook; converted object scripts expose `_gm_input_event_bindings()` plus `_gm_input_*` methods for deterministic frame dispatch.
- `GMAudio`: audio instances, groups, emitters, and listeners.
- `GMAsync`: async_load, HTTP, buffer, networking, platform, and extension queues. This manager owns the generated async queue pump so callback delivery is FIFO and `async_load` is scoped to each Async event.
- `GMPlatform`: service hooks, extension callback schemas, OS/debug, and GC state.

`project.godot` registers the managers in that order in `[autoload]`. Godot loads autoload nodes before the main scene and evaluates them in project order, which gives the runtime a stable startup sequence for later event, room, draw, input, audio, async, and platform migrations.

The CLI static report pipeline writes `gm2godot/platform_capability_report.json` and `.md`. These reports list target-specific permission, export-preset, and optional plugin checks for browser hooks, mobile microphone/camera/sensor APIs, Steam, IAP, cloud, push notifications, Xbox Live, and live wallpaper integrations.

Converted projects also receive `gm2godot/conversion_manifest.json`, a deterministic generated-output manifest with resource source paths, generated Godot paths, source-map files, file hashes, and diagnostics for path collisions that required stable generated suffixes. `GM2Godot validate` can write `gm2godot/godot_validation_report.json` by loading generated `.gd`, `.tscn`, `.tres`, and `.gdshader` resources through headless Godot when `GODOT_BIN` or `--godot-bin` is available.

The `GMRuntime` autoload records each manager in `manager_registry_snapshot()` and exposes `manager_order()`. Each manager owns named state buckets so future runtime slices can move domain state out of the static compatibility facade without changing generated GML helper call sites.

Collision events are dispatched by the central scheduler after motion/path updates and before End Step, matching the relevant GameMaker event-order window: https://manual.gamemaker.io/monthly/en/The_Asset_Editors/Object_Properties/Event_Order.htm. Dispatch uses generated Godot collision shape bounds, which aligns with Godot's 2D physics shape model: https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html. Pixel-perfect precise masks remain reported as a runtime fidelity limitation through the existing precise-collision warning path.

## Compatibility

The manager layer is enabled by default when `write_gml_runtime()` runs and `project.godot` exists. Existing generated scripts remain compatible because they still preload and call `res://gm2godot/gml_runtime.gd`.

Projects can remove or override the generated `GM*` autoloads while keeping the static compatibility facade for tests or incremental migrations. New runtime code should prefer manager `state_bucket()` ownership for persistent domain state and keep `GMRuntime.gml_*` helpers as stable call-site facades.
