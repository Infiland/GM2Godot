from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_transpiler import (
    GMLTranspileError,
    transpile_gml_expression,
)
from src.conversion.project_macros import collect_project_macro_values


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


class TestProjectMacros(unittest.TestCase):
    def test_collects_deterministic_configuration_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            _write_project_resources(
                project_dir,
                [("scripts", "AConfig"), ("scripts", "ZDefaults")],
            )
            early_path = project_dir / "scripts" / "AConfig" / "AConfig.gml"
            early_path.parent.mkdir(parents=True, exist_ok=True)
            early_path.write_text(
                "#macro Android:BASE 7\n"
                "#macro RESULT DOUBLE + BASE\n",
                encoding="utf-8",
            )
            late_path = project_dir / "scripts" / "ZDefaults" / "ZDefaults.gml"
            late_path.parent.mkdir(parents=True, exist_ok=True)
            late_path.write_text(
                "#macro BASE 4\n"
                "#macro DOUBLE (BASE * 2)\n",
                encoding="utf-8",
            )

            default_macros = collect_project_macro_values(project_dir)
            android_macros = collect_project_macro_values(
                project_dir,
                macro_configuration="android",
            )

            self.assertEqual(default_macros["BASE"], "4")
            self.assertEqual(android_macros["BASE"], "7")
            self.assertEqual(
                transpile_gml_expression("RESULT", macro_values=default_macros),
                "GMRuntime.gml_add((GMRuntime.gml_mul(4, 2)), 4)",
            )
            self.assertEqual(
                transpile_gml_expression("RESULT", macro_values=android_macros),
                "GMRuntime.gml_add((GMRuntime.gml_mul(7, 2)), 7)",
            )

    def test_expands_recursive_cross_file_macros_and_rejects_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            _write_project_resources(
                project_dir,
                [
                    ("scripts", "Base"),
                    ("objects", "obj_example"),
                    ("scripts", "Cycle"),
                ],
            )
            base_path = project_dir / "scripts" / "Base" / "Base.gml"
            base_path.parent.mkdir(parents=True, exist_ok=True)
            base_path.write_text("#macro BASE 5\n", encoding="utf-8")
            dependent_path = (
                project_dir / "objects" / "obj_example" / "Create_0.gml"
            )
            dependent_path.parent.mkdir(parents=True, exist_ok=True)
            dependent_path.write_text(
                "#macro DOUBLE (BASE * 2)\n"
                "#macro TOTAL DOUBLE + BASE\n",
                encoding="utf-8",
            )

            macro_values = collect_project_macro_values(project_dir)

            self.assertEqual(
                transpile_gml_expression("TOTAL", macro_values=macro_values),
                "GMRuntime.gml_add((GMRuntime.gml_mul(5, 2)), 5)",
            )

            cycle_path = project_dir / "scripts" / "Cycle" / "Cycle.gml"
            cycle_path.parent.mkdir(parents=True, exist_ok=True)
            cycle_path.write_text(
                "#macro FIRST SECOND\n#macro SECOND FIRST\n",
                encoding="utf-8",
            )
            cyclic_values = collect_project_macro_values(project_dir)

            with self.assertRaisesRegex(
                GMLTranspileError,
                "Recursive macro expansion",
            ):
                transpile_gml_expression("FIRST", macro_values=cyclic_values)

    def test_ignores_orphan_macro_sources_and_keeps_yyp_override_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            _write_project_resources(
                project_dir,
                [
                    ("scripts", "ZReferencedFirst"),
                    ("rooms", "r_config"),
                    ("scripts", "AReferencedLast"),
                ],
            )
            (
                project_dir
                / "scripts"
                / "ZReferencedFirst"
                / "ZReferencedFirst.gml"
            ).write_text("#macro CONFLICT 1\n", encoding="utf-8")
            (
                project_dir
                / "scripts"
                / "AReferencedLast"
                / "AReferencedLast.gml"
            ).write_text("#macro CONFLICT 2\n", encoding="utf-8")
            (project_dir / "rooms" / "r_config" / "RoomCreationCode.gml").write_text(
                "#macro ROOM_VALUE 3\n",
                encoding="utf-8",
            )

            stale_sibling = (
                project_dir
                / "scripts"
                / "ZReferencedFirst"
                / "ZZDeleted.gml"
            )
            stale_sibling.write_text(
                "#macro CONFLICT 777\n#macro STALE_SIBLING 1\n",
                encoding="utf-8",
            )
            orphan_path = project_dir / "scripts" / "ZZOrphan" / "ZZOrphan.gml"
            orphan_path.parent.mkdir(parents=True)
            orphan_path.write_text(
                "#macro CONFLICT 999\n#macro ORPHAN_ONLY 1\n",
                encoding="utf-8",
            )

            macros = collect_project_macro_values(project_dir)

            self.assertEqual(macros["CONFLICT"], "2")
            self.assertEqual(macros["ROOM_VALUE"], "3")
            self.assertNotIn("STALE_SIBLING", macros)
            self.assertNotIn("ORPHAN_ONLY", macros)


if __name__ == "__main__":
    unittest.main()
