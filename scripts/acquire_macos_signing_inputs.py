"""Acquire exact-source trusted-main inputs for verification-only signing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from collections.abc import Generator, Mapping
from contextlib import ExitStack, contextmanager
from http.client import HTTPException, HTTPSConnection
from io import BufferedReader, FileIO
from pathlib import Path
from ssl import TLSVersion, create_default_context
from typing import BinaryIO
from urllib.parse import urlsplit

if (trusted_root := str(Path(__file__).resolve().parents[1])) not in sys.path:
    sys.path.insert(0, trusted_root)

from scripts.check_main_quality import ApiReader, Budget, GitHubApi, parse_api_json
from src.conversion.json_values import JsonObject, JsonValue

REPOSITORY = "Infiland/GM2Godot"
API_ROOT = f"/repos/{REPOSITORY}/actions"
BUILD_PATH = ".github/workflows/release.yml"
MAX_RECORDS = 1000
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_PROOF_BYTES = 8 * 1024 * 1024
MAX_PROOF_ARCHIVE_BYTES = 32 * 1024 * 1024
PRIVATE_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL
NATIVE_METHODS = (
    "test_native_runtime_is_untranslated",
    "test_native_clean_exit_preserves_owned_leader",
    "test_native_exit_before_observer_registration",
    "test_native_timeout_reaps_owned_group",
    "test_native_inherited_stdout_descendant_is_bounded",
    "test_native_output_budget_stops_owned_group",
    "test_native_observer_and_control_errors_preserve_primary",
)


class SigningInputError(ValueError):
    """Unverified source, producer or input bytes cannot enter signing."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SigningInputError(message)


def object_value(value: JsonValue, field: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SigningInputError(f"invalid object: {field}")
    return value


def text(value: JsonValue, field: str) -> str:
    if not isinstance(value, str):
        raise SigningInputError(f"invalid text: {field}")
    return value


def integer(value: JsonValue, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SigningInputError(f"invalid integer: {field}")
    return value


def git_value(source: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", revision], cwd=source, capture_output=True,
        check=False, timeout=15,
    )
    require(result.returncode == 0, "trusted checkout identity unavailable")
    return result.stdout.decode("ascii").strip()


def clean_checkout(source: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=source, capture_output=True, check=False, timeout=15,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    require(result.returncode == 0 and result.stdout == b"", "trusted tracked checkout/index is not clean")


def trusted_context(source: Path, architecture: str, environment: Mapping[str, str]) -> JsonObject:
    expected = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
    }
    require(all(environment.get(key) == value for key, value in expected.items()), "trusted manual-main context required")
    sha = environment.get("GITHUB_SHA", "")
    require(re.fullmatch("[a-f0-9]{40}", sha) is not None, "invalid trusted source SHA")
    require(architecture in ("arm64", "x86_64"), "unsupported architecture")
    workspace = environment.get("GITHUB_WORKSPACE", "")
    require(bool(workspace) and source.is_absolute() and source.resolve(strict=True) == Path(workspace).resolve(strict=True), "source root differs from trusted workspace")
    require(git_value(source, "HEAD") == sha, "checkout differs from trusted source")
    clean_checkout(source)
    tree = git_value(source, "HEAD^{tree}")
    require(re.fullmatch("[a-f0-9]{40}", tree) is not None, "invalid checkout tree")
    run_id = environment.get("GITHUB_RUN_ID", "")
    attempt = environment.get("GITHUB_RUN_ATTEMPT", "")
    require(re.fullmatch("[1-9][0-9]*", run_id) is not None, "invalid signing run ID")
    require(re.fullmatch("[1-9][0-9]*", attempt) is not None, "invalid signing attempt")
    source_value: JsonObject = {"sha": sha, "tree": tree}
    signing: JsonObject = {"run_id": int(run_id), "run_attempt": int(attempt), "event": "workflow_dispatch", "branch": "main", "head_sha": sha}
    return {"schema_version": 1, "purpose": "verification_only", "release_eligible": False, "repository": REPOSITORY, "source": source_value, "signing": signing, "architecture": architecture}


def collection(api: ApiReader, endpoint: str, field: str) -> list[JsonObject]:
    rows: list[JsonObject] = []
    count = 0
    for page in range(1, 11):
        separator = "&" if "?" in endpoint else "?"
        result = api.get(f"{endpoint}{separator}per_page=100&page={page}")
        total = integer(result.get("total_count"), "total_count", minimum=0)
        require(total <= MAX_RECORDS, "API inventory exceeded bounded capacity")
        require(page == 1 or total == count, "API inventory count changed")
        count = total
        values = result.get(field)
        require(isinstance(values, list), f"invalid inventory: {field}")
        if not isinstance(values, list):
            raise SigningInputError(f"invalid inventory: {field}")
        rows.extend(object_value(value, field) for value in values)
        require(len(rows) <= total, "API inventory contains excess rows")
        if len(rows) == total:
            require(len({integer(row.get("id"), "id") for row in rows}) == len(rows), "duplicate API record ID")
            return rows
        require(len(values) == 100, "API inventory was truncated")
    raise SigningInputError("API inventory exceeded ten pages")


def verified_run(api: ApiReader, sha: str) -> JsonObject:
    workflow = api.get(f"{API_ROOT}/workflows/release.yml")
    require(workflow.get("path") == BUILD_PATH and workflow.get("state") == "active", "maintained Build workflow unavailable")
    workflow_id = integer(workflow.get("id"), "workflow_id")
    runs = collection(api, f"{API_ROOT}/workflows/{workflow_id}/runs?head_sha={sha}&event=push&branch=main", "workflow_runs")
    require(bool(runs), "no exact-source maintained Build run")
    numbers = [integer(run.get("run_number"), "run_number") for run in runs]
    require(len(set(numbers)) == len(numbers), "ambiguous exact-source Build history")
    chosen = runs[numbers.index(max(numbers))]
    run = api.get(f"{API_ROOT}/runs/{integer(chosen.get('id'), 'run_id')}")
    require(run.get("id") == chosen.get("id") and run.get("run_attempt") == chosen.get("run_attempt"), "Build attempt changed")
    require(object_value(run.get("repository"), "repository").get("full_name") == REPOSITORY, "producer repository mismatch")
    expected = {"head_sha": sha, "head_branch": "main", "event": "push", "path": BUILD_PATH, "workflow_id": workflow_id, "status": "completed", "conclusion": "success"}
    require(all(run.get(key) == value for key, value in expected.items()), "latest exact-source Build did not succeed")
    integer(run.get("run_attempt"), "run_attempt")
    return run


def latest_jobs(api: ApiReader, run: JsonObject) -> dict[str, JsonObject]:
    run_id = integer(run.get("id"), "run_id")
    attempt = integer(run.get("run_attempt"), "run_attempt")
    jobs = collection(api, f"{API_ROOT}/runs/{run_id}/jobs?filter=all", "jobs")
    selected: dict[str, JsonObject] = {}
    seen: set[tuple[str, int]] = set()
    for job in jobs:
        name = text(job.get("name"), "job.name")
        job_attempt = integer(job.get("run_attempt"), "job.run_attempt")
        expected = {"run_id": run_id, "head_sha": run.get("head_sha"), "head_branch": "main", "workflow_name": "Build and Release", "run_url": f"https://api.github.com{API_ROOT}/runs/{run_id}"}
        require(all(job.get(key) == value for key, value in expected.items()) and job_attempt <= attempt, "job source/attempt mismatch")
        require((name, job_attempt) not in seen, "ambiguous job execution")
        seen.add((name, job_attempt))
        prior = selected.get(name)
        if prior is None or integer(prior.get("run_attempt"), "prior attempt") < job_attempt:
            selected[name] = job
    return selected


def native_job(jobs: dict[str, JsonObject], architecture: str) -> JsonObject:
    for token in (", windows,", ", linux,", ", macos-arm64,", ", macos-x86_64,"):
        matches = [job for name, job in jobs.items() if name.startswith("build (") and token in name]
        require(len(matches) == 1 and matches[0].get("status") == "completed" and matches[0].get("conclusion") == "success", "all four native builds must succeed")
    token = ", macos-arm64," if architecture == "arm64" else ", macos-x86_64,"
    job = next(job for name, job in jobs.items() if name.startswith("build (") and token in name)
    steps = job.get("steps")
    require(isinstance(steps, list), "native steps unavailable")
    if not isinstance(steps, list):
        raise SigningInputError("native steps unavailable")
    required = {"Verify native macOS build runtime", "Install and verify dependencies", "Verify native macOS GUI lifecycle tests", "Verify packaged macOS GUI", "Upload macOS artifacts", "Upload macOS build proof"}
    successful = {text(step.get("name"), "step.name") for value in steps if (step := object_value(value, "step")).get("status") == "completed" and step.get("conclusion") == "success"}
    require(required <= successful, "required native producer step failed or missing")
    return job


def artifact_record(rows: list[JsonObject], name: str, run: JsonObject, job: JsonObject, *, cap: int = MAX_ARCHIVE_BYTES) -> JsonObject:
    matches = [row for row in rows if row.get("name") == name]
    require(len(matches) == 1, "missing or ambiguous input artifact")
    artifact = matches[0]
    require(artifact.get("expired") is False, "input artifact expired")
    producer = object_value(artifact.get("workflow_run"), "artifact.workflow_run")
    require(producer.get("id") == run.get("id") and producer.get("head_sha") == run.get("head_sha") and producer.get("head_branch") == "main", "artifact producer mismatch")
    size = integer(artifact.get("size_in_bytes"), "artifact.size")
    require(size <= cap, "input artifact exceeded byte cap")
    digest = text(artifact.get("digest"), "artifact.digest")
    require(re.fullmatch("sha256:[a-f0-9]{64}", digest) is not None, "input digest unavailable")
    created = text(artifact.get("created_at"), "artifact.created_at")
    require(text(job.get("started_at"), "job.started_at") <= created <= text(job.get("completed_at"), "job.completed_at"), "artifact outside selected native job")
    return {"id": integer(artifact.get("id"), "artifact.id"), "name": name, "size": size, "digest": digest, "producer_run_id": integer(run.get("id"), "run_id"), "producer_run_attempt": integer(job.get("run_attempt"), "native attempt")}


def selection(api: ApiReader, trusted: JsonObject) -> JsonObject:
    source = object_value(trusted.get("source"), "source")
    run = verified_run(api, text(source.get("sha"), "source.sha"))
    architecture = text(trusted.get("architecture"), "architecture")
    job = native_job(latest_jobs(api, run), architecture)
    run_id = integer(run.get("id"), "run_id")
    job_attempt = integer(job.get("run_attempt"), "native attempt")
    name = "macos-arm64" if architecture == "arm64" else "macos-x86_64"
    rows = collection(api, f"{API_ROOT}/runs/{run_id}/artifacts", "artifacts")
    unsigned = artifact_record(rows, f"GM2Godot-{name}", run, job)
    proof = artifact_record(rows, f"GM2Godot-{name}-proof-{run_id}-{job_attempt}", run, job, cap=MAX_PROOF_ARCHIVE_BYTES)
    producer: JsonObject = {"run_id": run_id, "run_attempt": integer(run.get("run_attempt"), "run_attempt"), "workflow_id": integer(run.get("workflow_id"), "workflow_id"), "event": "push", "branch": "main", "head_sha": source.get("sha")}
    context = dict(trusted)
    context.update({"producer": producer, "unsigned_artifact": unsigned, "proof_artifact": proof})
    native_identity: JsonObject = {key: job.get(key) for key in ("id", "name", "run_id", "run_attempt", "head_sha", "started_at", "completed_at", "status", "conclusion")}
    return {"context": context, "native_job": native_identity}


def file_identity(status: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return status.st_dev, status.st_ino, status.st_mode, status.st_nlink, status.st_size, status.st_mtime_ns, status.st_ctime_ns


def directory_identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def require_regular_input(status: os.stat_result, cap: int) -> None:
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1 and status.st_size <= cap, "input body is not a bounded regular owned file")


@contextmanager
def input_stream(path: Path, cap: int) -> Generator[BinaryIO, None, None]:
    with ExitStack() as resources:
        parent = path.parent.stat()
        parent_descriptor: int | None = None
        stream: BinaryIO
        if os.name == "posix":
            parent_descriptor = os.open(path.parent.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            resources.callback(os.close, parent_descriptor)
            require(directory_identity(os.fstat(parent_descriptor)) == directory_identity(parent), "input parent changed before open")
            before = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            require_regular_input(before, cap)
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent_descriptor)
            resources.callback(os.close, descriptor)
            stream = resources.enter_context(BufferedReader(FileIO(descriptor, "rb", closefd=False)))
        else:
            # Ordinary source controls and portable transfer tests also use this
            # reader. Their opened descriptor must match the regular path entry.
            before = path.lstat()
            require_regular_input(before, cap)
            stream = resources.enter_context(path.open("rb"))
        require(file_identity(os.fstat(stream.fileno())) == file_identity(before), "input descriptor differs from path entry")
        yield stream
        require(file_identity(os.fstat(stream.fileno())) == file_identity(before) and file_identity(path.lstat()) == file_identity(before), "input body changed during read")
        require(directory_identity(path.parent.stat()) == directory_identity(parent), "input parent changed during read")
        if os.name == "posix":
            require(file_identity(os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)) == file_identity(before), "anchored input entry changed during read")


def stream_digest(stream: BinaryIO, cap: int) -> tuple[int, str]:
    stream.seek(0)
    digest = hashlib.sha256()
    count = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        count += len(chunk)
        require(count <= cap, "input body exceeded byte cap")
        digest.update(chunk)
    require(count == os.fstat(stream.fileno()).st_size, "input body changed during read")
    return count, digest.hexdigest()


def file_digest(path: Path, cap: int) -> tuple[int, str]:
    with input_stream(path, cap) as stream:
        return stream_digest(stream, cap)


def verify_digest(body: tuple[int, str], record: JsonObject) -> None:
    size, digest = body
    require(record.get("size") == size and record.get("digest") == f"sha256:{digest}", "downloaded original artifact digest mismatch")


def verify_archive(path: Path, record: JsonObject) -> None:
    verify_digest(file_digest(path, MAX_ARCHIVE_BYTES), record)


@contextmanager
def verified_archive(path: Path, cap: int, record: JsonObject | None) -> Generator[zipfile.ZipFile, None, None]:
    with input_stream(path, cap) as stream:
        body = stream_digest(stream, cap)
        if record is not None:
            verify_digest(body, record)
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            yield archive
        require(stream_digest(stream, cap) == body, "archive body changed during parsing")


def storage_location(location: str) -> tuple[str, str]:
    require(len(location) <= 8192 and not any(character in location for character in "\r\n"), "invalid artifact storage redirect")
    parsed = urlsplit(location)
    require(parsed.scheme == "https" and parsed.username is None and parsed.password is None and parsed.port is None and not parsed.fragment, "artifact storage redirect is not plain HTTPS")
    host = parsed.hostname or ""
    require(re.fullmatch(r"productionresultssa[a-z0-9]*\.blob\.core\.windows\.net", host) is not None, "artifact storage host is outside reviewed policy")
    require(parsed.path.startswith("/actions-results/") and bool(parsed.query), "artifact storage resource is outside reviewed policy")
    return host, parsed.path + "?" + parsed.query


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    require(value > 0, "artifact transfer deadline expired")
    return min(value, 15.0)


def https_connection(host: str, deadline: float) -> HTTPSConnection:
    context = create_default_context()
    context.minimum_version = TLSVersion.TLSv1_2
    return HTTPSConnection(host, timeout=remaining(deadline), context=context)


def artifact_location(artifact_id: int, token: str, deadline: float) -> tuple[str, str]:
    require(bool(token) and not any(character in token for character in "\r\n"), "valid read-only Actions token required")
    connection = https_connection("api.github.com", deadline)
    try:
        connection.request("GET", f"{API_ROOT}/artifacts/{artifact_id}/zip", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "GM2Godot-signing-verification"})
        response = connection.getresponse()
        require(response.status == 302, "artifact API did not provide expected storage redirect")
        location = response.getheader("Location")
        require(isinstance(location, str), "artifact storage redirect unavailable")
        if not isinstance(location, str):
            raise SigningInputError("artifact storage redirect unavailable")
        return storage_location(location)
    finally:
        connection.close()


def download_body(record: JsonObject, token: str, destination: Path) -> None:
    deadline = time.monotonic() + 600.0
    host, target = artifact_location(integer(record.get("id"), "artifact.id"), token, deadline)
    expected_size = integer(record.get("size"), "artifact.size")
    require(expected_size <= MAX_ARCHIVE_BYTES, "artifact exceeds transfer byte cap")
    connection = https_connection(host, deadline)
    try:
        # This is a new origin and a new request: never forward Authorization,
        # cookies, the GitHub token, or the confidential signed URL to logs.
        connection.request("GET", target, headers={"Accept": "application/octet-stream", "User-Agent": "GM2Godot-signing-verification"})
        response = connection.getresponse()
        require(response.status == 200, "artifact storage transfer did not succeed")
        count = 0
        with os.fdopen(os.open(destination, PRIVATE_FILE_FLAGS, 0o600), "wb") as stream:
            while True:
                remaining(deadline)
                chunk = response.read1(min(65536, expected_size + 1 - count))
                remaining(deadline)
                if not chunk:
                    break
                count += len(chunk)
                require(count <= expected_size, "artifact storage transfer exceeded API size")
                stream.write(chunk)
        require(count == expected_size, "artifact storage transfer is incomplete")
    finally:
        connection.close()
    verify_archive(destination, record)


def archive_members(archive: zipfile.ZipFile, expected: set[str], cap: int) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    require(len(members) == len(expected) and {member.filename for member in members} == expected, "artifact namespace mismatch")
    require(all(not member.is_dir() and not member.flag_bits & 1 and member.create_system == 3 and stat.S_ISREG(member.external_attr >> 16) and 0 < member.file_size <= cap for member in members), "artifact member is not a bounded regular file")
    return members


def extract_payload(archive_path: Path, destination: Path, architecture: str, *, record: JsonObject | None = None) -> tuple[Path, Path]:
    name = "macos-arm64" if architecture == "arm64" else "macos-x86_64"
    expected = {f"GM2Godot-{name}.zip", f"GM2Godot-{name}.dmg"}
    destination.mkdir(mode=0o700)
    require(stat.S_IMODE(destination.stat().st_mode) == 0o700, "input directory permissions are not private")
    with verified_archive(archive_path, MAX_ARCHIVE_BYTES, record) as archive:
        for member in archive_members(archive, expected, MAX_ARCHIVE_BYTES):
            with archive.open(member) as source, os.fdopen(os.open(destination / member.filename, PRIVATE_FILE_FLAGS, 0o600), "wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
    return destination / f"GM2Godot-{name}.zip", destination / f"GM2Godot-{name}.dmg"


def verify_runtime(value: JsonValue, architecture: str) -> None:
    runtime = object_value(value, "runtime")
    expected = {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin", "system": "Darwin", "machine": architecture}
    require(runtime.get("translated") is False, "original native runtime is translated or unproven")
    require(all(runtime.get(key) == wanted for key, wanted in expected.items()), "original native runtime mismatch")


def verify_native_report(report: JsonObject, architecture: str) -> None:
    require(integer(report.get("schema_version"), "native schema") == 1 and report.get("successful") is True and integer(report.get("tests_run"), "native count") == 7, "original native lifecycle gate did not pass")
    require(all(integer(report.get(key), key, minimum=0) == 0 for key in ("skips", "failures", "errors", "expected_failures", "unexpected_successes")), "original native lifecycle gate has adverse outcomes")
    selected: list[JsonValue] = [f"__main__.NativeLifecycleTests.{method}" for method in NATIVE_METHODS]
    require(all(report.get(key) == selected for key in ("selected", "started", "completed")), "original native lifecycle selection mismatch")
    verify_runtime(report.get("runtime"), architecture)


def verify_original_proof(path: Path, unsigned_zip: Path, architecture: str, source: Path, *, record: JsonObject | None = None) -> JsonObject:
    from scripts.verify_macos_bundle_metadata import load_source_policy

    name = "macos-arm64" if architecture == "arm64" else "macos-x86_64"
    expected = {f"release-{name}-{kind}.json" for kind in ("bootstrap", "dependencies", "native-tests", "gui")}
    with verified_archive(path, MAX_PROOF_ARCHIVE_BYTES, record) as archive:
        archive_members(archive, expected, MAX_PROOF_BYTES)
        native = parse_api_json(archive.read(f"release-{name}-native-tests.json"))
        gui = parse_api_json(archive.read(f"release-{name}-gui.json"))
    verify_native_report(native, architecture)
    require(integer(gui.get("schema_version"), "GUI schema") == 1 and gui.get("successful") is True, "original packaged GUI did not pass")
    verify_runtime(gui.get("runtime"), architecture)
    require(gui.get("zip_sha256") == file_digest(unsigned_zip, MAX_ARCHIVE_BYTES)[1], "unsigned ZIP differs from original GUI proof")
    require(gui.get("source_policy") == load_source_policy(source), "original bundle policy differs from trusted source")
    return {"native_lifecycle": native, "unsigned_gui": gui}


def owned_path(value: Path, environment: Mapping[str, str], *, existing_selection: bool = False) -> Path:
    require(os.name == "posix", "private acquisition paths require POSIX ownership")
    raw_temp = environment.get("RUNNER_TEMP", "")
    require(bool(raw_temp) and value.is_absolute(), "owned path must be absolute")
    declared_temp = Path(raw_temp)
    temp = declared_temp.resolve(strict=True)
    require(temp.is_dir() and temp.stat().st_uid == os.getuid(), "runner temporary directory is not owned")
    require(value.parent == declared_temp and value.parent.resolve(strict=True) == temp, "path must be directly inside runner temporary directory")
    require(not value.is_symlink(), "owned path is a symlink")
    if existing_selection:
        status = value.lstat()
        require(stat.S_ISREG(status.st_mode) and status.st_uid == os.getuid() and status.st_nlink == 1 and stat.S_IMODE(status.st_mode) == 0o600 and status.st_size <= 5 * 1024 * 1024, "selection is not a private bounded owned file")
    else:
        require(not value.exists(), "owned output already exists")
    return value


def read_private_json(path: Path) -> JsonObject:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600, "receipt is not a private owned file")
        body = stream.read(5 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    require(len(body) <= 5 * 1024 * 1024 and len(body) == before.st_size and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "private receipt changed or exceeded byte cap")
    return parse_api_json(body)


def verify_dependency_report(report: JsonObject, bootstrap: JsonObject, architecture: str, source: Path) -> None:
    require(integer(report.get("schema_version"), "dependency schema") == 2 and report.get("status") == "verified" and report.get("errors") == [] and report.get("mode") == "subset", "fresh dependency verification did not pass")
    require(report.get("required") == ["markdown2", "pillow", "pip", "pyinstaller", "pyside6", "requests"], "fresh dependency subset mismatch")
    projection: JsonObject = {key: bootstrap.get(key) for key in ("policy", "state", "source", "constraints", "source_transition")}
    require(report.get("bootstrap") == projection, "fresh dependency/bootstrap projections disagree")
    constraint = object_value(report.get("constraint"), "dependency constraint")
    require(constraint.get("sha256") == hashlib.sha256((source / "constraints/requirements-macos-py312.lock").read_bytes()).hexdigest(), "fresh dependency constraint differs from source")
    expected = object_value(report.get("expected_environment"), "expected environment")
    observation = object_value(report.get("observation"), "dependency observation")
    observed = object_value(observation.get("environment"), "observed environment")
    runtime = {"implementation_name": "cpython", "python_full_version": "3.12.10", "python_version": "3.12", "sys_platform": "darwin", "platform_machine": architecture}
    require(all(expected.get(key) == value and observed.get(key) == value for key, value in runtime.items()), "fresh dependency runtime mismatch")
    pins = object_value(object_value(bootstrap.get("source"), "bootstrap source").get("pins"), "bootstrap pins")
    pip_version = text(pins.get("pip"), "bootstrap pip version")
    require(bool(pip_version) and expected.get("pip_version") == observation.get("pip_version") == pip_version, "fresh pip version differs from bootstrap")
    for name in ("pip_check", "pip_inspect"):
        command = object_value(observation.get(name), name)
        require(integer(command.get("returncode"), name, minimum=0) == 0, "fresh dependency command failed")


def verify_prechecks(native_path: Path, dependency_path: Path, bootstrap_path: Path, architecture: str, source: Path) -> JsonObject:
    native = read_private_json(native_path)
    bootstrap = read_private_json(bootstrap_path)
    dependency = read_private_json(dependency_path)
    verify_native_report(native, architecture)
    require(integer(bootstrap.get("schema_version"), "bootstrap schema") == 1 and bootstrap.get("status") == "verified" and bootstrap.get("errors") == [] and bootstrap.get("policy") == "stable" and bootstrap.get("state") == "stable", "fresh bootstrap verification did not pass")
    source_row = object_value(bootstrap.get("source"), "bootstrap source")
    require(source_row.get("sha256") == hashlib.sha256((source / "requirements-bootstrap.txt").read_bytes()).hexdigest(), "fresh bootstrap differs from source")
    constraints = bootstrap.get("constraints")
    require(isinstance(constraints, list) and len(constraints) == 1, "fresh bootstrap constraint inventory mismatch")
    if not isinstance(constraints, list):
        raise SigningInputError("fresh bootstrap constraints unavailable")
    require(object_value(constraints[0], "bootstrap constraint").get("sha256") == hashlib.sha256((source / "constraints/requirements-macos-py312.lock").read_bytes()).hexdigest(), "fresh bootstrap constraint differs from source")
    verify_dependency_report(dependency, bootstrap, architecture, source)
    seals: list[JsonValue] = []
    for name, path in (("native_lifecycle", native_path), ("dependencies", dependency_path), ("bootstrap", bootstrap_path)):
        size, digest = file_digest(path, 5 * 1024 * 1024)
        seals.append({"kind": name, "name": path.name, "size": size, "sha256": digest})
    return {"fresh_verified_precheck_seals": seals}


def write_json(path: Path, value: JsonObject) -> None:
    with os.fdopen(os.open(path, PRIVATE_FILE_FLAGS, 0o600), "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def required_path(value: Path | None, field: str) -> Path:
    if value is None:
        raise SigningInputError(f"missing path: {field}")
    return owned_path(value, os.environ)


class Options(argparse.Namespace):
    mode: str
    source_root: Path
    architecture: str
    selection: Path
    native_proof: Path
    dependency_proof: Path
    bootstrap_proof: Path
    payload_archive: Path | None
    proof_archive: Path | None
    input_root: Path | None
    context: Path | None
    receipt: Path | None


def verify_inputs(api: ApiReader, trusted: JsonObject, saved: JsonObject, payload: Path, proof: Path, inputs: Path, source: Path) -> tuple[JsonObject, JsonObject]:
    before = selection(api, trusted)
    require(before == saved, "source/producer/artifact selection changed before verification")
    context = object_value(saved.get("context"), "context")
    unsigned_record = object_value(context.get("unsigned_artifact"), "unsigned_artifact")
    proof_record = object_value(context.get("proof_artifact"), "proof_artifact")
    verify_archive(payload, unsigned_record)
    verify_archive(proof, proof_record)
    architecture = text(trusted.get("architecture"), "architecture")
    unsigned_zip, unsigned_dmg = extract_payload(payload, inputs, architecture, record=unsigned_record)
    evidence = verify_original_proof(proof, unsigned_zip, architecture, source, record=proof_record)
    after = selection(api, trusted)
    require(after == saved, "source/producer/artifact selection changed after verification")
    verify_archive(payload, unsigned_record)
    verify_archive(proof, proof_record)
    receipt: JsonObject = {"schema_version": 1, "purpose": "verification_only", "release_eligible": False, "selection_before": before, "selection_after": after, "input_proof": evidence, "unsigned_zip_sha256": file_digest(unsigned_zip, MAX_ARCHIVE_BYTES)[1], "unsigned_dmg_sha256": file_digest(unsigned_dmg, MAX_ARCHIVE_BYTES)[1]}
    return context, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "check", "fetch"))
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--architecture", required=True, choices=("arm64", "x86_64"))
    parser.add_argument("--selection", required=True, type=Path)
    for name in ("native-proof", "dependency-proof", "bootstrap-proof"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("payload-archive", "proof-archive", "input-root", "context", "receipt"):
        parser.add_argument(f"--{name}", type=Path)
    args = Options()
    parser.parse_args(namespace=args)
    try:
        trusted = trusted_context(args.source_root, args.architecture, os.environ)
        selected_path = owned_path(args.selection, os.environ, existing_selection=args.mode != "plan")
        native_path = owned_path(args.native_proof, os.environ, existing_selection=True)
        dependency_path = owned_path(args.dependency_proof, os.environ, existing_selection=True)
        bootstrap_path = owned_path(args.bootstrap_proof, os.environ, existing_selection=True)
        prechecks = verify_prechecks(native_path, dependency_path, bootstrap_path, args.architecture, args.source_root)
        api = GitHubApi(os.environ.get("GH_TOKEN", ""), Budget(180))
        if args.mode == "plan":
            chosen = selection(api, trusted)
            write_json(selected_path, chosen)
            return 0
        payload = required_path(args.payload_archive, "payload-archive")
        proof = required_path(args.proof_archive, "proof-archive")
        inputs = required_path(args.input_root, "input-root")
        context_path = required_path(args.context, "context")
        receipt_path = required_path(args.receipt, "receipt")
        saved = read_private_json(selected_path)
        if args.mode == "fetch":
            require(selection(api, trusted) == saved, "source selection changed before acquisition")
            context = object_value(saved.get("context"), "context")
            token = os.environ.get("GH_TOKEN", "")
            download_body(object_value(context.get("unsigned_artifact"), "unsigned_artifact"), token, payload)
            download_body(object_value(context.get("proof_artifact"), "proof_artifact"), token, proof)
            api = GitHubApi(token, Budget(180))
        context, receipt = verify_inputs(api, trusted, saved, payload, proof, inputs, args.source_root)
        require(verify_prechecks(native_path, dependency_path, bootstrap_path, args.architecture, args.source_root) == prechecks, "fresh verification prechecks changed during acquisition")
        receipt.update(prechecks)
        write_json(receipt_path, receipt)
        write_json(context_path, context)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, HTTPException, zipfile.BadZipFile) as error:
        reason = str(error) if isinstance(error, SigningInputError) else type(error).__name__
        print(f"Signing inputs rejected: {reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
