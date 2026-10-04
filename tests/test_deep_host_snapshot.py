from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonArray, JsonObject, JsonValue
from src.conversion.project_manifest import GameMakerProjectManifest
from src.conversion.resource_index import GameMakerResourceIndex, IndexedRoom
from src.conversion.resource_models import (
    GameMakerResourceModels,
    ObjectModel,
    ProjectModel,
    SpriteModel,
)
from src.deep.host_snapshot import build_host_snapshot, write_host_snapshot
from src.deep.snapshot_resources import inventory_resources


class DeepHostSnapshotTests(unittest.TestCase):
    def json_object(self, value: JsonValue) -> JsonObject:
        if not isinstance(value, dict):
            self.fail(f"Expected an object, got {type(value).__name__}")
        return value

    def json_array(self, value: JsonValue) -> JsonArray:
        if not isinstance(value, list):
            self.fail(f"Expected an array, got {type(value).__name__}")
        return value

    def inventory(self, models: GameMakerResourceModels,
                  rooms: tuple[IndexedRoom, ...] = ()) -> JsonObject:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            index = GameMakerResourceIndex(temporary, temporary, log_callback=lambda _message: None)
            index.rooms = {room.name: room for room in rooms}
            index.room_order = [room.name for room in rooms]
            return inventory_resources(source, GameMakerProjectManifest("Project", None), models, index)

    def test_resource_sidecars_and_api_inventory_are_exported_without_source_writes(self) -> None:
        source = Path(__file__).parent / "fixtures/part2/projects/resource_matrix"
        before = {str(path): path.read_bytes() for path in source.rglob("*") if path.is_file()}
        snapshot = build_host_snapshot(str(source))
        inventory = self.json_object(snapshot["inventory"])
        resources = [self.json_object(row) for row in self.json_array(inventory["resources"])]
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertTrue(snapshot["gmlApiEntries"])
        self.assertTrue(any(row["kind"] == "objects" for row in resources))
        self.assertTrue(any(str(path).endswith(".gml") for row in resources
                            for path in self.json_array(row["sourcePaths"])))
        self.assertEqual(before, {str(path): path.read_bytes() for path in source.rglob("*") if path.is_file()})
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "host.json"
            write_host_snapshot(str(source), str(destination))
            self.assertEqual(json.loads(destination.read_text()), snapshot)

    def test_snapshot_cannot_be_written_into_source(self) -> None:
        source = Path(__file__).parent / "fixtures/part2/projects/resource_matrix"
        with self.assertRaisesRegex(ValueError, "outside"):
            write_host_snapshot(str(source), str(source / "deep.json"))

    def test_godot_project_is_not_a_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, "project.godot").write_text("config_version=5\n")
            with self.assertRaisesRegex(ValueError, "GameMaker"):
                build_host_snapshot(temporary)

    def test_event_and_frame_rows_filter_malformed_entries_without_mutating_unknown_data(self) -> None:
        raw = self.json_object(decode_gamemaker_json(
            '{"eventList":[null,7,[],{"eventType":3,"eventNum":0,'
            '"future":{"nullable":null,"rows":[false,{"next":1}]}},'
            '{"eventType":0,"eventNum":0,"isDnD":true},'
            '{"eventType":99,"eventNum":2}],'
            '"frames":[null,"bad",{}, {"future":null}]}',
            source_path="objects/Forward.yy",
        ).value)
        original = json.dumps(raw)
        events = self.json_array(raw["eventList"])
        event = self.json_object(events[3])
        unknown = event["future"]
        models = GameMakerResourceModels(
            ProjectModel("Project", None, "GMProject", "2.0", 2),
            objects=(ObjectModel("Forward", "objects", "GMObject", "", "", 0, raw_data=raw),),
            sprites=(SpriteModel("Frames", "sprites", "GMSprite", "", "", 1, raw_data=raw),),
        )
        inventory = self.inventory(models)
        objects = self.json_array(inventory["objects"])
        exported = self.json_array(self.json_object(objects[0])["events"])
        self.assertEqual(exported, [
            {"eventType": 3, "eventNum": 0, "file": "Step_0.gml"},
            {"eventType": 0, "eventNum": 0, "file": None},
            {"eventType": 99, "eventNum": 2, "file": "Event99_2.gml"},
        ])
        self.assertEqual(self.json_object(self.json_array(inventory["sprites"])[0])["frameCount"], 2)
        self.assertIs(models.objects[0].raw_data, raw)
        self.assertIs(event["future"], unknown)
        self.assertEqual(json.dumps(raw), original)

    def test_malformed_event_keys_keep_native_failure_policy(self) -> None:
        events: JsonArray = [{"eventType": []}, {"eventType": 0, "eventNum": {}}]
        for event in events:
            with self.subTest(event=event):
                raw: JsonObject = {"eventList": [event]}
                models = GameMakerResourceModels(
                    ProjectModel("Project", None, "GMProject", "2.0", 1),
                    objects=(ObjectModel("Bad", "objects", "GMObject", "", "", 0, raw_data=raw),),
                )
                with self.assertRaises(TypeError):
                    self.inventory(models)

    def test_room_instance_order_and_nulls_keep_layer_preorder_and_stable_ties(self) -> None:
        layers: JsonArray = [None, {"resourceType": "GMRInstanceLayer", "%Name": "First", "depth": 12,
            "instances": [None, {"name": "unlisted", "x": True, "y": float("nan"),
                                 "objectId": {"name": "Object"}},
                          {"name": "second", "x": 2, "y": 3}]},
            {"resourceType": "GMRInstanceLayer", "name": "Last", "depth": False,
             "instances": [{"%Name": "first", "x": -4.5, "y": 6},
                           {"name": "also_unlisted", "objectId": None}]}]
        room = IndexedRoom("Room", "", "", "", layers=layers,
                           instance_creation_order=[None, {"name": "first"}, {"%Name": "second"}])
        models = GameMakerResourceModels(ProjectModel("Project", None, "GMProject", "2.0", 1))
        exported = self.json_object(self.json_array(self.inventory(models, (room,))["rooms"])[0])
        instances = [self.json_object(row) for row in self.json_array(exported["instances"])]
        self.assertEqual([row["name"] for row in instances], ["first", "second", "unlisted", "also_unlisted"])
        self.assertEqual(instances[0], {"name": "first", "objectName": None, "x": -4.5, "y": 6})
        self.assertEqual(instances[2], {"name": "unlisted", "objectName": "Object", "x": None, "y": None})
        self.assertEqual(instances[3], {"name": "also_unlisted", "objectName": None, "x": None, "y": None})
        self.assertEqual(exported["layers"], [
            {"name": "First", "resourceType": "GMRInstanceLayer", "depth": 12, "order": 0},
            {"name": "Last", "resourceType": "GMRInstanceLayer", "depth": None, "order": 1},
        ])
        self.assertIs(room.layers, layers)

    def test_malformed_room_collection_values_are_not_relabelled_as_typed_rows(self) -> None:
        malformed: JsonArray = [None, True, 3, "rows", {"future": None}]
        models = GameMakerResourceModels(ProjectModel("Project", None, "GMProject", "2.0", 1))
        for value in malformed:
            with self.subTest(value=value):
                room = IndexedRoom("Room", "", "", "", layers=value, instance_creation_order=value)
                exported = self.json_object(self.json_array(self.inventory(models, (room,))["rooms"])[0])
                self.assertEqual(exported["instances"], [])
                self.assertEqual(exported["layers"], [])
                self.assertIs(room.layers, value)

    def test_room_coordinate_numbers_reject_bool_bad_shapes_and_nonfinite_values(self) -> None:
        rejected: JsonArray = [True, False, float("nan"), float("inf"), float("-inf"), "3", None, []]
        models = GameMakerResourceModels(ProjectModel("Project", None, "GMProject", "2.0", 1))
        for value in rejected:
            with self.subTest(value=value):
                room = IndexedRoom("Room", "", "", "", layers=[
                    {"resourceType": "GMRInstanceLayer", "instances": [{"x": value, "y": 2}]}])
                exported = self.json_object(self.json_array(self.inventory(models, (room,))["rooms"])[0])
                instance = self.json_object(self.json_array(exported["instances"])[0])
                self.assertIsNone(instance["x"])
                self.assertEqual(instance["y"], 2)

    def test_native_huge_integer_overflow_is_not_silently_filtered(self) -> None:
        models = GameMakerResourceModels(ProjectModel("Project", None, "GMProject", "2.0", 1))
        base = IndexedRoom("Room", "", "", "")
        for layers in (
            [{"depth": 10 ** 1000}],
            [{"resourceType": "GMRInstanceLayer", "instances": [{"x": 10 ** 1000}]}],
        ):
            with self.subTest(layers=layers):
                with self.assertRaises(OverflowError):
                    self.inventory(models, (replace(base, layers=layers),))

    def test_atomic_writer_keeps_recursive_null_unknown_values_and_existing_source(self) -> None:
        payload: JsonObject = {"schemaVersion": 1, "future": {"nullable": None, "values": [False, 10 ** 100, {}]}}
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary, "source")
            source.mkdir()
            original = source / "Project.yyp"
            original.write_text("{}", encoding="utf-8")
            destination = Path(temporary, "snapshot.json")
            destination.write_text("old snapshot", encoding="utf-8")
            with patch("src.deep.host_snapshot.build_host_snapshot", return_value=payload):
                write_host_snapshot(str(source), str(destination))
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), payload)
            self.assertEqual(original.read_text(encoding="utf-8"), "{}")
            self.assertEqual(sorted(path.name for path in Path(temporary).iterdir()), ["snapshot.json", "source"])

    def test_atomic_writer_nonfinite_rejection_preserves_destination_and_removes_temporary(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary, "source")
                source.mkdir()
                destination = Path(temporary, "snapshot.json")
                destination.write_bytes(b"unchanged")
                payload: JsonObject = {"schemaVersion": 1, "future": {"value": value}}
                with patch("src.deep.host_snapshot.build_host_snapshot", return_value=payload):
                    with self.assertRaisesRegex(ValueError, "Out of range float"):
                        write_host_snapshot(str(source), str(destination))
                self.assertEqual(destination.read_bytes(), b"unchanged")
                self.assertEqual(sorted(path.name for path in Path(temporary).iterdir()), ["snapshot.json", "source"])

    def test_atomic_replace_error_propagates_identity_and_cleans_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary, "source")
            source.mkdir()
            destination = Path(temporary, "snapshot.json")
            destination.write_bytes(b"unchanged")
            error = OSError("replace failed")
            with patch("src.deep.host_snapshot.build_host_snapshot", return_value={"schemaVersion": 1}), \
                    patch("src.deep.host_snapshot.os.replace", side_effect=error):
                with self.assertRaises(OSError) as caught:
                    write_host_snapshot(str(source), str(destination))
            self.assertIs(caught.exception, error)
            self.assertEqual(destination.read_bytes(), b"unchanged")
            self.assertEqual(sorted(path.name for path in Path(temporary).iterdir()), ["snapshot.json", "source"])
