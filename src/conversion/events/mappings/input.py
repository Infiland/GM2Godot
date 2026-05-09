from src.conversion.events.base import EventMapping


# Input event types are merged into a single _input(event) function.
# GameMaker keyboard-down events also route through the shared input stub for
# now so they are recognized as supported input instead of unknown events.
INPUT_EVENT_TYPES: set[int] = {5, 6, 9, 10, 13}
INPUT_MERGED_MAPPING = EventMapping("_input", "event", 4, "")
