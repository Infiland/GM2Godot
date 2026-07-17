import json
import os
import re
import stat
import tempfile
from collections.abc import Iterable
from enum import Enum
from typing import Any

from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.type_defs import StrPath


DEFAULT_GODOT_PROJECT_NAME = "GM2Godot Project"
GODOT_PROJECT_FILENAME = "project.godot"
MANAGED_OUTPUT_DIRECTORIES: tuple[str, ...] = (
    "fonts",
    "gm2godot",
    "included_files",
    "notes",
    "objects",
    "rooms",
    "scripts",
    "shaders",
    "sounds",
    "sprites",
    "tilesets",
)
MANAGED_OUTPUT_FILES: tuple[str, ...] = (
    "default_bus_layout.tres",
    "icon.ico",
    "icon.png",
)


class GodotProjectDestinationState(Enum):
    EXISTING_PROJECT = "existing_project"
    EMPTY = "empty"
    MISSING = "missing"


class ConversionPreflightError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        destination_path: str,
        workaround: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.destination_path = destination_path
        self.workaround = workaround


def format_godot_string(value: str) -> str:
    """Format a Python string as a Godot project setting string literal."""
    return json.dumps(value, ensure_ascii=False)


def inspect_godot_project_destination(
    godot_project_path: StrPath,
) -> GodotProjectDestinationState:
    """Classify a destination without creating or modifying any files."""
    destination = os.fspath(godot_project_path)
    try:
        destination_stat = os.lstat(destination)
    except FileNotFoundError:
        return GodotProjectDestinationState.MISSING
    except OSError as error:
        raise _destination_io_error(destination, "inspect", error) from error

    if stat.S_ISLNK(destination_stat.st_mode):
        raise ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-SYMLINK",
            f"Refusing to convert through a symbolic-link destination: {destination}",
            destination_path=destination,
            workaround="Choose the real destination directory instead of a symbolic link.",
        )
    if not stat.S_ISDIR(destination_stat.st_mode):
        raise ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-NOT-DIRECTORY",
            f"Godot destination exists but is not a directory: {destination}",
            destination_path=destination,
            workaround="Choose an empty directory or an existing Godot project directory.",
        )
    directory_fd = _open_destination_directory(destination)
    try:
        _verify_destination_identity(destination, directory_fd)
        state = _inspect_open_destination(destination, directory_fd)
        if state is GodotProjectDestinationState.EXISTING_PROJECT:
            _validate_managed_output_paths(destination)
        _verify_destination_identity(destination, directory_fd)
        return state
    finally:
        _close_destination_directory(directory_fd)


def prepare_godot_project_destination(
    gm_project_path: StrPath,
    godot_project_path: StrPath,
) -> str:
    """Preserve an existing Godot project or initialize a safe empty destination."""
    gm_path = os.fspath(gm_project_path)
    destination = os.fspath(godot_project_path)
    project_path = os.path.join(destination, GODOT_PROJECT_FILENAME)
    destination_state = inspect_godot_project_destination(destination)

    if destination_state is GodotProjectDestinationState.EXISTING_PROJECT:
        return project_path
    if destination_state is GodotProjectDestinationState.MISSING:
        try:
            os.makedirs(destination)
        except OSError as error:
            raise _destination_io_error(destination, "create", error) from error

    project_name = _initial_project_name(gm_path)
    project_content = _minimal_godot_project(project_name)
    directory_fd = _open_destination_directory(destination)
    try:
        _verify_destination_identity(destination, directory_fd)
        refreshed_state = _inspect_open_destination(destination, directory_fd)
        if refreshed_state is not GodotProjectDestinationState.EMPTY:
            raise ConversionPreflightError(
                "GM2GD-CONVERT-DESTINATION-CHANGED",
                f"Godot destination changed during preflight: {destination}",
                destination_path=destination,
                workaround="Inspect the destination, remove the conflicting change, then retry.",
            )
        _create_project_file_exclusively(
            destination,
            directory_fd,
            project_content.encode("utf-8"),
        )
        _verify_destination_identity(destination, directory_fd)
    except ConversionPreflightError:
        raise
    except OSError as error:
        raise _destination_io_error(
            destination,
            "write project.godot in",
            error,
        ) from error
    finally:
        _close_destination_directory(directory_fd)
    return project_path


def _open_destination_directory(destination: str) -> int | None:
    supports_directory_handle = (
        os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.listdir in os.supports_fd
    )
    if not supports_directory_handle:
        return None

    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(destination, flags)
    except OSError as error:
        raise _destination_io_error(destination, "open", error) from error


def _close_destination_directory(directory_fd: int | None) -> None:
    if directory_fd is not None:
        os.close(directory_fd)


def _verify_destination_identity(
    destination: str,
    directory_fd: int | None,
) -> None:
    try:
        path_stat = os.lstat(destination)
    except OSError as error:
        raise _destination_io_error(destination, "verify", error) from error

    destination_changed = stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(
        path_stat.st_mode
    )
    if directory_fd is not None:
        try:
            open_stat = os.fstat(directory_fd)
        except OSError as error:
            raise _destination_io_error(destination, "verify", error) from error
        destination_changed = destination_changed or (
            (path_stat.st_dev, path_stat.st_ino)
            != (open_stat.st_dev, open_stat.st_ino)
        )

    if destination_changed:
        raise ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-CHANGED",
            f"Godot destination changed during preflight: {destination}",
            destination_path=destination,
            workaround="Inspect the destination path and retry conversion.",
        )


def _inspect_open_destination(
    destination: str,
    directory_fd: int | None,
) -> GodotProjectDestinationState:
    try:
        existing_entries = sorted(
            os.listdir(directory_fd if directory_fd is not None else destination)
        )
    except OSError as error:
        raise _destination_io_error(destination, "inspect", error) from error

    if GODOT_PROJECT_FILENAME in existing_entries:
        project_stat = _project_file_stat(destination, directory_fd)
        if not stat.S_ISREG(project_stat.st_mode):
            raise _invalid_project_file_error(
                destination,
                "it is not a regular file",
            )
        project_bytes = _read_project_file(destination, directory_fd)
        invalid_reason = _invalid_godot_project_reason(project_bytes)
        if invalid_reason is not None:
            raise _invalid_project_file_error(destination, invalid_reason)
        return GodotProjectDestinationState.EXISTING_PROJECT

    if existing_entries:
        preview = ", ".join(repr(entry) for entry in existing_entries[:5])
        if len(existing_entries) > 5:
            preview += ", ..."
        raise ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-NOT-EMPTY",
            (
                "Refusing to convert into a non-empty destination without "
                f"{GODOT_PROJECT_FILENAME}: {destination}. Existing entries: {preview}"
            ),
            destination_path=destination,
            workaround=(
                "Choose an empty directory, a path that does not exist yet, or an "
                "existing Godot project containing project.godot."
            ),
        )
    return GodotProjectDestinationState.EMPTY


def _validate_managed_output_paths(destination: str) -> None:
    """Reject redirects and special files in paths conversion may overwrite."""
    destination_absolute = os.path.abspath(destination)
    destination_real = os.path.realpath(destination_absolute)

    for relative_path in MANAGED_OUTPUT_FILES:
        path = os.path.join(destination_absolute, relative_path)
        path_stat = _managed_path_stat(destination, path)
        if path_stat is None:
            continue
        if stat.S_ISLNK(path_stat.st_mode):
            raise _managed_output_symlink_error(destination, path)
        _validate_managed_path_containment(
            destination,
            destination_absolute,
            destination_real,
            path,
        )
        if not stat.S_ISREG(path_stat.st_mode):
            raise _invalid_managed_output_error(
                destination,
                path,
                "it is not a regular file",
            )
        if path_stat.st_nlink > 1:
            raise _managed_output_hardlink_error(destination, path)

    for relative_path in MANAGED_OUTPUT_DIRECTORIES:
        root = os.path.join(destination_absolute, relative_path)
        root_stat = _managed_path_stat(destination, root)
        if root_stat is None:
            continue
        if stat.S_ISLNK(root_stat.st_mode):
            raise _managed_output_symlink_error(destination, root)
        _validate_managed_path_containment(
            destination,
            destination_absolute,
            destination_real,
            root,
        )
        if not stat.S_ISDIR(root_stat.st_mode):
            raise _invalid_managed_output_error(
                destination,
                root,
                "it is not a directory",
            )
        _validate_managed_output_tree(
            destination,
            destination_absolute,
            destination_real,
            root,
        )


def _validate_managed_output_tree(
    destination: str,
    destination_absolute: str,
    destination_real: str,
    root: str,
) -> None:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = entry.path
                    try:
                        path_stat = entry.stat(follow_symlinks=False)
                    except OSError as error:
                        raise _destination_io_error(
                            destination,
                            f"inspect managed output path {path!r} in",
                            error,
                        ) from error
                    if stat.S_ISLNK(path_stat.st_mode):
                        raise _managed_output_symlink_error(destination, path)
                    _validate_managed_path_containment(
                        destination,
                        destination_absolute,
                        destination_real,
                        path,
                    )
                    if stat.S_ISDIR(path_stat.st_mode):
                        pending.append(path)
                    elif not stat.S_ISREG(path_stat.st_mode):
                        raise _invalid_managed_output_error(
                            destination,
                            path,
                            "it is neither a regular file nor a directory",
                        )
                    elif path_stat.st_nlink > 1:
                        raise _managed_output_hardlink_error(destination, path)
        except ConversionPreflightError:
            raise
        except OSError as error:
            raise _destination_io_error(
                destination,
                f"inspect managed output directory {directory!r} in",
                error,
            ) from error


def _managed_path_stat(
    destination: str,
    path: str,
) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _destination_io_error(
            destination,
            f"inspect managed output path {path!r} in",
            error,
        ) from error


def _validate_managed_path_containment(
    destination: str,
    destination_absolute: str,
    destination_real: str,
    path: str,
) -> None:
    path_absolute = os.path.abspath(path)
    path_real = os.path.realpath(path_absolute)
    if not _path_is_within(path_absolute, destination_absolute) or not _path_is_within(
        path_real,
        destination_real,
    ):
        raise ConversionPreflightError(
            "GM2GD-CONVERT-MANAGED-OUTPUT-ESCAPE",
            f"Refusing a managed output path outside the Godot destination: {path}",
            destination_path=destination,
            workaround=(
                "Remove redirected paths from GM2Godot-managed output locations, "
                "then retry conversion."
            ),
        )


def _path_is_within(path: str, directory: str) -> bool:
    try:
        return os.path.commonpath((path, directory)) == directory
    except ValueError:
        return False


def _managed_output_symlink_error(
    destination: str,
    path: str,
) -> ConversionPreflightError:
    return ConversionPreflightError(
        "GM2GD-CONVERT-MANAGED-OUTPUT-SYMLINK",
        f"Refusing to convert through a symbolic link in managed output: {path}",
        destination_path=destination,
        workaround=(
            "Remove symbolic links from GM2Godot-managed output locations or choose "
            "another destination."
        ),
    )


def _managed_output_hardlink_error(
    destination: str,
    path: str,
) -> ConversionPreflightError:
    return ConversionPreflightError(
        "GM2GD-CONVERT-MANAGED-OUTPUT-HARDLINK",
        f"Refusing to overwrite a multiply-linked managed output file: {path}",
        destination_path=destination,
        workaround=(
            "Replace hardlinked files in GM2Godot-managed output locations with "
            "independent copies, then retry conversion."
        ),
    )


def _invalid_managed_output_error(
    destination: str,
    path: str,
    reason: str,
) -> ConversionPreflightError:
    return ConversionPreflightError(
        "GM2GD-CONVERT-MANAGED-OUTPUT-INVALID",
        f"Refusing an invalid managed output path; {reason}: {path}",
        destination_path=destination,
        workaround=(
            "Move the conflicting managed output path aside or choose another destination."
        ),
    )


def _project_file_stat(
    destination: str,
    directory_fd: int | None,
) -> os.stat_result:
    try:
        if directory_fd is None:
            return os.lstat(os.path.join(destination, GODOT_PROJECT_FILENAME))
        return os.stat(
            GODOT_PROJECT_FILENAME,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        raise _invalid_project_file_error(
            destination,
            f"it could not be inspected ({error})",
        ) from error


def _read_project_file(destination: str, directory_fd: int | None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    project_fd = -1
    try:
        if directory_fd is None:
            project_fd = os.open(
                os.path.join(destination, GODOT_PROJECT_FILENAME),
                flags,
            )
        else:
            project_fd = os.open(GODOT_PROJECT_FILENAME, flags, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(project_fd).st_mode):
            raise _invalid_project_file_error(
                destination,
                "it is not a regular file",
            )
        chunks: list[bytes] = []
        while chunk := os.read(project_fd, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    except ConversionPreflightError:
        raise
    except OSError as error:
        raise _invalid_project_file_error(
            destination,
            f"it could not be read ({error})",
        ) from error
    finally:
        if project_fd >= 0:
            os.close(project_fd)


def _invalid_godot_project_reason(project_bytes: bytes) -> str | None:
    try:
        content = project_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "it is not valid UTF-8"

    delimiter_stack: list[str] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = _strip_godot_comment(raw_line)
        if line is None:
            return f"it has an unterminated string on line {line_number}"
        stripped = line.strip()
        if not stripped:
            continue

        if delimiter_stack:
            mismatch = _update_godot_delimiters(stripped, delimiter_stack)
            if mismatch is not None:
                return f"it has {mismatch} on line {line_number}"
            continue

        if re.fullmatch(r"\[[^\[\]\r\n]+\]", stripped):
            continue
        if "=" not in stripped:
            return f"it has an invalid setting on line {line_number}"

        key, raw_value = stripped.split("=", 1)
        value = raw_value.strip()
        if not key.strip() or not value:
            return f"it has an invalid setting on line {line_number}"
        if not _valid_godot_value_start(value):
            return f"it has an invalid value on line {line_number}"
        mismatch = _update_godot_delimiters(value, delimiter_stack)
        if mismatch is not None:
            return f"it has {mismatch} on line {line_number}"

    if delimiter_stack:
        return "it has an unterminated value"
    return None


def _strip_godot_comment(line: str) -> str | None:
    in_string = False
    escaped = False
    for index, character in enumerate(line):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character == ";":
            return line[:index]
    return None if in_string else line


def _valid_godot_value_start(value: str) -> bool:
    if value[0] in {'"', "&", "^", "[", "{", "+", "-", "."}:
        return True
    if value[0].isdigit():
        return True
    if value in {"true", "false", "null", "inf", "nan"}:
        return True
    return re.match(
        r"[A-Za-z_][A-Za-z0-9_.]*(?:\[[^\]]+\])?\s*\(",
        value,
    ) is not None


def _update_godot_delimiters(value: str, delimiter_stack: list[str]) -> str | None:
    closing_for = {"(": ")", "[": "]", "{": "}"}
    opening_for = {closing: opening for opening, closing in closing_for.items()}
    in_string = False
    escaped = False
    for character in value:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in closing_for:
            delimiter_stack.append(character)
        elif character in opening_for:
            if not delimiter_stack or delimiter_stack[-1] != opening_for[character]:
                return f"a mismatched {character!r} delimiter"
            delimiter_stack.pop()
    if in_string:
        return "an unterminated string"
    return None


def _invalid_project_file_error(
    destination: str,
    reason: str,
) -> ConversionPreflightError:
    project_path = os.path.join(destination, GODOT_PROJECT_FILENAME)
    return ConversionPreflightError(
        "GM2GD-CONVERT-PROJECT-FILE-INVALID",
        f"Godot destination contains an invalid {GODOT_PROJECT_FILENAME}; {reason}: {project_path}",
        destination_path=destination,
        workaround="Repair project.godot in Godot 4.7.1 or choose another destination.",
    )


def _create_project_file_exclusively(
    destination: str,
    directory_fd: int | None,
    project_bytes: bytes,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    project_fd = -1
    created = False
    try:
        if directory_fd is None:
            project_fd = os.open(
                os.path.join(destination, GODOT_PROJECT_FILENAME),
                flags,
                0o644,
            )
        else:
            project_fd = os.open(
                GODOT_PROJECT_FILENAME,
                flags,
                0o644,
                dir_fd=directory_fd,
            )
        created = True
        _write_project_bytes(project_fd, project_bytes)
        os.fsync(project_fd)
    except FileExistsError as error:
        raise ConversionPreflightError(
            "GM2GD-CONVERT-DESTINATION-CHANGED",
            f"Godot destination changed during preflight: {destination}",
            destination_path=destination,
            workaround="Inspect the destination, remove the conflicting change, then retry.",
        ) from error
    except BaseException:
        if created:
            try:
                if directory_fd is None:
                    os.unlink(os.path.join(destination, GODOT_PROJECT_FILENAME))
                else:
                    os.unlink(GODOT_PROJECT_FILENAME, dir_fd=directory_fd)
            except OSError:
                pass
        raise
    finally:
        if project_fd >= 0:
            os.close(project_fd)


def _write_project_bytes(project_fd: int, project_bytes: bytes) -> None:
    written = 0
    while written < len(project_bytes):
        byte_count = os.write(project_fd, project_bytes[written:])
        if byte_count <= 0:
            raise OSError("project.godot write made no progress")
        written += byte_count


def _initial_project_name(gm_project_path: str) -> str:
    manifest = load_gamemaker_project_manifest(gm_project_path)
    manifest_name = manifest.project_name.strip()
    if manifest_name:
        return manifest_name
    if manifest.yyp_path is not None:
        yyp_stem = os.path.splitext(os.path.basename(manifest.yyp_path))[0].strip()
        if yyp_stem:
            return yyp_stem
    return DEFAULT_GODOT_PROJECT_NAME


def _minimal_godot_project(project_name: str) -> str:
    quoted_name = format_godot_string(project_name)
    return (
        "; Engine configuration file.\n"
        "; It's best edited using the editor UI and not directly,\n"
        "; since the parameters that go here are not all obvious.\n"
        "\n"
        "config_version=5\n"
        "\n"
        "[application]\n"
        "\n"
        f"config/name={quoted_name}\n"
        'config/features=PackedStringArray("4.7")\n'
    )


def _destination_io_error(
    destination_path: str,
    operation: str,
    error: OSError,
) -> ConversionPreflightError:
    return ConversionPreflightError(
        "GM2GD-CONVERT-DESTINATION-IO",
        f"Could not {operation} Godot destination {destination_path}: {error}",
        destination_path=destination_path,
        workaround="Check the destination path and permissions, then retry conversion.",
    )


class GodotProjectFile:
    """Line-preserving helper for small `project.godot` setting updates."""

    def __init__(self, project_godot_path: str) -> None:
        self.project_godot_path = project_godot_path

    def set_main_scene(self, scene_path: str) -> bool:
        """Set [application] run/main_scene while preserving unrelated settings."""
        return self.set_setting("application", "run/main_scene", scene_path)

    def set_autoloads(self, autoloads: Iterable[tuple[str, str]]) -> bool:
        """Set managed [autoload] entries in deterministic order."""
        if not os.path.isfile(self.project_godot_path):
            return False

        with open(self.project_godot_path, "r", encoding="utf-8") as f:
            content = f.read()

        autoload_lines = tuple(
            (name, self._format_value(self._autoload_value(path)))
            for name, path in autoloads
        )
        updated = self._set_autoloads(content, autoload_lines)
        atomic_rewrite_text(self.project_godot_path, updated)

        return True

    def set_setting(self, section: str, key: str, value: Any) -> bool:
        if not os.path.isfile(self.project_godot_path):
            return False

        with open(self.project_godot_path, "r", encoding="utf-8") as f:
            content = f.read()

        updated = self._set_setting(content, section, key, self._format_value(value))
        atomic_rewrite_text(self.project_godot_path, updated)

        return True

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, str):
            return format_godot_string(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @classmethod
    def _set_setting(
        cls, content: str, section: str, key: str, formatted_value: str
    ) -> str:
        lines = content.splitlines(keepends=True)
        newline = cls._detect_newline(content)
        section_header = f"[{section}]"
        setting_line = f"{key}={formatted_value}"

        section_start = None
        section_end = len(lines)
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == section_header:
                section_start = index
                section_end = len(lines)
                continue
            if section_start is not None and cls._is_section_header(stripped):
                section_end = index
                break

        if section_start is None:
            return cls._append_section(content, section_header, setting_line, newline)

        key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        matching_indices = [
            index
            for index in range(section_start + 1, section_end)
            if key_pattern.match(lines[index])
        ]
        if matching_indices:
            first_index = matching_indices[0]
            first_line = lines[first_index]
            indent = first_line[:len(first_line) - len(first_line.lstrip())]
            lines[first_index] = (
                f"{indent}{setting_line}{cls._line_ending(first_line, newline)}"
            )
            for duplicate_index in reversed(matching_indices[1:]):
                del lines[duplicate_index]
            return "".join(lines)

        insert_at = cls._setting_insert_index(lines, section_start, section_end)
        if insert_at > 0 and not cls._ends_with_newline(lines[insert_at - 1]):
            lines[insert_at - 1] = lines[insert_at - 1] + newline
        lines.insert(insert_at, setting_line + newline)
        return "".join(lines)

    @classmethod
    def _set_autoloads(
        cls,
        content: str,
        autoloads: tuple[tuple[str, str], ...],
    ) -> str:
        managed_names = {name for name, _value in autoloads}
        setting_lines = [
            f"{name}={formatted_value}"
            for name, formatted_value in autoloads
        ]
        lines = content.splitlines(keepends=True)
        newline = cls._detect_newline(content)
        section_header = "[autoload]"

        section_start = None
        section_end = len(lines)
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == section_header:
                section_start = index
                section_end = len(lines)
                continue
            if section_start is not None and cls._is_section_header(stripped):
                section_end = index
                break

        if section_start is None:
            return cls._append_section(content, section_header, "\n".join(setting_lines), newline)

        managed_pattern = re.compile(
            r"^\s*(?:" + "|".join(re.escape(name) for name in managed_names) + r")\s*="
        )
        preserved_body: list[str] = []
        for line in lines[section_start + 1:section_end]:
            if managed_pattern.match(line):
                continue
            preserved_body.append(line)

        managed_body = [line + newline for line in setting_lines]
        lines[section_start + 1:section_end] = managed_body + preserved_body
        return "".join(lines)

    @staticmethod
    def _append_section(
        content: str, section_header: str, setting_line: str, newline: str
    ) -> str:
        if not content:
            return f"{section_header}{newline}{setting_line}{newline}"

        separator = "" if content.endswith(("\n", "\r")) else newline
        return f"{content}{separator}{newline}{section_header}{newline}{setting_line}{newline}"

    @staticmethod
    def _autoload_value(path: str) -> str:
        return path if path.startswith("*") else "*" + path

    @staticmethod
    def _is_section_header(stripped_line: str) -> bool:
        return stripped_line.startswith("[") and stripped_line.endswith("]")

    @staticmethod
    def _detect_newline(content: str) -> str:
        return "\r\n" if "\r\n" in content else "\n"

    @staticmethod
    def _line_ending(line: str, default_newline: str) -> str:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
        return default_newline

    @staticmethod
    def _ends_with_newline(line: str) -> bool:
        return line.endswith(("\n", "\r"))

    @staticmethod
    def _setting_insert_index(
        lines: list[str], section_start: int, section_end: int
    ) -> int:
        insert_at = section_end
        while insert_at > section_start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        return insert_at


def atomic_rewrite_text(path: str, content: str) -> None:
    """Atomically replace an existing UTF-8 text file without changing its mode."""
    original_stat = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(original_stat.st_mode):
        raise OSError(f"Refusing to rewrite non-regular file: {path}")

    directory = os.path.dirname(path) or os.curdir
    basename = os.path.basename(path)
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=directory,
        prefix=f".{basename}.",
        suffix=".tmp",
    )
    temporary_pending = True
    try:
        os.chmod(temporary_path, stat.S_IMODE(original_stat.st_mode))
        temporary_file = os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="",
        )
        file_descriptor = -1
        with temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        temporary_pending = False
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
