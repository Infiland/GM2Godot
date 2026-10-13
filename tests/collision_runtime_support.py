"""Project fixtures shared by the GameMaker collision and motion Godot tests.

The tests build small Godot projects holding the GML runtime, sprite scenes in
the format the sprite converter writes (GameMaker size, origin, bounding box
and collision kind as metadata, precise masks as rectangles) and an asset
registry, then run a GDScript smoke scene from tests/fixtures/collision_runtime.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.conversion.asset_registry import (
    AssetRegistryEntry,
    render_asset_registry_script,
)
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.script_generator import (
    ObjectRuntimeConfig,
    SpriteRuntimeConfig,
    generate_script_content,
)
from tests.godot_test_support import write_fixture_text

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "collision_runtime"
SMOKE_TIMEOUT_SECONDS = 90

_SMOKE_SCENE = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://smoke.gd" id="1"]\n\n'
    '[node name="Smoke" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)


@dataclass(frozen=True)
class MaskRect:
    """An opaque rectangle of a precise mask, in sprite pixels."""

    x: int
    y: int
    width: int
    height: int
    frame: int | None = None


@dataclass(frozen=True)
class CollisionSprite:
    """A GameMaker sprite reduced to what collisions read."""

    name: str
    width: int
    height: int
    origin: tuple[int, int]
    bbox: tuple[int, int, int, int]
    collision_kind: int = 1
    mask_rects: tuple[MaskRect, ...] = ()
    frame_count: int = 1


def sprite_scene(sprite: CollisionSprite) -> str:
    """Render a sprite scene the way the sprite converter lays it out."""
    origin_x, origin_y = sprite.origin
    left, top, right, bottom = sprite.bbox
    shape_ids: dict[tuple[int, int], str] = {}
    sub_resources: list[str] = []
    for rect in sprite.mask_rects:
        size = (rect.width, rect.height)
        if size not in shape_ids:
            shape_ids[size] = f"RectangleShape2D_{len(shape_ids) + 1}"
            sub_resources.append(
                f'[sub_resource type="RectangleShape2D" id="{shape_ids[size]}"]\n'
                f"size = Vector2({rect.width}, {rect.height})\n\n"
            )
    root = [
        f'[node name="{sprite.name}" type="Area2D"]\n',
        f"metadata/gamemaker_width = {sprite.width}\n",
        f"metadata/gamemaker_height = {sprite.height}\n",
        f"metadata/gamemaker_origin_x = {origin_x}\n",
        f"metadata/gamemaker_origin_y = {origin_y}\n",
        f"metadata/gamemaker_collision_kind = {sprite.collision_kind}\n",
        "metadata/gamemaker_collision_tolerance = 0\n",
        f"metadata/gamemaker_bbox_left = {left}\n",
        f"metadata/gamemaker_bbox_right = {right}\n",
        f"metadata/gamemaker_bbox_top = {top}\n",
        f"metadata/gamemaker_bbox_bottom = {bottom}\n",
    ]
    if sprite.frame_count > 1:
        root.append(f"metadata/gamemaker_mask_frame_count = {sprite.frame_count}\n")
    nodes = ['\n[node name="Sprite2D" type="Sprite2D" parent="."]\n']
    for index, rect in enumerate(sprite.mask_rects, start=1):
        center_x = rect.x + rect.width / 2 - origin_x
        center_y = rect.y + rect.height / 2 - origin_y
        node = [
            f'\n[node name="PreciseMask{index}" type="CollisionShape2D" parent="."]\n',
            f"position = Vector2({center_x}, {center_y})\n",
            f'shape = SubResource("{shape_ids[(rect.width, rect.height)]}")\n',
        ]
        if rect.frame is not None:
            node.append(f"metadata/gamemaker_mask_frame = {rect.frame}\n")
        node.append("metadata/gamemaker_precise_mask = true\n")
        nodes.append("".join(node))
    return "[gd_scene format=3]\n\n" + "".join(sub_resources) + "".join(root) + "".join(nodes)


def sprite_entry(asset_id: int, name: str) -> AssetRegistryEntry:
    source_path = f"sprites/{name}/{name}.yy"
    return AssetRegistryEntry(
        id=asset_id,
        name=name,
        kind="sprites",
        asset_type="sprite",
        type_name="Sprite",
        source_path=source_path,
        godot_path=sprite_resource_path(name),
        legacy_id=source_path,
    )


def object_entry(asset_id: int, name: str, godot_path: str = "") -> AssetRegistryEntry:
    source_path = f"objects/{name}/{name}.yy"
    return AssetRegistryEntry(
        id=asset_id,
        name=name,
        kind="objects",
        asset_type="object",
        type_name="Object",
        source_path=source_path,
        godot_path=godot_path,
        legacy_id=source_path,
    )


def sprite_resource_path(name: str) -> str:
    return f"res://sprites/{name}/{name}.tscn"


def object_scene_path(name: str) -> str:
    return f"res://objects/{name}/{name}.tscn"


def write_generated_object(
    project_dir: Path,
    name: str,
    sprite: CollisionSprite | None,
    *,
    solid: bool = False,
    mask_sprite_name: str | None = None,
    parent_object_names: tuple[str, ...] = (),
    other_sprite_names: tuple[str, ...] = (),
) -> None:
    """Write a converted object without events: its script and its scene.

    The scene holds the object's sprite (if it has one) as a child, as
    converted objects do, so ``instance_create_*`` can instantiate it from the
    asset registry. ``other_sprite_names`` are further sprites the object's
    script can switch to, as the converter lists every sprite of the project.
    """
    sprite_names = ((sprite.name,) if sprite is not None else ()) + other_sprite_names
    object_dir = project_dir / "objects" / name
    write_fixture_text(
        object_dir / f"{name}.gd",
        generate_script_content(
            [],
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name=sprite.name if sprite is not None else None,
                sprite_scene_paths={sprite_name: sprite_resource_path(sprite_name) for sprite_name in sprite_names},
            ),
            object_runtime=ObjectRuntimeConfig(
                object_name=name,
                parent_object_names=parent_object_names,
                solid=solid,
                mask_sprite_name=mask_sprite_name,
            ),
        ),
    )
    script_resource = f'[ext_resource type="Script" path="res://objects/{name}/{name}.gd" id="2"]\n\n'
    root_node = f'[node name="{name}" type="Node2D"]\nscript = ExtResource("2")\n'
    if sprite is None:
        write_fixture_text(
            object_dir / f"{name}.tscn",
            "[gd_scene load_steps=2 format=3]\n\n" + script_resource + root_node,
        )
        return
    write_fixture_text(
        object_dir / f"{name}.tscn",
        "[gd_scene load_steps=3 format=3]\n\n"
        f'[ext_resource type="PackedScene" path="{sprite_resource_path(sprite.name)}" id="1"]\n\n'
        + script_resource
        + root_node
        + f'\n[node name="{sprite.name}" parent="." instance=ExtResource("1")]\n',
    )


def write_collision_project(
    project_dir: Path,
    *,
    project_name: str,
    sprites: Sequence[CollisionSprite],
    objects: Sequence[AssetRegistryEntry],
    fixture_files: Mapping[str, str],
    application_settings: str = "",
) -> None:
    """Write a runnable project whose main scene runs ``smoke.gd``.

    ``fixture_files`` maps project paths to files in the collision_runtime
    fixture directory; it must provide ``smoke.gd``.
    """
    write_fixture_text(
        project_dir / "project.godot",
        "[application]\n"
        f'config/name="{project_name}"\n'
        'run/main_scene="res://smoke.tscn"\n'
        f"{application_settings}",
    )
    write_gml_runtime(str(project_dir))
    entries: list[AssetRegistryEntry] = []
    for index, sprite in enumerate(sprites, start=1):
        write_fixture_text(
            project_dir / "sprites" / sprite.name / f"{sprite.name}.tscn",
            sprite_scene(sprite),
        )
        entries.append(sprite_entry(index, sprite.name))
    entries.extend(objects)
    write_smoke_files(project_dir, entries, fixture_files)


def write_smoke_files(
    project_dir: Path,
    registry_entries: Sequence[AssetRegistryEntry],
    fixture_files: Mapping[str, str],
) -> None:
    """Write the asset registry, the fixture scripts and the smoke scene."""
    write_fixture_text(
        project_dir / "gm2godot" / "gml_asset_registry.gd",
        render_asset_registry_script(tuple(registry_entries)),
    )
    for project_path, fixture_name in fixture_files.items():
        destination = project_dir / project_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE_DIR / fixture_name, destination)
    write_fixture_text(project_dir / "smoke.tscn", _SMOKE_SCENE)


def run_smoke_scene(godot_binary: str, project_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["HOME"] = str(project_dir)
    return subprocess.run(
        [
            godot_binary,
            "--headless",
            "--log-file",
            str(project_dir / "godot.log"),
            "--path",
            str(project_dir),
            "--scene",
            "res://smoke.tscn",
            "--quit-after",
            "30",
        ],
        capture_output=True,
        text=True,
        timeout=SMOKE_TIMEOUT_SECONDS,
        check=False,
        env=environment,
    )
