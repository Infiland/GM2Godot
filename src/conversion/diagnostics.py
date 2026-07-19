from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from typing import Callable, Literal, TypeAlias

from src.conversion.anchored_artifacts import (
    ArtifactReceipt,
    ArtifactSnapshot,
    ArtifactSpec,
    ByteArtifactTransaction,
    artifact_sha256,
    modes_match,
    stable_artifact_fingerprint,
)
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.type_defs import StrPath

DiagnosticSeverity: TypeAlias = Literal["info", "warning", "error"]
FileFingerprint: TypeAlias = tuple[int, int, int, int, int]
PathIdentity: TypeAlias = tuple[int, int]

DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.json"
)
DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.md"
)

_REPORT_DIRECTORY_NAME = "gm2godot"
_JSON_REPORT_NAME = "conversion_diagnostics.json"
_MARKDOWN_REPORT_NAME = "conversion_diagnostics.md"
_REPORT_DIRECTORY_DESCRIPTION = "diagnostic report directory"


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
    root_identity: PathIdentity
    directory_identity: PathIdentity
    json_report: DiagnosticReportFileSnapshot
    markdown_report: DiagnosticReportFileSnapshot


@dataclass(frozen=True)
class ConversionDiagnosticReportPublicationReceipt:
    """Identity proof for the exact report pair published by one write."""

    json_path: str
    markdown_path: str
    root_identity: PathIdentity
    directory_identity: PathIdentity
    json_report: DiagnosticReportFingerprint
    markdown_report: DiagnosticReportFingerprint


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
        self,
        message: str,
        *,
        code: str = "GM2GD-WARNING",
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
        self,
        log_callback: Callable[[str], None],
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
        return _publish_report_pair(
            godot_project_path,
            json_content=self.to_json().encode("utf-8"),
            markdown_content=self.to_markdown().encode("utf-8"),
        )

    def write_reports(self, godot_project_path: StrPath) -> tuple[str, str]:
        """Publish both reports while preserving the legacy path tuple API."""
        receipt = self.publish_reports(godot_project_path)
        return receipt.json_path, receipt.markdown_path

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
    """Capture exact report bytes and metadata through retained bindings."""
    root = _normalized_report_root(godot_project_path)
    json_path, markdown_path = _diagnostic_report_paths(root)
    with ByteArtifactTransaction.open(
        root,
        _REPORT_DIRECTORY_NAME,
        create=True,
        create_root=True,
        description=_REPORT_DIRECTORY_DESCRIPTION,
    ) as transaction:
        json_snapshot, markdown_snapshot = transaction.capture_snapshots(
            (_JSON_REPORT_NAME, _MARKDOWN_REPORT_NAME)
        )
        directory_identity = transaction.directory_identity
        if directory_identity is None:
            raise AssertionError("Diagnostic report directory must be present.")
        return ConversionDiagnosticReportSnapshot(
            json_path=json_path,
            markdown_path=markdown_path,
            root_identity=transaction.root_identity,
            directory_identity=directory_identity,
            json_report=_diagnostic_snapshot(json_snapshot),
            markdown_report=_diagnostic_snapshot(markdown_snapshot),
        )


def restore_conversion_diagnostic_reports(
    godot_project_path: StrPath,
    snapshot: ConversionDiagnosticReportSnapshot,
    receipt: ConversionDiagnosticReportPublicationReceipt,
) -> None:
    """Restore a report-pair snapshot over the exact receipt-backed pair."""
    root = _normalized_report_root(godot_project_path)
    _validate_report_pair_paths(root, snapshot, receipt)
    _validate_report_file_snapshot(snapshot.json_report)
    _validate_report_file_snapshot(snapshot.markdown_report)
    _validate_report_fingerprint(receipt.json_report)
    _validate_report_fingerprint(receipt.markdown_report)
    if (
        snapshot.root_identity != receipt.root_identity
        or snapshot.directory_identity != receipt.directory_identity
    ):
        raise ValueError(
            "Diagnostic report snapshot and receipt directories do not match."
        )

    with ByteArtifactTransaction.open(
        root,
        _REPORT_DIRECTORY_NAME,
        create=False,
        description=_REPORT_DIRECTORY_DESCRIPTION,
    ) as transaction:
        if not transaction.available:
            raise OSError(
                "Diagnostic report directory disappeared before restore."
            )
        if (
            transaction.root_identity != receipt.root_identity
            or transaction.directory_identity != receipt.directory_identity
        ):
            raise OSError(
                "Diagnostic report root or directory changed before restore."
            )
        markdown_receipt = _core_receipt(
            transaction,
            _MARKDOWN_REPORT_NAME,
            receipt.markdown_report,
        )
        json_receipt = _core_receipt(
            transaction,
            _JSON_REPORT_NAME,
            receipt.json_report,
        )
        transaction.restore_snapshots(
            (
                _core_snapshot(
                    _MARKDOWN_REPORT_NAME,
                    snapshot.markdown_report,
                ),
                _core_snapshot(
                    _JSON_REPORT_NAME,
                    snapshot.json_report,
                ),
            ),
            (markdown_receipt, json_receipt),
        )


def invalidate_conversion_diagnostic_reports(godot_project_path: StrPath) -> None:
    """Best-effort removal of each stale report through one retained binding."""
    root = _normalized_report_root(godot_project_path)
    try:
        transaction = ByteArtifactTransaction.open(
            root,
            _REPORT_DIRECTORY_NAME,
            create=False,
            description=_REPORT_DIRECTORY_DESCRIPTION,
        )
    except OSError:
        return
    with transaction:
        if not transaction.available:
            return
        for name in (_JSON_REPORT_NAME, _MARKDOWN_REPORT_NAME):
            try:
                transaction.publish_specs((ArtifactSpec(name, None),))
            except OSError:
                continue


def _publish_report_pair(
    godot_project_path: StrPath,
    *,
    json_content: bytes,
    markdown_content: bytes,
) -> ConversionDiagnosticReportPublicationReceipt:
    root = _normalized_report_root(godot_project_path)
    json_path, markdown_path = _diagnostic_report_paths(root)
    with ByteArtifactTransaction.open(
        root,
        _REPORT_DIRECTORY_NAME,
        create=True,
        create_root=True,
        description=_REPORT_DIRECTORY_DESCRIPTION,
    ) as transaction:
        markdown_receipt, json_receipt = transaction.publish_specs(
            (
                ArtifactSpec(_MARKDOWN_REPORT_NAME, markdown_content),
                ArtifactSpec(_JSON_REPORT_NAME, json_content),
            )
        )
        if markdown_receipt is None or json_receipt is None:
            raise AssertionError("Published diagnostic reports must both be present.")
        directory_identity = transaction.directory_identity
        if directory_identity is None:
            raise AssertionError("Diagnostic report directory must be present.")
        return ConversionDiagnosticReportPublicationReceipt(
            json_path=json_path,
            markdown_path=markdown_path,
            root_identity=transaction.root_identity,
            directory_identity=directory_identity,
            json_report=_diagnostic_receipt(
                transaction,
                _JSON_REPORT_NAME,
                json_receipt,
            ),
            markdown_report=_diagnostic_receipt(
                transaction,
                _MARKDOWN_REPORT_NAME,
                markdown_receipt,
            ),
        )


def _diagnostic_snapshot(
    snapshot: ArtifactSnapshot,
) -> DiagnosticReportFileSnapshot:
    if not snapshot.present:
        return DiagnosticReportFileSnapshot(content=None, fingerprint=None)
    if (
        snapshot.content is None
        or snapshot.fingerprint is None
        or snapshot.mode is None
        or snapshot.sha256 is None
    ):
        raise AssertionError("A present diagnostic report snapshot is incomplete.")
    return DiagnosticReportFileSnapshot(
        content=snapshot.content,
        fingerprint=DiagnosticReportFingerprint(
            stat=snapshot.fingerprint,
            mode=snapshot.mode,
            sha256=_unprefixed_sha256(snapshot.sha256),
        ),
    )


def _diagnostic_receipt(
    transaction: ByteArtifactTransaction,
    name: str,
    receipt: ArtifactReceipt,
) -> DiagnosticReportFingerprint:
    transaction.verify_receipt(receipt)
    state = transaction.target_state(name)
    if state.fingerprint is None or state.mode is None:
        raise OSError(f"Published diagnostic report disappeared: {receipt.path}")
    return DiagnosticReportFingerprint(
        stat=state.fingerprint,
        mode=state.mode,
        sha256=_unprefixed_sha256(receipt.sha256),
    )


def _core_snapshot(
    name: str,
    snapshot: DiagnosticReportFileSnapshot,
) -> ArtifactSnapshot:
    if snapshot.fingerprint is None:
        return ArtifactSnapshot(
            name=name,
            content=None,
            mode=None,
            fingerprint=None,
            sha256=None,
        )
    if snapshot.content is None:
        raise ValueError("A present diagnostic report snapshot has no content.")
    return ArtifactSnapshot(
        name=name,
        content=snapshot.content,
        mode=snapshot.fingerprint.mode,
        fingerprint=snapshot.fingerprint.stat,
        sha256=artifact_sha256(snapshot.content),
    )


def _core_receipt(
    transaction: ByteArtifactTransaction,
    name: str,
    fingerprint: DiagnosticReportFingerprint,
) -> ArtifactReceipt:
    _validate_report_fingerprint(fingerprint)
    state = transaction.target_state(name)
    if (
        state.fingerprint is None
        or state.mode is None
        or state.fingerprint[:3] != fingerprint.stat[:3]
        or not modes_match(state.mode, fingerprint.mode)
    ):
        raise OSError(
            "Diagnostic report changed since publication: "
            f"{transaction.directory.child_path(name)}"
        )
    content = transaction.read_target_bytes(name, state)
    if _raw_sha256(content) != fingerprint.sha256:
        raise OSError(
            "Diagnostic report content changed since publication: "
            f"{transaction.directory.child_path(name)}"
        )
    return ArtifactReceipt(
        path=transaction.directory.child_path(name),
        content=content,
        mode=state.mode,
        fingerprint=stable_artifact_fingerprint(state.fingerprint),
        sha256=artifact_sha256(content),
    )


def _validate_report_pair_paths(
    root: str,
    snapshot: ConversionDiagnosticReportSnapshot,
    receipt: ConversionDiagnosticReportPublicationReceipt,
) -> None:
    expected_json, expected_markdown = _diagnostic_report_paths(root)
    expected_paths = (
        os.path.normcase(expected_json),
        os.path.normcase(expected_markdown),
    )
    for paths in (
        (snapshot.json_path, snapshot.markdown_path),
        (receipt.json_path, receipt.markdown_path),
    ):
        normalized = tuple(
            os.path.normcase(os.path.abspath(path))
            for path in paths
        )
        if normalized != expected_paths:
            raise ValueError(
                "Diagnostic report snapshot and receipt paths do not match."
            )


def _validate_report_fingerprint(
    fingerprint: DiagnosticReportFingerprint,
) -> None:
    if (
        len(fingerprint.stat) != 5
        or fingerprint.stat[2] < 0
        or not 0 <= fingerprint.mode <= 0o7777
        or len(fingerprint.sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in fingerprint.sha256
        )
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
        or snapshot.fingerprint.sha256 != _raw_sha256(snapshot.content)
    ):
        raise ValueError(
            "Diagnostic report snapshot content does not match its fingerprint."
        )


def _diagnostic_report_paths(godot_project_path: StrPath) -> tuple[str, str]:
    root = os.fspath(godot_project_path)
    return (
        os.path.join(root, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH),
        os.path.join(root, DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH),
    )


def _normalized_report_root(godot_project_path: StrPath) -> str:
    root: str = os.fspath(godot_project_path)
    return os.path.abspath(root)


def _raw_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _unprefixed_sha256(value: str) -> str:
    prefix = "sha256:"
    if not value.startswith(prefix) or len(value) != len(prefix) + 64:
        raise ValueError("Invalid artifact SHA-256 digest.")
    return value[len(prefix):]


def write_conversion_diagnostic_reports(
    godot_project_path: StrPath,
    diagnostics: DiagnosticCollector,
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
