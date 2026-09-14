"""Optional dependency setup runs outside the Qt event thread."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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

from src.deep.credentials import credential_environment, save_credential
from src.deep.install import ExtensionManager, opencode_path
from src.deep.opencode import install_opencode
from src.deep.session import DeepSession
from src.deep.settings import DeepSettings, data_directory, load_settings, save_settings


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
        self._runtime = QComboBox()
        self._runtime.addItems(["opencode", "codex", "claude", "pi", "mock"])
        self._runtime.setCurrentText(self._settings.runtime)
        layout.addRow("Agent / API runtime", self._runtime)
        self._provider = QLineEdit(self._settings.provider)
        layout.addRow("Provider", self._provider)
        self._model = QLineEdit(self._settings.model)
        layout.addRow("Model", self._model)
        self._free = QCheckBox("Automatic · Free models (OpenCode Zen only)")
        self._free.setChecked(self._settings.freeOnly)
        self._free.toggled.connect(self._free_changed)
        layout.addRow(self._free)
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
        self._roles: dict[str, QLineEdit] = {}
        self._role_providers: dict[str, QLineEdit] = {}
        self._role_runtimes: dict[str, QComboBox] = {}
        for role in ("researcher", "planner", "implementer", "reviewer"):
            override = self._settings.roleOverrides.get(role, {})
            field = QLineEdit(override.get("model", ""))
            field.setPlaceholderText("Use default model")
            self._roles[role] = field
            layout.addRow(f"{role.title()} model", field)
            provider = QLineEdit(override.get("provider", ""))
            provider.setPlaceholderText("Use default provider")
            self._role_providers[role] = provider
            layout.addRow(f"{role.title()} provider", provider)
            runtime = QComboBox()
            runtime.addItems(["Use default", "opencode", "codex", "claude", "pi", "mock"])
            runtime.setCurrentText(override.get("runtime", "Use default"))
            self._role_runtimes[role] = runtime
            layout.addRow(f"{role.title()} runtime", runtime)
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

    def _installation_status(self) -> str:
        try:
            return f"Deep installed: {ExtensionManager().installation().name}\nOpenCode: {opencode_path() or 'not installed'}"
        except FileNotFoundError:
            return "Deep components are not installed. Normal conversion is ready to use."

    def _free_changed(self, enabled: bool) -> None:
        if enabled:
            self._runtime.setCurrentText("opencode")
            self._provider.setText("opencode")
            self._model.setText("automatic-free")
            self._free_workers.setValue(1)
            self._cost.setValue(0)
        else:
            self._workers.setValue(4)

    def settings(self) -> DeepSettings:
        value = DeepSettings(runtime=self._runtime.currentText(), provider=self._provider.text().strip(), model=self._model.text().strip(), freeOnly=self._free.isChecked(), analysisWorkers=self._workers.value(), freeProviderConcurrency=self._free_workers.value(), godotBinary=self._godot.text().strip() or None, budgets={"maxTokens": self._tokens.value(), "maxCostUsd": self._cost.value(), "maxSeconds": self._seconds.value()}, roleOverrides={role: {"model": field.text().strip()} for role, field in self._roles.items() if field.text().strip()})
        for role, provider in self._role_providers.items():
            if provider.text().strip():
                value.roleOverrides.setdefault(role, {})["provider"] = provider.text().strip()
        for role, runtime in self._role_runtimes.items():
            if runtime.currentText() != "Use default":
                value.roleOverrides.setdefault(role, {})["runtime"] = runtime.currentText()
        value.validate()
        return value

    def _save(self) -> None:
        if self._task and self._task.isRunning():
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
            settings = self.settings()
            if self._secret.text():
                save_credential(settings.provider, self._secret.text())
            environment = credential_environment(settings.provider)
            binary = opencode_path()
            if binary:
                environment["PATH"] = os.path.dirname(binary) + os.pathsep + os.environ.get("PATH", "")
        except Exception as error:
            QMessageBox.warning(self, "Deep setup", str(error))
            return
        def action() -> str:
            session = DeepSession(ExtensionManager().command(), data_directory() / "connection-check", environment=environment)
            try:
                response: dict[str, Any] = session.request("capabilities", {"settings": settings.to_dict()}, timeout=60)
                return json.dumps(response.get("result", {}), indent=2)
            finally:
                session.close()
        self._start(action)

    def _start(self, action: Callable[[], str]) -> None:
        if self._task and self._task.isRunning():
            return
        self._status.setText("Working…")
        self._task = SetupTask(action, self)
        self._task.completed.connect(self._completed)
        self._task.start()

    def _completed(self, success: bool, message: str) -> None:
        self._status.setText(("Ready: " if success else "Unable to complete: ") + message)

    def reject(self) -> None:
        if self._task and self._task.isRunning():
            return
        super().reject()
