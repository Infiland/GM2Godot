from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO
from unittest import mock

from scripts import acquire_macos_signing_inputs as subject
from src.conversion.json_values import JsonArray, JsonObject

SHA = "a" * 40
TREE = "b" * 40


class FakeApi:
    def __init__(self, responses: dict[str, JsonObject]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, path: str) -> JsonObject:
        self.calls.append(path)
        return copy.deepcopy(self.responses[path])


def fixture() -> tuple[JsonObject, dict[str, JsonObject]]:
    source: JsonObject = {"sha": SHA, "tree": TREE}
    signing: JsonObject = {"run_id": 900, "run_attempt": 1, "event": "workflow_dispatch", "branch": "main", "head_sha": SHA}
    trusted: JsonObject = {"schema_version": 1, "purpose": "verification_only", "release_eligible": False, "repository": subject.REPOSITORY, "source": source, "signing": signing, "architecture": "arm64"}
    repository: JsonObject = {"full_name": subject.REPOSITORY}
    run: JsonObject = {"id": 200, "run_number": 10, "run_attempt": 2, "workflow_id": 55, "path": subject.BUILD_PATH, "head_sha": SHA, "head_branch": "main", "event": "push", "repository": repository, "status": "completed", "conclusion": "success"}
    names = ("windows", "linux", "macos-arm64", "macos-x86_64")
    step_names = ("Verify native macOS build runtime", "Install and verify dependencies", "Verify native macOS GUI lifecycle tests", "Verify packaged macOS GUI", "Upload macOS artifacts", "Upload macOS build proof")
    jobs: JsonArray = []
    for index, name in enumerate(names):
        steps: JsonArray = [{"name": step, "status": "completed", "conclusion": "success"} for step in step_names]
        job: JsonObject = {"id": 300 + index, "name": f"build (host, {name}, mode)", "run_id": 200, "run_attempt": 1, "head_sha": SHA, "head_branch": "main", "workflow_name": "Build and Release", "run_url": f"https://api.github.com{subject.API_ROOT}/runs/200", "status": "completed", "conclusion": "success", "started_at": "2026-01-01T00:01:00Z", "completed_at": "2026-01-01T00:05:00Z", "steps": steps}
        jobs.append(job)
    producer: JsonObject = {"id": 200, "head_sha": SHA, "head_branch": "main"}
    artifacts: JsonArray = []
    for artifact_id, name in [(400, "GM2Godot-macos-arm64"), (401, "GM2Godot-macos-arm64-proof-200-1")]:
        artifact: JsonObject = {"id": artifact_id, "name": name, "expired": False, "workflow_run": producer, "size_in_bytes": 5, "digest": "sha256:" + hashlib.sha256(b"abcde").hexdigest(), "created_at": "2026-01-01T00:04:00Z"}
        artifacts.append(artifact)
    run_values: JsonArray = [run]
    responses: dict[str, JsonObject] = {
        f"{subject.API_ROOT}/workflows/release.yml": {"id": 55, "path": subject.BUILD_PATH, "state": "active"},
        f"{subject.API_ROOT}/workflows/55/runs?head_sha={SHA}&event=push&branch=main&per_page=100&page=1": {"total_count": 1, "workflow_runs": run_values},
        f"{subject.API_ROOT}/runs/200": run,
        f"{subject.API_ROOT}/runs/200/jobs?filter=all&per_page=100&page=1": {"total_count": 4, "jobs": jobs},
        f"{subject.API_ROOT}/runs/200/artifacts?per_page=100&page=1": {"total_count": 2, "artifacts": artifacts},
    }
    return trusted, responses


def regular_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in entries.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, body)


def proof_entries(unsigned: bytes, policy: JsonObject, variant: str) -> dict[str, bytes]:
    runtime: JsonObject = {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin", "system": "Darwin", "machine": "arm64", "translated": False}
    selected: JsonArray = [f"__main__.NativeLifecycleTests.{name}" for name in subject.NATIVE_METHODS]
    native: JsonObject = {"schema_version": 1, "successful": True, "tests_run": 7, "skips": 0, "failures": 0, "errors": 0, "expected_failures": 0, "unexpected_successes": 0, "selected": selected, "started": selected, "completed": selected, "runtime": runtime}
    gui: JsonObject = {"schema_version": 1, "successful": True, "runtime": runtime, "zip_sha256": hashlib.sha256(unsigned).hexdigest(), "source_policy": policy, "proof_variant": variant}
    return {f"release-macos-arm64-{kind}.json": json.dumps(value).encode() for kind, value in [("bootstrap", {}), ("dependencies", {}), ("native-tests", native), ("gui", gui)]}


def archive_fixture(root: Path) -> tuple[JsonObject, dict[str, JsonObject], JsonObject, dict[str, bytes]]:
    trusted, responses = fixture()
    policy: JsonObject = {"version": "unit-version"}
    entries = proof_entries(b"original ZIP", policy, "A")
    paths = (root / "payload.zip", root / "proof.zip")
    regular_zip(paths[0], {"GM2Godot-macos-arm64.zip": b"original ZIP", "GM2Godot-macos-arm64.dmg": b"original DMG"})
    regular_zip(paths[1], entries)
    artifacts = responses[f"{subject.API_ROOT}/runs/200/artifacts?per_page=100&page=1"]["artifacts"]
    if not isinstance(artifacts, list):
        raise AssertionError("fixture artifacts unavailable")
    for row, path in zip(artifacts, paths, strict=True):
        artifact = subject.object_value(row, "fixture artifact")
        body = path.read_bytes()
        artifact["size_in_bytes"] = len(body)
        artifact["digest"] = "sha256:" + hashlib.sha256(body).hexdigest()
    return trusted, responses, policy, entries


class ArchiveReplacement:
    def __init__(self, path: Path, replacement: Path, at_open: int) -> None:
        self.path = path
        self.replacement = replacement
        self.at_open = at_open
        self.opens = 0
        self.original = zipfile.ZipFile

    @contextmanager
    def open(self, stream: BinaryIO) -> Generator[zipfile.ZipFile, None, None]:
        self.opens += 1
        replacing = self.opens == self.at_open
        held = self.path.with_suffix(".held")
        if replacing:
            self.path.replace(held)
            self.replacement.replace(self.path)
        try:
            with self.original(stream) as archive:
                yield archive
        finally:
            if replacing:
                self.path.replace(self.replacement)
                held.replace(self.path)


class FakeResponse:
    def __init__(self, status: int, *, location: str | None = None, body: bytes = b"") -> None:
        self.status = status
        self.location = location
        self.body = io.BytesIO(body)

    def getheader(self, name: str) -> str | None:
        return self.location if name == "Location" else None

    def read1(self, count: int) -> bytes:
        return self.body.read(count)


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        self.requests.append((method, target, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class TestMacosSigningInputs(unittest.TestCase):
    def test_exact_source_selection_preserves_retained_native_attempt(self) -> None:
        trusted, responses = fixture()
        value = subject.selection(FakeApi(responses), trusted)
        context = subject.object_value(value["context"], "context")
        producer = subject.object_value(context["producer"], "producer")
        unsigned = subject.object_value(context["unsigned_artifact"], "unsigned")
        proof = subject.object_value(context["proof_artifact"], "proof")
        self.assertEqual(producer["run_attempt"], 2)
        self.assertEqual(unsigned["producer_run_attempt"], 1)
        self.assertEqual(proof["producer_run_attempt"], 1)
        self.assertEqual(proof["name"], "GM2Godot-macos-arm64-proof-200-1")
        self.assertIs(context["release_eligible"], False)

    def test_latest_failed_source_run_does_not_fall_back_to_old_success(self) -> None:
        trusted, responses = fixture()
        responses[f"{subject.API_ROOT}/runs/200"]["conclusion"] = "failure"
        with self.assertRaisesRegex(subject.SigningInputError, "did not succeed"):
            subject.selection(FakeApi(responses), trusted)

    def test_duplicate_job_attempt_and_future_attempt_are_rejected(self) -> None:
        trusted, responses = fixture()
        endpoint = f"{subject.API_ROOT}/runs/200/jobs?filter=all&per_page=100&page=1"
        jobs = responses[endpoint]["jobs"]
        self.assertIsInstance(jobs, list)
        if not isinstance(jobs, list):
            self.fail("fixture jobs unavailable")
        for mode in ("duplicate", "future"):
            changed = copy.deepcopy(responses)
            changed_jobs = copy.deepcopy(jobs)
            row = subject.object_value(copy.deepcopy(changed_jobs[0]), "fixture job")
            row["id"] = 999
            row["run_attempt"] = 1 if mode == "duplicate" else 3
            changed_jobs.append(row)
            changed[endpoint]["jobs"] = changed_jobs
            changed[endpoint]["total_count"] = 5
            with self.subTest(mode=mode), self.assertRaises(subject.SigningInputError):
                subject.selection(FakeApi(changed), trusted)

    def test_expired_wrong_source_and_missing_api_digest_fail(self) -> None:
        trusted, responses = fixture()
        endpoint = f"{subject.API_ROOT}/runs/200/artifacts?per_page=100&page=1"
        for field, value in (("expired", True), ("digest", None)):
            changed = copy.deepcopy(responses)
            values = changed[endpoint]["artifacts"]
            if not isinstance(values, list):
                self.fail("fixture artifacts unavailable")
            subject.object_value(values[0], "fixture artifact")[field] = value
            with self.subTest(field=field), self.assertRaises(subject.SigningInputError):
                subject.selection(FakeApi(changed), trusted)
        changed = copy.deepcopy(responses)
        changed[f"{subject.API_ROOT}/runs/200"]["head_sha"] = "c" * 40
        with self.assertRaises(subject.SigningInputError):
            subject.selection(FakeApi(changed), trusted)

    def test_trusted_context_rejects_pr_fork_and_wrong_checkout_before_git_or_api(self) -> None:
        environment = {"GITHUB_REPOSITORY": subject.REPOSITORY, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA, "GITHUB_RUN_ID": "900", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKSPACE": str(Path.cwd())}
        for key, value in (("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_REPOSITORY", "fork/GM2Godot"), ("GITHUB_REF", "refs/heads/untrusted")):
            changed = dict(environment)
            changed[key] = value
            with self.subTest(key=key), mock.patch.object(subject, "git_value") as read_git, self.assertRaises(subject.SigningInputError):
                subject.trusted_context(Path("."), "arm64", changed)
            read_git.assert_not_called()
        with mock.patch.object(subject, "git_value", return_value="c" * 40), self.assertRaisesRegex(subject.SigningInputError, "checkout differs"):
            subject.trusted_context(Path.cwd(), "arm64", environment)

    def test_workspace_and_dirty_index_reject_before_policy_or_api(self) -> None:
        environment = {"GITHUB_REPOSITORY": subject.REPOSITORY, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA, "GITHUB_RUN_ID": "900", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKSPACE": str(Path.cwd())}
        changed = dict(environment)
        changed["GITHUB_WORKSPACE"] = str(Path.cwd().parent)
        with mock.patch.object(subject, "git_value") as read_git, self.assertRaisesRegex(subject.SigningInputError, "workspace"):
            subject.trusted_context(Path.cwd(), "arm64", changed)
        read_git.assert_not_called()
        result = subject.subprocess.CompletedProcess(["git"], 0, stdout=b" M tracked.py\n", stderr=b"")
        with mock.patch.object(subject, "git_value", return_value=SHA), mock.patch.object(subject.subprocess, "run", return_value=result) as status, self.assertRaisesRegex(subject.SigningInputError, "not clean"):
            subject.trusted_context(Path.cwd(), "arm64", environment)
        self.assertEqual(status.call_args.args[0], ["git", "status", "--porcelain=v1", "--untracked-files=no"])
        self.assertEqual(status.call_args.kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")

    @unittest.skipUnless(os.name == "posix", "native macOS private acquisition uses POSIX ownership/modes")
    def test_owned_outputs_are_direct_fresh_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            environment = {"RUNNER_TEMP": temp}
            for rejected in (Path("relative.json"), root / "nested" / "context.json"):
                with self.subTest(path=str(rejected)), self.assertRaises(subject.SigningInputError):
                    subject.owned_path(rejected, environment)
            selection = root / "selection.json"
            subject.write_json(subject.owned_path(selection, environment), {"schema_version": 1})
            self.assertEqual(stat.S_IMODE(selection.stat().st_mode), 0o600)
            self.assertEqual(subject.owned_path(selection, environment, existing_selection=True), selection)
            with self.assertRaisesRegex(subject.SigningInputError, "already exists"):
                subject.owned_path(selection, environment)
            os.chmod(selection, 0o644)
            with self.assertRaisesRegex(subject.SigningInputError, "private"):
                subject.owned_path(selection, environment, existing_selection=True)

    def test_storage_transfer_never_forwards_auth_to_new_origin(self) -> None:
        api = FakeConnection(FakeResponse(302, location="https://productionresultssa0.blob.core.windows.net/actions-results/unit?sig=UNIT_SIGNED_QUERY"))
        storage = FakeConnection(FakeResponse(200, body=b"abcde"))
        record: JsonObject = {"id": 400, "size": 5, "digest": "sha256:" + hashlib.sha256(b"abcde").hexdigest()}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(subject, "HTTPSConnection", side_effect=[api, storage]):
            destination = Path(temp) / "body.zip"
            subject.download_body(record, "UNIT_TOKEN", destination)
            self.assertEqual(destination.read_bytes(), b"abcde")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(api.requests[0][2]["Authorization"], "Bearer UNIT_TOKEN")
        self.assertNotIn("Authorization", storage.requests[0][2])
        self.assertNotIn("Cookie", storage.requests[0][2])
        self.assertTrue(api.closed)
        self.assertTrue(storage.closed)

    def test_foreign_redirect_rejects_before_storage_request_without_echoing_query(self) -> None:
        api = FakeConnection(FakeResponse(302, location="https://evil.example/actions-results/unit?sig=UNIT_PRIVATE_QUERY"))
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(subject, "HTTPSConnection", return_value=api) as connection:
            record: JsonObject = {"id": 400, "size": 5, "digest": "sha256:" + "0" * 64}
            with self.assertRaises(subject.SigningInputError) as caught:
                subject.download_body(record, "UNIT_TOKEN", Path(temp) / "body.zip")
        self.assertEqual(connection.call_count, 1)
        self.assertNotIn("UNIT_PRIVATE_QUERY", str(caught.exception))
        self.assertNotIn("UNIT_TOKEN", str(caught.exception))

    def test_complete_transfer_digest_mismatch_and_excess_body_fail(self) -> None:
        for body in (b"12345", b"abcdef"):
            api = FakeConnection(FakeResponse(302, location="https://productionresultssa0.blob.core.windows.net/actions-results/unit?sig=unit"))
            storage = FakeConnection(FakeResponse(200, body=body))
            record: JsonObject = {"id": 400, "size": 5, "digest": "sha256:" + hashlib.sha256(b"abcde").hexdigest()}
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temp, mock.patch.object(subject, "HTTPSConnection", side_effect=[api, storage]), self.assertRaises(subject.SigningInputError):
                subject.download_body(record, "UNIT_TOKEN", Path(temp) / "body.zip")
            self.assertTrue(storage.closed)

    def test_storage_timeout_preserves_partial_body_and_closes_both_connections(self) -> None:
        api = FakeConnection(FakeResponse(302, location="https://productionresultssa0.blob.core.windows.net/actions-results/unit?sig=UNIT_PRIVATE_QUERY"))
        storage = FakeConnection(FakeResponse(200))
        record: JsonObject = {"id": 400, "size": 5, "digest": "sha256:" + hashlib.sha256(b"abcde").hexdigest()}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(subject, "HTTPSConnection", side_effect=[api, storage]), mock.patch.object(storage.response, "read1", side_effect=[b"abc", TimeoutError("UNIT_PRIVATE_QUERY")]):
            destination = Path(temp) / "partial.zip"
            with self.assertRaises(TimeoutError):
                subject.download_body(record, "UNIT_TOKEN", destination)
            self.assertEqual(destination.read_bytes(), b"abc")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertTrue(api.closed)
        self.assertTrue(storage.closed)

    @unittest.skipUnless(os.name == "posix", "native macOS private acquisition uses POSIX ownership/modes")
    def test_outer_namespace_requires_two_flat_regular_members_before_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "outer.zip"
            regular_zip(path, {"GM2Godot-macos-arm64.zip": b"zip", "GM2Godot-macos-arm64.dmg": b"dmg"})
            first, second = subject.extract_payload(path, root / "valid", "arm64")
            self.assertEqual(stat.S_IMODE((root / "valid").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
            self.assertEqual(first.read_bytes(), b"zip")
            self.assertEqual(second.read_bytes(), b"dmg")
            regular_zip(path, {"GM2Godot-macos-arm64.zip": b"zip", "../outside.dmg": b"dmg"})
            with self.assertRaisesRegex(subject.SigningInputError, "namespace"):
                subject.extract_payload(path, root / "rejected", "arm64")
            self.assertFalse((root / "outside.dmg").exists())
            self.assertEqual(list((root / "rejected").iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "native macOS private acquisition uses POSIX ownership/modes")
    def test_outer_link_and_duplicate_names_are_rejected(self) -> None:
        for mode in ("link", "duplicate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "outer.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    for index in range(2):
                        name = "GM2Godot-macos-arm64.zip" if index == 0 or mode == "duplicate" else "GM2Godot-macos-arm64.dmg"
                        info = zipfile.ZipInfo(name)
                        info.create_system = 3
                        info.external_attr = ((stat.S_IFLNK if index == 1 else stat.S_IFREG) | 0o644) << 16
                        if mode == "duplicate" and index == 1:
                            with self.assertWarnsRegex(UserWarning, "Duplicate name"):
                                archive.writestr(info, b"body")
                        else:
                            archive.writestr(info, b"body")
                with self.assertRaises(subject.SigningInputError):
                    subject.extract_payload(path, Path(temp) / "extracted", "arm64")

    def test_native_original_proof_requires_exact_selectors_and_zero_skips(self) -> None:
        runtime: JsonObject = {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin", "system": "Darwin", "machine": "arm64", "translated": False}
        selected: JsonArray = [f"__main__.NativeLifecycleTests.{name}" for name in subject.NATIVE_METHODS]
        native: JsonObject = {"schema_version": 1, "successful": True, "tests_run": 7, "skips": 0, "failures": 0, "errors": 0, "expected_failures": 0, "unexpected_successes": 0, "selected": selected, "started": selected, "completed": selected, "runtime": runtime}
        policy: JsonObject = {"version": "unit-version"}
        with tempfile.TemporaryDirectory() as temp, mock.patch("scripts.verify_macos_bundle_metadata.load_source_policy", return_value=policy):
            root = Path(temp)
            unsigned = root / "unsigned.zip"
            unsigned.write_bytes(b"unsigned original")
            gui: JsonObject = {"schema_version": 1, "successful": True, "runtime": runtime, "zip_sha256": hashlib.sha256(unsigned.read_bytes()).hexdigest(), "source_policy": policy}
            path = root / "proof.zip"
            for skips in (0, 1, False):
                native["skips"] = skips
                regular_zip(path, {f"release-macos-arm64-{kind}.json": json.dumps(value).encode() for kind, value in [("bootstrap", {}), ("dependencies", {}), ("native-tests", native), ("gui", gui)]})
                with self.subTest(skips=skips):
                    if type(skips) is int and skips == 0:
                        self.assertEqual(subject.verify_original_proof(path, unsigned, "arm64", root)["native_lifecycle"], native)
                    else:
                        with self.assertRaises(subject.SigningInputError):
                            subject.verify_original_proof(path, unsigned, "arm64", root)

    @unittest.skipUnless(os.name == "posix", "native macOS receipts use POSIX ownership/modes")
    def test_fresh_prechecks_match_source_runtime_counts_and_private_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / "constraints").mkdir()
            lock = source / "constraints/requirements-macos-py312.lock"
            lock.write_text("pip==26.0\n", encoding="utf-8")
            bootstrap_source = source / "requirements-bootstrap.txt"
            bootstrap_source.write_text("pip==26.0\npip-tools==7.5.2\n", encoding="utf-8")
            lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
            pins: JsonObject = {"pip": "26.0", "pip-tools": "7.5.2"}
            source_row: JsonObject = {"sha256": hashlib.sha256(bootstrap_source.read_bytes()).hexdigest(), "pins": pins}
            constraints: JsonArray = [{"sha256": lock_sha}]
            transition: JsonObject = {"active": False, "from": pins, "to": pins}
            projection: JsonObject = {"policy": "stable", "state": "stable", "source": source_row, "constraints": constraints, "source_transition": transition}
            bootstrap: JsonObject = {"schema_version": 1, "status": "verified", "errors": [], **projection}
            runtime: JsonObject = {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin", "system": "Darwin", "machine": "arm64", "translated": False}
            selected: JsonArray = [f"__main__.NativeLifecycleTests.{name}" for name in subject.NATIVE_METHODS]
            native: JsonObject = {"schema_version": 1, "successful": True, "tests_run": 7, "skips": 0, "failures": 0, "errors": 0, "expected_failures": 0, "unexpected_successes": 0, "selected": selected, "started": selected, "completed": selected, "runtime": runtime}
            expected: JsonObject = {"implementation_name": "cpython", "python_full_version": "3.12.10", "python_version": "3.12", "sys_platform": "darwin", "platform_machine": "arm64", "pip_version": "26.0"}
            observed: JsonObject = dict(expected)
            observation: JsonObject = {"environment": observed, "pip_version": "26.0", "pip_check": {"returncode": 0}, "pip_inspect": {"returncode": 0}}
            dependency: JsonObject = {"schema_version": 2, "status": "verified", "errors": [], "mode": "subset", "required": ["markdown2", "pillow", "pip", "pyinstaller", "pyside6", "requests"], "bootstrap": projection, "constraint": {"sha256": lock_sha}, "expected_environment": expected, "observation": observation}
            paths = (source / "native.json", source / "dependencies.json", source / "bootstrap.json")
            for path, value in zip(paths, (native, dependency, bootstrap), strict=True):
                subject.write_json(path, value)
            result = subject.verify_prechecks(paths[0], paths[1], paths[2], "arm64", source)
            seals = result["fresh_verified_precheck_seals"]
            self.assertIsInstance(seals, list)
            if not isinstance(seals, list):
                self.fail("fresh receipt seals unavailable")
            self.assertEqual(len(seals), 3)
            self.assertEqual(subject.object_value(seals[0], "native seal")["sha256"], hashlib.sha256(paths[0].read_bytes()).hexdigest())
            for changed in ("skip", "bootstrap-source", "dependency-constraint", "runtime"):
                values = copy.deepcopy([native, dependency, bootstrap])
                if changed == "skip":
                    values[0]["skips"] = 1
                elif changed == "bootstrap-source":
                    subject.object_value(values[2]["source"], "source")["sha256"] = "0" * 64
                elif changed == "dependency-constraint":
                    subject.object_value(values[1]["constraint"], "constraint")["sha256"] = "0" * 64
                else:
                    subject.object_value(values[1]["expected_environment"], "expected")["platform_machine"] = "x86_64"
                for path, value in zip(paths, values, strict=True):
                    path.unlink()
                    subject.write_json(path, value)
                with self.subTest(changed=changed), self.assertRaises(subject.SigningInputError):
                    subject.verify_prechecks(paths[0], paths[1], paths[2], "arm64", source)

    def test_verified_input_context_is_not_emitted_after_metadata_drift(self) -> None:
        trusted, responses = fixture()
        saved = subject.selection(FakeApi(responses), trusted)
        responses[f"{subject.API_ROOT}/runs/200"]["run_attempt"] = 3
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(subject.SigningInputError):
                subject.verify_inputs(FakeApi(responses), trusted, saved, root / "payload.zip", root / "proof.zip", root / "inputs", root)
            self.assertFalse((root / "inputs").exists())

    def test_file_digest_keeps_ordinary_source_and_empty_file_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.py"
            for body in (b"ordinary source control\n", b""):
                path.write_bytes(body)
                for mode in (0o644, 0o755):
                    path.chmod(mode)
                    with self.subTest(body=body, mode=mode):
                        self.assertEqual(subject.file_digest(path, 1024), (len(body), hashlib.sha256(body).hexdigest()))

    @unittest.skipUnless(os.name == "posix", "descriptor replacement uses POSIX nofollow and inode/ctime semantics")
    def test_file_digest_rejects_symlink_and_restored_content_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "body"
            path.write_bytes(b"original")
            link = Path(temp) / "link"
            link.symlink_to(path)
            with self.assertRaises((OSError, subject.SigningInputError)):
                subject.file_digest(link, 1024)
            before = path.stat()
            original_digest = subject.stream_digest

            def rewritten(stream: BinaryIO, cap: int) -> tuple[int, str]:
                result = original_digest(stream, cap)
                path.write_bytes(b"replaced")
                path.write_bytes(b"original")
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                return result

            with mock.patch.object(subject, "stream_digest", side_effect=rewritten), self.assertRaisesRegex(subject.SigningInputError, "changed"):
                subject.file_digest(path, 1024)

    @unittest.skipUnless(os.name == "posix", "archive replacement uses POSIX descriptor and rename semantics")
    def test_verified_payload_cannot_extract_valid_replacement_then_restore_selected_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trusted, responses, policy, _ = archive_fixture(root)
            saved = subject.selection(FakeApi(responses), trusted)
            replacement = root / "replacement.zip"
            regular_zip(replacement, {"GM2Godot-macos-arm64.zip": b"original ZIP", "GM2Godot-macos-arm64.dmg": b"replaced DMG"})
            swap = ArchiveReplacement(root / "payload.zip", replacement, 1)
            with mock.patch("scripts.verify_macos_bundle_metadata.load_source_policy", return_value=policy):
                _, valid_dmg = subject.extract_payload(replacement, root / "valid-replacement", "arm64")
                self.assertEqual(valid_dmg.read_bytes(), b"replaced DMG")
                _, stable = subject.verify_inputs(FakeApi(responses), trusted, saved, root / "payload.zip", root / "proof.zip", root / "stable", root)
                self.assertEqual(stable["unsigned_dmg_sha256"], hashlib.sha256(b"original DMG").hexdigest())
                with mock.patch.object(subject.zipfile, "ZipFile", side_effect=swap.open):
                    try:
                        _, receipt = subject.verify_inputs(FakeApi(responses), trusted, saved, root / "payload.zip", root / "proof.zip", root / "raced", root)
                    except subject.SigningInputError as error:
                        self.assertRegex(str(error), "changed")
                    else:
                        self.assertEqual(receipt["unsigned_dmg_sha256"], hashlib.sha256(b"original DMG").hexdigest())
            self.assertEqual((root / "raced/GM2Godot-macos-arm64.zip").read_bytes(), b"original ZIP")
            self.assertEqual((root / "raced/GM2Godot-macos-arm64.dmg").read_bytes(), b"original DMG")
            subject.verify_archive(root / "payload.zip", subject.object_value(subject.object_value(saved["context"], "context")["unsigned_artifact"], "unsigned"))

    @unittest.skipUnless(os.name == "posix", "archive replacement uses POSIX descriptor and rename semantics")
    def test_verified_proof_cannot_parse_valid_replacement_then_restore_selected_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trusted, responses, policy, entries = archive_fixture(root)
            saved = subject.selection(FakeApi(responses), trusted)
            replacement = root / "replacement.zip"
            regular_zip(replacement, proof_entries(b"original ZIP", policy, "B"))
            swap = ArchiveReplacement(root / "proof.zip", replacement, 2)
            with mock.patch("scripts.verify_macos_bundle_metadata.load_source_policy", return_value=policy):
                _, stable = subject.verify_inputs(FakeApi(responses), trusted, saved, root / "payload.zip", root / "proof.zip", root / "stable", root)
                self.assertEqual(subject.object_value(subject.object_value(stable["input_proof"], "proof")["unsigned_gui"], "GUI")["proof_variant"], "A")
                valid_proof = subject.verify_original_proof(replacement, root / "stable/GM2Godot-macos-arm64.zip", "arm64", root)
                self.assertEqual(subject.object_value(valid_proof["unsigned_gui"], "GUI")["proof_variant"], "B")
                with mock.patch.object(subject.zipfile, "ZipFile", side_effect=swap.open), mock.patch.object(subject, "parse_api_json", wraps=subject.parse_api_json) as parser:
                    try:
                        _, receipt = subject.verify_inputs(FakeApi(responses), trusted, saved, root / "payload.zip", root / "proof.zip", root / "raced", root)
                    except subject.SigningInputError as error:
                        self.assertRegex(str(error), "changed")
                    else:
                        self.assertEqual(subject.object_value(subject.object_value(receipt["input_proof"], "proof")["unsigned_gui"], "GUI")["proof_variant"], "A")
                self.assertEqual(parser.call_args_list, [mock.call(entries["release-macos-arm64-native-tests.json"]), mock.call(entries["release-macos-arm64-gui.json"])])
            subject.verify_archive(root / "proof.zip", subject.object_value(subject.object_value(saved["context"], "context")["proof_artifact"], "proof"))


if __name__ == "__main__":
    unittest.main()
