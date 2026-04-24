from dataclasses import dataclass


@dataclass(frozen=True)
class EventMapping:
    """Metadata for mapping a GameMaker event to a Godot function.

    Attributes:
        godot_func: Godot function name (e.g. "_ready", "_process").
        params: Function parameter string (e.g. "", "delta", "event").
        sort_key: Canonical ordering in the generated .gd file.
        gml_filename: Expected GML source filename (e.g. "Create_0.gml").
    """
    godot_func: str
    params: str
    sort_key: int
    gml_filename: str
