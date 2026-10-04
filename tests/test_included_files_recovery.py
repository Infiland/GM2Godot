# pyright: reportPrivateUsage=false

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from typing import Callable
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion import included_files as included_files_module
from src.conversion.included_file_paths import plan_included_file_paths
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
    render_included_file_registry,
)
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_files_parts import (
    constants as _included_constants,
    file_publication as _included_file_publication,
    guarded_mutations as _included_mutations,
    locking as _included_locking,
    native_posix as _included_posix,
    native_windows as _included_windows,
    path_validation as _included_paths,
    phase_observer as _included_phases,
    publisher as _included_publisher,
    record_io as _included_records,
    record_lifecycle as _included_record_lifecycle,
    recorded_cleanup as _included_cleanup,
    recovery as _included_recovery,
    recovery_codec as _included_codec,
    source_snapshots as _included_snapshots,
    staging as _included_staging,
    stat_metadata as _included_metadata,
)
from tests import included_files_support as _included_support

_included_files_transaction_debris = _included_support.included_files_transaction_debris


class TestIncludedFilesManagedRootTransaction(_included_support.IncludedManagedRootFixture):
    def test_recovery_parsers_reject_ambiguous_json_types(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_record = _included_records.read_included_recovery_record(
            os.path.join(
                self.godot_dir,
                _included_constants.INCLUDED_FILES_JOURNAL_NAME,
            ),
            project_identity,
        )
        commit_record = _included_records.read_included_recovery_record(
            os.path.join(
                self.godot_dir,
                _included_constants.INCLUDED_FILES_COMMIT_NAME,
            ),
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed interruption did not preserve both records")
        journal_payload = dict(journal_record[1])
        commit_payload = dict(commit_record[1])
        journal = _included_codec.included_recovery_journal_from_payload(
            self.godot_dir,
            project_identity,
            journal_payload,
        )
        stage_identity = journal.transaction.stage_container_identity
        stage_payload = {
            "format_version": True,
            "state": "staging",
            "project_identity": list(project_identity),
            "stage_identity": list(stage_identity),
        }
        journal_with_invalid_backup_location = dict(journal_payload)
        journal_with_invalid_backup_location["registry_backup_location"] = []
        tree_with_invalid_kind = {
            "root_fingerprint": [
                1,
                2,
                stat.S_IFDIR | 0o700,
                0,
                0,
                1,
            ],
            "entries": [
                {
                    "relative_path": "payload.txt",
                    "kind": [],
                    "fingerprint": [
                        1,
                        3,
                        stat.S_IFREG | 0o600,
                        0,
                        0,
                        1,
                    ],
                    "ctime_ns": 0,
                    "content_sha256": hashlib.sha256(b"").hexdigest(),
                }
            ],
        }
        journal_payload["format_version"] = True
        commit_payload["format_version"] = True

        cases: tuple[tuple[str, Callable[[], object], str], ...] = (
            (
                "journal",
                lambda: _included_codec.included_recovery_journal_from_payload(
                    self.godot_dir,
                    project_identity,
                    journal_payload,
                ),
                "journal format version",
            ),
            (
                "commit-marker",
                lambda: _included_codec.included_commit_marker_and_journal_from_payload(
                    self.godot_dir,
                    commit_payload,
                    project_identity,
                ),
                "commit marker format version",
            ),
            (
                "stage-marker",
                lambda: _included_codec.included_stage_marker_matches(
                    stage_payload,
                    project_identity,
                    stage_identity,
                ),
                "stage marker format version",
            ),
            (
                "tree-kind",
                lambda: _included_codec.included_tree_snapshot_from_payload(
                    tree_with_invalid_kind,
                    "test tree",
                ),
                "tree kind",
            ),
            (
                "registry-backup-location",
                lambda: _included_codec.included_recovery_journal_from_payload(
                    self.godot_dir,
                    project_identity,
                    journal_with_invalid_backup_location,
                ),
                "registry recovery backup location",
            ),
        )
        for label, parse, error_pattern in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(OSError, error_pattern):
                    parse()

    def test_recovery_tree_parser_rejects_cross_device_entry(self) -> None:
        root_path = os.path.join(self.godot_dir, "included_files")
        os.makedirs(root_path)
        with open(os.path.join(root_path, "payload.txt"), "wb") as payload_file:
            payload_file.write(b"payload")
        snapshot = _included_snapshots.capture_included_tree(root_path)
        payload = _included_codec.included_tree_snapshot_payload(snapshot)
        entries = payload["entries"]
        self.assertIsInstance(entries, list)
        first_entry = entries[0]
        self.assertIsInstance(first_entry, dict)
        fingerprint = first_entry["fingerprint"]
        self.assertIsInstance(fingerprint, list)
        root_fingerprint = snapshot.root_fingerprint
        if root_fingerprint is None:
            self.fail("captured recovery test tree unexpectedly disappeared")
        fingerprint[0] = root_fingerprint[0] + 1

        with self.assertRaisesRegex(OSError, "cross-device"):
            _included_codec.included_tree_snapshot_from_payload(
                payload,
                "modeled cross-device tree",
            )

    def test_unknown_recovery_record_is_preserved_and_rejected(self) -> None:
        journal_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_JOURNAL_NAME,
        )
        unknown_content = b"user-owned recovery collision\n"
        with open(journal_path, "wb") as journal_file:
            journal_file.write(unknown_content)

        self._write("payload.txt", "payload")
        with self.assertRaisesRegex(
            OSError,
            "Invalid Included Files recovery record",
        ):
            self._converter(max_workers=1).convert_all()

        with open(journal_path, "rb") as journal_file:
            self.assertEqual(journal_file.read(), unknown_content)
        self.assertFalse(
            os.path.lexists(os.path.join(self.godot_dir, "included_files"))
        )
        os.unlink(journal_path)

    def test_oversized_stable_recovery_records_are_not_read_or_removed(
        self,
    ) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        for record_name in (
            _included_constants.INCLUDED_FILES_JOURNAL_NAME,
            _included_constants.INCLUDED_FILES_COMMIT_NAME,
        ):
            with self.subTest(record_name=record_name):
                record_path = os.path.join(self.godot_dir, record_name)
                with open(record_path, "wb") as record_file:
                    record_file.truncate(65)
                original_stat = os.lstat(record_path)
                with (
                    patch.object(
                        _included_constants,
                        'INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES',
                        64,
                    ),
                    patch.object(
                        _included_records,
                        'read_included_recovery_record_payload',
                        side_effect=AssertionError(
                            "oversized recovery payload was read"
                        ),
                    ) as payload_read,
                    self.assertRaisesRegex(OSError, "canonical size limit"),
                ):
                    _included_recovery.recover_included_output_set(
                        self.godot_dir,
                        project_identity,
                    )
                payload_read.assert_not_called()
                current_stat = os.lstat(record_path)
                self.assertEqual(
                    (current_stat.st_dev, current_stat.st_ino),
                    (original_stat.st_dev, original_stat.st_ino),
                )
                self.assertEqual(current_stat.st_size, 65)
                os.unlink(record_path)

    def test_oversized_canonical_recovery_temporaries_are_preserved_unread(
        self,
    ) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        temporary_paths = (
            os.path.join(
                self.godot_dir,
                _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + "a" * 16
                + ".tmp",
            ),
            os.path.join(
                self.godot_dir,
                _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "b" * 16
                + ".tmp",
            ),
        )
        original_identities: dict[str, tuple[int, int]] = {}
        for temporary_path in temporary_paths:
            with open(temporary_path, "wb") as temporary_file:
                temporary_file.truncate(65)
            temporary_stat = os.lstat(temporary_path)
            original_identities[temporary_path] = (
                temporary_stat.st_dev,
                temporary_stat.st_ino,
            )

        with (
            patch.object(
                _included_constants,
                'INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES',
                64,
            ),
            patch.object(
                _included_records,
                'read_included_recovery_record_payload',
                side_effect=AssertionError(
                    "oversized recovery payload was read"
                ),
            ) as payload_read,
        ):
            cleaned, warnings = (
                _included_recovery.cleanup_orphan_included_recovery_state(
                    self.godot_dir,
                    project_identity,
                )
            )

        self.assertEqual(cleaned, 0)
        payload_read.assert_not_called()
        for temporary_path in temporary_paths:
            with self.subTest(temporary_path=temporary_path):
                self.assertTrue(
                    any(temporary_path in warning for warning in warnings)
                )
                temporary_stat = os.lstat(temporary_path)
                self.assertEqual(
                    (temporary_stat.st_dev, temporary_stat.st_ino),
                    original_identities[temporary_path],
                )
                self.assertEqual(temporary_stat.st_size, 65)

    def test_oversized_recovery_tombstone_is_preserved_unread(self) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        tombstone_path = _included_paths.included_cleanup_tombstone_path(
            os.path.join(self.godot_dir, "temporary-record"),
            "c" * 32,
            "journal-temporary-record",
            "journal",
            expect_directory=False,
        )
        with open(tombstone_path, "wb") as tombstone_file:
            tombstone_file.truncate(65)
        original_stat = os.lstat(tombstone_path)

        with (
            patch.object(
                _included_constants,
                'INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES',
                64,
            ),
            patch.object(
                _included_records,
                'read_included_recovery_record_payload',
                side_effect=AssertionError(
                    "oversized recovery payload was read"
                ),
            ) as payload_read,
        ):
            cleaned, warnings = (
                _included_recovery.cleanup_orphan_included_recovery_state(
                    self.godot_dir,
                    project_identity,
                )
            )

        self.assertEqual(cleaned, 0)
        payload_read.assert_not_called()
        self.assertTrue(any(tombstone_path in warning for warning in warnings))
        current_stat = os.lstat(tombstone_path)
        self.assertEqual(
            (current_stat.st_dev, current_stat.st_ino),
            (original_stat.st_dev, original_stat.st_ino),
        )
        self.assertEqual(current_stat.st_size, 65)

    def test_generated_oversized_recovery_record_is_rejected_before_staging(
        self,
    ) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        destination_name = "oversized-recovery-record.json"
        temporary_prefix = ".oversized-recovery-record."
        original_names = set(os.listdir(self.godot_dir))

        with (
            patch.object(
                _included_constants,
                'INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES',
                64,
            ),
            self.assertRaisesRegex(
                OSError,
                "Generated Included Files recovery record.*size limit",
            ),
        ):
            _included_record_lifecycle.publish_included_recovery_record(
                self.godot_dir,
                project_identity,
                filename=destination_name,
                temporary_prefix=temporary_prefix,
                payload={
                    "format_version": (
                        _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                    ),
                    "state": "x" * 128,
                },
            )

        self.assertEqual(set(os.listdir(self.godot_dir)), original_names)

    def test_changed_generation_size_preflight_precedes_payload_staging(
        self,
    ) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")

        with (
            patch.object(
                _included_constants,
                'INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES',
                1024,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
            ) as create_stage,
            patch.object(
                _included_staging,
                'prepare_included_registry_directory',
            ) as prepare_registry,
            patch.object(
                _included_record_lifecycle,
                'publish_included_recovery_record',
            ) as publish_record,
            self.assertRaisesRegex(
                OSError,
                "preflight failed before payload staging",
            ),
        ):
            converter.convert_all()

        create_stage.assert_not_called()
        prepare_registry.assert_not_called()
        publish_record.assert_not_called()
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    def test_compact_tree_parser_is_strict_bounded_and_deterministic(
        self,
    ) -> None:
        snapshot = self._recovery_cleanup_snapshot("nested/payload.bin")
        compact_payload = (
            _included_codec.included_compact_tree_snapshot_payload(
                snapshot
            )
        )
        self.assertEqual(
            _included_codec.included_tree_snapshot_from_payload(
                compact_payload,
                "compact test tree",
                format_version=(
                    _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                ),
            ),
            snapshot,
        )
        record_payload = {
            "format_version": (
                _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION
            ),
            "state": "test",
            "tree": compact_payload,
        }
        content = _included_codec.included_recovery_record_content(
            record_payload
        )
        self.assertEqual(
            content,
            _included_codec.included_recovery_record_content(
                json.loads(content.decode("utf-8"))
            ),
        )
        self.assertNotIn(b"\n  ", content)

        malformed_payloads: list[list[object]] = []
        extra_column = json.loads(json.dumps(compact_payload))
        extra_column[1][0].append(None)
        malformed_payloads.append(extra_column)
        unknown_kind = json.loads(json.dumps(compact_payload))
        unknown_kind[1][0][1] = "directory"
        malformed_payloads.append(unknown_kind)
        short_integer = json.loads(json.dumps(compact_payload))
        short_integer[1][0][2][0] = "0" * 15
        malformed_payloads.append(short_integer)
        duplicate_path = json.loads(json.dumps(compact_payload))
        duplicate_path[1].append(list(duplicate_path[1][0]))
        malformed_payloads.append(duplicate_path)
        unsorted_paths = json.loads(json.dumps(compact_payload))
        unsorted_paths[1].reverse()
        malformed_payloads.append(unsorted_paths)

        for index, malformed_payload in enumerate(malformed_payloads):
            with (
                self.subTest(case=index),
                self.assertRaises(OSError),
            ):
                _included_codec.included_tree_snapshot_from_payload(
                    malformed_payload,
                    "compact test tree",
                    format_version=(
                        _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                    ),
                )

        with (
            patch.object(
                _included_constants,
                'INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES',
                len(snapshot.entries) - 1,
            ),
            self.assertRaisesRegex(OSError, "too many entries"),
        ):
            _included_codec.included_tree_snapshot_from_payload(
                compact_payload,
                "compact test tree",
                format_version=(
                    _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                ),
            )

    def test_changed_ten_thousand_entry_preflight_stays_below_cap(
        self,
    ) -> None:
        logical_paths = tuple(
            f"entry-{index:05d}.txt" for index in range(10_000)
        )
        assignments = plan_included_file_paths(logical_paths)
        receipts = {
            path: (
                1,
                _included_constants.INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256,
            )
            for path in logical_paths
        }
        registry_content = render_included_file_registry(
            assignments,
            set(logical_paths),
            receipts,
        ).encode("utf-8")
        assigned_byte_counts = {
            assignment.assigned_output_path: 1
            for assignment in assignments
        }
        project_identity = (1, 2)
        (
            _stage_identity,
            _container_snapshot,
            previous_root_snapshot,
            _registry_identity,
            _registry_mode,
        ) = _included_codec.included_preflight_placeholder_snapshots(
            project_identity,
            assigned_byte_counts,
            registry_content,
        )
        previous_registry_snapshot = (
            included_files_module._IncludedRegistrySnapshot(
                directory_identity=(1, 10),
                file_identity=(1, 11),
                file_mode=0o600,
                content=registry_content,
            )
        )

        first_sizes = (
            _included_codec.preflight_included_recovery_record_sizes(
                self.godot_dir,
                project_identity,
                assigned_byte_counts,
                registry_content,
                previous_root_snapshot,
                previous_registry_snapshot,
            )
        )
        second_sizes = (
            _included_codec.preflight_included_recovery_record_sizes(
                self.godot_dir,
                project_identity,
                assigned_byte_counts,
                registry_content,
                previous_root_snapshot,
                previous_registry_snapshot,
            )
        )
        expected_sizes = included_files_module._IncludedRecoveryRecordSizes(
            journal_bytes=13_865_860,
            commit_bytes=13_866_493,
        )
        self.assertEqual(first_sizes, expected_sizes)
        self.assertEqual(second_sizes, expected_sizes)
        self.assertLess(
            expected_sizes.commit_bytes,
            _included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        )

    def test_scale_gate_skip_flag_fails_outside_github_actions(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "GM2GODOT_SKIP_WINDOWS_INCLUDED_FILES_SCALE_GATE": "1",
                    "GITHUB_ACTIONS": "",
                },
            ),
            self.assertRaisesRegex(
                AssertionError,
                "may only be skipped by its paired GitHub Actions job",
            ),
        ):
            self._enforce_windows_included_files_scale_gate_environment()

    def test_scale_gate_skip_flag_skips_inside_github_actions(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "GM2GODOT_SKIP_WINDOWS_INCLUDED_FILES_SCALE_GATE": "1",
                    "GITHUB_ACTIONS": "true",
                },
            ),
            self.assertRaisesRegex(
                unittest.SkipTest,
                "dedicated native Windows Included Files scale job",
            ),
        ):
            self._enforce_windows_included_files_scale_gate_environment()

    def test_scale_gate_require_flag_rejects_skip(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "GM2GODOT_REQUIRE_WINDOWS_INCLUDED_FILES_SCALE_GATE": "1",
                    "GM2GODOT_SKIP_WINDOWS_INCLUDED_FILES_SCALE_GATE": "1",
                    "GITHUB_ACTIONS": "true",
                },
            ),
            self.assertRaisesRegex(
                AssertionError,
                "required Included Files scale gate cannot be skipped",
            ),
        ):
            self._enforce_windows_included_files_scale_gate_environment()

    def test_scale_gate_require_flag_fails_outside_github_actions(
        self,
    ) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "GM2GODOT_REQUIRE_WINDOWS_INCLUDED_FILES_SCALE_GATE": "1",
                    "GITHUB_ACTIONS": "",
                },
            ),
            self.assertRaisesRegex(
                AssertionError,
                "may only be required by GitHub Actions",
            ),
        ):
            self._enforce_windows_included_files_scale_gate_environment()

    def test_ten_thousand_entry_compact_records_publish_and_recover_below_cap(
        self,
    ) -> None:
        self._enforce_windows_included_files_scale_gate_environment()
        entry_count = 10_000
        for index in range(entry_count):
            with open(
                os.path.join(
                    self.datafiles_dir,
                    f"entry-{index:05d}.txt",
                ),
                "wb",
            ) as source_file:
                source_file.write(b"x")

        captured_sizes: (
            included_files_module._IncludedRecoveryRecordSizes | None
        ) = None
        original_commit = _included_publisher.commit_included_output_set

        def capture_commit(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal captured_sizes
            captured_sizes = transaction.recovery_record_sizes
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        def interrupt_after_commit(phase: str) -> None:
            if phase == "generation-committed":
                raise OSError("simulated committed interruption")

        with (
            patch.object(
                _included_publisher,
                'commit_included_output_set',
                side_effect=capture_commit,
            ),
            patch.object(
                _included_phases,
                'after_included_transaction_phase',
                side_effect=interrupt_after_commit,
            ),
            self.assertRaisesRegex(
                OSError,
                "simulated committed interruption",
            ),
        ):
            self._converter(max_workers=4).convert_all()

        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_JOURNAL_NAME,
        )
        commit_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_COMMIT_NAME,
        )
        journal_record = _included_records.read_included_recovery_record(
            journal_path,
            project_identity,
        )
        commit_record = _included_records.read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed generation did not retain both records")
        self.assertEqual(
            journal_record[1]["format_version"],
            _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        )
        self.assertEqual(
            commit_record[1]["format_version"],
            _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        )
        actual_sizes = included_files_module._IncludedRecoveryRecordSizes(
            journal_bytes=os.path.getsize(journal_path),
            commit_bytes=os.path.getsize(commit_path),
        )
        self.assertEqual(captured_sizes, actual_sizes)
        self.assertEqual(
            actual_sizes,
            included_files_module._IncludedRecoveryRecordSizes(
                journal_bytes=8_138_698,
                commit_bytes=8_139_331,
            ),
        )
        self.assertLess(
            actual_sizes.journal_bytes,
            _included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        )
        self.assertLess(
            actual_sizes.commit_bytes,
            _included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        )

        project_lock = _included_locking.acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            recovery_message = (
                _included_recovery.recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            )
        finally:
            _included_locking.release_included_project_lock(
                project_lock
            )
        self.assertIsNotNone(recovery_message)
        self.assertEqual(
            len(
                os.listdir(
                    os.path.join(self.godot_dir, "included_files")
                )
            ),
            entry_count,
        )
        with open(
            os.path.join(
                self.godot_dir,
                "included_files",
                "entry-00000.txt",
            ),
            "rb",
        ) as output_file:
            self.assertEqual(output_file.read(), b"x")
        self._assert_no_transaction_debris()

    def test_recovery_record_staging_syncs_parent_before_durable_phase(
        self,
    ) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        events: list[tuple[str, str]] = []
        original_sync = _included_posix.sync_included_directory

        def trace_sync(path: str, expected_identity: tuple[int, int]) -> None:
            events.append(("sync", path))
            original_sync(path, expected_identity)

        def trace_phase(phase: str) -> None:
            events.append(("phase", phase))

        with (
            patch.object(
                _included_posix,
                'sync_included_directory',
                side_effect=trace_sync,
            ),
            patch.object(
                _included_phases,
                'after_included_transaction_phase',
                side_effect=trace_phase,
            ),
        ):
            _included_record_lifecycle.publish_included_recovery_record(
                self.godot_dir,
                project_identity,
                filename="test-recovery-record.json",
                temporary_prefix=".test-recovery-record.",
                payload={"state": "test"},
                staged_phase="journal-record-staged",
            )

        self.assertEqual(
            events,
            [
                ("sync", self.godot_dir),
                ("phase", "journal-record-staged"),
                ("sync", self.godot_dir),
            ],
        )

    def test_subprocess_interruption_recovers_every_publication_boundary(
        self,
    ) -> None:
        phases = (
            ("journal-record-staged", False),
            ("journal-prepared", False),
            ("previous-root-backed-up", False),
            ("new-root-published", False),
            ("previous-registry-backed-up", False),
            ("new-registry-published", False),
            ("commit-record-staged", False),
            ("generation-committed", True),
            ("journal-removed", True),
            ("commit-marker-removed", True),
        )
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import phase_observer as included_phase_observer
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path, requested_phase = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == requested_phase:
        os._exit(86)

included_phase_observer.after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""

        def pair_snapshot(project_path: str) -> tuple[int, dict[str, bytes], int, bytes]:
            root_path = os.path.join(project_path, "included_files")
            registry_path = os.path.join(
                project_path,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            )
            files: dict[str, bytes] = {}
            for directory, _subdirectories, filenames in os.walk(root_path):
                for filename in filenames:
                    file_path = os.path.join(directory, filename)
                    relative_path = os.path.relpath(
                        file_path,
                        root_path,
                    ).replace(os.sep, "/")
                    with open(file_path, "rb") as output_file:
                        files[relative_path] = output_file.read()
            with open(registry_path, "rb") as registry_file:
                registry_content = registry_file.read()
            return (
                os.lstat(root_path).st_ino,
                files,
                os.lstat(registry_path).st_ino,
                registry_content,
            )

        for phase, committed in phases:
            with self.subTest(phase=phase):
                with (
                    tempfile.TemporaryDirectory() as gm_path,
                    tempfile.TemporaryDirectory() as godot_path,
                ):
                    datafiles_path = os.path.join(gm_path, "datafiles")
                    os.mkdir(datafiles_path)
                    old_source_path = os.path.join(datafiles_path, "old.txt")
                    with open(old_source_path, "wb") as source_file:
                        source_file.write(b"old generation")
                    converter = IncludedFilesConverter(
                        gm_path,
                        godot_path,
                        log_callback=lambda _message: None,
                        progress_callback=lambda _value: None,
                        conversion_running=lambda: True,
                        max_workers=1,
                    )
                    converter.convert_all()
                    previous_pair = pair_snapshot(godot_path)

                    os.unlink(old_source_path)
                    with open(
                        os.path.join(datafiles_path, "new.txt"),
                        "wb",
                    ) as source_file:
                        source_file.write(b"new generation")

                    environment = os.environ.copy()
                    existing_python_path = environment.get("PYTHONPATH")
                    environment["PYTHONPATH"] = (
                        PROJECT_ROOT
                        if not existing_python_path
                        else PROJECT_ROOT + os.pathsep + existing_python_path
                    )
                    interrupted = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            interruption_script,
                            gm_path,
                            godot_path,
                            phase,
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )
                    self.assertEqual(
                        interrupted.returncode,
                        86,
                        interrupted.stdout + interrupted.stderr,
                    )
                    if phase == "journal-record-staged":
                        self.assertFalse(
                            os.path.lexists(
                                os.path.join(
                                    godot_path,
                                    _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                                )
                            )
                        )
                        journal_temporaries = [
                            name
                            for name in os.listdir(godot_path)
                            if name.startswith(
                                _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                            )
                            and name.endswith(".tmp")
                        ]
                        self.assertEqual(len(journal_temporaries), 1)
                        stages = [
                            name
                            for name in os.listdir(godot_path)
                            if name.startswith(
                                _included_constants.INCLUDED_FILES_STAGE_PREFIX
                            )
                            and name.endswith(".stage")
                        ]
                        self.assertEqual(len(stages), 1)
                        self.assertNotEqual(
                            os.listdir(os.path.join(godot_path, stages[0])),
                            [],
                        )

                    project_identity = (
                        _included_file_publication.ensure_included_output_project_root(
                            godot_path
                        )
                    )
                    project_lock = (
                        _included_locking.acquire_included_project_lock(
                            godot_path,
                            project_identity,
                        )
                    )
                    try:
                        recovery_message = (
                            _included_recovery.recover_included_output_set(
                                godot_path,
                                project_identity,
                            )
                        )
                    finally:
                        _included_locking.release_included_project_lock(
                            project_lock
                        )
                    if phase == "journal-record-staged":
                        self.assertIsNotNone(recovery_message)
                        assert recovery_message is not None
                        self.assertIn(
                            "durable journal temporary",
                            recovery_message,
                        )

                    recovered_pair = pair_snapshot(godot_path)
                    if committed:
                        self.assertEqual(
                            recovered_pair[1],
                            {"new.txt": b"new generation"},
                        )
                        self.assertIn(b'"logical_path": "new.txt"', recovered_pair[3])
                        self.assertNotIn(b'"logical_path": "old.txt"', recovered_pair[3])
                    else:
                        self.assertEqual(recovered_pair, previous_pair)

                    self.assertEqual(
                        _included_files_transaction_debris(godot_path),
                        (),
                    )

                    converter.convert_all()
                    self.assertEqual(
                        pair_snapshot(godot_path)[1],
                        {"new.txt": b"new generation"},
                    )

    def test_format_v1_records_recover_at_every_publication_boundary(
        self,
    ) -> None:
        phases = (
            ("journal-record-staged", False),
            ("journal-prepared", False),
            ("previous-root-backed-up", False),
            ("new-root-published", False),
            ("previous-registry-backed-up", False),
            ("new-registry-published", False),
            ("commit-record-staged", False),
            ("generation-committed", True),
            ("journal-removed", True),
            ("commit-marker-removed", True),
        )
        for phase, committed in phases:
            with (
                self.subTest(phase=phase),
                tempfile.TemporaryDirectory() as gm_path,
                tempfile.TemporaryDirectory() as godot_path,
            ):
                datafiles_path = os.path.join(gm_path, "datafiles")
                os.mkdir(datafiles_path)
                old_source_path = os.path.join(datafiles_path, "old.txt")
                with open(old_source_path, "wb") as source_file:
                    source_file.write(b"old generation")
                converter = IncludedFilesConverter(
                    gm_path,
                    godot_path,
                    log_callback=lambda _message: None,
                    progress_callback=lambda _value: None,
                    conversion_running=lambda: True,
                    max_workers=1,
                )
                converter.convert_all()
                os.unlink(old_source_path)
                with open(
                    os.path.join(datafiles_path, "new.txt"),
                    "wb",
                ) as source_file:
                    source_file.write(b"new generation")

                interrupted = self._run_interrupted_conversion(
                    phase,
                    gm_path=gm_path,
                    godot_path=godot_path,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )
                project_identity = (
                    _included_file_publication.ensure_included_output_project_root(
                        godot_path
                    )
                )
                rewritten = self._rewrite_included_recovery_records_as_v1(
                    godot_path,
                    project_identity,
                )
                if phase == "commit-marker-removed":
                    self.assertEqual(rewritten, 0)
                else:
                    self.assertGreaterEqual(rewritten, 1)

                project_lock = (
                    _included_locking.acquire_included_project_lock(
                        godot_path,
                        project_identity,
                    )
                )
                try:
                    _included_recovery.recover_included_output_set(
                        godot_path,
                        project_identity,
                    )
                finally:
                    _included_locking.release_included_project_lock(
                        project_lock
                    )

                root_path = os.path.join(godot_path, "included_files")
                observed_files: dict[str, bytes] = {}
                for directory, _subdirectories, filenames in os.walk(
                    root_path
                ):
                    for filename in filenames:
                        file_path = os.path.join(directory, filename)
                        relative_path = os.path.relpath(
                            file_path,
                            root_path,
                        ).replace(os.sep, "/")
                        with open(file_path, "rb") as output_file:
                            observed_files[relative_path] = output_file.read()
                self.assertEqual(
                    observed_files,
                    (
                        {"new.txt": b"new generation"}
                        if committed
                        else {"old.txt": b"old generation"}
                    ),
                )
                self.assertEqual(
                    _included_files_transaction_debris(godot_path),
                    (),
                )

    def test_first_publication_recovers_durable_prepared_journal_temporary(
        self,
    ) -> None:
        self._write("first.txt", "first generation")
        root_path = os.path.join(self.godot_dir, "included_files")
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(registry_path)

        interrupted = self._run_interrupted_conversion(
            "journal-record-staged"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertFalse(os.path.lexists(root_path))
        self.assertTrue(os.path.isdir(registry_directory))
        self.assertFalse(os.path.lexists(registry_path))
        self.assertEqual(
            len(
                [
                    name
                    for name in os.listdir(self.godot_dir)
                    if name.startswith(
                        _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                    )
                    and name.endswith(".tmp")
                ]
            ),
            1,
        )

        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        project_lock = _included_locking.acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            recovery_message = (
                _included_recovery.recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            )
        finally:
            _included_locking.release_included_project_lock(project_lock)

        self.assertIsNotNone(recovery_message)
        self.assertIn("durable journal temporary", recovery_message or "")
        self.assertFalse(os.path.lexists(root_path))
        self.assertFalse(os.path.lexists(registry_directory))
        self._assert_no_transaction_debris()

    def test_first_publication_journal_temporary_preserves_appeared_registry(
        self,
    ) -> None:
        self._write("first.txt", "first generation")
        interrupted = self._run_interrupted_conversion(
            "journal-record-staged"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        journal_temporary_path = os.path.join(
            self.godot_dir,
            next(
                name
                for name in os.listdir(self.godot_dir)
                if name.startswith(
                    _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                )
                and name.endswith(".tmp")
            ),
        )
        journal_temporary_stat = os.lstat(journal_temporary_path)
        journal_temporary_identity = (
            journal_temporary_stat.st_dev,
            journal_temporary_stat.st_ino,
        )
        with open(journal_temporary_path, "rb") as journal_temporary_file:
            journal_temporary_content = journal_temporary_file.read()

        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        unknown_registry_content = b"user-owned registry collision\n"
        with open(registry_path, "wb") as registry_file:
            registry_file.write(unknown_registry_content)
        unknown_registry_stat = os.lstat(registry_path)
        unknown_registry_identity = (
            unknown_registry_stat.st_dev,
            unknown_registry_stat.st_ino,
        )

        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        project_lock = _included_locking.acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            recovery_message = (
                _included_recovery.recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            )
        finally:
            _included_locking.release_included_project_lock(project_lock)

        self.assertIn(
            "ambiguous Included Files journal temporary was preserved",
            recovery_message or "",
        )
        current_journal_temporary_stat = os.lstat(journal_temporary_path)
        self.assertEqual(
            (
                current_journal_temporary_stat.st_dev,
                current_journal_temporary_stat.st_ino,
            ),
            journal_temporary_identity,
        )
        with open(journal_temporary_path, "rb") as journal_temporary_file:
            self.assertEqual(
                journal_temporary_file.read(),
                journal_temporary_content,
            )
        current_registry_stat = os.lstat(registry_path)
        self.assertEqual(
            (current_registry_stat.st_dev, current_registry_stat.st_ino),
            unknown_registry_identity,
        )
        with open(registry_path, "rb") as registry_file:
            self.assertEqual(registry_file.read(), unknown_registry_content)

    def test_restart_rollback_syncs_registry_before_journal_retirement(
        self,
    ) -> None:
        self._write("old.txt", "old generation")
        self._converter(max_workers=1).convert_all()
        previous_pair = self._pair_snapshot()
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        registry_directory_stat = os.lstat(registry_directory)
        registry_directory_identity = (
            registry_directory_stat.st_dev,
            registry_directory_stat.st_ino,
        )

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        interrupted = self._run_interrupted_conversion(
            "new-registry-published"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )

        events: list[tuple[str, str, tuple[int, int] | None]] = []
        original_sync = _included_posix.sync_included_directory
        original_remove = _included_record_lifecycle.remove_included_recovery_record

        def trace_sync(path: str, expected_identity: tuple[int, int]) -> None:
            if os.path.abspath(path) == registry_directory:
                events.append(("sync", path, expected_identity))
            original_sync(path, expected_identity)

        def trace_remove(
            path: str,
            identity: tuple[int, int],
            project_path: str,
            project_identity: tuple[int, int],
        ) -> None:
            if os.path.basename(path) == (
                _included_constants.INCLUDED_FILES_JOURNAL_NAME
            ):
                events.append(("remove", path, identity))
            original_remove(
                path,
                identity,
                project_path,
                project_identity,
            )

        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        with (
            patch.object(
                _included_posix,
                'sync_included_directory',
                side_effect=trace_sync,
            ),
            patch.object(
                _included_record_lifecycle,
                'remove_included_recovery_record',
                side_effect=trace_remove,
            ),
        ):
            project_lock = _included_locking.acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                recovery_message = (
                    _included_recovery.recover_included_output_set(
                        self.godot_dir,
                        project_identity,
                    )
                )
            finally:
                _included_locking.release_included_project_lock(
                    project_lock
                )

        self.assertIn("rolled back", recovery_message or "")
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(events[0], ("sync", registry_directory, registry_directory_identity))
        self.assertEqual(events[1][0], "remove")
        self._assert_no_transaction_debris()

    def test_committed_cleanup_recovery_is_idempotent_at_every_owned_boundary(
        self,
    ) -> None:
        boundaries = (
            ("root-backup", "quarantined", None),
            ("root-backup", "removed", None),
            ("registry-backup", "quarantined", None),
            ("registry-backup", "removed", None),
            ("stage", "quarantined", None),
            ("stage", "removed", None),
            (
                "record",
                "quarantined",
                _included_constants.INCLUDED_FILES_JOURNAL_NAME,
            ),
            (
                "record",
                "removed",
                _included_constants.INCLUDED_FILES_JOURNAL_NAME,
            ),
            (
                "record",
                "quarantined",
                _included_constants.INCLUDED_FILES_COMMIT_NAME,
            ),
            (
                "record",
                "removed",
                _included_constants.INCLUDED_FILES_COMMIT_NAME,
            ),
        )
        commit_interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import phase_observer as included_phase_observer
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "generation-committed":
        os._exit(86)

included_phase_observer.after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""
        cleanup_interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import file_publication as included_file_publication
from src.conversion.included_files_parts import locking as included_locking
from src.conversion.included_files_parts import recovery as included_recovery
from src.conversion.included_files_parts import phase_observer as included_phase_observer

godot_path, requested_role, requested_action, requested_path = sys.argv[1:]
matches = 0

def stop_after_phase(phase: str) -> None:
    global matches
    parts = phase.split(":", 3)
    if len(parts) != 4 or parts[0] != "cleanup":
        return
    _cleanup, role, relative_path, action = parts
    if role != requested_role or action != requested_action:
        return
    if requested_path != "-" and relative_path != requested_path:
        return
    matches += 1
    if matches == 1:
        os._exit(86)

included_phase_observer.after_included_transaction_phase = stop_after_phase
project_identity = included_file_publication.ensure_included_output_project_root(
    godot_path
)
project_lock = included_locking.acquire_included_project_lock(
    godot_path,
    project_identity,
)
try:
    included_recovery.recover_included_output_set(
        godot_path,
        project_identity,
    )
finally:
    included_locking.release_included_project_lock(project_lock)
"""

        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )

        def pair_snapshot(
            project_path: str,
        ) -> tuple[int, dict[str, bytes], int, bytes]:
            root_path = os.path.join(project_path, "included_files")
            registry_path = os.path.join(
                project_path,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            )
            files: dict[str, bytes] = {}
            for directory, _subdirectories, filenames in os.walk(root_path):
                for filename in filenames:
                    file_path = os.path.join(directory, filename)
                    relative_path = os.path.relpath(
                        file_path,
                        root_path,
                    ).replace(os.sep, "/")
                    with open(file_path, "rb") as output_file:
                        files[relative_path] = output_file.read()
            with open(registry_path, "rb") as registry_file:
                registry_content = registry_file.read()
            return (
                os.lstat(root_path).st_ino,
                files,
                os.lstat(registry_path).st_ino,
                registry_content,
            )

        def recover(project_path: str) -> str | None:
            project_identity = (
                _included_file_publication.ensure_included_output_project_root(
                    project_path
                )
            )
            project_lock = _included_locking.acquire_included_project_lock(
                project_path,
                project_identity,
            )
            try:
                return _included_recovery.recover_included_output_set(
                    project_path,
                    project_identity,
                )
            finally:
                _included_locking.release_included_project_lock(
                    project_lock
                )

        for role, action, relative_path in boundaries:
            label = relative_path or role
            with self.subTest(role=role, action=action, path=label):
                with (
                    tempfile.TemporaryDirectory() as gm_path,
                    tempfile.TemporaryDirectory() as godot_path,
                ):
                    datafiles_path = os.path.join(gm_path, "datafiles")
                    os.mkdir(datafiles_path)
                    old_source_path = os.path.join(datafiles_path, "old.txt")
                    with open(old_source_path, "wb") as source_file:
                        source_file.write(b"old generation")
                    converter = IncludedFilesConverter(
                        gm_path,
                        godot_path,
                        log_callback=lambda _message: None,
                        progress_callback=lambda _value: None,
                        conversion_running=lambda: True,
                        max_workers=1,
                    )
                    converter.convert_all()

                    os.unlink(old_source_path)
                    with open(
                        os.path.join(datafiles_path, "new.txt"),
                        "wb",
                    ) as source_file:
                        source_file.write(b"new generation")

                    committed = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            commit_interruption_script,
                            gm_path,
                            godot_path,
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )
                    self.assertEqual(
                        committed.returncode,
                        86,
                        committed.stdout + committed.stderr,
                    )
                    committed_pair = pair_snapshot(godot_path)
                    self.assertEqual(
                        committed_pair[1],
                        {"new.txt": b"new generation"},
                    )

                    interrupted_cleanup = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            cleanup_interruption_script,
                            godot_path,
                            role,
                            action,
                            relative_path or "-",
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )
                    self.assertEqual(
                        interrupted_cleanup.returncode,
                        86,
                        interrupted_cleanup.stdout
                        + interrupted_cleanup.stderr,
                    )

                    recover(godot_path)
                    self.assertEqual(
                        pair_snapshot(godot_path),
                        committed_pair,
                    )
                    self.assertEqual(
                        _included_files_transaction_debris(godot_path),
                        (),
                    )

                    self.assertIsNone(recover(godot_path))
                    self.assertEqual(
                        pair_snapshot(godot_path),
                        committed_pair,
                    )
                    self.assertEqual(
                        _included_files_transaction_debris(godot_path),
                        (),
                    )

    def test_committed_cleanup_preserves_unknown_content_inside_recorded_trees(
        self,
    ) -> None:
        locations = ("root-backup", "stage")

        for location in locations:
            with self.subTest(location=location):
                with (
                    tempfile.TemporaryDirectory() as gm_path,
                    tempfile.TemporaryDirectory() as godot_path,
                ):
                    datafiles_path = os.path.join(gm_path, "datafiles")
                    os.mkdir(datafiles_path)
                    old_source_path = os.path.join(datafiles_path, "old.txt")
                    with open(old_source_path, "wb") as source_file:
                        source_file.write(b"old generation")
                    converter = IncludedFilesConverter(
                        gm_path,
                        godot_path,
                        log_callback=lambda _message: None,
                        progress_callback=lambda _value: None,
                        conversion_running=lambda: True,
                        max_workers=1,
                    )
                    converter.convert_all()

                    unrelated_path = os.path.join(
                        godot_path,
                        "user-project-sentinel.txt",
                    )
                    with open(unrelated_path, "wb") as unrelated_file:
                        unrelated_file.write(b"unrelated user content\n")
                    unrelated_identity = os.lstat(unrelated_path).st_ino

                    os.unlink(old_source_path)
                    with open(
                        os.path.join(datafiles_path, "new.txt"),
                        "wb",
                    ) as source_file:
                        source_file.write(b"new generation")

                    class CommitInterrupted(BaseException):
                        pass

                    def stop_after_commit(phase: str) -> None:
                        if phase == "generation-committed":
                            raise CommitInterrupted()

                    with patch.object(
                        _included_phases,
                        'after_included_transaction_phase',
                        side_effect=stop_after_commit,
                    ):
                        with self.assertRaises(CommitInterrupted):
                            converter.convert_all()

                    project_identity = (
                        _included_file_publication.ensure_included_output_project_root(
                            godot_path
                        )
                    )
                    journal_path = os.path.join(
                        godot_path,
                        _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                    )
                    journal_record = (
                        _included_records.read_included_recovery_record(
                            journal_path,
                            project_identity,
                        )
                    )
                    if journal_record is None:
                        self.fail("committed interruption did not preserve its journal")
                    _journal_identity, journal_payload = journal_record
                    journal = (
                        _included_codec.included_recovery_journal_from_payload(
                            godot_path,
                            project_identity,
                            journal_payload,
                        )
                    )
                    if location == "root-backup":
                        container_path = journal.root_backup_path
                        container_snapshot = (
                            journal.transaction.previous_root_snapshot
                        )
                        cleanup_role = "root-backup"
                    else:
                        container_path = journal.transaction.stage_container_path
                        container_snapshot = (
                            journal.transaction.staged_container_snapshot
                        )
                        cleanup_role = "stage"

                    user_path = os.path.join(
                        container_path,
                        "user-preserved.txt",
                    )
                    with open(user_path, "wb") as user_file:
                        user_file.write(b"injected user content\n")
                    user_identity = os.lstat(user_path).st_ino

                    final_root_path = os.path.join(
                        godot_path,
                        "included_files",
                    )
                    final_registry_path = os.path.join(
                        godot_path,
                        INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                    )
                    final_root_identity = os.lstat(final_root_path).st_ino
                    final_registry_identity = os.lstat(final_registry_path).st_ino
                    with open(final_registry_path, "rb") as registry_file:
                        final_registry_content = registry_file.read()

                    project_lock = (
                        _included_locking.acquire_included_project_lock(
                            godot_path,
                            project_identity,
                        )
                    )
                    try:
                        recovery_message = (
                            _included_recovery.recover_included_output_set(
                                godot_path,
                                project_identity,
                            )
                        )
                    finally:
                        _included_locking.release_included_project_lock(
                            project_lock
                        )

                    self.assertIsNotNone(recovery_message)
                    self.assertIn("preserved", recovery_message or "")
                    tombstone_path = (
                        _included_paths.included_cleanup_tombstone_path(
                            container_path,
                            journal.transaction_id,
                            cleanup_role,
                            ".",
                            expect_directory=True,
                        )
                    )
                    preserved_containers = [
                        candidate
                        for candidate in (container_path, tombstone_path)
                        if os.path.isdir(candidate)
                    ]
                    self.assertEqual(len(preserved_containers), 1)
                    preserved_container = preserved_containers[0]
                    preserved_user_path = os.path.join(
                        preserved_container,
                        "user-preserved.txt",
                    )
                    self.assertEqual(
                        os.lstat(preserved_user_path).st_ino,
                        user_identity,
                    )
                    with open(preserved_user_path, "rb") as user_file:
                        self.assertEqual(
                            user_file.read(),
                            b"injected user content\n",
                        )
                    for entry in container_snapshot.entries:
                        self.assertFalse(
                            os.path.lexists(
                                os.path.join(
                                    preserved_container,
                                    *entry.relative_path.split("/"),
                                )
                            ),
                            entry.relative_path,
                        )

                    self.assertEqual(
                        os.lstat(final_root_path).st_ino,
                        final_root_identity,
                    )
                    with open(
                        os.path.join(final_root_path, "new.txt"),
                        "rb",
                    ) as output_file:
                        self.assertEqual(output_file.read(), b"new generation")
                    self.assertFalse(
                        os.path.lexists(os.path.join(final_root_path, "old.txt"))
                    )
                    self.assertEqual(
                        os.lstat(final_registry_path).st_ino,
                        final_registry_identity,
                    )
                    with open(final_registry_path, "rb") as registry_file:
                        self.assertEqual(
                            registry_file.read(),
                            final_registry_content,
                        )
                    self.assertEqual(
                        os.lstat(unrelated_path).st_ino,
                        unrelated_identity,
                    )
                    with open(unrelated_path, "rb") as unrelated_file:
                        self.assertEqual(
                            unrelated_file.read(),
                            b"unrelated user content\n",
                        )
                    self.assertFalse(os.path.lexists(journal_path))
                    self.assertFalse(
                        os.path.lexists(
                            os.path.join(
                                godot_path,
                                _included_constants.INCLUDED_FILES_COMMIT_NAME,
                            )
                        )
                    )

    def test_marker_only_committed_recovery_uses_embedded_cleanup_manifest(
        self,
    ) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import phase_observer as included_phase_observer
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "generation-committed":
        os._exit(86)

included_phase_observer.after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )
        interrupted = subprocess.run(
            (
                sys.executable,
                "-c",
                interruption_script,
                self.gm_dir,
                self.godot_dir,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )

        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_JOURNAL_NAME,
        )
        commit_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_COMMIT_NAME,
        )
        journal_record = _included_records.read_included_recovery_record(
            journal_path,
            project_identity,
        )
        commit_record = _included_records.read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed interruption did not preserve both records")
        _journal_identity, journal_payload = journal_record
        _commit_identity, commit_payload = commit_record
        journal = _included_codec.included_recovery_journal_from_payload(
            self.godot_dir,
            project_identity,
            journal_payload,
        )
        _marker, embedded_journal = (
            _included_codec.included_commit_marker_and_journal_from_payload(
                self.godot_dir,
                commit_payload,
                project_identity,
            )
        )
        self.assertEqual(embedded_journal, journal)
        self.assertTrue(os.path.lexists(journal.root_backup_path))
        self.assertTrue(os.path.lexists(journal.registry_backup_path))
        self.assertTrue(
            os.path.lexists(journal.transaction.stage_container_path)
        )
        committed_pair = self._pair_snapshot()
        self.assertEqual(
            committed_pair[1],
            {"new.txt": b"new generation"},
        )
        self.assertIn(b'"logical_path": "new.txt"', committed_pair[3])
        self.assertNotIn(b'"logical_path": "old.txt"', committed_pair[3])

        os.unlink(journal_path)
        _included_posix.sync_included_directory(
            self.godot_dir,
            project_identity,
        )

        def recover() -> str | None:
            project_lock = _included_locking.acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return _included_recovery.recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                _included_locking.release_included_project_lock(
                    project_lock
                )

        recovery_message = recover()

        self.assertIsNotNone(recovery_message)
        self.assertIn("already committed", recovery_message or "")
        self.assertEqual(self._pair_snapshot(), committed_pair)
        self.assertFalse(os.path.lexists(journal.root_backup_path))
        self.assertFalse(os.path.lexists(journal.registry_backup_path))
        self.assertFalse(
            os.path.lexists(journal.transaction.stage_container_path)
        )
        self.assertFalse(os.path.lexists(commit_path))
        self._assert_no_transaction_debris()

        self.assertIsNone(recover())
        self.assertEqual(self._pair_snapshot(), committed_pair)
        self._assert_no_transaction_debris()

    def test_modeled_windows_commit_marker_rejects_forged_embedded_path_before_io(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        commit_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_COMMIT_NAME,
        )
        commit_record = _included_records.read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if commit_record is None:
            self.fail("committed interruption did not preserve its commit marker")
        _commit_identity, commit_payload = commit_record
        forged_payload = json.loads(json.dumps(commit_payload))
        embedded_journal = forged_payload["recovery_journal"]
        staged_snapshot = embedded_journal["staged_container_snapshot"]
        if embedded_journal["format_version"] == 1:
            staged_entries = staged_snapshot["entries"]
            forged_entry = next(
                entry for entry in staged_entries if entry["kind"] == "file"
            )
            forged_entry["relative_path"] = "safe/D:evil"
        else:
            staged_entries = staged_snapshot[1]
            forged_entry = next(
                entry for entry in staged_entries if entry[1] == "f"
            )
            forged_entry[0] = "safe/D:evil"
        forged_payload["recovery_journal_sha256"] = hashlib.sha256(
            _included_codec.included_recovery_record_content(
                embedded_journal
            )
        ).hexdigest()
        forged_content = (
            _included_codec.included_recovery_record_content(
                forged_payload
            )
        )
        self.assertEqual(
            forged_content,
            _included_codec.included_recovery_record_content(
                json.loads(forged_content.decode("utf-8"))
            ),
        )

        with (
            patch.object(os, "name", "nt"),
            patch.object(os, "stat") as stat_call,
            patch.object(os, "lstat") as lstat_call,
            patch.object(
                _included_cleanup,
                'cleanup_recorded_included_tree',
            ) as cleanup_tree,
            patch.object(
                _included_mutations,
                'move_exact_included_file',
            ) as move_file,
            patch.object(
                _included_mutations,
                'move_exact_included_directory',
            ) as move_directory,
            self.assertRaisesRegex(OSError, "Windows-ambiguous"),
        ):
            _included_codec.included_commit_marker_and_journal_from_payload(
                self.godot_dir,
                forged_payload,
                project_identity,
            )
        stat_call.assert_not_called()
        lstat_call.assert_not_called()
        cleanup_tree.assert_not_called()
        move_file.assert_not_called()
        move_directory.assert_not_called()

    def test_modeled_windows_recovery_paths_reject_ambiguous_components_before_io(
        self,
    ) -> None:
        cases = (
            "safe/D:evil",
            "foo:bar",
            " leading.txt",
            "trailing.",
            "trailing ",
            "CON",
            "con.txt",
            "AUX.bin",
            "NUL",
            "COM1.dat",
            "LPT9",
        )
        cleanup_root = os.path.join(self.godot_dir, "modeled-cleanup-root")

        for relative_path in cases:
            with (
                self.subTest(relative_path=relative_path),
                patch.object(os, "name", "nt"),
                patch.object(os, "stat") as stat_call,
                patch.object(os, "lstat") as lstat_call,
                patch.object(
                    _included_mutations,
                    'move_exact_included_file',
                ) as move_file,
                patch.object(
                    _included_mutations,
                    'move_exact_included_directory',
                ) as move_directory,
                self.assertRaisesRegex(OSError, "Windows-ambiguous"),
            ):
                _included_cleanup.cleanup_recorded_included_tree(
                    cleanup_root,
                    self._recovery_cleanup_snapshot(relative_path),
                    (7, 8),
                    "modeled-windows-path",
                    "path-confinement-test",
                )
            lstat_call.assert_not_called()
            stat_call.assert_not_called()
            move_file.assert_not_called()
            move_directory.assert_not_called()

    @unittest.skipIf(os.name == "nt", "requires native POSIX path semantics")
    def test_posix_recovery_paths_keep_posix_valid_components(self) -> None:
        root_path = os.path.join(self.godot_dir, "posix-cleanup-root")
        cases = (
            "safe/D:evil",
            "D:evil",
            "foo:bar",
            " leading.txt",
            "trailing.",
            "trailing ",
            "CON",
            "con.txt",
        )

        for relative_path in cases:
            with self.subTest(relative_path=relative_path):
                self.assertEqual(
                    _included_paths.included_recovery_relative_path(
                        relative_path
                    ),
                    relative_path,
                )
                reconstructed = (
                    _included_paths.included_recovery_tree_entry_path(
                        root_path,
                        relative_path,
                    )
                )
                self.assertEqual(
                    reconstructed,
                    os.path.abspath(
                        os.path.join(root_path, *relative_path.split("/"))
                    ),
                )
                self.assertEqual(
                    os.path.commonpath(
                        (os.path.abspath(root_path), reconstructed)
                    ),
                    os.path.abspath(root_path),
                )

    @unittest.skipUnless(os.name == "nt", "requires native Windows paths")
    def test_native_windows_recovery_paths_reject_before_io(self) -> None:
        cleanup_root = os.path.join(self.godot_dir, "native-cleanup-root")
        safe_path = _included_paths.included_recovery_tree_entry_path(
            cleanup_root,
            "safe/payload.txt",
        )
        self.assertEqual(
            safe_path,
            os.path.abspath(
                os.path.join(cleanup_root, "safe", "payload.txt")
            ),
        )

        for relative_path in (
            "safe/D:evil",
            "foo:bar",
            " leading.txt",
            "trailing.",
            "trailing ",
            "CON",
            "AUX.txt",
            "NUL",
            "COM1.bin",
            "LPT1",
        ):
            with (
                self.subTest(relative_path=relative_path),
                patch.object(os, "stat") as stat_call,
                patch.object(os, "lstat") as lstat_call,
                patch.object(
                    _included_mutations,
                    'move_exact_included_file',
                ) as move_file,
                patch.object(
                    _included_mutations,
                    'move_exact_included_directory',
                ) as move_directory,
                self.assertRaisesRegex(OSError, "Windows-ambiguous"),
            ):
                _included_cleanup.cleanup_recorded_included_tree(
                    cleanup_root,
                    self._recovery_cleanup_snapshot(relative_path),
                    (7, 8),
                    "native-windows-path",
                    "path-confinement-test",
                )
            lstat_call.assert_not_called()
            stat_call.assert_not_called()
            move_file.assert_not_called()
            move_directory.assert_not_called()

    def test_temporary_record_cleanup_tombstones_resume_after_hard_exit(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        record_specs = (
            (
                "journal",
                _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX,
            ),
            (
                "commit",
                _included_constants.INCLUDED_FILES_COMMIT_NAME,
                _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX,
            ),
        )
        canonical_records: list[tuple[str, str, bytes]] = []
        for record_kind, stable_name, temporary_prefix in record_specs:
            record = _included_records.read_included_recovery_record(
                os.path.join(self.godot_dir, stable_name),
                project_identity,
            )
            if record is None:
                self.fail(
                    "committed interruption did not preserve its "
                    + record_kind
                    + " record"
                )
            canonical_records.append(
                (
                    record_kind,
                    temporary_prefix,
                    _included_codec.included_recovery_record_content(
                        record[1]
                    ),
                )
            )

        def recover() -> str | None:
            project_lock = _included_locking.acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return _included_recovery.recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                _included_locking.release_included_project_lock(
                    project_lock
                )

        committed_pair = self._pair_snapshot()
        self.assertIsNotNone(recover())
        self.assertEqual(self._pair_snapshot(), committed_pair)
        self._assert_no_transaction_debris()

        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import file_publication as included_file_publication
from src.conversion.included_files_parts import locking as included_locking
from src.conversion.included_files_parts import record_lifecycle as included_record_lifecycle
from src.conversion.included_files_parts import source_snapshots as included_source_snapshots
from src.conversion.included_files_parts import phase_observer as included_phase_observer

project_path, record_path, requested_phase = sys.argv[1:]
project_identity = included_file_publication.ensure_included_output_project_root(
    project_path
)
project_lock = included_locking.acquire_included_project_lock(
    project_path,
    project_identity,
)

def stop_after_phase(phase: str) -> None:
    if phase == requested_phase:
        os._exit(86)

included_phase_observer.after_included_transaction_phase = stop_after_phase
try:
    record_state = included_source_snapshots.included_regular_file_state(
        record_path,
        expected_parent_identity=project_identity,
    )
    if record_state is None:
        os._exit(87)
    included_record_lifecycle.remove_included_recovery_record(
        record_path,
        record_state[0],
        project_path,
        project_identity,
    )
finally:
    included_locking.release_included_project_lock(project_lock)
os._exit(88)
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )

        for record_kind, temporary_prefix, content in canonical_records:
            for action in ("quarantined", "removed"):
                with self.subTest(record=record_kind, action=action):
                    temporary_path = os.path.join(
                        self.godot_dir,
                        temporary_prefix + "a" * 16 + ".tmp",
                    )
                    with open(temporary_path, "wb") as temporary_file:
                        temporary_file.write(content)
                        temporary_file.flush()
                        os.fsync(temporary_file.fileno())
                    _included_posix.sync_included_directory(
                        self.godot_dir,
                        project_identity,
                    )
                    temporary_stat = os.lstat(temporary_path)
                    temporary_identity = (
                        temporary_stat.st_dev,
                        temporary_stat.st_ino,
                    )
                    tombstone_path = (
                        _included_paths.included_cleanup_tombstone_path(
                            temporary_path,
                            hashlib.sha256(content).hexdigest()[:32],
                            record_kind + "-temporary-record",
                            record_kind,
                            expect_directory=False,
                        )
                    )
                    requested_phase = (
                        "cleanup:"
                        + record_kind
                        + "-temporary-record:"
                        + record_kind
                        + ":"
                        + action
                    )

                    interrupted = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            interruption_script,
                            self.godot_dir,
                            temporary_path,
                            requested_phase,
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )

                    self.assertEqual(
                        interrupted.returncode,
                        86,
                        interrupted.stdout + interrupted.stderr,
                    )
                    self.assertFalse(os.path.lexists(temporary_path))
                    if action == "quarantined":
                        tombstone_stat = os.lstat(tombstone_path)
                        self.assertEqual(
                            (tombstone_stat.st_dev, tombstone_stat.st_ino),
                            temporary_identity,
                        )
                        with open(tombstone_path, "rb") as tombstone_file:
                            self.assertEqual(tombstone_file.read(), content)
                    else:
                        self.assertFalse(os.path.lexists(tombstone_path))

                    recovery_message = recover()
                    if action == "quarantined":
                        self.assertIn("removed 1", recovery_message or "")
                    else:
                        self.assertIsNone(recovery_message)

                    self.assertFalse(os.path.lexists(tombstone_path))
                    self.assertEqual(self._pair_snapshot(), committed_pair)
                    self._assert_no_transaction_debris()
                    self.assertIsNone(recover())

    def test_bounded_record_accepts_stable_path_handle_metadata_skew(self) -> None:
        payload = b'{"state":"prepared"}\n'
        record_path = os.path.join(self.godot_dir, "recovery-record.json")
        with open(record_path, "wb") as record_file:
            record_file.write(payload)
        path_stat = os.lstat(record_path)
        handle_stat = self._modeled_handle_stat(
            path_stat,
            ctime_offset=1,
        )

        with (
            open(record_path, "rb") as record_file,
            patch.object(
                os,
                "fstat",
                side_effect=(handle_stat, handle_stat),
            ),
        ):
            content = (
                _included_records.read_opened_included_bounded_record_payload(
                    record_file,
                    path_stat,
                    record_path,
                    path_stat.st_dev,
                    None,
                    len(payload),
                    lambda opened_file: opened_file.read(len(payload) + 1),
                    "Included Files recovery record",
                    "canonical",
                )
            )

        self.assertEqual(content, payload)

    def test_committed_cleanup_preserves_unknown_stage_content(self) -> None:
        logs: list[str] = []
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=logs.append,
            progress_callback=lambda _value: None,
            conversion_running=self.running.is_set,
            max_workers=1,
        )
        self._write("new.txt", "new")
        cleanup_recorded_tree = (
            _included_cleanup.cleanup_recorded_included_tree
        )
        sentinel_path: str | None = None

        def inject_unknown_stage_content(
            path: str,
            snapshot: included_files_module._IncludedTreeSnapshot,
            expected_parent_identity: tuple[int, int],
            transaction_id: str,
            role: str,
        ) -> tuple[str, ...]:
            nonlocal sentinel_path
            if sentinel_path is None and role == "stage":
                sentinel_path = os.path.join(path, "unknown-sentinel.txt")
                with open(sentinel_path, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown committed stage content")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
            return cleanup_recorded_tree(
                path,
                snapshot,
                expected_parent_identity,
                transaction_id,
                role,
            )

        with patch.object(
            _included_cleanup,
            'cleanup_recorded_included_tree',
            side_effect=inject_unknown_stage_content,
        ):
            converter.convert_all()

        self.assertIsNotNone(sentinel_path)
        if sentinel_path is not None:
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(
                    sentinel_file.read(),
                    b"unknown committed stage content",
                )
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (os.path.basename(os.path.dirname(sentinel_path)),),
            )
        self.assertEqual(self._pair_snapshot()[1], {"new.txt": b"new"})
        self.assertTrue(
            any("transaction cleanup failed" in message for message in logs),
            logs,
        )

    def test_large_cleanup_tombstone_recovers_after_hard_exit(self) -> None:
        payload_size = 64 * 1024 * 1024
        source_path = os.path.join(self.datafiles_dir, "large.bin")
        with open(source_path, "wb") as source_file:
            source_file.truncate(payload_size)
        converter = self._converter(max_workers=1)
        converter.convert_all()
        os.unlink(source_path)
        self._write("new.txt", "new generation")

        interrupted = self._run_interrupted_conversion(
            "cleanup:root-backup:large.bin:quarantined"
        )

        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        large_tombstones = [
            os.path.join(directory, filename)
            for directory, _subdirectories, filenames in os.walk(
                self.godot_dir
            )
            for filename in filenames
            if filename.startswith(
                _included_constants.INCLUDED_FILES_CLEANUP_PREFIX
            )
            and filename.endswith(".file")
            and os.path.getsize(os.path.join(directory, filename))
            == payload_size
        ]
        self.assertEqual(len(large_tombstones), 1)
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                )
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    _included_constants.INCLUDED_FILES_COMMIT_NAME,
                )
            )
        )

        converter.convert_all()

        self.assertEqual(
            self._pair_snapshot()[1],
            {"new.txt": b"new generation"},
        )
        self.assertFalse(os.path.lexists(large_tombstones[0]))
        self._assert_no_transaction_debris()

    def test_windows_deterministic_cleanup_recovers_after_readonly_clear_exit(
        self,
    ) -> None:
        cleanup_directory = os.path.join(
            self.godot_dir,
            "windows-deterministic-readonly-exit",
        )
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "owned.txt")
        content = b"owned interrupted cleanup target"
        with open(owned_path, "wb") as owned_file:
            owned_file.write(content)
        os.chmod(owned_path, 0o400)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        expected_identity = (owned_stat.st_dev, owned_stat.st_ino)
        expected_parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        expected_fingerprint = _included_metadata.included_path_fingerprint(
            owned_stat
        )
        transaction_id = "b" * 32
        tombstone_path = _included_paths.included_cleanup_tombstone_path(
            owned_path,
            transaction_id,
            "test-readonly-exit",
            "owned.txt",
            expect_directory=False,
        )

        class SimulatedProcessExit(BaseException):
            pass

        def stop_after_readonly_clear(phase: str) -> None:
            if phase == "cleanup-readonly-cleared":
                raise SimulatedProcessExit()

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'open_included_file_validation_stream',
                side_effect=self._open_modeled_windows_validation_stream,
            ),
            patch.object(
                _included_phases,
                'after_included_transaction_phase',
                side_effect=stop_after_readonly_clear,
            ),
            self.assertRaises(SimulatedProcessExit),
        ):
            _included_cleanup.cleanup_recorded_included_file(
                owned_path,
                expected_identity,
                hashlib.sha256(content).hexdigest(),
                expected_parent_identity,
                transaction_id,
                "test-readonly-exit",
                "owned.txt",
                expected_fingerprint=expected_fingerprint,
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertFalse(os.path.lexists(owned_path))
        interrupted_stat = os.lstat(tombstone_path)
        self.assertTrue(interrupted_stat.st_mode & stat.S_IWRITE)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'open_included_file_validation_stream',
                side_effect=self._open_modeled_windows_validation_stream,
            ),
        ):
            warnings = _included_cleanup.cleanup_recorded_included_file(
                owned_path,
                expected_identity,
                hashlib.sha256(content).hexdigest(),
                expected_parent_identity,
                transaction_id,
                "test-readonly-exit",
                "owned.txt",
                expected_fingerprint=expected_fingerprint,
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertEqual(warnings, ())
        self.assertFalse(os.path.lexists(tombstone_path))

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_cleanup_recovers_after_process_exit(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old/nested.txt", "old payload")
        converter.convert_all()
        public_root = os.path.join(self.godot_dir, "included_files")
        self._mark_native_windows_tree_read_only(public_root)

        os.unlink(os.path.join(self.datafiles_dir, "old", "nested.txt"))
        os.rmdir(os.path.join(self.datafiles_dir, "old"))
        self._write("new/nested.txt", "new payload")

        interrupted = self._run_interrupted_conversion(
            "cleanup-readonly-cleared"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                )
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    _included_constants.INCLUDED_FILES_COMMIT_NAME,
                )
            )
        )

        converter.convert_all()

        self.assertEqual(
            self._pair_snapshot()[1],
            {"new/nested.txt": b"new payload"},
        )
        self._assert_no_transaction_debris()


if __name__ == "__main__":
    unittest.main()
