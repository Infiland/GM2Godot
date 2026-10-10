"""Audio container detection for GameMaker sound files.

GameMaker accepts sound files without an extension (the IDE stores what it
imported under the bare resource name). Godot picks its audio importer from the
file extension, so such files are given the extension of the container they
actually hold.
"""

from __future__ import annotations

import os

from src.conversion.type_defs import StrPath

GODOT_AUDIO_EXTENSIONS: tuple[str, ...] = (".wav", ".mp3", ".ogg")
_SNIFF_BYTES = 12


def detect_audio_extension(header: bytes) -> str | None:
    """Return the Godot audio extension for a file header, or None if unknown."""
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return ".wav"
    if header.startswith(b"OggS"):
        return ".ogg"
    if header.startswith(b"ID3"):
        return ".mp3"
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        # MPEG audio frame sync without an ID3 tag.
        return ".mp3"
    return None


def sniff_audio_extension(path: StrPath) -> str | None:
    try:
        with open(path, "rb") as audio_file:
            header = audio_file.read(_SNIFF_BYTES)
    except OSError:
        return None
    return detect_audio_extension(header)


def godot_audio_filename(source_path: StrPath) -> str:
    """Return the output filename Godot can import for a GameMaker sound file.

    Files that already carry a supported extension keep their name; files with
    no recognised extension get the extension of the container they hold.
    """
    filename = os.path.basename(os.fspath(source_path))
    if os.path.splitext(filename)[1].lower() in GODOT_AUDIO_EXTENSIONS:
        return filename
    detected_extension = sniff_audio_extension(source_path)
    if detected_extension is None:
        return filename
    return filename + detected_extension
