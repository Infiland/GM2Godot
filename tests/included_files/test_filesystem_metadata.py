"""Native stat projections and explicitly modeled junction-facility policy."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.conversion.included_files_parts.filesystem_metadata import (
    handle_state,
    output_path_is_redirected,
    path_fingerprint,
    path_handle_binding,
    source_fingerprint,
)


class TestIncludedFilesFilesystemMetadata(unittest.TestCase):
    def test_stat_projections_preserve_exact_fields_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "payload")
            path.write_bytes(b"stat projection")
            os.utime(path, ns=(1_234_567_890_000_000_000, 1_345_678_901_000_000_000))
            with path.open("rb") as stream:
                states = (os.lstat(path), os.fstat(stream.fileno()))
                for state in states:
                    self.assertNotEqual(state.st_mtime_ns, state.st_ctime_ns)
                    self.assertEqual(path_fingerprint(state), (
                        state.st_dev, state.st_ino, state.st_mode, state.st_size, state.st_mtime_ns, state.st_nlink,
                    ))
                    self.assertEqual(path_handle_binding(state), (
                        state.st_dev, state.st_ino, stat.S_IFMT(state.st_mode), state.st_size,
                        state.st_mtime_ns, state.st_nlink,
                    ))
                    self.assertEqual(handle_state(state), (
                        state.st_dev, state.st_ino, state.st_mode, state.st_size,
                        state.st_mtime_ns, state.st_ctime_ns, state.st_nlink,
                    ))
                    self.assertEqual(source_fingerprint(state), (
                        state.st_dev, state.st_ino, state.st_mode, state.st_size, state.st_mtime_ns, state.st_ctime_ns,
                    ))

    def test_symlink_short_circuit_and_unavailable_junction_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "ordinary")
            path.write_bytes(b"ordinary")
            ordinary = os.lstat(path)
            # This declared mode is a metadata model, not a native symlink claim.
            declared_link = os.stat_result((stat.S_IFLNK | 0o777, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            with patch.object(os.path, "isjunction", create=True, side_effect=AssertionError("must short-circuit")) as checker:
                self.assertTrue(output_path_is_redirected(str(path), declared_link))
                checker.assert_not_called()
            for unavailable in (None, False):
                with self.subTest(unavailable=unavailable), patch.object(os.path, "isjunction", unavailable, create=True):
                    self.assertFalse(output_path_is_redirected(str(path), ordinary))
            path_text = str(path)
            # An empty declared API models the missing optional path facility.
            with patch.object(os, "path", Mock(spec=[])):
                self.assertFalse(output_path_is_redirected(path_text, ordinary))

    def test_junction_checker_result_and_error_are_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "ordinary")
            path.write_bytes(b"ordinary")
            state = os.lstat(path)
            for answer in (False, True):
                with self.subTest(answer=answer), patch.object(os.path, "isjunction", create=True, return_value=answer) as checker:
                    self.assertIs(output_path_is_redirected(str(path), state), answer)
                    checker.assert_called_once_with(str(path))
            failure = OSError("native junction facility failed")
            with patch.object(os.path, "isjunction", create=True, side_effect=failure) as checker:
                with self.assertRaises(OSError) as caught:
                    output_path_is_redirected(str(path), state)
                self.assertIs(caught.exception, failure)
                checker.assert_called_once_with(str(path))
