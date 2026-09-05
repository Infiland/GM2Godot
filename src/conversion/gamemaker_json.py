"""Read GameMaker JSON while retaining its established decoding behavior."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from src.conversion.json_values import JsonValue, validate_json_value
from src.conversion.type_defs import StrPath


@dataclass(frozen=True)
class GameMakerJsonDocument:
    source_path: str
    source: str
    value: JsonValue


def parse_gamemaker_json(source: str, *, source_path: str = "") -> GameMakerJsonDocument:
    """Decode and validate while preserving original text and legacy comma rules."""
    cleaned = re.sub(r",\s*([}\]])", r"\1", source)
    value: object = json.loads(cleaned)
    return GameMakerJsonDocument(source_path, source, validate_json_value(value))


def read_gamemaker_json(path: StrPath) -> GameMakerJsonDocument:
    """Read a caller-selected path; source containment remains the caller's job."""
    with open(path, "r", encoding="utf-8") as source_file:
        source = source_file.read()
    return parse_gamemaker_json(source, source_path=os.fspath(path))
