from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import TypedDict, cast

from PIL import Image

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.sprites import SpriteConverter


_EXPECTED_GODOT_VERSION = "4.7.1.stable.official.a13da4feb"
_FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "precise_collision_masks"
    / "fixture.json"
)


class _SpriteSpec(TypedDict):
    name: str
    collision_kind: int
    frame_indices: list[int]


class _FixtureSpec(TypedDict):
    width: int
    height: int
    origin: list[int]
    collision_tolerance: int
    frames: list[list[str]]
    sprites: list[_SpriteSpec]


def _find_godot_binary() -> str | None:
    configured = os.environ.get("GODOT_BIN")
    if configured and os.path.isfile(configured):
        return configured
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


def _load_fixture() -> _FixtureSpec:
    return cast(
        _FixtureSpec,
        json.loads(_FIXTURE_PATH.read_text(encoding="utf-8")),
    )


def _write_frame(path: Path, rows: list[str]) -> None:
    image = Image.new("RGBA", (len(rows[0]), len(rows)), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            if value == "#":
                image.putpixel((x, y), (255, 255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_gamemaker_fixture(project_dir: Path, fixture: _FixtureSpec) -> None:
    resources: list[dict[str, object]] = []
    origin_x, origin_y = fixture["origin"]
    for sprite in fixture["sprites"]:
        name = sprite["name"]
        resources.append(
            {
                "id": {
                    "name": name,
                    "path": f"sprites/{name}/{name}.yy",
                    "resourceType": "GMSprite",
                },
                "resourceType": "GMSprite",
            }
        )
        frame_entries: list[dict[str, object]] = []
        keyframes: list[dict[str, object]] = []
        layer_name = f"{name}_layer"
        for output_index, fixture_frame_index in enumerate(
            sprite["frame_indices"]
        ):
            frame_name = f"{name}_frame_{output_index}"
            frame_entries.append(
                {
                    "$GMSpriteFrame": "v1",
                    "name": frame_name,
                    "resourceType": "GMSpriteFrame",
                    "resourceVersion": "2.0",
                }
            )
            keyframes.append(
                {
                    "Key": float(output_index),
                    "Length": 1.0,
                    "Channels": {"0": {"Id": {"name": frame_name}}},
                }
            )
            _write_frame(
                project_dir
                / "sprites"
                / name
                / "layers"
                / frame_name
                / f"{layer_name}.png",
                fixture["frames"][fixture_frame_index],
            )

        yy = {
            "$GMSprite": "v2",
            "name": name,
            "resourceType": "GMSprite",
            "resourceVersion": "2.0",
            "width": fixture["width"],
            "height": fixture["height"],
            "origin": 9,
            "bboxMode": 2,
            "bbox_left": 0,
            "bbox_right": fixture["width"] - 1,
            "bbox_top": 0,
            "bbox_bottom": fixture["height"] - 1,
            "collisionKind": sprite["collision_kind"],
            "collisionTolerance": fixture["collision_tolerance"],
            "frames": frame_entries,
            "layers": [
                {
                    "$GMImageLayer": "",
                    "name": layer_name,
                    "visible": True,
                    "resourceType": "GMImageLayer",
                    "resourceVersion": "2.0",
                }
            ],
            "sequence": {
                "xorigin": origin_x,
                "yorigin": origin_y,
                "playbackSpeed": 0.0,
                "playbackSpeedType": 0,
                "playback": 1,
                "tracks": [{"keyframes": {"Keyframes": keyframes}}],
            },
        }
        _write_text(
            project_dir / "sprites" / name / f"{name}.yy",
            json.dumps(yy, indent=2) + "\n",
        )

    _write_text(
        project_dir / "PreciseCollisionMasks.yyp",
        json.dumps(
            {
                "%Name": "PreciseCollisionMasks",
                "resourceType": "GMProject",
                "resourceVersion": "2.0",
                "resources": resources,
            },
            indent=2,
        )
        + "\n",
    )


def _write_godot_probe(project_dir: Path) -> None:
    actor_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var id = GMRuntime.gml_instance_noone()
        var other = GMRuntime.gml_instance_noone()
        var object_name = ""
        var hits = 0

        func configure(gm_object_name):
        \tobject_name = gm_object_name

        func _ready():
        \tid = GMRuntime.gml_instance_register(self, object_name)

        func _gm_collision_event_bindings():
        \tif object_name != "subject":
        \t\treturn []
        \treturn [{"target_object": "target", "method": "_on_collision_target"}]

        func _on_collision_target():
        \thits += 1
        """
    )
    smoke_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const Actor = preload("res://collision_actor.gd")

        func _check(condition, message):
        \tif condition:
        \t\treturn true
        \tpush_error(str(message))
        \tget_tree().quit(1)
        \treturn false

        func _spawn_sprite(path, object_name, world_position):
        \tvar sprite = load(path).instantiate()
        \tsprite.position = world_position
        \tadd_child(sprite)
        \tvar handle = GMRuntime.gml_instance_register(sprite, object_name)
        \treturn {"instance": sprite, "handle": handle}

        func _ready():
        \tvar rectangle = _spawn_sprite(
        \t\t"res://sprites/spr_rectangle/spr_rectangle.tscn",
        \t\t"rectangle",
        \t\tVector2(10, 20)
        \t)
        \tvar rectangle_point = rectangle["instance"].to_global(Vector2(0.5, 0.5))
        \tif not _check(
        \t\tGMRuntime.gml_handle_is_valid(
        \t\t\tGMRuntime.gml_collision_point(
        \t\t\t\trectangle["instance"],
        \t\t\t\trectangle_point.x,
        \t\t\t\trectangle_point.y,
        \t\t\t\trectangle["handle"],
        \t\t\t\ttrue,
        \t\t\t\tfalse
        \t\t\t)
        \t\t),
        \t\t"rectangle mask did not include a transparent source pixel"
        \t):
        \t\treturn

        \tvar precise = _spawn_sprite(
        \t\t"res://sprites/spr_precise_static/spr_precise_static.tscn",
        \t\t"precise_static",
        \t\tVector2(30, 20)
        \t)
        \tprecise["instance"].scale = Vector2(2, 1)
        \tprecise["instance"].rotation_degrees = 90
        \tvar first_pixel = precise["instance"].to_global(Vector2(-1.5, -1.5))
        \tvar last_pixel = precise["instance"].to_global(Vector2(1.5, 1.5))
        \tvar transparent_pixel = precise["instance"].to_global(Vector2(0.5, 0.5))
        \tfor opaque_point in [first_pixel, last_pixel]:
        \t\tif not _check(
        \t\t\tGMRuntime.gml_handle_is_valid(
        \t\t\t\tGMRuntime.gml_collision_point(
        \t\t\t\t\tprecise["instance"],
        \t\t\t\t\topaque_point.x,
        \t\t\t\t\topaque_point.y,
        \t\t\t\t\tprecise["handle"],
        \t\t\t\t\ttrue,
        \t\t\t\t\tfalse
        \t\t\t\t)
        \t\t\t),
        \t\t\t"static precise mask did not composite or transform an opaque frame pixel"
        \t\t):
        \t\t\treturn
        \tif not _check(
        \t\tnot GMRuntime.gml_handle_is_valid(
        \t\t\tGMRuntime.gml_collision_point(
        \t\t\t\tprecise["instance"],
        \t\t\t\ttransparent_pixel.x,
        \t\t\t\ttransparent_pixel.y,
        \t\t\t\tprecise["handle"],
        \t\t\t\ttrue,
        \t\t\t\tfalse
        \t\t\t)
        \t\t),
        \t\t"precise query used the bounding rectangle"
        \t):
        \t\treturn
        \tif not _check(
        \t\tGMRuntime.gml_handle_is_valid(
        \t\t\tGMRuntime.gml_collision_point(
        \t\t\t\tprecise["instance"],
        \t\t\t\ttransparent_pixel.x,
        \t\t\t\ttransparent_pixel.y,
        \t\t\t\tprecise["handle"],
        \t\t\t\tfalse,
        \t\t\t\tfalse
        \t\t\t)
        \t\t),
        \t\t"non-precise query did not use the transformed mask bounds"
        \t):
        \t\treturn

        \tvar subject = Actor.new()
        \tsubject.configure("subject")
        \tsubject.position = Vector2(60, 20)
        \tvar per_frame_mask = load(
        \t\t"res://sprites/spr_precise_per_frame/spr_precise_per_frame.tscn"
        \t).instantiate()
        \tsubject.add_child(per_frame_mask)
        \tadd_child(subject)
        \tvar visual = per_frame_mask.get_node("AnimatedSprite2D")
        \tvisual.pause()
        \tvisual.frame = 0

        \tvar target = Actor.new()
        \ttarget.configure("target")
        \ttarget.position = Vector2(61.5, 21.5)
        \tvar target_shape = CollisionShape2D.new()
        \tvar target_rectangle = RectangleShape2D.new()
        \ttarget_rectangle.size = Vector2(0.5, 0.5)
        \ttarget_shape.shape = target_rectangle
        \ttarget.add_child(target_shape)
        \tadd_child(target)

        \tif not _check(
        \t\tnot GMRuntime.gml_handle_is_valid(
        \t\t\tGMRuntime.gml_collision_point(
        \t\t\t\tsubject,
        \t\t\t\ttarget.position.x,
        \t\t\t\ttarget.position.y,
        \t\t\t\tsubject.id,
        \t\t\t\ttrue,
        \t\t\t\tfalse
        \t\t\t)
        \t\t),
        \t\t"per-frame mask exposed a pixel from the inactive frame"
        \t):
        \t\treturn
        \tif not _check(
        \t\tGMRuntime.gml_collision_event_dispatch_frame([subject, target], 1) == 0,
        \t\t"collision event used an inactive per-frame mask"
        \t):
        \t\treturn

        \tvisual.frame = 1
        \tif not _check(
        \t\tGMRuntime.gml_handle_is_valid(
        \t\t\tGMRuntime.gml_collision_point(
        \t\t\t\tsubject,
        \t\t\t\ttarget.position.x,
        \t\t\t\ttarget.position.y,
        \t\t\t\tsubject.id,
        \t\t\t\ttrue,
        \t\t\t\tfalse
        \t\t\t)
        \t\t),
        \t\t"image frame change did not activate its precise mask"
        \t):
        \t\treturn
        \tif not _check(
        \t\tGMRuntime.gml_collision_event_dispatch_frame([subject, target], 2) == 1,
        \t\t"collision event and precise query did not share the active mask"
        \t):
        \t\treturn
        \tif not _check(subject.hits == 1, "collision callback was not dispatched once"):
        \t\treturn

        \tprint("PRECISE_COLLISION_MASKS_OK")
        \tget_tree().quit(0)
        """
    )
    smoke_scene = textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://smoke.gd" id="1"]

        [node name="Smoke" type="Node2D"]
        script = ExtResource("1")
        """
    )
    _write_text(project_dir / "collision_actor.gd", actor_script)
    _write_text(project_dir / "smoke.gd", smoke_script)
    _write_text(project_dir / "smoke.tscn", smoke_scene)


class TestPreciseCollisionMasksGodot(unittest.TestCase):
    def test_rectangle_static_and_per_frame_masks_have_distinct_outcomes(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        version_result = subprocess.run(
            [godot_binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stderr)
        if version_result.stdout.strip() != _EXPECTED_GODOT_VERSION:
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gamemaker_dir = root / "gamemaker"
            godot_dir = root / "godot"
            gamemaker_dir.mkdir()
            godot_dir.mkdir()
            _write_gamemaker_fixture(gamemaker_dir, _load_fixture())

            logs: list[str] = []
            converter = SpriteConverter(
                str(gamemaker_dir),
                str(godot_dir),
                log_callback=logs.append,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
            )
            converter.convert_all()
            self.assertFalse(
                any("fallback" in message.lower() for message in logs),
                "\n".join(logs),
            )

            _write_text(
                godot_dir / "project.godot",
                (
                    '[application]\nconfig/name="PreciseCollisionMasks"\n'
                    'run/main_scene="res://smoke.tscn"\n'
                ),
            )
            write_gml_runtime(str(godot_dir))
            _write_godot_probe(godot_dir)

            godot_environment = dict(os.environ)
            godot_environment["HOME"] = str(root / "home")
            import_result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--recovery-mode",
                    "--path",
                    str(godot_dir),
                    "--import",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=godot_environment,
            )
            import_output = import_result.stdout + import_result.stderr
            self.assertEqual(import_result.returncode, 0, import_output)
            self.assertNotIn("SCRIPT ERROR:", import_output)
            self.assertNotIn("ERROR:", import_output)
            self.assertNotIn("WARNING:", import_output)
            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--log-file",
                    str(root / "godot.log"),
                    "--path",
                    str(godot_dir),
                    "--scene",
                    "res://smoke.tscn",
                    "--quit-after",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=godot_environment,
            )
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn(_EXPECTED_GODOT_VERSION, output)
        self.assertIn("PRECISE_COLLISION_MASKS_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
