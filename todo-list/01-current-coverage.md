# Current Coverage

This file records what the current codebase appears to support. Partial features are unchecked until behavior is complete enough for full GameMaker compatibility.

## Conversion Pipeline

- [x] Select conversion groups for `assets`, `project`, and `wip` in `src/conversion/converter.py`.
- [x] Run converters in a stable high-level sequence through `src/conversion/converter.py`.
- [x] Use shared converter helpers for lenient `.yy` JSON parsing and subfolder extraction in `src/conversion/base_converter.py`.
- [x] Edit `project.godot` while preserving existing lines in `src/conversion/project_godot.py`.
- [x] Generate selected project settings, game icon output, and audio bus layout in `src/conversion/project_settings.py`.
- [ ] Replace hard-coded converter order with a dependency graph.
- [ ] Add a typed `ConversionContext` instead of repeated constructor argument plumbing.
- [ ] Add durable diagnostics and reports instead of relying primarily on log callbacks.

## Resource Converters

- [x] Convert sprites from `.yy` metadata and source images.
- [x] Preserve sprite subfolders.
- [x] Compose visible sprite image layers.
- [x] Preserve sprite frame order.
- [x] Generate static and animated sprite Godot scenes.
- [x] Preserve sprite origin metadata.
- [x] Preserve animation speed, durations, and loop information.
- [x] Generate basic collision shape data for sprites.
- [x] Imported precise and precise-per-frame alpha mask collision behavior.
- [ ] Partial: full nine-slice, skeletal, broadcast, texture group, and runtime sprite mutation behavior.

- [x] Convert sounds by copying `.wav`, `.mp3`, and `.ogg` assets.
- [x] Write Godot import metadata for sounds.
- [x] Preserve volume and audio group metadata.
- [x] Generate an audio group map.
- [ ] Partial: full compression, preload, streaming, platform format, positional emitter/listener, and async audio semantics.

- [x] Convert fonts from bundled TTFs or system font lookup.
- [x] Generate fallback `SystemFont` resources.
- [x] Preserve selected bold, italic, anti-aliasing, and subfolder metadata.
- [ ] Partial: glyph ranges, sprite fonts, SDF/MSDF behavior, texture group behavior, and exact GameMaker text rendering.

- [x] Copy included files from `datafiles/` into the generated Godot project.
- [x] Copy note text files and preserve note subfolders.
- [ ] Partial: included file export target rules and sandbox path compatibility.

- [x] Convert object assets into Godot object folders, scenes, and scripts.
- [x] Preserve object sprite, parent, solid, persistent, and event metadata.
- [x] Generate object script runtime registration hooks.
- [x] Transpile many object event GML bodies.
- [ ] Partial: full object variable import, physics fixture import, instance activation/deactivation, parent event semantics, and exact lifecycle order.

- [x] Convert script assets into callable generated wrappers.
- [x] Support modern `function name(...) {}` script content.
- [x] Support pre-2.3-style GMS2 script bodies through wrapper generation where present in importable projects.
- [x] Generate `gm2godot/gml_script_registry.gd`.
- [x] Support extension function mapping files.
- [ ] Partial: native extension behavior and full external library mapping.

- [x] Convert rooms into Godot scenes.
- [x] Set the first GameMaker room as the generated Godot main scene.
- [x] Preserve room order from the project file.
- [x] Generate room runtime script attachment.
- [x] Generate instance, background, tile, asset, effect, and nested layer containers in many cases.
- [x] Preserve camera/view metadata and selected camera nodes.
- [x] Preserve instance creation order metadata.
- [ ] Partial: room creation code execution.
- [ ] Partial: instance creation code execution.
- [ ] Partial: multiple visible views, follow-object camera behavior, view surfaces, and GUI surface behavior.
- [ ] Partial: room inheritance and runtime room mutation.
- [ ] Partial: room layer effects and filters.

- [x] Convert basic tileset metadata into Godot `TileSet` resources.
- [x] Preserve tile size, separation, margins, tile count, and subfolders.
- [ ] Partial: TileDataFormat variants, animated tiles, brushes, autotile metadata, tile transforms, tile collisions, and runtime tilemap APIs.

- [x] Convert shader files into `.gdshader` files with basic string substitutions.
- [ ] Partial: full GLSL ES to Godot shader language translation.
- [ ] Partial: attributes, varyings, uniforms, samplers, macros, precision qualifiers, multi-pass effects, and shader compiler diagnostics.

- [x] Generate an asset registry covering sprites, sounds, rooms, objects, scripts, fonts, paths, shaders, tilesets, timelines, sequences, and included files.
- [x] Generate stable asset IDs and metadata for many resource types.
- [ ] Partial: asset registry support for full runtime dynamic creation, deletion, tagging, and texture/audio group fidelity.

- [x] Generate a path registry from GameMaker path points, closed flag, and precision.
- [ ] Partial: real Godot `Path2D`/`Curve2D` assets and exact path interpolation/orientation/point speed behavior.

## Missing Or Mostly Metadata-Only Resources

- [ ] Full path resource converter to Godot path/curve resources.
- [ ] Timeline converter.
- [ ] Sequence converter.
- [ ] Animation curve converter.
- [x] Particle system asset converter.
- [ ] Extension converter for native/plugin-backed behavior.
- [ ] Texture group converter.
- [ ] Full audio group behavior.
- [ ] Full platform/options/configuration converter.
- [ ] Full room filters/effects converter.
- [ ] Full room inheritance semantics.
- [ ] Full object physics fixture converter.
- [ ] Full IDE tags/folders/options documentation export.

## GML Transpiler Coverage

- [x] Tokenize numeric literals including decimal, floats, numeric separators, hex, GameMaker `$` hex, binary, and hash color literals.
- [x] Tokenize string literals with quotes and escapes.
- [x] Strip `//` and block comments.
- [x] Convert `begin` and `end` blocks.
- [x] Parse unary operators `+`, `-`, `!`, `not`, and `~`.
- [x] Parse arithmetic, comparison, boolean, bitwise, shift, `div`, and `mod` operators.
- [x] Parse ternary `?:`.
- [x] Parse nullish `??` and nullish assignment `??=`.
- [x] Parse function calls and omitted arguments as `undefined`.
- [x] Parse array literals, struct literals, nested arrays, nested structs, and shorthand fields.
- [x] Parse `nameof(...)`.
- [x] Parse `new Constructor(...)`.
- [x] Parse `var`, multiple declarations, `:=`, uninitialized locals, and `globalvar`.
- [x] Parse assignments and many compound assignments.
- [x] Parse `++` and `--` statements and limited assignment RHS uses.
- [x] Parse enum declarations with compile-time values.
- [x] Parse function literals, methods, constructors, constructor inheritance, parameter defaults, return, and static declarations inside functions.
- [x] Parse `if`, `else`, `while`, `repeat`, `do until`, `for`, `switch`, `break`, `continue`, `exit`, `throw`, `try/catch/finally`, and `with`.
- [x] Parse array, struct, DS map, DS list, DS grid, and array reference accessors.
- [x] Parse `event_inherited()`.
- [x] Parse many preprocessor directives: `#macro`, `#define`, `#if`, `#ifdef`, `#ifndef`, `#elif`, `#else`, `#endif`, `defined()`, and `#region`/`#endregion`.
- [ ] Partial: chained assignments.
- [ ] Partial: arbitrary nested increment/decrement expressions.
- [ ] Partial: `delete` for struct/member/accessor targets.
- [ ] Partial: full preprocessor expression language.
- [ ] Partial: all current GMS2+ GameMaker grammar edge cases and importable syntax variants.

## Runtime Coverage

- [x] Generate runtime script segments through `src/conversion/gml_runtime_parts/script.py` and `writer.py`.
- [x] Implement foundation values, global/builtin variable wrappers, handles, methods, exceptions, and instance registration.
- [x] Implement many math, random, arrays, structs, variables, accessors, and strings APIs.
- [x] Implement DS list, stack, queue, priority, map, and grid core operations.
- [x] Implement file, path, INI, JSON, buffer, base64, hash, and save/load helpers.
- [x] Implement async HTTP bridge and networking core TCP/UDP helpers.
- [x] Implement non-positional audio playback and documented audio aliases.
- [x] Implement draw basics, sprite/text draw calls, GPU/draw state subset, surfaces, cameras/display subset, input polling subset, room/game flow subset, time/alarms subset, motion/path subset, physics subset, shader subset, particles subset, sequences/timelines compatibility subset, OS/debug/GC subset, platform service hook framework, and extension mapping policy.
- [ ] Partial: manifest reports many partial/unsupported/planned APIs. Current agent inventory found about 542 implemented, 331 partial, 105 unsupported, and 7 planned entries across 985 manifest entries.
- [ ] Partial: collisions and masks are approximations.
- [ ] Partial: surfaces and application surface behavior are approximations.
- [ ] Partial: platform services are hook-backed, not actual SDK integrations.
- [ ] Partial: sequences/timelines are compatibility stubs/metadata, not full authored conversion.

## Event Coverage

- [x] Map Create, Destroy, Clean Up, Alarm 0..11, Step, Begin Step, End Step, Collision, Draw variants, many Other events, and async family callback names.
- [x] Recognize Keyboard, Mouse, KeyPress, KeyRelease, and Gesture as merged input categories.
- [x] Include tests under `tests/conversion/events/` for many mapping cases.
- [ ] Partial: input event source is recognized but not fully loaded into generated `_input(event)` branches.
- [ ] Partial: automatic alarm ticking is not fully integrated into generated objects.
- [ ] Partial: End Step is mapped but not automatically dispatched.
- [ ] Partial: collision callback functions are generated but automatic collision dispatch is missing.
- [ ] Partial: draw subevents are generated but not fully ordered/invoked like GameMaker.
- [ ] Partial: async HTTP mapped name differs from runtime dispatcher name.
- [ ] Partial: user events map to functions but need `event_user`/`event_perform` runtime integration.
- [ ] Partial: Trigger event type is not mapped.

## Generated Output Risks

- [ ] Manual `.import` files can be fragile across Godot versions.
- [ ] Many project settings are only partially mapped and may be placed in incomplete sections.
- [ ] Runtime state is a static `RefCounted` preload, not a full Godot autoload manager architecture.
- [ ] Godot callback order is not equivalent to GameMaker event order.
- [ ] String-based generated-code tests can miss invalid GDScript.
- [ ] Godot smoke tests can skip when a Godot binary is missing.
