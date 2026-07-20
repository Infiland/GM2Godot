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
  - Fonts, notes, scripts, objects, rooms, tilesets, shaders, paths, timelines, sequences, particles, extensions, texture groups, and options metadata where supported
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

## What GM2Godot Is and Isn't

**GM2Godot is:**
- A modern project conversion tool from GameMaker to Godot
- A growing GMS2+ GML-to-GDScript transpiler and Godot runtime compatibility layer with tests and reports
- A time-saver for starting Godot projects from GameMaker
- A tool for developers who want to migrate their projects

**GM2Godot isn't:**
- A perfect 1:1 conversion tool
- A complete implementation of every current GameMaker GML Code and GML Reference page yet
- A guarantee that converted gameplay semantics match GameMaker without manual review, especially for unsupported platform services, precise collision masks, shaders, and target-specific runtime APIs
- A tool for converting compiled GM projects (use [UndertaleToolMod](https://github.com/UnderminersTeam/UndertaleModTool) instead)

## Compatibility Todo List

The full compatibility roadmap lives in [`todo-list/`](todo-list/README.md). It tracks checked current coverage, missing features, GMS2+ GML Code coverage, GML Reference/runtime API coverage, events, project import work, Godot architecture, and testing/codebase improvements. Generated report commands can also write current compatibility artifacts under `gm2godot/`.

## Releases

Current source version: `0.7.37`.

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

CLI reports are written under `gm2godot/` inside the selected report or Godot project directory. The diagnostic outputs are `conversion_diagnostics.json` and `conversion_diagnostics.md`; static compatibility outputs include `gml_manual_scope.md`, `gml_api_compatibility.md`, and the JSON/Markdown platform capability reports.

The four static compatibility reports publish as one ordered transaction through a retained verified `gm2godot/` directory binding. Ordinary render or publication failures preserve the complete prior set with its exact modes instead of deleting it; successful return means all four new reports passed durability and final receipt validation.

Every valid `convert` invocation prints exactly one terminal outcome summary after its buffered conversion logs. The diagnostic JSON report also includes a top-level `outcome` object with:

- `state`: `success`, `partial`, `failed`, or `cancelled`.
- `converters` and `resources`: `requested`, `executed`, `completed`, `skipped`, and `failed` counts.
- `failed_step` and `failure_phase`: optional failure context when conversion could not finish.

The named `steps` ledger uses conversion-plan order. `completed`, `skipped`, and `failed` partition the requested steps; completed and failed steps were executed. A step interrupted by cancellation is both executed and skipped, so `executed` and `skipped` are intentionally not disjoint. A `partial` outcome means every requested converter step completed but one or more resources were skipped or failed.

After destination preflight, every terminal run writes format-v1 `conversion_attempt.json`. A trustworthy successful or partial conversion also writes format-v2 `conversion_manifest.json`. The attempt state and canonical-manifest trust are independent: a late report failure or cancellation can occur after a trustworthy canonical manifest was already committed.

| `canonical_manifest.status` | `updated` | `current_output` | `sha256` meaning |
| --- | ---: | --- | --- |
| `updated` | `true` | `verified` | Expected digest of the canonical manifest committed last by this publication transaction |
| `preserved` | `false` | `unverified` | Digest of an existing regular file left untouched by this publication |
| `absent` | `false` | `unavailable` | `null`; no canonical manifest exists |

The two public ledger paths and JSON schemas stay stable, but their publication is one recoverable generation. GM2Godot durably records the complete prior and desired pair before replacing the attempt and optional canonical manifest, then switches one persistent generation pointer as the commit decision. Recovery under a project-local operating-system lock restores the prior pair before that switch or verifies the new pair afterward. Consumers should still verify `canonical_manifest.sha256` as defense against later replacement or corruption, but a mismatch is rejected recovery state rather than a normal interrupted-publication result. `status` remains transaction-relative, not whole-run provenance; inspect the latest attempt before trusting preserved output after failed or cancelled work.

Conversion exit codes are stable for CI:

| Result | Exit code |
| --- | ---: |
| Success, with diagnostic thresholds passing | `0` |
| Partial output | `2` |
| Partial output with `--allow-partial`, with diagnostic thresholds passing | `0` |
| Any diagnostic threshold violation, including with `--allow-partial` | `2` |
| Preflight rejection | `2` |
| Failed conversion or runtime exception | `1` |
| Cancelled conversion or first `SIGINT` received before the terminal outcome line begins committing | `130` |

`--allow-partial` applies only to the `convert` command. It accepts usable partial output for exit-code purposes, but does not override `--fail-on-unsupported`, `--max-warnings`, `--max-errors`, or `--max-unsupported`.

The single terminal outcome line is the CLI commit point. A `SIGINT` received before that commit rewrites reports to `cancelled` and exits `130`; once stdout publication has begun, the completed outcome is not retroactively changed or printed a second time.

Useful conversion and validation filters:
- `--groups assets,project,wip` selects conversion groups.
- `--only asset_registry,scripts,objects` runs specific converter keys instead of groups.
- `list-converters --format json` prints the exact converter keys accepted by `--only`.
- `--allow-partial` lets a partial conversion exit successfully when every diagnostic threshold also passes.
- `--fail-on-unsupported`, `--max-warnings`, `--max-errors`, and `--max-unsupported` turn diagnostics into non-zero exit codes for CI.
- `--godot-bin` points validation at a specific Godot executable when `GODOT_BIN` is not set.

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
