# pyright: reportPrivateUsage=false
"""Recoverable destination-wide publication of one managed generation.

The publisher deliberately remains separate from ``Converter`` orchestration.
It consumes the destination-local workspace and frozen inventories established
by issues #789 and #790, and gives a later integration layer one old-or-new
commit decision covering managed files plus canonical conversion evidence.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Literal, Mapping, cast

from src.conversion.anchored_artifacts import (
    PathIdentity,
    VerifiedDirectory,
    modes_match,
)
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_MANIFEST_RELATIVE_PATH,
)
from src.conversion.generation_inventory import (
    GENERATION_INVENTORY_MAX_ENTRIES,
    GenerationInventory,
    GenerationInventoryEntry,
    normalize_generation_inventory_path,
    stage_inventory_carry_forward,
    validate_generation_inventory,
    validate_staged_generation_inventory,
)
from src.conversion.managed_output_workspace import (
    WORKSPACE_PARENT_NAME,
    ManagedOutputWorkspace,
)
from src.conversion import managed_output_workspace as workspace_module


MANAGED_OUTPUT_JOURNAL_NAME = ".gm2godot-managed-output-transaction.json"
MANAGED_OUTPUT_POINTER_NAME = ".gm2godot-managed-output-generation.json"
MANAGED_OUTPUT_RECOVERY_NAME = ".gm2godot-managed-output-recovery.json"

_FORMAT_VERSION = 1
_PUBLICATION_ROOT = ".gm2godot-publication"
_PUBLICATION_MARKER = "ownership.json"
_BACKUP_ROOT = f"{_PUBLICATION_ROOT}/backups"
_DISPLACED_ROOT = f"{_PUBLICATION_ROOT}/displaced"
_DIRECTORY_STAGE_ROOT = f"{_PUBLICATION_ROOT}/directories"
_EVIDENCE_ROOT = f"{_PUBLICATION_ROOT}/evidence"
_POINTER_STAGE_PATH = f"{_PUBLICATION_ROOT}/desired-pointer.json"
_POINTER_DISPLACED_PATH = f"{_PUBLICATION_ROOT}/previous-pointer.json"
_JOURNAL_STAGE_PATH = f"{_PUBLICATION_ROOT}/journal.json"
_RECOVERY_STAGE_PATH = f"{_PUBLICATION_ROOT}/recovery.json"

_JOURNAL_MAX_BYTES = 64 * 1024 * 1024
_GENERATION_RECORD_MAX_BYTES = 64 * 1024 * 1024
_POINTER_MAX_BYTES = 1024 * 1024
_RECOVERY_MAX_BYTES = 1024 * 1024
_EVIDENCE_MAX_BYTES = 32 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
_RECOVERY_PATH_LIMIT = 100
_RECOVERY_MESSAGE_LIMIT = 4096

_TRANSACTION_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GENERATION_RECORD_PATTERN = re.compile(
    r"\.gm2godot-managed-output-generation-([0-9a-f]{32})-(previous|desired)\.json\Z"
)
_WINDOWS_MOVEFILE_WRITE_THROUGH = 0x00000008

GenerationRole = Literal["previous", "desired"]
TransitionKind = Literal["managed", "attempt", "manifest"]
DirectoryDisposition = Literal["existing", "staged"]


def _before_managed_output_phase(_phase: str, _path: str | None) -> None:
    """Narrow fault-injection seam around publication and recovery phases."""


@dataclass(frozen=True, slots=True)
class ManagedOutputPublicationReceipt:
    transaction_id: str
    inventory_sha256: str
    manifest_sha256: str | None
    attempt_sha256: str | None


@dataclass(frozen=True, slots=True)
class _ContentReceipt:
    mode: int
    byte_count: int
    sha256: str

    @classmethod
    def from_entry(cls, entry: GenerationInventoryEntry) -> _ContentReceipt:
        return cls(
            mode=entry.mode,
            byte_count=entry.byte_count,
            sha256=entry.sha256,
        )

    @classmethod
    def from_bytes(cls, content: bytes, mode: int) -> _ContentReceipt:
        return cls(
            mode=mode,
            byte_count=len(content),
            sha256=_sha256_bytes(content),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class _FileReceipt:
    relative_path: str
    identity: PathIdentity
    content: _ContentReceipt

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "identity": _identity_payload(self.identity),
            **self.content.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _EvidenceValue:
    path: str
    content: bytes | None
    mode: int | None
    identity: PathIdentity | None
    stored_receipt: _ContentReceipt | None = None

    @property
    def present(self) -> bool:
        return self.content is not None or self.stored_receipt is not None

    @property
    def receipt(self) -> _ContentReceipt | None:
        if self.stored_receipt is not None:
            return self.stored_receipt
        if self.content is None:
            return None
        if self.mode is None:
            raise AssertionError("Present evidence requires a mode")
        return _ContentReceipt.from_bytes(self.content, self.mode)


@dataclass(frozen=True, slots=True)
class _GenerationRecord:
    transaction_id: str
    role: GenerationRole
    destination_identity: PathIdentity
    inventory: GenerationInventory
    managed_identities: tuple[tuple[str, PathIdentity], ...]
    attempt: _EvidenceValue
    manifest: _EvidenceValue


@dataclass(frozen=True, slots=True)
class _RecordReference:
    name: str
    identity: PathIdentity
    mode: int
    byte_count: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "identity": _identity_payload(self.identity),
            "mode": self.mode,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class _Pointer:
    transaction_id: str
    destination_identity: PathIdentity
    journal_sha256: str
    generation_record: _RecordReference


@dataclass(frozen=True, slots=True)
class _PointerSnapshot:
    identity: PathIdentity
    mode: int
    content: bytes
    pointer: _Pointer


@dataclass(frozen=True, slots=True)
class _Transition:
    path: str
    kind: TransitionKind
    previous: _ContentReceipt | None
    desired: _ContentReceipt | None
    previous_public_identity: PathIdentity | None
    backup: _FileReceipt | None
    desired_stage: _FileReceipt | None
    backup_path: str
    desired_stage_path: str
    displaced_path: str

    @property
    def unchanged(self) -> bool:
        return _content_receipts_match(self.previous, self.desired)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "previous": (
                None if self.previous is None else self.previous.to_dict()
            ),
            "desired": None if self.desired is None else self.desired.to_dict(),
            "previous_public_identity": (
                None
                if self.previous_public_identity is None
                else _identity_payload(self.previous_public_identity)
            ),
            "backup": None if self.backup is None else self.backup.to_dict(),
            "desired_stage": (
                None
                if self.desired_stage is None
                else self.desired_stage.to_dict()
            ),
            "backup_path": self.backup_path,
            "desired_stage_path": self.desired_stage_path,
            "displaced_path": self.displaced_path,
        }


@dataclass(frozen=True, slots=True)
class _DirectoryState:
    path: str
    disposition: DirectoryDisposition
    identity: PathIdentity
    mode: int
    stage_path: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "disposition": self.disposition,
            "identity": _identity_payload(self.identity),
            "mode": self.mode,
            "stage_path": self.stage_path,
        }


@dataclass(frozen=True, slots=True)
class _Journal:
    transaction_id: str
    destination_identity: PathIdentity
    workspace_parent_identity: PathIdentity
    stage_identity: PathIdentity
    publication_identity: PathIdentity
    previous_record: _RecordReference
    desired_record: _RecordReference
    previous_pointer: _PointerSnapshot | None
    pointer_stage_identity: PathIdentity
    directories: tuple[_DirectoryState, ...]
    transitions: tuple[_Transition, ...]


@dataclass(frozen=True, slots=True)
class _PreparedPublication:
    journal: _Journal
    journal_content: bytes
    desired_pointer: _Pointer
    desired_pointer_content: bytes
    desired_record: _GenerationRecord


def _sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"Non-finite JSON number is unsupported: {value}")


def _decode_canonical_json(
    content: bytes,
    *,
    description: str,
    maximum: int,
) -> dict[str, object]:
    if len(content) > maximum:
        raise OSError(f"{description.capitalize()} exceeds {maximum} bytes")
    try:
        decoded = content.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise OSError(f"Invalid {description}") from error
    payload = _mapping(value, description)
    if content != _canonical_json_bytes(payload):
        raise OSError(f"Non-canonical {description}")
    return payload


def _mapping(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OSError(f"Invalid {description}")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise OSError(f"Invalid {description}")
    return cast(dict[str, object], raw)


def _exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    description: str,
) -> None:
    if frozenset(payload) != expected:
        raise OSError(f"Invalid {description} fields")


def _bounded_integer(
    value: object,
    description: str,
    *,
    maximum: int,
) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise OSError(f"Invalid {description}")
    return value


def _mode(value: object, description: str) -> int:
    return _bounded_integer(value, description, maximum=0o7777)


def _digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise OSError(f"Invalid {description}")
    return value


def _transaction_id(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or _TRANSACTION_ID_PATTERN.fullmatch(value) is None
    ):
        raise OSError(f"Invalid {description}")
    return value


def _identity_payload(identity: PathIdentity) -> list[str]:
    values: list[str] = []
    for value in identity:
        if type(value) is not int or value < 0 or value.bit_length() > 128:
            raise OSError("Managed-output identity is outside uint128")
        values.append(f"{value:032x}")
    return values


def _identity(value: object, description: str) -> PathIdentity:
    if not isinstance(value, list):
        raise OSError(f"Invalid {description}")
    components = cast(list[object], value)
    if len(components) != 2:
        raise OSError(f"Invalid {description}")
    parsed: list[int] = []
    for component in components:
        if (
            not isinstance(component, str)
            or len(component) != 32
            or any(character not in "0123456789abcdef" for character in component)
        ):
            raise OSError(f"Invalid {description}")
        parsed.append(int(component, 16))
    return parsed[0], parsed[1]


def _safe_relative_path(path: str, description: str) -> str:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or posixpath.normpath(path) != path
    ):
        raise OSError(f"Invalid {description}: {path!r}")
    for component in path.split("/"):
        if component in {"", ".", ".."} or component.endswith((" ", ".")):
            raise OSError(f"Invalid {description}: {path!r}")
    return path


def _content_receipt_from_payload(
    value: object,
    description: str,
) -> _ContentReceipt:
    payload = _mapping(value, description)
    _exact_keys(
        payload,
        frozenset({"mode", "byte_count", "sha256"}),
        description,
    )
    return _ContentReceipt(
        mode=_mode(payload["mode"], f"{description} mode"),
        byte_count=_bounded_integer(
            payload["byte_count"],
            f"{description} byte count",
            maximum=(1 << 63) - 1,
        ),
        sha256=_digest(payload["sha256"], f"{description} digest"),
    )


def _file_receipt_from_payload(
    value: object,
    *,
    expected_path: str,
    description: str,
) -> _FileReceipt:
    payload = _mapping(value, description)
    _exact_keys(
        payload,
        frozenset({"path", "identity", "mode", "byte_count", "sha256"}),
        description,
    )
    if payload["path"] != expected_path:
        raise OSError(f"Invalid {description} path")
    return _FileReceipt(
        relative_path=expected_path,
        identity=_identity(payload["identity"], f"{description} identity"),
        content=_ContentReceipt(
            mode=_mode(payload["mode"], f"{description} mode"),
            byte_count=_bounded_integer(
                payload["byte_count"],
                f"{description} byte count",
                maximum=(1 << 63) - 1,
            ),
            sha256=_digest(payload["sha256"], f"{description} digest"),
        ),
    )


def _record_reference_from_payload(
    value: object,
    description: str,
) -> _RecordReference:
    payload = _mapping(value, description)
    _exact_keys(
        payload,
        frozenset({"name", "identity", "mode", "byte_count", "sha256"}),
        description,
    )
    name = payload["name"]
    if (
        not isinstance(name, str)
        or _GENERATION_RECORD_PATTERN.fullmatch(name) is None
    ):
        raise OSError(f"Invalid {description} name")
    return _RecordReference(
        name=name,
        identity=_identity(payload["identity"], f"{description} identity"),
        mode=_mode(payload["mode"], f"{description} mode"),
        byte_count=_bounded_integer(
            payload["byte_count"],
            f"{description} byte count",
            maximum=_GENERATION_RECORD_MAX_BYTES,
        ),
        sha256=_digest(payload["sha256"], f"{description} digest"),
    )


def _content_receipts_match(
    left: _ContentReceipt | None,
    right: _ContentReceipt | None,
) -> bool:
    if left is None or right is None:
        return left is right
    return (
        left.byte_count == right.byte_count
        and left.sha256 == right.sha256
        and modes_match(left.mode, right.mode)
    )


def _generation_record_name(
    transaction_id: str,
    role: GenerationRole,
) -> str:
    return f".gm2godot-managed-output-generation-{transaction_id}-{role}.json"


def _publication_marker_content(
    workspace: ManagedOutputWorkspace,
    publication_identity: PathIdentity,
) -> bytes:
    return _canonical_json_bytes(
        {
            "format_version": _FORMAT_VERSION,
            "kind": "gm2godot-managed-output-publication-state",
            "transaction_id": workspace.transaction_id,
            "destination_identity": _identity_payload(
                workspace._destination.identity
            ),
            "stage_identity": _identity_payload(workspace._stage_identity),
            "publication_identity": _identity_payload(publication_identity),
        }
    )


def _open_relative_parent(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
    *,
    create: bool,
    description: str,
) -> tuple[list[VerifiedDirectory], VerifiedDirectory, str]:
    _safe_relative_path(relative_path, description)
    return workspace._open_relative_parent(
        root,
        relative_path,
        create=create,
        description=description,
    )


def _close_bindings(
    workspace: ManagedOutputWorkspace,
    bindings: list[VerifiedDirectory],
) -> None:
    if bindings:
        workspace._close_relative_bindings(bindings)


def _sync_exact_windows_file(
    parent: VerifiedDirectory,
    leaf: str,
    identity: PathIdentity,
    mode: int,
) -> None:
    descriptor = -1
    mode_changed = not bool(mode & stat.S_IWUSR)
    try:
        if mode_changed:
            parent.chmod_exact(
                leaf,
                identity,
                mode | stat.S_IWUSR,
                require_single_link=True,
            )
        descriptor = parent.open_file(
            leaf,
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != identity
        ):
            raise OSError(
                "Managed-output file changed before its Windows durability "
                f"barrier: {parent.child_path(leaf)}"
            )
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if mode_changed and parent.lexists(leaf):
            parent.chmod_exact(
                leaf,
                identity,
                mode,
                require_single_link=True,
            )


def _capture_file(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
    *,
    expected_identity: PathIdentity | None = None,
    expected_content: _ContentReceipt | None = None,
    maximum: int | None = None,
    include_content: bool = False,
    durable: bool = False,
) -> tuple[_FileReceipt, bytes | None]:
    bindings, parent, leaf = _open_relative_parent(
        workspace,
        root,
        relative_path,
        create=False,
        description="managed-output publication file",
    )
    descriptor = -1
    try:
        path = parent.child_path(leaf)
        path_stat = parent.stat(leaf)
        if (
            workspace_module._path_is_redirected(path, path_stat)
            or not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or (maximum is not None and path_stat.st_size > maximum)
        ):
            raise OSError(
                "Refusing redirected, non-regular, multiply-linked, or "
                f"oversized managed-output publication file: {path}"
            )
        descriptor = parent.open_file(
            leaf,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        opened = os.fstat(descriptor)
        identity = opened.st_dev, opened.st_ino
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not os.path.samestat(path_stat, opened)
            or opened.st_dev != workspace._destination_device
            or (expected_identity is not None and identity != expected_identity)
        ):
            raise OSError(
                f"Managed-output publication file changed while opening: {path}"
            )
        workspace_module._verify_file_boundary(
            path,
            opened,
            descriptor,
            expected_device=workspace._destination_device,
            expected_mount_id=workspace._destination_mount_id,
        )
        digest = hashlib.sha256()
        byte_count = 0
        chunks: list[bytes] | None = [] if include_content else None
        while True:
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            byte_count += len(chunk)
            if maximum is not None and byte_count > maximum:
                raise OSError(
                    f"Managed-output publication file exceeds {maximum} bytes: {path}"
                )
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        if durable and os.name != "nt":
            os.fsync(descriptor)
        final_opened = os.fstat(descriptor)
        final_path = parent.stat(leaf)
        fingerprint = workspace_module._fingerprint(opened)
        if (
            not workspace_module._fingerprints_match(
                workspace_module._fingerprint(final_opened),
                fingerprint,
            )
            or not workspace_module._fingerprints_match(
                workspace_module._fingerprint(final_path),
                fingerprint,
            )
            or byte_count != opened.st_size
        ):
            raise OSError(
                f"Managed-output publication file changed while reading: {path}"
            )
        receipt = _FileReceipt(
            relative_path=relative_path,
            identity=identity,
            content=_ContentReceipt(
                mode=stat.S_IMODE(opened.st_mode),
                byte_count=byte_count,
                sha256="sha256:" + digest.hexdigest(),
            ),
        )
        if expected_content is not None and not _content_receipts_match(
            receipt.content,
            expected_content,
        ):
            raise OSError(
                f"Managed-output publication content changed: {relative_path!r}"
            )
        if durable and os.name == "nt":
            os.close(descriptor)
            descriptor = -1
            _sync_exact_windows_file(
                parent,
                leaf,
                identity,
                receipt.content.mode,
            )
            _capture_file(
                workspace,
                root,
                relative_path,
                expected_identity=identity,
                expected_content=receipt.content,
                maximum=maximum,
            )
        if durable:
            parent.sync()
        parent.verify_path()
        return receipt, None if chunks is None else b"".join(chunks)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _close_bindings(workspace, bindings)


def _capture_optional_file(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
    *,
    maximum: int,
) -> _EvidenceValue:
    try:
        receipt, content = _capture_file(
            workspace,
            root,
            relative_path,
            maximum=maximum,
            include_content=True,
        )
    except FileNotFoundError:
        return _EvidenceValue(relative_path, None, None, None)
    if content is None:
        raise AssertionError("Evidence capture requested file bytes")
    return _EvidenceValue(
        path=relative_path,
        content=content,
        mode=receipt.content.mode,
        identity=receipt.identity,
    )


def _ensure_private_directory(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
    *,
    mode: int = 0o700,
) -> VerifiedDirectory:
    components = _safe_relative_path(
        relative_path,
        "managed-output private directory",
    ).split("/")
    current = root
    opened: list[VerifiedDirectory] = []
    try:
        for component in components:
            path = current.child_path(component)
            try:
                child_stat = current.stat(component)
            except FileNotFoundError:
                current.mkdir(component, mode)
                current.sync()
                child_stat = current.stat(component)
            if (
                workspace_module._path_is_redirected(path, child_stat)
                or not stat.S_ISDIR(child_stat.st_mode)
            ):
                raise OSError(
                    "Refusing redirected or non-directory managed-output "
                    f"private state: {path}"
                )
            identity = child_stat.st_dev, child_stat.st_ino
            child = current.open_child(
                component,
                expected_identity=identity,
                description="managed-output private directory",
            )
            opened.append(child)
            workspace_module._verify_binding_boundary(
                child,
                expected_device=workspace._destination_device,
                expected_mount_id=workspace._destination_mount_id,
            )
            current = child
        selected = opened.pop()
        for binding in reversed(opened):
            binding.close()
        return selected
    except BaseException:
        for binding in reversed(opened):
            binding.close()
        raise


def _create_bytes_file(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
    content: bytes,
    *,
    mode: int,
) -> _FileReceipt:
    parent_path = relative_path.rpartition("/")[0]
    if parent_path:
        with _ensure_private_directory(workspace, root, parent_path):
            pass
    bindings, parent, leaf = _open_relative_parent(
        workspace,
        root,
        relative_path,
        create=False,
        description="managed-output private file",
    )
    descriptor = -1
    identity: PathIdentity | None = None
    try:
        if parent.lexists(leaf):
            raise OSError(
                "Managed-output private state collision was preserved: "
                + parent.child_path(leaf)
            )
        descriptor = parent.open_file(
            leaf,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0),
            0o600,
        )
        opened = os.fstat(descriptor)
        identity = opened.st_dev, opened.st_ino
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != workspace._destination_device
        ):
            raise OSError(
                "Refusing non-regular, aliased, or cross-device managed-output "
                f"private file: {parent.child_path(leaf)}"
            )
        workspace_module._write_descriptor(descriptor, content)
        fchmod = getattr(os, "fchmod", None)
        if callable(fchmod):
            cast(Callable[[int, int], None], fchmod)(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if not callable(fchmod):
            parent.chmod_exact(
                leaf,
                identity,
                mode,
                require_single_link=True,
            )
        parent.sync()
        receipt, _unused = _capture_file(
            workspace,
            root,
            relative_path,
            expected_identity=identity,
            expected_content=_ContentReceipt.from_bytes(content, mode),
            durable=True,
        )
        return receipt
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if identity is not None and parent.lexists(leaf):
            try:
                completion_error = parent.unlink(
                    leaf,
                    expected_identity=identity,
                )
                if completion_error is not None:
                    raise completion_error
                parent.sync()
            except OSError:
                pass
        raise
    finally:
        _close_bindings(workspace, bindings)


def _copy_file_exact(
    workspace: ManagedOutputWorkspace,
    source_root: VerifiedDirectory,
    source_path: str,
    destination_root: VerifiedDirectory,
    destination_path: str,
    expected: _FileReceipt,
) -> _FileReceipt:
    parent_path = destination_path.rpartition("/")[0]
    if parent_path:
        with _ensure_private_directory(workspace, destination_root, parent_path):
            pass
    source_bindings, source_parent, source_leaf = _open_relative_parent(
        workspace,
        source_root,
        source_path,
        create=False,
        description="managed-output backup source",
    )
    destination_bindings, destination_parent, destination_leaf = (
        _open_relative_parent(
            workspace,
            destination_root,
            destination_path,
            create=False,
            description="managed-output backup destination",
        )
    )
    source_descriptor = -1
    destination_descriptor = -1
    destination_identity: PathIdentity | None = None
    try:
        source_descriptor = source_parent.open_file(
            source_leaf,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        source_stat = os.fstat(source_descriptor)
        if (
            not stat.S_ISREG(source_stat.st_mode)
            or source_stat.st_nlink != 1
            or (source_stat.st_dev, source_stat.st_ino) != expected.identity
        ):
            raise OSError(
                f"Managed-output backup source changed: {source_path!r}"
            )
        if destination_parent.lexists(destination_leaf):
            raise OSError(
                "Managed-output backup collision was preserved: "
                + destination_parent.child_path(destination_leaf)
            )
        destination_descriptor = destination_parent.open_file(
            destination_leaf,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0),
            0o600,
        )
        destination_stat = os.fstat(destination_descriptor)
        destination_identity = (
            destination_stat.st_dev,
            destination_stat.st_ino,
        )
        if (
            not stat.S_ISREG(destination_stat.st_mode)
            or destination_stat.st_nlink != 1
            or destination_stat.st_dev != workspace._destination_device
        ):
            raise OSError(
                "Refusing non-regular, aliased, or cross-device managed-output "
                f"backup: {destination_path!r}"
            )
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(source_descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            byte_count += len(chunk)
            digest.update(chunk)
            workspace_module._write_descriptor(destination_descriptor, chunk)
        fchmod = getattr(os, "fchmod", None)
        if callable(fchmod):
            cast(Callable[[int, int], None], fchmod)(
                destination_descriptor,
                expected.content.mode,
            )
        os.fsync(destination_descriptor)
        source_after = os.fstat(source_descriptor)
        source_path_after = source_parent.stat(source_leaf)
        if (
            (source_after.st_dev, source_after.st_ino) != expected.identity
            or (source_path_after.st_dev, source_path_after.st_ino)
            != expected.identity
            or byte_count != expected.content.byte_count
            or "sha256:" + digest.hexdigest() != expected.content.sha256
        ):
            raise OSError(
                f"Managed-output backup source changed while copying: {source_path!r}"
            )
        os.close(destination_descriptor)
        destination_descriptor = -1
        if not callable(fchmod):
            destination_parent.chmod_exact(
                destination_leaf,
                destination_identity,
                expected.content.mode,
                require_single_link=True,
            )
        destination_parent.sync()
        receipt, _unused = _capture_file(
            workspace,
            destination_root,
            destination_path,
            expected_identity=destination_identity,
            expected_content=expected.content,
            durable=True,
        )
        return receipt
    except BaseException:
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
        if (
            destination_identity is not None
            and destination_parent.lexists(destination_leaf)
        ):
            try:
                completion_error = destination_parent.unlink(
                    destination_leaf,
                    expected_identity=destination_identity,
                )
                if completion_error is not None:
                    raise completion_error
                destination_parent.sync()
            except OSError:
                pass
        raise
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)
        _close_bindings(workspace, destination_bindings)
        _close_bindings(workspace, source_bindings)


def _evidence_value_payload(value: _EvidenceValue) -> dict[str, object]:
    receipt = value.receipt
    return {
        "path": value.path,
        "present": value.present,
        "identity": (
            None if value.identity is None else _identity_payload(value.identity)
        ),
        "mode": None if receipt is None else receipt.mode,
        "byte_count": 0 if receipt is None else receipt.byte_count,
        "sha256": None if receipt is None else receipt.sha256,
    }


def _generation_record_payload(record: _GenerationRecord) -> dict[str, object]:
    return {
        "format_version": _FORMAT_VERSION,
        "kind": "gm2godot-managed-output-generation-record",
        "transaction_id": record.transaction_id,
        "role": record.role,
        "destination_identity": _identity_payload(record.destination_identity),
        "inventory": record.inventory.to_dict(),
        "managed_identities": [
            [path, *_identity_payload(identity)]
            for path, identity in record.managed_identities
        ],
        "evidence": {
            "attempt": _evidence_value_payload(record.attempt),
            "manifest": _evidence_value_payload(record.manifest),
        },
    }


def _generation_record_content(record: _GenerationRecord) -> bytes:
    content = _canonical_json_bytes(_generation_record_payload(record))
    if len(content) > _GENERATION_RECORD_MAX_BYTES:
        raise OSError(
            "Managed-output generation record exceeds "
            f"{_GENERATION_RECORD_MAX_BYTES} bytes"
        )
    return content


def _evidence_value_from_payload(
    value: object,
    *,
    expected_path: str,
    description: str,
) -> _EvidenceValue:
    payload = _mapping(value, description)
    _exact_keys(
        payload,
        frozenset(
            {"path", "present", "identity", "mode", "byte_count", "sha256"}
        ),
        description,
    )
    if payload["path"] != expected_path or type(payload["present"]) is not bool:
        raise OSError(f"Invalid {description}")
    present = payload["present"]
    if not present:
        if (
            payload["identity"] is not None
            or payload["mode"] is not None
            or payload["byte_count"] != 0
            or payload["sha256"] is not None
        ):
            raise OSError(f"Invalid absent {description}")
        return _EvidenceValue(expected_path, None, None, None)
    identity = _identity(payload["identity"], f"{description} identity")
    mode = _mode(payload["mode"], f"{description} mode")
    byte_count = _bounded_integer(
        payload["byte_count"],
        f"{description} byte count",
        maximum=_EVIDENCE_MAX_BYTES,
    )
    digest = _digest(payload["sha256"], f"{description} digest")
    return _EvidenceValue(
        path=expected_path,
        content=None,
        mode=mode,
        identity=identity,
        stored_receipt=_ContentReceipt(
            mode=mode,
            byte_count=byte_count,
            sha256=digest,
        ),
    )


def _evidence_receipt(value: _EvidenceValue) -> _ContentReceipt | None:
    return value.receipt


def _generation_record_from_content(content: bytes) -> _GenerationRecord:
    payload = _decode_canonical_json(
        content,
        description="managed-output generation record",
        maximum=_GENERATION_RECORD_MAX_BYTES,
    )
    _exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "kind",
                "transaction_id",
                "role",
                "destination_identity",
                "inventory",
                "managed_identities",
                "evidence",
            }
        ),
        "managed-output generation record",
    )
    if (
        payload["format_version"] != _FORMAT_VERSION
        or payload["kind"] != "gm2godot-managed-output-generation-record"
        or payload["role"] not in {"previous", "desired"}
    ):
        raise OSError("Unsupported managed-output generation record")
    transaction_id = _transaction_id(
        payload["transaction_id"],
        "managed-output generation record transaction",
    )
    try:
        inventory = GenerationInventory.from_value(payload["inventory"])
    except OSError:
        raise
    identities_value = payload["managed_identities"]
    if not isinstance(identities_value, list):
        raise OSError("Invalid managed-output generation identities")
    identity_rows = cast(list[object], identities_value)
    if len(identity_rows) != len(inventory.entries):
        raise OSError("Managed-output generation identity count mismatch")
    managed_identities: list[tuple[str, PathIdentity]] = []
    for raw_row, entry in zip(identity_rows, inventory.entries, strict=True):
        if not isinstance(raw_row, list):
            raise OSError("Invalid managed-output generation identity row")
        row = cast(list[object], raw_row)
        if len(row) != 3 or row[0] != entry.path:
            raise OSError("Invalid managed-output generation identity row")
        managed_identities.append(
            (
                entry.path,
                _identity([row[1], row[2]], "managed-output file identity"),
            )
        )
    evidence = _mapping(payload["evidence"], "managed-output evidence receipts")
    _exact_keys(
        evidence,
        frozenset({"attempt", "manifest"}),
        "managed-output evidence receipts",
    )
    record = _GenerationRecord(
        transaction_id=transaction_id,
        role=cast(GenerationRole, payload["role"]),
        destination_identity=_identity(
            payload["destination_identity"],
            "managed-output generation destination identity",
        ),
        inventory=inventory,
        managed_identities=tuple(managed_identities),
        attempt=_evidence_value_from_payload(
            evidence["attempt"],
            expected_path=CONVERSION_ATTEMPT_RELATIVE_PATH.replace(os.sep, "/"),
            description="managed-output attempt receipt",
        ),
        manifest=_evidence_value_from_payload(
            evidence["manifest"],
            expected_path=CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"),
            description="managed-output manifest receipt",
        ),
    )
    if content != _generation_record_content_for_receipts(record):
        raise OSError("Managed-output generation record changed")
    return record


def _generation_record_content_for_receipts(record: _GenerationRecord) -> bytes:
    def receipt_payload(value: _EvidenceValue) -> dict[str, object]:
        receipt = _evidence_receipt(value)
        return {
            "path": value.path,
            "present": receipt is not None,
            "identity": (
                None
                if value.identity is None
                else _identity_payload(value.identity)
            ),
            "mode": None if receipt is None else receipt.mode,
            "byte_count": 0 if receipt is None else receipt.byte_count,
            "sha256": None if receipt is None else receipt.sha256,
        }

    return _canonical_json_bytes(
        {
            "format_version": _FORMAT_VERSION,
            "kind": "gm2godot-managed-output-generation-record",
            "transaction_id": record.transaction_id,
            "role": record.role,
            "destination_identity": _identity_payload(
                record.destination_identity
            ),
            "inventory": record.inventory.to_dict(),
            "managed_identities": [
                [path, *_identity_payload(identity)]
                for path, identity in record.managed_identities
            ],
            "evidence": {
                "attempt": receipt_payload(record.attempt),
                "manifest": receipt_payload(record.manifest),
            },
        }
    )


def _pointer_payload(pointer: _Pointer) -> dict[str, object]:
    return {
        "format_version": _FORMAT_VERSION,
        "kind": "gm2godot-managed-output-generation",
        "state": "committed",
        "transaction_id": pointer.transaction_id,
        "destination_identity": _identity_payload(pointer.destination_identity),
        "journal_sha256": pointer.journal_sha256,
        "generation_record": pointer.generation_record.to_dict(),
    }


def _pointer_content(pointer: _Pointer) -> bytes:
    content = _canonical_json_bytes(_pointer_payload(pointer))
    if len(content) > _POINTER_MAX_BYTES:
        raise OSError(
            f"Managed-output generation pointer exceeds {_POINTER_MAX_BYTES} bytes"
        )
    return content


def _pointer_from_content(content: bytes) -> _Pointer:
    payload = _decode_canonical_json(
        content,
        description="managed-output generation pointer",
        maximum=_POINTER_MAX_BYTES,
    )
    _exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "kind",
                "state",
                "transaction_id",
                "destination_identity",
                "journal_sha256",
                "generation_record",
            }
        ),
        "managed-output generation pointer",
    )
    if (
        payload["format_version"] != _FORMAT_VERSION
        or payload["kind"] != "gm2godot-managed-output-generation"
        or payload["state"] != "committed"
    ):
        raise OSError("Unsupported managed-output generation pointer")
    pointer = _Pointer(
        transaction_id=_transaction_id(
            payload["transaction_id"],
            "managed-output pointer transaction",
        ),
        destination_identity=_identity(
            payload["destination_identity"],
            "managed-output pointer destination identity",
        ),
        journal_sha256=_digest(
            payload["journal_sha256"],
            "managed-output pointer journal digest",
        ),
        generation_record=_record_reference_from_payload(
            payload["generation_record"],
            "managed-output pointer generation record",
        ),
    )
    if content != _pointer_content(pointer):
        raise OSError("Managed-output generation pointer changed")
    return pointer


def _read_pointer(
    workspace: ManagedOutputWorkspace,
) -> _PointerSnapshot | None:
    try:
        receipt, content = _capture_file(
            workspace,
            workspace._staging_parent,
            MANAGED_OUTPUT_POINTER_NAME,
            maximum=_POINTER_MAX_BYTES,
            include_content=True,
        )
    except FileNotFoundError:
        return None
    if content is None:
        raise AssertionError("Pointer capture requested bytes")
    return _PointerSnapshot(
        identity=receipt.identity,
        mode=receipt.content.mode,
        content=content,
        pointer=_pointer_from_content(content),
    )


def _read_generation_record(
    workspace: ManagedOutputWorkspace,
    reference: _RecordReference,
) -> _GenerationRecord:
    receipt, content = _capture_file(
        workspace,
        workspace._staging_parent,
        reference.name,
        expected_identity=reference.identity,
        expected_content=_ContentReceipt(
            mode=reference.mode,
            byte_count=reference.byte_count,
            sha256=reference.sha256,
        ),
        maximum=_GENERATION_RECORD_MAX_BYTES,
        include_content=True,
    )
    if content is None:
        raise AssertionError("Generation-record capture requested bytes")
    if (
        receipt.identity != reference.identity
        or receipt.content.byte_count != reference.byte_count
        or receipt.content.sha256 != reference.sha256
        or not modes_match(receipt.content.mode, reference.mode)
    ):
        raise OSError(
            "Managed-output generation record no longer matches its pointer"
        )
    record = _generation_record_from_content(content)
    name_match = _GENERATION_RECORD_PATTERN.fullmatch(reference.name)
    if (
        name_match is None
        or record.transaction_id != name_match.group(1)
        or record.role != name_match.group(2)
    ):
        raise OSError(
            "Managed-output generation record name disagrees with its content"
        )
    return record


def _evidence_state_matches(
    actual: _EvidenceValue,
    expected: _EvidenceValue,
) -> bool:
    actual_receipt = _evidence_receipt(actual)
    expected_receipt = _evidence_receipt(expected)
    return (
        actual.path == expected.path
        and actual.identity == expected.identity
        and _content_receipts_match(actual_receipt, expected_receipt)
    )


def _capture_public_evidence(
    workspace: ManagedOutputWorkspace,
) -> tuple[_EvidenceValue, _EvidenceValue]:
    attempt_path = CONVERSION_ATTEMPT_RELATIVE_PATH.replace(os.sep, "/")
    manifest_path = CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/")
    attempt = _capture_optional_file(
        workspace,
        workspace._destination,
        attempt_path,
        maximum=_EVIDENCE_MAX_BYTES,
    )
    manifest = _capture_optional_file(
        workspace,
        workspace._destination,
        manifest_path,
        maximum=_EVIDENCE_MAX_BYTES,
    )
    return attempt, manifest


def _decode_evidence_json(content: bytes, description: str) -> dict[str, object]:
    return _decode_canonical_json(
        content,
        description=description,
        maximum=_EVIDENCE_MAX_BYTES,
    )


def _validate_evidence_pair(
    attempt: _EvidenceValue,
    manifest: _EvidenceValue,
    inventory: GenerationInventory,
    *,
    require_updated: bool,
) -> None:
    if not attempt.present:
        if manifest.present:
            raise OSError(
                "A canonical conversion manifest cannot exist without its "
                "latest-attempt record"
            )
        if inventory.entries:
            raise OSError(
                "A non-empty managed generation requires canonical conversion "
                "evidence"
            )
        return
    if attempt.content is None:
        raise ValueError("Evidence validation requires actual attempt bytes")
    attempt_payload = _decode_evidence_json(
        attempt.content,
        "conversion attempt evidence",
    )
    canonical = _mapping(
        attempt_payload.get("canonical_manifest"),
        "conversion attempt canonical-manifest record",
    )
    expected_manifest_path = CONVERSION_MANIFEST_RELATIVE_PATH.replace(
        os.sep,
        "/",
    )
    if canonical.get("path") != expected_manifest_path:
        raise OSError("Conversion attempt names an unexpected canonical manifest")
    if not manifest.present:
        if (
            canonical.get("status") != "absent"
            or canonical.get("updated") is not False
            or canonical.get("current_output") != "unavailable"
            or canonical.get("sha256") is not None
        ):
            raise OSError(
                "Conversion attempt disagrees with absent canonical evidence"
            )
        if inventory.entries:
            raise OSError(
                "A non-empty managed generation cannot select an absent manifest"
            )
        return
    if manifest.content is None:
        raise ValueError("Evidence validation requires actual manifest bytes")
    manifest_payload = _decode_evidence_json(
        manifest.content,
        "canonical conversion manifest",
    )
    try:
        manifest_inventory = GenerationInventory.from_value(
            manifest_payload.get("generation_inventory")
        )
    except OSError as error:
        raise OSError(
            "Canonical conversion manifest has an invalid generation inventory"
        ) from error
    if manifest_inventory != inventory:
        raise OSError(
            "Canonical conversion manifest does not describe the frozen "
            "managed generation"
        )
    manifest_digest = _sha256_bytes(manifest.content)
    status = canonical.get("status")
    updated = canonical.get("updated")
    current_output = canonical.get("current_output")
    if require_updated:
        consistent = (
            status == "updated"
            and updated is True
            and current_output == "verified"
        )
    else:
        consistent = (
            status == "updated"
            and updated is True
            and current_output == "verified"
        ) or (
            status == "preserved"
            and updated is False
            and current_output in {"unverified", "verified"}
        )
    if not consistent or canonical.get("sha256") != manifest_digest:
        raise OSError(
            "Conversion attempt and canonical manifest evidence disagree"
        )


def _verify_generation_record(
    workspace: ManagedOutputWorkspace,
    record: _GenerationRecord,
) -> tuple[_EvidenceValue, _EvidenceValue]:
    if record.destination_identity != workspace._destination.identity:
        raise OSError(
            "Managed-output generation record belongs to another destination"
        )
    validate_generation_inventory(
        workspace.destination_path,
        record.inventory,
    )
    identities = dict(record.managed_identities)
    if identities.keys() != record.inventory.by_path().keys():
        raise OSError("Managed-output generation record identities are incomplete")
    for entry in record.inventory.entries:
        receipt, _content = _capture_file(
            workspace,
            workspace._destination,
            entry.path,
            expected_identity=identities[entry.path],
            expected_content=_ContentReceipt.from_entry(entry),
        )
        if receipt.identity != identities[entry.path]:
            raise OSError(
                f"Managed-output generation identity changed: {entry.path!r}"
            )
    attempt, manifest = _capture_public_evidence(workspace)
    if not _evidence_state_matches(attempt, record.attempt) or not (
        _evidence_state_matches(manifest, record.manifest)
    ):
        raise OSError(
            "Public conversion evidence no longer matches the selected "
            "managed generation"
        )
    _validate_evidence_pair(
        attempt,
        manifest,
        record.inventory,
        require_updated=False,
    )
    workspace._verify_base()
    return attempt, manifest


def _verify_pointer_generation(
    workspace: ManagedOutputWorkspace,
    snapshot: _PointerSnapshot,
) -> _GenerationRecord:
    pointer = snapshot.pointer
    if pointer.destination_identity != workspace._destination.identity:
        raise OSError(
            "Managed-output generation pointer belongs to another destination"
        )
    if pointer.generation_record.name == MANAGED_OUTPUT_POINTER_NAME:
        raise OSError("Managed-output generation pointer is self-referential")
    record = _read_generation_record(
        workspace,
        pointer.generation_record,
    )
    if (
        record.transaction_id != pointer.transaction_id
        or record.role != "desired"
    ):
        raise OSError(
            "Managed-output pointer and generation record transaction disagree"
        )
    _verify_generation_record(workspace, record)
    return record


def _pointer_snapshot_payload(
    snapshot: _PointerSnapshot | None,
) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "identity": _identity_payload(snapshot.identity),
        "mode": snapshot.mode,
        "byte_count": len(snapshot.content),
        "sha256": _sha256_bytes(snapshot.content),
        "content_base64": base64.b64encode(snapshot.content).decode("ascii"),
    }


def _pointer_snapshot_from_payload(
    value: object,
) -> _PointerSnapshot | None:
    if value is None:
        return None
    payload = _mapping(value, "managed-output previous pointer")
    _exact_keys(
        payload,
        frozenset(
            {"identity", "mode", "byte_count", "sha256", "content_base64"}
        ),
        "managed-output previous pointer",
    )
    byte_count = _bounded_integer(
        payload["byte_count"],
        "managed-output previous pointer byte count",
        maximum=_POINTER_MAX_BYTES,
    )
    encoded = payload["content_base64"]
    if not isinstance(encoded, str):
        raise OSError("Invalid managed-output previous pointer bytes")
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise OSError("Invalid managed-output previous pointer bytes") from error
    digest = _digest(
        payload["sha256"],
        "managed-output previous pointer digest",
    )
    if len(content) != byte_count or _sha256_bytes(content) != digest:
        raise OSError("Managed-output previous pointer content mismatch")
    return _PointerSnapshot(
        identity=_identity(
            payload["identity"],
            "managed-output previous pointer identity",
        ),
        mode=_mode(payload["mode"], "managed-output previous pointer mode"),
        content=content,
        pointer=_pointer_from_content(content),
    )


def _journal_payload(journal: _Journal) -> dict[str, object]:
    return {
        "format_version": _FORMAT_VERSION,
        "kind": "gm2godot-managed-output-transaction",
        "state": "prepared",
        "transaction_id": journal.transaction_id,
        "destination_identity": _identity_payload(journal.destination_identity),
        "workspace_parent_identity": _identity_payload(
            journal.workspace_parent_identity
        ),
        "stage_identity": _identity_payload(journal.stage_identity),
        "publication_identity": _identity_payload(journal.publication_identity),
        "previous_record": journal.previous_record.to_dict(),
        "desired_record": journal.desired_record.to_dict(),
        "previous_pointer": _pointer_snapshot_payload(journal.previous_pointer),
        "pointer_stage_identity": _identity_payload(
            journal.pointer_stage_identity
        ),
        "directories": [directory.to_dict() for directory in journal.directories],
        "transitions": [
            transition.to_dict() for transition in journal.transitions
        ],
    }


def _journal_content(journal: _Journal) -> bytes:
    content = _canonical_json_bytes(_journal_payload(journal))
    if len(content) > _JOURNAL_MAX_BYTES:
        raise OSError(
            f"Managed-output transaction journal exceeds {_JOURNAL_MAX_BYTES} bytes"
        )
    return content


def _directory_state_from_payload(value: object) -> _DirectoryState:
    payload = _mapping(value, "managed-output directory state")
    _exact_keys(
        payload,
        frozenset({"path", "disposition", "identity", "mode", "stage_path"}),
        "managed-output directory state",
    )
    path_value = payload["path"]
    disposition = payload["disposition"]
    stage_path = payload["stage_path"]
    if not isinstance(path_value, str):
        raise OSError("Invalid managed-output directory path")
    path = _safe_relative_path(path_value, "managed-output directory path")
    if disposition not in {"existing", "staged"}:
        raise OSError("Invalid managed-output directory disposition")
    expected_stage = (
        None
        if disposition == "existing"
        else f"{_DIRECTORY_STAGE_ROOT}/{path}"
    )
    if stage_path != expected_stage:
        raise OSError("Invalid managed-output directory stage path")
    return _DirectoryState(
        path=path,
        disposition=cast(DirectoryDisposition, disposition),
        identity=_identity(
            payload["identity"],
            "managed-output directory identity",
        ),
        mode=_mode(payload["mode"], "managed-output directory mode"),
        stage_path=cast(str | None, stage_path),
    )


def _transition_private_paths(
    path: str,
    kind: TransitionKind,
) -> tuple[str, str, str]:
    if kind == "managed":
        suffix = path
        desired_stage = path
    elif kind == "attempt":
        suffix = "conversion_attempt.json"
        desired_stage = f"{_EVIDENCE_ROOT}/desired-attempt.json"
    else:
        suffix = "conversion_manifest.json"
        desired_stage = f"{_EVIDENCE_ROOT}/desired-manifest.json"
    return (
        f"{_BACKUP_ROOT}/{suffix}",
        desired_stage,
        f"{_DISPLACED_ROOT}/{suffix}",
    )


def _transition_from_payload(value: object) -> _Transition:
    payload = _mapping(value, "managed-output transition")
    _exact_keys(
        payload,
        frozenset(
            {
                "path",
                "kind",
                "previous",
                "desired",
                "previous_public_identity",
                "backup",
                "desired_stage",
                "backup_path",
                "desired_stage_path",
                "displaced_path",
            }
        ),
        "managed-output transition",
    )
    path_value = payload["path"]
    kind_value = payload["kind"]
    if not isinstance(path_value, str) or kind_value not in {
        "managed",
        "attempt",
        "manifest",
    }:
        raise OSError("Invalid managed-output transition path or kind")
    path = _safe_relative_path(path_value, "managed-output transition path")
    kind = cast(TransitionKind, kind_value)
    if kind == "managed":
        try:
            normalized = normalize_generation_inventory_path(path)
        except ValueError as error:
            raise OSError(str(error)) from error
        if normalized != path:
            raise OSError("Managed-output transition path is not canonical")
    elif path != (
        CONVERSION_ATTEMPT_RELATIVE_PATH.replace(os.sep, "/")
        if kind == "attempt"
        else CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/")
    ):
        raise OSError("Invalid managed-output evidence transition path")
    previous = (
        None
        if payload["previous"] is None
        else _content_receipt_from_payload(
            payload["previous"],
            "managed-output previous content",
        )
    )
    desired = (
        None
        if payload["desired"] is None
        else _content_receipt_from_payload(
            payload["desired"],
            "managed-output desired content",
        )
    )
    previous_identity_value = payload["previous_public_identity"]
    previous_identity = (
        None
        if previous_identity_value is None
        else _identity(
            previous_identity_value,
            "managed-output previous public identity",
        )
    )
    backup_path, desired_stage_path, displaced_path = (
        _transition_private_paths(path, kind)
    )
    if (
        payload["backup_path"] != backup_path
        or payload["desired_stage_path"] != desired_stage_path
        or payload["displaced_path"] != displaced_path
    ):
        raise OSError("Invalid managed-output transition private paths")
    backup = (
        None
        if payload["backup"] is None
        else _file_receipt_from_payload(
            payload["backup"],
            expected_path=backup_path,
            description="managed-output backup receipt",
        )
    )
    desired_stage = (
        None
        if payload["desired_stage"] is None
        else _file_receipt_from_payload(
            payload["desired_stage"],
            expected_path=desired_stage_path,
            description="managed-output desired-stage receipt",
        )
    )
    if (
        (previous is None)
        != (previous_identity is None)
        or (previous is None) != (backup is None)
        or (desired is None) != (desired_stage is None)
        or (
            backup is not None
            and not _content_receipts_match(previous, backup.content)
        )
        or (
            desired_stage is not None
            and not _content_receipts_match(desired, desired_stage.content)
        )
    ):
        raise OSError("Inconsistent managed-output transition receipts")
    return _Transition(
        path=path,
        kind=kind,
        previous=previous,
        desired=desired,
        previous_public_identity=previous_identity,
        backup=backup,
        desired_stage=desired_stage,
        backup_path=backup_path,
        desired_stage_path=desired_stage_path,
        displaced_path=displaced_path,
    )


def _journal_from_content(content: bytes) -> _Journal:
    payload = _decode_canonical_json(
        content,
        description="managed-output transaction journal",
        maximum=_JOURNAL_MAX_BYTES,
    )
    _exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "kind",
                "state",
                "transaction_id",
                "destination_identity",
                "workspace_parent_identity",
                "stage_identity",
                "publication_identity",
                "previous_record",
                "desired_record",
                "previous_pointer",
                "pointer_stage_identity",
                "directories",
                "transitions",
            }
        ),
        "managed-output transaction journal",
    )
    if (
        payload["format_version"] != _FORMAT_VERSION
        or payload["kind"] != "gm2godot-managed-output-transaction"
        or payload["state"] != "prepared"
    ):
        raise OSError("Unsupported managed-output transaction journal")
    raw_directories = payload["directories"]
    raw_transitions = payload["transitions"]
    if not isinstance(raw_directories, list) or not isinstance(
        raw_transitions,
        list,
    ):
        raise OSError("Invalid managed-output transaction lists")
    directory_values = cast(list[object], raw_directories)
    transition_values = cast(list[object], raw_transitions)
    if len(directory_values) > GENERATION_INVENTORY_MAX_ENTRIES * 2 or len(
        transition_values
    ) > GENERATION_INVENTORY_MAX_ENTRIES + 2:
        raise OSError("Managed-output transaction journal contains too many paths")
    directories = tuple(
        _directory_state_from_payload(value)
        for value in directory_values
    )
    transitions = tuple(
        _transition_from_payload(value)
        for value in transition_values
    )
    if tuple(sorted(directories, key=lambda item: item.path)) != directories:
        raise OSError("Managed-output journal directories are not sorted")
    transition_keys = tuple(
        (
            1 if transition.kind == "attempt" else 2 if transition.kind == "manifest" else 0,
            transition.path,
        )
        for transition in transitions
    )
    if transition_keys != tuple(sorted(transition_keys)):
        raise OSError("Managed-output journal transitions are not sorted")
    if len({directory.path.casefold() for directory in directories}) != len(
        directories
    ) or len({transition.path.casefold() for transition in transitions}) != len(
        transitions
    ):
        raise OSError("Managed-output journal contains colliding paths")
    journal = _Journal(
        transaction_id=_transaction_id(
            payload["transaction_id"],
            "managed-output journal transaction",
        ),
        destination_identity=_identity(
            payload["destination_identity"],
            "managed-output journal destination identity",
        ),
        workspace_parent_identity=_identity(
            payload["workspace_parent_identity"],
            "managed-output journal workspace-parent identity",
        ),
        stage_identity=_identity(
            payload["stage_identity"],
            "managed-output journal stage identity",
        ),
        publication_identity=_identity(
            payload["publication_identity"],
            "managed-output journal publication identity",
        ),
        previous_record=_record_reference_from_payload(
            payload["previous_record"],
            "managed-output previous generation record",
        ),
        desired_record=_record_reference_from_payload(
            payload["desired_record"],
            "managed-output desired generation record",
        ),
        previous_pointer=_pointer_snapshot_from_payload(
            payload["previous_pointer"]
        ),
        pointer_stage_identity=_identity(
            payload["pointer_stage_identity"],
            "managed-output pointer stage identity",
        ),
        directories=directories,
        transitions=transitions,
    )
    if content != _journal_content(journal):
        raise OSError("Managed-output transaction journal changed")
    return journal


def _read_journal(
    workspace: ManagedOutputWorkspace,
) -> tuple[_FileReceipt, bytes, _Journal] | None:
    try:
        receipt, content = _capture_file(
            workspace,
            workspace._staging_parent,
            MANAGED_OUTPUT_JOURNAL_NAME,
            maximum=_JOURNAL_MAX_BYTES,
            include_content=True,
        )
    except FileNotFoundError:
        return None
    if content is None:
        raise AssertionError("Journal capture requested bytes")
    journal = _journal_from_content(content)
    if (
        journal.destination_identity != workspace._destination.identity
        or journal.workspace_parent_identity
        != workspace._staging_parent.identity
    ):
        raise OSError(
            "Managed-output journal belongs to another destination or "
            "workspace parent"
        )
    return receipt, content, journal


def _capture_directory(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
) -> tuple[PathIdentity, int]:
    bindings, parent, leaf = _open_relative_parent(
        workspace,
        root,
        relative_path,
        create=False,
        description="managed-output publication directory",
    )
    child: VerifiedDirectory | None = None
    try:
        path = parent.child_path(leaf)
        path_stat = parent.stat(leaf)
        if workspace_module._path_is_redirected(
            path,
            path_stat,
        ) or not stat.S_ISDIR(path_stat.st_mode):
            raise OSError(
                "Refusing redirected or non-directory managed-output "
                f"publication path: {path}"
            )
        identity = path_stat.st_dev, path_stat.st_ino
        child = parent.open_child(
            leaf,
            expected_identity=identity,
            description="managed-output publication directory",
        )
        workspace_module._verify_binding_boundary(
            child,
            expected_device=workspace._destination_device,
            expected_mount_id=workspace._destination_mount_id,
        )
        return identity, stat.S_IMODE(path_stat.st_mode)
    finally:
        if child is not None:
            child.close()
        _close_bindings(workspace, bindings)


def _required_directory_paths(paths: Iterable[str]) -> tuple[str, ...]:
    directories: set[str] = set()
    for path in paths:
        components = _safe_relative_path(
            path,
            "managed-output public path",
        ).split("/")
        for count in range(1, len(components)):
            directories.add("/".join(components[:count]))
    return tuple(sorted(directories))


def _path_is_within(path: str, ancestor: str) -> bool:
    return path == ancestor or path.startswith(ancestor + "/")


def _prepare_directory_states(
    workspace: ManagedOutputWorkspace,
    public_paths: Iterable[str],
) -> tuple[_DirectoryState, ...]:
    required = _required_directory_paths(public_paths)
    missing_roots: list[str] = []
    existing: dict[str, _DirectoryState] = {}
    for path in sorted(required, key=lambda value: (value.count("/"), value)):
        if any(_path_is_within(path, root) for root in missing_roots):
            continue
        try:
            identity, mode = _capture_directory(
                workspace,
                workspace._destination,
                path,
            )
        except FileNotFoundError:
            missing_roots.append(path)
            continue
        existing[path] = _DirectoryState(
            path=path,
            disposition="existing",
            identity=identity,
            mode=mode,
            stage_path=None,
        )

    stage = workspace._require_stage()
    with _ensure_private_directory(
        workspace,
        stage,
        _DIRECTORY_STAGE_ROOT,
    ):
        pass
    staged: dict[str, _DirectoryState] = {}
    for path in required:
        if not any(_path_is_within(path, root) for root in missing_roots):
            continue
        stage_path = f"{_DIRECTORY_STAGE_ROOT}/{path}"
        with _ensure_private_directory(
            workspace,
            stage,
            stage_path,
            mode=0o755,
        ) as directory:
            directory.sync()
            staged[path] = _DirectoryState(
                path=path,
                disposition="staged",
                identity=directory.identity,
                mode=stat.S_IMODE(
                    workspace_module._binding_stat(directory).st_mode
                ),
                stage_path=stage_path,
            )
    states = tuple(
        sorted(
            (*existing.values(), *staged.values()),
            key=lambda value: value.path,
        )
    )
    if {state.path for state in states} != set(required):
        raise OSError("Managed-output directory plan is incomplete")
    return states


def _staged_directory_roots(
    directories: tuple[_DirectoryState, ...],
) -> tuple[_DirectoryState, ...]:
    staged_paths = {
        directory.path
        for directory in directories
        if directory.disposition == "staged"
    }
    return tuple(
        directory
        for directory in directories
        if directory.disposition == "staged"
        and (
            directory.path.rpartition("/")[0] not in staged_paths
        )
    )


def _verify_directory_state(
    workspace: ManagedOutputWorkspace,
    state: _DirectoryState,
) -> None:
    identity, mode = _capture_directory(
        workspace,
        workspace._destination,
        state.path,
    )
    if identity != state.identity or not modes_match(mode, state.mode):
        raise OSError(
            f"Managed-output directory changed: {state.path!r}"
        )


def _verify_transition_directories(
    workspace: ManagedOutputWorkspace,
    directories: tuple[_DirectoryState, ...],
    path: str,
) -> None:
    parent = path.rpartition("/")[0]
    for state in directories:
        if parent == state.path or parent.startswith(state.path + "/"):
            _verify_directory_state(workspace, state)
    workspace._verify_base()


def _verify_all_directories(
    workspace: ManagedOutputWorkspace,
    directories: tuple[_DirectoryState, ...],
) -> None:
    for directory in directories:
        _verify_directory_state(workspace, directory)
    workspace._verify_base()


def _sync_stage_directories(
    workspace: ManagedOutputWorkspace,
    paths: Iterable[str],
) -> None:
    stage = workspace._require_stage()
    directories = _required_directory_paths(paths)
    for path in sorted(
        directories,
        key=lambda value: (value.count("/"), value),
        reverse=True,
    ):
        bindings, parent, leaf = _open_relative_parent(
            workspace,
            stage,
            path,
            create=False,
            description="managed-output staged directory",
        )
        child: VerifiedDirectory | None = None
        try:
            path_stat = parent.stat(leaf)
            if (
                workspace_module._path_is_redirected(
                    parent.child_path(leaf),
                    path_stat,
                )
                or not stat.S_ISDIR(path_stat.st_mode)
            ):
                raise OSError(
                    f"Managed-output staged directory changed: {path!r}"
                )
            child = parent.open_child(
                leaf,
                expected_identity=(path_stat.st_dev, path_stat.st_ino),
                description="managed-output staged directory",
            )
            workspace_module._verify_binding_boundary(
                child,
                expected_device=workspace._destination_device,
                expected_mount_id=workspace._destination_mount_id,
            )
            child.sync()
        finally:
            if child is not None:
                child.close()
            _close_bindings(workspace, bindings)
    stage.sync()


def _native_rename_noreplace(
    source_parent: VerifiedDirectory,
    source_name: str,
    destination_parent: VerifiedDirectory,
    destination_name: str,
) -> None:
    if (
        source_parent.strategy == "posix_dir_fd"
        and destination_parent.strategy == "posix_dir_fd"
    ):
        if sys.platform == "darwin":
            function_name = "renameatx_np"
            exclusive_flag = 0x00000004
        elif sys.platform.startswith("linux"):
            function_name = "renameat2"
            exclusive_flag = 1
        else:
            raise OSError(
                "Atomic non-replacing managed-output rename is unavailable on "
                + sys.platform
            )
        libc = ctypes.CDLL(None, use_errno=True)
        raw_function = getattr(libc, function_name, None)
        if raw_function is None:
            raise OSError(
                "Atomic non-replacing managed-output rename is unavailable: "
                + function_name
            )
        rename_function = cast(
            Callable[[int, bytes, int, bytes, int], int],
            raw_function,
        )
        ctypes.set_errno(0)
        result = rename_function(
            source_parent.descriptor,
            os.fsencode(source_name),
            destination_parent.descriptor,
            os.fsencode(destination_name),
            exclusive_flag,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(
                error_number,
                os.strerror(error_number),
                destination_parent.child_path(destination_name),
            )
        return
    if (
        source_parent.strategy == "windows_handle"
        and destination_parent.strategy == "windows_handle"
    ):
        source_parent.verify_path()
        destination_parent.verify_path()
        workspace_module._rename_noreplace_windows(
            source_parent.child_path(source_name),
            destination_parent.child_path(destination_name),
        )
        source_parent.verify_path()
        destination_parent.verify_path()
        return
    raise OSError(
        "Strong same-filesystem managed-output namespace moves are unavailable "
        f"for {source_parent.strategy}/{destination_parent.strategy}"
    )


def _move_exact_noreplace(
    workspace: ManagedOutputWorkspace,
    *,
    source_root: VerifiedDirectory,
    source_path: str,
    destination_root: VerifiedDirectory,
    destination_path: str,
    expected_identity: PathIdentity,
    expect_directory: bool,
    phase: str,
) -> None:
    source_bindings, source_parent, source_leaf = _open_relative_parent(
        workspace,
        source_root,
        source_path,
        create=False,
        description="managed-output move source",
    )
    destination_bindings, destination_parent, destination_leaf = (
        _open_relative_parent(
            workspace,
            destination_root,
            destination_path,
            create=False,
            description="managed-output move destination",
        )
    )
    moved = False
    mode_changed = False
    original_mode = 0
    expected_kind = stat.S_ISDIR if expect_directory else stat.S_ISREG
    try:
        source_stat = source_parent.stat(source_leaf)
        source_display = source_parent.child_path(source_leaf)
        destination_display = destination_parent.child_path(destination_leaf)
        if (
            workspace_module._path_is_redirected(source_display, source_stat)
            or not expected_kind(source_stat.st_mode)
            or (source_stat.st_dev, source_stat.st_ino) != expected_identity
            or source_stat.st_dev != workspace._destination_device
            or (not expect_directory and source_stat.st_nlink != 1)
        ):
            raise OSError(
                f"Managed-output move source changed: {source_display}"
            )
        if destination_parent.lexists(destination_leaf):
            raise OSError(
                "Managed-output destination appeared and was preserved: "
                + destination_display
            )
        if not expect_directory:
            original_mode = stat.S_IMODE(source_stat.st_mode)
            mode_changed = (
                os.name == "nt"
                and not bool(original_mode & stat.S_IWUSR)
            )
            if mode_changed:
                source_parent.chmod_exact(
                    source_leaf,
                    expected_identity,
                    original_mode | stat.S_IWUSR,
                    require_single_link=True,
                )
        _before_managed_output_phase(phase, destination_display)
        current = source_parent.stat(source_leaf)
        if (
            workspace_module._path_is_redirected(source_display, current)
            or not expected_kind(current.st_mode)
            or (current.st_dev, current.st_ino) != expected_identity
            or (not expect_directory and current.st_nlink != 1)
        ):
            raise OSError(
                f"Managed-output move source changed before rename: {source_display}"
            )
        if destination_parent.lexists(destination_leaf):
            raise OSError(
                "Managed-output destination appeared and was preserved: "
                + destination_display
            )
        _native_rename_noreplace(
            source_parent,
            source_leaf,
            destination_parent,
            destination_leaf,
        )
        moved = True
        destination_stat = destination_parent.stat(destination_leaf)
        if (
            workspace_module._path_is_redirected(
                destination_display,
                destination_stat,
            )
            or not expected_kind(destination_stat.st_mode)
            or (destination_stat.st_dev, destination_stat.st_ino)
            != expected_identity
            or (not expect_directory and destination_stat.st_nlink != 1)
        ):
            raise OSError(
                "Managed-output move installed an unexpected entry: "
                + destination_display
            )
        if mode_changed:
            destination_parent.chmod_exact(
                destination_leaf,
                expected_identity,
                original_mode,
                require_single_link=True,
            )
            mode_changed = False
        source_parent.sync()
        if destination_parent.identity != source_parent.identity:
            destination_parent.sync()
        source_parent.verify_path()
        destination_parent.verify_path()
    except BaseException as error:
        if moved:
            try:
                if (
                    not source_parent.lexists(source_leaf)
                    and destination_parent.lexists(destination_leaf)
                ):
                    _native_rename_noreplace(
                        destination_parent,
                        destination_leaf,
                        source_parent,
                        source_leaf,
                    )
                    source_parent.sync()
                    if destination_parent.identity != source_parent.identity:
                        destination_parent.sync()
                    moved = False
            except BaseException as restore_error:
                error.add_note(
                    "Restoring the failed managed-output namespace move also "
                    f"failed: {restore_error}"
                )
        if mode_changed:
            try:
                selected_parent = (
                    destination_parent if moved else source_parent
                )
                selected_leaf = (
                    destination_leaf if moved else source_leaf
                )
                selected_parent.chmod_exact(
                    selected_leaf,
                    expected_identity,
                    original_mode,
                    require_single_link=True,
                )
            except BaseException as mode_error:
                error.add_note(
                    "Restoring the managed-output read-only mode also failed: "
                    f"{mode_error}"
                )
        raise
    finally:
        _close_bindings(workspace, destination_bindings)
        _close_bindings(workspace, source_bindings)


def _remove_file_exact(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
    expected_identity: PathIdentity,
) -> None:
    bindings, parent, leaf = _open_relative_parent(
        workspace,
        root,
        relative_path,
        create=False,
        description="managed-output private cleanup file",
    )
    try:
        current = parent.stat(leaf)
        if (
            workspace_module._path_is_redirected(
                parent.child_path(leaf),
                current,
            )
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != expected_identity
        ):
            raise OSError(
                "Managed-output cleanup file changed: "
                + parent.child_path(leaf)
            )
        if os.name == "nt" and not bool(
            stat.S_IMODE(current.st_mode) & stat.S_IWUSR
        ):
            parent.chmod_exact(
                leaf,
                expected_identity,
                stat.S_IMODE(current.st_mode) | stat.S_IWUSR,
                require_single_link=True,
            )
        completion_error = parent.unlink(
            leaf,
            expected_identity=expected_identity,
        )
        if completion_error is not None:
            raise completion_error
        parent.sync()
    finally:
        _close_bindings(workspace, bindings)


def _write_existing_bytes(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    relative_path: str,
    expected_identity: PathIdentity,
    content: bytes,
    *,
    mode: int,
) -> _FileReceipt:
    bindings, parent, leaf = _open_relative_parent(
        workspace,
        root,
        relative_path,
        create=False,
        description="managed-output private staged record",
    )
    descriptor = -1
    try:
        current = parent.stat(leaf)
        if (
            workspace_module._path_is_redirected(
                parent.child_path(leaf),
                current,
            )
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != expected_identity
        ):
            raise OSError(
                "Managed-output staged record changed: "
                + parent.child_path(leaf)
            )
        descriptor = parent.open_file(
            leaf,
            os.O_WRONLY
            | os.O_TRUNC
            | getattr(os, "O_BINARY", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != expected_identity
        ):
            raise OSError(
                "Managed-output staged record changed while opening: "
                + parent.child_path(leaf)
            )
        workspace_module._write_descriptor(descriptor, content)
        fchmod = getattr(os, "fchmod", None)
        if callable(fchmod):
            cast(Callable[[int, int], None], fchmod)(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if not callable(fchmod):
            parent.chmod_exact(
                leaf,
                expected_identity,
                mode,
                require_single_link=True,
            )
        parent.sync()
        receipt, _unused = _capture_file(
            workspace,
            root,
            relative_path,
            expected_identity=expected_identity,
            expected_content=_ContentReceipt.from_bytes(content, mode),
            durable=True,
        )
        return receipt
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _close_bindings(workspace, bindings)


def _record_reference(
    name: str,
    receipt: _FileReceipt,
) -> _RecordReference:
    return _RecordReference(
        name=name,
        identity=receipt.identity,
        mode=receipt.content.mode,
        byte_count=receipt.content.byte_count,
        sha256=receipt.content.sha256,
    )


def _verify_no_unexpected_parent_state(
    workspace: ManagedOutputWorkspace,
    pointer: _PointerSnapshot | None,
) -> None:
    allowed_records: set[str] = (
        set()
        if pointer is None
        else {pointer.pointer.generation_record.name}
    )
    for name in workspace._staging_parent.list_names():
        if name in {
            workspace_module.WORKSPACE_PARENT_MARKER_NAME,
            MANAGED_OUTPUT_POINTER_NAME,
        }:
            continue
        if name in {
            MANAGED_OUTPUT_JOURNAL_NAME,
            MANAGED_OUTPUT_RECOVERY_NAME,
        }:
            raise OSError(
                "Managed-output recovery must complete before another "
                f"publication: {workspace._staging_parent.child_path(name)}"
            )
        if _GENERATION_RECORD_PATTERN.fullmatch(name) is not None:
            if name not in allowed_records:
                raise OSError(
                    "Unknown managed-output generation record was preserved: "
                    + workspace._staging_parent.child_path(name)
                )
            continue
        if name.startswith(".gm2godot-managed-output-"):
            raise OSError(
                "Unknown managed-output transaction state was preserved: "
                + workspace._staging_parent.child_path(name)
            )


def _managed_identity_rows(
    inventory: GenerationInventory,
    receipts: Mapping[str, _FileReceipt],
) -> tuple[tuple[str, PathIdentity], ...]:
    if receipts.keys() != inventory.by_path().keys():
        raise OSError("Managed-output generation file identities are incomplete")
    return tuple(
        (entry.path, receipts[entry.path].identity)
        for entry in inventory.entries
    )


def _public_generation_record(
    workspace: ManagedOutputWorkspace,
    inventory: GenerationInventory,
    attempt: _EvidenceValue,
    manifest: _EvidenceValue,
    *,
    transaction_id: str,
    role: GenerationRole,
) -> tuple[_GenerationRecord, dict[str, _FileReceipt]]:
    receipts: dict[str, _FileReceipt] = {}
    for entry in inventory.entries:
        receipt, _content = _capture_file(
            workspace,
            workspace._destination,
            entry.path,
            expected_content=_ContentReceipt.from_entry(entry),
        )
        receipts[entry.path] = receipt
    return (
        _GenerationRecord(
            transaction_id=transaction_id,
            role=role,
            destination_identity=workspace._destination.identity,
            inventory=inventory,
            managed_identities=_managed_identity_rows(inventory, receipts),
            attempt=attempt,
            manifest=manifest,
        ),
        receipts,
    )


def _stage_desired_managed_files(
    workspace: ManagedOutputWorkspace,
    inventory: GenerationInventory,
) -> dict[str, _FileReceipt]:
    receipts: dict[str, _FileReceipt] = {}
    for entry in inventory.entries:
        receipt, _content = _capture_file(
            workspace,
            workspace._require_stage(),
            entry.path,
            expected_content=_ContentReceipt.from_entry(entry),
            durable=True,
        )
        receipts[entry.path] = receipt
    _sync_stage_directories(
        workspace,
        (entry.path for entry in inventory.entries),
    )
    return receipts


def _stage_evidence(
    workspace: ManagedOutputWorkspace,
    *,
    attempt_content: bytes | None,
    manifest_content: bytes | None,
    previous_attempt: _EvidenceValue,
    previous_manifest: _EvidenceValue,
) -> tuple[_EvidenceValue, _EvidenceValue, dict[str, _FileReceipt]]:
    values: list[tuple[TransitionKind, str, bytes | None, _EvidenceValue]] = [
        (
            "attempt",
            CONVERSION_ATTEMPT_RELATIVE_PATH.replace(os.sep, "/"),
            attempt_content,
            previous_attempt,
        ),
        (
            "manifest",
            CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"),
            manifest_content,
            previous_manifest,
        ),
    ]
    staged: dict[str, _FileReceipt] = {}
    desired_values: list[_EvidenceValue] = []
    for kind, public_path, content, previous in values:
        if content is None:
            desired_values.append(
                _EvidenceValue(public_path, None, None, None)
            )
            continue
        if len(content) > _EVIDENCE_MAX_BYTES:
            raise OSError(
                f"Managed-output {kind} evidence exceeds {_EVIDENCE_MAX_BYTES} bytes"
            )
        mode = 0o600 if previous.mode is None else previous.mode
        _backup_path, stage_path, _displaced_path = (
            _transition_private_paths(public_path, kind)
        )
        stage_receipt = _create_bytes_file(
            workspace,
            workspace._require_stage(),
            stage_path,
            content,
            mode=mode,
        )
        staged[public_path] = stage_receipt
        desired_values.append(
            _EvidenceValue(
                path=public_path,
                content=content,
                mode=mode,
                identity=stage_receipt.identity,
            )
        )
    return desired_values[0], desired_values[1], staged


def _final_evidence_value(
    previous: _EvidenceValue,
    staged: _EvidenceValue,
) -> _EvidenceValue:
    previous_receipt = _evidence_receipt(previous)
    desired_receipt = _evidence_receipt(staged)
    if _content_receipts_match(previous_receipt, desired_receipt):
        return _EvidenceValue(
            staged.path,
            staged.content,
            staged.mode,
            previous.identity,
        )
    return staged


def _final_managed_receipts(
    previous_inventory: GenerationInventory,
    desired_inventory: GenerationInventory,
    previous_receipts: Mapping[str, _FileReceipt],
    staged_receipts: Mapping[str, _FileReceipt],
) -> dict[str, _FileReceipt]:
    previous = previous_inventory.by_path()
    final: dict[str, _FileReceipt] = {}
    for entry in desired_inventory.entries:
        prior = previous.get(entry.path)
        if (
            prior is not None
            and _content_receipts_match(
                _ContentReceipt.from_entry(prior),
                _ContentReceipt.from_entry(entry),
            )
        ):
            final[entry.path] = previous_receipts[entry.path]
        else:
            final[entry.path] = staged_receipts[entry.path]
    return final


def _create_backup(
    workspace: ManagedOutputWorkspace,
    *,
    public_path: str,
    private_path: str,
    expected: _FileReceipt,
) -> _FileReceipt:
    return _copy_file_exact(
        workspace,
        workspace._destination,
        public_path,
        workspace._require_stage(),
        private_path,
        expected,
    )


def _prepare_transitions(
    workspace: ManagedOutputWorkspace,
    previous_inventory: GenerationInventory,
    desired_inventory: GenerationInventory,
    previous_receipts: Mapping[str, _FileReceipt],
    desired_stage_receipts: Mapping[str, _FileReceipt],
    previous_attempt: _EvidenceValue,
    previous_manifest: _EvidenceValue,
    desired_attempt: _EvidenceValue,
    desired_manifest: _EvidenceValue,
    desired_evidence_stages: Mapping[str, _FileReceipt],
) -> tuple[_Transition, ...]:
    previous_entries = previous_inventory.by_path()
    desired_entries = desired_inventory.by_path()
    transitions: list[_Transition] = []
    for path in sorted(previous_entries.keys() | desired_entries.keys()):
        previous_entry = previous_entries.get(path)
        desired_entry = desired_entries.get(path)
        backup_path, desired_stage_path, displaced_path = (
            _transition_private_paths(path, "managed")
        )
        prior_receipt = previous_receipts.get(path)
        backup = (
            None
            if prior_receipt is None
            else _create_backup(
                workspace,
                public_path=path,
                private_path=backup_path,
                expected=prior_receipt,
            )
        )
        transitions.append(
            _Transition(
                path=path,
                kind="managed",
                previous=(
                    None
                    if previous_entry is None
                    else _ContentReceipt.from_entry(previous_entry)
                ),
                desired=(
                    None
                    if desired_entry is None
                    else _ContentReceipt.from_entry(desired_entry)
                ),
                previous_public_identity=(
                    None if prior_receipt is None else prior_receipt.identity
                ),
                backup=backup,
                desired_stage=desired_stage_receipts.get(path),
                backup_path=backup_path,
                desired_stage_path=desired_stage_path,
                displaced_path=displaced_path,
            )
        )

    evidence_values = (
        ("attempt", previous_attempt, desired_attempt),
        ("manifest", previous_manifest, desired_manifest),
    )
    for raw_kind, previous, desired in evidence_values:
        kind = cast(TransitionKind, raw_kind)
        backup_path, desired_stage_path, displaced_path = (
            _transition_private_paths(desired.path, kind)
        )
        previous_receipt = _evidence_receipt(previous)
        public_receipt = (
            None
            if previous_receipt is None or previous.identity is None
            else _FileReceipt(
                relative_path=previous.path,
                identity=previous.identity,
                content=previous_receipt,
            )
        )
        backup = (
            None
            if public_receipt is None
            else _create_backup(
                workspace,
                public_path=previous.path,
                private_path=backup_path,
                expected=public_receipt,
            )
        )
        transitions.append(
            _Transition(
                path=desired.path,
                kind=kind,
                previous=previous_receipt,
                desired=_evidence_receipt(desired),
                previous_public_identity=previous.identity,
                backup=backup,
                desired_stage=desired_evidence_stages.get(desired.path),
                backup_path=backup_path,
                desired_stage_path=desired_stage_path,
                displaced_path=displaced_path,
            )
        )
    ordered = tuple(
        sorted(
            transitions,
            key=lambda transition: (
                1
                if transition.kind == "attempt"
                else 2
                if transition.kind == "manifest"
                else 0,
                transition.path,
            ),
        )
    )
    for transition in ordered:
        if transition.previous is None:
            continue
        displaced_parent = transition.displaced_path.rpartition("/")[0]
        if displaced_parent:
            with _ensure_private_directory(
                workspace,
                workspace._require_stage(),
                displaced_parent,
            ) as directory:
                directory.sync()
    return ordered


def _prepare_publication_root(
    workspace: ManagedOutputWorkspace,
) -> PathIdentity:
    stage = workspace._require_stage()
    if stage.lexists(_PUBLICATION_ROOT):
        raise OSError(
            "Unknown managed-output publication state was preserved: "
            + stage.child_path(_PUBLICATION_ROOT)
        )
    with _ensure_private_directory(
        workspace,
        stage,
        _PUBLICATION_ROOT,
    ) as publication:
        identity = publication.identity
        marker = _publication_marker_content(workspace, identity)
    _create_bytes_file(
        workspace,
        stage,
        f"{_PUBLICATION_ROOT}/{_PUBLICATION_MARKER}",
        marker,
        mode=0o600,
    )
    for path in (
        _BACKUP_ROOT,
        _DISPLACED_ROOT,
        _DIRECTORY_STAGE_ROOT,
        _EVIDENCE_ROOT,
    ):
        with _ensure_private_directory(workspace, stage, path) as directory:
            directory.sync()
    return identity


def _record_from_pointer_or_baseline(
    workspace: ManagedOutputWorkspace,
    previous_inventory: GenerationInventory,
    pointer: _PointerSnapshot | None,
) -> tuple[
    _GenerationRecord,
    _RecordReference | None,
    dict[str, _FileReceipt],
    _EvidenceValue,
    _EvidenceValue,
]:
    if pointer is not None:
        selected = _verify_pointer_generation(workspace, pointer)
        if selected.inventory != previous_inventory:
            raise OSError(
                "Frozen previous inventory disagrees with the committed "
                "managed-output generation"
            )
        public_record, receipts = _public_generation_record(
            workspace,
            previous_inventory,
            *_capture_public_evidence(workspace),
            transaction_id=selected.transaction_id,
            role="desired",
        )
        if (
            public_record.managed_identities
            != selected.managed_identities
            or not _evidence_state_matches(
                public_record.attempt,
                selected.attempt,
            )
            or not _evidence_state_matches(
                public_record.manifest,
                selected.manifest,
            )
        ):
            raise OSError(
                "Committed managed-output generation identities changed"
            )
        return (
            selected,
            pointer.pointer.generation_record,
            receipts,
            public_record.attempt,
            public_record.manifest,
        )
    attempt, manifest = _capture_public_evidence(workspace)
    _validate_evidence_pair(
        attempt,
        manifest,
        previous_inventory,
        require_updated=False,
    )
    record, receipts = _public_generation_record(
        workspace,
        previous_inventory,
        attempt,
        manifest,
        transaction_id=workspace.transaction_id,
        role="previous",
    )
    return record, None, receipts, attempt, manifest


def _create_stable_generation_record(
    workspace: ManagedOutputWorkspace,
    record: _GenerationRecord,
) -> tuple[_RecordReference, _FileReceipt]:
    name = _generation_record_name(record.transaction_id, record.role)
    receipt = _create_bytes_file(
        workspace,
        workspace._staging_parent,
        name,
        _generation_record_content(record),
        mode=0o600,
    )
    return _record_reference(name, receipt), receipt


def _prepare_publication(
    workspace: ManagedOutputWorkspace,
    *,
    previous_inventory: GenerationInventory,
    desired_inventory: GenerationInventory,
    attempt_content: bytes | None,
    manifest_content: bytes | None,
    require_updated: bool,
) -> _PreparedPublication:
    workspace.verify()
    validate_generation_inventory(
        workspace.destination_path,
        previous_inventory,
    )
    validate_staged_generation_inventory(workspace, desired_inventory)
    pointer = _read_pointer(workspace)
    _verify_no_unexpected_parent_state(workspace, pointer)
    (
        previous_record,
        existing_previous_reference,
        previous_receipts,
        previous_attempt,
        previous_manifest,
    ) = _record_from_pointer_or_baseline(
        workspace,
        previous_inventory,
        pointer,
    )
    publication_identity = _prepare_publication_root(workspace)
    stable_records: list[tuple[str, PathIdentity]] = []
    try:
        desired_stage_receipts = _stage_desired_managed_files(
            workspace,
            desired_inventory,
        )
        desired_attempt_staged, desired_manifest_staged, evidence_stages = (
            _stage_evidence(
                workspace,
                attempt_content=attempt_content,
                manifest_content=manifest_content,
                previous_attempt=previous_attempt,
                previous_manifest=previous_manifest,
            )
        )
        desired_attempt = _final_evidence_value(
            previous_attempt,
            desired_attempt_staged,
        )
        desired_manifest = _final_evidence_value(
            previous_manifest,
            desired_manifest_staged,
        )
        _validate_evidence_pair(
            _EvidenceValue(
                desired_attempt.path,
                desired_attempt.content,
                desired_attempt.mode,
                desired_attempt.identity,
            ),
            _EvidenceValue(
                desired_manifest.path,
                desired_manifest.content,
                desired_manifest.mode,
                desired_manifest.identity,
            ),
            desired_inventory,
            require_updated=require_updated,
        )
        transitions = _prepare_transitions(
            workspace,
            previous_inventory,
            desired_inventory,
            previous_receipts,
            desired_stage_receipts,
            previous_attempt,
            previous_manifest,
            desired_attempt_staged,
            desired_manifest_staged,
            evidence_stages,
        )
        directories = _prepare_directory_states(
            workspace,
            (transition.path for transition in transitions),
        )
        _sync_stage_directories(
            workspace,
            (
                transition.backup_path
                for transition in transitions
                if transition.backup is not None
            ),
        )
        final_receipts = _final_managed_receipts(
            previous_inventory,
            desired_inventory,
            previous_receipts,
            desired_stage_receipts,
        )
        desired_record = _GenerationRecord(
            transaction_id=workspace.transaction_id,
            role="desired",
            destination_identity=workspace._destination.identity,
            inventory=desired_inventory,
            managed_identities=_managed_identity_rows(
                desired_inventory,
                final_receipts,
            ),
            attempt=desired_attempt,
            manifest=desired_manifest,
        )
        if existing_previous_reference is None:
            previous_reference, previous_record_receipt = (
                _create_stable_generation_record(
                    workspace,
                    previous_record,
                )
            )
            stable_records.append(
                (
                    previous_reference.name,
                    previous_record_receipt.identity,
                )
            )
        else:
            previous_reference = existing_previous_reference
        desired_reference, desired_record_receipt = (
            _create_stable_generation_record(
                workspace,
                desired_record,
            )
        )
        stable_records.append(
            (desired_reference.name, desired_record_receipt.identity)
        )
        pointer_stage = _create_bytes_file(
            workspace,
            workspace._require_stage(),
            _POINTER_STAGE_PATH,
            b"",
            mode=0o600,
        )
        journal = _Journal(
            transaction_id=workspace.transaction_id,
            destination_identity=workspace._destination.identity,
            workspace_parent_identity=workspace._staging_parent.identity,
            stage_identity=workspace._stage_identity,
            publication_identity=publication_identity,
            previous_record=previous_reference,
            desired_record=desired_reference,
            previous_pointer=pointer,
            pointer_stage_identity=pointer_stage.identity,
            directories=directories,
            transitions=transitions,
        )
        journal_content = _journal_content(journal)
        desired_pointer = _Pointer(
            transaction_id=workspace.transaction_id,
            destination_identity=workspace._destination.identity,
            journal_sha256=_sha256_bytes(journal_content),
            generation_record=desired_reference,
        )
        desired_pointer_content = _pointer_content(desired_pointer)
        validate_staged_generation_inventory(workspace, desired_inventory)
        workspace.verify()
        return _PreparedPublication(
            journal=journal,
            journal_content=journal_content,
            desired_pointer=desired_pointer,
            desired_pointer_content=desired_pointer_content,
            desired_record=desired_record,
        )
    except BaseException as error:
        for name, identity in reversed(stable_records):
            try:
                _remove_file_exact(
                    workspace,
                    workspace._staging_parent,
                    name,
                    identity,
                )
            except BaseException as cleanup_error:
                error.add_note(
                    "Removing an uncommitted managed-output generation record "
                    f"also failed: {cleanup_error}"
                )
        raise


def _publish_journal(
    workspace: ManagedOutputWorkspace,
    prepared: _PreparedPublication,
) -> _FileReceipt:
    if workspace._staging_parent.lexists(MANAGED_OUTPUT_JOURNAL_NAME):
        raise OSError(
            "A managed-output transaction journal already requires recovery"
        )
    staged = _create_bytes_file(
        workspace,
        workspace._require_stage(),
        _JOURNAL_STAGE_PATH,
        prepared.journal_content,
        mode=0o600,
    )
    _before_managed_output_phase(
        "before_journal_publish",
        workspace._staging_parent.child_path(MANAGED_OUTPUT_JOURNAL_NAME),
    )
    _move_exact_noreplace(
        workspace,
        source_root=workspace._require_stage(),
        source_path=_JOURNAL_STAGE_PATH,
        destination_root=workspace._staging_parent,
        destination_path=MANAGED_OUTPUT_JOURNAL_NAME,
        expected_identity=staged.identity,
        expect_directory=False,
        phase="journal_publish",
    )
    receipt, content = _capture_file(
        workspace,
        workspace._staging_parent,
        MANAGED_OUTPUT_JOURNAL_NAME,
        expected_identity=staged.identity,
        expected_content=_ContentReceipt.from_bytes(
            prepared.journal_content,
            0o600,
        ),
        maximum=_JOURNAL_MAX_BYTES,
        include_content=True,
        durable=True,
    )
    if content != prepared.journal_content:
        raise OSError("Managed-output journal changed after publication")
    _before_managed_output_phase(
        "journal_durable",
        workspace._staging_parent.child_path(MANAGED_OUTPUT_JOURNAL_NAME),
    )
    return receipt


def _prepare_pointer_stage(
    workspace: ManagedOutputWorkspace,
    prepared: _PreparedPublication,
) -> _FileReceipt:
    receipt = _write_existing_bytes(
        workspace,
        workspace._require_stage(),
        _POINTER_STAGE_PATH,
        prepared.journal.pointer_stage_identity,
        prepared.desired_pointer_content,
        mode=0o600,
    )
    if receipt.identity != prepared.journal.pointer_stage_identity:
        raise OSError("Managed-output pointer stage identity changed")
    return receipt


def _verify_private_recovery_material(
    workspace: ManagedOutputWorkspace,
    prepared: _PreparedPublication,
    pointer_stage: _FileReceipt,
) -> None:
    workspace.verify()
    stage = workspace._require_stage()
    publication_identity, _publication_mode = _capture_directory(
        workspace,
        stage,
        _PUBLICATION_ROOT,
    )
    if publication_identity != prepared.journal.publication_identity:
        raise OSError("Managed-output publication state identity changed")
    marker_content = _publication_marker_content(
        workspace,
        publication_identity,
    )
    _capture_file(
        workspace,
        stage,
        f"{_PUBLICATION_ROOT}/{_PUBLICATION_MARKER}",
        expected_content=_ContentReceipt.from_bytes(marker_content, 0o600),
    )
    for transition in prepared.journal.transitions:
        if transition.backup is not None:
            _capture_file(
                workspace,
                stage,
                transition.backup_path,
                expected_identity=transition.backup.identity,
                expected_content=transition.backup.content,
            )
        if transition.desired_stage is not None:
            _capture_file(
                workspace,
                stage,
                transition.desired_stage_path,
                expected_identity=transition.desired_stage.identity,
                expected_content=transition.desired_stage.content,
            )
    for directory in prepared.journal.directories:
        if directory.disposition != "staged" or directory.stage_path is None:
            continue
        identity, mode = _capture_directory(
            workspace,
            stage,
            directory.stage_path,
        )
        if identity != directory.identity or not modes_match(
            mode,
            directory.mode,
        ):
            raise OSError(
                f"Managed-output staged directory changed: {directory.path!r}"
            )
    _read_generation_record(workspace, prepared.journal.previous_record)
    _read_generation_record(workspace, prepared.journal.desired_record)
    _capture_file(
        workspace,
        stage,
        _POINTER_STAGE_PATH,
        expected_identity=pointer_stage.identity,
        expected_content=_ContentReceipt.from_bytes(
            prepared.desired_pointer_content,
            0o600,
        ),
    )
    _verify_journal_unchanged(
        workspace,
        prepared.journal,
        prepared.journal_content,
    )


def _install_directory_roots(
    workspace: ManagedOutputWorkspace,
    directories: tuple[_DirectoryState, ...],
) -> None:
    for root in _staged_directory_roots(directories):
        if root.stage_path is None:
            raise AssertionError("A staged directory requires a private path")
        _move_exact_noreplace(
            workspace,
            source_root=workspace._require_stage(),
            source_path=root.stage_path,
            destination_root=workspace._destination,
            destination_path=root.path,
            expected_identity=root.identity,
            expect_directory=True,
            phase="before_directory_install",
        )
        _before_managed_output_phase(
            "directory_installed",
            os.path.join(workspace.destination_path, *root.path.split("/")),
        )
    _verify_all_directories(workspace, directories)


def _capture_transition_current(
    workspace: ManagedOutputWorkspace,
    transition: _Transition,
) -> _FileReceipt | None:
    try:
        receipt, _content = _capture_file(
            workspace,
            workspace._destination,
            transition.path,
        )
    except FileNotFoundError:
        return None
    return receipt


def _receipt_matches_expected(
    actual: _FileReceipt | None,
    expected_content: _ContentReceipt | None,
    expected_identity: PathIdentity | None,
) -> bool:
    if actual is None or expected_content is None or expected_identity is None:
        return (
            actual is None
            and expected_content is None
            and expected_identity is None
        )
    return actual.identity == expected_identity and _content_receipts_match(
        actual.content,
        expected_content,
    )


def _desired_public_identity(
    transition: _Transition,
) -> PathIdentity | None:
    if transition.desired is None:
        return None
    if transition.unchanged:
        return transition.previous_public_identity
    if transition.desired_stage is None:
        raise AssertionError("Present desired content requires a staged file")
    return transition.desired_stage.identity


def _verify_transition_previous(
    workspace: ManagedOutputWorkspace,
    transition: _Transition,
) -> None:
    actual = _capture_transition_current(workspace, transition)
    if not _receipt_matches_expected(
        actual,
        transition.previous,
        transition.previous_public_identity,
    ):
        raise OSError(
            "Managed-output public entry changed before publication: "
            + repr(transition.path)
        )


def _verify_transition_desired(
    workspace: ManagedOutputWorkspace,
    transition: _Transition,
) -> None:
    actual = _capture_transition_current(workspace, transition)
    if not _receipt_matches_expected(
        actual,
        transition.desired,
        _desired_public_identity(transition),
    ):
        raise OSError(
            "Managed-output desired entry is unavailable: "
            + repr(transition.path)
        )


def _install_transition(
    workspace: ManagedOutputWorkspace,
    transition: _Transition,
    directories: tuple[_DirectoryState, ...],
) -> None:
    _verify_transition_directories(
        workspace,
        directories,
        transition.path,
    )
    _verify_transition_previous(workspace, transition)
    if transition.unchanged:
        _verify_transition_desired(workspace, transition)
        return
    if (
        transition.previous is not None
        and transition.previous_public_identity is not None
    ):
        _move_exact_noreplace(
            workspace,
            source_root=workspace._destination,
            source_path=transition.path,
            destination_root=workspace._require_stage(),
            destination_path=transition.displaced_path,
            expected_identity=transition.previous_public_identity,
            expect_directory=False,
            phase="before_public_displace",
        )
        _before_managed_output_phase(
            "public_displaced",
            os.path.join(
                workspace.destination_path,
                *transition.path.split("/"),
            ),
        )
    if transition.desired is not None:
        if transition.desired_stage is None:
            raise AssertionError("Desired content requires a stage")
        _move_exact_noreplace(
            workspace,
            source_root=workspace._require_stage(),
            source_path=transition.desired_stage_path,
            destination_root=workspace._destination,
            destination_path=transition.path,
            expected_identity=transition.desired_stage.identity,
            expect_directory=False,
            phase="before_public_install",
        )
        _before_managed_output_phase(
            "public_installed",
            os.path.join(
                workspace.destination_path,
                *transition.path.split("/"),
            ),
        )
    _verify_transition_desired(workspace, transition)
    _verify_transition_directories(
        workspace,
        directories,
        transition.path,
    )


def _install_transitions(
    workspace: ManagedOutputWorkspace,
    prepared: _PreparedPublication,
) -> None:
    for transition in prepared.journal.transitions:
        _install_transition(
            workspace,
            transition,
            prepared.journal.directories,
        )


def _verify_journal_unchanged(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    content: bytes,
) -> _FileReceipt:
    record = _read_journal(workspace)
    if (
        record is None
        or record[1] != content
        or record[2] != journal
    ):
        raise OSError("Managed-output journal changed during publication")
    return record[0]


def _verify_desired_publication(
    workspace: ManagedOutputWorkspace,
    prepared: _PreparedPublication,
) -> None:
    for transition in prepared.journal.transitions:
        _verify_transition_desired(workspace, transition)
    _verify_all_directories(
        workspace,
        prepared.journal.directories,
    )
    _verify_generation_record(workspace, prepared.desired_record)
    _verify_journal_unchanged(
        workspace,
        prepared.journal,
        prepared.journal_content,
    )
    _before_managed_output_phase(
        "desired_generation_verified",
        workspace.destination_path,
    )


def _pointer_matches_snapshot(
    actual: _PointerSnapshot | None,
    expected: _PointerSnapshot | None,
) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return (
        actual.identity == expected.identity
        and modes_match(actual.mode, expected.mode)
        and actual.content == expected.content
        and actual.pointer == expected.pointer
    )


def _pointer_matches_desired(
    actual: _PointerSnapshot | None,
    desired: _Pointer,
    content: bytes,
    identity: PathIdentity,
) -> bool:
    return (
        actual is not None
        and actual.identity == identity
        and actual.content == content
        and actual.pointer == desired
    )


def _publish_commit_decision(
    workspace: ManagedOutputWorkspace,
    prepared: _PreparedPublication,
    pointer_stage: _FileReceipt,
) -> _PointerSnapshot:
    previous = prepared.journal.previous_pointer
    if previous is not None:
        current = _read_pointer(workspace)
        if not _pointer_matches_snapshot(current, previous):
            raise OSError(
                "Managed-output previous commit decision changed before commit"
            )
        _move_exact_noreplace(
            workspace,
            source_root=workspace._staging_parent,
            source_path=MANAGED_OUTPUT_POINTER_NAME,
            destination_root=workspace._require_stage(),
            destination_path=_POINTER_DISPLACED_PATH,
            expected_identity=previous.identity,
            expect_directory=False,
            phase="before_previous_pointer_displace",
        )
    elif _read_pointer(workspace) is not None:
        raise OSError("Managed-output commit decision appeared before commit")
    _before_managed_output_phase(
        "before_commit_decision",
        workspace._staging_parent.child_path(MANAGED_OUTPUT_POINTER_NAME),
    )
    _move_exact_noreplace(
        workspace,
        source_root=workspace._require_stage(),
        source_path=_POINTER_STAGE_PATH,
        destination_root=workspace._staging_parent,
        destination_path=MANAGED_OUTPUT_POINTER_NAME,
        expected_identity=pointer_stage.identity,
        expect_directory=False,
        phase="commit_decision",
    )
    current = _read_pointer(workspace)
    if not _pointer_matches_desired(
        current,
        prepared.desired_pointer,
        prepared.desired_pointer_content,
        pointer_stage.identity,
    ):
        raise OSError("Managed-output commit decision did not publish")
    _before_managed_output_phase(
        "commit_decision_published",
        workspace._staging_parent.child_path(MANAGED_OUTPUT_POINTER_NAME),
    )
    return cast(_PointerSnapshot, current)


def _capture_private_if_present(
    workspace: ManagedOutputWorkspace,
    stage: VerifiedDirectory,
    path: str,
    expected: _FileReceipt,
) -> _FileReceipt | None:
    try:
        receipt, _content = _capture_file(
            workspace,
            stage,
            path,
            expected_identity=expected.identity,
            expected_content=expected.content,
        )
    except FileNotFoundError:
        return None
    return receipt


def _rollback_transition(
    workspace: ManagedOutputWorkspace,
    stage: VerifiedDirectory,
    transition: _Transition,
) -> None:
    if transition.unchanged:
        _verify_transition_previous(workspace, transition)
        return
    current = _capture_transition_current(workspace, transition)
    desired_identity = _desired_public_identity(transition)
    if _receipt_matches_expected(
        current,
        transition.desired,
        desired_identity,
    ) and transition.desired is not None:
        if transition.desired_stage is None:
            raise AssertionError("Desired rollback requires a stage receipt")
        _move_exact_noreplace(
            workspace,
            source_root=workspace._destination,
            source_path=transition.path,
            destination_root=stage,
            destination_path=transition.desired_stage_path,
            expected_identity=transition.desired_stage.identity,
            expect_directory=False,
            phase="before_rollback_desired",
        )
        current = None
    elif not _receipt_matches_expected(
        current,
        transition.previous,
        transition.previous_public_identity,
    ) and current is not None:
        raise OSError(
            "Unknown public replacement was preserved during rollback: "
            + repr(transition.path)
        )

    if transition.previous is None:
        if _capture_transition_current(workspace, transition) is not None:
            raise OSError(
                f"Managed-output create did not roll back: {transition.path!r}"
            )
        return
    if _receipt_matches_expected(
        _capture_transition_current(workspace, transition),
        transition.previous,
        transition.previous_public_identity,
    ):
        return
    if transition.backup is None or transition.previous_public_identity is None:
        raise OSError("Managed-output rollback backup is incomplete")
    displaced = _capture_private_if_present(
        workspace,
        stage,
        transition.displaced_path,
        _FileReceipt(
            relative_path=transition.displaced_path,
            identity=transition.previous_public_identity,
            content=transition.previous,
        ),
    )
    if displaced is not None:
        source_path = transition.displaced_path
        source_identity = displaced.identity
    else:
        backup = _capture_private_if_present(
            workspace,
            stage,
            transition.backup_path,
            transition.backup,
        )
        if backup is None:
            raise OSError(
                f"Managed-output rollback material is unavailable: {transition.path!r}"
            )
        source_path = transition.backup_path
        source_identity = backup.identity
    _move_exact_noreplace(
        workspace,
        source_root=stage,
        source_path=source_path,
        destination_root=workspace._destination,
        destination_path=transition.path,
        expected_identity=source_identity,
        expect_directory=False,
        phase="before_rollback_previous",
    )
    restored = _capture_transition_current(workspace, transition)
    if restored is None or not _content_receipts_match(
        restored.content,
        transition.previous,
    ):
        raise OSError(
            f"Managed-output previous content was not restored: {transition.path!r}"
        )


def _verify_staged_directory_tree_empty(
    workspace: ManagedOutputWorkspace,
    root: _DirectoryState,
    directories: tuple[_DirectoryState, ...],
) -> None:
    expected = {
        state.path: state
        for state in directories
        if state.disposition == "staged"
        and _path_is_within(state.path, root.path)
    }
    for path, state in sorted(expected.items(), reverse=True):
        identity, mode = _capture_directory(
            workspace,
            workspace._destination,
            path,
        )
        if identity != state.identity or not modes_match(mode, state.mode):
            raise OSError(
                f"Managed-output created directory changed: {path!r}"
            )
        bindings, parent, leaf = _open_relative_parent(
            workspace,
            workspace._destination,
            path,
            create=False,
            description="managed-output created directory",
        )
        child: VerifiedDirectory | None = None
        try:
            child = parent.open_child(
                leaf,
                expected_identity=state.identity,
                description="managed-output created directory",
            )
            expected_children = {
                candidate.path.rsplit("/", 1)[-1]
                for candidate in expected.values()
                if candidate.path.rpartition("/")[0] == path
            }
            if set(child.list_names()) != expected_children:
                raise OSError(
                    "Managed-output created directory contains unknown entries: "
                    + repr(path)
                )
        finally:
            if child is not None:
                child.close()
            _close_bindings(workspace, bindings)


def _rollback_directories(
    workspace: ManagedOutputWorkspace,
    stage: VerifiedDirectory,
    directories: tuple[_DirectoryState, ...],
) -> None:
    for root in reversed(_staged_directory_roots(directories)):
        if root.stage_path is None:
            raise AssertionError("Staged directory root requires a path")
        try:
            public_identity, _mode_value = _capture_directory(
                workspace,
                workspace._destination,
                root.path,
            )
        except FileNotFoundError:
            try:
                staged_identity, _stage_mode = _capture_directory(
                    workspace,
                    stage,
                    root.stage_path,
                )
            except FileNotFoundError as error:
                raise OSError(
                    f"Managed-output directory rollback material is missing: {root.path!r}"
                ) from error
            if staged_identity != root.identity:
                raise OSError(
                    f"Managed-output directory stage changed: {root.path!r}"
                )
            continue
        if public_identity != root.identity:
            raise OSError(
                "Unknown directory replacement was preserved during rollback: "
                + repr(root.path)
            )
        _verify_staged_directory_tree_empty(workspace, root, directories)
        _move_exact_noreplace(
            workspace,
            source_root=workspace._destination,
            source_path=root.path,
            destination_root=stage,
            destination_path=root.stage_path,
            expected_identity=root.identity,
            expect_directory=True,
            phase="before_rollback_directory",
        )


def _restore_previous_pointer(
    workspace: ManagedOutputWorkspace,
    stage: VerifiedDirectory,
    previous: _PointerSnapshot | None,
) -> None:
    current = _read_pointer(workspace)
    if previous is None:
        if current is not None:
            raise OSError(
                "Unexpected managed-output commit decision was preserved "
                "during rollback"
            )
        return
    if _pointer_matches_snapshot(current, previous):
        return
    if current is not None:
        raise OSError(
            "Unknown managed-output commit decision was preserved during rollback"
        )
    try:
        displaced, _content = _capture_file(
            workspace,
            stage,
            _POINTER_DISPLACED_PATH,
            expected_identity=previous.identity,
            expected_content=_ContentReceipt.from_bytes(
                previous.content,
                previous.mode,
            ),
        )
    except FileNotFoundError:
        recreated = _create_bytes_file(
            workspace,
            workspace._staging_parent,
            MANAGED_OUTPUT_POINTER_NAME,
            previous.content,
            mode=previous.mode,
        )
        restored = _read_pointer(workspace)
        if (
            restored is None
            or restored.identity != recreated.identity
            or restored.content != previous.content
        ):
            raise OSError(
                "Managed-output previous commit decision could not be recreated"
            )
        return
    _move_exact_noreplace(
        workspace,
        source_root=stage,
        source_path=_POINTER_DISPLACED_PATH,
        destination_root=workspace._staging_parent,
        destination_path=MANAGED_OUTPUT_POINTER_NAME,
        expected_identity=displaced.identity,
        expect_directory=False,
        phase="before_pointer_rollback",
    )


def _rollback_publication(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    previous_record: _GenerationRecord,
) -> Exception | None:
    stage = workspace._require_stage()
    errors: list[BaseException] = []
    _before_managed_output_phase("before_rollback", workspace.destination_path)
    for transition in reversed(journal.transitions):
        try:
            _rollback_transition(workspace, stage, transition)
        except BaseException as error:
            errors.append(error)
    try:
        _rollback_directories(workspace, stage, journal.directories)
    except BaseException as error:
        errors.append(error)
    try:
        _restore_previous_pointer(
            workspace,
            stage,
            journal.previous_pointer,
        )
    except BaseException as error:
        errors.append(error)
    try:
        _verify_generation_record(workspace, previous_record)
    except BaseException as error:
        errors.append(error)
    _before_managed_output_phase("after_rollback", workspace.destination_path)
    if not errors:
        return None
    combined = OSError(
        "Managed-output rollback did not complete: "
        + "; ".join(str(error) for error in errors)
    )
    combined.__cause__ = errors[0]
    for additional in errors[1:]:
        combined.add_note(f"Additional rollback failure: {additional}")
    return combined


def _file_exists_with_identity(
    workspace: ManagedOutputWorkspace,
    root: VerifiedDirectory,
    path: str,
    identity: PathIdentity,
) -> bool:
    try:
        receipt, _content = _capture_file(
            workspace,
            root,
            path,
            expected_identity=identity,
        )
    except FileNotFoundError:
        return False
    return receipt.identity == identity


def _recovery_payload(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    error: BaseException,
    *,
    selected_generation: Literal["previous", "desired", "unknown"],
) -> dict[str, object]:
    affected = [transition.path for transition in journal.transitions]
    displayed = affected[:_RECOVERY_PATH_LIMIT]
    return {
        "format_version": _FORMAT_VERSION,
        "kind": "gm2godot-managed-output-recovery",
        "state": "recovery_required",
        "transaction_id": journal.transaction_id,
        "destination_identity": _identity_payload(
            journal.destination_identity
        ),
        "selected_generation": selected_generation,
        "journal": (
            f"{WORKSPACE_PARENT_NAME}/{MANAGED_OUTPUT_JOURNAL_NAME}"
        ),
        "workspace_stage": (
            f"{WORKSPACE_PARENT_NAME}/transaction-"
            f"{journal.transaction_id}.stage"
        ),
        "affected_path_count": len(affected),
        "affected_paths": displayed,
        "affected_paths_truncated": len(displayed) != len(affected),
        "error": str(error)[:_RECOVERY_MESSAGE_LIMIT],
        "next_step": (
            "Retry recover_managed_output_generation(destination_path) before "
            "starting another conversion; preserve the journal, workspace, "
            "generation records, and listed public paths unchanged."
        ),
    }


def _recovery_content(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    error: BaseException,
    *,
    selected_generation: Literal["previous", "desired", "unknown"],
) -> bytes:
    content = _canonical_json_bytes(
        _recovery_payload(
            workspace,
            journal,
            error,
            selected_generation=selected_generation,
        )
    )
    if len(content) > _RECOVERY_MAX_BYTES:
        raise OSError(
            f"Managed-output recovery artifact exceeds {_RECOVERY_MAX_BYTES} bytes"
        )
    return content


def _read_recovery_artifact(
    workspace: ManagedOutputWorkspace,
) -> tuple[_FileReceipt, dict[str, object]] | None:
    try:
        receipt, content = _capture_file(
            workspace,
            workspace._staging_parent,
            MANAGED_OUTPUT_RECOVERY_NAME,
            maximum=_RECOVERY_MAX_BYTES,
            include_content=True,
        )
    except FileNotFoundError:
        return None
    if content is None:
        raise AssertionError("Recovery-artifact capture requested bytes")
    payload = _decode_canonical_json(
        content,
        description="managed-output recovery artifact",
        maximum=_RECOVERY_MAX_BYTES,
    )
    required = {
        "format_version",
        "kind",
        "state",
        "transaction_id",
        "destination_identity",
        "selected_generation",
        "journal",
        "workspace_stage",
        "affected_path_count",
        "affected_paths",
        "affected_paths_truncated",
        "error",
        "next_step",
    }
    _exact_keys(
        payload,
        frozenset(required),
        "managed-output recovery artifact",
    )
    if (
        payload["format_version"] != _FORMAT_VERSION
        or payload["kind"] != "gm2godot-managed-output-recovery"
        or payload["state"] != "recovery_required"
        or payload["selected_generation"]
        not in {"previous", "desired", "unknown"}
    ):
        raise OSError("Unsupported managed-output recovery artifact")
    _transaction_id(
        payload["transaction_id"],
        "managed-output recovery transaction",
    )
    if _identity(
        payload["destination_identity"],
        "managed-output recovery destination identity",
    ) != workspace._destination.identity:
        raise OSError(
            "Managed-output recovery artifact belongs to another destination"
        )
    return receipt, payload


def _publish_recovery_artifact(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    error: BaseException,
    *,
    selected_generation: Literal["previous", "desired", "unknown"],
) -> None:
    existing = _read_recovery_artifact(workspace)
    if existing is not None:
        if existing[1]["transaction_id"] != journal.transaction_id:
            raise OSError(
                "A recovery artifact for another managed-output transaction "
                "was preserved"
            )
        return
    content = _recovery_content(
        workspace,
        journal,
        error,
        selected_generation=selected_generation,
    )
    temporary_name = (
        f".gm2godot-managed-output-recovery.{journal.transaction_id}.tmp"
    )
    staged = _create_bytes_file(
        workspace,
        workspace._staging_parent,
        temporary_name,
        content,
        mode=0o600,
    )
    try:
        _move_exact_noreplace(
            workspace,
            source_root=workspace._staging_parent,
            source_path=temporary_name,
            destination_root=workspace._staging_parent,
            destination_path=MANAGED_OUTPUT_RECOVERY_NAME,
            expected_identity=staged.identity,
            expect_directory=False,
            phase="recovery_artifact_publish",
        )
    except BaseException:
        if _file_exists_with_identity(
            workspace,
            workspace._staging_parent,
            temporary_name,
            staged.identity,
        ):
            try:
                _remove_file_exact(
                    workspace,
                    workspace._staging_parent,
                    temporary_name,
                    staged.identity,
                )
            except OSError:
                pass
        raise
    published = _read_recovery_artifact(workspace)
    if (
        published is None
        or published[0].identity != staged.identity
        or published[1]["transaction_id"] != journal.transaction_id
    ):
        raise OSError("Managed-output recovery artifact did not publish")


def _remove_matching_recovery_artifact(
    workspace: ManagedOutputWorkspace,
    transaction_id: str,
) -> None:
    existing = _read_recovery_artifact(workspace)
    if existing is None:
        return
    receipt, payload = existing
    if payload["transaction_id"] != transaction_id:
        raise OSError(
            "A recovery artifact for another managed-output transaction was "
            "preserved"
        )
    _remove_file_exact(
        workspace,
        workspace._staging_parent,
        MANAGED_OUTPUT_RECOVERY_NAME,
        receipt.identity,
    )


def _remove_record_if_present(
    workspace: ManagedOutputWorkspace,
    reference: _RecordReference,
) -> None:
    try:
        receipt, _content = _capture_file(
            workspace,
            workspace._staging_parent,
            reference.name,
            expected_identity=reference.identity,
            expected_content=_ContentReceipt(
                mode=reference.mode,
                byte_count=reference.byte_count,
                sha256=reference.sha256,
            ),
        )
    except FileNotFoundError:
        return
    _remove_file_exact(
        workspace,
        workspace._staging_parent,
        reference.name,
        receipt.identity,
    )


def _remove_journal_if_present(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    journal_content: bytes,
) -> None:
    record = _read_journal(workspace)
    if record is None:
        return
    receipt, content, parsed = record
    if content != journal_content or parsed != journal:
        raise OSError(
            "Managed-output journal changed before identity-bound cleanup"
        )
    _remove_file_exact(
        workspace,
        workspace._staging_parent,
        MANAGED_OUTPUT_JOURNAL_NAME,
        receipt.identity,
    )


def _cleanup_transaction(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    journal_content: bytes,
    *,
    selected: Literal["previous", "desired"],
) -> None:
    _before_managed_output_phase(
        "before_private_cleanup",
        workspace.stage_path if workspace._stage is not None else None,
    )
    if workspace._stage is not None and not workspace._cleaned:
        workspace.resume_recovery_cleanup()
        workspace.cleanup()
    if selected == "desired":
        if journal.previous_record.name != journal.desired_record.name:
            _remove_record_if_present(workspace, journal.previous_record)
    else:
        _remove_record_if_present(workspace, journal.desired_record)
        if journal.previous_pointer is None:
            _remove_record_if_present(workspace, journal.previous_record)
    _remove_matching_recovery_artifact(
        workspace,
        journal.transaction_id,
    )
    _remove_journal_if_present(
        workspace,
        journal,
        journal_content,
    )
    _before_managed_output_phase(
        "transaction_cleanup_complete",
        workspace.destination_path,
    )


def _cleanup_unjournaled_records(
    workspace: ManagedOutputWorkspace,
    prepared: _PreparedPublication,
) -> None:
    _remove_record_if_present(workspace, prepared.journal.desired_record)
    if prepared.journal.previous_pointer is None:
        _remove_record_if_present(workspace, prepared.journal.previous_record)


def _preserve_workspace_if_available(
    workspace: ManagedOutputWorkspace,
    error: BaseException,
) -> None:
    if workspace._stage is None or workspace._cleaned:
        return
    try:
        workspace.preserve_for_recovery()
    except BaseException as preservation_error:
        error.add_note(
            "Marking the managed-output workspace for recovery also failed: "
            f"{preservation_error}"
        )


def _publication_receipt(
    prepared: _PreparedPublication,
) -> ManagedOutputPublicationReceipt:
    manifest_receipt = _evidence_receipt(prepared.desired_record.manifest)
    attempt_receipt = _evidence_receipt(prepared.desired_record.attempt)
    return ManagedOutputPublicationReceipt(
        transaction_id=prepared.journal.transaction_id,
        inventory_sha256=_sha256_bytes(
            prepared.desired_record.inventory.to_bytes()
        ),
        manifest_sha256=(
            None if manifest_receipt is None else manifest_receipt.sha256
        ),
        attempt_sha256=(
            None if attempt_receipt is None else attempt_receipt.sha256
        ),
    )


def _publish(
    workspace: ManagedOutputWorkspace,
    *,
    previous_inventory: GenerationInventory,
    desired_inventory: GenerationInventory,
    attempt_content: bytes | None,
    manifest_content: bytes | None,
    require_updated: bool,
) -> ManagedOutputPublicationReceipt:
    prepared: _PreparedPublication | None = None
    journal_published = False
    try:
        prepared = _prepare_publication(
            workspace,
            previous_inventory=previous_inventory,
            desired_inventory=desired_inventory,
            attempt_content=attempt_content,
            manifest_content=manifest_content,
            require_updated=require_updated,
        )
        _publish_journal(workspace, prepared)
        journal_published = True
        pointer_stage = _prepare_pointer_stage(workspace, prepared)
        _verify_private_recovery_material(
            workspace,
            prepared,
            pointer_stage,
        )
        _install_directory_roots(
            workspace,
            prepared.journal.directories,
        )
        _install_transitions(workspace, prepared)
        _verify_desired_publication(workspace, prepared)
        committed_pointer = _publish_commit_decision(
            workspace,
            prepared,
            pointer_stage,
        )
        selected = _verify_pointer_generation(
            workspace,
            committed_pointer,
        )
        if (
            selected.inventory != desired_inventory
            or selected.transaction_id != workspace.transaction_id
        ):
            raise OSError(
                "Managed-output commit decision selected an unexpected generation"
            )
        _cleanup_transaction(
            workspace,
            prepared.journal,
            prepared.journal_content,
            selected="desired",
        )
        return _publication_receipt(prepared)
    except BaseException as error:
        if prepared is None:
            raise
        current_pointer: _PointerSnapshot | None
        try:
            current_pointer = _read_pointer(workspace)
        except BaseException as pointer_error:
            current_pointer = None
            error.add_note(
                "Determining the managed-output commit decision also failed: "
                f"{pointer_error}"
            )
        committed = _pointer_matches_desired(
            current_pointer,
            prepared.desired_pointer,
            prepared.desired_pointer_content,
            prepared.journal.pointer_stage_identity,
        )
        if committed:
            try:
                _publish_recovery_artifact(
                    workspace,
                    prepared.journal,
                    error,
                    selected_generation="desired",
                )
            except BaseException as artifact_error:
                error.add_note(
                    "Publishing the managed-output recovery artifact also "
                    f"failed: {artifact_error}"
                )
            _preserve_workspace_if_available(workspace, error)
            error.add_note(
                "The durable managed-output commit decision selects the new "
                "generation; recovery must verify and finish cleanup."
            )
            raise
        if not journal_published:
            try:
                _cleanup_unjournaled_records(workspace, prepared)
            except BaseException as cleanup_error:
                error.add_note(
                    "Cleaning unjournaled managed-output records also failed: "
                    f"{cleanup_error}"
                )
            raise
        try:
            previous_record = _read_generation_record(
                workspace,
                prepared.journal.previous_record,
            )
            rollback_error = _rollback_publication(
                workspace,
                prepared.journal,
                previous_record,
            )
        except BaseException as rollback_exception:
            rollback_error = (
                rollback_exception
                if isinstance(rollback_exception, Exception)
                else OSError(str(rollback_exception))
            )
        if rollback_error is not None:
            error.add_note(
                "Managed-output rollback also failed: "
                f"{rollback_error}"
            )
            try:
                _publish_recovery_artifact(
                    workspace,
                    prepared.journal,
                    rollback_error,
                    selected_generation="previous",
                )
            except BaseException as artifact_error:
                error.add_note(
                    "Publishing the managed-output recovery artifact also "
                    f"failed: {artifact_error}"
                )
            _preserve_workspace_if_available(workspace, error)
            raise
        try:
            _cleanup_transaction(
                workspace,
                prepared.journal,
                prepared.journal_content,
                selected="previous",
            )
        except BaseException as cleanup_error:
            error.add_note(
                "Managed-output rollback cleanup also failed: "
                f"{cleanup_error}"
            )
            try:
                _publish_recovery_artifact(
                    workspace,
                    prepared.journal,
                    cleanup_error,
                    selected_generation="previous",
                )
            except BaseException as artifact_error:
                error.add_note(
                    "Publishing the managed-output recovery artifact also "
                    f"failed: {artifact_error}"
                )
            _preserve_workspace_if_available(workspace, error)
        raise


def publish_managed_output_generation(
    workspace: ManagedOutputWorkspace,
    *,
    previous_inventory: GenerationInventory,
    desired_inventory: GenerationInventory,
    canonical_manifest_content: bytes,
    attempt_content: bytes,
) -> ManagedOutputPublicationReceipt:
    """Publish managed files and matching evidence under one durable decision."""

    return _publish(
        workspace,
        previous_inventory=previous_inventory,
        desired_inventory=desired_inventory,
        attempt_content=attempt_content,
        manifest_content=canonical_manifest_content,
        require_updated=True,
    )


def publish_managed_output_attempt(
    workspace: ManagedOutputWorkspace,
    *,
    verified_inventory: GenerationInventory,
    attempt_content: bytes,
) -> ManagedOutputPublicationReceipt:
    """Publish attempt-only evidence after verifying the prior generation."""

    workspace.verify()
    validate_generation_inventory(
        workspace.destination_path,
        verified_inventory,
    )
    _attempt, manifest = _capture_public_evidence(workspace)
    stage_inventory_carry_forward(
        workspace,
        verified_inventory,
        enabled_converters=(),
    )
    return _publish(
        workspace,
        previous_inventory=verified_inventory,
        desired_inventory=verified_inventory,
        attempt_content=attempt_content,
        manifest_content=manifest.content,
        require_updated=False,
    )


def _peek_pending_journal(
    destination_path: str | os.PathLike[str],
) -> tuple[bytes, _Journal] | None:
    path_value: str = os.fspath(destination_path)
    path = os.path.abspath(path_value)
    try:
        destination_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    if workspace_module._path_is_redirected(
        path,
        destination_stat,
    ) or not stat.S_ISDIR(destination_stat.st_mode):
        raise OSError(
            f"Refusing redirected or non-directory managed-output destination: {path}"
        )
    with VerifiedDirectory.open(
        path,
        description="managed-output recovery destination",
    ) as destination:
        try:
            parent_stat = destination.stat(WORKSPACE_PARENT_NAME)
        except FileNotFoundError:
            return None
        parent_path = destination.child_path(WORKSPACE_PARENT_NAME)
        if workspace_module._path_is_redirected(
            parent_path,
            parent_stat,
        ) or not stat.S_ISDIR(parent_stat.st_mode):
            raise OSError(
                "Refusing redirected or non-directory managed-output recovery "
                f"parent: {parent_path}"
            )
        parent = destination.open_child(
            WORKSPACE_PARENT_NAME,
            expected_identity=(parent_stat.st_dev, parent_stat.st_ino),
            description="managed-output recovery parent",
        )
        try:
            destination_device = workspace_module._binding_stat(
                destination
            ).st_dev
            destination_mount_id = (
                workspace_module._linux_mount_id(destination.descriptor)
                if destination.strategy == "posix_dir_fd"
                else None
            )
            workspace_module._verify_binding_boundary(
                parent,
                expected_device=destination_device,
                expected_mount_id=destination_mount_id,
            )
            try:
                _identity_value, _mode_value, content = (
                    workspace_module._read_regular_bytes(
                        parent,
                        MANAGED_OUTPUT_JOURNAL_NAME,
                        expected_device=destination_device,
                        expected_mount_id=destination_mount_id,
                        max_bytes=_JOURNAL_MAX_BYTES,
                    )
                )
            except FileNotFoundError:
                return None
            journal = _journal_from_content(content)
            if (
                journal.destination_identity != destination.identity
                or journal.workspace_parent_identity != parent.identity
            ):
                raise OSError(
                    "Managed-output journal belongs to another destination"
                )
            return content, journal
        finally:
            parent.close()


def _journal_stage_name(transaction_id: str) -> str:
    return f"transaction-{transaction_id}.stage"


def _journal_stage_is_absent(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
) -> bool:
    name = _journal_stage_name(journal.transaction_id)
    try:
        current = workspace._staging_parent.stat(name)
    except FileNotFoundError:
        return True
    path = workspace._staging_parent.child_path(name)
    if (
        workspace_module._path_is_redirected(path, current)
        or not stat.S_ISDIR(current.st_mode)
        or (current.st_dev, current.st_ino) != journal.stage_identity
    ):
        raise OSError(
            "Managed-output recovery stage changed and was preserved: " + path
        )
    return False


def _recover_committed(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    journal_content: bytes,
    *,
    reopened_original_stage: bool,
    reopen_error: BaseException | None,
) -> str:
    try:
        if (
            not reopened_original_stage
            and not _journal_stage_is_absent(workspace, journal)
        ):
            raise OSError(
                "Managed-output committed recovery stage could not be "
                "reopened safely"
            )
        desired_record = _read_generation_record(
            workspace,
            journal.desired_record,
        )
        _verify_generation_record(workspace, desired_record)
        _cleanup_transaction(
            workspace,
            journal,
            journal_content,
            selected="desired",
        )
        return "finalized the committed managed-output generation"
    except BaseException as error:
        if reopen_error is not None:
            error.add_note(
                "Reopening the original managed-output stage also failed: "
                f"{reopen_error}"
            )
        try:
            _publish_recovery_artifact(
                workspace,
                journal,
                error,
                selected_generation="desired",
            )
        except BaseException as artifact_error:
            error.add_note(
                "Publishing the managed-output recovery artifact also failed: "
                f"{artifact_error}"
            )
        _preserve_workspace_if_available(workspace, error)
        raise


def _recover_precommit(
    workspace: ManagedOutputWorkspace,
    journal: _Journal,
    journal_content: bytes,
    *,
    reopened_original_stage: bool,
    reopen_error: BaseException | None,
) -> str:
    current_pointer = _read_pointer(workspace)
    pointer_is_previous = _pointer_matches_snapshot(
        current_pointer,
        journal.previous_pointer,
    )
    pointer_is_displaced_previous = (
        current_pointer is None and journal.previous_pointer is not None
    )
    if not pointer_is_previous and not pointer_is_displaced_previous:
        error = OSError(
            "Managed-output journal and durable commit decision disagree"
        )
        try:
            _publish_recovery_artifact(
                workspace,
                journal,
                error,
                selected_generation="unknown",
            )
        except BaseException as artifact_error:
            error.add_note(
                "Publishing the managed-output recovery artifact also failed: "
                f"{artifact_error}"
            )
        _preserve_workspace_if_available(workspace, error)
        raise error
    if (
        not reopened_original_stage
        or workspace.transaction_id != journal.transaction_id
        or workspace._stage_identity != journal.stage_identity
    ):
        error = OSError(
            "The pre-commit managed-output recovery stage is unavailable; "
            "exact rollback material was preserved"
        )
        if reopen_error is not None:
            error.add_note(
                f"Reopening the original recovery stage failed: {reopen_error}"
            )
        try:
            _publish_recovery_artifact(
                workspace,
                journal,
                error,
                selected_generation="previous",
            )
        except BaseException as artifact_error:
            error.add_note(
                "Publishing the managed-output recovery artifact also failed: "
                f"{artifact_error}"
            )
        _preserve_workspace_if_available(workspace, error)
        raise error
    previous_record = _read_generation_record(
        workspace,
        journal.previous_record,
    )
    rollback_error = _rollback_publication(
        workspace,
        journal,
        previous_record,
    )
    if rollback_error is not None:
        try:
            _publish_recovery_artifact(
                workspace,
                journal,
                rollback_error,
                selected_generation="previous",
            )
        except BaseException as artifact_error:
            rollback_error.add_note(
                "Publishing the managed-output recovery artifact also failed: "
                f"{artifact_error}"
            )
        _preserve_workspace_if_available(workspace, rollback_error)
        raise rollback_error
    try:
        _cleanup_transaction(
            workspace,
            journal,
            journal_content,
            selected="previous",
        )
    except BaseException as cleanup_error:
        try:
            _publish_recovery_artifact(
                workspace,
                journal,
                cleanup_error,
                selected_generation="previous",
            )
        except BaseException as artifact_error:
            cleanup_error.add_note(
                "Publishing the managed-output recovery artifact also failed: "
                f"{artifact_error}"
            )
        _preserve_workspace_if_available(workspace, cleanup_error)
        raise
    return "rolled back the interrupted managed-output generation"


def _recover_locked(
    workspace: ManagedOutputWorkspace,
    expected_content: bytes,
    expected_journal: _Journal,
    *,
    reopened_original_stage: bool,
    reopen_error: BaseException | None,
) -> str:
    journal_record = _read_journal(workspace)
    if (
        journal_record is None
        or journal_record[1] != expected_content
        or journal_record[2] != expected_journal
    ):
        raise OSError(
            "Managed-output journal changed while acquiring the destination lock"
        )
    _journal_receipt, journal_content, journal = journal_record
    desired_pointer = _Pointer(
        transaction_id=journal.transaction_id,
        destination_identity=journal.destination_identity,
        journal_sha256=_sha256_bytes(journal_content),
        generation_record=journal.desired_record,
    )
    desired_pointer_content = _pointer_content(desired_pointer)
    current_pointer = _read_pointer(workspace)
    if _pointer_matches_desired(
        current_pointer,
        desired_pointer,
        desired_pointer_content,
        journal.pointer_stage_identity,
    ):
        return _recover_committed(
            workspace,
            journal,
            journal_content,
            reopened_original_stage=reopened_original_stage,
            reopen_error=reopen_error,
        )
    return _recover_precommit(
        workspace,
        journal,
        journal_content,
        reopened_original_stage=reopened_original_stage,
        reopen_error=reopen_error,
    )


def _verify_without_pending_journal(
    workspace: ManagedOutputWorkspace,
) -> None:
    pointer = _read_pointer(workspace)
    _verify_no_unexpected_parent_state(workspace, pointer)
    if pointer is not None:
        _verify_pointer_generation(workspace, pointer)
    recovery = _read_recovery_artifact(workspace)
    if recovery is not None:
        raise OSError(
            "A managed-output recovery artifact remains without its journal; "
            "exact state was preserved for inspection"
        )


def recover_managed_output_generation(
    destination_path: str | os.PathLike[str],
) -> str | None:
    """Recover a pending publication or verify the selected generation.

    Recovery acquires the same destination-wide lock as staging. Before the
    durable pointer it restores the complete prior generation; after the
    pointer it verifies the complete desired generation and finishes only
    identity-bound cleanup.
    """

    pending = _peek_pending_journal(destination_path)
    if pending is None:
        with ManagedOutputWorkspace.open(destination_path) as workspace:
            _verify_without_pending_journal(workspace)
        return None
    expected_content, journal = pending
    workspace: ManagedOutputWorkspace | None = None
    reopen_error: BaseException | None = None
    reopened_original_stage = False
    try:
        try:
            workspace = ManagedOutputWorkspace.open(
                destination_path,
                transaction_id=journal.transaction_id,
                reuse_existing=True,
            )
            reopened_original_stage = True
        except BaseException as error:
            reopen_error = error
            workspace = ManagedOutputWorkspace.open(destination_path)
        return _recover_locked(
            workspace,
            expected_content,
            journal,
            reopened_original_stage=reopened_original_stage,
            reopen_error=reopen_error,
        )
    finally:
        if workspace is not None:
            workspace.close()


__all__ = [
    "MANAGED_OUTPUT_JOURNAL_NAME",
    "MANAGED_OUTPUT_POINTER_NAME",
    "MANAGED_OUTPUT_RECOVERY_NAME",
    "ManagedOutputPublicationReceipt",
    "publish_managed_output_attempt",
    "publish_managed_output_generation",
    "recover_managed_output_generation",
]
