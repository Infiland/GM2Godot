# L02 accepted CLI request and session contract

Task L02 / #867 depends on verified L01. Root accepts the final proposal and
actual T01 entry refresh at `e142714a0f24a085d5717132f24f44f3c2d488f8`, tree
`704f61ddd14b6b769392d7303195b8d4e808fb5d`. R12 is subsequently verified at
`b9c05cd326cbcb8531ca93c24709bcf14cb81748`; its ancestry and metadata will be
preserved during combined integration. Original proof remains attributed to its
actual source, rather than being relabeled as a later combined run.

Implementation owner: audit_policy_tests_docs, isolated branch
`dev/080-cli-session`. Independent source reviewer: audit_gml_resources, followed
by root's actual-code review. Root coordinates integration and all shared policy,
verification, ledger and release metadata. Production work begins only after the
entry metadata is reviewed and root assigns the implementation window.

## Problem and accepted boundary

The CLI still owns parser construction, raw configuration, signal state and
terminal reporting. At this entry, `_run_convert` is 336 physical lines / 490
structural units, complexity 56. L02 extracts bounded configuration and one
conversion's signal state; L03 retains reporting and final coordinator reduction.
L02's resulting 289 / 432, complexity 43 coordinator is an intermediate reduction.

The exact eight implementation paths are:

- `src/cli.py`
- `src/cli_configuration.py`
- `src/cli_session.py`
- `tests/test_cli.py`
- `tests/cli_test_support.py`
- `tests/test_cli_configuration.py`
- `tests/test_cli_session.py`
- `.github/workflows/tests.yml`

Root alone owns the maintainability baseline, coverage policy, architecture
verification manifest, this contract, `contracts.json` and `LEDGER.md`. No new
reporting module, flag, setting framework, registry, callback protocol, dependency,
suppression, exception, compatibility wrapper or production family is included.

## Configuration inputs, outputs and callers

`cli_configuration` owns `build_parser`, its four existing private argument/default
helpers, the existing conversion-group constants, `CLISetting`, `ConverterInventory`,
`converter_inventory`, `settings_for_selection` and `_split_csv`. The parser body,
help, flags and defaults stay intact. `CONVERSION_CATEGORIES` remains the exact
catalog object from the converter module. CLI calls the canonical owners explicitly.

Three frozen records hold ordinary argparse values in declaration order:

| Record | Fields |
| --- | --- |
| `ConverterSelection` | `only`, `groups`, `sound_group_folders` |
| `DiagnosticThresholds` | `fail_on_unsupported`, `max_unsupported`, `max_errors`, `max_warnings` |
| `ConvertRequest` | `gm_project`, `platform`, `godot_project`, `selection`, `report_dir`, `allow_partial`, `thresholds` |

`convert_request_from_args` and `thresholds_from_args` copy raw values without
splitting CSV, validating names, coercing booleans or normalizing paths. Supported
input is the unchanged parser's ordinary Namespace, not effectful property-backed
fake argument objects. Settings resolution remains the fourth positional argument
to `Converter.convert`, after constructor and the three path/platform evaluations.
Unsafe report paths and constructor failures retain precedence over invalid
selection. Selection `SystemExit` retains signal cleanup and no terminal summary.
CSV ordering, duplicate handling, nonempty `--only` precedence and modifier coercion
remain unchanged. CLI retains threshold comparisons, precedence and exit mapping.

Search found no outside production/test importer of the retired CLI internals.
The new tests migrate `CLISetting` to its canonical owner. No old re-export remains;
the internal records' `__module__` and private helper locations intentionally move.
No pickle or private introspection compatibility is promised.

## Session lifecycle and dependency direction

`cli_session` depends only on stdlib. `ConversionSession` owns eight fields:
`running`, `previous_sigint`, `handler_eligible`, `sigint_handler_restored`,
`sigint_received`, `managed_generation_decided`, `terminal_summary_phase`, and
`terminal_summary_interrupted`.

Construction preserves Event creation/set, previous handler lookup, main-thread
eligibility, initial flags/phase and a fresh local Exception subclass in that order.
The exception type is per session, with its private qualname moving into the
initializer. It must not become a shared module-level exception.

Handler installation remains the first operation inside the protected outer try.
Eligibility records main-thread ability, not successful installation. Failure
before or after assignment still reaches fallback cleanup. The first active SIGINT
marks received and clears the same Event passed to Converter; preparing may raise
that session's exception. A second active signal raises KeyboardInterrupt. Decided,
committing and committed states retain their existing cancellation exclusion.

Normal restoration retains its eligible/restored guard, actual handler comparison
on KeyboardInterrupt, restoration flag and conditional rethrow. Fallback retains
the distinct old finally behavior without adopting the normal method's flag or
comparison behavior. Normal restore immediately precedes committed return; outer
finally still calls fallback. Nested and sequential conversions own separate state.
CLI continues to own Converter, diagnostics, repair ordering, full-value outcome
comparison, publication, terminal output and return codes.

Dependencies are `cli -> cli_configuration -> converter/catalog` and
`cli -> cli_session -> stdlib`; neither leaf imports CLI. The reviewed complete
graph retains 14 static cycles / one eager cycle, with none added. Actual fresh
imports and entry points remain required runtime evidence.

## Tests and measured reductions

All 78 retained CLI IDs and 444 assertion ASTs remain. Seventy-four complete method
bodies stay exact. Three fixed signal mock targets migrate to `cli_session`.
The fourth changed method uses the existing typed `post-restore-return` boundary
instead of private frame/getattr/inspect/cast logic. Its real SIGINT and output,
report, exit and interruption assertions remain. The support requires a unique
`session.restore_sigint_handler()` immediately followed by `return exit_code`;
the preparing match changes only to the new explicit session field. No new trace
framework is introduced.

Ten before tests have now passed with zero skips against the real e142 public CLI
in a private export containing all 584 Git blobs plus two exact final-path test
overlays. Six configuration methods cover full settings/order and failure
precedence; four session methods cover worker noninstallation, assignment failure,
sequential Event isolation and nested handler restoration. The existing typed
OutcomeConverterStub is the execution seam. The separate retained cohort passed
77 tests with its sole exact Mac-host skip, `native Windows handles required`.
Source, runtime, cwd/PYTHONPATH, actual imports and real SIGINT restoration were
checked before and after both phases. No native Windows result is inferred.

Five candidate-only methods cover raw record values, fresh inventories, distinct
local exception types, cancellation phase state and distinct restoration flags.
They are not old-code characterization. All fifteen candidate methods must pass
without skips. The ten old-code bodies and retained assertions may not be weakened.

| Owner | Before physical / structural | Accepted projection |
| --- | --- | --- |
| CLI module | 1134 / 1710 | 870 / 1343 |
| `_run_convert` | 336 / 490, C56 | 289 / 432, C43 |
| Configuration leaf | new | 277 / 373; max function 108 / 140, C7 |
| Session leaf | new | 60 / 118; max function 14 / 35, C5 |
| Retained CLI tests | 3403 / 7057 | 3368 / 6992 |
| Existing support | 152 / 285 | 165 / 320 |
| Configuration tests | new | 198 / 642; max function 28 / 128, C2 |
| Session tests | new | 212 / 657; max function 34 / 123, C4 |

The entry has 388 Python files; projection has 392, preserving all 385 non-owner
parent files. The seven Python projections are exact to the reviewed proposal.
Only four workflow lines are added: the two new test modules immediately after
`tests.test_cli` on macOS and Windows. Both T01 helper additions and every prior
workflow step survive. Linux full discovery includes the new methods.

Actual-parent debt projects from 1045 to 1044: one B009 removal and seven reduced
allowances, no new or grown key. This is source-backed planning, not a fresh strict
gate receipt. Root will apply reviewed reductions and run the actual-parent gate.
Coverage and architecture-verification objects remain unchanged unless root
reviews a concrete required update; no new floor or skip allowance is proposed.

## Remaining proof and completion

After implementation: zero-error/zero-warning Pyright, project and tracked Ruff,
maintainability/diff checks, then all 15 new and 78 retained cases with exact host
skip attribution. Run fresh actual module/main version, inventory JSON, top-level
and convert/validate help entry points, comparing base/candidate streams and exits.
Verify actual loaded origins and Qt absence in the public-main version probe.

Run one frozen full suite with exact Godot `4.7.2.stable.official.ed1daf0bf`, required
LTS mode and all five pinned real projects. Required fixtures/engine cannot skip.
Reuse the reviewed L01 nine real CLI scenarios and same-ref control against actual
e142 and candidate: success, partial, preflight, runtime, cancellation,
initial-static, initial-diagnostic, late-repair and attempt-publication. Preserve
all output bytes/inventories/modes, logs/exits, diagnostics/outcomes/events, signal
restoration and assertions. Only the already approved case/stage paths and three
private receipt schemas may be normalized; retain raw private bytes and controls.

Measure the accepted eight public orchestration cases, 200 calls each per fresh
worker, one warmup per ref plus five measured workers per ref, interleaved. Keep
imports, setup, hashing, resets and assertions outside the timed public-main calls.
Preserve samples and median/min/max/stdev; report whole-process native peak RSS
with units. These stubbed cases cannot establish filesystem conversion speed.
Root reviews material changes and reserves the finite timing window before use.

At both PR and merge commits, verify all fifteen new public method IDs in their
exact Linux/macOS/Windows job steps with zero skips. Retain the 78 CLI cases,
native transaction/mode/N01/bind/crash, Godot and all existing required evidence.
Required collection controls must reject missing IDs, induced skips and wrong
source/cwd/prefix/origin through the existing reviewed mechanisms. No generic
runner or schema is added. Source and proof review precede integration; exact
merged CI and root ledger verification complete L02.

Adding an option changes its canonical parser/record/selection, explicit CLI
consumption and tests. Adding signal behavior changes the session and entry/model
tests. Removing either removes those exact consumers and fields without an
adapter or global registry. All old scoped owners retire within L02.

Evidence is retained under `.gm2godot-v080-evidence/L02`: final proposal index
`2ed076fc1ddd3dabd13f6071899e6f8617fbe60f78ab65bd49d95097e1e37625`, actual
entry index `81e60edc5271420ac27d3ca69685e7aa6b32d9eef0be5692396069f80e3d677d`,
independent entry review `725ca62e40b65dab7a12180ab2027005efef26fd50d9ed3822a93b20c9aa522d`,
and root entry review `36415d1cd3545f773f11824ddd892b105d3babfe64cab7cd4af0a2e770d81009`.

## Current-parent integration and accepted local proof

Root combines the immutable reviewed d3 source with verified I02 merge
`4787f4bd3a86f1ba881337fb10562ca0644d92ea`. All seven Python owners are byte-exact
d3; all392 unrelated parent Python files remain exact478, for399 Python files.
The workflow is exact478 plus the two L02 modules in each existing macOS and
Windows command. All four I02 heredocs, T01/R12 and inherited gates remain.
Root preserves the actual478 baseline and applies only the reviewed1045-to1044
reductions; no policy, coverage floor, allowance or normalization is added.

Source and complete local proof are independently/root approved. The immutable
full suite ran3139 tests in774.589 seconds:3083 successes and56 exact prior host
skips, including actual success for all five pinned projects. Six actual module/
main commands per ref matched streams and exits, with public-main Qt/origin proof.
Nine CLI cases matched at e142, same-ref and d3, with328 public file instances per
capture,501 replay bytes and all three78-ID replays. The first parity attempt
failed its ordered-ID guard before replay; only the reviewed two-line alphabetical
comparison correction passed. All twelve private controls passed with the original
three-schema projection. No failed attempt is relabeled as successful evidence.

The finite12-worker timing result has19,200 raw samples. The median sum of eight case
means increased53.50855 microseconds/+1.3483%; the largest per-call increase was
25.970 microseconds. Four conversion profiles showed positive ranges. Root accepts
this absolute one-invocation overhead; this is not real conversion throughput or
a speedup claim. Median whole-process RSS decreased1MiB and includes imports,
mocks and verification. The accepted actual configuration tests measure200/660;
the earlier198/642 entry projection above remains historical.

Original local results stay attributed to d3/e142. The new composition requires
Pyright0/0, both Ruff paths, actionlint,83 CI methods,93 CLI methods with the sole
exact existing local host skip, and strict1044 against actual478. A new immutable
native verifier package must bind all399 Python sources and exact final PR/merge
heads. Each host must execute all15 new methods with zero skips; all inherited
I02/I01/R12/T01/CLI/native artifact/mode/coverage proof remains mandatory.

Final local approval: `L02/L02-root-final-local-proof-review.json`, SHA
`fdd769a156e41c5e20580915a0c7998dfe49e8ce419c8c70766e7736adfa6e7d`.
The combined proposal is `L02/current-parent-4787f4b/review-files.json`, SHA
`1d1f902101afcad8b161d2d0b115aa875149eec420c156a8e96cbf672829542e`.
