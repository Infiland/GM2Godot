from __future__ import annotations

import ctypes
import hashlib
import os
import secrets
import stat
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Literal, TypeAlias, cast


FileFingerprint: TypeAlias = tuple[int, int, int, int, int]
ReceiptFingerprint: TypeAlias = tuple[int, int, int, int]
PathIdentity: TypeAlias = tuple[int, int]
DirectoryStrategy: TypeAlias = Literal["posix_dir_fd", "windows_handle", "verified_path"]


def _path_is_redirected(path: str, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def _file_fingerprint(path_stat: os.stat_result) -> FileFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def _stable_fingerprint(fingerprint: FileFingerprint) -> ReceiptFingerprint:
    # Renaming the same inode aside and back can update ctime. Receipts retain
    # exact identity, size, mtime, mode, bytes, and digest instead.
    return fingerprint[:4]


def _sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _is_windows_platform() -> bool:
    return os.name == "nt"


def modes_match(actual: int, expected: int) -> bool:
    if _is_windows_platform():
        return bool(actual & stat.S_IWUSR) == bool(expected & stat.S_IWUSR)
    return actual == expected


def fingerprints_match(actual: FileFingerprint, expected: FileFingerprint) -> bool:
    if _is_windows_platform():
        # Windows path and handle stat APIs can expose different ctime values
        # for the same file. Size, mtime, identity, bytes, and SHA remain exact.
        return actual[:4] == expected[:4]
    return actual == expected


def _replaceable_mode(mode: int) -> int:
    if not _is_windows_platform():
        return mode
    return mode | stat.S_IWUSR


def _descriptor_relative_supported() -> bool:
    return (
        os.name != "nt"
        and bool(getattr(os, "O_DIRECTORY", 0))
        and bool(getattr(os, "O_NOFOLLOW", 0))
        and os.chmod in os.supports_fd
        and all(
            operation in os.supports_dir_fd
            for operation in (os.open, os.mkdir, os.stat, os.rename, os.unlink)
        )
    )


def _safe_leaf(name: str) -> str:
    windows_stem = name.rstrip(" .").split(".", 1)[0].upper()
    windows_reserved = (
        windows_stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        or (
            len(windows_stem) == 4
            and windows_stem[:3] in {"COM", "LPT"}
            and windows_stem[3] in "123456789"
        )
    )
    if (
        name in {"", ".", ".."}
        or "\x00" in name
        or os.path.basename(name) != name
        or any(separator in name for separator in ("/", "\\"))
        or (
            os.name == "nt"
            and (
                ":" in name
                or name.endswith((" ", "."))
                or any(ord(character) < 32 for character in name)
                or windows_reserved
            )
        )
    ):
        raise ValueError(f"Unsafe artifact transaction name: {name!r}")
    return name


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
_WINDOWS_MOVEFILE_REPLACE_EXISTING = 0x00000001
_WINDOWS_MOVEFILE_WRITE_THROUGH = 0x00000008


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


@lru_cache(maxsize=1)
def _windows_file_api() -> Any:
    if os.name != "nt":
        raise OSError("Windows artifact transaction APIs are unavailable")
    if (
        ctypes.sizeof(_WindowsFileId128) != 16
        or ctypes.sizeof(_WindowsFileIdInfo) != 24
        or _WindowsFileIdInfo.FileId.offset != 8
        or ctypes.sizeof(_WindowsFileBasicInfo) != 40
        or _WindowsFileBasicInfo.FileAttributes.offset != 32
    ):
        raise OSError("Unsupported Windows artifact transaction ABI layout")
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
    kernel32.MoveFileExW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    )
    kernel32.MoveFileExW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


def _windows_api_error(operation: str, path: str) -> OSError:
    get_last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    error_number = get_last_error()
    format_error = cast(Callable[[int], str], getattr(ctypes, "FormatError"))
    return OSError(
        error_number,
        f"{operation}: {format_error(error_number).strip()}",
        path,
    )


def _windows_extended_path(path: str) -> str:
    """Return an absolute Win32 path independent of MAX_PATH policy."""
    absolute_path = os.path.abspath(path)
    if absolute_path.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def _windows_handle_identity(kernel32: Any, handle: int, path: str) -> PathIdentity:
    identity_info = _WindowsFileIdInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_ID_INFO_CLASS,
        ctypes.byref(identity_info),
        ctypes.sizeof(identity_info),
    ):
        raise _windows_api_error("Could not identify artifact directory handle", path)
    return (
        int(identity_info.VolumeSerialNumber),
        int.from_bytes(bytes(identity_info.FileId.Identifier), "little"),
    )


def _windows_directory_attributes(kernel32: Any, handle: int, path: str) -> int:
    basic_info = _WindowsFileBasicInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_BASIC_INFO_CLASS,
        ctypes.byref(basic_info),
        ctypes.sizeof(basic_info),
    ):
        raise _windows_api_error("Could not inspect artifact directory handle", path)
    return int(basic_info.FileAttributes)


def _open_windows_directory_handle(
    path: str,
    expected_identity: PathIdentity,
) -> tuple[Any, int]:
    kernel32 = _windows_file_api()
    handle = kernel32.CreateFileW(
        _windows_extended_path(path),
        _WINDOWS_FILE_TRAVERSE | _WINDOWS_FILE_READ_ATTRIBUTES,
        _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE,
        None,
        _WINDOWS_OPEN_EXISTING,
        _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
        | _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise _windows_api_error("Could not bind artifact transaction directory", path)
    handle_value = cast(int, handle)
    try:
        path_stat = os.lstat(path)
        attributes = _windows_directory_attributes(kernel32, handle_value, path)
        if (
            kernel32.GetFileType(handle_value) != _WINDOWS_FILE_TYPE_DISK
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != expected_identity
            or _windows_handle_identity(kernel32, handle_value, path)
            != expected_identity
            or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
            or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise OSError(f"Artifact transaction directory changed: {path}")
    except BaseException as error:
        if not kernel32.CloseHandle(handle_value):
            error.add_note(
                f"Could not close rejected artifact directory handle: {path}"
            )
        raise
    return kernel32, handle_value


def _before_anchored_artifact_phase(
    _phase: str,
    _directory_path: str,
    _name: str | None,
) -> None:
    """Narrow adversarial-test seam around namespace and durability phases."""


@dataclass
class VerifiedDirectory(AbstractContextManager["VerifiedDirectory"]):
    """A directory whose namespace remains bound for a complete transaction.

    POSIX operations are descriptor-relative. Windows retains a directory
    handle opened without delete sharing, so path-based child operations cannot
    be redirected by moving the directory. Other platforms use an explicitly
    weaker verified-path strategy chosen before any staging begins.
    """

    path: str
    identity: PathIdentity
    description: str
    strategy: DirectoryStrategy
    descriptor: int = -1
    windows_api: Any | None = None
    windows_handle: int | None = None
    closed: bool = False

    @classmethod
    def open(cls, path: str, *, description: str) -> "VerifiedDirectory":
        absolute_path = os.path.abspath(path)
        try:
            path_stat = os.lstat(absolute_path)
        except OSError as error:
            raise OSError(f"{description.capitalize()} is unavailable: {path}") from error
        if _path_is_redirected(absolute_path, path_stat) or not stat.S_ISDIR(
            path_stat.st_mode
        ):
            raise OSError(f"Refusing redirected or non-directory {description}: {path}")
        identity = (path_stat.st_dev, path_stat.st_ino)
        if _descriptor_relative_supported():
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(absolute_path, flags)
            try:
                opened_stat = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(opened_stat.st_mode)
                    or (opened_stat.st_dev, opened_stat.st_ino) != identity
                ):
                    raise OSError(f"{description.capitalize()} changed: {path}")
            except BaseException as error:
                try:
                    os.close(descriptor)
                except BaseException as close_error:
                    error.add_note(
                        f"Could not close rejected {description} descriptor: "
                        f"{close_error}"
                    )
                raise
            binding = cls(
                path=absolute_path,
                identity=identity,
                description=description,
                strategy="posix_dir_fd",
                descriptor=descriptor,
            )
        elif os.name == "nt":
            kernel32, handle = _open_windows_directory_handle(
                absolute_path,
                identity,
            )
            binding = cls(
                path=absolute_path,
                identity=identity,
                description=description,
                strategy="windows_handle",
                windows_api=kernel32,
                windows_handle=handle,
            )
        else:
            binding = cls(
                path=absolute_path,
                identity=identity,
                description=description,
                strategy="verified_path",
            )
        try:
            binding.verify_path()
        except BaseException as error:
            try:
                binding.close()
            except BaseException as close_error:
                error.add_note(
                    f"Could not close rejected {description} binding: {close_error}"
                )
            raise
        return binding

    @classmethod
    def open_or_create(
        cls,
        path: str,
        *,
        description: str,
    ) -> "VerifiedDirectory":
        """Create a missing directory chain through verified parent bindings.

        Every component is opened without following its final entry, and every
        parent crosses its durability barrier before the implementation
        descends into the child. Repeating the barrier for an existing final
        component makes a retry complete a prior creation whose parent sync
        failed after the directory became visible.
        """
        absolute_path = os.path.abspath(path)
        components: list[str] = []
        existing_parent = absolute_path
        while True:
            parent_path, component = os.path.split(existing_parent)
            if not component:
                return cls.open(absolute_path, description=description)
            components.append(_safe_leaf(component))
            try:
                parent_stat = os.lstat(parent_path)
            except FileNotFoundError:
                existing_parent = parent_path
                continue
            if _path_is_redirected(parent_path, parent_stat) or not stat.S_ISDIR(
                parent_stat.st_mode
            ):
                raise OSError(
                    f"Refusing redirected or non-directory {description} parent: "
                    f"{parent_path}"
                )
            existing_parent = parent_path
            break

        binding = cls.open(
            existing_parent,
            description=f"{description} parent",
        )
        try:
            ordered_components = tuple(reversed(components))
            for index, component in enumerate(ordered_components):
                child_path = binding.child_path(component)
                try:
                    child_stat = binding.stat(component)
                except FileNotFoundError:
                    try:
                        binding.mkdir(component)
                    except FileExistsError:
                        pass
                    child_stat = binding.stat(component)
                if _path_is_redirected(child_path, child_stat) or not stat.S_ISDIR(
                    child_stat.st_mode
                ):
                    raise OSError(
                        f"Refusing redirected or non-directory {description}: "
                        f"{child_path}"
                    )
                child_identity = (child_stat.st_dev, child_stat.st_ino)
                child_description = (
                    description
                    if index == len(ordered_components) - 1
                    else f"{description} parent"
                )
                child = binding.open_child(
                    component,
                    expected_identity=child_identity,
                    description=child_description,
                )
                try:
                    binding.sync()
                    child.verify_path()
                    binding.verify_path()
                except BaseException as error:
                    try:
                        child.close()
                    except BaseException as close_error:
                        error.add_note(
                            f"Could not close rejected {child_description} binding: "
                            f"{close_error}"
                        )
                    raise
                try:
                    binding.close()
                except BaseException as error:
                    try:
                        child.close()
                    except BaseException as close_error:
                        error.add_note(
                            f"Could not close {child_description} binding: {close_error}"
                        )
                    raise
                binding = child
            return binding
        except BaseException as error:
            try:
                binding.close()
            except BaseException as close_error:
                error.add_note(
                    f"Could not close {description} creation binding: {close_error}"
                )
            raise

    def __exit__(
        self,
        _exc_type: object,
        active_error: BaseException | None,
        _traceback: object,
    ) -> bool | None:
        try:
            self.close()
        except BaseException as close_error:
            if active_error is None:
                raise
            active_error.add_note(
                f"Could not close {self.description} binding: {close_error}"
            )
        return None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.descriptor >= 0:
            descriptor = self.descriptor
            self.descriptor = -1
            os.close(descriptor)
        if self.windows_handle is not None:
            handle = self.windows_handle
            self.windows_handle = None
            assert self.windows_api is not None
            if not self.windows_api.CloseHandle(handle):
                raise _windows_api_error(
                    "Could not close artifact transaction directory",
                    self.path,
                )

    def verify_path(self) -> None:
        if self.closed:
            raise OSError(f"{self.description.capitalize()} binding is closed")
        try:
            path_stat = os.lstat(self.path)
        except OSError as error:
            raise OSError(f"{self.description.capitalize()} changed: {self.path}") from error
        if (
            _path_is_redirected(self.path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != self.identity
        ):
            raise OSError(f"{self.description.capitalize()} changed: {self.path}")
        if self.strategy == "posix_dir_fd":
            opened_stat = os.fstat(self.descriptor)
            if (
                not stat.S_ISDIR(opened_stat.st_mode)
                or (opened_stat.st_dev, opened_stat.st_ino) != self.identity
            ):
                raise OSError(f"{self.description.capitalize()} changed: {self.path}")
        elif self.strategy == "windows_handle":
            assert self.windows_api is not None
            assert self.windows_handle is not None
            attributes = _windows_directory_attributes(
                self.windows_api,
                self.windows_handle,
                self.path,
            )
            if (
                _windows_handle_identity(
                    self.windows_api,
                    self.windows_handle,
                    self.path,
                )
                != self.identity
                or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise OSError(f"{self.description.capitalize()} changed: {self.path}")

    def child_path(self, name: str) -> str:
        return os.path.join(self.path, _safe_leaf(name))

    def open_child(
        self,
        name: str,
        *,
        expected_identity: PathIdentity,
        description: str,
    ) -> "VerifiedDirectory":
        leaf = _safe_leaf(name)
        child_path = self.child_path(leaf)
        try:
            child_stat = self.stat(leaf)
        except OSError as error:
            raise OSError(f"{description.capitalize()} is unavailable: {child_path}") from error
        if _path_is_redirected(child_path, child_stat) or not stat.S_ISDIR(
            child_stat.st_mode
        ):
            raise OSError(
                f"Refusing redirected or non-directory {description}: {child_path}"
            )
        identity = (child_stat.st_dev, child_stat.st_ino)
        if identity != expected_identity:
            raise OSError(f"{description.capitalize()} changed: {child_path}")
        if self.strategy == "posix_dir_fd":
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(leaf, flags, dir_fd=self.descriptor)
            try:
                opened_stat = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(opened_stat.st_mode)
                    or (opened_stat.st_dev, opened_stat.st_ino) != expected_identity
                ):
                    raise OSError(f"{description.capitalize()} changed: {child_path}")
            except BaseException as error:
                try:
                    os.close(descriptor)
                except BaseException as close_error:
                    error.add_note(
                        f"Could not close rejected {description} descriptor: "
                        f"{close_error}"
                    )
                raise
            binding = VerifiedDirectory(
                path=child_path,
                identity=expected_identity,
                description=description,
                strategy="posix_dir_fd",
                descriptor=descriptor,
            )
            try:
                self.verify_path()
                binding.verify_path()
            except BaseException as error:
                try:
                    binding.close()
                except BaseException as close_error:
                    error.add_note(
                        f"Could not close rejected {description} binding: {close_error}"
                    )
                raise
            return binding
        if self.strategy == "windows_handle":
            # The retained root handle prevents parent relocation while this
            # second handle binds the exact child captured by the caller.
            self.verify_path()
            kernel32, handle = _open_windows_directory_handle(
                child_path,
                expected_identity,
            )
            binding = VerifiedDirectory(
                path=child_path,
                identity=expected_identity,
                description=description,
                strategy="windows_handle",
                windows_api=kernel32,
                windows_handle=handle,
            )
            try:
                self.verify_path()
                binding.verify_path()
            except BaseException as error:
                try:
                    binding.close()
                except BaseException as close_error:
                    error.add_note(
                        f"Could not close rejected {description} binding: {close_error}"
                    )
                raise
            return binding
        # The verified fallback repeats the full path guards and rejects a
        # freshly captured replacement before returning it to the transaction.
        self.verify_path()
        binding = VerifiedDirectory.open(child_path, description=description)
        try:
            if binding.identity != expected_identity:
                raise OSError(f"{description.capitalize()} changed: {child_path}")
            self.verify_path()
        except BaseException as error:
            try:
                binding.close()
            except BaseException as close_error:
                error.add_note(
                    f"Could not close rejected {description} binding: {close_error}"
                )
            raise
        return binding

    def stat(self, name: str) -> os.stat_result:
        leaf = _safe_leaf(name)
        if self.strategy == "posix_dir_fd":
            return os.stat(leaf, dir_fd=self.descriptor, follow_symlinks=False)
        self.verify_path()
        result = os.lstat(self.child_path(leaf))
        self.verify_path()
        return result

    def lexists(self, name: str) -> bool:
        try:
            self.stat(name)
        except FileNotFoundError:
            return False
        return True

    def list_names(self) -> tuple[str, ...]:
        if self.strategy == "posix_dir_fd":
            return tuple(sorted(os.listdir(self.descriptor)))
        self.verify_path()
        names = tuple(sorted(os.listdir(self.path)))
        self.verify_path()
        return names

    def open_file(self, name: str, flags: int, mode: int = 0o600) -> int:
        leaf = _safe_leaf(name)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        if self.strategy == "posix_dir_fd":
            return os.open(leaf, flags, mode, dir_fd=self.descriptor)
        self.verify_path()
        descriptor = os.open(self.child_path(leaf), flags, mode)
        try:
            self.verify_path()
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def mkdir(self, name: str, mode: int = 0o755) -> None:
        leaf = _safe_leaf(name)
        _before_anchored_artifact_phase("before_mkdir", self.path, leaf)
        if self.strategy == "posix_dir_fd":
            os.mkdir(leaf, mode, dir_fd=self.descriptor)
        else:
            self.verify_path()
            os.mkdir(self.child_path(leaf), mode)
            self.verify_path()
        _before_anchored_artifact_phase("after_mkdir", self.path, leaf)

    def replace(
        self,
        source: str,
        destination: str,
        *,
        expected_source: PathIdentity,
        expected_destination: PathIdentity | None,
    ) -> BaseException | None:
        source_leaf = _safe_leaf(source)
        destination_leaf = _safe_leaf(destination)
        _before_anchored_artifact_phase(
            "before_replace",
            self.path,
            destination_leaf,
        )
        self.verify_regular_identity(source_leaf, expected_source)
        if expected_destination is None:
            if self.lexists(destination_leaf):
                raise OSError(
                    "Artifact transaction destination appeared: "
                    f"{self.child_path(destination_leaf)}"
                )
        else:
            self.verify_regular_identity(destination_leaf, expected_destination)
        if self.strategy == "posix_dir_fd":
            os.rename(
                source_leaf,
                destination_leaf,
                src_dir_fd=self.descriptor,
                dst_dir_fd=self.descriptor,
            )
        elif self.strategy == "windows_handle":
            self.verify_path()
            assert self.windows_api is not None
            if not self.windows_api.MoveFileExW(
                _windows_extended_path(self.child_path(source_leaf)),
                _windows_extended_path(self.child_path(destination_leaf)),
                _WINDOWS_MOVEFILE_REPLACE_EXISTING
                | _WINDOWS_MOVEFILE_WRITE_THROUGH,
            ):
                raise _windows_api_error(
                    "Could not replace artifact transaction file",
                    self.child_path(destination_leaf),
                )
        else:
            self.verify_path()
            os.replace(
                self.child_path(source_leaf),
                self.child_path(destination_leaf),
            )
        try:
            if self.strategy != "posix_dir_fd":
                self.verify_path()
            _before_anchored_artifact_phase(
                "after_replace",
                self.path,
                destination_leaf,
            )
        except BaseException as error:
            return error
        return None

    def unlink(
        self,
        name: str,
        *,
        expected_identity: PathIdentity,
    ) -> BaseException | None:
        leaf = _safe_leaf(name)
        _before_anchored_artifact_phase("before_unlink", self.path, leaf)
        self.verify_regular_identity(leaf, expected_identity)
        if self.strategy == "posix_dir_fd":
            os.unlink(leaf, dir_fd=self.descriptor)
        else:
            self.verify_path()
            os.unlink(self.child_path(leaf))
        try:
            if self.strategy != "posix_dir_fd":
                self.verify_path()
            _before_anchored_artifact_phase("after_unlink", self.path, leaf)
        except BaseException as error:
            return error
        return None

    def chmod_exact(
        self,
        name: str,
        identity: PathIdentity,
        mode: int,
        *,
        require_single_link: bool = False,
    ) -> int:
        leaf = _safe_leaf(name)
        current = self.stat(leaf)
        if (
            not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != identity
            or (require_single_link and current.st_nlink != 1)
        ):
            raise OSError(f"Artifact transaction file changed: {self.child_path(leaf)}")
        current_mode = stat.S_IMODE(current.st_mode)
        if modes_match(current_mode, mode):
            return current_mode
        descriptor = self.open_file(leaf, os.O_RDONLY)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != identity
                or (require_single_link and opened.st_nlink != 1)
            ):
                raise OSError(
                    f"Artifact transaction file changed: {self.child_path(leaf)}"
                )
            fchmod_candidate: object = getattr(os, "fchmod", None)
            if callable(fchmod_candidate):
                fchmod = cast(Callable[[int, int], None], fchmod_candidate)
                fchmod(descriptor, mode)
            elif os.chmod in os.supports_fd:
                os.chmod(descriptor, mode)
            else:
                self.verify_regular_identity(leaf, identity)
                os.chmod(self.child_path(leaf), mode)
                self.verify_regular_identity(leaf, identity)
        finally:
            os.close(descriptor)
        self.verify_regular_identity(leaf, identity)
        current_mode = stat.S_IMODE(self.stat(leaf).st_mode)
        if not modes_match(current_mode, mode):
            raise OSError(
                f"Artifact transaction file mode did not update: {self.child_path(leaf)}"
            )
        return current_mode

    def verify_regular_identity(self, name: str, identity: PathIdentity) -> None:
        leaf = _safe_leaf(name)
        try:
            path_stat = self.stat(leaf)
        except OSError as error:
            raise OSError(
                f"Artifact transaction file changed: {self.child_path(leaf)}"
            ) from error
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != identity
        ):
            raise OSError(f"Artifact transaction file changed: {self.child_path(leaf)}")

    def sync(self) -> None:
        _before_anchored_artifact_phase("before_sync", self.path, None)
        if self.strategy == "posix_dir_fd":
            os.fsync(self.descriptor)
        elif self.strategy == "windows_handle":
            # Win32 has no documented unprivileged equivalent to POSIX
            # directory fsync. File stages are fsynced and namespace moves use
            # MOVEFILE_WRITE_THROUGH; this barrier verifies the pinned handle.
            self.verify_path()
        else:
            self.verify_path()
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(self.path, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != self.identity
                ):
                    raise OSError(f"{self.description.capitalize()} changed: {self.path}")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self.verify_path()
        _before_anchored_artifact_phase("after_sync", self.path, None)


@dataclass
class AnchoredArtifactDirectory(
    AbstractContextManager["AnchoredArtifactDirectory"]
):
    root: VerifiedDirectory
    directory: VerifiedDirectory | None
    relative_directory: str
    description: str

    @classmethod
    def open(
        cls,
        root_path: str,
        relative_directory: str,
        *,
        create: bool,
        create_root: bool = False,
        description: str,
    ) -> "AnchoredArtifactDirectory":
        child_name = _safe_leaf(relative_directory)
        root_description = f"{description} root"
        root = (
            VerifiedDirectory.open_or_create(
                root_path,
                description=root_description,
            )
            if create_root
            else VerifiedDirectory.open(
                root_path,
                description=root_description,
            )
        )
        child_path = root.child_path(child_name)
        directory: VerifiedDirectory | None = None
        try:
            try:
                child_stat = root.stat(child_name)
            except FileNotFoundError:
                if not create:
                    return cls(root, None, child_name, description)
                try:
                    root.mkdir(child_name)
                except FileExistsError:
                    pass
                child_stat = root.stat(child_name)
            if _path_is_redirected(child_path, child_stat) or not stat.S_ISDIR(
                child_stat.st_mode
            ):
                raise OSError(
                    f"Refusing redirected or non-directory {description}: {child_path}"
                )
            child_identity = (child_stat.st_dev, child_stat.st_ino)
            directory = root.open_child(
                child_name,
                expected_identity=child_identity,
                description=description,
            )
            if create:
                # Repeat the parent durability barrier even for an existing child.
                # A previous creation may have become visible before its parent
                # sync failed, and a retry must not treat that entry as durable.
                root.sync()
                directory.verify_path()
            root.verify_path()
            return cls(root, directory, child_name, description)
        except BaseException as error:
            if directory is not None:
                try:
                    directory.close()
                except OSError as close_error:
                    error.add_note(f"Could not close artifact directory: {close_error}")
            try:
                root.close()
            except OSError as close_error:
                error.add_note(f"Could not close artifact root: {close_error}")
            raise

    @property
    def path(self) -> str:
        return self.root.child_path(self.relative_directory)

    @property
    def root_identity(self) -> PathIdentity:
        return self.root.identity

    @property
    def directory_identity(self) -> PathIdentity | None:
        return None if self.directory is None else self.directory.identity

    @property
    def strategy(self) -> DirectoryStrategy | None:
        return None if self.directory is None else self.directory.strategy

    def require_directory(self) -> VerifiedDirectory:
        if self.directory is None:
            raise OSError(f"{self.description.capitalize()} is unavailable: {self.path}")
        return self.directory

    def verify(self) -> None:
        self.root.verify_path()
        if self.directory is not None:
            self.directory.verify_path()
        self.root.verify_path()

    def current_directory_path(self) -> str | None:
        """Resolve the retained directory's current name when it stays in root."""
        if self.directory is None:
            return None
        try:
            self.directory.verify_path()
        except OSError:
            pass
        else:
            return self.directory.path
        if self.root.strategy != "posix_dir_fd":
            return None
        try:
            self.root.verify_path()
            entries = os.listdir(self.root.descriptor)
        except OSError:
            return None
        for entry in entries:
            try:
                leaf = _safe_leaf(entry)
                entry_stat = self.root.stat(leaf)
            except (OSError, ValueError):
                continue
            if (
                stat.S_ISDIR(entry_stat.st_mode)
                and (entry_stat.st_dev, entry_stat.st_ino) == self.directory.identity
            ):
                candidate = self.root.child_path(leaf)
                try:
                    candidate_stat = os.lstat(candidate)
                except OSError:
                    continue
                if (
                    stat.S_ISDIR(candidate_stat.st_mode)
                    and (candidate_stat.st_dev, candidate_stat.st_ino)
                    == self.directory.identity
                ):
                    return candidate
        return None

    def __exit__(
        self,
        _exc_type: object,
        active_error: BaseException | None,
        _traceback: object,
    ) -> bool | None:
        close_error: BaseException | None = None
        try:
            if self.directory is not None:
                self.directory.close()
        except BaseException as error:
            close_error = error
        try:
            self.root.close()
        except BaseException as error:
            if close_error is None:
                close_error = error
            else:
                close_error.add_note(f"Could not close artifact root: {error}")
        if close_error is not None:
            if active_error is None:
                raise close_error
            active_error.add_note(f"Could not close artifact bindings: {close_error}")
        return None


@dataclass(frozen=True)
class ArtifactTargetState:
    fingerprint: FileFingerprint | None
    mode: int | None

    @property
    def present(self) -> bool:
        return self.fingerprint is not None


@dataclass(frozen=True)
class StagedArtifact:
    directory_path: str
    name: str
    identity: PathIdentity
    content: bytes
    # The temporary inode stays replaceable until its final transition.
    mode: int
    target_mode: int
    sha256: str

    @property
    def path(self) -> str:
        return os.path.join(self.directory_path, self.name)


@dataclass(frozen=True)
class ArtifactReceipt:
    path: str
    content: bytes
    mode: int
    fingerprint: ReceiptFingerprint
    sha256: str


@dataclass(frozen=True)
class ArtifactSnapshot:
    name: str
    content: bytes | None
    mode: int | None
    fingerprint: FileFingerprint | None
    sha256: str | None

    @property
    def present(self) -> bool:
        return self.fingerprint is not None


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    content: bytes | None
    # None preserves an existing mode and otherwise uses the private stage mode.
    mode: int | None = None


@dataclass
class _PublishedMutation:
    snapshot: ArtifactSnapshot
    desired: StagedArtifact | None
    backup: StagedArtifact | None


@dataclass
class _RestoreMutation:
    snapshot: ArtifactSnapshot
    receipt: ArtifactReceipt | None
    restored: StagedArtifact | None
    receipt_backup: StagedArtifact | None
    restored_committed: bool


@dataclass(frozen=True)
class _ReplaceTarget:
    identity: PathIdentity
    mode: int
    mode_changed: bool


class ByteArtifactTransaction(AbstractContextManager["ByteArtifactTransaction"]):
    """Byte-oriented operations confined to one retained artifact directory.

    The class intentionally owns no report schema or ordering policy. A caller
    can compose one or many ordered present/absent targets while every stage,
    backup, replacement, rollback, recovery, cleanup, and durability barrier
    uses this same binding.
    """

    def __init__(self, anchored: AnchoredArtifactDirectory) -> None:
        self.anchored = anchored

    @classmethod
    def open(
        cls,
        root_path: str,
        relative_directory: str,
        *,
        create: bool,
        create_root: bool = False,
        description: str,
    ) -> "ByteArtifactTransaction":
        return cls(
            AnchoredArtifactDirectory.open(
                root_path,
                relative_directory,
                create=create,
                create_root=create_root,
                description=description,
            )
        )

    @property
    def directory(self) -> VerifiedDirectory:
        return self.anchored.require_directory()

    @property
    def path(self) -> str:
        return self.anchored.path

    @property
    def root_identity(self) -> PathIdentity:
        return self.anchored.root_identity

    @property
    def directory_identity(self) -> PathIdentity | None:
        return self.anchored.directory_identity

    @property
    def strategy(self) -> DirectoryStrategy | None:
        return self.anchored.strategy

    @property
    def available(self) -> bool:
        return self.anchored.directory is not None

    def __exit__(
        self,
        exc_type: object,
        active_error: BaseException | None,
        traceback: object,
    ) -> bool | None:
        return self.anchored.__exit__(exc_type, active_error, traceback)

    def verify_directory(self) -> None:
        self.anchored.verify()

    def phase(self, phase: str, name: str | None = None) -> None:
        _before_anchored_artifact_phase(phase, self.path, name)

    def target_state(self, name: str) -> ArtifactTargetState:
        leaf = _safe_leaf(name)
        try:
            path_stat = self.directory.stat(leaf)
        except FileNotFoundError:
            return ArtifactTargetState(fingerprint=None, mode=None)
        path = self.directory.child_path(leaf)
        if _path_is_redirected(path, path_stat) or not stat.S_ISREG(
            path_stat.st_mode
        ):
            raise OSError(f"Refusing redirected or non-regular artifact: {path}")
        return ArtifactTargetState(
            fingerprint=_file_fingerprint(path_stat),
            mode=stat.S_IMODE(path_stat.st_mode),
        )

    def verify_target_state(
        self,
        name: str,
        expected: ArtifactTargetState,
    ) -> None:
        leaf = _safe_leaf(name)
        try:
            path_stat = self.directory.stat(leaf)
        except FileNotFoundError:
            if expected.fingerprint is None:
                return
            raise OSError(f"Artifact disappeared: {self.directory.child_path(leaf)}")
        path = self.directory.child_path(leaf)
        if (
            expected.fingerprint is None
            or _path_is_redirected(path, path_stat)
            or not stat.S_ISREG(path_stat.st_mode)
            or _file_fingerprint(path_stat) != expected.fingerprint
            or expected.mode is None
            or not modes_match(stat.S_IMODE(path_stat.st_mode), expected.mode)
        ):
            raise OSError(f"Artifact changed: {path}")

    def read_target_bytes(
        self,
        name: str,
        expected: ArtifactTargetState,
    ) -> bytes:
        leaf = _safe_leaf(name)
        if expected.fingerprint is None:
            raise ValueError("Cannot read an absent artifact.")
        descriptor = self.directory.open_file(leaf, os.O_RDONLY)
        try:
            opened_before = os.fstat(descriptor)
            path_before = self.directory.stat(leaf)
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or not fingerprints_match(
                    _file_fingerprint(opened_before),
                    expected.fingerprint,
                )
                or _file_fingerprint(path_before) != expected.fingerprint
            ):
                raise OSError(
                    f"Artifact changed while reading: {self.directory.child_path(leaf)}"
                )
            with os.fdopen(descriptor, "rb") as artifact_file:
                descriptor = -1
                content = artifact_file.read()
                opened_after = os.fstat(artifact_file.fileno())
            if not fingerprints_match(
                _file_fingerprint(opened_after),
                expected.fingerprint,
            ):
                raise OSError(
                    f"Artifact changed while reading: {self.directory.child_path(leaf)}"
                )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        self.verify_target_state(leaf, expected)
        return content

    def stage_existing(
        self,
        name: str,
        expected: ArtifactTargetState,
        *,
        suffix: str = ".backup",
    ) -> StagedArtifact | None:
        leaf = _safe_leaf(name)
        if expected.fingerprint is None:
            return None
        self.phase("before_backup", leaf)
        content = self.read_target_bytes(leaf, expected)
        self.verify_target_state(leaf, expected)
        staged = self.stage_bytes(
            leaf,
            content,
            mode=expected.mode,
            suffix=suffix,
            phase_name="backup_stage",
        )
        self.phase("after_backup", leaf)
        return staged

    def stage_bytes(
        self,
        target_name: str,
        content: bytes,
        *,
        mode: int | None,
        suffix: str,
        phase_name: str = "stage",
        staged_name: str | None = None,
    ) -> StagedArtifact:
        target_leaf = _safe_leaf(target_name)
        self.phase(f"before_{phase_name}", target_leaf)
        descriptor = -1
        staged_leaf = ""
        identity: PathIdentity | None = None
        candidates = (
            (_safe_leaf(staged_name),)
            if staged_name is not None
            else tuple(
                f".{target_leaf}.{secrets.token_hex(8)}{suffix}"
                for _attempt in range(100)
            )
        )
        for candidate in candidates:
            staged_leaf = candidate
            try:
                descriptor = self.directory.open_file(
                    staged_leaf,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                break
            except FileExistsError:
                continue
        if descriptor < 0:
            raise OSError(
                f"Could not stage artifact transaction file: {target_leaf}"
            )
        initial_stat = os.fstat(descriptor)
        identity = (initial_stat.st_dev, initial_stat.st_ino)
        if not stat.S_ISREG(initial_stat.st_mode) or initial_stat.st_nlink != 1:
            os.close(descriptor)
            descriptor = -1
            cleanup_error = self.unlink_if_identity(staged_leaf, identity)
            if cleanup_error is not None:
                cleanup_error.add_note(
                    f"Rejected artifact stage remained: {self.directory.child_path(staged_leaf)}"
                )
            raise OSError(
                f"Refusing non-regular or multiply-linked artifact stage: "
                f"{self.directory.child_path(staged_leaf)}"
            )
        target_mode = stat.S_IMODE(initial_stat.st_mode) if mode is None else mode
        staging_mode = _replaceable_mode(target_mode)
        try:
            with os.fdopen(descriptor, "wb") as staged_file:
                descriptor = -1
                staged_file.write(content)
                staged_file.flush()
                if not modes_match(
                    stat.S_IMODE(os.fstat(staged_file.fileno()).st_mode),
                    staging_mode,
                ):
                    fchmod_candidate: object = getattr(os, "fchmod", None)
                    if callable(fchmod_candidate):
                        fchmod = cast(Callable[[int, int], None], fchmod_candidate)
                        fchmod(staged_file.fileno(), staging_mode)
                    else:
                        self.directory.chmod_exact(
                            staged_leaf,
                            identity,
                            staging_mode,
                        )
                os.fsync(staged_file.fileno())
            staged_stat = self.directory.stat(staged_leaf)
            staged_mode = stat.S_IMODE(staged_stat.st_mode)
            if (
                not stat.S_ISREG(staged_stat.st_mode)
                or staged_stat.st_nlink != 1
                or (staged_stat.st_dev, staged_stat.st_ino) != identity
                or not modes_match(staged_mode, staging_mode)
            ):
                raise OSError(
                    f"Staged artifact changed: {self.directory.child_path(staged_leaf)}"
                )
            staged = StagedArtifact(
                directory_path=self.path,
                name=staged_leaf,
                identity=identity,
                content=content,
                mode=staged_mode,
                target_mode=target_mode,
                sha256=_sha256_bytes(content),
            )
            self.verify_staged(staged)
            self.phase(f"after_{phase_name}", target_leaf)
            return staged
        except BaseException as error:
            if descriptor >= 0:
                os.close(descriptor)
            cleanup_error = self.unlink_if_identity(staged_leaf, identity)
            if cleanup_error is not None:
                error.add_note(
                    "Failed to remove incomplete artifact transaction stage: "
                    f"{cleanup_error}"
                )
            raise

    def read_staged(
        self,
        staged: StagedArtifact,
        *,
        name: str | None = None,
        verify_mode: bool = True,
    ) -> bytes:
        selected_name = staged.name if name is None else _safe_leaf(name)
        expected_mode = (
            staged.mode if selected_name == staged.name else staged.target_mode
        )
        descriptor = self.directory.open_file(selected_name, os.O_RDONLY)
        try:
            opened_before = os.fstat(descriptor)
            fingerprint_before = _file_fingerprint(opened_before)
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or opened_before.st_nlink != 1
                or (opened_before.st_dev, opened_before.st_ino) != staged.identity
                or (
                    verify_mode
                    and not modes_match(
                        stat.S_IMODE(opened_before.st_mode),
                        expected_mode,
                    )
                )
            ):
                raise OSError(
                    f"Staged artifact changed: {self.directory.child_path(selected_name)}"
                )
            with os.fdopen(descriptor, "rb") as staged_file:
                descriptor = -1
                content = staged_file.read()
                opened_after = os.fstat(staged_file.fileno())
            path_after = self.directory.stat(selected_name)
            if (
                not stat.S_ISREG(opened_after.st_mode)
                or opened_after.st_nlink != 1
                or path_after.st_nlink != 1
                or (opened_after.st_dev, opened_after.st_ino) != staged.identity
                or (path_after.st_dev, path_after.st_ino) != staged.identity
                or (
                    verify_mode
                    and not modes_match(
                        stat.S_IMODE(opened_after.st_mode),
                        expected_mode,
                    )
                )
                or (
                    verify_mode
                    and not modes_match(
                        stat.S_IMODE(path_after.st_mode),
                        expected_mode,
                    )
                )
                or not fingerprints_match(
                    _file_fingerprint(opened_after),
                    fingerprint_before,
                )
                or not fingerprints_match(
                    _file_fingerprint(path_after),
                    fingerprint_before,
                )
                or content != staged.content
                or _sha256_bytes(content) != staged.sha256
            ):
                raise OSError(
                    "Staged artifact content changed: "
                    f"{self.directory.child_path(selected_name)}"
                )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        self.directory.verify_regular_identity(selected_name, staged.identity)
        return content

    def verify_staged(
        self,
        staged: StagedArtifact,
        *,
        name: str | None = None,
    ) -> None:
        self.read_staged(staged, name=name)

    def path_matches_stage(self, name: str, staged: StagedArtifact) -> bool:
        try:
            self.read_staged(staged, name=name, verify_mode=False)
        except OSError:
            return False
        return True

    def _make_target_replaceable(self, name: str) -> _ReplaceTarget | None:
        leaf = _safe_leaf(name)
        try:
            path_stat = self.directory.stat(leaf)
        except FileNotFoundError:
            return None
        path = self.directory.child_path(leaf)
        if _path_is_redirected(path, path_stat) or not stat.S_ISREG(
            path_stat.st_mode
        ):
            raise OSError(f"Refusing redirected or non-regular artifact: {path}")
        identity = (path_stat.st_dev, path_stat.st_ino)
        mode = stat.S_IMODE(path_stat.st_mode)
        mode_changed = _is_windows_platform() and not mode & stat.S_IWUSR
        if mode_changed:
            if path_stat.st_nlink != 1:
                raise OSError(
                    "Refusing to change a read-only multiply-linked artifact: "
                    f"{path}"
                )
            self.directory.chmod_exact(
                leaf,
                identity,
                _replaceable_mode(mode),
                require_single_link=True,
            )
        return _ReplaceTarget(identity=identity, mode=mode, mode_changed=mode_changed)

    def _restore_replace_target_mode(
        self,
        name: str,
        target: _ReplaceTarget | None,
        error: BaseException,
    ) -> None:
        if target is None or not target.mode_changed:
            return
        try:
            self.directory.chmod_exact(name, target.identity, target.mode)
        except Exception as mode_error:
            error.add_note(
                f"Failed to restore replaced artifact target mode: {mode_error}"
            )

    def replace_staged(
        self,
        staged: StagedArtifact,
        target_name: str,
    ) -> BaseException | None:
        target_leaf = _safe_leaf(target_name)
        self.phase("before_commit", target_leaf)
        self.verify_staged(staged)
        target_state = self._make_target_replaceable(target_leaf)
        try:
            self.directory.chmod_exact(
                staged.name,
                staged.identity,
                staged.target_mode,
            )
            completion_error = self.directory.replace(
                staged.name,
                target_leaf,
                expected_source=staged.identity,
                expected_destination=(
                    None if target_state is None else target_state.identity
                ),
            )
        except BaseException as error:
            if self.path_matches_stage(target_leaf, staged):
                return error
            try:
                self.directory.chmod_exact(
                    staged.name,
                    staged.identity,
                    staged.mode,
                )
            except Exception as mode_error:
                error.add_note(
                    f"Failed to restore replaceable artifact stage mode: {mode_error}"
                )
            self._restore_replace_target_mode(target_leaf, target_state, error)
            raise
        if completion_error is not None:
            return completion_error
        try:
            self.verify_staged(staged, name=target_leaf)
            self.phase("after_commit", target_leaf)
        except BaseException as error:
            return error
        return None

    def replace_target_with_stage_path(
        self,
        target_name: str,
        staged_copy: StagedArtifact,
        displaced_target: StagedArtifact,
    ) -> BaseException | None:
        target_leaf = _safe_leaf(target_name)
        self.verify_staged(staged_copy)
        target_state = self._make_target_replaceable(target_leaf)
        if target_state is None:
            raise OSError(
                f"Artifact disappeared before displacement: "
                f"{self.directory.child_path(target_leaf)}"
            )
        try:
            completion_error = self.directory.replace(
                target_leaf,
                staged_copy.name,
                expected_source=target_state.identity,
                expected_destination=staged_copy.identity,
            )
        except BaseException as error:
            if self.path_matches_stage(staged_copy.name, displaced_target):
                return error
            self._restore_replace_target_mode(target_leaf, target_state, error)
            raise
        if completion_error is not None:
            return completion_error
        try:
            self.verify_staged(displaced_target)
        except BaseException as error:
            return error
        return None

    def unlink_finalized(
        self,
        staged: StagedArtifact,
        name: str,
        *,
        tombstone_name: str | None = None,
    ) -> tuple[StagedArtifact | None, BaseException | None]:
        leaf = _safe_leaf(name)
        self.verify_staged(staged, name=leaf)
        if self.strategy == "windows_handle":
            # Win32 has no directory-fsync equivalent for an unlink. Move the
            # exact public inode behind a private name with write-through first;
            # best-effort cleanup may leave only that hidden tombstone after a
            # power loss, never resurrect the public target.
            placeholder = self.stage_bytes(
                leaf,
                staged.content,
                mode=staged.target_mode,
                suffix=".tombstone",
                phase_name="tombstone_stage",
                staged_name=tombstone_name,
            )
            displaced = StagedArtifact(
                directory_path=self.path,
                name=placeholder.name,
                identity=staged.identity,
                content=staged.content,
                mode=_replaceable_mode(staged.target_mode),
                target_mode=staged.target_mode,
                sha256=staged.sha256,
            )
            try:
                completion_error = self.replace_target_with_stage_path(
                    leaf,
                    placeholder,
                    displaced,
                )
            except BaseException as error:
                cleanup_error = self.unlink_staged(placeholder)
                if cleanup_error is not None:
                    error.add_note(
                        "Failed to remove unused artifact tombstone stage: "
                        f"{cleanup_error}"
                    )
                raise
            return displaced, completion_error
        target_state = self._make_target_replaceable(leaf)
        if target_state is None:
            return None, None
        try:
            completion_error = self.directory.unlink(
                leaf,
                expected_identity=target_state.identity,
            )
        except BaseException as error:
            if not self.directory.lexists(leaf):
                return None, error
            self._restore_replace_target_mode(leaf, target_state, error)
            raise
        if completion_error is not None:
            return None, completion_error
        if self.directory.lexists(leaf):
            error = OSError(
                f"Artifact remained after unlink: {self.directory.child_path(leaf)}"
            )
            return None, error
        return None, None

    def unlink_staged(self, staged: StagedArtifact) -> Exception | None:
        try:
            self.verify_staged(staged)
            completion_error = self.directory.unlink(
                staged.name,
                expected_identity=staged.identity,
            )
            if completion_error is not None:
                raise completion_error
        except Exception as error:
            return error
        return None

    def unlink_if_identity(
        self,
        name: str,
        identity: PathIdentity | None,
    ) -> Exception | None:
        if identity is None:
            return None
        try:
            self.directory.verify_regular_identity(name, identity)
            completion_error = self.directory.unlink(
                name,
                expected_identity=identity,
            )
            if completion_error is not None:
                raise completion_error
        except Exception as error:
            return error
        return None

    def cleanup(
        self,
        temporary_files: dict[str, StagedArtifact],
    ) -> list[Exception]:
        self.phase("before_cleanup", None)
        errors: list[Exception] = []
        removed = False
        for temporary_name, staged in tuple(temporary_files.items()):
            try:
                if not self.directory.lexists(temporary_name):
                    temporary_files.pop(temporary_name, None)
                    continue
                self.verify_staged(staged)
                completion_error = self.directory.unlink(
                    temporary_name,
                    expected_identity=staged.identity,
                )
                temporary_files.pop(temporary_name, None)
                removed = True
                if completion_error is not None:
                    raise completion_error
            except Exception as error:
                errors.append(error)
        if removed:
            try:
                self.sync("cleanup_durability")
            except Exception as error:
                errors.append(error)
        self.phase("after_cleanup", None)
        return errors

    def sync(self, phase: str = "durability") -> None:
        self.phase(f"before_{phase}", None)
        self.directory.sync()
        self.anchored.root.verify_path()
        self.phase(f"after_{phase}", None)

    def receipt(self, name: str, staged: StagedArtifact) -> ArtifactReceipt:
        leaf = _safe_leaf(name)
        self.verify_staged(staged, name=leaf)
        path_stat = self.directory.stat(leaf)
        return ArtifactReceipt(
            path=self.directory.child_path(leaf),
            content=staged.content,
            mode=stat.S_IMODE(path_stat.st_mode),
            fingerprint=_stable_fingerprint(_file_fingerprint(path_stat)),
            sha256=staged.sha256,
        )

    def verify_receipt(self, receipt: ArtifactReceipt) -> None:
        expected_parent = os.path.normcase(os.path.abspath(self.path))
        receipt_parent = os.path.normcase(os.path.abspath(os.path.dirname(receipt.path)))
        if receipt_parent != expected_parent:
            raise ValueError("Artifact receipt belongs to another directory.")
        leaf = _safe_leaf(os.path.basename(receipt.path))
        state = self.target_state(leaf)
        if (
            state.fingerprint is None
            or _stable_fingerprint(state.fingerprint) != receipt.fingerprint
            or state.mode is None
            or not modes_match(state.mode, receipt.mode)
            or _sha256_bytes(receipt.content) != receipt.sha256
        ):
            raise OSError(f"Artifact no longer matches its receipt: {receipt.path}")
        content = self.read_target_bytes(leaf, state)
        if content != receipt.content or _sha256_bytes(content) != receipt.sha256:
            raise OSError(f"Artifact no longer matches its receipt: {receipt.path}")

    def capture_snapshot(self, name: str) -> ArtifactSnapshot:
        leaf = _safe_leaf(name)
        state = self.target_state(leaf)
        if state.fingerprint is None:
            self.verify_directory()
            self.verify_target_state(leaf, state)
            return ArtifactSnapshot(
                name=leaf,
                content=None,
                mode=None,
                fingerprint=None,
                sha256=None,
            )
        content = self.read_target_bytes(leaf, state)
        return ArtifactSnapshot(
            name=leaf,
            content=content,
            mode=state.mode,
            fingerprint=state.fingerprint,
            sha256=_sha256_bytes(content),
        )

    def capture_staged(self, name: str) -> StagedArtifact | None:
        """Capture an existing private artifact for identity-bound cleanup."""
        leaf = _safe_leaf(name)
        state = self.target_state(leaf)
        if state.fingerprint is None:
            return None
        if state.mode is None:
            raise AssertionError("A present artifact target must have a mode.")
        content = self.read_target_bytes(leaf, state)
        staged = StagedArtifact(
            directory_path=self.path,
            name=leaf,
            identity=(state.fingerprint[0], state.fingerprint[1]),
            content=content,
            mode=state.mode,
            target_mode=state.mode,
            sha256=_sha256_bytes(content),
        )
        self.verify_staged(staged)
        return staged

    def capture_snapshots(
        self,
        names: tuple[str, ...],
    ) -> tuple[ArtifactSnapshot, ...]:
        self._validate_unique_names(names)
        return tuple(self.capture_snapshot(name) for name in names)

    def verify_snapshot(self, snapshot: ArtifactSnapshot) -> None:
        self._validate_snapshot(snapshot)
        self._verify_snapshot_current(snapshot)

    def _verify_snapshot_current(self, snapshot: ArtifactSnapshot) -> None:
        state = self._snapshot_state(snapshot)
        self.verify_target_state(snapshot.name, state)
        if not snapshot.present:
            return
        assert snapshot.content is not None
        assert snapshot.sha256 is not None
        content = self.read_target_bytes(snapshot.name, state)
        if content != snapshot.content or _sha256_bytes(content) != snapshot.sha256:
            raise OSError(
                "Artifact content changed: "
                f"{self.directory.child_path(snapshot.name)}"
            )

    def publish_specs(
        self,
        specs: tuple[ArtifactSpec, ...],
        *,
        guards: tuple[ArtifactSnapshot, ...] = (),
        before_commit: Callable[[str], None] | None = None,
        after_commit: Callable[[str], None] | None = None,
    ) -> tuple[ArtifactReceipt | None, ...]:
        """Publish an ordered present/absent set with guards and reverse rollback."""
        self._validate_unique_names(
            tuple(spec.name for spec in specs)
            + tuple(guard.name for guard in guards)
        )
        for guard in guards:
            self._validate_snapshot(guard)
        normalized_specs = tuple(
            ArtifactSpec(
                name=_safe_leaf(spec.name),
                content=spec.content,
                mode=spec.mode,
            )
            for spec in specs
        )
        snapshots = self.capture_snapshots(
            tuple(spec.name for spec in normalized_specs)
        )
        desired_stages: dict[str, StagedArtifact | None] = {}
        backups: dict[str, StagedArtifact | None] = {}
        temporary_files: dict[str, StagedArtifact] = {}
        active_error: BaseException | None = None
        mutations: list[_PublishedMutation] = []

        def verify_guards() -> None:
            self.verify_directory()
            for guard in guards:
                self._verify_snapshot_current(guard)

        try:
            verify_guards()
            for spec, snapshot in zip(normalized_specs, snapshots, strict=True):
                verify_guards()
                desired = None
                if spec.content is not None:
                    desired = self.stage_bytes(
                        spec.name,
                        spec.content,
                        mode=snapshot.mode if spec.mode is None else spec.mode,
                        suffix=".tmp",
                    )
                    temporary_files[desired.name] = desired
                desired_stages[spec.name] = desired
            for spec, snapshot in zip(normalized_specs, snapshots, strict=True):
                verify_guards()
                backup = self.stage_existing(
                    spec.name,
                    self._snapshot_state(snapshot),
                )
                backups[spec.name] = backup
                if backup is not None:
                    temporary_files[backup.name] = backup
                if snapshot.present and (
                    backup is None
                    or backup.content != snapshot.content
                    or backup.sha256 != snapshot.sha256
                ):
                    raise OSError(
                        "Artifact backup no longer matches its snapshot: "
                        f"{self.directory.child_path(snapshot.name)}"
                    )
                self._verify_snapshot_current(snapshot)
                verify_guards()

            verify_guards()
            for snapshot in snapshots:
                self._verify_snapshot_current(snapshot)

            for spec, snapshot in zip(normalized_specs, snapshots, strict=True):
                desired = desired_stages[spec.name]
                backup = backups[spec.name]
                # Earlier ordered commits and their durability barriers can
                # give another writer time to change a later target. Never
                # overwrite that external state from the stale preflight.
                self._verify_snapshot_current(snapshot)
                verify_guards()
                mutation_started = False
                completion_error: BaseException | None = None
                if before_commit is not None:
                    before_commit(spec.name)
                    self._verify_snapshot_current(snapshot)
                    verify_guards()
                if desired is not None:
                    completion_error = self.replace_staged(desired, spec.name)
                    mutation_started = True
                    temporary_files.pop(desired.name, None)
                elif snapshot.present:
                    published_previous = self._snapshot_as_staged(
                        snapshot,
                        name=spec.name,
                        storage_mode=cast(int, snapshot.mode),
                    )
                    tombstone, completion_error = self.unlink_finalized(
                        published_previous,
                        spec.name,
                    )
                    if tombstone is not None:
                        temporary_files[tombstone.name] = tombstone
                    mutation_started = True
                if mutation_started:
                    mutations.append(_PublishedMutation(snapshot, desired, backup))
                    if completion_error is not None:
                        raise completion_error
                    self.phase("before_durability", spec.name)
                    self.sync(f"commit_{spec.name}_durability")
                    self.phase("after_durability", spec.name)
                    verify_guards()
                    if after_commit is not None:
                        after_commit(spec.name)
                        verify_guards()

            receipts = tuple(
                None
                if desired_stages[spec.name] is None
                else self.receipt(spec.name, cast(StagedArtifact, desired_stages[spec.name]))
                for spec in normalized_specs
            )
        except BaseException as error:
            active_error = error
            if mutations:
                rollback_error = self._rollback_published_mutations(
                    mutations,
                    temporary_files,
                )
                if rollback_error is not None:
                    error.add_note(f"Artifact publication rollback also failed: {rollback_error}")
            raise
        finally:
            cleanup_errors = self.cleanup(temporary_files)
            if active_error is not None and cleanup_errors:
                active_error.add_note(
                    "Artifact publication cleanup failed: "
                    + "; ".join(str(error) for error in cleanup_errors)
                )

        verify_guards()
        for spec, receipt in zip(normalized_specs, receipts, strict=True):
            if receipt is None:
                if self.directory.lexists(spec.name):
                    raise OSError(
                        f"Absent artifact reappeared after publication: {spec.name}"
                    )
            else:
                self.verify_receipt(receipt)
        return receipts

    def restore_snapshots(
        self,
        snapshots: tuple[ArtifactSnapshot, ...],
        receipts: tuple[ArtifactReceipt | None, ...],
    ) -> None:
        """Restore ordered snapshots while exact publication receipts remain live."""
        if len(snapshots) != len(receipts):
            raise ValueError("Artifact snapshots and receipts must have equal lengths.")
        self._validate_unique_names(tuple(snapshot.name for snapshot in snapshots))
        for snapshot in snapshots:
            self._validate_snapshot(snapshot)
        for snapshot, receipt in zip(snapshots, receipts, strict=True):
            if receipt is None:
                self.verify_target_state(
                    snapshot.name,
                    ArtifactTargetState(fingerprint=None, mode=None),
                )
            else:
                if os.path.basename(receipt.path) != snapshot.name:
                    raise ValueError("Artifact receipt belongs to another snapshot.")
                self.verify_receipt(receipt)

        receipt_copies: dict[str, StagedArtifact | None] = {}
        restored_stages: dict[str, StagedArtifact | None] = {}
        temporary_files: dict[str, StagedArtifact] = {}
        mutations: list[_RestoreMutation] = []
        active_error: BaseException | None = None
        try:
            for snapshot, receipt in zip(snapshots, receipts, strict=True):
                receipt_copy = None
                if receipt is not None:
                    receipt_copy = self.stage_bytes(
                        snapshot.name,
                        receipt.content,
                        mode=receipt.mode,
                        suffix=".restore.backup",
                    )
                    temporary_files[receipt_copy.name] = receipt_copy
                receipt_copies[snapshot.name] = receipt_copy

                restored = None
                if snapshot.present:
                    assert snapshot.content is not None
                    assert snapshot.mode is not None
                    restored = self.stage_bytes(
                        snapshot.name,
                        snapshot.content,
                        mode=snapshot.mode,
                        suffix=".restore.tmp",
                    )
                    temporary_files[restored.name] = restored
                restored_stages[snapshot.name] = restored

            # Staging can run arbitrary filesystem work and is deliberately
            # observable through the phase hook. Recheck every publication
            # receipt immediately before the first namespace mutation so a
            # target changed during preparation is left completely untouched.
            self.verify_directory()
            for snapshot, receipt in zip(snapshots, receipts, strict=True):
                if receipt is None:
                    self.verify_target_state(
                        snapshot.name,
                        ArtifactTargetState(fingerprint=None, mode=None),
                    )
                else:
                    self.verify_receipt(receipt)

            for snapshot, receipt in zip(snapshots, receipts, strict=True):
                restored = restored_stages[snapshot.name]
                receipt_copy = receipt_copies[snapshot.name]
                # Preserve exact optimistic-concurrency semantics for every
                # ordered entry, not only for the set-wide preflight.
                if receipt is None:
                    self.verify_target_state(
                        snapshot.name,
                        ArtifactTargetState(fingerprint=None, mode=None),
                    )
                else:
                    self.verify_receipt(receipt)
                displaced_receipt: StagedArtifact | None = None
                mutation_started = False
                recorded_mutation: _RestoreMutation | None = None
                if receipt is not None:
                    assert receipt_copy is not None
                    displaced_receipt = self._receipt_as_staged(
                        receipt,
                        name=receipt_copy.name,
                        storage_mode=receipt_copy.mode,
                    )
                    completion_error = self.replace_target_with_stage_path(
                        snapshot.name,
                        receipt_copy,
                        displaced_receipt,
                    )
                    mutation_started = True
                    temporary_files[displaced_receipt.name] = displaced_receipt
                    recorded_mutation = _RestoreMutation(
                        snapshot,
                        receipt,
                        restored,
                        displaced_receipt,
                        False,
                    )
                    mutations.append(recorded_mutation)
                    if completion_error is not None:
                        raise completion_error
                if restored is not None:
                    completion_error = self.replace_staged(restored, snapshot.name)
                    mutation_started = True
                    temporary_files.pop(restored.name, None)
                    if recorded_mutation is None:
                        recorded_mutation = _RestoreMutation(
                            snapshot,
                            receipt,
                            restored,
                            displaced_receipt,
                            True,
                        )
                        mutations.append(recorded_mutation)
                    else:
                        recorded_mutation.restored_committed = True
                    if completion_error is not None:
                        raise completion_error
                if mutation_started:
                    self.phase("before_durability", snapshot.name)
                    self.sync(f"restore_{snapshot.name}_durability")
                    self.phase("after_durability", snapshot.name)
                self._verify_restored_snapshot(snapshot, restored)
        except BaseException as error:
            active_error = error
            if mutations:
                rollback_error = self._rollback_restore_mutations(
                    mutations,
                    temporary_files,
                )
                if rollback_error is not None:
                    error.add_note(f"Artifact snapshot rollback also failed: {rollback_error}")
            raise
        finally:
            cleanup_errors = self.cleanup(temporary_files)
            if active_error is not None and cleanup_errors:
                active_error.add_note(
                    "Artifact restore cleanup failed: "
                    + "; ".join(str(error) for error in cleanup_errors)
                )

        self.verify_directory()
        for snapshot in snapshots:
            self._verify_restored_snapshot(
                snapshot,
                restored_stages[snapshot.name],
            )

    def _rollback_published_mutations(
        self,
        mutations: list[_PublishedMutation],
        temporary_files: dict[str, StagedArtifact],
    ) -> Exception | None:
        errors: list[BaseException] = []
        retained_paths: list[str] = []
        try:
            self.phase("before_rollback", None)
        except BaseException as error:
            errors.append(error)
        for mutation in reversed(mutations):
            name = mutation.snapshot.name
            backup = mutation.backup
            desired = mutation.desired
            recovery: StagedArtifact | None = None
            try:
                if desired is not None:
                    self.verify_staged(desired, name=name)
                elif self.directory.lexists(name):
                    raise OSError(f"Absent artifact changed before rollback: {name}")
                if backup is None:
                    assert desired is not None
                    tombstone, completion_error = self.unlink_finalized(
                        desired,
                        name,
                    )
                    if tombstone is not None:
                        temporary_files[tombstone.name] = tombstone
                    if completion_error is not None:
                        raise completion_error
                else:
                    recovery = self.stage_bytes(
                        name,
                        backup.content,
                        mode=backup.target_mode,
                        suffix=".recovery.backup",
                        phase_name="recovery_stage",
                    )
                    temporary_files[recovery.name] = recovery
                    completion_error = self.replace_staged(backup, name)
                    temporary_files.pop(backup.name, None)
                    if completion_error is not None:
                        raise completion_error
                self.sync(f"rollback_{name}_durability")
                self._verify_snapshot_restored(mutation.snapshot, backup)
                if recovery is not None:
                    cleanup_error = self.unlink_staged(recovery)
                    if cleanup_error is None:
                        temporary_files.pop(recovery.name, None)
                        self.sync(f"recovery_{name}_cleanup_durability")
            except BaseException as error:
                errors.append(error)
                try:
                    retained = self._retain_recovery(
                        (recovery, backup),
                        temporary_files,
                    )
                    if retained is not None:
                        retained_paths.append(retained)
                except BaseException as retention_error:
                    errors.append(retention_error)
        try:
            self.phase("after_rollback", None)
        except BaseException as error:
            errors.append(error)
        return self._combined_rollback_error(errors, retained_paths)

    def _rollback_restore_mutations(
        self,
        mutations: list[_RestoreMutation],
        temporary_files: dict[str, StagedArtifact],
    ) -> Exception | None:
        errors: list[BaseException] = []
        retained_paths: list[str] = []
        try:
            self.phase("before_rollback", None)
        except BaseException as error:
            errors.append(error)
        for mutation in reversed(mutations):
            name = mutation.snapshot.name
            recovery: StagedArtifact | None = None
            try:
                if mutation.restored_committed:
                    self._verify_restored_snapshot(
                        mutation.snapshot,
                        mutation.restored,
                    )
                elif self.directory.lexists(name):
                    raise OSError(
                        f"Artifact changed after receipt displacement: {name}"
                    )
                if mutation.receipt is None:
                    if mutation.restored is not None:
                        tombstone, completion_error = self.unlink_finalized(
                            mutation.restored,
                            name,
                        )
                        if tombstone is not None:
                            temporary_files[tombstone.name] = tombstone
                        if completion_error is not None:
                            raise completion_error
                else:
                    receipt_backup = mutation.receipt_backup
                    if receipt_backup is None:
                        raise OSError(f"Artifact receipt backup disappeared: {name}")
                    recovery = self.stage_bytes(
                        name,
                        receipt_backup.content,
                        mode=receipt_backup.target_mode,
                        suffix=".recovery.backup",
                    )
                    temporary_files[recovery.name] = recovery
                    completion_error = self.replace_staged(receipt_backup, name)
                    temporary_files.pop(receipt_backup.name, None)
                    if completion_error is not None:
                        raise completion_error
                self.sync(f"restore_rollback_{name}_durability")
                if mutation.receipt is None:
                    if self.directory.lexists(name):
                        raise OSError(f"Absent receipt reappeared: {name}")
                else:
                    self.verify_receipt(mutation.receipt)
                if recovery is not None:
                    cleanup_error = self.unlink_staged(recovery)
                    if cleanup_error is None:
                        temporary_files.pop(recovery.name, None)
                        self.sync(f"restore_recovery_{name}_cleanup_durability")
            except BaseException as error:
                errors.append(error)
                try:
                    retained = self._retain_recovery(
                        (mutation.receipt_backup, recovery),
                        temporary_files,
                    )
                    if retained is not None:
                        retained_paths.append(retained)
                except BaseException as retention_error:
                    errors.append(retention_error)
        try:
            self.phase("after_rollback", None)
        except BaseException as error:
            errors.append(error)
        return self._combined_rollback_error(errors, retained_paths)

    @staticmethod
    def _combined_rollback_error(
        errors: list[BaseException],
        retained_paths: list[str],
    ) -> Exception | None:
        if not errors:
            return None
        details = "; ".join(str(error) for error in errors)
        if retained_paths:
            details += "; verified recovery artifact preserved at: " + ", ".join(
                retained_paths
            )
        wrapped = OSError(details)
        wrapped.__cause__ = errors[0]
        for additional_error in errors[1:]:
            wrapped.add_note(f"Additional rollback failure: {additional_error}")
        return wrapped

    def _retain_recovery(
        self,
        candidates: tuple[StagedArtifact | None, ...],
        temporary_files: dict[str, StagedArtifact],
    ) -> str | None:
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                self.verify_staged(candidate)
            except OSError:
                continue
            temporary_files.pop(candidate.name, None)
            current_directory = self.anchored.current_directory_path()
            if current_directory is not None:
                return os.path.join(current_directory, candidate.name)
            return (
                f"{candidate.name!r} in retained directory identity "
                f"{self.directory.identity!r}; original path {self.path!r} changed"
            )
        return None

    def _verify_restored_snapshot(
        self,
        snapshot: ArtifactSnapshot,
        restored: StagedArtifact | None,
    ) -> None:
        if not snapshot.present:
            if self.directory.lexists(snapshot.name):
                raise OSError(f"Artifact should have been absent: {snapshot.name}")
            return
        if restored is None:
            raise ValueError("A present snapshot requires a staged artifact.")
        self.verify_staged(restored, name=snapshot.name)

    def _verify_snapshot_restored(
        self,
        snapshot: ArtifactSnapshot,
        backup: StagedArtifact | None,
    ) -> None:
        if not snapshot.present:
            if self.directory.lexists(snapshot.name):
                raise OSError(f"Artifact should have rolled back to absence: {snapshot.name}")
            return
        if backup is None:
            raise OSError(f"Artifact rollback backup disappeared: {snapshot.name}")
        self.verify_staged(backup, name=snapshot.name)

    def _snapshot_as_staged(
        self,
        snapshot: ArtifactSnapshot,
        *,
        name: str,
        storage_mode: int,
    ) -> StagedArtifact:
        if (
            snapshot.content is None
            or snapshot.mode is None
            or snapshot.fingerprint is None
            or snapshot.sha256 is None
        ):
            raise ValueError("A present artifact snapshot is incomplete.")
        return StagedArtifact(
            directory_path=self.path,
            name=_safe_leaf(name),
            identity=(snapshot.fingerprint[0], snapshot.fingerprint[1]),
            content=snapshot.content,
            mode=storage_mode,
            target_mode=snapshot.mode,
            sha256=snapshot.sha256,
        )

    def _receipt_as_staged(
        self,
        receipt: ArtifactReceipt,
        *,
        name: str,
        storage_mode: int,
    ) -> StagedArtifact:
        return StagedArtifact(
            directory_path=self.path,
            name=_safe_leaf(name),
            identity=(receipt.fingerprint[0], receipt.fingerprint[1]),
            content=receipt.content,
            mode=storage_mode,
            target_mode=receipt.mode,
            sha256=receipt.sha256,
        )

    @staticmethod
    def _snapshot_state(snapshot: ArtifactSnapshot) -> ArtifactTargetState:
        return ArtifactTargetState(
            fingerprint=snapshot.fingerprint,
            mode=snapshot.mode,
        )

    @staticmethod
    def _validate_snapshot(snapshot: ArtifactSnapshot) -> None:
        _safe_leaf(snapshot.name)
        if snapshot.present:
            if (
                snapshot.content is None
                or snapshot.mode is None
                or snapshot.sha256 is None
            ):
                raise ValueError("A present artifact snapshot is incomplete.")
            assert snapshot.fingerprint is not None
            if (
                len(snapshot.content) != snapshot.fingerprint[2]
                or _sha256_bytes(snapshot.content) != snapshot.sha256
            ):
                raise ValueError("Artifact snapshot content does not match its fingerprint.")
            return
        if (
            snapshot.content is not None
            or snapshot.mode is not None
            or snapshot.sha256 is not None
        ):
            raise ValueError("An absent artifact snapshot cannot contain file data.")

    @staticmethod
    def _validate_unique_names(names: tuple[str, ...]) -> None:
        normalized = tuple(_safe_leaf(name) for name in names)
        comparison_names = (
            tuple(name.casefold() for name in normalized)
            if os.name == "nt"
            else normalized
        )
        if len(set(comparison_names)) != len(comparison_names):
            raise ValueError("Artifact transaction names must be unique.")


def artifact_sha256(content: bytes) -> str:
    return _sha256_bytes(content)


def stable_artifact_fingerprint(
    fingerprint: FileFingerprint,
) -> ReceiptFingerprint:
    return _stable_fingerprint(fingerprint)


__all__ = [
    "AnchoredArtifactDirectory",
    "ArtifactReceipt",
    "ArtifactSnapshot",
    "ArtifactSpec",
    "ArtifactTargetState",
    "ByteArtifactTransaction",
    "DirectoryStrategy",
    "FileFingerprint",
    "PathIdentity",
    "ReceiptFingerprint",
    "StagedArtifact",
    "VerifiedDirectory",
    "artifact_sha256",
    "fingerprints_match",
    "modes_match",
    "stable_artifact_fingerprint",
]
