# Compatibility and Limitations

> **Applies to:** GM2Godot 0.7.7 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-18

[Home](Home) · [Quick Start Conversion](Quick-Start-Conversion) · [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting)

GM2Godot converts supported GameMaker source projects into an editable Godot project. It is a migration tool, not a byte-for-byte runtime replacement: a conversion that completes still needs review and gameplay testing in Godot.

## What the compatibility labels mean

| Status | Meaning |
| --- | --- |
| **Implemented** | GM2Godot has a working parser, emitter, converter, or runtime path for the documented surface, as applicable. Check the entry's parser, emitter, runtime, and smoke-coverage fields separately: an implemented status does not promise smoke coverage or perfect behavior in every composition or project. |
| **Partial** | A useful conversion path exists, but known GameMaker semantics, target behavior, resource variants, or regression coverage are incomplete. Read the entry notes and conversion diagnostics before relying on it. |
| **Unsupported** | GM2Godot does not have a safe equivalent. The feature should be reported explicitly instead of being treated as working output. It needs a project change, manual Godot implementation, or reviewed plugin/extension bridge. |
| **Planned** | The feature is tracked but does not yet have a supported implementation. A roadmap entry is not a compatibility promise or release date. |

Generated reports also use **out of scope** for behavior that GM2Godot intentionally does not plan to translate. In particular, GM2Godot converts source projects; it does not recover projects from compiled GameMaker games.

## Get the current answer from generated reports

Do not rely on a hand-copied API count in this Wiki. The manifest and report generators change with the implementation and are the current source of truth for a checkout or release.

```bash
python main.py report --report-dir reports
python main.py analyze \
  --gm-project path/to/GameMakerProject \
  --report-dir reports \
  --target-platform windows
```

Look under `reports/gm2godot/`:

- `gml_manual_scope.md` summarizes modern GML language and manual-section coverage.
- `gml_api_compatibility.md` summarizes runtime API coverage by category and links categories to their tracking issues.
- `platform_capability_report.md` and `.json` identify target-specific export presets, permissions, plugins, hooks, and unsupported capabilities.
- `conversion_diagnostics.md` and `.json` contain the command's diagnostics. `analyze` currently reports target selection and project-directory/`.yyp` findings; conversion adds converter, resource, API, and outcome diagnostics under the generated project's `gm2godot/` directory.
- A converted project's `gm2godot/conversion_manifest.json` records the exact enabled converters, source metadata, resources, generated-file hashes, and canonical `success` or `partial` outcome. It is project evidence, not a global support table; verify it through the latest attempt ledger as described in [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting). The schema and publication contract live in the canonical [`conversion_manifest.py`](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/conversion_manifest.py).

For work that is missing or not yet proven, the repository [compatibility roadmap](https://github.com/Infiland/GM2Godot/tree/main/todo-list) provides planning and historical context. It can lag the implementation, so use generated reports—not roadmap checkboxes or copied totals—for current support claims. See [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting) for project-specific outcomes and report trust rules.

## Host, source filter, and export target are different

Three separate platform questions are easy to confuse:

| Question | Current contract |
| --- | --- |
| **Where can GM2Godot run?** | Release artifacts and source execution are supported on Windows, macOS, and Linux. This is the **conversion host**. |
| **What does `--target-platform` select?** | The CLI accepts `windows`, `macos`, or `linux`. This is a **GameMaker source/configuration filter** used for target-specific project options, conditional GML and macros, and capability-report context. It does not filter the project's resource inventory. It defaults from the conversion host. |
| **Where can the generated game be exported?** | The generated project targets Godot 4.7.1, but GM2Godot does not certify a complete export for a platform. Godot export templates and presets, signing, permissions, SDKs, native extensions, store services, and target-device tests remain separate work. |

Selecting `--target-platform windows`, for example, does **not** create or validate a production Windows export and does not make Steam, Xbox, native DLL, or other platform APIs available. Use the generated platform capability report and configure the required Godot plugins and export settings explicitly.

## Compatibility baseline

- The source compatibility target is **[GameMaker LTS 2026](https://releases.gamemaker.io/release-notes/2026/0)** and its [version-specific manual](https://manual.gamemaker.io/lts/en/). Projects from newer monthly or beta releases may contain schema, syntax, APIs, or resource variants outside this baseline.
- The output and automated smoke-test target is the official **[Godot 4.7.1](https://godotengine.org/article/maintenance-release-godot-4-7-1/)** build at commit `a13da4feb`. Other Godot versions may parse the project, but they are not the compatibility target for this release.
- GM2Godot expects an editable GameMaker project with a `.yyp` and its `.yy`, GML, and asset files. Compiled executables are not supported input.
- A generated project is a migration starting point. Keep the original GameMaker project, convert into a separate destination, and compare behavior before replacing any production workflow.

## Known limitation areas

The following areas require especially careful manual review. This list is intentionally high level; the generated reports and roadmap hold the detailed, current status.

- Exact GameMaker value, coercion, lookup, lifecycle, and event-order edge cases can differ from GDScript and Godot callbacks.
- Precise sprite masks, pixel-perfect collisions, collision dispatch, and GameMaker physics behavior are not guaranteed to match Godot physics.
- Shader translation, surfaces, GPU/draw state, cameras, the application surface, GUI scaling, and render ordering can need manual Godot work.
- Advanced room/layer mutation, tilemaps, texture groups, sequences, timelines, particles, animation curves, and dynamic asset APIs have partial or metadata-only areas.
- Audio groups, streaming/compression, positional audio, async payload timing, networking, and filesystem sandbox behavior can vary by target.
- Native extensions, marketplace SDKs, Steam, IAP, cloud, push, console, browser, and mobile services require explicit Godot plugins, permissions, or project-specific bridges; metadata and stubs are not working SDK integrations.
- Importing a resource does not prove exact runtime semantics, visual parity, performance, or export readiness. Large and renderer-sensitive projects need representative target-device tests.

An **implemented** label therefore means “the documented GM2Godot contract exists,” not “the whole converted game is guaranteed identical.” Treat warnings and unsupported diagnostics as migration tasks, and validate the generated project with the exact Godot target described in [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting).

## When you find a gap

Use the project's [issue chooser](https://github.com/Infiland/GM2Godot/issues/new/choose) so the report reaches the right workflow. Include a minimal source example, the relevant generated diagnostic/report entry, GM2Godot version or commit, GameMaker version, Godot version, conversion host, and selected target-platform filter. The troubleshooting page explains which report files are safe to trust and attach.
