# R04 bridge retirement — accepted cleanup contract

Status: ACCEPTED by root after independent contract review and successful initial R04 PR #881 and merge verification. Fixed cleanup parent S is `f40402cebc7f4820571f6f54febd78c7f9c17e6a`. PR CI `33939639226` and merge CI `33941403378` each passed all 24 required jobs and the sole permitted dependency-submission skip; native receipts and 6/6/2 artifact-mode proofs passed with zero skips. The four source hashes and complete new-policy baseline are frozen in the external `cleanup-entry.json`. One implementation owner: audit_policy_tests_docs in this isolated cleanup worktree. Independent actual-code reviewer: audit_transactions_cli, then root. Root owns campaign metadata and commits/integration.

## Exact scope

Four files change:

1. scripts/check_maintainability.py: remove its unused hashlib import, the R04 transition comment and both LEGACY_IMPORT_LAYOUT_* constants. In parent_debt replace only the raw-byte/hash/legacy-policy selection with the original strict `return load_baseline(git(root, "show", f"{revision}:{BASELINE_PATH}").decode(), policy(root))`. Preserve Git ref resolution, ancestor validation, baseline existence checks and the exact missing-baseline BOOTSTRAP_REF=38b364855f06e971d2676b921fd300e1f40f076a branch. load_baseline, policy, IMPORT_LAYOUT, measurement/retention and every budget remain unchanged.
2. tests/test_maintainability_metrics.py: remove its now-unused hashlib import. Delete TestMaintainabilityParent.test_import_layout_bridge_requires_exact_git_parent_and_raw_bytes and replace it with test_legacy_import_layout_candidates_and_git_parents_are_rejected. The permanent test builds an otherwise valid baseline omitting only import_layout, proves direct candidate loading rejects it, and proves resolved baseline-bearing Git parent loading rejects it. Keep json for this real payload. No frozen-parent/hash constant or acceptance branch remains in tests.
3. CONTRIBUTING.md: replace its six-line R04 bridge/explicit-P guidance with normal strict candidate/baseline-bearing-parent policy guidance and retained formatting-only size accounting. The missing-baseline bootstrap is not described as rejected. Existing general HEAD examples again apply to normal new-policy development.
4. todo-list/07-testing-codebase-improvements.md: remove only the appended temporary-bridge pending sentence from the already-completed import-sorting item. Root campaign metadata, rather than this implementation item, controls final R04 verification.

The only optional fifth allowed file is maintainability-baseline.json, and only if the ordinary strict generator produces actual reductions/current evidence at the real cleanup base. The full projected measurement shows byte-equivalent debt and retained size evidence, so no baseline edit is presently expected. No policy-metadata rewrite, allowance, new owner, new test module, helper or parent fallback is permitted.

Root owns all campaign contracts/ledger/status updates. docs/wiki/Contributing-and-Testing.md contains only the permanent selected-layout guidance and needs no cleanup edit. Neither tests/test_maintainability_policy.py nor the production metrics module needs an edit. No source, converter, native transaction, workflow, runtime pin, receipt inventory or release change is part of this cleanup.

## Permanent controls and exact parent proof

Retain the current three real-Ruff layout regressions, mutation rejection for each import-layout field, exact project/workflow settings, unknown/nonancestor rejection, missing-parent versus the one 38b bootstrap control, pinned/isolated measurement, suppression protection, packing/proportional-retention and stale-debt tests. Preserve all five R03-added test bodies.

The new named test explicitly retains both legacy-candidate and legacy-baseline-parent rejection after the temporary acceptance test is deleted. It uses a resolved mock parent solely to isolate policy validation, alongside the existing normal new-policy parent-load test. There is no permissive legacy case, obsolete pinned P constant or test-only compatibility route.

For executed Git proof, the external projected checker already accepts the real new-policy owner commit ef758360d91e96f2df0a72fc17769e7e5ed77c09 and rejects historical baseline-bearing P (`1240a7b16d893bc06ba3d258683c731c60dbadca`) with the policy mismatch. The existing bootstrap constant and branch are unchanged. This is current-ref preflight, not a future integration receipt.

Cleanup entry is frozen at integrated new-policy S `f40402cebc7f4820571f6f54febd78c7f9c17e6a` after successful initial PR and merge proof. Before cleanup PR/push dispatch, record the actual local comparison ref, PR event merge-base and push event.before. Each baseline-bearing comparison must carry the complete current policy and satisfy normal ancestry; the ordinary strict loader applies to all of them. They need no new constants or exceptional selection. If a live event still requires legacy P, defer the cleanup until that event is complete. C02/V01 retains final main/missing-baseline bootstrap verification.

## Measured projection and validation

| Owner | Before physical / structural | After physical / structural | Limit |
| --- | ---: | ---: | ---: |
| scripts/check_maintainability.py | 277 / 775 | 266 / 760 | 800 / 800 |
| tests/test_maintainability_metrics.py | 414 / 1460 | 399 / 1405 | 1500 / 1500 |

All other Python bytes remain the frozen initial R04 candidate. The real measurement over all 372 composed source files yields exactly the same 1,056 debt entries and identical retained size evidence: new_debt=[], no baseline change required. These are removal counts, with no architecture decomposition claim.

The external capsule passes native Pyright (0 errors, 0 warnings), project Ruff and all 49 existing policy/metrics tests with zero skips. The new strict rejection method runs with the unchanged permanent controls. The receipt also verifies real new-policy owner-ref acceptance and old baseline-bearing P rejection. This does not substitute for implementation checks tied to the actual later cleanup base.

After implementation, run full native Pyright --warnings, normal/tracked Ruff, the existing policy/metrics/documentation tests, strict nonwriting gate against the actual S comparison (and --update only if real reductions require it), diff checks and the two actual Git acceptance/rejection controls. Root must inspect the actual small diff, obtain independent code approval and verify the required cleanup PR and integration CI receipts. Existing workflows remain authoritative for their full-suite/native/artifact/Godot checks; no skip or inventory relaxation is permitted. Freeze code before those receipts.

Completion requires the initial R04 merge proof plus the separate cleanup commit's approved exact diff, all required cleanup checks and actual local/PR/push comparison evidence. No bridge constant, raw-hash guard or temporary acceptance test may remain before V01/release.

## Frozen artifacts

cleanup-projection.patch and cleanup-projection.json contain exactly the four projected edits and their before/after hashes. preview/ contains those files and unchanged support copies for the bounded checks. maintainability-and-parent-proof.json records all 372-source measurement and actual Git preflight. pyright.log, ruff.log and focused.log contain executed results. cleanup-review-files.json freezes this contract, the four candidate files, patch, metrics and receipts. The actual integrated cleanup base is S `f40402cebc7f4820571f6f54febd78c7f9c17e6a`; root verified the initial merge before this assignment.
