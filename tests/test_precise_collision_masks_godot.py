from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast

from PIL import Image

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.sprites import SpriteConverter
from tests.collision_runtime_support import (
    object_entry,
    sprite_entry,
    write_smoke_files,
)
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)

_EXPECTED_GODOT_VERSION = "4.7.2.stable.official.ed1daf0bf"
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


def _write_godot_probe(project_dir: Path, fixture: _FixtureSpec) -> None:
    sprite_entries = [
        sprite_entry(index, sprite["name"])
        for index, sprite in enumerate(fixture["sprites"], start=1)
    ]
    object_entries = [
        object_entry(100 + index, name)
        for index, name in enumerate(("rectangle", "precise_static", "subject", "target"))
    ]
    write_smoke_files(
        project_dir,
        [*sprite_entries, *object_entries],
        {
            "smoke.gd": "precise_masks_smoke.gd",
            "instance.gd": "instance.gd",
            "precise_actor.gd": "precise_actor.gd",
        },
    )


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
                "Exact Godot 4.7.2 required; found "
                + version_result.stdout.strip()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gamemaker_dir = root / "gamemaker"
            godot_dir = root / "godot"
            gamemaker_dir.mkdir()
            godot_dir.mkdir()
            fixture = _load_fixture()
            _write_gamemaker_fixture(gamemaker_dir, fixture)

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
            _write_godot_probe(godot_dir, fixture)

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
                timeout=90,
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
                timeout=90,
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
