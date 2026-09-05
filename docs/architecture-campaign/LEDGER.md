# v0.8.0 campaign ledger

States: planned, implementing, reviewing, changes requested, approved, integrated,
verified, blocked. The [plan](PLAN.md) and [contracts](contracts.json) bound the
54-task campaign. Historical review iterations remain in Git history.

## Current checkpoint

- Campaign baseline: main `38b364855f06e971d2676b921fd300e1f40f076a`.
- Integration branch: `dev/080-architecture-campaign`, through verified I02
  PR #890 at `4787f4bd3a86f1ba881337fb10562ca0644d92ea`.
- Progress counts fully verified roadmap tasks: 15 of 54 (27.8%). Source review,
  integration and pending checks do not count as verification.
- Main's 11 dirty policy files remain untouched. Twenty-two unused worktrees
  were removed after preserving their branches/commits and required evidence;
  the main, campaign, active L02 and active R13 worktrees remain.
- Approved local environment: native CPython 3.12.10 arm64 and exact Godot
  `4.7.2.stable.official.ed1daf0bf`. Python 3.14 is not proof.
- The single final v0.8.0 release follows full campaign verification and merge
  of `dev/080-architecture-campaign` into `main`, as confirmed by the user.
- L02 source and complete local proof are approved; the reviewed combination with verified
  I02 has passed bounded checks; final native PR/merge proof is next. R13 source
  has passed65 focused tests and is under independent/root review. I03 remains
  a prospective contract with typing and characterization prerequisites.

## Ownership and progress

| Task | State | Owner / candidate | Independent review | Evidence |
| --- | --- | --- | --- | --- |
| Initial audit and plan | verified | root | Three read-only investigators | Initial metrics, history and native environment receipts |
| R02 shrinking policy | verified | audit_transactions_cli, `3d2cfd0`; integrated `50e86af` | audit_policy_tests_docs and root approved | `R02/README.md`; integrated CI at `3579cdd` |
| R01 GML boundaries | verified | audit_gml_resources, `68dbf847`; integrated `edfe6df` | Independent semantic/structural review and root approved | `r01-corrections-final-index.json`, `r01-integrated-required.json`; integrated CI at `3579cdd` |
| C01 aggregate CI | verified | audit_transactions_cli, root integration corrections through `244f8aa`; PR #875 merged `3579cdd` | Independent and root reviews approved | `C01/live-final-run.json`, `C01/merge-push-run.json` |
| D01 diagnostic models | verified | audit_policy_tests_docs, `a679a2f`; PR #876 merged `c2d55e6` | Independent and root reviews approved extraction and coverage correction | `D01/live-final-run.json`, `D01/merge-push-run.json` |
| N01 native receipts | verified | audit_transactions_cli, `66bfcfe`; reviewed corrections through `b06c15b`; PR #879 merged `47642d8` | Independent and root code/integration reviews approved | `N01/pr-ci-final.json`, `N01/merge-push-run.json`; six zero-skip native artifacts at each exact revision |
| R10 recursive JSON | verified | audit_gml_resources, `bd0967c`; root integration `e56a5e3`; PR #878 merged `91a33c1` | Independent and root code/integration reviews approved | `R10/pr-ci-final.json`, `R10/merge-push-run.json`; both immutable parity runs match |
| R03 E4/E7 lint | verified | audit_transactions_cli, `356e2ae`; PR #880 merged `1240a7b` | Independent and root code/integration reviews approved | Final PR and merge CI; exact native 6/6/2 zero-skip proof at both revisions |
| R04 import layout | verified | Initial PR #881 at `f40402c`; cleanup PR #883 at `feb22c3` | Independent and root actual-code and metadata reviews approved | Cleanup PR CI `33943223988`, merge CI `33943927132`; exact native artifacts and actual-parent receipts verified |
| I01 Included Files models and planning | verified | audit_transactions_cli, `93d6ac8`; PR #884 merged `475e96e` | Independent and root actual-code and metadata APPROVE | PR CI `33946483807` and merge CI `33947905402`; all 31 required native/runtime cases and six native artifacts passed at both exact revisions |
| R11 Authoritative project resource model | verified | audit_gml_resources; PR #885 merged `1196295` | Independent/root source, local-proof and combined-metadata APPROVE | PR CI33948869821 and merge CI33949869128; exact native receipts/mode cases, all26 new methods/zero skips, actual-parent1056 gate passed |
| G01 GML typed lowering context | verified | audit_policy_tests_docs; PR #886 merged `7fdd97c` | Independent/root source, corrected proof and combined metadata APPROVE | PR CI33951220652 and merge CI33952438794; six native artifacts, mode cases and all49 selected tests/zero skips; actual-parent1055 gate |
| L01 CLI artifact ownership | verified | audit_transactions_cli; PR #887 merged `7dd2b9c` | Independent/root source, corrections and final proof APPROVE | PR CI33958314011 and merge CI33959387452; exact native CLI/Converter/crash/bind, six N01 receipts, mode cases, two preflight guards and unchanged coverage floors; strict1047 actual7fdd |
| T01 exact Godot test discovery | verified | audit_policy_tests_docs; PR #888 merged `e142714` | Independent/root source, guarded-parent and exact CI proof APPROVE | PR CI33960637423 and merge CI33961965330;65 runtime cases in Linux Godot and12 helpers per native host,0skips; six receipts, mode/CLI/guards/crash/bind/coverage and strict1045 actual7dd |
| R12 authoritative path model | verified | audit_gml_resources; PR #889 merged b9c05cd | Independent/root source, local, combined and exact CI proof APPROVE | PR33964091840/merge33965005168;35 required/0skips, retainedT01/native/CLI/strict1045; external R12/final-verification.json |
| I02 Included Files POSIX operations | verified | audit_transactions_cli; PR #890 merged4787f4b | Independent/root source, local, combined and exact CI APPROVE | PR33968388651/merge33971661125;50new+31retained native/runtime, R12/T01/CLI/artifacts/modes/coverage,strict1045actualb9; I02/final-verification.json |
| L02 CLI request and session ownership | approved | audit_policy_tests_docs; sourced3a05b2, root combination with4787f4b | Independent/root source, final local and actual combined proof APPROVE |3139full/56known skips,all5fixtures,6entry commands,nine-case parity/same-ref,12controls,12timing workers; L02/L02-root-final-local-proof-review.json |
| Other rows | planned | Assigned after contract acceptance | Independent reviewer, then root | `contracts.json` |

Raw evidence is retained outside the worktrees at
`/Users/infi/Documents/Github/.gm2godot-v080-evidence`.

## Accepted decisions

1. Repair the existing policy rather than introduce another framework. Schema 2
   preserves the original 1,014 debt entries and measures 350 structural entries
   from the same immutable baseline. Parent Git evidence, structural vocabulary,
   suppression detection and proportional physical allowances prevent packing,
   relocation and incremental baseline laundering. No new allowance is accepted.
2. Preserve #820 as provenance. R01 integrates its behavior with the newer policy;
   it does not publish 0.7.75. Its helper split has explicit direct imports and
   keeps all fourteen parity fields. Test helpers cannot become app dependencies.
3. C01 uses seven unconditional same-commit reusable calls and explicit terminal
   result inventories. Existing native jobs, pins, submission guard and coverage
   remain intact. A real campaign PR must prove the aggregate before verification.
4. D01 moves four immutable records into one stdlib-only leaf without changing
   constructors, report bytes, messages, mapping or deduplication. Three temporary
   exports have named family/Included Files/CLI consumers and retire by R26.
   Removing the obsolete bootstrap from `test_base_converter` avoids adding lint
   debt when its import moves to the canonical owner.
   Its extracted leaf stays in both original coverage cohorts; thresholds and
   existing patterns are unchanged. The saved Linux report proves all original
   missing-line and branch counts are unchanged and the leaf is fully covered.
5. Native receipt #860 remains a prerequisite for Included Files decomposition.
   Modeled Windows tests do not establish NTFS proof. Existing safety ownership
   and platform durability guarantees remain explicit.
6. R26 waits for all family migrations, I10, E01 and L03. New unrelated findings
   receive separate issues; they do not expand this finite roadmap.
7. Root opened #877 for early Included Files recovery/snapshot interruption that
   bypasses lock release. It needs its own regression and reviewed behavior-fix
   scope in the existing locking/coordinator work; I01 must not hide the fix.
8. R03 owns the exact 199 E4/E7 findings and native chmod proof. R04 remains a
   separate import pass. R05 follows R04/R26 so remaining reflective test seams
   and exception ownership are stable; W02 waits for final R05 enforcement.
   Existing I001/B debt checks continue throughout. No task or limit is removed.

9. After independent review, root accepts [conditional parallel implementation entry](R04-parallel-entry-contract.md)
   for R11/I01/G01 from approved frozen cleanup candidate C. All entry checks and
   explicit isolated assignments remain required. Child PRs/integration wait for
   successful cleanup merge proof. Root serializes baseline and shared metadata.

## Validation checkpoint

- Initial unchanged-production baseline at `7141a27`: 2,897 tests passed in
  409.879 seconds with exact Godot and pinned SNAP, Adding and SimpleTopDown;
  70 platform or optional-corpus skips were recorded.
- R02: Pyright 0 errors/warnings, Ruff, 58 focused/documentation tests and full
  2,943-test suite passed. Its 78 skips include eight unavailable external-fixture
  skips beyond the baseline. Gate passed 1,364 exact entries.
- R01 at immutable `68dbf847`: 594 required tests passed with zero skips; full
  2,932-test suite passed with 70 classified platform/optional-corpus skips.
  Main-to-candidate and same-ref comparisons matched across five fixtures and all
  fourteen fields; all 44 public exports were preserved. Root verified 19 evidence
  hashes and integrated source identity, then reran Pyright, Ruff, 60 policy/doc/
  version tests and 594 required tests with zero skips. Debt fell to 1,341 entries.
- R01's bounded utility benchmark used 50 SNAP sources and recorded every sample,
  input hash and peak RSS. Median changes were comments +3.18%, assignment -7.43%,
  split +3.86%; RSS was 24.33/24.23 MB. This is not a converter performance claim.
- C01 at immutable `8a76561`: Pyright 0/0, Ruff, actionlint, 94 focused tests and
  all 2,950 full-suite tests passed. All five pinned external projects ran;
  44 skips were platform/filesystem-specific. All 15 prior validation job bodies
  were unchanged. Independent adversarial aggregate tests passed.
- C01 root integration added the already-pinned Ruff to the Linux full-test
  environment because R02's real metric probes invoke it. Independent review,
  Pyright 0/0, Ruff/actionlint and 95 CI/workflow/documentation tests passed.
  Final PR run `33927363926` at `244f8aa` and merge run `33928650923` at `3579cdd`
  each passed 24 checks, including `ci-success`; only the explicitly permitted
  non-main dependency-submission job skipped.
- D01 at immutable `a679a2f`: Pyright 0/0, Ruff, 117 focused tests and 2,951 full
  tests passed. All five pinned external projects ran; 44 skips were platform/
  filesystem-specific. Four moved records have exact AST equivalence and existing
  JSON/Markdown report bytes match. Candidate file hashes stayed frozen throughout.
- D01's first native CI ran all unit/native/Godot/conversion checks successfully;
  two coverage groups omitted the moved fully covered leaf. The correction passed
  independent review, Pyright 0/0, Ruff, 26 focused tests and the 1,340-entry gate.
  The same saved Linux report now passes every unchanged coverage floor.
  Final PR run `33929950992` at `7a27ccd` and merge run `33931958726` at `c2d55e6`
  each passed 24 checks and the explicitly permitted dependency submission skip.
- R10: final Pyright 0/0, Ruff, 287 required tests with zero skips and the
  1,338-entry gate passed. The frozen full run passed 3,017 tests with 44 native/
  filesystem skips across all five pinned projects. A subsequent one-line test
  portability correction accepts native directory-open `OSError`; all production
  hashes stayed unchanged and focused proof was rerun. Root verified source and
  log hashes. Immutable base/candidate and same-reference comparisons match across
  five fixtures and all fourteen fields, including the 44-export facade contract.
  Final PR CI `33932635435` at `e56a5e3` passed all 24 required checks; merge CI
  `33933858620` at `91a33c1` passed all 24 required checks and the sole permitted
  dependency-submission skip. The merge tree equals the approved PR tree.
- N01's frozen full run passed 3,031 tests with 56 classified native/filesystem
  skips across all five external projects. Reviewed follow-up corrections preserve
  legacy native newline bytes and assert the actual NT directory handle chain.
  At `b06c15b`, CI `33933576033` produced all six required receipts: Linux 10,
  macOS 13 and Windows 16 tests, each executed twice with zero skips. Root verified
  exact selected methods, success fields and artifact hashes. After combining R10,
  Pyright 0/0, Ruff, 131 focused tests, 287 R10 required tests, 13 required macOS
  receipt tests and the 1,338-entry gate passed. All six native receipts also
  passed at final combined `6066856` in run `33934278689` and merged `47642d8`
  in run `33935348197`, with zero skips. Both runs passed all 24 required checks
  and the sole permitted dependency-submission skip. The merge tree equals the
  approved PR tree. Issues #860/#844 remain open for final main integration and
  actual release-environment evidence owned by C02/V02; #859 remains completed.
- R03 at immutable `356e2ae`: all 199 E4/E7 findings removed; Pyright 0/0,
  normal/tracked Ruff, actionlint and the 1,269-entry gate passed. The 287 focused
  tests passed with ten ordinary platform skips. All six required macOS artifact
  methods passed without skips, including real descriptor rollback and closure.
  Independent review ran 119 tests without skips. The frozen full run passed
  3,062 tests across all five pinned projects: 53 Windows-only skips, two Linux
  bind-mount cases and one case-sensitive-filesystem case. All 72 reviewed file
  hashes stayed unchanged. Exactly 1,472 original cohort/policy/artifact test IDs
  remain, with five authorized additions. N01 ancestry merge `456877c` has the
  identical owner tree. Final PR CI `33936762868` at `f1781fc` passed all 24 required
  checks and the sole permitted dependency-submission skip. Native logs prove
  Linux six, macOS six and Windows two actual executions with zero skips. Merge
  `1240a7b` has the approved tree; merge CI `33937769395` passed all 24 required
  checks and the sole permitted dependency-submission skip. Exact merge native
  logs also prove Linux six, macOS six and Windows two executions with zero skips.
- R04 at immutable `ef75836`: the 244-file import cohort plus eleven infrastructure
  files, with three overlapping paths, match the accepted 252-path scope. Project, tracked-input
  CI and isolated metrics use the same explicit layout. All 213 I001 debt entries
  disappear; 1,056 entries remain without any new or increased allowance. Root
  verified all 372 source hashes, 367 import-only ASTs and the unchanged policy
  protections. Independent review passed 80 tests with zero skips; owner focused
  checks passed 398 with one Windows-only skip, and native macOS passed 13/13.
  Pyright reports zero errors/warnings; both Ruff paths, actionlint and the strict
  parent gate pass. The frozen full suite passed 3,064 tests on exact Godot with
  all five pinned projects and 56 classified skips (53 Windows, two Linux bind
  mounts, one case-sensitive-filesystem case). Final PR/merge CI and the separate
  exact-parent bridge deletion remain required; this row is not yet verified.
- The earlier exploratory TCC/Monophobia run overlapped root source edits and is
  not immutable baseline evidence; its explicit caveat remains with the raw log.

- R04 initial PR #881 at `fef28b6` and merge `f40402c` passed CI `33939639226`
  and `33941403378`: 24 successful jobs and the sole permitted dependency submission
  skip. Native receipt methods passed twice per platform (10/13/16), and artifact
  mode tests passed Linux/macOS 6 each and Windows 2, all without skips. Both actual
  parent comparisons resolved `1240a7b`; the merge tree matches the reviewed PR.
  Cleanup begins from the complete new-policy `f40402c` baseline with 1,056 entries.

- R04 cleanup `bfe9b1f` matches the four-file reviewed projection. Independent and
  root actual-code reviews approve; Pyright 0/0, both Ruff paths, 61 focused tests
  with zero skips and the 1,056-entry strict gate pass. Actual S `f40402c` accepts;
  baseline-bearing legacy P `1240a7b` rejects. Bootstrap, baseline/debt/evidence,
  all five R03 test bodies and the other 370 source files remain unchanged.
  Required cleanup PR and merge CI/native proof remain outstanding.

Full-suite times from concurrent validation are not performance comparisons.
Windows and Linux claims require their actual native CI receipts.

- R04 cleanup PR #883 and merge `feb22c3` each passed 25 strict CI jobs (24 success,
  one permitted dependency-submission skip), six exact-head native receipt artifacts,
  native mode selections 6/6/2 with zero skips, and strict comparison against actual
  parent `f40402c`. The temporary legacy-policy exception is removed.

- I02 final PR #890 and merge4787f4b are verified. Both exact CI runs passed
  the50 I02 and31 retained I01 native/runtime selections, all retained R12/T01,
  CLI, artifacts, mode, coverage and strict1045 actual-b9 proof. No modeled or
  skipped test was credited as native success. The approved PR and merge trees
  match; immutable evidence is `I02/final-verification.json`.
- L02 local proof is approved at d3 against e142:3139 tests with3083 successes
  and56 exact prior host skips, all five fixtures, six actual entry commands,
  nine CLI parity cases and same-ref, three78-ID replays and12 private controls.
  The first parity ordering failure remains failed; its reviewed two-line
  correction passed. Twelve timing workers showed up to25.97 microseconds of
  added per-call orchestration cost, accepted by root without a conversion
  speed claim. Current-parent checks and exact PR/merge proof remain pending.

- L02 prepared merge2a69dc0 has exactly the reviewed d3/478 source composition:
  598 files,399 Python files, all unchanged through its checks. Pyright0/0,
  both Ruff paths, actionlint and strict1044 against actual478 passed. The83 CI
  methods all passed;93 CLI methods produced92 successes and the exact existing
  Windows-binding directory-relocation skip. All15 new methods passed. The saved
  combined results and independent review are approved; final PR/merge native
  proof remains pending. No original full/parity/timing run was repeated.
