# G02 control transfer and declarations contract

Task G02 / issue867 remains planned in the finite54-task campaign. Verified
progress is19/54 (35.2%). Root and independent reviewers accepted the concrete
cap-800 design and immutable C source refresh. This tracked entry assigns
`/root/r14_broad_binding` as sole implementation owner in managed
`/Users/infi/.codex/worktrees/g02-statement-control/GM2Godot`, branch
`codex/080-statement-control`; `/root/r14_native_review` is the read-only reviewer.

Source basis is C `7612e928a5faec56b91cb2c54e56744449e122b4`, tree
`1b6e65df7997979cc36f65d999b583c58c802025`, parent documented R14 D then
verified merge M `b45399259c2af24a914fdfefc161ba20c44348ba`. The source-refresh
index is `08d2699740ca8d8c367afb4ae0eaa8722af1266b95b24001ba04b6bea03a1278`;
root review is `6d6262c790ee39e89cfca156b10ce72c9f2745d56aac9785321d7da3decef4bd`,
independent review is `3ce0d0abdf4aeb3fdf48ffff17d987437bcac1ebaf845d6dda01adee7eccf951`.
All619 C sources,615 M-equal nonmetadata files, original cap-800 inputs and
historical618-file F archive are preserved in external evidence. The unused F
checkout was removed only after those current bindings were independently/root
approved; its branch, source archive, evidence and shared runtime remain.

This entry grants external literal old-package preparation only after root binds
the actual clean entry commit/worktree, exact source/callers/test ASTs/full modes,
actual native runtime and available five-project fixtures, and accepted budgets.
The managed environment receipt is preparation, not an executable-parent assignment.
Different-author and root acceptance of the literal old bodies/fixtures/guards/
launcher/oracles precedes separately authorized old execution. Successful actual
old observations require independent/root acceptance before any production edits.
No application/test import, collection, checker, engine, CI, parity or timing
workload is authorized by this document. No G02 verification credit is earned.

The exact11 code/test paths appear in contracts.json;10 are owner-editable.
Root alone updates the architecture cohort's two owner names and baseline,
architecture/campaign/coverage/verification metadata. Conditional CI changes
require separate concrete review. No other path is authorized. The accepted
source design below is retained verbatim from its ownership section; its source-
only stage descriptions remain provenance and do not override these entry gates.

## Exact ownership and finite scope

The new statement_control owner handles return, break, continue, exit, inherited-event and throw policy; capture serialization and dispatch also belong there. The new statement_declarations owner handles var validation/emission and the existing var-name token reader. Statements retains actual expression mutation and assignment machinery. The parser retains tokens, cursor, source spans, hoisting policy, globalvar/static consumption, switch/try/loop/with lifecycle and fresh G01 context construction.

globalvar and static are already parser branches. Their cursor/error/scope timing remains unchanged, as do static_declarations and static initialization owners. No other statement family moves. Assignment target266/416/C20, assignment-to-temp137/210/P9 and assignment-to-emitted151/284/C16/P9 remain protected ASTs for later tasks.

The exact eleven code/test paths are listed in contract.json. Ten are editable by a future designated implementation owner; the architecture cohort update is root integration. statement_models receives only one fixed callable type alias; all four dataclasses, all fourteen context fields and model export4 stay exact. Facade44, phase3, signatures, identities and containers stay exact. Root alone controls baseline, campaign documents, coverage/verification registration and the finite CI integration paths. No branch, worktree, task, issue, PR or release is created by this plan.

## API and borrowed state

lower_control_transfer returns list[str] or None. None means the original raw text did not match this family. Its eight parameters are statement, original canonical StatementLoweringContext, actual value-lowering callable, actual inherited-expression parsing callable, and the four already-normalized local/scope/macro/counter aliases. It allocates no context view. The depth/capture policies move with their plain frozen fields; inherited_event_call is read only at its existing probe phase after exit. Supported G01 inputs remain the exact frozen record/None, without a new property or duck-typed context surface.

lower_var_declarations has four parameters: declarations text, canonical context, actual initializer callable and actual constant-name guard. At the selected var branch only, statements uses dataclasses.replace to override precisely local_names, declared_local_names, scope_context, macro_values and generated_counter with the five aliases already normalized by G01. All nine other fields are retained by reference/value, including the original enum iterator and capture. There is no container copy, replacement counter, second context class, callback object or result framework.

That view is necessary because the declaration owner must repeat the existing inner normalization. It checks local/declared None, normalizes scope, materializes frozenset(enum_names or []) once, evaluates macro_values or {}, and applies the explicit counter None rule, in that order. A mapping can be truthy during outer normalization and falsey during this second check. The original enum iterator can be exhausted before an initializer. These existing behaviors remain observable. The actual initializer receives the current inner aliases, rather than a closure over the outer context or mapping.

StatementValueLowerer is one typing-only eight-argument callable alias in statement_models. Arguments are source, local names, instance variables, enum values, original enum iterable, normalized scope, current macro mapping and shared counter. Result is the existing prelude-list/emitted-text tuple. It has no capture argument, because the existing value pipeline did not receive one; control policy retains the exact capture reference independently.

The existing duplicate mutation-then-expression pipeline occurs three times: valued return, valued throw and ordinary var initialization. _lower_statement_value keeps those two real operations and exact argument arrangements, adding no normalization. _lower_var_initializer keeps the current nested-assignment predicate: it calls the unchanged assignment-to-temp helper for that route, otherwise the real shared value helper with its received eight arguments. Underlying helpers and their own later normalization are unchanged.

Inherited parsing receives the existing parse_gml_expression function directly and calls it with the original statement alone, without macro/enum/scope keywords. Constant validation receives the existing reject_constant_declaration_name function directly, called after identifier and asset validation with current inner macro keys. Neither new owner imports expression_api, enum_helpers, parser, emitter or statements. These fixed seams prevent new grammar cycles while keeping one actual implementation of each operation.

collect_var_declaration_names borrows tokens, start index and the existing parser-owned _skip_function_literal callable. It owns only temporary index/depth/name collection and returns the same ordered tuple. Cursor, function-body skipping and root/nested hoist policy remain in the parser. This one bounded var reader move provides a real parser size reduction, covering the necessary direct control/declaration imports under the existing ratchet.

## Branches, effects and errors

Keep the initial empty guard before any context work. Preserve G01 outer local/declared/scope/macro/counter normalization order. Raw probes remain return equality, return-space prefix, break, continue, exit, inherited-event probe, throw equality and throw-space prefix. There is no global strip/tokenization. Unrecognized control falls through to unchanged delete, then the existing var-space branch, then unchanged remaining families.

Return/break/continue/exit reject finally before depth, capture or value errors. Return requires function depth; exit does not. Captured break/continue require both the flag and matching capture depth. Throw remains allowed in finally; missing value errors, valued mutation/evaluation, captured value, function return and top-level call-plus-return retain exact order/text. Inherited probing retains its prefix check, grouped Call/Name recognition, no-argument error and parent-or-pass result.

Capture dispatch retains ordered return/exit/break/continue/throw guards, source flags, parent forwarding, original dictionary/value text and return-value policy. Its current nesting depth is six, so it cannot simply move intact. Split per-kind emission into one small helper while the outer ordered loop retains source gating and exact guard text; both functions must stay at nesting four or below. No reflective dispatch or callback table is introduced.

Var declarations stay left to right, skip empty comma pieces and reject unsupported operators before name validation. Identifier, asset, constant/macro and enum checks keep order. The duplicate validation sequence becomes one helper; no guard is broadened. Initializer prelude and declaration/redeclaration line precede local then declared-set mutation. Earlier declarations remain committed after a later error. Sanitization, prefix names, counter increments, iterator exhaustion and an empty supplied counter's deferred IndexError are preserved.

Switch/try capture construction, installation/restoration, finally-depth changes, catch-local cleanup and nested sharing/merge remain in unchanged parser methods. Only their direct dispatcher import changes owner. Existing globalvar/static methods and static_declarations remain byte/AST exact. Source-map owners and diagnostic text/type/location policy are unchanged; added helper stack frames do not convert errors or add catches/retries.

## Measured source and destination budgets

These are actual old-source measurements with pinned CPython 3.12.10, existing pure saved AST helpers and pinned Ruff 0.15.22. Raw command/output/runtime origin and 501 C901 rows are retained. Threshold-zero exit1 is a measurement, not a lint/test pass.

| Actual owner | Physical | Structural | C901 / nesting / parameters |
| --- | ---: | ---: | --- |
| statements module | 2766 | 4641 | — |
| transpile_statement | 1155 | 1940 | 122 / 4 / 2 |
| var helper | 84 | 169 | 10 / 3 / 9 |
| capture dispatch | 45 | 72 | 9 / 6 / 4 |
| parser module | 1149 | 2296 | — |
| var-name reader | 30 | 74 | 11 / 4 / 2 |
| model module | 76 | 143 | — |
| architecture test module | 868 | 1468 | — |
| G01 context test module | 409 | 1136 | — |

Proposed caps are design budgets, without candidate code or measured projection. Statements must shrink to at most 2640 physical/4400 structural; its lowerer to 1090/1850/C110. Parser must shrink to 1130/2240. Model stays within 160/260. New control and declaration modules are capped at 500/750 and 400/700 respectively. All new production functions must meet 150 physical/structural, C15, nesting 4 and parameters 8. All new test modules meet 800/1500 and methods 200/200/C15/nesting 4/parameters 8. The architecture cohort update stays below 880/1490, with no new exemption.

Retire exactly three old debt records: var helper structural 169, var helper parameters 9 and capture dispatch nesting 6. No corresponding debt may appear under new names. Other old keys only shrink/disappear; no suppression, allowance, cycle or packed-source workaround is accepted. Historical physical allowances 2770/1159/parser 1157 are provenance, not budgets. G02 does not force the untouched remaining dispatcher below C15/150: that final goal belongs to G05 after G03/G04.

Proposed leaf-edge analysis preserves all eleven current static cycle records and zero eager cycles. Actual implementation still needs the real full parent ratchet and phase/private-import graph gates. The var-only context view, extra helper/callback calls, new shared value-result tuples and temporary per-kind dispatch line lists add allocations/work. Original live state and prelude lists remain borrowed. These changes support no speedup or memory improvement claim.

## Before characterization and matched proof

The plan has seventeen new methods: thirteen unit bodies with 41 fixed cells, two map/diagnostic bodies and two native programs. It reuses 85 authenticated existing unit IDs and five unchanged exact-Godot methods. This is finite case data and body planning; no executable tests or controller were prepared.

Old arms wrap the real operations, recording exact positional/keyword arguments, is-identities, normalization/iterator/callback order, counter and capture mutations, emitted bytes and errors. Candidate arms keep those inputs/assertions and saved successful old observations. Only explicit real patch lookups migrate. The valued return/throw and two-stage var mapping cases fail if a callback captures pre-normalized None/falsey aliases, the outer var mapping, or a copied/lost counter. Inherited cases fail if any extra parsing context keyword is introduced. Captured outputs and nested parser observations also check original capture identity/fields and shared counter progression. Output-only mocks are insufficient.

The existing G01 var spy migrates to the new declaration entry and maps its canonical view back to the exact old observation dictionary. All existing assertions/events/identity checks and other G01 test ASTs remain exact. Existing facade, phase/model and source-map method bodies remain protected; the architecture cohort adds only two owner names.

New native programs use existing require_exact_godot/write_gml_runtime and the actual public facade in small headless projects. They cover return/finally, loop/switch continue and break through finally, nested throw/catch, exit/finally, declaration post/preincrement and actual inherited-event callback/no-parent effects. They retain complete raw logs and generated code/maps. Existing script/static/global and constructor tests remain distinct proof; constructor inheritance is not substituted for inherited-event coverage. Proposed expectations require successful exact-parent old observation before candidate edits.

After accepted entry and old arms, freeze candidate and obtain actual Pyright zero diagnostics, both Ruff paths, focused/architecture/ratchet/diff checks and independent/root code review. Run one broad full suite with exact Godot 4.7.2.stable.official.ed1daf0bf, native CPython 3.12.10, GameMaker LTS 2026 and all five pinned projects, with required successes and allowed retained skips bound before launch. Run existing R01 five-fixture/all14-field old/candidate parity and same-ref reproducibility with no new normalization/exclusion. Also compare the bounded native programs' full maps/effects, since fixture parity does not cover every control transfer. Root owns exact PR/merge/native CI and parent verification.

Performance planning reuses the eight byte-identical G01 real-facade inputs, five independent measured processes per revision and 250 passes per process, with import/warmup outside timing and output hashes outside the clock. Historical outputs are provenance only; refresh them at the actual verified entry. Preserve raw wall/CPU/RSS samples, native RSS units, dispersion and load/overlap evidence. Root must separately bind/review exact workload/order/timer/RSS source and reserve the window. No benchmark source or execution exists here, and added replace/helper costs need real review.

Before executable preparation or implementation, require root/independent acceptance of this exact C refresh, root tracked G02 concrete contract and sole-owner entry, final assigned worktree/parent/source/caller/test/full-mode/fixture/runtime/budget binding and separately reviewed literal old-characterization source. The current C source copies and retained five-fixture origin pins are design authority only; future runtime/fixture availability and exact old execution inputs must be rebound. R15 has a separate owner and entry; this package prepares none of its executable characterization. G02 completion credit is zero.
