# I03 Windows operations and validation streams

Root accepts the previously reviewed I03 / #798 ownership contract against
verified campaign parent `5faa683a07a913c96d5283d06b8e2cb1b44e5b30`, tree
`610510164786071400b095901b21f0182b118fc7`. The Included Files coordinator,
retained test family and immediate model/filesystem dependencies are unchanged
from the proposal basis. The actual parent includes verified I02 and L02 work.

Independent and root review accept the corrected old binding observation and
the unchanged concrete migration map. Root assigns `review_r13_full` as the sole
implementer in `dev/080-windows-filesystem`, using the existing
`GM2Godot-080-i03-preflight` worktree. Apply the eight reviewed extraction projections and the bounded typing
correction below, with necessary import ordering. Preserve further failures
for review before making another semantic or policy change.
Root owns integration and will review the actual implementation after a separate
reviewer has inspected it. Version and release work remain reserved for v0.8.0.

## Ownership and scope

Move exactly fifteen top-level definitions and seventeen fixed constants into
three leaves. Keep 175 coordinator definitions under the declared canonical
symbol translation. The coordinator retains transaction decisions, traversal,
quarantine, readonly cleanup, rollback, phase hooks and project-lock policy.

| Owner | Canonical definitions |
| --- | --- |
| `windows_operations.py` | `lock_file`, `WindowsFileId128`, `WindowsFileIdInfo`, `WindowsFileBasicInfo`, `file_read_api`, `cleanup_parent_api`, `transaction_api`, `transaction_error`, `extended_path`, `rename_transaction_entry` |
| `windows_bindings.py` | `cleanup_parent_identity`, `cleanup_parent_attributes`, `WindowsCleanupParentBinding`, `verify_cleanup_parent_binding` |
| `filesystem.py` | `open_validation_stream` |

The coordinator imports final owners directly. Filesystem depends on Windows
operations; Windows bindings depends on Windows operations, existing filesystem
metadata and models; Windows operations depends only on the standard library.
Leaves never import the coordinator or receive callbacks into it. Remove old
private definitions and names without aliases or forwarding wrappers. Separate
same-spelled implementations in asset_registry are outside this task.

The implementer owns only these ten implementation paths:

- `src/conversion/included_files.py`
- `src/conversion/included_files_parts/windows_operations.py`
- `src/conversion/included_files_parts/windows_bindings.py`
- `src/conversion/included_files_parts/filesystem.py`
- `tests/test_included_files.py`
- `tests/included_files/test_windows_operations.py`
- `tests/included_files/test_windows_bindings.py`
- `tests/included_files/test_filesystem.py`
- `pyrightconfig.json` (only the accepted global platform field)
- `scripts/_anchored_output.py` (accepted module types and direct WinDLL construction)

Root alone owns the measured baseline, the finite native Windows workflow step,
this contract, contracts.json and the ledger. Preserve all existing gates,
coverage floors and native commands. No change to crash-recovery tests, package
initializers, dependencies, version metadata or other resource families is needed.

## Behavioral and lifetime contract

Keep all ctypes widths, record layouts, argtypes/restypes, flags, sentinels and
error filenames. The three API loaders remain lazy and independently cached
with maxsize one. Imports must not load DLLs or import msvcrt eagerly. Retain
extended path spelling and the three existing rename routes, including modeled
Windows behavior on a non-Windows host and real MoveFileExW write-through.

Keep the mutable binding's `path, identity, kernel32, handle` field order. Reject
invalid paths and identities before acquisition; retain verification order,
non-delete-sharing handles, BaseException handling and close-note order. Clear
the handle before CloseHandle, preserving one-shot close even when it raises.
Keep context-entry failure behavior and active-error versus close-error precedence.

Validation-stream acquisition remains one complete cross-platform operation.
Preserve ordinary open and POSIX no-follow behavior. On Windows, successful
HANDLE-to-fd conversion transfers ownership away from kernel32; successful
fdopen transfers it to the caller-owned stream. Failed transfers close only the
resource still owned by that stage. Preserve existing cleanup exception
precedence and the distinct stream/transaction error lookup order.

The approved eight direct attribute reads replace constant-name getattr calls:
WinDLL three times, get_last_error twice, FormatError twice and msvcrt.locking
once. Preserve attribute acquisition and invocation order. The bounded typing
correction removes three identity casts diagnosed as unnecessary; retain the
other five callable casts. Retire the six old B009 keys rather than moving their
allowances. The initial typing failure and root decision remain recorded below.
No new Any, module cast, Protocol, fallback getattr, alias, suppression, exclusion
or allowance may conceal a diagnostic.

## Bounded typing correction

The exact eight applied projections first produced 22 Pyright errors and zero
warnings. Fifteen errors arise from mutation through vars(module), whose selected
stub overload returns a mapping proxy. Seven concern Windows-only attributes and
an import used only in a platform branch omitted by Mac-target analysis. Preserve
that initial failure; no characterization or broad test followed it.

Replace exactly thirteen vars(os)/vars(ctypes) expressions in the two new test
modules with the same module's __dict__. This preserves the live dictionary,
patch.dict scopes, manual removals/writes, restoration and every assertion.

Set only pythonPlatform to All in the existing strict Pyright configuration.
Retain the includes, excludes, Python version, severities and required command.
This analyzes all platform branches together and exposes platform declarations;
it does not establish that an API exists on every individual host. Keep all
actual native and modeled platform gates. A scoped Included Files environment
was investigated and rejected because imported ctypes/msvcrt stubs retain the
default environment. Do not hardcode local tooling paths or a host platform.

Under All, remove exactly three unnecessary identity casts: locking and
transaction_error's get_last_error in windows_operations, and get_last_error in
filesystem. Preserve lookup and invocation order, remaining casts and lazy imports.

All also exposes one old optional-module typing problem in _anchored_output.
Import ModuleType from types and narrow only four annotations: the local
windows_receipt, _load_exact_sibling's return, _windows_receipt_cache and
_windows_receipt_module's return. The optional local/cache values retain None;
the two helper returns are ModuleType. Existing loader returns are validated
sys.modules entries or module_from_spec results. Preserve loader bodies, guards,
cache lifetime, import resolution, errors and side effects. The one additional
Windows constructor simplification required by measured debt is defined below.

The diagnostic All check with the correct project root reported nineteen errors:
the fifteen dictionary errors, three unnecessary casts and that one inherited
module diagnostic. It is diagnosis only, not acceptance. Run the ordinary required
Pyright command on the actual corrected checkout and require zero errors and
warnings before proceeding. Preserve all initial and diagnostic logs under I03;
the source correction and platform proposal require independent and root review.

## Bounded metric correction

The applied typing correction passed the ordinary Pyright command with zero
errors/warnings and both Ruff checks. The complete static audit then examined
all sixty fresh functions and ten implementation paths. It found three affected
owners: the argument-mismatch test at nesting five, the native validation-stream
test at nesting six, and the existing anchored-output module growing from
2,430/4,370 to 2,431/4,371 physical/structural units. Preserve these findings;
no characterization or other behavioral proof was run on that source.

Extract two narrow assertion helpers from the new tests. In the bindings test,
move only the innermost verify mock/assertRaises block and its post-assertions
into _assert_binding_mismatch, called inside the same outer scopes. In the native
filesystem test, move only the assertRaises(PermissionError)/forbidden-writer
block into _assert_write_access_denied, called while the validation stream is
still open. Preserve every case, assertion, native skip decorator, patch scope,
resource acquisition/close order and public test ID. Expanding the helper calls
must reconstruct the previous test-module ASTs, apart from the helper definitions.

In _anchored_output._windows_file_api, replace the constant-name getattr,
identity callable cast and single-use win_dll local with the direct
ctypes.WinDLL("kernel32", use_last_error=True) constructor. Global All exposes
this existing native API to the checker. Preserve the platform guard, one lazy
lookup/load, constructor arguments and every subsequent ABI assignment. This
retires that existing B009 entry and removes actual syntax, keeping the added
concrete module types within the unchanged size allowance. Do not remove blank
lines, compress statements or increase allowances to satisfy the metric gate.

These three file corrections require independent/root source review before
application. Run the ordinary required Pyright and both Ruff checks afterward,
then repeat the complete static audit and require no fresh limit violation or
existing allowance growth. All prior type/lint/metric failures remain immutable.
The original six Included Files B009 retirements remain mandatory, together with
the one anchored WinDLL B009 retirement. Behavioral/native proof follows the
same reviewed sequence below.

## Characterization and binding migration

The accepted old characterization has eighteen actual local successes and no
skips. The twenty reviewed candidate methods comprise eight operations, six
binding and six filesystem cases; two require actual Windows. Preserve all 222
retained test IDs, all 825 main-module assertion ASTs and every scenario.

The first 39-test observer passed its test policy but captured no bindings; that
result remains preserved and rejected as binding proof. The corrected run has
35 successes and four exact existing Windows-only skips. It captures all 77
possible test/lifetime pairs, with 97 patch instances installed and restored.
Forty-two of 43 source patch sites have actual interception; the parent-change
helper's rename site correctly has zero calls after pre-rename rejection. Keep
that negative behavior. Actual verifier delegation is established by Mock and
real-code identity, not simply by observing a call inside a patched scope.

Preserve all 43 patch arguments, wraps, side effects and lifetimes: forty lexical
sites in twenty-one headers and three returned ExitStack sites with ten consumers.
Patch coordinator lock/rename/stream/verifier bindings at their new canonical
names. Patch the stream's loader in filesystem, binding loader/identity/attributes/
error in windows_bindings, and rename's loader in windows_operations. Class-open
patches target the same canonical WindowsCleanupParentBinding class object.
Modeled OS/kernel calls establish behavior, not native Windows success.

## Measurements and completion proof

The before coordinator has 11,139 physical and 15,473 structural units; the
reviewed implementation has 10,720 and 14,769, removing 419 physical lines and
704 structural units. The three leaves measure 215/315 (operations), 237/280
(bindings) and 84/107 (filesystem). Together with the coordinator they add 117
physical lines and remove two structural units. Do not claim repository-wide
shrink or a thin coordinator. Fresh functions must remain within C15,
nesting four, eight parameters and 150 physical/structural units. Leaf caps are
operations 300/500, bindings 300/400 and filesystem 120/150 physical/structural;
each new test module is capped at 600/1400. No retained allowance may grow.

Use the approved CPython 3.12.10 environment and exact Godot
`4.7.2.stable.official.ed1daf0bf`. After applying the eight reviewed projections,
run Pyright with zero errors/warnings and both Ruff checks, explicitly including
all six new files. Apply only necessary import ordering under the unchanged
120-column configuration. Preserve initial failures and review any semantic fix.

After type/lint fixes, compare the same eighteen candidate characterizations
with the accepted old results and run the 242-method Included Files cohort,
naming every skip. Root then measures the baseline against actual 5faa and
requires all seven B009 keys retired, including anchored output, with no added
or increased debt. After source
freeze, independent and root actual-code review precede the full suite with
all five pinned external projects, Included Files parity and same-ref control.
Keep output bytes, modes, logs, outcomes, ordering and failure phases exact.

Native Windows must run the reviewed 34-method selection without skips: twenty
new methods plus fourteen retained cases. Preserve all I02, scale, containment,
bind, crash/recovery, CLI, Godot and artifact proof. Exact PR and campaign-merge
verification are mandatory before I03 counts as verified. Later campaign changes
require a bounded actual-parent integration review.

The immutable proposal, projections, characterization, rejected and corrected
observer results, and implementation handoff remain under
`/Users/infi/Documents/Github/.gm2godot-v080-evidence/I03`. This document adds no
new framework, transaction behavior, compatibility layer or release scope.

## Accepted entry evidence

The original proposal index is
`2560672c47e58d496b843878166758225f3ba5e1dbf601f9c68f459163ac035f`
and the authored characterization index is
`6d6ad908d19e33f9ae693d34be4d727fc030508f0007a217cacf4316ce38d089`.
The corrected observer result is
`2b5fcb2402ea3219356a77f089a7994c960cc492341a9ab8c8006e4223c42132`;
independent actual review is
`211479543cf5b1e2e72885888b04ce36b3c19be3312746c7288af606cb008557`
and root actual review is
`a22d95cb597dbb26546d4cbd1ec86e732b9d79fbcbd51669dd3833f7a7a5f8f0`.
The handoff index is
`0753ef2388a861d00384e354023a12639003720b67202fad51d639e756347cec`.
All 601 old source/overlay hashes were unchanged immediately before entry
metadata was added. The committed entry contains 602 files: 599 unchanged, two
updated metadata files and the new contract. The actual baseline has 1,044 entries. The observation reaches eight zero-call generations, only
same-target stack depth one and normal patch-method returns; it does not claim
shadowing or patch-method unwind coverage. Candidate and native proof remain
outstanding. Preserve the old evidence without rerunning its source-bound tools
after this branch changes.

## Accepted local implementation proof

The implementation and its bounded typing and metric corrections are approved
independently and by root. The 18 characterizations passed; the 242-method cohort
had 225 successes and 17 exact host skips. The 39-method observer had 35 successes
and four exact Windows skips, with all 77 pairs and 97 patch generations observed.
These executions retain their original source-map identity `110fcd94`; their
raw evidence is not relabeled after subsequent source changes.

The strict baseline update then found three fresh B023 closure diagnostics in
the new close-answer test. Its corrected public method keeps both answers in
the original order and calls one typed `_assert_close_answer` helper per answer.
Inlining the complete helper reconstructs the entire prior module AST exactly.
All six bindings methods passed with zero skips on the corrected source map
`1b242d30`. Pyright reported zero errors/warnings and both Ruff checks passed.
The new bindings test module measures 280 physical lines and 945 structural
units; the helper measures 25/69. No suppression or allowance was added.

Against 5faa, the accepted baseline has 1,037 entries, down from 1,044: seven
removed and six lowered, with none added or grown. All production files, the
retained main test module and the observer remain unchanged by that test fix.
Independent correction review is `089c0b389de8c325e6946480da19b51dfafaf83cb453df9487b897d8b4166c34`;
root review is `11dfb18b76fe45557e28104b7a283a6936235f9a7ad1216ea423baff51266e64`.

Root will compose the verified R13 campaign parent before freezing the final
source for full-suite, Included Files parity and actual Windows verification.
The regular Windows workflow adds the reviewed 34-method selection. Its eleven
negative/collection controls use a separate temporary proof commit whose parent
is the frozen candidate; that proof commit is never merged into the campaign.
Final full/native results and exact PR/merge verification are still required.
