# Changelog

## 0.6.1 - 2026-05-28

- Added CLI version output, converter inventory discovery, JSON inventory output for automation, and direct `python -m src.cli` execution.
- Documented the new CLI commands and incremented the source version for issue #660.

## 0.6.0 - 2026-05-28

Milestone 7: GML Transpiler Part 2.

- Expanded current GMS2+ GML compatibility indexing, diagnostics, CLI reporting, source maps, runtime segment validation, and generated-output manifests.
- Added broad Part 2 transpiler/runtime coverage for value semantics, dynamic variables, accessors, constructors, control flow, macros, project metadata, rooms, layers, paths, tilesets, timelines, sequences, particles, async queues, draw phases, input events, collisions, data structures, files, buffers, networking, audio, cameras, display/window APIs, movement, physics, platform services, and runtime managers.
- Added pinned Godot smoke validation, external project conversion gates, golden conversion snapshots, Ruff code-health checks, fixture corpus coverage, architecture policy reports, and contributor/runtime documentation.
- Milestone audit: implementation issues #575 through #612 plus #642, #643, and #644 are closed and merged with green checks. The release PR closes the Milestone 7 master tracker (#574) and release issue (#613).
