"""Model discovery, exact recommendations, and recoverable GUI selection."""
from __future__ import annotations

import os
import threading
import time
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from src.deep.models import DiscoveredModel, ModelCatalog, discover_models, parse_catalog, preferred_go_model
from src.deep.settings import DeepSettings
from src.gui.dialogs.deep_resume_dialog import DeepResumeDialog
from src.gui.widgets.deep_model_picker import DeepModelPicker


def go_catalog(*, authenticated: bool | None = True, resume: bool = True) -> ModelCatalog:
    return ModelCatalog((DiscoveredModel("deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "opencode-go", "OpenCode Go", authenticated),), True, None, "", resume)


class DiscoveryTests(unittest.TestCase):
    def test_legacy_metadata_cannot_claim_free_or_connected(self) -> None:
        catalog = parse_catalog({"provider": {"installed": True, "models": [
            {"id": "free-example", "name": "Free example"},
            {"id": "free-example"}, None, {"id": ""},
        ]}}, "opencode")
        self.assertEqual(len(catalog.models), 1)
        self.assertFalse(catalog.models[0].free_eligible)
        self.assertIsNone(catalog.models[0].authenticated)
        self.assertFalse(catalog.resume_model_selection)

    def test_free_metadata_requires_zen_and_exact_boolean(self) -> None:
        catalog = parse_catalog({"features": {"resumeModelSelection": True}, "provider": {"models": [
            {"id": "a", "provider": "opencode", "freeEligible": True},
            {"id": "b", "provider": "opencode-go", "freeEligible": True},
            {"id": "c", "provider": "opencode", "freeEligible": "true"},
            {"id": "d", "available": False},
        ]}}, "opencode")
        self.assertEqual([model.free_eligible for model in catalog.models], [True, False, False, False])
        self.assertFalse(catalog.models[-1].available)
        self.assertTrue(catalog.resume_model_selection)
        self.assertEqual(parse_catalog({"provider": {"models": None}}, "opencode").models, ())
        with self.assertRaises(ValueError):
            parse_catalog({"provider": []}, "opencode")

    def test_go_preference_requires_exact_available_authenticated_candidate_and_paid_opt_in(self) -> None:
        self.assertIsNotNone(preferred_go_model(go_catalog(), False))
        self.assertIsNone(preferred_go_model(go_catalog(), True))
        self.assertIsNone(preferred_go_model(go_catalog(authenticated=False), False))
        self.assertIsNone(preferred_go_model(go_catalog(authenticated=None), False))
        similar = ModelCatalog((DiscoveredModel("deepseek-v4-flash", "DeepSeek V4 Flash", "opencode-go", "Go", True),), True, True, "")
        self.assertIsNone(preferred_go_model(similar, False))

    def test_discovery_uses_pinned_extension_and_closes_session(self) -> None:
        with patch("src.deep.models.ExtensionManager") as manager, patch("src.deep.models.DeepSession") as session, patch("src.deep.models.credential_environment", return_value={}), patch("src.deep.models.opencode_path", return_value=None):
            session.return_value.request.return_value = {"result": {"provider": {"installed": True, "models": []}}}
            installation = Path("/pinned-extension")
            result = discover_models(DeepSettings(), installation)
            self.assertTrue(result.installed)
            manager.return_value.command.assert_called_once_with(installation)
            self.assertEqual(session.return_value.request.call_args.args[0], "capabilities")
            self.assertEqual(set(session.return_value.request.call_args.args[1]), {"settings"})
            session.return_value.close.assert_called_once()


class ModelPickerTests(unittest.TestCase):
    application: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_discovered_go_preferred_without_guessing_id(self) -> None:
        settings = DeepSettings(freeOnly=False)
        picker = DeepModelPicker(settings, auto_discover=False)
        picker.set_catalog(go_catalog(), "")
        self.assertEqual(picker.provider.currentText(), "OpenCode Go")
        self.assertEqual(picker.model.currentText(), "DeepSeek V4.1 Flash")
        result = picker.apply_to(settings)
        self.assertEqual((result.provider, result.model), ("opencode-go", "deepseek-v4.1-flash"))
        self.assertFalse(result.freeOnly)
        picker.close()

    def test_free_policy_is_not_switched_by_discovery(self) -> None:
        settings = DeepSettings()
        picker = DeepModelPicker(settings, auto_discover=False)
        picker.set_catalog(go_catalog(), "")
        self.assertEqual(picker.apply_to(settings), settings)
        self.assertFalse(picker.provider.isEnabled())
        picker.close()

    def test_free_recovery_can_select_only_verified_free_models(self) -> None:
        settings = DeepSettings()
        picker = DeepModelPicker(settings, auto_discover=False)
        catalog = ModelCatalog((
            DiscoveredModel("eligible", "Eligible", "opencode", "Zen", True, True),
            DiscoveredModel("unknown", "Unknown", "opencode", "Zen", None),
            *go_catalog().models,
        ), True, None, "", True)
        picker.set_catalog(catalog)
        self.assertEqual(picker.model.count(), 2)
        picker.model.setCurrentIndex(1)
        result = picker.apply_to(settings)
        self.assertEqual(result.model, "eligible")
        self.assertEqual(result.provider, "opencode")
        self.assertTrue(result.freeOnly)
        picker.close()

    def test_explicit_saved_selection_retained_and_recommendation_is_optional(self) -> None:
        settings = DeepSettings(freeOnly=False, provider="anthropic", model="chosen-model")
        picker = DeepModelPicker(settings, auto_discover=False)
        picker.set_catalog(go_catalog(), "")
        self.assertEqual(picker.apply_to(settings).model, "chosen-model")
        picker.preferred_button.click()
        self.assertEqual(picker.apply_to(settings).model, "deepseek-v4.1-flash")
        picker.close()

    def test_missing_extension_keeps_saved_selection_and_reports_recovery(self) -> None:
        settings = DeepSettings(freeOnly=False, model="saved")
        picker = DeepModelPicker(settings, auto_discover=False)
        picker.set_catalog(None, "Components not installed")
        self.assertEqual(picker.apply_to(settings), settings)
        self.assertIn("install or update", picker.status.text())
        picker.close()

    def test_old_extension_cannot_change_saved_job_model(self) -> None:
        settings = DeepSettings(freeOnly=False, model="saved")
        picker = DeepModelPicker(settings, auto_discover=False, require_resume_support=True)
        picker.set_catalog(go_catalog(resume=False), "")
        picker.preferred_button.click()
        self.assertEqual(picker.apply_to(settings), settings)
        self.assertFalse(picker.provider.isEnabled())
        picker.close()

    def test_resume_model_change_clears_old_role_overrides_without_mutating_original(self) -> None:
        original = DeepSettings(freeOnly=False, model="old", roleOverrides={"researcher": {"model": "limited"}})
        dialog = DeepResumeDialog(original)
        picker = dialog.findChild(DeepModelPicker)
        assert picker is not None
        picker.set_catalog(go_catalog(), "")
        picker.preferred_button.click()
        resumed = dialog.settings()
        self.assertEqual(resumed.model, "deepseek-v4.1-flash")
        self.assertEqual(resumed.roleOverrides, {})
        self.assertEqual(original.roleOverrides, {"researcher": {"model": "limited"}})
        dialog.close()

    def test_discovery_is_async_and_dialog_retains_worker_until_finished(self) -> None:
        started, release = threading.Event(), threading.Event()

        def discovery(_settings: DeepSettings, _installation: Path | None) -> ModelCatalog:
            started.set()
            release.wait(3)
            return go_catalog()

        with patch("src.gui.widgets.deep_model_picker.discover_models", side_effect=discovery):
            picker = DeepModelPicker(DeepSettings(), auto_discover=False)
            picker.refresh()
            self.assertTrue(started.wait(1))
            self.assertTrue(picker.is_busy())
            self.assertFalse(picker.refresh_button.isEnabled())
            release.set()
            deadline = time.monotonic() + 3
            while picker.is_busy() and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.005)
            self.application.processEvents()
            self.assertFalse(picker.is_busy())
            self.assertIn("models discovered", picker.status.text())
            picker.close()
