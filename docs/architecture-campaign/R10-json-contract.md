# R10 accepted recursive JSON contract

Task/issue: R10 / #797. Root accepted this contract after independent and actual-code review on 2026-09-05. Implementation starts from f87aa69, the reviewed C01/R01/D01 integration candidate. D01 is frozen and locally verified; merge order remains C01, D01, then R10. Owner: audit_gml_resources in GM2Godot-080-json on dev/080-recursive-json. Independent reviewer: audit_transactions_cli, followed by root.

## Problem, owners and measurable outcome

Four shared GameMaker readers duplicate UTF-8 reading, identical trailing-comma substitution and json.loads. JsonDict imports cover 30 production modules plus 5 tests; JsonList covers 6 production modules; JsonValue covers room_layers. These include report serializers, dynamic keyword dictionaries and event APIs, so replacing the three Any aliases globally would force unreviewed family migrations.

The source cycle is project_manifest -> project_source_paths -> project_manifest (the reverse edges are one type-checking import and the local manifest load inside GML discovery). Keep D01's diagnostic_models.ProjectSourceLocation as the sole location record. Keep ProjectResourceReference in project_manifest through R10; its project-family ownership is R11's decision. ResolvedProjectSourcePath remains in the resolver. A second source metadata leaf is unnecessary.

R10 outcome: one validated decoder shared by all four current shared readers; canonical recursive values actually returned by the new loader and consumed throughout extracted discovery; path resolver no longer imports manifest, JSON parsing or event mapping; three explicitly transitional legacy-return adapters remain. This is not completion of #797, not removal of legacy Any aliases, and not authoritative family modeling.

## Proposed exact boundary APIs

New src/conversion/json_values.py is a stdlib-only value/validation leaf:

- JsonScalar = str | int | float | bool | None.
- JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]; JsonObject and JsonArray name those concrete containers.
- JsonFieldPath = tuple[str | int, ...].
- validate_json_value(value: object, *, field_path: JsonFieldPath = ()) -> JsonValue. Check every nested container/key/value, reject non-string object keys and non-JSON native objects with JsonValueError, detect cycles for this callable native-object entry point, and return the same tree without coercion/copying/reordering. A single cast after complete validation may live here; no broad downstream casts. Use a bounded iterative walk so validation adds no recursion-depth limit to json.loads. Explicit helpers may separate object, array and scalar validation if needed to meet budgets.
- JsonValueError(ValueError) carries the exact typed field path and expected/actual type descriptions. It is a boundary exception, not a new diagnostic collector/model/code registry.
- format_json_field_path(path: JsonFieldPath) -> str: empty path '$'; identifier keys joined by dots, indexes by [n], nonidentifier keys by JSON-quoted brackets. Thus resources[0].id.path and ["a.b"][2] are unambiguous. It reports structure location only; do not invent source line/column from a reserialized tree.

New src/conversion/gamemaker_json.py owns source text and file I/O:

- Frozen GameMakerJsonDocument(source_path: str, source: str, value: JsonValue). JSON null remains a successful document with value None; read/parse failure is an exception, never confused with null.
- parse_gamemaker_json(source: str, *, source_path: str = '') -> GameMakerJsonDocument: apply the existing exact re.sub(r',\s*([}\]])', r'\1', source) semantics, decode with stdlib json.loads into object, then validate_json_value. Retain the original source, not cleaned text, for existing line behavior.
- read_gamemaker_json(path: StrPath) -> GameMakerJsonDocument: UTF-8 open/read and delegation to parse_gamemaker_json. It neither selects nor confines paths; the current caller must perform its existing resolution before open. No caching, traversal, diagnostics emission, logging, writer ownership, cancellation or process lifecycle here.
- Preserve native OSError/UnicodeError/JSONDecodeError/RecursionError behavior until existing callers apply their established exception policy. Do not introduce a depth cap, strict finite-number policy or duplicate-key policy in R10.

No field-default/coercion framework or speculative accessor family is added. Family parsers later use membership to distinguish missing from null and raise/translate field-path errors according to that family's characterized policy. Existing diagnostics continue through D01 records with their exact current code/message/severity/path/line/field strings; R10 adds no new emitted diagnostics for old inputs.

## Exact implementation/migration tasks and dependency direction

1. Add the two boundary modules and characterization tests before routing existing loads through them.
2. Adapt BaseConverter._read_yy_file, project_manifest._read_lenient_json_file and resource_models._read_lenient_json_file to the canonical document/value internally, retaining their current legacy JsonDict return annotations and exact failure behavior. These three existing functions are explicit temporary legacy-return adapters; do not add a redundant as_legacy wrapper. Retain their direct type_defs annotations so remaining legacy use is visible. No new unvalidated Any input/return in json_values, gamemaker_json or discovery.
3. Remove project_source_paths._read_lenient_json_file; discovery uses read_gamemaker_json and canonical JsonObject/JsonArray directly with the current object-root acceptance and caught exception set. Preserve event mapping behavior and order; no E01 event-model migration here.
4. Move exactly _GML_RESOURCE_KINDS and these eight functions into new project_source_discovery.py: project_gml_source_paths, _resource_gml_candidates, _script_gml_candidate, _object_gml_candidates, _first_existing_event_candidate, _event_source_filenames, _room_gml_candidates, _iter_room_instances. Move only their imports; keep all path resolution and ResolvedProjectSourcePath in project_source_paths. Remove its manifest type-checking import, local manifest load, event imports and JSON imports.
5. Migrate discovery imports in objects.py, project_enums.py, project_macros.py and tests/test_project_source_paths.py. In objects.py also replace exactly the two duplicated regex/json.loads pairs in _get_project_asset_names and _parse_object_yy with `data = cast(JsonDict, parse_gamemaker_json(content).value)`. Retain their existing open/resolution code, surrounding exception lists and unconditional legacy casts. This removes actual duplicate decoding to offset the necessary new imports; it does not migrate object fields/models. No old-owner discovery re-export, lazy forwarding wrapper or new resolver protocol. The manifest alone owns ProjectResourceReference; discovery imports it and load_gamemaker_project_manifest directly.
6. Document the staged legacy adapters/consumer inventory and add the exact R10 required test selection. Update only real maintainability reductions; no allowance, threshold or exclusion increase.

DAG: discovery -> manifest -> source_paths; discovery -> source_paths, gamemaker_json, existing event APIs; manifest/base_converter/resource_models -> gamemaker_json; gamemaker_json -> json_values and existing StrPath alias; diagnostic records -> D01 diagnostic_models. None of source_paths/json_values/gamemaker_json imports discovery or manifest. Preserve current ProjectSourceLocation identity/import contract from D01.

## Direct readers/callers and deferred families

- BaseConverter._read_yy_file: 11 production call sites across base_converter (subfolder lookup), shaders, resource_index (2), sounds, asset_registry (2), sprites (3), objects. They keep the existing method contract; their parsing/model logic is untouched.
- Manifest reader: load_gamemaker_project_manifest and _parse_project_options.
- Descriptive resource-model reader: _parse_resource_model. Its aggregate parser still has zero production callers and only tests/test_conversion_architecture; routing its reader is consistency, not claiming production family migration.
- Discovery reader: project_gml_source_paths, reached by ObjectConverter._get_project_script_instance_variables, project_enums.collect_project_enum_values and project_macros.collect_project_macro_values.
- The two direct object decoding sites join R10's shared boundary with their existing explicit legacy casts; R19 still owns authoritative object modeling and removal of those casts. The remaining 8 direct GameMaker decoding sites are deliberately deferred: project_settings (R11), path_registry (R12), fonts (R13), tilesets' two sites (R18), room_layers (R20), animation_curve_registry (R23), extension_registry (R24). Do not conflate project_godot string unquoting or GML extension-function mapping JSON with GameMaker resource metadata decoding.
- R11–R25 each establish their single authoritative family parser/model, migrate actual consumers, delete the corresponding descriptive class/duplicate parsing and preserve unknown extras. Shared events/report-schema consumers remain E01/other named rows plus R26.

## Compatibility characterization and proof

Fresh planning probe covers 10 inputs across all four current readers (r10-planning-loader-characterization.json). Required unchanged facts: trailing commas accepted; regex also currently changes quoted ', }' text into '}'; duplicate keys last-win; nested unknown fields/null/bools preserved; NaN and +/-Infinity accepted; top-level null/array/scalar rejected by object-reader adapters; manifest returns (None, original_source) for valid nonobject JSON but (None, '') for malformed/BOM inputs. Preserve these in R10; a string-aware normalizer or strict-number hardening would be separate behavior work.

Expand characterization with empty/missing/wrong-type values at nested paths, empty keys and keys containing dots/brackets/quotes, malformed UTF-8, deep objects/arrays around the existing decoder recursion boundary, native non-string keys/set/bytes/tuple/cyclic input rejection, and unknown data/order/identity retention. Ensure None represents JSON null only inside a successful document; no defaulting, field deletion or original-source line changes.

Characterize both object call sites separately: valid nonobject roots currently raise uncaught AttributeError when `.get` executes; preserve this by retaining the existing cast, rather than substituting an object-only reader returning None. JSONDecodeError and UnicodeDecodeError follow the existing caught fallback/logging paths; decoder RecursionError continues to propagate. Keep all source-path tests for traversal, drive paths, symlinked roots/sidecars, cross-family target rejection, discovered backslashes, orphan exclusion, duplicate realpath exclusion, event fallback order and room nested-layer/instance ownership. Verify containment still precedes file access. Reuse D01 source-location records and preserve every pre-existing diagnostic field.

Required test modules: new tests.test_json_values and tests.test_gamemaker_json; tests.test_base_converter, tests.test_project_manifest, tests.test_project_source_paths, tests.test_conversion_architecture, tests.test_project_enums, tests.test_project_macros, tests.test_objects, tests.test_scripts, tests.test_script_generator, tests.test_lts_2026_conversion, tests.test_simple_topdown_conversion. Exact IDs/zero-skip requirements go in architecture-verification.json R10 before implementation completion. Native Pyright 0/0, Ruff, focused after fixes, full unittest with approved Godot/all three pinned fixtures, final maintainability and diff checks. Compare immutable task base/candidate using the existing five-fixture, same-destination 14-field parity contract plus same-ref control. Preserve the 44-export GML contract. Run relevant native source/path checks on Linux/Windows when affected; modeled path behavior on macOS is not native proof.

Performance: freeze exact sorted .yyp/.yy input inventory, file SHA256, counts/total bytes and per-fixture counts for the five existing parity fixtures. Compare (a) read/decode corpus and (b) load_manifest plus project_gml_source_paths on identical inputs, isolated native processes, same warm-cache policy, 5 samples of 3 complete passes. Record all samples, median, standard deviation and platform-native peak RSS bytes. No forced OS cache flushing or parallel benchmark workloads. Investigate a reproducible material regression before approval; do not trade away validation or claim overall conversion speed from this scoped benchmark. Reuse immutable complete-conversion parity for real behavior.

## Budgets, allowed files and completion

Current integration physical/structural units: base_converter 419/549; manifest 1108/2013 (frozen D01 1091/1992); source_paths 574/892; resource_models 615/1059 (D01 604/1047). The discovery functions alone are 219 physical/394 structural units; retained resolver class/function bodies are 265/426. Final counter vocabulary is the accepted R02 implementation, including expressions and multiline literals.

In-memory exact import/decode AST preflight (no source edits): objects 1914 physical / 3002 structural -> 1913 / 2994 including both new imports and two genuine decoder removals; project_enums 193 / 344 unchanged; project_macros 97 / 155 unchanged; tests/test_project_source_paths 585 / 902 -> 585 / 903, under its 1500 budget. Receipt: r10-in-memory-import-preflight.json. This proves the proposed ownership resolution has headroom; the complete final R02 gate still runs on the implemented revision.

Destination budgets (both physical and structural): json_values <=500; gamemaker_json <=200; discovery <=650; source_paths <=600; new functions <=15 complexity, <=150 physical and structural units, nesting<=4, parameters<=8. New tests <=1500 module and <=200 function physical/structural units. Existing manifest/resource_models debt must not grow and R10 claims only actual loader/import/cycle reduction; their family split is deferred. No threshold, allowance, exception or suppression additions.

Exact allowed files to add to the current R10 row: src/conversion/json_values.py; src/conversion/gamemaker_json.py (new additional owner); src/conversion/project_source_discovery.py; src/conversion/type_defs.py (staging documentation only); src/conversion/base_converter.py; src/conversion/project_manifest.py; src/conversion/project_source_paths.py; src/conversion/resource_models.py; src/conversion/objects.py (discovery/decoder imports and exactly two decoder-pair replacements only); project_enums.py, project_macros.py (discovery imports only); tests/test_json_values.py; tests/test_gamemaker_json.py; existing focused tests/test_base_converter.py, test_project_manifest.py, test_project_source_paths.py, test_conversion_architecture.py, test_objects.py (two loader-policy characterizations); architecture-verification.json; maintainability-baseline.json; scoped architecture documentation/contract records owned or approved by root. No D01 model edits, resource-family parsing edits, events API changes, version/release changes or CI redesign.

Temporary adapter removal: the two existing object casts retire with R19's authoritative object parser. Manifest's legacy loader disappears or becomes fully canonical in R11; BaseConverter._read_yy_file and resource_models' legacy loader are removed after their final actual family caller migrates, no later than R26. R26 removes the three Any aliases from type_defs and retires their remaining report/event/raw consumers to canonical JSON or existing specific models, deletes any remaining descriptive resource_models surface only after consumers are gone, removes D01's separately recorded compatibility exports, and enforces an exact no-legacy-import/no-duplicate-GameMaker-decoder assertion. R10 completion explicitly permits only these inventoried legacy returns and two object casts; amend its current generic 'remove before this task verified' wording rather than falsely claiming them eliminated.

One isolated R10 implementer; separate semantic reviewer and root actual-code approval. Root must accept this finite boundary/API/adapter/file inventory before edits. Completion requires canonical boundary used in production discovery and all four shared decoder paths plus the two object decoding sites, old duplicate decoder bodies removed, source_paths->manifest edge absent, matched characterization/parity/performance and native checks passing, exact reviewed revision integrated. R10 does not mark later family rows or #797 complete.

## Root acceptance refinements

- Detect cycles using active ancestors; shared acyclic containers remain valid.
- A non-string dictionary key is reported at its containing typed path with the
  actual key and type. Do not convert integer dictionary keys into array indexes.
- Preserve discovery's exception boundary around reading/decoding only. Existing
  event mapping errors must propagate as before.
- The single canonical validator cast follows complete runtime validation. No
  other new broad casts or suppressions are authorized in canonical modules.
- The three existing legacy-return adapters and two existing object casts are
  explicit staged exceptions only; their named R11/R19/R26 deletion conditions
  remain mandatory. R10 cannot claim all converters are free of Any.
- Allowed documentation owner for the implementer is this contract. Root owns
  the ledger and contracts.json. Other architecture documentation requires a
  named, bounded approval before editing.
- N01 owns the shared verification-manifest schema first. R10 records its exact
  required method inventory in external evidence and runs the direct selection;
  root adds that inventory to architecture-verification.json as a serialized
  integration edit after N01. The implementer does not edit that shared manifest.

## Implemented boundary and measured tradeoff

The isolated source base is 4a60e46. The new value, decoder and discovery owners
measure 95/216, 32/41 and 262/407 physical/structural units respectively. The
retained resolver measures 320/458. The validator's 36/117 units and nesting 4
meet the accepted limits. The strict ratchet records only actual reductions,
including removal of the manifest/resolver cycle; no allowances were added.

Canonical discovery consumes recursive values directly. The three legacy-return
readers remain visible in their existing owners, and only the two pre-existing
R19 object casts remain at the migrated object decoding sites. The legacy aliases
are intentionally unchanged; their R11/R19/R26 removal conditions above apply.

The frozen performance corpus contains 201 metadata files totaling 174,499 bytes
from the five parity fixtures. Five isolated native process samples, each with
three complete passes after one warm-up, measured read/decode medians of 14.819 ms
before and 18.921 ms after (standard deviations 0.284/0.345 ms). The added complete
recursive validation costs 1.37 ms per corpus pass. Manifest loading plus GML
discovery measured 196.337/197.153 ms (standard deviations 3.080/0.941 ms), within
the observed variance. Peak RSS stayed within 0.10 MB for both workloads. This
measures those scoped operations, not overall conversion speed. Root accepted
the measured validation cost; no caching or weaker validation was introduced.

External R10 evidence retains input/file hashes, every timing sample, source and
harness hashes, native peak RSS, the bounded cost profile, and pre-refactor loader
characterizations. Correctness tests cover quoted-comma behavior, source retention,
unknown/null/nonfinite values, malformed UTF-8, native decoder recursion errors,
active cycles versus shared containers, exact key paths and the discovery event
exception boundary. Immutable complete-conversion parity and native full-suite
receipts remain separate completion proofs.
