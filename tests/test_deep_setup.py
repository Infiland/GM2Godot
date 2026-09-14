"""Offscreen GUI regressions for optional setup and ordinary conversion settings."""
from __future__ import annotations

import os
import unittest
from typing import cast
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox

from src.conversion.converter import CONVERSION_CATEGORIES
from src.deep.settings import DeepSettings
from src.gui.dialogs.deep_resume_dialog import DeepResumeDialog
from src.gui.dialogs.deep_setup_dialog import DeepSetupDialog
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.gui.setting_value import SettingValue


class DeepSetupTests(unittest.TestCase):
    application: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_normal_settings_controls_exist_without_deep_install(self) -> None:
        settings = {key: SettingValue(True) for keys in CONVERSION_CATEGORIES.values() for key in keys}
        dialog = SettingsDialog(settings, SettingValue(True), SettingValue(False), "linux", 1)
        self.assertEqual(dialog.selected_platform(), "linux")
        self.assertEqual(dialog.selected_max_workers(), 1)
        dialog.close()

    def test_deep_panel_has_no_download_or_model_call_on_open(self) -> None:
        with patch("src.gui.dialogs.deep_setup_dialog.load_settings", return_value=DeepSettings()), patch("src.gui.dialogs.deep_setup_dialog.ExtensionManager") as manager:
            manager.return_value.installation.side_effect = FileNotFoundError()
            dialog = DeepSetupDialog()
            settings = dialog.settings()
            self.assertFalse(settings.allowRemoteSourceUpload)
            self.assertEqual(settings.analysisWorkers, 4)
            self.assertEqual(settings.freeProviderConcurrency, 1)
            manager.return_value.install.assert_not_called()
            manager.return_value.command.assert_not_called()
            dialog.close()

    def test_resume_limits_keep_provider_and_do_not_mutate_original(self) -> None:
        original = DeepSettings()
        dialog = DeepResumeDialog(original)
        spins = dialog.findChildren(QSpinBox)
        spins[0].setValue(2000000)
        spins[1].setValue(7200)
        spins[2].setValue(8)
        result = dialog.settings()
        self.assertEqual(result.budgets["maxTokens"], 2000000)
        self.assertEqual(result.budgets["maxSeconds"], 7200)
        self.assertEqual(result.analysisWorkers, 8)
        self.assertEqual(original.budgets["maxTokens"], 1000000)
        self.assertEqual(original.analysisWorkers, 4)
        self.assertEqual(result.provider, original.provider)
        self.assertEqual(result.model, original.model)
        self.assertTrue(result.freeOnly)
        self.assertFalse(dialog.findChildren(QDoubleSpinBox)[0].isEnabled())
        dialog.close()
