from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
import lzma
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib


ARCHIVE_NAME = "GM2Godot-linux.zip"
EXECUTABLE_NAME = "GM2Godot"
README_NAME = "README.md"
EXPECTED_MEMBER_MODES = {
    EXECUTABLE_NAME: 0o755,
    README_NAME: 0o644,
}
GUI_SMOKE_RECEIPT_ENV = "GM2GODOT_GUI_SMOKE_RECEIPT"
GUI_SMOKE_RECEIPT = b"GM2Godot packaged GUI ready\n"
XVFB_RUN_PATH = Path("/usr/bin/xvfb-run")

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
MAX_README_BYTES = 4 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = MAX_EXECUTABLE_BYTES + MAX_README_BYTES
MAX_PROCESS_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_DIAGNOSTIC_LINE_CHARACTERS = 1000
PROCESS_TIMEOUT_SECONDS = 60.0
PROCESS_POLL_SECONDS = 0.2
PROCESS_CLEANUP_TIMEOUT_SECONDS = 5.0
PROCESS_GROUP_GRACE_SECONDS = 2.0
PROCESS_TERMINATION_GRACE_SECONDS = 2.0

_FATAL_OUTPUT_SIGNATURES = (
    "error while loading shared libraries",
    "cannot open shared object file",
    "could not find the qt platform plugin",
    "could not load the qt platform plugin",
    "no qt platform plugin could be initialized",
)


class LinuxGuiArtifactVerificationError(Exception):
    """A deterministic validation failure suitable for CI output."""


def _require_absolute_normalized_path(raw_path: str, description: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        raise LinuxGuiArtifactVerificationError(
            f"{description} must be an absolute path: {raw_path!r}"
        )
    if Path(os.path.normpath(os.fspath(path))) != path:
        raise LinuxGuiArtifactVerificationError(
            f"{description} must be lexically normalized: {raw_path!r}"
        )
    return path


def _required_open_flags(base: int, *names: str) -> int:
    flags = base
    for name in names:
        value = getattr(os, name, None)
        if type(value) is not int:
            raise LinuxGuiArtifactVerificationError(
                f"required no-follow filesystem flag {name} is unavailable"
            )
        flags |= value
    return flags


def _validate_archive_path(archive_path: Path) -> None:
    if archive_path.name != ARCHIVE_NAME:
        raise LinuxGuiArtifactVerificationError(
            f"Linux release archive must be named {ARCHIVE_NAME}: {archive_path}"
        )


def _validate_members(
    members: Sequence[zipfile.ZipInfo],
) -> dict[str, zipfile.ZipInfo]:
    expected_names = Counter(EXPECTED_MEMBER_MODES.keys())
    observed_names = Counter(member.filename for member in members)
    if len(members) != len(EXPECTED_MEMBER_MODES) or observed_names != expected_names:
        raise LinuxGuiArtifactVerificationError(
            "Linux release ZIP must contain exactly GM2Godot and README.md once each"
        )

    selected: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for member in members:
        if member.orig_filename != member.filename:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member has a NUL-truncated or aliased name: {member.orig_filename!r}"
            )
        if member.flag_bits & 0x1:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member is encrypted: {member.filename}"
            )
        if member.compress_type != zipfile.ZIP_DEFLATED:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member does not use the required DEFLATE compression: "
                f"{member.filename}"
            )
        if member.create_system != 3:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member lacks Unix metadata: {member.filename}"
            )

        raw_mode = (member.external_attr >> 16) & 0xFFFF
        expected_mode = EXPECTED_MEMBER_MODES[member.filename]
        if stat.S_IFMT(raw_mode) != stat.S_IFREG:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member is not a regular file: {member.filename}"
            )
        if stat.S_IMODE(raw_mode) != expected_mode:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member {member.filename} has mode "
                f"{stat.S_IMODE(raw_mode):04o}; expected {expected_mode:04o}"
            )

        maximum_size = (
            MAX_EXECUTABLE_BYTES
            if member.filename == EXECUTABLE_NAME
            else MAX_README_BYTES
        )
        if member.file_size <= 0 or member.file_size > maximum_size:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member {member.filename} has an invalid declared size"
            )
        if member.compress_size < 0 or member.compress_size > MAX_ARCHIVE_BYTES:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member {member.filename} has an invalid compressed size"
            )
        total_size += member.file_size
        selected[member.filename] = member

    if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise LinuxGuiArtifactVerificationError(
            "Linux release ZIP exceeds the total uncompressed-size limit"
        )
    return selected


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("short write while extracting ZIP member")
        offset += written


def _extract_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    destination: Path,
    expected_mode: int,
) -> None:
    descriptor: int | None = None
    extracted_size = 0
    try:
        descriptor = os.open(
            destination,
            _required_open_flags(
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                "O_CLOEXEC",
                "O_NOFOLLOW",
            ),
            expected_mode,
        )
        with archive.open(member, "r") as source:
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                extracted_size += len(chunk)
                if extracted_size > member.file_size:
                    raise LinuxGuiArtifactVerificationError(
                        f"ZIP member {member.filename} exceeded its declared size"
                    )
                _write_all(descriptor, chunk)
        if extracted_size != member.file_size:
            raise LinuxGuiArtifactVerificationError(
                f"ZIP member {member.filename} differs from its declared size"
            )
        os.fchmod(descriptor, expected_mode)
        os.fsync(descriptor)
    except LinuxGuiArtifactVerificationError:
        raise
    except (
        OSError,
        EOFError,
        RuntimeError,
        NotImplementedError,
        ValueError,
        lzma.LZMAError,
        zipfile.BadZipFile,
        zlib.error,
    ) as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to extract ZIP member {member.filename}: {error}"
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _validate_extracted_file(
    path: Path,
    expected_mode: int,
    expected_size: int,
) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to inspect extracted file {path.name}: {error}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise LinuxGuiArtifactVerificationError(
            f"extracted file is not regular: {path.name}"
        )
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise LinuxGuiArtifactVerificationError(
            f"extracted file {path.name} has the wrong mode"
        )
    if metadata.st_size != expected_size:
        raise LinuxGuiArtifactVerificationError(
            f"extracted file {path.name} has the wrong size"
        )


def _read_process_output(stream: object) -> bytes:
    try:
        stream.seek(0)  # type: ignore[attr-defined]
        content = stream.read(MAX_PROCESS_OUTPUT_BYTES + 1)  # type: ignore[attr-defined]
    except OSError as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to read packaged GUI output: {error}"
        ) from error
    if not isinstance(content, bytes):
        raise LinuxGuiArtifactVerificationError("packaged GUI output was not bytes")
    if len(content) > MAX_PROCESS_OUTPUT_BYTES:
        raise LinuxGuiArtifactVerificationError(
            "packaged GUI output exceeded the bounded verification limit"
        )
    return content


def _bounded_output_excerpt(
    line: str,
    marker_start: int,
    marker_end: int,
) -> str:
    escaped_prefix = (
        line[:marker_start]
        .encode("unicode_escape")
        .decode("ascii")
        .replace("'", r"\x27")
    )
    escaped_marker = (
        line[marker_start:marker_end]
        .encode("unicode_escape")
        .decode("ascii")
        .replace("'", r"\x27")
    )
    escaped_suffix = (
        line[marker_end:]
        .encode("unicode_escape")
        .decode("ascii")
        .replace("'", r"\x27")
    )
    escaped_line = escaped_prefix + escaped_marker + escaped_suffix
    escaped_marker_start = len(escaped_prefix)
    escaped_marker_end = escaped_marker_start + len(escaped_marker)
    if len(escaped_line) <= MAX_DIAGNOSTIC_LINE_CHARACTERS:
        return f"'{escaped_line}'"

    marker_length = escaped_marker_end - escaped_marker_start
    omitted_prefix = escaped_marker_start > 0
    omitted_suffix = escaped_marker_end < len(escaped_line)
    ellipsis_length = 3 * (int(omitted_prefix) + int(omitted_suffix))
    content_budget = MAX_DIAGNOSTIC_LINE_CHARACTERS - ellipsis_length
    if marker_length > content_budget:
        marker_budget = MAX_DIAGNOSTIC_LINE_CHARACTERS - 3
        return f"'{escaped_marker[:marker_budget]}...'"

    remaining = content_budget - marker_length
    left_available = escaped_marker_start
    right_available = len(escaped_line) - escaped_marker_end
    left_length = min(left_available, remaining // 2)
    right_length = min(right_available, remaining - left_length)
    remaining -= left_length + right_length
    if remaining:
        additional_left = min(left_available - left_length, remaining)
        left_length += additional_left
        remaining -= additional_left
    if remaining:
        right_length += min(right_available - right_length, remaining)

    excerpt_start = escaped_marker_start - left_length
    excerpt_end = escaped_marker_end + right_length
    excerpt = escaped_line[excerpt_start:excerpt_end]
    if excerpt_start:
        excerpt = "..." + excerpt
    if excerpt_end < len(escaped_line):
        excerpt += "..."
    return f"'{excerpt}'"


def _fatal_output_diagnostic(content: str) -> tuple[str, str] | None:
    for line in content.splitlines():
        selected: tuple[int, int, str] | None = None
        for signature in _FATAL_OUTPUT_SIGNATURES:
            match = re.search(
                re.escape(signature),
                line,
                flags=re.IGNORECASE | re.ASCII,
            )
            if match is None:
                continue
            candidate = (match.start(), match.end(), signature)
            if selected is None or candidate[0] < selected[0]:
                selected = candidate
        if selected is None:
            continue
        marker_start, marker_end, signature = selected
        return signature, _bounded_output_excerpt(
            line,
            marker_start,
            marker_end,
        )
    return None


def _process_group_exists(process: subprocess.Popen[bytes]) -> bool:
    leader_returncode = process.poll()
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError as error:
        # Darwin can report EPERM for a just-terminated group while its leader
        # is becoming waitable. Do not risk signalling a recycled group ID;
        # the direct child is still reaped with a separate bounded wait.
        if sys.platform == "darwin" or leader_returncode is not None:
            return False
        raise LinuxGuiArtifactVerificationError(
            f"unable to inspect packaged GUI process group: {error}"
        ) from error
    except OSError as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to inspect packaged GUI process group: {error}"
        ) from error
    return True


def _signal_process_group(
    process: subprocess.Popen[bytes],
    selected_signal: signal.Signals,
) -> bool:
    try:
        os.killpg(process.pid, selected_signal)
    except ProcessLookupError:
        return False
    except OSError as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to signal packaged GUI process group with "
            f"{selected_signal.name}: {error}"
        ) from error
    return True


def _wait_for_group_disappearance(
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while _process_group_exists(process):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(PROCESS_POLL_SECONDS, remaining))
    return True


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if _signal_process_group(process, signal.SIGTERM) and not _wait_for_group_disappearance(
        process,
        PROCESS_TERMINATION_GRACE_SECONDS,
    ):
        _signal_process_group(process, signal.SIGKILL)
        if not _wait_for_group_disappearance(
            process,
            PROCESS_CLEANUP_TIMEOUT_SECONDS,
        ):
            raise LinuxGuiArtifactVerificationError(
                "packaged GUI process group survived SIGKILL cleanup"
            )

    if process.poll() is None:
        try:
            process.wait(timeout=PROCESS_CLEANUP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise LinuxGuiArtifactVerificationError(
                "packaged GUI process group could not be reaped after termination"
            ) from error


def _process_output_size(output: object) -> int:
    try:
        return os.fstat(output.fileno()).st_size  # type: ignore[attr-defined]
    except OSError as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to inspect packaged GUI output: {error}"
        ) from error


def _wait_for_process_group_exit(
    process: subprocess.Popen[bytes],
    output: object,
) -> None:
    deadline = time.monotonic() + PROCESS_GROUP_GRACE_SECONDS
    while _process_group_exists(process):
        if _process_output_size(output) > MAX_PROCESS_OUTPUT_BYTES:
            raise LinuxGuiArtifactVerificationError(
                "packaged GUI output exceeded the bounded verification limit"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LinuxGuiArtifactVerificationError(
                "packaged GUI left a descendant process running after exit"
            )
        time.sleep(min(PROCESS_POLL_SECONDS, remaining))


def _wait_for_process(
    process: subprocess.Popen[bytes],
    output: object,
    timeout_seconds: float,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    while True:
        output_size = _process_output_size(output)
        if output_size > MAX_PROCESS_OUTPUT_BYTES:
            raise LinuxGuiArtifactVerificationError(
                "packaged GUI output exceeded the bounded verification limit"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LinuxGuiArtifactVerificationError(
                f"packaged GUI timed out after {timeout_seconds:g} seconds"
            )
        try:
            return process.wait(timeout=min(PROCESS_POLL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue


def _validate_xvfb_run(path: Path) -> None:
    if not path.is_absolute() or Path(os.path.normpath(os.fspath(path))) != path:
        raise LinuxGuiArtifactVerificationError(
            f"xvfb-run path must be absolute and normalized: {path}"
        )
    try:
        metadata = path.lstat()
    except OSError as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to inspect xvfb-run: {error}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise LinuxGuiArtifactVerificationError(
            f"xvfb-run is not an executable regular file: {path}"
        )


def _validate_receipt(receipt_path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            receipt_path,
            _required_open_flags(os.O_RDONLY, "O_CLOEXEC", "O_NOFOLLOW"),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise LinuxGuiArtifactVerificationError(
                "packaged GUI readiness receipt is not a regular file"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise LinuxGuiArtifactVerificationError(
                "packaged GUI readiness receipt does not have mode 0600"
            )
        content = os.read(descriptor, len(GUI_SMOKE_RECEIPT) + 1)
    except LinuxGuiArtifactVerificationError:
        raise
    except OSError as error:
        raise LinuxGuiArtifactVerificationError(
            f"unable to read packaged GUI readiness receipt: {error}"
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if content != GUI_SMOKE_RECEIPT:
        raise LinuxGuiArtifactVerificationError(
            "packaged GUI readiness receipt content is invalid"
        )


def _runtime_environment(root: Path, receipt_path: Path) -> dict[str, str]:
    runtime = root / "runtime"
    temporary = root / "tmp"
    config = root / "config"
    cache = root / "cache"
    data = root / "data"
    for directory in (runtime, temporary, config, cache, data):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)

    environment = dict(os.environ)
    for key in (
        "DISPLAY",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PYTHONHOME",
        "PYTHONPATH",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
    ):
        environment.pop(key, None)
    environment.update(
        {
            GUI_SMOKE_RECEIPT_ENV: os.fspath(receipt_path),
            "QT_QPA_PLATFORM": "xcb",
            "QT_DEBUG_PLUGINS": "1",
            "XDG_RUNTIME_DIR": os.fspath(runtime),
            "XDG_CONFIG_HOME": os.fspath(config),
            "XDG_CACHE_HOME": os.fspath(cache),
            "XDG_DATA_HOME": os.fspath(data),
            "TMPDIR": os.fspath(temporary),
        }
    )
    return environment


def _run_packaged_gui(
    root: Path,
    executable: Path,
    *,
    xvfb_run_path: Path,
    timeout_seconds: float,
) -> None:
    _validate_xvfb_run(xvfb_run_path)
    receipt_path = root / "gui-ready.receipt"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise LinuxGuiArtifactVerificationError(
            "packaged GUI readiness receipt path already exists"
        )

    environment = _runtime_environment(root, receipt_path)
    process: subprocess.Popen[bytes] | None = None
    process_group_gone = False
    try:
        with tempfile.TemporaryFile(mode="w+b", dir=root) as output:
            try:
                process = subprocess.Popen(
                    [
                        os.fspath(xvfb_run_path),
                        "--auto-servernum",
                        "--error-file=/dev/stderr",
                        "--server-args=-screen 0 1024x768x24",
                        os.fspath(executable),
                    ],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    close_fds=True,
                    shell=False,
                    start_new_session=True,
                )
            except OSError as error:
                raise LinuxGuiArtifactVerificationError(
                    f"unable to launch packaged GUI under Xvfb: {error}"
                ) from error

            returncode = _wait_for_process(process, output, timeout_seconds)
            _wait_for_process_group_exit(process, output)
            process_group_gone = True
            captured = _read_process_output(output)
    finally:
        if process is not None and not process_group_gone:
            _terminate_process_group(process)

    decoded_output = captured.decode("utf-8", errors="replace")
    fatal_diagnostic = _fatal_output_diagnostic(decoded_output)
    if fatal_diagnostic is not None:
        signature, excerpt = fatal_diagnostic
        raise LinuxGuiArtifactVerificationError(
            f"packaged GUI emitted fatal loader/platform diagnostic: {signature}; "
            f"matching output: {excerpt}"
        )
    if returncode != 0:
        raise LinuxGuiArtifactVerificationError(
            f"packaged GUI exited with status {returncode}"
        )
    _validate_receipt(receipt_path)


def verify_archive(
    archive_path: Path,
    *,
    xvfb_run_path: Path = XVFB_RUN_PATH,
    timeout_seconds: float = PROCESS_TIMEOUT_SECONDS,
) -> None:
    archive_path = _require_absolute_normalized_path(
        os.fspath(archive_path),
        "Linux release archive",
    )
    _validate_archive_path(archive_path)
    if timeout_seconds <= 0:
        raise LinuxGuiArtifactVerificationError("process timeout must be positive")

    archive_descriptor: int | None = None
    try:
        try:
            archive_descriptor = os.open(
                archive_path,
                _required_open_flags(os.O_RDONLY, "O_CLOEXEC", "O_NOFOLLOW"),
            )
            archive_metadata = os.fstat(archive_descriptor)
        except OSError as error:
            raise LinuxGuiArtifactVerificationError(
                f"unable to open Linux release ZIP without following links: {error}"
            ) from error
        if not stat.S_ISREG(archive_metadata.st_mode):
            raise LinuxGuiArtifactVerificationError(
                "Linux release ZIP is not a regular file"
            )
        if archive_metadata.st_size <= 0 or archive_metadata.st_size > MAX_ARCHIVE_BYTES:
            raise LinuxGuiArtifactVerificationError(
                "Linux release ZIP has an invalid size"
            )

        with tempfile.TemporaryDirectory(
            prefix="gm2godot-linux-gui-artifact-"
        ) as raw_root:
            root = Path(raw_root).resolve(strict=True)
            root.chmod(0o700)
            try:
                with (
                    os.fdopen(os.dup(archive_descriptor), "rb") as archive_stream,
                    zipfile.ZipFile(archive_stream) as archive,
                ):
                    selected = _validate_members(archive.infolist())
                    for name, expected_mode in EXPECTED_MEMBER_MODES.items():
                        _extract_member(
                            archive,
                            selected[name],
                            root / name,
                            expected_mode,
                        )
            except LinuxGuiArtifactVerificationError:
                raise
            except (
                OSError,
                EOFError,
                RuntimeError,
                NotImplementedError,
                ValueError,
                lzma.LZMAError,
                zipfile.BadZipFile,
                zlib.error,
            ) as error:
                raise LinuxGuiArtifactVerificationError(
                    f"unable to inspect Linux release ZIP: {error}"
                ) from error

            for name, expected_mode in EXPECTED_MEMBER_MODES.items():
                _validate_extracted_file(
                    root / name,
                    expected_mode,
                    selected[name].file_size,
                )
            executable = (root / EXECUTABLE_NAME).resolve(strict=True)
            if executable.parent != root:
                raise LinuxGuiArtifactVerificationError(
                    "extracted executable escaped the private verification directory"
                )
            _run_packaged_gui(
                root,
                executable,
                xvfb_run_path=xvfb_run_path,
                timeout_seconds=timeout_seconds,
            )
    finally:
        if archive_descriptor is not None:
            try:
                os.close(archive_descriptor)
            except OSError:
                pass


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify and launch the exact packaged Linux GUI under Xvfb."
    )
    parser.add_argument("--archive", required=True)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parse_args(arguments)
    try:
        archive_path = _require_absolute_normalized_path(
            options.archive,
            "Linux release archive",
        )
        verify_archive(archive_path)
    except LinuxGuiArtifactVerificationError as error:
        print(f"Linux packaged GUI verification failed: {error}", file=sys.stderr)
        return 1
    print(f"Verified packaged Linux GUI under Xvfb: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
