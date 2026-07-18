# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from src.conversion.asset_registry import (
    AssetRegistryConverter,
    AssetRegistryEntry,
    _ProjectResource,
)
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.scripts import (
    SCRIPT_REGISTRY_RELATIVE_PATH,
    ScriptConverter,
)
from src.conversion.script_functions import (
    modern_script_function_declarations,
    modern_script_structure,
)
from src.conversion.type_defs import JsonDict


SNAP_BUFFER_READ_YAML_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "real_world"
    / "snap"
    / "SnapBufferReadYAML.gml"
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _resource_entry(kind: str, name: str) -> dict[str, object]:
    return {
        "id": {
            "name": name,
            "path": f"{kind}/{name}/{name}.yy",
        }
    }


def _extension_yy(name: str) -> dict[str, object]:
    return {
        "%Name": name,
        "name": name,
        "files": [
            {
                "filename": f"{name}.dll",
                "functions": [
                    {
                        "name": "ads_show_rewarded",
                        "externalName": "Ads_ShowRewarded",
                        "argCount": 1,
                    }
                ],
            }
        ],
        "resourceType": "GMExtension",
    }


class ScriptSourceProbe(ScriptConverter):
    def source_gml_path(self, entry: AssetRegistryEntry) -> str | None:
        return self._source_gml_path(entry)


class TestScriptConverter(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = Path(tempfile.mkdtemp())
        self.godot_dir = Path(tempfile.mkdtemp())
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_project(self) -> None:
        _write_json(
            self.gm_dir / "ScriptTest.yyp",
            {
                "resources": [
                    _resource_entry("scripts", "scr_add"),
                    _resource_entry("scripts", "scr_modern"),
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        for script_name in ("scr_add", "scr_modern"):
            _write_json(
                self.gm_dir / "scripts" / script_name / f"{script_name}.yy",
                {
                    "%Name": script_name,
                    "name": script_name,
                    "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                    "resourceType": "GMScript",
                },
            )
        _write_text(
            self.gm_dir / "scripts" / "scr_add" / "scr_add.gml",
            "return argument0 + argument1;",
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "function scr_modern(a, b = 4) { return a + b; }",
        )

    def _converter(
        self,
        macro_configuration: str | None = None,
        *,
        diagnostics: DiagnosticCollector | None = None,
    ) -> ScriptConverter:
        return ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
            diagnostics=diagnostics,
        )

    def _source_probe(
        self,
        diagnostics: DiagnosticCollector,
    ) -> ScriptSourceProbe:
        return ScriptSourceProbe(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _script_entry(name: str, source_path: str) -> AssetRegistryEntry:
        return AssetRegistryEntry(
            id=1,
            name=name,
            kind="scripts",
            asset_type="script",
            type_name="Script",
            source_path=source_path,
            godot_path="res://scripts/probe.gd",
            legacy_id=source_path,
        )

    def test_converts_scripts_and_generated_registry(self) -> None:
        self._write_project()

        registry_path = self._converter().convert_all()

        self.assertEqual(registry_path, str(self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH))
        legacy_script = (self.godot_dir / "scripts" / "game" / "scr_add.gd").read_text(encoding="utf-8")
        modern_script = (self.godot_dir / "scripts" / "game" / "scr_modern.gd").read_text(encoding="utf-8")
        legacy_source_map = json.loads(
            (self.godot_dir / "scripts" / "game" / "scr_add.gd.gmlmap.json").read_text(encoding="utf-8")
        )
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8")

        self.assertIn("func _gm_script_call():", legacy_script)
        self.assertIn("func _gm_script_call_scoped(_gml_script_self = null, _gml_script_other = null):", legacy_script)
        self.assertIn("# GM2Godot source:", legacy_script)
        self.assertIn("GMRuntime.gml_argument(0)", legacy_script)
        self.assertIn("GMRuntime.gml_argument(1)", legacy_script)
        self.assertEqual(legacy_source_map["event"], "script:scr_add")
        self.assertTrue(legacy_source_map["entries"])
        self.assertEqual(
            legacy_source_map["entries"][0]["source_path"],
            str(self.gm_dir / "scripts" / "scr_add" / "scr_add.gml"),
        )
        self.assertEqual(legacy_source_map["entries"][0]["source_line"], 1)
        self.assertIn("func gm2godot_callable():", modern_script)
        self.assertIn("func gm2godot_scoped_callable():", modern_script)
        self.assertIn("func _gm_script_call(a = null, b = null):", modern_script)
        self.assertIn(
            "func _gm_script_call_scoped(_gml_script_self = null, _gml_script_other = null, a = null, b = null):",
            modern_script,
        )
        self.assertIn("if b == null or GMRuntime.is_undefined(b): b = 4", modern_script)
        self.assertIn('preload("res://scripts/game/scr_add.gd").new().gm2godot_callable()', registry)
        self.assertIn('preload("res://scripts/game/scr_add.gd").new().gm2godot_scoped_callable()', registry)
        self.assertIn('"legacy_arguments": true', registry)
        self.assertIn('preload("res://scripts/game/scr_modern.gd").new().gm2godot_callable()', registry)
        self.assertIn('preload("res://scripts/game/scr_modern.gd").new().gm2godot_scoped_callable()', registry)
        self.assertIn('"legacy_arguments": false', registry)

    def test_resource_outcome_counts_safe_and_blocked_scripts(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "return @;",
        )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()
        result = converter.conversion_step_result()

        self.assertEqual(
            registry_path,
            str(self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH),
        )
        self.assertTrue(
            (self.godot_dir / "scripts" / "game" / "scr_add.gd").is_file()
        )
        self.assertFalse(
            (self.godot_dir / "scripts" / "game" / "scr_modern.gd").exists()
        )
        self.assertEqual(result.resources.requested, 2)
        self.assertEqual(result.resources.executed, 2)
        self.assertEqual(result.resources.completed, 1)
        self.assertEqual(result.resources.skipped, 1)
        self.assertEqual(result.resources.failed, 0)
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-GML-TRANSPILE"
                and diagnostic.resource == "scr_modern"
                for diagnostic in diagnostics.diagnostics()
            )
        )

    def test_missing_only_declared_script_is_requested_and_skipped(self) -> None:
        _write_json(
            self.gm_dir / "ScriptTest.yyp",
            {
                "resources": [_resource_entry("scripts", "scr_missing")],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        converter = self._converter()

        self.assertIsNone(converter.convert_all())

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            any(
                "Skipping missing GameMaker asset scr_missing" in log
                for log in self.logs
            )
        )
        self.assertFalse(
            (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).exists()
        )

    def test_safe_and_missing_declared_scripts_have_strict_counts(self) -> None:
        self._write_project()
        shutil.rmtree(self.gm_dir / "scripts" / "scr_modern")
        converter = self._converter()

        registry_path = converter.convert_all()

        self.assertEqual(
            registry_path,
            str(self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH),
        )
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
            (self.godot_dir / "scripts" / "game" / "scr_add.gd").is_file()
        )
        self.assertFalse(
            (self.godot_dir / "scripts" / "game" / "scr_modern.gd").exists()
        )
        assert registry_path is not None
        registry = Path(registry_path).read_text(encoding="utf-8")
        self.assertIn('"name": "scr_add"', registry)
        self.assertNotIn('"name": "scr_modern"', registry)

    def test_cancellation_during_planning_requests_every_script(self) -> None:
        self._write_project()
        running = True
        original_metadata = AssetRegistryConverter._metadata

        def metadata_then_cancel(
            registry_converter: AssetRegistryConverter,
            resource: _ProjectResource,
            room_order_indices: dict[str, int] | None = None,
            *,
            timeline_script_stem: str | None = None,
            godot_path: str = "",
        ) -> JsonDict:
            nonlocal running
            result = original_metadata(
                registry_converter,
                resource,
                room_order_indices,
                timeline_script_stem=timeline_script_stem,
                godot_path=godot_path,
            )
            running = False
            return result

        converter = ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: running,
        )

        with patch.object(
            AssetRegistryConverter,
            "_metadata",
            new=metadata_then_cancel,
        ):
            self.assertIsNone(converter.convert_all())

        result = converter.conversion_step_result()
        self.assertTrue(result.cancelled)
        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=2,
                skipped=2,
            ),
        )
        self.assertFalse(
            (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).exists()
        )

    def test_cancellation_after_script_write_defers_completion(self) -> None:
        self._write_project()
        running = True
        converter = ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: running,
        )
        original_write_script = converter._write_script

        def write_then_cancel(*args: Any, **kwargs: Any) -> Any:
            nonlocal running
            result = original_write_script(*args, **kwargs)
            running = False
            return result

        with patch.object(
            converter,
            "_write_script",
            side_effect=write_then_cancel,
        ):
            self.assertIsNone(converter.convert_all())

        self.assertTrue(
            (self.godot_dir / "scripts" / "game" / "scr_add.gd").is_file()
        )
        self.assertFalse(
            (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).exists()
        )
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

    def test_later_script_exception_fails_prior_unpublished_script(self) -> None:
        self._write_project()
        converter = self._converter()
        original_write_script = converter._write_script

        def write_or_raise(
            entry: AssetRegistryEntry,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            if entry.name == "scr_modern":
                raise RuntimeError("script worker failed")
            return original_write_script(entry, *args, **kwargs)

        with patch.object(
            converter,
            "_write_script",
            side_effect=write_or_raise,
        ):
            with self.assertRaisesRegex(RuntimeError, "script worker failed"):
                converter.convert_all()

        self.assertTrue(
            (self.godot_dir / "scripts" / "game" / "scr_add.gd").is_file()
        )
        self.assertFalse(
            (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).exists()
        )
        with self.assertRaises(ValueError):
            converter.conversion_step_result(finalize_unfinished_as=None)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as="failed",
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                failed=2,
            ),
        )

    def test_declared_manifest_script_path_owns_selected_sidecar(self) -> None:
        _write_json(
            self.gm_dir / "ScriptTest.yyp",
            {
                "resources": [
                    {
                        "id": {
                            "name": "scr_declared",
                            "path": "scripts/nested/source/custom_script.yy",
                        }
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        script_metadata: dict[str, object] = {
            "%Name": "scr_declared",
            "name": "scr_declared",
            "parent": {
                "name": "Declared",
                "path": "folders/Scripts/Declared.yy",
            },
            "resourceType": "GMScript",
        }
        _write_json(
            self.gm_dir / "scripts" / "nested" / "source" / "custom_script.yy",
            script_metadata,
        )
        _write_text(
            self.gm_dir / "scripts" / "nested" / "source" / "scr_declared.gml",
            "function scr_declared() { return 41; }",
        )
        _write_json(
            self.gm_dir / "scripts" / "scr_declared" / "scr_declared.yy",
            script_metadata,
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_declared" / "scr_declared.gml",
            "function scr_declared() { return 99; }",
        )

        self._converter().convert_all()

        generated = (
            self.godot_dir / "scripts" / "declared" / "scr_declared.gd"
        ).read_text(encoding="utf-8")
        self.assertIn("return 41", generated)
        self.assertNotIn("return 99", generated)
        self.assertIn("func gm2godot_callable():", generated)

    def test_unusual_script_name_cannot_move_preferred_source_from_owner(self) -> None:
        owner_path = self.gm_dir / "scripts" / "owner" / "custom.yy"
        _write_json(owner_path, {"resourceType": "GMScript"})
        escaped_source = self.gm_dir / "scripts" / "escaped.gml"
        fallback_source = self.gm_dir / "scripts" / "owner" / "safe.gml"
        _write_text(escaped_source, "return 99;")
        _write_text(fallback_source, "return 7;")
        diagnostics = DiagnosticCollector()

        selected = self._source_probe(diagnostics).source_gml_path(
            self._script_entry("../escaped", "scripts/owner/custom.yy")
        )

        self.assertEqual(selected, str(fallback_source))
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "scripts/owner/custom.yy")
        self.assertEqual(rejected[0].manifest_entry, "preferred script source")

    def test_script_name_aliases_do_not_select_derived_source(self) -> None:
        aliases = (
            ("slash", "bridge/../a_alias", "a_alias.gml"),
            ("backslash", r"bridge\..\a_alias", "a_alias.gml"),
            ("dot", ".", "..gml"),
            ("dotdot", "..", "...gml"),
        )
        for label, script_name, aliased_filename in aliases:
            with self.subTest(alias=label):
                owner_relative = f"scripts/owner_{label}/custom.yy"
                owner_directory = self.gm_dir / "scripts" / f"owner_{label}"
                fallback_source = owner_directory / "z_fallback.gml"
                _write_json(
                    owner_directory / "custom.yy",
                    {"resourceType": "GMScript"},
                )
                _write_text(fallback_source, "return 7;")
                _write_text(owner_directory / aliased_filename, "return 99;")
                diagnostics = DiagnosticCollector()

                selected = self._source_probe(diagnostics).source_gml_path(
                    self._script_entry(script_name, owner_relative)
                )

                self.assertEqual(selected, str(fallback_source))
                rejected = [
                    diagnostic
                    for diagnostic in diagnostics.diagnostics()
                    if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
                ]
                self.assertEqual(len(rejected), 1, rejected)
                self.assertEqual(rejected[0].source_path, owner_relative)
                self.assertEqual(
                    rejected[0].manifest_entry,
                    "preferred script source",
                )

    def test_safe_script_name_still_prefers_matching_source(self) -> None:
        owner_directory = self.gm_dir / "scripts" / "owner_safe"
        preferred_source = owner_directory / "scr_safe.gml"
        _write_json(
            owner_directory / "custom.yy",
            {"resourceType": "GMScript"},
        )
        _write_text(owner_directory / "a_fallback.gml", "return 7;")
        _write_text(preferred_source, "return 99;")
        diagnostics = DiagnosticCollector()

        selected = self._source_probe(diagnostics).source_gml_path(
            self._script_entry("scr_safe", "scripts/owner_safe/custom.yy")
        )

        self.assertEqual(selected, str(preferred_source))
        self.assertFalse(
            any(
                diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
                for diagnostic in diagnostics.diagnostics()
            )
        )

    def test_fallback_discovery_skips_source_symlink_outside_project(self) -> None:
        owner_path = self.gm_dir / "scripts" / "owner" / "custom.yy"
        fallback_source = self.gm_dir / "scripts" / "owner" / "b_valid.gml"
        _write_json(owner_path, {"resourceType": "GMScript"})
        _write_text(fallback_source, "return 7;")
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_source = Path(outside_dir) / "a_external.gml"
            outside_source.write_text("return 99;", encoding="utf-8")
            linked_source = self.gm_dir / "scripts" / "owner" / "a_external.gml"
            try:
                os.symlink(outside_source, linked_source)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            selected = self._source_probe(diagnostics).source_gml_path(
                self._script_entry("missing", "scripts/owner/custom.yy")
            )

        self.assertEqual(selected, str(fallback_source))
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "scripts/owner/custom.yy")
        self.assertEqual(rejected[0].manifest_entry, "discovered script source")

    def test_preferred_sidecar_symlink_outside_project_uses_valid_fallback(self) -> None:
        owner_path = self.gm_dir / "scripts" / "owner" / "custom.yy"
        fallback_source = self.gm_dir / "scripts" / "owner" / "z_valid.gml"
        _write_json(owner_path, {"resourceType": "GMScript"})
        _write_text(fallback_source, "return 7;")
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_source = Path(outside_dir) / "outside.gml"
            outside_source.write_text("return 99;", encoding="utf-8")
            preferred_source = self.gm_dir / "scripts" / "owner" / "scr_owner.gml"
            try:
                os.symlink(outside_source, preferred_source)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            selected = self._source_probe(diagnostics).source_gml_path(
                self._script_entry("scr_owner", "scripts/owner/custom.yy")
            )

        self.assertEqual(selected, str(fallback_source))
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "scripts/owner/custom.yy")
        self.assertEqual(rejected[0].manifest_entry, "preferred script source")

    def test_script_yy_symlink_outside_project_is_not_used_as_an_owner(self) -> None:
        script_directory = self.gm_dir / "scripts" / "owner"
        fallback_source = script_directory / "safe.gml"
        _write_text(fallback_source, "return 7;")
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_yy = Path(outside_dir) / "custom.yy"
            _write_json(outside_yy, {"resourceType": "GMScript"})
            try:
                os.symlink(outside_yy, script_directory / "custom.yy")
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            selected = self._source_probe(diagnostics).source_gml_path(
                self._script_entry("safe", "scripts/owner/custom.yy")
            )

        self.assertIsNone(selected)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].manifest_entry, "script .yy")

    def test_script_body_uses_caller_instance_scope(self) -> None:
        self._write_project()
        project_path = self.gm_dir / "ScriptTest.yyp"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        resources = cast(list[object], project["resources"])
        resources.append(_resource_entry("scripts", "scr_move"))
        _write_json(project_path, project)
        _write_json(
            self.gm_dir / "scripts" / "scr_move" / "scr_move.yy",
            {
                "%Name": "scr_move",
                "name": "scr_move",
                "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                "resourceType": "GMScript",
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_move" / "scr_move.gml",
            "function scr_move(amount) { x += amount; return x; }",
        )

        self._converter().convert_all()

        script = (self.godot_dir / "scripts" / "game" / "scr_move.gd").read_text(encoding="utf-8")
        self.assertIn('GMRuntime.gml_variable_instance_get(_gml_script_self, "x")', script)
        self.assertIn('GMRuntime.gml_variable_instance_set(_gml_script_self, "x"', script)
        self.assertNotIn("position.x", script)

    def test_modern_script_body_initializes_and_uses_static_variables(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "function scr_modern(delta)\n"
            "{\n"
            "    static total = 10;\n"
            "    static callback = function(value)\n"
            "    {\n"
            "        return value + 1;\n"
            "    };\n"
            "    total += delta;\n"
            "    return callback;\n"
            "}\n",
        )
        diagnostics = DiagnosticCollector()

        ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()

        self.assertEqual(diagnostics.diagnostics(), ())
        script = (self.godot_dir / "scripts" / "game" / "scr_modern.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'GMRuntime.gml_static_scope("scr_modern.scr_modern:<anonymous>:0:',
            script,
        )
        self.assertIn("GMRuntime.gml_static_initialize(_gml_static_scope_", script)
        self.assertIn("func(_gml_method_self = null, value = null):", script)
        self.assertIn("GMRuntime.gml_struct_set(_gml_static_scope_", script)
        self.assertIn("return GMRuntime.gml_struct_get(_gml_static_scope_", script)

    def test_modern_script_verbatim_default_ignores_literal_delimiters(self) -> None:
        self._write_project()
        source = (
            "function scr_modern(\n"
            "    value = @'line 1,) } // literal\n"
            "line 2 with \"quotes\"',\n"
            "    other = 2\n"
            ")\n"
            "{\n"
            "    return value;\n"
            "}\n"
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            source,
        )

        declarations = modern_script_function_declarations(source)
        self.assertIsNotNone(declarations)
        assert declarations is not None
        self.assertEqual(
            declarations[0].parameters[0].default,
            "@'line 1,) } // literal\nline 2 with \"quotes\"'",
        )
        self.assertEqual(declarations[0].parameters[1].name, "other")

        self._converter().convert_all()

        script = (
            self.godot_dir / "scripts" / "game" / "scr_modern.gd"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'value = "line 1,) } // literal\\nline 2 with \\"quotes\\""',
            script,
        )

    def test_discovers_constructor_and_explicit_top_level_initialization(self) -> None:
        structure = modern_script_structure(
            "function Adding() constructor {\n"
            "    static operate = function(a, b) { return a + b; }\n"
            "}\n"
            "new Adding();\n"
        )

        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertEqual(len(structure.declarations), 1)
        self.assertEqual(structure.declarations[0].name, "Adding")
        self.assertTrue(structure.declarations[0].is_constructor)
        self.assertEqual(len(structure.top_level_statements), 1)
        self.assertEqual(
            structure.top_level_statements[0].constructor_name,
            "Adding",
        )

    def test_discovers_modern_functions_around_top_level_enum(self) -> None:
        declarations = modern_script_function_declarations(
            "enum TokenKind\n"
            "{\n"
            "    STRING,\n"
            "    COLLECTION = 4,\n"
            "}\n"
            "function decode(value)\n"
            "{\n"
            "    return value == TokenKind.STRING;\n"
            "}\n"
            "enum ResultKind { OK, ERROR }\n"
            "function Builder() constructor\n"
            "{\n"
            "    static read = function() { return ResultKind.OK; }\n"
            "}\n"
        )

        self.assertIsNotNone(declarations)
        assert declarations is not None
        self.assertEqual(
            tuple(declaration.name for declaration in declarations),
            ("decode", "Builder"),
        )
        self.assertFalse(declarations[0].is_constructor)
        self.assertTrue(declarations[1].is_constructor)

    def test_discovers_modern_functions_around_top_level_macros(self) -> None:
        declarations = modern_script_function_declarations(
            "function decode() { return TOKEN_SYMBOL; }\n"
            "#macro TOKEN_SYMBOL 0\n"
            "#macro Android:TOKEN_LITERAL 1\n"
            "#macro COMBINED (TOKEN_SYMBOL + \\\n"
            "    TOKEN_LITERAL)\n"
            "function environment() { return COMBINED; }\n"
        )

        self.assertIsNotNone(declarations)
        assert declarations is not None
        self.assertEqual(
            tuple(declaration.name for declaration in declarations),
            ("decode", "environment"),
        )

    def test_discovers_only_active_conditional_modern_functions_with_exact_offsets(self) -> None:
        source = (
            "#define FEATURE_ENABLED\r\n"
            "#if defined(FEATURE_ENABLED) && Android\r\n"
            "function android_impl() { return 11; }\r\n"
            "#else\r\n"
            "function desktop_impl() { return 22; }\r\n"
            "#endif\r\n"
            "function Builder() constructor {}\r\n"
            "#if Android\r\n"
            "new Builder();\r\n"
            "#endif\r\n"
        )

        android_structure = modern_script_structure(
            source,
            macro_configuration="Android",
        )
        desktop_structure = modern_script_structure(
            source,
            macro_configuration="Windows",
        )

        self.assertIsNotNone(android_structure)
        self.assertIsNotNone(desktop_structure)
        assert android_structure is not None
        assert desktop_structure is not None
        self.assertEqual(
            tuple(declaration.name for declaration in android_structure.declarations),
            ("android_impl", "Builder"),
        )
        self.assertEqual(
            tuple(declaration.name for declaration in desktop_structure.declarations),
            ("desktop_impl", "Builder"),
        )
        self.assertEqual(len(android_structure.top_level_statements), 1)
        self.assertEqual(desktop_structure.top_level_statements, ())
        initializer = android_structure.top_level_statements[0]
        self.assertEqual(initializer.source, "new Builder();")
        self.assertEqual(source[initializer.start:initializer.end], initializer.source)

    def test_discovers_named_constructor_after_global_anonymous_constructor(self) -> None:
        structure = modern_script_structure(
            "global.testAnonymousGlobalConstructor = function() constructor {}\n"
            "function TestGlobalConstructor() constructor\n"
            "{\n"
            "    variable = 3.141;\n"
            "}\n"
        )

        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertEqual(len(structure.declarations), 1)
        self.assertEqual(structure.declarations[0].name, "TestGlobalConstructor")
        self.assertTrue(structure.declarations[0].is_constructor)
        self.assertEqual(
            tuple(
                statement.source
                for statement in structure.top_level_statements
            ),
            ("global.testAnonymousGlobalConstructor = function() constructor {}",),
        )

    def test_preserves_supported_top_level_statement_order_and_multiplicity(self) -> None:
        structure = modern_script_structure(
            "function Probe() constructor {}\n"
            "global.First = function() constructor {};\n"
            "new Probe();\n"
            "global.Child = function(value): global.First(value) constructor {\n"
            "    child_value = value;\n"
            "};\n"
            "new Probe();\n"
            "new Probe();\n"
        )

        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertEqual(
            tuple(statement.kind for statement in structure.top_level_statements),
            (
                "global_constructor_assignment",
                "constructor_call",
                "global_constructor_assignment",
                "constructor_call",
                "constructor_call",
            ),
        )
        self.assertEqual(
            tuple(
                statement.constructor_name
                for statement in structure.top_level_statements
                if statement.kind == "constructor_call"
            ),
            ("Probe", "Probe", "Probe"),
        )
        self.assertIn(
            ": global.First(value) constructor",
            structure.top_level_statements[2].source,
        )

    def test_discovers_standalone_global_anonymous_constructor_script(self) -> None:
        structure = modern_script_structure(
            "global.Parent = function(value) constructor { parent_value = value; };\n"
            "global.Child = function(value): global.Parent(value) constructor {\n"
            "    child_value = value + 1;\n"
            "};\n"
        )

        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertEqual(structure.declarations, ())
        self.assertEqual(len(structure.top_level_statements), 2)
        self.assertTrue(
            all(
                statement.kind == "global_constructor_assignment"
                for statement in structure.top_level_statements
            )
        )

    def test_converts_global_anonymous_constructor_initializer(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "global.testAnonymousGlobalConstructor = function() constructor {}\n"
            "function scr_modern() constructor\n"
            "{\n"
            "    variable = 3.141;\n"
            "}\n",
        )
        diagnostics = DiagnosticCollector()

        ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()

        self.assertEqual(diagnostics.diagnostics(), ())
        script = (
            self.godot_dir / "scripts" / "game" / "scr_modern.gd"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'GMRuntime.gml_selector_set(GMRuntime.gml_global_scope(), '
            '"testAnonymousGlobalConstructor", GMRuntime.gml_constructor(',
            script,
        )
        self.assertIn("func _gm_script_call(_gml_constructor_self = null):", script)
        self.assertIn(
            'GMRuntime.gml_variable_instance_set(_gml_constructor_self, "variable", 3.141)',
            script,
        )

    def test_converts_standalone_derived_global_constructor_initializer(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "global.Parent = function(value) constructor { parent_value = value; };\n"
            "global.Child = function(value): global.Parent(value) constructor {\n"
            "    child_value = value + 1;\n"
            "};\n",
        )
        diagnostics = DiagnosticCollector()

        ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()

        self.assertEqual(diagnostics.diagnostics(), ())
        script = (
            self.godot_dir / "scripts" / "game" / "scr_modern.gd"
        ).read_text(encoding="utf-8")
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(
            encoding="utf-8"
        )
        self.assertIn("func gm2godot_initialize_top_level():", script)
        self.assertIn(
            "GMRuntime.gml_constructor_inherit(_gml_constructor_self, "
            'GMRuntime.gml_selector_get(GMRuntime.gml_global_scope(), "Parent"), '
            "[value])",
            script,
        )
        self.assertIn(
            '"initializer": Callable(_gm_initializer_owner_1, '
            '"gm2godot_initialize_top_level")',
            registry,
        )

    def test_emits_top_level_initializers_in_source_order_without_deduplication(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "function scr_modern() constructor {}\n"
            "/* keep source-map line offsets\n"
            "   across stripped comments */\n"
            "global.First = function() constructor {};\n"
            "new scr_modern();\n"
            "global.Second = function() constructor {};\n"
            "new scr_modern();\n"
            "new scr_modern();\n",
        )

        self._converter().convert_all()

        script = (
            self.godot_dir / "scripts" / "game" / "scr_modern.gd"
        ).read_text(encoding="utf-8")
        source_map = cast(
            dict[str, object],
            json.loads(
                (
                    self.godot_dir
                    / "scripts"
                    / "game"
                    / "scr_modern.gd.gmlmap.json"
                ).read_text(encoding="utf-8")
            ),
        )
        first_assignment = script.index('"First"')
        first_new = script.index(
            'GMRuntime.gml_new(GMRuntime.gml_asset_get_index("scr_modern"), [])'
        )
        second_assignment = script.index('"Second"')
        self.assertLess(first_assignment, first_new)
        self.assertLess(first_new, second_assignment)
        self.assertEqual(
            script.count(
                'GMRuntime.gml_new(GMRuntime.gml_asset_get_index("scr_modern"), [])'
            ),
            3,
        )
        initializer_entries = [
            entry
            for entry in cast(list[dict[str, object]], source_map["entries"])
            if entry["event"] == "script:scr_modern:top-level"
        ]
        self.assertTrue(initializer_entries)
        first_initializer_entry = initializer_entries[0]
        self.assertEqual(first_initializer_entry["source_line"], 4)
        self.assertIn(
            "global.First",
            cast(str, first_initializer_entry["source_text"]),
        )
        self.assertEqual(
            script.splitlines()[
                cast(int, first_initializer_entry["generated_line"]) - 1
            ].strip(),
            first_initializer_entry["generated_text"],
        )

    def test_discovers_all_functions_in_snap_buffer_read_yaml_fixture(self) -> None:
        declarations = modern_script_function_declarations(
            SNAP_BUFFER_READ_YAML_FIXTURE.read_text(encoding="utf-8")
        )

        self.assertIsNotNone(declarations)
        assert declarations is not None
        self.assertEqual(
            tuple(declaration.name for declaration in declarations),
            (
                "SnapBufferReadYAML",
                "__SnapFromYAMLBufferTokenizer",
                "__SnapFromYAMLBufferBuilder",
            ),
        )
        self.assertEqual(
            tuple(declaration.is_constructor for declaration in declarations),
            (False, True, True),
        )

    def test_converts_full_snap_buffer_read_yaml_fixture(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            SNAP_BUFFER_READ_YAML_FIXTURE.read_text(encoding="utf-8"),
        )
        diagnostics = DiagnosticCollector()

        ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()

        self.assertTrue(
            all(
                diagnostic.code == "GM2GD-GML-CASE-COLLISION"
                for diagnostic in diagnostics.diagnostics()
            )
        )
        self.assertIn("Converted script: scr_modern", self.logs)
        script = (
            self.godot_dir / "scripts" / "game" / "scr_modern.gd"
        ).read_text(encoding="utf-8")
        self.assertIn("func _gm_script_call_SnapBufferReadYAML(", script)
        self.assertIn("func _gm_script_call___SnapFromYAMLBufferTokenizer(", script)
        self.assertIn("func _gm_script_call___SnapFromYAMLBufferBuilder(", script)
        self.assertEqual(
            script.count("GMRuntime.gml_array_set(_field_order_array, _gm2gd_mutation_value_"),
            2,
        )

    def test_converts_constructor_script_static_methods_and_registry_identity(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "function scr_modern() constructor {\n"
            "    static operate = function(a, b) { return a + b; }\n"
            "    static invert = function(value) { return -value; }\n"
            "}\n"
            "new scr_modern();\n",
        )
        diagnostics = DiagnosticCollector()

        ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()

        self.assertEqual(diagnostics.diagnostics(), ())
        script = (self.godot_dir / "scripts" / "game" / "scr_modern.gd").read_text(
            encoding="utf-8"
        )
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(
            encoding="utf-8"
        )
        self.assertIn("var _gm_constructor_scr_modern = GMRuntime.gml_constructor(", script)
        self.assertIn("func _gm_script_call(_gml_constructor_self = null):", script)
        self.assertIn('["operate", func(): return GMRuntime.gml_method(', script)
        self.assertIn('["invert", func(): return GMRuntime.gml_method(', script)
        self.assertIn("GMRuntime.gml_static_bind(", script)
        self.assertIn(
            'GMRuntime.gml_new(GMRuntime.gml_asset_get_index("scr_modern"), [])',
            script,
        )
        self.assertIn("func gm2godot_initialize_top_level():", script)
        self.assertIn("var _gm_constructor_1 =", registry)
        self.assertIn('"callable": _gm_constructor_1', registry)
        self.assertIn('"scoped_callable": _gm_constructor_1', registry)

    def test_converts_scripts_with_mapped_extension_calls(self) -> None:
        self._write_project()
        project_path = self.gm_dir / "ScriptTest.yyp"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        resources = cast(list[object], project["resources"])
        resources.append(_resource_entry("extensions", "AdSDK"))
        _write_json(project_path, project)
        _write_json(self.gm_dir / "extensions" / "AdSDK" / "AdSDK.yy", _extension_yy("AdSDK"))
        _write_json(
            self.gm_dir / "gm2godot_extension_functions.json",
            {
                "functions": {
                    "ads_show_rewarded": {
                        "target": "AdBridge.show_rewarded",
                        "min_args": 1,
                        "max_args": 1,
                    }
                }
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_add" / "scr_add.gml",
            'ads_show_rewarded("zone_1"); return 1;',
        )

        self._converter().convert_all()

        legacy_script = (self.godot_dir / "scripts" / "game" / "scr_add.gd").read_text(encoding="utf-8")
        self.assertIn('AdBridge.show_rewarded("zone_1")', legacy_script)

    def test_applies_macro_configuration_to_script_sources(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "#if Android\n"
            "function scr_modern() { return 11; }\n"
            "#else\n"
            "function scr_modern() { return 22; }\n"
            "#endif\n",
        )

        self._converter(macro_configuration="Android").convert_all()

        modern_script = (self.godot_dir / "scripts" / "game" / "scr_modern.gd").read_text(encoding="utf-8")
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(
            encoding="utf-8"
        )
        self.assertIn("return 11", modern_script)
        self.assertNotIn("return 22", modern_script)
        self.assertIn("func gm2godot_callable():", modern_script)
        self.assertNotIn("GMRuntime.gml_method(_gml_script_self, func scr_modern", modern_script)
        self.assertIn('"legacy_arguments": false', registry)

    def test_project_macros_expand_across_scripts_with_configuration_precedence(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_add" / "scr_add.gml",
            "#macro Android:BASE 7\n"
            "#macro BASE 4\n"
            "#macro DOUBLE (BASE * 2)\n",
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "function scr_modern(value = BASE) { return DOUBLE + value; }",
        )

        self._converter(macro_configuration="Android").convert_all()

        modern_script = (
            self.godot_dir / "scripts" / "game" / "scr_modern.gd"
        ).read_text(encoding="utf-8")
        self.assertIn("value = 7", modern_script)
        self.assertIn(
            "return GMRuntime.gml_add((GMRuntime.gml_mul(7, 2)), value)",
            modern_script,
        )
        self.assertNotIn('"BASE"', modern_script)
        self.assertNotIn('"DOUBLE"', modern_script)

    def test_converts_multi_function_script_assets_and_declared_registry_names(self) -> None:
        self._write_project()
        project_path = self.gm_dir / "ScriptTest.yyp"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        resources = cast(list[object], project["resources"])
        resources.append(_resource_entry("scripts", "ending"))
        _write_json(project_path, project)
        _write_json(
            self.gm_dir / "scripts" / "ending" / "ending.yy",
            {
                "%Name": "ending",
                "name": "ending",
                "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                "resourceType": "GMScript",
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "ending" / "ending.gml",
            "function loadending() {\n"
            "    for (var i = 1; i <= 7; i++) { global.endingnum[i] = i; }\n"
            "}\n"
            "function saveending() {\n"
            "    for (var i = 1; i <= 7; i++) { loadending(); }\n"
            "}\n",
        )
        diagnostics = DiagnosticCollector()

        registry_path = ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()

        self.assertEqual(registry_path, str(self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH))
        self.assertEqual(diagnostics.diagnostics(), ())
        ending_script = (self.godot_dir / "scripts" / "game" / "ending.gd").read_text(encoding="utf-8")
        self.assertIn("func _gm_script_call_loadending():", ending_script)
        self.assertIn(
            "func _gm_script_call_scoped_loadending(_gml_script_self = null, _gml_script_other = null):",
            ending_script,
        )
        self.assertIn("func _gm_script_call_saveending():", ending_script)
        self.assertIn(
            "GMRuntime.gml_script_call(GMRuntime.gml_asset_get_index(\"loadending\"), [], "
            "_gml_script_self, _gml_script_other)",
            ending_script,
        )
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8")
        self.assertIn('"name": "scr_add"', registry)
        self.assertIn('"name": "scr_modern"', registry)
        self.assertIn('"name": "loadending"', registry)
        self.assertIn('"name": "saveending"', registry)
        self.assertNotIn('"name": "ending"', registry)
        self.assertIn(
            'preload("res://scripts/game/ending.gd").new().gm2godot_callable_loadending()',
            registry,
        )
        self.assertIn(
            'preload("res://scripts/game/ending.gd").new().gm2godot_scoped_callable_saveending()',
            registry,
        )


if __name__ == "__main__":
    unittest.main()
