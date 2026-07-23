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

The dependency-only typed model layer has three explicit owners:

- `gml_transpiler_parts.shared_models` owns tokens, scope context, static
  declarations, assignment/increment aliases, extension-function metadata, and
  `GMLTranspileError`.
- `gml_transpiler_parts.expression_models` owns every expression AST node and
  the complete `Expression` union.
- `gml_transpiler_parts.result_models` owns preprocessing diagnostics/results,
  source diagnostics/maps, and transpile results.

These modules depend only on the standard library or another model module.
`gml_transpiler_parts.model` is now only the frozen private-alias compatibility
shim consumed by the top-level facade until #820.

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
baseline for #794. It records 209 private imported-name edges across 64
facade/phase module pairs and all 60 production imports from the facade or
phase package. Every entry records its owner and consumer and is classified as
the supported public facade, an intended package-internal phase API, or a
module-private implementation that must move behind its owner.

The same test freezes the 44 supported non-underscore facade exports and their
signatures separately from the 30 underscore-prefixed legacy exports. It also
permits exactly the current 16 phase-package `reportPrivateUsage=false`
directives plus the facade directive. New, missing, or unclassified imports,
new private facade exports, signature drift, and added or broadened
private-usage suppressions fail the test.

The #816 model extraction removed exactly 120 internal private model edges and
replaced four production private model imports with explicit typed exports. The
baseline is a migration allowlist, not a public-API declaration for private
names. #817 owns lexical and language metadata, #818 expression
parsing/lowering/emission, #819 the statement phase, and #820 the legacy facade
shim and final zero-private-edge assertion. Until those ordered children land,
do not add an exception or expose an underscore name merely to make the
baseline pass.

