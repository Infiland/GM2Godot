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
  - Fonts, notes, included files, scripts, objects, rooms, tilesets, shaders, paths, timelines, sequences, particles, extensions, texture groups, and options metadata where supported
  - Project settings, game icons, platform options, and validation reports
- **Platform Support**: Converts settings for multiple platforms:
  - Windows
  - macOS
  - Linux
- **Diagnostics and Reports**: Writes structured warnings/errors, compatibility Markdown/JSON, trusted conversion manifests, per-attempt outcome ledgers, architecture-policy reports, and optional headless Godot validation reports
- **Customizable Conversion**: Choose conversion groups or specific converter keys
- **Compatibility Roadmap**: Tracks current and missing GameMaker-to-Godot coverage in [`todo-list/`](todo-list/README.md)

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

Current source version: `0.7.7`.

Downloadable releases include Windows (`.exe`), macOS (`.dmg` with `.app`), and Linux binaries. You can also run from source on Windows, macOS, and Linux.

To build a local macOS distributable (`.app` + `.dmg`), run `bash build_macos.sh` from the project root.

## Installation

### Prerequisites

- Python 3.12 or later

### Setup

1. **Clone the Repository**
```bash
git clone https://github.com/Infiland/GM2Godot
cd GM2Godot
```

2. **Create a Virtual Environment** (recommended)
```bash
python3 -m venv venv
```

3. **Activate the Virtual Environment**
- On macOS/Linux:
```bash
source venv/bin/activate
```
- On Windows:
```bash
venv\Scripts\activate
```

4. **Install Dependencies**
```bash
pip install -r requirements.txt
```

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

Each ledger file is replaced atomically from the same directory. The pair is committed attempt-first and canonical-last rather than through one multi-file atomic operation, so consumers must verify that the canonical file matches `canonical_manifest.sha256`; a mismatch identifies an interrupted publication. `current_output=verified` applies to the digest-matching canonical. `status` describes this artifact-publication transaction, not whole-run provenance. A preserved file may come from an earlier run or an earlier phase of the same invocation; preserving it does not validate its format or prove that it describes the current destination. Inspect the latest attempt ledger before trusting it after failed or cancelled work.

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

Ensure Python 3.12 or later is installed.

Create and activate a virtual environment:
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

Install dependencies from requirements.txt:
pip install -r requirements.txt

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
