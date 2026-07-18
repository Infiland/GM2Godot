import os
import shutil
import re
from PIL import Image
from typing import Optional, List

# Import localization manager
from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    load_gamemaker_project_manifest,
    unsupported_project_option_diagnostics,
)
from src.conversion.project_godot import GodotProjectFile, atomic_rewrite_text, format_godot_string
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback

class ProjectSettingsConverter(BaseConverter):
    def __init__(self, gm_project_path: str, godot_project_path: str,
                 log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 gm_platform: str = 'windows',
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None,
                 project_manifest: GameMakerProjectManifest | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path,
                         log_callback, progress_callback, conversion_running,
                         max_workers=max_workers, diagnostics=diagnostics)
        self.gm_platform = gm_platform
        self.project_manifest = project_manifest or load_gamemaker_project_manifest(
            self.gm_project_path,
            target_platform=gm_platform,
        )
        self.options_platform_path = os.path.join(self.gm_project_path, 'options', self.gm_platform, f'options_{self.gm_platform}.yy')
        self.options_windows_path = os.path.join(self.gm_project_path, 'options', 'windows', f'options_windows.yy')
        self.options_main_path = os.path.join(self.gm_project_path, 'options', 'main', 'options_main.yy')

    def convert_icon(self) -> bool:
        requested_icon_path = os.path.join(
            self.gm_project_path,
            'options',
            self.gm_platform,
            'icons',
        )
        gm_icon_path = self._resolve_icon_directory(
            requested_icon_path,
            self.gm_platform,
        )
        icon_platform = self.gm_platform
        godot_ico_path = os.path.join(self.godot_project_path, 'icon.ico')
        godot_png_path = os.path.join(self.godot_project_path, 'icon.png')

        if gm_icon_path is None:
            fallback_icon = self._find_fallback_icon_path()
            if fallback_icon is None:
                self.log_callback(get_localized("Console_Convertor_Icon_Error_DirectoryNotFound").format(
                    gm_icon_path=requested_icon_path))
                return False
            gm_icon_path, icon_platform = fallback_icon

        icon_files = self._contained_icon_files(gm_icon_path, icon_platform)

        if not (icon_files):
            self.log_callback(get_localized("Console_Convertor_Icon_Error_FileNotFound"))
            return False

        icon_name, source_icon = icon_files[0]
            
        try:
            shutil.copy2(source_icon, godot_ico_path)
            self.log_callback(get_localized("Console_Convertor_Icon_Copied").format(icon_files=icon_name))

            with Image.open(source_icon) as img:
                img.save(godot_png_path, 'PNG')
            self.log_callback(get_localized("Console_Convertor_Icon_Converted").format(icon_files=icon_name))

            project_godot_path = os.path.join(
                self.godot_project_path,
                "project.godot",
            )
            if os.path.isfile(project_godot_path):
                GodotProjectFile(project_godot_path).set_setting(
                    "application",
                    "config/icon",
                    "res://icon.png",
                )
        
            return True
        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_Error_IconGeneric").format(error=str(e)))
            return False

    def _find_fallback_icon_path(self) -> tuple[str, str] | None:
        """Search other platforms for an icon directory when the selected platform has none."""
        resolved_options = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, 'options'),
            resource_type="project_options",
            field="options directory",
        )
        if (
            resolved_options is None
            or not os.path.isdir(resolved_options.filesystem_path)
        ):
            return None

        for platform in sorted(os.listdir(resolved_options.filesystem_path)):
            if platform == self.gm_platform:
                continue
            candidate = self._resolve_icon_directory(
                os.path.join(
                    resolved_options.filesystem_path,
                    platform,
                    'icons',
                ),
                platform,
            )
            if candidate is not None and self._contained_icon_files(candidate, platform):
                self.log_callback(get_localized("Console_Convertor_Icon_Fallback").format(platform=platform))
                return candidate, platform

        return None

    def _resolve_icon_directory(
        self,
        icon_path: str,
        platform: str,
    ) -> str | None:
        resolved = self._resolve_discovered_project_source(
            icon_path,
            owner_source_path=f"options/{platform}",
            resource=platform,
            resource_type="project_options",
            field="icons directory",
        )
        if resolved is None or not os.path.isdir(resolved.filesystem_path):
            return None
        return resolved.filesystem_path

    def _contained_icon_files(
        self,
        icon_directory: str,
        platform: str,
    ) -> list[tuple[str, str]]:
        try:
            filenames = sorted(os.listdir(icon_directory))
        except OSError:
            return []
        icons: list[tuple[str, str]] = []
        for filename in filenames:
            if not filename.casefold().endswith((".ico", ".png")):
                continue
            resolved = self._resolve_discovered_project_source(
                os.path.join(icon_directory, filename),
                owner_source_path=f"options/{platform}/icons",
                resource=platform,
                resource_type="project_options",
                field="icon file",
            )
            if resolved is not None and os.path.isfile(resolved.filesystem_path):
                icons.append((filename, resolved.filesystem_path))
        return icons

    def get_gm_project_name(self) -> Optional[str]:
        if self.project_manifest.yyp_path is None:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNotFound"))
            return None
        if not self.project_manifest.project_name:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNameNotRead").format(error="missing %Name/name"))
            return None
        return self.project_manifest.project_name

    def get_gm_option(self, option_name: str, file_path: str) -> Optional[str]:
        option = self.project_manifest.get_option(
            option_name,
            self._platform_from_options_path(file_path),
        )
        if option is not None:
            return self._option_value_as_string(option.value)
        if not os.path.exists(file_path):
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNotFound"))
            return None
        return None

    def update_project_name(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback(get_localized("Console_Error_MissingGodotFile"))
            return

        try:
            gm_project_name = self.get_gm_project_name()
            if gm_project_name:
                updated = GodotProjectFile(project_godot_path).set_setting(
                    "application",
                    "config/name",
                    gm_project_name,
                )
                if updated:
                    self.log_callback(get_localized("Console_Convertor_Settings_UpdatedName").format(gm_project_name=gm_project_name))
            else:
                self.log_callback(get_localized("Console_Convertor_Settings_Error_Name_GM"))

        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_NameGeneric").format(error=str(e)))

    def update_project_settings(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback(get_localized("Console_Error_MissingGodotFile"))
            return

        try:
            with open(project_godot_path, 'r', encoding='utf-8') as file:
                content = file.read()

            for gm_option, platform, godot_section, godot_setting, value_kind in self._project_setting_mappings():
                option = self.project_manifest.get_option(gm_option, platform)
                if option is not None:
                    value = self._godot_project_setting_value(option.value, value_kind)
                    content = self.update_godot_setting(
                        content,
                        godot_setting,
                        value,
                        section=godot_section,
                        value_kind=value_kind,
                    )

            for diagnostic in unsupported_project_option_diagnostics(
                self.project_manifest,
                target_platform=self.gm_platform,
                supported_keys=self._supported_project_option_keys(),
            ):
                self._safe_log(f"{diagnostic.severity.title()}: {diagnostic.message}")

            atomic_rewrite_text(project_godot_path, content)

            self.log_callback(get_localized("Console_Convertor_Settings_Updated"))
            
        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_NotUpdated").format(error=str(e)))

    def update_godot_setting(
        self,
        content: str,
        setting: str,
        value: object,
        section: str = "application",
        value_kind: str | None = None,
    ) -> str:
        if section != "application":
            content = self._remove_godot_setting_from_section(
                content,
                setting,
                section="application",
            )

        new_setting = f'{setting}={self._format_godot_value(value, value_kind)}'
        section_span = self._godot_section_span(content, section)
        if section_span is None:
            line_ending = self._line_ending(content)
            separator = "" if not content or content.endswith(("\n", "\r")) else line_ending
            return (
                f"{content}{separator}{line_ending}[{section}]{line_ending}"
                f"{new_setting}{line_ending}"
            )

        body_start, body_end = section_span
        section_body = content[body_start:body_end]
        setting_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(setting)}[ \t]*=.*$",
        )
        if setting_pattern.search(section_body):
            updated_body = setting_pattern.sub(new_setting, section_body, count=1)
            return f"{content[:body_start]}{updated_body}{content[body_end:]}"

        line_ending = self._line_ending(content)
        return f"{content[:body_start]}{new_setting}{line_ending}{content[body_start:]}"

    def read_audio_groups(self) -> List[str]:
        if self.project_manifest.yyp_path is None:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNotFound"))
            return []
        audio_group_names = self.project_manifest.audio_group_names()
        if not audio_group_names:
            self.log_callback(get_localized("Console_Convertor_AudioBus_Error_SectionNotFound_GM"))
            return []
        self.log_callback(get_localized("Console_Convertor_AudioBus_Group_Found").format(audio_group_names=', '.join(audio_group_names)))
        return audio_group_names

    def _project_setting_mappings(self) -> list[tuple[str, str, str, str, str]]:
        return [
            ("option_windows_description_info", "windows", "application", "config/description", "string"),
            (f"option_{self.gm_platform}_version", self.gm_platform, "application", "config/version", "string"),
            ("option_windows_use_splash", "windows", "application", "boot_splash/show_image", "bool"),
            ("option_game_speed", "main", "application", "run/max_fps", "int"),
            (
                f"option_{self.gm_platform}_vsync",
                self.gm_platform,
                "display",
                "window/vsync/vsync_mode",
                "vsync",
            ),
            (
                f"option_{self.gm_platform}_sync",
                self.gm_platform,
                "display",
                "window/vsync/vsync_mode",
                "vsync",
            ),
            (
                f"option_{self.gm_platform}_resize_window",
                self.gm_platform,
                "display",
                "window/size/resizable",
                "bool",
            ),
            ("option_windows_borderless", "windows", "display", "window/size/borderless", "bool"),
            (
                f"option_{self.gm_platform}_interpolate_pixels",
                self.gm_platform,
                "rendering",
                "textures/canvas_textures/default_texture_filter",
                "texture_filter",
            ),
            (
                f"option_{self.gm_platform}_start_fullscreen",
                self.gm_platform,
                "display",
                "window/size/mode",
                "fullscreen",
            ),
        ]

    def _supported_project_option_keys(self) -> set[str]:
        return {
            key
            for key, _platform, _section, _setting, _kind in self._project_setting_mappings()
        }

    @staticmethod
    def _godot_section_span(content: str, section: str) -> tuple[int, int] | None:
        header = re.search(
            rf"(?m)^\[{re.escape(section)}\][ \t]*(?:\r?\n|$)",
            content,
        )
        if header is None:
            return None

        body_start = header.end()
        next_header = re.search(r"(?m)^\[[^\]\r\n]+\][ \t]*(?:\r?\n|$)", content[body_start:])
        body_end = body_start + next_header.start() if next_header is not None else len(content)
        return body_start, body_end

    @classmethod
    def _remove_godot_setting_from_section(
        cls,
        content: str,
        setting: str,
        *,
        section: str,
    ) -> str:
        section_span = cls._godot_section_span(content, section)
        if section_span is None:
            return content

        body_start, body_end = section_span
        section_body = content[body_start:body_end]
        setting_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(setting)}[ \t]*=.*(?:\r?\n|$)",
        )
        updated_body = setting_pattern.sub("", section_body)
        return f"{content[:body_start]}{updated_body}{content[body_end:]}"

    @staticmethod
    def _line_ending(content: str) -> str:
        return "\r\n" if "\r\n" in content else "\n"

    def _platform_from_options_path(self, file_path: str) -> str:
        options_root = os.path.join(self.gm_project_path, "options")
        try:
            relative = os.path.relpath(file_path, options_root)
        except ValueError:
            relative = os.path.basename(file_path)
        parts = relative.split(os.sep)
        if len(parts) > 1 and parts[0]:
            return parts[0]
        filename = os.path.splitext(os.path.basename(file_path))[0]
        if filename.startswith("options_"):
            return filename[len("options_"):]
        return "main"

    @staticmethod
    def _option_value_as_string(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _godot_project_setting_value(self, value: object, value_kind: str) -> object:
        if value_kind == "bool":
            return self._bool_option(value)
        if value_kind == "int":
            return self._int_option(value)
        if value_kind == "vsync":
            return 1 if self._bool_option(value) else 0
        if value_kind == "texture_filter":
            return 1 if self._bool_option(value) else 0
        if value_kind == "fullscreen":
            return 3 if self._bool_option(value) else 0
        return value

    @staticmethod
    def _bool_option(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value != 0
        return str(value).casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def _int_option(value: object) -> int:
        if isinstance(value, bool):
            return 1 if value else 0
        if not isinstance(value, (int, float, str)):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _format_godot_value(value: object, value_kind: str | None = None) -> str:
        if value_kind == "string":
            return format_godot_string(str(value))
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        value_text = str(value)
        lowered = value_text.casefold()
        if lowered in {"true", "false"}:
            return lowered
        if re.fullmatch(r"-?\d+(?:\.\d+)?", value_text):
            return value_text
        escaped = value_text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def generate_audio_bus_layout(self) -> None:
        audio_groups = self.read_audio_groups()
        bus_layout_path = os.path.join(self.godot_project_path, 'default_bus_layout.tres')

        try:
            with open(bus_layout_path, 'w', encoding='utf-8') as file:
                file.write('[gd_resource type="AudioBusLayout" format=3 uid="uid://cvoahc3k1xyrn"]\n\n')
                file.write('[resource]\n')
                
                for i, group in enumerate(audio_groups):
                    bus_name = "Master" if group == "audiogroup_default" else group
                    file.write(f'bus/{i}/name = "{bus_name}"\n')
                    file.write(f'bus/{i}/solo = false\n')
                    file.write(f'bus/{i}/mute = false\n')
                    file.write(f'bus/{i}/bypass_fx = false\n')
                    file.write(f'bus/{i}/volume_db = 0.0\n')
                    file.write(f'bus/{i}/send = "Master"\n')
                    if i < len(audio_groups) - 1:
                        file.write('\n')

                if "audiogroup_default" not in audio_groups and "Master" not in audio_groups:
                    i = len(audio_groups)
                    file.write(f'\nbus/{i}/name = "Master"\n')
                    file.write(f'bus/{i}/solo = false\n')
                    file.write(f'bus/{i}/mute = false\n')
                    file.write(f'bus/{i}/bypass_fx = false\n')
                    file.write(f'bus/{i}/volume_db = 0.0\n')
                    file.write(f'bus/{i}/send = "Master"\n')

            self.log_callback(get_localized("Console_Convertor_AudioBus_Group_Generated").format(audio_groups_num=len(audio_groups)))
            self.log_callback(f"Generated default_bus_layout.tres with {len(audio_groups)} audio buses.")
        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_AudioBus_Error_GroupNotGenerated").format(error=str(e)))

    def convert_all(self) -> None:
        self.convert_icon()
        self.update_project_name()
        self.update_project_settings()
        self.generate_audio_bus_layout()
