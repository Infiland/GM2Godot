# Generated Project and Runtime

> **Applies to:** GM2Godot 0.7.9 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-18

[Home](Home) · [Installation](Installation) · [Quick start](Quick-Start-Conversion) · [Compatibility](Compatibility-and-Limitations) · [Diagnostics](Diagnostics-and-Troubleshooting) · [Contributing](Contributing-and-Testing)

This page is the advanced-user map of a converted project: what GM2Godot owns, how the generated runtime coordinates GameMaker semantics, and which reports are authoritative. The implementation-facing documents in the main repository remain canonical for details that can change between releases.

## Generated layout and ownership

A full conversion can produce a tree like this. The exact files depend on the enabled converter keys and the source project.

```text
GodotProject/
├── project.godot
├── default_bus_layout.tres
├── icon.ico / icon.png
├── addons/gm2godot_extensions/
├── gm2godot/
│   ├── gml_runtime.gd
│   ├── gml_room_node.gd
│   ├── managers/
│   ├── conversion_attempt.json
│   ├── conversion_manifest.json
│   ├── conversion_diagnostics.json / .md
│   ├── architecture_policy.json
│   └── other registries and compatibility reports
├── fonts/
├── included_files/
├── notes/
├── objects/
├── rooms/
├── scripts/
├── shaders/
├── sounds/
├── sprites/
└── tilesets/
```

GM2Godot treats these directories as managed output roots:

- `addons/gm2godot_extensions/`
- `fonts/`, `gm2godot/`, `included_files/`, `notes/`, `objects/`, `rooms/`, `scripts/`, `shaders/`, `sounds/`, `sprites/`, and `tilesets/`

The top-level `default_bus_layout.tres`, `icon.ico`, and `icon.png` are managed files. `project.godot` is jointly managed: GM2Godot can update the generated `GM*` autoload entries and, when a room is generated, set `run/main_scene` from the first GameMaker `RoomOrderNodes` entry. Existing unrelated project settings and unrelated autoloads are preserved.

### Included Files and file reads

GameMaker Included Files from `datafiles/` are emitted under `res://included_files/`. Each relative path uses GameMaker's packaged lookup form: ASCII `A`–`Z` is lowercased and spaces become underscores, including nested directory components; other characters are preserved.

For relative file and buffer reads, the generated runtime checks the exact `user://gm2godot/<path>` first and then the normalized `res://included_files/<path>`. Writes target user storage. A saved user file therefore overrides its packaged default, and deleting the saved copy reveals the packaged file again. `file_exists()`, text-file reads, and `buffer_load()` share this precedence.

When source paths collapse to the same packaged name, or when one normalized file path would block another file's directory, GM2Godot reserves natural names and deterministically assigns `_2`, `_3`, and later suffixes before the extension. The emitted files, asset registry, and conversion manifest use the same assignments. `GM2GD-INCLUDED-FILE-PATH-COLLISION` reports the mapping; rename these conflicts in GameMaker because normalized lookup cannot distinguish every original alias. Publication also rejects redirected or non-regular paths in the managed `included_files/` output tree instead of writing through them.

`res://included_files/` and `res://gm2godot/gml_included_file_registry.gd` form one converter-owned output set. Ordinary conversion failures and cancellation preserve the previous pair, but the root and registry are published in separate steps and are not process-crash-atomic. Until [#727](https://github.com/Infiland/GM2Godot/issues/727) is implemented, do not run conversion while a live game or another converter is accessing the same output project.

This emission and runtime-read contract is covered by an end-to-end smoke test using the exact supported Godot 4.7.1 build.

Treat every generated file under a managed root as reproducible output. A later conversion can replace it even if the converter does not delete the entire directory. For repeatable migrations:

1. Keep the GameMaker project and `gm2godot_extension_functions.json` as source-controlled inputs.
2. Put hand-authored Godot code outside the managed roots—for example, `res://game/` or `res://addons/my_bridge/`.
3. Point extension mappings or custom autoloads at that hand-authored code.
4. Review `conversion_attempt.json`, diagnostics, and the manifest diff after every regeneration.

Editing generated GDScript is useful for investigation, but it is not a durable fix. Make durable changes in the GameMaker source, the extension mapping/bridge, or GM2Godot itself. The managed-path safety rules are implemented in [`project_godot.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/project_godot.py).

## Room and rendering architecture

The generated room policy translates GameMaker’s flat resource model into a Godot scene tree:

- Each room is a `Node2D` root using `res://gm2godot/gml_room_node.gd`.
- The first ordered GameMaker room becomes the Godot main scene when it was converted successfully.
- GameMaker layers become `Node2D` children. The depth mapping is `z_index = -GameMaker depth`, because lower GameMaker depth and higher Godot `z_index` both draw later.
- Every room reserves a `GMGUI` `CanvasLayer` at layer `1000` for Draw GUI phases.
- Decodable tile data uses Godot 4 `TileMapLayer` output.
- Native Godot callbacks do not define GameMaker event order; the runtime managers coordinate the generated phases.

`gm2godot/architecture_policy.json` records the feature-detected backend choices for the particular conversion:

| Domain | Possible policy modes | What selects the mode |
| --- | --- | --- |
| Rendering | `godot_node_scene`, `central_canvas_draw_manager`, `surface_viewport` | Detected `draw_`, `shader_`, `gpu_`, `font_`, or `sprite_` API usage, effect layers, and surface/application-surface usage |
| Collision | `generated_bounds_idle`, `generated_bounds_direct_queries`, `godot_physics_world_bridge` | Collision-query code and GameMaker physics-room settings |
| Audio | pooled `AudioStreamPlayer` / `AudioStreamPlayer2D`, or an idle runtime manager | Sound assets and audio API usage |
| File, buffer, HTTP, network | `FileAccess`, `DirAccess`, `PackedByteArray`, HTTP and socket wrappers | Detected file/buffer/network APIs |

The policy is a conversion-time description, not proof of gameplay parity. Inspect its `project_features`, `renderer`, `collision`, `audio`, `file_buffer_network`, `runtime_managers`, and `signal_queue_policy` fields together with diagnostics. The canonical, implementation-facing policy is [`godot_architecture_policy.md`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/godot_architecture_policy.md).

## Runtime facade and autoload managers

Generated scripts continue to preload `res://gm2godot/gml_runtime.gd` and call `GMRuntime.gml_*`. That static compatibility facade is the stable call-site boundary. The generated autoloads under `res://gm2godot/managers/` divide lifecycle ownership into explicit domains and register in this order:

| Order | Autoload | Primary responsibility |
| ---: | --- | --- |
| 0 | `GMRuntime` | Root registry, compatibility lifecycle, startup and shutdown |
| 10 | `GMAssets` | Assets, texture groups, audio groups and dynamic assets |
| 20 | `GMRooms` | Room order, current room, transitions and layers |
| 30 | `GMInstances` | Live instances, handles, object indices and creation order |
| 40 | `GMEvents` | Input dispatch, Step scheduler, alarms, timelines, sequences and collision window |
| 50 | `GMDraw` | Ordered Draw phases, draw state, surfaces, shaders and texture-group state |
| 60 | `GMInput` | Godot input capture and GameMaker keyboard, mouse, gamepad and gesture state |
| 70 | `GMAudio` | Audio instances, groups, emitters and listeners |
| 80 | `GMAsync` | FIFO async delivery, `async_load`, HTTP, buffer and networking queues |
| 90 | `GMPlatform` | Platform hooks, extension callback schemas, OS/debug and GC state |

Godot loads the autoload nodes before the main scene and the generated `project.godot` lists them deterministically. `GMRuntime.manager_order()` exposes the observed registration order, while `manager_registry_snapshot()` exposes domains, dependencies, state keys, and initialization indices.

Each manager also exposes named `state_bucket()` dictionaries. These are ownership and migration seams; they do **not** mean that every compatibility variable has already moved out of `gml_runtime.gd`. Existing generated call sites should keep using the facade unless a runtime change deliberately moves a domain behind a manager.

See [`runtime_managers.md`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/runtime_managers.md), [`runtime_managers.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/runtime_managers.py), and the executable expectations in [`test_runtime_managers.py`](https://github.com/Infiland/GM2Godot/blob/main/tests/test_runtime_managers.py).

## Lifecycle and event order

### Room entry and transitions

Generated object `_ready()` methods register the instance, initialize motion state, and run converted Create behavior when present. The generated room root then performs the room-entry sequence:

1. Register layer and view metadata.
2. Update the current room and room globals.
3. Run instance creation code in declared GameMaker creation order.
4. Dispatch Game Start once for the running game.
5. Run room creation code.
6. Dispatch Room Start.

For `room_goto*()` and `room_restart()`, the compatibility runtime dispatches Room End on the old scene, moves persistent instances to a root-level holding node, replaces the room scene, restores those instances, and runs the entry sequence for the new scene.

### Per-frame scheduler

`GMInput._input(event)` captures native input as it arrives. On the generated `GMEvents` frame pump, input event bindings are dispatched first, followed by the central scheduler:

```text
Begin Step
→ time sources
→ alarms
→ Step
→ motion/path update
→ collision dispatch
→ End Step
→ clear one-frame input edges
```

Collision is therefore evaluated after motion/path updates and before End Step. Do not attach correctness to the incidental `_process()` order of individual object nodes.

`GMDraw` independently dispatches the ordered drawing phases:

```text
Pre Draw → Draw Begin → Draw → Draw End → Post Draw
→ Draw GUI Begin → Draw GUI → Draw GUI End
```

`GMAsync` owns FIFO delivery for queued HTTP, networking, audio, platform, and extension callbacks. It scopes `async_load` to each delivered Async event. Godot signals that affect GameMaker ordering—such as supported collision, timer, animation, HTTP-completion, and audio-finished signals—must be queued through the manager identified by `architecture_policy.json`; user-authored native callbacks are outside this ordering contract unless they use the same queue.

The current GameMaker-facing phase contract and known deviations live in [`runtime_managers.md`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/runtime_managers.md). GameMaker’s reference order is linked from that canonical document.

## State and persistence boundaries

Runtime state has three practical ownership levels:

| Scope | Examples | Expected lifetime |
| --- | --- | --- |
| Static compatibility facade | Globals, handles, registries and compatibility helper state still owned by `gml_runtime.gd` | Across generated room scene changes |
| Autoload manager buckets | Domain registries, queue metadata and future migrated runtime state | Across generated room scene changes |
| Room/object scene state | Layer nodes, object instances, transient draw/collision data | Normally one room or frame unless explicitly preserved |

Persistent **instances** are reparented across generated room transitions. Their instance creation code is not rerun after restoration. Full persistent **room** state is not preserved: the generated scene enters again and lifecycle/room creation behavior runs, with a runtime warning. This is a deliberate, reported deviation rather than silent parity.

One-frame input edges, collision pairs, transient draw state, room-local layers, and non-persistent instances should be reset at their documented frame or room boundary. Add a regression test whenever custom runtime work moves state between ownership levels.

## Conversion evidence and trust model

The `gm2godot/` directory is also the evidence bundle for a conversion:

| Artifact | When it exists | Use it for |
| --- | --- | --- |
| `conversion_attempt.json` (format 1) | Every terminal attempt after destination preflight | Latest terminal state, named step ledger, failure/cancellation context, and the canonical-manifest digest relationship |
| `conversion_manifest.json` (format 2) | Trustworthy success or usable partial conversion | Source metadata, enabled converters, resources, generated paths, source maps, generated-file hashes, architecture policy and path-collision diagnostics |
| `conversion_diagnostics.json` / `.md` | Conversion/report pipeline | Structured warnings, errors, unsupported APIs, source locations, workarounds and outcome |
| `architecture_policy.json` (format 1) | Conversion policy publication | Project feature scan and selected runtime/backend policies |
| `platform_capability_report.json` / `.md` | Static report generation | Target permissions, export presets, optional plugins and platform-service gaps |
| `extension_compatibility_report.json` | Extension metadata conversion | Native files, discovered functions, mappings, generated stubs and extension diagnostics |
| `godot_validation_report.json` (format 1) | `validate` with Godot validation enabled | Destination-project import, loadable-resource scan and optional main-scene boot results |
| `*.gd.gmlmap.json` | GML source-map emission | Mapping generated GDScript lines back to GameMaker source/event context |

Important trust rules:

- Unsafe destinations rejected during preflight are not modified and do not receive an attempt ledger.
- A partial canonical manifest is written only when every requested converter step completed; its partiality comes from skipped or failed resources.
- `conversion_attempt.json` is committed before `conversion_manifest.json`. Each file replacement is atomic, but the pair is not one multi-file atomic transaction.
- Consumers must compare `conversion_attempt.json` → `canonical_manifest.sha256` with the actual canonical manifest. A mismatch means publication was interrupted.
- `canonical_manifest.status = preserved` is transaction-relative. It does not prove that an older manifest describes the destination after a failed or cancelled attempt.
- `generated_files` describes files changed from the conversion’s initial output snapshot; it intentionally does not claim ownership of every unchanged pre-existing file.

The exact schemas and transaction rules are defined by [`conversion_manifest.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/conversion_manifest.py), [`conversion_outcome.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/conversion_outcome.py), and their [manifest tests](https://github.com/Infiland/GM2Godot/blob/main/tests/test_conversion_manifest.py).

## Extension mappings and platform bridges

GM2Godot does not guess how a native GameMaker extension, SDK, storefront, ad network, or analytics library should behave in Godot. Unmapped extension calls are not emitted as raw GDScript.

Put an explicit mapping file at the GameMaker project root:

```json
{
  "functions": {
    "ads_show_rewarded": {
      "target": "AdBridge.show_rewarded",
      "min_args": 1,
      "max_args": 1
    },
    "analytics_event": "AnalyticsBridge.event"
  }
}
```

The target becomes the emitted Godot call target. Back it with a reviewed script, addon, autoload, or GDExtension that handles platform permissions and SDK setup. For repeat conversion, keep that implementation outside `res://addons/gm2godot_extensions/`, because that subtree is generated.

GM2Godot emits disabled-by-default stubs under `res://addons/gm2godot_extensions/<extension>/`. Their methods call `push_error()` until a project-specific implementation replaces the behavior. Platform-service hooks and extension async schemas can route results through the generated `GMAsync` queue, preserving callback payload context and `async_load` scoping.

Use the full mapping, platform-hook, and callback-schema contract in [`extension_compatibility.md`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/extension_compatibility.md). Always inspect `extension_compatibility_report.json` before enabling an extension on an export target.

## Known deviations to review before shipping

| Area | Current behavior |
| --- | --- |
| Precise collision masks | Precise requests are reported, but runtime collision uses generated shape bounds; pixel-perfect mask parity is not implemented. |
| Persistent rooms | Persistent instances are carried across room changes, but full persistent room state is not retained. |
| Shaders and GPU state | GameMaker GLSL ES and Godot shader language/state do not map one-to-one; generated output needs visual review. |
| Native extensions and platform services | Closed binaries, entitlements, permissions and SDK initialization require explicit reviewed Godot integrations. |
| `game_end` | Maps to `SceneTree.quit()`; platform-specific close prompts and window behavior are not emulated. |
| Custom Godot callbacks/signals | Only generated manager queues participate in the GameMaker ordering contract. Direct custom callbacks can observe a different order. |
| Architecture feature detection | Policy selection is based on indexed project metadata and GML feature scanning. It guides review; it is not a runtime-equivalence proof. |

The complete and frequently changing coverage matrix belongs on [Compatibility and Limitations](Compatibility-and-Limitations) and in the repository’s [`todo-list/`](https://github.com/Infiland/GM2Godot/tree/main/todo-list). Do not infer support merely because a function transpiles or a resource loads.

## Validate a generated project

Use the exact pinned Godot build for resource and runtime validation:

```bash
python main.py validate \
  --godot-project /path/to/GodotProject \
  --godot-bin /path/to/Godot-4.7.1 \
  --godot-boot-frames 120 \
  --fail-on-unsupported
```

Validation imports supported asset types, loads every `.gd`, `.tscn`, `.tres`, and `.gdshader` resource under the destination project except `.godot/`, and can boot the configured main scene for the requested frame count. Read the first warning/error in `gm2godot/godot_validation_report.json`, then correlate it with conversion diagnostics and any `.gmlmap.json` source map.

For report interpretation and failure recovery, continue to [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting). For implementation changes, use [Contributing and Testing](Contributing-and-Testing) and preserve the runtime/architecture contracts covered by the Godot-backed tests.

---

[Home](Home) · [Quick start](Quick-Start-Conversion) · [Compatibility](Compatibility-and-Limitations) · [Diagnostics](Diagnostics-and-Troubleshooting)
