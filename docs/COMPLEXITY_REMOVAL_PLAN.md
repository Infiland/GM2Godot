# Function complexity removal plan

These source-reviewed boundaries describe how to remove existing complexity without changing behavior. The required C90 gate fixes the threshold at 15. Each of the 116 named tasks below corresponds to an individually reviewed existing function in `complexity-exceptions.json`; its measured score is also its ceiling. New or increased debt fails. Improvements must tighten both measured score and ceiling, and functions reduced to 15 or removed require deleting their exceptions and completed tasks. The policy and these removal boundaries fulfill the complexity baseline in [issue #795](https://github.com/Infiland/GM2Godot/issues/795).

<a id="fn-a68fc18d29d2bd3f"></a>

## `scripts/_anchored_output.py::OutputParentBinding.close`

Close output-parent descriptors/handles child first.

Preserve: Two-attempt budgets, ordered failures and early retention of live children and their ancestors must survive; legacy integer resources have different contracts.

Removal: Extract separate POSIX and Windows bounded lease-close loops and closed-state calculation.

Existing checks: `tests.test_anchored_receipt_outer_lease.AnchoredReceiptOuterLeaseTests.test_binding_keeps_parent_open_when_child_exhausts_cleanup`, `tests.test_anchored_receipt_posix_failures.AnchoredReceiptPosixFailureTests.test_binding_retries_helper_boundary_before_moving_to_parent`

<a id="fn-5d5cbe7b02e5e1db"></a>

## `scripts/_anchored_output.py::OutputParentBinding.verify`

Revalidate namespace/identity/mode under POSIX or Windows bindings.

Preserve: Receipt-mode error translation, intermediate deny-only ACLs/private indexes, and legacy exception behavior cannot be conflated.

Removal: Split strategy-specific receipt-policy validation from legacy verification.

Existing checks: `tests.test_anchored_receipt_ancestor.AnchoredReceiptAncestorTests.test_bound_intermediate_becoming_world_writable_is_rejected`, `tests.test_anchored_receipt_darwin.AnchoredReceiptDarwinTests.test_native_deny_only_intermediate_supports_publish_and_idempotency`

<a id="fn-53d562b352a84365"></a>

## `scripts/_anchored_output.py::_OutputParentBindingLeaseState.close`

Close retained publication resources before the parent binding.

Preserve: Do not close the parent while a newer resource remains live; preserve status-inspection failures and first/secondary exception order.

Removal: Extract publication-resource close and binding-close routines with explicit closed results.

Existing checks: `tests.test_anchored_receipt_outer_lease.AnchoredReceiptOuterLeaseTests.test_outer_lease_keeps_older_resources_and_parent_open_until_newest_closes`, `tests.test_anchored_receipt_outer_lease.AnchoredReceiptOuterLeaseTests.test_public_finalizer_recovers_when_outer_cleanup_call_is_interrupted`

<a id="fn-4822416ebb5b3299"></a>

## `scripts/_anchored_output.py::_darwin_descriptor_has_extended_acl`

Query/validate native Darwin ACLs and retire the captured pointer.

Preserve: No double free after an interrupted native return; preserve errno, deny-only intermediates, rejection of empty non-null ACLs and cleanup-note priority.

Removal: Split descriptor/structural ACL validation from bounded deny-entry enumeration; leave native result recording/free in the owner.

Existing checks: `tests.test_anchored_receipt_darwin.AnchoredReceiptDarwinTests.test_modeled_acl_enumeration_interrupt_frees_allocation_once`, `tests.test_anchored_receipt_darwin.AnchoredReceiptDarwinTests.test_modeled_acl_structural_validation_failure_is_rejected`

<a id="fn-53a3c684261ae99e"></a>

## `scripts/_anchored_output.py::_open_rooted_posix_parent`

Create/open rooted POSIX parents with preregistered ownership.

Preserve: Preserve pre-native owner slots, missing-directory race rejection, private modes/ACL checks and parent fsync even for existing ancestors.

Removal: Extract one component acquisition/sealing step while keeping the outer installed lease authoritative.

Existing checks: `tests.test_anchored_receipt_ancestor.AnchoredReceiptAncestorTests.test_preinstalled_owner_recovers_root_child_and_verification_interrupts`, `tests.test_anchored_receipt_ancestor.AnchoredReceiptAncestorTests.test_existing_ancestor_retries_containing_directory_sync`

<a id="fn-7f5e194fbc41eef2"></a>

## `scripts/_anchored_output.py::_publish_windows_receipt_bytes`

Coordinate retained-handle Windows receipt publication and observation.

Preserve: Unknown/published rename outcomes preserve public names; authenticated collision provenance, winner verification and live-child parent retention remain distinct.

Removal: Extract exact observation/error translation, collision handling and resource finalization as finite operations.

Existing checks: `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_trace_boundaries_never_dispose_unknown_or_published_rename`, `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_cleanup_and_definite_rename_evidence_rejects_spoofed_attributes`

<a id="fn-c1088b29259921b5"></a>

## `scripts/_anchored_output.py::_read_exact_receipt`

Read and verify exact bounded receipt bytes against retained identity.

Preserve: Keep len(payload)+1 bounds, one-link/mode/ACL checks, namespace drift codes, primary exception identity and two-attempt close priority.

Removal: Extract byte/metadata comparison and descriptor-close resolution.

Existing checks: `tests.test_anchored_receipt_posix_failures.AnchoredReceiptPosixFailureTests.test_retained_validation_rejects_bounded_read_and_metadata_drift`, `tests.test_anchored_receipt_posix_failures.AnchoredReceiptPosixFailureTests.test_receipt_reader_retries_cleanup_helper_boundary_without_leaking`

<a id="fn-ec5aba11e237fb9c"></a>

## `scripts/_anchored_output.py::_rooted_output_parts`

Canonicalize rooted output components without resolving replaceable descendants.

Preserve: Only trusted /tmp and /var aliases resolve; Windows devices/ADS and lexical escape reject before resource acquisition.

Removal: Extract trusted Darwin root-alias handling and Windows root/component validation.

Existing checks: `tests.test_anchored_receipt_ancestor.AnchoredReceiptAncestorTests.test_unsafe_final_or_creation_parent_is_rejected_without_mutation`

<a id="fn-e0626db692b4259f"></a>

## `scripts/_anchored_output.py::open_output_parent`

Acquire verified output-parent anchors with cleanup on partial acquisition.

Preserve: No-follow checks, final binding verification and control-flow exception identity/cleanup notes must occur at the original stages.

Removal: Extract POSIX and Windows acquisition branches after the existing path normalization.

Existing checks: `tests.test_anchored_receipt_ancestor.AnchoredReceiptAncestorTests.test_open_and_final_verification_failures_close_every_acquired_descriptor`, `tests.test_anchored_receipt_ancestor.AnchoredReceiptAncestorTests.test_replacement_between_stat_and_open_is_rejected_untouched`

<a id="fn-56e2c9574e4f9267"></a>

## `scripts/_anchored_output.py::publish_new_bytes`

Publish new snapshot bytes by private temporary link with no overwrite.

Preserve: Uncertain temporary identity must never be unlinked by name; retain no-replace link semantics, fsync order and control-flow failures.

Removal: Extract rejected-publication cleanup and successful-anchor-close error selection.

Existing checks: `tests.test_anchored_receipt_posix_failures.AnchoredReceiptPosixFailureTests.test_collision_observes_exact_winner_and_never_unlinks_public_name`

<a id="fn-d4a670474d49a4b7"></a>

## `scripts/_anchored_receipt_posix.py::_PosixReceiptPublicationLease.close`

Close POSIX receipt verification/stage/private-directory resources.

Preserve: Global four-attempt stage/sync budgets, two-attempt close budgets and early ancestor retention cannot reset during retries.

Removal: Extract descriptor closure plus named-stage and private-directory durability retry phases.

Existing checks: `tests.test_anchored_receipt_outer_lease.AnchoredReceiptOuterLeaseTests.test_posix_publication_lease_keeps_older_descriptors_open_until_newest_closes`, `tests.test_anchored_receipt_darwin.AnchoredReceiptDarwinTests.test_publication_cleanup_does_not_exceed_seeded_private_sync_budget`

<a id="fn-cd21a8f01c85f9aa"></a>

## `scripts/_anchored_receipt_posix.py::_open_darwin_receipt_stage`

Allocate/seal one Darwin private staging root and named inode.

Preserve: Register native ownership before interruption; reject substituted roots/stages, preserve bounded identity cleanup and leave unprovable entries untouched.

Removal: Extract root creation/sealing, named-inode validation and failure cleanup.

Existing checks: `tests.test_anchored_receipt_darwin.AnchoredReceiptDarwinTests.test_inner_stage_swap_is_rejected_without_publication_or_unsafe_cleanup`, `tests.test_anchored_receipt_darwin.AnchoredReceiptDarwinTests.test_failed_stage_keeps_private_parent_when_stage_close_is_exhausted`

<a id="fn-fd91d14bb19af5a7"></a>

## `scripts/_anchored_receipt_posix.py::_publish_posix_receipt_bytes`

Publish an exact POSIX receipt, recover uncertain effects and finalize leases.

Preserve: Never roll back an uncertain public receipt; keep collision idempotency, exact identity observation, flush ordering and control-flow cleanup precedence.

Removal: Extract attempted-publication recovery/durability steps and lease finalization.

Existing checks: `tests.test_anchored_receipt_posix_failures.AnchoredReceiptPosixFailureTests.test_effect_then_control_flow_still_runs_durability_pipeline`, `tests.test_anchored_receipt_posix_failures.AnchoredReceiptPosixFailureTests.test_successful_collision_promotes_control_flow_close_failure`

<a id="fn-5915dcaca902e60a"></a>

## `scripts/_anchored_receipt_windows.py::close_windows_handle_lease`

Close a Windows handle while retaining native close evidence.

Preserve: Never retry an unrecorded ambiguous CloseHandle; replay recorded evidence rather than the native call, with bounded attempts and stable primary notes.

Removal: Extract result interpretation and lease retirement from native address/call capture.

Existing checks: `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_close_call_return_gap_preserves_active_primary`, `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_cleanup_failures_preserve_primary_and_order_notes`

<a id="fn-ac227344f9d41771"></a>

## `scripts/_anchored_receipt_windows.py::publish_windows_receipt`

Create, verify and rename a Windows receipt with publication phases.

Preserve: Set unknown before native rename and published only after return; dispose only definitely staged handles and attach actual outcome evidence on interruptions.

Removal: Extract candidate write/read verification and primary/cleanup resolution.

Existing checks: `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_definite_negative_rename_disposes_but_raised_rename_is_unknown`, `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_nonfinal_return_and_nonzero_completion_keep_unknown_outcome`

<a id="fn-9af0279f0cb35772"></a>

## `scripts/_anchored_receipt_windows.py::read_windows_receipt`

Read canonical receipt bytes through a retained relative Windows handle.

Preserve: Pre-acquisition missing differs from post-acquisition disappearance; whole payload bounds, retained lease and exact close errors remain authoritative.

Removal: Extract metadata/byte validation and phase-aware OSError translation.

Existing checks: `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_write_loops_and_read_requires_exact_eof`, `tests.test_anchored_receipt_windows.WindowsAnchoredReceiptTests.test_post_rename_exact_read_and_metadata_drift_are_detected_without_disposition`

<a id="fn-7af085f0a4d2dd4f"></a>

## `scripts/build_dependency_snapshot.py::verify_receipt`

Binds successful environment receipt to the exact constraint, installed set, native tuple, authored bootstrap and successful pip commands.

Preserve: A self-consistent but foreign receipt can otherwise be accepted. Exact int/bool distinctions, first mismatch code, source/constraint path and hash checks must retain their current order.

Removal: Extract ordered constraint/installed/runtime, bootstrap-transition, then command-result validators. Each takes the existing typed policies, and bootstrap checks keep stable/source-transition projections separate. The top-level function retains stage order.

Existing checks: `tests/test_dependency_snapshot.py::DependencySnapshotTests.test_receipt_lock_installed_source_and_tuple_bindings_fail_closed`; `tests/test_dependency_snapshot.py::DependencySnapshotTests.test_each_platform_label_rejects_self_consistent_wrong_native_tuple`.

<a id="fn-00e44d06699cbff2"></a>

## `scripts/capture_conversion_parity.py::validate_runtime_markers`

Independently authenticates runtime marker schema, exact warning sequence, raw ANSI output, stages and ordered boot operations.

Preserve: Declared resource-fixture warnings intentionally retain failed status while accepting zero import/boot codes; default-empty policy cannot be silently widened. Three output scans must agree, including duplicates/order.

Removal: Small first extraction: one exact ANSI-stripped issue parser shared by output and boot_output. Then isolate schema/stage validation from warning-policy comparison; keep operations extraction from boot_output and status checks last.

Existing checks: `tests/test_capture_conversion_parity.py::TestCaptureConversionParity.test_warning_probe_rejects_missing_extra_reordered_errors_and_nonzero_stages`; `tests/test_capture_conversion_parity.py::TestCaptureConversionParity.test_runtime_defaults_reject_undeclared_warnings_and_optional_import_mismatch`.

<a id="fn-8e28695267bffed7"></a>

## `scripts/conversion_parity_snapshot.py::_validate_journal_rows`

Checks journal directory receipts, sorted transition policy, backup bytes/identities and complete previous/desired inventories.

Preserve: An evidence transition must not become managed, and previous-public/backup/desired-stage identities are distinct. Validation order, sorted transition keys and exact backup set are part of rejection behavior.

Removal: Extract directory-row validation and a single transition-row validator returning its kind/path/backup contribution. Keep ordered aggregation, uniqueness and whole-inventory equality in the caller.

Existing checks: `tests/test_conversion_parity_snapshot.py::TestConversionParitySnapshot.test_journal_stable_paths_backups_and_native_directory_modes_are_bound`; `tests/test_conversion_parity_snapshot.py::TestConversionParitySnapshot.test_evidence_transition_cannot_be_reclassified_as_managed`.

<a id="fn-38b99f490df87409"></a>

## `scripts/conversion_parity_snapshot.py::_validated_publication`

Authenticates publication marker/pointer/journal/generation provenance and actual public bytes/modes before normalizing volatile IDs.

Preserve: Normalizing before digest, native identity, evidence inventory and backup proof checks could conceal a changed publication. Transaction lock bytes/modes and stable paths must remain visible.

Removal: Split exact record/provenance authentication, generation/public inventory joins, and final normalization. Pass only authenticated existing records into normalization; retain exact observed/public record inventories and rechecks.

Existing checks: `tests/test_conversion_parity_snapshot.py::TestConversionParitySnapshot.test_only_authenticated_ids_and_bound_digests_are_normalized`; `tests/test_conversion_parity_snapshot.py::TestConversionParitySnapshot.test_pointer_digest_name_identity_and_byte_receipts_are_authenticated`.

<a id="fn-db2a5c54f398b025"></a>

## `scripts/propose_native_wheels.py::_observe_wheel`

Seals a retained native wheel, parses safe ZIP metadata and joins filename/version/native tags to METADATA/WHEEL.

Preserve: Archive aliases, special/encrypted members, duplicate metadata roots and incompatible tags must fail before acceptance. Streaming hash and post-read descriptor/name seals must remain outside parsing helpers.

Removal: Extract ZIP namespace/member policy, then exact metadata-pair/tag identity validation on the already-open archive. Keep opening, bounded full hashing, seek, and before/after file checks with the current descriptor owner.

Existing checks: `tests/test_native_wheel_proposals.py::TestNativeWheelProposals.test_real_wheel_fixture_requires_metadata_directory_and_native_tag_agreement`; `tests/test_native_wheel_proposals.py::TestNativeWheelProposals.test_real_wheel_fixture_rejects_duplicates_traversal_and_modified_bytes`.

<a id="fn-48a6a7e98dfaf044"></a>

## `scripts/propose_native_wheels.py::produce`

Runs native source binding, two independent wheel downloads, self-hosting, fresh offline installs and final artifact sealing.

Preserve: Native preflight precedes source/venv work; current/candidate/fresh environments, caches and wheelhouses must remain distinct. Nested closures capture one Journal/publisher and phase order; partial journal failure must note the primary error.

Removal: Extract the double-download/observation comparison and final wheelhouse/reference sealing as named stages. Move environment/compile/preflight operations into a finite typed producer owner retaining one Journal and exact command order, then keep orchestration thin.

Existing checks: `tests/test_native_wheel_proposals.py::TestNativeWheelProposals.test_native_mismatch_precedes_source_reads_or_environment_creation`; `tests/test_native_wheel_proposal_validation.py::TestNativeWheelProposalValidation.test_distinct_environment_wheelhouse_cache_and_monotonic_command_proofs_reject`.

<a id="fn-14bf1394f2b66e0e"></a>

## `scripts/propose_native_wheels.py::run_command`

Owns a guardian subprocess, bounded output/readiness, deadline, kill/reap and retained command evidence.

Preserve: Readiness is a directory published after successful result publication; early result reads or reaping before final group signaling risk forged completion/PGID reuse. Control-flow exceptions and cleanup/capture notes retain precedence.

Removal: Separate readiness/output/deadline observation from cleanup of the same unreaped process. A cleanup helper returns ordered errors after group kill, wait, stdin close and both captures; caller preserves original BaseException and notes.

Existing checks: `tests/test_native_wheel_proposals.py::TestNativeWheelProposals.test_actual_guardian_readiness_defers_result_reads_and_preserves_fatal_failures`; `tests/test_native_wheel_proposals.py::TestNativeWheelProposals.test_guardian_cleanup_reaps_after_signal_failure_and_preserves_control_identity`.

<a id="fn-70bb118e8ef8fc01"></a>

## `scripts/release_publisher.py::PublisherConfig.from_environment`

Builds main-only publisher config from canonical origins, exact event SHA/tag/name, safe workspace paths and bounded delays.

Preserve: Token retrieval and validation order must not expose credentials or permit PR refs/foreign URLs/path traversal. Preflight delay permits 0..10 while ownership delay permits 0..1, including current nonfinite rejection.

Removal: Small extraction: validate both named retry delays in one pure stage at their original position, or move only relative output-path validation. Retain required-value checks and main event identity checks before config construction.

Existing checks: `tests/test_release_publisher_recovery.py::TestPublisherConfiguration.test_accepts_only_main_branch_release_events_and_exact_sha`; `tests/test_release_publisher_recovery.py::TestPublisherConfiguration.test_requires_canonical_origins_relative_paths_and_fixed_name`.

<a id="fn-5807e3fcea299ed8"></a>

## `scripts/release_publisher.py::validate_release`

Validates owned GitHub release identity, exact URLs, draft/public state, timestamps and optional empty asset condition.

Preserve: A draft HTML segment differs intentionally from the published tag URL. Ownership ID, immutable/draft state and empty-asset check cannot be merged into permissive generic schema handling.

Removal: Small extraction: validate publication timestamps/immutable/asset state after existing ID/URL checks. Keep ReleaseIdentity construction and draft HTML handling in order. This is preferable to accepting a historical score-16 exception.

Existing checks: `tests/test_release_publisher.py::TestReleasePublisher.test_failures_are_terminal_without_retry_adoption_or_foreign_mutation`; `tests/test_release_publisher.py::TestReleasePublisher.test_visibility_retry_never_waits_out_nonempty_or_malformed_drift`.

<a id="fn-16431ca110b8484e"></a>

## `scripts/verify_dependency_environment.py::_bound_regular_files`

Holds a cohort of regular-file descriptors through all before/read/after/yield checks, then closes every descriptor in reverse order.

Preserve: Sequential reads cannot synthesize mixed generations. Append failure must close the untracked descriptor, caller interruption keeps its identity, and successful cleanup gives control-flow exceptions priority over ordinary close failures.

Removal: Extract reverse close collection and exact successful/primary-error resolution into narrow helpers. Keep acquisition, alias rejection, all-cohort checks and generator yield in one ownership scope; no new context controller.

Existing checks: `tests/test_dependency_policy.py::TestDependencyBootstrapPolicy.test_native_cohort_does_not_synthesize_sequential_file_generations`; `tests/test_dependency_policy.py::TestDependencyBootstrapPolicy.test_native_cohort_closes_every_descriptor_in_reverse_on_interrupt`; `tests/test_dependency_policy.py::TestDependencyBootstrapPolicy.test_successful_policy_read_preserves_control_flow_close_failure`.

<a id="fn-2ed948e01d6856e4"></a>

## `scripts/verify_dependency_environment.py::analyze_inspect_report`

Analyzes pip inspect metadata/environment, installed pins, required roots and complete/subset policy into deterministic findings.

Preserve: Malformed schema raises immediately while mismatches accumulate; duplicate normalized names preserve the first installed version. pip bootstrap checks differ from other pins, and metadata/direct URL locality rules cannot be weakened.

Removal: Extract installed-item analysis, pip bootstrap findings, and required/complete membership findings in their existing sequence; keep final sorted finding tuple and exact schema parsing unchanged.

Existing checks: `tests/test_dependency_policy.py::TestDependencyEnvironmentVerifier.test_duplicate_normalized_installed_names_are_rejected`; `tests/test_dependency_policy.py::TestDependencyEnvironmentVerifier.test_complete_mode_requires_lock_and_environment_equality`; `tests/test_dependency_policy.py::TestDependencyEnvironmentVerifier.test_non_pip_installer_and_direct_url_are_rejected`.

<a id="fn-7c67956d42edf500"></a>

## `scripts/verify_dependency_environment.py::main`

Orchestrates verifier path preflight, bootstrap policy, independent inspect/check commands and atomic success/failure receipt publication.

Preserve: Alias/policy failures occur before pip, pip check remains independent of inspect failure, and output failure returns 2 instead of verification failure 1. Failure receipts must still be written and preserve cleanup diagnostics.

Removal: Small extraction candidate: the final atomic receipt write/error reporting/status return stage contains two except branches plus one status branch. Move it intact into a named finisher; then remeasure before considering an exception.

Existing checks: `tests/test_dependency_policy.py::TestDependencyEnvironmentVerifier.test_constraint_output_aliases_are_rejected_before_pip_without_overwrite`; `tests/test_dependency_policy.py::TestDependencyEnvironmentVerifier.test_pip_check_failure_is_independent_and_terminal`; `tests/test_dependency_policy.py::TestDependencyEnvironmentVerifier.test_main_receipt_diagnostic_includes_stable_code_and_cleanup_notes`.

<a id="fn-f9103fe486050a52"></a>

## `scripts/verify_macos_bundle_metadata.py::_inspect_directory_inventory_at`

Owns inventory collections/root seal and invokes a nested descriptor-relative physical bundle walk.

Preserve: The nested visit is counted inside this owner as well as independently in the historical inventory; two independent waivers would hide one decomposition debt. Root identity and final link graph must remain checked.

Removal: Move the walker into a named private function with finite typed inventory state, keeping root pre/post seals and finalization here. Coordinate this task with the nested visit removal below rather than waive both.

Existing checks: `tests/test_macos_macho_inventory.py::TestRetainedBundleInputs.test_retained_app_root_replacement_is_rejected`; `tests/test_macos_macho_inventory.py::TestRetainedBundleInputs.test_close_preserves_primary_and_attempts_all_fds`.

<a id="fn-59906da18b85a286"></a>

## `scripts/verify_macos_bundle_metadata.py::_inspect_directory_inventory_at.visit`

Enumerates bounded sorted entries and inspects directories/files/symlinks with descriptor-relative anti-race checks.

Preserve: Count limit precedes sorted materialization, nofollow/nonblock prevent symlink/FIFO races, and every acquired descriptor is closed without masking the active error. Lexical aliases/link graph and cumulative entry count span recursion.

Removal: Extract child-directory recursion ownership, regular Mach-O leaf inspection and symlink inspection as three handlers returning actual inventory records. Keep one bounded shared count and original per-entry dispatch order.

Existing checks: `tests/test_macos_macho_inventory.py::TestRetainedBundleInputs.test_count_limit_precedes_sorted_materialization`; `tests/test_macos_macho_inventory.py::TestBundleInventory.test_non_regular_leaf_and_raced_fifo_fail_without_blocking`; `tests/test_macos_macho_inventory.py::TestBundleInventory.test_regular_file_mutation_during_macho_parse_is_rejected`.

<a id="fn-f555c76779efcc8a"></a>

## `scripts/verify_macos_bundle_metadata.py::_inspect_dmg_contents`

Copies/binds a DMG, attaches read-only, recovers exact device, inspects mounted app, detaches/confirms and cleans retained resources.

Preserve: Failed/timeout/malformed attach may still mount. Known device must be detached before safety is inferred; unconfirmed mount retains root. Active/primary/cleanup errors and notes have explicit precedence, and mounted descriptors close before detach.

Removal: Separate attach/device recovery, mounted inspection, and detach/confirmation/private cleanup around one finite state owner. Do not make a generic context manager that assumes failed attach means no mount or overwrites the active exception.

Existing checks: `tests/test_macos_bundle_metadata.py::MacOSBundleMetadataDmgTests.test_attach_command_error_still_recovers_partial_mount_and_detaches`; `tests/test_macos_bundle_metadata.py::MacOSBundleMetadataDmgTests.test_unknown_mount_after_failed_recovery_retains_root`; `tests/test_macos_bundle_metadata.py::MacOSBundleRetainedInputTests.test_mounted_descriptors_close_before_detach`.

<a id="fn-ef8426703b273959"></a>

## `scripts/verify_macos_bundle_metadata.py::_inspect_zip_inventory`

Validates ZIP namespace/type/ancestor graph, then streams symlinks and native files into a bundle inventory.

Preserve: Every archive path participates in duplicate detection while app-relative paths also get normalization/ancestor checks; explicit Unix type and encrypted members reject before payload reads. Link targets remain bounded UTF-8.

Removal: Extract namespace/app-member planning from planned payload inspection, preserving the existing full namespace pass before any stream reads. Return finite member/path/kind and available-path inventories, then finalize the same graph.

Existing checks: `tests/test_macos_macho_inventory.py::TestZipNativeGraph.test_archive_special_missing_modes_encryption_and_symlink_parents_are_rejected`; `tests/test_macos_macho_inventory.py::TestBundleInventory.test_zip_rejects_implicit_case_and_unicode_ancestor_aliases`.

<a id="fn-76cf62e0646615d7"></a>

## `scripts/verify_macos_bundle_metadata.py::_parse_macho_stream`

Parses bounded thin Mach-O headers/load commands and one macOS deployment requirement.

Preserve: Wrong CPU/subtype, fat/32-bit/byte-swapped files, malformed table sizes/alignment, non-macOS platforms and duplicate deployment commands must reject before claiming native compatibility. Preserve stream byte consumption and limits.

Removal: Split native header validation from bounded deployment-command decoding. A command decoder returns zero/one minimum versions per command; keep exact table offset/trailing bytes and exactly-one final policy in the caller.

Existing checks: `tests/test_macos_macho_inventory.py::TestMachOParser.test_truncated_and_structurally_invalid_tables_are_rejected`; `tests/test_macos_macho_inventory.py::TestMachOParser.test_missing_duplicate_wrong_platform_and_bad_tool_tables_are_rejected`.

<a id="fn-4231382ca6f9abfa"></a>

## `scripts/verify_macos_bundle_metadata.py::_remove_private_dmg_root`

Removes only the observed private DMG copy, mount directory and owned root, retaining ordered cleanup failures.

Preserve: Canonical paths, retained ancestry, owned mode/link count and physical mount identity must be rechecked. Copy and mount removal both run after one failure; root removal requires both successes, and first error/notes are stable.

Removal: Small wrapper split: standalone retained-owner acquisition delegates to a named owned cleanup operation; within it extract copy and mount removal helpers while retaining both attempts and ordered failure resolution.

Existing checks: `tests/test_macos_bundle_metadata.py::MacOSBundleMetadataDmgTests.test_private_cleanup_preserves_first_failure_and_orders_later_notes`; `tests/test_macos_bundle_metadata.py::MacOSBundleMetadataDmgTests.test_mount_and_root_rmdir_failures_report_removed_private_copy`.

<a id="fn-80f7e92c1b21371d"></a>

## `scripts/verify_macos_bundle_metadata.py::_select_zip_plist`

Selects one exact canonical Info.plist and rejects case/Unicode ancestor aliases and irregular leaf metadata.

Preserve: Unrelated members are intentionally ignored here while plist ancestor aliases and target duplicates reject. Generic full-app validation is a different policy and must not silently replace this selector.

Removal: Small extraction: final single-target regular/type/encryption/size checks into a plist-member validator. Leave canonical ancestor selection in place, preserving exact directory and unrelated-member behavior.

Existing checks: `tests/test_macos_bundle_metadata.py::MacOSBundleMetadataZipTests.test_explicit_ancestor_files_symlinks_and_aliases_are_rejected`; `tests/test_macos_bundle_metadata.py::MacOSBundleMetadataZipTests.test_exact_directory_ancestors_are_allowed_and_unrelated_members_are_ignored`.

<a id="fn-604676b916a1f2d0"></a>

## `scripts/verify_macos_gui_artifact.py::copy_zip`

Copies exact bound source ZIP bytes into an exclusively created private ZIP and independently rereads/seals them.

Preserve: Same-size substitution, growth/truncation, changed mode/link state or output identity must fail; both descriptors close in order and preserve a primary BaseException.

Removal: Small extraction candidate: private-copy full reread/digest/EOF validation, called only after source verification/fsync/created-state seal. Keep both descriptor acquisitions and finally cleanup in the owner.

Existing checks: `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_regular_copy_rejects_link_substitution_growth_and_caps`; `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_copy_seals_destination_identity_and_original_bytes_before_return`.

<a id="fn-70ee6a4c94c0baa2"></a>

## `scripts/verify_macos_gui_artifact.py::extract_transcript`

Validates and fully CRC-reads every selected ZIP resource, exclusively materializes it, then writes links/modes and returns a transcript.

Preserve: Allowed extras are CRC-read in original member order and never extracted; cumulative budgets include extras/inferred directories. File descriptors close before deferred symlinks, modes apply deepest-first, and exact private ZIP seal is rechecked.

Removal: Extract member planning/extra streaming without moving its original sequence, then regular-or-link payload materialization and final link/mode stages. Keep borrowed archive ownership, exclusive creation and primary/close failure handling explicit.

Existing checks: `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_allowed_extras_are_crc_checked_and_unsafe_extras_rejected`; `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_crc_and_truncated_zip_payloads_fail`; `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_path_case_type_link_and_duplicate_attacks_fail_before_extraction`.

<a id="fn-ba977a28a4ae15fc"></a>

## `scripts/verify_macos_gui_artifact.py::inspect_tree`

Owns physical transcript accumulation/budget and root binding around a nested full-resource walk.

Preserve: Nested walk carries cumulative byte budget and includes directory modes/symlink targets/resource hashes, so it cannot be replaced with a native-only or extension-only inventory. Parent and visit debts overlap.

Removal: Move visit into a named finite-state walker; retain final MAX_ENTRIES check, root verification and sorted complete transcript here. Resolve the nested task simultaneously, not via two permanent allowances.

Existing checks: `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_complete_resource_transcript_and_physical_tree_match`; `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_full_non_macho_resource_and_directory_mode_drift_are_detected`.

<a id="fn-df865b3c4f9e69de"></a>

## `scripts/verify_macos_gui_artifact.py::inspect_tree.visit`

Recursively seals every physical directory/symlink/regular resource without crossing a filesystem or following links.

Preserve: Entry type/stat seals span before/open/read/after; hardlinks/special files reject, byte totals accumulate across recursion, and directory list/stat rechecks catch concurrent mutations. Child closes preserve primary identity.

Removal: Extract bounded regular-file hashing and one opened-child handler, leaving symlink check and sorted recursion orchestration. State tracks only actual rows/total bytes; no policy-swallowing generic traversal.

Existing checks: `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_physical_tree_read_races_and_budgets_reject_changed_resources`; `tests/test_macos_gui_artifact_verifier.py::ZipTranscriptTests.test_extra_symlink_and_hardlinked_physical_resources_are_rejected`.

<a id="fn-0aa1eb792af6f700"></a>

## `scripts/verify_macos_gui_artifact.py::run_gui_process`

Runs a packaged GUI in one owned session, observes exit/output and signals/proves/reaps the owned group.

Preserve: Final group signal must precede direct fallback/proof/reap to avoid PID/PGID reuse; ABI/default SIGCHLD checks precede child creation. Output capture and ordered cleanup failures retain the original control exception.

Removal: Extract ordered cleanup of the existing unreaped process into a specific helper returning returncode/errors. Keep observation/primary capture and final exception resolution in the owner; no second process controller.

Existing checks: `tests/test_macos_gui_artifact_verifier.py::ReceiptAndRuntimeTests.test_unsupported_ownership_policy_and_api_fail_before_child_creation`; `tests/test_macos_gui_artifact_verifier.py::NativeLifecycleTests.test_native_timeout_reaps_owned_group`; `tests/test_macos_gui_artifact_verifier.py::NativeLifecycleTests.test_native_observer_and_control_errors_preserve_primary`.

<a id="fn-3b4f85fb261dd65d"></a>

## `scripts/verify_macos_gui_artifact.py::verify_archive`

Binds original/private ZIP, verifies full extraction/native inventory, runs actual packaged GUI, checks receipt/resource stability, rehashes original and cleans owners.

Preserve: Replacing the new private root must not trigger recursive deletion of an unowned namespace. GUI-success claims require exact receipt plus unchanged complete resources/original bytes and successful cleanup, not process exit alone.

Removal: Extract final bound original-source rehash, packaged executable/receipt smoke stage and owned cleanup resolution. Preserve native runtime preflight before source reads and source/private ancestry acquisition cleanup even on early failures.

Existing checks: `tests/test_macos_gui_artifact_verifier.py::PipelineTests.test_missing_receipt_primary_control_and_cleanup_failures_block_success`; `tests/test_macos_gui_artifact_verifier.py::PipelineTests.test_new_private_root_replacement_is_not_written_or_recursively_removed`; `tests/test_macos_gui_artifact_verifier.py::PipelineTests.test_source_replacement_and_full_resource_flip_after_launch_fail`.

<a id="fn-f92805c913f1af36"></a>

## `scripts/verify_native_wheel_proposal.py::_command_policy`

Authenticates ordered command/phase IDs and exact native generator, compile, download, observation, verification and offline install policies.

Preserve: Removing global banned flags, -I, distinct environment/wheelhouse/cache roots, or exact helper/path/receipt binding permits synthetic/cross-platform proofs. Windows canonical key/case handling differs intentionally from POSIX.

Removal: Split command grouping/schema/order validation from named environment, download/compile, observation/preflight and verification/install policy passes. Preserve pass order, exact command coverage and final pip isolation/binary/direct-URL checks.

Existing checks: `tests/test_native_wheel_proposal_validation.py::TestNativeWheelProposalValidation.test_command_hash_offline_isolation_and_cross_platform_bypasses_reject`; `tests/test_native_wheel_proposal_validation.py::TestNativeWheelProposalValidation.test_phase_outcomes_exact_ids_coverage_and_positive_counts_reject`; `tests/test_native_wheel_proposal_validation.py::TestNativeWheelProposalValidation.test_distinct_environment_wheelhouse_cache_and_monotonic_command_proofs_reject`.

<a id="fn-0cd252af0c738c29"></a>

## `src/cli.py::_run_convert`

Coordinate a conversion attempt, live report and cancellation owners, primary error classification, external/canonical report settlement, single buffered terminal summary and ordered exit/error presentation.

Preserve: SIGINT must be active before Converter construction and managed_generation_decided set in the original convert finally. Keep the sole observer, live diagnostics/Namespace reads, logs-before-report settlement, original primary failure precedence, preparing/committing/committed trace-sensitive statements and stdout write, plus handler restore immediately before return. Helper extraction must not introduce an earlier property read, second observer/controller, or a broader catch.

Removal: Extract three named stages: classify the primary convert result through the live backend; settle external/canonical reports and cancelled outcomes through the existing report/session owners; select and emit terminal failure details in the existing primary/report/artifact/attempt/restore precedence. Use finite typed result records only for computed local results and the existing live owners for observable dependencies. Keep the original summary loop, phase assignments, stdout write and restore/return windows in _run_convert. Measure each extracted function and the driver before accepting the decomposition.

Test task: Retain all 78 original TestCLIReports methods/446 self assertions and the separate four report/three session cases; do not rewrite trace windows or relax selectors. Verify preflight/runtime error precedence when reports also fail, first/second SIGINT, construction/install/log-flush/summary-gap interruptions, committed-generation cutoff and single terminal output.

Existing checks: `tests.test_cli.TestCLIReports.test_preflight_error_survives_external_report_failure`, `tests.test_cli.TestCLIReports.test_runtime_error_survives_external_report_failure`, `tests.test_cli.TestCLIReports.test_sigint_during_converter_construction_publishes_cancelled_outcome`, `tests.test_cli.TestCLIReports.test_second_sigint_during_handler_install_restores_previous_handler`, `tests.test_cli.TestCLIReports.test_sigint_in_pre_summary_gap_is_observed_before_output`, `tests.test_cli.TestCLIReports.test_sigint_after_handler_restore_cannot_override_committed_exit`, `tests.test_cli.TestCLIReports.test_real_post_decision_sigint_never_rewrites_canonical_reports`, `tests.test_cli_conversion_session.TestCLIConversionSession.test_borrowed_event_live_phase_and_generation_cutoff`, `tests.test_cli_conversion_session.TestCLIConversionSession.test_late_native_signal_binding_and_distinct_restoration_paths`, `tests.test_cli_conversion_session.TestCLIConversionSession.test_session_import_boundary_and_driver_trace_windows`

<a id="fn-c83997288b25dc51"></a>

## `src/cli_report_lifecycle.py::ConversionReportLifecycle.repair`

Repair canonical/external diagnostic reports while preserving borrowed checkpoints and verified generations, observe cancellation at two exact stages, refresh artifact manifests or publish the failed attempt, and retry outcome changes.

Preserve: Deduplicate normalized destinations only once at entry while preserving live args/operation read order. Maintain reverse receipt restoration, first report-error selection, same-object borrowed checkpoints/receipts, per-publication current backend diagnostics, managed report protection, existing exception/control boundaries and both cancellation observations. Refresh/attempt errors and restore notes must retain their precedence; a failed late repair must not erase a trusted generation.

Removal: Extract destination planning called once at entry; one per-iteration diagnostic publication stage returning a finite typed canonical-current/first-error result; and the artifact refresh/attempt publication stage returning a typed outcome/retry decision. Keep set_outcome/reset and the two observe_cancellation calls at their original outer-loop stages. Reuse existing checkpoint/reset/restore and seven live operations; do not cache diagnostics or introduce another transaction/report controller. Retain first Exception handling and unchanged KeyboardInterrupt propagation, then measure every new function and repair.

Test task: Retain real publication/reassigned-collector, reverse restore/retry/notes and success-to-cancelled repair-reentry tests, plus existing driver failures. Exercise equal canonical/external destinations, failed repair preserving both prior pairs, late manifest refresh failure, protected prior-generation reports and cancellation during publication; assert bytes, errors, call order and no duplicate summary.

Existing checks: `tests.test_cli_report_lifecycle.TestCLIReportLifecycle.test_repair_uses_reassigned_backend_diagnostics_and_real_report_publication`, `tests.test_cli_report_lifecycle.TestCLIReportLifecycle.test_reverse_restore_retains_failed_real_receipt_notes_and_clears_after_retry`, `tests.test_cli_report_lifecycle.TestCLIReportLifecycle.test_report_import_boundary_and_single_observer_repair_reentry`, `tests.test_cli.TestCLIReports.test_external_report_failure_repairs_published_success_json`, `tests.test_cli.TestCLIReports.test_external_report_failure_preserves_every_failed_repair_pair`, `tests.test_cli.TestCLIReports.test_external_report_failure_deduplicates_canonical_destination`, `tests.test_cli.TestCLIReports.test_real_managed_report_failure_preserves_prior_generation`, `tests.test_cli.TestCLIReports.test_sigint_during_report_generation_rewrites_cancelled_outcome`

<a id="fn-aa1d01658377dbfd"></a>

## `src/conversion/anchored_artifacts.py::ByteArtifactTransaction._rollback_published_mutations`

Roll back published mutations in reverse order.

Preserve: Continue after ordinary/control failures, preserve unknown replacements, durable backup cleanup and combined first-signal ordering.

Removal: Extract one mutation restoration with its retained recovery candidate.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_publish_rollback_continues_after_one_target_fails`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_publish_multiple_rollback_signals_use_first_identity_and_keep_notes`

<a id="fn-38c3c1649c2ad00d"></a>

## `src/conversion/anchored_artifacts.py::ByteArtifactTransaction._rollback_restore_mutations`

Roll back completed snapshot restoration in reverse order.

Preserve: Distinguish displaced-only vs restored targets, retain exact recovery candidates and continue collecting errors without overwriting external changes.

Removal: Extract per-mutation receipt restoration and final receipt verification.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_restore_rollback_continues_and_retains_exact_receipt`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_restore_forward_system_exit_survives_ordinary_rollback_failure`

<a id="fn-8cf7b45fc4c7fc01"></a>

## `src/conversion/anchored_artifacts.py::ByteArtifactTransaction.cleanup`

Clean transaction temporary files and durably record completed removals.

Preserve: Completed removals sync before rethrow; incomplete control signals stop traversal, first control-signal identity wins, after_cleanup is conditional.

Removal: Extract one temporary cleanup outcome and final error aggregation.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_cleanup_completed_signal_precedes_later_incomplete_signal_and_stops`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_cleanup_completed_unlink_signal_syncs_before_exact_reraise`

<a id="fn-cee263f1864669ac"></a>

## `src/conversion/anchored_artifacts.py::ByteArtifactTransaction.publish_specs`

Publish an ordered artifact set with guards, backups and rollback.

Preserve: Preserve before/after callbacks, guard rechecks, mutation recording before completion errors, per-target durability and reverse rollback.

Removal: Extract desired-stage/backup preparation and one guarded mutation.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_ordered_publish_rolls_back_all_prior_mutations`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_completed_present_publish_signal_records_mutation_before_rollback`

<a id="fn-653a2d83370a63f9"></a>

## `src/conversion/anchored_artifacts.py::ByteArtifactTransaction.restore_snapshots`

Restore ordered snapshots while publication receipts remain exact.

Preserve: Record ambiguous displacement and restored_committed before errors; keep receipt rechecks, durability and recovery retention.

Removal: Extract restore-stage preparation and one receipt displacement/restore step.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_restore_rolls_back_completed_receipt_displacement`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_ordered_restore_rechecks_later_receipt_after_prior_durability`

<a id="fn-a4fb89ba2a09f785"></a>

## `src/conversion/anchored_artifacts.py::ByteArtifactTransaction.unlink_finalized`

Remove a finalized target via Windows tombstone or bound unlink.

Preserve: Return completed/unknown ownership faithfully; keep displaced tombstone identity, read-only restoration and original/control-flow error preference.

Removal: Extract backend-specific removal and completion-probe resolution.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_unlink_finalized_completion_probe_signal_does_not_mask_original`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_modeled_windows_absent_publish_completed_unknown_tombstone_resolves_displaced_owner`

<a id="fn-89d6c2647aaee69f"></a>

## `src/conversion/anchored_artifacts.py::VerifiedDirectory.chmod_exact`

Change a bound regular file mode with restoration after drift.

Preserve: Keep provider binding, hard-link checks, expected-current-mode checks and Windows path fallback; never restore an externally replaced inode.

Removal: Extract descriptor chmod provider selection and late identity/mode restoration.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_descriptor_chmod_callbacks_preserve_provider_binding`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_modeled_windows_hardlink_during_fchmod_restores_alias_mode`

<a id="fn-8c7b2ff95d81e2c7"></a>

## `src/conversion/anchored_artifacts.py::VerifiedDirectory.open_child`

Open and verify an identity-bound child directory.

Preserve: Parent and child verification order, no-follow binding, fallback policy and same-object primary exceptions must remain exact.

Removal: Extract POSIX and Windows child-open paths, sharing only rejected-binding cleanup where semantics match.

Existing checks: `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_windows_child_prebind_swap_to_junction_is_rejected`, `tests.test_anchored_artifacts.TestAnchoredArtifacts.test_child_is_bound_before_parent_durability_barrier`

<a id="fn-2eafa45f61f69563"></a>

## `src/conversion/atomic_generated_text.py::_atomic_write_asset_text_fallback`

Write asset text atomically on fallback paths, including read-only Windows.

Preserve: Preserve exact staging/output identity, file modes, Windows quarantine path and unchanged silent cleanup OSError policy.

Removal: Extract post-publication validator cleanup and owned-stage cleanup.

Existing checks: `tests.test_atomic_generated_text.TestAtomicGeneratedText.test_posix_paths_preserve_exact_readonly_mode`, `tests.test_atomic_generated_text.TestAtomicGeneratedText.test_native_windows_readonly_hardlink_preserves_external_alias`

<a id="fn-7feced4f9f640fca"></a>

## `src/conversion/atomic_generated_text.py::_publish_bound_windows_readonly_asset_transaction`

Replace read-only Windows assets with retained handles and rollback.

Preserve: The previous-file deletion uncertainty forbids rollback; keep validator/hook order, namespace checks and separate cleanup notes.

Removal: Extract delete-pending commit classification and handle cleanup.

Existing checks: `tests.test_atomic_generated_text.TestAtomicGeneratedText.test_readonly_transaction_failures_restore_original`, `tests.test_atomic_generated_text.TestAtomicGeneratedText.test_readonly_transaction_preserves_unknown_publish_destination`

<a id="fn-824a24b5908d3a28"></a>

## `src/conversion/conversion_artifact_generation.py::_publish_locked`

Commit a conversion artifact pair through journal and generation pointer.

Preserve: Keep callbacks for unchanged manifest values, known-transition checks, durable pointer as commit boundary and recovery only before commitment.

Removal: Extract one desired-value publication and post-commit journal cleanup.

Existing checks: `tests.test_conversion_manifest.TestConversionManifest.test_subprocess_interruption_recovers_every_generation_boundary`, `tests.test_conversion_manifest.TestConversionManifest.test_subprocess_interruption_recovers_every_rollback_boundary`

<a id="fn-4a0b2035c18f3a59"></a>

## `src/conversion/converter.py::Converter._run_finalizers`

Publish/restore finalizer architecture and diagnostic checkpoints.

Preserve: Preserve finalizer error ordering, staged finalizer eligibility, late cancellation rewrite and restoration only against the matching generation.

Removal: Extract architecture checkpoint, diagnostic checkpoint and post-commit cancellation refresh.

Existing checks: `tests.test_converter.TestConverterOutcomes.test_cancellation_during_artifact_publish_keeps_success_canonical`, `tests.test_converter.TestConverterOutcomes.test_finalizer_failure_revokes_late_canonical_refresh_candidate`

<a id="fn-bf90e664d206a7be"></a>

## `src/conversion/converter.py::Converter.convert`

Orchestrate conversion recovery, preflight, steps, finalizers and verified publication.

Preserve: Keep canonical outcome, cancellation boundaries, workspace cleanup and runtime-before-finalizer/attempt errors; public convert signature stays stable.

Removal: Extract conversion-step execution/accounting and final exception resolution without a second controller.

Existing checks: `tests.test_converter_transaction.TestConverterManagedOutputTransaction.test_mid_run_cancellation_after_real_write_preserves_baseline`, `tests.test_converter.TestConverterOutcomes.test_runtime_error_precedes_finalizer_error`

<a id="fn-bfa87cbeee92f17b"></a>

## `src/conversion/fonts.py::FontConverter._find_disk_font_files`

Discover contained disk fonts without a YYP manifest.

Preserve: Keep sorted scan/reverse child scheduling, no symlink directory traversal, cross-family validation and report callback order.

Removal: Extract entry classification/resolution and accepted font validation from DFS.

Existing checks: `tests.test_fonts.TestFontConverterSourcePathContainment.test_rejects_disk_fallback_font_directory_link`, `tests.test_fonts.TestFontConverterSourcePathContainment.test_disk_fallback_rejects_contained_cross_family_font_yy_link`

<a id="fn-61f436db49ea69c6"></a>

## `src/conversion/fonts.py::FontConverter._process_font`

Convert one validated font from bundled/system source or .tres fallback.

Preserve: Keep owner-relative resolution before system fallback, second bundled check immediately before copy, metadata preservation and output filename/log stage.

Removal: Extract bundled-source selection/revalidation and publication/logging.

Existing checks: `tests.test_fonts.TestFontConverterSourcePathContainment.test_revalidates_bundled_font_immediately_before_copy`, `tests.test_fonts.TestFontConverterSystemFontLookup.test_system_font_copy_does_not_propagate_protected_metadata`

<a id="fn-a516752c7a269a05"></a>

## `src/conversion/generation_inventory.py::_validate_legacy_generated_files`

Validate legacy generated-file entries against actual inventory.

Preserve: Preserve manifest self exception, auxiliary/unmanaged skipping before duplicate tracking, case-collision and shared-owner digest exceptions.

Removal: Extract one canonical entry classification and current-entry validation.

Existing checks: `tests.test_generation_inventory.TestGenerationInventory.test_legacy_manifest_migration_completes_unchanged_managed_roots`, `tests.test_generation_inventory.TestGenerationInventory.test_legacy_migration_rejects_ambiguous_or_nonfinite_json`

<a id="fn-cc26607ae8eac241"></a>

## `src/conversion/gml_transpiler_parts/emitter.py::_emit_descriptor_call`

Lower descriptor-specific function calls after arity validation.

Preserve: Keep arity first, base instance arguments before domain overrides and exact self/other/default placement.

Removal: Extract keyboard/method, callback-array, instance-domain and variadic groups.

Existing checks: `tests.test_gml_api_manifest.TestGMLAPIManifest.test_function_descriptor_arity_validation_is_deterministic`, `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_audio_helpers_lower_sound_assets_to_runtime`

<a id="fn-b04bcaba675ffa3a"></a>

## `src/conversion/gml_transpiler_parts/emitter.py::_emit_expression`

Emit typed expression nodes recursively.

Preserve: Preserve child evaluation order, operator precedence and receiver/static binding.

Removal: Extract Call and FunctionLiteral emission.

Existing checks: `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_omitted_call_arguments_emit_gml_undefined`, `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_template_string_target_expressions_are_evaluated_once`

<a id="fn-ac0c1a7f90ca0a8f"></a>

## `src/conversion/gml_transpiler_parts/emitter.py::_emit_name`

Emit scope/builtin/asset names with collision precedence.

Preserve: Preserve locals/static/asset-global precedence and resolve_asset_names=False checks.

Removal: Separate nonlocal builtin/legacy and instance resolution.

Existing checks: `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_scope_lookup_precedence_and_asset_values_are_explicit`, `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_rejects_unscoped_asset_name_variable_collisions`

<a id="fn-5ff66ad16f1b49a6"></a>

## `src/conversion/gml_transpiler_parts/enum_helpers.py::_evaluate_enum_expression`

Evaluate constant enum expressions.

Preserve: Binary left then right still evaluates right when left is None; named calls stop at their first nonconstant argument.

Removal: Extract unary and named-call argument evaluation.

Existing checks: `tests.test_gml_expression_api.GMLExpressionAPITests.test_enum_and_constant_semantic_operations_preserve_results_and_errors`

<a id="fn-181c028b48470bc2"></a>

## `src/conversion/gml_transpiler_parts/enum_helpers.py::_reject_enum_mutation_expression`

Reject forbidden enum mutations across supported children.

Preserve: Check forbidden mutation call before callee/arguments; do not start traversing previously ignored nodes.

Removal: Merge identical Struct/DSMap branches, then separate supported-child recursion.

Existing checks: `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_rejects_enum_member_mutation`, `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_allows_enum_member_as_non_mutating_index`

<a id="fn-eda12c7a369b9618"></a>

## `src/conversion/gml_transpiler_parts/expression_parser.py::_ExpressionParser._parse_postfix`

Parse postfix calls/accessors with token positions.

Preserve: Preserve match/consume order, omitted sentinels and source errors.

Removal: Extract call-argument and bracket-suffix readers.

Existing checks: `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_omitted_call_arguments_emit_gml_undefined`, `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_transpiles_multiple_template_expressions_and_accessors`

<a id="fn-590b832be1d76089"></a>

## `src/conversion/gml_transpiler_parts/expression_parser.py::_ExpressionParser._parse_primary`

Parse literals/names/arrays/structs/function expressions.

Preserve: Keep quoted/empty-key errors, parser cursor and original error positions.

Removal: Extract string and array/struct readers.

Existing checks: `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_transpiles_nameof_enum_member_after_declaration`, `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_rejects_malformed_template_strings`

<a id="fn-08e62a3c55d23968"></a>

## `src/conversion/gml_transpiler_parts/gml_function_dispatch.py::_build_function_descriptors`

Register the finite GML descriptor catalog.

Preserve: Keep insertion order, duplicate collisions, final overrides and all public descriptor metadata.

Removal: Extract core-value, resource/instance and platform registration phases with typed table helper.

Existing checks: `tests.test_gml_api_manifest.TestGMLAPIManifest.test_function_descriptors_include_lowering_metadata_and_issue_urls`, `tests.test_gml_api_manifest.TestGMLAPIManifest.test_function_descriptors_cover_current_implemented_call_helpers`

<a id="fn-6403511a9bed2866"></a>

## `src/conversion/gml_transpiler_parts/preprocessor.py::preprocess_gml_source`

Preprocess active directives to normalized source.

Preserve: Share only identical state logic; retain macro continuations, normalized output and first diagnostic.

Removal: Extract conditional frame transitions and active-directive handling.

Existing checks: `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_preprocessor_conditionals_skip_disabled_code`, `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_preprocessor_define_values_feed_macro_expansion`

<a id="fn-5850f1ee7d7e600b"></a>

## `src/conversion/gml_transpiler_parts/preprocessor.py::preprocess_gml_source_preserving_layout`

Preprocess directives while preserving original source layout.

Preserve: Retain exact offsets/newlines, macro continuations and distinct layout policy; avoid merging normalized-output semantics.

Removal: Extract conditional frame transitions and span blanking.

Existing checks: `tests.test_gml_lexical_api.GMLLexicalAPIBehaviorTests.test_preprocessing_models_layout_bytes_positions_and_failures`, `tests.test_gml_source_maps.TestGMLSourceMaps.test_source_map_tracks_comments_macros_multiline_and_nested_blocks`

<a id="fn-352ef2975d8347cb"></a>

## `src/conversion/gml_transpiler_parts/statements.py::_assignment_target_reader_writer`

Build assignment target reader/writer closures.

Preserve: Keep _record_instance_assignment stage, cached target/key order and closure captures.

Removal: Separate scoped/builtin resolution from collection/selector handling.

Existing checks: `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_assignment_expression_results_cover_member_and_accessor_targets`, `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_transpiles_postincrement_in_simple_array_assignment_index`

<a id="fn-3b9a5f8787d0afc0"></a>

## `src/conversion/gml_transpiler_parts/statements.py::transpile_statement`

Transpile statement forms with mutable scope/control state.

Preserve: Preserve finally capture, shared sets/counters, LHS-before-RHS, lazy nullish preludes and writeback; do not repair unrelated unreachable DS-list raise after DS-grid raise.

Removal: Extract control-flow/throw, delete, increment and assignment phases.

Existing checks: `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_finally_preserves_abrupt_control_flow_from_try_body`, `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_transpiles_nullish_assignment`

<a id="fn-2c8302b8062c3df5"></a>

## `src/conversion/gml_transpiler_parts/tokens.py::tokenize_gml_source`

Tokenize source with exact cursors and positions.

Preserve: Outer cursor retains newline/operator order and unterminated-prefix location.

Removal: Extract string/numeric and dollar/hash prefix readers.

Existing checks: `tests.test_gml_tokenizer.TestGMLTokenizerLineColumns.test_public_tokens_preserve_exact_lf_crlf_cr_and_mixed_positions`, `tests.test_gml_tokenizer.TestGMLTokenizerLineColumns.test_rejects_unterminated_verbatim_string_at_prefix_location`

<a id="fn-3dc44b113d04833b"></a>

## `src/conversion/gml_transpiler_parts/utils.py::split_assignment`

Find top-level assignment operators while respecting quoted/depth syntax.

Preserve: Keep escapes/depth transitions/operator order and comparison filtering.

Removal: Extract quoted consumption or top-level operator recognition.

Existing checks: `tests.test_gml_transpiler.TestGMLExpressionTranspiler.test_verbatim_content_is_not_split_as_comments_or_statements`, `tests.test_gml_transpiler.TestGMLStatementTranspiler.test_transpiles_compound_assignments`

<a id="fn-3abe33ab62fc41fa"></a>

## `src/conversion/godot_validation.py::_run_godot_command`

Run Godot with bounded output and owned process/reader cleanup.

Preserve: Keep non-reaping POSIX exit observation, claim/abandon lock, live-reader pipe ownership, timeout identity/output, group cleanup and diagnostic order.

Removal: Extract output-reader lifecycle and process cleanup/error assembly with explicit ownership state.

Existing checks: `tests.test_godot_validation.TestGodotProcessOwnership.test_interrupted_reader_start_abandons_target_before_descriptor_reuse`, `tests.test_godot_validation.TestGodotProcessOwnership.test_independent_teardown_failures_keep_timeout_and_all_diagnostics`

<a id="fn-4e1377386afc07d5"></a>

## `src/conversion/godot_validation.py::_wait_godot_process_exit`

Observe POSIX child exit without releasing its PID.

Preserve: Preserve ownership checks around observation, WNOWAIT, deadline semantics, ProcessLookup reproof and queue-close error notes; no wait/poll substitution.

Removal: Extract waitid and kqueue observation implementations.

Existing checks: `tests.test_godot_validation.TestGodotProcessOwnership.test_already_reaped_leader_never_signals_reusable_pid`, `tests.test_godot_validation.TestGodotProcessOwnership.test_timeout_observer_close_note_reaches_validation_output`

<a id="fn-c5b632d5425ab93f"></a>

## `src/conversion/godot_validation.py::validate_generated_godot_project`

Import, validate resources and optionally boot generated Godot output.

Preserve: Do not collapse permitted import-only timeout success into general success; preserve output issue detection, boot ordering, report bytes and resource discovery.

Removal: Extract import/no-audio-fallback outcome decision and resource-script validation.

Existing checks: `tests.test_godot_validation.TestGodotValidation.test_import_only_validation_skips_resource_load_script`, `tests.test_godot_validation.TestGodotValidation.test_import_timeout_returns_bounded_partial_output`

<a id="fn-af86ebd4c1da445c"></a>

## `src/conversion/included_files_parts/driver.py::IncludedDriverOperations.convert_included_files`

Plan, lock, recover, stage workers and publish Included Files.

Preserve: Keep dynamic self dispatch/resource accounting, active output reset, bounded worker cancellation, source receipt verification and final lock release precedence.

Removal: Extract unchanged-generation completion, worker-result consumption and staged-registry/transaction assembly into finite typed operations.

Existing checks: `tests.test_included_files_locking.TestIncludedFilesManagedRootTransaction.test_project_lock_release_is_once_for_lifecycle_returns`, `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_changed_payload_uses_the_normal_output_transaction`

<a id="fn-92a9c590d9c6d336"></a>

## `src/conversion/included_files_parts/guarded_mutations.py::_chmod_exact_included_file`

Apply exact Included Files mode changes with pinned parent policy.

Preserve: Borrowed Windows binding remains caller-owned; retain late hook before open, exact inode checks and restoration notes after quarantined failure.

Removal: Extract descriptor path and fallback quarantine/chmod/restore paths.

Existing checks: `tests.test_included_files_state_owners.TestIncludedFilesStateOwners.test_fallback_quarantine_observes_late_hook_before_moving_real_entry`, `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_native_windows_readonly_commit_failure_rolls_back_cleanly`

<a id="fn-fd96f906b327cef3"></a>

## `src/conversion/included_files_parts/guarded_mutations.py::_move_exact_included_entry`

Move an exact Included Files entry with parent identities.

Preserve: Keep original rename hook and repeated parent checks, no overwrite, same-binding optimization and unknown-moved-entry preservation.

Removal: Extract descriptor and fallback moves with explicit parent-verification closures.

Existing checks: `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_transaction_source_swap_restores_unknown_replacement_without_loss`, `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_unknown_registry_backup_destination_is_not_overwritten`

<a id="fn-295d01100af7e2af"></a>

## `src/conversion/included_files_parts/locking.py::_acquire_included_project_lock`

Acquire cooperative Included Files project lock safely.

Preserve: Windows locks before reading the byte; POSIX validates before flock, then rechecks content/namespace; retain unlock/close ordering on failure.

Removal: Extract lock validation/acquisition from file opening/initialization and cleanup.

Existing checks: `tests.test_included_files_locking.TestIncludedFilesManagedRootTransaction.test_modeled_windows_lock_contends_before_reading_locked_byte`, `tests.test_included_files_locking.TestIncludedFilesManagedRootTransaction.test_project_lock_rejects_ambiguous_existing_content_without_mutation`

<a id="fn-0a2794ac65f663ca"></a>

## `src/conversion/included_files_parts/publisher.py::_commit_included_output_set`

Publish Included Files root/registry as one recoverable generation.

Preserve: Cancellation/hook/fsync boundaries and durable marker determine rollback permission; ambiguous marker lookup must preserve recovery state.

Removal: Extract journal preparation, root/registry move phases, commit validation and post-commit retirement.

Existing checks: `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_subprocess_interruption_recovers_every_publication_boundary`, `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_committed_cleanup_recovery_is_idempotent_at_every_owned_boundary`

<a id="fn-75994f0f5dd4ee2f"></a>

## `src/conversion/included_files_parts/recorded_cleanup.py::_cleanup_recorded_included_directory`

Quarantine/remove one recorded Included Files cleanup directory.

Preserve: Unknown/duplicate/nonempty entries remain untouched; verify borrowed parent around list/remove and deliver quarantined/removed phases after durability.

Removal: Extract tombstone-resume handling and source-to-tombstone preparation.

Existing checks: `tests.test_included_files_state_owners.TestIncludedFilesStateOwners.test_phase_observer_is_live_after_real_quarantine_and_on_cleanup_resume`, `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_committed_cleanup_preserves_unknown_content_inside_recorded_trees`

<a id="fn-8fc1794e0fb8dc70"></a>

## `src/conversion/included_files_parts/recorded_cleanup.py::_cleanup_recorded_included_tree`

Clean a manifest-bound Included Files tree with native handle lifetimes.

Preserve: Preserve absent subtree pruning, reverse file/removal ordering, shared root handle lifetime and child closure before parent removal; do not flatten to recursive path deletion.

Removal: Extract POSIX-like traversal and Windows preflight/cleanup action stacks.

Existing checks: `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_windows_nested_absent_subtree_skips_descendant_work`, `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_windows_nested_bindings_close_before_parent_removal`

<a id="fn-ea87dacca7c2b99e"></a>

## `src/conversion/included_files_parts/recovery.py::_cleanup_orphan_included_recovery_state`

Clean only self-identifying orphan staging/temporary/cleanup records.

Preserve: Retain fresh sorted rescans, identity/marker validation, unpromoted journal preservation, canonical tombstone names and warning order.

Removal: Extract each of the three reserved-entry classes into separate passes.

Existing checks: `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_temporary_record_cleanup_tombstones_resume_after_hard_exit`, `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_oversized_canonical_recovery_temporaries_are_preserved_unread`

<a id="fn-1066d7288473e54c"></a>

## `src/conversion/included_files_parts/recovery.py::_recover_included_output_set`

Recover journal/marker generations or orphan state.

Preserve: Keep journal/marker agreement, durable prior generation verification, record retirement order and exact recovery messages/phases.

Removal: Extract marker-only, uncommitted rollback and committed cleanup branches.

Existing checks: `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_marker_only_committed_recovery_uses_embedded_cleanup_manifest`, `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_restart_rollback_syncs_registry_before_journal_retirement`

<a id="fn-8bd6de8f7f636481"></a>

## `src/conversion/included_files_parts/recovery_codec.py::_included_recovery_journal_from_payload`

Decode and cross-validate a bounded Included Files recovery journal.

Preserve: Retain exact key/type/version rules, compact vs legacy integer policy, alias/device rejection and path construction only after validation.

Removal: Extract staged-snapshot consistency and registry/managed-identity cross-validation.

Existing checks: `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_recovery_parsers_reject_ambiguous_json_types`, `tests.test_included_files_recovery.TestIncludedFilesManagedRootTransaction.test_modeled_windows_commit_marker_rejects_forged_embedded_path_before_io`

<a id="fn-8d886d7d8fbe0484"></a>

## `src/conversion/included_files_parts/staging.py::_create_included_output_stage`

Allocate a private Included Files stage and ownership marker.

Preserve: Preserve 100 collision attempts, parent/child identity checks, marker timing and BaseException-vs-Exception cleanup distinction.

Removal: Extract descriptor-bound and fallback allocation branches.

Existing checks: `tests.test_included_files_staging.TestIncludedFilesManagedRootTransaction.test_fallback_stage_allocation_preserves_colliding_file`, `tests.test_included_files_staging.TestIncludedFilesManagedRootTransaction.test_moved_and_symlinked_stage_container_is_rejected`

<a id="fn-a7b40067e92bf25d"></a>

## `src/conversion/included_files_parts/transaction_cleanup.py::_rollback_included_output_set`

Restore previous Included Files registry/root after failed publication.

Preserve: Continue collecting each branch error; never overwrite unknown entries, retain registry-before-root order and exact previous-absence policy.

Removal: Extract registry restoration, root restoration and newly-created-directory cleanup.

Existing checks: `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_first_publication_rollback_is_idempotent_after_registry_publish`, `tests.test_included_files_transactions.TestIncludedFilesManagedRootTransaction.test_preprepare_rollback_refuses_appeared_registry_before_read`

<a id="fn-1198191da02ca10c"></a>

## `src/conversion/managed_output_publisher.py::_copy_file_exact`

Copy an exact managed-output backup under retained directory bindings.

Preserve: No-follow one-link/same-device checks and source-after verification must bracket copy; retain read-only mode and binding-close order.

Removal: Extract bounded streaming/digest validation and owned destination cleanup.

Existing checks: `tests.test_managed_output_publisher.TestManagedOutputPublisher.test_symlink_and_hardlink_public_entries_preserve_external_targets`, `tests.test_managed_output_publisher.TestManagedOutputPublisher.test_windows_read_only_replacement_uses_write_through_moves`

<a id="fn-c05bb66e753e2342"></a>

## `src/conversion/managed_output_publisher.py::_move_exact_noreplace`

Move exact managed-output entries without replacement and with durability.

Preserve: Keep hook before the second source/destination check, no-replace rename, safe rollback, parent sync order and durable phase only after verified success.

Removal: Extract read-only preparation/restoration and namespace rollback.

Existing checks: `tests.test_managed_output_publisher.TestManagedOutputPublisher.test_concurrent_replacement_is_preserved_and_fails_closed`, `tests.test_managed_output_publisher.TestManagedOutputPublisher.test_each_install_failure_rolls_back_complete_prior_generation`

<a id="fn-2adab6ed547d1551"></a>

## `src/conversion/managed_output_workspace.py::ManagedOutputWorkspace._capture_cleanup_entries`

Capture an ownership-bound managed-output cleanup tree.

Preserve: Keep global entry counter/order, stage marker last, resume-prefix policy, mount/device boundaries and child resource closure; never traverse redirects.

Removal: Extract reserved-name validation and regular-file capture from recursive directory capture.

Existing checks: `tests.test_managed_output_workspace.TestManagedOutputWorkspace.test_cleanup_rejects_hardlinked_stage_then_retries_safely`, `tests.test_managed_output_workspace.TestManagedOutputWorkspace.test_changed_ownership_marker_is_preserved_until_restored`

<a id="fn-072cf50565558748"></a>

## `src/conversion/notes.py::NoteConverter._discover_notes`

Discover contained text notes and companion metadata.

Preserve: Retain sorted DFS/dedup, one resolved-entry map, metadata live read timing and symlink rejection before text copy.

Removal: Extract directory entry collection and note asset assembly.

Existing checks: `tests.test_notes.TestNoteConverterSourceContainment.test_rejects_external_companion_yy_without_reading_it`, `tests.test_notes.TestNoteConverterSourceContainment.test_final_pre_copy_check_rejects_late_note_symlink_swap`

<a id="fn-aa2d274f778c8fdd"></a>

## `src/conversion/objects.py::ObjectConverter.convert_objects`

Plan object assets and consume parallel conversion outcomes.

Preserve: Preserve manifest authority, initial runtime/context construction, as_completed order, first worker error after all results and sorted final accounting.

Removal: Extract fallback discovery and completed/skipped/failed future accounting.

Existing checks: `tests.test_objects.TestObjectConverterBasic.test_cancellation_leaves_objects_for_inherited_finalization`, `tests.test_objects.TestScriptGeneration.test_missing_event_source_skips_object_and_makes_conversion_partial`

<a id="fn-34e1346ae3e0d615"></a>

## `src/conversion/script_functions.py::modern_script_structure`

Recognize modern script declarations and top-level constructor initialization.

Preserve: Retain layout-preserving source offsets, enum/preprocessor skipping, declaration-before-constructor-call requirement and None for unsupported syntax.

Removal: Extract declaration parsing and supported top-level initializer cases.

Existing checks: `tests.test_scripts.TestScriptConverter.test_discovers_constructor_and_explicit_top_level_initialization`, `tests.test_scripts.TestScriptConverter.test_discovers_modern_functions_around_top_level_enum`

<a id="fn-e47f1faeb860c46f"></a>

## `src/conversion/script_generator.py::generate_script_content`

Generate canonically ordered event/runtime GDScript.

Preserve: Keep plugin callbacks/order, dedup/default body merging, inherited runtime declarations and sprite→object→draw wrapper sequencing.

Removal: Extract event/binding collection, runtime prelude and per-function body wrapping.

Existing checks: `tests.test_script_generator.TestScriptGeneratorBasic.test_object_runtime_preserves_inherited_lifecycle_when_no_local_event`, `tests.test_script_generator.TestScriptGeneratorRecursiveEvents.test_source_backed_input_keeps_original_numeric_string_coercion`

<a id="fn-6e61b6ef9443eb31"></a>

## `src/conversion/shader_translation.py::_lex_shader`

Lex shaders with source locations and unsupported-comment diagnostics.

Preserve: Keep comment/directive-before-identifier order, line_has_code, backslash continuation, exponent signs, escapes and unterminated-comment issue location.

Removal: Extract directive, number and quoted-string readers while the outer cursor owns locations.

Existing checks: `tests.test_shader_translation.TestGameMakerShaderTranslation.test_declaration_like_comments_do_not_change_parser_results`, `tests.test_shader_translation.TestGameMakerShaderTranslation.test_rejects_preprocessor_directive`

<a id="fn-75a9e24c9c9bb67a"></a>

## `src/conversion/shaders.py::ShaderConverter._disk_shader_assets`

Discover contained shader stages and companion YY metadata.

Preserve: Keep sorted DFS/source containment, expected YY name, read YY then live subfolder reread, same-directory stage ownership and first-stage authority.

Removal: Extract directory scan/classification and asset builder merging.

Existing checks: `tests.test_shaders.TestShaderSourcePathContainment.test_disk_fallback_rejects_yy_symlink_but_converts_safe_stage`, `tests.test_shaders.TestShaderAssetOwnershipAndStages.test_dual_stage_asset_publishes_one_complete_shader`

<a id="fn-6e221c1c26e19d81"></a>

## `src/conversion/sprites.py::SpriteConverter._build_precise_collision_block`

Convert alpha masks to precise collision rectangles/resources.

Preserve: Keep bbox/tolerance validation, strict alpha threshold, static composite vs per-frame masks, shared total rectangle budget and exact shape/node IDs.

Removal: Extract image-to-mask capture and resource/node emission.

Existing checks: `tests.test_sprites.TestGenerateSpriteScene.test_static_precise_multiframe_mask_composites_all_frames`, `tests.test_sprites.TestGenerateSpriteScene.test_precise_mask_uses_strict_alpha_tolerance`

<a id="fn-04c6efa683bc4b9d"></a>

## `src/conversion/sprites.py::SpriteConverter.convert_sprites`

Plan declared/discovered sprite frames, run workers and emit scenes.

Preserve: Preserve unavailable/orphan/empty accounting, stable collision-safe paths, cancellation before scenes, first worker/scene error, animation fallback and log order.

Removal: Extract sprite source planning, frame worker outcomes and scene finalization.

Existing checks: `tests.test_sprites.TestSpriteConverterBasic.test_worker_exception_fails_bad_sprite_after_safe_sibling_completes`, `tests.test_sprites.TestSpriteConverterBasic.test_scene_exception_fails_bad_sprite_after_safe_sibling_completes`

<a id="fn-3c1b53c87722de2b"></a>

## `src/conversion/tilesets.py::TileSetConverter.convert_tilesets`

Plan/revalidate tilesets and consume parallel results.

Preserve: Preserve request/skip accounting and late YY check, callback provenance, eager future exception behavior, first cancelled return and safe sibling progress.

Removal: Extract manifest vs fallback planning, leaving outcome consumption ordered as_completed.

Existing checks: `tests.test_tilesets.TestTileSetSourceContainment.test_safe_and_missing_declared_tilesets_have_strict_counts`, `tests.test_tilesets.TestTileSetSourceContainment.test_disk_fallback_rejects_tileset_file_and_directory_symlink_escapes`

<a id="fn-9c671a631fe3e7ae"></a>

## `src/deep/progress.py::DeepProgress.apply`

Merge Deep progress snapshots and partial task/agent events.

Preserve: Keep sequence replay rejection before mutation, capabilities early return, queued/completed rows, phase defaults and malformed container handling.

Removal: Extract monitoring row merge and completion/error message update.

Existing checks: `tests.test_deep_progress.ProgressStateTests.test_task_snapshots_merge_with_agent_updates_and_replayed_events`

<a id="fn-e2f53a41191826dc"></a>

## `src/gui/widgets/deep_model_picker.py::DeepModelPicker.set_catalog`

Populate provider/model UI from discovered catalog.

Preserve: Keep saved selection/recommendation policy, signal blocking stages, authenticated runtime wording and catalog_changed then selection_changed order.

Removal: Extract automatic/provider/free population and status text construction.

Existing checks: `tests.test_deep_models.ModelPickerTests.test_explicit_saved_selection_retained_and_recommendation_is_optional`, `tests.test_deep_models.ModelPickerTests.test_old_extension_cannot_change_saved_job_model`

<a id="fn-449e694d388ce00c"></a>

## `src/update_checker.py::UpdateChecker.download_update`

Download, verify and atomically replace an update payload.

Preserve: Keep request before validation, finite streaming bounds, progress callbacks, old mode preservation, publication only after exact digest/size and response/temp cleanup.

Removal: Extract expected/header validation and streamed digest/size verification.

Existing checks: `tests.test_update_checker.TestDownloadUpdate.test_truncated_download_preserves_existing_destination_and_cleans_up`, `tests.test_update_checker.TestDownloadUpdate.test_missing_content_length_allows_nonempty_download`

<a id="fn-7c0abbdb6920c4e3"></a>

## `tests/test_ci_workflows.py::TestCIWorkflows.test_authoritative_dependency_lock_fetch_contract`

Execute the privileged fetch workflow Bash against ordered exact repository-contents GET responses for all four native labels.

Preserve: All22 assertion sites remain, including endpoint order and duplicate shared-Mac request, raw per-label lock bytes, empty output on every failure, duplicate/truncated JSON, content/size cap and missing response. Keep Intel metadata/source/missing/content/newline mutations and exact errors. Never deduplicate the two Mac fetches or normalize their raw-byte comparison.

Removal: Extract authenticated response/fake-gh fixture construction and a negative-result assertion helper; consolidate only repeated execution/assertion plumbing while each mutation remains named and independent.

Existing checks: `tests.test_ci_workflows.TestCIWorkflows.test_authoritative_dependency_lock_fetch_contract`

<a id="fn-f45ad626ff4eea37"></a>

## `tests/test_ci_workflows.py::TestCIWorkflows.test_native_wheel_LF_materialization_rebuilds_cached_CRLF_index_fatally`

Execute the actual LF-materialization workflow script against a disposable native Git repository reproducing clean-index cached CRLF.

Preserve: All27 assertion call sites (including nested Git/index helpers) stay. Keep two literal LF script equality checks, native Windows Git-Bash resolution, sanitized GIT environment, executable mode/binary blobs, stale mtime/index reproduction and force-alone defect control. Same15s subprocess budgets; unchanged config/HEAD/tree/paths and failed source empty-index-before-write assertions.

Removal: Extract disposable Git fixture preparation/CRLF cache setup and one valid/missing/unavailable-source exercise with explicit arguments; retain the original public case and subTest labels.

Existing checks: `tests.test_ci_workflows.TestCIWorkflows.test_native_wheel_LF_materialization_rebuilds_cached_CRLF_index_fatally`

<a id="fn-b82c72e58e2031b7"></a>

## `tests/test_ci_workflows.py::TestCIWorkflows.test_privileged_dependency_snapshot_validator_matches_producer_contract`

Execute the actual pre-submission Bash validator against genuine producer-built four-platform snapshots, receipts and original ZIPs.

Preserve: All13 assertion sites stay and execute repeatedly across four success and16 negative fixtures. Preserve real dependency_snapshot producer calls and regular0600 archive metadata; distinct authoritative locks vs self-consistent forged candidates; current/prior attempt acceptance but future rejection; Windows newline acceptance; all pip/job/correlator/source/receipt/member/Intel archive and authoritative inventory failures. Every rejected set leaves validated output empty. No Python-only mirror of the extracted Bash validator.

Removal: Extract per-platform producer artifact assembly, one validator-run fixture and named mutation groups; retain the original case, success/negative subTests and assertions.

Existing checks: `tests.test_ci_workflows.TestCIWorkflows.test_privileged_dependency_snapshot_validator_matches_producer_contract`

<a id="fn-fc572cf9e6251363"></a>

## `tests/test_ci_workflows.py::_macos_release_build_policy_errors`

Validate exact four-host build/publication structure, fatal Mac gates and separate payload/proof archives.

Preserve: Retain early structural returns, error ordering, four exact runtime tuples, all guard/timeout/environment exclusions, fatal metadata/native/GUI ordering, unique archive paths/names, exact publisher predicate and four digest-mismatch-enforced downloads. Avoid a permissive normalized YAML validator that hides duplicate or injected steps.

Removal: Extract matrix/runtime policy, Mac step metadata/commands, architecture-specific artifact routing and publisher/download policy into finite validators that append to the same error list.

Existing checks: `tests.test_ci_workflows.TestCIWorkflows.test_release_preserves_digest_checks_without_deprecated_extraction`, `tests.test_ci_workflows.TestCIWorkflows.test_macos_release_policy_rejects_missing_lanes_or_bypassed_proofs`

<a id="fn-8d0821ca086b641e"></a>

## `tests/test_ci_workflows.py::_native_wheel_proposal_policy_errors`

Validate committed four-host proof workflow, source preflight, root selection and original archive routing.

Preserve: Retain literal prelude/source phase and headers, two checkout/LF instances, named step order/count, pinned actions/root-script SHA, event/ref/HEAD bounds, fatal stdlib test prefix, fresh aggregate parent and exact shlex command tails. Do not interpret always() here as the release validator does; this aggregate explicitly inspects matrix result.

Removal: Extract native/aggregate header policy, exact action and root-script policy, and producer/validator command policy. Keep outer ordered error accumulation and early missing-job return.

Existing checks: `tests.test_ci_workflows.TestCIWorkflows.test_native_wheel_proposals_bind_four_native_hosts_and_original_archives`, `tests.test_ci_workflows.TestCIWorkflows.test_native_wheel_proposal_policy_rejects_missing_or_bypassed_proofs`

<a id="fn-e26c9b765387d3ea"></a>

## `tests/test_ci_workflows.py::_run_existing_release_integrity`

Construct an isolated authenticated GET/strict-checksum fixture and execute the actual existing-release Bash step.

Preserve: Keep generated program bytes and shebangs, endpoint/header/GET argument rejection, selected-release asset binding, per-kind response state/call logs/failures, strict manifest parsing and forced checksum exit. Retain PATH isolation, native tool links, missing token/repository/tag/tool cases and exact cwd/capture. Do not replace literal executed Bash or embedded programs with calls to a mirror validator.

Removal: Extract response/payload materialization and finite fake-gh/fake-sha256sum fixture writers, leaving actual workflow extraction, environment assembly and Bash invocation in the owner.

Existing checks: `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_accepts_canonical_reordered_state`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_release_identity_and_state`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_harness_binds_assets_to_selected_release_id`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_asset_inventory_and_metadata`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_fails_closed_on_every_api_boundary`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_malformed_api_responses`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_each_failed_asset_download`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_download_size_and_digest_mismatch`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_noncanonical_manifests`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_metadata_and_manifest_triangle`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_propagates_strict_checksum_failure`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_rejects_snapshot_mutation`, `tests.test_ci_workflows.TestCIWorkflows.test_existing_release_integrity_requires_environment_and_tools`

<a id="fn-6bb4217efe913172"></a>

## `tests/test_gml_transpiler_architecture.py::_expression_boundary_bypasses_from_source`

Detect expression implementation, utility and legacy facade bypasses through direct/relative imports and attributes.

Preserve: The utility module and its named/wildcard imports have a distinct rule from implementation modules. Preserve aliases and existing explicit local cycle gateways.

Removal: Share only the exact AST facade-binding/attribute mechanics with the lexical scanner; keep each finite owner/name policy in its own scanner. Retain every existing expression bypass fixture.

Existing checks: `test_expression_boundary_scanner_rejects_every_bypass_form`, `test_expression_implementation_modules_have_no_external_bypasses`

<a id="fn-afc8b7787b44a928"></a>

## `tests/test_gml_transpiler_architecture.py::_lexical_boundary_bypasses_from_source`

Detect lexical owner/module/wildcard/private facade and aliased attribute bypasses without importing consumer source.

Preserve: Relative imports, alias prefixes and all legacy lexical facade names must still be checked; extracting a helper must not skip direct module edges.

Removal: Extract the exact facade-binding collection and attribute access scan into finite AST-only helpers. Retain lexical import policy here and all original bypass fixtures.

Existing checks: `test_lexical_boundary_scanner_rejects_private_and_module_bypasses`, `test_lexical_implementation_modules_have_no_external_bypasses`

<a id="fn-0f016ae884964633"></a>

## `tests/test_godot_validation.py::TestGodotProcessOwnership._run_fake`

Run the real Godot process owner against a borrowed fake process with directed reader, signal, ownership, setup and control errors.

Preserve: Group signal precedes reaping; fake reader release, observer close notes, original SIGCHLD policy and primary error identities must retain exact order. Module proxies must not patch process-global os behavior.

Removal: Extract the typed reader factory and individual fake-operation bindings into a dedicated fixture owner. Keep one original patch scope, real runner call and finally reader-release sequence. Preserve all existing process-ownership cases.

Existing checks: `TestGodotProcessOwnership`

<a id="fn-e504a2d7ca5faa51"></a>

## `tests/test_included_files_owner_architecture.py::assert_orchestration_boundary`

Reject direct filesystem writes/acquisition outside the Included Files operation owners using actual imported targets.

Preserve: Read-only source listing/open/close and the single driver mkdir are explicit exceptions. String/dataclass replace remains pure; alias/attribute resolution and write-open flag rejection cannot become leaf-name-only checks.

Removal: Extract import-binding collection and a finite recursive target resolver, then isolate one call policy check. Retain existing exact allowed operation sets and all negative bypass fixtures.

Existing checks: `test_complete_owner_graph_and_orchestration_boundaries`

<a id="fn-5eaf84f6fe5c6200"></a>

## `tests/test_native_wheel_proposals.py::TestNativeWheelProposals.test_actual_guardian_readiness_defers_result_reads_and_preserves_fatal_failures`

Exercise partial/withheld/missing real guardian result publication and prove reads wait for readiness.

Preserve: The literal subprocess fixture, stdin release handshake, no early result reads, bounded timeout, reaped process and closed stdin assertions are independent safety evidence. Preserve temporary module-family restoration and mode labels.

Removal: Extract the byte-exact guardian fixture writer and one per-mode test driver with a finite typed fixture state for acquired process/root/read observations. Keep all original assertions and actual subprocess execution; no modeled replacement.

Existing checks: `test_actual_guardian_readiness_defers_result_reads_and_preserves_fatal_failures`

<a id="fn-6013e6c02608a406"></a>

## `tests/test_release_publisher.py::ScriptedTransport._fault_result`

Produce deterministic tag/release/upload/publish transport faults with actual simulated mutation and streamed byte evidence.

Preserve: Some failures mutate remote state before losing the response. Keep owned/foreign IDs, draft versus public URLs, streamed size/digest, mutation timing and exact HTTP status distinctions; a generic error dictionary would hide these behaviors.

Removal: Split explicit fault dispatch into tag, release ownership, upload and final-publication helpers, retaining existing FaultKind coverage and terminal unknown-kind error. Keep transport sequence/ordinal and original mutation methods authoritative.

Existing checks: `test_failures_are_terminal_without_retry_adoption_or_foreign_mutation`, `test_intel_upload_failures_retain_only_validated_owned_prefix`
