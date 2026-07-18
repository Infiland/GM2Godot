from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    project_gml_source_paths,
    resolve_project_filesystem_source_path,
    resolve_project_sidecar_source_path,
    resolve_project_source_path,
    validate_project_resource_source_path,
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

    def test_resource_metadata_guard_preserves_only_same_kind_yy_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            same_kind = resolve_project_source_path(
                root,
                "scripts/legacy/../scr_live/scr_live.yy",
            )
            cross_kind = resolve_project_source_path(
                root,
                "scripts/../objects/o_cross/o_cross.yy",
            )
            wrong_extension = resolve_project_source_path(
                root,
                "scripts/scr_live/scr_live.gml",
            )

            self.assertIs(
                validate_project_resource_source_path(same_kind, "scripts"),
                same_kind,
            )
            self.assertEqual(
                same_kind.source_path,
                "scripts/scr_live/scr_live.yy",
            )
            with self.assertRaisesRegex(ProjectSourcePathError, "declared 'scripts'"):
                validate_project_resource_source_path(cross_kind, "scripts")
            with self.assertRaisesRegex(ProjectSourcePathError, ".yy metadata file"):
                validate_project_resource_source_path(wrong_extension, "scripts")

    def test_resource_metadata_guard_checks_contained_symlink_target_family(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            same_family_target = root / "sprites" / "target" / "target.yy"
            cross_family_target = root / "objects" / "target" / "target.yy"
            same_family_target.parent.mkdir(parents=True)
            cross_family_target.parent.mkdir(parents=True)
            same_family_target.write_text("{}", encoding="utf-8")
            cross_family_target.write_text("{}", encoding="utf-8")
            same_family_link = root / "sprites" / "same" / "same.yy"
            cross_family_link = root / "sprites" / "cross" / "cross.yy"
            same_family_link.parent.mkdir()
            cross_family_link.parent.mkdir()
            try:
                same_family_link.symlink_to(same_family_target)
                cross_family_link.symlink_to(cross_family_target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            same_family = resolve_project_source_path(
                root,
                "sprites/same/same.yy",
            )
            cross_family = resolve_project_source_path(
                root,
                "sprites/cross/cross.yy",
            )

            self.assertIs(
                validate_project_resource_source_path(
                    same_family,
                    "sprites",
                ),
                same_family,
            )
            with self.assertRaisesRegex(
                ProjectSourcePathError,
                "after symbolic-link resolution",
            ):
                validate_project_resource_source_path(
                    cross_family,
                    "sprites",
                )

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

    def test_rejects_leading_traversal_that_reenters_project_lexically(self) -> None:
        with tempfile.TemporaryDirectory() as parent_text:
            parent = Path(parent_text)
            root = parent / "project"
            source = root / "scripts" / "inside.gml"
            source.parent.mkdir(parents=True)
            source.write_text("return 1;", encoding="utf-8")

            for source_path in (
                "../project/scripts/inside.gml",
                "sprites/../../project/scripts/inside.gml",
            ):
                with self.subTest(source_path=source_path):
                    with self.assertRaisesRegex(
                        ProjectSourcePathError,
                        "escapes the selected GameMaker project root through traversal",
                    ):
                        resolve_project_source_path(root, source_path)

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

    def test_resolves_owner_relative_and_project_relative_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            owner = root / "rooms" / "r_test" / "r_test.yy"
            owner.parent.mkdir(parents=True)
            owner.write_text("{}", encoding="utf-8")
            room_code = owner.parent / "RoomCreationCode.gml"
            room_code.write_text("show_debug_message('room')", encoding="utf-8")
            script = root / "scripts" / "scr_test" / "scr_test.gml"
            script.parent.mkdir(parents=True)
            script.write_text("return 1;", encoding="utf-8")

            owner_relative = resolve_project_sidecar_source_path(
                root,
                "rooms/r_test/r_test.yy",
                "RoomCreationCode.gml",
            )
            rooted = resolve_project_sidecar_source_path(
                root,
                owner,
                "scripts/scr_test/scr_test.gml",
            )
            placeholder = resolve_project_sidecar_source_path(
                root,
                owner,
                "${project_dir}/scripts/scr_test/scr_test.gml",
            )
            other_resource_root = resolve_project_sidecar_source_path(
                root,
                owner,
                "materials/m_world/m_world.yy",
            )
            config_root = resolve_project_sidecar_source_path(
                root,
                owner,
                "configs/Default/config.yy",
            )

            self.assertEqual(owner_relative.source_path, "rooms/r_test/RoomCreationCode.gml")
            self.assertEqual(rooted.filesystem_path, os.path.abspath(script))
            self.assertEqual(placeholder.filesystem_path, os.path.abspath(script))
            self.assertEqual(
                other_resource_root.source_path,
                "materials/m_world/m_world.yy",
            )
            self.assertEqual(
                config_root.source_path,
                "configs/Default/config.yy",
            )

    def test_rejects_unsafe_sidecar_forms_before_owner_composition(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            unsafe_paths = (
                "../../../outside.gml",
                "/tmp/outside.gml",
                r"C:\Games\Outside\outside.gml",
                r"C:Outside\outside.gml",
                r"\\server\share\outside.gml",
                "bad\0path.gml",
            )
            for sidecar_path in unsafe_paths:
                with self.subTest(sidecar_path=sidecar_path):
                    with self.assertRaises(ProjectSourcePathError):
                        resolve_project_sidecar_source_path(
                            root,
                            "rooms/r_test/r_test.yy",
                            sidecar_path,
                        )

    def test_revalidates_discovered_file_symlinks(self) -> None:
        with (
            tempfile.TemporaryDirectory() as parent_text,
            tempfile.TemporaryDirectory() as outside_text,
        ):
            parent = Path(parent_text)
            root = parent / "project"
            root.mkdir()
            inside = root / "scripts" / "inside.gml"
            inside.parent.mkdir()
            inside.write_text("return 1;", encoding="utf-8")
            outside = Path(outside_text) / "outside.gml"
            outside.write_text("return 2;", encoding="utf-8")
            try:
                inside_link = root / "inside_link.gml"
                inside_link.symlink_to(inside)
                outside_link = root / "outside_link.gml"
                outside_link.symlink_to(outside)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            resolved_inside = resolve_project_filesystem_source_path(root, inside_link)
            self.assertEqual(
                os.path.realpath(resolved_inside.filesystem_path),
                os.path.realpath(inside),
            )
            with self.assertRaisesRegex(ProjectSourcePathError, "symbolic link"):
                resolve_project_filesystem_source_path(root, outside_link)

    def test_revalidates_canonical_candidate_under_symlinked_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as parent_text:
            parent = Path(parent_text)
            canonical_root = parent / "canonical_project"
            source = canonical_root / "scripts" / "inside.gml"
            source.parent.mkdir(parents=True)
            source.write_text("return 1;", encoding="utf-8")
            selected_root = parent / "selected_project"
            try:
                selected_root.symlink_to(canonical_root, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            resolved = resolve_project_filesystem_source_path(
                selected_root,
                source,
            )

            self.assertEqual(resolved.source_path, "scripts/inside.gml")
            self.assertEqual(
                os.path.realpath(resolved.filesystem_path),
                os.path.realpath(source),
            )

    @unittest.skipIf(os.sep == "\\", "Backslash is a native separator on Windows")
    def test_rejects_discovered_literal_backslash_instead_of_redirecting(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            listed_path = root / "extensions" / "evil\\name.yy"
            redirected_path = root / "extensions" / "evil" / "name.yy"
            listed_path.parent.mkdir(parents=True)
            redirected_path.parent.mkdir(parents=True)
            listed_path.write_text('{"name":"listed"}', encoding="utf-8")
            redirected_path.write_text('{"name":"redirected"}', encoding="utf-8")

            with self.assertRaisesRegex(
                ProjectSourcePathError,
                "host-literal backslash",
            ):
                resolve_project_filesystem_source_path(root, listed_path)

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

    def test_gml_enumeration_rejects_cross_kind_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            (root / "Project.yyp").write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "id": {
                                    "name": "scr_live",
                                    "path": (
                                        "scripts/legacy/../scr_live/scr_live.yy"
                                    ),
                                }
                            },
                            {
                                "id": {
                                    "name": "scr_cross",
                                    "path": (
                                        "scripts/../objects/scr_cross/scr_cross.yy"
                                    ),
                                }
                            },
                        ],
                        "RoomOrderNodes": [],
                        "resourceType": "GMProject",
                    }
                ),
                encoding="utf-8",
            )
            live_dir = root / "scripts" / "scr_live"
            live_dir.mkdir(parents=True)
            (live_dir / "scr_live.yy").write_text(
                json.dumps({"name": "scr_live", "resourceType": "GMScript"}),
                encoding="utf-8",
            )
            (live_dir / "scr_live.gml").write_text("return 1;\n", encoding="utf-8")
            cross_dir = root / "objects" / "scr_cross"
            cross_dir.mkdir(parents=True)
            (cross_dir / "scr_cross.yy").write_text(
                json.dumps({"name": "scr_cross", "resourceType": "GMScript"}),
                encoding="utf-8",
            )
            (cross_dir / "scr_cross.gml").write_text(
                "return 2;\n",
                encoding="utf-8",
            )

            source_paths = tuple(
                source.source_path for source in project_gml_source_paths(root)
            )

        self.assertEqual(source_paths, ("scripts/scr_live/scr_live.gml",))

    def test_derived_sidecar_names_cannot_leave_their_owner_directory(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            (root / "Project.yyp").write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "id": {
                                    "name": "../leaked",
                                    "path": "scripts/owner/custom.yy",
                                }
                            },
                            {
                                "id": {
                                    "name": "r_owner",
                                    "path": "rooms/r_owner/r_owner.yy",
                                }
                            },
                        ],
                        "RoomOrderNodes": [],
                        "resourceType": "GMProject",
                    }
                ),
                encoding="utf-8",
            )
            script_dir = root / "scripts" / "owner"
            script_dir.mkdir(parents=True)
            (script_dir / "custom.yy").write_text(
                json.dumps(
                    {
                        "name": "../leaked",
                        "resourceType": "GMScript",
                    }
                ),
                encoding="utf-8",
            )
            (root / "scripts" / "leaked.gml").write_text(
                "#macro LEAKED_SCRIPT 1\n",
                encoding="utf-8",
            )
            room_dir = root / "rooms" / "r_owner"
            room_dir.mkdir(parents=True)
            (room_dir / "r_owner.yy").write_text(
                json.dumps(
                    {
                        "name": "r_owner",
                        "resourceType": "GMRoom",
                        "layers": [
                            {
                                "instances": [
                                    {
                                        "name": "/../../shared/Leak",
                                        "hasCreationCode": True,
                                    }
                                ]
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            leaked_room_code = root / "rooms" / "shared" / "Leak.gml"
            leaked_room_code.parent.mkdir(parents=True)
            leaked_room_code.write_text(
                "#macro LEAKED_ROOM 1\n",
                encoding="utf-8",
            )

            source_paths = tuple(
                source.source_path for source in project_gml_source_paths(root)
            )

        self.assertEqual(source_paths, ())


if __name__ == "__main__":
    unittest.main()
