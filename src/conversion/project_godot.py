import os
from collections.abc import Iterable
from typing import Any


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
        with open(self.project_godot_path, "w", encoding="utf-8") as f:
            f.write(updated)

        return True

    def set_setting(self, section: str, key: str, value: Any) -> bool:
        if not os.path.isfile(self.project_godot_path):
            return False

        with open(self.project_godot_path, "r", encoding="utf-8") as f:
            content = f.read()

        updated = self._set_setting(content, section, key, self._format_value(value))
        with open(self.project_godot_path, "w", encoding="utf-8") as f:
            f.write(updated)

        return True

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
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

        for index in range(section_start + 1, section_end):
            line = lines[index]
            stripped = line.lstrip()
            if stripped.startswith(f"{key}="):
                indent = line[:len(line) - len(stripped)]
                lines[index] = f"{indent}{setting_line}{cls._line_ending(line, newline)}"
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

        preserved_body: list[str] = []
        for line in lines[section_start + 1:section_end]:
            stripped = line.lstrip()
            if any(stripped.startswith(f"{name}=") for name in managed_names):
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
