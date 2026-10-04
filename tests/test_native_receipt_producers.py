"""Real fresh/identical receipt publication by the normal CLI producers."""

from __future__ import annotations

import contextlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts import capture_conversion_parity as parity, run_required_unittest as runner
from scripts._anchored_output import AnchoredOutputError

ROOT = Path(__file__).resolve().parents[1]
Writer = Callable[[Path, Mapping[str, object]], None]


def native_constraint() -> Path:
    suffix = {"linux": "linux", "darwin": "macos", "win32": "windows"}[sys.platform]
    return ROOT / "constraints" / f"requirements-{suffix}-py312.lock"


def producer_profile() -> tuple[str, tuple[str, ...]]:
    profile = os.environ.get("NATIVE_RECEIPT_PROFILE", "stable")
    if profile == "stable":
        return profile, ("pip",)
    if profile == "native-lock-workflow":
        return profile, ("pip", "pip-tools")
    raise ValueError(f"Unknown native receipt producer profile: {profile}")


class TestNativeReceiptProducers(unittest.TestCase):
    def _assert_cli_publication(self, arguments: list[str]) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw).resolve() / "receipt.json"
            command = [sys.executable, *arguments, "--output", str(output)]
            first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(first.returncode, 0, first.stderr)
            content, identity = output.read_bytes(), output.stat().st_ino
            second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((output.read_bytes(), output.stat().st_ino), (content, identity))
            output.write_bytes(b"conflicting receipt\n")
            conflict = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("output-different", conflict.stderr)
            self.assertEqual(output.read_bytes(), b"conflicting receipt\n")

    def test_bootstrap_cli_fresh_identical_conflict(self) -> None:
        profile, _requirements = producer_profile()
        arguments = [
            "-m", "scripts.verify_dependency_bootstrap",
            "--source", str(ROOT / "requirements-bootstrap.txt"),
            "--policy", profile,
        ]
        if profile == "stable":
            arguments.extend(("--constraint", str(native_constraint())))
        self._assert_cli_publication(arguments)

    def test_environment_cli_fresh_identical_conflict(self) -> None:
        runtime = (platform.python_version(), sys.platform, platform.machine())
        if runtime not in {
            ("3.12.13", "linux", "x86_64"),
            ("3.12.10", "darwin", "arm64"),
            ("3.12.10", "darwin", "x86_64"),
            ("3.12.10", "win32", "AMD64"),
        }:
            self.skipTest(f"Environment receipt requires a reviewed native baseline; executing {runtime}")
        profile, requirements = producer_profile()
        arguments = [
            "-m", "scripts.verify_dependency_environment", "--mode", "subset",
            "--constraint", str(native_constraint()), "--expected-python", platform.python_version(),
            "--expected-platform", sys.platform, "--expected-machine", platform.machine(),
            "--bootstrap", str(ROOT / "requirements-bootstrap.txt"), "--bootstrap-policy", profile,
        ]
        for requirement in requirements:
            arguments.extend(("--require", requirement))
        self._assert_cli_publication(arguments)

    def _assert_writer(self, writer: Writer) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw).resolve() / "nested" / "receipt.json"
            receipt = {"equal": True, "value": "unchanged"}
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=raw, delete=False) as legacy:
                legacy.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
                legacy_path = Path(legacy.name)
            content = legacy_path.read_bytes()
            writer(output, receipt)
            self.assertEqual(output.read_bytes(), content)
            output.unlink()
            legacy_path.replace(output)
            identity = output.stat().st_ino
            writer(output, receipt)
            self.assertEqual((output.read_bytes(), output.stat().st_ino), (content, identity))
            with self.assertRaises(AnchoredOutputError) as raised:
                writer(output, {"equal": False, "value": "different"})
            self.assertEqual(raised.exception.code, "output-different")
            self.assertEqual((output.read_bytes(), output.stat().st_ino), (content, identity))

    def _assert_module_entrypoint(self, module: str) -> None:
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, "-m", module, "--help"], cwd=ROOT, env=environment,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertIn("--receipt", completed.stdout)

    def _assert_receipt_cli(
        self,
        main: Callable[[list[str]], int],
        arguments: list[str],
        *,
        expected_ids: tuple[str, ...] | None = None,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as raw,
            contextlib.redirect_stderr(io.StringIO()) as errors,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            output = Path(raw).resolve() / "receipt.json"
            arguments += ["--receipt", str(output)]
            self.assertEqual(main(arguments), 0)
            content, identity = output.read_bytes(), output.stat().st_ino
            if expected_ids is not None:
                receipt = cast(dict[str, object], json.loads(content))
                for key in ("selected_test_ids", "started_test_ids", "completed_test_ids"):
                    self.assertEqual(receipt[key], list(expected_ids))
                self.assertIs(type(receipt["tests_run"]), int)
                self.assertEqual(receipt["tests_run"], len(expected_ids))
                self.assertIs(receipt["successful"], True)
                self.assertEqual(receipt["skips"], {})
                for key in ("failures", "errors", "expected_failures", "unexpected_successes"):
                    self.assertEqual(receipt[key], [])
            self.assertEqual(main(arguments), 0)
            self.assertEqual((output.read_bytes(), output.stat().st_ino), (content, identity))
            output.write_bytes(b"other receipt\n")
            self.assertEqual(main(arguments), 2)
            self.assertIn("output-different", errors.getvalue())
            self.assertEqual(output.read_bytes(), b"other receipt\n")

    def test_required_writer_and_cli_fresh_identical_conflict(self) -> None:
        self._assert_module_entrypoint("scripts.run_required_unittest")
        self._assert_writer(runner.write_receipt)
        # Isolate only the conversion prerequisites for this publication test.
        # The real nonempty loader/coverage runner still records actual execution.
        selected = ("tests.test_required_unittest_runner._RunnerFixture.test_success",)
        definition = runner.GateDefinition("R01", selected, {}, ("scripts/run_required_unittest.py",), {})
        with (
            patch.object(runner, "load_gate", return_value=definition),
            patch.object(runner, "load_parity_definition"),
            patch.object(runner, "validate_parity_inputs"),
        ):
            self._assert_receipt_cli(
                runner.main, ["--manifest", "unused", "--gate", "R01"], expected_ids=selected,
            )

    def test_parity_writer_and_cli_fresh_identical_conflict(self) -> None:
        self._assert_module_entrypoint("scripts.capture_conversion_parity")
        self._assert_writer(parity.write_receipt)
        # This synthetic capture seam proves CLI receipt publication only;
        # native conversion parity remains the separate immutable R01 gate.
        with (
            patch.object(parity, "load_parity_definition"),
            patch.object(parity, "capture_parity", return_value={"equal": True}),
        ):
            self._assert_receipt_cli(parity.main, [
                "--manifest", "unused", "--gate", "R01", "--base-ref", "before", "--head-ref", "after",
            ])
