from __future__ import annotations

import hashlib
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
FileFingerprint: TypeAlias = tuple[int, int, int, int, int]
PathIdentity: TypeAlias = tuple[int, int]

# Windows models ``chmod`` as a read-only file attribute rather than the full
# POSIX permission mask.  Keep this as a module-level capability flag so the
# Windows replacement rules can be exercised narrowly on other platforms.
_WINDOWS_READONLY_FILE_ATTRIBUTES = os.name == "nt"

DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.json"
)
DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.md"
)


@dataclass(frozen=True)
class _ReportTargetState:
    fingerprint: FileFingerprint | None
    mode: int | None

    @property
    def identity(self) -> PathIdentity | None:
        if self.fingerprint is None:
            return None
        return self.fingerprint[:2]


@dataclass(frozen=True)
class DiagnosticReportFingerprint:
    """Exact identity and content fingerprint for one diagnostic report."""

    stat: FileFingerprint
    mode: int
    sha256: str

    @property
    def identity(self) -> PathIdentity:
        return self.stat[:2]


@dataclass(frozen=True)
class DiagnosticReportFileSnapshot:
    """Exact pre-publication state of one present or absent report."""

    content: bytes | None
    fingerprint: DiagnosticReportFingerprint | None

    @property
    def mode(self) -> int | None:
        if self.fingerprint is None:
            return None
        return self.fingerprint.mode


@dataclass(frozen=True)
class ConversionDiagnosticReportSnapshot:
    """Exact state of the diagnostic report pair before it is rewritten."""

    json_path: str
    markdown_path: str
    directory_identity: PathIdentity
    json_report: DiagnosticReportFileSnapshot
    markdown_report: DiagnosticReportFileSnapshot


@dataclass(frozen=True)
class ConversionDiagnosticReportPublicationReceipt:
    """Identity proof for the exact report pair published by one write."""

    json_path: str
    markdown_path: str
    directory_identity: PathIdentity
    json_report: DiagnosticReportFingerprint
    markdown_report: DiagnosticReportFingerprint


@dataclass(frozen=True)
class _TemporaryReport:
    path: str
    fingerprint: DiagnosticReportFingerprint
    destination_mode: int


@dataclass(frozen=True)
class _PublishedReport:
    path: str
    fingerprint: DiagnosticReportFingerprint | None
    backup: _TemporaryReport | None


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

    def publish_reports(
        self,
        godot_project_path: StrPath,
    ) -> ConversionDiagnosticReportPublicationReceipt:
        """Publish both reports and return proof of their exact committed state."""
        json_path, markdown_path = _normalized_diagnostic_report_paths(
            godot_project_path
        )
        report_directory = os.path.dirname(json_path)
        directory_identity = _prepare_report_directory(report_directory)
        _verify_report_directory(report_directory, directory_identity)
        json_state = _report_target_state(json_path)
        markdown_state = _report_target_state(markdown_path)
        previous_json = _capture_report_file(json_path, json_state)
        previous_markdown = _capture_report_file(markdown_path, markdown_state)
        _verify_report_file_snapshot(json_path, previous_json)
        _verify_report_file_snapshot(markdown_path, previous_markdown)
        json_report, markdown_report = _publish_report_pair(
            json_path=json_path,
            json_content=self.to_json().encode("utf-8"),
            json_mode=json_state.mode,
            markdown_path=markdown_path,
            markdown_content=self.to_markdown().encode("utf-8"),
            markdown_mode=markdown_state.mode,
            expected_json_state=json_state,
            expected_markdown_state=markdown_state,
            report_directory=report_directory,
            directory_identity=directory_identity,
            exact_json_fingerprint=previous_json.fingerprint,
            exact_markdown_fingerprint=previous_markdown.fingerprint,
        )
        if json_report is None or markdown_report is None:
            raise AssertionError("Published diagnostic reports must both be present.")
        return ConversionDiagnosticReportPublicationReceipt(
            json_path=json_path,
            markdown_path=markdown_path,
            directory_identity=directory_identity,
            json_report=json_report,
            markdown_report=markdown_report,
        )

    def write_reports(self, godot_project_path: StrPath) -> tuple[str, str]:
        """Publish both reports while preserving the legacy path tuple API."""
        self.publish_reports(godot_project_path)
        return _diagnostic_report_paths(godot_project_path)

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


def capture_conversion_diagnostic_reports(
    godot_project_path: StrPath,
) -> ConversionDiagnosticReportSnapshot:
    """Capture exact report bytes and metadata without following redirects."""
    json_path, markdown_path = _normalized_diagnostic_report_paths(
        godot_project_path
    )
    report_directory = os.path.dirname(json_path)
    directory_identity = _prepare_report_directory(report_directory)
    _verify_report_directory(report_directory, directory_identity)
    json_report = _capture_report_file(json_path, _report_target_state(json_path))
    _verify_report_directory(report_directory, directory_identity)
    markdown_report = _capture_report_file(
        markdown_path,
        _report_target_state(markdown_path),
    )
    _verify_report_directory(report_directory, directory_identity)
    _verify_report_file_snapshot(json_path, json_report)
    _verify_report_file_snapshot(markdown_path, markdown_report)
    return ConversionDiagnosticReportSnapshot(
        json_path=json_path,
        markdown_path=markdown_path,
        directory_identity=directory_identity,
        json_report=json_report,
        markdown_report=markdown_report,
    )


def restore_conversion_diagnostic_reports(
    godot_project_path: StrPath,
    snapshot: ConversionDiagnosticReportSnapshot,
    receipt: ConversionDiagnosticReportPublicationReceipt,
) -> None:
    """Restore a same-directory snapshot over the exact pair in ``receipt``.

    The snapshot may be an older trusted baseline retained across multiple
    managed rewrites; the receipt must always describe the latest rewrite.
    """
    json_path, markdown_path = _normalized_diagnostic_report_paths(
        godot_project_path
    )
    if (
        snapshot.json_path != json_path
        or snapshot.markdown_path != markdown_path
        or receipt.json_path != json_path
        or receipt.markdown_path != markdown_path
    ):
        raise ValueError("Diagnostic report snapshot and receipt paths do not match.")
    if (
        snapshot.directory_identity != receipt.directory_identity
    ):
        raise ValueError(
            "Diagnostic report snapshot and receipt directories do not match."
        )
    _validate_report_file_snapshot(snapshot.json_report)
    _validate_report_file_snapshot(snapshot.markdown_report)
    _validate_report_fingerprint(receipt.json_report)
    _validate_report_fingerprint(receipt.markdown_report)

    report_directory = os.path.dirname(json_path)
    _verify_report_directory(report_directory, receipt.directory_identity)
    # Moving the exact displaced inode out and back during a failed restore
    # changes ctime on POSIX.  Rebase only that volatile metadata after proving
    # that identity, size, mode, and content still match the caller's receipt.
    json_state = _current_state_matching_receipt(
        json_path,
        receipt.json_report,
    )
    markdown_state = _current_state_matching_receipt(
        markdown_path,
        receipt.markdown_report,
    )
    restored_json, restored_markdown = _publish_report_pair(
        json_path=json_path,
        json_content=snapshot.json_report.content,
        json_mode=snapshot.json_report.mode,
        markdown_path=markdown_path,
        markdown_content=snapshot.markdown_report.content,
        markdown_mode=snapshot.markdown_report.mode,
        expected_json_state=json_state,
        expected_markdown_state=markdown_state,
        report_directory=report_directory,
        directory_identity=receipt.directory_identity,
        preserve_displaced_targets=True,
    )
    _verify_restored_report(json_path, snapshot.json_report, restored_json)
    _verify_restored_report(
        markdown_path,
        snapshot.markdown_report,
        restored_markdown,
    )


def invalidate_conversion_diagnostic_reports(godot_project_path: StrPath) -> None:
    """Best-effort removal of a diagnostic report pair known to be stale."""
    root_path: str = os.fspath(godot_project_path)
    root = os.path.abspath(root_path)
    try:
        root_stat = os.lstat(root)
    except OSError:
        return
    if _path_is_redirected(root, root_stat) or not stat.S_ISDIR(
        root_stat.st_mode
    ):
        return
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    report_paths = _diagnostic_report_paths(root)
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
            _verify_project_root(root, root_identity)
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


def _normalized_diagnostic_report_paths(
    godot_project_path: StrPath,
) -> tuple[str, str]:
    root_path: str = os.fspath(godot_project_path)
    root = os.path.abspath(root_path)
    _prepare_project_root(root)
    return _diagnostic_report_paths(root)


def _prepare_project_root(path: str) -> PathIdentity:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        os.makedirs(path, exist_ok=True)
        path_stat = os.lstat(path)
    if _path_is_redirected(path, path_stat) or not stat.S_ISDIR(
        path_stat.st_mode
    ):
        raise OSError(f"Refusing redirected Godot project root: {path}")
    return (path_stat.st_dev, path_stat.st_ino)


def _verify_project_root(path: str, expected_identity: PathIdentity) -> None:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise OSError(f"Godot project root changed: {path}") from error
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Godot project root changed: {path}")


def _prepare_report_directory(path: str) -> tuple[int, int]:
    project_root = os.path.dirname(path)
    root_identity = _prepare_project_root(project_root)
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        try:
            os.mkdir(path)
        except FileExistsError:
            pass
        path_stat = os.lstat(path)
    if _path_is_redirected(path, path_stat) or not stat.S_ISDIR(path_stat.st_mode):
        raise OSError(f"Refusing redirected diagnostic report directory: {path}")
    directory_identity = (path_stat.st_dev, path_stat.st_ino)
    _verify_project_root(project_root, root_identity)
    _verify_report_directory(path, directory_identity)
    # Always cross this durability barrier.  A prior attempt may have created
    # the child directory and then failed its root fsync, so merely observing
    # an existing child cannot prove that its directory entry is durable.
    _fsync_project_root(project_root, root_identity)
    _verify_report_directory(path, directory_identity)
    return directory_identity


def _verify_report_directory(
    path: str,
    expected_identity: tuple[int, int],
) -> None:
    project_root = os.path.dirname(path)
    try:
        root_stat = os.lstat(project_root)
    except OSError as error:
        raise OSError(f"Diagnostic report directory changed: {path}") from error
    if _path_is_redirected(project_root, root_stat) or not stat.S_ISDIR(
        root_stat.st_mode
    ):
        raise OSError(f"Diagnostic report directory changed: {path}")
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
        return _ReportTargetState(fingerprint=None, mode=None)
    if _path_is_redirected(path, path_stat) or not stat.S_ISREG(
        path_stat.st_mode
    ):
        raise OSError(f"Refusing non-regular diagnostic report: {path}")
    return _ReportTargetState(
        fingerprint=_file_fingerprint(path_stat),
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
        expected.fingerprint is None
        or _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or _file_fingerprint(path_stat) != expected.fingerprint
        or stat.S_IMODE(path_stat.st_mode) != expected.mode
    ):
        raise OSError(f"Diagnostic report changed during publication: {path}")


def _regular_path_identity(path: str) -> PathIdentity:
    path_stat = os.lstat(path)
    if _path_is_redirected(path, path_stat) or not stat.S_ISREG(
        path_stat.st_mode
    ):
        raise OSError(f"Refusing non-regular staged diagnostic report: {path}")
    return (path_stat.st_dev, path_stat.st_ino)


def _verify_regular_path_identity(
    path: str,
    expected_identity: PathIdentity,
) -> None:
    try:
        identity = _regular_path_identity(path)
    except OSError as error:
        raise OSError(f"Staged diagnostic report changed: {path}") from error
    if identity != expected_identity:
        raise OSError(f"Staged diagnostic report changed: {path}")


def _file_fingerprint(path_stat: os.stat_result) -> FileFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _target_state_from_fingerprint(
    fingerprint: DiagnosticReportFingerprint,
) -> _ReportTargetState:
    return _ReportTargetState(
        fingerprint=fingerprint.stat,
        mode=fingerprint.mode,
    )


def _read_report_bytes(path: str, expected: _ReportTargetState) -> bytes:
    if expected.fingerprint is None:
        raise ValueError("Cannot read an absent diagnostic report.")
    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, open_flags)
    try:
        opened_before = os.fstat(file_descriptor)
        path_before = os.lstat(path)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or not stat.S_ISREG(path_before.st_mode)
            or _file_fingerprint(opened_before) != expected.fingerprint
            or _file_fingerprint(path_before) != expected.fingerprint
            or stat.S_IMODE(opened_before.st_mode) != expected.mode
            or stat.S_IMODE(path_before.st_mode) != expected.mode
        ):
            raise OSError(f"Diagnostic report changed while reading it: {path}")
        with os.fdopen(file_descriptor, "rb") as report_file:
            file_descriptor = -1
            content = report_file.read()
            opened_after = os.fstat(report_file.fileno())
        if (
            _file_fingerprint(opened_after) != expected.fingerprint
            or stat.S_IMODE(opened_after.st_mode) != expected.mode
        ):
            raise OSError(f"Diagnostic report changed while reading it: {path}")
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    _verify_report_target_state(path, expected)
    return content


def _capture_report_file(
    path: str,
    state: _ReportTargetState,
) -> DiagnosticReportFileSnapshot:
    if state.fingerprint is None:
        return DiagnosticReportFileSnapshot(content=None, fingerprint=None)
    if state.mode is None:
        raise AssertionError("A present diagnostic report must have a mode.")
    content = _read_report_bytes(path, state)
    return DiagnosticReportFileSnapshot(
        content=content,
        fingerprint=DiagnosticReportFingerprint(
            stat=state.fingerprint,
            mode=state.mode,
            sha256=_sha256_bytes(content),
        ),
    )


def _validate_report_fingerprint(
    fingerprint: DiagnosticReportFingerprint,
) -> None:
    if (
        len(fingerprint.stat) != 5
        or fingerprint.stat[2] < 0
        or not 0 <= fingerprint.mode <= 0o7777
        or len(fingerprint.sha256) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint.sha256)
    ):
        raise ValueError("Invalid diagnostic report fingerprint.")


def _validate_report_file_snapshot(
    snapshot: DiagnosticReportFileSnapshot,
) -> None:
    if snapshot.fingerprint is None:
        if snapshot.content is not None:
            raise ValueError("An absent diagnostic report snapshot has content.")
        return
    if snapshot.content is None:
        raise ValueError("A present diagnostic report snapshot has no content.")
    _validate_report_fingerprint(snapshot.fingerprint)
    if (
        snapshot.fingerprint.stat[2] != len(snapshot.content)
        or snapshot.fingerprint.sha256 != _sha256_bytes(snapshot.content)
    ):
        raise ValueError("Diagnostic report snapshot content does not match its fingerprint.")


def _verify_report_fingerprint(
    path: str,
    expected: DiagnosticReportFingerprint,
) -> None:
    _validate_report_fingerprint(expected)
    content = _read_report_bytes(path, _target_state_from_fingerprint(expected))
    if _sha256_bytes(content) != expected.sha256:
        raise OSError(f"Diagnostic report content changed: {path}")


def _current_state_matching_receipt(
    path: str,
    expected: DiagnosticReportFingerprint,
) -> _ReportTargetState:
    """Return current metadata after stable receipt fields still match.

    ``mtime`` and ``ctime`` are concurrency hints rather than semantic receipt
    identity: moving the same inode aside and back during rollback can change
    them.  Identity, exact size, mode, and SHA-256 must never drift.
    """
    _validate_report_fingerprint(expected)
    current = _report_target_state(path)
    if (
        current.fingerprint is None
        or current.identity != expected.identity
        or current.fingerprint[2] != expected.stat[2]
        or current.mode != expected.mode
    ):
        raise OSError(f"Diagnostic report changed since publication: {path}")
    content = _read_report_bytes(path, current)
    if _sha256_bytes(content) != expected.sha256:
        raise OSError(f"Diagnostic report content changed: {path}")
    return current


def _verify_report_file_snapshot(
    path: str,
    snapshot: DiagnosticReportFileSnapshot,
) -> None:
    _validate_report_file_snapshot(snapshot)
    if snapshot.fingerprint is None:
        _verify_report_target_state(
            path,
            _ReportTargetState(fingerprint=None, mode=None),
        )
        return
    current = _read_report_bytes(
        path,
        _target_state_from_fingerprint(snapshot.fingerprint),
    )
    if (
        _sha256_bytes(current) != snapshot.fingerprint.sha256
        or current != snapshot.content
    ):
        raise OSError(f"Diagnostic report content changed: {path}")


def _stage_existing_report(
    path: str,
    expected: _ReportTargetState,
) -> _TemporaryReport | None:
    if expected.identity is None:
        return None
    content = _read_report_bytes(path, expected)
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
) -> _TemporaryReport:
    report_directory = os.path.dirname(path) or os.curdir
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=report_directory,
        prefix=f".{os.path.basename(path)}.",
        suffix=suffix,
    )
    initial_stat = os.fstat(file_descriptor)
    staged_identity = (initial_stat.st_dev, initial_stat.st_ino)
    destination_mode = (
        stat.S_IMODE(initial_stat.st_mode) if mode is None else mode
    )
    expected_mode = (
        stat.S_IMODE(initial_stat.st_mode)
        if _WINDOWS_READONLY_FILE_ATTRIBUTES
        else destination_mode
    )
    try:
        # mkstemp's restrictive mode is retained for a new report, so the
        # process umask is never bypassed.  An existing regular report keeps
        # its prior mode through the held descriptor when the platform
        # supports fchmod, avoiding a path-swap window before publication.
        # Apply that mode after writing because POSIX clears set-ID bits when
        # file content changes.
        staged_file = os.fdopen(file_descriptor, "wb")
        file_descriptor = -1
        with staged_file:
            staged_file.write(content)
            staged_file.flush()
            if mode is not None and not _WINDOWS_READONLY_FILE_ATTRIBUTES:
                _set_staged_report_mode(
                    staged_file.fileno(),
                    staged_path,
                    staged_identity,
                    mode,
                )
            os.fsync(staged_file.fileno())
        staged_state = _report_target_state(staged_path)
        if (
            staged_state.identity != staged_identity
            or staged_state.mode != expected_mode
            or staged_state.fingerprint is None
        ):
            raise OSError(f"Staged diagnostic report changed: {staged_path}")
        temporary_report = _TemporaryReport(
            path=staged_path,
            fingerprint=DiagnosticReportFingerprint(
                stat=staged_state.fingerprint,
                mode=expected_mode,
                sha256=_sha256_bytes(content),
            ),
            destination_mode=destination_mode,
        )
        _verify_temporary_report(temporary_report)
        return temporary_report
    except BaseException as error:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        cleanup_error = _unlink_temporary_report(staged_path, staged_identity)
        if cleanup_error is not None:
            error.add_note(
                "Failed to remove incomplete diagnostic report stage "
                f"{staged_path}: {cleanup_error}"
            )
        raise


def _set_staged_report_mode(
    file_descriptor: int,
    staged_path: str,
    staged_identity: PathIdentity,
    mode: int,
) -> None:
    fchmod_candidate: object = getattr(os, "fchmod", None)
    if callable(fchmod_candidate):
        fchmod = cast(Callable[[int, int], None], fchmod_candidate)
        try:
            fchmod(file_descriptor, mode)
        except NotImplementedError:
            pass
        else:
            opened_stat = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or (opened_stat.st_dev, opened_stat.st_ino) != staged_identity
                or stat.S_IMODE(opened_stat.st_mode) != mode
            ):
                raise OSError(
                    f"Staged diagnostic report changed: {staged_path}"
                )
            _verify_regular_path_identity(staged_path, staged_identity)
            return

    # Windows does not expose fchmod on all supported Python builds.  Guard
    # its path-based fallback on both sides so an observed swap is rejected.
    _verify_regular_path_identity(staged_path, staged_identity)
    os.chmod(staged_path, mode)
    _verify_regular_path_identity(staged_path, staged_identity)


def _report_modes_match(actual: int, expected: int) -> bool:
    if _WINDOWS_READONLY_FILE_ATTRIBUTES:
        return bool(actual & stat.S_IWRITE) == bool(expected & stat.S_IWRITE)
    return actual == expected


def _set_report_mode_guarded(
    path: str,
    expected_identity: PathIdentity,
    mode: int,
) -> _ReportTargetState:
    """Set one final report's mode without accepting a path replacement."""
    _verify_regular_path_identity(path, expected_identity)
    os.chmod(path, mode)
    _verify_regular_path_identity(path, expected_identity)
    state = _report_target_state(path)
    if (
        state.fingerprint is None
        or state.identity != expected_identity
        or state.mode is None
        or not _report_modes_match(state.mode, mode)
    ):
        raise OSError(f"Diagnostic report mode changed unexpectedly: {path}")
    return state


def _make_report_replaceable(
    path: str,
    expected: _ReportTargetState,
) -> tuple[_ReportTargetState, bool]:
    """Temporarily clear a Windows destination's read-only attribute."""
    if (
        not _WINDOWS_READONLY_FILE_ATTRIBUTES
        or expected.fingerprint is None
        or expected.mode is None
        or expected.mode & stat.S_IWRITE
    ):
        return expected, False
    expected_identity = expected.identity
    if expected_identity is None:
        raise AssertionError("A present diagnostic report must have an identity.")
    _verify_report_target_state(path, expected)
    writable = _set_report_mode_guarded(
        path,
        expected_identity,
        expected.mode | stat.S_IWRITE,
    )
    if (
        writable.fingerprint is None
        or writable.fingerprint[2] != expected.fingerprint[2]
    ):
        raise OSError(f"Diagnostic report changed while making it writable: {path}")
    return writable, True


def _restore_report_mode_after_failed_replacement(
    path: str,
    prepared: _ReportTargetState,
    original: _ReportTargetState,
    changed: bool,
) -> None:
    if not changed:
        return
    if (
        prepared.identity is None
        or original.identity != prepared.identity
        or original.mode is None
    ):
        raise AssertionError("A replaceable report must retain its original mode.")
    _set_report_mode_guarded(path, prepared.identity, original.mode)


def _verify_relocated_temporary_report(
    report: _TemporaryReport,
    path: str,
    *,
    destination_mode: int | None = None,
) -> DiagnosticReportFingerprint:
    state = _report_target_state(path)
    if (
        state.fingerprint is None
        or state.mode is None
        or state.identity != report.fingerprint.identity
        or (
            destination_mode is not None
            and not _report_modes_match(state.mode, destination_mode)
        )
    ):
        raise OSError(f"Staged diagnostic report changed: {path}")
    content = _read_report_bytes(path, state)
    if _sha256_bytes(content) != report.fingerprint.sha256:
        raise OSError(f"Staged diagnostic report content changed: {path}")
    return DiagnosticReportFingerprint(
        stat=state.fingerprint,
        mode=state.mode,
        sha256=report.fingerprint.sha256,
    )


def _apply_temporary_report_destination_mode(
    report: _TemporaryReport,
    path: str,
) -> DiagnosticReportFingerprint:
    current = _verify_relocated_temporary_report(report, path)
    if not _report_modes_match(current.mode, report.destination_mode):
        _set_report_mode_guarded(
            path,
            report.fingerprint.identity,
            report.destination_mode,
        )
    return _verify_relocated_temporary_report(
        report,
        path,
        destination_mode=report.destination_mode,
    )


def _verify_temporary_report(
    report: _TemporaryReport,
    *,
    path: str | None = None,
) -> DiagnosticReportFingerprint:
    selected_path = report.path if path is None else path
    state = _report_target_state(selected_path)
    if (
        state.identity != report.fingerprint.identity
        or state.mode != report.fingerprint.mode
    ):
        raise OSError(f"Staged diagnostic report changed: {selected_path}")
    content = _read_report_bytes(selected_path, state)
    if _sha256_bytes(content) != report.fingerprint.sha256:
        raise OSError(
            f"Staged diagnostic report content changed: {selected_path}"
        )
    if state.fingerprint is None or state.mode is None:
        raise AssertionError("A verified temporary report must be present.")
    current = DiagnosticReportFingerprint(
        stat=state.fingerprint,
        mode=state.mode,
        sha256=report.fingerprint.sha256,
    )
    if path is None and current != report.fingerprint:
        raise OSError(f"Staged diagnostic report changed: {selected_path}")
    return current


def _verify_expected_report(
    path: str,
    state: _ReportTargetState,
    exact: DiagnosticReportFingerprint | None,
) -> None:
    if exact is not None:
        if state != _target_state_from_fingerprint(exact):
            raise ValueError("Exact diagnostic report receipt does not match state.")
        if _WINDOWS_READONLY_FILE_ATTRIBUTES:
            _current_state_matching_receipt(path, exact)
        else:
            _verify_report_fingerprint(path, exact)
    else:
        if (
            _WINDOWS_READONLY_FILE_ATTRIBUTES
            and state.fingerprint is not None
            and state.mode is not None
        ):
            current = _report_target_state(path)
            if (
                current.fingerprint is None
                or current.identity != state.identity
                or current.fingerprint[2] != state.fingerprint[2]
                or current.mode is None
                or not _report_modes_match(current.mode, state.mode)
            ):
                raise OSError(
                    f"Diagnostic report changed during publication: {path}"
                )
        else:
            _verify_report_target_state(path, state)


def _publish_staged_report(
    staged_report: _TemporaryReport,
    report_path: str,
    backup: _TemporaryReport | None,
    temporary_reports: dict[str, _TemporaryReport],
    published_reports: list[_PublishedReport],
    *,
    replace_existing_publication: bool = False,
) -> None:
    _verify_temporary_report(staged_report)
    original_target = _report_target_state(report_path)
    prepared_target, target_mode_changed = _make_report_replaceable(
        report_path,
        original_target,
    )
    replacement_completed = False
    replacement_error: BaseException | None = None
    try:
        os.replace(staged_report.path, report_path)
        replacement_completed = True
    except BaseException as error:
        replacement_error = error
        try:
            replacement_completed = (
                _regular_path_identity(report_path)
                == staged_report.fingerprint.identity
            )
        except OSError:
            replacement_completed = False
        if not replacement_completed:
            try:
                _restore_report_mode_after_failed_replacement(
                    report_path,
                    prepared_target,
                    original_target,
                    target_mode_changed,
                )
            except BaseException as restore_error:
                error.add_note(
                    "Failed to restore the diagnostic report read-only "
                    f"attribute after replacement failure: {restore_error}"
                )
            raise
    temporary_reports.pop(staged_report.path, None)
    provisional_fingerprint = _verify_relocated_temporary_report(
        staged_report,
        report_path,
    )
    published_report = _PublishedReport(
        path=report_path,
        fingerprint=provisional_fingerprint,
        backup=backup,
    )
    if replace_existing_publication:
        if not published_reports or published_reports[-1].path != report_path:
            raise AssertionError(
                "A displaced diagnostic report must be recorded before publication."
            )
        published_reports[-1] = published_report
    else:
        published_reports.append(published_report)
    try:
        published_fingerprint = _apply_temporary_report_destination_mode(
            staged_report,
            report_path,
        )
    except BaseException as integrity_error:
        try:
            current_fingerprint = _verify_relocated_temporary_report(
                staged_report,
                report_path,
            )
            published_reports[-1] = _PublishedReport(
                path=report_path,
                fingerprint=current_fingerprint,
                backup=backup,
            )
        except BaseException as current_error:
            integrity_error.add_note(
                "Published diagnostic report also failed current-state "
                f"verification: {current_error}"
            )
        if replacement_error is not None:
            replacement_error.add_note(
                "Published diagnostic report also failed integrity verification: "
                f"{integrity_error}"
            )
            raise replacement_error
        raise
    published_reports[-1] = _PublishedReport(
        path=report_path,
        fingerprint=published_fingerprint,
        backup=backup,
    )
    if replacement_error is not None:
        raise replacement_error


def _remove_report(
    report_path: str,
    backup: _TemporaryReport | None,
    published_reports: list[_PublishedReport],
) -> None:
    original_target = _report_target_state(report_path)
    prepared_target, target_mode_changed = _make_report_replaceable(
        report_path,
        original_target,
    )
    removal_completed = False
    removal_error: BaseException | None = None
    try:
        os.unlink(report_path)
        removal_completed = True
    except BaseException as error:
        removal_error = error
        removal_completed = not os.path.lexists(report_path)
        if not removal_completed:
            try:
                _restore_report_mode_after_failed_replacement(
                    report_path,
                    prepared_target,
                    original_target,
                    target_mode_changed,
                )
            except BaseException as restore_error:
                error.add_note(
                    "Failed to restore the diagnostic report read-only "
                    f"attribute after removal failure: {restore_error}"
                )
            raise
    published_reports.append(
        _PublishedReport(
            path=report_path,
            fingerprint=None,
            backup=backup,
        )
    )
    _verify_report_target_state(
        report_path,
        _ReportTargetState(fingerprint=None, mode=None),
    )
    if removal_error is not None:
        raise removal_error


def _displace_report_for_restore(
    report_path: str,
    expected: _ReportTargetState,
    backup: _TemporaryReport | None,
    temporary_reports: dict[str, _TemporaryReport],
) -> tuple[_TemporaryReport, BaseException | None]:
    """Move the exact published inode aside so rollback can move it back."""
    if expected.fingerprint is None or expected.mode is None or backup is None:
        raise AssertionError("A receipt-backed diagnostic report must be present.")
    expected_identity = expected.identity
    if expected_identity is None:
        raise AssertionError("A receipt-backed report must have an identity.")
    _verify_report_target_state(report_path, expected)
    _verify_temporary_report(backup)
    prepared_target, target_mode_changed = _make_report_replaceable(
        report_path,
        expected,
    )
    displacement_error: BaseException | None = None
    displacement_completed = False
    try:
        os.replace(report_path, backup.path)
        displacement_completed = True
    except BaseException as error:
        displacement_error = error
        try:
            displacement_completed = (
                _regular_path_identity(backup.path) == expected.identity
                and not os.path.lexists(report_path)
            )
        except OSError:
            displacement_completed = False
        if not displacement_completed:
            try:
                _restore_report_mode_after_failed_replacement(
                    report_path,
                    prepared_target,
                    expected,
                    target_mode_changed,
                )
            except BaseException as restore_error:
                error.add_note(
                    "Failed to restore the diagnostic report read-only "
                    f"attribute after displacement failure: {restore_error}"
                )
            raise

    displaced: _TemporaryReport | None = None
    try:
        displaced_state = _report_target_state(backup.path)
        if (
            displaced_state.fingerprint is None
            or displaced_state.identity != expected.identity
            or displaced_state.fingerprint[2] != expected.fingerprint[2]
        ):
            raise OSError(
                f"Displaced diagnostic report changed: {report_path}"
            )
        if displaced_state.mode is None:
            raise AssertionError("A displaced diagnostic report must have a mode.")
        displaced = _TemporaryReport(
            path=backup.path,
            fingerprint=DiagnosticReportFingerprint(
                stat=displaced_state.fingerprint,
                mode=displaced_state.mode,
                sha256=backup.fingerprint.sha256,
            ),
            destination_mode=expected.mode,
        )
        temporary_reports[backup.path] = displaced
        _verify_temporary_report(displaced)
        _verify_report_target_state(
            report_path,
            _ReportTargetState(fingerprint=None, mode=None),
        )
    except BaseException as integrity_error:
        try:
            os.replace(backup.path, report_path)
            temporary_reports.pop(backup.path, None)
            if displaced is None:
                _set_report_mode_guarded(
                    report_path,
                    expected_identity,
                    expected.mode,
                )
            else:
                _apply_temporary_report_destination_mode(displaced, report_path)
        except Exception as rollback_error:
            integrity_error.add_note(
                "Failed to return displaced diagnostic report after integrity "
                f"failure: {rollback_error}"
            )
        raise
    return displaced, displacement_error


def _verify_published_report(report: _PublishedReport) -> None:
    if report.fingerprint is None:
        _verify_report_target_state(
            report.path,
            _ReportTargetState(fingerprint=None, mode=None),
        )
    else:
        _verify_report_fingerprint(report.path, report.fingerprint)


def _validate_desired_report(content: bytes | None, mode: int | None) -> None:
    if content is None:
        if mode is not None:
            raise ValueError("An absent diagnostic report cannot have a mode.")
        return
    if mode is not None and not 0 <= mode <= 0o7777:
        raise ValueError("Invalid diagnostic report mode.")


def _publish_report_pair(
    *,
    json_path: str,
    json_content: bytes | None,
    json_mode: int | None,
    markdown_path: str,
    markdown_content: bytes | None,
    markdown_mode: int | None,
    expected_json_state: _ReportTargetState,
    expected_markdown_state: _ReportTargetState,
    report_directory: str,
    directory_identity: PathIdentity,
    exact_json_fingerprint: DiagnosticReportFingerprint | None = None,
    exact_markdown_fingerprint: DiagnosticReportFingerprint | None = None,
    preserve_displaced_targets: bool = False,
) -> tuple[
    DiagnosticReportFingerprint | None,
    DiagnosticReportFingerprint | None,
]:
    _validate_desired_report(json_content, json_mode)
    _validate_desired_report(markdown_content, markdown_mode)
    _verify_report_directory(report_directory, directory_identity)
    _verify_expected_report(
        json_path,
        expected_json_state,
        exact_json_fingerprint,
    )
    _verify_expected_report(
        markdown_path,
        expected_markdown_state,
        exact_markdown_fingerprint,
    )

    specs = (
        (
            json_path,
            json_content,
            json_mode,
            expected_json_state,
            exact_json_fingerprint,
        ),
        (
            markdown_path,
            markdown_content,
            markdown_mode,
            expected_markdown_state,
            exact_markdown_fingerprint,
        ),
    )
    temporary_reports: dict[str, _TemporaryReport] = {}
    staged: dict[str, _TemporaryReport | None] = {}
    backups: dict[str, _TemporaryReport | None] = {}
    published: list[_PublishedReport] = []
    active_error: BaseException | None = None
    try:
        for report_path, content, mode, state, exact in specs:
            _verify_report_directory(report_directory, directory_identity)
            _verify_expected_report(report_path, state, exact)
            staged_report = (
                None
                if content is None
                else _stage_report_bytes(
                    report_path,
                    content,
                    mode=mode,
                    suffix=".tmp",
                )
            )
            staged[report_path] = staged_report
            if staged_report is not None:
                temporary_reports[staged_report.path] = staged_report

        for report_path, _content, _mode, state, exact in specs:
            _verify_report_directory(report_directory, directory_identity)
            _verify_expected_report(report_path, state, exact)
            backup = _stage_existing_report(report_path, state)
            backups[report_path] = backup
            if backup is not None:
                temporary_reports[backup.path] = backup
            if (
                exact is not None
                and backup is not None
                and backup.fingerprint.sha256 != exact.sha256
            ):
                raise OSError(
                    "Diagnostic report changed while creating its backup: "
                    f"{report_path}"
                )

        try:
            for report_path, content, _mode, state, exact in reversed(specs):
                _verify_report_directory(report_directory, directory_identity)
                _verify_expected_report(report_path, state, exact)
                staged_report = staged[report_path]
                backup = backups[report_path]
                if preserve_displaced_targets:
                    displaced, displacement_error = _displace_report_for_restore(
                        report_path,
                        state,
                        backup,
                        temporary_reports,
                    )
                    backups[report_path] = displaced
                    backup = displaced
                    published.append(
                        _PublishedReport(
                            path=report_path,
                            fingerprint=None,
                            backup=backup,
                        )
                    )
                    if displacement_error is not None:
                        raise displacement_error
                    if content is not None:
                        if staged_report is None:
                            raise AssertionError("A present report must have a stage.")
                        _publish_staged_report(
                            staged_report,
                            report_path,
                            backup,
                            temporary_reports,
                            published,
                            replace_existing_publication=True,
                        )
                elif content is None:
                    if state.fingerprint is not None:
                        _remove_report(report_path, backup, published)
                else:
                    if staged_report is None:
                        raise AssertionError("A present report must have a stage.")
                    _publish_staged_report(
                        staged_report,
                        report_path,
                        backup,
                        temporary_reports,
                        published,
                    )
                _fsync_report_directory(report_directory, directory_identity)
                if published and published[-1].path == report_path:
                    _verify_published_report(published[-1])
            _verify_report_directory(report_directory, directory_identity)
            for published_report in published:
                _verify_published_report(published_report)
        except BaseException as publish_error:
            rollback_errors = _rollback_reports(
                published,
                temporary_reports,
                json_path=json_path,
                json_state=expected_json_state,
                json_exact=exact_json_fingerprint,
                markdown_path=markdown_path,
                markdown_state=expected_markdown_state,
                markdown_exact=exact_markdown_fingerprint,
                report_directory=report_directory,
                directory_identity=directory_identity,
            )
            if rollback_errors:
                publish_error.add_note(
                    "Diagnostics rollback also failed: "
                    + "; ".join(str(error) for error in rollback_errors)
                )
            raise
    except BaseException as error:
        active_error = error
        raise
    finally:
        cleanup_errors = _cleanup_temporary_reports(
            temporary_reports,
            report_directory=report_directory,
            directory_identity=directory_identity,
        )
        if cleanup_errors and active_error is not None:
            active_error.add_note(
                "Diagnostics cleanup also failed: "
                + "; ".join(str(error) for error in cleanup_errors)
            )

    json_report = _verify_desired_report(json_path, json_content, json_mode)
    markdown_report = _verify_desired_report(
        markdown_path,
        markdown_content,
        markdown_mode,
    )
    _verify_report_directory(report_directory, directory_identity)
    _verify_optional_report_fingerprint(json_path, json_report)
    _verify_optional_report_fingerprint(markdown_path, markdown_report)
    return json_report, markdown_report


def _verify_optional_report_fingerprint(
    path: str,
    fingerprint: DiagnosticReportFingerprint | None,
) -> None:
    if fingerprint is None:
        _verify_report_target_state(
            path,
            _ReportTargetState(fingerprint=None, mode=None),
        )
    else:
        _verify_report_fingerprint(path, fingerprint)


def _verify_desired_report(
    path: str,
    content: bytes | None,
    mode: int | None,
) -> DiagnosticReportFingerprint | None:
    if content is None:
        _verify_report_target_state(
            path,
            _ReportTargetState(fingerprint=None, mode=None),
        )
        return None
    state = _report_target_state(path)
    if mode is not None and (
        state.mode is None or not _report_modes_match(state.mode, mode)
    ):
        raise OSError(f"Restored diagnostic report mode changed: {path}")
    captured = _capture_report_file(path, state)
    if captured.content != content or captured.fingerprint is None:
        raise OSError(f"Published diagnostic report content changed: {path}")
    return captured.fingerprint


def _verify_restored_report(
    path: str,
    snapshot: DiagnosticReportFileSnapshot,
    restored: DiagnosticReportFingerprint | None,
) -> None:
    _validate_report_file_snapshot(snapshot)
    if snapshot.content is None:
        if restored is not None:
            raise OSError(f"Absent diagnostic report was recreated: {path}")
        _verify_report_target_state(
            path,
            _ReportTargetState(fingerprint=None, mode=None),
        )
        return
    if (
        restored is None
        or snapshot.mode is None
        or not _report_modes_match(restored.mode, snapshot.mode)
    ):
        raise OSError(f"Restored diagnostic report mode changed: {path}")
    _verify_report_fingerprint(path, restored)
    current = _read_report_bytes(path, _target_state_from_fingerprint(restored))
    if current != snapshot.content:
        raise OSError(f"Restored diagnostic report content changed: {path}")


def _rollback_reports(
    published: list[_PublishedReport],
    temporary_reports: dict[str, _TemporaryReport],
    *,
    json_path: str,
    json_state: _ReportTargetState,
    json_exact: DiagnosticReportFingerprint | None,
    markdown_path: str,
    markdown_state: _ReportTargetState,
    markdown_exact: DiagnosticReportFingerprint | None,
    report_directory: str,
    directory_identity: PathIdentity,
) -> list[Exception]:
    errors: list[Exception] = []
    restored: list[tuple[_PublishedReport, _TemporaryReport | None]] = []
    for report in reversed(published):
        recovery: _TemporaryReport | None = None
        try:
            _verify_report_directory(report_directory, directory_identity)
            _verify_published_report(report)
            if report.backup is None:
                if report.fingerprint is not None:
                    published_state = _target_state_from_fingerprint(
                        report.fingerprint
                    )
                    prepared_state, mode_changed = _make_report_replaceable(
                        report.path,
                        published_state,
                    )
                    try:
                        os.unlink(report.path)
                    except Exception as unlink_error:
                        if os.path.lexists(report.path):
                            try:
                                _restore_report_mode_after_failed_replacement(
                                    report.path,
                                    prepared_state,
                                    published_state,
                                    mode_changed,
                                )
                            except Exception as restore_error:
                                unlink_error.add_note(
                                    "Failed to restore the diagnostic report "
                                    "read-only attribute after rollback removal "
                                    f"failure: {restore_error}"
                                )
                            raise
            else:
                backup_content = _read_temporary_report(report.backup)
                recovery = _stage_report_bytes(
                    report.path,
                    backup_content,
                    mode=report.backup.destination_mode,
                    suffix=".recovery.backup",
                )
                temporary_reports[recovery.path] = recovery
                if report.fingerprint is None:
                    published_state = _ReportTargetState(
                        fingerprint=None,
                        mode=None,
                    )
                else:
                    published_state = _target_state_from_fingerprint(
                        report.fingerprint
                    )
                prepared_state, mode_changed = _make_report_replaceable(
                    report.path,
                    published_state,
                )
                replacement_completed = False
                try:
                    os.replace(report.backup.path, report.path)
                    replacement_completed = True
                except Exception as replace_error:
                    try:
                        replacement_completed = (
                            _regular_path_identity(report.path)
                            == report.backup.fingerprint.identity
                        )
                    except OSError:
                        replacement_completed = False
                    if not replacement_completed:
                        try:
                            _restore_report_mode_after_failed_replacement(
                                report.path,
                                prepared_state,
                                published_state,
                                mode_changed,
                            )
                        except Exception as restore_error:
                            replace_error.add_note(
                                "Failed to restore the diagnostic report "
                                "read-only attribute after rollback replacement "
                                f"failure: {restore_error}"
                            )
                        raise
                temporary_reports.pop(report.backup.path, None)
                restored_fingerprint = (
                    _apply_temporary_report_destination_mode(
                        report.backup,
                        report.path,
                    )
                )
                report = _PublishedReport(
                    path=report.path,
                    fingerprint=report.fingerprint,
                    backup=_TemporaryReport(
                        path=report.backup.path,
                        fingerprint=restored_fingerprint,
                        destination_mode=report.backup.destination_mode,
                    ),
                )
            _fsync_report_directory(report_directory, directory_identity)
            if report.backup is None:
                _verify_report_target_state(
                    report.path,
                    _ReportTargetState(fingerprint=None, mode=None),
                )
            else:
                _verify_relocated_temporary_report(
                    report.backup,
                    report.path,
                    destination_mode=report.backup.destination_mode,
                )
            restored.append((report, recovery))
        except Exception as error:
            recovery_path = _preserve_recovery_report(
                recovery,
                report.backup,
                temporary_reports,
            )
            if recovery_path is not None:
                wrapped_error = OSError(
                    f"{error}; previous diagnostic report preserved at: "
                    f"{recovery_path}"
                )
                wrapped_error.__cause__ = error
                errors.append(wrapped_error)
            else:
                errors.append(error)

    for report, recovery in restored:
        try:
            if report.backup is None:
                _verify_report_target_state(
                    report.path,
                    _ReportTargetState(fingerprint=None, mode=None),
                )
            else:
                _verify_relocated_temporary_report(
                    report.backup,
                    report.path,
                    destination_mode=report.backup.destination_mode,
                )
        except Exception as error:
            recovery_path = _preserve_recovery_report(
                recovery,
                None,
                temporary_reports,
            )
            if recovery_path is not None:
                wrapped_error = OSError(
                    f"{error}; previous diagnostic report preserved at: "
                    f"{recovery_path}"
                )
                wrapped_error.__cause__ = error
                errors.append(wrapped_error)
            else:
                errors.append(error)

    if not errors:
        restored_by_path = {
            report.path: (report, recovery)
            for report, recovery in restored
        }
        for path, state, exact in (
            (json_path, json_state, json_exact),
            (markdown_path, markdown_state, markdown_exact),
        ):
            restored_report = restored_by_path.get(path)
            try:
                if restored_report is None:
                    _verify_expected_report(path, state, exact)
                elif restored_report[0].backup is None:
                    _verify_report_target_state(
                        path,
                        _ReportTargetState(fingerprint=None, mode=None),
                    )
                else:
                    _verify_relocated_temporary_report(
                        restored_report[0].backup,
                        path,
                        destination_mode=(
                            restored_report[0].backup.destination_mode
                        ),
                    )
            except Exception as error:
                recovery_path = (
                    None
                    if restored_report is None
                    else _preserve_recovery_report(
                        restored_report[1],
                        None,
                        temporary_reports,
                    )
                )
                if recovery_path is None:
                    errors.append(error)
                else:
                    wrapped_error = OSError(
                        f"{error}; previous diagnostic report preserved at: "
                        f"{recovery_path}"
                    )
                    wrapped_error.__cause__ = error
                    errors.append(wrapped_error)
    return errors


def _read_temporary_report(report: _TemporaryReport) -> bytes:
    state = _report_target_state(report.path)
    if (
        state.identity != report.fingerprint.identity
        or state.mode != report.fingerprint.mode
    ):
        raise OSError(f"Staged diagnostic report changed: {report.path}")
    content = _read_report_bytes(report.path, state)
    if _sha256_bytes(content) != report.fingerprint.sha256:
        raise OSError(f"Staged diagnostic report content changed: {report.path}")
    return content


def _preserve_recovery_report(
    recovery: _TemporaryReport | None,
    backup: _TemporaryReport | None,
    temporary_reports: dict[str, _TemporaryReport],
) -> str | None:
    for candidate in (recovery, backup):
        if candidate is None:
            continue
        try:
            _verify_temporary_report(candidate)
        except OSError:
            continue
        temporary_reports.pop(candidate.path, None)
        return candidate.path
    return None


def _cleanup_temporary_reports(
    temporary_reports: dict[str, _TemporaryReport],
    *,
    report_directory: str,
    directory_identity: PathIdentity,
) -> list[Exception]:
    errors: list[Exception] = []
    removed = False
    for path, report in tuple(temporary_reports.items()):
        try:
            _verify_report_directory(report_directory, directory_identity)
            if not os.path.lexists(path):
                temporary_reports.pop(path, None)
                continue
            _verify_temporary_report(report)
            try:
                os.unlink(path)
            except Exception:
                if os.path.lexists(path):
                    raise
            temporary_reports.pop(path, None)
            removed = True
        except Exception as error:
            errors.append(error)
    if removed:
        try:
            _fsync_report_directory(report_directory, directory_identity)
        except Exception as error:
            errors.append(error)
    return errors


def _unlink_temporary_report(
    path: str,
    expected_identity: PathIdentity,
) -> Exception | None:
    try:
        if not os.path.lexists(path):
            return None
        if _regular_path_identity(path) != expected_identity:
            raise OSError(f"Staged diagnostic report changed: {path}")
        os.unlink(path)
    except Exception as error:
        return error
    return None


def _fsync_report_directory(
    path: str,
    expected_identity: PathIdentity,
) -> None:
    _fsync_directory(
        path,
        expected_identity,
        verify=_verify_report_directory,
        changed_message=f"Diagnostic report directory changed: {path}",
    )


def _fsync_project_root(
    path: str,
    expected_identity: PathIdentity,
) -> None:
    _fsync_directory(
        path,
        expected_identity,
        verify=_verify_project_root,
        changed_message=f"Godot project root changed: {path}",
    )


def _fsync_directory(
    path: str,
    expected_identity: PathIdentity,
    *,
    verify: Callable[[str, PathIdentity], None],
    changed_message: str,
) -> None:
    verify(path, expected_identity)
    if os.name == "nt":
        return
    open_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os,
        "O_NOFOLLOW",
        0,
    )
    directory_descriptor = os.open(path, open_flags)
    try:
        opened_stat = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(opened_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino) != expected_identity
        ):
            raise OSError(changed_message)
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    verify(path, expected_identity)


def _unlink_best_effort(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def write_conversion_diagnostic_reports(
    godot_project_path: StrPath, diagnostics: DiagnosticCollector
) -> tuple[str, str]:
    return diagnostics.write_reports(godot_project_path)


def publish_conversion_diagnostic_reports(
    godot_project_path: StrPath,
    diagnostics: DiagnosticCollector,
) -> ConversionDiagnosticReportPublicationReceipt:
    return diagnostics.publish_reports(godot_project_path)


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
