from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    project_gml_source_paths,
    resolve_project_source_path,
)


class TestProjectSourcePaths(unittest.TestCase):
    def test_accepts_mixed_separators_and_normalizes_in_project_segments(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            yy_path = root / "sprites" / "actors" / "s_player" / "s_player.yy"
            yy_path.parent.mkdir(parents=True)
            yy_path.write_text("{}", encoding="utf-8")

            resolved = resolve_project_source_path(
                root,
                r"sprites\actors/unused/../s_player\s_player.yy",
            )

            self.assertEqual(
                resolved.source_path,
                "sprites/actors/s_player/s_player.yy",
            )
            self.assertEqual(resolved.filesystem_path, os.path.abspath(yy_path))

    def test_rejects_parent_traversal_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as parent_text:
            parent = Path(parent_text)
            root = parent / "project"
            root.mkdir()
            outside = parent / "outside.yy"
            outside.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(
                ProjectSourcePathError,
                "escapes the selected GameMaker project root",
            ):
                resolve_project_source_path(root, "sprites/../../outside.yy")

    def test_rejects_posix_windows_drive_and_unc_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            absolute_paths = (
                "/tmp/outside.yy",
                r"C:\Games\Outside\outside.yy",
                r"C:Outside\outside.yy",
                r"./C:\Games\Outside\outside.yy",
                r"sprites/../C:\Games\Outside\outside.yy",
                r"\\server\share\outside.yy",
            )
            for source_path in absolute_paths:
                with self.subTest(source_path=source_path):
                    with self.assertRaisesRegex(
                        ProjectSourcePathError,
                        "must be relative",
                    ):
                        resolve_project_source_path(root, source_path)

    def test_rejects_symbolic_link_escape(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root_text,
            tempfile.TemporaryDirectory() as outside_text,
        ):
            root = Path(root_text)
            outside = Path(outside_text)
            (outside / "s_escape.yy").write_text("{}", encoding="utf-8")
            sprites = root / "sprites"
            sprites.mkdir()
            try:
                (sprites / "linked").symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            with self.assertRaisesRegex(
                ProjectSourcePathError,
                "symbolic link",
            ):
                resolve_project_source_path(root, "sprites/linked/s_escape.yy")

    def test_allows_symbolic_links_that_remain_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            target = root / "sprites" / "s_inside"
            target.mkdir(parents=True)
            yy_path = target / "s_inside.yy"
            yy_path.write_text("{}", encoding="utf-8")
            try:
                (root / "sprite_alias").symlink_to(
                    root / "sprites",
                    target_is_directory=True,
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            resolved = resolve_project_source_path(
                root,
                "sprite_alias/s_inside/s_inside.yy",
            )

            self.assertEqual(
                os.path.realpath(resolved.filesystem_path),
                os.path.realpath(yy_path),
            )
            self.assertEqual(
                resolved.source_path,
                "sprite_alias/s_inside/s_inside.yy",
            )

    def test_enumerates_only_yyp_owned_gml_in_resource_and_metadata_order(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            resources = [
                ("scripts", "scr_live"),
                ("objects", "o_live"),
                ("rooms", "r_live"),
            ]
            (root / "Project.yyp").write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "id": {
                                    "name": name,
                                    "path": f"{kind}/{name}/{name}.yy",
                                }
                            }
                            for kind, name in resources
                        ],
                        "RoomOrderNodes": [],
                        "resourceType": "GMProject",
                    }
                ),
                encoding="utf-8",
            )

            script_dir = root / "scripts" / "scr_live"
            script_dir.mkdir(parents=True)
            (script_dir / "scr_live.yy").write_text(
                json.dumps({"name": "scr_live", "resourceType": "GMScript"}),
                encoding="utf-8",
            )
            (script_dir / "scr_live.gml").write_text("#macro LIVE 1\n", encoding="utf-8")
            (script_dir / "Deleted.gml").write_text("#macro STALE 1\n", encoding="utf-8")

            object_dir = root / "objects" / "o_live"
            object_dir.mkdir(parents=True)
            (object_dir / "o_live.yy").write_text(
                json.dumps(
                    {
                        "name": "o_live",
                        "resourceType": "GMObject",
                        "eventList": [{"eventType": 0, "eventNum": 0}],
                    }
                ),
                encoding="utf-8",
            )
            (object_dir / "Create_0.gml").write_text("enum Live { A }\n", encoding="utf-8")
            (object_dir / "Step_0.gml").write_text("enum Deleted { A }\n", encoding="utf-8")

            room_dir = root / "rooms" / "r_live"
            room_dir.mkdir(parents=True)
            (room_dir / "r_live.yy").write_text(
                json.dumps(
                    {
                        "name": "r_live",
                        "resourceType": "GMRoom",
                        "creationCodeFile": "RoomCreationCode.gml",
                        "layers": [
                            {
                                "instances": [
                                    {"name": "inst_live", "hasCreationCode": True},
                                    {"name": "inst_deleted", "hasCreationCode": False},
                                ]
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (room_dir / "RoomCreationCode.gml").write_text("#macro ROOM 1\n", encoding="utf-8")
            (room_dir / "InstanceCreationCode_inst_live.gml").write_text(
                "#macro INSTANCE 1\n",
                encoding="utf-8",
            )
            (room_dir / "InstanceCreationCode_inst_deleted.gml").write_text(
                "#macro DELETED_INSTANCE 1\n",
                encoding="utf-8",
            )

            orphan_dir = root / "scripts" / "scr_orphan"
            orphan_dir.mkdir(parents=True)
            (orphan_dir / "scr_orphan.gml").write_text(
                "#macro ORPHAN 1\n",
                encoding="utf-8",
            )

            source_paths = tuple(
                source.source_path for source in project_gml_source_paths(root)
            )

            self.assertEqual(
                source_paths,
                (
                    "scripts/scr_live/scr_live.gml",
                    "objects/o_live/Create_0.gml",
                    "rooms/r_live/RoomCreationCode.gml",
                    "rooms/r_live/InstanceCreationCode_inst_live.gml",
                ),
            )


if __name__ == "__main__":
    unittest.main()
