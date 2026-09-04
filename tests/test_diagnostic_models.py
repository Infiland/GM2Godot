from __future__ import annotations

import ast
import hashlib
import inspect
import json
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from unittest.mock import patch

from src.conversion import (
    diagnostic_models,
    diagnostics,
    project_manifest,
    resource_models,
)
from src.conversion.diagnostic_models import (
    ConversionDiagnostic,
    ProjectManifestDiagnostic,
    ProjectSourceLocation,
    ResourceModelDiagnostic,
)
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_manifest import GameMakerProjectManifest


class TestDiagnosticModels(unittest.TestCase):
    def test_records_have_one_owner_and_compatibility_exports_keep_identity(self) -> None:
        for record in (ConversionDiagnostic, ProjectManifestDiagnostic, ResourceModelDiagnostic, ProjectSourceLocation):
            self.assertEqual(record.__module__, "src.conversion.diagnostic_models")
        self.assertIs(diagnostics.ConversionDiagnostic, ConversionDiagnostic)
        self.assertIs(diagnostics.DiagnosticSeverity, diagnostic_models.DiagnosticSeverity)
        self.assertIs(project_manifest.ProjectManifestDiagnostic, ProjectManifestDiagnostic)
        self.assertIs(diagnostic_models.ProjectManifestSeverity, diagnostic_models.DiagnosticSeverity)
        self.assertIs(diagnostic_models.ResourceModelSeverity, diagnostic_models.DiagnosticSeverity)
        for owner in (diagnostics, project_manifest, resource_models):
            definitions = {node.name for node in ast.parse(inspect.getsource(owner)).body if isinstance(node, ast.ClassDef)}
            self.assertTrue(definitions.isdisjoint({
                "ConversionDiagnostic", "ProjectManifestDiagnostic", "ResourceModelDiagnostic", "ProjectSourceLocation",
            }))

    def test_cold_model_import_loads_no_project_services(self) -> None:
        tree = ast.parse(inspect.getsource(diagnostic_models))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                self.assertIn(node.module, {"__future__", "dataclasses", "typing"})
            self.assertNotIsInstance(node, ast.Import)
        completed = subprocess.run(
            [sys.executable, "-c", (
                "import json, sys\n"
                "import src.conversion.diagnostic_models\n"
                "print(json.dumps(sorted(name for name in sys.modules if name.startswith('src.conversion.'))))"
            )],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=True, timeout=15,
        )
        self.assertEqual(completed.stderr, "")
        self.assertEqual(json.loads(completed.stdout), ["src.conversion.diagnostic_models"])

    def test_constructor_signatures_preserve_field_order_and_alias_annotations(self) -> None:
        signatures = {
            ConversionDiagnostic: (
                "(severity: 'DiagnosticSeverity', code: 'str', message: 'str', "
                "source_path: 'str | None' = None, line: 'int | None' = None, "
                "column: 'int | None' = None, resource: 'str | None' = None, "
                "resource_type: 'str | None' = None, event: 'str | None' = None, "
                "api: 'str | None' = None, manifest_entry: 'str | None' = None, "
                "issue_number: 'int | None' = None, workaround: 'str | None' = None) -> None"
            ),
            ProjectManifestDiagnostic: (
                "(severity: 'ProjectManifestSeverity', code: 'str', message: 'str', "
                "source: 'ProjectSourceLocation | None' = None, resource: 'str | None' = None, "
                "resource_type: 'str | None' = None, resource_kind: 'str | None' = None) -> None"
            ),
            ResourceModelDiagnostic: (
                "(severity: 'ResourceModelSeverity', code: 'str', message: 'str', "
                "source_path: 'str' = '', resource_name: 'str' = '', resource_kind: 'str' = '') -> None"
            ),
            ProjectSourceLocation: "(path: 'str', line: 'int', field_path: 'str' = '') -> None",
        }
        for record, expected in signatures.items():
            with self.subTest(record=record.__name__):
                self.assertEqual(str(inspect.signature(record)), expected)

    def test_records_remain_frozen_hashable_and_distinct(self) -> None:
        records = (
            ConversionDiagnostic("warning", "GM2GD-SAMPLE", "message"),
            ProjectManifestDiagnostic("warning", "GM2GD-SAMPLE", "message"),
            ResourceModelDiagnostic("warning", "GM2GD-SAMPLE", "message"),
            ProjectSourceLocation("project.yyp", 7),
        )
        for record in records:
            with self.subTest(record=type(record).__name__):
                copy = replace(record)
                self.assertEqual(record, copy)
                self.assertEqual(hash(record), hash(copy))
                field_name = next(iter(asdict(record)))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, field_name, "changed")
        self.assertEqual(len(set(records)), 4)
        self.assertEqual(records[0], ConversionDiagnostic(severity="warning", code="GM2GD-SAMPLE", message="message"))
        self.assertIsNone(records[0].source_path)
        self.assertIsNone(records[1].source)
        self.assertEqual(records[2].source_path, "")
        self.assertEqual(records[3].field_path, "")

    def test_conversion_dictionary_preserves_all_fields_and_empty_values(self) -> None:
        diagnostic = ConversionDiagnostic(
            "error", "GM2GD-SAMPLE", "unchanged", "source.yy", 0, 0,
            "", "object", "Create", "api", "resources[0]", 797, "keep field",
        )
        expected = {
            "severity": "error",
            "code": "GM2GD-SAMPLE",
            "message": "unchanged",
            "source_path": "source.yy",
            "line": 0,
            "column": 0,
            "resource": "",
            "resource_type": "object",
            "event": "Create",
            "api": "api",
            "manifest_entry": "resources[0]",
            "issue_number": 797,
            "workaround": "keep field",
        }
        self.assertEqual(diagnostic.to_dict(), expected)
        self.assertEqual(tuple(diagnostic.to_dict()), tuple(expected))
        self.assertIsNone(ConversionDiagnostic("info", "code", "message").to_dict()["source_path"])

    def test_report_bytes_preserve_sorting_escaping_and_null_fields(self) -> None:
        collector = DiagnosticCollector()
        collector.add(
            "warning", "GM2GD-SAMPLE", "Warning: A | B\nnext",
            source_path="objects/obj.yy", line=0, column=0, resource="",
            resource_type="object", event="Create", api="sample",
            manifest_entry="resources[0]", issue_number=797, workaround="Keep field",
        )
        collector.add("info", "GM2GD-INFO", "Info: preserved")
        # Captured from the unchanged e69dacd report implementation before relocation.
        self.assertEqual(
            hashlib.sha256(collector.to_json().encode()).hexdigest(),
            "c9ddc9c7fbff58585f46611187125a47f3dfd19794bb98029f385c43f9a2ca8b",
        )
        self.assertEqual(
            hashlib.sha256(collector.to_markdown().encode()).hexdigest(),
            "8262e5ddc359a0bd3aff123bb65ed20694f01d46ea680452afd847df19fbbbd7",
        )

    def test_structured_and_log_deduplication_keep_different_contracts(self) -> None:
        collector = DiagnosticCollector()
        first = collector.add("warning", "GM2GD-SAMPLE", "Warning: unchanged", line=1)
        duplicate = collector.add("warning", "GM2GD-SAMPLE", "Warning: unchanged", line=1)
        second = collector.add("warning", "GM2GD-SAMPLE", "Warning: unchanged", line=2)
        self.assertEqual(first, duplicate)
        self.assertIsNot(first, duplicate)
        self.assertIsNone(collector.add_from_log_message("  Warning: unchanged  "))
        self.assertEqual(collector.diagnostics(), (first, second))
        self.assertEqual(collector.summary(), {"info": 0, "warning": 2, "error": 0, "total": 2})

    def test_manifest_to_resource_mapping_keeps_existing_location_and_empty_rules(self) -> None:
        source = ProjectSourceLocation("project.yyp", 7, "resources[0].id.path")
        manifest = GameMakerProjectManifest(
            "project", "project.yyp", diagnostics=(
                ProjectManifestDiagnostic("warning", "GM2GD-REJECTED", "Rejected ../outside.yy", source),
                ProjectManifestDiagnostic("info", "GM2GD-MISSING", "Missing metadata"),
            ),
        )
        with patch.object(resource_models, "load_gamemaker_project_manifest", return_value=manifest):
            result = resource_models.parse_gamemaker_resource_models("unused")
        self.assertEqual(asdict(source), {"path": "project.yyp", "line": 7, "field_path": "resources[0].id.path"})
        self.assertEqual(result.diagnostics, (
            ResourceModelDiagnostic("warning", "GM2GD-REJECTED", "Rejected ../outside.yy", "project.yyp"),
            ResourceModelDiagnostic("info", "GM2GD-MISSING", "Missing metadata"),
        ))


if __name__ == "__main__":
    unittest.main()
