"""Live CLI report dependencies and borrowed publication restoration contracts."""

from __future__ import annotations

import argparse
import ast
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import PropertyMock, patch

from src import cli, cli_report_lifecycle as reports
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.diagnostics import (
    ConversionDiagnosticReportPublicationReceipt,
    ConversionDiagnosticReportSnapshot,
    DiagnosticCollector,
)


class _ReportBackend:
    def __init__(
        self,
        diagnostics: DiagnosticCollector,
        events: list[str] | None = None,
    ) -> None:
        self.current_diagnostics = diagnostics
        self.events = events
        self.artifact_refreshes: list[ConversionOutcome] = []
        self.attempt_publications: list[ConversionOutcome] = []

    @property
    def diagnostics(self) -> DiagnosticCollector:
        if self.events is not None:
            self.events.append("diagnostics")
        return self.current_diagnostics

    def refresh_conversion_artifacts(
        self,
        attempt_outcome: ConversionOutcome,
    ) -> tuple[str | None, str]:
        self.artifact_refreshes.append(attempt_outcome)
        return "", ""

    def publish_conversion_attempt(self, attempt_outcome: ConversionOutcome) -> str:
        self.attempt_publications.append(attempt_outcome)
        return ""


class _ObservedValues(cli.CLIReportValues):
    def __init__(self, args: argparse.Namespace, events: list[str]) -> None:
        super().__init__(args)
        self.events = events

    @property
    def platform(self) -> str:
        self.events.append("platform")
        return super().platform


def _unchanged_outcome(current: ConversionOutcome) -> ConversionOutcome:
    return current


class TestCLIReportLifecycle(unittest.TestCase):
    def test_live_namespace_late_cli_writers_and_distinct_none_read_stages(self) -> None:
        events: list[str] = []
        args = argparse.Namespace(platform="linux", godot_project="managed")
        values = _ObservedValues(args, events)
        operations = cli.CLIReportOperations()
        diagnostics = DiagnosticCollector()
        static_calls: list[tuple[str, str | None]] = []

        def first_writer(root: str, target_platform: str | None = None) -> None:
            static_calls.append((root, target_platform))

        def second_writer(root: str, target_platform: str | None = None) -> None:
            static_calls.append((root, target_platform))

        with patch.object(cli, "_write_static_reports", first_writer):
            reports.write_staged_cli_reports("first-stage", os.curdir, diagnostics, values, operations)
        args.platform = "macos"
        with patch.object(cli, "_write_static_reports", second_writer):
            reports.write_staged_cli_reports("second-stage", os.curdir, diagnostics, values, operations)
        self.assertEqual(static_calls, [("first-stage", "linux"), ("second-stage", "macos")])
        with patch.object(
            _ObservedValues,
            "platform",
            new_callable=PropertyMock,
            side_effect=AssertionError("staged None must not read platform"),
        ):
            reports.write_staged_cli_reports("unused-stage", None, diagnostics, values, operations)

        events.clear()
        backend = _ReportBackend(diagnostics, events)
        lifecycle = reports.ConversionReportLifecycle(
            backend,
            values,
            reports.ConversionReportState(external_report_dir=None),
            operations,
            _unchanged_outcome,
        )
        external_calls: list[tuple[str | None, str, DiagnosticCollector]] = []

        def external_writer(
            destination: str | None,
            target_platform: str,
            current_diagnostics: DiagnosticCollector,
        ) -> ConversionDiagnosticReportPublicationReceipt | None:
            events.append("writer")
            external_calls.append((destination, target_platform, current_diagnostics))
            return None

        with patch.object(cli, "_write_external_conversion_reports", external_writer):
            lifecycle.publish_external_reports()
        self.assertEqual(events, ["platform", "diagnostics", "writer"])
        self.assertEqual(external_calls, [(None, "macos", diagnostics)])

    def test_repair_uses_reassigned_backend_diagnostics_and_real_report_publication(self) -> None:
        original = DiagnosticCollector()
        current = DiagnosticCollector()
        backend = _ReportBackend(original)
        with tempfile.TemporaryDirectory() as directory:
            destination = str(Path(directory) / "external")
            args = argparse.Namespace(platform="linux", godot_project=directory)
            lifecycle = reports.ConversionReportLifecycle(
                backend,
                cli.CLIReportValues(args),
                reports.ConversionReportState(external_report_dir=destination),
                cli.CLIReportOperations(),
                _unchanged_outcome,
            )
            backend.current_diagnostics = current
            outcome = ConversionOutcome(state="failed", failure_phase="runtime")
            with (
                patch.object(original, "publish_reports", side_effect=AssertionError("stale collector")),
                patch.object(current, "publish_reports", wraps=current.publish_reports) as publication,
            ):
                self.assertIs(lifecycle.repair(outcome), outcome)
            publication.assert_called_once_with(destination)
            self.assertIsNone(original.outcome())
            self.assertIs(current.outcome(), outcome)
            self.assertIn('"state": "failed"', (Path(destination) / "gm2godot/conversion_diagnostics.json").read_text())
            self.assertEqual(backend.artifact_refreshes, [])
            self.assertEqual(backend.attempt_publications, [])

    def test_reverse_restore_retains_failed_real_receipt_notes_and_clears_after_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destinations = (root / "first", root / "second")
            original = DiagnosticCollector()
            original.add("warning", "GM2GD-OLD", "Previous generation.")
            for destination in destinations:
                original.publish_reports(str(destination))
            backend = _ReportBackend(DiagnosticCollector())
            state = reports.ConversionReportState(external_report_dir=None, protect_managed_reports=True)
            lifecycle = reports.ConversionReportLifecycle(
                backend,
                cli.CLIReportValues(argparse.Namespace(platform="linux", godot_project=directory)),
                state,
                cli.CLIReportOperations(),
                _unchanged_outcome,
            )
            first = lifecycle.checkpoint(str(destinations[0]))
            second = lifecycle.checkpoint(str(destinations[1]))
            assert first is not None and second is not None
            original_bytes = {
                path: Path(path).read_bytes()
                for checkpoint in (first, second)
                for path in (checkpoint.snapshot.json_path, checkpoint.snapshot.markdown_path)
            }
            replacement = DiagnosticCollector()
            replacement.add("error", "GM2GD-NEW", "Attempt publication.")
            first_receipt = replacement.publish_reports(first.destination)
            second_receipt = replacement.publish_reports(second.destination)
            first.receipt, second.receipt = first_receipt, second_receipt
            failed_bytes = Path(second.snapshot.json_path).read_bytes()
            failure = OSError("retained second receipt")
            failure.add_note("first recovery note")
            failure.add_note("second recovery note")
            real_restore = cli.restore_conversion_diagnostic_reports
            observed: list[tuple[str, ConversionDiagnosticReportPublicationReceipt]] = []

            def restore(
                destination: str,
                snapshot: ConversionDiagnosticReportSnapshot,
                receipt: ConversionDiagnosticReportPublicationReceipt,
            ) -> None:
                observed.append((destination, receipt))
                if destination == second.destination:
                    raise failure
                real_restore(destination, snapshot, receipt)

            with patch.object(cli, "restore_conversion_diagnostic_reports", restore):
                self.assertFalse(lifecycle.reset_publications())
            self.assertEqual(observed, [(second.destination, second_receipt), (first.destination, first_receipt)])
            self.assertIsNone(first.receipt)
            self.assertIs(second.receipt, second_receipt)
            self.assertEqual(list(state.managed_report_checkpoints.values()), [first, second])
            error = state.report_restore_error
            assert isinstance(error, OSError)
            self.assertEqual(
                str(error),
                "managed conversion diagnostics could not be restored: " + second.destination + ": retained second receipt",
            )
            self.assertEqual(
                error.__notes__,
                [second.destination + ": first recovery note", second.destination + ": second recovery note"],
            )
            self.assertEqual(Path(first.snapshot.json_path).read_bytes(), original_bytes[first.snapshot.json_path])
            self.assertEqual(Path(second.snapshot.json_path).read_bytes(), failed_bytes)
            self.assertTrue(lifecycle.restore_managed_reports())
            self.assertEqual(state.managed_report_checkpoints, {})
            self.assertIsNone(state.report_restore_error)
            self.assertIsNone(second.receipt)
            for path, content in original_bytes.items():
                self.assertEqual(Path(path).read_bytes(), content)

    def test_report_import_boundary_and_single_observer_repair_reentry(self) -> None:
        allowed = {"src.conversion.conversion_outcome", "src.conversion.diagnostics"}

        def project_edges(source: str) -> set[str]:
            dependencies: set[str] = set()
            for node in ast.walk(ast.parse(source)):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level or node.module is None or any(alias.name == "*" for alias in node.names):
                        raise AssertionError("Relative or wildcard report import")
                    names = [node.module]
                for name in names:
                    if name.split(".", 1)[0] in sys.stdlib_module_names:
                        continue
                    if name not in allowed:
                        raise AssertionError("Report owner backedge: " + name)
                    dependencies.add(name)
            return dependencies

        self.assertEqual(project_edges(Path(reports.__file__).read_text()), allowed)
        for forbidden in (
            "from src import cli",
            "def late():\n    from src import cli\n",
            "from src.conversion.converter import Converter",
            "from src.conversion.diagnostics import *",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(AssertionError):
                    project_edges(forbidden)

        backend = _ReportBackend(DiagnosticCollector())
        observations: list[str] = []
        publications: list[str] = []

        def observe(current: ConversionOutcome) -> ConversionOutcome:
            observations.append(current.state)
            return replace(current, state="cancelled") if current.state == "success" else current

        real_publish = backend.diagnostics.publish_reports

        def publish(destination: str) -> ConversionDiagnosticReportPublicationReceipt:
            outcome = backend.diagnostics.outcome()
            assert outcome is not None
            publications.append(outcome.state)
            return real_publish(destination)

        with tempfile.TemporaryDirectory() as directory:
            lifecycle = reports.ConversionReportLifecycle(
                backend,
                cli.CLIReportValues(argparse.Namespace(platform="linux", godot_project=directory)),
                reports.ConversionReportState(external_report_dir=str(Path(directory) / "external")),
                cli.CLIReportOperations(),
                observe,
            )
            with patch.object(backend.diagnostics, "publish_reports", publish):
                result = lifecycle.repair(ConversionOutcome(state="success"))
            self.assertEqual(result.state, "cancelled")
            self.assertEqual(publications, ["success", "cancelled"])
            self.assertEqual(observations, ["success", "cancelled", "cancelled"])
            self.assertIs(backend.diagnostics.outcome(), result)


if __name__ == "__main__":
    unittest.main()
