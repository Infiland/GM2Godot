# R04 accepted import layout contract

Root accepted this bounded contract on 2026-09-05 after independent and root
review of the actual policy prototype, source transformations and refreshed metrics.
Task R04 / issue #795. Implementation owner: audit_policy_tests_docs in
`GM2Godot-080-import-layout`, branch `dev/080-import-layout`. Independent reviewer:
`audit_gml_resources`, then root actual-code and integration review.

- Frozen source parent P: `1240a7b16d893bc06ba3d258683c731c60dbadca`.
- Raw Git-show baseline SHA-256: `cea9e1b5ec2a55a05c0f720ce43de7c4e11219e2108aabb9d47b888c38e85d7e`.
- Approved R03 PR source: `f1781fc5ce8cb52be3658219aec082eb49f0512e`;
  PR #880 CI `33936762868` passed all required checks. P has its exact tree.
- R03 merge CI `33937769395` is running. Isolated R04 implementation is authorized;
  opening its PR or integrating it requires successful R03 merge verification.
- Use `--base-ref 1240a7b16d893bc06ba3d258683c731c60dbadca` for the full local R04 delta.
  The root contract commit does not change the trusted legacy parent to HEAD.
- Root serializes the campaign tip at P through R04 integration. A source correction
  or movement to Q requires explicit source/parent/hash review before dependent
  dispatch; identical baseline bytes alone are insufficient.
- The exact 252 implementation paths are in this task's `contracts.json` row.
  Root owns this contract, ledger and contract registry.
- R04 is not verified until the separate post-integration bridge removal passes its
  exact local, PR and push comparisons. All 54 campaign tasks remain required.

Evidence is retained under `/Users/infi/Documents/Github/.gm2godot-v080-evidence`.
The frozen reviewed inventory is `R04/refresh-final-review-files.json`, SHA-256
`484bdded18e12d994c4b4a2805a47551c19b294f4f794e3c6c0e48b1560549f5`.
Root rechecked all 372 Python source hashes against P; its 41 existing Markdown lint
inputs are unchanged in scope. This new contract is an additional Markdown input.

R05 remains after R04/R26 and W02 waits for R05. R04's accepted scope is imports
and their exact enforcement policy; no architecture decomposition credit is given
to formatting or import-statement folding.

## Exact inputs and allowed files

The frozen R03 worktree contains 372 Python and 41 Markdown lint inputs. All Markdown inputs have zero I findings under the selected settings. Its schema-2 baseline has 213 I001 owner entries representing 213 findings.

`R04/r03-frozen-refresh/layout-inventory.json` records every source hash, before/after physical and structural metrics, both enforcement results, AST comparisons and identical static/eager graphs. Its 244 `affected_files` are the proposed import-only cohort. `R04/r03-frozen-refresh/allowed-files-and-decisions.json` enumerates the full proposed owner allowlist: those 244 files plus the explicit infrastructure below, 252 unique files total. It is a finite list, not permission to edit every Python file. Inventory differences at the actual R03 parent require root review before implementation.

Infrastructure files:

- `pyproject.toml`
- `scripts/maintainability_metrics.py`
- `scripts/check_maintainability.py`
- `tests/test_maintainability_metrics.py`
- `tests/test_maintainability_policy.py`
- `.github/workflows/code-health.yml`
- `tests/test_documentation_health.py`
- `CONTRIBUTING.md`
- `docs/wiki/Contributing-and-Testing.md`
- `maintainability-baseline.json`
- `todo-list/07-testing-codebase-improvements.md`

Root owns the formal campaign contract, `contracts.json` and `LEDGER.md` updates. No new production helper, test framework, test module, waiver, ignore, exclusion, dependency pin, release version or unrelated function change is proposed.

## One explicit import layout in every enforcement surface

Use `line-length=120`, `lint.isort.combine-as-imports=true`, and `lint.isort.split-on-trailing-comma=false` consistently in:

1. Normal project Ruff configuration.
2. Code Health's isolated command over every tracked lint input.
3. `maintainability_metrics.run_ruff`, which remains isolated, pinned and independent of local exclusions/ignores.

Enable `I` globally in both normal and tracked-input lint. Keep R03's E4/E7 enforcement, E9/F, the existing coarse project C90 ceiling and the ratchet's independent C15 threshold. Retain target Python 3.12, all exact suppression accounting, paths/classifications, Git parent resolution and structural/physical metrics. Do not run Ruff's general formatter or other fix families.

The old isolated ratchet silently used Ruff's default 88 columns while the project used 120. This produced 37 differing previews, enumerated in `initial_88_120_conflict_paths`. Default combine-as-imports=false also split explicit re-export groups into extra AST statements and created avoidable structural debt. The proposed fixed layout addresses both concrete causes. The trailing-comma setting permits ordinary imports that fit the existing 120-column limit to occupy one line.

On identical frozen R03 source, changing only these settings leaves all 408 non-I findings exactly unchanged, including locations/messages; old I findings are 213, and the proposed layout identifies 247 before source sorting (`R04/r03-frozen-refresh/policy-layout-effect.json`). These are measurement vocabulary differences, not repairs or decomposition.

### Explicit baseline-policy transition, no schema change

Record the three import-layout values in `policy(root)` as an `import_layout` mapping. Keep `SCHEMA_VERSION=2`, all old policy fields, all thresholds, classifications, pins and exclusions unchanged. The candidate baseline must match this complete new policy exactly.

The current `parent_debt` strictly loads a parent baseline using the current policy. Merely adding the mapping and regenerating the candidate would therefore reject the legitimate old parent. The implementation must include one bounded, reviewed transition: root freezes the exact R04 entry-parent commit and raw baseline SHA-256. Only that Git-resolved legacy parent may omit `import_layout`, and only when every other policy field exactly matches. Load its exact existing debt and size evidence under the known legacy policy; do not remeasure the parent under the new layout. No arbitrary old-parent fallback, threshold exception, edited external baseline, generic policy mismatch acceptance or source-driven allowance may be introduced. If actual CI comparison needs a different legacy parent, stop for root review of that exact input.

Actual source must be globally clean under the selected layout before old I debt is removed. Config-driven remeasurement alone is not retirement. Existing physical allowances continue through `retain_size_allowances`; record honest physical/structural/AST evidence. Import wrapping/folding is formatting, and merging duplicate import statements is import cleanup. Neither is credited as architecture decomposition. The bridge is temporary and owned by R04: remove it in a separate post-integration change once all live comparison bases have the new policy, and before V01/release. The addendum specifies the exact deletion and validation condition; legacy baseline-bearing P comparisons fail after removal. The existing missing-baseline `BOOTSTRAP_REF=38b3648` route remains unchanged, with final main comparison proof owned by C02/V01.

## Four original conflicts and exact alternatives

Readable before/after excerpts for all four owners are in `R04/budget-conflicts.md`, with current complete candidate files in `R04/r03-frozen-refresh/sorted/`. The original four conflicts and their final solutions are unchanged by this refresh.

| Owner | Before physical / structural | Initial 120/combine preview | Final proposal |
|---|---:|---:|---:|
| `gml_transpiler_parts/statement_parser.py` | 1190 / 2362 | 1191 / 2362 | 1180 / 2362 |
| `sprites.py` | 1688 / 3056 | 1692 / 3056 | 1688 / 3056 |
| `test_anchored_receipt_windows_integration.py` | 1684 / 3927 | 1685 / 3925 | 1681 / 3925 |
| `test_architecture_policy.py` | 1650 / 2893 | 1652 / 2892 | 1650 / 2893 |

The trailing-comma setting resolves statement_parser and the modeled Windows test through ordinary single-line imports. No executable statements are packed or removed.

For `tests/test_architecture_policy.py`, use the two explicit module spellings below, preserving both aliases and every caller:

```python
import src.conversion.anchored_artifacts as anchored_artifacts_module
import src.conversion.architecture_policy as architecture_policy_module
```

For `src/conversion/sprites.py`, change its seven existing intra-package import statements to relative package spellings: `src.localization` becomes `..localization`, and six `src.conversion.*` owners become `.*`. Preserve all 15 imported objects, aliases and the seven-owner order. This lets the existing generated-path import fit within 120 columns and keeps one ordinary intra-package group. Changing only generated_paths would still add one grouping line and does not meet the allowance. No callable, consumer, export or data model changes are part of this alternative.

## Import semantics and ownership evidence

The full preview preserves every non-import AST and import-block boundary, modulo the two explicitly listed spelling changes. Imports are not moved across assignments, calls, guards or function boundaries. The frozen R03 implementation supplies the obsolete test-bootstrap removals; R04 does not independently alter them.

A separate GML reviewer inspected the 19 production GML preview files: import bindings, explicit `as same` exports and all 44 facade `__all__` entries are preserved; no ordering-sensitive initialization was found. Their ASTs remain identical under the final layout. See `R04-gml-preview-independent.json`.

Other bounded source review covered native tooling, GUI and the application entrypoint. Native injected sibling loading stays after its existing state/definition barriers; function-local native imports stay local. GUI startup still imports only after the CLI/smoke dispatch decisions, and Qt construction remains later. The packaging Qt hook's top-level dependency call remains after its import block. These source checks do not substitute for native execution.

The two architecture-test module spellings bind the same module objects and load the same 74 modules in the same order in fresh processes. For sprites, fresh canonical-package loading resolves all 15 imported objects identically and preserves the ordered `src.*` module load sequence. All four actual consumers bind the same `SpriteConverter`: `src.conversion.converter`, `tests.test_sprites`, `tests.test_authored_particles_godot`, and `tests.test_precise_collision_masks_godot`.

Module execution was also checked using public `runpy.run_module(..., run_name='__main__', alter_sys=True)` with a public source-selection finder: both immutable sources retain `__package__='src.conversion'`, execute successfully and resolve the same 15 objects. This mirrors package-module execution without editing repository files. The repository's dynamic file loaders target exact anchored-output/receipt siblings or macOS bundle metadata; none loads sprites under an arbitrary name. No supported direct-file sprites entrypoint was found. See the refreshed `R04/r03-frozen-refresh/import-spelling-proof.json` and `module-execution-proof.json`; these are macOS import checks, not native transaction or full-suite receipts.

## Measurable acceptance and headroom

Across the 244 affected files, frozen R03 source measures 198014 physical lines / 360240 structural units. The final import preview measures 197396 / 360207: 618 fewer physical lines and 33 fewer import statement units. These reductions are formatting/import cleanup only. The selected layout has 247 I findings before sorting and zero after, in both isolated and project configurations. Both previews agree; non-import AST mismatches and dependency-graph changes are zero.

`R04/r03-frozen-refresh/composed-maintainability-proof.json` runs the actual proposed metrics/checker over all 372 sorted sources plus the four composed policy/test owners. Real R02 retention against the frozen R03 baseline reports `new_debt=[]`, no remaining I debt, and 1269 to 1056 debt entries. Both global source lint paths pass. No repository baseline was written; this is a frozen-source preview, not an integrated Git-parent receipt. Repeat the strict gate against actual P before implementation approval.

Infrastructure headroom before semantic policy/test additions:

| Owner | Physical / structural after import preview | Structural limit |
|---|---:|---:|
| `check_maintainability.py` | 264 / 759 | 800 |
| `maintainability_metrics.py` | 255 / 743 | 800 |
| `test_maintainability_metrics.py` | 381 / 1350 | 1500 |
| `test_maintainability_policy.py` | 319 / 1326 | 1500 |
| `test_documentation_health.py` | 456 / 825 | 1500 |
| `test_native_receipts_windows.py` | 400 / 1484 | 1500 |

Policy and regression additions must fit these unchanged budgets; no automatic helper extraction or new file is authorized if they do not. New/changed functions must retain existing stricter limits, with no complexity/parameter/nesting/suppression growth. Exact native test IDs and positive assertions remain unchanged.

## Required proof before implementation acceptance

- Characterize real Ruff behavior before editing the policy: an import that fits120 but not88, combined explicit aliases, and a trailing-comma group that fits120. Each regression must fail with the old inconsistent measurement path. Recheck the exact 37 divergent source previews using both final commands and save equality receipts. Do not replace source checks with assertions of configuration strings alone.
- Test the complete recorded layout in candidate policy and all enforcement paths. Independently mutate each setting and verify rejection. Test the one frozen legacy Git parent bridge, edited legacy bytes, unrelated legacy parent, changed thresholds/classifications/pins, and edited candidate policy. Existing suppression, packed source, growth/retention, missing-parent and stale-debt regressions remain required.
- Test that a layout change without actually sorting source cannot remove I debt or pass global I enforcement. Check target py312/C15 and ignore/exclusion resistance. Baseline updates contain only exact reductions and current size evidence; no new debt key/value is accepted.
- Re-run a fresh process import/`python -m` check for sprites and its real consumers on implemented source. Verify the GML facade, CLI fast path, GUI smoke path, dependency-script isolated invocations and dynamic native helper loading using existing owners. Do not add a generic import-test framework or a long-lived list of obsolete source paths to unit tests; keep the exact 37-source parity receipt in the campaign evidence and use small representative committed regressions for each setting interaction.
- Run `./venv/bin/pyright --warnings` with zero errors/warnings, pinned Ruff normal and tracked isolated commands, the strict ratchet against the frozen Git parent, appropriate existing policy/docs/architecture/CLI/resource tests, and the broad `./venv/bin/python -m unittest` suite with exact Godot and all pinned fixtures. Freeze source hashes before full proof; no timing improvement claim is warranted.
- Run all three native hosts through the existing exact N01 inventories, both stable and native-lock profiles, plus the affected artifact and Godot/GUI workflow coverage. Preserve existing receipt output directories, runtime pins, zero-skip required gates and all positive native cases. A macOS-only modeled test run cannot certify the reordered native imports.
- One owner implements only the accepted finite list; an independent reviewer then root read the actual diff and receipts. No commit/push/integration until the existing root review protocol authorizes it.

Root accepts the fixed layout, the nine enumerated import spelling changes and the exact legacy-policy transition on the frozen P above. All 372 source hashes and the raw Git baseline match the independently reviewed projection.

The final refreshed artifact inventory is `R04/refresh-final-review-files.json`; `R04-frozen-R03-refresh-delta.md` explains the 273-to244 path correction and the composed test budget. Historical inventories remain evidence of earlier projections, not the final allowed cohort.

# Required policy transition and retirement

## Small implementation shape

`maintainability_metrics.py` adds one `IMPORT_LAYOUT` mapping containing exactly `line_length=120`, `combine_as_imports=true`, and `split_on_trailing_comma=false`. Its isolated Ruff arguments read these values explicitly. `policy(root)` records the same mapping, retaining schema2 and every existing policy field and budget.

Only `parent_debt` contains the temporary compatibility branch. It still resolves the caller's ref to a commit, checks that it is an ancestor of HEAD, verifies the baseline exists, and reads the raw baseline through `git show`. It then uses this exact shape:

```python
raw = git(root, "show", f"{revision}:{BASELINE_PATH}")
expected_policy = policy(root)
if (
    revision == LEGACY_IMPORT_LAYOUT_PARENT
    and hashlib.sha256(raw).hexdigest() == LEGACY_IMPORT_LAYOUT_BASELINE_SHA256
):
    expected_policy.pop("import_layout")
return load_baseline(raw.decode(), expected_policy)
```

The guard checks both identities. The hash covers unmodified Git-show bytes, before decoding. It only selects the known old expected policy, which differs by the one newly recorded mapping. All other refs/bytes use the strict complete current policy. Thresholds, rules, classification, version, pins, schema and every other field still compare exactly. There is no parent remeasurement, ancestor fallback, hash-only fallback or candidate baseline exception. Existing missing-parent/bootstrap logic remains unchanged. In particular, `BOOTSTRAP_REF=38b364855f06e971d2676b921fd300e1f40f076a` retains its one legitimate missing-baseline route; a final campaign-to-main PR may still use it. No new route or historical-ref rejection rule is added.

`load_baseline` itself is untouched. A legacy candidate baseline still fails. To begin the source migration, preserve the exact inherited candidate debt/evidence and add only its newly required policy mapping explicitly; then run ordinary `--update` against frozen P after sorting the actual source. That command still verifies candidate and actual debt against P before writing exact reductions. No copied/increased allowance is introduced by the metadata step.

## Freeze the real comparison identities together

Root froze P and the exact raw Git-show baseline SHA above after R03 integration. The entry receipt records these values. Mutable branch names or working-tree bytes do not authorize another parent.

| Surface | Actual ref supplied to the checker | Required entry condition |
|---|---|---|
| Initial local uncommitted R04 work | Explicit P | Use the frozen commit above, including after this root-owned contract-only commit. Do not use HEAD as the legacy comparison parent. |
| Later local R04 commits | Explicit P while reviewing the full R04 delta | P remains an ancestor; current source and candidate baseline must be globally clean. |
| R04 pull request Code Health | `git merge-base(PR_BASE_SHA, PR_HEAD_SHA)` from the event payload | Resolve and record this value as P before dispatch. |
| Campaign integration push Code Health | `github.event.before` | Serialize integration so the previous campaign tip is P, and verify it immediately before pushing. |
| Subsequent R04 cleanup PR/push | PR merge-base / previous push, both with new-policy baselines | Bridge is unnecessary; normal strict loading must pass. |

The existing workflow checks the event revision, so the ancestor condition remains meaningful. A later campaign tip Q can differ from the PR merge-base P even when its baseline bytes are identical. Do not let the single hash authorize Q. Prefer serializing R04 entry through integration so all initial legacy comparisons are P. If campaign movement makes that impossible, pause for root to review the actual P/Q event identities and revise this finite contract before dispatch; no generic acceptance rule is authorized.

The actual frozen identities above replace the external prototype placeholders. Root must verify the eventual PR merge-base and previous-push event are still P before dispatch.

## Explicit temporary ownership and deletion

R04 owns bridge removal as a required post-integration completion step, with root owning the campaign serialization and integration. It is not permanent support for historical parents and is not deferred to an unrelated task.

The owner must open the small removal change only after the R04 migration is integrated, the original PR has completed, and root verifies every live comparison base that will validate the removal is a descendant carrying the complete new-policy baseline. In particular, do not remove the branch in the original R04 PR's final commit: that PR still compares against legacy P. Check its removal PR merge-base and the integration push's previous SHA explicitly.

Delete the two frozen constants, the guarded legacy-policy selection, and the `hashlib` import if then unused. Delete temporary tests that assert legacy-parent acceptance; retain or adapt the permanent tests that reject legacy candidate policy, changed layout settings, unknown/nonancestor parents and edited policy. Restore `parent_debt` to strict full current policy loading for every baseline-bearing parent. This rejects the removed legacy R03 P, not the existing missing-baseline bootstrap38b3648 route. C02/V01 owns final main-integration comparison proof. The global source layout and candidate baseline remain unchanged.

Validate the cleanup against new-policy local/PR/push parents, rerun the existing policy tests and actual comparison workflows, and prove that legacy P is rejected after removal. Root records the deletion commit and successful exact event receipts in R04's completion evidence. Keep R04 at implementation-complete/proof-pending until this removal is verified. No bridge constant, code branch or acceptance test may remain at V01 or release.

## Measured code and tests

The prototype changes only four existing owner files. It creates no production leaf or test framework and performs no extraction. Current source and final fixed-layout test imports are composed in the preview.

| Owner | Before physical / structural | Preview physical / structural | Structural limit |
|---|---:|---:|---:|
| `scripts/check_maintainability.py` | 264 / 759 | 277 / 775 | 800 |
| `scripts/maintainability_metrics.py` | 255 / 743 | 262 / 765 | 800 |
| `tests/test_maintainability_metrics.py` | 382 / 1351 | 414 / 1460 | 1500 |
| `tests/test_maintainability_policy.py` | 320 / 1327 | 340 / 1420 | 1500 |

The committed regressions represented by this prototype cover exact legacy parent+bytes acceptance, wrong ref with identical bytes rejection, changed raw bytes rejection, normal new-policy parent acceptance, strict legacy candidate rejection, each of the three mutated recorded settings, and actual Ruff behavior for 88-versus120 width, combined aliases and trailing-comma folding. Under the old measurement function the new real-Ruff test produces three expected failures; under the preview it passes. Existing suppression, stale-debt, parent trust, line retention and packed-source cases run alongside it.

The prototype leaves headroom for the small existing documentation/workflow-contract assertions. The main contract still requires real project/isolated equality receipts for the exact37 historical divergent previews and final all-source enforcement. Config-string assertions alone do not replace those proofs.

The frozen R03 implementation changes `tests/test_maintainability_metrics.py`: its real E4/E7 regression, imports and workflow assertions are all retained in the corrected 414-line/1460-unit prototype. Its 30 joined import separators reduce the R04 cohort from 273 to 244 files; 29 files no longer need any import change. All five R03-added test bodies are exactly preserved. The refreshed prototype passes Pyright, Ruff and all 49 tests in the two policy modules, including R03's global enforcement assertions and three added workflow layout-flag checks. The old measurement still produces the three expected negative-control failures. See `R04/r03-frozen-refresh/policy-preview-checks.json` and `R03-added-tests-preserved.json`. Actual P is frozen above and all reviewed source hashes match that merge.
