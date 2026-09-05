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
from src.conversion.anchored_artifacts import ArtifactSpec, ByteArtifactTransaction, StagedArtifact


class TestAnchoredArtifacts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.root = self.temp_dir / "project"
        self.artifact_directory = self.root / "gm2godot"
        self.root.mkdir()
        self.artifact_directory.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def assertArtifactModeEqual(self, actual: int, expected: int) -> None:
        if os.name == "nt":
            self.assertEqual(
                bool(actual & stat.S_IWUSR),
                bool(expected & stat.S_IWUSR),
            )
            return
        self.assertEqual(actual, expected)

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
        expected_strategy = (
            "windows_handle" if os.name == "nt" else "verified_path"
        )
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
                self.assertEqual(transaction.strategy, expected_strategy)
                staged = transaction.stage_bytes(
                    "report.json",
                    b"fallback\n",
                    mode=None,
                    suffix=".tmp",
                )
                self.assertEqual(transaction.strategy, expected_strategy)
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

    @unittest.skipUnless(os.name == "posix", "POSIX mode semantics required")
    def test_post_write_stage_mode_change_is_preserved_on_rejection(self) -> None:
        staged_path: Path | None = None
        mode_changed = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            real_stat = transaction.directory.stat

            def change_mode_before_first_stage_stat(name: str) -> os.stat_result:
                nonlocal mode_changed, staged_path
                if not mode_changed:
                    staged_path = self.artifact_directory / name
                    staged_path.chmod(0o600)
                    mode_changed = True
                return real_stat(name)

            with (
                patch.object(
                    transaction.directory,
                    "stat",
                    side_effect=change_mode_before_first_stage_stat,
                ),
                self.assertRaisesRegex(OSError, "Staged artifact changed") as raised,
            ):
                transaction.stage_bytes(
                    "report.json",
                    b"stage\n",
                    mode=0o640,
                    suffix=".tmp",
                )

        self.assertTrue(mode_changed)
        self.assertIsNotNone(staged_path)
        assert staged_path is not None
        self.assertTrue(staged_path.is_file())
        self.assertEqual(staged_path.read_bytes(), b"stage\n")
        self.assertEqual(stat.S_IMODE(staged_path.stat().st_mode), 0o600)
        self.assertTrue(
            any(
                staged_path.name in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            [staged_path.name],
        )

    @unittest.skipUnless(os.name == "posix", "POSIX hard links required")
    def test_post_write_stage_hardlink_is_preserved_on_rejection(self) -> None:
        alias = self.root / "stage-alias.json"
        staged_path: Path | None = None
        linked = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            real_stat = transaction.directory.stat

            def link_before_first_stage_stat(name: str) -> os.stat_result:
                nonlocal linked, staged_path
                if not linked:
                    staged_path = self.artifact_directory / name
                    os.link(staged_path, alias)
                    linked = True
                return real_stat(name)

            with (
                patch.object(
                    transaction.directory,
                    "stat",
                    side_effect=link_before_first_stage_stat,
                ),
                self.assertRaisesRegex(OSError, "Staged artifact changed") as raised,
            ):
                transaction.stage_bytes(
                    "report.json",
                    b"stage\n",
                    mode=0o600,
                    suffix=".tmp",
                )

        self.assertTrue(linked)
        self.assertIsNotNone(staged_path)
        assert staged_path is not None
        self.assertTrue(staged_path.is_file())
        self.assertTrue(alias.is_file())
        self.assertEqual(staged_path.read_bytes(), b"stage\n")
        self.assertEqual(alias.read_bytes(), b"stage\n")
        staged_stat = staged_path.stat()
        alias_stat = alias.stat()
        self.assertEqual(
            (staged_stat.st_dev, staged_stat.st_ino),
            (alias_stat.st_dev, alias_stat.st_ino),
        )
        self.assertGreaterEqual(staged_stat.st_nlink, 2)
        self.assertTrue(
            any(
                staged_path.name in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            [staged_path.name],
        )

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

    def test_modeled_windows_rejects_late_readonly_target_hardlink(self) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        linked = False

        def link_target_at_replace(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal linked
            if phase != "before_replace" or name != "report.json" or linked:
                return
            os.link(target, alias)
            linked = True

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
                    patch(
                        "src.conversion.anchored_artifacts._file_fingerprint",
                        side_effect=self._stable_ctime_fingerprint,
                    ),
                    patch(
                        "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                        side_effect=link_target_at_replace,
                    ),
                    self.assertRaisesRegex(
                        OSError,
                        "read-only multiply-linked artifact",
                    ),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(linked)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertEqual(
                (target.stat().st_dev, target.stat().st_ino),
                (alias.stat().st_dev, alias.stat().st_ino),
            )
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertFalse(stat.S_IMODE(alias.stat().st_mode) & stat.S_IWUSR)
            self.assertEqual(
                sorted(path.name for path in self.artifact_directory.iterdir()),
                ["report.json"],
            )
        finally:
            target.chmod(0o600)

    def test_modeled_windows_late_stage_hardlink_keeps_original_mode(self) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "stage-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        staged_path: Path | None = None
        alias_mode_at_hook: int | None = None

        def link_stage_at_replace(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal alias_mode_at_hook, staged_path
            if phase != "before_replace" or name != "report.json":
                return
            candidates = tuple(self.artifact_directory.glob(".report.json.*.tmp"))
            self.assertEqual(len(candidates), 1)
            staged_path = candidates[0]
            os.link(staged_path, alias)
            alias_mode_at_hook = stat.S_IMODE(alias.stat().st_mode)

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
                    patch(
                        "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                        side_effect=link_stage_at_replace,
                    ),
                    self.assertRaisesRegex(OSError, "transaction file changed"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertIsNotNone(staged_path)
            assert staged_path is not None
            self.assertTrue(staged_path.is_file())
            self.assertEqual(staged_path.read_bytes(), b"new\n")
            self.assertEqual(alias.read_bytes(), b"new\n")
            self.assertEqual(
                (staged_path.stat().st_dev, staged_path.stat().st_ino),
                (alias.stat().st_dev, alias.stat().st_ino),
            )
            self.assertIsNotNone(alias_mode_at_hook)
            self.assertArtifactModeEqual(
                stat.S_IMODE(alias.stat().st_mode),
                cast(int, alias_mode_at_hook),
            )
        finally:
            target.chmod(0o600)

    def test_modeled_windows_post_stage_chmod_hardlink_restores_alias_mode(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "stage-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        staged_path: Path | None = None
        linked = False

        try:
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                real_chmod = transaction.directory.chmod_exact

                def link_after_stage_chmod(
                    name: str,
                    identity: tuple[int, int],
                    mode: int,
                    **kwargs: Any,
                ) -> int:
                    nonlocal linked, staged_path
                    result = real_chmod(name, identity, mode, **kwargs)
                    if (
                        not linked
                        and name.startswith(".report.json.")
                        and not mode & stat.S_IWUSR
                    ):
                        staged_path = self.artifact_directory / name
                        os.link(staged_path, alias)
                        linked = True
                    return result

                with (
                    patch(
                        "src.conversion.anchored_artifacts._is_windows_platform",
                        return_value=True,
                    ),
                    patch.object(
                        transaction.directory,
                        "chmod_exact",
                        side_effect=link_after_stage_chmod,
                    ),
                    self.assertRaisesRegex(OSError, "Staged artifact changed"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(linked)
            self.assertIsNotNone(staged_path)
            assert staged_path is not None
            self.assertEqual(staged_path.read_bytes(), b"new\n")
            self.assertEqual(alias.read_bytes(), b"new\n")
            self.assertTrue(stat.S_IMODE(staged_path.stat().st_mode) & stat.S_IWUSR)
            self.assertTrue(stat.S_IMODE(alias.stat().st_mode) & stat.S_IWUSR)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
        finally:
            target.chmod(0o600)

    def test_modeled_windows_post_preparation_failure_restores_target_mode(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        failed_after_preparation = False

        try:
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                real_prepare = cast(
                    Callable[[str, Any], None],
                    getattr(transaction, "_prepare_replace_target_mode"),
                )

                def fail_after_target_preparation(
                    name: str,
                    prepared: Any,
                ) -> None:
                    nonlocal failed_after_preparation
                    real_prepare(name, prepared)
                    if name == "report.json" and not failed_after_preparation:
                        failed_after_preparation = True
                        raise OSError("injected post-preparation failure")

                with (
                    patch(
                        "src.conversion.anchored_artifacts._is_windows_platform",
                        return_value=True,
                    ),
                    patch.object(
                        transaction,
                        "_prepare_replace_target_mode",
                        side_effect=fail_after_target_preparation,
                    ),
                    self.assertRaisesRegex(OSError, "post-preparation failure"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(failed_after_preparation)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertEqual(
                sorted(path.name for path in self.artifact_directory.iterdir()),
                ["report.json"],
            )
        finally:
            target.chmod(0o600)

    @unittest.skipUnless(
        callable(getattr(os, "fchmod", None)),
        "descriptor chmod is unavailable",
    )
    def test_modeled_windows_hardlink_during_fchmod_restores_alias_mode(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        real_fchmod = os.fchmod
        linked = False

        def link_before_fchmod(descriptor: int, mode: int) -> None:
            nonlocal linked
            opened = os.fstat(descriptor)
            if (
                not linked
                and (opened.st_dev, opened.st_ino) == target_identity
                and mode & stat.S_IWUSR
            ):
                os.link(target, alias)
                linked = True
            real_fchmod(descriptor, mode)

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
                    patch(
                        "src.conversion.anchored_artifacts.os.fchmod",
                        side_effect=link_before_fchmod,
                    ),
                    self.assertRaisesRegex(OSError, "transaction file changed"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(linked)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertEqual(
                (target.stat().st_dev, target.stat().st_ino),
                (alias.stat().st_dev, alias.stat().st_ino),
            )
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertFalse(stat.S_IMODE(alias.stat().st_mode) & stat.S_IWUSR)
        finally:
            target.chmod(0o600)

    def test_modeled_windows_hardlink_during_path_chmod_restores_alias_mode(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        real_chmod = os.chmod
        linked = False

        def link_before_path_chmod(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
            mode: int,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            nonlocal linked
            if not isinstance(path, int):
                candidate = Path(os.fsdecode(path))
                candidate_stat = os.lstat(candidate)
                if (
                    not linked
                    and (candidate_stat.st_dev, candidate_stat.st_ino)
                    == target_identity
                    and mode & stat.S_IWUSR
                ):
                    os.link(target, alias)
                    linked = True
            real_chmod(path, mode, *args, **kwargs)

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
                    patch(
                        "src.conversion.anchored_artifacts.os.fchmod",
                        None,
                        create=True,
                    ),
                    patch(
                        "src.conversion.anchored_artifacts.os.chmod",
                        side_effect=link_before_path_chmod,
                    ),
                    self.assertRaisesRegex(OSError, "transaction file changed"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(linked)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertEqual(
                (target.stat().st_dev, target.stat().st_ino),
                (alias.stat().st_dev, alias.stat().st_ino),
            )
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertFalse(stat.S_IMODE(alias.stat().st_mode) & stat.S_IWUSR)
        finally:
            target.chmod(0o600)

    @unittest.skipUnless(
        callable(getattr(os, "fchmod", None)),
        "descriptor chmod is unavailable",
    )
    def test_modeled_windows_fchmod_race_preserves_external_mode(self) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        real_fchmod = os.fchmod
        changed = False

        def change_mode_and_link(descriptor: int, mode: int) -> None:
            nonlocal changed
            opened = os.fstat(descriptor)
            real_fchmod(descriptor, mode)
            if (
                not changed
                and (opened.st_dev, opened.st_ino) == target_identity
                and mode & stat.S_IWUSR
            ):
                target.chmod(0o400)
                os.link(target, alias)
                changed = True

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
                    patch(
                        "src.conversion.anchored_artifacts.os.fchmod",
                        side_effect=change_mode_and_link,
                    ),
                    self.assertRaisesRegex(OSError, "transaction file changed"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(changed)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o400)
            self.assertArtifactModeEqual(stat.S_IMODE(alias.stat().st_mode), 0o400)
        finally:
            target.chmod(0o600)

    def test_modeled_windows_path_chmod_race_preserves_external_mode(self) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        real_chmod = os.chmod
        changed = False

        def change_mode_and_link(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
            mode: int,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            nonlocal changed
            candidate_stat: os.stat_result | None = None
            if not isinstance(path, int):
                candidate_stat = os.lstat(Path(os.fsdecode(path)))
            real_chmod(path, mode, *args, **kwargs)
            if (
                not changed
                and candidate_stat is not None
                and (candidate_stat.st_dev, candidate_stat.st_ino)
                == target_identity
                and mode & stat.S_IWUSR
            ):
                real_chmod(target, 0o400)
                os.link(target, alias)
                changed = True

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
                    patch(
                        "src.conversion.anchored_artifacts.os.fchmod",
                        None,
                        create=True,
                    ),
                    patch(
                        "src.conversion.anchored_artifacts.os.chmod",
                        side_effect=change_mode_and_link,
                    ),
                    self.assertRaisesRegex(OSError, "transaction file changed"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(changed)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o400)
            self.assertArtifactModeEqual(stat.S_IMODE(alias.stat().st_mode), 0o400)
        finally:
            target.chmod(0o600)

    def test_modeled_windows_late_hardlink_restores_prepared_target_mode(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        linked = False

        try:
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                real_prepare = cast(
                    Callable[[str, Any], None],
                    getattr(transaction, "_prepare_replace_target_mode"),
                )

                def link_after_target_preparation(
                    name: str,
                    prepared: Any,
                ) -> None:
                    nonlocal linked
                    real_prepare(name, prepared)
                    if name == "report.json" and not linked:
                        os.link(target, alias)
                        linked = True

                with (
                    patch(
                        "src.conversion.anchored_artifacts._is_windows_platform",
                        return_value=True,
                    ),
                    patch.object(
                        transaction,
                        "_prepare_replace_target_mode",
                        side_effect=link_after_target_preparation,
                    ),
                    self.assertRaisesRegex(
                        OSError,
                        "multiply-linked artifact at the mutation boundary",
                    ),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(linked)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertEqual(alias.read_bytes(), b"old\n")
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR)
            self.assertFalse(stat.S_IMODE(alias.stat().st_mode) & stat.S_IWUSR)
        finally:
            target.chmod(0o600)

    def test_modeled_windows_external_mode_change_is_not_overwritten_on_abort(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o444)
        externally_changed = False

        try:
            with ByteArtifactTransaction.open(
                str(self.root),
                "gm2godot",
                create=False,
                description="test artifact directory",
            ) as transaction:
                real_prepare = cast(
                    Callable[[str, Any], None],
                    getattr(transaction, "_prepare_replace_target_mode"),
                )

                def change_mode_after_target_preparation(
                    name: str,
                    prepared: Any,
                ) -> None:
                    nonlocal externally_changed
                    real_prepare(name, prepared)
                    if name == "report.json" and not externally_changed:
                        target.chmod(0o400)
                        externally_changed = True

                with (
                    patch(
                        "src.conversion.anchored_artifacts._is_windows_platform",
                        return_value=True,
                    ),
                    patch.object(
                        transaction,
                        "_prepare_replace_target_mode",
                        side_effect=change_mode_after_target_preparation,
                    ),
                    self.assertRaisesRegex(OSError, "Artifact changed"),
                ):
                    transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

            self.assertTrue(externally_changed)
            self.assertEqual(target.read_bytes(), b"old\n")
            self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o400)
        finally:
            target.chmod(0o600)

    def test_writable_hardlink_change_at_replace_boundary_is_preserved(self) -> None:
        target = self.artifact_directory / "report.json"
        alias = self.root / "report-alias.json"
        target.write_bytes(b"old\n")
        os.link(target, alias)
        original_identity = (target.stat().st_dev, target.stat().st_ino)
        changed = False

        def change_through_alias(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal changed
            if phase != "before_replace" or name != "report.json" or changed:
                return
            self._overwrite_same_inode(alias, b"EXT\n")
            changed = True

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=change_through_alias,
                ),
                self.assertRaisesRegex(OSError, "Artifact content changed"),
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertTrue(changed)
        self.assertEqual(target.read_bytes(), b"EXT\n")
        self.assertEqual(alias.read_bytes(), b"EXT\n")
        self.assertEqual(
            (target.stat().st_dev, target.stat().st_ino), original_identity
        )
        self.assertEqual((alias.stat().st_dev, alias.stat().st_ino), original_identity)
        self.assertGreaterEqual(target.stat().st_nlink, 2)
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

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
        self.assertArtifactModeEqual(stat.S_IMODE(first.stat().st_mode), 0o640)
        self.assertArtifactModeEqual(stat.S_IMODE(second.stat().st_mode), 0o600)
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

    def test_after_backup_ordinary_error_exactly_cleans_owned_stage(self) -> None:
        self._assert_after_backup_failure_cleans_owned_stage(
            OSError("injected after-backup failure")
        )

    def test_after_backup_keyboard_interrupt_exactly_cleans_owned_stage(self) -> None:
        self._assert_after_backup_failure_cleans_owned_stage(
            KeyboardInterrupt("injected after-backup interrupt")
        )

    def test_after_backup_system_exit_exactly_cleans_owned_stage(self) -> None:
        signal = SystemExit(211)

        self._assert_after_backup_failure_cleans_owned_stage(signal)

        self.assertEqual(signal.code, 211)

    def test_after_backup_in_place_tamper_aborts_and_preserves_stage(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o640)
        tampered_backup: Path | None = None

        def tamper_after_backup(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal tampered_backup
            if phase != "after_backup" or name != "report.json":
                return
            candidates = tuple(self.artifact_directory.glob(".report.json.*.backup"))
            self.assertEqual(len(candidates), 1)
            tampered_backup = candidates[0]
            self._overwrite_same_inode(tampered_backup, b"BAD\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=tamper_after_backup,
                ),
                self.assertRaisesRegex(OSError, "changed") as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertIsNotNone(tampered_backup)
        assert tampered_backup is not None
        self.assertTrue(tampered_backup.is_file())
        self.assertEqual(tampered_backup.read_bytes(), b"BAD\n")
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertTrue(
            any(
                tampered_backup.name in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            sorted(("report.json", tampered_backup.name)),
        )

    def test_after_backup_identity_replacement_aborts_and_preserves_collision(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o640)
        replacement = self.root / "replacement-backup"
        replacement.write_bytes(b"old\n")
        replacement.chmod(0o640)
        replacement_identity = (replacement.stat().st_dev, replacement.stat().st_ino)
        replaced_backup: Path | None = None

        def replace_after_backup(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal replaced_backup
            if phase != "after_backup" or name != "report.json":
                return
            candidates = tuple(self.artifact_directory.glob(".report.json.*.backup"))
            self.assertEqual(len(candidates), 1)
            replaced_backup = candidates[0]
            os.replace(replacement, replaced_backup)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=replace_after_backup,
                ),
                self.assertRaisesRegex(OSError, "changed") as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertIsNotNone(replaced_backup)
        assert replaced_backup is not None
        self.assertTrue(replaced_backup.is_file())
        self.assertEqual(replaced_backup.read_bytes(), b"old\n")
        self.assertEqual(
            (replaced_backup.stat().st_dev, replaced_backup.stat().st_ino),
            replacement_identity,
        )
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertTrue(
            any(
                replaced_backup.name in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            sorted(("report.json", replaced_backup.name)),
        )

    def test_cross_entry_backup_tamper_aborts_before_public_mutation(self) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"one\n")
        second.write_bytes(b"two\n")
        first_backup: Path | None = None
        phases: list[str] = []

        def tamper_first_backup_from_second_hook(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal first_backup
            phases.append(phase)
            if phase != "after_backup":
                return
            if name == "first.json":
                candidates = tuple(
                    self.artifact_directory.glob(".first.json.*.backup")
                )
                self.assertEqual(len(candidates), 1)
                first_backup = candidates[0]
                return
            if name == "second.json":
                self.assertIsNotNone(first_backup)
                assert first_backup is not None
                self._overwrite_same_inode(first_backup, b"BAD\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=tamper_first_backup_from_second_hook,
                ),
                self.assertRaisesRegex(OSError, "changed"),
            ):
                transaction.publish_specs(
                    (
                        ArtifactSpec("first.json", b"ONE\n"),
                        ArtifactSpec("second.json", b"TWO\n"),
                    )
                )

        self.assertIsNotNone(first_backup)
        assert first_backup is not None
        self.assertTrue(first_backup.is_file())
        self.assertEqual(first_backup.read_bytes(), b"BAD\n")
        self.assertEqual(first.read_bytes(), b"one\n")
        self.assertEqual(second.read_bytes(), b"two\n")
        self.assertNotIn("before_commit", phases)
        self.assertNotIn("before_replace", phases)
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            sorted(("first.json", "second.json", first_backup.name)),
        )

    def test_publish_rejects_same_inode_change_at_replace_boundary(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        original_identity = (target.stat().st_dev, target.stat().st_ino)
        changed = False

        def change_target_at_replace(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal changed
            if phase != "before_replace" or name != "report.json" or changed:
                return
            self._overwrite_same_inode(target, b"EXT\n")
            changed = True

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=change_target_at_replace,
                ),
                self.assertRaisesRegex(OSError, "Artifact content changed"),
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertTrue(changed)
        self.assertEqual(target.read_bytes(), b"EXT\n")
        self.assertEqual(
            (target.stat().st_dev, target.stat().st_ino), original_identity
        )
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_publish_rejects_same_inode_stage_change_at_replace_boundary(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        changed_stage: Path | None = None

        def change_stage_at_replace(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal changed_stage
            if phase != "before_replace" or name != "report.json":
                return
            candidates = tuple(self.artifact_directory.glob(".report.json.*.tmp"))
            self.assertEqual(len(candidates), 1)
            changed_stage = candidates[0]
            self._overwrite_same_inode(changed_stage, b"BAD\n")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=change_stage_at_replace,
                ),
                self.assertRaisesRegex(OSError, "Staged artifact content changed"),
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertIsNotNone(changed_stage)
        assert changed_stage is not None
        self.assertTrue(changed_stage.is_file())
        self.assertEqual(changed_stage.read_bytes(), b"BAD\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            sorted(("report.json", changed_stage.name)),
        )

    def test_absent_publish_rejects_same_inode_change_at_unlink_boundary(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        original_identity = (target.stat().st_dev, target.stat().st_ino)
        changed = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            windows_tombstone = transaction.strategy == "windows_handle"

            def change_target_at_unlink(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal changed
                posix_boundary = phase == "before_unlink" and name == "report.json"
                windows_boundary = (
                    windows_tombstone
                    and phase == "before_replace"
                    and name is not None
                    and name.endswith(".tombstone")
                )
                if changed or not (posix_boundary or windows_boundary):
                    return
                self._overwrite_same_inode(target, b"EXT\n")
                changed = True

            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=change_target_at_unlink,
                ),
                self.assertRaisesRegex(OSError, "content changed"),
            ):
                transaction.publish_specs((ArtifactSpec("report.json", None),))

        self.assertTrue(changed)
        self.assertEqual(target.read_bytes(), b"EXT\n")
        self.assertEqual(
            (target.stat().st_dev, target.stat().st_ino), original_identity
        )
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_restore_rejects_same_inode_receipt_change_at_replace_boundary(
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
            published_identity = (target.stat().st_dev, target.stat().st_ino)
            changed = False

            def change_receipt_at_displacement(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal changed
                if (
                    phase != "before_replace"
                    or name is None
                    or not name.endswith(".restore.backup")
                    or changed
                ):
                    return
                self._overwrite_same_inode(target, b"EXT\n")
                changed = True

            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=change_receipt_at_displacement,
                ),
                self.assertRaisesRegex(OSError, "content changed"),
            ):
                transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertTrue(changed)
        self.assertEqual(target.read_bytes(), b"EXT\n")
        self.assertEqual(
            (target.stat().st_dev, target.stat().st_ino), published_identity
        )
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
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
        self.assertArtifactModeEqual(
            stat.S_IMODE(retained[0].stat().st_mode),
            0o600,
        )
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(
            any("injected second rollback failure" in note for note in notes)
        )
        self.assertTrue(
            any("verified recovery artifact preserved" in note for note in notes)
        )

    def test_publish_rollback_preserves_same_inode_external_change(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        original_mode = stat.S_IMODE(target.stat().st_mode)
        rolling_back = False
        changed = False

        def fail_then_change_rollback_target(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal changed, rolling_back
            if phase == "before_commit_report.json_durability":
                rolling_back = True
                raise OSError("injected publication durability failure")
            if (
                rolling_back
                and phase == "before_replace"
                and name == "report.json"
                and not changed
            ):
                self._overwrite_same_inode(target, b"EXT\n")
                changed = True

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_then_change_rollback_target,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "publication durability failure",
                ) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertTrue(changed)
        self.assertEqual(target.read_bytes(), b"EXT\n")
        retained = [
            path
            for path in self.artifact_directory.iterdir()
            if path.name != "report.json"
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), b"old\n")
        retained_stat = retained[0].stat()
        self.assertEqual(retained_stat.st_nlink, 1)
        self.assertNotEqual(
            (retained_stat.st_dev, retained_stat.st_ino),
            (target.stat().st_dev, target.stat().st_ino),
        )
        self.assertArtifactModeEqual(
            stat.S_IMODE(retained_stat.st_mode),
            original_mode,
        )
        notes = getattr(raised.exception, "__notes__", ())
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
        self.assertArtifactModeEqual(
            stat.S_IMODE(target.stat().st_mode),
            0o640,
        )

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

    def test_restore_rollback_preserves_same_inode_external_change(self) -> None:
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
            rolling_back = False
            changed = False

            def fail_then_change_rollback_target(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal changed, rolling_back
                if phase == "before_restore_report.json_durability":
                    rolling_back = True
                    raise OSError("injected restore durability failure")
                if (
                    rolling_back
                    and phase == "before_replace"
                    and name == "report.json"
                    and not changed
                ):
                    self._overwrite_same_inode(target, b"EXT\n")
                    changed = True

            with (
                patch(
                    "src.conversion.anchored_artifacts._file_fingerprint",
                    side_effect=self._stable_ctime_fingerprint,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_then_change_rollback_target,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "restore durability failure",
                ) as raised,
            ):
                transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertTrue(changed)
        self.assertEqual(target.read_bytes(), b"EXT\n")
        retained = [
            path
            for path in self.artifact_directory.iterdir()
            if path.name != "report.json"
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), receipt.content)
        retained_stat = retained[0].stat()
        self.assertEqual(retained_stat.st_nlink, 1)
        self.assertNotEqual(
            (retained_stat.st_dev, retained_stat.st_ino),
            (target.stat().st_dev, target.stat().st_ino),
        )
        self.assertArtifactModeEqual(
            stat.S_IMODE(retained_stat.st_mode),
            receipt.mode,
        )
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(
            any("verified recovery artifact preserved" in note for note in notes)
        )

    def test_publish_before_rollback_keyboard_interrupt_preempts_forward_error_and_attempts_all(
        self,
    ) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")
        forward_error = OSError("injected forward publication failure")
        rollback_signal = KeyboardInterrupt("injected before-rollback interrupt")
        rolling_back = False
        signal_injected = False
        rollback_attempts: list[str] = []

        def interrupt_before_rollback(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal rolling_back, signal_injected
            if phase == "before_commit_second.json_durability" and not rolling_back:
                rolling_back = True
                raise forward_error
            if rolling_back and phase == "before_rollback" and not signal_injected:
                signal_injected = True
                raise rollback_signal
            if rolling_back and phase == "before_commit" and name is not None:
                rollback_attempts.append(name)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=interrupt_before_rollback,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs(
                    (
                        ArtifactSpec("first.json", b"first new\n"),
                        ArtifactSpec("second.json", b"second new\n"),
                    )
                )

        self.assertIs(raised.exception, rollback_signal)
        self.assertEqual(rollback_attempts, ["second.json", "first.json"])
        self.assertEqual(first.read_bytes(), b"first old\n")
        self.assertEqual(second.read_bytes(), b"second old\n")
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(forward_error) in note for note in notes))

    def test_publish_forward_keyboard_interrupt_survives_ordinary_rollback_failure(
        self,
    ) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")
        forward_signal = KeyboardInterrupt("injected forward publication interrupt")
        rollback_error = OSError("injected ordinary publication rollback failure")
        rolling_back = False
        rollback_attempts: list[str] = []

        def interrupt_forward_and_fail_second_rollback(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal rolling_back
            if phase == "before_commit_second.json_durability" and not rolling_back:
                rolling_back = True
                raise forward_signal
            if not rolling_back or phase != "before_commit" or name is None:
                return
            rollback_attempts.append(name)
            if name == "second.json":
                raise rollback_error

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=interrupt_forward_and_fail_second_rollback,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs(
                    (
                        ArtifactSpec("first.json", b"first new\n"),
                        ArtifactSpec("second.json", b"second new\n"),
                    )
                )

        self.assertIs(raised.exception, forward_signal)
        self.assertEqual(rollback_attempts, ["second.json", "first.json"])
        self.assertEqual(first.read_bytes(), b"first old\n")
        self.assertEqual(second.read_bytes(), b"second new\n")
        retained = [
            path for path in self.artifact_directory.iterdir() if path.name not in {"first.json", "second.json"}
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), b"second old\n")
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(rollback_error) in note for note in notes))
        self.assertTrue(any("verified recovery artifact preserved" in note.lower() for note in notes))

    def test_publish_multiple_rollback_signals_use_first_identity_and_keep_notes(
        self,
    ) -> None:
        first = self.artifact_directory / "first.json"
        second = self.artifact_directory / "second.json"
        first.write_bytes(b"first old\n")
        second.write_bytes(b"second old\n")
        forward_error = OSError("injected ordinary publication failure")
        first_signal = SystemExit(73)
        second_signal = KeyboardInterrupt("injected later rollback interrupt")
        rolling_back = False
        rollback_attempts: list[str] = []

        def raise_each_rollback_signal(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal rolling_back
            if phase == "before_commit_second.json_durability" and not rolling_back:
                rolling_back = True
                raise forward_error
            if not rolling_back or phase != "before_commit" or name is None:
                return
            rollback_attempts.append(name)
            if name == "second.json":
                raise first_signal
            raise second_signal

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=raise_each_rollback_signal,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs(
                    (
                        ArtifactSpec("first.json", b"first new\n"),
                        ArtifactSpec("second.json", b"second new\n"),
                    )
                )

        self.assertIs(raised.exception, first_signal)
        self.assertEqual(first_signal.code, 73)
        self.assertEqual(rollback_attempts, ["second.json", "first.json"])
        self.assertEqual(first.read_bytes(), b"first new\n")
        self.assertEqual(second.read_bytes(), b"second new\n")
        retained = [
            path for path in self.artifact_directory.iterdir() if path.name not in {"first.json", "second.json"}
        ]
        self.assertEqual(len(retained), 2)
        self.assertEqual(
            {path.read_bytes() for path in retained},
            {b"first old\n", b"second old\n"},
        )
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(forward_error) in note for note in notes))
        self.assertTrue(any(str(second_signal) in note for note in notes))
        self.assertTrue(any("verified recovery artifact preserved" in note.lower() for note in notes))

    def test_restore_rollback_system_exit_preempts_forward_error_and_attempts_all(
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
            forward_error = OSError("injected ordinary restore failure")
            rollback_signal = SystemExit(89)
            rolling_back = False
            rollback_attempts: list[str] = []

            def fail_restore_then_exit_from_rollback(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal rolling_back
                if phase == "before_restore_second.json_durability" and not rolling_back:
                    rolling_back = True
                    raise forward_error
                if not rolling_back or phase != "before_commit" or name is None:
                    return
                rollback_attempts.append(name)
                if name == "second.json":
                    raise rollback_signal

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_restore_then_exit_from_rollback,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.restore_snapshots(snapshots, receipts)
            transaction.verify_receipt(first_receipt)

        self.assertIs(raised.exception, rollback_signal)
        self.assertEqual(rollback_signal.code, 89)
        self.assertEqual(rollback_attempts, ["second.json", "first.json"])
        self.assertEqual(first.read_bytes(), first_receipt.content)
        self.assertEqual(second.read_bytes(), b"second old\n")
        retained = [
            path for path in self.artifact_directory.iterdir() if path.name not in {"first.json", "second.json"}
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), second_receipt.content)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(forward_error) in note for note in notes))
        self.assertTrue(any("verified recovery artifact preserved" in note.lower() for note in notes))

    def test_restore_forward_system_exit_survives_ordinary_rollback_failure(
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
            forward_signal = SystemExit(97)
            rollback_error = OSError("injected ordinary restore rollback failure")
            rolling_back = False
            rollback_attempts: list[str] = []

            def exit_restore_then_fail_second_rollback(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal rolling_back
                if phase == "before_restore_second.json_durability" and not rolling_back:
                    rolling_back = True
                    raise forward_signal
                if not rolling_back or phase != "before_commit" or name is None:
                    return
                rollback_attempts.append(name)
                if name == "second.json":
                    raise rollback_error

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=exit_restore_then_fail_second_rollback,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.restore_snapshots(snapshots, receipts)
            transaction.verify_receipt(first_receipt)

        self.assertIs(raised.exception, forward_signal)
        self.assertEqual(forward_signal.code, 97)
        self.assertEqual(rollback_attempts, ["second.json", "first.json"])
        self.assertEqual(first.read_bytes(), first_receipt.content)
        self.assertEqual(second.read_bytes(), b"second old\n")
        retained = [
            path for path in self.artifact_directory.iterdir() if path.name not in {"first.json", "second.json"}
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), second_receipt.content)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(rollback_error) in note for note in notes))
        self.assertTrue(any("verified recovery artifact preserved" in note.lower() for note in notes))

    def test_completed_present_publish_signal_records_mutation_before_rollback(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        completion_signal = SystemExit(101)
        signal_injected = False

        def exit_after_completed_replace(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal signal_injected
            if phase != "after_replace" or name != "report.json" or signal_injected:
                return
            signal_injected = True
            raise completion_signal

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=exit_after_completed_replace,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertTrue(signal_injected)
        self.assertIs(raised.exception, completion_signal)
        self.assertEqual(completion_signal.code, 101)
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_completed_absent_publish_signal_records_mutation_before_rollback(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        completion_signal = KeyboardInterrupt("injected completed unlink interrupt")
        signal_injected = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            windows_tombstone = transaction.strategy == "windows_handle"

            def interrupt_after_completed_unlink(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal signal_injected
                posix_completion = phase == "after_unlink" and name == "report.json"
                windows_completion = (
                    windows_tombstone and phase == "after_replace" and name is not None and name.endswith(".tombstone")
                )
                if signal_injected or not (posix_completion or windows_completion):
                    return
                signal_injected = True
                raise completion_signal

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=interrupt_after_completed_unlink,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", None),))

        self.assertTrue(signal_injected)
        self.assertIs(raised.exception, completion_signal)
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_cleanup_completed_unlink_signal_syncs_before_exact_reraise(
        self,
    ) -> None:
        cleanup_signal = KeyboardInterrupt("injected post-unlink cleanup interrupt")
        phases: list[str] = []
        signal_injected = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            staged = transaction.stage_bytes(
                "report.json",
                b"stage\n",
                mode=0o600,
                suffix=".tmp",
            )
            temporary_files = {staged.name: staged}

            def interrupt_after_stage_unlink(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal signal_injected
                phases.append(phase)
                if phase != "after_unlink" or name != staged.name or signal_injected:
                    return
                signal_injected = True
                raise cleanup_signal

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=interrupt_after_stage_unlink,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.cleanup(temporary_files)

        self.assertTrue(signal_injected)
        self.assertIs(raised.exception, cleanup_signal)
        self.assertEqual(temporary_files, {})
        self.assertFalse(Path(staged.path).exists())
        self.assertIn("before_cleanup_durability", phases)
        self.assertIn("after_cleanup_durability", phases)
        self.assertLess(
            phases.index("after_unlink"),
            phases.index("before_cleanup_durability"),
        )
        self.assertLess(
            phases.index("before_cleanup_durability"),
            phases.index("after_cleanup_durability"),
        )

    def test_cleanup_direct_post_unlink_control_signal_tracks_completion_before_escape(
        self,
    ) -> None:
        for cleanup_signal in (
            KeyboardInterrupt("injected direct cleanup interrupt"),
            SystemExit(127),
        ):
            with self.subTest(signal_type=type(cleanup_signal).__name__):
                phases: list[str] = []
                unlink_attempts: list[str] = []

                with ByteArtifactTransaction.open(
                    str(self.root),
                    "gm2godot",
                    create=False,
                    description="test artifact directory",
                ) as transaction:
                    interrupted = transaction.stage_bytes(
                        "first.json",
                        b"first stage\n",
                        mode=0o600,
                        suffix=".tmp",
                    )
                    later = transaction.stage_bytes(
                        "second.json",
                        b"second stage\n",
                        mode=0o600,
                        suffix=".tmp",
                    )
                    temporary_files = {
                        interrupted.name: interrupted,
                        later.name: later,
                    }
                    original_unlink = transaction.directory.unlink

                    def unlink_then_raise_control_signal(
                        name: str,
                        *,
                        expected_identity: tuple[int, int],
                        prepare_target: Callable[[], None] | None = None,
                        verify_target: Callable[[], None] | None = None,
                    ) -> BaseException | None:
                        unlink_attempts.append(name)
                        completion_error = original_unlink(
                            name,
                            expected_identity=expected_identity,
                            prepare_target=prepare_target,
                            verify_target=verify_target,
                        )
                        if name == interrupted.name:
                            raise cleanup_signal
                        return completion_error

                    def record_phase(
                        phase: str,
                        _directory_path: str,
                        _name: str | None,
                    ) -> None:
                        phases.append(phase)

                    with (
                        patch.object(
                            transaction.directory,
                            "unlink",
                            side_effect=unlink_then_raise_control_signal,
                        ),
                        patch(
                            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                            side_effect=record_phase,
                        ),
                        self.assertRaises(BaseException) as raised,
                    ):
                        transaction.cleanup(temporary_files)

                self.assertIs(raised.exception, cleanup_signal)
                if isinstance(cleanup_signal, SystemExit):
                    self.assertEqual(cleanup_signal.code, 127)
                self.assertEqual(
                    unlink_attempts,
                    [interrupted.name, later.name],
                )
                self.assertEqual(temporary_files, {})
                self.assertFalse(Path(interrupted.path).exists())
                self.assertFalse(Path(later.path).exists())
                self.assertIn("before_cleanup_durability", phases)
                self.assertIn("after_cleanup_durability", phases)
                self.assertLess(
                    phases.index("before_cleanup_durability"),
                    phases.index("after_cleanup_durability"),
                )

    def test_cleanup_completed_signal_precedes_later_incomplete_signal_and_stops(
        self,
    ) -> None:
        first_signal = KeyboardInterrupt("injected completed first cleanup interrupt")
        second_signal = SystemExit(149)
        phases: list[str] = []
        unlink_attempts: list[str] = []

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            first = transaction.stage_bytes(
                "first.json",
                b"first stage\n",
                mode=0o600,
                suffix=".tmp",
            )
            second = transaction.stage_bytes(
                "second.json",
                b"second stage\n",
                mode=0o600,
                suffix=".tmp",
            )
            later = transaction.stage_bytes(
                "later.json",
                b"later stage\n",
                mode=0o600,
                suffix=".tmp",
            )
            temporary_files = {
                first.name: first,
                second.name: second,
                later.name: later,
            }
            original_unlink = transaction.directory.unlink

            def complete_first_then_interrupt_second(
                name: str,
                *,
                expected_identity: tuple[int, int],
                prepare_target: Callable[[], None] | None = None,
                verify_target: Callable[[], None] | None = None,
            ) -> BaseException | None:
                unlink_attempts.append(name)
                if name == second.name:
                    raise second_signal
                completion_error = original_unlink(
                    name,
                    expected_identity=expected_identity,
                    prepare_target=prepare_target,
                    verify_target=verify_target,
                )
                if name == first.name:
                    raise first_signal
                return completion_error

            def record_phase(
                phase: str,
                _directory_path: str,
                _name: str | None,
            ) -> None:
                phases.append(phase)

            with (
                patch.object(
                    transaction.directory,
                    "unlink",
                    side_effect=complete_first_then_interrupt_second,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=record_phase,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.cleanup(temporary_files)

        self.assertIs(raised.exception, first_signal)
        self.assertEqual(second_signal.code, 149)
        self.assertEqual(unlink_attempts, [first.name, second.name])
        self.assertNotIn(first.name, temporary_files)
        self.assertIn(second.name, temporary_files)
        self.assertIn(later.name, temporary_files)
        self.assertFalse(Path(first.path).exists())
        self.assertTrue(Path(second.path).exists())
        self.assertTrue(Path(later.path).exists())
        self.assertIn("before_cleanup_durability", phases)
        self.assertIn("after_cleanup_durability", phases)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(second_signal.code) in note for note in notes))

    def test_unlink_staged_completed_control_signal_syncs_before_exact_reraise(
        self,
    ) -> None:
        cleanup_signal = SystemExit(151)
        phases: list[str] = []

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            staged = transaction.stage_bytes(
                "report.json",
                b"stage\n",
                mode=0o600,
                suffix=".tmp",
            )

            def exit_after_public_unlink(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                phases.append(phase)
                if phase == "after_unlink" and name == staged.name:
                    raise cleanup_signal

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=exit_after_public_unlink,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.unlink_staged(staged)

        self.assertIs(raised.exception, cleanup_signal)
        self.assertEqual(cleanup_signal.code, 151)
        self.assertFalse(Path(staged.path).exists())
        self.assertIn("before_staged_cleanup_durability", phases)
        self.assertIn("after_staged_cleanup_durability", phases)
        self.assertLess(
            phases.index("after_unlink"),
            phases.index("before_staged_cleanup_durability"),
        )
        self.assertLess(
            phases.index("before_staged_cleanup_durability"),
            phases.index("after_staged_cleanup_durability"),
        )

    def test_publish_rollback_recovery_post_unlink_system_exit_keeps_durability_error(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        forward_error = OSError("injected ordinary post-publication failure")
        cleanup_signal = SystemExit(137)
        durability_error = OSError("injected publication recovery cleanup durability failure")
        cleanup_signal_injected = False
        durability_error_injected = False

        def exit_after_publish(_name: str) -> None:
            raise forward_error

        def fail_publish_recovery_cleanup(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal cleanup_signal_injected, durability_error_injected
            if (
                phase == "after_unlink"
                and name is not None
                and name.endswith(".recovery.backup")
                and not cleanup_signal_injected
            ):
                cleanup_signal_injected = True
                raise cleanup_signal
            if phase == "before_recovery_report.json_cleanup_durability" and not durability_error_injected:
                durability_error_injected = True
                raise durability_error

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_publish_recovery_cleanup,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs(
                    (ArtifactSpec("report.json", b"new\n"),),
                    after_commit=exit_after_publish,
                )

        self.assertTrue(cleanup_signal_injected)
        self.assertTrue(durability_error_injected)
        self.assertIs(raised.exception, cleanup_signal)
        self.assertEqual(cleanup_signal.code, 137)
        self.assertEqual(target.read_bytes(), b"old\n")
        notes = "\n".join(getattr(raised.exception, "__notes__", ()))
        self.assertIn(str(forward_error), notes)
        self.assertIn(str(durability_error), notes)
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_restore_rollback_recovery_post_unlink_keyboard_interrupt_keeps_durability_error(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        forward_error = OSError("injected ordinary completed restore failure")
        cleanup_signal = KeyboardInterrupt("injected restore recovery post-unlink interrupt")
        durability_error = OSError("injected restore recovery cleanup durability failure")
        cleanup_signal_injected = False
        durability_error_injected = False
        forward_error_injected = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshots = transaction.capture_snapshots(("report.json",))
            receipts = transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))
            receipt = receipts[0]
            assert receipt is not None

            def interrupt_restore_and_fail_recovery_cleanup(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal cleanup_signal_injected
                nonlocal durability_error_injected
                nonlocal forward_error_injected
                if phase == "after_restore_report.json_durability" and not forward_error_injected:
                    forward_error_injected = True
                    raise forward_error
                if (
                    phase == "after_unlink"
                    and name is not None
                    and name.endswith(".recovery.backup")
                    and not cleanup_signal_injected
                ):
                    cleanup_signal_injected = True
                    raise cleanup_signal
                if phase == "before_restore_recovery_report.json_cleanup_durability" and not durability_error_injected:
                    durability_error_injected = True
                    raise durability_error

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=interrupt_restore_and_fail_recovery_cleanup,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.restore_snapshots(snapshots, receipts)

        self.assertTrue(forward_error_injected)
        self.assertTrue(cleanup_signal_injected)
        self.assertTrue(durability_error_injected)
        self.assertIs(raised.exception, cleanup_signal)
        self.assertEqual(target.read_bytes(), receipt.content)
        notes = "\n".join(getattr(raised.exception, "__notes__", ()))
        self.assertIn(str(forward_error), notes)
        self.assertIn(str(durability_error), notes)
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_publish_rollback_retries_ordinary_recovery_cleanup_without_spurious_failure(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        forward_error = OSError("injected ordinary post-publication failure")
        cleanup_error = OSError("injected one-shot publication recovery cleanup")
        recovery_unlink_attempts = 0

        def fail_after_publish(_name: str) -> None:
            raise forward_error

        def fail_first_publish_recovery_unlink(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal recovery_unlink_attempts
            if phase != "before_unlink" or name is None or not name.endswith(".recovery.backup"):
                return
            recovery_unlink_attempts += 1
            if recovery_unlink_attempts == 1:
                raise cleanup_error

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_first_publish_recovery_unlink,
                ),
                self.assertRaises(OSError) as raised,
            ):
                transaction.publish_specs(
                    (ArtifactSpec("report.json", b"new\n"),),
                    after_commit=fail_after_publish,
                )

        self.assertIs(raised.exception, forward_error)
        self.assertEqual(recovery_unlink_attempts, 2)
        self.assertEqual(target.read_bytes(), b"old\n")
        notes = getattr(raised.exception, "__notes__", ())
        self.assertFalse(any("rollback" in note.lower() for note in notes))
        self.assertNotIn(str(cleanup_error), "\n".join(notes))
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_restore_rollback_retries_ordinary_recovery_cleanup_without_spurious_failure(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        forward_error = OSError("injected ordinary completed restore failure")
        cleanup_error = OSError("injected one-shot restore recovery cleanup")
        recovery_unlink_attempts = 0
        forward_error_injected = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshots = transaction.capture_snapshots(("report.json",))
            receipts = transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))
            receipt = receipts[0]
            assert receipt is not None

            def fail_restore_and_first_recovery_unlink(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal forward_error_injected, recovery_unlink_attempts
                if phase == "after_restore_report.json_durability" and not forward_error_injected:
                    forward_error_injected = True
                    raise forward_error
                if phase != "before_unlink" or name is None or not name.endswith(".recovery.backup"):
                    return
                recovery_unlink_attempts += 1
                if recovery_unlink_attempts == 1:
                    raise cleanup_error

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_restore_and_first_recovery_unlink,
                ),
                self.assertRaises(OSError) as raised,
            ):
                transaction.restore_snapshots(snapshots, receipts)

        self.assertTrue(forward_error_injected)
        self.assertIs(raised.exception, forward_error)
        self.assertEqual(recovery_unlink_attempts, 2)
        self.assertEqual(target.read_bytes(), receipt.content)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertFalse(any("rollback" in note.lower() for note in notes))
        self.assertNotIn(str(cleanup_error), "\n".join(notes))
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

    def test_replace_staged_completion_probe_signal_does_not_mask_original(self) -> None:
        target = self.artifact_directory / "replace.json"
        target.write_bytes(b"old\n")
        original_signal = KeyboardInterrupt("injected completed replacement interrupt")
        probe_signal = SystemExit(157)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            staged = transaction.stage_bytes(
                "replace.json",
                b"new\n",
                mode=0o640,
                suffix=".tmp",
            )
            original_replace = transaction.directory.replace

            def replace_then_raise(*args: Any, **kwargs: Any) -> BaseException | None:
                completion_error = original_replace(*args, **kwargs)
                self.assertIsNone(completion_error)
                raise original_signal

            with (
                patch.object(
                    transaction.directory,
                    "replace",
                    side_effect=replace_then_raise,
                ),
                patch.object(
                    transaction,
                    "path_matches_stage",
                    side_effect=probe_signal,
                ),
            ):
                completion_error = transaction.replace_staged(
                    staged,
                    "replace.json",
                )

        self.assertIs(completion_error, original_signal)
        self.assertEqual(probe_signal.code, 157)
        self.assertEqual(target.read_bytes(), b"new\n")
        self.assertFalse(Path(staged.path).exists())
        notes = "\n".join(getattr(completion_error, "__notes__", ()))
        self.assertIn(str(probe_signal.code), notes)

    def test_target_displacement_completion_probe_signal_does_not_mask_original(
        self,
    ) -> None:
        target = self.artifact_directory / "displace.json"
        target.write_bytes(b"old\n")
        original_signal = SystemExit(163)
        probe_signal = KeyboardInterrupt("injected displacement probe interrupt")

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshot = transaction.capture_snapshot("displace.json")
            assert snapshot.content is not None
            assert snapshot.mode is not None
            assert snapshot.fingerprint is not None
            assert snapshot.sha256 is not None
            staged_copy = transaction.stage_bytes(
                "displace.json",
                b"placeholder\n",
                mode=0o600,
                suffix=".restore.backup",
            )
            displaced_target = StagedArtifact(
                directory_path=transaction.path,
                name=staged_copy.name,
                identity=(snapshot.fingerprint[0], snapshot.fingerprint[1]),
                content=snapshot.content,
                mode=staged_copy.mode,
                target_mode=snapshot.mode,
                sha256=snapshot.sha256,
            )
            original_replace = transaction.directory.replace

            def replace_then_raise(*args: Any, **kwargs: Any) -> BaseException | None:
                completion_error = original_replace(*args, **kwargs)
                self.assertIsNone(completion_error)
                raise original_signal

            with (
                patch.object(
                    transaction.directory,
                    "replace",
                    side_effect=replace_then_raise,
                ),
                patch.object(
                    transaction,
                    "path_matches_stage",
                    side_effect=probe_signal,
                ),
            ):
                completion_error = transaction.replace_target_with_stage_path(
                    "displace.json",
                    staged_copy,
                    displaced_target,
                )

        self.assertIs(completion_error, original_signal)
        self.assertEqual(original_signal.code, 163)
        self.assertFalse(target.exists())
        self.assertEqual(Path(staged_copy.path).read_bytes(), b"old\n")
        notes = "\n".join(getattr(completion_error, "__notes__", ()))
        self.assertIn(str(probe_signal), notes)

    @unittest.skipIf(os.name == "nt", "POSIX unlink completion probe required")
    def test_unlink_finalized_completion_probe_signal_does_not_mask_original(
        self,
    ) -> None:
        target = self.artifact_directory / "unlink.json"
        target.write_bytes(b"old\n")
        original_signal = KeyboardInterrupt("injected completed public unlink")
        probe_signal = SystemExit(167)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshot = transaction.capture_snapshot("unlink.json")
            assert snapshot.content is not None
            assert snapshot.mode is not None
            assert snapshot.fingerprint is not None
            assert snapshot.sha256 is not None
            finalized = StagedArtifact(
                directory_path=transaction.path,
                name="unlink.json",
                identity=(snapshot.fingerprint[0], snapshot.fingerprint[1]),
                content=snapshot.content,
                mode=snapshot.mode,
                target_mode=snapshot.mode,
                sha256=snapshot.sha256,
            )
            original_unlink = transaction.directory.unlink

            def unlink_then_raise(*args: Any, **kwargs: Any) -> BaseException | None:
                completion_error = original_unlink(*args, **kwargs)
                self.assertIsNone(completion_error)
                raise original_signal

            with (
                patch.object(
                    transaction.directory,
                    "unlink",
                    side_effect=unlink_then_raise,
                ),
                patch.object(
                    transaction.directory,
                    "lexists",
                    side_effect=probe_signal,
                ),
            ):
                tombstone, completion_error = transaction.unlink_finalized(
                    finalized,
                    "unlink.json",
                )

        self.assertIsNone(tombstone)
        self.assertIs(completion_error, original_signal)
        self.assertEqual(probe_signal.code, 167)
        self.assertFalse(target.exists())
        notes = "\n".join(getattr(completion_error, "__notes__", ()))
        self.assertIn(str(probe_signal.code), notes)

    def test_publish_persistent_replace_probe_uncertainty_rolls_back_owned_mutation(
        self,
    ) -> None:
        target = self.artifact_directory / "persistent-publish.json"
        target.write_bytes(b"old\n")
        original_signal = KeyboardInterrupt("injected persistent publication replacement interrupt")
        probe_signal = SystemExit(173)
        replace_attempts = 0
        probe_attempts = 0

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            original_replace = transaction.directory.replace

            def replace_then_raise(*args: Any, **kwargs: Any) -> BaseException | None:
                nonlocal replace_attempts
                replace_attempts += 1
                completion_error = original_replace(*args, **kwargs)
                self.assertIsNone(completion_error)
                raise original_signal

            def fail_completion_probe(
                _name: str,
                _staged: StagedArtifact,
            ) -> bool:
                nonlocal probe_attempts
                probe_attempts += 1
                raise probe_signal

            with (
                patch.object(
                    transaction.directory,
                    "replace",
                    side_effect=replace_then_raise,
                ),
                patch.object(
                    transaction,
                    "path_matches_stage",
                    side_effect=fail_completion_probe,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("persistent-publish.json", b"new\n"),))

        self.assertIs(raised.exception, original_signal)
        self.assertEqual(probe_signal.code, 173)
        self.assertEqual(replace_attempts, 2)
        self.assertEqual(probe_attempts, 4)
        self.assertEqual(target.read_bytes(), b"old\n")
        retained = [path for path in self.artifact_directory.iterdir() if path != target]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), b"old\n")
        notes = "\n".join(getattr(raised.exception, "__notes__", ()))
        self.assertIn(str(probe_signal.code), notes)
        self.assertIn("verified recovery artifact preserved", notes.lower())
        self.assertIn(str(retained[0]), notes)

    def test_restore_persistent_pre_mutation_displacement_uncertainty_cleans_placeholder(
        self,
    ) -> None:
        target = self.artifact_directory / "persistent-pre-restore.json"
        sentinel = self.artifact_directory / "unrelated.txt"
        target.write_bytes(b"old\n")
        sentinel.write_bytes(b"unrelated\n")
        original_signal = KeyboardInterrupt("injected pre-mutation restore displacement interrupt")
        first_probe_signal = SystemExit(179)
        second_probe_signal = KeyboardInterrupt("injected persistent restore completion retry interrupt")
        probe_signals = (first_probe_signal, second_probe_signal)
        receipt_placeholders: list[StagedArtifact] = []
        replace_attempts = 0
        probe_attempts = 0

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshots = transaction.capture_snapshots(("persistent-pre-restore.json",))
            receipts = transaction.publish_specs((ArtifactSpec("persistent-pre-restore.json", b"new\n"),))
            receipt = receipts[0]
            assert receipt is not None
            directory_before = self._directory_snapshot(self.artifact_directory)
            original_stage_bytes = transaction.stage_bytes

            def capture_receipt_placeholder(
                *args: Any,
                **kwargs: Any,
            ) -> StagedArtifact:
                staged = original_stage_bytes(*args, **kwargs)
                if kwargs.get("suffix") == ".restore.backup":
                    receipt_placeholders.append(staged)
                return staged

            def fail_displacement_before_replace(
                *args: Any,
                **_kwargs: Any,
            ) -> BaseException | None:
                nonlocal replace_attempts
                replace_attempts += 1
                self.assertEqual(args[0], "persistent-pre-restore.json")
                self.assertTrue(str(args[1]).endswith(".restore.backup"))
                raise original_signal

            def fail_completion_probes(
                _name: str,
                _staged: StagedArtifact,
            ) -> bool:
                nonlocal probe_attempts
                signal = probe_signals[probe_attempts]
                probe_attempts += 1
                raise signal

            with (
                patch.object(
                    transaction,
                    "stage_bytes",
                    side_effect=capture_receipt_placeholder,
                ),
                patch.object(
                    transaction.directory,
                    "replace",
                    side_effect=fail_displacement_before_replace,
                ),
                patch.object(
                    transaction,
                    "path_matches_stage",
                    side_effect=fail_completion_probes,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.restore_snapshots(snapshots, receipts)

            self.assertIs(raised.exception, original_signal)
            transaction.verify_receipt(receipt)
            self.assertEqual(
                self._directory_snapshot(self.artifact_directory),
                directory_before,
            )

        self.assertEqual(replace_attempts, 1)
        self.assertEqual(probe_attempts, 2)
        self.assertEqual(len(receipt_placeholders), 1)
        self.assertFalse(Path(receipt_placeholders[0].path).exists())
        self.assertFalse(any(".restore.backup" in path.name for path in self.artifact_directory.iterdir()))
        self.assertEqual(target.read_bytes(), b"new\n")
        self.assertEqual(sentinel.read_bytes(), b"unrelated\n")
        notes = "\n".join(getattr(raised.exception, "__notes__", ()))
        self.assertIn(str(first_probe_signal.code), notes)
        self.assertIn(str(second_probe_signal), notes)

    def test_restore_persistent_displacement_probe_uncertainty_restores_receipt(
        self,
    ) -> None:
        target = self.artifact_directory / "persistent-restore.json"
        target.write_bytes(b"old\n")
        original_signal = SystemExit(179)
        probe_signal = KeyboardInterrupt("injected persistent restore completion probe interrupt")
        replace_attempts = 0
        probe_attempts = 0

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            snapshots = transaction.capture_snapshots(("persistent-restore.json",))
            receipts = transaction.publish_specs((ArtifactSpec("persistent-restore.json", b"new\n"),))
            receipt = receipts[0]
            assert receipt is not None
            original_replace = transaction.directory.replace

            def replace_then_raise(*args: Any, **kwargs: Any) -> BaseException | None:
                nonlocal replace_attempts
                replace_attempts += 1
                completion_error = original_replace(*args, **kwargs)
                self.assertIsNone(completion_error)
                raise original_signal

            def fail_completion_probe(
                _name: str,
                _staged: StagedArtifact,
            ) -> bool:
                nonlocal probe_attempts
                probe_attempts += 1
                raise probe_signal

            with (
                patch.object(
                    transaction.directory,
                    "replace",
                    side_effect=replace_then_raise,
                ),
                patch.object(
                    transaction,
                    "path_matches_stage",
                    side_effect=fail_completion_probe,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.restore_snapshots(snapshots, receipts)

        self.assertIs(raised.exception, original_signal)
        self.assertEqual(original_signal.code, 179)
        self.assertEqual(replace_attempts, 2)
        self.assertEqual(probe_attempts, 4)
        self.assertEqual(target.read_bytes(), receipt.content)
        retained = [path for path in self.artifact_directory.iterdir() if path != target]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), receipt.content)
        notes = "\n".join(getattr(raised.exception, "__notes__", ()))
        self.assertIn(str(probe_signal), notes)
        self.assertIn("verified recovery artifact preserved", notes.lower())
        self.assertIn(str(retained[0]), notes)

    def test_modeled_windows_absent_publish_pre_mutation_tombstone_uncertainty_cleans_placeholder(
        self,
    ) -> None:
        target = self.artifact_directory / "persistent-tombstone.json"
        sentinel = self.artifact_directory / "unrelated.txt"
        target.write_bytes(b"old\n")
        sentinel.write_bytes(b"unrelated\n")
        original_signal = SystemExit(181)
        first_probe_signal = KeyboardInterrupt("injected tombstone completion probe interrupt")
        second_probe_signal = SystemExit(191)
        probe_signals = (first_probe_signal, second_probe_signal)
        tombstone_placeholders: list[StagedArtifact] = []
        replace_attempts = 0
        probe_attempts = 0

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            directory_before = self._directory_snapshot(self.artifact_directory)
            original_stage_bytes = transaction.stage_bytes

            def capture_tombstone_placeholder(
                *args: Any,
                **kwargs: Any,
            ) -> StagedArtifact:
                staged = original_stage_bytes(*args, **kwargs)
                if kwargs.get("suffix") == ".tombstone":
                    tombstone_placeholders.append(staged)
                return staged

            def fail_displacement_before_replace(
                *args: Any,
                **_kwargs: Any,
            ) -> BaseException | None:
                nonlocal replace_attempts
                replace_attempts += 1
                self.assertEqual(args[0], "persistent-tombstone.json")
                self.assertTrue(str(args[1]).endswith(".tombstone"))
                raise original_signal

            def fail_completion_probes(
                _name: str,
                _staged: StagedArtifact,
            ) -> bool:
                nonlocal probe_attempts
                signal = probe_signals[probe_attempts]
                probe_attempts += 1
                raise signal

            with (
                patch.object(
                    ByteArtifactTransaction,
                    "strategy",
                    property(lambda _transaction: "windows_handle"),
                ),
                patch.object(
                    transaction,
                    "stage_bytes",
                    side_effect=capture_tombstone_placeholder,
                ),
                patch.object(
                    transaction.directory,
                    "replace",
                    side_effect=fail_displacement_before_replace,
                ),
                patch.object(
                    transaction,
                    "path_matches_stage",
                    side_effect=fail_completion_probes,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("persistent-tombstone.json", None),))

            self.assertIs(raised.exception, original_signal)
            directory_after = self._directory_snapshot(self.artifact_directory)
            self.assertEqual(
                directory_after[target.name],
                directory_before[target.name],
            )
            self.assertEqual(
                directory_after[sentinel.name],
                directory_before[sentinel.name],
            )

        self.assertEqual(replace_attempts, 1)
        self.assertEqual(probe_attempts, 2)
        self.assertEqual(len(tombstone_placeholders), 1)
        self.assertFalse(Path(tombstone_placeholders[0].path).exists())
        self.assertFalse(any(".tombstone" in path.name for path in self.artifact_directory.iterdir()))
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(sentinel.read_bytes(), b"unrelated\n")
        notes = "\n".join(getattr(raised.exception, "__notes__", ()))
        self.assertIn(str(first_probe_signal), notes)
        self.assertIn(str(second_probe_signal.code), notes)

    def test_modeled_windows_absent_publish_completed_unknown_tombstone_resolves_displaced_owner(
        self,
    ) -> None:
        target = self.artifact_directory / "completed-tombstone.json"
        sentinel = self.artifact_directory / "unrelated.txt"
        target.write_bytes(b"old\n")
        target.chmod(0o640)
        sentinel.write_bytes(b"unrelated\n")
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        sentinel_before = self._directory_snapshot(self.artifact_directory)[sentinel.name]
        original_signal = KeyboardInterrupt("injected completed tombstone displacement interrupt")
        first_probe_signal = SystemExit(193)
        second_probe_signal = KeyboardInterrupt("injected completed tombstone retry interrupt")
        probe_signals = (first_probe_signal, second_probe_signal)
        tombstone_placeholders: list[StagedArtifact] = []
        resolved_owners: list[StagedArtifact] = []
        replace_attempts = 0
        probe_attempts = 0

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            original_stage_bytes = transaction.stage_bytes
            original_replace = transaction.directory.replace
            original_resolver = cast(
                Callable[..., tuple[StagedArtifact, BaseException]],
                getattr(transaction, "_resolve_ambiguous_stage_ownership"),
            )

            def capture_tombstone_placeholder(
                *args: Any,
                **kwargs: Any,
            ) -> StagedArtifact:
                staged = original_stage_bytes(*args, **kwargs)
                if kwargs.get("suffix") == ".tombstone":
                    tombstone_placeholders.append(staged)
                return staged

            def complete_first_displacement_then_interrupt(
                *args: Any,
                **kwargs: Any,
            ) -> BaseException | None:
                nonlocal replace_attempts
                replace_attempts += 1
                completion_error = original_replace(*args, **kwargs)
                self.assertIsNone(completion_error)
                if replace_attempts == 1:
                    self.assertEqual(args[0], "completed-tombstone.json")
                    self.assertTrue(str(args[1]).endswith(".tombstone"))
                    raise original_signal
                return None

            def fail_completion_probes(
                _name: str,
                _staged: StagedArtifact,
            ) -> bool:
                nonlocal probe_attempts
                signal = probe_signals[probe_attempts]
                probe_attempts += 1
                raise signal

            def record_resolved_owner(
                original_stage: StagedArtifact,
                completed_stage: StagedArtifact,
                error: BaseException,
                *,
                operation: str,
            ) -> tuple[StagedArtifact, BaseException]:
                owned_stage, selected_error = original_resolver(
                    original_stage,
                    completed_stage,
                    error,
                    operation=operation,
                )
                resolved_owners.append(owned_stage)
                return owned_stage, selected_error

            with (
                patch.object(
                    ByteArtifactTransaction,
                    "strategy",
                    property(lambda _transaction: "windows_handle"),
                ),
                patch.object(
                    transaction,
                    "stage_bytes",
                    side_effect=capture_tombstone_placeholder,
                ),
                patch.object(
                    transaction.directory,
                    "replace",
                    side_effect=complete_first_displacement_then_interrupt,
                ),
                patch.object(
                    transaction,
                    "path_matches_stage",
                    side_effect=fail_completion_probes,
                ),
                patch.object(
                    transaction,
                    "_resolve_ambiguous_stage_ownership",
                    side_effect=record_resolved_owner,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("completed-tombstone.json", None),))

            self.assertIs(raised.exception, original_signal)

        self.assertEqual(replace_attempts, 2)
        self.assertEqual(probe_attempts, 2)
        self.assertEqual(len(tombstone_placeholders), 1)
        self.assertEqual(len(resolved_owners), 1)
        self.assertEqual(resolved_owners[0].name, tombstone_placeholders[0].name)
        self.assertEqual(resolved_owners[0].identity, target_identity)
        self.assertNotEqual(
            resolved_owners[0].identity,
            tombstone_placeholders[0].identity,
        )
        self.assertFalse(Path(resolved_owners[0].path).exists())
        self.assertFalse(any(".tombstone" in path.name for path in self.artifact_directory.iterdir()))
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["completed-tombstone.json", "unrelated.txt"],
        )
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertEqual(
            self._directory_snapshot(self.artifact_directory)[sentinel.name],
            sentinel_before,
        )
        notes = "\n".join(getattr(raised.exception, "__notes__", ()))
        self.assertIn(str(first_probe_signal.code), notes)
        self.assertIn(str(second_probe_signal), notes)

    @unittest.skipIf(os.name == "nt", "POSIX unlink completion probe required")
    def test_absent_publish_post_success_probe_signal_records_and_rolls_back_unlink(
        self,
    ) -> None:
        target = self.artifact_directory / "persistent-unlink.json"
        target.write_bytes(b"old\n")
        probe_signal = KeyboardInterrupt("injected post-success absent publication probe interrupt")
        phases: list[str] = []
        public_unlink_completed = False
        probe_injected = False

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            original_unlink = transaction.directory.unlink
            original_lexists = transaction.directory.lexists

            def record_successful_unlink(
                *args: Any,
                **kwargs: Any,
            ) -> BaseException | None:
                nonlocal public_unlink_completed
                completion_error = original_unlink(*args, **kwargs)
                if args and args[0] == "persistent-unlink.json":
                    self.assertIsNone(completion_error)
                    public_unlink_completed = True
                return completion_error

            def fail_first_post_success_probe(name: str) -> bool:
                nonlocal probe_injected
                if name == "persistent-unlink.json" and public_unlink_completed and not probe_injected:
                    probe_injected = True
                    raise probe_signal
                return original_lexists(name)

            def record_phase(
                phase: str,
                _directory_path: str,
                _name: str | None,
            ) -> None:
                phases.append(phase)

            with (
                patch.object(
                    transaction.directory,
                    "unlink",
                    side_effect=record_successful_unlink,
                ),
                patch.object(
                    transaction.directory,
                    "lexists",
                    side_effect=fail_first_post_success_probe,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=record_phase,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("persistent-unlink.json", None),))

        self.assertTrue(public_unlink_completed)
        self.assertTrue(probe_injected)
        self.assertIs(raised.exception, probe_signal)
        self.assertIn("before_rollback", phases)
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["persistent-unlink.json"],
        )

    def test_successful_publish_surfaces_backup_cleanup_failure(self) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o640)
        cleanup_error = OSError("injected publication backup cleanup failure")
        retained_backup: Path | None = None

        def fail_backup_unlink(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal retained_backup
            if (
                phase != "before_unlink"
                or name is None
                or not name.endswith(".backup")
                or ".restore." in name
            ):
                return
            retained_backup = self.artifact_directory / name
            raise cleanup_error

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_backup_unlink,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertIs(raised.exception, cleanup_error)
        self.assertEqual(target.read_bytes(), b"new\n")
        self.assertIsNotNone(retained_backup)
        assert retained_backup is not None
        self.assertTrue(retained_backup.is_file())
        self.assertEqual(retained_backup.read_bytes(), b"old\n")
        self.assertArtifactModeEqual(
            stat.S_IMODE(retained_backup.stat().st_mode),
            0o640,
        )

    def test_successful_publish_preserves_cleanup_control_signal(self) -> None:
        for cleanup_signal in (
            KeyboardInterrupt("injected successful cleanup interrupt"),
            SystemExit(223),
        ):
            with self.subTest(signal_type=type(cleanup_signal).__name__):
                case_root = self.temp_dir / type(cleanup_signal).__name__
                case_artifacts = case_root / "gm2godot"
                case_root.mkdir()
                case_artifacts.mkdir()
                target = case_artifacts / "report.json"
                target.write_bytes(b"old\n")
                retained_backup: Path | None = None

                def interrupt_backup_unlink(
                    phase: str,
                    directory_path: str,
                    name: str | None,
                ) -> None:
                    nonlocal retained_backup
                    if (
                        phase != "before_unlink"
                        or name is None
                        or not name.endswith(".backup")
                    ):
                        return
                    retained_backup = Path(directory_path) / name
                    raise cleanup_signal

                with ByteArtifactTransaction.open(
                    str(case_root),
                    "gm2godot",
                    create=False,
                    description="test artifact directory",
                ) as transaction:
                    with (
                        patch(
                            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                            side_effect=interrupt_backup_unlink,
                        ),
                        self.assertRaises(BaseException) as raised,
                    ):
                        transaction.publish_specs(
                            (ArtifactSpec("report.json", b"new\n"),)
                        )

                self.assertIs(raised.exception, cleanup_signal)
                if isinstance(cleanup_signal, SystemExit):
                    self.assertEqual(cleanup_signal.code, 223)
                self.assertEqual(target.read_bytes(), b"new\n")
                self.assertIsNotNone(retained_backup)
                assert retained_backup is not None
                self.assertTrue(retained_backup.is_file())
                self.assertEqual(retained_backup.read_bytes(), b"old\n")

    def test_successful_restore_surfaces_receipt_backup_cleanup_failure(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o640)
        cleanup_error = OSError("injected restore receipt cleanup failure")
        retained_backup: Path | None = None

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

            def fail_receipt_backup_unlink(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal retained_backup
                if (
                    phase != "before_unlink"
                    or name is None
                    or not name.endswith(".restore.backup")
                ):
                    return
                retained_backup = self.artifact_directory / name
                raise cleanup_error

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_receipt_backup_unlink,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.restore_snapshots((snapshot,), (receipt,))

        self.assertIs(raised.exception, cleanup_error)
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertIsNotNone(retained_backup)
        assert retained_backup is not None
        self.assertTrue(retained_backup.is_file())
        self.assertEqual(retained_backup.read_bytes(), b"new\n")

    def test_publish_forward_error_survives_ordinary_cleanup_phase_errors(
        self,
    ) -> None:
        for cleanup_phase in ("before_cleanup", "after_cleanup"):
            with self.subTest(cleanup_phase=cleanup_phase):
                case_root = self.temp_dir / cleanup_phase
                case_artifacts = case_root / "gm2godot"
                case_root.mkdir()
                case_artifacts.mkdir()
                target = case_artifacts / "report.json"
                target.write_bytes(b"old\n")
                forward_error = OSError(
                    f"injected forward failure before {cleanup_phase}"
                )
                cleanup_error = OSError(
                    f"injected ordinary {cleanup_phase} failure"
                )
                cleanup_injected = False

                def fail_cleanup_phase(
                    phase: str,
                    _directory_path: str,
                    _name: str | None,
                ) -> None:
                    nonlocal cleanup_injected
                    if phase != cleanup_phase or cleanup_injected:
                        return
                    cleanup_injected = True
                    raise cleanup_error

                def fail_before_commit(_name: str) -> None:
                    raise forward_error

                with ByteArtifactTransaction.open(
                    str(case_root),
                    "gm2godot",
                    create=False,
                    description="test artifact directory",
                ) as transaction:
                    with (
                        patch(
                            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                            side_effect=fail_cleanup_phase,
                        ),
                        self.assertRaises(BaseException) as raised,
                    ):
                        transaction.publish_specs(
                            (ArtifactSpec("report.json", b"new\n"),),
                            before_commit=fail_before_commit,
                        )

                self.assertTrue(cleanup_injected)
                self.assertIs(raised.exception, forward_error)
                self.assertEqual(target.read_bytes(), b"old\n")
                self.assertTrue(
                    any(
                        str(cleanup_error) in note
                        for note in getattr(raised.exception, "__notes__", ())
                    )
                )

    def test_publish_cleanup_preserves_same_name_replacement_and_fails(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        replacement = self.root / "replacement-backup"
        replacement.write_bytes(b"external collision\n")
        replacement.chmod(0o600)
        replacement_identity = (replacement.stat().st_dev, replacement.stat().st_ino)
        collision: Path | None = None

        def replace_backup_before_cleanup(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal collision
            if phase != "before_cleanup":
                return
            candidates = tuple(self.artifact_directory.glob(".report.json.*.backup"))
            self.assertEqual(len(candidates), 1)
            collision = candidates[0]
            os.replace(replacement, collision)

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=replace_backup_before_cleanup,
                ),
                self.assertRaises(OSError) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertEqual(target.read_bytes(), b"new\n")
        self.assertIsNotNone(collision)
        assert collision is not None
        self.assertTrue(collision.is_file())
        self.assertEqual(collision.read_bytes(), b"external collision\n")
        self.assertEqual(
            (collision.stat().st_dev, collision.stat().st_ino),
            replacement_identity,
        )
        self.assertFalse(replacement.exists())
        self.assertTrue(
            collision.name in str(raised.exception)
            or any(
                collision.name in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )

    def test_publish_cleanup_system_exit_preempts_forward_error_with_note(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        forward_error = OSError("injected ordinary pre-commit failure")
        cleanup_signal = SystemExit(109)
        forward_injected = False
        cleanup_injected = False
        phases: list[str] = []

        def fail_forward_then_exit_after_cleanup_unlink(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal cleanup_injected, forward_injected
            phases.append(phase)
            if phase == "before_commit" and name == "report.json" and not forward_injected:
                forward_injected = True
                raise forward_error
            if phase == "after_unlink" and name is not None and name != "report.json" and not cleanup_injected:
                cleanup_injected = True
                raise cleanup_signal

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_forward_then_exit_after_cleanup_unlink,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertTrue(forward_injected)
        self.assertTrue(cleanup_injected)
        self.assertIs(raised.exception, cleanup_signal)
        self.assertEqual(cleanup_signal.code, 109)
        self.assertEqual(target.read_bytes(), b"old\n")
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(forward_error) in note for note in notes))
        self.assertIn("before_cleanup_durability", phases)
        self.assertIn("after_cleanup_durability", phases)

    def test_publish_forward_keyboard_interrupt_keeps_cleanup_failure_note(
        self,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        forward_signal = KeyboardInterrupt("injected pre-commit interrupt")
        cleanup_error = OSError("injected ordinary cleanup failure")
        forward_injected = False
        cleanup_injected = False

        def interrupt_forward_then_fail_cleanup(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal cleanup_injected, forward_injected
            if phase == "before_commit" and name == "report.json" and not forward_injected:
                forward_injected = True
                raise forward_signal
            if phase == "before_unlink" and name is not None and name != "report.json" and not cleanup_injected:
                cleanup_injected = True
                raise cleanup_error

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=interrupt_forward_then_fail_cleanup,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertTrue(forward_injected)
        self.assertTrue(cleanup_injected)
        self.assertIs(raised.exception, forward_signal)
        self.assertEqual(target.read_bytes(), b"old\n")
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any(str(cleanup_error) in note for note in notes))
        retained = [path for path in self.artifact_directory.iterdir() if path.name != "report.json"]
        self.assertEqual(len(retained), 1)

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

    def _assert_after_backup_failure_cleans_owned_stage(
        self,
        hook_error: BaseException,
    ) -> None:
        target = self.artifact_directory / "report.json"
        target.write_bytes(b"old\n")
        target.chmod(0o640)
        backup_path: Path | None = None
        error_injected = False

        def fail_after_backup(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal backup_path, error_injected
            if (
                phase != "after_backup"
                or name != "report.json"
                or error_injected
            ):
                return
            candidates = tuple(self.artifact_directory.glob(".report.json.*.backup"))
            self.assertEqual(len(candidates), 1)
            backup_path = candidates[0]
            error_injected = True
            raise hook_error

        with ByteArtifactTransaction.open(
            str(self.root),
            "gm2godot",
            create=False,
            description="test artifact directory",
        ) as transaction:
            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_after_backup,
                ),
                self.assertRaises(BaseException) as raised,
            ):
                transaction.publish_specs((ArtifactSpec("report.json", b"new\n"),))

        self.assertTrue(error_injected)
        self.assertIs(raised.exception, hook_error)
        self.assertIsNotNone(backup_path)
        assert backup_path is not None
        self.assertFalse(backup_path.exists())
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertArtifactModeEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertEqual(
            sorted(path.name for path in self.artifact_directory.iterdir()),
            ["report.json"],
        )

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

    def _overwrite_same_inode(self, path: Path, content: bytes) -> None:
        before = path.stat()
        self.assertEqual(len(content), before.st_size)
        with path.open("r+b", buffering=0) as artifact_file:
            artifact_file.write(content)
            artifact_file.truncate()
            os.fsync(artifact_file.fileno())
        os.utime(
            path,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )
        after = path.stat()
        self.assertEqual(
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        )

    @staticmethod
    def _stable_ctime_fingerprint(
        path_stat: os.stat_result,
    ) -> tuple[int, int, int, int, int]:
        return (
            path_stat.st_dev,
            path_stat.st_ino,
            path_stat.st_size,
            path_stat.st_mtime_ns,
            0,
        )


if __name__ == "__main__":
    unittest.main()
