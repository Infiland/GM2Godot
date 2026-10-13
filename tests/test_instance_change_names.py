from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from src.conversion.instance_change_names import (
    InstanceChangeNames,
    collect_instance_change_names,
)
from src.conversion.project_macros import collect_project_macro_values


class TestInstanceChangeNames(unittest.TestCase):
    """The project's script functions and macros that run instance_change."""

    def setUp(self) -> None:
        self.project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.project)

    def _write_project(self, scripts: dict[str, str], objects: dict[str, str] | None = None) -> None:
        resources: list[dict[str, dict[str, str]]] = []
        for name, source in scripts.items():
            script_dir = os.path.join(self.project, "scripts", name)
            os.makedirs(script_dir)
            with open(os.path.join(script_dir, f"{name}.yy"), "w", encoding="utf-8") as f:
                json.dump({"name": name, "resourceType": "GMScript"}, f)
            with open(os.path.join(script_dir, f"{name}.gml"), "w", encoding="utf-8") as f:
                f.write(source)
            resources.append({"id": {"name": name, "path": f"scripts/{name}/{name}.yy"}})
        for name, source in (objects or {}).items():
            object_dir = os.path.join(self.project, "objects", name)
            os.makedirs(object_dir)
            with open(os.path.join(object_dir, f"{name}.yy"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": name,
                        "resourceType": "GMObject",
                        "eventList": [{"eventType": 0, "eventNum": 0, "resourceType": "GMEvent"}],
                    },
                    f,
                )
            with open(os.path.join(object_dir, "Create_0.gml"), "w", encoding="utf-8") as f:
                f.write(source)
            resources.append({"id": {"name": name, "path": f"objects/{name}/{name}.yy"}})
        with open(os.path.join(self.project, "Test.yyp"), "w", encoding="utf-8") as f:
            json.dump({"resources": resources, "RoomOrderNodes": [], "resourceType": "GMProject"}, f)

    def _collect(self, macro_configuration: str | None = None) -> InstanceChangeNames:
        return collect_instance_change_names(
            self.project,
            macro_configuration=macro_configuration,
            macro_values=collect_project_macro_values(self.project, macro_configuration=macro_configuration),
        )

    def test_functions_that_call_instance_change_are_found_through_other_functions(self) -> None:
        self._write_project(
            {
                "scr_change": "function scr_change(_o) { instance_change(_o, true); }\n"
                "function scr_quiet() { return 1; }\n",
                "scr_wrap": "function scr_wrap(_o) {\n    if (_o != noone) scr_change(_o);\n}\n"
                "function scr_wrap_twice(_o) { scr_wrap(_o); scr_wrap(_o); }\n",
            }
        )

        names = self._collect()

        self.assertEqual(names.functions, {"scr_change", "scr_wrap", "scr_wrap_twice"})
        self.assertEqual(names.macros, frozenset())

    def test_macros_and_the_functions_that_use_them_are_found_together(self) -> None:
        self._write_project(
            {
                "macros": "#macro BECOME instance_change(o_b, true)\n"
                "#macro BECOME_TWICE BECOME; BECOME\n"
                "#macro MAX_HP 5\n"
                "#macro OTHER scr_via_macro()\n",
                "scr_via_macro": "function scr_via_macro() { BECOME_TWICE; }\n",
            }
        )

        names = self._collect()

        self.assertEqual(names.macros, {"BECOME", "BECOME_TWICE", "OTHER"})
        self.assertEqual(names.functions, {"scr_via_macro"})

    def test_a_script_without_function_declarations_is_a_function_of_the_script_name(self) -> None:
        self._write_project({"scr_old": "instance_change(argument0, true);\n", "scr_old_call": "scr_old(o_b);\n"})

        names = self._collect()

        self.assertEqual(names.functions, {"scr_old", "scr_old_call"})

    def test_defining_a_function_or_naming_a_member_does_not_run_instance_change(self) -> None:
        self._write_project(
            {
                "scr_defines": "function scr_defines() constructor {\n"
                "    static change = function(_o) { instance_change(_o, true); };\n"
                "    callback = function() { instance_change(o_b, true); };\n"
                "}\n",
                "scr_members": "function scr_members(_o) { _o.instance_change(1); other.scr_unrelated(); return 1; }\n"
                "function scr_unrelated() { return 2; }\n",
                "scr_mentions": "function scr_mentions() { var instance_change_count = 3; return \"instance_change(\"; }\n",
            }
        )

        names = self._collect()

        self.assertEqual(names, InstanceChangeNames())

    def test_objects_do_not_define_functions_but_their_macros_count(self) -> None:
        self._write_project(
            {"scr_call": "function scr_call() { LOCAL_BECOME; }\n"},
            objects={"o_a": "#macro LOCAL_BECOME instance_change(o_a, false)\n"},
        )

        names = self._collect()

        self.assertEqual(names.macros, {"LOCAL_BECOME"})
        self.assertEqual(names.functions, {"scr_call"})

    def test_a_macro_of_another_configuration_is_not_used(self) -> None:
        self._write_project(
            {
                "macros": "#macro Debug:BECOME instance_change(o_b, true)\n"
                "#macro BECOME 0\n"
                "function scr_use() { BECOME; }\n",
            }
        )

        self.assertEqual(self._collect("Release").macros, frozenset())
        self.assertEqual(self._collect("Debug").macros, {"BECOME"})
        self.assertEqual(self._collect("Debug").functions, {"scr_use"})

    def test_a_project_without_sources_has_no_names(self) -> None:
        self.assertEqual(self._collect(), InstanceChangeNames())
        self.assertEqual(
            collect_instance_change_names(self.project, macro_values={"BECOME": "instance_change(o_b, true)"}),
            InstanceChangeNames(macros=frozenset({"BECOME"})),
        )


if __name__ == "__main__":
    unittest.main()
