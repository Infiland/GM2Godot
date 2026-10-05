"""Conditional same-Build acquisition; no verification-only proof can publish.

Requires the separately admitted bootstrap input validators and publication gate.
This module plans and verifies action-downloaded bytes; it never signs or fetches
an artifact body, accesses credentials, or waits for its enclosing Build run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO

from scripts.acquire_macos_signing_inputs import (
    API_ROOT,
    BUILD_PATH,
    MAX_ARCHIVE_BYTES,
    MAX_PROOF_ARCHIVE_BYTES,
    MAX_PROOF_BYTES,
    REPOSITORY,
    SigningInputError,
    artifact_record,
    collection,
    integer,
    latest_jobs,
    native_job,
    object_value,
    require,
    text,
    verify_original_proof,
    verify_prechecks,
)
from scripts.check_main_quality import ApiReader, Budget, GitHubApi, QualityGateError, parse_api_json
from scripts.verify_macos_bundle_metadata import load_source_policy
from scripts.verify_macos_signing_receipts import RECEIPT_KEYS
from src.conversion.json_values import JsonObject, JsonValue

ARCHITECTURES = ("arm64", "x86_64")
MAX_SELECTION_BYTES = 5 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_GIT_BYTES = 5 * 1024 * 1024
MAX_SOURCE_FILES = 10_000
MAX_SIGNED_PROOF_ARCHIVE_BYTES = 80 * 1024 * 1024
PROOF_CAPS = {"signing.json": 1024 * 1024, "app-notary-log.json": 4 * 1024 * 1024,
              "dmg-notary-log.json": 4 * 1024 * 1024, "signed-gui.json": 64 * 1024 * 1024}
LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
SELECTION_KEYS = frozenset({"schema_version", "mode", "trusted", "source_guard", "prerequisites", "artifacts"})
ARTIFACT_KEYS = frozenset({"id", "name", "size", "digest", "producer_run_id", "producer_run_attempt"})


def closed(value: JsonValue, keys: frozenset[str], label: str) -> JsonObject:
    result = object_value(value, label)
    require(frozenset(result) == keys, f"unexpected fields: {label}")
    return result


def unique_pairs(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    value: JsonObject = {}
    for key, member in pairs:
        require(key not in value, "duplicate JSON field")
        value[key] = member
    return value


def decode(body: bytes) -> JsonObject:
    try:
        # Check duplicate keys before the existing recursive validated boundary.
        json.loads(body, object_pairs_hook=unique_pairs)
        return parse_api_json(body)
    except SigningInputError:
        raise
    except (ValueError, RecursionError, UnicodeError, QualityGateError) as error:
        raise SigningInputError("malformed acquisition JSON") from error


def relative_name(value: str) -> str:
    parts = value.split("/")
    require(bool(value) and not value.startswith("/") and not any(part in ("", ".", "..") for part in parts)
            and not any(character in value for character in "\\\r\n\t\0"), "unsafe owned relative path")
    return value


def root_status(root: Path) -> tuple[int, int, int]:
    require(root.is_absolute() and root == root.resolve(strict=True), "root is not an actual absolute directory")
    status = root.lstat()
    require(stat.S_ISDIR(status.st_mode) and status.st_uid == os.getuid(), "root is not an owned directory")
    return status.st_dev, status.st_ino, status.st_uid


def parent_fd(path: Path, roots: Sequence[Path], *, create: bool = False) -> int:
    require(path.is_absolute(), "owned path is not absolute")
    candidates = [root for root in roots if path != root and path.is_relative_to(root)]
    require(bool(candidates), "path escaped the authorized owned roots")
    root = max(candidates, key=lambda item: len(item.parts))
    relative = relative_name(path.relative_to(root).as_posix())
    device, inode, uid = root_status(root)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        anchored = os.fstat(descriptor)
        require((anchored.st_dev, anchored.st_ino, anchored.st_uid) == (device, inode, uid),
                "owned root changed before anchored open")
        for part in relative.split("/")[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            status = os.fstat(child)
            if status.st_uid != uid or status.st_dev != device:
                os.close(child)
                raise SigningInputError("owned directory moved to another owner or device")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def stat_key(status: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (status.st_dev, status.st_ino, status.st_uid, status.st_mode,
            status.st_nlink, status.st_size, status.st_mtime_ns)


def file_seal(path: Path, cap: int, roots: Sequence[Path], *, body: bool = False, empty: bool = False) -> tuple[JsonObject, bytes]:
    directory = parent_fd(path, roots)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            mode = stat.S_IMODE(before.st_mode)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                    and (0 <= before.st_size if empty else 0 < before.st_size) and before.st_size <= cap,
                    "body is not a bounded owned regular file")
            digest = hashlib.sha256()
            blob = hashlib.sha1(f"blob {before.st_size}\0".encode("ascii"))
            chunks: list[bytes] = []
            count = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                count += len(chunk)
                require(count <= cap, "body exceeded its bound")
                digest.update(chunk)
                blob.update(chunk)
                if body:
                    chunks.append(chunk)
            require(count == before.st_size and stat_key(before) == stat_key(os.fstat(stream.fileno()))
                    and stat_key(before) == stat_key(os.stat(path.name, dir_fd=directory, follow_symlinks=False)),
                    "body or anchored filename changed during complete read")
        return {"name": path.name, "size": count, "sha256": digest.hexdigest(), "blob": blob.hexdigest(), "mode": mode}, b"".join(chunks)
    finally:
        os.close(directory)


def private_json(path: Path, roots: Sequence[Path]) -> JsonObject:
    seal, body = file_seal(path, MAX_SELECTION_BYTES, roots, body=True)
    require(seal["mode"] == 0o600, "internal selection is not private")
    return decode(body)


def fresh_file(path: Path, roots: Sequence[Path]) -> None:
    directory = parent_fd(path, roots)
    try:
        try:
            os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise SigningInputError("owned output already exists")
    finally:
        os.close(directory)


def write_json(path: Path, value: JsonObject, roots: Sequence[Path]) -> JsonObject:
    fresh_file(path, roots)
    body = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    require(len(body) <= MAX_SELECTION_BYTES, "acquisition receipt exceeded its bound")
    directory = parent_fd(path, roots)
    try:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return file_seal(path, MAX_SELECTION_BYTES, roots)[0]


def fresh_directory(path: Path, roots: Sequence[Path]) -> None:
    directory = parent_fd(path, roots)
    try:
        os.mkdir(path.name, 0o700, dir_fd=directory)
        status = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        require(stat.S_ISDIR(status.st_mode) and stat.S_IMODE(status.st_mode) == 0o700
                and status.st_uid == os.getuid(), "fresh directory is not private")
    finally:
        os.close(directory)


def git_bytes(source: Path, arguments: Sequence[str]) -> bytes:
    result = subprocess.run(["git", *arguments], cwd=source, capture_output=True, check=False, timeout=15,
                            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    require(result.returncode == 0 and len(result.stdout) <= MAX_GIT_BYTES and len(result.stderr) <= 65536,
            "trusted source Git inventory unavailable or excessive")
    return result.stdout


def source_guard(source: Path, allowed: Mapping[str, JsonObject]) -> JsonObject:
    physical_root: list[JsonValue] = list(root_status(source))
    head = git_bytes(source, ("rev-parse", "HEAD")).decode("ascii").strip()
    tree = git_bytes(source, ("rev-parse", "HEAD^{tree}")).decode("ascii").strip()
    expected: dict[str, tuple[str, str]] = {}
    for entry in git_bytes(source, ("ls-tree", "-rz", "--full-tree", "HEAD")).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split(" ")
        name = relative_name(raw_path.decode("utf-8"))
        require(kind == "blob" and mode in ("100644", "100755") and name not in expected, "unsupported tracked source entry")
        expected[name] = mode, blob
    require(0 < len(expected) <= MAX_SOURCE_FILES, "tracked source inventory exceeded its bound")
    index: dict[str, tuple[str, str]] = {}
    for entry in git_bytes(source, ("ls-files", "--stage", "-z")).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, blob, stage = metadata.decode("ascii").split(" ")
        name = relative_name(raw_path.decode("utf-8"))
        require(stage == "0" and name not in index, "unmerged or duplicate source index entry")
        index[name] = mode, blob
    require(index == expected, "tracked index differs from immutable HEAD")
    rows: list[JsonValue] = []
    total = 0
    for name, (mode, blob) in sorted(expected.items()):
        seal, _body = file_seal(source / name, MAX_SOURCE_FILE_BYTES, (source,), empty=True)
        require(seal["blob"] == blob and seal["mode"] == (0o755 if mode == "100755" else 0o644),
                "physical tracked source differs from immutable HEAD bytes or mode")
        total += integer(seal["size"], "source size", minimum=0)
        require(total <= MAX_SOURCE_TOTAL_BYTES, "source inventory exceeded total byte bound")
        rows.append({"path": name, "Git_mode": mode, **seal})
    untracked = [relative_name(row.decode("utf-8")) for row in
                 git_bytes(source, ("ls-files", "--others", "-z")).split(b"\0") if row]
    require(len(untracked) == len(set(untracked)) and set(untracked) == set(allowed),
            "unrelated untracked source data or missing owned output")
    for name in untracked:
        expected_seal = allowed[name]
        cap = integer(expected_seal["size"], "owned size")
        seal, _body = file_seal(source / name, cap, (source,))
        require(seal == expected_seal and seal["mode"] in (0o600, 0o644)
                and Path(name).suffix in (".zip", ".json"), "owned data mode/body/namespace changed")
    require(physical_root == list(root_status(source)), "source root changed during inspection")
    return {"head": head, "tree": tree, "physical_root": physical_root, "files": rows}


def trusted_context(source: Path, environment: Mapping[str, str]) -> JsonObject:
    require(environment.get("GITHUB_REPOSITORY") == REPOSITORY and environment.get("GITHUB_REF") == "refs/heads/main",
            "exact trusted repository/main required")
    event = environment.get("GITHUB_EVENT_NAME", "")
    require(event in ("push", "workflow_dispatch"), "actual trusted-main Build event required")
    sha = environment.get("GITHUB_SHA", "")
    require(re.fullmatch("[a-f0-9]{40}", sha) is not None, "invalid Build SHA")
    require(environment.get("GITHUB_WORKFLOW_REF") == f"{REPOSITORY}/{BUILD_PATH}@refs/heads/main"
            and environment.get("GITHUB_WORKFLOW_SHA") == sha, "actual Build workflow source mismatch")
    require(environment.get("GITHUB_WORKSPACE") == str(source), "source differs from actual workspace")
    run, attempt = environment.get("GITHUB_RUN_ID", ""), environment.get("GITHUB_RUN_ATTEMPT", "")
    require(re.fullmatch("[1-9][0-9]*", run) is not None and re.fullmatch("[1-9][0-9]*", attempt) is not None,
            "invalid Build run/attempt")
    return {"repository": REPOSITORY, "source_sha": sha, "event": event, "run_id": int(run), "run_attempt": int(attempt)}


def current_run(api: ApiReader, trusted: JsonObject) -> JsonObject:
    workflow = api.get(f"{API_ROOT}/workflows/release.yml")
    require(workflow.get("path") == BUILD_PATH and workflow.get("state") == "active", "maintained Build unavailable")
    workflow_id = integer(workflow.get("id"), "workflow ID")
    run_id = integer(trusted["run_id"], "run ID")
    run = api.get(f"{API_ROOT}/runs/{run_id}")
    expected: JsonObject = {"id": run_id, "run_attempt": trusted["run_attempt"], "head_sha": trusted["source_sha"],
                            "event": trusted["event"], "head_branch": "main", "path": BUILD_PATH, "workflow_id": workflow_id}
    require(all(type(run.get(key)) is type(value) and run.get(key) == value for key, value in expected.items())
            and object_value(run.get("repository"), "repository").get("full_name") == REPOSITORY, "current Build identity/attempt drift")
    require((run.get("status") == "in_progress" and run.get("conclusion") is None)
            or (run.get("status") == "completed" and run.get("conclusion") == "success"), "current Build failed or is not running")
    attempt = api.get(f"{API_ROOT}/runs/{run_id}/attempts/{integer(trusted['run_attempt'], 'attempt')}")
    require(all(type(attempt.get(key)) is type(value) and attempt.get(key) == value for key, value in expected.items())
            and object_value(attempt.get("repository"), "attempt repository").get("full_name") == REPOSITORY,
            "attempt identity differs from current Build")
    require((attempt.get("status") == "in_progress" and attempt.get("conclusion") is None)
            or (attempt.get("status") == "completed" and attempt.get("conclusion") == "success"),
            "current attempt failed or is not running")
    return run


def job_projection(job: JsonObject) -> JsonObject:
    return {key: job.get(key) for key in ("id", "name", "run_id", "run_attempt", "head_sha", "head_branch",
                                        "started_at", "completed_at", "status", "conclusion")}


def required_job(jobs: Mapping[str, JsonObject], name: str) -> JsonObject:
    require(name in jobs, f"missing required Build role: {name}")
    job = jobs[name]
    require(job.get("status") == "completed" and job.get("conclusion") == "success", f"unsuccessful Build role: {name}")
    return job


def signing_job(jobs: Mapping[str, JsonObject], architecture: str, attempt: int) -> JsonObject:
    token = ", macos-arm64," if architecture == "arm64" else ", macos-x86_64,"
    matches = [job for name, job in jobs.items() if name.startswith("macos-sign (") and token in name]
    require(len(matches) == 1, "missing or ambiguous native signing role")
    job = matches[0]
    require(job.get("status") == "completed" and job.get("conclusion") == "success"
            and integer(job.get("run_attempt"), "signing attempt") == attempt, "signing must succeed under current common attempt")
    steps = job.get("steps")
    require(isinstance(steps, list), "signing step evidence unavailable")
    if not isinstance(steps, list):
        raise SigningInputError("signing steps unavailable")
    names = [text(object_value(row, "signing step").get("name"), "step name") for row in steps]
    require(len(names) == len(set(names)), "duplicate signing step names")
    for name in ("Recheck same-run inputs before secret access", "Sign notarize staple and test publication bytes",
                 "Upload eligible signed macOS payloads", "Upload eligible signing receipts"):
        matches_step = [object_value(row, "step") for row in steps if object_value(row, "step").get("name") == name]
        require(len(matches_step) == 1 and matches_step[0].get("status") == "completed"
                and matches_step[0].get("conclusion") == "success", "required signing/evidence step failed")
    return job


def snapshot(api: ApiReader, trusted: JsonObject, mode: str, architecture: str | None) -> JsonObject:
    run = current_run(api, trusted)
    jobs = latest_jobs(api, run)
    require(len([name for name in jobs if name.startswith("build (")]) == 4, "native Build profile changed")
    preflight = required_job(jobs, "release-state-preflight")
    quality = required_job(jobs, "main-quality")
    version = required_job(jobs, "get-version")
    rows = collection(api, f"{API_ROOT}/runs/{integer(run['id'], 'run')}/artifacts", "artifacts")
    artifacts: JsonObject = {}
    roles: list[JsonValue] = [job_projection(version), job_projection(preflight), job_projection(quality)]
    native: dict[str, JsonObject] = {}
    for arch in ARCHITECTURES:
        native[arch] = native_job(jobs, arch)
    roles.extend(job_projection(job) for name, job in sorted(jobs.items()) if name.startswith("build (")
                 and any(token in name for token in (", windows,", ", linux,", ", macos-arm64,", ", macos-x86_64,")))
    if mode == "signing":
        require(architecture in ARCHITECTURES, "signing architecture required")
        arch = "arm64" if architecture == "arm64" else "x86_64"
        job = native[arch]
        name = "macos-arm64" if arch == "arm64" else "macos-x86_64"
        attempt = integer(job.get("run_attempt"), "native attempt")
        artifacts["unsigned"] = artifact_record(rows, f"GM2Godot-{name}", run, job)
        artifacts["proof"] = artifact_record(rows, f"GM2Godot-{name}-proof-{run['id']}-{attempt}", run, job, cap=MAX_PROOF_ARCHIVE_BYTES)
    else:
        for platform in ("windows", "linux"):
            matches = [job for name, job in jobs.items() if name.startswith("build (") and f", {platform}," in name]
            require(len(matches) == 1, "ambiguous non-Mac native role")
            artifacts[platform] = artifact_record(rows, f"GM2Godot-{platform}", run, matches[0])
        for arch in ARCHITECTURES:
            job = signing_job(jobs, arch, integer(run["run_attempt"], "run attempt"))
            roles.append(job_projection(job))
            name = "macos-arm64" if arch == "arm64" else "macos-x86_64"
            artifacts[f"{arch}_payload"] = artifact_record(rows, f"GM2Godot-{name}-signed", run, job)
            artifacts[f"{arch}_proof"] = artifact_record(rows, f"GM2Godot-{name}-signing-proof-{run['id']}-{run['run_attempt']}",
                                                       run, job, cap=MAX_SIGNED_PROOF_ARCHIVE_BYTES)
    for value in artifacts.values():
        record = object_value(value, "artifact")
        current = api.get(f"{API_ROOT}/artifacts/{integer(record['id'], 'artifact ID')}")
        matching = [row for row in rows if row.get("id") == record["id"]]
        require(len(matching) == 1 and current == matching[0], "listing/per-artifact metadata drift")
    ids = [integer(object_value(value, "artifact")["id"], "artifact ID") for value in artifacts.values()]
    require(len(ids) == len(set(ids)), "artifact IDs are reused across purposes")
    return {"workflow_id": integer(run["workflow_id"], "workflow ID"), "prerequisites": roles, "artifacts": artifacts}


def make_selection(api: ApiReader, source: Path, trusted: JsonObject, mode: str, architecture: str | None) -> JsonObject:
    guard = source_guard(source, {})
    require(guard["head"] == trusted["source_sha"], "source differs from actual Build SHA")
    before = snapshot(api, trusted, mode, architecture)
    require(snapshot(api, trusted, mode, architecture) == before and source_guard(source, {}) == guard,
            "source or required role/artifact identity changed during planning")
    trusted_full = dict(trusted)
    trusted_full["source_tree"] = guard["tree"]
    trusted_full["architecture"] = architecture
    trusted_full["workflow_id"] = before["workflow_id"]
    return {"schema_version": 1, "mode": mode, "trusted": trusted_full, "source_guard": guard,
            "prerequisites": before["prerequisites"], "artifacts": before["artifacts"]}


def validate_selection(saved: JsonObject, trusted: JsonObject, mode: str, architecture: str | None) -> None:
    closed(saved, SELECTION_KEYS, "selection")
    require(type(saved["schema_version"]) is int and saved["schema_version"] == 1 and saved["mode"] == mode,
            "selection schema/mode mismatch")
    bound = closed(saved["trusted"], frozenset({*trusted, "source_tree", "architecture", "workflow_id"}), "trusted selection")
    require(all(type(bound[key]) is type(value) and bound[key] == value for key, value in trusted.items())
            and bound["architecture"] == architecture, "selection belongs to another source/event/run/attempt/architecture")
    require(re.fullmatch("[a-f0-9]{40}", text(bound["source_tree"], "source tree")) is not None, "invalid selected tree")
    integer(bound["workflow_id"], "selected workflow ID")
    artifacts = object_value(saved["artifacts"], "selected artifacts")
    expected = {"unsigned", "proof"} if mode == "signing" else {"windows", "linux", "arm64_payload", "x86_64_payload", "arm64_proof", "x86_64_proof"}
    require(frozenset(artifacts) == frozenset(expected), "selected artifact purposes differ")
    for value in artifacts.values():
        record = closed(value, ARTIFACT_KEYS, "selected artifact")
        integer(record["id"], "artifact ID")
        require(integer(record["size"], "artifact size") <= MAX_ARCHIVE_BYTES
                and re.fullmatch("sha256:[a-f0-9]{64}", text(record["digest"], "artifact digest")) is not None,
                "invalid selected body seal")
    require(object_value(saved["source_guard"], "source guard").get("head") == trusted["source_sha"], "selected source guard mismatch")


def recheck(api: ApiReader, saved: JsonObject) -> None:
    trusted = object_value(saved["trusted"], "trusted")
    mode = text(saved["mode"], "mode")
    arch_value = trusted["architecture"]
    require(arch_value is None or isinstance(arch_value, str), "invalid selected architecture")
    architecture = arch_value if isinstance(arch_value, str) else None
    now = snapshot(api, trusted, mode, architecture)
    require(now["workflow_id"] == trusted["workflow_id"] and now["prerequisites"] == saved["prerequisites"]
            and now["artifacts"] == saved["artifacts"], "selected provider roles/artifacts changed")


def record(saved: JsonObject, key: str) -> JsonObject:
    return object_value(object_value(saved["artifacts"], "artifacts")[key], key)


def downloaded(directory: Path, artifact: JsonObject, roots: Sequence[Path]) -> tuple[Path, JsonObject]:
    require(text(artifact["name"], "artifact name").startswith("GM2Godot-"), "unexpected artifact name")
    path = directory / f"{artifact['name']}.zip"
    descriptor = parent_fd(path, roots)  # Directory verification does not follow a symlink.
    os.close(descriptor)
    require(sorted(item.name for item in directory.iterdir()) == [path.name], "download directory has extra or missing files")
    seal, _body = file_seal(path, MAX_ARCHIVE_BYTES, roots)
    require(seal["mode"] in (0o600, 0o644) and seal["size"] == artifact["size"]
            and f"sha256:{seal['sha256']}" == artifact["digest"], "downloaded full body differs from selected API digest")
    return path, seal


def local_members(archive: zipfile.ZipFile, caps: Mapping[str, int]) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    require(len(members) == len(caps) and {member.filename for member in members} == set(caps)
            and len({member.filename.casefold() for member in members}) == len(members), "artifact namespace/duplicate collision")
    for member in members:
        require(member.orig_filename == member.filename and member.filename == Path(member.filename).name
                and "\\" not in member.filename and not member.extra and not member.is_dir()
                and not member.flag_bits & 1 and member.create_system == 3 and stat.S_ISREG(member.external_attr >> 16)
                and not member.external_attr & 0x10 and 0 < member.file_size <= caps[member.filename],
                "artifact member is unsafe, unencrypted nonregular, or excessive")
        stream = archive.fp
        require(stream is not None, "archive closed during local header validation")
        if stream is None:
            raise SigningInputError("archive unavailable")
        stream.seek(member.header_offset)
        raw = stream.read(LOCAL_HEADER.size)
        require(len(raw) == LOCAL_HEADER.size, "truncated local header")
        fields = LOCAL_HEADER.unpack(raw)
        name, extra = stream.read(fields[-2]), stream.read(fields[-1])
        expected_name = member.filename.encode("utf-8" if member.flag_bits & 0x800 else "cp437")
        require(fields[0] == 0x04034B50 and fields[2] == member.flag_bits and fields[3] == member.compress_type
                and name == expected_name and len(extra) == fields[-1] and not extra, "local/central ZIP metadata mismatch")
        require(bool(member.flag_bits & 8) or (fields[6], fields[7], fields[8])
                == (member.CRC, member.compress_size, member.file_size), "local/central ZIP CRC or size disagreement")
    require(sum(member.file_size for member in members) <= sum(caps.values()), "archive decompressed limit exceeded")
    return members


def verify_raw_archive(raw: BinaryIO, path: Path, directory: int, selected: JsonObject,
                       identity: os.stat_result | None = None) -> os.stat_result:
    before = os.fstat(raw.fileno())
    anchored = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
            and 0 < before.st_size <= MAX_ARCHIVE_BYTES
            and stat_key(before) == stat_key(anchored) and before.st_ctime_ns == anchored.st_ctime_ns,
            "parsed ZIP descriptor differs from anchored selected filename")
    if identity is not None:
        require(stat_key(before) == stat_key(identity) and before.st_ctime_ns == identity.st_ctime_ns,
                "parsed ZIP descriptor changed during member verification")
    raw.seek(0)
    digest = hashlib.sha256()
    blob = hashlib.sha1(f"blob {before.st_size}\0".encode("ascii"))
    count = 0
    for chunk in iter(lambda: raw.read(1024 * 1024), b""):
        count += len(chunk)
        require(count <= MAX_ARCHIVE_BYTES and count <= before.st_size, "parsed ZIP exceeded its complete body bound")
        digest.update(chunk)
        blob.update(chunk)
    after = os.fstat(raw.fileno())
    anchored_after = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
    require(count == before.st_size and stat_key(before) == stat_key(after) == stat_key(anchored_after)
            and before.st_ctime_ns == after.st_ctime_ns == anchored_after.st_ctime_ns,
            "parsed ZIP descriptor or filename changed during complete body read")
    actual: JsonObject = {"name": path.name, "size": count, "sha256": digest.hexdigest(),
                          "blob": blob.hexdigest(), "mode": stat.S_IMODE(before.st_mode)}
    require(actual == selected, "parsed ZIP full body differs from selected API-bound seal")
    raw.seek(0)
    return before


def inspect_members(path: Path, caps: Mapping[str, int], roots: Sequence[Path], destination: Path | None = None,
                    *, selected: JsonObject) -> list[JsonValue]:
    directory = parent_fd(path, roots)
    rows: list[JsonValue] = []
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as raw:
            identity = verify_raw_archive(raw, path, directory, selected)
            with zipfile.ZipFile(raw) as archive:
                for member in local_members(archive, caps):
                    target = None
                    if destination is not None:
                        parent = parent_fd(destination / member.filename, roots)
                        try:
                            target = os.fdopen(os.open(member.filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                                       0o600, dir_fd=parent), "wb")
                        finally:
                            os.close(parent)
                    digest = hashlib.sha256()
                    count = 0
                    try:
                        with archive.open(member) as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                count += len(chunk)
                                require(count <= caps[member.filename] and count <= member.file_size, "member exceeded its bound")
                                digest.update(chunk)
                                if target is not None:
                                    target.write(chunk)
                        require(count == member.file_size, "member was not read through EOF")
                    finally:
                        if target is not None:
                            target.close()
                    rows.append({"name": member.filename, "size": count, "sha256": digest.hexdigest()})
            verify_raw_archive(raw, path, directory, selected, identity)
    finally:
        os.close(directory)
    require(file_seal(path, MAX_ARCHIVE_BYTES, roots)[0] == selected, "archive changed while reading complete members")
    return rows


def context(saved: JsonObject, architecture: str) -> JsonObject:
    trusted = object_value(saved["trusted"], "trusted")
    run: JsonObject = {"run_id": trusted["run_id"], "run_attempt": trusted["run_attempt"], "event": trusted["event"],
                       "branch": "main", "head_sha": trusted["source_sha"]}
    producer = dict(run)
    producer["workflow_id"] = trusted["workflow_id"]
    return {"schema_version": 1, "purpose": "publication", "release_eligible": True, "repository": REPOSITORY,
            "source": {"sha": trusted["source_sha"], "tree": trusted["source_tree"]}, "producer": producer,
            "signing": run, "architecture": architecture,
            "unsigned_artifact": record(saved, "unsigned"), "proof_artifact": record(saved, "proof")}


def signing_layout(source: Path, temporary: Path, paths: Sequence[Path]) -> None:
    root_status(source)
    root_status(temporary)
    require(not temporary.is_relative_to(source) and not source.is_relative_to(temporary),
            "signing runner-temp and source roots must be separate")
    require(len(paths) == len(set(paths)) and all(path.parent == temporary for path in paths),
            "signing data must be distinct direct owned runner-temp paths outside source")
    for path in paths:
        relative_name(path.name)


def verify_signing(api: ApiReader, saved: JsonObject, source: Path, payload_directory: Path, proof_directory: Path,
                   inputs: Path, roots: Sequence[Path]) -> tuple[JsonObject, JsonObject]:
    require(len(roots) == 2 and roots[0] == source, "signing owned root roles differ")
    proof_output = inputs.with_name(inputs.name + "-original-proof")
    signing_layout(source, roots[1], (payload_directory, proof_directory, inputs, proof_output))
    recheck(api, saved)
    require(source_guard(source, {}) == saved["source_guard"], "source changed before signing acquisition")
    trusted = object_value(saved["trusted"], "trusted")
    architecture = text(trusted["architecture"], "architecture")
    name = "macos-arm64" if architecture == "arm64" else "macos-x86_64"
    payload, payload_seal = downloaded(payload_directory, record(saved, "unsigned"), roots)
    proof, proof_seal = downloaded(proof_directory, record(saved, "proof"), roots)
    fresh_directory(inputs, roots)
    fresh_directory(proof_output, roots)
    pair = {f"GM2Godot-{name}.zip": MAX_ARCHIVE_BYTES, f"GM2Godot-{name}.dmg": MAX_ARCHIVE_BYTES}
    payload_members = inspect_members(payload, pair, roots, inputs, selected=payload_seal)
    proof_caps = {f"release-{name}-{kind}.json": MAX_PROOF_BYTES for kind in ("bootstrap", "dependencies", "native-tests", "gui")}
    proof_members = inspect_members(proof, proof_caps, roots, proof_output, selected=proof_seal)
    evidence = verify_original_proof(proof, inputs / f"GM2Godot-{name}.zip", architecture, source, record=record(saved, "proof"))
    original_prechecks = verify_prechecks(proof_output / f"release-{name}-native-tests.json",
                                         proof_output / f"release-{name}-dependencies.json",
                                         proof_output / f"release-{name}-bootstrap.json", architecture, source)
    recheck(api, saved)
    require(file_seal(payload, MAX_ARCHIVE_BYTES, roots)[0] == payload_seal
            and file_seal(proof, MAX_ARCHIVE_BYTES, roots)[0] == proof_seal
            and source_guard(source, {}) == saved["source_guard"], "original inputs/source changed after semantic verification")
    receipt: JsonObject = {"schema_version": 1, "successful": True, "purpose": "publication_input_acquisition",
                           "selection": saved, "payload_archive": payload_seal, "proof_archive": proof_seal,
                           "payload_members": payload_members, "proof_members": proof_members,
                           "original_native_GUI": evidence, "original_bootstrap_dependencies": original_prechecks,
                           "proof_directory": str(proof_output)}
    return context(saved, architecture), receipt


def allowed_data(source: Path, files: Mapping[Path, JsonObject]) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    for path, seal in files.items():
        if path.is_relative_to(source):
            relative = relative_name(path.relative_to(source).as_posix())
            require(relative not in result and path.suffix in (".zip", ".json") and seal["mode"] in (0o600, 0o644),
                    "owned allowance is not finite nonimportable data")
            result[relative] = seal
    return result


def normalize_archive(path: Path, target: Path, roots: Sequence[Path]) -> None:
    require(path.parent == target.parent and path != target, "invalid normalization target")
    fresh_file(target, roots)
    before = file_seal(path, MAX_ARCHIVE_BYTES, roots)[0]
    directory = parent_fd(path, roots)
    try:
        os.link(path.name, target.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        left = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        right = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
        require(left.st_dev == right.st_dev and left.st_ino == right.st_ino and left.st_nlink == right.st_nlink == 2,
                "normalization link identity changed")
        os.unlink(path.name, dir_fd=directory)
    finally:
        os.close(directory)
    after = file_seal(target, MAX_ARCHIVE_BYTES, roots)[0]
    require({key: value for key, value in after.items() if key != "name"}
            == {key: value for key, value in before.items() if key != "name"}, "normalized archive body changed")


def signed_receipt(path: Path, saved: JsonObject, source: Path, architecture: str, payloads: list[JsonValue], roots: Sequence[Path]) -> None:
    _seal, body = file_seal(path, PROOF_CAPS["signing.json"], roots, body=True)
    receipt = closed(decode(body), RECEIPT_KEYS, "signed publication receipt")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1 and receipt["successful"] is True
            and receipt["purpose"] == "publication" and receipt["release_eligible"] is True,
            "verification-only or unsuccessful signing evidence cannot enter publication")
    trusted = object_value(saved["trusted"], "trusted")
    require(receipt["repository"] == REPOSITORY and receipt["architecture"] == architecture
            and receipt["source"] == {"sha": trusted["source_sha"], "tree": trusted["source_tree"]}, "receipt source/architecture mismatch")
    expected: JsonObject = {"run_id": trusted["run_id"], "run_attempt": trusted["run_attempt"], "event": trusted["event"],
                            "branch": "main", "head_sha": trusted["source_sha"]}
    signing = closed(receipt["signing"], frozenset(expected), "receipt signing")
    require(all(type(signing[key]) is type(value) and signing[key] == value for key, value in expected.items()),
            "receipt signing event/run/current attempt mismatch")
    expected["workflow_id"] = trusted["workflow_id"]
    producer = closed(receipt["producer"], frozenset(expected), "receipt producer")
    require(all(type(producer[key]) is type(value) and producer[key] == value for key, value in expected.items())
            and receipt["version"] == load_source_policy(source)["version"], "receipt producer/source version mismatch")
    rows = receipt["final_payloads"]
    require(isinstance(rows, list) and sorted(rows, key=lambda item: text(object_value(item, "payload")["name"], "name"))
            == sorted(payloads, key=lambda item: text(object_value(item, "payload")["name"], "name")), "receipt final full-body seals mismatch")


def verify_publisher(api: ApiReader, saved: JsonObject, source: Path, raw_root: Path, proof_root: Path,
                     receipt_root: Path, roots: Sequence[Path]) -> tuple[JsonObject, JsonObject, dict[Path, JsonObject]]:
    recheck(api, saved)
    require(raw_root == source / "raw-artifacts" and proof_root == source / "raw-signing-proofs"
            and receipt_root == source / "signing-receipts", "publisher output roots differ from authored finite layout")
    require(sorted(item.name for item in raw_root.iterdir()) == ["GM2Godot-linux", "GM2Godot-macos-arm64", "GM2Godot-macos-x86_64", "GM2Godot-windows"]
            and sorted(item.name for item in proof_root.iterdir()) == ["arm64", "x86_64"], "publisher raw roots contain unrelated directories")
    files: dict[Path, JsonObject] = {}
    selected_paths: dict[str, Path] = {}
    for platform in ("windows", "linux"):
        path, seal = downloaded(raw_root / f"GM2Godot-{platform}", record(saved, platform), roots)
        files[path] = seal
        inspect_members(path, {f"GM2Godot-{platform}.zip": MAX_ARCHIVE_BYTES}, roots, selected=seal)
    for arch in ARCHITECTURES:
        name = "macos-arm64" if arch == "arm64" else "macos-x86_64"
        for purpose, directory in (("payload", raw_root / f"GM2Godot-{name}"), ("proof", proof_root / arch)):
            path, seal = downloaded(directory, record(saved, f"{arch}_{purpose}"), roots)
            selected_paths[f"{arch}_{purpose}"] = path
            files[path] = seal
    require(source_guard(source, allowed_data(source, files)) == saved["source_guard"], "source/unrelated untracked changed after downloads")
    fresh_directory(receipt_root, roots)
    member_rows: JsonObject = {}
    trusted = object_value(saved["trusted"], "trusted")
    for arch in ARCHITECTURES:
        name = "macos-arm64" if arch == "arm64" else "macos-x86_64"
        destination = receipt_root / arch
        fresh_directory(destination, roots)
        proofs = inspect_members(selected_paths[f"{arch}_proof"], PROOF_CAPS, roots, destination,
                                 selected=files[selected_paths[f"{arch}_proof"]])
        payload = selected_paths[f"{arch}_payload"]
        pair = inspect_members(payload, {f"GM2Godot-{name}.zip": MAX_ARCHIVE_BYTES, f"GM2Godot-{name}.dmg": MAX_ARCHIVE_BYTES}, roots,
                               selected=files[payload])
        signed_receipt(destination / "signing.json", saved, source, arch, pair, roots)
        member_rows[arch] = {"payloads": pair, "proofs": proofs}
        for filename in PROOF_CAPS:
            path = destination / filename
            files[path] = file_seal(path, PROOF_CAPS[filename], roots)[0]
        target = payload.with_name(f"GM2Godot-{name}.zip")
        normalize_archive(payload, target, roots)
        del files[payload]
        files[target] = file_seal(target, MAX_ARCHIVE_BYTES, roots)[0]
    recheck(api, saved)
    require(source_guard(source, allowed_data(source, files)) == saved["source_guard"], "final owned data/source guard failed")
    producer: JsonObject = {"run_id": trusted["run_id"], "run_attempt": trusted["run_attempt"], "workflow_id": trusted["workflow_id"],
                            "event": trusted["event"], "branch": "main", "head_sha": trusted["source_sha"]}
    publisher_context: JsonObject = {"schema_version": 1, "purpose": "publication", "release_eligible": True,
                                    "repository": REPOSITORY, "source": {"sha": trusted["source_sha"], "tree": trusted["source_tree"]},
                                    "producer": producer, "signing": {key: value for key, value in producer.items() if key != "workflow_id"}}
    receipt: JsonObject = {"schema_version": 1, "successful": True, "selection": saved, "members": member_rows,
                           "owned_data": [{"path": str(path), **seal} for path, seal in sorted(files.items())],
                           "scope": "Acquisition/full byte and context proof only; final Developer ID/notary/GUI gate remains mandatory before checksums."}
    return publisher_context, receipt, files


def outputs(saved: JsonObject, path: Path, roots: Sequence[Path]) -> None:
    trusted = object_value(saved["trusted"], "trusted")
    values = {"workflow_id": integer(trusted["workflow_id"], "workflow ID")}
    if saved["mode"] == "signing":
        values.update(unsigned_artifact_id=integer(record(saved, "unsigned")["id"], "unsigned ID"),
                      proof_artifact_id=integer(record(saved, "proof")["id"], "proof ID"))
    else:
        for arch in ARCHITECTURES:
            for purpose in ("payload", "proof"):
                values[f"{arch}_{purpose}_id"] = integer(record(saved, f"{arch}_{purpose}")["id"], "signed artifact ID")
    directory = parent_fd(path, roots)
    try:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "wb") as stream:
        status = os.fstat(stream.fileno())
        require(stat.S_ISREG(status.st_mode) and status.st_uid == os.getuid() and status.st_nlink == 1
                and status.st_size <= 65536, "unsafe Actions output file")
        stream.write("".join(f"{name}={value}\n" for name, value in values.items()).encode("ascii"))


class Options(argparse.Namespace):
    mode: str
    source_root: Path
    architecture: str | None
    selection: Path
    payload_directory: Path | None
    proof_directory: Path | None
    inputs: Path | None
    context: Path | None
    receipt: Path | None
    raw_root: Path | None
    proof_root: Path | None
    receipt_root: Path | None


def needed(value: Path | None, label: str) -> Path:
    if value is None:
        raise SigningInputError(f"missing argument: {label}")
    return value


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan-signing", "verify-signing", "plan-publisher", "verify-publisher"))
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--architecture", choices=ARCHITECTURES)
    for name in ("payload-directory", "proof-directory", "inputs", "context", "receipt", "raw-root", "proof-root", "receipt-root"):
        parser.add_argument(f"--{name}", type=Path)
    options = Options()
    parser.parse_args(arguments, namespace=options)
    try:
        source = options.source_root
        temporary = Path(os.environ.get("RUNNER_TEMP", ""))
        root_status(temporary)
        roots = (source, temporary)
        trusted = trusted_context(source, os.environ)
        signing = options.mode.endswith("signing")
        require((signing and options.architecture in ARCHITECTURES) or (not signing and options.architecture is None),
                "architecture must be specified only for native signing modes")
        require(os.environ.get("GITHUB_JOB") == ("macos-sign" if signing else "release"), "caller is not the authored Build role")
        mode = "signing" if signing else "publisher"
        api = GitHubApi(os.environ.get("GH_TOKEN", ""), Budget(180))
        require(options.selection.parent == temporary, "selection must be a direct private runner-temp file")
        if signing:
            signing_layout(source, temporary, (options.selection,))
        if options.mode.startswith("plan-"):
            chosen = make_selection(api, source, trusted, mode, options.architecture)
            write_json(options.selection, chosen, roots)
            outputs(chosen, Path(os.environ.get("GITHUB_OUTPUT", "")), (temporary,))
            require(source_guard(source, {}) == chosen["source_guard"], "source changed after selection/output publication")
            print(json.dumps({"successful": True, "mode": options.mode, "selection": str(options.selection)}, sort_keys=True))
            return 0
        saved = private_json(options.selection, roots)
        validate_selection(saved, trusted, mode, options.architecture)
        context_path, receipt_path = needed(options.context, "context"), needed(options.receipt, "receipt")
        require(context_path.parent == temporary and receipt_path.parent == temporary and len({options.selection, context_path, receipt_path}) == 3,
                "private receipt paths collide or escape runner temp")
        fresh_file(context_path, roots)
        fresh_file(receipt_path, roots)
        files: dict[Path, JsonObject] = {}
        if signing:
            inputs = needed(options.inputs, "inputs")
            signing_layout(source, temporary, (options.selection, context_path, receipt_path,
                           needed(options.payload_directory, "payload-directory"),
                           needed(options.proof_directory, "proof-directory"), inputs,
                           inputs.with_name(inputs.name + "-original-proof")))
            bound, receipt = verify_signing(api, saved, source, needed(options.payload_directory, "payload-directory"),
                                           needed(options.proof_directory, "proof-directory"), inputs, roots)
        else:
            bound, receipt, files = verify_publisher(api, saved, source, needed(options.raw_root, "raw-root"),
                                                    needed(options.proof_root, "proof-root"), needed(options.receipt_root, "receipt-root"), roots)
        context_seal = write_json(context_path, bound, roots)
        receipt_seal = write_json(receipt_path, receipt, roots)
        recheck(api, saved)
        require(source_guard(source, allowed_data(source, files)) == saved["source_guard"], "final source/output guard failed")
        print(json.dumps({"successful": True, "mode": options.mode, "context": context_seal,
                          "receipt": receipt_seal}, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError, UnicodeError, RecursionError, subprocess.SubprocessError,
            zipfile.BadZipFile, KeyError) as error:
        reason = str(error) if isinstance(error, SigningInputError) else type(error).__name__
        print(f"Publication inputs rejected: {reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
