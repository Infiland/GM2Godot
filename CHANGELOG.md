# Changelog

## 0.7.15 - 2026-07-18

- Validated every release artifact ZIP member table against exact flat regular-file allowlists before extraction, rejecting unsafe or alternate-path metadata, duplicate, extra, symlink, directory, and special-file entries while preserving the verified payload bytes.

## 0.7.14 - 2026-07-18

- Added a deterministic `SHA256SUMS` release asset for the four final platform payloads, with fail-closed file validation and executable manifest regression coverage.

## 0.7.13 - 2026-07-18

- Upgraded archived GitHub Actions artifact transport to immutable `actions/upload-artifact` v7.0.1 across release builds, release smoke, and bounded LTS failure reports, preserving the verified nested archive layout consumed by the v8 downloader.

## 0.7.12 - 2026-07-18

- Added a pull-request-only release-action smoke that round-trips and verifies a deterministic artifact through the production pins, then proves the release publisher loaded and stopped at a credentialless pre-network boundary without changing tags or releases.

## 0.7.11 - 2026-07-18

- Enabled weekly Dependabot checks for SHA-pinned GitHub Actions while preserving immutable references and their same-line release-version comments.

## 0.7.10 - 2026-07-18

- Serialized the two-run workflow publisher race across tag checks, builds, and publication without blocking pull-request validation; the surviving waiter rechecks the exact tag, same-version release state detected without that tag fails before builds with manual-recovery guidance, and asset collisions are non-overwriting.

## 0.7.9 - 2026-07-18

- Made release reruns idempotent through an authoritative exact remote-tag check: existing versions skip builds and publication without changing assets, absent tags proceed, and lookup failures stop the workflow; updated maintainer guidance to match.

## 0.7.8 - 2026-07-18

- Aligned Included File emission, asset registry and conversion-manifest paths, and generated GML file APIs on `res://included_files/`, using GameMaker packaged-name normalization (ASCII `A`–`Z` to lowercase and spaces to underscores) with deterministic collision-safe suffixes and diagnostics.
- Preserved `user://gm2godot/`-first relative read precedence over packaged defaults and added exact Godot 4.7.1 end-to-end coverage for nested `file_exists()`, text-file reads, and `buffer_load()`.
- Confined Included File publication against redirected or non-regular destination paths, hardlink referent mutation, and tested late path swaps while preserving binary bytes and source metadata.
- Made Included File integrity checks portable across Windows path and handle metadata while retaining exact same-handle and SHA-256 source/output mutation detection, and expanded the native Windows transaction regression job.
- Made `res://included_files/` and its generated runtime registry one converter-owned output set whose previous pair survives ordinary conversion failures and cancellation. Its separate publication steps are not process-crash-atomic, so conversion must not run alongside a live game or another converter until [#727](https://github.com/Infiland/GM2Godot/issues/727) is implemented.

## 0.7.7 - 2026-07-18

- Upgraded the release-only artifact download action to immutable v8.0.1, retained fail-closed SHA-256 digest verification, and bypassed its deprecated Node extraction dependency before native archive extraction.
- Added regression coverage for the verified-archive download mode and the exact Linux, macOS, and Windows extraction layout consumed by the release publisher.

## 0.7.6 - 2026-07-18

- Pinned every GitHub Actions dependency to an immutable commit backed by a Node 24-native release, eliminating mutable tag drift and retired Node 20 runtime warnings.
- Added repository policy checks that reject unpinned or non-Node-24-native action references before workflow changes can merge.

## 0.7.5 - 2026-07-18

- Added reviewable GitHub Wiki sources with installation, conversion, compatibility, diagnostics, generated-runtime, contributor, and maintainer guidance for GameMaker LTS 2026 and Godot 4.7.1.
- Corrected stale destination, localization, UI, support, code-of-conduct, and license documentation, and added a versioned release/Wiki review checklist with local link coverage.

## 0.7.4 - 2026-07-18

- Added format-v2 trusted conversion manifests with terminal outcomes and plan-ordered requested, executed, completed, skipped, and failed step names for successful and partial conversions.
- Added a per-run `conversion_attempt.json` outcome ledger after destination preflight for success, partial, failure, and cancellation, preserving an existing canonical manifest as an explicitly unverified historical baseline after unsuccessful attempts.

## 0.7.3 - 2026-07-18

- Added explicit `success`, `partial`, `failed`, and `cancelled` conversion outcomes with machine-readable converter/resource counts, deterministic CLI summaries, and an opt-in for automation that accepts partial output.
- Hardened current GameMaker LTS resource accounting and output publication, including Included Files paths, extension and timeline collisions, reusable converter runs, and transactional no-follow report writes.

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
