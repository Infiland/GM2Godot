"""Protected verification-only Developer ID packaging operations.

Provider attestation belongs to the maintained acquisition planner. This module
checks that attested context against the trusted checkout and current job before
reading credentials; a well-shaped JSON file alone is not provider attestation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import plistlib
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType, TracebackType
from typing import TYPE_CHECKING, BinaryIO, Literal, Never, Protocol, TypeGuard
from uuid import UUID

from src.conversion.json_values import JsonObject, JsonValue, validate_json_value

if TYPE_CHECKING:
    from scripts.verify_macos_bundle_metadata import BundleInspection, VerificationReceipt

type Architecture = Literal["arm64", "x86_64"]

REPOSITORY = "Infiland/GM2Godot"
SECRET_NAMES = (
    "MACOS_DEVELOPER_ID_P12_BASE64",
    "MACOS_DEVELOPER_ID_P12_PASSWORD",
    "APPLE_NOTARY_API_KEY_P8_BASE64",
)
MAX_COMMAND_BYTES = 8 * 1024 * 1024
MAX_CONTEXT_BYTES = 1024 * 1024
MAX_NOTARY_LOG_BYTES = 4 * 1024 * 1024
MAX_GUI_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD_BYTES = 1024 * 1024 * 1024
OPERATION_BUDGET_SECONDS = 3900
CLEANUP_BUDGET_SECONDS = 300
SOURCE_PROBE_TIMEOUT_SECONDS = 15


class SigningFailure(Exception):
    """A safe phase-level failure; never include confidential argv or output."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SigningFailure(message)


def exact_keys(data: JsonObject, names: frozenset[str]) -> None:
    require(frozenset(data) == names, "Unexpected or missing context fields")


def json_object(value: JsonValue) -> JsonObject:
    if isinstance(value, dict):
        return value
    raise SigningFailure("Expected a JSON object")


def text(data: JsonObject, key: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    raise SigningFailure(f"Expected nonempty text field: {key}")


def positive_integer(data: JsonObject, key: str) -> int:
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise SigningFailure(f"Expected positive integer field: {key}")


def sha_text(data: JsonObject, key: str, digits: int = 40) -> str:
    value = text(data, key)
    require(re.fullmatch(rf"[0-9a-f]{{{digits}}}", value) is not None, "Invalid hexadecimal identity")
    return value


def unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def reject_json_constant(_value: str) -> JsonValue:
    raise SigningFailure("Nonfinite JSON number is not permitted")


def canonical_uuid(value: str) -> str:
    identifier = str(UUID(value))
    require(identifier == value.lower(), "Invalid canonical UUID")
    return identifier


def decode_object(body: bytes, label: str) -> JsonObject:
    raw: object = json.loads(body, object_pairs_hook=unique_json_pairs, parse_constant=reject_json_constant)
    return json_object(validate_json_value(raw, source_path=label))


@dataclass(frozen=True)
class FileSeal:
    name: str
    size: int
    sha256: str

    def as_json(self) -> JsonObject:
        return {"name": self.name, "size": self.size, "sha256": self.sha256}


def read_bound_file(path: Path, limit: int) -> tuple[bytes, FileSeal]:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "Expected a direct single-link regular file")
    require(0 < before.st_size <= limit, "Input exceeds its bounded size")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(os.path.samestat(before, opened), "Input binding changed during open")
        body = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        require(len(body) == before.st_size and len(body) <= limit, "Input size changed")
        require((opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "Input changed during read")
        require(os.path.samestat(after, path.lstat()), "Input name changed during read")
    return body, FileSeal(path.name, len(body), hashlib.sha256(body).hexdigest())


def seal_file(path: Path, limit: int = MAX_PAYLOAD_BYTES) -> FileSeal:
    # Streaming avoids a payload-sized in-memory copy while retaining the same
    # descriptor/name/size/time binding checks as the bounded proof reader.
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "Expected a direct single-link payload")
    require(0 < before.st_size <= limit, "Payload exceeds its bounded size")
    digest = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(os.path.samestat(before, opened), "Payload binding changed during open")
        size = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            require(size <= limit, "Payload grew beyond its bounded size")
            digest.update(block)
        after = os.fstat(stream.fileno())
        require(size == before.st_size, "Payload size changed")
        require((opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "Payload changed during read")
        require(os.path.samestat(after, path.lstat()), "Payload name changed during read")
    return FileSeal(path.name, size, digest.hexdigest())


def write_exclusive(path: Path, body: bytes) -> FileSeal:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600), "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        before = os.fstat(stream.fileno())
        require(stream.write(body) == len(body), "Exclusive output write was incomplete")
        stream.flush()
        require(os.path.samestat(before, path.lstat()), "Exclusive output binding changed")
    return FileSeal(path.name, len(body), hashlib.sha256(body).hexdigest())


@dataclass(frozen=True)
class ProducerRun:
    run_id: int
    run_attempt: int
    workflow_id: int
    head_sha: str

    def as_json(self) -> JsonObject:
        return {"run_id": self.run_id, "run_attempt": self.run_attempt, "workflow_id": self.workflow_id, "event": "push", "branch": "main", "head_sha": self.head_sha}


@dataclass(frozen=True)
class SigningRun:
    run_id: int
    run_attempt: int
    head_sha: str

    def as_json(self) -> JsonObject:
        return {"run_id": self.run_id, "run_attempt": self.run_attempt, "event": "workflow_dispatch", "branch": "main", "head_sha": self.head_sha}


@dataclass(frozen=True)
class ArtifactBinding:
    id: int
    name: str
    size: int
    digest: str
    producer_run_id: int
    producer_run_attempt: int


@dataclass(frozen=True)
class SigningContext:
    source_sha: str
    source_tree: str
    producer: ProducerRun
    signing: SigningRun
    architecture: Architecture
    unsigned_artifact: ArtifactBinding
    proof_artifact: ArtifactBinding


def parse_producer(data: JsonObject, source_sha: str) -> ProducerRun:
    exact_keys(data, frozenset({"run_id", "run_attempt", "workflow_id", "event", "branch", "head_sha"}))
    require(text(data, "event") == "push" and text(data, "branch") == "main", "Unsigned producer is not a main push")
    require(sha_text(data, "head_sha") == source_sha, "Unsigned producer source differs")
    return ProducerRun(positive_integer(data, "run_id"), positive_integer(data, "run_attempt"), positive_integer(data, "workflow_id"), source_sha)


def parse_signing(data: JsonObject, source_sha: str) -> SigningRun:
    exact_keys(data, frozenset({"run_id", "run_attempt", "event", "branch", "head_sha"}))
    require(text(data, "event") == "workflow_dispatch" and text(data, "branch") == "main", "Verification is not a main manual run")
    require(sha_text(data, "head_sha") == source_sha, "Signing source differs")
    return SigningRun(positive_integer(data, "run_id"), positive_integer(data, "run_attempt"), source_sha)


def parse_artifact(data: JsonObject, producer: ProducerRun) -> ArtifactBinding:
    exact_keys(data, frozenset({"id", "name", "size", "digest", "producer_run_id", "producer_run_attempt"}))
    digest = text(data, "digest")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None, "Artifact has no exact API SHA256 digest")
    run_id = positive_integer(data, "producer_run_id")
    attempt = positive_integer(data, "producer_run_attempt")
    require(run_id == producer.run_id and attempt <= producer.run_attempt, "Artifact producer/attempt differs")
    return ArtifactBinding(positive_integer(data, "id"), text(data, "name"), positive_integer(data, "size"), digest, run_id, attempt)


def parse_context(data: JsonObject) -> SigningContext:
    exact_keys(data, frozenset({"schema_version", "purpose", "release_eligible", "repository", "source", "producer", "signing", "architecture", "unsigned_artifact", "proof_artifact"}))
    require(positive_integer(data, "schema_version") == 1 and text(data, "repository") == REPOSITORY, "Unknown context schema/repository")
    require(text(data, "purpose") == "verification_only" and data["release_eligible"] is False, "Bootstrap cannot authorize publication")
    source = json_object(data["source"])
    exact_keys(source, frozenset({"sha", "tree"}))
    source_sha, source_tree = sha_text(source, "sha"), sha_text(source, "tree")
    requested = text(data, "architecture")
    if requested == "arm64":
        architecture: Architecture = "arm64"
    elif requested == "x86_64":
        architecture = "x86_64"
    else:
        raise SigningFailure("Unknown native architecture")
    producer = parse_producer(json_object(data["producer"]), source_sha)
    signing = parse_signing(json_object(data["signing"]), source_sha)
    unsigned = parse_artifact(json_object(data["unsigned_artifact"]), producer)
    proof = parse_artifact(json_object(data["proof_artifact"]), producer)
    require(unsigned.id != proof.id and unsigned.producer_run_attempt == proof.producer_run_attempt, "Artifact identities/attempts conflict")
    require(unsigned.name == f"GM2Godot-macos-{architecture}" and proof.name == f"GM2Godot-macos-{architecture}-proof-{producer.run_id}-{unsigned.producer_run_attempt}", "Artifact names differ from source roles")
    return SigningContext(source_sha, source_tree, producer, signing, architecture, unsigned, proof)


@dataclass(frozen=True)
class SigningOptions:
    context_path: Path
    source_root: Path
    unsigned_zip: Path
    unsigned_dmg: Path
    architecture: Architecture
    output_root: Path
    proof_root: Path


def secret_environment_name(name: str) -> bool:
    upper = name.upper()
    return name in SECRET_NAMES or upper.startswith(("GH_", "GITHUB_", "GIT", "SSH_", "ACTIONS_", "APPLE_", "MACOS_DEVELOPER_", "MACOS_SIGNING_", "KEYCHAIN_", "DYLD", "PYTHON")) or any(part in upper for part in ("TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY", "CREDENTIAL"))


def safe_environment(environment: Mapping[str, str]) -> dict[str, str]:
    # Iterate names first: rejected keys are never looked up before the guard.
    result = {name: environment[name] for name in environment if not secret_environment_name(name)}
    result["LC_ALL"] = "C"
    return result


def required_environment(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    require(bool(value), f"Missing required protected setting: {name}")
    return value


def verify_checkout(source: Path, context: SigningContext, environment: Mapping[str, str]) -> None:
    for arguments, expected in ((["rev-parse", "HEAD"], context.source_sha), (["rev-parse", "HEAD^{tree}"], context.source_tree), (["status", "--porcelain", "--untracked-files=normal"], "")):
        result = subprocess.run(["git", "-C", str(source), *arguments], check=True, capture_output=True, text=True, timeout=SOURCE_PROBE_TIMEOUT_SECONDS, env=safe_environment(environment))
        require(result.stdout.strip() == expected, "Trusted source HEAD/tree or tracked worktree/index changed")


def trusted_source(options: SigningOptions, context: SigningContext, environment: Mapping[str, str]) -> Path:
    require(required_environment(environment, "GITHUB_REPOSITORY") == REPOSITORY and required_environment(environment, "GITHUB_REF") == "refs/heads/main", "Verification requires this repository's trusted main")
    require(required_environment(environment, "GITHUB_EVENT_NAME") == "workflow_dispatch", "Verification requires a manual main run")
    require(required_environment(environment, "GITHUB_SHA") == context.source_sha and required_environment(environment, "GITHUB_RUN_ID") == str(context.signing.run_id) and required_environment(environment, "GITHUB_RUN_ATTEMPT") == str(context.signing.run_attempt), "Current verification run differs from acquired context")
    workspace = Path(required_environment(environment, "GITHUB_WORKSPACE")).resolve(strict=True)
    source = options.source_root.resolve(strict=True)
    require(source == workspace and not options.source_root.is_symlink() and source.is_dir(), "Source must be the direct trusted workspace")
    verify_checkout(source, context, environment)
    require(options.architecture == context.architecture, "Requested architecture differs from acquired context")
    return source


def fresh_directory_path(path: Path, runner_temp: Path, source: Path) -> Path:
    require(path.is_absolute(), "Output/proof root must be absolute")
    candidate = path.resolve(strict=False)
    require(candidate != runner_temp and candidate.is_relative_to(runner_temp), "Output/proof must be owned beneath RUNNER_TEMP")
    require(not candidate.is_relative_to(source) and not source.is_relative_to(candidate), "Artifacts/proofs cannot replace importable source")
    require(not candidate.exists() and not candidate.is_symlink(), "Output/proof root must be fresh")
    return candidate


def prepare_roots(options: SigningOptions, source: Path, environment: Mapping[str, str]) -> tuple[Path, Path, Path]:
    runner_temp = Path(required_environment(environment, "RUNNER_TEMP")).resolve(strict=True)
    require(runner_temp.is_dir(), "RUNNER_TEMP is not a physical directory")
    output = fresh_directory_path(options.output_root, runner_temp, source)
    proof = fresh_directory_path(options.proof_root, runner_temp, source)
    require(not output.is_relative_to(proof) and not proof.is_relative_to(output), "Output and proof roots must be disjoint")
    require(output.parent.is_dir() and proof.parent.is_dir(), "Output/proof parents must already exist")
    for path in (options.context_path, options.unsigned_zip, options.unsigned_dmg):
        require(not path.resolve(strict=True).is_relative_to(source), "Input artifacts/context must stay outside importable source")
    output.mkdir(mode=0o700)
    proof.mkdir(mode=0o700)
    return runner_temp, output, proof


@dataclass(frozen=True)
class Credentials:
    p12: bytes = field(repr=False)
    p12_password: str = field(repr=False)
    p8: bytes = field(repr=False)
    identity_sha1: str
    team_id: str
    notary_key_id: str
    notary_issuer_id: str
    redactions: tuple[bytes, ...] = field(repr=False)


def credentials(environment: Mapping[str, str]) -> Credentials:
    values = tuple(required_environment(environment, name) for name in SECRET_NAMES)
    identity = required_environment(environment, "MACOS_SIGNING_IDENTITY_SHA1").upper()
    team = required_environment(environment, "APPLE_TEAM_ID")
    key = required_environment(environment, "APPLE_NOTARY_KEY_ID")
    issuer = required_environment(environment, "APPLE_NOTARY_ISSUER_ID")
    require(re.fullmatch(r"[0-9A-F]{40}", identity) is not None and re.fullmatch(r"[A-Z0-9]{10}", team) is not None, "Invalid Developer ID identity/team")
    require(re.fullmatch(r"[A-Z0-9]{10}", key) is not None, "Invalid team notarization key ID")
    require(str(UUID(issuer)) == issuer.lower(), "Invalid team notarization issuer UUID")
    p12, p8 = base64.b64decode(values[0], validate=True), base64.b64decode(values[2], validate=True)
    require(bool(p12) and bool(p8), "Empty protected credential")
    tokens = tuple(environment[name].encode() for name in environment if any(part in name.upper() for part in ("TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY", "CREDENTIAL")) and environment[name])
    redactions = tuple(value.encode() for value in values) + (p12, p8) + tokens
    return Credentials(p12, values[1], p8, identity, team, key, issuer, redactions)


class OperationBudgets:
    def __init__(self) -> None:
        self.operation_deadline = time.monotonic() + OPERATION_BUDGET_SECONDS
        self.cleanup_deadline: float | None = None

    def timeout(self, requested: int, cleanup: bool) -> int:
        now = time.monotonic()
        if cleanup:
            if self.cleanup_deadline is None:
                self.cleanup_deadline = now + CLEANUP_BUDGET_SECONDS
            deadline = self.cleanup_deadline
        else:
            deadline = self.operation_deadline
        remaining = deadline - now
        require(requested > 0 and remaining > 0, "Protected operation deadline exhausted")
        return min(requested, math.ceil(remaining))


class WorkerProcess(Protocol):
    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


def stop_metadata_worker(process: WorkerProcess, budgets: OperationBudgets, primary: BaseException) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=budgets.timeout(120, True))
    except (subprocess.TimeoutExpired, SigningFailure):
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=budgets.timeout(30, True))
        except (subprocess.TimeoutExpired, SigningFailure, OSError):
            raise SigningFailure("Metadata worker forcibly stopped; verifier cleanup and reap remain unconfirmed") from primary
        raise SigningFailure("Metadata worker forcibly stopped; verifier cleanup remains unconfirmed") from primary


def supervise_metadata_worker(process: WorkerProcess, timeout: int, budgets: OperationBudgets) -> int:
    try:
        return process.wait(timeout=timeout)
    except BaseException as primary:
        try:
            stop_metadata_worker(process, budgets, primary)
        except OSError:
            raise SigningFailure("Metadata worker termination failed; verifier cleanup remains unconfirmed") from primary
        raise


class CommandExecutor(Protocol):
    def execute(self, argv: Sequence[str], *, stdout: BinaryIO, stderr: BinaryIO, timeout: int, environment: Mapping[str, str], cwd: Path | None, cleanup_budget: OperationBudgets | None = None) -> int: ...


class SubprocessExecutor:
    def execute(self, argv: Sequence[str], *, stdout: BinaryIO, stderr: BinaryIO, timeout: int, environment: Mapping[str, str], cwd: Path | None, cleanup_budget: OperationBudgets | None = None) -> int:
        if cleanup_budget is not None:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=environment, cwd=cwd)
            return supervise_metadata_worker(process, timeout, cleanup_budget)
        return subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout, env=environment, cwd=cwd, check=False).returncode


@dataclass(frozen=True)
class CommandResult:
    stdout: bytes
    stderr: bytes
    returncode: int
    timed_out: bool


class Commands:
    def __init__(self, executor: CommandExecutor, environment: Mapping[str, str], proof: Path, redactions: tuple[bytes, ...]) -> None:
        self.executor = executor
        self.environment = safe_environment(environment)
        self.proof = proof
        self.redactions = redactions
        self.sequence = 0
        self.budgets = OperationBudgets()

    def operation_timeout(self, requested: int, cleanup: bool) -> int:
        return self.budgets.timeout(requested, cleanup)

    def redact(self, body: bytes) -> bytes:
        for secret in sorted(set(self.redactions), key=len, reverse=True):
            body = body.replace(secret, b"[REDACTED]")
        return body

    def result(self, argv: Sequence[str], label: str, *, timeout: int = 120, confidential: bool = False, cleanup: bool = False, metadata_worker: bool = False, cwd: Path | None = None) -> CommandResult:
        require(re.fullmatch(r"[a-z][a-z-]*", label) is not None, "Invalid operation label")
        effective_timeout = self.operation_timeout(timeout, cleanup)
        timed_out = False
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                status = self.executor.execute(argv, stdout=stdout, stderr=stderr, timeout=effective_timeout, environment=self.environment, cwd=cwd, cleanup_budget=self.budgets if metadata_worker else None)
            except subprocess.TimeoutExpired:
                status, timed_out = -1, True
            except (OSError, subprocess.SubprocessError):
                raise SigningFailure(f"Protected operation could not start: {label}") from None
            require(stdout.tell() <= MAX_COMMAND_BYTES and stderr.tell() <= MAX_COMMAND_BYTES, "Operation output exceeds bounded log size")
            stdout.seek(0)
            stderr.seek(0)
            output, errors = self.redact(stdout.read()), self.redact(stderr.read())
        if not confidential:
            self.sequence += 1
            for suffix, body in (("stdout", output), ("stderr", errors)):
                write_exclusive(self.proof / f"{self.sequence:03d}-{label}-{suffix}.log", body)
        return CommandResult(output, errors, status, timed_out)

    def run(self, argv: Sequence[str], label: str, *, timeout: int = 120, confidential: bool = False, cleanup: bool = False, metadata_worker: bool = False, combined: bool = False, cwd: Path | None = None) -> bytes:
        result = self.result(argv, label, timeout=timeout, confidential=confidential, cleanup=cleanup, metadata_worker=metadata_worker, cwd=cwd)
        require(result.returncode == 0 and not result.timed_out, f"Protected operation failed: {label}")
        return result.stdout + result.stderr if combined else result.stdout


class PrivateWork:
    def __init__(self, runner_temp: Path) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="gm2godot-signing-", dir=runner_temp))
        self.binding = self.path.lstat()
        require(stat.S_ISDIR(self.binding.st_mode) and stat.S_IMODE(self.binding.st_mode) == 0o700, "Private signing work is not owned0700")
        self.removed = False

    def verify(self) -> None:
        require(os.path.samestat(self.binding, self.path.lstat()), "Private signing directory binding changed")

    def cleanup(self, primary: BaseException | None) -> None:
        try:
            self.verify()
            require(shutil.rmtree.avoids_symlink_attacks, "Private cleanup requires descriptor-safe rmtree")
            shutil.rmtree(self.path)
            require(not self.path.exists() and not self.path.is_symlink(), "Private signing work remains")
            self.removed = True
        except BaseException as error:
            if primary is not None:
                primary.add_note(f"Private signing cleanup failed ({type(error).__name__})")
                raise primary from error
            raise SigningFailure("Private signing cleanup failed") from error

    def __enter__(self) -> PrivateWork:
        return self

    def __exit__(self, _exception_type: type[BaseException] | None, exception: BaseException | None, _traceback: TracebackType | None) -> None:
        self.cleanup(exception)


class Keychain:
    def __init__(self, work: PrivateWork, commands: Commands, private: Credentials) -> None:
        self.work, self.commands, self.private = work, commands, private
        self.path = work.path / "signing.keychain-db"
        self.password = secrets.token_urlsafe(32)
        commands.redactions += (self.password.encode(),)
        self.attempted = False
        self.deleted = False

    def create(self) -> None:
        self.work.verify()
        require(not self.path.exists() and not self.path.is_symlink(), "Owned keychain path is occupied")
        self.attempted = True
        self.commands.run(["/usr/bin/security", "create-keychain", "-p", self.password, str(self.path)], "create-keychain", confidential=True)
        self.commands.run(["/usr/bin/security", "set-keychain-settings", "-lut", "3600", str(self.path)], "keychain-settings", confidential=True)
        self.commands.run(["/usr/bin/security", "unlock-keychain", "-p", self.password, str(self.path)], "unlock-keychain", confidential=True)

    def import_identity(self) -> None:
        p12 = self.work.path / "certificate.p12"
        write_exclusive(p12, self.private.p12)
        self.commands.run(["/usr/bin/security", "import", str(p12), "-k", str(self.path), "-P", self.private.p12_password, "-T", "/usr/bin/codesign"], "import-identity", confidential=True)
        p12.unlink()
        self.commands.run(["/usr/bin/security", "set-key-partition-list", "-S", "apple-tool:,apple:", "-k", self.password, str(self.path)], "partition-list", confidential=True)
        result = self.commands.run(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning", str(self.path)], "find-identity").decode("utf-8", errors="strict")
        pattern = rf'^\s*\d+\) {re.escape(self.private.identity_sha1)} "Developer ID Application: .+ \({self.private.team_id}\)"$'
        require(len(re.findall(pattern, result, re.MULTILINE | re.IGNORECASE)) == 1, "Exact Developer ID private-key identity unavailable")

    def cleanup(self, primary: BaseException | None) -> None:
        try:
            self.work.verify()
            if self.attempted and (self.path.exists() or self.path.is_symlink()):
                require(stat.S_ISREG(self.path.lstat().st_mode), "Owned keychain path changed kind")
                self.commands.run(["/usr/bin/security", "delete-keychain", str(self.path)], "delete-keychain", confidential=True, cleanup=True)
            require(not self.path.exists() and not self.path.is_symlink(), "Owned keychain remains")
            self.deleted = True
        except BaseException as error:
            if primary is not None:
                primary.add_note(f"Owned keychain cleanup failed ({type(error).__name__})")
                raise primary from error
            raise SigningFailure("Owned keychain cleanup failed") from error

    def __enter__(self) -> Keychain:
        try:
            self.create()
            self.import_identity()
            return self
        except BaseException as primary:
            self.cleanup(primary)
            raise

    def __exit__(self, _exception_type: type[BaseException] | None, exception: BaseException | None, _traceback: TracebackType | None) -> None:
        self.cleanup(exception)


class BundleOperations:
    """Lazy real maintained APIs; first call occurs after trusted source guards."""

    def policy(self, source: Path) -> dict[str, str]:
        from scripts import verify_macos_bundle_metadata as metadata
        try:
            return metadata.load_source_policy(source)
        except metadata.MetadataVerificationError:
            raise SigningFailure("Maintained source policy verification failed") from None

    def zip(self, path: Path, policy: Mapping[str, str], architecture: str) -> BundleInspection:
        from scripts import verify_macos_bundle_metadata as metadata
        try:
            return metadata.inspect_zip_bundle(path, policy, architecture)
        except metadata.MetadataVerificationError:
            raise SigningFailure("Maintained ZIP verification failed") from None

    def app(self, path: Path, policy: Mapping[str, str], architecture: str) -> BundleInspection:
        from scripts import verify_macos_bundle_metadata as metadata
        try:
            return metadata.inspect_app_bundle(path, policy, architecture)
        except metadata.MetadataVerificationError:
            raise SigningFailure("Maintained App verification failed") from None

    def artifacts(self, context_path: Path, source: Path, app: Path, zip_path: Path, dmg_path: Path, architecture: Architecture, commands: Commands) -> VerificationReceipt:
        context = parse_context(decode_object(read_bound_file(context_path, MAX_CONTEXT_BYTES)[0], "acquired context"))
        body = commands.run([sys.executable, "-I", str(source / "scripts/sign_notarize_macos.py"), "--metadata-worker", "--context", str(context_path), "--source-root", str(source), "--app", str(app), "--zip", str(zip_path), "--dmg", str(dmg_path)], "maintained-metadata-worker", timeout=300, metadata_worker=True, cwd=source)
        return parse_metadata_return(body, context, architecture)


def plist_map(value: object) -> TypeGuard[dict[object, object]]:
    # Foreign plist values can contain data/date fields. Only this boundary
    # examines object values; owned mount entities below have precise types.
    return type(value) is dict


def plist_array(value: object) -> TypeGuard[list[object]]:
    return type(value) is list


@dataclass(frozen=True)
class MountEntity:
    image: str
    mount: str
    device: str


def mount_entities(body: bytes) -> tuple[MountEntity, ...]:
    raw: object = plistlib.loads(body)
    if not plist_map(raw):
        raise SigningFailure("Invalid disk-image info root")
    images = raw.get("images")
    if not plist_array(images):
        raise SigningFailure("Disk-image info lacks its image list")
    rows: list[MountEntity] = []
    for image in images:
        rows.extend(image_entities(image))
    return tuple(rows)


def image_entities(value: object) -> list[MountEntity]:
    if not plist_map(value):
        raise SigningFailure("Invalid disk-image entry")
    image = value.get("image-path")
    entities = value.get("system-entities")
    if not isinstance(image, str) or not plist_array(entities):
        raise SigningFailure("Disk-image entry lacks path/entities")
    rows: list[MountEntity] = []
    for entity in entities:
        if not plist_map(entity):
            raise SigningFailure("Invalid mount entity")
        mount, device = entity.get("mount-point"), entity.get("dev-entry")
        if mount is None:
            continue
        if not isinstance(mount, str) or not isinstance(device, str) or re.fullmatch(r"/dev/disk[0-9]+(?:s[0-9]+)*", device) is None:
            raise SigningFailure("Invalid physical mount binding")
        rows.append(MountEntity(image, mount, device))
    return rows


class DmgMount:
    def __init__(self, work: PrivateWork, commands: Commands, image: Path) -> None:
        self.work, self.commands, self.image = work, commands, image
        self.mount = work.path / "distributed-dmg"
        self.mount.mkdir(mode=0o700)
        self.detached = False

    def owned_devices(self, *, cleanup: bool = False) -> set[str]:
        info = self.commands.run(["/usr/bin/hdiutil", "info", "-plist"], "mount-info", cleanup=cleanup)
        rows = mount_entities(info)
        return {row.device for row in rows if row.image == str(self.image) and row.mount == str(self.mount)}

    def attach(self) -> None:
        self.work.verify()
        self.commands.run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", str(self.mount), "-plist", str(self.image)], "mount-dmg")
        require(len(self.owned_devices()) == 1, "Mounted image has no unambiguous exact owned device")

    def cleanup(self, primary: BaseException | None) -> None:
        errors: list[BaseException] = []
        try:
            self.work.verify()
            devices = self.owned_devices(cleanup=True)
            require(len(devices) <= 1, "Ambiguous owned disk-image devices; refusing to guess")
            if devices:
                self.commands.run(["/usr/bin/hdiutil", "detach", next(iter(devices))], "detach-dmg", cleanup=True)
        except BaseException as error:
            errors.append(error)
        try:
            require(not self.owned_devices(cleanup=True), "Owned distributed image remains attached")
        except BaseException as error:
            errors.append(error)
        if errors:
            if primary is not None:
                primary.add_note(f"Owned disk-image cleanup failed ({type(errors[0]).__name__})")
                raise primary from errors[0]
            raise SigningFailure("Owned disk-image cleanup failed") from errors[0]
        self.detached = True

    def __enter__(self) -> Path:
        try:
            self.attach()
            return self.mount / "GM2Godot.app"
        except BaseException as primary:
            self.cleanup(primary)
            raise

    def __exit__(self, _exception_type: type[BaseException] | None, exception: BaseException | None, _traceback: TracebackType | None) -> None:
        self.cleanup(exception)


def verify_unsigned_namespace(zip_path: Path, source: Path) -> None:
    import zipfile
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        readmes = [item for item in members if item.filename == "README.md"]
        require(len(readmes) == 1 and all(item.filename == "README.md" or item.filename.startswith("GM2Godot.app/") for item in members), "Unsigned ZIP namespace differs")
        readme = readmes[0]
        require(readme.create_system == 3 and stat.S_ISREG(readme.external_attr >> 16) and not readme.flag_bits & 1, "Packaged README is not regular unencrypted Unix data")
        source_body, _source_seal = read_bound_file(source / "README.md", MAX_CONTEXT_BYTES)
        require(readme.file_size == len(source_body) and archive.read(readme) == source_body, "Packaged README differs from trusted source")


def signing_targets(app: Path, inspection: BundleInspection) -> tuple[Path, ...]:
    targets = {app / item.relative_path for item in inspection.inventory.mach_o_files}
    for current, directories, _files in os.walk(app, followlinks=False):
        directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()]
        for name in directories:
            path = Path(current) / name
            if path.suffix in {".framework", ".app", ".appex", ".xpc", ".bundle"}:
                targets.add(path)
    targets.discard(app)
    return tuple(sorted(targets, key=lambda path: (-len(path.relative_to(app).parts), path.as_posix()))) + (app,)


def sign_tree(commands: Commands, keychain: Keychain, app: Path, inspection: BundleInspection) -> None:
    for path in signing_targets(app, inspection):
        commands.run(["/usr/bin/codesign", "--force", "--timestamp", "--options", "runtime", "--sign", keychain.private.identity_sha1, "--keychain", str(keychain.path), str(path)], "sign-code")


def empty_entitlements(commands: Commands, path: Path) -> None:
    body = commands.run(["/usr/bin/codesign", "--display", "--entitlements", "-", "--xml", str(path)], "read-entitlements", combined=True)
    begin = body.find(b"<?xml")
    if begin >= 0:
        end = body.find(b"</plist>", begin)
        require(end >= 0, "Malformed signed entitlements")
        value: object = plistlib.loads(body[begin:end + len(b"</plist>")])
        require(value == {}, "Unapproved signed entitlements")


def code_identity(commands: Commands, path: Path, private: Credentials, certificate_root: Path, *, runtime_required: bool, app: bool) -> JsonObject:
    commands.run(["/usr/bin/codesign", "--verify", "--strict", "--all-architectures", *(["--deep"] if app else []), str(path)], "verify-code")
    display = commands.run(["/usr/bin/codesign", "--display", "--verbose=4", str(path)], "read-signature", combined=True).decode("utf-8", errors="strict")
    authorities = re.findall(r"^Authority=(Developer ID Application: .+)$", display, re.MULTILINE)
    timestamps = re.findall(r"^Timestamp=(?!none\b)(.+)$", display, re.MULTILINE)
    teams = re.findall(r"^TeamIdentifier=(.+)$", display, re.MULTILINE)
    runtime = re.search(r"^CodeDirectory .*flags=.*runtime", display, re.MULTILINE) is not None
    require(len(authorities) == len(timestamps) == 1 and teams == [private.team_id] and "Signature=adhoc" not in display, "Signed Developer ID/team/timestamp policy failed")
    require(authorities[0].endswith(f" ({private.team_id})") and re.search(r"\b[0-9]{4}\b", timestamps[0]) is not None, "Developer ID authority/date differs from approved signing policy")
    require(not runtime_required or runtime, "Signed executable lacks hardened runtime")
    certificate_root.mkdir(mode=0o700)
    prefix = certificate_root / "certificate-"
    commands.run(["/usr/bin/codesign", "--display", "--extract-certificates", str(prefix), str(path)], "extract-certificate")
    certificate, _seal = read_bound_file(certificate_root / "certificate-0", 1024 * 1024)
    fingerprint = hashlib.sha1(certificate).hexdigest().upper()
    require(fingerprint == private.identity_sha1, "Signed certificate fingerprint differs from approved identity")
    empty_entitlements(commands, path)
    return {"certificate_sha1": fingerprint, "team_id": teams[0], "authority": authorities[0], "timestamp": timestamps[0], "runtime": runtime, "signature_verified": True, "entitlements_verified_empty": True}


def inspect_signed_tree(commands: Commands, private: Credentials, work: PrivateWork, app: Path, inspection: BundleInspection) -> list[JsonValue]:
    rows: list[JsonValue] = []
    for index, target in enumerate(signing_targets(app, inspection)):
        relative = "." if target == app else target.relative_to(app).as_posix()
        row = code_identity(commands, target, private, work.path / f"code-certificate-{index}", runtime_required=True, app=target == app or target.suffix == ".app")
        row["path"] = relative
        rows.append(row)
    return rows


class Notary:
    def __init__(self, commands: Commands, private: Credentials, p8: Path) -> None:
        self.commands, self.private, self.p8 = commands, private, p8

    def auth(self) -> list[str]:
        return ["--key", str(self.p8), "--key-id", self.private.notary_key_id, "--issuer", self.private.notary_issuer_id]

    def submit(self, payload: Path, label: str) -> JsonObject:
        require(label in {"app", "dmg"}, "Unknown notary payload role")
        submitted = seal_file(payload)
        result = self.commands.result(["/usr/bin/xcrun", "notarytool", "submit", str(payload), *self.auth(), "--wait", "--timeout", "30m", "--output-format", "json"], f"notarize-{label}", timeout=1860)
        submission = decode_object(result.stdout, f"{label} submission")
        identifier = canonical_uuid(text(submission, "id"))
        require(seal_file(payload) == submitted, "Submitted archive changed during notarization")
        raw_log = self.p8.parent / f"{label}-notary-raw.json"
        log = self.commands.proof / f"{label}-notary-log.json"
        require(not raw_log.exists() and not raw_log.is_symlink() and not log.exists() and not log.is_symlink(), "Notary log path is occupied")
        self.commands.run(["/usr/bin/xcrun", "notarytool", "log", identifier, *self.auth(), str(raw_log)], f"notary-log-{label}")
        body, _raw_seal = read_bound_file(raw_log, MAX_NOTARY_LOG_BYTES)
        require(seal_file(payload) == submitted, "Submitted archive changed while collecting its notary log")
        safe = self.commands.redact(body)
        seal = write_exclusive(log, safe)
        require(safe == body, "Notary log contained protected material; sanitized proof retained")
        report = decode_object(body, f"{label} notary log")
        require(result.returncode == 0 and not result.timed_out and submission.get("status") == "Accepted", "Notary submission was not Accepted; safe proof retained")
        verify_notary_log(report, identifier, submitted)
        return {"id": identifier, "status": "Accepted", "submission": submitted.as_json(), "log": seal.as_json()}


def verify_notary_log(report: JsonObject, identifier: str, submitted: FileSeal) -> None:
    require(canonical_uuid(text(report, "jobId")) == identifier and report.get("status") == "Accepted", "Notary log does not attest the accepted submission")
    require(text(report, "archiveFilename") == submitted.name, "Notary archive filename differs from submitted bytes")
    require("issues" in report and (report["issues"] is None or report["issues"] == []), "Notary issues require review")
    if "statusCode" in report:
        require(type(report["statusCode"]) is int and report["statusCode"] == 0, "Notary log has an unsuccessful status code")
    if "sha256" in report:
        reported_hash = text(report, "sha256").lower()
        require(re.fullmatch(r"[0-9a-f]{64}", reported_hash) is not None and reported_hash == submitted.sha256, "Notary log hash differs from pre-staple submitted bytes")


def assess_app(commands: Commands, path: Path) -> JsonObject:
    commands.run(["/usr/bin/codesign", "--verify", "--strict", "--all-architectures", "--deep", str(path)], "assess-code")
    commands.run(["/usr/bin/xcrun", "stapler", "validate", str(path)], "validate-app-ticket")
    result = commands.run(["/usr/sbin/spctl", "--assess", "--type", "execute", "--verbose=4", str(path)], "assess-app", combined=True)
    require(b"source=Notarized Developer ID" in result, "Distributed App is not accepted as notarized Developer ID")
    return {"accepted": True, "source": "Notarized Developer ID", "signature_verified": True, "ticket_valid": True}


def assess_dmg(commands: Commands, path: Path, private: Credentials, work: PrivateWork) -> JsonObject:
    code_identity(commands, path, private, work.path / "dmg-certificate", runtime_required=False, app=False)
    commands.run(["/usr/bin/xcrun", "stapler", "validate", str(path)], "validate-dmg-ticket")
    result = commands.run(["/usr/sbin/spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=4", str(path)], "assess-dmg", combined=True)
    require(b"source=Notarized Developer ID" in result, "Distributed DMG is not accepted as notarized Developer ID")
    return {"accepted": True, "source": "Notarized Developer ID", "signature_verified": True, "ticket_valid": True}


def metadata_value(receipt: VerificationReceipt) -> JsonObject:
    metadata = receipt.metadata
    maximum: list[JsonValue] = list(receipt.maximum_macos)
    return {"metadata": {"identifier": metadata.identifier, "short_version": metadata.short_version, "build_version": metadata.build_version, "minimum_system_version": metadata.minimum_system_version, "plist_sha256": metadata.plist_sha256}, "architecture": receipt.architecture, "macho_count": receipt.macho_count, "symlink_count": receipt.symlink_count, "maximum_macos": maximum}


@dataclass(frozen=True)
class MetadataRequest:
    context_path: Path
    source_root: Path
    app: Path
    zip_path: Path
    dmg_path: Path


def script_source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def trusted_worker_source(request: MetadataRequest, entry_script: Path, context: SigningContext, environment: Mapping[str, str]) -> Path:
    source = request.source_root.resolve(strict=True)
    require(source == script_source_root() and not request.source_root.is_symlink(), "Metadata worker requires its direct trusted source checkout")
    require(not entry_script.is_symlink() and entry_script.resolve(strict=True) == source / "scripts/sign_notarize_macos.py", "Metadata worker entry script differs from trusted source")
    for path in (request.context_path, request.app, request.zip_path, request.dmg_path):
        require(not path.resolve(strict=True).is_relative_to(source), "Metadata worker artifacts must stay outside importable source")
    verify_checkout(source, context, environment)
    return source


def interrupt_metadata_worker(_signal: int, _frame: FrameType | None) -> Never:
    # An exception enters the unchanged verifier's owned finally cleanup.
    # A supervisor still treats interruption as failure, not successful cleanup.
    raise SigningFailure("Metadata worker interrupted; verification did not finish")


def metadata_worker(request: MetadataRequest, *, entry_script: Path) -> JsonObject:
    current = os.environ
    require(not any(secret_environment_name(name) for name in current), "Metadata worker refuses credential or source-injection environment keys")
    context = parse_context(decode_object(read_bound_file(request.context_path, MAX_CONTEXT_BYTES)[0], "acquired context"))
    source = trusted_worker_source(request, entry_script, context, current)
    # No maintained verifier import or call occurs before the environment and
    # exact acquired checkout checks above. Its hdiutil children inherit only
    # this already-scrubbed process environment, without global mutation.
    from scripts import verify_macos_bundle_metadata as metadata
    previous = signal.signal(signal.SIGTERM, interrupt_metadata_worker)
    try:
        actual = metadata.verify_artifacts(source, request.app, request.zip_path, request.dmg_path, context.architecture)
    except metadata.MetadataVerificationError:
        raise SigningFailure("Maintained artifact verification failed; verifier cleanup is unconfirmed") from None
    finally:
        signal.signal(signal.SIGTERM, previous)
    verify_checkout(source, context, current)
    return {"schema_version": 1, "successful": True, "source": {"sha": context.source_sha, "tree": context.source_tree}, "verification_returned": True, "metadata_return": metadata_value(actual)}


def nonnegative_integer(data: JsonObject, key: str) -> int:
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise SigningFailure(f"Expected nonnegative integer field: {key}")


def macos_components(value: JsonValue) -> tuple[int, int, int]:
    require(isinstance(value, list) and len(value) == 3, "Metadata worker maximum macOS version differs")
    if isinstance(value, list):
        first, second, third = value
        if type(first) is int and type(second) is int and type(third) is int and first >= 0 and second >= 0 and third >= 0:
            return first, second, third
    raise SigningFailure("Metadata worker version components differ")


def parse_verification_return(value: JsonObject, architecture: Architecture) -> VerificationReceipt:
    from scripts import verify_macos_bundle_metadata as metadata
    exact_keys(value, frozenset({"metadata", "architecture", "macho_count", "symlink_count", "maximum_macos"}))
    require(text(value, "architecture") == architecture, "Metadata worker architecture differs")
    fields = json_object(value["metadata"])
    exact_keys(fields, frozenset({"identifier", "short_version", "build_version", "minimum_system_version", "plist_sha256"}))
    bundle = metadata.BundleMetadata(text(fields, "identifier"), text(fields, "short_version"), text(fields, "build_version"), text(fields, "minimum_system_version"), sha_text(fields, "plist_sha256", 64))
    return metadata.VerificationReceipt(bundle, architecture, positive_integer(value, "macho_count"), nonnegative_integer(value, "symlink_count"), macos_components(value["maximum_macos"]))


def parse_metadata_return(body: bytes, context: SigningContext, architecture: Architecture) -> VerificationReceipt:
    require(len(body) <= MAX_CONTEXT_BYTES, "Metadata worker receipt exceeds its bounded size")
    try:
        value = decode_object(body, "metadata worker receipt")
    except (ValueError, RecursionError):
        raise SigningFailure("Metadata worker receipt is malformed") from None
    exact_keys(value, frozenset({"schema_version", "successful", "source", "verification_returned", "metadata_return"}))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["successful"] is True and value["verification_returned"] is True, "Metadata worker did not return a successful verification")
    source = json_object(value["source"])
    exact_keys(source, frozenset({"sha", "tree"}))
    require(sha_text(source, "sha") == context.source_sha and sha_text(source, "tree") == context.source_tree, "Metadata worker source differs")
    return parse_verification_return(json_object(value["metadata_return"]), architecture)


def safe_cleanup_summaries(error: BaseException) -> tuple[str, ...]:
    summaries: list[str] = []
    for note in error.__notes__ if hasattr(error, "__notes__") else ():
        for prefix, summary in (("Private signing cleanup failed (", "Private signing cleanup failed."), ("Owned keychain cleanup failed (", "Owned keychain cleanup failed."), ("Owned disk-image cleanup failed (", "Owned disk-image cleanup failed.")):
            if note.startswith(prefix) and note.endswith(")") and summary not in summaries:
                summaries.append(summary)
    return tuple(summaries)


def safe_failure_message(error: BaseException) -> str:
    detail = str(error) if isinstance(error, SigningFailure) else type(error).__name__
    cleanup = " ".join(safe_cleanup_summaries(error))
    suffix = f" {cleanup}" if cleanup else ""
    return f"Protected verification failed: {detail}.{suffix} No publication is authorized."


@dataclass(frozen=True)
class PreparedArtifacts:
    final_zip: Path
    final_dmg: Path
    metadata: VerificationReceipt
    nested_code: list[JsonValue]
    notarization: JsonObject
    assessments: JsonObject
    owned_mounts_detached: bool
    final_seals: tuple[FileSeal, FileSeal]


def build_final_zip(commands: Commands, bundles: BundleOperations, keychain: Keychain, notary: Notary, source: Path, work: PrivateWork, policy: Mapping[str, str], unsigned: Path, architecture: Architecture, output: Path) -> tuple[Path, Path, BundleInspection, JsonObject]:
    initial = bundles.zip(unsigned, policy, architecture)
    verify_unsigned_namespace(unsigned, source)
    payload = work.path / "payload"
    payload.mkdir(mode=0o700)
    commands.run(["/usr/bin/ditto", "-xk", str(unsigned), str(payload)], "extract-unsigned")
    app = payload / "GM2Godot.app"
    physical = bundles.app(app, policy, architecture)
    require(physical == initial, "Unsigned extraction changed native/plist/link inventory")
    sign_tree(commands, keychain, app, physical)
    submission = work.path / "app-submission.zip"
    commands.run(["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(submission)], "package-submission")
    app_notary = notary.submit(submission, "app")
    commands.run(["/usr/bin/xcrun", "stapler", "staple", str(app)], "staple-app")
    assess_app(commands, app)
    final_zip = output / f"GM2Godot-macos-{architecture}.zip"
    commands.run(["7z", "a", "-snl", str(final_zip), "."], "package-public-zip", timeout=300, cwd=payload)
    final_inspection = bundles.zip(final_zip, policy, architecture)
    verify_unsigned_namespace(final_zip, source)
    extracted = work.path / "final-zip"
    extracted.mkdir(mode=0o700)
    commands.run(["/usr/bin/ditto", "-xk", str(final_zip), str(extracted)], "extract-public-zip")
    require(bundles.app(extracted / "GM2Godot.app", policy, architecture) == final_inspection, "Signed ZIP extraction changed inventory")
    return app, final_zip, final_inspection, app_notary


def build_final_dmg(commands: Commands, keychain: Keychain, notary: Notary, work: PrivateWork, app: Path, policy: Mapping[str, str], architecture: Architecture, output: Path) -> tuple[Path, JsonObject]:
    root = work.path / "dmg-source"
    root.mkdir(mode=0o700)
    commands.run(["/usr/bin/ditto", str(app), str(root / "GM2Godot.app")], "copy-dmg-app")
    (root / "Applications").symlink_to("/Applications")
    final_dmg = output / f"GM2Godot-macos-{architecture}.dmg"
    commands.run(["/usr/bin/hdiutil", "create", "-volname", "GM2Godot", "-srcfolder", str(root), "-format", "UDZO", str(final_dmg)], "create-dmg", timeout=300)
    commands.run(["/usr/bin/codesign", "--sign", keychain.private.identity_sha1, "--keychain", str(keychain.path), "--timestamp", "--identifier", policy["CFBundleIdentifier"] + ".disk." + architecture, str(final_dmg)], "sign-dmg")
    dmg_notary = notary.submit(final_dmg, "dmg")
    commands.run(["/usr/bin/xcrun", "stapler", "staple", str(final_dmg)], "staple-dmg")
    return final_dmg, dmg_notary


def prepare_artifacts(options: SigningOptions, source: Path, output: Path, work: PrivateWork, commands: Commands, bundles: BundleOperations, private: Credentials) -> tuple[PreparedArtifacts, bool]:
    policy = bundles.policy(source)
    p8 = work.path / "notary.p8"
    write_exclusive(p8, private.p8)
    keychain = Keychain(work, commands, private)
    with keychain:
        notary = Notary(commands, private, p8)
        app, final_zip, inspection, app_notary = build_final_zip(commands, bundles, keychain, notary, source, work, policy, options.unsigned_zip, options.architecture, output)
        zip_seal = seal_file(final_zip)
        distributed = work.path / "final-zip" / "GM2Godot.app"
        nested = inspect_signed_tree(commands, private, work, distributed, inspection)
        zip_assessment = assess_app(commands, distributed)
        final_dmg, dmg_notary = build_final_dmg(commands, keychain, notary, work, app, policy, options.architecture, output)
        require(text(app_notary, "id") != text(dmg_notary, "id"), "App and DMG notarization identifiers are duplicated")
        dmg_seal = seal_file(final_dmg)
        dmg_assessment = assess_dmg(commands, final_dmg, private, work)
        actual_metadata = bundles.artifacts(options.context_path, source, app, final_zip, final_dmg, options.architecture, commands)
        mount = DmgMount(work, commands, final_dmg)
        with mount as mounted_app:
            require(bundles.app(mounted_app, policy, options.architecture) == inspection, "Distributed DMG native/plist/link inventory differs")
            app_assessment = assess_app(commands, mounted_app)
        require((seal_file(final_zip), seal_file(final_dmg)) == (zip_seal, dmg_seal), "Final signed bytes changed during verification")
        result = PreparedArtifacts(final_zip, final_dmg, actual_metadata, nested, {"app": app_notary, "dmg": dmg_notary}, {"zip_app": zip_assessment, "dmg_app": app_assessment, "dmg": dmg_assessment}, mount.detached, (zip_seal, dmg_seal))
    return result, keychain.deleted


def signed_gui(commands: Commands, source: Path, final_zip: Path, architecture: Architecture) -> JsonObject:
    path = commands.proof / "signed-gui.json"
    require(not path.exists() and not path.is_symlink(), "Signed GUI proof path is occupied")
    commands.run([sys.executable, "-I", str(source / "scripts" / "verify_macos_gui_artifact.py"), "--source-root", str(source), "--zip", str(final_zip), "--expected-architecture", architecture, "--output", str(path)], "signed-gui", timeout=300)
    body, report_seal = read_bound_file(path, MAX_GUI_BYTES)
    value = decode_object(body, "signed GUI receipt")
    runtime = json_object(value.get("runtime"))
    gui = json_object(value.get("gui"))
    require(value.get("schema_version") == 1 and value.get("successful") is True and value.get("zip_sha256") == seal_file(final_zip).sha256, "Signed GUI receipt differs from exact final ZIP")
    require(runtime.get("implementation") == "CPython" and runtime.get("platform") == "darwin" and runtime.get("system") == "Darwin" and runtime.get("machine") == architecture and runtime.get("python_version") == "3.12.10" and runtime.get("translated") is False, "Signed GUI runtime is not pinned native Python")
    require(type(gui.get("returncode")) is int and gui.get("returncode") == 0 and gui.get("cleanup_successful") is True and gui.get("exact_receipt") is True, "Signed GUI lifecycle or cleanup failed")
    require(value.get("source_app_gui_tested") is False and value.get("dmg_gui_tested") is False, "Signed GUI evidence scope changed")
    return {"successful": True, "architecture": architecture, "zip_sha256": value["zip_sha256"], "report": report_seal.as_json(), "gui": {"returncode": 0, "cleanup_successful": True, "exact_receipt": True}, "source_app_gui_tested": False, "dmg_gui_tested": False}


def signing_receipt(context: SigningContext, private: Credentials, original: tuple[FileSeal, FileSeal], artifacts: PreparedArtifacts, gui: JsonObject, keychain_deleted: bool, private_removed: bool) -> JsonObject:
    require(keychain_deleted and private_removed and artifacts.owned_mounts_detached, "Private resources have not been cleaned")
    require((seal_file(artifacts.final_zip), seal_file(artifacts.final_dmg)) == artifacts.final_seals, "Final signed bytes changed after verification")
    metadata = artifacts.metadata
    return {"schema_version": 1, "successful": True, "purpose": "verification_only", "release_eligible": False, "repository": REPOSITORY, "source": {"sha": context.source_sha, "tree": context.source_tree}, "producer": context.producer.as_json(), "signing": context.signing.as_json(), "architecture": context.architecture, "version": metadata.metadata.short_version, "unsigned_payloads": [item.as_json() for item in original], "final_payloads": [item.as_json() for item in artifacts.final_seals], "metadata": metadata_value(metadata), "developer_id": {"team_id": private.team_id, "identity_sha1": private.identity_sha1, "nested_code": artifacts.nested_code}, "notarization": artifacts.notarization, "assessments": artifacts.assessments, "signed_gui": gui, "cleanup": {"keychain_deleted": True, "private_files_removed": True, "owned_mounts_detached": True}}


def sign_verification(options: SigningOptions, *, environment: Mapping[str, str] | None = None, executor: CommandExecutor | None = None, bundles: BundleOperations | None = None) -> JsonObject:
    current = os.environ if environment is None else environment
    body, _context_seal = read_bound_file(options.context_path, MAX_CONTEXT_BYTES)
    context = parse_context(decode_object(body, "acquired signing context"))
    source = trusted_source(options, context, current)
    require(options.unsigned_zip.name == f"GM2Godot-macos-{options.architecture}.zip" and options.unsigned_dmg.name == f"GM2Godot-macos-{options.architecture}.dmg", "Unsigned payload names differ from source roles")
    original = (seal_file(options.unsigned_zip), seal_file(options.unsigned_dmg))
    runner_temp, output, proof = prepare_roots(options, source, current)
    private = credentials(current)
    commands = Commands(SubprocessExecutor() if executor is None else executor, current, proof, private.redactions)
    operations = BundleOperations() if bundles is None else bundles
    commands.run([sys.executable, "-I", str(source / "scripts" / "verify_macos_gui_artifact.py"), "--check-native-runtime", "--expected-architecture", options.architecture], "native-runtime", timeout=60)
    work = PrivateWork(runner_temp)
    with work:
        artifacts, keychain_deleted = prepare_artifacts(options, source, output, work, commands, operations, private)
        commands.operation_timeout(1, False)
    require((seal_file(options.unsigned_zip), seal_file(options.unsigned_dmg)) == original, "Original unsigned payload changed")
    gui = signed_gui(commands, source, artifacts.final_zip, options.architecture)
    trusted_source(options, context, current)
    receipt = signing_receipt(context, private, original, artifacts, gui, keychain_deleted, work.removed)
    encoded = (json.dumps(receipt, indent=2, allow_nan=False) + "\n").encode()
    require(len(encoded) <= MAX_CONTEXT_BYTES, "Signing receipt exceeds its bounded size")
    commands.operation_timeout(1, False)
    write_exclusive(proof / "signing.json", encoded)
    return receipt
