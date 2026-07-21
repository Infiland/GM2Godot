from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from src import cli
from src.conversion import asset_registry as asset_registry_module
from src.conversion import (
    conversion_artifact_generation as generation_module,
)
from src.conversion import conversion_manifest as conversion_manifest_module
from src.conversion.anchored_artifacts import ByteArtifactTransaction
from src.conversion.architecture_policy import ARCHITECTURE_POLICY_RELATIVE_PATH
from src.conversion.asset_registry import (
    AssetRegistryConverter,
    AssetRegistryEntry,
    AssetRegistryPublication,
)
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_MANIFEST_RELATIVE_PATH,
    build_conversion_manifest,
    capture_conversion_output_snapshot,
    recover_conversion_artifacts,
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
        self.assertEqual(generated_by_path["project.godot"]["kind"], "project")
        inventory_entries = cast(
            list[dict[str, object]],
            cast(dict[str, object], manifest["generation_inventory"])["entries"],
        )
        inventory_by_path = {
            str(entry["path"]): entry
            for entry in inventory_entries
        }
        self.assertEqual(
            inventory_by_path["project.godot"]["owner"],
            {
                "class": "shared_owner",
                "name": "project_configuration",
            },
        )

    def test_artifact_pair_commits_attempt_first_through_one_bound_directory(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "godot"
        godot_dir.mkdir()
        durable_steps: list[tuple[str, str]] = []

        def record_commits(
            phase: str,
            directory_path: str,
            name: str | None,
        ) -> None:
            if (
                phase
                in {
                    "generation_journal_prepared",
                    "generation_artifact_durable",
                    "generation_committed",
                }
                and name is not None
            ):
                durable_steps.append((directory_path, name))

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=record_commits,
        ):
            manifest_path, attempt_path = self._write_artifacts(godot_dir)

        artifact_directory = os.path.abspath(godot_dir / "gm2godot")
        self.assertEqual(
            durable_steps,
            [
                (
                    artifact_directory,
                    generation_module.CONVERSION_GENERATION_JOURNAL_NAME,
                ),
                (artifact_directory, "conversion_attempt.json"),
                (artifact_directory, "conversion_manifest.json"),
                (
                    artifact_directory,
                    generation_module.CONVERSION_GENERATION_POINTER_NAME,
                ),
            ],
        )
        self.assertTrue(Path(cast(str, manifest_path)).is_file())
        self.assertTrue(Path(attempt_path).is_file())
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_subprocess_interruption_recovers_every_generation_boundary(
        self,
    ) -> None:
        phases = (
            ("generation_journal_stage_created", 1, False),
            ("generation_journal_staged", 1, False),
            ("generation_journal_published", 1, False),
            ("generation_journal_prepared", 1, False),
            ("generation_artifact_stage_created", 1, False),
            ("generation_artifact_staged", 1, False),
            ("generation_artifact_published", 1, False),
            ("generation_artifact_durable", 1, False),
            ("generation_artifact_stage_created", 2, False),
            ("generation_artifact_staged", 2, False),
            ("generation_artifact_published", 2, False),
            ("generation_artifact_durable", 2, False),
            ("generation_pointer_stage_created", 1, False),
            ("generation_pointer_staged", 1, False),
            ("generation_pointer_published", 1, True),
            ("generation_committed", 1, True),
            ("generation_temporary_cleanup_complete", 1, True),
            ("generation_journal_unlinked", 1, True),
            ("generation_journal_removed", 1, True),
        )
        control_dir = self.temp_dir / "generation-control"
        control_dir.mkdir()
        partial_outcome = self._partial_outcome()
        self._write_artifacts(
            control_dir,
            manifest_outcome=partial_outcome,
            attempt_outcome=partial_outcome,
        )
        expected_new = self._artifact_pair_snapshot(control_dir)

        for index, (phase, occurrence, committed) in enumerate(phases):
            with self.subTest(phase=phase, occurrence=occurrence):
                godot_dir = self.temp_dir / f"generation-boundary-{index}"
                godot_dir.mkdir()
                self._write_artifacts(godot_dir)
                expected_previous = self._artifact_pair_snapshot(godot_dir)

                interrupted = self._run_generation_subprocess(
                    godot_dir,
                    operation="publish",
                    phase=phase,
                    occurrence=occurrence,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )

                recover_conversion_artifacts(str(godot_dir))

                self.assertEqual(
                    self._artifact_pair_snapshot(godot_dir),
                    expected_new if committed else expected_previous,
                )
                self._assert_artifact_pair_digest_matches(godot_dir)
                self.assertEqual(
                    self._generation_transaction_debris(godot_dir),
                    (),
                )

    def test_subprocess_interruption_recovers_every_rollback_boundary(
        self,
    ) -> None:
        cases = (
            (
                "generation_journal_stage_created",
                "generation_journal_published",
            ),
            (
                "generation_journal_stage_created",
                "generation_journal_promoted",
            ),
            (
                "generation_artifact_durable",
                "generation_artifact_stage_created",
            ),
            ("generation_artifact_durable", "generation_artifact_staged"),
            (
                "generation_artifact_durable",
                "generation_rollback_artifact_published",
            ),
            (
                "generation_artifact_durable",
                "generation_rollback_artifact_durable",
            ),
            ("generation_artifact_durable", "generation_rollback_complete"),
            (
                "generation_pointer_staged",
                "generation_temporary_removed",
            ),
            (
                "generation_artifact_durable",
                "generation_temporary_cleanup_complete",
            ),
            ("generation_artifact_durable", "generation_journal_unlinked"),
            ("generation_artifact_durable", "generation_journal_removed"),
        )
        for index, (forward_phase, recovery_phase) in enumerate(cases):
            with self.subTest(
                forward_phase=forward_phase,
                recovery_phase=recovery_phase,
            ):
                godot_dir = self.temp_dir / f"rollback-boundary-{index}"
                godot_dir.mkdir()
                self._write_artifacts(godot_dir)
                expected_previous = self._artifact_pair_snapshot(godot_dir)

                interrupted = self._run_generation_subprocess(
                    godot_dir,
                    operation="publish",
                    phase=forward_phase,
                    occurrence=1,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )
                interrupted_recovery = self._run_generation_subprocess(
                    godot_dir,
                    operation="recover",
                    phase=recovery_phase,
                    occurrence=1,
                )
                self.assertEqual(
                    interrupted_recovery.returncode,
                    86,
                    interrupted_recovery.stdout + interrupted_recovery.stderr,
                )

                recover_conversion_artifacts(str(godot_dir))

                self.assertEqual(
                    self._artifact_pair_snapshot(godot_dir),
                    expected_previous,
                )
                self._assert_artifact_pair_digest_matches(godot_dir)
                self.assertEqual(
                    self._generation_transaction_debris(godot_dir),
                    (),
                )

    def test_attempt_only_generation_recovery_preserves_canonical(
        self,
    ) -> None:
        control_dir = self.temp_dir / "attempt-only-control"
        control_dir.mkdir()
        self._write_artifacts(control_dir)
        canonical_before = (
            control_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        ).read_bytes()
        self._write_artifacts(
            control_dir,
            manifest_outcome=None,
            attempt_outcome=self._failed_outcome(),
        )
        expected_failed = self._artifact_pair_snapshot(control_dir)

        for index, (phase, committed) in enumerate(
            (
                ("generation_artifact_durable", False),
                ("generation_pointer_published", True),
            )
        ):
            with self.subTest(phase=phase):
                godot_dir = self.temp_dir / f"attempt-only-{index}"
                godot_dir.mkdir()
                self._write_artifacts(godot_dir)
                expected_previous = self._artifact_pair_snapshot(godot_dir)

                interrupted = self._run_generation_subprocess(
                    godot_dir,
                    operation="attempt-only",
                    phase=phase,
                    occurrence=1,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )
                recover_conversion_artifacts(str(godot_dir))

                self.assertEqual(
                    self._artifact_pair_snapshot(godot_dir),
                    expected_failed if committed else expected_previous,
                )
                self.assertEqual(
                    (godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH).read_bytes(),
                    canonical_before,
                )
                self._assert_artifact_pair_digest_matches(godot_dir)

    def test_first_attempt_only_generation_recovers_absent_canonical(
        self,
    ) -> None:
        for index, (phase, committed) in enumerate(
            (
                ("generation_artifact_durable", False),
                ("generation_pointer_published", True),
            )
        ):
            with self.subTest(phase=phase):
                godot_dir = self.temp_dir / f"first-attempt-only-{index}"
                godot_dir.mkdir()
                interrupted = self._run_generation_subprocess(
                    godot_dir,
                    operation="attempt-only",
                    phase=phase,
                    occurrence=1,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )

                recover_conversion_artifacts(str(godot_dir))

                attempt_path = godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH
                manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
                self.assertEqual(attempt_path.exists(), committed)
                self.assertFalse(manifest_path.exists())
                if committed:
                    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        attempt["canonical_manifest"]["status"],
                        "absent",
                    )
                    self.assertIsNone(attempt["canonical_manifest"]["sha256"])
                self._assert_artifact_pair_digest_matches(godot_dir)
                self.assertEqual(
                    self._generation_transaction_debris(godot_dir),
                    (),
                )

    def test_first_publication_rollback_resumes_after_hard_exit(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "first-publication-rollback"
        godot_dir.mkdir()
        interrupted = self._run_generation_subprocess(
            godot_dir,
            operation="attempt-only",
            phase="generation_artifact_durable",
            occurrence=1,
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        interrupted_recovery = self._run_generation_subprocess(
            godot_dir,
            operation="recover",
            phase="generation_rollback_artifact_published",
            occurrence=1,
        )
        self.assertEqual(
            interrupted_recovery.returncode,
            86,
            interrupted_recovery.stdout + interrupted_recovery.stderr,
        )

        recover_conversion_artifacts(str(godot_dir))

        self.assertEqual(
            self._artifact_pair_snapshot(godot_dir),
            ((None, None), (None, None)),
        )
        self.assertEqual(
            self._generation_transaction_debris(godot_dir),
            (),
        )

    def test_lock_initialization_recovers_after_hard_exit(self) -> None:
        for index, phase in enumerate(
            ("generation_lock_initialized", "generation_lock_durable")
        ):
            with self.subTest(phase=phase):
                godot_dir = self.temp_dir / f"lock-initialization-{index}"
                godot_dir.mkdir()
                interrupted = self._run_generation_subprocess(
                    godot_dir,
                    operation="attempt-only",
                    phase=phase,
                    occurrence=1,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )

                recover_conversion_artifacts(str(godot_dir))

                self.assertEqual(
                    self._artifact_pair_snapshot(godot_dir),
                    ((None, None), (None, None)),
                )
                lock_path = (
                    godot_dir
                    / "gm2godot"
                    / generation_module.CONVERSION_GENERATION_LOCK_NAME
                )
                self.assertEqual(lock_path.read_bytes(), b"\x00")

        empty_lock_dir = self.temp_dir / "empty-lock-initialization"
        (empty_lock_dir / "gm2godot").mkdir(parents=True)
        empty_lock_path = (
            empty_lock_dir
            / "gm2godot"
            / generation_module.CONVERSION_GENERATION_LOCK_NAME
        )
        empty_lock_path.write_bytes(b"")

        recover_conversion_artifacts(str(empty_lock_dir))

        self.assertEqual(empty_lock_path.read_bytes(), b"\x00")

    def test_malformed_and_unknown_recovery_state_is_preserved(self) -> None:
        for index, (name, content) in enumerate(
            (
                (
                    generation_module.CONVERSION_GENERATION_JOURNAL_NAME,
                    b"{not canonical json\n",
                ),
                (
                    ".gm2godot-conversion-unknown.state",
                    b"unknown reserved state\n",
                ),
            )
        ):
            with self.subTest(name=name):
                godot_dir = self.temp_dir / f"malformed-state-{index}"
                godot_dir.mkdir()
                self._write_artifacts(godot_dir)
                pair_before = self._artifact_pair_snapshot(godot_dir)
                reserved_path = godot_dir / "gm2godot" / name
                reserved_path.write_bytes(content)

                with self.assertRaises(OSError):
                    recover_conversion_artifacts(str(godot_dir))

                self.assertEqual(
                    self._artifact_pair_snapshot(godot_dir),
                    pair_before,
                )
                self.assertEqual(reserved_path.read_bytes(), content)

    @unittest.skipUnless(os.name == "posix", "POSIX links are required")
    def test_redirected_and_hardlinked_recovery_records_are_preserved(
        self,
    ) -> None:
        for index, redirected in enumerate((True, False)):
            with self.subTest(redirected=redirected):
                godot_dir = self.temp_dir / f"linked-record-{index}"
                godot_dir.mkdir()
                self._write_artifacts(godot_dir)
                pair_before = self._artifact_pair_snapshot(godot_dir)
                pointer_path = (
                    godot_dir
                    / "gm2godot"
                    / generation_module.CONVERSION_GENERATION_POINTER_NAME
                )
                external_path = self.temp_dir / f"external-pointer-{index}"
                if redirected:
                    pointer_content = pointer_path.read_bytes()
                    pointer_path.unlink()
                    external_path.write_bytes(pointer_content)
                    pointer_path.symlink_to(external_path)
                else:
                    os.link(pointer_path, external_path)
                    pointer_content = external_path.read_bytes()

                with self.assertRaises(OSError):
                    recover_conversion_artifacts(str(godot_dir))

                self.assertEqual(
                    self._artifact_pair_snapshot(godot_dir),
                    pair_before,
                )
                self.assertEqual(external_path.read_bytes(), pointer_content)
                if redirected:
                    self.assertTrue(pointer_path.is_symlink())
                else:
                    self.assertGreaterEqual(pointer_path.stat().st_nlink, 2)

    def test_mounted_recovery_record_is_rejected_without_mutation(self) -> None:
        godot_dir = self.temp_dir / "mounted-record"
        godot_dir.mkdir()
        self._write_artifacts(godot_dir)
        pair_before = self._artifact_pair_snapshot(godot_dir)
        pointer_path = (
            godot_dir
            / "gm2godot"
            / generation_module.CONVERSION_GENERATION_POINTER_NAME
        )
        pointer_before = pointer_path.read_bytes()
        real_ismount = os.path.ismount

        def model_pointer_mount(path: str) -> bool:
            return os.path.normcase(os.path.abspath(path)) == os.path.normcase(
                os.path.abspath(pointer_path)
            ) or real_ismount(path)

        with (
            patch.object(
                generation_module.os.path,
                "ismount",
                side_effect=model_pointer_mount,
            ),
            self.assertRaisesRegex(OSError, "mounted"),
        ):
            recover_conversion_artifacts(str(godot_dir))

        self.assertEqual(
            self._artifact_pair_snapshot(godot_dir),
            pair_before,
        )
        self.assertEqual(pointer_path.read_bytes(), pointer_before)

    def test_legacy_digest_mismatch_is_rejected_before_migration(self) -> None:
        godot_dir, manifest_path, attempt_path, _, _ = self._existing_artifacts()
        manifest_path.write_bytes(b'{"externally": "mismatched"}\n')
        pair_before = self._artifact_pair_snapshot(godot_dir)

        with self.assertRaisesRegex(OSError, "digest mismatch"):
            self._write_artifacts(godot_dir)

        self.assertEqual(
            self._artifact_pair_snapshot(godot_dir),
            pair_before,
        )
        self.assertFalse(
            (
                attempt_path.parent
                / generation_module.CONVERSION_GENERATION_POINTER_NAME
            ).exists()
        )
        self.assertFalse(
            (
                attempt_path.parent
                / generation_module.CONVERSION_GENERATION_JOURNAL_NAME
            ).exists()
        )

    def test_generation_lock_rejects_concurrent_recovery(self) -> None:
        godot_dir = self.temp_dir / "generation-lock"
        godot_dir.mkdir()
        self._write_artifacts(godot_dir)
        pair_before = self._artifact_pair_snapshot(godot_dir)

        with ByteArtifactTransaction.open(
            str(godot_dir),
            "gm2godot",
            create=False,
            description="conversion artifact directory",
        ) as transaction:
            with generation_module.ConversionArtifactGenerationLock.acquire(
                transaction
            ):
                concurrent = self._run_generation_subprocess(
                    godot_dir,
                    operation="recover",
                    phase="phase-that-must-not-run",
                    occurrence=1,
                )

        self.assertNotEqual(concurrent.returncode, 0)
        self.assertIn(
            "already publishing or recovering",
            concurrent.stderr,
        )
        self.assertEqual(
            self._artifact_pair_snapshot(godot_dir),
            pair_before,
        )

    def test_attempt_only_preserves_canonical_bytes_and_records_exact_digest(
        self,
    ) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, _ = (
            self._existing_artifacts()
        )

        returned_manifest, returned_attempt = self._write_artifacts(
            godot_dir,
            manifest_outcome=None,
            attempt_outcome=self._failed_outcome(),
        )

        self.assertIsNone(returned_manifest)
        self.assertEqual(Path(returned_attempt), attempt_path)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        self.assertEqual(attempt["attempt"]["state"], "failed")
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
        self.assertEqual(
            manifest["conversion"]["steps"]["completed"],
            ["scripts", "objects"],
        )
        attempt = json.loads(Path(attempt_path_value).read_text(encoding="utf-8"))
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        )
        self.assertEqual(attempt["canonical_manifest"]["status"], "updated")

    def test_generated_files_exclude_transaction_files_but_keep_manifest_self(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "godot"
        artifact_dir = godot_dir / "gm2godot"
        artifact_dir.mkdir(parents=True)
        snapshot = capture_conversion_output_snapshot(str(godot_dir))
        excluded_names = (
            "conversion_attempt.json",
            ".conversion_attempt.json.stale.tmp",
            ".conversion_attempt.json.abcdefgh.recovery.backup",
            ".conversion_manifest.json.stale.backup",
            generation_module.CONVERSION_GENERATION_LOCK_NAME,
            generation_module.CONVERSION_GENERATION_JOURNAL_NAME,
            generation_module.CONVERSION_GENERATION_POINTER_NAME,
            (".conversion_attempt.json." + ("a" * 32) + ".generation-desired.tmp"),
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
            generated["gm2godot/conversion_manifest.json"]["sha256"],
            "self",
        )

    def test_serialization_failure_preserves_pair_without_creating_directory(
        self,
    ) -> None:
        existing_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts(self.temp_dir / "existing")
        )
        missing_dir = self.temp_dir / "missing"
        missing_dir.mkdir()

        for godot_dir in (existing_dir, missing_dir):
            with (
                patch(
                    "src.conversion.conversion_manifest._serialize_json",
                    side_effect=TypeError("injected serialization failure"),
                ),
                self.assertRaisesRegex(
                    TypeError,
                    "injected serialization failure",
                ),
            ):
                self._write_artifacts(godot_dir)

        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertFalse((missing_dir / "gm2godot").exists())

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
        real_revalidate = AssetRegistryConverter.revalidate_publication
        validation_phases: list[bool] = []

        def delete_then_revalidate(
            converter: AssetRegistryConverter,
            publication: AssetRegistryPublication,
            *,
            validate_content: bool,
        ) -> None:
            validation_phases.append(validate_content)
            if not validate_content:
                output_path.unlink()
            real_revalidate(
                converter,
                publication,
                validate_content=validate_content,
            )

        with (
            patch.object(
                AssetRegistryConverter,
                "revalidate_publication",
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

        self.assertEqual(validation_phases, [False])
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
        output_stat = output_path.stat()
        replacement = b"tampered included payload"
        self.assertEqual(len(replacement), output_stat.st_size)
        real_revalidate = AssetRegistryConverter.revalidate_publication
        validation_phases: list[bool] = []

        def mutate_then_revalidate(
            converter: AssetRegistryConverter,
            publication: AssetRegistryPublication,
            *,
            validate_content: bool,
        ) -> None:
            validation_phases.append(validate_content)
            if validate_content:
                with output_path.open("r+b", buffering=0) as output_file:
                    output_file.write(replacement)
                    os.fsync(output_file.fileno())
                os.utime(
                    output_path,
                    ns=(output_stat.st_atime_ns, output_stat.st_mtime_ns),
                )
                mutated_stat = output_path.stat()
                self.assertEqual(mutated_stat.st_size, output_stat.st_size)
                self.assertEqual(mutated_stat.st_mtime_ns, output_stat.st_mtime_ns)
            real_revalidate(
                converter,
                publication,
                validate_content=validate_content,
            )

        with (
            patch.object(
                AssetRegistryConverter,
                "revalidate_publication",
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

        self.assertEqual(validation_phases, [False, True])
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_frozen_inventory_same_size_change_rolls_back_artifact_pair(
        self,
    ) -> None:
        godot_dir = self.temp_dir / "frozen-inventory-change"
        output = godot_dir / "scripts" / "managed.gd"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"original bytes")
        self._write_artifacts(godot_dir)
        pair_before = self._artifact_pair_snapshot(godot_dir)
        output_stat = output.stat()
        real_validate = conversion_manifest_module.validate_generation_inventory
        validation_count = 0

        def mutate_before_canonical_commit(
            root_path: str,
            inventory: object,
        ) -> None:
            nonlocal validation_count
            validation_count += 1
            if validation_count == 2:
                output.write_bytes(b"mutated! bytes")
                os.utime(
                    output,
                    ns=(output_stat.st_atime_ns, output_stat.st_mtime_ns),
                )
            real_validate(root_path, cast(Any, inventory))

        with (
            patch.object(
                conversion_manifest_module,
                "validate_generation_inventory",
                side_effect=mutate_before_canonical_commit,
            ),
            self.assertRaisesRegex(OSError, "changed"),
        ):
            self._write_artifacts(godot_dir)

        self.assertEqual(validation_count, 2)
        self.assertEqual(
            self._artifact_pair_snapshot(godot_dir),
            pair_before,
        )
        self.assertEqual(output.read_bytes(), b"mutated! bytes")

    def test_included_file_manifest_publication_reads_payload_six_times(
        self,
    ) -> None:
        (
            gm_dir,
            godot_dir,
            output_path,
            _manifest_path,
            _attempt_path,
            _manifest_before,
            _attempt_before,
        ) = self._included_publication_fixture("read-budget")
        payload_size = output_path.stat().st_size
        real_read_chunk = cast(
            Callable[[Any], bytes],
            getattr(
                asset_registry_module,
                "_read_included_file_validation_chunk",
            ),
        )
        real_revalidate = AssetRegistryConverter.revalidate_publication
        payload_bytes_read = 0
        phase_reads: list[tuple[bool, int]] = []

        def count_payload_bytes(opened_file: Any) -> bytes:
            nonlocal payload_bytes_read
            chunk = real_read_chunk(opened_file)
            payload_bytes_read += len(chunk)
            return chunk

        def record_phase_reads(
            converter: AssetRegistryConverter,
            publication: AssetRegistryPublication,
            *,
            validate_content: bool,
        ) -> None:
            before = payload_bytes_read
            real_revalidate(
                converter,
                publication,
                validate_content=validate_content,
            )
            phase_reads.append((validate_content, payload_bytes_read - before))

        with (
            patch.object(
                asset_registry_module,
                "_read_included_file_validation_chunk",
                new=count_payload_bytes,
            ),
            patch.object(
                AssetRegistryConverter,
                "revalidate_publication",
                new=record_phase_reads,
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

        self.assertEqual(
            phase_reads,
            [(False, 0), (True, 2 * payload_size)],
        )
        self.assertEqual(payload_bytes_read, 6 * payload_size)

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

    def test_stage_and_canonical_commit_failures_restore_existing_pair(self) -> None:
        cases = (
            (
                "before_generation_desired_stage",
                "conversion_manifest.json",
                "staging failed",
            ),
            ("before_commit", "conversion_manifest.json", "commit failed"),
        )
        for phase, name, message in cases:
            with self.subTest(phase=phase):
                (
                    godot_dir,
                    manifest_path,
                    attempt_path,
                    manifest_before,
                    attempt_before,
                ) = self._existing_artifacts(self.temp_dir / phase)

                def fail_selected_phase(
                    current_phase: str,
                    _directory_path: str,
                    current_name: str | None,
                ) -> None:
                    if current_phase == phase and current_name == name:
                        raise OSError(message)

                with (
                    patch(
                        "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                        side_effect=fail_selected_phase,
                    ),
                    self.assertRaisesRegex(OSError, message),
                ):
                    self._write_artifacts(godot_dir)

                self.assertEqual(manifest_path.read_bytes(), manifest_before)
                self.assertEqual(attempt_path.read_bytes(), attempt_before)
                self.assertEqual(self._temporary_artifact_files(godot_dir), [])

    def test_final_publication_preserves_unknown_pair_replacement(self) -> None:
        godot_dir, manifest_path, attempt_path, manifest_before, attempt_before = (
            self._existing_artifacts()
        )
        corrupted_attempt = b"corrupted during canonical publication\n"

        def corrupt_attempt_after_canonical(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            if (
                phase == "generation_artifact_durable"
                and name == "conversion_manifest.json"
            ):
                attempt_path.write_bytes(corrupted_attempt)

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=corrupt_attempt_after_canonical,
            ),
            self.assertRaisesRegex(
                OSError,
                "Unknown replacement",
            ) as raised,
        ):
            self._write_artifacts(godot_dir)

        self.assertNotEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(attempt_path.read_bytes(), corrupted_attempt)
        self.assertTrue(
            (
                attempt_path.parent
                / generation_module.CONVERSION_GENERATION_JOURNAL_NAME
            ).is_file()
        )
        self.assertTrue(
            any(
                "rollback also failed" in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )
        self.assertNotEqual(attempt_before, corrupted_attempt)

    def test_stale_cleanup_preserves_canonical_recovery_until_canonical_update(
        self,
    ) -> None:
        godot_dir, manifest_path, _, _, _ = self._existing_artifacts()
        attempt_stale = manifest_path.parent / (
            ".conversion_attempt.json.abcdefgh.backup"
        )
        manifest_recovery = manifest_path.parent / (
            ".conversion_manifest.json.abcdefgh.recovery.backup"
        )
        attempt_stale.write_bytes(b"old attempt backup\n")
        manifest_recovery.write_bytes(b"old canonical recovery\n")

        self._write_artifacts(
            godot_dir,
            manifest_outcome=None,
            attempt_outcome=self._failed_outcome(),
        )

        self.assertFalse(attempt_stale.exists())
        self.assertEqual(
            manifest_recovery.read_bytes(),
            b"old canonical recovery\n",
        )

        self._write_artifacts(godot_dir)

        self.assertFalse(manifest_recovery.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX links are required")
    def test_stale_cleanup_refuses_redirected_and_hardlinked_lookalikes(
        self,
    ) -> None:
        godot_dir, manifest_path, _, _, _ = self._existing_artifacts()
        external = self.temp_dir / "external-stale.json"
        external_content = b"external sentinel\n"
        external.write_bytes(external_content)
        symlink = manifest_path.parent / (
            ".conversion_attempt.json.redirected.backup"
        )
        hardlink = manifest_path.parent / (
            ".conversion_manifest.json.hardlinked.backup"
        )
        symlink.symlink_to(external)
        os.link(external, hardlink)

        self._write_artifacts(godot_dir)

        self.assertTrue(symlink.is_symlink())
        self.assertTrue(hardlink.is_file())
        self.assertEqual(external.read_bytes(), external_content)
        self.assertEqual(hardlink.read_bytes(), external_content)

    def test_attempt_only_guard_rejects_canonical_change_after_digesting(
        self,
    ) -> None:
        godot_dir, manifest_path, attempt_path, _, attempt_before = (
            self._existing_artifacts()
        )
        external_manifest = b"externally changed manifest\n"
        changed = False

        def change_after_attempt_stage(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            nonlocal changed
            if (
                not changed
                and phase == "generation_artifact_staged"
                and name == "conversion_attempt.json"
            ):
                changed = True
                manifest_path.write_bytes(external_manifest)

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=change_after_attempt_stage,
            ),
            self.assertRaisesRegex(OSError, "Unknown replacement"),
        ):
            self._write_artifacts(
                godot_dir,
                manifest_outcome=None,
                attempt_outcome=self._failed_outcome(),
            )

        self.assertTrue(changed)
        self.assertEqual(manifest_path.read_bytes(), external_manifest)
        self.assertEqual(attempt_path.read_bytes(), attempt_before)
        self.assertTrue(
            (
                manifest_path.parent
                / generation_module.CONVERSION_GENERATION_JOURNAL_NAME
            ).is_file()
        )

    @unittest.skipIf(os.name == "nt", "Exact POSIX modes are unavailable")
    def test_existing_and_new_artifact_modes_remain_exact(self) -> None:
        godot_dir, manifest_path, attempt_path, _, _ = self._existing_artifacts()
        os.chmod(manifest_path, 0o440)
        os.chmod(attempt_path, 0o640)

        self._write_artifacts(godot_dir)

        self.assertEqual(stat.S_IMODE(os.lstat(manifest_path).st_mode), 0o440)
        self.assertEqual(stat.S_IMODE(os.lstat(attempt_path).st_mode), 0o640)

        fresh_dir = self.temp_dir / "fresh"
        fresh_dir.mkdir()
        manifest_value, attempt_value = self._write_artifacts(fresh_dir)
        for artifact_path in (
            Path(cast(str, manifest_value)),
            Path(attempt_value),
        ):
            self.assertEqual(
                stat.S_IMODE(os.lstat(artifact_path).st_mode) & 0o077,
                0,
            )

    @unittest.skipUnless(os.name == "posix", "POSIX relocation is required")
    def test_physical_replacement_never_mutates_replacement_at_any_pair_boundary(
        self,
    ) -> None:
        cases = [
            (
                "before_generation_journal_stage",
                generation_module.CONVERSION_GENERATION_JOURNAL_NAME,
            ),
            (
                "before_commit",
                generation_module.CONVERSION_GENERATION_JOURNAL_NAME,
            ),
            (
                "generation_journal_prepared",
                generation_module.CONVERSION_GENERATION_JOURNAL_NAME,
            ),
            ("before_generation_desired_stage", "conversion_attempt.json"),
            ("before_commit", "conversion_attempt.json"),
            ("generation_artifact_durable", "conversion_attempt.json"),
            ("before_generation_desired_stage", "conversion_manifest.json"),
            ("before_commit", "conversion_manifest.json"),
            ("generation_artifact_durable", "conversion_manifest.json"),
            (
                "before_generation_pointer_stage",
                generation_module.CONVERSION_GENERATION_POINTER_NAME,
            ),
            (
                "before_commit",
                generation_module.CONVERSION_GENERATION_POINTER_NAME,
            ),
            (
                "generation_committed",
                generation_module.CONVERSION_GENERATION_POINTER_NAME,
            ),
            ("generation_temporary_cleanup_complete", None),
            (
                "generation_journal_unlinked",
                generation_module.CONVERSION_GENERATION_JOURNAL_NAME,
            ),
        ]
        for index, (selected_phase, selected_name) in enumerate(cases):
            with self.subTest(
                phase=selected_phase,
                name=selected_name,
            ):
                godot_dir, _, _, _, _ = self._existing_artifacts(
                    self.temp_dir / f"boundary-{index}"
                )
                artifact_directory = godot_dir / "gm2godot"
                parked = godot_dir / "gm2godot.parked"
                stale = artifact_directory / (
                    ".conversion_attempt.json.stale.backup"
                )
                stale.write_bytes(b"owned stale backup\n")
                outside = godot_dir / "outside-hardlink.json"
                outside.write_bytes(b"outside hardlink sentinel\n")
                swapped = False
                replacement_before: dict[
                    str,
                    tuple[int, int, int, bytes],
                ] = {}

                def replace_directory(
                    phase: str,
                    directory_path: str,
                    name: str | None,
                ) -> None:
                    nonlocal replacement_before, swapped
                    if (
                        phase != selected_phase
                        or name != selected_name
                        or os.path.abspath(directory_path)
                        != os.path.abspath(artifact_directory)
                    ):
                        return
                    swapped = True
                    os.rename(artifact_directory, parked)
                    artifact_directory.mkdir()
                    (
                        artifact_directory / "conversion_attempt.json"
                    ).write_bytes(b"replacement attempt\n")
                    (
                        artifact_directory / "conversion_manifest.json"
                    ).write_bytes(b"replacement manifest\n")
                    (artifact_directory / "sentinel.txt").write_bytes(
                        b"replacement sentinel\n"
                    )
                    os.link(
                        outside,
                        artifact_directory
                        / ".conversion_attempt.json.abcdefgh.backup",
                    )
                    replacement_before = _directory_snapshot(
                        artifact_directory
                    )

                with (
                    patch(
                        "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                        side_effect=replace_directory,
                    ),
                    self.assertRaises(OSError),
                ):
                    self._write_artifacts(godot_dir)

                self.assertTrue(swapped)
                self.assertEqual(
                    _directory_snapshot(artifact_directory),
                    replacement_before,
                )
                self.assertEqual(
                    outside.read_bytes(),
                    b"outside hardlink sentinel\n",
                )

    @unittest.skipUnless(os.name == "posix", "POSIX relocation is required")
    def test_rollback_and_recovery_stay_bound_after_physical_replacement(
        self,
    ) -> None:
        cases = (
            ("before_generation_previous_stage", "conversion_attempt.json"),
            (
                "generation_rollback_artifact_published",
                "conversion_attempt.json",
            ),
        )
        for selected_phase, selected_name in cases:
            with self.subTest(phase=selected_phase):
                godot_dir, _, _, _, _ = self._existing_artifacts(
                    self.temp_dir / selected_phase
                )
                artifact_directory = godot_dir / "gm2godot"
                parked = godot_dir / "gm2godot.parked"
                outside = godot_dir / "outside-hardlink.json"
                outside.write_bytes(b"outside rollback sentinel\n")
                swapped = False
                replacement_before: dict[
                    str,
                    tuple[int, int, int, bytes],
                ] = {}

                def fail_then_replace(
                    phase: str,
                    directory_path: str,
                    name: str | None,
                ) -> None:
                    nonlocal replacement_before, swapped
                    if (
                        phase == "before_commit"
                        and name == "conversion_manifest.json"
                    ):
                        raise OSError("injected canonical failure")
                    if (
                        swapped
                        or phase != selected_phase
                        or name != selected_name
                        or os.path.abspath(directory_path)
                        != os.path.abspath(artifact_directory)
                    ):
                        return
                    swapped = True
                    os.rename(artifact_directory, parked)
                    artifact_directory.mkdir()
                    (
                        artifact_directory / "conversion_attempt.json"
                    ).write_bytes(b"replacement attempt\n")
                    (
                        artifact_directory / "conversion_manifest.json"
                    ).write_bytes(b"replacement manifest\n")
                    (artifact_directory / "sentinel.txt").write_bytes(
                        b"replacement sentinel\n"
                    )
                    os.link(
                        outside,
                        artifact_directory
                        / ".conversion_manifest.json.abcdefgh.recovery.backup",
                    )
                    replacement_before = _directory_snapshot(
                        artifact_directory
                    )

                with (
                    patch(
                        "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                        side_effect=fail_then_replace,
                    ),
                    self.assertRaisesRegex(
                        OSError,
                        "injected canonical failure",
                    ) as raised,
                ):
                    self._write_artifacts(godot_dir)

                self.assertTrue(swapped)
                self.assertEqual(
                    _directory_snapshot(artifact_directory),
                    replacement_before,
                )
                self.assertEqual(
                    outside.read_bytes(),
                    b"outside rollback sentinel\n",
                )
                self.assertTrue(
                    any(
                        "rollback also failed" in note
                        for note in getattr(
                            raised.exception,
                            "__notes__",
                            (),
                        )
                    )
                )

    @unittest.skipUnless(os.name == "nt", "Native Windows handles are required")
    def test_windows_bindings_block_root_and_directory_relocation(self) -> None:
        godot_dir, _, _, _, _ = self._existing_artifacts()
        artifact_directory = godot_dir / "gm2godot"
        parked_root = godot_dir.with_name("godot.parked")
        parked_artifacts = godot_dir / "gm2godot.parked"
        relocation_checked = False

        def try_relocation(
            phase: str,
            _directory_path: str,
            _name: str | None,
        ) -> None:
            nonlocal relocation_checked
            if phase != "before_generation_journal_stage" or relocation_checked:
                return
            relocation_checked = True
            with self.assertRaises(OSError):
                os.rename(artifact_directory, parked_artifacts)
            with self.assertRaises(OSError):
                os.rename(godot_dir, parked_root)

        with patch(
            "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
            side_effect=try_relocation,
        ):
            self._write_artifacts(godot_dir)

        self.assertTrue(relocation_checked)

    @unittest.skipUnless(os.name == "nt", "Native Windows modes are required")
    def test_windows_read_only_pair_is_replaced_and_rolled_back_exactly(
        self,
    ) -> None:
        success_dir, success_manifest, success_attempt, manifest_before, attempt_before = (
            self._existing_artifacts(self.temp_dir / "readonly-success")
        )
        for path in (success_manifest, success_attempt):
            os.chmod(path, 0o444)

        self._write_artifacts(success_dir)

        self.assertNotEqual(success_manifest.read_bytes(), manifest_before)
        self.assertNotEqual(success_attempt.read_bytes(), attempt_before)
        for path in (success_manifest, success_attempt):
            self.assertFalse(stat.S_IMODE(os.lstat(path).st_mode) & stat.S_IWRITE)

        rollback_dir, rollback_manifest, rollback_attempt, manifest_before, attempt_before = (
            self._existing_artifacts(self.temp_dir / "readonly-rollback")
        )
        for path in (rollback_manifest, rollback_attempt):
            os.chmod(path, 0o444)

        def fail_canonical_commit(
            phase: str,
            _directory_path: str,
            name: str | None,
        ) -> None:
            if phase == "before_commit" and name == "conversion_manifest.json":
                raise OSError("injected read-only canonical failure")

        with (
            patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_canonical_commit,
            ),
            self.assertRaisesRegex(
                OSError,
                "injected read-only canonical failure",
            ),
        ):
            self._write_artifacts(rollback_dir)

        self.assertEqual(rollback_manifest.read_bytes(), manifest_before)
        self.assertEqual(rollback_attempt.read_bytes(), attempt_before)
        for path in (rollback_manifest, rollback_attempt):
            self.assertFalse(stat.S_IMODE(os.lstat(path).st_mode) & stat.S_IWRITE)

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

    @staticmethod
    def _artifact_pair_snapshot(
        godot_dir: Path,
    ) -> tuple[
        tuple[bytes | None, int | None],
        tuple[bytes | None, int | None],
    ]:
        values: list[tuple[bytes | None, int | None]] = []
        for relative_path in (
            CONVERSION_ATTEMPT_RELATIVE_PATH,
            CONVERSION_MANIFEST_RELATIVE_PATH,
        ):
            path = godot_dir / relative_path
            if not path.exists():
                values.append((None, None))
                continue
            path_stat = path.stat()
            values.append(
                (
                    path.read_bytes(),
                    stat.S_IMODE(path_stat.st_mode),
                )
            )
        return cast(
            tuple[
                tuple[bytes | None, int | None],
                tuple[bytes | None, int | None],
            ],
            tuple(values),
        )

    def _assert_artifact_pair_digest_matches(
        self,
        godot_dir: Path,
    ) -> None:
        attempt_path = godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH
        manifest_path = godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        if not attempt_path.exists():
            self.assertFalse(manifest_path.exists())
            return
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        canonical = cast(
            dict[str, object],
            attempt["canonical_manifest"],
        )
        if not manifest_path.exists():
            self.assertEqual(canonical["status"], "absent")
            self.assertIsNone(canonical["sha256"])
            return
        self.assertEqual(
            canonical["sha256"],
            "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        )

    @staticmethod
    def _generation_transaction_debris(
        godot_dir: Path,
    ) -> tuple[str, ...]:
        artifact_dir = godot_dir / "gm2godot"
        allowed = {
            "conversion_attempt.json",
            "conversion_manifest.json",
            generation_module.CONVERSION_GENERATION_LOCK_NAME,
            generation_module.CONVERSION_GENERATION_POINTER_NAME,
        }
        return tuple(
            sorted(
                path.name for path in artifact_dir.iterdir() if path.name not in allowed
            )
        )

    def _run_generation_subprocess(
        self,
        godot_dir: Path,
        *,
        operation: str,
        phase: str,
        occurrence: int,
    ) -> subprocess.CompletedProcess[str]:
        script = """
import os
import sys

from src.conversion import anchored_artifacts as anchored_module
from src.conversion.conversion_manifest import (
    capture_conversion_output_snapshot,
    recover_conversion_artifacts,
    write_conversion_artifacts,
)
from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepLedger,
)

gm_path, godot_path, operation, requested_phase, occurrence_text = sys.argv[1:]
requested_occurrence = int(occurrence_text)
matches = 0

def stop_at_phase(
    current_phase: str,
    _directory_path: str,
    _name: str | None,
) -> None:
    global matches
    if current_phase != requested_phase:
        return
    matches += 1
    if matches == requested_occurrence:
        os._exit(86)

anchored_module._before_anchored_artifact_phase = stop_at_phase
if operation == "recover":
    recover_conversion_artifacts(godot_path)
elif operation == "publish":
    steps = ConversionStepLedger.from_requested(("scripts", "objects"))
    steps = steps.start("scripts").complete("scripts")
    steps = steps.start("objects").complete("objects")
    outcome = ConversionOutcome(
        state="partial",
        steps=steps,
        resources=ConversionCounts(requested=1, skipped=1),
    )
    write_conversion_artifacts(
        gm_path,
        godot_path,
        target_platform="windows",
        enabled_converters=outcome.steps.requested,
        output_snapshot=capture_conversion_output_snapshot(godot_path),
        manifest_outcome=outcome,
        attempt_outcome=outcome,
    )
elif operation == "attempt-only":
    steps = ConversionStepLedger.from_requested(("scripts", "objects"))
    steps = steps.start("scripts").complete("scripts")
    steps = steps.start("objects").fail("objects")
    outcome = ConversionOutcome(
        state="failed",
        steps=steps,
        failed_step="objects",
        failure_phase="runtime",
    )
    write_conversion_artifacts(
        gm_path,
        godot_path,
        target_platform="windows",
        enabled_converters=outcome.steps.requested,
        output_snapshot=capture_conversion_output_snapshot(godot_path),
        manifest_outcome=None,
        attempt_outcome=outcome,
    )
else:
    raise AssertionError(f"Unknown subprocess operation: {operation}")
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(PROJECT_ROOT)
            if not existing_python_path
            else str(PROJECT_ROOT) + os.pathsep + existing_python_path
        )
        return subprocess.run(
            (
                sys.executable,
                "-c",
                script,
                str(FIXTURE_ROOT),
                str(godot_dir),
                operation,
                phase,
                str(occurrence),
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=environment,
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
        manifest_before, attempt_before = self._legacy_artifact_pair_bytes(
            state="success",
        )
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
        manifest_before, attempt_before = self._legacy_artifact_pair_bytes(
            state="success",
        )
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
    def _legacy_artifact_pair_bytes(
        *,
        state: str,
    ) -> tuple[bytes, bytes]:
        manifest = (
            json.dumps(
                {
                    "format_version": 2,
                    "conversion": {"state": state},
                    "generated_files": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        attempt = (
            json.dumps(
                {
                    "format_version": 1,
                    "attempt": {"state": state},
                    "canonical_manifest": {
                        "path": "gm2godot/conversion_manifest.json",
                        "status": "updated",
                        "updated": True,
                        "current_output": "verified",
                        "sha256": "sha256:" + hashlib.sha256(manifest).hexdigest(),
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        return manifest, attempt

    @staticmethod
    def _temporary_artifact_files(godot_dir: Path) -> list[Path]:
        artifact_dir = godot_dir / "gm2godot"
        if not artifact_dir.exists():
            return []
        old_transaction_files = [
            *artifact_dir.glob(".conversion_manifest.json.*.tmp"),
            *artifact_dir.glob(".conversion_manifest.json.*.backup"),
            *artifact_dir.glob(".conversion_attempt.json.*.tmp"),
            *artifact_dir.glob(".conversion_attempt.json.*.backup"),
        ]
        generation_files = [
            path
            for path in artifact_dir.iterdir()
            if path.name
            not in {
                generation_module.CONVERSION_GENERATION_LOCK_NAME,
                generation_module.CONVERSION_GENERATION_POINTER_NAME,
            }
            and generation_module.is_conversion_generation_auxiliary(path.name)
        ]
        return sorted(
            {
                *old_transaction_files,
                *generation_files,
            }
        )


def _directory_snapshot(
    directory: Path,
) -> dict[str, tuple[int, int, int, bytes]]:
    snapshot: dict[str, tuple[int, int, int, bytes]] = {}
    for path in sorted(directory.iterdir()):
        path_stat = os.lstat(path)
        content = path.read_bytes() if stat.S_ISREG(path_stat.st_mode) else b""
        snapshot[path.name] = (
            path_stat.st_ino,
            path_stat.st_nlink,
            stat.S_IMODE(path_stat.st_mode),
            content,
        )
    return snapshot


if __name__ == "__main__":
    unittest.main()
