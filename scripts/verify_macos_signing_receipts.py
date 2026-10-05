"""Join protected signing attestations to final bytes without executing artifacts.

UNEXECUTED outside phase2 proposal. Local fixtures cannot establish Apple trust.
Invoke as a module so the maintained recursive JSON boundary is importable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from src.conversion.json_values import JsonObject, JsonValue, validate_json_value

REPOSITORY = "Infiland/GM2Godot"
ARCHITECTURES = ("arm64", "x86_64")
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_GUI_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD_BYTES = 1024 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
RECEIPT_KEYS = frozenset(
    {
        "schema_version", "successful", "purpose", "release_eligible", "repository", "source", "producer",
        "signing", "architecture", "version", "unsigned_payloads", "final_payloads", "metadata", "developer_id",
        "notarization", "assessments", "signed_gui", "cleanup",
    }
)


class ReceiptVerificationError(ValueError):
    """A deterministic failure; no signing credentials are consumed."""


@dataclass(frozen=True)
class PublicationContext:
    source_sha: str
    source_tree: str
    version: str
    producer_run_id: int
    producer_run_attempt: int
    producer_workflow_id: int
    signing_run_id: int
    signing_run_attempt: int
    team_id: str
    identity_sha1: str
    build_event: Literal["push", "workflow_dispatch"]
    bundle_identifier: str = "land.infi.gm2godot"


@dataclass(frozen=True)
class ReceiptInput:
    architecture: str
    receipt: Path
    payload_directory: Path


@dataclass(frozen=True)
class FileSeal:
    name: str
    size: int
    sha256: str


def _object(value: JsonValue, label: str, keys: frozenset[str] | None = None) -> JsonObject:
    if not isinstance(value, dict):
        raise ReceiptVerificationError(f"{label} must be an object")
    if keys is not None and frozenset(value) != keys:
        raise ReceiptVerificationError(f"{label} has missing or extra fields")
    return value


def _array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ReceiptVerificationError(f"{label} must be an array")
    return value


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ReceiptVerificationError(f"{label} must be bounded nonempty text")
    return value


def _integer(value: JsonValue, label: str, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ReceiptVerificationError(f"{label} must be a native integer >= {minimum}")
    return value


def _equal(value: JsonValue, expected: JsonValue, label: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ReceiptVerificationError(f"{label} differs from the required value")


def _pattern(value: JsonValue, pattern: str, label: str) -> str:
    text = _text(value, label)
    if re.fullmatch(pattern, text) is None:
        raise ReceiptVerificationError(f"{label} is malformed")
    return text


def _flat_name(value: JsonValue, label: str) -> str:
    name = _pattern(value, r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", label)
    if name in {".", ".."}:
        raise ReceiptVerificationError(f"{label} is unsafe")
    return name


def _uuid(value: JsonValue, label: str) -> str:
    text = _pattern(value, r"[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}", label)
    return str(UUID(text))


def _seal(value: JsonValue, label: str, maximum: int) -> FileSeal:
    row = _object(value, label, frozenset({"name", "size", "sha256"}))
    size = _integer(row["size"], f"{label}.size")
    if size > maximum:
        raise ReceiptVerificationError(f"{label}.size exceeds its bound")
    return FileSeal(
        _flat_name(row["name"], f"{label}.name"), size,
        _pattern(row["sha256"], r"[0-9a-f]{64}", f"{label}.sha256"),
    )


def _stat_key(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _file_bytes(path: Path, maximum: int, expected: FileSeal | None = None) -> bytes:
    """Bounded regular-file read with final descriptor and named-file checks."""
    if os.name != "posix":
        raise ReceiptVerificationError("receipt publication verification requires POSIX no-follow opens")
    with_directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.fstat(with_directory)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=with_directory)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > maximum:
                raise ReceiptVerificationError(f"{path.name} is not a bounded nonempty regular file")
            content = bytearray()
            digest = hashlib.sha256()
            while block := os.read(descriptor, CHUNK_BYTES):
                if len(content) + len(block) > maximum:
                    raise ReceiptVerificationError(f"{path.name} grew beyond its bound")
                content.extend(block)
                digest.update(block)
            after = os.fstat(descriptor)
            named = os.stat(path.name, dir_fd=with_directory, follow_symlinks=False)
            if _stat_key(before) != _stat_key(after) or _stat_key(before) != _stat_key(named):
                raise ReceiptVerificationError(f"{path.name} changed during verification")
            if len(content) != before.st_size:
                raise ReceiptVerificationError(f"{path.name} read size differs from its binding")
            if expected is not None and (len(content), digest.hexdigest()) != (expected.size, expected.sha256):
                raise ReceiptVerificationError(f"{path.name} full size/hash mismatch")
        finally:
            os.close(descriptor)
        if not os.path.samestat(parent, path.parent.stat(follow_symlinks=False)):
            raise ReceiptVerificationError("proof directory binding changed")
        return bytes(content)
    finally:
        os.close(with_directory)


def _hash_payload(path: Path, expected: FileSeal) -> None:
    """Stream large payloads through EOF instead of loading them into memory."""
    if os.name != "posix":
        raise ReceiptVerificationError("payload publication verification requires POSIX no-follow opens")
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.fstat(parent_fd)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size != expected.size:
                raise ReceiptVerificationError(f"{path.name} is not the expected regular payload")
            digest, count = hashlib.sha256(), 0
            while block := os.read(descriptor, CHUNK_BYTES):
                count += len(block)
                if count > expected.size:
                    raise ReceiptVerificationError(f"{path.name} grew during hashing")
                digest.update(block)
            named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if _stat_key(before) != _stat_key(os.fstat(descriptor)) or _stat_key(before) != _stat_key(named):
                raise ReceiptVerificationError(f"{path.name} changed during hashing")
            if (count, digest.hexdigest()) != (expected.size, expected.sha256):
                raise ReceiptVerificationError(f"{path.name} full size/hash mismatch")
        finally:
            os.close(descriptor)
        if not os.path.samestat(parent, path.parent.stat(follow_symlinks=False)):
            raise ReceiptVerificationError("payload directory binding changed")
    finally:
        os.close(parent_fd)


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptVerificationError("duplicate JSON field")
        result[key] = value
    return result


def _decode(content: bytes, label: str) -> JsonObject:
    try:
        raw: object = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
        return _object(validate_json_value(raw, source_path=label), label)
    except ReceiptVerificationError:
        raise
    except (ValueError, RecursionError) as error:
        raise ReceiptVerificationError("malformed JSON") from error


def _context(context: PublicationContext) -> None:
    _pattern(context.source_sha, r"[0-9a-f]{40}", "expected source SHA")
    _pattern(context.source_tree, r"[0-9a-f]{40}", "expected source tree")
    _pattern(context.version, r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", "version")
    if context.build_event not in ("push", "workflow_dispatch"):
        raise ReceiptVerificationError("publication requires the actual trusted-main Build event")
    if context.version == "0.0.0":
        raise ReceiptVerificationError("placeholder versions are not publication eligible")
    _pattern(context.team_id, r"[A-Z0-9]{10}", "expected team")
    _pattern(context.identity_sha1, r"[A-Fa-f0-9]{40}", "expected certificate SHA1")
    _pattern(context.bundle_identifier, r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+){2,}", "bundle identifier")
    for number in (context.producer_run_id, context.producer_run_attempt, context.producer_workflow_id,
                   context.signing_run_id, context.signing_run_attempt):
        _integer(number, "expected run identity")
    if (context.producer_run_id, context.producer_run_attempt) != (context.signing_run_id, context.signing_run_attempt):
        raise ReceiptVerificationError("publication signing must belong to the same Build run and attempt")


def _provenance(receipt: JsonObject, context: PublicationContext, architecture: str) -> None:
    for key, expected in {
        "schema_version": 1, "successful": True, "purpose": "publication", "release_eligible": True,
        "repository": REPOSITORY, "architecture": architecture, "version": context.version,
    }.items():
        _equal(receipt[key], expected, key)
    source = _object(receipt["source"], "source", frozenset({"sha", "tree"}))
    _equal(source["sha"], context.source_sha, "source.sha")
    _equal(source["tree"], context.source_tree, "source.tree")
    producer = _object(receipt["producer"], "producer", frozenset(
        {"run_id", "run_attempt", "workflow_id", "event", "branch", "head_sha"}
    ))
    signing = _object(receipt["signing"], "signing", frozenset(
        {"run_id", "run_attempt", "event", "branch", "head_sha"}
    ))
    for row, run_id, attempt in (
        (producer, context.producer_run_id, context.producer_run_attempt),
        (signing, context.signing_run_id, context.signing_run_attempt),
    ):
        for key, expected in {"run_id": run_id, "run_attempt": attempt, "event": context.build_event, "branch": "main",
                              "head_sha": context.source_sha}.items():
            _equal(row[key], expected, key)
    _equal(producer["workflow_id"], context.producer_workflow_id, "producer.workflow_id")


def _metadata(receipt: JsonObject, context: PublicationContext, architecture: str) -> JsonObject:
    result = _object(receipt["metadata"], "metadata", frozenset(
        {"metadata", "architecture", "macho_count", "symlink_count", "maximum_macos"}
    ))
    values = _object(result["metadata"], "metadata.metadata", frozenset(
        {"identifier", "short_version", "build_version", "minimum_system_version", "plist_sha256"}
    ))
    for key, expected in {"identifier": context.bundle_identifier, "short_version": context.version,
                          "build_version": context.version, "minimum_system_version": "15.0"}.items():
        _equal(values[key], expected, key)
    _pattern(values["plist_sha256"], r"[0-9a-f]{64}", "plist_sha256")
    _equal(result["architecture"], architecture, "metadata.architecture")
    _integer(result["macho_count"], "macho_count")
    _integer(result["symlink_count"], "symlink_count", 0)
    maximum = _array(result["maximum_macos"], "maximum_macos")
    if len(maximum) != 3:
        raise ReceiptVerificationError("maximum_macos requires three integers")
    version = tuple(_integer(component, "maximum_macos component", 0) for component in maximum)
    if version > (15, 0, 0):
        raise ReceiptVerificationError("native deployment exceeds maintained macOS15 minimum")
    return values


def _payloads(value: JsonValue, architecture: str, label: str) -> tuple[FileSeal, FileSeal]:
    rows = _array(value, label)
    if len(rows) != 2:
        raise ReceiptVerificationError(f"{label} requires exactly two payloads")
    pair = tuple(_seal(row, label, MAX_PAYLOAD_BYTES) for row in rows)
    expected = {f"GM2Godot-macos-{architecture}.zip", f"GM2Godot-macos-{architecture}.dmg"}
    if {row.name for row in pair} != expected:
        raise ReceiptVerificationError(f"{label} has wrong, duplicate or unsafe payload names")
    return pair[0], pair[1]


def _developer_id(value: JsonValue, context: PublicationContext) -> set[str]:
    identity = _object(value, "developer_id", frozenset({"team_id", "identity_sha1", "nested_code"}))
    _equal(identity["team_id"], context.team_id, "Developer ID team")
    _equal(identity["identity_sha1"], context.identity_sha1.upper(), "Developer ID certificate")
    code = _array(identity["nested_code"], "nested_code")
    if not code or len(code) > 100_000:
        raise ReceiptVerificationError("nested code inventory is empty or exceeds its bound")
    paths: set[str] = set()
    for value in code:
        row = _object(value, "nested code", frozenset(
            {"path", "certificate_sha1", "team_id", "authority", "timestamp", "runtime", "signature_verified",
             "entitlements_verified_empty"}
        ))
        path = _text(row["path"], "nested code path")
        parts = path.split("/")
        if path != "." and (path.startswith("/") or any(part in {"", ".", ".."} for part in parts) or "\\" in path):
            raise ReceiptVerificationError("nested code path is outside the app")
        if path.casefold() in paths:
            raise ReceiptVerificationError("duplicate nested code path")
        paths.add(path.casefold())
        _equal(row["certificate_sha1"], context.identity_sha1.upper(), "nested certificate")
        _equal(row["team_id"], context.team_id, "nested team")
        authority = _text(row["authority"], "nested authority")
        if not authority.startswith("Developer ID Application: ") or not authority.endswith(f" ({context.team_id})"):
            raise ReceiptVerificationError("nested authority is not the configured Developer ID Application")
        timestamp = _text(row["timestamp"], "nested timestamp")
        if re.search(r"\b[0-9]{4}\b", timestamp) is None:
            raise ReceiptVerificationError("nested timestamp lacks an actual signing date")
        for key in ("runtime", "signature_verified", "entitlements_verified_empty"):
            _equal(row[key], True, key)
    if not {".", "contents/macos/gm2godot"} <= paths:
        raise ReceiptVerificationError("nested signatures omit the app or main executable")
    return paths


def _proof(value: JsonValue, directory: Path, seen: set[str], maximum: int) -> JsonObject:
    seal = _seal(value, "proof file", maximum)
    folded = seal.name.casefold()
    if folded in seen:
        raise ReceiptVerificationError("proof filename collision")
    seen.add(folded)
    return _decode(_file_bytes(directory / seal.name, maximum, seal), seal.name)


def _notarization(value: JsonValue, directory: Path, seen: set[str]) -> set[str]:
    submissions = _object(value, "notarization", frozenset({"app", "dmg"}))
    identifiers: set[str] = set()
    for label in ("app", "dmg"):
        row = _object(submissions[label], label, frozenset({"id", "status", "submission", "log"}))
        identifier = _uuid(row["id"], "notary id")
        if identifier in identifiers:
            raise ReceiptVerificationError("app and DMG notary submissions are duplicated")
        identifiers.add(identifier)
        _equal(row["status"], "Accepted", "notary status")
        submission = _seal(row["submission"], "pre-staple submission", MAX_PAYLOAD_BYTES)
        log = _proof(row["log"], directory, seen, MAX_LOG_BYTES)
        _equal(_uuid(log.get("jobId"), "notary log id"), identifier, "notary log id")
        _equal(log.get("status"), "Accepted", "notary log status")
        _equal(log.get("archiveFilename"), submission.name, "notary log archive filename")
        if "statusCode" in log:
            _equal(log["statusCode"], 0, "notary log status code")
        if "sha256" in log:
            reported_hash = _pattern(log["sha256"], r"[A-Fa-f0-9]{64}", "notary log submitted hash")
            _equal(reported_hash.lower(), submission.sha256, "notary log pre-staple submitted hash")
        if "issues" not in log or log["issues"] not in (None, []):
            raise ReceiptVerificationError("notary log is missing issues or reports issues")
    return identifiers


def _assessments(value: JsonValue) -> None:
    checks = _object(value, "assessments", frozenset({"zip_app", "dmg_app", "dmg"}))
    for label in ("zip_app", "dmg_app", "dmg"):
        row = _object(checks[label], label, frozenset({"accepted", "source", "signature_verified", "ticket_valid"}))
        _equal(row["source"], "Notarized Developer ID", "assessment source")
        for key in ("accepted", "signature_verified", "ticket_valid"):
            _equal(row[key], True, f"{label}.{key}")


def _gui_inventory(bundle: JsonObject, metadata_return: JsonObject, architecture: str,
                   code_paths: set[str]) -> None:
    native = _array(bundle.get("mach_o_files"), "GUI Mach-O inventory")
    links = _array(bundle.get("symlinks"), "GUI symlink inventory")
    _equal(metadata_return["macho_count"], len(native), "GUI Mach-O count")
    _equal(metadata_return["symlink_count"], len(links), "GUI symlink count")
    minima: list[tuple[int, ...]] = []
    paths: set[str] = set()
    for value in native:
        row = _object(value, "GUI native file", frozenset({"path", "architecture", "minimum_macos", "filetype", "mode"}))
        path = _text(row["path"], "GUI native path")
        if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")):
            raise ReceiptVerificationError("GUI native path is unsafe")
        folded = path.casefold()
        if folded in paths or folded not in code_paths:
            raise ReceiptVerificationError("GUI native signature coverage is duplicated or incomplete")
        paths.add(folded)
        _equal(row["architecture"], architecture, "GUI native architecture")
        minimum = _array(row["minimum_macos"], "GUI native minimum")
        if len(minimum) != 3:
            raise ReceiptVerificationError("GUI native minimum requires three integers")
        minima.append(tuple(_integer(component, "GUI minimum component", 0) for component in minimum))
        _integer(row["filetype"], "GUI native filetype")
        _integer(row["mode"], "GUI native mode")
    if not minima:
        raise ReceiptVerificationError("GUI native inventory is empty")
    expected_maximum: list[JsonValue] = [component for component in max(minima)]
    _equal(metadata_return["maximum_macos"], expected_maximum, "GUI native maximum")


def _gui(value: JsonValue, directory: Path, seen: set[str], architecture: str,
         zip_hash: str, metadata_return: JsonObject, code_paths: set[str]) -> None:
    summary = _object(value, "signed_gui", frozenset(
        {"successful", "architecture", "zip_sha256", "report", "gui", "source_app_gui_tested", "dmg_gui_tested"}
    ))
    for key, expected in {"successful": True, "architecture": architecture, "zip_sha256": zip_hash,
                          "source_app_gui_tested": False, "dmg_gui_tested": False}.items():
        _equal(summary[key], expected, f"signed_gui.{key}")
    brief = _object(summary["gui"], "signed_gui.gui", frozenset(
        {"returncode", "cleanup_successful", "exact_receipt"}
    ))
    report = _proof(summary["report"], directory, seen, MAX_GUI_BYTES)
    for key in ("schema_version", "successful", "zip_sha256", "source_app_gui_tested", "dmg_gui_tested"):
        _equal(report.get(key), 1 if key == "schema_version" else summary[key], f"GUI report {key}")
    runtime = _object(report.get("runtime"), "GUI runtime")
    for key, expected in {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin",
                          "system": "Darwin", "machine": architecture, "translated": False}.items():
        _equal(runtime.get(key), expected, f"GUI runtime {key}")
    gui = _object(report.get("gui"), "GUI report gui")
    for key, expected in {"returncode": 0, "cleanup_successful": True, "exact_receipt": True}.items():
        _equal(brief[key], expected, key)
        _equal(gui.get(key), expected, f"GUI report {key}")
    _equal(gui.get("receipt_mode"), 0o600, "GUI ready receipt mode")
    _equal(gui.get("receipt_nlink"), 1, "GUI ready receipt links")
    _equal(gui.get("receipt_sha256"), hashlib.sha256(b"GM2Godot packaged GUI ready\n").hexdigest(), "GUI ready bytes")
    bundle = _object(report.get("bundle"), "GUI report bundle")
    _equal(bundle.get("metadata"), metadata_return["metadata"], "GUI report metadata")
    _gui_inventory(bundle, metadata_return, architecture, code_paths)


def _verify_one(item: ReceiptInput, context: PublicationContext) -> tuple[tuple[FileSeal, FileSeal], set[str]]:
    receipt = _object(_decode(_file_bytes(item.receipt, MAX_RECEIPT_BYTES), str(item.receipt)),
                      "receipt", RECEIPT_KEYS)
    _provenance(receipt, context, item.architecture)
    _metadata(receipt, context, item.architecture)
    metadata_return = _object(receipt["metadata"], "metadata")
    _payloads(receipt["unsigned_payloads"], item.architecture, "unsigned_payloads")
    pair = _payloads(receipt["final_payloads"], item.architecture, "final_payloads")
    receipt_name = _flat_name(item.receipt.name, "receipt filename")
    seen = {receipt_name.casefold(), *(row.name.casefold() for row in pair)}
    if len(seen) != 3:
        raise ReceiptVerificationError("receipt and payload filename collision")
    code_paths = _developer_id(receipt["developer_id"], context)
    identifiers = _notarization(receipt["notarization"], item.receipt.parent, seen)
    _assessments(receipt["assessments"])
    zip_hash = next(row.sha256 for row in pair if row.name.endswith(".zip"))
    _gui(receipt["signed_gui"], item.receipt.parent, seen, item.architecture, zip_hash, metadata_return, code_paths)
    cleanup = _object(receipt["cleanup"], "cleanup", frozenset(
        {"keychain_deleted", "private_files_removed", "owned_mounts_detached"}
    ))
    for key in cleanup:
        _equal(cleanup[key], True, f"cleanup.{key}")
    for row in pair:
        _hash_payload(item.payload_directory / row.name, row)
    return pair, identifiers


def verify_publication_receipts(inputs: Sequence[ReceiptInput], context: PublicationContext) -> tuple[FileSeal, ...]:
    _context(context)
    if len(inputs) != 2 or {item.architecture for item in inputs} != set(ARCHITECTURES):
        raise ReceiptVerificationError("publication requires exactly one receipt for each native architecture")
    paths = [os.path.abspath(item.receipt) for item in inputs]
    if len(set(paths)) != 2:
        raise ReceiptVerificationError("receipt paths are duplicated")
    proofs = tuple(_verify_one(item, context) for item in inputs)
    files = tuple(row for pair, _identifiers in proofs for row in pair)
    identifiers = tuple(identifier for _pair, values in proofs for identifier in values)
    if len(set(identifiers)) != 4:
        raise ReceiptVerificationError("notary submissions are reused across architectures")
    if len({row.name.casefold() for row in files}) != 4:
        raise ReceiptVerificationError("final payload filename collision")
    return tuple(sorted(files, key=lambda row: row.name))


class _Arguments(argparse.Namespace):
    arm64_receipt: Path
    arm64_payload_directory: Path
    x86_64_receipt: Path
    x86_64_payload_directory: Path
    source_sha: str
    source_tree: str
    version: str
    producer_run_id: int
    producer_run_attempt: int
    producer_workflow_id: int
    signing_run_id: int
    signing_run_attempt: int
    team_id: str
    identity_sha1: str
    build_event: Literal["push", "workflow_dispatch"]
    bundle_identifier: str


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for architecture in ARCHITECTURES:
        flag = architecture.replace("_", "-")
        parser.add_argument(f"--{flag}-receipt", required=True, type=Path)
        parser.add_argument(f"--{flag}-payload-directory", required=True, type=Path)
    for name in ("source-sha", "source-tree", "version", "team-id", "identity-sha1"):
        parser.add_argument(f"--{name}", required=True)
    for name in ("producer-run-id", "producer-run-attempt", "producer-workflow-id", "signing-run-id", "signing-run-attempt"):
        parser.add_argument(f"--{name}", required=True, type=int)
    parser.add_argument("--build-event", required=True, choices=("push", "workflow_dispatch"))
    parser.add_argument("--bundle-identifier", default="land.infi.gm2godot")
    options = _Arguments()
    parser.parse_args(arguments, namespace=options)
    context = PublicationContext(
        options.source_sha, options.source_tree, options.version, options.producer_run_id,
        options.producer_run_attempt, options.producer_workflow_id, options.signing_run_id,
        options.signing_run_attempt, options.team_id, options.identity_sha1, options.build_event, options.bundle_identifier,
    )
    inputs = (
        ReceiptInput("arm64", options.arm64_receipt, options.arm64_payload_directory),
        ReceiptInput("x86_64", options.x86_64_receipt, options.x86_64_payload_directory),
    )
    try:
        seals = verify_publication_receipts(inputs, context)
    except (ReceiptVerificationError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"Mac signing receipt gate failed: {error}", file=sys.stderr)
        return 1
    result: JsonObject = {
        "successful": True, "source_sha": context.source_sha, "run_id": context.producer_run_id,
        "run_attempt": context.producer_run_attempt, "build_event": context.build_event,
        "final_payloads": [{"name": row.name, "size": row.size, "sha256": row.sha256} for row in seals],
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
