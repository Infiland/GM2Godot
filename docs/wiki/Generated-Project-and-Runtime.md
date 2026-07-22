# Generated Project and Runtime

> **Applies to:** GM2Godot 0.7.45 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-22

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
│   ├── timelines/
│   ├── conversion_attempt.json
│   ├── conversion_manifest.json
│   ├── conversion_diagnostics.json / .md
│   ├── architecture_policy.json
│   └── other registries and compatibility reports
├── fonts/
├── included_files/
├── notes/
├── objects/
├── paths/
├── rooms/
├── scripts/
├── shaders/
├── sounds/
├── sprites/
└── tilesets/
```

GM2Godot treats these directories as managed output roots:

- `addons/gm2godot_extensions/`
- `fonts/`, `gm2godot/`, `included_files/`, `notes/`, `objects/`, `paths/`, `rooms/`, `scripts/`, `shaders/`, `sounds/`, `sprites/`, and `tilesets/`

The top-level `default_bus_layout.tres`, `icon.ico`, and `icon.png` are managed files. `project.godot` is jointly managed: GM2Godot can update the generated `GM*` autoload entries and, when a room is generated, set `run/main_scene` from the first GameMaker `RoomOrderNodes` entry. Existing unrelated project settings and unrelated autoloads are preserved.

### Included Files and file reads

GameMaker Included Files from `datafiles/` are emitted under `res://included_files/`. Each relative path uses GameMaker's packaged lookup form: ASCII `A`–`Z` is lowercased and spaces become underscores, including nested directory components; other characters are preserved.

For relative file and buffer reads, the generated runtime checks the exact `user://gm2godot/<path>` first and then the normalized `res://included_files/<path>`. Writes target user storage. A saved user file therefore overrides its packaged default, and deleting the saved copy reveals the packaged file again. `file_exists()`, text-file reads, and `buffer_load()` share this precedence.

When source paths collapse to the same packaged name, or when one normalized file path would block another file's directory, GM2Godot reserves natural names and deterministically assigns `_2`, `_3`, and later suffixes before the extension. The emitted files, asset registry, and conversion manifest use the same assignments. `GM2GD-INCLUDED-FILE-PATH-COLLISION` reports the mapping; rename these conflicts in GameMaker because normalized lookup cannot distinguish every original alias. Publication also rejects redirected or non-regular paths in the managed `included_files/` output tree instead of writing through them.

Unchanged-generation receipt validation and changed-generation staging keep at most twice the configured worker count unfinished. The source plan and completed receipt map still scale with the Included File count, but queued futures and submission bookkeeping do not. Once cancellation or the first terminal worker failure is observed, GM2Godot admits no further source work, cancels pending tasks where possible, drains only the bounded running remainder, and leaves the previous public generation unchanged.

When a changed generation retains the same planned paths, immutable source-content receipts flow into copying and staged-tree capture instead of rereading bytes already proven for that attempt. Reuse remains bound to the exact source path and handle, assigned path, staged and public output identities, transaction, and generation. GM2Godot still hashes both the source and published tree at the final pre-commit boundary; any same-size mutation, replacement, redirection, hard-link, mount, or directory swap fails closed and restores the previous complete root/registry pair. The deterministic single-file payload bounds are 5x reads for an initial generation, 4x for an unchanged generation, and at most 8x for a changed generation.

`res://included_files/` and `res://gm2godot/gml_included_file_registry.gd` form one recoverable converter-owned generation. Before replacing either public path, GM2Godot durably publishes `.gm2godot-included-files-transaction.json`, which records the exact previous and staged identities, bytes, hashes, and transaction paths. Format v2 stores tree entries as strict compact rows with fixed-width integer fields; recovery continues to accept canonical format-v1 journals and commit markers. After both new paths have been published and verified, GM2Godot durably publishes `.gm2godot-included-files-commit.json`; the marker embeds the complete cleanup manifest so recovery remains possible if journal retirement was interrupted. At the start of the next Included Files conversion, a prepared transaction with no matching commit marker is rolled back to the complete previous pair; a transaction with the matching marker is verified as the complete new pair and its cleanup is finalized. The public `res://` paths do not change, so existing projects need no path migration.

The two public-path moves are not one indivisible filesystem syscall. A format-v2 generated registry therefore records the expected byte count and SHA-256 for every emitted file. The first generated `GMRuntime` autoload establishes integrity before script-registry initialization and before the main scene: it parses every receipt strictly, then hashes emitted payloads sequentially in deterministic registry order using fixed 1 MiB chunks. Trust is all-or-nothing. A missing or receiptless registry, malformed receipt, absent payload, size mismatch, SHA-256 mismatch, or transaction journal leaves the complete packaged generation unavailable to relative GML file APIs instead of exposing a verified subset or falling through to a loose `res://included_files/` path. Rerun conversion to replace a legacy receiptless runtime registry; this does not remove format-v1 journal and commit-marker recovery support.

Startup prevalidation performs one full read of every emitted Included File, so startup time is proportional to their total byte count while hashing memory remains bounded to one 1 MiB chunk. After trust is established, exact and canonical path resolution, `file_exists()`, text reads, and buffer loads use receipt-cache and byte-count checks and do not checksum the payload again on first access. `gml_included_file_integrity_status()` reports the registry, entry, verified-entry, hash-attempt, hashed-byte, and hashing-time counters for diagnostics and performance tests. Verification is deliberately completed on the ordered startup path rather than racing file calls against background workers. User-file overrides retain their normal precedence, and explicit `res://` paths remain explicit engine paths.

The runtime contract follows the official [GameMaker LTS Included Files](https://manual.gamemaker.io/lts/en/Settings/Included_Files.htm) and [file-area precedence](https://manual.gamemaker.io/lts/en/Additional_Information/The_File_System.htm) documentation. Its implementation uses the exact Godot 4.7 [FileAccess](https://docs.godotengine.org/en/4.7/classes/class_fileaccess.html), [HashingContext](https://docs.godotengine.org/en/4.7/classes/class_hashingcontext.html), and [Autoload](https://docs.godotengine.org/en/4.7/tutorials/scripting/singletons_autoload.html) contracts; Godot's [thread-safe API guidance](https://docs.godotengine.org/en/4.7/tutorials/performance/thread_safe_apis.html) is why generation trust is established on the ordered startup path instead of sharing mutable dictionaries with worker tasks.

Recovery and publication run under a non-blocking operating-system lock stored at `.gm2godot-included-files.lock` in the destination project. A second cooperating GM2Godot converter fails without modifying the generation and may be retried after the first converter exits. The persistent lock file itself is not evidence that a converter is still running; ownership is the operating-system lock, not file existence. A fully synced journal temporary is promoted before orphan cleanup, while partial or ambiguously named records are preserved. Canonical recovery records are limited to 16 MiB and are rejected from their verified file size before payload parsing if they exceed that bound. For a changed generation, GM2Godot renders byte-exact format-v2 journal and commit stand-ins from the planned paths, source byte counts, fixed-width metadata, and registry shape before creating the payload stage; both actual records must retain those exact sizes before publication. Malformed, oversized, ambiguous, or unknown replacements at reserved transaction paths are preserved and fail closed instead of being guessed at or deleted.

Do not convert while a live game, editor session that is actively loading Included Files, or non-cooperating writer is accessing the generated project. Those processes do not acquire the converter lock, and a live runtime can retain already-open files or startup-established verification from before a publication. Close them, run conversion or automatic recovery to completion, and then reopen the project.

Managed generation trees and the registry must remain on the Godot project's filesystem. Capture and recovery reject cross-device entries and nested mount points; on Linux, open-descriptor mount IDs also detect same-filesystem bind mounts that ordinary mount-point checks can miss. Descriptor-capable hosts retain the open directory chain and verify each direct parent/child binding before and after traversal instead of repeatedly rechecking every ancestor. The native Windows path fallback verifies each current directory through its complete path. Both paths therefore keep binding work linear in tree depth while retaining deterministic ordering and fail-closed replacement and concurrent-mutation checks. Cleanup rechecks filesystem boundaries before traversing recorded directories and preserves the tree if a mount or unknown replacement appears. Recorded file receipts are streamed in 1 MiB chunks before and after cleanup quarantine, so receipt verification never buffers an entire Included File in Python memory.

On Windows, the path-based transaction fallback rejects real NTFS junctions at the managed root, inside the tree, at the registry directory, and at staging or backup boundaries without traversing their targets. Native calls use extended-length paths, and transaction moves request write-through completion. Recovery cleanup walks only entries recorded in the durable snapshot and moves each one through a fixed transaction-derived tombstone before deletion; it never treats an owned directory identity as authority to delete unknown descendants. A read-only file is made writable only at that deterministic tombstone, its attribute is restored if deletion fails, and a file with multiple hard links is retained rather than changing the shared attribute visible through an external alias. Native `windows-2025` tests cover those junctions and read-only cleanup after success, commit failure, cancellation, rollback, process exit, and restart recovery. Windows does not expose an unprivileged, documented directory-deletion flush equivalent: a machine power loss may replay a hidden cleanup tombstone after its deletion, but cannot turn that tombstone back into either public generation path. Preserve and report unexpected hidden transaction debris instead of deleting it by hand. These checks do not make non-cooperating concurrent namespace mutation safe.

Subprocess tests terminate conversion without running Python cleanup at every forward publication boundary, plus the quarantine/removal boundaries for owned backup, staging, stable-record, and temporary-record cleanup. Every forward boundary is recovered with both the existing format-v1 records and the generated format-v2 records. Recovery must expose the exact previous generation before the commit marker or the exact new generation after it, never a mixed pair. The registry receipt and runtime-read contract is also covered by an end-to-end smoke test using the exact supported Godot 4.7.1 build.

### Destination-wide workspace foundation

Version 0.7.38 added a reusable `ManagedOutputWorkspace` for the complete managed-output transaction planned in later releases. It creates a private transaction directory under `.gm2godot-managed-output/` only after binding the destination, workspace parent, and stage and proving that all three share the destination device and mount. A persistent `.gm2godot-managed-output.lock` file carries one non-blocking operating-system lock for the whole session; file existence alone does not mean a session is active.

Snapshot and streaming-copy operations accept an exact normalized relative-path allowlist. They reject symbolic links, Windows junctions or other reparse points, hard-linked regular files, nested mounts, cross-device entries, and changed directory bindings without scanning an entire managed root for implied ownership. Bounded canonical markers bind the workspace parent and stage to the destination identity and 32-character transaction identifier. Cleanup first validates the complete private tree, preserves unknown or changed lookalikes, and removes only identity-verified transaction state. Cancellation and ordinary staging errors therefore leave public managed and user-owned destination bytes and modes unchanged.

This is intentionally foundation-only in 0.7.38: `Converter`, CLI orchestration, finalizers, canonical manifests, and individual converters still use their existing destinations. The workspace does not yet define a complete generation inventory, publish or recover public output, alter the conversion-manifest schema, or implement stale logical-resource deletion.

The implementation follows Python 3.12's documented [`dir_fd`, `follow_symlinks`, and file-descriptor capability](https://docs.python.org/3.12/library/os.html#files-and-directories) contracts, [`fcntl.flock`](https://docs.python.org/3.12/library/fcntl.html#fcntl.flock) on POSIX, and [`msvcrt.locking`](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.locking) on Windows. Native Windows bindings use Microsoft's [`CreateFileW`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew) no-follow/reparse and sharing semantics, [`GetFileInformationByHandleEx`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex) identities, non-replacing write-through [`MoveFileExW`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw) moves, and the documented [reparse-point model](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points). No generated GDScript or GameMaker source interpretation changes: the target remains the official [GameMaker LTS 2026 Included Files](https://manual.gamemaker.io/lts/en/Settings/Included_Files.htm) and [file-area](https://manual.gamemaker.io/lts/en/Additional_Information/The_File_System.htm) behavior, with exact Godot 4.7.1 [`FileAccess`](https://docs.godotengine.org/en/4.7/classes/class_fileaccess.html), [`DirAccess`](https://docs.godotengine.org/en/4.7/classes/class_diraccess.html), and [command-line validation](https://docs.godotengine.org/en/4.7/tutorials/editor/command_line_tutorial.html).

### Complete generation inventory

The preceding generation-inventory foundation added one immutable model for staging carry-forward, staged/public validation, canonical-manifest rendering, and manifest publication guards. Entries are sorted by normalized NFC destination-relative paths using `/` separators and record the output kind, a producing `converter_step` or explicit `shared_owner`, byte count, `sha256:` digest, and exact mode. `project.godot` uses the `project_configuration` shared-owner class because converter steps update only GM2Godot-owned settings while unrelated settings remain user-controlled. Shared generated runtime and evidence files use named shared-owner classes instead of being assigned arbitrarily to one converter.

The format-v2 conversion manifest retains its stable filename and top-level format version. It adds `generation_inventory: {"format_version": 1, "entries": [...]}`. `generated_files` remains for existing consumers, but is now a complete path/kind/digest projection of that same inventory rather than a start-of-invocation fingerprint diff; its canonical-manifest compatibility row remains `sha256: "self"`. The inventory itself excludes the canonical manifest to avoid a self-digest cycle, and also excludes the latest-attempt ledger, `.godot/`, destination/artifact locks, transaction and recovery records, private stages/backups, and files outside the documented managed paths. Canonical bytes use Python 3.12's documented [`json.dumps(..., sort_keys=True)`](https://docs.python.org/3.12/library/json.html#json.dumps) behavior with fixed UTF-8, indentation, ASCII escaping, and a trailing newline.

The first inventory-aware run migrates an existing format-v2 manifest through a 32 MiB canonical-record limit and at most 100,000 entries, then completes its allowlist from the documented managed roots. Absolute, escaping, structurally ambiguous, case-colliding, unsafe native-Windows, malformed, redirected, mounted, cross-device, non-regular, or multiply-linked entries are rejected before staging or artifact publication. A selective run carries every disabled converter's prior inventory entries byte-, mode-, and digest-exactly; shared entries provide the baseline for later joint updates. Canonical bytes are rendered from one frozen inventory, and publication rehashes that same topology and content before and after committing the manifest so a same-size mutation with restored timestamps is still detected.

### Recoverable destination-wide publisher

Version 0.7.40 added an internal publisher that consumes one verified `ManagedOutputWorkspace` plus frozen previous and desired inventories; it never derives ownership from mutable public paths. Before the first public move, a strict bounded journal binds the destination, workspace, exact inventory records, required directory identities, every desired stage and prior backup, the current public identities, and the canonical manifest/attempt receipts. New directories and managed file creates, replacements, and removals use verified no-follow bindings and same-filesystem namespace moves. The attempt is installed after managed files and the canonical manifest is last. Only after the complete desired inventory, evidence bytes, modes, digests, and identities verify does one durable generation pointer select the new generation.

Before that pointer, ordinary failure rolls mutations back in reverse order and recovery restores and verifies the prior managed inventory plus its exact canonical evidence. After it, recovery accepts only the complete selected new inventory/evidence set and finishes identity-bound cleanup. Unknown, redirected, mounted, multiply-linked, replaced, or concurrently changed entries are preserved and fail closed. If rollback cannot finish safely, the journal, stage, backups, and displaced entries remain available and a separate bounded `.gm2godot-managed-output-recovery.json` record under the private workspace parent reports the transaction, affected paths, selected generation, error, and safe retry call; it is not the canonical manifest or latest-attempt ledger.

The implementation follows Python 3.12's [`os` descriptor-relative and replacement contracts](https://docs.python.org/3.12/library/os.html#files-and-directories), POSIX Issue 8 atomic [`rename`/`renameat`](https://pubs.opengroup.org/onlinepubs/9799919799/functions/rename.html) and file/directory [`fsync`](https://pubs.opengroup.org/onlinepubs/9799919799/functions/fsync.html) semantics, and Microsoft's same-volume [`MoveFileExW`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw) `MOVEFILE_WRITE_THROUGH`, [`FlushFileBuffers`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers), and [reparse-point](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points) contracts. Every stage, backup, journal, recovery artifact, generation record, and namespace move remains on the destination filesystem; `MOVEFILE_COPY_ALLOWED` and every other cross-volume copy/delete fallback are intentionally disabled.

The compatibility baseline was rechecked against the official [GameMaker LTS 2026 Included Files](https://manual.gamemaker.io/lts/en/Settings/Included_Files.htm), [file-area precedence](https://manual.gamemaker.io/lts/en/Additional_Information/The_File_System.htm), and [2026.0 release notes](https://releases.gamemaker.io/release-notes/2026/0), whose current release is IDE 16 with GMS2 Runtime 23. SNAP (IDE 15 metadata) and Adding (IDE 16 metadata) remain pinned conversion fixtures. Generated output is imported, resource-loaded, and booted with the official [Godot 4.7.1 maintenance release](https://godotengine.org/article/maintenance-release-godot-4-7-1/) built from `a13da4feb`, using its documented [command-line](https://docs.godotengine.org/en/4.7/tutorials/editor/command_line_tutorial.html), [`FileAccess`](https://docs.godotengine.org/en/4.7/classes/class_fileaccess.html), and [`DirAccess`](https://docs.godotengine.org/en/4.7/classes/class_diraccess.html) contracts.

Version 0.7.41 makes this the production `Converter.convert()` path used by GUI, direct-library, and CLI conversion. Recovery and the destination-wide lock run before mutating preflight. That release copied the previous complete inventory into the private stage so enabled converters could replace output without silently adopting the then-separate stale-resource deletion policy; disabled and shared output remained exact. The staged Godot path is passed to project initialization/settings, every selected converter and registry, architecture and diagnostic reports, CLI static reports when `--report-dir` is the project itself, inventory capture/validation, and canonical-manifest construction.

After converter and finalizer work reaches a trustworthy `success` or `partial` candidate, GM2Godot freezes and rehashes the stage, reads the exact staged manifest/attempt bytes through verified bindings, performs one final cooperative cancellation check, and enters recoverable publication. Runtime exceptions, finalizer failures, validation failures, or cancellation before that point discard only verified private state. The prior public inventory, canonical diagnostics, and architecture policy remain byte- and mode-exact; only `conversion_attempt.json` is advanced, with `canonical_manifest.current_output: "verified"` after transactionally checking the preserved generation. Once publication starts, cancellation is no longer accepted as a rollback claim: the publisher completes its durable old-or-new decision.

Version 0.7.42 adds deterministic phase declarations for every durable publication boundary. Real project-setting, script, object, registry, diagnostic, manifest, and attempt mutations are terminated without Python cleanup after each observed forward move, reverse rollback, recovery retry, and private cleanup operation. Every restart verifies the exact prior generation before the durable pointer or the exact desired generation after it, including canonical manifest and attempt digests; another recovery must make no changes. Native tests use byte, mode, identity, device, and namespace assertions rather than timing thresholds.

### Bound method receiver context

Version 0.7.44 represents every generated receiver-aware function with explicit metadata. A generated method callable declares hidden `self` and `other` arguments; a constructor declares the new struct plus its constructor `other`; ordinary Godot object methods declare no hidden GML receiver arguments. The runtime therefore never uses `Callable.is_standard()` or `is_custom()` to guess generated arity. It retains the Godot callable owner separately from the semantic GameMaker binding so an unbound script reference remains alive without pretending that its generated `RefCounted` wrapper is `method_get_self()`.

Each transpiled dynamic call supplies the current GML `self`. A bound callee receives that value as `other`, so nested method calls advance context one scope at a time and array/struct callback helpers preserve the scope that invoked the callback. Script registry entries keep separate ordinary and receiver-aware call paths: direct asset calls retain caller `self`/`other`, while `method(target, script_reference)` copies the receiver contract and uses `target` as the rebound `self` without consuming a user argument.

`new` has a separate checked path so receiver injection cannot be omitted or applied twice. The newly allocated struct is always constructor `self`. For an unbound script constructor, `other` is the scope that called `new`; for a constructor rebound with `method`, GameMaker's bound-constructor exception makes the bound scope `other`. Parent constructor calls reuse the same new struct and propagate constructor context. Missing receiver metadata and unmarked custom Godot callables fail closed with a runtime error.

These rules follow GameMaker LTS [Method Variables](https://manual.gamemaker.io/lts/en/GameMaker_Language/GML_Overview/Method_Variables.htm), [Instance Keywords](https://manual.gamemaker.io/lts/en/GameMaker_Language/GML_Overview/Instance_Keywords.htm), and [`method`](https://manual.gamemaker.io/lts/en/GameMaker_Language/GML_Reference/Variable_Functions/method.htm). Godot behavior is pinned to the exact 4.7.1 [`Callable`](https://docs.godotengine.org/en/4.7/classes/class_callable.html) contract—where lambdas, bound arguments, global functions, and Variant methods can all be custom callables—and its [GDScript lambda](https://docs.godotengine.org/en/4.7/tutorials/scripting/gdscript/gdscript_basics.html#lambda-functions) rules.

### Successful stale-resource invalidation

Version 0.7.43 defines logical ownership for the five resource families in #715. An object owns the collision-safe resource directory containing its required `.tscn` and `.gd` plus any `.gd.gmlmap.json`; a room owns its collision-safe directory containing the required `.tscn` and optional generated `.gd`; a sprite owns its collision-safe scene/frame directory; a shader owns its exact `.gdshader`; and a timeline owns each collision-safe `gm2godot/timelines/<stem>_<moment>.gd` action script named by its metadata. These paths remain physically owned by the corresponding generation-inventory converter step.

When one of the selected object, room, sprite, shader, or asset-registry/timeline converters runs, its prior converter-owned inventory entries are not copied into the private candidate stage. Current source resources then regenerate their complete outputs. A resource that is missing, rejected, blocked by transpilation, skipped, failed, or absent from the authoritative YYP leaves no logical output in the desired inventory; the existing destination-wide publisher commits those removals with all creates/replacements and canonical evidence under the same recoverable old-or-new decision. This gives multi-file objects, rooms, and sprites generation-level atomicity without deleting public files directly from a converter.

Before the runtime asset registry is rendered, object/room/sprite/shader rows are checked against the confined candidate inventory. Rows whose required outputs are absent are omitted, and missing timeline action-script references are stripped while retaining the timeline's supported metadata. Canonical manifest resources are reconciled against the same frozen inventory used to render `generated_files`. If room conversion leaves a previous `run/main_scene` pointing to a missing `res://rooms/` output, that one GM2Godot-managed setting is removed; unrelated project settings and non-room startup scenes remain unchanged.

Disabled converters retain the prior byte-, mode-, and digest-exact inventory by design, so a selective run must include `asset_registry` when its runtime registry also needs refreshing. A failed or cancelled run before the durable decision still exposes the complete prior generation, not the candidate's planned deletions. Files outside the documented managed roots are never deletion candidates. Unknown files added inside a managed root make the frozen topology disagree with its manifest and fail closed while preserving the file; GM2Godot does not infer ownership from location alone after a canonical inventory exists.

The source-of-truth policy follows GameMaker LTS 2026's official [Project Format](https://manual.gamemaker.io/lts/en/Additional_Information/Project_Format.htm): the root YYP describes project resources, while each YY describes one resource and its associated files. Shader ownership follows the LTS [Shader Editor](https://manual.gamemaker.io/lts/en/The_Asset_Editors/Shaders.htm) two-stage asset model, and timeline action ownership follows the LTS [Timeline Editor](https://manual.gamemaker.io/lts/en/The_Asset_Editors/Timelines.htm) moment/code model. Validation uses Godot 4.7's documented [`--import`](https://docs.godotengine.org/en/4.7/tutorials/editor/command_line_tutorial.html) scan and [import process](https://docs.godotengine.org/en/4.7/tutorials/assets_pipeline/import_process.html), under which project assets are rescanned from files while imported cache state lives under `.godot/` and can be regenerated.

`Converter.convert()` is the direct-library contract used by the GUI worker and CLI. A cooperative `conversion_running` flag cleared during converter/finalizer/validation work, or during recovery before new work begins, yields `cancelled` only before publication and leaves the verified prior generation public. Once publication starts, cancellation is deferred until the old-or-new decision and cannot relabel a committed generation. Exceptions expose `last_outcome`, but public trust comes from the canonical evidence plus any recovery artifact—not from return-versus-exception alone.

If `.gm2godot-managed-output-recovery.json` is present under the private workspace parent:

1. Close the Godot editor/game and every process that can write the destination.
2. Preserve the recovery artifact, journal, named stage, generation records, and affected public paths unchanged.
3. Read `transaction_id`, `affected_paths`, `selected_generation`, `error`, and `next_step`. `previous` means rollback is selected, `desired` means the commit decision already selected the new generation, and `unknown` means neither generation may be assumed.
4. Retry conversion or call `recover_managed_output_generation(destination_path)` once the underlying permission/device problem is fixed. Repeat recovery is idempotent after completion.
5. If recovery still rejects identity, redirection, mount, hard-link, or namespace state, back up the destination and report the preserved artifacts; do not edit the journal or pointer to force acceptance.

The recovery artifact is canonical JSON bounded to 1 MiB, its error to 4,096 characters, and its displayed affected-path list to 100 entries; the full count and truncation flag remain explicit. Crash-interrupted cleanup resumes only for the detached stage whose transaction and filesystem identity match the journal. This does not make a live Godot process or non-cooperating writer safe.

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

### Precise sprite collision masks

Version 0.7.45 derives Precise collision geometry from the alpha channel of each converted RGBA frame, clips it to the inclusive GameMaker bounding box, and includes pixels whose alpha is strictly greater than `collisionTolerance`. A static Precise mask unions every subimage before converting contiguous pixels into exact rectangle geometry. Precise Per Frame keeps separate geometry for each subimage; the generated sprite scene switches enabled shapes on `AnimatedSprite2D.frame_changed`, and generated `image_index` handling explicitly synchronizes the same frame.

The visual and mask use the GameMaker origin as their common local reference. The object transform then applies position, `image_xscale`, `image_yscale`, and `image_angle` to both. Collision events, place/position and motion checks, and point/rectangle/line/circle single-result and list APIs read the active transformed polygons. An advanced query with `precise = false` uses the transformed GameMaker mask bounds; `precise = true` uses precise pixels when the target has them.

If frame bytes are unreadable, dimensions or bounds disagree, tolerance is invalid, or exact decomposition exceeds 16,384 rectangles, conversion emits `GM2GD-SPRITE-PRECISE-MASK-FALLBACK` and retains the prior bounding-box fallback when that box is valid. Runtime-created/modified sprite masks, `mask_index` overrides, skeletal meshes, tile-set masks, and GameMaker physics fixtures remain separate compatibility areas.

This follows the GameMaker LTS [Sprite Editor collision-mask rules](https://manual.gamemaker.io/lts/en/The_Asset_Editors/Sprites.htm), [collision rotation/scaling and precise-query semantics](https://manual.gamemaker.io/lts/en/GameMaker_Language/GML_Reference/Movement_And_Collisions/Collisions/Collisions.htm), and [`sprite_collision_mask`](https://manual.gamemaker.io/lts/en/GameMaker_Language/GML_Reference/Asset_Management/Sprites/Sprite_Manipulation/sprite_collision_mask.htm). Generated behavior is validated against Godot 4.7.1 [`AnimatedSprite2D.frame_changed`](https://docs.godotengine.org/en/4.7/classes/class_animatedsprite2d.html), [`CollisionShape2D`](https://docs.godotengine.org/en/4.7/classes/class_collisionshape2d.html), and [`Transform2D`](https://docs.godotengine.org/en/4.7/classes/class_transform2d.html).

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
| `conversion_manifest.json` (format 2) | Trustworthy success or usable partial conversion | Source metadata, enabled converters, resources, complete format-v1 generation inventory, source maps, generated-file hashes, architecture policy and path-collision diagnostics |
| `conversion_diagnostics.json` / `.md` | Conversion/report pipeline | Structured warnings, errors, unsupported APIs, source locations, workarounds and outcome |
| `architecture_policy.json` (format 1) | Conversion policy publication | Project feature scan and selected runtime/backend policies |
| `platform_capability_report.json` / `.md` | Static report generation | Target permissions, export presets, optional plugins and platform-service gaps |
| `extension_compatibility_report.json` | Extension metadata conversion | Native files, discovered functions, mappings, generated stubs and extension diagnostics |
| `godot_validation_report.json` (format 1) | `validate` with Godot validation enabled | Destination-project import, loadable-resource scan and optional main-scene boot results |
| `*.gd.gmlmap.json` | GML source-map emission | Mapping generated GDScript lines back to GameMaker source/event context |

Important trust rules:

- Unsafe destinations rejected during preflight are not modified and do not receive an attempt ledger.
- A partial canonical manifest is written only when every requested converter step completed; its partiality comes from skipped or failed resources.
- `conversion_attempt.json` and the optional `conversion_manifest.json` are published as one recoverable generation through a verified `gm2godot/` directory binding. A durable `.gm2godot-conversion-transaction.json` records the complete previous and desired pair before either public file changes; `.gm2godot-conversion-generation.json` is the sole commit pointer.
- Recovery under `.gm2godot-conversion.lock` restores the complete previous pair when the transaction has no matching pointer, or verifies and finalizes the complete new pair after the pointer switch. The public filenames, format-v1 attempt schema, and existing format-v2 manifest fields do not change; `generation_inventory` is additive.
- Consumers should still compare `conversion_attempt.json` → `canonical_manifest.sha256` with the actual canonical manifest as a defense against later replacement or corruption. After migration to the generation pointer, a digest mismatch is rejected recovery state, not a normal interrupted-publication result.
- `canonical_manifest.status = preserved` is transaction-relative. It does not prove that an older manifest describes the destination after a failed or cancelled attempt.
- `generation_inventory.entries` is the complete desired managed generation, including exact unchanged carry-forward for disabled converter steps and jointly managed `project.godot`. `generated_files` is the backward-compatible projection of that same frozen inventory.

The first 0.7.32 publication accepts a legacy pair only when its existing attempt digest agrees with the canonical bytes, or both files are absent. A mismatched, malformed, redirected, mounted, hard-linked, or otherwise replaced pair/recovery record is preserved and rejected for manual inspection. Recovery records are canonical JSON capped at 32 MiB and each embedded artifact is capped at 64 MiB uncompressed, so damaged or hostile state cannot request unbounded parsing.

The exact schemas and transaction rules are defined by [`generation_inventory.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/generation_inventory.py), [`conversion_manifest.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/conversion_manifest.py), [`conversion_artifact_generation.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/conversion_artifact_generation.py), [`conversion_outcome.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/conversion_outcome.py), and their [inventory](https://github.com/Infiland/GM2Godot/blob/main/tests/test_generation_inventory.py) and [manifest tests](https://github.com/Infiland/GM2Godot/blob/main/tests/test_conversion_manifest.py).

### Anchored report publication confinement

`architecture_policy.json`, the `conversion_diagnostics.json` / `.md` pair, and the four CLI static compatibility reports are staged, backed up, published, rolled back, recovered and cleaned through one destination-directory binding retained for each complete operation. Diagnostic snapshots and publication receipts bind both the report root and its exact `gm2godot/` child. The static set commits `gml_manual_scope.md`, `gml_api_compatibility.md`, `platform_capability_report.json`, then `platform_capability_report.md`; ordinary failures restore every prior byte and exact mode rather than invalidating the set. An explicit external report root that does not exist is created one component at a time through its verified parent; each new directory entry crosses the parent durability barrier before creation descends further.

On POSIX hosts with the required APIs, every child lookup and namespace mutation is relative to a no-follow directory descriptor and durability barriers call `fsync()` on that retained descriptor. Replacing the visible `gm2godot/` path therefore makes publication fail, but cannot redirect capture, restore, invalidation, cleanup or rollback into the replacement directory.

On Windows, GM2Godot opens both the report root and the exact captured `gm2godot/` directory with reparse-point inspection and without delete sharing before it creates a stage. Child paths remain safe to resolve while those handles prevent either directory from being relocated; replacement requests use write-through completion. Publishing absence first moves the exact target behind a private write-through tombstone, then removes that tombstone on a best-effort basis. Windows has no documented general equivalent to POSIX directory `fsync`, so directory barriers revalidate the retained handle. This is a confinement and strongest-available write-through guarantee, not a claim of identical power-loss durability; a crash can leave hidden tombstone debris, but cannot restore its old public name.

If a non-Windows host lacks descriptor-relative open, stat, mkdir, rename or unlink, `O_NOFOLLOW`, `O_DIRECTORY`, or descriptor chmod, the transaction selects a `verified_path` fallback before staging. That fallback verifies the root and destination identities before and after each full-path operation. It rejects links and changed directories but narrows rather than eliminates the final non-cooperating path-resolution race. The backend is fixed for the transaction and never downgrades after a stage exists.

The retained directory binding does not lock individual artifact names against a non-cooperating writer. Exact inode, mode, byte and digest checks run after staging, before every ordered mutation, and again at the native replace/unlink boundary. A process that races the final system call can still win the remaining leaf-entry interval on platforms without a suitable handle-relative primitive. Close editors, games and other writers while conversion or recovery is running; unexpected exact-state changes fail the transaction and preserve verified recovery material instead of authorizing an overwrite.

The two diagnostic files retain stable public paths and ordinary-exception rollback, but they are still separate ordered replacements. A hard process or machine crash between their durability barriers can therefore expose one old file and one new file. Treat the pair as belonging to one successful invocation only when their outcome and surrounding attempt evidence agree; a future generation protocol is required for old-or-new crash atomicity across the pair.

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
| Runtime-authored collision masks | Imported static and per-frame precise sprite masks are generated exactly within the documented complexity bound; runtime mask mutation, `mask_index`, skeletal/tile masks, and physics fixtures still need project-specific review. |
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
