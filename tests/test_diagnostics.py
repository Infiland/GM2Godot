from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from dataclasses import replace
from typing import Callable, cast
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.diagnostics import (
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
    DiagnosticCollector,
    capture_conversion_diagnostic_reports,
    invalidate_conversion_diagnostic_reports,
    publish_conversion_diagnostic_reports,
    restore_conversion_diagnostic_reports,
)
from src.conversion import diagnostics as diagnostics_module
from src.conversion.conversion_outcome import ConversionCounts, ConversionOutcome
from tests.conversion_outcome_helpers import completed_conversion_step_ledger


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

    def test_snapshot_captures_absent_report_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot = capture_conversion_diagnostic_reports(tmp_dir)

            self.assertEqual(snapshot.json_path, os.path.join(
                os.path.abspath(tmp_dir),
                DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
            ))
            self.assertEqual(snapshot.json_report.content, None)
            self.assertEqual(snapshot.json_report.fingerprint, None)
            self.assertEqual(snapshot.markdown_report.content, None)
            self.assertEqual(snapshot.markdown_report.fingerprint, None)
            report_directory_stat = os.stat(os.path.join(tmp_dir, "gm2godot"))
            self.assertEqual(
                snapshot.directory_identity,
                (report_directory_stat.st_dev, report_directory_stat.st_ino),
            )

    def test_snapshot_captures_exact_bytes_modes_and_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            json_content = b"old json\x00\xff\n"
            markdown_content = b"old markdown\r\n"
            for path, content, mode in (
                (json_path, json_content, 0o640),
                (markdown_path, markdown_content, 0o600),
            ):
                with open(path, "wb") as report_file:
                    report_file.write(content)
                os.chmod(path, mode)

            snapshot = capture_conversion_diagnostic_reports(tmp_dir)

            for path, expected_content, expected_mode, captured in (
                (json_path, json_content, 0o640, snapshot.json_report),
                (
                    markdown_path,
                    markdown_content,
                    0o600,
                    snapshot.markdown_report,
                ),
            ):
                self.assertEqual(captured.content, expected_content)
                self.assertIsNotNone(captured.fingerprint)
                assert captured.fingerprint is not None
                path_stat = os.stat(path, follow_symlinks=False)
                self.assertEqual(
                    captured.fingerprint.identity,
                    (path_stat.st_dev, path_stat.st_ino),
                )
                self.assertEqual(
                    captured.fingerprint.sha256,
                    hashlib.sha256(expected_content).hexdigest(),
                )
                if os.name != "nt":
                    self.assertEqual(captured.mode, expected_mode)

    def test_snapshot_refuses_redirected_or_nonregular_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            external_path = os.path.join(tmp_dir, "external.json")
            os.makedirs(os.path.dirname(json_path))
            with open(external_path, "wb") as external_file:
                external_file.write(b"external sentinel\n")
            try:
                os.symlink(external_path, json_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(OSError, "non-regular diagnostic report"):
                capture_conversion_diagnostic_reports(tmp_dir)

            with open(external_path, "rb") as external_file:
                self.assertEqual(external_file.read(), b"external sentinel\n")

    def test_reports_and_invalidation_refuse_symlinked_project_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as container:
            external_root = os.path.join(container, "external_project")
            report_directory = os.path.join(external_root, "gm2godot")
            os.makedirs(report_directory)
            external_reports = (
                os.path.join(
                    external_root,
                    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
                ),
                os.path.join(
                    external_root,
                    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
                ),
            )
            for report_path in external_reports:
                with open(report_path, "wb") as report_file:
                    report_file.write(b"external sentinel\n")
            redirected_root = os.path.join(container, "redirected_project")
            try:
                os.symlink(external_root, redirected_root)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(
                OSError,
                "redirected Godot project root",
            ):
                DiagnosticCollector().publish_reports(redirected_root)
            with self.assertRaisesRegex(
                OSError,
                "redirected Godot project root",
            ):
                capture_conversion_diagnostic_reports(redirected_root)
            invalidate_conversion_diagnostic_reports(redirected_root)

            for report_path in external_reports:
                with open(report_path, "rb") as report_file:
                    self.assertEqual(
                        report_file.read(),
                        b"external sentinel\n",
                    )

    def test_reports_and_invalidation_refuse_mocked_junction_project_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_directory = os.path.join(tmp_dir, "gm2godot")
            os.makedirs(report_directory)
            report_paths = (
                os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
                os.path.join(
                    tmp_dir,
                    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
                ),
            )
            for report_path in report_paths:
                with open(report_path, "wb") as report_file:
                    report_file.write(b"junction sentinel\n")
            normalized_root = os.path.normcase(os.path.abspath(tmp_dir))

            def root_is_junction(path: str) -> bool:
                return os.path.normcase(os.path.abspath(path)) == normalized_root

            with patch.object(
                os.path,
                "isjunction",
                side_effect=root_is_junction,
                create=True,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "redirected Godot project root",
                ):
                    DiagnosticCollector().publish_reports(tmp_dir)
                invalidate_conversion_diagnostic_reports(tmp_dir)

            for report_path in report_paths:
                with open(report_path, "rb") as report_file:
                    self.assertEqual(
                        report_file.read(),
                        b"junction sentinel\n",
                    )

    def test_new_report_directory_is_durably_linked_from_project_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_directory = os.path.join(tmp_dir, "gm2godot")
            fsync_project_root_impl = cast(
                Callable[[str, tuple[int, int]], None],
                getattr(diagnostics_module, "_fsync_project_root"),
            )

            with patch(
                "src.conversion.diagnostics._fsync_project_root",
                wraps=fsync_project_root_impl,
            ) as fsync_project_root:
                DiagnosticCollector().publish_reports(tmp_dir)

            fsync_project_root.assert_called_once()
            fsync_root, fsync_identity = fsync_project_root.call_args.args
            self.assertEqual(fsync_root, os.path.abspath(tmp_dir))
            root_stat = os.stat(tmp_dir, follow_symlinks=False)
            self.assertEqual(
                fsync_identity,
                (root_stat.st_dev, root_stat.st_ino),
            )
            self.assertTrue(os.path.isdir(report_directory))

    def test_existing_report_directory_retries_project_root_fsync(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_directory = os.path.join(tmp_dir, "gm2godot")
            real_fsync_project_root = cast(
                Callable[[str, tuple[int, int]], None],
                getattr(diagnostics_module, "_fsync_project_root"),
            )

            with patch(
                "src.conversion.diagnostics._fsync_project_root",
                side_effect=OSError("project root fsync failed"),
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "project root fsync failed",
                ):
                    DiagnosticCollector().publish_reports(tmp_dir)

            self.assertTrue(os.path.isdir(report_directory))
            with patch(
                "src.conversion.diagnostics._fsync_project_root",
                wraps=real_fsync_project_root,
            ) as retry_fsync:
                DiagnosticCollector().publish_reports(tmp_dir)

            retry_fsync.assert_called_once()

    def test_publish_receipt_proves_current_pair_and_helper_matches_api(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            diagnostics = DiagnosticCollector()
            diagnostics.add("warning", "GM2GD-TEST", "receipt sentinel")

            receipt = publish_conversion_diagnostic_reports(tmp_dir, diagnostics)

            for path, fingerprint in (
                (receipt.json_path, receipt.json_report),
                (receipt.markdown_path, receipt.markdown_report),
            ):
                path_stat = os.stat(path, follow_symlinks=False)
                with open(path, "rb") as report_file:
                    content = report_file.read()
                self.assertEqual(
                    fingerprint.identity,
                    (path_stat.st_dev, path_stat.st_ino),
                )
                self.assertEqual(
                    fingerprint.sha256,
                    hashlib.sha256(content).hexdigest(),
                )
                self.assertEqual(
                    fingerprint.mode,
                    stat.S_IMODE(path_stat.st_mode),
                )
    def test_restore_reinstates_exact_present_report_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            previous = {
                json_path: (b"trusted json\x00\n", 0o640),
                markdown_path: (b"trusted markdown\r\n", 0o600),
            }
            for path, (content, mode) in previous.items():
                with open(path, "wb") as report_file:
                    report_file.write(content)
                os.chmod(path, mode)
            snapshot = capture_conversion_diagnostic_reports(tmp_dir)
            receipt = DiagnosticCollector().publish_reports(tmp_dir)

            restore_conversion_diagnostic_reports(tmp_dir, snapshot, receipt)

            for path, (content, mode) in previous.items():
                with open(path, "rb") as report_file:
                    self.assertEqual(report_file.read(), content)
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), mode)
            self.assertEqual(
                set(os.listdir(os.path.dirname(json_path))),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_restore_reinstates_absent_report_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot = capture_conversion_diagnostic_reports(tmp_dir)
            receipt = DiagnosticCollector().publish_reports(tmp_dir)

            restore_conversion_diagnostic_reports(tmp_dir, snapshot, receipt)

            self.assertFalse(os.path.lexists(receipt.json_path))
            self.assertFalse(os.path.lexists(receipt.markdown_path))
            self.assertEqual(os.listdir(os.path.dirname(receipt.json_path)), [])

    def test_restore_reinstates_mixed_present_and_absent_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            os.makedirs(os.path.dirname(json_path))
            with open(json_path, "wb") as report_file:
                report_file.write(b"trusted json only\n")
            os.chmod(json_path, 0o640)
            snapshot = capture_conversion_diagnostic_reports(tmp_dir)
            receipt = DiagnosticCollector().publish_reports(tmp_dir)

            restore_conversion_diagnostic_reports(tmp_dir, snapshot, receipt)

            with open(json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), b"trusted json only\n")
            self.assertFalse(os.path.lexists(receipt.markdown_path))
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(os.stat(json_path).st_mode), 0o640)

    def test_old_baseline_can_restore_over_latest_matching_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            with open(json_path, "wb") as report_file:
                report_file.write(b"trusted json\n")
            with open(markdown_path, "wb") as report_file:
                report_file.write(b"trusted markdown\n")
            baseline = capture_conversion_diagnostic_reports(tmp_dir)
            first = DiagnosticCollector()
            first.add("warning", "GM2GD-FIRST", "first rewrite")
            first.publish_reports(tmp_dir)
            second = DiagnosticCollector()
            second.add("error", "GM2GD-SECOND", "second rewrite")
            latest_receipt = second.publish_reports(tmp_dir)

            restore_conversion_diagnostic_reports(
                tmp_dir,
                baseline,
                latest_receipt,
            )

            with open(json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), b"trusted json\n")
            with open(markdown_path, "rb") as report_file:
                self.assertEqual(report_file.read(), b"trusted markdown\n")

    def test_restore_refuses_pair_changed_after_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline = capture_conversion_diagnostic_reports(tmp_dir)
            receipt = DiagnosticCollector().publish_reports(tmp_dir)
            with open(receipt.json_path, "ab") as report_file:
                report_file.write(b"third-party mutation\n")
            with open(receipt.markdown_path, "rb") as report_file:
                markdown_before = report_file.read()

            with self.assertRaisesRegex(OSError, "changed"):
                restore_conversion_diagnostic_reports(
                    tmp_dir,
                    baseline,
                    receipt,
                )

            with open(receipt.json_path, "rb") as report_file:
                self.assertTrue(report_file.read().endswith(b"third-party mutation\n"))
            with open(receipt.markdown_path, "rb") as report_file:
                self.assertEqual(report_file.read(), markdown_before)

    def test_restore_refuses_replaced_identity_even_with_exact_same_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline = capture_conversion_diagnostic_reports(tmp_dir)
            receipt = DiagnosticCollector().publish_reports(tmp_dir)
            with open(receipt.json_path, "rb") as report_file:
                published_json = report_file.read()
            published_mode = stat.S_IMODE(os.stat(receipt.json_path).st_mode)
            replacement_path = os.path.join(
                os.path.dirname(receipt.json_path),
                "replacement.json",
            )
            with open(replacement_path, "wb") as report_file:
                report_file.write(published_json)
            os.chmod(replacement_path, published_mode)
            os.replace(replacement_path, receipt.json_path)

            with self.assertRaisesRegex(OSError, "changed"):
                restore_conversion_diagnostic_reports(
                    tmp_dir,
                    baseline,
                    receipt,
                )

            with open(receipt.json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), published_json)
            self.assertTrue(os.path.isfile(receipt.markdown_path))

    def test_restore_refuses_mode_changed_after_receipt(self) -> None:
        if os.name == "nt":
            self.skipTest("Exact POSIX mode checks are unavailable")
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline = capture_conversion_diagnostic_reports(tmp_dir)
            receipt = DiagnosticCollector().publish_reports(tmp_dir)
            original_mode = stat.S_IMODE(os.stat(receipt.json_path).st_mode)
            changed_mode = original_mode ^ stat.S_IXUSR
            os.chmod(receipt.json_path, changed_mode)

            with self.assertRaisesRegex(OSError, "changed since publication"):
                restore_conversion_diagnostic_reports(
                    tmp_dir,
                    baseline,
                    receipt,
                )

            self.assertEqual(
                stat.S_IMODE(os.stat(receipt.json_path).st_mode),
                changed_mode,
            )
            self.assertTrue(os.path.isfile(receipt.markdown_path))

    def test_restore_refuses_snapshot_content_that_does_not_match_fingerprint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            for path, content in (
                (json_path, b"trusted json\n"),
                (markdown_path, b"trusted markdown\n"),
            ):
                with open(path, "wb") as report_file:
                    report_file.write(content)
            baseline = capture_conversion_diagnostic_reports(tmp_dir)
            receipt = DiagnosticCollector().publish_reports(tmp_dir)
            with open(receipt.json_path, "rb") as report_file:
                published_json = report_file.read()
            tampered_json = replace(
                baseline.json_report,
                content=b"tampered baseline\n",
            )
            tampered_baseline = replace(
                baseline,
                json_report=tampered_json,
            )

            with self.assertRaisesRegex(ValueError, "does not match"):
                restore_conversion_diagnostic_reports(
                    tmp_dir,
                    tampered_baseline,
                    receipt,
                )

            with open(receipt.json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), published_json)
            self.assertTrue(os.path.isfile(receipt.markdown_path))

    def test_restore_failure_rolls_back_to_published_receipt_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            with open(json_path, "wb") as report_file:
                report_file.write(b"trusted json\n")
            with open(markdown_path, "wb") as report_file:
                report_file.write(b"trusted markdown\n")
            baseline = capture_conversion_diagnostic_reports(tmp_dir)
            diagnostics = DiagnosticCollector()
            diagnostics.add("error", "GM2GD-NEW", "new receipt")
            receipt = diagnostics.publish_reports(tmp_dir)
            with open(json_path, "rb") as report_file:
                published_json = report_file.read()
            with open(markdown_path, "rb") as report_file:
                published_markdown = report_file.read()
            real_replace = os.replace

            def fail_json_restore(source: str, destination: str) -> None:
                if destination == json_path and source.endswith(".tmp"):
                    raise OSError("json restore failed")
                real_replace(source, destination)

            with patch(
                "src.conversion.diagnostics.os.replace",
                side_effect=fail_json_restore,
            ):
                with self.assertRaisesRegex(OSError, "json restore failed"):
                    restore_conversion_diagnostic_reports(
                        tmp_dir,
                        baseline,
                        receipt,
                    )

            with open(json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), published_json)
            with open(markdown_path, "rb") as report_file:
                self.assertEqual(report_file.read(), published_markdown)
            for report_path, fingerprint in (
                (json_path, receipt.json_report),
                (markdown_path, receipt.markdown_report),
            ):
                report_stat = os.stat(report_path, follow_symlinks=False)
                self.assertEqual(
                    (report_stat.st_dev, report_stat.st_ino),
                    fingerprint.identity,
                )
                self.assertEqual(
                    stat.S_IMODE(report_stat.st_mode),
                    fingerprint.mode,
                )
            self.assertEqual(
                set(os.listdir(os.path.dirname(json_path))),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

            # The same receipt remains valid after rollback even though moving
            # its inodes out and back may have changed timestamp metadata.
            restore_conversion_diagnostic_reports(
                tmp_dir,
                baseline,
                receipt,
            )
            with open(json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), b"trusted json\n")
            with open(markdown_path, "rb") as report_file:
                self.assertEqual(report_file.read(), b"trusted markdown\n")

    def test_absent_restore_failure_rolls_back_deleted_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline = capture_conversion_diagnostic_reports(tmp_dir)
            diagnostics = DiagnosticCollector()
            diagnostics.add("error", "GM2GD-NEW", "new receipt")
            receipt = diagnostics.publish_reports(tmp_dir)
            with open(receipt.json_path, "rb") as report_file:
                published_json = report_file.read()
            with open(receipt.markdown_path, "rb") as report_file:
                published_markdown = report_file.read()
            real_replace = os.replace

            def fail_json_removal(source: str, destination: str) -> None:
                if source == receipt.json_path and destination.endswith(".backup"):
                    raise OSError("json removal failed")
                real_replace(source, destination)

            with patch(
                "src.conversion.diagnostics.os.replace",
                side_effect=fail_json_removal,
            ):
                with self.assertRaisesRegex(OSError, "json removal failed"):
                    restore_conversion_diagnostic_reports(
                        tmp_dir,
                        baseline,
                        receipt,
                    )

            with open(receipt.json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), published_json)
            with open(receipt.markdown_path, "rb") as report_file:
                self.assertEqual(report_file.read(), published_markdown)
            for report_path, fingerprint in (
                (receipt.json_path, receipt.json_report),
                (receipt.markdown_path, receipt.markdown_report),
            ):
                report_stat = os.stat(report_path, follow_symlinks=False)
                self.assertEqual(
                    (report_stat.st_dev, report_stat.st_ino),
                    fingerprint.identity,
                )
            self.assertEqual(
                set(os.listdir(os.path.dirname(receipt.json_path))),
                {
                    os.path.basename(receipt.json_path),
                    os.path.basename(receipt.markdown_path),
                },
            )

            restore_conversion_diagnostic_reports(tmp_dir, baseline, receipt)
            self.assertFalse(os.path.lexists(receipt.json_path))
            self.assertFalse(os.path.lexists(receipt.markdown_path))

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
            steps=completed_conversion_step_ledger(("sprites",)),
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
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(os.stat(json_path).st_mode), 0o640)
                self.assertEqual(
                    stat.S_IMODE(os.stat(markdown_path).st_mode),
                    0o600,
                )
            self.assertEqual(
                set(os.listdir(os.path.dirname(json_path))),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_windows_readonly_attributes_survive_publish_and_restore(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            for report_path, content, mode in (
                (json_path, b"readonly json\n", 0o444),
                (markdown_path, b"writable markdown\n", 0o600),
            ):
                with open(report_path, "wb") as report_file:
                    report_file.write(content)
                os.chmod(report_path, mode)

            real_replace = os.replace
            real_unlink = os.unlink

            def windows_replace(source: str, destination: str) -> None:
                for candidate in (source, destination):
                    if os.path.lexists(candidate) and not (
                        stat.S_IMODE(os.lstat(candidate).st_mode) & stat.S_IWRITE
                    ):
                        raise PermissionError(
                            f"Windows refuses to replace read-only file: {candidate}"
                        )
                real_replace(source, destination)

            def windows_unlink(path: str) -> None:
                if os.path.lexists(path) and not (
                    stat.S_IMODE(os.lstat(path).st_mode) & stat.S_IWRITE
                ):
                    raise PermissionError(
                        f"Windows refuses to unlink read-only file: {path}"
                    )
                real_unlink(path)

            with (
                patch.object(
                    diagnostics_module,
                    "_WINDOWS_READONLY_FILE_ATTRIBUTES",
                    True,
                ),
                patch(
                    "src.conversion.diagnostics.os.replace",
                    side_effect=windows_replace,
                ),
                patch(
                    "src.conversion.diagnostics.os.unlink",
                    side_effect=windows_unlink,
                ),
            ):
                snapshot = capture_conversion_diagnostic_reports(tmp_dir)
                receipt = DiagnosticCollector().publish_reports(tmp_dir)

                self.assertFalse(
                    stat.S_IMODE(os.stat(json_path).st_mode) & stat.S_IWRITE
                )
                self.assertTrue(
                    stat.S_IMODE(os.stat(markdown_path).st_mode) & stat.S_IWRITE
                )

                restore_conversion_diagnostic_reports(
                    tmp_dir,
                    snapshot,
                    receipt,
                )

            with open(json_path, "rb") as report_file:
                self.assertEqual(report_file.read(), b"readonly json\n")
            with open(markdown_path, "rb") as report_file:
                self.assertEqual(report_file.read(), b"writable markdown\n")
            self.assertFalse(
                stat.S_IMODE(os.stat(json_path).st_mode) & stat.S_IWRITE
            )
            self.assertTrue(
                stat.S_IMODE(os.stat(markdown_path).st_mode) & stat.S_IWRITE
            )
            self.assertEqual(
                set(os.listdir(os.path.dirname(json_path))),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_windows_readonly_attributes_survive_publish_rollback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            for report_path, content in (
                (json_path, b"previous json\n"),
                (markdown_path, b"previous markdown\n"),
            ):
                with open(report_path, "wb") as report_file:
                    report_file.write(content)
                os.chmod(report_path, 0o444)

            real_replace = os.replace
            real_unlink = os.unlink
            json_publish_failed = False

            def fail_json_publish(source: str, destination: str) -> None:
                nonlocal json_publish_failed
                for candidate in (source, destination):
                    if os.path.lexists(candidate) and not (
                        stat.S_IMODE(os.lstat(candidate).st_mode) & stat.S_IWRITE
                    ):
                        raise PermissionError(
                            f"Windows refuses to replace read-only file: {candidate}"
                        )
                if (
                    destination == json_path
                    and source.endswith(".tmp")
                    and not json_publish_failed
                ):
                    json_publish_failed = True
                    raise OSError("json publish failed")
                real_replace(source, destination)

            def windows_unlink(path: str) -> None:
                if os.path.lexists(path) and not (
                    stat.S_IMODE(os.lstat(path).st_mode) & stat.S_IWRITE
                ):
                    raise PermissionError(
                        f"Windows refuses to unlink read-only file: {path}"
                    )
                real_unlink(path)

            with (
                patch.object(
                    diagnostics_module,
                    "_WINDOWS_READONLY_FILE_ATTRIBUTES",
                    True,
                ),
                patch(
                    "src.conversion.diagnostics.os.replace",
                    side_effect=fail_json_publish,
                ),
                patch(
                    "src.conversion.diagnostics.os.unlink",
                    side_effect=windows_unlink,
                ),
            ):
                with self.assertRaisesRegex(OSError, "json publish failed"):
                    DiagnosticCollector().publish_reports(tmp_dir)

            for report_path, expected_content in (
                (json_path, b"previous json\n"),
                (markdown_path, b"previous markdown\n"),
            ):
                with open(report_path, "rb") as report_file:
                    self.assertEqual(report_file.read(), expected_content)
                self.assertFalse(
                    stat.S_IMODE(os.stat(report_path).st_mode) & stat.S_IWRITE
                )
            self.assertEqual(
                set(os.listdir(os.path.dirname(json_path))),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_cleanup_fsync_failure_after_commit_still_returns_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            report_directory = os.path.dirname(json_path)
            os.makedirs(report_directory)
            for report_path, content in (
                (json_path, b"old json\n"),
                (markdown_path, b"old markdown\n"),
            ):
                with open(report_path, "wb") as report_file:
                    report_file.write(content)
            diagnostics = DiagnosticCollector()
            diagnostics.add("warning", "GM2GD-NEW", "new reports")
            real_fsync = cast(
                Callable[[str, tuple[int, int]], None],
                getattr(diagnostics_module, "_fsync_report_directory"),
            )
            cleanup_fsync_failures = 0

            def fail_cleanup_fsync(
                path: str,
                identity: tuple[int, int],
            ) -> None:
                nonlocal cleanup_fsync_failures
                remaining_backups = tuple(
                    name
                    for name in os.listdir(path)
                    if name.endswith(".backup")
                )
                if not remaining_backups:
                    cleanup_fsync_failures += 1
                    raise OSError("cleanup fsync failed")
                real_fsync(path, identity)

            with patch(
                "src.conversion.diagnostics._fsync_report_directory",
                side_effect=fail_cleanup_fsync,
            ):
                receipt = diagnostics.publish_reports(tmp_dir)

            self.assertEqual(cleanup_fsync_failures, 1)
            for report_path, fingerprint in (
                (json_path, receipt.json_report),
                (markdown_path, receipt.markdown_report),
            ):
                with open(report_path, "rb") as report_file:
                    content = report_file.read()
                self.assertEqual(
                    hashlib.sha256(content).hexdigest(),
                    fingerprint.sha256,
                )
                self.assertNotIn(b"old ", content)
            self.assertEqual(
                set(os.listdir(report_directory)),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_cleanup_accepts_unlink_that_removes_backup_then_raises(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            report_directory = os.path.dirname(json_path)
            os.makedirs(report_directory)
            for report_path, content in (
                (json_path, b"old json\n"),
                (markdown_path, b"old markdown\n"),
            ):
                with open(report_path, "wb") as report_file:
                    report_file.write(content)
            diagnostics = DiagnosticCollector()
            diagnostics.add("warning", "GM2GD-NEW", "new reports")
            real_unlink = os.unlink
            removed_then_raised = 0

            def remove_backup_then_raise(path: str) -> None:
                nonlocal removed_then_raised
                real_unlink(path)
                if path.endswith(".backup"):
                    removed_then_raised += 1
                    raise OSError("unlink reported failure after removal")

            with patch(
                "src.conversion.diagnostics.os.unlink",
                side_effect=remove_backup_then_raise,
            ):
                receipt = diagnostics.publish_reports(tmp_dir)

            self.assertEqual(removed_then_raised, 2)
            self.assertEqual(receipt.json_path, json_path)
            self.assertEqual(receipt.markdown_path, markdown_path)
            self.assertEqual(
                set(os.listdir(report_directory)),
                {os.path.basename(json_path), os.path.basename(markdown_path)},
            )

    def test_cleanup_propagates_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            report_directory = os.path.dirname(json_path)
            os.makedirs(report_directory)
            for report_path in (json_path, markdown_path):
                with open(report_path, "wb") as report_file:
                    report_file.write(b"old report\n")
            real_unlink = os.unlink

            def interrupt_backup_cleanup(path: str) -> None:
                if path.endswith(".backup"):
                    raise KeyboardInterrupt("diagnostic cleanup interrupted")
                real_unlink(path)

            with patch(
                "src.conversion.diagnostics.os.unlink",
                side_effect=interrupt_backup_cleanup,
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "diagnostic cleanup interrupted",
                ):
                    DiagnosticCollector().publish_reports(tmp_dir)

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

    def test_existing_report_modes_are_set_through_held_descriptors(
        self,
    ) -> None:
        if os.name == "nt":
            self.skipTest("Windows preserves only the read-only file attribute")
        fchmod_candidate = getattr(os, "fchmod", None)
        if not callable(fchmod_candidate):
            self.skipTest("os.fchmod is unavailable")
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            for report_path, mode in (
                (json_path, 0o640),
                (markdown_path, 0o600),
            ):
                with open(report_path, "wb") as report_file:
                    report_file.write(b"old report\n")
                os.chmod(report_path, mode)
            real_fchmod = fchmod_candidate
            fchmod_calls: list[tuple[tuple[int, int], int]] = []

            def record_fchmod(file_descriptor: int, mode: int) -> None:
                opened_stat = os.fstat(file_descriptor)
                fchmod_calls.append(
                    ((opened_stat.st_dev, opened_stat.st_ino), mode)
                )
                real_fchmod(file_descriptor, mode)

            with patch.object(os, "fchmod", side_effect=record_fchmod):
                DiagnosticCollector().publish_reports(tmp_dir)

            self.assertEqual(len(fchmod_calls), 4)
            self.assertEqual(
                sorted(mode for _identity, mode in fchmod_calls),
                [0o600, 0o600, 0o640, 0o640],
            )
            self.assertEqual(
                len({identity for identity, _mode in fchmod_calls}),
                4,
            )

    def test_existing_set_id_modes_are_preserved_after_staging_writes(
        self,
    ) -> None:
        if os.name == "nt" or not callable(getattr(os, "fchmod", None)):
            self.skipTest("POSIX descriptor mode preservation is unavailable")
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = os.path.join(tmp_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
            markdown_path = os.path.join(
                tmp_dir,
                DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
            )
            os.makedirs(os.path.dirname(json_path))
            expected_modes = {
                json_path: 0o4750,
                markdown_path: 0o2750,
            }
            for report_path, mode in expected_modes.items():
                with open(report_path, "wb") as report_file:
                    report_file.write(b"old report\n")
                os.chmod(report_path, mode)
                if stat.S_IMODE(os.stat(report_path).st_mode) != mode:
                    self.skipTest("The test filesystem does not retain set-ID modes")

            DiagnosticCollector().publish_reports(tmp_dir)

            for report_path, mode in expected_modes.items():
                self.assertEqual(
                    stat.S_IMODE(os.stat(report_path).st_mode),
                    mode,
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
