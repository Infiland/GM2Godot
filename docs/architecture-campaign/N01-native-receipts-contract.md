# N01 accepted native receipt contract

Root accepted this contract and the six independent-review refinements below on 2026-09-05. Implementation owner: audit_transactions_cli in GM2Godot-080-native-receipts, branch dev/080-native-receipts. Independent reviewer: audit_policy_tests_docs, followed by root. Base f87aa69 contains frozen, reviewed C01/R01/D01 candidates; integration remains in dependency order. Live issue [#860](https://github.com/Infiland/GM2Godot/issues/860)
was reread and remains OPEN. This is the native prerequisite of #844 after #859, not an Included Files
redesign. C01 and the integrated R01 runner are dependencies. One implementer and separate native/code
reviewers own the eventual task; Windows and Linux execution are missing evidence until CI runs.

## Existing evidence and bounded ownership

The public operation is scripts._anchored_output.publish_identical_receipt_bytes(Path, bytes).
It already owns parent binding acquisition, publication leases and finally-based cleanup.
Windows retains every directory ancestor without delete sharing, opens an existing receipt with
read sharing only, validates disk type/basic/standard/file-ID metadata, flushes file data, renames the leaf within the retained source directory (native rename RootDirectory is NULL), and revalidates bytes/identity. Private lease types are not a test API.
The old test_anchored_receipt_windows_integration module uses FakeKernel32/FakeNtApi; retain those
modeled fault cases, but they cannot fulfill native NTFS acceptance.

Do not change receipt production/lease APIs for test access. New native tests invoke the public
publisher, verify real filesystem state and use finite DLL-call interleavings only for timing and
specific injected failures. No private symbol imports/calls, suppressions, or getattr-based private
access. No production model/lease extraction is needed by this contract.

## Exact proposed allowed files

New cohesive native proof owners:
- tests/test_native_receipts_windows.py: real NTFS success, rejection and interleavings.
- tests/windows_receipt_native_support.py: bounded native DLL instrumentation, ABI observations,
  volume/handle queries and junction setup; no fake filesystem or generic syscall framework.
- tests/test_native_receipts_posix.py: Linux/macOS absent creation, identical inode preservation,
  different-content rejection, public parent/file namespace behavior and cleanup.
- tests/test_native_receipts_darwin.py: physical-path behavior through the /tmp and /var aliases.
- tests/test_native_receipt_producers.py: normal bootstrap/environment and R01 receipt writers.
- tests/test_native_receipt_gate_policy.py: small exact manifest/workflow/skip/timeout contracts.

Existing bounded integration owners:
- architecture-verification.json: R01 explicit conversion-parity kind plus N01-linux/N01-macos/
  N01-windows native-receipts definitions; original R01 parity payload preserved.
- scripts/run_required_unittest.py: explicit validation discriminator, native runtime prerequisite,
  zero-skip native policy and anchored receipt publication.
- scripts/capture_conversion_parity.py: only replace the duplicate temporary-replace receipt writer
  with the existing anchored publisher, keeping canonical JSON bytes unchanged; narrowly handle AnchoredOutputError in main as specified below.
- tests/test_required_unittest_runner.py and tests/test_capture_conversion_parity.py: narrowly scoped
  discriminator and fresh/identical/different receipt regressions; no broad owner growth.
- .github/workflows/tests.yml and .github/workflows/dependency-locks.yml: invoke required native gates
  inside existing real native jobs; upload their receipts with missing-file failure.
- docs/wiki/Contributing-and-Testing.md: exact native commands and durability limits.
- maintainability-baseline.json: reductions only if actual existing debt shrinks.

No edits to _anchored_output.py or _anchored_receipt_*.py, release.yml, versions, dependency locks,
receipt schemas, existing huge modeled tests, or generic frameworks. A discovered real native defect
requires a separate explicit invariant/API refinement from root before broadening files.

## Native matrix and required-gate interface

Keep the R01 runner, not another runner. Add required validation_kind with exactly the explicit
conversion-parity and native-receipts cases. Missing/unknown kind fails. R01 must remain the
conversion-parity case and must still load/validate its entire parity definition: deleting its parity
object or fixture/runtime evidence fails, never falls through to a native/unit-only path. Native mode
is allowed only for the three enumerated N01 gate IDs, with exact ID-to-native-tuple binding.

N01-linux: Python 3.12.13, sys.platform linux, machine x86_64.
N01-macos: Python 3.12.10, sys.platform darwin, machine arm64.
N01-windows: Python 3.12.10, sys.platform win32, machine AMD64, actual NTFS volume.

Each manifest definition declares exact individual unittest method IDs, required source/lock files and
allowed_skips {}. Add a small typed native runtime record in the runner if useful; do not make Godot
optional in the R01 runtime record. Native validation fails wrong platform/runtime before collection.
Native filesystem prerequisites raise failures, not SkipTest. Ordinary repo-wide discovery may keep
platform decorators; the explicitly selected native gate must execute every selected test without a
skip. Require exact equality between the declared and discovered method-ID inventories, positive collection and testsRun == discovered count in addition to the existing rejection
of errors, failures, expectedFailures, unexpectedSuccesses and undeclared skips. Reject duplicates.

Tests workflow invokes Linux in test, macOS in macos-managed-output-transactions, Windows in
windows-artifact-transactions. Dependency Locks generate invokes the corresponding gate in every
one of its three native matrix entries after the native environment is established. Preserve all
five Tests jobs, all three dependency host entries, C01 exact terminal inventories and full submission
guard. No if/continue-on-error on a required native step. Set finite native-step/job timeouts;
missing receipt upload fails. Static mutations prove removal, conditional bypass, wrong tuple,
allowed skip, continue-on-error and missing timeout are rejected. Actual cancellation/timeout fails
its containing job and therefore its unchanged C01 child terminal and ci-success.

## Finite NTFS proof cases

1. Absent creation yields exact payload, regular disk file, expected private attributes, nonzero stable
   volume/file ID, single link, no stage leftovers. Same payload preserves file ID; different payload
   fails without touching existing bytes/identity.
2. Create a real hard link to an existing target; same bytes still fail because link count exceeds one.
   Use actual metadata queries. A directory target and real junction/reparse ancestor/parent fail closed;
   verify outside/junction destinations remain untouched. Use actual mklink /J or native reparse setup,
   no modeled junction. Missing native capability fails the required gate.
3. While each retained test-owned ancestor and output-parent handle is live, attempt real rename/removal/replacement
   and require Windows sharing denial. After the publisher returns, the same namespace operations must
   succeed, proving retained handles were closed. Observe sharing flags on trusted drive/volume roots;
   do not attempt to rename a host volume root.
4. During existing-target reading attempt actual replacement, hard-link/write access and renaming;
   require replacement/rename denial and unchanged original file ID/content. If a hard-link operation
   is permitted by NTFS, require the real metadata recheck to reject the changed link count; never
   interpret a successful unsafe mutation plus successful publication as a passing test.
5. During staging (after actual create/write and before native rename), attempt real stage substitution,
   ancestor substitution and target-name collision. Require no overwrite; compare the concurrent winner
   by actual file ID/bytes and preserve unrelated files.
6. Long physical Unicode paths exceeding traditional MAX_PATH publish and reuse successfully.
7. Observe real NtCreateFile, ReadFile, WriteFile, FlushFileBuffers, GetFileInformationByHandleEx and
   NtSetInformationFile inputs/results. Validate actual ABI argtypes/restype and buffer sizes/layouts,
   fixed-width NTSTATUS/ULONG/WCHAR, pointer-width OBJECT_ATTRIBUTES/IO_STATUS_BLOCK/UNICODE_STRING,
   rename info alignment, reparse options and directory/target sharing flags. Successful real operations
   and independent metadata reads are required; layout assertions alone are insufficient.
8. Fail before publication at a chosen real operation (e.g. after actual stage write and before flush),
   retaining the injected error and proving stage cleanup plus handle closure. For a post-native-rename
   injected exception, verify the published namespace identity is retained and not disposed. Do not
   pretend an injected failure proves a real disk durability failure.
9. Capture handles returned by successful real opens and verify they are invalid after return or
   failure using actual GetHandleInformation; also verify post-call rename/delete works and bounded
   repeated-call handle counts do not grow. Leave CloseHandle as the real ctypes function: production
   _native_close_handle_address chooses its native ownership path from that function address, so wrapping
   it in Mock would exercise a different close path.

For instrumentation, capture the real ctypes.WinDLL factory before a bounded patch; return real loaded
DLL objects. Wrap only the explicitly needed public native function fields, forward argtypes/restype
assignments to the real callable, preserve last-error semantics, and delegate all non-injected calls.
A small typed callable protocol/helper is appropriate; no dynamic name registry, fake API model, or
private lease instance. Observe ABI through the configured public native callable signature and real
buffers, rather than importing private production ctypes structure classes. Keep CloseHandle untouched.

## Normal producers and receipt ownership

The ordinary bootstrap and dependency-environment CLI already share
verify_dependency_environment.atomic_write_receipt -> anchored publisher. Workflow inspection shows
unique RUNNER_TEMP bootstrap/dependency paths per test/release job, and dependency-locks refuses an
existing work root before creating its distinct bootstrap/current/candidate/fresh-1/fresh-2 paths.
Fresh-1 and fresh-2 are separate destinations compared for normalized equality; different-byte
replacement is not required. Retain all native environment verifier invocations.

Run bootstrap and actual installed-environment verification twice into a fresh then identical path on
each native host; assert byte and file-ID/inode equality, then different content fails without mutation.
This exercises the same producer used by test/release bootstraps, not a modeled writer. Existing release
build jobs provide the actual release-environment receipt evidence when C02/final release executes;
N01 must not claim that remote release execution has already happened.

The two R01 write_receipt functions currently perform mkdir plus NamedTemporaryFile.replace and thus
permit different-content replacement. Replace those small bodies with canonical serialization plus
publish_identical_receipt_bytes. The existing publisher owns parent creation and cleanup; no second
writer owner. Receipt schemas, JSON ordering/encoding and public CLI arguments remain unchanged.
Successful identical reuse preserves identity; different receipt output fails rather than overwriting.
This ownership change is confined to two writers and their focused tests, not parity conversion logic.

## Proof, metrics and completion

New test/helper owners target <800 physical lines, no structural/module debt, functions <=15 McCabe,
<=150 physical lines and no new suppressions. Existing R01 owners are run_required_unittest260,
capture_conversion_parity486, runner tests160 and parity tests584 physical lines before N01; measure
all destinations under R02 before acceptance. Keep native support cohesive rather than growing old
oversize modeled tests. Existing 15 validation jobs and seven-call C01 graph retain their requirements.

Require local Pyright 0/0, Ruff, focused new/runner/workflow tests, exact native macOS zero-skip receipt,
full unittest, immutable-parent ratchet, actionlint and diff check. Independent reviewer reruns contract
mutations and traces both success and failure ownership through actual public publication.
Linux/Windows artifacts are external evidence until exact-revision CI runs; every required native gate
must be green with zero skips and published receipts. #844 remains open until issue860 native matrix
and ordinary dependency workflows pass on the exact merged commit. Preserve POSIX directory-entry
fsync guarantees separately from Windows file-data flush plus namespace revalidation; do not claim a
retained-directory flush on Windows or supported behavior on an unproved filesystem.

## Accepted independent-review refinements (authoritative)

1. Freeze the required native method IDs per host and compare exact discovered
   IDs, not merely a positive count. Policy mutations must reject deletion of one
   method, an empty class, omitted cases and duplicates. Keep these mutations in
   the new policy-test module.
2. Tests jobs use their existing verified environment and stable bootstrap
   policy. Dependency Locks invokes the gate through `$CURRENT_PYTHON` and the
   committed-generator producer profile: `native-lock-workflow`, ordered
   requirements `pip,pip-tools`. Its N01 artifacts live outside `RECEIPT_DIR`,
   whose exact eight-receipt contract remains intact; upload N01 separately with
   missing-file failure. Do not invent a second environment verifier.
3. Include actual `CreateFileW` ancestor acquisition in bounded observations.
   Forward factory arguments and real calling conventions and argtypes/restype.
   Keep CloseHandle untouched. Preserve incoming ctypes last-error across
   pre-hooks; capture ctypes.get_last_error immediately after the delegated call
   and restore it after observers/fault hooks. Raw GetLastError is insufficient.
   Independent metadata reads use the captured unwrapped WinDLL factory.
4. Verify the actual rename ABI: RootDirectory is NULL and the leaf is relative
   to the open source handle's existing directory. Check captured handle validity
   immediately after publication before opening unrelated handles that could
   reuse the numeric values. Namespace operations and bounded handle counts
   supplement that evidence.
5. Both R01 receipt CLIs currently write outside their exception handlers. Permit
   narrowly scoped handling of AnchoredOutputError in their existing main
   functions. Conflicting output returns an explicit nonzero status and a useful
   publisher error code, retaining exception information. Do not catch process
   control exceptions. Characterize fresh, identical and conflicting output
   through both CLI and writer entry points. This deliberate no-overwrite receipt
   behavior belongs to #860; do not hide it as a body-only refactor.
6. Initial physical/structural sizes: runner 260/588, capture 486/791, runner
   tests 160/274, parity tests 584/1272. Capture has nine structural units of
   headroom before duplicate writer removal. Every destination must satisfy the
   existing ratchet with no new allowances or suppressions.

N01 alone owns architecture-verification.json until its schema is frozen. R10
records its proposed exact IDs externally; root adds that inventory afterward
through a serialized edit. Its future conversion-parity kind must retain the
full parity prerequisite, not become a native-only bypass.

Root owns the ledger and contracts.json after acceptance. The implementation
owner may update this contract only for factual evidence and approved scope.
No additional production native-lease files or new public test-access APIs are
authorized. A discovered platform defect requires a bounded root refinement.
