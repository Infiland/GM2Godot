from __future__ import annotations

import argparse
import io
import json
import os
import signal
import stat
import sys
import threading
from contextlib import redirect_stdout
from dataclasses import dataclass, replace
from types import FrameType
from typing import Sequence, TypedDict, cast

from src.conversion.anchored_artifacts import ArtifactSpec, ByteArtifactTransaction
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.conversion.conversion_manifest import CONVERSION_MANIFEST_RELATIVE_PATH
from src.conversion.diagnostics import (
    ConversionDiagnosticReportPublicationReceipt,
    ConversionDiagnosticReportSnapshot,
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    DiagnosticSeverity,
    DiagnosticCollector,
    capture_conversion_diagnostic_reports,
    restore_conversion_diagnostic_reports,
)
from src.conversion.gml_transpiler import (
    generate_gml_api_compatibility_report,
    render_gml_manual_scope_markdown,
)
from src.conversion.godot_validation import (
    validate_generated_godot_project,
    write_godot_validation_report,
)
from src.conversion.platform_capabilities import (
    generate_platform_capability_report,
    render_platform_capability_markdown,
)
from src.conversion.project_godot import ConversionPreflightError
from src.version import get_version


DEFAULT_CONVERSION_GROUPS = ("assets", "project", "wip")
_NON_CONVERTER_SETTING_KEYS = frozenset({"sound_group_folders"})
_STATIC_REPORT_DIRECTORY = "gm2godot"
_STATIC_REPORT_DIRECTORY_DESCRIPTION = "CLI static report directory"
_STATIC_REPORT_FILENAMES = (
    "gml_manual_scope.md",
    "gml_api_compatibility.md",
    "platform_capability_report.json",
    "platform_capability_report.md",
)


class ConverterInventory(TypedDict):
    default_groups: list[str]
    groups: dict[str, list[str]]
    converter_keys: list[str]


@dataclass(frozen=True)
class CLISetting:
    value: bool

    def get(self) -> bool:
        return self.value


@dataclass
class _ManagedDiagnosticCheckpoint:
    destination: str
    snapshot: ConversionDiagnosticReportSnapshot
    receipt: ConversionDiagnosticReportPublicationReceipt | None = None


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.version:
        print(f"GM2Godot {get_version()}")
        return 0

    if args.command == "list-converters":
        _print_converter_inventory(args.output_format)
        return 0

    if args.command == "report":
        diagnostics = DiagnosticCollector()
        _write_static_reports(args.report_dir)
        diagnostics.write_reports(args.report_dir)
        return _threshold_exit_code(diagnostics, args)

    if args.command == "analyze":
        diagnostics = _analyze_project(args.gm_project, args.platform)
        _write_static_reports(args.report_dir, args.platform)
        diagnostics.write_reports(args.report_dir)
        return _threshold_exit_code(diagnostics, args)

    if args.command == "convert":
        return _run_convert(args)

    if args.command == "validate":
        diagnostics = _validate_project(
            args.godot_project,
            godot_binary=args.godot_bin,
            godot_boot_frames=args.godot_boot_frames,
            run_godot_validation=not args.skip_godot_validation,
        )
        if args.report_dir:
            _write_static_reports(args.report_dir)
            diagnostics.write_reports(args.report_dir)
        return _threshold_exit_code(diagnostics, args)

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="GM2Godot",
        description="Headless GM2Godot conversion, analysis, validation, and reporting.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the GM2Godot version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser(
        "list-converters",
        help="List available conversion groups and converter keys.",
    )
    list_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        dest="output_format",
        help="Output format for converter inventory.",
    )

    report_parser = subparsers.add_parser("report", help="Write static compatibility reports.")
    _add_report_args(report_parser)
    _add_threshold_args(report_parser)

    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze a GameMaker project without writing converted output."
    )
    analyze_parser.add_argument("--gm-project", required=True, help="GameMaker project directory.")
    analyze_parser.add_argument(
        "--platform",
        "--target-platform",
        dest="platform",
        default=_default_platform(),
        choices=("windows", "macos", "linux"),
        help="Target GameMaker platform for option filtering.",
    )
    _add_report_args(analyze_parser)
    _add_threshold_args(analyze_parser)

    convert_parser = subparsers.add_parser("convert", help="Convert a GameMaker project.")
    convert_parser.add_argument("--gm-project", required=True, help="GameMaker project directory.")
    convert_parser.add_argument("--godot-project", required=True, help="Godot project directory.")
    convert_parser.add_argument(
        "--platform",
        "--target-platform",
        dest="platform",
        default=_default_platform(),
        choices=("windows", "macos", "linux"),
        help="Target GameMaker platform for option filtering.",
    )
    convert_parser.add_argument(
        "--groups",
        default="assets,project,wip",
        help="Comma-separated conversion groups from assets, project, wip.",
    )
    convert_parser.add_argument(
        "--only",
        default="",
        help="Comma-separated individual converter keys to run instead of groups.",
    )
    convert_parser.add_argument(
        "--sound-group-folders",
        action="store_true",
        help="Group converted sounds by GameMaker audio group folders.",
    )
    convert_parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Treat partial converted output as a successful exit when diagnostic "
            "thresholds also pass."
        ),
    )
    _add_report_args(convert_parser, required=False)
    _add_threshold_args(convert_parser)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate generated output reports and project presence."
    )
    validate_parser.add_argument("--godot-project", required=True, help="Godot project directory.")
    validate_parser.add_argument(
        "--godot-bin",
        default=None,
        help="Optional Godot executable for generated GDScript/scene/resource validation.",
    )
    validate_parser.add_argument(
        "--skip-godot-validation",
        action="store_true",
        help="Skip headless Godot generated resource validation.",
    )
    validate_parser.add_argument(
        "--godot-boot-frames",
        type=_non_negative_int,
        default=0,
        help=(
            "After generated resource validation passes, boot the Godot project's "
            "configured main scene headlessly for this many frames and fail on "
            "warning/error output. Default: 0 (disabled)."
        ),
    )
    _add_report_args(validate_parser, required=False)
    _add_threshold_args(validate_parser)

    return parser


def _add_report_args(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument(
        "--report-dir",
        required=required,
        default=None,
        help="Directory where JSON and Markdown reports should be written.",
    )


def _add_threshold_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fail-on-unsupported",
        action="store_true",
        help="Exit non-zero when any unsupported diagnostic is present.",
    )
    parser.add_argument(
        "--max-warnings",
        type=int,
        default=None,
        help="Exit non-zero when warning diagnostics exceed this count.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=0,
        help="Exit non-zero when error diagnostics exceed this count.",
    )
    parser.add_argument(
        "--max-unsupported",
        type=int,
        default=None,
        help="Exit non-zero when unsupported diagnostics exceed this count.",
    )


def _run_convert(args: argparse.Namespace) -> int:
    logs: list[str] = []
    running = threading.Event()
    running.set()
    previous_sigint = signal.getsignal(signal.SIGINT)
    handler_installed = threading.current_thread() is threading.main_thread()
    sigint_handler_restored = False
    sigint_received = False
    terminal_summary_phase = "idle"
    canonical_reports_authorized = False
    external_report_dir: str | None = args.report_dir
    canonical_refresh_disabled = False
    late_artifact_error: Exception | None = None
    late_report_error: Exception | None = None
    attempt_publication_error: Exception | None = None
    report_restore_error: Exception | None = None
    protect_managed_reports = False
    managed_report_checkpoints: dict[str, _ManagedDiagnosticCheckpoint] = {}

    class _TerminalSummaryInterrupted(Exception):
        pass

    def request_cancellation(_signum: int, _frame: FrameType | None) -> None:
        nonlocal sigint_received
        if terminal_summary_phase in {"committing", "committed"}:
            # The buffered outcome line is the CLI's terminal commit point.
            # Once publication begins, changing the outcome would either
            # duplicate the line or make stdout disagree with the reports.
            return
        if sigint_received:
            raise KeyboardInterrupt
        sigint_received = True
        running.clear()
        if terminal_summary_phase == "preparing":
            raise _TerminalSummaryInterrupted

    def restore_sigint_handler() -> None:
        nonlocal sigint_handler_restored
        if not handler_installed or sigint_handler_restored:
            return
        try:
            signal.signal(signal.SIGINT, previous_sigint)
        except KeyboardInterrupt:
            sigint_handler_restored = (
                signal.getsignal(signal.SIGINT) == previous_sigint
            )
            if terminal_summary_phase != "committed":
                raise
        else:
            sigint_handler_restored = True

    try:
        if handler_installed:
            signal.signal(signal.SIGINT, request_cancellation)

        converter = Converter(
            log_callback=lambda message: logs.append(message),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
        )
        conversion_diagnostics = DiagnosticCollector()
        _add_platform_diagnostic(conversion_diagnostics, args.platform)

        def observe_cancellation(current: ConversionOutcome) -> ConversionOutcome:
            if sigint_received and current.state != "cancelled":
                current = replace(current, state="cancelled")
            converter.diagnostics.set_outcome(current)
            return current

        def managed_report_checkpoint(
            destination: str,
        ) -> _ManagedDiagnosticCheckpoint | None:
            if (
                not protect_managed_reports
                or not _resolved_path_is_within(
                    destination,
                    args.godot_project,
                )
            ):
                return None
            destination_key = _resolved_path_key(destination)
            checkpoint = managed_report_checkpoints.get(destination_key)
            if checkpoint is None:
                normalized_destination = os.path.realpath(
                    os.path.abspath(destination)
                )
                checkpoint = _ManagedDiagnosticCheckpoint(
                    destination=normalized_destination,
                    snapshot=capture_conversion_diagnostic_reports(
                        normalized_destination
                    ),
                )
                managed_report_checkpoints[destination_key] = checkpoint
            return checkpoint

        def reset_managed_report_publications() -> bool:
            nonlocal report_restore_error
            restore_errors: list[tuple[str, Exception]] = []
            for checkpoint in reversed(tuple(managed_report_checkpoints.values())):
                if checkpoint.receipt is None:
                    continue
                try:
                    restore_conversion_diagnostic_reports(
                        checkpoint.destination,
                        checkpoint.snapshot,
                        checkpoint.receipt,
                    )
                except Exception as error:
                    restore_errors.append((checkpoint.destination, error))
                else:
                    checkpoint.receipt = None
            if restore_errors:
                restore_error = OSError(
                    "managed conversion diagnostics could not be restored: "
                    + "; ".join(
                        f"{destination}: {error}"
                        for destination, error in restore_errors
                    )
                )
                for destination, error in restore_errors:
                    for note in _exception_notes(error):
                        restore_error.add_note(f"{destination}: {note}")
                report_restore_error = restore_error
                return False
            report_restore_error = None
            return True

        def restore_managed_reports() -> bool:
            restored = reset_managed_report_publications()
            if restored:
                managed_report_checkpoints.clear()
            return restored

        def repair_conversion_reports(
            current: ConversionOutcome,
        ) -> ConversionOutcome:
            nonlocal attempt_publication_error
            nonlocal canonical_refresh_disabled, late_artifact_error, late_report_error
            nonlocal protect_managed_reports, report_restore_error
            destinations: list[tuple[str, str]] = []
            seen_destinations: set[str] = set()
            canonical_destination_key = (
                _resolved_path_key(args.godot_project)
                if canonical_reports_authorized
                else None
            )
            candidate_destinations = (
                args.godot_project if canonical_reports_authorized else None,
                external_report_dir,
            )
            for destination in candidate_destinations:
                if destination is None:
                    continue
                destination_key = _resolved_path_key(destination)
                if destination_key in seen_destinations:
                    continue
                seen_destinations.add(destination_key)
                destinations.append((destination, destination_key))

            while True:
                converter.diagnostics.set_outcome(current)
                if not reset_managed_report_publications():
                    canonical_refresh_disabled = True
                canonical_reports_current = False
                report_repair_error: Exception | None = None
                for destination, destination_key in destinations:
                    if (
                        canonical_refresh_disabled
                        and protect_managed_reports
                        and _resolved_path_is_within(
                            destination,
                            args.godot_project,
                        )
                    ):
                        # Once a managed repair or artifact publication fails
                        # while a current manifest is protected, preserve the
                        # exact diagnostic files described by that manifest.
                        # Failed and cancelled attempts have no new canonical
                        # candidate, so their terminal diagnostics must still
                        # be published when no current manifest is protected.
                        continue
                    try:
                        checkpoint = managed_report_checkpoint(destination)
                        publication_destination = (
                            checkpoint.destination
                            if checkpoint is not None
                            else destination
                        )
                        receipt = converter.diagnostics.publish_reports(
                            publication_destination
                        )
                    except Exception as error:
                        # A failed late repair must not delete a previously
                        # trustworthy report or its canonical manifest.
                        if report_repair_error is None:
                            report_repair_error = error
                        continue
                    else:
                        if checkpoint is not None:
                            checkpoint.receipt = receipt
                        if destination_key == canonical_destination_key:
                            canonical_reports_current = True

                observed = observe_cancellation(current)
                if observed.state != current.state:
                    current = observed
                    continue

                if (
                    report_repair_error is not None
                    and current.state in {"success", "partial"}
                ):
                    canonical_refresh_disabled = True
                    late_report_error = report_repair_error
                    restore_managed_reports()
                    current = replace(
                        current,
                        state="failed",
                        failed_step="conversion_diagnostics",
                        failure_phase="finalizer",
                    )
                    converter.diagnostics.set_outcome(current)
                    continue

                if canonical_destination_key is not None:
                    if canonical_reports_current and not canonical_refresh_disabled:
                        try:
                            manifest_path, _attempt_path = (
                                converter.refresh_conversion_artifacts(current)
                            )
                        except Exception as error:
                            canonical_refresh_disabled = True
                            restore_managed_reports()
                            if current.state in {"success", "partial"}:
                                late_artifact_error = error
                                current = replace(
                                    current,
                                    state="failed",
                                    failed_step="conversion_artifacts",
                                    failure_phase="finalizer",
                                )
                                converter.diagnostics.set_outcome(current)
                                continue
                            try:
                                converter.publish_conversion_attempt(current)
                            except Exception as error:
                                attempt_publication_error = error
                            else:
                                attempt_publication_error = None
                        else:
                            attempt_publication_error = None
                            if manifest_path is None and protect_managed_reports:
                                restore_managed_reports()
                                canonical_refresh_disabled = True
                            else:
                                managed_report_checkpoints.clear()
                                report_restore_error = None
                                if manifest_path is not None:
                                    protect_managed_reports = True
                    else:
                        if protect_managed_reports and managed_report_checkpoints:
                            restore_managed_reports()
                            canonical_refresh_disabled = True
                        try:
                            converter.publish_conversion_attempt(current)
                        except Exception as error:
                            attempt_publication_error = error
                        else:
                            attempt_publication_error = None

                observed = observe_cancellation(current)
                if observed.state == current.state:
                    return observed
                current = observed

        outcome: ConversionOutcome | None = None
        preflight_error: ConversionPreflightError | None = None
        runtime_error: Exception | None = None
        primary_exit_code: int | None = None
        primary_stderr: str | None = None
        try:
            outcome = converter.convert(
                args.gm_project,
                args.platform,
                args.godot_project,
                _settings_for_args(args),
                diagnostics=conversion_diagnostics,
            )
        except ConversionPreflightError as error:
            preflight_error = error
        except Exception as error:
            runtime_error = error

        if preflight_error is not None:
            diagnostic = converter.diagnostics.add(
                "error",
                preflight_error.code,
                str(preflight_error),
                source_path=preflight_error.destination_path,
                resource_type="project",
                workaround=preflight_error.workaround,
            )
            outcome = _failed_conversion_outcome(
                converter.diagnostics,
                failure_phase="preflight",
            )
            primary_exit_code = 2
            primary_stderr = json.dumps(diagnostic.to_dict(), sort_keys=True)
        elif runtime_error is not None:
            outcome = _failed_conversion_outcome(
                converter.diagnostics,
                failure_phase="runtime",
            )
            primary_exit_code = 1
            primary_stderr = f"GM2Godot conversion failed: {runtime_error}"
        elif outcome is None:
            outcome = _failed_conversion_outcome(
                converter.diagnostics,
                failure_phase="missing-outcome",
            )

        canonical_reports_authorized = (
            preflight_error is None and outcome.failure_phase != "preflight"
        )
        protect_managed_reports = (
            preflight_error is None
            and runtime_error is None
            and outcome.state in {"success", "partial"}
            and _regular_conversion_manifest_exists(args.godot_project)
        )
        external_report_dir = _safe_conversion_report_destination(
            args.report_dir,
            preflight_failed=outcome.failure_phase == "preflight",
            preflight_error=preflight_error,
            gm_project_path=args.gm_project,
            godot_project_path=args.godot_project,
        )

        state_before_log_flush = outcome.state
        _print_conversion_logs(logs)
        outcome = observe_cancellation(outcome)
        reports_need_repair = (
            outcome.state != state_before_log_flush
            or runtime_error is not None
            or outcome.state in {"failed", "cancelled"}
        )
        report_state = outcome.state
        report_error: Exception | None = None
        try:
            external_checkpoint = (
                managed_report_checkpoint(external_report_dir)
                if external_report_dir is not None
                else None
            )
            external_publication_destination = (
                external_checkpoint.destination
                if external_checkpoint is not None
                else external_report_dir
            )
            external_receipt = _write_external_conversion_reports(
                external_publication_destination,
                args.platform,
                converter.diagnostics,
            )
            if external_checkpoint is not None and external_receipt is not None:
                external_checkpoint.receipt = external_receipt
        except Exception as error:
            report_error = error
        else:
            if (
                canonical_reports_authorized
                and external_report_dir is not None
                and _resolved_path_is_within(
                    external_report_dir,
                    args.godot_project,
                )
            ):
                # Reports written inside managed output after Converter's
                # initial artifact commit must enter the canonical file ledger.
                reports_need_repair = True

        outcome = observe_cancellation(outcome)
        report_failure_stderr: str | None = None
        if (
            report_error is not None
            and primary_exit_code is None
            and outcome.state in {"success", "partial"}
        ):
            outcome = replace(
                outcome,
                state="failed",
                failed_step="external_reports",
                failure_phase="report",
            )
            converter.diagnostics.set_outcome(outcome)
            report_failure_stderr = (
                f"GM2Godot external report generation failed: {report_error}"
            )
            reports_need_repair = True

        if outcome.state != report_state:
            reports_need_repair = True

        if report_error is not None or reports_need_repair:
            outcome = repair_conversion_reports(outcome)

        observed = observe_cancellation(outcome)
        if observed.state != outcome.state:
            outcome = repair_conversion_reports(observed)
        else:
            outcome = observed

        summary_output = ""
        while True:
            try:
                terminal_summary_phase = "preparing"
                observed = observe_cancellation(outcome)
                if observed.state != outcome.state:
                    outcome = repair_conversion_reports(observed)
                else:
                    outcome = observed

                summary_buffer = io.StringIO()
                with redirect_stdout(summary_buffer):
                    _print_conversion_summary(outcome)

                observed = observe_cancellation(outcome)
                if observed.state != outcome.state:
                    outcome = repair_conversion_reports(observed)
                    continue

                outcome = observed
                summary_output = summary_buffer.getvalue()
                terminal_summary_phase = "committing"
                sys.stdout.write(summary_output)
                terminal_summary_phase = "committed"
            except _TerminalSummaryInterrupted:
                terminal_summary_phase = "idle"
                outcome = repair_conversion_reports(
                    observe_cancellation(outcome)
                )
            else:
                break

        if outcome.state == "cancelled":
            exit_code = 130
        elif primary_stderr is not None:
            print(primary_stderr, file=sys.stderr)
            _print_conversion_failure_details(runtime_error)
            if (
                runtime_error is not None
                and report_error is not None
                and outcome.failure_phase != "preflight"
            ):
                _print_conversion_failure_detail(
                    f"external report generation failed: {report_error}"
                )
                _print_conversion_failure_details(report_error)
            exit_code = primary_exit_code if primary_exit_code is not None else 1
        elif primary_exit_code is not None:
            exit_code = primary_exit_code
        elif report_failure_stderr is not None:
            print(report_failure_stderr, file=sys.stderr)
            _print_conversion_failure_details(report_error)
            exit_code = 1
        elif late_report_error is not None:
            print(
                "GM2Godot conversion report repair failed: "
                f"{late_report_error}",
                file=sys.stderr,
            )
            _print_conversion_failure_details(late_report_error)
            exit_code = 1
        elif late_artifact_error is not None:
            print(
                "GM2Godot conversion artifact publication failed: "
                f"{late_artifact_error}",
                file=sys.stderr,
            )
            _print_conversion_failure_details(late_artifact_error)
            exit_code = 1
        else:
            exit_code = _conversion_outcome_exit_code(
                outcome,
                converter.diagnostics,
                args,
            )

        if attempt_publication_error is not None:
            print(
                "GM2Godot terminal conversion attempt publication failed: "
                f"{attempt_publication_error}",
                file=sys.stderr,
            )
            _print_conversion_failure_details(attempt_publication_error)
            if exit_code == 0:
                exit_code = 1
        if report_restore_error is not None:
            print(
                "GM2Godot managed conversion report restoration failed: "
                f"{report_restore_error}",
                file=sys.stderr,
            )
            _print_conversion_failure_details(report_restore_error)
            if exit_code == 0:
                exit_code = 1

        try:
            restore_sigint_handler()
            return exit_code
        except KeyboardInterrupt:
            if terminal_summary_phase == "committed":
                return exit_code
            raise
    finally:
        if handler_installed and not sigint_handler_restored:
            try:
                signal.signal(signal.SIGINT, previous_sigint)
            except KeyboardInterrupt:
                if terminal_summary_phase != "committed":
                    raise


def _failed_conversion_outcome(
    diagnostics: DiagnosticCollector,
    *,
    failure_phase: str,
) -> ConversionOutcome:
    existing = diagnostics.outcome()
    if existing is not None:
        if existing.state == "failed":
            return existing
        outcome = replace(
            existing,
            state="failed",
            failure_phase=failure_phase,
        )
    else:
        outcome = ConversionOutcome(
            state="failed",
            failure_phase=failure_phase,
        )
    diagnostics.set_outcome(outcome)
    return outcome


def _print_conversion_logs(logs: Sequence[str]) -> None:
    for message in logs:
        print(message)


def _print_conversion_summary(outcome: ConversionOutcome) -> None:
    print(outcome.summary_line())


def _exception_notes(error: BaseException) -> tuple[str, ...]:
    raw_notes = getattr(error, "__notes__", ())
    if not isinstance(raw_notes, (list, tuple)):
        return ()
    notes = cast(list[object] | tuple[object, ...], raw_notes)
    return tuple(note for note in notes if isinstance(note, str))


def _print_conversion_failure_details(error: BaseException | None) -> None:
    if error is None:
        return
    for note in _exception_notes(error):
        _print_conversion_failure_detail(note)


def _print_conversion_failure_detail(detail: str) -> None:
    print(
        f"GM2Godot conversion failure detail: {detail}",
        file=sys.stderr,
    )


def _write_external_conversion_reports(
    report_dir: str | None,
    target_platform: str,
    diagnostics: DiagnosticCollector,
) -> ConversionDiagnosticReportPublicationReceipt | None:
    if report_dir is None:
        return None
    _write_static_reports(report_dir, target_platform)
    return diagnostics.publish_reports(report_dir)


def _safe_conversion_report_destination(
    report_dir: str | None,
    *,
    preflight_failed: bool,
    preflight_error: ConversionPreflightError | None,
    gm_project_path: str,
    godot_project_path: str,
) -> str | None:
    if report_dir is None or not preflight_failed:
        return report_dir

    unsafe_roots = [
        gm_project_path,
        godot_project_path,
    ]
    if preflight_error is not None:
        unsafe_roots.append(preflight_error.destination_path)
    if any(
        _resolved_path_is_within(report_dir, unsafe_root)
        for unsafe_root in unsafe_roots
    ):
        return None
    return report_dir


def _resolved_path_is_within(path: str, root: str) -> bool:
    resolved_path_value = os.path.realpath(os.path.abspath(path))
    resolved_root_value = os.path.realpath(os.path.abspath(root))
    candidate = resolved_path_value
    while True:
        try:
            if os.path.samefile(candidate, resolved_root_value):
                return True
        except OSError:
            pass
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent

    resolved_path = _resolved_path_key(resolved_path_value)
    resolved_root = _resolved_path_key(resolved_root_value)
    try:
        return os.path.commonpath((resolved_path, resolved_root)) == resolved_root
    except ValueError:
        return False


def _resolved_path_key(path: str) -> str:
    normalized = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    if os.name == "nt" or sys.platform == "darwin":
        return normalized.casefold()
    return normalized


def _regular_conversion_manifest_exists(godot_project_path: str) -> bool:
    manifest_path = os.path.join(
        godot_project_path,
        CONVERSION_MANIFEST_RELATIVE_PATH,
    )
    try:
        manifest_stat = os.lstat(manifest_path)
    except OSError:
        return False
    return stat.S_ISREG(manifest_stat.st_mode)


def _conversion_outcome_exit_code(
    outcome: ConversionOutcome,
    diagnostics: DiagnosticCollector,
    args: argparse.Namespace,
) -> int:
    if outcome.state == "cancelled":
        return 130
    if outcome.state == "failed":
        return 1
    threshold_exit = _threshold_exit_code(diagnostics, args)
    if threshold_exit != 0:
        return threshold_exit
    if outcome.state == "partial" and not args.allow_partial:
        return 2
    return 0


def _analyze_project(gm_project_path: str, platform_name: str) -> DiagnosticCollector:
    diagnostics = DiagnosticCollector()
    _add_platform_diagnostic(diagnostics, platform_name)
    if not os.path.isdir(gm_project_path):
        diagnostics.add(
            "error",
            "GM2GD-ANALYZE-MISSING-GM-PROJECT",
            f"GameMaker project directory does not exist: {gm_project_path}",
            source_path=gm_project_path,
            workaround="Pass --gm-project with the root directory that contains the .yyp file.",
        )
        return diagnostics

    yyp_files = sorted(name for name in os.listdir(gm_project_path) if name.endswith(".yyp"))
    if not yyp_files:
        diagnostics.add(
            "warning",
            "GM2GD-ANALYZE-MISSING-YYP",
            f"No GameMaker .yyp file found for platform {platform_name}: {gm_project_path}",
            source_path=gm_project_path,
            workaround="Analyze or convert the root folder of a GameMaker project.",
        )
    elif len(yyp_files) > 1:
        diagnostics.add(
            "warning",
            "GM2GD-ANALYZE-MULTIPLE-YYP",
            f"Multiple GameMaker .yyp files found; using deterministic first file: {', '.join(yyp_files)}",
            source_path=gm_project_path,
        )
    return diagnostics


def _validate_project(
    godot_project_path: str,
    *,
    godot_binary: str | None = None,
    godot_boot_frames: int = 0,
    run_godot_validation: bool = True,
) -> DiagnosticCollector:
    diagnostics = DiagnosticCollector()
    if not os.path.isdir(godot_project_path):
        diagnostics.add(
            "error",
            "GM2GD-VALIDATE-MISSING-GODOT-PROJECT",
            f"Godot project directory does not exist: {godot_project_path}",
            source_path=godot_project_path,
        )
        return diagnostics

    project_file = os.path.join(godot_project_path, "project.godot")
    if not os.path.isfile(project_file):
        diagnostics.add(
            "warning",
            "GM2GD-VALIDATE-MISSING-PROJECT-GODOT",
            f"Godot project.godot file does not exist: {project_file}",
            source_path=project_file,
        )

    report_path = os.path.join(godot_project_path, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as report_file:
                report = json.load(report_file)
        except (OSError, json.JSONDecodeError) as exc:
            diagnostics.add(
                "error",
                "GM2GD-VALIDATE-BAD-DIAGNOSTICS-REPORT",
                f"Could not parse diagnostics report {report_path}: {exc}",
                source_path=report_path,
            )
        else:
            _import_diagnostics_report(diagnostics, report, report_path)
    else:
        diagnostics.add(
            "warning",
            "GM2GD-VALIDATE-MISSING-DIAGNOSTICS-REPORT",
            f"Diagnostics report does not exist: {report_path}",
            source_path=report_path,
        )
    if run_godot_validation:
        _add_godot_validation_diagnostic(
            diagnostics,
            godot_project_path,
            godot_binary,
            boot_frames=godot_boot_frames,
        )
    return diagnostics


def _add_platform_diagnostic(
    diagnostics: DiagnosticCollector, platform_name: str
) -> None:
    diagnostics.add(
        "info",
        "GM2GD-CLI-TARGET-PLATFORM",
        f"Target platform filter: {platform_name}",
        resource_type="platform",
        resource=platform_name,
    )


def _add_godot_validation_diagnostic(
    diagnostics: DiagnosticCollector,
    godot_project_path: str,
    godot_binary: str | None,
    *,
    boot_frames: int = 0,
) -> None:
    report = validate_generated_godot_project(
        godot_project_path,
        godot_binary=godot_binary,
        boot_frames=boot_frames,
    )
    write_godot_validation_report(godot_project_path, report)
    if report.status == "passed":
        diagnostics.add(
            "info",
            "GM2GD-GODOT-VALIDATION",
            report.message,
            source_path=godot_project_path,
        )
        return
    if report.status == "skipped":
        diagnostics.add(
            "info",
            "GM2GD-GODOT-VALIDATION-SKIPPED",
            report.message,
            source_path=godot_project_path,
            workaround="Install Godot and set GODOT_BIN, or pass --godot-bin to validate generated resources.",
        )
        return
    diagnostics.add(
        "error",
        "GM2GD-GODOT-VALIDATION-FAILED",
        report.message,
        source_path=godot_project_path,
        workaround="Open the generated project with the pinned Godot version and fix the first parser/resource error reported in gm2godot/godot_validation_report.json.",
    )


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected a non-negative integer: {value}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"Expected a non-negative integer: {value}")
    return parsed


def _import_diagnostics_report(
    diagnostics: DiagnosticCollector, report: object, report_path: str
) -> None:
    if not isinstance(report, dict):
        diagnostics.add(
            "error",
            "GM2GD-VALIDATE-BAD-DIAGNOSTICS-SHAPE",
            f"Diagnostics report root must be an object: {report_path}",
            source_path=report_path,
        )
        return

    typed_report = cast(dict[str, object], report)
    report_diagnostics = typed_report.get("diagnostics")
    if not isinstance(report_diagnostics, list):
        diagnostics.add(
            "error",
            "GM2GD-VALIDATE-BAD-DIAGNOSTICS-SHAPE",
            f"Diagnostics report must contain a diagnostics array: {report_path}",
            source_path=report_path,
        )
        return

    for item in cast(list[object], report_diagnostics):
        if not isinstance(item, dict):
            diagnostics.add(
                "warning",
                "GM2GD-VALIDATE-SKIPPED-DIAGNOSTIC",
                f"Skipped malformed diagnostic entry in {report_path}.",
                source_path=report_path,
            )
            continue

        typed_item = cast(dict[str, object], item)
        diagnostics.add(
            _diagnostic_severity_from_report(typed_item.get("severity")),
            _string_field(typed_item.get("code"), "GM2GD-VALIDATE-IMPORTED"),
            _string_field(typed_item.get("message"), "Imported diagnostic from report."),
            source_path=_optional_string_field(typed_item.get("source_path")),
            line=_optional_int_field(typed_item.get("line")),
            column=_optional_int_field(typed_item.get("column")),
            resource=_optional_string_field(typed_item.get("resource")),
            resource_type=_optional_string_field(typed_item.get("resource_type")),
            event=_optional_string_field(typed_item.get("event")),
            api=_optional_string_field(typed_item.get("api")),
            manifest_entry=_optional_string_field(typed_item.get("manifest_entry")),
            issue_number=_optional_int_field(typed_item.get("issue_number")),
            workaround=_optional_string_field(typed_item.get("workaround")),
        )


def _settings_for_args(args: argparse.Namespace) -> dict[str, CLISetting]:
    all_keys = [
        key
        for keys in CONVERSION_CATEGORIES.values()
        for key in keys
        if key not in _NON_CONVERTER_SETTING_KEYS
    ]
    settings = {key: CLISetting(False) for key in all_keys}

    only = _split_csv(args.only)
    if only:
        for key in only:
            if key not in settings:
                raise SystemExit(f"Unknown converter key for --only: {key}")
            settings[key] = CLISetting(True)
    else:
        selected_groups = _split_csv(args.groups)
        for group in selected_groups:
            if group not in CONVERSION_CATEGORIES:
                raise SystemExit(f"Unknown conversion group for --groups: {group}")
            for key in CONVERSION_CATEGORIES[group]:
                settings[key] = CLISetting(True)

    settings["sound_group_folders"] = CLISetting(bool(args.sound_group_folders))
    return settings


def _converter_inventory() -> ConverterInventory:
    groups = {
        group: [key for key in keys if key not in _NON_CONVERTER_SETTING_KEYS]
        for group, keys in CONVERSION_CATEGORIES.items()
    }
    converter_keys = sorted({key for keys in groups.values() for key in keys})
    return {
        "default_groups": list(DEFAULT_CONVERSION_GROUPS),
        "groups": groups,
        "converter_keys": converter_keys,
    }


def _print_converter_inventory(output_format: str) -> None:
    inventory = _converter_inventory()
    if output_format == "json":
        print(json.dumps(inventory, indent=2, sort_keys=True))
        return

    print("Default groups: " + ", ".join(inventory["default_groups"]))
    print("")
    print("Conversion groups:")
    for group, keys in inventory["groups"].items():
        print(f"  {group}: {', '.join(keys)}")
    print("")
    print("Converter keys:")
    for key in inventory["converter_keys"]:
        print(f"  {key}")


def _write_static_reports(report_dir: str, target_platform: str | None = None) -> None:
    reports = (
        (_STATIC_REPORT_FILENAMES[0], render_gml_manual_scope_markdown()),
        (_STATIC_REPORT_FILENAMES[1], _render_api_compatibility_markdown()),
        (
            _STATIC_REPORT_FILENAMES[2],
            json.dumps(
                generate_platform_capability_report(target_platform),
                indent=2,
                sort_keys=True,
            )
            + "\n",
        ),
        (
            _STATIC_REPORT_FILENAMES[3],
            render_platform_capability_markdown(target_platform),
        ),
    )
    _publish_static_report_texts(report_dir, reports)


def _publish_static_report_texts(
    report_dir: str,
    reports: Sequence[tuple[str, str]],
) -> None:
    """Publish the complete report set while preserving its exact prior state."""
    specs = tuple(
        ArtifactSpec(filename, content.encode("utf-8"))
        for filename, content in reports
    )
    with ByteArtifactTransaction.open(
        os.path.abspath(report_dir),
        _STATIC_REPORT_DIRECTORY,
        create=True,
        create_root=True,
        description=_STATIC_REPORT_DIRECTORY_DESCRIPTION,
    ) as transaction:
        receipts = transaction.publish_specs(specs)
        if any(receipt is None for receipt in receipts):
            raise AssertionError("Published static reports must all be present.")


def _render_api_compatibility_markdown() -> str:
    lines = [
        "# GML API Compatibility",
        "",
        "| Category | Implemented | Partial | Planned | Unsupported | Out of scope | Total | Issue |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in generate_gml_api_compatibility_report():
        lines.append(
            f"| {row.category} | {row.implemented} | {row.partial} | {row.planned} | "
            f"{row.unsupported} | {row.out_of_scope} | {row.total} | #{row.issue_number} |"
        )
    return "\n".join(lines) + "\n"


def _threshold_exit_code(diagnostics: DiagnosticCollector, args: argparse.Namespace) -> int:
    summary = diagnostics.summary()
    unsupported_count = sum(
        1
        for diagnostic in diagnostics.diagnostics()
        if "unsupported" in diagnostic.code.lower()
        or "unsupported" in diagnostic.message.lower()
    )

    max_unsupported = 0 if args.fail_on_unsupported else args.max_unsupported
    if max_unsupported is not None and unsupported_count > max_unsupported:
        return 2
    if args.max_errors is not None and summary["error"] > args.max_errors:
        return 2
    if args.max_warnings is not None and summary["warning"] > args.max_warnings:
        return 2
    return 0


def _diagnostic_severity_from_report(value: object) -> DiagnosticSeverity:
    if value == "info":
        return "info"
    if value == "warning":
        return "warning"
    if value == "error":
        return "error"
    return "warning"


def _string_field(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return value
    return fallback


def _optional_string_field(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _optional_int_field(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _default_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "windows"


if __name__ == "__main__":
    sys.exit(main())
