"""Descriptor-retained POSIX publication for small immutable receipts.

The private staging protections assume adversaries cannot access or mutate the
retained descriptor. They do not claim protection from same-UID processes or
root once those actors can inspect this process or its open descriptors.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import errno
import functools
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Callable, NoReturn, Protocol, TYPE_CHECKING


if TYPE_CHECKING:

    class AnchoredOutputError(ValueError):
        code: str

        def __init__(self, code: str, message: str) -> None: ...

    class OutputParentBinding(Protocol):
        parent: Path
        leaf: str
        strategy: str
        descriptors: tuple[int, ...]

        def stat(self, name: str) -> os.stat_result: ...
        def open_read(self, name: str, lease: _PosixDescriptorLease) -> int: ...
        def verify(self) -> None: ...
        def sync(self) -> None: ...
        def close(self) -> list[BaseException]: ...

    class _PosixDescriptorLease:
        descriptor: int | None

        def close(self) -> None: ...

    def _close_posix_descriptor_lease(
        lease: _PosixDescriptorLease,
        primary: BaseException | None,
        context: str,
    ) -> BaseException | None: ...

    def _darwin_descriptor_has_extended_acl(
        descriptor: int,
        *,
        error_code: str = "output-anchor-unavailable",
        context: str = "retained macOS descriptor",
    ) -> bool: ...

    def _open_posix_descriptor(
        lease: _PosixDescriptorLease,
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int: ...

    def _read_exact_receipt(
        binding: OutputParentBinding,
        name: str,
        expected_payload: bytes,
        *,
        descriptor_lease: _PosixDescriptorLease,
        expected_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]: ...

    def _receipt_mode_is_canonical(value: os.stat_result) -> bool: ...
    def _same_identity(value: os.stat_result, identity: tuple[int, int]) -> bool: ...
    def _stable_file_metadata(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]: ...
    def _validate_safe_posix_directory_descriptor(
        descriptor: int,
        *,
        code: str,
        context: str,
        require_private: bool = False,
    ) -> os.stat_result: ...


_LINUX_AT_FDCWD = -100
_LINUX_AT_SYMLINK_FOLLOW = 0x400
_DARWIN_RECEIPT_STAGING_ROOT = ".gm2godot-receipt-staging"
_DARWIN_RECEIPT_STAGING_ROOT_ALTERNATE = ".gm2godot-receipt-staging.private"
_DARWIN_RENAME_EXCL = 0x00000004
_NATIVE_RESULT_PENDING = object()
_POSIX_PUBLICATION_UNAVAILABLE_ERRNOS = frozenset(
    {
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
)


@dataclass(frozen=True)
class _PosixReceiptStage:
    descriptor: int
    private_directory_descriptor: int = -1
    private_directory_name: str = ""
    private_directory_identity: tuple[int, int] | None = None
    named_stage_name: str = ""


@dataclass
class _PosixReceiptStageLease:
    descriptor: _PosixDescriptorLease
    private_directory: _PosixDescriptorLease
    stage: _PosixReceiptStage | None = None
    named_stage_name: str | None = None
    named_cleanup_attempts: int = 0
    named_stage_retained: bool = False
    private_directory_sync_pending: bool = False
    private_directory_sync_attempts: int = 0
    private_directory_sync_retained: bool = False
    rename_result: object = _NATIVE_RESULT_PENDING
    rename_errno: int = 0


@dataclass
class _PosixReceiptPublicationLease:
    """Own every transient descriptor outside the publisher's exception table."""

    binding: OutputParentBinding
    stage: _PosixReceiptStageLease = field(
        default_factory=lambda: _PosixReceiptStageLease(
            _PosixDescriptorLease(),
            _PosixDescriptorLease(),
        )
    )
    transient_descriptors: list[_PosixDescriptorLease] = field(default_factory=lambda: list[_PosixDescriptorLease]())
    _private_verification_complete: bool = False
    _closed: bool = False

    def new_transient_descriptor(self) -> _PosixDescriptorLease:
        lease = _PosixDescriptorLease()
        self.transient_descriptors.append(lease)
        return lease

    @property
    def is_closed(self) -> bool:
        return self._closed or (
            self.stage.descriptor.descriptor is None
            and self.stage.private_directory.descriptor is None
            and all(lease.descriptor is None for lease in self.transient_descriptors)
            and (self.stage.named_stage_name is None or self.stage.named_stage_retained)
            and (
                not self.stage.private_directory_sync_pending
                or self.stage.private_directory_sync_retained
            )
        )

    def close(self) -> tuple[BaseException, ...]:
        if self._closed:
            return ()
        failures: list[BaseException] = []

        def close_descriptor(lease: _PosixDescriptorLease, context: str) -> bool:
            failure_count = len(failures)
            close_error: BaseException | None = None
            for _attempt in range(2):
                try:
                    close_error = _close_posix_descriptor_lease(
                        lease,
                        None,
                        context,
                    )
                except BaseException as close_call_error:
                    failures.append(close_call_error)
                    if lease.descriptor is not None:
                        continue
                else:
                    if close_error is not None:
                        failures.append(close_error)
                break
            try:
                descriptor_closed = lease.descriptor is None
            except BaseException as status_error:
                failures.append(status_error)
                descriptor_closed = False
            if not descriptor_closed and len(failures) == failure_count:
                failures.append(
                    AnchoredOutputError(
                        "output-cleanup-retained",
                        f"The {context} remained open after bounded cleanup attempts.",
                    )
                )
            return descriptor_closed

        for transient in reversed(self.transient_descriptors):
            if not close_descriptor(transient, "receipt verification descriptor"):
                return tuple(failures)
        if (
            sys.platform == "darwin"
            and self.stage.named_stage_name is not None
            and not self.stage.named_stage_retained
        ):
            for _attempt in range(2):
                if self.stage.named_cleanup_attempts >= 4:
                    break
                self.stage.named_cleanup_attempts += 1
                try:
                    _cleanup_darwin_named_stage(self.stage)
                except BaseException as cleanup_error:
                    failures.append(cleanup_error)
                    continue
                break
        if (
            self.stage.named_stage_name is not None
            and not self.stage.named_stage_retained
            and self.stage.named_cleanup_attempts < 4
        ):
            # Keep both identity descriptors alive for the outer owner to make
            # one more bounded cleanup pass before giving up safely.
            return tuple(failures)
        if self.stage.named_stage_name is not None and not self.stage.named_stage_retained:
            self.stage.named_stage_retained = True
            failures.append(
                AnchoredOutputError(
                    "output-cleanup-retained",
                    "The private macOS receipt staging name could not be removed after bounded identity checks; "
                    "the entry was left untouched.",
                )
            )
        if (
            self.stage.private_directory_sync_pending
            and not self.stage.private_directory_sync_retained
            and self.stage.private_directory_sync_attempts < 4
        ):
            for _attempt in range(2):
                if self.stage.private_directory_sync_attempts >= 4:
                    break
                try:
                    _sync_darwin_private_directory_if_pending(self.stage)
                except BaseException as sync_error:
                    failures.append(sync_error)
                    continue
                break
        if (
            self.stage.private_directory_sync_pending
            and not self.stage.private_directory_sync_retained
            and self.stage.private_directory_sync_attempts < 4
        ):
            # The private directory must outlive its retryable durability
            # barrier just as it outlives a retryable named-stage cleanup.
            return tuple(failures)
        if self.stage.private_directory_sync_pending and not self.stage.private_directory_sync_retained:
            self.stage.private_directory_sync_retained = True
            failures.append(
                AnchoredOutputError(
                    "output-cleanup-retained",
                    "The private macOS receipt directory could not be durably flushed after bounded retries.",
                )
            )
        if not close_descriptor(self.stage.descriptor, "receipt staging descriptor"):
            return tuple(failures)
        retained_stage = self.stage.stage
        if (
            retained_stage is not None
            and retained_stage.private_directory_descriptor >= 0
            and not self._private_verification_complete
        ):
            try:
                _verify_darwin_private_directory(self.binding, retained_stage)
            except BaseException as verification_error:
                failures.append(verification_error)
            finally:
                self._private_verification_complete = True
        if not close_descriptor(
            self.stage.private_directory,
            "private receipt directory descriptor",
        ):
            return tuple(failures)
        self._closed = self.is_closed
        return tuple(failures)


def _raise_posix_publication_error(
    error_number: int,
    destination: str,
    *,
    operation: str,
    additional_unavailable: frozenset[int] = frozenset(),
) -> NoReturn:
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    if error_number in _POSIX_PUBLICATION_UNAVAILABLE_ERRNOS | additional_unavailable:
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            f"The filesystem does not support descriptor-bound receipt {operation}.",
        )
    raise OSError(error_number, os.strerror(error_number), destination)


def _linux_link_receipt_descriptor(
    descriptor: int,
    directory_descriptor: int,
    destination: str,
) -> None:
    """Link one unnamed Linux file descriptor without replacing a name."""

    libc = ctypes.CDLL(None, use_errno=True)
    operation = getattr(libc, "linkat", None)
    if operation is None:
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "Linux linkat is unavailable for descriptor-bound receipt publication.",
        )
    operation.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    )
    operation.restype = ctypes.c_int
    source = os.fsencode(f"/proc/self/fd/{descriptor}")
    if (
        operation(
            _LINUX_AT_FDCWD,
            source,
            directory_descriptor,
            os.fsencode(destination),
            _LINUX_AT_SYMLINK_FOLLOW,
        )
        == 0
    ):
        return
    _raise_posix_publication_error(
        ctypes.get_errno(),
        destination,
        operation="linking",
        additional_unavailable=frozenset(
            {
                errno.EACCES,
                errno.ENOENT,
                errno.ENOTDIR,
                errno.EPERM,
                errno.EXDEV,
            }
        ),
    )


def _darwin_rename_receipt_stage(
    stage: _PosixReceiptStage,
    lease: _PosixReceiptStageLease,
    directory_descriptor: int,
    destination: str,
) -> None:
    """Move one private retained inode into place without replacement."""

    source_name = lease.named_stage_name
    if not source_name or source_name != stage.named_stage_name:
        raise AnchoredOutputError(
            "output-temporary-invalid",
            "The private macOS receipt stage has no retained source name.",
        )
    source_entry = os.stat(
        source_name,
        dir_fd=stage.private_directory_descriptor,
        follow_symlinks=False,
    )
    source_descriptor = os.fstat(stage.descriptor)
    if (
        not stat.S_ISREG(source_entry.st_mode)
        or source_entry.st_nlink != 1
        or _stable_file_metadata(source_entry) != _stable_file_metadata(source_descriptor)
    ):
        raise AnchoredOutputError(
            "output-temporary-invalid",
            "The private macOS receipt staging name changed before publication.",
        )

    libc = ctypes.CDLL(None, use_errno=True)
    operation = getattr(libc, "renameatx_np", None)
    if operation is None:
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "macOS renameatx_np is unavailable for descriptor-bound receipt publication.",
        )
    operation.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )

    class _RenameResult(ctypes.c_int):
        pass

    setattr(
        _RenameResult,
        "_check_retval_",
        functools.partial(setattr, lease, "rename_result"),
    )
    operation.restype = _RenameResult
    lease.private_directory_sync_pending = True
    ctypes.set_errno(0)
    operation(
        stage.private_directory_descriptor,
        os.fsencode(source_name),
        directory_descriptor,
        os.fsencode(destination),
        _DARWIN_RENAME_EXCL,
    )
    lease.rename_errno = ctypes.get_errno()
    result = getattr(lease.rename_result, "value", lease.rename_result)
    if not isinstance(result, int):
        raise OSError("Native macOS receipt rename returned without recording its result.")
    if result == 0:
        return
    _raise_posix_publication_error(
        lease.rename_errno or errno.EIO,
        destination,
        operation="renaming",
    )


def _validate_exact_receipt_descriptor(
    descriptor: int,
    payload: bytes,
    expected_identity: tuple[int, int],
    *,
    expected_link_count: int,
    code: str,
) -> None:
    """Read and validate the exact retained inode used for publication."""

    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != expected_link_count
        or not _same_identity(before, expected_identity)
        or not _receipt_mode_is_canonical(before)
        or _darwin_descriptor_has_extended_acl(
            descriptor,
            error_code=code,
            context="retained receipt descriptor",
        )
    ):
        raise AnchoredOutputError(
            code,
            "The retained receipt descriptor is not one canonical private regular file.",
        )
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = len(payload) + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(descriptor)
    if (
        _stable_file_metadata(before) != _stable_file_metadata(after)
        or not _receipt_mode_is_canonical(after)
        or _darwin_descriptor_has_extended_acl(
            descriptor,
            error_code=code,
            context="retained receipt descriptor after reading",
        )
        or b"".join(chunks) != payload
    ):
        raise AnchoredOutputError(
            code,
            "The retained receipt descriptor changed during exact verification.",
        )


def _write_and_sync_retained_descriptor(descriptor: int, payload: bytes) -> None:
    """Write and sync a new staging inode while retaining its descriptor."""

    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    written = 0
    while written < len(payload):
        count = os.write(descriptor, payload[written:])
        if count <= 0:
            raise OSError(errno.EIO, "Could not write the complete receipt staging payload.")
        written += count
    os.fsync(descriptor)


def _sync_posix_public_descriptor(
    binding: OutputParentBinding,
    payload: bytes,
    expected_identity: tuple[int, int],
    descriptor_lease: _PosixDescriptorLease,
) -> None:
    """Bind, validate, and durably flush one exact public receipt inode."""
    descriptor: int | None = None
    primary: BaseException | None = None
    try:
        try:
            descriptor = binding.open_read(binding.leaf, descriptor_lease)
        except OSError as error:
            if not isinstance(error, FileNotFoundError) and error.errno not in {errno.ENOENT, errno.ELOOP}:
                raise
            translated = AnchoredOutputError(
                "output-changed",
                f"Published receipt changed while it was being opened: {binding.parent / binding.leaf}.",
            )
            for note in getattr(error, "__notes__", ()):
                translated.add_note(note)
            raise translated from error
        _validate_exact_receipt_descriptor(
            descriptor,
            payload,
            expected_identity,
            expected_link_count=1,
            code="output-changed",
        )
        os.fsync(descriptor)
    except BaseException as error:
        primary = error
        raise
    finally:
        close_call_failures: list[BaseException] = []
        close_error: BaseException | None = None
        for _attempt in range(2):
            try:
                close_error = _close_posix_descriptor_lease(
                    descriptor_lease,
                    primary,
                    "published receipt descriptor",
                )
            except BaseException as close_call_error:
                # Catch both a pre-call interruption and one delivered after
                # the helper returned but before Python stored its result.
                close_call_failures.append(close_call_error)
                if descriptor_lease.descriptor is not None:
                    continue
            break
        if primary is not None:
            for close_call_error in close_call_failures:
                primary.add_note(f"Could not close published receipt descriptor: {close_call_error}")
        elif close_call_failures:
            first_close_failure = close_call_failures[0]
            for later_failure in close_call_failures[1:]:
                first_close_failure.add_note(f"Published receipt close failure: {later_failure}")
            raise first_close_failure
        elif close_error is not None:
            raise close_error


def _darwin_private_directory_is_canonical(
    value: os.stat_result,
    identity: tuple[int, int],
) -> bool:
    return (
        stat.S_ISDIR(value.st_mode)
        and _same_identity(value, identity)
        and stat.S_IMODE(value.st_mode) == 0o700
        and value.st_uid == os.geteuid()
    )


def _verify_darwin_private_directory(
    binding: OutputParentBinding,
    stage: _PosixReceiptStage,
) -> None:
    """Report outer-name changes without removing any directory by name.

    macOS has no public descriptor-bound directory-removal primitive. The
    stable 0700 staging root is therefore intentionally retained: a final
    ``rmdir`` through the writable parent would reintroduce a last-component
    swap race after an otherwise descriptor-bound publication.
    """

    identity = stage.private_directory_identity
    if stage.private_directory_descriptor < 0 or identity is None:
        raise AnchoredOutputError(
            "output-cleanup-retained",
            "The macOS receipt staging directory was not bound for safe cleanup.",
        )
    try:
        entry = binding.stat(stage.private_directory_name)
        opened = os.fstat(stage.private_directory_descriptor)
    except BaseException as error:
        raise AnchoredOutputError(
            "output-cleanup-retained",
            "The stable macOS receipt staging root is missing or cannot be verified; no outer directory was removed.",
        ) from error
    if not (
        _darwin_private_directory_is_canonical(entry, identity)
        and _darwin_private_directory_is_canonical(opened, identity)
        and not _darwin_descriptor_has_extended_acl(
            stage.private_directory_descriptor,
            error_code="output-cleanup-retained",
            context="private macOS receipt directory",
        )
    ):
        raise AnchoredOutputError(
            "output-cleanup-retained",
            "The stable macOS receipt staging root changed; no outer directory was removed.",
        )


def _unlink_darwin_stage_if_identity(
    directory_descriptor: int,
    stage_name: str,
    identity: tuple[int, int],
    *,
    before_unlink: Callable[[], None] | None = None,
) -> None:
    entry: os.stat_result | None = None
    for _attempt in range(2):
        try:
            entry = os.stat(
                stage_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            # A control-flow exception can replace a successful stat return
            # before Python stores it. Re-observe once before concluding that
            # the leased stage name is absent.
            continue
        break
    if entry is None:
        return
    if not stat.S_ISREG(entry.st_mode) or not _same_identity(entry, identity):
        raise AnchoredOutputError(
            "output-cleanup-retained",
            "The private macOS receipt staging entry changed and was left untouched.",
        )
    if before_unlink is not None:
        before_unlink()
    os.unlink(stage_name, dir_fd=directory_descriptor)


def _cleanup_darwin_named_stage(lease: _PosixReceiptStageLease) -> None:
    """Remove only the still-named inode owned by a Darwin stage lease."""

    stage_name = lease.named_stage_name
    if stage_name is None:
        _sync_darwin_private_directory_if_pending(lease)
        return
    stage_descriptor = lease.descriptor.descriptor
    if stage_descriptor is None:
        # The candidate name is recorded before openat. Without a leased
        # descriptor there is no identity that authorizes removing anything.
        lease.named_stage_name = None
        return
    private_descriptor = lease.private_directory.descriptor
    if private_descriptor is None:
        raise AnchoredOutputError(
            "output-cleanup-retained",
            "The failed private receipt stage is still named, but its directory descriptor is unavailable.",
        )
    leased_stage = os.fstat(stage_descriptor)
    if (
        not stat.S_ISREG(leased_stage.st_mode)
        or _darwin_descriptor_has_extended_acl(
            stage_descriptor,
            error_code="output-cleanup-retained",
            context="private macOS receipt stage during cleanup",
        )
    ):
        raise AnchoredOutputError(
            "output-cleanup-retained",
            "The failed private receipt staging descriptor is not a regular file; no named entry was removed.",
        )
    _unlink_darwin_stage_if_identity(
        private_descriptor,
        stage_name,
        (leased_stage.st_dev, leased_stage.st_ino),
        before_unlink=lambda: setattr(
            lease,
            "private_directory_sync_pending",
            True,
        ),
    )
    lease.named_stage_name = None
    _sync_darwin_private_directory_if_pending(lease)


def _sync_darwin_private_directory_if_pending(lease: _PosixReceiptStageLease) -> None:
    """Retry the source-directory barrier after unlink or rename removal."""

    if not lease.private_directory_sync_pending:
        return
    private_descriptor = lease.private_directory.descriptor
    if private_descriptor is None:
        raise AnchoredOutputError(
            "output-cleanup-retained",
            "The private macOS receipt directory needs a durability retry but its descriptor is unavailable.",
        )
    lease.private_directory_sync_attempts += 1
    os.fsync(private_descriptor)
    lease.private_directory_sync_pending = False


def _open_darwin_receipt_stage(
    binding: OutputParentBinding,
    private_directory_name: str,
    lease: _PosixReceiptStageLease,
) -> _PosixReceiptStage:
    """Create a named source inside one stable retained ACL-free 0700 root.

    A writer with access only to the shared parent may rename or replace the
    stable outer entry, but cannot redirect inner operations away from the
    retained directory descriptor. Darwin cannot prevent a hostile same-UID
    process from opening or mutating another process's staging inode.
    """

    parent_descriptor = binding.descriptors[-1]
    private_created = False
    private_descriptor = -1
    private_identity: tuple[int, int] | None = None
    stage_descriptor = -1
    stage_name = ""
    try:
        created: os.stat_result | None = None
        for _attempt in range(2):
            try:
                created = binding.stat(private_directory_name)
            except FileNotFoundError:
                # Re-observe once so a return-boundary exception cannot make
                # an existing wrong-mode root look absent and eligible for
                # sealing as a directory created by this call.
                continue
            break
        if created is None:
            _validate_safe_posix_directory_descriptor(
                parent_descriptor,
                code="output-temporary-invalid",
                context="macOS receipt staging-root creation parent",
            )
            try:
                os.mkdir(private_directory_name, 0o700, dir_fd=parent_descriptor)
            except FileExistsError as create_error:
                raise AnchoredOutputError(
                    "output-temporary-invalid",
                    "The macOS receipt staging root appeared after it was observed missing.",
                ) from create_error
            private_created = True
            created = binding.stat(private_directory_name)
        if (
            not stat.S_ISDIR(created.st_mode)
            or created.st_uid != os.geteuid()
            or (
                not private_created
                and stat.S_IMODE(created.st_mode) != 0o700
            )
            or (
                private_created
                and stat.S_IMODE(created.st_mode) & ~0o700
            )
        ):
            raise AnchoredOutputError(
                "output-temporary-invalid",
                "The stable macOS receipt staging root is not a current-user-owned 0700 directory.",
            )
        private_identity = (created.st_dev, created.st_ino)
        if private_created:
            # The public parent was proven safe before mkdir, so another UID
            # cannot swap this entry while a restrictive umask is repaired.
            # Same-UID/root interference remains outside the threat model.
            os.chmod(
                private_directory_name,
                0o700,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            created = binding.stat(private_directory_name)
            if not _darwin_private_directory_is_canonical(created, private_identity):
                raise AnchoredOutputError(
                    "output-temporary-invalid",
                    "The new macOS receipt staging root changed while its mode was sealed.",
                )
        private_descriptor = _open_posix_descriptor(
            lease.private_directory,
            private_directory_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        opened_directory = os.fstat(private_descriptor)
        if (
            not stat.S_ISDIR(opened_directory.st_mode)
            or opened_directory.st_uid != os.geteuid()
            or not _same_identity(opened_directory, private_identity)
        ):
            raise AnchoredOutputError(
                "output-temporary-invalid",
                "The stable macOS receipt staging root changed while it was opened.",
            )
        if not _darwin_private_directory_is_canonical(
            opened_directory,
            private_identity,
        ) and private_created:
            os.fchmod(private_descriptor, 0o700)
            opened_directory = os.fstat(private_descriptor)
        if not _darwin_private_directory_is_canonical(
            opened_directory,
            private_identity,
        ):
            raise AnchoredOutputError(
                "output-temporary-invalid",
                "The stable macOS receipt staging root could not be sealed to mode 0700.",
            )
        _validate_safe_posix_directory_descriptor(
            private_descriptor,
            code="output-temporary-invalid",
            context="private macOS receipt staging root",
            require_private=True,
        )

        for _attempt in range(100):
            stage_name = f"{secrets.token_hex(16)}.tmp"
            # Record the candidate name before entering the native open. If
            # control flow is interrupted after openat has populated the
            # descriptor lease but before its return value reaches a Python
            # local, exception cleanup can still bind that name to the leased
            # descriptor's identity. A failed open owns no descriptor, so this
            # intent alone never authorizes unlinking an existing entry.
            lease.named_stage_name = stage_name
            try:
                stage_descriptor = _open_posix_descriptor(
                    lease.descriptor,
                    stage_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=private_descriptor,
                )
            except FileExistsError:
                # A FileExistsError raised at the Python call/return seam can
                # arrive after openat created the file and transferred its
                # descriptor into the lease. That is not a collision: keep
                # the original candidate name so outer cleanup can bind and
                # remove exactly the acquired inode.
                if lease.descriptor.descriptor is not None:
                    raise
                lease.named_stage_name = None
                continue
            break
        if stage_descriptor < 0:
            raise AnchoredOutputError(
                "output-temporary-unavailable",
                "Could not create a unique private macOS receipt staging inode.",
            )
        os.fchmod(stage_descriptor, 0o600)
        opened_stage = os.fstat(stage_descriptor)
        stage_entry = os.stat(
            stage_name,
            dir_fd=private_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened_stage.st_mode)
            or opened_stage.st_nlink != 1
            or not _receipt_mode_is_canonical(opened_stage)
            or _darwin_descriptor_has_extended_acl(
                stage_descriptor,
                error_code="output-temporary-invalid",
                context="private macOS receipt staging descriptor",
            )
            or _stable_file_metadata(opened_stage) != _stable_file_metadata(stage_entry)
        ):
            raise AnchoredOutputError(
                "output-temporary-invalid",
                "The private macOS receipt staging inode changed before publication.",
            )
        stage = _PosixReceiptStage(
            descriptor=stage_descriptor,
            private_directory_descriptor=private_descriptor,
            private_directory_name=private_directory_name,
            private_directory_identity=private_identity,
            named_stage_name=stage_name,
        )
        lease.stage = stage
        return stage
    except BaseException as error:
        if lease.named_stage_name is not None and not lease.named_stage_retained:
            while lease.named_cleanup_attempts < 4:
                lease.named_cleanup_attempts += 1
                try:
                    _cleanup_darwin_named_stage(lease)
                except BaseException as cleanup_error:
                    error.add_note(f"Could not remove failed private receipt staging: {cleanup_error}")
                    continue
                break
        if lease.named_stage_name is not None and not lease.named_stage_retained:
            lease.named_stage_retained = True
            error.add_note("The failed private receipt staging name was left untouched after bounded identity checks.")
        if (
            lease.private_directory_sync_pending
            and not lease.private_directory_sync_retained
        ):
            while lease.private_directory_sync_attempts < 4:
                try:
                    _sync_darwin_private_directory_if_pending(lease)
                except BaseException as sync_error:
                    error.add_note(
                        "Could not durably flush the failed private receipt staging directory: "
                        f"{sync_error}"
                    )
                    continue
                break
        if (
            lease.private_directory_sync_pending
            and not lease.private_directory_sync_retained
        ):
            # Record the exhausted durability obligation before either owned
            # descriptor can be closed. The outer publication lease may then
            # finish bounded cleanup without replaying an ambiguous barrier.
            lease.private_directory_sync_retained = True
            error.add_note(
                "The failed private receipt staging directory could not be durably flushed "
                "after bounded retries."
            )
        for descriptor_lease, context in (
            (lease.descriptor, "failed receipt staging descriptor"),
            (lease.private_directory, "failed private receipt directory"),
        ):
            for _attempt in range(2):
                try:
                    close_error = _close_posix_descriptor_lease(
                        descriptor_lease,
                        error,
                        context,
                    )
                except BaseException as close_call_error:
                    error.add_note(f"Could not close {context}: {close_call_error}")
                    if descriptor_lease.descriptor is not None:
                        continue
                else:
                    if close_error is not error and close_error is not None:
                        error.add_note(f"Could not close {context}: {close_error}")
                break
            try:
                descriptor_closed = descriptor_lease.descriptor is None
            except BaseException as status_error:
                error.add_note(f"Could not confirm closure of {context}: {status_error}")
                descriptor_closed = False
            if not descriptor_closed:
                error.add_note(f"The {context} remained open after bounded cleanup attempts.")
                # The private directory is the staging descriptor's retained
                # parent and must outlive it when cleanup cannot finish.
                break
        if private_descriptor < 0 and private_created:
            error.add_note(
                "The stable macOS receipt staging root was intentionally left in place because macOS has no "
                "descriptor-bound directory-removal primitive."
            )
        raise


def _open_posix_receipt_stage(
    binding: OutputParentBinding,
    temporary_name: str,
    lease: _PosixReceiptStageLease,
) -> _PosixReceiptStage:
    """Open Linux unnamed staging or a private named macOS stage."""

    if binding.strategy != "posix-dir-fd":
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "Descriptor-bound POSIX receipt staging requires a retained directory descriptor.",
        )
    if sys.platform.startswith("linux"):
        temporary_flag = int(getattr(os, "O_TMPFILE", 0))
        if not temporary_flag:
            raise AnchoredOutputError(
                "output-anchor-unavailable",
                "Linux O_TMPFILE is unavailable for descriptor-bound receipt staging.",
            )
        flags = os.O_RDWR | temporary_flag | getattr(os, "O_CLOEXEC", 0)
        try:
            try:
                descriptor = _open_posix_descriptor(
                    lease.descriptor,
                    ".",
                    flags,
                    0o600,
                    dir_fd=binding.descriptors[-1],
                )
            except OSError as error:
                if error.errno in _POSIX_PUBLICATION_UNAVAILABLE_ERRNOS | {
                    errno.EISDIR,
                    errno.ENOENT,
                }:
                    raise AnchoredOutputError(
                        "output-anchor-unavailable",
                        "The filesystem does not support Linux O_TMPFILE receipt staging.",
                    ) from error
                raise
            os.fchmod(descriptor, 0o600)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 0 or not _receipt_mode_is_canonical(opened):
                raise AnchoredOutputError(
                    "output-temporary-invalid",
                    "Receipt staging is not one canonical private regular file.",
                )
            stage = _PosixReceiptStage(descriptor=descriptor)
            lease.stage = stage
            return stage
        except BaseException as error:
            for _attempt in range(2):
                try:
                    close_error = _close_posix_descriptor_lease(
                        lease.descriptor,
                        error,
                        "failed receipt staging descriptor",
                    )
                except BaseException as close_call_error:
                    error.add_note(f"Could not close failed receipt staging descriptor: {close_call_error}")
                    if lease.descriptor.descriptor is not None:
                        continue
                else:
                    if close_error is not error and close_error is not None:
                        error.add_note(f"Could not close failed receipt staging descriptor: {close_error}")
                break
            raise
    if sys.platform == "darwin":
        return _open_darwin_receipt_stage(binding, temporary_name, lease)
    raise AnchoredOutputError(
        "output-anchor-unavailable",
        "This POSIX platform has no supported descriptor-bound receipt publication primitive.",
    )


def _publish_posix_receipt_descriptor(
    binding: OutputParentBinding,
    stage: _PosixReceiptStage,
    stage_lease: _PosixReceiptStageLease,
    destination: str,
    payload: bytes,
    expected_identity: tuple[int, int],
) -> None:
    """Verify and publish exactly the inode held by ``descriptor``."""

    binding.verify()
    _validate_exact_receipt_descriptor(
        stage.descriptor,
        payload,
        expected_identity,
        expected_link_count=(0 if sys.platform.startswith("linux") else 1),
        code="output-temporary-invalid",
    )
    if sys.platform.startswith("linux"):
        _linux_link_receipt_descriptor(
            stage.descriptor,
            binding.descriptors[-1],
            destination,
        )
        return
    if sys.platform == "darwin":
        _darwin_rename_receipt_stage(
            stage,
            stage_lease,
            binding.descriptors[-1],
            destination,
        )
        return
    raise AnchoredOutputError(
        "output-anchor-unavailable",
        "This POSIX platform has no supported descriptor-bound receipt publication primitive.",
    )


def _darwin_private_root_for_destination(destination: str) -> str:
    """Keep the implementation root distinct from every supported leaf."""

    if destination == _DARWIN_RECEIPT_STAGING_ROOT:
        return _DARWIN_RECEIPT_STAGING_ROOT_ALTERNATE
    return _DARWIN_RECEIPT_STAGING_ROOT


def _durably_verify_public_receipt(
    binding: OutputParentBinding,
    payload: bytes,
    expected_identity: tuple[int, int],
    publication_lease: _PosixReceiptPublicationLease,
) -> None:
    """Flush the exact public inode and parent, then verify the namespace."""

    _sync_posix_public_descriptor(
        binding,
        payload,
        expected_identity,
        publication_lease.new_transient_descriptor(),
    )
    binding.sync()
    _read_exact_receipt(
        binding,
        binding.leaf,
        payload,
        descriptor_lease=publication_lease.new_transient_descriptor(),
        expected_identity=expected_identity,
    )


def _publish_posix_receipt_bytes(
    path: Path,
    payload: bytes,
    binding: OutputParentBinding,
    publication_lease: _PosixReceiptPublicationLease,
) -> None:
    """Publish one canonical receipt through caller-retained ownership."""

    if publication_lease.binding is not binding:
        raise ValueError("POSIX receipt publication lease belongs to another binding.")
    stage_lease = publication_lease.stage
    stage: _PosixReceiptStage | None = None
    descriptor = -1
    source_identity: tuple[int, int] | None = None
    output_identity: tuple[int, int] | None = None
    publication_attempted = False
    primary_error: BaseException | None = None
    try:
        try:
            binding.stat(binding.leaf)
        except FileNotFoundError:
            pass
        else:
            output_identity = _read_exact_receipt(
                binding,
                binding.leaf,
                payload,
                descriptor_lease=publication_lease.new_transient_descriptor(),
            )
            _durably_verify_public_receipt(
                binding,
                payload,
                output_identity,
                publication_lease,
            )
            return

        if sys.platform == "darwin":
            stage = _open_posix_receipt_stage(
                binding,
                _darwin_private_root_for_destination(binding.leaf),
                stage_lease,
            )
            descriptor = stage.descriptor
        else:
            stage = _open_posix_receipt_stage(binding, "", stage_lease)
            descriptor = stage.descriptor
        opened = os.fstat(descriptor)
        source_identity = (opened.st_dev, opened.st_ino)
        _write_and_sync_retained_descriptor(descriptor, payload)
        _validate_exact_receipt_descriptor(
            descriptor,
            payload,
            source_identity,
            expected_link_count=(0 if sys.platform.startswith("linux") else 1),
            code="output-temporary-invalid",
        )

        source_link_count: int | None = None
        try:
            publication_attempted = True
            _publish_posix_receipt_descriptor(
                binding,
                stage,
                stage_lease,
                binding.leaf,
                payload,
                source_identity,
            )
        except FileExistsError:
            # FileExistsError may be a true collision or an exception delivered
            # after the native no-replace operation took effect. Observe the
            # public inode before deciding whether durability work is required.
            output_identity = _read_exact_receipt(
                binding,
                binding.leaf,
                payload,
                descriptor_lease=publication_lease.new_transient_descriptor(),
            )
            if sys.platform == "darwin":
                # A distinct exact collision winner leaves our source named;
                # an effect-then-exception leaves it absent. The same identity-
                # checked cleanup handles both and durably flushes the private
                # directory removal before the public parent.
                _cleanup_darwin_named_stage(stage_lease)
            _durably_verify_public_receipt(
                binding,
                payload,
                output_identity,
                publication_lease,
            )
            return
        if source_link_count is None:
            output_identity = source_identity
            _read_exact_receipt(
                binding,
                binding.leaf,
                payload,
                descriptor_lease=publication_lease.new_transient_descriptor(),
                expected_identity=source_identity,
            )
            if sys.platform == "darwin":
                _cleanup_darwin_named_stage(stage_lease)
            source_link_count = 1

        assert source_link_count is not None
        _validate_exact_receipt_descriptor(
            descriptor,
            payload,
            source_identity,
            expected_link_count=source_link_count,
            code="output-changed",
        )
        binding.verify()
        assert output_identity is not None
        _durably_verify_public_receipt(
            binding,
            payload,
            output_identity,
            publication_lease,
        )
    except BaseException as error:
        primary_error = error
        if publication_attempted:
            if sys.platform == "darwin":
                try:
                    _cleanup_darwin_named_stage(stage_lease)
                except BaseException as private_cleanup_error:
                    error.add_note(
                        "Could not remove and flush the private macOS receipt stage after a publication failure: "
                        f"{private_cleanup_error}"
                    )
            recovered_identity: tuple[int, int] | None = None
            try:
                recovered_identity = _read_exact_receipt(
                    binding,
                    binding.leaf,
                    payload,
                    descriptor_lease=publication_lease.new_transient_descriptor(),
                )
            except BaseException as observation_error:
                error.add_note(
                    "Descriptor-bound receipt publication outcome could not be bound to one exact public inode: "
                    f"{observation_error}."
                )
            else:
                error.add_note(
                    "Descriptor-bound receipt publication exposed an exact public receipt before the failure; "
                    "the valid public inode was left untouched."
                )
            recovery_steps: list[tuple[str, Callable[[], object]]] = [
                ("revalidate the receipt parent", lambda: binding.verify()),
            ]
            if recovered_identity is not None:
                recovery_steps.append(
                    (
                        "flush the exact public receipt",
                        lambda: _sync_posix_public_descriptor(
                            binding,
                            payload,
                            recovered_identity,
                            publication_lease.new_transient_descriptor(),
                        ),
                    )
                )
            recovery_steps.append(("flush the receipt parent", lambda: binding.sync()))
            if recovered_identity is not None:
                recovery_steps.append(
                    (
                        "perform final receipt verification",
                        lambda: _read_exact_receipt(
                            binding,
                            binding.leaf,
                            payload,
                            descriptor_lease=publication_lease.new_transient_descriptor(),
                            expected_identity=recovered_identity,
                        ),
                    )
                )
            for description, recovery_step in recovery_steps:
                try:
                    recovery_step()
                except BaseException as recovery_error:
                    error.add_note(
                        f"Could not {description} while recovering an attempted receipt publication: {recovery_error}"
                    )
        raise
    finally:
        close_failures: list[BaseException] = []
        publication_closed = False
        for _attempt in range(2):
            try:
                close_failures.extend(publication_lease.close())
            except BaseException as publication_close_error:
                close_failures.append(publication_close_error)
            try:
                publication_closed = publication_lease.is_closed
            except BaseException as status_error:
                close_failures.append(status_error)
                publication_closed = False
            if publication_closed:
                break
        if not publication_closed:
            if not close_failures:
                close_failures.append(
                    AnchoredOutputError(
                        "output-cleanup-retained",
                        "A POSIX receipt publication resource remained open after bounded cleanup attempts.",
                    )
                )
        else:
            try:
                binding_close_failures = binding.close()
            except BaseException as binding_close_error:
                # The binding owns its resources until its close implementation
                # confirms otherwise. Treat an interruption at the call/return
                # boundary as another cleanup failure so it cannot replace an
                # already-active publication error.
                close_failures.append(binding_close_error)
            else:
                close_failures.extend(binding_close_failures)
        if close_failures:
            if primary_error is not None:
                for close_error in close_failures:
                    primary_error.add_note(f"Could not close a receipt publication resource: {close_error}")
            else:
                control_flow_failure = next(
                    (failure for failure in close_failures if not isinstance(failure, Exception)),
                    None,
                )
                if control_flow_failure is not None:
                    for failure in close_failures:
                        if failure is not control_flow_failure:
                            control_flow_failure.add_note(f"Receipt publication close failure: {failure}")
                    raise control_flow_failure
                first_close_error = close_failures[0]
                for later_error in close_failures[1:]:
                    first_close_error.add_note(f"Receipt publication close failure: {later_error}")
                raise first_close_error


__all__ = ["_publish_posix_receipt_bytes"]
