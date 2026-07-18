from __future__ import annotations

import json
import math
import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TypedDict, cast

# Import localization manager
from src.localization import get_localized
from src.conversion.asset_output_paths import build_asset_output_paths, resource_filesystem_path
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.generated_paths import generated_path_segment, generated_resource_stem, generated_subfolder_path
from src.conversion.project_manifest import (
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
from src.conversion.project_godot import format_godot_string
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    validate_project_resource_source_path,
)
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath


class SoundData(TypedDict):
    name: str
    soundFile: str
    volume: float
    type: int
    bitDepth: int
    bitRate: int
    sampleRate: int
    compression: int
    preload: bool
    audioGroupId: str
    duration: float


class SoundResult(TypedDict):
    success: bool
    name: str
    audio_group: str


@dataclass(frozen=True)
class _DeclaredSoundResource:
    outcome_key: str
    name: str
    source_path: str | None
    owner_source_path: str
    manifest_field: str | None


class SoundConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False, max_workers: int | None = None,
                 organize_by_audio_group: bool = False,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_sounds_path = os.path.join(self.godot_project_path, 'sounds')
        self.organize_by_audio_group = bool(organize_by_audio_group)
        self._sound_output_paths: dict[str, str] = {}

    def _declared_sound_resources(
        self,
    ) -> tuple[_DeclaredSoundResource, ...] | None:
        """Return sounds selected by a valid YYP, including rejected paths."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="sound",
        )
        if manifest.yyp_path is None or any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        ):
            return None

        declared: dict[tuple[str, str], _DeclaredSoundResource] = {}
        for resource in manifest.find_resources(kind="sounds"):
            if not resource.name:
                continue
            manifest_field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            # A single GameMaker sound can appear more than once in a YYP. The
            # normalized source path is its stable base-resource identity.
            identity = ("path", resource.path)
            declared.setdefault(
                identity,
                _DeclaredSoundResource(
                    outcome_key=resource.path,
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path,
                    manifest_field=manifest_field,
                ),
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_sound(diagnostic)
            ):
                continue
            identity = ("rejected", diagnostic.resource)
            declared.setdefault(
                identity,
                _DeclaredSoundResource(
                    outcome_key=diagnostic.resource,
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        diagnostic.source.path
                        if diagnostic.source is not None
                        else manifest.yyp_path
                    ),
                    manifest_field=(
                        diagnostic.source.field_path
                        if diagnostic.source is not None
                        else None
                    ),
                ),
            )

        return tuple(declared.values())

    @staticmethod
    def _manifest_diagnostic_is_sound(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "sounds"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold() in {"sound", "gmsound"}
        )

    def _report_unavailable_declared_sound(
        self,
        resource: _DeclaredSoundResource,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker sound "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-SOUND-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="sound",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker sound .yy metadata inside "
                    "the project root or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _resolve_declared_sound_resource(
        self,
        resource: _DeclaredSoundResource,
    ) -> str | None:
        if resource.source_path is None:
            self._report_unavailable_declared_sound(
                resource,
                reason="its manifest source path was rejected",
            )
            return None

        resolved = self._resolve_project_source(
            resource.source_path,
            owner_source_path=resource.owner_source_path,
            resource=resource.name,
            resource_type="sound",
            field=resource.manifest_field,
        )
        if resolved is None:
            self._report_unavailable_declared_sound(
                resource,
                reason="its manifest source path is unavailable",
            )
            return None
        try:
            validate_project_resource_source_path(resolved, "sounds")
        except ProjectSourcePathError as exc:
            self._report_source_path_rejection(
                resource.source_path,
                exc,
                owner_source_path=resource.owner_source_path,
                resource=resource.name,
                resource_type="sound",
                field=resource.manifest_field,
            )
            self._report_unavailable_declared_sound(
                resource,
                reason="its manifest source path is outside the sounds resource family",
            )
            return None
        if not os.path.isfile(resolved.filesystem_path):
            self._report_unavailable_declared_sound(
                resource,
                reason=f"metadata is missing at {resolved.source_path!r}",
            )
            return None
        return resolved.filesystem_path

    def _find_disk_sound_files(self) -> list[str]:

        sound_folder = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, 'sounds'),
            resource_type="sound",
            field="sounds directory",
        )
        if sound_folder is None:
            return []

        sound_files: list[str] = []
        pending_directories = [sound_folder]
        visited_directories: set[str] = set()
        while pending_directories:
            directory = pending_directories.pop()
            resolved_directory = self._resolve_discovered_project_source(
                directory.filesystem_path,
                owner_source_path=directory.source_path,
                resource=os.path.basename(directory.source_path),
                resource_type="sound",
                field="discovered sound directory",
            )
            if resolved_directory is None or not os.path.isdir(
                resolved_directory.filesystem_path
            ):
                continue

            canonical_directory = os.path.normcase(
                os.path.realpath(resolved_directory.filesystem_path)
            )
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)

            child_directories: list[ResolvedProjectSourcePath] = []
            try:
                with os.scandir(resolved_directory.filesystem_path) as entries:
                    for entry in sorted(entries, key=lambda item: item.name):
                        filename = entry.name
                        lower_filename = filename.casefold()
                        is_sound_yy = (
                            lower_filename.endswith('.yy')
                            and not lower_filename.endswith('.old.yy')
                        )
                        try:
                            is_unlinked_directory = entry.is_dir(
                                follow_symlinks=False
                            )
                            is_symlink = entry.is_symlink()
                        except OSError:
                            continue
                        if not is_sound_yy and not is_unlinked_directory and not is_symlink:
                            continue

                        resolved_entry = self._resolve_discovered_project_source(
                            entry.path,
                            owner_source_path=resolved_directory.source_path,
                            resource=(
                                os.path.splitext(filename)[0]
                                if is_sound_yy
                                else filename
                            ),
                            resource_type="sound",
                            field=(
                                "discovered .yy"
                                if is_sound_yy
                                else "discovered sound entry"
                            ),
                        )
                        if resolved_entry is None:
                            continue

                        if os.path.isdir(resolved_entry.filesystem_path):
                            # Preserve os.walk's historical behavior for contained
                            # directory links while still rejecting escaping links.
                            if not is_symlink:
                                child_directories.append(resolved_entry)
                            continue
                        if is_sound_yy and os.path.isfile(
                            resolved_entry.filesystem_path
                        ):
                            try:
                                validate_project_resource_source_path(
                                    resolved_entry,
                                    "sounds",
                                )
                            except ProjectSourcePathError as exc:
                                self._report_source_path_rejection(
                                    entry.path,
                                    exc,
                                    owner_source_path=resolved_directory.source_path,
                                    resource=os.path.splitext(filename)[0],
                                    resource_type="sound",
                                    field="discovered .yy",
                                )
                                continue
                            sound_files.append(resolved_entry.filesystem_path)
            except OSError:
                continue
            pending_directories.extend(reversed(child_directories))
        return sorted(sound_files)

    def find_sound_files(self) -> list[str]:
        declared_resources = self._declared_sound_resources()
        if declared_resources is None:
            return self._find_disk_sound_files()
        return [
            yy_path
            for resource in declared_resources
            if (yy_path := self._resolve_declared_sound_resource(resource))
            is not None
        ]

    def _parse_sound_yy(self, yy_path: str) -> SoundData | None:
        data = self._read_yy_file(yy_path)
        if data is None:
            self._safe_log(get_localized("Console_Convertor_Sounds_ParseError").format(yy_path=yy_path))
            return None

        raw_sound_file = data.get('soundFile')
        if not isinstance(raw_sound_file, str) or not raw_sound_file:
            raw_name = data.get('name')
            sound_name = (
                raw_name
                if isinstance(raw_name, str) and raw_name
                else os.path.splitext(os.path.basename(yy_path))[0]
            )
            rejected_value = (
                raw_sound_file
                if isinstance(raw_sound_file, str)
                else repr(raw_sound_file)
            )
            self._report_source_path_rejection(
                rejected_value,
                ProjectSourcePathError(
                    "GameMaker soundFile must be a non-empty string: "
                    f"{raw_sound_file!r}"
                ),
                owner_source_path=yy_path,
                resource=sound_name,
                resource_type="sound",
                field="soundFile",
            )
            return None

        try:
            return {
                'name': str(data['name']),
                'soundFile': raw_sound_file,
                'volume': float(data.get('volume', 1.0)),
                'type': int(data.get('type', 0)),
                'bitDepth': int(data.get('bitDepth', 16)),
                'bitRate': int(data.get('bitRate', 128)),
                'sampleRate': int(data.get('sampleRate', 44100)),
                'compression': int(data.get('compression', 0)),
                'preload': bool(data.get('preload', True)),
                'audioGroupId': str(cast(JsonDict, data.get('audioGroupId', {})).get('name', 'audiogroup_default')),
                'duration': float(data.get('duration', 0.0)),
            }
        except (KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Sounds_ParseError").format(yy_path=yy_path))
            return None

    @staticmethod
    def _volume_to_db(volume: float) -> float:
        if volume <= 0.0:
            return -80.0
        return 20.0 * math.log10(volume)

    def _build_output_paths(self, sound_name: str, subfolder: str, audio_group: str) -> tuple[str, str]:
        output_parts: list[str] = []

        if self.organize_by_audio_group:
            output_parts.append(generated_path_segment(audio_group or 'audiogroup_default', 'audiogroup_default'))

        safe_subfolder = generated_subfolder_path(subfolder)
        if safe_subfolder:
            output_parts.extend(part for part in safe_subfolder.split('/') if part)

        output_parts.append(generated_resource_stem(sound_name))

        output_dir = os.path.join(self.godot_sounds_path, *output_parts)
        res_subfolder = '/'.join(output_parts)
        return output_dir, res_subfolder

    def _write_audio_group_map(self, audio_group_map: dict[str, str]) -> None:
        map_path = os.path.join(self.godot_sounds_path, 'audio_group_map.json')
        ordered_map = {name: audio_group_map[name] for name in sorted(audio_group_map)}
        payload = {
            'format_version': 1,
            'sounds': ordered_map,
        }

        with open(map_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.write('\n')

        if not self.compact_logging:
            self._safe_log(get_localized("Console_Convertor_Sounds_MapGenerated").format(
                map_path='sounds/audio_group_map.json', sounds_num=len(ordered_map)))

    def _generate_import_file(self, sound_file: str, subfolder: str = "") -> str | None:
        ext = os.path.splitext(sound_file)[1].lower()

        if subfolder:
            res_path = f"res://sounds/{subfolder}/{sound_file}"
        else:
            res_path = f"res://sounds/{sound_file}"

        if ext == '.wav':
            return (
                f'[remap]\n'
                f'importer="wav"\n'
                f'type="AudioStreamWAV"\n'
                f'uid=""\n'
                f'path=""\n'
                f'\n'
                f'[deps]\n'
                f'source_file={format_godot_string(res_path)}\n'
                f'dest_files=[]\n'
                f'\n'
                f'[params]\n'
                f'force/8_bit=false\n'
                f'force/mono=false\n'
                f'force/max_rate=false\n'
                f'force/max_rate_hz=44100\n'
                f'edit/trim=false\n'
                f'edit/normalize=false\n'
                f'edit/loop_mode=0\n'
                f'edit/loop_begin=0\n'
                f'edit/loop_end=-1\n'
                f'compress/mode=0\n'
            )
        elif ext == '.mp3':
            return (
                f'[remap]\n'
                f'importer="mp3"\n'
                f'type="AudioStreamMP3"\n'
                f'uid=""\n'
                f'path=""\n'
                f'\n'
                f'[deps]\n'
                f'source_file={format_godot_string(res_path)}\n'
                f'dest_files=[]\n'
                f'\n'
                f'[params]\n'
                f'loop=false\n'
                f'loop_offset=0.0\n'
                f'bpm=0.0\n'
                f'beat_count=0\n'
                f'bar_beats=4\n'
            )
        elif ext == '.ogg':
            return (
                f'[remap]\n'
                f'importer="oggvorbisstr"\n'
                f'type="AudioStreamOggVorbis"\n'
                f'uid=""\n'
                f'path=""\n'
                f'\n'
                f'[deps]\n'
                f'source_file={format_godot_string(res_path)}\n'
                f'dest_files=[]\n'
                f'\n'
                f'[params]\n'
                f'loop=false\n'
                f'loop_offset=0.0\n'
                f'bpm=0.0\n'
                f'beat_count=0\n'
                f'bar_beats=4\n'
            )
        return None

    def _process_sound(self, yy_path: str) -> SoundResult | None:
        if not self.conversion_running():
            return None

        discovered_name = os.path.splitext(os.path.basename(yy_path))[0]
        resolved_yy = self._resolve_discovered_project_source(
            yy_path,
            owner_source_path=yy_path,
            resource=discovered_name,
            resource_type="sound",
            field="sound .yy",
        )
        if resolved_yy is None:
            return {
                'success': False,
                'name': discovered_name,
                'audio_group': 'audiogroup_default',
            }
        try:
            validate_project_resource_source_path(resolved_yy, "sounds")
        except ProjectSourcePathError as exc:
            self._report_source_path_rejection(
                yy_path,
                exc,
                owner_source_path=yy_path,
                resource=discovered_name,
                resource_type="sound",
                field="sound .yy",
            )
            return {
                'success': False,
                'name': discovered_name,
                'audio_group': 'audiogroup_default',
            }

        sound_data = self._parse_sound_yy(resolved_yy.filesystem_path)
        if sound_data is None:
            return {
                'success': False,
                'name': discovered_name,
                'audio_group': 'audiogroup_default',
            }

        sound_name = sound_data['name']
        sound_file_reference = sound_data['soundFile']
        audio_group = sound_data['audioGroupId'] or 'audiogroup_default'

        if not sound_file_reference:
            self._safe_log(get_localized("Console_Convertor_Sounds_NoFile").format(name=sound_name))
            return {'success': False, 'name': sound_name, 'audio_group': audio_group}

        resolved_audio = self._resolve_project_source(
            sound_file_reference,
            owner_source_path=resolved_yy.source_path,
            resource=sound_name,
            resource_type="sound",
            field="soundFile",
        )
        if resolved_audio is None:
            return {'success': False, 'name': sound_name, 'audio_group': audio_group}

        audio_path = resolved_audio.filesystem_path
        if not os.path.isfile(audio_path):
            self._safe_log(get_localized("Console_Convertor_Sounds_FileMissing").format(
                name=sound_name, sound_file=sound_file_reference))
            return {'success': False, 'name': sound_name, 'audio_group': audio_group}

        sound_file = os.path.basename(audio_path)
        resource_path = self._sound_output_paths.get(sound_name, "")
        if resource_path:
            dest_path = resource_filesystem_path(self.godot_project_path, resource_path)
            output_dir = os.path.dirname(dest_path)
            resource_relative = resource_path.removeprefix("res://sounds/")
            res_subfolder = os.path.dirname(resource_relative).replace("\\", "/")
            sound_file = os.path.basename(dest_path)
        else:
            subfolder = self._get_subfolder_from_yy(resolved_yy.filesystem_path)
            output_dir, res_subfolder = self._build_output_paths(sound_name, subfolder, audio_group)
            dest_path = os.path.join(output_dir, sound_file)
        os.makedirs(output_dir, exist_ok=True)

        shutil.copy2(audio_path, dest_path)

        import_content = self._generate_import_file(sound_file, res_subfolder)
        if import_content is not None:
            import_path = dest_path + '.import'
            with open(import_path, 'w', encoding='utf-8') as f:
                f.write(import_content)

        if not self.compact_logging:
            self._safe_log(get_localized("Console_Convertor_Sounds_Converted").format(
                name=sound_name, sound_file=sound_file))

            if sound_data['volume'] != 1.0:
                volume_db = self._volume_to_db(sound_data['volume'])
                self._safe_log(get_localized("Console_Convertor_Sounds_VolumeNote").format(
                    name=sound_name, volume=sound_data['volume'],
                    volume_db=f"{volume_db:.1f}"))

            if audio_group != 'audiogroup_default':
                self._safe_log(get_localized("Console_Convertor_Sounds_BusNote").format(
                    name=sound_name, bus_name=audio_group))

        return {'success': True, 'name': sound_name, 'audio_group': audio_group}

    def _process_sound_with_outcome(
        self,
        yy_path: str,
        outcome_key: str,
    ) -> SoundResult | None:
        """Run one logical sound conversion while preserving the legacy result."""
        if not self.conversion_running():
            return None
        self._resource_started(outcome_key)
        try:
            result = self._process_sound(yy_path)
        except Exception:
            self._resource_failed(outcome_key)
            raise
        if result is None:
            self._resource_skipped(outcome_key)
        elif not result["success"]:
            self._resource_failed(outcome_key)
        return result

    def convert_sounds(self) -> None:
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_sounds_path, exist_ok=True)

        declared_resources = self._declared_sound_resources()
        if declared_resources is None:
            sound_files = list(dict.fromkeys(self._find_disk_sound_files()))
            sound_work = [(sound_file, sound_file) for sound_file in sound_files]
            for sound_file in sound_files:
                self._resource_requested(sound_file)
        else:
            for resource in declared_resources:
                self._resource_requested(resource.outcome_key)
            if not self.conversion_running():
                self.log_callback(get_localized("Console_Convertor_Sounds_Stopped"))
                return
            sound_work: list[tuple[str, str]] = []
            for resource in declared_resources:
                yy_path = self._resolve_declared_sound_resource(resource)
                if yy_path is None:
                    self._resource_skipped(resource.outcome_key)
                    continue
                sound_work.append((yy_path, resource.outcome_key))
            sound_files = [yy_path for yy_path, _outcome_key in sound_work]

        if not sound_files:
            self.log_callback(get_localized("Console_Convertor_Sounds_Error_NotFound"))
            return

        self._sound_output_paths = build_asset_output_paths(
            self.gm_project_path,
            self.godot_project_path,
            conversion_running=self.conversion_running,
            organize_sounds_by_audio_group=self.organize_by_audio_group,
        ).get("sounds", {})

        total_sounds = len(sound_files)
        processed_sounds = 0
        audio_group_map: dict[str, str] = {}
        successful_outcome_keys: set[str] = set()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[SoundResult | None], tuple[str, str]] = {
                executor.submit(
                    self._process_sound_with_outcome,
                    sound_file,
                    outcome_key,
                ): (sound_file, outcome_key)
                for sound_file, outcome_key in sound_work
            }
            for future in as_completed(futures_map):
                _sound_file, outcome_key = futures_map[future]
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Sounds_Stopped"))
                    return

                processed_sounds += 1

                if result['success']:
                    successful_outcome_keys.add(outcome_key)
                    audio_group_map[result['name']] = result['audio_group']
                    if self.compact_logging:
                        self._safe_log_progress(result['name'], processed_sounds, total_sounds)

                self._safe_progress(int(processed_sounds / total_sounds * 100))

        if not self.conversion_running():
            self.log_callback(get_localized("Console_Convertor_Sounds_Stopped"))
            return

        self._write_audio_group_map(audio_group_map)
        for outcome_key in sorted(successful_outcome_keys):
            self._resource_completed(outcome_key)

        self.log_callback(get_localized("Console_Convertor_Sounds_Complete"))

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_sounds()
