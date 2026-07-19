from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, cast
from unittest.mock import patch

from src.conversion import anchored_artifacts as anchored_artifacts_module
from src.conversion.anchored_artifacts import ArtifactSpec, ByteArtifactTransaction


class TestAnchoredArtifacts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.root = self.temp_dir / "project"
        self.artifact_directory = self.root / "gm2godot"
        self.root.mkdir()
        self.artifact_directory.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_capture_binding_does_not_create_missing_directory(self) -> None:
        self.artifact_directory.rmdir()

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            self.assertFalse(transaction.available)
            transaction.verify_directory()

        self.assertFalse(self.artifact_directory.exists())

    def test_posix_binding_keeps_replacement_directory_untouched(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        parked = self.root / "gm2godot.parked"

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            if transaction.strategy != "posix_dir_fd":
                self.skipTest("descriptor-relative POSIX operations are unavailable")
            staged = transaction.stage_bytes(
                "report.json",
                b"new\n",
                mode=0o640,
                suffix=".tmp",
            )
            os.rename(self.artifact_directory, parked)
            self.artifact_directory.mkdir()
            replacement_target = self.artifact_directory / "report.json"
            replacement_target.write_bytes(b"attacker\n")
            replacement_target.chmod(0o444)
            sentinel = self.artifact_directory / "sentinel.txt"
            sentinel.write_bytes(b"outside\n")
            replacement_before = self._directory_snapshot(self.artifact_directory)

            transaction.replace_staged(staged, "report.json")
            with self.assertRaisesRegex(OSError, "changed"):
                transaction.verify_directory()

        self.assertEqual((parked / "report.json").read_bytes(), b"new\n")
        self.assertEqual(
            self._directory_snapshot(self.artifact_directory),
            replacement_before,
        )

    def test_posix_cleanup_uses_binding_not_replacement_temp_name(self) -> None:
        parked = self.root / "gm2godot.parked"

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            if transaction.strategy != "posix_dir_fd":
                self.skipTest("descriptor-relative POSIX operations are unavailable")
            staged = transaction.stage_bytes(
                "report.json",
                b"stage\n",
                mode=0o600,
                suffix=".backup",
            )
            os.rename(self.artifact_directory, parked)
            self.artifact_directory.mkdir()
            collision = self.artifact_directory / staged.name
            collision.write_bytes(b"replacement collision\n")
            collision.chmod(0o444)
            sentinel = self.artifact_directory / "sentinel.txt"
            sentinel.write_bytes(b"outside\n")
            replacement_before = self._directory_snapshot(self.artifact_directory)

            cleanup_errors = transaction.cleanup({staged.name: staged})

        self.assertTrue(cleanup_errors)
        self.assertFalse((parked / staged.name).exists())
        self.assertEqual(
            self._directory_snapshot(self.artifact_directory),
            replacement_before,
        )

    @unittest.skipUnless(os.name == "posix", "POSIX relocation semantics required")
    def test_child_is_bound_before_parent_durability_barrier(self) -> None:
        parked = self.root / "gm2godot.parked"
        swapped = False

        def replace_child_during_root_sync(
            phase: str,
            directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal swapped
            if (
                phase != "before_sync"
                or os.path.abspath(directory_path) != os.path.abspath(self.root)
                or swapped
            ):
                return
            os.rename(self.artifact_directory, parked)
            self.artifact_directory.mkdir()
            (self.artifact_directory / "sentinel.txt").write_bytes(b"outside\n")
            swapped = True

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=replace_child_during_root_sync,
            ),
            self.assertRaisesRegex(OSError, "changed"),
        ):
            ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=True,
                description="test artifact directory",
            )

        self.assertTrue(swapped)
        self.assertEqual(
            self._directory_snapshot(self.artifact_directory),
            {
                "sentinel.txt": (
                    (self.artifact_directory / "sentinel.txt").stat().st_dev,
                    (self.artifact_directory / "sentinel.txt").stat().st_ino,
                    stat.S_IMODE(
                        (self.artifact_directory / "sentinel.txt").stat().st_mode
                    ),
                    b"outside\n",
                )
            },
        )
        self.assertEqual(list(parked.iterdir()), [])

    def test_backend_is_selected_before_staging_and_never_downgrades(self) -> None:
        with patch(
            "src.conversion.anchored_artifacts._descriptor_relative_supported",
            return_value=False,
        ):
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                self.assertEqual(transaction.strategy, "verified_path")
                staged = transaction.stage_bytes(
                    "report.json",
                    b"fallback\n",
                    mode=None,
                    suffix=".tmp",
                )
                self.assertEqual(transaction.strategy, "verified_path")
                self.assertTrue(Path(staged.path).is_file())
                self.assertIsNone(transaction.unlink_staged(staged))

    def test_leaf_validation_rejects_escape_and_windows_ads_names(self) -> None:
        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            invalid_names = ("", ".", "..", "../escape", "a/b", "a\\b", "x\x00y")
            for name in invalid_names:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    transaction.target_state(name)

            with patch.object(anchored_artifacts_module.os, "name", "nt"):
                for name in (
                    "report.json:stream",
                    "report.json.",
                    "report.json ",
                    "NUL",
                    "con.txt",
                    "COM1.log",
                    "name\x1f.json",
                ):
                    with self.subTest(windows_name=name), self.assertRaises(ValueError):
                        transaction.target_state(name)
                with self.assertRaisesRegex(ValueError, "must be unique"):
                    transaction.capture_snapshots(("Report.json", "report.json"))

    def test_modeled_windows_rejects_readonly_hardlink_before_chmod(self) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        os.link(target, alias)
        target.chmod(0o444)

        try:
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                with (
                    patch(
                        "src.conversion.anchored_artifacts._is_windows_platform",
                        return_value=True,
                    ),
                    self.assertRaisesRegex(
                        OSError,
                        "read-only multiply-linked artifact",
                    ),
                ):
                    transaction.publish_specs(
                        (ArtifactSpec("report.json", b"new\n"),)
                    )

            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertFalse(stat.S_IMODE(alias.stat().st_mode) & stat.S_IWUSR)
            self.assertEqual(
                sorted(path.name for path in self.artifact_directory.iterdir()),
                ["report.json"],
            )
        finally:
            target.chmod(0o600)

    def test_ordered_present_absent_publish_and_restore_share_one_core(self) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        first.chmod(0o640)
        second.write_bytes(b"second old\n")
        second.chmod(0o600)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshots = transaction.capture_snapshots(("first.json", "second.json"))
            receipts = transaction.publish_specs(
                (
                    ArtifactSpec("first.json", b"first new\n"),
                    ArtifactSpec("second.json", None),
                )
            )
            self.assertEqual(first.read_bytes(), b"first new\n")
            self.assertFalse(second.exists())
            self.assertIsNotNone(receipts[0])
            self.assertIsNone(receipts[1])

            transaction.restore_snapshots(snapshots, receipts)

        self.assertEqual(first.read_bytes(), b"first old\n")
        self.assertEqual(second.read_bytes(), b"second old\n")
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(second.stat().st_mode), 0o600)
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["first.json", "second.json"],
        )

    def test_ordered_publish_rolls_back_all_prior_mutations(self) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")

        def fail_after_second_commit(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            if phase == "before_commit_second.json_durability":
                raise OSError("injected ordered publication failure")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_after_second_commit,
                ),
                self.assertRaisesRegex(OSError, "ordered publication failure"),
            ):
                transaction.publish_specs(
                    (
                        ArtifactSpec("first.json", b"first new\n"),
                        ArtifactSpec("second.json", None),
                    )
                )

        self.assertEqual(first.read_bytes(), b"first old\n")
        self.assertEqual(second.read_bytes(), b"second old\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["first.json", "second.json"],
        )

    def test_ordered_publish_rechecks_later_target_after_prior_durability(self) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")
        changed_later_target = False

        def change_second_after_first_durability(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal changed_later_target
            if phase != "after_durability" or name != "first.json":
                return
            second.write_bytes(b"second external\n")
            changed_later_target = True

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=change_second_after_first_durability,
                ),
                self.assertRaisesRegex(OSError, "Artifact changed"),
            ):
                transaction.publish_specs(
                    (
                        ArtifactSpec("first.json", b"first new\n"),
                        ArtifactSpec("second.json", b"second new\n"),
                    )
                )

        self.assertTrue(changed_later_target)
        self.assertEqual(first.read_bytes(), b"first old\n")
        self.assertEqual(second.read_bytes(), b"second external\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["first.json", "second.json"],
        )

    def test_publish_rollback_continues_after_one_target_fails(self) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")
        first.chmod(0o640)
        second.chmod(0o600)
        rolling_back = False
        rollback_attempts: list[str] = []

        def fail_second_rollback_only(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal rolling_back
            if phase == "before_commit_second.json_durability":
                rolling_back = True
                raise OSError("injected ordered publication failure")
            if not rolling_back or phase != "before_commit" or name is None:
                return
            rollback_attempts.append(name)
            if name == "second.json":
                raise OSError("injected second rollback failure")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_second_rollback_only,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "ordered publication failure",
                ) as raised,
            ):
                transaction.publish_specs(
                    (
                        ArtifactSpec("first.json", b"first new\n"),
                        ArtifactSpec("second.json", b"second new\n"),
                    )
                )

        self.assertEqual(rollback_attempts, ["second.json", "first.json"])
        self.assertEqual(first.read_bytes(), b"first old\n")
        self.assertEqual(second.read_bytes(), b"second new\n")
        retained = [
            path
            for path in self.artifact_directory.iterdir()
            if path.name not in {"first.json", "second.json"}
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), b"second old\n")
        self.assertEqual(stat.S_IMODE(retained[0].stat().st_mode), 0o600)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(
            any("injected second rollback failure" in note for note in notes)
        )
        self.assertTrue(
            any("verified recovery artifact preserved" in note for note in notes)
        )

    def test_restore_rolls_back_completed_receipt_displacement(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o640)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshot = transaction.capture_snapshot("report.json")
            receipt = transaction.publish_specs(
                (ArtifactSpec("report.json", b"new\n"),)
            )[0]
            assert receipt is not None
            failures = 0

            def fail_after_receipt_displacement(
                phase: str,
                _directory_path: str,
                _name: str | None,
            ) -> None:
                nonlocal failures
                if phase == "after_replace" and failures == 0:
                    failures += 1
                    raise OSError("injected completed displacement failure")

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_after_receipt_displacement,
                ),
                self.assertRaisesRegex(OSError, "completed displacement failure"),
            ):
                transaction.restore_snapshots((snapshot,), (receipt,))

            self.assertEqual(target.read_bytes(), receipt.content)
            target_stat = target.stat()
            self.assertEqual(
                (target_stat.st_dev, target_stat.st_ino),
                receipt.fingerprint[:2],
            )
            transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)

    def test_restore_rejects_changed_receipt_before_staging_or_mutation(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshot = transaction.capture_snapshot("report.json")
            receipt = transaction.publish_specs(
                (ArtifactSpec("report.json", b"new\n"),)
            )[0]
            assert receipt is not None
            target.write_bytes(b"changed after publication\n")
            directory_before = self._directory_snapshot(self.artifact_directory)

            with self.assertRaisesRegex(OSError, "no longer matches its receipt"):
                transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertEqual(
            self._directory_snapshot(self.artifact_directory),
            directory_before,
        )

    def test_restore_rechecks_receipt_after_staging_before_mutation(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshot = transaction.capture_snapshot("report.json")
            receipt = transaction.publish_specs(
                (ArtifactSpec("report.json", b"new\n"),)
            )[0]
            assert receipt is not None
            changed_during_staging = False

            def replace_after_first_restore_stage(
                phase: str,
                _directory_path: str,
                _name: str | None,
            ) -> None:
                nonlocal changed_during_staging
                if phase != "after_stage" or changed_during_staging:
                    return
                target.write_bytes(b"changed during restore staging\n")
                changed_during_staging = True

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=replace_after_first_restore_stage,
                ),
                self.assertRaisesRegex(OSError, "no longer matches its receipt"),
            ):
                transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertTrue(changed_during_staging)
        self.assertEqual(target.read_bytes(), b"changed during restore staging\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_restore_does_not_displace_target_changed_at_replace_boundary(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshot = transaction.capture_snapshot("report.json")
            receipt = transaction.publish_specs(
                (ArtifactSpec("report.json", b"new\n"),)
            )[0]
            assert receipt is not None
            replaced = False

            def replace_at_native_boundary(
                phase: str,
                _directory_path: str,
                _name: str | None,
            ) -> None:
                nonlocal replaced
                if phase != "before_replace" or replaced:
                    return
                replacement = self.artifact_directory / "external.tmp"
                replacement.write_bytes(b"external replacement\n")
                os.replace(replacement, target)
                replaced = True

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=replace_at_native_boundary,
                ),
                self.assertRaisesRegex(OSError, "transaction file changed"),
            ):
                transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), b"external replacement\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_ordered_restore_rechecks_later_receipt_after_prior_durability(
        self,
    ) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshots = transaction.capture_snapshots(("first.json", "second.json"))
            receipts = transaction.publish_specs(
                (
                    ArtifactSpec("first.json", b"first new\n"),
                    ArtifactSpec("second.json", b"second new\n"),
                )
            )
            first_receipt, second_receipt = receipts
            assert first_receipt is not None
            assert second_receipt is not None
            changed_later_receipt = False

            def change_second_after_first_durability(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal changed_later_receipt
                if phase != "after_durability" or name != "first.json":
                    return
                second.write_bytes(b"second external\n")
                changed_later_receipt = True

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=change_second_after_first_durability,
                ),
                self.assertRaisesRegex(OSError, "no longer matches its receipt"),
            ):
                transaction.restore_snapshots(snapshots, receipts)

        self.assertTrue(changed_later_receipt)
        self.assertEqual(first.read_bytes(), first_receipt.content)
        self.assertEqual(second.read_bytes(), b"second external\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["first.json", "second.json"],
        )

    def test_restore_rollback_continues_and_retains_exact_receipt(self) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshots = transaction.capture_snapshots(("first.json", "second.json"))
            receipts = transaction.publish_specs(
                (
                    ArtifactSpec("first.json", b"first new\n"),
                    ArtifactSpec("second.json", b"second new\n"),
                )
            )
            first_receipt, second_receipt = receipts
            assert first_receipt is not None
            assert second_receipt is not None
            rolling_back = False
            rollback_attempts: list[str] = []

            def fail_second_rollback_only(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal rolling_back
                if phase == "before_restore_second.json_durability":
                    rolling_back = True
                    raise OSError("injected ordered restore failure")
                if not rolling_back or phase != "before_commit" or name is None:
                    return
                rollback_attempts.append(name)
                if name == "second.json":
                    raise OSError("injected receipt rollback failure")

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_second_rollback_only,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "ordered restore failure",
                ) as raised,
            ):
                transaction.restore_snapshots(snapshots, receipts)

            transaction.verify_receipt(first_receipt)

        self.assertEqual(rollback_attempts, ["second.json", "first.json"])
        self.assertEqual(first.read_bytes(), first_receipt.content)
        self.assertEqual(second.read_bytes(), b"second old\n")
        retained = [
            path
            for path in self.artifact_directory.iterdir()
            if path.name not in {"first.json", "second.json"}
        ]
        self.assertEqual(len(retained), 1)
        retained_stat = retained[0].stat()
        self.assertEqual(
            (retained_stat.st_dev, retained_stat.st_ino),
            second_receipt.fingerprint[:2],
        )
        self.assertEqual(retained[0].read_bytes(), second_receipt.content)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(
            any("injected receipt rollback failure" in note for note in notes)
        )
        self.assertTrue(
            any("verified recovery artifact preserved" in note for note in notes)
        )

    @unittest.skipUnless(os.name == "nt", "native Windows handle semantics required")
    def test_windows_binding_blocks_directory_and_root_relocation(self) -> None:
        parked_directory = self.root / "gm2godot.parked"
        parked_root = self.temp_dir / "project.parked"

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ):
            with self.assertRaises(OSError):
                os.rename(self.artifact_directory, parked_directory)
            with self.assertRaises(OSError):
                os.rename(self.root, parked_root)

        os.rename(self.artifact_directory, parked_directory)
        os.rename(parked_directory, self.artifact_directory)
        os.rename(self.root, parked_root)
        os.rename(parked_root, self.root)

    @unittest.skipUnless(os.name == "nt", "native Windows handle semantics required")
    def test_windows_child_prebind_swap_to_junction_is_rejected(self) -> None:
        outside = self.temp_dir / "outside-prebind"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_bytes(b"outside\n")
        parked = self.root / "gm2godot.parked"
        real_open = cast(
            Callable[[str, tuple[int, int]], tuple[Any, int]],
            getattr(anchored_artifacts_module, "_open_windows_directory_handle"),
        )
        swapped = False

        def swap_before_child_handle(
            path: str,
            expected_identity: tuple[int, int],
        ) -> tuple[Any, int]:
            nonlocal swapped
            if (
                os.path.normcase(os.path.abspath(path))
                == os.path.normcase(os.path.abspath(self.artifact_directory))
                and not swapped
            ):
                os.rename(self.artifact_directory, parked)
                completed = subprocess.run(
                    [
                        "cmd.exe",
                        "/d",
                        "/c",
                        "mklink",
                        "/J",
                        str(self.artifact_directory),
                        str(outside),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                swapped = True
            return real_open(path, expected_identity)

        try:
            with (
                patch(
                    "src.conversion.anchored_artifacts._open_windows_directory_handle",
                    side_effect=swap_before_child_handle,
                ),
                self.assertRaisesRegex(OSError, "changed"),
            ):
                ByteArtifactTransaction.open(
                    str(self.root),
                    "gm2godot",
                    create=False,
                    description="test artifact directory",
                )
            self.assertTrue(swapped)
            self.assertEqual(sentinel.read_bytes(), b"outside\n")
            self.assertEqual(list(parked.iterdir()), [])
        finally:
            if self.artifact_directory.is_junction():
                os.rmdir(self.artifact_directory)
            if parked.exists():
                os.rename(parked, self.artifact_directory)

    @unittest.skipUnless(os.name == "nt", "native Windows junction semantics required")
    def test_windows_binding_rejects_real_junction_without_touching_target(self) -> None:
        outside = self.temp_dir / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_bytes(b"outside\n")
        self.artifact_directory.rmdir()
        completed = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(self.artifact_directory),
                str(outside),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        try:
            junction_stat = os.lstat(self.artifact_directory)
            attributes_seen: list[int] = []
            real_attributes = cast(
                Callable[[Any, int, str], int],
                getattr(anchored_artifacts_module, "_windows_directory_attributes"),
            )

            def record_attributes(kernel32: Any, handle: int, path: str) -> int:
                attributes = real_attributes(kernel32, handle, path)
                attributes_seen.append(attributes)
                return attributes

            with (
                patch(
                    "src.conversion.anchored_artifacts._windows_directory_attributes",
                    side_effect=record_attributes,
                ),
                self.assertRaisesRegex(OSError, "changed"),
            ):
                open_windows_directory = cast(
                    Callable[[str, tuple[int, int]], tuple[Any, int]],
                    getattr(
                        anchored_artifacts_module,
                        "_open_windows_directory_handle",
                    ),
                )
                open_windows_directory(
                    str(self.artifact_directory),
                    (junction_stat.st_dev, junction_stat.st_ino),
                )
            self.assertTrue(attributes_seen)
            directory_attribute = cast(
                int,
                getattr(
                    anchored_artifacts_module,
                    "_WINDOWS_FILE_ATTRIBUTE_DIRECTORY",
                ),
            )
            reparse_attribute = cast(
                int,
                getattr(
                    anchored_artifacts_module,
                    "_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT",
                ),
            )
            self.assertTrue(
                attributes_seen[-1] & directory_attribute
            )
            self.assertTrue(
                attributes_seen[-1] & reparse_attribute
            )
            with self.assertRaisesRegex(OSError, "redirected"):
                ByteArtifactTransaction.open(
                    str(self.root),
                    "gm2godot",
                    create=False,
                    description="test artifact directory",
                )
            self.assertEqual(sentinel.read_bytes(), b"outside\n")
        finally:
            os.rmdir(self.artifact_directory)
            self.artifact_directory.mkdir()

    @unittest.skipUnless(os.name == "nt", "native Windows move semantics required")
    def test_windows_moves_use_extended_write_through_paths(self) -> None:
        target_name = "report-Δ-日本語.json"
        target = self.artifact_directory / target_name
        target.write_bytes(b"old\n")
        calls: list[tuple[str, str, int]] = []

        class RecordingWindowsApi:
            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped

            def MoveFileExW(
                self,
                source: str,
                destination: str,
                flags: int,
            ) -> int:
                calls.append((source, destination, flags))
                move = cast(
                    Callable[[str, str, int], int],
                    getattr(self.wrapped, "MoveFileExW"),
                )
                return move(source, destination, flags)

            def __getattr__(self, name: str) -> Any:
                return getattr(self.wrapped, name)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            self.assertEqual(transaction.strategy, "windows_handle")
            transaction.directory.windows_api = RecordingWindowsApi(
                transaction.directory.windows_api
            )
            receipt = transaction.publish_specs(
                (ArtifactSpec(target_name, b"new\n"),)
            )[0]
            assert receipt is not None
            absent_receipt = transaction.publish_specs(
                (ArtifactSpec(target_name, None),)
            )[0]
            self.assertIsNone(absent_receipt)

        self.assertFalse(target.exists())
        self.assertEqual(len(calls), 2)
        expected_flags = (
            cast(
                int,
                getattr(
                    anchored_artifacts_module,
                    "_WINDOWS_MOVEFILE_REPLACE_EXISTING",
                ),
            )
            | cast(
                int,
                getattr(
                    anchored_artifacts_module,
                    "_WINDOWS_MOVEFILE_WRITE_THROUGH",
                ),
            )
        )
        for source, destination, flags in calls:
            self.assertTrue(source.startswith("\\\\?\\"))
            self.assertTrue(destination.startswith("\\\\?\\"))
            self.assertEqual(flags, expected_flags)
        self.assertTrue(calls[1][1].endswith(".tombstone"))

    @unittest.skipUnless(os.name == "nt", "native Windows hardlinks required")
    def test_windows_readonly_hardlink_is_rejected_without_alias_mutation(self) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        os.link(target, alias)
        target.chmod(0o444)
        try:
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                with self.assertRaisesRegex(
                    OSError,
                    "read-only multiply-linked artifact",
                ):
                    transaction.publish_specs(
                        (ArtifactSpec("report.json", b"new\n"),)
                    )
            target_stat = target.stat()
            alias_stat = alias.stat()
            self.assertEqual(
                (target_stat.st_dev, target_stat.st_ino),
                (alias_stat.st_dev, alias_stat.st_ino),
            )
            self.assertGreaterEqual(target_stat.st_nlink, 2)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertFalse(stat.S_IMODE(target_stat.st_mode) & stat.S_IWUSR)
            self.assertFalse(stat.S_IMODE(alias_stat.st_mode) & stat.S_IWUSR)
        finally:
            target.chmod(0o600)

    @unittest.skipUnless(os.name == "nt", "native Windows attributes required")
    def test_windows_single_link_readonly_publish_and_restore(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        try:
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                snapshot = transaction.capture_snapshot("report.json")
                receipt = transaction.publish_specs(
                    (ArtifactSpec("report.json", b"new\n"),)
                )[0]
                assert receipt is not None
                self.assertEqual(target.read_bytes(), b"new\n")
                self.assertFalse(
                    stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR
                )
                transaction.restore_snapshots((snapshot,), (receipt,))

            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertEqual(
                sorted(path.name for path in self.artifact_directory.iterdir()),
                ["report.json"],
            )
        finally:
            if target.exists():
                target.chmod(0o600)

    @unittest.skipUnless(os.name == "nt", "native Windows long paths required")
    def test_windows_long_unicode_publish_and_restore(self) -> None:
        long_root = self.temp_dir / ("a" * 120) / ("b" * 120) / "project-日本語"
        long_root.mkdir(parents=True)
        child_name = "gm2godot-Δοκιμή"
        target_name = "architecture-policy-日本語.json"
        target = long_root / child_name / target_name
        self.assertGreater(len(str(target)), 260)

        with ByteArtifactTransaction.open(
            str(long_root),
            child_name,
            create=True,
            description="long Unicode artifact directory",
        ) as transaction:
            snapshot = transaction.capture_snapshot(target_name)
            receipt = transaction.publish_specs(
                (ArtifactSpec(target_name, "受け渡しΔ\n".encode()),)
            )[0]
            assert receipt is not None
            transaction.verify_receipt(receipt)
            transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertFalse(target.exists())
        self.assertEqual(list((long_root / child_name).iterdir()), [])

    @staticmethod
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


if __name__ == "__main__":
    unittest.main()
