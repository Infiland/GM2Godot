# v0.8.0 campaign ledger

States: planned, implementing, reviewing, changes requested, approved, integrated,
verified, blocked. The [plan](PLAN.md) and [contracts](contracts.json) bound scope.

## Current checkpoint

- Campaign baseline: main/remote `38b364855f06e971d2676b921fd300e1f40f076a`.
- Integration worktree: `GM2Godot-080`, branch `dev/080-architecture-campaign`.
- Initial audit complete across history, ownership, graphs, complexity, GML,
  resources, transactions, CLI, diagnostics, tests/runtime, packaging, CI/release
  and documentation. Three independent read-only investigators contributed.
- Main's 11 dirty policy files and four unrelated worktrees remain preserved.
- Environment: native CPython 3.12.10 arm64 complete dependency receipt passed;
  Godot exact 4.7.2 build verified. Primary checkout's Python 3.14 is not release
  evidence.
- R02 initial verdict: REQUEST CHANGES. Embedded comment suppressions bypass the
  scanner; equivalent AST line packing erases size debt. Current 32 tests and
  1,014-entry gate pass, demonstrating missing assertions rather than acceptance.
- R01 GML review: APPROVE at preserved `6e86c3f`; 44 exports and exact parity
  evidence verified. Integration verdict: REQUEST CHANGES for 14 newly measured
  debt entries (including legitimate renamed function keys, helper lint/nesting
  and preprocessor size). No separate 0.7.75 release.
- Latest release remains v0.7.74. No v0.8.0 tag or release has been created.

## Decisions

1. Reuse and repair existing R02 policy; do not create another framework.
2. Preserve #820 as provenance; implement integration corrections in a new
   worktree. Root alone reconciles its unpublished version surfaces.
3. Native receipt #860 is an explicit prerequisite, not assumed complete from
   earlier transaction CI. Unrelated 847/852/854/855 work stays with its owner.
4. Keep existing structured diagnostics and explicit phase APIs. No new generic
   registries, reflective dispatch or general Python name-resolution engine.
5. Accept R01 and R02 task contracts for implementation after initial package
   publication. Remaining contracts are planned and receive a bounded refresh
   and explicit upper acceptance immediately before their owner starts.

## Task progress

| Task | State | Implementation owner | Independent reviewer | Evidence |
| --- | --- | --- | --- | --- |
| Initial audit/plan | verified | root | three read-only investigators | initial-metrics.json, issue/pr history, native-environment.json |
| R02 | integrated | audit_transactions_cli, GM2Godot-080-policy | audit_policy_tests_docs + root | two reproduced bypasses |
| R01 | implementing | audit_gml_resources, GM2Godot-080-gml | policy/test reviewer + root | preserved 6e86c3f, r01-new-debt.json |
| Remaining contracts | planned | assigned at contract acceptance | independent owner + root | see contracts.json |

R02 is integrated locally; native campaign CI verification follows through C01. Other implementation tasks remain unintegrated.

Plan review requested explicit particles/extensions/alias-retirement rows, serialization edges, slice-specific G01 targets, pre-extraction I01 state inventory, complete G05 structured-family ownership and measured time/memory evidence. Root incorporated these findings; the finite roadmap now has 54 rows. R02 repairs may proceed independently.

## Validation checkpoint

- Fresh unchanged-production baseline at planning commit 7141a27: full unittest passed, 2,897 tests in 409.879 seconds, 70 recorded platform/optional skips, using exact Godot and pinned SNAP/Adding/SimpleTopDown fixtures. Receipt: baseline-full-unittest.log.
- R01 initial correction review approved semantics: independent 59-test cohort and 16,011 base/candidate lexical comparisons passed. The owner is refining a measured split_top_level performance regression before freezing the final candidate. This review is not final integrated acceptance.
- R02 v2 design accepted: formatting-independent size evidence, retained effective physical allowance where structure does not shrink, immutable bootstrap, and structural debt for packed new destinations. Comment/import-only shortening is allowed but receives no structural improvement credit.
- C01 exact job/permission/concurrency contract accepted at C01-ci-contract.md; implementation waits for R02.

- R01 lexical overhead fixed; final bounded50-source benchmark has per-sample timings/input hashes and peak memory: medians comments+3.18%, assignment-7.43%, split+3.86%, RSS24.33/24.23MB. This is a utility microbenchmark, not a converter speed claim. Root accepted one cohesive output-snapshot helper extraction to meet R02 structural budget; normalization and all fourteen comparison fields remain frozen.
- R02 independent trust review additionally required packed expression relocation coverage; the structural vocabulary now includes expression operations/comprehension clauses. Integration remains pending review.

- R02 final implementation is under read-only review. Its bounded size helper and schema 2 are accepted; immutable bootstrap now records the original 1,014 entries unchanged plus 350 structural-size entries from the same old source. No new implementation allowance is accepted. Native full-suite proof is running.
- R01 additional helper contracts accepted: typed manifest parsing stays in conversion_parity_contract; runtime/fixture identity moves to conversion_parity_inputs; output comparison stays in conversion_parity_snapshot with its own tests; facade contract checks move to gml_facade_contract_support and depend directly on the import scanner. Both test helpers remain forbidden application dependencies. Native receipt task N01 explicitly waits for the existing required-test runner from R01.

- R02 approved by independent reviewer and root, committed as 3d2cfd0 and integrated as 50e86af. Pyright 0 errors/warnings, Ruff, 58 focused/documentation tests, full unittest 2,943 tests in 369.135s passed. Its 78 skips include 8 external-fixture skips compared with the initial fixture-enabled baseline; exact Godot was present. No claim of a zero-skip or fixture-enabled R02 full run. Integrated gate passes 1,364 entries against immutable 38b. Evidence: R02/README.md and raw receipts.
- C01 implementation assigned to audit_transactions_cli in isolated GM2Godot-080-ci on dev/080-ci-aggregate. Accepted C01-ci-contract.md is authoritative. Root prepared verified official actionlint 1.7.12 darwin/arm64 tool in external evidence tools directory; no project dependency changes. Independent review and a real campaign PR are required before verification.
