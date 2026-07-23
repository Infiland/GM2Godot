from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from typing import cast

from scripts import check_coverage


class TestCoveragePolicy(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name)
        (self.root / "src").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "main.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / "src" / "core.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / "scripts" / "tool.py").write_text("value = 1\n", encoding="utf-8")
        self.policy_path = self.root / "coverage-policy.json"
        self.report_path = self.root / "coverage.json"
        self._write_json(self.policy_path, self._policy_payload())

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _policy_payload() -> dict[str, object]:
        return {
            "schema_version": 1,
            "baseline": {
                "commit": "0" * 40,
                "coverage": "test",
                "python": "test",
                "platform": "test",
                "command": "test",
            },
            "source": {
                "files": ["main.py"],
                "directories": ["src", "scripts"],
            },
            "floors": [
                {
                    "name": "overall-production",
                    "include": ["main.py", "src/*", "scripts/*"],
                    "line": 88.0,
                    "branch": 75.0,
                    "baseline": {
                        "covered_lines": 22,
                        "statements": 25,
                        "covered_branches": 9,
                        "branches": 12,
                    },
                },
                {
                    "name": "core",
                    "include": ["src/*"],
                    "line": 90.0,
                    "branch": 66.66,
                    "baseline": {
                        "covered_lines": 9,
                        "statements": 10,
                        "covered_branches": 4,
                        "branches": 6,
                    },
                },
            ],
        }

    @staticmethod
    def _file_payload(
        *,
        covered_lines: int,
        statements: int,
        covered_branches: int,
        branches: int,
    ) -> dict[str, object]:
        return {
            "summary": {
                "covered_lines": covered_lines,
                "num_statements": statements,
                "covered_branches": covered_branches,
                "num_branches": branches,
            }
        }

    def _report_payload(self, *, branch_coverage: bool = True) -> dict[str, object]:
        return {
            "meta": {
                "branch_coverage": branch_coverage,
                "format": 3,
                "version": "test",
            },
            "files": {
                "main.py": self._file_payload(
                    covered_lines=8,
                    statements=10,
                    covered_branches=3,
                    branches=4,
                ),
                "src/core.py": self._file_payload(
                    covered_lines=9,
                    statements=10,
                    covered_branches=4,
                    branches=6,
                ),
                "scripts/tool.py": self._file_payload(
                    covered_lines=5,
                    statements=5,
                    covered_branches=2,
                    branches=2,
                ),
            },
        }

    def _invoke(self) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = check_coverage.main(
                [
                    "--policy",
                    str(self.policy_path),
                    "--report",
                    str(self.report_path),
                    "--source-root",
                    str(self.root),
                ]
            )
        return status, stdout.getvalue(), stderr.getvalue()

    def _assert_configuration_error(
        self,
        *,
        policy: dict[str, object] | None = None,
        report: dict[str, object] | None = None,
        expected: str,
    ) -> None:
        self._write_json(
            self.policy_path,
            self._policy_payload() if policy is None else policy,
        )
        self._write_json(
            self.report_path,
            self._report_payload() if report is None else report,
        )
        status, _, stderr = self._invoke()
        self.assertEqual(status, 2)
        self.assertIn(expected, stderr)

    def test_measured_line_and_branch_floors_pass_at_or_above_policy(self) -> None:
        self._write_json(self.report_path, self._report_payload())

        status, stdout, stderr = self._invoke()

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertIn("PASS overall-production", stdout)
        self.assertIn("line 88.00% (22/25, floor 88.00%)", stdout)
        self.assertIn("branch 75.00% (9/12, floor 75.00%)", stdout)
        self.assertIn("PASS core", stdout)

    def test_controlled_report_below_line_and_branch_floors_fails(self) -> None:
        payload = self._report_payload()
        files = cast(dict[str, object], payload["files"])
        files["src/core.py"] = self._file_payload(
            covered_lines=8,
            statements=10,
            covered_branches=3,
            branches=6,
        )
        self._write_json(self.report_path, payload)

        status, stdout, stderr = self._invoke()

        self.assertEqual(status, 1)
        self.assertIn("FAIL overall-production", stdout)
        self.assertIn("FAIL core", stdout)
        self.assertIn("overall-production line coverage", stderr)
        self.assertIn("overall-production branch coverage", stderr)
        self.assertIn("core line coverage", stderr)
        self.assertIn("core branch coverage", stderr)

    def test_report_without_branch_measurement_is_rejected(self) -> None:
        self._write_json(
            self.report_path,
            self._report_payload(branch_coverage=False),
        )

        status, stdout, stderr = self._invoke()

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("branch_coverage=true", stderr)

    def test_floor_must_equal_recorded_baseline_truncated_to_two_decimals(
        self,
    ) -> None:
        policy = self._policy_payload()
        floors = cast(list[dict[str, object]], policy["floors"])
        floors[0]["line"] = 87.99
        self._write_json(self.policy_path, policy)
        self._write_json(self.report_path, self._report_payload())

        status, stdout, stderr = self._invoke()

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn(
            "line must equal the baseline truncated to two decimals: 88.00",
            stderr,
        )

    def test_policy_rejects_invalid_baseline_metadata_and_duplicate_scopes(
        self,
    ) -> None:
        invalid_commit = self._policy_payload()
        baseline = cast(dict[str, object], invalid_commit["baseline"])
        baseline["commit"] = "not-a-commit"

        duplicate_scope = self._policy_payload()
        duplicate_floors = cast(
            list[dict[str, object]],
            duplicate_scope["floors"],
        )
        duplicate_floors.append(dict(duplicate_floors[0]))

        branch_mismatch = self._policy_payload()
        mismatch_floors = cast(
            list[dict[str, object]],
            branch_mismatch["floors"],
        )
        mismatch_floors[1]["branch"] = 66.65

        for label, policy, expected in (
            (
                "commit",
                invalid_commit,
                "must be a full lowercase Git commit",
            ),
            ("duplicate-scope", duplicate_scope, "floor names must be unique"),
            (
                "branch-baseline",
                branch_mismatch,
                "branch must equal the baseline truncated to two decimals",
            ),
        ):
            with self.subTest(label=label):
                self._assert_configuration_error(
                    policy=policy,
                    expected=expected,
                )

    def test_report_rejects_unsafe_paths_and_impossible_counts(self) -> None:
        unsafe_path = self._report_payload()
        unsafe_files = cast(dict[str, object], unsafe_path["files"])
        unsafe_files["src\\core.py"] = unsafe_files.pop("src/core.py")

        impossible_count = self._report_payload()
        impossible_files = cast(dict[str, object], impossible_count["files"])
        core_file = cast(dict[str, object], impossible_files["src/core.py"])
        core_summary = cast(dict[str, object], core_file["summary"])
        core_summary["covered_lines"] = 11

        empty_report = self._report_payload()
        empty_report["files"] = {}

        for label, report, expected in (
            ("unsafe-path", unsafe_path, "must use forward slashes"),
            (
                "impossible-count",
                impossible_count,
                "covered_lines exceeds num_statements",
            ),
            ("empty-report", empty_report, "files must not be empty"),
        ):
            with self.subTest(label=label):
                self._assert_configuration_error(
                    report=report,
                    expected=expected,
                )

    def test_configured_sources_and_floor_patterns_must_resolve(self) -> None:
        missing_directory = self._policy_payload()
        source = cast(dict[str, object], missing_directory["source"])
        directories = cast(list[str], source["directories"])
        directories.append("missing")

        unmatched_scope = self._policy_payload()
        floors = cast(list[dict[str, object]], unmatched_scope["floors"])
        floors[1]["include"] = ["unmatched/*"]

        for label, policy, expected in (
            (
                "missing-directory",
                missing_directory,
                "source directory does not exist: missing",
            ),
            ("unmatched-scope", unmatched_scope, "matched no production files"),
        ):
            with self.subTest(label=label):
                self._assert_configuration_error(
                    policy=policy,
                    expected=expected,
                )

    def test_missing_or_malformed_report_is_actionable(self) -> None:
        self.report_path.unlink(missing_ok=True)
        status, stdout, stderr = self._invoke()
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("cannot read coverage report", stderr)

        self.report_path.write_text("{", encoding="utf-8")
        status, stdout, stderr = self._invoke()
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("is not valid JSON", stderr)

    def test_report_must_cover_exact_configured_production_scope(self) -> None:
        payload = self._report_payload()
        files = cast(dict[str, object], payload["files"])
        del files["scripts/tool.py"]
        files["tests/test_core.py"] = self._file_payload(
            covered_lines=1,
            statements=1,
            covered_branches=0,
            branches=0,
        )
        self._write_json(self.report_path, payload)

        status, stdout, stderr = self._invoke()

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("missing production files: scripts/tool.py", stderr)
        self.assertIn("unexpected files: tests/test_core.py", stderr)


if __name__ == "__main__":
    unittest.main()
