from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import run_required_unittest as runner


class _RunnerFixture(unittest.TestCase):
    def test_success(self) -> None:
        self.assertTrue(True)


class TestRequiredUnittestRunner(unittest.TestCase):
    def test_module_entry_points_work_without_pythonpath(self) -> None:
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        for module in ("scripts.run_required_unittest", "scripts.capture_conversion_parity"):
            with self.subTest(module=module):
                completed = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("--manifest", completed.stdout)
                self.assertEqual(completed.stderr, "")

    def test_load_gate_requires_schema_and_exact_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            manifest = Path(temporary_root) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "gates": {
                            "R01": {
                                "validation_kind": "conversion-parity",
                                "unittest_ids": [
                                    "tests.test_required_unittest_runner._RunnerFixture.test_success"
                                ],
                                "required_environment": {},
                                "required_paths": ["required.txt"],
                                "allowed_skips": {},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            definition = runner.load_gate(manifest, "R01")
            self.assertEqual(definition.gate, "R01")
            self.assertEqual(definition.required_paths, ("required.txt",))
            with self.assertRaises(runner.ManifestError):
                runner.load_gate(manifest, "R02")

    def test_run_gate_records_exact_discovered_test_ids(self) -> None:
        definition = runner.GateDefinition(
            gate="R01",
            unittest_ids=(
                "tests.test_required_unittest_runner._RunnerFixture.test_success",
            ),
            required_environment={},
            required_paths=(),
            allowed_skips={},
        )
        status, receipt = runner.run_gate(
            definition,
            root=Path(__file__).resolve().parents[1],
            stream=StringIO(),
        )
        self.assertEqual(status, 0)
        self.assertEqual(receipt["tests_run"], 1)
        self.assertEqual(
            receipt["selected_test_ids"],
            ["tests.test_required_unittest_runner._RunnerFixture.test_success"],
        )

    def test_suite_loading_preserves_import_search_paths(self) -> None:
        original_paths = list(sys.path)
        _suite, discovered = runner.load_suite(
            ("tests.test_required_unittest_runner._RunnerFixture.test_success",)
        )
        self.assertEqual(len(discovered), 1)
        self.assertEqual(sys.path, original_paths)

    def test_skips_require_the_exact_manifest_reason(self) -> None:
        case = _RunnerFixture("test_success")
        result = unittest.TestResult()
        result.startTest(case)
        result.addSkip(case, "native capability unavailable")
        result.stopTest(case)
        self.assertFalse(runner.result_is_allowed(result, {}))
        self.assertTrue(
            runner.result_is_allowed(
                result,
                {case.id(): "native capability unavailable"},
            )
        )

    def test_runner_stops_before_tests_and_receipt_when_parity_preflight_fails(self) -> None:
        gate = runner.GateDefinition(
            gate="R01",
            unittest_ids=(
                "tests.test_required_unittest_runner._RunnerFixture.test_success",
            ),
            required_environment={},
            required_paths=(),
            allowed_skips={},
        )
        with (
            patch.object(runner, "load_gate", return_value=gate),
            patch.object(runner, "verify_prerequisites"),
            patch.object(
                runner,
                "load_parity_definition",
                return_value=object(),
            ),
            patch.object(
                runner,
                "validate_parity_inputs",
                side_effect=runner.ParityError("bad parity input"),
            ),
            patch.object(runner, "run_gate") as run_gate,
            patch.object(runner, "write_receipt") as write_receipt,
        ):
            status = runner.main(
                [
                    "--manifest",
                    "manifest.json",
                    "--gate",
                    "R01",
                    "--receipt",
                    "receipt.json",
                ]
            )
        self.assertEqual(status, 2)
        run_gate.assert_not_called()
        write_receipt.assert_not_called()
    def test_write_receipt_is_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            receipt_path = Path(temporary_root) / "nested" / "receipt.json"
            runner.write_receipt(receipt_path, {"z": [1], "a": "value"})
            self.assertEqual(
                receipt_path.read_text(encoding="utf-8"),
                '{\n  "a": "value",\n  "z": [\n    1\n  ]\n}\n',
            )


if __name__ == "__main__":
    unittest.main()
