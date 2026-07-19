"""Crash-recoverable publication for the conversion attempt/manifest pair."""

from __future__ import annotations

import base64
import binascii
import errno
import json
import os
import re
import stat
import sys
import zlib
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, cast

from src.conversion.anchored_artifacts import (
    ArtifactSnapshot,
    ByteArtifactTransaction,
    StagedArtifact,
    artifact_sha256,
    modes_match,
)


_GENERATION_FORMAT_VERSION = 1
_GENERATION_LOCK_NAME = ".gm2godot-conversion.lock"
_GENERATION_JOURNAL_NAME = ".gm2godot-conversion-transaction.json"
_GENERATION_POINTER_NAME = ".gm2godot-conversion-generation.json"
_GENERATION_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024
_GENERATION_RECORD_MAX_BYTES = 32 * 1024 * 1024
_GENERATION_LOCK_CONTENT = b"\x00"
_TRANSACTION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

CONVERSION_GENERATION_LOCK_NAME = _GENERATION_LOCK_NAME
CONVERSION_GENERATION_JOURNAL_NAME = _GENERATION_JOURNAL_NAME
CONVERSION_GENERATION_POINTER_NAME = _GENERATION_POINTER_NAME


@dataclass(frozen=True)
class _GenerationValue:
    name: str
    content: bytes | None
    mode: int | None

    @property
    def present(self) -> bool:
        return self.content is not None

    @property
    def sha256(self) -> str | None:
        return None if self.content is None else artifact_sha256(self.content)


@dataclass(frozen=True)
class _GenerationReceipt:
    name: str
    present: bool
    mode: int | None
    byte_count: int
    sha256: str | None


@dataclass(frozen=True)
class _PointerReceipt:
    transaction_id: str
    mode: int
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class _GenerationJournal:
    transaction_id: str
    directory_identity: tuple[int, int]
    previous_pointer: _PointerReceipt | None
    previous: tuple[_GenerationValue, _GenerationValue]
    desired: tuple[_GenerationValue, _GenerationValue]


@dataclass(frozen=True)
class _GenerationPointer:
    transaction_id: str
    journal_sha256: str
    artifacts: tuple[_GenerationReceipt, _GenerationReceipt]


@dataclass
class _ConversionGenerationLock(AbstractContextManager["_ConversionGenerationLock"]):
    descriptor: int
    windows: bool
    released: bool = False

    @classmethod
    def acquire(
        cls,
        transaction: ByteArtifactTransaction,
    ) -> "_ConversionGenerationLock":
        _verify_generation_directory_mount(transaction)
        descriptor = transaction.directory.open_file(
            _GENERATION_LOCK_NAME,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
            0o600,
        )
        windows = os.name == "nt"
        locked = False
        try:
            initial_stat = os.fstat(descriptor)
            path_stat = transaction.directory.stat(_GENERATION_LOCK_NAME)
            identity = (initial_stat.st_dev, initial_stat.st_ino)
            if (
                not stat.S_ISREG(initial_stat.st_mode)
                or initial_stat.st_nlink != 1
                or path_stat.st_nlink != 1
                or (path_stat.st_dev, path_stat.st_ino) != identity
            ):
                raise OSError(
                    "Refusing non-regular or multiply-linked conversion generation lock"
                )
            _verify_generation_file_mount(
                transaction,
                descriptor,
                _GENERATION_LOCK_NAME,
            )
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                if windows:
                    import msvcrt

                    windows_lock = cast(
                        Callable[[int, int, int], None],
                        getattr(msvcrt, "locking"),
                    )
                    lock_mode = cast(int, getattr(msvcrt, "LK_NBLCK"))
                    windows_lock(descriptor, lock_mode, 1)
                else:
                    import fcntl

                    fcntl.flock(
                        descriptor,
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise OSError(
                        "Another conversion artifact generation is already publishing or recovering"
                    ) from error
                raise
            locked = True
            os.lseek(descriptor, 0, os.SEEK_SET)
            content = os.read(descriptor, len(_GENERATION_LOCK_CONTENT) + 1)
            initialized = False
            if content == b"":
                os.lseek(descriptor, 0, os.SEEK_SET)
                written = os.write(descriptor, _GENERATION_LOCK_CONTENT)
                if written != len(_GENERATION_LOCK_CONTENT):
                    raise OSError("Could not initialize conversion generation lock")
                os.ftruncate(descriptor, len(_GENERATION_LOCK_CONTENT))
                os.fsync(descriptor)
                initialized = True
                transaction.phase(
                    "generation_lock_initialized",
                    _GENERATION_LOCK_NAME,
                )
            elif content != _GENERATION_LOCK_CONTENT:
                raise OSError("Invalid conversion generation lock content")
            current_stat = os.fstat(descriptor)
            current_path_stat = transaction.directory.stat(_GENERATION_LOCK_NAME)
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or current_stat.st_nlink != 1
                or current_path_stat.st_nlink != 1
                or (current_stat.st_dev, current_stat.st_ino) != identity
                or (current_path_stat.st_dev, current_path_stat.st_ino) != identity
                or current_stat.st_size != len(_GENERATION_LOCK_CONTENT)
            ):
                raise OSError("Conversion generation lock changed")
            if initialized:
                transaction.sync("generation_lock_initialization_durability")
                transaction.phase(
                    "generation_lock_durable",
                    _GENERATION_LOCK_NAME,
                )
            transaction.verify_directory()
            return cls(descriptor=descriptor, windows=windows)
        except BaseException:
            if locked:
                try:
                    _unlock_generation_descriptor(descriptor, windows)
                except OSError:
                    pass
            os.close(descriptor)
            raise

    def __exit__(
        self,
        _exc_type: object,
        active_error: BaseException | None,
        _traceback: object,
    ) -> bool | None:
        try:
            self.release()
        except BaseException as error:
            if active_error is None:
                raise
            active_error.add_note(
                f"Could not release conversion generation lock: {error}"
            )
        return None

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        descriptor = self.descriptor
        self.descriptor = -1
        active_error: BaseException | None = None
        try:
            _unlock_generation_descriptor(descriptor, self.windows)
        except BaseException as error:
            active_error = error
        try:
            os.close(descriptor)
        except BaseException as error:
            if active_error is None:
                raise
            active_error.add_note(
                f"Could not close conversion generation lock: {error}"
            )
        if active_error is not None:
            raise active_error


ConversionArtifactGenerationLock = _ConversionGenerationLock


def _unlock_generation_descriptor(descriptor: int, windows: bool) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if windows:
        import msvcrt

        windows_lock = cast(
            Callable[[int, int, int], None],
            getattr(msvcrt, "locking"),
        )
        unlock_mode = cast(int, getattr(msvcrt, "LK_UNLCK"))
        windows_lock(descriptor, unlock_mode, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _linux_mount_id(file_descriptor: int) -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(
            f"/proc/self/fdinfo/{file_descriptor}",
            "r",
            encoding="utf-8",
        ) as fdinfo:
            for line in fdinfo:
                if not line.startswith("mnt_id:"):
                    continue
                value = line.partition(":")[2].strip()
                return int(value) if value.isascii() and value.isdigit() else None
    except OSError:
        return None
    return None


def _verify_generation_file_mount(
    transaction: ByteArtifactTransaction,
    file_descriptor: int,
    name: str,
) -> None:
    path = transaction.directory.child_path(name)
    opened_stat = os.fstat(file_descriptor)
    if opened_stat.st_dev != transaction.directory.identity[0] or os.path.ismount(path):
        raise OSError(f"Refusing mounted conversion generation state: {path}")
    if transaction.strategy != "posix_dir_fd":
        return
    directory_mount_id = _linux_mount_id(transaction.directory.descriptor)
    file_mount_id = _linux_mount_id(file_descriptor)
    if (
        directory_mount_id is not None
        and file_mount_id is not None
        and directory_mount_id != file_mount_id
    ):
        raise OSError(f"Refusing mounted conversion generation state: {path}")


def _verify_generation_directory_mount(
    transaction: ByteArtifactTransaction,
) -> None:
    if transaction.root_identity[0] != transaction.directory.identity[
        0
    ] or os.path.ismount(transaction.path):
        raise OSError(
            f"Refusing mounted conversion generation artifact directory: {transaction.path}"
        )
    if transaction.strategy != "posix_dir_fd":
        return
    root_mount_id = _linux_mount_id(transaction.anchored.root.descriptor)
    directory_mount_id = _linux_mount_id(transaction.directory.descriptor)
    if (
        root_mount_id is not None
        and directory_mount_id is not None
        and root_mount_id != directory_mount_id
    ):
        raise OSError(
            f"Refusing mounted conversion generation artifact directory: {transaction.path}"
        )


def _exact_keys(
    value: dict[str, Any],
    expected: frozenset[str],
    description: str,
) -> None:
    if value.keys() != expected:
        raise OSError(f"Invalid conversion generation {description} fields")


def _mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OSError(f"Invalid conversion generation {description}")
    raw_mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw_mapping):
        raise OSError(f"Invalid conversion generation {description}")
    return cast(dict[str, Any], raw_mapping)


def _integer(
    value: Any,
    description: str,
    *,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < 0:
        raise OSError(f"Invalid conversion generation {description}")
    if maximum is not None and value > maximum:
        raise OSError(f"Invalid conversion generation {description}")
    return value


def _transaction_id(value: Any, description: str) -> str:
    if not isinstance(value, str) or _TRANSACTION_ID_PATTERN.fullmatch(value) is None:
        raise OSError(f"Invalid conversion generation {description}")
    return value


def _sha256(value: Any, description: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise OSError(f"Invalid conversion generation {description}")
    return value


def _identity(value: Any, description: str) -> tuple[int, int]:
    if not isinstance(value, list):
        raise OSError(f"Invalid conversion generation {description}")
    components = cast(list[Any], value)
    if len(components) != 2:
        raise OSError(f"Invalid conversion generation {description}")
    return (
        _integer(components[0], description),
        _integer(components[1], description),
    )


def _mode(value: Any, description: str) -> int:
    return _integer(value, description, maximum=0o7777)


def _compress_content(content: bytes) -> str:
    return base64.b64encode(zlib.compress(content, level=9)).decode("ascii")


def _decompress_content(
    value: Any,
    byte_count: int,
    description: str,
) -> bytes:
    if not isinstance(value, str):
        raise OSError(f"Invalid conversion generation {description}")
    try:
        compressed = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise OSError(f"Invalid conversion generation {description}") from error
    try:
        decompressor = zlib.decompressobj()
        content = decompressor.decompress(compressed, byte_count + 1)
    except zlib.error as error:
        raise OSError(f"Invalid conversion generation {description}") from error
    if (
        len(content) != byte_count
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        raise OSError(f"Invalid conversion generation {description}")
    return content


def _value_payload(value: _GenerationValue) -> dict[str, Any]:
    if not value.present:
        return {
            "name": value.name,
            "present": False,
            "mode": None,
            "byte_count": 0,
            "sha256": None,
            "content_zlib_base64": None,
        }
    if value.content is None or value.mode is None:
        raise AssertionError("A present generation value must be complete")
    if len(value.content) > _GENERATION_ARTIFACT_MAX_BYTES:
        raise OSError(
            f"Conversion generation artifact exceeds {_GENERATION_ARTIFACT_MAX_BYTES} bytes: {value.name}"
        )
    return {
        "name": value.name,
        "present": True,
        "mode": value.mode,
        "byte_count": len(value.content),
        "sha256": value.sha256,
        "content_zlib_base64": _compress_content(value.content),
    }


def _value_from_payload(
    value: Any,
    expected_name: str,
    description: str,
) -> _GenerationValue:
    payload = _mapping(value, description)
    _exact_keys(
        payload,
        frozenset(
            {
                "name",
                "present",
                "mode",
                "byte_count",
                "sha256",
                "content_zlib_base64",
            }
        ),
        description,
    )
    if payload.get("name") != expected_name:
        raise OSError(f"Invalid conversion generation {description} name")
    present = payload.get("present")
    if type(present) is not bool:
        raise OSError(f"Invalid conversion generation {description} presence")
    byte_count = _integer(
        payload.get("byte_count"),
        f"{description} byte count",
        maximum=_GENERATION_ARTIFACT_MAX_BYTES,
    )
    if not present:
        if (
            payload.get("mode") is not None
            or byte_count != 0
            or payload.get("sha256") is not None
            or payload.get("content_zlib_base64") is not None
        ):
            raise OSError(f"Invalid absent conversion generation {description}")
        return _GenerationValue(expected_name, None, None)
    mode = _mode(payload.get("mode"), f"{description} mode")
    digest = _sha256(payload.get("sha256"), f"{description} digest")
    content = _decompress_content(
        payload.get("content_zlib_base64"),
        byte_count,
        f"{description} content",
    )
    if artifact_sha256(content) != digest:
        raise OSError(f"Conversion generation {description} digest mismatch")
    return _GenerationValue(expected_name, content, mode)


def _receipt(value: _GenerationValue) -> _GenerationReceipt:
    return _GenerationReceipt(
        name=value.name,
        present=value.present,
        mode=value.mode,
        byte_count=0 if value.content is None else len(value.content),
        sha256=value.sha256,
    )


def _receipt_payload(receipt: _GenerationReceipt) -> dict[str, Any]:
    return {
        "name": receipt.name,
        "present": receipt.present,
        "mode": receipt.mode,
        "byte_count": receipt.byte_count,
        "sha256": receipt.sha256,
    }


def _receipt_from_payload(
    value: Any,
    expected_name: str,
) -> _GenerationReceipt:
    payload = _mapping(value, "pointer artifact")
    _exact_keys(
        payload,
        frozenset({"name", "present", "mode", "byte_count", "sha256"}),
        "pointer artifact",
    )
    if payload.get("name") != expected_name:
        raise OSError("Invalid conversion generation pointer artifact name")
    present = payload.get("present")
    if type(present) is not bool:
        raise OSError("Invalid conversion generation pointer artifact presence")
    byte_count = _integer(
        payload.get("byte_count"),
        "pointer artifact byte count",
        maximum=_GENERATION_ARTIFACT_MAX_BYTES,
    )
    if not present:
        if (
            payload.get("mode") is not None
            or byte_count != 0
            or payload.get("sha256") is not None
        ):
            raise OSError("Invalid absent conversion generation pointer artifact")
        return _GenerationReceipt(
            expected_name,
            False,
            None,
            0,
            None,
        )
    return _GenerationReceipt(
        expected_name,
        True,
        _mode(payload.get("mode"), "pointer artifact mode"),
        byte_count,
        _sha256(payload.get("sha256"), "pointer artifact digest"),
    )


def _pointer_receipt_payload(
    receipt: _PointerReceipt | None,
) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {
        "transaction_id": receipt.transaction_id,
        "mode": receipt.mode,
        "byte_count": receipt.byte_count,
        "sha256": receipt.sha256,
    }


def _pointer_receipt_from_payload(value: Any) -> _PointerReceipt | None:
    if value is None:
        return None
    payload = _mapping(value, "previous pointer")
    _exact_keys(
        payload,
        frozenset({"transaction_id", "mode", "byte_count", "sha256"}),
        "previous pointer",
    )
    return _PointerReceipt(
        transaction_id=_transaction_id(
            payload.get("transaction_id"),
            "previous pointer transaction id",
        ),
        mode=_mode(payload.get("mode"), "previous pointer mode"),
        byte_count=_integer(
            payload.get("byte_count"),
            "previous pointer byte count",
            maximum=_GENERATION_RECORD_MAX_BYTES,
        ),
        sha256=_sha256(
            payload.get("sha256"),
            "previous pointer digest",
        ),
    )


def _record_content(payload: dict[str, Any]) -> bytes:
    content = (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if len(content) > _GENERATION_RECORD_MAX_BYTES:
        raise OSError(
            f"Conversion generation recovery record exceeds {_GENERATION_RECORD_MAX_BYTES} bytes"
        )
    return content


def _journal_payload(journal: _GenerationJournal) -> dict[str, Any]:
    return {
        "format_version": _GENERATION_FORMAT_VERSION,
        "state": "prepared",
        "transaction_id": journal.transaction_id,
        "directory_identity": list(journal.directory_identity),
        "previous_pointer": _pointer_receipt_payload(journal.previous_pointer),
        "previous_artifacts": [_value_payload(value) for value in journal.previous],
        "desired_artifacts": [_value_payload(value) for value in journal.desired],
    }


def _journal_content(journal: _GenerationJournal) -> bytes:
    return _record_content(_journal_payload(journal))


def _journal_from_payload(
    payload: dict[str, Any],
    attempt_name: str,
    manifest_name: str,
) -> _GenerationJournal:
    _exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "transaction_id",
                "directory_identity",
                "previous_pointer",
                "previous_artifacts",
                "desired_artifacts",
            }
        ),
        "journal",
    )
    if (
        _integer(
            payload.get("format_version"),
            "journal format version",
        )
        != _GENERATION_FORMAT_VERSION
        or payload.get("state") != "prepared"
    ):
        raise OSError("Unsupported conversion generation journal")
    names = (attempt_name, manifest_name)
    previous_payloads = payload.get("previous_artifacts")
    desired_payloads = payload.get("desired_artifacts")
    if not isinstance(previous_payloads, list) or not isinstance(
        desired_payloads,
        list,
    ):
        raise OSError("Invalid conversion generation journal artifacts")
    typed_previous_payloads = cast(list[Any], previous_payloads)
    typed_desired_payloads = cast(list[Any], desired_payloads)
    if len(typed_previous_payloads) != 2 or len(typed_desired_payloads) != 2:
        raise OSError("Invalid conversion generation journal artifacts")
    previous = cast(
        tuple[_GenerationValue, _GenerationValue],
        tuple(
            _value_from_payload(
                value,
                name,
                "previous artifact",
            )
            for value, name in zip(
                typed_previous_payloads,
                names,
                strict=True,
            )
        ),
    )
    desired = cast(
        tuple[_GenerationValue, _GenerationValue],
        tuple(
            _value_from_payload(
                value,
                name,
                "desired artifact",
            )
            for value, name in zip(
                typed_desired_payloads,
                names,
                strict=True,
            )
        ),
    )
    _validate_conversion_pair(previous)
    _validate_conversion_pair(desired)
    return _GenerationJournal(
        transaction_id=_transaction_id(
            payload.get("transaction_id"),
            "journal transaction id",
        ),
        directory_identity=_identity(
            payload.get("directory_identity"),
            "journal directory identity",
        ),
        previous_pointer=_pointer_receipt_from_payload(payload.get("previous_pointer")),
        previous=previous,
        desired=desired,
    )


def _pointer_payload(pointer: _GenerationPointer) -> dict[str, Any]:
    return {
        "format_version": _GENERATION_FORMAT_VERSION,
        "state": "committed",
        "transaction_id": pointer.transaction_id,
        "journal_sha256": pointer.journal_sha256,
        "artifacts": [_receipt_payload(receipt) for receipt in pointer.artifacts],
    }


def _pointer_content(pointer: _GenerationPointer) -> bytes:
    return _record_content(_pointer_payload(pointer))


def _pointer_from_payload(
    payload: dict[str, Any],
    attempt_name: str,
    manifest_name: str,
) -> _GenerationPointer:
    _exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "transaction_id",
                "journal_sha256",
                "artifacts",
            }
        ),
        "pointer",
    )
    if (
        _integer(
            payload.get("format_version"),
            "pointer format version",
        )
        != _GENERATION_FORMAT_VERSION
        or payload.get("state") != "committed"
    ):
        raise OSError("Unsupported conversion generation pointer")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise OSError("Invalid conversion generation pointer artifacts")
    typed_artifacts = cast(list[Any], artifacts)
    if len(typed_artifacts) != 2:
        raise OSError("Invalid conversion generation pointer artifacts")
    names = (attempt_name, manifest_name)
    receipts = cast(
        tuple[_GenerationReceipt, _GenerationReceipt],
        tuple(
            _receipt_from_payload(value, name)
            for value, name in zip(typed_artifacts, names, strict=True)
        ),
    )
    return _GenerationPointer(
        transaction_id=_transaction_id(
            payload.get("transaction_id"),
            "pointer transaction id",
        ),
        journal_sha256=_sha256(
            payload.get("journal_sha256"),
            "pointer journal digest",
        ),
        artifacts=receipts,
    )


def _record_snapshot(
    transaction: ByteArtifactTransaction,
    name: str,
) -> ArtifactSnapshot:
    state = transaction.target_state(name)
    if state.fingerprint is not None:
        if state.fingerprint[2] > _GENERATION_RECORD_MAX_BYTES:
            raise OSError(
                f"Conversion generation recovery record exceeds "
                f"{_GENERATION_RECORD_MAX_BYTES} bytes: "
                f"{transaction.directory.child_path(name)}"
            )
        path_stat = transaction.directory.stat(name)
        if path_stat.st_nlink != 1:
            raise OSError(
                "Refusing multiply-linked conversion generation recovery "
                f"record: {transaction.directory.child_path(name)}"
            )
        descriptor = transaction.directory.open_file(name, os.O_RDONLY)
        try:
            opened_stat = os.fstat(descriptor)
            if opened_stat.st_nlink != 1 or (
                opened_stat.st_dev,
                opened_stat.st_ino,
            ) != (
                state.fingerprint[0],
                state.fingerprint[1],
            ):
                raise OSError(
                    f"Conversion generation recovery record changed: {transaction.directory.child_path(name)}"
                )
            _verify_generation_file_mount(transaction, descriptor, name)
        finally:
            os.close(descriptor)
    snapshot = transaction.capture_snapshot(name)
    if snapshot.present:
        current_stat = transaction.directory.stat(name)
        if current_stat.st_nlink != 1:
            raise OSError(
                "Refusing multiply-linked conversion generation recovery "
                f"record: {transaction.directory.child_path(name)}"
            )
    return snapshot


def _decoded_record(snapshot: ArtifactSnapshot, description: str) -> dict[str, Any]:
    if snapshot.content is None:
        raise ValueError("Cannot decode an absent recovery record")
    try:
        decoded = snapshot.content.decode("utf-8")
        payload = _mapping(json.loads(decoded), description)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OSError(f"Invalid conversion generation {description}") from error
    if snapshot.content != _record_content(payload):
        raise OSError(f"Non-canonical conversion generation {description}")
    return payload


def _read_journal(
    transaction: ByteArtifactTransaction,
    attempt_name: str,
    manifest_name: str,
    *,
    name: str = _GENERATION_JOURNAL_NAME,
) -> tuple[ArtifactSnapshot, _GenerationJournal] | None:
    snapshot = _record_snapshot(transaction, name)
    if not snapshot.present:
        return None
    journal = _journal_from_payload(
        _decoded_record(snapshot, "journal"),
        attempt_name,
        manifest_name,
    )
    if journal.directory_identity != transaction.directory.identity:
        raise OSError(
            "Conversion generation journal belongs to another artifact directory"
        )
    if snapshot.content != _journal_content(journal):
        raise OSError("Conversion generation journal changed")
    return snapshot, journal


def _read_pointer(
    transaction: ByteArtifactTransaction,
    attempt_name: str,
    manifest_name: str,
    *,
    name: str = _GENERATION_POINTER_NAME,
) -> tuple[ArtifactSnapshot, _GenerationPointer] | None:
    snapshot = _record_snapshot(transaction, name)
    if not snapshot.present:
        return None
    pointer = _pointer_from_payload(
        _decoded_record(snapshot, "pointer"),
        attempt_name,
        manifest_name,
    )
    if snapshot.content != _pointer_content(pointer):
        raise OSError("Conversion generation pointer changed")
    return snapshot, pointer


def _capture_value(
    transaction: ByteArtifactTransaction,
    name: str,
) -> _GenerationValue:
    state = transaction.target_state(name)
    if state.fingerprint is not None:
        if state.fingerprint[2] > _GENERATION_ARTIFACT_MAX_BYTES:
            raise OSError(
                f"Conversion generation artifact exceeds "
                f"{_GENERATION_ARTIFACT_MAX_BYTES} bytes: "
                f"{transaction.directory.child_path(name)}"
            )
        path_stat = transaction.directory.stat(name)
        if path_stat.st_nlink != 1:
            raise OSError(
                f"Refusing multiply-linked conversion generation artifact: {transaction.directory.child_path(name)}"
            )
        descriptor = transaction.directory.open_file(name, os.O_RDONLY)
        try:
            _verify_generation_file_mount(transaction, descriptor, name)
        finally:
            os.close(descriptor)
    snapshot = transaction.capture_snapshot(name)
    return _GenerationValue(
        name=snapshot.name,
        content=snapshot.content,
        mode=snapshot.mode,
    )


def _capture_pair(
    transaction: ByteArtifactTransaction,
    attempt_name: str,
    manifest_name: str,
    *,
    validate: bool = True,
) -> tuple[_GenerationValue, _GenerationValue]:
    pair = (
        _capture_value(transaction, attempt_name),
        _capture_value(transaction, manifest_name),
    )
    if validate:
        _validate_conversion_pair(pair)
    return pair


def _value_matches(
    actual: _GenerationValue,
    expected: _GenerationValue,
) -> bool:
    if actual.name != expected.name or actual.content != expected.content:
        return False
    if actual.mode is None or expected.mode is None:
        return actual.mode is expected.mode
    return modes_match(actual.mode, expected.mode)


def _pair_matches(
    actual: tuple[_GenerationValue, _GenerationValue],
    expected: tuple[_GenerationValue, _GenerationValue],
) -> bool:
    return all(
        _value_matches(actual_value, expected_value)
        for actual_value, expected_value in zip(
            actual,
            expected,
            strict=True,
        )
    )


def _receipt_matches_value(
    receipt: _GenerationReceipt,
    value: _GenerationValue,
) -> bool:
    if receipt.name != value.name or receipt.present != value.present:
        return False
    if not value.present:
        return (
            receipt.mode is None and receipt.byte_count == 0 and receipt.sha256 is None
        )
    if value.content is None or value.mode is None or receipt.mode is None:
        return False
    return (
        modes_match(receipt.mode, value.mode)
        and receipt.byte_count == len(value.content)
        and receipt.sha256 == value.sha256
    )


def _validate_conversion_pair(
    pair: tuple[_GenerationValue, _GenerationValue],
) -> None:
    attempt, manifest = pair
    if attempt.content is None:
        if manifest.content is not None:
            raise OSError(
                "A conversion manifest cannot exist without its attempt ledger"
            )
        return
    try:
        attempt_payload = _mapping(
            json.loads(attempt.content.decode("utf-8")),
            "attempt ledger",
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OSError("Invalid conversion attempt ledger") from error
    canonical = _mapping(
        attempt_payload.get("canonical_manifest"),
        "attempt canonical-manifest record",
    )
    expected_path = "gm2godot/conversion_manifest.json"
    if canonical.get("path") != expected_path:
        raise OSError("Invalid conversion attempt canonical-manifest path")
    status = canonical.get("status")
    updated = canonical.get("updated")
    current_output = canonical.get("current_output")
    digest = canonical.get("sha256")
    if manifest.content is None:
        if (
            status != "absent"
            or updated is not False
            or current_output != "unavailable"
            or digest is not None
        ):
            raise OSError("Conversion attempt disagrees with absent canonical manifest")
        return
    status_is_consistent = (
        status == "updated"
        and updated is True
        and current_output == "verified"
    ) or (
        status == "preserved"
        and updated is False
        and current_output == "unverified"
    )
    if (
        not status_is_consistent
        or digest != artifact_sha256(manifest.content)
    ):
        raise OSError("Conversion attempt/canonical manifest digest mismatch")


def _pointer_receipt_from_snapshot(
    snapshot: ArtifactSnapshot,
    pointer: _GenerationPointer,
) -> _PointerReceipt:
    if snapshot.content is None or snapshot.mode is None:
        raise ValueError("A pointer receipt requires a present pointer")
    return _PointerReceipt(
        transaction_id=pointer.transaction_id,
        mode=snapshot.mode,
        byte_count=len(snapshot.content),
        sha256=artifact_sha256(snapshot.content),
    )


def _pointer_matches_receipt(
    current: tuple[ArtifactSnapshot, _GenerationPointer] | None,
    expected: _PointerReceipt | None,
) -> bool:
    if expected is None:
        return current is None
    if current is None:
        return False
    snapshot, pointer = current
    if snapshot.content is None or snapshot.mode is None:
        return False
    return (
        pointer.transaction_id == expected.transaction_id
        and modes_match(snapshot.mode, expected.mode)
        and len(snapshot.content) == expected.byte_count
        and artifact_sha256(snapshot.content) == expected.sha256
    )


def _verify_pointer_generation(
    transaction: ByteArtifactTransaction,
    pointer: _GenerationPointer,
    attempt_name: str,
    manifest_name: str,
) -> tuple[_GenerationValue, _GenerationValue]:
    pair = _capture_pair(transaction, attempt_name, manifest_name)
    if not all(
        _receipt_matches_value(receipt, value)
        for receipt, value in zip(pointer.artifacts, pair, strict=True)
    ):
        raise OSError("Committed conversion artifact generation is unavailable")
    return pair


def _journal_temporary_name(transaction_id: str) -> str:
    return f".gm2godot-conversion-transaction.{transaction_id}.tmp"


def _pointer_temporary_name(transaction_id: str) -> str:
    return f".gm2godot-conversion-generation.{transaction_id}.tmp"


def _artifact_temporary_name(
    name: str,
    transaction_id: str,
    role: str,
) -> str:
    return f".{name}.{transaction_id}.generation-{role}.tmp"


def _artifact_tombstone_name(
    name: str,
    transaction_id: str,
) -> str:
    return f".{name}.{transaction_id}.generation-delete.tombstone"


def _reserved_generation_name(name: str) -> bool:
    return (
        name.startswith(".gm2godot-conversion-")
        or (name.startswith(".conversion_attempt.json.") and ".generation-" in name)
        or (name.startswith(".conversion_manifest.json.") and ".generation-" in name)
    )


def _expected_temporary_names(
    journal: _GenerationJournal,
) -> frozenset[str]:
    names = {
        _journal_temporary_name(journal.transaction_id),
        _pointer_temporary_name(journal.transaction_id),
    }
    for value in journal.previous:
        names.add(
            _artifact_temporary_name(
                value.name,
                journal.transaction_id,
                "previous",
            )
        )
        names.add(
            _artifact_tombstone_name(
                value.name,
                journal.transaction_id,
            )
        )
    for value in journal.desired:
        names.add(
            _artifact_temporary_name(
                value.name,
                journal.transaction_id,
                "desired",
            )
        )
    return frozenset(names)


def _validate_temporary_stage(
    transaction: ByteArtifactTransaction,
    journal: _GenerationJournal,
    name: str,
    pointer_content: bytes,
) -> StagedArtifact:
    staged = transaction.capture_staged(name)
    if staged is None:
        raise OSError(f"Conversion generation temporary disappeared: {name}")
    expected_content: bytes | None = None
    expected_modes: tuple[int, ...] = ()
    if name == _journal_temporary_name(journal.transaction_id):
        expected_content = _journal_content(journal)
        expected_modes = (0o600,)
    elif name == _pointer_temporary_name(journal.transaction_id):
        expected_content = pointer_content
        expected_modes = (
            0o600,
            *(
                ()
                if journal.previous_pointer is None
                else (journal.previous_pointer.mode,)
            ),
        )
    else:
        matching_values: tuple[_GenerationValue, ...] = ()
        for previous, desired in zip(
            journal.previous,
            journal.desired,
            strict=True,
        ):
            if name == _artifact_temporary_name(
                previous.name,
                journal.transaction_id,
                "previous",
            ):
                matching_values = (previous,)
                break
            if name in {
                _artifact_temporary_name(
                    desired.name,
                    journal.transaction_id,
                    "desired",
                ),
                _artifact_tombstone_name(
                    desired.name,
                    journal.transaction_id,
                ),
            }:
                matching_values = (desired,)
                break
        matching_values = tuple(
            value
            for value in matching_values
            if value.content is not None and value.mode is not None
        )
        if not matching_values:
            raise OSError(f"Unknown conversion generation temporary: {name}")
        if not any(
            staged.content == value.content
            and modes_match(staged.target_mode, cast(int, value.mode))
            for value in matching_values
        ):
            raise OSError(f"Changed conversion generation temporary: {name}")
        return staged
    if staged.content != expected_content or not any(
        modes_match(staged.target_mode, expected_mode)
        for expected_mode in expected_modes
    ):
        raise OSError(f"Changed conversion generation temporary: {name}")
    return staged


def _validate_reserved_names(
    transaction: ByteArtifactTransaction,
    journal: _GenerationJournal | None,
) -> None:
    expected: frozenset[str] = (
        frozenset[str]() if journal is None else _expected_temporary_names(journal)
    )
    allowed_fixed = {
        _GENERATION_LOCK_NAME,
        _GENERATION_JOURNAL_NAME,
        _GENERATION_POINTER_NAME,
    }
    for name in transaction.directory.list_names():
        if name in allowed_fixed:
            continue
        if not _reserved_generation_name(name):
            continue
        if name not in expected:
            raise OSError(
                f"Unknown conversion generation recovery state was preserved: {transaction.directory.child_path(name)}"
            )


def _remove_staged(
    transaction: ByteArtifactTransaction,
    staged: StagedArtifact,
) -> None:
    cleanup_error = transaction.unlink_staged(staged)
    if cleanup_error is not None:
        raise cleanup_error


def _cleanup_generation_temporaries(
    transaction: ByteArtifactTransaction,
    journal: _GenerationJournal,
    pointer_content: bytes,
) -> None:
    _validate_reserved_names(transaction, journal)
    removed = False
    for name in sorted(_expected_temporary_names(journal)):
        if not transaction.directory.lexists(name):
            continue
        staged = _validate_temporary_stage(
            transaction,
            journal,
            name,
            pointer_content,
        )
        _remove_staged(transaction, staged)
        removed = True
        transaction.phase("generation_temporary_removed", name)
    if removed:
        transaction.sync("generation_temporary_cleanup_durability")
    transaction.phase("generation_temporary_cleanup_complete", None)


def _remove_journal(
    transaction: ByteArtifactTransaction,
    expected_content: bytes,
) -> None:
    journal_stage = transaction.capture_staged(_GENERATION_JOURNAL_NAME)
    if journal_stage is None or journal_stage.content != expected_content:
        raise OSError("Conversion generation journal changed before cleanup")
    _remove_staged(transaction, journal_stage)
    transaction.phase("generation_journal_unlinked", _GENERATION_JOURNAL_NAME)
    transaction.sync("generation_journal_cleanup_durability")
    transaction.phase("generation_journal_removed", _GENERATION_JOURNAL_NAME)


def _promote_journal_temporary(
    transaction: ByteArtifactTransaction,
    attempt_name: str,
    manifest_name: str,
) -> bool:
    if transaction.directory.lexists(_GENERATION_JOURNAL_NAME):
        return False
    candidates: list[tuple[str, ArtifactSnapshot, _GenerationJournal]] = []
    for name in transaction.directory.list_names():
        prefix = ".gm2godot-conversion-transaction."
        suffix = ".tmp"
        if not name.startswith(prefix):
            continue
        if not name.endswith(suffix):
            raise OSError(
                "Malformed conversion generation journal temporary was "
                f"preserved: {transaction.directory.child_path(name)}"
            )
        token = name[len(prefix) : -len(suffix)]
        if _TRANSACTION_ID_PATTERN.fullmatch(token) is None:
            raise OSError(
                "Malformed conversion generation journal temporary was "
                f"preserved: {transaction.directory.child_path(name)}"
            )
        record = _read_journal(
            transaction,
            attempt_name,
            manifest_name,
            name=name,
        )
        if record is None:
            continue
        snapshot, journal = record
        if journal.transaction_id != token:
            raise OSError(
                "Conversion generation journal temporary name disagrees with its transaction"
            )
        candidates.append((name, snapshot, journal))
    if len(candidates) > 1:
        raise OSError(
            "Multiple conversion generation journal temporaries require manual inspection"
        )
    if not candidates:
        return False
    name, snapshot, journal = candidates[0]
    current_pair = _capture_pair(
        transaction,
        attempt_name,
        manifest_name,
        validate=False,
    )
    pointer = _read_pointer(
        transaction,
        attempt_name,
        manifest_name,
    )
    if not _pair_matches(
        current_pair, journal.previous
    ) or not _pointer_matches_receipt(
        pointer,
        journal.previous_pointer,
    ):
        raise OSError(
            "Durable conversion journal temporary disagrees with the current prior generation"
        )
    staged = transaction.capture_staged(name)
    if staged is None or staged.content != snapshot.content:
        raise OSError("Conversion generation journal temporary changed")
    completion_error = transaction.replace_staged(
        staged,
        _GENERATION_JOURNAL_NAME,
    )
    transaction.phase(
        "generation_journal_published",
        _GENERATION_JOURNAL_NAME,
    )
    transaction.sync("generation_journal_durability")
    if completion_error is not None:
        raise completion_error
    transaction.phase(
        "generation_journal_promoted",
        _GENERATION_JOURNAL_NAME,
    )
    return True


def _stage_value(
    transaction: ByteArtifactTransaction,
    value: _GenerationValue,
    transaction_id: str,
    role: str,
) -> StagedArtifact:
    if value.content is None or value.mode is None:
        raise ValueError("Cannot stage an absent generation value")
    staged_name = _artifact_temporary_name(
        value.name,
        transaction_id,
        role,
    )
    if transaction.directory.lexists(staged_name):
        existing = transaction.capture_staged(staged_name)
        if (
            existing is None
            or existing.content != value.content
            or not modes_match(existing.target_mode, value.mode)
        ):
            raise OSError(
                f"Changed conversion generation artifact stage was preserved: {staged_name}"
            )
        return existing
    staged = transaction.stage_bytes(
        value.name,
        value.content,
        mode=value.mode,
        suffix="",
        phase_name=f"generation_{role}_stage",
        staged_name=staged_name,
    )
    transaction.phase("generation_artifact_stage_created", value.name)
    transaction.sync(f"generation_{role}_{value.name}_stage_durability")
    transaction.phase("generation_artifact_staged", value.name)
    return staged


def _restore_previous_generation(
    transaction: ByteArtifactTransaction,
    journal: _GenerationJournal,
    attempt_name: str,
    manifest_name: str,
) -> None:
    current_pair = _capture_pair(
        transaction,
        attempt_name,
        manifest_name,
        validate=False,
    )
    for current, previous, desired in zip(
        current_pair,
        journal.previous,
        journal.desired,
        strict=True,
    ):
        if not (_value_matches(current, previous) or _value_matches(current, desired)):
            raise OSError(
                f"Unknown replacement in interrupted conversion generation was preserved: {current.name}"
            )
    for previous in reversed(journal.previous):
        current = _capture_value(transaction, previous.name)
        if _value_matches(current, previous):
            continue
        if previous.present:
            staged = _stage_value(
                transaction,
                previous,
                journal.transaction_id,
                "previous",
            )
            completion_error = transaction.replace_staged(
                staged,
                previous.name,
            )
            transaction.phase(
                "generation_rollback_artifact_published",
                previous.name,
            )
            transaction.sync(f"generation_rollback_{previous.name}_durability")
            transaction.phase(
                "generation_rollback_artifact_durable",
                previous.name,
            )
            if completion_error is not None:
                raise completion_error
        else:
            if current.content is None or current.mode is None:
                raise OSError(
                    f"Conversion generation artifact disappeared: {current.name}"
                )
            current_snapshot = transaction.capture_snapshot(current.name)
            if (
                current_snapshot.content is None
                or current_snapshot.mode is None
                or current_snapshot.fingerprint is None
                or current_snapshot.sha256 is None
            ):
                raise OSError(f"Conversion generation artifact changed: {current.name}")
            current_stage = StagedArtifact(
                directory_path=transaction.path,
                name=current.name,
                identity=(
                    current_snapshot.fingerprint[0],
                    current_snapshot.fingerprint[1],
                ),
                content=current_snapshot.content,
                mode=current_snapshot.mode,
                target_mode=current_snapshot.mode,
                sha256=current_snapshot.sha256,
            )
            tombstone, completion_error = transaction.unlink_finalized(
                current_stage,
                current.name,
                tombstone_name=_artifact_tombstone_name(
                    current.name,
                    journal.transaction_id,
                ),
            )
            transaction.phase(
                "generation_rollback_artifact_published",
                current.name,
            )
            transaction.sync(f"generation_rollback_{current.name}_durability")
            transaction.phase(
                "generation_rollback_artifact_durable",
                current.name,
            )
            if completion_error is not None:
                raise completion_error
            if tombstone is not None:
                _remove_staged(transaction, tombstone)
                transaction.sync(
                    f"generation_rollback_{current.name}_tombstone_durability"
                )
    restored = _capture_pair(
        transaction,
        attempt_name,
        manifest_name,
    )
    if not _pair_matches(restored, journal.previous):
        raise OSError(
            "Interrupted conversion generation did not restore its prior pair"
        )
    transaction.phase("generation_rollback_complete", None)


def _verify_known_transition(
    transaction: ByteArtifactTransaction,
    journal: _GenerationJournal,
    attempt_name: str,
    manifest_name: str,
) -> None:
    current_pair = _capture_pair(
        transaction,
        attempt_name,
        manifest_name,
        validate=False,
    )
    for current, previous, desired in zip(
        current_pair,
        journal.previous,
        journal.desired,
        strict=True,
    ):
        if not (_value_matches(current, previous) or _value_matches(current, desired)):
            raise OSError(
                f"Unknown replacement in conversion generation was preserved: {current.name}"
            )


def _pointer_for_journal(
    journal: _GenerationJournal,
    journal_content: bytes,
) -> _GenerationPointer:
    return _GenerationPointer(
        transaction_id=journal.transaction_id,
        journal_sha256=artifact_sha256(journal_content),
        artifacts=cast(
            tuple[_GenerationReceipt, _GenerationReceipt],
            tuple(_receipt(value) for value in journal.desired),
        ),
    )


def _recover_locked(
    transaction: ByteArtifactTransaction,
    attempt_name: str,
    manifest_name: str,
) -> str | None:
    promoted = _promote_journal_temporary(
        transaction,
        attempt_name,
        manifest_name,
    )
    journal_record = _read_journal(
        transaction,
        attempt_name,
        manifest_name,
    )
    if journal_record is None:
        _validate_reserved_names(transaction, None)
        pointer_record = _read_pointer(
            transaction,
            attempt_name,
            manifest_name,
        )
        if pointer_record is None:
            _capture_pair(transaction, attempt_name, manifest_name)
            return None
        _snapshot, pointer = pointer_record
        _verify_pointer_generation(
            transaction,
            pointer,
            attempt_name,
            manifest_name,
        )
        return None

    journal_snapshot, journal = journal_record
    if journal_snapshot.content is None:
        raise AssertionError("A journal record must contain bytes")
    journal_content = journal_snapshot.content
    pointer = _pointer_for_journal(journal, journal_content)
    pointer_content = _pointer_content(pointer)
    _validate_reserved_names(transaction, journal)
    pointer_record = _read_pointer(
        transaction,
        attempt_name,
        manifest_name,
    )
    committed = (
        pointer_record is not None
        and pointer_record[1] == pointer
        and pointer_record[0].content == pointer_content
    )
    if committed:
        _verify_pointer_generation(
            transaction,
            pointer,
            attempt_name,
            manifest_name,
        )
        _cleanup_generation_temporaries(
            transaction,
            journal,
            pointer_content,
        )
        _remove_journal(transaction, journal_content)
        transaction.phase("generation_recovery_committed", None)
        return "finalized a committed conversion artifact generation"

    if not _pointer_matches_receipt(
        pointer_record,
        journal.previous_pointer,
    ):
        raise OSError("Conversion generation journal and pointer disagree")
    _restore_previous_generation(
        transaction,
        journal,
        attempt_name,
        manifest_name,
    )
    _cleanup_generation_temporaries(
        transaction,
        journal,
        pointer_content,
    )
    _remove_journal(transaction, journal_content)
    transaction.phase("generation_recovery_rolled_back", None)
    message = "rolled back an interrupted conversion artifact generation"
    if promoted:
        message += " from its durable journal temporary"
    return message


def recover_conversion_artifact_generation(
    transaction: ByteArtifactTransaction,
    *,
    attempt_name: str,
    manifest_name: str,
) -> str | None:
    """Recover or verify the generation selected by its durable pointer."""

    if not transaction.available:
        transaction.verify_directory()
        return None
    with _ConversionGenerationLock.acquire(transaction):
        return _recover_locked(
            transaction,
            attempt_name,
            manifest_name,
        )


def _snapshot_receipt(
    snapshot: ArtifactSnapshot,
    pointer: _GenerationPointer,
) -> _PointerReceipt:
    return _pointer_receipt_from_snapshot(snapshot, pointer)


def _publish_journal(
    transaction: ByteArtifactTransaction,
    journal: _GenerationJournal,
) -> tuple[bytes, StagedArtifact]:
    content = _journal_content(journal)
    temporary_name = _journal_temporary_name(journal.transaction_id)
    staged = transaction.stage_bytes(
        _GENERATION_JOURNAL_NAME,
        content,
        mode=0o600,
        suffix="",
        phase_name="generation_journal_stage",
        staged_name=temporary_name,
    )
    transaction.phase("generation_journal_stage_created", temporary_name)
    transaction.sync("generation_journal_stage_durability")
    transaction.phase("generation_journal_staged", temporary_name)
    completion_error = transaction.replace_staged(
        staged,
        _GENERATION_JOURNAL_NAME,
    )
    transaction.phase(
        "generation_journal_published",
        _GENERATION_JOURNAL_NAME,
    )
    transaction.sync("generation_journal_durability")
    if completion_error is not None:
        raise completion_error
    transaction.phase(
        "generation_journal_prepared",
        _GENERATION_JOURNAL_NAME,
    )
    return content, staged


def _current_pointer_is(
    transaction: ByteArtifactTransaction,
    pointer: _GenerationPointer,
    attempt_name: str,
    manifest_name: str,
) -> bool:
    try:
        current = _read_pointer(
            transaction,
            attempt_name,
            manifest_name,
        )
    except OSError:
        return False
    return (
        current is not None
        and current[1] == pointer
        and current[0].content == _pointer_content(pointer)
    )


def _publish_pointer(
    transaction: ByteArtifactTransaction,
    journal: _GenerationJournal,
    pointer: _GenerationPointer,
) -> BaseException | None:
    content = _pointer_content(pointer)
    pointer_mode = (
        0o600 if journal.previous_pointer is None else journal.previous_pointer.mode
    )
    temporary_name = _pointer_temporary_name(journal.transaction_id)
    staged = transaction.stage_bytes(
        _GENERATION_POINTER_NAME,
        content,
        mode=pointer_mode,
        suffix="",
        phase_name="generation_pointer_stage",
        staged_name=temporary_name,
    )
    transaction.phase("generation_pointer_stage_created", temporary_name)
    transaction.sync("generation_pointer_stage_durability")
    transaction.phase("generation_pointer_staged", temporary_name)
    completion_error = transaction.replace_staged(
        staged,
        _GENERATION_POINTER_NAME,
    )
    transaction.phase(
        "generation_pointer_published",
        _GENERATION_POINTER_NAME,
    )
    transaction.sync("generation_pointer_durability")
    transaction.phase(
        "generation_committed",
        _GENERATION_POINTER_NAME,
    )
    return completion_error


def _publish_locked(
    transaction: ByteArtifactTransaction,
    *,
    attempt_name: str,
    manifest_name: str,
    attempt_content: bytes | Callable[[bytes | None], bytes],
    manifest_content: bytes | None,
    before_commit: Callable[[str], None] | None,
    after_commit: Callable[[str], None] | None,
) -> None:
    _recover_locked(transaction, attempt_name, manifest_name)
    previous = _capture_pair(
        transaction,
        attempt_name,
        manifest_name,
    )
    resolved_attempt_content = (
        attempt_content(previous[1].content)
        if callable(attempt_content)
        else attempt_content
    )
    pointer_record = _read_pointer(
        transaction,
        attempt_name,
        manifest_name,
    )
    previous_pointer = (
        None
        if pointer_record is None
        else _snapshot_receipt(pointer_record[0], pointer_record[1])
    )
    desired_manifest = (
        previous[1]
        if manifest_content is None
        else _GenerationValue(
            manifest_name,
            manifest_content,
            previous[1].mode if previous[1].mode is not None else 0o600,
        )
    )
    desired = (
        _GenerationValue(
            attempt_name,
            resolved_attempt_content,
            previous[0].mode if previous[0].mode is not None else 0o600,
        ),
        desired_manifest,
    )
    _validate_conversion_pair(desired)
    transaction_id = os.urandom(16).hex()
    journal = _GenerationJournal(
        transaction_id=transaction_id,
        directory_identity=transaction.directory.identity,
        previous_pointer=previous_pointer,
        previous=previous,
        desired=desired,
    )
    journal_content = b""
    pointer: _GenerationPointer | None = None
    committed = False
    try:
        journal_content, _journal_stage = _publish_journal(
            transaction,
            journal,
        )
        pointer = _pointer_for_journal(journal, journal_content)
        for desired_value in desired:
            current = _capture_value(transaction, desired_value.name)
            if _value_matches(current, desired_value):
                if (
                    desired_value.name == manifest_name
                    and manifest_content is not None
                ):
                    if before_commit is not None:
                        before_commit(desired_value.name)
                    if after_commit is not None:
                        after_commit(desired_value.name)
                    _verify_known_transition(
                        transaction,
                        journal,
                        attempt_name,
                        manifest_name,
                    )
                continue
            previous_value = next(
                value for value in previous if value.name == desired_value.name
            )
            if not _value_matches(current, previous_value):
                raise OSError(
                    f"Conversion artifact changed during generation publication: {desired_value.name}"
                )
            if before_commit is not None:
                before_commit(desired_value.name)
                current = _capture_value(
                    transaction,
                    desired_value.name,
                )
                if not _value_matches(current, previous_value):
                    raise OSError(
                        f"Conversion artifact changed before generation publication: {desired_value.name}"
                    )
            staged = _stage_value(
                transaction,
                desired_value,
                transaction_id,
                "desired",
            )
            _verify_known_transition(
                transaction,
                journal,
                attempt_name,
                manifest_name,
            )
            completion_error = transaction.replace_staged(
                staged,
                desired_value.name,
            )
            transaction.phase(
                "generation_artifact_published",
                desired_value.name,
            )
            transaction.sync(f"generation_{desired_value.name}_durability")
            transaction.phase(
                "generation_artifact_durable",
                desired_value.name,
            )
            if completion_error is not None:
                raise completion_error
            if after_commit is not None:
                after_commit(desired_value.name)
            _verify_known_transition(
                transaction,
                journal,
                attempt_name,
                manifest_name,
            )

        published_pair = _capture_pair(
            transaction,
            attempt_name,
            manifest_name,
        )
        if not _pair_matches(published_pair, desired):
            raise OSError("Published conversion artifact generation is incomplete")
        journal_record = _read_journal(
            transaction,
            attempt_name,
            manifest_name,
        )
        if (
            journal_record is None
            or journal_record[1] != journal
            or journal_record[0].content != journal_content
        ):
            raise OSError("Conversion generation journal changed before commit")
        pointer_error = _publish_pointer(
            transaction,
            journal,
            pointer,
        )
        committed = _current_pointer_is(
            transaction,
            pointer,
            attempt_name,
            manifest_name,
        )
        if not committed:
            raise OSError("Conversion generation pointer did not commit")
        _verify_pointer_generation(
            transaction,
            pointer,
            attempt_name,
            manifest_name,
        )
        if pointer_error is not None:
            raise pointer_error
        _cleanup_generation_temporaries(
            transaction,
            journal,
            _pointer_content(pointer),
        )
        _remove_journal(transaction, journal_content)
        transaction.verify_directory()
    except BaseException as error:
        if pointer is not None and _current_pointer_is(
            transaction,
            pointer,
            attempt_name,
            manifest_name,
        ):
            committed = True
        if committed:
            error.add_note(
                "The new conversion artifact generation pointer was published; "
                "recovery will verify the selected generation and finish cleanup"
            )
            raise
        try:
            _recover_locked(
                transaction,
                attempt_name,
                manifest_name,
            )
        except BaseException as rollback_error:
            error.add_note(
                f"Conversion generation rollback also failed: {rollback_error}"
            )
        raise


def publish_conversion_artifact_generation(
    transaction: ByteArtifactTransaction,
    *,
    attempt_name: str,
    manifest_name: str,
    attempt_content: bytes | Callable[[bytes | None], bytes],
    manifest_content: bytes | None,
    before_commit: Callable[[str], None] | None = None,
    after_commit: Callable[[str], None] | None = None,
) -> None:
    """Publish the stable attempt/manifest paths as one recoverable generation."""

    with _ConversionGenerationLock.acquire(transaction):
        _publish_locked(
            transaction,
            attempt_name=attempt_name,
            manifest_name=manifest_name,
            attempt_content=attempt_content,
            manifest_content=manifest_content,
            before_commit=before_commit,
            after_commit=after_commit,
        )


def is_conversion_generation_auxiliary(filename: str) -> bool:
    return filename in {
        _GENERATION_LOCK_NAME,
        _GENERATION_JOURNAL_NAME,
        _GENERATION_POINTER_NAME,
    } or _reserved_generation_name(filename)


__all__ = [
    "CONVERSION_GENERATION_JOURNAL_NAME",
    "CONVERSION_GENERATION_LOCK_NAME",
    "CONVERSION_GENERATION_POINTER_NAME",
    "ConversionArtifactGenerationLock",
    "is_conversion_generation_auxiliary",
    "publish_conversion_artifact_generation",
    "recover_conversion_artifact_generation",
]
