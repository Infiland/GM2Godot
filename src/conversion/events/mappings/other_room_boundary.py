from src.conversion.events.base import EventMapping, StaticMappings


STATIC_MAPPINGS: StaticMappings = {
    (7, 0): EventMapping("_on_outside_room", "", 14, "Other_0.gml"),
    (7, 1): EventMapping("_on_intersect_boundary", "", 14, "Other_1.gml"),
}

STATIC_MAPPINGS.update({
    (7, 40 + view_index): EventMapping(
        f"_on_outside_view_{view_index}",
        "",
        14,
        f"Other_{40 + view_index}.gml",
    )
    for view_index in range(8)
})

STATIC_MAPPINGS.update({
    (7, 50 + view_index): EventMapping(
        f"_on_intersect_view_{view_index}_boundary",
        "",
        14,
        f"Other_{50 + view_index}.gml",
    )
    for view_index in range(8)
})
