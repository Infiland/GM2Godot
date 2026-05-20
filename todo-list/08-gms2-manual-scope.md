# GMS2+ Manual Scope

This file defines the absolute compatibility scope requested for GM2Godot: every current GMS2+ GameMaker `GML Code Overview` page and every current `GML Code Reference` category/page should eventually be represented in the converter, runtime, diagnostics, or explicit unsupported-feature report.

Scope rules:

- Target current GMS2+ / modern GameMaker projects only.
- GMS 1.4 or GML 1.4-only behavior is out of scope.
- If the current manual documents a deprecated API, GM2Godot still needs one of these outcomes: faithful implementation, safe compatibility shim, or explicit diagnostic with migration guidance.
- Every category below means every function/page under that category is in scope, not only the category heading.
- A category is unchecked until all pages under it are implemented, tested, or explicitly diagnosed.

## GML Code Overview Pages

- [x] Basic Code Structure: parse normal event/script code blocks and generated statement boundaries.
- [x] Runtime Functions: lower many built-in/runtime function calls through descriptors and `GMRuntime` helpers.
- [x] Variables And Variable Scope: locals, globals, instance variables, and many builtin variables are modeled.
- [x] Data Types: core GML values are represented through GDScript values and runtime wrappers.
- [x] if / else and Conditional Operators.
- [x] Addressing Variables In Other Instances: partial support through selectors, `with`, and runtime helpers.
- [x] Expressions And Operators: many current operators are parsed and emitted.
- [x] Script Functions And Variables.
- [x] Method Variables.
- [x] Script Functions vs. Methods.
- [x] Static Variables inside functions/constructors.
- [x] Arrays.
- [x] Structs & Constructors.
- [x] Commenting Code: line and block comments are handled by the parser.
- [x] Instance Keywords: `self`, `other`, `all`, and `noone` are recognized.
- [x] Evaluation Order: many expression precedence rules are implemented.
- [x] Accessors: arrays, struct, DS map/list/grid, and array-reference accessors are implemented.
- [ ] Full source mapping for Basic Code Structure diagnostics.
- [ ] Full current-manual variable lookup parity across locals, instance variables, globals, statics, assets, enum members, scripts, constructors, methods, and dynamic fields.
- [ ] Full current-manual data type parity for undefined, NaN, infinity, pointers, handles, methods, structs, arrays, asset IDs, instance IDs, and dynamic resources.
- [ ] Full current-manual truthiness, equality, coercion, numeric precision, string conversion, array copy/reference, struct reference, and handle lifecycle parity.
- [ ] Full current-manual method binding, method identity, constructor static inheritance, closure capture, and static chain behavior.
- [ ] Full current-manual evaluation-order edge cases, especially prefix/postfix mutation and assignment expressions.
- [ ] Full current-manual accessor edge cases, including nested mixed accessors, missing values, auto-expansion, destroyed handles, and DS serialization.

## GML Language Features

- [x] `if`, `else`, and conditional operators.
- [x] `for`.
- [x] `while`.
- [x] `repeat`.
- [x] `do` / `until`.
- [x] `switch`, `case`, and `default`.
- [x] `break`.
- [x] `continue`.
- [x] `return`.
- [x] `exit`.
- [x] `throw`.
- [x] `try`, `catch`, and `finally` subset.
- [x] `with` subset.
- [x] `new` constructor calls.
- [x] `delete` subset.
- [x] `begin` and `end` block aliases.
- [ ] Full `finally` behavior where return/break/continue/exit interactions differ.
- [ ] Full `with` behavior for nested `self`/`other`, object targets, parent targets, destroyed targets, and event/collision contexts.
- [ ] Full `delete` behavior for member/accessor/struct targets.
- [ ] Full assignment expression and chained assignment semantics.

## GML Reference: Variable And Array Functions

- [ ] Variable Functions category: every current manual page in `GML_Reference/Variable_Functions`.
- [ ] Array Functions category: every current manual array function page, including higher-order functions such as map/filter/reduce-style APIs where documented.
- [ ] Type checking and type conversion helpers.
- [ ] Dynamic instance/global/struct variable access helpers.
- [ ] Weak reference and reference-related helpers where documented.
- [ ] Runtime support, transpiler lowering, and tests for every documented variable/array function.

## GML Reference: Asset Management

The current manual source has 781 Asset Management pages. Every page is in scope.

- [x] Sprites: basic conversion, registry entries, draw helpers, and metadata subset.
- [x] Audio/Sounds: basic conversion, audio group metadata, bus generation, and playback subset.
- [x] Fonts: basic conversion and runtime drawing subset.
- [x] Scripts: conversion and script registry generation.
- [x] Shaders: basic source conversion and runtime shader subset.
- [x] Rooms: room scene generation and room runtime subset.
- [x] Objects/Instances: object scene/script generation and instance registry subset.
- [x] Paths: path registry and runtime path subset.
- [x] Tilesets: basic tileset conversion.
- [ ] Animation Curves: all 10 current manual pages.
- [ ] Assets And Tags: all 12 current manual pages.
- [ ] Audio: all 125 current manual pages, including groups, emitters, listeners, queues, buffers, sync groups, recording, and async playback.
- [ ] Extensions: all 7 current manual pages, including functions, constants, files, platform implementations, and native binding policy.
- [ ] Fonts: all 28 current manual pages, including glyph ranges, runtime fonts, text measurement, and sprite/dynamic font behavior.
- [ ] Instances: all 52 current manual pages, including creation, destruction, change, activation, lookup, nearest/furthest, variables, and parent targeting.
- [ ] Objects: all 27 current manual pages, including parent metadata, event inheritance, object variables, and object lookups.
- [ ] Particle Systems: every current manual page and any asset-backed particle system data.
- [ ] Paths: all 44 current manual pages, including dynamic paths, point speed, smoothing, interpolation, start/end actions, and path events.
- [ ] Rooms: all 275 current manual pages, including room order, settings, persistence, cameras/views, layers, tilemaps, sequence elements, text elements, particle elements, effect layers, UI layers, inheritance, and runtime room/layer APIs.
- [ ] Sequences: all 19 current manual pages, including tracks, keyframes, moments, broadcasts, instances, objects, text, audio, nested sequences, and runtime sequence APIs.
- [ ] Shaders: all 18 current manual pages, including shader compilation, uniforms, sampler handling, and Godot shader-language translation.
- [ ] Sprites: all 137 current manual pages, including masks, bounding boxes, collision, texture pages, skeleton animation, nine-slice, dynamic sprite APIs, and broadcast messages.
- [ ] Tilesets: all 5 current manual pages, including tile data, tile animation, brushes, transforms, and runtime tilemap behavior.
- [ ] Timelines: all 15 current manual pages for current GMS2+ imports, including moments, position, speed, loop/end behavior, and event scheduling.

## GML Reference: General Game Control

- [ ] Every current manual page in `General_Game_Control`.
- [ ] Game lifecycle APIs such as restart/end/save/load where documented.
- [ ] Project metadata variables such as `game_project_name`.
- [ ] Game speed/FPS and timing controls where documented.
- [ ] Deprecated current-manual APIs must produce compatibility shims or explicit diagnostics.

## GML Reference: Movement And Collisions

- [x] Movement helpers subset.
- [x] Collision query subset.
- [x] Motion planning/path subset.
- [ ] Movement: all 15 current manual pages.
- [ ] Collisions: all 25 current manual pages.
- [ ] Motion Planning: all 22 current manual pages.
- [ ] Exact collision masks, precise collisions, bbox behavior, parent object matching, list-returning query APIs, tilemap collisions, and collision event scheduling.

## GML Reference: Drawing

The current manual source has 389 Drawing pages. Every page is in scope.

- [x] Basic forms subset.
- [x] Colour and alpha subset.
- [x] Sprite/text draw subset.
- [x] Surface subset.
- [x] GPU/draw state subset.
- [x] Shader helper subset.
- [x] Particle draw/runtime subset.
- [ ] Basic Forms: all 24 current manual pages.
- [ ] Colour And Alpha: all 18 current manual pages.
- [ ] GPU Control: all 66 current manual pages, including blend modes, culling, depth, stencil, scissor, color write, texture state, filtering, repeat, and state leakage.
- [ ] Mipmapping: all 25 current manual pages.
- [ ] Sprites And Tiles: all 20 current manual pages.
- [ ] Text: all 16 current manual pages.
- [ ] Primitives And Vertex Formats: all 45 current manual pages.
- [ ] Surfaces: all 42 current manual pages, including application surface, target stack, volatility, copy/save, and surface-to-sprite behavior.
- [ ] Lighting: all 9 current manual pages.
- [ ] Particles: all 76 current manual pages.
- [ ] Textures: all 25 current manual pages.
- [ ] Videos: all 16 current manual pages.
- [ ] Depth And Stencil Buffer: every current manual page.

## GML Reference: Cameras And Display

- [x] Camera/display subset.
- [x] GUI size subset.
- [ ] Cameras And Viewports: all 59 current manual pages.
- [ ] Game Window: all 43 current manual pages.
- [ ] Full camera creation, destruction, view matrices, projections, viewport arrays, window sizing, fullscreen, orientation, DPI, GUI scaling, screenshots, and multi-view behavior.

## GML Reference: Game Input

- [x] Keyboard polling subset.
- [x] Mouse polling subset.
- [x] Gamepad polling subset.
- [ ] Device Input: all 15 current manual pages.
- [ ] GamePad Input: all 27 current manual pages.
- [ ] Gesture Input: all 24 current manual pages.
- [ ] Keyboard Input: all 18 current manual pages.
- [ ] Mouse Input: all 11 current manual pages.
- [ ] Virtual Keys And Keyboards: all 10 current manual pages.
- [ ] Full per-step pressed/released state, text input, virtual keyboard, gestures, gamepad vibration, touch/device mapping, and input-event dispatch.

## GML Reference: Data Structures

- [x] DS list, map, grid, queue, stack, and priority queue core subsets.
- [ ] DS Grids: all 40 current manual pages.
- [ ] DS Lists: all 22 current manual pages.
- [ ] DS Maps: all 31 current manual pages.
- [ ] DS Priority Queues: all 17 current manual pages.
- [ ] DS Queues: all 13 current manual pages.
- [ ] DS Stacks: all 12 current manual pages.
- [ ] Full serialization, JSON encoding/decoding, nested DS ownership, destroyed-handle behavior, sorting, shuffling, and accessor edge cases.

## GML Reference: Strings

- [x] String helper subset.
- [ ] Every current manual page in `Strings`.
- [ ] Unicode, UTF-8, byte length vs character length, copy/delete/insert/replace/search, formatting, real/string conversion, and template/string interpolation behavior where documented.

## GML Reference: Maths And Numbers

- [x] Maths and random subset.
- [ ] Angles And Distance: all 29 current manual pages.
- [ ] Date And Time: all 54 current manual pages.
- [ ] Matrix Functions: all 18 current manual pages.
- [ ] Number Functions: all 31 current manual pages.
- [ ] Exact random determinism, epsilon behavior, degree/radian assumptions, matrix behavior, date/time numeric encoding, and rounding/truncation parity.

## GML Reference: Flex Panels And Time Sources

- [x] Flex panel runtime subset.
- [x] Time/alarm helper subset.
- [ ] Flex Panels: all 71 current manual pages, including every function reference page.
- [ ] Time Sources: all 26 current manual pages.
- [ ] Full Yoga-equivalent layout behavior, dirty/layout lifecycle, panel nodes, time source lifecycle, pause/resume, and async/timer integration.

## GML Reference: Physics

- [x] Physics runtime subset.
- [ ] Fixtures: all 27 current manual pages.
- [ ] Forces: all 7 current manual pages.
- [ ] Joints: all 15 current manual pages.
- [ ] Physics Variables: all 29 current manual pages.
- [ ] Soft Body Particles: all 45 current manual pages.
- [ ] The Physics World: all 8 current manual pages.
- [ ] Full fixture shapes, sensors, collision masks/categories, density, restitution, friction, damping, world scale, debug draw, raycasts, forces, impulses, all joints, physics particles, and collision callbacks.

## GML Reference: Async, Networking, Web, Files, Buffers

- [x] HTTP async subset.
- [x] Networking TCP/UDP subset.
- [x] File/INI/JSON subset.
- [x] Buffer subset.
- [ ] Asynchronous Functions: all 23 current manual pages, including Cloud Saving, Dialog, Facebook if current manual exposes it, HTTP, and Push Notifications.
- [ ] Networking: all 18 current manual pages.
- [ ] Web And HTML5: all 18 current manual pages.
- [ ] File Handling: all 82 current manual pages, including binary files, encoding/hashing, directories, file system, INI files, and text files.
- [ ] Buffers: all 47 current manual pages.
- [ ] Full `async_load` maps, request IDs, event broadcasts, packet framing, sockets, UDP broadcast, WebSocket behavior, CORS/browser constraints, sandbox paths, binary alignment, endianness, compression, hashes, and async save/load.

## GML Reference: Platform, OS, Debug, GC

- [x] OS/debug/GC subset.
- [x] Platform service hook framework.
- [ ] In App Purchases: every current manual page.
- [ ] Xbox Live/UWP: all 70 current manual pages, including matchmaking, saving data, stats/leaderboards, users/accounts.
- [ ] OS And Compiler: all 33 current manual pages, including build/runtime constants, compiler/target checks, browser/device/os data, dialogs, permissions, URL/browser helpers, and `gml_pragma`.
- [ ] Debugging: all 48 current manual pages, including debug overlay, debug controls, callstack, input record/playback, debug logging, modal dialogs, and error handling.
- [ ] Garbage Collection: all 10 current manual pages.
- [ ] Steam: every current manual page and plugin-backed functions documented there.
- [ ] Live Wallpapers: all 3 current manual pages.
- [ ] GXC: all current manual pages if current target/platform support is in scope.
- [ ] Rollback: all current manual pages if current GameMaker exposes the rollback API to GMS2+ projects.

## Page-Level Coverage Requirement

- [ ] Generate a machine-readable index of every current manual `GML_Overview` and `GML_Reference` page with status, owner module, test path, docs URL, and diagnostic policy.
- [ ] Cross-check the generated index against `gml_api_manifest.py` so no current manual page is missing from the compatibility report.
- [ ] Add a CI check that fails when a manual page exists without a status entry.
- [ ] Add a docs generator that emits this checklist from the official manual tree and GM2Godot manifest data.
- [ ] Add an explicit `out_of_scope` status only for pages proven to be outside GMS2+ current compatibility goals.
