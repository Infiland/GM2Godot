from __future__ import annotations

import hashlib
import importlib
import inspect
import io
import json
import os
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, cast
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import cli
from src.conversion.converter import Converter
from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepLedger,
)
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_MANIFEST_RELATIVE_PATH,
)
from src.conversion.diagnostics import (
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
    DiagnosticCollector,
)
from src.conversion.godot_validation import GodotValidationReport
from src.conversion.project_godot import ConversionPreflightError
from src.version import get_version


class _OutcomeConverterStub:
    def __init__(
        self,
        outcome: ConversionOutcome,
        *,
        error: Exception | None = None,
        warning: bool = False,
        on_convert: Callable[[], None] | None = None,
    ) -> None:
        self.outcome = outcome
        self.error = error
        self.warning = warning
        self.on_convert = on_convert
        self.diagnostics = DiagnosticCollector()
        self.artifact_refreshes: list[ConversionOutcome] = []
        self.attempt_publications: list[ConversionOutcome] = []

    def convert(
        self,
        *_args: object,
        diagnostics: DiagnosticCollector | None = None,
        **_kwargs: object,
    ) -> ConversionOutcome:
        self.diagnostics = diagnostics or DiagnosticCollector()
        if self.warning:
            self.diagnostics.add(
                "warning",
                "GM2GD-TEST-WARNING",
                "Synthetic conversion warning.",
            )
        self.diagnostics.set_outcome(self.outcome)
        if self.on_convert is not None:
            self.on_convert()
        if self.error is not None:
            raise self.error
        return self.outcome

    def refresh_conversion_artifacts(
        self,
        attempt_outcome: ConversionOutcome,
    ) -> tuple[str | None, str]:
        self.artifact_refreshes.append(attempt_outcome)
        return "", ""

    def publish_conversion_attempt(
        self,
        attempt_outcome: ConversionOutcome,
    ) -> str:
        self.attempt_publications.append(attempt_outcome)
        return ""


def _success_outcome() -> ConversionOutcome:
    completed = ConversionCounts(
        requested=1,
        executed=1,
        completed=1,
    )
    steps = ConversionStepLedger.from_requested(("scripts",))
    steps = steps.start("scripts").complete("scripts")
    return ConversionOutcome(
        state="success",
        steps=steps,
        resources=completed,
    )


def _partial_outcome() -> ConversionOutcome:
    steps = ConversionStepLedger.from_requested(("scripts",))
    steps = steps.start("scripts").complete("scripts")
    return ConversionOutcome(
        state="partial",
        steps=steps,
        resources=ConversionCounts(
            requested=2,
            executed=2,
            completed=1,
            skipped=1,
        ),
    )


def _failed_outcome() -> ConversionOutcome:
    steps = ConversionStepLedger.from_requested(("scripts",))
    steps = steps.start("scripts").fail("scripts")
    return ConversionOutcome(
        state="failed",
        steps=steps,
        failed_step="scripts",
        failure_phase="converter",
    )


class TestCLIReports(unittest.TestCase):
    _STATIC_REPORT_FILENAMES = (
        "gml_manual_scope.md",
        "gml_api_compatibility.md",
        "platform_capability_report.json",
        "platform_capability_report.md",
    )

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def _write_static_report_baseline(
        self,
        report_root: str,
    ) -> dict[str, tuple[bytes, int]]:
        os.makedirs(report_root, exist_ok=True)
        baseline: dict[str, tuple[bytes, int]] = {}
        modes = (0o600, 0o640, 0o644, 0o660)
        for index, (filename, mode) in enumerate(
            zip(self._STATIC_REPORT_FILENAMES, modes, strict=True)
        ):
            content = f"previous static report {index}\n".encode()
            path = os.path.join(report_root, filename)
            with open(path, "wb") as report_file:
                report_file.write(content)
            os.chmod(path, mode)
            baseline[filename] = (content, stat.S_IMODE(os.stat(path).st_mode))
        return baseline

    def _assert_static_report_baseline(
        self,
        report_root: str,
        baseline: dict[str, tuple[bytes, int]],
    ) -> None:
        for filename, (expected_content, expected_mode) in baseline.items():
            path = os.path.join(report_root, filename)
            with open(path, "rb") as report_file:
                self.assertEqual(report_file.read(), expected_content)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), expected_mode)

    def _assert_no_static_report_transaction_debris(self, report_root: str) -> None:
        self.assertFalse(
            any(
                entry.endswith(
                    (".tmp", ".backup", ".recovery", ".tombstone")
                )
                for entry in os.listdir(report_root)
            )
        )

    def _static_report_directory_snapshot(
        self,
        report_root: str,
    ) -> dict[str, tuple[int, int, int, bytes]]:
        snapshot: dict[str, tuple[int, int, int, bytes]] = {}
        for entry in os.listdir(report_root):
            path = os.path.join(report_root, entry)
            path_stat = os.stat(path, follow_symlinks=False)
            with open(path, "rb") as report_file:
                content = report_file.read()
            snapshot[entry] = (
                path_stat.st_dev,
                path_stat.st_ino,
                stat.S_IMODE(path_stat.st_mode),
                content,
            )
        return snapshot

    def _publish_static_reports(
        self,
        report_dir: str,
        target_platform: str | None = None,
    ) -> None:
        writer = cast(
            Callable[[str, str | None], None],
            getattr(cli, "_write_static_reports"),
        )
        writer(report_dir, target_platform)

    def _convert_args(self, *extra: str) -> list[str]:
        return [
            "convert",
            "--gm-project",
            os.path.join(self.temp_dir, "gm"),
            "--godot-project",
            os.path.join(self.temp_dir, "godot"),
            *extra,
        ]

    def _run_stubbed_convert(
        self,
        converter: _OutcomeConverterStub,
        *extra: str,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("src.cli.Converter", return_value=converter),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(self._convert_args(*extra))
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _run_real_convert(
        self,
        gm_project: str,
        godot_project: str,
        *extra: str,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(
                [
                    "convert",
                    "--gm-project",
                    gm_project,
                    "--godot-project",
                    godot_project,
                    *extra,
                ]
            )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _write_outcome_reports(
        self,
        destination: str,
        outcome: ConversionOutcome,
    ) -> None:
        diagnostics = DiagnosticCollector()
        diagnostics.set_outcome(outcome)
        diagnostics.write_reports(destination)

    def _read_report_outcome_state(self, destination: str) -> str:
        with open(
            os.path.join(destination, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        outcome = report["outcome"]
        self.assertIsInstance(outcome, dict)
        return outcome["state"]

    def _read_conversion_artifact(
        self,
        destination: str,
        relative_path: str,
    ) -> dict[str, Any]:
        with open(
            os.path.join(destination, relative_path),
            "r",
            encoding="utf-8",
        ) as artifact_file:
            artifact = json.load(artifact_file)
        self.assertIsInstance(artifact, dict)
        return artifact

    def _artifact_sha256(self, destination: str, relative_path: str) -> str:
        with open(os.path.join(destination, relative_path), "rb") as artifact_file:
            return "sha256:" + hashlib.sha256(artifact_file.read()).hexdigest()

    def _write_real_script_project(self, name: str) -> tuple[str, str]:
        gm_dir = os.path.join(self.temp_dir, f"{name}-gm")
        godot_dir = os.path.join(self.temp_dir, f"{name}-godot")
        script_name = "scr_identity"
        script_dir = os.path.join(gm_dir, "scripts", script_name)
        os.makedirs(script_dir)
        source_path = f"scripts/{script_name}/{script_name}.yy"
        with open(
            os.path.join(script_dir, f"{script_name}.yy"),
            "w",
            encoding="utf-8",
        ) as metadata_file:
            json.dump(
                {
                    "name": script_name,
                    "resourceType": "GMScript",
                    "parent": {
                        "name": "Scripts",
                        "path": "folders/Scripts.yy",
                    },
                },
                metadata_file,
            )
        with open(
            os.path.join(script_dir, f"{script_name}.gml"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("return argument0;\n")
        with open(
            os.path.join(gm_dir, f"{name}.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "%Name": name,
                    "resources": [
                        {
                            "id": {
                                "name": script_name,
                                "path": source_path,
                            }
                        }
                    ],
                },
                project_file,
            )
        return gm_dir, godot_dir

    def _assert_manifest_diagnostic_hashes(self, godot_dir: str) -> None:
        with open(
            os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as manifest_file:
            manifest = json.load(manifest_file)
        generated_files = {
            entry["path"]: entry["sha256"]
            for entry in manifest["generated_files"]
        }
        for relative_path in (
            DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
            DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
        ):
            normalized_path = relative_path.replace(os.sep, "/")
            with open(os.path.join(godot_dir, relative_path), "rb") as report_file:
                expected = "sha256:" + hashlib.sha256(report_file.read()).hexdigest()
            self.assertEqual(generated_files[normalized_path], expected)

    def test_report_writes_static_and_diagnostic_reports(self) -> None:
        report_dir = os.path.join(self.temp_dir, "reports")
        report_root = os.path.join(report_dir, "gm2godot")
        os.makedirs(report_root)
        manual_path = os.path.join(report_root, "gml_manual_scope.md")
        with open(manual_path, "w", encoding="utf-8") as manual_file:
            manual_file.write("previous report\n")
        os.chmod(manual_path, 0o640)

        exit_code = cli.main(["report", "--report-dir", report_dir])

        self.assertEqual(exit_code, 0)
        self.assertTrue(os.path.isfile(os.path.join(report_root, "conversion_diagnostics.json")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "conversion_diagnostics.md")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "gml_manual_scope.md")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "gml_api_compatibility.md")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "platform_capability_report.json")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "platform_capability_report.md")))

        with open(os.path.join(report_root, "conversion_diagnostics.json"), "r", encoding="utf-8") as report_file:
            report = json.load(report_file)

        self.assertEqual(report["summary"]["total"], 0)

        with open(os.path.join(report_root, "platform_capability_report.json"), "r", encoding="utf-8") as report_file:
            capability_report = json.load(report_file)

        self.assertEqual(capability_report["issue_number"], 606)
        self.assertTrue(
            any(
                check["capability"] == "microphone"
                and "audio_start_recording" in check["apis"]
                for check in capability_report["checks"]
            )
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(manual_path).st_mode), 0o640)
            self.assertEqual(
                stat.S_IMODE(
                    os.stat(
                        os.path.join(report_root, "gml_api_compatibility.md")
                    ).st_mode
                ),
                0o600,
            )

    def test_static_report_modes_do_not_require_fchmod(self) -> None:
        report_dir = os.path.join(self.temp_dir, "no-fchmod-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        baseline = self._write_static_report_baseline(report_root)

        with (
            patch(
                "src.conversion.anchored_artifacts.os.fchmod",
                None,
                create=True,
            ),
            patch.object(DiagnosticCollector, "write_reports"),
        ):
            exit_code = cli.main(["report", "--report-dir", report_dir])

        self.assertEqual(exit_code, 0)
        if os.name != "nt":
            for filename, (_content, expected_mode) in baseline.items():
                self.assertEqual(
                    stat.S_IMODE(
                        os.stat(os.path.join(report_root, filename)).st_mode
                    ),
                    expected_mode,
                )

        new_report_dir = os.path.join(self.temp_dir, "new-no-fchmod-reports")
        with patch(
            "src.conversion.anchored_artifacts.os.fchmod",
            None,
            create=True,
        ):
            self._publish_static_reports(new_report_dir)

        new_report_root = os.path.join(new_report_dir, "gm2godot")
        for filename in self._STATIC_REPORT_FILENAMES:
            path = os.path.join(new_report_root, filename)
            self.assertTrue(os.path.isfile(path))
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are required")
    def test_new_static_report_permissions_remain_private_under_umask(self) -> None:
        report_dir = os.path.join(self.temp_dir, "private-mode-reports")
        previous_umask = os.umask(0o077)
        try:
            exit_code = cli.main(["report", "--report-dir", report_dir])
        finally:
            os.umask(previous_umask)

        self.assertEqual(exit_code, 0)
        report_root = os.path.join(report_dir, "gm2godot")
        for filename in self._STATIC_REPORT_FILENAMES:
            self.assertEqual(
                stat.S_IMODE(os.stat(os.path.join(report_root, filename)).st_mode),
                0o600,
            )

    def test_static_report_refuses_symlink_without_touching_outside_file(self) -> None:
        report_dir = os.path.join(self.temp_dir, "symlink-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        os.makedirs(report_root)
        outside_path = os.path.join(self.temp_dir, "outside-manual.md")
        with open(outside_path, "w", encoding="utf-8") as outside_file:
            outside_file.write("do not overwrite\n")
        report_path = os.path.join(report_root, "gml_manual_scope.md")
        try:
            os.symlink(outside_path, report_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symlink creation unavailable: {error}")

        with self.assertRaisesRegex(OSError, "non-regular artifact"):
            cli.main(["report", "--report-dir", report_dir])

        self.assertTrue(os.path.islink(report_path))
        with open(outside_path, "r", encoding="utf-8") as outside_file:
            self.assertEqual(outside_file.read(), "do not overwrite\n")

    def test_static_report_refuses_symlink_report_root(self) -> None:
        report_dir = os.path.join(self.temp_dir, "symlink-root-reports")
        outside_root = os.path.join(self.temp_dir, "outside-report-root")
        os.makedirs(report_dir)
        os.makedirs(outside_root)
        report_root = os.path.join(report_dir, "gm2godot")
        try:
            os.symlink(outside_root, report_root)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symlink creation unavailable: {error}")

        with self.assertRaisesRegex(OSError, "redirected"):
            cli.main(["report", "--report-dir", report_dir])

        self.assertTrue(os.path.islink(report_root))
        self.assertEqual(os.listdir(outside_root), [])

    def test_static_report_refuses_windows_junction_report_root(self) -> None:
        report_dir = os.path.join(self.temp_dir, "junction-root-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        os.makedirs(report_root)

        with patch.object(
            cli.os.path,
            "isjunction",
            return_value=True,
            create=True,
        ):
            with self.assertRaisesRegex(OSError, "redirected"):
                cli.main(["report", "--report-dir", report_dir])

        self.assertEqual(os.listdir(report_root), [])

    def test_static_report_refuses_non_directory_report_root(self) -> None:
        report_dir = os.path.join(self.temp_dir, "file-root-reports")
        os.makedirs(report_dir)
        report_root = os.path.join(report_dir, "gm2godot")
        with open(report_root, "w", encoding="utf-8") as report_root_file:
            report_root_file.write("not a report directory\n")

        with self.assertRaises(OSError):
            cli.main(["report", "--report-dir", report_dir])

        with open(report_root, "r", encoding="utf-8") as report_root_file:
            self.assertEqual(report_root_file.read(), "not a report directory\n")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_static_report_refuses_special_file_report_root(self) -> None:
        report_dir = os.path.join(self.temp_dir, "special-root-reports")
        os.makedirs(report_dir)
        report_root = os.path.join(report_dir, "gm2godot")
        os.mkfifo(report_root)

        with self.assertRaises(OSError):
            cli.main(["report", "--report-dir", report_dir])

        self.assertTrue(
            stat.S_ISFIFO(os.stat(report_root, follow_symlinks=False).st_mode)
        )

    def test_static_report_replaces_hardlink_without_mutating_other_link(self) -> None:
        report_dir = os.path.join(self.temp_dir, "hardlink-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        os.makedirs(report_root)
        outside_path = os.path.join(self.temp_dir, "outside-api.md")
        with open(outside_path, "w", encoding="utf-8") as outside_file:
            outside_file.write("shared bytes must survive\n")
        report_path = os.path.join(report_root, "gml_api_compatibility.md")
        os.link(outside_path, report_path)
        outside_inode = os.stat(outside_path).st_ino

        exit_code = cli.main(["report", "--report-dir", report_dir])

        self.assertEqual(exit_code, 0)
        with open(outside_path, "r", encoding="utf-8") as outside_file:
            self.assertEqual(outside_file.read(), "shared bytes must survive\n")
        with open(report_path, "r", encoding="utf-8") as report_file:
            self.assertIn("GML API Compatibility", report_file.read())
        self.assertNotEqual(os.stat(report_path).st_ino, outside_inode)

    def test_static_report_refuses_non_regular_target_before_publication(self) -> None:
        report_dir = os.path.join(self.temp_dir, "non-regular-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        non_regular_path = os.path.join(
            report_root,
            "gml_api_compatibility.md",
        )
        os.makedirs(non_regular_path)

        with self.assertRaisesRegex(OSError, "non-regular artifact"):
            cli.main(["report", "--report-dir", report_dir])

        self.assertTrue(os.path.isdir(non_regular_path))
        self.assertEqual(os.listdir(report_root), ["gml_api_compatibility.md"])

    def test_static_report_renderer_failure_preserves_previous_set(self) -> None:
        report_dir = os.path.join(self.temp_dir, "render-failure-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        baseline = self._write_static_report_baseline(report_root)

        with patch(
            "src.cli._render_api_compatibility_markdown",
            side_effect=OSError("static report rendering failed"),
        ):
            with self.assertRaisesRegex(OSError, "static report rendering failed"):
                cli.main(["report", "--report-dir", report_dir])

        self._assert_static_report_baseline(report_root, baseline)
        self._assert_no_static_report_transaction_debris(report_root)

    def test_static_report_staging_failure_preserves_previous_set_and_cleans_temps(
        self,
    ) -> None:
        report_dir = os.path.join(self.temp_dir, "stage-failure-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        baseline = self._write_static_report_baseline(report_root)

        def fail_second_stage(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            if (
                phase == "before_stage"
                and name == self._STATIC_REPORT_FILENAMES[1]
            ):
                raise OSError("static report staging failed")

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=fail_second_stage,
        ):
            with self.assertRaisesRegex(OSError, "static report staging failed"):
                self._publish_static_reports(report_dir)

        self._assert_static_report_baseline(report_root, baseline)
        self._assert_no_static_report_transaction_debris(report_root)

    def test_static_report_commit_failure_restores_previous_set_and_modes(
        self,
    ) -> None:
        report_dir = os.path.join(self.temp_dir, "commit-failure-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        baseline = self._write_static_report_baseline(report_root)

        def fail_second_commit(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            if (
                phase == "before_commit"
                and name == self._STATIC_REPORT_FILENAMES[1]
            ):
                raise OSError("static report commit failed")

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=fail_second_commit,
        ):
            with self.assertRaisesRegex(OSError, "static report commit failed"):
                self._publish_static_reports(report_dir)

        self._assert_static_report_baseline(report_root, baseline)
        self._assert_no_static_report_transaction_debris(report_root)

    def test_static_report_sync_failure_restores_previous_set(self) -> None:
        report_dir = os.path.join(self.temp_dir, "sync-failure-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        baseline = self._write_static_report_baseline(report_root)

        def fail_second_sync(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            if phase == (
                "before_commit_"
                f"{self._STATIC_REPORT_FILENAMES[1]}_durability"
            ):
                raise OSError("static report sync failed")

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=fail_second_sync,
        ):
            with self.assertRaisesRegex(OSError, "static report sync failed"):
                self._publish_static_reports(report_dir)

        self._assert_static_report_baseline(report_root, baseline)
        self._assert_no_static_report_transaction_debris(report_root)

    def test_static_report_interrupt_after_commit_restores_previous_set(
        self,
    ) -> None:
        report_dir = os.path.join(self.temp_dir, "commit-interrupt-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        baseline = self._write_static_report_baseline(report_root)
        interrupted = False

        def interrupt_after_commit(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal interrupted
            if (
                not interrupted
                and phase == "after_commit"
                and name == self._STATIC_REPORT_FILENAMES[0]
            ):
                interrupted = True
                raise KeyboardInterrupt

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=interrupt_after_commit,
        ):
            with self.assertRaises(KeyboardInterrupt):
                self._publish_static_reports(report_dir)

        self._assert_static_report_baseline(report_root, baseline)
        self._assert_no_static_report_transaction_debris(report_root)

    def test_static_report_final_validation_failure_restores_previous_set(
        self,
    ) -> None:
        report_dir = os.path.join(self.temp_dir, "validation-failure-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        baseline = self._write_static_report_baseline(report_root)
        real_receipt = cli.ByteArtifactTransaction.receipt

        def fail_last_receipt(
            transaction: Any,
            name: str,
            staged: Any,
        ) -> Any:
            if name == self._STATIC_REPORT_FILENAMES[-1]:
                raise OSError("static report final validation failed")
            return real_receipt(transaction, name, staged)

        with patch.object(
            cli.ByteArtifactTransaction,
            "receipt",
            new=fail_last_receipt,
        ):
            with self.assertRaisesRegex(
                OSError,
                "static report final validation failed",
            ):
                self._publish_static_reports(report_dir)

        self._assert_static_report_baseline(report_root, baseline)
        self._assert_no_static_report_transaction_debris(report_root)

    def test_static_reports_commit_and_sync_in_declared_order(self) -> None:
        report_dir = os.path.join(self.temp_dir, "ordered-reports")
        commits: list[str] = []
        durability: list[str] = []

        def record_order(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            if phase == "before_commit" and name is not None:
                commits.append(name)
            if phase == "before_durability" and name is not None:
                durability.append(name)

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=record_order,
        ):
            self._publish_static_reports(report_dir)

        self.assertEqual(commits, list(self._STATIC_REPORT_FILENAMES))
        self.assertEqual(durability, list(self._STATIC_REPORT_FILENAMES))

    def test_static_report_refuses_linked_baseline_without_mutating_referents(
        self,
    ) -> None:
        report_dir = os.path.join(self.temp_dir, "linked-failure-reports")
        report_root = os.path.join(report_dir, "gm2godot")
        os.makedirs(report_root)
        symlink_referent = os.path.join(self.temp_dir, "outside-static-symlink.md")
        hardlink_referent = os.path.join(self.temp_dir, "outside-static-hardlink.md")
        with open(symlink_referent, "w", encoding="utf-8") as outside_file:
            outside_file.write("symlink sentinel\n")
        with open(hardlink_referent, "w", encoding="utf-8") as outside_file:
            outside_file.write("hardlink sentinel\n")
        try:
            os.symlink(
                symlink_referent,
                os.path.join(report_root, self._STATIC_REPORT_FILENAMES[0]),
            )
            os.link(
                hardlink_referent,
                os.path.join(report_root, self._STATIC_REPORT_FILENAMES[1]),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"File links are unavailable: {error}")
        for filename in self._STATIC_REPORT_FILENAMES[2:]:
            with open(
                os.path.join(report_root, filename),
                "w",
                encoding="utf-8",
            ) as report_file:
                report_file.write("old report\n")

        with self.assertRaisesRegex(OSError, "non-regular artifact"):
            self._publish_static_reports(report_dir)

        self.assertTrue(
            os.path.islink(
                os.path.join(report_root, self._STATIC_REPORT_FILENAMES[0])
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(report_root, self._STATIC_REPORT_FILENAMES[1])
            )
        )
        with open(symlink_referent, "r", encoding="utf-8") as outside_file:
            self.assertEqual(outside_file.read(), "symlink sentinel\n")
        with open(hardlink_referent, "r", encoding="utf-8") as outside_file:
            self.assertEqual(outside_file.read(), "hardlink sentinel\n")

    @unittest.skipUnless(os.name == "posix", "POSIX directory relocation required")
    def test_static_reports_never_mutate_physical_replacement_at_each_phase(
        self,
    ) -> None:
        per_target_phases = (
            "before_stage",
            "before_backup",
            "before_commit",
            "before_durability",
        )
        cases = tuple(
            (phase, filename)
            for phase in per_target_phases
            for filename in self._STATIC_REPORT_FILENAMES
        ) + (
            ("before_sync", None),
            ("before_cleanup", None),
        )

        for index, (selected_phase, selected_name) in enumerate(cases):
            with self.subTest(phase=selected_phase, name=selected_name):
                report_dir = os.path.join(
                    self.temp_dir,
                    f"physical-replacement-{index}",
                )
                report_root = os.path.join(report_dir, "gm2godot")
                parked_root = os.path.join(report_dir, "gm2godot.parked")
                self._write_static_report_baseline(report_root)
                swapped = False
                replacement_before: dict[
                    str,
                    tuple[int, int, int, bytes],
                ] = {}

                def replace_report_directory(
                    phase: str,
                    directory_path: str,
                    name: str | None,
                ) -> None:
                    nonlocal swapped, replacement_before
                    if (
                        swapped
                        or phase != selected_phase
                        or name != selected_name
                        or os.path.abspath(directory_path)
                        != os.path.abspath(report_root)
                    ):
                        return
                    swapped = True
                    os.rename(report_root, parked_root)
                    os.makedirs(report_root)
                    for filename in self._STATIC_REPORT_FILENAMES:
                        with open(
                            os.path.join(report_root, filename),
                            "wb",
                        ) as replacement_file:
                            replacement_file.write(
                                f"replacement {filename}\n".encode()
                            )
                    with open(
                        os.path.join(report_root, "unrelated-sentinel.txt"),
                        "wb",
                    ) as sentinel_file:
                        sentinel_file.write(b"do not mutate\n")
                    with open(
                        os.path.join(
                            report_root,
                            ".gml_manual_scope.md.collision.backup",
                        ),
                        "wb",
                    ) as collision_file:
                        collision_file.write(b"collision\n")
                    replacement_before = self._static_report_directory_snapshot(
                        report_root
                    )

                with (
                    patch(
                        "src.conversion.anchored_artifacts."
                        "_before_anchored_artifact_phase",
                        side_effect=replace_report_directory,
                    ),
                    self.assertRaises(OSError),
                ):
                    self._publish_static_reports(report_dir)

                self.assertTrue(swapped)
                self.assertEqual(
                    self._static_report_directory_snapshot(report_root),
                    replacement_before,
                )

    @unittest.skipUnless(os.name == "posix", "POSIX directory relocation required")
    def test_static_report_rollback_stays_bound_after_physical_replacement(
        self,
    ) -> None:
        report_dir = os.path.join(self.temp_dir, "rollback-replacement")
        report_root = os.path.join(report_dir, "gm2godot")
        parked_root = os.path.join(report_dir, "gm2godot.parked")
        self._write_static_report_baseline(report_root)
        publication_failed = False
        swapped = False
        replacement_before: dict[str, tuple[int, int, int, bytes]] = {}

        def fail_then_replace_for_rollback(
            phase: str,
            directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal publication_failed, swapped, replacement_before
            if (
                not publication_failed
                and phase == "after_commit"
                and name == self._STATIC_REPORT_FILENAMES[1]
            ):
                publication_failed = True
                raise OSError("static report post-commit failure")
            if (
                not publication_failed
                or swapped
                or phase != "before_rollback"
                or os.path.abspath(directory_path)
                != os.path.abspath(report_root)
            ):
                return
            swapped = True
            os.rename(report_root, parked_root)
            os.makedirs(report_root)
            for filename in self._STATIC_REPORT_FILENAMES:
                with open(
                    os.path.join(report_root, filename),
                    "wb",
                ) as replacement_file:
                    replacement_file.write(
                        f"rollback replacement {filename}\n".encode()
                    )
            with open(
                os.path.join(report_root, "unrelated-sentinel.txt"),
                "wb",
            ) as sentinel_file:
                sentinel_file.write(b"do not mutate\n")
            replacement_before = self._static_report_directory_snapshot(
                report_root
            )

        with (
            patch(
                "src.conversion.anchored_artifacts."
                "_before_anchored_artifact_phase",
                side_effect=fail_then_replace_for_rollback,
            ),
            self.assertRaisesRegex(
                OSError,
                "static report post-commit failure",
            ) as raised,
        ):
            self._publish_static_reports(report_dir)

        self.assertTrue(swapped)
        self.assertEqual(
            self._static_report_directory_snapshot(report_root),
            replacement_before,
        )
        self.assertTrue(
            any(
                "verified recovery artifact preserved" in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )

    @unittest.skipUnless(os.name == "nt", "native Windows handles required")
    def test_static_report_windows_binding_blocks_directory_relocation(self) -> None:
        report_dir = os.path.join(self.temp_dir, "windows-binding")
        report_root = os.path.join(report_dir, "gm2godot")
        parked_root = os.path.join(report_dir, "gm2godot.parked")
        self._write_static_report_baseline(report_root)
        relocation_checked = False

        def attempt_relocation(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal relocation_checked
            if (
                relocation_checked
                or phase != "before_stage"
                or name != self._STATIC_REPORT_FILENAMES[0]
            ):
                return
            relocation_checked = True
            with self.assertRaises(OSError):
                os.rename(report_root, parked_root)

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=attempt_relocation,
        ):
            self._publish_static_reports(report_dir)

        self.assertTrue(relocation_checked)
        self.assertFalse(os.path.exists(parked_root))
        for filename in self._STATIC_REPORT_FILENAMES:
            self.assertTrue(os.path.isfile(os.path.join(report_root, filename)))

    def test_version_flag_prints_current_version(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = cli.main(["--version"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), f"GM2Godot {get_version()}")

    def test_list_converters_writes_text_inventory(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = cli.main(["list-converters"])

        inventory = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Default groups: assets, project, wip", inventory)
        self.assertIn("Conversion groups:", inventory)
        self.assertIn("Converter keys:", inventory)
        self.assertIn("  assets: sprites, fonts, sounds", inventory)
        self.assertIn("  asset_registry", inventory)

    def test_list_converters_writes_json_inventory(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = cli.main(["list-converters", "--format", "json"])

        inventory = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(inventory["default_groups"], ["assets", "project", "wip"])
        self.assertIn("sprites", inventory["groups"]["assets"])
        self.assertIn("project_settings", inventory["groups"]["project"])
        self.assertNotIn("sound_group_folders", inventory["groups"]["assets"])
        self.assertNotIn("sound_group_folders", inventory["converter_keys"])

    def test_sound_group_folder_modifier_is_rejected_as_only_converter(self) -> None:
        godot_dir = os.path.join(self.temp_dir, "modifier-only-godot")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "convert",
                "--gm-project",
                os.path.join(self.temp_dir, "modifier-only-gm"),
                "--godot-project",
                godot_dir,
                "--only",
                "sound_group_folders",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr.strip(),
            "Unknown converter key for --only: sound_group_folders",
        )
        self.assertFalse(os.path.exists(godot_dir))

    def test_module_entrypoint_prints_version(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--version"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"GM2Godot {get_version()}")

    def test_app_entrypoint_routes_global_cli_flags(self) -> None:
        app_entrypoint = importlib.import_module("main")

        with (
            patch.object(sys, "argv", ["main.py", "--version"]),
            patch("src.cli.main", return_value=0) as cli_main,
            self.assertRaises(SystemExit) as context,
        ):
            app_entrypoint.main()

        self.assertEqual(context.exception.code, 0)
        cli_main.assert_called_once_with(["--version"])

    def test_analyze_only_writes_platform_diagnostic_without_conversion_output(self) -> None:
        gm_dir = os.path.join(self.temp_dir, "gm")
        report_dir = os.path.join(self.temp_dir, "reports")
        os.makedirs(gm_dir)

        exit_code = cli.main([
            "analyze",
            "--gm-project",
            gm_dir,
            "--report-dir",
            report_dir,
            "--target-platform",
            "linux",
            "--max-warnings",
            "0",
        ])

        self.assertEqual(exit_code, 2)
        self.assertFalse(os.path.exists(os.path.join(gm_dir, "project.godot")))

        with open(os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH), "r", encoding="utf-8") as report_file:
            report = json.load(report_file)

        codes = [diagnostic["code"] for diagnostic in report["diagnostics"]]
        self.assertIn("GM2GD-CLI-TARGET-PLATFORM", codes)
        self.assertIn("GM2GD-ANALYZE-MISSING-YYP", codes)
        self.assertTrue(any("linux" in diagnostic["message"] for diagnostic in report["diagnostics"]))
        with open(
            os.path.join(report_dir, "gm2godot", "platform_capability_report.json"),
            "r",
            encoding="utf-8",
        ) as capability_file:
            capability_report = json.load(capability_file)
        self.assertEqual(capability_report["selected_target"], "linux")

    def test_validate_applies_thresholds_to_existing_diagnostics_report(self) -> None:
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_root = os.path.join(godot_dir, "gm2godot")
        os.makedirs(report_root)
        with open(os.path.join(godot_dir, "project.godot"), "w", encoding="utf-8") as project_file:
            project_file.write('[application]\nconfig/name="Demo"\n')
        with open(os.path.join(godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH), "w", encoding="utf-8") as report_file:
            json.dump(
                {
                    "summary": {"info": 0, "warning": 1, "error": 0, "total": 1},
                    "diagnostics": [
                        {
                            "severity": "warning",
                            "code": "GM2GD-GML-UNSUPPORTED",
                            "message": "Unsupported GML API: show_message_async",
                            "api": "show_message_async",
                        }
                    ],
                },
                report_file,
            )

        exit_code = cli.main(["validate", "--godot-project", godot_dir, "--fail-on-unsupported"])

        self.assertEqual(exit_code, 2)

    def test_validate_passes_boot_frame_count_to_godot_validation(self) -> None:
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_root = os.path.join(godot_dir, "gm2godot")
        os.makedirs(report_root)
        with open(os.path.join(godot_dir, "project.godot"), "w", encoding="utf-8") as project_file:
            project_file.write('[application]\nconfig/name="Demo"\n')
        with open(os.path.join(godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH), "w", encoding="utf-8") as report_file:
            json.dump(
                {"summary": {"info": 0, "warning": 0, "error": 0, "total": 0}, "diagnostics": []},
                report_file,
            )

        validation_report = GodotValidationReport(
            status="passed",
            godot_binary="/tmp/fake-godot",
            project_path=godot_dir,
            resource_paths=(),
            message="Headless Godot boot ran the project main scene for 5 frame(s).",
            boot_frames=5,
        )
        with (
            patch("src.cli.validate_generated_godot_project", return_value=validation_report) as validate_project,
            patch("src.cli.write_godot_validation_report") as write_report,
        ):
            exit_code = cli.main([
                "validate",
                "--godot-project",
                godot_dir,
                "--godot-bin",
                "/tmp/fake-godot",
                "--godot-boot-frames",
                "5",
            ])

        self.assertEqual(exit_code, 0)
        validate_project.assert_called_once_with(
            godot_dir,
            godot_binary="/tmp/fake-godot",
            boot_frames=5,
        )
        write_report.assert_called_once_with(godot_dir, validation_report)

    def test_convert_can_write_selected_reports_and_fail_warning_threshold(self) -> None:
        gm_dir = os.path.join(self.temp_dir, "gm")
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_dir = os.path.join(self.temp_dir, "reports")
        os.makedirs(gm_dir)
        os.makedirs(godot_dir)
        with open(os.path.join(gm_dir, "Bad.yyp"), "w", encoding="utf-8") as yyp_file:
            yyp_file.write('{"resources": [}')
        with open(os.path.join(godot_dir, "project.godot"), "w", encoding="utf-8") as project_file:
            project_file.write('[application]\nconfig/name="Demo"\n')

        report_destinations: list[str] = []
        original_publish_reports = DiagnosticCollector.publish_reports

        def track_report_write(
            diagnostics: DiagnosticCollector,
            destination: str | os.PathLike[str],
        ) -> object:
            report_destinations.append(os.fspath(destination))
            return original_publish_reports(diagnostics, destination)

        with patch.object(DiagnosticCollector, "publish_reports", track_report_write):
            exit_code = cli.main([
                "convert",
                "--gm-project",
                gm_dir,
                "--godot-project",
                godot_dir,
                "--only",
                "asset_registry",
                "--report-dir",
                report_dir,
                "--max-warnings",
                "0",
            ])

        self.assertEqual(exit_code, 2)
        self.assertTrue(os.path.isfile(os.path.join(godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)))
        self.assertTrue(os.path.isfile(os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)))

        with open(os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH), "r", encoding="utf-8") as report_file:
            report = json.load(report_file)

        codes = [diagnostic["code"] for diagnostic in report["diagnostics"]]
        self.assertIn("GM2GD-WARNING", codes)
        self.assertIn("GM2GD-CLI-TARGET-PLATFORM", codes)
        self.assertEqual(codes.count("GM2GD-CLI-TARGET-PLATFORM"), 1)
        self.assertEqual(report_destinations, [godot_dir, report_dir])

    def test_convert_success_prints_one_summary_and_writes_outcome_report(
        self,
    ) -> None:
        outcome = _success_outcome()
        report_dir = os.path.join(self.temp_dir, "success-report")

        exit_code, stdout, stderr = self._run_stubbed_convert(
            _OutcomeConverterStub(outcome),
            "--report-dir",
            report_dir,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertEqual(stdout.strip(), outcome.summary_line())
        with open(
            os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        self.assertEqual(report["outcome"], outcome.to_dict())
        static_report_root = os.path.join(report_dir, "gm2godot")
        for filename in self._STATIC_REPORT_FILENAMES:
            self.assertTrue(os.path.isfile(os.path.join(static_report_root, filename)))

    def test_convert_static_report_commit_failure_cleans_temp_and_fails_outcome(
        self,
    ) -> None:
        outcome = _success_outcome()
        report_dir = os.path.join(self.temp_dir, "static-commit-failure")
        report_root = os.path.join(report_dir, "gm2godot")

        def fail_static_commit(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            if (
                phase == "before_commit"
                and name == self._STATIC_REPORT_FILENAMES[1]
            ):
                raise OSError("static report commit failed")

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=fail_static_commit,
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                _OutcomeConverterStub(outcome),
                "--report-dir",
                report_dir,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertIn("static report commit failed", stderr)
        for filename in self._STATIC_REPORT_FILENAMES:
            self.assertFalse(os.path.lexists(os.path.join(report_root, filename)))
        self.assertFalse(
            any(
                entry.endswith((".tmp", ".backup"))
                for entry in os.listdir(report_root)
            )
        )

    def test_external_report_failure_returns_failed_outcome(self) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)

        with patch(
            "src.cli._write_external_conversion_reports",
            side_effect=OSError("report disk full"),
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                os.path.join(self.temp_dir, "failed-report"),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertNotIn("GM2Godot conversion outcome: success", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot external report generation failed: report disk full\n",
        )
        failed_outcome = converter.diagnostics.outcome()
        self.assertIsNotNone(failed_outcome)
        assert failed_outcome is not None
        self.assertEqual(failed_outcome.state, "failed")
        self.assertEqual(failed_outcome.failed_step, "external_reports")
        self.assertEqual(failed_outcome.failure_phase, "report")
        self.assertEqual(failed_outcome.converters, outcome.converters)
        self.assertEqual(failed_outcome.resources, outcome.resources)
        self.assertEqual(converter.artifact_refreshes, [failed_outcome])
        self.assertEqual(converter.attempt_publications, [])

    def test_external_report_failure_repairs_published_success_json(self) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_dir = os.path.join(self.temp_dir, "stale-success-report")
        self._write_outcome_reports(godot_dir, outcome)

        def publish_success_then_fail(
            destination: str | None,
            _target_platform: str,
            diagnostics: DiagnosticCollector,
        ) -> None:
            assert destination is not None
            diagnostics.write_reports(destination)
            raise OSError("failed after publishing success JSON")

        with patch(
            "src.cli._write_external_conversion_reports",
            side_effect=publish_success_then_fail,
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot external report generation failed: "
            "failed after publishing success JSON\n",
        )
        self.assertEqual(self._read_report_outcome_state(godot_dir), "failed")
        self.assertEqual(self._read_report_outcome_state(report_dir), "failed")
        self.assertEqual(len(converter.artifact_refreshes), 1)
        self.assertEqual(converter.artifact_refreshes[0].state, "failed")
        self.assertEqual(converter.attempt_publications, [])

    def test_real_external_report_failure_refreshes_canonical_manifest_hashes(
        self,
    ) -> None:
        gm_dir, godot_dir = self._write_real_script_project("LateReportFailure")
        report_dir = os.path.join(self.temp_dir, "late-report-failure")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "src.cli._write_external_conversion_reports",
                side_effect=OSError("report disk full"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                [
                    "convert",
                    "--gm-project",
                    gm_dir,
                    "--godot-project",
                    godot_dir,
                    "--only",
                    "scripts",
                    "--report-dir",
                    report_dir,
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue().count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout.getvalue())
        self.assertIn("external report generation failed", stderr.getvalue())
        self.assertEqual(self._read_report_outcome_state(godot_dir), "failed")
        self.assertEqual(self._read_report_outcome_state(report_dir), "failed")
        self._assert_manifest_diagnostic_hashes(godot_dir)
        manifest = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        )
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(manifest["conversion"]["state"], "success")
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertEqual(attempt["attempt"]["failed_step"], "external_reports")
        self.assertEqual(attempt["canonical_manifest"]["status"], "updated")
        self.assertTrue(attempt["canonical_manifest"]["updated"])
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "verified",
        )
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            self._artifact_sha256(
                godot_dir,
                CONVERSION_MANIFEST_RELATIVE_PATH,
            ),
        )

    def test_real_canonical_report_dir_refreshes_static_report_manifest_hashes(
        self,
    ) -> None:
        gm_dir, godot_dir = self._write_real_script_project("CanonicalReports")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(
                [
                    "convert",
                    "--gm-project",
                    gm_dir,
                    "--godot-project",
                    godot_dir,
                    "--only",
                    "scripts",
                    "--report-dir",
                    godot_dir,
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("GM2Godot conversion outcome: success", stdout.getvalue())
        manifest = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        )
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(manifest["format_version"], 2)
        generated_files = {
            entry["path"]: entry["sha256"]
            for entry in manifest["generated_files"]
        }
        for filename in self._STATIC_REPORT_FILENAMES:
            relative_path = f"gm2godot/{filename}"
            with self.subTest(relative_path=relative_path):
                self.assertEqual(
                    generated_files[relative_path],
                    self._artifact_sha256(godot_dir, relative_path),
                )
        self.assertEqual(attempt["attempt"]["state"], "success")
        self.assertEqual(attempt["canonical_manifest"]["status"], "updated")
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            self._artifact_sha256(
                godot_dir,
                CONVERSION_MANIFEST_RELATIVE_PATH,
            ),
        )

    def test_real_nested_report_dir_stays_outside_managed_inventory(
        self,
    ) -> None:
        gm_dir, godot_dir = self._write_real_script_project("NestedReports")
        report_dir = os.path.join(godot_dir, "reports")

        exit_code, stdout, stderr = self._run_real_convert(
            gm_dir,
            godot_dir,
            "--only",
            "scripts",
            "--report-dir",
            report_dir,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("GM2Godot conversion outcome: success", stdout)
        manifest = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        )
        generated_files = {
            entry["path"]: entry["sha256"]
            for entry in manifest["generated_files"]
        }
        inventory_paths = {
            entry["path"]
            for entry in manifest["generation_inventory"]["entries"]
        }
        external_report_paths = (
            *(f"reports/gm2godot/{name}" for name in self._STATIC_REPORT_FILENAMES),
            "reports/" + DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH.replace(os.sep, "/"),
            "reports/"
            + DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH.replace(os.sep, "/"),
        )
        for relative_path in external_report_paths:
            with self.subTest(relative_path=relative_path):
                self.assertNotIn(relative_path, generated_files)
                self.assertNotIn(relative_path, inventory_paths)
                self.assertTrue(os.path.isfile(os.path.join(godot_dir, relative_path)))

    def test_nested_managed_report_repair_failure_is_terminal(self) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "NestedReportRepairFailure"
        )
        report_dir = os.path.join(godot_dir, "reports")
        original_publish_reports = DiagnosticCollector.publish_reports
        nested_publications = 0

        def fail_second_nested_publication(
            diagnostics: DiagnosticCollector,
            destination: str | os.PathLike[str],
        ) -> object:
            nonlocal nested_publications
            if (
                os.path.realpath(os.fspath(destination))
                == os.path.realpath(report_dir)
            ):
                nested_publications += 1
                if nested_publications == 2:
                    raise OSError("nested report disk full")
            return original_publish_reports(diagnostics, destination)

        with patch.object(
            DiagnosticCollector,
            "publish_reports",
            fail_second_nested_publication,
        ):
            exit_code, stdout, stderr = self._run_real_convert(
                gm_dir,
                godot_dir,
                "--only",
                "scripts",
                "--report-dir",
                report_dir,
            )

        self.assertEqual(nested_publications, 2)
        self.assertEqual(exit_code, 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot conversion report repair failed: "
            "nested report disk full\n",
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    report_dir,
                    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
                )
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    report_dir,
                    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
                )
            )
        )
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertEqual(
            attempt["attempt"]["failed_step"],
            "conversion_diagnostics",
        )
        self.assertEqual(
            attempt["attempt"]["failure_phase"],
            "finalizer",
        )
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertFalse(attempt["canonical_manifest"]["updated"])
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "unverified",
        )
        self._assert_manifest_diagnostic_hashes(godot_dir)

    def test_nested_managed_diagnostics_restore_after_late_refresh_failure(
        self,
    ) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "NestedReportRestoration"
        )
        report_dir = os.path.join(godot_dir, "reports")
        original_refresh = Converter.refresh_conversion_artifacts
        refresh_calls = 0
        manifest_before_failure: bytes | None = None

        def interrupt_then_fail_refresh(
            converter: Converter,
            attempt_outcome: ConversionOutcome,
        ) -> tuple[str | None, str]:
            nonlocal manifest_before_failure, refresh_calls
            refresh_calls += 1
            if refresh_calls == 3:
                raise OSError("cancelled nested refresh failed")
            result = original_refresh(converter, attempt_outcome)
            if refresh_calls == 2:
                with open(
                    os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
                    "rb",
                ) as manifest_file:
                    manifest_before_failure = manifest_file.read()
                signal.raise_signal(signal.SIGINT)
            return result

        with patch.object(
            Converter,
            "refresh_conversion_artifacts",
            interrupt_then_fail_refresh,
        ):
            exit_code, stdout, stderr = self._run_real_convert(
                gm_dir,
                godot_dir,
                "--only",
                "scripts",
                "--report-dir",
                report_dir,
            )

        self.assertEqual(refresh_calls, 3)
        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr, "")
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertIsNotNone(manifest_before_failure)
        manifest_path = os.path.join(
            godot_dir,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        )
        with open(manifest_path, "rb") as manifest_file:
            self.assertEqual(manifest_file.read(), manifest_before_failure)
        manifest = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        )
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "cancelled")
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        generated_files = {
            entry["path"]: entry["sha256"]
            for entry in manifest["generated_files"]
        }
        managed_diagnostics = (
            DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH.replace(os.sep, "/"),
            DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH.replace(os.sep, "/"),
        )
        external_diagnostics = (
            "reports/" + DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH.replace(os.sep, "/"),
            "reports/"
            + DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH.replace(os.sep, "/"),
        )
        for relative_path in managed_diagnostics:
            with self.subTest(relative_path=relative_path):
                self.assertEqual(
                    generated_files[relative_path],
                    self._artifact_sha256(godot_dir, relative_path),
                )
        for relative_path in external_diagnostics:
            with self.subTest(relative_path=relative_path):
                self.assertNotIn(relative_path, generated_files)
                self.assertTrue(os.path.isfile(os.path.join(godot_dir, relative_path)))

    def test_managed_report_symlink_alias_restores_after_cancelled_refresh_failure(
        self,
    ) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "AliasedReportRestoration"
        )
        os.makedirs(godot_dir)
        report_alias = os.path.join(self.temp_dir, "aliased-godot-reports")
        try:
            os.symlink(godot_dir, report_alias, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Directory symlink creation unavailable: {error}")

        original_external_write = getattr(
            cli,
            "_write_external_conversion_reports",
        )
        original_refresh = Converter.refresh_conversion_artifacts
        refresh_calls = 0

        def interrupt_after_external_write(
            destination: str | None,
            target_platform: str,
            diagnostics: DiagnosticCollector,
        ) -> object:
            receipt = original_external_write(
                destination,
                target_platform,
                diagnostics,
            )
            signal.raise_signal(signal.SIGINT)
            return receipt

        def fail_cancelled_refresh(
            converter: Converter,
            attempt_outcome: ConversionOutcome,
        ) -> tuple[str | None, str]:
            nonlocal refresh_calls
            refresh_calls += 1
            if refresh_calls == 2:
                raise OSError("cancelled aliased refresh failed")
            return original_refresh(converter, attempt_outcome)

        with (
            patch(
                "src.cli._write_external_conversion_reports",
                side_effect=interrupt_after_external_write,
            ),
            patch.object(
                Converter,
                "refresh_conversion_artifacts",
                fail_cancelled_refresh,
            ),
        ):
            exit_code, stdout, stderr = self._run_real_convert(
                gm_dir,
                godot_dir,
                "--only",
                "scripts",
                "--report-dir",
                report_alias,
            )

        self.assertEqual(refresh_calls, 2)
        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr, "")
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertEqual(self._read_report_outcome_state(godot_dir), "success")
        self._assert_manifest_diagnostic_hashes(godot_dir)
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "cancelled")
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "unverified",
        )

    def test_real_late_canonical_report_repair_failure_is_terminal(self) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "LateCanonicalReportRepairFailure"
        )
        original_publish_reports = DiagnosticCollector.publish_reports
        canonical_write_calls = 0

        def fail_first_late_canonical_repair(
            diagnostics: DiagnosticCollector,
            destination: str | os.PathLike[str],
        ) -> object:
            nonlocal canonical_write_calls
            if os.path.realpath(os.fspath(destination)) == os.path.realpath(godot_dir):
                canonical_write_calls += 1
                if canonical_write_calls == 3:
                    raise OSError("late canonical report disk full")
            return original_publish_reports(diagnostics, destination)

        with patch.object(
            DiagnosticCollector,
            "publish_reports",
            fail_first_late_canonical_repair,
        ):
            exit_code, stdout, stderr = self._run_real_convert(
                gm_dir,
                godot_dir,
                "--only",
                "scripts",
                "--report-dir",
                godot_dir,
            )

        self.assertEqual(canonical_write_calls, 3)
        self.assertEqual(exit_code, 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot conversion report repair failed: "
            "late canonical report disk full\n",
        )
        manifest = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        )
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(manifest["conversion"]["state"], "success")
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertEqual(
            attempt["attempt"]["failed_step"],
            "conversion_diagnostics",
        )
        self.assertEqual(attempt["attempt"]["failure_phase"], "finalizer")
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertFalse(attempt["canonical_manifest"]["updated"])
        self._assert_manifest_diagnostic_hashes(godot_dir)
        generated_files = {
            entry["path"]: entry["sha256"]
            for entry in manifest["generated_files"]
        }
        for filename in self._STATIC_REPORT_FILENAMES:
            relative_path = f"gm2godot/{filename}"
            with self.subTest(relative_path=relative_path):
                self.assertNotIn(relative_path, generated_files)

    def test_real_successful_late_artifact_refresh_failure_is_terminal(
        self,
    ) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "LateArtifactFailure"
        )
        original_refresh = Converter.refresh_conversion_artifacts
        refresh_calls = 0
        manifest_before: bytes | None = None

        def fail_second_refresh(
            converter: Converter,
            attempt_outcome: ConversionOutcome,
        ) -> tuple[str | None, str]:
            nonlocal manifest_before, refresh_calls
            refresh_calls += 1
            if refresh_calls == 2:
                with open(
                    os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
                    "rb",
                ) as manifest_file:
                    manifest_before = manifest_file.read()
                raise OSError("late artifact disk full")
            return original_refresh(converter, attempt_outcome)

        with patch.object(
            Converter,
            "refresh_conversion_artifacts",
            fail_second_refresh,
        ):
            exit_code, stdout, stderr = self._run_real_convert(
                gm_dir,
                godot_dir,
                "--only",
                "scripts",
                "--report-dir",
                godot_dir,
            )

        self.assertEqual(refresh_calls, 2)
        self.assertEqual(exit_code, 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot conversion artifact publication failed: "
            "late artifact disk full\n",
        )
        self.assertIsNotNone(manifest_before)
        with open(
            os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
            "rb",
        ) as manifest_file:
            self.assertEqual(manifest_file.read(), manifest_before)
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertEqual(
            attempt["attempt"]["failed_step"],
            "conversion_artifacts",
        )
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertFalse(attempt["canonical_manifest"]["updated"])
        self._assert_manifest_diagnostic_hashes(godot_dir)

    def test_real_failed_terminal_attempt_publication_is_reported(self) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "TerminalAttemptPublicationFailure"
        )
        original_refresh = Converter.refresh_conversion_artifacts
        refresh_calls = 0
        attempt_publication_calls = 0

        def fail_second_refresh(
            converter: Converter,
            attempt_outcome: ConversionOutcome,
        ) -> tuple[str | None, str]:
            nonlocal refresh_calls
            refresh_calls += 1
            if refresh_calls == 2:
                raise OSError("late artifact disk full")
            return original_refresh(converter, attempt_outcome)

        def fail_terminal_attempt_publication(
            _converter: Converter,
            _attempt_outcome: ConversionOutcome,
        ) -> str:
            nonlocal attempt_publication_calls
            attempt_publication_calls += 1
            raise OSError("attempt ledger disk full")

        with (
            patch.object(
                Converter,
                "refresh_conversion_artifacts",
                fail_second_refresh,
            ),
            patch.object(
                Converter,
                "publish_conversion_attempt",
                fail_terminal_attempt_publication,
            ),
        ):
            exit_code, stdout, stderr = self._run_real_convert(
                gm_dir,
                godot_dir,
                "--only",
                "scripts",
                "--report-dir",
                godot_dir,
            )

        self.assertEqual(refresh_calls, 2)
        self.assertEqual(attempt_publication_calls, 1)
        self.assertEqual(exit_code, 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot conversion artifact publication failed: "
            "late artifact disk full\n"
            "GM2Godot terminal conversion attempt publication failed: "
            "attempt ledger disk full\n",
        )
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "success")

    def test_recovered_terminal_attempt_publication_clears_stale_error(self) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        publish_calls: list[ConversionOutcome] = []

        def fail_late_refresh(_current: ConversionOutcome) -> tuple[str | None, str]:
            raise OSError("late artifact failure")

        def fail_once_then_publish(current: ConversionOutcome) -> str:
            publish_calls.append(current)
            if len(publish_calls) == 1:
                signal.raise_signal(signal.SIGINT)
                raise OSError("intermediate attempt failure")
            return ""

        with (
            patch.object(
                converter,
                "refresh_conversion_artifacts",
                side_effect=fail_late_refresh,
            ),
            patch.object(
                converter,
                "publish_conversion_attempt",
                side_effect=fail_once_then_publish,
            ),
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                os.path.join(self.temp_dir, "godot"),
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr, "")
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertEqual([item.state for item in publish_calls], ["failed", "cancelled"])
        self.assertEqual(
            self._read_report_outcome_state(os.path.join(self.temp_dir, "godot")),
            "cancelled",
        )

    def test_external_report_failure_preserves_every_failed_repair_pair(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_dir = os.path.join(self.temp_dir, "unrepairable-report")
        self._write_outcome_reports(godot_dir, outcome)
        self._write_outcome_reports(report_dir, outcome)

        with (
            patch(
                "src.cli._write_external_conversion_reports",
                side_effect=OSError("report disk full"),
            ),
            patch.object(
                DiagnosticCollector,
                "publish_reports",
                side_effect=OSError("repair disk full"),
            ),
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot external report generation failed: report disk full\n",
        )
        for destination in (godot_dir, report_dir):
            with self.subTest(destination=destination):
                self.assertEqual(
                    self._read_report_outcome_state(destination),
                    "success",
                )
        self.assertEqual(converter.artifact_refreshes, [])
        self.assertEqual(len(converter.attempt_publications), 1)
        self.assertEqual(converter.attempt_publications[0].state, "failed")
        self.assertEqual(
            converter.attempt_publications[0].failed_step,
            "external_reports",
        )

    def test_external_report_failure_deduplicates_canonical_destination(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        godot_dir = os.path.join(self.temp_dir, "godot")
        self._write_outcome_reports(godot_dir, outcome)
        original_publish_reports = DiagnosticCollector.publish_reports
        repair_destinations: list[str] = []

        def track_repair(
            diagnostics: DiagnosticCollector,
            destination: str | os.PathLike[str],
        ) -> object:
            repair_destinations.append(os.fspath(destination))
            return original_publish_reports(diagnostics, destination)

        with (
            patch(
                "src.cli._write_external_conversion_reports",
                side_effect=OSError("report disk full"),
            ),
            patch.object(
                DiagnosticCollector,
                "publish_reports",
                track_repair,
            ),
        ):
            exit_code, _stdout, _stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                os.path.join(godot_dir, "."),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(repair_destinations, [godot_dir])
        self.assertEqual(self._read_report_outcome_state(godot_dir), "failed")
        self.assertEqual(len(converter.artifact_refreshes), 1)
        self.assertEqual(converter.attempt_publications, [])

    def test_real_preflight_refusal_does_not_publish_conversion_artifacts(self) -> None:
        gm_dir, godot_dir = self._write_real_script_project("UnsafeDestination")
        os.makedirs(godot_dir)
        sentinel_path = os.path.join(godot_dir, "keep.txt")
        with open(sentinel_path, "w", encoding="utf-8") as sentinel_file:
            sentinel_file.write("keep\n")

        exit_code, stdout, stderr = self._run_real_convert(
            gm_dir,
            godot_dir,
            "--only",
            "scripts",
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            json.loads(stderr)["code"],
            "GM2GD-CONVERT-DESTINATION-NOT-EMPTY",
        )
        self.assertEqual(
            sorted(os.listdir(godot_dir)),
            ["keep.txt"],
        )

    def test_generic_preflight_failure_does_not_write_inside_project_roots(
        self,
    ) -> None:
        for report_root_name in ("gm", "godot"):
            with self.subTest(report_root=report_root_name):
                case_root = os.path.join(
                    self.temp_dir,
                    f"generic-preflight-{report_root_name}",
                )
                gm_dir = os.path.join(case_root, "gm")
                godot_dir = os.path.join(case_root, "godot")
                os.makedirs(gm_dir)
                os.makedirs(godot_dir)
                for project_root in (gm_dir, godot_dir):
                    with open(
                        os.path.join(project_root, "keep.txt"),
                        "w",
                        encoding="utf-8",
                    ) as sentinel_file:
                        sentinel_file.write("keep\n")

                converter = _OutcomeConverterStub(
                    ConversionOutcome(
                        state="failed",
                        failure_phase="preflight",
                    ),
                    error=OSError("preflight scan denied"),
                )
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch("src.cli.Converter", return_value=converter),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = cli.main(
                        [
                            "convert",
                            "--gm-project",
                            gm_dir,
                            "--godot-project",
                            godot_dir,
                            "--report-dir",
                            os.path.join(
                                gm_dir if report_root_name == "gm" else godot_dir,
                                "nested-reports",
                            ),
                        ]
                    )

                self.assertEqual(exit_code, 1)
                self.assertIn(
                    "GM2Godot conversion outcome: failed",
                    stdout.getvalue(),
                )
                self.assertEqual(
                    stderr.getvalue(),
                    "GM2Godot conversion failed: preflight scan denied\n",
                )
                self.assertEqual(sorted(os.listdir(gm_dir)), ["keep.txt"])
                self.assertEqual(sorted(os.listdir(godot_dir)), ["keep.txt"])

    def test_preflight_error_survives_external_report_failure(self) -> None:
        outcome = ConversionOutcome(
            state="failed",
            failure_phase="preflight",
        )
        source_dir = os.path.join(self.temp_dir, "unsafe-source-destination")
        os.makedirs(source_dir)
        error = ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-TEST",
            "Unsafe conversion destination.",
            destination_path=source_dir,
            workaround="Choose a safe destination.",
        )
        report_dir = os.path.join(self.temp_dir, "preflight-report-failure")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "src.cli.Converter",
                return_value=_OutcomeConverterStub(outcome, error=error),
            ),
            patch(
                "src.cli._write_external_conversion_reports",
                side_effect=OSError("report disk full"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main([
                "convert",
                "--gm-project",
                source_dir,
                "--godot-project",
                source_dir,
                "--report-dir",
                report_dir,
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            stdout.getvalue().count("GM2Godot conversion outcome:"),
            1,
        )
        stderr_diagnostic = json.loads(stderr.getvalue())
        self.assertEqual(
            stderr_diagnostic["code"],
            "GM2GD-CONVERT-DESTINATION-TEST",
        )
        self.assertFalse(os.path.exists(os.path.join(source_dir, "gm2godot")))
        self.assertEqual(self._read_report_outcome_state(report_dir), "failed")

    def test_preflight_refusal_does_not_write_reports_inside_unsafe_roots(
        self,
    ) -> None:
        source_dir = os.path.join(self.temp_dir, "unsafe-source")
        godot_dir = os.path.join(self.temp_dir, "unsafe-godot")
        os.makedirs(source_dir)
        os.makedirs(godot_dir)
        source_alias = os.path.join(self.temp_dir, "source-alias")
        godot_alias = os.path.join(self.temp_dir, "godot-alias")
        os.symlink(source_dir, source_alias)
        os.symlink(godot_dir, godot_alias)
        error = ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-TEST",
            "Unsafe conversion destination.",
            destination_path=godot_dir,
            workaround="Choose a safe destination.",
        )
        cases = [
            (os.path.join(source_alias, "."), source_dir),
            (
                os.path.join(godot_alias, "nested-reports"),
                os.path.join(godot_dir, "nested-reports"),
            ),
        ]
        case_alias = os.path.join(
            os.path.dirname(source_dir),
            os.path.basename(source_dir).upper(),
        )
        try:
            case_alias_matches = os.path.samefile(case_alias, source_dir)
        except OSError:
            case_alias_matches = False
        if case_alias_matches:
            cases.append((case_alias, source_dir))

        for report_dir, resolved_report_dir in cases:
            with self.subTest(report_dir=report_dir):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch(
                        "src.cli.Converter",
                        return_value=_OutcomeConverterStub(
                            ConversionOutcome(
                                state="failed",
                                failure_phase="preflight",
                            ),
                            error=error,
                        ),
                    ),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = cli.main([
                        "convert",
                        "--gm-project",
                        source_dir,
                        "--godot-project",
                        godot_dir,
                        "--report-dir",
                        report_dir,
                    ])

                self.assertEqual(exit_code, 2)
                self.assertEqual(
                    stdout.getvalue().count("GM2Godot conversion outcome:"),
                    1,
                )
                self.assertEqual(
                    json.loads(stderr.getvalue())["code"],
                    "GM2GD-CONVERT-DESTINATION-TEST",
                )
                self.assertFalse(
                    os.path.exists(
                        os.path.join(resolved_report_dir, "gm2godot")
                    )
                )

    def test_runtime_error_survives_external_report_failure(self) -> None:
        outcome = _failed_outcome()
        report_dir = os.path.join(self.temp_dir, "runtime-report-failure")

        with patch(
            "src.cli._write_external_conversion_reports",
            side_effect=OSError("report disk full"),
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                _OutcomeConverterStub(
                    outcome,
                    error=RuntimeError("converter disk full"),
                ),
                "--report-dir",
                report_dir,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertEqual(
            stderr,
            "GM2Godot conversion failed: converter disk full\n"
            "GM2Godot conversion failure detail: external report generation "
            "failed: report disk full\n",
        )
        with open(
            os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        self.assertEqual(report["outcome"], outcome.to_dict())

    def test_partial_conversion_requires_explicit_allow_partial(self) -> None:
        outcome = _partial_outcome()
        cases = ((False, 2), (True, 0))
        for allow_partial, expected_exit in cases:
            with self.subTest(allow_partial=allow_partial):
                report_dir = os.path.join(
                    self.temp_dir,
                    f"partial-{allow_partial}",
                )
                extra = ["--report-dir", report_dir]
                if allow_partial:
                    extra.append("--allow-partial")

                exit_code, stdout, stderr = self._run_stubbed_convert(
                    _OutcomeConverterStub(outcome),
                    *extra,
                )

                self.assertEqual(exit_code, expected_exit)
                self.assertEqual(stderr, "")
                self.assertEqual(
                    stdout.count("GM2Godot conversion outcome:"),
                    1,
                )
                with open(
                    os.path.join(
                        report_dir,
                        DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
                    ),
                    "r",
                    encoding="utf-8",
                ) as report_file:
                    report = json.load(report_file)
                self.assertEqual(report["outcome"], outcome.to_dict())

    def test_real_blocked_script_makes_cli_partial_and_keeps_safe_sibling(
        self,
    ) -> None:
        gm_dir = os.path.join(self.temp_dir, "real-partial-gm")
        godot_dir = os.path.join(self.temp_dir, "real-partial-godot")
        resources: list[dict[str, object]] = []
        for script_name, source in (
            ("scr_safe", "return 1;\n"),
            ("scr_blocked", "return @;\n"),
        ):
            script_dir = os.path.join(gm_dir, "scripts", script_name)
            os.makedirs(script_dir, exist_ok=True)
            yy_relative = f"scripts/{script_name}/{script_name}.yy"
            with open(
                os.path.join(script_dir, f"{script_name}.yy"),
                "w",
                encoding="utf-8",
            ) as yy_file:
                json.dump(
                    {
                        "name": script_name,
                        "resourceType": "GMScript",
                        "parent": {
                            "name": "Scripts",
                            "path": "folders/Scripts.yy",
                        },
                    },
                    yy_file,
                )
            with open(
                os.path.join(script_dir, f"{script_name}.gml"),
                "w",
                encoding="utf-8",
            ) as gml_file:
                gml_file.write(source)
            resources.append(
                {"id": {"name": script_name, "path": yy_relative}}
            )
        with open(
            os.path.join(gm_dir, "Partial.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump({"%Name": "Partial", "resources": resources}, project_file)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(
                [
                    "convert",
                    "--gm-project",
                    gm_dir,
                    "--godot-project",
                    godot_dir,
                    "--only",
                    "scripts",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(stdout.getvalue().count("GM2Godot conversion outcome:"), 1)
        with open(
            os.path.join(godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        self.assertEqual(report["outcome"]["state"], "partial")
        self.assertEqual(
            report["outcome"]["resources"],
            {
                "requested": 2,
                "executed": 2,
                "completed": 1,
                "skipped": 1,
                "failed": 0,
            },
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(godot_dir, "scripts", "scr_safe.gd")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(godot_dir, "scripts", "scr_blocked.gd")
            )
        )

    def test_partial_allow_does_not_override_diagnostic_thresholds(self) -> None:
        exit_code, stdout, stderr = self._run_stubbed_convert(
            _OutcomeConverterStub(_partial_outcome(), warning=True),
            "--allow-partial",
            "--max-warnings",
            "0",
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)

    def test_runtime_exception_returns_one_after_failed_report_and_summary(
        self,
    ) -> None:
        outcome = _failed_outcome()
        report_dir = os.path.join(self.temp_dir, "runtime-report")

        exit_code, stdout, stderr = self._run_stubbed_convert(
            _OutcomeConverterStub(
                outcome,
                error=RuntimeError("disk full"),
            ),
            "--report-dir",
            report_dir,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("disk full", stderr)
        with open(
            os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        self.assertEqual(report["outcome"], outcome.to_dict())

    def test_runtime_exception_prints_finalizer_notes_in_order(self) -> None:
        runtime_error = OSError("manifest failed")
        runtime_error.add_note(
            "Additional conversion finalizer failure: diagnostic restore failed"
        )
        runtime_error.add_note(
            "Additional conversion finalizer failure: architecture restore failed"
        )

        exit_code, stdout, stderr = self._run_stubbed_convert(
            _OutcomeConverterStub(
                _failed_outcome(),
                error=runtime_error,
            )
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot conversion failed: manifest failed\n"
            "GM2Godot conversion failure detail: Additional conversion "
            "finalizer failure: diagnostic restore failed\n"
            "GM2Godot conversion failure detail: Additional conversion "
            "finalizer failure: architecture restore failed\n",
        )

    def test_runtime_exception_coerces_preexisting_nonfailed_outcome(self) -> None:
        for original_outcome in (_success_outcome(), _partial_outcome()):
            with self.subTest(original_state=original_outcome.state):
                report_dir = os.path.join(
                    self.temp_dir,
                    f"runtime-after-{original_outcome.state}",
                )
                exit_code, stdout, stderr = self._run_stubbed_convert(
                    _OutcomeConverterStub(
                        original_outcome,
                        error=RuntimeError("late converter failure"),
                    ),
                    "--report-dir",
                    report_dir,
                )

                self.assertEqual(exit_code, 1)
                self.assertEqual(
                    stdout.count("GM2Godot conversion outcome:"),
                    1,
                )
                self.assertIn("GM2Godot conversion outcome: failed", stdout)
                self.assertNotIn(
                    f"GM2Godot conversion outcome: {original_outcome.state}",
                    stdout,
                )
                self.assertEqual(
                    stderr,
                    "GM2Godot conversion failed: late converter failure\n",
                )
                with open(
                    os.path.join(
                        report_dir,
                        DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
                    ),
                    "r",
                    encoding="utf-8",
                ) as report_file:
                    report = json.load(report_file)
                self.assertEqual(report["outcome"]["state"], "failed")
                self.assertEqual(report["outcome"]["failure_phase"], "runtime")
                self.assertEqual(
                    report["outcome"]["converters"],
                    original_outcome.converters.to_dict(),
                )
                self.assertEqual(
                    report["outcome"]["resources"],
                    original_outcome.resources.to_dict(),
                )

    def test_real_second_run_runtime_failure_publishes_unverified_diagnostics(
        self,
    ) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "HistoricalRuntimeFailure"
        )
        first_exit, _first_stdout, first_stderr = self._run_real_convert(
            gm_dir,
            godot_dir,
            "--only",
            "scripts",
        )
        self.assertEqual(first_exit, 0)
        self.assertEqual(first_stderr, "")

        with patch(
            "src.conversion.scripts.ScriptConverter.convert_all",
            side_effect=RuntimeError("second-run script failure"),
        ):
            exit_code, stdout, stderr = self._run_real_convert(
                gm_dir,
                godot_dir,
                "--only",
                "scripts",
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("GM2Godot conversion outcome: failed", stdout)
        self.assertEqual(
            stderr,
            "GM2Godot conversion failed: second-run script failure\n",
        )
        self.assertEqual(self._read_report_outcome_state(godot_dir), "failed")
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "unverified",
        )

    def test_preflight_failure_keeps_stderr_as_one_diagnostic_json(self) -> None:
        outcome = ConversionOutcome(
            state="failed",
            failure_phase="preflight",
        )
        error = ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-TEST",
            "Unsafe conversion destination.",
            destination_path="/unsafe/godot",
            workaround="Choose a safe destination.",
        )
        report_dir = os.path.join(self.temp_dir, "preflight-report")

        exit_code, stdout, stderr = self._run_stubbed_convert(
            _OutcomeConverterStub(outcome, error=error),
            "--report-dir",
            report_dir,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        stderr_diagnostic = json.loads(stderr)
        self.assertEqual(
            stderr_diagnostic["code"],
            "GM2GD-CONVERT-DESTINATION-TEST",
        )
        with open(
            os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        self.assertEqual(report["outcome"], outcome.to_dict())

    def test_sigint_overrides_success_restores_handler_and_returns_130(self) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(
            outcome,
            on_convert=lambda: signal.raise_signal(signal.SIGINT),
        )
        running_events: list[threading.Event] = []

        def converter_factory(**kwargs: object) -> _OutcomeConverterStub:
            conversion_running = kwargs["conversion_running"]
            self.assertIsInstance(conversion_running, threading.Event)
            assert isinstance(conversion_running, threading.Event)
            running_events.append(conversion_running)
            return converter

        report_dir = os.path.join(self.temp_dir, "cancelled-report")
        previous_sigint = signal.getsignal(signal.SIGINT)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("src.cli.Converter", side_effect=converter_factory),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                self._convert_args("--report-dir", report_dir)
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue().count("GM2Godot conversion outcome:"),
            1,
        )
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout.getvalue())
        self.assertEqual(len(running_events), 1)
        self.assertFalse(running_events[0].is_set())
        self.assertEqual(signal.getsignal(signal.SIGINT), previous_sigint)
        with open(
            os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        self.assertEqual(report["outcome"]["state"], "cancelled")
        self.assertEqual(
            report["outcome"]["converters"],
            outcome.converters.to_dict(),
        )
        self.assertEqual(
            report["outcome"]["resources"],
            outcome.resources.to_dict(),
        )

    def test_sigint_during_converter_construction_publishes_cancelled_outcome(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        running_events: list[threading.Event] = []

        def interrupting_factory(**kwargs: object) -> _OutcomeConverterStub:
            conversion_running = kwargs["conversion_running"]
            self.assertIsInstance(conversion_running, threading.Event)
            assert isinstance(conversion_running, threading.Event)
            running_events.append(conversion_running)
            signal.raise_signal(signal.SIGINT)
            return converter

        report_dir = os.path.join(self.temp_dir, "constructor-interrupted")
        previous_sigint = signal.getsignal(signal.SIGINT)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("src.cli.Converter", side_effect=interrupting_factory),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                self._convert_args("--report-dir", report_dir)
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue().count("GM2Godot conversion outcome:"),
            1,
        )
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout.getvalue())
        self.assertEqual(len(running_events), 1)
        self.assertFalse(running_events[0].is_set())
        self.assertEqual(signal.getsignal(signal.SIGINT), previous_sigint)
        self.assertEqual(self._read_report_outcome_state(report_dir), "cancelled")

    def test_second_sigint_during_handler_install_restores_previous_handler(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        previous_sigint = signal.getsignal(signal.SIGINT)
        original_signal = signal.signal
        install_calls = 0
        restore_calls = 0
        interrupted = False

        def interrupt_after_handler_install(
            signum: signal.Signals,
            handler: Any,
        ) -> Any:
            nonlocal install_calls, interrupted, restore_calls
            result = original_signal(signum, handler)
            if signum == signal.SIGINT and handler is previous_sigint:
                restore_calls += 1
            elif signum == signal.SIGINT:
                install_calls += 1
                if not interrupted:
                    interrupted = True
                    signal.raise_signal(signal.SIGINT)
                    signal.raise_signal(signal.SIGINT)
            return result

        stdout = io.StringIO()
        stderr = io.StringIO()
        handler_after_abort: Any = None
        try:
            with (
                patch("src.cli.Converter", return_value=converter),
                patch(
                    "src.cli.signal.signal",
                    side_effect=interrupt_after_handler_install,
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    cli.main(self._convert_args())
            handler_after_abort = signal.getsignal(signal.SIGINT)
        finally:
            original_signal(signal.SIGINT, previous_sigint)

        self.assertTrue(interrupted)
        self.assertEqual(install_calls, 1)
        self.assertEqual(restore_calls, 1)
        self.assertIs(handler_after_abort, previous_sigint)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_sigint_during_log_flush_publishes_cancelled_outcome(self) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_dir = os.path.join(self.temp_dir, "log-flush-interrupted")
        self._write_outcome_reports(godot_dir, outcome)
        original_print_logs = getattr(cli, "_print_conversion_logs")

        def interrupt_during_log_flush(logs: list[str]) -> None:
            signal.raise_signal(signal.SIGINT)
            original_print_logs(logs)

        with patch(
            "src.cli._print_conversion_logs",
            side_effect=interrupt_during_log_flush,
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertEqual(self._read_report_outcome_state(godot_dir), "cancelled")
        self.assertEqual(self._read_report_outcome_state(report_dir), "cancelled")

    def test_real_sigint_during_log_flush_refreshes_manifest_hashes(self) -> None:
        gm_dir, godot_dir = self._write_real_script_project("LateCancellation")
        original_print_logs = getattr(cli, "_print_conversion_logs")
        stdout = io.StringIO()
        stderr = io.StringIO()

        def interrupt_during_log_flush(logs: list[str]) -> None:
            signal.raise_signal(signal.SIGINT)
            original_print_logs(logs)

        with (
            patch(
                "src.cli._print_conversion_logs",
                side_effect=interrupt_during_log_flush,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                [
                    "convert",
                    "--gm-project",
                    gm_dir,
                    "--godot-project",
                    godot_dir,
                    "--only",
                    "scripts",
                ]
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(stdout.getvalue().count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout.getvalue())
        self.assertEqual(self._read_report_outcome_state(godot_dir), "cancelled")
        self._assert_manifest_diagnostic_hashes(godot_dir)
        manifest = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        )
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(manifest["conversion"]["state"], "success")
        self.assertEqual(attempt["attempt"]["state"], "cancelled")
        self.assertEqual(attempt["canonical_manifest"]["status"], "updated")
        self.assertTrue(attempt["canonical_manifest"]["updated"])
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "verified",
        )
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            self._artifact_sha256(
                godot_dir,
                CONVERSION_MANIFEST_RELATIVE_PATH,
            ),
        )

    def test_real_failed_cancelled_report_rewrite_preserves_manifest(self) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "CancelledReportFailure"
        )
        original_print_logs = getattr(cli, "_print_conversion_logs")
        original_publish_reports = DiagnosticCollector.publish_reports
        manifest_before: bytes | None = None

        def interrupt_during_log_flush(logs: list[str]) -> None:
            nonlocal manifest_before
            with open(
                os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
                "rb",
            ) as manifest_file:
                manifest_before = manifest_file.read()
            signal.raise_signal(signal.SIGINT)
            original_print_logs(logs)

        def fail_cancelled_canonical_report(
            diagnostics: DiagnosticCollector,
            destination: str | os.PathLike[str],
        ) -> object:
            outcome = diagnostics.outcome()
            if (
                outcome is not None
                and outcome.state == "cancelled"
                and os.path.realpath(os.fspath(destination))
                == os.path.realpath(godot_dir)
            ):
                raise OSError("cancelled report disk full")
            return original_publish_reports(diagnostics, destination)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "src.cli._print_conversion_logs",
                side_effect=interrupt_during_log_flush,
            ),
            patch.object(
                DiagnosticCollector,
                "publish_reports",
                fail_cancelled_canonical_report,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                [
                    "convert",
                    "--gm-project",
                    gm_dir,
                    "--godot-project",
                    godot_dir,
                    "--only",
                    "scripts",
                ]
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(stdout.getvalue().count("GM2Godot conversion outcome:"), 1)
        self.assertEqual(self._read_report_outcome_state(godot_dir), "success")
        self.assertIsNotNone(manifest_before)
        with open(
            os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
            "rb",
        ) as manifest_file:
            self.assertEqual(manifest_file.read(), manifest_before)
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "cancelled")
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertFalse(attempt["canonical_manifest"]["updated"])
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            self._artifact_sha256(
                godot_dir,
                CONVERSION_MANIFEST_RELATIVE_PATH,
            ),
        )

    def test_real_failed_late_artifact_refresh_preserves_manifest(self) -> None:
        gm_dir, godot_dir = self._write_real_script_project(
            "CancelledManifestFailure"
        )
        original_print_logs = getattr(cli, "_print_conversion_logs")
        original_refresh_artifacts = Converter.refresh_conversion_artifacts
        refresh_calls = 0
        manifest_before: bytes | None = None

        def interrupt_during_log_flush(logs: list[str]) -> None:
            nonlocal manifest_before
            with open(
                os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
                "rb",
            ) as manifest_file:
                manifest_before = manifest_file.read()
            signal.raise_signal(signal.SIGINT)
            original_print_logs(logs)

        def fail_late_artifact_refresh(
            converter: Converter,
            attempt_outcome: ConversionOutcome,
        ) -> tuple[str | None, str]:
            nonlocal refresh_calls
            refresh_calls += 1
            if refresh_calls == 2:
                raise OSError("late artifact disk full")
            return original_refresh_artifacts(converter, attempt_outcome)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "src.cli._print_conversion_logs",
                side_effect=interrupt_during_log_flush,
            ),
            patch.object(
                Converter,
                "refresh_conversion_artifacts",
                fail_late_artifact_refresh,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                [
                    "convert",
                    "--gm-project",
                    gm_dir,
                    "--godot-project",
                    godot_dir,
                    "--only",
                    "scripts",
                ]
            )

        self.assertEqual(refresh_calls, 2)
        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(stdout.getvalue().count("GM2Godot conversion outcome:"), 1)
        self.assertEqual(self._read_report_outcome_state(godot_dir), "success")
        self.assertIsNotNone(manifest_before)
        with open(
            os.path.join(godot_dir, CONVERSION_MANIFEST_RELATIVE_PATH),
            "rb",
        ) as manifest_file:
            self.assertEqual(manifest_file.read(), manifest_before)
        attempt = self._read_conversion_artifact(
            godot_dir,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        self.assertEqual(attempt["attempt"]["state"], "cancelled")
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertFalse(attempt["canonical_manifest"]["updated"])
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            self._artifact_sha256(
                godot_dir,
                CONVERSION_MANIFEST_RELATIVE_PATH,
            ),
        )
        self._assert_manifest_diagnostic_hashes(godot_dir)

    def test_sigint_before_summary_output_republishes_cancelled_outcome(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_dir = os.path.join(self.temp_dir, "summary-interrupted")
        self._write_outcome_reports(godot_dir, outcome)
        original_print_summary = getattr(cli, "_print_conversion_summary")
        interrupted = False

        def interrupt_before_summary(current: ConversionOutcome) -> None:
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                signal.raise_signal(signal.SIGINT)
            original_print_summary(current)

        with patch(
            "src.cli._print_conversion_summary",
            side_effect=interrupt_before_summary,
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertNotIn("GM2Godot conversion outcome: success", stdout)
        self.assertEqual(self._read_report_outcome_state(godot_dir), "cancelled")
        self.assertEqual(self._read_report_outcome_state(report_dir), "cancelled")

    def test_sigint_after_buffered_summary_prints_only_cancelled_summary(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        report_dir = os.path.join(self.temp_dir, "summary-post-print-interrupt")
        original_print_summary = getattr(cli, "_print_conversion_summary")
        interrupted = False

        def interrupt_after_summary(current: ConversionOutcome) -> None:
            nonlocal interrupted
            original_print_summary(current)
            if not interrupted:
                interrupted = True
                signal.raise_signal(signal.SIGINT)

        with patch(
            "src.cli._print_conversion_summary",
            side_effect=interrupt_after_summary,
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )

        self.assertTrue(interrupted)
        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertNotIn("GM2Godot conversion outcome: success", stdout)
        self.assertEqual(self._read_report_outcome_state(report_dir), "cancelled")

    def test_sigint_in_pre_summary_gap_is_observed_before_output(self) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        report_dir = os.path.join(self.temp_dir, "pre-summary-gap-interrupt")
        run_convert = getattr(cli, "_run_convert")
        source_lines, source_start = inspect.getsourcelines(run_convert)
        phase_assignment_offset = next(
            offset
            for offset, source_line in enumerate(source_lines)
            if source_line.strip() == 'terminal_summary_phase = "preparing"'
        )
        target_line = source_start + phase_assignment_offset + 1
        interrupted = False

        def interrupt_on_terminal_entry(
            frame: object,
            event: str,
            _arg: object,
        ) -> object:
            nonlocal interrupted
            frame_code = getattr(frame, "f_code", None)
            frame_line = getattr(frame, "f_lineno", None)
            if (
                not interrupted
                and event == "line"
                and frame_code is run_convert.__code__
                and frame_line == target_line
            ):
                interrupted = True
                sys.settrace(None)
                signal.raise_signal(signal.SIGINT)
            return interrupt_on_terminal_entry

        previous_trace = sys.gettrace()
        sys.settrace(cast(Any, interrupt_on_terminal_entry))
        try:
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )
        finally:
            sys.settrace(previous_trace)

        self.assertTrue(interrupted)
        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertNotIn("GM2Godot conversion outcome: success", stdout)
        self.assertEqual(self._read_report_outcome_state(report_dir), "cancelled")

    def test_sigint_while_restoring_handler_after_commit_keeps_one_summary(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        report_dir = os.path.join(self.temp_dir, "handler-restore-interrupt")
        previous_sigint = signal.getsignal(signal.SIGINT)
        original_signal = signal.signal
        interrupted = False

        def interrupt_before_handler_restore(
            signum: signal.Signals,
            handler: Any,
        ) -> Any:
            nonlocal interrupted
            if (
                not interrupted
                and signum == signal.SIGINT
                and handler is previous_sigint
            ):
                interrupted = True
                signal.raise_signal(signal.SIGINT)
            return original_signal(signum, handler)

        with patch(
            "src.cli.signal.signal",
            side_effect=interrupt_before_handler_restore,
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )

        self.assertTrue(interrupted)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: success", stdout)
        self.assertNotIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertEqual(signal.getsignal(signal.SIGINT), previous_sigint)
        self.assertEqual(self._read_report_outcome_state(report_dir), "success")

    def test_sigint_after_handler_restore_does_not_duplicate_committed_summary(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        report_dir = os.path.join(self.temp_dir, "post-handler-restore-interrupt")
        previous_sigint = signal.getsignal(signal.SIGINT)
        original_signal = signal.signal
        interrupted = False

        def restore_then_interrupt(
            signum: signal.Signals,
            handler: Any,
        ) -> Any:
            nonlocal interrupted
            result = original_signal(signum, handler)
            if (
                not interrupted
                and signum == signal.SIGINT
                and handler is previous_sigint
            ):
                interrupted = True
                signal.raise_signal(signal.SIGINT)
            return result

        with patch(
            "src.cli.signal.signal",
            side_effect=restore_then_interrupt,
        ):
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )

        self.assertTrue(interrupted)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: success", stdout)
        self.assertNotIn("GM2Godot conversion outcome: cancelled", stdout)
        self.assertEqual(signal.getsignal(signal.SIGINT), previous_sigint)
        self.assertEqual(self._read_report_outcome_state(report_dir), "success")

    def test_sigint_after_stdout_accepts_summary_keeps_single_committed_line(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        report_dir = os.path.join(self.temp_dir, "stdout-commit-interrupt")

        class SignalAfterOutcomeWrite(io.StringIO):
            interrupted = False

            def write(self, text: str) -> int:
                written = super().write(text)
                if (
                    not self.interrupted
                    and "GM2Godot conversion outcome:" in text
                ):
                    self.interrupted = True
                    signal.raise_signal(signal.SIGINT)
                return written

        stdout = SignalAfterOutcomeWrite()
        stderr = io.StringIO()
        with (
            patch("src.cli.Converter", return_value=converter),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                self._convert_args("--report-dir", report_dir)
            )

        self.assertTrue(stdout.interrupted)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue().count("GM2Godot conversion outcome:"),
            1,
        )
        self.assertIn(
            "GM2Godot conversion outcome: success",
            stdout.getvalue(),
        )
        self.assertEqual(self._read_report_outcome_state(report_dir), "success")

    def test_sigint_after_handler_restore_cannot_override_committed_exit(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        report_dir = os.path.join(self.temp_dir, "post-restore-return-interrupt")
        run_convert = getattr(cli, "_run_convert")
        source_lines, source_start = inspect.getsourcelines(run_convert)
        restore_offset = next(
            offset
            for offset, source_line in enumerate(source_lines)
            if source_line.strip() == "restore_sigint_handler()"
        )
        target_line = next(
            source_start + offset
            for offset in range(restore_offset + 1, len(source_lines))
            if source_lines[offset].strip() == "return exit_code"
        )
        interrupted = False

        def interrupt_before_committed_return(
            frame: object,
            event: str,
            _arg: object,
        ) -> object:
            nonlocal interrupted
            if (
                not interrupted
                and event == "line"
                and getattr(frame, "f_code", None) is run_convert.__code__
                and getattr(frame, "f_lineno", None) == target_line
            ):
                interrupted = True
                sys.settrace(None)
                signal.raise_signal(signal.SIGINT)
            return interrupt_before_committed_return

        previous_trace = sys.gettrace()
        sys.settrace(cast(Any, interrupt_before_committed_return))
        try:
            exit_code, stdout, stderr = self._run_stubbed_convert(
                converter,
                "--report-dir",
                report_dir,
            )
        finally:
            sys.settrace(previous_trace)

        self.assertTrue(interrupted)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.count("GM2Godot conversion outcome:"), 1)
        self.assertIn("GM2Godot conversion outcome: success", stdout)
        self.assertEqual(self._read_report_outcome_state(report_dir), "success")

    def test_sigint_during_report_generation_rewrites_cancelled_outcome(
        self,
    ) -> None:
        outcome = _success_outcome()
        converter = _OutcomeConverterStub(outcome)
        report_dir = os.path.join(self.temp_dir, "report-interrupted")
        original_write_reports = getattr(
            cli,
            "_write_external_conversion_reports",
        )

        def interrupt_during_reports(
            destination: str | None,
            target_platform: str,
            diagnostics: DiagnosticCollector,
        ) -> None:
            signal.raise_signal(signal.SIGINT)
            original_write_reports(destination, target_platform, diagnostics)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("src.cli.Converter", return_value=converter),
            patch(
                "src.cli._write_external_conversion_reports",
                side_effect=interrupt_during_reports,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.main(
                self._convert_args("--report-dir", report_dir)
            )

        self.assertEqual(exit_code, 130)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue().count("GM2Godot conversion outcome:"),
            1,
        )
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout.getvalue())
        with open(
            os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = json.load(report_file)
        self.assertEqual(report["outcome"]["state"], "cancelled")
        self.assertEqual(
            report["outcome"]["converters"],
            outcome.converters.to_dict(),
        )
        self.assertEqual(
            report["outcome"]["resources"],
            outcome.resources.to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
