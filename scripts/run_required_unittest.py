from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import traceback
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO, cast

from scripts._anchored_output import (
    AnchoredOutputError,
    publish_identical_receipt_bytes,
)
from scripts.conversion_parity_contract import ParityError, load_parity_definition
from scripts.conversion_parity_inputs import validate_parity_inputs

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NATIVE_RUNTIMES = {
    "N01-linux": ("3.12.13", "linux", "x86_64"),
    "N01-macos": ("3.12.10", "darwin", "arm64"),
    "N01-windows": ("3.12.10", "win32", "AMD64"),
}


class ManifestError(ValueError):
    """Raised when an architecture-verification manifest cannot be trusted."""


@dataclass(frozen=True)
class GateDefinition:
    gate: str
    unittest_ids: tuple[str, ...]
    required_environment: dict[str, str]
    required_paths: tuple[str, ...]
    allowed_skips: dict[str, str]
    validation_kind: Literal["conversion-parity", "native-receipts"] = "conversion-parity"
    native_runtime: tuple[str, str, str] | None = None


def load_gate(manifest_path: Path, gate: str) -> GateDefinition:
    """Load and validate one immutable gate definition."""
    try:
        document = _object_mapping(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            "verification manifest",
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"Cannot read verification manifest: {error}") from error
    if document.get("schema_version") != 1:
        raise ManifestError("Verification manifest must use schema_version 1")
    gates = _object_mapping(document.get("gates"), "gates")
    if gate not in gates:
        raise ManifestError(f"Verification manifest has no {gate!r} gate")
    definition = _object_mapping(gates[gate], f"verification gate {gate!r}")
    kind = _validation_kind(definition.get("validation_kind"), gate)
    return GateDefinition(
        gate=gate,
        unittest_ids=_string_tuple(definition.get("unittest_ids"), "unittest_ids"),
        required_environment=_string_mapping(
            definition.get("required_environment", {}),
            "required_environment",
        ),
        required_paths=_string_tuple(definition.get("required_paths"), "required_paths"),
        allowed_skips=_string_mapping(definition.get("allowed_skips", {}), "allowed_skips"),
        validation_kind=kind,
        native_runtime=_native_runtime(definition, gate) if kind == "native-receipts" else None,
    )


def _validation_kind(value: object, gate: str) -> Literal["conversion-parity", "native-receipts"]:
    if value == "conversion-parity" and gate not in NATIVE_RUNTIMES:
        return "conversion-parity"
    if value == "native-receipts" and gate in NATIVE_RUNTIMES:
        return "native-receipts"
    raise ManifestError(f"Invalid validation_kind {value!r} for {gate}")


def _native_runtime(definition: Mapping[str, object], gate: str) -> tuple[str, str, str]:
    runtime = _string_mapping(definition.get("runtime"), "native runtime")
    expected = dict(zip(("python_version", "platform", "machine"), NATIVE_RUNTIMES[gate], strict=True))
    if runtime != expected or definition.get("allowed_skips") != {}:
        raise ManifestError(f"{gate} requires its exact native runtime and zero allowed skips")
    return NATIVE_RUNTIMES[gate]


def verify_prerequisites(definition: GateDefinition, *, root: Path) -> None:
    """Fail before collection when declared files or environment inputs are absent."""
    if definition.validation_kind == "native-receipts":
        actual = (platform.python_version(), sys.platform, platform.machine())
        if definition.native_runtime != actual or definition.allowed_skips:
            raise ManifestError(f"{definition.gate} requires {definition.native_runtime}, got {actual}; no skips allowed")
    for relative_path in definition.required_paths:
        if not (root / relative_path).is_file():
            raise ManifestError(f"{definition.gate} requires file {relative_path!r}")
    for name, requirement in definition.required_environment.items():
        actual = os.environ.get(name)
        if not _environment_requirement_met(actual, requirement):
            raise ManifestError(
                f"{definition.gate} requires {name} to satisfy {requirement!r}; got {actual!r}"
            )


def _environment_requirement_met(value: str | None, requirement: str) -> bool:
    if not value:
        return False
    if requirement == "required-executable":
        return Path(value).is_file() and os.access(value, os.X_OK)
    if requirement == "required-git-checkout":
        return (Path(value) / ".git").exists()
    return value == requirement

def load_suite(
    test_ids: Sequence[str],
) -> tuple[unittest.TestSuite, tuple[str, ...]]:
    """Load all declared unittest names and return their exact discovered IDs."""
    suite = unittest.TestSuite()
    discovered: list[str] = []
    for test_id in test_ids:
        tests = tuple(_iter_tests(unittest.defaultTestLoader.loadTestsFromName(test_id)))
        if not tests:
            raise ManifestError(f"Unittest target {test_id!r} collected no tests")
        suite.addTests(tests)
        discovered.extend(test.id() for test in tests)
    duplicates = _duplicates(discovered)
    if duplicates:
        raise ManifestError(f"Unittest targets collect duplicate test IDs: {sorted(duplicates)}")
    return suite, tuple(discovered)


def run_gate(
    definition: GateDefinition,
    *,
    root: Path,
    stream: TextIO,
) -> tuple[int, dict[str, object]]:
    """Run one declared gate and produce a deterministic machine receipt."""
    verify_prerequisites(definition, root=root)
    suite, discovered = load_suite(definition.unittest_ids)
    if definition.validation_kind == "native-receipts" and discovered != definition.unittest_ids:
        raise ManifestError("Native gate must declare the exact discovered individual method IDs")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    receipt = _receipt(definition, discovered, result)
    complete = bool(discovered) and result.testsRun == len(discovered)
    return (0 if complete and result_is_allowed(result, definition.allowed_skips) else 1), receipt


def write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    """Publish a fresh or byte-identical canonical JSON gate receipt."""
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    # Preserve the previous text writer's native newline bytes, including CRLF.
    publish_identical_receipt_bytes(path, payload.replace("\n", os.linesep).encode("utf-8"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one exact architecture-verification unittest gate."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        definition = load_gate(args.manifest, args.gate)
        verify_prerequisites(definition, root=PROJECT_ROOT)
        if definition.validation_kind == "conversion-parity":
            parity_definition = load_parity_definition(args.manifest, args.gate)
            validate_parity_inputs(parity_definition, root=PROJECT_ROOT)
        status, receipt = run_gate(definition, root=PROJECT_ROOT, stream=sys.stdout)
    except (ManifestError, ParityError) as error:
        print(f"verification manifest error: {error}", file=sys.stderr)
        return 2
    try:
        write_receipt(args.receipt, receipt)
    except AnchoredOutputError as error:
        print(f"receipt publication error [{error.code}]: {error}", file=sys.stderr)
        traceback.print_exception(error, file=sys.stderr)
        return 2
    return status

def _object_mapping(value: object, key: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ManifestError(f"{key} must be an object")
    raw = cast(dict[object, object], value)
    mapping: dict[str, object] = {}
    for name, item in raw.items():
        if not isinstance(name, str):
            raise ManifestError(f"{key} keys must be strings")
        mapping[name] = item
    return mapping


def _object_list(value: object, key: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestError(f"{key} must be a list")
    return list(cast(list[object], value))


def _string_tuple(value: object, key: str) -> tuple[str, ...]:
    strings: list[str] = []
    for item in _object_list(value, key):
        if not isinstance(item, str):
            raise ManifestError(f"{key} must contain only strings")
        strings.append(item)
    if not strings:
        raise ManifestError(f"{key} must not be empty")
    if len(strings) != len(set(strings)):
        raise ManifestError(f"{key} must not contain duplicates")
    return tuple(strings)


def _string_mapping(value: object, key: str) -> dict[str, str]:
    strings: dict[str, str] = {}
    for name, item in _object_mapping(value, key).items():
        if not isinstance(item, str):
            raise ManifestError(f"{key} must be a string-to-string object")
        strings[name] = item
    return strings
def _iter_tests(suite: unittest.TestSuite) -> tuple[unittest.TestCase, ...]:
    tests: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            tests.extend(_iter_tests(item))
        else:
            tests.append(item)
    return tuple(tests)


def _duplicates(test_ids: Sequence[str]) -> frozenset[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for test_id in test_ids:
        if test_id in seen:
            duplicates.add(test_id)
        seen.add(test_id)
    return frozenset(duplicates)


def _receipt(
    definition: GateDefinition,
    discovered: tuple[str, ...],
    result: unittest.TestResult,
) -> dict[str, object]:
    return {
        "gate": definition.gate,
        "selected_test_ids": list(discovered),
        "tests_run": result.testsRun,
        "skips": _skip_reasons(result),
        "failures": _outcome_ids(result.failures),
        "errors": _outcome_ids(result.errors),
        "expected_failures": _outcome_ids(result.expectedFailures),
        "unexpected_successes": sorted(test.id() for test in result.unexpectedSuccesses),
        "successful": result.wasSuccessful(),
    }


def _skip_reasons(result: unittest.TestResult) -> dict[str, str]:
    return {test.id(): reason for test, reason in result.skipped}


def _outcome_ids(outcomes: Sequence[tuple[unittest.TestCase, str]]) -> list[str]:
    return sorted(test.id() for test, _ in outcomes)


def result_is_allowed(
    result: unittest.TestResult,
    allowed_skips: Mapping[str, str],
) -> bool:
    return (
        result.wasSuccessful()
        and not result.failures
        and not result.errors
        and not result.expectedFailures
        and not result.unexpectedSuccesses
        and _skip_reasons(result) == dict(allowed_skips)
    )


if __name__ == "__main__":
    raise SystemExit(main())
