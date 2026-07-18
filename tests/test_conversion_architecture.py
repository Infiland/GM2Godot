# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import json
import shutil
import tempfile
import unittest

from src.conversion.conversion_plan import (
    build_conversion_plan,
    group_conversion_plan,
    validate_conversion_step_graph,
)
from src.conversion.gml_transpiler_parts.asset_lowering import (
    asset_argument_indices,
    first_argument_is_script_asset,
)
from src.conversion.gml_transpiler_parts.emitter import _emit_expression
from src.conversion.gml_transpiler_parts.expression_parser import _parse_gml_expression
from src.conversion.gml_transpiler_parts.gml_function_dispatch import (
    get_gml_function_descriptor,
    validate_gml_function_arity,
)
from src.conversion.gml_transpiler_parts.model import _Binary, _ScopeContext
from src.conversion.resource_models import (
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
        expression = _parse_gml_expression("1 + score")
        self.assertIsInstance(expression, _Binary)

        emitted, _precedence = _emit_expression(
            expression,
            {"score"},
            scope_context=_ScopeContext(),
        )
        self.assertEqual(emitted, "GMRuntime.gml_add(1, score)")

        descriptor = get_gml_function_descriptor("draw_sprite")
        self.assertIsNotNone(descriptor)
        if descriptor is None:
            self.fail("draw_sprite descriptor is required for semantic arity validation")
        self.assertIsNotNone(validate_gml_function_arity(descriptor, 1))

    def test_asset_lowering_rules_are_outside_emitter(self) -> None:
        self.assertEqual(asset_argument_indices("draw_sprite", "draw"), frozenset({0}))
        self.assertEqual(asset_argument_indices("room_goto", "room"), frozenset({0}))
        self.assertTrue(first_argument_is_script_asset("script_execute"))


if __name__ == "__main__":
    unittest.main()
