from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable, cast
from unittest.mock import patch

from src.conversion import managed_output_workspace as workspace_module
from src.conversion.anchored_artifacts import VerifiedDirectory
from src.conversion.managed_output_workspace import (
    DESTINATION_LOCK_NAME,
    ManagedOutputWorkspace,
    WORKSPACE_PARENT_MARKER_NAME,
    WORKSPACE_PARENT_NAME,
    WORKSPACE_STAGE_MARKER_NAME,
)


class _TestCancellation(Exception):
    pass


class TestManagedOutputWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.destination = self.temp_dir / "project"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def _make_destination(self) -> None:
        self.destination.mkdir()

    def _assert_no_transaction_stage(self) -> None:
        workspace_parent = self.destination / WORKSPACE_PARENT_NAME
        self.assertTrue(workspace_parent.is_dir())
        self.assertEqual(
            sorted(path.name for path in workspace_parent.iterdir()),
            [WORKSPACE_PARENT_MARKER_NAME],
        )

    @staticmethod
    def _mode(path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    def assertModeEqual(self, actual: int, expected: int) -> None:
        if os.name == "nt":
            self.assertEqual(
                bool(actual & stat.S_IWUSR),
                bool(expected & stat.S_IWUSR),
            )
            return
        self.assertEqual(actual, expected)

    def test_missing_destination_creates_destination_local_bound_stage(self) -> None:
        nested_destination = self.destination / "nested" / "godot"

        with ManagedOutputWorkspace.open(nested_destination) as workspace:
            stage = Path(workspace.stage_path)
            self.assertTrue(stage.is_dir())
            self.assertEqual(
                stage.parent,
                (nested_destination / WORKSPACE_PARENT_NAME).resolve(),
            )
            self.assertEqual(workspace.destination_device, workspace.stage_device)
            self.assertEqual(len(workspace.transaction_id), 32)
            self.assertTrue((stage / WORKSPACE_STAGE_MARKER_NAME).is_file())
            self.assertTrue(workspace.locked)

        self.destination = nested_destination
        self.assertTrue((nested_destination / DESTINATION_LOCK_NAME).is_file())
        self._assert_no_transaction_stage()

    def test_existing_destination_allowlist_copies_only_requested_regular_file(
        self,
    ) -> None:
        self._make_destination()
        managed = self.destination / "managed"
        managed.mkdir()
        requested = managed / "requested.txt"
        requested.write_bytes(b"requested payload\n")
        requested.chmod(0o640)
        unrequested = managed / "unrequested.txt"
        unrequested.write_bytes(b"unrequested payload\n")
        outside = self.temp_dir / "outside.txt"
        outside.write_bytes(b"outside sentinel\n")
        redirected = managed / "redirected.txt"
        redirected.symlink_to(outside)
        requested_mode = self._mode(requested)

        with ManagedOutputWorkspace.open(self.destination) as workspace:
            snapshots = workspace.snapshot_files(("managed/requested.txt",))
            receipts = workspace.copy_snapshots(snapshots)
            staged_requested = Path(workspace.stage_path) / "managed" / "requested.txt"

            self.assertEqual(len(snapshots), 1)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(staged_requested.read_bytes(), b"requested payload\n")
            self.assertModeEqual(self._mode(staged_requested), requested_mode)
            self.assertFalse(
                (Path(workspace.stage_path) / "managed" / "unrequested.txt").exists()
            )
            self.assertFalse(
                (Path(workspace.stage_path) / "managed" / "redirected.txt").exists()
            )

        self.assertEqual(requested.read_bytes(), b"requested payload\n")
        self.assertEqual(unrequested.read_bytes(), b"unrequested payload\n")
        self.assertEqual(outside.read_bytes(), b"outside sentinel\n")
        self.assertTrue(redirected.is_symlink())
        self.assertModeEqual(self._mode(requested), requested_mode)
        self._assert_no_transaction_stage()

    def test_cancellation_removes_only_private_stage(self) -> None:
        self._make_destination()
        user_file = self.destination / "user-owned.txt"
        user_file.write_bytes(b"user bytes\n")
        user_file.chmod(0o640)
        original_mode = self._mode(user_file)

        with self.assertRaises(_TestCancellation):
            with ManagedOutputWorkspace.open(self.destination) as workspace:
                snapshots = workspace.snapshot_files(("user-owned.txt",))
                workspace.copy_snapshots(snapshots)
                raise _TestCancellation

        self.assertEqual(user_file.read_bytes(), b"user bytes\n")
        self.assertModeEqual(self._mode(user_file), original_mode)
        self._assert_no_transaction_stage()

    def test_ordinary_staging_failure_cleans_partial_private_copy(self) -> None:
        self._make_destination()
        first = self.destination / "first.txt"
        second = self.destination / "second.txt"
        first.write_bytes(b"first\n")
        second.write_bytes(b"second\n")
        first_mode = self._mode(first)
        second_mode = self._mode(second)
        real_hook = cast(
            Callable[[str, str], None],
            getattr(workspace_module, "_before_workspace_phase"),
        )
        stage_creations = 0

        def fail_second_stage_create(phase: str, path: str) -> None:
            nonlocal stage_creations
            real_hook(phase, path)
            if phase == "before_stage_file_create":
                stage_creations += 1
                if stage_creations == 2:
                    raise OSError("injected ordinary staging failure")

        with (
            patch.object(
                workspace_module,
                "_before_workspace_phase",
                side_effect=fail_second_stage_create,
            ),
            self.assertRaisesRegex(OSError, "ordinary staging failure"),
        ):
            with ManagedOutputWorkspace.open(self.destination) as workspace:
                snapshots = workspace.snapshot_files(("first.txt", "second.txt"))
                workspace.copy_snapshots(snapshots)

        self.assertEqual(stage_creations, 2)
        self.assertEqual(first.read_bytes(), b"first\n")
        self.assertEqual(second.read_bytes(), b"second\n")
        self.assertModeEqual(self._mode(first), first_mode)
        self.assertModeEqual(self._mode(second), second_mode)
        self._assert_no_transaction_stage()

    def test_second_session_fails_before_creating_another_stage(self) -> None:
        self._make_destination()
        first = ManagedOutputWorkspace.open(
            self.destination,
            transaction_id="1" * 32,
        )
        try:
            workspace_parent = self.destination / WORKSPACE_PARENT_NAME
            names_before = sorted(path.name for path in workspace_parent.iterdir())
            with self.assertRaisesRegex(OSError, "already holds"):
                ManagedOutputWorkspace.open(
                    self.destination,
                    transaction_id="2" * 32,
                )
            self.assertEqual(
                sorted(path.name for path in workspace_parent.iterdir()),
                names_before,
            )
        finally:
            first.close()
        self._assert_no_transaction_stage()

    def test_destination_lock_contends_across_processes(self) -> None:
        self._make_destination()
        first = ManagedOutputWorkspace.open(
            self.destination,
            transaction_id="3" * 32,
        )
        try:
            workspace_parent = self.destination / WORKSPACE_PARENT_NAME
            names_before = sorted(path.name for path in workspace_parent.iterdir())
            child = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    (
                        "import sys\n"
                        "from src.conversion.managed_output_workspace import "
                        "ManagedOutputWorkspace\n"
                        "try:\n"
                        "    ManagedOutputWorkspace.open(sys.argv[1])\n"
                        "except OSError as error:\n"
                        "    print(error)\n"
                        "    raise SystemExit(0)\n"
                        "raise SystemExit(1)\n"
                    ),
                    str(self.destination),
                ),
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertIn("already holds", child.stdout)
            self.assertEqual(
                sorted(path.name for path in workspace_parent.iterdir()),
                names_before,
            )
        finally:
            first.close()
        self._assert_no_transaction_stage()

    def test_unknown_lock_content_is_preserved_and_rejected(self) -> None:
        self._make_destination()
        lock = self.destination / DESTINATION_LOCK_NAME
        lock.write_bytes(b"unknown lock collision\n")

        with self.assertRaisesRegex(OSError, "unknown or incomplete"):
            ManagedOutputWorkspace.open(self.destination)

        self.assertEqual(lock.read_bytes(), b"unknown lock collision\n")
        self.assertFalse((self.destination / WORKSPACE_PARENT_NAME).exists())

    def test_unknown_workspace_parent_collision_is_preserved(self) -> None:
        self._make_destination()
        workspace_parent = self.destination / WORKSPACE_PARENT_NAME
        workspace_parent.mkdir()
        sentinel = workspace_parent / "user-sentinel.txt"
        sentinel.write_bytes(b"do not remove\n")

        with self.assertRaisesRegex(OSError, "preserved for inspection"):
            ManagedOutputWorkspace.open(self.destination)

        self.assertEqual(sentinel.read_bytes(), b"do not remove\n")
        self.assertEqual(
            sorted(path.name for path in workspace_parent.iterdir()),
            ["user-sentinel.txt"],
        )

    def test_stage_same_filesystem_check_runs_before_marker_creation(self) -> None:
        self._make_destination()
        real_verify = cast(
            Callable[..., int | None],
            getattr(workspace_module, "_verify_binding_boundary"),
        )
        rejected_stage = False

        def reject_modeled_cross_device_stage(
            binding: VerifiedDirectory,
            *,
            expected_device: int,
            expected_mount_id: int | None,
            allow_mountpoint: bool = False,
        ) -> int | None:
            nonlocal rejected_stage
            if binding.description == "managed-output stage":
                rejected_stage = True
                raise OSError(
                    "Refusing a managed-output path that crosses a filesystem boundary"
                )
            return real_verify(
                binding,
                expected_device=expected_device,
                expected_mount_id=expected_mount_id,
                allow_mountpoint=allow_mountpoint,
            )

        with (
            patch.object(
                workspace_module,
                "_verify_binding_boundary",
                side_effect=reject_modeled_cross_device_stage,
            ),
            self.assertRaisesRegex(OSError, "filesystem boundary"),
        ):
            ManagedOutputWorkspace.open(self.destination)

        self.assertTrue(rejected_stage)
        self._assert_no_transaction_stage()

    def test_invalid_transaction_id_is_rejected_before_destination_creation(self) -> None:
        with self.assertRaisesRegex(ValueError, "32 lowercase hexadecimal"):
            ManagedOutputWorkspace.open(
                self.destination,
                transaction_id="NOT-A-TRANSACTION",
            )
        self.assertFalse(self.destination.exists())

    def test_read_only_source_mode_and_bytes_are_unchanged(self) -> None:
        self._make_destination()
        source = self.destination / "readonly.txt"
        source.write_bytes(b"read-only source\n")
        source.chmod(0o444)
        source_mode = self._mode(source)
        try:
            with ManagedOutputWorkspace.open(self.destination) as workspace:
                snapshots = workspace.snapshot_files(("readonly.txt",))
                workspace.copy_snapshots(snapshots)
                staged = Path(workspace.stage_path) / "readonly.txt"
                self.assertEqual(staged.read_bytes(), b"read-only source\n")
                self.assertModeEqual(self._mode(staged), source_mode)

            self.assertEqual(source.read_bytes(), b"read-only source\n")
            self.assertModeEqual(self._mode(source), source_mode)
            self._assert_no_transaction_stage()
        finally:
            if source.exists():
                source.chmod(0o600)

    def test_cleanup_rejects_hardlinked_stage_then_retries_safely(self) -> None:
        self._make_destination()
        source = self.destination / "source.txt"
        source.write_bytes(b"stage hardlink sentinel\n")
        alias = self.destination / "user-alias.txt"
        workspace = ManagedOutputWorkspace.open(self.destination)
        try:
            snapshots = workspace.snapshot_files(("source.txt",))
            workspace.copy_snapshots(snapshots)
            staged = Path(workspace.stage_path) / "source.txt"
            os.link(staged, alias)

            with self.assertRaisesRegex(OSError, "multiply-linked"):
                workspace.cleanup()

            self.assertEqual(staged.read_bytes(), b"stage hardlink sentinel\n")
            self.assertEqual(alias.read_bytes(), b"stage hardlink sentinel\n")
            self.assertGreaterEqual(staged.stat().st_nlink, 2)
            alias.unlink()
            workspace.cleanup()
        finally:
            workspace.close()

        self.assertEqual(source.read_bytes(), b"stage hardlink sentinel\n")
        self.assertFalse(alias.exists())
        self._assert_no_transaction_stage()

    def test_changed_ownership_marker_is_preserved_until_restored(self) -> None:
        self._make_destination()
        workspace = ManagedOutputWorkspace.open(self.destination)
        stage = Path(workspace.stage_path)
        marker = stage / WORKSPACE_STAGE_MARKER_NAME
        original_marker = marker.read_bytes()
        try:
            marker.write_bytes(b'{"unknown":"marker"}\n')
            with self.assertRaisesRegex(OSError, "ownership marker changed"):
                workspace.cleanup()
            self.assertTrue(stage.is_dir())
            self.assertEqual(marker.read_bytes(), b'{"unknown":"marker"}\n')

            marker.write_bytes(original_marker)
            workspace.cleanup()
        finally:
            workspace.close()
        self._assert_no_transaction_stage()

    def test_cleanup_retry_after_transient_pre_quarantine_failure(self) -> None:
        self._make_destination()
        workspace = ManagedOutputWorkspace.open(self.destination)
        original_stage = Path(workspace.stage_path)
        failed = False
        real_hook = cast(
            Callable[[str, str], None],
            getattr(workspace_module, "_before_workspace_phase"),
        )

        def fail_once(phase: str, path: str) -> None:
            nonlocal failed
            real_hook(phase, path)
            if phase == "before_stage_cleanup_quarantine" and not failed:
                failed = True
                raise OSError("injected cleanup retry")

        try:
            with (
                patch.object(
                    workspace_module,
                    "_before_workspace_phase",
                    side_effect=fail_once,
                ),
                self.assertRaisesRegex(OSError, "cleanup retry"),
            ):
                workspace.cleanup()
            self.assertTrue(original_stage.is_dir())
            workspace.cleanup()
        finally:
            workspace.close()

        self.assertTrue(failed)
        self._assert_no_transaction_stage()

    def test_cleanup_retry_after_entry_was_quarantined(self) -> None:
        self._make_destination()
        source = self.destination / "source.txt"
        source.write_bytes(b"cleanup retry payload\n")
        workspace = ManagedOutputWorkspace.open(self.destination)
        snapshots = workspace.snapshot_files(("source.txt",))
        workspace.copy_snapshots(snapshots)
        failed = False

        def fail_after_entry_quarantine(phase: str, _path: str) -> None:
            nonlocal failed
            if phase == "before_cleanup_file_remove" and not failed:
                failed = True
                raise OSError("injected quarantined cleanup retry")

        try:
            with (
                patch.object(
                    workspace_module,
                    "_before_workspace_phase",
                    side_effect=fail_after_entry_quarantine,
                ),
                self.assertRaisesRegex(OSError, "quarantined cleanup retry"),
            ):
                workspace.cleanup()
            retained_stage = Path(workspace.stage_path)
            self.assertTrue(retained_stage.is_dir())
            self.assertNotIn("source.txt", {path.name for path in retained_stage.iterdir()})
            workspace.cleanup()
        finally:
            workspace.close()

        self.assertTrue(failed)
        self.assertEqual(source.read_bytes(), b"cleanup retry payload\n")
        self._assert_no_transaction_stage()

    def test_stage_symlink_is_preserved_without_touching_external_target(self) -> None:
        self._make_destination()
        external = self.temp_dir / "external-stage-file.txt"
        external.write_bytes(b"external stage sentinel\n")
        workspace = ManagedOutputWorkspace.open(self.destination)
        stage_link = Path(workspace.stage_path) / "redirected.txt"
        try:
            stage_link.symlink_to(external)
            with self.assertRaisesRegex(OSError, "redirected"):
                workspace.cleanup()
            self.assertTrue(stage_link.is_symlink())
            self.assertEqual(external.read_bytes(), b"external stage sentinel\n")

            stage_link.unlink()
            workspace.cleanup()
        finally:
            workspace.close()

        self.assertEqual(external.read_bytes(), b"external stage sentinel\n")
        self._assert_no_transaction_stage()

    def test_symlink_source_is_rejected_without_touching_external_target(self) -> None:
        self._make_destination()
        external = self.temp_dir / "external.txt"
        external.write_bytes(b"external sentinel\n")
        redirected = self.destination / "redirected.txt"
        redirected.symlink_to(external)

        with ManagedOutputWorkspace.open(self.destination) as workspace:
            with self.assertRaisesRegex(OSError, "redirected"):
                workspace.snapshot_files(("redirected.txt",))

        self.assertTrue(redirected.is_symlink())
        self.assertEqual(external.read_bytes(), b"external sentinel\n")
        self._assert_no_transaction_stage()

    def test_hardlinked_source_is_rejected_without_alias_mutation(self) -> None:
        self._make_destination()
        source = self.destination / "source.txt"
        alias = self.temp_dir / "external-alias.txt"
        source.write_bytes(b"external alias sentinel\n")
        os.link(source, alias)
        source_mode = self._mode(source)

        with ManagedOutputWorkspace.open(self.destination) as workspace:
            with self.assertRaisesRegex(OSError, "multiply-linked"):
                workspace.snapshot_files(("source.txt",))

        self.assertEqual(source.read_bytes(), b"external alias sentinel\n")
        self.assertEqual(alias.read_bytes(), b"external alias sentinel\n")
        self.assertModeEqual(self._mode(source), source_mode)
        self.assertModeEqual(self._mode(alias), source_mode)
        self._assert_no_transaction_stage()

    def test_modeled_nested_mount_is_rejected_without_reading_sentinel(self) -> None:
        self._make_destination()
        mounted = self.destination / "managed" / "mounted"
        mounted.mkdir(parents=True)
        sentinel = mounted / "external-sentinel.txt"
        sentinel.write_bytes(b"mounted sentinel\n")
        mounted_normalized = os.path.normcase(os.path.realpath(mounted))
        real_ismount = os.path.ismount

        def modeled_mount(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> bool:
            normalized = os.path.normcase(os.path.realpath(path))
            if normalized == mounted_normalized:
                return True
            return real_ismount(path)

        with ManagedOutputWorkspace.open(self.destination) as workspace:
            with (
                patch.object(
                    workspace_module.os.path,
                    "ismount",
                    side_effect=modeled_mount,
                ),
                self.assertRaisesRegex(OSError, "mount boundary"),
            ):
                workspace.snapshot_files(("managed/mounted/external-sentinel.txt",))

        self.assertEqual(sentinel.read_bytes(), b"mounted sentinel\n")
        self._assert_no_transaction_stage()

    @unittest.skipIf(os.name == "nt", "physical POSIX path swap required")
    def test_posix_source_directory_swap_is_rejected_without_traversal(self) -> None:
        self._make_destination()
        managed = self.destination / "managed"
        managed.mkdir()
        (managed / "payload.txt").write_bytes(b"managed source\n")
        parked = self.destination / "managed.parked"
        external = self.temp_dir / "outside"
        external.mkdir()
        external_sentinel = external / "payload.txt"
        external_sentinel.write_bytes(b"outside sentinel\n")
        managed_normalized = os.path.normcase(os.path.realpath(managed))
        swapped = False

        def swap_before_bind(phase: str, path: str) -> None:
            nonlocal swapped
            if (
                phase == "before_relative_directory_bind"
                and os.path.normcase(os.path.realpath(path)) == managed_normalized
                and not swapped
            ):
                managed.rename(parked)
                managed.symlink_to(external, target_is_directory=True)
                swapped = True

        try:
            with ManagedOutputWorkspace.open(self.destination) as workspace:
                with (
                    patch.object(
                        workspace_module,
                        "_before_workspace_phase",
                        side_effect=swap_before_bind,
                    ),
                    self.assertRaisesRegex(OSError, "redirected|changed"),
                ):
                    workspace.snapshot_files(("managed/payload.txt",))
            self.assertTrue(swapped)
            self.assertEqual(external_sentinel.read_bytes(), b"outside sentinel\n")
            self.assertTrue(managed.is_symlink())
        finally:
            if managed.is_symlink():
                managed.unlink()
            if parked.exists():
                parked.rename(managed)

        self._assert_no_transaction_stage()

    @unittest.skipIf(os.name == "nt", "physical POSIX directory replacement required")
    def test_posix_stage_replacement_is_preserved_without_target_traversal(self) -> None:
        self._make_destination()
        external = self.temp_dir / "outside-stage"
        external.mkdir()
        external_sentinel = external / "sentinel.txt"
        external_sentinel.write_bytes(b"outside stage sentinel\n")
        workspace = ManagedOutputWorkspace.open(self.destination)
        stage = Path(workspace.stage_path)
        parked = stage.with_name(stage.name + ".parked")
        try:
            stage.rename(parked)
            stage.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(OSError, "changed"):
                workspace.cleanup()
            self.assertEqual(
                external_sentinel.read_bytes(),
                b"outside stage sentinel\n",
            )
            self.assertTrue(stage.is_symlink())

            stage.unlink()
            parked.rename(stage)
            workspace.cleanup()
        finally:
            if stage.is_symlink():
                stage.unlink()
            if parked.exists() and not stage.exists():
                parked.rename(stage)
            workspace.close()

        self._assert_no_transaction_stage()

    def test_destination_symlink_component_is_rejected_without_target_creation(
        self,
    ) -> None:
        outside = self.temp_dir / "outside-destination"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_bytes(b"outside destination sentinel\n")
        redirected = self.temp_dir / "redirected"
        redirected.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(OSError, "redirected"):
            ManagedOutputWorkspace.open(redirected / "must-not-exist")

        self.assertEqual(sentinel.read_bytes(), b"outside destination sentinel\n")
        self.assertFalse((outside / "must-not-exist").exists())

    @unittest.skipUnless(sys.platform == "win32", "native Windows junction required")
    def test_windows_junction_source_is_rejected_without_touching_target(self) -> None:
        self._make_destination()
        external = self.temp_dir / "junction-target"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"junction sentinel\n")
        junction = self.destination / "managed"
        completed = subprocess.run(
            (
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(junction),
                str(external),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        try:
            with ManagedOutputWorkspace.open(self.destination) as workspace:
                with self.assertRaisesRegex(OSError, "redirected"):
                    workspace.snapshot_files(("managed/sentinel.txt",))
            self.assertEqual(sentinel.read_bytes(), b"junction sentinel\n")
        finally:
            if os.path.isjunction(junction):
                os.rmdir(junction)
        self._assert_no_transaction_stage()

    @unittest.skipUnless(sys.platform == "win32", "native Windows junction required")
    def test_windows_junction_stage_cleanup_preserves_external_target(self) -> None:
        self._make_destination()
        external = self.temp_dir / "stage-junction-target"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"stage junction sentinel\n")
        workspace = ManagedOutputWorkspace.open(self.destination)
        junction = Path(workspace.stage_path) / "redirected"
        completed = subprocess.run(
            (
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(junction),
                str(external),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        try:
            with self.assertRaisesRegex(OSError, "redirected"):
                workspace.cleanup()
            self.assertEqual(sentinel.read_bytes(), b"stage junction sentinel\n")
            self.assertTrue(os.path.isjunction(junction))

            os.rmdir(junction)
            workspace.cleanup()
        finally:
            if os.path.isjunction(junction):
                os.rmdir(junction)
            workspace.close()

        self.assertEqual(sentinel.read_bytes(), b"stage junction sentinel\n")
        self._assert_no_transaction_stage()

    @unittest.skipUnless(sys.platform == "win32", "native Windows attributes required")
    def test_windows_read_only_stage_tree_cleanup_preserves_source(self) -> None:
        self._make_destination()
        source_directory = self.destination / "managed"
        source_directory.mkdir()
        source = source_directory / "readonly.txt"
        source.write_bytes(b"native Windows read-only sentinel\n")
        source.chmod(stat.S_IREAD)
        workspace = ManagedOutputWorkspace.open(self.destination)
        try:
            snapshots = workspace.snapshot_files(("managed/readonly.txt",))
            workspace.copy_snapshots(snapshots)
            staged_directory = Path(workspace.stage_path) / "managed"
            staged_file = staged_directory / "readonly.txt"
            staged_file.chmod(stat.S_IREAD)
            staged_directory.chmod(stat.S_IREAD)
            workspace.cleanup()

            self.assertEqual(
                source.read_bytes(),
                b"native Windows read-only sentinel\n",
            )
            self.assertFalse(self._mode(source) & stat.S_IWUSR)
        finally:
            if source.exists():
                source.chmod(stat.S_IWRITE | stat.S_IREAD)
            workspace.close()
        self._assert_no_transaction_stage()


if __name__ == "__main__":
    unittest.main()
