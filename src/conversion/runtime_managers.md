# GM2Godot Runtime Managers

Converted projects keep `res://gm2godot/gml_runtime.gd` as the compatibility facade so generated scripts can continue to call `GMRuntime.gml_*` helpers. New generated projects also receive deterministic autoload managers under `res://gm2godot/managers/`.

The generated autoloads are:

- `GMRuntime`: root registry and compatibility lifecycle.
- `GMAssets`: asset registry, texture groups, audio groups, and dynamic assets.
- `GMRooms`: room order, current room, transitions, and layers.
- `GMInstances`: live instances, handles, object indices, and creation order.
- `GMEvents`: frame events, alarms, timelines, and sequences.
- `GMDraw`: draw state, surfaces, shader cache, and texture-group state.
- `GMInput`: keyboard, mouse, gamepad, and gesture state.
- `GMAudio`: audio instances, groups, emitters, and listeners.
- `GMAsync`: async_load, HTTP, buffer, and networking queues.
- `GMPlatform`: service hooks, extension callback schemas, OS/debug, and GC state.

`project.godot` registers the managers in that order in `[autoload]`. Godot loads autoload nodes before the main scene and evaluates them in project order, which gives the runtime a stable startup sequence for later event, room, draw, input, audio, async, and platform migrations.

The `GMRuntime` autoload records each manager in `manager_registry_snapshot()` and exposes `manager_order()`. Each manager owns named state buckets so future runtime slices can move domain state out of the static compatibility facade without changing generated GML helper call sites.

## Compatibility

The manager layer is enabled by default when `write_gml_runtime()` runs and `project.godot` exists. Existing generated scripts remain compatible because they still preload and call `res://gm2godot/gml_runtime.gd`.

Projects can remove or override the generated `GM*` autoloads while keeping the static compatibility facade for tests or incremental migrations. New runtime code should prefer manager `state_bucket()` ownership for persistent domain state and keep `GMRuntime.gml_*` helpers as stable call-site facades.
