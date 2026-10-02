"""Independent inventories and bypass regressions for required native receipts."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts import run_required_unittest as runner
from tests import test_native_receipts_posix as posix
from tests.test_native_receipt_producers import producer_profile
from tests.windows_receipt_native_support import WINDOWS_AMD64_ABI, native_abi_layout

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
    "test_unopened_parent_junction_substitution_is_rejected",
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
SHARED_PATHS = (
    "scripts/_anchored_output.py",
    "scripts/run_required_unittest.py",
    "scripts/capture_conversion_parity.py",
    "scripts/verify_dependency_bootstrap.py",
    "scripts/verify_dependency_environment.py",
    "requirements-bootstrap.txt",
    "tests/test_native_receipt_producers.py",
    "tests/test_native_receipt_gate_policy.py",
)
REQUIRED_PATHS = {
    "N01-linux": SHARED_PATHS + (
        "scripts/_anchored_receipt_posix.py", "tests/test_native_receipts_posix.py",
        "constraints/requirements-linux-py312.lock",
    ),
    "N01-macos": SHARED_PATHS + (
        "scripts/_anchored_receipt_posix.py", "tests/test_native_receipts_posix.py",
        "tests/test_native_receipts_darwin.py", "constraints/requirements-macos-py312.lock",
    ),
    "N01-windows": SHARED_PATHS + (
        "scripts/_anchored_receipt_windows.py", "tests/test_native_receipts_windows.py",
        "tests/windows_receipt_native_support.py", "constraints/requirements-windows-py312.lock",
    ),
}
R01_PRESERVED_SHA256 = "caf3fc0123ea3fdfc70385394674539fb9b3a7f7737aa598f78720d0989866a1"
UPLOAD_ACTION = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"
TEST_JOBS = (
    ("test", "linux", "ubuntu-24.04", "x64", 30),
    ("macos-managed-output-transactions", "macos", "macos-26", "arm64", 30),
    ("windows-artifact-transactions", "windows", "windows-2025", "x64", 20),
)
LOCK_ENTRIES = {
    "linux-x64": {
        "runner": "ubuntu-24.04", "architecture": "x64", "python_version": "'3.12.13'",
        "constraint": "requirements-linux-py312.lock", "expected_platform": "linux",
        "expected_machine": "x86_64", "venv_python": "bin/python", "pip_config_file": "/dev/null",
        "native_receipt_gate": "N01-linux",
    },
    "macos-arm64": {
        "runner": "macos-26", "architecture": "arm64", "python_version": "'3.12.10'",
        "constraint": "requirements-macos-py312.lock", "expected_platform": "darwin",
        "expected_machine": "arm64", "venv_python": "bin/python", "pip_config_file": "/dev/null",
        "native_receipt_gate": "N01-macos",
    },
    "windows-x64": {
        "runner": "windows-2025", "architecture": "x64", "python_version": "'3.12.10'",
        "constraint": "requirements-windows-py312.lock", "expected_platform": "win32",
        "expected_machine": "AMD64", "venv_python": "Scripts/python.exe", "pip_config_file": "nul",
        "native_receipt_gate": "N01-windows",
    },
}


def named_block(source: str, prefix: str, name: str) -> str:
    """Require one block in the repository's actionlint-checked workflow style."""
    starts = list(re.finditer(rf"(?m)^{re.escape(prefix)}(\S[^\n]*)\n", source))
    matching = [index for index, match in enumerate(starts) if match.group(1) == name]
    if len(matching) != 1:
        raise AssertionError(f"Expected exactly one {name!r} block; got {len(matching)}")
    index = matching[0]
    end = starts[index + 1].start() if index + 1 < len(starts) else len(source)
    return source[starts[index].start():end]


def mutate_block(source: str, prefix: str, name: str, mutation: Callable[[str], str]) -> str:
    block = named_block(source, prefix, name)
    return source.replace(block, mutation(block), 1)


class EmptyNativeFixture(unittest.TestCase):
    pass


class TestNativeReceiptGatePolicy(unittest.TestCase):
    def _assert_inventory(self, definition: runner.GateDefinition) -> None:
        self.assertEqual(definition.validation_kind, "native-receipts")
        self.assertEqual(definition.unittest_ids, INVENTORIES[definition.gate])
        runtime = definition.native_runtime
        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual((runtime.python_version, runtime.platform_name, runtime.machine), RUNTIMES[definition.gate])
        self.assertEqual(definition.required_paths, REQUIRED_PATHS[definition.gate])
        self.assertEqual(definition.required_environment, {})
        self.assertEqual(definition.allowed_skips, {})
        for source in definition.required_paths:
            self.assertTrue((ROOT / source).is_file(), source)
        _suite, discovered = runner.load_suite(definition.unittest_ids)
        self.assertEqual(discovered, definition.unittest_ids)

    def _document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(MANIFEST.read_text(encoding="utf-8")))

    def _load_document(self, document: dict[str, object], gate: str) -> runner.GateDefinition:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "manifest.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return runner.load_gate(path, gate)

    def _load_modified(self, gate: str, **updates: object) -> runner.GateDefinition:
        document = self._document()
        gates = cast(dict[str, dict[str, object]], document["gates"])
        gates[gate].update(updates)
        return self._load_document(document, gate)

    def test_exact_native_method_inventories_and_runtime(self) -> None:
        self.assertEqual(tuple(map(len, INVENTORIES.values())), (10, 13, 17))
        for gate in INVENTORIES:
            with self.subTest(gate=gate):
                self._assert_inventory(runner.load_gate(MANIFEST, gate))
                self.assertEqual(tuple(runner.NATIVE_GATE_TEST_IDS[gate]), INVENTORIES[gate])
                self.assertEqual(runner.NATIVE_GATE_RUNTIMES[gate], runner.load_gate(MANIFEST, gate).native_runtime)

    def test_r01_declaration_is_preserved_beside_explicit_kind(self) -> None:
        gates = cast(dict[str, dict[str, object]], self._document()["gates"])
        self.assertEqual(set(gates), {"R01", *INVENTORIES})
        r01 = dict(gates["R01"])
        self.assertEqual(r01.pop("validation_kind"), "conversion-parity")
        payload = json.dumps(r01, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), R01_PRESERVED_SHA256)

    def test_manifest_inventory_omission_duplicate_reorder_and_module_are_rejected(self) -> None:
        for gate, identifiers in INVENTORIES.items():
            mutations = (
                identifiers[1:], (*identifiers, identifiers[0]), tuple(reversed(identifiers)),
                (identifiers[0].rsplit(".", 1)[0],), ("tests.test_native_receipts_posix",), (),
            )
            for selection in mutations:
                with self.subTest(gate=gate, selection=selection), self.assertRaises(runner.ManifestError):
                    self._load_modified(gate, unittest_ids=list(selection))
        definition = replace(runner.load_gate(MANIFEST, "N01-linux"), unittest_ids=POSIX_IDS[1:])
        with self.assertRaises(runner.ManifestError):
            runner.validate_gate_definition(definition)

    def test_deleted_method_and_empty_class_cannot_satisfy_discovery(self) -> None:
        definition = runner.load_gate(MANIFEST, "N01-linux")
        original = posix.TestNativeReceiptsPosix.test_absent_and_identical_preserve_private_inode
        delattr(posix.TestNativeReceiptsPosix, POSIX[0])
        try:
            with self.assertRaises(AssertionError):
                self._assert_inventory(definition)
        finally:
            setattr(posix.TestNativeReceiptsPosix, POSIX[0], original)
        with self.assertRaises(runner.ManifestError):
            runner.load_suite(("tests.test_native_receipt_gate_policy.EmptyNativeFixture",))

    def test_native_runtime_environment_and_skip_mutations_are_rejected(self) -> None:
        for gate, runtime in RUNTIMES.items():
            values: dict[str, object] = dict(zip(("python_version", "platform", "machine"), runtime, strict=True))
            mutations: list[dict[str, object]] = [
                {"allowed_skips": {INVENTORIES[gate][0]: "missing capability"}},
                {"required_environment": {"GODOT_BIN": "required-executable"}},
                {"runtime": None}, {"runtime": {**values, "extra": "ignored"}},
            ]
            for key in values:
                missing = dict(values)
                del missing[key]
                mutations.extend(({"runtime": missing}, {"runtime": {**values, key: "wrong"}}))
            for update in mutations:
                with self.subTest(gate=gate, update=update), self.assertRaises(runner.ManifestError):
                    self._load_modified(gate, **update)

    def test_missing_unknown_and_cross_kind_cannot_bypass_parity(self) -> None:
        for gate, kind in (("R01", None), ("R01", "unknown"), ("R01", "native-receipts"),
                           ("N01-linux", "conversion-parity"), ("N01-windows", "unknown")):
            with self.subTest(gate=gate, kind=kind), self.assertRaises(runner.ManifestError):
                self._load_modified(gate, validation_kind=kind)
        for gate in ("R01", *INVENTORIES):
            document = self._document()
            gates = cast(dict[str, dict[str, object]], document["gates"])
            del gates[gate]["validation_kind"]
            with self.subTest(gate=gate), self.assertRaises(runner.ManifestError):
                self._load_document(document, gate)
        document = self._document()
        gates = cast(dict[str, dict[str, object]], document["gates"])
        gates["N01-other"] = gates["N01-linux"]
        with self.assertRaises(runner.ManifestError):
            self._load_document(document, "N01-other")
        del gates["R01"]["parity"]
        with tempfile.TemporaryDirectory() as raw, contextlib.redirect_stderr(io.StringIO()):
            path = Path(raw) / "manifest.json"
            output = Path(raw) / "receipt.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with patch.object(runner, "verify_prerequisites"), patch.object(runner, "run_gate") as execute:
                status = runner.main(["--manifest", str(path), "--gate", "R01", "--receipt", str(output)])
            self.assertEqual(status, 2)
            execute.assert_not_called()
            self.assertFalse(output.exists())

    def test_wrong_runtime_fails_before_collection_and_receipt(self) -> None:
        definition = runner.load_gate(MANIFEST, "N01-linux")
        with patch.object(runner.platform, "python_version", return_value="0.0.0"):
            with patch.object(runner, "load_suite") as collect, self.assertRaises(runner.ManifestError):
                runner.run_gate(definition, root=ROOT, stream=io.StringIO())
            with tempfile.TemporaryDirectory() as raw, contextlib.redirect_stderr(io.StringIO()):
                output = Path(raw) / "receipt.json"
                self.assertEqual(runner.main([
                    "--manifest", str(MANIFEST), "--gate", "N01-linux", "--receipt", str(output),
                ]), 2)
                self.assertFalse(output.exists())
        collect.assert_not_called()

    def test_partial_zero_and_skipped_native_execution_cannot_report_success(self) -> None:
        definition = runner.load_gate(MANIFEST, "N01-linux")
        for count in (0, len(definition.unittest_ids) - 1, len(definition.unittest_ids)):
            result = unittest.TestResult()
            result.testsRun = count
            with patch.object(runner, "verify_prerequisites"), patch.object(unittest.TextTestRunner, "run", return_value=result):
                status, receipt = runner.run_gate(definition, root=ROOT, stream=io.StringIO())
            self.assertEqual(status, 1)
            self.assertFalse(receipt["successful"])
        result = unittest.TestResult()
        result.addSkip(unittest.FunctionTestCase(lambda: None), "native capability unavailable")
        self.assertFalse(runner.result_is_allowed(result, {}))

    def _assert_workflow_job(self, job: str, gate: str, profile: str, receipt: str, interpreter: str,
                             upload_path: str, artifact_name: str, timeout: int) -> None:
        metadata = job.split("    steps:\n", 1)[0]
        self.assertEqual(len(re.findall(r"(?m)^    timeout-minutes:", metadata)), 1)
        self.assertIn(f"    timeout-minutes: {timeout}\n", metadata)
        self.assertNotRegex(metadata, r"(?m)^    (?:['\"]?(?:if|continue-on-error|defaults)['\"]?):")
        self.assertEqual(job.count("scripts.run_required_unittest"), 1)
        native = named_block(job, "      - name: ", "Run required native receipt gate")
        gate_env = "          NATIVE_RECEIPT_GATE: ${{ matrix.native_receipt_gate }}\n" if profile == "native-lock-workflow" else ""
        expected = (
            "      - name: Run required native receipt gate\n"
            "        timeout-minutes: 10\n"
            "        shell: bash\n"
            "        env:\n"
            f"          NATIVE_RECEIPT_PROFILE: {profile}\n"
            f"{gate_env}"
            "        run: >-\n"
            f"          {interpreter} -m scripts.run_required_unittest\n"
            f"          --manifest architecture-verification.json --gate {gate}\n"
            f'          --receipt "{receipt}"'
        )
        self.assertEqual(native.rstrip(), expected)
        upload = named_block(job, "      - name: ", "Upload required native receipt")
        expected_upload = (
            "      - name: Upload required native receipt\n"
            "        timeout-minutes: 10\n"
            f"        uses: {UPLOAD_ACTION}\n"
            "        with:\n"
            f"          name: {artifact_name}\n"
            f"          path: {upload_path}\n"
            "          if-no-files-found: error\n"
            "          retention-days: 7\n"
            "          archive: true"
        )
        self.assertEqual(upload.rstrip(), expected_upload)
        self.assertLess(job.index(native), job.index(upload))

    def _assert_workflows(self, tests: str, locks: str) -> None:
        self.assertEqual(tests.count("scripts.run_required_unittest"), 3)
        self.assertEqual(locks.count("scripts.run_required_unittest"), 1)
        for owner, host, native_runner, architecture, timeout in TEST_JOBS:
            job = named_block(tests, "  ", owner + ":")
            self._assert_workflow_job(job, f"N01-{host}", "stable", f"$RUNNER_TEMP/n01-tests-{host}.json", "python",
                                      f"${{{{ runner.temp }}}}/n01-tests-{host}.json", f"native-receipts-tests-{host}", timeout)
            self.assertIn(f"    runs-on: {native_runner}\n", job.split("    steps:\n", 1)[0])
            setup = named_block(job, "      - name: ", "Set up Python")
            self.assertIn(f"          python-version: '{RUNTIMES[f'N01-{host}'][0]}'\n", setup)
            self.assertIn(f"          architecture: {architecture}\n", setup)
            self.assertLess(job.index("Install and verify test dependencies"), job.index("Run required native receipt gate"))
        job = named_block(locks, "  ", "generate:")
        self._assert_workflow_job(job, '"$NATIVE_RECEIPT_GATE"', "native-lock-workflow",
                                  "dependency-locks/native-receipts/receipt.json", '"$CURRENT_PYTHON"',
                                  "dependency-locks/native-receipts/receipt.json",
                                  "native-receipts-dependency-locks-${{ matrix.platform }}", 45)
        self.assertIn("      RECEIPT_DIR: dependency-locks/artifact/receipts\n", job)
        self.assertIn("      ARTIFACT_DIR: dependency-locks/artifact\n", job)
        self.assertIn("      CURRENT_PYTHON: dependency-locks/work/current-generator/${{ matrix.venv_python }}\n", job)
        self.assertIn("    runs-on: ${{ matrix.runner }}\n", job)
        self.assertLess(job.index("Create and verify committed lock generator"), job.index("Run required native receipt gate"))
        self.assertLess(job.index("Upload required native receipt"), job.index("Generate bootstrap compatibility candidate"))
        matrix = job.split("    env:\n", 1)[0]
        for label, expected in LOCK_ENTRIES.items():
            entry = named_block(matrix, "          - platform: ", label)
            pairs = re.findall(r"(?m)^            (\w+): ([^\n]+)$", entry)
            self.assertEqual(len(pairs), len(dict(pairs)), "Duplicate native matrix key")
            self.assertEqual(dict(pairs), expected)
        self.assertEqual(len(re.findall(r"(?m)^          - platform:", matrix)), 3)

    def _workflows(self) -> tuple[str, str]:
        directory = ROOT / ".github/workflows"
        return ((directory / "tests.yml").read_text(encoding="utf-8"),
                (directory / "dependency-locks.yml").read_text(encoding="utf-8"))

    def test_workflows_require_all_native_gates_and_separate_receipts(self) -> None:
        self._assert_workflows(*self._workflows())

    def test_gate_step_missing_duplicate_and_bypass_mutations_are_rejected(self) -> None:
        tests, locks = self._workflows()
        for workflow, owner in (("tests", TEST_JOBS[0][0]), ("tests", TEST_JOBS[1][0]),
                                ("tests", TEST_JOBS[2][0]), ("locks", "generate")):
            source = tests if workflow == "tests" else locks
            job = named_block(source, "  ", owner + ":")
            native = named_block(job, "      - name: ", "Run required native receipt gate")
            mutations = (
                "", native + native,
                native.replace("        timeout-minutes: 10\n", ""),
                native.replace("        timeout-minutes: 10\n", "        timeout-minutes: 0\n"),
                native.replace("        shell: bash\n", "        shell: pwsh\n"),
                native.replace("        env:\n", "        if: false\n        env:\n"),
                native.replace("        env:\n", '        "if": false\n        env:\n'),
                native.replace("        env:\n", "        continue-on-error: true\n        env:\n"),
                native.replace("        env:\n", "        'continue-on-error': true\n        env:\n"),
                native.replace("        env:\n", "        working-directory: elsewhere\n        env:\n"),
                native.replace("--manifest architecture-verification.json", "--manifest missing.json"),
                native.replace("--gate ", "--gate N01-other "),
                native.replace("NATIVE_RECEIPT_PROFILE: stable", "NATIVE_RECEIPT_PROFILE: wrong"),
                native.replace("NATIVE_RECEIPT_PROFILE: native-lock-workflow", "NATIVE_RECEIPT_PROFILE: stable"),
                native.replace("          python -m scripts.run_required_unittest", "          python3 -m scripts.run_required_unittest"),
                native.replace('"$CURRENT_PYTHON" -m scripts.run_required_unittest', 'python -m scripts.run_required_unittest'),
                native.replace("NATIVE_RECEIPT_GATE: ${{ matrix.native_receipt_gate }}", "NATIVE_RECEIPT_GATE: N01-linux"),
                native.replace(" -m scripts.run_required_unittest", " -m wrong.module"),
                native.replace(" -m scripts.run_required_unittest", " -m scripts.run_required_unittest || true"),
                native.replace("        run: >-", "        run: |\n          set +e"),
                native.replace("--receipt ", "--receipt missing.json "),
            )
            for changed in mutations:
                if changed == native:
                    continue
                with self.subTest(workflow=workflow, owner=owner, changed=changed), self.assertRaises(AssertionError):
                    altered = source.replace(native, changed, 1)
                    self._assert_workflows(altered if workflow == "tests" else tests,
                                           altered if workflow == "locks" else locks)

    def test_upload_missing_duplicate_and_no_failure_flags_are_rejected(self) -> None:
        tests, locks = self._workflows()
        for workflow, owner in (("tests", TEST_JOBS[0][0]), ("tests", TEST_JOBS[1][0]),
                                ("tests", TEST_JOBS[2][0]), ("locks", "generate")):
            source = tests if workflow == "tests" else locks
            job = named_block(source, "  ", owner + ":")
            upload = named_block(job, "      - name: ", "Upload required native receipt")
            changes = (
                "", upload + upload,
                upload.replace("        timeout-minutes: 10\n", ""),
                upload.replace("        with:\n", "        if: false\n        with:\n"),
                upload.replace("        with:\n", '        "continue-on-error": true\n        with:\n'),
                upload.replace("          if-no-files-found: error\n", ""),
                upload.replace("          if-no-files-found: error", "          if-no-files-found: warn"),
                upload.replace("          if-no-files-found: error", "          if-no-files-found: ignore"),
                upload.replace("          archive: true", "          archive: false"),
                re.sub(r"(?m)^          path: [^\n]+\n", "", upload),
                upload.replace("          path: ", "          path: absent/"),
                upload.replace("          name: native-receipts", "          name: dependency-lock"),
            )
            for changed in changes:
                with self.subTest(workflow=workflow, owner=owner, changed=changed), self.assertRaises(AssertionError):
                    altered = source.replace(upload, changed, 1)
                    self._assert_workflows(altered if workflow == "tests" else tests,
                                           altered if workflow == "locks" else locks)

    def test_job_budget_condition_and_native_tuple_mutations_are_rejected(self) -> None:
        tests, locks = self._workflows()
        for workflow, owner in (("tests", TEST_JOBS[0][0]), ("tests", TEST_JOBS[1][0]),
                                ("tests", TEST_JOBS[2][0]), ("locks", "generate")):
            source = tests if workflow == "tests" else locks
            job = named_block(source, "  ", owner + ":")
            with self.subTest(workflow=workflow, owner=owner, duplicate=True), self.assertRaises(AssertionError):
                duplicated = source.replace(job, job + job, 1)
                self._assert_workflows(duplicated if workflow == "tests" else tests,
                                       duplicated if workflow == "locks" else locks)
            metadata, steps = job.split("    steps:\n", 1)
            changes = (
                re.sub(r"(?m)^    timeout-minutes: [^\n]+\n", "", metadata),
                re.sub(r"(?m)^    timeout-minutes: [^\n]+\n", "    timeout-minutes: 99\n", metadata),
                metadata.replace("    runs-on:", "    if: false\n    runs-on:", 1),
                metadata.replace("    runs-on:", '    "continue-on-error": true\n    runs-on:', 1),
            )
            for changed in changes:
                with self.subTest(workflow=workflow, owner=owner, changed=changed), self.assertRaises(AssertionError):
                    altered = source.replace(job, changed + "    steps:\n" + steps, 1)
                    self._assert_workflows(altered if workflow == "tests" else tests,
                                           altered if workflow == "locks" else locks)
        for owner, host, native_runner, architecture, _timeout in TEST_JOBS:
            for old, new in ((f"runs-on: {native_runner}", "runs-on: wrong"),
                             (f"python-version: '{RUNTIMES[f'N01-{host}'][0]}'", "python-version: '3.14.7'"),
                             (f"architecture: {architecture}", "architecture: wrong")):
                with self.subTest(owner=owner, replacement=new), self.assertRaises(AssertionError):
                    changed = mutate_block(tests, "  ", owner + ":", lambda job: job.replace(old, new, 1))
                    self._assert_workflows(changed, locks)
        for label, entry in LOCK_ENTRIES.items():
            for key, value in entry.items():
                with self.subTest(label=label, key=key), self.assertRaises(AssertionError):
                    changed = mutate_block(locks, "          - platform: ", label,
                                           lambda block: block.replace(f"{key}: {value}", f"{key}: wrong", 1))
                    self._assert_workflows(tests, changed)
        with self.assertRaises(AssertionError):
            self._assert_workflows(tests, locks.replace('"$CURRENT_PYTHON" -m scripts.run_required_unittest',
                                                       'python -m scripts.run_required_unittest', 1))

    def test_gate_cannot_move_before_verified_dependency_environment(self) -> None:
        tests, locks = self._workflows()
        for workflow, owner, preceding in (("tests", TEST_JOBS[0][0], "Install and verify test dependencies"),
                                           ("tests", TEST_JOBS[1][0], "Install and verify test dependencies"),
                                           ("tests", TEST_JOBS[2][0], "Install and verify test dependencies"),
                                           ("locks", "generate", "Create and verify committed lock generator")):
            source = tests if workflow == "tests" else locks
            job = named_block(source, "  ", owner + ":")
            native = named_block(job, "      - name: ", "Run required native receipt gate")
            earlier = named_block(job, "      - name: ", preceding)
            changed = job.replace(native, "", 1).replace(earlier, native + earlier, 1)
            with self.subTest(workflow=workflow, owner=owner), self.assertRaises(AssertionError):
                altered = source.replace(job, changed, 1)
                self._assert_workflows(altered if workflow == "tests" else tests,
                                       altered if workflow == "locks" else locks)

    def test_generator_profile_requires_pip_and_pip_tools_in_order(self) -> None:
        with patch.dict("os.environ", {"NATIVE_RECEIPT_PROFILE": "native-lock-workflow"}):
            self.assertEqual(producer_profile(), ("native-lock-workflow", ("pip", "pip-tools")))
        with patch.dict("os.environ", {"NATIVE_RECEIPT_PROFILE": "stable"}):
            self.assertEqual(producer_profile(), ("stable", ("pip",)))
        with patch.dict("os.environ", {"NATIVE_RECEIPT_PROFILE": "unknown"}), self.assertRaises(ValueError):
            producer_profile()

    def test_fixed_width_native_abi_preflight(self) -> None:
        self.assertEqual(native_abi_layout(), WINDOWS_AMD64_ABI)
