from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest.mock import patch

from src.conversion import generation_inventory as inventory_module
from src.conversion import managed_output_publisher as publisher_module
from src.conversion.generation_inventory import (
    GenerationInventory,
    capture_generation_inventory,
    stage_inventory_carry_forward,
)
from src.conversion.managed_output_publisher import (
    MANAGED_OUTPUT_JOURNAL_NAME,
    MANAGED_OUTPUT_POINTER_NAME,
    MANAGED_OUTPUT_RECOVERY_NAME,
    publish_managed_output_attempt,
    publish_managed_output_generation,
    recover_managed_output_generation,
)
from src.conversion.managed_output_workspace import (
    WORKSPACE_PARENT_NAME,
    ManagedOutputWorkspace,
)


class TestManagedOutputPublisher(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.destination = self.temp_dir / "project"
        self.destination.mkdir()
        self.transaction_counter = 0

    def tearDown(self) -> None:
        shutil.rmtree(
            self.temp_dir,
            onexc=self._retry_windows_read_only_cleanup,
        )

    @staticmethod
    def _retry_windows_read_only_cleanup(
        function: Callable[..., object],
        path: str,
        error: BaseException,
    ) -> None:
        if not isinstance(error, PermissionError):
            raise error
        path_stat = os.lstat(path)
        os.chmod(path, stat.S_IMODE(path_stat.st_mode) | stat.S_IWRITE)
        function(path)

    def _transaction_id(self) -> str:
        self.transaction_counter += 1
        return f"{self.transaction_counter:032x}"

    @staticmethod
    def _json_bytes(payload: dict[str, object]) -> bytes:
        return (
            json.dumps(
                payload,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def _evidence(
        self,
        inventory: GenerationInventory,
        *,
        attempt_state: str = "success",
    ) -> tuple[bytes, bytes]:
        manifest = self._json_bytes(
            {
                "format_version": 2,
                "generation_inventory": inventory.to_dict(),
                "generated_files": [
                    entry.to_generated_file_dict()
                    for entry in inventory.entries
                ],
            }
        )
        attempt = self._json_bytes(
            {
                "format_version": 1,
                "attempt": {"state": attempt_state},
                "canonical_manifest": {
                    "path": "gm2godot/conversion_manifest.json",
                    "status": "updated",
                    "updated": True,
                    "current_output": "verified",
                    "sha256": (
                        "sha256:" + hashlib.sha256(manifest).hexdigest()
                    ),
                },
            }
        )
        return manifest, attempt

    @staticmethod
    def _write_stage(
        workspace: ManagedOutputWorkspace,
        files: dict[str, bytes],
        *,
        modes: dict[str, int] | None = None,
    ) -> None:
        stage = Path(workspace.stage_path)
        for relative_path, content in files.items():
            output = stage / relative_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            if modes is not None and relative_path in modes:
                output.chmod(modes[relative_path])

    def _publish_initial(
        self,
        files: dict[str, bytes],
        *,
        modes: dict[str, int] | None = None,
    ) -> GenerationInventory:
        previous = capture_generation_inventory(self.destination)
        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            self._write_stage(workspace, files, modes=modes)
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            publish_managed_output_generation(
                workspace,
                previous_inventory=previous,
                desired_inventory=desired,
                canonical_manifest_content=manifest,
                attempt_content=attempt,
            )
        return desired

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

    def _public_snapshot(
        self,
        inventory: GenerationInventory,
    ) -> dict[str, tuple[bytes, int]]:
        return {
            entry.path: (
                (self.destination / entry.path).read_bytes(),
                self._mode(self.destination / entry.path),
            )
            for entry in inventory.entries
        }

    def _assert_public_snapshot(
        self,
        snapshot: dict[str, tuple[bytes, int]],
    ) -> None:
        for relative_path, (content, mode) in snapshot.items():
            path = self.destination / relative_path
            self.assertEqual(path.read_bytes(), content)
            self.assertModeEqual(self._mode(path), mode)

    def _assert_no_pending_transaction(self) -> None:
        parent = self.destination / WORKSPACE_PARENT_NAME
        self.assertTrue(
            (parent / MANAGED_OUTPUT_POINTER_NAME).is_file()
        )
        self.assertFalse((parent / MANAGED_OUTPUT_JOURNAL_NAME).exists())
        self.assertFalse((parent / MANAGED_OUTPUT_RECOVERY_NAME).exists())
        self.assertFalse(
            any(path.name.endswith(".stage") for path in parent.iterdir())
        )

    def test_synthetic_generation_commits_create_replace_delete_and_evidence_last(
        self,
    ) -> None:
        previous = self._publish_initial(
            {
                "project.godot": b'[application]\nconfig/name="Old"\n',
                "scripts/replace.gd": b"old script\n",
                "rooms/unchanged.tscn": b"[gd_scene]\n",
                "sprites/delete.png": b"old sprite\n",
            },
            modes={
                "project.godot": 0o640,
                "scripts/replace.gd": 0o640,
                "rooms/unchanged.tscn": 0o444,
                "sprites/delete.png": 0o600,
            },
        )
        user_sentinel = self.destination / "user-owned.txt"
        user_sentinel.write_bytes(b"user sentinel\n")
        prior_manifest = (
            self.destination / "gm2godot" / "conversion_manifest.json"
        ).read_bytes()
        installed: list[str] = []

        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            stage = Path(workspace.stage_path)
            (stage / "scripts" / "replace.gd").chmod(0o600)
            (stage / "scripts" / "replace.gd").write_bytes(b"new script\n")
            (stage / "sprites" / "delete.png").unlink()
            created = stage / "objects" / "new" / "new.gd"
            created.parent.mkdir(parents=True)
            created.write_bytes(b"extends Node\n")
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)

            def record_install(phase: str, path: str | None) -> None:
                if phase == "public_installed" and path is not None:
                    installed.append(path)

            with patch.object(
                publisher_module,
                "_before_managed_output_phase",
                side_effect=record_install,
            ):
                receipt = publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )

        self.assertEqual(
            (self.destination / "scripts" / "replace.gd").read_bytes(),
            b"new script\n",
        )
        self.assertEqual(
            (self.destination / "rooms" / "unchanged.tscn").read_bytes(),
            b"[gd_scene]\n",
        )
        self.assertFalse(
            (self.destination / "sprites" / "delete.png").exists()
        )
        self.assertEqual(created.name, "new.gd")
        self.assertEqual(
            (self.destination / "objects" / "new" / "new.gd").read_bytes(),
            b"extends Node\n",
        )
        self.assertEqual(user_sentinel.read_bytes(), b"user sentinel\n")
        self.assertEqual(
            (self.destination / "gm2godot" / "conversion_manifest.json").read_bytes(),
            manifest,
        )
        self.assertNotEqual(manifest, prior_manifest)
        self.assertEqual(
            (self.destination / "gm2godot" / "conversion_attempt.json").read_bytes(),
            attempt,
        )
        self.assertTrue(installed[-2].endswith("conversion_attempt.json"))
        self.assertTrue(installed[-1].endswith("conversion_manifest.json"))
        self.assertEqual(receipt.manifest_sha256, "sha256:" + hashlib.sha256(manifest).hexdigest())
        self.assertEqual(
            capture_generation_inventory(self.destination),
            desired,
        )
        self.assertIsNone(
            recover_managed_output_generation(self.destination)
        )
        self._assert_no_pending_transaction()

    def test_invalid_stage_fails_before_journal_or_public_mutation(self) -> None:
        previous = self._publish_initial(
            {"scripts/main.gd": b"old bytes\n"}
        )
        prior = self._public_snapshot(previous)
        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            desired = capture_generation_inventory(workspace.stage_path)
            staged = Path(workspace.stage_path) / "scripts" / "main.gd"
            staged.write_bytes(b"new bytes\n")
            manifest, attempt = self._evidence(desired)
            with self.assertRaisesRegex(OSError, "changed"):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
        self._assert_public_snapshot(prior)
        self._assert_no_pending_transaction()

    def test_each_install_failure_rolls_back_complete_prior_generation(
        self,
    ) -> None:
        for failure_index in range(1, 6):
            with self.subTest(failure_index=failure_index):
                case_root = self.temp_dir / f"case-{failure_index}"
                case_root.mkdir()
                original_destination = self.destination
                self.destination = case_root
                try:
                    previous = self._publish_initial(
                        {
                            "scripts/a.gd": b"old a\n",
                            "scripts/b.gd": b"old b\n",
                            "sprites/old.png": b"old sprite\n",
                        }
                    )
                    prior = self._public_snapshot(previous)
                    sentinel = self.destination / "user-owned.txt"
                    sentinel.write_bytes(b"user\n")
                    install_count = 0
                    rollback_paths: list[str] = []
                    installed_paths: list[str] = []

                    def fail_install(
                        phase: str,
                        path: str | None,
                    ) -> None:
                        nonlocal install_count
                        if phase == "before_public_install":
                            install_count += 1
                            if install_count == failure_index:
                                raise OSError(
                                    f"injected install failure {failure_index}"
                                )
                        elif phase == "public_installed" and path is not None:
                            installed_paths.append(path)
                        elif phase == "before_rollback_desired" and path is not None:
                            rollback_paths.append(path)

                    with ManagedOutputWorkspace.open(
                        self.destination,
                        transaction_id=self._transaction_id(),
                    ) as workspace:
                        stage_inventory_carry_forward(
                            workspace,
                            previous,
                            enabled_converters=(),
                        )
                        stage = Path(workspace.stage_path)
                        (stage / "scripts" / "a.gd").write_bytes(b"new a\n")
                        (stage / "scripts" / "b.gd").write_bytes(b"new b\n")
                        (stage / "sprites" / "old.png").unlink()
                        created = stage / "rooms" / "new.tscn"
                        created.parent.mkdir()
                        created.write_bytes(b"new room\n")
                        desired = capture_generation_inventory(
                            workspace.stage_path
                        )
                        known_public_paths = {
                            *previous.by_path(),
                            *desired.by_path(),
                            "gm2godot/conversion_attempt.json",
                            "gm2godot/conversion_manifest.json",
                        }
                        manifest, attempt = self._evidence(desired)
                        with (
                            patch.object(
                                publisher_module,
                                "_before_managed_output_phase",
                                side_effect=fail_install,
                            ),
                            self.assertRaisesRegex(
                                OSError,
                                f"injected install failure {failure_index}",
                            ),
                        ):
                            publish_managed_output_generation(
                                workspace,
                                previous_inventory=previous,
                                desired_inventory=desired,
                                canonical_manifest_content=manifest,
                                attempt_content=attempt,
                            )

                    self._assert_public_snapshot(prior)
                    self.assertFalse(
                        (self.destination / "rooms" / "new.tscn").exists()
                    )
                    self.assertEqual(sentinel.read_bytes(), b"user\n")
                    if rollback_paths:
                        rollback_relative: list[str] = []
                        for path in rollback_paths:
                            if path.endswith("desired-attempt.json"):
                                rollback_relative.append(
                                    "gm2godot/conversion_attempt.json"
                                )
                            elif path.endswith("desired-manifest.json"):
                                rollback_relative.append(
                                    "gm2godot/conversion_manifest.json"
                                )
                            else:
                                rollback_relative.append(
                                    path.partition(
                                        ".stage" + os.sep
                                    )[2]
                                    .lstrip(os.sep)
                                    .replace("\\", "/")
                                )

                        def identify_public_path(path: str) -> str:
                            normalized = path.replace("\\", "/").casefold()
                            for candidate in sorted(
                                known_public_paths,
                                key=len,
                                reverse=True,
                            ):
                                folded = candidate.casefold()
                                if normalized == folded or normalized.endswith(
                                    "/" + folded
                                ):
                                    return candidate
                            raise AssertionError(
                                f"Unknown installed public path: {path}"
                            )

                        expected = [
                            identify_public_path(path)
                            for path in reversed(installed_paths)
                            if not path.endswith("sprites/old.png")
                        ]
                        self.assertEqual(rollback_relative, expected)
                    self.assertIsNone(
                        recover_managed_output_generation(self.destination)
                    )
                    self._assert_no_pending_transaction()
                finally:
                    self.destination = original_destination

    def test_rollback_failure_retains_artifact_and_retry_is_idempotent(
        self,
    ) -> None:
        previous = self._publish_initial(
            {
                "scripts/a.gd": b"old a\n",
                "scripts/b.gd": b"old b\n",
            }
        )
        prior = self._public_snapshot(previous)
        install_count = 0
        rollback_failed = False
        transaction_id = self._transaction_id()

        def fail_commit_and_rollback(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal install_count, rollback_failed
            if phase == "before_public_install":
                install_count += 1
                if install_count == 2:
                    raise OSError("injected commit failure")
            if phase == "before_rollback_previous" and not rollback_failed:
                rollback_failed = True
                raise OSError("injected rollback failure")

        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=transaction_id,
        ) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            stage = Path(workspace.stage_path)
            (stage / "scripts" / "a.gd").write_bytes(b"new a\n")
            (stage / "scripts" / "b.gd").write_bytes(b"new b\n")
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            with (
                patch.object(
                    publisher_module,
                    "_before_managed_output_phase",
                    side_effect=fail_commit_and_rollback,
                ),
                self.assertRaisesRegex(OSError, "injected commit failure"),
            ):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
            self.assertTrue(workspace.preserved_for_recovery)

        parent = self.destination / WORKSPACE_PARENT_NAME
        artifact_path = parent / MANAGED_OUTPUT_RECOVERY_NAME
        journal_path = parent / MANAGED_OUTPUT_JOURNAL_NAME
        self.assertTrue(artifact_path.is_file())
        self.assertTrue(journal_path.is_file())
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(artifact["transaction_id"], transaction_id)
        self.assertEqual(artifact["selected_generation"], "previous")
        self.assertIn("scripts/a.gd", artifact["affected_paths"])
        self.assertIn("Retry recover_managed_output_generation", artifact["next_step"])
        self.assertEqual(
            recover_managed_output_generation(self.destination),
            "rolled back the interrupted managed-output generation",
        )
        self._assert_public_snapshot(prior)
        self.assertFalse(artifact_path.exists())
        self.assertIsNone(
            recover_managed_output_generation(self.destination)
        )
        self._assert_no_pending_transaction()

    def test_cleanup_failure_keeps_committed_generation_and_recovers(
        self,
    ) -> None:
        previous = self._publish_initial(
            {"scripts/main.gd": b"old\n"}
        )
        desired_inventory: GenerationInventory | None = None
        desired_manifest = b""
        desired_attempt = b""
        failed = False

        def fail_cleanup_once(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal failed
            if phase == "before_private_cleanup" and not failed:
                failed = True
                raise OSError("injected cleanup failure")

        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            (Path(workspace.stage_path) / "scripts" / "main.gd").write_bytes(
                b"new\n"
            )
            desired_inventory = capture_generation_inventory(
                workspace.stage_path
            )
            desired_manifest, desired_attempt = self._evidence(
                desired_inventory
            )
            with (
                patch.object(
                    publisher_module,
                    "_before_managed_output_phase",
                    side_effect=fail_cleanup_once,
                ),
                self.assertRaisesRegex(OSError, "injected cleanup failure"),
            ):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired_inventory,
                    canonical_manifest_content=desired_manifest,
                    attempt_content=desired_attempt,
                )
            self.assertTrue(workspace.preserved_for_recovery)

        self.assertIsNotNone(desired_inventory)
        self.assertEqual(
            (self.destination / "scripts" / "main.gd").read_bytes(),
            b"new\n",
        )
        self.assertEqual(
            (self.destination / "gm2godot" / "conversion_manifest.json").read_bytes(),
            desired_manifest,
        )
        self.assertEqual(
            recover_managed_output_generation(self.destination),
            "finalized the committed managed-output generation",
        )
        self.assertEqual(
            capture_generation_inventory(self.destination),
            desired_inventory,
        )
        self.assertIsNone(
            recover_managed_output_generation(self.destination)
        )
        self._assert_no_pending_transaction()

    def test_concurrent_replacement_is_preserved_and_fails_closed(self) -> None:
        previous = self._publish_initial(
            {"scripts/main.gd": b"old\n"}
        )
        public_file = self.destination / "scripts" / "main.gd"
        replacement = self.temp_dir / "replacement.gd"
        replacement.write_bytes(b"concurrent user replacement\n")
        replaced = False

        def replace_before_displacement(
            phase: str,
            path: str | None,
        ) -> None:
            nonlocal replaced
            if (
                phase == "before_public_displace"
                and not replaced
            ):
                os.replace(replacement, public_file)
                replaced = True

        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            (Path(workspace.stage_path) / "scripts" / "main.gd").write_bytes(
                b"new\n"
            )
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            with (
                patch.object(
                    publisher_module,
                    "_before_managed_output_phase",
                    side_effect=replace_before_displacement,
                ),
                self.assertRaises(OSError),
            ):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
            self.assertTrue(workspace.preserved_for_recovery)

        self.assertTrue(replaced)
        self.assertEqual(
            public_file.read_bytes(),
            b"concurrent user replacement\n",
        )
        artifact = (
            self.destination
            / WORKSPACE_PARENT_NAME
            / MANAGED_OUTPUT_RECOVERY_NAME
        )
        self.assertTrue(artifact.is_file())
        with self.assertRaisesRegex(OSError, "Unknown public replacement"):
            recover_managed_output_generation(self.destination)
        self.assertEqual(
            public_file.read_bytes(),
            b"concurrent user replacement\n",
        )

    def test_attempt_only_publication_preserves_verified_generation(self) -> None:
        inventory = self._publish_initial(
            {
                "scripts/main.gd": b"stable output\n",
                "rooms/main.tscn": b"[gd_scene]\n",
            }
        )
        before = self._public_snapshot(inventory)
        manifest_path = (
            self.destination / "gm2godot" / "conversion_manifest.json"
        )
        manifest = manifest_path.read_bytes()
        failed_attempt = self._json_bytes(
            {
                "format_version": 1,
                "attempt": {"state": "failed"},
                "canonical_manifest": {
                    "path": "gm2godot/conversion_manifest.json",
                    "status": "preserved",
                    "updated": False,
                    "current_output": "unverified",
                    "sha256": (
                        "sha256:" + hashlib.sha256(manifest).hexdigest()
                    ),
                },
            }
        )
        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            publish_managed_output_attempt(
                workspace,
                verified_inventory=inventory,
                attempt_content=failed_attempt,
            )

        self._assert_public_snapshot(before)
        self.assertEqual(manifest_path.read_bytes(), manifest)
        self.assertEqual(
            (self.destination / "gm2godot" / "conversion_attempt.json").read_bytes(),
            failed_attempt,
        )
        self._assert_no_pending_transaction()

    def test_bounded_journal_failure_preserves_public_generation(self) -> None:
        previous = self._publish_initial(
            {
                "scripts/a.gd": b"old a\n",
                "scripts/b.gd": b"old b\n",
            }
        )
        prior = self._public_snapshot(previous)
        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            (Path(workspace.stage_path) / "scripts" / "a.gd").write_bytes(
                b"new a\n"
            )
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            with (
                patch.object(
                    publisher_module,
                    "_JOURNAL_MAX_BYTES",
                    256,
                ),
                self.assertRaisesRegex(OSError, "journal exceeds"),
            ):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
        self._assert_public_snapshot(prior)
        self._assert_no_pending_transaction()

    @unittest.skipUnless(os.name == "posix", "POSIX links are required")
    def test_symlink_and_hardlink_public_entries_preserve_external_targets(
        self,
    ) -> None:
        previous = self._publish_initial(
            {"scripts/main.gd": b"old\n"}
        )
        public_file = self.destination / "scripts" / "main.gd"
        external = self.temp_dir / "external.gd"
        external.write_bytes(b"external sentinel\n")
        public_file.unlink()
        public_file.symlink_to(external)
        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            self._write_stage(workspace, {"scripts/main.gd": b"new\n"})
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            with self.assertRaisesRegex(OSError, "redirected"):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
        self.assertEqual(external.read_bytes(), b"external sentinel\n")
        self.assertTrue(public_file.is_symlink())

        public_file.unlink()
        public_file.write_bytes(b"old\n")
        external.unlink()
        os.link(public_file, external)
        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            self._write_stage(workspace, {"scripts/main.gd": b"new\n"})
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            with self.assertRaisesRegex(OSError, "multiply-linked"):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
        self.assertEqual(external.read_bytes(), b"old\n")
        self.assertGreaterEqual(public_file.stat().st_nlink, 2)

    def test_modeled_nested_mount_fails_before_public_mutation(self) -> None:
        previous = self._publish_initial(
            {"scripts/main.gd": b"old\n"}
        )
        prior = self._public_snapshot(previous)
        scripts = self.destination / "scripts"
        real_ismount = os.path.ismount

        def modeled_mount(path: str | os.PathLike[str]) -> bool:
            return os.path.normcase(os.path.realpath(path)) == os.path.normcase(
                os.path.realpath(scripts)
            ) or real_ismount(path)

        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            self._write_stage(workspace, {"scripts/main.gd": b"new\n"})
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            with (
                patch.object(
                    inventory_module.os.path,
                    "ismount",
                    side_effect=modeled_mount,
                ),
                self.assertRaisesRegex(OSError, "mounted"),
            ):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
        self._assert_public_snapshot(prior)

    @unittest.skipIf(os.name == "nt", "physical POSIX directory swap required")
    def test_posix_directory_swap_is_rejected_without_external_traversal(
        self,
    ) -> None:
        previous = self._publish_initial(
            {"scripts/main.gd": b"old\n"}
        )
        scripts = self.destination / "scripts"
        parked = self.destination / "scripts.parked"
        external = self.temp_dir / "outside"
        external.mkdir()
        sentinel = external / "sentinel.gd"
        sentinel.write_bytes(b"external sentinel\n")
        swapped = False

        def swap_directory(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal swapped
            if phase == "before_public_displace" and not swapped:
                scripts.rename(parked)
                scripts.symlink_to(external, target_is_directory=True)
                swapped = True

        try:
            with ManagedOutputWorkspace.open(
                self.destination,
                transaction_id=self._transaction_id(),
            ) as workspace:
                stage_inventory_carry_forward(
                    workspace,
                    previous,
                    enabled_converters=(),
                )
                (
                    Path(workspace.stage_path) / "scripts" / "main.gd"
                ).write_bytes(b"new\n")
                desired = capture_generation_inventory(workspace.stage_path)
                manifest, attempt = self._evidence(desired)
                with (
                    patch.object(
                        publisher_module,
                        "_before_managed_output_phase",
                        side_effect=swap_directory,
                    ),
                    self.assertRaises(OSError),
                ):
                    publish_managed_output_generation(
                        workspace,
                        previous_inventory=previous,
                        desired_inventory=desired,
                        canonical_manifest_content=manifest,
                        attempt_content=attempt,
                    )
            self.assertTrue(swapped)
            self.assertTrue(scripts.is_symlink())
            self.assertEqual(sentinel.read_bytes(), b"external sentinel\n")
        finally:
            if scripts.is_symlink():
                scripts.unlink()
            if parked.exists() and not scripts.exists():
                parked.rename(scripts)

    def test_malformed_journal_is_preserved_and_rejected(self) -> None:
        inventory = self._publish_initial(
            {"scripts/main.gd": b"stable\n"}
        )
        before = self._public_snapshot(inventory)
        journal = (
            self.destination
            / WORKSPACE_PARENT_NAME
            / MANAGED_OUTPUT_JOURNAL_NAME
        )
        malformed = b'{"format_version":1,"unexpected":true}\n'
        journal.write_bytes(malformed)

        with self.assertRaisesRegex(OSError, "journal"):
            recover_managed_output_generation(self.destination)

        self.assertEqual(journal.read_bytes(), malformed)
        self._assert_public_snapshot(before)

    @unittest.skipUnless(sys.platform == "win32", "native Windows required")
    def test_windows_read_only_replacement_uses_write_through_moves(self) -> None:
        previous = self._publish_initial(
            {"scripts/main.gd": b"old\n"},
            modes={"scripts/main.gd": stat.S_IREAD},
        )
        public_file = self.destination / "scripts" / "main.gd"
        move_calls: list[tuple[str, str]] = []
        real_move = cast(
            Callable[[str, str], None],
            getattr(
                publisher_module.workspace_module,
                "_rename_noreplace_windows",
            ),
        )

        def record_move(source: str, destination: str) -> None:
            move_calls.append((source, destination))
            real_move(source, destination)

        with ManagedOutputWorkspace.open(
            self.destination,
            transaction_id=self._transaction_id(),
        ) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            staged = Path(workspace.stage_path) / "scripts" / "main.gd"
            staged.chmod(stat.S_IWRITE | stat.S_IREAD)
            staged.write_bytes(b"new\n")
            staged.chmod(stat.S_IREAD)
            desired = capture_generation_inventory(workspace.stage_path)
            manifest, attempt = self._evidence(desired)
            with patch.object(
                publisher_module.workspace_module,
                "_rename_noreplace_windows",
                side_effect=record_move,
            ):
                publish_managed_output_generation(
                    workspace,
                    previous_inventory=previous,
                    desired_inventory=desired,
                    canonical_manifest_content=manifest,
                    attempt_content=attempt,
                )
        self.assertEqual(public_file.read_bytes(), b"new\n")
        self.assertFalse(self._mode(public_file) & stat.S_IWUSR)
        self.assertGreater(len(move_calls), 0)
        self._assert_no_pending_transaction()

    @unittest.skipUnless(sys.platform == "win32", "native Windows junction required")
    def test_windows_junction_is_rejected_without_touching_external_sentinel(
        self,
    ) -> None:
        external = self.temp_dir / "junction-target"
        external.mkdir()
        sentinel = external / "sentinel.gd"
        sentinel.write_bytes(b"junction sentinel\n")
        junction = self.destination / "scripts"
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
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        try:
            with ManagedOutputWorkspace.open(
                self.destination,
                transaction_id=self._transaction_id(),
            ) as workspace:
                self._write_stage(workspace, {"scripts/main.gd": b"new\n"})
                desired = capture_generation_inventory(workspace.stage_path)
                manifest, attempt = self._evidence(desired)
                with self.assertRaisesRegex(OSError, "redirected"):
                    publish_managed_output_generation(
                        workspace,
                        previous_inventory=GenerationInventory(),
                        desired_inventory=desired,
                        canonical_manifest_content=manifest,
                        attempt_content=attempt,
                    )
            self.assertEqual(sentinel.read_bytes(), b"junction sentinel\n")
        finally:
            if os.path.isjunction(junction):
                os.rmdir(junction)


if __name__ == "__main__":
    unittest.main()
