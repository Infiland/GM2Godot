"""Conditional acquisition fixtures: no mock is genuine Apple/native proof."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
import zipfile
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from scripts import acquire_macos_publication_inputs as acquisition, acquire_macos_signing_inputs as original_inputs
from src.conversion.json_values import JsonObject, JsonValue

SHA = "a" * 40
TREE = "b" * 40


def _job(identifier: int, name: str, attempt: int = 1, *, signing: bool = False) -> JsonObject:
    names = (
        "Recheck same-run inputs before secret access", "Sign notarize staple and test publication bytes",
        "Upload eligible signed macOS payloads", "Upload eligible signing receipts",
    ) if signing else (
        "Verify native macOS build runtime", "Install and verify dependencies", "Verify native macOS GUI lifecycle tests",
        "Verify packaged macOS GUI", "Upload macOS artifacts", "Upload macOS build proof",
    )
    steps: list[JsonValue] = [{"name": name, "status": "completed", "conclusion": "success"} for name in names]
    return {"id": identifier, "name": name, "run_id": 17, "run_attempt": attempt, "head_sha": SHA,
            "head_branch": "main", "workflow_name": "Build and Release",
            "run_url": f"https://api.github.com{acquisition.API_ROOT}/runs/17",
            "started_at": "2026-10-05T00:00:00Z", "completed_at": "2026-10-05T00:10:00Z",
            "status": "completed", "conclusion": "success", "steps": steps}


def _artifact(identifier: int, name: str, body: bytes = b"body") -> JsonObject:
    return {"id": identifier, "name": name, "expired": False, "size_in_bytes": len(body),
            "digest": f"sha256:{hashlib.sha256(body).hexdigest()}", "created_at": "2026-10-05T00:05:00Z",
            "workflow_run": {"id": 17, "head_sha": SHA, "head_branch": "main"}}


class _Api:
    def __init__(self, event: str = "push") -> None:
        self.run: JsonObject = {"id": 17, "run_attempt": 2, "head_sha": SHA, "event": event, "head_branch": "main",
                               "path": acquisition.BUILD_PATH, "workflow_id": 101, "status": "in_progress",
                               "conclusion": None, "repository": {"full_name": acquisition.REPOSITORY}}
        self.jobs = [
            _job(1, "get-version"), _job(2, "release-state-preflight"), _job(3, "main-quality"),
            _job(4, "build (windows-latest, windows, x64, 3.12.10)"),
            _job(5, "build (ubuntu-latest, linux, x64, 3.12.10)"),
            _job(6, "build (macos-26, macos-arm64, arm64, 3.12.10)"),
            _job(7, "build (macos-26-intel, macos-x86_64, x64, 3.12.10)"),
            _job(8, "macos-sign (macos-26, macos-arm64, arm64, 3.12.10)", 2, signing=True),
            _job(9, "macos-sign (macos-26-intel, macos-x86_64, x64, 3.12.10)", 2, signing=True),
        ]
        self.artifacts = [
            _artifact(20, "GM2Godot-windows"), _artifact(21, "GM2Godot-linux"),
            _artifact(22, "GM2Godot-macos-arm64"), _artifact(23, "GM2Godot-macos-arm64-proof-17-1"),
            _artifact(24, "GM2Godot-macos-x86_64"), _artifact(25, "GM2Godot-macos-x86_64-proof-17-1"),
            _artifact(26, "GM2Godot-macos-arm64-signed"), _artifact(27, "GM2Godot-macos-arm64-signing-proof-17-2"),
            _artifact(28, "GM2Godot-macos-x86_64-signed"), _artifact(29, "GM2Godot-macos-x86_64-signing-proof-17-2"),
        ]
        self.calls: list[str] = []
        self.foreign_artifact = False

    def get(self, path: str) -> JsonObject:
        self.calls.append(path)
        if path == f"{acquisition.API_ROOT}/workflows/release.yml":
            return {"id": 101, "path": acquisition.BUILD_PATH, "state": "active"}
        if path in (f"{acquisition.API_ROOT}/runs/17", f"{acquisition.API_ROOT}/runs/17/attempts/2"):
            return dict(self.run)
        if path.startswith(f"{acquisition.API_ROOT}/runs/17/jobs?filter=all&"):
            rows: list[JsonValue] = [dict(job) for job in self.jobs]
            return {"total_count": len(rows), "jobs": rows}
        if path.startswith(f"{acquisition.API_ROOT}/runs/17/artifacts?"):
            rows = [dict(artifact) for artifact in self.artifacts]
            return {"total_count": len(rows), "artifacts": rows}
        for artifact in self.artifacts:
            if path == f"{acquisition.API_ROOT}/artifacts/{artifact['id']}":
                result = dict(artifact)
                if self.foreign_artifact:
                    result["size_in_bytes"] = 999
                return result
        raise AssertionError(f"unexpected bounded endpoint: {path}")


def _trusted(event: str = "push") -> JsonObject:
    return {"repository": acquisition.REPOSITORY, "source_sha": SHA, "event": event, "run_id": 17, "run_attempt": 2}


def _guard() -> JsonObject:
    return {"head": SHA, "tree": TREE, "physical_root": [1, 2, 3], "files": []}


def _zip(path: Path, contents: dict[str, bytes], *, extra: bytes = b"", mode: int = stat.S_IFREG | 0o644) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in contents.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.extra = extra
            archive.writestr(info, body)
    path.chmod(0o600)
    return path.read_bytes()


def _original_proof_entries(unsigned: bytes, policy: JsonObject, variant: str) -> dict[str, bytes]:
    runtime: JsonObject = {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin", "system": "Darwin", "machine": "arm64", "translated": False}
    selected: list[JsonValue] = [f"__main__.NativeLifecycleTests.{name}" for name in original_inputs.NATIVE_METHODS]
    native: JsonObject = {"schema_version": 1, "successful": True, "tests_run": 7, "skips": 0, "failures": 0, "errors": 0, "expected_failures": 0, "unexpected_successes": 0, "selected": selected, "started": selected, "completed": selected, "runtime": runtime}
    gui: JsonObject = {"schema_version": 1, "successful": True, "runtime": runtime, "zip_sha256": hashlib.sha256(unsigned).hexdigest(), "source_policy": policy, "proof_variant": variant}
    return {f"release-macos-arm64-{kind}.json": json.dumps(value).encode() for kind, value in [("bootstrap", {}), ("dependencies", {}), ("native-tests", native), ("gui", gui)]}


class PublicationInputTests(unittest.TestCase):
    def test_in_progress_push_and_dispatch_preserve_actual_unsigned_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary).resolve()
            for event in ("push", "workflow_dispatch"):
                with self.subTest(event=event), patch.object(acquisition, "source_guard", return_value=_guard()):
                    api = _Api(event)
                    saved = acquisition.make_selection(api, source, _trusted(event), "signing", "arm64")
                    acquisition.validate_selection(saved, _trusted(event), "signing", "arm64")
                    context = acquisition.context(saved, "arm64")
                    producer = acquisition.object_value(context["producer"], "producer")
                    signing = acquisition.object_value(context["signing"], "signing")
                    original = acquisition.object_value(context["unsigned_artifact"], "unsigned")
                    proof = acquisition.object_value(context["proof_artifact"], "proof")
                    self.assertEqual(producer["event"], event)
                    self.assertEqual(signing["event"], event)
                    self.assertEqual(producer["run_attempt"], 2)
                    self.assertEqual(signing["run_attempt"], 2)
                    self.assertEqual(original["producer_run_attempt"], 1)
                    self.assertEqual(proof["producer_run_attempt"], 1)
                    self.assertEqual(context["purpose"], "publication")
                    self.assertIs(context["release_eligible"], True)
                    self.assertNotIn("/workflows/101/runs", "\n".join(api.calls))

    def test_source_attempt_roles_and_provider_drift_reject_without_old_run_fallback(self) -> None:
        mutations: tuple[tuple[str, JsonValue], ...] = (
            ("head_sha", "c" * 40), ("head_branch", "other"), ("event", "pull_request"),
            ("run_attempt", 1), ("path", ".github/workflows/tests.yml"),
            ("repository", {"full_name": "other/repo"}), ("status", "queued"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                api = _Api()
                api.run[field] = value
                with self.assertRaises(acquisition.SigningInputError):
                    acquisition.snapshot(api, _trusted(), "signing", "arm64")
        api = _Api()
        api.jobs[2]["conclusion"] = "failure"
        with self.assertRaisesRegex(acquisition.SigningInputError, "unsuccessful Build role"):
            acquisition.snapshot(api, _trusted(), "signing", "arm64")
        api = _Api()
        api.jobs.append(dict(api.jobs[6]))
        api.jobs[-1]["id"] = 99
        with self.assertRaisesRegex(acquisition.SigningInputError, "ambiguous job execution"):
            acquisition.snapshot(api, _trusted(), "signing", "arm64")
        api = _Api()
        api.jobs[8]["run_attempt"] = 1
        with self.assertRaisesRegex(acquisition.SigningInputError, "current common attempt"):
            acquisition.snapshot(api, _trusted(), "publisher", None)
        api = _Api()
        api.foreign_artifact = True
        with self.assertRaisesRegex(acquisition.SigningInputError, "metadata drift"):
            acquisition.snapshot(api, _trusted(), "signing", "arm64")
        with tempfile.TemporaryDirectory() as temporary, patch.object(acquisition, "source_guard", return_value=_guard()):
            api = _Api()
            saved = acquisition.make_selection(api, Path(temporary).resolve(), _trusted(), "signing", "arm64")
            api.run["run_attempt"] = 3
            with self.assertRaises(acquisition.SigningInputError):
                acquisition.recheck(api, saved)

    @unittest.skipUnless(os.name == "posix", "owned acquisition descriptor fixtures require POSIX ownership and dir_fd")
    def test_full_archive_body_flat_namespace_and_local_metadata_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            pair = {"GM2Godot-macos-arm64.zip": b"zip payload", "GM2Godot-macos-arm64.dmg": b"dmg payload"}
            path = root / "GM2Godot-macos-arm64.zip"
            body = _zip(path, pair)
            artifact: JsonObject = {"name": "GM2Godot-macos-arm64", "size": len(body),
                                    "digest": f"sha256:{hashlib.sha256(body).hexdigest()}"}
            actual, selected = acquisition.downloaded(root, artifact, (root,))
            self.assertEqual(actual, path)
            rows = acquisition.inspect_members(path, {name: 1024 for name in pair}, (root,), selected=selected)
            self.assertEqual({acquisition.text(acquisition.object_value(row, "member")["name"], "name") for row in rows}, set(pair))
            artifact["digest"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(acquisition.SigningInputError, "full body"):
                acquisition.downloaded(root, artifact, (root,))
            for label, contents, extra, mode in (
                ("path escape", {"../GM2Godot-macos-arm64.zip": b"x"}, b"", stat.S_IFREG | 0o644),
                ("extra field", pair, b"\x01\x00\x00\x00", stat.S_IFREG | 0o644),
                ("symlink", pair, b"", stat.S_IFLNK | 0o777),
                ("unexpected member", {**pair, "extra.py": b"print('bad')"}, b"", stat.S_IFREG | 0o644),
            ):
                with self.subTest(label=label):
                    _zip(path, contents, extra=extra, mode=mode)
                    with self.assertRaises(acquisition.SigningInputError):
                        acquisition.inspect_members(path, {name: 1024 for name in pair}, (root,),
                                                   selected=acquisition.file_seal(path, 1024 * 1024, (root,))[0])
            raw = bytearray(_zip(path, pair))
            raw[14] ^= 1  # Local CRC only; central metadata and bodies remain intact.
            path.write_bytes(raw)
            with self.assertRaisesRegex(acquisition.SigningInputError, "CRC or size"):
                acquisition.inspect_members(path, {name: 1024 for name in pair}, (root,),
                                            selected=acquisition.file_seal(path, 1024 * 1024, (root,))[0])
            target = root / "normalized.zip"
            _zip(path, pair)
            old_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            acquisition.normalize_archive(path, target, (root,))
            self.assertFalse(path.exists())
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), old_hash)
            path.write_bytes(b"new")
            with self.assertRaisesRegex(acquisition.SigningInputError, "already exists"):
                acquisition.normalize_archive(path, target, (root,))
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), old_hash)

            # Both ZIPs have the accepted namespace and size; only their bytes differ.
            # Replace A with B solely for the parser's real descriptor open, then
            # restore A before parsing. Every pathname seal still observes real A.
            download = root / "swap-download"
            download.mkdir()
            selected_path = download / "GM2Godot-macos-arm64.zip"
            replacement = root / "unselected-B.zip"
            parked = root / "selected-A.saved.zip"
            destination = root / "swap-rejected"
            destination.mkdir(mode=0o700)
            members_a = {"GM2Godot-macos-arm64.zip": b"A ZIP bytes", "GM2Godot-macos-arm64.dmg": b"A DMG bytes"}
            members_b = {name: value.replace(b"A", b"B") for name, value in members_a.items()}
            bytes_a, bytes_b = _zip(selected_path, members_a), _zip(replacement, members_b)
            self.assertEqual(len(bytes_a), len(bytes_b))
            self.assertNotEqual(hashlib.sha256(bytes_a).hexdigest(), hashlib.sha256(bytes_b).hexdigest())
            for archive_path, wanted in ((selected_path, members_a), (replacement, members_b)):
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual({name: archive.read(name) for name in archive.namelist()}, wanted)
            selected_artifact: JsonObject = {"name": "GM2Godot-macos-arm64", "size": len(bytes_a),
                                            "digest": f"sha256:{hashlib.sha256(bytes_a).hexdigest()}"}
            _selected_path, selected_seal = acquisition.downloaded(download, selected_artifact, (root,))
            real_seal, real_open = acquisition.file_seal, os.open
            sealing_path = False
            swaps = 0

            def unchanged_path_seal(sealed_path: Path, cap: int, roots: Sequence[Path], *,
                                    body: bool = False, empty: bool = False) -> tuple[JsonObject, bytes]:
                nonlocal sealing_path
                sealing_path = True
                try:
                    return real_seal(sealed_path, cap, roots, body=body, empty=empty)
                finally:
                    sealing_path = False

            def swapping_open(opened_path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
                nonlocal swaps
                if (not sealing_path and opened_path == selected_path.name
                        and flags == os.O_RDONLY | os.O_NOFOLLOW and dir_fd is not None):
                    selected_path.replace(parked)
                    replacement.replace(selected_path)
                    try:
                        descriptor = real_open(opened_path, flags, mode, dir_fd=dir_fd)
                    finally:
                        selected_path.replace(replacement)
                        parked.replace(selected_path)
                    swaps += 1
                    return descriptor
                return real_open(opened_path, flags, mode, dir_fd=dir_fd)

            with patch.object(acquisition, "file_seal", side_effect=unchanged_path_seal), \
                 patch.object(os, "open", side_effect=swapping_open), \
                 self.assertRaisesRegex(acquisition.SigningInputError, "descriptor|full body"):
                acquisition.inspect_members(selected_path, {name: 1024 for name in members_a}, (root,), destination,
                                            selected=selected_seal)
            self.assertEqual(swaps, 1)
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(selected_path.read_bytes(), bytes_a)
            self.assertEqual(replacement.read_bytes(), bytes_b)
            self.assertFalse(parked.exists())

    @unittest.skipUnless(os.name == "posix", "owned acquisition descriptor fixtures require POSIX ownership and dir_fd")
    def test_source_bytes_index_modes_empty_files_and_exact_owned_data_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            tracked = root / "__init__.py"
            tracked.write_bytes(b"")
            tracked.chmod(0o644)
            blob = hashlib.sha1(b"blob 0\0").hexdigest()
            untracked: list[str] = []
            def git(_source: Path, arguments: tuple[str, ...]) -> bytes:
                if arguments == ("rev-parse", "HEAD"):
                    return (SHA + "\n").encode()
                if arguments == ("rev-parse", "HEAD^{tree}"):
                    return (TREE + "\n").encode()
                if arguments == ("ls-tree", "-rz", "--full-tree", "HEAD"):
                    return f"100644 blob {blob}\t__init__.py\0".encode()
                if arguments == ("ls-files", "--stage", "-z"):
                    return f"100644 {blob} 0\t__init__.py\0".encode()
                self.assertEqual(arguments, ("ls-files", "--others", "-z"))
                return b"".join(name.encode() + b"\0" for name in untracked)
            with patch.object(acquisition, "git_bytes", side_effect=git):
                clean = acquisition.source_guard(root, {})
                tracked.write_bytes(b"changed")
                with self.assertRaisesRegex(acquisition.SigningInputError, "immutable HEAD"):
                    acquisition.source_guard(root, {})
                tracked.write_bytes(b"")
                tracked.chmod(0o755)
                with self.assertRaisesRegex(acquisition.SigningInputError, "mode"):
                    acquisition.source_guard(root, {})
                tracked.chmod(0o644)
                raw = root / "raw-artifacts"
                raw.mkdir()
                payload = raw / "one.zip"
                payload.write_bytes(b"owned archive")
                payload.chmod(0o600)
                seal, _body = acquisition.file_seal(payload, 1024, (root,))
                untracked.append("raw-artifacts/one.zip")
                allowed = acquisition.allowed_data(root, {payload: seal})
                self.assertEqual(acquisition.source_guard(root, allowed), clean)
                for unrelated in ("raw-artifacts/extra.py", "__pycache__/ignored.pyc"):
                    untracked.append(unrelated)
                    with self.assertRaisesRegex(acquisition.SigningInputError, "unrelated untracked"):
                        acquisition.source_guard(root, allowed)
                    untracked.pop()
                payload.write_bytes(b"changed body")
                with self.assertRaises(acquisition.SigningInputError):
                    acquisition.source_guard(root, allowed)
                script = root / "raw-artifacts/extra.py"
                script.write_bytes(b"script")
                script.chmod(0o600)
                script_seal, _body = acquisition.file_seal(script, 1024, (root,))
                with self.assertRaisesRegex(acquisition.SigningInputError, "nonimportable"):
                    acquisition.allowed_data(root, {script: script_seal})
            link = root / "link.zip"
            link.symlink_to(payload)
            with self.assertRaises(OSError):
                acquisition.file_seal(link, 1024, (root,))

    @unittest.skipUnless(os.name == "posix", "owned acquisition descriptor fixtures require POSIX ownership and dir_fd")
    def test_actual_original_pair_calls_unchanged_semantic_validators_before_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            runner = root / "runner-temp"
            runner.mkdir()
            payload_dir, proof_dir = runner / "payload", runner / "proof"
            payload_dir.mkdir()
            proof_dir.mkdir()
            payload = payload_dir / "GM2Godot-macos-arm64.zip"
            payload_body = _zip(payload, {"GM2Godot-macos-arm64.zip": b"unsigned zip", "GM2Godot-macos-arm64.dmg": b"unsigned dmg"})
            proof = proof_dir / "GM2Godot-macos-arm64-proof-17-1.zip"
            proof_body = _zip(proof, {f"release-macos-arm64-{kind}.json": b'{}' for kind in ("bootstrap", "dependencies", "native-tests", "gui")})
            api = _Api()
            api.artifacts[2] = _artifact(22, "GM2Godot-macos-arm64", payload_body)
            api.artifacts[3] = _artifact(23, "GM2Godot-macos-arm64-proof-17-1", proof_body)
            with patch.object(acquisition, "source_guard", return_value=_guard()), \
                 patch.object(acquisition, "verify_original_proof", return_value={"mock_native_GUI": True}) as native, \
                 patch.object(acquisition, "verify_prechecks", return_value={"mock_original_dependencies": True}) as dependencies:
                saved = acquisition.make_selection(api, source, _trusted(), "signing", "arm64")
                inputs = runner / "inputs"
                context, receipt = acquisition.verify_signing(api, saved, source, payload_dir, proof_dir, inputs, (source, runner))
                native.assert_called_once_with(proof, inputs / "GM2Godot-macos-arm64.zip", "arm64", source,
                                               record=acquisition.record(saved, "proof"))
                dependencies.assert_called_once_with(runner / "inputs-original-proof/release-macos-arm64-native-tests.json",
                    runner / "inputs-original-proof/release-macos-arm64-dependencies.json",
                    runner / "inputs-original-proof/release-macos-arm64-bootstrap.json", "arm64", source)
                self.assertEqual((inputs / "GM2Godot-macos-arm64.zip").read_bytes(), b"unsigned zip")
                self.assertEqual((inputs / "GM2Godot-macos-arm64.dmg").read_bytes(), b"unsigned dmg")
                self.assertEqual(context["signing"], {"run_id": 17, "run_attempt": 2, "event": "push", "branch": "main", "head_sha": SHA})
                self.assertIs(receipt["successful"], True)
                # This fixture tests calls/bytes, never authentic native/provider success.
                with self.assertRaisesRegex(acquisition.SigningInputError, "outside source"):
                    acquisition.signing_layout(source, runner, (source / "payload", runner / "proof"))
                (source / "runner-temp").mkdir()
                with self.assertRaisesRegex(acquisition.SigningInputError, "separate"):
                    acquisition.signing_layout(source, source / "runner-temp", (source / "runner-temp/selection.json",))
                with self.assertRaisesRegex(acquisition.SigningInputError, "distinct"):
                    acquisition.signing_layout(source, runner, (runner / "one", runner / "one"))

    @unittest.skipUnless(os.name == "posix", "owned acquisition descriptor fixtures require POSIX ownership and dir_fd")
    def test_lower_proof_reread_keeps_api_selected_digest_across_valid_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, runner = root / "source", root / "runner-temp"
            source.mkdir()
            runner.mkdir()
            payload_dir, proof_dir = runner / "payload", runner / "proof"
            payload_dir.mkdir()
            proof_dir.mkdir()
            payload = payload_dir / "GM2Godot-macos-arm64.zip"
            payload_body = _zip(payload, {"GM2Godot-macos-arm64.zip": b"unsigned zip", "GM2Godot-macos-arm64.dmg": b"unsigned dmg"})
            policy: JsonObject = {"version": "unit-version"}
            proof = proof_dir / "GM2Godot-macos-arm64-proof-17-1.zip"
            replacement, parked = runner / "unselected-proof-B.zip", proof_dir / "selected-proof-A.held"
            bytes_a = _zip(proof, _original_proof_entries(b"unsigned zip", policy, "A"))
            bytes_b = _zip(replacement, _original_proof_entries(b"unsigned zip", policy, "B"))
            self.assertEqual(len(bytes_a), len(bytes_b))
            self.assertNotEqual(hashlib.sha256(bytes_a).hexdigest(), hashlib.sha256(bytes_b).hexdigest())
            unsigned = runner / "unsigned.zip"
            unsigned.write_bytes(b"unsigned zip")
            real_proof = acquisition.verify_original_proof
            with patch("scripts.verify_macos_bundle_metadata.load_source_policy", return_value=policy):
                for proof_path, variant in ((proof, "A"), (replacement, "B")):
                    evidence = real_proof(proof_path, unsigned, "arm64", source)
                    self.assertEqual(acquisition.object_value(evidence["unsigned_gui"], "GUI")["proof_variant"], variant)

                def replaced_proof(path: Path, unsigned_zip: Path, architecture: str, source_root: Path, *,
                                   record: JsonObject | None = None) -> JsonObject:
                    path.replace(parked)
                    replacement.replace(path)
                    try:
                        return real_proof(path, unsigned_zip, architecture, source_root, record=record)
                    finally:
                        path.replace(replacement)
                        parked.replace(path)

                api = _Api()
                api.artifacts[2] = _artifact(22, "GM2Godot-macos-arm64", payload_body)
                api.artifacts[3] = _artifact(23, "GM2Godot-macos-arm64-proof-17-1", bytes_a)
                with patch.object(acquisition, "source_guard", return_value=_guard()), \
                     patch.object(acquisition, "verify_original_proof", side_effect=replaced_proof) as lower, \
                     patch.object(original_inputs, "parse_api_json", wraps=original_inputs.parse_api_json) as parser, \
                     patch.object(acquisition, "verify_prechecks", return_value={"mock_original_dependencies": True}) as dependencies:
                    saved = acquisition.make_selection(api, source, _trusted(), "signing", "arm64")
                    inputs = runner / "inputs"
                    with self.assertRaisesRegex(acquisition.SigningInputError, "artifact digest mismatch"):
                        acquisition.verify_signing(api, saved, source, payload_dir, proof_dir, inputs, (source, runner))
                    lower.assert_called_once_with(proof, inputs / "GM2Godot-macos-arm64.zip", "arm64", source,
                                                  record=acquisition.record(saved, "proof"))
                    parser.assert_not_called()
                    dependencies.assert_not_called()
            self.assertEqual(proof.read_bytes(), bytes_a)
            self.assertEqual(replacement.read_bytes(), bytes_b)
            self.assertFalse(parked.exists())
            self.assertEqual((runner / "inputs-original-proof/release-macos-arm64-gui.json").read_bytes(),
                             _original_proof_entries(b"unsigned zip", policy, "A")["release-macos-arm64-gui.json"])

    @unittest.skipUnless(os.name == "posix", "owned acquisition descriptor fixtures require POSIX ownership and dir_fd")
    def test_publisher_full_bodies_normalization_and_late_trust_gate_remain_separate(self) -> None:
        for rejected_field in (None, "purpose", "final_payloads"):
            with self.subTest(rejected_field=rejected_field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, runner = root / "source", root / "runner-temp"
                source.mkdir()
                runner.mkdir()
                api = _Api()
                raw, proofs, receipts = runner / "raw-artifacts", runner / "raw-signing-proofs", source / "signing-receipts"
                raw.mkdir()
                proofs.mkdir()
                for platform, index in (("windows", 0), ("linux", 1)):
                    name = f"GM2Godot-{platform}"
                    directory = raw / name
                    directory.mkdir()
                    body = _zip(directory / f"{name}.zip", {f"{name}.zip": platform.encode()})
                    api.artifacts[index] = _artifact(20 + index, name, body)
                for arch, payload_index, proof_index, identifier in (("arm64", 6, 7, 26), ("x86_64", 8, 9, 28)):
                    platform = "macos-arm64" if arch == "arm64" else "macos-x86_64"
                    name = f"GM2Godot-{platform}"
                    payload_dir, proof_dir = raw / name, proofs / arch
                    payload_dir.mkdir()
                    proof_dir.mkdir()
                    contents = {f"{name}.zip": f"signed ZIP {arch}".encode(), f"{name}.dmg": f"signed DMG {arch}".encode()}
                    pair: list[JsonValue] = [{"name": filename, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                                             for filename, body in contents.items()]
                    receipt: JsonObject = {key: {} for key in acquisition.RECEIPT_KEYS}
                    receipt.update(schema_version=1, successful=True, purpose="publication", release_eligible=True,
                                   repository=acquisition.REPOSITORY, source={"sha": SHA, "tree": TREE}, architecture=arch,
                                   producer={"run_id": 17, "run_attempt": 2, "workflow_id": 101, "event": "push", "branch": "main", "head_sha": SHA},
                                   signing={"run_id": 17, "run_attempt": 2, "event": "push", "branch": "main", "head_sha": SHA},
                                   version="0.8.99", final_payloads=pair)
                    if arch == "arm64" and rejected_field == "purpose":
                        receipt["purpose"] = "verification_only"
                        receipt["release_eligible"] = False
                    elif arch == "arm64" and rejected_field == "final_payloads":
                        receipt["final_payloads"] = [{"name": f"{name}.zip", "size": 1, "sha256": "f" * 64}]
                    body = _zip(payload_dir / f"{name}-signed.zip", contents)
                    api.artifacts[payload_index] = _artifact(identifier, f"{name}-signed", body)
                    proof_contents = {filename: b"{}" for filename in acquisition.PROOF_CAPS}
                    proof_contents["signing.json"] = json.dumps(receipt).encode()
                    body = _zip(proof_dir / f"{name}-signing-proof-17-2.zip", proof_contents)
                    api.artifacts[proof_index] = _artifact(identifier + 1, f"{name}-signing-proof-17-2", body)
                def owned_guard(_source: Path, allowed: dict[str, JsonObject]) -> JsonObject:
                    actual = {path.relative_to(source).as_posix(): path for path in source.rglob("*") if path.is_file()}
                    self.assertEqual(set(allowed), set(actual))
                    for name, path in actual.items():
                        body = path.read_bytes()
                        self.assertEqual(allowed[name]["size"], len(body))
                        self.assertEqual(allowed[name]["sha256"], hashlib.sha256(body).hexdigest())
                        self.assertEqual(allowed[name]["mode"], stat.S_IMODE(path.stat().st_mode))
                    return _guard()
                with patch.object(acquisition, "source_guard", side_effect=owned_guard), \
                     patch.object(acquisition, "load_source_policy", return_value={"version": "0.8.99"}):
                    saved = acquisition.make_selection(api, source, _trusted(), "publisher", None)
                    # The actual complete fixture archives arrive after clean planning.
                    shutil.copytree(raw, source / "raw-artifacts")
                    shutil.copytree(proofs, source / "raw-signing-proofs")
                    raw, proofs = source / "raw-artifacts", source / "raw-signing-proofs"
                    if rejected_field is not None:
                        with self.assertRaises(acquisition.SigningInputError):
                            acquisition.verify_publisher(api, saved, source, raw, proofs, receipts, (source, runner))
                        continue
                    context, receipt, files = acquisition.verify_publisher(api, saved, source, raw, proofs, receipts, (source, runner))
                self.assertEqual(len(files), 14)
                self.assertEqual(context["signing"], {"run_id": 17, "run_attempt": 2, "event": "push", "branch": "main", "head_sha": SHA})
                for platform in ("macos-arm64", "macos-x86_64"):
                    normalized = raw / f"GM2Godot-{platform}" / f"GM2Godot-{platform}.zip"
                    self.assertTrue(normalized.is_file())
                    self.assertFalse(normalized.with_name(f"GM2Godot-{platform}-signed.zip").exists())
                self.assertIn("final Developer ID/notary/GUI gate remains mandatory", acquisition.text(receipt["scope"], "scope"))
                # Empty trust observations intentionally pass only transport/context.
                # They are not authentic Apple proof and must fail the separate gate.

    @unittest.skipUnless(os.name == "posix", "owned acquisition descriptor fixtures require POSIX ownership and dir_fd")
    def test_receipt_context_and_public_cli_safe_failure_never_upgrade_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            saved: JsonObject = {"trusted": {**_trusted(), "source_tree": TREE, "workflow_id": 101}}
            path = root / "signing.json"
            pair: list[JsonValue] = [{"name": "GM2Godot-macos-arm64.zip", "size": 1, "sha256": "d" * 64},
                                    {"name": "GM2Godot-macos-arm64.dmg", "size": 2, "sha256": "e" * 64}]
            receipt: JsonObject = {name: {} for name in acquisition.RECEIPT_KEYS}
            receipt.update(schema_version=1, successful=True, purpose="publication", release_eligible=True,
                           repository=acquisition.REPOSITORY, source={"sha": SHA, "tree": TREE}, architecture="arm64",
                           producer={"run_id": 17, "run_attempt": 2, "workflow_id": 101, "event": "push", "branch": "main", "head_sha": SHA},
                           signing={"run_id": 17, "run_attempt": 2, "event": "push", "branch": "main", "head_sha": SHA},
                           version="0.8.99", final_payloads=pair)
            def save(value: JsonObject) -> None:
                path.write_text(json.dumps(value), encoding="utf-8")
                path.chmod(0o600)
            save(receipt)
            with patch.object(acquisition, "load_source_policy", return_value={"version": "0.8.99"}):
                acquisition.signed_receipt(path, saved, source, "arm64", pair, (root,))
                mutations: tuple[tuple[str, JsonValue], ...] = (
                    ("purpose", "verification_only"), ("release_eligible", False), ("architecture", "x86_64"),
                    ("signing", {"run_id": 17, "run_attempt": 1, "event": "push", "branch": "main", "head_sha": SHA}),
                    ("producer", {"run_id": True, "run_attempt": 2, "workflow_id": 101, "event": "push", "branch": "main", "head_sha": SHA}),
                    ("final_payloads", [{"name": "GM2Godot-macos-arm64.zip", "size": 1, "sha256": "f" * 64}]),
                )
                for key, value in mutations:
                    with self.subTest(key=key):
                        changed = dict(receipt)
                        changed[key] = value
                        save(changed)
                        with self.assertRaises(acquisition.SigningInputError):
                            acquisition.signed_receipt(path, saved, source, "arm64", pair, (root,))
            for body in (b'{"a":1,"a":2}', b'{"n":' + b'9' * 5000 + b'}', b'[' * 1100 + b'0' + b']' * 1100):
                with self.assertRaises(acquisition.SigningInputError):
                    acquisition.decode(body)
            error = io.StringIO()
            with patch.dict(os.environ, {"RUNNER_TEMP": str(root)}, clear=True), \
                 patch.object(acquisition, "trusted_context", side_effect=RuntimeError("SECRET_TOKEN_MUST_NOT_PRINT")), \
                 patch("sys.stderr", error):
                code = acquisition.main(["plan-signing", "--source-root", str(source), "--selection", str(root / "selection.json"), "--architecture", "arm64"])
            self.assertEqual(code, 2)
            self.assertEqual(error.getvalue(), "Publication inputs rejected: RuntimeError\n")
            self.assertNotIn("Traceback", error.getvalue())
            self.assertFalse((root / "selection.json").exists())


if __name__ == "__main__":
    unittest.main()
