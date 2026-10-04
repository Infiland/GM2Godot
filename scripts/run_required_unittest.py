from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TextIO, cast

from scripts._anchored_output import (
    AnchoredOutputError,
    publish_identical_receipt_bytes,
)
from scripts.conversion_parity_contract import ParityError, load_parity_definition
from scripts.conversion_parity_inputs import validate_parity_inputs

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DIAGNOSTIC_TEXT_LIMIT = 512
_DIAGNOSTIC_NOTE_LIMIT = 8
_DIAGNOSTIC_TRUNCATION = "... [truncated]"


class ManifestError(ValueError):
    """Raised when an architecture-verification manifest cannot be trusted."""


@dataclass(frozen=True)
class NativeRuntimeRequirement:
    python_version: str
    platform_name: str
    machine: str


POSIX_NATIVE_TEST_IDS = tuple(
    "tests.test_native_receipts_posix.TestNativeReceiptsPosix." + method
    for method in (
        "test_absent_and_identical_preserve_private_inode",
        "test_different_and_linked_targets_fail_without_mutation",
        "test_symlink_parent_and_target_never_redirect_publication",
        "test_real_file_and_directory_fsync_are_executed",
        "test_parent_relocation_is_detected_and_retained_descriptor_closes",
        "test_post_write_failure_cleans_stage_and_closes_descriptor",
    )
)
DARWIN_NATIVE_TEST_IDS = tuple(
    "tests.test_native_receipts_darwin.TestNativeReceiptsDarwin." + method
    for method in (
        "test_tmp_alias_preserves_physical_inode", "test_var_alias_preserves_physical_inode",
        "test_redirect_below_trusted_alias_is_rejected",
    )
)
WINDOWS_NATIVE_TEST_IDS = tuple(
    "tests.test_native_receipts_windows.TestNativeReceiptsWindows." + method
    for method in (
        "test_native_abi_publication_and_identical_identity",
        "test_different_content_and_hardlinks_are_rejected",
        "test_junction_directory_and_reserved_targets_fail_closed",
        "test_retained_ancestors_deny_relocation_then_close",
        "test_existing_target_is_pinned_during_identical_comparison",
        "test_stage_substitution_is_denied",
        "test_concurrent_target_winner_is_not_overwritten",
        "test_long_unicode_path_publishes_and_reuses",
        "test_post_write_failure_cleans_stage_and_handles",
        "test_post_rename_failure_retains_published_identity",
        "test_repeated_publication_does_not_leak_handles",
        "test_observers_preserve_ctypes_last_error_and_native_close",
        "test_unopened_parent_junction_substitution_is_rejected",
    )
)
PRODUCER_NATIVE_TEST_IDS = tuple(
    "tests.test_native_receipt_producers.TestNativeReceiptProducers." + method
    for method in (
        "test_bootstrap_cli_fresh_identical_conflict", "test_environment_cli_fresh_identical_conflict",
        "test_required_writer_and_cli_fresh_identical_conflict", "test_parity_writer_and_cli_fresh_identical_conflict",
    )
)
NATIVE_GATE_TEST_IDS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "N01-linux": POSIX_NATIVE_TEST_IDS + PRODUCER_NATIVE_TEST_IDS,
    "N01-macos": POSIX_NATIVE_TEST_IDS + DARWIN_NATIVE_TEST_IDS + PRODUCER_NATIVE_TEST_IDS,
    "N01-macos-x64": POSIX_NATIVE_TEST_IDS + DARWIN_NATIVE_TEST_IDS + PRODUCER_NATIVE_TEST_IDS,
    "N01-windows": WINDOWS_NATIVE_TEST_IDS + PRODUCER_NATIVE_TEST_IDS,
})
NATIVE_GATE_RUNTIMES: Mapping[str, NativeRuntimeRequirement] = MappingProxyType({
    "N01-linux": NativeRuntimeRequirement("3.12.13", "linux", "x86_64"),
    "N01-macos": NativeRuntimeRequirement("3.12.10", "darwin", "arm64"),
    "N01-macos-x64": NativeRuntimeRequirement("3.12.10", "darwin", "x86_64"),
    "N01-windows": NativeRuntimeRequirement("3.12.10", "win32", "AMD64"),
})


@dataclass(frozen=True)
class GateDefinition:
    gate: str
    unittest_ids: tuple[str, ...]
    required_environment: dict[str, str]
    required_paths: tuple[str, ...]
    allowed_skips: dict[str, str]
    validation_kind: Literal["conversion-parity", "native-receipts"] = "conversion-parity"
    native_runtime: NativeRuntimeRequirement | None = None


class _CoverageResult(unittest.TextTestResult):
    """Record actual test starts and completions independently of collection."""

    def startTest(self, test: unittest.TestCase) -> None:
        if not hasattr(self, "started_test_ids"):
            self.started_test_ids: list[str] = []
            self.completed_test_ids: list[str] = []
        self.started_test_ids.append(test.id())
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        self.completed_test_ids.append(test.id())
        super().stopTest(test)


class _CoverageRunner(unittest.TextTestRunner):
    def _makeResult(self) -> _CoverageResult:
        return _CoverageResult(self.stream, self.descriptions, self.verbosity)


def load_gate(manifest_path: Path, gate: str) -> GateDefinition:
    """Load and validate one immutable gate definition."""
    try:
        document = _object_mapping(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            "verification manifest",
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"Cannot read verification manifest: {error}") from error
    if type(document.get("schema_version")) is not int or document.get("schema_version") != 1:
        raise ManifestError("Verification manifest must use schema_version 1")
    gates = _object_mapping(document.get("gates"), "gates")
    if gate not in gates:
        raise ManifestError(f"Verification manifest has no {gate!r} gate")
    definition = _object_mapping(gates[gate], f"verification gate {gate!r}")
    kind = definition.get("validation_kind")
    if kind == "conversion-parity":
        validation_kind = "conversion-parity"
    elif kind == "native-receipts":
        validation_kind = "native-receipts"
    else:
        raise ManifestError("validation_kind must explicitly name conversion-parity or native-receipts")
    native_runtime: NativeRuntimeRequirement | None = None
    if validation_kind == "native-receipts":
        runtime = _string_mapping(definition.get("runtime"), "runtime")
        if set(runtime) != {"python_version", "platform", "machine"}:
            raise ManifestError("Native runtime requires exactly python_version, platform, and machine")
        native_runtime = NativeRuntimeRequirement(runtime["python_version"], runtime["platform"], runtime["machine"])
    gate_definition = GateDefinition(
        gate=gate,
        unittest_ids=_string_tuple(definition.get("unittest_ids"), "unittest_ids"),
        required_environment=_string_mapping(
            definition.get("required_environment", {}),
            "required_environment",
        ),
        required_paths=_string_tuple(definition.get("required_paths"), "required_paths"),
        allowed_skips=_string_mapping(definition.get("allowed_skips", {}), "allowed_skips"),
        validation_kind=validation_kind,
        native_runtime=native_runtime,
    )
    validate_gate_definition(gate_definition)
    return gate_definition


def validate_gate_definition(definition: GateDefinition) -> None:
    """Bind declared native inventories and runtimes before collecting any test."""
    if definition.gate == "R01":
        if definition.validation_kind != "conversion-parity" or definition.native_runtime is not None:
            raise ManifestError("R01 must retain conversion-parity validation")
        return
    if definition.gate not in NATIVE_GATE_TEST_IDS or definition.validation_kind != "native-receipts":
        raise ManifestError("Only the four N01 gates may use native-receipts validation")
    if definition.unittest_ids != NATIVE_GATE_TEST_IDS[definition.gate]:
        raise ManifestError(f"{definition.gate} must select its exact ordered native method IDs")
    if definition.native_runtime != NATIVE_GATE_RUNTIMES[definition.gate]:
        raise ManifestError(f"{definition.gate} must retain its exact native runtime tuple")
    if definition.allowed_skips or definition.required_environment:
        raise ManifestError("Native receipt gates require zero allowed skips and no conversion environment prerequisites")


def verify_prerequisites(definition: GateDefinition, *, root: Path) -> None:
    """Fail before collection when declared files or environment inputs are absent."""
    validate_gate_definition(definition)
    if definition.native_runtime is not None:
        actual = NativeRuntimeRequirement(platform.python_version(), sys.platform, platform.machine())
        if actual != definition.native_runtime:
            raise ManifestError(f"{definition.gate} requires native runtime {definition.native_runtime!r}; got {actual!r}")
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
        raise ManifestError("Native receipt discovery did not collect the exact ordered method inventory")
    result = _CoverageRunner(stream=stream, verbosity=2).run(suite)
    receipt = _receipt(definition, discovered, result)
    return (0 if receipt["successful"] else 1), receipt


def write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    """Publish native text-writer bytes without replacing a different receipt."""
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
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
    except (SystemExit, KeyboardInterrupt) as error:
        print(f"verification interrupted before completion: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    try:
        write_receipt(args.receipt, receipt)
    except AnchoredOutputError as error:
        report_receipt_publication_error(error, stream=sys.stderr)
        return 2
    except (SystemExit, KeyboardInterrupt) as error:
        _report_receipt_diagnostic(error, label=f"receipt publication interrupted: {type(error).__name__}", stream=sys.stderr)
        print("An immutable candidate or prior identical receipt may remain; no retry or overwrite was attempted.", file=sys.stderr)
        return 2
    return status


def report_receipt_publication_error(error: AnchoredOutputError, *, stream: TextIO) -> None:
    """Expose stable code, causal failure, and cleanup notes without retrying."""
    _report_receipt_diagnostic(error, label=f"receipt publication failed [{error.code}]", stream=stream)
    print("Use a fresh receipt path, or retain a byte-identical private single-link receipt; no existing output was replaced.", file=stream)
    print("An immutable candidate or prior identical receipt may remain; no retry or overwrite was attempted.", file=stream)


def _report_receipt_diagnostic(error: BaseException, *, label: str, stream: TextIO) -> None:
    """Bound CLI rendering while leaving the primary exception and notes intact."""
    print(_bounded_diagnostic(f"{label}: {error}"), file=stream)
    if error.__cause__ is not None:
        print(_bounded_diagnostic(f"cause: {type(error.__cause__).__name__}: {error.__cause__}"), file=stream)
    for index, note in enumerate(getattr(error, "__notes__", ())):
        if index == _DIAGNOSTIC_NOTE_LIMIT:
            print("note: additional diagnostic notes omitted [truncated]", file=stream)
            break
        print(_bounded_diagnostic(f"note: {note}"), file=stream)


def _bounded_diagnostic(message: str) -> str:
    if len(message) <= _DIAGNOSTIC_TEXT_LIMIT:
        return message
    return message[:_DIAGNOSTIC_TEXT_LIMIT - len(_DIAGNOSTIC_TRUNCATION)] + _DIAGNOSTIC_TRUNCATION


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
        "started_test_ids": list(getattr(result, "started_test_ids", ())),
        "completed_test_ids": list(getattr(result, "completed_test_ids", ())),
        "tests_run": result.testsRun,
        "skips": _skip_reasons(result),
        "failures": _outcome_ids(result.failures),
        "errors": _outcome_ids(result.errors),
        "expected_failures": _outcome_ids(result.expectedFailures),
        "unexpected_successes": sorted(test.id() for test in result.unexpectedSuccesses),
        "successful": result_is_allowed(result, definition.allowed_skips, discovered),
    }


def _skip_reasons(result: unittest.TestResult) -> dict[str, str]:
    return {test.id(): reason for test, reason in result.skipped}


def _outcome_ids(outcomes: Sequence[tuple[unittest.TestCase, str]]) -> list[str]:
    return sorted(test.id() for test, _ in outcomes)


def result_is_allowed(
    result: unittest.TestResult,
    allowed_skips: Mapping[str, str],
    discovered: Sequence[str] | None = None,
) -> bool:
    return (
        type(result.testsRun) is int and result.testsRun > 0
        and (
            discovered is None
            or (
                result.testsRun == len(discovered)
                and tuple(getattr(result, "started_test_ids", ())) == tuple(discovered)
                and tuple(getattr(result, "completed_test_ids", ())) == tuple(discovered)
            )
        )
        and result.wasSuccessful()
        and not result.failures
        and not result.errors
        and not result.expectedFailures
        and not result.unexpectedSuccesses
        and _skip_reasons(result) == dict(allowed_skips)
    )


if __name__ == "__main__":
    raise SystemExit(main())
