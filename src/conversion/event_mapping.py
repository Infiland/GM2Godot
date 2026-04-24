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


# Input event types that are merged into a single _input(event) function.
# GameMaker keyboard-down events also route through the shared input stub for
# now so they are recognized as supported input instead of unknown events.
INPUT_EVENT_TYPES = frozenset({5, 6, 9, 10, 13})

# The merged input event mapping used when any input event is present
INPUT_MERGED_MAPPING = EventMapping("_input", "event", 4, "")

# Static lookup for events with fixed (eventType, eventNum) mappings
_STATIC_MAP = {
    (0, 0): EventMapping("_ready", "", 0, "Create_0.gml"),
    (1, 0): EventMapping("_on_destroy", "", 10, "Destroy_0.gml"),
    (3, 0): EventMapping("_process", "delta", 1, "Step_0.gml"),
    (3, 1): EventMapping("_physics_process", "delta", 2, "Step_1.gml"),
    (3, 2): EventMapping("_on_end_step", "", 12, "Step_2.gml"),
    (8, 0): EventMapping("_draw", "", 3, "Draw_0.gml"),
    (8, 64): EventMapping("_on_draw_gui", "", 15, "Draw_64.gml"),
    (12, 0): EventMapping("_exit_tree", "", 5, "CleanUp_0.gml"),
    (7, 6): EventMapping("_on_no_more_lives", "", 14, "Other_6.gml"),
    (7, 9): EventMapping("_on_no_more_health", "", 14, "Other_9.gml"),
}

# GameMaker event type number to GML filename prefix
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


def is_input_event(event):
    """Check whether an event dict represents a supported input event."""
    return event.get('eventType', -1) in INPUT_EVENT_TYPES


def map_event(event):
    """Map a GameMaker event dict to an EventMapping.

    Returns None for input events (types 6, 9, 10) since they are merged
    into a single _input(event) function by the script generator.
    """
    event_type = event.get('eventType', -1)
    event_num = event.get('eventNum', 0)

    if event_type in INPUT_EVENT_TYPES:
        return None

    # Try static lookup first
    mapping = _STATIC_MAP.get((event_type, event_num))
    if mapping is not None:
        return mapping

    # Build GML filename for dynamic events
    gml_prefix = _GML_EVENT_NAMES.get(event_type, f"Event{event_type}")
    gml_filename = f"{gml_prefix}_{event_num}.gml"

    # Lifecycle events that match on eventType alone (any eventNum)
    if event_type == 0:
        return EventMapping("_ready", "", 0, gml_filename)
    if event_type == 1:
        return EventMapping("_on_destroy", "", 10, gml_filename)
    if event_type == 12:
        return EventMapping("_exit_tree", "", 5, gml_filename)

    # Variable events
    if event_type == 2:
        return EventMapping(f"_on_alarm_{event_num}", "", 11, gml_filename)
    if event_type == 4:
        collision_obj = event.get('collisionObjectId')
        if collision_obj and isinstance(collision_obj, dict):
            obj_name = collision_obj.get('name', 'unknown')
            return EventMapping(f"_on_collision_{obj_name}", "", 13, gml_filename)
        return EventMapping("_on_collision", "", 13, gml_filename)
    if event_type == 7:
        return EventMapping(f"_on_other_{event_num}", "", 14, gml_filename)
    if event_type == 8:
        return EventMapping(f"_on_draw_{event_num}", "", 16, gml_filename)

    # Unknown event type
    return EventMapping(f"_on_event_{event_type}_{event_num}", "", 20, gml_filename)
