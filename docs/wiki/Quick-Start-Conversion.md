# Quick Start Conversion

> **Applies to:** GM2Godot 0.7.20 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-19

This guide covers a first conversion through either the desktop interface or the source CLI. GM2Godot converts source projects, so select the GameMaker project root that contains the `.yyp` file—not an exported or compiled game.

Before converting into an existing Godot project, commit it to version control or make a backup. Conversion writes the selected generated resources and settings into that project.

## Choose a safe Godot destination

GM2Godot classifies the destination before writing output. The current rules are implemented in [`project_godot.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/project_godot.py).

| Destination state | GUI | CLI | Result |
| --- | --- | --- | --- |
| Path does not exist | Not accepted; create an empty directory first. | Accepted. | The CLI creates the directory and initializes `project.godot` when conversion starts. |
| Existing empty directory | Accepted. | Accepted. | Conversion initializes a minimal `project.godot`. |
| Existing Godot project with a valid regular `project.godot` | Accepted. | Accepted. | Selected converters may update `project.godot` and GM2Godot-managed paths. Back up or commit the project first. |
| Non-empty directory without `project.godot` | Rejected. | Rejected. | Preflight refuses conversion instead of treating the directory as a new project. |

Redirected destinations such as symbolic links or junctions, invalid `project.godot` files, and unsafe managed output paths are also rejected. Choose the real project directory and resolve the reported preflight error before retrying.

## Convert with the GUI

1. Launch the packaged application, or run `python main.py` from an activated source environment.
2. For **GameMaker Directory**, choose the project root containing one `.yyp` file.
3. For **Godot Directory**, choose an empty directory or an existing valid Godot project. The GUI requires this directory to exist already.
4. Open **Settings** and review the conversion checkboxes. Most start enabled; notes and sound-group folders start off.
5. Choose the target platform: `windows`, `macos`, or `linux`. This selects target-specific GameMaker project options and conditional GML/macros; it does not filter the project's resources and does not have to match the computer running the converter.
6. Click **Convert** and follow the console and progress display. The stop button requests cancellation.

A completed progress bar means the conversion worker finished; it is not proof of full GameMaker semantic compatibility. Use the report checks below before treating the output as ready.

## Convert with the CLI

The CLI is available from a source installation through `python main.py` or `python -m src.cli`. A complete first conversion can be run as one command:

```bash
python main.py convert --gm-project "/path/to/GameMakerProject" --godot-project "/path/to/GodotProject" --groups assets,project,wip --target-platform windows
```

Replace both paths and choose `windows`, `macos`, or `linux` for the GameMaker options and conditional GML/macros you want selected. This does not filter the project's resources. If `--target-platform` is omitted, GM2Godot defaults to the current host platform.

The three conversion groups are defined by the current [`CONVERSION_CATEGORIES`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/converter.py):

- `assets` converts the supported asset, script, object, room, and registry outputs.
- `project` converts the supported icon, project metadata/settings, audio buses, and notes.
- `wip` enables the shader and tileset converters.

To run only specific converters, first print the accepted keys:

```bash
python main.py list-converters --format json
python main.py convert --gm-project "/path/to/GameMakerProject" --godot-project "/path/to/GodotProject" --only sprites,scripts,objects,rooms --target-platform windows
```

When `--only` contains at least one key, it takes precedence over `--groups`. Unknown group names and converter keys are rejected before conversion.

## Verify the first conversion

1. Read the terminal outcome (CLI). A terminal state can be `success`, `partial`, `failed`, or `cancelled`.
2. After destination preflight succeeds, read `<GodotProject>/gm2godot/conversion_attempt.json` and `<GodotProject>/gm2godot/conversion_diagnostics.md`. Address errors, unsupported APIs, and relevant warnings. A pre-existing `conversion_manifest.json` may describe an earlier trustworthy run, so inspect the newest attempt ledger first. A rejected preflight intentionally writes no conversion artifacts inside the destination.
3. Validate the destination project, including the generated resources, with the exact Godot 4.7.1 executable:

   ```bash
   python main.py validate --godot-project "/path/to/GodotProject" --godot-bin "/absolute/path/to/Godot-4.7.1" --fail-on-unsupported
   ```

   If `--godot-bin` is omitted, validation checks `GODOT_BIN`, then a `godot` executable on `PATH`, then the standard macOS application path. If Godot cannot be found, project/resource validation is reported as skipped rather than passed.

4. For an additional bounded boot check of the configured main scene, add `--godot-boot-frames 60`. The validation details are written to `<GodotProject>/gm2godot/godot_validation_report.json`.
5. Open `project.godot` in Godot 4.7.1, inspect the generated scenes and scripts, and test the game paths that matter to your project. Conversion and parser validation do not guarantee one-to-one runtime behavior.

The repository CI pins the full Godot build used for smoke tests in [`godot-smoke.yml`](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/godot-smoke.yml). For interpreting partial output and unsupported features, continue with [Compatibility and Limitations](Compatibility-and-Limitations); for report details and failures, use [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting). Generated file layout and runtime helpers are covered in [Generated Project and Runtime](Generated-Project-and-Runtime).

If GM2Godot is not installed yet, start with [Installation](Installation).
