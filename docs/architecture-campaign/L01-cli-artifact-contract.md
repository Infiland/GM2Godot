# L01 accepted implementation contract

Root ACCEPTS and assigns this finite contract after independent and root review.
The implementation base is verified R04 cleanup merge
`feb22c30ea13475116c0190e302df0fc7fe08383`. All fifteen source inputs in the accepted
proposal match this checkout. R04 exact PR and merge CI/native/strict-parent proof
passed; its temporary baseline exception is removed. This current assignment
supersedes the read-only proposal status and historical source below. All substantive
scope, behavior, characterization, size and proof constraints remain binding.

Sole implementer: `audit_transactions_cli`, isolated worktree
`/Users/infi/Documents/Github/GM2Godot-080-cli-artifact-ownership` on
`dev/080-cli-artifact-ownership`. Independent actual-code reviewer:
`audit_policy_tests_docs`, then root. Exactly four owner-editable files:
`src/cli.py`, `src/conversion/converter.py`, `tests/test_cli.py`, and the new
`tests/cli_test_support.py`. Root alone writes the fifth allowed file,
`maintainability-baseline.json`, plus campaign/coverage/verification metadata.
No commit, push or PR before root actual-code approval and explicit instruction.

Characterize the supported True branch with the corrected stub and the real retained
CLI/Converter cases before production deletion. Preserve all 78 method identities
under the finite seven-name mapping and every live external-report and pre/post-decision
SIGINT invariant. This is the accepted deletion slice; L03 owns final coordinator
complexity. Refresh actual source metrics before editing and distinguish retained
physical allowances from source line counts. No budget or scope growth is implied.

Use the approved native Python 3.12.10 environment and exact Godot
`4.7.2.stable.official.ed1daf0bf`. Freeze source for proof. Request root's CPU window
before full-suite, parity or benchmarks; R11 and G01 have prior reservations.
Focused/before-production checks may proceed. Required full proof uses all five
pinned projects. Native CI and exact integrated revision checks remain mandatory.

# L01 final finite contract proposal

Read-only source reconciliation, 2026-09-05. This supersedes the edfe6df-era draft;
no repository implementation or commit is authorized. Inspected frozen R04 candidate
`ef758360d91e96f2df0a72fc17769e7e5ed77c09` in GM2Godot-080-import-layout; its three L01 Python
owners are byte-identical to the approved R04 policy preview based on R03 f1781fc5.
Root-owned dirty campaign documentation is excluded. The final integrated R04 revision,
retired policy bridge, parent trust and actual metrics must be refreshed before implementation.

`L01-final-source-inventory.json` records all current source hashes, exact symbols and allowed
paths; `L01-final-test-inventory.json` records an actual 78-ID unittest collection, all 29 stub
consumers, seven explicit method renames, five retiring B009 keys, and native/real proof hashes.
The external source/support prototypes are feasibility and characterization evidence, not
an accepted repository patch.
## Supported boundary and scope

Supported entry points are `python main.py ...`, `python -m src.cli ...`, and the existing
`cli.main(argv)` function. main.py forwards CLI arguments. The parser exposes no converter
factory, plugin or nontransactional-mode switch. Repository/documentation search found no
supported alternate Converter injection interface. Tests patch the module's imported
`src.cli.Converter` binding; that is a test seam, not evidence of a second production mode.

There is exactly one production `managed_output_transactional` definition, True on Converter,
and exactly one reader, CLI's getattr(..., False). Remove that fallback and its obsolete
canonical-report adaptation. Delete the one marker declaration after the reader disappears.
Do not add a replacement capability probe, permissive getattr, adapter protocol or factory API.

Keep the public Converter constructor and its real staged_output_finalizer, callbacks and
threading.Event behavior. Keep diagnostics, last_outcome, convert and publish_conversion_attempt
semantics. refresh_conversion_artifacts remains a real Converter operation used by its
finalizers; remove only CLI's unreachable calls, never its implementation or direct tests.
Diagnostic capture/restore/publisher types remain used by Converter and diagnostic tests.

L02/L03 retain request/session/reporting decomposition. No new cli_configuration.py,
cli_session.py or cli_reporting.py is justified by this deletion slice.

## Exact True-path propagation

| Existing value or owner | True-mode fact | L01 change |
|---|---|---|
| transactional_conversion | Always True for the supported Converter | Remove the flag/read; make its existing positive branches unconditional. |
| managed_generation_decided | Set True in convert's finally, before log flush, external reporting and summary | Keep the assignment and decision timing exactly. Do not infer that late SIGINT can undo conversion. |
| canonical_reports_authorized | Always False | Remove variable, assignments, canonical candidate and canonical destination key. |
| protect_managed_reports | Always False | Remove variable and protected canonical branches. |
| managed_report_checkpoints | Always empty: checkpoint helper immediately returns None | Remove dict, _ManagedDiagnosticCheckpoint, managed_report_checkpoint, reset_managed_report_publications and restore_managed_reports. |
| canonical_refresh_disabled | Only controls removed canonical paths | Remove it and their associated writes. |
| late_artifact_error / report_restore_error | Never populated in the supported True path | Remove variables and their now-unreachable stderr branches. |
| _regular_conversion_manifest_exists | Called only by the obsolete protect expression | Delete function plus its now-unused stat and CONVERSION_MANIFEST_RELATIVE_PATH imports. |
| capture/restore report imports and snapshot type | Used in CLI only by removed checkpoints | Remove CLI imports; shared diagnostic implementations remain untouched. |
| Managed report destination | Already staged via real Converter callback | Keep _managed_report_relative_path validation and write_staged_cli_reports; suppress later external publication when the managed-relative result is not None. |
| Initial external publication | No checkpoint or normalized checkpoint destination exists | Call _write_external_conversion_reports(external_report_dir, platform, diagnostics) directly. Keep helper ordering and return type. Remove unused local receipt/checkpoint bookkeeping. |

Keep _resolved_path_key and _resolved_path_is_within: they still enforce report path safety.
Keep _safe_conversion_report_destination including preflight refusal and source/output roots.
Keep _write_external_conversion_reports' receipt return type: it still accurately represents
the diagnostic publisher, and deleting that API/type has no benefit to this slice.

## Live external repair and attempt publication

`repair_conversion_reports` is not dead. Retain a small nested helper, optionally rename it
`repair_external_conversion_reports` consistently. It has one possible destination,
external_report_dir; no canonical candidate list, destination-key deduplication or checkpoint.

Preserve this order for every existing call site:

1. Set the diagnostic collector's current outcome.
2. If an external destination exists, call DiagnosticCollector.publish_reports directly.
   Repair does not rerender the four static reports and does not call the initial external
   wrapper again. Retain the wrapper's static-before-diagnostics ordering on initial publication.
3. Preserve existing Exception handling and state observations. A failed repair for an already
   failed/cancelled outcome must not delete an old trustworthy report, replace the primary
   error, synthesize a canonical generation or introduce new stderr. Preserve the existing
   conditional success/partial downgrade to conversion_diagnostics/finalizer and retry logic
   when reducing the helper; do not redesign outcome propagation in L01.
4. Return the observed outcome. Keep the caller's current repair triggers and call order.

With the supported current call graph, normal repair is reached for runtime failure,
failed/cancelled outcome or initial report failure; primary report failure already changes
successful/partial state to failed/external_reports/report before repair. The retained
defensive success/partial branch need not become a new public behavior or new generalized API.

After repair, preserve the separate existing comparison:
`isinstance(converter.last_outcome, ConversionOutcome) and converter.last_outcome != outcome`.
Only then call publish_conversion_attempt(outcome). Compare the complete dataclass value,
not just state, identity, truthiness or diagnostic collector outcome. Equal outcomes do not
republish; None or a non-ConversionOutcome value does not create an attempt. Preserve the
current direct `published_outcome = converter.last_outcome` read: a missing attribute is not
a supported alternate interface and must not acquire a new fallback. The stale draft's
missing-attribute claim is explicitly withdrawn.
Do not move attempt publication into the diagnostic repair loop or retry it unconditionally.
Preserve the actual Exception capture, terminal-attempt error detail, and exit-code escalation
only when the prior exit code was zero. Canonical files and manifest remain unchanged by a
late failed attempt.

Keep stdout log/one-summary ordering, primary preflight JSON, runtime/finalizer note order,
external error precedence, diagnostic thresholds, --allow-partial and exit 0/1/2/130 mapping.
Preserve real signal installation/restoration and summary buffering. No signal/session
redesign or removal of unrelated terminal branches belongs in this slice.

## Exact fake/stub migration

`L01-final-test-inventory.json` enumerates 29 TestCLIReports methods constructing _OutcomeConverterStub,
plus the real Converter refresh/publication tests. There is one stub class, not an
independent family of alternate production engines. _run_stubbed_convert is the common seam;
direct module-binding factory/return-value patches are separately listed in that inventory.

Move exactly the stub and the three current outcome factories into the new bounded
`tests/cli_test_support.py`, with package-internal public names OutcomeConverterStub,
success_outcome, partial_outcome and failed_outcome. Migrate their direct names in test_cli;
do not move TestCLIReports, native tests or runtime fixtures. This removes the shared helper
from the 3,602-line test owner without creating a second helper implementation.

The corrected stub must model the supported contract:

- Capture the actual threading.Event passed to the patched factory. _run_stubbed_convert
  and every explicit factory/return-value patch must bind it; missing binding fails clearly.
  A finite factory helper may inspect the one known conversion_running argument. It must
  not be a generic dependency container or fake transaction framework.
- Store last_outcome separately from diagnostics.outcome. Initialize to None and update it
  when convert records/returns an outcome or publish_conversion_attempt succeeds. A property
  that simply reads diagnostics.outcome would hide a changed terminal attempt and is forbidden.
- Run the existing on_convert callback at its existing seam. Observe a cleared Event while
  still inside convert and return/set a cancelled outcome as the real converter does. Do not
  rely on CLI cancelling an already returned success. Preserve configured exception, warning,
  ledger and resource-count cases; keep last_outcome/diagnostics state explicit on error.
- publish_conversion_attempt records the exact value and updates last_outcome only on success.
  Remove artifact_refreshes and the obsolete fake refresh_conversion_artifacts method. Do not
  implement fake managed publication or invoke a staged finalizer against a fabricated stage.
  All managed staging/preservation claims continue to use the actual Converter.
- During before-source-change characterization the fake may carry managed_output_transactional
  = True to select today's supported branch. Remove the temporary marker with the production
  marker. No permanent false-mode fake or compatibility fixture remains.

### Exact semantic test adjustments

| Existing test(s), all in TestCLIReports | Required migration, preserving the actual production invariant |
|---|---|
| test_external_report_failure_returns_failed_outcome | Keep failed external_reports/report outcome, one summary and exact primary stderr. Expect one changed terminal attempt; remove false-mode canonical refresh expectation. |
| test_external_report_failure_repairs_published_success_json | External JSON becomes failed; seeded canonical JSON stays success and untouched. Assert terminal attempt value instead of canonical refresh. |
| test_external_report_failure_preserves_every_failed_repair_pair | Keep both trustworthy old report pairs unchanged when repair fails; retain original report error and one failed attempt. No canonical rewrite. |
| test_recovered_terminal_attempt_publication_clears_stale_error | This scenario depends on an unreachable canonical refresh plus late cancellation retry. Replace in place with the real True-mode terminal-attempt contract: exact changed outcome publishes once; equal outcome does not; a failure is reported without false retry/recovery. Include a differing-counts/same-state comparison case. |
| test_external_report_failure_deduplicates_canonical_destination | Its mock raises even for the None destination that production treats as a no-op. Replace with actual managed-report staging/suppression coverage: the real staged finalizer owns the canonical report; post-commit external publication sees None and performs no write. Reuse existing real project fixture and report/manifest hash assertions. |
| test_sigint_overrides_success_restores_handler_and_returns_130; test_sigint_during_converter_construction_publishes_cancelled_outcome | Keep exit130, one cancelled summary/report and restored handler. Bind the actual Event and have the stub observe it before returning. Preserve a real pre-decision cancellation case through a Converter callback/conversion seam. |
| test_sigint_during_log_flush_publishes_cancelled_outcome; test_sigint_before_summary_output_republishes_cancelled_outcome; test_sigint_after_buffered_summary_prints_only_cancelled_summary; test_sigint_in_pre_summary_gap_is_observed_before_output; test_sigint_during_report_generation_rewrites_cancelled_outcome | These points are after the real generation decision. Rename only these cases to describe preserved committed outcome; keep the same interruption timing and assert stable success/report/attempt, one summary and correct restored handler. Do not delete the interruption probes. |
| Four existing handler/stdout/committed-return SIGINT tests and second-SIGINT installation test | Preserve their existing one-summary, stable exit and handler restoration assertions. Bind the corrected fake where they patch Converter directly. |
| Remaining stub success/partial/threshold/preflight/runtime tests | Mechanical helper/factory migration only; preserve existing error text, note order, counts, report safety and status assertions. |

Keep all real tests: canonical staged-only reports, managed static failure rollback, symlink
alias staging, nested external once-only publication, no post-commit canonical refresh,
no equal-outcome attempt republication, runtime second-run preservation and post-decision
signal stability. No broad replacements of these real tests with stubs are authorized.

All executable tests remain in tests/test_cli.py, preserving its existing macOS/Windows
workflow selections. The new file contains shared test support only, so no new native gate
or workflow inventory is needed. Remove the source-sized duplicate helper definitions;
do not use wildcard imports or private reexports to preserve old references.

## Exact allowed files (5)

1. src/cli.py: constant propagation/removal above and surviving external helper simplification.
2. src/conversion/converter.py: delete the sole managed_output_transactional = True declaration;
   no constructor, conversion, finalizer, publication or ownership changes.
3. tests/test_cli.py: exact stub/helper/factory and enumerated assertion migrations; characterize
   through existing real fixtures, without moving the large suite or weakening native coverage.
4. tests/cli_test_support.py (new): the one corrected stub, three unchanged outcome factories,
   and the finite five-boundary typed signal context manager defined below.
5. maintainability-baseline.json: actual reductions only, against the accepted immutable parent.

No diagnostics/anchored publication implementation, report format, CLI flag, converter setting,
workflow, dependency, version, GUI, source family, request model or production module extraction.
Final R04 integration is a prerequisite. Root must freeze the integrated source and
new-policy immutable parent before implementation; no concurrent CLI/import edits.

## Before metrics and finite targets

| Owner | Physical lines | Structural units |
|---|---:|---:|
| src/cli.py | 1401 | 2036 |
| _run_convert | 579 | 794 |
| repair_conversion_reports | 141 | 173 |
| managed_report_checkpoint | 25 | 31 |
| reset_managed_report_publications | 31 | 59 |
| restore_managed_reports | 5 | 6 |
| _regular_conversion_manifest_exists | 10 | 15 |
| src/conversion/converter.py | 1442 | 1772 |
| tests/test_cli.py | 3602 | 7094 |

Existing recorded McCabe values are _run_convert C98 and repair C28. Target cli.py <=1180
physical/1750 structural; _run_convert <=360 physical/550 structural/C60; surviving repair
<=60 physical/C10 and within every fresh-function R02 limit. This is a deletion milestone;
L03 still owns the final <=150/C15 coordinator. No claim that retained coordinator debt is
fully retired. Converter changes exactly one declaration and records honest retained debt.

New support owner <=180 physical/350 structural and no suppressions/debt; functions <=150
physical/200 structural/C15 (tighter than the general 200-physical test-function ceiling).
Every fresh production function remains <=150 physical AND <=150 structural, C15/nesting4/
parameters8; test helpers and renamed methods are fresh owners with no inherited allowances. Existing test owner must shrink, targeting <=3600 physical/7070
structural after real helper removal and scoped replacements. If measured targets fail,
return for bounded refinement rather than packing lines, dropping assertions or raising budgets.

## Characterization and completion proof

Before production deletion, correct the fake to today's True mode and run its migrated
cases plus the real cases. Record exact stdout/stderr/status, ordered publication call log,
full last_outcome/diagnostic/attempt values, canonical manifest bytes and its report hashes.
This baseline must be the supported True path, not a false-mode fixture adjusted only after
code removal. Freeze constructor callback/Event behavior and real pre/post-decision timing.

Historical edfe6df evidence, not fresh R04 execution: eight existing real cases passed at
that older source: late external report
failure, managed report failure, external publish-once, no canonical refresh, staged-only
canonical reports, no redundant terminal attempt, canonical preservation after SIGINT and
no late refresh after SIGINT. All 8 passed in 1.456s; this is correctness evidence, not a
performance claim. Exact historical output is `L01/real-characterization-before.txt`; rerun these cases at the accepted parent.

After edits: Pyright --warnings 0/0; Ruff; full tests.test_cli plus support/entry-point checks;
tests.test_converter, tests.test_converter_transaction, tests.test_diagnostics and managed-output
crash recovery; full unittest with exact Godot and all required pinned fixtures; immutable-parent
R02 and diff check. Run the existing native macOS/Windows CLI transaction selections and Linux
managed-output/bind-mount coverage on the exact integrated revision. Keep all actual native
checks; local macOS and stub evidence cannot certify NTFS.

Compare immutable base/candidate real success, partial, preflight, runtime, cancellation,
initial static/diagnostic failure, late external repair failure and attempt-publication failure.
Preserve complete payloads/hashes and only normalize explicitly identified run-specific paths
or timing fields when necessary. Keep CLI cold import free of PySide6. Report platform,
interpreter and fixture identities with receipts. Any elapsed-time/peak-memory comparison
uses the same inputs, repeats and controlled CPU window; no performance claim follows from
removing unreachable code.

Freeze exact files/hashes and receipts; independent reviewer and root review actual source.
The rest of this contract adds the reconciled exact identities and proof limits. This proposal
authorizes neither implementation nor commit/integration.


## Reconciled scenario counts and exact method identities

The stale shorthand "three obsolete cases" is incorrect. Exactly two complete scenarios
assert the unsupported false-mode canonical adapter and are replaced in place. Three other
cases remain live external-report failure tests and retain their IDs; only their obsolete
canonical-refresh expectations migrate. The five post-return SIGINT cases remain executable
probes at their original boundaries. No third deleted scenario is invented.

All names below share `tests.test_cli.TestCLIReports.`:

| Existing method | Candidate method |
|---|---|
| test_recovered_terminal_attempt_publication_clears_stale_error | test_terminal_attempt_publication_uses_exact_outcome_comparison |
| test_external_report_failure_deduplicates_canonical_destination | test_managed_report_destination_suppresses_post_commit_external_writes |
| test_sigint_during_log_flush_publishes_cancelled_outcome | test_sigint_during_log_flush_preserves_decided_outcome |
| test_sigint_before_summary_output_republishes_cancelled_outcome | test_sigint_before_summary_output_preserves_decided_outcome |
| test_sigint_after_buffered_summary_prints_only_cancelled_summary | test_sigint_after_buffered_summary_prints_only_decided_summary |
| test_sigint_in_pre_summary_gap_is_observed_before_output | test_sigint_in_pre_summary_gap_preserves_decided_outcome |
| test_sigint_during_report_generation_rewrites_cancelled_outcome | test_sigint_during_report_generation_preserves_decided_outcome |

All 71 other IDs remain, preserving 78 total executable methods; all test methods stay in
`tests/test_cli.py`. The 29 current stub consumers include both replaced scenarios and five
renamed signal cases. The managed-destination replacement uses the real Converter, so the
candidate need not retain 29 stub consumers as an artificial invariant. This is a source
cohort inventory, not a claim that 29 different production engines are supported.

The three live ID-preserving assertion migrations are
`test_external_report_failure_returns_failed_outcome`,
`test_external_report_failure_repairs_published_success_json`, and
`test_external_report_failure_preserves_every_failed_repair_pair`. Keep their exact primary
stderr, outcome phase/step and report-pair preservation checks. For the last two, compare
seeded canonical bytes rather than silently making canonical diagnostics agree with the
latest failed external attempt.

The new exact-comparison method covers equal dataclass values (including distinct equal
objects), changed values, same-state differing counts/ledger, None and a deliberately invalid
non-ConversionOutcome value, plus one publication failure with no retry. The failure's effect
on stderr and 0-to-1-only escalation must be compared with an already nonzero outcome. A
finite subTest table and explicit mocks are sufficient; no new result protocol, reflective
framework or missing-attribute compatibility scenario. Existing live initial-report/runtime
failure tests supply their primary-error precedence checks. Any new helper or replacement
method must fit its fresh size budget; do not move allowances from the renamed methods.

## Exact typed signal observation and debt retirement

The new support owner contains one `cli_sigint_at_boundary` context manager with a finite
Literal of five cases and a typed `types.FrameType` callback. It calls no private CLI helper;
tests invoke public `cli.main`, real `signal.raise_signal(SIGINT)` and real stdout/report
publication. The existing helper functions still run without monkeypatching their behavior.

| Boundary token | Exact source observation | Preserved injection point |
|---|---|---|
| log-flush | cli.py `_print_conversion_logs`, trace `call` | Arguments evaluated, before the log function body. |
| before-summary | cli.py `_print_conversion_summary`, trace `call` | Before the buffered summary body. |
| after-summary | same function, trace `return` | After the summary write into its existing buffer, before caller resumes. |
| pre-summary-gap | cli.py `_run_convert`, exact next line after its sole `terminal_summary_phase = "preparing"` assignment | Existing before-observation line event, not a generic after-convert callback. |
| report-generation | cli.py `_write_external_conversion_reports`, trace `call` | Before the existing initial external publisher body. |

Require exact `frame.f_code.co_filename == cli.__file__`, function name and event; the line
case additionally resolves the one literal source assignment and asserts it is unique.
Snapshot the boundary in a reached list, disable the temporary trace before raising SIGINT,
and restore the original trace in finally. Each case must assert exactly `[boundary]`, the
original real SIGINT handler restored, one successful summary/status0, unchanged seeded
canonical report bytes where present, exact external outcome and no redundant attempt
publication. The report-generation case retains converter/resource payload assertions.
The after-summary case must still prove the buffered line reaches stdout once.

No Any, constant-name getattr, casts to Any, new private-access suppression, production alias,
or source-inspection wrapper framework is permitted. A missing/renamed source checkpoint
must fail clearly through the uniqueness/reached assertion, not silently skip. The helper
is a finite public-CLI observation seam, not a production extension API or replacement for
actual transactional/native tests. Existing unrelated signal tests and their debt are not
silently rewritten in this slice.

The five renamed SIGINT owners each currently have one `lint.B009` key. The exact full keys
and current counts are frozen in `L01-final-test-inventory.json`; all five retire, and no
replacement B009 key is allowed. In particular, the separate unchanged
`test_sigint_after_handler_restore_cannot_override_committed_exit` key is outside this
retirement cohort. R02 prohibits treating a rename as an allowance transfer.

`cli_test_support-prototype.py` is an external finite feasibility example: 152 physical /
285 structural units; the context manager is 34 physical /98 structural, its nested trace
9/32. It has no fresh size debt, strict Pyright0/0 and isolated final-R04 Ruff I/B/C901/E4/E7/
E9/F pass. The three outcome factory ASTs are identical to the original except their names,
including failed_step="scripts", failure_phase="converter" and original default resources.
The return annotation uses Generator to satisfy the current pinned strict type checker.

A read-only probe exercised all five boundaries on unchanged R04 production source with
a corrected explicit True-mode characterization stub. All five passed with full outcome
values, no extra attempts, preserved seeded report bytes, one success summary and restored
handlers/traces; `L01-signal-characterization.json` records source/prototype hashes and
payloads. These are actual macOS public CLI observations using the proposed fake; they do
not establish managed generation publication or native Windows correctness.

## Source-backed size and ownership feasibility

The external deletion-only projection records cli.py 1140 physical /1710 structural;
_run_convert 338/490, C56, nesting6; surviving repair 29/51, nesting3, below C15. It introduces
no size debt and preserves the retained coordinator's existing debt honestly. This is
source-shape feasibility, not executed candidate behavior. Its exact script/hash and before/
after measurements are frozen in `L01-deletion-preflight.json` and `preflight_dead_adapter.py`.
The retained coordinator does not yet meet final <=150/C15; L03 owns that later milestone.

Keep `from dataclasses import dataclass`: CLISetting still uses it after checkpoint deletion.
Keep inspect/Callable/Any imports in test_cli where unchanged existing tests still require
them; do not apply a broad import or private-access cleanup. Only ordinary final-R04 import
normalization required by the exact moved helper imports is in scope.

The contract targets remain cli<=1180/1750, coordinator<=360/550/C60, repair<=60physical/C10
and fresh-production structural<=150, support<=180/350, and test_cli<=3600/7070 while all
existing debt shrinks or stays within the trusted retained allowance. The proposed support
has 28 physical /65 structural units of headroom. Final semantic tests may use that finite
headroom; exceeding it requires root refinement before widening any path/budget. No lowered
threshold, ignore, exclusion, source packing, assertion deletion, function relocation to
hide debt or baseline key rename is authorized.

## Exact retained native and collection proof

Collect `tests.test_cli` before and after with unittest's normal loader; compare exact ID sets
using the seven-name mapping, and require 78 methods. The inventory records existing body
AST hashes for all methods and explicit real-Converter/native cohorts. Assert the unchanged
real and platform-specific methods retain their assertions, allowing only referenced moved
factory names where actually present.

Existing Tests workflow already selects whole `tests.test_cli` on macOS and Windows; Linux
full discovery also collects it. No workflow/new gate/new runner is in the five-file scope.
Relevant native CLI methods, all retained under TestCLIReports, are:

- POSIX `test_new_static_report_permissions_remain_private_under_umask`,
  `test_static_reports_never_mutate_physical_replacement_at_each_phase`, and
  `test_static_report_rollback_stays_bound_after_physical_replacement`.
- Windows `test_static_report_windows_binding_blocks_directory_relocation`.
- Existing real report symlink, hardlink, staged-only, runtime, preflight, partial, manifest
  hash and post-decision signal cases remain. Link availability skips must be recorded as
  missing evidence on an applicable host, never reclassified as successful native coverage.
  The modeled junction case is not an actual Windows substitute.

Retain actual `tests.test_converter_transaction.TestConverterManagedOutputTransaction`
methods `test_mid_run_cancellation_after_real_write_preserves_baseline`,
`test_cancellation_during_finalizer_preserves_baseline`,
`test_cancellation_after_validation_preserves_baseline`,
`test_cancellation_immediately_before_decision_preserves_baseline`, and
`test_runtime_failure_after_real_mutations_preserves_baseline`.
Retain `tests.test_managed_output_crash_recovery.TestManagedOutputCrashRecovery.`
`test_cli_sigint_matches_recovery_and_commit_decisions`, which exercises the real public CLI
against actual recovery/commit decision phases. N01's receipt native tests cover another
owner and cannot replace these CLI/Converter transaction proofs.

Commands from the eventual accepted worktree:

```sh
./venv/bin/pyright --warnings
./venv/bin/python -m ruff check .
./venv/bin/python -m unittest -v tests.test_cli tests.test_converter tests.test_converter_transaction tests.test_diagnostics tests.test_managed_output_crash_recovery
./venv/bin/python scripts/check_maintainability.py --base-ref "$L01_BASE"
git diff --check
```

Use the actual pinned R04 workflow native transaction selections without changing them.
The existing Linux command remains mandatory with `GM2GODOT_REQUIRE_LINUX_BIND_MOUNT=1`:
`python -m unittest -v tests.test_managed_output_crash_recovery.TestManagedOutputCrashRecovery.test_linux_bind_mount_is_rejected_without_reading_external_target`.
Windows/macOS required methods must execute on their actual host; a generic suite exit0
with those methods skipped does not complete that host's proof.

Full native local unittest uses approved Python3.12.10, exact Godot4.7.2 official ed1daf0bf,
and all five pinned projects from `R03/full-inputs.json` (SIMPLE_TOPDOWN2413d771,
TCC4b6e942c, MONOPHOBIAb79cc26f, SNAPb4191e19, ADDING1bf03261). Reverify full immutable fixture
SHAs and interpreter/Godot identities before the run; this reference is a fixture manifest,
not a claim a future L01 run already passed. Freeze the full candidate source while it runs.
Local/full and three-host integrated CI receipts, actual skip classification and all required
checks are completion requirements. No elapsed-time or memory improvement claim is made.

## Acceptance boundary

Root accepts exact scope after a different agent reviews this frozen proposal and actual
source. Before implementation refresh source/import/metric/test inventories against the final
integrated R04 parent and recheck the five-source-path allowance; any changed semantics or
budget is a reported dependency. During implementation characterize the corrected True-mode
fixture first, then remove the dead production branch, then run focused/type/lint/gate/full
and native proof. Root alone approves final commit/integration after actual-code review.


## Approved implementation and local proof

The accepted source is `87d96d58b81edc929292fb33ada02fd2046419c6` on verified
parent `feb22c30ea13475116c0190e302df0fc7fe08383`. Independent source review and
root actual-code review approve all four owner files. A second independent reviewer
and root also approve the final local evidence. Integration and exact native PR/merge
CI remain pending; this task is approved, not verified.

The unsupported False capability branch and its obsolete canonical-report adapter are
removed. Real Converter finalizers, artifact refresh, transaction decisions and external
repair remain authoritative. The separate full-dataclass terminal-attempt comparison,
primary error precedence, one-summary output, exit mapping and pre/post-decision SIGINT
behavior remain intact. The temporary True marker used during characterization is gone.

Measured source changes (physical/structural units) are CLI 1401/2036 to 1134/1710,
coordinator 579/794 C98 to 336/490 C56, and surviving repair 29/51 C7. The new support
owner is 152/285, maximum C6. The test owner is 3403/7057. The actual Converter at the
accepted parent was 1442/1772; its one-marker deletion yields 1441/1771. These are source
measurements, distinct from retained proportional physical allowances. L03 still owns
the final thin coordinator. Baseline entries fall from 1056 to 1048: eight retirements
and nine lowered allowances, without a new allowance or policy change.

Before production deletion, the corrected True-mode characterization ran all 78 CLI
methods with one Windows-only skip. The candidate preserves 71 IDs and the seven
accepted mappings, three factory ASTs, 49 non-stub and 28 native/real test bodies.
Focused checks, strict Pyright (zero errors/warnings), Ruff, the trusted-parent gate
and diff check passed. The frozen full suite ran 3064 tests in 767.319 seconds:
3008 passed and 56 host skips (53 Windows, two Linux bind mounts, one case-sensitive
filesystem requirement). All 373 source hashes, native Python 3.12.10, exact Godot
4.7.2 official ed1daf0bf and all five immutable fixture commits were checked.

Nine real CLI scenarios at immutable base, same-ref control and candidate compare
complete outcomes, ordered calls, stdout/stderr, signal restoration and public artifact
bytes/hashes/modes. Each also replays the 78 preserved characterization assertions;
these are later replays, not recovered earlier output streams. All comparisons match.
The first comparison correctly failed on private UUID/inode differences and is retained.
The reviewed correction permits only three known private receipt schemas: it validates
exact inventories and fields, transaction/name bindings, raw desired-record references,
sizes/modes and shared destination identities before projecting specified volatile
identifiers and digests. Public bytes remain exact, unknown private fields/files fail,
and eight rejection plus four nonvolatile-change controls pass. It makes no historical
inode-stat, cross-phase inode-persistence or removed-journal-integrity claim. No time or
memory improvement is claimed for this deletion slice.

Final local proof index SHA256 is
`225845d3142b0292beb514029a00e68ff2791ea5d5ab1268f6a27758965762f2` (27 artifacts).
Independent final proof receipt SHA256 is
`b54a3ca4e531a7710d7feaac1d17bece1ac8011fa9bdf5fcef2dea2651081f86`.
Native selections already include the full CLI owner; existing coverage includes both
production owners. No workflow, gate selector, coverage floor or production coverage
cohort change is needed. Required CLI POSIX/Windows, real Converter cancellation/crash,
Linux bind-mount and final combined revision evidence remain explicit completion gates.
