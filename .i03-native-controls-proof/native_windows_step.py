"""I03 native Windows operations gate with exact selection and runtime checks."""

import inspect
import json
import platform
import sys
import unittest
from pathlib import Path

root = Path(sys.argv[1]).resolve()
venv = Path(sys.argv[2]).resolve()
assert Path.cwd().resolve() == root and Path(sys.prefix).resolve() == venv
assert Path(sys.executable).resolve() == (venv / "Scripts" / "python.exe").resolve()
assert (platform.python_version(), sys.platform, platform.machine()) == ("3.12.10", "win32", "AMD64")

from scripts.run_required_unittest import load_suite, result_is_allowed
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_files_parts.filesystem import open_validation_stream
from src.conversion.included_files_parts.windows_bindings import WindowsCleanupParentBinding
from src.conversion.included_files_parts.windows_operations import file_read_api, cleanup_parent_api, transaction_api
from tests.included_files.test_filesystem import TestIncludedFilesFilesystem
from tests.included_files.test_windows_bindings import TestIncludedFilesWindowsBindings
from tests.included_files.test_windows_operations import TestIncludedFilesWindowsOperations
from tests.test_included_files import TestIncludedFilesConverterOutputContainment, TestIncludedFilesManagedRootTransaction

origins = {
    load_suite: "scripts/run_required_unittest.py",
    result_is_allowed: "scripts/run_required_unittest.py",
    IncludedFilesConverter: "src/conversion/included_files.py",
    open_validation_stream: "src/conversion/included_files_parts/filesystem.py",
    WindowsCleanupParentBinding: "src/conversion/included_files_parts/windows_bindings.py",
    file_read_api: "src/conversion/included_files_parts/windows_operations.py",
    cleanup_parent_api: "src/conversion/included_files_parts/windows_operations.py",
    transaction_api: "src/conversion/included_files_parts/windows_operations.py",
    TestIncludedFilesFilesystem: "tests/included_files/test_filesystem.py",
    TestIncludedFilesWindowsBindings: "tests/included_files/test_windows_bindings.py",
    TestIncludedFilesWindowsOperations: "tests/included_files/test_windows_operations.py",
    TestIncludedFilesConverterOutputContainment: "tests/test_included_files.py",
    TestIncludedFilesManagedRootTransaction: "tests/test_included_files.py",
}
assert all(Path(inspect.getfile(inspect.unwrap(owner))).resolve() == root / path for owner, path in origins.items())
ids = (
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_abi_records_preserve_sizes_offsets_and_values",
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_cached_loaders_preserve_signatures_and_independent_lifetimes",
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_loaders_reject_non_windows_before_loading",
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_cleanup_loader_rejects_unsupported_layout_before_loading",
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_transaction_error_preserves_lookup_order_number_and_filename",
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_lock_file_preserves_one_byte_and_error_identity",
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_rename_preserves_refusal_fallback_native_flags_and_error",
    "tests.included_files.test_windows_operations.TestIncludedFilesWindowsOperations.test_native_windows_abi_and_write_through_rename",
    "tests.included_files.test_filesystem.TestIncludedFilesFilesystem.test_plain_validation_open_avoids_native_acquisition",
    "tests.included_files.test_filesystem.TestIncludedFilesFilesystem.test_posix_no_follow_transfers_fd_and_closes_wrapper_failure",
    "tests.included_files.test_filesystem.TestIncludedFilesFilesystem.test_windows_invalid_handles_preserve_error_without_close",
    "tests.included_files.test_filesystem.TestIncludedFilesFilesystem.test_windows_handle_transfer_failure_closes_native_handle_once",
    "tests.included_files.test_filesystem.TestIncludedFilesFilesystem.test_windows_stream_wrapper_failure_closes_only_transferred_fd",
    "tests.included_files.test_filesystem.TestIncludedFilesFilesystem.test_native_windows_validation_stream_closure_restores_write_access",
    "tests.included_files.test_windows_bindings.TestIncludedFilesWindowsBindings.test_open_refusals_precede_native_acquisition",
    "tests.included_files.test_windows_bindings.TestIncludedFilesWindowsBindings.test_rejected_verification_retains_primary_error_and_close_note",
    "tests.included_files.test_windows_bindings.TestIncludedFilesWindowsBindings.test_context_entry_and_exit_preserve_verification_and_error_order",
    "tests.included_files.test_windows_bindings.TestIncludedFilesWindowsBindings.test_close_clears_handle_before_native_call_and_never_retries",
    "tests.included_files.test_windows_bindings.TestIncludedFilesWindowsBindings.test_verify_preserves_short_circuit_order_and_closed_refusal",
    "tests.included_files.test_windows_bindings.TestIncludedFilesWindowsBindings.test_binding_argument_mismatch_precedes_verify",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_recovery_paths_reject_before_io",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_cleanup_parent_binding_blocks_relocation",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_cleanup_parent_binding_rejects_junction",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_noop_hashes_deny_concurrent_writes",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_readonly_backup_cleanup_leaves_no_debris",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_readonly_cleanup_recovers_after_process_exit",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_readonly_commit_failure_rolls_back_cleanly",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_readonly_cancellation_rolls_back_cleanly",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_managed_root_junction_is_rejected",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_nested_tree_junction_is_rejected",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_registry_directory_junction_is_rejected",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_stage_container_junction_is_rejected",
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_native_windows_backup_destination_junction_is_preserved",
    "tests.test_included_files.TestIncludedFilesConverterOutputContainment.test_native_windows_project_lock_blocks_root_relocation",
)
assert len(ids) == len(set(ids)) == 34
assert all(test_id.rsplit(".", 1)[1].startswith("test_") for test_id in ids)
suite, discovered = load_suite(ids)
assert discovered == ids
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert Path.cwd().resolve() == root and Path(sys.prefix).resolve() == venv
assert Path(sys.executable).resolve() == (venv / "Scripts" / "python.exe").resolve()
assert (platform.python_version(), sys.platform, platform.machine()) == ("3.12.10", "win32", "AMD64")
assert all(Path(inspect.getfile(inspect.unwrap(owner))).resolve() == root / path for owner, path in origins.items())
accepted = result.testsRun == 34 and result_is_allowed(result, {})
print(json.dumps({"gate": "I03-windows-operations", "python": sys.executable, "prefix": sys.prefix,
                  "root": str(root), "runtime": [platform.python_version(), sys.platform, platform.machine()],
                  "origins": sorted(set(origins.values())), "selected_ids": list(discovered),
                  "tests_run": result.testsRun, "skip_count": len(result.skipped), "accepted": accepted}, sort_keys=True))
raise SystemExit(0 if accepted else 1)
