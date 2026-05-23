import importlib
import pkgutil
from types import ModuleType
from typing import Any, Iterator, cast

from src.conversion.events import mappings
from src.conversion.events.base import EventMapping, EventTypeHandlers, StaticMappings
from src.conversion.type_defs import JsonDict


_GML_EVENT_NAMES: dict[int, str] = {
    0: "Create",
    1: "Destroy",
    2: "Alarm",
    3: "Step",
    4: "Collision",
    5: "Keyboard",
    6: "Mouse",
    7: "Other",
    8: "Draw",
    9: "KeyPress",
    10: "KeyRelease",
    12: "CleanUp",
    13: "Gesture",
}


def _iter_package_modules(package: ModuleType) -> Iterator[ModuleType]:
    package_info = cast(Any, package)
    modules = sorted(pkgutil.iter_modules(package_info.__path__), key=lambda module: module.name)
    for module in modules:
        yield importlib.import_module(f"{package_info.__name__}.{module.name}")


def _load_mapping_registry() -> tuple[StaticMappings, EventTypeHandlers, frozenset[int], EventMapping]:
    static_map: StaticMappings = {}
    event_type_handlers: EventTypeHandlers = {}
    input_event_types: set[int] = set()
    input_merged_mapping: EventMapping | None = None

    for module in _iter_package_modules(mappings):
        static_map.update(cast(StaticMappings, getattr(module, "STATIC_MAPPINGS", {})))
        event_type_handlers.update(cast(EventTypeHandlers, getattr(module, "EVENT_TYPE_HANDLERS", {})))
        input_event_types.update(cast(set[int], getattr(module, "INPUT_EVENT_TYPES", set[int]())))

        module_input_mapping = cast(EventMapping | None, getattr(module, "INPUT_MERGED_MAPPING", None))
        if module_input_mapping is not None:
            input_merged_mapping = module_input_mapping

    if input_merged_mapping is None:
        input_merged_mapping = EventMapping("_input", "event", 4, "")

    return static_map, event_type_handlers, frozenset(input_event_types), input_merged_mapping


_STATIC_MAP, _EVENT_TYPE_HANDLERS, INPUT_EVENT_TYPES, INPUT_MERGED_MAPPING = _load_mapping_registry()


def is_input_event(event: JsonDict) -> bool:
    """Check whether an event dict represents a supported input event."""
    return event.get('eventType', -1) in INPUT_EVENT_TYPES


def map_event(event: JsonDict) -> EventMapping | None:
    """Map a GameMaker event dict to an EventMapping.

    Returns None for input events since they are merged into a single
    _input(event) function by the script generator.
    """
    event_type = cast(int, event.get('eventType', -1))
    event_num = cast(int, event.get('eventNum', 0))

    if event_type in INPUT_EVENT_TYPES:
        return None

    mapping = _STATIC_MAP.get((event_type, event_num))
    if mapping is not None:
        return mapping

    gml_prefix = _GML_EVENT_NAMES.get(event_type, f"Event{event_type}")
    gml_filename = f"{gml_prefix}_{event_num}.gml"

    handler = _EVENT_TYPE_HANDLERS.get(event_type)
    if handler is not None:
        return handler(event, gml_filename)

    return EventMapping(f"_on_event_{event_type}_{event_num}", "", 20, gml_filename)


def map_input_event(event: JsonDict) -> EventMapping | None:
    """Map an input event to its source-backed generated handler."""
    from src.conversion.events.mappings.input import map_input_event as _map_input_event

    if not is_input_event(event):
        return None
    return _map_input_event(event)
