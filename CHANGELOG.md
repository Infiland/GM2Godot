# Changelog

## 0.7.52 - 2026-07-23

- Extracted dependency-only `shared_models`, `expression_models`, and `result_models` owners for cross-phase tokens/context/static metadata, the complete expression AST union, and preprocessing/diagnostic/source-map/transpile results.
- Migrated phase, converter, and test consumers to non-underscore typed exports while retaining only the frozen top-level facade's private model aliases for #820; the #815 baseline dropped exactly 120 internal private model edges and replaced four production private model imports.
- Preserved dataclass fields, defaults, frozen/equality behavior, error locations/messages, result serialization, supported facade identities/signatures, transpiled GDScript, source maps, diagnostics, and generated project output while removing four model-only private-usage suppressions.

## 0.7.51 - 2026-07-23

- Added an AST-based GML transpiler boundary inventory covering every private facade/phase imported-name edge and every production import from the facade or phase package, with exact owner, consumer, classification, and staged #816–#820 disposition.
- Froze the 44 supported non-underscore facade exports and callable signatures separately from 30 legacy private exports, and made new, missing, stale, or unclassified boundary edges fail focused architecture tests.
- Recorded the transitional private-usage suppressions without broadening them and documented the no-growth baseline and ordered migration non-goals; transpilation, diagnostics, source maps, and generated project output remain unchanged.

## 0.7.50 - 2026-07-23

- Added pinned coverage.py line and branch measurement for `main.py`, `src/`, and maintained `scripts/`, collecting the existing full unittest suite once and publishing JSON and Cobertura XML reports from required pull-request CI.
- Enforced the measured clean-main overall floor plus separate converter-orchestration, manifest/diagnostic, project-parsing, and GML-transpiler line and branch floors with exact production-source inventory validation and actionable diagnostics.
- Added controlled below-floor, source-scope, branch-configuration, dependency-lock, workflow, and artifact-publication tests, plus contributor guidance for reproducing and intentionally raising the reviewed floors.

## 0.7.49 - 2026-07-22

- Expanded the clickable release-notes view from the latest release to the ten newest published GitHub release changelogs, each labeled and linked to its release.
- Added a localized **Show more** action that requests subsequent ten-release pages, appends them without discarding visible history, and remains retryable after a transient failure.
- Added strict GitHub response validation plus focused network, pagination, rendering, localization, and failure-preservation tests.

## 0.7.48 - 2026-07-22

- Replaced heuristic shader substitutions with a tokenized GameMaker GLSL ES declaration parser that handles multi-line, array, and comma-separated attributes, varyings, uniforms, constants, and precision declarations before merging paired stages.
- Mapped supported 2D position, colour, texture-coordinate, base-texture, varying, and world/view/projection semantics to Godot 4.7.1 CanvasItem shaders while retaining custom uniforms instead of guessing time semantics.
- Added source-linked fail-closed diagnostics and failed-resource accounting for unsupported attributes, matrix/clip-space paths, scalar matrix constructors, Godot built-in name collisions, preprocessor directives, conflicting declarations/functions, and unlinked varyings, plus a provenance-pinned real shader corpus compiled and loaded by exact Godot 4.7.1.

## 0.7.47 - 2026-07-22

- Converted supported authored GameMaker sprite, instance, audio, text, nested-sequence, and audio-effect tracks into deterministic managed sequence descriptors with ordered asset/parameter keys, assign/linear interpolation, transforms, playback speed modes, draw order, and nested runtime evaluation.
- Converted sequence moments and broadcast keyframes plus legacy timeline GML moments into deterministic GameMaker frame order, including broadcast `event_data`, eager object-track creation, managed per-track audio buses/effects, and exact cleanup.
- Added source-linked partial-conversion diagnostics for every unsupported sequence track/key/effect or timeline action type, mixed current-LTS fixtures, and exact Godot 4.7.1 resource/playback/order coverage. Runtime-authored tracks, object overrides, animation-curve keys, clip masks/groups, particle sequence tracks, and unmapped audio/text effects remain explicit non-goals.

## 0.7.46 - 2026-07-22

- Converted authored GameMaker particle systems into stable generated Godot resources and normalized runtime descriptors for embedded particle types, emitters, origins, draw order, regions, timing, secondary-spawn metadata, and supported visual properties.
- Instantiated asset-backed particle systems from GML and room particle-layer elements with preserved layer visibility/depth and element transforms, mapped lifetime, shape, motion, colour/alpha, scale, textures, blend and stream/burst behavior to Godot 4.7.1 particles, and cleaned up room-owned systems, emitters, types, and nodes.
- Added source-linked diagnostics for unsupported attractor, destroyer, deflector, and changer data plus a current authored asset/room fixture and exact Godot 4.7.1 descriptor, lifecycle, and leak coverage.

## 0.7.45 - 2026-07-22

- Converted GameMaker Precise masks into alpha-tolerance-clipped pixel geometry, compositing all subimages for static masks and generating independently switchable geometry for Precise Per Frame sprites.
- Kept active masks aligned with sprite origin, frame, `sprite_index`, `image_index`, scale, and rotation, and made collision events, movement checks, and point/rectangle/line/circle query variants consume the same transformed geometry.
- Added structured safe-fallback diagnostics for masks that cannot be represented exactly plus focused conversion tests and an exact Godot 4.7.1 fixture distinguishing rectangle, static precise, and per-frame outcomes.

## 0.7.44 - 2026-07-22

- Made generated bound methods receive invocation-time `other` from the calling `self` through nested dynamic calls, `method_call`, script dispatch, and array/struct callbacks instead of retaining declaration-time scope.
- Replaced custom-versus-standard `Callable` arity inference with explicit generated receiver metadata, preserved that metadata when rebinding script references and constructors, and fail closed when an unmarked custom Godot callable cannot be safely rebound.
- Added a focused GameMaker fixture plus exact Godot 4.7.1 coverage for nested `self`/`other`, normal and rebound script calls, callback context, constructor `other`, single receiver injection, generated output, and unsupported metadata paths.

## 0.7.43 - 2026-07-21

- Added explicit logical output ownership for objects, rooms, sprites, shaders, and timeline action scripts; selected converters now rebuild those outputs from the authoritative YYP instead of carrying their prior inventory entries into a successful or partial candidate.
- Made successful publication delete unavailable, blocked, skipped, and removed resources through the existing recoverable old-or-new transaction, reconcile aggregate registry/manifest references to the frozen files that remain, and clear only a stale GM2Godot-managed room startup scene.
- Added repeat-conversion, source-loss, transpile-blocker, multi-file cleanup, cancellation, rollback, fail-closed user-file, disabled-converter compatibility, and exact Godot 4.7.1 validation coverage without changing failed/cancelled preservation or unrelated-file guarantees.

## 0.7.42 - 2026-07-21

- Added a classified, deterministic subprocess hard-exit matrix over real project-setting, script, object, registry, canonical-evidence, forward commit, reverse rollback, restart recovery, and private cleanup boundaries; every interruption now proves an exact inventory/manifest/attempt-consistent previous or desired generation and idempotent recovery.
- Made crash-interrupted cleanup remove only the journal-identity-bound detached stage on restart, including read-only native Windows trees, and made repeated pre-commit recovery accept an already-removed created directory only after every managed transition verifies the complete prior generation.
- Added strict real-mutation recovery-artifact, ambiguity, independent recovery-failure, CLI `SIGINT`, GUI stop-event, direct-library cancellation, same-filesystem, Linux bind-mount, Windows junction/reparse/write-through, and native Linux/macOS/Windows CI gates while retaining the #715 stale-resource policy and live-writer guarantees as non-goals.

## 0.7.41 - 2026-07-21

- Routed `Converter.convert()`, GUI/library callers, CLI-managed reports, every selected converter and project-setting operation, architecture/diagnostic finalizers, inventory validation, and canonical-manifest construction through one destination-local managed-output workspace.
- Made runtime, cancellation, finalizer, staged-validation, and ordinary publication failures preserve the prior managed generation byte- and mode-exact while publishing only a separate attempt ledger whose preserved canonical output is transactionally verified; the final cooperative cancellation check now precedes the durable generation decision.
- Added real project-setting/script/registry mutation coverage for successful publication, failure rollback, cancellation during converter/finalizer/validation work, the pre-decision boundary, user sentinels, and native Windows integration, without adding the exhaustive hard-exit matrix or stale logical-resource invalidation policy.

## 0.7.40 - 2026-07-21

- Added a destination-wide publisher that consumes one verified `ManagedOutputWorkspace` and frozen previous/desired inventories, durably journals identity-bound same-filesystem stages and backups before public mutation, installs managed creates/replacements/removals with canonical attempt/manifest evidence last, and selects the complete new generation through one durable commit pointer.
- Added reverse ordinary rollback and idempotent pre-/post-decision recovery with byte- and mode-exact verification, attempt-only publication after prior-generation verification, strict bounded records, and a separate machine-readable recovery artifact that preserves ambiguous material and reports the transaction, affected paths, selected generation, and safe retry action.
- Added focused synthetic multi-directory, stage/commit/rollback/cleanup failure, recovery retry, concurrent replacement, no-follow, symlink, hard-link, mount, POSIX directory-swap, native Windows junction/read-only/write-through, bounded-parser, and deterministic evidence coverage without routing production converters or implementing stale logical-resource cleanup.

## 0.7.39 - 2026-07-21

- Added one immutable, deterministically sorted managed-generation inventory with normalized destination-relative paths, output kinds, converter-step or explicit shared ownership, byte counts, SHA-256 receipts, and exact rollback modes.
- Made format-v2 canonical manifests render their additive format-v1 `generation_inventory` and complete backward-compatible `generated_files` view from the same frozen model, including disabled-converter carry-forward and jointly managed `project.godot`, while excluding attempt, lock, recovery, workspace, `.godot/`, and unrelated state.
- Added bounded legacy-manifest migration, pre/post-publication digest validation, and focused ordering, worker-count, separator, repeated-run, `--only`, collision, malformed/oversized, same-size mutation, POSIX link/mount, and native Windows junction/read-only coverage without routing converters to staging or implementing destination-wide commit/recovery.

## 0.7.38 - 2026-07-20

- Added a reusable destination-wide managed-output workspace session with a non-blocking operating-system lock, destination-local private stages, explicit same-filesystem proof, and retained no-follow destination, staging-parent, and stage bindings.
- Added exact allowlist snapshot and streaming-copy primitives plus bounded identity-bound ownership markers and fail-closed cleanup that preserves redirected, mounted, hard-linked, replaced, or unknown lookalike state without changing public destination bytes or modes.
- Added focused cancellation, staging-failure, lock-contention, cleanup-retry, POSIX path-swap/symlink/hard-link/mount, and native Windows junction/read-only coverage while preserving GameMaker LTS 2026 and exact Godot 4.7.1 behavior; production converters are intentionally not routed through this foundation yet.

## 0.7.37 - 2026-07-20

- Moved format-v2 Included File integrity establishment into the generated `GMRuntime` autoload startup, before script initialization or the main scene, so normal exact-path, canonical-path, `file_exists`, text-read, and buffer-load calls perform no full-payload checksum.
- Made startup verification an all-or-nothing generation gate with deterministic sequential 1 MiB SHA-256 chunks, bounded memory, strict registry receipts, and fail-closed handling for missing, malformed, incomplete, or same-size-modified loose payloads.
- Added a deterministic 64 MiB first-access measurement, pre-trust mutation and missing-registry adversarial coverage, and exact Godot 4.7.1/GameMaker LTS 2026 validation.

## 0.7.36 - 2026-07-20

- Reused immutable source and staged-output content receipts during changed Included Files publication while binding them to the exact source path and handle, assigned path, output identities, transaction, and generation.
- Retained final source and published-tree SHA-256 validation before the commit marker, so same-size mutation, replacement, redirection, mount, hard-link, and directory-swap failures still restore the previous complete root/registry generation.
- Bounded the deterministic 64 MiB changed-payload path to at most 8x payload reads while retaining the existing 5x initial and 4x unchanged bounds, with focused receipt-boundary, rollback, and exact Godot 4.7.1/GameMaker LTS 2026 coverage.

## 0.7.35 - 2026-07-20

- Added deterministic format-v2 Included Files recovery records with compact fixed-width tree rows while retaining strict canonical parsing and recovery for existing format-v1 journals and commit markers.
- Preflighted the byte-exact journal and commit serialization before creating a payload stage, publishing recovery state, or changing the public generation, without increasing the 16 MiB canonical-record limit.
- Added malformed and bounded-parser coverage, old/new-format interruption recovery at every publication boundary, a deterministic 13,866,493-byte changed-generation preflight, and 10,000-file publication/recovery under exact Godot 4.7.1 and GameMaker LTS 2026 validation.

## 0.7.34 - 2026-07-20

- Replaced recursively nested ancestor checks during descriptor-pinned Included Files capture with direct parent/child verification over the retained descriptor chain, reducing binding work from quadratic to linear in tree depth.
- Applied equivalent current-directory identity verification to the path fallback used on native Windows while retaining no-follow opens, mount rejection, deterministic ordering, pre/post binding checks, and fail-closed handling of directory replacement and concurrent mutation.
- Added deterministic depth-scaling bounds, descriptor/fallback snapshot equivalence, deep ancestor-swap coverage, and exact GameMaker LTS 2026 and Godot 4.7.1 compatibility validation.

## 0.7.33 - 2026-07-20

- Bounded unchanged-generation receipt validation and changed-generation Included Files staging to at most twice the configured worker count, so future and submission bookkeeping no longer scales with the complete source set.
- Stopped admitting work after cancellation or the first observed terminal worker failure, then cancelled or drained only the bounded remainder while preserving the previous complete root/registry generation.
- Added a deterministic 10,000-source window probe, failure/cancellation admission tests, cross-worker output/receipt/diagnostic equivalence coverage, and exact Godot 4.7.1 and GameMaker LTS 2026 compatibility validation.

## 0.7.32 - 2026-07-19

- Published `conversion_attempt.json` and the optional canonical `conversion_manifest.json` as one recoverable generation using a durable transaction journal and persistent commit pointer while preserving both stable public paths and JSON schemas.
- Added a project-local operating-system lock, bounded canonical recovery records, strict legacy digest migration, and fail-closed handling for malformed, redirected, mounted, hard-linked, replaced, or unknown recovery state.
- Added POSIX and native Windows subprocess hard-exit coverage across every journal, artifact, pointer, rollback, and cleanup decision boundary, plus exact Godot 4.7.1 and GameMaker LTS 2026 compatibility validation.

## 0.7.31 - 2026-07-19

- Anchored the four CLI static compatibility reports to one shared verified-directory byte-artifact transaction for exact snapshots, private staging, backups, deterministic ordered commits, durability barriers, rollback, cleanup, and final receipt validation.
- Replaced destructive report-set invalidation with exact prior-byte and mode restoration after render, stage, replacement, sync, interruption, or validation failure, including portable mode preservation when descriptor chmod is unavailable.
- Added focused failure, ordering, hard-link, physical POSIX directory-replacement, native Windows relocation, and exact Godot 4.7.1 regression coverage while preserving the stable report paths and GameMaker LTS 2026 compatibility surface.

## 0.7.30 - 2026-07-19

- Anchored conversion-attempt and canonical-manifest staging, backup reads, attempt-first replacement, rollback, recovery retention, stale cleanup, durability barriers, and final receipts to one shared verified-directory byte-artifact transaction.
- Preserved stable artifact paths, exact modes, Windows read-only behavior, asset-registry revalidation, the `updated` / `preserved` / `absent` trust contract, and canonical SHA verification while rejecting physical directory replacement at every publication boundary.
- Added adversarial POSIX replacement and hard-link sentinel coverage across staging, backup, both commits, every sync, rollback, recovery and cleanup, plus native Windows relocation coverage and exact Godot 4.7.1 validation.

## 0.7.29 - 2026-07-19

- Anchored diagnostic JSON/Markdown capture, publication, restoration, invalidation, rollback, recovery retention and cleanup to the shared verified-directory byte-artifact transaction.
- Bound snapshots and receipts to both the report root and `gm2godot/` identities, with component-by-component creation and parent durability barriers for missing external report roots.
- Preserved stable paths, Markdown-first ordered commit, exact modes, read-only handling and ordinary-failure rollback; added physical replacement coverage across pair phases and documented that hard-crash pair atomicity remains future work.

## 0.7.28 - 2026-07-19

- Anchored architecture-policy publication and restoration to one retained destination-directory binding, using descriptor-relative POSIX operations, no-delete-share Win32 handles, write-through Windows moves, and an explicit verified-path fallback.
- Added a reusable ordered byte-artifact transaction with exact snapshots, receipts, modes, per-entry concurrency checks, reverse rollback continuation, recovery retention, cleanup, and write-through absence tombstones on Windows.
- Added adversarial directory-replacement, rollback, receipt-drift, read-only hardlink, native junction, relocation, Unicode long-path, and exact Godot 4.7.1 validation coverage.

## 0.7.27 - 2026-07-19

- Published the Included Files root and runtime registry as one journaled, recoverable generation: interruption before the durable commit marker restores the exact previous pair, while interruption after it verifies and finalizes the complete new pair on the next conversion.
- Serialized recovery and publication with a persistent project-local operating-system lock, durable POSIX directory synchronization and Windows write-through moves, strict size-bounded record recovery, cross-device and mount-boundary rejection, confined Windows recovery paths, and bounded-memory snapshot-driven tombstones that preserve unknown reserved-path replacements.
- Added format-v2 runtime registry content receipts so Godot 4.7.1 verifies each packaged file's byte count and SHA-256 before exposing it, plus subprocess hard-exit coverage across every forward publication boundary and the owned cleanup quarantine/removal boundaries.

## 0.7.26 - 2026-07-19
- Hardened native Windows Included Files cleanup so identity-verified read-only transaction files and directories are made writable only inside recoverable quarantine, with attributes restored when deletion fails and shared hard-link aliases preserved fail-closed.
- Added native NTFS junction and read-only transaction tests covering managed roots, nested trees, registry and staging directories, backup destinations, successful cleanup, commit failure, cancellation, and rollback.

## 0.7.25 - 2026-07-19

- Skipped unchanged Included Files publication only after the complete planned output topology, rendered registry bytes, and two stable source-content receipts match the descriptor-captured public generation.
- Kept the initial transaction at five full payload reads and bounded a deterministic 64 MiB unchanged generation to four, while pinned no-follow tree, registry, source-path, directory-identity, and final metadata checks make changed or concurrently mutated candidates use the normal transaction or fail closed without staging.

## 0.7.24 - 2026-07-19

- Reused attempt-local Included File receipts across asset-registry and manifest publication, reducing successful matching Included File validation from 12x payload reads to at most 6x while binding reuse to the exact source, generated output, assigned path, and output generation.
- Preserved final SHA-256 and path-versus-handle identity checks, with Win32 read handles denying concurrent write/delete sharing while the final receipts are hashed, so content mutation, path replacement, hard-link substitution, redirected paths, and directory swaps still fail closed.

## 0.7.23 - 2026-07-19

- Replaced read-only generated text outputs on Windows through identity-bound handles, no-replace quarantine moves, and POSIX-style read-only disposition without path-level chmod or cleanup races.
- Restored the exact prior identity and bytes on every pre-commit failure, preserved unknown namespace replacements, retained exact POSIX modes, and added native Windows coverage for the shared registry, group-report, and timeline writers.

## 0.7.22 - 2026-07-19

- Declared Ubuntu 24.04 x86_64 as the packaged Linux baseline, supplied QtGui's required EGL/GL providers and XCB libraries during dependency analysis, and intentionally excluded the unused Qt TIFF plugin whose obsolete `libtiff.so.5` ABI is unavailable on that baseline.
- Made the release build fail on unresolved shared-library warnings and validate the extracted Linux archive under the real `qxcb` platform in Xvfb, including bundled-library inventory, executable permissions, GUI readiness, fatal loader diagnostics, and bounded process cleanup.

## 0.7.21 - 2026-07-19

- Forwarded exact terminal conversion outcomes through the GUI worker so partial, failed, and cancelled runs no longer collapse into the green success state.
- Added localized resource-count and diagnostic-report guidance with distinct success, partial, failed, and cancelled presentation.

## 0.7.20 - 2026-07-19

- Stamped the macOS app bundle with the stable `land.infi.gm2godot` identifier and exact three-component release version from `src/version.py` for both its short and build versions.
- Added fail-closed metadata checks for the source `.app`, release ZIP, and DMG so inconsistent, missing, malformed, or placeholder bundle metadata stops artifact publication.

## 0.7.19 - 2026-07-19

- Pinned the complete CPython 3.12 runtime and tooling dependency graphs for the exact Linux x64, macOS arm64, and Windows x64 release tuples, with native pip-tools generation, self-hosted regeneration, strict installed-distribution receipts, `pip check`, and two fresh empty-cache installs per platform.
- Constrained every CI, release, Godot 4.7.1, GameMaker LTS 2026 fixture, and supported local-build install site to reviewed wheel-only pins; added fail-closed inventory and adversarial transitive-drift tests plus reproducible installation and refresh guidance.

## 0.7.18 - 2026-07-19

- Made each pre-mutation ownership gate tolerate only well-formed authenticated release listings whose exact-tag match set is temporarily empty, using seven bounded full-gate snapshots with exponential backoff; every retry revalidates the exact tag, run-owned draft by ID, uploaded asset prefix, published-tag absence, and complete draft-aware listing before any mutation.
- Persisted every empty-match retry, terminal visibility exhaustion, and nonempty identity drift decision in the ownership receipt while keeping foreign IDs, malformed responses, mutation failures, and ambiguous outcomes immediately terminal and never retrying uploads or publication.

## 0.7.17 - 2026-07-19

- Replaced the update-capable release action with a create-only publisher that seals the exact `main` event SHA and five local asset receipts, claims the tag through one validated `201 Created` response, and derives the only writable release ID from this run's validated draft-creation response.
- Bound every asset upload and finalization request to that run-owned numeric release ID, with draft-aware uniqueness, exact tag-target, owned-state, and uploaded-prefix gates before each mutation; collisions, ambiguous responses, and drift fail closed without retry, adoption, deletion, replacement, or automatic rollback.
- Added an atomic recovery receipt plus final release-by-ID, release-by-tag, tag, asset, and paginated uniqueness verification, and replaced the third-party publisher smoke with a local pre-network rejection check.

## 0.7.16 - 2026-07-18

- Added an operationally read-only audit for existing-tag release reruns: it requires one exact published release, verifies the exact five uploaded assets through independent paginated API state, downloads by asset ID into a private temporary directory, and checks sizes plus GitHub SHA-256 digests.
- Made the rerun audit enforce the canonical four-payload `SHA256SUMS` bytes, recheck the exact tag/release/asset receipt after downloads, fail closed on API/schema/download/concurrent-state errors, and leave builds and publication skipped.

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
