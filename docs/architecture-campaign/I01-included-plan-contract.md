# I01 accepted implementation contract

Status: ACCEPTED and assigned by root after independent and root contract review. Fixed implementation parent C is `ec257912ec907161b2e89d552a76dc591ed33b68`. The final source/import/metric refresh is verified in `/Users/infi/Documents/Github/.gm2godot-v080-evidence/I01/final-C-entry-source-confirmation.json`. This entry supersedes historical proposal status/source and completed-R04 implementation-start wording below; all substantive API, behavior, scope, size and proof requirements remain binding.

Sole implementer: `audit_transactions_cli` in `/Users/infi/Documents/Github/GM2Godot-080-included-file-plan`. Independent actual-code reviewer: `audit_gml_resources`, then root. The conditional start follows [R04's reviewed entry contract](R04-parallel-entry-contract.md). Cleanup PR #883 and CI `33943223988` are pending; no child PR or campaign integration is authorized before successful exact cleanup PR and merge proof. If cleanup changes or fails, root reassesses affected work and invalidates stale evidence.

Root has accepted the original finite contract SHA256 `5987a20d80010d614a4d64e38e0c726cea1b7a172edeb5d10fe589d25d8c007a` and confirmed all 15 source inputs at C. Applicable current measurements/import projections are recorded in the external final source receipt; historical measurement tables below remain provenance where earlier source counts differ. Strict comparison uses immutable C; policy thresholds, retained evidence, scopes and suppressions may not grow.

The complete allowed-file inventory below includes `maintainability-baseline.json` for integration only. **Root is its sole writer during parallel work.** The implementation owner edits only the other allowed paths, reports measured reductions, and asks root to run any baseline update sequentially before the final strict gate. Root also owns campaign documents, coverage-policy and architecture-verification integration. Do not edit, commit or push those shared files. Do not commit or push implementation source before root code approval and explicit instruction.

Freeze source before proof. Coordinate a reserved CPU window with root before full-suite or performance/parity runs; focused checks and before-production characterization may proceed. Use the approved native Python 3.12.10 environment and exact Godot `4.7.2.stable.official.ed1daf0bf`, all five pinned project environments where required, and preserve every native/skip distinction in the finite specification.

The accepted final-R04 addendum is `/Users/infi/Documents/Github/.gm2godot-v080-evidence/I01/post-r04-refresh/I01-post-R04-refresh.md` (SHA256 `5c0b62a5b7a2a3828bb9543f5e29236bb0acb3f3d8cdee11f648e40c05cdace3`). Its canonical imports, 200 existing IDs / 10 moves / 12 additions and tight 148-unit planner bound remain binding. Issue #877 is excluded and stays owned by I07/I10.

The independent review may accept this finite ownership/behavior contract now. Final starting
hashes, rendered destination size/type proof, executed characterization and native receipts
are pending implementation evidence, not current blockers in the production extraction.

## Scope decision

Extract the canonical transaction records, bounded lexical path validation and read-only
manifest planning. Keep descriptor acquisition, Windows API wrappers, source discovery,
worker admission, staging, journal codecs, publication, rollback and recovery in their current
owners for their named later slices. This is an ownership extraction, not a new transaction.

Planning currently includes filesystem availability checks and ordered diagnostic effects;
it must not be described as entirely pure. The record owner is a standard-library-only leaf
with no I/O, acquisition, closing, logging, callbacks or imports from conversion owners.

No new state enum is needed. The tables below describe existing state; journals and commit
markers remain the authoritative on-disk decision, with unchanged version 1/2 encoding.

## Existing states and transitions

| State | Evidence and current owner | Next transition / failure behavior |
|---|---|---|
| Planning | `IncludedFilesConverter._included_file_conversion_plan`, declaration resolution, contained disk discovery | Requested/skipped keys and available files are determined before destination locking. Manifest findings precede planning warnings. No destination write belongs to planning. |
| Lock acquired | `_ensure_included_output_project_root`, `_acquire_included_project_lock` | Acquire cooperative project lock, then recover pending state before capturing the previous output. See the separately recorded early interruption gap below. |
| Recovery | `_recover_included_output_set` | Promote a valid durable journal temporary; read journals/markers including tombstones. No journal/no marker permits only self-identified orphan cleanup. Journal without marker restores the previous pair. Matching marker selects committed cleanup; marker-only recovery uses its embedded journal. Mismatch or unknown state fails closed. |
| Previous generation observed | `_capture_included_tree`, `_capture_included_registry` | Bind old identities/content, then inspect sources. Exact unchanged generation returns without namespace replacement after repeated source/public revalidation. |
| Preflight | `_preflight_included_source_byte_counts`, `_preflight_included_recovery_record_sizes` | Compute exact journal/commit record sizes before payload staging. Keep 16 MiB record and 100,000 tree-entry bounds; no size-limit change. |
| Stage owned by converter | `_create_included_output_stage`, bounded copy workers | Private same-project stage and marker are created. Workers finish/close before stage disposal. Before handoff, converter cleanup may remove only the observed owned stage, only when no journal is pending. |
| Verified candidate | Root inventory, registry candidate, `IncludedOutputSetTransaction` | Record immutable identity/content receipts. Set `transaction_cleanup_managed = True` immediately before calling commit. From this point generic converter cleanup cannot remove the stage. |
| Journal prepared | `_commit_included_output_set` | Validate candidate and previous state; publish journal. Phases: `journal-record-staged`, `journal-prepared`. Cancellation is still reversible. |
| Reversible namespace installation | Same commit owner | `previous-root-backed-up` -> `new-root-published` -> `previous-registry-backed-up` -> `new-registry-published`. Each step revalidates/syncs the appropriate identities and checks cancellation. The root/registry pair is a generation transaction, not one atomic rename. |
| Commit decision | Final generation/source validation and marker publication | `commit-record-staged` -> `generation-committed`; verify the published marker. If a native/publication call completed before raising, reread and authenticate the real marker before deciding whether rollback is legal. Ambiguous marker state is retained without rollback. |
| Committed cleanup | `_cleanup_committed_included_output_set` | Identity-bound backup/stage cleanup, then `journal-removed`, then `commit-marker-removed`. Cleanup warnings remain visible. No cancellation-triggered rollback after an authenticated marker. |
| Pre-decision rollback | `_rollback_included_output_set` | Restore previous root/registry identities; remove only recorded stage entries. Successful retirement emits `rollback-complete`; failures attach notes and retain recoverable state. |
| Recovery completion | `_recover_included_output_set` | Uncommitted recovery emits `recovery-rolled-back`; committed recovery emits `recovery-journal-removed`, then `recovery-committed`. A second recovery must be idempotent. |
| Final release | Converter's main `finally` and `_release_included_project_lock` | Reset active output path; retain pending recovery state; release project lock. Main-body secondary cleanup/release errors preserve the original error through notes or visible warnings. Early recovery/snapshot blocks have the separate limitation below. |

Keep every existing finer cleanup/quarantine hook and ordering unchanged; the table is not
permission to collapse them. The source's hook calls and hard-exit matrices remain authoritative.

## Existing ownership, not a new lease framework

| Resource | Acquirer / sole cleanup owner | Ownership boundary |
|---|---|---|
| Cooperative lock descriptor | `_acquire_included_project_lock` returns `_IncludedProjectLock`; converter invokes `_release_included_project_lock` | Lock record is currently mutable data. Release unlocks then closes in `finally`; it does not reset the descriptor or make repeated release safe. Do not add destructors, context managers or ownership semantics to the moved record. |
| POSIX directory descriptors | Native/snapshot/copy helpers and local `try/finally` or `ExitStack` | `_IncludedTreeDescriptorBinding.parent_fd` is borrowed evidence, not an owner. Moving the record must never close its descriptor. |
| Windows directory handles | `_WindowsIncludedCleanupParentBinding.open` and its existing context/close methods | Binding implementation stays for I03. No ctypes structure or native callable moves in I01. |
| Source validation streams | Existing source/copy helpers and their `with`/`ExitStack` scopes | Stream closure remains local. Fingerprints, bindings and payload receipts contain evidence, not live streams. |
| Worker futures/executor | `_run_bounded_included_worker_phase` | At most `2 * max_workers` pending; stop admission after failure/cancellation, cancel queued futures, then `shutdown(wait=True, cancel_futures=True)`. It returns only after running work has finished. |
| Stage before handoff | `_create_included_output_stage`, then converter | Creation cleans a known owned stage on its existing failure branches. Converter owns the returned stage until transaction handoff; uncertain/substituted entries are retained. |
| Stage/backups after handoff | Commit/rollback/recovery through recorded cleanup | `IncludedOutputSetTransaction` records identities; it does not itself acquire or release. Only manifest-bound cleanup can remove these entries after transfer. |
| Journal/marker temporary and published names | Existing bounded record I/O and recovery owners | Durable marker is the decision record. Tombstone/quarantine names retain recovery provenance; remove only authenticated identities. |

### Existing interruption defect, outside I01

At source lines 11630-11670, post-acquisition recovery and initial snapshots run before the
main `try/finally` and catch only `Exception`. A `KeyboardInterrupt`/`SystemExit` there bypasses
lock release. An early release failure can also replace the original ordinary exception.
The exact modeled command/result is `I01/early-interruption-probe.md`: injected recovery
`KeyboardInterrupt` produced `release_calls=0`. This proves the Python cleanup-control-flow
gap; it is not native handle-leak evidence. Root independently confirmed recovery and tree
snapshot cases and opened [#877](https://github.com/Infiland/GM2Godot/issues/877), still open at
reconciliation. **I07/I10 own the separately accepted behavior fix**, including recovery,
initial tree and initial registry capture, exact-once release, primary exception identity and
secondary release-failure precedence. I01 must not fix, normalize or expand those branches.
The record move must not add idempotent release or destructor behavior as an indirect fix.

## Exact proposed production owners and symbols

New `src/conversion/included_files_parts/__init__.py` is empty: no imports or registrations.

### models.py

Move these 20 definitions from the monolith, preserving fields/order, defaults, frozen/mutable
status, property bodies, and `compare=False`/`repr=False` on the three optional transaction
evidence fields. Use the current spelling without its leading underscore as the canonical
package-internal name; migrate references directly, without old-name reexports or wrappers.
This deliberate internal name/owner change is not a new supported converter API. Current
journal/diagnostic serialization does not use dataclass repr or pickle.

- IncludedFileSource, DeclaredIncludedFile, IncludedFileConversionPlan.
- IncludedPayloadReceipt, IncludedCopyReceipt, IncludedSourceBinding,
  IncludedNoOpSourceReceipt, IncludedGenerationMatch, IncludedGenerationContentReceipt.
- IncludedTreeEntry, IncludedTreeSnapshot, IncludedTreeDescriptorBinding,
  IncludedTreePathBinding, IncludedRegistrySnapshot, IncludedRecoveryRecordSizes.
- IncludedOutputSetTransaction, IncludedRecoveryJournal, IncludedCommitMarker,
  IncludedProjectLock, IncludedOutputSetCancelled.

Move the seven tuple aliases with the same underscore removal: PathIdentity,
PathFingerprint, PathHandleBinding, HandleState, IncludedSourceFingerprint,
IncludedSourceDirectoryIdentity and IncludedCleanupFileState. Keep their tuple arity and
component meanings unchanged. No new lifecycle state record, unused descriptive model,
platform API, transaction constant bundle or worker TypeVar belongs in this owner.

### path_validation.py

Move exactly four bounded lexical functions, removing the old leading underscore and
redundant `included_` owner prefix: `windows_recovery_component_is_ambiguous`,
`recovery_relative_path`, `recovery_tree_entry_path`, `output_components`.
The Windows reserved-device-name constant moves with its one consumer, retaining all names
including superscript-digit variants. Existing error classes/text and OS-dependent validation
stay unchanged. One explicit annotation refinement is allowed: moved
`recovery_relative_path(value: object) -> str` replaces `Any` because its first existing
operation checks `isinstance(value, str)` and raises the same OSError for other values. No
new cast/decoder or weakened runtime validation is needed. The other signatures remain
`windows_recovery_component_is_ambiguous(component: str) -> bool`,
`recovery_tree_entry_path(root_path: str, relative_path: str) -> str`, and
`output_components(project_path: str, output_path: str) -> tuple[str, ...]`.
Keep source-path, recovery-path and output-path grammars distinct; do not
replace them with one permissive normalization helper.

This owner imports standard-library path facilities only. Its lexical checks and native
abspath/join/commonpath/relpath/normcase reconstruction do not query filesystem entries,
but abspath can depend on the current working directory. Do not call it independent of
process state or replace native path semantics with one POSIX-only normalizer. It must not import the
facade, codec, cleanup, planning or native owners. Later codec and recorded cleanup import
this leaf; cleanup must not acquire a recovery/codec import merely to rebuild a path.

### planning.py

Move the existing bodies of `_plan_manifest_included_files`, `_declared_included_files`,
`_manifest_diagnostic_is_included_file`, `_normalized_declaration_path` and
`_declared_relative_path` into direct package-internal functions with their owner-local names.
Move the decision/merge body of `_included_file_conversion_plan` into
`build_included_file_plan(manifest, *, resolve_declared, reject_source,
report_unavailable, discover_files) -> IncludedFileConversionPlan`.

The four callables are finite typed boundaries, not a service registry:

| Input | Existing bound implementation | Required call shape / behavior |
|---|---|---|
| resolve_declared | BaseConverter._resolve_project_source | Source string plus owner/resource/resource_type/field keyword arguments; returns existing ResolvedProjectSourcePath or None and preserves source-rejection reporting. |
| reject_source | BaseConverter._report_source_path_rejection | Existing rejected-path/error and owner/resource/type/field arguments; preserves exact family-escape and ordering behavior. |
| report_unavailable | IncludedFilesConverter._report_unavailable_declared_included_file | DeclaredIncludedFile and keyword reason; preserves current warning/diagnostic text and position. |
| discover_files | IncludedFilesConverter._discovered_included_files | No arguments; returns the existing sorted tuple and performs the current confined discovery only when the original branch reaches it. |

Select the four current bound methods **once per plan**, in resolve/reject/unavailable/discover
order, after manifest loading and manifest diagnostic forwarding. Retain those selected
callables through that plan. Overrides installed before this selection remain supported;
there is no guarantee that a later replacement of one of these selected methods is observed
mid-plan. This explicit binding policy is the finite extraction choice, not a live-forwarding
adapter. Current production and test callers do not rebind those four selected methods
while planning. Preserve ordinary nested method lookup inside the selected implementations:
for example BaseConverter._resolve_project_source still performs its existing
self._report_source_path_rejection lookup, and discovery still calls its original helpers.
The existing race instrumentation of retained _list_confined_directory remains effective;
do not substitute callbacks throughout BaseConverter or discovery.

Freeze these consumed signatures (explicit Protocol.__call__ is permitted for keywords):

```python
resolve_declared(source_path: str, *, owner_source_path: str, resource: str,
                 resource_type: str, field: str | None) -> ResolvedProjectSourcePath | None
reject_source(rejected_path: str, error: ProjectSourcePathError, *, owner_source_path: str,
              resource: str, resource_type: str, field: str | None) -> None
report_unavailable(declaration: DeclaredIncludedFile, *, reason: str) -> None
discover_files() -> tuple[IncludedFileSource, ...]
```

The concrete bound callbacks already accept these values (resolver/reporter accept wider
optional inputs). Keep the existing resolved `os.path.isfile` check in planning; no fifth
filesystem service parameter. Use small explicit callable protocols for keyword signatures
where required by Pyright;
no `Any`, reflective member forwarding, BaseConverter protocol, generic context object or
facade import. Planning may import canonical diagnostic models, project_manifest record types,
project_source_paths types, existing included_file_paths and its own models. Import
ProjectManifestDiagnostic from diagnostic_models, retiring that D01 downstream old-type edge.

Keep `_included_file_conversion_plan` as a short meaningful orchestration seam in the
converter: load manifest, forward manifest-level diagnostics, then call the planner with
those four existing bound operations. It is not a compatibility alias and is removed/moved
with coordinator orchestration in I10. Keep `_list_confined_directory`, `_collect_included_files`,
`_discovered_included_files`, `_report_directory_swap`, unavailable/collision reporting and
all native validation bodies unchanged for their later ownership slices.

Also extract the current pure `planned_logical_paths` filtering/path-assignment expression
from the opening of `convert_included_files` into
`plan_output_paths(plan: IncludedFileConversionPlan) -> tuple[IncludedFilePathAssignment, ...]`
in planning.py;
reuse canonical_included_file_lookup_path and plan_included_file_paths. Preserve requested
keys as reservations even when sources are unavailable, exact iteration order, and rejection
filtering. Do not duplicate the existing assignment algorithm or registry renderer.

### Dependency direction

`included_files -> planning -> models / included_file_paths / project_manifest records /
project_source_paths / diagnostic_models`; `included_files -> path_validation`; models has
standard-library imports only; path_validation has no conversion imports. Planner callbacks
invoke explicit existing operations; the planner never imports their concrete owner.
Later I02-I10 owners import these lower records/path validators directly. No lower owner
imports the facade or publishes private names through an initializer.

## Caller migration and test ownership

`final-source-inventory.json` lists current qualified monolith callers for all 20 moved
records, seven aliases, four path functions and six planning functions (37 symbols). Only `tests/test_included_files.py` directly references the moved records
or path validators outside that monolith. Its exact referenced records are IncludedCopyReceipt,
IncludedFileSource, IncludedNoOpSourceReceipt, IncludedOutputSetTransaction,
IncludedRecoveryRecordSizes, IncludedRegistrySnapshot, IncludedTreeEntry, IncludedTreeSnapshot;
its two leaf calls are recovery_relative_path and recovery_tree_entry_path. Migrate those
references and annotations to their final owner. The similarly named record in asset_registry
is a distinct definition and is not an I01 consumer.

Production converter.py and the Godot/public converter tests continue to import
IncludedFilesConverter from the supported facade. Existing embedded crash programs patch
the transaction phase hook, which remains in place. tests/test_managed_output_crash_recovery.py
has no moved-symbol consumer; remove it from I01's edit allowance. No existing workflow/native-gate selection needs renaming: those selections name the
retained transaction and output-containment classes. Root-owned manifest registration of
I01's new proof inventory is separate integration scope, not blanket permission for owner
edits to verification policy.

Move exactly these four complete existing test classes into
`tests/included_files/test_planning.py`, retaining their distinct setup/teardown helpers:
TestIncludedFilesManifestAccounting, TestIncludedFilesConverterNestedDirs,
TestIncludedFilesConverterSkipsYY, TestIncludedFilesConverterMissingFolder. These account for
489 physical lines / 983 structural units before destination imports. New focused
characterization can share those already moved fixtures; do not create a general test harness.
Keep Basic malformed/legacy fallback and native source-containment tests in the old file and
run them. The existing `_list_confined_directory` instance patch remains valid because that
method is not moved. Migrate the old test's D01 ConversionDiagnostic import directly to
diagnostic_models while its owner shrinks.

No temporary private compatibility exports are proposed. Every moved-symbol test uses its
canonical owner immediately. Remaining transaction/native private consumers stay for their
enumerated later slice; I10/R26 owns their final retirement.

The static source inventory contains 200 existing Included Files test methods: 190 remain in the
old module, ten move with their four complete classes. Preserve the class/method names and
assertion bodies; only the ten module-qualified identities change. Collect both explicit
module suites and discovery before/after, requiring a one-to-one mapping with no duplicate,
missing or accidental compatibility-export collection. The inventory names each old/new ID
and freezes method ASTs, physical spans and structural sizes. Largest moved method is
81 physical/153 structural; moved classes total 489 physical/983 structural before imports.

One additional direct consumer is `tests/fixtures/part2/corpus.json`: replace only
`tests/test_included_files.py::TestIncludedFilesConverterNestedDirs.test_normalizes_nested_packaged_paths`
with
`tests/included_files/test_planning.py::TestIncludedFilesConverterNestedDirs.test_normalizes_nested_packaged_paths`.
Root accepted this necessary source-reference migration and confirmed its current source at C. Preserve every other
JSON value and fixture payload. `TestPart2FixtureCorpus.test_resource_matrix_covers_required_milestone_areas`
checks it via `_assert_test_path_exists`; run that unchanged consumer.

The catalog is outside every R01/R10 hashed fixture root: the resource fixture is exactly
`tests/fixtures/part2/projects/resource_matrix`, not its metadata ancestor. Golden fixture
roots are separate. Therefore **no existing fixture fingerprint changes are required**.
Existing native exact IDs and payload evidence remain unchanged; root must enumerate any
new I01 manifest path/coverage registrations separately rather than rewriting old receipts.

## Exact allowed files (12)

1. src/conversion/included_files.py
2. src/conversion/included_files_parts/__init__.py (new, empty)
3. src/conversion/included_files_parts/models.py (new)
4. src/conversion/included_files_parts/planning.py (new)
5. src/conversion/included_files_parts/path_validation.py (new)
6. tests/test_included_files.py
7. tests/included_files/__init__.py (new, empty; preserves unittest discovery)
8. tests/included_files/test_models.py (new)
9. tests/included_files/test_planning.py (new)
10. tests/included_files/test_path_validation.py (new)
11. tests/fixtures/part2/corpus.json (the one source-reference string above only)
12. maintainability-baseline.json (allowed reductions only)

No edits to native receipt modules, native Included Files implementations, source resolver,
BaseConverter, existing assignment/registry owners, transaction codecs/hooks, lock/release
semantics, workflows, verification manifest, dependencies, versions or unrelated resources.

## Measured starting point and acceptance budgets

| Existing owner / symbol | Physical | Structural units | McCabe |
|---|---:|---:|---:|
| included_files.py | 12130 | 16958 | converter maximum 52 |
| tests/test_included_files.py | 12913 | 22695 | existing debt retained elsewhere |
| tests/test_managed_output_crash_recovery.py, read-only | 1713 | 2547 | unchanged |
| included_file_paths.py, read-only | 255 | 346 | unchanged |
| _included_file_conversion_plan | 58 | 92 | 4 |
| _plan_manifest_included_files | 81 | 114 | 9 |
| _declared_included_files | 91 | 150 | 10 |
| _manifest_diagnostic_is_included_file | 13 | 20 | 1 |
| _normalized_declaration_path | 3 | 13 | 1 |
| _declared_relative_path | 27 | 38 | 4 |
| convert_included_files | 541 | 701 | 52 |
| Four lexical path functions, total | 92 | 201 | max 4 |

Targets: models <=350 physical/600 structural; planning <=500 physical/780 structural;
path_validation <=150 physical/300 structural. Each new test module <=800 physical and <=1400 structural as design targets, with the
unchanged 1500/1500 test-module thresholds as absolute limits. Every production function
must be **<=150 physical AND <=150 structural**, every test/helper function **<=200 physical
AND <=200 structural**; C<=15, nesting<=4, parameters<=8 and all other R02 policy remain
unchanged. Tuple/operation structural units are a separate conservative size metric, not LOC.

The external read-only AST preflight (no rendered implementation) gives direct-call
`declared_included_files` 148 structural units from 150, `plan_manifest_included_files` 109
from 114, `declared_relative_path` 37 from 38, and `build_included_file_plan` 84 from 92 including
forwarding the three finite callbacks. Predicate 20 and normalization 13 are unchanged. The
largest projected nesting is 4 and parameter count 5. These prove plausible strict-function
headroom; actual typed imports/protocols and rendered modules must still pass the final
counter, Pyright and globally enforced Ruff. No formatter/line packing credit retires debt.
Original production owner should lose at least 500 physical and 700 structural units;
old test owner should lose at least 450 physical and 850 structural units. Treat these
as structural targets, not permission for line packing. Measure before approving if
the typed interface costs more than expected; do not raise a threshold or relocate debt.
The 541-line/C52 transaction coordinator is not claimed decomposed by I01; only its
small path-planning expression moves, with I08/I10 owning its lifecycle decomposition.

## Required characterization and proof

Before moving definitions, characterize the existing behavior; then update the tests to the
canonical owners during extraction. Add exactly the following finite methods in the three
new modules (no test framework or reusable fake filesystem); any extra method/file requires
scope refinement before editing:

| New class / module | New methods |
|---|---|
| TestIncludedFileModels / test_models.py | `test_records_preserve_fields_defaults_and_frozen_status`; `test_receipt_properties_and_transaction_equality_preserve_evidence`; `test_borrowed_bindings_and_lock_records_do_not_acquire_or_close` |
| TestIncludedFilePathValidation / test_path_validation.py | `test_recovery_relative_path_keeps_lexical_grammar_and_error_text`; `test_windows_recovery_components_reject_device_and_reset_forms`; `test_recovery_tree_entry_path_keeps_native_round_trip_containment`; `test_output_components_requires_exact_managed_root` |
| TestIncludedFilePlanning / test_planning.py | `test_manifest_shapes_keep_fallback_discovery_boundaries`; `test_declarations_keep_normalized_precedence_and_field_paths`; `test_resolution_and_unavailable_callbacks_keep_order`; `test_missing_declarations_reserve_discovered_and_output_names`; `test_output_assignments_preserve_collision_order` |

These 12 new methods plus the ten moved methods must fit the stated module/function budgets.
The resulting scoped collection is 212 methods: 190 retained, ten relocated and 12 new,
subject to confirming the source count with real baseline unittest collection at assignment.
Use explicit small input tables and existing domain records. Do not shrink old failure
assertions to fund new cases. Pure ownership/import-graph assertions may accompany these
finite tests or the external review inventory; no new generic architecture checker.

The cases must establish:

- Record fields/defaults/tuple arities, frozen status and copy/identity properties;
  transaction optional evidence remains excluded from equality and repr; mutable lock
  record stays data-only and cancellation uses one shared exception type.
- Missing/malformed/legacy YYP fallback; both IncludedFiles spellings; resource-form and
  rejected declarations; directory-plus-name filePath; exact normalized duplicate
  precedence; missing/rejected counts; disk-only additions and declared .yy payloads.
- Ordered manifest/source/unavailable findings, reasons and one collision warning per
  canonical group; requested-but-missing keys reserve output paths; collision suffix and
  file/directory conflict assignments remain byte-identical using the existing planner.
- Recovery path grammar (empty/dot/dotdot/NUL/backslash/absolute forms, Windows device,
  drive-relative, ADS/trailing dot/space/control forms); reconstruction cannot reset a
  native path or escape its root; output grammar still requires the managed root.
- Import direction and zero acquisition/I/O in models; no production/test use of the
  removed old private model/path names after migration, no private reexport initializer.

Compare immutable-base/candidate plans, ordered serialized diagnostics/logs, count tuples,
assigned paths, generated registry bytes and copied payload hashes on the same fixture
matrix. Preserve discovery calls/order, descriptor/fallback behavior, contained file-symlink
copy semantics and rejection of outside/replaced datafiles roots. Do not collapse warning
events into an unordered findings set or eagerly resolve all declarations before reporting.

Run Pyright --warnings to 0 errors/0 warnings and Ruff under all rules enforced at assignment.
After fixes run the three new modules, `tests.test_included_files`,
`tests.test_included_file_paths`, `tests.test_included_file_registry`,
`tests.test_part2_fixture_corpus`, and complete `tests.test_managed_output_crash_recovery`.
Run full unittest on a frozen candidate under exact Godot 4.7.2.stable.official.ed1daf0bf
and all five approved immutable external projects (three LTS fixtures, TCC and Monophobia),
recording exact env paths/commits, counts and every skip. Run the ratchet against the
immutable assignment parent and git diff --check. Include all six current `tests.test_files_ini_json_godot.TestFilesIniJsonGodotSmoke` methods
and `tests.test_resource_matrix_godot.ResourceMatrixEndToEndTests.test_cli_converts_full_fixture_and_exact_godot_loads_outputs`
with zero skips under the exact engine. `final-proof-inventory.json` records these IDs. Preserve current native Windows transaction/scale selections and Linux
bind-mount gate; actual affected native jobs must pass before I01 is verified. Modeled
Windows paths never count as NTFS execution. The proof inventory names the 14 actual
Windows Included Files methods already in the retained transaction/output-containment
classes, the unchanged dedicated 10,000-entry scale ID, the required Linux bind-mount ID,
and the local POSIX path method. The unchanged Included Files privileged bind-mount method
is also retained in the inventory; any privilege skip is explicitly **missing evidence**,
not a pass or new skip allowance. Root accepts that distinction for this models/path/planning
slice: I01 establishes no new snapshot/bind-mount implementation proof. I04/native snapshot
work must revisit actual privileged execution when it affects that owner. Do not widen these
12 files to modify the method, workflow or skip policy. Preserve the existing required
generic Linux crash-recovery bind gate without treating it as Included Files snapshot proof.
Check the required native methods executed rather than inferring
coverage from an overall job success with skips. Required scale runner remains the existing
`scripts.run_windows_included_files_scale_gate` (exactly one pass, zero skips); no new runner
or validation kind is proposed.

POSIX retains no-follow descriptors, no-replace moves, mount/identity checks and file plus
directory fsync. Included Files Windows uses its existing no-delete-sharing parent bindings,
file identity/reparse checks and MoveFileExW(MOVEFILE_WRITE_THROUGH); directory fsync returns
on Windows. This is separate from N01's receipt publisher and its NtSetInformationFile path.
Do not unify or describe the two Windows implementations as interchangeable.

Measure base/candidate planning elapsed time and peak memory for identical 10,000-entry
input with five fresh-process samples per revision on the approved native interpreter,
alternating base/candidate order after one unmeasured warmup each. Freeze the same ordered
10,000 manifest declarations and contained one-byte source files; hash their metadata/payload
inventory. Time only planning after setup/imports, preserving real resolver and isfile effects;
record total process peak RSS separately with native units, host/interpreter and CPU window.
Report medians, ranges and absolute deltas. Investigate repeatable >10% elapsed/RSS changes
outside sample variance; that threshold requests analysis, not a new performance allowance. Investigate material regressions without changing
native operations or worker bounds. No performance improvement claim follows from extraction.

Freeze exact files/hashes and receipts for independent review, then root reviews the actual
diff. The root entry above authorizes isolated implementation only; commits and integration remain root-owned after review.

## Ordered effect and lifecycle review checklist

The planner must load/forward manifest diagnostics first in the facade. A valid manifest
branch requires a YYP, no malformed-YYP diagnostic, and either IncludedFiles spelling,
a datafiles/GMIncludedFile resource or included-file rejected declaration. Use raw_data only
for existing membership tests. Declarations enter an insertion-ordered `setdefault` map:
IncludedFiles entries first, resources second, rejected findings last. Select raw field by
first present key path/filePath/filename; preserve directory-plus-name treatment.

Resolve each declaration before checking its relative-key duplicate; then account the key,
check datafiles family and file availability, and report that declaration's warning before
proceeding. Do not batch resolution or reorder findings. Discovery runs once on the original
reached branch; requested missing declarations suppress matching discovered additions.
`plan_output_paths` preserves requested keys followed by available source paths, filters only
existing ProjectSourcePathError cases and reuses the existing assignment algorithm. Keep
`assignments_by_source`, counters, collision reporting and every transaction statement in
the coordinator except the agreed small planning expression.

The lifecycle fingerprint inventory freezes acquisition, release, worker, recovery, stage,
commit, rollback, snapshot and report owners. I01 may only rename moved record/type/path
references there; keep statement/control-flow/exception/hook ordering and native API calls.
The convert method may additionally replace its agreed opening path-planning expression.
No behavioral fix for #877 is inferred from passing normal cancellation/recovery tests.

## Root-owned integration and final acceptance

Before assigning the isolated owner, root must accept these 12 files and name the post-R04
immutable source. Refresh this inventory and destination size estimates; preserve any new
R04 import grouping and R02 retained-debt evidence from that parent. Root updates
contracts.json/campaign notes and, if required, registers exact I01 method/path/coverage
ownership in architecture-verification.json without changing old fixture fingerprints,
existing payload outcomes, coverage floors or skip allowances. Those are not implementation
owner edit permissions. No workflow edit is presently required.

One implementer characterizes, extracts and verifies; freeze the complete patch, exact
changed-file SHA256 inventory, source/collection mapping, native logs and before/after
performance transcript. Independent reviewer then root read the actual frozen diff and
return APPROVE/REQUEST CHANGES. Final CI must cover the exact integrated revision, including
actual native methods listed above, before I01 is verified. Commit/push/PR/integration remain
root-owned actions; this implementation assignment does not authorize owner commits or integration.
