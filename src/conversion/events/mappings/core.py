from src.conversion.events.base import EventMapping


STATIC_MAPPINGS = {
    (0, 0): EventMapping("_ready", "", 0, "Create_0.gml"),
    (1, 0): EventMapping("_on_destroy", "", 10, "Destroy_0.gml"),
    (3, 0): EventMapping("_process", "delta", 1, "Step_0.gml"),
    (3, 1): EventMapping("_physics_process", "delta", 2, "Step_1.gml"),
    (3, 2): EventMapping("_on_end_step", "", 12, "Step_2.gml"),
    (8, 0): EventMapping("_draw", "", 3, "Draw_0.gml"),
    (8, 64): EventMapping("_on_draw_gui", "", 15, "Draw_64.gml"),
    (12, 0): EventMapping("_exit_tree", "", 5, "CleanUp_0.gml"),
}


def map_create_event(_event, gml_filename):
    return EventMapping("_ready", "", 0, gml_filename)


def map_destroy_event(_event, gml_filename):
    return EventMapping("_on_destroy", "", 10, gml_filename)


def map_cleanup_event(_event, gml_filename):
    return EventMapping("_exit_tree", "", 5, gml_filename)


def map_alarm_event(event, gml_filename):
    return EventMapping(f"_on_alarm_{event.get('eventNum', 0)}", "", 11, gml_filename)


def map_collision_event(event, gml_filename):
    collision_obj = event.get('collisionObjectId')
    if collision_obj and isinstance(collision_obj, dict):
        obj_name = collision_obj.get('name', 'unknown')
        return EventMapping(f"_on_collision_{obj_name}", "", 13, gml_filename)
    return EventMapping("_on_collision", "", 13, gml_filename)


def map_other_event(event, gml_filename):
    return EventMapping(f"_on_other_{event.get('eventNum', 0)}", "", 14, gml_filename)


def map_draw_event(event, gml_filename):
    return EventMapping(f"_on_draw_{event.get('eventNum', 0)}", "", 16, gml_filename)


EVENT_TYPE_HANDLERS = {
    0: map_create_event,
    1: map_destroy_event,
    2: map_alarm_event,
    4: map_collision_event,
    7: map_other_event,
    8: map_draw_event,
    12: map_cleanup_event,
}
