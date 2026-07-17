from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.scripts import ScriptConverter


def _find_godot_binary() -> str | None:
    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path

    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary

    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    if os.path.isfile(mac_binary):
        return mac_binary
    return None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _resource_entry(kind: str, name: str) -> dict[str, object]:
    return {
        "id": {
            "name": name,
            "path": f"{kind}/{name}/{name}.yy",
        }
    }


def _write_gm_project(gm_dir: Path) -> None:
    _write_json(
        gm_dir / "ScriptRuntimeSmoke.yyp",
        {
            "resources": [
                _resource_entry("scripts", "scr_add"),
                _resource_entry("scripts", "scr_modern"),
                _resource_entry("scripts", "scr_context"),
                _resource_entry("scripts", "scr_static"),
                _resource_entry("scripts", "scr_constructor"),
                _resource_entry("scripts", "scr_global_constructor"),
                _resource_entry("scripts", "scr_conditional"),
            ],
            "RoomOrderNodes": [],
            "resourceType": "GMProject",
        },
    )
    for script_name in (
        "scr_add",
        "scr_modern",
        "scr_context",
        "scr_static",
        "scr_constructor",
        "scr_global_constructor",
        "scr_conditional",
    ):
        _write_json(
            gm_dir / "scripts" / script_name / f"{script_name}.yy",
            {
                "%Name": script_name,
                "name": script_name,
                "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                "resourceType": "GMScript",
            },
        )
    _write_text(gm_dir / "scripts" / "scr_add" / "scr_add.gml", "return argument0 + argument1;")
    _write_text(
        gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
        "function scr_modern(a, b = 4) { return a + b; }",
    )
    _write_text(
        gm_dir / "scripts" / "scr_context" / "scr_context.gml",
        "function scr_context(delta) { score += delta; return score; }",
    )
    _write_text(
        gm_dir / "scripts" / "scr_static" / "scr_static.gml",
        "function scr_static(delta) { static total = delta; total += 1; return total; }",
    )
    _write_text(
        gm_dir / "scripts" / "scr_constructor" / "scr_constructor.gml",
        "function scr_constructor(value = 0) constructor {\n"
        "    static operate = function(a, b) { return invert(a) + b; }\n"
        "    static invert = function(item) { return -item; }\n"
        "    amount = value;\n"
        "}\n"
        "new scr_constructor();\n",
    )
    _write_text(
        gm_dir / "scripts" / "scr_global_constructor" / "scr_global_constructor.gml",
        "global.testAnonymousGlobalConstructor = function() constructor {}\n"
        "function scr_global_constructor() constructor\n"
        "{\n"
        "    variable = 3.141;\n"
        "}\n",
    )
    _write_text(
        gm_dir / "scripts" / "scr_conditional" / "scr_conditional.gml",
        "#if Android\n"
        "function scr_conditional(value) { return value + 100; }\n"
        "#else\n"
        "function scr_conditional(value) { return value - 100; }\n"
        "#endif\n",
    )


class TestScriptRuntimeGodotSmoke(unittest.TestCase):
    def test_script_execute_legacy_arguments_and_callable_lookup(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var _parent_constructor_method = null

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _identity(value = 0):
            \treturn value

            func _parent_constructor(instance, value):
            \tGMRuntime.gml_variable_instance_set(instance, "parent_value", value)

            func _child_constructor(instance, value):
            \tGMRuntime.gml_constructor_inherit(instance, _parent_constructor_method, [value])
            \tGMRuntime.gml_variable_instance_set(instance, "child_value", value + 1)

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tvar legacy_id = GMRuntime.gml_asset_get_index("scr_add")
            \tvar modern_id = GMRuntime.gml_asset_get_index("scr_modern")
            \tvar context_id = GMRuntime.gml_asset_get_index("scr_context")
            \tvar static_id = GMRuntime.gml_asset_get_index("scr_static")
            \tvar constructor_id = GMRuntime.gml_asset_get_index("scr_constructor")
            \tvar global_constructor_id = GMRuntime.gml_asset_get_index("scr_global_constructor")
            \tvar conditional_id = GMRuntime.gml_asset_get_index("scr_conditional")

            \tif not _check(GMRuntime.gml_script_exists(legacy_id), "script_exists failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_get_name(legacy_id) == "scr_add", "script_get_name failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_execute(legacy_id, [2, 3]) == 5, "script_execute legacy args failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_call(legacy_id, [7, 8], self, self) == 15, "transpiled script-call asset id failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_argument_count() == 0, "legacy argument scope did not restore"):
            \t\treturn

            \tvar callable = GMRuntime.gml_global_function("scr_modern")
            \tif not _check(GMRuntime.gml_eq(callable, GMRuntime.gml_script_get_callable(modern_id)), "script callable identity failed"):
            \t\treturn
            \tvar callbacks = [callable]
            \tvar method_result = GMRuntime.gml_method_call(callbacks[0], [4, 6])
            \tif not _check(method_result == 10, "callable lookup did not remain method-callable: " + str(method_result)):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_execute(modern_id, [5]) == 9, "optional default argument failed"):
            \t\treturn
            \tGMRuntime.gml_variable_instance_set(self, "score", 10)
            \tif not _check(GMRuntime.gml_script_execute(context_id, [5], self, self) == 15, "caller-scoped script result failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_call(context_id, [2], self, self) == 17, "caller-scoped transpiled script call failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_variable_instance_get(self, "score") == 17, "caller-scoped script mutation failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_execute(static_id, [10]) == 11, "script static initialization failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_execute(static_id, [100]) == 12, "script static persistence failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_script_execute(conditional_id, [5]) == 105, "active conditional modern script failed"):
            \t\treturn

            \tvar constructor = GMRuntime.gml_script_get_callable(constructor_id)
            \tif not _check(GMRuntime.is_method(constructor) and constructor.is_constructor, "constructor script did not register as a constructor"):
            \t\treturn
            \tvar operate = GMRuntime.gml_selector_get(constructor_id, "operate")
            \tvar invert = GMRuntime.gml_selector_get(constructor, "invert")
            \tif not _check(GMRuntime.gml_call_value(operate, [2, 3]) == 1, "constructor static sibling call failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_call_value(invert, [4]) == -4, "constructor static invert failed"):
            \t\treturn
            \tvar constructed = GMRuntime.gml_new(constructor_id, [9])
            \tif not _check(GMRuntime.gml_variable_instance_get(constructed, "amount") == 9, "constructor asset id did not allocate an instance"):
            \t\treturn
            \tvar anonymous_constructor = GMRuntime.gml_selector_get(GMRuntime.gml_global_scope(), "testAnonymousGlobalConstructor")
            \tif not _check(GMRuntime.is_method(anonymous_constructor) and anonymous_constructor.is_constructor, "global anonymous constructor initializer did not run"):
            \t\treturn
            \tvar anonymous_instance = GMRuntime.gml_new(anonymous_constructor, [])
            \tif not _check(GMRuntime.gml_is_instanceof(anonymous_instance, anonymous_constructor), "global anonymous constructor instance mismatch"):
            \t\treturn
            \tvar global_constructor_instance = GMRuntime.gml_new(global_constructor_id, [])
            \tif not _check(is_equal_approx(GMRuntime.gml_variable_instance_get(global_constructor_instance, "variable"), 3.141), "named constructor beside global initializer failed"):
            \t\treturn

            \tvar method_a = GMRuntime.gml_method(self, Callable(self, "_identity"))
            \tvar method_b = GMRuntime.gml_method(self, Callable(self, "_identity"))
            \tvar method_c = GMRuntime.gml_method(GMRuntime.gml_struct({}), Callable(self, "_identity"))
            \tif not _check(GMRuntime.gml_eq(method_a, method_b), "bound method identity failed"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_eq(method_a, method_c), "bound method self identity failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_method_get_self(method_a) == self, "method_get_self failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_method_get_index(method_a) == Callable(self, "_identity"), "method_get_index failed"):
            \t\treturn

            \t_parent_constructor_method = GMRuntime.gml_constructor(self, Callable(self, "_parent_constructor"))
            \tvar child_constructor = GMRuntime.gml_constructor(self, Callable(self, "_child_constructor"))
            \tvar parent_static = GMRuntime.gml_static_get(_parent_constructor_method)
            \tvar child_static = GMRuntime.gml_static_get(child_constructor)
            \tGMRuntime.gml_struct_set(parent_static, "kind", "parent")
            \tGMRuntime.gml_struct_set(child_static, "kind", "child")
            \tvar instance = GMRuntime.gml_new(child_constructor, [6])
            \tif not _check(GMRuntime.gml_variable_instance_get(instance, "parent_value") == 6, "parent constructor did not run"):
            \t\treturn
            \tif not _check(GMRuntime.gml_variable_instance_get(instance, "child_value") == 7, "child constructor did not run"):
            \t\treturn
            \tif not _check(GMRuntime.gml_is_instanceof(instance, child_constructor), "child instanceof failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_is_instanceof(instance, _parent_constructor_method), "parent instanceof failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_struct_get(GMRuntime.gml_static_get(GMRuntime.gml_static_get(instance)), "kind") == "parent", "static chain parent lookup failed"):
            \t\treturn

            \tprint("SCRIPT_RUNTIME_SMOKE_OK")
            \tGMRuntime.gm2godot_runtime_shutdown()
            \tget_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as gm_tmp, tempfile.TemporaryDirectory() as godot_tmp:
            gm_dir = Path(gm_tmp)
            project_dir = Path(godot_tmp)
            _write_gm_project(gm_dir)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            AssetRegistryConverter(
                gm_dir,
                project_dir,
                macro_configuration="Android",
            ).convert_all()
            ScriptConverter(
                gm_dir,
                project_dir,
                macro_configuration="Android",
            ).convert_all()
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            try:
                result = subprocess.run(
                    [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                self.fail("Godot script runtime smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SCRIPT_RUNTIME_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
