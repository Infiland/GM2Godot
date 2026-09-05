# R12 accepted path-model implementation contract

Root ACCEPTS this finite contract and assigns implementation from fully verified R11
merge `1196295179296dfc12274ff39ba79e6adfb4a1b2` (PR #885). Exact final PR and merge
CI, native receipts and actual-parent proof passed. All thirty refreshed source inputs
match this checkout. The final proposal, accepted addendum and actual entry refresh
below are authoritative together; this assignment supersedes their historical proposed
status. No additional API, malformed-input domain or file scope is implied.

Sole implementer: `audit_gml_resources`, isolated worktree
`/Users/infi/Documents/Github/GM2Godot-080-path-model`, branch `dev/080-path-model`.
Independent actual-code reviewer: `audit_policy_tests_docs`, then root. Six owner files:
new path_model.py, path_registry.py, resource_models.py under src/conversion;
new test_path_model.py and test_path_model_consumers.py, existing test_path_registry.py
under tests. Root alone writes maintainability-baseline.json and shared coverage,
verification and campaign metadata. Preserve canonical project identity from R11.
No commit, push or PR before independent and root actual-code approval/instruction.

Characterize the actual parent before production edits. The complete five-numeric-field
aggregate API retirement and issue #882 non-object registry ValueError are accepted;
all other output, exception timing, source containment and publication behavior remains
binding. Actual source sizes are registry206/394 and aggregate582/989; corrected import
projections are178/323 and580/984, model71/109. Use actual final imports with new leaves
present. No new debt, suppression, assertion weakening or budget increase is authorized.

Use approved native Python3.12.10 and exact Godot4.7.2 official ed1daf0bf. Freeze source
for proof. Root reserves CPU windows before full, runtime, parity or benchmarking;
T01 correction has the next timing/full window. Before-source finite characterization
and light source/type/unit work may proceed, coordinated with root. Full proof uses all
five immutable fixtures; all required runtime/native evidence and exact PR/merge CI
remain completion criteria. One final v0.8.0 release, no per-slice publication.

# R12 finite path-resource contract proposal

Status: refined final read-only proposal. Root accepted the explicit API/bug scopes in final/R12-final-contract-addendum.md; corrected independent/root final review and actual R11 integration remain prerequisites. No implementation, issue publication, commit or repository edit is authorized. Current Python source is approved R04 ef758360d91e96f2df0a72fc17769e7e5ed77c09. R04 cleanup and the independently approved R11 proposal precede implementation. Freeze the actual integrated R11 parent, compare source hashes, and refresh every metric before acceptance; the R11 deletion projection is not an integrated revision.

The initial R12 row requires one authoritative paths parser/model and retirement of renderer dictionary parsing and the descriptive PathModel. The finite proposal below accomplishes that with one small canonical leaf, two existing production consumers and bounded tests. It does not migrate another family or introduce a new framework or compatibility adapter.

## Accepted API and bug scopes

Root accepted the exact canonical PathModel aggregate shape below, including retirement of the descriptive metadata fields and the changed kind/constructor/serialization/module surface. Root also accepted stable asset-field values and the changed name/id read timing, with no effectful-property promise. The complete eager numeric conversion/error domain covers x, y, speed, kind and precision; its errors now occur during aggregate construction as an architectural API tradeoff.

[Issue #882](https://github.com/Infiland/GM2Godot/issues/882) owns the deliberate ValueError for non-object registry rereads, preserving null skips, caller-specific catches, source containment and aggregate diagnostics. It is distinct from the numeric API tradeoff. No legacy-error adapter or behavior change outside these accepted domains is authorized.

The normative final addendum records the exact matrix and expanded executed evidence: 404 numeric outcomes (382 identical and 22 accepted aggregate error changes), plus 14 root/publication cases. The original 88 outcomes and 15 artifacts are retained as historical evidence. They are no longer a literal seven-example limit on the accepted domain. No repository implementation or passing future integration receipt is claimed.

## Actual production path and ownership

| Stage | Actual owner and operation | R12 action |
|---|---|---|
| Discovery/order | AssetRegistryConverter._resources_from_yyp and _resources_from_disk resolve/validate sources, use BaseConverter._read_yy_file, preserve manifest/disk order and existing deduplication. | No edit. R10's project_source_discovery is for GML scripts/objects/rooms, not this paths traversal. |
| Asset identity | AssetRegistryConverter._build_entries_from_resources assigns stable ids, names, generated paths and resource metadata. | No edit or reassignment. |
| Path acquisition | build_path_registry_entries iterates the provided iterable once, filters exact kind == paths, independently resolves each source and rereads it. | Keep this timing and source guard. Use the existing R10 reader under the same caller-specific OSError/JSONDecodeError catch. |
| Canonical interpretation | New path_model.parse_path_model receives an already validated JsonObject plus caller-selected name/source_path. | One pure parser creates canonical typed points/flags/kind/precision and retains the same raw object. |
| Output projection | path_registry creates the existing seven-field PathRegistryEntry from the canonical model plus asset id/godot_path. | Replace _path_entry_from_yy with _path_entry_from_model; no raw-field interpretation in the output projection. |
| Publication | write_path_registry builds all entries, writes scenes in entry order, then creates/writes the registry. AssetRegistryConverter calls it after group reports and before animation/extension/final registry output. | Keep order, text mode, errors and caller accounting unchanged. |
| Aggregate metadata | parse_gamemaker_resource_models traverses manifest references; its source resolver also validates resource-kind paths and collects diagnostics. | Route only the paths branch to the same pure parser; keep all other family branches byte/AST-equivalent except the single reader's stronger return annotation. |
| Runtime | 47_paths_motion_planning.gd loads/normalizes registry entries and script_generator invokes path stepping. | No runtime/generated template change. |

The two acquisition policies remain distinct. The aggregate reader already calls R10 and catches OSError, JSONDecodeError, TypeError and ValueError, filters object roots and emits GM2GD-RESOURCE-YY-MISSING through its caller. Keep that helper and strengthen only its return annotation from legacy JsonDict to JsonObject. The registry reader catches only OSError and JSONDecodeError; UnicodeDecodeError, integer digit-limit ValueError and RecursionError propagate. Retiring its duplicate json.loads/trailing-comma implementation must not broaden its catch or normalize paths differently.

Both readers continue to read at their current times. No cache, parse-once discovery handoff, new metadata context, operation cancellation policy or I/O ownership transfer is introduced. The canonical model has no os/pathlib/importlib, filesystem, resolver, loader, converter, renderer or writer dependency. Its only nonstdlib dependency is json_values. Path registry and resource_models import it; it imports neither consumer, project_manifest nor future project_model. This avoids competing R11 ownership and all model-to-loader cycles.

## Exact canonical symbols and API

New src/conversion/path_model.py owns:

- Frozen PathPoint with unchanged x: float, y: float, speed: float = 100.0 fields, constructor order and to_godot_dict key order x/y/speed. Strengthen that result to JsonObject. path_registry retains one explicit identity-preserving PathPoint import so its existing public constructor/import still works; there is no second definition, wrapper or module/pickle shim. Its canonical __module__ change is characterized.
- Frozen PathModel with required name: str, source_path: str, raw_data: JsonObject, points: tuple[PathPoint, ...], closed: bool, kind: int, precision: int, in that order. point_count returns len(points). Raw-object identity, insertion order and unknown nested values remain; the model is shallowly frozen, with no constructor validation, copy or deep freeze. Its parsed fields are a snapshot and do not rebuild after raw_data mutation.
- parse_path_model(data: JsonObject, *, name: str, source_path: str) -> PathModel, _path_points(value: JsonValue) -> tuple[PathPoint, ...], and the moved finite _number(value: JsonValue, default: float) -> float. These do no I/O or logging. The caller-selected name wins over raw name/%Name, exactly as the writer currently does.

Keep PathRegistryEntry, its seven constructor fields/order/default behavior, render_path_registry_script, render_path_scene, write_path_registry, build_path_registry_entries, constants and _PathAssetEntry protocol in path_registry. Their signatures remain. The DTO has output identity and godot_path absent from the source model; it is not a second raw parser or a legacy model adapter. It shares the model's point tuple. Delete path_registry's PathPoint definition, _path_entry_from_yy, _read_json_lenient, _strip_trailing_commas and _number definitions, three narrowing casts and the legacy JsonDict import. Replace only the acquisition helper with _read_path_document and the typed output mapper with _path_entry_from_model.

Delete resource_models' original PathModel subclass and paths-only len(_dict_list(...))/bool interpretation. Its paths tuple/list/factory and add/parse return annotations use the canonical model directly, with ResourceModel | PathModel where needed. Its imported name is that same canonical class, not a compatibility implementation; the old class shape is explicitly retired. Existing other-family raw helpers/casts remain owned by their named later family tasks/R26. Do not claim this slice removes all legacy JSON aliases or all duplicate source acquisition.

## Supported values and exact ordering

| Input / event | Preserved behavior |
|---|---|
| Missing, non-list or null points | Empty tuple. |
| Points list containing non-dicts | Filter those elements; preserve the order and duplicates of dictionary points. Empty dictionaries become a default point. |
| x/y/speed | bool -> float(int(value)); int/float -> float(value); everything else uses 0/0/100. Numeric strings are not parsed. Evaluate x, then y, then speed for each point before closed/kind/precision. |
| closed | Ordinary bool(value), including truthy nonempty string "false". |
| kind / precision | int(_number(value, 0/4)); bool conversion and truncation toward zero remain. No clamping, rounding, smoothing or finite-number filter. |
| Unknown fields | Retained in the canonical raw object; ignored by geometry/output as before. R10's existing regex quirk also rewrites comma-before-bracket text inside JSON strings. Do not fix it in R12. |
| NaN/Infinity | Preserve existing JSON permissiveness and exact later float/int formatting exceptions; only the explicitly accepted earlier aggregate error scope changes. |
| Iterables and names | Consume once in supplied order, no new sort/deduplication. Preserve duplicate ids/names and exact kind case sensitivity. |
| Generated geometry | Four zero tangent coordinates plus x/y per point, zero tilts, original point_count, closed/kind/precision/speed metadata. Do not append the closing point or implement curved interpolation. |
| Scene number formatting | Existing six decimal places/trim behavior, integer formatting and negative zero output remain. |
| Native bytes | Rendered strings and json.dumps argument/default/key order remain; ordinary UTF-8 text writers retain per-host newline translation. Never normalize CRLF/LF for parity. |

## Resource and lifecycle boundaries

Source resolution remains before read and all entries are built before any output open. A build/parse failure produces no new path outputs. Each scene writer creates its parent then opens/truncates the scene before rendering/writing; a later scene failure may leave earlier scenes and an opened empty scene. Registry open/write occurs last and can fail after scenes exist. Preserve this existing behavior within the surrounding conversion transaction; do not introduce a path-specific atomic publisher, compensation, retry, no-follow guarantee or changed cleanup. Empty/non-res:// godot_path still suppresses the individual scene while its registry entry remains. Source/root guards and generated output-path authority remain at their existing owners.

The existing Windows auxiliary readonly test covers groups/timelines, not this path writer. Do not cite it, N01 receipt tests or a mocked race as new path native safety proof. The existing contained-source symlink test is real but may skip when links are unavailable; applicable skips remain missing host evidence.

## Exactly seven implementer paths

1. src/conversion/path_model.py (new), exact symbols above.
2. src/conversion/path_registry.py, model/reader migration and duplicate deletion only.
3. src/conversion/resource_models.py, paths class/branch/union migration and the existing reader's JsonObject return annotation only.
4. tests/test_path_model.py (new), pure model/parse characterization.
5. tests/test_path_model_consumers.py (new), aggregate/registry/shared-reader identity and behavior proofs.
6. tests/test_path_registry.py, keep three existing IDs and add the finite writer/order/byte cases below.
7. maintainability-baseline.json, actual nonincreasing debt/evidence update against the accepted immutable parent only.

No existing Godot test, runtime template, asset registry, base converter, manifest/project model, R10 decoder, fixture, workflow, dependency or release file is edited by this owner. Reuse committed resource_matrix and temporary finite inputs. Root owns campaign docs, the exact required-ID/cohort integration and coverage-policy ownership: path_model must join actual project-parsing ownership without removing existing paths or changing floors/baselines. Current overall-production already includes it. Root serializes those shared changes after code/schema freeze.

## Measured bounds and remaining prerequisite

| Owner | R04 current physical / structural | Contract-derived R11 parent | R12 external preview |
|---|---:|---:|---:|
| path_registry.py | 206 / 394 | 206 / 394 | 179 / 323 |
| resource_models.py | 605 / 1035 | 586 / 989 | 585 / 984 |
| path_model.py | absent | absent | 71 / 109 |
| resource_models._parse_resource_model | 135 / 265 | 135 / 265 | 135 / 261 |
| tests/test_path_registry.py | 134 / 266 | unchanged | Tests not implemented. |

The registry renderer/writer bodies are unchanged in the projection. _path_points is 12 physical/35 structural, nesting2; parse_path_model is 16/27 after removing unused source-text storage. No original text storage is added: the existing raw values and contained source path are the canonical model input. The R11 resource_models preview removes only its approved ProjectModel/_project_model and binds aggregate.project to its manifest; it deliberately does not claim any other R11 implementation bytes.

Targets: new model <=120 physical/220 structural; registry <=200/380 and actual duplicate deletion; both resource_models module and every retained debt owner must not grow relative to actual R11. New test_model <=350/900, test_consumers <=450/1100, test_path_registry <=500/1000. All fresh production functions <=150 physical/structural, C15, nesting4, parameters8; fresh test functions <=200 physical/structural under existing policy. Do not move allowances, pack source, add suppressions or raise thresholds to meet them. Recompute R02 proportional retained evidence and all lint/import debt at actual entry: the shown structural decrease is a feasibility measure, not a future gate receipt.

## Finite characterization and test contract

Before changing production source, turn the existing 88-outcome and expanded 404-outcome external characterizations into immutable base evidence with exact values/types/error classes/messages and rendered byte hashes. Retain all 12 existing selected method IDs and ASTs from R12-runtime-test-inventory.json, plus the aggregate architecture owner. Four bounded current modules collect 17 methods; that is collection only, not a run. All 30 current source/fixture hashes and 19 source-owner metrics are in R12-current-source-inventory.json.

New test_model methods (seven): point constructor/serialization order and frozen behavior; canonical shape/raw identity and snapshot behavior; point filtering/defaults/order; bool/numeric/truncation/closed table; unknown fields and caller names; exact geometry exceptions; canonical dependency/import ownership. Each table is finite and uses ordinary unittest/subTest, with no reflective test framework.

New test_consumers methods (six): aggregate canonical identity/shape; registry canonical point identity and same output projection; caller-specific read/root/encoding errors (the four root categories use accepted issue #882 scope); aggregate numeric-error timing (uses the accepted five-field API scope); R10 trailing-comma/string/unknown behavior and source containment; complete normal aggregate/registry value comparison including empty resources and input name authority. Assert all other aggregate family records/diagnostics remain unchanged for the committed matrix.

Add five tests to existing TestPathRegistry: one-shot iterable/duplicates/order; build failure before any output; scene-before-registry ordering with exact partial-write state; registry failure after already written scenes; native text-writer byte equality and non-res:// scene suppression. Expected bytes must come from the established renderer/text-writer behavior and fixed fixtures, not from reusing the candidate parser to generate its own expected values. Keep the current three tests intact, including real source-symlink escape rejection.

The selected existing methods include four AssetRegistryConverter cases for malformed/empty metadata, failure accounting and real generated outputs; three registry tests; GML lowering and runtime value/presence checks; actual paths motion smoke; and the full resource_matrix CLI/Godot method. Their exact IDs are in the inventory; do not silently replace them with the new model tests.

## Native runtime, parity and performance evidence

Run the current paths motion smoke on the exact Godot4.7.2.stable.official.ed1daf0bf. It uses manually constructed two-point entries and proves length20, halfway10/0.5, Path Ended/state clearing and grid route50/start(5,5); it does not read YY or load Path2D. Separately run the current resource_matrix actual CLI/Converter test with GODOT_BIN explicitly set and the exact-version check observed. That method returns early without Godot when the env is absent, so a generic passing result alone is insufficient. It reads the committed closed three-point YY and creates/loads its Path2D scene. Preserve both fixture/output hashes and distinguish parse/load evidence from sampled movement semantics.

Runtime source remains unchanged, including these existing limits: kind/godot_path are dropped by normalization; speed metadata and precision do not control polyline stepping; closing length is counted but the final ordinary-segment return can bypass the later closing-segment interpolation. No smooth/closed/endaction/reverse/empty/one-point feature improvement is claimed or fixed in R12. Any separately observed bug goes to root for separate issue/scope reconciliation.

Before/candidate comparison uses immutable actual R11/R12 code, identical input files and unnormalized native bytes. Include the committed three-point YY, existing two-point/default/empty cases and the bounded malformed table; only the complete accepted malformed-root and eager five-field numeric domains in the final addendum may differ. Compare full generated registry/scene maps, diagnostics, resource counts, phase/error precedence and actual runtime sample output. Root chooses the existing conversion-parity receipt/cohort integration; no new runner/schema/framework is needed.

Performance is separately measured because the new path reader performs R10 recursive validation and the aggregate now constructs real point geometry. Use a deterministic 200-file path-only manifest with 32 ordered points per file (6,400 total), plus the committed small fixture. Freeze exact source bytes/counts and measure three existing API workloads: build+render; aggregate parse; actual AssetRegistryConverter.convert_all. Record output hashes and counts so skipped work cannot appear faster. One warm-up, five alternating isolated base/candidate samples, three passes per sample, native Python3.12.10, same temporary output policy and an agreed CPU window; preserve all samples, median/variance and raw peak RSS with platform units. Report the aggregate's added work separately. Investigate material regressions with root; no invented speed target or speculative optimization.

After accepted implementation: Pyright --warnings 0/0, project/tracked Ruff, focused model/registry/aggregate/asset/runtime tests, strict immutable-parent ratchet and diff check, then frozen full unittest with exact Godot and all five pinned projects. Require actual applicable macOS/Linux/Windows source/native jobs and retain precise skip categories. No local modeled evidence certifies Windows behavior. Freeze source/hash/receipts for separate independent and root actual-code review before any commit or integration.


# R12 final contract addendum

Root accepted the canonical PathModel aggregate shape, stable asset-field value contract and eager five-field numeric normalization as explicit architectural API tradeoffs on 2026-09-05. [Issue #882](https://github.com/Infiland/GM2Godot/issues/882) separately owns deliberate rejection of non-object path rereads. These decisions replace the three pending gates and the literal seven-example parity limitation in the original proposal. They do not authorize implementation: corrected independent/root final review and actual R11 integration/source/base refresh remain mandatory.

All original 15 artifacts remain byte-identical. Their original status comments are historical. The refined final contract preserves the exact seven allowed paths, canonical/DTO ownership, source containment, publication lifecycle, no-adapter/no-new-debt limits and runtime/performance requirements. No new repository file or runtime change is added by this refinement.

## Exact numeric domain and evaluation order

One pure parser performs the same numeric operations the registry builder already performs, now also when the aggregate constructs canonical path geometry. For each dictionary point, normalize x then y then speed in input order; finish every point before closed, kind and precision. closed keeps bool(value). kind precedes precision. The parser remains outside the aggregate read/decode catch, so numeric conversion errors are not changed into source-missing diagnostics.

| Supplied field value | x / y | speed | kind / precision |
|---|---|---|---|
| Field absent, null, string, array or object | Default 0.0 | Default 100.0 | Default 0 / 4 after the existing float/int path. Numeric strings are not parsed. |
| bool | float(int(value)): 0.0 or 1.0 | Same | int of that float: 0 or 1. |
| Ordinary int or finite float | float(value), retaining the existing float rounding and sign behavior | Same | int(float(value)), truncating toward zero. |
| Integer outside float conversion range | OverflowError during parsing | Same | Same OverflowError from the intermediate float conversion. |
| NaN | Accepted by model/build/registry JSON rendering; current scene coordinate formatting raises ValueError | Accepted, including the existing nonfinite JSON metadata text | ValueError from int(NaN) during parsing. |
| Positive/negative infinity | Accepted by model/build/registry JSON rendering; current scene coordinate formatting raises OverflowError | Accepted, including the existing nonfinite JSON metadata text | OverflowError from int(infinity) during parsing. |

The accepted aggregate timing change covers the entire existing float/int error domain over x, y, speed, kind and precision, not merely the original three witnesses. The registry's error types/messages and order remain. Existing nonfinite text may be unsuitable for Godot; preserving that text does not claim broader valid-input support. No finite-value rejection, clamp, smoother, decoder change or runtime fix is authorized.

The expanded executed matrix has exactly 19 value rows for each of five fields: absence, null, both booleans, zero, negative integer, ordinary fraction, negative zero, numeric string, nonnumeric string, list, object, positive/negative 10**400, NaN, both infinities, 2**53+1 and 1e308. Six cross-field cases discriminate point-before-metadata and kind-before-precision exception order. This gives 101 scenarios and 404 outcomes (build, aggregate, registry render and scene render).

Current versus external projection: 382 outcomes are identical. Exactly 22 aggregate outcomes differ: ten positive/negative huge-integer field cases; six nonfinite kind/precision cases; and six cross-field error cases. All 303 build/registry-render/scene-render outcomes are identical. The existing registry errors become aggregate errors; no other changed result is accepted by this matrix. The complete ordinary-value contract remains in the refined main document.

## Stable asset fields and changed read timing

Supported asset entries provide stable id, name, kind, source_path and godot_path values throughout each build. Actual production AssetRegistryEntry and current test _AssetEntry owners are frozen dataclasses; no deliberate rebinding/property-callback consumer was found. An ordinary entry object may still satisfy the protocol, but there is no promise to preserve side effects or raised exceptions from effectful property access. No runtime wrapper, memoizer, validation layer or callback API is added.

The following trace was executed using a temporary observer returning the same fixed values. It records timing, not an additional supported effectful-property contract:

| Case | Current read order | Canonical projection read order |
|---|---|---|
| Valid geometry | kind, source_path, id, name, godot_path | kind, source_path, name, id, godot_path |
| Huge x error | kind, source_path | kind, source_path, name |
| NaN kind error | kind, source_path, id, name | kind, source_path, name |

The model receives name before numeric parsing, and id is read when creating the output DTO after geometry succeeds. The previously stated numeric field order is unchanged. Iteration remains one-shot and ordered; duplicate entries and ordinary scalar values retain their existing behavior.

## Separate malformed-root issue scope

Issue #882 covers decoded array, string, boolean and numeric roots reaching the registry reread after ordinary discovery or through its direct API. Reject them with ValueError containing the resolved, contained source path before opening any new path output. Do not skip them or recreate the accidental AttributeError. This is distinct from the accepted aggregate geometry timing tradeoff.

Preserve JSON null, malformed JSON and OSError skipping; preserve encoding, digit-limit and recursion error propagation. The aggregate retains its object-root filter and exact existing missing-resource diagnostics. No source guard, writer lifecycle or object-field coercion is relaxed. Issue #882 remains open until root records final integration evidence.

A separate 14-case actual writer/reader probe uses a valid first entry followed by the tested entry and seeds existing outputs. It covers array/string/boolean and five numeric examples (integer, finite float, NaN and both infinities), null, malformed JSON, missing source, invalid UTF-8, a 5000-digit integer and 20000 nested arrays. Eight non-object examples change only AttributeError→the issue #882 ValueError; all fail before any new output and preserve the seeded files. All 14 cases have identical aggregate results/diagnostics and output maps between current and projection. Null/malformed/missing inputs still allow the valid first entry to publish. Encoding/digit-limit/recursion errors still fail before new output. This is ordinary temporary-filesystem proof, not a native race/handle claim.

## Evidence and completion gate

`numeric-before.json`, `numeric-projected.json`, `numeric-comparison.json` and their script contain the 404 outcomes, exact module origins/hashes and read-order observations. `roots-before.json`, `roots-projected.json`, `roots-comparison.json` and their script contain the 14 writer cases. Source implementation is still the original external 71/109 model preview; no repository candidate exists.

Carry the finite matrix into the planned model/consumer tests using ordinary subTest tables. Keep each fresh method within the existing limits; split by the five named fields/error phases if needed inside the already allowed test owners, without adding a framework or dropping rows. The final expected test-ID inventory is collected and frozen at implementation. Preserve all existing retained selected tests and the original exact native/runtime/full proof requirements. Final parity compares the complete accepted input domains, not only the original seven literal examples.


# R12 entry refresh against final R11

Conditional entry is source-compatible with the accepted R12 contract; implementation is still unauthorized until R11 merge CI is verified. Final R11 head `14b380744384bca975d916486286cf5c44d08ae7` and actual merge `1196295179296dfc12274ff39ba79e6adfb4a1b2` have the same tree `dade43475e4c3a8a1603af9ec697db0c8c2d4427`. This read-only refresh does not establish CI completion.

The seven accepted paths remain exact: new `src/conversion/path_model.py`, existing `src/conversion/path_registry.py` and `src/conversion/resource_models.py`, new `tests/test_path_model.py` and `tests/test_path_model_consumers.py`, existing `tests/test_path_registry.py`, and the root-owned `maintainability-baseline.json`. The implementer therefore owns six paths. No further source, test, fixture or workflow path is requested.

All 27 frozen proposal artifacts verify. Of 30 source inputs, 24 are byte-identical. The six changes are the baseline, R11 project manifest/resource aggregation/audio-group registry changes, R11 architecture assertions, and the I01 corpus assertion-path relocation. Within the 19 inventoried owner functions, only `parse_gamemaker_resource_models` changed: `project=manifest` replaces the deleted descriptive project projection. The R12 parser, renderer, path writer, selected registry consumers and all 12 retained runtime method ASTs are unchanged. The corpus payloads and path fixture bytes are unchanged.

Apply R12 to actual R11, preserving canonical project identity and the permanent manifest type exports. Do not repeat the old hypothetical ProjectModel deletion or restore its constructor/parser. The former R11 physical projection was 586 lines; the actual aggregate is 582. Current-to-R12 projected physical/structural units are resource_models 582/989 to 580/984, path_registry 206/394 to 178/323, and new path_model 71/109. The aggregate parser remains 135/265 to 135/261. Existing test_path_registry is 134/266. These remain below all accepted destination/function budgets; unchanged function ASTs preserve the reviewed complexity limits. New test bodies still require implementation-time measurement.

The original external preview classified the then-nonexistent path_model as a separate import group. This refresh sorts an external temporary copy of the real source tree with the new model present, under the accepted R04 flags; it removes one separator in each affected existing module. All three projected non-import ASTs and import bindings equal the frozen proposal. This is an import-layout correction, not a claimed architectural improvement. The dependency remains resource_models/path_registry -> path_model -> json_values; the model has no writer/registry import, so the ordinary final import order does not introduce a reverse edge. Actual import and runtime proof remains implementation work.

No accepted semantic choice changes: stable concrete asset fields, the complete five-field numeric conversion/error-timing matrix, the explicit obsolete descriptive PathModel retirement, #882 non-object root ValueError, raw identity, typed JSON inputs and existing publication/error ordering all remain required. No adapter, broader cast, new allowance, budget inflation or new scope is proposed.

Root must seed and update the baseline from the actual verified entry parent and serialize the existing coverage/required-ID integration. Any newly integrated T01 runtime-helper changes need a source/ID refresh before dispatch; no helper migration is silently included here. Full/native/characterization/parity and reserved benchmark proof remain exactly required by the accepted contract. No tests, benchmark, full suite, production edits or shared metadata edits were performed for this refresh.


## Frozen implementation source accepted

Independent review and root actual-code review approve the six owner files in
source index SHA256 `9912f6435997317e3f7d13f4613b48d6b2489c16dcbc113053525da639934a36`.
The independent receipt is
`d99054adcbf38cfacad87dd398fc4fb748c0245182928729b0a681a632c8ca70`;
root actual-code review is `424a31410d4e66505164b25a719c0f4552405e842424c2aa6fa884fd741c4252`.

The canonical model is 74 physical/109 structural lines. Registry shrinks from
206/394 to 172/323, and aggregate from 582/989 to 578/984. The two new test owners
are 197/728 and 212/724; registry tests are 243/670. Fresh production functions
remain at most 14/35 lines and fresh tests at most 42/168, within the accepted
complexity, nesting and parameter budgets. Small deletion-boundary blank-line
cleanup is not an architectural improvement. The strict actual1196295 baseline
retains 1,056 entries; only aggregate function structure 265→261 and module
structure 989→984 decrease. No mapping, new allowance or threshold changes.

One pure parser owns point filtering and x/y/speed then closed/kind/precision
coercion. Registry and aggregate consume its exact canonical model; renderers
and publication function bodies remain unchanged. The old descriptive model and
three unchecked casts disappear. Raw-object identity, parsed snapshots, source
containment, exception boundaries and ordered partial writes retain their
accepted behavior. Only the reviewed full-domain eager aggregate errors and
issue #882 non-object ValueError differ. All other resource-family branches
remain unchanged.

Before-production proof recorded 88 direct outcomes, 404 numeric outcomes and
14 root/publication cases. Five new writer tests and three retained registry
tests passed against unchanged parent source. Final source-bound comparison
preserves all 303 builder/render numeric outcomes and all output maps; the
22 aggregate errors and eight non-object errors match the accepted domains.
Pyright reports zero errors/warnings; both Ruff paths and diff checks pass.
The exact-Godot focused cohort passed 35/35 without skips, and the independent
21-case unit check also passed without skips. These checks are local evidence.

Root registers those exact 35 IDs as the R12 gate with zero allowed skips and
unchanged R11 runtime, external fixtures, parity fields and normalization. Six
owner paths become required inputs. The canonical path model joins the existing
project-parsing coverage owner; all floors and historical baselines stay fixed.

Benchmark, full exact-Godot/all-five-project proof, required gate, five-fixture
all-fourteen-field parity and same-ref control still require the frozen candidate.
Final actual-parent integration and native PR/merge CI remain completion criteria.


## Final immutable local proof accepted

Independent and root review approve candidate `0763d71879d1f166b90134159c1594ce84b10db8`
with source commit `9e01fd1610f3aa25375cd763c171d3767bed5646`. The exact R12 gate
passed 35 tests with zero skips or exceptional results. Full unittest with exact
Godot and all five projects passed 3,120 tests in 768.258 seconds. Its 56 exact
skip records match the previous R11 full run: 53 Windows/NTFS, two Linux bind
mount and one host case-sensitivity case. These remain missing native evidence
on the local host.

Both actual119-to-candidate and candidate-to-itself comparisons passed all five
fixtures and 14 unchanged R01 fields, including all visible file hash/size/mode
maps and the existing transaction-semantics comparison. The 44 facade exports
match; raw private transaction records remain preserved with their allowed
volatility. All 580 tracked files, 392 phase inputs, six source/six metadata
owners, harness hashes and pinned fixture identities remained unchanged.

The final benchmark used two excluded warmups and ten fresh samples, three
passes per sample. Every output map, byte hash, mode, count, raw log and common
model field matched. For 200 paths with 6,400 points, registry conversion median
rose 21.251 ms across three passes (+2.20%); build/render rose 18.661 ms (+14.00%)
and aggregate construction 12.683 ms (+8.21%). Whole-process median RSS rose
3,997,696 bytes, including imports and retained results/converters. These scoped
costs are accepted for canonical validation and ownership. Their cause has not
been profiled, and no whole-project speed improvement is claimed. The small
mixed registry-only fixture retains its existing one unavailable Included File
and exact warning; the separate full CLI/Godot fixture test passed.

The two earlier failed excluded-warmup attempts and their copied source/input
inventories are preserved. None contributed final samples. Root and independent
review verified all 151 indexed artifacts, all three attempts' manifests and
all 12 final raw captures.

Final index SHA256: `6d0ad4c0d976d76b43271c0550dd51b365e69a4e5494598b11e6a4854f5f7912`.
Independent receipt: `bb18fdc0acabd2ab5dd36cca8a67c87dd56b3c8ed04283d228e05b233daa8c56`.
Root final review: `d17b2b10358680205e0a73c24b85cbc8d5164143184c7c8f97346256fb6614e3`.

R12 is approved locally. Final metadata review, actual-parent combined source
checks and exact PR/merge native CI remain required before verification.


## Prepared integration with reviewed T01 and corrected L01

Prepared merge `d6f0d85fd225e146358d2a57b41732e9f94be417` combines the six
approved R12 source owners from `9e01fd1610f3aa25375cd763c171d3767bed5646`
with reviewed T01 parent `1d544e02cad9d99d2102c8d9c54e6819f4e548a2`. That
parent includes the independently reviewed L01 Windows snapshot-key correction
at `397e1bc6184155086105eb7b5d10477dc45747d4`. These are prepared sources;
L01 native PR CI and later predecessor/own merge verification remain pending.

All six R12 owners remain exact approved bytes; the other 384 Python files match
the reviewed T01 parent. The combined tree has 390 Python files. T01's two Godot
setup migrations in the path-motion and resource-matrix tests are retained with
all runtime assertions. All seven parent verification gate objects remain intact;
only the accepted 35-test R12 gate is added. Coverage adds path_model.py to the
existing project-parsing group, with every other value and floor unchanged.

Root seeded the exact reviewed-parent baseline and regenerated it from combined
source. All 1,045 keys remain, with only two lower allowances: resource_models'
parser structure 265 to 261 and module structure 989 to 984. There are no new or
grown allowances or policy changes. The resulting baseline matches the merged
source evidence exactly. The strict gate passes against `1d544e0`.

On frozen tracked inputs, Pyright reports zero errors and warnings, Ruff and diff
check pass, all 35 required R12 cases pass without skips on exact Godot and the
pinned fixture environment, and 113 CLI/policy tests pass with one expected
Windows-only local skip. Input hashes are unchanged before and after all checks.
The earlier full suite, five-fixture parity/control and benchmark remain evidence
for immutable `0763d71879d1f166b90134159c1594ce84b10db8`; no new full-suite or
benchmark claim is made. Actual verified-parent ancestry, final metadata review
and exact native PR/merge evidence remain completion gates.

Combined input SHA256: `60043630166ab54999f4ef033c2e96ef4295aeb61cf8774b8797a0293bc87084`.
Combined result SHA256: `01fdbf08d2ddca50867da7788ea78ac6ff464585a26ff6ea0c487856dc54930d`.
