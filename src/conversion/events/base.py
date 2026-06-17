from dataclasses import dataclass
from typing import Callable, TypeAlias

from src.conversion.type_defs import JsonDict


EventKey: TypeAlias = tuple[int, int]
EventHandler: TypeAlias = Callable[[JsonDict, str], "EventMapping"]
StaticMappings: TypeAlias = dict[EventKey, "EventMapping"]
EventTypeHandlers: TypeAlias = dict[int, EventHandler]


@dataclass(frozen=True)
class EventMapping:
    """Metadata for mapping a GameMaker event to a Godot function.

    Attributes:
        godot_func: Godot function name (e.g. "_ready", "_process").
        params: Function parameter string (e.g. "", "delta", "event").
        sort_key: Canonical ordering in the generated .gd file.
        gml_filename: Expected GML source filename (e.g. "Create_0.gml").
        fallback_gml_filenames: Additional source filenames to try when the
            preferred GameMaker event source file is not present.
    """
    godot_func: str
    params: str
    sort_key: int
    gml_filename: str
    fallback_gml_filenames: tuple[str, ...] = ()
