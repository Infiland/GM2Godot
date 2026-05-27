from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime


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


class TestMathRandomGodotSmoke(unittest.TestCase):
    def test_math_helpers_and_seeded_random_are_deterministic(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _near(actual, expected, message):
            \treturn _check(abs(float(actual) - float(expected)) <= 0.0001, str(message) + ": " + str(actual))

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tif not _check(GMRuntime.gml_abs(-7) == 7, "abs mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_sign(-7) == -1, "sign mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_floor(1.75) == 1, "floor mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_ceil(1.25) == 2, "ceil mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_round(1.5) == 2, "round mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_frac(3.25), 0.25, "frac mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_clamp(8, 0, 5) == 5, "clamp mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_lerp(10, 20, 0.25), 12.5, "lerp mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_min([3, 1, 2]) == 1, "min mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_max([3, 1, 2]) == 3, "max mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_dcos(180), -1.0, "dcos mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_dsin(90), 1.0, "dsin mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_radtodeg(PI), 180.0, "radtodeg mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_degtorad(180), PI, "degtorad mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_point_distance(0, 0, 3, 4), 5.0, "point_distance mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_point_direction(0, 0, 10, 0), 0.0, "point_direction east mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_point_direction(0, 0, 0, -10), 90.0, "point_direction up mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_point_direction(0, 0, 0, 10), 270.0, "point_direction down mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_lengthdir_x(10, 60), 5.0, "lengthdir_x mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_lengthdir_y(10, 90), -10.0, "lengthdir_y mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_angle_difference(10, 350), 20.0, "angle_difference positive mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_angle_difference(350, 10), -20.0, "angle_difference negative mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_dot_product(1, 2, 3, 4) == 11, "dot_product mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_dot_product_3d(1, 2, 3, 4, 5, 6) == 32, "dot_product_3d mismatch"):
            \t\treturn

            \tGMRuntime.gml_random_set_seed(123)
            \tvar first_random = GMRuntime.gml_random(10)
            \tvar first_irandom = GMRuntime.gml_irandom(5)
            \tvar first_range = GMRuntime.gml_random_range(5, 10)
            \tvar first_irange = GMRuntime.gml_irandom_range(2, 4)
            \tvar first_choice = GMRuntime.gml_choose(["a", "b", "c"])
            \tvar first_seed = GMRuntime.gml_random_get_seed()

            \tif not _check(first_random >= 0 and first_random < 10, "random out of range"):
            \t\treturn
            \tif not _check(first_irandom >= 0 and first_irandom <= 5, "irandom out of range"):
            \t\treturn
            \tif not _check(first_range >= 5 and first_range <= 10, "random_range out of range"):
            \t\treturn
            \tif not _check(first_irange >= 2 and first_irange <= 4, "irandom_range out of range"):
            \t\treturn
            \tif not _check(first_choice in ["a", "b", "c"], "choose out of set"):
            \t\treturn

            \tGMRuntime.gml_random_set_seed(123)
            \tif not _near(GMRuntime.gml_random(10), first_random, "random seed replay mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_irandom(5) == first_irandom, "irandom seed replay mismatch"):
            \t\treturn
            \tif not _near(GMRuntime.gml_random_range(5, 10), first_range, "random_range seed replay mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_irandom_range(2, 4) == first_irange, "irandom_range seed replay mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_choose(["a", "b", "c"]) == first_choice, "choose seed replay mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_random_get_seed() == first_seed, "random_get_seed replay mismatch"):
            \t\treturn

            \tprint("MATH_RANDOM_SMOKE_OK")
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

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("MATH_RANDOM_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
