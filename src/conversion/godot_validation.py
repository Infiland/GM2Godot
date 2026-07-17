from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal, TypeAlias

from src.conversion.type_defs import JsonDict

GODOT_VALIDATION_REPORT_RELATIVE_PATH = os.path.join(
    "gm2godot", "godot_validation_report.json"
)
GodotValidationStatus: TypeAlias = Literal["passed", "failed", "skipped"]
GodotOutputIssueSeverity: TypeAlias = Literal["warning", "error"]
_LOADABLE_EXTENSIONS = (".gd", ".gdshader", ".tscn", ".tres")
_IMPORTABLE_EXTENSIONS = (
    ".bmp",
    ".dds",
    ".exr",
    ".hdr",
    ".jpg",
    ".jpeg",
    ".ktx",
    ".ktx2",
    ".mp3",
    ".ogg",
    ".otf",
    ".png",
    ".svg",
    ".tga",
    ".ttf",
    ".wav",
    ".webp",
    ".woff",
    ".woff2",
)
_GODOT_ERROR_PREFIXES = ("ERROR:", "SCRIPT ERROR:", "SHADER ERROR:")
_GODOT_WARNING_PREFIXES = ("WARNING:", "SCRIPT WARNING:", "SHADER WARNING:")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
_AUDIO_IMPORTABLE_EXTENSIONS = (".mp3", ".ogg", ".wav")
_GODOT_OUTPUT_CAPTURE_LIMIT_BYTES = 512 * 1024
_GODOT_OUTPUT_READ_CHUNK_BYTES = 64 * 1024
_GODOT_OUTPUT_ISSUE_PREFIX_LIMIT_BYTES = 1024
_GODOT_OUTPUT_READER_POLL_SECONDS = 0.01
_GODOT_OUTPUT_READER_DRAIN_GRACE_SECONDS = 0.25
_GODOT_OUTPUT_READER_STOP_GRACE_SECONDS = 0.25


class _BoundedGodotOutput:
    def __init__(self, limit_bytes: int) -> None:
        if limit_bytes < 2:
            raise ValueError("Godot output capture limit must be at least 2 bytes.")
        self._head_limit_bytes = limit_bytes // 2
        self._tail_limit_bytes = limit_bytes - self._head_limit_bytes
        self._head = bytearray()
        self._tail: deque[bytes] = deque()
        self._tail_bytes = 0
        self._tail_preceding_byte: int | None = None
        self._total_bytes = 0
        self._line_prefix = bytearray()
        self._line_started = False
        self._error_count = 0
        self._warning_count = 0
        self._finished = False

    def append(self, chunk: bytes) -> None:
        if self._finished:
            raise RuntimeError("Cannot append Godot output after capture is finished.")
        self._total_bytes += len(chunk)
        self._track_output_issues(chunk)
        head_remaining = self._head_limit_bytes - len(self._head)
        if head_remaining > 0:
            self._head.extend(chunk[:head_remaining])
            chunk = chunk[head_remaining:]
        if not chunk:
            return

        if self._tail_preceding_byte is None and not self._tail:
            self._tail_preceding_byte = self._head[-1] if self._head else None
        self._tail.append(chunk)
        self._tail_bytes += len(chunk)
        overflow = self._tail_bytes - self._tail_limit_bytes
        while overflow > 0:
            oldest_chunk = self._tail[0]
            if overflow < len(oldest_chunk):
                self._tail_preceding_byte = oldest_chunk[overflow - 1]
                self._tail[0] = oldest_chunk[overflow:]
                self._tail_bytes -= overflow
                break
            self._tail.popleft()
            self._tail_preceding_byte = oldest_chunk[-1]
            self._tail_bytes -= len(oldest_chunk)
            overflow -= len(oldest_chunk)

    def text(self) -> str:
        self._finish()
        retained_bytes = len(self._head) + self._tail_bytes
        tail = b"".join(self._tail)
        if self._total_bytes <= retained_bytes:
            return (bytes(self._head) + tail).decode("utf-8", errors="replace")

        omitted_bytes = self._total_bytes - retained_bytes
        head_output = bytes(self._head).decode("utf-8", errors="replace")
        tail_output = tail.decode("utf-8", errors="replace")
        tail_starts_on_line_boundary = self._tail_preceding_byte in (None, ord("\n"))
        tail_issue_output = tail_output
        if not tail_starts_on_line_boundary:
            first_newline = tail_output.find("\n")
            tail_issue_output = tail_output[first_newline + 1 :] if first_newline >= 0 else ""
        retained_issues = detect_godot_output_issues(head_output) + detect_godot_output_issues(
            tail_issue_output
        )
        retained_error_count = sum(issue.severity == "error" for issue in retained_issues)
        retained_warning_count = sum(issue.severity == "warning" for issue in retained_issues)
        omitted_error_count = max(0, self._error_count - retained_error_count)
        omitted_warning_count = max(0, self._warning_count - retained_warning_count)

        marker_lines = [
            "[GM2Godot: Godot output truncated; "
            f"omitted {omitted_bytes} byte(s); retained first {len(self._head)} "
            f"and last {self._tail_bytes} byte(s).]"
        ]
        if omitted_error_count:
            marker_lines.append(
                "ERROR: GM2Godot output truncation omitted "
                f"{omitted_error_count} additional Godot error diagnostic(s)."
            )
        if omitted_warning_count:
            marker_lines.append(
                "WARNING: GM2Godot output truncation omitted "
                f"{omitted_warning_count} additional Godot warning diagnostic(s)."
            )
        marker = "\n" + "\n".join(marker_lines) + "\n"
        if not tail_starts_on_line_boundary:
            marker += "[GM2Godot: retained tail begins mid-line] "
        return head_output + marker + tail_output

    def _track_output_issues(self, chunk: bytes) -> None:
        offset = 0
        while offset < len(chunk):
            newline_index = chunk.find(b"\n", offset)
            if newline_index < 0:
                self._append_line_prefix(chunk[offset:])
                return
            self._append_line_prefix(chunk[offset:newline_index])
            self._finish_line()
            offset = newline_index + 1

    def _append_line_prefix(self, chunk: bytes) -> None:
        if chunk:
            self._line_started = True
        remaining = _GODOT_OUTPUT_ISSUE_PREFIX_LIMIT_BYTES - len(self._line_prefix)
        if remaining > 0:
            self._line_prefix.extend(chunk[:remaining])

    def _finish_line(self) -> None:
        severity = _godot_output_issue_severity(
            self._line_prefix.decode("utf-8", errors="replace")
        )
        if severity == "error":
            self._error_count += 1
        elif severity == "warning":
            self._warning_count += 1
        self._line_prefix.clear()
        self._line_started = False

    def _finish(self) -> None:
        if self._finished:
            return
        if self._line_started:
            self._finish_line()
        self._finished = True


@dataclass(frozen=True)
class GodotOutputIssue:
    severity: GodotOutputIssueSeverity
    line: str

    def to_dict(self) -> JsonDict:
        return {
            "severity": self.severity,
            "line": self.line,
        }


@dataclass(frozen=True)
class GodotValidationReport:
    status: GodotValidationStatus
    godot_binary: str
    project_path: str
    resource_paths: tuple[str, ...]
    returncode: int | None = None
    import_returncode: int | None = None
    boot_returncode: int | None = None
    import_output: str = ""
    boot_output: str = ""
    output: str = ""
    message: str = ""
    boot_frames: int = 0
    output_issues: tuple[GodotOutputIssue, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "format_version": 1,
            "status": self.status,
            "godot_binary": self.godot_binary,
            "project_path": self.project_path,
            "resource_count": len(self.resource_paths),
            "resource_paths": list(self.resource_paths),
            "returncode": self.returncode,
            "import_returncode": self.import_returncode,
            "boot_returncode": self.boot_returncode,
            "import_output": self.import_output,
            "boot_output": self.boot_output,
            "output": self.output,
            "boot_frames": self.boot_frames,
            "output_issue_count": len(self.output_issues),
            "output_error_count": sum(1 for issue in self.output_issues if issue.severity == "error"),
            "output_warning_count": sum(1 for issue in self.output_issues if issue.severity == "warning"),
            "output_issues": [issue.to_dict() for issue in self.output_issues],
            "message": self.message,
        }


def find_godot_binary(explicit_path: str | None = None) -> str | None:
    if explicit_path and os.path.isfile(explicit_path):
        return explicit_path

    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path

    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary

    macos_app_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    if os.path.isfile(macos_app_binary):
        return macos_app_binary
    return None


def validate_generated_godot_project(
    godot_project_path: str,
    *,
    godot_binary: str | None = None,
    timeout: int = 60,
    load_resources: bool = True,
    boot_frames: int = 0,
) -> GodotValidationReport:
    if boot_frames < 0:
        raise ValueError("boot_frames must be zero or greater.")

    resolved_binary = find_godot_binary(godot_binary)
    resource_paths = generated_godot_resource_paths(godot_project_path)
    if resolved_binary is None:
        return GodotValidationReport(
            status="skipped",
            godot_binary="",
            project_path=godot_project_path,
            resource_paths=resource_paths,
            boot_frames=boot_frames,
            message="Godot binary not found; set GODOT_BIN or pass --godot-bin to run generated resource/runtime validation.",
        )

    if not os.path.isfile(os.path.join(godot_project_path, "project.godot")):
        return GodotValidationReport(
            status="failed",
            godot_binary=resolved_binary,
            project_path=godot_project_path,
            resource_paths=resource_paths,
            boot_frames=boot_frames,
            message="project.godot is missing; generated resources cannot be loaded through Godot.",
        )

    script = _validation_script(resource_paths)
    import_output = ""
    import_returncode: int | None = None
    importable_asset_paths = generated_godot_importable_asset_paths(godot_project_path)
    if importable_asset_paths or not load_resources:
        try:
            import_result = _run_godot_import(
                resolved_binary,
                godot_project_path,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
            output_issues = detect_godot_output_issues(output)
            if not load_resources and not output_issues:
                if boot_frames == 0:
                    return GodotValidationReport(
                        status="passed",
                        godot_binary=resolved_binary,
                        project_path=godot_project_path,
                        resource_paths=resource_paths,
                        import_output=output,
                        output=output,
                        message=_import_only_timeout_message(timeout, len(importable_asset_paths), len(resource_paths)),
                        boot_frames=boot_frames,
                        output_issues=(),
                    )
                output_issues = detect_godot_output_issues(output)
            return GodotValidationReport(
                status="failed",
                godot_binary=resolved_binary,
                project_path=godot_project_path,
                resource_paths=resource_paths,
                import_output=output,
                output=output,
                message=f"Headless Godot import timed out after {timeout} seconds.",
                boot_frames=boot_frames,
                output_issues=output_issues,
            )
        import_output = import_result.stdout
        import_returncode = import_result.returncode
        import_output_issues = detect_godot_output_issues(import_output)
        if import_result.returncode != 0 and not import_output_issues and not load_resources:
            try:
                fallback_result = _run_godot_import_without_audio(
                    resolved_binary,
                    godot_project_path,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                fallback_output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                combined_output = _combine_output(import_output, fallback_output)
                output_issues = detect_godot_output_issues(combined_output)
                if not output_issues and boot_frames == 0:
                    return GodotValidationReport(
                        status="passed",
                        godot_binary=resolved_binary,
                        project_path=godot_project_path,
                        resource_paths=resource_paths,
                        import_output=combined_output,
                        output=combined_output,
                        message=_audio_fallback_timeout_message(timeout, len(importable_asset_paths), len(resource_paths)),
                        boot_frames=boot_frames,
                        output_issues=(),
                    )
                return GodotValidationReport(
                    status="failed",
                    godot_binary=resolved_binary,
                    project_path=godot_project_path,
                    resource_paths=resource_paths,
                    import_output=combined_output,
                    output=combined_output,
                    message=f"Headless Godot no-audio import fallback timed out after {timeout} seconds.",
                    boot_frames=boot_frames,
                    output_issues=output_issues,
                )

            fallback_output = fallback_result.stdout
            combined_output = _combine_output(import_output, fallback_output)
            fallback_output_issues = detect_godot_output_issues(combined_output)
            if fallback_result.returncode == 0 and not fallback_output_issues:
                if boot_frames > 0:
                    return _run_godot_boot_validation(
                        resolved_binary,
                        godot_project_path,
                        resource_paths=resource_paths,
                        import_returncode=fallback_result.returncode,
                        import_output=combined_output,
                        previous_output=combined_output,
                        boot_frames=boot_frames,
                        timeout=timeout,
                    )
                return GodotValidationReport(
                    status="passed",
                    godot_binary=resolved_binary,
                    project_path=godot_project_path,
                    resource_paths=resource_paths,
                    returncode=fallback_result.returncode,
                    import_returncode=fallback_result.returncode,
                    import_output=combined_output,
                    output=combined_output,
                    message=_audio_fallback_message(
                        import_result.returncode,
                        fallback_result.returncode,
                        len(importable_asset_paths),
                        (),
                    ),
                    boot_frames=boot_frames,
                    output_issues=(),
                )
            else:
                return GodotValidationReport(
                    status="failed",
                    godot_binary=resolved_binary,
                    project_path=godot_project_path,
                    resource_paths=resource_paths,
                    returncode=fallback_result.returncode,
                    import_returncode=fallback_result.returncode,
                    import_output=combined_output,
                    output=combined_output,
                    message=_audio_fallback_message(
                        import_result.returncode,
                        fallback_result.returncode,
                        len(importable_asset_paths),
                        fallback_output_issues,
                    ),
                    boot_frames=boot_frames,
                    output_issues=fallback_output_issues,
                )
        if import_result.returncode != 0 or import_output_issues:
            return GodotValidationReport(
                status="failed",
                godot_binary=resolved_binary,
                project_path=godot_project_path,
                resource_paths=resource_paths,
                returncode=import_result.returncode,
                import_returncode=import_result.returncode,
                import_output=import_output,
                output=import_output,
                message=_import_message(import_result.returncode, len(importable_asset_paths), import_output_issues),
                boot_frames=boot_frames,
                output_issues=import_output_issues,
            )

    if not load_resources:
        if boot_frames > 0:
            return _run_godot_boot_validation(
                resolved_binary,
                godot_project_path,
                resource_paths=resource_paths,
                import_returncode=import_returncode,
                import_output=import_output,
                previous_output=import_output,
                boot_frames=boot_frames,
                timeout=timeout,
            )
        return GodotValidationReport(
            status="passed",
            godot_binary=resolved_binary,
            project_path=godot_project_path,
            resource_paths=resource_paths,
            returncode=import_returncode,
            import_returncode=import_returncode,
            import_output=import_output,
            output=import_output,
            message=_import_only_message(import_returncode, len(importable_asset_paths), len(resource_paths)),
            boot_frames=boot_frames,
            output_issues=(),
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "gm2godot_validate.gd")
        with open(script_path, "w", encoding="utf-8") as script_file:
            script_file.write(script)
        try:
            result = _run_godot_command(
                [
                    resolved_binary,
                    "--headless",
                    "--path",
                    godot_project_path,
                    "--script",
                    script_path,
                ],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
            combined_output = _combine_output(import_output, output)
            return GodotValidationReport(
                status="failed",
                godot_binary=resolved_binary,
                project_path=godot_project_path,
                resource_paths=resource_paths,
                import_returncode=import_returncode,
                import_output=import_output,
                output=combined_output,
                message=f"Headless Godot validation timed out after {timeout} seconds.",
                boot_frames=boot_frames,
                output_issues=detect_godot_output_issues(combined_output),
            )

    combined_output = _combine_output(import_output, result.stdout)
    output_issues = detect_godot_output_issues(combined_output)
    status: GodotValidationStatus = (
        "passed" if result.returncode == 0 and not output_issues else "failed"
    )

    resource_report = GodotValidationReport(
        status=status,
        godot_binary=resolved_binary,
        project_path=godot_project_path,
        resource_paths=resource_paths,
        returncode=result.returncode,
        import_returncode=import_returncode,
        import_output=import_output,
        output=combined_output,
        message=_validation_message(result.returncode, len(resource_paths), output_issues),
        boot_frames=boot_frames,
        output_issues=output_issues,
    )
    if status == "failed" or boot_frames == 0:
        return resource_report

    return _run_godot_boot_validation(
        resolved_binary,
        godot_project_path,
        resource_paths=resource_paths,
        import_returncode=import_returncode,
        import_output=import_output,
        previous_output=combined_output,
        boot_frames=boot_frames,
        timeout=timeout,
    )


def write_godot_validation_report(
    godot_project_path: str,
    report: GodotValidationReport,
) -> str:
    report_path = os.path.join(godot_project_path, GODOT_VALIDATION_REPORT_RELATIVE_PATH)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(report.to_dict(), report_file, indent=2, sort_keys=True)
        report_file.write("\n")
    return report_path


def generated_godot_resource_paths(godot_project_path: str) -> tuple[str, ...]:
    resource_paths: list[str] = []
    if not os.path.isdir(godot_project_path):
        return ()
    for root, dirs, files in os.walk(godot_project_path):
        dirs[:] = sorted(directory for directory in dirs if directory != ".godot")
        for filename in sorted(files):
            if not filename.endswith(_LOADABLE_EXTENSIONS):
                continue
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, godot_project_path).replace(os.sep, "/")
            resource_paths.append("res://" + relative_path)
    return tuple(sorted(resource_paths))


def generated_godot_importable_asset_paths(godot_project_path: str) -> tuple[str, ...]:
    asset_paths: list[str] = []
    if not os.path.isdir(godot_project_path):
        return ()
    for root, dirs, files in os.walk(godot_project_path):
        dirs[:] = sorted(directory for directory in dirs if directory != ".godot")
        for filename in sorted(files):
            if not filename.lower().endswith(_IMPORTABLE_EXTENSIONS):
                continue
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, godot_project_path).replace(os.sep, "/")
            asset_paths.append("res://" + relative_path)
    return tuple(sorted(asset_paths))


def detect_godot_output_issues(output: str) -> tuple[GodotOutputIssue, ...]:
    issues: list[GodotOutputIssue] = []
    for line in output.splitlines():
        stripped = _strip_ansi_escape_sequences(line).strip()
        if not stripped:
            continue
        severity = _godot_output_issue_severity(stripped)
        if severity is not None:
            issues.append(GodotOutputIssue(severity=severity, line=stripped))
    return tuple(issues)


def _godot_output_issue_severity(line: str) -> GodotOutputIssueSeverity | None:
    stripped = _strip_ansi_escape_sequences(line).strip()
    if stripped.startswith(_GODOT_ERROR_PREFIXES):
        return "error"
    if stripped.startswith(_GODOT_WARNING_PREFIXES):
        return "warning"
    return None


def _strip_ansi_escape_sequences(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def _run_godot_command(
    command: list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    output = _BoundedGodotOutput(_GODOT_OUTPUT_CAPTURE_LIMIT_BYTES)
    process: subprocess.Popen[bytes] = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name == "posix",
    )
    output_stream = process.stdout
    if output_stream is None:
        process.kill()
        process.wait()
        raise RuntimeError("Godot output pipe was not created.")

    deadline = time.monotonic() + max(0, timeout)
    reader_errors: list[OSError] = []
    reader_stop = threading.Event()
    output_fd = output_stream.fileno()
    os.set_blocking(output_fd, False)

    def read_output() -> None:
        while not reader_stop.is_set():
            try:
                chunk = os.read(output_fd, _GODOT_OUTPUT_READ_CHUNK_BYTES)
            except BlockingIOError:
                reader_stop.wait(_GODOT_OUTPUT_READER_POLL_SECONDS)
                continue
            except OSError as exc:
                reader_errors.append(exc)
                return
            if not chunk:
                return
            output.append(chunk)

    output_reader = threading.Thread(
        target=read_output,
        name="gm2godot-godot-output-reader",
        daemon=True,
    )
    output_reader.start()

    try:
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _kill_godot_process(process)
        process.wait()
        _finish_godot_output_reader(output_reader, reader_stop)
        output_stream.close()
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=output.text(),
        ) from None

    if output_reader.is_alive():
        # The direct process has exited, so an open pipe now belongs to a
        # descendant. Clean up the validation process group instead of waiting
        # indefinitely for that inherited descriptor to close.
        _kill_godot_process(process)
    _finish_godot_output_reader(output_reader, reader_stop)
    output_stream.close()
    if reader_errors:
        raise RuntimeError("Failed while capturing Godot output.") from reader_errors[0]
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=output.text(),
        stderr=None,
    )


def _finish_godot_output_reader(
    output_reader: threading.Thread,
    reader_stop: threading.Event,
) -> None:
    output_reader.join(timeout=_GODOT_OUTPUT_READER_DRAIN_GRACE_SECONDS)
    if not output_reader.is_alive():
        return
    reader_stop.set()
    output_reader.join(timeout=_GODOT_OUTPUT_READER_STOP_GRACE_SECONDS)
    if output_reader.is_alive():
        raise RuntimeError("Godot output reader did not stop after pipe cleanup.")


def _kill_godot_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    if process.poll() is None:
        process.kill()


def _run_godot_import(
    resolved_binary: str,
    godot_project_path: str,
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return _run_godot_command(
        [
            resolved_binary,
            "--headless",
            "--recovery-mode",
            "--path",
            godot_project_path,
            "--import",
        ],
        timeout=timeout,
    )


def _run_godot_import_without_audio(
    resolved_binary: str,
    godot_project_path: str,
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        validation_project_path = os.path.join(temp_dir, "godot_project")
        shutil.copytree(
            godot_project_path,
            validation_project_path,
            ignore=_ignore_audio_import_validation_files,
        )
        return _run_godot_import(
            resolved_binary,
            validation_project_path,
            timeout=timeout,
        )


def _run_godot_boot_validation(
    resolved_binary: str,
    godot_project_path: str,
    *,
    resource_paths: tuple[str, ...],
    import_returncode: int | None,
    import_output: str,
    previous_output: str,
    boot_frames: int,
    timeout: int,
) -> GodotValidationReport:
    try:
        boot_result = _run_godot_boot(
            resolved_binary,
            godot_project_path,
            boot_frames=boot_frames,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        boot_output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
        combined_output = _combine_output(previous_output, boot_output)
        output_issues = detect_godot_output_issues(combined_output)
        return GodotValidationReport(
            status="failed",
            godot_binary=resolved_binary,
            project_path=godot_project_path,
            resource_paths=resource_paths,
            import_returncode=import_returncode,
            import_output=import_output,
            boot_output=boot_output,
            output=combined_output,
            message=f"Headless Godot boot timed out after {timeout} seconds.",
            boot_frames=boot_frames,
            output_issues=output_issues,
        )

    boot_output = boot_result.stdout
    combined_output = _combine_output(previous_output, boot_output)
    output_issues = detect_godot_output_issues(combined_output)
    status: GodotValidationStatus = (
        "passed" if boot_result.returncode == 0 and not output_issues else "failed"
    )
    return GodotValidationReport(
        status=status,
        godot_binary=resolved_binary,
        project_path=godot_project_path,
        resource_paths=resource_paths,
        returncode=boot_result.returncode,
        import_returncode=import_returncode,
        boot_returncode=boot_result.returncode,
        import_output=import_output,
        boot_output=boot_output,
        output=combined_output,
        message=_boot_message(boot_result.returncode, boot_frames, output_issues),
        boot_frames=boot_frames,
        output_issues=output_issues,
    )


def _run_godot_boot(
    resolved_binary: str,
    godot_project_path: str,
    *,
    boot_frames: int,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return _run_godot_command(
        [
            resolved_binary,
            "--headless",
            "--disable-vsync",
            "--fixed-fps",
            "60",
            "--path",
            godot_project_path,
            "--quit-after",
            str(boot_frames),
        ],
        timeout=timeout,
    )


def _ignore_audio_import_validation_files(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name == ".godot" or name.lower().endswith(_AUDIO_IMPORTABLE_EXTENSIONS)
    }


def _combine_output(import_output: str, validation_output: str) -> str:
    if not import_output:
        return validation_output
    if not validation_output:
        return import_output
    return import_output.rstrip() + "\n" + validation_output


def _import_message(
    returncode: int,
    importable_asset_count: int,
    output_issues: tuple[GodotOutputIssue, ...],
) -> str:
    if output_issues:
        error_count = sum(1 for issue in output_issues if issue.severity == "error")
        warning_count = sum(1 for issue in output_issues if issue.severity == "warning")
        return (
            "Headless Godot import reported "
            f"{error_count} error(s) and {warning_count} warning(s) "
            f"while importing {importable_asset_count} generated asset(s)."
        )
    if returncode == 0:
        return f"Headless Godot import completed for {importable_asset_count} generated asset(s)."
    return "Headless Godot import failed while importing generated assets."


def _import_only_message(
    returncode: int | None,
    importable_asset_count: int,
    resource_count: int,
) -> str:
    if returncode == 0:
        return (
            "Headless Godot import completed without warning/error output for "
            f"{importable_asset_count} generated asset(s); skipped loading "
            f"{resource_count} generated scripts/scenes/resources."
        )
    if returncode is None:
        return (
            "Headless Godot import-only validation skipped resource loading, but "
            "there were no importable generated assets to force a Godot scan."
        )
    return "Headless Godot import-only validation failed while importing generated assets."


def _import_only_timeout_message(
    timeout: int,
    importable_asset_count: int,
    resource_count: int,
) -> str:
    return (
        "Headless Godot import ran for "
        f"{timeout} seconds without warning/error output while scanning "
        f"{importable_asset_count} generated asset(s); skipped loading "
        f"{resource_count} generated scripts/scenes/resources."
    )


def _audio_fallback_message(
    original_returncode: int,
    fallback_returncode: int,
    importable_asset_count: int,
    output_issues: tuple[GodotOutputIssue, ...],
) -> str:
    if output_issues:
        error_count = sum(1 for issue in output_issues if issue.severity == "error")
        warning_count = sum(1 for issue in output_issues if issue.severity == "warning")
        return (
            "Headless Godot import exited with code "
            f"{original_returncode}; no-audio import fallback reported "
            f"{error_count} error(s) and {warning_count} warning(s) while scanning "
            f"{importable_asset_count} generated asset(s)."
        )
    if fallback_returncode == 0:
        return (
            "Headless Godot import exited with code "
            f"{original_returncode} without warning/error output; no-audio import "
            f"fallback completed for {importable_asset_count} generated asset(s)."
        )
    return (
        "Headless Godot import exited with code "
        f"{original_returncode}; no-audio import fallback exited with code "
        f"{fallback_returncode} while scanning generated assets."
    )


def _audio_fallback_timeout_message(
    timeout: int,
    importable_asset_count: int,
    resource_count: int,
) -> str:
    return (
        "Headless Godot import exited nonzero without warning/error output; no-audio "
        f"import fallback ran for {timeout} seconds while scanning "
        f"{importable_asset_count} generated asset(s); skipped loading "
        f"{resource_count} generated scripts/scenes/resources."
    )


def _validation_message(
    returncode: int,
    resource_count: int,
    output_issues: tuple[GodotOutputIssue, ...],
) -> str:
    if output_issues:
        error_count = sum(1 for issue in output_issues if issue.severity == "error")
        warning_count = sum(1 for issue in output_issues if issue.severity == "warning")
        return (
            "Headless Godot validation reported "
            f"{error_count} error(s) and {warning_count} warning(s) "
            "while loading generated scripts/scenes/resources."
        )
    if returncode == 0:
        return f"Headless Godot validation loaded {resource_count} generated resources."
    return "Headless Godot validation failed while loading generated scripts/scenes/resources."


def _validation_script(resource_paths: tuple[str, ...]) -> str:
    resource_json = json.dumps(list(resource_paths), indent=2)
    return (
        "extends SceneTree\n\n"
        f"const RESOURCE_PATHS = {resource_json}\n\n"
        "func _initialize():\n"
        "\tvar failures = []\n"
        "\tfor resource_path in RESOURCE_PATHS:\n"
        "\t\tvar resource = ResourceLoader.load(resource_path)\n"
        "\t\tif resource == null:\n"
        "\t\t\tfailures.append(resource_path)\n"
        "\tif failures.is_empty():\n"
        "\t\tprint(\"GM2GODOT_VALIDATION_OK \" + str(RESOURCE_PATHS.size()))\n"
        "\t\tquit(0)\n"
        "\t\treturn\n"
        "\tfor failure in failures:\n"
        "\t\tpush_error(\"GM2Godot generated resource failed to load: \" + str(failure))\n"
        "\tquit(1)\n"
    )


def _boot_message(
    returncode: int,
    boot_frames: int,
    output_issues: tuple[GodotOutputIssue, ...],
) -> str:
    if output_issues:
        error_count = sum(1 for issue in output_issues if issue.severity == "error")
        warning_count = sum(1 for issue in output_issues if issue.severity == "warning")
        return (
            "Headless Godot boot reported "
            f"{error_count} error(s) and {warning_count} warning(s) while running "
            f"the project main scene for {boot_frames} frame(s)."
        )
    if returncode == 0:
        return (
            "Headless Godot boot ran the project main scene for "
            f"{boot_frames} frame(s) without warning/error output."
        )
    return (
        "Headless Godot boot exited with code "
        f"{returncode} while running the project main scene for {boot_frames} frame(s)."
    )
