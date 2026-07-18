from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import cast

from src.conversion.architecture_policy import (
    ARCHITECTURE_POLICY_RELATIVE_PATH,
    build_architecture_policy_report,
    write_architecture_policy_report,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class TestArchitecturePolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.gm_dir = self.temp_dir / "gm"
        self.godot_dir = self.temp_dir / "godot"
        self.gm_dir.mkdir()
        self.godot_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_policy_selection_uses_representative_project_features(self) -> None:
        self._write_project_with_room_and_feature_script()

        report = build_architecture_policy_report(
            str(self.gm_dir),
            target_platform="windows",
            enabled_converters=["scripts", "rooms", "sounds"],
        )
        features = cast(dict[str, object], report["project_features"])
        signal_policy = cast(list[dict[str, object]], report["signal_queue_policy"])

        self.assertEqual(features["room_count"], 1)
        self.assertEqual(features["has_multiple_visible_views"], True)
        self.assertEqual(features["has_tile_layers"], True)
        self.assertEqual(features["has_scrolling_or_tiled_backgrounds"], True)
        self.assertEqual(features["has_surface_code"], True)
        self.assertEqual(features["has_precise_collision_request"], True)
        self.assertEqual(cast(dict[str, object], report["renderer"])["mode"], "surface_viewport")
        self.assertEqual(
            cast(dict[str, object], report["collision"])["mode"],
            "godot_physics_world_bridge",
        )
        self.assertEqual(
            cast(dict[str, object], report["collision"])["precise_masks"],
            "planned_custom_mask_backend",
        )
        self.assertEqual(cast(dict[str, object], report["audio"])["mode"], "pooled_audio_stream_players")
        self.assertEqual(
            cast(dict[str, object], report["file_buffer_network"])["network"],
            "gm_async_socket_wrappers",
        )
        self.assertIn(
            {"godot_signal": "HTTPRequest.request_completed", "runtime_manager": "GMAsync"},
            [
                {
                    "godot_signal": str(policy["godot_signal"]),
                    "runtime_manager": str(policy["runtime_manager"]),
                }
                for policy in signal_policy
            ],
        )

    def test_write_report_emits_deterministic_json(self) -> None:
        self._write_minimal_project()

        report_path = write_architecture_policy_report(
            str(self.gm_dir),
            str(self.godot_dir),
            target_platform="linux",
            enabled_converters=["rooms"],
        )

        self.assertEqual(report_path, str(self.godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH))
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        self.assertEqual(report["format_version"], 1)
        self.assertEqual(report["target_platform"], "linux")
        self.assertEqual(report["enabled_converters"], ["rooms"])
        self.assertEqual(report["room_root"]["id"], "gm_room_node2d")
        self.assertEqual(report["renderer"]["mode"], "godot_node_scene")

    def test_feature_scan_ignores_gml_file_symlink_outside_project(self) -> None:
        self._write_minimal_project()
        outside_source = self.temp_dir / "outside.gml"
        _write_text(outside_source, "network_create_socket(0);")
        linked_source = self.gm_dir / "scripts" / "linked.gml"
        linked_source.parent.mkdir(parents=True, exist_ok=True)
        try:
            linked_source.symlink_to(outside_source)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symbolic links are unavailable: {exc}")

        report = build_architecture_policy_report(
            str(self.gm_dir),
            target_platform="windows",
            enabled_converters=["scripts"],
        )
        features = cast(dict[str, object], report["project_features"])

        self.assertEqual(features["has_network_code"], False)

    def _write_minimal_project(self) -> None:
        _write_json(
            self.gm_dir / "PolicyProject.yyp",
            {
                "resources": [
                    {"id": {"name": "r_empty", "path": "rooms/r_empty/r_empty.yy"}},
                ],
                "RoomOrderNodes": [
                    {"roomId": {"name": "r_empty", "path": "rooms/r_empty/r_empty.yy"}},
                ],
                "resourceType": "GMProject",
            },
        )
        _write_json(
            self.gm_dir / "rooms" / "r_empty" / "r_empty.yy",
            self._room("r_empty"),
        )

    def _write_project_with_room_and_feature_script(self) -> None:
        _write_json(
            self.gm_dir / "PolicyProject.yyp",
            {
                "resources": [
                    {"id": {"name": "r_policy", "path": "rooms/r_policy/r_policy.yy"}},
                    {"id": {"name": "scr_policy", "path": "scripts/scr_policy/scr_policy.yy"}},
                ],
                "RoomOrderNodes": [
                    {"roomId": {"name": "r_policy", "path": "rooms/r_policy/r_policy.yy"}},
                ],
                "resourceType": "GMProject",
            },
        )
        _write_json(
            self.gm_dir / "rooms" / "r_policy" / "r_policy.yy",
            self._room(
                "r_policy",
                physics_world=True,
                layers=[
                    {"%Name": "Instances", "resourceType": "GMRInstanceLayer"},
                    {
                        "%Name": "Tiles",
                        "resourceType": "GMRTileLayer",
                        "tiles": {"SerialiseWidth": 1, "SerialiseHeight": 1, "TileCompressedData": [0]},
                    },
                    {
                        "%Name": "Background",
                        "resourceType": "GMRBackgroundLayer",
                        "htiled": True,
                        "hspeed": 2,
                    },
                ],
                views=[
                    {"visible": True, "xview": 0, "yview": 0, "wview": 320, "hview": 180},
                    {"visible": True, "xview": 320, "yview": 0, "wview": 320, "hview": 180},
                ],
            ),
        )
        _write_json(
            self.gm_dir / "scripts" / "scr_policy" / "scr_policy.yy",
            {
                "%Name": "scr_policy",
                "name": "scr_policy",
                "resourceType": "GMScript",
                "parent": {"name": "Scripts", "path": "folders/Scripts.yy"},
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_policy" / "scr_policy.gml",
            "\n".join([
                "surface_create(320, 180);",
                "audio_play_sound(snd_click, 0, false);",
                "network_create_socket(0);",
                "buffer_create(16, buffer_grow, 1);",
                "collision_point(id, x, y, o_wall, true, false);",
            ]),
        )

    @staticmethod
    def _room(
        name: str,
        *,
        physics_world: bool = False,
        layers: list[dict[str, object]] | None = None,
        views: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "$GMRoom": "v1",
            "%Name": name,
            "name": name,
            "creationCodeFile": "",
            "inheritCode": False,
            "inheritCreationOrder": False,
            "inheritLayers": False,
            "instanceCreationOrder": [],
            "isDnd": False,
            "layers": layers or [],
            "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
            "parentRoom": None,
            "physicsSettings": {
                "inheritPhysicsSettings": False,
                "PhysicsWorld": physics_world,
                "PhysicsWorldGravityX": 0.0,
                "PhysicsWorldGravityY": 10.0,
                "PhysicsWorldPixToMetres": 0.1,
            },
            "resourceType": "GMRoom",
            "roomSettings": {
                "Width": 640,
                "Height": 360,
                "inheritRoomSettings": False,
                "persistent": False,
            },
            "views": views or [],
            "viewSettings": {"enableViews": bool(views)},
            "volume": 1.0,
        }


if __name__ == "__main__":
    unittest.main()
