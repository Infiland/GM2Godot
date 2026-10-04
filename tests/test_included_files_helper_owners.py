"""Contracts for included-files helper ownership and operation boundaries."""

from __future__ import annotations

import ast
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.conversion.included_files_parts import (
    constants,
    models,
    path_validation,
    recovery_codec,
    stat_metadata,
)

_STDLIB_ROOTS = frozenset({
    "__future__", "base64", "binascii", "dataclasses", "hashlib", "json",
    "os", "posixpath", "stat", "typing",
})
_PARTS = "src.conversion.included_files_parts"


def project_dependencies(source: str, allowed: frozenset[str]) -> frozenset[str]:
    """Inspect all imports, including deferred ones, without importing source."""
    dependencies: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None or any(alias.name == "*" for alias in node.names):
                raise AssertionError("Relative/wildcard owner import")
            names = (
                [node.module + "." + alias.name for alias in node.names]
                if node.module == _PARTS
                else [node.module]
            )
        for name in names:
            if name.split(".", 1)[0] in _STDLIB_ROOTS:
                continue
            if name not in allowed:
                raise AssertionError("Unexpected owner dependency: " + name)
            dependencies.add(name)
    return frozenset(dependencies)


def sample_tree(relative_path: str = "payload.txt") -> models.IncludedTreeSnapshot:
    return models.IncludedTreeSnapshot(
        root_fingerprint=(1, 2, stat.S_IFDIR | 0o700, 0, 3, 1),
        entries=(models.IncludedTreeEntry(
            relative_path=relative_path,
            kind="file",
            fingerprint=(1, 4, stat.S_IFREG | 0o600, 7, 5, 1),
            ctime_ns=6,
            content_sha256="a" * 64,
        ),),
    )


class TestIncludedFilesHelperOwners(unittest.TestCase):
    def test_platform_path_rejection_precedes_metadata_and_performs_no_stat_io(self) -> None:
        tree = sample_tree("payload:stream")
        payload = recovery_codec.included_tree_snapshot_payload(tree)
        original_validator = stat_metadata.validated_included_tree_snapshot
        with (
            patch.object(stat_metadata, "validated_included_tree_snapshot", wraps=original_validator) as validate,
            patch.object(os, "stat", side_effect=AssertionError("Unexpected stat I/O")),
            patch.object(os, "lstat", side_effect=AssertionError("Unexpected lstat I/O")),
            patch.object(os, "fstat", side_effect=AssertionError("Unexpected fstat I/O")),
        ):
            with patch.object(os, "name", "nt"):
                with self.assertRaisesRegex(OSError, "Windows-ambiguous"):
                    recovery_codec.included_tree_snapshot_from_payload(payload, "tree")
            validate.assert_not_called()
            # A later operation observes the current platform, not an import-time choice.
            with patch.object(os, "name", "posix"):
                parsed = recovery_codec.included_tree_snapshot_from_payload(payload, "tree")
            self.assertEqual(parsed, tree)
            validate.assert_called_once()

    def test_late_output_observation_sees_mutation_and_preserves_borrowed_fd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "payload.bin"
            replacement = Path(directory) / "replacement.bin"
            output.write_bytes(b"original")
            replacement.write_bytes(b"replacement")
            if os.name == "posix":
                # The POSIX operation borrows a real directory descriptor.
                descriptor = os.open(directory, os.O_RDONLY)
                before = os.fstat(descriptor)
                observe = stat_metadata.included_output_state_at
                expected = observe(descriptor, output.name)

                def mutate_at_read(parent_fd: int, name: str) -> tuple[int, int] | None:
                    os.replace(replacement, output)
                    return observe(parent_fd, name)

                try:
                    with patch.object(stat_metadata, "included_output_state_at", side_effect=mutate_at_read) as read:
                        with self.assertRaisesRegex(OSError, "changed during publication"):
                            stat_metadata.verify_included_output_state_at(descriptor, output.name, expected)
                        read.assert_called_once_with(descriptor, output.name)
                    after = os.fstat(descriptor)
                    self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
                finally:
                    os.close(descriptor)
            else:
                # Native Windows uses the existing path observation; no directory-FD claim.
                observe_path = stat_metadata.included_output_state
                expected = observe_path(str(output))

                def mutate_at_path_read(path: str) -> tuple[int, int] | None:
                    os.replace(replacement, output)
                    return observe_path(path)

                with patch.object(stat_metadata, "included_output_state", side_effect=mutate_at_path_read) as read:
                    with self.assertRaisesRegex(OSError, "changed during publication"):
                        stat_metadata.verify_included_output_state(str(output), expected)
                    read.assert_called_once_with(str(output))
            self.assertEqual(output.read_bytes(), b"replacement")

    def test_v1_v2_round_trip_canonical_bytes_and_live_constants_cap(self) -> None:
        tree = sample_tree()
        serializer = recovery_codec.included_serialized_json_content
        versions = (
            (1, recovery_codec.included_tree_snapshot_payload(tree), b'{\n  "a": 1,\n  "format_version": 1,\n  "z": "\\u00e9"\n}\n'),
            (2, recovery_codec.included_compact_tree_snapshot_payload(tree), b'{"a":1,"format_version":2,"z":"\\u00e9"}\n'),
        )
        for version, tree_payload, canonical in versions:
            with self.subTest(version=version):
                parsed = recovery_codec.included_tree_snapshot_from_payload(tree_payload, "tree", format_version=version)
                self.assertEqual(parsed, tree)
                self.assertEqual(
                    recovery_codec.included_tree_snapshot_sha256(parsed, version),
                    recovery_codec.included_tree_snapshot_sha256(tree, version),
                )
                record = {"z": "\u00e9", "format_version": version, "a": 1}
                with patch.object(recovery_codec, "included_serialized_json_content", wraps=serializer) as render:
                    self.assertEqual(recovery_codec.included_recovery_record_content(record), canonical)
                    render.assert_called_once_with(record, compact=version == 2)
                self.assertEqual(json.loads(canonical), record)
                with patch.object(constants, "INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES", len(canonical)):
                    self.assertEqual(recovery_codec.included_recovery_record_content(record), canonical)
                with patch.object(constants, "INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES", len(canonical) - 1):
                    with self.assertRaisesRegex(OSError, "canonical size limit"):
                        recovery_codec.included_recovery_record_content(record)

    def test_real_owner_imports_have_only_the_reviewed_acyclic_edges(self) -> None:
        leaves = frozenset({_PARTS + ".models", _PARTS + ".constants"})
        allowed = (
            (models, frozenset[str]()),
            (constants, frozenset[str]()),
            (path_validation, leaves | {"src.conversion.included_file_registry"}),
            (stat_metadata, frozenset({_PARTS + ".models", "src.conversion.included_file_paths"})),
            (recovery_codec, leaves | {_PARTS + ".path_validation", _PARTS + ".stat_metadata"}),
        )
        rank = {models.__name__: 0, constants.__name__: 0, path_validation.__name__: 1,
                stat_metadata.__name__: 1, recovery_codec.__name__: 2}
        for owner, expected in allowed:
            with self.subTest(owner=owner.__name__):
                filename = owner.__file__
                assert filename is not None
                edges = project_dependencies(Path(filename).read_text(encoding="utf-8"), expected)
                self.assertEqual(edges, expected)
                for dependency in edges:
                    if dependency in rank:
                        self.assertLess(rank[dependency], rank[owner.__name__])
        for forbidden in (
            "from src.conversion import included_files",
            "from src.conversion.included_files_parts import stat_metadata",
            "from . import recovery_codec",
            "from src.conversion.included_files_parts.models import *",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(AssertionError):
                    project_dependencies(forbidden, leaves)
