from __future__ import annotations

import unittest

from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.room_display import (
    GAMEMAKER_VIEW_COUNT,
    application_surface_display_settings,
    application_surface_size,
    room_size,
    room_view_entries,
)


def _view(**overrides: JsonValue) -> JsonObject:
    view: JsonObject = {
        "visible": False,
        "xview": 0,
        "yview": 0,
        "wview": 1366,
        "hview": 768,
        "xport": 0,
        "yport": 0,
        "wport": 1366,
        "hport": 768,
        "hborder": 32,
        "vborder": 32,
        "hspeed": -1,
        "vspeed": -1,
        "objectId": None,
    }
    view.update(overrides)
    return view


class TestRoomDisplay(unittest.TestCase):
    def test_room_size_uses_gamemaker_defaults_for_missing_values(self) -> None:
        self.assertEqual(room_size({"Width": 320, "Height": 200}), (320.0, 200.0))
        self.assertEqual(room_size({}), (1024.0, 768.0))
        self.assertEqual(room_size(None), (1024.0, 768.0))

    def test_application_surface_uses_room_size_without_views(self) -> None:
        size = application_surface_size(
            {"Width": 640, "Height": 360},
            {"enableViews": False},
            [_view(visible=True, wport=1920, hport=1080)],
        )

        self.assertEqual(size, (640, 360))

    def test_application_surface_uses_visible_port_extent_with_views(self) -> None:
        size = application_surface_size(
            {"Width": 4000, "Height": 3000},
            {"enableViews": True},
            [
                _view(visible=True, wview=64, hview=64, wport=640, hport=640),
                _view(visible=False, xport=0, yport=0, wport=5000, hport=5000),
                _view(visible=True, xport=600, yport=100, wport=100, hport=600),
            ],
        )

        self.assertEqual(size, (700, 700))

    def test_views_enabled_without_visible_views_falls_back_to_room_size(self) -> None:
        size = application_surface_size(
            {"Width": 800, "Height": 450},
            {"enableViews": True},
            [_view(visible=False, wport=64, hport=64)],
        )

        self.assertEqual(size, (800, 450))

    def test_room_view_entries_normalize_eight_slots(self) -> None:
        entries = room_view_entries(
            [
                _view(
                    visible=True,
                    xview=8,
                    yview=16,
                    wview=64.5,
                    hview=64,
                    wport=640,
                    hport=640,
                    objectId={"name": "o_target", "path": "objects/o_target/o_target.yy"},
                    hborder=100,
                    vborder=50,
                    hspeed=4,
                    vspeed=-1,
                )
            ],
            {"Width": 320, "Height": 240},
        )

        self.assertEqual(len(entries), GAMEMAKER_VIEW_COUNT)
        self.assertEqual(
            entries[0],
            {
                "visible": True,
                "xview": 8,
                "yview": 16,
                "wview": 64.5,
                "hview": 64,
                "xport": 0,
                "yport": 0,
                "wport": 640,
                "hport": 640,
                "object": "o_target",
                "hborder": 100,
                "vborder": 50,
                "hspeed": 4,
                "vspeed": -1,
            },
        )
        for entry in entries[1:]:
            self.assertFalse(entry["visible"])
            self.assertEqual((entry["wview"], entry["hview"]), (320, 240))
            self.assertEqual((entry["wport"], entry["hport"]), (320, 240))
            self.assertIsNone(entry["object"])
            self.assertEqual((entry["hborder"], entry["vborder"]), (32, 32))
            self.assertEqual((entry["hspeed"], entry["vspeed"]), (-1, -1))

    def test_room_view_entries_ignore_slots_beyond_eight(self) -> None:
        entries = room_view_entries(
            [_view(xview=index) for index in range(10)],
            {"Width": 320, "Height": 240},
        )

        self.assertEqual([entry["xview"] for entry in entries], list(range(8)))

    def test_display_settings_select_viewport_stretch(self) -> None:
        self.assertEqual(
            application_surface_display_settings(640, 480),
            (
                ("display", "window/size/viewport_width", 640),
                ("display", "window/size/viewport_height", 480),
                ("display", "window/stretch/mode", "viewport"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
