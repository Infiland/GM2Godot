# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
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
