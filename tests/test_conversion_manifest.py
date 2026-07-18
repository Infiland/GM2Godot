from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from src import cli
from src.conversion import conversion_manifest as conversion_manifest_module
from src.conversion.architecture_policy import ARCHITECTURE_POLICY_RELATIVE_PATH
from src.conversion.asset_registry import AssetRegistryConverter, AssetRegistryEntry
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_MANIFEST_RELATIVE_PATH,
    build_conversion_manifest,
    capture_conversion_output_snapshot,
    write_conversion_artifacts,
)
from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepLedger,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "golden" / "basic_scripts"


class TestConversionManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(
            self.temp_dir,
            onexc=self._retry_windows_read_only_cleanup,
        )

    @staticmethod
    def _retry_windows_read_only_cleanup(
        function: Callable[..., object],
        path: str,
        error: BaseException,
    ) -> None:
        if not isinstance(error, PermissionError):
            raise error
        path_stat = os.lstat(path)
        path_mode = stat.S_IMODE(path_stat.st_mode)
        if not stat.S_ISREG(path_stat.st_mode) or path_mode & stat.S_IWRITE:
            raise error
        os.chmod(path, path_mode | stat.S_IWRITE)
        function(path)

    def test_convert_emits_deterministic_manifest_with_source_and_path_metadata(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        (godot_dir / "project.godot").write_text(
            '[application]\nconfig/name="Manifest Fixture"\n',
            encoding="utf-8",
        )

        exit_code = cli.main(
            [
                "convert",
                "--gm-project",
                str(FIXTURE_ROOT),
                "--godot-project",
                str(godot_dir),
                "--target-platform",
                "windows",
                "--only",
                "scripts",
                "--max-warnings",
                "0",
            ]
        )

        self.assertEqual(exit_code, 0)
        manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        resources = cast(list[dict[str, object]], manifest["resources"])
        generated_files = cast(list[dict[str, object]], manifest["generated_files"])

        self.assertEqual(manifest["format_version"], 2)
        self.assertEqual(
            cast(dict[str, object], manifest["conversion"])["state"],
            "success",
        )
        self.assertFalse(
            cast(dict[str, object], manifest["conversion"])["cancelled"]
        )
        self.assertEqual(manifest["target_platform"], "windows")
        self.assertEqual(manifest["enabled_converters"], ["scripts"])
        self.assertEqual(
            cast(dict[str, object], manifest["source_project"])["ide_version"],
            "",
        )
        self.assertEqual(
            cast(dict[str, object], manifest["architecture_policies"])["target_platform"],
            "windows",
        )
        self.assertTrue((godot_dir / ARCHITECTURE_POLICY_RELATIVE_PATH).is_file())
        self.assertTrue(
            any(
                resource["name"] == "scr_add"
                and resource["source_path"] == "scripts/scr_add/scr_add.yy"
                and resource["godot_path"] == "res://scripts/game/scr_add.gd"
                for resource in resources
            )
        )
        self.assertTrue(
            any(
                generated["path"] == "scripts/game/scr_add.gd.gmlmap.json"
                and generated["kind"] == "source_map"
                for generated in generated_files
            )
        )
        self.assertTrue(
            any(
                generated["path"] == ARCHITECTURE_POLICY_RELATIVE_PATH.replace("\\", "/")
                and generated["kind"] == "report"
                for generated in generated_files
            )
        )
        self.assertEqual(manifest["path_diagnostics"], [])
        attempt = json.loads(
            (godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH).read_text(
                encoding="utf-8"
            )
        )
        canonical_record = cast(dict[str, object], attempt["canonical_manifest"])
        self.assertEqual(canonical_record["status"], "updated")
        self.assertTrue(canonical_record["updated"])
        self.assertEqual(
            canonical_record["sha256"],
            "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        )

    def test_manifest_reports_collision_safe_generated_paths(self) -> None:
        gm_dir = self.temp_dir / "gm"
        godot_dir = self.temp_dir / "godot"
        gm_dir.mkdir()
        godot_dir.mkdir()
        (gm_dir / "CollisionTest.yyp").write_text(
            json.dumps(
                {
                    "resources": [
                        {"id": {"name": "Scr Spawn", "path": "scripts/Scr Spawn/Scr Spawn.yy"}},
                        {"id": {"name": "scr_spawn", "path": "scripts/scr_spawn/scr_spawn.yy"}},
                    ],
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                }
            ),
            encoding="utf-8",
        )
        for script_name in ("Scr Spawn", "scr_spawn"):
            script_dir = gm_dir / "scripts" / script_name
            script_dir.mkdir(parents=True)
            (script_dir / f"{script_name}.yy").write_text(
                json.dumps(
                    {
                        "%Name": script_name,
                        "name": script_name,
                        "parent": {"name": "Scripts", "path": "folders/Scripts.yy"},
                        "resourceType": "GMScript",
                    }
                ),
                encoding="utf-8",
            )

        manifest = build_conversion_manifest(
            str(gm_dir),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=["scripts"],
            output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
            conversion_outcome=self._successful_outcome(("scripts",)),
        )
        resources = cast(list[dict[str, object]], manifest["resources"])

        self.assertEqual(
            {
                str(resource["name"]): str(resource["godot_path"])
                for resource in resources
            },
            {
                "Scr Spawn": "res://scripts/scr_spawn.gd",
                "scr_spawn": "res://scripts/scr_spawn_2.gd",
            },
        )
        self.assertTrue(
            any(
                diagnostic["code"] == "GM2GD-PATH-COLLISION-RENAMED"
                for diagnostic in cast(list[dict[str, object]], manifest["path_diagnostics"])
            )
        )

    def test_manifest_groups_included_file_packaged_lookup_collisions(
        self,
    ) -> None:
        gm_dir = self.temp_dir / "gm"
        godot_dir = self.temp_dir / "godot"
        gm_dir.mkdir()
        godot_dir.mkdir()
        (gm_dir / "IncludedFiles.yyp").write_text(
            json.dumps(
                {
                    "%Name": "IncludedFiles",
                    "resourceType": "GMProject",
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )
        entries = (
            AssetRegistryEntry(
                id=0,
                name="Config/Read Me.TXT",
                kind="included_files",
                asset_type="included_file",
                type_name="Included File",
                source_path="datafiles/Config/Read Me.TXT",
                godot_path="res://included_files/config/read_me_3.txt",
                legacy_id="",
            ),
            AssetRegistryEntry(
                id=1,
                name="config/read_me.txt",
                kind="included_files",
                asset_type="included_file",
                type_name="Included File",
                source_path="datafiles/config/read_me.txt",
                godot_path="res://included_files/config/read_me.txt",
                legacy_id="",
            ),
            AssetRegistryEntry(
                id=2,
                name="config/read_me_2.txt",
                kind="included_files",
                asset_type="included_file",
                type_name="Included File",
                source_path="datafiles/config/read_me_2.txt",
                godot_path="res://included_files/config/read_me_2.txt",
                legacy_id="",
            ),
        )

        with patch.object(
            conversion_manifest_module,
            "_asset_registry_entries",
            return_value=entries,
        ):
            manifest = build_conversion_manifest(
                str(gm_dir),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=[],
                output_snapshot=capture_conversion_output_snapshot(
                    str(godot_dir)
                ),
                conversion_outcome=self._successful_outcome(),
            )

        resources = cast(list[dict[str, object]], manifest["resources"])
        self.assertEqual(
            {
                str(resource["name"]): str(resource["godot_path"])
                for resource in resources
            },
            {
                "Config/Read Me.TXT": (
                    "res://included_files/config/read_me_3.txt"
                ),
                "config/read_me.txt": (
                    "res://included_files/config/read_me.txt"
                ),
                "config/read_me_2.txt": (
                    "res://included_files/config/read_me_2.txt"
                ),
            },
        )
        collisions = [
            diagnostic
            for diagnostic in cast(
                list[dict[str, object]],
                manifest["path_diagnostics"],
            )
            if diagnostic["code"] == "GM2GD-PATH-COLLISION-RENAMED"
        ]
        self.assertEqual(len(collisions), 1)
        collision = collisions[0]
        self.assertEqual(
            collision["base_godot_path_casefold"],
            "res://included_files/config/read_me.txt",
        )
        collision_resources = cast(
            list[dict[str, object]],
            collision["resources"],
        )
        self.assertEqual(
            {
                str(resource["name"]): (
                    str(resource["base_godot_path"]),
                    str(resource["stable_godot_path"]),
                )
                for resource in collision_resources
            },
            {
                "Config/Read Me.TXT": (
                    "res://included_files/config/read_me.txt",
                    "res://included_files/config/read_me_3.txt",
                ),
                "config/read_me.txt": (
                    "res://included_files/config/read_me.txt",
                    "res://included_files/config/read_me.txt",
                ),
            },
        )

    def test_manifest_groups_included_file_prefix_collisions_independent_of_order(
        self,
    ) -> None:
        gm_dir = self.temp_dir / "gm-prefix"
        godot_dir = self.temp_dir / "godot-prefix"
        gm_dir.mkdir()
        godot_dir.mkdir()
        (gm_dir / "IncludedFiles.yyp").write_text(
            json.dumps(
                {
                    "%Name": "IncludedFiles",
                    "resourceType": "GMProject",
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )
        entries = (
            AssetRegistryEntry(
                id=0,
                name="foo_bar",
                kind="included_files",
                asset_type="included_file",
                type_name="Included File",
                source_path="datafiles/foo_bar",
                godot_path="res://included_files/foo_bar_3",
                legacy_id="",
            ),
            AssetRegistryEntry(
                id=1,
                name="Foo Bar/item.txt",
                kind="included_files",
                asset_type="included_file",
                type_name="Included File",
                source_path="datafiles/Foo Bar/item.txt",
                godot_path="res://included_files/foo_bar/item.txt",
                legacy_id="",
            ),
            AssetRegistryEntry(
                id=2,
                name="foo_bar_2",
                kind="included_files",
                asset_type="included_file",
                type_name="Included File",
                source_path="datafiles/foo_bar_2",
                godot_path="res://included_files/foo_bar_2",
                legacy_id="",
            ),
        )

        def path_diagnostics_for(
            registry_entries: tuple[AssetRegistryEntry, ...],
        ) -> list[dict[str, object]]:
            with patch.object(
                conversion_manifest_module,
                "_asset_registry_entries",
                return_value=registry_entries,
            ):
                manifest = build_conversion_manifest(
                    str(gm_dir),
                    str(godot_dir),
                    target_platform="windows",
                    enabled_converters=[],
                    output_snapshot=capture_conversion_output_snapshot(
                        str(godot_dir)
                    ),
                    conversion_outcome=self._successful_outcome(),
                )
            return cast(
                list[dict[str, object]],
                manifest["path_diagnostics"],
            )

        forward = path_diagnostics_for(entries)
        reverse = path_diagnostics_for(tuple(reversed(entries)))

        self.assertEqual(forward, reverse)
        collisions = [
            diagnostic
            for diagnostic in forward
            if diagnostic["code"] == "GM2GD-PATH-COLLISION-RENAMED"
        ]
        self.assertEqual(len(collisions), 1)
        collision = collisions[0]
        self.assertEqual(
            collision["base_godot_path_casefold"],
            "res://included_files/foo_bar",
        )
        collision_resources = cast(
            list[dict[str, object]],
            collision["resources"],
        )
        self.assertEqual(
            {
                str(resource["name"]): (
                    str(resource["base_godot_path"]),
                    str(resource["stable_godot_path"]),
                )
                for resource in collision_resources
            },
            {
                "foo_bar": (
                    "res://included_files/foo_bar",
                    "res://included_files/foo_bar_3",
                ),
                "Foo Bar/item.txt": (
                    "res://included_files/foo_bar/item.txt",
                    "res://included_files/foo_bar/item.txt",
                ),
            },
        )

    def test_manifest_excludes_unavailable_included_file_outputs(self) -> None:
        gm_dir = self.temp_dir / "gm-publication-filter"
        godot_dir = self.temp_dir / "godot-publication-filter"
        datafiles_dir = gm_dir / "datafiles"
        included_files_dir = godot_dir / "included_files"
        datafiles_dir.mkdir(parents=True)
        included_files_dir.mkdir(parents=True)
        (gm_dir / "IncludedFiles.yyp").write_text(
            json.dumps(
                {
                    "%Name": "IncludedFiles",
                    "resourceType": "GMProject",
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )
        (datafiles_dir / "absent.bin").write_bytes(b"absent output payload")
        (datafiles_dir / "stale.bin").write_bytes(b"current stale payload")
        (datafiles_dir / "matching.bin").write_bytes(b"matching payload")
        (included_files_dir / "stale.bin").write_bytes(b"old stale payload")
        (included_files_dir / "matching.bin").write_bytes(b"matching payload")

        manifest = build_conversion_manifest(
            str(gm_dir),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=[],
            output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
            conversion_outcome=self._successful_outcome(),
        )

        resources = cast(list[dict[str, object]], manifest["resources"])
        included_resources = {
            str(resource["name"]): str(resource["godot_path"])
            for resource in resources
            if resource["kind"] == "included_files"
        }
        self.assertEqual(
            included_resources,
            {
                "matching.bin": "res://included_files/matching.bin",
            },
        )

    def test_manifest_reserves_missing_canonical_before_normalized_alias(
        self,
    ) -> None:
        gm_dir = self.temp_dir / "gm-reserved-included-path"
        godot_dir = self.temp_dir / "godot-reserved-included-path"
        datafiles_dir = gm_dir / "datafiles"
        included_files_dir = godot_dir / "included_files"
        datafiles_dir.mkdir(parents=True)
        included_files_dir.mkdir(parents=True)
        (gm_dir / "IncludedFiles.yyp").write_text(
            json.dumps(
                {
                    "%Name": "IncludedFiles",
                    "resourceType": "GMProject",
                    "resources": [],
                    "IncludedFiles": [
                        {
                            "name": "read_me.txt",
                            "path": "datafiles/read_me.txt",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (datafiles_dir / "Read Me.txt").write_bytes(b"alias payload")
        (included_files_dir / "read_me_2.txt").write_bytes(b"alias payload")

        manifest = build_conversion_manifest(
            str(gm_dir),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=[],
            output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
            conversion_outcome=self._successful_outcome(),
        )

        resources = cast(list[dict[str, object]], manifest["resources"])
        included_resources = {
            str(resource["name"]): str(resource["godot_path"])
            for resource in resources
            if resource["kind"] == "included_files"
        }
        self.assertEqual(
            included_resources,
            {
                "Read Me.txt": "res://included_files/read_me_2.txt",
            },
        )

    def test_manifest_records_source_project_ide_version(self) -> None:
        gm_dir = self.temp_dir / "gm"
        godot_dir = self.temp_dir / "godot"
        gm_dir.mkdir()
        godot_dir.mkdir()
        (gm_dir / "Versioned.yyp").write_text(
            json.dumps(
                {
                    "%Name": "Versioned",
                    "resourceType": "GMProject",
                    "resourceVersion": "1.7",
                    "MetaData": {"IDEVersion": "2026.0.1.123"},
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )

        manifest = build_conversion_manifest(
            str(gm_dir),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=[],
            output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
            conversion_outcome=self._successful_outcome(),
        )

        source_project = cast(dict[str, object], manifest["source_project"])
        self.assertEqual(source_project["name"], "Versioned")
        self.assertEqual(source_project["ide_version"], "2026.0.1.123")

    def test_generated_files_include_emitted_binary_files_but_not_preexisting_files(self) -> None:
        gm_dir = self.temp_dir / "gm"
        godot_dir = self.temp_dir / "godot"
        datafiles_dir = gm_dir / "datafiles"
        datafiles_dir.mkdir(parents=True)
        godot_dir.mkdir()
        (gm_dir / "BinaryOutputs.yyp").write_text(
            json.dumps(
                {
                    "%Name": "BinaryOutputs",
                    "resourceType": "GMProject",
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )
        emitted_files = {
            "art.png": b"\x89PNG\r\n\x1a\nconverted-image",
            "tone.wav": b"RIFF\x10\x00\x00\x00WAVEconverted-audio",
            "ui.ttf": b"\x00\x01\x00\x00converted-font",
        }
        for filename, content in emitted_files.items():
            (datafiles_dir / filename).write_bytes(content)

        (godot_dir / "project.godot").write_text(
            '[application]\nconfig/name="Existing Project"\n',
            encoding="utf-8",
        )
        (godot_dir / "unrelated.png").write_bytes(b"pre-existing image")
        (godot_dir / "custom.gd").write_text("extends Node\n", encoding="utf-8")

        exit_code = cli.main(
            [
                "convert",
                "--gm-project",
                str(gm_dir),
                "--godot-project",
                str(godot_dir),
                "--target-platform",
                "windows",
                "--only",
                "included_files",
                "--max-warnings",
                "0",
            ]
        )

        self.assertEqual(exit_code, 0)
        manifest = json.loads(
            (godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        generated_files = cast(list[dict[str, object]], manifest["generated_files"])
        generated_by_path = {
            str(entry["path"]): entry
            for entry in generated_files
        }
        expected_kinds = {
            "art.png": "image",
            "tone.wav": "audio",
            "ui.ttf": "font",
        }
        for filename, kind in expected_kinds.items():
            relative_path = f"included_files/{filename}"
            self.assertEqual(generated_by_path[relative_path]["kind"], kind)
            expected_hash = "sha256:" + hashlib.sha256(emitted_files[filename]).hexdigest()
            self.assertEqual(generated_by_path[relative_path]["sha256"], expected_hash)

        self.assertNotIn("unrelated.png", generated_by_path)
        self.assertNotIn("custom.gd", generated_by_path)
        self.assertNotIn("project.godot", generated_by_path)

    def test_artifact_pair_is_fsynced_and_published_attempt_first_from_same_directory(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        real_replace = os.replace
        real_fsync = os.fsync

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                wraps=real_replace,
            ) as replace,
            patch(
                "src.conversion.conversion_manifest.os.fsync",
                wraps=real_fsync,
            ) as fsync,
        ):
            manifest_path, attempt_path = self._write_artifacts(godot_dir)

        self.assertIsNotNone(manifest_path)
        self.assertEqual(len(replace.call_args_list), 2)
        destinations = [Path(call.args[1]) for call in replace.call_args_list]
        self.assertEqual(
            destinations,
            [
                godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH,
                godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH,
            ],
        )
        for call in replace.call_args_list:
            staged_path, destination_path = call.args
            self.assertEqual(Path(staged_path).parent, Path(destination_path).parent)
        self.assertGreaterEqual(fsync.call_count, 2 if os.name == "nt" else 4)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])
        self.assertTrue(Path(cast(str, manifest_path)).is_file())
        self.assertTrue(Path(attempt_path).is_file())

    @unittest.skipIf(os.name == "nt", "Directory fsync is unavailable on Windows")
    def test_new_artifact_directory_entry_is_fsynced_through_project_root(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        real_directory_fsync = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_fsync_verified_directory"),
        )

        with patch(
            "src.conversion.conversion_manifest._fsync_verified_directory",
            wraps=real_directory_fsync,
        ) as fsync_directory:
            self._write_artifacts(godot_dir)

        self.assertTrue(
            any(
                Path(call.args[0]) == godot_dir
                and call.kwargs.get("description") == "conversion artifact root"
                for call in fsync_directory.call_args_list
            )
        )

    @unittest.skipIf(os.name == "nt", "Directory fsync is unavailable on Windows")
    def test_retry_fsyncs_project_root_after_directory_creation_sync_failure(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        real_directory_fsync = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_fsync_verified_directory"),
        )
        root_sync_failed = False

        def fail_first_root_sync(
            path: str,
            expected_identity: object,
            *,
            description: str,
        ) -> None:
            nonlocal root_sync_failed
            if description == "conversion artifact root" and not root_sync_failed:
                root_sync_failed = True
                raise OSError("injected artifact root fsync failure")
            real_directory_fsync(
                path,
                cast(tuple[int, int], expected_identity),
                description=description,
            )

        with (
            patch(
                "src.conversion.conversion_manifest._fsync_verified_directory",
                side_effect=fail_first_root_sync,
            ),
            self.assertRaisesRegex(OSError, "injected artifact root fsync failure"),
        ):
            self._write_artifacts(godot_dir)

        self.assertTrue(root_sync_failed)
        self.assertTrue((godot_dir / "gm2godot").is_dir())
        self.assertFalse(
            (godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH).exists()
        )
        self.assertFalse(
            (godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH).exists()
        )

        with patch(
            "src.conversion.conversion_manifest._fsync_verified_directory",
            wraps=real_directory_fsync,
        ) as retry_fsync:
            self._write_artifacts(godot_dir)

        self.assertTrue(
            any(
                Path(call.args[0]) == godot_dir
                and call.kwargs.get("description") == "conversion artifact root"
                for call in retry_fsync.call_args_list
            )
        )

    def test_attempt_only_preserves_canonical_bytes_and_records_exact_digest(
        self,
    ) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, _ = (
            self._existing_artifacts()
        )
        failed_outcome = self._failed_outcome()

        returned_manifest, returned_attempt = self._write_artifacts(
            godot_dir,
            manifest_outcome=None,
            attempt_outcome=failed_outcome,
        )

        self.assertIsNone(returned_manifest)
        self.assertEqual(Path(returned_attempt), attempt_path)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        self.assertEqual(attempt["format_version"], 1)
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertFalse(attempt["attempt"]["cancelled"])
        self.assertEqual(
            attempt["attempt"]["steps"],
            {
                "requested": ["scripts", "objects"],
                "executed": ["scripts", "objects"],
                "completed": ["scripts"],
                "skipped": [],
                "failed": ["objects"],
            },
        )
        self.assertEqual(
            attempt["canonical_manifest"],
            {
                "path": "gm2godot/conversion_manifest.json",
                "status": "preserved",
                "updated": False,
                "current_output": "unverified",
                "sha256": "sha256:"
                + hashlib.sha256(manifest_before).hexdigest(),
            },
        )
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_attempt_only_records_absent_canonical_and_cancellation(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()

        returned_manifest, returned_attempt = self._write_artifacts(
            godot_dir,
            manifest_outcome=None,
            attempt_outcome=self._cancelled_outcome(),
        )

        self.assertIsNone(returned_manifest)
        self.assertFalse(
            (godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH).exists()
        )
        attempt = json.loads(Path(returned_attempt).read_text(encoding="utf-8"))
        self.assertEqual(attempt["attempt"]["state"], "cancelled")
        self.assertTrue(attempt["attempt"]["cancelled"])
        self.assertEqual(
            attempt["canonical_manifest"],
            {
                "path": "gm2godot/conversion_manifest.json",
                "status": "absent",
                "updated": False,
                "current_output": "unavailable",
                "sha256": None,
            },
        )

    def test_manifest_embeds_complete_conversion_record_and_exact_attempt_digest(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        outcome = self._partial_outcome()

        manifest_path_value, attempt_path_value = self._write_artifacts(
            godot_dir,
            manifest_outcome=outcome,
            attempt_outcome=outcome,
        )

        manifest_path = Path(cast(str, manifest_path_value))
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["format_version"], 2)
        self.assertEqual(manifest["conversion"]["state"], "partial")
        self.assertFalse(manifest["conversion"]["cancelled"])
        self.assertEqual(
            manifest["conversion"]["steps"]["completed"],
            ["scripts", "objects"],
        )
        self.assertEqual(manifest["conversion"]["steps"]["skipped"], [])
        attempt = json.loads(Path(attempt_path_value).read_text(encoding="utf-8"))
        self.assertEqual(
            attempt["canonical_manifest"],
            {
                "path": "gm2godot/conversion_manifest.json",
                "status": "updated",
                "updated": True,
                "current_output": "verified",
                "sha256": "sha256:"
                + hashlib.sha256(manifest_bytes).hexdigest(),
            },
        )

    def test_generated_files_exclude_attempt_stages_and_backups_but_keep_manifest_self(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "godot"
        artifact_dir = godot_dir / "gm2godot"
        artifact_dir.mkdir(parents=True)
        snapshot = capture_conversion_output_snapshot(str(godot_dir))
        excluded_names = (
            "conversion_attempt.json",
            ".conversion_attempt.json.stale.tmp",
            ".conversion_attempt.json.recovery.backup",
            ".conversion_manifest.json.stale.tmp",
            ".conversion_manifest.json.recovery.backup",
        )
        for filename in excluded_names:
            (artifact_dir / filename).write_text(filename, encoding="utf-8")
        (artifact_dir / "kept_report.json").write_text("{}\n", encoding="utf-8")

        manifest = build_conversion_manifest(
            str(FIXTURE_ROOT),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=[],
            output_snapshot=snapshot,
            conversion_outcome=self._successful_outcome(),
        )

        generated = {
            entry["path"]: entry
            for entry in cast(list[dict[str, object]], manifest["generated_files"])
        }
        for filename in excluded_names:
            self.assertNotIn(f"gm2godot/{filename}", generated)
        self.assertIn("gm2godot/kept_report.json", generated)
        self.assertEqual(
            generated["gm2godot/conversion_manifest.json"],
            {
                "path": "gm2godot/conversion_manifest.json",
                "kind": "manifest",
                "sha256": "self",
            },
        )

    def test_serialization_failure_preserves_existing_artifact_pair(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )

        with (
            patch(
                "src.conversion.conversion_manifest._serialize_json",
                side_effect=TypeError("injected serialization failure"),
            ),
            self.assertRaisesRegex(TypeError, "injected serialization failure"),
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_serialization_failure_does_not_create_artifact_directory(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()

        with (
            patch(
                "src.conversion.conversion_manifest._serialize_json",
                side_effect=TypeError("injected serialization failure"),
            ),
            self.assertRaisesRegex(TypeError, "injected serialization failure"),
        ):
            self._write_artifacts(godot_dir)

        self.assertFalse((godot_dir / "gm2godot").exists())

    def test_included_output_delete_at_manifest_boundary_rolls_back_pair(
        self,
    ) -> None:
        (
            gm_dir,
            godot_dir,
            output_path,
            manifest_path,
            attempt_path,
            manifest_before,
            attempt_before,
        ) = self._included_publication_fixture("delete-boundary")
        real_revalidate = AssetRegistryConverter.revalidate_published_entries
        validation_calls = 0

        def delete_then_revalidate(
            converter: AssetRegistryConverter,
            entries: tuple[AssetRegistryEntry, ...],
        ) -> None:
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 1:
                output_path.unlink()
            real_revalidate(converter, entries)

        with (
            patch.object(
                AssetRegistryConverter,
                "revalidate_published_entries",
                new=delete_then_revalidate,
            ),
            self.assertRaisesRegex(
                OSError,
                "publication inputs changed",
            ),
        ):
            write_conversion_artifacts(
                str(gm_dir),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=(),
                output_snapshot=capture_conversion_output_snapshot(
                    str(godot_dir)
                ),
                manifest_outcome=self._successful_outcome(),
                attempt_outcome=self._successful_outcome(),
            )

        self.assertEqual(validation_calls, 1)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_included_output_byte_change_after_manifest_publish_rolls_back_pair(
        self,
    ) -> None:
        (
            gm_dir,
            godot_dir,
            output_path,
            manifest_path,
            attempt_path,
            manifest_before,
            attempt_before,
        ) = self._included_publication_fixture("change-after-publish")
        real_revalidate = AssetRegistryConverter.revalidate_published_entries
        validation_calls = 0

        def mutate_then_revalidate(
            converter: AssetRegistryConverter,
            entries: tuple[AssetRegistryEntry, ...],
        ) -> None:
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 2:
                output_path.write_bytes(b"changed after manifest publication")
            real_revalidate(converter, entries)

        with (
            patch.object(
                AssetRegistryConverter,
                "revalidate_published_entries",
                new=mutate_then_revalidate,
            ),
            self.assertRaisesRegex(
                OSError,
                "publication inputs changed",
            ),
        ):
            write_conversion_artifacts(
                str(gm_dir),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=(),
                output_snapshot=capture_conversion_output_snapshot(
                    str(godot_dir)
                ),
                manifest_outcome=self._successful_outcome(),
                attempt_outcome=self._successful_outcome(),
            )

        self.assertEqual(validation_calls, 2)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_outcome_steps_must_match_enabled_conversion_plan(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        contradictory_outcome = self._successful_outcome()

        with self.assertRaisesRegex(ValueError, "must match the enabled conversion plan"):
            build_conversion_manifest(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=("scripts",),
                output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
                conversion_outcome=contradictory_outcome,
            )

        with self.assertRaisesRegex(ValueError, "must match the enabled conversion plan"):
            write_conversion_artifacts(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=("scripts",),
                output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
                manifest_outcome=contradictory_outcome,
                attempt_outcome=contradictory_outcome,
            )

        self.assertFalse((godot_dir / "gm2godot").exists())

    def test_canonical_partial_requires_every_converter_step_to_complete(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        steps = ConversionStepLedger.from_requested(("scripts", "objects"))
        steps = steps.start("scripts").complete("scripts")

        with self.assertRaisesRegex(ValueError, "every requested converter step"):
            ConversionOutcome(
                state="partial",
                steps=steps,
                resources=ConversionCounts(requested=1, skipped=1),
            )

        self.assertFalse((godot_dir / "gm2godot").exists())

    def test_canonical_update_requires_matching_attempt_work(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        canonical_outcome = self._successful_outcome(("scripts",))
        unexecuted_steps = ConversionStepLedger.from_requested(("scripts",))
        cancelled_attempt = ConversionOutcome(
            state="cancelled",
            steps=unexecuted_steps,
        )

        with self.assertRaisesRegex(ValueError, "must describe the same executed"):
            write_conversion_artifacts(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=("scripts",),
                output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
                manifest_outcome=canonical_outcome,
                attempt_outcome=cancelled_attempt,
            )

        self.assertFalse((godot_dir / "gm2godot").exists())

    def test_canonical_update_allows_named_report_or_finalizer_failure(self) -> None:
        canonical_outcome = self._successful_outcome(("scripts",))

        for failure_phase in ("report", "finalizer"):
            with self.subTest(failure_phase=failure_phase):
                godot_dir = self.temp_dir / failure_phase
                godot_dir.mkdir()
                failed_attempt = ConversionOutcome(
                    state="failed",
                    steps=canonical_outcome.steps,
                    resources=canonical_outcome.resources,
                    failed_step="external_reports",
                    failure_phase=failure_phase,
                )

                manifest_path, attempt_path = self._write_artifacts(
                    godot_dir,
                    manifest_outcome=canonical_outcome,
                    attempt_outcome=failed_attempt,
                )

                self.assertIsNotNone(manifest_path)
                attempt = json.loads(Path(attempt_path).read_text(encoding="utf-8"))
                self.assertEqual(attempt["attempt"]["state"], "failed")
                self.assertEqual(
                    attempt["canonical_manifest"]["current_output"],
                    "verified",
                )

    def test_canonical_update_rejects_untrustworthy_failed_attempt_context(
        self,
    ) -> None:
        canonical_outcome = self._successful_outcome(("scripts",))

        for index, failure_phase in enumerate(
            ("runtime", "preflight", "missing-outcome", None)
        ):
            with self.subTest(failure_phase=failure_phase):
                godot_dir = self.temp_dir / f"rejected-{index}"
                godot_dir.mkdir()
                failed_attempt = ConversionOutcome(
                    state="failed",
                    steps=canonical_outcome.steps,
                    resources=canonical_outcome.resources,
                    failed_step="scripts",
                    failure_phase=failure_phase,
                )

                with self.assertRaisesRegex(ValueError, "report or finalizer"):
                    self._write_artifacts(
                        godot_dir,
                        manifest_outcome=canonical_outcome,
                        attempt_outcome=failed_attempt,
                    )

                self.assertFalse((godot_dir / "gm2godot").exists())

        unnamed_dir = self.temp_dir / "unnamed-finalizer"
        unnamed_dir.mkdir()
        unnamed_attempt = ConversionOutcome(
            state="failed",
            steps=canonical_outcome.steps,
            resources=canonical_outcome.resources,
            failure_phase="finalizer",
        )
        with self.assertRaisesRegex(ValueError, "named failed step"):
            self._write_artifacts(
                unnamed_dir,
                manifest_outcome=canonical_outcome,
                attempt_outcome=unnamed_attempt,
            )
        self.assertFalse((unnamed_dir / "gm2godot").exists())

    def test_canonical_update_allows_cancelled_identical_completed_work(self) -> None:
        godot_dir = self.temp_dir / "cancelled-completed"
        godot_dir.mkdir()
        canonical_outcome = self._successful_outcome(("scripts",))
        cancelled_attempt = ConversionOutcome(
            state="cancelled",
            steps=canonical_outcome.steps,
            resources=canonical_outcome.resources,
        )

        manifest_path, attempt_path = self._write_artifacts(
            godot_dir,
            manifest_outcome=canonical_outcome,
            attempt_outcome=cancelled_attempt,
        )

        self.assertIsNotNone(manifest_path)
        attempt = json.loads(Path(attempt_path).read_text(encoding="utf-8"))
        self.assertEqual(attempt["attempt"]["state"], "cancelled")
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "verified",
        )

    def test_unknown_enabled_converter_is_rejected_before_output_mutation(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()

        with self.assertRaisesRegex(ValueError, "Unknown enabled converter key"):
            write_conversion_artifacts(
                str(FIXTURE_ROOT),
                str(godot_dir),
                target_platform="windows",
                enabled_converters=("not_a_converter",),
                output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
                manifest_outcome=self._successful_outcome(),
                attempt_outcome=self._successful_outcome(),
            )

        self.assertFalse((godot_dir / "gm2godot").exists())

    def test_staged_write_failure_preserves_existing_pair_and_cleans_stages(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_fsync = os.fsync
        call_count = 0

        def fail_second_fsync(file_descriptor: int) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("injected staged write failure")
            real_fsync(file_descriptor)

        with (
            patch(
                "src.conversion.conversion_manifest.os.fsync",
                side_effect=fail_second_fsync,
            ),
            self.assertRaisesRegex(OSError, "injected staged write failure"),
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_incomplete_stage_cleanup_failure_is_reported_and_retained(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        real_fsync = os.fsync
        real_unlink = os.unlink

        def fail_file_fsync(file_descriptor: int) -> None:
            if stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                raise OSError("injected stage fsync failure")
            real_fsync(file_descriptor)

        def fail_stage_unlink(path: str | bytes) -> None:
            if os.fsdecode(path).endswith(".tmp"):
                raise OSError("injected stage cleanup failure")
            real_unlink(path)

        with (
            patch(
                "src.conversion.conversion_manifest.os.fsync",
                side_effect=fail_file_fsync,
            ),
            patch(
                "src.conversion.conversion_manifest.os.unlink",
                side_effect=fail_stage_unlink,
            ),
            self.assertRaisesRegex(OSError, "injected stage fsync failure") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertTrue(
            any(
                "Failed to remove incomplete conversion artifact stage" in note
                and "injected stage cleanup failure" in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )
        self.assertEqual(len(self._temporary_artifact_files(godot_dir)), 1)

    def test_later_successful_publish_cleans_owned_backup_leftovers(self) -> None:
        godot_dir, _, _, _, _ = self._existing_artifacts()
        real_unlink = os.unlink

        def fail_backup_cleanup(path: str | bytes) -> None:
            if os.fsdecode(path).endswith(".backup"):
                raise PermissionError("injected backup cleanup refusal")
            real_unlink(path)

        with patch(
            "src.conversion.conversion_manifest.os.unlink",
            side_effect=fail_backup_cleanup,
        ):
            self._write_artifacts(godot_dir)

        leftovers = self._temporary_artifact_files(godot_dir)
        self.assertEqual(len(leftovers), 2)
        self.assertTrue(all(path.name.endswith(".backup") for path in leftovers))

        self._write_artifacts(godot_dir)

        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_attempt_only_publish_preserves_canonical_recovery_leftover(self) -> None:
        godot_dir, manifest_path, _, _, _ = self._existing_artifacts()
        recovery_path = manifest_path.parent / (
            f".{manifest_path.name}.abcdefgh.recovery.backup"
        )
        recovery_content = b'{"trusted": "recovery"}\n'
        recovery_path.write_bytes(recovery_content)

        self._write_artifacts(
            godot_dir,
            manifest_outcome=None,
            attempt_outcome=self._failed_outcome(),
        )

        self.assertEqual(recovery_path.read_bytes(), recovery_content)

        self._write_artifacts(godot_dir)

        self.assertFalse(recovery_path.exists())

    def test_cleanup_control_flow_signals_propagate_after_valid_commit(self) -> None:
        for signal_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(signal_type=signal_type.__name__):
                godot_dir, manifest_path, attempt_path, _, _ = (
                    self._existing_artifacts(
                        self.temp_dir / signal_type.__name__.lower()
                    )
                )
                real_unlink = os.unlink
                interrupted = False

                def interrupt_backup_cleanup(path: str | bytes) -> None:
                    nonlocal interrupted
                    if not interrupted and os.fsdecode(path).endswith(".backup"):
                        interrupted = True
                        raise signal_type("injected cleanup control-flow signal")
                    real_unlink(path)

                with (
                    patch(
                        "src.conversion.conversion_manifest.os.unlink",
                        side_effect=interrupt_backup_cleanup,
                    ),
                    self.assertRaises(signal_type),
                ):
                    self._write_artifacts(godot_dir)

                self.assertTrue(interrupted)
                manifest_bytes = manifest_path.read_bytes()
                attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    attempt["canonical_manifest"]["sha256"],
                    "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
                )
                self.assertGreaterEqual(
                    len(self._temporary_artifact_files(godot_dir)),
                    1,
                )

                self._write_artifacts(godot_dir)

                self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_incomplete_stage_cleanup_does_not_swallow_keyboard_interrupt(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "stage-cleanup-interrupt"
        godot_dir.mkdir()
        real_fsync = os.fsync
        real_unlink = os.unlink

        def fail_file_fsync(file_descriptor: int) -> None:
            if stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                raise OSError("injected stage failure")
            real_fsync(file_descriptor)

        def interrupt_stage_cleanup(path: str | bytes) -> None:
            if os.fsdecode(path).endswith(".tmp"):
                raise KeyboardInterrupt("injected stage cleanup interrupt")
            real_unlink(path)

        with (
            patch(
                "src.conversion.conversion_manifest.os.fsync",
                side_effect=fail_file_fsync,
            ),
            patch(
                "src.conversion.conversion_manifest.os.unlink",
                side_effect=interrupt_stage_cleanup,
            ),
            self.assertRaisesRegex(
                KeyboardInterrupt,
                "injected stage cleanup interrupt",
            ),
        ):
            self._write_artifacts(godot_dir)

    @unittest.skipIf(os.name == "nt", "Symlink creation is not portable on Windows")
    def test_stale_cleanup_refuses_redirected_lookalike(self) -> None:
        godot_dir, _, attempt_path, _, _ = self._existing_artifacts()
        external_path = self.temp_dir / "external-stale-lookalike.json"
        external_content = b"external sentinel\n"
        external_path.write_bytes(external_content)
        lookalike = attempt_path.parent / (
            f".{attempt_path.name}.abcdefgh.backup"
        )
        lookalike.symlink_to(external_path)

        self._write_artifacts(godot_dir)

        self.assertTrue(lookalike.is_symlink())
        self.assertEqual(external_path.read_bytes(), external_content)

    def test_second_replace_failure_rolls_back_attempt_and_preserves_pair(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_replace = os.replace

        def fail_canonical_publish(source: str, destination: str) -> None:
            if (
                Path(destination) == manifest_path
                and source.endswith(".tmp")
            ):
                raise OSError("injected canonical replace failure")
            real_replace(source, destination)

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=fail_canonical_publish,
            ),
            self.assertRaisesRegex(OSError, "injected canonical replace failure"),
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_final_publication_revalidates_the_entire_artifact_pair(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_replace = os.replace
        corrupted_attempt = b"corrupted during canonical publication\n"

        def publish_then_corrupt_attempt(source: str, destination: str) -> None:
            real_replace(source, destination)
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                attempt_path.write_bytes(corrupted_attempt)

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=publish_then_corrupt_attempt,
            ),
            self.assertRaisesRegex(OSError, "content changed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), corrupted_attempt)
        recovery_files = list(
            attempt_path.parent.glob(f".{attempt_path.name}.*.backup")
        )
        self.assertEqual(len(recovery_files), 1)
        self.assertEqual(recovery_files[0].read_bytes(), attempt_before)
        self.assertTrue(
            any(
                "rollback also failed" in note
                and os.fspath(recovery_files[0]) in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    def test_publication_revalidates_pair_after_cleanup_fsync(self) -> None:
        godot_dir, manifest_path, attempt_path, _, _ = self._existing_artifacts()
        real_directory_fsync = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_fsync_artifact_directory"),
        )
        directory_fsync_calls = 0
        corrupted_attempt = b"corrupted during cleanup fsync\n"

        def corrupt_during_cleanup_fsync(
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal directory_fsync_calls
            directory_fsync_calls += 1
            real_directory_fsync(*args, **kwargs)
            if directory_fsync_calls == 3:
                attempt_path.write_bytes(corrupted_attempt)

        with (
            patch(
                "src.conversion.conversion_manifest._fsync_artifact_directory",
                side_effect=corrupt_during_cleanup_fsync,
            ),
            self.assertRaisesRegex(OSError, "content changed"),
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(directory_fsync_calls, 3)
        self.assertTrue(manifest_path.is_file())
        self.assertEqual(attempt_path.read_bytes(), corrupted_attempt)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    @unittest.skipIf(os.name == "nt", "Directory fsync is unavailable on Windows")
    def test_directory_fsync_failure_after_attempt_publish_rolls_back_pair(
        self,
    ) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_fsync = os.fsync
        directory_fsync_failed = False
        artifact_directory_stat = os.stat(manifest_path.parent)
        artifact_directory_identity = (
            artifact_directory_stat.st_dev,
            artifact_directory_stat.st_ino,
        )

        def fail_first_directory_fsync(file_descriptor: int) -> None:
            nonlocal directory_fsync_failed
            descriptor_stat = os.fstat(file_descriptor)
            if (
                stat.S_ISDIR(descriptor_stat.st_mode)
                and (descriptor_stat.st_dev, descriptor_stat.st_ino)
                == artifact_directory_identity
                and not directory_fsync_failed
            ):
                directory_fsync_failed = True
                raise OSError("injected directory fsync failure")
            real_fsync(file_descriptor)

        with (
            patch(
                "src.conversion.conversion_manifest.os.fsync",
                side_effect=fail_first_directory_fsync,
            ),
            self.assertRaisesRegex(OSError, "injected directory fsync failure"),
        ):
            self._write_artifacts(godot_dir)

        self.assertTrue(directory_fsync_failed)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    @unittest.skipIf(os.name == "nt", "Directory fsync is unavailable on Windows")
    def test_rollback_fsync_failure_retains_verified_recovery_copy(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_replace = os.replace
        real_directory_fsync = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_fsync_artifact_directory"),
        )
        directory_fsync_calls = 0

        def fail_canonical_publish(source: str, destination: str) -> None:
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                raise OSError("canonical publish failed")
            real_replace(source, destination)

        def fail_rollback_fsync(*args: object, **kwargs: object) -> None:
            nonlocal directory_fsync_calls
            directory_fsync_calls += 1
            if directory_fsync_calls == 2:
                raise OSError("rollback directory fsync failed")
            real_directory_fsync(*args, **kwargs)

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=fail_canonical_publish,
            ),
            patch(
                "src.conversion.conversion_manifest._fsync_artifact_directory",
                side_effect=fail_rollback_fsync,
            ),
            self.assertRaisesRegex(OSError, "canonical publish failed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        recovery_files = list(
            attempt_path.parent.glob(f".{attempt_path.name}.*.recovery.backup")
        )
        self.assertEqual(len(recovery_files), 1)
        self.assertEqual(recovery_files[0].read_bytes(), attempt_before)
        self.assertTrue(
            any(
                "rollback directory fsync failed" in note
                and os.fspath(recovery_files[0]) in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    def test_rollback_revalidates_restored_bytes_after_directory_fsync(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_replace = os.replace
        real_directory_fsync = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_fsync_artifact_directory"),
        )
        directory_fsync_calls = 0
        corrupted_attempt = b"corrupted during rollback fsync\n"

        def fail_canonical_publish(source: str, destination: str) -> None:
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                raise OSError("canonical publish failed")
            real_replace(source, destination)

        def tamper_during_rollback_fsync(*args: object, **kwargs: object) -> None:
            nonlocal directory_fsync_calls
            directory_fsync_calls += 1
            real_directory_fsync(*args, **kwargs)
            if directory_fsync_calls == 2:
                attempt_path.write_bytes(corrupted_attempt)

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=fail_canonical_publish,
            ),
            patch(
                "src.conversion.conversion_manifest._fsync_artifact_directory",
                side_effect=tamper_during_rollback_fsync,
            ),
            self.assertRaisesRegex(OSError, "canonical publish failed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), corrupted_attempt)
        recovery_files = list(
            attempt_path.parent.glob(f".{attempt_path.name}.*.recovery.backup")
        )
        self.assertEqual(len(recovery_files), 1)
        self.assertEqual(recovery_files[0].read_bytes(), attempt_before)
        self.assertTrue(
            any(
                "rollback also failed" in note
                and "content changed" in note
                and os.fspath(recovery_files[0]) in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    def test_rollback_revalidates_absence_after_directory_fsync(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        attempt_path = godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH
        manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        real_replace = os.replace
        real_directory_fsync = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_fsync_artifact_directory"),
        )
        directory_fsync_calls = 0
        recreated_attempt = b"recreated during rollback fsync\n"

        def fail_canonical_publish(source: str, destination: str) -> None:
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                raise OSError("canonical publish failed")
            real_replace(source, destination)

        def recreate_during_rollback_fsync(*args: object, **kwargs: object) -> None:
            nonlocal directory_fsync_calls
            directory_fsync_calls += 1
            real_directory_fsync(*args, **kwargs)
            if directory_fsync_calls == 2:
                attempt_path.write_bytes(recreated_attempt)

        with (
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=fail_canonical_publish,
            ),
            patch(
                "src.conversion.conversion_manifest._fsync_artifact_directory",
                side_effect=recreate_during_rollback_fsync,
            ),
            self.assertRaisesRegex(OSError, "canonical publish failed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertFalse(manifest_path.exists())
        self.assertEqual(attempt_path.read_bytes(), recreated_attempt)
        self.assertTrue(
            any(
                "rollback also failed" in note
                and "reappeared during rollback" in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    def test_multi_artifact_rollback_revalidates_every_restored_target(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_directory_fsync = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_fsync_artifact_directory"),
        )
        directory_fsync_calls = 0
        corrupted_manifest = b"corrupted during later rollback\n"

        def fail_publish_then_corrupt_restored_manifest(
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal directory_fsync_calls
            directory_fsync_calls += 1
            real_directory_fsync(*args, **kwargs)
            if directory_fsync_calls == 2:
                raise OSError("second publish directory fsync failed")
            if directory_fsync_calls == 4:
                manifest_path.write_bytes(corrupted_manifest)

        with (
            patch(
                "src.conversion.conversion_manifest._fsync_artifact_directory",
                side_effect=fail_publish_then_corrupt_restored_manifest,
            ),
            self.assertRaisesRegex(
                OSError,
                "second publish directory fsync failed",
            ) as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(manifest_path.read_bytes(), corrupted_manifest)
        recovery_files = list(
            manifest_path.parent.glob(f".{manifest_path.name}.*.recovery.backup")
        )
        self.assertEqual(len(recovery_files), 1)
        self.assertEqual(recovery_files[0].read_bytes(), manifest_before)
        self.assertTrue(
            any(
                "rollback also failed" in note
                and "content changed" in note
                and os.fspath(recovery_files[0]) in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    def test_replace_that_mutates_then_raises_is_detected_and_rolled_back(self) -> None:
        for failing_artifact in ("attempt", "manifest"):
            with self.subTest(failing_artifact=failing_artifact):
                test_root = self.temp_dir / failing_artifact
                (
                    godot_dir,
                    manifest_path,
                    attempt_path,
                    manifest_before,
                    attempt_before,
                ) = self._existing_artifacts(test_root)
                failing_path = (
                    attempt_path if failing_artifact == "attempt" else manifest_path
                )
                real_replace = os.replace

                def mutate_then_fail(source: str, destination: str) -> None:
                    real_replace(source, destination)
                    if Path(destination) == failing_path and source.endswith(".tmp"):
                        raise OSError(f"{failing_artifact} replace mutated then failed")

                with (
                    patch(
                        "src.conversion.conversion_manifest.os.replace",
                        side_effect=mutate_then_fail,
                    ),
                    self.assertRaisesRegex(
                        OSError,
                        f"{failing_artifact} replace mutated then failed",
                    ),
                ):
                    self._write_artifacts(godot_dir)

                self.assertEqual(manifest_path.read_bytes(), manifest_before)
                self.assertEqual(attempt_path.read_bytes(), attempt_before)
                self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_rollback_replace_that_mutates_then_raises_counts_as_restored(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_replace = os.replace

        def fail_publish_and_mutating_rollback(
            source: str,
            destination: str,
        ) -> None:
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                raise OSError("canonical publish failed")
            if Path(destination) == attempt_path and source.endswith(".backup"):
                real_replace(source, destination)
                raise OSError("rollback replace mutated then failed")
            real_replace(source, destination)

        with patch(
            "src.conversion.conversion_manifest.os.replace",
            side_effect=fail_publish_and_mutating_rollback,
        ):
            with self.assertRaisesRegex(OSError, "canonical publish failed") as context:
                self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertFalse(
            any(
                "rollback also failed" in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_rollback_failure_retains_recovery_backup_and_adds_exception_note(
        self,
    ) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_replace = os.replace

        def fail_publish_and_rollback(source: str, destination: str) -> None:
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                raise OSError("canonical publish failed")
            if Path(destination) == attempt_path and source.endswith(".backup"):
                raise OSError("attempt rollback failed")
            real_replace(source, destination)

        with patch(
            "src.conversion.conversion_manifest.os.replace",
            side_effect=fail_publish_and_rollback,
        ):
            with self.assertRaisesRegex(OSError, "canonical publish failed") as context:
                self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertNotEqual(attempt_path.read_bytes(), attempt_before)
        notes = getattr(context.exception, "__notes__", [])
        self.assertTrue(
            any("rollback also failed" in note for note in notes),
            notes,
        )
        recovery_files = list(
            attempt_path.parent.glob(f".{attempt_path.name}.*.backup")
        )
        self.assertEqual(len(recovery_files), 1)
        self.assertEqual(recovery_files[0].read_bytes(), attempt_before)
        self.assertTrue(
            any(os.fspath(recovery_files[0]) in note for note in notes),
            notes,
        )
        self.assertEqual(
            [
                path
                for path in self._temporary_artifact_files(godot_dir)
                if path != recovery_files[0]
            ],
            [],
        )

    def test_windows_file_fingerprint_match_ignores_only_ctime(self) -> None:
        fingerprints_match = cast(
            Callable[
                [tuple[int, int, int, int, int], tuple[int, int, int, int, int]],
                bool,
            ],
            getattr(conversion_manifest_module, "_file_fingerprints_match"),
        )
        baseline = (11, 22, 33, 44, 55)
        ctime_only_drift = (11, 22, 33, 44, 99)
        real_drift = {
            "device": (12, 22, 33, 44, 55),
            "inode": (11, 23, 33, 44, 55),
            "size": (11, 22, 34, 44, 55),
            "mtime": (11, 22, 33, 45, 55),
        }

        with patch(
            "src.conversion.conversion_manifest._uses_windows_file_fingerprint_semantics",
            return_value=True,
        ):
            self.assertTrue(fingerprints_match(ctime_only_drift, baseline))
            for field, fingerprint in real_drift.items():
                with self.subTest(field=field):
                    self.assertFalse(fingerprints_match(fingerprint, baseline))

        with patch(
            "src.conversion.conversion_manifest._uses_windows_file_fingerprint_semantics",
            return_value=False,
        ):
            self.assertFalse(fingerprints_match(ctime_only_drift, baseline))

    def test_windows_target_state_keeps_exact_path_ctime_guard(self) -> None:
        artifact_path = self.temp_dir / "artifact.json"
        artifact_path.write_bytes(b"stable artifact\n")
        target_state = cast(
            Callable[[str], object],
            getattr(conversion_manifest_module, "_artifact_target_state"),
        )(str(artifact_path))
        verify_target_state = cast(
            Callable[[str, object], None],
            getattr(conversion_manifest_module, "_verify_artifact_target_state"),
        )
        real_fingerprint = cast(
            Callable[[os.stat_result], tuple[int, int, int, int, int]],
            getattr(conversion_manifest_module, "_file_fingerprint"),
        )

        def path_ctime_drift(
            path_stat: os.stat_result,
        ) -> tuple[int, int, int, int, int]:
            fingerprint = real_fingerprint(path_stat)
            return (*fingerprint[:4], fingerprint[4] + 1)

        with (
            patch(
                "src.conversion.conversion_manifest._uses_windows_file_fingerprint_semantics",
                return_value=True,
            ),
            patch(
                "src.conversion.conversion_manifest._file_fingerprint",
                side_effect=path_ctime_drift,
            ),
            self.assertRaisesRegex(OSError, "changed during publication"),
        ):
            verify_target_state(str(artifact_path), target_state)

    def test_windows_temporary_verification_accepts_ctime_only_divergence(
        self,
    ) -> None:
        stage_artifact = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_artifact_bytes"),
        )
        verify_artifact = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_verify_temporary_artifact"),
        )
        file_fingerprint = cast(
            Callable[[os.stat_result], tuple[int, int, int, int, int]],
            getattr(conversion_manifest_module, "_file_fingerprint"),
        )
        artifact = stage_artifact(
            str(self.temp_dir / "artifact.json"),
            b"stable artifact\n",
            mode=None,
            suffix=".tmp",
        )
        fingerprint_call = 0

        def ctime_divergent_fingerprint(
            path_stat: os.stat_result,
        ) -> tuple[int, int, int, int, int]:
            nonlocal fingerprint_call
            fingerprint_call += 1
            fingerprint = file_fingerprint(path_stat)
            return (*fingerprint[:4], fingerprint[4] + fingerprint_call)

        try:
            with (
                patch(
                    "src.conversion.conversion_manifest._uses_windows_file_fingerprint_semantics",
                    return_value=True,
                ),
                patch(
                    "src.conversion.conversion_manifest._file_fingerprint",
                    side_effect=ctime_divergent_fingerprint,
                ),
            ):
                verify_artifact(artifact)

            fingerprint_call = 0
            with (
                patch(
                    "src.conversion.conversion_manifest._uses_windows_file_fingerprint_semantics",
                    return_value=False,
                ),
                patch(
                    "src.conversion.conversion_manifest._file_fingerprint",
                    side_effect=ctime_divergent_fingerprint,
                ),
                self.assertRaisesRegex(OSError, "content changed"),
            ):
                verify_artifact(artifact)
        finally:
            Path(artifact.path).unlink(missing_ok=True)

    def test_windows_temporary_verification_rejects_content_and_mode_drift(
        self,
    ) -> None:
        stage_artifact = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_artifact_bytes"),
        )
        verify_artifact = cast(
            Callable[..., None],
            getattr(conversion_manifest_module, "_verify_temporary_artifact"),
        )
        original_content = b"original\n"
        artifact = stage_artifact(
            str(self.temp_dir / "artifact.json"),
            original_content,
            mode=None,
            suffix=".tmp",
        )
        artifact_path = Path(artifact.path)

        try:
            artifact_path.write_bytes(b"tampered\n")
            with (
                patch(
                    "src.conversion.conversion_manifest._uses_windows_file_fingerprint_semantics",
                    return_value=True,
                ),
                self.assertRaisesRegex(OSError, "content changed"),
            ):
                verify_artifact(artifact)

            artifact_path.write_bytes(original_content)
            tampered_mode = artifact.staged_mode ^ stat.S_IWRITE
            os.chmod(artifact_path, tampered_mode)
            with (
                patch(
                    "src.conversion.conversion_manifest._uses_windows_file_fingerprint_semantics",
                    return_value=True,
                ),
                self.assertRaisesRegex(OSError, "artifact changed"),
            ):
                verify_artifact(artifact)
        finally:
            os.chmod(artifact_path, artifact.staged_mode | stat.S_IWRITE)
            artifact_path.unlink(missing_ok=True)

    def test_windows_read_only_artifact_pair_is_replaced_without_read_only_temps(
        self,
    ) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        for artifact_path in (manifest_path, attempt_path):
            os.chmod(artifact_path, 0o444)
        real_replace = os.replace
        real_unlink = os.unlink
        replaced_targets: list[Path] = []
        removed_temporary_paths: list[Path] = []

        def windows_replace(source: str, destination: str) -> None:
            destination_path = Path(destination)
            if destination_path.exists() and not (
                stat.S_IMODE(os.lstat(destination_path).st_mode)
                & stat.S_IWRITE
            ):
                raise PermissionError("Windows cannot replace a read-only target")
            real_replace(source, destination)
            replaced_targets.append(destination_path)

        def windows_unlink(path: str | bytes) -> None:
            decoded_path = Path(os.fsdecode(path))
            if decoded_path.exists() and not (
                stat.S_IMODE(os.lstat(decoded_path).st_mode)
                & stat.S_IWRITE
            ):
                raise PermissionError("Windows cannot unlink a read-only file")
            if decoded_path.name.startswith(".conversion_"):
                removed_temporary_paths.append(decoded_path)
            real_unlink(path)

        with (
            patch(
                "src.conversion.conversion_manifest._uses_windows_file_attribute_modes",
                return_value=True,
            ),
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=windows_replace,
            ),
            patch(
                "src.conversion.conversion_manifest.os.unlink",
                side_effect=windows_unlink,
            ),
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(
            replaced_targets,
            [attempt_path, manifest_path],
        )
        self.assertTrue(removed_temporary_paths)
        self.assertNotEqual(manifest_path.read_bytes(), manifest_before)
        self.assertNotEqual(attempt_path.read_bytes(), attempt_before)
        for artifact_path in (manifest_path, attempt_path):
            self.assertEqual(
                stat.S_IMODE(os.lstat(artifact_path).st_mode),
                0o444,
            )
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_windows_read_only_pair_is_restored_after_second_replace_failure(
        self,
    ) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        for artifact_path in (manifest_path, attempt_path):
            os.chmod(artifact_path, 0o444)
        real_replace = os.replace
        real_unlink = os.unlink
        canonical_failure_injected = False

        def windows_replace(source: str, destination: str) -> None:
            nonlocal canonical_failure_injected
            destination_path = Path(destination)
            if destination_path.exists() and not (
                stat.S_IMODE(os.lstat(destination_path).st_mode)
                & stat.S_IWRITE
            ):
                raise PermissionError("Windows cannot replace a read-only target")
            if (
                destination_path == manifest_path
                and source.endswith(".tmp")
            ):
                canonical_failure_injected = True
                raise OSError("injected read-only canonical publish failure")
            real_replace(source, destination)

        def windows_unlink(path: str | bytes) -> None:
            decoded_path = Path(os.fsdecode(path))
            if decoded_path.exists() and not (
                stat.S_IMODE(os.lstat(decoded_path).st_mode)
                & stat.S_IWRITE
            ):
                raise PermissionError("Windows cannot unlink a read-only file")
            real_unlink(path)

        with (
            patch(
                "src.conversion.conversion_manifest._uses_windows_file_attribute_modes",
                return_value=True,
            ),
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=windows_replace,
            ),
            patch(
                "src.conversion.conversion_manifest.os.unlink",
                side_effect=windows_unlink,
            ),
            self.assertRaisesRegex(
                OSError,
                "injected read-only canonical publish failure",
            ),
        ):
            self._write_artifacts(godot_dir)

        self.assertTrue(canonical_failure_injected)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        for artifact_path in (manifest_path, attempt_path):
            self.assertEqual(
                stat.S_IMODE(os.lstat(artifact_path).st_mode),
                0o444,
            )
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable")
    def test_existing_artifact_modes_are_preserved(self) -> None:
        godot_dir, manifest_path, attempt_path, _, _ = self._existing_artifacts()
        os.chmod(manifest_path, 0o640)
        os.chmod(attempt_path, 0o604)

        self._write_artifacts(godot_dir)

        self.assertEqual(os.stat(manifest_path).st_mode & 0o777, 0o640)
        self.assertEqual(os.stat(attempt_path).st_mode & 0o777, 0o604)

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable")
    def test_existing_set_id_artifact_modes_are_preserved(self) -> None:
        godot_dir, manifest_path, attempt_path, _, _ = self._existing_artifacts()
        expected_modes = {
            manifest_path: stat.S_ISUID | 0o640,
            attempt_path: stat.S_ISGID | 0o640,
        }
        for artifact_path, expected_mode in expected_modes.items():
            os.chmod(artifact_path, expected_mode)
            if stat.S_IMODE(os.stat(artifact_path).st_mode) != expected_mode:
                self.skipTest("Filesystem does not retain set-ID file modes")

        self._write_artifacts(godot_dir)

        for artifact_path, expected_mode in expected_modes.items():
            with self.subTest(artifact=artifact_path.name):
                self.assertEqual(
                    stat.S_IMODE(os.stat(artifact_path).st_mode),
                    expected_mode,
                )

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable")
    def test_staged_mode_tampering_is_detected_before_publication(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        os.chmod(manifest_path, 0o640)
        real_stage = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_artifact_bytes"),
        )

        def stage_then_chmod(
            path: str,
            content: bytes,
            *,
            mode: int | None,
            suffix: str,
        ) -> Any:
            staged = real_stage(path, content, mode=mode, suffix=suffix)
            if Path(path) == manifest_path and suffix == ".tmp":
                os.chmod(staged.path, 0o666)
            return staged

        with (
            patch(
                "src.conversion.conversion_manifest._stage_artifact_bytes",
                side_effect=stage_then_chmod,
            ),
            self.assertRaisesRegex(OSError, "Staged conversion artifact changed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertTrue(
            any(
                "cleanup failed" in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable")
    def test_stage_capture_window_mode_tampering_is_rejected(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_lstat = os.lstat
        tampered = False

        def chmod_before_stage_stat(path: str | bytes) -> os.stat_result:
            nonlocal tampered
            decoded_path = os.fsdecode(path)
            if (
                not tampered
                and decoded_path.endswith(".tmp")
                and f".{attempt_path.name}." in os.path.basename(decoded_path)
            ):
                os.chmod(decoded_path, 0o666)
                tampered = True
            return real_lstat(path)

        with (
            patch(
                "src.conversion.conversion_manifest.os.lstat",
                side_effect=chmod_before_stage_stat,
            ),
            self.assertRaisesRegex(OSError, "mode changed"),
        ):
            self._write_artifacts(godot_dir)

        self.assertTrue(tampered)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable")
    def test_backup_mode_tampering_is_never_restored(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_stage_existing = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_existing_artifact"),
        )
        real_replace = os.replace

        def backup_then_chmod(path: str, expected: object) -> Any:
            backup = real_stage_existing(path, expected)
            if Path(path) == attempt_path and backup is not None:
                os.chmod(backup.path, 0o666)
            return backup

        def fail_canonical_publish(source: str, destination: str) -> None:
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                raise OSError("canonical publish failed")
            real_replace(source, destination)

        with (
            patch(
                "src.conversion.conversion_manifest._stage_existing_artifact",
                side_effect=backup_then_chmod,
            ),
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=fail_canonical_publish,
            ),
            self.assertRaisesRegex(OSError, "canonical publish failed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertNotEqual(attempt_path.read_bytes(), attempt_before)
        self.assertTrue(
            any(
                "rollback also failed" in note and "artifact changed" in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable")
    def test_backup_capture_window_mode_tampering_is_rejected(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_lstat = os.lstat
        tampered = False

        def chmod_before_backup_stat(path: str | bytes) -> os.stat_result:
            nonlocal tampered
            decoded_path = os.fsdecode(path)
            if (
                not tampered
                and decoded_path.endswith(".backup")
                and f".{attempt_path.name}." in os.path.basename(decoded_path)
            ):
                os.chmod(decoded_path, 0o666)
                tampered = True
            return real_lstat(path)

        with (
            patch(
                "src.conversion.conversion_manifest.os.lstat",
                side_effect=chmod_before_backup_stat,
            ),
            self.assertRaisesRegex(OSError, "mode changed"),
        ):
            self._write_artifacts(godot_dir)

        self.assertTrue(tampered)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable")
    def test_new_artifact_modes_remain_restrictive(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()

        manifest_path_value, attempt_path_value = self._write_artifacts(godot_dir)

        for artifact_path in (
            Path(cast(str, manifest_path_value)),
            Path(attempt_path_value),
        ):
            with self.subTest(artifact=artifact_path.name):
                self.assertEqual(os.stat(artifact_path).st_mode & 0o077, 0)

    @unittest.skipIf(os.name == "nt", "Symlink creation is not portable on Windows")
    def test_refuses_redirected_root_and_artifact_targets(self) -> None:
        real_root = self.temp_dir / "real-root"
        real_root.mkdir()
        redirected_root = self.temp_dir / "redirected-root"
        redirected_root.symlink_to(real_root, target_is_directory=True)
        with self.assertRaisesRegex(OSError, "redirected or non-directory"):
            self._write_artifacts(redirected_root)

        godot_dir = self.temp_dir / "godot"
        artifact_dir = godot_dir / "gm2godot"
        artifact_dir.mkdir(parents=True)
        external = self.temp_dir / "external.json"
        external.write_text("external\n", encoding="utf-8")
        manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        manifest_path.symlink_to(external)

        with self.assertRaisesRegex(OSError, "redirected or non-regular"):
            self._write_artifacts(
                godot_dir,
                manifest_outcome=None,
                attempt_outcome=self._failed_outcome(),
            )

        self.assertEqual(external.read_text(encoding="utf-8"), "external\n")
        self.assertFalse((godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH).exists())

    @unittest.skipIf(not hasattr(os, "mkfifo"), "FIFOs are unavailable")
    def test_refuses_nonregular_artifact_target(self) -> None:
        godot_dir = self.temp_dir / "godot"
        attempt_path = godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH
        attempt_path.parent.mkdir(parents=True)
        os.mkfifo(attempt_path)

        with self.assertRaisesRegex(OSError, "non-regular"):
            self._write_artifacts(godot_dir)

    def test_target_change_during_staging_is_detected_without_publication(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, _ = (
            self._existing_artifacts()
        )
        externally_changed_attempt = b"externally changed attempt\n"
        real_stage = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_artifact_bytes"),
        )
        stage_count = 0

        def stage_then_change_target(
            path: str,
            content: bytes,
            *,
            mode: int | None,
            suffix: str,
        ) -> Any:
            nonlocal stage_count
            staged = real_stage(path, content, mode=mode, suffix=suffix)
            stage_count += 1
            if stage_count == 1:
                attempt_path.write_bytes(externally_changed_attempt)
            return staged

        with (
            patch(
                "src.conversion.conversion_manifest._stage_artifact_bytes",
                side_effect=stage_then_change_target,
            ),
            self.assertRaisesRegex(OSError, "changed"),
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), externally_changed_attempt)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_in_place_stage_tampering_is_detected_before_publication(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_stage = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_artifact_bytes"),
        )

        def stage_then_tamper(
            path: str,
            content: bytes,
            *,
            mode: int | None,
            suffix: str,
        ) -> Any:
            staged = real_stage(path, content, mode=mode, suffix=suffix)
            if Path(path) == manifest_path and suffix == ".tmp":
                Path(staged.path).write_bytes(b"tampered manifest stage\n")
            return staged

        with (
            patch(
                "src.conversion.conversion_manifest._stage_artifact_bytes",
                side_effect=stage_then_tamper,
            ),
            self.assertRaisesRegex(OSError, "content changed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertTrue(
            any(
                "cleanup failed" in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )
        self.assertEqual(len(self._temporary_artifact_files(godot_dir)), 1)

    def test_in_place_backup_tampering_is_never_restored(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        real_stage_existing = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_existing_artifact"),
        )
        real_replace = os.replace

        def backup_then_tamper(path: str, expected: object) -> Any:
            backup = real_stage_existing(path, expected)
            if Path(path) == attempt_path and backup is not None:
                Path(backup.path).write_bytes(b"tampered attempt backup\n")
            return backup

        def fail_canonical_publish(source: str, destination: str) -> None:
            if Path(destination) == manifest_path and source.endswith(".tmp"):
                raise OSError("canonical publish failed")
            real_replace(source, destination)

        with (
            patch(
                "src.conversion.conversion_manifest._stage_existing_artifact",
                side_effect=backup_then_tamper,
            ),
            patch(
                "src.conversion.conversion_manifest.os.replace",
                side_effect=fail_canonical_publish,
            ),
            self.assertRaisesRegex(OSError, "canonical publish failed") as context,
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertNotEqual(attempt_path.read_bytes(), attempt_before)
        self.assertNotEqual(attempt_path.read_bytes(), b"tampered attempt backup\n")
        self.assertTrue(
            any(
                "rollback also failed" in note and "content changed" in note
                for note in getattr(context.exception, "__notes__", [])
            )
        )

    def test_attempt_only_rejects_canonical_change_after_digesting(self) -> None:
        godot_dir, manifest_path, attempt_path, _, attempt_before = (
            self._existing_artifacts()
        )
        external_manifest = b"externally changed manifest\n"
        real_stage = cast(
            Callable[..., Any],
            getattr(conversion_manifest_module, "_stage_artifact_bytes"),
        )
        changed = False

        def stage_then_change_manifest(
            path: str,
            content: bytes,
            *,
            mode: int | None,
            suffix: str,
        ) -> Any:
            nonlocal changed
            staged = real_stage(path, content, mode=mode, suffix=suffix)
            if not changed:
                manifest_path.write_bytes(external_manifest)
                changed = True
            return staged

        with (
            patch(
                "src.conversion.conversion_manifest._stage_artifact_bytes",
                side_effect=stage_then_change_manifest,
            ),
            self.assertRaisesRegex(OSError, "changed during publication"),
        ):
            self._write_artifacts(
                godot_dir,
                manifest_outcome=None,
                attempt_outcome=self._failed_outcome(),
            )

        self.assertEqual(manifest_path.read_bytes(), external_manifest)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_rejects_failed_or_cancelled_canonical_outcome_before_writing(self) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()

        for outcome in (self._failed_outcome(), self._cancelled_outcome()):
            with self.subTest(state=outcome.state):
                with self.assertRaisesRegex(ValueError, "success or partial"):
                    self._write_artifacts(
                        godot_dir,
                        manifest_outcome=outcome,
                        attempt_outcome=outcome,
                    )

        self.assertFalse((godot_dir / "gm2godot").exists())

    def _write_artifacts(
        self,
        godot_dir: Path,
        *,
        manifest_outcome: ConversionOutcome | None = None,
        attempt_outcome: ConversionOutcome | None = None,
    ) -> tuple[str | None, str]:
        selected_manifest_outcome = (
            self._successful_outcome()
            if manifest_outcome is None and attempt_outcome is None
            else manifest_outcome
        )
        selected_attempt_outcome = (
            attempt_outcome
            if attempt_outcome is not None
            else cast(ConversionOutcome, selected_manifest_outcome)
        )
        return write_conversion_artifacts(
            str(FIXTURE_ROOT),
            str(godot_dir),
            target_platform="windows",
            enabled_converters=selected_attempt_outcome.steps.requested,
            output_snapshot=capture_conversion_output_snapshot(str(godot_dir)),
            manifest_outcome=selected_manifest_outcome,
            attempt_outcome=selected_attempt_outcome,
        )

    def _included_publication_fixture(
        self,
        name: str,
    ) -> tuple[Path, Path, Path, Path, Path, bytes, bytes]:
        gm_dir = self.temp_dir / f"{name}-gm"
        godot_dir = self.temp_dir / f"{name}-godot"
        datafiles_dir = gm_dir / "datafiles"
        included_files_dir = godot_dir / "included_files"
        artifact_dir = godot_dir / "gm2godot"
        datafiles_dir.mkdir(parents=True)
        included_files_dir.mkdir(parents=True)
        artifact_dir.mkdir(parents=True)
        (gm_dir / "IncludedFiles.yyp").write_text(
            json.dumps(
                {
                    "%Name": "IncludedFiles",
                    "resourceType": "GMProject",
                    "resources": [],
                }
            ),
            encoding="utf-8",
        )
        payload = b"matching included payload"
        (datafiles_dir / "payload.bin").write_bytes(payload)
        output_path = included_files_dir / "payload.bin"
        output_path.write_bytes(payload)
        manifest_path = artifact_dir / "conversion_manifest.json"
        attempt_path = artifact_dir / "conversion_attempt.json"
        manifest_before = b"previous canonical manifest\n"
        attempt_before = b"previous conversion attempt\n"
        manifest_path.write_bytes(manifest_before)
        attempt_path.write_bytes(attempt_before)
        return (
            gm_dir,
            godot_dir,
            output_path,
            manifest_path,
            attempt_path,
            manifest_before,
            attempt_before,
        )

    @staticmethod
    def _successful_outcome(
        step_names: tuple[str, ...] = (),
    ) -> ConversionOutcome:
        steps = ConversionStepLedger.from_requested(step_names)
        for step_name in step_names:
            steps = steps.start(step_name).complete(step_name)
        return ConversionOutcome(state="success", steps=steps)

    @staticmethod
    def _partial_outcome() -> ConversionOutcome:
        steps = ConversionStepLedger.from_requested(("scripts", "objects"))
        steps = steps.start("scripts").complete("scripts")
        steps = steps.start("objects").complete("objects")
        return ConversionOutcome(
            state="partial",
            steps=steps,
            resources=ConversionCounts(requested=1, skipped=1),
        )

    @staticmethod
    def _failed_outcome() -> ConversionOutcome:
        steps = ConversionStepLedger.from_requested(("scripts", "objects"))
        steps = steps.start("scripts").complete("scripts")
        steps = steps.start("objects").fail("objects")
        return ConversionOutcome(
            state="failed",
            steps=steps,
            failed_step="objects",
            failure_phase="runtime",
        )

    @staticmethod
    def _cancelled_outcome() -> ConversionOutcome:
        steps = ConversionStepLedger.from_requested(("scripts", "objects"))
        steps = steps.start("scripts").complete("scripts")
        return ConversionOutcome(
            state="cancelled",
            steps=steps,
            resources=ConversionCounts(requested=1, skipped=1),
        )

    def _existing_artifacts(
        self,
        godot_dir: Path | None = None,
    ) -> tuple[Path, Path, Path, bytes, bytes]:
        selected_godot_dir = godot_dir or (self.temp_dir / "godot")
        manifest_path = selected_godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        attempt_path = selected_godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH
        manifest_path.parent.mkdir(parents=True)
        manifest_before = b'{"format_version": 1, "generated_files": []}\n'
        attempt_before = b'{"format_version": 1, "attempt": {"state": "success"}}\n'
        manifest_path.write_bytes(manifest_before)
        attempt_path.write_bytes(attempt_before)
        return (
            selected_godot_dir,
            manifest_path,
            attempt_path,
            manifest_before,
            attempt_before,
        )

    @staticmethod
    def _temporary_artifact_files(godot_dir: Path) -> list[Path]:
        artifact_dir = godot_dir / "gm2godot"
        if not artifact_dir.exists():
            return []
        return sorted(
            [
                *artifact_dir.glob(".conversion_manifest.json.*.tmp"),
                *artifact_dir.glob(".conversion_manifest.json.*.backup"),
                *artifact_dir.glob(".conversion_attempt.json.*.tmp"),
                *artifact_dir.glob(".conversion_attempt.json.*.backup"),
            ]
        )


if __name__ == "__main__":
    unittest.main()
