from __future__ import annotations

from typing import Callable, Mapping, TypeAlias

from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.scripts import ScriptConverter
from src.conversion.objects import ObjectConverter
from src.conversion.rooms import RoomConverter
from src.conversion.shaders import ShaderConverter
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.project_settings import ProjectSettingsConverter
from src.conversion.architecture_policy import write_architecture_policy_report
from src.conversion.conversion_context import (
    ConversionContext,
    RunningFlag,
    enabled_converter_keys,
    sound_group_folders_enabled,
)
from src.conversion.conversion_manifest import write_conversion_manifest
from src.conversion.conversion_plan import build_conversion_plan
from src.conversion.diagnostics import DiagnosticCollector, write_conversion_diagnostic_reports
from src.conversion.type_defs import BoolSetting, LogCallback, ProgressCallback

from src.localization import get_localized


CONVERSION_CATEGORIES: dict[str, list[str]] = {
    "assets": ["sprites", "fonts", "sounds", "sound_group_folders", "included_files", "scripts", "objects", "rooms", "asset_registry"],
    "project": ["game_icon", "project_name", "project_settings", "audio_buses", "notes"],
    "wip": ["shaders", "tilesets"],
}


ConverterFn: TypeAlias = Callable[[], object]


class Converter:
    def __init__(self, log_callback: LogCallback, progress_callback: ProgressCallback,
                 status_callback: LogCallback, conversion_running: RunningFlag,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None) -> None:
        self.log_callback: LogCallback = log_callback
        self.progress_callback: ProgressCallback = progress_callback
        self.status_callback: LogCallback = status_callback
        self.conversion_running = conversion_running
        self._raw_log_callback: LogCallback = log_callback
        self._raw_update_log_callback: LogCallback = update_log_callback or log_callback
        self.update_log_callback: LogCallback = self._raw_update_log_callback
        self.compact_logging = compact_logging
        self.max_workers = max_workers
        self.diagnostics = DiagnosticCollector()

    def convert(self, gm_path: str, gm_platform: str, godot_path: str,
                settings: Mapping[str, BoolSetting]) -> None:
        self.diagnostics = DiagnosticCollector()
        self.log_callback = self.diagnostics.wrap_log_callback(self._raw_log_callback)
        self.update_log_callback = self.diagnostics.wrap_log_callback(self._raw_update_log_callback)
        context = self._create_context(gm_path, gm_platform, godot_path, settings)
        runners = self._build_step_runners(context)
        plan = build_conversion_plan(context.enabled_converters)

        try:
            for step in plan:
                if not context.is_running():
                    break
                converter_fn = runners.get(step.key)
                if converter_fn is None:
                    continue
                log_message = get_localized(step.log_key)
                context.log_callback(log_message)
                context.status_callback(log_message)
                converter_fn()
                context.progress_callback(0)
        finally:
            write_conversion_diagnostic_reports(context.godot_project_path, context.diagnostics)
            write_architecture_policy_report(
                context.gm_project_path,
                context.godot_project_path,
                target_platform=context.target_platform,
                enabled_converters=context.enabled_converters,
            )
            write_conversion_manifest(
                context.gm_project_path,
                context.godot_project_path,
                target_platform=context.target_platform,
                enabled_converters=context.enabled_converters,
            )

    def _create_context(
        self,
        gm_path: str,
        gm_platform: str,
        godot_path: str,
        settings: Mapping[str, BoolSetting],
    ) -> ConversionContext:
        return ConversionContext(
            gm_project_path=gm_path,
            godot_project_path=godot_path,
            target_platform=gm_platform,
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            status_callback=self.status_callback,
            conversion_running=self.conversion_running.is_set,
            update_log_callback=self.update_log_callback,
            compact_logging=self.compact_logging,
            max_workers=self.max_workers,
            diagnostics=self.diagnostics,
            enabled_converters=enabled_converter_keys(settings),
            group_sounds_by_audio_group=sound_group_folders_enabled(settings),
        )

    def _build_step_runners(self, context: ConversionContext) -> dict[str, ConverterFn]:
        project_settings = ProjectSettingsConverter(
            context.gm_project_path,
            context.godot_project_path,
            context.log_callback,
            context.progress_callback,
            context.is_running,
            gm_platform=context.target_platform,
            max_workers=context.max_workers,
            diagnostics=context.diagnostics,
        )

        return {
            "game_icon": project_settings.convert_icon,
            "project_name": project_settings.update_project_name,
            "project_settings": project_settings.update_project_settings,
            "audio_buses": project_settings.generate_audio_bus_layout,
            "sprites": lambda: SpriteConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
            ).convert_all(),
            "fonts": lambda: FontConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
            ).convert_all(),
            "tilesets": lambda: TileSetConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
            ).convert_all(),
            "sounds": lambda: SoundConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
                organize_by_audio_group=context.group_sounds_by_audio_group,
            ).convert_all(),
            "notes": lambda: NoteConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
            ).convert_all(),
            "shaders": lambda: ShaderConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
            ).convert_all(),
            "included_files": lambda: IncludedFilesConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
            ).convert_all(),
            "scripts": lambda: ScriptConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
                diagnostics=context.diagnostics,
                macro_configuration=context.target_platform,
            ).convert_all(),
            "objects": lambda: ObjectConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
                diagnostics=context.diagnostics,
                macro_configuration=context.target_platform,
            ).convert_all(),
            "rooms": lambda: RoomConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
                diagnostics=context.diagnostics,
            ).convert_all(),
            "asset_registry": lambda: AssetRegistryConverter(
                context.gm_project_path,
                context.godot_project_path,
                context.log_callback,
                context.progress_callback,
                context.is_running,
                update_log_callback=context.update_log_callback,
                compact_logging=context.compact_logging,
                max_workers=context.max_workers,
                organize_sounds_by_audio_group=context.group_sounds_by_audio_group,
            ).convert_all(),
        }
