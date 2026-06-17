from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Literal, TypeAlias

from src.conversion.type_defs import JsonDict

GODOT_VALIDATION_REPORT_RELATIVE_PATH = os.path.join(
    "gm2godot", "godot_validation_report.json"
)
GodotValidationStatus: TypeAlias = Literal["passed", "failed", "skipped"]
GodotOutputIssueSeverity: TypeAlias = Literal["warning", "error"]
_LOADABLE_EXTENSIONS = (".gd", ".gdshader", ".tscn", ".tres")
_GODOT_ERROR_PREFIXES = ("ERROR:", "SCRIPT ERROR:", "SHADER ERROR:")
_GODOT_WARNING_PREFIXES = ("WARNING:", "SCRIPT WARNING:", "SHADER WARNING:")


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
    output: str = ""
    message: str = ""
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
            "output": self.output,
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

    for candidate in (
        "/Applications/Godot.app/Contents/MacOS/Godot",
        "/tmp/godot-4.4.1-macos/Godot.app/Contents/MacOS/Godot",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def validate_generated_godot_project(
    godot_project_path: str,
    *,
    godot_binary: str | None = None,
    timeout: int = 60,
) -> GodotValidationReport:
    resolved_binary = find_godot_binary(godot_binary)
    resource_paths = generated_godot_resource_paths(godot_project_path)
    if resolved_binary is None:
        return GodotValidationReport(
            status="skipped",
            godot_binary="",
            project_path=godot_project_path,
            resource_paths=resource_paths,
            message="Godot binary not found; set GODOT_BIN or pass --godot-bin to run generated resource validation.",
        )

    if not os.path.isfile(os.path.join(godot_project_path, "project.godot")):
        return GodotValidationReport(
            status="failed",
            godot_binary=resolved_binary,
            project_path=godot_project_path,
            resource_paths=resource_paths,
            message="project.godot is missing; generated resources cannot be loaded through Godot.",
        )

    script = _validation_script(resource_paths)
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "gm2godot_validate.gd")
        with open(script_path, "w", encoding="utf-8") as script_file:
            script_file.write(script)
        try:
            result = subprocess.run(
                [
                    resolved_binary,
                    "--headless",
                    "--path",
                    godot_project_path,
                    "--script",
                    script_path,
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
            return GodotValidationReport(
                status="failed",
                godot_binary=resolved_binary,
                project_path=godot_project_path,
                resource_paths=resource_paths,
                output=output,
                message=f"Headless Godot validation timed out after {timeout} seconds.",
            )

    output_issues = detect_godot_output_issues(result.stdout)
    status: GodotValidationStatus = (
        "passed" if result.returncode == 0 and not output_issues else "failed"
    )

    return GodotValidationReport(
        status=status,
        godot_binary=resolved_binary,
        project_path=godot_project_path,
        resource_paths=resource_paths,
        returncode=result.returncode,
        output=result.stdout,
        message=_validation_message(result.returncode, len(resource_paths), output_issues),
        output_issues=output_issues,
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


def detect_godot_output_issues(output: str) -> tuple[GodotOutputIssue, ...]:
    issues: list[GodotOutputIssue] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_GODOT_ERROR_PREFIXES):
            issues.append(GodotOutputIssue(severity="error", line=stripped))
        elif stripped.startswith(_GODOT_WARNING_PREFIXES):
            issues.append(GodotOutputIssue(severity="warning", line=stripped))
    return tuple(issues)


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
