# GM2Godot

GM2Godot converts editable GameMaker projects into Godot projects. Give it a project
folder containing a `.yyp` file, its GML source and assets; it generates GDScript,
Godot resources and runtime helpers to help you continue development in Godot.

GM2Godot targets GameMaker LTS 2026 source projects and Godot 4.7.2 output.

[Quick start](https://github.com/Infiland/GM2Godot/wiki/Quick-Start-Conversion) ·
[Downloads](https://github.com/Infiland/GM2Godot/releases/latest) ·
[Documentation](https://github.com/Infiland/GM2Godot/wiki)

<img width="802" height="632" alt="screen" src="https://github.com/user-attachments/assets/cedf47f5-6668-44ab-8cf6-959a21afd7fa" />

## What it converts

- Supported GML expressions, scripts, object events, room creation code and macros.
- Sprites and collision masks, sounds, fonts, objects, rooms and Included Files.
- Supported tilesets, shaders, paths, sequences, timelines, particles and project settings.
- Runtime helpers for supported GameMaker APIs, asset references and room behavior.
- Diagnostics and compatibility reports to identify unsupported or incomplete conversion.

Use the desktop GUI to choose projects and conversion settings, or the headless CLI
for conversion, analysis, validation and reports.

## Start with the GUI

1. [Download a release](https://github.com/Infiland/GM2Godot/releases/latest) for your host
   and extract the archive or install the Mac app from its DMG.
2. Select the GameMaker directory containing your `.yyp` and a separate, existing
   empty folder or valid Godot project for the output.
3. Review **Settings**, choose the target GameMaker platform and click **Convert**.
4. Read the logs and reports, then open the generated project in Godot 4.7.2.

Back up an existing destination and close Godot before converting into it.
The [quick-start guide](https://github.com/Infiland/GM2Godot/wiki/Quick-Start-Conversion)
explains destination rules and how to check the result.

## Run from source or use the CLI

Follow the [source setup instructions](https://github.com/Infiland/GM2Godot/wiki/Installation#run-from-source)
for your platform first. From the repository root in the activated environment,
launch the GUI with `python main.py`, or run a conversion:

```bash
python main.py convert \
  --gm-project "/path/to/GameMakerProject" \
  --godot-project "/path/to/GodotProject" \
  --groups assets,project,wip --target-platform windows --report-dir reports
```

Change the paths and choose `windows`, `macos` or `linux` for GameMaker options and
conditional GML/macros. This selects conversion settings, not a finished game export.
See the [CLI guide](https://github.com/Infiland/GM2Godot/wiki/Quick-Start-Conversion#convert-with-the-cli)
for filters and validation. [Report guidance](https://github.com/Infiland/GM2Godot/wiki/Diagnostics-and-Troubleshooting)
explains warnings, partial results and the generated `gm2godot/` reports.

## Install Python launchers from a local wheel

After preparing the source environment, you can install a wheel built from this
project in that same environment. Use the actual wheel path:

```bash
python -m pip install --no-deps "path/to/the-built-wheel.whl"
gm2godot --version
gm2godot --help
```

The installation creates the `gm2godot` console command and `gm2godot-gui` GUI
launcher, with bundled GDScript, icons and language catalogs. Run `gm2godot` with
no arguments or `gm2godot-gui` to open the GUI; use `gm2godot` for commands that
print output. See [Python distribution and installed launchers](docs/python-distribution.md)
for local wheel requirements and installed language preferences.

## Compatibility and optional Deep conversion

Converted output is a migration starting point: review generated code and compare
gameplay with the original. Some GML APIs and resource variants remain unsupported;
compiled GameMaker games are not accepted input. Check
[Compatibility and Limitations](https://github.com/Infiland/GM2Godot/wiki/Compatibility-and-Limitations)
and the [coverage roadmap](todo-list/README.md) for your project's requirements.

Optional [Deep conversion](docs/DEEP_CONVERSION.md) adds AI research and reviewed
conversion through a downloadable extension.

## Releases

Current source version: `1.0.0`.

Published downloads include Windows and Linux ZIPs, plus separate macOS Apple Silicon
and Intel ZIP/DMG pairs. See [Installation](https://github.com/Infiland/GM2Godot/wiki/Installation)
for host requirements and `SHA256SUMS` verification. Release history is in the
[changelog](CHANGELOG.md) and [GitHub Releases](https://github.com/Infiland/GM2Godot/releases).

## Contribute and get help

- [Contributing](CONTRIBUTING.md) and [coding-agent instructions](AGENTS.md)
- [Development account with GPT-5.6](docs/AI_ASSISTED_DEVELOPMENT.md)
- [Report a problem](https://github.com/Infiland/GM2Godot/issues) with project details and diagnostics
- [License](LICENSE)
