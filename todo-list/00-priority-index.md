# Priority Index

This file is the high-level roadmap for reaching full GameMaker-to-Godot transpilation.

## P0: Must Fix For Playable Broad Compatibility

### Compiler Frontend

- [x] Parse and emit many modern GML expressions, statements, functions, constructors, structs, arrays, accessors, control-flow forms, and preprocessor directives.
- [x] Validate function dispatch arity for many known GameMaker APIs.
- [x] Emit diagnostics for known unsupported GML APIs instead of silently generating wrong code.
- [x] Support extension function mappings through user-provided compatibility mappings.
- [ ] Support arbitrary prefix/postfix `++` and `--` expressions, not only statement and limited assignment RHS forms.
- [ ] Support chained assignment with GameMaker-compatible result semantics.
- [ ] Support `delete` for struct/member/accessor targets.
- [ ] Expand preprocessor `#if` expression evaluation beyond simple symbols, booleans, `defined()`, and negation.
- [ ] Decide and document support policy for unsupported directives such as `#import`, `#include`, and `gml_pragma`.
- [ ] Add source maps from generated GDScript back to GML file, event, line, and column.
- [ ] Add parser fuzz/property tests for strings, comments, operators, accessors, macros, malformed syntax, and nested control flow.

### Project Import

- [x] Parse `.yyp` resource lists and many `.yy` resource files.
- [x] Convert common resources: sprites, sounds, fonts, objects, scripts, rooms, notes, included files, shaders, tilesets, asset registry data, and path registry data.
- [x] Preserve many IDE subfolders through `parent.path` metadata.
- [x] Generate `project.godot` main scene settings and selected project settings.
- [ ] Import all project options, target options, export settings, permissions, splash/icons, window/display options, and platform-specific configuration.
- [ ] Import project configurations and config-specific macros/options/assets.
- [ ] Import texture groups as actionable Godot import/runtime behavior, not only metadata.
- [ ] Import audio groups with full preload/stream/compression semantics, not only buses and metadata.
- [ ] Import object physics fixture settings, masks, categories, damping, density, restitution, friction, sensors, and collision filters.
- [ ] Import room creation code and instance creation code as executable GML in the correct lifecycle order.
- [ ] Import full room inheritance and runtime mutation behavior.
- [ ] Import animation curves, particle assets, timelines, sequences, extensions, filters/effects, UI layers, and dynamic room layer element data.
- [ ] Add committed full `.yyp/.yy` fixture projects for every resource type.

### Runtime API

- [x] Generate `res://gm2godot/gml_runtime.gd` from ordered GDScript runtime segments.
- [x] Generate registries for assets, scripts, and paths.
- [x] Implement many math, string, array, struct, variable, DS, file, INI, JSON, buffer, draw, input, audio, room, path, physics, networking, async HTTP, particle, shader, OS/debug, and platform hook APIs.
- [x] Track API support status in a manifest with category counts and unsupported diagnostics.
- [ ] Move from broad compatibility subsets to exact GameMaker semantics for collisions, surfaces, draw state, audio, physics, sequences, timelines, particles, platform services, texture groups, and async event payloads.
- [ ] Implement full sprite/texture/skeleton API coverage.
- [ ] Implement full room layer element APIs for tilemaps, backgrounds, sprites, text, particles, sequences, UI layers, filters, and effects.
- [ ] Implement all native external call and extension paths through explicit Godot plugins, GDExtension bindings, or actionable stubs.
- [ ] Implement media/device APIs: video, microphone, camera, sensors, permissions, mobile lifecycle, browser integration, and platform-specific storage.
- [ ] Add a durable JSON and Markdown unsupported-feature report for every conversion.

### Event Dispatch

- [x] Map many GameMaker event categories to generated function names.
- [x] Generate basic Create, Destroy, Clean Up, Step, Alarm, Collision, Draw, Other, Async, and lifecycle callback names.
- [x] Recognize input events as a merged input category.
- [ ] Implement a central GameMaker-compatible event scheduler instead of relying only on Godot callback order.
- [ ] Load and transpile keyboard, mouse, key press, key release, and gesture event source into generated `_input(event)` dispatch.
- [ ] Add automatic alarm ticking and exact alarm countdown semantics.
- [ ] Add automatic End Step dispatch after all Step events.
- [ ] Add collision event pair dispatch, parent matching, and precomputed collision sets.
- [ ] Add Draw Begin, Draw, Draw End, Pre Draw, Post Draw, Draw GUI Begin, Draw GUI, and Draw GUI End ordering.
- [ ] Add `event_user`, `event_perform`, and generic event invocation.
- [ ] Fix async HTTP naming mismatch between mapped event function and runtime dispatcher.
- [ ] Add room/view boundary, animation, broadcast, wallpaper, platform, and async family dispatch where the runtime supports the triggering API.

### Generated Godot Architecture

- [x] Generate Godot scenes/scripts/resources under stable project folders such as `sprites/`, `objects/`, `rooms/`, `sounds/`, and `gm2godot/`.
- [x] Use a shared runtime compatibility script for many GameMaker APIs.
- [ ] Introduce explicit runtime managers for game loop, event scheduling, rooms, instances, drawing, async, input, audio, and compatibility configuration.
- [ ] Consider using Godot autoloads for runtime managers where stable global state is required.
- [ ] Preserve GameMaker instance IDs independently from Godot node instance IDs.
- [ ] Add deterministic generated-code ordering, scene resource IDs, output paths, and stable snapshot tests.
- [ ] Add headless Godot project validation for generated `.gd`, `.tscn`, `.tres`, imports, and project settings.

### Testing And Fixtures

- [x] Run strict Pyright through local and CI checks.
- [x] Run Python unit tests in CI.
- [x] Maintain broad tests for converters, parser, runtime generation, events, and Godot smoke harnesses.
- [ ] Add CI with a pinned Godot binary so `*_godot.py` smoke tests do not silently skip.
- [ ] Add generated GDScript parser/load checks through Godot headless.
- [ ] Add GameMaker-to-Godot golden trace fixtures for event order, alarms, input, collision, draw order, async, rooms, persistence, and lifecycle.
- [ ] Add visual regression tests for surfaces, blend state, shaders, GUI scaling, cameras, tiles, and draw order.
- [ ] Add project-specific compatibility reports and fail thresholds for unsupported APIs and transpile warnings.

### Tooling And UX

- [x] Provide a GUI converter with selectable conversion groups.
- [ ] Add CLI modes: analyze-only, convert, validate, report, fail-on-unsupported, and target-platform filter.
- [ ] Generate compatibility reports grouped by manual category, asset type, event, function, source file, and severity.
- [ ] Add source-linked warnings for unsupported GML APIs, unsupported resources, skipped event source, shader failures, invalid generated code, and platform gaps.
- [x] Update README product positioning because the project now contains a real transpiler and runtime.
- [ ] Add documentation for adding a new GML API, runtime segment, resource converter, event mapping, fixture, and Godot smoke test.

## P1: Expand Correctness And Coverage

### Compiler Frontend

- [ ] Preserve GameMaker truthiness, equality/coercion, `NaN`, `infinity`, `undefined`, integer division, modulo, string conversion, and boolean threshold behavior across all expression forms.
- [ ] Support full static-chain behavior for functions, constructors, inherited statics, method structs, `static_get`, and `static_set`.
- [ ] Add dynamic variable and struct APIs: `variable_*`, `struct_*`, dynamic globals, instance variables created on assignment, and constructor tags.
- [ ] Add compatibility for current GMS2+ syntax variants, including script asset patterns that current GameMaker can still import and run.
- [ ] Add DnD/GML Visual lowering if projects contain visual action data.

### Project Import

- [ ] Convert all layer element types: background, sprite, tilemap, sequence, text, particle system, effect/filter, and UI/flex layers.
- [ ] Convert tilesets with animated tiles, tile brushes, auto-tile metadata, border/output border, tile transforms, and tile collision data.
- [ ] Convert paths into real Godot `Path2D`/`Curve2D` resources while preserving GameMaker point speed and precision data.
- [ ] Convert sequences into `AnimationPlayer`, generated scene orchestration, or a runtime sequence scheduler.
- [ ] Convert timelines into deterministic frame/moment resources.
- [ ] Convert animation curves and sequence curves.
- [ ] Convert marketplace extensions as metadata plus generated Godot plugin binding stubs.

### Runtime API

- [ ] Implement full animation/image variable behavior: `sprite_index`, `image_index`, `image_speed`, `image_number`, scale, angle, blend, alpha, and animation events.
- [ ] Implement layer APIs for creating, moving, querying, and destroying all supported layer element types.
- [ ] Implement full physics fixture/joint/world behavior or a documented compatibility backend.
- [ ] Implement particle APIs and asset-backed particle systems.
- [ ] Implement texture APIs, texture prefetch/flush, texture group behavior, and raw texture handle/UV compatibility.
- [ ] Implement dynamic asset creation APIs for sprites, sounds, fonts, paths, rooms, layers, particles, and surfaces.
- [ ] Implement platform abstraction layers for desktop, web, mobile, Steam, IAP, cloud, and console APIs through optional plugins.

### Generated Godot Architecture

- [ ] Add rendering backend modes: Godot-node mode, central canvas draw manager mode, and high-fidelity surface/viewport mode.
- [ ] Add generated editor metadata so converted rooms/assets can be inspected in Godot without losing source links.
- [ ] Add compatibility configuration toggles for performance vs fidelity.

### Testing And Fixtures

- [ ] Add fixtures for shaders, materials, paths, timelines, sequences, particles, physics, tilemaps, views, layer inheritance, extensions, macros/configs, included files, fonts, texture groups, audio groups, and project options.
- [ ] Add async fixtures with mock HTTP servers, file/dialog callbacks, network packets, buffer async, image loading, and extension callbacks.
- [ ] Add physics fixtures for fixtures, sensors, collision callbacks, joints, raycasts, and timestep behavior.
- [ ] Add runtime conformance tests comparing captured GameMaker output traces to generated Godot output traces.

## P2: Advanced Compatibility

- [ ] Support advanced current-manual compatibility patterns only when they apply to GMS2+ projects or current GameMaker imports.
- [ ] Import package formats such as `.yymps`, `.yymp`, `.gmez`, local packages, and marketplace metadata where practical.
- [ ] Implement advanced draw APIs: primitives, vertex buffers, vertex formats, matrices, depth/stencil, fog, mipmapping, lighting, and skeletal sprite APIs.
- [ ] Implement advanced audio: positional emitters/listeners, effects, buses, sync groups, recording, and platform-specific playback restrictions.
- [ ] Implement advanced networking and platform services through plugins and service SDK bridges.
- [ ] Add optional C#, GDExtension, or native runtime backend for performance-sensitive games.
- [ ] Add deterministic replay and event tracing for debugging converted projects.
- [ ] Add public compatibility fixture zoo covering every manual category.
- [ ] Add performance benchmarks for instance count, draw calls, DS-heavy code, surfaces, physics, tilemaps, sequences, and shaders.

## P3: Ecosystem And Long-Term Goals

- [ ] Support community compatibility packs for Steam, Epic/GOG, mobile billing, ads, analytics, cloud saves, consoles, and common marketplace extensions.
- [ ] Add optional exact Box2D compatibility if Godot physics diverges too much for physics-heavy projects.
- [ ] Add optional custom renderer for projects that depend on exact GameMaker batching, blend, texture page, surface, and application surface behavior.
- [ ] Support incremental reconversion without overwriting manual Godot edits.
- [ ] Support plugin APIs so third parties can add compiler/runtime/resource mappings for project-specific conventions.
- [ ] Add project scoring such as `playable`, `mostly compatible`, `requires extension work`, `renderer-sensitive`, and `physics-sensitive`.
- [ ] Add large-project anonymization tooling so real projects can contribute compatibility cases without exposing source/assets.
