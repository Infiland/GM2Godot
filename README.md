# GM2Godot

<img width="802" height="632" alt="screen" src="https://github.com/user-attachments/assets/cedf47f5-6668-44ab-8cf6-959a21afd7fa" />

GM2Godot targets GameMaker LTS 2026 source projects and Godot 4.7.1 output. It converts supported project data and GML through a GUI or headless CLI, with generated Godot runtime helpers, deterministic asset registries, diagnostics, compatibility reports, and fixture-backed regression tests.

[Documentation](https://github.com/Infiland/GM2Godot/wiki) · [Latest release](https://github.com/Infiland/GM2Godot/releases/latest) · [Issues](https://github.com/Infiland/GM2Godot/issues)

## Features

- **Modern Dark Theme UI**: Clean project selection, settings, progress, and logs
- **Headless CLI**: Convert, analyze, validate, and generate compatibility reports for CI workflows
- **GML Transpilation**: Converts supported GMS2+ expressions, scripts, object events, room creation code, macros, extension stubs, and source-map metadata into GDScript
- **Generated Runtime**: Emits `gm2godot/gml_runtime.gd`, runtime managers, asset registries, room/runtime metadata, and compatibility helpers for supported GameMaker APIs
- **Asset Conversion**: Converts GameMaker project resources to Godot format:
  - Sprites, collision masks, animation metadata, and generated scenes
  - Sound effects, audio groups, bus layouts, and runtime playback metadata
  - Fonts, notes, scripts, objects, rooms, tilesets, shaders, paths, authored sequence/timeline playback, asset-backed particles, extensions, texture groups, and options metadata where supported
  - Included Files under `res://included_files/`, with GameMaker packaged-path normalization, `user://gm2godot/`-first read precedence, and deterministic collision-safe suffixes and diagnostics
  - Project settings, game icons, platform options, and validation reports
- **Platform Support**: Converts settings for multiple platforms:
  - Windows
  - macOS
  - Linux
- **Diagnostics and Reports**: Writes structured warnings/errors, compatibility Markdown/JSON, trusted conversion manifests, per-attempt outcome ledgers, architecture-policy reports, and optional headless Godot validation reports
- **Customizable Conversion**: Choose conversion groups or specific converter keys
- **Compatibility Roadmap**: Tracks current and missing GameMaker-to-Godot coverage in [`todo-list/`](todo-list/README.md)

`res://included_files/` and `res://gm2godot/gml_included_file_registry.gd` are published as one recoverable converter-owned generation. A durable journal and commit marker make the next conversion select and verify either the complete previous generation or the complete committed generation after an interruption, while a cooperative per-project lock rejects another GM2Godot converter. While the stable journal exists, relative GML reads fail closed to `user://` instead of observing either public path. During generated `GMRuntime` autoload startup, format-v2 registry entries are verified as one complete generation against their byte counts and SHA-256 hashes in deterministic 1 MiB chunks. Missing, malformed, incomplete, or mismatched generations expose no packaged entries; normal first file access uses the established receipts without hashing the payload again. This adds one bounded-memory startup pass over all emitted Included File bytes. Format-v2 recovery records use compact, fixed-width tree rows whose exact journal and commit sizes are preflighted before payload staging; the 16 MiB cap remains unchanged and format-v1 interruptions remain recoverable. Descriptor-pinned and native Windows path traversal keep binding verification linear in managed-tree depth while retaining no-follow, mount, replacement, and concurrent-mutation rejection. The public `res://` paths remain stable. Do not convert while a live game or a non-cooperating writer is accessing the generated project; they do not participate in the converter lock and may retain already-open or cached state.

Version 0.7.38 also provides the internal destination-wide workspace foundation for the next transaction stages. A `ManagedOutputWorkspace` holds a non-blocking operating-system lock at `.gm2godot-managed-output.lock`, proves that its private transaction directory under `.gm2godot-managed-output/` shares the destination filesystem, and snapshots or copies only an explicit allowlist of regular files. Strict ownership markers bind cleanup to the exact transaction; redirected, mounted, multiply-linked, replaced, or unknown reserved state is preserved with an error instead of traversed or guessed at.

Version 0.7.39 added the next foundation: one immutable complete inventory for the desired managed generation. Each entry records a normalized slash-separated destination-relative path, output kind, producing converter step or explicit shared-owner class, byte count, SHA-256, and exact file mode. The additive `generation_inventory` object in the format-v2 canonical manifest is sorted independently of source enumeration, worker count, and host path separator. It includes unchanged output carried forward from disabled converter steps and jointly managed `project.godot`; `generated_files` remains available to existing consumers as a complete path/kind/digest view.

The inventory excludes `.godot/`, `conversion_attempt.json`, the canonical manifest's self-referential bytes, destination and artifact locks, transaction/recovery records, private stages/backups, and files outside the documented managed roots. Existing format-v2 manifests migrate through bounded parsing plus those roots; malformed, absolute, escaping, redirected, mounted, multiply-linked, or case-colliding state fails closed. Canonical manifest bytes are rendered from one frozen inventory and the same inventory is rehashed before and after manifest publication, including detection of same-size content changes with restored timestamps.

Version 0.7.40 adds the internal destination-wide publisher over that workspace and frozen inventory. It durably records exact prior and desired generation records, verified stage/backup/public identities, canonical manifest and attempt receipts, and required directory bindings before the first public move. Managed creates, replacements, removals, and evidence are installed through same-filesystem no-follow moves with the canonical manifest last; one durable generation pointer then selects the complete new file/evidence set. Before that pointer, ordinary failure and recovery restore the complete previous bytes and modes in reverse order. After it, recovery verifies the new generation and finishes only identity-bound cleanup. Unsafe rollback publishes a separate bounded recovery artifact with transaction, path, selected-generation, and retry diagnostics while preserving exact recovery material.

Version 0.7.41 routes production conversion through that transaction. Recovery and the destination-wide lock precede mutating preflight; the complete prior managed generation is copied into the same-filesystem stage, and every selected converter, project-setting operation, registry, architecture/diagnostic finalizer, optional CLI report set, inventory validator, and canonical-manifest builder receives the staged project path. A trustworthy `success` or `partial` candidate is frozen, rehashed, and committed with its exact manifest and attempt digest. Runtime, finalizer, validation, cancellation, and ordinary publication failures discard verified private state and retain the prior public bytes and modes; their attempt ledger reports a transactionally verified preserved canonical generation instead of overwriting its diagnostics or architecture report.

The final cooperative cancellation check immediately precedes entry into recoverable publication. Cancellation observed before it preserves the prior generation and reports `cancelled`; once publication starts, GM2Godot completes the old-or-new decision and does not later claim cancellation.

Version 0.7.42 classifies every durable destination-wide forward, rollback, restart-recovery, and cleanup boundary as pre- or post-commit, then terminates real converter subprocesses at every observed boundary on native Linux, macOS, and Windows. Restart must expose and verify either the complete prior inventory plus its exact canonical manifest/attempt evidence or the complete desired inventory and evidence; a second recovery is a no-op. Crash-interrupted cleanup resumes only for the detached stage whose identity is bound by the durable journal. Symlinks, hard links, nested mounts and Linux bind mounts, Windows junctions/reparse points, read-only trees, destination/leaf replacement, and unknown state fail closed without changing external or user-owned sentinels. That release kept #715's successful stale logical-resource policy separate and did not make conversion safe beside a live Godot editor/game or non-cooperating namespace writer.

Version 0.7.43 applies that separate policy to selected object, room, sprite, shader, and asset-registry/timeline converters. Their prior owned outputs are not copied into the candidate stage: current authoritative YYP resources regenerate complete private output sets, while unavailable, blocked, skipped, or removed resources contribute no stale files to a successful or partial commit. Objects own their scene, script, and optional source map; rooms own their scene and optional script; sprites own their collision-safe resource directory; shaders own one generated shader; timelines own their collision-safe action scripts. Registry rows, timeline script references, canonical manifest resources, inventory files, and a GM2Godot-managed room startup scene are reconciled to the files that remain. Disabled converters retain their exact prior inventory by design. Failed or cancelled pre-decision runs still preserve the complete prior generation, unrelated files outside documented managed roots remain untouched, and unknown additions inside managed roots fail closed rather than being adopted or deleted.

Version 0.7.44 preserves GameMaker bound-method context across generated GDScript. Receiver-aware callables now declare hidden `self`/`other` metadata explicitly instead of relying on Godot's standard/custom `Callable` classification. Every transpiled dynamic call passes its current `self`; nested methods and callbacks therefore receive invocation-time `other`, while ordinary script calls retain their caller scope. Rebinding a script reference preserves its receiver contract, and constructors inject the new struct exactly once while using the documented caller or bound-constructor scope as `other`. Unmarked custom Godot callables fail closed instead of receiving guessed arguments.

Version 0.7.45 generates alpha-derived pixel geometry for GameMaker Precise and Precise Per Frame sprite masks. Static masks composite all subimages; per-frame masks switch with the displayed image. Generated collision events and point, rectangle, line, circle, position, place, and movement checks share the active transformed geometry, including sprite origin, scale, rotation, `sprite_index`, and `image_index` changes. A structured `GM2GD-SPRITE-PRECISE-MASK-FALLBACK` warning retains the bounding-box fallback when malformed, unreadable, mismatched, or excessively complex source data cannot be represented exactly.

Version 0.7.46 converts authored GameMaker particle systems into stable `.tres` descriptors and instantiates their embedded types and emitters from GML or room particle-layer elements. Generated Godot 4.7.1 particles preserve supported origin, draw order, region, lifetime, stream/burst, shape, motion, colour/alpha, scale, texture, blend, and secondary-spawn metadata, while room ownership deterministically releases systems, emitters, types, and nodes. Legacy attractor, destroyer, deflector, and changer data remains fail-closed with source-linked diagnostics.

Version 0.7.47 converts supported authored sequence asset and parameter tracks into managed `.tres` descriptors and deterministic runtime nodes. Sprite, instance, audio, text, nested-sequence, mapped audio-effect, moment, and broadcast keys preserve playback speed modes, assign/linear interpolation, transforms, draw/action order, and nesting; timeline moment GML runs in frame order without skipped intermediate moments. Unsupported track/key/effect/action types produce source-linked partial-conversion diagnostics instead of being dropped.

Version 0.7.48 parses paired GameMaker GLSL ES shader stages before generating one Godot CanvasItem shader. The supported 2D subset maps `in_Position`, `in_Colour`/`in_Colour0`, `in_TextureCoord`, varyings, custom uniforms and arrays, `gm_BaseTexture`, and fixed world/view/projection matrix constants. Multi-line and comma-separated declarations are normalized without regex-only inference. Custom/normal vertex attributes, unsupported clip-space or 3D transforms, preprocessor directives, stage conflicts, and unlinked varyings fail the logical shader resource with source-linked diagnostics instead of publishing plausible but incorrect output.

Version 0.7.49 expands the clickable release-notes view to the ten newest published changelogs. Each entry is labeled and linked to its GitHub release, and **Show more** appends the next ten entries while preserving the history already displayed.

## What GM2Godot Is and Isn't

**GM2Godot is:**
- A modern project conversion tool from GameMaker to Godot
- A growing GMS2+ GML-to-GDScript transpiler and Godot runtime compatibility layer with tests and reports
- A time-saver for starting Godot projects from GameMaker
- A tool for developers who want to migrate their projects

**GM2Godot isn't:**
- A perfect 1:1 conversion tool
- A complete implementation of every current GameMaker GML Code and GML Reference page yet
- A guarantee that converted gameplay semantics match GameMaker without manual review, especially for unsupported platform services, runtime-authored masks or sequence tracks, sequence animation-curve/clip-mask keys, advanced particle modifiers, Godot physics fixtures, custom/3D/macro-driven or multi-pass shaders, and target-specific runtime APIs
- A tool for converting compiled GM projects (use [UndertaleToolMod](https://github.com/UnderminersTeam/UndertaleModTool) instead)

## Compatibility Todo List

The full compatibility roadmap lives in [`todo-list/`](todo-list/README.md). It tracks checked current coverage, missing features, GMS2+ GML Code coverage, GML Reference/runtime API coverage, events, project import work, Godot architecture, and testing/codebase improvements. Generated report commands can also write current compatibility artifacts under `gm2godot/`.

## Releases

Current source version: `0.7.49`.

Downloadable releases include Windows (`.exe`), macOS (`.dmg` with `.app`), and Linux binaries. You can also run from source on Windows, macOS, and Linux.
The packaged Linux artifact is validated on Ubuntu 24.04 x86_64. Its glibc 2.39 requirement is necessary but does not make other distributions a validated target; they must also supply compatible system, OpenGL/EGL, and X11 libraries. The reviewed Linux package manifest installs Ubuntu's `libegl1` and `libgl1` providers for QtGui together with the required XCB client libraries. The release job rejects unresolved-library warnings, extracts the final ZIP, and proves that its GUI reaches the event loop through the real `qxcb` platform under Xvfb before upload.

On a minimal Ubuntu 24.04 installation, install the reviewed host libraries before launching the downloaded Linux executable:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
  libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 \
  libxcb-util1 libxcb-xkb1
```

Releases starting with 0.7.14 include `SHA256SUMS` for the four platform payloads so downloaded bytes can be checked independently.
When an exact version tag already exists, a release-workflow rerun now audits the published release, exact five-asset inventory, GitHub digests, downloaded bytes, checksum manifest, and stable tag/release receipt before accepting the run as a build-and-publication no-op.

To build local macOS distributables (`.app` + `.zip` + `.dmg`), run `bash build_macos.sh` from the project root. The macOS app uses the stable bundle identifier `land.infi.gm2godot`; its short and build versions both match the three-component release version in `src/version.py`.

## Installation

### Prerequisites

- Use the native, reproducible baseline for your host:

  | Host | Python | Constraint |
  | --- | --- | --- |
  | Linux x64 | CPython 3.12.13 | `constraints/requirements-linux-py312.txt` |
  | macOS arm64 | CPython 3.12.10 | `constraints/requirements-macos-py312.txt` |
  | Windows x64 | CPython 3.12.10 | `constraints/requirements-windows-py312.txt` |

  Other Python patch versions and architectures are not the reviewed dependency baseline.

### Setup

1. **Clone the Repository**
```bash
git clone https://github.com/Infiland/GM2Godot
cd GM2Godot
```

2. **Create and Activate a Virtual Environment**

Use the exact interpreter from the table above. After activation, `python --version` must report the listed patch version.

Linux x64:

```bash
mapfile -t qt_packages < <(
  sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' \
    packaging/linux/qt-xcb-runtime-packages.txt
)
sudo apt-get update
sudo apt-get install --yes --no-install-recommends "${qt_packages[@]}"
python3.12 -m venv venv
source venv/bin/activate
python --version  # Python 3.12.13
```

macOS arm64:

```bash
python3.12 -m venv venv
source venv/bin/activate
python --version  # Python 3.12.10
```

Windows x64 (PowerShell):

```powershell
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python --version  # Python 3.12.10
```

3. **Install the Constrained Dependency Graph**

Bootstrap the exact pip version and install runtime dependencies with the constraint for the current host. Both commands deliberately disable the package cache and source distributions.

Linux x64:

```bash
export PIP_CONFIG_FILE=/dev/null
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-linux-py312.txt pip==26.1.2
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-linux-py312.txt -r requirements.txt
```

macOS arm64:

```bash
export PIP_CONFIG_FILE=/dev/null
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-macos-py312.txt pip==26.1.2
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-macos-py312.txt -r requirements.txt
```

Windows x64 (PowerShell):

```powershell
$env:PIP_CONFIG_FILE = "nul"
python -m pip --isolated --disable-pip-version-check --no-input install `
  --no-cache-dir --only-binary=:all: `
  --constraint constraints/requirements-windows-py312.txt pip==26.1.2
python -m pip --isolated --disable-pip-version-check --no-input install `
  --no-cache-dir --only-binary=:all: `
  --constraint constraints/requirements-windows-py312.txt -r requirements.txt
```

`PIP_CONFIG_FILE` points at the platform null device and `--isolated` ignores user settings, so local pip configuration cannot weaken the reviewed install policy. The committed constraints are compiled from `requirements-lock.in` on their matching native hosts by [`.github/workflows/dependency-locks.yml`](.github/workflows/dependency-locks.yml); the current generator pin is `pip-tools==7.6.0`. Pull requests and pushes use preference-seeded `refresh=locked` generation. A manual run can use `refresh=locked`, `refresh=all`, or `refresh=package`; package refreshes also require the normalized `refresh_package` name. Each native job self-hosts its candidate and compares two clean-install receipts before uploading evidence. When a refresh changes a constraint, the final committed-equality gate intentionally fails until the reviewed native result is committed and the workflow is rerun. A generator upgrade may first require committing the uploaded self-hosted result. Do not generate one platform's constraint from another platform.

## Usage

### GUI

1. **Launch the Application**
```bash
python main.py
```

2. **Configure Project Paths**
- Set your GameMaker project directory
- Set a separate Godot project destination
  - The destination may be missing, empty, or an existing valid Godot project containing `project.godot`.
  - GM2Godot rejects a non-empty non-project directory. Back up existing projects because managed output paths may be replaced by a later conversion.

3. **Configure Settings**
- Click the "Settings" button to open the configuration window
- Select which assets to convert:
  - Assets (sprites, sounds, fonts)
  - Project (icons, settings, audio)
  - Work in Progress features
- Choose your target GameMaker platform

4. **Start Conversion**
- Click "Convert" to begin the process
- Monitor progress through the progress bar
- View detailed logs in the console
- Use the stop button if needed

### CLI

The same entrypoint can run headless conversion, analysis, validation, and report generation:

```bash
python main.py --version
python main.py list-converters
python main.py list-converters --format json
python main.py report --report-dir reports
python main.py analyze --gm-project path/to/GameMakerProject --report-dir reports --target-platform windows
python main.py convert --gm-project path/to/GameMakerProject --godot-project path/to/GodotProject --groups assets,project --report-dir reports --target-platform windows
python main.py validate --godot-project path/to/GodotProject --fail-on-unsupported
```

You can also invoke the same headless interface directly with `python -m src.cli`.

CLI reports are written under `gm2godot/` inside the selected report or Godot project directory. The diagnostic outputs are `conversion_diagnostics.json` and `conversion_diagnostics.md`; static compatibility outputs include `gml_manual_scope.md`, `gml_api_compatibility.md`, and the JSON/Markdown platform capability reports. A report set that resolves inside the project's managed `gm2godot/` evidence root is staged with the conversion; a destination that would put reports under another converter-owned root is rejected instead of creating untracked post-commit output.

The four static compatibility reports publish as one ordered transaction through a retained verified `gm2godot/` directory binding. Ordinary render or publication failures preserve the complete prior set with its exact modes instead of deleting it; successful return means all four new reports passed durability and final receipt validation.

Every valid `convert` invocation prints exactly one terminal outcome summary after its buffered conversion logs. The diagnostic JSON report also includes a top-level `outcome` object with:

- `state`: `success`, `partial`, `failed`, or `cancelled`.
- `converters` and `resources`: `requested`, `executed`, `completed`, `skipped`, and `failed` counts.
- `failed_step` and `failure_phase`: optional failure context when conversion could not finish.

The named `steps` ledger uses conversion-plan order. `completed`, `skipped`, and `failed` partition the requested steps; completed and failed steps were executed. A step interrupted by cancellation is both executed and skipped, so `executed` and `skipped` are intentionally not disjoint. A `partial` outcome means every requested converter step completed but one or more resources were skipped or failed.

After destination preflight, every terminal run writes format-v1 `conversion_attempt.json`. A trustworthy successful or partial conversion also writes format-v2 `conversion_manifest.json`. Managed output and canonical evidence are selected together; failed or cancelled work before the generation decision publishes only non-canonical attempt evidence after verifying the preserved generation.

The format-v2 manifest now carries an additive `generation_inventory` object at inventory format 1. Its canonical `entries` array is the complete managed generation rather than an invocation-local diff. Every row contains `path`, `kind`, `owner` (`converter_step` or `shared_owner`), `byte_count`, `sha256`, and `mode`. The legacy `generated_files` field and stable manifest/attempt paths remain; `generated_files` is rendered from the same inventory, with the canonical manifest retaining its existing `sha256: "self"` compatibility row.

| `canonical_manifest.status` | `updated` | `current_output` | `sha256` meaning |
| --- | ---: | --- | --- |
| `updated` | `true` | `verified` | Expected digest of the canonical manifest committed last by this publication transaction |
| `preserved` | `false` | `verified` | Digest of the prior canonical manifest after the managed-output transaction verified or restored its complete generation |
| `preserved` | `false` | `unverified` | Legacy artifact-only publication left an existing regular file untouched without destination-wide generation verification |
| `absent` | `false` | `unavailable` | `null`; no canonical manifest exists |

The two public ledger paths, attempt schema, and existing manifest fields stay stable; the inventory is additive. Their publication is one recoverable generation. GM2Godot durably records the complete prior and desired pair before replacing the attempt and optional canonical manifest, then switches one persistent generation pointer as the commit decision. Recovery under a project-local operating-system lock restores the prior pair before that switch or verifies the new pair afterward. Consumers should still verify `canonical_manifest.sha256` as defense against later replacement or corruption, but a mismatch is rejected recovery state rather than a normal interrupted-publication result. `status` remains transaction-relative, not whole-run provenance; inspect the latest attempt before trusting preserved output after failed or cancelled work.

Conversion exit codes are stable for CI:

| Result | Exit code |
| --- | ---: |
| Success, with diagnostic thresholds passing | `0` |
| Partial output | `2` |
| Partial output with `--allow-partial`, with diagnostic thresholds passing | `0` |
| Any diagnostic threshold violation, including with `--allow-partial` | `2` |
| Preflight rejection | `2` |
| Failed conversion or runtime exception | `1` |
| Cancelled conversion or first `SIGINT` observed before the managed-generation decision | `130` |

`--allow-partial` applies only to the `convert` command. It accepts usable partial output for exit-code purposes, but does not override `--fail-on-unsupported`, `--max-warnings`, `--max-errors`, or `--max-unsupported`.

The final cancellation check before recoverable managed-output publication is the conversion commit point. A `SIGINT` observed before it preserves the prior generation, publishes a `cancelled` attempt, and exits `130`. Once publication begins, the converter resolves the durable old-or-new decision and later signals cannot relabel exposed committed output as cancelled. The CLI still buffers and prints exactly one terminal outcome line.

Direct `Converter.convert()` callers use the same contract as the GUI and CLI. Supply a live cooperative `conversion_running` flag; cancellation observed before publication returns a `cancelled` outcome with the verified prior generation, while clearing the flag after publication begins does not change the selected terminal generation. Runtime, validation, publication, or recovery errors are raised and remain available through `last_outcome`; callers must not infer trust from return-versus-exception alone.

If `.gm2godot-managed-output/.gm2godot-managed-output-recovery.json` exists, close Godot and every other writer, preserve that artifact together with the named journal/stage/generation records, and retry conversion or call `recover_managed_output_generation(destination_path)` before reading managed output. `selected_generation` reports `previous`, `desired`, or `unknown`; `desired` can accompany a cleanup exception after the new generation was durably selected, while `unknown` requires preserving the destination for inspection. Never edit the pointer, journal, transaction ID, affected paths, or digest to force recovery. Every private stage, backup, journal, recovery artifact, generation record, and namespace move must stay on the destination filesystem; cross-device copy/delete fallback is intentionally unavailable.

Useful conversion and validation filters:
- `--groups assets,project,wip` selects conversion groups.
- `--only asset_registry,scripts,objects` runs specific converter keys instead of groups.
- `list-converters --format json` prints the exact converter keys accepted by `--only`.
- `--allow-partial` lets a partial conversion exit successfully when every diagnostic threshold also passes.
- `--fail-on-unsupported`, `--max-warnings`, `--max-errors`, and `--max-unsupported` turn diagnostics into non-zero exit codes for CI.
- `--godot-bin` points validation at a specific Godot executable when `GODOT_BIN` is not set.

## AI-Assisted Development with GPT-5.6

I used GM2Godot together with GPT-5.6 as an AI-assisted development workflow for migrating GameMaker projects to Godot. GPT-5.6 helped me understand the repository and its conversion pipeline, plan and implement changes, inspect GameMaker project files, write and review Python, GML, and GDScript code, create regression tests, investigate conversion failures, and document compatibility limitations.

My workflow was iterative: I used GPT-5.6 to analyze the current behavior, make a focused change, run the relevant commands or tests, inspect the generated Godot output and diagnostics, and refine the implementation when the results exposed an issue. This included both the graphical application and the headless CLI, as well as conversion reports and generated runtime helpers.

GPT-5.6 was used as a development assistant, not as a substitute for verification. Changes were reviewed against the repository, executed locally, and validated with the project's available tests and conversion output before being treated as working. Final compatibility, correctness, and release decisions remain the responsibility of the project maintainer.

## Contributing

We welcome contributions! Check out [CONTRIBUTING.md](https://github.com/Infiland/GM2Godot/blob/main/CONTRIBUTING.md) for guidelines.

To contribute:
1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to your branch
5. Create a Pull Request

## Support

- Report issues on our [GitHub Issues](https://github.com/Infiland/GM2Godot/issues) page
- Check our [Documentation](https://github.com/Infiland/GM2Godot/wiki) for detailed guides

---

## Instructions for Coding Agents (LLMs)

```text
You are setting up the GM2Godot project.

Use exactly one supported native dependency baseline:
- Linux x64: CPython 3.12.13 with constraints/requirements-linux-py312.txt
- macOS arm64: CPython 3.12.10 with constraints/requirements-macos-py312.txt
- Windows x64: CPython 3.12.10 with constraints/requirements-windows-py312.txt

Create and activate a virtual environment with that exact interpreter. Confirm the
active environment with python --version before installing anything.

Set PIP_CONFIG_FILE to /dev/null on Linux or macOS, or lowercase nul in Windows
PowerShell. Bootstrap pip==26.1.2 and install requirements.txt with python -m pip,
--isolated, --disable-pip-version-check, --no-input, --no-cache-dir,
--only-binary=:all:, and the matching --constraint file. For example, on Linux
x64:
export PIP_CONFIG_FILE=/dev/null
python -m pip --isolated --disable-pip-version-check --no-input install --no-cache-dir --only-binary=:all: --constraint constraints/requirements-linux-py312.txt pip==26.1.2
python -m pip --isolated --disable-pip-version-check --no-input install --no-cache-dir --only-binary=:all: --constraint constraints/requirements-linux-py312.txt -r requirements.txt

The null config file and isolated mode prevent machine-local pip settings from
changing the reviewed install behavior.

Never generate a constraint for one platform on another platform. Pull requests
and pushes use preference-seeded refresh=locked generation. Manual workflow runs
accept refresh=locked, refresh=all, or refresh=package with a normalized
refresh_package. Candidates are compiled from requirements-lock.in; the current
generator pin is pip-tools==7.6.0. The native workflow self-hosts each candidate,
compares two clean installs, and uploads evidence before intentionally failing
when a changed result has not yet been committed. A generator upgrade may require
committing the self-hosted result and rerunning.

The project uses PySide6 (not Tkinter). Required packages are:
- Pillow
- markdown2
- requests
- PySide6

Run the application using:
python main.py

Headless verification examples:
python main.py --version
python main.py list-converters --format json
python main.py report --report-dir reports
python main.py analyze --gm-project path/to/GameMakerProject --report-dir reports --target-platform windows
python main.py validate --godot-project path/to/GodotProject --fail-on-unsupported

Verification for coding agents:
- If Python or generated-code logic changes, run ./venv/bin/pyright --warnings and relevant tests.
- For broad code changes, run ./venv/bin/python -m unittest.
- For documentation-only changes, do not run Pyright or tests unless explicitly requested.

Ensure all dependencies are installed correctly before execution.
```
