"""Protect the finite same-revision CI graph and execute its terminal gates."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
REQUIRED_WORKFLOWS = {
    "tests": "tests.yml",
    "pyright": "pyright.yml",
    "code-health": "code-health.yml",
    "godot": "godot-smoke.yml",
    "conversion": "tcc-conversion-test.yml",
    "dependencies": "dependency-locks.yml",
    "release-smoke": "release-action-smoke.yml",
}
REQUIRED_JOBS = {
    "tests.yml": (
        "test",
        "macos-managed-output-transactions",
        "windows-artifact-transactions",
        "windows-included-files-scale",
        "windows-managed-output-crash-recovery",
    ),
    "pyright.yml": ("pyright",),
    "code-health.yml": ("ruff",),
    "godot-smoke.yml": ("godot-smoke",),
    "tcc-conversion-test.yml": ("tcc-conversion", "lts-2026-conversion"),
    "dependency-locks.yml": ("generate", "submit-dependency-graphs"),
    "release-action-smoke.yml": (
        "upload-sentinel", "verify-sentinel", "publisher-startup",
    ),
    "ci.yml": tuple(REQUIRED_WORKFLOWS),
}
SUBMISSION_EVENT = (
    "github.event_name == 'push' && github.ref == 'refs/heads/main' && "
    "github.event.deleted == false && github.sha == github.event.after"
)
CANCEL_POLICY = (
    "  cancel-in-progress: ${{ github.event_name != 'push' || "
    "github.ref != 'refs/heads/main' }}\n"
)


def _job_blocks(workflow: str) -> dict[str, str]:
    """Read this repository's block-style job inventory; actionlint validates YAML."""
    jobs = workflow.split("\njobs:\n", 1)[1]
    starts = list(re.finditer(r"(?m)^  ([a-z0-9_-]+):\n", jobs))
    boundaries = [match.start() for match in starts[1:]] + [len(jobs)]
    return {
        match.group(1): jobs[match.start():end].rstrip() + "\n"
        for match, end in zip(starts, boundaries, strict=True)
    }


def _terminal_name(filename: str) -> str:
    return "ci-success" if filename == "ci.yml" else "workflow-success"


def _run_gate(
    workflow: str,
    filename: str,
    results: dict[str, str],
    submission_required: str = "false",
) -> subprocess.CompletedProcess[str]:
    terminal = _job_blocks(workflow)[_terminal_name(filename)]
    script = textwrap.dedent(terminal.split("        run: |\n", 1)[1])
    python = script.removeprefix("python3 - <<'PY'\n").removesuffix("PY\n")
    environment = dict(os.environ)
    environment["REQUIRED_JOBS"] = json.dumps({
        job: {"result": result, "outputs": {}} for job, result in results.items()
    })
    environment["SUBMISSION_REQUIRED"] = submission_required
    return subprocess.run(
        [sys.executable, "-c", python], env=environment, check=False,
        capture_output=True, text=True, timeout=10,
    )


class CIAggregateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflows = {
            filename: (WORKFLOW_DIR / filename).read_text(encoding="utf-8")
            for filename in REQUIRED_JOBS
        }

    def _assert_graph(self, workflows: dict[str, str]) -> None:
        caller = _job_blocks(workflows["ci.yml"])
        self.assertEqual(set(caller), {*REQUIRED_WORKFLOWS, "ci-success"})
        for call, filename in REQUIRED_WORKFLOWS.items():
            expected = f"  {call}:\n    uses: ./.github/workflows/{filename}\n"
            if call == "dependencies":
                expected += "    permissions:\n      actions: read\n      contents: write\n"
            self.assertEqual(caller[call], expected)
        for filename, required in REQUIRED_JOBS.items():
            jobs = _job_blocks(workflows[filename])
            terminal_name = _terminal_name(filename)
            self.assertEqual(set(jobs), {*required, terminal_name})
            terminal = jobs[terminal_name]
            self.assertIn(f"    name: {terminal_name}\n", terminal)
            self.assertIn("    if: always()\n", terminal)
            self.assertIn(f"    needs: [{', '.join(required)}]\n", terminal)
            self.assertIn("    permissions: {}\n", terminal)
            self.assertIn("      REQUIRED_JOBS: ${{ toJSON(needs) }}\n", terminal)
            self.assertIn("    runs-on: ubuntu-24.04\n", terminal)
            self.assertNotIn("uses:", terminal)
            write_count = 1 if filename in {"ci.yml", "dependency-locks.yml"} else 0
            self.assertEqual(workflows[filename].count(": write"), write_count)

    def test_exact_same_commit_calls_and_terminal_dependencies(self) -> None:
        self._assert_graph(self.workflows)

    def test_full_suite_installs_and_verifies_pinned_policy_tool(self) -> None:
        job = _job_blocks(self.workflows["tests.yml"])["test"]
        setup = job.split("      - name: Run unit tests\n", 1)[0]
        requirements = (WORKFLOW_DIR.parents[1] / "requirements-tooling.txt").read_text(
            encoding="utf-8",
        )
        ruff_pin = next(line for line in requirements.splitlines() if line.startswith("ruff=="))
        install = setup.split("python scripts/verify_dependency_environment.py", 1)[0]
        self.assertIn(ruff_pin, install)
        verification = setup.split("python scripts/verify_dependency_environment.py", 1)[1]
        self.assertIn("--require ruff \\\n", verification)

    def test_triggers_cover_main_and_campaign_without_duplicate_children(self) -> None:
        caller = self.workflows["ci.yml"].split("\npermissions:", 1)[0]
        self.assertEqual(caller, (
            "name: CI\n\non:\n"
            "  pull_request:\n    branches: [main, dev/080-architecture-campaign]\n"
            "  push:\n    branches: [main, dev/080-architecture-campaign]\n"
            "  workflow_call:\n"
        ))
        for filename in REQUIRED_WORKFLOWS.values():
            header = self.workflows[filename].split("\njobs:\n", 1)[0]
            with self.subTest(filename=filename):
                self.assertIn("on:\n  workflow_call:\n", header)
                self.assertNotIn("  pull_request:", header)
                self.assertNotIn("  push:", header)
                if filename != "dependency-locks.yml":
                    self.assertNotIn("  workflow_dispatch:", header)

    def test_concurrency_does_not_cancel_parent_or_live_main_push(self) -> None:
        for filename, prefix in (
            ("ci.yml", "gm2godot-ci-caller"),
            ("dependency-locks.yml", "gm2godot-ci-dependencies"),
        ):
            self.assertIn(
                f"  group: {prefix}-${{{{ github.workflow }}}}-${{{{ github.ref }}}}\n",
                self.workflows[filename],
            )
            self.assertIn(CANCEL_POLICY, self.workflows[filename])

    def test_submission_retains_complete_event_guard_and_permission_boundary(self) -> None:
        workflow = self.workflows["dependency-locks.yml"]
        self.assertIn("\npermissions:\n  contents: read\n", workflow)
        jobs = _job_blocks(workflow)
        submission = jobs["submit-dependency-graphs"]
        self.assertIn(
            "    if: >-\n"
            "      ${{ !cancelled() &&\n"
            "          needs.generate.result == 'success' &&\n"
            "          github.event_name == 'push' &&\n"
            "          github.ref == 'refs/heads/main' &&\n"
            "          github.event.deleted == false &&\n"
            "          github.sha == github.event.after }}\n",
            submission,
        )
        self.assertIn("    permissions:\n      actions: read\n      contents: write\n", submission)
        self.assertNotIn("permissions:", jobs["generate"])
        self.assertIn(
            f"      SUBMISSION_REQUIRED: ${{{{ {SUBMISSION_EVENT} }}}}\n",
            jobs["workflow-success"],
        )

    def test_contract_rejects_missing_calls_dependencies_and_unsafe_permissions(self) -> None:
        mutations = (
            ("ci.yml", "  pyright:\n    uses: ./.github/workflows/pyright.yml\n", ""),
            ("ci.yml", "pyright.yml\n", "pyright.yml@main\n"),
            ("tests.yml", "test, macos-managed-output-transactions, ", "test, "),
            ("ci.yml", "      contents: write\n", "      contents: read\n"),
            ("pyright.yml", "    permissions: {}\n", "    permissions:\n      contents: write\n"),
            ("ci.yml", "    if: always()\n", "    if: success()\n"),
        )
        for filename, before, after in mutations:
            with self.subTest(filename=filename, mutation=before):
                modified = dict(self.workflows)
                self.assertIn(before, modified[filename])
                modified[filename] = modified[filename].replace(before, after, 1)
                with self.assertRaises(AssertionError):
                    self._assert_graph(modified)

    def test_required_results_fail_closed_for_each_actual_terminal_script(self) -> None:
        for filename, required in REQUIRED_JOBS.items():
            successes = dict.fromkeys(required, "success")
            workflow = self.workflows[filename]
            self.assertEqual(_run_gate(workflow, filename, successes, "true").returncode, 0)
            self._assert_required_failures(filename, successes)

    def _assert_required_failures(self, filename: str, successes: dict[str, str]) -> None:
        for job in successes:
            for result in ("failure", "cancelled", "skipped", "missing"):
                with self.subTest(filename=filename, job=job, result=result):
                    modified = dict(successes)
                    if result == "missing":
                        del modified[job]
                    else:
                        modified[job] = result
                    self.assertNotEqual(
                        _run_gate(self.workflows[filename], filename, modified, "true").returncode, 0,
                    )

    def test_submission_skip_is_allowed_only_when_event_guard_is_inapplicable(self) -> None:
        filename = "dependency-locks.yml"
        workflow = self.workflows[filename]
        results = {"generate": "success", "submit-dependency-graphs": "skipped"}
        self.assertEqual(_run_gate(workflow, filename, results).returncode, 0)
        for condition in ("true", "", "invalid"):
            self.assertNotEqual(_run_gate(workflow, filename, results, condition).returncode, 0)
        for job in results:
            for result in ("failure", "cancelled", "missing"):
                with self.subTest(job=job, result=result):
                    modified = dict(results)
                    if result == "missing":
                        del modified[job]
                    else:
                        modified[job] = result
                    self.assertNotEqual(_run_gate(workflow, filename, modified).returncode, 0)
        results["generate"] = "skipped"
        self.assertNotEqual(_run_gate(workflow, filename, results).returncode, 0)


if __name__ == "__main__":
    unittest.main()
