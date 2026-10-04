# pyright: reportPrivateUsage=false

import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from typing import BinaryIO, Callable
from unittest.mock import patch

if (PROJECT_ROOT := os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion import included_files as included_files_module
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.included_file_registry import INCLUDED_FILE_REGISTRY_RELATIVE_PATH
from src.conversion.included_files_parts import (
    file_publication as _included_file_publication,
    generation_matching as _included_generation_matching,
    guarded_mutations as _included_mutations,
    native_posix as _included_posix,
    publisher as _included_publisher,
    source_snapshots as _included_snapshots,
    staging as _included_staging,
)
from tests import included_files_support as _included_support


class TestIncludedFilesManagedRootTransaction(_included_support.IncludedManagedRootFixture):
    def test_unchanged_generation_preserves_public_identity_without_writes(
        self,
    ) -> None:
        self._write("nested/payload.txt", "stable payload")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
            "payload.txt",
        )
        previous_output_identity = os.lstat(output_path).st_ino

        with (
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("unchanged conversion staged output"),
            ) as create_stage,
            patch.object(os, "fsync") as fsync,
            patch.object(os, "replace") as replace,
        ):
            converter.convert_all()

        create_stage.assert_not_called()
        fsync.assert_not_called()
        replace.assert_not_called()
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(os.lstat(output_path).st_ino, previous_output_identity)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                completed=1,
            ),
        )
        self._assert_no_transaction_debris()

    def test_64_mib_generation_has_bounded_initial_unchanged_and_changed_reads(
        self,
    ) -> None:
        payload_size = 64 * 1024 * 1024
        source_path = os.path.join(self.datafiles_dir, "large.bin")
        with open(source_path, "wb") as source_file:
            source_file.truncate(payload_size)
        converter = self._converter(max_workers=1)
        original_payload_read = (
            _included_file_publication.read_included_payload_chunk
        )
        original_validation_read = (
            _included_snapshots.read_included_validation_chunk
        )
        read_bytes = 0

        def count_payload_read(source_file: BinaryIO) -> bytes:
            nonlocal read_bytes
            chunk = original_payload_read(source_file)
            if os.fstat(source_file.fileno()).st_size == payload_size:
                read_bytes += len(chunk)
            return chunk

        def count_validation_read(source_file: BinaryIO) -> bytes:
            nonlocal read_bytes
            chunk = original_validation_read(source_file)
            if os.fstat(source_file.fileno()).st_size == payload_size:
                read_bytes += len(chunk)
            return chunk

        with (
            patch.object(
                _included_file_publication,
                'read_included_payload_chunk',
                side_effect=count_payload_read,
            ),
            patch.object(
                _included_snapshots,
                'read_included_validation_chunk',
                side_effect=count_validation_read,
            ),
        ):
            converter.convert_all()
        self.assertEqual(read_bytes, 5 * payload_size)

        read_bytes = 0
        with (
            patch.object(
                _included_file_publication,
                'read_included_payload_chunk',
                side_effect=count_payload_read,
            ),
            patch.object(
                _included_snapshots,
                'read_included_validation_chunk',
                side_effect=count_validation_read,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("unchanged conversion staged output"),
            ),
        ):
            converter.convert_all()
        self.assertEqual(read_bytes, 4 * payload_size)

        with open(source_path, "r+b", buffering=0) as source_file:
            source_file.write(b"\x01")
            os.fsync(source_file.fileno())
        read_bytes = 0
        with (
            patch.object(
                _included_file_publication,
                'read_included_payload_chunk',
                side_effect=count_payload_read,
            ),
            patch.object(
                _included_snapshots,
                'read_included_validation_chunk',
                side_effect=count_validation_read,
            ),
        ):
            converter.convert_all()
        self.assertLessEqual(read_bytes, 8 * payload_size)
        self._assert_no_transaction_debris()

    def test_changed_generation_receipts_are_boundary_bound(self) -> None:
        self._write("payload.txt", "BEFORE")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "AFTER!")
        captured_transactions: list[
            included_files_module._IncludedOutputSetTransaction
        ] = []

        def capture_transaction(
            _project_path: str,
            transaction: (
                included_files_module._IncludedOutputSetTransaction
            ),
            _conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            captured_transactions.append(transaction)
            raise OSError("captured generation receipts")

        with (
            patch.object(
                _included_publisher,
                'commit_included_output_set',
                side_effect=capture_transaction,
            ),
            self.assertRaisesRegex(
                OSError,
                "captured generation receipts",
            ),
        ):
            converter.convert_all()

        self.assertEqual(len(captured_transactions), 1)
        transaction = captured_transactions[0]
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(len(transaction.content_receipts), 1)
        transaction_id = transaction.publication_transaction_id
        generation_identity = transaction.staged_root_snapshot.identity
        self.assertIsNotNone(transaction_id)
        self.assertIsNotNone(generation_identity)
        if transaction_id is None or generation_identity is None:
            self.fail("changed-generation receipts lost their boundaries")
        receipt = transaction.content_receipts[0]
        captured_snapshot = (
            _included_snapshots.capture_included_tree_from_generation_receipts(
                transaction.staged_root_path,
                expected_parent_identity=(
                    transaction.stage_container_identity
                ),
                transaction_id=transaction_id,
                generation_identity=generation_identity,
                stage_container_identity=(
                    transaction.stage_container_identity
                ),
                receipts=transaction.content_receipts,
            )
        )
        self.assertEqual(
            captured_snapshot,
            transaction.staged_root_snapshot,
        )

        source_handle_state = receipt.source.binding.handle_state
        output_fingerprint = receipt.output.output_fingerprint
        output_handle_state = receipt.output.output_handle_state
        forged_receipts = {
            "transaction": replace(
                receipt,
                transaction_id="0" * 32,
            ),
            "generation": replace(
                receipt,
                generation_identity=(
                    generation_identity[0],
                    generation_identity[1] + 1,
                ),
            ),
            "assigned path": replace(
                receipt,
                source=replace(
                    receipt.source,
                    assigned_path="other.bin",
                ),
            ),
            "source identity": replace(
                receipt,
                source=replace(
                    receipt.source,
                    binding=replace(
                        receipt.source.binding,
                        handle_state=(
                            source_handle_state[0],
                            source_handle_state[1] + 1,
                            *source_handle_state[2:],
                        ),
                    ),
                ),
            ),
            "staged output identity": replace(
                receipt,
                output=replace(
                    receipt.output,
                    output_fingerprint=(
                        output_fingerprint[0],
                        output_fingerprint[1] + 1,
                        *output_fingerprint[2:],
                    ),
                    output_handle_state=(
                        output_handle_state[0],
                        output_handle_state[1] + 1,
                        *output_handle_state[2:],
                    ),
                ),
            ),
            "public output identity": replace(
                receipt,
                public_output_path=receipt.public_output_path + ".other",
            ),
            "stage container": replace(
                receipt,
                stage_container_identity=(
                    transaction.stage_container_identity[0],
                    transaction.stage_container_identity[1] + 1,
                ),
            ),
        }
        for boundary, forged_receipt in forged_receipts.items():
            with (
                self.subTest(boundary=boundary),
                self.assertRaisesRegex(
                    OSError,
                    "generation.*receipt|receipt.*binding",
                ),
            ):
                _included_snapshots.capture_included_tree_from_generation_receipts(
                    transaction.staged_root_path,
                    expected_parent_identity=(
                        transaction.stage_container_identity
                    ),
                    transaction_id=transaction_id,
                    generation_identity=generation_identity,
                    stage_container_identity=(
                        transaction.stage_container_identity
                    ),
                    receipts=(forged_receipt,),
                )
        _included_mutations.remove_owned_included_tree(
            transaction.stage_container_path,
            transaction.stage_container_identity,
            expected_parent_identity=transaction.project_identity,
        )
        self._assert_no_transaction_debris()

    def test_final_source_receipt_failure_restores_previous_generation(
        self,
    ) -> None:
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "CHANGED!")
        source_path = os.path.join(
            self.datafiles_dir,
            "payload.txt",
        )
        source_stat = os.stat(source_path)
        mutated = False

        def mutate_source() -> None:
            nonlocal mutated
            with open(source_path, "r+b", buffering=0) as source_file:
                source_file.write(b"MUTATED!")
                os.fsync(source_file.fileno())
            os.utime(
                source_path,
                ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
            )
            mutated = True

        with (
            patch.object(
                _included_publisher,
                'before_included_changed_generation_final_validation',
                side_effect=mutate_source,
            ),
            self.assertRaisesRegex(OSError, "source receipt"),
        ):
            converter.convert_all()

        self.assertTrue(mutated)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    def test_hardlinked_public_payload_is_republished_normally(self) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        external_path = os.path.join(self.godot_dir, "external-hardlink.txt")
        with open(external_path, "w", encoding="utf-8") as external_file:
            external_file.write("stable")
        os.unlink(output_path)
        try:
            os.link(external_path, output_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Hard links are unavailable: {error}")
        self.assertEqual(os.lstat(output_path).st_nlink, 2)
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
        self.assertEqual(os.lstat(output_path).st_nlink, 1)
        with open(external_path, "r", encoding="utf-8") as external_file:
            self.assertEqual(external_file.read(), "stable")
        self._assert_no_transaction_debris()

    def test_source_mutation_between_noop_receipts_fails_closed(self) -> None:
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        source_path = os.path.join(self.datafiles_dir, "payload.txt")
        source_stat = os.stat(source_path)

        def mutate_source() -> None:
            with open(source_path, "r+b", buffering=0) as source_file:
                source_file.write(b"MUTATED!")
                os.fsync(source_file.fileno())
            os.utime(
                source_path,
                ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
            )

        with (
            patch.object(
                _included_generation_matching,
                'before_included_unchanged_source_revalidation',
                side_effect=mutate_source,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("mutated no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "sources changed"),
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

    def test_source_directory_swap_with_same_inode_fails_closed(self) -> None:
        self._write("nested/payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        source_directory = os.path.join(self.datafiles_dir, "nested")
        moved_directory = os.path.join(self.datafiles_dir, "nested-original")

        def swap_source_directory() -> None:
            os.rename(source_directory, moved_directory)
            os.mkdir(source_directory)
            os.link(
                os.path.join(moved_directory, "payload.txt"),
                os.path.join(source_directory, "payload.txt"),
            )

        with (
            patch.object(
                _included_generation_matching,
                'before_included_unchanged_source_revalidation',
                side_effect=swap_source_directory,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("swapped no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "sources changed"),
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            os.stat(
                os.path.join(source_directory, "payload.txt")
            ).st_ino,
            os.stat(
                os.path.join(moved_directory, "payload.txt")
            ).st_ino,
        )
        self._assert_no_transaction_debris()

    def test_public_root_symlink_swap_during_noop_is_preserved_and_rejected(
        self,
    ) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        root_path = os.path.join(self.godot_dir, "included_files")
        moved_root = os.path.join(self.godot_dir, "preserved-root")
        replacement_root = tempfile.mkdtemp()
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_identity = os.lstat(registry_path).st_ino
        with open(
            os.path.join(replacement_root, "payload.txt"),
            "wb",
        ) as replacement_file:
            replacement_file.write(b"replacement")

        def swap_public_root() -> None:
            os.rename(root_path, moved_root)
            try:
                os.symlink(replacement_root, root_path)
            except (NotImplementedError, OSError) as error:
                os.rename(moved_root, root_path)
                self.skipTest(f"Symbolic links are unavailable: {error}")

        try:
            with (
                patch.object(
                    _included_generation_matching,
                    'before_included_unchanged_public_revalidation',
                    side_effect=swap_public_root,
                ),
                patch.object(
                    _included_staging,
                    'create_included_output_stage',
                    side_effect=AssertionError(
                        "swapped no-op candidate staged output"
                    ),
                ),
                self.assertRaisesRegex(OSError, "redirected|changed"),
            ):
                converter.convert_all()

            self.assertTrue(os.path.islink(root_path))
            with open(
                os.path.join(moved_root, "payload.txt"),
                "rb",
            ) as preserved_file:
                self.assertEqual(preserved_file.read(), b"stable")
            with open(
                os.path.join(root_path, "payload.txt"),
                "rb",
            ) as replacement_file:
                self.assertEqual(replacement_file.read(), b"replacement")
            self.assertEqual(os.lstat(registry_path).st_ino, registry_identity)
            self._assert_no_transaction_debris()
        finally:
            shutil.rmtree(replacement_root)

    def test_registry_mutation_during_noop_is_rejected_without_staging(
        self,
    ) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        root_identity, root_files, registry_identity, registry_content = (
            self._pair_snapshot()
        )
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )

        def mutate_registry() -> None:
            with open(registry_path, "ab") as registry_file:
                registry_file.write(b"# concurrent mutation\n")
                registry_file.flush()
                os.fsync(registry_file.fileno())

        with (
            patch.object(
                _included_generation_matching,
                'before_included_unchanged_public_revalidation',
                side_effect=mutate_registry,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("mutated no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "registry changed"),
        ):
            converter.convert_all()

        current_pair = self._pair_snapshot()
        self.assertEqual(current_pair[0], root_identity)
        self.assertEqual(current_pair[1], root_files)
        self.assertEqual(current_pair[2], registry_identity)
        self.assertEqual(
            current_pair[3],
            registry_content + b"# concurrent mutation\n",
        )
        self._assert_no_transaction_debris()

    def test_unchanged_generation_uses_the_pinned_fallback_verifier(self) -> None:
        self._write("nested/payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("fallback no-op staged output"),
            ),
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    def test_unchanged_contained_source_symlink_keeps_copy_semantics(self) -> None:
        target_path = os.path.join(self.datafiles_dir, "target.txt")
        with open(target_path, "w", encoding="utf-8") as source_file:
            source_file.write("contained target")
        alias_path = os.path.join(self.datafiles_dir, "alias.txt")
        try:
            os.symlink(target_path, alias_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        converter = self._converter(max_workers=2)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        with patch.object(
            _included_staging,
            'create_included_output_stage',
            side_effect=AssertionError("symlink no-op candidate staged output"),
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            previous_pair[1],
            {
                "alias.txt": b"contained target",
                "target.txt": b"contained target",
            },
        )
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_noop_hashes_deny_concurrent_writes(self) -> None:
        self._write("payload.txt", "stable payload")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        source_path = os.path.join(self.datafiles_dir, "payload.txt")
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        original_read = _included_snapshots.read_included_validation_chunk
        blocked_paths: set[str] = set()

        def observe_write_sharing(opened_file: BinaryIO) -> bytes:
            for path in (source_path, output_path):
                try:
                    with open(path, "r+b"):
                        pass
                except PermissionError:
                    blocked_paths.add(path)
            return original_read(opened_file)

        with patch.object(
            _included_snapshots,
            'read_included_validation_chunk',
            side_effect=observe_write_sharing,
        ):
            converter.convert_all()

        self.assertEqual(blocked_paths, {source_path, output_path})


if __name__ == "__main__":
    unittest.main()
