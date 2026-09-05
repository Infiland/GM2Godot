# R13 authoritative font model

Root accepts this R13 / #797 implementation contract against verified R12 merge
`b9c05cd326cbcb8531ca93c24709bcf14cb81748`, tree
`0d49511e22aa48f72e80a77b6d4811df416dd31d`. R13 depends on R12 and preserves
the integrated T01 helpers. It is independent of the concurrent I02 and L02
work; root will reconcile their actual integration state before its PR.

Implementation owner: `audit_gml_resources`, in `dev/080-font-model` at
`GM2Godot-080-font-model`. A separate agent reviews the actual source read-only;
root then reads the actual changes and owns integration. No source change is
authorized outside the thirteen scoped paths below, including the retained
snapshot amendment. Version and release work remains
reserved for the single final v0.8.0 release.

## Problem and benefit

The font worker, registry planning and descriptive resource aggregate interpret
overlapping raw fields differently. Fonts also lazily import output-path code
which imports the registry, and the registry imports font lookup helpers back
from the converter. One canonical normalized model and one source-lookup leaf
remove duplicate interpretation and this cycle without moving worker failures
into planning or changing generated output.

## Model, callers and compatibility

`font_model.py` owns a frozen `FontModel` with ten required fields, in order:
`font_name`, `name`, `size`, `bold`, `italic`, `antialiasing`, `include_ttf`,
`ttf_name`, `source_path`, `raw_data`. Parsed values are snapshots and raw data
retains the exact recursively validated dictionary, its order and unknown
values. The pure parser uses the worker's existing required-key evaluation,
`str`, `float`, `bool` and `int` order and defaults. Its finite numeric narrowing
uses runtime checks, without Any, casts, ignores, clamping or fallback values.

The worker retains JSON acquisition and its existing caught
`OSError`, `JSONDecodeError`, `KeyError` and `TypeError` boundary. Native
`ValueError`, `OverflowError`, `UnicodeDecodeError` and `RecursionError` retain
their observed phases. Existing trailing-comma behavior, including the
inside-string quirk, remains unchanged. Keep safe sibling execution, outcome
settlement, diagnostics, cancellation and exact output bytes.

Registry planning uses two concrete raw-string selectors in the model owner:
`bundled_font_reference` and `system_font_reference`. It must not eagerly parse
worker numeric or required fields. Preserve bundled lookup/fallback order and
the existing cache lifetime. The worker's already normalized TTF string may be
stored once and reused at the accepted four reads without moving any I/O.

The aggregate returns the canonical model directly. Root explicitly accepts
retirement of the unused descriptive FontModel's constructor, inheritance,
metadata fields, serialization shape, reference-selected name, string-only
family and size-default/coercion policy. The full accepted field-domain
contract bounds this retirement; twenty differing and four equal historical
witnesses are examples, not its entire domain. Worker and registry behavior
receive no exception from this retirement. Preserve every other resource family
and R12's canonical path model. No adapter, alias or second font model remains.

## Source lookup and lifecycle

`font_sources.py` owns the existing extension set, bundled output filename,
system font directories, system resolver and its finite filename matcher.
Preserve unsorted directory/walk/file order, lowercasing, space removal, suffix
precedence and first-match selection. Delete the unused bundled resolver and
old private lookup definitions. Migrate callers and four lookup tests directly
to the public owner; introduce no forwarding exports.

Dependency direction is fonts to output paths to registry to model/source
leaves, with direct fonts-to-leaf imports. The model depends only on validated
JSON types and dataclasses; the source leaf depends on generated-path helpers
and the standard library. Neither leaf imports a converter or output registry.

Fonts retain source validation and immediate pre-copy revalidation, staging,
copy/replace/cleanup, output collision authority, progress and future settlement.
No new filesystem guarantee, escaping fix, font-size behavior or cache belongs
to R13. GameMaker LTS 2026 and exact Godot
`4.7.2.stable.official.ed1daf0bf` remain required.

## Allowed implementation files

- `src/conversion/font_model.py`
- `src/conversion/font_sources.py`
- `src/conversion/fonts.py`
- `src/conversion/asset_registry.py`
- `src/conversion/resource_models.py`
- `tests/test_fonts.py`
- `tests/test_font_model.py`
- `tests/test_font_sources.py`
- `tests/test_font_model_consumers.py`
- `tests/test_font_runtime_godot.py`
- `tests/test_resource_matrix_godot.py`
- `src/conversion/conversion_architecture.md`
- `tests/test_path_model_consumers.py` (only the snapshot literal below)

Root alone owns baseline, coverage, required-test manifest, workflow, contract
and ledger changes. Add the four font/model/source/consumer modules to the
existing native commands while preserving all current modules, jobs, pins and
gates. Map new files to their real existing coverage cohorts without lowering
floors. No version, fixture payload, dependency or unrelated formatting changes.

## Before evidence and measured targets

Actual b9 characterization reproduced all 95 historical observations and the
24 aggregate subset. The expanded matrix completed 184 single-field, six
first-error, fifteen root/read, 138 bundled-selector and 23 family-selector
cases: 366 cases and 776 public observations. Raw bytes, error timing, lookup
calls, source hashes and runtime bindings are retained. Root and independent
review approved the results.

Before-test proof is twelve actual successes from the original thirteen-test
run plus one separate corrected recursion-test success. The original failure
is preserved. Only that fixture changed to the existing 10,000-array/null
decoder case; no thirteen-test rerun or altered runtime limits is claimed.
The nineteen new test bodies and their budgets have already been reviewed.

| Owner | Before physical / structural | Accepted projection |
| --- | ---: | ---: |
| fonts.py | 806 / 1361 | 692 / 1077 |
| asset_registry.py | 4110 / 6854 | 4109 / 6845 |
| resource_models.py | 578 / 984 | 569 / 976 |
| font_model.py | absent | 57 / 98 |
| font_sources.py | absent | 74 / 187 |
| tests/test_fonts.py | 1448 / 2889 | 1408 / 2800 |

The existing worker remains 150 physical / 226 structural lines; R13 does not
claim its complete decomposition. New production functions stay at C15,
nesting four, at most eight parameters and 150 physical/structural lines.
New test functions stay within the unchanged 200-line limits. No debt may grow,
move under a larger allowance or disappear through packing or suppression.
Report actual destination sizes, complexity, imports and deleted duplicates.

## Completion proof

Run Pyright with zero errors/warnings, both required Ruff checks and the strict
actual-parent maintainability gate. Run the 65 required IDs after fixes,
including all nineteen new tests, four moved IDs and exact-Godot runtime cases.
Retain old assertion bodies apart from the accepted lookup migrations. The
runtime test must use T01's exact-Godot helper and public `draw_set_font`,
`draw_get_font` and string-width behavior on an actually converted Font.

Preserve the approved nineteen meaningful controls. Run one immutable full
suite with all five pinned projects, the R01 fourteen-field parity and same-ref
control, and the font field/output matrix with only the accepted aggregate
retirement differences. Preserve the 44 public GML exports and all native
requirements. No platform skip becomes native success.

Measure the two accepted bounded decode/normalize and planning/conversion
workloads with identical inputs, interleaved fresh processes, excluded warmups,
all samples, dispersion and native peak-RSS units. In particular, measure the
cost of retaining raw glyph/unknown data honestly. Do not claim speedup or
performance acceptance from a successful invocation alone.

Freeze source for independent review and root actual-code review. Commit,
push, PR and merge require root coordination. R13 is verified only after its
scoped migrations, deletions, local proof and exact PR/merge CI all pass.
All other resource families and #797 completion remain separate roadmap work.

Detailed immutable evidence is under
`/Users/infi/Documents/Github/.gm2godot-v080-evidence/R13`, including the accepted
refinement, test-body proposal, recursion correction and b9 matrix results.

## Frozen source review and root proof metadata

Independent and root actual-code reviews approve the twelve source owners frozen
in `R13/implementation/review-files.json`. The actual font converter is693/1078;
the aggregate is563/968. Two reviewed projection corrections add the required
`FONT_EXTENSIONS` import and remove the now-unreferenced `_float_value` helper.
The initial diagnostics remain recorded; final Pyright reports0 errors/warnings,
both Ruff paths pass and all65 required tests pass with zero skips. No source
change occurred during that run. The strict unchanged baseline generator/checker
against actual b9 lowers1045 entries to1042: three removed, seven reduced, no new
or grown debt or changed policy. The targeted font cycle is removed (14to13
static cycles, one unchanged eager cycle); existing unrelated debt remains.

Root adds exactly the four accepted modules `tests.test_fonts`,
`tests.test_font_model`, `tests.test_font_sources`, and
`tests.test_font_model_consumers` to each existing macOS/Windows command. Every
old module and T01 helper remains. The converted-font runtime case runs in the
local65-ID and existing Linux exact-Godot selection; these four additions do not
claim native macOS/Windows Godot execution. The four source/consumer modules
must execute on their actual native hosts with precise skip attribution.

The canonical font model joins the existing project-parsing coverage cohort
because the aggregate now consumes it. Every existing pattern, coverage floor,
baseline and source scope stays unchanged. The font source leaf remains covered
by overall-production. The new R13 verification gate selects the exact accepted65
IDs with no allowed skips and retains R12's runtime, immutable fixtures, dependency
locks and full fourteen-field parity contract; all prior gate objects are exact.
Its five parity inputs are two repository fixtures and three external projects;
the separately required full suite runs all five pinned external projects.

At that initial source snapshot, full, controls, font matrix, parity/same-ref,
performance and integration proof were still outstanding. The accepted results
below retain their actual source identities. The later combined source preserves
verified I02/L02 work; final PR/merge native proof remains outstanding.

## Retained whole-aggregate snapshot amendment

The immutable `465b562380313fad75245b2f97c5ecdd4824228c` full run executed
3161 tests: 3104 successes, one stale snapshot failure and 56 exact prior host
skips. All five pinned external fixture tests passed; all595 tracked files and
fixture bindings stayed unchanged. Preserve that failed result and its package.

Root authorizes the thirteenth owner path only for the expected digest in
`TestPathModelConsumers.test_resource_matrix_and_empty_project_preserve_other_families`.
The retained R12 snapshot includes fonts. Derivation from its complete stored
before records and the accepted ten-field font shape changes only that font
record; all twelve other record groups remain exact. The complete expected hash
changes from `651ad1121c018bae0ede16519da370d0c5e567e1f37127702aa25cefbd813622`
to `e2ab818a5d5a81569b433364a932c452aa6250ccdf06ab46319d825ae323404e`.
Keep all seven assertions, all record families, fixture bytes, path normalization
and the original twelve source owners unchanged. The equal-length literal does
not change the module/method AST structure or maintainability allowance.

The frozen proposal index is `fe3798891d6950e74c8a5e09dc9e5a5adf106df71dcbc24a92b26b950cf1bee3`.
After correction, run Pyright with zero errors/warnings, both Ruff checks and an
explicit66-ID selection: existing65 plus the corrected retained method, no skips.
Freeze a new source commit and reviewed full-v2 package before the required full
suite with all five external fixtures. Rebind unexecuted parity, matrix, controls
and timing packages in fresh locations; preserve all original evidence and every
accepted payload, assertion, native gate, coverage floor and benchmark workload.
The failed full result does not establish proof for the corrected tree.

## Accepted local and combined results

Independent and root reviews approve immutable corrected source
`321a629abb5090fc3409a75d2b0dd83e06299505`. The 66 focused tests passed with zero
skips after Pyright and Ruff fixes. The accepted full retry ran 3161 tests with
3105 successes and 56 exact existing host skips; all five pinned external project
tests passed. Both earlier failed full runs remain preserved: the stale aggregate
snapshot and an unchanged reader-deadline test. Isolated diagnostics do not
establish the cause of the latter failure.

The five-fixture fourteen-field base/candidate and same-ref comparisons are
equal under the existing normalization. Raw transaction identities remain in
the evidence. Both resource-matrix runtime markers report the same two
compatibility warnings; parity does not claim warning-free runtime validation.
The 366-case matrix produces 776 observations per run: 585 unchanged and 191
explicitly accepted aggregate retirements. Nineteen intact controls pass; nineteen
fresh one-ID mutants trigger 37 intended callbacks, with every source restoration
verified. A failed root read-only raw-identity assertion and its continuation
sequencing deviation remain documented; no comparator policy was weakened.

The timing comparison uses two excluded warmups and five alternating fresh
process pairs with identical inputs. Three passes over 64 glyph-rich documents
retain 192 models and 393,216 glyph dictionaries. Decode/normalize median rises
from 0.264205708s to 0.653276s: 147.26%, or about 2.026ms per retained parse. Whole
benchmark-process median peak RSS rises from 50,085,888 to 190,054,400 bytes
(about 133.48MiB additional). These material costs are accepted because the
contract requires complete recursive JSON validation and raw dictionary identity.
The new model retains the validated dictionary without copying or caching it.
Successful production workers return a name rather than collecting models;
exception tracebacks can retain locals until future settlement. This source
explanation is not a quantitative allocation profile or production peak estimate.

The separate 90-font planning/conversion workload preserves every output and
log. Its median changes from 0.172695791s to 0.167902s, with overlapping sample
ranges, so no speedup is claimed. Timing acceptance is recorded in
`R13/timing-result-review/performance-verdict.json`; complete root local approval
is `R13/R13-root-final-local-proof-review.json` under the external evidence root.

Prepared merge `1a8bd8200d6fdb72a4b1a3d1908239aeddc93049` combines that source
with verified campaign parent `5faa683a07a913c96d5283d06b8e2cb1b44e5b30`. All 13
R13 owners and 13 incoming Python paths preserve their reviewed bytes; there
are no overlapping Python edits. The 605-file/405-Python source passed Pyright
with zero errors/warnings, both Ruff checks, actionlint and the strict unchanged
maintainability policy. Its actual-parent allowance falls 1044 to 1041, with three
entries removed, seven reduced and no additions or growth. All prior gates,
coverage floors, I02 native commands and L02 CLI modules remain preserved.

The combined focused runs contain 242 tests: 65 R13 successes, one retained
snapshot success, 83 CI successes and 93 CLI tests with 92 successes plus the exact
existing Windows-only directory-relocation skip. All 605 source hashes remain
unchanged through those checks. Independent combined review is
`R13/current-parent-5faa/independent-combined-source-review/review.json`.
Final status documentation is a separate narrow delta; original full, parity,
matrix, controls and timing results remain bound to 321. R13 is locally approved
and becomes verified only after exact final-source PR and campaign-merge native
CI evidence is accepted. Campaign progress remains 16 of 54 tasks (29.6%).
