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

    def _assert_receipt_cli(self, main: Callable[[list[str]], int], arguments: list[str]) -> None:
        with tempfile.TemporaryDirectory() as raw, contextlib.redirect_stderr(io.StringIO()) as errors:
            output = Path(raw).resolve() / "receipt.json"
            arguments += ["--receipt", str(output)]
            self.assertEqual(main(arguments), 0)
            content, identity = output.read_bytes(), output.stat().st_ino
            self.assertEqual(main(arguments), 0)
            self.assertEqual((output.read_bytes(), output.stat().st_ino), (content, identity))
            output.write_bytes(b"other receipt\n")
            self.assertEqual(main(arguments), 2)
            self.assertIn("output-different", errors.getvalue())
            self.assertEqual(output.read_bytes(), b"other receipt\n")

    def test_required_writer_and_cli_fresh_identical_conflict(self) -> None:
        self._assert_writer(runner.write_receipt)
        definition = runner.GateDefinition("R01", (), {}, (), {})
        with (
            patch.object(runner, "load_gate", return_value=definition),
            patch.object(runner, "load_parity_definition"),
            patch.object(runner, "validate_parity_inputs"),
            patch.object(runner, "run_gate", return_value=(0, {"successful": True})),
        ):
            self._assert_receipt_cli(runner.main, ["--manifest", "unused", "--gate", "R01"])

    def test_parity_writer_and_cli_fresh_identical_conflict(self) -> None:
        self._assert_writer(parity.write_receipt)
        with (
            patch.object(parity, "load_parity_definition"),
            patch.object(parity, "capture_parity", return_value={"equal": True}),
        ):
            self._assert_receipt_cli(parity.main, [
                "--manifest", "unused", "--gate", "R01", "--base-ref", "before", "--head-ref", "after",
            ])
