"""Pure parent metadata preserving the virtual reader's lookup behavior."""

from dataclasses import dataclass, field

from src.conversion.json_values import JsonObject


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True)
class GameMakerResourceParentMetadata:
    parent_path: str = ""
    raw_data: JsonObject = field(default_factory=_empty_json_object)
    has_parent_path: bool = False


def parse_gamemaker_resource_parent_metadata(data: JsonObject) -> GameMakerResourceParentMetadata:
    """Capture parent.path without coercing or validating a virtual reader's data."""
    parent_path = ""
    has_parent_path = False
    raw_parent = data.get("parent")
    if isinstance(raw_parent, dict):
        raw_path = raw_parent.get("path")
        if isinstance(raw_path, str):
            parent_path = raw_path
            has_parent_path = True
    return GameMakerResourceParentMetadata(parent_path=parent_path, raw_data=data, has_parent_path=has_parent_path)
