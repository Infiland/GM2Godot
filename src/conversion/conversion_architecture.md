# Conversion Architecture

This document records the boundaries used by the converter orchestration and
the GML transpiler. It is intentionally implementation-facing: tests assert the
module names and responsibilities below so future refactors keep these seams
visible.

## Conversion Run Context

`conversion_context.ConversionContext` is the typed run state shared by the
orchestrator and conversion step factories. It carries source and target paths,
target platform, callbacks, the running flag, diagnostics, worker settings, and
the enabled converter set. New converter wiring should receive this context
instead of adding another parallel list of constructor arguments.

## Conversion Plan

`conversion_plan.CONVERSION_STEPS` is the single dependency graph for
converter execution. Each step has a stable key, a group (`project`, `assets`,
or `wip`), a localized log key, and optional dependencies. The planner orders
enabled steps topologically but does not auto-enable dependencies; user settings
still define the conversion surface.

## Resource Models

`resource_models.parse_gamemaker_resource_models()` parses `.yyp` and `.yy`
metadata into typed intermediate models without accepting a Godot output path
and without writing files. The model layer currently covers project metadata,
sprites, sounds, fonts, objects, rooms, room layers, scripts, shaders, tilesets,
paths, sequences, timelines, generic remaining resources, and diagnostics.
Converters can adopt these models incrementally as resource-specific renderers
are separated from discovery and parsing.

## GML Pipeline Phases

The dependency-only typed model layer has four explicit owners:

- `gml_transpiler_parts.shared_models` owns tokens, scope context, static
  declarations, assignment/increment aliases, extension-function metadata, and
  `GMLTranspileError`.
- `gml_transpiler_parts.expression_models` owns every expression AST node, the
  complete `Expression` union and its `GMLExpression` alias, and the frozen
  `GMLExpressionEmission` text/precedence result.
- `gml_transpiler_parts.statement_models` owns the frozen
  `GMLStatementRequest` input contract, `GMLStatementResult` output contract,
  and `ControlFlowCapture` state shared only within statement parsing and
  lowering.
- `gml_transpiler_parts.result_models` owns preprocessing diagnostics/results,
  source diagnostics/maps, and transpile results.

These modules depend only on the standard library or another model module.
`gml_transpiler_parts.model` is now only the frozen private-alias compatibility
shim consumed by the top-level facade until #820.

`gml_transpiler_parts.lexical_api` is the typed package-internal entry point for
the lexical phase. Its exact 15-operation surface covers complete-source and
expression tokenization, normal and layout-preserving preprocessing, identifier
validation/sanitization/predicates, and the ordinary, verbatim, and template
string operations shared with source analysis. It returns the canonical
`shared_models.Token` and `result_models.GMLPreprocessResult` types rather than
parallel lexical models. Higher-level phases and production collectors import
those operations through `lexical_api`; the lexical owner cohort imports public
owner definitions directly, including the exact cycle-safe `utils` dependencies
needed by `preprocessor`. Cursor loops, numeric and character readers, delimiter
mechanics, directive matching, newline-search helpers, and template-expression
internals remain module-private.

`gml_transpiler_parts.expression_api` is the typed package-internal entry point
for the expression phase. Its exact 17-operation surface covers expression
parsing, normal and truthiness-aware emission, instance-keyword lowering,
constructor/static initialization, enum and constant validation, and the
direct-member/name-resolution queries consumed by higher phases. Cross-phase
emission returns `expression_models.GMLExpressionEmission`; the recursive
emitter keeps its tuple implementation private. Higher-level statement,
script, project-enum, and API consumers import through `expression_api`, while
the cycle-safe expression owner cohort imports exact public owner definitions
directly. Parser cursors, recursive parse/emission helpers, enum evaluator
mechanics, alarm-array recognition, and multiline formatting remain private.

`gml_transpiler_parts.statement_api` is the typed package-internal entry point
for the statement phase. Its exact three-operation surface consists of
`collect_static_declarations`, `parse_gml_statements`, and `static_scope_id`.
The parse operation accepts one frozen `GMLStatementRequest` naming every
orchestration input and returns one frozen `GMLStatementResult` with emitted
lines and final local, instance, scope, enum, and macro state. Top-level
orchestration and nested expression function bodies use this boundary; the
function-body route remains cycle-safe through a function-local import.
Control-flow capture has an explicit frozen model, while parser cursors and
matching, generated-name counters, recursive statement lowering, and
static-declaration mechanics remain private.

The GML transpiler has three explicit phase families:

- Parser phase: `gml_transpiler_parts.tokens`,
  `gml_transpiler_parts.expression_parser`, and `statement_parser` turn source
  text into typed token and AST structures.
- Semantic analysis phase: `preprocessor`, `gml_function_dispatch`,
  `gml_api_manifest`, `extension_functions`, and `asset_lowering` resolve
  configuration, API support, arity, extension mappings, and asset-argument
  lowering rules.
- GDScript emission phase: `emitter`, `expression_service`, and `api` render
  validated AST or statement output to GDScript and source-map metadata.

Asset-specific lowering metadata lives in `asset_lowering` so the generic
expression emitter does not own the GameMaker API argument tables.

### Frozen transpiler boundary baseline

`tests/test_gml_transpiler_architecture.py` is the machine-checked migration
baseline for #794. It records 31 private imported-name edges across 4
facade/phase module pairs and all 60 production imports from the facade or
phase package, including the 4 remaining private production import edges.
Every entry records its owner and consumer and is classified as the supported
public facade, an intended package-internal phase API, or a module-private
implementation that must move behind its owner.

The same test freezes the 44 supported non-underscore facade exports and their
signatures separately from the 30 underscore-prefixed legacy exports. It also
permits exactly the current 2 phase-package `reportPrivateUsage=false`
directives plus the facade directive. New, missing, or unclassified imports,
new private facade exports, signature drift, lexical-, expression-, or
statement-owner bypasses, and added or broadened private-usage suppressions
fail the test.

The #816 model extraction removed exactly 120 internal private model edges and
replaced four production private model imports with explicit typed exports.
The #861 language-metadata slice removed another 74 internal private edges,
kept all 60 production imports while reducing their private import edges from
22 to 16, and reduced private-usage suppressions from 17 to 15. Its sole
remaining private constants edge is the frozen facade compatibility alias
assigned to #820. The #862 lexical slice removed another 39 internal private
edges and 21 private owner/consumer pairs, routed the higher-level lexical
consumers through the exact typed facade, kept all 60 production imports while
reducing private production import edges from 16 to 7, and reduced tracked
suppressions from 15 to 12. The #818 expression slice removed 36 internal
private edges and 18 private owner/consumer pairs, replaced three private
production imports without changing the 60-import total, and reduced tracked
suppressions from 12 to 8. It routes higher phases through the exact typed
expression facade while preserving one canonical AST representation and
private recursive parser/emitter mechanics. The #819 statement slice removes
another 29 internal private edges and 10 private owner/consumer pairs, keeps
all 60 production imports and the 4 remaining private production edges, and
reduces tracked private-usage suppressions from 8 to 3. It routes orchestration
and nested function bodies through the exact three-operation statement API and
frozen request/result/control models without changing generated bytes or
mutable state propagation. The baseline is a migration allowlist, not a
public-API declaration for private names. #820 owns the legacy facade shim and
final zero-private-edge assertion. Until that ordered child lands, do not add
an exception or expose an underscore name merely to make the baseline pass.
