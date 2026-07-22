# GM2Godot Documentation

> **Applies to:** GM2Godot 0.7.48 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-22

GM2Godot converts supported GameMaker source projects and GML into editable Godot projects. It combines asset conversion, a GML-to-GDScript transpiler, generated runtime helpers, compatibility diagnostics, and headless Godot validation. It is a migration aid, not a promise of automatic one-to-one gameplay parity.

## Start here

- [Installation](Installation) — download a release build or run GM2Godot from source on Windows, macOS, or Linux.
- [Quick Start Conversion](Quick-Start-Conversion) — convert a project through the GUI or CLI and validate the result.
- [Compatibility and Limitations](Compatibility-and-Limitations) — understand the current target, support levels, platform scope, and known gaps.
- [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting) — interpret outcomes, reports, exit codes, and common failures.
- [Generated Project and Runtime](Generated-Project-and-Runtime) — learn what GM2Godot generates and where manual Godot work belongs.
- [Contributing and Testing](Contributing-and-Testing) — extend the transpiler, runtime, converters, fixtures, or documentation.

Maintainers should also read [Release and Wiki Maintenance](Maintainer-Release-and-Wiki).

## Compatibility target

This documentation set describes:

- GM2Godot 0.7.48;
- GameMaker LTS 2026 source projects in the GMS2 runtime family; and
- Godot 4.7.1 output and validation, pinned in CI as `4.7.1.stable.official.a13da4feb`.

GameMaker beta/GMRT releases and later Godot releases are not implied by that target. GM2Godot can continue after unsupported or malformed resources and may produce a usable `partial` conversion; always inspect the generated diagnostics and run Godot validation before treating a migration as complete.

## Typical workflow

1. Preserve the GameMaker project and choose a separate Godot destination.
2. Run conversion from the GUI or CLI.
3. Read `conversion_diagnostics.md` and the terminal outcome.
4. Validate the destination project, including generated resources, with the exact supported Godot version.
5. Review unsupported or partial behavior, then continue the migration in Godot.
6. Keep authored Godot work outside paths that GM2Godot owns and may replace on a later conversion.

## Current sources of truth

The Wiki explains how to use the project. Details that change frequently remain canonical in the repository:

- [README and CLI outcome contract](https://github.com/Infiland/GM2Godot/blob/main/README.md)
- [Compatibility roadmap](https://github.com/Infiland/GM2Godot/tree/main/todo-list) — planning context, not a live support table
- [Generated-runtime documentation](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/runtime_managers.md)
- [Godot architecture policy](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/godot_architecture_policy.md)
- [Contributing guide](https://github.com/Infiland/GM2Godot/blob/main/CONTRIBUTING.md)
- [Changelog](https://github.com/Infiland/GM2Godot/blob/main/CHANGELOG.md)

Generate current compatibility reports from the version of GM2Godot you are actually running instead of relying on copied API totals.

## Downloads and support

- [Latest release](https://github.com/Infiland/GM2Godot/releases/latest)
- [Open issues](https://github.com/Infiland/GM2Godot/issues)
- [Report an unsupported GML API](https://github.com/Infiland/GM2Godot/issues/new?template=unsupported_gml_api.yml)
- [Report invalid generated GDScript](https://github.com/Infiland/GM2Godot/issues/new?template=invalid_generated_gdscript.yml)
- [Report a resource conversion mismatch](https://github.com/Infiland/GM2Godot/issues/new?template=resource_conversion_mismatch.yml)
