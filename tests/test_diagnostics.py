from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.diagnostics import (
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
    DiagnosticCollector,
)


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


if __name__ == "__main__":
    unittest.main()
