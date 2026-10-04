"""Offscreen GUI regressions for optional setup and ordinary conversion settings."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from src.conversion.converter import CONVERSION_CATEGORIES
from src.deep.install import ExtensionManager
from src.deep.settings import DeepSettings
from src.gui.dialogs.deep_resume_dialog import DeepResumeDialog
from src.gui.dialogs.deep_setup_dialog import DeepSetupDialog
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.gui.setting_value import SettingValue
from src.gui.widgets.deep_model_picker import DeepModelPicker
from tests.test_deep_client import VerifiedReleaseFixture


class DeepSetupTests(unittest.TestCase):
    application: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_download_action_installs_shipped_default_without_automatic_download(self) -> None:
        """An unshown dialog downloads components only through the clicked install action."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            releases = VerifiedReleaseFixture(root)
            manager = ExtensionManager(root / "managed")
            actions: list[Callable[[], str]] = []

            def capture_action(_dialog: DeepSetupDialog, action: Callable[[], str]) -> None:
                actions.append(action)

            with patch("src.gui.dialogs.deep_setup_dialog.load_settings", return_value=DeepSettings()), patch(
                "src.gui.dialogs.deep_setup_dialog.ExtensionManager", return_value=manager,
            ), patch("src.deep.install.platform_key", return_value="linux-x64"), patch(
                "src.deep.install.download_verified_transport", side_effect=releases.download,
            ), patch("src.gui.widgets.deep_model_picker.discover_models") as discovery, patch.object(
                DeepSetupDialog, "_start", autospec=True, side_effect=capture_action,
            ):
                dialog = DeepSetupDialog()
                try:
                    self.assertEqual(releases.requested_urls, [])
                    discovery.assert_not_called()
                    buttons = [button for button in dialog.findChildren(QPushButton)
                               if button.text() == "Download / update Deep components"]
                    self.assertEqual(len(buttons), 1)
                    buttons[0].click()
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(releases.requested_urls, [])
                    result = actions[0]()
                    current = manager.installation()
                    self.assertEqual(result, str(current))
                    self.assertEqual(json.loads((current / "install.json").read_text())["manifest"]["version"], "0.2.2")
                    self.assertEqual(manager.command(), [
                        str(current / "node/bin/node"), str(current / "engine/dist/host/main.js"),
                    ])
                    self.assertEqual((current / "engine/dist/host/main.js").read_bytes(), b"fixture engine 0.2.2\n")
                    self.assertEqual(releases.requested_urls, [
                        "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/deep-manifest.json",
                        "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/fixture-deep-linux-x64.zip",
                    ])
                    discovery.assert_not_called()
                finally:
                    dialog.close()

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

    def test_codex_setup_does_not_save_an_unrelated_entered_api_key(self) -> None:
        settings = DeepSettings(runtime="codex", provider="codex", model="discovered", freeOnly=False,
                                executable="/custom installation/codex")
        with patch("src.gui.dialogs.deep_setup_dialog.load_settings", return_value=settings), patch("src.gui.dialogs.deep_setup_dialog.ExtensionManager"), patch("src.gui.dialogs.deep_setup_dialog.save_settings") as save, patch("src.gui.dialogs.deep_setup_dialog.save_credential") as credential:
            dialog = DeepSetupDialog()
            picker = dialog.findChild(DeepModelPicker)
            assert picker is not None
            secret = dialog.findChildren(QLineEdit)[-1]
            self.assertFalse(secret.isEnabled())
            secret.setText("unrelated-provider-key")
            picker.executable.setText("/new installation/codex")
            dialog.settings().validate()
            dialog.findChildren(QPushButton)[-1].click()
            credential.assert_not_called()
            self.assertEqual(save.call_args.args[0].executable, "/new installation/codex")
            dialog.close()
