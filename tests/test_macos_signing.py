"""Credentialless boundary tests; mocks do not establish Apple signing trust."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import plistlib
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO
from unittest.mock import patch

from scripts import (
    macos_signing as signing,
    sign_notarize_macos as signing_cli,
    verify_macos_bundle_metadata as metadata,
)
from scripts.verify_macos_bundle_metadata import (
    MH_EXECUTE,
    BundleInspection,
    BundleInventory,
    BundleMetadata,
    MachOFile,
    VerificationReceipt,
)
from src.conversion.json_values import JsonObject, JsonValue

SOURCE_SHA = "1" * 40
SOURCE_TREE = "2" * 40
FAKE_CERTIFICATE = b"synthetic-test-certificate-not-a-real-credential"
FAKE_PASSWORD = "synthetic-test-password"
FAKE_P8 = b"synthetic-test-private-key-not-a-real-credential"
TEAM = "TESTTEAM01"
NOTARY_ID = "12345678-1234-4234-8234-123456789abc"


def context_value() -> JsonObject:
    return {
        "schema_version": 1, "purpose": "verification_only", "release_eligible": False,
        "repository": signing.REPOSITORY, "source": {"sha": SOURCE_SHA, "tree": SOURCE_TREE},
        "producer": {"run_id": 100, "run_attempt": 2, "workflow_id": 10, "event": "push", "branch": "main", "head_sha": SOURCE_SHA},
        "signing": {"run_id": 200, "run_attempt": 1, "event": "workflow_dispatch", "branch": "main", "head_sha": SOURCE_SHA},
        "architecture": "arm64",
        "unsigned_artifact": {"id": 300, "name": "GM2Godot-macos-arm64", "size": 10, "digest": "sha256:" + "3" * 64, "producer_run_id": 100, "producer_run_attempt": 1},
        "proof_artifact": {"id": 301, "name": "GM2Godot-macos-arm64-proof-100-1", "size": 10, "digest": "sha256:" + "4" * 64, "producer_run_id": 100, "producer_run_attempt": 1},
    }


def fake_credentials() -> signing.Credentials:
    return signing.Credentials(FAKE_CERTIFICATE, FAKE_PASSWORD, FAKE_P8, hashlib.sha1(FAKE_CERTIFICATE).hexdigest().upper(), TEAM, "TESTKEY001", NOTARY_ID, (FAKE_CERTIFICATE, FAKE_PASSWORD.encode(), FAKE_P8))


def environment_value(source: Path, runner: Path) -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": signing.REPOSITORY, "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": SOURCE_SHA,
        "GITHUB_RUN_ID": "200", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKSPACE": str(source),
        "RUNNER_TEMP": str(runner), "PATH": "/usr/bin:/bin", "HOME": str(runner),
        "MACOS_DEVELOPER_ID_P12_BASE64": base64.b64encode(FAKE_CERTIFICATE).decode(),
        "MACOS_DEVELOPER_ID_P12_PASSWORD": FAKE_PASSWORD,
        "APPLE_NOTARY_API_KEY_P8_BASE64": base64.b64encode(FAKE_P8).decode(),
        "MACOS_SIGNING_IDENTITY_SHA1": fake_credentials().identity_sha1.lower(),
        "APPLE_TEAM_ID": TEAM, "APPLE_NOTARY_KEY_ID": "TESTKEY001", "APPLE_NOTARY_ISSUER_ID": NOTARY_ID,
        "GITHUB_TOKEN": "synthetic-token", "PYTHONPATH": "untrusted-module-path",
    }


class GuardedEnvironment(Mapping[str, str]):
    def __init__(self, values: Mapping[str, str]) -> None:
        self._entries = dict(values)
        self.secret_reads: list[str] = []

    def __getitem__(self, name: str) -> str:
        if name in signing.SECRET_NAMES:
            self.secret_reads.append(name)
            raise AssertionError("A credential was read before a trusted guard")
        return self._entries[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True)
class PlannedCommand:
    prefix: tuple[str, ...]
    stdout: bytes = b""
    stderr: bytes = b""
    status: int = 0
    writes: tuple[tuple[Path, bytes], ...] = ()
    removes: tuple[Path, ...] = ()
    timed_out: bool = False


class QueueExecutor:
    """Finite subprocess effects on owned real files, with exact call order."""

    def __init__(self, rows: Sequence[PlannedCommand]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str]] = []
        self.metadata_budgets: list[signing.OperationBudgets | None] = []

    def execute(self, argv: Sequence[str], *, stdout: BinaryIO, stderr: BinaryIO, timeout: int, environment: Mapping[str, str], cwd: Path | None, cleanup_budget: signing.OperationBudgets | None = None) -> int:
        if not self.rows:
            raise AssertionError("Unexpected child invocation")
        row = self.rows.pop(0)
        actual = tuple(argv)
        if actual[:len(row.prefix)] != row.prefix:
            raise AssertionError("Unexpected child operation or argument order")
        self.calls.append(actual)
        self.environments.append(dict(environment))
        self.metadata_budgets.append(cleanup_budget)
        for path, body in row.writes:
            path.write_bytes(body)
        for path in row.removes:
            path.unlink()
        stdout.write(row.stdout)
        stderr.write(row.stderr)
        if row.timed_out:
            raise subprocess.TimeoutExpired("synthetic-command", timeout)
        return row.status


def options_value(root: Path) -> tuple[signing.SigningOptions, dict[str, str]]:
    root = root.resolve(strict=True)
    source, runner = root / "checkout", root / "runner"
    source.mkdir()
    runner.mkdir()
    context = runner / "context.json"
    context.write_text(json.dumps(context_value()))
    zip_path, dmg_path = runner / "GM2Godot-macos-arm64.zip", runner / "GM2Godot-macos-arm64.dmg"
    zip_path.write_bytes(b"synthetic unsigned zip")
    dmg_path.write_bytes(b"synthetic unsigned dmg")
    return signing.SigningOptions(context, source, zip_path, dmg_path, "arm64", runner / "output", runner / "proof"), environment_value(source, runner)


def commands_value(root: Path, rows: Sequence[PlannedCommand]) -> tuple[signing.Commands, QueueExecutor]:
    proof = root / "proof"
    proof.mkdir()
    executor = QueueExecutor(rows)
    return signing.Commands(executor, {"PATH": "/usr/bin:/bin", "GITHUB_TOKEN": "synthetic-token"}, proof, fake_credentials().redactions), executor


def mount_info(image: Path, mount: Path, devices: tuple[str, ...]) -> bytes:
    entities: list[dict[str, str]] = [{"mount-point": str(mount), "dev-entry": device} for device in devices]
    return plistlib.dumps({"images": [{"image-path": str(image), "system-entities": entities}, {"image-path": "/unrelated/image.dmg", "system-entities": [{"mount-point": "/unrelated/mount", "dev-entry": "/dev/disk999s1"}]}]})


def metadata_receipt() -> VerificationReceipt:
    return VerificationReceipt(BundleMetadata("com.infiland.GM2Godot", "0.8.99", "0.8.99", "12.0", "5" * 64), "arm64", 1, 0, (12, 0, 0))


def gui_value(zip_path: Path) -> JsonObject:
    return {"schema_version": 1, "successful": True, "runtime": {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin", "system": "Darwin", "machine": "arm64", "translated": False}, "zip_sha256": signing.seal_file(zip_path).sha256, "gui": {"returncode": 0, "cleanup_successful": True, "exact_receipt": True}, "source_app_gui_tested": False, "dmg_gui_tested": False}


class CleanupCheckingExecutor(QueueExecutor):
    def __init__(self, runner: Path, rows: Sequence[PlannedCommand]) -> None:
        super().__init__(rows)
        self.runner = runner
        self.gui_saw_private_cleanup = False

    def execute(self, argv: Sequence[str], *, stdout: BinaryIO, stderr: BinaryIO, timeout: int, environment: Mapping[str, str], cwd: Path | None, cleanup_budget: signing.OperationBudgets | None = None) -> int:
        if "--output" in argv:
            if list(self.runner.glob("gm2godot-signing-*")):
                raise AssertionError("GUI began before private signing resources were removed")
            self.gui_saw_private_cleanup = True
        return super().execute(argv, stdout=stdout, stderr=stderr, timeout=timeout, environment=environment, cwd=cwd, cleanup_budget=cleanup_budget)


def prepare_synthetic_artifacts(_options: signing.SigningOptions, _source: Path, output: Path, work: signing.PrivateWork, _commands: signing.Commands, _bundles: signing.BundleOperations, _private: signing.Credentials) -> tuple[signing.PreparedArtifacts, bool]:
    (work.path / "private-notary-material").write_bytes(FAKE_P8)
    zip_path, dmg_path = output / "GM2Godot-macos-arm64.zip", output / "GM2Godot-macos-arm64.dmg"
    zip_path.write_bytes(b"synthetic verified zip")
    dmg_path.write_bytes(b"synthetic verified dmg")
    actual = signing.PreparedArtifacts(zip_path, dmg_path, metadata_receipt(), [], {}, {}, True, (signing.seal_file(zip_path), signing.seal_file(dmg_path)))
    return actual, True


def successful_git_response(argv: Sequence[str], *, check: bool, capture_output: bool, text: bool, timeout: int, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    if argv[-1] == "HEAD":
        result = SOURCE_SHA
    elif argv[-1] == "HEAD^{tree}":
        result = SOURCE_TREE
    else:
        result = ""
    return subprocess.CompletedProcess(argv, 0, result, "")


def orchestration_report() -> bytes:
    value: JsonObject = {"schema_version": 1, "successful": True, "runtime": {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin", "system": "Darwin", "machine": "arm64", "translated": False}, "zip_sha256": hashlib.sha256(b"synthetic verified zip").hexdigest(), "gui": {"returncode": 0, "cleanup_successful": True, "exact_receipt": True}, "source_app_gui_tested": False, "dmg_gui_tested": False}
    return json.dumps(value).encode()


class PlannedWorkerProcess:
    def __init__(self, outcomes: Sequence[int | subprocess.TimeoutExpired]) -> None:
        self.outcomes = list(outcomes)
        self.returncode: int | None = None
        self.wait_timeouts: list[float | None] = []
        self.signals: list[str] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        result = self.outcomes.pop(0)
        if isinstance(result, subprocess.TimeoutExpired):
            raise result
        self.returncode = result
        return result

    def terminate(self) -> None:
        self.signals.append("terminate")

    def kill(self) -> None:
        self.signals.append("kill")


def worker_value(options: signing.SigningOptions) -> tuple[signing.MetadataRequest, Path]:
    script = options.source_root / "scripts/sign_notarize_macos.py"
    script.parent.mkdir()
    script.write_text("# synthetic trusted script binding\n")
    app = options.unsigned_zip.parent / "GM2Godot.app"
    app.mkdir()
    return signing.MetadataRequest(options.context_path, options.source_root, app, options.unsigned_zip, options.unsigned_dmg), script


def cli_arguments(options: signing.SigningOptions) -> list[str]:
    return ["--context", str(options.context_path), "--source-root", str(options.source_root), "--unsigned-zip", str(options.unsigned_zip), "--unsigned-dmg", str(options.unsigned_dmg), "--architecture", options.architecture, "--output-root", str(options.output_root), "--proof-root", str(options.proof_root)]




def publication_context_value(event: signing.BuildEvent = "push") -> JsonObject:
    # A separate synthetic acquisition output, not an in-place bootstrap upgrade.
    return {
        "schema_version": 1, "purpose": "publication", "release_eligible": True,
        "repository": signing.REPOSITORY, "source": {"sha": SOURCE_SHA, "tree": SOURCE_TREE},
        "producer": {"run_id": 100, "run_attempt": 2, "workflow_id": 10, "event": event, "branch": "main", "head_sha": SOURCE_SHA},
        "signing": {"run_id": 100, "run_attempt": 2, "event": event, "branch": "main", "head_sha": SOURCE_SHA},
        "architecture": "arm64",
        "unsigned_artifact": {"id": 300, "name": "GM2Godot-macos-arm64", "size": 10, "digest": "sha256:" + "3" * 64, "producer_run_id": 100, "producer_run_attempt": 1},
        "proof_artifact": {"id": 301, "name": "GM2Godot-macos-arm64-proof-100-1", "size": 10, "digest": "sha256:" + "4" * 64, "producer_run_id": 100, "producer_run_attempt": 1},
    }


def publication_options_value(root: Path, event: signing.BuildEvent = "push") -> tuple[signing.SigningOptions, dict[str, str]]:
    initial, environment = options_value(root)
    # Fixtures construct a fresh separately attested publication document. The
    # production module provides no bootstrap-context conversion operation.
    initial.context_path.write_text(json.dumps(publication_context_value(event)))
    options = replace(initial, purpose="publication")
    environment.update({
        "GITHUB_EVENT_NAME": event, "GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_WORKFLOW_REF": f"{signing.REPOSITORY}/.github/workflows/release.yml@refs/heads/main",
        "GITHUB_WORKFLOW_SHA": SOURCE_SHA,
    })
    return options, environment


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_CLOEXEC"), "Signing resource ownership requires POSIX descriptors; genuine native macOS signing is a separate gate")
class TestMacOSSigning(unittest.TestCase):
    def test_context_rejects_publication_duplicate_unknown_and_nonfinite_fields(self) -> None:
        value = context_value()
        value["purpose"], value["release_eligible"] = "publication", True
        with self.assertRaises(signing.SigningFailure):
            signing.parse_context(value)
        value = context_value()
        value["extra"] = None
        with self.assertRaises(signing.SigningFailure):
            signing.parse_context(value)
        for body in (b'{"schema_version":1,"schema_version":1}', b'{"value":NaN}'):
            with self.subTest(body=body), self.assertRaises(signing.SigningFailure):
                signing.decode_object(body, "test")

    def test_partial_native_job_attempt_is_retained_and_cannot_be_relabelled(self) -> None:
        context = signing.parse_context(context_value())
        self.assertEqual((context.producer.run_attempt, context.unsigned_artifact.producer_run_attempt), (2, 1))
        for key, value in (("producer_run_attempt", 3), ("producer_run_attempt", True), ("name", "GM2Godot-macos-arm64-proof-100-2"), ("id", 300)):
            data = context_value()
            artifact = data["proof_artifact"]
            assert isinstance(artifact, dict)
            artifact[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(signing.SigningFailure):
                signing.parse_context(data)

    def test_trust_event_guards_precede_every_credential_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, values = options_value(Path(name))
            for key, value in (("GITHUB_REF", "refs/heads/untrusted"), ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_SHA", "0" * 40), ("GITHUB_RUN_ID", "201")):
                environment = GuardedEnvironment({**values, key: value})
                with self.subTest(key=key), self.assertRaises(signing.SigningFailure):
                    signing.sign_verification(options, environment=environment)
                self.assertEqual(environment.secret_reads, [])
            self.assertFalse(options.output_root.exists())
            self.assertFalse(options.proof_root.exists())

    def test_workspace_head_tree_and_index_binding_are_checked_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, values = options_value(Path(name))
            environment = GuardedEnvironment(values)
            context = signing.parse_context(context_value())
            responses = [subprocess.CompletedProcess(["git"], 0, SOURCE_SHA + "\n", ""), subprocess.CompletedProcess(["git"], 0, SOURCE_TREE + "\n", ""), subprocess.CompletedProcess(["git"], 0, " M README.md\n", "")]
            with patch("scripts.macos_signing.subprocess.run", side_effect=responses) as run, self.assertRaises(signing.SigningFailure):
                signing.trusted_source(options, context, environment)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(environment.secret_reads, [])
            unrelated = Path(name) / "other"
            unrelated.mkdir()
            with self.assertRaises(signing.SigningFailure):
                signing.trusted_source(options, context, {**values, "GITHUB_WORKSPACE": str(unrelated)})

    def test_output_and_proof_roots_reject_both_nested_directions_and_existing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, values = options_value(Path(name))
            for output, proof in ((options.output_root, options.output_root / "proof"), (options.proof_root / "output", options.proof_root)):
                nested = signing.SigningOptions(options.context_path, options.source_root, options.unsigned_zip, options.unsigned_dmg, "arm64", output, proof)
                with self.subTest(output=output), self.assertRaises(signing.SigningFailure):
                    signing.prepare_roots(nested, options.source_root, values)
            self.assertFalse(options.output_root.exists())
            options.output_root.mkdir()
            with self.assertRaises(signing.SigningFailure):
                signing.prepare_roots(options, options.source_root, values)
            self.assertFalse(options.proof_root.exists())

    def test_payload_binding_rejects_symlink_hardlink_and_exclusive_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / "payload"
            seal = signing.write_exclusive(path, b"original")
            self.assertEqual(seal, signing.seal_file(path))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                signing.write_exclusive(path, b"replacement")
            symlink = root / "symlink"
            symlink.symlink_to(path)
            with self.assertRaises(signing.SigningFailure):
                signing.seal_file(symlink)
            hardlink = root / "hardlink"
            os.link(path, hardlink)
            with self.assertRaises(signing.SigningFailure):
                signing.seal_file(path)
            self.assertEqual(path.read_bytes(), b"original")

    def test_confidential_commands_scrub_child_environment_and_keep_safe_logs_only(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            commands, executor = commands_value(Path(name), [PlannedCommand(("security",), FAKE_PASSWORD.encode(), FAKE_P8), PlannedCommand(("inspect",), FAKE_PASSWORD.encode(), FAKE_P8)])
            result = commands.result(["security", FAKE_PASSWORD], "confidential", confidential=True)
            self.assertEqual((result.stdout, result.stderr), (b"[REDACTED]", b"[REDACTED]"))
            self.assertEqual(list(commands.proof.iterdir()), [])
            commands.run(["inspect"], "inspect", combined=True)
            self.assertNotIn("GITHUB_TOKEN", executor.environments[0])
            self.assertEqual(executor.environments[0]["LC_ALL"], "C")
            self.assertEqual([path.read_bytes() for path in sorted(commands.proof.iterdir())], [b"[REDACTED]", b"[REDACTED]"])
            self.assertNotIn(FAKE_PASSWORD, repr(fake_credentials()))

    def test_timeout_and_oversized_logs_never_become_success(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            commands, _executor = commands_value(Path(name), [PlannedCommand(("timeout",), stdout=b"partial", timed_out=True), PlannedCommand(("large",), stdout=b"x" * (signing.MAX_COMMAND_BYTES + 1))])
            result = commands.result(["timeout"], "timeout", timeout=1)
            self.assertTrue(result.timed_out)
            self.assertEqual(result.returncode, -1)
            self.assertEqual((commands.proof / "001-timeout-stdout.log").read_bytes(), b"partial")
            with self.assertRaises(signing.SigningFailure):
                commands.result(["large"], "large")
            self.assertFalse((commands.proof / "002-large-stdout.log").exists())

    def test_cleanup_reserve_survives_operation_deadline_without_unbounded_retries(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            with patch("scripts.macos_signing.time.monotonic", return_value=100.0):
                commands, executor = commands_value(Path(name), [PlannedCommand(("owned-cleanup",))])
            with patch("scripts.macos_signing.time.monotonic", return_value=4001.0):
                with self.assertRaises(signing.SigningFailure):
                    commands.run(["ordinary"], "ordinary")
                self.assertEqual(executor.calls, [])
                commands.run(["owned-cleanup"], "owned-cleanup", cleanup=True)
            self.assertEqual(executor.calls, [("owned-cleanup",)])
            with patch("scripts.macos_signing.time.monotonic", return_value=4302.0), self.assertRaises(signing.SigningFailure):
                commands.run(["owned-cleanup"], "owned-cleanup", cleanup=True)
            self.assertEqual(len(executor.calls), 1)

    def test_failed_keychain_create_cleans_its_partial_file_and_preserves_unrelated_file(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            unrelated = root / "unrelated.keychain-db"
            unrelated.write_bytes(b"untouched")
            with signing.PrivateWork(root) as work:
                owned = work.path / "signing.keychain-db"
                commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/security", "create-keychain"), status=1, writes=((owned, b"partial"),)), PlannedCommand(("/usr/bin/security", "delete-keychain"), removes=(owned,))])
                keychain = signing.Keychain(work, commands, fake_credentials())
                with self.assertRaises(signing.SigningFailure):
                    with keychain:
                        self.fail("Failed keychain creation must not enter body")
                self.assertTrue(keychain.deleted)
                self.assertEqual(executor.calls[-1], ("/usr/bin/security", "delete-keychain", str(owned)))
                self.assertEqual(list(commands.proof.iterdir()), [])
            self.assertFalse(work.path.exists())
            self.assertEqual(unrelated.read_bytes(), b"untouched")

    def test_keychain_cleanup_failure_retains_the_original_error_object(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with signing.PrivateWork(root) as work:
                owned = work.path / "signing.keychain-db"
                owned.write_bytes(b"owned")
                commands, _executor = commands_value(root, [PlannedCommand(("/usr/bin/security", "delete-keychain"), status=1)])
                keychain = signing.Keychain(work, commands, fake_credentials())
                keychain.attempted = True
                original = ValueError("synthetic primary failure")
                with self.assertRaises(ValueError) as caught:
                    keychain.cleanup(original)
                self.assertIs(caught.exception, original)
                self.assertIsInstance(original.__cause__, signing.SigningFailure)
                self.assertFalse(keychain.deleted)
                self.assertTrue(owned.exists())
            self.assertTrue(work.removed)

    def test_partial_attach_recovers_only_the_exact_owned_image_mount_device(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            image = root / "final.dmg"
            image.write_bytes(b"image")
            with signing.PrivateWork(root) as work:
                mount_path = work.path / "distributed-dmg"
                commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/hdiutil", "attach"), status=1), PlannedCommand(("/usr/bin/hdiutil", "info"), stdout=mount_info(image, mount_path, ("/dev/disk7s1",))), PlannedCommand(("/usr/bin/hdiutil", "detach", "/dev/disk7s1")), PlannedCommand(("/usr/bin/hdiutil", "info"), stdout=mount_info(image, mount_path, ()))])
                mount = signing.DmgMount(work, commands, image)
                with self.assertRaises(signing.SigningFailure):
                    with mount:
                        self.fail("Failed attach must not enter body")
                self.assertTrue(mount.detached)
                self.assertEqual([call for call in executor.calls if call[1] == "detach"], [("/usr/bin/hdiutil", "detach", "/dev/disk7s1")])
                self.assertEqual(executor.rows, [])

    def test_ambiguous_mount_does_not_detach_any_device_and_blocks_cleanup_success(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            image = root / "final.dmg"
            image.write_bytes(b"image")
            with signing.PrivateWork(root) as work:
                mount_path = work.path / "distributed-dmg"
                body = mount_info(image, mount_path, ("/dev/disk7s1", "/dev/disk8s1"))
                commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/hdiutil", "info"), stdout=body), PlannedCommand(("/usr/bin/hdiutil", "info"), stdout=body)])
                mount = signing.DmgMount(work, commands, image)
                with self.assertRaises(signing.SigningFailure):
                    mount.cleanup(None)
                self.assertFalse(mount.detached)
                self.assertFalse(any(call[1] == "detach" for call in executor.calls))

    def test_notary_submission_keeps_actual_id_and_hash_bound_accepted_log(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            p8 = root / "notary.p8"
            p8.write_bytes(FAKE_P8)
            payload = root / "payload.zip"
            payload.write_bytes(b"actual synthetic pre-staple submission")
            log = json.dumps({"jobId": NOTARY_ID.upper(), "archiveFilename": "payload.zip", "status": "Accepted", "statusCode": 0, "issues": None}).encode()
            commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/xcrun", "notarytool", "submit"), stdout=json.dumps({"id": NOTARY_ID, "status": "Accepted"}).encode()), PlannedCommand(("/usr/bin/xcrun", "notarytool", "log", NOTARY_ID), writes=((root / "app-notary-raw.json", log),))])
            row = signing.Notary(commands, fake_credentials(), p8).submit(root / "payload.zip", "app")
            self.assertEqual(row, {"id": NOTARY_ID, "status": "Accepted", "submission": signing.seal_file(payload).as_json(), "log": signing.seal_file(commands.proof / "app-notary-log.json").as_json()})
            self.assertEqual((commands.proof / "app-notary-log.json").read_bytes(), log)
            self.assertEqual(sum(call[2] == "submit" for call in executor.calls), 1)

    def test_rejected_or_timed_out_notary_is_not_resubmitted_and_keeps_returned_log(self) -> None:
        for timed_out in (False, True):
            with self.subTest(timed_out=timed_out), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                p8 = root / "notary.p8"
                p8.write_bytes(FAKE_P8)
                payload = root / "payload.zip"
                payload.write_bytes(b"actual synthetic pre-staple submission")
                log = json.dumps({"jobId": NOTARY_ID.upper(), "archiveFilename": "payload.zip", "status": "Invalid", "statusCode": 4000, "issues": [{"message": "synthetic rejection"}]}).encode()
                commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/xcrun", "notarytool", "submit"), stdout=json.dumps({"id": NOTARY_ID, "status": "Invalid"}).encode(), status=1, timed_out=timed_out), PlannedCommand(("/usr/bin/xcrun", "notarytool", "log"), writes=((root / "app-notary-raw.json", log),))])
                with self.assertRaises(signing.SigningFailure):
                    signing.Notary(commands, fake_credentials(), p8).submit(root / "payload.zip", "app")
                self.assertEqual((commands.proof / "app-notary-log.json").read_bytes(), log)
                self.assertEqual(sum(call[2] == "submit" for call in executor.calls), 1)

    def test_notary_log_secret_echo_is_redacted_and_never_attested(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            p8 = root / "notary.p8"
            p8.write_bytes(FAKE_P8)
            payload = root / "payload.zip"
            payload.write_bytes(b"actual synthetic pre-staple submission")
            log = json.dumps({"jobId": NOTARY_ID.upper(), "archiveFilename": "payload.zip", "status": "Accepted", "statusCode": 0, "issues": None, "echo": FAKE_PASSWORD}).encode()
            commands, _executor = commands_value(root, [PlannedCommand(("/usr/bin/xcrun", "notarytool", "submit"), stdout=json.dumps({"id": NOTARY_ID, "status": "Accepted"}).encode()), PlannedCommand(("/usr/bin/xcrun", "notarytool", "log"), writes=((root / "app-notary-raw.json", log),))])
            with self.assertRaises(signing.SigningFailure):
                signing.Notary(commands, fake_credentials(), p8).submit(root / "payload.zip", "app")
            retained = (commands.proof / "app-notary-log.json").read_bytes()
            self.assertIn(b"[REDACTED]", retained)
            self.assertNotIn(FAKE_PASSWORD.encode(), retained)

    def test_notary_log_optional_fields_bind_pre_staple_submission_and_uuid_case(self) -> None:
        submitted = signing.FileSeal("app-submission.zip", 12, "a" * 64)
        log: JsonObject = {"jobId": NOTARY_ID.upper(), "archiveFilename": submitted.name, "status": "Accepted", "issues": []}
        signing.verify_notary_log(log, NOTARY_ID, submitted)
        log["statusCode"], log["sha256"] = 0, submitted.sha256.upper()
        signing.verify_notary_log(log, NOTARY_ID, submitted)
        for key, value in (("archiveFilename", "public-final.zip"), ("sha256", "b" * 64), ("statusCode", False), ("jobId", "ffffffff-1234-4234-8234-123456789abc")):
            changed = dict(log)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(signing.SigningFailure):
                signing.verify_notary_log(changed, NOTARY_ID, submitted)

    def test_notary_submit_mutation_blocks_success_without_resubmission(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            p8, payload = root / "notary.p8", root / "payload.zip"
            p8.write_bytes(FAKE_P8)
            payload.write_bytes(b"pre-staple original")
            commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/xcrun", "notarytool", "submit"), stdout=json.dumps({"id": NOTARY_ID, "status": "Accepted"}).encode(), writes=((payload, b"changed during submission"),))])
            with self.assertRaises(signing.SigningFailure):
                signing.Notary(commands, fake_credentials(), p8).submit(payload, "app")
            self.assertEqual(len(executor.calls), 1)
            self.assertFalse((commands.proof / "signing.json").exists())

    def test_signing_target_order_covers_native_code_nested_bundles_and_root_without_deep(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            app = root / "GM2Godot.app"
            nested = app / "Contents" / "Frameworks" / "Owned.framework"
            nested.mkdir(parents=True)
            native = nested / "Owned"
            native.write_bytes(b"synthetic native")
            (app / "external.framework").symlink_to(root / "outside", target_is_directory=True)
            inspection = BundleInspection(metadata_receipt().metadata, BundleInventory((MachOFile(native.relative_to(app).as_posix(), "arm64", (12, 0, 0), MH_EXECUTE, 0o755),), ()))
            commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/codesign", "--force")) for _index in range(3)])
            with signing.PrivateWork(root) as work:
                keychain = signing.Keychain(work, commands, fake_credentials())
                signing.sign_tree(commands, keychain, app, inspection)
            self.assertEqual([call[-1] for call in executor.calls], [str(native), str(nested), str(app)])
            self.assertTrue(all("--timestamp" in call and "runtime" in call and "--deep" not in call for call in executor.calls))

    def test_code_signature_certificate_is_observed_and_normalized_not_caller_stamped(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            certificate_root = root / "certificate"
            display = f"Authority=Developer ID Application: Synthetic ({TEAM})\nTimestamp=Oct 5, 2026 at 12:00:00 PM\nTeamIdentifier={TEAM}\nCodeDirectory v=20500 flags=0x10000(runtime)\n".encode()
            commands, executor = commands_value(root, [PlannedCommand(("/usr/bin/codesign", "--verify")), PlannedCommand(("/usr/bin/codesign", "--display", "--verbose=4"), stderr=display), PlannedCommand(("/usr/bin/codesign", "--display", "--extract-certificates"), writes=((certificate_root / "certificate-0", FAKE_CERTIFICATE),)), PlannedCommand(("/usr/bin/codesign", "--display", "--entitlements"), stdout=plistlib.dumps({}))])
            row = signing.code_identity(commands, root / "main", fake_credentials(), certificate_root, runtime_required=True, app=False)
            self.assertEqual(row["certificate_sha1"], fake_credentials().identity_sha1)
            self.assertIs(row["runtime"], True)
            self.assertIs(row["entitlements_verified_empty"], True)
            self.assertEqual(executor.rows, [])

    def test_signature_policy_rejects_wrong_team_missing_runtime_or_nonempty_entitlements(self) -> None:
        displays = (f"Authority=Developer ID Application: Synthetic ({TEAM})\nTimestamp=now\nTeamIdentifier=WRONGTEAM0\nCodeDirectory flags=runtime\n", f"Authority=Developer ID Application: Synthetic ({TEAM})\nTimestamp=now\nTeamIdentifier={TEAM}\nCodeDirectory flags=0\n")
        for display in displays:
            with self.subTest(display=display), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                commands, _executor = commands_value(root, [PlannedCommand(("/usr/bin/codesign", "--verify")), PlannedCommand(("/usr/bin/codesign", "--display"), stderr=display.encode())])
                with self.assertRaises(signing.SigningFailure):
                    signing.code_identity(commands, root / "main", fake_credentials(), root / "certificate", runtime_required=True, app=False)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            commands, _executor = commands_value(root, [PlannedCommand(("/usr/bin/codesign",), stdout=plistlib.dumps({"com.apple.security.cs.allow-jit": True}))])
            with self.assertRaises(signing.SigningFailure):
                signing.empty_entitlements(commands, root / "main")

    def test_signed_gui_uses_scrubbed_isolated_child_and_actual_hash_runtime_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            payload = root / "GM2Godot-macos-arm64.zip"
            payload.write_bytes(b"signed synthetic payload")
            report = gui_value(payload)
            commands, executor = commands_value(root, [PlannedCommand((sys.executable, "-I", "-B"), writes=((root / "proof" / "signed-gui.json", json.dumps(report).encode()),))])
            value = signing.signed_gui(commands, root / "source", payload, "arm64")
            self.assertEqual(value["zip_sha256"], signing.seal_file(payload).sha256)
            self.assertIs(value["dmg_gui_tested"], False)
            self.assertNotIn("GITHUB_TOKEN", executor.environments[0])
            self.assertEqual(executor.calls[0][:4], (sys.executable, "-I", "-B", str(root / "source" / "scripts" / "verify_macos_gui_artifact.py")))

    def test_signed_gui_rejects_mutated_hash_foreign_runtime_and_cleanup_failure(self) -> None:
        for role in ("hash", "runtime", "cleanup"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                payload = root / "GM2Godot-macos-arm64.zip"
                payload.write_bytes(b"signed synthetic payload")
                report = gui_value(payload)
                if role == "hash":
                    report["zip_sha256"] = "0" * 64
                elif role == "runtime":
                    runtime = report["runtime"]
                    assert isinstance(runtime, dict)
                    runtime["python_version"] = "3.14.7"
                else:
                    gui = report["gui"]
                    assert isinstance(gui, dict)
                    gui["cleanup_successful"] = False
                commands, _executor = commands_value(root, [PlannedCommand((sys.executable, "-I"), writes=((root / "proof" / "signed-gui.json", json.dumps(report).encode()),))])
                with self.assertRaises(signing.SigningFailure):
                    signing.signed_gui(commands, root / "source", payload, "arm64")

    def test_final_receipt_preserves_actual_metadata_and_refuses_missing_cleanup_or_changed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            zip_path, dmg_path = root / "final.zip", root / "final.dmg"
            zip_path.write_bytes(b"final zip")
            dmg_path.write_bytes(b"final dmg")
            seals = (signing.seal_file(zip_path), signing.seal_file(dmg_path))
            artifacts = signing.PreparedArtifacts(zip_path, dmg_path, metadata_receipt(), [], {}, {}, True, seals)
            context = signing.parse_context(context_value())
            receipt = signing.signing_receipt(context, fake_credentials(), seals, artifacts, {}, True, True)
            self.assertEqual(receipt["metadata"], signing.metadata_value(metadata_receipt()))
            self.assertEqual(receipt["purpose"], "verification_only")
            self.assertIs(receipt["release_eligible"], False)
            with self.assertRaises(signing.SigningFailure):
                signing.signing_receipt(context, fake_credentials(), seals, artifacts, {}, False, True)
            dmg_path.write_bytes(b"changed final dmg")
            with self.assertRaises(signing.SigningFailure):
                signing.signing_receipt(context, fake_credentials(), seals, artifacts, {}, True, True)

    def test_orchestration_runs_signed_gui_after_private_cleanup_and_keeps_actual_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = options_value(Path(name))
            executor = CleanupCheckingExecutor(Path(environment["RUNNER_TEMP"]), [PlannedCommand((sys.executable, "-I")), PlannedCommand((sys.executable, "-I"), writes=((options.proof_root / "signed-gui.json", orchestration_report()),))])
            with patch("scripts.macos_signing.subprocess.run", side_effect=successful_git_response), patch("scripts.macos_signing.prepare_artifacts", side_effect=prepare_synthetic_artifacts):
                receipt = signing.sign_verification(options, environment=environment, executor=executor)
            self.assertTrue(executor.gui_saw_private_cleanup)
            self.assertEqual(receipt["metadata"], signing.metadata_value(metadata_receipt()))
            self.assertIs(receipt["release_eligible"], False)
            self.assertEqual(receipt["cleanup"], {"keychain_deleted": True, "private_files_removed": True, "owned_mounts_detached": True})
            self.assertEqual(signing.decode_object((options.proof_root / "signing.json").read_bytes(), "retained receipt"), receipt)
            self.assertTrue(all("MACOS_DEVELOPER_ID_P12_PASSWORD" not in row and "GITHUB_TOKEN" not in row for row in executor.environments))

    def test_final_gui_mutation_cannot_publish_a_successful_signing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = options_value(Path(name))
            executor = CleanupCheckingExecutor(Path(environment["RUNNER_TEMP"]), [PlannedCommand((sys.executable, "-I")), PlannedCommand((sys.executable, "-I"), writes=((options.proof_root / "signed-gui.json", orchestration_report()), (options.output_root / "GM2Godot-macos-arm64.dmg", b"changed during GUI")))])
            with patch("scripts.macos_signing.subprocess.run", side_effect=successful_git_response), patch("scripts.macos_signing.prepare_artifacts", side_effect=prepare_synthetic_artifacts), self.assertRaises(signing.SigningFailure):
                signing.sign_verification(options, environment=environment, executor=executor)
            self.assertTrue(executor.gui_saw_private_cleanup)
            self.assertFalse((options.proof_root / "signing.json").exists())

    def test_cli_reports_authored_safe_failure_and_fixed_cleanup_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, _environment = options_value(Path(name))
            failure = signing.SigningFailure("Missing required protected setting: APPLE_TEAM_ID")
            failure.add_note("Owned keychain cleanup failed (OSError)")
            failure.add_note("untrusted note " + FAKE_PASSWORD)
            output, errors = io.StringIO(), io.StringIO()
            with patch("scripts.sign_notarize_macos.sign_verification", side_effect=failure), patch("sys.stdout", output), patch("sys.stderr", errors):
                self.assertEqual(signing_cli.main(cli_arguments(options)), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(errors.getvalue(), "Protected verification failed: Missing required protected setting: APPLE_TEAM_ID. Owned keychain cleanup failed. No publication is authorized.\n")
            self.assertNotIn(FAKE_PASSWORD, errors.getvalue())
            self.assertNotIn("Traceback", errors.getvalue())

    def test_cli_never_prints_foreign_secret_message_cause_argv_or_notes(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, _environment = options_value(Path(name))
            errors_to_raise = (OSError(FAKE_PASSWORD), ValueError(FAKE_PASSWORD), subprocess.CalledProcessError(1, ["security", FAKE_PASSWORD], output=FAKE_P8, stderr=FAKE_CERTIFICATE))
            for failure in errors_to_raise:
                with self.subTest(kind=type(failure).__name__):
                    failure.add_note(FAKE_PASSWORD)
                    failure.__cause__ = ValueError(FAKE_PASSWORD)
                    output, errors = io.StringIO(), io.StringIO()
                    with patch("scripts.sign_notarize_macos.sign_verification", side_effect=failure), patch("sys.stdout", output), patch("sys.stderr", errors):
                        self.assertEqual(signing_cli.main(cli_arguments(options)), 1)
                    self.assertEqual(output.getvalue(), "")
                    self.assertEqual(errors.getvalue(), f"Protected verification failed: {type(failure).__name__}. No publication is authorized.\n")
                    self.assertNotIn(FAKE_PASSWORD, errors.getvalue())
                    self.assertNotIn("Traceback", errors.getvalue())

    def test_direct_worker_refuses_credential_and_injection_keys_before_input_or_verifier(self) -> None:
        absent = Path("/not-an-input")
        request = signing.MetadataRequest(absent, absent, absent, absent, absent)
        for key in (*signing.SECRET_NAMES, "GITHUB_TOKEN", "GH_TOKEN", "GIT_CONFIG_COUNT", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "CUSTOM_CREDENTIAL"):
            with self.subTest(key=key):
                guarded = GuardedEnvironment({key: FAKE_PASSWORD})
                with patch("scripts.macos_signing.os.environ", guarded), patch("scripts.verify_macos_bundle_metadata.verify_artifacts") as verifier, self.assertRaises(signing.SigningFailure) as caught:
                    signing.metadata_worker(request, entry_script=absent)
                self.assertEqual(str(caught.exception), "Metadata worker refuses credential or source-injection environment keys")
                self.assertEqual(guarded.secret_reads, [])
                verifier.assert_not_called()

    def test_worker_checks_actual_entry_and_checkout_before_maintained_verification(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = options_value(Path(name))
            request, script = worker_value(options)
            scrubbed = signing.safe_environment(environment)
            with patch.dict(os.environ, scrubbed, clear=True), patch("scripts.macos_signing.script_source_root", return_value=options.source_root), patch("scripts.macos_signing.subprocess.run", side_effect=successful_git_response) as probes, patch("scripts.verify_macos_bundle_metadata.verify_artifacts", return_value=metadata_receipt()) as verifier:
                result = signing.metadata_worker(request, entry_script=script)
            verifier.assert_called_once_with(options.source_root, request.app, options.unsigned_zip, options.unsigned_dmg, "arm64")
            self.assertEqual(probes.call_count, 6)
            self.assertTrue(all(call.kwargs["timeout"] == 15 for call in probes.call_args_list))
            self.assertEqual(result["metadata_return"], signing.metadata_value(metadata_receipt()))
            altered = subprocess.CompletedProcess(["git"], 0, "wrong-source", "")
            with patch.dict(os.environ, scrubbed, clear=True), patch("scripts.macos_signing.script_source_root", return_value=options.source_root), patch("scripts.macos_signing.subprocess.run", return_value=altered), patch("scripts.verify_macos_bundle_metadata.verify_artifacts") as rejected, self.assertRaises(signing.SigningFailure):
                signing.metadata_worker(request, entry_script=script)
            rejected.assert_not_called()

    def test_worker_refuses_an_alternate_or_symlink_entry_before_checkout_and_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = options_value(Path(name))
            request, script = worker_value(options)
            alternate = script.with_name("alternate.py")
            alternate.write_text(script.read_text())
            linked = script.with_name("linked.py")
            linked.symlink_to(script)
            for entry in (alternate, linked):
                with self.subTest(entry=entry.name), patch.dict(os.environ, signing.safe_environment(environment), clear=True), patch("scripts.macos_signing.script_source_root", return_value=options.source_root), patch("scripts.macos_signing.verify_checkout") as probes, patch("scripts.verify_macos_bundle_metadata.verify_artifacts") as verifier, self.assertRaises(signing.SigningFailure):
                    signing.metadata_worker(request, entry_script=entry)
                probes.assert_not_called()
                verifier.assert_not_called()

    def test_maintained_verifier_failures_are_safe_phase_failures_not_raw_secret_text(self) -> None:
        bundles = signing.BundleOperations()
        failure = metadata.MetadataVerificationError(FAKE_PASSWORD)
        with patch("scripts.verify_macos_bundle_metadata.load_source_policy", side_effect=failure), self.assertRaises(signing.SigningFailure) as caught:
            bundles.policy(Path("/source"))
        self.assertEqual(str(caught.exception), "Maintained source policy verification failed")
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(FAKE_PASSWORD, signing.safe_failure_message(caught.exception))
        with patch("scripts.verify_macos_bundle_metadata.inspect_zip_bundle", side_effect=failure), self.assertRaises(signing.SigningFailure) as caught_zip:
            bundles.zip(Path("/zip"), {}, "arm64")
        self.assertEqual(str(caught_zip.exception), "Maintained ZIP verification failed")
        with patch("scripts.verify_macos_bundle_metadata.inspect_app_bundle", side_effect=failure), self.assertRaises(signing.SigningFailure) as caught_app:
            bundles.app(Path("/app"), {}, "arm64")
        self.assertEqual(str(caught_app.exception), "Maintained App verification failed")

    def test_indirect_hdiutil_child_inherits_only_scrubbed_worker_environment(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = options_value(Path(name))
            request, script = worker_value(options)
            observed: list[dict[str, str]] = []

            def hdiutil_child(argv: Sequence[str], *, check: bool, stdin: int, stdout: BinaryIO, stderr: BinaryIO, env: Mapping[str, str], shell: bool, timeout: float) -> subprocess.CompletedProcess[bytes]:
                observed.append(dict(env))
                stdout.write(plistlib.dumps({"images": []}))
                self.assertFalse(shell)
                self.assertEqual(argv[0], "/usr/bin/hdiutil")
                return subprocess.CompletedProcess(argv, 1 if "attach" in argv else 0)

            def verification(source: Path, app: Path, zip_path: Path, dmg_path: Path, architecture: str) -> VerificationReceipt:
                # The public maintained DMG route reaches its actual environment-
                # copying hdiutil boundary; only the external process is mocked.
                with self.assertRaises(metadata.MetadataVerificationError):
                    metadata.inspect_dmg(dmg_path, {})
                return metadata_receipt()

            scrubbed = signing.safe_environment(environment)
            with patch.dict(os.environ, scrubbed, clear=True), patch("scripts.macos_signing.script_source_root", return_value=options.source_root), patch("scripts.macos_signing.verify_checkout"), patch("scripts.verify_macos_bundle_metadata.verify_artifacts", side_effect=verification), patch("scripts.verify_macos_bundle_metadata.subprocess.run", side_effect=hdiutil_child):
                result = signing.metadata_worker(request, entry_script=script)
            self.assertTrue(observed)
            self.assertTrue(all(not signing.secret_environment_name(key) for row in observed for key in row))
            self.assertTrue(all(row["LC_ALL"] == "C" for row in observed))
            self.assertEqual(result["metadata_return"], signing.metadata_value(metadata_receipt()))

    def test_metadata_parent_uses_scrubbed_isolated_worker_and_full_machine_return(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            options, environment = options_value(root)
            request, _script = worker_value(options)
            context = signing.parse_context(context_value())
            machine: JsonObject = {"schema_version": 1, "successful": True, "source": {"sha": SOURCE_SHA, "tree": SOURCE_TREE}, "verification_returned": True, "metadata_return": signing.metadata_value(metadata_receipt())}
            executor = QueueExecutor([PlannedCommand((sys.executable, "-I"), stdout=json.dumps(machine).encode())])
            proof = root / "proof"
            proof.mkdir()
            commands = signing.Commands(executor, environment, proof, fake_credentials().redactions)
            actual = signing.BundleOperations().artifacts(options.context_path, options.source_root, request.app, options.unsigned_zip, options.unsigned_dmg, "arm64", commands)
            self.assertEqual(actual, metadata_receipt())
            self.assertEqual(executor.calls[0][:5], (sys.executable, "-I", "-B", str(options.source_root / "scripts/sign_notarize_macos.py"), "--metadata-worker"))
            self.assertIs(executor.metadata_budgets[0], commands.budgets)
            self.assertFalse(any(signing.secret_environment_name(key) for key in executor.environments[0]))
            machine["successful"] = False
            with self.assertRaises(signing.SigningFailure):
                signing.parse_metadata_return(json.dumps(machine).encode(), context, "arm64")

    def test_cooperative_worker_timeout_preserves_primary_and_does_not_force_kill(self) -> None:
        primary = subprocess.TimeoutExpired("synthetic worker", 300)
        process = PlannedWorkerProcess((primary, 1))
        budgets = signing.OperationBudgets()
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            signing.supervise_metadata_worker(process, 300, budgets)
        self.assertIs(caught.exception, primary)
        self.assertEqual(process.signals, ["terminate"])
        self.assertEqual(process.wait_timeouts[0], 300)
        self.assertLessEqual(process.wait_timeouts[1] or 0, 120)
        self.assertIsNotNone(budgets.cleanup_deadline)

    def test_forced_worker_timeout_blocks_receipt_and_parent_private_cleanup_still_runs(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            primary = subprocess.TimeoutExpired("synthetic worker", 300)
            process = PlannedWorkerProcess((primary, subprocess.TimeoutExpired("synthetic cooperative wait", 120), -9))
            commands, executor = commands_value(root, [])
            work = signing.PrivateWork(root)
            owned = work.path / "signing.keychain-db"
            owned.write_bytes(b"synthetic owned keychain")
            executor.rows.append(PlannedCommand(("/usr/bin/security", "delete-keychain"), removes=(owned,)))
            keychain = signing.Keychain(work, commands, fake_credentials())
            keychain.attempted = True
            with self.assertRaises(signing.SigningFailure) as caught:
                with work:
                    try:
                        signing.supervise_metadata_worker(process, 300, commands.budgets)
                    except signing.SigningFailure as failure:
                        keychain.cleanup(failure)
                        raise
            self.assertEqual(str(caught.exception), "Metadata worker forcibly stopped; verifier cleanup remains unconfirmed")
            self.assertIs(caught.exception.__cause__, primary)
            self.assertEqual(process.signals, ["terminate", "kill"])
            self.assertTrue(keychain.deleted)
            self.assertTrue(work.removed)
            self.assertFalse((commands.proof / "signing.json").exists())

    def test_worker_sigterm_enters_maintained_finally_and_restores_previous_handler(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = options_value(Path(name))
            request, script = worker_value(options)
            cleaned: list[bool] = []
            previous = signal.getsignal(signal.SIGTERM)

            def interrupted(source: Path, app: Path, zip_path: Path, dmg_path: Path, architecture: str) -> VerificationReceipt:
                try:
                    signing.interrupt_metadata_worker(signal.SIGTERM, None)
                finally:
                    cleaned.append(True)

            with patch.dict(os.environ, signing.safe_environment(environment), clear=True), patch("scripts.macos_signing.script_source_root", return_value=options.source_root), patch("scripts.macos_signing.verify_checkout"), patch("scripts.verify_macos_bundle_metadata.verify_artifacts", side_effect=interrupted), self.assertRaises(signing.SigningFailure):
                signing.metadata_worker(request, entry_script=script)
            self.assertEqual(cleaned, [True])
            self.assertIs(signal.getsignal(signal.SIGTERM), previous)

    def test_deadline_exhausted_after_gui_blocks_success_receipt_with_private_resources_removed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = options_value(Path(name))
            executor = CleanupCheckingExecutor(Path(environment["RUNNER_TEMP"]), [PlannedCommand((sys.executable, "-I")), PlannedCommand((sys.executable, "-I"), writes=((options.proof_root / "signed-gui.json", orchestration_report()),))])

            def observed_clock() -> float:
                return 4100.0 if executor.gui_saw_private_cleanup else 100.0

            with patch("scripts.macos_signing.time.monotonic", side_effect=observed_clock), patch("scripts.macos_signing.subprocess.run", side_effect=successful_git_response), patch("scripts.macos_signing.prepare_artifacts", side_effect=prepare_synthetic_artifacts), self.assertRaises(signing.SigningFailure) as caught:
                signing.sign_verification(options, environment=environment, executor=executor)
            self.assertEqual(str(caught.exception), "Protected operation deadline exhausted")
            self.assertTrue(executor.gui_saw_private_cleanup)
            self.assertFalse(list(Path(environment["RUNNER_TEMP"]).glob("gm2godot-signing-*")))
            self.assertFalse((options.proof_root / "signing.json").exists())


    def test_publication_mode_requires_separate_context_without_upgrading_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, values = options_value(Path(name))
            original = options.context_path.read_bytes()
            guarded = GuardedEnvironment(values)
            with self.assertRaises(signing.SigningFailure):
                signing.sign_publication(options, environment=guarded)
            with self.assertRaises(signing.SigningFailure):
                signing.sign_publication(replace(options, purpose="publication"), environment=guarded)
            self.assertEqual(options.context_path.read_bytes(), original)
            self.assertEqual(guarded.secret_reads, [])
            self.assertFalse(options.output_root.exists())
            self.assertFalse(options.proof_root.exists())
        with self.assertRaises(signing.SigningFailure):
            signing.parse_publication_context(context_value())
        with self.assertRaises(signing.SigningFailure):
            signing.parse_context(publication_context_value())

    def test_publication_context_binds_same_actual_event_run_attempt_and_artifact_history(self) -> None:
        events: tuple[signing.BuildEvent, ...] = ("push", "workflow_dispatch")
        for event in events:
            with self.subTest(event=event):
                context = signing.parse_publication_context(publication_context_value(event))
                self.assertEqual(context.producer.as_json()["event"], event)
                self.assertEqual(context.signing.as_json()["event"], event)
                self.assertEqual((context.producer.run_id, context.signing.run_id), (100, 100))
                self.assertEqual((context.producer.run_attempt, context.signing.run_attempt), (2, 2))
                self.assertEqual(context.unsigned_artifact.producer_run_attempt, 1)
                self.assertEqual(context.purpose, "publication")
        changes: tuple[tuple[str, str, JsonValue], ...] = (
            ("signing", "run_id", 101), ("signing", "run_attempt", 1),
            ("signing", "event", "workflow_dispatch"), ("producer", "event", "pull_request"),
            ("producer", "branch", "untrusted"), ("signing", "head_sha", "0" * 40),
            ("producer", "workflow_id", True), ("unsigned_artifact", "producer_run_attempt", 3),
        )
        for role, field, value in changes:
            data = publication_context_value()
            row = data[role]
            assert isinstance(row, dict)
            row[field] = value
            with self.subTest(role=role, field=field), self.assertRaises(signing.SigningFailure):
                signing.parse_publication_context(data)

    def test_publication_environment_guards_precede_credentials_and_owned_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, values = publication_options_value(Path(name))
            wrong: tuple[tuple[str, str], ...] = (
                ("GITHUB_REPOSITORY", "someone/else"), ("GITHUB_REF", "refs/heads/feature"),
                ("GITHUB_EVENT_NAME", "workflow_dispatch"), ("GITHUB_SHA", "0" * 40),
                ("GITHUB_RUN_ID", "101"), ("GITHUB_RUN_ATTEMPT", "3"),
                ("GITHUB_WORKFLOW_REF", f"{signing.REPOSITORY}/.github/workflows/macos-signing-verification.yml@refs/heads/main"),
                ("GITHUB_WORKFLOW_REF", f"{signing.REPOSITORY}/.github/workflows/release.yml@refs/heads/feature"),
                ("GITHUB_WORKFLOW_SHA", "0" * 40),
            )
            for field, value in wrong:
                guarded = GuardedEnvironment({**values, field: value})
                with self.subTest(field=field, value=value), self.assertRaises(signing.SigningFailure):
                    signing.sign_publication(options, environment=guarded)
                self.assertEqual(guarded.secret_reads, [])
            self.assertFalse(options.output_root.exists())
            self.assertFalse(options.proof_root.exists())
            guarded = GuardedEnvironment(values)
            dirty = [subprocess.CompletedProcess(["git"], 0, SOURCE_SHA, ""), subprocess.CompletedProcess(["git"], 0, SOURCE_TREE, ""), subprocess.CompletedProcess(["git"], 0, " M tracked.py", "")]
            with patch("scripts.macos_signing.subprocess.run", side_effect=dirty), self.assertRaises(signing.SigningFailure):
                signing.sign_publication(options, environment=guarded)
            self.assertEqual(guarded.secret_reads, [])
            self.assertFalse(options.proof_root.exists())

    def test_publication_uses_same_cleaned_pipeline_and_emits_actual_event_in_closed_receipt(self) -> None:
        events: tuple[signing.BuildEvent, ...] = ("push", "workflow_dispatch")
        for event in events:
            with self.subTest(event=event), tempfile.TemporaryDirectory() as name:
                options, environment = publication_options_value(Path(name), event)
                initial_context = options.context_path.read_bytes()
                executor = CleanupCheckingExecutor(Path(environment["RUNNER_TEMP"]), [PlannedCommand((sys.executable, "-I", "-B")), PlannedCommand((sys.executable, "-I", "-B"), writes=((options.proof_root / "signed-gui.json", orchestration_report()),))])
                with patch("scripts.macos_signing.subprocess.run", side_effect=successful_git_response), patch("scripts.macos_signing.prepare_artifacts", side_effect=prepare_synthetic_artifacts):
                    receipt = signing.sign_publication(options, environment=environment, executor=executor)
                self.assertTrue(executor.gui_saw_private_cleanup)
                self.assertEqual(receipt["purpose"], "publication")
                self.assertIs(receipt["release_eligible"], True)
                self.assertEqual(receipt["metadata"], signing.metadata_value(metadata_receipt()))
                producer, actual = receipt["producer"], receipt["signing"]
                assert isinstance(producer, dict) and isinstance(actual, dict)
                self.assertEqual((producer["event"], actual["event"]), (event, event))
                self.assertEqual((producer["run_id"], actual["run_id"], producer["run_attempt"], actual["run_attempt"]), (100, 100, 2, 2))
                self.assertEqual(options.context_path.read_bytes(), initial_context)
                self.assertEqual(signing.decode_object((options.proof_root / "signing.json").read_bytes(), "synthetic receipt"), receipt)
                self.assertFalse(any(signing.secret_environment_name(key) for row in executor.environments for key in row))

    def test_publication_context_mutation_after_gui_blocks_eligible_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = publication_options_value(Path(name))
            altered = publication_context_value()
            source = altered["source"]
            assert isinstance(source, dict)
            source["tree"] = "0" * 40
            executor = CleanupCheckingExecutor(Path(environment["RUNNER_TEMP"]), [PlannedCommand((sys.executable, "-I")), PlannedCommand((sys.executable, "-I"), writes=((options.proof_root / "signed-gui.json", orchestration_report()), (options.context_path, json.dumps(altered).encode())))])
            with patch("scripts.macos_signing.subprocess.run", side_effect=successful_git_response), patch("scripts.macos_signing.prepare_artifacts", side_effect=prepare_synthetic_artifacts), self.assertRaises(signing.SigningFailure) as failed:
                signing.sign_publication(options, environment=environment, executor=executor)
            self.assertEqual(str(failed.exception), "Acquired publication context changed")
            self.assertTrue(executor.gui_saw_private_cleanup)
            self.assertFalse((options.proof_root / "signing.json").exists())

    def test_publication_metadata_worker_requires_explicit_matching_mode_and_returns_actual_fields(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, environment = publication_options_value(Path(name))
            initial_request, entry = worker_value(options)
            request = replace(initial_request, purpose="publication")
            with patch.dict(os.environ, signing.safe_environment(environment), clear=True), patch("scripts.macos_signing.script_source_root", return_value=options.source_root), patch("scripts.macos_signing.subprocess.run", side_effect=successful_git_response), patch("scripts.verify_macos_bundle_metadata.verify_artifacts", return_value=metadata_receipt()) as verifier:
                actual = signing.metadata_worker(request, entry_script=entry)
                self.assertEqual(actual["metadata_return"], signing.metadata_value(metadata_receipt()))
                verifier.assert_called_once_with(options.source_root, request.app, request.zip_path, request.dmg_path, "arm64")
                with self.assertRaises(signing.SigningFailure):
                    signing.metadata_worker(initial_request, entry_script=entry)
                self.assertEqual(verifier.call_count, 1)
            executor = QueueExecutor([PlannedCommand((sys.executable, "-I", "-B"), stdout=json.dumps(actual).encode())])
            options.proof_root.mkdir()
            commands = signing.Commands(executor, environment, options.proof_root, fake_credentials().redactions)
            returned = signing.BundleOperations().artifacts(options.context_path, options.source_root, request.app, request.zip_path, request.dmg_path, "arm64", commands, purpose="publication")
            self.assertEqual(returned, metadata_receipt())
            self.assertIn(("--purpose", "publication"), tuple(zip(executor.calls[0], executor.calls[0][1:], strict=False)))
            self.assertFalse(any(signing.secret_environment_name(key) for key in executor.environments[0]))

    def test_public_cli_defaults_stay_bootstrap_and_explicit_publication_guards_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, values = publication_options_value(Path(name))
            guarded = GuardedEnvironment({**values, "GITHUB_WORKFLOW_REF": "untrusted-workflow"})
            for extra in ([], ["--purpose", "publication"]):
                output, errors = io.StringIO(), io.StringIO()
                with self.subTest(extra=extra), patch("scripts.macos_signing.os.environ", guarded), patch("sys.stdout", output), patch("sys.stderr", errors):
                    self.assertEqual(signing_cli.main([*extra, *cli_arguments(options)]), 1)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("No publication is authorized.", errors.getvalue())
                self.assertNotIn("Traceback", errors.getvalue())
                self.assertNotIn(FAKE_PASSWORD, errors.getvalue())
                self.assertEqual(guarded.secret_reads, [])
            self.assertFalse(options.output_root.exists())
            self.assertFalse(options.proof_root.exists())
            with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as failed:
                signing_cli.main(["--purpose", "unknown", *cli_arguments(options)])
            self.assertEqual(failed.exception.code, 2)

    def test_public_cli_explicit_mode_preserves_options_and_does_not_claim_publication(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            options, _values = publication_options_value(Path(name))
            output = io.StringIO()
            with patch("scripts.sign_notarize_macos.sign_publication", return_value={"architecture": "arm64"}) as publish, patch("scripts.sign_notarize_macos.sign_verification") as bootstrap, patch("sys.stdout", output):
                self.assertEqual(signing_cli.main(["--purpose", "publication", *cli_arguments(options)]), 0)
            publish.assert_called_once_with(options)
            bootstrap.assert_not_called()
            self.assertEqual(output.getvalue(), "Publication-mode Developer ID proof complete for arm64; publication still requires the same-run receipt gate.\n")


if __name__ == "__main__":
    unittest.main()
