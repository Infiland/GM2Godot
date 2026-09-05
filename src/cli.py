from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from dataclasses import replace
from typing import Sequence, cast

from src.cli_configuration import (
    ConvertRequest,
    DiagnosticThresholds,
    build_parser,
    convert_request_from_args,
    converter_inventory,
    settings_for_selection,
    thresholds_from_args,
)
from src.cli_session import ConversionSession
from src.conversion.anchored_artifacts import ArtifactSpec, ByteArtifactTransaction
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.converter import Converter
from src.conversion.diagnostics import (
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    ConversionDiagnosticReportPublicationReceipt,
    DiagnosticCollector,
    DiagnosticSeverity,
)
from src.conversion.gml_transpiler import generate_gml_api_compatibility_report, render_gml_manual_scope_markdown
from src.conversion.godot_validation import validate_generated_godot_project, write_godot_validation_report
from src.conversion.platform_capabilities import (
    generate_platform_capability_report,
    render_platform_capability_markdown,
)
from src.conversion.project_godot import MANAGED_OUTPUT_DIRECTORIES, ConversionPreflightError
from src.version import get_version

_STATIC_REPORT_DIRECTORY = "gm2godot"
_STATIC_REPORT_DIRECTORY_DESCRIPTION = "CLI static report directory"
_STATIC_REPORT_FILENAMES = (
    "gml_manual_scope.md",
    "gml_api_compatibility.md",
    "platform_capability_report.json",
    "platform_capability_report.md",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
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
        return _threshold_exit_code(diagnostics, thresholds_from_args(args))

    if args.command == "analyze":
        diagnostics = _analyze_project(args.gm_project, args.platform)
        _write_static_reports(args.report_dir, args.platform)
        diagnostics.write_reports(args.report_dir)
        return _threshold_exit_code(diagnostics, thresholds_from_args(args))

    if args.command == "convert":
        return _run_convert(convert_request_from_args(args))

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
        return _threshold_exit_code(diagnostics, thresholds_from_args(args))

    parser.print_help()
    return 2


def _run_convert(request: ConvertRequest) -> int:
    logs: list[str] = []
    session = ConversionSession()
    external_report_dir: str | None = request.report_dir
    late_report_error: Exception | None = None
    attempt_publication_error: Exception | None = None

    try:
        session.install_sigint_handler()

        try:
            managed_report_relative = _managed_report_relative_path(
                request.report_dir,
                request.godot_project,
            )
        except ValueError as error:
            print(
                f"GM2Godot conversion report destination is unsafe: {error}",
                file=sys.stderr,
            )
            return 2
        conversion_diagnostics = DiagnosticCollector()
        _add_platform_diagnostic(conversion_diagnostics, request.platform)

        def write_staged_cli_reports(staged_path: str) -> None:
            if managed_report_relative is None:
                return
            staged_report_root = os.path.normpath(
                os.path.join(staged_path, managed_report_relative)
            )
            _write_static_reports(staged_report_root, request.platform)
            if managed_report_relative not in {"", os.curdir}:
                conversion_diagnostics.publish_reports(staged_report_root)

        converter = Converter(
            log_callback=lambda message: logs.append(message),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=session.running,
            staged_output_finalizer=(
                write_staged_cli_reports
                if managed_report_relative is not None
                else None
            ),
        )

        def observe_cancellation(current: ConversionOutcome) -> ConversionOutcome:
            if (
                session.sigint_received
                and not session.managed_generation_decided
                and current.state != "cancelled"
            ):
                current = replace(current, state="cancelled")
            converter.diagnostics.set_outcome(current)
            return current

        def repair_conversion_reports(current: ConversionOutcome) -> ConversionOutcome:
            nonlocal late_report_error
            while True:
                converter.diagnostics.set_outcome(current)
                report_repair_error: Exception | None = None
                if external_report_dir is not None:
                    try:
                        converter.diagnostics.publish_reports(external_report_dir)
                    except Exception as error:
                        report_repair_error = error

                observed = observe_cancellation(current)
                if observed.state != current.state:
                    current = observed
                    continue
                if report_repair_error is not None and current.state in {"success", "partial"}:
                    late_report_error = report_repair_error
                    current = replace(
                        current,
                        state="failed",
                        failed_step="conversion_diagnostics",
                        failure_phase="finalizer",
                    )
                    converter.diagnostics.set_outcome(current)
                    continue
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
                request.gm_project,
                request.platform,
                request.godot_project,
                settings_for_selection(request.selection),
                diagnostics=conversion_diagnostics,
            )
        except ConversionPreflightError as error:
            preflight_error = error
        except Exception as error:
            runtime_error = error
        finally:
            session.managed_generation_decided = True

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

        external_report_dir = _safe_conversion_report_destination(
            request.report_dir,
            preflight_failed=outcome.failure_phase == "preflight",
            preflight_error=preflight_error,
            gm_project_path=request.gm_project,
            godot_project_path=request.godot_project,
        )
        if managed_report_relative is not None:
            external_report_dir = None

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
            _write_external_conversion_reports(external_report_dir, request.platform, converter.diagnostics)
        except Exception as error:
            report_error = error

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

        published_outcome = converter.last_outcome
        if (
            isinstance(published_outcome, ConversionOutcome)
            and published_outcome != outcome
        ):
            try:
                converter.publish_conversion_attempt(outcome)
            except Exception as error:
                attempt_publication_error = error
            else:
                attempt_publication_error = None

        summary_output = ""
        while True:
            try:
                session.terminal_summary_phase = "preparing"
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
                session.terminal_summary_phase = "committing"
                sys.stdout.write(summary_output)
                session.terminal_summary_phase = "committed"
            except session.terminal_summary_interrupted:
                session.terminal_summary_phase = "idle"
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
        else:
            exit_code = _conversion_outcome_exit_code(
                outcome,
                converter.diagnostics,
                request,
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

        try:
            session.restore_sigint_handler()
            return exit_code
        except KeyboardInterrupt:
            if session.terminal_summary_phase == "committed":
                return exit_code
            raise
    finally:
        session.restore_sigint_handler_fallback()


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


def _managed_report_relative_path(
    report_dir: str | None,
    godot_project_path: str,
) -> str | None:
    if report_dir is None:
        return None
    project_root = os.path.realpath(os.path.abspath(godot_project_path))
    report_root = os.path.realpath(os.path.abspath(report_dir))
    generated_report_root = os.path.join(report_root, _STATIC_REPORT_DIRECTORY)
    matching_roots = tuple(
        relative_path
        for relative_path in MANAGED_OUTPUT_DIRECTORIES
        if _resolved_path_is_within(
            generated_report_root,
            os.path.join(project_root, relative_path),
        )
    )
    if not matching_roots:
        return None
    evidence_root = "gm2godot"
    if evidence_root not in {
        relative_path.replace("\\", "/") for relative_path in matching_roots
    }:
        raise ValueError(
            "generated reports would enter a converter-owned managed root; "
            "choose the project root, a path under its gm2godot directory, "
            "or an external report directory"
        )
    try:
        relative = os.path.relpath(report_root, project_root)
    except ValueError:
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    return relative


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


def _conversion_outcome_exit_code(
    outcome: ConversionOutcome,
    diagnostics: DiagnosticCollector,
    request: ConvertRequest,
) -> int:
    if outcome.state == "cancelled":
        return 130
    if outcome.state == "failed":
        return 1
    threshold_exit = _threshold_exit_code(diagnostics, request.thresholds)
    if threshold_exit != 0:
        return threshold_exit
    if outcome.state == "partial" and not request.allow_partial:
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


def _print_converter_inventory(output_format: str) -> None:
    inventory = converter_inventory()
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


def _threshold_exit_code(diagnostics: DiagnosticCollector, thresholds: DiagnosticThresholds) -> int:
    summary = diagnostics.summary()
    unsupported_count = sum(
        1
        for diagnostic in diagnostics.diagnostics()
        if "unsupported" in diagnostic.code.lower()
        or "unsupported" in diagnostic.message.lower()
    )

    max_unsupported = 0 if thresholds.fail_on_unsupported else thresholds.max_unsupported
    if max_unsupported is not None and unsupported_count > max_unsupported:
        return 2
    if thresholds.max_errors is not None and summary["error"] > thresholds.max_errors:
        return 2
    if thresholds.max_warnings is not None and summary["warning"] > thresholds.max_warnings:
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


if __name__ == "__main__":
    sys.exit(main())
