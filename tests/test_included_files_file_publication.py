# pyright: reportPrivateUsage=false

import os
import stat
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.included_files_parts import native_posix as _included_posix, constants as _included_constants, stat_metadata as _included_metadata
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import ConversionDiagnostic, DiagnosticCollector
from src.conversion.included_files_parts import file_publication as _included_file_publication
from src.conversion.included_files_parts import locking as _included_locking
from tests import included_files_support as _included_support
_included_files_transaction_debris = _included_support.included_files_transaction_debris


class TestIncludedFilesConverterOutputContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(self.datafiles_dir)
        self.source_path = os.path.join(self.datafiles_dir, "payload.bin")
        self.payload = b"\x00included\xffpayload"
        with open(self.source_path, "wb") as source_file:
            source_file.write(self.payload)
        os.chmod(self.source_path, 0o640)
        os.utime(
            self.source_path,
            ns=(1_700_000_000_123_456_789, 1_700_000_001_987_654_321),
        )
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _convert(
        self,
        *,
        force_fallback: bool = False,
        expect_failure: bool = False,
    ) -> tuple[IncludedFilesConverter, DiagnosticCollector]:
        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        def convert() -> None:
            if force_fallback:
                with patch.object(
                    _included_posix,
                    'confined_included_output_supported',
                    return_value=False,
                ):
                    converter.convert_all()
            else:
                converter.convert_all()

        if expect_failure:
            with self.assertRaises(OSError):
                convert()
        else:
            convert()
        return converter, diagnostics

    @staticmethod
    def _output_rejections(
        diagnostics: DiagnosticCollector,
    ) -> list[ConversionDiagnostic]:
        return [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-INCLUDED-FILE-OUTPUT-REJECTED"
        ]

    def _make_symlink(self, target: str, link_path: str) -> None:
        try:
            os.symlink(target, link_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

    def _assert_persistent_project_lock(self, project_path: str) -> str:
        lock_path = os.path.join(
            project_path,
            _included_constants.INCLUDED_FILES_LOCK_NAME,
        )
        self.assertTrue(os.path.isfile(lock_path))
        self.assertFalse(os.path.islink(lock_path))
        with open(lock_path, "rb") as lock_file:
            self.assertEqual(
                lock_file.read(),
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
            )
        return lock_path

    def _assert_no_project_transaction_debris(
        self,
        project_path: str,
    ) -> None:
        self._assert_persistent_project_lock(project_path)
        self.assertEqual(
            _included_files_transaction_debris(project_path),
            (),
        )

    def _assert_failed_output(
        self,
        converter: IncludedFilesConverter,
        diagnostics: DiagnosticCollector,
        *,
        requested: int = 1,
        completed: int = 0,
        rejection_count: int | None = None,
    ) -> None:
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=requested,
                executed=requested,
                completed=completed,
                failed=requested - completed,
            ),
        )
        rejections = self._output_rejections(diagnostics)
        expected_rejections = (
            requested - completed
            if rejection_count is None
            else rejection_count
        )
        self.assertEqual(len(rejections), expected_rejections, rejections)
        self.assertTrue(
            all(
                diagnostic.severity == "error"
                and diagnostic.resource_type == "included_file"
                and diagnostic.manifest_entry
                == "generated Included File output"
                for diagnostic in rejections
            ),
            rejections,
        )

    def test_normal_copy_preserves_binary_bytes_and_metadata(self) -> None:
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.bin",
        )
        source_stat = os.stat(self.source_path)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                )

                with open(output_path, "rb") as output_file:
                    self.assertEqual(output_file.read(), self.payload)
                output_stat = os.stat(output_path)
                if os.chmod in os.supports_fd:
                    self.assertEqual(
                        stat.S_IMODE(output_stat.st_mode),
                        stat.S_IMODE(source_stat.st_mode),
                    )
                if os.utime in os.supports_fd:
                    self.assertEqual(
                        output_stat.st_mtime_ns,
                        source_stat.st_mtime_ns,
                    )
                self.assertEqual(
                    converter.conversion_step_result(
                        finalize_unfinished_as=None,
                    ).resources,
                    ConversionCounts(requested=1, executed=1, completed=1),
                )
                self.assertEqual(self._output_rejections(diagnostics), [])

    def test_rejects_redirected_included_files_root(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        self._make_symlink(self.outside_dir, managed_root)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                    expect_failure=True,
                )

                self.assertTrue(os.path.islink(managed_root))
                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                self._assert_failed_output(converter, diagnostics)

    def test_rejects_redirected_nested_output_directory(self) -> None:
        nested_source_dir = os.path.join(self.datafiles_dir, "Nested")
        os.makedirs(nested_source_dir)
        with open(
            os.path.join(nested_source_dir, "child.bin"),
            "wb",
        ) as source_file:
            source_file.write(b"nested payload")
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        nested_output = os.path.join(managed_root, "nested")
        outside_output = os.path.join(self.outside_dir, "child.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        self._make_symlink(self.outside_dir, nested_output)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                    expect_failure=True,
                )

                self.assertTrue(os.path.islink(nested_output))
                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                self._assert_failed_output(
                    converter,
                    diagnostics,
                    requested=2,
                )

    def test_rejects_final_output_symlink(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        self._make_symlink(outside_output, output_path)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                    expect_failure=True,
                )

                self.assertTrue(os.path.islink(output_path))
                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                self._assert_failed_output(converter, diagnostics)

    def test_replaces_final_hardlink_without_mutating_referent(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                if os.path.lexists(output_path):
                    os.unlink(output_path)
                try:
                    os.link(outside_output, output_path)
                except (NotImplementedError, OSError) as error:
                    self.skipTest(f"Hard links are unavailable: {error}")

                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                )

                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                with open(output_path, "rb") as output_file:
                    self.assertEqual(output_file.read(), self.payload)
                self.assertNotEqual(
                    os.stat(outside_output).st_ino,
                    os.stat(output_path).st_ino,
                )
                self.assertEqual(
                    converter.conversion_step_result(
                        finalize_unfinished_as=None,
                    ).resources,
                    ConversionCounts(requested=1, executed=1, completed=1),
                )
                self.assertEqual(self._output_rejections(diagnostics), [])

    def test_late_final_output_swap_is_rejected_without_external_mutation(
        self,
    ) -> None:
        if not _included_posix.confined_included_output_supported():
            self.skipTest("Descriptor-relative Included File output is unavailable")
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        with open(output_path, "wb") as output_file:
            output_file.write(b"previous output")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        original_verify = _included_metadata.verify_included_output_state_at
        swapped = False

        def swap_then_verify(
            directory_fd: int,
            filename: str,
            expected_identity: tuple[int, int] | None,
        ) -> None:
            nonlocal swapped
            if not swapped:
                os.unlink(output_path)
                self._make_symlink(outside_output, output_path)
                swapped = True
            original_verify(directory_fd, filename, expected_identity)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with patch.object(
            _included_metadata,
            'verify_included_output_state_at',
            side_effect=swap_then_verify,
        ), self.assertRaises(OSError):
            converter.convert_all()

        self.assertTrue(os.path.islink(output_path))
        with open(outside_output, "rb") as outside_file:
            self.assertEqual(outside_file.read(), b"outside sentinel")
        self.assertFalse(
            any(name.startswith(".gm2godot-") for name in os.listdir(managed_root))
        )
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_late_output_directory_relocation_is_rejected_before_publish(
        self,
    ) -> None:
        if not _included_posix.confined_included_output_supported():
            self.skipTest("Descriptor-relative Included File output is unavailable")
        os.unlink(self.source_path)
        nested_source = os.path.join(
            self.datafiles_dir,
            "Nested",
            "payload.bin",
        )
        os.makedirs(os.path.dirname(nested_source))
        with open(nested_source, "wb") as source_file:
            source_file.write(self.payload)
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        os.makedirs(nested_output)
        moved_directory = os.path.join(self.outside_dir, "moved_nested")
        original_verify = (
            _included_file_publication.verify_open_included_output_directory
        )
        nested_verifications = 0

        def relocate_then_verify(
            project_path: str,
            directory_path: str,
            directory_fd: int,
        ) -> None:
            nonlocal nested_verifications
            if os.path.normcase(directory_path).endswith(
                os.path.normcase(os.path.join("included_files", "nested"))
            ):
                nested_verifications += 1
                if nested_verifications == 3:
                    os.rename(nested_output, moved_directory)
            original_verify(project_path, directory_path, directory_fd)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with patch.object(
            _included_file_publication,
            'verify_open_included_output_directory',
            side_effect=relocate_then_verify,
        ), self.assertRaises(OSError):
            converter.convert_all()

        self.assertTrue(os.path.isdir(moved_directory))
        self.assertEqual(os.listdir(moved_directory), [])
        self._assert_no_project_transaction_debris(self.godot_dir)
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_final_rename_cannot_follow_swapped_output_directory(self) -> None:
        if not _included_posix.confined_included_output_supported():
            self.skipTest("Descriptor-relative Included File output is unavailable")
        os.unlink(self.source_path)
        nested_source = os.path.join(
            self.datafiles_dir,
            "Nested",
            "payload.bin",
        )
        os.makedirs(os.path.dirname(nested_source))
        with open(nested_source, "wb") as source_file:
            source_file.write(self.payload)
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        os.makedirs(nested_output)
        moved_directory = os.path.join(
            self.godot_dir,
            ".moved_nested",
        )
        redirected_directory = os.path.join(
            self.outside_dir,
            "redirected_nested",
        )
        os.makedirs(redirected_directory)
        outside_output = os.path.join(
            redirected_directory,
            "payload.bin",
        )
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        original_rename = os.rename
        swapped = False
        publication_dir_fds: tuple[int, int] | None = None

        def relocate_before_publish(
            source: str,
            destination: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            nonlocal publication_dir_fds, swapped
            if (
                not swapped
                and src_dir_fd is not None
                and dst_dir_fd is not None
                and source.startswith(".gm2godot-")
            ):
                original_rename(nested_output, moved_directory)
                self._make_symlink(
                    redirected_directory,
                    nested_output,
                )
                publication_dir_fds = (src_dir_fd, dst_dir_fd)
                swapped = True
            original_rename(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with (
            patch.object(
                _included_posix,
                'confined_included_output_supported',
                return_value=True,
            ),
            patch.object(
                os,
                "rename",
                side_effect=relocate_before_publish,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertTrue(swapped)
        self.assertIsNotNone(publication_dir_fds)
        if publication_dir_fds is not None:
            self.assertEqual(
                publication_dir_fds[0],
                publication_dir_fds[1],
            )
        self.assertTrue(os.path.islink(nested_output))
        with open(outside_output, "rb") as outside_file:
            self.assertEqual(outside_file.read(), b"outside sentinel")
        self.assertEqual(os.listdir(moved_directory), [])
        self._assert_no_project_transaction_debris(self.godot_dir)
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_fallback_late_final_swap_is_rejected_without_external_mutation(
        self,
    ) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        with open(output_path, "wb") as output_file:
            output_file.write(b"previous output")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        original_verify = _included_metadata.verify_included_output_state
        swapped = False

        def swap_then_verify(
            path: str,
            expected_identity: tuple[int, int] | None,
        ) -> None:
            nonlocal swapped
            if not swapped:
                os.unlink(output_path)
                self._make_symlink(outside_output, output_path)
                swapped = True
            original_verify(path, expected_identity)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with (
            patch.object(
                _included_posix,
                'confined_included_output_supported',
                return_value=False,
            ),
            patch.object(
                _included_metadata,
                'verify_included_output_state',
                side_effect=swap_then_verify,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertTrue(os.path.islink(output_path))
        with open(outside_output, "rb") as outside_file:
            self.assertEqual(outside_file.read(), b"outside sentinel")
        self.assertFalse(
            any(name.startswith(".gm2godot-") for name in os.listdir(managed_root))
        )
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_fallback_late_directory_relocation_cleans_project_stage(
        self,
    ) -> None:
        os.unlink(self.source_path)
        nested_source = os.path.join(
            self.datafiles_dir,
            "Nested",
            "payload.bin",
        )
        os.makedirs(os.path.dirname(nested_source))
        with open(nested_source, "wb") as source_file:
            source_file.write(self.payload)
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        os.makedirs(nested_output)
        moved_directory = os.path.join(self.outside_dir, "moved_nested")
        original_verify = (
            _included_file_publication.verify_included_output_directories_fallback
        )
        moved = False

        def relocate_then_verify(
            identities: tuple[tuple[str, tuple[int, int]], ...],
        ) -> None:
            nonlocal moved
            if not moved and len(identities) > 1:
                os.rename(nested_output, moved_directory)
                moved = True
            original_verify(identities)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with (
            patch.object(
                _included_posix,
                'confined_included_output_supported',
                return_value=False,
            ),
            patch.object(
                _included_file_publication,
                'verify_included_output_directories_fallback',
                side_effect=relocate_then_verify,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertTrue(os.path.isdir(moved_directory))
        self.assertEqual(os.listdir(moved_directory), [])
        self._assert_no_project_transaction_debris(self.godot_dir)
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    @unittest.skipIf(
        os.name == "nt",
        "the persistent Windows project lock blocks root relocation",
    )
    def test_fallback_project_root_swap_cleans_external_stage_before_copy(
        self,
    ) -> None:
        moved_project = os.path.join(
            self.outside_dir,
            "moved_project",
        )
        original_mkstemp = tempfile.mkstemp
        original_rename = os.rename
        swapped = False

        def relocate_before_stage(
            suffix: str | None = None,
            prefix: str | None = None,
            dir: str | None = None,
            text: bool = False,
        ) -> tuple[int, str]:
            nonlocal swapped
            original_rename(self.godot_dir, moved_project)
            try:
                self._make_symlink(self.outside_dir, self.godot_dir)
            except BaseException:
                original_rename(moved_project, self.godot_dir)
                raise
            swapped = True
            return original_mkstemp(
                suffix=suffix,
                prefix=prefix,
                dir=dir,
                text=text,
            )

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        try:
            with (
                patch.object(
                    _included_posix,
                    'confined_included_output_supported',
                    return_value=False,
                ),
                patch.object(
                    _included_file_publication.tempfile,
                    "mkstemp",
                    side_effect=relocate_before_stage,
                ),
                self.assertRaises(OSError),
            ):
                converter.convert_all()

            outside_files = [
                os.path.join(directory, filename)
                for directory, _subdirectories, filenames in os.walk(
                    self.outside_dir
                )
                for filename in filenames
            ]
            self.assertTrue(swapped)
            lock_path = self._assert_persistent_project_lock(moved_project)
            non_lock_outside_files = [
                path for path in outside_files if path != lock_path
            ]
            self.assertEqual(len(non_lock_outside_files), 1)
            self.assertTrue(
                non_lock_outside_files[0].startswith(moved_project + os.sep)
            )
            self.assertEqual(
                os.path.basename(non_lock_outside_files[0]),
                _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME,
            )
            self._assert_failed_output(converter, diagnostics)
        finally:
            if os.path.islink(self.godot_dir):
                os.unlink(self.godot_dir)
            if os.path.isdir(moved_project):
                original_rename(moved_project, self.godot_dir)

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_project_lock_blocks_root_relocation(self) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        moved_project = os.path.join(self.outside_dir, "moved_project")
        project_lock = _included_locking.acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            with self.assertRaises(OSError):
                os.rename(self.godot_dir, moved_project)
        finally:
            _included_locking.release_included_project_lock(project_lock)
            if not os.path.lexists(self.godot_dir) and os.path.isdir(moved_project):
                os.rename(moved_project, self.godot_dir)

        self.assertTrue(os.path.isdir(self.godot_dir))
        self.assertFalse(os.path.lexists(moved_project))
        self._assert_no_project_transaction_debris(self.godot_dir)

    def test_fallback_rejects_mocked_windows_junction(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        normalized_managed_root = os.path.normcase(os.path.abspath(managed_root))

        def is_mock_junction(path: str) -> bool:
            return (
                os.path.normcase(os.path.abspath(path))
                == normalized_managed_root
            )

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
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
        _included_locking.release_included_project_lock(project_lock)
        with (
            patch.object(
                _included_posix,
                'confined_included_output_supported',
                return_value=False,
            ),
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(
                os.path,
                "isjunction",
                side_effect=is_mock_junction,
                create=True,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertEqual(os.listdir(managed_root), [])
        self._assert_failed_output(converter, diagnostics)


if __name__ == "__main__":
    unittest.main()
