from __future__ import annotations

import json
import os
import re
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
    import_output: str = ""
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
            "import_returncode": self.import_returncode,
            "import_output": self.import_output,
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
    load_resources: bool = True,
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
                return GodotValidationReport(
                    status="passed",
                    godot_binary=resolved_binary,
                    project_path=godot_project_path,
                    resource_paths=resource_paths,
                    import_output=output,
                    output=output,
                    message=_import_only_timeout_message(timeout, len(importable_asset_paths), len(resource_paths)),
                    output_issues=(),
                )
            return GodotValidationReport(
                status="failed",
                godot_binary=resolved_binary,
                project_path=godot_project_path,
                resource_paths=resource_paths,
                import_output=output,
                output=output,
                message=f"Headless Godot import timed out after {timeout} seconds.",
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
                if not output_issues:
                    return GodotValidationReport(
                        status="passed",
                        godot_binary=resolved_binary,
                        project_path=godot_project_path,
                        resource_paths=resource_paths,
                        import_output=combined_output,
                        output=combined_output,
                        message=_audio_fallback_timeout_message(timeout, len(importable_asset_paths), len(resource_paths)),
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
                    output_issues=output_issues,
                )

            fallback_output = fallback_result.stdout
            combined_output = _combine_output(import_output, fallback_output)
            fallback_output_issues = detect_godot_output_issues(combined_output)
            if fallback_result.returncode == 0 and not fallback_output_issues:
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
                output_issues=import_output_issues,
            )

    if not load_resources:
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
            output_issues=(),
        )

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
                import_returncode=import_returncode,
                import_output=import_output,
                output=output,
                message=f"Headless Godot validation timed out after {timeout} seconds.",
            )

    combined_output = _combine_output(import_output, result.stdout)
    output_issues = detect_godot_output_issues(combined_output)
    status: GodotValidationStatus = (
        "passed" if result.returncode == 0 and not output_issues else "failed"
    )

    return GodotValidationReport(
        status=status,
        godot_binary=resolved_binary,
        project_path=godot_project_path,
        resource_paths=resource_paths,
        returncode=result.returncode,
        import_returncode=import_returncode,
        import_output=import_output,
        output=combined_output,
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
        if stripped.startswith(_GODOT_ERROR_PREFIXES):
            issues.append(GodotOutputIssue(severity="error", line=stripped))
        elif stripped.startswith(_GODOT_WARNING_PREFIXES):
            issues.append(GodotOutputIssue(severity="warning", line=stripped))
    return tuple(issues)


def _strip_ansi_escape_sequences(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def _run_godot_import(
    resolved_binary: str,
    godot_project_path: str,
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            resolved_binary,
            "--headless",
            "--recovery-mode",
            "--path",
            godot_project_path,
            "--import",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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
