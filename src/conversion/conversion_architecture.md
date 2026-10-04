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

### Project JSON boundary

The first migrated JSON family is project metadata: `project_manifest` uses
`gamemaker_json` to retain the original GameMaker source text and validate every
decoded value as recursive `json_values.JsonValue`, with typed field access
through `json_fields`. These three leaves depend only on the standard library
and the JSON value leaf; they do not acquire source-containment responsibilities
or import converter/resource owners. Validation preserves raw container identity
and insertion order, rejects unsupported values and ancestor cycles, and walks
deep native values iteratively.

`project_settings` uses the same decoder only to revalidate freshly acquired
options files; it continues to render its cached manifest. The owners retain
their different read/decode exception boundaries and their existing diagnostics.
All GameMaker project/resource acquisition readers now use this shared decoder.
Their owner-local containment, catches and non-object-root handling remain
distinct. Known consumers use typed views or existing models, and `type_defs`
no longer exports unbounded JSON aliases. This boundary preserves the decoder's current
nonfinite number behavior; a finite-only numeric policy is not part of it.

### Path metadata boundary

`path_metadata` is the shared known-field authority for path resources. The
path-registry producer and the path branch of `resource_models` decode through
`gamemaker_json`, then consume the same frozen metadata and retain its raw JSON
container identities. The aggregate derives path counts, closed state and
subfolders from this metadata, while its existing `PathModel` keeps its original
field prefix and adds an optional metadata carrier excluded from repr/equality.
The inherited `ResourceModel.raw_data` now carries a recursive `JsonObject`;
unknown fields remain attached by identity.

The consumers keep separate containment and acquisition policies. The aggregate
still maps its existing read/decode failures to resource diagnostics; the path
registry still rereads current source before producing path outputs. Metadata
retains native numeric values without eager float/int conversion, so aggregate
inspection does not acquire the producer's numeric failures. Registry numeric
construction and coordinate rendering retain their existing ordering, including
nonfinite coordinate failures after a scene is opened and nonfinite speed JSON
serialization. Those numeric policies remain local to the owner rather than
being imposed by the shared JSON boundary.

### Font metadata boundary

`font_metadata` captures the known font fields shared by the font converter and
the font branch of `resource_models`. Both decode through `gamemaker_json` and
retain source JSON identities. The aggregate consumes strict font-name, native
size and parent-path summaries. The converter requests a separate ordered
projection that preserves its required-name string conversions and missing
size default of 12; the aggregate keeps its native-number-only size policy and
default of 0. Its float conversion remains after base/subfolder evaluation and
outside the acquisition catch, including existing huge and nonfinite behavior.
The replaced raw font branch and its unused `_float_value` helper are removed;
the other generic resource branches retain their existing projections.

`FontModel` keeps its original module, inheritance, field prefix, repr and
equality, with an optional metadata carrier excluded from repr/equality.
Dataclass reflection intentionally includes the new carrier and its private
primitive presence/value records; missing-field sentinels are transient rather
than stored Enum values. The owners retain their different exception policies
and source-acquisition seams. Font output fallback rereads current parent
metadata while registry-planned destinations retain precedence. Registry font
planning now consumes separate bundle and system-name captures at the original
callback stages: parent-folder discovery runs before bundle capture, and a
failed bundle resolution precedes system-name capture. The typed registry input
retains raw identity without applying the converter's required-field coercions.

### Sound metadata boundary

`sound_metadata` captures known sound inputs and preserves the decoded JSON root
and unknown values. The aggregate consumes only strict native-string summaries
for soundFile, audioGroupId.name and parent.path; it never requests the ordered
converter projection or applies converter defaults/coercions. Its existing
read/decode failure catch still produces the same missing-resource warning,
while metadata, subfolder and model construction remain outside that catch.
The sound converter retains its separate acquisition and projection catches,
including source-file rejection before conversion and delayed audio-group errors.

`SoundModel` retains its original ten-field prefix, module, inheritance, defaults,
repr and equality, with an optional metadata suffix excluded from repr/equality.
Dataclass reflection intentionally includes that suffix and the leaf's primitive
presence/value capture. The separate sound decoder alias is the same shared
function, preserving the path and font patch seams. Registry sound planning
consumes separate file, audio-group and metadata projections with its original
forgiving numeric defaults. File capture precedes source resolution; group
capture follows that callback and precedes fresh folder discovery.

### Tileset metadata boundary

`tileset_metadata` captures known tileset inputs for the primary declaration
converter and the tileset branch of `resource_models`, retaining decoded JSON
identities. The aggregate consumes only strict sprite-name, native-int dimension
and parent-path summaries; it neither resolves sprite references nor requests
the converter's ordered projection. Its tileset decoder alias is the same shared
function, with the other family aliases unchanged. The existing acquisition
catch and missing-resource warning remain, while capture, subfolder and model
construction stay outside that catch.

`TileSetModel` keeps its original eleven-field prefix, module, defaults, repr and
equality, adding an optional metadata carrier excluded from repr/equality.
Reflection includes that carrier and its primitive presence/value captures.
The converter retains reference validation before numeric capture so rejection
callbacks can affect later values, and preserves its ordered conversions and
late rendering failures. Its nested sprite reader now uses the shared decoder,
captures each atlas frame before owner reference validation, and selects layers
after that validation. The room layout projection retains conditional tile-count
access after column conversion. Tileset declarations use typed per-entry
resource-reference captures, leaving containment and rejection with the owner.

### Sprite, object and reference acquisition models

`sprite_metadata` and `object_metadata` provide frozen known-field views consumed
by both converters and the aggregate model layer. `SpriteModel` and `ObjectModel`
retain their old field prefixes and add optional metadata carriers excluded from
repr/equality. Aggregate base and parent-folder evaluation precedes these views;
summary fields retain their native-type policies. Sprite collision, animation,
frame/layer and object event/reference projections retain their distinct owner
conversion and failure stages.

`resource_reference_metadata` captures registry declarations, sprite declarations
and object asset names at their existing per-entry discovery seams. It leaves
source containment, fallback naming and manifest rejection with those owners.
Unknown raw fields retain recursive JSON types and container identity. Object
events retain their existing copied sanitation step and scalar mapping keys;
animation-curve and extension registries narrow their existing public models
rather than adding parallel representations.

Source discovery, generic aggregate resources, room layers, curves, extensions,
object reads and tileset atlas reads share the decoder without merging their
catch policies. Aggregate family decoder aliases remain separate patch seams
for the same underlying function. Nested room, sequence, timeline, particle and
registry output consumers now retain recursive JSON types throughout. The
unbounded `type_defs` JSON aliases and their redundant transport casts are removed.

### Shared resource reader and parent metadata

`BaseConverter._read_yy_file` retains its owner-local containment refresh and
UTF-8 read, then uses `gamemaker_json` to validate the decoded graph. It returns
the original `JsonObject` or its existing `None` failure result. The current GameMaker decoding dialect
continues to accept nonfinite floats, separately from standard JSON compliance.

`resource_parent_metadata` captures the optional parent path without acquiring
files, validating an override's whole graph or coercing values. The inherited
folder helper keeps virtual reader dispatch, fresh source reads, string-subclass
behavior, formatting order and its existing exception boundaries. A captured
`has_parent_path` flag distinguishes missing or malformed paths from a valid
empty string, preserving the original string-method and early-return boundaries. Unknown raw
metadata stays attached by identity.

### Nested room and authored asset views

`room_metadata` keeps room-index capture after the creation-code callback and
preserves malformed truthy settings/layers as `JsonValue` until their original
use point. Inheritance remains an owner-managed copy/merge. Renderer fields are
live reads after name allocation, warnings and reference callbacks. Strict
aggregate summaries use settings capture, lazy preorder layer fields and then
room-summary projection; they do not borrow the renderer or registry defaults.

`sequence_metadata`, `particle_metadata` and `timeline_metadata` define precise
records consumed by normalization, registry planning and rendering. Aggregate
track/moment counts retain their strict list-of-object policy. Timeline aliases,
action precedence and callback ordering remain with their existing owners.
Sequence and particle numeric exception policies remain distinct.

Generated reports and Deep host snapshots return recursive `JsonObject` and
`JsonArray` values with their existing formats, ordering and finiteness policies.
GameMaker managed-output reconciliation has an explicitly typed JSON route;
the separate general mapping API keeps its broader non-GameMaker contract.
These leaves depend on standard-library and JSON primitives, keeping resource
acquisition, source containment and side effects in the existing owners.

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
The #820 facade cleanup removed the frozen private-alias compatibility path
from the top-level facade. Canonical shared, expression, statement, and result
models remain package-internal under their explicit owner modules.

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

### Enforced transpiler boundary

`tests/test_gml_transpiler_architecture.py` is the machine-checked zero-violation
boundary for #794. It records zero private imported-name edges and zero private
owner/consumer pairs across the facade, phase package, production consumers,
and tests. Each edge must use either the supported public facade or an explicit
package-internal non-underscore phase, model, language-metadata, or utility API;
the contract deliberately does not freeze an inventory of benign public callers.

The same test freezes the complete static top-level facade at the exact 44
supported non-underscore exports and their signatures. There are no private
facade exports and no file-level `reportPrivateUsage=false` directives in the
facade or production phase package. The gate rejects underscore imports in
absolute, relative, aliased, and parenthesized forms; private or dynamic
facade `__all__`; signature drift; phase-owner bypasses; production imports
from designated test-support modules; and any added private-usage suppression.
The runtime phase tests continue to prove immutable metadata containers, resolved
annotations, canonical model identities, exact callable signatures, and frozen
model fields. Only `tests.gml_facade_contract_support` may import the exact eight
language, phase API, and model module objects needed to return these runtime
facts; it exposes a frozen contract record rather than module objects. The
architecture test alone retains its facade module-object exception for the exact
44-name identity and signature contract. The lexical, expression, and statement
owner gates remain explicit, including all four statement gateway edges in both
orchestration modules and the sole deferred import inside function-literal parsing.

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
private recursive parser/emitter mechanics. The #819 statement slice removed
another 29 internal private edges and 10 private owner/consumer pairs, keeps
all 60 production imports and the 4 remaining private production edges, and
reduces tracked private-usage suppressions from 8 to 3. It routes orchestration
and nested function bodies through the exact three-operation statement API and
frozen request/result/control models without changing generated bytes or
mutable state propagation. The #820 facade cleanup removed the final 31 tracked
internal facade/phase private imported-name edges and 4 such owner/consumer
pairs, migrated the remaining production consumers to explicit non-underscore
owners, and removed seven related file-level private-usage suppressions: the
final 3 tracked facade/phase directives plus 4 now-obsolete consumer/test
directives. It also removed all 30 legacy underscore-prefixed facade exports—the
28 imported aliases and 2 local tokenizer wrappers—while preserving the exact 44
supported public exports, their order, identities, and callable signatures. The
former staged allowlist is now the zero-violation gate above; do not add an
exception or expose an underscore name merely to bypass it.
