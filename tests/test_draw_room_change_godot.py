"""A room change requested by a Draw event, as GameMaker carries it out.

Once an event requests a room change, GameMaker runs no further events of
the old room: yyObject.PerformEvent returns while New_Room != -1, and Draw
events are not among the events persistent instances still get (HTML5
runner: yyObject.js PerformEvent). So after a Draw event calls room_goto,
no later Draw, Draw End, Post Draw or Draw GUI event runs in that frame,
for any instance.

The runner then switches rooms and runs a whole step of the new room in the
same tick (_GameMaker.js GameMaker_Tick), and that step's draw updates the
views first (yyRoom.js DrawViews calls UpdateViews): the new room's first
frame is already drawn with its views following their objects.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    InstanceLayer,
    RoomInstance,
    RoomView,
    add_probe_autoload,
    convert_gamemaker_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_EVENT_DRAW = (8, 0)
_EVENT_DRAW_GUI = (8, 64)
_EVENT_DRAW_BEGIN = (8, 72)
_EVENT_DRAW_END = (8, 73)
_EVENT_POST_DRAW = (8, 77)

_LOG = """function log_event(_who, _what) {
    array_push(global.log, _who + ":" + _what + ":" + room_get_name(room));
}
"""


def _log(who: str, what: str) -> str:
    return f'log_event("{who}", "{what}");\n'


_PROJECT = GameMakerProject(
    name="DrawRoomChange",
    scripts={"scr_log": _LOG},
    objects=(
        # Deepest, so its Draw runs first; its second Draw requests the change.
        GameMakerObject(
            "o_goer",
            {
                EVENT_CREATE: "draws = 0;\n",
                _EVENT_DRAW: "draws += 1;\nif (room == r_first && draws == 2) {\n    "
                + _log("o_goer", "goto")
                + "    room_goto(r_second);\n}\n",
                _EVENT_DRAW_GUI: _log("o_goer", "draw_gui"),
            },
        ),
        GameMakerObject(
            "o_watcher",
            {
                _EVENT_DRAW_BEGIN: _log("o_watcher", "draw_begin"),
                _EVENT_DRAW: _log("o_watcher", "draw"),
                _EVENT_DRAW_END: _log("o_watcher", "draw_end"),
                _EVENT_POST_DRAW: _log("o_watcher", "post_draw"),
                _EVENT_DRAW_GUI: _log("o_watcher", "draw_gui"),
            },
        ),
        # Persistent instances get no Draw events either once the change is
        # requested; they draw again in the new room.
        GameMakerObject(
            "o_keeper",
            {_EVENT_DRAW: _log("o_keeper", "draw"), _EVENT_DRAW_GUI: _log("o_keeper", "draw_gui")},
            persistent=True,
        ),
        # The object the new room's view follows; it records the view
        # position its first Draw events see.
        GameMakerObject(
            "o_player",
            {
                EVENT_CREATE: "draws = 0;\n",
                _EVENT_DRAW: "draws += 1;\n"
                "var _cam = view_camera[0];\n"
                'array_push(global.views, string(camera_get_view_x(_cam)) + "," + string(camera_get_view_y(_cam)));\n'
                "if (draws == 3) global.done = true;\n",
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_first",
            layers=(
                InstanceLayer(
                    "Front",
                    0,
                    (RoomInstance("inst_watcher", "o_watcher", 10, 10), RoomInstance("inst_keeper", "o_keeper", 20, 10)),
                ),
                InstanceLayer("Back", 100, (RoomInstance("inst_goer", "o_goer", 30, 10),)),
            ),
            creation_order=("inst_goer", "inst_watcher", "inst_keeper"),
            creation_code="global.log = [];\nglobal.views = [];\nglobal.done = false;\n",
        ),
        GameMakerRoom(
            "r_second",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_player", "o_player", 600, 400),)),),
            creation_order=("inst_player",),
            width=1000,
            height=1000,
            views=(RoomView(0, 0, 320, 240, 0, 0, 320, 240),),
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	var scope = GMRuntime.gml_global_scope()
	if _frames > 300 or bool(scope.get("done", false)):
		print("DRAW_ROOM_CHANGE " + JSON.stringify({"log": scope.get("log", []), "views": scope.get("views", [])}))
		get_tree().quit(0)
"""


def _follow_player(gamemaker_dir: Path) -> None:
    # View 0 of the second room follows o_player (Room Editor "Object
    # Following"), with the default 32 pixel borders.
    room_path = gamemaker_dir / "rooms" / "r_second" / "r_second.yy"
    room = json.loads(room_path.read_text(encoding="utf-8"))
    room["views"][0]["objectId"] = {"name": "o_player", "path": "objects/o_player/o_player.yy"}
    room_path.write_text(json.dumps(room, indent=2) + "\n", encoding="utf-8")


class TestDrawRoomChangeGodot(unittest.TestCase):
    results: dict[str, list[str]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            raise unittest.SkipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            _follow_player(root / "gamemaker")
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
        output = result.stdout + result.stderr
        if result.returncode != 0 or "SCRIPT ERROR" in output:
            raise AssertionError(output)
        lines = [line for line in output.splitlines() if line.startswith("DRAW_ROOM_CHANGE ")]
        if len(lines) != 1:
            raise AssertionError(output)
        cls.results = json.loads(lines[0].removeprefix("DRAW_ROOM_CHANGE "))

    def test_no_draw_event_runs_after_a_draw_event_requests_a_room_change(self) -> None:
        log = self.results["log"]
        self.assertIn("o_goer:goto:r_first", log)
        goto = log.index("o_goer:goto:r_first")
        # The frame's Draw Begin ran before the change was requested.
        self.assertEqual(log[goto - 1], "o_watcher:draw_begin:r_first")
        # Nothing of the old room draws after the request, persistent
        # instances included ...
        after = log[goto + 1 :]
        self.assertEqual([entry for entry in after if entry.endswith(":r_first")], [])
        # ... and the next draw is the new room's.
        self.assertEqual(after[:2], ["o_keeper:draw:r_second", "o_keeper:draw_gui:r_second"])

    def test_the_new_room_is_first_drawn_with_its_views_following(self) -> None:
        # o_player at (600, 400) in a 1000x1000 room: the 320x240 view with
        # 32 pixel borders moves to (600 + 32 - 320, 400 + 32 - 240) before
        # the first draw of the room.
        self.assertEqual(self.results["views"], ["312,192", "312,192", "312,192"])


if __name__ == "__main__":
    unittest.main()
