# G01 accepted implementation contract

Status: ACCEPTED and assigned by root after independent and root contract review. Fixed implementation parent C is `ec257912ec907161b2e89d552a76dc591ed33b68`. The final source/import/metric refresh is verified in `/Users/infi/Documents/Github/.gm2godot-v080-evidence/G01/final-C-entry-source-confirmation.json`. This entry supersedes historical proposal status/source and completed-R04 implementation-start wording below; all substantive API, behavior, scope, size and proof requirements remain binding.

Sole implementer: `audit_policy_tests_docs` in `/Users/infi/Documents/Github/GM2Godot-080-statement-context`. Independent actual-code reviewer: `audit_transactions_cli`, then root. The conditional start follows [R04's reviewed entry contract](R04-parallel-entry-contract.md). Cleanup PR #883 and CI `33943223988` are pending; no child PR or campaign integration is authorized before successful exact cleanup PR and merge proof. If cleanup changes or fails, root reassesses affected work and invalidates stale evidence.

Root has accepted the original finite contract SHA256 `db995a2a85d82a3fc04c058e2cf94e17bb6be513359704152d773d7da232a9fc` and confirmed all 16 source inputs at C. Applicable current measurements/import projections are recorded in the external final source receipt; historical measurement tables below remain provenance where earlier source counts differ. Strict comparison uses immutable C; policy thresholds, retained evidence, scopes and suppressions may not grow.

The complete allowed-file inventory below includes `maintainability-baseline.json` for integration only. **Root is its sole writer during parallel work.** The implementation owner edits only the other allowed paths, reports measured reductions, and asks root to run any baseline update sequentially before the final strict gate. Root also owns campaign documents, coverage-policy and architecture-verification integration. Do not edit, commit or push those shared files. Do not commit or push implementation source before root code approval and explicit instruction.

Freeze source before proof. Coordinate a reserved CPU window with root before full-suite or performance/parity runs; focused checks and before-production characterization may proceed. Use the approved native Python 3.12.10 environment and exact Godot `4.7.2.stable.official.ed1daf0bf`, all five pinned project environments where required, and preserve every native/skip distinction in the finite specification.

## Problem, benefit and ownership

`statements.transpile_statement` has **15 parameters including statement**, not the roadmap's provisional 16. Four parser calls repeat 13 or 14 state arguments; the lowerer has one recursive call. The current owners are `_StatementParser` for live parser state and `statements` for statement lowering. Introduce one frozen `StatementLoweringContext` in the existing model owner; retain state and lifecycle ownership in those same two implementations. This reduces the lowerer to two parameters and centralizes fresh parser-state construction before the later handler slices. It does not claim to decompose the remaining C120/1151-line lowerer.

## Inputs, outputs and finite internal contract

New internal signature: `transpile_statement(statement: str, context: StatementLoweringContext | None = None) -> list[str]`. All existing internal callers migrate; there is no compatibility adapter for the old 15-parameter signature, which has no external production consumer in the complete source/test inventory. `GMLStatementRequest`, `GMLStatementResult`, the three statement phase operations, and all 44 public facade exports retain exact identity, order, signatures and container contracts.

The frozen dataclass contains exactly the old 14 state fields, in old argument order, with their original types and defaults. The complete field/type/default table is in `G01-source-caller-proof.json`: local_names, declared_local_names, instance_variables; loop_depth, continue_depth, return_depth, finally_depth; enum_values, enum_names, scope_context, inherited_event_call, macro_values, generated_counter, control_flow_capture. Mapping/MutableMapping, Iterable and MutableSet annotations are not tightened. No copies, validators, caches, counter object, new result type or framework. The model's explicit internal `__all__` grows from three to four names; the facade and statement API exports do not grow. The exact always-truthy class and None are the supported new internal input; arbitrary duck-typed contexts/subclasses with custom truthiness are not an additional compatibility surface.

The first operation remains `if not statement: return []`. Only afterward use the accepted readable `context = context or StatementLoweringContext()`. Preserve old field normalization in exactly this order: local_names None becomes a fresh set; declared_local_names None becomes a separate fresh set; normalize scope; macro_values uses its existing `or {}` rule; generated_counter uses the existing explicit None rule. Empty supplied sets/counter retain identity. A falsey mapping is replaced and a truthy mapping retained as before. Scope None uses the existing default; supplied scope identity survives. Instance variables and enums retain the old None behavior. Iterable enum names are neither materialized nor normalized earlier. An empty supplied counter retains its existing deferred generated-name failure. Do not propagate defaults into the original context or mutate its fields.

The dataclass freezes field rebinding only. Containers remain the exact live aliases; local/declared/instance sets and generated counter mutations remain visible in the old order, and macro/enum mappings retain their current identity. No output, exception text/type, source location, token handling, resource lookup, mutation lowering or generated-name policy changes. `inherited_event_call` is read directly at its sole remaining use after recursive context retention, avoiding a redundant local alias.

## Callers and evaluation/capture order

`G01-source-caller-proof.json` inventories all five actual calls, their exact owner/line, expression and argument read order. No additional production caller exists.

- `_parse_statement`: construct fresh context after `tokens_to_source`; pass capture.
- `_parse_for_statement` initializer: only when nonempty; fresh context; capture remains omitted/None.
- `_parse_for_statement` operation: only when nonempty, after condition lowering and before loop/continue depth increments; fresh context; capture remains omitted/None.
- `_parse_do_until_body` unbraced path: after the unchanged empty-token guard and token conversion; fresh context; capture remains omitted/None.
- Lowerer simple RHS prefix/postfix increment recursion: statement expression evaluated first, then derive the context described below; capture remains omitted/None.

Add one parser method `_lowering_context(self, *, include_control_flow_capture: bool = False)`. It constructs a new context from current attributes in the old argument order. The ordinary call passes True, the other three use False/default. Read `self.control_flow_capture` last and only when requested; do not evaluate it as a helper argument ahead of the other attributes. No cached context and no automatic capture propagation to previously omitted sites. Existing constructor copies, nested parser sharing/merging, scope enrichment, depth transitions, condition timing and generated-counter increments stay outside this slice.

Use `dataclasses.replace` only at the one recursive call. Explicitly override local_names, declared_local_names, scope_context, macro_values and generated_counter with the five normalized aliases; explicitly override control_flow_capture=None. Retain instance_variables, all four depth fields, enum_values, enum_names and inherited_event_call. The receipt checks all eight retained names are never rebound in the original lowerer and that each old recursive argument was exactly that name; its 14-row table records every old/new value. Postfix temporary allocation and local-set insertion still precede recursion; emitted prelude, increment and final assignment keep their ordering. No generic replacement wrapper or extra model field.

## Dependency direction and allowed files

Parser -> statements and statement_models; statements -> statement_models/shared models and ordinary stdlib dataclasses.replace; statement_models -> shared_models plus stdlib typing/dataclasses. The model layer does not import parser, expressions, rendering or source-map owners. No reverse edge, registration or new module indirection.

Exactly eight proposed implementation paths:

1. `src/conversion/gml_transpiler_parts/statement_models.py`
2. `src/conversion/gml_transpiler_parts/statements.py`
3. `src/conversion/gml_transpiler_parts/statement_parser.py`
4. `tests/test_gml_statement_context.py` (new cohesive context/behavior characterization owner)
5. `tests/test_gml_statement_api.py` (only internal model export expectation)
6. `tests/test_gml_transpiler_models.py` (only internal model export expectation)
7. `src/conversion/conversion_architecture.md`
8. `maintainability-baseline.json` (exact reductions/evidence only)

Root owns any shared architecture-verification method inventory, campaign records and coverage mapping after review; no implementer edits there are implied. There is no other production caller to authorize. Family handlers, parser dispatch, public facade, token/source-map implementation and legacy capture behavior are explicit non-goals.

## Before metrics and measurable improvement

`G01-final-layout-context-preflight.json` and reproducible external `preflight_context.py` project source in memory only, then apply the complete final R04 import settings and the final structural vocabulary. This is a source-shape feasibility proof, not tested implementation.

| Owner | Before physical / structural | Proposed physical / structural |
|---|---:|---:|
| statement_models module | 57 / 102 | 76 / 143 |
| statements module | 2771 / 4644 | 2762 / 4644 |
| transpile_statement function | 1161 / 1944 | 1151 / 1943 |
| statement_parser module | 1180 / 2362 | 1149 / 2296 |
| new parser context factory | absent | 17 / 31 |

Lowerer parameters 15 -> 2; complexity 122 -> 120 due only to equivalent default normalization; nesting stays 4. Existing other statements C20/C16 helpers are unchanged. No new size-debt key/value and no new E4/E7/E9/F findings. This does not present the small C decrement or import formatting as handler decomposition. New context factory stays C<=15, nesting<=4, parameters<=8, and both physical/structural function measures<=150. New test owner stays <=1500 physical/structural units, each method<=200 and C<=15, with no extra helper module or suppression. Existing oversized owner/function budgets may only stay level or shrink; preserve their stricter retained physical allowances. Any implementation growth beyond these budgets requires a concrete design review, never an allowance or packed-source workaround.

## Characterization and proof

Before changing production code, add the behavior assertions in the new test owner against the original signature, then migrate their call construction while retaining those assertions. The eight proposed exact IDs and each expected observation are enumerated in `G01-source-caller-proof.json`. They cover early empty return, precise None/falsey rules, mutation aliases and empty-counter timing, fresh parser reads/order, capture inclusion/omissions, field-by-field recursive state and generated/effect order, and the new frozen-but-live contract. Tests for the new context shape follow its addition. Use bounded observation of the actual calls when needed; no alternate parser or generic test runner.

The receipt also inventories 40 existing exact method IDs with AST hashes: all statement API/model/source-map contracts, 14 evaluation/scope/control-flow lowering methods and four actual exact-Godot methods (array-index postincrement, two bound-method cases, script runtime). Preserve these old method bodies except the two explicitly allowed internal-export expectations. Source-map malformed syntax and reserved-name/case diagnostics must keep their exact output. Execute focused new and existing cohorts with zero skips where required; missing exact Godot is incomplete proof, not an optional success. Full unittest runs with exact Godot 4.7.2.stable.official.ed1daf0bf and all five pinned projects; report every native/filesystem skip without relabeling it as passed. This slice changes no native filesystem implementation or required native gate.

Run approved native Python Pyright --warnings with zero diagnostics, both established Ruff paths, architecture/facade checks, the strict Git-parent debt gate and diff checks. Freeze source hashes before full evidence and independent/root actual-code review. After approved immutable commit, run the accepted R01 five-fixture/all-14-field base-to-candidate parity and same-ref reproducibility contract; preserve complete raw logs/snapshots and exact source identity. No normalization change. Integration/CI and parent verification remain separate completion states.

Shared parser allocation changes require a bounded performance comparison. `G01-benchmark-inputs.json` freezes eight valid input/output pairs already characterized on f1781fc: declarations, simple recursive increments, assignment-index evaluation, ordinary and declaration for loops, unbraced do-until, finally-return and finally-continue. Proposed timing: five isolated processes per revision, each one untimed warmup then 250 passes through all eight public transpile_gml_code calls (indent empty); imports and output hashing outside the timed region. Retain all wall/CPU/peak-RSS samples, harness/source/input hashes, variance and medians; reserve a CPU window with root before timing. Run identical inputs/repeats/environment at immutable base and candidate, with outputs verified. Report the scoped allocation tradeoff honestly; do not claim conversion-wide speed from this workload, and do not weaken semantics or add caching to repair a small measured cost. Five-fixture parity supplies broader correctness, not a performance claim.

## Completion and removal

Implementation owner is assigned by root after independent/root contract acceptance and actual post-R04 ref/hash/metric refresh. Complete only after all five callers migrate, old repeated argument lists disappear, public contracts remain intact, both owner/test budgets pass, characterization/performance/full/parity proof is tied to frozen source, independent then root actual-code review approves, and exact integration checks verify. No temporary adapter is introduced. Therefore no deferred removal or fallback path is authorized; any newly discovered behavioral discrepancy is reported for separate finite scope instead of being silently repaired here.
