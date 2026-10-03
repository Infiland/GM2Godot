from __future__ import annotations

import os
import json
import math
import shutil
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest.mock import patch

from src.conversion.conversion_plan import (
    build_conversion_plan,
    group_conversion_plan,
    validate_conversion_step_graph,
)
from src.conversion.gml_transpiler_parts.asset_lowering import (
    asset_argument_indices,
    first_argument_is_script_asset,
)
from src.conversion.gml_transpiler_parts.expression_api import (
    emit_gml_expression,
    parse_gml_expression,
)
from src.conversion.gml_transpiler_parts.expression_models import Binary
from src.conversion.gml_transpiler_parts.gml_function_dispatch import (
    get_gml_function_descriptor,
    validate_gml_function_arity,
)
from src.conversion.gml_transpiler_parts.shared_models import ScopeContext
from src.conversion.gamemaker_json import GameMakerJsonDocument, decode_gamemaker_json
from src.conversion.json_values import JsonArray, JsonObject
from src.conversion.path_metadata import GameMakerPathMetadata, PathMetadataPoint
from src.conversion.resource_models import (
    PathModel,
    ResourceModel,
    parse_gamemaker_resource_models,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCE_MATRIX_PATH = os.path.join(
    PROJECT_ROOT,
    "tests",
    "fixtures",
    "part2",
    "projects",
    "resource_matrix",
)
MISSING_YY_PATH = os.path.join(
    PROJECT_ROOT,
    "tests",
    "fixtures",
    "part2",
    "projects",
    "missing_yy",
)


class TestConversionPlan(unittest.TestCase):
    def test_default_graph_validates(self) -> None:
        self.assertEqual(validate_conversion_step_graph(), ())

    def test_builds_dependency_order_for_enabled_steps(self) -> None:
        plan = build_conversion_plan([
            "asset_registry",
            "rooms",
            "objects",
            "scripts",
            "sprites",
            "tilesets",
        ])
        keys = [step.key for step in plan]

        self.assertLess(keys.index("sprites"), keys.index("objects"))
        self.assertLess(keys.index("scripts"), keys.index("objects"))
        self.assertLess(keys.index("objects"), keys.index("rooms"))
        self.assertLess(keys.index("tilesets"), keys.index("rooms"))
        self.assertLess(keys.index("rooms"), keys.index("asset_registry"))

    def test_dependencies_order_only_enabled_steps(self) -> None:
        self.assertEqual(
            [step.key for step in build_conversion_plan(["objects"])],
            ["objects"],
        )

    def test_groups_planned_steps(self) -> None:
        grouped = group_conversion_plan(build_conversion_plan(["project_settings", "sprites", "shaders"]))

        self.assertEqual([step.key for step in grouped["project"]], ["project_settings"])
        self.assertEqual([step.key for step in grouped["assets"]], ["sprites"])
        self.assertEqual([step.key for step in grouped["wip"]], ["shaders"])


class TestResourceModels(unittest.TestCase):
    def test_parse_resource_matrix_without_godot_output_path(self) -> None:
        self.assertFalse(os.path.exists(os.path.join(RESOURCE_MATRIX_PATH, "gm2godot")))

        models = parse_gamemaker_resource_models(RESOURCE_MATRIX_PATH)

        self.assertEqual(models.project.name, "ResourceMatrix")
        self.assertEqual(models.project.resource_count, 14)
        self.assertEqual([sprite.name for sprite in models.sprites], ["spr_checker"])
        self.assertEqual([sound.name for sound in models.sounds], ["snd_click"])
        self.assertEqual([font.name for font in models.fonts], ["fnt_ui"])
        self.assertEqual([tileset.name for tileset in models.tilesets], ["ts_ground"])
        self.assertEqual([path.name for path in models.paths], ["path_patrol"])
        self.assertEqual([sequence.name for sequence in models.sequences], ["seq_intro"])
        self.assertEqual([timeline.name for timeline in models.timelines], ["tl_intro"])
        self.assertTrue(any(script.gml_path for script in models.scripts))
        self.assertTrue(any(shader.vertex_path for shader in models.shaders))
        self.assertTrue(any(shader.fragment_path for shader in models.shaders))
        self.assertTrue(any(room.inherit_layers for room in models.rooms))
        self.assertIn("GMRInstanceLayer", {layer.resource_type for layer in models.layers})
        self.assertIn("GMRTileLayer", {layer.resource_type for layer in models.layers})
        self.assertIn("GMREffectLayer", {layer.resource_type for layer in models.layers})
        self.assertEqual(models.diagnostics, ())
        self.assertFalse(os.path.exists(os.path.join(RESOURCE_MATRIX_PATH, "gm2godot")))

    def test_missing_resource_is_structured_parse_diagnostic(self) -> None:
        models = parse_gamemaker_resource_models(MISSING_YY_PATH)
        diagnostics = {(diagnostic.code, diagnostic.resource_name) for diagnostic in models.diagnostics}

        self.assertIn(("GM2GD-RESOURCE-YY-MISSING", "spr_missing"), diagnostics)
        self.assertEqual(models.project.resource_count, 1)
        self.assertEqual(models.sprites, ())

    def test_resource_model_rejects_manifest_path_outside_project(self) -> None:
        project_dir = tempfile.mkdtemp()
        try:
            with open(
                os.path.join(project_dir, "Unsafe.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump(
                    {
                        "%Name": "Unsafe",
                        "resourceType": "GMProject",
                        "resources": [
                            {
                                "id": {
                                    "name": "scr_outside",
                                    "path": "scripts/../../../outside.yy",
                                }
                            }
                        ],
                    },
                    project_file,
                )

            models = parse_gamemaker_resource_models(project_dir)

            rejected = [
                diagnostic
                for diagnostic in models.diagnostics
                if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
            ]
            self.assertEqual(models.scripts, ())
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0].resource_name, "scr_outside")
            self.assertEqual(rejected[0].source_path, os.path.join(project_dir, "Unsafe.yyp"))
        finally:
            shutil.rmtree(project_dir)

    def test_resource_model_rejects_path_normalized_into_another_kind(self) -> None:
        project_dir = tempfile.mkdtemp()
        try:
            resource_dir = os.path.join(project_dir, "objects", "o_cross")
            os.makedirs(resource_dir)
            yyp_path = os.path.join(project_dir, "CrossKind.yyp")
            with open(yyp_path, "w", encoding="utf-8") as project_file:
                json.dump(
                    {
                        "%Name": "CrossKind",
                        "resourceType": "GMProject",
                        "resources": [
                            {
                                "id": {
                                    "name": "s_cross",
                                    "path": "sprites/../objects/o_cross/o_cross.yy",
                                }
                            }
                        ],
                    },
                    project_file,
                )
            with open(
                os.path.join(resource_dir, "o_cross.yy"),
                "w",
                encoding="utf-8",
            ) as resource_file:
                json.dump(
                    {
                        "%Name": "o_cross",
                        "resourceType": "GMObject",
                    },
                    resource_file,
                )

            models = parse_gamemaker_resource_models(project_dir)

            rejected = [
                diagnostic
                for diagnostic in models.diagnostics
                if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
            ]
            self.assertEqual(models.sprites, ())
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0].source_path, yyp_path)
            self.assertEqual(rejected[0].resource_name, "s_cross")
            self.assertEqual(rejected[0].resource_kind, "sprites")
        finally:
            shutil.rmtree(project_dir)

    def test_resource_model_rejects_script_sidecar_link_outside_project(self) -> None:
        project_dir = tempfile.mkdtemp()
        outside_dir = tempfile.mkdtemp()
        try:
            script_dir = os.path.join(project_dir, "scripts", "scr_linked")
            os.makedirs(script_dir)
            with open(
                os.path.join(project_dir, "Linked.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump(
                    {
                        "%Name": "Linked",
                        "resourceType": "GMProject",
                        "resources": [
                            {
                                "id": {
                                    "name": "scr_linked",
                                    "path": "scripts/scr_linked/scr_linked.yy",
                                },
                                "resourceType": "GMScript",
                            }
                        ],
                    },
                    project_file,
                )
            with open(
                os.path.join(script_dir, "scr_linked.yy"),
                "w",
                encoding="utf-8",
            ) as resource_file:
                json.dump(
                    {
                        "%Name": "scr_linked",
                        "resourceType": "GMScript",
                    },
                    resource_file,
                )
            outside_source = os.path.join(outside_dir, "scr_linked.gml")
            with open(outside_source, "w", encoding="utf-8") as source_file:
                source_file.write("return 42;\n")
            try:
                os.symlink(
                    outside_source,
                    os.path.join(script_dir, "scr_linked.gml"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            models = parse_gamemaker_resource_models(project_dir)

            self.assertEqual(len(models.scripts), 1)
            self.assertIsNone(models.scripts[0].gml_path)
            rejected = [
                diagnostic
                for diagnostic in models.diagnostics
                if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
            ]
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0].resource_name, "scr_linked")
            self.assertEqual(rejected[0].resource_kind, "scripts")
        finally:
            shutil.rmtree(project_dir)
            shutil.rmtree(outside_dir)


class TestGMLPipelineBoundaries(unittest.TestCase):
    def test_architecture_doc_names_phase_boundaries(self) -> None:
        doc_path = os.path.join(PROJECT_ROOT, "src", "conversion", "conversion_architecture.md")
        with open(doc_path, "r", encoding="utf-8") as doc_file:
            content = doc_file.read()

        self.assertIn("ConversionContext", content)
        self.assertIn("CONVERSION_STEPS", content)
        self.assertIn("Parser phase", content)
        self.assertIn("Semantic analysis phase", content)
        self.assertIn("GDScript emission phase", content)
        self.assertIn("asset_lowering", content)

    def test_parser_semantic_and_emitter_modules_remain_independent(self) -> None:
        expression = parse_gml_expression("1 + score")
        self.assertIsInstance(expression, Binary)

        emission = emit_gml_expression(
            expression,
            {"score"},
            scope_context=ScopeContext(),
        )
        self.assertEqual(emission.text, "GMRuntime.gml_add(1, score)")

        descriptor = get_gml_function_descriptor("draw_sprite")
        self.assertIsNotNone(descriptor)
        if descriptor is None:
            self.fail("draw_sprite descriptor is required for semantic arity validation")
        self.assertIsNotNone(validate_gml_function_arity(descriptor, 1))

    def test_asset_lowering_rules_are_outside_emitter(self) -> None:
        self.assertEqual(asset_argument_indices("draw_sprite", "draw"), frozenset({0}))
        self.assertEqual(asset_argument_indices("room_goto", "room"), frozenset({0}))
        self.assertTrue(first_argument_is_script_asset("script_execute"))


class TestPathResourceModelBoundary(unittest.TestCase):
    @staticmethod
    def _write_project(project: Path, names: tuple[str, ...] = ("path_test",)) -> Path:
        yyp_path = project / "PathBoundary.yyp"
        yyp_path.write_text(
            json.dumps({
                "%Name": "PathBoundary",
                "resourceType": "GMProject",
                "resources": [
                    {"id": {"name": name, "path": f"paths/{name}/{name}.yy"}, "resourceType": "GMPath"}
                    for name in names
                ],
            }),
            encoding="utf-8",
        )
        return yyp_path

    @staticmethod
    def _write_path(project: Path, data: JsonObject, name: str = "path_test") -> Path:
        source_path = project / "paths" / name / f"{name}.yy"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(json.dumps(data), encoding="utf-8")
        return source_path

    def test_resource_matrix_path_has_authoritative_metadata_without_outputs(self) -> None:
        documents: list[GameMakerJsonDocument] = []

        def track_decode(source: str, *, source_path: str) -> GameMakerJsonDocument:
            document = decode_gamemaker_json(source, source_path=source_path)
            documents.append(document)
            return document

        with patch("src.conversion.resource_models.decode_gamemaker_json", side_effect=track_decode):
            models = parse_gamemaker_resource_models(RESOURCE_MATRIX_PATH)

        self.assertEqual(len(documents), 1)
        self.assertEqual(len(models.paths), 1)
        model = models.paths[0]
        metadata = model.metadata
        assert metadata is not None
        self.assertEqual((model.point_count, model.closed), (3, True))
        self.assertEqual((metadata.kind, metadata.precision), (1, 4))
        self.assertEqual([(p.x, p.y, p.speed) for p in metadata.points], [(0, 0, 100), (64, 0, 100), (64, 64, 100)])
        self.assertIs(model.raw_data, metadata.raw_data)
        self.assertIs(metadata.raw_data, documents[0].value)
        self.assertEqual(model.yyp_path, "paths/path_patrol/path_patrol.yy")
        self.assertEqual(models.diagnostics, ())
        self.assertFalse((Path(RESOURCE_MATRIX_PATH) / "gm2godot").exists())

    def test_path_summary_and_subfolder_use_the_leaf_projection(self) -> None:
        raw: JsonObject = {"points": [], "closed": False, "parent": {"path": "folders/Paths/Raw.yy"}}
        metadata = GameMakerPathMetadata(
            closed=True,
            points=(PathMetadataPoint(3, 4),),
            parent_path="folders/Paths/From Model.yy",
            raw_data=raw,
        )
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            source_path = self._write_path(project, raw)
            document = GameMakerJsonDocument(str(source_path), source_path.read_text(encoding="utf-8"), raw)
            with patch("src.conversion.resource_models.decode_gamemaker_json", return_value=document), patch(
                "src.conversion.resource_models.parse_gamemaker_path_metadata", return_value=metadata,
            ) as projection:
                models = parse_gamemaker_resource_models(directory)

        model = models.paths[0]
        self.assertIs(model.metadata, metadata)
        self.assertIs(model.raw_data, raw)
        self.assertEqual((model.point_count, model.closed, model.subfolder), (1, True, "from_model"))
        projection.assert_called_once_with(raw, source_path=str(source_path))

    def test_deep_unknown_metadata_and_point_raw_objects_retain_identity(self) -> None:
        nested: JsonArray = []
        cursor = nested
        for _ in range(1600):
            child: JsonArray = []
            cursor.append(child)
            cursor = child
        point: JsonObject = {"x": 2, "y": 3, "unknown": nested}
        raw: JsonObject = {"first": 1, "points": [point], "unknown": nested, "last": 2}

        def decode_deep(source: str, *, source_path: str) -> GameMakerJsonDocument:
            with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                return decode_gamemaker_json(source, source_path=source_path)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            self._write_path(project, {})
            before = sorted(p.relative_to(project) for p in project.rglob("*"))
            with patch("src.conversion.resource_models.decode_gamemaker_json", side_effect=decode_deep):
                models = parse_gamemaker_resource_models(directory)
            self.assertEqual(sorted(p.relative_to(project) for p in project.rglob("*")), before)

        metadata = models.paths[0].metadata
        assert metadata is not None
        self.assertIs(models.paths[0].raw_data, raw)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.points[0].raw_data, point)
        self.assertIs(metadata.raw_data["unknown"], nested)
        self.assertEqual(tuple(metadata.raw_data), ("first", "points", "unknown", "last"))
        self.assertEqual(models.diagnostics, ())

    def test_aggregate_retains_huge_and_nonfinite_numbers_without_producer_conversion(self) -> None:
        huge = 10 ** 400
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            self._write_path(project, {
                "points": [{"x": huge, "y": float("inf"), "speed": float("nan")}],
                "kind": float("nan"), "precision": huge, "closed": "false",
            })
            models = parse_gamemaker_resource_models(directory)

        metadata = models.paths[0].metadata
        assert metadata is not None
        self.assertEqual((models.paths[0].point_count, models.paths[0].closed), (1, True))
        self.assertIs(type(metadata.points[0].x), int)
        self.assertEqual(metadata.points[0].x, huge)
        self.assertTrue(math.isinf(metadata.points[0].y))
        self.assertTrue(math.isnan(metadata.points[0].speed))
        self.assertTrue(math.isnan(metadata.kind))
        self.assertEqual(metadata.precision, huge)
        self.assertEqual(models.diagnostics, ())

    def test_boolean_numbers_fractional_precision_and_explicit_zero_keep_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            self._write_path(project, {
                "points": [{"x": True, "y": False, "speed": 0}, {"x": 1.25, "y": -0.0}],
                "kind": False, "precision": 4.75, "closed": [],
            })
            models = parse_gamemaker_resource_models(directory)

        metadata = models.paths[0].metadata
        assert metadata is not None
        self.assertEqual([(p.x, p.y, p.speed) for p in metadata.points], [(1, 0, 0), (1.25, -0.0, 100.0)])
        self.assertIs(type(metadata.points[0].x), int)
        self.assertIs(type(metadata.points[0].y), int)
        self.assertIs(type(metadata.points[0].speed), int)
        self.assertIs(type(metadata.points[1].x), float)
        self.assertEqual(math.copysign(1.0, metadata.points[1].y), -1.0)
        self.assertEqual((metadata.kind, metadata.precision, models.paths[0].closed), (0, 4.75, False))

    def test_malformed_known_shapes_remain_silent_and_count_object_points(self) -> None:
        cases: tuple[tuple[JsonObject, int, bool], ...] = (
            ({}, 0, False),
            ({"points": None, "closed": None}, 0, False),
            ({"points": {"x": 1}, "closed": {}}, 0, False),
            ({"points": "points", "closed": [0]}, 0, True),
            ({"points": [None, True, 4, "point", {}, {"x": "2", "speed": None}], "closed": ""}, 2, False),
        )
        for data, count, closed in cases:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self._write_project(project)
                self._write_path(project, data)
                models = parse_gamemaker_resource_models(directory)
                model = models.paths[0]
                metadata = model.metadata
                assert metadata is not None
                self.assertEqual((model.point_count, model.closed), (count, closed))
                self.assertEqual(len(metadata.points), count)
                self.assertEqual(models.diagnostics, ())
                if count:
                    self.assertEqual([(p.x, p.y, p.speed) for p in metadata.points], [(0.0, 0.0, 100.0)] * count)

    def test_nonobject_decode_and_actual_read_failures_preserve_diagnostic_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project, ("first", "valid", "last"))
            first = self._write_path(project, {}, "first")
            first.write_bytes(b"\xff")
            self._write_path(project, {"points": [{}]}, "valid")
            last = self._write_path(project, {}, "last")
            last.write_text("[]", encoding="utf-8")
            models = parse_gamemaker_resource_models(directory)
            self.assertEqual([p.name for p in models.paths], ["valid"])
            self.assertEqual(models.paths[0].order, 1)
            self.assertEqual(models.project.resource_count, 3)
            self.assertEqual(
                [(d.severity, d.code, d.message, d.source_path, d.resource_name, d.resource_kind) for d in models.diagnostics],
                [("warning", "GM2GD-RESOURCE-YY-MISSING", f"Could not parse GameMaker resource .yy: {p}", str(p), name, "paths")
                 for p, name in ((first, "first"), (last, "last"))],
            )
            for root in ("null", '"path"', "true", "false", "42", "1.25", "{broken"):
                with self.subTest(root=root):
                    first.write_text(root, encoding="utf-8")
                    updated = parse_gamemaker_resource_models(directory)
                    self.assertEqual([p.name for p in updated.paths], ["valid"])
                    self.assertEqual(updated.diagnostics, models.diagnostics)
            digit_limit = sys.get_int_max_str_digits()
            if digit_limit:
                first.write_text('{"unknown":' + "1" * (digit_limit + 1) + "}", encoding="utf-8")
                self.assertEqual(parse_gamemaker_resource_models(directory).diagnostics, models.diagnostics)

    def test_path_acquisition_keeps_its_wide_catch_and_control_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            source_path = self._write_path(project, {})
            handled: tuple[Exception, ...] = (
                OSError("read failure"), TypeError("decode type"), ValueError("decode value"),
                json.JSONDecodeError("malformed", "{", 1),
                UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
            )
            for owner in ("open", "decode_gamemaker_json"):
                for failure in handled:
                    with self.subTest(owner=owner, failure=type(failure).__name__), patch(
                        f"src.conversion.resource_models.{owner}", side_effect=failure,
                    ):
                        models = parse_gamemaker_resource_models(directory)
                        self.assertEqual(models.paths, ())
                        self.assertEqual(len(models.diagnostics), 1)
                        diagnostic = models.diagnostics[0]
                        self.assertEqual((diagnostic.code, diagnostic.source_path, diagnostic.resource_name, diagnostic.resource_kind),
                                         ("GM2GD-RESOURCE-YY-MISSING", str(source_path), "path_test", "paths"))
                for failure in (RecursionError("nesting"), KeyboardInterrupt("stop"), SystemExit(7)):
                    with self.subTest(owner=owner, failure=type(failure).__name__), patch(
                        f"src.conversion.resource_models.{owner}", side_effect=failure,
                    ), self.assertRaises(type(failure)) as raised:
                        parse_gamemaker_resource_models(directory)
                    self.assertIs(raised.exception, failure)

    def test_invalid_decoded_unknown_values_map_to_existing_missing_diagnostic(self) -> None:
        invalid: dict[str, object] = {"points": [], "unknown": object()}

        def decode_invalid(source: str, *, source_path: str) -> GameMakerJsonDocument:
            with patch("src.conversion.gamemaker_json.json.loads", return_value=invalid):
                return decode_gamemaker_json(source, source_path=source_path)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            source = self._write_path(project, {})
            with patch("src.conversion.resource_models.decode_gamemaker_json", side_effect=decode_invalid):
                models = parse_gamemaker_resource_models(directory)
            self.assertEqual(models.paths, ())
            self.assertEqual(len(models.diagnostics), 1)
            self.assertEqual(models.diagnostics[0].message, f"Could not parse GameMaker resource .yy: {source}")

    def test_projection_failures_are_outside_acquisition_catch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            self._write_path(project, {})
            for failure in (OSError("projection"), TypeError("projection"), ValueError("projection"), RecursionError("projection"),
                            KeyboardInterrupt("projection"), SystemExit(9)):
                with self.subTest(failure=type(failure).__name__), patch(
                    "src.conversion.resource_models.parse_gamemaker_path_metadata", side_effect=failure,
                ), self.assertRaises(type(failure)) as raised:
                    parse_gamemaker_resource_models(directory)
                self.assertIs(raised.exception, failure)

    def test_subfolder_case_and_backslash_order_and_relative_source_field_are_unchanged(self) -> None:
        cases = (
            ("folders/Paths.yy", ""),
            ("folders/Paths/AI.yy", "ai"),
            ("folders\\Paths\\AI.yy", ""),
            ("folders/Paths/AI\\Sub.yy", "ai/sub"),
            ("Folders/Paths/AI.yy", "paths/ai"),
            ("folders/Paths/AI.YY", "ai_yy"),
        )
        for parent_path, expected in cases:
            with self.subTest(parent_path=parent_path), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self._write_project(project)
                source = self._write_path(project, {"parent": {"path": parent_path}})
                model = parse_gamemaker_resource_models(directory).paths[0]
                assert model.metadata is not None
                self.assertEqual(model.metadata.parent_path, parent_path)
                self.assertEqual(model.subfolder, expected)
                self.assertEqual(model.yy_path, str(source))
                self.assertEqual(model.yyp_path, "paths/path_test/path_test.yy")

    def test_path_carrier_preserves_model_identity_prefix_defaults_repr_and_equality(self) -> None:
        old_fields = ("name", "kind", "resource_type", "yy_path", "yyp_path", "order", "subfolder", "raw_data", "point_count", "closed")
        self.assertEqual(tuple(f.name for f in fields(PathModel)), old_fields + ("metadata",))
        self.assertEqual(PathModel.__module__, "src.conversion.resource_models")
        self.assertEqual(PathModel.__bases__, (ResourceModel,))
        plain = PathModel("path", "paths", "GMPath", "/source/path.yy", "paths/path.yy", 3)
        data: JsonObject = {}
        metadata = GameMakerPathMetadata(raw_data=data)
        attached = PathModel("path", "paths", "GMPath", "/source/path.yy", "paths/path.yy", 3, "", data, 0, False, metadata)
        self.assertIsNone(plain.metadata)
        self.assertEqual((plain.subfolder, plain.raw_data, plain.point_count, plain.closed), ("", {}, 0, False))
        self.assertEqual(plain, attached)
        self.assertEqual(repr(plain), repr(attached))
        self.assertFalse(fields(PathModel)[-1].compare)
        self.assertFalse(fields(PathModel)[-1].repr)
        self.assertIs(attached.metadata, metadata)
        self.assertIs(attached.raw_data, metadata.raw_data)
        self.assertIsNot(plain.raw_data, PathModel("other", "paths", "GMPath", "other.yy", "other.yy", 0).raw_data)
        with self.assertRaises(FrozenInstanceError):
            setattr(plain, "closed", True)

    def test_path_source_is_acquired_once_after_containment_and_family_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._write_project(project)
            source = self._write_path(project, {"points": [{}]})
            with patch("src.conversion.resource_models.open", wraps=open) as source_open, patch(
                "src.conversion.resource_models.decode_gamemaker_json", wraps=decode_gamemaker_json,
            ) as decoder, patch(
                "src.conversion.resource_models._read_lenient_json_file", side_effect=AssertionError("generic reader used for path"),
            ):
                models = parse_gamemaker_resource_models(directory)
            self.assertEqual(models.paths[0].point_count, 1)
            source_open.assert_called_once_with(str(source), "r", encoding="utf-8")
            decoder.assert_called_once()

            yyp = self._write_project(project)
            yyp.write_text(json.dumps({
                "%Name": "PathBoundary", "resourceType": "GMProject",
                "resources": [{"id": {"name": "path_test", "path": "paths/../objects/other/other.yy"}, "resourceType": "GMPath"}],
            }), encoding="utf-8")
            with patch("src.conversion.resource_models.open", side_effect=AssertionError("rejected path was opened")):
                rejected = parse_gamemaker_resource_models(directory)
            self.assertEqual(rejected.paths, ())
            self.assertEqual(len(rejected.diagnostics), 1)
            self.assertEqual(rejected.diagnostics[0].code, "GM2GD-SOURCE-PATH-REJECTED")
            self.assertEqual(rejected.diagnostics[0].source_path, str(yyp))


if __name__ == "__main__":
    unittest.main()
