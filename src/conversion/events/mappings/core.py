from typing import cast

from src.conversion.events.base import EventMapping, EventTypeHandlers, StaticMappings
from src.conversion.type_defs import JsonDict


STATIC_MAPPINGS: StaticMappings = {
    (0, 0): EventMapping("_ready", "", 0, "Create_0.gml"),
    (1, 0): EventMapping("_on_destroy", "", 10, "Destroy_0.gml"),
    (3, 1): EventMapping("_on_begin_step", "", 1, "Step_1.gml"),
    (3, 0): EventMapping("_on_step", "", 2, "Step_0.gml"),
    (3, 2): EventMapping("_on_end_step", "", 12, "Step_2.gml"),
    (8, 0): EventMapping("_draw", "", 3, "Draw_0.gml"),
    (8, 64): EventMapping("_on_draw_gui", "", 15, "Draw_64.gml"),
    (8, 65): EventMapping("_on_resize", "", 6, "Draw_65.gml"),
    (8, 72): EventMapping("_on_draw_begin", "", 16, "Draw_72.gml"),
    (8, 73): EventMapping("_on_draw_end", "", 16, "Draw_73.gml"),
    (8, 74): EventMapping("_on_draw_gui_begin", "", 15, "Draw_74.gml"),
    (8, 75): EventMapping("_on_draw_gui_end", "", 15, "Draw_75.gml"),
    (8, 76): EventMapping("_on_pre_draw", "", 16, "Draw_76.gml"),
    (8, 77): EventMapping("_on_post_draw", "", 16, "Draw_77.gml"),
    (12, 0): EventMapping("_exit_tree", "", 5, "CleanUp_0.gml"),
}


def map_create_event(_event: JsonDict, gml_filename: str) -> EventMapping:
    return EventMapping("_ready", "", 0, gml_filename)


def map_destroy_event(_event: JsonDict, gml_filename: str) -> EventMapping:
    return EventMapping("_on_destroy", "", 10, gml_filename)


def map_cleanup_event(_event: JsonDict, gml_filename: str) -> EventMapping:
    return EventMapping("_exit_tree", "", 5, gml_filename)


def map_alarm_event(event: JsonDict, gml_filename: str) -> EventMapping:
    return EventMapping(f"_on_alarm_{event.get('eventNum', 0)}", "", 11, gml_filename)


def map_collision_event(event: JsonDict, gml_filename: str) -> EventMapping:
    collision_obj = event.get('collisionObjectId')
    if collision_obj and isinstance(collision_obj, dict):
        collision_data = cast(JsonDict, collision_obj)
        obj_name = cast(str, collision_data.get('name', 'unknown'))
        return EventMapping(f"_on_collision_{obj_name}", "", 13, gml_filename)
    return EventMapping("_on_collision", "", 13, gml_filename)


def map_other_event(event: JsonDict, gml_filename: str) -> EventMapping:
    return EventMapping(f"_on_other_{event.get('eventNum', 0)}", "", 14, gml_filename)


def map_draw_event(event: JsonDict, gml_filename: str) -> EventMapping:
    return EventMapping(f"_on_draw_{event.get('eventNum', 0)}", "", 16, gml_filename)


EVENT_TYPE_HANDLERS: EventTypeHandlers = {
    0: map_create_event,
    1: map_destroy_event,
    2: map_alarm_event,
    4: map_collision_event,
    7: map_other_event,
    8: map_draw_event,
    12: map_cleanup_event,
}
