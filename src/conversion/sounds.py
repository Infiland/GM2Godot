from __future__ import annotations

import json
import math
import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TypedDict, cast

# Import localization manager
from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.generated_paths import generated_path_segment, generated_resource_stem, generated_subfolder_path
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

class SoundConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False, max_workers: int | None = None,
                 organize_by_audio_group: bool = False) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_sounds_path = os.path.join(self.godot_project_path, 'sounds')
        self.organize_by_audio_group = bool(organize_by_audio_group)

    def find_sound_files(self) -> list[str]:
        sound_folder = os.path.join(self.gm_project_path, 'sounds')
        sound_files: list[str] = []
        for root, _, files in os.walk(sound_folder):
            sound_files.extend(
                os.path.join(root, file)
                for file in files
                if file.lower().endswith('.yy') and not file.lower().endswith('.old.yy')
            )
        return sound_files

    def _parse_sound_yy(self, yy_path: str) -> SoundData | None:
        data = self._read_yy_file(yy_path)
        if data is None:
            self._safe_log(get_localized("Console_Convertor_Sounds_ParseError").format(yy_path=yy_path))
            return None

        try:
            return {
                'name': str(data['name']),
                'soundFile': str(data.get('soundFile', '')),
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
                f'source_file="{res_path}"\n'
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
                f'source_file="{res_path}"\n'
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
                f'source_file="{res_path}"\n'
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

        sound_data = self._parse_sound_yy(yy_path)
        if sound_data is None:
            sound_name = os.path.splitext(os.path.basename(yy_path))[0]
            return {'success': False, 'name': sound_name, 'audio_group': 'audiogroup_default'}

        sound_name = sound_data['name']
        sound_file = sound_data['soundFile']
        audio_group = sound_data['audioGroupId'] or 'audiogroup_default'

        if not sound_file:
            self._safe_log(get_localized("Console_Convertor_Sounds_NoFile").format(name=sound_name))
            return {'success': False, 'name': sound_name, 'audio_group': audio_group}

        audio_path = os.path.join(os.path.dirname(yy_path), sound_file)
        if not os.path.isfile(audio_path):
            self._safe_log(get_localized("Console_Convertor_Sounds_FileMissing").format(
                name=sound_name, sound_file=sound_file))
            return {'success': False, 'name': sound_name, 'audio_group': audio_group}

        subfolder = self._get_subfolder_from_yy(yy_path)
        output_dir, res_subfolder = self._build_output_paths(sound_name, subfolder, audio_group)
        os.makedirs(output_dir, exist_ok=True)

        dest_path = os.path.join(output_dir, sound_file)
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

    def convert_sounds(self) -> None:
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_sounds_path, exist_ok=True)

        gm_sounds_path = os.path.join(self.gm_project_path, 'sounds')

        if not os.path.exists(gm_sounds_path):
            self.log_callback(get_localized("Console_Convertor_Sounds_Error_NotFound"))
            return

        sound_files = sorted(self.find_sound_files())

        if not sound_files:
            self.log_callback(get_localized("Console_Convertor_Sounds_Error_NotFound"))
            return

        total_sounds = len(sound_files)
        processed_sounds = 0
        audio_group_map: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[SoundResult | None], str] = {executor.submit(self._process_sound, sf): sf for sf in sound_files}
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Sounds_Stopped"))
                    return

                processed_sounds += 1

                if result['success']:
                    audio_group_map[result['name']] = result['audio_group']
                    if self.compact_logging:
                        self._safe_log_progress(result['name'], processed_sounds, total_sounds)

                self._safe_progress(int(processed_sounds / total_sounds * 100))

        self._write_audio_group_map(audio_group_map)

        self.log_callback(get_localized("Console_Convertor_Sounds_Complete"))

    def convert_all(self) -> None:
        self.convert_sounds()
