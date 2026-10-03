"""Produce native wheel proposal evidence; never publish production locks.

Run directly with ``python -I``. Public Packaging is loaded only by a verified
generator's observation child. Existing repository policy helpers are loaded
from exact sibling files, without modifying the import path.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
import ctypes
from dataclasses import dataclass
from email.parser import BytesParser
from email.message import Message
import hashlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Protocol, cast
import zipfile

MAX_TEXT_BYTES = 1_048_576
MAX_COMMAND_SECONDS = 900
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
GIT_SELECTORS = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE", "GIT_PREFIX",
})


class ProposalError(ValueError):
    """A proposal failed its source, native, or execution contract."""


@dataclass(frozen=True)
class NativeHost:
    python: str
    sys_platform: str
    os_name: str
    system: str
    machine: str
    seed: str
    companion: str
    venv_python: str


HOSTS: Mapping[str, NativeHost] = {
    "linux-x64": NativeHost("3.12.13", "linux", "posix", "Linux", "x86_64", "constraints/requirements-linux-py312.lock", "constraints/requirements-linux-x64-py312.wheels.lock", "bin/python"),
    "macos-arm64": NativeHost("3.12.10", "darwin", "posix", "Darwin", "arm64", "constraints/requirements-macos-py312.lock", "constraints/requirements-macos-arm64-py312.wheels.lock", "bin/python"),
    "macos-x64": NativeHost("3.12.10", "darwin", "posix", "Darwin", "x86_64", "constraints/requirements-macos-py312.lock", "constraints/requirements-macos-x64-py312.wheels.lock", "bin/python"),
    "windows-x64": NativeHost("3.12.10", "win32", "nt", "Windows", "AMD64", "constraints/requirements-windows-py312.lock", "constraints/requirements-windows-x64-py312.wheels.lock", "Scripts/python.exe"),
}


def native_identity() -> dict[str, str]:
    return {
        "python_version": platform.python_version(), "sys_platform": sys.platform,
        "os_name": os.name, "system": platform.system(),
        "machine": platform.machine(), "implementation": sys.implementation.name,
    }


def require_native(host: NativeHost, observed: Mapping[str, str]) -> None:
    expected = {
        "python_version": host.python, "sys_platform": host.sys_platform,
        "os_name": host.os_name, "system": host.system,
        "machine": host.machine, "implementation": "cpython",
    }
    if dict(observed) != expected or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise ProposalError(f"native tuple mismatch: expected {expected!r}, observed {dict(observed)!r}")


def isolated_environment(source: Mapping[str, str]) -> dict[str, str]:
    result = {
        key: value for key, value in source.items()
        if not key.upper().startswith(("PYTHON", "PIP_", "PIP_TOOLS_"))
    }
    result["PIP_CONFIG_FILE"] = os.devnull
    return result


def load_sibling(name: str, filename: str, directory: Path | None = None) -> ModuleType:
    path = (Path(__file__).resolve(strict=True).parent if directory is None else directory) / filename
    if path.is_symlink() or not path.is_file():
        raise ProposalError(f"required physical sibling is unavailable: {path}")
    prior = sys.modules.get(name)
    if prior is not None:
        if getattr(prior, "__file__", None) != str(path):
            raise ProposalError(f"conflicting sibling module: {name}")
        return prior
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ProposalError(f"cannot load exact sibling: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def file_binding(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def same_file_across_views(path_value: os.stat_result, descriptor_value: os.stat_result) -> bool:
    path_key, descriptor_key = file_binding(path_value), file_binding(descriptor_value)
    if sys.platform != "win32":
        return path_key == descriptor_key
    # CPython 3.12 Windows path ctime is creation time; fd ctime is change time.
    # Birthtime has matching semantics, while each view keeps its full own seal.
    path_birthtime: object = getattr(path_value, "st_birthtime_ns", None)
    descriptor_birthtime: object = getattr(descriptor_value, "st_birthtime_ns", None)
    return (path_key[:6] == descriptor_key[:6]
            and type(path_birthtime) is int and type(descriptor_birthtime) is int
            and path_birthtime == descriptor_birthtime)


def hash_regular(path: Path, maximum: int) -> tuple[int, str]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
        raise ProposalError(f"not a bounded private regular file: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with io.FileIO(descriptor, "r", closefd=True) as stream:
        opened = os.fstat(stream.fileno())
        if not same_file_across_views(before, opened):
            raise ProposalError(f"file changed while opening: {path}; expected={file_binding(before)!r}; observed={file_binding(opened)!r}")
        digest, size = hashlib.sha256(), 0
        while block := stream.read(min(1_048_576, maximum + 1 - size)):
            size += len(block)
            if size > maximum:
                raise ProposalError(f"file byte bound exceeded: {path}")
            digest.update(block)
        if size != before.st_size or file_binding(os.fstat(stream.fileno())) != file_binding(opened):
            raise ProposalError(f"file changed while hashing: {path}")
    if file_binding(path.lstat()) != file_binding(before):
        raise ProposalError(f"file namespace changed while hashing: {path}")
    return size, digest.hexdigest()


def read_regular(path: Path, maximum: int = MAX_TEXT_BYTES) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
        raise ProposalError(f"not a bounded private regular file: {path}")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not same_file_across_views(before, opened):
            raise ProposalError(f"file changed while opening: {path}; expected={file_binding(before)!r}; observed={file_binding(opened)!r}")
        content = stream.read(maximum + 1)
        if len(content) > maximum or file_binding(os.fstat(stream.fileno())) != file_binding(opened):
            raise ProposalError(f"file changed/overflowed while reading: {path}")
    if file_binding(path.lstat()) != file_binding(before):
        raise ProposalError(f"file namespace changed while reading: {path}")
    return content


def publish_bytes(path: Path, payload: bytes) -> None:
    module = load_sibling("_gm2godot_native_proposal_anchored", "_anchored_output.py")
    publish = cast(Callable[[Path, bytes], None], getattr(module, "publish_identical_receipt_bytes"))
    publish(path, payload)


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


class _NativeFunction(Protocol):
    argtypes: object
    restype: object

    def __call__(self, *arguments: object) -> int: ...


class _NativeLibrary(Protocol):
    def __getattr__(self, name: str) -> _NativeFunction: ...


def _windows_guard_job() -> object:
    """Assign this guardian before any command child exists; close kills its tree."""
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
            ("flags", ctypes.c_uint32), ("minimum_working_set", ctypes.c_size_t),
            ("maximum_working_set", ctypes.c_size_t), ("active_process_limit", ctypes.c_uint32),
            ("affinity", ctypes.c_size_t), ("priority", ctypes.c_uint32),
            ("scheduling", ctypes.c_uint32),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("read_operations", "write_operations", "other_operations", "read_bytes", "write_bytes", "other_bytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    load = cast(Callable[..., _NativeLibrary], getattr(ctypes, "WinDLL"))
    last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    if ctypes.sizeof(BasicLimits) != 64 or ctypes.sizeof(IoCounters) != 48 or ctypes.sizeof(ExtendedLimits) != 144:
        raise ProposalError("unsupported Windows x64 Job Object ABI")
    kernel = load("kernel32", use_last_error=True)
    create = kernel.CreateJobObjectW
    create.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    create.restype = wintypes.HANDLE
    configure = kernel.SetInformationJobObject
    configure.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    configure.restype = ctypes.c_int32  # Win32 BOOL has fixed 32-bit width.
    assign = kernel.AssignProcessToJobObject
    assign.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    assign.restype = ctypes.c_int32
    current = kernel.GetCurrentProcess
    current.argtypes = ()
    current.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = ctypes.c_int32
    handle = create(None, None)
    if not handle:
        raise OSError(last_error(), "CreateJobObjectW failed")
    limits = ExtendedLimits()
    limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    try:
        if not configure(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError(last_error(), "SetInformationJobObject failed")
        if not assign(handle, current()):
            raise OSError(last_error(), "AssignProcessToJobObject failed before child launch")
    except BaseException as error:
        try:
            if not close(handle):
                error.add_note(f"CloseHandle failed after job setup failure: {last_error()}")
        except BaseException as cleanup_error:
            error.add_note(f"CloseHandle raised after job setup failure: {str(cleanup_error)[:512]}")
        raise
    # Deliberately retained until guardian termination: no child inherits this
    # handle, and OS process teardown closes it even after forced termination.
    return handle


def _guardian(specification_path: Path) -> int:
    specification = json.loads(read_regular(specification_path).decode("utf-8"))
    result_path = Path(specification["result"])
    job: object | None = None
    try:
        if os.name == "nt":
            job = _windows_guard_job()
        completed = subprocess.run(
            specification["argv"], cwd=specification["cwd"],
            env=specification["environment"], check=False, stdin=subprocess.DEVNULL,
        )
        result = {"returncode": completed.returncode, "error": None}
    except BaseException as error:
        result = {"returncode": None, "error": f"{type(error).__name__}: {str(error)[:512]}"}
    publish_bytes(result_path, json_bytes(result))
    # Parent owns an unreaped guardian until it kills the complete group/job.
    # EOF means parent died: the guardian must close its own remaining tree.
    while os.read(0, 1):
        pass
    if os.name == "posix":
        os.killpg(os.getpgrp(), signal.SIGKILL)
    _ = job
    return 2


def _require_private_guardian_ownership() -> None:
    # This isolated CLI has no child reaper/observer thread and never polls the
    # private guardian. Default SIGCHLD keeps its leader reserved until teardown.
    if os.name == "posix":
        child_signal = getattr(signal, "SIGCHLD", None)
        if not isinstance(child_signal, int) or signal.getsignal(child_signal) != signal.SIG_DFL:
            raise ProposalError("private guardian requires default SIGCHLD ownership")


def run_command(argv: Sequence[str], *, cwd: Path, environment: Mapping[str, str],
                work: Path, label: str, timeout: int = MAX_COMMAND_SECONDS,
                guardian_path: Path | None = None,
                publisher: Callable[[Path, bytes], None] = publish_bytes) -> dict[str, object]:
    """Retain bounded output and kill/reap the unreaped guardian and its children."""
    if not 0 < timeout <= MAX_COMMAND_SECONDS:
        raise ProposalError("invalid command timeout")
    _require_private_guardian_ownership()
    command_root = Path(tempfile.mkdtemp(prefix="command-", dir=work))
    specification_path = command_root / "specification.json"
    result_path = command_root / "result.json"
    publisher(specification_path, json_bytes({"argv": list(argv), "cwd": str(cwd),
                    "environment": dict(environment), "result": str(result_path)}))
    stdout_path, stderr_path = command_root / "stdout", command_root / "stderr"
    process: subprocess.Popen[bytes] | None = None
    primary: BaseException | None = None
    result: dict[str, object] | None = None
    print(f"Native command {label}: {json.dumps(list(argv))}", flush=True)
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve() if guardian_path is None else guardian_path), "--internal-guardian", str(specification_path)],
                cwd=cwd, env=environment, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                start_new_session=os.name == "posix",
            )
            deadline = time.monotonic() + timeout
            while not result_path.exists():
                if stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_TEXT_BYTES:
                    raise ProposalError(f"command output bound exceeded: {label}")
                if time.monotonic() >= deadline:
                    raise ProposalError(f"command timed out after {timeout}s: {label}")
                time.sleep(0.05)
            result = cast(dict[str, object], json.loads(read_regular(result_path).decode("utf-8")))
            if type(result.get("returncode")) is not int or result.get("returncode") != 0 or result.get("error") is not None:
                raise ProposalError(f"command failed: {label}: {result!r}")
        except BaseException as error:
            primary = error
            raise
        finally:
            if process is not None:
                cleanup_errors: list[BaseException] = []
                try:
                    if os.name == "posix":
                        _require_private_guardian_ownership()
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                try:
                    process.wait(timeout=15)
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                if process.stdin is not None:
                    try:
                        process.stdin.close()
                    except BaseException as cleanup_error:
                        cleanup_errors.append(cleanup_error)
                for output_path, target in ((stdout_path, sys.stdout), (stderr_path, sys.stderr)):
                    try:
                        content = read_regular(output_path)
                        if content:
                            print(content.decode(errors="replace"), file=target, flush=True)
                    except BaseException as capture_error:
                        cleanup_errors.append(capture_error)
                if cleanup_errors:
                    retained = primary if primary is not None else cleanup_errors[0]
                    for cleanup_error in cleanup_errors if primary is not None else cleanup_errors[1:]:
                        retained.add_note(f"guardian cleanup/capture failure: {str(cleanup_error)[:512]}")
                    if primary is None:
                        raise retained
    output = read_regular(stdout_path)
    errors = read_regular(stderr_path)
    if len(output) + len(errors) > MAX_TEXT_BYTES:
        raise ProposalError(f"command output bound exceeded: {label}")
    return {"label": label, "argv": list(argv), "cwd": str(cwd), "returncode": 0,
            "stdout_sha256": hashlib.sha256(output).hexdigest(), "stderr_sha256": hashlib.sha256(errors).hexdigest(),
            "stdout_bytes": len(output), "stderr_bytes": len(errors)}


HELPERS = (
    "scripts/propose_native_wheels.py", "scripts/verify_native_wheel_proposal.py",
    "scripts/compile_dependency_lock.py", "scripts/verify_dependency_environment.py",
    "scripts/verify_dependency_bootstrap.py", "scripts/_anchored_output.py",
    "scripts/_anchored_receipt_posix.py", "scripts/_anchored_receipt_windows.py",
    ".github/workflows/native-wheel-proposals.yml",
)
ROOTS = ("requirements-bootstrap.txt", "requirements.txt", "requirements-tooling.txt", "requirements-lock.in")
PHASES = (
    "native-preflight", "current-preflight", "current-generator", "candidate-compile",
    "candidate-preflight", "first-download", "first-observation", "second-download",
    "second-observation", "candidate-generator", "selfhost-compile", "fresh-1", "fresh-2",
)
COMPILE_FLAGS = (
    "--resolver=backtracking", "--strip-extras", "--allow-unsafe",
    "--no-emit-index-url", "--no-emit-trusted-host", "--no-emit-find-links",
    "--no-emit-options", "--no-config",
    "--pip-args=--isolated --disable-pip-version-check --no-input --no-cache-dir --only-binary=:all:",
)
PIP_FLAGS = ("--isolated", "--disable-pip-version-check", "--no-input")
BOOTSTRAP_CODE = (
    "import importlib.util,sys; from pathlib import Path; "
    "p=Path(sys.argv[1]).resolve(strict=True); "
    "s=importlib.util.spec_from_file_location('_proposal_bootstrap_verifier',p); "
    "m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; "
    "s.loader.exec_module(m); raise SystemExit(m.bootstrap_preflight_main(sys.argv[2:]))"
)
PIN = re.compile(r"([a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)\s*==\s*([a-z0-9][a-z0-9.!+_-]*)\Z", re.IGNORECASE | re.ASCII)
MAX_WHEEL_BYTES = 536_870_912
MAX_METADATA_BYTES = 4_194_304
MAX_JSON_BYTES = 16_777_216


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def exact_pins(content: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in content.decode("utf-8").splitlines():
        if "\\" in raw:
            raise ProposalError("version locks cannot contain continuations")
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        if match is None:
            raise ProposalError(f"not an exact version pin: {line!r}")
        name = normalize_name(match[1])
        if name in result:
            raise ProposalError(f"duplicate normalized pin: {name}")
        result[name] = match[2]
    if not result:
        raise ProposalError("empty version pin set")
    return result


def companion_bytes(pins: Mapping[str, str], wheels: Sequence[Mapping[str, object]]) -> bytes:
    observed: dict[str, str] = {}
    for wheel in wheels:
        name, version, digest = wheel.get("name"), wheel.get("version"), wheel.get("sha256")
        if not isinstance(name, str) or not isinstance(version, str) or not isinstance(digest, str):
            raise ProposalError("malformed observed wheel identity")
        if name != normalize_name(name) or name in observed or pins.get(name) != version or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ProposalError("wheel/pin identity or digest mismatch")
        observed[name] = digest
    if set(observed) != set(pins):
        raise ProposalError("wheel/pin inventory is missing or additional")
    return "".join(f"{name}=={pins[name]} --hash=sha256:{observed[name]}\n" for name in sorted(pins)).encode()


def parse_companion(content: bytes) -> dict[str, tuple[str, str]]:
    if b"\r" in content or not content.endswith(b"\n"):
        raise ProposalError("companion must use canonical terminal LF")
    result: dict[str, tuple[str, str]] = {}
    for line in content.decode().splitlines():
        match = re.fullmatch(r"([a-z0-9][a-z0-9-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*) --hash=sha256:([0-9a-f]{64})", line)
        if match is None or match[1] in result:
            raise ProposalError("invalid/duplicate canonical hashed pin")
        result[match[1]] = (match[2], match[3])
    if not result or list(result) != sorted(result):
        raise ProposalError("empty or unsorted companion")
    return result


class WheelReader(io.BufferedReader):
    def read(self, size: int | None = -1) -> bytes:
        request = os.fstat(self.fileno()).st_size - self.tell() if size is None or size < 0 else size
        if request > 33_554_432:
            raise ProposalError("wheel ZIP directory read bound exceeded")
        return super().read(size)


@dataclass(frozen=True)
class WheelParser:
    filename: Callable[[str], tuple[str, str, frozenset[str]]]
    tags: Callable[[str], frozenset[str]]
    version: Callable[[str], str]


def _packaging_attribute(module_name: str, attribute_name: str) -> object:
    """Load public APIs only inside the verified observation environment."""
    try:
        module = importlib.import_module(module_name)
        value: object = getattr(module, attribute_name)
    except (ImportError, AttributeError) as error:
        raise ProposalError(f"verified Packaging API unavailable: {module_name}.{attribute_name}") from error
    if attribute_name != "__file__" and not callable(value):
        raise ProposalError(f"verified Packaging API is not callable: {module_name}.{attribute_name}")
    return value


def _packaging_source_path(module_name: str) -> Path:
    filename = _packaging_attribute(module_name, "__file__")
    if not isinstance(filename, str) or not filename:
        raise ProposalError(f"verified Packaging module has no source path: {module_name}")
    return Path(filename)


def public_wheel_parser() -> WheelParser:
    # Deferred until the observation child is running in the verified generator.
    parse_tag = cast(Callable[[str], frozenset[object]], _packaging_attribute("packaging.tags", "parse_tag"))
    parse_wheel_filename = cast(Callable[[str], tuple[str, object, object, frozenset[object]]],
        _packaging_attribute("packaging.utils", "parse_wheel_filename"))
    parse_version = cast(Callable[[str], object], _packaging_attribute("packaging.version", "Version"))

    def filename(value: str) -> tuple[str, str, frozenset[str]]:
        name, version, _, tags = parse_wheel_filename(value)
        return name, str(version), frozenset(str(tag) for tag in tags)

    def tags(value: str) -> frozenset[str]:
        return frozenset(str(tag) for tag in parse_tag(value))

    def version(value: str) -> str:
        return str(parse_version(value))

    return WheelParser(filename, tags, version)


def _observe_wheel(path: Path, pins: Mapping[str, str], native_tags: frozenset[str],
                   parser: WheelParser | None = None) -> dict[str, object]:
    selected = public_wheel_parser() if parser is None else parser

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_WHEEL_BYTES:
        raise ProposalError(f"invalid native wheel file: {path}")
    name, version, filename_tags = selected.filename(path.name)
    if pins.get(name) != version:
        raise ProposalError(f"native wheel filename does not project to candidate: {path.name}")
    tags = sorted(filename_tags)
    compatible = sorted(set(tags) & native_tags)
    if not compatible:
        raise ProposalError(f"wheel has no actual native compatible tag: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with WheelReader(io.FileIO(descriptor, "r", closefd=True)) as stream:
        opened = os.fstat(stream.fileno())
        if not same_file_across_views(before, opened):
            raise ProposalError(f"wheel changed while opening; expected={file_binding(before)!r}; observed={file_binding(opened)!r}")
        digest = hashlib.sha256()
        size = 0
        while block := stream.read(min(1_048_576, MAX_WHEEL_BYTES + 1 - size)):
            size += len(block)
            if size > MAX_WHEEL_BYTES:
                raise ProposalError("wheel byte bound exceeded")
            digest.update(block)
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            if not 0 < len(infos) <= 100_000:
                raise ProposalError("wheel member count bound exceeded")
            names = [info.filename for info in infos]
            if len(set(names)) != len(names):
                raise ProposalError("duplicate wheel ZIP member")
            for info in infos:
                parts = info.filename.rstrip("/").split("/")
                if info.orig_filename != info.filename or "\\" in info.filename or ":" in info.filename or any(ord(char) < 32 or ord(char) == 127 for char in info.filename) or any(part in ("", ".", "..") for part in parts) or info.filename.startswith("/") or info.flag_bits & 1:
                    raise ProposalError("unsafe/encrypted wheel ZIP member")
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ProposalError("special wheel ZIP member")
            if sum(info.file_size for info in infos) > 2_147_483_648:
                raise ProposalError("expanded wheel byte bound exceeded")
            metadata_names = [member for member in names if member.endswith(".dist-info/METADATA") and member.count("/") == 1]
            wheel_names = [member for member in names if member.endswith(".dist-info/WHEEL") and member.count("/") == 1]
            if len(metadata_names) != 1 or len(wheel_names) != 1 or metadata_names[0].rsplit("/", 1)[0] != wheel_names[0].rsplit("/", 1)[0]:
                raise ProposalError("wheel has ambiguous/missing metadata")
            directory = metadata_names[0].rsplit("/", 1)[0].removesuffix(".dist-info")
            directory_name, separator, directory_version = directory.rpartition("-")
            if not separator or normalize_name(directory_name) != name or selected.version(directory_version) != version:
                raise ProposalError("wheel dist-info directory identity mismatch")
            records: list[Message[str, str]] = []
            for member in (metadata_names[0], wheel_names[0]):
                if not 0 < archive.getinfo(member).file_size <= MAX_METADATA_BYTES:
                    raise ProposalError("wheel metadata byte bound exceeded")
                records.append(BytesParser().parsebytes(archive.read(member)))
            metadata, wheel_metadata = records
            if len(metadata.get_all("Name", [])) != 1 or len(metadata.get_all("Version", [])) != 1 or normalize_name(str(metadata["Name"])) != name or str(metadata["Version"]) != version:
                raise ProposalError("wheel filename/METADATA identity mismatch")
            wheel_tags = {tag for value in wheel_metadata.get_all("Tag", []) for tag in selected.tags(str(value))}
            if wheel_metadata.get_all("Wheel-Version", []) != ["1.0"] or wheel_tags != set(tags):
                raise ProposalError("wheel filename/WHEEL tag mismatch")
        if size != before.st_size or file_binding(os.fstat(stream.fileno())) != file_binding(opened):
            raise ProposalError("wheel changed while hashing/inspecting")
    if file_binding(path.lstat()) != file_binding(before):
        raise ProposalError("wheel namespace changed while inspecting")
    return {"name": name, "version": version, "filename": path.name, "size": size,
            "sha256": digest.hexdigest(), "tags": tags, "compatible_tags": compatible}


def observe(specification_path: Path) -> int:
    specification = cast(dict[str, object], json.loads(read_regular(specification_path).decode()))
    identity = cast(dict[str, object], specification["identity"])
    native = cast(dict[str, str], specification["native"])
    host = HOSTS[cast(str, identity["platform"])]
    require_native(host, native_identity())
    if native != native_identity():
        raise ProposalError("observation child native identity changed")
    candidate = Path(cast(str, specification["candidate"]))
    content = read_regular(candidate)
    pins = exact_pins(content)
    packaging_version = importlib.metadata.version("packaging")
    if packaging_version != pins.get("packaging"):
        raise ProposalError("observing Packaging differs from candidate pin")
    sys_tags = cast(Callable[[], Iterable[object]], _packaging_attribute("packaging.tags", "sys_tags"))
    native_tags = [str(tag) for tag in sys_tags()]
    if not native_tags or len(native_tags) != len(set(native_tags)) or len(native_tags) > 8_192:
        raise ProposalError("invalid native tag observation")
    tag_observation = {
        "packaging_version": packaging_version,
        "packaging_tags_sha256": hashlib.sha256(read_regular(_packaging_source_path("packaging.tags"))).hexdigest(),
        "packaging_utils_sha256": hashlib.sha256(read_regular(_packaging_source_path("packaging.utils"))).hexdigest(),
        "tags": native_tags, "tags_sha256": hashlib.sha256(("\n".join(native_tags) + "\n").encode()).hexdigest(),
    }
    house = Path(cast(str, specification["wheelhouse"]))
    entries = list(house.iterdir())
    if not entries or len(entries) > 512 or any(path.suffix != ".whl" for path in entries):
        raise ProposalError("invalid/missing/additional native wheelhouse entries")
    wheels = sorted((_observe_wheel(path, pins, frozenset(native_tags)) for path in entries), key=lambda row: cast(str, row["name"]))
    companion = companion_bytes(pins, wheels)
    packaging_rows = [row for row in wheels if row["name"] == "packaging"]
    if len(packaging_rows) != 1:
        raise ProposalError("selected Packaging wheel missing")
    # Installed source must be the exact selected native Packaging bytes.
    with zipfile.ZipFile(house / cast(str, packaging_rows[0]["filename"])) as archive:
        for member, key in (("packaging/tags.py", "packaging_tags_sha256"), ("packaging/utils.py", "packaging_utils_sha256")):
            if archive.getinfo(member).file_size > MAX_TEXT_BYTES or hashlib.sha256(archive.read(member)).hexdigest() != tag_observation[key]:
                raise ProposalError("installed Packaging source differs from observed wheel")
    inventory = {"schema_version": 1, "identity": identity, "native": native,
                 "candidate_sha256": hashlib.sha256(content).hexdigest(),
                 "tag_observation": tag_observation, "wheels": wheels}
    publish_bytes(Path(cast(str, specification["inventory"])), json_bytes(inventory))
    publish_bytes(Path(cast(str, specification["companion"])), companion)
    return 0


class Journal:
    def __init__(self, work: Path, environment: Mapping[str, str], guardian: Path,
                 publisher: Callable[[Path, bytes], None]) -> None:
        self.work = work
        self.environment = environment
        self.guardian = guardian
        self.publisher = publisher
        self.records: list[dict[str, object]] = []
        self.phases: list[dict[str, object]] = [{"name": "native-preflight", "returncode": 0, "command_ids": []}]

    def invoke(self, phase: str, kind: str, argv: Sequence[str], cwd: Path, timeout: int = 600,
               extra_environment: Mapping[str, str] | None = None) -> None:
        if phase != self.phases[-1]["name"]:
            if PHASES[len(self.phases)] != phase:
                raise ProposalError(f"phase sequence drift: {phase}")
            self.phases.append({"name": phase, "returncode": 0, "command_ids": []})
        environment = dict(self.environment)
        environment.update(extra_environment or {})
        run_command(argv, cwd=cwd, environment=environment, work=self.work, label=phase + ":" + kind, timeout=timeout,
                    guardian_path=self.guardian, publisher=self.publisher)
        identifier = len(self.records) + 1
        self.records.append({"id": identifier, "phase": phase, "kind": kind,
                             "argv": list(argv), "cwd": str(cwd), "returncode": 0})
        cast(list[int], self.phases[-1]["command_ids"]).append(identifier)

    def bytes(self) -> bytes:
        return b"".join(json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n" for record in self.records)


def _git(source: Path, arguments: Sequence[str]) -> bytes:
    if any(key.upper() in GIT_SELECTORS for key in os.environ):
        raise ProposalError("repository selectors cannot redirect source Git operations")
    if len(arguments) == 3 and tuple(arguments[:2]) == ("cat-file", "blob"):
        object_name = arguments[2]
        size = _git(source, ("cat-file", "-s", object_name))
        if not re.fullmatch(rb"[0-9]+\n", size) or not 0 < int(size) <= MAX_TEXT_BYTES or _git(source, ("cat-file", "-t", object_name)) != b"blob\n":
            raise ProposalError("immutable source blob type/size bound exceeded")
    completed = subprocess.run(["git", "--no-replace-objects", "-C", str(source), *arguments],
                               check=False, stdin=subprocess.DEVNULL, capture_output=True,
                               env=isolated_environment(os.environ), timeout=30)
    if completed.returncode or len(completed.stdout) > MAX_TEXT_BYTES or len(completed.stderr) > MAX_TEXT_BYTES:
        raise ProposalError("bounded immutable source Git read failed")
    return completed.stdout


def version_layout(source: Path, phase: str) -> dict[str, str]:
    layout = {name: host.seed for name, host in HOSTS.items()}
    split = ("constraints/requirements-macos-arm64-py312.lock", "constraints/requirements-macos-x64-py312.lock")
    present = [os.path.lexists(source / name) for name in split]
    if any(present) and not all(present):
        raise ProposalError("partial committed macOS split layout")
    if phase == "require-committed" and all(present):
        layout["macos-arm64"], layout["macos-x64"] = split
    return layout


def bind_source(source: Path, source_sha: str, platform_name: str, phase: str) -> tuple[dict[str, bytes], dict[str, str]]:
    if not source.is_absolute() or source.is_symlink() or source.resolve(strict=True) != source:
        raise ProposalError("source root must be an absolute physical checkout")
    if not (source / "scripts/propose_native_wheels.py").samefile(Path(__file__)):
        raise ProposalError("producer must be the exact checked-out sibling source")
    if Path(_git(source, ("rev-parse", "--show-toplevel")).decode().strip()).resolve(strict=True) != source or _git(source, ("rev-parse", "HEAD")).decode().strip() != source_sha:
        raise ProposalError("source checkout root/HEAD differs from explicit immutable SHA")
    graft_path = Path(_git(source, ("rev-parse", "--git-path", "info/grafts")).decode().strip())
    if not graft_path.is_absolute():
        graft_path = source / graft_path
    if os.path.lexists(graft_path):
        raise ProposalError("source ancestry grafts are forbidden")
    layout = version_layout(source, phase)
    names = set(HELPERS + ROOTS + (layout[platform_name],))
    if phase == "require-committed":
        names.update(layout.values())
        names.update(host.companion for host in HOSTS.values())
    files: dict[str, bytes] = {}
    for name in sorted(names):
        content = read_regular(source / name)
        if content != _git(source, ("cat-file", "blob", f"{source_sha}:{name}")):
            raise ProposalError(f"physical source differs from immutable object: {name}")
        files[name] = content
    if phase == "require-committed":
        for name, host in HOSTS.items():
            projection = {key: value[0] for key, value in parse_companion(files[host.companion]).items()}
            if projection != exact_pins(files[layout[name]]):
                raise ProposalError(f"committed companion projection mismatch: {name}")
    return files, layout


def _fresh_root(path: Path) -> None:
    if not path.is_absolute() or os.path.lexists(path):
        raise ProposalError(f"work root must be fresh and absolute: {path}")
    if not path.parent.is_dir() or path.parent.is_symlink() or path.parent.resolve(strict=True) != path.parent:
        raise ProposalError("work root parent must be physical and already exist")
    path.mkdir(mode=0o700)


def prepare_snapshot(work: Path, files: Mapping[str, bytes]) -> tuple[Path, Callable[[Path, bytes], None]]:
    """Bootstrap only authenticated helpers into the new private source root.

    These exclusive, fsynced initial copies are needed before the captured
    anchored publisher can itself be loaded. All subsequent publications use
    that exact captured helper; checkout mutations never change execution.
    """
    export = work / "source"
    directory = export / "scripts"
    directory.mkdir(parents=True, mode=0o700)
    for name in HELPERS:
        if not name.endswith(".py"):
            continue
        path = export / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            if stream.write(files[name]) != len(files[name]):
                raise ProposalError("authenticated helper copy was short")
            stream.flush()
            os.fsync(stream.fileno())
        if read_regular(path) != files[name]:
            raise ProposalError("authenticated helper snapshot changed")
    module = load_sibling("_gm2godot_native_proposal_snapshot_anchor", "_anchored_output.py", directory)
    publish = cast(Callable[[Path, bytes], None], getattr(module, "publish_identical_receipt_bytes"))
    for name, content in files.items():
        path = export / name
        path.parent.mkdir(parents=True, exist_ok=True)
        publish(path, content)
    return export, publish


def produce(arguments: argparse.Namespace) -> int:
    platform_name = cast(str, arguments.platform)
    host = HOSTS[platform_name]
    require_native(host, native_identity())  # Before source helper loads/venv/ensurepip.
    repository = cast(str, arguments.repository)
    source_sha = cast(str, arguments.source_sha)
    if repository != "Infiland/GM2Godot" or SHA_PATTERN.fullmatch(source_sha) is None:
        raise ProposalError("invalid canonical repository/source SHA")
    run_id, attempt = cast(int, arguments.run_id), cast(int, arguments.run_attempt)
    if run_id <= 0 or attempt <= 0:
        raise ProposalError("run/attempt must be positive")
    source, work = Path(arguments.source_root), Path(arguments.work_root)
    phase = cast(str, arguments.phase)
    files, layout = bind_source(source, source_sha, platform_name, phase)
    _fresh_root(work)
    artifact = work / "artifact"
    for name in ("inputs", "candidate", "selfhost", "downloads", "receipts", "logs", "wheelhouse"):
        (artifact / name).mkdir(parents=True, mode=0o700)
    export, publish = prepare_snapshot(work, files)
    binding = {"schema_version": 1, "files": {name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)} for name, content in files.items()}}
    publish(artifact / "inputs/source-bindings.json", json_bytes(binding))
    seed = artifact / "inputs/seed.lock"
    publish(seed, files[layout[platform_name]])
    bootstrap = export / "requirements-bootstrap.txt"
    verifier = export / "scripts/verify_dependency_environment.py"
    producer = export / "scripts/propose_native_wheels.py"
    candidate = artifact / "candidate/version.lock"
    companion = artifact / "candidate/companion.wheels.lock"
    identity: dict[str, object] = {"repository": repository, "source_sha": source_sha,
                    "run_id": run_id, "run_attempt": attempt, "platform": platform_name}
    journal = Journal(work, isolated_environment(os.environ), producer, publish)

    def preflight(name: str, constraint: Path) -> None:
        journal.invoke(name, "preflight", [sys.executable, "-I", "-c", BOOTSTRAP_CODE, str(verifier),
            "--source", str(bootstrap), "--policy", "stable", "--constraint", str(constraint),
            "--output", str(artifact / ("receipts/" + name + ".json"))], export)

    def verify(name: str, python: Path, constraint: Path, mode: str) -> None:
        required = ["--require", "pip", "--require", "pip-tools"] if mode == "subset" else []
        journal.invoke(name, "verify", [str(python), "-I", str(verifier), "--constraint", str(constraint),
            "--mode", mode, *required, "--expected-python", host.python, "--expected-platform", host.sys_platform,
            "--expected-machine", host.machine, "--bootstrap", str(bootstrap), "--bootstrap-policy", "stable",
            "--output", str(artifact / ("receipts/" + name + ".json"))], export)

    def environment(name: str, constraint: Path, house: Path | None = None) -> Path:
        root = work / name
        journal.invoke(name, "venv", [sys.executable, "-I", "-m", "venv", str(root)], export)
        python = root / host.venv_python
        if house is None:
            for package in ("pip", "pip-tools"):
                journal.invoke(name, "install", [str(python), "-I", "-m", "pip", *PIP_FLAGS, "install",
                    "--no-cache-dir", "--only-binary=:all:", "--constraint", str(constraint), package], export)
            verify(name, python, constraint, "subset")
        else:
            pins = exact_pins(read_regular(constraint))
            rows = parse_companion(read_regular(companion))
            pip_hash = work / (name + "-pip.wheels.lock")
            version, digest = rows["pip"]
            if pins["pip"] != version:
                raise ProposalError("hashed pip bootstrap differs from candidate")
            publish(pip_hash, f"pip=={version} --hash=sha256:{digest}\n".encode())
            for requirements in (pip_hash, companion):
                journal.invoke(name, "install", [str(python), "-I", "-m", "pip", *PIP_FLAGS, "install",
                    "--require-hashes", "--no-index", "--find-links", str(house), "--only-binary=:all:",
                    "--no-cache-dir", "-r", str(requirements)], export)
            verify(name, python, constraint, "complete")
        return python

    def compile_graph(name: str, python: Path, preference: bytes) -> bytes:
        root = work / name
        root.mkdir(mode=0o700)
        for relative, content in files.items():
            if relative.startswith("constraints/"):
                continue
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            publish(destination, content)
        logical_output = layout[platform_name]
        output = root / logical_output
        output.parent.mkdir(parents=True, exist_ok=True)
        publish(output, preference)
        compile_argv = [str(python), "-I", "scripts/compile_dependency_lock.py", *COMPILE_FLAGS,
                        "--cache-dir=" + str(work / (name + "-cache")),
                        "--output-file=" + logical_output, "requirements-lock.in"]
        canonical = 'python -I scripts/compile_dependency_lock.py ' + ' '.join(COMPILE_FLAGS[:-1]) + ' "' + COMPILE_FLAGS[-1] + '" --output-file=' + logical_output + ' requirements-lock.in'
        journal.invoke(name, "compile", compile_argv, root, 900,
                       {"CUSTOM_COMPILE_COMMAND": canonical})
        return read_regular(output)

    try:
        preflight("current-preflight", seed)
        current = environment("current-generator", seed)
        candidate_bytes = compile_graph("candidate-compile", current, read_regular(seed))
        publish(candidate, candidate_bytes)
        preflight("candidate-preflight", candidate)
        pins = exact_pins(candidate_bytes)
        houses = (artifact / "wheelhouse", work / "second-wheelhouse")
        houses[1].mkdir(mode=0o700)
        for index, house in enumerate(houses):
            prefix = "first" if index == 0 else "second"
            journal.invoke(prefix + "-download", "download", [str(current), "-I", "-m", "pip", *PIP_FLAGS,
                "download", "--no-cache-dir", "--only-binary=:all:", "--dest", str(house), "-r", str(candidate)], export, 900)
            specification = work / (prefix + "-observation.json")
            publish(specification, json_bytes({"identity": identity, "native": native_identity(),
                "candidate": str(candidate), "wheelhouse": str(house),
                "inventory": str(artifact / ("downloads/" + prefix + "-wheel-inventory.json")),
                "companion": str(companion if index == 0 else artifact / "downloads/second-companion.wheels.lock")}))
            journal.invoke(prefix + "-observation", "observe", [str(current), "-I", str(producer), "--internal-observe", str(specification)], export)
        if read_regular(artifact / "downloads/first-wheel-inventory.json", MAX_JSON_BYTES) != read_regular(artifact / "downloads/second-wheel-inventory.json", MAX_JSON_BYTES) or read_regular(companion) != read_regular(artifact / "downloads/second-companion.wheels.lock"):
            raise ProposalError("independent native download inventories/companions differ")
        candidate_python = environment("candidate-generator", candidate, houses[0])
        selfhost_bytes = compile_graph("selfhost-compile", candidate_python, candidate_bytes)
        publish(artifact / "selfhost/version.lock", selfhost_bytes)
        if selfhost_bytes != candidate_bytes:
            raise ProposalError("self-hosted native version lock differs")
        environment("fresh-1", candidate, houses[0])
        environment("fresh-2", candidate, houses[1])
        if read_regular(artifact / "receipts/fresh-1.json", MAX_JSON_BYTES) != read_regular(artifact / "receipts/fresh-2.json", MAX_JSON_BYTES):
            raise ProposalError("original complete schema2 fresh install receipts differ")
        if phase == "require-committed" and (candidate_bytes != files[layout[platform_name]] or read_regular(companion) != files[host.companion]):
            raise ProposalError("generated native version/companion differs from committed source")
        if [row["name"] for row in journal.phases] != list(PHASES):
            raise ProposalError("missing native phases")
        publish(artifact / "logs/commands.jsonl", journal.bytes())
        inventory = cast(dict[str, object], json.loads(read_regular(artifact / "downloads/first-wheel-inventory.json", MAX_JSON_BYTES).decode()))
        wheel_rows = cast(list[dict[str, object]], inventory["wheels"])
        for house in houses:
            if {path.name for path in house.iterdir()} != {row["filename"] for row in wheel_rows}:
                raise ProposalError("native wheelhouse inventory changed before sealing")
            for row in wheel_rows:
                size, digest = hash_regular(house / cast(str, row["filename"]), MAX_WHEEL_BYTES)
                if size != row["size"] or digest != row["sha256"]:
                    raise ProposalError("native wheel bytes changed before sealing")
        references: dict[str, dict[str, object]] = {}
        for path in sorted(artifact.rglob("*")):
            if path.is_dir():
                continue
            relative = path.relative_to(artifact).as_posix()
            if relative.startswith("wheelhouse/"):
                row = next(w for w in wheel_rows if w["filename"] == path.name)
                references[relative] = {"sha256": row["sha256"], "bytes": row["size"]}
            else:
                content = read_regular(path, MAX_JSON_BYTES)
                references[relative] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        proposal = {"schema_version": 1, "kind": "native-wheel-proposal", "status": "verified", "phase": phase,
                    "identity": identity, "native": native_identity(), "tag_observation": inventory["tag_observation"],
                    "files": references, "phases": journal.phases,
                    "counts": {"pins": len(pins), "wheels": len(cast(list[object], inventory["wheels"])), "commands": len(journal.records)}}
        publish(artifact / "proposal.json", json_bytes(proposal))
    except BaseException as error:
        try:
            publish(artifact / "logs/commands.jsonl", journal.bytes())
        except BaseException as cleanup_error:
            error.add_note(f"partial command evidence publication failed: {str(cleanup_error)[:512]}")
        raise
    print(f"Native wheel proposal verified: platform={platform_name} pins={len(pins)} phase={phase}; artifact={artifact}")
    return 0


def _positive_integer(text: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", text) is None:
        raise argparse.ArgumentTypeError("expected an exact positive integer")
    return int(text)


def main(arguments: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if arguments is None else arguments)
    if not sys.flags.isolated:
        print("native wheel proposal requires Python isolated mode (-I)", file=sys.stderr)
        return 2
    try:
        if len(argv) == 2 and argv[0] == "--internal-guardian":
            return _guardian(Path(argv[1]))
        if len(argv) == 2 and argv[0] == "--internal-observe":
            return observe(Path(argv[1]))
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--source-root", required=True)
        parser.add_argument("--platform", choices=tuple(HOSTS), required=True)
        parser.add_argument("--repository", required=True)
        parser.add_argument("--source-sha", required=True)
        parser.add_argument("--run-id", type=_positive_integer, required=True)
        parser.add_argument("--run-attempt", type=_positive_integer, required=True)
        parser.add_argument("--phase", choices=("discover", "require-committed"), required=True)
        parser.add_argument("--work-root", required=True)
        parsed = parser.parse_args(argv)
        return produce(parsed)
    except (OSError, ValueError, ImportError, RuntimeError, zipfile.BadZipFile, KeyboardInterrupt, SystemExit) as error:
        if isinstance(error, SystemExit) and error.code == 0 and "--help" in argv:
            return 0
        print(f"native wheel proposal failed ({type(error).__name__}): {str(error)[:512]}", file=sys.stderr)
        for note in getattr(error, "__notes__", ())[:8]:
            print(f"note: {note[:512]}", file=sys.stderr)
        print("Partial work/evidence may remain; no retry or overwrite was attempted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
