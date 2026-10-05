# Testing And Codebase Improvement Checklist

This file tracks engineering work that will make full transpilation safer to build and maintain.

## Current Strengths

- [x] Strict Pyright configuration exists in `pyrightconfig.json`.
- [x] Pyright CI workflow exists.
- [x] Python unittest CI workflow exists.
- [x] Broad tests exist for GML transpiler behavior.
- [x] Broad tests exist for generated runtime behavior.
- [x] Tests exist for many resource converters.
- [x] Tests exist for event mapping modules.
- [x] External project conversion tests exist for real-world projects.
- [x] Runtime is split into named GDScript segments.
- [x] Event mappings are modularized into registry and mapping modules.
- [x] GML API manifest includes status, category, notes, issue references, docs URLs, and coverage metadata.
- [x] Manifest integrity tests exist.
- [x] Fixture catalog for part of the compatibility roadmap exists.
- [x] Object conversion preserves transpile failures as warnings instead of crashing the whole conversion.

## P0: CI And Validation

- [x] Run required headless smoke CI with exact Godot `4.7.2.stable.official.ed1daf0bf` and its pinned archive checksum.
- [ ] Partial: CI discovers `test_*_godot.py` with the pinned binary; deliberate host, fixture and capability conditions still determine which cases are eligible.
- [x] Validate generated GDScript syntax through the pinned headless Godot validator and committed smoke/fixture corpus.
- [x] Validate generated scene/resource loading through headless Godot, with explicit import-only and boot policies.
- [ ] Add external-project conversion assertions for unsupported/transpile-warning counts.
- [ ] Add failure thresholds for unsupported APIs, invalid generated code, missing assets, and skipped resources.
- [x] Add committed minimal `.yyp/.yy` fixture project corpus.
- [ ] Add end-to-end golden conversion tests over fixture projects.
- [ ] Snapshot selected generated `project.godot`, `.tscn`, `.gd`, registry, and runtime outputs.
- [ ] Normalize nondeterministic IDs and paths in snapshots.
- [ ] Add deterministic output tests for ordering, ext_resource IDs, object/room ordering, and dictionary traversal.
- [ ] Add manifest-to-runtime/emitter consistency tests.
- [x] Add manifest-to-fixture coverage budgets.
- [ ] Add durable unsupported-feature report artifacts as JSON and Markdown.

## P0: Diagnostics And User Reports

- [x] Provide the typed `DiagnosticCollector` and deterministic JSON/Markdown report publication.
- [x] Define typed severity, code and message fields plus optional source path, line, column, resource/type, event, API, manifest entry, issue number and workaround context.
- [x] Record the reviewed classified converter warning/error producers through typed diagnostics while preserving raw callback text/order and message-level report dedup.
- [x] Include collected GML transpile failures and their available source context in conversion diagnostic reports.
- [x] Report known unsupported GML API diagnostics and static manifest compatibility coverage.
- [ ] Emit conversion report for skipped resources.
- [x] Emit source-linked conversion diagnostics for unsupported shader constructs and failed logical shader resources.
- [ ] Emit conversion report for unsupported platform services.
- [x] Include pinned-validator failures in diagnostic reports and write the generated Godot validation report.
- [x] Provide CLI `--fail-on-unsupported` and explicit diagnostic thresholds.
- [x] Provide the CLI `analyze` command without writing converted output.

## P1: Architecture Boundaries

- [x] Introduce typed `ConversionContext` shared by converters.
- [x] Replace hard-coded converter sequence with explicit dependency graph.
- [x] Split source discovery/parsing from Godot rendering/writing for resource converters.
- [x] Create typed intermediate models for projects, sprites, sounds, fonts, objects, rooms, layers, scripts, shaders, tilesets, paths, sequences, timelines, and diagnostics.
- [x] Separate parser AST, semantic analysis, and GDScript emission phases more sharply.
- [x] Move asset-specific lowering rules out of the general expression emitter where possible.
- [x] Give CLI report publication/repair and cancellation/signal state dedicated typed owners while preserving the driver’s trace and return boundaries.
- [x] Install the GUI/CLI package with authoritative root assets and runtime segments, preserving source/frozen resource and preference behavior.
- [x] Gate main release publication on successful exact-SHA quality workflows and the Build native/preflight prerequisites.
- [ ] Unify arity, lowering kind, manifest status, docs URL, runtime function name, and tests in one source of truth.
- [ ] Add explicit runtime segment dependency declarations.
- [ ] Add event mapping manifest with event type, event number, callback, runtime requirements, support status, test path, and issue reference.

## P1: Manifest And Coverage

- [ ] Split or generate `gml_api_manifest.py` from smaller category data files.
- [ ] Add CLI command to print compatibility reports as Markdown, JSON, and CSV.
- [ ] Validate unique API names.
- [ ] Validate category names.
- [ ] Validate support flag combinations.
- [ ] Validate docs URL shape.
- [ ] Validate owner module importability or runtime segment existence.
- [ ] Validate issue URL format.
- [ ] Detect duplicate category keys that Python would collapse silently.
- [ ] Add diagnostics-to-docs mapping with stable diagnostic codes.
- [ ] Add compatibility coverage trend artifacts to CI.
- [ ] Add status-regression checks for manifest entries.
- [ ] Tie fixture unsupported API references to actual conversion diagnostics.

## P1: Generated Code Stability

- [ ] Add golden tests for full `generate_script_content` outputs.
- [ ] Add tests for duplicate functions, bad ordering, invalid indentation, and invalid surrounding code.
- [ ] Add GDScript formatting or parser checks through Godot.
- [ ] Add source map metadata tests.
- [ ] Add deterministic ID/path utilities across objects, rooms, sprites, layers, and registries.
- [ ] Add tests for inherited object event ordering.
- [ ] Add tests for parent chain cycles.
- [ ] Add tests for missing parent files.
- [ ] Add tests for duplicate resource names in different folders.
- [ ] Add tests for resource names colliding with GDScript reserved words.
- [ ] Add tests that non-empty event code cannot silently become `pass` without a diagnostic.

## P1: Real GameMaker Fixtures

- [x] Add fixture projects for shaders and materials.
- [x] Add fixture projects for paths.
- [x] Add fixture projects for timelines and sequences.
- [x] Add fixture projects for particles.
- [x] Add fixture projects for physics.
- [x] Add fixture projects for tilemaps.
- [x] Add fixture projects for views and layer inheritance.
- [x] Add fixture projects for extension functions.
- [x] Add fixture projects for macros and configs.
- [x] Add fixture projects for included files.
- [x] Add fixture projects for fonts.
- [x] Add fixture projects for texture groups.
- [x] Add fixture projects for audio groups.
- [x] Add fixture projects for options and platform settings.
- [ ] Add multiple GameMaker version fixtures if supporting more than the currently documented version.
- [x] Add malformed/missing `.yy` fixtures.
- [ ] Add fixtures that prove conversion can continue after unsupported features while preserving diagnostics.

## P2: Pyright, Lint, And Code Health

- [ ] Reduce broad file-level Pyright suppressions over time.
- [x] Add Ruff or equivalent linting.
- [x] Add complexity checks for parser/emitter/runtime generation modules with threshold 15 and individually reviewed, ratcheting function exceptions.
- [x] Add import sorting.
- [x] Enforce import placement (`E4`) without new suppressions; event tests use normal package imports and deliberate bootstrap/discovery stages remain explicit.
- [x] Add unused code checks through the complete Pyflakes (`F`) family in local and tracked-source CI lint.
- [x] Enforce 26 focused bug-risk selectors without blanket ignores; retain separate reviews for callback lifetimes and exception causes.
- [ ] Add broad exception checks.
- [ ] Add unreachable branch checks.
- [x] Add typed `.yy` dataclasses or `TypedDict` models instead of repeated casts.
- [x] Document required local Pyright, configured and tracked-source Ruff, complexity, and unittest commands as the equivalent checks before a commit.
- [ ] Partial: event tests use normal package imports; 41 ordinary unittest prefix guards remain. Standalone verifier and Godot-discovery barriers retain their deliberate contracts.
- [x] Add shared test utility for live Godot binary discovery with the original lookup order.
- [x] Add shared UTF-8 fixture-writing helpers; 50 compatible test modules use shared discovery, writes or standard scene launches while assertions, skips and specialized capability/launch policies stay local.
- [x] Add Python coverage reporting and coverage floor for core modules.

## P2: Runtime Maintainability

- [x] Add per-segment ownership docs.
- [x] Add public runtime function indexes.
- [ ] Split runtime segments when they accumulate unrelated concerns.
- [ ] Add concatenation tests for segment ordering.
- [ ] Add tests for duplicate runtime function names.
- [ ] Add tests for duplicate runtime constants.
- [ ] Add event mapping conflict tests across modules.
- [x] Add docs for event execution order and deviations from GameMaker semantics.
- [x] Add docs for runtime state, global state, and persistence behavior.

## P2: Documentation And UX

- [x] Update README to reflect that the project now includes substantial GML transpilation and runtime work.
- [x] Update setup docs to match current dependencies.
- [ ] Add compatibility report document generated from the manifest.
- [ ] Add `What failed and what to do next` conversion report UX.
- [x] Add issue template for unsupported GML API reports.
- [x] Add issue template for invalid generated GDScript.
- [x] Add issue template for resource conversion mismatches.
- [x] Add issue template for fixture contributions.
- [x] Add CLI docs.
- [x] Add docs for adding a new GML API.
- [x] Add docs for adding a new runtime segment.
- [x] Add docs for adding a new resource converter.
- [x] Add docs for adding a new event mapping.
- [x] Add docs for adding a new fixture.
- [x] Add docs for known GameMaker/Godot semantic differences.

## Current Design Risks To Track

- [ ] Godot behavior can regress without CI catching it if Godot smoke tests skip.
- [ ] Manifest status can drift from actual dispatch/runtime implementation.
- [ ] Unsupported event transpilation can degrade to missing behavior while conversion still succeeds.
- [ ] Public transpiler facade exports private internals, making refactors risky.
- [ ] Runtime segment concatenation order is manual.
- [ ] String-based generated-code tests can miss invalid GDScript.
- [x] README and CONTRIBUTING docs may lag implementation maturity.
- [ ] External project CI can become non-reproducible if third-party repos are not pinned.
