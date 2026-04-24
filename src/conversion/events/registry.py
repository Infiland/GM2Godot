import importlib
import pkgutil

from src.conversion.events import mappings
from src.conversion.events.base import EventMapping


_GML_EVENT_NAMES = {
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


def _iter_package_modules(package):
    modules = sorted(pkgutil.iter_modules(package.__path__), key=lambda module: module.name)
    for module in modules:
        yield importlib.import_module(f"{package.__name__}.{module.name}")


def _load_mapping_registry():
    static_map = {}
    event_type_handlers = {}
    input_event_types = set()
    input_merged_mapping = None

    for module in _iter_package_modules(mappings):
        static_map.update(getattr(module, "STATIC_MAPPINGS", {}))
        event_type_handlers.update(getattr(module, "EVENT_TYPE_HANDLERS", {}))
        input_event_types.update(getattr(module, "INPUT_EVENT_TYPES", set()))

        module_input_mapping = getattr(module, "INPUT_MERGED_MAPPING", None)
        if module_input_mapping is not None:
            input_merged_mapping = module_input_mapping

    if input_merged_mapping is None:
        input_merged_mapping = EventMapping("_input", "event", 4, "")

    return static_map, event_type_handlers, frozenset(input_event_types), input_merged_mapping


_STATIC_MAP, _EVENT_TYPE_HANDLERS, INPUT_EVENT_TYPES, INPUT_MERGED_MAPPING = _load_mapping_registry()


def is_input_event(event):
    """Check whether an event dict represents a supported input event."""
    return event.get('eventType', -1) in INPUT_EVENT_TYPES


def map_event(event):
    """Map a GameMaker event dict to an EventMapping.

    Returns None for input events since they are merged into a single
    _input(event) function by the script generator.
    """
    event_type = event.get('eventType', -1)
    event_num = event.get('eventNum', 0)

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
