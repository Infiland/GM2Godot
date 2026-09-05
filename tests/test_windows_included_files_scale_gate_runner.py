from __future__ import annotations

import os
import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import ANY, patch

from scripts import run_windows_included_files_scale_gate as scale_gate

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestWindowsIncludedFilesScaleGateRunner(unittest.TestCase):
    @staticmethod
    def _suite(test_case: unittest.TestCase) -> unittest.TestSuite:
        return unittest.TestSuite((test_case,))

    def _run_case(self, test_case: unittest.TestCase) -> tuple[int, str]:
        stream = StringIO()
        status = scale_gate.run_exact_suite(
            self._suite(test_case),
            stream=stream,
        )
        return status, stream.getvalue()

    def test_target_is_the_exact_ten_thousand_entry_case(self) -> None:
        self.assertEqual(
            scale_gate.EXACT_TEST_NAME,
            "tests.test_included_files.TestIncludedFilesManagedRootTransaction."
            "test_ten_thousand_entry_compact_records_publish_and_recover_below_cap",
        )

    def test_exact_passing_case_succeeds(self) -> None:
        status, output = self._run_case(unittest.FunctionTestCase(lambda: None))

        self.assertEqual(status, 0)
        self.assertIn("Ran 1 test", output)
        self.assertIn("OK", output)

    def test_empty_or_duplicate_collection_fails_before_execution(self) -> None:
        for count in (0, 2):
            with self.subTest(count=count):
                suite = unittest.TestSuite(
                    unittest.FunctionTestCase(lambda: None)
                    for _index in range(count)
                )
                stream = StringIO()

                status = scale_gate.run_exact_suite(suite, stream=stream)

                self.assertEqual(status, 2)
                self.assertIn(
                    f"must collect exactly one test; collected {count}",
                    stream.getvalue(),
                )

    def test_decorator_skip_is_a_gate_failure(self) -> None:
        class DecoratorSkippedCase(unittest.TestCase):
            @unittest.skip("injected decorator skip")
            def runTest(self) -> None:
                self.fail("the skipped body must not execute")

        status, output = self._run_case(DecoratorSkippedCase())

        self.assertEqual(status, 1)
        self.assertIn("skipped", output)
        self.assertIn("requires exactly one executed passing test", output)

    def test_setup_skip_is_a_gate_failure(self) -> None:
        class SetupSkippedCase(unittest.TestCase):
            def setUp(self) -> None:
                self.skipTest("injected setup skip")

            def runTest(self) -> None:
                self.fail("the skipped body must not execute")

        status, output = self._run_case(SetupSkippedCase())

        self.assertEqual(status, 1)
        self.assertIn("injected setup skip", output)
        self.assertIn("zero skips", output)

    def test_failure_and_error_are_gate_failures(self) -> None:
        def fail() -> None:
            raise AssertionError("injected failure")

        def error() -> None:
            raise RuntimeError("injected error")

        for case, expected in (
            (unittest.FunctionTestCase(fail), "injected failure"),
            (unittest.FunctionTestCase(error), "injected error"),
        ):
            with self.subTest(expected=expected):
                status, output = self._run_case(case)

                self.assertEqual(status, 1)
                self.assertIn(expected, output)

    def test_expected_failure_and_unexpected_success_are_gate_failures(
        self,
    ) -> None:
        class ExpectedFailureCase(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self) -> None:
                self.fail("injected expected failure")

        class UnexpectedSuccessCase(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self) -> None:
                pass

        for case, expected in (
            (ExpectedFailureCase(), "expected failure"),
            (UnexpectedSuccessCase(), "unexpected success"),
        ):
            with self.subTest(expected=expected):
                status, output = self._run_case(case)

                self.assertEqual(status, 1)
                self.assertIn(expected, output.lower())

    def test_main_rejects_non_ci_missing_require_and_skip_conflict(self) -> None:
        environments: tuple[tuple[dict[str, str], str], ...] = (
            ({}, "may only run in GitHub Actions"),
            ({"GITHUB_ACTIONS": "true"}, "=1 is required"),
            (
                {
                    "GITHUB_ACTIONS": "true",
                    scale_gate.REQUIRE_ENVIRONMENT_VARIABLE: "1",
                    scale_gate.SKIP_ENVIRONMENT_VARIABLE: "1",
                },
                "conflicts with the required gate",
            ),
        )
        for environment, expected in environments:
            with self.subTest(expected=expected), patch.dict(
                os.environ,
                environment,
                clear=True,
            ), patch("sys.stderr", new_callable=StringIO) as stderr:
                status = scale_gate.main()

                self.assertEqual(status, 2)
                self.assertIn(expected, stderr.getvalue())

    def test_module_entrypoint_executes_fail_closed_runner(self) -> None:
        environment = os.environ.copy()
        environment.pop("GITHUB_ACTIONS", None)
        environment.pop(scale_gate.REQUIRE_ENVIRONMENT_VARIABLE, None)
        environment.pop(scale_gate.SKIP_ENVIRONMENT_VARIABLE, None)

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.run_windows_included_files_scale_gate",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("may only run in GitHub Actions", completed.stderr)

    def test_main_loads_only_exact_test_and_propagates_runner_status(
        self,
    ) -> None:
        for runner_status in (0, 1, 2):
            with self.subTest(runner_status=runner_status):
                suite = self._suite(unittest.FunctionTestCase(lambda: None))
                with (
                    patch.dict(
                        os.environ,
                        {
                            "GITHUB_ACTIONS": "true",
                            scale_gate.REQUIRE_ENVIRONMENT_VARIABLE: "1",
                        },
                        clear=True,
                    ),
                    patch.object(
                        unittest.defaultTestLoader,
                        "loadTestsFromName",
                        return_value=suite,
                    ) as load_tests,
                    patch.object(
                        scale_gate,
                        "run_exact_suite",
                        return_value=runner_status,
                    ) as run_suite,
                ):
                    status = scale_gate.main()

                self.assertEqual(status, runner_status)
                load_tests.assert_called_once_with(scale_gate.EXACT_TEST_NAME)
                run_suite.assert_called_once_with(suite, stream=ANY)

    def test_main_converts_fixture_system_exit_zero_to_failure(self) -> None:
        class ExitFromClassFixtureCase(unittest.TestCase):
            @classmethod
            def setUpClass(cls) -> None:
                raise SystemExit(0)

            def runTest(self) -> None:
                self.fail("the fixture must prevent execution")

        suite = self._suite(ExitFromClassFixtureCase())
        with (
            patch.dict(
                os.environ,
                {
                    "GITHUB_ACTIONS": "true",
                    scale_gate.REQUIRE_ENVIRONMENT_VARIABLE: "1",
                },
                clear=True,
            ),
            patch.object(
                unittest.defaultTestLoader,
                "loadTestsFromName",
                return_value=suite,
            ),
            patch("sys.stderr", new_callable=StringIO) as stderr,
        ):
            status = scale_gate.main()

        self.assertEqual(status, 1)
        self.assertIn("unexpected SystemExit(0)", stderr.getvalue())
        self.assertIn("refusing a successful process exit", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
