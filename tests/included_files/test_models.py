"""Data-only Included Files records retain their construction and ownership rules."""

import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError, fields, replace
from unittest.mock import patch

from src.conversion.included_files_parts.models import (
    DeclaredIncludedFile,
    IncludedCommitMarker,
    IncludedCopyReceipt,
    IncludedFileConversionPlan,
    IncludedFileSource,
    IncludedGenerationContentReceipt,
    IncludedGenerationMatch,
    IncludedNoOpSourceReceipt,
    IncludedOutputSetCancelled,
    IncludedOutputSetTransaction,
    IncludedPayloadReceipt,
    IncludedProjectLock,
    IncludedRecoveryJournal,
    IncludedRecoveryRecordSizes,
    IncludedRegistrySnapshot,
    IncludedSourceBinding,
    IncludedTreeDescriptorBinding,
    IncludedTreeEntry,
    IncludedTreePathBinding,
    IncludedTreeSnapshot,
)

FINGERPRINT = (1, 2, 3, 4, 5, 6)
HANDLE = (*FINGERPRINT, 7)


def _transaction() -> IncludedOutputSetTransaction:
    tree = IncludedTreeSnapshot(FINGERPRINT, ())
    return IncludedOutputSetTransaction(
        (1, 2), "stage", (3, 4), tree, "root", tree, "registry", (5, 6), 0o600,
        b"registry", IncludedTreeSnapshot(None, ()), IncludedRegistrySnapshot(None, None, None, None),
    )


def _record_cases():
    source = IncludedFileSource("disk", "logical", "owner")
    binding = IncludedSourceBinding("disk", "canonical", (("directory", (1, 2)),), HANDLE, HANDLE, HANDLE)
    receipt = IncludedNoOpSourceReceipt("logical", "assigned", binding, 3, "digest")
    copy = IncludedCopyReceipt(IncludedPayloadReceipt(FINGERPRINT, 3, "digest"), FINGERPRINT, 7, HANDLE)
    return (
        (source, "filesystem_path relative_path owner_source_path"),
        (DeclaredIncludedFile("name", None, "owner", None), "name source_path owner_source_path manifest_field"),
        (IncludedFileConversionPlan(("logical",), (source,), ()), "requested_keys available_files skipped_keys"),
        (copy.payload, "source_fingerprint byte_count sha256"),
        (copy, "payload output_fingerprint output_ctime_ns output_handle_state"),
        (binding, "filesystem_path canonical_path directory_identities lexical_state path_state handle_state"),
        (receipt, "logical_path assigned_path binding byte_count sha256"),
        (IncludedGenerationMatch(True, (receipt,)), "unchanged source_receipts"),
        (IncludedGenerationContentReceipt("id", (1, 2), (3, 4), receipt, "staged", "public", copy),
         "transaction_id generation_identity stage_container_identity source staged_output_path public_output_path output"),
        (IncludedTreeEntry("a", "file", FINGERPRINT, None, None),
         "relative_path kind fingerprint ctime_ns content_sha256"),
        (IncludedTreeSnapshot(None, ()), "root_fingerprint entries"),
        (IncludedTreeDescriptorBinding(99, "a", FINGERPRINT, "display"), "parent_fd name fingerprint display_path"),
        (IncludedTreePathBinding("path", (1, 2)), "path identity"),
        (IncludedRegistrySnapshot(None, None, None, None), "directory_identity file_identity file_mode content"),
        (IncludedRecoveryRecordSizes(1, 2), "journal_bytes commit_bytes"),
        (_transaction(), "project_identity stage_container_path stage_container_identity staged_container_snapshot "
         "staged_root_path staged_root_snapshot staged_registry_path staged_registry_identity staged_registry_mode "
         "staged_registry_content previous_root_snapshot previous_registry_snapshot recovery_record_sizes "
         "publication_transaction_id content_receipts"),
        (IncludedRecoveryJournal(2, "id", _transaction(), "root", "registry", "directory", (1, 2), False),
         "format_version transaction_id transaction root_backup_path registry_backup_path registry_directory_path "
         "registry_directory_identity registry_directory_created"),
        (IncludedCommitMarker(2, "id", (1, 2), (3, 4), "root", (5, 6), (7, 8), "registry"),
         "format_version transaction_id project_identity root_identity root_snapshot_sha256 "
         "registry_directory_identity registry_identity registry_content_sha256"),
    )


class TestIncludedFileModels(unittest.TestCase):
    def test_records_preserve_fields_defaults_and_frozen_status(self) -> None:
        for record, names in _record_cases():
            with self.subTest(record=type(record).__name__):
                self.assertEqual(tuple(field.name for field in fields(record)), tuple(names.split()))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, names.split()[0], None)
        self.assertEqual(tuple(field.name for field in fields(IncludedProjectLock)),
                         ("file_descriptor", "path", "windows"))
        self.assertIsInstance(IncludedOutputSetCancelled("cancel"), Exception)

    def test_receipt_properties_and_transaction_equality_preserve_evidence(self) -> None:
        payload = IncludedPayloadReceipt(FINGERPRINT, 3, "digest")
        receipt = IncludedCopyReceipt(payload, FINGERPRINT, 9, HANDLE)
        self.assertIs(receipt.payload, payload)
        self.assertIs(receipt.source_fingerprint, FINGERPRINT)
        self.assertEqual((receipt.byte_count, receipt.sha256), (3, "digest"))
        self.assertIsNone(IncludedTreeSnapshot(None, ()).identity)
        self.assertEqual(IncludedTreeSnapshot(FINGERPRINT, ()).identity, (1, 2))
        transaction = _transaction()
        self.assertEqual((transaction.recovery_record_sizes, transaction.publication_transaction_id,
                          transaction.content_receipts), (None, None, ()))
        binding = IncludedSourceBinding("a", "a", (), HANDLE, HANDLE, HANDLE)
        source = IncludedNoOpSourceReceipt("a", "a", binding, 3, "digest")
        evidence = IncludedGenerationContentReceipt("id", (1, 2), (3, 4), source, "s", "p", receipt)
        updated = replace(transaction, recovery_record_sizes=IncludedRecoveryRecordSizes(1, 2),
                          publication_transaction_id="id", content_receipts=(evidence,))
        self.assertEqual(updated, transaction)
        self.assertEqual(repr(updated), repr(transaction))
        self.assertIs(updated.content_receipts[0], evidence)
        self.assertNotEqual(replace(transaction, staged_registry_content=b"changed"), transaction)

    def test_borrowed_bindings_and_lock_records_do_not_acquire_or_close(self) -> None:
        with tempfile.TemporaryFile() as stream:
            descriptor = stream.fileno()
            before = os.fstat(descriptor)
            with patch("os.open", side_effect=AssertionError("record acquired a descriptor")), \
                    patch("os.close", side_effect=AssertionError("record closed a borrowed descriptor")):
                binding = IncludedTreeDescriptorBinding(descriptor, "a", FINGERPRINT, "display")
                lock = IncludedProjectLock(descriptor, "lock", False)
                self.assertEqual(binding.parent_fd, descriptor)
                lock.path = "renamed"
                lock.windows = True
                self.assertEqual((lock.file_descriptor, lock.path, lock.windows), (descriptor, "renamed", True))
                del binding, lock
            self.assertEqual(os.fstat(descriptor), before)
