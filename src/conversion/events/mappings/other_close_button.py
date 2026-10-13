from src.conversion.events.base import EventMapping, StaticMappings

# A plain method like every other event: the runtime calls it for each
# instance when the window is closed (gml_game_window_close_request), and the
# object's nearest handler runs.
STATIC_MAPPINGS: StaticMappings = {
    (7, 30): EventMapping("_on_close_button", "", 6, "Other_30.gml"),
}
