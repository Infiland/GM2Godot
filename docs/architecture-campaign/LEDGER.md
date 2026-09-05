# v0.8.0 campaign ledger

States: planned, implementing, reviewing, changes requested, approved, integrated,
verified, blocked. The [plan](PLAN.md) and [contracts](contracts.json) bound the
54-task campaign. Historical review iterations remain in Git history.

## Current checkpoint

- Campaign baseline: main `38b364855f06e971d2676b921fd300e1f40f076a`.
- Integration branch: `dev/080-architecture-campaign`, through C01 PR #875 at
  `3579cdd`. Both its final PR and exact merge revision passed aggregate native CI.
- Main's 11 dirty policy files, preserved #820 work, and unrelated worktrees
  847/852/854/855 remain untouched.
- Approved local environment: native CPython 3.12.10 arm64 and exact Godot
  `4.7.2.stable.official.ed1daf0bf`. The primary checkout's Python 3.14 is not proof.
- Latest published release is v0.7.74. Inherited 0.7.75 metadata is an unpublished
  campaign intermediate. Root will coordinate the single final v0.8.0 release.
- No external blocker. N01 is preparing frozen review and native proof. R10 code
  is approved at `bd0967c`; immutable conversion parity is running. The remaining
  planned rows need bounded contract acceptance before implementation.

## Ownership and progress

| Task | State | Owner / candidate | Independent review | Evidence |
| --- | --- | --- | --- | --- |
| Initial audit and plan | verified | root | Three read-only investigators | Initial metrics, history and native environment receipts |
| R02 shrinking policy | verified | audit_transactions_cli, `3d2cfd0`; integrated `50e86af` | audit_policy_tests_docs and root approved | `R02/README.md`; integrated CI at `3579cdd` |
| R01 GML boundaries | verified | audit_gml_resources, `68dbf847`; integrated `edfe6df` | Independent semantic/structural review and root approved | `r01-corrections-final-index.json`, `r01-integrated-required.json`; integrated CI at `3579cdd` |
| C01 aggregate CI | verified | audit_transactions_cli, root integration corrections through `244f8aa`; PR #875 merged `3579cdd` | Independent and root reviews approved | `C01/live-final-run.json`, `C01/merge-push-run.json` |
| D01 diagnostic models | approved | audit_policy_tests_docs, `a679a2f`; root coverage ownership correction `6919ffb` | Independent and root reviews approved both scopes | PR #876 native rerun pending; `D01/coverage-owner-comparison.json` |
| N01 native receipts | implementing | audit_transactions_cli; accepted contract `5944ecf` | Independent and root reviews underway | `N01-contract-refinement.md`; native CI still required |
| R10 recursive JSON | reviewing | audit_gml_resources, `bd0967c`; accepted contract `4a60e46` | Independent and root code reviews approved | `R10/candidate-commit.json`, `R10/*-final.json`; immutable parity pending |
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
  The same saved Linux report now passes every unchanged coverage floor. A new
  exact-revision CI run remains required before integration.
- R10: final Pyright 0/0, Ruff, 287 required tests with zero skips and the
  1,338-entry gate passed. The frozen full run passed 3,017 tests with 44 native/
  filesystem skips across all five pinned projects. A subsequent one-line test
  portability correction accepts native directory-open `OSError`; all production
  hashes stayed unchanged and focused proof was rerun. Root verified source and
  log hashes. Immutable five-fixture, fourteen-field parity is still pending.
- The earlier exploratory TCC/Monophobia run overlapped root source edits and is
  not immutable baseline evidence; its explicit caveat remains with the raw log.

Full-suite times from concurrent validation are not performance comparisons.
Windows and Linux claims require their actual native CI receipts.
