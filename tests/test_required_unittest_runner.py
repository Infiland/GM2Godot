from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from dataclasses import replace
from typing import cast
from unittest.mock import patch

from scripts._anchored_output import AnchoredOutputError
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

    def test_load_gate_requires_an_exact_integer_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            manifest = Path(temporary_root) / "manifest.json"
            for schema_version in (True, 1.0):
                with self.subTest(schema_version=repr(schema_version)):
                    manifest.write_text(json.dumps({
                        "schema_version": schema_version,
                        "gates": {"R01": {
                            "validation_kind": "conversion-parity",
                            "unittest_ids": [
                                "tests.test_required_unittest_runner._RunnerFixture.test_success"
                            ],
                            "required_environment": {},
                            "required_paths": ["required.txt"],
                            "allowed_skips": {},
                        }},
                    }), encoding="utf-8")
                    with self.assertRaisesRegex(runner.ManifestError, "schema_version 1"):
                        runner.load_gate(manifest, "R01")

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
        self.assertEqual(receipt["completed_test_ids"], receipt["selected_test_ids"])
        self.assertTrue(receipt["successful"])
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

    def test_suite_loading_rejects_zero_collection(self) -> None:
        with patch.object(
            unittest.defaultTestLoader,
            "loadTestsFromName",
            return_value=unittest.TestSuite(),
        ):
            with self.assertRaisesRegex(runner.ManifestError, "collected no tests"):
                runner.load_suite(("empty.target",))

    def test_suite_loading_rejects_duplicate_and_overlapping_test_ids(self) -> None:
        fixture_id = "tests.test_required_unittest_runner._RunnerFixture.test_success"
        fixture_class = "tests.test_required_unittest_runner._RunnerFixture"
        for targets in ((fixture_id, fixture_id), (fixture_class, fixture_id)):
            with self.subTest(targets=targets):
                with self.assertRaisesRegex(runner.ManifestError, "duplicate test IDs"):
                    runner.load_suite(targets)

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

    def test_early_stopped_suite_cannot_report_success(self) -> None:
        class StopsSuite(unittest.TestCase):
            def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult:
                completed = super().run(result)
                assert completed is not None
                completed.stop()
                return completed

            def test_first(self) -> None:
                pass

            def test_second(self) -> None:
                raise AssertionError("The required second test must execute")

        first, second = StopsSuite("test_first"), StopsSuite("test_second")
        definition = runner.GateDefinition("R01", ("target",), {}, (), {})
        with patch.object(runner, "load_suite", return_value=(
            unittest.TestSuite((first, second)), (first.id(), second.id())
        )):
            status, receipt = runner.run_gate(definition, root=Path.cwd(), stream=StringIO())
        self.assertEqual(status, 1)
        self.assertEqual(receipt["tests_run"], 1)
        self.assertEqual(receipt["selected_test_ids"], [first.id(), second.id()])
        self.assertEqual(receipt["started_test_ids"], [first.id()])
        self.assertEqual(receipt["completed_test_ids"], [first.id()])
        self.assertFalse(receipt["successful"])

    def test_zero_results_and_unapproved_skips_are_unsuccessful(self) -> None:
        self.assertFalse(runner.result_is_allowed(unittest.TestResult(), {}))
        case = _RunnerFixture("test_success")
        definition = runner.GateDefinition("R01", ("target",), {}, (), {})

        def skip_case(result: unittest.TestResult) -> unittest.TestResult:
            result.startTest(case)
            result.addSkip(case, "missing native capability")
            result.stopTest(case)
            return result

        with (
            patch.object(case, "run", side_effect=skip_case),
            patch.object(runner, "load_suite", return_value=(
                unittest.TestSuite((case,)), (case.id(),)
            )),
        ):
            status, receipt = runner.run_gate(definition, root=Path.cwd(), stream=StringIO())
        self.assertEqual(status, 1)
        self.assertFalse(receipt["successful"])
        self.assertEqual(receipt["skips"], {case.id(): "missing native capability"})

    def test_zero_execution_is_rejected_for_empty_and_nonempty_selections(self) -> None:
        case = _RunnerFixture("test_success")

        def never_start(result: unittest.TestResult) -> unittest.TestResult:
            result.testsRun += 1
            result.addSuccess(case)
            return result

        for selected in ((), (case.id(),)):
            with self.subTest(selected=selected):
                cases = (case,) if selected else ()
                with patch.object(case, "run", side_effect=never_start):
                    status, receipt = self._run_fixture_suite(cases, selected)
                self.assertEqual(status, 1)
                self.assertEqual(receipt["selected_test_ids"], list(selected))
                self.assertEqual(receipt["tests_run"], 1 if selected else 0)
                self.assertEqual(receipt["started_test_ids"], [])
                self.assertEqual(receipt["completed_test_ids"], [])
                self.assertFalse(receipt["successful"])

    def test_reported_success_requires_actual_completion(self) -> None:
        case = _RunnerFixture("test_success")

        def never_complete(result: unittest.TestResult) -> unittest.TestResult:
            result.startTest(case)
            result.addSuccess(case)
            return result

        with patch.object(case, "run", side_effect=never_complete):
            status, receipt = self._run_fixture_suite((case,))
        self.assertEqual(status, 1)
        self.assertEqual(receipt["tests_run"], 1)
        self.assertEqual(receipt["started_test_ids"], [case.id()])
        self.assertEqual(receipt["completed_test_ids"], [])
        self.assertEqual(receipt["failures"], [])
        self.assertEqual(receipt["errors"], [])
        self.assertFalse(receipt["successful"])

    def test_completion_identity_is_checked_independently_from_start_identity(self) -> None:
        case = _RunnerFixture("test_success")

        def other_test() -> None:
            pass

        other = unittest.FunctionTestCase(other_test)

        def complete_wrong_case(result: unittest.TestResult) -> unittest.TestResult:
            result.startTest(case)
            result.addSuccess(case)
            result.stopTest(other)
            return result

        with patch.object(case, "run", side_effect=complete_wrong_case):
            status, receipt = self._run_fixture_suite((case,))
        self.assertEqual(status, 1)
        self.assertEqual(receipt["tests_run"], 1)
        self.assertEqual(receipt["selected_test_ids"], [case.id()])
        self.assertEqual(receipt["started_test_ids"], [case.id()])
        self.assertEqual(receipt["completed_test_ids"], [other.id()])
        self.assertFalse(receipt["successful"])

    def test_exact_completion_identity_is_required_even_when_count_matches(self) -> None:
        definition = runner.GateDefinition("R01", ("target",), {}, (), {})
        case = _RunnerFixture("test_success")
        with patch.object(runner, "load_suite", return_value=(
            unittest.TestSuite((case,)), ("wrong.test.id",)
        )):
            status, receipt = runner.run_gate(definition, root=Path.cwd(), stream=StringIO())
        self.assertEqual(status, 1)
        self.assertEqual(receipt["tests_run"], 1)
        self.assertEqual(receipt["selected_test_ids"], ["wrong.test.id"])
        self.assertEqual(receipt["started_test_ids"], [case.id()])
        self.assertEqual(receipt["completed_test_ids"], [case.id()])
        self.assertFalse(receipt["successful"])

    def test_reordered_or_duplicated_execution_cannot_satisfy_exact_selection(self) -> None:
        class Successes(unittest.TestCase):
            def test_first(self) -> None:
                pass

            def test_second(self) -> None:
                pass

        selected = (Successes("test_first").id(), Successes("test_second").id())
        executions = (
            ("test_second", "test_first"),
            ("test_first", "test_first"),
            ("test_first", "test_second", "test_first"),
        )
        for methods in executions:
            with self.subTest(methods=methods):
                cases = tuple(Successes(method) for method in methods)
                status, receipt = self._run_fixture_suite(cases, selected)
                executed = [case.id() for case in cases]
                self.assertEqual(status, 1)
                self.assertEqual(receipt["selected_test_ids"], list(selected))
                self.assertEqual(receipt["tests_run"], len(cases))
                self.assertEqual(receipt["started_test_ids"], executed)
                self.assertEqual(receipt["completed_test_ids"], executed)
                self.assertFalse(receipt["successful"])

    def test_failed_outcomes_are_rejected_after_complete_execution(self) -> None:
        class Outcomes(unittest.TestCase):
            def test_failure(self) -> None:
                raise AssertionError("required assertion failed")

            def test_error(self) -> None:
                raise RuntimeError("required test errored")

            @unittest.expectedFailure
            def test_expected_failure(self) -> None:
                raise AssertionError("expected failure still violates the required gate")

            @unittest.expectedFailure
            def test_unexpected_success(self) -> None:
                pass

            def test_system_exit(self) -> None:
                raise SystemExit(0)

        outcomes = (
            ("test_failure", "failures"),
            ("test_error", "errors"),
            ("test_expected_failure", "expected_failures"),
            ("test_unexpected_success", "unexpected_successes"),
            ("test_system_exit", "errors"),
        )
        for method, outcome in outcomes:
            with self.subTest(method=method):
                case = Outcomes(method)
                status, receipt = self._run_fixture_suite((case,))
                self.assertEqual(status, 1)
                self.assertEqual(receipt["tests_run"], 1)
                self.assertEqual(receipt["selected_test_ids"], [case.id()])
                self.assertEqual(receipt["started_test_ids"], [case.id()])
                self.assertEqual(receipt["completed_test_ids"], [case.id()])
                for field in ("failures", "errors", "expected_failures", "unexpected_successes"):
                    self.assertEqual(receipt[field], [case.id()] if field == outcome else [])
                self.assertFalse(receipt["successful"])

    def test_skip_policy_requires_exact_ids_reasons_and_observed_skips(self) -> None:
        reason = "native capability unavailable"

        class Skipped(unittest.TestCase):
            @unittest.skip(reason)
            def test_native_gate(self) -> None:
                raise AssertionError("a skipped test body must not execute")

        case_id = Skipped("test_native_gate").id()
        policies: tuple[tuple[dict[str, str], int], ...] = (
            ({}, 1),
            ({case_id: reason}, 0),
            ({case_id: "different reason"}, 1),
            ({"different.test.id": reason}, 1),
            ({case_id: reason, "unused.test.id": reason}, 1),
        )
        for allowed_skips, expected_status in policies:
            with self.subTest(allowed_skips=allowed_skips):
                case = Skipped("test_native_gate")
                status, receipt = self._run_fixture_suite((case,), allowed_skips=allowed_skips)
                self.assertEqual(status, expected_status)
                self.assertEqual(receipt["started_test_ids"], [case_id])
                self.assertEqual(receipt["completed_test_ids"], [case_id])
                self.assertEqual(receipt["skips"], {case_id: reason})
                self.assertEqual(receipt["successful"], expected_status == 0)

    def test_control_flow_abort_before_completion_never_writes_receipt(self) -> None:
        for interruption in (SystemExit(0), SystemExit(2), KeyboardInterrupt()):
            with self.subTest(interruption=type(interruption).__name__):
                case = _RunnerFixture("test_success")
                started: list[str] = []

                def abort_case(result: unittest.TestResult) -> unittest.TestResult:
                    result.startTest(case)
                    started.append(case.id())
                    raise interruption

                definition = runner.GateDefinition("R01", ("target",), {}, (), {})
                error_stream = StringIO()
                with (
                    patch.object(case, "run", side_effect=abort_case),
                    patch.object(runner, "load_gate", return_value=definition),
                    patch.object(runner, "verify_prerequisites"),
                    patch.object(runner, "load_parity_definition", return_value=object()),
                    patch.object(runner, "validate_parity_inputs"),
                    patch.object(runner, "load_suite", return_value=(
                        unittest.TestSuite((case,)), (case.id(),)
                    )),
                    patch.object(runner.sys, "stdout", StringIO()),
                    patch.object(runner.sys, "stderr", error_stream),
                    patch.object(runner, "write_receipt") as write_receipt,
                ):
                    status = runner.main([
                        "--manifest", "manifest.json", "--gate", "R01",
                        "--receipt", "receipt.json",
                    ])
                self.assertEqual(status, 2)
                self.assertIn("interrupted", error_stream.getvalue().lower())
                self.assertEqual(started, [case.id()])
                write_receipt.assert_not_called()

    def _run_fixture_suite(
        self,
        cases: tuple[unittest.TestCase, ...],
        selected: tuple[str, ...] | None = None,
        *,
        allowed_skips: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        definition = runner.GateDefinition("R01", ("target",), {}, (), allowed_skips or {})
        discovered = tuple(case.id() for case in cases) if selected is None else selected
        with patch.object(runner, "load_suite", return_value=(
            unittest.TestSuite(cases), discovered
        )):
            return runner.run_gate(definition, root=Path.cwd(), stream=StringIO())

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

    def test_validation_kind_is_mandatory_and_bound_to_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            for gate, kind in (("R01", None), ("R01", "unknown"), ("R01", "native-receipts"),
                               ("N01-linux", "conversion-parity"), ("R02", "conversion-parity"),
                               ("N01-other", "native-receipts")):
                row: dict[str, object] = {
                    "unittest_ids": ["tests.test_required_unittest_runner._RunnerFixture.test_success"],
                    "required_paths": ["required.txt"], "required_environment": {}, "allowed_skips": {},
                    "runtime": {"python_version": "3.12.13", "platform": "linux", "machine": "x86_64"},
                }
                if kind is not None:
                    row["validation_kind"] = kind
                path.write_text(json.dumps({"schema_version": 1, "gates": {gate: row}}), encoding="utf-8")
                with self.subTest(gate=gate, kind=kind), self.assertRaises(runner.ManifestError):
                    runner.load_gate(path, gate)

    def test_native_inventory_runtime_and_zero_skip_policy_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            for gate in ("N01-linux", "N01-macos", "N01-windows"):
                runtime = runner.NATIVE_GATE_RUNTIMES[gate]
                row: dict[str, object] = {
                    "validation_kind": "native-receipts", "unittest_ids": list(runner.NATIVE_GATE_TEST_IDS[gate]),
                    "required_paths": ["required.txt"], "required_environment": {}, "allowed_skips": {},
                    "runtime": {"python_version": runtime.python_version, "platform": runtime.platform_name,
                                "machine": runtime.machine},
                }
                path.write_text(json.dumps({"schema_version": 1, "gates": {gate: row}}), encoding="utf-8")
                definition = runner.load_gate(path, gate)
                self.assertEqual(definition.native_runtime, runtime)
                self.assertEqual(len(definition.unittest_ids), {"N01-linux": 10, "N01-macos": 13, "N01-windows": 17}[gate])
                mutations: tuple[tuple[str, object], ...] = (
                    ("unittest_ids", list(definition.unittest_ids[:-1])),
                    ("unittest_ids", list(reversed(definition.unittest_ids))),
                    ("unittest_ids", [definition.unittest_ids[0], definition.unittest_ids[0]]),
                    ("unittest_ids", ["tests.test_native_receipt_producers"]),
                    ("allowed_skips", {definition.unittest_ids[0]: "not supported"}),
                    ("required_environment", {"GODOT_BIN": "required-executable"}),
                    ("runtime", {"python_version": "3.12.99", "platform": runtime.platform_name, "machine": runtime.machine}),
                    ("runtime", {"python_version": runtime.python_version, "platform": "other", "machine": runtime.machine}),
                    ("runtime", {"python_version": runtime.python_version, "platform": runtime.platform_name, "machine": "other"}),
                    ("runtime", {"python_version": runtime.python_version, "platform": runtime.platform_name, "machine": runtime.machine, "extra": "ignored"}),
                )
                for field, value in mutations:
                    malformed = {**row, field: value}
                    path.write_text(json.dumps({"schema_version": 1, "gates": {gate: malformed}}), encoding="utf-8")
                    with self.subTest(gate=gate, field=field, value=value), self.assertRaises(runner.ManifestError):
                        runner.load_gate(path, gate)

    def test_native_runtime_is_checked_before_collection(self) -> None:
        definition = self._native_definition()
        runtime = cast(runner.NativeRuntimeRequirement, definition.native_runtime)
        with patch.object(runner.platform, "python_version", return_value=runtime.python_version), patch.object(
            runner.sys, "platform", runtime.platform_name
        ), patch.object(runner.platform, "machine", return_value="wrong-machine"), patch.object(runner, "load_suite") as collect:
            with self.assertRaisesRegex(runner.ManifestError, "requires native runtime"):
                runner.run_gate(definition, root=Path.cwd(), stream=StringIO())
        collect.assert_not_called()

    def test_native_discovery_must_match_every_declared_method_before_execution(self) -> None:
        definition = self._native_definition()
        variants = (definition.unittest_ids[:-1], tuple(reversed(definition.unittest_ids)),
                    ("wrong.test.id",), ())
        for discovered in variants:
            with self.subTest(discovered=discovered), patch.object(runner, "verify_prerequisites"), patch.object(
                runner, "load_suite", return_value=(unittest.TestSuite((_RunnerFixture("test_success"),)), discovered)
            ), patch.object(unittest.TextTestRunner, "run") as execute:
                with self.assertRaisesRegex(runner.ManifestError, "exact ordered method inventory"):
                    runner.run_gate(definition, root=Path.cwd(), stream=StringIO())
            execute.assert_not_called()

    def test_native_cli_does_not_call_conversion_preflight(self) -> None:
        definition = self._native_definition()
        case = _RunnerFixture("test_success")
        with patch.object(runner, "load_gate", return_value=definition), patch.object(
            runner, "verify_prerequisites"
        ), patch.object(runner, "load_parity_definition") as parity_load, patch.object(
            runner, "validate_parity_inputs"
        ) as parity_validate, patch.object(runner, "load_suite", return_value=(
            unittest.TestSuite((case,)), (case.id(),)
        )), patch.object(runner, "write_receipt") as publish, patch.object(runner.sys, "stderr", StringIO()):
            status = runner.main(["--manifest", "manifest.json", "--gate", definition.gate, "--receipt", "receipt.json"])
        self.assertEqual(status, 2)
        parity_load.assert_not_called()
        parity_validate.assert_not_called()
        publish.assert_not_called()

    def test_test_count_requires_an_exact_positive_integer(self) -> None:
        case = _RunnerFixture("test_success")
        for count in (True, 1.0, 0, -1):
            result = unittest.TestResult()
            result.startTest(case)
            result.stopTest(case)
            setattr(result, "testsRun", count)
            with self.subTest(count=repr(count)):
                self.assertFalse(runner.result_is_allowed(result, {}))

    @staticmethod
    def _native_definition() -> runner.GateDefinition:
        return runner.GateDefinition("N01-linux", runner.NATIVE_GATE_TEST_IDS["N01-linux"], {}, (), {},
                                     "native-receipts", runner.NATIVE_GATE_RUNTIMES["N01-linux"])

    def test_native_policy_cannot_be_bypassed_by_direct_definition(self) -> None:
        definition = self._native_definition()
        for malformed in (replace(definition, allowed_skips={definition.unittest_ids[0]: "skip"}),
                          replace(definition, unittest_ids=definition.unittest_ids[:-1]),
                          replace(definition, validation_kind="conversion-parity")):
            with self.subTest(definition=malformed), patch.object(runner, "load_suite") as collect:
                with self.assertRaises(runner.ManifestError):
                    runner.run_gate(malformed, root=Path.cwd(), stream=StringIO())
            collect.assert_not_called()

    def test_writer_preserves_native_text_bytes_and_identical_identity(self) -> None:
        payload = {"z": [1], "a": "value\nline\r\nUnicode Ω"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.json"
            with baseline.open("w", encoding="utf-8") as file:
                file.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            receipt = root / "nested" / "receipt.json"
            runner.write_receipt(receipt, payload)
            self.assertEqual(receipt.read_bytes(), baseline.read_bytes())
            identity = (receipt.stat().st_dev, receipt.stat().st_ino)
            runner.write_receipt(receipt, payload)
            self.assertEqual((receipt.stat().st_dev, receipt.stat().st_ino), identity)
            with self.assertRaises(AnchoredOutputError) as error:
                runner.write_receipt(receipt, {"different": True})
            self.assertEqual(error.exception.code, "output-different")
            self.assertEqual(receipt.read_bytes(), baseline.read_bytes())
            self.assertEqual((receipt.stat().st_dev, receipt.stat().st_ino), identity)

    def test_windows_structural_newlines_are_preserved_without_platform_faking(self) -> None:
        payload = {"line": "escaped\nvalue"}
        with patch.object(runner.os, "linesep", "\r\n"), patch.object(runner, "publish_identical_receipt_bytes") as publish:
            runner.write_receipt(Path("receipt.json"), payload)
        publish.assert_called_once_with(Path("receipt.json"), (json.dumps(payload, indent=2, sort_keys=True) + "\n").replace("\n", "\r\n").encode("utf-8"))

    def test_writer_preserves_primary_controls(self) -> None:
        for interruption in (KeyboardInterrupt(), SystemExit(0), SystemExit(7)):
            with self.subTest(interruption=type(interruption).__name__), patch.object(
                runner, "publish_identical_receipt_bytes", side_effect=interruption
            ):
                with self.assertRaises(type(interruption)) as caught:
                    runner.write_receipt(Path("receipt.json"), {"receipt": "test"})
            self.assertIs(caught.exception, interruption)

    def test_runner_cli_reports_anchored_code_cause_and_notes(self) -> None:
        definition = runner.GateDefinition("R01", ("tests.test_required_unittest_runner._RunnerFixture.test_success",), {}, (), {})
        error = AnchoredOutputError("output-different", "existing bytes differ")
        error.__cause__ = OSError("causal failure")
        error.add_note("owned cleanup detail")
        stderr = StringIO()
        with patch.object(runner, "load_gate", return_value=definition), patch.object(
            runner, "load_parity_definition", return_value=object()
        ), patch.object(runner, "validate_parity_inputs"), patch.object(runner, "write_receipt", side_effect=error), patch.object(
            runner.sys, "stdout", StringIO()
        ), patch.object(runner.sys, "stderr", stderr):
            status = runner.main(["--manifest", "manifest.json", "--gate", "R01", "--receipt", "receipt.json"])
        self.assertEqual(status, 2)
        for expected in ("output-different", "causal failure", "owned cleanup detail", "fresh receipt path"):
            self.assertIn(expected, stderr.getvalue())

    def test_writer_controls_exit_cli_nonzero_after_actual_execution(self) -> None:
        definition = runner.GateDefinition("R01", ("tests.test_required_unittest_runner._RunnerFixture.test_success",), {}, (), {})
        for interruption in (KeyboardInterrupt(), SystemExit(0), SystemExit(7)):
            stderr = StringIO()
            interruption.add_note("control cleanup detail")
            with self.subTest(interruption=type(interruption).__name__), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "receipt.json"
                path.write_bytes(b"prior immutable receipt")
                identity = (path.stat().st_dev, path.stat().st_ino)
                with patch.object(runner, "load_gate", return_value=definition), patch.object(
                    runner, "load_parity_definition", return_value=object()
                ), patch.object(runner, "validate_parity_inputs"), patch.object(
                    runner, "write_receipt", side_effect=interruption
                ), patch.object(runner.sys, "stdout", StringIO()), patch.object(runner.sys, "stderr", stderr):
                    status = runner.main(["--manifest", "manifest.json", "--gate", "R01", "--receipt", str(path)])
                self.assertEqual(status, 2)
                self.assertIn("publication interrupted", stderr.getvalue())
                self.assertIn("control cleanup detail", stderr.getvalue())
                self.assertIn("may remain", stderr.getvalue())
                self.assertEqual(path.read_bytes(), b"prior immutable receipt")
                self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)

    def test_receipt_cli_bounds_messages_and_notes_without_mutating_errors(self) -> None:
        definition = runner.GateDefinition("R01", ("tests.test_required_unittest_runner._RunnerFixture.test_success",), {}, (), {})
        errors = (AnchoredOutputError("output-different", "primary-" * 1000),
                  KeyboardInterrupt("primary-" * 1000), SystemExit(0), SystemExit(7))
        for error in errors:
            cause = OSError("causal-" * 1000)
            error.__cause__ = cause
            notes = [f"note-{index:02d}-" + "detail-" * 1000 for index in range(12)]
            for note in notes:
                error.add_note(note)
            original_text = str(error)
            stderr = StringIO()
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "receipt.json"
                path.write_bytes(b"prior immutable receipt")
                identity = (path.stat().st_dev, path.stat().st_ino)
                with patch.object(runner, "load_gate", return_value=definition), patch.object(
                    runner, "load_parity_definition", return_value=object()
                ), patch.object(runner, "validate_parity_inputs"), patch.object(
                    runner, "write_receipt", side_effect=error
                ), patch.object(runner.sys, "stdout", StringIO()), patch.object(runner.sys, "stderr", stderr):
                    status = runner.main(["--manifest", "manifest.json", "--gate", "R01", "--receipt", str(path)])
                self.assertEqual(status, 2)
                self.assertEqual(path.read_bytes(), b"prior immutable receipt")
                self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)
            lines = stderr.getvalue().splitlines()
            self.assertTrue(lines[0].startswith("receipt publication"))
            if len(original_text) > 512:
                self.assertIn("primary-", lines[0])
                self.assertTrue(lines[0].endswith("... [truncated]"))
            self.assertTrue(lines[1].startswith("cause: OSError: causal-"))
            self.assertTrue(lines[1].endswith("... [truncated]"))
            self.assertLessEqual(max(len(line) for line in lines), 512)
            self.assertLessEqual(len(stderr.getvalue()), 5400)
            self.assertIn("An immutable candidate or prior identical receipt may remain", stderr.getvalue())
            self.assertEqual(sum(line.startswith("note: note-") for line in lines), 8)
            for index in range(8):
                self.assertTrue(lines[index + 2].startswith(f"note: note-{index:02d}-detail-"))
                self.assertTrue(lines[index + 2].endswith("... [truncated]"))
            self.assertIn("note: additional diagnostic notes omitted [truncated]", lines)
            self.assertNotIn("note-08-", stderr.getvalue())
            self.assertEqual(str(error), original_text)
            self.assertIs(error.__cause__, cause)
            self.assertEqual(getattr(error, "__notes__"), notes)


if __name__ == "__main__":
    unittest.main()
