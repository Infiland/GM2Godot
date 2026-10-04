# pyright: reportPrivateUsage=false

import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from collections.abc import Collection, Iterable, Mapping
from typing import BinaryIO, Callable
from unittest.mock import patch

if (PROJECT_ROOT := os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion import included_files as included_files_module
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.included_file_paths import IncludedFilePathAssignment
from src.conversion.included_file_registry import INCLUDED_FILE_REGISTRY_RELATIVE_PATH
from src.conversion.included_files_parts import (
    constants as _included_constants,
    driver as _included_driver,
    file_publication as _included_file_publication,
    generation_matching as _included_generation_matching,
    guarded_mutations as _included_mutations,
    locking as _included_locking,
    native_posix as _included_posix,
    native_windows as _included_windows,
    phase_observer as _included_phases,
    publisher as _included_publisher,
    record_io as _included_records,
    recorded_cleanup as _included_cleanup,
    recovery as _included_recovery,
    recovery_codec as _included_codec,
    source_snapshots as _included_snapshots,
    staging as _included_staging,
    stat_metadata as _included_metadata,
)
from tests import included_files_support as _included_support

_included_files_transaction_debris = _included_support.included_files_transaction_debris
_ModeledWindowsCleanupParentBinding = _included_support.ModeledWindowsCleanupParentBinding


class TestIncludedFilesManagedRootTransaction(_included_support.IncludedManagedRootFixture):
    def test_windows_nested_absent_subtree_skips_descendant_work(self) -> None:
        root_path = os.path.join(self.godot_dir, "windows-absent-stage")
        nested_path = os.path.join(root_path, "included_files")
        deep_path = os.path.join(nested_path, "deep")
        os.makedirs(deep_path)
        expected_contents: dict[str, bytes] = {}
        for index in range(16):
            filename = f"entry-{index:04d}.txt"
            content = f"preserved payload {index}\n".encode()
            expected_contents[filename] = content
            with open(os.path.join(deep_path, filename), "wb") as entry_file:
                entry_file.write(content)

        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        published_path = os.path.join(
            self.godot_dir,
            "windows-published-stage",
        )
        os.rename(nested_path, published_path)
        bindings: list[_ModeledWindowsCleanupParentBinding] = []

        def open_binding(
            path: str,
            identity: tuple[int, int],
        ) -> _ModeledWindowsCleanupParentBinding:
            binding = _ModeledWindowsCleanupParentBinding(path, identity)
            bindings.append(binding)
            return binding

        cleanup_file_state = _included_cleanup.included_cleanup_file_state
        cleanup_directory_state = (
            _included_cleanup.included_cleanup_directory_state
        )
        with (
            self._modeled_windows_cleanup_context(open_binding),
            patch.object(
                _included_cleanup,
                'included_cleanup_file_state',
                wraps=cleanup_file_state,
            ) as file_state_mock,
            patch.object(
                _included_cleanup,
                'included_cleanup_directory_state',
                wraps=cleanup_directory_state,
            ) as directory_state_mock,
        ):
            warnings = _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "b" * 32,
                "windows-absent-stage",
            )

        self.assertEqual(warnings, ())
        self.assertEqual(file_state_mock.call_count, 0)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].path, os.path.abspath(root_path))
        self.assertTrue(bindings[0].closed)
        self.assertEqual(bindings[0].close_count, 1)
        probed_directory_paths = {
            os.path.abspath(call.args[0])
            for call in directory_state_mock.call_args_list
        }
        self.assertNotIn(os.path.abspath(deep_path), probed_directory_paths)
        self.assertFalse(os.path.lexists(root_path))
        published_deep_path = os.path.join(published_path, "deep")
        self.assertEqual(
            sorted(os.listdir(published_deep_path)),
            sorted(expected_contents),
        )
        for filename, expected_content in expected_contents.items():
            with open(
                os.path.join(published_deep_path, filename),
                "rb",
            ) as published_file:
                self.assertEqual(published_file.read(), expected_content)

    def test_windows_nested_bindings_close_before_parent_removal(self) -> None:
        root_path = os.path.join(self.godot_dir, "nested-binding-lifetime")
        nested_path = os.path.join(root_path, "nested")
        deep_path = os.path.join(nested_path, "deep")
        os.makedirs(deep_path)
        payload_path = os.path.join(deep_path, "payload.txt")
        with open(payload_path, "wb") as payload_file:
            payload_file.write(b"binding lifetime payload\n")

        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        bindings: list[_ModeledWindowsCleanupParentBinding] = []
        live_bindings_before_move: dict[str, frozenset[str]] = {}

        def open_binding(
            path: str,
            identity: tuple[int, int],
        ) -> _ModeledWindowsCleanupParentBinding:
            binding = _ModeledWindowsCleanupParentBinding(path, identity)
            bindings.append(binding)
            return binding

        def record_live_bindings(source: str, _destination: str) -> None:
            live_bindings_before_move[os.path.abspath(source)] = frozenset(
                binding.path for binding in bindings if not binding.closed
            )

        with (
            self._modeled_windows_cleanup_context(open_binding),
            patch.object(
                _included_mutations,
                'before_included_transaction_rename_fallback',
                side_effect=record_live_bindings,
            ),
        ):
            warnings = _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "3" * 32,
                "nested-lifetime",
            )

        absolute_root = os.path.abspath(root_path)
        absolute_nested = os.path.abspath(nested_path)
        absolute_deep = os.path.abspath(deep_path)
        self.assertEqual(warnings, ())
        self.assertEqual(
            live_bindings_before_move[os.path.abspath(payload_path)],
            frozenset({absolute_root, absolute_nested, absolute_deep}),
        )
        self.assertEqual(
            live_bindings_before_move[absolute_deep],
            frozenset({absolute_root, absolute_nested}),
        )
        self.assertEqual(
            live_bindings_before_move[absolute_nested],
            frozenset({absolute_root}),
        )
        self.assertEqual(
            live_bindings_before_move[absolute_root],
            frozenset(),
        )
        self.assertTrue(all(binding.closed for binding in bindings))
        self.assertTrue(all(binding.close_count == 1 for binding in bindings))
        self.assertFalse(os.path.lexists(root_path))

    def test_windows_child_binding_open_rechecks_nested_parent(self) -> None:
        root_path = os.path.join(self.godot_dir, "nested-open-race")
        outer_path = os.path.join(root_path, "outer")
        parked_outer_path = os.path.join(root_path, "outer-parked")
        inner_path = os.path.join(outer_path, "inner")
        owned_path = os.path.join(inner_path, "owned.txt")
        os.makedirs(inner_path)
        with open(owned_path, "wb") as owned_file:
            owned_file.write(b"recorded acquisition-race content\n")

        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        bindings: list[_ModeledWindowsCleanupParentBinding] = []
        parent_changed = False

        def open_binding(
            path: str,
            identity: tuple[int, int],
        ) -> _ModeledWindowsCleanupParentBinding:
            nonlocal parent_changed
            binding = _ModeledWindowsCleanupParentBinding(path, identity)
            bindings.append(binding)
            if (
                not parent_changed
                and os.path.abspath(path) == os.path.abspath(inner_path)
            ):
                self.assertTrue(
                    any(
                        candidate.path == os.path.abspath(outer_path)
                        and not candidate.closed
                        for candidate in bindings
                    )
                )
                os.rename(outer_path, parked_outer_path)
                os.makedirs(inner_path)
                with open(owned_path, "wb") as replacement_file:
                    replacement_file.write(b"unknown acquisition replacement\n")
                parent_changed = True
            return binding

        with (
            self._modeled_windows_cleanup_context(open_binding),
            self.assertRaisesRegex(OSError, "cleanup parent changed"),
        ):
            _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "5" * 32,
                "nested-open-race",
            )

        self.assertTrue(parent_changed)
        self.assertEqual(len(bindings), 4)
        self.assertTrue(all(binding.closed for binding in bindings))
        self.assertTrue(all(binding.close_count == 1 for binding in bindings))
        self.assertEqual(bindings[-1].path, os.path.abspath(inner_path))
        with open(
            os.path.join(parked_outer_path, "inner", "owned.txt"),
            "rb",
        ) as parked_file:
            self.assertEqual(
                parked_file.read(),
                b"recorded acquisition-race content\n",
            )
        with open(owned_path, "rb") as replacement_file:
            self.assertEqual(
                replacement_file.read(),
                b"unknown acquisition replacement\n",
            )

    def test_first_publication_rollback_is_idempotent_after_registry_publish(
        self,
    ) -> None:
        self._write("first.txt", "first generation")
        root_path = os.path.join(self.godot_dir, "included_files")
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(registry_path)
        self.assertFalse(os.path.lexists(root_path))
        self.assertFalse(os.path.lexists(registry_path))
        self.assertFalse(os.path.lexists(registry_directory))

        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import phase_observer as included_phase_observer
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "new-registry-published":
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
        self.assertTrue(os.path.isdir(root_path))
        self.assertTrue(os.path.isfile(registry_path))

        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
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

        def assert_absent_generation() -> None:
            self.assertFalse(os.path.lexists(root_path))
            self.assertFalse(os.path.lexists(registry_path))
            self.assertFalse(os.path.lexists(registry_directory))
            self._assert_no_transaction_debris()
            self.assertEqual(
                set(os.listdir(self.godot_dir)),
                {_included_constants.INCLUDED_FILES_LOCK_NAME},
            )

        first_recovery = recover()
        self.assertIsNotNone(first_recovery)
        self.assertIn("rolled back", first_recovery or "")
        assert_absent_generation()

        self.assertIsNone(recover())
        assert_absent_generation()

    def test_noncanonical_reserved_temporaries_are_preserved_and_nonblocking(
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
        canonical_commit_content = (
            _included_codec.included_recovery_record_content(commit_payload)
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

        self.assertIsNotNone(recover())
        committed_pair = self._pair_snapshot()
        invalid_records = {
            (
                _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + "f" * 15
                + ".tmp"
            ): b"short reserved token\n",
            (
                _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + "f" * 17
                + ".tmp"
            ): b"long reserved token\n",
            (
                _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "g" * 16
                + ".tmp"
            ): b"non-hex reserved token\n",
            (
                _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "F" * 16
                + ".tmp"
            ): b"uppercase reserved token\n",
            (
                _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "f" * 16
                + ".extra.tmp"
            ): b"extra reserved token material\n",
            (
                _included_constants.INCLUDED_FILES_STAGE_PREFIX
                + "user-owned.tmp"
            ): b"arbitrary reserved-prefix temporary\n",
        }
        invalid_identities: dict[str, tuple[int, int]] = {}
        for name, content in invalid_records.items():
            record_path = os.path.join(self.godot_dir, name)
            with open(record_path, "wb") as record_file:
                record_file.write(content)
            record_stat = os.lstat(record_path)
            invalid_identities[name] = (record_stat.st_dev, record_stat.st_ino)

        canonical_commit_temporary = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
            + "a" * 16
            + ".tmp",
        )
        with open(canonical_commit_temporary, "wb") as temporary_file:
            temporary_file.write(canonical_commit_content)

        recovery_message = recover()

        self.assertIsNotNone(recovery_message)
        self.assertIn("removed 1", recovery_message or "")
        self.assertFalse(os.path.lexists(canonical_commit_temporary))
        for name, expected_content in invalid_records.items():
            with self.subTest(preserved=name):
                record_path = os.path.join(self.godot_dir, name)
                record_stat = os.lstat(record_path)
                self.assertEqual(
                    (record_stat.st_dev, record_stat.st_ino),
                    invalid_identities[name],
                )
                with open(record_path, "rb") as record_file:
                    self.assertEqual(record_file.read(), expected_content)
        self.assertEqual(self._pair_snapshot(), committed_pair)

        self.assertIsNotNone(recover())
        self.assertEqual(self._pair_snapshot(), committed_pair)

    def test_changed_payload_uses_the_normal_output_transaction(self) -> None:
        self._write("payload.txt", "BEFORE")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "AFTER!")
        original_create_stage = (
            _included_staging.create_included_output_stage
        )

        with patch.object(
            _included_staging,
            'create_included_output_stage',
            wraps=original_create_stage,
        ) as create_stage:
            converter.convert_all()

        create_stage.assert_called_once()
        current_pair = self._pair_snapshot()
        self.assertNotEqual(current_pair[0], previous_pair[0])
        self.assertEqual(current_pair[1], {"payload.txt": b"AFTER!"})
        self._assert_no_transaction_debris()

    def test_final_output_hardlink_substitution_restores_previous_generation(
        self,
    ) -> None:
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "CHANGED!")
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        external_path = os.path.join(
            self.gm_dir,
            "receipt-hardlink.bin",
        )
        with open(external_path, "wb") as external_file:
            external_file.write(b"CHANGED!")
        substituted = False

        def substitute_hardlink() -> None:
            nonlocal substituted
            os.unlink(output_path)
            try:
                os.link(external_path, output_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Hard links are unavailable: {error}")
            substituted = True

        with (
            patch.object(
                _included_publisher,
                'before_included_changed_generation_final_validation',
                side_effect=substitute_hardlink,
            ),
            self.assertRaisesRegex(
                OSError,
                "root generation|tree changed",
            ),
        ):
            converter.convert_all()

        self.assertTrue(substituted)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        with open(external_path, "rb") as external_file:
            self.assertEqual(external_file.read(), b"CHANGED!")

    def test_changed_path_uses_the_normal_output_transaction(
        self,
    ) -> None:
        self._write("old.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        os.rename(
            os.path.join(self.datafiles_dir, "old.txt"),
            os.path.join(self.datafiles_dir, "new.txt"),
        )
        original_create_stage = (
            _included_staging.create_included_output_stage
        )

        with patch.object(
            _included_staging,
            'create_included_output_stage',
            wraps=original_create_stage,
        ) as create_stage:
            converter.convert_all()

        create_stage.assert_called_once()
        self.assertEqual(self._pair_snapshot()[1], {"new.txt": b"stable"})
        self._assert_no_transaction_debris()

    def test_changed_registry_rendering_uses_the_normal_output_transaction(
        self,
    ) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        original_render = _included_driver.render_included_file_registry
        original_create_stage = (
            _included_staging.create_included_output_stage
        )

        def changed_render(
            assignments: Iterable[IncludedFilePathAssignment],
            emitted_logical_paths: Collection[str],
            content_receipts: Mapping[str, tuple[int, str]] | None = None,
        ) -> str:
            return (
                original_render(
                    assignments,
                    emitted_logical_paths,
                    content_receipts,
                )
                + "# changed rendering\n"
            )

        with (
            patch.object(
                _included_driver,
                "render_included_file_registry",
                side_effect=changed_render,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
                wraps=original_create_stage,
            ) as create_stage,
        ):
            converter.convert_all()

        create_stage.assert_called_once()
        with open(registry_path, "rb") as registry_file:
            self.assertTrue(registry_file.read().endswith(b"# changed rendering\n"))
        self._assert_no_transaction_debris()

    def test_staged_payload_hardlink_is_rejected_before_publication(self) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        external_path = os.path.join(
            self.gm_dir,
            "external-staged-payload.txt",
        )
        original_capture = _included_snapshots.capture_included_tree
        hardlink_created = False

        def capture_with_hardlink(
            root_path: str,
            *,
            expected_parent_identity: (
                included_files_module._PathIdentity | None
            ) = None,
            include_content: bool = True,
        ) -> included_files_module._IncludedTreeSnapshot:
            nonlocal hardlink_created
            stage_name = os.path.basename(os.path.dirname(root_path))
            if (
                not hardlink_created
                and os.path.basename(root_path)
                == _included_constants.INCLUDED_FILES_ROOT_NAME
                and stage_name.startswith(
                    _included_constants.INCLUDED_FILES_STAGE_PREFIX
                )
            ):
                staged_path = os.path.join(root_path, "new.txt")
                try:
                    os.link(staged_path, external_path)
                except (NotImplementedError, OSError) as error:
                    self.skipTest(f"Hard links are unavailable: {error}")
                hardlink_created = True
            return original_capture(
                root_path,
                expected_parent_identity=expected_parent_identity,
                include_content=include_content,
            )

        with (
            patch.object(
                _included_snapshots,
                'capture_included_tree',
                side_effect=capture_with_hardlink,
            ),
            self.assertRaisesRegex(OSError, "multiple hard links"),
        ):
            converter.convert_all()

        self.assertTrue(hardlink_created)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        with open(external_path, "rb") as external_file:
            self.assertEqual(external_file.read(), b"new generation")
        self._assert_no_transaction_debris()

    def test_staged_registry_hardlink_is_rejected_before_publication(self) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        external_path = os.path.join(
            self.gm_dir,
            "external-staged-registry.gd",
        )
        external_content: bytes | None = None
        original_snapshot = (
            _included_staging.included_stage_container_snapshot
        )

        def snapshot_with_hardlink(
            project_identity: included_files_module._PathIdentity,
            stage_path: str,
            stage_identity: included_files_module._PathIdentity,
            staged_root_snapshot: included_files_module._IncludedTreeSnapshot,
            staged_registry_identity: included_files_module._PathIdentity,
            staged_registry_content: bytes,
        ) -> included_files_module._IncludedTreeSnapshot:
            nonlocal external_content
            staged_registry_path = os.path.join(
                stage_path,
                "gml_included_file_registry.gd",
            )
            try:
                os.link(staged_registry_path, external_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Hard links are unavailable: {error}")
            with open(external_path, "rb") as external_file:
                external_content = external_file.read()
            return original_snapshot(
                project_identity,
                stage_path,
                stage_identity,
                staged_root_snapshot,
                staged_registry_identity,
                staged_registry_content,
            )

        with (
            patch.object(
                _included_staging,
                'included_stage_container_snapshot',
                side_effect=snapshot_with_hardlink,
            ),
            self.assertRaisesRegex(OSError, "multiple hard links"),
        ):
            converter.convert_all()

        self.assertIsNotNone(external_content)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        with open(external_path, "rb") as external_file:
            self.assertEqual(external_file.read(), external_content)
        self._assert_no_transaction_debris()

    def test_collision_and_availability_changes_use_normal_transactions(
        self,
    ) -> None:
        self._write("Alpha Beta.txt", "first")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        self._write("alpha_beta.txt", "second")
        original_create_stage = (
            _included_staging.create_included_output_stage
        )

        with patch.object(
            _included_staging,
            'create_included_output_stage',
            wraps=original_create_stage,
        ) as collision_stage:
            converter.convert_all()
        collision_stage.assert_called_once()
        self.assertEqual(len(self._pair_snapshot()[1]), 2)

        os.unlink(os.path.join(self.datafiles_dir, "Alpha Beta.txt"))
        os.unlink(os.path.join(self.datafiles_dir, "alpha_beta.txt"))
        with patch.object(
            _included_staging,
            'create_included_output_stage',
            wraps=original_create_stage,
        ) as availability_stage:
            converter.convert_all()
        availability_stage.assert_called_once()
        self.assertEqual(self._pair_snapshot()[1], {})
        self._assert_no_transaction_debris()

    def test_late_same_size_public_mutation_is_rejected_without_staging(
        self,
    ) -> None:
        if os.name == "nt":
            self.skipTest("Windows ctime does not portably expose content changes")
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        output_stat = os.stat(output_path)
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_identity = os.lstat(registry_path).st_ino

        def mutate_public_payload() -> None:
            with open(output_path, "r+b", buffering=0) as output_file:
                output_file.write(b"MUTATED!")
                os.fsync(output_file.fileno())
            os.utime(
                output_path,
                ns=(output_stat.st_atime_ns, output_stat.st_mtime_ns),
            )

        with (
            patch.object(
                _included_generation_matching,
                'before_included_unchanged_final_revalidation',
                side_effect=mutate_public_payload,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("mutated no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "tree metadata changed"),
        ):
            converter.convert_all()

        with open(output_path, "rb") as output_file:
            self.assertEqual(output_file.read(), b"MUTATED!")
        self.assertEqual(os.lstat(registry_path).st_ino, registry_identity)
        self._assert_no_transaction_debris()

    def test_regular_file_in_place_of_managed_root_is_preserved(self) -> None:
        self._write("new.txt", "new")
        root_path = os.path.join(self.godot_dir, "included_files")
        with open(root_path, "wb") as root_file:
            root_file.write(b"unmanaged sentinel")
        converter = self._converter(max_workers=1)

        with self.assertRaisesRegex(OSError, "non-directory Included Files root"):
            converter.convert_all()

        with open(root_path, "rb") as root_file:
            self.assertEqual(root_file.read(), b"unmanaged sentinel")
        self.assertFalse(
            os.path.lexists(
                os.path.join(
                    self.godot_dir,
                    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                )
            )
        )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_fifo_in_staged_root_preserves_previous_pair(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFOs are unavailable")
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        original_process = converter._process_file

        def inject_fifo(
            gm_file_path: str,
            godot_file_path: str,
            relative_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool, object | None] | None:
            result = original_process(
                gm_file_path,
                godot_file_path,
                relative_path,
                owner_source_path,
            )
            os.mkfifo(os.path.join(os.path.dirname(godot_file_path), "rogue.fifo"))
            return result

        with patch.object(
            converter,
            "_process_file",
            side_effect=inject_fifo,
        ), self.assertRaisesRegex(OSError, "non-regular entry"):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_torn_source_mutation_during_copy_preserves_previous_pair(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        source_path = os.path.join(self.datafiles_dir, "new.bin")
        pre_mutation_payload = b"A" * (2 * 1024 * 1024)
        post_mutation_payload = b"B" * (2 * 1024 * 1024)
        with open(source_path, "wb") as source_file:
            source_file.write(pre_mutation_payload)
        original_stat = os.stat(source_path)
        original_read = _included_file_publication.read_included_payload_chunk
        original_fingerprint = _included_metadata.included_source_fingerprint
        mutated = False
        streamed_chunks: list[bytes] = []

        def mutate_already_read_bytes(source_file: BinaryIO) -> bytes:
            nonlocal mutated
            chunk = original_read(source_file)
            if chunk:
                streamed_chunks.append(chunk)
            if not mutated and chunk:
                with open(source_path, "r+b", buffering=0) as mutator:
                    mutator.seek(0)
                    mutator.write(post_mutation_payload)
                    os.fsync(mutator.fileno())
                os.utime(
                    source_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )
                mutated = True
            return chunk

        def windows_style_fingerprint(
            source_stat: os.stat_result,
        ) -> tuple[int, int, int, int, int, int]:
            fingerprint = original_fingerprint(source_stat)
            return (*fingerprint[:-1], original_stat.st_ctime_ns)

        with (
            patch.object(
                _included_file_publication,
                'read_included_payload_chunk',
                side_effect=mutate_already_read_bytes,
            ),
            patch.object(
                _included_metadata,
                'included_source_fingerprint',
                side_effect=windows_style_fingerprint,
            ),
            self.assertRaisesRegex(OSError, "output-set staging failed"),
        ):
            converter.convert_all()

        self.assertTrue(mutated)
        streamed_payload = b"".join(streamed_chunks)
        self.assertEqual(
            streamed_payload,
            b"A" * (1024 * 1024) + b"B" * (1024 * 1024),
        )
        self.assertNotEqual(streamed_payload, pre_mutation_payload)
        self.assertNotEqual(streamed_payload, post_mutation_payload)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_same_size_staged_mutation_with_restored_mtime_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "GOOD")
        original_commit = _included_publisher.commit_included_output_set
        mutated = False
        preserved_staged_file: str | None = None

        def mutate_then_commit(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal mutated, preserved_staged_file
            staged_file = os.path.join(
                transaction.staged_root_path,
                "new.txt",
            )
            preserved_staged_file = staged_file
            staged_stat = os.stat(staged_file)
            with open(staged_file, "r+b", buffering=0) as output_file:
                output_file.write(b"EVIL")
                os.fsync(output_file.fileno())
            os.utime(
                staged_file,
                ns=(staged_stat.st_atime_ns, staged_stat.st_mtime_ns),
            )
            if os.stat(staged_file).st_mtime_ns != staged_stat.st_mtime_ns:
                self.skipTest("Filesystem cannot restore nanosecond mtime")
            mutated = True
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        with patch.object(
            _included_publisher,
            'commit_included_output_set',
            side_effect=mutate_then_commit,
        ), self.assertRaisesRegex(OSError, "tree changed"):
            converter.convert_all()

        self.assertTrue(mutated)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self.assertIsNotNone(preserved_staged_file)
        if preserved_staged_file is not None:
            with open(preserved_staged_file, "rb") as staged_file:
                self.assertEqual(staged_file.read(), b"EVIL")
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (
                    os.path.basename(
                        os.path.dirname(os.path.dirname(preserved_staged_file))
                    ),
                ),
            )

    def test_first_registry_publication_failure_restores_absent_pair(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        final_root_path = os.path.join(self.godot_dir, "included_files")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(final_registry_path)
        original_move = _included_mutations.move_exact_included_file
        publication_failed = False

        def publish_then_fail(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
            windows_source_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
            windows_destination_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
        ) -> None:
            nonlocal publication_failed
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
                windows_source_parent_binding=windows_source_parent_binding,
                windows_destination_parent_binding=(
                    windows_destination_parent_binding
                ),
            )
            if destination == final_registry_path and not publication_failed:
                publication_failed = True
                raise OSError("injected first registry publication failure")

        with patch.object(
            _included_mutations,
            'move_exact_included_file',
            side_effect=publish_then_fail,
        ), self.assertRaisesRegex(
            OSError,
            "injected first registry publication failure",
        ):
            converter.convert_all()

        self.assertTrue(publication_failed)
        self.assertFalse(os.path.lexists(final_root_path))
        self.assertFalse(os.path.lexists(final_registry_path))
        self.assertFalse(os.path.lexists(registry_directory))
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_preprepare_rollback_refuses_appeared_registry_before_read(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        original_verify_tree = (
            _included_snapshots.verify_included_tree_snapshot
        )
        original_file_state_at = (
            _included_snapshots.included_regular_file_state_at
        )
        injected = False
        appeared_registry_read_attempts: list[str] = []

        def inject_registry_before_prepare(
            root_path: str,
            expected: included_files_module._IncludedTreeSnapshot,
            *,
            expected_parent_identity: tuple[int, int] | None = None,
        ) -> None:
            nonlocal injected
            original_verify_tree(
                root_path,
                expected,
                expected_parent_identity=expected_parent_identity,
            )
            if (
                not injected
                and os.path.basename(os.path.dirname(root_path)).startswith(
                    ".gm2godot-included-files-"
                )
            ):
                os.makedirs(os.path.dirname(final_registry_path))
                with open(final_registry_path, "wb") as registry_file:
                    registry_file.write(b"unknown appeared registry")
                injected = True
                raise OSError("injected failure before registry prepare")

        def record_registry_state_attempt(
            parent_fd: int,
            name: str,
            display_path: str,
            *,
            allowed_identities: frozenset[tuple[int, int]] | None = None,
        ) -> tuple[tuple[int, int], int, bytes] | None:
            if display_path == final_registry_path:
                appeared_registry_read_attempts.append(display_path)
            return original_file_state_at(
                parent_fd,
                name,
                display_path,
                allowed_identities=allowed_identities,
            )

        with (
            patch.object(
                _included_snapshots,
                'verify_included_tree_snapshot',
                side_effect=inject_registry_before_prepare,
            ),
            patch.object(
                _included_snapshots,
                'included_regular_file_state_at',
                side_effect=record_registry_state_attempt,
            ),
            self.assertRaisesRegex(
                OSError,
                "injected failure before registry prepare",
            ),
        ):
            converter.convert_all()

        self.assertTrue(injected)
        self.assertEqual(appeared_registry_read_attempts, [])
        with open(final_registry_path, "rb") as registry_file:
            self.assertEqual(registry_file.read(), b"unknown appeared registry")
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        debris = _included_files_transaction_debris(self.godot_dir)
        self.assertEqual(len(debris), 2)
        stage_relative_path = debris[0]
        self.assertTrue(
            stage_relative_path.startswith(
                _included_constants.INCLUDED_FILES_STAGE_PREFIX
            ),
            debris,
        )
        self.assertEqual(
            debris[1],
            stage_relative_path
            + "/"
            + _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME,
        )
        with open(
            os.path.join(
                self.godot_dir,
                stage_relative_path,
                "included_files",
                "new.txt",
            ),
            "rb",
        ) as staged_file:
            self.assertEqual(staged_file.read(), b"new")

    def test_unknown_registry_backup_destination_is_not_overwritten(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        original_rename = (
            _included_posix.rename_included_transaction_entry_at
        )
        sentinel_name: str | None = None

        def inject_unknown_destination(
            source_parent_fd: int,
            source_name: str,
            destination_parent_fd: int,
            destination_name: str,
        ) -> None:
            nonlocal sentinel_name
            if (
                sentinel_name is None
                and destination_name.startswith(
                    ".gml_included_file_registry.gd."
                )
                and destination_name.endswith(".backup")
            ):
                sentinel_fd = os.open(
                    destination_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=destination_parent_fd,
                )
                try:
                    os.write(sentinel_fd, b"unknown sentinel")
                    os.fsync(sentinel_fd)
                finally:
                    os.close(sentinel_fd)
                sentinel_name = destination_name
            original_rename(
                source_parent_fd,
                source_name,
                destination_parent_fd,
                destination_name,
            )

        def inject_unknown_destination_fallback(
            _source: str,
            destination: str,
        ) -> None:
            nonlocal sentinel_name
            destination_name = os.path.basename(destination)
            if (
                sentinel_name is None
                and destination_name.startswith(
                    ".gml_included_file_registry.gd."
                )
                and destination_name.endswith(".backup")
            ):
                with open(destination, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown sentinel")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
                sentinel_name = destination_name

        rename_patcher = (
            patch.object(
                _included_posix,
                'rename_included_transaction_entry_at',
                side_effect=inject_unknown_destination,
            )
            if _included_posix.included_descriptor_paths_supported()
            else patch.object(
                _included_mutations,
                'before_included_transaction_rename_fallback',
                side_effect=inject_unknown_destination_fallback,
            )
        )
        with rename_patcher, self.assertRaises(OSError):
            converter.convert_all()

        self.assertIsNotNone(sentinel_name)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        if sentinel_name is not None:
            sentinel_path = os.path.join(
                self.godot_dir,
                "gm2godot",
                sentinel_name,
            )
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(sentinel_file.read(), b"unknown sentinel")
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (
                    os.path.relpath(sentinel_path, self.godot_dir).replace(
                        os.sep,
                        "/",
                    ),
                ),
            )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )

    def test_cancelled_rollback_preserves_unknown_stage_content(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        cleanup_recorded_tree = (
            _included_cleanup.cleanup_recorded_included_tree
        )
        sentinel_path: str | None = None
        cancellation_injected = False

        def cancel_after_journal(phase: str) -> None:
            nonlocal cancellation_injected
            if phase == "journal-prepared":
                cancellation_injected = True
                self.running.clear()

        def inject_unknown_stage_content(
            path: str,
            snapshot: included_files_module._IncludedTreeSnapshot,
            expected_parent_identity: tuple[int, int],
            transaction_id: str,
            role: str,
        ) -> tuple[str, ...]:
            nonlocal sentinel_path
            if sentinel_path is None and role == "rollback-stage":
                sentinel_path = os.path.join(path, "unknown-sentinel.txt")
                with open(sentinel_path, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown cancelled stage content")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
            return cleanup_recorded_tree(
                path,
                snapshot,
                expected_parent_identity,
                transaction_id,
                role,
            )

        with (
            patch.object(
                _included_phases,
                'after_included_transaction_phase',
                side_effect=cancel_after_journal,
            ),
            patch.object(
                _included_cleanup,
                'cleanup_recorded_included_tree',
                side_effect=inject_unknown_stage_content,
            ),
        ):
            converter.convert_all()

        self.assertTrue(cancellation_injected)
        self.assertTrue(converter.conversion_step_result().cancelled)
        self.assertIsNotNone(sentinel_path)
        if sentinel_path is not None:
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(
                    sentinel_file.read(),
                    b"unknown cancelled stage content",
                )
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (os.path.basename(os.path.dirname(sentinel_path)),),
            )
        self.assertFalse(
            os.path.lexists(os.path.join(self.godot_dir, "included_files"))
        )

    def test_failed_rollback_preserves_unknown_stage_content(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        cleanup_recorded_tree = (
            _included_cleanup.cleanup_recorded_included_tree
        )
        sentinel_path: str | None = None

        def fail_after_journal(phase: str) -> None:
            if phase == "journal-prepared":
                raise OSError("injected commit failure")

        def inject_unknown_stage_content(
            path: str,
            snapshot: included_files_module._IncludedTreeSnapshot,
            expected_parent_identity: tuple[int, int],
            transaction_id: str,
            role: str,
        ) -> tuple[str, ...]:
            nonlocal sentinel_path
            if sentinel_path is None and role == "rollback-stage":
                sentinel_path = os.path.join(path, "unknown-sentinel.txt")
                with open(sentinel_path, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown failed stage content")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
            return cleanup_recorded_tree(
                path,
                snapshot,
                expected_parent_identity,
                transaction_id,
                role,
            )

        with (
            patch.object(
                _included_phases,
                'after_included_transaction_phase',
                side_effect=fail_after_journal,
            ),
            patch.object(
                _included_cleanup,
                'cleanup_recorded_included_tree',
                side_effect=inject_unknown_stage_content,
            ),
            self.assertRaisesRegex(OSError, "injected commit failure"),
        ):
            converter.convert_all()

        self.assertIsNotNone(sentinel_path)
        if sentinel_path is not None:
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(
                    sentinel_file.read(),
                    b"unknown failed stage content",
                )
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (os.path.basename(os.path.dirname(sentinel_path)),),
            )
        self.assertFalse(
            os.path.lexists(os.path.join(self.godot_dir, "included_files"))
        )

    def test_transaction_source_swap_restores_unknown_replacement_without_loss(
        self,
    ) -> None:
        if not (
            _included_posix.included_descriptor_paths_supported()
            and _included_posix.included_native_noreplace_available()
        ):
            self.skipTest("Descriptor-pinned no-replace rename is unavailable")
        transaction_directory = os.path.join(self.godot_dir, "source-swap")
        os.mkdir(transaction_directory)
        source_path = os.path.join(transaction_directory, "source.txt")
        replacement_path = os.path.join(
            transaction_directory,
            "replacement.txt",
        )
        parked_path = os.path.join(transaction_directory, "parked-owned.txt")
        destination_path = os.path.join(transaction_directory, "published.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("owned source")
        with open(replacement_path, "w", encoding="utf-8") as replacement_file:
            replacement_file.write("unknown replacement")
        source_stat = os.lstat(source_path)
        parent_stat = os.lstat(transaction_directory)
        swapped = False

        def swap_source(parent_fd: int, source_name: str) -> None:
            nonlocal swapped
            if swapped or source_name != "source.txt":
                return
            os.rename(
                source_name,
                os.path.basename(parked_path),
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.rename(
                os.path.basename(replacement_path),
                source_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            swapped = True

        with patch.object(
            _included_mutations,
            'before_included_transaction_rename',
            side_effect=swap_source,
        ), self.assertRaisesRegex(OSError, "restored without loss"):
            _included_mutations.move_exact_included_file(
                source_path,
                destination_path,
                (source_stat.st_dev, source_stat.st_ino),
                source_parent_identity=(parent_stat.st_dev, parent_stat.st_ino),
                destination_parent_identity=(
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
            )

        self.assertTrue(swapped)
        with open(source_path, encoding="utf-8") as source_file:
            self.assertEqual(source_file.read(), "unknown replacement")
        with open(parked_path, encoding="utf-8") as parked_file:
            self.assertEqual(parked_file.read(), "owned source")
        self.assertFalse(os.path.lexists(destination_path))

    @unittest.skipUnless(
        _included_posix.included_descriptor_paths_supported(),
        "Descriptor-pinned Included Files paths are unavailable",
    )
    def test_descriptor_and_fallback_tree_snapshots_are_byte_equivalent(
        self,
    ) -> None:
        root_path = os.path.join(self.godot_dir, "snapshot-equivalence")
        os.makedirs(os.path.join(root_path, "z", "nested"))
        os.makedirs(os.path.join(root_path, "a"))
        for relative_path, content in (
            ("z/nested/last.bin", b"\x00\xfflast\n"),
            ("a/first.txt", b"first\n"),
            ("middle.json", b'{"stable":true}\n'),
        ):
            output_path = os.path.join(root_path, *relative_path.split("/"))
            with open(output_path, "wb") as output_file:
                output_file.write(content)

        descriptor_snapshot = _included_snapshots.capture_included_tree(
            root_path
        )
        with patch.object(
            _included_posix,
            'included_descriptor_paths_supported',
            return_value=False,
        ):
            fallback_snapshot = _included_snapshots.capture_included_tree(
                root_path
            )

        descriptor_bytes = json.dumps(
            _included_codec.included_tree_snapshot_payload(
                descriptor_snapshot
            ),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        fallback_bytes = json.dumps(
            _included_codec.included_tree_snapshot_payload(
                fallback_snapshot
            ),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self.assertEqual(fallback_bytes, descriptor_bytes)

    def test_repeated_conversion_supports_file_directory_file_shapes(self) -> None:
        converter = self._converter()
        self._write("foo_bar", "blocking file")
        converter.convert_all()
        root_path = os.path.join(self.godot_dir, "included_files")
        self.assertTrue(os.path.isfile(os.path.join(root_path, "foo_bar")))

        self._write("Foo Bar/item.txt", "nested file")
        converter.convert_all()
        self.assertTrue(
            os.path.isfile(os.path.join(root_path, "foo_bar", "item.txt"))
        )
        with open(
            os.path.join(root_path, "foo_bar_2"),
            encoding="utf-8",
        ) as output_file:
            self.assertEqual(output_file.read(), "blocking file")

        shutil.rmtree(os.path.join(self.datafiles_dir, "Foo Bar"))
        converter.convert_all()
        self.assertTrue(os.path.isfile(os.path.join(root_path, "foo_bar")))
        self.assertFalse(os.path.lexists(os.path.join(root_path, "foo_bar_2")))
        self.assertEqual(os.listdir(root_path), ["foo_bar"])
        self._assert_no_transaction_debris()

    def test_second_root_rename_failure_restores_previous_pair(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        original_move = _included_mutations.move_exact_included_directory
        final_root_path = os.path.join(self.godot_dir, "included_files")

        def fail_staged_root_publish(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
            windows_source_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
            windows_destination_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
        ) -> None:
            if (
                destination == final_root_path
                and ".gm2godot-included-files-" in source
            ):
                raise OSError("injected root publication failure")
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
                windows_source_parent_binding=windows_source_parent_binding,
                windows_destination_parent_binding=(
                    windows_destination_parent_binding
                ),
            )

        with patch.object(
            _included_mutations,
            'move_exact_included_directory',
            side_effect=fail_staged_root_publish,
        ):
            with self.assertRaisesRegex(
                OSError,
                "injected root publication failure",
            ):
                converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_commit_failure_rolls_back_cleanly(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old/nested.txt", "old payload")
        converter.convert_all()
        public_root = os.path.join(self.godot_dir, "included_files")
        public_directory = os.path.join(public_root, "old")
        public_file = os.path.join(public_directory, "nested.txt")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        for path in (
            public_file,
            final_registry_path,
            public_directory,
            public_root,
        ):
            os.chmod(path, stat.S_IREAD)
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old", "nested.txt"))
        os.rmdir(os.path.join(self.datafiles_dir, "old"))
        self._write("new/nested.txt", "new payload")
        original_commit = _included_publisher.commit_included_output_set
        original_move = _included_mutations.move_exact_included_file
        publication_failed = False

        def commit_with_readonly_stage(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            return original_commit(
                project_path,
                self._transaction_with_native_windows_readonly_staged_root(
                    transaction
                ),
                conversion_running,
            )

        def publish_registry_then_fail(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
            windows_source_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
            windows_destination_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
        ) -> None:
            nonlocal publication_failed
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
                windows_source_parent_binding=windows_source_parent_binding,
                windows_destination_parent_binding=(
                    windows_destination_parent_binding
                ),
            )
            if destination == final_registry_path and not publication_failed:
                publication_failed = True
                raise OSError("injected native Windows commit failure")

        with (
            patch.object(
                _included_publisher,
                'commit_included_output_set',
                side_effect=commit_with_readonly_stage,
            ),
            patch.object(
                _included_mutations,
                'move_exact_included_file',
                side_effect=publish_registry_then_fail,
            ),
            self.assertRaisesRegex(
                OSError,
                "injected native Windows commit failure",
            ),
        ):
            converter.convert_all()

        self.assertTrue(publication_failed)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_cancellation_rolls_back_cleanly(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old/nested.txt", "old payload")
        converter.convert_all()
        public_root = os.path.join(self.godot_dir, "included_files")
        public_directory = os.path.join(public_root, "old")
        public_file = os.path.join(public_directory, "nested.txt")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        for path in (
            public_file,
            final_registry_path,
            public_directory,
            public_root,
        ):
            os.chmod(path, stat.S_IREAD)
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old", "nested.txt"))
        os.rmdir(os.path.join(self.datafiles_dir, "old"))
        self._write("new/nested.txt", "new payload")
        original_commit = _included_publisher.commit_included_output_set
        original_move = _included_mutations.move_exact_included_file
        cancellation_injected = False

        def commit_with_readonly_stage(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            return original_commit(
                project_path,
                self._transaction_with_native_windows_readonly_staged_root(
                    transaction
                ),
                conversion_running,
            )

        def publish_registry_then_cancel(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
            windows_source_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
            windows_destination_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
        ) -> None:
            nonlocal cancellation_injected
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
                windows_source_parent_binding=windows_source_parent_binding,
                windows_destination_parent_binding=(
                    windows_destination_parent_binding
                ),
            )
            if destination == final_registry_path and not cancellation_injected:
                cancellation_injected = True
                self.running.clear()

        with (
            patch.object(
                _included_publisher,
                'commit_included_output_set',
                side_effect=commit_with_readonly_stage,
            ),
            patch.object(
                _included_mutations,
                'move_exact_included_file',
                side_effect=publish_registry_then_cancel,
            ),
        ):
            converter.convert_all()

        self.assertTrue(cancellation_injected)
        self.assertTrue(converter.conversion_step_result().cancelled)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_managed_root_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("payload.txt", "stable payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        root_path = os.path.join(self.godot_dir, "included_files")
        parked_root = os.path.join(self.godot_dir, ".native-parked-root")
        target_path = self._make_native_windows_junction_target(
            "managed-root"
        )
        os.rename(root_path, parked_root)
        try:
            self._make_native_windows_junction(root_path, target_path)
            with self.assertRaisesRegex(OSError, "redirected"):
                converter.convert_all()
            self.assertTrue(os.path.isjunction(root_path))
            self._assert_native_windows_junction_sentinel(target_path)
        finally:
            self._remove_native_windows_junction(root_path)
            if os.path.isdir(parked_root):
                os.rename(parked_root, root_path)

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_nested_tree_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("nested/payload.txt", "stable payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        nested_path = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        parked_nested = os.path.join(self.godot_dir, ".native-parked-nested")
        target_path = self._make_native_windows_junction_target("nested-tree")
        os.rename(nested_path, parked_nested)
        try:
            self._make_native_windows_junction(nested_path, target_path)
            with self.assertRaisesRegex(OSError, "redirected"):
                converter.convert_all()
            self.assertTrue(os.path.isjunction(nested_path))
            self._assert_native_windows_junction_sentinel(target_path)
        finally:
            self._remove_native_windows_junction(nested_path)
            if os.path.isdir(parked_nested):
                os.rename(parked_nested, nested_path)

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_registry_directory_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("payload.txt", "stable payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        parked_registry = os.path.join(
            self.godot_dir,
            ".native-parked-registry",
        )
        target_path = self._make_native_windows_junction_target(
            "registry-directory"
        )
        os.rename(registry_directory, parked_registry)
        try:
            self._make_native_windows_junction(
                registry_directory,
                target_path,
            )
            with self.assertRaisesRegex(OSError, "redirected"):
                converter.convert_all()
            self.assertTrue(os.path.isjunction(registry_directory))
            self._assert_native_windows_junction_sentinel(target_path)
        finally:
            self._remove_native_windows_junction(registry_directory)
            if os.path.isdir(parked_registry):
                os.rename(parked_registry, registry_directory)

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_backup_destination_junction_is_preserved(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new payload")
        final_root_path = os.path.join(self.godot_dir, "included_files")
        target_path = self._make_native_windows_junction_target(
            "backup-destination"
        )
        backup_junction: str | None = None

        def inject_backup_junction(source: str, destination: str) -> None:
            nonlocal backup_junction
            if (
                backup_junction is None
                and source == final_root_path
                and os.path.basename(destination).startswith(
                    ".included_files."
                )
                and destination.endswith(".backup")
            ):
                self._make_native_windows_junction(destination, target_path)
                backup_junction = destination

        try:
            with (
                patch.object(
                    _included_mutations,
                    'before_included_transaction_rename_fallback',
                    side_effect=inject_backup_junction,
                ),
                self.assertRaises(OSError),
            ):
                converter.convert_all()
            self.assertIsNotNone(backup_junction)
            self.assertTrue(os.path.isjunction(backup_junction or ""))
            self._assert_native_windows_junction_sentinel(target_path)
            self.assertEqual(self._pair_snapshot(), previous_pair)
        finally:
            if backup_junction is not None:
                self._remove_native_windows_junction(backup_junction)

        self._assert_no_transaction_debris()


if __name__ == "__main__":
    unittest.main()
