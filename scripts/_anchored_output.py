"""Anchored, no-overwrite byte publication for isolated repository scripts.

This private module is deliberately stdlib-only. Callers retain responsibility
for serialization, size limits, and translating stable publication error codes
into their own CLI error taxonomy.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Callable, Literal, cast


class AnchoredOutputError(ValueError):
    """An anchored output path or publication violated the output contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_WINDOWS_FILE_READ_ATTRIBUTES = 0x00000080
_WINDOWS_FILE_TRAVERSE = 0x00000020
_WINDOWS_FILE_SHARE_READ = 0x00000001
_WINDOWS_FILE_SHARE_WRITE = 0x00000002
_WINDOWS_OPEN_EXISTING = 3
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WINDOWS_FILE_TYPE_DISK = 1
_WINDOWS_FILE_BASIC_INFO_CLASS = 0
_WINDOWS_FILE_ID_INFO_CLASS = 18


class _WindowsFileId128(ctypes.Structure):
    _fields_ = (("Identifier", ctypes.c_uint8 * 16),)


class _WindowsFileIdInfo(ctypes.Structure):
    _fields_ = (
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", _WindowsFileId128),
    )


class _WindowsFileBasicInfo(ctypes.Structure):
    _fields_ = (
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
    )


def descriptor_relative_output_supported() -> bool:
    return (
        os.name != "nt"
        and bool(getattr(os, "O_DIRECTORY", 0))
        and bool(getattr(os, "O_NOFOLLOW", 0))
        and os.stat in os.supports_follow_symlinks
        and all(
            operation in os.supports_dir_fd
            for operation in (os.open, os.stat, os.link, os.unlink)
        )
    )


def _path_is_redirected(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(os.fspath(path))


def _windows_extended_path(path: Path) -> str:
    absolute_path = os.path.abspath(path)
    if absolute_path.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def _windows_file_api() -> Any:
    if os.name != "nt":
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "Win32 output-directory handles are unavailable on this platform.",
        )
    win_dll = cast(Callable[..., Any], getattr(ctypes, "WinDLL"))
    kernel32 = win_dll("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.GetFileInformationByHandleEx.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    kernel32.GetFileInformationByHandleEx.restype = ctypes.c_int
    kernel32.GetFileType.argtypes = (ctypes.c_void_p,)
    kernel32.GetFileType.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


def _windows_handle_identity(kernel32: Any, handle: int) -> tuple[int, int]:
    identity_info = _WindowsFileIdInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_ID_INFO_CLASS,
        ctypes.byref(identity_info),
        ctypes.sizeof(identity_info),
    ):
        raise OSError("Could not identify the snapshot output directory handle.")
    return (
        int(identity_info.VolumeSerialNumber),
        int.from_bytes(bytes(identity_info.FileId.Identifier), "little"),
    )


def _windows_directory_attributes(kernel32: Any, handle: int) -> int:
    basic_info = _WindowsFileBasicInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_BASIC_INFO_CLASS,
        ctypes.byref(basic_info),
        ctypes.sizeof(basic_info),
    ):
        raise OSError("Could not inspect the snapshot output directory handle.")
    return int(basic_info.FileAttributes)


def _open_windows_directory_handle(
    kernel32: Any,
    path: Path,
    expected_identity: tuple[int, int],
) -> int:
    handle = kernel32.CreateFileW(
        _windows_extended_path(path),
        _WINDOWS_FILE_TRAVERSE | _WINDOWS_FILE_READ_ATTRIBUTES,
        _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE,
        None,
        _WINDOWS_OPEN_EXISTING,
        _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS | _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise OSError(f"Could not bind snapshot output directory: {path}.")
    handle_value = cast(int, handle)
    try:
        path_stat = path.lstat()
        attributes = _windows_directory_attributes(kernel32, handle_value)
        if (
            kernel32.GetFileType(handle_value) != _WINDOWS_FILE_TYPE_DISK
            or _path_is_redirected(path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != expected_identity
            or _windows_handle_identity(kernel32, handle_value) != expected_identity
            or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
            or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise OSError(f"Snapshot output directory changed: {path}.")
    except BaseException as error:
        try:
            if not kernel32.CloseHandle(handle_value):
                error.add_note(
                    "Could not close the rejected snapshot output directory handle."
                )
        except BaseException as cleanup_error:
            error.add_note(
                "Could not close the rejected snapshot output directory handle: "
                f"{cleanup_error}"
            )
        raise
    return handle_value


@dataclass
class OutputParentBinding:
    checkout: Path
    parent: Path
    leaf: str
    strategy: Literal["posix-dir-fd", "windows-handle"]
    descriptors: tuple[int, ...] = ()
    links: tuple[tuple[int, str, int], ...] = ()
    windows_api: Any | None = None
    windows_entries: tuple[tuple[Path, tuple[int, int], int], ...] = ()

    def close(self) -> tuple[BaseException, ...]:
        failures: list[BaseException] = []
        for descriptor in reversed(self.descriptors):
            try:
                os.close(descriptor)
            except BaseException as error:
                failures.append(error)
        if self.windows_api is not None:
            for _path, _identity, handle in reversed(self.windows_entries):
                try:
                    if not self.windows_api.CloseHandle(handle):
                        failures.append(
                            OSError(
                                "Could not close a snapshot output directory handle."
                            )
                        )
                except BaseException as error:
                    failures.append(error)
        return tuple(failures)

    def verify(self) -> None:
        if self.strategy == "posix-dir-fd":
            root_stat = self.checkout.lstat()
            opened_root = os.fstat(self.descriptors[0])
            if (
                _path_is_redirected(self.checkout, root_stat)
                or not stat.S_ISDIR(root_stat.st_mode)
                or (root_stat.st_dev, root_stat.st_ino)
                != (opened_root.st_dev, opened_root.st_ino)
            ):
                raise AnchoredOutputError(
                    "output-parent-changed",
                    f"Snapshot output checkout changed while bound: {self.checkout}.",
                )
            for parent_descriptor, component, child_descriptor in self.links:
                entry = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                opened = os.fstat(child_descriptor)
                if (
                    stat.S_ISLNK(entry.st_mode)
                    or not stat.S_ISDIR(entry.st_mode)
                    or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
                ):
                    raise AnchoredOutputError(
                        "output-parent-changed",
                        f"Snapshot output ancestor changed while bound: {self.parent}.",
                    )
            return

        assert self.windows_api is not None
        for path, identity, handle in self.windows_entries:
            path_stat = path.lstat()
            attributes = _windows_directory_attributes(self.windows_api, handle)
            if (
                _path_is_redirected(path, path_stat)
                or not stat.S_ISDIR(path_stat.st_mode)
                or (path_stat.st_dev, path_stat.st_ino) != identity
                or _windows_handle_identity(self.windows_api, handle) != identity
                or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise AnchoredOutputError(
                    "output-parent-changed",
                    f"Snapshot output ancestor changed while bound: {path}.",
                )

    def stat(self, name: str) -> os.stat_result:
        if self.strategy == "posix-dir-fd":
            return os.stat(
                name,
                dir_fd=self.descriptors[-1],
                follow_symlinks=False,
            )
        self.verify()
        result = (self.parent / name).lstat()
        self.verify()
        return result

    def open_new(self, name: str) -> int:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if self.strategy == "posix-dir-fd":
            return os.open(name, flags, 0o600, dir_fd=self.descriptors[-1])
        self.verify()
        return os.open(self.parent / name, flags, 0o600)

    def link(self, source: str, destination: str) -> None:
        if self.strategy == "posix-dir-fd":
            os.link(
                source,
                destination,
                src_dir_fd=self.descriptors[-1],
                dst_dir_fd=self.descriptors[-1],
                follow_symlinks=False,
            )
            return
        self.verify()
        os.link(
            self.parent / source,
            self.parent / destination,
            follow_symlinks=False,
        )

    def unlink(self, name: str) -> None:
        if self.strategy == "posix-dir-fd":
            os.unlink(name, dir_fd=self.descriptors[-1])
            return
        self.verify()
        os.unlink(self.parent / name)
        self.verify()

    def sync(self) -> None:
        if self.strategy != "posix-dir-fd":
            # The hard-link operation still publishes one name atomically on
            # Windows, but Python exposes no portable directory-entry flush
            # for the retained Win32 directory handles used here.
            return
        os.fsync(self.descriptors[-1])


def _checkout_output_parts(path: Path) -> tuple[Path, Path, tuple[str, ...]]:
    leaf = path.name
    if leaf in {"", ".", ".."}:
        raise AnchoredOutputError(
            "path-outside-checkout",
            f"Snapshot output must name a file below the physical checkout: {path}.",
        )
    try:
        checkout = Path.cwd().resolve(strict=True)
        # Normalize dot components without following any caller-controlled
        # output ancestor. Absolute spellings may still use an OS-level alias
        # for the physical cwd (for example macOS /var -> /private/var), so map
        # the outermost lexical ancestor that identifies the checkout and keep
        # every component below it for no-follow traversal from the anchor.
        lexical_parent = Path(os.path.abspath(os.path.normpath(os.fspath(path.parent))))
        try:
            relative_parent_parts = lexical_parent.relative_to(checkout).parts
        except ValueError:
            reversed_suffix: list[str] = []
            current = lexical_parent
            matched_parts: tuple[str, ...] | None = None
            while True:
                try:
                    matches_checkout = current.samefile(checkout)
                except OSError:
                    matches_checkout = False
                if matches_checkout:
                    # Continue toward the filesystem root so a symlink below
                    # the checkout that points back to it cannot become the
                    # trusted prefix.
                    matched_parts = tuple(reversed(reversed_suffix))
                parent = current.parent
                if parent == current:
                    break
                reversed_suffix.append(current.name)
                current = parent
            if matched_parts is None:
                raise ValueError("Output parent is not lexically below the checkout.")
            relative_parent_parts = matched_parts
    except (OSError, ValueError) as error:
        raise AnchoredOutputError(
            "path-outside-checkout",
            f"Snapshot output must resolve below the physical checkout: {path}.",
        ) from error
    absolute = checkout.joinpath(*relative_parent_parts, leaf)
    return checkout, absolute, (*relative_parent_parts, leaf)


def open_output_parent(path: Path) -> OutputParentBinding:
    checkout, absolute, parts = _checkout_output_parts(path)
    parent = absolute.parent
    leaf = parts[-1]
    if descriptor_relative_output_supported():
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors: list[int] = []
        links: list[tuple[int, str, int]] = []
        try:
            root_descriptor = os.open(".", flags)
            descriptors.append(root_descriptor)
            root_path_stat = checkout.lstat()
            opened_root = os.fstat(root_descriptor)
            if (
                _path_is_redirected(checkout, root_path_stat)
                or not stat.S_ISDIR(opened_root.st_mode)
                or (root_path_stat.st_dev, root_path_stat.st_ino)
                != (opened_root.st_dev, opened_root.st_ino)
            ):
                raise OSError("The physical checkout changed while it was opened.")
            for component in parts[:-1]:
                parent_descriptor = descriptors[-1]
                entry = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
                    raise OSError(f"Redirected output ancestor: {component}.")
                child_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=parent_descriptor,
                )
                descriptors.append(child_descriptor)
                opened = os.fstat(child_descriptor)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
                ):
                    raise OSError(f"Output ancestor changed: {component}.")
                links.append((parent_descriptor, component, child_descriptor))
            binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="posix-dir-fd",
                descriptors=tuple(descriptors),
                links=tuple(links),
            )
            binding.verify()
            return binding
        except BaseException as error:
            cleanup_binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="posix-dir-fd",
                descriptors=tuple(descriptors),
            )
            for cleanup_error in cleanup_binding.close():
                error.add_note(
                    f"Could not close a snapshot output directory descriptor: "
                    f"{cleanup_error}"
                )
            if isinstance(error, AnchoredOutputError) or not isinstance(error, Exception):
                raise
            raise AnchoredOutputError(
                "output-parent-invalid",
                f"Cannot bind snapshot output parent inside the checkout: {parent}.",
            ) from error

    if os.name == "nt":
        kernel32 = _windows_file_api()
        entries: list[tuple[Path, tuple[int, int], int]] = []
        try:
            current = checkout
            for component in (None, *parts[:-1]):
                if component is not None:
                    current /= component
                path_stat = current.lstat()
                if _path_is_redirected(current, path_stat) or not stat.S_ISDIR(
                    path_stat.st_mode
                ):
                    raise OSError(f"Redirected output ancestor: {current}.")
                identity = (path_stat.st_dev, path_stat.st_ino)
                handle = _open_windows_directory_handle(kernel32, current, identity)
                entries.append((current, identity, handle))
            binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="windows-handle",
                windows_api=kernel32,
                windows_entries=tuple(entries),
            )
            binding.verify()
            return binding
        except BaseException as error:
            cleanup_binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="windows-handle",
                windows_api=kernel32,
                windows_entries=tuple(entries),
            )
            for cleanup_error in cleanup_binding.close():
                error.add_note(
                    f"Could not close a snapshot output directory handle: "
                    f"{cleanup_error}"
                )
            if isinstance(error, AnchoredOutputError) or not isinstance(error, Exception):
                raise
            raise AnchoredOutputError(
                "output-parent-invalid",
                f"Cannot bind snapshot output parent inside the checkout: {parent}.",
            ) from error

    raise AnchoredOutputError(
        "output-anchor-unavailable",
        "This platform cannot bind snapshot output operations to the physical checkout.",
    )


def _same_identity(path_stat: os.stat_result, identity: tuple[int, int]) -> bool:
    return (path_stat.st_dev, path_stat.st_ino) == identity


def _unlink_output_if_identity(
    binding: OutputParentBinding,
    name: str,
    identity: tuple[int, int],
) -> None:
    try:
        current = binding.stat(name)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(current.st_mode) or not _same_identity(current, identity):
        raise AnchoredOutputError(
            "output-cleanup-changed",
            f"Refusing to remove a changed snapshot output artifact: {binding.parent / name}.",
        )
    binding.unlink(name)


def publish_new_bytes(path: Path, payload: bytes) -> None:
    """Publish bytes below the physical cwd without replacing an existing name."""

    binding = open_output_parent(path)
    temporary_name = ""
    temporary_identity: tuple[int, int] | None = None
    output_identity: tuple[int, int] | None = None
    published = False
    descriptor = -1
    primary_error: BaseException | None = None
    try:
        try:
            binding.stat(binding.leaf)
        except FileNotFoundError:
            pass
        else:
            raise AnchoredOutputError("output-exists", f"Refusing to overwrite existing snapshot output: {path}.")

        for _attempt in range(100):
            temporary_name = f".{binding.leaf}.{secrets.token_hex(8)}.tmp"
            try:
                descriptor = binding.open_new(temporary_name)
            except FileExistsError:
                continue
            binding.verify()
            break
        if descriptor < 0:
            raise AnchoredOutputError(
                "output-temporary-unavailable",
                f"Could not create a private temporary snapshot beside {path}.",
            )
        opened = os.fstat(descriptor)
        temporary_identity = (opened.st_dev, opened.st_ino)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise AnchoredOutputError(
                "output-temporary-invalid",
                f"Snapshot temporary file is not one private regular file: {path}.",
            )
        file_handle = os.fdopen(descriptor, "wb")
        descriptor = -1
        with file_handle as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        binding.verify()
        try:
            binding.link(temporary_name, binding.leaf)
        except FileExistsError as error:
            raise AnchoredOutputError("output-exists", f"Refusing to overwrite existing snapshot output: {path}.") from error
        published = True
        output_identity = temporary_identity
        output_stat = binding.stat(binding.leaf)
        if (
            not stat.S_ISREG(output_stat.st_mode)
            or not _same_identity(output_stat, temporary_identity)
        ):
            raise AnchoredOutputError(
                "output-changed",
                f"Snapshot output changed while it was published: {path}.",
            )
        binding.verify()
        binding.sync()
        _unlink_output_if_identity(binding, temporary_name, temporary_identity)
        temporary_identity = None
        binding.sync()
        binding.verify()
        output_stat = binding.stat(binding.leaf)
        if (
            not stat.S_ISREG(output_stat.st_mode)
            or output_stat.st_nlink != 1
            or not _same_identity(output_stat, output_identity)
        ):
            raise AnchoredOutputError(
                "output-changed",
                f"Snapshot output changed before publication completed: {path}.",
            )
    except BaseException as error:
        primary_error = error
        if descriptor >= 0:
            if temporary_identity is None:
                try:
                    opened_for_cleanup = os.fstat(descriptor)
                    if stat.S_ISREG(opened_for_cleanup.st_mode):
                        temporary_identity = (
                            opened_for_cleanup.st_dev,
                            opened_for_cleanup.st_ino,
                        )
                    else:
                        error.add_note(
                            "Could not bind the snapshot temporary file for cleanup: "
                            "the opened descriptor is not a regular file."
                        )
                except BaseException as cleanup_error:
                    # Do not unlink by name without proving that the entry is
                    # still the file represented by this descriptor. A writer
                    # with directory access could have replaced it. At this
                    # point publication has not begun, so the fail-closed cost
                    # is at most one unpredictable, newly created empty temp.
                    error.add_note(
                        f"Could not identify the snapshot temporary file for cleanup: "
                        f"{cleanup_error}. The unverified temporary name was "
                        "intentionally left in place rather than risk deleting "
                        "a replaced entry."
                    )
            try:
                os.close(descriptor)
            except BaseException as cleanup_error:
                error.add_note(
                    f"Could not close the snapshot temporary descriptor: "
                    f"{cleanup_error}"
                )
            descriptor = -1
        if published and output_identity is not None:
            try:
                _unlink_output_if_identity(binding, binding.leaf, output_identity)
            except BaseException as cleanup_error:
                error.add_note(f"Could not remove rejected snapshot output: {cleanup_error}")
        if temporary_identity is not None:
            try:
                _unlink_output_if_identity(binding, temporary_name, temporary_identity)
            except BaseException as cleanup_error:
                error.add_note(f"Could not remove snapshot temporary file: {cleanup_error}")
        raise
    finally:
        close_failures = binding.close()
        if close_failures:
            if primary_error is not None:
                for close_error in close_failures:
                    primary_error.add_note(
                        f"Could not close a snapshot output anchor: {close_error}"
                    )
            else:
                control_flow_failure = next(
                    (
                        failure
                        for failure in close_failures
                        if not isinstance(failure, Exception)
                    ),
                    None,
                )
                if control_flow_failure is not None:
                    for failure in close_failures:
                        if failure is not control_flow_failure:
                            control_flow_failure.add_note(
                                f"Output anchor close failure: {failure}"
                            )
                    raise control_flow_failure
                close_error = AnchoredOutputError(
                    "output-anchor-close-failed",
                    "Snapshot publication completed, but one or more output "
                    "directory anchors could not be closed.",
                )
                for failure in close_failures:
                    close_error.add_note(f"Output anchor close failure: {failure}")
                raise close_error from close_failures[0]


__all__ = [
    "AnchoredOutputError",
    "OutputParentBinding",
    "descriptor_relative_output_supported",
    "open_output_parent",
    "publish_new_bytes",
]
