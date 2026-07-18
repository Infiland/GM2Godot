from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.diagnostics import (
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
    DiagnosticCollector,
    invalidate_conversion_diagnostic_reports,
)
from src.conversion.conversion_outcome import ConversionCounts, ConversionOutcome


class TestDiagnosticCollector(unittest.TestCase):
    def test_warning_log_wrapper_preserves_log_and_records_diagnostic(self):
        logs: list[str] = []
        diagnostics = DiagnosticCollector()
        wrapped_log = diagnostics.wrap_log_callback(lambda message: logs.append(message))

        wrapped_log("Warning: Unsupported room layer emitted as placeholder.")
        wrapped_log("Converted sprite spr_player.")

        self.assertEqual(logs, [
            "Warning: Unsupported room layer emitted as placeholder.",
            "Converted sprite spr_player.",
        ])
        recorded = diagnostics.diagnostics()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].severity, "warning")
        self.assertEqual(recorded[0].code, "GM2GD-WARNING")

    def test_info_log_wrapper_records_informational_diagnostic(self):
        diagnostics = DiagnosticCollector()
        wrapped_log = diagnostics.wrap_log_callback(lambda message: None)

        wrapped_log("Info: Missing optional GameMaker metadata file; fallback metadata preserved.")

        recorded = diagnostics.diagnostics()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].severity, "info")
        self.assertEqual(recorded[0].code, "GM2GD-WARNING")

    def test_transpile_failure_extracts_api_and_issue_metadata(self):
        diagnostics = DiagnosticCollector()

        diagnostic = diagnostics.add_transpile_failure(
            "Warning: Could not transpile GameMaker event code for obj/Create_0.gml: "
            "GML API 'show_message_async' from Asynchronous Functions is unsupported; "
            "tracked by #507. Dialog callbacks are not wired.",
            source_path="/tmp/project/objects/obj/Create_0.gml",
            resource="obj",
            resource_type="object",
            event="_ready",
        )

        self.assertEqual(diagnostic.api, "show_message_async")
        self.assertEqual(diagnostic.manifest_entry, "show_message_async")
        self.assertEqual(diagnostic.issue_number, 507)
        self.assertEqual(diagnostic.source_path, "/tmp/project/objects/obj/Create_0.gml")
        self.assertEqual(diagnostic.resource_type, "object")
        self.assertEqual(diagnostic.event, "_ready")

    def test_exact_structured_duplicates_are_deduped(self):
        diagnostics = DiagnosticCollector()

        diagnostics.add(
            "warning",
            "GM2GD-SOURCE-PATH-REJECTED",
            "Warning: Rejected GameMaker source path '../outside.wav'.",
            source_path="sounds/snd_test/snd_test.yy",
            resource="snd_test",
            resource_type="sound",
            manifest_entry="soundFile",
        )
        diagnostics.add(
            "warning",
            "GM2GD-SOURCE-PATH-REJECTED",
            "Warning: Rejected GameMaker source path '../outside.wav'.",
            source_path="sounds/snd_test/snd_test.yy",
            resource="snd_test",
            resource_type="sound",
            manifest_entry="soundFile",
        )
        diagnostics.add(
            "warning",
            "GM2GD-SOURCE-PATH-REJECTED",
            "Warning: Rejected GameMaker source path '../outside.wav'.",
            source_path="sounds/snd_test/snd_test.yy",
            resource="snd_other",
            resource_type="sound",
            manifest_entry="soundFile",
        )

        self.assertEqual(len(diagnostics.diagnostics()), 2)

    def test_reports_are_written_as_deterministic_json_and_markdown(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            diagnostics = DiagnosticCollector()
            diagnostics.add(
                "warning",
                "GM2GD-RESOURCE-UNSUPPORTED",
                "Unsupported GameMaker room asset type GMREffectLayer.",
                source_path="/tmp/project/rooms/r_main/r_main.yy",
                resource="r_main",
                resource_type="room",
                issue_number=590,
            )

            json_path, markdown_path = diagnostics.write_reports(tmp_dir)

            self.assertEqual(
                json_path,
                os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            )
            self.assertEqual(
                markdown_path,
                os.path.join(tmp_dir, DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH),
            )
            with open(json_path, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
            with open(markdown_path, "r", encoding="utf-8") as markdown_file:
                markdown = markdown_file.read()

            self.assertEqual(data["summary"]["warning"], 1)
            self.assertEqual(data["diagnostics"][0]["code"], "GM2GD-RESOURCE-UNSUPPORTED")
            self.assertIn("GM2Godot Conversion Diagnostics", markdown)
            self.assertIn("GM2GD-RESOURCE-UNSUPPORTED", markdown)
        finally:
            shutil.rmtree(tmp_dir)

    def test_report_schema_is_unchanged_without_conversion_outcome(self) -> None:
        diagnostics = DiagnosticCollector()

        self.assertEqual(
            set(diagnostics.to_json_dict()),
            {"summary", "diagnostics"},
        )

    def test_reports_include_explicit_conversion_outcome_when_set(self) -> None:
        diagnostics = DiagnosticCollector()
        outcome = ConversionOutcome(
            state="partial",
            converters=ConversionCounts(requested=1, executed=1, completed=1),
            resources=ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )
        diagnostics.set_outcome(outcome)

        report = diagnostics.to_json_dict()

        self.assertEqual(report["outcome"], outcome.to_dict())
        self.assertIn("Conversion outcome: `partial`", diagnostics.to_markdown())

    def test_markdown_staging_failure_leaves_no_new_report_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            diagnostics = DiagnosticCollector()
            diagnostics.set_outcome(ConversionOutcome(state="success"))
            report_directory = os.path.join(tmp_dir, "gm2godot")
            real_mkstemp = tempfile.mkstemp
            stage_calls = 0

            def fail_second_stage(
                suffix: str | None = None,
                prefix: str | None = None,
                dir: str | os.PathLike[str] | None = None,
                text: bool = False,
            ) -> tuple[int, str]:
                nonlocal stage_calls
                stage_calls += 1
                if stage_calls == 2:
                    raise OSError("markdown staging failed")
                return real_mkstemp(
                    suffix=suffix,
                    prefix=prefix,
                    dir=dir,
                    text=text,
                )

            with patch(
                "src.conversion.diagnostics.tempfile.mkstemp",
                side_effect=fail_second_stage,
            ):
                with self.assertRaisesRegex(OSError, "markdown staging failed"):
                    diagnostics.write_reports(tmp_dir)

            self.assertFalse(
                os.path.exists(
                    os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
                )
            )
            self.assertFalse(
                os.path.exists(
                    os.path.join(tmp_dir, DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH)
                )
            )
            self.assertEqual(os.listdir(report_directory), [])

    def test_second_replace_failure_restores_previous_report_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as json_file:
                json_file.write("previous json\n")
            with open(markdown_path, "w", encoding="utf-8") as markdown_file:
                markdown_file.write("previous markdown\n")
            os.chmod(json_path, 0o640)
            os.chmod(markdown_path, 0o600)

            diagnostics = DiagnosticCollector()
            diagnostics.set_outcome(ConversionOutcome(state="success"))
            real_replace = os.replace
            destinations: list[str] = []
            json_replace_attempts = 0

            def fail_first_json_replace(source: str, destination: str) -> None:
                nonlocal json_replace_attempts
                destinations.append(destination)
                if destination == json_path:
                    json_replace_attempts += 1
                    if json_replace_attempts == 1:
                        raise OSError("json publish failed")
                real_replace(source, destination)

            with patch(
                "src.conversion.diagnostics.os.replace",
                side_effect=fail_first_json_replace,
            ):
                with self.assertRaisesRegex(OSError, "json publish failed"):
                    diagnostics.write_reports(tmp_dir)

            self.assertEqual(destinations[:2], [markdown_path, json_path])
            with open(json_path, "r", encoding="utf-8") as json_file:
                self.assertEqual(json_file.read(), "previous json\n")
            with open(markdown_path, "r", encoding="utf-8") as markdown_file:
                self.assertEqual(markdown_file.read(), "previous markdown\n")
            self.assertEqual(stat.S_IMODE(os.stat(json_path).st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(os.stat(markdown_path).st_mode), 0o600)
            self.assertEqual(
                set(os.listdir(os.path.dirname(json_path))),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_post_replace_exception_still_restores_previous_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            with open(json_path, "w", encoding="utf-8") as report_file:
                report_file.write("previous json\n")
            with open(markdown_path, "w", encoding="utf-8") as report_file:
                report_file.write("previous markdown\n")
            real_replace = os.replace
            injected = False

            def replace_then_fail(source: str, destination: str) -> None:
                nonlocal injected
                real_replace(source, destination)
                if not injected and source.endswith(".tmp"):
                    injected = True
                    raise OSError("post-replace failure")

            with patch(
                "src.conversion.diagnostics.os.replace",
                side_effect=replace_then_fail,
            ):
                with self.assertRaisesRegex(OSError, "post-replace failure"):
                    DiagnosticCollector().write_reports(tmp_dir)

            with open(json_path, "r", encoding="utf-8") as report_file:
                self.assertEqual(report_file.read(), "previous json\n")
            with open(markdown_path, "r", encoding="utf-8") as report_file:
                self.assertEqual(report_file.read(), "previous markdown\n")
            self.assertEqual(
                set(os.listdir(os.path.dirname(json_path))),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_rollback_failure_preserves_previous_report_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            report_directory = os.path.dirname(json_path)
            os.makedirs(report_directory)
            with open(json_path, "w", encoding="utf-8") as report_file:
                report_file.write("previous json\n")
            with open(markdown_path, "w", encoding="utf-8") as report_file:
                report_file.write("previous markdown\n")

            diagnostics = DiagnosticCollector()
            diagnostics.set_outcome(ConversionOutcome(state="success"))
            real_replace = os.replace

            def fail_publish_and_rollback(
                source: str,
                destination: str,
            ) -> None:
                if destination == json_path and source.endswith(".tmp"):
                    raise OSError("json publish failed")
                if destination == markdown_path and source.endswith(".backup"):
                    raise OSError("markdown rollback failed")
                real_replace(source, destination)

            with patch(
                "src.conversion.diagnostics.os.replace",
                side_effect=fail_publish_and_rollback,
            ):
                with self.assertRaisesRegex(OSError, "json publish failed"):
                    diagnostics.write_reports(tmp_dir)

            recovery_paths = [
                os.path.join(report_directory, name)
                for name in os.listdir(report_directory)
                if name.endswith(".backup")
            ]
            self.assertEqual(len(recovery_paths), 1)
            with open(recovery_paths[0], "r", encoding="utf-8") as backup_file:
                self.assertEqual(backup_file.read(), "previous markdown\n")
            with open(json_path, "r", encoding="utf-8") as report_file:
                self.assertEqual(report_file.read(), "previous json\n")
            with open(markdown_path, "r", encoding="utf-8") as report_file:
                self.assertNotEqual(report_file.read(), "previous markdown\n")
            self.assertFalse(
                any(name.endswith(".tmp") for name in os.listdir(report_directory))
            )

    def test_reports_refuse_final_symlink_without_reading_referent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
            )
            external_path = os.path.join(tmp_dir, "external.json")
            os.makedirs(os.path.dirname(report_path))
            with open(external_path, "w", encoding="utf-8") as external_file:
                external_file.write("external sentinel\n")
            try:
                os.symlink(external_path, report_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(OSError, "non-regular diagnostic report"):
                DiagnosticCollector().write_reports(tmp_dir)

            self.assertTrue(os.path.islink(report_path))
            with open(external_path, "r", encoding="utf-8") as external_file:
                self.assertEqual(external_file.read(), "external sentinel\n")

    def test_reports_refuse_symlinked_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            external_directory = os.path.join(tmp_dir, "external")
            os.makedirs(external_directory)
            report_directory = os.path.join(tmp_dir, "gm2godot")
            try:
                os.symlink(external_directory, report_directory)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(
                OSError,
                "redirected diagnostic report directory",
            ):
                DiagnosticCollector().write_reports(tmp_dir)

            self.assertEqual(os.listdir(external_directory), [])

    def test_report_verification_and_invalidation_refuse_mocked_junction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
            )
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            report_directory = os.path.dirname(json_path)
            os.makedirs(report_directory)
            for report_path in (json_path, markdown_path):
                with open(report_path, "w", encoding="utf-8") as report_file:
                    report_file.write("stale sentinel\n")

            normalized_report_directory = os.path.normcase(
                os.path.abspath(report_directory)
            )
            report_directory_checks = 0

            def junction_after_initial_check(path: str) -> bool:
                nonlocal report_directory_checks
                if (
                    os.path.normcase(os.path.abspath(path))
                    != normalized_report_directory
                ):
                    return False
                report_directory_checks += 1
                return report_directory_checks > 1

            with patch.object(
                os.path,
                "isjunction",
                side_effect=junction_after_initial_check,
                create=True,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "Diagnostic report directory changed",
                ):
                    DiagnosticCollector().write_reports(tmp_dir)
                invalidate_conversion_diagnostic_reports(tmp_dir)

            for report_path in (json_path, markdown_path):
                with open(report_path, "r", encoding="utf-8") as report_file:
                    self.assertEqual(report_file.read(), "stale sentinel\n")

    def test_reports_replace_hardlinks_without_mutating_referents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            external_json = os.path.join(tmp_dir, "external.json")
            external_markdown = os.path.join(tmp_dir, "external.md")
            for path, content in (
                (external_json, "external json\n"),
                (external_markdown, "external markdown\n"),
            ):
                with open(path, "w", encoding="utf-8") as external_file:
                    external_file.write(content)
            try:
                os.link(external_json, json_path)
                os.link(external_markdown, markdown_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Hard links are unavailable: {error}")

            DiagnosticCollector().write_reports(tmp_dir)

            with open(external_json, "r", encoding="utf-8") as external_file:
                self.assertEqual(external_file.read(), "external json\n")
            with open(external_markdown, "r", encoding="utf-8") as external_file:
                self.assertEqual(external_file.read(), "external markdown\n")
            self.assertNotEqual(os.stat(json_path).st_ino, os.stat(external_json).st_ino)
            self.assertNotEqual(
                os.stat(markdown_path).st_ino,
                os.stat(external_markdown).st_ino,
            )

    def test_reports_refuse_nonregular_final_target(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(report_path))
            os.mkfifo(report_path)

            with self.assertRaisesRegex(OSError, "non-regular diagnostic report"):
                DiagnosticCollector().write_reports(tmp_dir)

    def test_report_writer_does_not_require_os_fchmod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(
                os,
                "fchmod",
                side_effect=AssertionError("os.fchmod must not be called"),
                create=True,
            ):
                json_path, markdown_path = DiagnosticCollector().write_reports(
                    tmp_dir
                )

            self.assertTrue(os.path.isfile(json_path))
            self.assertTrue(os.path.isfile(markdown_path))
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(os.stat(json_path).st_mode), 0o600)
                self.assertEqual(
                    stat.S_IMODE(os.stat(markdown_path).st_mode),
                    0o600,
                )

    def test_invalidate_reports_is_best_effort_for_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            for report_path in (json_path, markdown_path):
                with open(report_path, "w", encoding="utf-8") as report_file:
                    report_file.write("stale\n")
            real_unlink = os.unlink

            def fail_json_unlink(path: str) -> None:
                if path == json_path:
                    raise PermissionError("json is locked")
                real_unlink(path)

            with patch(
                "src.conversion.diagnostics.os.unlink",
                side_effect=fail_json_unlink,
            ):
                invalidate_conversion_diagnostic_reports(tmp_dir)

            self.assertTrue(os.path.exists(json_path))
            self.assertFalse(os.path.exists(markdown_path))

            invalidate_conversion_diagnostic_reports(tmp_dir)
            self.assertFalse(os.path.exists(json_path))

    def test_invalidate_reports_refuses_symlinked_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            external_directory = os.path.join(tmp_dir, "external")
            os.makedirs(external_directory)
            external_report = os.path.join(
                external_directory,
                os.path.basename(DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
            )
            with open(external_report, "w", encoding="utf-8") as report_file:
                report_file.write("external sentinel\n")
            try:
                os.symlink(
                    external_directory,
                    os.path.join(tmp_dir, "gm2godot"),
                )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")

            invalidate_conversion_diagnostic_reports(tmp_dir)

            with open(external_report, "r", encoding="utf-8") as report_file:
                self.assertEqual(report_file.read(), "external sentinel\n")


if __name__ == "__main__":
    unittest.main()
