"""CLI argument parsing, raw requests and conversion setting selection."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TypedDict

from src.conversion.converter import CONVERSION_CATEGORIES

DEFAULT_CONVERSION_GROUPS = ("assets", "project", "wip")
_NON_CONVERTER_SETTING_KEYS = frozenset({"sound_group_folders"})


class ConverterInventory(TypedDict):
    default_groups: list[str]
    groups: dict[str, list[str]]
    converter_keys: list[str]


@dataclass(frozen=True)
class CLISetting:
    value: bool

    def get(self) -> bool:
        return self.value


@dataclass(frozen=True)
class ConverterSelection:
    only: str
    groups: str
    sound_group_folders: bool


@dataclass(frozen=True)
class DiagnosticThresholds:
    fail_on_unsupported: bool
    max_unsupported: int | None
    max_errors: int | None
    max_warnings: int | None


@dataclass(frozen=True)
class ConvertRequest:
    gm_project: str
    platform: str
    godot_project: str
    selection: ConverterSelection
    report_dir: str | None
    allow_partial: bool
    thresholds: DiagnosticThresholds


def thresholds_from_args(args: argparse.Namespace) -> DiagnosticThresholds:
    return DiagnosticThresholds(
        args.fail_on_unsupported, args.max_unsupported, args.max_errors, args.max_warnings,
    )


def convert_request_from_args(args: argparse.Namespace) -> ConvertRequest:
    return ConvertRequest(
        args.gm_project,
        args.platform,
        args.godot_project,
        ConverterSelection(args.only, args.groups, args.sound_group_folders),
        args.report_dir,
        args.allow_partial,
        thresholds_from_args(args),
    )


def build_parser() -> argparse.ArgumentParser:
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


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected a non-negative integer: {value}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"Expected a non-negative integer: {value}")
    return parsed


def settings_for_selection(selection: ConverterSelection) -> dict[str, CLISetting]:
    all_keys = [
        key
        for keys in CONVERSION_CATEGORIES.values()
        for key in keys
        if key not in _NON_CONVERTER_SETTING_KEYS
    ]
    settings = {key: CLISetting(False) for key in all_keys}

    only = _split_csv(selection.only)
    if only:
        for key in only:
            if key not in settings:
                raise SystemExit(f"Unknown converter key for --only: {key}")
            settings[key] = CLISetting(True)
    else:
        selected_groups = _split_csv(selection.groups)
        for group in selected_groups:
            if group not in CONVERSION_CATEGORIES:
                raise SystemExit(f"Unknown conversion group for --groups: {group}")
            for key in CONVERSION_CATEGORIES[group]:
                settings[key] = CLISetting(True)

    settings["sound_group_folders"] = CLISetting(bool(selection.sound_group_folders))
    return settings


def converter_inventory() -> ConverterInventory:
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


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _default_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "windows"
