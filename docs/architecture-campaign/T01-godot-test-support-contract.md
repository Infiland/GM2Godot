# T01 / #867 — exact Godot test discovery: finite contract proposal

Status: ACCEPTED by root. This entry supersedes the historical proposal/acceptance-pending wording below. Fixed implementation base is verified R04 cleanup merge `feb22c30ea13475116c0190e302df0fc7fe08383`; its exact PR/merge/native proof is complete. All 76 current inputs were reverified at assignment, including the reviewed strict-policy CONTRIBUTING paragraph. The original accepted corrected contract SHA256 is `c1ac4605800e5afbc4a63e29fd79978ee7035cec2ab254d9af6c2807163adbb2`.

Sole implementer: `audit_policy_tests_docs` in `/Users/infi/Documents/Github/GM2Godot-080-godot-test-support`, branch `dev/080-godot-test-support`. Independent actual-code reviewer: `audit_transactions_cli`, then root. Root accepts the exact combined-stream policy and six-site changes, finite 54-path scope, corrected 76-method origin-bound external proof, twelve read-only canonical runtime consumers, and unchanged production/parity validator. Of the 54 scoped paths, `maintainability-baseline.json` is root-only; the implementer owns the other 53. Root owns this contract, contracts/ledger, all shared verification/coverage/version/release metadata. No source or workflow expansion is authorized.

Author the twelve helper characterization methods before migrating old test consumers. Preserve all stated special probe/decorator timings and assertions. Native helper proof must execute all twelve methods without skips on Windows/macOS. Heavy full/runtime/performance runs use root's reserved queue. Independent/root reviews and exact integration proof remain required; this is implementation authorization, not completion.


Status: READ-ONLY PROPOSAL. No implementation, repository edit, commit, PR or acceptance is implied. This replaces the provisional T01 inventory and generic roadmap wording only after root acceptance.

## Source and precise problem

The source is frozen R04 owner `ef758360d91e96f2df0a72fc17769e7e5ed77c09`, observed through its documentation-only integration child `fef28b6cc2f5dc7afd623d24a2b506e9acd46867`. `cohort-inventory.json` freezes each owner byte hash, method IDs/ASTs, deleted finder definition, exact replacement statements and both physical/structural metrics. `source-caller-proof-inventory.json` freezes production/CI/measurement inputs and read-only consumers. Root must choose the actual post-R04-and-bridge-retirement implementation base and refresh these hashes and metrics before dispatch. Any overlapping change requires a reviewed delta, not silently substituted evidence.

There are 43 local finder definitions totaling 535 physical lines. They implement the same environment → PATH `godot` → neutral macOS application path policy as the existing production owner `src/conversion/godot_validation.py::find_godot_binary`; six mocked cases across all 44 actual definitions (264 executions) preserve both result and filesystem/PATH query order. The three syntactic finder variants are not three policies. There are 15 actual Godot `--version` calls in nine files. Three of those files already contain local finder duplicates; the union is 49 test files. Root's sixteenth search hit, `tests.test_cli.TestCLIReports.test_module_entrypoint_prints_version`, invokes Python's `-m src.cli --version`, is unrelated and is excluded.

The 49 owners contain 112 existing test IDs. There are 64 actual runtime test call sites to migrate, including the resource-matrix test's one private version-validation helper. Ten current wrong-build checks call `skipTest`, permitting unsuitable engines to masquerade as optional absence; five already fail. Existing runtime GDScript, f-strings, banners, value/evaluation-order assertions, fixture setup, conversion assertions and generated-code validation remain in their test owners.

## Ownership, typed API, dependencies

Keep `src/conversion/godot_validation.py::find_godot_binary` unchanged as the sole application discovery owner. Add exactly one test-only helper owner `tests/godot_test_support.py`, with:

```python
require_exact_godot(godot_binary: str | None = None, *, timeout: int = 10) -> str
```

It returns the same selected string without resolving, normalizing or rewriting it. `None` means call the existing production finder once. A discovered `None` raises `unittest.SkipTest("Godot binary not available")`. A supplied string bypasses discovery, including an empty or invalid string; it is never replaced through `or`/fallback. A selected missing, directory, inaccessible or non-executable file reaches the native process-launch error. Do not change the production finder's existing invalid-`GODOT_BIN` fallback or add executable/path acceptance policy there.

Run `[selected, "--version"]` with `capture_output=True`, `text=True`, `check=False`, and the passed timeout. Strip the concatenation `stdout + stderr`. Nonzero status raises `AssertionError` with status and output; an exact-build mismatch raises `AssertionError` with expected/observed output. `OSError`, `TimeoutExpired` and text-decoding errors propagate; do not turn them into skips, retry or wrap them in a new exception hierarchy. The sole helper pin is `4.7.2.stable.official.ed1daf0bf`; existing test-local banner assertions/constants remain because they validate the actual later runtime output. No `__all__`/finder re-export chain, protocols, cache, process manager, context manager, project builder, command wrapper or dependency is added.

Dependency direction: migrated tests → test helper → existing production finder; test helper → standard library. No application or tool imports tests. Actual before/proposed graphs retain the same 14 static cycles and one eager cycle, with no added cycle or reverse test-helper edge. Those existing cycles are not claimed fixed here. T01 depends on verified R01 and completed R04 including its separate bridge retirement; later task ordering/overlap is root-owned.

## Explicit behavioral acceptance decisions

The common output rule is intentionally a test-policy change, not byte-for-byte probe equivalence. Eight old probes merge stderr into stdout; six compare only stdout; one concatenates stdout and stderr. All 15 existing timeout values are retained: ten at 10 seconds, four at 30 seconds, one at 20 seconds. The common concatenation rejects extra stderr text at the six stdout-only sites, and also accepts an exact banner solely on stderr there. It does not preserve cross-stream interleaving order. Root must accept this single explicit combined-output policy or request a precise revised rule; do not silently add a mode parameter/framework. The probe output must otherwise exactly equal the pinned build after `strip()`.

Ten old wrong-version skips become failures. The other five remain failures. Forty-nine finder-only sites gain a bounded 10-second exact-build probe before their old first runtime work. There is no claim of unchanged subprocess count or runtime cost: 15 probes become 64, adding 49 launches when all affected runtime tests execute. No result is cached across tests.

Most bodies replace their old finder/optional-absence block with the helper at the same position. The ten existing leading finder/version blocks collapse to one call at the same position. Preserve these special sites explicitly:

* `TestDSCollectionsGodotSmoke`: retain module-global `godot_binary = find_godot_binary()` and the existing class skip predicate. Do not probe a version during import or decoration. Replace the method's initial non-None assertion with `selected_godot_binary = require_exact_godot(godot_binary)`; its one launch uses that local string. Under the existing class guard the captured global is non-None; it is not rediscovered. Module-global name and class skip timing remain. The method stays 173 physical/187 structural in the preview.
* `ProjectPreflightGodotTests.test_cli_generated_project_opens_in_exact_godot_4_7_2`: retain the environment decorator and the initial `os.environ["GODOT_BIN"]` read. Probe the explicit path at the old probe location, after fixture/conversion assertions. Its second autoload test has no duplicate probe and remains unchanged; its exact build is supplied by CI's install gate.
* The exact-runtime `TestUpdateProjectSettingsFromManifest.test_godot_reads_generated_settings_at_canonical_project_settings_paths` and `TestConvertIconFallback.test_exact_godot_reads_icon_from_fresh_cli_conversion` methods: retain their environment decorators, fixture/conversion work, environment reads and old 30-second probe locations. Do not move the read earlier.
* Resource-matrix: retain the caller's existing `if not godot_binary: return` after its non-runtime conversion assertions. This method still provides conversion-only evidence without the environment and must not then be counted as runtime proof. Retain the private helper's `os.path.isfile` assertion before the 30-second version probe and all resource/boot checks afterward. The required T01 environment prevents that optional runtime branch from being omitted in completion proof.
* Stale-output integration: retain its import-time finder decorator, conversion/partial-outcome assertions, then its fresh body finder call and `assert godot_binary is not None`. Probe the explicit resulting string with timeout 20 at the existing location. Removing that assertion or giving `None` to rediscovery would change the existing race/absence behavior and is excluded.

`cohort-inventory.json` records all exact call-site method names, timeout/stream modes and replacement statement spans; it is the finite migration inventory. Preserve argument evaluation order and all non-boundary statements. No helper import may launch a process: actual external collection of the 112 old IDs passes on baseline and preview with `subprocess.run` patched to reject any collection-time call.

## Read-only canonical consumers and excluded owners

There are 12 actual runtime methods across nine already-canonical files outside the 49-file union, plus the production-finder unit characterization method. Their exact IDs, AST hashes, line locations, decorators and CI owner are in `source-caller-proof-inventory.json::readonly_canonical_consumers`.

* Four one-method string smoke modules (`verbatim_strings`, `quoted_struct_keys`, `debug_strings`, `template_strings`) already use the canonical finder. Their normal optional absence blocks remain. The exact Godot smoke workflow selects them through `test_*_godot.py` after archive checksum and exact `--version` checks.
* Golden conversion's one method and four actual-runtime `test_godot_validation` methods retain their finder skip decorators and production validator calls. The smoke workflow explicitly runs both modules after the same exact install gate. The separate finder unit test exercises the production API with a mock and is not runtime proof.
* SimpleTopDown and TCC retain their optional finder decorators; Monophobia retains its explicit required-engine assertion. Their fixture classes also require the corresponding pinned checkout. The TCC conversion workflow installs and verifies exact Godot before explicitly selecting all three modules.

Adding the new helper to these 12 methods would make ad hoc local version selection clearer, but would add new probes/ownership changes without removing any accepted duplicate. It provides no new exact-engine CI guarantee: both workflows already pin/check the build and export `GODOT_BIN`. Keep these files read-only in initial T01 unless root explicitly expands the exact scope after reviewing that tradeoff. Do not claim that their local fallback execution independently checks the exact build.

Keep `scripts/conversion_parity_inputs.validate_runtime` unchanged. It requires the manifest/environment executable, verifies Python/platform/machine first, rejects missing/non-executable paths, and checks explicit stdout/version/status without any finder fallback. Its `--version` call currently has no timeout; record this for T02 subprocess planning only. T01 neither fixes it nor weakens its guarantees. No CLI version code, native output reader, transaction/process cleanup, fixture payload or production generated-code owner changes.

## Exact allowed files and bounded destinations

Proposed implementer scope is exactly 54 files: the 49 below, the two new test-support files, CONTRIBUTING, the existing baseline, and one existing native workflow. The workflow scope is only adding `tests.test_godot_test_support` to the existing macOS and Windows unittest module lists; Linux's full discovery already selects it. Preserve every current method/job/guard/dependency. Root accepted this exact small workflow extension in principle. `native-command-delta.json`/`.patch` freeze its two additions, original workflow hash and resulting hash. Full contract review and implementation authorization remain pending.

```text
tests/test_array_delete_godot.py
tests/test_array_foreach_godot.py
tests/test_array_sort_godot.py
tests/test_assignment_index_postincrement_godot.py
tests/test_async_http_godot.py
tests/test_async_queue_godot.py
tests/test_audio_runtime_godot.py
tests/test_authored_particles_godot.py
tests/test_bound_method_context_godot.py
tests/test_buffers_godot.py
tests/test_cameras_display_godot.py
tests/test_collision_events_godot.py
tests/test_collision_queries_godot.py
tests/test_draw_basic_godot.py
tests/test_draw_event_dispatch_godot.py
tests/test_draw_sprite_text_godot.py
tests/test_draw_surfaces_godot.py
tests/test_ds_collections_godot.py
tests/test_ds_file_buffer_network_parity_godot.py
tests/test_event_scheduler_godot.py
tests/test_files_ini_json_godot.py
tests/test_flex_panels_godot.py
tests/test_game_input_godot.py
tests/test_gpu_draw_state_godot.py
tests/test_instance_registry_godot.py
tests/test_layers_runtime_godot.py
tests/test_math_random_godot.py
tests/test_motion_helpers_godot.py
tests/test_named_constructor_inheritance_godot.py
tests/test_networking_godot.py
tests/test_os_debug_gc_godot.py
tests/test_particles_runtime_godot.py
tests/test_paths_motion_godot.py
tests/test_physics_runtime_godot.py
tests/test_platform_services_godot.py
tests/test_precise_collision_masks_godot.py
tests/test_project_preflight_godot.py
tests/test_project_settings.py
tests/test_resource_matrix_godot.py
tests/test_room_game_flow_godot.py
tests/test_runtime_managers_godot.py
tests/test_script_runtime_godot.py
tests/test_script_top_level_enum_godot.py
tests/test_script_top_level_initializers_godot.py
tests/test_sequences_timelines_godot.py
tests/test_shader_runtime_godot.py
tests/test_shaders_godot.py
tests/test_stale_managed_output_invalidation.py
tests/test_time_alarms_godot.py
tests/godot_test_support.py
tests/test_godot_test_support.py
CONTRIBUTING.md
maintainability-baseline.json
.github/workflows/tests.yml
```

The concrete completion proof is the 64 exact affected runtime IDs plus the 12 proposed helper IDs, with zero allowed skips. `runtime_proof_plan.py` freezes a finite external invocation of the existing `run_gate` API after `validate_parity_inputs` checks the unchanged R01 runtime/fixture contract. It reuses that declared prerequisite definition with only the external proof label, exact 76-method selection and empty skip allowance replaced. Invoke the corrected external harness from the exact candidate checkout, with `PYTHONPATH` set to that checkout's absolute path; the `--root` value must match both. The harness rejects mismatches before importing campaign scripts, checks every loaded `scripts`/`tests` module against that checkout's actual `.py`/`__init__.py` path, and preimports the 50 declared test modules before runtime validation. It rechecks all such module origins after execution and records the paths, cwd and PYTHONPATH in the receipt. An identical source file imported from a different checkout is rejected. No sys.path insertion, path repair, fallback import, shared runner change or new schema is introduced. The exact invocation is frozen in `origin-binding-correction/invocation.txt`; these corrected contract/harness files supersede only the corresponding original artifacts, which remain unchanged. This is an external evidence invocation, not a new registered gate, schema or runner. The required `GODOT_BIN` prerequisite prevents resource-matrix's optional runtime branch and environment decorators from silently omitting runtime execution. No shared manifest edit is necessary for this proof. Root may separately serialize an inventory record if required by campaign records; the implementer has no authority to edit `architecture-verification.json`. A metadata-only root contract/ledger record is root-owned.

The existing 49 owners measure 15,145 physical/20,856 structural units. The readable final-layout preview measures 14,202/19,088: reductions of 943 physical and 1,768 structural units. The new helper is 31/48, its one function 19/42, nesting 1, parameters 2, below complexity 15. Net before the new independent characterization test module: 14,233/19,136. These are source-preview measurements, not a completed implementation claim. The first preliminary external preview lacked the complete package geometry for first-party import grouping; the authoritative preview and metrics now use the actual frozen source package layout and pass isolated lint.

Budget the new helper at at most 100 physical and 150 structural units (and always below the roadmap's 300-line helper maximum); its function at most 60 of each, complexity ≤15, nesting ≤4, parameters ≤8. Budget new `tests/test_godot_test_support.py` at at most 300 physical/600 structural units, every function ≤200 of each, complexity ≤15, nesting ≤4, parameters ≤8. This is one independently understandable characterization owner, not helpers split to hide debt. Existing oversized modules/functions may only shrink or hold their exact immutable parent values under the unchanged gate; update the baseline downward only. Do not raise or add allowances, suppressions, exclusions, dynamic path bootstraps, casts or metric policy. No unrelated formatting; final R04 import layout applies to changed imports. Existing production source hashes and fixture payloads must stay unchanged.

## Characterization, negative controls and completion proof

Author the finite 12 helper methods before changing the scoped test consumers:

```text
tests.test_godot_test_support.TestGodotTestSupport.test_discovery_preserves_environment_path_and_macos_fallbacks
tests.test_godot_test_support.TestGodotTestSupport.test_absent_optional_engine_skips_before_launch
tests.test_godot_test_support.TestGodotTestSupport.test_explicit_path_bypasses_discovery
tests.test_godot_test_support.TestGodotTestSupport.test_empty_explicit_path_is_launch_error_without_fallback
tests.test_godot_test_support.TestGodotTestSupport.test_exact_build_requires_successful_combined_output
tests.test_godot_test_support.TestGodotTestSupport.test_wrong_build_is_failure_not_skip
tests.test_godot_test_support.TestGodotTestSupport.test_nonzero_version_exit_is_failure
tests.test_godot_test_support.TestGodotTestSupport.test_timeout_and_oserror_propagate
tests.test_godot_test_support.TestGodotTestSupport.test_version_timeout_values_are_preserved
tests.test_godot_test_support.TestGodotTestSupport.test_import_does_not_discover_or_launch_engine
tests.test_godot_test_support.TestGodotTestSupport.test_wrong_build_executes_real_version_process
tests.test_godot_test_support.TestGodotTestSupport.test_repeated_calls_rediscover_and_revalidate
```

The first method covers the real production finder's environment → PATH → macOS fallback behavior via controlled filesystem/PATH results, including invalid/empty environment fallbacks. Tests must observe selection/launch, not just compare the helper's implementation text. Explicit path and empty path tests prove discovery is bypassed. Exact output/status tests exercise correct, empty, wrong, stderr-only and extra-stderr outcomes; timeouts cover 10/20/30. Errors must propagate as their native classes, and two calls must rediscover/reprobe. Import proof rejects any discovery/version process. The actual-process negative control calls the native `sys.executable` as the supplied engine; Python's successful `--version` must cause a wrong-build assertion, never a skip or success.

Before/after characterization already performed externally, to be repeated against the accepted immutable implementation refs:

* 264 finder-case executions preserve all selected outputs and ordered filesystem/PATH queries across the 43 duplicates and canonical owner.
* The ten existing skip-on-wrong-build test methods run with `GODOT_BIN` set to the actual native Python executable. Baseline: exactly 10 skips, zero errors/failures. Proposed helper migration: exactly 10 failures, zero skips/errors. This uses a real process; it does not merely mock its status/output. Its ten exact IDs and raw tracebacks are frozen in `characterization-proof.json`.
* All 112 existing owner test IDs collect unchanged; no process is launched by collection. All multiline string payload values are identical. Implementation proof additionally compares unchanged-method ASTs, boundary-stripped changed-method ASTs with the one DS local rename normalized, GDScript/f-string AST payloads and non-version subprocess argument ASTs so no assertion/launch is hidden in the helper.
* Re-run the existing required-runner skip rejection characterization (`tests.test_required_unittest_runner.TestRequiredUnittestRunner.test_skips_require_the_exact_manifest_reason`), and exercise the exact T01 required gate with an induced helper skip: a required skip must make the gate nonzero. An absent required `GODOT_BIN` must fail the prerequisite. Restore source/environment, rehash and pass the real gate with no skips before freezing. Do not alter the runner to obtain this proof.

On the accepted native environment run Pyright `./venv/bin/pyright --warnings` to zero errors/warnings, normal and tracked-input Ruff, the unchanged strict maintainability comparison against the actual immutable parent, actionlint for the two module-list additions, and diff checks. Run the 12 helper tests plus all 112 existing owner IDs after fixes. The 64 runtime IDs and 12 helper IDs must pass with exact Godot and zero skips in the required gate; a gate receipt is not substituted by ordinary unittest's success-on-skip. Preserve all existing other IDs. The larger owner/full suite may include existing platform-only skips (e.g. symlink privilege tests); record each exact reason and do not credit them as required runtime proof.

Run full unittest on the final frozen tree with the exact Godot binary and all five existing pinned project environments. Run the same Linux exact-engine smoke/fixture workflows already used by the campaign. The small helper characterization module must also run on native Windows and macOS via the two approved existing-command additions; require all 12 pass/no skips and inspect exact source/receipt identity. This provides Windows path/error/real-Python-launch evidence; it does not claim Windows Godot runtime coverage. Preserve existing native/transaction/privileged proof gates unchanged.

Record the cost of the 49 additional version processes honestly: on a reserved native window use the same exact engine/input and freeze all per-launch durations for the old 15-probe and proposed 64-probe workload, plus suite elapsed time with the same fixture environment. This measures test verification overhead, not converter performance. No cache or micro-optimization is authorized to erase it. Full conversion parity is not changed by test-only code; if root requires the existing five-fixture/all-14-field and same-ref proof for T01, invoke the unchanged R01 manifest contract and runner rather than creating new normalization or runtime policy. Never claim generated-byte equality only from a timing result.

## Assignment, acceptance and deletion conditions

One root-assigned T01 implementer in an isolated `dev/` worktree; transactions agent (if still independent/available) then root review actual frozen code and proof. No source edits or implementation before root accepts this finite scope/API and refreshes the actual post-R04 base. The proposer is not its independent reviewer.

Acceptance decisions still outstanding: (1) the combined-stream rule and its exact six-site channel changes; (2) final acceptance of the 54-file implementer scope and finite external required-proof invocation (the two native command-list additions are already accepted in principle); (3) retaining the 12 already-canonical runtime methods and parity validator as read-only; (4) scheduling/fixed parent after R04 bridge retirement and exact runtime/performance proof acceptance. No additional permission is inferred from this proposal.

Completion requires zero `_find_godot_binary` definitions/references in the accepted 43-owner inventory, zero local `--version` subprocess blocks at all 15 old sites, all 64 callers on the one test helper, preserved 112 old IDs/visible assertions, the 12 new meaningful test IDs, no source/type/lint/new-debt regressions, required native/exact-engine evidence, independent and root approval, and final PR/merge exact-revision CI. Existing direct production-finder imports solely for DS/stale decorator/global timing remain intentional and are not duplicate finder implementations. No temporary adapter is proposed; all old local definitions and migrated version blocks are deleted in this task before verification. The helper is a permanent small test-only owner; it cannot become a new application discovery owner or T02 subprocess framework.


## Accepted executable selection correction

This addendum supersedes the earlier conflation of static call sites, executable
runtime methods and complete probe counts. All 53 implementation owner files remain
exactly as independently/root approved at source commit
`4defcb3f5de3f6bea8bf130488dcc6fc55de4599`; baseline-only commit
`c767c48e9f9a129d8e5e62e306a8282712b81821` has 1054 entries (two removals,
17 reductions). No test body, payload, assertion, helper API, native selector or
production source changes for this correction.

The original 112-owner run passed all 112 tests with zero skips in 81.596 seconds.
The subsequent induced-skip control selected a private camera helper requiring a
scene_writer argument. Its TypeError made the 76-case receipt invalid as skip-only
proof. That failed receipt, the successful owner run and the actual 15/64 timing
remain preserved. Neither positive required proof nor full suite ran in that attempt.

Replace only TestCamerasDisplayGodotSmoke._run_smoke in the required inventory with
its three existing public callers, in this order: test_camera_helpers_sync_view_arrays_and_gui_size,
test_multiview_viewport_state_and_diagnostics, test_window_display_screenshot_apis.
All other selected IDs and their order are unchanged. Each wrapper invokes the
helper once with its own scene writer and checks its distinct runtime marker.

The corrected selection contains 66 runtime methods and the same 12 helper methods:
78 unique public test_ IDs, all required to execute without skips. All 64 static helper
sites remain: 62 direct public tests, one camera helper called by three tests, and
one resource-matrix helper called by one test. No repeated direct or looped probe edge
exists in this finite inventory. The old 15 probe expressions execute once each;
the candidate runtime cohort executes 66 probes, 51 additional launches. The 49 new
static sites remain a separate count. The first 15/64 benchmark describes only the
static workload actually measured. Corrected timing uses three alternating 15/66
rounds, retaining exact per-launch expressions/durations and all raw samples.

The external corrected harness rejects non-test method IDs before runtime work,
preserves exact cwd/PYTHONPATH/import-origin binding and uses the unchanged required
runner. Its corrected 78-method induced real-helper skip control must fail solely
for the one expected skip, then the untouched positive process must pass all 78 with
zero skips. Missing required GODOT_BIN still fails before a test receipt. Full unittest
uses the exact Godot engine and all five pinned fixtures. The previous source-bound
112/0 receipt is reused because all 374 Python source hashes remain identical.

Root and the independent reviewer accept the external ten-artifact correction index
SHA256 `0330beafc6bb268b7e64c06dc1dbb47cbb74986cfe8750d201a0acd87f69b433`.
The independent correction receipt SHA256 is
`77c68e5f2b7102ad30576c8c5b50ec4f514076f07be8639eaefa6e7145134343`.
The corrected driver freezes and rechecks all six external code/input hashes plus
that index, all 374 source files, six root metadata files and all five fixture pins
before/after each phase. Fresh corrected receipts go in a separate directory.
Root must freeze this metadata and reserve the benchmark window before execution.
Native Windows/macOS still require the same twelve helper cases with zero skips;
Linux/Godot discovery already selects the three camera wrappers. No new workflow or
Windows Godot-runtime guarantee is introduced. Corrected proof is pending, not passed.


## Final corrected local proof accepted

Independent review and root actual-code/proof review approve immutable candidate
`d99d28a4009e2d4eae7ecc8e526bb6f193cfb43a`. The corrected required cohort passed
78 tests with zero skips, errors or failures. Missing required GODOT_BIN exited 1
before a test receipt; the induced real-helper control ran all 78 and exited 1
solely for its one intended skip, with no errors or failures. The earlier 112-owner
receipt is reused explicitly: all 374 Python source hashes are unchanged.

The full suite passed 3,076 tests in 768.704 seconds with 56 recorded skips:
53 Windows/NTFS cases, two Linux bind-mount cases, and one case-insensitive-host
case. Exact Godot 4.7.2.stable.official.ed1daf0bf and all five pinned projects
were available. Skipped platform behavior remains missing native evidence locally.

Three alternating pairs measured the actual 15/66 probe workloads. Median totals
were 376.150207 ms and 1,671.230631 ms, an added 1.295080424 seconds for 51 extra
version launches. Ranges were 372.528372–376.870085 ms and
1,649.066960–1,674.186497 ms. The 28,196,864-byte maximum RSS belongs to the
benchmark Python worker; it does not measure child Godot memory or converter
performance. The original failed 76-case control and 15/64 static-site timing
remain preserved with their stated limitations.

The final 49 migrated test owners contain 14,190 physical and 19,088 structural
lines. The new helper is 31/48 lines and its tests 168/485; combined Python source
shrinks by 756 physical and 1,235 structural lines. All 43 duplicate finders and
15 old version blocks are removed, while the 112 existing owner IDs and visible
runtime assertions remain. The helper function is 19/42 lines and fresh functions
fit the accepted budgets. The actual-parent baseline retains 1,054 entries with
two removals and 17 reductions; no allowance grows.

Root rehashed all 21 final artifacts, 374 source files, six frozen metadata files
and ten correction inputs, and checked the phase chains, origins and raw counts.
The final proof index SHA256 is
`44375af32d0745746b7b5d7f5131b12394549a5eb1a97c719f448567f6ccfe6d`.
Independent final proof receipt SHA256:
`44c17c5d29ad6110b22ca70c2e3a85bb40d4f1912c3dca2f99dd7cbe4cb3fdb3`.
Root final proof review SHA256:
`dd4e3efe01510bc29ef9b1f5350f0cb39fdbd4a9e638ba1d4d1fe191557c6dbd`.

T01 is approved locally. Completion still requires actual-parent integration,
combined checks and exact PR/merge CI, including twelve helper cases without
skips on both native macOS and Windows. This approval is not campaign verification.
