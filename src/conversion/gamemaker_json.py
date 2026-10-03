"""Decode GameMaker metadata while retaining its original source text."""

import json
import re
from dataclasses import dataclass

from src.conversion.json_values import JsonValue, validate_json_value


@dataclass(frozen=True)
class GameMakerJsonDocument:
    source_path: str
    source_text: str
    value: JsonValue


def decode_gamemaker_json(source: str, *, source_path: str) -> GameMakerJsonDocument:
    """Preserve the existing trailing-comma rewrite and stdlib decoder policy."""
    value: object = json.loads(re.sub(r",\s*([}\]])", r"\1", source))
    return GameMakerJsonDocument(
        source_path=source_path,
        source_text=source,
        value=validate_json_value(value, source_path=source_path),
    )


def read_gamemaker_json(path: str) -> GameMakerJsonDocument:
    """Read UTF-8 metadata; callers own containment and exception handling."""
    with open(path, "r", encoding="utf-8") as source_file:
        source = source_file.read()
    return decode_gamemaker_json(source, source_path=path)
