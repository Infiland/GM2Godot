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

The GML transpiler has three explicit phase families:

- Parser phase: `gml_transpiler_parts.tokens`,
  `gml_transpiler_parts.expression_parser`, `statement_parser`, and `model`
  turn source text into typed token and AST structures.
- Semantic analysis phase: `preprocessor`, `gml_function_dispatch`,
  `gml_api_manifest`, `extension_functions`, and `asset_lowering` resolve
  configuration, API support, arity, extension mappings, and asset-argument
  lowering rules.
- GDScript emission phase: `emitter`, `expression_service`, and `api` render
  validated AST or statement output to GDScript and source-map metadata.

Asset-specific lowering metadata lives in `asset_lowering` so the generic
expression emitter does not own the GameMaker API argument tables.

