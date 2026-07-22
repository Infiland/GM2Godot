# Assets And Project Import Checklist

This file tracks GameMaker project/resource data that the converter must eventually parse and preserve.

## Project Manifest And Global Data

- [x] Parse `.yyp` resource list enough to discover many assets.
- [x] Preserve room order for generated project main scene behavior.
- [x] Preserve many resource names and paths.
- [x] Preserve selected asset browser subfolders.
- [x] Generate selected Godot project settings.
- [x] Generate selected audio buses from GameMaker audio groups.
- [ ] Parse every `.yyp` field needed for project graph, folders/views, resource ordering, tags, configs, texture groups, audio groups, room order, included files, options, and extension references.
- [ ] Resolve resources by name, path, UUID, and resource type across all known schema versions.
- [ ] Parse GameMaker version/schema metadata and compatibility flags.
- [ ] Parse project configurations and per-config overrides.
- [ ] Parse target platform options for Windows, macOS, Linux, Web, iOS, Android, consoles, and UWP where present.
- [ ] Parse texture group settings as actionable import/runtime configuration.
- [ ] Parse audio group load/unload/preload settings as actionable import/runtime configuration.
- [ ] Parse resource tags and preserve them in generated metadata.
- [ ] Parse included file deployment rules.
- [ ] Parse extension metadata, options, files, constants, functions, macros, and platform implementations.
- [ ] Preserve source locations for diagnostics.

## Common `.yy` Handling

- [x] Parse lenient JSON-like `.yy` files in converter helpers.
- [x] Parse common `resourceType`, `resourceVersion`, and `name` fields in many converters.
- [x] Use `parent.path` metadata for subfolders in many converters.
- [ ] Tolerate and report future unknown fields consistently.
- [ ] Store parsed resource models before emitting Godot files.
- [ ] Add schema validation per resource type.
- [ ] Add malformed/missing `.yy` fixture tests.
- [ ] Track original source path and line/field for every diagnostic.

## Sprites

- [x] Static sprites.
- [x] Animated sprites/subimages.
- [x] Frame order.
- [x] Visible image layer composition.
- [x] Origin metadata.
- [x] Basic collision mask shape generation.
- [x] Playback speed and loop metadata.
- [x] Precise and precise-per-frame alpha masks.
- [ ] Bounding box modes exactly matching GameMaker.
- [ ] Nine-slice data.
- [ ] Sprite tags.
- [ ] Texture page and texture group behavior.
- [ ] Per-frame metadata beyond image order/duration.
- [ ] Spine/skeletal animation sprites.
- [ ] Sprite broadcast messages.
- [ ] Runtime sprite add/delete/replace APIs.
- [ ] Surface-to-sprite conversion.

## Sounds And Audio Groups

- [x] Copy common audio file types.
- [x] Preserve volume metadata.
- [x] Preserve audio group mapping metadata.
- [x] Generate audio bus layout.
- [ ] Compression format mapping.
- [ ] Sound type mapping: normal, background music, 3D, stream, and platform-specific variants.
- [ ] Preload behavior.
- [ ] Audio group load/unload behavior.
- [ ] Emitters and listeners referenced by code.
- [ ] Audio queues, buffers, recording, and sync groups.
- [ ] Async audio playback events.

## Fonts

- [x] Bundled TTF copying.
- [x] System font fallback.
- [x] Basic bold/italic/anti-aliasing metadata.
- [ ] Glyph ranges.
- [ ] Font texture group membership.
- [ ] SDF/MSDF settings.
- [ ] Sprite fonts.
- [ ] Runtime font add/delete APIs.
- [ ] Text measurement and wrapping parity.

## Paths

- [x] Parse path points.
- [x] Parse open/closed flag.
- [x] Parse precision.
- [x] Generate runtime path registry.
- [ ] Convert to Godot `Path2D` and `Curve2D` resources.
- [ ] Preserve smooth/straight interpolation.
- [ ] Preserve point speed.
- [ ] Preserve path orientation behavior.
- [ ] Runtime path creation/manipulation APIs.
- [ ] Path Ended event scheduling.

## Scripts

- [x] Convert modern script functions.
- [x] Convert pre-2.3-style GMS2 script bodies into wrappers where current GameMaker projects can still contain them.
- [x] Generate script registry.
- [x] Support multiple functions per script where parsed by the transpiler.
- [ ] Preserve documentation comments/source maps.
- [ ] Full macro/enum/config interaction across all scripts.
- [ ] Script asset variants supported by current GMS2+ project imports.

## Shaders

- [x] Copy/convert shader files into `.gdshader` with basic replacements.
- [ ] Full vertex shader translation.
- [ ] Full fragment shader translation.
- [ ] Attribute mapping.
- [ ] Varying mapping.
- [ ] Uniform mapping and runtime binding.
- [ ] Sampler/texture mapping.
- [ ] Precision qualifier handling.
- [ ] Multi-pass effect conversion.
- [ ] Shader compile validation through Godot headless.

## Rooms And Layers

- [x] Generate one Godot scene per room.
- [x] Preserve room order.
- [x] Preserve room size metadata.
- [x] Generate instance layers.
- [x] Generate background layer structure.
- [x] Generate tile layer structure for supported tile data.
- [x] Generate asset/effect/nested layer placeholders in many cases.
- [x] Generate selected camera/view nodes and metadata.
- [x] Preserve layer depth into Godot ordering metadata.
- [ ] Room speed and timing integration.
- [ ] Room persistent flag.
- [ ] Room creation code execution.
- [ ] Instance creation code execution.
- [ ] Room inheritance.
- [ ] Layer visibility/lock/offset/speed/parallax behavior.
- [ ] Background tiling and scrolling behavior.
- [ ] Multiple active views.
- [ ] View surfaces.
- [ ] Camera follow behavior.
- [ ] Physics world settings.
- [ ] Dynamic room/layer APIs.
- [ ] UI layers and flex panels from room data.
- [ ] Filters/effects conversion.

## Objects And Instances

- [x] Convert object scenes and scripts.
- [x] Preserve object sprite reference.
- [x] Preserve parent object reference.
- [x] Preserve visible/solid/persistent metadata where parsed.
- [x] Convert many event code files.
- [x] Register instances in runtime.
- [ ] Full object variable import.
- [ ] Full instance variable override import.
- [ ] Full mask sprite override.
- [ ] Full object physics import.
- [ ] Full parent event inheritance and inherited collision behavior.
- [ ] Full instance IDs and handles across room changes.
- [ ] Instance activation/deactivation APIs.
- [ ] `instance_change` behavior.
- [ ] Layer instance APIs.

## Tilesets And Tilemaps

- [x] Parse tileset sprite, tile size, separation, margin, and count.
- [x] Generate basic Godot `TileSet` resources.
- [ ] Animated tiles.
- [ ] Tile animation speed.
- [ ] Auto-tile sets.
- [ ] Tile brushes.
- [ ] Tilemap layer data for every GameMaker TileDataFormat.
- [ ] Tile flipping, rotation, and mirroring flags.
- [ ] Tile collision, navigation, and occlusion data.
- [ ] Runtime tilemap APIs.

## Sequences And Timelines

- [x] Asset registry recognizes sequence and timeline categories.
- [x] Runtime has a compatibility subset for sequences/timelines.
- [ ] Convert sequence metadata.
- [ ] Convert sequence playback length and speed.
- [ ] Convert tracks and keyframes.
- [ ] Convert curve interpolation.
- [ ] Convert sprite, instance, audio, text, nested sequence, graphic, and effect tracks.
- [ ] Convert broadcast messages and moment events.
- [ ] Convert timeline moments and GML actions.
- [ ] Implement timeline variables and runtime control.
- [ ] Implement sequence layer elements and runtime sequence APIs.

## Particles, Effects, Animation Curves

- [x] Runtime has particle compatibility subset.
- [x] Convert particle system assets into stable generated descriptors.
- [x] Convert authored particle types and emitters, with source-linked diagnostics for unsupported attractors, destroyers, deflectors, and changers.
- [x] Convert room particle system layer elements.
- [ ] Convert built-in effects and filters.
- [ ] Convert effect parameters and ordering.
- [ ] Convert animation curve assets.
- [ ] Convert animation curve channels, points, and interpolation.

## Extensions And Platform Services

- [x] Discover extension functions and require mapping for behavior.
- [x] Document extension compatibility policy.
- [x] Provide platform service hook framework.
- [ ] Convert extension constants, macros, files, options, and platform implementation metadata.
- [ ] Generate Godot plugin/GDExtension binding stubs.
- [ ] Provide common compatibility packs for Steam, IAP, ads, analytics, cloud, push notifications, social, console, and mobile services.
- [ ] Support async callbacks from extension/platform SDKs.
- [ ] Support external native calls through explicit bindings.

## Notes, Included Files, Options

- [x] Copy notes.
- [x] Copy included files.
- [x] Convert selected project settings.
- [ ] Full included file export target behavior.
- [ ] Full platform options.
- [ ] Full compiler/runtime options.
- [ ] Full permissions/capabilities.
- [ ] Full localization files and string tables if present.
