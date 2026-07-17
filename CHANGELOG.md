# Changelog

## 0.7.2 - 2026-07-17

- Confined nested GameMaker `.yy` sidecar and fallback-scan paths to the declared project root, rejecting traversal, absolute-path, drive-relative, NUL, and symlink escapes with source-linked diagnostics.

## 0.7.1 - 2026-07-17

- Added immutable GameMaker LTS 2026 SNAP and Adding fixtures to CI with exact Godot 4.7.1 conversion, generated-resource validation, short runtime boot checks, and bounded failure reports.

## 0.7.0 - 2026-07-17

- Retargeted generated projects and CI to GameMaker LTS 2026 and exact Godot 4.7.1 compatibility, with locally pinned SNAP and Adding fixture conversions and runtime boots used as release evidence.
- Expanded current GML syntax and runtime support for constructors, preprocessors, macros, enums, strings, arrays, data structures, top-level initialization, tilemaps, and source maps.
- Hardened deterministic asset output, project path containment, atomic manifests and project settings, update integrity, process shutdown, diagnostics, and CLI/GUI completion handling.
- Added broad unit and Godot-backed regression coverage for the completed compatibility-hardening work tracked by issues #653, #700, #701, and #703, plus foundations for the remaining follow-ups.

## 0.6.1 - 2026-05-28

- Added CLI version output, converter inventory discovery, JSON inventory output for automation, and direct `python -m src.cli` execution.
- Documented the new CLI commands and incremented the source version for issue #660.

## 0.6.0 - 2026-05-28

Milestone 7: GML Transpiler Part 2.

- Expanded current GMS2+ GML compatibility indexing, diagnostics, CLI reporting, source maps, runtime segment validation, and generated-output manifests.
- Added broad Part 2 transpiler/runtime coverage for value semantics, dynamic variables, accessors, constructors, control flow, macros, project metadata, rooms, layers, paths, tilesets, timelines, sequences, particles, async queues, draw phases, input events, collisions, data structures, files, buffers, networking, audio, cameras, display/window APIs, movement, physics, platform services, and runtime managers.
- Added pinned Godot smoke validation, external project conversion gates, golden conversion snapshots, Ruff code-health checks, fixture corpus coverage, architecture policy reports, and contributor/runtime documentation.
- Milestone audit: implementation issues #575 through #612 plus #642, #643, and #644 are closed and merged with green checks. The release PR closes the Milestone 7 master tracker (#574) and release issue (#613).
