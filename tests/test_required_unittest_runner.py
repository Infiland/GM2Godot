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


if __name__ == "__main__":
    unittest.main()
