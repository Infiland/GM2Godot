"""Recover a saved job with explicit model selection and cumulative limits."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.deep.settings import DeepSettings
from src.gui.widgets.deep_model_picker import DeepModelPicker


class DeepResumeDialog(QDialog):
    def __init__(self, settings: DeepSettings, parent: QWidget | None = None, *, allow_model_change: bool = True, installation: Path | None = None) -> None:
        super().__init__(parent)
        self._settings = copy.deepcopy(settings)
        self._allow_model_change = allow_model_change
        self.setWindowTitle("Resume Deep job")
        self.resize(640, 600)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        scroll.setWidget(contents)
        outer.addWidget(scroll)
        layout = QFormLayout(contents)
        explanation = QLabel("Increase exhausted limits before resuming. Token and cost limits include work already completed. The time limit starts again on resume. Completed work is saved. Change a rate-limited model below; future tasks use the new selection. The free-only policy remains unchanged.")
        explanation.setWordWrap(True)
        layout.addRow(explanation)
        self._picker = DeepModelPicker(settings, self, allow_policy_change=False, require_resume_support=True, auto_discover=allow_model_change, installation=installation)
        self._picker.setEnabled(allow_model_change)
        layout.addRow(self._picker)
        model_note = QLabel("Changing the model applies it to every role for future tasks. Project files are sent to the selected provider. Completed work remains saved." if allow_model_change else "This saved job uses an older Deep extension. Its model cannot be changed; limits can still be adjusted.")
        model_note.setWordWrap(True)
        layout.addRow(model_note)
        self._tokens = QSpinBox()
        self._tokens.setRange(int(settings.budgets.get("maxTokens", 1)), 100000000)
        self._tokens.setValue(int(settings.budgets.get("maxTokens", 1000000)))
        layout.addRow("Total token limit", self._tokens)
        self._cost = QDoubleSpinBox()
        self._cost.setRange(settings.budgets.get("maxCostUsd", 0), 100000)
        self._cost.setValue(settings.budgets.get("maxCostUsd", 0))
        self._cost.setEnabled(not settings.freeOnly)
        layout.addRow("Total cost limit (USD)", self._cost)
        self._seconds = QSpinBox()
        self._seconds.setRange(int(settings.budgets.get("maxSeconds", 60)), 604800)
        self._seconds.setValue(int(settings.budgets.get("maxSeconds", 3600)))
        layout.addRow("Additional time (seconds)", self._seconds)
        self._workers = QSpinBox()
        self._workers.setRange(1, 32)
        self._workers.setValue(settings.analysisWorkers)
        layout.addRow("Parallel researchers", self._workers)
        self._free_workers = QSpinBox()
        self._free_workers.setRange(1, 32)
        self._free_workers.setValue(settings.freeProviderConcurrency)
        layout.addRow("Free provider concurrency", self._free_workers)
        resume = QPushButton("Resume saved job")
        resume.clicked.connect(self.accept)
        outer.addWidget(resume)

    def settings(self) -> DeepSettings:
        settings = self._picker.apply_to(self._settings) if self._allow_model_change else copy.deepcopy(self._settings)
        if (settings.runtime, settings.provider, settings.model) != (self._settings.runtime, self._settings.provider, self._settings.model):
            settings.roleOverrides = {}
        settings.budgets.update(maxTokens=self._tokens.value(), maxCostUsd=self._cost.value(), maxSeconds=self._seconds.value())
        settings.analysisWorkers = self._workers.value()
        settings.freeProviderConcurrency = self._free_workers.value()
        settings.validate()
        return settings

    def accept(self) -> None:
        if not self._picker.is_busy():
            super().accept()

    def reject(self) -> None:
        if not self._picker.is_busy():
            super().reject()
