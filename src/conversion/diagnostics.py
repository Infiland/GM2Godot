from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import threading
from dataclasses import dataclass
from typing import Callable, Literal, TypeAlias, cast

from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.type_defs import StrPath

DiagnosticSeverity: TypeAlias = Literal["info", "warning", "error"]

DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.json"
)
DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.md"
)


@dataclass(frozen=True)
class _ReportTargetState:
    identity: tuple[int, int] | None
    mode: int | None


@dataclass(frozen=True)
class ConversionDiagnostic:
    severity: DiagnosticSeverity
    code: str
    message: str
    source_path: str | None = None
    line: int | None = None
    column: int | None = None
    resource: str | None = None
    resource_type: str | None = None
    event: str | None = None
    api: str | None = None
    manifest_entry: str | None = None
    issue_number: int | None = None
    workaround: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source_path": self.source_path,
            "line": self.line,
            "column": self.column,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "event": self.event,
            "api": self.api,
            "manifest_entry": self.manifest_entry,
            "issue_number": self.issue_number,
            "workaround": self.workaround,
        }


class DiagnosticCollector:
    def __init__(self) -> None:
        self._diagnostics: list[ConversionDiagnostic] = []
        self._recorded_diagnostics: set[ConversionDiagnostic] = set()
        self._recorded_messages: set[str] = set()
        self._outcome: ConversionOutcome | None = None
        self._lock = threading.RLock()

    def set_outcome(self, outcome: ConversionOutcome) -> None:
        with self._lock:
            self._outcome = outcome

    def outcome(self) -> ConversionOutcome | None:
        with self._lock:
            return self._outcome

    def add(
        self,
        severity: DiagnosticSeverity,
        code: str,
        message: str,
        *,
        source_path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        event: str | None = None,
        api: str | None = None,
        manifest_entry: str | None = None,
        issue_number: int | None = None,
        workaround: str | None = None,
    ) -> ConversionDiagnostic:
        diagnostic = ConversionDiagnostic(
            severity=severity,
            code=code,
            message=message,
            source_path=source_path,
            line=line,
            column=column,
            resource=resource,
            resource_type=resource_type,
            event=event,
            api=api,
            manifest_entry=manifest_entry,
            issue_number=issue_number,
            workaround=workaround,
        )
        with self._lock:
            if diagnostic in self._recorded_diagnostics:
                return diagnostic
            self._diagnostics.append(diagnostic)
            self._recorded_diagnostics.add(diagnostic)
            self._recorded_messages.add(message)
        return diagnostic

    def add_from_log_message(
        self, message: str, *, code: str = "GM2GD-WARNING"
    ) -> ConversionDiagnostic | None:
        stripped = message.strip()
        severity = _severity_from_log_message(stripped)
        if severity is None:
            return None
        with self._lock:
            if stripped in self._recorded_messages:
                return None
            return self.add(severity, code, stripped)

    def add_transpile_failure(
        self,
        message: str,
        *,
        source_path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        event: str | None = None,
        workaround: str | None = None,
    ) -> ConversionDiagnostic:
        api_name = _extract_gml_api_name(message)
        issue_number = _extract_issue_number(message)
        return self.add(
            "warning",
            "GM2GD-GML-TRANSPILE",
            message,
            source_path=source_path,
            line=line,
            column=column,
            resource=resource,
            resource_type=resource_type,
            event=event,
            api=api_name,
            manifest_entry=api_name,
            issue_number=issue_number,
            workaround=workaround,
        )

    def wrap_log_callback(
        self, log_callback: Callable[[str], None]
    ) -> Callable[[str], None]:
        def _wrapped(message: str) -> None:
            self.add_from_log_message(message)
            log_callback(message)

        return _wrapped

    def diagnostics(self) -> tuple[ConversionDiagnostic, ...]:
        with self._lock:
            return tuple(self._diagnostics)

    def summary(self) -> dict[str, int]:
        counts = {"info": 0, "warning": 0, "error": 0}
        for diagnostic in self._diagnostics:
            counts[diagnostic.severity] += 1
        counts["total"] = len(self._diagnostics)
        return counts

    def to_json_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "summary": self.summary(),
            "diagnostics": [
                diagnostic.to_dict()
                for diagnostic in self._sorted_diagnostics()
            ],
        }
        outcome = self.outcome()
        if outcome is not None:
            payload["outcome"] = outcome.to_dict()
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2, sort_keys=True) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# GM2Godot Conversion Diagnostics",
            "",
        ]
        outcome = self.outcome()
        if outcome is not None:
            lines.extend(
                [
                    f"Conversion outcome: `{outcome.state}`",
                    "",
                    outcome.summary_line(),
                    "",
                ]
            )
        lines.extend(
            [
                "| Severity | Code | Source | Resource | Event/API | Message |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        diagnostics = self._sorted_diagnostics()
        if not diagnostics:
            lines.append("| info | GM2GD-OK |  |  |  | No diagnostics recorded. |")
            return "\n".join(lines) + "\n"

        for diagnostic in diagnostics:
            source = diagnostic.source_path or ""
            resource_parts = [
                value
                for value in (diagnostic.resource_type, diagnostic.resource)
                if value
            ]
            event_api = diagnostic.event or diagnostic.api or ""
            message = _escape_markdown_table(diagnostic.message)
            lines.append(
                "| {severity} | {code} | {source} | {resource} | {event_api} | {message} |".format(
                    severity=diagnostic.severity,
                    code=diagnostic.code,
                    source=_escape_markdown_table(source),
                    resource=_escape_markdown_table("/".join(resource_parts)),
                    event_api=_escape_markdown_table(event_api),
                    message=message,
                )
            )
        return "\n".join(lines) + "\n"

    def write_reports(self, godot_project_path: StrPath) -> tuple[str, str]:
        """Publish both reports with best-effort in-process rollback.

        The two final ``os.replace`` calls cannot be made crash-atomic as a
        pair.  Each individual report is staged completely before publication,
        and an exception during the second replacement restores the first one
        when its original backup is still available.
        """
        json_content = self.to_json()
        markdown_content = self.to_markdown()
        json_path, markdown_path = _diagnostic_report_paths(godot_project_path)
        report_directory = os.path.dirname(json_path)
        report_directory_identity = _prepare_report_directory(report_directory)

        temporary_paths: set[str] = set()
        published_identities: dict[str, tuple[int, int]] = {}
        try:
            _verify_report_directory(
                report_directory,
                report_directory_identity,
            )
            json_state = _report_target_state(json_path)
            markdown_state = _report_target_state(markdown_path)
            json_stage = _stage_report_text(
                json_path,
                json_content,
                mode=json_state.mode,
            )
            temporary_paths.add(json_stage)
            _verify_report_directory(
                report_directory,
                report_directory_identity,
            )
            markdown_stage = _stage_report_text(
                markdown_path,
                markdown_content,
                mode=markdown_state.mode,
            )
            temporary_paths.add(markdown_stage)

            _verify_report_directory(
                report_directory,
                report_directory_identity,
            )
            json_backup = _stage_existing_report(json_path, json_state)
            if json_backup is not None:
                temporary_paths.add(json_backup)
            _verify_report_directory(
                report_directory,
                report_directory_identity,
            )
            markdown_backup = _stage_existing_report(
                markdown_path,
                markdown_state,
            )
            if markdown_backup is not None:
                temporary_paths.add(markdown_backup)

            try:
                _verify_report_directory(
                    report_directory,
                    report_directory_identity,
                )
                _verify_report_target_state(markdown_path, markdown_state)
                markdown_stage_identity = _regular_path_identity(markdown_stage)
                _publish_staged_report(
                    markdown_stage,
                    markdown_path,
                    markdown_stage_identity,
                    temporary_paths,
                    published_identities,
                )

                _verify_report_directory(
                    report_directory,
                    report_directory_identity,
                )
                _verify_report_target_state(json_path, json_state)
                json_stage_identity = _regular_path_identity(json_stage)
                _publish_staged_report(
                    json_stage,
                    json_path,
                    json_stage_identity,
                    temporary_paths,
                    published_identities,
                )
            except BaseException as publish_error:
                rollback_errors = _restore_report_pair(
                    json_path=json_path,
                    json_backup=json_backup,
                    markdown_path=markdown_path,
                    markdown_backup=markdown_backup,
                    temporary_paths=temporary_paths,
                    published_identities=published_identities,
                )
                if rollback_errors:
                    publish_error.add_note(
                        "Diagnostics rollback also failed: "
                        + "; ".join(str(error) for error in rollback_errors)
                    )
                raise
        finally:
            for temporary_path in temporary_paths:
                try:
                    _verify_report_directory(
                        report_directory,
                        report_directory_identity,
                    )
                except OSError:
                    break
                _unlink_best_effort(temporary_path)

        return json_path, markdown_path

    def _sorted_diagnostics(self) -> tuple[ConversionDiagnostic, ...]:
        return tuple(
            sorted(
                self._diagnostics,
                key=lambda item: (
                    item.severity,
                    item.code,
                    item.source_path or "",
                    item.resource_type or "",
                    item.resource or "",
                    item.event or "",
                    item.message,
                ),
            )
        )


def invalidate_conversion_diagnostic_reports(godot_project_path: StrPath) -> None:
    """Best-effort removal of a diagnostic report pair known to be stale."""
    report_paths = _diagnostic_report_paths(godot_project_path)
    report_directory = os.path.dirname(report_paths[0])
    try:
        directory_stat = os.lstat(report_directory)
    except OSError:
        return
    if _path_is_redirected(report_directory, directory_stat) or not stat.S_ISDIR(
        directory_stat.st_mode
    ):
        return
    directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
    for report_path in report_paths:
        try:
            _verify_report_directory(report_directory, directory_identity)
        except OSError:
            return
        _unlink_best_effort(report_path)


def _diagnostic_report_paths(godot_project_path: StrPath) -> tuple[str, str]:
    root = os.fspath(godot_project_path)
    return (
        os.path.join(root, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
        os.path.join(root, DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH),
    )


def _prepare_report_directory(path: str) -> tuple[int, int]:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        os.makedirs(path, exist_ok=True)
        path_stat = os.lstat(path)
    if _path_is_redirected(path, path_stat) or not stat.S_ISDIR(path_stat.st_mode):
        raise OSError(f"Refusing redirected diagnostic report directory: {path}")
    return (path_stat.st_dev, path_stat.st_ino)


def _verify_report_directory(
    path: str,
    expected_identity: tuple[int, int],
) -> None:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise OSError(f"Diagnostic report directory changed: {path}") from error
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Diagnostic report directory changed: {path}")


def _path_is_redirected(path: str, path_stat: os.stat_result) -> bool:
    """Return whether a path is a symbolic link or Windows junction."""
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def _report_target_state(path: str) -> _ReportTargetState:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return _ReportTargetState(identity=None, mode=None)
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Refusing non-regular diagnostic report: {path}")
    return _ReportTargetState(
        identity=(path_stat.st_dev, path_stat.st_ino),
        mode=stat.S_IMODE(path_stat.st_mode),
    )


def _verify_report_target_state(
    path: str,
    expected: _ReportTargetState,
) -> None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if expected.identity is None:
            return
        raise OSError(f"Diagnostic report disappeared during publication: {path}")
    if (
        expected.identity is None
        or not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected.identity
    ):
        raise OSError(f"Diagnostic report changed during publication: {path}")


def _regular_path_identity(path: str) -> tuple[int, int]:
    path_stat = os.lstat(path)
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Refusing non-regular staged diagnostic report: {path}")
    return (path_stat.st_dev, path_stat.st_ino)


def _publish_staged_report(
    staged_path: str,
    report_path: str,
    staged_identity: tuple[int, int],
    temporary_paths: set[str],
    published_identities: dict[str, tuple[int, int]],
) -> None:
    try:
        os.replace(staged_path, report_path)
    except BaseException:
        try:
            replacement_completed = (
                _regular_path_identity(report_path) == staged_identity
            )
        except OSError:
            replacement_completed = False
        if replacement_completed:
            temporary_paths.discard(staged_path)
            published_identities[report_path] = staged_identity
        raise
    temporary_paths.discard(staged_path)
    published_identities[report_path] = staged_identity


def _stage_report_text(path: str, content: str, *, mode: int | None) -> str:
    return _stage_report_bytes(
        path,
        content.encode("utf-8"),
        mode=mode,
        suffix=".tmp",
    )


def _stage_existing_report(
    path: str,
    expected: _ReportTargetState,
) -> str | None:
    if expected.identity is None:
        return None
    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, open_flags)
    try:
        open_stat = os.fstat(file_descriptor)
        path_stat = os.lstat(path)
        open_identity = (open_stat.st_dev, open_stat.st_ino)
        if (
            not stat.S_ISREG(open_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or open_identity != expected.identity
            or (path_stat.st_dev, path_stat.st_ino) != open_identity
        ):
            raise OSError(
                f"Diagnostic report changed while creating its backup: {path}"
            )
        with os.fdopen(file_descriptor, "rb") as report_file:
            file_descriptor = -1
            content = report_file.read()
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    _verify_report_target_state(path, expected)
    return _stage_report_bytes(
        path,
        content,
        mode=expected.mode,
        suffix=".backup",
    )


def _stage_report_bytes(
    path: str,
    content: bytes,
    *,
    mode: int | None,
    suffix: str,
) -> str:
    report_directory = os.path.dirname(path) or os.curdir
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=report_directory,
        prefix=f".{os.path.basename(path)}.",
        suffix=suffix,
    )
    staged_pending = True
    try:
        # mkstemp's restrictive mode is retained for a new report, so the
        # process umask is never bypassed.  An existing regular report keeps
        # its prior mode through the path-based chmod available on Windows.
        if mode is not None:
            os.chmod(staged_path, mode)
        staged_file = os.fdopen(file_descriptor, "wb")
        file_descriptor = -1
        with staged_file:
            staged_file.write(content)
            staged_file.flush()
            os.fsync(staged_file.fileno())
        staged_pending = False
        return staged_path
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if staged_pending:
            _unlink_best_effort(staged_path)


def _restore_report_pair(
    *,
    json_path: str,
    json_backup: str | None,
    markdown_path: str,
    markdown_backup: str | None,
    temporary_paths: set[str],
    published_identities: dict[str, tuple[int, int]],
) -> list[BaseException]:
    rollback_errors: list[BaseException] = []
    for report_path, backup_path in (
        (markdown_path, markdown_backup),
        (json_path, json_backup),
    ):
        published_identity = published_identities.get(report_path)
        if published_identity is None:
            continue
        try:
            current_identity = _regular_path_identity(report_path)
            if current_identity != published_identity:
                raise OSError(
                    "Published diagnostic report changed before rollback: "
                    f"{report_path}"
                )
            if backup_path is None:
                os.unlink(report_path)
            else:
                backup_identity = _regular_path_identity(backup_path)
                try:
                    os.replace(backup_path, report_path)
                except BaseException:
                    try:
                        replacement_completed = (
                            _regular_path_identity(report_path)
                            == backup_identity
                        )
                    except OSError:
                        replacement_completed = False
                    if not replacement_completed:
                        raise
                temporary_paths.discard(backup_path)
        except FileNotFoundError as error:
            if backup_path is None:
                continue
            temporary_paths.discard(backup_path)
            error.add_note(
                f"Previous diagnostic report preserved at: {backup_path}"
            )
            rollback_errors.append(error)
        except BaseException as error:
            if backup_path is not None:
                # This is the last recoverable copy of the pre-publication
                # report.  Leave it beside the reports for manual recovery.
                temporary_paths.discard(backup_path)
                error.add_note(
                    f"Previous diagnostic report preserved at: {backup_path}"
                )
            rollback_errors.append(error)
    return rollback_errors


def _unlink_best_effort(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def write_conversion_diagnostic_reports(
    godot_project_path: StrPath, diagnostics: DiagnosticCollector
) -> tuple[str, str]:
    return diagnostics.write_reports(godot_project_path)


def _escape_markdown_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _severity_from_log_message(message: str) -> DiagnosticSeverity | None:
    normalized = message.lower()
    if normalized.startswith("info:"):
        return "info"
    if normalized.startswith("warning:"):
        return "warning"
    if normalized.startswith("error:"):
        return "error"
    return None


def _extract_gml_api_name(message: str) -> str | None:
    match = re.search(r"GML API '([^']+)'", message)
    if match is None:
        return None
    return match.group(1)


def _extract_issue_number(message: str) -> int | None:
    match = re.search(r"tracked by #(\d+)", message)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
