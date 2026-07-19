from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Callable, cast
from unittest.mock import patch

from src.conversion import anchored_artifacts as anchored_artifacts_module
from src.conversion import architecture_policy as architecture_policy_module
from src.conversion.anchored_artifacts import ByteArtifactTransaction
from src.conversion.architecture_policy import (
    ARCHITECTURE_POLICY_RELATIVE_PATH,
    build_architecture_policy_report,
    capture_architecture_policy_snapshot,
    publish_architecture_policy_report,
    restore_architecture_policy_snapshot,
    write_architecture_policy_report,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _lstat_at(path: str | bytes, *, dir_fd: int | None) -> os.stat_result:
    return os.stat(path, dir_fd=dir_fd, follow_symlinks=False)


def _lexists_at(path: str | bytes, *, dir_fd: int | None) -> bool:
    try:
        _lstat_at(path, dir_fd=dir_fd)
    except FileNotFoundError:
        return False
    return True


def _directory_snapshot(path: Path) -> dict[str, tuple[int, int, int, bytes]]:
    snapshot: dict[str, tuple[int, int, int, bytes]] = {}
    for child in path.iterdir():
        child_stat = child.lstat()
        snapshot[child.name] = (
            child_stat.st_dev,
            child_stat.st_ino,
            stat.S_IMODE(child_stat.st_mode),
            child.read_bytes(),
        )
    return snapshot


def _remove_readonly_test_path(
    function: Callable[..., object],
    path: str,
    error: BaseException,
) -> None:
    if not isinstance(error, PermissionError):
        raise error
    path_stat = os.lstat(path)
    path_mode = stat.S_IMODE(path_stat.st_mode)
    if not stat.S_ISREG(path_stat.st_mode) or path_mode & stat.S_IWRITE:
        raise error
    os.chmod(path, path_mode | stat.S_IWRITE)
    function(path)


class TestArchitecturePolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.gm_dir = self.temp_dir / "gm"
        self.godot_dir = self.temp_dir / "godot"
        self.gm_dir.mkdir()
        self.godot_dir.mkdir()

    def tearDown(self) -> None:
        if os.name == "nt":
            shutil.rmtree(self.temp_dir, onexc=_remove_readonly_test_path)
            return
        shutil.rmtree(self.temp_dir)

    def assertPolicyModeEqual(self, actual: int, expected: int) -> None:
        if os.name == "nt":
            self.assertEqual(
                bool(actual & stat.S_IWUSR),
                bool(expected & stat.S_IWUSR),
            )
            return
        self.assertEqual(actual, expected)

    def test_policy_selection_uses_representative_project_features(self) -> None:
        self._write_project_with_room_and_feature_script()

        report = build_architecture_policy_report(
            str(self.gm_dir),
            target_platform="windows",
            enabled_converters=["scripts", "rooms", "sounds"],
        )
        features = cast(dict[str, object], report["project_features"])
        signal_policy = cast(list[dict[str, object]], report["signal_queue_policy"])

        self.assertEqual(features["room_count"], 1)
        self.assertEqual(features["has_multiple_visible_views"], True)
        self.assertEqual(features["has_tile_layers"], True)
        self.assertEqual(features["has_scrolling_or_tiled_backgrounds"], True)
        self.assertEqual(features["has_surface_code"], True)
        self.assertEqual(features["has_precise_collision_request"], True)
        self.assertEqual(cast(dict[str, object], report["renderer"])["mode"], "surface_viewport")
        self.assertEqual(
            cast(dict[str, object], report["collision"])["mode"],
            "godot_physics_world_bridge",
        )
        self.assertEqual(
            cast(dict[str, object], report["collision"])["precise_masks"],
            "planned_custom_mask_backend",
        )
        self.assertEqual(cast(dict[str, object], report["audio"])["mode"], "pooled_audio_stream_players")
        self.assertEqual(
            cast(dict[str, object], report["file_buffer_network"])["network"],
            "gm_async_socket_wrappers",
        )
        self.assertIn(
            {"godot_signal": "HTTPRequest.request_completed", "runtime_manager": "GMAsync"},
            [
                {
                    "godot_signal": str(policy["godot_signal"]),
                    "runtime_manager": str(policy["runtime_manager"]),
                }
                for policy in signal_policy
            ],
        )

    def test_write_report_emits_deterministic_json(self) -> None:
        self._write_minimal_project()

        report_path = write_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )

        self.assertEqual(report_path, str(self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH))
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        self.assertEqual(report["format_version"], 1)
        self.assertEqual(report["target_platform"], "linux")
        self.assertEqual(report["enabled_converters"], ["rooms"])
        self.assertEqual(report["room_root"]["id"], "gm_room_node2d")
        self.assertEqual(report["renderer"]["mode"], "godot_node_scene")

    def test_publish_receipt_and_restore_preserve_exact_existing_report(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        previous_content = b'{"previous": true}\n'
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(previous_content)
        report_path.chmod(0o640)
        previous_mode = stat.S_IMODE(report_path.stat().st_mode)
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))

        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )

        self.assertTrue(snapshot.present)
        self.assertEqual(snapshot.content, previous_content)
        assert snapshot.mode is not None
        self.assertPolicyModeEqual(snapshot.mode, previous_mode)
        self.assertIsNotNone(snapshot.fingerprint)
        self.assertEqual(receipt.path, str(report_path))
        self.assertEqual(receipt.content, report_path.read_bytes())
        self.assertPolicyModeEqual(receipt.mode, previous_mode)
        self.assertPolicyModeEqual(
            stat.S_IMODE(report_path.stat().st_mode),
            previous_mode,
        )
        self.assertEqual(
            receipt.fingerprint,
            (
                report_path.stat().st_dev,
                report_path.stat().st_ino,
                report_path.stat().st_size,
                report_path.stat().st_mtime_ns,
            ),
        )

        restored_path = restore_architecture_policy_snapshot(
            str(self.godot_dir),
            snapshot,
            receipt,
        )

        self.assertEqual(restored_path, str(report_path))
        self.assertEqual(report_path.read_bytes(), previous_content)
        self.assertPolicyModeEqual(
            stat.S_IMODE(report_path.stat().st_mode),
            previous_mode,
        )

    def test_windows_staged_io_accepts_only_ctime_drift_across_stat_apis(
        self,
    ) -> None:
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        transaction = ByteArtifactTransaction.open(
            str(self.godot_dir),
            "gm2godot",
            create=False,
            description="architecture-policy report directory",
        )
        staged = transaction.stage_bytes(
            report_path.name,
            b'{"staged": "ctime drift"}\n',
            mode=None,
            suffix=".tmp",
        )
        real_fingerprint = cast(
            Callable[[os.stat_result], tuple[int, int, int, int, int]],
            getattr(anchored_artifacts_module, "_file_fingerprint"),
        )
        fingerprint_calls = 0

        def ctime_drifting_fingerprint(
            path_stat: os.stat_result,
        ) -> tuple[int, int, int, int, int]:
            nonlocal fingerprint_calls
            fingerprint_calls += 1
            fingerprint = real_fingerprint(path_stat)
            return (
                *fingerprint[:4],
                fingerprint[4] + fingerprint_calls,
            )

        try:
            with (
                patch(
                    "src.conversion.anchored_artifacts._is_windows_platform",
                    return_value=True,
                ),
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=ctime_drifting_fingerprint,
                ),
            ):
                transaction.verify_staged(staged)

            self.assertEqual(fingerprint_calls, 3)
            fingerprint_calls = 0
            with (
                patch(
                    "src.conversion.anchored_artifacts._is_windows_platform",
                    return_value=False,
                ),
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=ctime_drifting_fingerprint,
                ),
                self.assertRaisesRegex(OSError, "content changed"),
            ):
                transaction.verify_staged(staged)
        finally:
            transaction.unlink_staged(staged)
            transaction.__exit__(None, None, None)

        fingerprints_match = cast(
            Callable[
                [
                    tuple[int, int, int, int, int],
                    tuple[int, int, int, int, int],
                ],
                bool,
            ],
            getattr(anchored_artifacts_module, "fingerprints_match"),
        )
        original = (1, 2, 3, 4, 5)
        ctime_only_drift = (1, 2, 3, 4, 50)
        mtime_only_drift = (1, 2, 3, 40, 5)
        identity_drift = (10, 20, 3, 4, 5)
        size_drift = (1, 2, 30, 4, 5)
        with patch(
            "src.conversion.anchored_artifacts._is_windows_platform",
            return_value=True,
        ):
            self.assertTrue(fingerprints_match(original, ctime_only_drift))
            self.assertFalse(fingerprints_match(original, mtime_only_drift))
            self.assertFalse(fingerprints_match(original, identity_drift))
            self.assertFalse(fingerprints_match(original, size_drift))
        with patch(
            "src.conversion.anchored_artifacts._is_windows_platform",
            return_value=False,
        ):
            self.assertFalse(fingerprints_match(original, ctime_only_drift))

    def test_windows_target_state_keeps_exact_path_ctime_guard(self) -> None:
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(b'{"stable": true}\n')
        real_fingerprint = cast(
            Callable[[os.stat_result], tuple[int, int, int, int, int]],
            getattr(anchored_artifacts_module, "_file_fingerprint"),
        )

        def path_ctime_drift(
            path_stat: os.stat_result,
        ) -> tuple[int, int, int, int, int]:
            fingerprint = real_fingerprint(path_stat)
            return (*fingerprint[:4], fingerprint[4] + 1)

        with ByteArtifactTransaction.open(
            str(self.godot_dir),
            "gm2godot",
            create=False,
            description="architecture-policy report directory",
        ) as transaction:
            target_state = transaction.target_state("architecture_policy.json")
            with (
                patch(
                    "src.conversion.anchored_artifacts._is_windows_platform",
                    return_value=True,
                ),
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=path_ctime_drift,
                ),
                self.assertRaisesRegex(OSError, "Artifact changed"),
            ):
                transaction.verify_target_state(
                    "architecture_policy.json",
                    target_state,
                )

    def test_windows_receipt_guard_rejects_identity_size_content_and_mode_changes(
        self,
    ) -> None:
        self._write_minimal_project()
        verify_receipt = cast(
            Callable[..., None],
            getattr(architecture_policy_module, "_verify_policy_receipt"),
        )

        for case in ("identity", "size", "content", "mode"):
            with self.subTest(case=case):
                godot_dir = self.temp_dir / f"windows-guard-{case}"
                godot_dir.mkdir()
                receipt = publish_architecture_policy_report(
                    str(self.gm_dir),
                    str(godot_dir),
                    target_platform="windows",
                    enabled_converters=["rooms"],
                )
                report_path = Path(receipt.path)
                if case == "identity":
                    replacement_path = report_path.with_suffix(".replacement")
                    replacement_path.write_bytes(receipt.content)
                    replacement_path.chmod(receipt.mode)
                    os.replace(replacement_path, report_path)
                elif case == "size":
                    report_path.write_bytes(receipt.content + b"x")
                elif case == "content":
                    report_path.write_bytes(b"X" + receipt.content[1:])
                    current_stat = report_path.stat()
                    receipt = replace(
                        receipt,
                        fingerprint=(
                            current_stat.st_dev,
                            current_stat.st_ino,
                            current_stat.st_size,
                            current_stat.st_mtime_ns,
                        ),
                    )
                else:
                    report_path.chmod(receipt.mode ^ stat.S_IWUSR)

                with ByteArtifactTransaction.open(
                    str(godot_dir),
                    "gm2godot",
                    create=False,
                    description="architecture-policy report directory",
                ) as transaction:
                    with (
                        patch(
                            "src.conversion.anchored_artifacts._is_windows_platform",
                            return_value=True,
                        ),
                        self.assertRaisesRegex(
                            OSError,
                            "no longer matches its publication receipt",
                        ),
                    ):
                        verify_receipt(receipt, transaction)

    def test_mocked_windows_readonly_report_publishes_restores_and_cleans(
        self,
    ) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        previous_content = b'{"previous": "readonly"}\n'
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(previous_content)
        report_path.chmod(0o444)
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        real_rename = os.rename
        real_unlink = os.unlink

        def windows_replace(
            source: str,
            destination: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            if _lexists_at(destination, dir_fd=dst_dir_fd):
                destination_mode = stat.S_IMODE(
                    _lstat_at(destination, dir_fd=dst_dir_fd).st_mode
                )
                if not destination_mode & stat.S_IWUSR:
                    raise PermissionError(
                        "mock Windows refuses to replace a read-only destination"
                    )
            real_rename(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        def windows_unlink(
            path: str | bytes,
            *,
            dir_fd: int | None = None,
        ) -> None:
            if _lexists_at(path, dir_fd=dir_fd):
                path_mode = stat.S_IMODE(_lstat_at(path, dir_fd=dir_fd).st_mode)
                if not path_mode & stat.S_IWUSR:
                    raise PermissionError(
                        "mock Windows refuses to unlink a read-only file"
                    )
            real_unlink(path, dir_fd=dir_fd)

        with (
            patch(
                "src.conversion.anchored_artifacts._is_windows_platform",
                return_value=True,
            ),
            patch(
                "src.conversion.anchored_artifacts.os.rename",
                side_effect=windows_replace,
            ),
            patch(
                "src.conversion.anchored_artifacts.os.unlink",
                side_effect=windows_unlink,
            ),
        ):
            receipt = publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="windows",
                enabled_converters=["rooms"],
            )
            self.assertFalse(receipt.mode & stat.S_IWUSR)
            self.assertFalse(stat.S_IMODE(report_path.stat().st_mode) & stat.S_IWUSR)
            self.assertEqual(list(report_path.parent.iterdir()), [report_path])

            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertEqual(report_path.read_bytes(), previous_content)
        self.assertFalse(stat.S_IMODE(report_path.stat().st_mode) & stat.S_IWUSR)
        self.assertEqual(list(report_path.parent.iterdir()), [report_path])
        report_path.chmod(0o600)

    def test_mocked_windows_failed_replace_restores_readonly_and_cleans(
        self,
    ) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        previous_content = b'{"previous": "readonly"}\n'
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(previous_content)
        report_path.chmod(0o444)
        real_unlink = os.unlink

        def fail_report_replace(
            phase: str,
            directory_path: str,
            name: str | None,
        ) -> None:
            if phase == "before_replace" and name == report_path.name:
                assert name is not None
                destination = os.path.join(directory_path, name)
                destination_mode = stat.S_IMODE(
                    os.lstat(destination).st_mode
                )
                if not destination_mode & stat.S_IWUSR:
                    raise PermissionError(
                        "mock Windows refuses to replace a read-only destination"
                    )
                raise OSError("injected Windows replacement failure")

        def windows_unlink(
            path: str | bytes,
            *,
            dir_fd: int | None = None,
        ) -> None:
            if _lexists_at(path, dir_fd=dir_fd):
                path_mode = stat.S_IMODE(_lstat_at(path, dir_fd=dir_fd).st_mode)
                if not path_mode & stat.S_IWUSR:
                    raise PermissionError(
                        "mock Windows refuses to unlink a read-only file"
                    )
            real_unlink(path, dir_fd=dir_fd)

        with (
            patch(
                "src.conversion.anchored_artifacts._is_windows_platform",
                return_value=True,
            ),
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_report_replace,
            ),
            patch(
                "src.conversion.anchored_artifacts.os.unlink",
                side_effect=windows_unlink,
            ),
            self.assertRaisesRegex(OSError, "Windows replacement failure"),
        ):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="windows",
                enabled_converters=["rooms"],
            )

        self.assertEqual(report_path.read_bytes(), previous_content)
        self.assertFalse(stat.S_IMODE(report_path.stat().st_mode) & stat.S_IWUSR)
        self.assertEqual(list(report_path.parent.iterdir()), [report_path])
        report_path.chmod(0o600)

    def test_mocked_windows_readonly_rollback_restores_replaceable_backup(
        self,
    ) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        previous_content = b'{"previous": "readonly"}\n'
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(previous_content)
        report_path.chmod(0o444)
        real_rename = os.rename
        real_unlink = os.unlink
        fsync_calls = 0

        def windows_replace(
            source: str,
            destination: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            if _lexists_at(destination, dir_fd=dst_dir_fd):
                destination_mode = stat.S_IMODE(
                    _lstat_at(destination, dir_fd=dst_dir_fd).st_mode
                )
                if not destination_mode & stat.S_IWUSR:
                    raise PermissionError(
                        "mock Windows refuses to replace a read-only destination"
                    )
            real_rename(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        def windows_unlink(
            path: str | bytes,
            *,
            dir_fd: int | None = None,
        ) -> None:
            if _lexists_at(path, dir_fd=dir_fd):
                path_mode = stat.S_IMODE(_lstat_at(path, dir_fd=dir_fd).st_mode)
                if not path_mode & stat.S_IWUSR:
                    raise PermissionError(
                        "mock Windows refuses to unlink a read-only file"
                    )
            real_unlink(path, dir_fd=dir_fd)

        def fail_first_directory_fsync(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal fsync_calls
            if phase != "before_durability":
                return
            fsync_calls += 1
            if fsync_calls == 1:
                raise OSError("injected Windows directory fsync failure")

        with (
            patch(
                "src.conversion.anchored_artifacts._is_windows_platform",
                return_value=True,
            ),
            patch(
                "src.conversion.anchored_artifacts.os.rename",
                side_effect=windows_replace,
            ),
            patch(
                "src.conversion.anchored_artifacts.os.unlink",
                side_effect=windows_unlink,
            ),
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_first_directory_fsync,
            ),
            self.assertRaisesRegex(OSError, "Windows directory fsync failure"),
        ):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="windows",
                enabled_converters=["rooms"],
            )

        self.assertEqual(report_path.read_bytes(), previous_content)
        self.assertFalse(stat.S_IMODE(report_path.stat().st_mode) & stat.S_IWUSR)
        self.assertEqual(list(report_path.parent.iterdir()), [report_path])
        report_path.chmod(0o600)

    def test_publish_retry_repeats_root_fsync_after_creation_fsync_failure(
        self,
    ) -> None:
        self._write_minimal_project()
        report_directory = self.godot_dir / "gm2godot"
        real_sync = anchored_artifacts_module.VerifiedDirectory.sync
        root_fsync_failures = 0

        def fail_first_root_fsync(
            binding: anchored_artifacts_module.VerifiedDirectory,
        ) -> None:
            nonlocal root_fsync_failures
            if os.path.abspath(binding.path) == os.path.abspath(self.godot_dir):
                root_fsync_failures += 1
                raise OSError("injected root fsync failure")
            real_sync(binding)

        with patch.object(
            anchored_artifacts_module.VerifiedDirectory,
            "sync",
            autospec=True,
            side_effect=fail_first_root_fsync,
        ):
            with self.assertRaisesRegex(OSError, "root fsync failure"):
                publish_architecture_policy_report(
                    str(self.gm_dir),
                    str(self.godot_dir),
                    target_platform="linux",
                    enabled_converters=["rooms"],
                )

        self.assertEqual(root_fsync_failures, 1)
        self.assertTrue(report_directory.is_dir())
        retry_root_fsyncs = 0

        def record_retry_root_fsync(
            binding: anchored_artifacts_module.VerifiedDirectory,
        ) -> None:
            nonlocal retry_root_fsyncs
            if os.path.abspath(binding.path) == os.path.abspath(self.godot_dir):
                retry_root_fsyncs += 1
            real_sync(binding)

        with patch.object(
            anchored_artifacts_module.VerifiedDirectory,
            "sync",
            autospec=True,
            side_effect=record_retry_root_fsync,
        ):
            receipt = publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )

        self.assertEqual(retry_root_fsyncs, 1)
        self.assertTrue(Path(receipt.path).is_file())

    def test_restore_removes_report_when_snapshot_was_absent(self) -> None:
        self._write_minimal_project()
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))

        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        restore_architecture_policy_snapshot(
            str(self.godot_dir),
            snapshot,
            receipt,
        )

        self.assertFalse(snapshot.present)
        self.assertIsNone(snapshot.content)
        self.assertIsNone(snapshot.mode)
        self.assertIsNone(snapshot.fingerprint)
        self.assertFalse(Path(receipt.path).exists())

    def test_restore_rejects_forged_snapshot_content(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(b'{"previous": true}\n')
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        assert snapshot.content is not None
        forged_snapshot = replace(
            snapshot,
            content=b"X" + snapshot.content[1:],
        )

        with self.assertRaisesRegex(
            ValueError,
            "snapshot content does not match its fingerprint",
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                forged_snapshot,
                receipt,
            )

        self.assertEqual(report_path.read_bytes(), receipt.content)
        self.assertEqual(list(report_path.parent.iterdir()), [report_path])

    def test_restore_absent_snapshot_accepts_unlink_that_completed_before_error(
        self,
    ) -> None:
        self._write_minimal_project()
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        report_path = Path(receipt.path)
        real_unlink = os.unlink

        def unlink_report_then_raise(
            path: str | bytes,
            *,
            dir_fd: int | None = None,
        ) -> None:
            real_unlink(path, dir_fd=dir_fd)
            if os.path.basename(os.fsdecode(path)) == Path(receipt.path).name:
                raise OSError("injected post-unlink failure")

        with patch(
            "src.conversion.anchored_artifacts.os.unlink",
            side_effect=unlink_report_then_raise,
        ):
            restored_path = restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertEqual(restored_path, str(report_path))
        self.assertFalse(report_path.exists())
        self.assertEqual(list(report_path.parent.iterdir()), [])

    def test_restore_absent_snapshot_rolls_back_completed_unlink_on_later_failure(
        self,
    ) -> None:
        self._write_minimal_project()
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        report_path = Path(receipt.path)
        real_unlink = os.unlink
        fsync_calls = 0

        def unlink_report_then_raise(
            path: str | bytes,
            *,
            dir_fd: int | None = None,
        ) -> None:
            real_unlink(path, dir_fd=dir_fd)
            if os.path.basename(os.fsdecode(path)) == Path(receipt.path).name:
                raise OSError("injected post-unlink failure")

        def fail_first_directory_fsync(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal fsync_calls
            if phase != "before_durability":
                return
            fsync_calls += 1
            if fsync_calls == 1:
                raise OSError("injected restore fsync failure")

        with (
            patch(
                "src.conversion.anchored_artifacts.os.unlink",
                side_effect=unlink_report_then_raise,
            ),
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_first_directory_fsync,
            ),
            self.assertRaisesRegex(OSError, "injected restore fsync failure"),
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertEqual(report_path.read_bytes(), receipt.content)
        self.assertPolicyModeEqual(
            stat.S_IMODE(report_path.stat().st_mode),
            receipt.mode,
        )
        self.assertEqual(list(report_path.parent.iterdir()), [report_path])

    def test_restore_refuses_to_replace_report_changed_after_publication(self) -> None:
        self._write_minimal_project()
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        report_path = Path(receipt.path)
        report_stat = report_path.stat()
        changed_content = b"X" + receipt.content[1:]
        report_path.write_bytes(changed_content)
        report_path.chmod(receipt.mode)
        os.utime(
            report_path,
            ns=(report_stat.st_atime_ns, receipt.fingerprint[3]),
        )
        changed_stat = report_path.stat()
        self.assertEqual(
            (
                changed_stat.st_dev,
                changed_stat.st_ino,
                changed_stat.st_size,
                changed_stat.st_mtime_ns,
            ),
            receipt.fingerprint,
        )

        with self.assertRaisesRegex(
            OSError,
            "no longer matches its publication receipt",
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertEqual(report_path.read_bytes(), changed_content)

    def test_restore_rejects_identical_content_under_replacement_inode(self) -> None:
        self._write_minimal_project()
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        report_path = Path(receipt.path)
        replacement_path = report_path.with_suffix(".replacement")
        replacement_path.write_bytes(receipt.content)
        replacement_path.chmod(receipt.mode)
        replacement_stat = replacement_path.stat()
        os.utime(
            replacement_path,
            ns=(replacement_stat.st_atime_ns, receipt.fingerprint[3]),
        )
        os.replace(replacement_path, report_path)
        self.assertNotEqual(report_path.stat().st_ino, receipt.fingerprint[1])

        with self.assertRaisesRegex(
            OSError,
            "no longer matches its publication receipt",
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertEqual(report_path.read_bytes(), receipt.content)

    def test_publish_rolls_back_existing_report_when_directory_fsync_fails(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        previous_content = b'{"previous": true}\n'
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(previous_content)
        report_path.chmod(0o640)
        previous_mode = stat.S_IMODE(report_path.stat().st_mode)
        fsync_calls = 0

        def fail_first_directory_fsync(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal fsync_calls
            if phase != "before_durability":
                return
            fsync_calls += 1
            if fsync_calls == 1:
                raise OSError("injected directory fsync failure")

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_first_directory_fsync,
            ),
            self.assertRaisesRegex(OSError, "injected directory fsync failure"),
        ):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )

        self.assertEqual(report_path.read_bytes(), previous_content)
        self.assertPolicyModeEqual(
            stat.S_IMODE(report_path.stat().st_mode),
            previous_mode,
        )

    def test_publish_cleans_first_stage_when_backup_staging_fails(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        previous_content = b'{"previous": true}\n'
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(previous_content)
        real_fsync = os.fsync
        fsync_calls = 0

        def fail_second_file_fsync(file_descriptor: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError("injected backup stage fsync failure")
            real_fsync(file_descriptor)

        with (
            patch(
                "src.conversion.architecture_policy.os.fsync",
                side_effect=fail_second_file_fsync,
            ),
            self.assertRaisesRegex(OSError, "injected backup stage fsync failure"),
        ):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )

        self.assertEqual(report_path.read_bytes(), previous_content)
        self.assertEqual(list(report_path.parent.iterdir()), [report_path])

    def test_publish_cleanup_does_not_suppress_keyboard_interrupt(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(b'{"previous": true}\n')
        real_unlink = os.unlink

        def interrupt_backup_cleanup(
            path: str | bytes,
            *,
            dir_fd: int | None = None,
        ) -> None:
            if os.fsdecode(path).endswith(".backup"):
                raise KeyboardInterrupt("injected cleanup interrupt")
            real_unlink(path, dir_fd=dir_fd)

        with (
            patch(
                "src.conversion.anchored_artifacts.os.unlink",
                side_effect=interrupt_backup_cleanup,
            ),
            self.assertRaisesRegex(KeyboardInterrupt, "cleanup interrupt"),
        ):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )

    def test_restore_rolls_back_to_receipt_when_directory_fsync_fails(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(b'{"previous": true}\n')
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        fsync_calls = 0

        def fail_first_directory_fsync(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal fsync_calls
            if phase != "before_durability":
                return
            fsync_calls += 1
            if fsync_calls == 1:
                raise OSError("injected restore fsync failure")

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_first_directory_fsync,
            ),
            self.assertRaisesRegex(OSError, "injected restore fsync failure"),
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertEqual(report_path.read_bytes(), receipt.content)
        self.assertPolicyModeEqual(
            stat.S_IMODE(report_path.stat().st_mode),
            receipt.mode,
        )

    def test_failed_restore_keeps_original_receipt_valid_for_retry(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(b'{"previous": true}\n')
        report_path.chmod(0o640)
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        original_fingerprint = receipt.fingerprint
        fsync_calls = 0

        def fail_first_directory_fsync(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal fsync_calls
            if phase != "before_durability":
                return
            fsync_calls += 1
            if fsync_calls == 1:
                raise OSError("injected post-mutation restore failure")

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_first_directory_fsync,
            ),
            self.assertRaisesRegex(OSError, "post-mutation restore failure"),
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        rolled_back_stat = report_path.stat()
        self.assertEqual(receipt.fingerprint, original_fingerprint)
        self.assertEqual(
            original_fingerprint,
            (
                rolled_back_stat.st_dev,
                rolled_back_stat.st_ino,
                rolled_back_stat.st_size,
                rolled_back_stat.st_mtime_ns,
            ),
        )
        self.assertEqual(report_path.read_bytes(), receipt.content)
        self.assertPolicyModeEqual(
            stat.S_IMODE(rolled_back_stat.st_mode),
            receipt.mode,
        )

        restored_path = restore_architecture_policy_snapshot(
            str(self.godot_dir),
            snapshot,
            receipt,
        )

        self.assertEqual(restored_path, str(report_path))
        self.assertEqual(report_path.read_bytes(), snapshot.content)
        assert snapshot.mode is not None
        self.assertPolicyModeEqual(
            stat.S_IMODE(report_path.stat().st_mode),
            snapshot.mode,
        )

    @unittest.skipUnless(
        os.name == "posix" and callable(getattr(os, "fchmod", None)),
        "POSIX fchmod is required for exact special-mode validation",
    )
    def test_publish_applies_exact_special_mode_after_staged_write(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(b'{"previous": true}\n')
        requested_mode = 0o6750
        report_path.chmod(requested_mode)
        if stat.S_IMODE(report_path.stat().st_mode) != requested_mode:
            self.skipTest("Filesystem does not preserve setuid/setgid mode bits")

        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )

        self.assertEqual(receipt.mode, requested_mode)
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), requested_mode)

    def test_restore_cleans_receipt_backup_when_snapshot_staging_fails(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        report_path.write_bytes(b'{"previous": true}\n')
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        real_fsync = os.fsync
        fsync_calls = 0

        def fail_second_file_fsync(file_descriptor: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError("injected snapshot stage fsync failure")
            real_fsync(file_descriptor)

        with (
            patch(
                "src.conversion.architecture_policy.os.fsync",
                side_effect=fail_second_file_fsync,
            ),
            self.assertRaisesRegex(OSError, "injected snapshot stage fsync failure"),
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertEqual(report_path.read_bytes(), receipt.content)
        self.assertEqual(list(report_path.parent.iterdir()), [report_path])

    def test_publish_refuses_redirected_report_directory(self) -> None:
        self._write_minimal_project()
        outside_directory = self.temp_dir / "outside"
        outside_directory.mkdir()
        report_directory = self.godot_dir / "gm2godot"
        try:
            report_directory.symlink_to(outside_directory, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symbolic links are unavailable: {exc}")

        with self.assertRaisesRegex(OSError, "Refusing redirected"):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )

        self.assertEqual(list(outside_directory.iterdir()), [])

    def test_publish_refuses_symlink_or_nonregular_report_target(self) -> None:
        self._write_minimal_project()
        report_path = self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH
        report_path.parent.mkdir(parents=True)
        outside_report = self.temp_dir / "outside.json"
        outside_report.write_bytes(b"outside\n")
        try:
            report_path.symlink_to(outside_report)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symbolic links are unavailable: {exc}")

        with self.assertRaisesRegex(OSError, "non-regular"):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )
        self.assertEqual(outside_report.read_bytes(), b"outside\n")

        report_path.unlink()
        if not hasattr(os, "mkfifo"):
            return
        os.mkfifo(report_path)
        with self.assertRaisesRegex(OSError, "non-regular"):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )

    @unittest.skipUnless(os.name == "posix", "POSIX directory relocation is required")
    def test_publish_never_mutates_physical_replacement_at_any_main_phase(
        self,
    ) -> None:
        self._write_minimal_project()
        phases = (
            "before_stage",
            "before_backup",
            "before_commit",
            "before_durability",
            "before_cleanup",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                godot_dir = self.temp_dir / f"phase-{phase}"
                report_directory = godot_dir / "gm2godot"
                report_path = report_directory / "architecture_policy.json"
                parked = godot_dir / "gm2godot.parked"
                godot_dir.mkdir()
                report_directory.mkdir()
                report_path.write_bytes(b'{"previous": true}\n')
                replacement_before: dict[str, tuple[int, int, int, bytes]] = {}
                swapped = False

                def replace_directory(
                    current_phase: str,
                    directory_path: str,
                    _name: str | None,
                ) -> None:
                    nonlocal replacement_before, swapped
                    if (
                        swapped
                        or current_phase != phase
                        or os.path.abspath(directory_path)
                        != os.path.abspath(report_directory)
                    ):
                        return
                    swapped = True
                    os.rename(report_directory, parked)
                    report_directory.mkdir()
                    (report_directory / "architecture_policy.json").write_bytes(
                        b'{"replacement": true}\n'
                    )
                    (report_directory / ".architecture_policy.json.collision.backup").write_bytes(
                        b"collision\n"
                    )
                    (report_directory / "sentinel.txt").write_bytes(b"outside\n")
                    replacement_before = _directory_snapshot(report_directory)

                with (
                    patch(
                        "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                        side_effect=replace_directory,
                    ),
                    self.assertRaisesRegex(OSError, "changed"),
                ):
                    publish_architecture_policy_report(
                        str(self.gm_dir),
                        str(godot_dir),
                        target_platform="linux",
                        enabled_converters=["rooms"],
                    )

                self.assertTrue(swapped)
                self.assertEqual(
                    _directory_snapshot(report_directory),
                    replacement_before,
                )

    @unittest.skipUnless(os.name == "posix", "POSIX directory relocation is required")
    def test_publish_rollback_stays_bound_after_physical_replacement(self) -> None:
        self._write_minimal_project()
        report_directory = self.godot_dir / "gm2godot"
        report_path = report_directory / "architecture_policy.json"
        parked = self.godot_dir / "gm2godot.parked"
        report_directory.mkdir()
        report_path.write_bytes(b'{"previous": true}\n')
        replacement_before: dict[str, tuple[int, int, int, bytes]] = {}
        swapped = False

        def fail_then_replace(
            phase: str,
            directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal replacement_before, swapped
            if phase == "after_commit":
                raise OSError("injected post-commit failure")
            if phase != "before_rollback" or swapped:
                return
            swapped = True
            os.rename(report_directory, parked)
            report_directory.mkdir()
            (report_directory / "architecture_policy.json").write_bytes(
                b'{"replacement": true}\n'
            )
            (report_directory / "sentinel.txt").write_bytes(b"outside\n")
            replacement_before = _directory_snapshot(report_directory)

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_then_replace,
            ),
            self.assertRaisesRegex(OSError, "post-commit failure") as raised,
        ):
            publish_architecture_policy_report(
                str(self.gm_dir),
                str(self.godot_dir),
                target_platform="linux",
                enabled_converters=["rooms"],
            )

        self.assertTrue(swapped)
        self.assertEqual(
            _directory_snapshot(report_directory),
            replacement_before,
        )
        rollback_notes = [
            note
            for note in getattr(raised.exception, "__notes__", ())
            if "verified recovery artifact preserved" in note
        ]
        self.assertEqual(len(rollback_notes), 1)
        self.assertIn(str(parked), rollback_notes[0])

    @unittest.skipUnless(os.name == "posix", "POSIX directory relocation is required")
    def test_restore_stays_bound_after_physical_replacement(self) -> None:
        self._write_minimal_project()
        report_directory = self.godot_dir / "gm2godot"
        report_path = report_directory / "architecture_policy.json"
        parked = self.godot_dir / "gm2godot.parked"
        report_directory.mkdir()
        report_path.write_bytes(b'{"previous": true}\n')
        snapshot = capture_architecture_policy_snapshot(str(self.godot_dir))
        receipt = publish_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )
        replacement_before: dict[str, tuple[int, int, int, bytes]] = {}
        swapped = False

        def replace_before_snapshot_commit(
            phase: str,
            directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal replacement_before, swapped
            if phase != "before_commit" or swapped:
                return
            swapped = True
            os.rename(report_directory, parked)
            report_directory.mkdir()
            (report_directory / "architecture_policy.json").write_bytes(
                b'{"replacement": true}\n'
            )
            (report_directory / "sentinel.txt").write_bytes(b"outside\n")
            replacement_before = _directory_snapshot(report_directory)

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=replace_before_snapshot_commit,
            ),
            self.assertRaisesRegex(OSError, "changed"),
        ):
            restore_architecture_policy_snapshot(
                str(self.godot_dir),
                snapshot,
                receipt,
            )

        self.assertTrue(swapped)
        self.assertEqual(
            _directory_snapshot(report_directory),
            replacement_before,
        )

    def test_feature_scan_ignores_gml_file_symlink_outside_project(self) -> None:
        self._write_minimal_project()
        outside_source = self.temp_dir / "outside.gml"
        _write_text(outside_source, "network_create_socket(0);")
        linked_source = self.gm_dir / "scripts" / "linked.gml"
        linked_source.parent.mkdir(parents=True, exist_ok=True)
        try:
            linked_source.symlink_to(outside_source)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symbolic links are unavailable: {exc}")

        report = build_architecture_policy_report(
            str(self.gm_dir),
            target_platform="windows",
            enabled_converters=["scripts"],
        )
        features = cast(dict[str, object], report["project_features"])

        self.assertEqual(features["has_network_code"], False)

    def _write_minimal_project(self) -> None:
        _write_json(
            self.gm_dir / "PolicyProject.yyp",
            {
                "resources": [
                    {"id": {"name": "r_empty", "path": "rooms/r_empty/r_empty.yy"}},
                ],
                "RoomOrderNodes": [
                    {"roomId": {"name": "r_empty", "path": "rooms/r_empty/r_empty.yy"}},
                ],
                "resourceType": "GMProject",
            },
        )
        _write_json(
            self.gm_dir / "rooms" / "r_empty" / "r_empty.yy",
            self._room("r_empty"),
        )

    def _write_project_with_room_and_feature_script(self) -> None:
        _write_json(
            self.gm_dir / "PolicyProject.yyp",
            {
                "resources": [
                    {"id": {"name": "r_policy", "path": "rooms/r_policy/r_policy.yy"}},
                    {"id": {"name": "scr_policy", "path": "scripts/scr_policy/scr_policy.yy"}},
                ],
                "RoomOrderNodes": [
                    {"roomId": {"name": "r_policy", "path": "rooms/r_policy/r_policy.yy"}},
                ],
                "resourceType": "GMProject",
            },
        )
        _write_json(
            self.gm_dir / "rooms" / "r_policy" / "r_policy.yy",
            self._room(
                "r_policy",
                physics_world=True,
                layers=[
                    {"%Name": "Instances", "resourceType": "GMRInstanceLayer"},
                    {
                        "%Name": "Tiles",
                        "resourceType": "GMRTileLayer",
                        "tiles": {"SerialiseWidth": 1, "SerialiseHeight": 1, "TileCompressedData": [0]},
                    },
                    {
                        "%Name": "Background",
                        "resourceType": "GMRBackgroundLayer",
                        "htiled": True,
                        "hspeed": 2,
                    },
                ],
                views=[
                    {"visible": True, "xview": 0, "yview": 0, "wview": 320, "hview": 180},
                    {"visible": True, "xview": 320, "yview": 0, "wview": 320, "hview": 180},
                ],
            ),
        )
        _write_json(
            self.gm_dir / "scripts" / "scr_policy" / "scr_policy.yy",
            {
                "%Name": "scr_policy",
                "name": "scr_policy",
                "resourceType": "GMScript",
                "parent": {"name": "Scripts", "path": "folders/Scripts.yy"},
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_policy" / "scr_policy.gml",
            "\n".join([
                "surface_create(320, 180);",
                "audio_play_sound(snd_click, 0, false);",
                "network_create_socket(0);",
                "buffer_create(16, buffer_grow, 1);",
                "collision_point(id, x, y, o_wall, true, false);",
            ]),
        )

    @staticmethod
    def _room(
        name: str,
        *,
        physics_world: bool = False,
        layers: list[dict[str, object]] | None = None,
        views: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "$GMRoom": "v1",
            "%Name": name,
            "name": name,
            "creationCodeFile": "",
            "inheritCode": False,
            "inheritCreationOrder": False,
            "inheritLayers": False,
            "instanceCreationOrder": [],
            "isDnd": False,
            "layers": layers or [],
            "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
            "parentRoom": None,
            "physicsSettings": {
                "inheritPhysicsSettings": False,
                "PhysicsWorld": physics_world,
                "PhysicsWorldGravityX": 0.0,
                "PhysicsWorldGravityY": 10.0,
                "PhysicsWorldPixToMetres": 0.1,
            },
            "resourceType": "GMRoom",
            "roomSettings": {
                "Width": 640,
                "Height": 360,
                "inheritRoomSettings": False,
                "persistent": False,
            },
            "views": views or [],
            "viewSettings": {"enableViews": bool(views)},
            "volume": 1.0,
        }


if __name__ == "__main__":
    unittest.main()
