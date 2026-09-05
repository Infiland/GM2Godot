"""The recovery and output grammars are separate, host-aware boundaries."""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.conversion.included_files_parts.path_validation import (
    output_components,
    recovery_relative_path,
    recovery_tree_entry_path,
    windows_recovery_component_is_ambiguous,
)


class TestIncludedFilePathValidation(unittest.TestCase):
    def test_recovery_relative_path_keeps_lexical_grammar_and_error_text(self) -> None:
        values: tuple[object, ...] = (None, 1, [], "", ".", "..", "/a", "a//b", "a/./b", "a/../b", "a\0b", "a\\b")
        for value in values:
            with self.subTest(value=value), self.assertRaisesRegex(OSError, "^Invalid Included Files recovery tree path$"):
                recovery_relative_path(value)
        for value in ("a", "nested/é.txt", "..name"):
            self.assertEqual(recovery_relative_path(value), value)
        if os.name != "nt":
            for value in ("CON", "a:b", " space", "trailing."):
                self.assertEqual(recovery_relative_path(value), value)

    def test_windows_recovery_components_reject_device_and_reset_forms(self) -> None:
        for value in ("CON", "con.txt", "NUL .txt", "COM¹", "LPT².log", "CONIN$", "CONOUT$", "D:payload",
                      "a:b", " leading", "trailing ", "trailing.", "a\x1fb", "a<b", "a?b", 'a"b'):
            with self.subTest(value=value):
                self.assertTrue(windows_recovery_component_is_ambiguous(value))
                with patch("os.name", "nt"), self.assertRaisesRegex(
                    OSError, "^Windows-ambiguous Included Files recovery tree path$"
                ):
                    recovery_relative_path(f"nested/{value}")
        for value in ("console.txt", "COM0", "LPT10", "ordinary", "é.txt"):
            self.assertFalse(windows_recovery_component_is_ambiguous(value))

    def test_recovery_tree_entry_path_keeps_native_round_trip_containment(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(recovery_tree_entry_path(root, "nested/é.txt"), os.path.join(root, "nested", "é.txt"))
            for value in ("../outside", "/outside", "nested/../../outside"):
                with self.assertRaisesRegex(OSError, "^Invalid Included Files recovery tree path$"):
                    recovery_tree_entry_path(root, value)
            with patch("os.path.relpath", return_value="different"), self.assertRaisesRegex(
                OSError, "^Included Files recovery tree path escaped its recorded root$"
            ):
                recovery_tree_entry_path(root, "nested/file")
            with patch("os.path.commonpath", side_effect=ValueError("different root")), self.assertRaisesRegex(
                OSError, "^Included Files recovery tree path escaped its recorded root$"
            ):
                recovery_tree_entry_path(root, "nested/file")

    def test_output_components_requires_exact_managed_root(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(output_components(root, os.path.join(root, "included_files", "a", "b")),
                             ("included_files", "a", "b"))
            for relative in ("", "included_files", "Included_files/a", "elsewhere/a", "../outside"):
                value = os.path.join(root, relative)
                with self.subTest(relative=relative), self.assertRaises(ValueError) as error:
                    output_components(root, value)
                self.assertEqual(str(error.exception),
                                 f"Generated Included File output escapes its managed root: {value}")
