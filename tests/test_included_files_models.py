"""Contracts for the included-files record and constant owners."""

from __future__ import annotations

import ast
import gc
import os
import pickle
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_type_hints

from src.conversion import included_file_paths, included_files, project_manifest, project_source_paths, type_defs
from src.conversion.included_files_parts import constants, models


# These are the exact finite aliases in the reviewed extraction proposal.
MODEL_ALIASES = (
    "IncludedFileSource", "DeclaredIncludedFile", "IncludedFileConversionPlan",
    "PathIdentity", "PathFingerprint", "PathHandleBinding", "HandleState",
    "IncludedSourceFingerprint", "IncludedSourceDirectoryIdentity", "IncludedCleanupFileState",
    "IncludedPayloadReceipt", "IncludedCopyReceipt", "IncludedSourceBinding",
    "IncludedNoOpSourceReceipt", "IncludedGenerationMatch", "IncludedGenerationContentReceipt",
    "IncludedTreeEntry", "IncludedTreeSnapshot", "IncludedTreeDescriptorBinding",
    "IncludedTreePathBinding", "IncludedRegistrySnapshot", "IncludedRecoveryRecordSizes",
    "IncludedOutputSetTransaction", "IncludedRecoveryJournal", "IncludedCommitMarker",
    "IncludedProjectLock", "IncludedOutputSetCancelled",
)
CONSTANT_ALIASES = (
    "INCLUDED_FILES_ROOT_NAME", "INCLUDED_FILES_STAGE_PREFIX", "INCLUDED_FILES_LOCK_NAME",
    "INCLUDED_FILES_LOCK_TEMP_PREFIX", "INCLUDED_FILES_LOCK_CLEANUP_PREFIX",
    "INCLUDED_FILES_JOURNAL_NAME", "INCLUDED_FILES_COMMIT_NAME",
    "INCLUDED_FILES_JOURNAL_TEMP_PREFIX", "INCLUDED_FILES_COMMIT_TEMP_PREFIX",
    "INCLUDED_FILES_STAGE_MARKER_NAME", "INCLUDED_FILES_CLEANUP_PREFIX",
    "INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION", "INCLUDED_FILES_RECOVERY_FORMAT_VERSION",
    "INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION", "INCLUDED_FILES_WORKER_WINDOW_MULTIPLIER",
    "INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES", "INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES",
    "INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS", "INCLUDED_FILES_RECOVERY_INTEGER_MAX",
    "INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256", "INCLUDED_FILES_LOCK_CONTENT",
)


def leaf_policy_violation(source: str, allowed_imports: frozenset[str]) -> str | None:
    """Enforce only the two landed dependency-free leaves, including relative backedges."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name not in allowed_imports for alias in node.names):
                return "import"
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in allowed_imports or any(alias.name == "*" for alias in node.names):
                return "import"
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in {"dataclass", "field"}:
                return "call"
    return None


class TestIncludedFilesModelsFirstSlice(unittest.TestCase):
    def test_facade_aliases_are_owner_objects_and_public_bindings_remain_original(self) -> None:
        for owner, names in ((models, MODEL_ALIASES), (constants, CONSTANT_ALIASES)):
            for name in names:
                with self.subTest(owner=owner.__name__, name=name):
                    self.assertIs(getattr(included_files, "_" + name), getattr(owner, name))
                    self.assertIs(getattr(owner, name), getattr(owner, "_" + name))
        self.assertEqual(included_files.IncludedFilesConverter.__module__, "src.conversion.included_files")
        self.assertEqual(included_files.IncludedFilesConverter.__qualname__, "IncludedFilesConverter")
        self.assertIs(getattr(included_files, "IncludedFilePathAssignment"), included_file_paths.IncludedFilePathAssignment)
        self.assertIs(getattr(included_files, "ProjectSourcePathError"), project_source_paths.ProjectSourcePathError)
        self.assertIs(getattr(included_files, "ResolvedProjectSourcePath"), project_source_paths.ResolvedProjectSourcePath)
        self.assertIs(getattr(included_files, "GameMakerProjectManifest"), project_manifest.GameMakerProjectManifest)
        self.assertIs(getattr(included_files, "ProjectManifestDiagnostic"), project_manifest.ProjectManifestDiagnostic)
        for name in ("ConversionRunning", "LogCallback", "ProgressCallback", "StrPath"):
            self.assertIs(getattr(included_files, name), getattr(type_defs, name))

    def test_private_reflection_annotations_properties_and_new_runtime_pickle_are_honest(self) -> None:
        fingerprint = (1, 2, 3, 4, 5, 6)
        payload = models.IncludedPayloadReceipt(fingerprint, 12, "digest")
        receipt = models.IncludedCopyReceipt(payload, fingerprint, 7, (1, 2, 3, 4, 5, 6, 7))
        self.assertEqual(type(receipt).__module__, "src.conversion.included_files_parts.models")
        self.assertEqual(type(receipt).__name__, "_IncludedCopyReceipt")
        self.assertEqual(type(receipt).__qualname__, "_IncludedCopyReceipt")
        self.assertTrue(repr(receipt).startswith("_IncludedCopyReceipt("))
        self.assertEqual(models.IncludedOutputSetCancelled.__module__, "src.conversion.included_files_parts.models")
        self.assertEqual(get_type_hints(models.IncludedCopyReceipt)["payload"], models.IncludedPayloadReceipt)
        prop = vars(models.IncludedCopyReceipt)["source_fingerprint"]
        assert isinstance(prop, property) and prop.fget is not None
        self.assertEqual(get_type_hints(prop.fget)["return"], models.IncludedSourceFingerprint)
        self.assertEqual((receipt.source_fingerprint, receipt.byte_count, receipt.sha256), (fingerprint, 12, "digest"))
        restored: object = pickle.loads(pickle.dumps(receipt))
        assert isinstance(restored, models.IncludedCopyReceipt)
        self.assertIs(type(restored), models.IncludedCopyReceipt)
        self.assertEqual(restored, receipt)

    def test_frozen_records_and_mutable_lock_do_not_take_ownership_of_borrowed_descriptor(self) -> None:
        with tempfile.TemporaryFile() as stream:
            descriptor = stream.fileno()
            before = os.fstat(descriptor)
            fingerprint = (before.st_dev, before.st_ino, before.st_mode,
                           before.st_nlink, before.st_size, before.st_mtime_ns)
            binding = models.IncludedTreeDescriptorBinding(descriptor, "borrowed", fingerprint, "display")
            with self.assertRaises(FrozenInstanceError):
                setattr(binding, "name", "replacement")
            lock = models.IncludedProjectLock(descriptor, "before", os.name == "nt")
            lock.path = "after"
            self.assertEqual(lock.path, "after")
            self.assertEqual(lock.file_descriptor, descriptor)
            del binding, lock
            gc.collect()
            after = os.fstat(descriptor)
            self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))

    def test_landed_leaves_have_no_facade_platform_or_io_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        parts = root / "src/conversion/included_files_parts"
        self.assertEqual((parts / "__init__.py").read_bytes(), b"")
        self.assertIsNone(leaf_policy_violation((parts / "models.py").read_text(encoding="utf-8"),
                                               frozenset({"__future__", "dataclasses"})))
        self.assertIsNone(leaf_policy_violation((parts / "constants.py").read_text(encoding="utf-8"), frozenset()))
        for source in (
            "from ..included_files import IncludedFilesConverter",
            "from .models import IncludedFileSource",
            "import os",
            "from pathlib import Path",
            "from dataclasses import *",
            "open('payload')",
            "__import__('os')",
        ):
            with self.subTest(source=source):
                self.assertIsNotNone(leaf_policy_violation(source, frozenset({"__future__", "dataclasses"})))


if __name__ == "__main__":
    unittest.main()
