"""Adjust cumulative limits without changing the approved provider or project plan."""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from src.deep.settings import DeepSettings


class DeepResumeDialog(QDialog):
    def __init__(self, settings: DeepSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = copy.deepcopy(settings)
        self.setWindowTitle("Resume Deep job")
        layout = QFormLayout(self)
        explanation = QLabel("Increase exhausted limits before resuming. Token and cost limits include work already completed. The time limit starts again on resume. Provider, model and reviewed project remain unchanged.")
        explanation.setWordWrap(True)
        layout.addRow(explanation)
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
        layout.addRow(resume)

    def settings(self) -> DeepSettings:
        settings = copy.deepcopy(self._settings)
        settings.budgets.update(maxTokens=self._tokens.value(), maxCostUsd=self._cost.value(), maxSeconds=self._seconds.value())
        settings.analysisWorkers = self._workers.value()
        settings.freeProviderConcurrency = self._free_workers.value()
        settings.validate()
        return settings
