from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, cast

from PIL import Image

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.rooms import RoomConverter
from src.conversion.sprites import SpriteConverter


_EXPECTED_GODOT_VERSION = "4.7.1.stable.official.a13da4feb"
_FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "authored_particles"
    / "fixture.json"
)


def _find_godot_binary() -> str | None:
    configured = os.environ.get("GODOT_BIN")
    if configured and os.path.isfile(configured):
        return configured
    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary
    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    return mac_binary if os.path.isfile(mac_binary) else None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, indent=2) + "\n")


def _ignore_message(_message: str) -> None:
    return None


def _ignore_progress(_value: int | float) -> None:
    return None


def _conversion_running() -> bool:
    return True


def _load_fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(_FIXTURE_PATH.read_text(encoding="utf-8")),
    )


def _write_sprite(project_dir: Path) -> None:
    sprite_name = "spr_particle"
    frame_name = "frame_particle"
    layer_name = "layer_particle"
    sprite = {
        "$GMSprite": "v2",
        "%Name": sprite_name,
        "name": sprite_name,
        "resourceType": "GMSprite",
        "resourceVersion": "2.0",
        "width": 2,
        "height": 2,
        "origin": 0,
        "bboxMode": 0,
        "bbox_left": 0,
        "bbox_right": 1,
        "bbox_top": 0,
        "bbox_bottom": 1,
        "collisionKind": 1,
        "frames": [
            {
                "$GMSpriteFrame": "v1",
                "name": frame_name,
                "resourceType": "GMSpriteFrame",
                "resourceVersion": "2.0",
            }
        ],
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
            "xorigin": 0,
            "yorigin": 0,
            "playbackSpeed": 0.0,
            "playbackSpeedType": 0,
            "playback": 1,
            "tracks": [
                {
                    "keyframes": {
                        "Keyframes": [
                            {
                                "Key": 0.0,
                                "Length": 1.0,
                                "Channels": {"0": {"Id": {"name": frame_name}}},
                            }
                        ]
                    }
                }
            ],
        },
        "parent": {"name": "Sprites", "path": "folders/Sprites.yy"},
    }
    _write_json(
        project_dir / "sprites" / sprite_name / f"{sprite_name}.yy",
        sprite,
    )
    image_path = (
        project_dir
        / "sprites"
        / sprite_name
        / "layers"
        / frame_name
        / f"{layer_name}.png"
    )
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (2, 2), (255, 255, 255, 255))
    image.putpixel((1, 1), (255, 0, 0, 255))
    image.save(image_path)


def _write_gamemaker_fixture(
    project_dir: Path,
    fixture: dict[str, Any],
) -> None:
    particle_system = cast(dict[str, Any], fixture["particle_system"])
    room_layer = cast(dict[str, Any], fixture["room_layer"])
    _write_sprite(project_dir)
    _write_json(
        project_dir / "particles" / "ps_authored" / "ps_authored.yy",
        particle_system,
    )
    room = {
        "$GMRoom": "v1",
        "%Name": "rm_particles",
        "name": "rm_particles",
        "resourceType": "GMRoom",
        "resourceVersion": "2.0",
        "creationCodeFile": "",
        "inheritCode": False,
        "inheritCreationOrder": False,
        "inheritLayers": False,
        "instanceCreationOrder": [],
        "isDnd": False,
        "layers": [room_layer],
        "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
        "parentRoom": None,
        "physicsSettings": {
            "inheritPhysicsSettings": False,
            "PhysicsWorld": False,
            "PhysicsWorldGravityX": 0.0,
            "PhysicsWorldGravityY": 10.0,
            "PhysicsWorldPixToMetres": 0.1,
        },
        "roomSettings": {
            "Width": 320,
            "Height": 240,
            "inheritRoomSettings": False,
            "persistent": False,
        },
        "views": [],
        "viewSettings": {"enableViews": False},
        "volume": 1.0,
    }
    _write_json(
        project_dir / "rooms" / "rm_particles" / "rm_particles.yy",
        room,
    )
    resources = [
        {
            "id": {
                "name": "spr_particle",
                "path": "sprites/spr_particle/spr_particle.yy",
                "resourceType": "GMSprite",
            },
            "resourceType": "GMSprite",
        },
        {
            "id": {
                "name": "ps_authored",
                "path": "particles/ps_authored/ps_authored.yy",
                "resourceType": "GMParticleSystem",
            },
            "resourceType": "GMParticleSystem",
        },
        {
            "id": {
                "name": "rm_particles",
                "path": "rooms/rm_particles/rm_particles.yy",
                "resourceType": "GMRoom",
            },
            "resourceType": "GMRoom",
        },
    ]
    _write_json(
        project_dir / "AuthoredParticles.yyp",
        {
            "$GMProject": "v1",
            "%Name": "AuthoredParticles",
            "name": "AuthoredParticles",
            "resourceType": "GMProject",
            "resourceVersion": "2.0",
            "MetaData": {"IDEVersion": "2026.0.0.16"},
            "resources": resources,
            "RoomOrderNodes": [
                {
                    "roomId": {
                        "name": "rm_particles",
                        "path": "rooms/rm_particles/rm_particles.yy",
                    }
                }
            ],
        },
    )


def _write_probe(project_dir: Path, room_path: str) -> None:
    script = textwrap.dedent(
        f"""\
        extends Node

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const ROOM_PATH = {json.dumps(room_path)}

        func _check(condition, message):
        \tif condition:
        \t\treturn true
        \tpush_error(str(message))
        \tget_tree().quit(1)
        \treturn false

        func _ready():
        \tcall_deferred("_run")

        func _run():
        \tvar asset_id = GMRuntime.gml_asset_get_index("ps_authored")
        \tvar direct_system = GMRuntime.gml_part_system_create(asset_id)
        \tif not _check(GMRuntime.gml_part_system_exists(direct_system), "GML asset-backed system creation failed"):
        \t\treturn
        \tvar direct_record = direct_system.reference
        \tif not _check(direct_record["emitters"].size() == 2 and direct_record["owned_types"].size() == 2, "GML asset-backed descriptors were not instantiated"):
        \t\treturn
        \tvar direct_node = direct_record["node"]
        \tvar direct_types = direct_record["owned_types"].duplicate()
        \tGMRuntime.gml_part_system_destroy(direct_system)
        \tawait get_tree().process_frame
        \tif not _check(not GMRuntime.gml_part_system_exists(direct_system), "direct authored system handle leaked"):
        \t\treturn
        \tif not _check(not is_instance_valid(direct_node), "direct authored system node leaked"):
        \t\treturn
        \tfor type_handle in direct_types:
        \t\tif not _check(not GMRuntime.gml_handle_is_valid(type_handle), "direct authored type leaked"):
        \t\t\treturn
        \tvar invalid_system = GMRuntime.gml_part_system_create("missing_particle_asset")
        \tif not _check(not GMRuntime.gml_part_system_exists(invalid_system), "missing authored asset did not fail closed"):
        \t\treturn
        \tvar packed_room = load(ROOM_PATH)
        \tif not _check(packed_room is PackedScene, "generated room did not load"):
        \t\treturn
        \tvar room = packed_room.instantiate()
        \tadd_child(room)
        \tawait get_tree().process_frame
        \tvar layer = room.get_node_or_null("Effects")
        \tif not _check(layer is Node2D, "particle asset layer missing"):
        \t\treturn
        \tif not _check(not layer.visible, "layer visibility was not preserved"):
        \t\treturn
        \tif not _check(layer.z_index == 240, "layer depth was not preserved"):
        \t\treturn
        \tif not _check(layer.position == Vector2(3, 5), "layer offset was not preserved"):
        \t\treturn
        \tvar host = layer.get_node_or_null("particle_authored")
        \tif not _check(host is Node2D, "particle layer element missing"):
        \t\treturn
        \tif not _check(host.position == Vector2(32, 48), "element position mismatch"):
        \t\treturn
        \tif not _check(host.scale == Vector2(1.5, 0.75), "element scale mismatch"):
        \t\treturn
        \tif not _check(abs(host.rotation_degrees - 15.0) < 0.001, "element rotation mismatch"):
        \t\treturn
        \tvar system = host.get_meta("gamemaker_particle_system_handle", null)
        \tif not _check(GMRuntime.gml_part_system_exists(system), "authored system was not instantiated"):
        \t\treturn
        \tvar system_record = system.reference
        \tif not _check(system_record["asset_name"] == "ps_authored", "asset descriptor was not loaded"):
        \t\treturn
        \tif not _check(system_record["xorigin"] == 4.0 and system_record["yorigin"] == 6.0, "asset origin mismatch"):
        \t\treturn
        \tif not _check(system_record["emitters"].size() == 2, "authored emitter count mismatch"):
        \t\treturn
        \tif not _check(system_record["owned_types"].size() == 2, "authored type count mismatch"):
        \t\treturn
        \tvar stream_record = null
        \tvar burst_record = null
        \tvar emitter_handles = []
        \tfor emitter_handle in system_record["emitters"].values():
        \t\temitter_handles.append(emitter_handle)
        \t\tvar emitter_record = emitter_handle.reference
        \t\tif emitter_record["name"] == "EmitterStream":
        \t\t\tstream_record = emitter_record
        \t\telif emitter_record["name"] == "EmitterBurst":
        \t\t\tburst_record = emitter_record
        \tif not _check(stream_record != null and burst_record != null, "authored emitter names mismatch"):
        \t\treturn
        \tvar stream_node = stream_record["node"]
        \tvar stream_material = stream_node.process_material
        \tif not _check(stream_node is GPUParticles2D and stream_node.emitting, "stream emitter did not start"):
        \t\treturn
        \tif not _check(stream_node.amount == 90, "stream rate was not converted from particles per step"):
        \t\treturn
        \tif not _check(abs(stream_node.lifetime - 0.75) < 0.001, "lifetime range was not preserved"):
        \t\treturn
        \tif not _check(stream_node.position == Vector2(10, 10), "asset origin was not applied to emitter region"):
        \t\treturn
        \tif not _check(stream_node.draw_order == GPUParticles2D.DRAW_ORDER_REVERSE_LIFETIME, "draw order mismatch"):
        \t\treturn
        \tif not _check(stream_material.emission_shape == ParticleProcessMaterial.EMISSION_SHAPE_SPHERE, "ellipse shape mismatch"):
        \t\treturn
        \tif not _check(stream_material.initial_velocity_min == 60.0 and stream_material.initial_velocity_max == 180.0, "motion range mismatch"):
        \t\treturn
        \tif not _check(stream_material.gravity.y > 300.0, "gravity was not converted to step motion"):
        \t\treturn
        \tif not _check(stream_material.color_ramp != null, "colour and alpha ramp missing"):
        \t\treturn
        \tif not _check(stream_material.scale_curve != null, "size increase curve missing"):
        \t\treturn
        \tif not _check(stream_node.texture != null, "built-in particle texture missing"):
        \t\treturn
        \tvar burst_node = burst_record["node"]
        \tif not _check(burst_node.one_shot and burst_node.amount == 3, "burst emitter behavior mismatch"):
        \t\treturn
        \tif not _check(burst_node.texture != null, "sprite particle texture missing"):
        \t\treturn
        \tif not _check(burst_node.material is CanvasItemMaterial and burst_node.material.blend_mode == CanvasItemMaterial.BLEND_MODE_ADD, "additive blend mismatch"):
        \t\treturn
        \tvar spawn_descriptor = burst_node.get_meta("gamemaker_spawn_on_death", {{}})
        \tif not _check(spawn_descriptor.get("count", 0) == 2.0, "spawn-on-death descriptor missing"):
        \t\treturn
        \tvar owned_types = system_record["owned_types"].duplicate()
        \tvar system_node = system_record["node"]
        \troom.queue_free()
        \tawait get_tree().process_frame
        \tawait get_tree().process_frame
        \tif not _check(not GMRuntime.gml_part_system_exists(system), "room particle system leaked"):
        \t\treturn
        \tfor emitter_handle in emitter_handles:
        \t\tif not _check(not GMRuntime.gml_handle_is_valid(emitter_handle), "room emitter handle leaked"):
        \t\t\treturn
        \tfor type_handle in owned_types:
        \t\tif not _check(not GMRuntime.gml_handle_is_valid(type_handle), "room particle type handle leaked"):
        \t\t\treturn
        \tif not _check(not is_instance_valid(system_node), "room particle node leaked"):
        \t\treturn
        \tprint("AUTHORED_PARTICLES_OK")
        \tget_tree().quit(0)
        """
    )
    scene = textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://smoke.gd" id="1"]

        [node name="Smoke" type="Node"]
        script = ExtResource("1")
        """
    )
    _write_text(project_dir / "smoke.gd", script)
    _write_text(project_dir / "smoke.tscn", scene)


class TestAuthoredParticlesGodot(unittest.TestCase):
    def test_authored_asset_room_lifecycle_and_cleanup(self) -> None:
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
            _write_text(
                godot_dir / "project.godot",
                (
                    '[application]\nconfig/name="AuthoredParticles"\n'
                    'run/main_scene="res://smoke.tscn"\n\n'
                    '[rendering]\nrenderer/rendering_method="gl_compatibility"\n'
                    'renderer/rendering_method.mobile="gl_compatibility"\n'
                ),
            )

            diagnostics = DiagnosticCollector()
            SpriteConverter(
                str(gamemaker_dir),
                str(godot_dir),
                log_callback=_ignore_message,
                progress_callback=_ignore_progress,
                conversion_running=_conversion_running,
                diagnostics=diagnostics,
            ).convert_all()
            RoomConverter(
                str(gamemaker_dir),
                str(godot_dir),
                log_callback=_ignore_message,
                progress_callback=_ignore_progress,
                conversion_running=_conversion_running,
                diagnostics=diagnostics,
            ).convert_all()
            registry_converter = AssetRegistryConverter(
                str(gamemaker_dir),
                str(godot_dir),
                log_callback=_ignore_message,
                progress_callback=_ignore_progress,
                conversion_running=_conversion_running,
                diagnostics=diagnostics,
            )
            registry_converter.convert_all()
            entries = registry_converter.build_entries()
            particle_entry = next(
                entry for entry in entries if entry.name == "ps_authored"
            )
            room_entry = next(
                entry for entry in entries if entry.name == "rm_particles"
            )
            descriptor_path = (
                godot_dir
                / particle_entry.godot_path.removeprefix("res://")
            )
            self.assertTrue(descriptor_path.is_file())
            descriptor_text = descriptor_path.read_text(encoding="utf-8")
            self.assertIn(
                "metadata/gamemaker_particle_descriptor",
                descriptor_text,
            )
            self.assertEqual(diagnostics.summary()["warning"], 0)
            write_gml_runtime(str(godot_dir))
            _write_probe(godot_dir, room_entry.godot_path)

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
                    "20",
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
        self.assertIn("AUTHORED_PARTICLES_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
