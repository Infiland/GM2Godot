"""Optional dependency setup runs outside the Qt event thread."""
from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.deep.credentials import save_credential
from src.deep.install import ExtensionManager, opencode_path
from src.deep.opencode import install_opencode
from src.deep.models import ModelCatalog
from src.gui.widgets.deep_model_picker import DeepModelPicker
from src.deep.settings import DeepSettings, load_settings, save_settings


class SetupTask(QThread):
    completed = Signal(bool, str)

    def __init__(self, action: Callable[[], str], parent: QWidget) -> None:
        super().__init__(parent)
        self.action = action

    def run(self) -> None:
        try:
            self.completed.emit(True, self.action())
        except Exception as error:
            self.completed.emit(False, str(error))


class DeepSetupDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deep conversion setup")
        self.resize(640, 600)
        self._task: SetupTask | None = None
        self._settings = load_settings()
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        scroll.setWidget(contents)
        outer.addWidget(scroll)
        layout = QFormLayout(contents)
        self._status = QLabel(self._installation_status())
        self._status.setWordWrap(True)
        layout.addRow(self._status)
        install = QPushButton("Download / update Deep components")
        install.clicked.connect(lambda: self._start(lambda: str(ExtensionManager().install())))
        layout.addRow(install)
        opencode = QPushButton("Install OpenCode")
        opencode.clicked.connect(lambda: self._start(install_opencode))
        layout.addRow(opencode)
        self._picker = DeepModelPicker(self._settings, self)
        self._picker.catalog_changed.connect(self._catalog_changed)
        layout.addRow(self._picker)
        self._workers = QSpinBox()
        self._workers.setRange(1, 32)
        self._workers.setValue(self._settings.analysisWorkers)
        layout.addRow("Parallel researchers", self._workers)
        self._free_workers = QSpinBox()
        self._free_workers.setRange(1, 32)
        self._free_workers.setValue(self._settings.freeProviderConcurrency)
        layout.addRow("Free provider concurrency", self._free_workers)
        self._tokens = QSpinBox()
        self._tokens.setRange(1, 100000000)
        self._tokens.setValue(int(self._settings.budgets.get("maxTokens", 1000000)))
        layout.addRow("Token limit", self._tokens)
        self._cost = QDoubleSpinBox()
        self._cost.setRange(0, 100000)
        self._cost.setValue(self._settings.budgets.get("maxCostUsd", 0))
        layout.addRow("Cost limit (USD)", self._cost)
        self._seconds = QSpinBox()
        self._seconds.setRange(60, 604800)
        self._seconds.setValue(int(self._settings.budgets.get("maxSeconds", 3600)))
        layout.addRow("Time limit (seconds)", self._seconds)
        self._godot = QLineEdit(self._settings.godotBinary or "")
        layout.addRow("Godot executable (optional)", self._godot)
        self._roles: dict[str, QComboBox] = {}
        for role in ("researcher", "planner", "implementer", "reviewer"):
            field = QComboBox()
            field.addItem("Use default model", {})
            override = self._settings.roleOverrides.get(role, {})
            if override:
                field.addItem(f"Saved override: {override.get('model', 'default model')}", override)
                field.setCurrentIndex(1)
            self._roles[role] = field
            layout.addRow(f"{role.title()} model", field)
        self._secret = QLineEdit()
        self._secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret.setPlaceholderText("Leave blank to keep existing credential / agent login")
        layout.addRow("API key (OS keyring)", self._secret)
        note = QLabel("Source files are sent to the selected provider only after you start research. Existing Codex / Claude / OpenCode sign-in is reused. Free model availability and limits can change. Mock is a simulation.")
        note.setWordWrap(True)
        layout.addRow(note)
        terms = QLabel('<a href="https://opencode.ai/docs/zen/">OpenCode Zen availability, pricing and data use</a>')
        terms.setOpenExternalLinks(True)
        layout.addRow(terms)
        check = QPushButton("Check connection and available models")
        check.clicked.connect(self._check)
        layout.addRow(check)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        layout.addRow(save)
        self._picker.selection_changed.connect(self._sync_policy)
        self._sync_policy()

    def _sync_policy(self) -> None:
        free = self._picker.free.isChecked()
        self._cost.setEnabled(not free)
        if free:
            self._cost.setValue(0)
            for field in self._roles.values():
                override = cast(dict[str, str], field.currentData() or {})
                if override.get("runtime", "opencode") != "opencode" or override.get("provider", "opencode") != "opencode":
                    field.setCurrentIndex(0)

    def _installation_status(self) -> str:
        try:
            return f"Deep installed: {ExtensionManager().installation().name}\nOpenCode: {opencode_path() or 'not installed'}"
        except FileNotFoundError:
            return "Deep components are not installed. Normal conversion is ready to use."
        except (OSError, ValueError) as error:
            return f"Deep components need repair: {error}"

    def _catalog_changed(self, catalog: ModelCatalog) -> None:
        for field in self._roles.values():
            selected = cast(dict[str, str], field.currentData() or {})
            field.clear()
            field.addItem("Use default model", {})
            if selected:
                field.addItem(f"Saved override: {selected.get('model', 'default model')}", selected)
                field.setCurrentIndex(1)
            if self._picker.free.isChecked():
                continue
            for model in catalog.models:
                if model.available:
                    field.addItem(f"{model.provider_name} · {model.name}", {
                        "runtime": self._picker.runtime.currentText(),
                        "provider": model.provider, "model": model.id,
                    })

    def settings(self) -> DeepSettings:
        value = self._picker.apply_to(self._settings)
        value.analysisWorkers = self._workers.value()
        value.freeProviderConcurrency = self._free_workers.value()
        value.godotBinary = self._godot.text().strip() or None
        value.budgets = {"maxTokens": self._tokens.value(), "maxCostUsd": self._cost.value(), "maxSeconds": self._seconds.value()}
        value.roleOverrides = {role: field.currentData() for role, field in self._roles.items() if field.currentData()}
        value.validate()
        return value

    def _save(self) -> None:
        if self._picker.is_busy() or (self._task and self._task.isRunning()):
            return
        try:
            settings = self.settings()
            if self._secret.text():
                save_credential(settings.provider, self._secret.text())
            save_settings(settings)
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "Deep setup", str(error))

    def _check(self) -> None:
        try:
            settings = self._picker.apply_to(self._settings)
            if self._secret.text():
                save_credential(settings.provider, self._secret.text())
            self._picker.refresh()
        except Exception as error:
            QMessageBox.warning(self, "Deep setup", str(error))

    def _start(self, action: Callable[[], str]) -> None:
        if self._picker.is_busy() or (self._task and self._task.isRunning()):
            return
        self._status.setText("Working…")
        self._task = SetupTask(action, self)
        self._task.completed.connect(self._completed)
        self._task.start()

    def _completed(self, success: bool, message: str) -> None:
        self._status.setText(("Ready: " if success else "Unable to complete: ") + message)
        if success:
            self._picker.refresh()

    def reject(self) -> None:
        if self._picker.is_busy() or (self._task and self._task.isRunning()):
            return
        super().reject()
