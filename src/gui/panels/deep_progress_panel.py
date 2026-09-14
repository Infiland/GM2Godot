"""Scrollable live Deep work lists and explicit pause/recovery controls."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from src.deep.progress import ACTIVE, ATTENTION, DONE, DeepProgress
from src.deep.settings import DeepSettings
from src.gui.theme import THEME


class DeepProgressPanel(QWidget):
    pause_requested = Signal()
    resume_requested = Signal()
    limits_changed = Signal(int, int)
    artifacts_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = DeepProgress()
        self._running = False
        self._pending_limits = False
        self._free_only = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh)
        self._rows: dict[str, dict[str, QTreeWidgetItem]] = {name: {} for name in ("agents", "research", "implementation")}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Preparing Deep research…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        controls = QHBoxLayout()
        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        self.free_workers = QSpinBox()
        self.free_workers.setRange(1, 32)
        controls.addWidget(QLabel("Researchers"))
        controls.addWidget(self.workers)
        self.free_label = QLabel("Free provider limit")
        controls.addWidget(self.free_label)
        controls.addWidget(self.free_workers)
        self.apply_button = QPushButton("Apply limits")
        self.apply_button.clicked.connect(self._apply_limits)
        controls.addWidget(self.apply_button)
        controls.addStretch()
        layout.addLayout(controls)
        actions = QHBoxLayout()
        self.pause_button = QPushButton("Pause and save")
        self.pause_button.clicked.connect(self.pause_requested.emit)
        actions.addWidget(self.pause_button)
        self.resume_button = QPushButton("Resume / change model…")
        self.resume_button.clicked.connect(self.resume_requested.emit)
        actions.addWidget(self.resume_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.hint = QLabel("Worker reductions take effect as active agents finish. Implementation is integrated one task at a time.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a resource, task, model or agent…")
        self.search.textChanged.connect(self._filter)
        filters.addWidget(self.search, 1)
        self.filter_state = QComboBox()
        self.filter_state.addItems(["All tasks", "Active", "Pending", "Completed", "Needs attention"])
        self.filter_state.currentTextChanged.connect(self._filter)
        filters.addWidget(self.filter_state)
        artifacts = QPushButton("Open saved progress")
        artifacts.clicked.connect(self.artifacts_requested.emit)
        filters.addWidget(artifacts)
        layout.addLayout(filters)
        self.tabs = QTabWidget()
        self.trees: dict[str, QTreeWidget] = {}
        for key, title in (("agents", "Agents"), ("research", "Research"), ("implementation", "Implementation")):
            tree = QTreeWidget()
            tree.setHeaderLabels(["Agent / task" if key == "agents" else "Resource / task", "Status", "Role", "Provider / model", "Attempt"])
            tree.setRootIsDecorated(False)
            tree.setAlternatingRowColors(True)
            tree.setStyleSheet(f"QTreeWidget {{ background: {THEME['bg_secondary']}; alternate-background-color: {THEME['bg_dialog']}; color: {THEME['fg_primary']}; border: 1px solid {THEME['border']}; }} QTreeWidget::item {{ padding: 4px; }} QTreeWidget::item:selected {{ background: {THEME['accent_blue']}; color: white; }} QHeaderView::section {{ background: {THEME['bg_tertiary']}; color: {THEME['fg_primary']}; padding: 6px; border: none; }}")
            tree.setUniformRowHeights(True)
            tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            tree.setColumnWidth(1, 110)
            tree.setColumnWidth(2, 95)
            tree.setColumnWidth(4, 65)
            tree.itemSelectionChanged.connect(self._details)
            self.trees[key] = tree
            self.tabs.addTab(tree, title)
        self.tabs.currentChanged.connect(self._details)
        layout.addWidget(self.tabs, 1)
        self.details = QTextBrowser()
        self.details.setMaximumHeight(100)
        self.details.setPlaceholderText("Select a task or agent to inspect its current activity, findings or failure reason.")
        layout.addWidget(self.details)
        self.setMinimumHeight(270)

    def begin(self, model: DeepProgress, settings: DeepSettings) -> None:
        self.model = model
        self._pending_limits = False
        self._free_only = settings.freeOnly
        for tree in self.trees.values():
            tree.clear()
        self._rows = {name: {} for name in self.trees}
        self.workers.setValue(settings.analysisWorkers)
        self.free_workers.setValue(settings.freeProviderConcurrency)
        self.free_workers.setVisible(settings.freeOnly)
        self.free_label.setVisible(settings.freeOnly)
        self.set_running(True)
        self.refresh()

    def set_running(self, running: bool) -> None:
        self._running = running
        self.pause_button.setEnabled(running)
        self.resume_button.setEnabled((running and self.model.features.get("resumeModelSelection", False)) or (not running and self.model.state in {"paused", "review", "running", "research"}))
        self.resume_button.setText("Change model…" if running else "Review plan…" if self.model.state == "review" else "Resume / change model…")
        self.apply_button.setEnabled(running and self.model.features.get("liveConfiguration", False) and not self._pending_limits)

    def _apply_limits(self) -> None:
        self._pending_limits = True
        self.apply_button.setEnabled(False)
        self.hint.setText("Applying worker limits… Active agents keep their current work.")
        self.limits_changed.emit(self.workers.value(), self.free_workers.value())

    def control_result(self, result: dict[str, Any], error: dict[str, Any] | None = None) -> None:
        self._pending_limits = False
        if error:
            self.hint.setText(str(error.get("message", "Unable to change worker limits. Pause and adjust them before resuming.")))
        else:
            requested = result.get("requestedAnalysisWorkers", result.get("analysisWorkers", self.workers.value()))
            effective = result.get("analysisWorkers", requested)
            self.workers.setValue(int(requested))
            self.free_workers.setValue(int(result.get("freeProviderConcurrency", self.free_workers.value())))
            self.hint.setText(f"Research limit applied: {effective} active at most. Reductions wait for active agents to finish.")
        self.set_running(self._running)

    def refresh(self) -> None:
        for key, source in (("agents", self.model.agents), ("research", self.model.tasks), ("implementation", self.model.tasks)):
            for identifier, row in source.items():
                if key != "agents" and row.get("phase") != key:
                    continue
                item = self._rows[key].get(identifier)
                if item is None:
                    item = QTreeWidgetItem(self.trees[key])
                    self._rows[key][identifier] = item
                label = str(row.get("label") or row.get("taskId") or identifier)
                values = [label, str(row.get("state", "pending")).replace("_", " ").title(), str(row.get("role", "—")),
                          " / ".join(str(row[field]) for field in ("provider", "model") if row.get(field)) or "—", str(row.get("attempt", "—"))]
                for column, value in enumerate(values):
                    item.setText(column, value)
                    item.setToolTip(column, value)
                item.setData(0, Qt.ItemDataRole.UserRole, row)
        active = sum(row.get("state") in ACTIVE for row in self.model.agents.values())
        research, research_total, research_blocked = self.model.counts("research")
        implemented, implementation_total, implementation_blocked = self.model.counts("implementation")
        self.tabs.setTabText(0, f"Agents · {active} active")
        self.tabs.setTabText(1, f"Research · {research}/{research_total}")
        self.tabs.setTabText(2, f"Implementation · {implemented}/{implementation_total}")
        phase = {"analyze": "Research", "plan": "Planning", "implement": "Implementation", "validate": "Validation", "report": "Report"}.get(self.model.phase, self.model.phase.title())
        state = self.model.state.title()
        self.summary.setText(f"{phase} · {state} · {active} active agents · {research_blocked + implementation_blocked} need attention")
        if not self.model.features.get("monitoring"):
            self.hint.setText("Live task inventories require updated Deep components. Existing progress is still saved; you can pause and resume this job.")
        self.set_running(self._running)
        self._filter()
        self._details()

    def schedule_refresh(self) -> None:
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _filter(self) -> None:
        query = self.search.text().casefold()
        selection = self.filter_state.currentText()
        for rows in self._rows.values():
            for item in rows.values():
                row = item.data(0, Qt.ItemDataRole.UserRole)
                state = str(row.get("state", "pending"))
                matches = selection == "All tasks" or (selection == "Active" and state in ACTIVE) or (selection == "Completed" and state in DONE) or (selection == "Needs attention" and state in ATTENTION) or (selection == "Pending" and state not in ACTIVE | DONE | ATTENTION)
                text = " ".join(item.text(column) for column in range(5)).casefold()
                item.setHidden(not matches or query not in text)

    def _details(self) -> None:
        tree = self.trees.get(("agents", "research", "implementation")[self.tabs.currentIndex()])
        selected = tree.selectedItems() if tree else []
        if not selected:
            self.details.setPlainText(self.model.message)
            return
        row = selected[0].data(0, Qt.ItemDataRole.UserRole)
        parts = [f"{key.replace('_', ' ').title()}: {row[key]}" for key in ("summary", "reason", "label", "state", "role", "provider", "model", "attempt", "taskId", "agentId", "artifact", "usage") if row.get(key) is not None]
        self.details.setPlainText("\n".join(parts))
