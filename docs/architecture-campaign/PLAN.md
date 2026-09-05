# GM2Godot v0.8.0 architecture campaign

This is the bounded implementation plan for issue #867. The September 4, 2026
objective supersedes the earlier per-slice release plan: publish one completed
v0.8.0. A planned row is not a completion claim. The [ledger](LEDGER.md) records
actual approval, integration and verification. [Task contracts](contracts.json)
define ownership, scope, dependencies and proof before implementation.

## Verified starting point

- Main and the live remote are `38b364855f06e971d2676b921fd300e1f40f076a`.
  The published release is v0.7.74 at that revision. Its seven workflow runs
  passed (Tests, Pyright, Code Health, Godot Headless Smoke, TCC Conversion Test,
  Dependency Locks, Build and Release). No PR is open; v0.7.75 and v0.8.0 tags
  are absent remotely.
- Main has 11 uncommitted maintainability-policy files. They remain untouched;
  an exact copy and binary patch were saved outside the checkout. R02 owns their
  reviewed integration. They are not a new independent policy proposal.
- `GM2Godot-820`, branch `dev/820-gml-facade-zero-private`, is clean at
  `6e86c3f0f6bf360600dd96900e12eba2c3282929`. R01 preserves this implementation
  and reviews its integration. Its unpublished 0.7.75 metadata will be reconciled
  by the release owner; it will not trigger a separate release.
- Worktrees 847 (`e9541c9`), 852 (`8e56998`), 854 (`916ef80`) and 855 (`98f97ab`)
  are clean with unique work. Their matching issues retain ownership; they are
  outside this campaign, must not be overwritten or deleted, and are not evidence
  of merged work. Intel macOS packaging and Wiki publication remain separately
  owned. The release must accurately state its actual architecture support.
- #850 is closed via #863. Exact Godot migration #869 and GML/manual work
  #870–#874 are merged. #794, #795, #797, #798, #817 and #820 remain open.
  Close parents only when all their requirements are proved.
- #859 is merged via #866. #844 and its native receipt child #860 remain open.
  N01 owns this prerequisite before Included Files implementation begins.
- Repository ruleset 1249039 requires PRs and blocks deletion/non-fast-forward
  updates, but requires no status checks. The authenticated maintainer has admin
  permission. C02 must add and verify the aggregate requirement without removing
  existing rules or using the admin bypass to integrate unverified work.

The main checkout's `venv` is Python 3.14.7, not the native baseline. Campaign
worktrees use the existing verified macOS arm64 CPython 3.12.10 environment,
Pyright 1.1.411 and Ruff 0.15.22. A fresh complete dependency receipt passed.
The installed engine reports exactly `4.7.2.stable.official.ed1daf0bf`.

## Fresh measurements and proof inventory

Measurements use the existing policy's Python 3.12 AST and pinned Ruff against
342 tracked Python inputs, including 141 `src` modules. The initial policy
records 1,014 exact debt entries; 64 application functions exceed complexity 15,
as do 24 tooling and five test functions. These counts include legacy debt,
not allowances for new code.

| Owner | Lines | Largest relevant function | Function lines | Complexity |
| --- | ---: | --- | ---: | ---: |
| `included_files.py` | 12,130 | `IncludedFilesConverter.convert_included_files` | 541 | 52 |
| `included_files.py` | same | `_commit_included_output_set` | 486 | 35 |
| `included_files.py` | same | `_cleanup_recorded_included_tree` | 430 | 46 |
| `gml_transpiler_parts/statements.py` | 2,771 | `transpile_statement` | 1,161 | 122 |
| `cli.py` | 1,411 | `_run_convert` | 579 | 98 |
| `cli.py` | same | nested `repair_conversion_reports` | 141 | 28 |
| `tests/test_included_files.py` | 12,914 | transaction tests | measured per slice | — |
| `tests/test_cli.py` | 3,611 | CLI lifecycle tests | measured per slice | — |

The syntax graph has 548 static edges and 541 eager edges. There are 15 elementary
static cycles in four strongly connected components, and one eager cycle:

1. `fonts -> asset_output_paths -> asset_registry -> fonts` (wrong ownership).
2. `project_manifest <-> project_source_paths` (model/loader coupling).
3. Eight GML grammar modules (includes legitimate deferred recursive function-body
   parsing; document that recursion and verify actual import orders).
4. `events.__init__ <-> events.registry` (package import ownership).

Graphs are syntax-derived, conservative for conditionals and incomplete for
computed imports. Structural gates supplement, and do not replace, actual import
orders and conversions. R10/R13/E01 eliminate avoidable ownership cycles; recursive
grammar calls must remain explicit and cycle-safe. No new cycles are permitted.

Resource models are not yet authoritative production input. `type_defs.py` still
defines `JsonValue = Any`, and converter families repeat dictionary parsing.
R10 establishes recursive JSON validation and source-aware field paths; R11–R26
migrate one family at a time, retaining validated unknown fields.

There are 43 local Godot finder definitions (37 identical), 51 `_write_text`
definitions, 47 independent binary/environment checks, and 64 test files that
alter `sys.path`. Test support must consolidate real duplication while keeping
assertions visible. Packaging has no build-system/project metadata or console
entry points; source imports do not prove installability.

Fresh baseline proof: five CPython 3.12.10/exact-Godot tests passed for real CLI
resource-matrix conversion/import/load, math and seeded-random runtime behavior,
named constructor inheritance/source lines, and golden output/maps/diagnostics.
Prior #820 receipts were reconciled to its exact commit and verified by hashes:
590 required tests with zero skips; 2,925 full tests with 82 explicitly recorded
platform/optional skips; five same-path fixture parity comparisons including
runtime markers, plus same-ref control comparisons. A fresh independent #820
check preserves the 44 exports, order, identity owners, signatures and list
container; 13 architecture tests pass. This is scoped local evidence, not PR CI.

Pinned SNAP, Adding and SimpleTopDown checkouts and prior receipts are available
in the preserved campaign evidence directory. Native Windows/Linux cases must
run on those hosts; macOS or modeled platform tests cannot satisfy them.

## Target ownership

```text
CLI/GUI presentation -> conversion plan/context -> converters -> output writers
                                              -> resource family models
JSON loading -> recursive validation -> typed resource models -> converters
resource/path models -> source resolution and manifest loading (no reverse edge)

GML public facade -> typed lexical/expression/statement APIs
statement API -> parser -> explicit statement handlers -> expression API
shared typed state owns scope, generated names, static/loop/source-map context

Included Files facade -> transaction coordinator
coordinator -> planning / snapshot / staging / publication / recovery
planning, snapshot, staging, publication, recovery -> models and platform ops
recovery -> journal parser; POSIX/Windows -> dependency-only models
models never import transaction services; platform ops never import facade

test domains -> small Godot/fixture/process helpers -> stdlib and public APIs
CI aggregate -> all required validations at one exact revision -> release gate
```

Diagnostics already have stable code/severity/location/resource context. D01
reuses that model, separates parse-only diagnostic ownership from report I/O and
adds phase only where a producer needs it without changing existing serialization
or messages accidentally. No parallel diagnostic registry is authorized.

## Finite roadmap

Rows are task boundaries, not permission to broaden their allowed files. Shared resource/registry, Included Files monolith and GML dispatcher edits are explicitly serialized; independent branches never own the same file concurrently. Each
resource family is a separate review. Later discovery outside these rows goes to
a separate issue, except a demonstrated prerequisite blocking a listed guarantee.

| IDs | Outcome | Dependency |
| --- | --- | --- |
| R02 | Repair and integrate existing shrinking debt gate | initial audit |
| R01 | Integrate reviewed #820; resolve new-policy debt conflicts | R02 |
| C01 | Run all required CI on campaign PRs; exact-SHA aggregate | R02 |
| N01 | Complete #860 native receipt proofs and #844 prerequisites | C01 |
| R03–R05 | Complete E4/E7, I, B lint cohorts without blanket suppressions | R02, serialized ownership |
| D01 | Parse-only diagnostic ownership, reused by JSON models | R01 |
| R10 | Validated recursive JSON and model/source ownership boundary | D01 |
| R11–R26 | Project, paths, fonts, scripts, sounds, sprites, shaders, tilesets, objects, rooms/layers, sequences, timelines, curves, extensions, particles; retire the enumerated legacy aliases | R10; one family per task |
| I01–I10 | Models/planning, POSIX, Windows, snapshots, journal, stage/publication, recovery/cleanup, facade/test split | N01; models first, coordinator last |
| G01–G05 | Typed statement context/dispatch, value handlers, flow handlers, remaining handlers and stale adapters | R01; context before handlers |
| E01 | Explicit event mapping imports; remove eager registry cycle | R01 |
| L01–L03 | Remove obsolete nontransactional CLI adapter; typed request/session; thin rendering/exit coordination | R01; lifecycle serialized |
| T01–T03 | Exact Godot helper; domain fixture/process adoption; installed test imports | R01, packaging for final import cleanup |
| P01–P02 | Build metadata, package data and installed CLI/GUI entry points | R01, T01 |
| C02 | Consolidated setup, release gate and live branch requirement | C01, P02, native/test tasks |
| W01 | Full README rewrite and verified user quick start | final interfaces and P02 |
| W02 | Full CONTRIBUTING rewrite and verified contributor route | final interfaces and R02/C02 |
| V01 | Integrated parity, runtime, native CI and independent campaign review | all architecture/docs tasks |
| V02 | Version, changelog, artifacts, approved main merge and v0.8.0 verification | V01 |

R03 begins from the approved combined R10/N01 source under its accepted exact
contract; integration waits for verified dependencies. R04 remains a separate
import-only pass after R03. R05 follows R04 and R26 so typed resource, native,
event and CLI owners are stable before their remaining Bugbear findings are
fixed. The existing immutable-parent debt gate continues to measure I001 and B
throughout; this schedule permits no new debt, suppression or exclusion. W02
waits for R05 so contributor commands describe final lint enforcement. All 54
tasks remain required by V01/V02.

## Measurable acceptance targets

- Zero governed private GML imports and suppressions; the 44-export contract stays
  identical. Remove obsolete adapters once their final callers migrate.
- New/reworked functions have complexity <=15; ordinary modules <=800 physical
  lines, ordinary functions <=150 lines, tests <=1,500/200. Any cohesive exception
  needs explicit upper review and cannot increase accepted legacy debt. No
  threshold inflation, expanded exclusions or suppression growth.
- `transpile_statement` and `_run_convert` end as coordinators <=150 lines and
  complexity <=15. Statement handlers obey the same function limits. Included
  Files' facade <=300 lines; no extracted executable module exceeds 1,500 lines
  without a specific reviewed justification, and original major transaction
  functions must be decomposed rather than moved intact.
- Each listed resource family has one authoritative typed parser, production
  consumers and malformed/missing/null/unknown-field tests. Agreed duplicate
  production paths disappear; models depend on no renderer/writer.
- Compare identical-input base/candidate elapsed time and peak memory for shared parsing, discovery and orchestration; investigate material regressions before acceptance.
- Record original and destination module/function sizes, complexity, cycles,
  API growth, removed duplication and helper/test growth per decomposition.
- Maintainability checks compare a Git-resolved immutable parent. Reductions
  remove stale allowances; reviewed old-to-new mappings may preserve, never
  increase, a moved allowance. Cosmetic packing cannot count as decomposition.
- Clean wheel and sdist installation works outside the checkout; CLI version,
  help and conversion and applicable GUI startup/package-data checks pass.
- One aggregate CI gate represents every required check, fails on cancellation,
  rejects missing workflows and verifies exact source identity. Live branch and
  release enforcement are independently verified.
- README and CONTRIBUTING meet the requested complete structures with independently
  followed commands. Historical prose remains in changelog/detailed docs, with
  useful information retained and working links.
- Release tag, source commit, nonempty assets, checksums, packaged version and
  notes are verified. No incomplete v0.8.0 is published.

## Integration and evidence rules

Use `dev/080-architecture-campaign` as the integration branch, based on main
38b3648. Each implementer receives a separate worktree and allowed files.
Reviewers stay read-only. The upper agent owns the ledger, shared contracts,
version/release metadata, actual code review, integration and release.

Do not change `src/version.py` on main until the final approved release. Campaign
PRs target the integration branch; C01 makes their validations run. Preserve the
existing publication-only-main restriction. Each integration uses reviewed
commits; main receives the final reviewed campaign through a PR. Do not use
force-push, reset, stash or destructive cleanup to simplify history.

For Python/generated-code changes run `./venv/bin/pyright --warnings` (0/0),
`./venv/bin/ruff check .`, focused tests after fixes, the accepted maintainability
gate and `git diff --check`. Shared changes also require full unittest. Relevant
exact-Godot, LTS, native transaction and same-input base/candidate parity must
actually run. Never infer runtime correctness from conversion or boot alone.

The evidence store is the sibling `.gm2godot-v080-evidence` directory; the previous
`.gm2godot-campaign-evidence` is preserved. Receipts record exact commits, command,
environment, result and skips. The tracked ledger is the recovery entry point;
external receipts are evidence, never authority to waive review. Remove only
worktrees/builds whose completion and safe disposition are proved.
