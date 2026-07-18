import os
# pyright: reportPrivateUsage=false
import json
import sys
import shutil
import tempfile
import threading
import unittest
from typing import cast
from unittest.mock import DEFAULT, MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.objects import ObjectConverter, ObjectProcessResult
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.converter import Converter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.events.base import EventMapping
from src.conversion.event_mapping import is_input_event, map_event, map_input_event
from src.conversion.type_defs import JsonDict


def _make_object_yy_content(name: str, sprite_name: str | None = None,
                            parent_path: str = "folders/Objects.yy",
                            event_list: list[JsonDict] | None = None,
                            parent_object_name: str | None = None,
                            persistent: bool = False) -> str:
    """Build a GameMaker object .yy file string."""
    if sprite_name is not None:
        sprite_id = (
            '{{"name": "{sprite_name}", '
            '"path": "sprites/{sprite_name}/{sprite_name}.yy",}}'
        ).format(sprite_name=sprite_name)
    else:
        sprite_id = "null"

    if parent_object_name is None:
        parent_object_id = "null"
    else:
        parent_object_id = (
            '{{"name": "{parent_object_name}", '
            '"path": "objects/{parent_object_name}/{parent_object_name}.yy",}}'
        ).format(parent_object_name=parent_object_name)

    if event_list is None:
        event_list = []
    event_entries: list[str] = []
    for evt in event_list:
        collision_id = "null"
        if evt.get("collisionObjectId") is not None:
            col = cast(JsonDict, evt["collisionObjectId"])
            collision_id = '{{"name": "{name}", "path": "objects/{name}/{name}.yy",}}'.format(name=col["name"])
        entry = (
            '{{"isDnD":{isDnD},"eventNum":{eventNum},"eventType":{eventType},'
            '"collisionObjectId":{collisionObjectId},'
            '"resourceVersion":"2.0","name":"","resourceType":"GMEvent",}}'
        ).format(
            isDnD=str(evt.get("isDnD") is True).lower(),
            eventNum=evt.get("eventNum", 0),
            eventType=evt.get("eventType", 0),
            collisionObjectId=collision_id,
        )
        event_entries.append(entry)
    event_list_str = ",\n    ".join(event_entries)
    if event_list_str:
        event_list_str = "\n    " + event_list_str + ",\n  "

    return (
        '{{\n'
        '  "$GMObject": "",\n'
        '  "%Name": "{name}",\n'
        '  "eventList": [{event_list_str}],\n'
        '  "managed": true,\n'
        '  "name": "{name}",\n'
        '  "overriddenProperties": [],\n'
        '  "parent": {{"name": "Objects", "path": "{parent_path}",}},\n'
        '  "parentObjectId": {parent_object_id},\n'
        '  "persistent": {persistent},\n'
        '  "physicsObject": false,\n'
        '  "properties": [],\n'
        '  "resourceType": "GMObject",\n'
        '  "resourceVersion": "2.0",\n'
        '  "solid": false,\n'
        '  "spriteId": {sprite_id},\n'
        '  "spriteMaskId": null,\n'
        '  "visible": true,\n'
        '}}'
    ).format(
        name=name,
        sprite_id=sprite_id,
        parent_path=parent_path,
        parent_object_id=parent_object_id,
        event_list_str=event_list_str,
        persistent=str(persistent).lower(),
    )


def _create_fake_sprite_scene(godot_dir: str, sprite_name: str, subfolder: str = "") -> None:
    """Create a minimal sprite .tscn file in the Godot project."""
    if subfolder:
        sprite_dir = os.path.join(godot_dir, "sprites", subfolder, sprite_name)
    else:
        sprite_dir = os.path.join(godot_dir, "sprites", sprite_name)
    os.makedirs(sprite_dir, exist_ok=True)
    tscn_path = os.path.join(sprite_dir, sprite_name + ".tscn")
    with open(tscn_path, "w", encoding="utf-8") as f:
        f.write('[gd_scene format=3]\n\n[node name="{}" type="Area2D"]\n'.format(sprite_name))


def _make_sprite_yy_content(sprite_name: str, parent_path: str = "folders/Sprites.yy") -> str:
    """Build a minimal sprite .yy file with parent folder info."""
    return (
        '{{\n'
        '  "name": "{name}",\n'
        '  "parent": {{"name": "Sprites", "path": "{parent_path}",}},\n'
        '  "resourceType": "GMSprite",\n'
        '}}'
    ).format(name=sprite_name, parent_path=parent_path)


class TestObjectConverterBasic(unittest.TestCase):
    """Test ObjectConverter with a minimal fake GameMaker project."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create an object with a sprite reference
        obj_dir = os.path.join(self.gm_dir, "objects", "o_player")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_player", sprite_name="s_player")
        with open(os.path.join(obj_dir, "o_player.yy"), "w") as f:
            f.write(yy_content)

        # Create an object without a sprite
        obj_dir2 = os.path.join(self.gm_dir, "objects", "o_controller")
        os.makedirs(obj_dir2)
        yy_content2 = _make_object_yy_content("o_controller", sprite_name=None)
        with open(os.path.join(obj_dir2, "o_controller.yy"), "w") as f:
            f.write(yy_content2)

        # Create the fake converted sprite scene for o_player's sprite
        _create_fake_sprite_scene(self.godot_dir, "s_player")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, macro_configuration: str | None = None) -> ObjectConverter:
        return ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
        )

    def test_converts_object_to_godot_dir(self):
        converter = self._make_converter()
        result = converter.convert_all()

        godot_obj_dir = os.path.join(self.godot_dir, "objects", "o_player")
        self.assertIsNone(result)
        self.assertTrue(os.path.isdir(godot_obj_dir),
                        "Expected objects/o_player directory in Godot project")
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=2,
            ),
        )

    def test_failed_object_does_not_hide_safe_sibling_completion(self):
        converter = self._make_converter()

        def process_object(
            object_name: str,
            *_args: object,
        ) -> ObjectProcessResult:
            return {
                "status": (
                    "completed" if object_name == "o_player" else "failed"
                ),
                "name": object_name,
                "has_sprite": False,
                "sprite_name": None,
                "event_count": 0,
            }

        with patch.object(converter, "_process_object", side_effect=process_object):
            converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                failed=1,
            ),
        )

    def test_cancellation_leaves_objects_for_inherited_finalization(self):
        running = threading.Event()
        running.set()
        converter = ObjectConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda _value: None,
            conversion_running=running.is_set,
            max_workers=1,
        )

        def cancel_object(
            _object_name: str,
            *_args: object,
        ) -> None:
            running.clear()

        with patch.object(converter, "_process_object", side_effect=cancel_object):
            converter.convert_all()

        with self.assertRaises(ValueError):
            converter.conversion_step_result(finalize_unfinished_as=None)

        result = converter.conversion_step_result()
        self.assertTrue(result.cancelled)
        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=2,
                executed=1,
                skipped=2,
            ),
        )

    def test_worker_exception_marks_object_failed_after_safe_sibling_settles(self):
        converter = self._make_converter()

        def process_object(
            object_name: str,
            *_args: object,
        ) -> ObjectProcessResult:
            if object_name == "o_controller":
                raise RuntimeError("object worker failed")
            return {
                "status": "completed",
                "name": object_name,
                "has_sprite": False,
                "sprite_name": None,
                "event_count": 0,
            }

        with patch.object(converter, "_process_object", side_effect=process_object):
            with self.assertRaisesRegex(RuntimeError, "object worker failed"):
                converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                failed=1,
            ),
        )

    def test_generates_tscn_file(self):
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.tscn")
        self.assertTrue(os.path.isfile(tscn_path), "Expected .tscn file to be generated")

    def test_tscn_instances_sprite(self):
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('PackedScene', content)
        self.assertIn('res://sprites/s_player/s_player.tscn', content)
        self.assertIn('instance=ExtResource("1")', content)
        self.assertIn('type="Node2D"', content)

    def test_object_without_sprite(self):
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_controller", "o_controller.tscn")
        self.assertTrue(os.path.isfile(tscn_path), "Expected .tscn file for object without sprite")

        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('type="Node2D"', content)
        self.assertNotIn('PackedScene', content)
        self.assertNotIn('instance', content)
        self.assertIn('type="Script"', content)
        self.assertIn('script = ExtResource', content)


class TestObjectConverterEmpty(unittest.TestCase):
    """Edge cases: missing objects dir and missing sprites."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_empty_objects_no_crash(self):
        """No objects directory at all should log an error and not crash."""
        converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise

        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for missing objects folder")

    def test_missing_sprite_scene_fallback(self):
        """Object referencing a sprite whose scene doesn't exist should fall back to no-sprite."""
        obj_dir = os.path.join(self.gm_dir, "objects", "o_broken")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_broken", sprite_name="s_nonexistent")
        with open(os.path.join(obj_dir, "o_broken.yy"), "w") as f:
            f.write(yy_content)

        converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise

        # Scene should still be created, but without sprite reference
        tscn_path = os.path.join(self.godot_dir, "objects", "o_broken", "o_broken.tscn")
        self.assertTrue(os.path.isfile(tscn_path),
                        "Should still generate .tscn even when sprite is missing")

        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('type="Node2D"', content)
        self.assertNotIn('PackedScene', content)
        self.assertIn('type="Script"', content)


class TestParseObjectYY(unittest.TestCase):
    """Test _parse_object_yy directly."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_object_yy(self, object_name: str, content: str) -> None:
        obj_dir = os.path.join(self.gm_dir, "objects", object_name)
        os.makedirs(obj_dir, exist_ok=True)
        with open(os.path.join(obj_dir, object_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_valid_object_with_sprite(self):
        content = _make_object_yy_content("o_test", sprite_name="s_test")
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["sprite_name"], "s_test")

    def test_parses_valid_object_without_sprite(self):
        content = _make_object_yy_content("o_empty", sprite_name=None)
        self._write_object_yy("o_empty", content)

        result = self.converter._parse_object_yy("o_empty")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNone(result["sprite_name"])

    def test_parses_parent_object_name(self):
        content = _make_object_yy_content("o_child", parent_object_name="o_parent")
        self._write_object_yy("o_child", content)

        result = self.converter._parse_object_yy("o_child")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["parent_object_name"], "o_parent")

    def test_returns_none_for_missing(self):
        result = self.converter._parse_object_yy("nonexistent_object")
        self.assertIsNone(result)

    def test_handles_trailing_commas(self):
        content = (
            '{\n'
            '  "spriteId": {"name": "s_tc", "path": "sprites/s_tc/s_tc.yy",},\n'
            '  "name": "o_tc",\n'
            '  "resourceType": "GMObject",\n'
            '}'
        )
        self._write_object_yy("o_tc", content)

        result = self.converter._parse_object_yy("o_tc")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["sprite_name"], "s_tc")


class TestObjectConverterYYPFiltering(unittest.TestCase):
    """Test that objects are filtered against the .yyp project file."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create two objects on disk
        for name in ["o_listed", "o_unlisted"]:
            obj_dir = os.path.join(self.gm_dir, "objects", name)
            os.makedirs(obj_dir)
            yy_content = _make_object_yy_content(name, sprite_name=None)
            with open(os.path.join(obj_dir, name + ".yy"), "w") as f:
                f.write(yy_content)

        # Create a .yyp that only lists o_listed
        yyp_content = (
            '{\n'
            '  "resources": [\n'
            '    {"id": {"name": "o_listed", "path": "objects/o_listed/o_listed.yy"}}\n'
            '  ]\n'
            '}'
        )
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w") as f:
            f.write(yyp_content)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_yyp_resources(self, resources: list[JsonDict]) -> None:
        with open(
            os.path.join(self.gm_dir, "Test.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "%Name": "Test",
                    "resources": resources,
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                },
                project_file,
            )

    @staticmethod
    def _object_resource(name: str, path: str | None = None) -> JsonDict:
        return cast(
            JsonDict,
            {
                "id": {
                    "name": name,
                    "path": path or f"objects/{name}/{name}.yy",
                }
            },
        )

    def test_only_listed_objects_converted(self):
        converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        listed_path = os.path.join(self.godot_dir, "objects", "o_listed", "o_listed.tscn")
        unlisted_path = os.path.join(self.godot_dir, "objects", "o_unlisted", "o_unlisted.tscn")

        self.assertTrue(os.path.isfile(listed_path),
                        "Object listed in .yyp should be converted")
        self.assertFalse(os.path.isfile(unlisted_path),
                         "Object not listed in .yyp should be skipped")

    def test_missing_only_declared_object_makes_conversion_partial(self):
        self._write_yyp_resources([self._object_resource("o_missing")])
        shutil.rmtree(os.path.join(self.gm_dir, "objects"))
        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
        )
        objects_enabled = MagicMock()
        objects_enabled.get.return_value = True

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"objects": objects_enabled},
        )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, skipped=1),
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.godot_dir, "objects", "o_listed"))
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.godot_dir, "objects", "o_unlisted"))
        )
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-OBJECT-SOURCE-UNAVAILABLE"
                and diagnostic.resource == "o_missing"
                for diagnostic in converter.diagnostics.diagnostics()
            )
        )

    def test_safe_and_missing_declared_objects_have_strict_counts(self):
        self._write_yyp_resources(
            [
                self._object_resource("o_listed"),
                self._object_resource("o_missing"),
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = ObjectConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        )

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=1,
                completed=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_listed",
                    "o_listed.tscn",
                )
            )
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.godot_dir, "objects", "o_missing"))
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.godot_dir, "objects", "o_unlisted"))
        )
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-OBJECT-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].resource, "o_missing")
        self.assertEqual(unavailable[0].source_path, "Test.yyp")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "resources[1].id.path",
        )

    def test_rejected_declared_object_is_requested_and_skipped(self):
        rejected_name = "o_rejected"
        rejected_dir = os.path.join(self.gm_dir, "objects", rejected_name)
        os.makedirs(rejected_dir)
        with open(
            os.path.join(rejected_dir, rejected_name + ".yy"),
            "w",
            encoding="utf-8",
        ) as object_file:
            object_file.write(_make_object_yy_content(rejected_name))
        self._write_yyp_resources(
            [
                self._object_resource(
                    rejected_name,
                    f"objects/../../outside/{rejected_name}.yy",
                )
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = ObjectConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        )

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, skipped=1),
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "objects", rejected_name)
            )
        )
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
                and diagnostic.resource == rejected_name
                for diagnostic in diagnostics.diagnostics()
            )
        )
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-OBJECT-SOURCE-UNAVAILABLE"
                and diagnostic.resource == rejected_name
                for diagnostic in diagnostics.diagnostics()
            )
        )


class TestObjectSourceContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self) -> ObjectConverter:
        return ObjectConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )

    def _write_json(self, path: str, value: object) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as output_file:
            json.dump(value, output_file)

    def _generated_object_script(self, object_name: str) -> str:
        for directory, _subdirectories, filenames in os.walk(self.godot_dir):
            filename = object_name + ".gd"
            if filename in filenames:
                with open(
                    os.path.join(directory, filename),
                    "r",
                    encoding="utf-8",
                ) as source_file:
                    return source_file.read()
        self.fail(f"Missing generated object script for {object_name}")

    def _all_generated_text(self) -> str:
        chunks: list[str] = []
        for directory, _subdirectories, filenames in os.walk(self.godot_dir):
            for filename in filenames:
                path = os.path.join(directory, filename)
                try:
                    with open(path, "r", encoding="utf-8") as source_file:
                        chunks.append(source_file.read())
                except (OSError, UnicodeDecodeError):
                    continue
        return "\n".join(chunks)

    def test_manifest_discovery_reads_selected_yyp_once(self) -> None:
        yyp_path = os.path.join(self.gm_dir, "ObjectPaths.yyp")
        self._write_json(yyp_path, {"resources": []})

        with patch("builtins.open", wraps=open) as tracked_open:
            valid_objects = self._make_converter()._get_valid_object_names()

        self.assertEqual(valid_objects, {})
        yyp_reads = [
            call
            for call in tracked_open.call_args_list
            if call.args
            and isinstance(call.args[0], (str, os.PathLike))
            and os.path.abspath(os.fspath(call.args[0])) == yyp_path
        ]
        self.assertEqual(len(yyp_reads), 1, yyp_reads)

    def test_event_filename_cannot_reach_another_project_directory(self) -> None:
        owner_path = os.path.join(
            self.gm_dir,
            "objects",
            "o_owner",
            "o_owner.yy",
        )
        self._write_json(owner_path, {"resourceType": "GMObject"})
        mapping = EventMapping(
            godot_func="_gm_cross_owner",
            params="",
            sort_key=1,
            gml_filename="../shared/Leak.gml",
        )

        contained = self._make_converter()._event_mapping_paths_are_contained(
            "objects/o_owner/o_owner.yy",
            "o_owner",
            mapping,
            field="eventList[0].sourceFile",
        )

        self.assertFalse(contained)
        rejected = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "objects/o_owner/o_owner.yy")
        self.assertEqual(rejected[0].manifest_entry, "eventList[0].sourceFile")

    def test_yyp_declared_object_path_is_used_instead_of_name_reconstruction(self) -> None:
        declared_dir = os.path.join(self.gm_dir, "objects", "nested", "source")
        reconstructed_dir = os.path.join(self.gm_dir, "objects", "o_declared")
        os.makedirs(declared_dir)
        os.makedirs(reconstructed_dir)
        self._write_json(
            os.path.join(declared_dir, "custom_object.yy"),
            {
                "name": "o_declared",
                "resourceType": "GMObject",
                "eventList": [{"eventType": 0, "eventNum": 0}],
            },
        )
        with open(
            os.path.join(declared_dir, "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("declared_source = 1;")
        self._write_json(
            os.path.join(reconstructed_dir, "o_declared.yy"),
            {
                "name": "o_declared",
                "resourceType": "GMObject",
                "eventList": [{"eventType": 0, "eventNum": 0}],
            },
        )
        with open(
            os.path.join(reconstructed_dir, "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("RECONSTRUCTED_MARKER = 1;")
        self._write_json(
            os.path.join(self.gm_dir, "Project.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "o_declared",
                            "path": "objects/nested/source/custom_object.yy",
                        }
                    }
                ],
                "resourceType": "GMProject",
            },
        )

        self._make_converter().convert_all()

        script = self._generated_object_script("o_declared")
        self.assertIn("declared_source = 1", script)
        self.assertNotIn("RECONSTRUCTED_MARKER", script)

    def test_external_first_yyp_cannot_mask_contained_declared_object_path(self) -> None:
        declared_path = os.path.join(
            self.gm_dir,
            "objects",
            "nested",
            "custom_object.yy",
        )
        self._write_json(
            declared_path,
            {
                "name": "o_inside",
                "parent": {
                    "name": "Objects",
                    "path": "folders/Objects.yy",
                },
                "resourceType": "GMObject",
                "eventList": [],
            },
        )
        self._write_json(
            os.path.join(self.gm_dir, "BInside.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "o_inside",
                            "path": "objects/nested/custom_object.yy",
                        }
                    }
                ],
                "resourceType": "GMProject",
            },
        )
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_yyp = os.path.join(outside_dir, "Outside.yyp")
            self._write_json(
                outside_yyp,
                {
                    "resources": [
                        {
                            "id": {
                                "name": "o_outside",
                                "path": "objects/o_outside/o_outside.yy",
                            }
                        }
                    ]
                },
            )
            try:
                os.symlink(
                    outside_yyp,
                    os.path.join(self.gm_dir, "AOutside.yyp"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            converter = self._make_converter()
            valid_objects = converter._get_valid_object_names()

        self.assertEqual(valid_objects, {"o_inside": ""})
        self.assertEqual(
            converter._object_source_paths,
            {"o_inside": "objects/nested/custom_object.yy"},
        )
        rejected = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertIsNone(rejected[0].source_path)
        self.assertEqual(rejected[0].resource_type, "project")
        self.assertEqual(rejected[0].manifest_entry, "AOutside.yyp")
        self.assertIn("AOutside.yyp", rejected[0].message)

    def test_non_file_first_yyp_is_rejected_with_source_link(self) -> None:
        os.makedirs(os.path.join(self.gm_dir, "ADirectory.yyp"))
        self._write_json(
            os.path.join(self.gm_dir, "BInside.yyp"),
            {"resources": [], "resourceType": "GMProject"},
        )

        valid_objects = self._make_converter()._get_valid_object_names()

        self.assertEqual(valid_objects, {})
        rejected = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "ADirectory.yyp")
        self.assertEqual(rejected[0].resource_type, "project")
        self.assertEqual(rejected[0].manifest_entry, "ADirectory.yyp")

    def test_disk_fallback_rejects_object_yy_file_symlink_escape(self) -> None:
        object_dir = os.path.join(self.gm_dir, "objects", "o_escape")
        os.makedirs(object_dir)
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_yy = os.path.join(outside_dir, "o_escape.yy")
            self._write_json(
                outside_yy,
                {
                    "name": "OUTSIDE_OBJECT_MARKER",
                    "resourceType": "GMObject",
                    "eventList": [],
                },
            )
            try:
                os.symlink(outside_yy, os.path.join(object_dir, "o_escape.yy"))
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            self._make_converter().convert_all()

        self.assertNotIn("OUTSIDE_OBJECT_MARKER", self._all_generated_text())
        rejected = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
            and diagnostic.resource == "o_escape"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "objects/o_escape")
        self.assertEqual(rejected[0].manifest_entry, "object.yy")

    def test_disk_fallback_rejects_contained_cross_family_object_yy_link(
        self,
    ) -> None:
        linked_name = "o_cross_family_link"
        wrong_family_yy = os.path.join(
            self.gm_dir,
            "sprites",
            "wrong_object",
            "target.yy",
        )
        self._write_json(
            wrong_family_yy,
            {
                "name": "WRONG_FAMILY_OBJECT_MARKER",
                "resourceType": "GMObject",
                "eventList": [],
            },
        )
        linked_directory = os.path.join(self.gm_dir, "objects", linked_name)
        os.makedirs(linked_directory)
        try:
            os.symlink(
                wrong_family_yy,
                os.path.join(linked_directory, linked_name + ".yy"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        safe_name = "o_safe_sibling"
        self._write_json(
            os.path.join(self.gm_dir, "objects", safe_name, safe_name + ".yy"),
            {
                "name": safe_name,
                "resourceType": "GMObject",
                "eventList": [],
            },
        )

        self._make_converter().convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    linked_name,
                    linked_name + ".tscn",
                )
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    safe_name,
                    safe_name + ".tscn",
                )
            )
        )
        self.assertNotIn("WRONG_FAMILY_OBJECT_MARKER", self._all_generated_text())
        rejected = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
            and diagnostic.resource == linked_name
            and diagnostic.manifest_entry == "object.yy"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, f"objects/{linked_name}")
        self.assertEqual(rejected[0].resource_type, "object")
        self.assertEqual(rejected[0].manifest_entry, "object.yy")

    def test_contained_reference_paths_override_untrusted_reference_names(self) -> None:
        for object_name in ("o_parent", "o_bullet"):
            self._write_json(
                os.path.join(
                    self.gm_dir,
                    "objects",
                    object_name,
                    object_name + ".yy",
                ),
                {
                    "name": object_name,
                    "resourceType": "GMObject",
                    "eventList": [],
                },
            )
        self._write_json(
            os.path.join(self.gm_dir, "sprites", "s_real", "s_real.yy"),
            {
                "name": "s_real",
                "resourceType": "GMSprite",
                "parent": {"path": "folders/Sprites.yy"},
            },
        )
        _create_fake_sprite_scene(self.godot_dir, "s_real")
        child_dir = os.path.join(self.gm_dir, "objects", "o_child")
        self._write_json(
            os.path.join(child_dir, "o_child.yy"),
            {
                "name": "o_child",
                "resourceType": "GMObject",
                "spriteId": {
                    "name": "UNTRUSTED_SPRITE_NAME",
                    "path": "sprites/s_real/s_real.yy",
                },
                "parentObjectId": {
                    "name": "UNTRUSTED_PARENT_NAME",
                    "path": "objects/o_parent/o_parent.yy",
                },
                "eventList": [
                    {
                        "eventType": 4,
                        "eventNum": 0,
                        "collisionObjectId": {
                            "name": "UNTRUSTED_COLLISION_NAME",
                            "path": "objects/o_bullet/o_bullet.yy",
                        },
                    }
                ],
            },
        )
        with open(
            os.path.join(child_dir, "Collision_o_bullet.gml"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("safe_collision = true;")

        self._make_converter().convert_all()

        script = self._generated_object_script("o_child")
        self.assertTrue(script.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertIn('"target_object": "o_bullet"', script)
        self.assertIn("func _on_collision_o_bullet():", script)
        self.assertIn(
            'GMRuntime.gml_variable_instance_set(self, "safe_collision", true)',
            script,
        )
        generated = self._all_generated_text()
        self.assertIn("res://sprites/s_real/s_real.tscn", generated)
        self.assertNotIn("UNTRUSTED_", generated)

    def test_custom_reference_filenames_preserve_logical_resource_names(self) -> None:
        references = (
            (
                "sprites",
                "s_logical",
                "sprites/storage/custom_sprite.yy",
                "GMSprite",
            ),
            (
                "objects",
                "o_parent_logical",
                "objects/storage/custom_parent.yy",
                "GMObject",
            ),
            (
                "objects",
                "o_collision_logical",
                "objects/storage/custom_collision.yy",
                "GMObject",
            ),
        )
        project_resources: list[dict[str, object]] = []
        for _kind, logical_name, source_path, resource_type in references:
            self._write_json(
                os.path.join(self.gm_dir, *source_path.split("/")),
                {
                    "%Name": logical_name,
                    "name": logical_name,
                    "resourceType": resource_type,
                    "eventList": [],
                },
            )
            project_resources.append(
                {"id": {"name": logical_name, "path": source_path}}
            )
        child_source_path = "objects/o_child/o_child.yy"
        self._write_json(
            os.path.join(self.gm_dir, *child_source_path.split("/")),
            {
                "name": "o_child",
                "resourceType": "GMObject",
                "spriteId": {
                    "name": "UNTRUSTED_SPRITE_NAME",
                    "path": references[0][2],
                },
                "parentObjectId": {
                    "name": "UNTRUSTED_PARENT_NAME",
                    "path": references[1][2],
                },
                "eventList": [
                    {
                        "eventType": 4,
                        "eventNum": 0,
                        "collisionObjectId": {
                            "name": "UNTRUSTED_COLLISION_NAME",
                            "path": references[2][2],
                        },
                    }
                ],
            },
        )
        project_resources.append(
            {"id": {"name": "o_child", "path": child_source_path}}
        )
        self._write_json(
            os.path.join(self.gm_dir, "Project.yyp"),
            {"resources": project_resources, "resourceType": "GMProject"},
        )

        parsed = self._make_converter()._parse_object_yy(
            "o_child",
            child_source_path,
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["sprite_name"], "s_logical")
        self.assertEqual(parsed["sprite_source_path"], references[0][2])
        self.assertEqual(parsed["parent_object_name"], "o_parent_logical")
        self.assertEqual(parsed["parent_object_source_path"], references[1][2])
        collision = parsed["event_list"][0]["collisionObjectId"]
        self.assertIsInstance(collision, dict)
        assert isinstance(collision, dict)
        self.assertEqual(collision["name"], "o_collision_logical")
        self.assertEqual(collision["path"], references[2][2])

    def test_rejects_malformed_declared_paths_and_unsafe_legacy_names(self) -> None:
        owner_source_path = "objects/o_owner/o_owner.yy"
        self._write_json(
            os.path.join(self.gm_dir, *owner_source_path.split("/")),
            {"name": "o_owner", "resourceType": "GMObject"},
        )
        self._write_json(
            os.path.join(self.gm_dir, "sprites", "s_safe", "s_safe.yy"),
            {"name": "s_safe", "resourceType": "GMSprite"},
        )
        converter = self._make_converter()
        malformed_paths: tuple[object, ...] = (7, None, "")
        unsafe_names = (
            "../safe",
            "/tmp/safe",
            r"C:\Games\safe",
            r"C:safe",
            r"\\server\share\safe",
            "bad\0name",
            "nested/../safe",
        )

        for index, raw_path in enumerate(malformed_paths):
            with self.subTest(path=raw_path):
                self.assertIsNone(
                    converter._resolve_resource_reference(
                        {"path": raw_path, "name": "s_safe"},
                        owner_source_path=owner_source_path,
                        owner_name="o_owner",
                        field=f"badPath[{index}]",
                        resource_kind="sprites",
                    )
                )
        for index, raw_name in enumerate(unsafe_names):
            with self.subTest(name=raw_name):
                self.assertIsNone(
                    converter._resolve_resource_reference(
                        {"name": raw_name},
                        owner_source_path=owner_source_path,
                        owner_name="o_owner",
                        field=f"badName[{index}]",
                        resource_kind="sprites",
                    )
                )

        self.assertEqual(
            converter._resolve_resource_reference(
                {"name": "s_safe"},
                owner_source_path=owner_source_path,
                owner_name="o_owner",
                field="safeSprite",
                resource_kind="sprites",
            ),
            ("s_safe", "sprites/s_safe/s_safe.yy"),
        )
        rejected = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(
            len(rejected),
            len(malformed_paths) + len(unsafe_names),
            rejected,
        )
        self.assertTrue(
            all(
                diagnostic.source_path == owner_source_path
                and diagnostic.resource == "o_owner"
                and diagnostic.resource_type == "object"
                for diagnostic in rejected
            )
        )

    def test_nested_references_and_event_symlinks_never_enter_output(self) -> None:
        object_dir = os.path.join(self.gm_dir, "objects", "o_child")
        os.makedirs(object_dir)
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_parent = os.path.join(outside_dir, "outside_parent.yy")
            outside_sprite = os.path.join(outside_dir, "outside_sprite.yy")
            outside_collision = os.path.join(outside_dir, "outside_collision.yy")
            outside_gml = os.path.join(outside_dir, "outside_event.gml")
            self._write_json(
                outside_parent,
                {"name": "OUTSIDE_PARENT_MARKER", "eventList": []},
            )
            self._write_json(
                outside_sprite,
                {"name": "OUTSIDE_SPRITE_MARKER", "frames": []},
            )
            self._write_json(
                outside_collision,
                {"name": "OUTSIDE_COLLISION_MARKER", "eventList": []},
            )
            with open(outside_gml, "w", encoding="utf-8") as source_file:
                source_file.write("OUTSIDE_EVENT_CODE_MARKER = 1;")

            os.makedirs(os.path.join(self.gm_dir, "sprites"))
            try:
                os.symlink(
                    outside_parent,
                    os.path.join(self.gm_dir, "objects", "parent_link.yy"),
                )
                os.symlink(
                    outside_sprite,
                    os.path.join(self.gm_dir, "sprites", "sprite_link.yy"),
                )
                os.symlink(
                    outside_collision,
                    os.path.join(self.gm_dir, "objects", "collision_link.yy"),
                )
                os.symlink(outside_gml, os.path.join(object_dir, "Create_0.gml"))
                os.symlink(outside_gml, os.path.join(object_dir, "Collision_0.gml"))
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            self._write_json(
                os.path.join(object_dir, "o_child.yy"),
                {
                    "name": "o_child",
                    "resourceType": "GMObject",
                    "spriteId": {
                        "name": "s_outside",
                        "path": "sprites/sprite_link.yy",
                    },
                    "parentObjectId": {
                        "name": "o_outside",
                        "path": "objects/parent_link.yy",
                    },
                    "eventList": [
                        {"eventType": 0, "eventNum": 0},
                        {
                            "eventType": 4,
                            "eventNum": 0,
                            "collisionObjectId": {
                                "name": "o_collision_outside",
                                "path": "objects/collision_link.yy",
                            },
                        },
                        {
                            "eventType": 99,
                            "eventNum": "/../../../../OUTSIDE_EVENT_FILENAME_MARKER",
                        },
                    ],
                },
            )

            self._make_converter().convert_all()

        generated = self._all_generated_text()
        for marker in (
            "OUTSIDE_PARENT_MARKER",
            "OUTSIDE_SPRITE_MARKER",
            "OUTSIDE_COLLISION_MARKER",
            "OUTSIDE_EVENT_CODE_MARKER",
            "OUTSIDE_EVENT_FILENAME_MARKER",
            "o_outside",
            "s_outside",
            "o_collision_outside",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, generated)

        rejected = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
            and diagnostic.resource == "o_child"
        ]
        self.assertGreaterEqual(len(rejected), 5)
        self.assertTrue(
            all(
                diagnostic.source_path == "objects/o_child/o_child.yy"
                and diagnostic.resource == "o_child"
                and diagnostic.resource_type == "object"
                for diagnostic in rejected
            )
        )
        rejected_fields = {diagnostic.manifest_entry for diagnostic in rejected}
        self.assertIn("spriteId.path", rejected_fields)
        self.assertIn("parentObjectId.path", rejected_fields)
        self.assertIn("eventList[1].collisionObjectId.path", rejected_fields)
        self.assertIn("eventList[0].sourceFile", rejected_fields)
        self.assertIn("eventList[2].sourceFile", rejected_fields)


class TestObjectConverterSubfolders(unittest.TestCase):
    """Test that objects respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, macro_configuration: str | None = None) -> ObjectConverter:
        return ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
        )

    def test_object_in_subfolder(self):
        """Object with nested parent path should be placed in subfolder."""
        obj_dir = os.path.join(self.gm_dir, "objects", "o_boss")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_boss", sprite_name=None,
                                              parent_path="folders/Objects/Game/Enemies.yy")
        with open(os.path.join(obj_dir, "o_boss.yy"), "w") as f:
            f.write(yy_content)

        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "game", "enemies", "o_boss", "o_boss.tscn")
        self.assertTrue(os.path.isfile(tscn_path),
                        "Object should be in objects/game/enemies/o_boss/")

    def test_object_with_sprite_in_subfolder(self):
        """Object should resolve sprite cross-reference with correct subfolder path."""
        # Create object
        obj_dir = os.path.join(self.gm_dir, "objects", "o_player")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_player", sprite_name="s_player",
                                              parent_path="folders/Objects.yy")
        with open(os.path.join(obj_dir, "o_player.yy"), "w") as f:
            f.write(yy_content)

        # Create sprite .yy in GM project (for subfolder resolution)
        sprite_gm_dir = os.path.join(self.gm_dir, "sprites", "s_player")
        os.makedirs(sprite_gm_dir)
        sprite_yy = _make_sprite_yy_content("s_player", parent_path="folders/Sprites/Player.yy")
        with open(os.path.join(sprite_gm_dir, "s_player.yy"), "w") as f:
            f.write(sprite_yy)

        # Create converted sprite scene at the subfolder location
        _create_fake_sprite_scene(self.godot_dir, "s_player", subfolder="player")

        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('res://sprites/player/s_player/s_player.tscn', content)

    def test_root_level_object_stays_flat(self):
        """Object with root-level parent should stay in flat structure."""
        obj_dir = os.path.join(self.gm_dir, "objects", "o_ctrl")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_ctrl", sprite_name=None,
                                              parent_path="folders/Objects.yy")
        with open(os.path.join(obj_dir, "o_ctrl.yy"), "w") as f:
            f.write(yy_content)

        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_ctrl", "o_ctrl.tscn")
        self.assertTrue(os.path.isfile(tscn_path),
                        "Root-level object should remain at objects/o_ctrl/")


class TestScriptGeneration(unittest.TestCase):
    """Test .gd script file generation for objects."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(
        self,
        macro_configuration: str | None = None,
        diagnostics: DiagnosticCollector | None = None,
    ) -> ObjectConverter:
        return ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
            diagnostics=diagnostics,
        )

    def _setup_object(self, name: str, sprite_name: str | None = None,
                      event_list: list[JsonDict] | None = None,
                      parent_object_name: str | None = None,
                      persistent: bool = False,
                      create_empty_event_sources: bool = True) -> None:
        obj_dir = os.path.join(self.gm_dir, "objects", name)
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content(
            name,
            sprite_name=sprite_name,
            event_list=event_list,
            parent_object_name=parent_object_name,
            persistent=persistent,
        )
        with open(os.path.join(obj_dir, name + ".yy"), "w") as f:
            f.write(yy_content)
        if create_empty_event_sources:
            for event in event_list or []:
                if event.get("isDnD") is True:
                    continue
                mapping = (
                    map_input_event(event)
                    if is_input_event(event)
                    else map_event(event)
                )
                if mapping is None or not mapping.gml_filename:
                    continue
                with open(
                    os.path.join(obj_dir, mapping.gml_filename),
                    "w",
                    encoding="utf-8",
                ):
                    pass
        if sprite_name:
            _create_fake_sprite_scene(self.godot_dir, sprite_name)

    def _reference_object_and_scripts(
        self,
        object_name: str,
        *script_names: str,
    ) -> None:
        resources: list[dict[str, dict[str, str]]] = []
        for script_name in script_names:
            script_dir = os.path.join(self.gm_dir, "scripts", script_name)
            os.makedirs(script_dir, exist_ok=True)
            with open(
                os.path.join(script_dir, f"{script_name}.yy"),
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    {
                        "%Name": script_name,
                        "name": script_name,
                        "resourceType": "GMScript",
                    },
                    f,
                )
            resources.append(
                {
                    "id": {
                        "name": script_name,
                        "path": f"scripts/{script_name}/{script_name}.yy",
                    }
                }
            )
        resources.append(
            {
                "id": {
                    "name": object_name,
                    "path": f"objects/{object_name}/{object_name}.yy",
                }
            }
        )
        with open(
            os.path.join(self.gm_dir, "Project.yyp"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "resources": resources,
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                },
                f,
            )

    def _write_object_manifest(self, *object_names: str) -> None:
        with open(
            os.path.join(self.gm_dir, "Project.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "%Name": "Project",
                    "resources": [
                        {
                            "id": {
                                "name": object_name,
                                "path": (
                                    f"objects/{object_name}/{object_name}.yy"
                                ),
                            }
                        }
                        for object_name in object_names
                    ],
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                },
                project_file,
            )

    def test_generates_gd_file(self):
        """A .gd file should be created alongside the .tscn."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        self.assertTrue(os.path.isfile(gd_path), "Expected .gd file to be generated")

    def test_script_extends_node2d(self):
        """Script should start with extends Node2D."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertTrue(content.startswith("extends Node2D"))

    def test_script_with_no_events(self):
        """Object with empty eventList still registers with the runtime instance registry."""
        self._setup_object("o_empty", event_list=[])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_empty", "o_empty.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn('GMRuntime.gml_instance_register(self, "o_empty", [])', content)
        self.assertIn("func _ready():\n\t_gm_register_instance()", content)
        self.assertIn("func _exit_tree():\n\t_gm_unregister_instance()", content)

    def test_script_records_persistent_object_state(self):
        self._setup_object("o_persist", event_list=[], persistent=True)
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_persist", "o_persist.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn("var persistent = true", content)
        self.assertIn("\tpersistent = true", content)
        self.assertIn('GMRuntime.gml_variable_instance_set(self, "persistent", persistent)', content)
        self.assertIn('set_meta("gamemaker_persistent", persistent)', content)

    def test_script_registers_parent_object_chain(self):
        self._setup_object("o_parent", event_list=[{"eventType": 0, "eventNum": 0}])
        self._setup_object("o_child", event_list=[], parent_object_name="o_parent")
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertTrue(content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertIn('GMRuntime.gml_instance_register(self, "o_child", ["o_parent"])', content)
        self.assertIn(
            "func _ready():\n\t_gm_register_instance()\n\t_gm_initialize_motion_runtime()\n\tsuper._ready()",
            content,
        )

    def test_child_object_reuses_inherited_sprite_runtime_members(self):
        self._setup_object(
            "o_parent",
            sprite_name="s_parent",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        self._setup_object(
            "o_child",
            sprite_name="s_child",
            event_list=[],
            parent_object_name="o_parent",
        )
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertTrue(content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertNotIn('const s_child = "s_child"', content)
        self.assertNotIn("const _GM_SPRITE_SCENES", content)
        self.assertNotIn("\nvar sprite_index =", content)
        self.assertNotIn("\nvar image_index =", content)
        self.assertNotIn("func _gm_apply_sprite_index():", content)
        self.assertIn("\tsprite_index = \"s_child\"\n\t_gm_initialize_sprite_runtime()", content)
        self.assertIn("\tsuper._ready()", content)

    def test_script_event_sources_use_selected_macro_configuration(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                "#if Android\n"
                "score = 11;\n"
                "#else\n"
                "score = 22;\n"
                "#endif\n"
            )

        converter = self._make_converter(macro_configuration="Android")
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("\tscore = 11", content)
        self.assertNotIn("\tscore = 22", content)

    def test_event_instance_members_use_selected_macro_configuration(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                "#if Android\n"
                "active_member = 11;\n"
                "#else\n"
                "inactive_member = 22;\n"
                "#endif\n"
            )

        self._make_converter(macro_configuration="Android").convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("var active_member", content)
        self.assertIn("\tactive_member = 11", content)
        self.assertNotIn("var inactive_member", content)
        self.assertNotIn("inactive_member = 22", content)

    def test_project_macro_from_script_expands_in_object_event(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        self._reference_object_and_scripts("o_test", "Config")
        macro_path = os.path.join(
            self.gm_dir,
            "scripts",
            "Config",
            "Config.gml",
        )
        os.makedirs(os.path.dirname(macro_path), exist_ok=True)
        with open(macro_path, "w", encoding="utf-8") as f:
            f.write(
                "#macro BASE_SCORE 8\n"
                "#macro DOUBLE_SCORE (BASE_SCORE * 2)\n"
            )
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("score = DOUBLE_SCORE;")

        self._make_converter().convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("\tscore = (GMRuntime.gml_mul(8, 2))", content)
        self.assertNotIn('"BASE_SCORE"', content)
        self.assertNotIn('"DOUBLE_SCORE"', content)

    def test_script_with_create_event(self):
        """eventType 0 should produce func _ready()."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _ready():", content)
        self.assertIn("\t_gm_register_instance()", content)

    def test_script_transpiles_create_event_gml_body(self):
        """Simple expression/operator GML bodies should populate event functions."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write("var speed = base_speed * 2; score ??= 0; score += speed div 2;")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(f"{gd_path}.gmlmap.json", "r", encoding="utf-8") as f:
            source_map = json.load(f)

        self.assertIn("func _ready():", content)
        self.assertIn(
            '\tvar speed = GMRuntime.gml_mul(GMRuntime.gml_variable_instance_get(self, "base_speed"), 2)',
            content,
        )
        self.assertIn("\tif GMRuntime.gml_is_nullish(score):\n\t\tscore = 0", content)
        self.assertIn("\tscore = GMRuntime.gml_add(score, GMRuntime.gml_int_div(speed, 2))", content)
        self.assertNotIn("\tpass", content)
        self.assertTrue(source_map["entries"])
        self.assertEqual(source_map["entries"][0]["source_path"], source_path)
        self.assertEqual(source_map["entries"][0]["event"], "_ready")
        self.assertEqual(source_map["entries"][0]["source_line"], 1)

    def test_script_transpiles_calls_to_modern_script_function_assets(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        script_dir = os.path.join(self.gm_dir, "scripts", "ending")
        os.makedirs(script_dir)
        with open(os.path.join(script_dir, "ending.yy"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "%Name": "ending",
                    "name": "ending",
                    "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                    "resourceType": "GMScript",
                },
                f,
            )
        with open(os.path.join(script_dir, "ending.gml"), "w", encoding="utf-8") as f:
            f.write("function loadending() { return 1; }\nfunction saveending() { loadending(); }\n")
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write("loadending();")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            'GMRuntime.gml_script_call(GMRuntime.gml_asset_get_index("loadending"), [], self, other)',
            content,
        )
        self.assertNotIn("\tloadending()", content)

    def test_object_events_lower_project_global_enum_members(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        self._reference_object_and_scripts("o_test", "Adding")
        script_dir = os.path.join(self.gm_dir, "scripts", "Adding")
        with open(
            os.path.join(script_dir, "Adding.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                "function Adding() constructor {\n"
                "    enum AddingOperator { equals, add = 7, multiply = 11 }\n"
                "}\n"
            )
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("choice = AddingOperator.add;")

        self._make_converter().convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("\tchoice = 7", content)
        self.assertNotIn('"AddingOperator"', content)

    def test_script_transpiles_infinity_runtime_support(self):
        """Infinity-sensitive GML should use the shared runtime support layer."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(
                "var limit = infinity; "
                "var ratio = 1 / 0; "
                "show_debug_message(string(limit));"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        runtime_path = os.path.join(self.godot_dir, "gm2godot", "gml_runtime.gd")
        self.assertTrue(os.path.isfile(runtime_path))
        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn("\tvar limit = INF", content)
        self.assertIn("\tvar ratio = GMRuntime.gml_div(1, 0)", content)
        self.assertIn(
            "\tGMRuntime.gml_show_debug_message(GMRuntime.gml_string(limit), [])",
            content,
        )

    def test_script_transpiles_string_runtime_support(self):
        """String conversion and concatenation should use the shared runtime."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write('var label = "Score: " + string(score); show_debug_message(label);')

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn(
            '\tvar label = GMRuntime.gml_add("Score: ", '
            'GMRuntime.gml_string(GMRuntime.gml_variable_instance_get(self, "score")))',
            content,
        )
        self.assertIn("\tGMRuntime.gml_show_debug_message(label, [])", content)

    def test_transpile_blocker_skips_object_and_makes_conversion_partial(self):
        self._setup_object(
            "o_blocked",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        self._setup_object(
            "o_safe",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        source_path = os.path.join(
            self.gm_dir,
            "objects",
            "o_blocked",
            "Create_0.gml",
        )
        with open(source_path, "w", encoding="utf-8") as f:
            f.write('show_message_async("Hello");')
        with open(
            os.path.join(
                self.gm_dir,
                "objects",
                "o_safe",
                "Create_0.gml",
            ),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("score = 1;")
        with open(
            os.path.join(self.gm_dir, "Test.yyp"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "%Name": "Test",
                    "resources": [
                        {
                            "id": {
                                "name": object_name,
                                "path": f"objects/{object_name}/{object_name}.yy",
                            }
                        }
                        for object_name in ("o_blocked", "o_safe")
                    ],
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                },
                f,
            )

        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
        )
        objects_enabled = MagicMock()
        objects_enabled.get.return_value = True
        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"objects": objects_enabled},
        )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(
            outcome.resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_safe",
                    "o_safe.gd",
                )
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_blocked",
                    "o_blocked.gd",
                )
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_blocked",
                    "o_blocked.tscn",
                )
            )
        )

        recorded = converter.diagnostics.diagnostics()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].code, "GM2GD-GML-TRANSPILE")
        self.assertEqual(recorded[0].api, "show_message_async")
        self.assertEqual(recorded[0].issue_number, 507)
        self.assertEqual(recorded[0].resource, "o_blocked")
        self.assertEqual(recorded[0].resource_type, "object")
        self.assertEqual(recorded[0].event, "_ready")

    def test_missing_event_source_skips_object_and_makes_conversion_partial(self):
        self._setup_object(
            "o_missing",
            event_list=[{"eventType": 0, "eventNum": 0}],
            create_empty_event_sources=False,
        )
        self._setup_object(
            "o_safe",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        self._write_object_manifest("o_missing", "o_safe")

        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
        )
        objects_enabled = MagicMock()
        objects_enabled.get.return_value = True

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"objects": objects_enabled},
        )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_safe",
                    "o_safe.gd",
                )
            )
        )
        for extension in (".gd", ".tscn"):
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        self.godot_dir,
                        "objects",
                        "o_missing",
                        "o_missing" + extension,
                    )
                )
            )

        missing = [
            diagnostic
            for diagnostic in converter.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-OBJECT-EVENT-SOURCE-MISSING"
        ]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].source_path, "objects/o_missing/Create_0.gml")
        self.assertEqual(missing[0].resource, "o_missing")
        self.assertEqual(missing[0].resource_type, "object")
        self.assertEqual(missing[0].event, "_ready")
        self.assertEqual(missing[0].manifest_entry, "eventList[0].sourceFile")

    def test_event_source_read_race_skips_object_without_partial_output(self):
        self._setup_object(
            "o_racy",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        source_path = os.path.join(
            self.gm_dir,
            "objects",
            "o_racy",
            "Create_0.gml",
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics=diagnostics)
        real_open = open

        def open_with_disappearing_event(
            path: object,
            mode: str = "r",
            *_args: object,
            **_kwargs: object,
        ) -> object:
            if (
                isinstance(path, str)
                and os.path.abspath(path) == source_path
                and "r" in mode
            ):
                raise FileNotFoundError("event source disappeared before read")
            return DEFAULT

        with patch(
            "builtins.open",
            wraps=real_open,
            side_effect=open_with_disappearing_event,
        ):
            converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(finalize_unfinished_as=None).resources,
            ConversionCounts(requested=1, executed=1, skipped=1),
        )
        for extension in (".gd", ".tscn"):
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        self.godot_dir,
                        "objects",
                        "o_racy",
                        "o_racy" + extension,
                    )
                )
            )
        read_diagnostics = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-OBJECT-EVENT-SOURCE-READ"
        ]
        self.assertEqual(len(read_diagnostics), 1)
        self.assertEqual(
            read_diagnostics[0].source_path,
            "objects/o_racy/Create_0.gml",
        )
        self.assertEqual(read_diagnostics[0].resource, "o_racy")
        self.assertEqual(read_diagnostics[0].event, "_ready")

    def test_rejected_event_source_skips_object(self):
        self._setup_object(
            "o_rejected",
            event_list=[{"eventType": 0, "eventNum": 0}],
            create_empty_event_sources=False,
        )
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_source = os.path.join(outside_dir, "Create_0.gml")
            with open(outside_source, "w", encoding="utf-8") as source_file:
                source_file.write("outside_marker = true;")
            event_source = os.path.join(
                self.gm_dir,
                "objects",
                "o_rejected",
                "Create_0.gml",
            )
            try:
                os.symlink(outside_source, event_source)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            diagnostics = DiagnosticCollector()
            converter = self._make_converter(diagnostics=diagnostics)
            converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(finalize_unfinished_as=None).resources,
            ConversionCounts(requested=1, executed=1, skipped=1),
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_rejected",
                    "o_rejected.gd",
                )
            )
        )
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-OBJECT-EVENT-SOURCE-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "objects/o_rejected/o_rejected.yy")
        self.assertEqual(rejected[0].resource, "o_rejected")
        self.assertEqual(rejected[0].event, "_ready")

    def test_zero_byte_and_dnd_events_do_not_block_object(self):
        self._setup_object(
            "o_empty_code",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        self._setup_object(
            "o_dnd",
            event_list=[{"eventType": 3, "eventNum": 0, "isDnD": True}],
        )
        converter = self._make_converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(finalize_unfinished_as=None).resources,
            ConversionCounts(requested=2, executed=2, completed=2),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_empty_code",
                    "o_empty_code.gd",
                )
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "objects",
                    "o_dnd",
                    "o_dnd.gd",
                )
            )
        )

    def test_child_event_inherited_preserves_parent_exit_boundary(self):
        """exit in an inherited parent event should not abort the child event."""
        self._setup_object("o_parent", event_list=[{"eventType": 0, "eventNum": 0}])
        self._setup_object(
            "o_child",
            event_list=[{"eventType": 0, "eventNum": 0}],
            parent_object_name="o_parent",
        )
        with open(
            os.path.join(self.gm_dir, "objects", "o_parent", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("parent_ran = true; exit; parent_after_exit = true;")
        with open(
            os.path.join(self.gm_dir, "objects", "o_child", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("child_before = true; event_inherited(); child_after = true;")

        converter = self._make_converter()
        converter.convert_all()

        parent_gd_path = os.path.join(self.godot_dir, "objects", "o_parent", "o_parent.gd")
        child_gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(parent_gd_path, "r", encoding="utf-8") as f:
            parent_content = f.read()
        with open(child_gd_path, "r", encoding="utf-8") as f:
            child_content = f.read()

        self.assertIn("func _ready():", parent_content)
        self.assertIn("\tparent_ran = true\n\treturn\n\tparent_after_exit = true", parent_content)
        self.assertTrue(child_content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertIn(
            '\tGMRuntime.gml_variable_instance_set(self, "child_before", true)\n'
            "\tsuper._ready()\n"
            '\tGMRuntime.gml_variable_instance_set(self, "child_after", true)',
            child_content,
        )

    def test_event_inherited_noops_when_parent_lacks_matching_event(self):
        self._setup_object("o_parent", event_list=[{"eventType": 3, "eventNum": 0}])
        self._setup_object(
            "o_child",
            event_list=[{"eventType": 0, "eventNum": 0}],
            parent_object_name="o_parent",
        )
        with open(
            os.path.join(self.gm_dir, "objects", "o_child", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("event_inherited(); child_after = true;")

        converter = self._make_converter()
        converter.convert_all()

        child_gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(child_gd_path, "r", encoding="utf-8") as f:
            child_content = f.read()

        self.assertIn(
            '\tpass\n\tGMRuntime.gml_variable_instance_set(self, "child_after", true)',
            child_content,
        )
        self.assertNotIn("super._ready()", child_content)

    def test_script_with_step_event(self):
        """eventType 3, eventNum 0 should produce the scheduler Step callback."""
        self._setup_object("o_test", event_list=[{"eventType": 3, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_step():", content)
        self.assertNotIn("func _process(delta):", content)

    def test_script_transpiles_topdown_step_movement(self):
        """Step polling movement should become Godot held-input movement."""
        self._setup_object("o_player", event_list=[{"eventType": 3, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_player", "Step_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(
                "if keyboard_check(vk_left) { x -= 10; }\n"
                "if keyboard_check(vk_right) { x += 10; }\n"
                "if keyboard_check(vk_up) { y -= 10; }\n"
                "if keyboard_check(vk_down) { y += 10; }\n"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn("func _on_step():", content)
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_LEFT):\n"
            "\t\tposition.x = GMRuntime.gml_sub(position.x, 10)",
            content,
        )
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_RIGHT):\n"
            "\t\tposition.x = GMRuntime.gml_add(position.x, 10)",
            content,
        )
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_UP):\n"
            "\t\tposition.y = GMRuntime.gml_sub(position.y, 10)",
            content,
        )
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_DOWN):\n"
            "\t\tposition.y = GMRuntime.gml_add(position.y, 10)",
            content,
        )

    def test_script_declares_instance_variables_shared_across_events(self):
        """Assignments without var should become reusable object member state."""
        self._setup_object(
            "o_player",
            event_list=[
                {"eventType": 0, "eventNum": 0},
                {"eventType": 3, "eventNum": 0},
            ],
        )
        object_dir = os.path.join(self.gm_dir, "objects", "o_player")
        with open(os.path.join(object_dir, "Create_0.gml"), "w", encoding="utf-8") as f:
            f.write("superSpeed = 0\nfaster = false;")
        with open(os.path.join(object_dir, "Step_0.gml"), "w", encoding="utf-8") as f:
            f.write(
                "if keyboard_check(vk_shift) { faster = true } else { faster = false }\n"
                "if faster = true { superSpeed = 20 }\n"
                "if keyboard_check(vk_left) { x -= superSpeed; }\n"
                "superSpeed = 10;"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn("var faster", content)
        self.assertIn("var superSpeed", content)
        self.assertIn("\tsuperSpeed = 0", content)
        self.assertIn("\tif GMRuntime.gml_keyboard_check(KEY_SHIFT):", content)
        self.assertIn("\tif GMRuntime.gml_eq(faster, true):", content)
        self.assertIn("\t\tposition.x = GMRuntime.gml_sub(position.x, superSpeed)", content)
        self.assertNotIn("Could not transpile", "\n".join(str(msg) for msg in self.logs))

    def test_script_assigned_instance_variables_are_declared_on_objects(self):
        self._setup_object("o_player", event_list=[{"eventType": 3, "eventNum": 0}])
        self._reference_object_and_scripts("o_player", "scr_controls")
        scripts_dir = os.path.join(self.gm_dir, "scripts", "scr_controls")
        os.makedirs(scripts_dir, exist_ok=True)
        with open(os.path.join(scripts_dir, "scr_controls.gml"), "w", encoding="utf-8") as f:
            f.write(
                "function scr_controls(local_param) {\n"
                "    var local_only = 0;\n"
                "    local_param = 1;\n"
                "    leftcontrols = 0;\n"
                "    rightcontrols = 1;\n"
                "}\n"
            )

        object_dir = os.path.join(self.gm_dir, "objects", "o_player")
        with open(os.path.join(object_dir, "Step_0.gml"), "w", encoding="utf-8") as f:
            f.write(
                "scr_controls(0);\n"
                "if leftcontrols = 0 { key_left = true; }\n"
                "if rightcontrols = 1 { key_right = true; }\n"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("var leftcontrols", content)
        self.assertIn("var rightcontrols", content)
        self.assertNotIn("var local_only", content)
        self.assertNotIn("var local_param", content)
        self.assertIn("if GMRuntime.gml_eq(leftcontrols, 0):", content)
        self.assertIn("if GMRuntime.gml_eq(rightcontrols, 1):", content)

    def test_script_assigned_instance_variables_are_inherited_by_child_objects(self):
        self._setup_object("o_parent", event_list=[])
        self._setup_object(
            "o_child",
            event_list=[{"eventType": 3, "eventNum": 0}],
            parent_object_name="o_parent",
        )
        scripts_dir = os.path.join(self.gm_dir, "scripts", "scr_controls")
        os.makedirs(scripts_dir, exist_ok=True)
        with open(os.path.join(scripts_dir, "scr_controls.gml"), "w", encoding="utf-8") as f:
            f.write("function scr_controls() { leftcontrols = 0; }\n")
        with open(
            os.path.join(self.gm_dir, "objects", "o_child", "Step_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("scr_controls(); if leftcontrols = 0 { key_left = true; }")
        self._reference_object_and_scripts("o_child", "scr_controls")
        project_path = os.path.join(self.gm_dir, "Project.yyp")
        with open(project_path, "r", encoding="utf-8") as f:
            project_data = json.load(f)
        project_data["resources"].append(
            {
                "id": {
                    "name": "o_parent",
                    "path": "objects/o_parent/o_parent.yy",
                }
            }
        )
        with open(project_path, "w", encoding="utf-8") as f:
            json.dump(project_data, f)

        converter = self._make_converter()
        converter.convert_all()

        parent_gd_path = os.path.join(self.godot_dir, "objects", "o_parent", "o_parent.gd")
        child_gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(parent_gd_path, "r", encoding="utf-8") as f:
            parent_content = f.read()
        with open(child_gd_path, "r", encoding="utf-8") as f:
            child_content = f.read()

        self.assertIn("var leftcontrols", parent_content)
        self.assertNotIn("var leftcontrols", child_content)
        self.assertTrue(child_content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertIn(
            'if GMRuntime.gml_eq(GMRuntime.gml_variable_instance_get(self, "leftcontrols"), 0):',
            child_content,
        )

    def test_only_referenced_configured_script_assignments_are_declared_on_objects(self):
        self._setup_object("o_player", event_list=[{"eventType": 3, "eventNum": 0}])
        self._reference_object_and_scripts("o_player", "scr_active")

        active_script_dir = os.path.join(self.gm_dir, "scripts", "scr_active")
        with open(
            os.path.join(active_script_dir, "scr_active.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                "function scr_active() {\n"
                "#if Android\n"
                "    configured_member = 1;\n"
                "#else\n"
                "    inactive_member = 1;\n"
                "#endif\n"
                "}\n"
            )

        orphan_script_dir = os.path.join(self.gm_dir, "scripts", "scr_orphan")
        os.makedirs(orphan_script_dir)
        with open(
            os.path.join(orphan_script_dir, "scr_orphan.yy"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "%Name": "scr_orphan",
                    "name": "scr_orphan",
                    "resourceType": "GMScript",
                },
                f,
            )
        with open(
            os.path.join(orphan_script_dir, "scr_orphan.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("function scr_orphan() { orphan_member = 1; }\n")

        with open(
            os.path.join(self.gm_dir, "objects", "o_player", "Step_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("scr_active();")

        self._make_converter(macro_configuration="Android").convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("var configured_member", content)
        self.assertNotIn("var inactive_member", content)
        self.assertNotIn("var orphan_member", content)

    def test_native_member_instance_variables_use_dynamic_storage(self):
        self._setup_object(
            "o_box",
            event_list=[
                {"eventType": 0, "eventNum": 0},
                {"eventType": 8, "eventNum": 0},
            ],
        )
        object_dir = os.path.join(self.gm_dir, "objects", "o_box")
        with open(os.path.join(object_dir, "Create_0.gml"), "w", encoding="utf-8") as f:
            f.write("draw = true;")
        with open(os.path.join(object_dir, "Draw_0.gml"), "w", encoding="utf-8") as f:
            f.write("if draw { draw_text(0, 0, \"on\"); }")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_box", "o_box.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("\n\nvar draw\n", content)
        self.assertIn('GMRuntime.gml_variable_instance_set(self, "draw", true)', content)
        self.assertIn(
            'if GMRuntime.gml_bool(GMRuntime.gml_variable_instance_get(self, "draw")):',
            content,
        )

    def test_failed_event_prevents_partial_object_output(self):
        self._setup_object(
            "o_stats",
            event_list=[
                {"eventType": 0, "eventNum": 0},
                {"eventType": 8, "eventNum": 0},
            ],
        )
        object_dir = os.path.join(self.gm_dir, "objects", "o_stats")
        with open(os.path.join(object_dir, "Create_0.gml"), "w", encoding="utf-8") as f:
            f.write('stats_rank_label = "A"; return 1;')
        with open(os.path.join(object_dir, "Draw_0.gml"), "w", encoding="utf-8") as f:
            f.write("draw_text(0, 0, stats_rank_label);")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_stats", "o_stats.gd")
        tscn_path = os.path.join(
            self.godot_dir,
            "objects",
            "o_stats",
            "o_stats.tscn",
        )

        self.assertFalse(os.path.exists(gd_path))
        self.assertFalse(os.path.exists(tscn_path))
        self.assertEqual(
            converter.conversion_step_result(finalize_unfinished_as=None).resources,
            ConversionCounts(requested=1, executed=1, skipped=1),
        )
        self.assertIn("Could not transpile", "\n".join(str(msg) for msg in self.logs))

    def test_script_supports_sprite_and_image_index(self):
        """sprite_index and image_index should map to generated sprite runtime state."""
        self._setup_object(
            "o_player",
            sprite_name="s_player",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        _create_fake_sprite_scene(self.godot_dir, "s_enemy")
        source_path = os.path.join(self.gm_dir, "objects", "o_player", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write("image_index = 2; sprite_index = s_enemy;")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('const s_enemy = "s_enemy"', content)
        self.assertIn('const s_player = "s_player"', content)
        self.assertIn('"s_enemy": preload("res://sprites/s_enemy/s_enemy.tscn")', content)
        self.assertIn('"s_player": preload("res://sprites/s_player/s_player.tscn")', content)
        self.assertIn('var sprite_index = "s_player":', content)
        self.assertIn('var image_index = 0.0:', content)
        self.assertIn('func _gm_apply_sprite_index():', content)
        self.assertIn('func _gm_apply_image_index():', content)
        self.assertIn('if has_meta("gamemaker_image_index"):', content)
        self.assertIn("\t_gm_initialize_sprite_runtime()\n\timage_index = 2", content)
        self.assertIn("\tsprite_index = s_enemy", content)
        self.assertNotIn("\n\nvar image_index\n", content)
        self.assertNotIn("\n\nvar sprite_index\n", content)

    def test_script_with_begin_step(self):
        """eventType 3, eventNum 1 should produce the scheduler Begin Step callback."""
        self._setup_object("o_test", event_list=[{"eventType": 3, "eventNum": 1}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_begin_step():", content)
        self.assertNotIn("func _physics_process(delta):", content)

    def test_script_with_draw_event(self):
        """eventType 8, eventNum 0 should produce func _draw()."""
        self._setup_object("o_test", event_list=[{"eventType": 8, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _draw():", content)

    def test_script_with_cleanup_event(self):
        """eventType 12 should produce func _exit_tree()."""
        self._setup_object("o_test", event_list=[{"eventType": 12, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _exit_tree():", content)

    def test_script_with_alarm_event(self):
        """eventType 2 should produce func _on_alarm_N()."""
        self._setup_object("o_test", event_list=[{"eventType": 2, "eventNum": 3}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_alarm_3():", content)

    def test_event_source_uses_runtime_alarm_array_access(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("alarm[0] = 3;\nnext_alarm = alarm[0];")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("GMRuntime.gml_alarm_set(self, 0, 3)", content)
        self.assertIn("next_alarm = GMRuntime.gml_alarm_get(self, 0)", content)
        self.assertNotIn("alarm[", content)

    def test_script_with_collision_event(self):
        """eventType 4 with collisionObjectId should produce func _on_collision_NAME()."""
        self._setup_object("o_test", event_list=[
            {"eventType": 4, "eventNum": 0, "collisionObjectId": {"name": "o_bullet"}}
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_collision_event_bindings():", content)
        self.assertIn('{"target_object": "o_bullet", "method": "_on_collision_o_bullet"}', content)
        self.assertIn("func _on_collision_o_bullet():", content)

    def test_named_collision_event_source_file_transpiles_body(self):
        self._setup_object("o_test", event_list=[
            {"eventType": 4, "eventNum": 0, "collisionObjectId": {"name": "o_bullet"}}
        ])
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Collision_o_bullet.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("collision_seen = true;")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("func _on_collision_o_bullet():", content)
        self.assertIn("\tcollision_seen = true", content)

    def test_collision_event_source_falls_back_to_numeric_filename(self):
        self._setup_object("o_test", event_list=[
            {"eventType": 4, "eventNum": 0, "collisionObjectId": {"name": "o_bullet"}}
        ], create_empty_event_sources=False)
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Collision_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("legacy_collision_seen = true;")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("func _on_collision_o_bullet():", content)
        self.assertIn("\tlegacy_collision_seen = true", content)

    def test_missing_collision_event_source_records_diagnostic(self):
        self._setup_object("o_test", event_list=[
            {"eventType": 4, "eventNum": 0, "collisionObjectId": {"name": "o_bullet"}}
        ], create_empty_event_sources=False)
        diagnostics = DiagnosticCollector()
        converter = ObjectConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        )
        converter.convert_all()

        missing_diagnostics = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-OBJECT-MISSING-COLLISION-EVENT-SOURCE"
        ]
        self.assertEqual(len(missing_diagnostics), 1)
        self.assertEqual(missing_diagnostics[0].resource, "o_test")
        self.assertEqual(missing_diagnostics[0].event, "_on_collision_o_bullet")
        self.assertIn("Collision_o_bullet.gml", missing_diagnostics[0].message)
        self.assertIn("Collision_0.gml", missing_diagnostics[0].message)

    def test_script_with_multiple_events(self):
        """Multiple events should produce multiple function stubs."""
        self._setup_object("o_test", event_list=[
            {"eventType": 0, "eventNum": 0},
            {"eventType": 3, "eventNum": 0},
            {"eventType": 1, "eventNum": 0},
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _ready():", content)
        self.assertIn("func _on_step():", content)
        self.assertIn("func _on_destroy():", content)

    def test_input_events_merged(self):
        """Mouse and keyboard events should produce GMInput dispatch bindings."""
        self._setup_object("o_test", event_list=[
            {"eventType": 6, "eventNum": 4},   # Mouse left click
            {"eventType": 9, "eventNum": 32},   # KeyPress space
            {"eventType": 10, "eventNum": 13},  # KeyRelease enter
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_input_event_bindings():", content)
        self.assertIn("func _gm_input_mouse_4():", content)
        self.assertIn("func _gm_input_key_press_32():", content)
        self.assertIn("func _gm_input_key_release_13():", content)
        self.assertNotIn("func _input(event):", content)

    def test_mouse_event_ranges_merged(self):
        """All ev_mouse ranges should be listed in one binding table."""
        self._setup_object("o_test", event_list=[
            {"eventType": 6, "eventNum": 0},
            {"eventType": 6, "eventNum": 11},
            {"eventType": 6, "eventNum": 50},
            {"eventType": 6, "eventNum": 58},
            {"eventType": 6, "eventNum": 60},
            {"eventType": 6, "eventNum": 61},
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_input_event_bindings():", content)
        self.assertIn("func _gm_input_mouse_0():", content)
        self.assertIn("func _gm_input_mouse_61():", content)
        self.assertNotIn("func _input(event):", content)

    def test_input_event_code_files_transpile_to_dispatch_methods(self):
        """Input .gml source should load into the event-specific GMInput method."""
        self._setup_object("o_test", event_list=[
            {"eventType": 9, "eventNum": 32},
            {"eventType": 13, "eventNum": 0},
        ])
        with open(os.path.join(self.gm_dir, "objects", "o_test", "KeyPress_32.gml"), "w", encoding="utf-8") as f:
            f.write("pressed_space = true;")
        with open(os.path.join(self.gm_dir, "objects", "o_test", "Gesture_0.gml"), "w", encoding="utf-8") as f:
            f.write('tap_x = event_data[? "posX"];')

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_input_key_press_32():", content)
        self.assertIn("\tpressed_space = true", content)
        self.assertIn("func _gm_input_gesture_0():", content)
        self.assertIn('tap_x = GMRuntime.gml_ds_map_find_value(GMRuntime.gml_builtin_global("event_data"), "posX")', content)
        self.assertIn('{"event_type": 9, "event_num": 32, "method": "_gm_input_key_press_32"}', content)

    def test_script_attached_to_tscn(self):
        """The .tscn file should reference the .gd script."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('type="Script"', content)
        self.assertIn('o_test.gd', content)
        self.assertIn('script = ExtResource', content)

    def test_load_steps_script_only(self):
        """load_steps should be 2 when only script (no sprite)."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('load_steps=2', content)

    def test_load_steps_sprite_and_script(self):
        """load_steps should be 3 when both sprite and script are present."""
        self._setup_object("o_test", sprite_name="s_test")
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('load_steps=3', content)
        self.assertIn('PackedScene', content)
        self.assertIn('type="Script"', content)

    def test_function_ordering(self):
        """Functions should be in canonical order: lifecycle, input, custom."""
        self._setup_object("o_test", event_list=[
            {"eventType": 2, "eventNum": 0},   # Alarm (custom)
            {"eventType": 6, "eventNum": 4},   # Mouse (input)
            {"eventType": 3, "eventNum": 0},   # Step (lifecycle)
            {"eventType": 0, "eventNum": 0},   # Create (lifecycle)
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        ready_pos = content.index("_ready")
        step_pos = content.index("_on_step")
        input_pos = content.index("_gm_input_event_bindings")
        alarm_pos = content.index("_on_alarm")
        self.assertLess(ready_pos, step_pos)
        self.assertLess(step_pos, input_pos)
        self.assertLess(input_pos, alarm_pos)

    def test_script_with_destroy_event(self):
        """eventType 1 should produce func _on_destroy()."""
        self._setup_object("o_test", event_list=[{"eventType": 1, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_destroy():", content)

    def test_script_with_other_event(self):
        """eventType 7 should produce func _on_other_N()."""
        self._setup_object("o_test", event_list=[{"eventType": 7, "eventNum": 26}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_other_26():", content)

    def test_script_with_no_more_lives_event(self):
        """eventType 7, eventNum 6 should add the legacy lives setter."""
        self._setup_object("o_test", event_list=[{"eventType": 7, "eventNum": 6}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("var lives = 0:", content)
        self.assertIn("func _on_no_more_lives():", content)

    def test_script_with_close_button_event(self):
        """eventType 7, eventNum 30 should generate close request handling."""
        self._setup_object("o_test", event_list=[{"eventType": 7, "eventNum": 30}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("get_tree().auto_accept_quit = false", content)
        self.assertIn("func _notification(what):", content)
        self.assertIn("NOTIFICATION_WM_CLOSE_REQUEST", content)

    def test_script_with_draw_gui_event(self):
        """eventType 8, eventNum 64 should produce func _on_draw_gui()."""
        self._setup_object("o_test", event_list=[{"eventType": 8, "eventNum": 64}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_draw_gui():", content)

    def test_unknown_event_type(self):
        """Unknown event types should produce safe fallback function names."""
        self._setup_object("o_test", event_list=[{"eventType": 99, "eventNum": 5}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_event_99_5():", content)


class TestParseObjectYYEvents(unittest.TestCase):
    """Test that _parse_object_yy extracts event lists."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_object_yy(self, object_name: str, content: str) -> None:
        obj_dir = os.path.join(self.gm_dir, "objects", object_name)
        os.makedirs(obj_dir, exist_ok=True)
        with open(os.path.join(obj_dir, object_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_event_list(self):
        """event_list should be included in parse result."""
        content = _make_object_yy_content("o_test", event_list=[
            {"eventType": 0, "eventNum": 0},
            {"eventType": 3, "eventNum": 0},
        ])
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result["event_list"]), 2)
        self.assertEqual(result["event_list"][0]["eventType"], 0)
        self.assertEqual(result["event_list"][1]["eventType"], 3)

    def test_empty_event_list(self):
        """Empty event list should parse as empty list."""
        content = _make_object_yy_content("o_test")
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["event_list"], [])

    def test_event_with_collision_object(self):
        """Collision events should preserve collisionObjectId."""
        content = _make_object_yy_content("o_test", event_list=[
            {"eventType": 4, "eventNum": 0, "collisionObjectId": {"name": "o_enemy"}},
        ])
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result["event_list"]), 1)
        self.assertEqual(result["event_list"][0]["collisionObjectId"]["name"], "o_enemy")


class TestObjectGeneratedPathCollisions(unittest.TestCase):
    def test_emitted_objects_match_collision_safe_registry_paths(self) -> None:
        gm_dir = tempfile.mkdtemp()
        godot_dir = tempfile.mkdtemp()
        try:
            names = ("FooBar", "foo_bar")
            resources: list[dict[str, object]] = []
            for name in names:
                object_dir = os.path.join(gm_dir, "objects", name)
                os.makedirs(object_dir)
                with open(
                    os.path.join(object_dir, name + ".yy"),
                    "w",
                    encoding="utf-8",
                ) as object_file:
                    object_file.write(_make_object_yy_content(name))
                resources.append(
                    {"id": {"name": name, "path": f"objects/{name}/{name}.yy"}}
                )
            with open(
                os.path.join(gm_dir, "CollisionObjects.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump({"resources": resources, "RoomOrderNodes": []}, project_file)

            ObjectConverter(
                gm_dir,
                godot_dir,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=2,
            ).convert_all()
            entries = AssetRegistryConverter(
                gm_dir,
                godot_dir,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
            ).build_entries()
            object_paths = {
                entry.name: entry.godot_path
                for entry in entries
                if entry.kind == "objects"
            }

            self.assertEqual(set(object_paths), set(names))
            self.assertEqual(len(set(object_paths.values())), len(names))
            for name, scene_path in object_paths.items():
                scene_file = os.path.join(
                    godot_dir,
                    *scene_path.removeprefix("res://").split("/"),
                )
                script_file = os.path.splitext(scene_file)[0] + ".gd"
                self.assertTrue(os.path.isfile(scene_file), scene_path)
                self.assertTrue(os.path.isfile(script_file), script_file)
                with open(scene_file, "r", encoding="utf-8") as generated_scene:
                    self.assertIn(f'[node name="{name}" type="Node2D"]', generated_scene.read())
        finally:
            shutil.rmtree(gm_dir)
            shutil.rmtree(godot_dir)


if __name__ == "__main__":
    unittest.main()
