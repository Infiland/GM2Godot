from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.project_settings import ProjectSettingsConverter

import os
import shutil
import re
import json
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ConversionSettings:
    game_icon: bool = True
    project_name: bool = True
    project_settings: bool = True
    audio_buses: bool = True
    sprites: bool = True
    fonts: bool = True
    tilesets: bool = True
    sounds: bool = True
    notes: bool = True

class BaseConverter:
    def __init__(self, gm_path: str, godot_path: str, log_callback: Callable[[str], None], 
                 progress_callback: Callable[[int], None]):
        self.gm_path = Path(gm_path)
        self.godot_path = Path(godot_path)
        self.log = log_callback
        self.update_progress = progress_callback

    def ensure_output_dir(self, dir_path: Path) -> None:
        """Ensure output directory exists, create if necessary."""
        dir_path.mkdir(parents=True, exist_ok=True)

    def calculate_progress(self, current: int, total: int) -> None:
        """Calculate and update progress percentage."""
        if total > 0:
            progress = int((current / total) * 100)
            self.update_progress(progress)

class Converter:
    def __init__(self, log_callback: Callable[[str], None], 
                 progress_callback: Callable[[int], None]):
        self.log = log_callback
        self.update_progress = progress_callback
        self._conversion_running = True

    def stop_conversion(self) -> None:
        """Stop the ongoing conversion process."""
        self._conversion_running = False

    def is_running(self) -> bool:
        """Check if conversion should continue running."""
        return self._conversion_running
    
    def _load_converter(self, converter_type: str):
        """Dynamically import and load converter classes when needed."""
        match converter_type:
            case "project_settings":
                from src.conversion.project_settings import ProjectSettingsConverter
                return ProjectSettingsConverter
            case "sprites":
                from src.conversion.sprites import SpriteConverter
                return SpriteConverter
            case "sounds":
                from src.conversion.sounds import SoundConverter
                return SoundConverter
            case "fonts":
                from src.conversion.fonts import FontConverter
                return FontConverter
            case "notes":
                from src.conversion.notes import NoteConverter
                return NoteConverter
            case "tilesets":
                from src.conversion.tilesets import TileSetConverter
                return TileSetConverter
            case _:
                raise ValueError(f"Unknown converter type: {converter_type}")

    def convert(self, gm_path: str, godot_path: str, settings: Dict[str, bool]) -> None:
        """
        Convert GameMaker project to Godot project.
        
        Args:
            gm_path: Path to GameMaker project
            godot_path: Path to Godot project
            settings: Dictionary of conversion settings
        """
        try:
            self._validate_paths(gm_path, godot_path)
            
            ProjectSettingsConverter = self._load_converter("project_settings")
            project_settings_converter = ProjectSettingsConverter(
                gm_path, 
                self._detect_platform(gm_path),
                godot_path, 
                self.log
            )

            converters = [
                ("game_icon", project_settings_converter.convert_icon, "Converting game icon..."),
                ("project_name", project_settings_converter.update_project_name, "Updating project name..."),
                ("project_settings", project_settings_converter.update_project_settings, "Updating project settings..."),
                ("audio_buses", project_settings_converter.generate_audio_bus_layout, "Generating audio bus layout..."),
                ("sprites", lambda: self._convert_resource("sprites", gm_path, godot_path), "Converting sprites..."),
                ("fonts", lambda: self._convert_resource("fonts", gm_path, godot_path), "Converting fonts..."),
                ("tilesets", lambda: self._convert_resource("tilesets", gm_path, godot_path), "Converting tilesets..."),
                ("sounds", lambda: self._convert_resource("sounds", gm_path, godot_path), "Converting sounds..."),
                ("notes", lambda: self._convert_resource("notes", gm_path, godot_path), "Converting notes...")
            ]

            for setting_name, converter_func, log_message in converters:
                if settings.get(setting_name, False):
                    if not self.is_running():
                        self.log("Conversion stopped by user.")
                        return
                    
                    self.log(log_message)
                    try:
                        converter_func()
                    except Exception as e:
                        self.log(f"Error during {setting_name} conversion: {str(e)}")
                    finally:
                        self.update_progress(0)

            self.log("Conversion complete!")

        except Exception as e:
            self.log(f"Error during conversion: {str(e)}")
            raise

    def _validate_paths(self, gm_path: str, godot_path: str) -> None:
        """Validate input and output paths."""
        if not os.path.exists(gm_path):
            raise ValueError(f"GameMaker project path does not exist: {gm_path}")
        
        if not os.path.exists(godot_path):
            raise ValueError(f"Godot project path does not exist: {godot_path}")
        
        if not any(f.endswith('.yyp') for f in os.listdir(gm_path)):
            raise ValueError("No .yyp file found in GameMaker project directory")

    def _detect_platform(self, gm_path: str) -> str:
        """Detect the target platform from GameMaker project."""
        platforms = ['windows', 'mac', 'linux', 'android', 'ios']
        options_dir = os.path.join(gm_path, 'options')
        
        if not os.path.exists(options_dir):
            return 'windows'
            
        for platform in platforms:
            if os.path.exists(os.path.join(options_dir, platform)):
                return platform
                
        return 'windows'
    
    def _convert_sprites(self, gm_path: str, godot_path: str) -> None:
        """Convert sprites with error handling and progress tracking."""
        sprite_converter = SpriteConverter(
            gm_path, 
            godot_path, 
            self.log, 
            self.update_progress,
            self.is_running
        )
        sprite_converter.convert_all()

    def _convert_sounds(self, gm_path: str, godot_path: str) -> None:
        """Convert sounds with error handling and progress tracking."""
        sound_converter = SoundConverter(
            gm_path, 
            godot_path, 
            self.log, 
            self.update_progress,
            self.is_running
        )
        sound_converter.convert_sounds()

    def _convert_notes(self, gm_path: str, godot_path: str) -> None:
        """Convert notes with error handling and progress tracking."""
        note_converter = NoteConverter(
            gm_path, 
            godot_path, 
            self.log, 
            self.update_progress,
            self.is_running
        )
        note_converter.convert_all()

    def _convert_fonts(self, gm_path: str, godot_path: str) -> None:
        """Convert fonts with error handling."""
        # TODO: Implement font conversion
        self.log("Font conversion not yet implemented")

    def _convert_tilesets(self, gm_path: str, godot_path: str) -> None:
        """Convert tilesets with error handling."""
        # TODO: Implement tileset conversion
        self.log("Tileset conversion not yet implemented")