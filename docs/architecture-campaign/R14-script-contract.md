# R14 canonical script model and source ownership contract

Status: VERIFIED at campaign merge `b45399259c2af24a914fdfefc161ba20c44348ba`, PR #897. Independent and upper-agent reviews accept the actual source, composition, local full/parity, qualified performance and exact PR/merge CI evidence. The immutable external receipt `R14/final-verification.json` has SHA256 `153626479d515bad5387bc0d55a7702f79ce5de653b91168bd3861830365ac99`. The design and earlier execution entries below retain their historical source bindings and fourteen-path implementation scope.

## Concrete benefit and authority

`scripts.py:405–492` and `asset_registry.py:2754–2844` implement the same preferred/fallback sidecar search with different entry guards and one different diagnostic. Move the matching search into one script-specific source owner. `script_functions.py` already owns the lexical parser; retain it unchanged. There is no renderer YY dictionary parser to remove. Amend that stale R14 contract claim explicitly.

The canonical nine-field `ScriptModel` will replace the descriptive aggregate-only class. The registry will construct this model from its already-owned metadata/raw dictionary at the current alias-discovery point, resolve the registry sidecar into the model, and use the resulting `gml_path` for the actual UTF-8 read/`modern_script_function_names` input. The alias loop will use the same returned model's `name` and `yyp_path` for base-name suppression and alias identity metadata. The aggregate will return that same canonical class, populated through its unchanged common metadata and neighbor policy. Discovery will consume the canonical raw dictionary/name/path through one relocated typed name query. These are required production consumers, not import-only adoption. No new YY parser is proposed.

The renderer continues to consume its independently read GML string through `modern_script_structure`; the model must not become a cross-phase source-text or lexical-structure cache. Registry folder derivation remains `_get_subfolder_from_resource` → `_get_subfolder_from_yy`, including its existing reads/cache behavior. Do not replace it with the model's descriptive `subfolder`, because that would change current behavior.

## Exact source scope

New production owners:

- `src/conversion/script_model.py`: pure canonical nine-field dataclass, empty-raw factory and finite dependency-name query. No added subfolder normalization, I/O, JSON decoding, converter/writer imports, lexical parser, cache or diagnostic sink.
- `src/conversion/script_sources.py`: three named entrypoints for conversion, registry and dependency discovery; one shared conversion/registry search split into bounded directory/preferred/fallback helpers. Existing source path primitives and synchronous caller callbacks only. No source-text or YY reads.

Existing production edits:

- `src/conversion/scripts.py`: replace `_script_yy_source` and `_source_gml_path` search bodies with one small converter-context binding method and the source-owner call at `_write_script`'s current source-selection point. Retire the two old private entrypoints; no renderer, registry-publication, cancellation or outcome rewrite.
- `src/conversion/asset_registry.py`: replace `_script_source_gml_path` and `_script_function_names` with one bounded model/alias-input helper; change only the scripts branch of `_build_entries_from_resources` to consume its model and function names. Keep base-entry construction, tags/legacy-ID policy, output paths and all other resource families unchanged.
- `src/conversion/project_source_discovery.py`: only the scripts arm of `_resource_gml_candidates`, its model construction, and removal of `_script_gml_candidate`; preserve `project_gml_source_paths` reads, catches, revalidation, manifest order and physical-source deduplication.
- `src/conversion/resource_models.py`: import/re-export the canonical `ScriptModel`, retire the old class declaration, and name the four-model union once as `ParsedResourceModel` for its two existing annotations. Keep `_base_kwargs`, the scripts arm, bucket ordering, every other family and `_first_existing_neighbor` bodies unchanged.

New tests: `tests/test_script_model.py`, `tests/test_script_sources.py`. Narrow existing edits only in `tests/test_scripts.py`, `tests/test_asset_registry.py`, `tests/test_project_source_paths.py`, `tests/test_conversion_architecture.py`, `tests/test_gamemaker_json.py`. Existing private probes at test_scripts:68–70 and test_asset_registry:2216 migrate to their actual successor paths; no compatibility-only old adapter remains. No new tracked fixture is presently justified: use existing fixtures and finite temporary directories.

Root alone owns any R14 contract, ledger, architecture ownership/test-selection and maintainability baseline metadata amendments. Root additionally owns the bounded native test-selection amendment below. No tool configuration, version, release or unrelated family edits are proposed. `script_functions.py`, `base_converter.py`, `project_source_paths.py`, `project_macros.py`, `project_enums.py`, `objects.py`, `converter.py`, and `tests/test_path_model_consumers.py` remain unchanged preservation inputs.

## Four path policies remain distinct

| Entry | Candidate order / guard | I/O and result |
| --- | --- | --- |
| Conversion | Resolve YY; require casefold `scripts/` prefix and `.yy` suffix; name `.gml` then sorted exact-lowercase `.gml` fallback, excluding the original/normalized unsafe preferred name | Preferred success avoids `listdir`; absolute result. Keep the converter's `must be exactly one safe path component` diagnostic |
| Registry | Resolve YY and require file; upstream family checks remain upstream. Same candidate loop as conversion | Preferred success avoids `listdir`; absolute result. Keep registry's `must identify exactly one path component` diagnostic |
| Dependency discovery | Manifest name, nonempty string `%Name`, nonempty string `name`, YY basename; preserve duplicate candidates, safe-component checks and owner-directory equality | No enumeration or local deduplication; project-relative result or empty string. Outer discovery re-resolves/rechecks and deduplicates `normcase(realpath)` in manifest order |
| Aggregate | YY basename `.gml`, then sorted neighbors matched with `.lower().endswith('.gml')` | Enumerate directory before preferred file check; listdir failure returns no source even if preferred exists. Deduplicate `normcase(abspath)` before resolution; collect existing-candidate path diagnostics. Absolute result |

The aggregate policy stays in the existing `_first_existing_neighbor`, shared with `.vsh` and `.fsh`. There is no fourth source entrypoint, new aggregate helper or callback. Its current direct canonical construction remains sufficient. The aggregate-only static projection reduces the parser's structural size 255→253 and its module 968→965 through class relocation and the shared explicit union alias; both operation bodies are unchanged. These are isolated proposal measurements, not complete candidate metrics. The rejected parser/helper and callback alternatives remain only as indexed comparison evidence; see AGGREGATE-COMPARISON.md.

For conversion/registry, each resolver/report callback runs immediately at the old operation boundary. `BaseConverter._report_source_path_rejection` adds its diagnostic under the lock and invokes `log_callback` before returning (base_converter:182–219). Do not collect reports, defer them until selection ends, catch callback exceptions, pre-resolve later candidates, or snapshot future filesystem results. A callback can raise or create/remove the next candidate. Concrete candidate and callback traces must match the old code.

## Bounds and compatibility

Each new module must be at most 800 executable physical lines. Every fresh function, including tests and context binders, must satisfy complexity ≤15, nesting ≤4, parameters ≤8, physical span ≤150 and structural size ≤150. These are acceptance caps, not measured candidate claims. Split only the named preferred/fallback operations as needed. No mode enum, configurable policy registry, generic traversal/trace framework, extra typing debt, new Any/casts/suppressions, duplicate GML parser or old-owner compatibility layer.

Retained debt cannot grow. In particular, registry `_script_source_gml_path`'s structure-160 debt must disappear; the scripts and registry module ratchets and aggregate `_parse_resource_model` structure-255 must not grow. Keep `_ParsedResourceModelBuckets.add`'s existing shape/order without expanding its nesting. Final metrics must be measured from the actual complete candidate, including fresh tests; no reduction is asserted by this proposal.

Canonical class relocation intentionally changes its defining module and removes `ResourceModel` inheritance, as with the existing canonical PathModel/FontModel pattern. Keep `resource_models.ScriptModel` as the same imported class, preserve the nine field order/defaults and frozen behavior, and explicitly approve this internal type-ownership change. Static search found no repository consumer requiring the old subclass relation. Do not claim unknown external `isinstance` callers are proven compatible.

No real source-feasibility blocker was found. Remaining gates are explicit design/type-ownership approval, exact old characterization bodies and captures, actual projected source/test review and metrics, all required checks/proofs, and independent/root review. None was executed here.

## Assigned ownership and execution boundary

Implementation owner: `prepare_i03_observer` in `dev/080-script-model`; independent reviewer: `prepare_r13_ci`; root owns acceptance, metadata and integration. The existing 59 methods are a reuse inventory; the 14 proposed characterization methods require frozen actual bodies and pre-use review. Candidate-only authority checks are separate from old behavior.

## Accepted API and caller contracts

These are source contracts, not installed or executed modules. Primary design is canonical class relocation and actual consumer adoption. No new YY parser or subfolder normalizer is proposed.

## Canonical model

`script_model.py` uses `dataclass(frozen=True)` without slots and `JsonObject` from `json_values`. Preserve the exact ordered schema:

```python
class ScriptModel:
    name: str
    kind: str
    resource_type: str
    yy_path: str
    yyp_path: str
    order: int
    subfolder: str = ""
    raw_data: JsonObject = field(default_factory=_empty_script_raw_data)
    gml_path: str | None = None

def _empty_script_raw_data() -> JsonObject: ...

def dependency_script_names(model: ScriptModel) -> tuple[str, ...]: ...
```

The constructor requires exactly the original first six fields and defaults only the last three. Its default raw dictionary is fresh per instance; supplied raw dictionaries are assigned by identity, without copying, recursive validation, freezing, filtering, coercion or decoding. Keep the existing `yyp_path` spelling and meaning: project-relative YY source path, not the YYP filename. Aggregate continues to supply all original nine values through its unchanged common `_base_kwargs` and neighbor selection. New registry/discovery models have explicit `kind='scripts'`; registry supplies internal descriptive `resource_type='GMScript'`, `order=0`, and leaves descriptive subfolder empty because no current registry alias operation uses that field. These new internal defaults must not replace aggregate manifest metadata, output-folder derivation or ordering.

`dependency_script_names` moves discovery:124–131 into the pure model owner: start with `model.name`; append `%Name` then `name` from `model.raw_data` only when each is a nonempty string; append `posixpath.splitext(posixpath.basename(model.yyp_path))[0]`. Return that tuple without deduplication. Sample the dictionary at the current discovery call. This is the only script-specific raw YY name query being relocated. Aggregate common metadata normalization remains in its existing shared owner; neither renderer nor registry currently has a duplicate YY parser.

## Finite source APIs

Use positional callback aliases, without generic callable signatures, Protocols or a context framework:

```python
ScriptPathResolver = Callable[
    [str, str | None, str], ResolvedProjectSourcePath | None
]
ScriptRejectionReporter = Callable[
    [str, ProjectSourcePathError, str | None, str], None
]

def conversion_script_source(
    name: str, source_path: str, *,
    resolve: ScriptPathResolver,
    discover: ScriptPathResolver,
    report: ScriptRejectionReporter,
) -> str | None: ...

def registry_script_source(
    model: ScriptModel, *,
    resolve: ScriptPathResolver,
    discover: ScriptPathResolver,
    report: ScriptRejectionReporter,
) -> ScriptModel: ...

def dependency_script_source(
    project_root: str,
    model: ScriptModel,
    resolved_resource: ResolvedProjectSourcePath,
) -> str: ...
```

Resolver callback arguments mean `(path, owner_source_path, field)`; reporter arguments mean `(path, exception, owner_source_path, field)`. Each converter context supplies three local lambdas/functions that call its existing self._resolve_project_source, self._resolve_discovered_project_source, and self._report_source_path_rejection with those exact keyword arguments, the current entry/resource name, and resource_type='script'. Look up each bound method inside its callback on every call. Do not retain a bound-method cache. Creating these local callables performs no I/O/reporting. Calling one executes the existing resolver/reporter immediately; exceptions propagate exactly as before.

The only private source helpers proposed are:

```python
def _conversion_yy_source(
    source_path: str,
    resolve: ScriptPathResolver, report: ScriptRejectionReporter,
) -> ResolvedProjectSourcePath | None: ...

def _named_script_source(
    name: str, yy_source: ResolvedProjectSourcePath, unsafe_message: str,
    resolve: ScriptPathResolver, discover: ScriptPathResolver,
    report: ScriptRejectionReporter,
) -> str | None: ...

def _preferred_script_source(
    name: str, yy_source: ResolvedProjectSourcePath, unsafe_message: str,
    resolve: ScriptPathResolver, report: ScriptRejectionReporter,
) -> tuple[str | None, set[str]]: ...

def _fallback_script_source(
    yy_source: ResolvedProjectSourcePath,
    script_directory: ResolvedProjectSourcePath, excluded_filenames: set[str],
    discover: ScriptPathResolver,
) -> str | None: ...
```

The two unsafe-message strings are fixed by the conversion/registry entrypoints, not configurable policy modes. `_named_script_source` resolves the directory before preferred validation, checks isdir, calls the preferred helper and only then the fallback helper. Preferred validation retains original/normalized-name exclusion, safe-component and owner-directory checks. Fallback retains sorted enumeration, exact lowercase `.gml` filtering, excluded names and discovered-source resolution, in that order. Split no further unless required by actual owner caps and reviewed for cohesion.

Conversion's YY helper retains the extra casefold scripts/.yy check. Registry performs its original resolve/isfile guard using model.yyp_path and model.name, invokes the shared search, then returns `dataclasses.replace(model, gml_path=selected_path)`. Failure clears any supplied previous gml_path; the input path is never a cache. Dependency retains the original ordered sidecar loop over dependency_script_names(model), resolver/catches, owner-directory equality and isfile. It neither enumerates nor reports diagnostics.

## Actual caller migration

1. `ScriptConverter._write_script` replaces only its source-selection expression with a small `_conversion_script_source(entry: AssetRegistryEntry) -> str | None` context binder calling conversion_script_source. The binder supplies entry.name/source_path and the three local callbacks. Remove old `_script_yy_source` and `_source_gml_path`; no compatibility-only forwarding names remain. Source selection still precedes `_output_path`, UTF-8 read, source diagnostics, render, output write and source maps. `_render_script` still calls the same modern_script_structure with the same string and macro configuration.

2. Replace registry's two old source-search/function-name methods with:

```python
def _script_model_and_function_names(
    self, resource: _ProjectResource,
) -> tuple[ScriptModel, tuple[str, ...]]: ...
```

At the current alias-discovery point, construct `ScriptModel(name=resource.name, kind='scripts', resource_type='GMScript', yy_path=resource.yy_path, yyp_path=resource.source_path, order=0, raw_data=resource.raw_data)`. Pass it and the local callbacks to registry_script_source. If the returned model.gml_path is None, return `(model, ())`; otherwise perform the old UTF-8 open/read on that exact field and call unchanged modern_script_function_names with self.macro_configuration. Preserve only `(OSError, GMLTranspileError)` catch, returning `(model, ())`; UnicodeDecodeError still propagates. No YY or GML reads move into the new owners.

At asset_registry:2340 use `script_model, function_names = self._script_model_and_function_names(resource)`. Iterate names in their original order. Suppress function_name equal to script_model.name, use script_model.yyp_path for alias source_path and metadata['script_source_path'], and script_model.name for metadata['script_asset']. Keep base-entry creation/append, used-ID allocation, generated output path, tags and legacy-ID calculation at their current positions. Base append still precedes source discovery and callback exceptions. No model crosses into per-script conversion.

3. Discovery's scripts arm constructs `ScriptModel(name=resource.name, kind=resource.kind, resource_type=resource.resource_type, yy_path=resolved_resource.filesystem_path, yyp_path=resolved_resource.source_path, order=resource.order, raw_data=resource_data)` from the already-read object. Call dependency_script_source(project_root, model, resolved_resource); keep `(candidate,) if candidate else ()`. Remove `_script_gml_candidate`. Outer reads, catches, revalidation, deduplication, object/room arms and consumer reads/caches remain unchanged.

4. Aggregate imports/re-exports ScriptModel from script_model and removes only its old subclass declaration. Its common `_base_kwargs`, scripts branch and `_first_existing_neighbor` bodies are byte-identical. It still constructs `ScriptModel(**base, gml_path=gml_path)` after selecting its source, preserving all values, metadata-before-neighbor timing and raw identity. Use one finite `ParsedResourceModel: TypeAlias = ResourceModel | PathModel | FontModel | ScriptModel` for the two repeated union annotations (bucket.add and _parse_resource_model). It names the actual four model alternatives, without a new runtime dispatch layer. The existing bucket branch/order remains unchanged. No new aggregate helper or callback is used.

`aggregate-primary-projection.patch` is the exact isolated existing-owner diff for step4, not a complete runnable R14 candidate. Static AST arithmetic gives module563/968→562/965 physical/structural and parser131/255→131/253; parser body and shader-shared neighbor remain unchanged. The complete candidate still needs all metrics/checks after approved implementation.

No YY read is added. Registry planning and per-script conversion keep separate GML reads and parser calls; dependency consumers keep independent reads and existing macro/enum caches; aggregate keeps its single existing YY decode. This proposal removes the duplicated converter/registry path loop, relocates the discovery raw-name query once, and replaces the aggregate-only class with an actual registry/discovery/aggregate model. It does not invent parsing work to justify the model.

## Implementation entry after actual characterization

The old-source invocation at `3933e07` passed all 71 methods with zero skips:
59 retained methods and 12 new observable cases. Root and independent result
reviews accept the exact callback exception/mutation records and real repeated
reads. The recorded sequence has 11 metadata opens (six YYP and five YY), one
registry GML read, and the converter's GML read followed by its GD write. Preserve
the complete ordered arrays; only their recorded temporary project/output root
prefixes may differ in the candidate comparison. No elapsed-time speed claim is
made from the concurrent correctness run.

Root now authorizes prepare_i03_observer to implement the exact accepted APIs
and caller changes within the thirteen allowed paths. Preserve the accepted
old package and its result; do not rerun its source-bound launcher after edits.
Port the twelve cases and retain all 59 existing IDs, adding the two candidate
authority methods and explicit additional authority arms. Complete source,
static, metrics and focused-result review precedes broad final proof. Root
owns baseline, architecture selection, workflow and campaign metadata.

Old result SHA256: `61d7d87d4c3a9b49a3ee0faf72fb35d3dd09dc6047255fb8c37c8437faa70291`.
Independent review: `a0aa0e54f25e4891d4548bf232982b948feda6d88d213bbb784f5219e2d9facb`.
Root review: `cb5a5c01015717504a8bff78f76a36fa83f0f2166c07a9792764ca7ca3a61354`.


## Bounded shared test-support owner

Root authorizes one additional implementation path, `tests/script_source_support.py`,
for `ScriptFixture`, `RegistrySourceProbe`, `RereadingConverter`, and
`ScriptReadProbe`. Both new test modules import these existing cohesive fixture
and probe classes. Keep model assertions in `test_script_model.py` and source
policy/callback assertions in `test_script_sources.py`; neither test module owns
the other's I/O infrastructure. Preserve all 59 retained IDs, new case IDs,
assertions, and observable callback/read ordering. This replaces the proposed
placement of shared probes in the model test module; it adds no new runner,
policy framework, production API, or behavior. The implementation scope is now
fourteen paths. All ordinary fresh-code and test-module budgets still apply.

Root also removed two unused private `name` parameters from the YY guard and fallback helper contracts. The three source entrypoint APIs and callback behavior are unchanged.

## Accepted implementation and broader verification

The independent reviewer `review_r13_full` and root accepted the actual implementation: 73 selected successes, zero skips, all retained callback and repeated-read observations preserved, Pyright zero diagnostics and both Ruff checks passed. The accepted external baseline has 1040 allowances against ae57: one removed and six lowered, with none added or grown. I03 composition requires a fresh actual-parent baseline; 1040 is not a claim about that future combined source.

Actual six-module production totals are 6031 to 6015 physical lines and 9995 to 10020 structural units. The benefit is clearer ownership and removal of the duplicate sidecar search; total structural size does not shrink. New owners are 35/52 and 167/286 physical/structural units; the cohesive test support owner is 192/461. All 64 fresh functions satisfy the accepted caps.

Root authorizes only the following workflow amendment: append the exact 73 selected IDs to the existing macOS native command and the 62 missing IDs to the existing Windows command, retaining its eleven already-selected registry IDs. Preserve all prior commands, setup, coverage, native obligations and the unchanged Godot workflow. Require all 73 unique selected successes on each native host; the five conditional symlink skips receive no successful proof credit. The existing R01 manifest supplies the unchanged five-project/fourteen-field parity contract.

The accepted broader plan is indexed by `R14/broader-proof-plan-81561810/review-files.json`. It requires full discovery with five external fixtures, R01 base/candidate and same-ref parity, and twelve fresh SNAP workers (two excluded warmups, five alternating measured pairs). Each worker calls real dependency discovery and `ScriptConverter.convert_all`; compare all outputs and scoped real-open records. Preserve the production registry callback wiring, including its existing silence. Report measured intervals with observation overhead and whole-process macOS RSS bytes. Final source, runtime, input and executable packages require review before use.

The actual preceding campaign parent is verified I03 merge `74688c86cb58c5e22592f9e868eba828ed064381`. Prepared R14 merge `a4f55de` preserved all independent implementation paths and the reviewed metadata composition: 618 files, 416 Python files, strict 1033 allowances with one removal and six reductions from this parent. Independent/root combined review and all static checks passed. That documentation-only checkpoint preceded executable proof binding; R14 remained reviewing at that checkpoint.

## Final verified evidence

PR #897 merged candidate `fb03dbebfbf7ebf30920f0ed562bf8d3b9afcb95` with the
verified I03 parent into `b45399259c2af24a914fdfefc161ba20c44348ba`. The merged
tree is `71715a8db27ad3cbd4407c0e23e6cdc676dd1f26`, identical to the approved
candidate. Exact PR/merge CI runs 36717618562/36761317593 passed: 24 successful
jobs and the sole permitted dependency-graph submission skip. Six once-only
merge selectors, ten outputs and 27 raw profiles are accepted after independent
and upper-agent review. All 73 selected methods passed on each native host,
including all required symlink cases; four required exact Godot cases passed.
Retained CLI/native/transaction/runtime/artifact and coverage gates passed with
only their explicitly declared host skips.

Full discovery ran 3220 tests with 3162 successes and 58 classified prior host
skips. All five external project and five script-symlink obligations passed.
Five-project/fourteen-field base/candidate and same-reference comparisons
matched under the unchanged R01 normalization. ResourceMatrix retains two
pre-existing compatibility warnings and failed status on both sides; exact
parity and successful import/boot do not establish warning-free output or every
semantic. No additional normalization was introduced.

The final actual-parent baseline is 1033, down from 1034 with one removal and six
reductions, zero additions or growth. The measured production totals remain
6031→6015 physical lines and 9995→10020 structural units. The ownership benefit
does not imply a total structural-size reduction. New production owners measure
35/52 and 167/286 physical/structural; fresh test owners measure 192/461,
147/581 and 404/1378. All 64 fresh functions meet complexity ≤15, nesting ≤4,
parameters ≤8 and physical/structural size ≤150.

The original twelve observations remain final: conversion medians 2.336327625s
and 2.606033375s, an increase of 0.26970575s (11.544%), with four of five measured
pairs slower. Its cause is unassigned. Accepted source-bound profiles show the
small explicit metadata/helper work and unchanged dominant computation/I/O,
resolving the missing material-source-work attribution. The two instrumented
CPU pairs differ in sign; event/timer overhead, generated-label collisions and
opaque native labels remain explicit. These profiles do not replace the original
latency, bound unprofiled incremental cost or prove equal host load. Native
macOS whole-process high-water memory includes guards/imports/mocks/observers;
it is not a production-worker or per-model memory bound. No speedup or precise
latency-equality claim is made.

The canonical class's defining-module/inheritance change remains an explicit
internal exception; unknown external `isinstance` or pickle compatibility is
not established. Earlier failure/review records and their reviewed corrections
remain immutable. Campaign completion is 19/54 (35.2%); this task grants no
final-main or release completion credit.
