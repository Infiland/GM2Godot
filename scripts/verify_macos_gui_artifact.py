"""Verify every byte of a final Mac ZIP before a bounded native Cocoa smoke."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import ModuleType, TracebackType
from typing import Callable, Literal, Protocol, cast
import zipfile


APP_NAME = "GM2Godot.app"
MAIN_PATH = "Contents/MacOS/GM2Godot"
GUI_RECEIPT_ENV = "GM2GODOT_GUI_SMOKE_RECEIPT"
GUI_RECEIPT_BYTES = b"GM2Godot packaged GUI ready\n"
MAX_SOURCE_BYTES = 1024 * 1024
MAX_ZIP_BYTES = 1024 * 1024 * 1024
MAX_ZIP_READ_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 100_000
MAX_DEPTH = 128
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_LINK_BYTES = 16 * 1024
CHUNK_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_GROUP_MEMBERS = 4096
GUI_TIMEOUT_SECONDS = 60.0
DRAIN_TIMEOUT_SECONDS = 2.0
REAP_TIMEOUT_SECONDS = 3.0
SUPPORTED_ARCHITECTURES = frozenset({"arm64", "x86_64"})


class MacGuiVerificationError(ValueError):
    """A final-package or process-ownership failure blocks upload."""


class _Metadata(Protocol):
    @property
    def identifier(self) -> str: ...
    @property
    def short_version(self) -> str: ...
    @property
    def build_version(self) -> str: ...
    @property
    def minimum_system_version(self) -> str: ...
    @property
    def plist_sha256(self) -> str: ...


class _MachO(Protocol):
    @property
    def relative_path(self) -> str: ...
    @property
    def architecture(self) -> str: ...
    @property
    def minimum_macos(self) -> tuple[int, int, int]: ...
    @property
    def filetype(self) -> int: ...
    @property
    def mode(self) -> int: ...


class _Link(Protocol):
    @property
    def relative_path(self) -> str: ...
    @property
    def target(self) -> str: ...


class _Inventory(Protocol):
    @property
    def mach_o_files(self) -> tuple[_MachO, ...]: ...
    @property
    def symlinks(self) -> tuple[_Link, ...]: ...


class _Inspection(Protocol):
    @property
    def metadata(self) -> _Metadata: ...
    @property
    def inventory(self) -> _Inventory: ...


class _BundleVerifier(Protocol):
    def load_source_policy(self, source_root: Path) -> dict[str, str]: ...
    def inspect_zip_bundle(self, zip_path: Path, expected: Mapping[str, str], expected_architecture: str) -> _Inspection: ...
    def inspect_app_bundle(self, app_path: Path, expected: Mapping[str, str], expected_architecture: str) -> _Inspection: ...


class _Publisher(Protocol):
    def publish_identical_receipt_bytes(self, output: Path, payload: bytes) -> None: ...


class _OutputPipe(Protocol):
    def fileno(self) -> int: ...


@dataclass(frozen=True, order=True)
class TreeEntry:
    path: str
    kind: Literal["directory", "regular", "symlink"]
    mode: int | None
    size: int
    sha256: str | None
    target: str | None


@dataclass(frozen=True)
class ProcessReceipt:
    returncode: int
    output: bytes
    elapsed_seconds: float


@dataclass(frozen=True)
class ZipCopy:
    sha256: str
    source_stat: tuple[int, int, int, int, int, int, int]
    private_stat: tuple[int, int, int, int, int, int, int]


class _WaitidPrefix(ctypes.Structure):
    _fields_ = [("si_signo", ctypes.c_int32), ("si_errno", ctypes.c_int32), ("si_code", ctypes.c_int32), ("si_pid", ctypes.c_int32), ("si_uid", ctypes.c_uint32), ("si_status", ctypes.c_int32)]


def _note(primary: BaseException, label: str, error: BaseException) -> None:
    message = f"{label}: {type(error).__name__}: {error}"
    primary.add_note(message[:509] + "..." if len(message) > 512 else message)


def _close(fd: int, primary: BaseException | None = None) -> None:
    try:
        os.close(fd)
    except BaseException as error:
        if primary is None:
            raise
        _note(primary, "descriptor cleanup failed", error)


def _flags(*names: str) -> int:
    result = 0
    for name in names:
        value = getattr(os, name, None)
        if type(value) is not int:
            raise MacGuiVerificationError(f"required open flag {name} is unavailable")
        result |= value
    return result


def _seal(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _absolute(path: Path) -> Path:
    if not path.is_absolute() or any(part in {".", ".."} or "\x00" in part for part in path.parts):
        raise MacGuiVerificationError("an absolute physical path is required")
    return path


class BoundDirectory:
    """Retain physical ancestors; changing directory times do not change identity."""

    def __init__(self, path: Path) -> None:
        self.path = _absolute(path)
        self.bindings: list[tuple[int | None, str, int, int, int]] = []
        try:
            parent: int | None = None
            for name in (path.anchor, *path.parts[1:]):
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                fd = os.open(name, _flags("O_RDONLY", "O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"), dir_fd=parent)
                self.bindings.append((parent, name, fd, before.st_dev, before.st_ino))
                opened = os.fstat(fd)
                if not stat.S_ISDIR(before.st_mode) or not os.path.samestat(before, opened):
                    raise MacGuiVerificationError("physical directory changed while opening")
                parent = fd
            self.verify()
        except BaseException as error:
            self.close(error)
            raise

    @property
    def fd(self) -> int:
        return self.bindings[-1][2]

    def verify(self) -> None:
        for parent, name, fd, device, inode in self.bindings:
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            opened = os.fstat(fd)
            if not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != (device, inode) or not os.path.samestat(named, opened):
                raise MacGuiVerificationError("retained physical ancestry changed")

    def close(self, primary: BaseException | None = None) -> None:
        bindings, self.bindings = self.bindings, []
        first = primary
        for _parent, _name, fd, _device, _inode in reversed(bindings):
            try:
                _close(fd)
            except BaseException as error:
                if first is None:
                    first = error
                else:
                    _note(first, "directory cleanup failed", error)
        if primary is None and first is not None:
            raise first

    def __enter__(self) -> BoundDirectory:
        return self

    def __exit__(self, _kind: type[BaseException] | None, primary: BaseException | None, _traceback: TracebackType | None) -> Literal[False]:
        self.close(primary)
        return False


def _open_file(parent: BoundDirectory, name: str, maximum: int) -> tuple[int, os.stat_result]:
    parent.verify()
    before = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= maximum:
        raise MacGuiVerificationError("file is not a bounded, singly linked regular file")
    fd = os.open(name, _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"), dir_fd=parent.fd)
    try:
        if _seal(os.fstat(fd)) != _seal(before):
            raise MacGuiVerificationError("file changed while opening")
        return fd, before
    except BaseException as error:
        _close(fd, error)
        raise


def _verify_file(parent: BoundDirectory, name: str, fd: int, before: os.stat_result) -> None:
    parent.verify()
    if _seal(os.fstat(fd)) != _seal(before) or _seal(os.stat(name, dir_fd=parent.fd, follow_symlinks=False)) != _seal(before):
        raise MacGuiVerificationError("retained file changed")


def _read_exact_file(path: Path, maximum: int) -> bytes:
    with BoundDirectory(path.parent) as parent:
        fd, before = _open_file(parent, path.name, maximum)
        primary: BaseException | None = None
        try:
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(fd, min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise MacGuiVerificationError("retained file was truncated")
                remaining -= len(chunk)
                chunks.append(chunk)
            if os.read(fd, 1):
                raise MacGuiVerificationError("retained file grew")
            _verify_file(parent, path.name, fd, before)
            return b"".join(chunks)
        except BaseException as error:
            primary = error
            raise
        finally:
            _close(fd, primary)


def _load_sibling(name: str) -> ModuleType:
    path = Path(__file__).resolve().with_name(f"{name}.py")
    content = _read_exact_file(path, MAX_SOURCE_BYTES)
    module_name = f"_gm2godot_mac_gui__{name}"
    module = ModuleType(module_name)
    module.__file__ = str(path)
    prior = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        exec(compile(content, str(path), "exec"), module.__dict__)
    except BaseException:
        if prior is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = prior
        raise
    return module


def _bundle_verifier() -> _BundleVerifier:
    return cast(_BundleVerifier, _load_sibling("verify_macos_bundle_metadata"))


def publish_receipt(path: Path, value: Mapping[str, object]) -> None:
    payload = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    publisher = cast(_Publisher, _load_sibling("_anchored_output"))
    publisher.publish_identical_receipt_bytes(path, payload)


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise MacGuiVerificationError("file write made no progress")
        view = view[written:]


def copy_zip(source: Path, destination: Path) -> ZipCopy:
    if sys.platform == "win32":
        raise MacGuiVerificationError("private ZIP copying requires POSIX")
    with BoundDirectory(source.parent) as parent, BoundDirectory(destination.parent) as output:
        fd, before = _open_file(parent, source.name, MAX_ZIP_BYTES)
        target: int | None = None
        primary: BaseException | None = None
        try:
            if not before.st_size:
                raise MacGuiVerificationError("ZIP is empty")
            target = os.open(destination.name, _flags("O_RDWR", "O_CREAT", "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW"), 0o600, dir_fd=output.fd)
            created = os.fstat(target)
            os.fchmod(target, 0o600)
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                content = os.read(fd, min(CHUNK_BYTES, remaining))
                if not content:
                    raise MacGuiVerificationError("source ZIP was truncated")
                remaining -= len(content)
                digest.update(content)
                _write_all(target, content)
            if os.read(fd, 1):
                raise MacGuiVerificationError("source ZIP grew")
            _verify_file(parent, source.name, fd, before)
            os.fsync(target)
            sealed = os.fstat(target)
            if not os.path.samestat(created, sealed) or not stat.S_ISREG(sealed.st_mode) or sealed.st_nlink != 1 or stat.S_IMODE(sealed.st_mode) != 0o600 or sealed.st_size != before.st_size:
                raise MacGuiVerificationError("private ZIP creation binding changed")
            os.lseek(target, 0, os.SEEK_SET)
            private_digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                content = os.read(target, min(CHUNK_BYTES, remaining))
                if not content:
                    raise MacGuiVerificationError("private ZIP copy truncated")
                remaining -= len(content)
                private_digest.update(content)
            if os.read(target, 1) or private_digest.digest() != digest.digest():
                raise MacGuiVerificationError("private ZIP bytes differ from the copied source")
            _verify_file(output, destination.name, target, sealed)
            output.verify()
            return ZipCopy(digest.hexdigest(), _seal(before), _seal(sealed))
        except BaseException as error:
            primary = error
            raise
        finally:
            first = primary
            for item in (target, fd):
                if item is None:
                    continue
                try:
                    _close(item)
                except BaseException as error:
                    if first is None:
                        first = error
                    else:
                        _note(first, "ZIP copy cleanup failed", error)
            if primary is None and first is not None:
                raise first


class _ZipReader(io.RawIOBase):
    def __init__(self, fd: int, size: int) -> None:
        super().__init__()
        self.fd = fd
        self.size = size
        self.position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        origin = {os.SEEK_SET: 0, os.SEEK_CUR: self.position, os.SEEK_END: self.size}.get(whence)
        if origin is None or origin + offset < 0:
            raise MacGuiVerificationError("invalid ZIP seek")
        self.position = origin + offset
        return self.position

    def read(self, size: int = -1) -> bytes:
        if sys.platform == "win32":
            raise MacGuiVerificationError("retained ZIP reading requires POSIX")
        requested = self.size - self.position if size < 0 else size
        if requested > MAX_ZIP_READ_BYTES:
            raise MacGuiVerificationError("ZIP reader byte budget exceeded")
        count = min(max(0, self.size - self.position), requested)
        result = bytearray()
        while len(result) < count:
            content = os.pread(self.fd, min(CHUNK_BYTES, count - len(result)), self.position)
            if not content:
                raise MacGuiVerificationError("private ZIP was truncated")
            self.position += len(content)
            result.extend(content)
        return bytes(result)


def _entry_parts(path: str) -> tuple[str, ...]:
    parts = tuple(path.split("/"))
    if any(not part or part in {".", ".."} or "\\" in part or "\x00" in part for part in parts) or len(parts) > MAX_DEPTH:
        raise MacGuiVerificationError("unsafe canonical App member path")
    return parts


def _parent_fd(root: BoundDirectory, parts: Sequence[str]) -> tuple[int, list[int]]:
    fd = root.fd
    opened: list[int] = []
    try:
        for name in parts:
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            child = os.open(name, _flags("O_RDONLY", "O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC"), dir_fd=fd)
            opened.append(child)
            if not stat.S_ISDIR(before.st_mode) or not os.path.samestat(before, os.fstat(child)):
                raise MacGuiVerificationError("extraction directory changed")
            fd = child
        root.verify()
        return fd, opened
    except BaseException as error:
        for child in reversed(opened):
            _close(child, error)
        raise


def _close_many(opened: Sequence[int], primary: BaseException | None) -> None:
    first = primary
    for fd in reversed(opened):
        try:
            _close(fd)
        except BaseException as error:
            if first is None:
                first = error
            else:
                _note(first, "extracted directory cleanup failed", error)
    if primary is None and first is not None:
        raise first


def extract_transcript(
    private_zip: Path, app: Path, expected: Mapping[str, str], architecture: str
) -> tuple[TreeEntry, ...]:
    """Every regular resource is read fully, CRC checked and exclusively written."""
    if sys.platform == "win32":
        raise MacGuiVerificationError("private App extraction requires POSIX")
    _bundle_verifier().inspect_zip_bundle(private_zip, expected, architecture)
    with BoundDirectory(private_zip.parent) as parent:
        fd, before = _open_file(parent, private_zip.name, MAX_ZIP_BYTES)
        primary: BaseException | None = None
        try:
            with _ZipReader(fd, before.st_size) as reader, zipfile.ZipFile(reader) as archive:
                members = archive.infolist()
                if len(members) > MAX_ENTRIES:
                    raise MacGuiVerificationError("ZIP member count budget exceeded")
                directories: dict[str, int] = {"": 0o755}
                selected: list[tuple[zipfile.ZipInfo, str, Literal["regular", "symlink"]]] = []
                total = 0
                for member in members:
                    name = member.orig_filename.rstrip("/")
                    if member.filename != member.orig_filename or "\x00" in name:
                        raise MacGuiVerificationError("ZIP contains a truncated member name")
                    parts = _entry_parts(name)
                    if parts[0].casefold() == APP_NAME.casefold() and parts[0] != APP_NAME:
                        raise MacGuiVerificationError("ZIP App root is not canonical")
                    mode = (member.external_attr >> 16) & 0xFFFF
                    kind = stat.S_IFMT(mode)
                    if member.create_system != 3 or member.flag_bits & 1 or mode & 0o7000:
                        raise MacGuiVerificationError("ZIP App mode/type/encryption is unsafe")
                    if parts[0] != APP_NAME:
                        # Extras are validated and CRC-read, never materialized.
                        # 7z includes README.md; ditto may include AppleDouble.
                        allowed_readme = parts == ("README.md",) and kind == stat.S_IFREG
                        allowed_appledouble = parts[0] == "__MACOSX" and (kind == stat.S_IFDIR or (kind == stat.S_IFREG and parts[-1].startswith("._") and len(parts[-1]) > 2))
                        if not (allowed_readme or allowed_appledouble) or not 0 <= member.file_size <= MAX_FILE_BYTES or (kind == stat.S_IFDIR and (not member.is_dir() or member.file_size)):
                            raise MacGuiVerificationError("ZIP contains an unsupported extra member")
                        total += member.file_size
                        if total > MAX_TOTAL_BYTES:
                            raise MacGuiVerificationError("ZIP total inflated byte budget exceeded")
                        with archive.open(member) as stream:
                            remaining = member.file_size
                            while remaining:
                                content = stream.read(min(CHUNK_BYTES, remaining))
                                if not content:
                                    raise MacGuiVerificationError("ZIP extra member was truncated")
                                remaining -= len(content)
                            if stream.read(1):
                                raise MacGuiVerificationError("ZIP extra member exceeds its declared size")
                        continue
                    relative = "/".join(parts[1:])
                    for depth in range(1, len(parts)):
                        directories.setdefault("/".join(parts[1:depth]), 0o755)
                    if kind == stat.S_IFDIR:
                        if not member.is_dir() or member.file_size:
                            raise MacGuiVerificationError("ZIP directory record is invalid")
                        directories[relative] = stat.S_IMODE(mode)
                    elif kind in {stat.S_IFREG, stat.S_IFLNK} and relative and not member.is_dir():
                        maximum = MAX_FILE_BYTES if kind == stat.S_IFREG else MAX_LINK_BYTES
                        if not 0 <= member.file_size <= maximum:
                            raise MacGuiVerificationError("ZIP member byte budget exceeded")
                        total += member.file_size
                        if total > MAX_TOTAL_BYTES:
                            raise MacGuiVerificationError("ZIP total inflated byte budget exceeded")
                        selected.append((member, relative, "regular" if kind == stat.S_IFREG else "symlink"))
                    else:
                        raise MacGuiVerificationError("ZIP App member type is unsupported")
                if len(directories) + len(selected) > MAX_ENTRIES:
                    raise MacGuiVerificationError("inferred App entry count budget exceeded")
                app.mkdir(mode=0o700)
                rows: list[TreeEntry] = []
                with BoundDirectory(app) as root:
                    for path in sorted(directories, key=lambda item: (item.count("/"), item)):
                        if path:
                            parts = _entry_parts(path)
                            directory, opened = _parent_fd(root, parts[:-1])
                            try:
                                os.mkdir(parts[-1], 0o700, dir_fd=directory)
                            except BaseException as error:
                                _close_many(opened, error)
                                raise
                            _close_many(opened, None)
                        rows.append(TreeEntry(path, "directory", directories[path], 0, None, None))
                    pending_links: list[tuple[str, str]] = []
                    for member, path, kind in selected:
                        parts = _entry_parts(path)
                        directory, opened = _parent_fd(root, parts[:-1])
                        target_fd: int | None = None
                        current: BaseException | None = None
                        try:
                            if kind == "regular":
                                target_fd = os.open(parts[-1], _flags("O_WRONLY", "O_CREAT", "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW"), 0o600, dir_fd=directory)
                            digest = hashlib.sha256()
                            link_bytes = bytearray()
                            with archive.open(member) as stream:
                                remaining = member.file_size
                                while remaining:
                                    content = stream.read(min(CHUNK_BYTES, remaining))
                                    if not content:
                                        raise MacGuiVerificationError("ZIP member was truncated")
                                    remaining -= len(content)
                                    digest.update(content)
                                    if target_fd is not None:
                                        _write_all(target_fd, content)
                                    else:
                                        link_bytes.extend(content)
                                if stream.read(1):
                                    raise MacGuiVerificationError("ZIP member exceeds its declared size")
                            if target_fd is not None:
                                mode = stat.S_IMODE((member.external_attr >> 16) & 0xFFFF)
                                os.fchmod(target_fd, mode)
                                os.fsync(target_fd)
                                rows.append(TreeEntry(path, kind, mode, member.file_size, digest.hexdigest(), None))
                            else:
                                target = bytes(link_bytes).decode("utf-8", errors="strict")
                                pending_links.append((path, target))
                                rows.append(TreeEntry(path, kind, None, member.file_size, None, target))
                        except BaseException as error:
                            current = error
                            raise
                        finally:
                            if target_fd is not None:
                                try:
                                    _close(target_fd)
                                except BaseException as error:
                                    if current is None:
                                        current = error
                                    else:
                                        _note(current, "extracted file close failed", error)
                            _close_many(opened, current)
                            if current is not None and sys.exception() is None:
                                raise current
                    for path, target in pending_links:
                        parts = _entry_parts(path)
                        directory, opened = _parent_fd(root, parts[:-1])
                        try:
                            os.symlink(target, parts[-1], dir_fd=directory)
                        except BaseException as error:
                            _close_many(opened, error)
                            raise
                        _close_many(opened, None)
                    for path in sorted(directories, key=lambda item: (-item.count("/"), item), reverse=False):
                        parts = _entry_parts(path) if path else ()
                        directory, opened = _parent_fd(root, parts)
                        try:
                            os.fchmod(directory, directories[path])
                        except BaseException as error:
                            _close_many(opened, error)
                            raise
                        _close_many(opened, None)
                    root.verify()
                _verify_file(parent, private_zip.name, fd, before)
                return tuple(sorted(rows))
        except BaseException as error:
            primary = error
            raise
        finally:
            _close(fd, primary)


def inspect_tree(app: Path) -> tuple[TreeEntry, ...]:
    """Independently inspect all physical entries without following links."""
    rows: list[TreeEntry] = []
    total = 0
    with BoundDirectory(app) as root:
        def visit(fd: int, prefix: str, depth: int) -> None:
            nonlocal total
            if depth > MAX_DEPTH or len(rows) > MAX_ENTRIES:
                raise MacGuiVerificationError("physical tree count/depth budget exceeded")
            own = os.fstat(fd)
            rows.append(TreeEntry(prefix, "directory", stat.S_IMODE(own.st_mode), 0, None, None))
            names = sorted(os.listdir(fd))
            for name in names:
                _entry_parts(name)
                path = f"{prefix}/{name}" if prefix else name
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(before.st_mode):
                    target = os.readlink(name, dir_fd=fd)
                    if _seal(os.stat(name, dir_fd=fd, follow_symlinks=False)) != _seal(before):
                        raise MacGuiVerificationError("physical symlink changed")
                    rows.append(TreeEntry(path, "symlink", None, len(target.encode("utf-8")), None, target))
                    continue
                child = os.open(name, _flags("O_RDONLY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK"), dir_fd=fd)
                primary: BaseException | None = None
                try:
                    opened = os.fstat(child)
                    if _seal(opened) != _seal(before):
                        raise MacGuiVerificationError("physical tree entry changed while opening")
                    if stat.S_ISDIR(opened.st_mode):
                        if opened.st_dev != own.st_dev:
                            raise MacGuiVerificationError("physical tree crosses a filesystem")
                        visit(child, path, depth + 1)
                    elif stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size <= MAX_FILE_BYTES:
                        digest = hashlib.sha256()
                        remaining = opened.st_size
                        total += remaining
                        if total > MAX_TOTAL_BYTES:
                            raise MacGuiVerificationError("physical tree total byte budget exceeded")
                        while remaining:
                            content = os.read(child, min(CHUNK_BYTES, remaining))
                            if not content:
                                raise MacGuiVerificationError("physical resource truncated")
                            remaining -= len(content)
                            digest.update(content)
                        if os.read(child, 1):
                            raise MacGuiVerificationError("physical resource grew")
                        rows.append(TreeEntry(path, "regular", stat.S_IMODE(opened.st_mode), opened.st_size, digest.hexdigest(), None))
                    else:
                        raise MacGuiVerificationError("physical tree contains a special or linked file")
                    if _seal(os.fstat(child)) != _seal(opened) or _seal(os.stat(name, dir_fd=fd, follow_symlinks=False)) != _seal(before):
                        raise MacGuiVerificationError("physical tree entry changed while reading")
                except BaseException as error:
                    primary = error
                    raise
                finally:
                    _close(child, primary)
            if names != sorted(os.listdir(fd)) or _seal(os.fstat(fd)) != _seal(own):
                raise MacGuiVerificationError("physical directory changed during traversal")
        visit(root.fd, "", 0)
        root.verify()
    if len(rows) > MAX_ENTRIES:
        raise MacGuiVerificationError("physical tree count budget exceeded")
    return tuple(sorted(rows))


def _libc() -> ctypes.CDLL:
    if sys.platform != "darwin" or ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(ctypes.c_long) != 8:
        raise MacGuiVerificationError("Darwin LP64 native APIs are required")
    return ctypes.CDLL(None, use_errno=True)


def _translation_status() -> bool:
    library = _libc()
    function = library.sysctlbyname
    function.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
    function.restype = ctypes.c_int
    value = ctypes.c_int(-1)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    ctypes.set_errno(0)
    result = function(b"sysctl.proc_translated", ctypes.byref(value), ctypes.byref(size), None, 0)
    failure = ctypes.get_errno()
    if result == -1 and failure == errno.ENOENT:
        return False
    if result != 0 or size.value != ctypes.sizeof(value) or value.value not in {0, 1}:
        raise MacGuiVerificationError(f"native translation status is unavailable or malformed (errno {failure})")
    return bool(value.value)


def require_native_runtime(architecture: str, *, pinned_python: bool = True) -> dict[str, object]:
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise MacGuiVerificationError("unsupported native architecture")
    observed = (platform.python_implementation(), platform.python_version(), sys.platform, platform.system(), platform.machine())
    if observed[0] != "CPython" or observed[2:] != ("darwin", "Darwin", architecture) or (pinned_python and observed[1] != "3.12.10"):
        raise MacGuiVerificationError(f"unexpected native runtime {observed!r}")
    if _translation_status():
        raise MacGuiVerificationError("Rosetta translation is not a native build or GUI proof")
    return {"implementation": observed[0], "python_version": observed[1], "platform": observed[2], "system": observed[3], "machine": observed[4], "translated": False}


def _waitid_options() -> tuple[int, int]:
    values: list[int] = []
    for name, expected in (("P_PID", 1), ("WNOHANG", 1), ("WEXITED", 4), ("WNOWAIT", 32)):
        value = getattr(os, name, None)
        if type(value) is not int or value != expected:
            raise MacGuiVerificationError(f"Darwin waitid constant {name} is unavailable or unexpected")
        values.append(value)
    return values[0], values[1] | values[2] | values[3]


def _require_default_sigchld() -> None:
    if sys.platform != "darwin" or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise ChildProcessError("private child ownership requires Darwin default SIGCHLD handling")


def _waitid_api() -> tuple[Callable[[int, int, object, int], int], int, int]:
    kind, options = _waitid_options()
    # Apple SDK LP64 siginfo_t is 104 bytes, aligned to 8. Return/errno prove
    # ownership; only its validated six-field prefix proves a terminal exit.
    storage_type = ctypes.c_uint64 * 13
    if ctypes.sizeof(storage_type) != 104 or ctypes.alignment(storage_type) != 8 or ctypes.sizeof(ctypes.c_int) != 4 or ctypes.sizeof(ctypes.c_uint32) != 4 or ctypes.sizeof(_WaitidPrefix) != 24 or ctypes.alignment(_WaitidPrefix) != 4 or _WaitidPrefix.si_signo.offset != 0 or _WaitidPrefix.si_code.offset != 8 or _WaitidPrefix.si_pid.offset != 12:
        raise MacGuiVerificationError("unexpected Darwin waitid ABI")
    function = _libc().waitid
    function.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(storage_type), ctypes.c_int]
    function.restype = ctypes.c_int
    return cast(Callable[[int, int, object, int], int], function), kind, options


def _waitid_record(pid: int) -> bytes:
    _require_default_sigchld()
    if not 0 < pid <= 0xFFFFFFFF:
        raise MacGuiVerificationError("invalid owned child PID")
    function, kind, options = _waitid_api()
    storage_type = ctypes.c_uint64 * 13
    storage = storage_type()
    ctypes.set_errno(0)
    result = function(kind, pid, ctypes.byref(storage), options)
    failure = ctypes.get_errno()
    if result != 0:
        raise OSError(failure or errno.EIO, os.strerror(failure or errno.EIO))
    return bytes(storage)


def _prove_child(pid: int) -> None:
    _waitid_record(pid)


def _prove_process(process: subprocess.Popen[bytes]) -> None:
    if process.returncode is not None:
        raise ChildProcessError("the private child has already been reaped")
    _prove_child(process.pid)


def _positive_child_exit(process: subprocess.Popen[bytes]) -> bool:
    if sys.platform != "darwin":
        raise MacGuiVerificationError("native exit records require Darwin")
    if process.returncode is not None:
        raise ChildProcessError("the private child has already been reaped")
    record = _waitid_record(process.pid)
    # Apple SDK sys/signal.h siginfo_t begins with six 32-bit fields;
    # si_signo/si_code/si_pid offsets are 0/8/12 within the aligned104B record.
    # WNOWAIT preserves the owned leader while identifying a terminal event.
    if len(record) != 104 or ctypes.sizeof(_WaitidPrefix) != 24 or ctypes.alignment(_WaitidPrefix) != 4 or _WaitidPrefix.si_signo.offset != 0 or _WaitidPrefix.si_code.offset != 8 or _WaitidPrefix.si_pid.offset != 12:
        raise MacGuiVerificationError("unexpected Darwin exit-record prefix ABI")
    codes: set[int] = set()
    for name, expected in (("CLD_EXITED", 1), ("CLD_KILLED", 2), ("CLD_DUMPED", 3)):
        value = getattr(os, name, None)
        if type(value) is not int or value != expected:
            raise MacGuiVerificationError(f"Darwin exit code {name} is unavailable or unexpected")
        codes.add(value)
    signo = int.from_bytes(record[0:4], sys.byteorder, signed=True)
    code = int.from_bytes(record[8:12], sys.byteorder, signed=True)
    pid = int.from_bytes(record[12:16], sys.byteorder, signed=True)
    if pid == 0 and not any(record):
        return False
    if pid != process.pid or signo != signal.SIGCHLD or code not in codes:
        raise MacGuiVerificationError("Darwin non-reaping wait returned an unexpected exit record")
    return True


def _group_census_api() -> Callable[[int, int, object, int], int]:
    # SDK libproc.h/proc_info.h: PROC_PGRP_ONLY=2, uint32 selectors,
    # int-sized PID rows. XNU lists both live and zombie group members.
    function = _libc().proc_listpids
    function.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    return cast(Callable[[int, int, object, int], int], function)


def _group_contains_only_exited_leader(process: subprocess.Popen[bytes]) -> bool:
    _prove_process(process)
    if not _positive_child_exit(process):
        return False
    function = _group_census_api()
    for _ in range(2):
        _prove_process(process)
        if not _positive_child_exit(process):
            return False
        buffer = (ctypes.c_int32 * (MAX_GROUP_MEMBERS + 1))()
        capacity = ctypes.sizeof(buffer)
        ctypes.set_errno(0)
        count = function(2, process.pid, ctypes.byref(buffer), capacity)
        failure = ctypes.get_errno()
        if failure or count <= 0 or count >= capacity or count % ctypes.sizeof(ctypes.c_int32):
            raise MacGuiVerificationError(f"Darwin group census failed or exceeded its budget (bytes {count}, errno {failure})")
        members = tuple(buffer[index] for index in range(count // ctypes.sizeof(ctypes.c_int32)))
        if members != (process.pid,):
            return False
        _prove_process(process)
        if not _positive_child_exit(process):
            return False
    return True


def _read_output(stream: _OutputPipe, output: bytearray) -> bool:
    while True:
        try:
            content = os.read(stream.fileno(), min(64 * 1024, MAX_OUTPUT_BYTES + 1 - len(output)))
        except BlockingIOError:
            return False
        if not content:
            return True
        output.extend(content)
        if len(output) > MAX_OUTPUT_BYTES:
            raise MacGuiVerificationError("packaged GUI output exceeds its byte budget")


def _observe_exit(process: subprocess.Popen[bytes], stream: _OutputPipe, output: bytearray, deadline: float) -> bool:
    if sys.platform != "darwin":
        raise MacGuiVerificationError("native exit observation requires Darwin")
    queue = select.kqueue()
    primary: BaseException | None = None
    eof = False
    try:
        change = select.kevent(process.pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
        try:
            queue.control([change], 0, 0)
        except OSError as error:
            if error.errno != errno.ESRCH:
                raise
            _prove_process(process)
            return _read_output(stream, output)
        while True:
            eof = _read_output(stream, output) or eof
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MacGuiVerificationError("packaged GUI exceeded its runtime deadline")
            events = queue.control(None, 1, min(0.05, remaining))
            if events:
                event = events[0]
                if event.flags & select.KQ_EV_ERROR:
                    raise OSError(event.data, "native exit observer rejected the child")
                if event.ident != process.pid or not event.fflags & select.KQ_NOTE_EXIT:
                    raise MacGuiVerificationError("native exit observer returned an unexpected event")
                _prove_process(process)
                return _read_output(stream, output) or eof
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            queue.close()
        except BaseException as error:
            if primary is None:
                raise
            _note(primary, "native exit observer close failed", error)


def _drain_output(stream: _OutputPipe, output: bytearray, *, timeout: float = DRAIN_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while not _read_output(stream, output):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MacGuiVerificationError("inherited GUI stdout did not reach EOF within its drain deadline")
        select.select([stream], [], [], min(0.05, remaining))


def _group_signal(process: subprocess.Popen[bytes]) -> None:
    if sys.platform != "darwin":
        raise MacGuiVerificationError("native group signaling requires Darwin")
    _prove_process(process)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        # XNU killpg excludes zombies and returns EPERM for a zombie-only
        # group. Accept only a positive exited-leader record and exact census;
        # EOF or a reserved PID alone cannot excuse inaccessible live members.
        if error.errno != errno.EPERM or not _group_contains_only_exited_leader(process):
            raise


def _direct_signal(process: subprocess.Popen[bytes]) -> None:
    if sys.platform != "darwin":
        raise MacGuiVerificationError("native child signaling requires Darwin")
    _prove_process(process)
    try:
        os.kill(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_gui_process(command: Sequence[str], root: Path, environment: Mapping[str, str], *, timeout: float = GUI_TIMEOUT_SECONDS) -> ProcessReceipt:
    """Own one private session; no reaping occurs before its final group signal."""
    if not 0 < timeout <= GUI_TIMEOUT_SECONDS:
        raise MacGuiVerificationError("invalid GUI runtime deadline")
    _require_default_sigchld()
    _waitid_api()  # Validate ABI and availability before acquiring a child.
    _group_census_api()
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    output = bytearray()
    primary: BaseException | None = None
    errors: list[BaseException] = []
    returncode: int | None = None
    try:
        process = subprocess.Popen(list(command), cwd=root, env=dict(environment), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, close_fds=True, start_new_session=True)
        if process.stdout is None:
            raise MacGuiVerificationError("packaged GUI has no owned output pipe")
        os.set_blocking(process.stdout.fileno(), False)
        eof = _observe_exit(process, process.stdout, output, started + timeout)
        if not eof:
            _drain_output(process.stdout, output)
    except BaseException as error:
        primary = error
    finally:
        if process is not None:
            group_error: BaseException | None = None
            try:
                _group_signal(process)
            except BaseException as error:
                group_error = error
                errors.append(error)
            # This is the last group-signal attempt. A direct fallback can no
            # longer invalidate a PID that will subsequently be used as a PGID.
            if group_error is not None and not isinstance(group_error, ChildProcessError):
                try:
                    _direct_signal(process)
                except BaseException as error:
                    errors.append(error)
            try:
                _prove_process(process)
            except BaseException as error:
                errors.append(error)
            try:
                returncode = process.wait(timeout=REAP_TIMEOUT_SECONDS)
            except BaseException as error:
                errors.append(error)
            if process.stdout is not None:
                try:
                    _drain_output(process.stdout, output)
                except BaseException as error:
                    errors.append(error)
                try:
                    process.stdout.close()
                except BaseException as error:
                    errors.append(error)
    if primary is None and errors:
        primary = errors.pop(0)
    if primary is not None:
        for error in errors:
            _note(primary, "GUI process cleanup failed", error)
        if output:
            primary.add_note("captured GUI output: " + ascii(bytes(output[:256]))[:480])
        raise primary
    if returncode != 0:
        raise MacGuiVerificationError(f"packaged GUI exited with status {returncode}")
    return ProcessReceipt(0, bytes(output), time.monotonic() - started)


def gui_environment(root: Path, receipt: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for key in tuple(environment):
        if key.startswith(("DYLD_", "PYTHON", "QT_")) or key == GUI_RECEIPT_ENV:
            environment.pop(key)
    for name in ("home", "config", "cache", "data", "tmp"):
        (root / name).mkdir(mode=0o700)
    environment.update({"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"), "XDG_DATA_HOME": str(root / "data"), "TMPDIR": str(root / "tmp"), GUI_RECEIPT_ENV: str(receipt)})
    return environment


def validate_gui_receipt(path: Path) -> str:
    with BoundDirectory(path.parent) as parent:
        fd, before = _open_file(parent, path.name, len(GUI_RECEIPT_BYTES))
        primary: BaseException | None = None
        try:
            if stat.S_IMODE(before.st_mode) != 0o600:
                raise MacGuiVerificationError("GUI receipt mode is not 0600")
            content = os.read(fd, len(GUI_RECEIPT_BYTES) + 1)
            if content != GUI_RECEIPT_BYTES:
                raise MacGuiVerificationError("GUI receipt bytes are not exact")
            _verify_file(parent, path.name, fd, before)
            return hashlib.sha256(content).hexdigest()
        except BaseException as error:
            primary = error
            raise
        finally:
            _close(fd, primary)


def _remove_contents(fd: int, device: int, depth: int = 0) -> None:
    if sys.platform == "win32":
        raise MacGuiVerificationError("private directory cleanup requires POSIX")
    if depth > MAX_DEPTH:
        raise MacGuiVerificationError("private cleanup depth budget exceeded")
    for name in os.listdir(fd):
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(before.st_mode):
            if before.st_dev != device:
                raise MacGuiVerificationError("private cleanup crosses a filesystem")
            child = os.open(name, _flags("O_RDONLY", "O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC"), dir_fd=fd)
            primary: BaseException | None = None
            try:
                if not os.path.samestat(before, os.fstat(child)):
                    raise MacGuiVerificationError("private cleanup directory changed")
                os.fchmod(child, stat.S_IMODE(before.st_mode) | 0o700)
                _remove_contents(child, device, depth + 1)
                if not os.path.samestat(before, os.stat(name, dir_fd=fd, follow_symlinks=False)):
                    raise MacGuiVerificationError("private cleanup directory moved")
                os.rmdir(name, dir_fd=fd)
            except BaseException as error:
                primary = error
                raise
            finally:
                _close(child, primary)
        else:
            os.unlink(name, dir_fd=fd)


def _cleanup_private_root(owner: BoundDirectory) -> None:
    if sys.platform == "win32":
        raise MacGuiVerificationError("private root cleanup requires POSIX")
    owner.verify()
    own = os.fstat(owner.fd)
    os.fchmod(owner.fd, stat.S_IMODE(own.st_mode) | 0o700)
    _remove_contents(owner.fd, own.st_dev)
    owner.verify()
    parent, name, _fd, _device, _inode = owner.bindings[-1]
    if parent is None:
        raise MacGuiVerificationError("private cleanup has no owned parent")
    os.rmdir(name, dir_fd=parent)


def _cleanup_unopened_root(path: Path, created: os.stat_result) -> None:
    with BoundDirectory(path.parent) as parent:
        named = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
        if not stat.S_ISDIR(named.st_mode) or not os.path.samestat(created, named):
            raise MacGuiVerificationError("new private root binding changed; replacement is retained")
        os.rmdir(path.name, dir_fd=parent.fd)


def _inspection_value(inspection: _Inspection) -> dict[str, object]:
    metadata = inspection.metadata
    return {"metadata": {"identifier": metadata.identifier, "short_version": metadata.short_version, "build_version": metadata.build_version, "minimum_system_version": metadata.minimum_system_version, "plist_sha256": metadata.plist_sha256}, "mach_o_files": [{"path": item.relative_path, "architecture": item.architecture, "minimum_macos": list(item.minimum_macos), "filetype": item.filetype, "mode": item.mode} for item in inspection.inventory.mach_o_files], "symlinks": [{"path": item.relative_path, "target": item.target} for item in inspection.inventory.symlinks]}


def verify_archive(source_root: Path, zip_path: Path, expected_architecture: str) -> dict[str, object]:
    runtime = require_native_runtime(expected_architecture)
    source_root, zip_path = _absolute(source_root), _absolute(zip_path)
    if zip_path.name != f"GM2Godot-macos-{expected_architecture}.zip":
        raise MacGuiVerificationError("final ZIP name does not match its native architecture")
    verifier = _bundle_verifier()
    policy = verifier.load_source_policy(source_root)
    source_owner: BoundDirectory | None = None
    owner: BoundDirectory | None = None
    private: Path | None = None
    created_root: os.stat_result | None = None
    primary: BaseException | None = None
    try:
        source_owner = BoundDirectory(zip_path.parent)
        original_source = os.stat(zip_path.name, dir_fd=source_owner.fd, follow_symlinks=False)
        raw_private = Path(tempfile.mkdtemp(prefix="gm2godot-macos-gui-"))
        # Resolve the pre-existing parent only, never a replaceable new leaf.
        private = raw_private.parent.resolve() / raw_private.name
        created_root = os.stat(private, follow_symlinks=False)
        if not stat.S_ISDIR(created_root.st_mode) or stat.S_IMODE(created_root.st_mode) != 0o700:
            raise MacGuiVerificationError("new private root is not an owned physical 0700 directory")
        owner = BoundDirectory(private)
        if not os.path.samestat(created_root, os.fstat(owner.fd)):
            # This owner pins a replacement; never recurse into that namespace.
            wrong_owner, owner = owner, None
            changed = MacGuiVerificationError("new private root changed during acquisition")
            wrong_owner.close(changed)
            raise changed
        private_zip = private / "package.zip"
        copied = copy_zip(zip_path, private_zip)
        zip_sha = copied.sha256
        source_owner.verify()
        if _seal(os.stat(zip_path.name, dir_fd=source_owner.fd, follow_symlinks=False)) != _seal(original_source):
            raise MacGuiVerificationError("source ZIP binding changed during copy")
        private_before = os.stat(private_zip.name, dir_fd=owner.fd, follow_symlinks=False)
        if _seal(private_before) != copied.private_stat or copied.source_stat != _seal(original_source):
            raise MacGuiVerificationError("sealed original/private ZIP binding changed before inspection")
        inspection = verifier.inspect_zip_bundle(private_zip, policy, expected_architecture)
        app = private / APP_NAME
        transcript = extract_transcript(private_zip, app, policy, expected_architecture)
        if transcript != inspect_tree(app):
            raise MacGuiVerificationError("extracted App full resource transcript differs from the final ZIP")
        native = verifier.inspect_app_bundle(app, policy, expected_architecture)
        if _inspection_value(inspection) != _inspection_value(native):
            raise MacGuiVerificationError("extracted App metadata/native inventory differs from the final ZIP")
        receipt = private / "gui-ready.receipt"
        environment = gui_environment(private, receipt)
        if receipt.exists() or receipt.is_symlink():
            raise MacGuiVerificationError("GUI receipt path is not fresh")
        executable = app / MAIN_PATH
        executable_sha = next(item.sha256 for item in transcript if item.path == MAIN_PATH)
        with BoundDirectory(executable.parent) as executable_parent:
            executable_fd, before = _open_file(executable_parent, executable.name, MAX_FILE_BYTES)
            current: BaseException | None = None
            try:
                if not before.st_mode & stat.S_IXUSR:
                    raise MacGuiVerificationError("packaged main executable is not executable")
                process = run_gui_process([str(executable)], private, environment)
                _verify_file(executable_parent, executable.name, executable_fd, before)
            except BaseException as error:
                current = error
                raise
            finally:
                _close(executable_fd, current)
        receipt_sha = validate_gui_receipt(receipt)
        if transcript != inspect_tree(app):
            raise MacGuiVerificationError("extracted App resources changed during GUI execution")
        if _seal(os.stat(private_zip.name, dir_fd=owner.fd, follow_symlinks=False)) != _seal(private_before):
            raise MacGuiVerificationError("private ZIP binding changed during verification")
        source_owner.verify()
        if _seal(os.stat(zip_path.name, dir_fd=source_owner.fd, follow_symlinks=False)) != _seal(original_source):
            raise MacGuiVerificationError("source ZIP binding changed during smoke")
        source_digest = hashlib.sha256()
        with BoundDirectory(zip_path.parent) as source_parent:
            source_fd, source_before = _open_file(source_parent, zip_path.name, MAX_ZIP_BYTES)
            current = None
            try:
                if _seal(source_before) != _seal(original_source):
                    raise MacGuiVerificationError("source ZIP final reopened binding differs from its original seal")
                remaining = source_before.st_size
                while remaining:
                    content = os.read(source_fd, min(CHUNK_BYTES, remaining))
                    if not content:
                        raise MacGuiVerificationError("source ZIP truncated after smoke")
                    remaining -= len(content)
                    source_digest.update(content)
                if os.read(source_fd, 1):
                    raise MacGuiVerificationError("source ZIP grew after smoke")
                _verify_file(source_parent, zip_path.name, source_fd, source_before)
            except BaseException as error:
                current = error
                raise
            finally:
                _close(source_fd, current)
        if source_digest.hexdigest() != zip_sha:
            raise MacGuiVerificationError("source ZIP bytes changed during smoke")
        return {"schema_version": 1, "successful": True, "runtime": runtime, "zip_path": str(zip_path), "zip_sha256": zip_sha, "zip_stat": list(_seal(original_source)), "source_policy": policy, "bundle": _inspection_value(native), "transcript": [{"path": row.path, "kind": row.kind, "mode": row.mode, "size": row.size, "sha256": row.sha256, "target": row.target} for row in transcript], "gui": {"returncode": process.returncode, "elapsed_seconds": process.elapsed_seconds, "receipt_sha256": receipt_sha, "receipt_mode": 0o600, "receipt_nlink": 1, "exact_receipt": True, "executable_sha256": executable_sha, "output_sha256": hashlib.sha256(process.output).hexdigest(), "output_bytes": len(process.output), "cleanup_successful": True}, "source_app_gui_tested": False, "dmg_gui_tested": False}
    except BaseException as error:
        primary = error
        raise
    finally:
        first = primary
        try:
            if owner is not None:
                _cleanup_private_root(owner)
            elif private is not None and created_root is not None:
                _cleanup_unopened_root(private, created_root)
        except BaseException as error:
            if first is None:
                first = error
            else:
                _note(first, "private App cleanup failed", error)
        try:
            if owner is not None:
                owner.close()
        except BaseException as error:
            if first is None:
                first = error
            else:
                _note(first, "private root descriptor cleanup failed", error)
        try:
            if source_owner is not None:
                source_owner.close()
        except BaseException as error:
            if first is None:
                first = error
            else:
                _note(first, "source ZIP ancestry cleanup failed", error)
        if primary is None and first is not None:
            raise first


def report_failure(error: BaseException) -> None:
    print("macOS final-ZIP verification failed: " + ascii(f"{type(error).__name__}: {error}")[:512], file=sys.stderr)
    for note in getattr(error, "__notes__", ())[:8]:
        print("cleanup detail: " + ascii(note)[:512], file=sys.stderr)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-architecture", required=True, choices=sorted(SUPPORTED_ARCHITECTURES))
    parser.add_argument("--check-native-runtime", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    try:
        if args.check_native_runtime:
            if args.source_root is not None or args.zip is not None or args.output is not None:
                raise MacGuiVerificationError("runtime-only mode does not accept artifact/output paths")
            print(json.dumps(require_native_runtime(args.expected_architecture), sort_keys=True))
        else:
            if args.source_root is None or args.zip is None or args.output is None:
                raise MacGuiVerificationError("source-root, zip and output are required")
            receipt = verify_archive(args.source_root, args.zip, args.expected_architecture)
            publish_receipt(_absolute(args.output), receipt)
            print(json.dumps({"successful": True, "zip_sha256": receipt["zip_sha256"], "architecture": args.expected_architecture, "output": str(args.output), "output_sha256": hashlib.sha256(_read_exact_file(args.output, 64 * 1024 * 1024)).hexdigest()}, sort_keys=True))
        return 0
    except BaseException as error:
        report_failure(error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
