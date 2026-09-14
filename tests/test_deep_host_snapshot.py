from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from src.deep.host_snapshot import build_host_snapshot, write_host_snapshot


class DeepHostSnapshotTests(unittest.TestCase):
    def test_resource_sidecars_and_api_inventory_are_exported_without_source_writes(self) -> None:
        source = Path(__file__).parent / "fixtures/part2/projects/resource_matrix"
        before = {str(path): path.read_bytes() for path in source.rglob("*") if path.is_file()}
        snapshot = build_host_snapshot(str(source))
        inventory = cast(dict[str, Any], snapshot["inventory"])
        resources = cast(list[dict[str, Any]], inventory["resources"])
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertTrue(snapshot["gmlApiEntries"])
        self.assertTrue(any(row["kind"] == "objects" for row in resources))
        self.assertTrue(any(str(path).endswith(".gml") for row in resources for path in row["sourcePaths"]))
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
