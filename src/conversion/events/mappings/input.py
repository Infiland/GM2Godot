from src.conversion.events.base import EventMapping
from src.conversion.type_defs import JsonDict


# Input event types are merged into a single _input(event) function.
# GameMaker keyboard-down events also route through the shared input stub for
# now so they are recognized as supported input instead of unknown events.
INPUT_EVENT_TYPES: set[int] = {5, 6, 9, 10, 13}
INPUT_MERGED_MAPPING = EventMapping("_input", "event", 4, "")

_INPUT_FUNCTION_PREFIXES: dict[int, str] = {
    5: "keyboard",
    6: "mouse",
    9: "key_press",
    10: "key_release",
    13: "gesture",
}

_INPUT_GML_PREFIXES: dict[int, str] = {
    5: "Keyboard",
    6: "Mouse",
    9: "KeyPress",
    10: "KeyRelease",
    13: "Gesture",
}


def map_input_event(event: JsonDict) -> EventMapping | None:
    """Map an input event to its event-specific generated method.

    The public ``map_event`` API still returns ``None`` for these events so
    callers can treat them as merged input. Object conversion uses this helper
    to load and transpile the original ``Keyboard_*.gml``, ``Mouse_*.gml``,
    and gesture source files into methods that the GMInput router dispatches.
    """
    event_type = int(event.get("eventType", -1))
    event_num = int(event.get("eventNum", 0))
    function_prefix = _INPUT_FUNCTION_PREFIXES.get(event_type)
    gml_prefix = _INPUT_GML_PREFIXES.get(event_type)
    if function_prefix is None or gml_prefix is None:
        return None
    return EventMapping(
        f"_gm_input_{function_prefix}_{event_num}",
        "",
        4,
        f"{gml_prefix}_{event_num}.gml",
    )
