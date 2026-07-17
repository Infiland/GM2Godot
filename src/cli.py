from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass
from typing import Sequence, TypedDict, cast

from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.conversion.diagnostics import (
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    DiagnosticSeverity,
    DiagnosticCollector,
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


class ConverterInventory(TypedDict):
    default_groups: list[str]
    groups: dict[str, list[str]]
    converter_keys: list[str]


@dataclass(frozen=True)
class CLISetting:
    value: bool

    def get(self) -> bool:
        return self.value


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
    converter = Converter(
        log_callback=lambda message: logs.append(message),
        progress_callback=lambda _value: None,
        status_callback=lambda _message: None,
        conversion_running=running,
    )
    conversion_diagnostics = DiagnosticCollector()
    _add_platform_diagnostic(conversion_diagnostics, args.platform)
    try:
        converter.convert(
            args.gm_project,
            args.platform,
            args.godot_project,
            _settings_for_args(args),
            diagnostics=conversion_diagnostics,
        )
    except ConversionPreflightError as error:
        diagnostic = converter.diagnostics.add(
            "error",
            error.code,
            str(error),
            source_path=error.destination_path,
            resource_type="project",
            workaround=error.workaround,
        )
        for message in logs:
            print(message)
        print(json.dumps(diagnostic.to_dict(), sort_keys=True), file=sys.stderr)
        if args.report_dir:
            _write_static_reports(args.report_dir, args.platform)
            converter.diagnostics.write_reports(args.report_dir)
        return 2
    for message in logs:
        print(message)
    if args.report_dir:
        _write_static_reports(args.report_dir, args.platform)
        converter.diagnostics.write_reports(args.report_dir)
    return _threshold_exit_code(converter.diagnostics, args)


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
    all_keys = [key for keys in CONVERSION_CATEGORIES.values() for key in keys]
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
    groups = {group: list(keys) for group, keys in CONVERSION_CATEGORIES.items()}
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
    report_root = os.path.join(report_dir, "gm2godot")
    os.makedirs(report_root, exist_ok=True)
    with open(os.path.join(report_root, "gml_manual_scope.md"), "w", encoding="utf-8") as manual_file:
        manual_file.write(render_gml_manual_scope_markdown())
    with open(os.path.join(report_root, "gml_api_compatibility.md"), "w", encoding="utf-8") as api_file:
        api_file.write(_render_api_compatibility_markdown())
    with open(os.path.join(report_root, "platform_capability_report.json"), "w", encoding="utf-8") as capability_file:
        json.dump(
            generate_platform_capability_report(target_platform),
            capability_file,
            indent=2,
            sort_keys=True,
        )
        capability_file.write("\n")
    with open(os.path.join(report_root, "platform_capability_report.md"), "w", encoding="utf-8") as capability_markdown:
        capability_markdown.write(render_platform_capability_markdown(target_platform))


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
