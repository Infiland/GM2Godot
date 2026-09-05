"""Finite inventories and fail-closed policy for the three native receipt gates."""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts import capture_conversion_parity as parity
from scripts import run_required_unittest as runner
from scripts._anchored_output import AnchoredOutputError
from tests import test_native_receipts_posix as posix
from tests.test_native_receipt_producers import producer_profile
from tests.windows_receipt_native_support import (
    WINDOWS_AMD64_ABI,
    native_abi_layout,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "architecture-verification.json"
POSIX = (
    "test_absent_and_identical_preserve_private_inode",
    "test_different_and_linked_targets_fail_without_mutation",
    "test_symlink_parent_and_target_never_redirect_publication",
    "test_real_file_and_directory_fsync_are_executed",
    "test_parent_relocation_is_detected_and_retained_descriptor_closes",
    "test_post_write_failure_cleans_stage_and_closes_descriptor",
)
DARWIN = (
    "test_tmp_alias_preserves_physical_inode",
    "test_var_alias_preserves_physical_inode",
    "test_redirect_below_trusted_alias_is_rejected",
)
WINDOWS = (
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
)
PRODUCERS = (
    "test_bootstrap_cli_fresh_identical_conflict",
    "test_environment_cli_fresh_identical_conflict",
    "test_required_writer_and_cli_fresh_identical_conflict",
    "test_parity_writer_and_cli_fresh_identical_conflict",
)


def method_ids(module: str, owner: str, methods: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"tests.{module}.{owner}.{method}" for method in methods)


POSIX_IDS = method_ids("test_native_receipts_posix", "TestNativeReceiptsPosix", POSIX)
DARWIN_IDS = method_ids("test_native_receipts_darwin", "TestNativeReceiptsDarwin", DARWIN)
WINDOWS_IDS = method_ids("test_native_receipts_windows", "TestNativeReceiptsWindows", WINDOWS)
PRODUCER_IDS = method_ids("test_native_receipt_producers", "TestNativeReceiptProducers", PRODUCERS)
INVENTORIES = {
    "N01-linux": POSIX_IDS + PRODUCER_IDS,
    "N01-macos": POSIX_IDS + DARWIN_IDS + PRODUCER_IDS,
    "N01-windows": WINDOWS_IDS + PRODUCER_IDS,
}
RUNTIMES = {
    "N01-linux": ("3.12.13", "linux", "x86_64"),
    "N01-macos": ("3.12.10", "darwin", "arm64"),
    "N01-windows": ("3.12.10", "win32", "AMD64"),
}


def named_block(source: str, prefix: str, name: str) -> str:
    """Select one block from the repository's actionlint-checked workflow style."""
    starts = list(re.finditer(rf"(?m)^{re.escape(prefix)}(\S[^\n]*)\n", source))
    ends = [match.start() for match in starts[1:]] + [len(source)]
    blocks = {match.group(1): source[match.start():end] for match, end in zip(starts, ends, strict=True)}
    return blocks[name]


class EmptyNativeFixture(unittest.TestCase):
    pass


class TestNativeReceiptGatePolicy(unittest.TestCase):
    def _assert_inventory(self, definition: runner.GateDefinition) -> None:
        self.assertEqual(definition.validation_kind, "native-receipts")
        self.assertEqual(definition.unittest_ids, INVENTORIES[definition.gate])
        self.assertEqual(definition.native_runtime, RUNTIMES[definition.gate])
        self.assertEqual(definition.allowed_skips, {})
        for source in definition.required_paths:
            self.assertTrue((ROOT / source).is_file(), source)
        _suite, discovered = runner.load_suite(definition.unittest_ids)
        self.assertEqual(discovered, definition.unittest_ids)

    def _load_modified(self, gate: str, **updates: object) -> runner.GateDefinition:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["gates"][gate].update(updates)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "manifest.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return runner.load_gate(path, gate)

    def test_exact_native_method_inventories_and_runtime(self) -> None:
        for gate in INVENTORIES:
            with self.subTest(gate=gate):
                self._assert_inventory(runner.load_gate(MANIFEST, gate))

    def test_inventory_rejects_omission_duplicate_deleted_method_and_empty_class(self) -> None:
        definition = runner.load_gate(MANIFEST, "N01-linux")
        with self.assertRaises(AssertionError):
            self._assert_inventory(replace(definition, unittest_ids=definition.unittest_ids[1:]))
        with self.assertRaises(runner.ManifestError):
            self._load_modified("N01-linux", unittest_ids=[*POSIX_IDS, POSIX_IDS[0]])
        original = posix.TestNativeReceiptsPosix.test_absent_and_identical_preserve_private_inode
        delattr(posix.TestNativeReceiptsPosix, POSIX[0])
        try:
            with self.assertRaises(AssertionError):
                self._assert_inventory(definition)
        finally:
            setattr(posix.TestNativeReceiptsPosix, POSIX[0], original)
        with self.assertRaises(runner.ManifestError):
            runner.load_suite(("tests.test_native_receipt_gate_policy.EmptyNativeFixture",))

    def test_native_runtime_and_skip_mutations_are_rejected(self) -> None:
        for update in (
            {"allowed_skips": {POSIX_IDS[0]: "missing capability"}},
            {"runtime": {"python_version": "3.12.10", "platform": "linux", "machine": "x86_64"}},
            {"runtime": None},
        ):
            with self.subTest(update=update), self.assertRaises(runner.ManifestError):
                self._load_modified("N01-linux", **update)

    def test_missing_unknown_and_cross_kind_cannot_bypass_parity(self) -> None:
        for gate, kind in (("R01", None), ("R01", "unknown"), ("R01", "native-receipts"),
                           ("N01-linux", "conversion-parity")):
            with self.subTest(gate=gate, kind=kind), self.assertRaises(runner.ManifestError):
                self._load_modified(gate, validation_kind=kind)
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        del document["gates"]["R01"]["parity"]
        with tempfile.TemporaryDirectory() as raw, contextlib.redirect_stderr(io.StringIO()):
            path = Path(raw) / "manifest.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with patch.object(runner, "verify_prerequisites"), patch.object(runner, "run_gate") as execute:
                status = runner.main(["--manifest", str(path), "--gate", "R01", "--receipt", str(path.with_suffix(".receipt"))])
            self.assertEqual(status, 2)
            execute.assert_not_called()

    def test_wrong_runtime_fails_before_collection(self) -> None:
        definition = runner.load_gate(MANIFEST, "N01-linux")
        with patch.object(runner.platform, "python_version", return_value="0.0.0"):
            with patch.object(runner, "load_suite") as collect, self.assertRaises(runner.ManifestError):
                runner.run_gate(definition, root=ROOT, stream=io.StringIO())
        collect.assert_not_called()

    def test_partial_or_zero_execution_and_native_skips_fail(self) -> None:
        definition = runner.load_gate(MANIFEST, "N01-linux")
        for count in (0, len(definition.unittest_ids) - 1):
            result = unittest.TestResult()
            result.testsRun = count
            with patch.object(runner, "verify_prerequisites"), patch.object(unittest.TextTestRunner, "run", return_value=result):
                status, _receipt = runner.run_gate(definition, root=ROOT, stream=io.StringIO())
            self.assertEqual(status, 1)
        result = unittest.TestResult()
        result.addSkip(unittest.FunctionTestCase(lambda: None), "native capability unavailable")
        self.assertFalse(runner.result_is_allowed(result, {}))

    def test_native_class_instead_of_individual_methods_fails_before_execution(self) -> None:
        definition = replace(runner.load_gate(MANIFEST, "N01-linux"), unittest_ids=("tests.test_native_receipts_posix.TestNativeReceiptsPosix",))
        with patch.object(runner, "verify_prerequisites"), patch.object(unittest.TextTestRunner, "run") as execute:
            with self.assertRaises(runner.ManifestError):
                runner.run_gate(definition, root=ROOT, stream=io.StringIO())
        execute.assert_not_called()

    def _assert_workflow_job(self, job: str, gate: str, profile: str, receipt: str, interpreter: str) -> None:
        self.assertRegex(job, r"(?m)^    timeout-minutes: (?:[1-9]|[1-3][0-9]|4[0-5])$")
        self.assertNotRegex(job, r"(?m)^    (?:if|continue-on-error):")
        native = named_block(job, "      - name: ", "Run required native receipt gate")
        self.assertIn("        timeout-minutes: 10\n", native)
        self.assertIn("        shell: bash\n", native)
        self.assertIn(f"          NATIVE_RECEIPT_PROFILE: {profile}\n", native)
        self.assertIn(f"{interpreter} -m scripts.run_required_unittest\n", native)
        self.assertIn(f"--manifest architecture-verification.json --gate {gate}\n", native)
        self.assertIn(f'--receipt "{receipt}"\n', native)
        self.assertNotRegex(native, r"(?m)^        (?:if|continue-on-error):")
        upload = named_block(job, "      - name: ", "Upload required native receipt")
        self.assertIn("        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", upload)
        self.assertIn("          if-no-files-found: error\n", upload)
        self.assertNotRegex(upload, r"(?m)^        (?:if|continue-on-error):")

    def _assert_workflows(self, tests: str, locks: str) -> None:
        for owner, host in (("test", "linux"), ("macos-managed-output-transactions", "macos"), ("windows-artifact-transactions", "windows")):
            job = named_block(tests, "  ", owner + ":")
            self._assert_workflow_job(job, f"N01-{host}", "stable", f"$RUNNER_TEMP/n01-tests-{host}.json", "python")
            self.assertIn(f"          path: ${{{{ runner.temp }}}}/n01-tests-{host}.json\n", job)
        job = named_block(locks, "  ", "generate:")
        self._assert_workflow_job(job, '"$NATIVE_RECEIPT_GATE"', "native-lock-workflow", "dependency-locks/native-receipts/receipt.json", '"$CURRENT_PYTHON"')
        self.assertIn("          NATIVE_RECEIPT_GATE: ${{ matrix.native_receipt_gate }}\n", job)
        self.assertIn("          path: dependency-locks/native-receipts/receipt.json\n", job)
        self.assertIn("      RECEIPT_DIR: dependency-locks/artifact/receipts\n", job)
        self.assertLess(job.index("Create and verify committed lock generator"), job.index("Run required native receipt gate"))
        for host, label in (("linux", "linux-x64"), ("macos", "macos-arm64"), ("windows", "windows-x64")):
            matrix = job.split("    env:\n", 1)[0]
            entry = named_block(matrix, "          - platform: ", label)
            self.assertIn(f"            native_receipt_gate: N01-{host}\n", entry)

    def test_workflows_require_all_native_gates_and_separate_receipts(self) -> None:
        tests = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        locks = (ROOT / ".github/workflows/dependency-locks.yml").read_text(encoding="utf-8")
        self._assert_workflows(tests, locks)

    def test_workflow_bypass_mutations_are_rejected(self) -> None:
        tests = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        locks = (ROOT / ".github/workflows/dependency-locks.yml").read_text(encoding="utf-8")
        marker = "      - name: Run required native receipt gate\n"
        mutations = (
            (marker, "      - name: Gate removed\n"),
            (marker, marker + "        if: false\n"),
            (marker, marker + "        continue-on-error: true\n"),
            ("        timeout-minutes: 10\n", ""),
            ("          if-no-files-found: error\n", "          if-no-files-found: warn\n"),
        )
        for old, new in mutations:
            for owner in ("tests", "locks"):
                with self.subTest(owner=owner, mutation=new), self.assertRaises((AssertionError, KeyError)):
                    self._assert_workflows(tests.replace(old, new, 1) if owner == "tests" else tests,
                                           locks.replace(old, new, 1) if owner == "locks" else locks)
        with self.assertRaises(AssertionError):
            self._assert_workflows(tests, locks.replace("native_receipt_gate: N01-linux", "native_receipt_gate: N01-macos"))
        with self.assertRaises(AssertionError):
            self._assert_workflows(tests.replace("    timeout-minutes: 30\n", "", 1), locks)
        with self.assertRaises(AssertionError):
            self._assert_workflows(tests, locks.replace("    timeout-minutes: 45\n", "", 1))

    def test_generator_profile_requires_pip_and_pip_tools_in_order(self) -> None:
        with patch.dict("os.environ", {"NATIVE_RECEIPT_PROFILE": "native-lock-workflow"}):
            self.assertEqual(producer_profile(), ("native-lock-workflow", ("pip", "pip-tools")))
        with patch.dict("os.environ", {"NATIVE_RECEIPT_PROFILE": "stable"}):
            self.assertEqual(producer_profile(), ("stable", ("pip",)))
        with patch.dict("os.environ", {"NATIVE_RECEIPT_PROFILE": "unknown"}), self.assertRaises(ValueError):
            producer_profile()

    def test_fixed_width_native_abi_preflight(self) -> None:
        self.assertEqual(native_abi_layout(), WINDOWS_AMD64_ABI)

    def _assert_cli_error_information(self, error: BaseException, *, propagated: bool) -> None:
        definition = runner.GateDefinition("R01", (), {}, (), {})
        with (
            patch.object(runner, "load_gate", return_value=definition),
            patch.object(runner, "load_parity_definition"),
            patch.object(runner, "validate_parity_inputs"),
            patch.object(runner, "run_gate", return_value=(0, {})),
            patch.object(parity, "load_parity_definition"),
            patch.object(parity, "capture_parity", return_value={}),
        ):
            for module, extra in ((runner, []), (parity, ["--base-ref", "a", "--head-ref", "b"])):
                with patch.object(module, "write_receipt", side_effect=error), contextlib.redirect_stderr(io.StringIO()) as output:
                    arguments = ["--manifest", "unused", "--gate", "R01", "--receipt", "unused", *extra]
                    self._assert_cli_result(module.main, arguments, error, propagated, output)

    def _assert_cli_result(self, main: Callable[[list[str]], int], arguments: list[str], error: BaseException,
                           propagated: bool, output: io.StringIO) -> None:
        if propagated:
            with self.assertRaises(type(error)):
                main(arguments)
            return
        self.assertEqual(main(arguments), 2)
        self.assertIn("output-different", output.getvalue())
        self.assertIn("cleanup evidence retained", output.getvalue())
        self.assertIn("original native cause", output.getvalue())

    def test_receipt_cli_preserves_error_chain_notes_and_process_control(self) -> None:
        error = AnchoredOutputError("output-different", "receipt conflict")
        error.add_note("cleanup evidence retained")
        error.__cause__ = OSError("original native cause")
        self._assert_cli_error_information(error, propagated=False)
        self._assert_cli_error_information(KeyboardInterrupt(), propagated=True)
        self._assert_cli_error_information(SystemExit(3), propagated=True)
