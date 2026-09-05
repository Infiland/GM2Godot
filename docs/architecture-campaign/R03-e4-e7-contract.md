# R03 exact E4/E7 contract

Task R03 / #795. Source basis is immutable combined commit 6066856144124a18c96521bab45ec1eca986c47f, including R10 merge 91a33c14803f889e2826f7088a79c0693455b57d and N01 correction b06c15bdfcd4299bde8fc148c4e3232ad2cf1a5d. Root selected this fixed implementation basis; final N01 integration proof is still a prerequisite for R03 integration. Read-only refresh scanned exactly 94 inputs: the original 62 finding owners plus changed/new Python inputs since edfe6df. No repository file, index or branch was changed. This document supersedes the earlier R03-contract-proposal.md; implementation remains unauthorized until root accepts this precise contract.

## Evidence and scope

199 findings in 62 files: 188 E402 findings in 61 test modules; 3 E731 findings (2 in production chmod_exact, 1 assigned test runner); 8 E741 findings in three test modules. Sixty E402 owners have obsolete top-level sys.path insertion. The remaining owner, tests/test_ds_collections_godot.py, imports write_gml_runtime after its Godot lookup. R01 test_gml_transpiler and D01 test_base_converter bootstrap removals are already incorporated and are not R03 work.

All 199 findings, locations and 62 source hashes are unchanged; all 62 owners are byte-identical to the original edfe6df basis. R10/N01/D01/C01 changed/new owners introduce no additional E4/E7 findings into the bounded delta. Exact allowed finding cohort:

- src/conversion/anchored_artifacts.py
- tests/conversion/events/test_alarm_events.py
- tests/conversion/events/test_animation_events.py
- tests/conversion/events/test_async_audio.py
- tests/conversion/events/test_async_dialog.py
- tests/conversion/events/test_async_http.py
- tests/conversion/events/test_async_image_loaded.py
- tests/conversion/events/test_async_networking.py
- tests/conversion/events/test_async_platform_events.py
- tests/conversion/events/test_async_save_load.py
- tests/conversion/events/test_async_sound_loaded.py
- tests/conversion/events/test_async_steam.py
- tests/conversion/events/test_async_system.py
- tests/conversion/events/test_broadcast_message.py
- tests/conversion/events/test_cleanup_event.py
- tests/conversion/events/test_collision_events.py
- tests/conversion/events/test_create_event.py
- tests/conversion/events/test_destroy_event.py
- tests/conversion/events/test_draw_events.py
- tests/conversion/events/test_gesture_events.py
- tests/conversion/events/test_keyboard_events.py
- tests/conversion/events/test_lifecycle_events.py
- tests/conversion/events/test_mouse_events.py
- tests/conversion/events/test_path_ended.py
- tests/conversion/events/test_registry.py
- tests/conversion/events/test_room_boundary_mappings.py
- tests/conversion/events/test_script_features.py
- tests/conversion/events/test_step_events.py
- tests/conversion/events/test_user_events.py
- tests/conversion/events/test_wallpaper_events.py
- tests/test_asset_registry.py
- tests/test_cli.py
- tests/test_converter.py
- tests/test_ds_collections_godot.py
- tests/test_event_mapping.py
- tests/test_extension_registry.py
- tests/test_fonts.py
- tests/test_gml_api_manifest.py
- tests/test_gml_manual_scope.py
- tests/test_gml_runtime.py
- tests/test_gml_runtime_segments.py
- tests/test_gml_source_maps.py
- tests/test_golden_conversion.py
- tests/test_included_files.py
- tests/test_monophobia_conversion.py
- tests/test_notes.py
- tests/test_objects.py
- tests/test_part2_fixture_catalog.py
- tests/test_part2_fixture_corpus.py
- tests/test_project_godot.py
- tests/test_project_manifest.py
- tests/test_project_settings.py
- tests/test_resource_index.py
- tests/test_rooms.py
- tests/test_runtime_managers.py
- tests/test_script_generator.py
- tests/test_shaders.py
- tests/test_simple_topdown_conversion.py
- tests/test_sounds.py
- tests/test_sprites.py
- tests/test_tcc_conversion.py
- tests/test_tilesets.py

## Finite changes and ownership

1. Remove the 60 top-level bootstrap guards and their sys.path.insert calls. Remove now-unused sys/os/Path imports only where their last actual use disappears. Keep every real fixture/process/cwd constant and place it after imports, preserving dependency order. PROJECT_ROOT remains needed in exactly eight owners: test_asset_registry, test_cli, test_golden_conversion, test_included_files, test_part2_fixture_catalog, test_part2_fixture_corpus, test_project_settings, test_tcc_conversion. test_asset_registry must move AUTHORED_SEQUENCE_FIXTURE together with PROJECT_ROOT. Retain sys in test_asset_registry, test_cli, test_included_files and test_project_settings because it has other actual uses. Delete obsolete bootstrap comments with the corresponding code.
2. In test_ds_collections_godot move only the source import before _find_godot_binary and its module-level invocation. Keep the lookup function, its environment/PATH/macOS precedence, its invocation, skip decorator, generated smoke source and runtime assertions intact. No T03 Godot helper consolidation or broader test split here.
3. In VerifiedDirectory.chmod_exact use functools.partial (from the existing functools import owner) for the two descriptor callbacks: partial(fchmod, descriptor) and partial(os.chmod, descriptor). Preserve callback selection order, the already-open descriptor, opened_mode rollback argument, identity/single-link checks, expected_current_mode policy, error notes and finally close. No transaction/path/ownership refactor. fchmod already refers to a selected local callable; the os.chmod branch becomes an explicit selected-callable capture rather than a later attribute lookup on rollback. This internal binding detail must be accepted/documented and covered by callback/race proof. An alternative nested callback preserving the late attribute lookup was measured and rejected: it raises chmod_exact C901 from 15 to 16, creating new debt. Do not add a generic adapter/class or waiver to hide it.
4. Change only the assigned test_converter runner lambda into one uniquely named local def runner returning self.converter._run_base_converter(failing), preserving late closure/method lookup and exception identity. The existing ConversionStepResult import can annotate its return. Do not alter unassigned lambdas or transaction test setup.
5. Rename the eight Python comprehension variables l to log in tests/test_fonts.py (4), test_project_settings.py (2), test_sprites.py (2), including the corresponding load occurrences in that comprehension. No substitutions inside generated GDScript/text and no assertion/filter/order changes. Alpha-normalized AST comparison should be identical for these loops.
6. Enable complete E4 and E7 families in pyproject.toml alongside existing E9, F and C90; keep the C90 ceiling, exclusions and target-version unchanged. Add E4,E7 to the existing isolated tracked-input command in code-health.yml (which already ignores noqa, gitignore and force-exclude). Preserve C01 terminal jobs and its validation-section-aware documentation test. No workflow graph, pin, dependency lock or release edit belongs to this cohort.
7. Update exact configuration/workflow assertions and contributor guidance. Retire only measured debt rows and tighten real size evidence. Do not mark all test packaging/helper work or broad #795 work complete.

Additional exact allowed files for enforcement/proof/documentation (10 additional files; 72 total): .github/workflows/tests.yml only for the finite native commands below; pyproject.toml; .github/workflows/code-health.yml; tests/test_documentation_health.py; tests/test_maintainability_metrics.py; new tests/test_anchored_directory_modes.py; CONTRIBUTING.md; docs/wiki/Contributing-and-Testing.md; maintainability-baseline.json; todo-list/07-testing-codebase-improvements.md. Root owns campaign contract/ledger updates and any serialized N01 manifest inventory. No source files outside the 62-file cohort, no tests/test_ci_workflows rewrite, and no other helper/package additions.

## Inputs, outputs, lifecycle and dependencies

Test imports remain supported via python -m unittest, unittest discovery and python -m tests.<module> from repository root with PYTHONPATH absent. Remove process-wide test import-path mutation without adding sitecustomize, conftest, a test import bootstrap or an installability framework. Direct script-path execution is not promoted as a supported replacement command; root documentation already uses module entry points.

Production input/output is the existing chmod_exact(name, identity, mode, require_single_link, expected_current_mode) contract. The method returns int: it returns current_mode when the requested mode already matches, and final_mode after successful mutation and final verification. opened_mode is the descriptor rollback argument, not the return value. Preserve no-op evaluation before expected_current_mode validation, exact opened descriptor identity, callback choice, rollback/error precedence, descriptor close and post-mutation identity verification. Neither callback escapes chmod_exact. No generated artifacts, diagnostic schemas or public exports change.

Dependencies: approved R01/R02/D01/C01; serialize with R10/N01 because source/manifest tests and workflow/config assertions overlap. The actual fixed starting commit must include their accepted changes. This proposal is not permission to cherry-pick older file snapshots over later work.

## Enforcement and behavior tests

- Extend the existing exact Ruff configuration assertion to [E4,E7,E9,F,C90], with no ignore/per-file-ignore allowance and unchanged exclusion set/ceiling. Extend the exact tracked lint command assertion to E4,E7,E9,F, retaining --isolated, --ignore-noqa, --no-respect-gitignore and --no-force-exclude. Preserve C01's workflow-success partition.
- Extend the existing pinned-Ruff measurement test with E731/E741 negative inputs and assert both metric rows alongside E402. Add a focused actual-Ruff test using the project configuration on temporary synthetic E401/E402/E701/E731/E741 inputs; all requested diagnostics must be produced, including representative newly enforced rules with no current debt. The isolated measurement's existing ignore-ALL/gitignore/noqa fixture continues to prove bypass attempts fail. Keep these in tests/test_maintainability_metrics.py; no new checker framework.
- For the 60 bootstrap removals, fresh subprocess imports from repo root with PYTHONPATH/PYTHONHOME removed must leave sys.path unchanged and resolve source modules inside the selected checkout. Exercise both unittest module loading and unittest discovery; preserve all collected test IDs except the explicit lambda local helper is not a test. Module execution uses -m, without direct-file bootstrap fallback.
- New small tests/test_anchored_directory_modes.py contains only focused descriptor callback characterization: selected callback receives the opened descriptor and requested mode; a post-chmod identity/link race restores opened_mode through the same descriptor; expected-current-mode/no-op branches preserve current behavior; failure paths close the descriptor and preserve the established error/restore-note precedence. Exercise the fd-capable selection using real native file descriptors and clearly identify any selector modeling. Retain the existing extensive hardlink/fchmod/path-chmod race tests unchanged and run them in full. Unsupported native mechanisms must be reported explicitly as missing R03 proof. The new module has the four exact method IDs in R03-native-proof-inventory.json; no production API changes or private-access bypasses are allowed.
- Preserve generated GDScript strings byte-for-byte in the E741 owners and DS smoke fixture. Compare test ASTs after excluding only removed bootstrap nodes, relocated constants/imports and exact alpha/local-lambda changes; inspect any additional difference.
- Run native Pyright 0 errors/warnings, normal Ruff and complete isolated tracked-input E4/E7 checks, exact cohort tests plus new focused mode/global-policy tests, full unittest on the approved runtime/exact Godot/pinned projects, R02 ratchet and diff check. Production callback changes require the exact native artifact-mode methods and new POSIX descriptor methods below. N01 receipt IDs do not exercise chmod_exact and cannot supply this evidence. No blanket skip waiver.

The earlier missing-Ruff CI prerequisite is resolved in the fixed source: Tests installs pinned Ruff 0.15.22 under the existing platform constraint and requires Ruff in its environment receipt. R03 preserves that environment ownership. No lock or dependency change is needed.

## Before/after metrics and review gates

Exact in-memory proposed cohort projection (source files untouched) removes all 199 E4/E7 findings and leaves zero E4/E7/F findings in the 62 projected files. Physical lines 54048 -> 53789; final-R02 structural units 105152 -> 103879. This is a bounded projection, not an implemented gate pass. Reductions come from obsolete bootstrap and lambda code removal; unrelated whitespace is not architectural credit. Only DS smoke gains one separator line while remaining 205 physical/231 structural, below all budgets. All other projected modules are non-growing in both measures.

chmod_exact: module 3486/5908 -> 3480/5906 physical/structural; function116/244 -> 110/242; C901 remains15 and both E731 rows disappear. Existing function/module structural debt remains; R03 does not claim to split the transaction owner. The rejected nested-helper variant would preserve5908 module structural units but add C90116 debt.

New ordinary modules/functions must satisfy existing <=800 module and <=150 function physical/structural units, complexity<=15, nesting<=4 and parameters<=8. New test module<=1500 and functions<=200 physical/structural units; target the focused mode module comfortably below 500 units. Existing large test modules may only shrink or retain permitted measured debt. No changed thresholds, baseline reset, extra exclusions, rule ignores, noqa/type suppressions or move allowances.

One isolated implementer after exact contract acceptance; separate read-only reviewer then root reads the actual final diff. Completion: exact cohort gone; E4/E7 globally enforced and bypass tests green; import behavior and collected tests preserved; callback/native transaction proof passes; Pyright/Ruff/ratchet/full suite pass on immutable candidate; root integrates the reviewed revision. No temporary adapter or postponed E4/E7 cleanup remains in R03. T03 must re-inventory its separate remaining responsibilities afterward.

Evidence: R03-combined-inventory.json (94 current hashes and 72 allowed files), R03-projection.json plus projected-source/ and project-cohort.py (exact external transformation), R03-collection-before.json (fresh-process module/discovery inventory; no test execution), R03-native-proof-inventory.json (exact native methods and source/AST hashes), cohort.json (all exact findings/locations and immutable commits), bootstrap-inventory.json (60 patterns plus DS exception and retained roots/imports), chmod-strategy-preflight.json, cohort-preflight.json. None is a substitute for implementation review or final native CI proof.


## Exact callback behavior accepted for implementation

The existing functools import becomes `from functools import lru_cache, partial`.
`partial(fchmod, descriptor)` preserves the already-selected local fchmod callable
and live descriptor. `partial(os.chmod, descriptor)` selects the then-current
callable once for the initial mutation and any rollback. The old lambda looked up
os.chmod again during rollback. This one internal binding change is explicit;
it must be accepted with this contract, not disguised as AST-equivalent behavior.
Neither callback escapes. Selection and os.supports_fd membership are not atomic;
this task adds no thread-safety guarantee.

The forced fd-capable branch test must save the real native os.chmod callable,
model fchmod absence and supports_fd membership for a typed observer, and delegate
actual os.chmod on the same opened descriptor. After the requested mutation, the
observer rebinds os.chmod to a sentinel and creates a real hardlink (or forces the
existing identity check through bounded instrumentation). The call must fail at
the changed-file check, restore opened_mode through the originally selected
observer on that same still-live descriptor, and close it. The sentinel must not
run. Check descriptor invalidation before any unrelated open can reuse its
number. Restore patched globals reliably. This distinguishes selection modeling
from real native descriptor operations. Existing fchmod and path-chmod race tests
remain unchanged and execute as additional characterization.

The four new methods in TestAnchoredDirectoryModes cover, respectively: both
successful descriptor selections and int final_mode; forced rebind/rollback;
no-op current_mode before expected-mode validation plus mismatch rejection;
and table-driven immediate failure, rollback Exception note, rollback
BaseException propagation and finally-close exception precedence. Use real
native descriptor closure under instrumentation. A close-error injection must
close the descriptor before raising its sentinel so the proof does not leak an
OS resource. No new general callback framework, fake-only filesystem proof,
production helper or suppression is allowed. Keep the small new test module
comfortably below 500 physical/structural units; all ordinary R02 limits remain.

## Exact native CI and collection proof

R03-native-proof-inventory.json is the authoritative finite method list. Add one
explicit `python -m unittest -v` command in each existing Tests native job, after
its established environment setup, with these exact existing/new method IDs:

- Linux/test: the two POSIX artifact-mode IDs plus the four new descriptor IDs
  (6 methods, 0 skips).
- macOS/macos-managed-output-transactions: the same 6 methods, 0 skips. This fixes
  the present coverage gap: its managed-output module list does not include the
  actual artifact/manifest/diagnostic mode owners.
- Windows/windows-artifact-transactions: the two existing native readonly
  artifact IDs (2 methods, 0 skips). Preserve its existing complete artifact
  transaction module command. Those methods use actual native Windows behavior;
  no forced POSIX descriptor support is claimed on Windows.

This is the only additional Tests workflow scope. Preserve all existing jobs,
needs, setup versions, dependency verification, N01 receipt gates, validation
commands, artifacts and terminal success checks. Do not add a new runner,
manifest kind, artifact schema, polling, dependency or framework. Exact names in
commands make deletion/misnaming fail collection. Completion additionally
requires matching verbose CI result lines with every expected method, counts
6/6/2 and zero skips/errors/failures. A skipped or absent method is missing proof
and blocks completion even if ordinary unittest exits zero. Root reviews the
exact-revision CI evidence and OS/runtime context. Do not relabel the diagnostic
test's early-return or set-ID unsupported cases as full native POSIX proof;
required POSIX hosts must support both fchmod and native os.chmod(fd, mode), and
the existing exact-mode half must execute.

Exact existing native IDs:

- `tests.test_conversion_manifest.TestConversionManifest.test_existing_and_new_artifact_modes_remain_exact`
- `tests.test_diagnostics.TestDiagnosticCollector.test_new_private_modes_and_existing_exact_modes_are_preserved`
- `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_windows_readonly_hardlink_is_rejected_without_alias_mutation`
- `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_windows_single_link_readonly_publish_and_restore`

Exact new POSIX IDs:

- `tests.test_anchored_directory_modes.TestAnchoredDirectoryModes.test_descriptor_callbacks_return_final_mode`
- `tests.test_anchored_directory_modes.TestAnchoredDirectoryModes.test_fd_chmod_rebinding_keeps_selected_rollback_callable`
- `tests.test_anchored_directory_modes.TestAnchoredDirectoryModes.test_noop_and_expected_mode_guard_precedence`
- `tests.test_anchored_directory_modes.TestAnchoredDirectoryModes.test_descriptor_failures_preserve_errors_and_close`


Keep all existing methods in tests.test_anchored_artifacts,
tests.test_conversion_manifest and tests.test_diagnostics unchanged and run those
modules in full in the local native suite and existing Linux/Windows cohorts.
The inventory explicitly lists the 11 modeled readonly/hardlink/fchmod/path-chmod
race methods; their source and AST hashes must not drift. Their modeled Windows
policy does not replace the 2 native Windows methods.

The fixed-source collection contains 1,273 tests in the 61 affected modules and 162 tests in the three unchanged artifact proof modules; module and discovery IDs match, with zero test bodies executed. R03-collection-before.json and R03-artifact-collection-before.json preserve the exact lists.

Before implementation and again at candidate, collect the 61 affected test
modules in fresh subprocesses with PYTHONPATH/PYTHONHOME absent, both through
module loading and unittest discovery. Match all baseline IDs exactly; then
require exactly the four intentional new IDs from the new mode module. Source
module origins must resolve inside the chosen checkout. Record sys.path before
and after imports; current obsolete guards may insert the absolute root in the
baseline python -c process, but the candidate must leave sys.path unchanged.
Also collect the three unchanged artifact proof modules and compare their exact
IDs. No renamed, disappeared or duplicated test passes this check. Preserve all
generated string constants byte-for-byte and compare the bounded projected AST
against source with only the enumerated transformations permitted. This finite
external evidence is a review tool, not a new repository analyzer.

Remaining prerequisites are root contract acceptance, implementation on the
fixed source, independent/root actual-diff review, native/full/static/gate proof
on the candidate, verified N01 integration and root integration. Existing native
N01 b06 receipts are real prerequisite evidence but receive no chmod coverage
credit. No further broad audit or scope expansion is required by this proposal.

The two additional policy test modules currently collect 37 tests (R03-policy-collection-before.json). Preserve those IDs and add exactly `tests.test_maintainability_metrics.TestMaintainabilityMeasurements.test_project_config_enforces_complete_e4_e7_families` for the new real-Ruff project-family test. The pinned-Ruff bypass method and documentation assertions are edits to existing methods. Across these bounded collections, the only intended new test IDs are this policy method plus the four descriptor methods. Any additional test or changed ID requires an explicit contract refinement.

The two existing policy owners have structural sizes 823 (documentation_health) and 1292 (maintainability_metrics), leaving 677 and 208 units before the unchanged 1500-unit test-module limit. The source projection does not consume that headroom. The new descriptor module remains below 500 units; production chmod module/function debt remains and is reduced only by the measured two units. Current R10/N01 source/test additions do not change any accepted budget and are not new R03 edit owners.

## Root acceptance

APPROVE. Root read the actual chmod implementation, all four existing native methods, the complete contract and frozen evidence after independent review. The explicit selected-callable binding change and exact 72-file scope are accepted. Implement in GM2Godot-080-e4-e7 on dev/080-e4-e7 from approved source 6066856. Add the Windows exact-ID command before the existing output-reader step, preserving its established command inventory. Root owns this contract, PLAN.md, contracts.json and LEDGER.md; the implementation owner owns only the 72 enumerated source/policy/test/documentation paths. No new manifest kind or runner is authorized. Required proof and verified N01 integration remain mandatory before R03 integration.
