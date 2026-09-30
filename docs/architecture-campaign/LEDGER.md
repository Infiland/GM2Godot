# v0.8.0 campaign ledger

States: planned, implementing, reviewing, changes requested, approved, integrated,
verified, blocked. The [plan](PLAN.md) and [contracts](contracts.json) bound the
54-task campaign. Historical review iterations remain in Git history.

## Current checkpoint

- Campaign baseline: main `38b364855f06e971d2676b921fd300e1f40f076a`.
- Integration branch: `dev/080-architecture-campaign`, through verified R14
  PR #897 at `b45399259c2af24a914fdfefc161ba20c44348ba`.
- Verified progress: 19 of 54 tasks (35.2%). Pending validation does not count
  as completion.
- Resumed main is clean at `cba7f52bb9aa6b68776e0342955d45d7c4fd803c`. Its
  September 14 Deep conversion work requires reconciliation at final integration.
  Twenty-six completed worktrees were removed with branches and evidence retained
  (25 campaign worktrees and one completed release worktree). Main, the campaign
  and R14 remain active; R15 uses a managed isolated worktree. R14 is retained
  until its successor source/proof bindings permit cleanup.
- Approved environment: native CPython 3.12.10 arm64 and exact Godot
  `4.7.2.stable.official.ed1daf0bf`.
- Merge the fully verified campaign into current `main`, preserving its newer
  work, then publish one final campaign release. v0.8.0 and v0.8.1 were published
  separately while the campaign was paused; their tags remain immutable. The
  final campaign release version is awaiting the user's updated preference.
- I03 has passed local full/public parity, genuine Windows proof and both exact
  PR/merge CI runs, including all retained native/runtime/CLI/artifact gates.
- R14 is verified after independent and upper-agent actual-source/result review.
  Full discovery passed with 3162 successes and 58 classified host skips; all
  five-project/fourteen-field and same-reference parity comparisons matched.
  Exact PR/merge CI, all six retained selectors and 73 selected successes per
  native host passed. The actual-parent baseline shrank from 1034 to 1033.
  Original conversion timing was 11.544% slower; its cause remains unassigned.
  The accepted source-work assessment does not claim equal latency or a speedup.
- R15's refreshed sound-model design is independently and upper-agent approved.
  `resume_main_reconciliation` owns its managed `codex/080-sound-model` checkout.
  The tracked entry authorizes external old-package preparation only after exact
  root parent/worktree binding; execution and implementation remain gated.

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
| L02 CLI request and session ownership | verified | PR #891 merged `5faa683` | Independent/root local, combined and exact CI APPROVE | PR33978428787/merge33980543144; all six native/CLI/runtime/artifact/coverage/strict-parent verifiers passed; L02/final-verification.json |
| R13 authoritative font model | verified | PR #892 merged `ae57bee` | Independent/root local, combined and exact CI APPROVE | PR33996106216/merge33998320814; all retained native/CLI/runtime/artifact/coverage/strict-parent proofs passed; R13/final-verification.json |
| I03 Included Files Windows operations | verified | PR #893 merged `74688c8` | Independent/root local, combined and exact CI APPROVE | PR34047439957/merge34049393947; Windows34/0 skips, all six retained CI verifiers and five parser controls accepted; I03/final-verification.json |
| R14 authoritative script model and source selection | verified | PR #897 merged `b453992` | Independent/root source, local, composition and exact CI APPROVE | PR36717618562/merge36761317593; 73/73/73 selected successes and 4 exact Godot cases; full/parity, qualified performance, retained native/CLI/artifact/coverage gates and strict1033; R14/final-verification.json |
| R15 authoritative sound model | planned | resume_main_reconciliation, managed codex/080-sound-model | Independent/root refreshed design APPROVE; literal old-package review pending | R15/source-refresh-M-b453992; R15-sound-contract.md; eight paths, 24 retained IDs and 12 old methods/49 arms; preparation only after bound entry |
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
  and 56 exact prior host skips, all five fixtures, six actual entry commands,
  nine CLI parity cases and same-ref, three78-ID replays and12 private controls.
  The first parity ordering failure remains failed; its reviewed two-line
  correction passed. Twelve timing workers showed up to25.97 microseconds of
  added per-call orchestration cost, accepted by root without a conversion
  speed claim. Current-parent checks and exact PR/merge proof remain pending.

- L02 prepared merge2a69dc0 has exactly the reviewed d3/478 source composition:
  598 files,399 Python files, all unchanged through its checks. Pyright 0/0,
  both Ruff paths, actionlint and strict1044 against actual478 passed. The83 CI
  methods all passed;93 CLI methods produced92 successes and the exact existing
  Windows-binding directory-relocation skip. All15 new methods passed. The saved
  combined results and independent review are approved; final PR/merge native
  proof remains pending. No original full/parity/timing run was repeated.

- R13 local proof is approved at immutable 321: the corrected 66 selection has
  zero skips; the successful full retry has 3105 successes and 56 exact prior host
  skips across 3161 tests. Both earlier failed full runs remain preserved. All
  five external projects, five-fixture fourteen-field parity and same-ref, the
  366-case matrix and 19 meaningful controls are independently/root accepted.
  Equal resource-matrix runtime warnings remain disclosed.
- R13 performance acceptance includes a material cost: 192 retained font parses
  take median 0.653276s versus 0.264205708s; whole benchmark-process peak RSS is
  190,054,400 versus50,085,888 bytes. Full recursive JSON validation and retained
  raw identity are required by the accepted model contract. The planning/output
  workload has overlapping timing ranges. No speedup, production per-worker
  peak or whole-conversion performance claim is made.
- R13 prepared merge 1a8 preserves all 13 R13 owners and all 13 incoming Python
  paths across 605 files / 405 Python files. Pyright 0/0, both Ruff checks, actionlint,
  strict baseline 1044 to 1041 and 242 focused tests passed, with only the exact
  existing Windows-only CLI skip. Original local full/parity/timing results
  retain their 321 source identity. Final metadata and exact PR/merge native
  verification remain required before R13 counts as verified.

- R13 is verified at campaign merge `ae57bee3b4ea05d2efa5e9206f2514b9dc68a292`
  after PR #892 and exact PR/merge CI runs 33996106216/33998320814. All required
  local, native, coverage and maintainability evidence is accepted in
  `R13/final-verification.json`. Campaign completion is 17/54 tasks (31.5%).
- R14 design accepted at ae57: remove the duplicated script sidecar search,
  introduce canonical model consumption in registry/discovery/aggregate, and
  preserve four path policies and the existing lexical parser. Root explicitly
  accepts the internal class defining-module/inheritance change.
  `prepare_i03_observer` owns the isolated `dev/080-script-model` worktree;
  `prepare_r13_ci` reviews independently. Only old characterization preparation
  is authorized until actual old results and source implementation scope pass
  review. The registry caller projection leaves one unit below its150 structural
  cap; complete candidate and new tests must be measured.

- R14 old characterization at `3933e07` passed 71 methods with zero skips.
  Independent and root reviews accept all callback and repeated-read records.
  Root authorizes the sole owner to implement the accepted thirteen-path design;
  candidate authority, metrics, full/parity/performance and CI proof remain pending.
  Verified campaign progress remains 17/54; this entry does not complete R14.

R14 bounded implementation review: shared script fixtures and source probes belong in `tests/script_source_support.py`, imported by the two focused test modules. Root added this fourteenth allowed path to keep test responsibilities clear while preserving all selected IDs and assertions. Production contracts and ordinary budgets are unchanged; candidate checks and independent review remain pending.

- R14 implementation is independently and upper-agent approved: 73 selected
  successes, zero skips, preserved callbacks/read arrays, Pyright zero diagnostics
  and both Ruff checks. The ae57 baseline loses one allowance and lowers six.
  Root adds only the reviewed 73 macOS and 62 missing Windows selected IDs.
  Broader full/parity/timing proof, I03 composition and native PR/merge CI remain
  pending; R14 has not earned verified-task credit.

- I03 local implementation review is approved:18 characterizations passed, the
  242-method cohort had225 successes/17exact host skips, and the39-method observer
  had35 successes/4exact Windows skips with77pairs/97generations. Those runs retain
  source110fcd94. The bounded close-answer helper correction preserves the entire
  prior module AST after inlining; all6 bindings tests pass on source1b242d30.
  Pyright0/0 and both Ruff checks pass. Baseline1044 to1037 removes7 entries and
  lowers6 without additions/growth. Root is composing verified R13 before final
  full/parity/native proof; I03 remains reviewing and is not counted as verified.

- I03 is verified at campaign merge `74688c86cb58c5e22592f9e868eba828ed064381`
  after PR #893 and CI34047439957/34049393947. The exact merged tree matches the
  approved source; all local, native and retained proof obligations passed.
  Final receipt `I03/final-verification.json` has SHA256
  `23a2c70d35980b927b58e908003a2dae697416f3e397d86c74d0671ebc282c2c`.
  Verified campaign progress is 18/54 (33.3%).

- R14 is verified at campaign merge `b45399259c2af24a914fdfefc161ba20c44348ba`
  after PR #897 and CI36717618562/36761317593. The merge has ordered I03/candidate
  parents and the exact approved candidate tree. Full discovery had 3220 tests,
  3162 successes and 58 prior host skips; required fixture/symlink and native
  selected methods had zero skips. All five-project/fourteen-field and same-ref
  comparisons matched under the unchanged R01 normalization. ResourceMatrix's
  two pre-existing compatibility warnings remain on both sides; this is parity,
  not warning-free or complete semantic proof. Six once-only merge selectors,
  ten receipts and 27 profiles were independently and upper-agent reviewed.
  The original conversion median rose by 0.26970575s (11.544%), with four of
  five measured pairs slower. Its cause remains unassigned. The finite profile
  assessment resolves missing source-work attribution; instrumented CPU/RSS
  does not replace the original timing or establish a general performance bound.
  Production physical lines fell 6031 to 6015 while structural size rose 9995
  to 10020. All 64 fresh functions meet their caps; the actual-parent ratchet
  removes one allowance and lowers six, with none added or grown (1034 to 1033).
  Final receipt `R14/final-verification.json` has SHA256
  `153626479d515bad5387bc0d55a7702f79ce5de653b91168bd3861830365ac99`.
  Verified campaign progress is 19/54 (35.2%). R15 requires a fresh parent-bound
  entry and accepted old characterization before implementation.

- R15 refreshed design is independently and upper-agent accepted at verified R14
  M and documented D. Exact scope is eight implementation paths, ten canonical
  fields, eight worker settings, eleven ordered strict values, 24 retained IDs,
  twelve old methods/49 fixed arms and two later candidate authority methods.
  Root assigns `resume_main_reconciliation` sole ownership in the managed
  `codex/080-sound-model` worktree. `R15-sound-contract.md` permits only external
  old-package preparation after root exact-entry/source/runtime binding; literal
  pre-use review precedes old execution; accepted old results precede implementation.
  Root owns baseline/workflow/campaign metadata. No R15 completion credit.
