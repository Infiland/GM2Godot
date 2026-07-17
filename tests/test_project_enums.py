from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.conversion.project_enums import collect_project_enum_values


def _write_project_resources(
    project_dir: Path,
    resources: list[tuple[str, str]],
) -> None:
    entries: list[dict[str, object]] = []
    resource_types = {
        "objects": "GMObject",
        "rooms": "GMRoom",
        "scripts": "GMScript",
    }
    for kind, name in resources:
        relative_path = f"{kind}/{name}/{name}.yy"
        entries.append({"id": {"name": name, "path": relative_path}})
        yy_data: dict[str, object] = {
            "%Name": name,
            "name": name,
            "resourceType": resource_types[kind],
        }
        if kind == "objects":
            yy_data["eventList"] = [{"eventType": 0, "eventNum": 0}]
        elif kind == "rooms":
            yy_data["creationCodeFile"] = "RoomCreationCode.gml"
            yy_data["layers"] = []
        yy_path = project_dir / relative_path
        yy_path.parent.mkdir(parents=True, exist_ok=True)
        yy_path.write_text(json.dumps(yy_data), encoding="utf-8")
    (project_dir / "Project.yyp").write_text(
        json.dumps(
            {
                "resources": entries,
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            }
        ),
        encoding="utf-8",
    )


class TestProjectEnums(unittest.TestCase):
    def test_collects_nested_global_enums_and_project_macros(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            _write_project_resources(
                project_dir,
                [("scripts", "Config"), ("objects", "obj_enum")],
            )
            config_path = project_dir / "scripts" / "Config" / "Config.gml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "#macro ENUM_BASE 4\n"
                "function Config() constructor {\n"
                "    enum First { base = ENUM_BASE, next }\n"
                "}\n",
                encoding="utf-8",
            )
            dependent_path = (
                project_dir / "objects" / "obj_enum" / "Create_0.gml"
            )
            dependent_path.parent.mkdir(parents=True, exist_ok=True)
            dependent_path.write_text(
                "enum Second { inherited = First.next, following }\n",
                encoding="utf-8",
            )

            self.assertEqual(
                collect_project_enum_values(project_dir),
                {
                    "First": {"base": 4, "next": 5},
                    "Second": {"inherited": 5, "following": 6},
                },
            )

    def test_ignores_enum_text_in_comments_and_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            _write_project_resources(project_dir, [("scripts", "Example")])
            source_path = project_dir / "scripts" / "Example" / "Example.gml"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(
                '// enum Commented { nope }\nvar text = "enum String { nope }";\n'
                "enum Actual { value = 9 }\n",
                encoding="utf-8",
            )

            self.assertEqual(
                collect_project_enum_values(project_dir),
                {"Actual": {"value": 9}},
            )

    def test_ignores_orphan_enums_and_keeps_yyp_declaration_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            _write_project_resources(
                project_dir,
                [
                    ("scripts", "ZReferencedFirst"),
                    ("scripts", "AReferencedSecond"),
                ],
            )
            (
                project_dir
                / "scripts"
                / "ZReferencedFirst"
                / "ZReferencedFirst.gml"
            ).write_text("enum Choice { value = 7 }\n", encoding="utf-8")
            (
                project_dir
                / "scripts"
                / "AReferencedSecond"
                / "AReferencedSecond.gml"
            ).write_text("enum Choice { value = 8 }\n", encoding="utf-8")

            stale_sibling = (
                project_dir
                / "scripts"
                / "ZReferencedFirst"
                / "AAADeleted.gml"
            )
            stale_sibling.write_text(
                "enum Choice { value = 777 }\nenum StaleSibling { value = 1 }\n",
                encoding="utf-8",
            )
            orphan_path = project_dir / "scripts" / "AAAOrphan" / "AAAOrphan.gml"
            orphan_path.parent.mkdir(parents=True)
            orphan_path.write_text(
                "enum Choice { value = 999 }\nenum OrphanOnly { value = 1 }\n",
                encoding="utf-8",
            )

            enums = collect_project_enum_values(project_dir)

            self.assertEqual(enums["Choice"], {"value": 7})
            self.assertNotIn("StaleSibling", enums)
            self.assertNotIn("OrphanOnly", enums)


if __name__ == "__main__":
    unittest.main()
