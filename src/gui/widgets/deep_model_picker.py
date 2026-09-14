"""Reusable asynchronous provider/model selector for setup and saved jobs."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QPushButton, QWidget

from src.deep.models import DiscoveredModel, ModelCatalog, discover_models, preferred_go_model
from src.deep.settings import DeepSettings


class ModelDiscoveryTask(QThread):
    completed = Signal(object, str)

    def __init__(self, settings: DeepSettings, parent: QWidget, installation: Path | None = None) -> None:
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)
        self.installation = installation

    def run(self) -> None:
        try:
            self.completed.emit(discover_models(self.settings, self.installation), "")
        except Exception as error:
            self.completed.emit(None, str(error))


class DeepModelPicker(QWidget):
    catalog_changed = Signal(object)
    selection_changed = Signal()

    def __init__(self, settings: DeepSettings, parent: QWidget | None = None, *,
                 allow_policy_change: bool = True, auto_discover: bool = True,
                 require_resume_support: bool = False, installation: Path | None = None) -> None:
        super().__init__(parent)
        self._settings = copy.deepcopy(settings)
        self._installation = installation
        self._resume_supported = False
        self._catalog = ModelCatalog((), False, None, "")
        self._task: ModelDiscoveryTask | None = None
        self._auto_discover = auto_discover
        self._allow_policy_change = allow_policy_change
        self._require_resume_support = require_resume_support
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.runtime = QComboBox()
        self.runtime.addItems(["opencode", "codex", "claude", "pi", "mock"])
        self.runtime.setCurrentText(settings.runtime)
        layout.addRow("Agent / API runtime", self.runtime)
        self.free = QCheckBox("Use free models only (OpenCode Zen)")
        self.free.setChecked(settings.freeOnly)
        self.free.setEnabled(allow_policy_change)
        layout.addRow(self.free)
        self.provider = QComboBox()
        self.model = QComboBox()
        self.model.setMinimumContentsLength(22)
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        layout.addRow("Provider", self.provider)
        layout.addRow("Model", self.model)
        self.manual = QCheckBox("Enter a custom provider / model ID (advanced)")
        layout.addRow(self.manual)
        self.status = QLabel("Models are discovered locally without sending project files.")
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.refresh_button = QPushButton("Refresh available models")
        self.refresh_button.clicked.connect(self.refresh)
        layout.addRow(self.refresh_button)
        self.preferred_button = QPushButton("Use DeepSeek V4.1 Flash on OpenCode Go")
        self.preferred_button.setVisible(False)
        self.preferred_button.clicked.connect(self._use_preferred)
        layout.addRow(self.preferred_button)
        self._seed(settings.provider, settings.model)
        self.runtime.currentTextChanged.connect(self._runtime_changed)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.model.currentIndexChanged.connect(self._model_changed)
        self.free.toggled.connect(self._free_changed)
        self.manual.toggled.connect(self._manual_changed)
        self._enabled()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._auto_discover:
            self._auto_discover = False
            self.refresh()

    def is_busy(self) -> bool:
        return self._task is not None and self._task.isRunning()

    def _model_changed(self, _index: int) -> None:
        self.selection_changed.emit()

    def _seed(self, provider: str, model: str) -> None:
        self.provider.blockSignals(True)
        self.provider.clear()
        providers = [provider]
        if self.runtime.currentText() == "pi":
            providers += ["openai", "anthropic", "google", "openrouter"]
        for item in dict.fromkeys(providers):
            self.provider.addItem(item, item)
        self.provider.blockSignals(False)
        self.model.clear()
        label = "Automatic · evaluated free models" if model == "automatic-free" else f"{model} (saved; not checked)"
        self.model.addItem(label, model)

    def _provider_id(self) -> str:
        return self.provider.currentText().strip() if self.manual.isChecked() else str(self.provider.currentData() or "")

    def _model_id(self) -> str:
        return self.model.currentText().strip() if self.manual.isChecked() else str(self.model.currentData() or "")

    def apply_to(self, settings: DeepSettings) -> DeepSettings:
        result = copy.deepcopy(settings)
        if self._require_resume_support and not self._resume_supported:
            return result
        result.runtime = self.runtime.currentText()
        result.provider = self._provider_id()
        result.model = self._model_id()
        result.freeOnly = self.free.isChecked()
        if result.freeOnly:
            result.runtime, result.provider = "opencode", "opencode"
            result.model = result.model or "automatic-free"
        return result

    def _enabled(self) -> None:
        busy, free = self.is_busy(), self.free.isChecked()
        busy = busy or (self._require_resume_support and not self._resume_supported)
        self.runtime.setEnabled(not busy and not free)
        self.provider.setEnabled(not busy and not free)
        self.model.setEnabled(not busy)
        self.free.setEnabled(not busy and self._allow_policy_change)
        self.manual.setEnabled(not busy and not free)
        self.refresh_button.setEnabled(not self.is_busy())
        self.preferred_button.setEnabled(not busy and not free)

    def _manual_changed(self, enabled: bool) -> None:
        provider, model = self.provider.currentText().strip(), self.model.currentText().strip()
        # Extract item IDs before switching to editable labels.
        if enabled:
            provider = str(self.provider.currentData() or self.provider.currentText())
            model = str(self.model.currentData() or "")
        self.provider.setEditable(enabled)
        self.model.setEditable(enabled)
        if enabled:
            self.provider.setEditText(provider)
            self.model.setEditText(model)
        else:
            self._seed(provider, model)

    def _use_preferred(self) -> None:
        preferred = preferred_go_model(self._catalog, self.free.isChecked())
        if preferred is None:
            return
        self.manual.setChecked(False)
        self.provider.setCurrentIndex(self.provider.findData(preferred.provider))
        self._populate_models(preferred.provider, preferred.id)

    def _free_changed(self, enabled: bool) -> None:
        if enabled:
            self.manual.setChecked(False)
            self.runtime.setCurrentText("opencode")
            self._seed("opencode", "automatic-free")
        else:
            self._seed(self.runtime.currentText(), "")
        self._enabled()
        self.refresh()
        self.selection_changed.emit()

    def _runtime_changed(self, runtime: str) -> None:
        self._catalog = ModelCatalog((), False, None, "")
        self.manual.setChecked(False)
        self._seed("openai" if runtime == "pi" else runtime, "simulation" if runtime == "mock" else "")
        self.refresh()
        self.selection_changed.emit()

    def _provider_changed(self) -> None:
        if self.manual.isChecked():
            return
        self._populate_models(self._provider_id(), "")
        if self.runtime.currentText() == "pi":
            self.refresh()
        self.selection_changed.emit()

    def _populate_models(self, provider: str, selected: str) -> None:
        self.model.clear()
        for model in self._catalog.models:
            if model.provider != provider or not model.available:
                continue
            suffix = " · sign-in required" if model.authenticated is False else ""
            self.model.addItem(f"{model.name}{suffix}", model.id)
        index = self.model.findData(selected)
        if index >= 0:
            self.model.setCurrentIndex(index)
        elif selected:
            self.model.insertItem(0, f"{selected} (saved; not in catalog)", selected)
            self.model.setCurrentIndex(0)
        elif self.model.count() == 0:
            self.model.addItem("No models discovered", "")

    def refresh(self) -> None:
        if self.is_busy():
            return
        settings = self.apply_to(self._settings)
        settings.model = settings.model or "discovery"
        settings.roleOverrides = {}
        self.status.setText("Discovering models and sign-in status… No project files are sent.")
        self._task = ModelDiscoveryTask(settings, self, self._installation)
        self._task.completed.connect(self.set_catalog)
        self._task.finished.connect(self._enabled)
        self._task.start()
        self._enabled()

    def set_catalog(self, catalog: ModelCatalog | None, error: str = "") -> None:
        if catalog is None:
            self.status.setText(f"Model discovery unavailable: {error}. Saved selections are retained; install or update Deep and retry.")
            return
        self._catalog = catalog
        self._resume_supported = catalog.resume_model_selection
        provider, selected = self._provider_id(), self._model_id()
        preferred = preferred_go_model(catalog, self.free.isChecked())
        recommend = preferred is not None and (not selected or selected == "automatic-free")
        if preferred is not None and recommend:
            provider, selected = preferred.provider, preferred.id
        if not self.manual.isChecked() and not self.free.isChecked():
            self.provider.blockSignals(True)
            self.provider.clear()
            providers: dict[str, str] = {provider: provider}
            for model in catalog.models:
                providers[model.provider] = model.provider_name
            for identity, name in providers.items():
                self.provider.addItem(name, identity)
            self.provider.setCurrentIndex(self.provider.findData(provider))
            self.provider.blockSignals(False)
            self._populate_models(provider, selected)
        elif self.free.isChecked():
            self.model.clear()
            self.model.addItem("Automatic · evaluated free models", "automatic-free")
            for model in catalog.models:
                if model.available and model.free_eligible:
                    self.model.addItem(f"{model.name} · verified free", model.id)
            index = self.model.findData(selected)
            if index < 0 and selected:
                self.model.addItem(f"{selected} (saved; free eligibility not confirmed)", selected)
                index = self.model.count() - 1
            self.model.setCurrentIndex(max(0, index))
        auth = "Signed in" if catalog.authenticated is True else "Sign-in required" if catalog.authenticated is False else "Sign-in varies by provider"
        description = f"{len(catalog.models)} models discovered. {auth}. {catalog.reason}"
        if self.free.isChecked():
            count = sum(model.free_eligible and model.available for model in catalog.models)
            description += f" {count} verified free candidates; eligibility is checked again before use."
        self.preferred_button.setVisible(preferred is not None)
        if preferred is not None:
            description += " Your preferred DeepSeek V4.1 Flash is available on connected OpenCode Go."
        if not catalog.installed:
            description = "Runtime unavailable. " + description
        if self._require_resume_support and not catalog.resume_model_selection:
            description += " This extension cannot change models for saved jobs. Update Deep components for new jobs; this job retains its model."
        self.status.setText(description)
        self._enabled()
        self.catalog_changed.emit(catalog)
        self.selection_changed.emit()

    def available_models(self) -> tuple[DiscoveredModel, ...]:
        return self._catalog.models
