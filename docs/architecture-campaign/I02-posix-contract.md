# I02 / #798 — Included Files POSIX operations and native stat metadata

Status: proposed for root acceptance and an independent contract review. This is read-only planning at verified I01/R11 parent `1196295179296dfc12274ff39ba79e6adfb4a1b2`, not implementation or executed native proof. The root-owned worktree is clean. All source-backed inputs, exact test IDs, per-symbol names and the import-normalized external projection are frozen beside this proposal. The earlier f40402c checkpoint is retained as history; current hashes and I01 canonical model imports are authoritative.

## Problem, benefit and owner

`src/conversion/included_files.py` still combines native descriptor operations and shared stat projections with traversal, Windows bindings, staging, publication and recovery. Sixteen cohesive POSIX functions plus five shared metadata functions can acquire obvious canonical owners without redesigning the transaction. This removes 387 physical/596 structural units of function bodies from the coordinator; direct imports keep every retained function's physical and structural size from growing. The extraction does not claim to finish #798 or to make the remaining coordinator thin.

Implementation owner: audit_transactions_cli, in a root-created isolated worktree after acceptance. Independent reviewer: assigned by root, then root reads the actual code. Root alone owns shared baseline/coverage/verification metadata, campaign documentation, ancestry/integration, commit authorization, PR/push and native CI.

## Exact source ownership and API

Move the 16 definitions listed by old/new name in `119-projection-initial.json` into `src/conversion/included_files_parts/posix_operations.py`:

- descriptor_paths_supported, native_noreplace_available;
- open_pinned_directory, open_pinned_parent;
- directory_identity_from_fd, verify_directory_fd;
- entry_stat_at, verify_entry_at;
- rename_transaction_entry_at, preserve_or_restore_unexpected_moved_entry_at;
- linux_mount_id_from_fd, directory_mount_id;
- verify_mount_boundary, verify_mount_boundary_path, verify_directory_entry_identity_at;
- sync_directory.

Move the exact DIRECTORY_OPEN_FLAGS expression with its descriptor users. Preserve its existing bits and normal module-import initialization; it is now initialized by the canonical lower module imported before the coordinator body. It is not recomputed at each call. Capability functions retain their existing dynamic os/sys lookups.

Move five definitions into `filesystem_metadata.py`: output_path_is_redirected, path_fingerprint, path_handle_binding, handle_state and source_fingerprint. Preserve all tuple fields/order, annotations, values, casts and branch/exception behavior. This leaf is shared by POSIX and retained Windows paths. Its junction facility check is a native-capability lookup, so it is not described as purely arithmetic or POSIX-only.

Dependency direction is `included_files -> posix_operations -> filesystem_metadata -> models`, with direct model imports from POSIX as needed. Metadata imports I01 HandleState, IncludedSourceFingerprint, PathFingerprint and PathHandleBinding; POSIX imports PathFingerprint and PathIdentity. No lower owner imports the coordinator, planner, traversal/snapshot owner, codecs, Windows APIs or cleanup. No package initializer reexport, adapter, protocol, service object, move allowance or forwarding function is added.

Production callers use the canonical public functions through direct imports. The projection freezes the exact imported set: 15 POSIX functions plus DIRECTORY_OPEN_FLAGS and all five metadata functions. native_noreplace_available is used only inside the POSIX owner and by canonical tests, so the coordinator does not import it. Ordinary Python imports bind the current callable once when the importing module loads. Production has no supported dynamic-rebinding API; tests target actual lookup sites. Remove all 21 old private definition names and the old constant name, with no compatibility aliases. The new modules own the canonical API; copied coordinator import bindings are implementation dependencies, not promised reexports.

There are 63 retained qualified production callers. Replacing a global Name with its canonical Name preserves their expression shape. The naive module-qualified projection that grew 19 oversized retained functions is explicitly rejected. No decomposition of unrelated lifecycle functions is needed to pay for qualification nodes.

## Lifecycle and behavior retained

open_pinned_directory owns its current descriptor while opening successive components. It resolves only the first absolute component as before, uses the same no-follow directory flags and dir_fd operations, closes the previous descriptor as it advances, and transfers one live returned descriptor. It does not retain the entire ancestor chain. open_pinned_parent transfers that descriptor plus the movable leaf. Preserve existing BaseException cleanup and close-error precedence exactly; no new exact-once or close-failure guarantee is claimed.

Identity, stat, verification and rename functions borrow parent descriptors and never close them. Native rename still uses actual Darwin renameatx_np with RENAME_EXCL=4 or Linux renameat2 with RENAME_NOREPLACE=1, preserving fsencode, reset/read errno and error status. It never fsyncs. Reverse restore/quarantine still uses exclusive native moves, preserves unexpected bytes in place or in a unique sibling quarantine, returns the same OSError/notes, and leaves all handle ownership with the caller. It does not acquire general recovery ownership.

The fdinfo reader owns its text stream. Non-Linux/unreadable OSError returns None; malformed, duplicate, non-ASCII or non-decimal mount IDs retain existing rejection; missing IDs and decoding exceptions retain their actual source behavior. directory_mount_id and path mount fallback own their temporary descriptors and close in the existing finally. Device/ismount fallback, no-follow open, kind/samestat and descriptor mount checks stay unchanged.

sync_directory remains a Windows no-op. On POSIX it owns a temporary pinned directory FD, verifies identity, calls actual fsync, verifies again and closes in finally. Higher owners retain all durability ordering. File type versus full mode, ctime and nlink membership remain distinct in the four stat projections; unavailable/noncallable junction behavior and native checker errors remain unchanged.

Keep traversal/source binding/tree capture, Windows APIs and leases, staged payloads, worker draining, journal/commit/stage records, locks, publication, rollback, cleanup and final release where they are. Preserve all public IncludedFilesConverter signatures/outcomes/messages/output bytes. #877's early interruption/primary-error issues remain separate I07/I10 work; I02 must not fix cancellation or normalize cleanup errors.

## Exact test migrations and binding policy

`119-existing-test-ids.json` freezes 212 current Included Files method IDs (190 original module plus22 I01 leaf tests). Retain all of them, with exactly three ownership moves: the mount-ID parser/boundary case and the native no-replace occupied-destination and unavailable-capability cases move from TestIncludedFilesManagedRootTransaction to TestIncludedFilesPosixOperations in `tests/included_files/test_posix_operations.py`. Their method names and complete assertions/fixture payloads remain; only canonical call/patch targets and the cohesive TemporaryDirectory fixture change. Do not retain aliases for old IDs.

`119-caller-bindings.json` identifies 56 qualified test consumers within51 direct consuming test methods and46 exact patch sites, including34 capability patches. Direct canonical imports replace moved-function calls and saved real delegates. A single local Boolean in test_owned_tree_cleanup_preserves_modeled_nested_mount changes from descriptor_paths_supported to descriptor_supported to avoid shadowing the imported function. All other current non-migration method ASTs must remain exact.

No generic patch helper or blanket double patches are proposed. Most patches stay on the retained coordinator's new imported binding. The lower parser/boundary test patches posix_operations.linux_mount_id_from_fd, and the unavailable-native-operation test patches posix_operations.native_noreplace_available. The parent-close failure case patches included_files.open_pinned_parent and included_files.linux_mount_id_from_fd, retaining its actual delegated parent FD and immediate invalidation assertion. Sync hooks patch included_files.sync_directory but call the directly imported real canonical function. source_fingerprint's existing special native-stat model patches the retained lookup. Existing os/sys module-object patches still affect the same shared standard-library objects.

The backup-collision hook is expected to need only included_files.rename_transaction_entry_at: the injected occupied destination causes the real exclusive rename to fail before the post-success restore/quarantine branch. Capability False cases avoid lower open_pinned_directory through retained fallback paths, mocked sync, Windows early return, pre-sync failure, or no-stage no-op verification. The inventory states the source-backed rationale for each site, not executed proof.

Before production changes, run the exact affected cases with bounded external real-delegation/source-origin observations and preserve their output. Record normalized moved-function/caller edges by test ID; retain no frames or descriptor resources. Original callables remain real. The candidate must reach equivalent intended injection boundaries and satisfy all existing native-delegation/sentinel/pair/debris/error assertions. If a retained scenario actually reaches both old-global meanings, stop and propose its exact two canonical bindings plus a reached-call proof; do not silently broaden patches or invent a live-forwarding adapter. This is a pre-production characterization prerequisite, not a relaxation of final equivalence.

## Ten new characterizations and size limits

`I02-characterization-and-native-plan.json` freezes ten proposed method IDs and their effects/assertions: seven POSIX cases and three metadata cases. They cover owned FD transfer and failed child-open closure before numeric reuse; borrowed identity/fingerprint checks; actual native rename success/errno; restore/quarantine preservation; finite fdinfo failure policies; real fsync ordering/error/closure; complete stat tuples; symlink short-circuit/unavailable junction policy; and unchanged native-checker result/error forwarding. Every new method must be run against the immutable pre-extraction implementation before moving production, using a one-use external exact import/patch-name translation to the existing real functions. Preserve that finite translation source, source hashes and unchanged assertion bodies; do not implement a second algorithm or a repository compatibility module for the characterization.

Observe invalidated FDs inside the real close observer immediately after delegation and before a later open can reuse the number. A post-return list of old numeric FDs alone is not valid closure proof. Native delegation is required; injected branch/metadata models are explicitly labeled and are not the sole proof for syscalls, NTFS, privileged mounts or persistence. Current cleanup/exception quirks must be characterized, not repaired.

Fresh production functions stay <=150 physical and structural, tests <=200 physical and structural, complexity<=15, nesting<=4 and parameters<=8. New POSIX module target<=600 physical/800 structural; metadata<=150/200. New POSIX test module including ten methods and its fixture stays<=750 physical/1400 structural; metadata test module<=200/500. No threshold, suppression, exclusion, import-policy, stale allowance or policy-protection changes are allowed. If a proposed test cannot fit, revise its cohesive proof before acceptance rather than relocate debt.

## Measured projection

`119-projection-metrics.json` binds the exact external projection after the current global import settings (120 columns, combine aliases, no split on trailing comma). This projection contains moved production and the three existing test moves, not the ten unwritten new tests.

| Owner | Before physical / structural | Projected physical / structural |
| --- | ---: | ---: |
| included_files.py | 11,552 /16,077 | 11,140 /15,473 |
| posix_operations.py | absent | 383 /525 |
| filesystem_metadata.py | absent | 80 /97 |
| test_included_files.py | 12,420 /21,674 | 12,295 /21,384 |
| test_posix_operations.py, three moved cases +fixture | absent | 164 /278 |

The three production modules together grow by51 physical/18 structural units from the two explicit lower-owner headers/import boundaries; no new production algorithm is added. This is an ownership extraction and shrinking coordinator, not a claim of aggregate line reduction. All retained function physical/structural growth lists are empty. Six prior native method ASTs already differ from the f404 checkpoint because I01 adopted canonical records/paths; current119 hashes are frozen rather than falsely demanding old aliases. All other prior proof method ASTs remain identical. The projection contains no new production loop/branch/algorithm/cast. Original POSIX bodies total331/505 and metadata56/91; the largest moved function is53 physical or64 structural. Independent review and the unchanged strict gate must confirm actual final debt, imports/cycles and function limits; projection measurements are not a claimed gate pass.

## Native and conversion proof

The refreshed native inventory binds40 existing methods and16 actual source/policy inputs. Keep all14 actual Windows methods plus the scale method, all seven exact-Godot cases, modeled mount cases, and the separate existing generic Linux bind gate. None is substituted by N01 receipt tests or artifact-mode tests, which have different production owners.

Root should accept the finite native command design in `I02-native-invocation-proposal.md`: use existing public load_suite/result_is_allowed primitives and unittest, with exact individual IDs, literal counts, origin/interpreter binding and automatic zero-skip failure. No new runner file, kind or manifest schema. Native Linux and macOS each require the exact23-method POSIX/metadata cohort (3 moved +7 retained FD/namespace +3 real durability +10 new). Native Linux additionally runs the unchanged actual Included Files bind method under the already verified venv interpreter through sudo; require exactly1 test/0skips. Preserve the generic Linux gate separately. Add the three new metadata cases to the existing native Windows command and verify all three run without skips alongside retained14+scale1. Do not change the bind method's skip/cleanup policy merely to invoke it with privilege. Missing privilege/tools/capability is a failing required native command, never substituted evidence.

Freeze and negatively characterize the bounded native invocations before source integration: missing/deleted ID, injected skip, foreign module origin and wrong cwd/prefix must fail. The real Linux bind case is mandatory on native CI; this macOS planning run provides no privilege proof. The three durability methods really call fsync through observation and must execute on native macOS. Passing their syscall/order assertions is not proof of behavior after arbitrary hardware power loss.

After source freeze, reserve the root CPU window for the full approved Python/Godot/all-five-project suite and finite public Included Files parity. Reuse the established ten I01 public convert_all inputs, preserve all seven comparison fields, add exact public-file modes as an explicit additional field, compare119→candidate and same-ref control. Normalize only previously accepted explicit root/path nondeterminism; never drop artifact bytes, digests, counts, diagnostics or modes. Bind all source/input/environment hashes and actual module origins. No extra conversion matrix or new runtime runner is proposed. Record bounded paired elapsed/RSS evidence for the same workload if making a cost claim; no speedup is claimed by this plan.

Run focused tests after typing/lint fixes, `./venv/bin/pyright --warnings` (0errors/0warnings), project/tracked Ruff, actionlint for the exact workflow, the relevant existing CI workflow tests, strict maintainability gate against the immutable accepted parent, and git diff --check. Preserve all212 existing IDs with three exact moves and10 additions, giving222 in the Included Files cohort. Record actual full-suite count and all skips; do not infer native success from a successful local full suite.

## Exact allowed files and root integration

Seven implementer-owned paths:

1. src/conversion/included_files.py — only21 definition/constant moves, canonical imports/references, and newly unused import removal.
2. src/conversion/included_files_parts/posix_operations.py — new canonical16-function owner and flags.
3. src/conversion/included_files_parts/filesystem_metadata.py — new canonicalfive-function owner.
4. tests/test_included_files.py — exact three moves and required canonical call/patch/local-name migrations; all unrelated assertions unchanged.
5. tests/included_files/test_posix_operations.py — three moved +seven new finite tests and cohesive fixture.
6. tests/included_files/test_filesystem_metadata.py — three new finite metadata tests.
7. .github/workflows/tests.yml — only accepted finite POSIX/bind commands and new metadata module in existing Windows command, preserving pins/runtime/native coverage.

Root-only serialized metadata paths: maintainability-baseline.json (genuine reductions only), coverage-policy.json (new owner coverage mapping, unchanged floors), architecture-verification.json (only necessary exact source/test ownership inventories; no new kind/N01 change), docs/architecture-campaign/I02-posix-contract.md, contracts.json and LEDGER.md. These are not implementer edits. Keep both package initializers unchanged. No version/release/notes, unrelated tests, source corpus payload, CLI, GML, JSON/resource owner or transaction behavior fix is allowed.

Completion requires independent actual-code APPROVE, root code APPROVE, immutable local receipts and unchanged reviewed hashes, root-authorized source commit/integration, strict combined checks, exact required PR and merge CI/native receipts and root verification. A local commit or broad full-suite success is not completion. Temporary-adapter removal condition: no repository adapter is introduced; all21 private old definitions disappear immediately and only external frozen before-production characterization translation remains as evidence.

Planning preflight history: the first external constant-span projection accidentally removed the adjacent Windows constant; configured Ruff rejected it. No repository source was edited. The failed draft/log are preserved under projection-preflight-failed. The corrected final projection passes configured Ruff and now checks every retained non-import module AST node, all21 moved bodies and the exact directory-flag expression, so the corrected facade figure above is authoritative.


# I02 entry refresh at verified G01 merge 7fdd97c

This separate, read-only appendix supplements the original 26-artifact proposal at `1196295179296dfc12274ff39ba79e6adfb4a1b2`. It does not modify that archive or authorize implementation. Root acceptance and an isolated worktree assignment remain necessary. The proposed implementation entry is `7fdd97cfb0149bb166175fd5479b5193f3d64423`.

`entry-confirmation.json` and its read-only checker bind 20 inputs: 18 are byte-identical to 119, including all production/test inputs, workflow, runner, coverage policy and I01 leaf tests. The only changed inputs are architecture-verification.json (the G01 gate is added; all six earlier gates are unchanged) and maintainability-baseline.json (1056 to 1055 keys, one GML parameter debt deletion, six lowered GML allowances and three GML size-evidence changes). The policy and I02 debt are unchanged. No source semantic or import-layout change affects this proposal.

All 212 existing Included Files IDs are recollected from source ASTs, not by executing unittest. All 40 native/proof method ASTs match the original 119 inventory. The exact 63 retained production callers, 56 qualified test consumers, 51 direct consuming methods, 46 patch sites and 34 capability patches carry forward unchanged. The four proposed new owner paths remain absent. All 26 original artifact hashes match their immutable index. No production, tests, native operations, type checker or benchmark ran during this entry refresh.

The final hash/AST check uses the approved Python 3.12.10 interpreter, matching the original inventory. A preliminary rerun with system Python 3.14.7 failed because AST serialization differs; its unpublished index and factual limitation are preserved under preflight-host-python-mismatch. The checker now rejects a different interpreter explicitly. That failed attempt supplies no proof credit.

The initial source receipt deliberately did not credit then-pending CI. Root subsequently verified G01 at this exact merge: G01/final-verification.json SHA `f49b48d8b976f35dcbe7f8299af56f841f56d541b52dd8e2053b8b4e4c812f9b`, bound to PR CI 33951220652 and merge CI 33952438794. The separate independent status receipt, L01/implementation/G01-independent-verified-status-review.json SHA `876e1f5fd0629adb20d73ce704be03ac56a897370806c8be3b96d1b8a61d2b64`, verifies the 17 proof hashes, both exact 49-method zero-skip gates, native receipts/mode proof and actual parent. This appendix references that verified evidence; it does not claim a new CI run. Campaign progress at that checkpoint is 11/54, 20.4%.

## Import layout and metric entry clarification

The original projection metrics and all binding ASTs remain the semantic reference: facade 11552/16077 to 11140/15473 physical/structural, POSIX preview 383/525, metadata 80/97, old test owner 12420/21674 to 12295/21384, and the three moved tests plus fixture 164/278. Every retained function has zero physical/structural growth. The new destination and function limits remain exactly those in the final proposal; no allowance is added.

The POSIX preview contains an extra blank separator between filesystem_metadata and models imports caused by classification in its temporary directory. Actual implementation must run the accepted global I settings with both new leaves physically present beside the existing models module. Preserve exactly the projected imported bindings and definition ASTs; report the resulting physical size. Do not retain an artificial blank solely to match 383 or claim the cosmetic correction as structural decomposition. The 525 structural reference and fixed budgets remain unchanged. Final actual import/metric/debt verification is mandatory.

## Windows exact-three refinement accepted by root

Replace the original proposal's ordinary append of the metadata test module to the Windows unittest command with one explicit three-ID, zero-skip command. Preserve the existing Windows transaction command, its 14 native cases and the separate scale case unchanged. The new command goes before the existing output-reader scheduling step, preserving that step's existing workflow-test boundary. This is still only the originally allowed `.github/workflows/tests.yml`; the seven implementer paths and six root-only metadata paths do not change.

The literal proposed Python body is `native_windows_metadata_invocation.py`, a review artifact rather than a repository runner. In the existing Windows job, use `shell: bash`, select the existing verified venv executable with `venv_python="$(cygpath -u "$VIRTUAL_ENV")/Scripts/python.exe"`, then invoke `"$venv_python" - "$GITHUB_WORKSPACE" "$VIRTUAL_ENV"` with a single-quoted heredoc. Existing dependency setup stores VIRTUAL_ENV as a native Windows path, so cygpath is used only to select that same executable from bash. Python checks cwd, prefix, executable, version 3.12.10, win32 and AMD64 before collection.

Use only the existing public `load_suite` and `result_is_allowed` functions and standard unittest. Freeze all three exact individual IDs, require literal length 3, `discovered == ids`, testsRun 3 and `result_is_allowed(result, {})`. Check the actual loader/checker, facade, canonical lower functions and selected test-class origins before and after execution. The latter rejects every skip, error, failure, expected failure and unexpected success. The retained log record includes the actual interpreter, source origins, selected IDs, testsRun and skip count; root binds it to each exact PR/merge commit. A plain successful process without this exact record is insufficient.

Before implementation integration, characterize this exact invocation externally: the intact three-ID collection is accepted; missing/deleted ID rejects before execution; one induced skip has testsRun 3 but exits nonzero; actual foreign-checkout module origin rejects; wrong prefix rejects. Also preserve the existing wrong-cwd/host/executable fail-closed checks. Any host adapter used to inspect collection on macOS must be explicit and retained and supplies no Windows runtime credit. Run no real Windows or mount operation during planning. The actual native Windows command must pass exactly 3/3 with zero skips at both PR and merge revisions. Linux/macOS retain exact 23 each and Linux additionally exact 1 privileged bind case, using their previously proposed unchanged runner primitives. No runner, validation kind, schema, skip allowance or N01 member is added.

## Before-production observation coverage

The original 51 direct consuming method count is correct. Exact self-call inspection additionally finds 13 existing methods that reach those patch/call sites through retained helpers. `patch-observation-sites.json` freezes all 64 observation IDs, the original 46 sites and the 11 returned-context/selected-patcher scopes needed to delimit them. All 64 are already among the unchanged 212; this is an accurate execution inventory, not 13 new scenarios. See the adjacent observation plan for the limited source/real-delegation proof and its limitations.

The accepted final cohort remains 212 current methods, exactly three moves and ten new characterizations, yielding 222. All retained assertions, payloads, native/model distinctions, ownership transfers and error behavior stay fixed. The proposed seven owner files, root-only metadata separation, direct canonical bindings, finite APIs, no-growth limits, actual privileged Included Files case, real macOS fsync proof and #877 I07/I10 exclusion are unchanged. A discovered ambiguous patch edge requires a precise reviewed correction before production edits; no blanket duplicate patches, private facade or live-forwarding compatibility layer is permitted.


## Root acceptance and isolated assignment

The historical proposal and entry appendix above are now accepted following
independent and root substantive review. Implementation owner audit_transactions_cli
uses this isolated branch `dev/080-included-posix` at actual verified entry
`7fdd97cfb0149bb166175fd5479b5193f3d64423`. The seven source/test/workflow paths and
six root-only metadata paths remain exactly as listed. Root retains commit,
integration, baseline, coverage, verification and final release ownership.

The original 26-artifact index is `75b64d7feac63467466f9f37a65c28cea007da63810569a1c5573d237f80cd85`;
the nine-artifact entry index is `304c7389756c0bd0163ca3a31d21c625b1c9a330c8bfcb4bdeaa4ce49e57ad18`.
Independent final entry approval: `a7690a46cec99e08f8edf58522c25e13a7d27113c3e11ea44a2624b05434e7c8`.
Root acceptance: `55a68c299705ef053f4558f8760054710afcd4fda92a2d8b15f1cc6354963d6a`.

The explicit Windows exact-three invocation supersedes the original ordinary
metadata-module append. The final matched comparison uses the same ten I01 inputs
and eight public fields at actual `7fdd97c` to the candidate, followed by same-ref
control. The 119 archive remains intact; no scenario or normalization is added.

Before production extraction, freeze and review the finite observer, execute the
64 existing cases with their real delegation/patch boundaries, and characterize
all ten new tests against the immutable original functions. Ambiguous actual
lookup edges require a reviewed correction before moving production. Native
23/23 Linux and macOS, the one privileged Included Files Linux bind case and
three exact Windows metadata cases must pass without skips at both PR and merge
revisions. Existing Windows14, scale, seven Godot and generic bind proof remain.

This assignment begins implementation and supplies no completed runtime proof
or task-verification credit. T01's independent test-helper migration will be
reconciled from its actual verified parent during serial integration.


## Accepted pre-extraction evidence and four-site refinement

The reviewed observer and ten new characterization tests have executed on unchanged
source at `abd97e414544513111b9e447aeb2356f0d34b337`, whose 384 Python files
still match the accepted entry. The observer selected all 64 existing IDs: 63
passed on native macOS Python 3.12.10 and the existing Linux-only bind method skipped
with exactly `Native Linux bind mounts are unavailable`. Its first host guard
prevents old-source native profiling on this Mac. That method has no moved-function
patch; its unchanged shared os.path.ismount patch and native assertions were reviewed.
Old privileged-Linux profiler edges and counts remain explicitly unavailable.
The required privileged Linux one-ID command still must pass with zero skips on
both PR and merge; static review and local models do not replace that evidence.

All 59 expected per-test patch lifetimes were entered and had positive calls to
their own target, with no missing or unexpected lifetimes. The raw receipt retains
5,844 rows and 209,253 calls, including real delegates and 301 unmapped Mock rows.
Source-span review found no moved-function call among those unmapped rows. The ten
new tests passed 10/10 with zero skips against the real old functions and exact
reviewed import/patch-target translation. Those tests prove native macOS behavior
plus their explicitly declared parser, metadata and capability models. Initial
29/32-file observer/template attempts and their corrected findings remain preserved.

Actual active calls establish 40 facade-only patch sites, two POSIX-only sites and
four sites needing both lookup owners. Only those four descriptor capability sites
change from the earlier single-binding projection: streaming cleanup, nested mount,
deep tree scale and deep ancestor swap. Each first patch targets
`src.conversion.included_files.descriptor_paths_supported` and binds its original
configured Mock as descriptor_capability. The immediately following patch installs
that same object at
`src.conversion.included_files_parts.posix_operations.descriptor_paths_supported`.
The existing Boolean, with lifetime, shared call history and reverse restoration
remain intact. The other 42 sites and all 826 retained assertion ASTs stay unchanged.

The four functions have physical/structural sizes 76/117, 80/137, 81/97 and 82/143.
Their structural sizes match the accepted projection and physical sizes grow only
three lines each, remaining below 200. The retained test module becomes
12,307/21,384, below entry 12,420/21,674. The final POSIX test template is 424/1,129;
the metadata template is 76/249. No helper, adapter, new allowance or suppression
is introduced by this refinement. Final candidate typing, global import layout,
strict actual-parent debt and all focused/full/native checks remain required.

Before the post-extraction observer runs, freeze and review its exact three-source
call map and four paired-site projection. Map each pair to one original consuming
lifetime without counting a call twice; retain exact per-test/variant/caller counts.
The four True lower-call totals must remain 6/1/8/1, with zero lower calls in every
False variant. Preserve real delegation and both actual lookup owners. The deep
ancestor test patches os.listdir, so the lower forced-True selector is necessary
to reach its native race. Only accepted owner/test moves and the existing local
Boolean rename may otherwise be normalized.

Accepted corrected pre-use index: `e75dd9bb52dbc5f4a9be350fdc3ecb3cbc4a97416b062b801dbc177564ef8e39`.
Raw binding index: `0270689262b0174d7cf5133011a3ae7b2d40b401c297590c62ab8b8fa43784f9`.
Ten-test receipt: `a34ae01baa78d980cab33e2f82bf8add2eba24c87aa8632e97964b59dbd588b6`.
Independent/root data approvals: `8ffdbfe937ecc591d233ad43df639bab1bd2bc1bbc6c7dfcb291493179787c5a` /
`e46f82b7b8d6e521c1b66dd89e064dbc387ee35fd23fe1480e50e7cb1f36f1f7`.
Four-site index: `ea60cfb5293edd91fc731b007cf13cdb4a4c5ce8e3922a5a721103f2036ba025`.
Independent/root four-site approvals: `c6e7c651b1fb1994976a3ec60b949407c504c88c482ec5c8e634f64c42436956` /
`629479528286c281d6a0adeaf506622e6f49ace26ab75a28c352ec03438ff75a`.

This completes the amended before-production prerequisite. The same seven owner
paths and six root-only metadata paths remain. Native Linux/macOS 23 each,
privileged Included Files Linux 1, Windows metadata 3, retained Windows 14 plus
scale, seven Godot cases and the separate generic bind gate are unchanged. No
production implementation, native CI or I02 task verification is claimed here.


## Original proof accepted and current-parent preparation

Immutable implementation `95831c08f0e230da0baa8822d80411b532cb75bf` has
independent and root actual-code approval. Its full suite ran 3,120 tests with
3,064 successes and the 56 exact existing host skips; all five required real
project methods passed with the required exact Godot. Public parity is exact
across ten cases and eight fields against actual old7fdd and a same-ref control,
including public bytes and modes. These executions remain attributed to958.

The approved call comparison preserves all5,844 raw rows and209,253 calls,
including301 originally unmapped rows and the four dual mock bindings. Its
64 selected cases have63 actual Mac successes and the one exact old privileged
Linux skip; no old native Linux profiler evidence is invented. The full44
invocation-control set passed as20 preservedv2 and24newv3 cases. The failed
foreign-test import is retained without credit; a byte-identical candidate test
file at the foreign path supplies the intended origin rejection. Controls are
not positive native Linux/Windows proof.

The accepted next parent is verified R12 merge
`b9c05cd326cbcb8531ca93c24709bcf14cb81748`. All six I02 Python owners remain
exact958; the389 other parent Python files are exactb9, giving395 total. The
workflow retains the complete approved I02 body and adds only the two already
verified T01 helper entries. Parent coverage and all eight gate objects remain
byte-exact; no schema, floor, exclusion or new runner is introduced.

Root resolves the ledger and task evidence, and checks the seven permitted
baseline reductions against actualb9, retaining1045 debt keys. The existing
checker requires its comparison parent to be a HEAD ancestor, so a prepared
merge commit may establish that ancestry before the exact-parent update/check.
This preparation is not final approval or campaign integration. Source/workflow
bytes must match the reviewed projection before and after all combined checks.

Combined checks are zero-diagnostic Pyright, project/tracked Ruff, actionlint,
the strict actual-parent gate, diff checks, and the83 existing CI workflow and
aggregate cases after lint/type fixes. Original full/parity/observer/controls
are retained with their original references. Actual PR and merge CI supply the
new combined full/native proof: Linux23, Mac23, privilegedLinux1 and Windows
metadata3 must run with zero skips, together with every retained native, CLI,
T01/R12, exact-Godot and receipt requirement. Root and independent review must
accept the resulting exact revision before counting I02 as verified.

Current-parent proposal index:
`a625bc04ad990c8aab70fa4d2837bba54238df955b1696c0140a19afd37943b1`;
independent review:
`200e426410a02c30e297360e0b1a30100cc74b769151068d7007311f5b7eb36b`;
root review:
`665409b2da6e36ee1031262adecdb950384c427aa546c52a57c8aea537a7db1f`.
