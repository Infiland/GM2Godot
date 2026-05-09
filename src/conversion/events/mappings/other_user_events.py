from src.conversion.events.base import EventMapping, StaticMappings


STATIC_MAPPINGS: StaticMappings = {
    (7, event_num): EventMapping(
        f"_user_event_{event_num - 10}",
        "",
        14,
        f"Other_{event_num}.gml",
    )
    for event_num in range(10, 26)
}
