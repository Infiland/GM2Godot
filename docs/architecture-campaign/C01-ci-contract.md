# C01: one exact-revision quality gate

Upper-agent plan acceptance: APPROVE for implementation after R02 integration.
Independent design review: `audit_policy_tests_docs`, 2026-09-04. One isolated
implementer owns the workflow changes; another agent reviews the final diff.

## Problem and scope

Current quality workflows run only for main. Campaign PRs need the same native
checks before integration. Publication also lacks a quality prerequisite; C01
creates the reusable gate, while C02 binds publication and the live ruleset.
No Python status polling framework or name-only remote check lookup is needed.

## Required graph

The new `ci.yml` runs on PRs to, and pushes on, `main` and
`dev/080-architecture-campaign`. It also supports `workflow_call` for later release
integration. It has seven unconditional same-revision local workflow calls:

| Call | Existing owner | Required inner jobs |
| --- | --- | --- |
| tests | `tests.yml` | `test`, `macos-managed-output-transactions`, `windows-artifact-transactions`, `windows-included-files-scale`, `windows-managed-output-crash-recovery` |
| pyright | `pyright.yml` | `pyright` |
| code-health | `code-health.yml` | `ruff` |
| godot | `godot-smoke.yml` | `godot-smoke` |
| conversion | `tcc-conversion-test.yml` | `tcc-conversion`, `lts-2026-conversion` |
| dependencies | `dependency-locks.yml` | complete three-host `generate` matrix; submission as described below |
| release-smoke | `release-action-smoke.yml` | `upload-sentinel`, `verify-sentinel`, `publisher-startup` |

Replace those owners' standalone PR/push triggers with `workflow_call` so normal
CI does not run twice. Preserve Dependency Locks' manual dispatch inputs and
locked/package/all refresh behavior. The release workflow remains unchanged in
C01; its platform builds are not yet a campaign-PR gate.

Every called workflow has an unconditional terminal job with `if: always()` and
an exact `needs` inventory. Every required result must equal `success`; failure,
cancellation, missing or skipped required jobs fail. Dependency submission may
be skipped only when its existing guarded main-push condition is inapplicable.
On a live nondeleted main push where `github.sha == github.event.after`, both the
generate matrix and submission must succeed. Preserve that full existing guard.

The top-level terminal job is named `ci-success`, needs all seven call jobs,
uses `if: always()`, and requires all seven results to be `success`. A missing
workflow cannot be interpreted as an allowed skip. Tests assert exact call and
required-inner-job inventories plus failure/cancel/skip behavior.

## Identity, permissions and lifecycle

Use local `./.github/workflows/...` calls so workflows come from the same commit
as the caller. Preserve the PR merge-base and push-before contexts used by the
R02 gate. Reusable calls retain the caller event context. Do not replace exact
checkout/source references with a floating branch.

The dependency call grants `actions: read` and `contents: write` as its maximum
permission set; the child default remains `contents: read`, and only the guarded
main-push submission receives write access. Nested workflows cannot elevate
their caller's permissions. Terminal status-only jobs use `permissions: {}`.
Release Smoke remains credentialless: no checkout credentials or real token in
the synthetic publisher test, and missing local assets must stop before an API
operation. It is safe and required on both PR and push runs.

Use different literal prefixes for caller and child concurrency groups because
`github.workflow` inside a reusable child names the caller. Preserve noncancelled
main-push execution; do not let a child cancel its own parent. Native platform
versions, immutable action pins, source/binary hashes, artifact digests, dependency
policy, coverage floors, scale gates and all runtime assertions remain intact.

## Files, proof and completion

Allowed files: `ci.yml`, the seven listed workflow owners, focused
`tests/test_ci_aggregate.py`, and necessary focused assertions in
`tests/test_ci_workflows.py` and `tests/test_documentation_health.py`. Record only
real debt reductions in the baseline; no thresholds or exclusions change.

Existing policy tests that count every Linux job or pin the former smoke trigger
must validate actual validation jobs separately from zero-permission terminal
jobs. Keep their native environment and pin assertions. Add mutation tests that
demonstrate a missing call, missing required dependency, skipped/failed/cancelled
required result, incorrectly permitted submission skip, or unsafe permission
change fails the contract.

Run exact native Pyright, Ruff, focused CI/policy tests, full unittest, ratchet,
diff check and actionlint when available. Open a narrow PR into the campaign
branch and verify the actual seven-call graph and `ci-success` on its exact
revision. Do not mark C01 verified from YAML checks alone. C02 owns main's live
required-status rule and release coupling after the reusable graph is proved.

Primary API references: [reusable workflow identity and permissions](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows),
[workflow syntax and job dependencies](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
and [required status rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).
