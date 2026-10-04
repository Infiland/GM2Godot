# pyright: reportPrivateUsage=false

import os
import sys
import shutil
import unittest
from typing import Callable
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.included_files_parts import phase_observer as _included_phases
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import native_posix as _included_posix, constants as _included_constants, path_validation as _included_paths
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.included_files_parts import file_publication as _included_file_publication
from src.conversion.included_files_parts import publisher as _included_publisher
from src.conversion.included_files_parts import staging as _included_staging
from tests import included_files_support as _included_support


class TestIncludedFilesManagedRootTransaction(_included_support.IncludedManagedRootFixture):
    def test_fallback_stage_name_matches_recovery_grammar(self) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(_included_posix, 'sync_included_directory'),
        ):
            stage_path, _stage_identity = (
                _included_staging.create_included_output_stage(
                    self.godot_dir,
                    project_identity,
                )
            )

        stage_name = os.path.basename(stage_path)
        self.assertEqual(
            _included_paths.included_recovery_managed_name(
                stage_name,
                prefix=_included_constants.INCLUDED_FILES_STAGE_PREFIX,
                suffix=".stage",
                label="stage container",
            ),
            stage_name,
        )

    def test_fallback_stage_allocation_preserves_colliding_file(self) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        first_token = "a" * 16
        second_token = "b" * 16
        colliding_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_STAGE_PREFIX
            + first_token
            + ".stage",
        )
        colliding_content = b"user-owned stage collision\n"
        with open(colliding_path, "wb") as colliding_file:
            colliding_file.write(colliding_content)
        colliding_stat = os.lstat(colliding_path)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(_included_posix, 'sync_included_directory'),
            patch.object(
                _included_staging.secrets,
                "token_hex",
                side_effect=[first_token, second_token],
            ) as token_hex,
        ):
            stage_path, _stage_identity = (
                _included_staging.create_included_output_stage(
                    self.godot_dir,
                    project_identity,
                )
            )

        self.assertEqual(
            os.path.basename(stage_path),
            _included_constants.INCLUDED_FILES_STAGE_PREFIX
            + second_token
            + ".stage",
        )
        self.assertEqual(token_hex.call_count, 2)
        current_colliding_stat = os.lstat(colliding_path)
        self.assertEqual(
            (current_colliding_stat.st_dev, current_colliding_stat.st_ino),
            (colliding_stat.st_dev, colliding_stat.st_ino),
        )
        with open(colliding_path, "rb") as colliding_file:
            self.assertEqual(colliding_file.read(), colliding_content)

    def test_fallback_stage_allocation_exhaustion_preserves_collision(
        self,
    ) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        colliding_token = "c" * 16
        colliding_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_STAGE_PREFIX
            + colliding_token
            + ".stage",
        )
        colliding_content = b"persistent user-owned stage collision\n"
        with open(colliding_path, "wb") as colliding_file:
            colliding_file.write(colliding_content)
        colliding_stat = os.lstat(colliding_path)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(
                _included_staging.secrets,
                "token_hex",
                return_value=colliding_token,
            ) as token_hex,
            self.assertRaisesRegex(
                OSError,
                "Could not allocate Included Files staging directory",
            ),
        ):
            _included_staging.create_included_output_stage(
                self.godot_dir,
                project_identity,
            )

        self.assertEqual(token_hex.call_count, 100)
        current_colliding_stat = os.lstat(colliding_path)
        self.assertEqual(
            (current_colliding_stat.st_dev, current_colliding_stat.st_ino),
            (colliding_stat.st_dev, colliding_stat.st_ino),
        )
        with open(colliding_path, "rb") as colliding_file:
            self.assertEqual(colliding_file.read(), colliding_content)

    def test_staged_tree_directories_sync_bottom_up_before_commit_record(
        self,
    ) -> None:
        self._write("level-one/level-two/payload.txt", "payload")
        events: list[tuple[str, str]] = []
        original_sync = _included_posix.sync_included_directory

        def trace_sync(path: str, expected_identity: tuple[int, int]) -> None:
            events.append(("sync", os.path.abspath(path)))
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
            self._converter(max_workers=1).convert_all()

        commit_record_index = events.index(("phase", "commit-record-staged"))
        root_path = os.path.join(self.godot_dir, "included_files")
        tree_syncs = [
            event
            for event in events[:commit_record_index]
            if event[0] == "sync"
            and (
                event[1] == root_path
                or event[1].startswith(root_path + os.sep)
            )
        ]
        self.assertEqual(
            tree_syncs,
            [
                (
                    "sync",
                    os.path.join(root_path, "level-one", "level-two"),
                ),
                ("sync", os.path.join(root_path, "level-one")),
                ("sync", root_path),
            ],
        )

    def test_created_registry_directory_swap_is_not_adopted(self) -> None:
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned registry creation is unavailable")
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        replacement_directory = os.path.join(
            self.godot_dir,
            "replacement-registry",
        )
        parked_directory = os.path.join(
            self.godot_dir,
            "parked-created-registry",
        )
        os.mkdir(replacement_directory)
        sentinel_path = os.path.join(replacement_directory, "sentinel.txt")
        with open(sentinel_path, "w", encoding="utf-8") as sentinel_file:
            sentinel_file.write("unknown registry directory")
        project_stat = os.lstat(self.godot_dir)
        empty_snapshot = included_files_module._IncludedRegistrySnapshot(
            directory_identity=None,
            file_identity=None,
            file_mode=None,
            content=None,
        )
        swapped = False

        def swap_created_registry(project_fd: int, name: str) -> None:
            nonlocal swapped
            if swapped:
                return
            os.rename(
                name,
                os.path.basename(parked_directory),
                src_dir_fd=project_fd,
                dst_dir_fd=project_fd,
            )
            os.rename(
                os.path.basename(replacement_directory),
                name,
                src_dir_fd=project_fd,
                dst_dir_fd=project_fd,
            )
            swapped = True

        with patch.object(
            _included_staging,
            'before_included_registry_directory_binding_check',
            side_effect=swap_created_registry,
        ), self.assertRaisesRegex(OSError, "changed after creation"):
            _included_staging.prepare_included_registry_directory(
                self.godot_dir,
                empty_snapshot,
                (project_stat.st_dev, project_stat.st_ino),
            )

        self.assertTrue(swapped)
        with open(
            os.path.join(registry_directory, "sentinel.txt"),
            encoding="utf-8",
        ) as sentinel_file:
            self.assertEqual(sentinel_file.read(), "unknown registry directory")
        self.assertEqual(os.listdir(parked_directory), [])

    def test_moved_and_symlinked_stage_container_is_rejected(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        moved_stage = os.path.join(self.gm_dir, "moved-stage")
        original_commit = _included_publisher.commit_included_output_set
        stage_link: str | None = None

        def redirect_stage_then_commit(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal stage_link
            os.rename(transaction.stage_container_path, moved_stage)
            try:
                os.symlink(moved_stage, transaction.stage_container_path)
            except (NotImplementedError, OSError) as error:
                os.rename(moved_stage, transaction.stage_container_path)
                self.skipTest(f"Symbolic links are unavailable: {error}")
            stage_link = transaction.stage_container_path
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        try:
            with patch.object(
                _included_publisher,
                'commit_included_output_set',
                side_effect=redirect_stage_then_commit,
            ), self.assertRaisesRegex(OSError, "redirected or non-directory"):
                converter.convert_all()

            self.assertIsNotNone(stage_link)
            self.assertEqual(self._pair_snapshot(), previous_pair)
            self.assertTrue(os.path.islink(stage_link or ""))
            self.assertTrue(os.path.isdir(moved_stage))
            self.assertEqual(
                converter.conversion_step_result(
                    finalize_unfinished_as=None,
                ).resources,
                ConversionCounts(requested=1, executed=1, failed=1),
            )
        finally:
            if stage_link is not None and os.path.islink(stage_link):
                os.unlink(stage_link)

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_stage_container_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new payload")
        original_commit = _included_publisher.commit_included_output_set
        parked_stage = os.path.join(self.gm_dir, "native-parked-stage")
        target_path = self._make_native_windows_junction_target(
            "stage-container"
        )
        stage_junction: str | None = None

        def replace_stage_with_junction(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal stage_junction
            os.rename(transaction.stage_container_path, parked_stage)
            self._make_native_windows_junction(
                transaction.stage_container_path,
                target_path,
            )
            stage_junction = transaction.stage_container_path
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        try:
            with (
                patch.object(
                    _included_publisher,
                    'commit_included_output_set',
                    side_effect=replace_stage_with_junction,
                ),
                self.assertRaisesRegex(OSError, "redirected"),
            ):
                converter.convert_all()
            self.assertIsNotNone(stage_junction)
            self.assertTrue(os.path.isjunction(stage_junction or ""))
            self._assert_native_windows_junction_sentinel(target_path)
            self.assertEqual(self._pair_snapshot(), previous_pair)
        finally:
            if stage_junction is not None:
                self._remove_native_windows_junction(stage_junction)
            if os.path.isdir(parked_stage):
                shutil.rmtree(
                    parked_stage,
                    onexc=self._retry_windows_read_only_cleanup,
                )

        self._assert_no_transaction_debris()


if __name__ == "__main__":
    unittest.main()
