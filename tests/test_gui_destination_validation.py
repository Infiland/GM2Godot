# pyright: reportPrivateUsage=false
# ruff: noqa: E402

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.conversion.project_godot import ConversionPreflightError
from src.gui.main_window import MainWindow
from src.gui.panels.console_panel import ConsolePanel
from src.localization import get_localized, get_localized_list


class _MainWindowDestinationHarness:
    def __init__(self) -> None:
        self._console = ConsolePanel()

    def _godot_destination_error_message(
        self,
        error: ConversionPreflightError,
    ) -> str:
        return MainWindow._godot_destination_error_message(error)

    def _check_godot_destination(self, folder: str) -> None:
        MainWindow._check_godot_destination(cast(MainWindow, self), folder)


class MainWindowDestinationValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing_app = QApplication.instance()
        cls.app = existing_app if isinstance(existing_app, QApplication) else QApplication([])

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.gm_directory = self.root / "game-maker"
        self.gm_directory.mkdir()
        (self.gm_directory / "Demo.yyp").write_text(
            json.dumps({"%Name": "Demo"}),
            encoding="utf-8",
        )
        self.harness = _MainWindowDestinationHarness()
        self.window = cast(MainWindow, self.harness)

    def tearDown(self) -> None:
        self.harness._console.deleteLater()
        self._temporary_directory.cleanup()

    def test_empty_destination_is_accepted_without_creating_project_on_selection(self) -> None:
        destination = self.root / "empty-godot"
        destination.mkdir()

        with patch("src.gui.main_window.QMessageBox.warning") as warning:
            MainWindow._on_path_selected(
                self.window,
                "godot",
                os.fspath(destination),
            )

        warning.assert_not_called()
        self.assertIn(
            get_localized("Console_GodotDestinationEmpty"),
            self.harness._console._text_edit.toPlainText(),
        )
        self.assertFalse((destination / "project.godot").exists())
        self.assertTrue(
            MainWindow._validate_projects(
                self.window,
                os.fspath(self.gm_directory),
                os.fspath(destination),
            )
        )
        self.assertFalse((destination / "project.godot").exists())

    def test_existing_project_destination_is_accepted_and_preserved(self) -> None:
        destination = self.root / "existing-godot"
        destination.mkdir()
        project_file = destination / "project.godot"
        original = b'config_version=5\n\n[application]\nconfig/name="Existing"\n'
        project_file.write_bytes(original)

        with patch("src.gui.main_window.QMessageBox.warning") as warning:
            MainWindow._on_path_selected(
                self.window,
                "godot",
                os.fspath(destination),
            )

        warning.assert_not_called()
        expected_log = get_localized("Console_ProjectFound").format(
            file_name="Godot",
            files="project.godot",
        )
        self.assertIn(expected_log, self.harness._console._text_edit.toPlainText())
        self.assertTrue(
            MainWindow._validate_projects(
                self.window,
                os.fspath(self.gm_directory),
                os.fspath(destination),
            )
        )
        self.assertEqual(project_file.read_bytes(), original)

    def test_occupied_nonproject_destination_is_rejected_without_writes(self) -> None:
        destination = self.root / "occupied-godot"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_bytes(b"keep")
        invalid_project = get_localized_list("Console_Error_InvalidProject")
        expected_title = invalid_project[0].format(file_name="Godot")
        expected_message = get_localized("Console_Error_GodotDestinationOccupied")

        with patch("src.gui.main_window.QMessageBox.warning") as warning:
            MainWindow._on_path_selected(
                self.window,
                "godot",
                os.fspath(destination),
            )

        warning.assert_called_once_with(
            self.window,
            expected_title,
            expected_message,
        )
        self.harness._console.clear()
        self.assertFalse(
            MainWindow._validate_projects(
                self.window,
                os.fspath(self.gm_directory),
                os.fspath(destination),
            )
        )
        self.assertEqual(
            self.harness._console._text_edit.toPlainText(),
            expected_message,
        )
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertFalse((destination / "project.godot").exists())


if __name__ == "__main__":
    unittest.main()
