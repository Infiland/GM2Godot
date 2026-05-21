from __future__ import annotations

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_runtime import (
    duplicate_runtime_symbols,
    runtime_api_index,
    runtime_segment_names,
    runtime_symbol_index,
    validate_runtime_segments,
)
from src.conversion.gml_runtime_parts.manifest import (
    RUNTIME_SEGMENT_MODULE_PREFIX,
    RuntimeSegmentDefinition,
    iter_runtime_segment_symbols,
    runtime_segment_for_owner_module,
    validate_runtime_segment_dependencies,
)
from src.conversion.gml_transpiler_parts.gml_api_manifest import iter_gml_api_entries


EXPECTED_RUNTIME_SEGMENT_ORDER = (
    "00_prelude.gd",
    "15_asset_registry.gd",
    "10_handles_and_instances.gd",
    "11_layers.gd",
    "20_methods_and_exceptions.gd",
    "30_numeric_arithmetic.gd",
    "35_maths_numbers.gd",
    "40_arrays_structs_variables.gd",
    "45_collision_queries.gd",
    "46_motion_helpers.gd",
    "47_paths_motion_planning.gd",
    "48_drawing_basic_forms.gd",
    "49_drawing_surfaces.gd",
    "51_particles.gd",
    "52_cameras_display.gd",
    "53_game_input.gd",
    "54_audio_runtime.gd",
    "55_room_game_flow.gd",
    "56_time_alarms.gd",
    "57_ds_lists_stacks_queues.gd",
    "58_ds_maps.gd",
    "59_ds_grids.gd",
    "50_static_types_and_clone.gd",
    "60_conversion_helpers.gd",
    "61_sequences_timelines.gd",
    "65_files_ini_json.gd",
    "66_buffers.gd",
    "67_async_runtime.gd",
    "68_networking.gd",
    "69_physics.gd",
    "70_handle_string_helpers.gd",
    "71_flex_panels.gd",
    "72_os_debug_gc.gd",
    "73_platform_services.gd",
    "80_static_hash_clone_error.gd",
)


class TestGMLRuntimeSegments(unittest.TestCase):
    def test_runtime_segment_order_is_manifest_driven_and_stable(self) -> None:
        self.assertEqual(runtime_segment_names(), EXPECTED_RUNTIME_SEGMENT_ORDER)

    def test_runtime_manifest_validation_is_clean(self) -> None:
        self.assertEqual(validate_runtime_segments(), ())

    def test_dependency_validation_catches_late_or_missing_dependencies(self) -> None:
        segments = (
            RuntimeSegmentDefinition("10_consumer.gd", "consumer", depends_on=("20_provider.gd",)),
            RuntimeSegmentDefinition("20_provider.gd", "provider"),
            RuntimeSegmentDefinition("30_unknown.gd", "unknown", depends_on=("99_missing.gd",)),
        )

        errors = validate_runtime_segment_dependencies(segments)

        self.assertIn(
            "10_consumer.gd depends on 20_provider.gd, which is ordered after it",
            errors,
        )
        self.assertIn(
            "30_unknown.gd depends on unknown runtime segment 99_missing.gd",
            errors,
        )

    def test_runtime_symbols_are_unique_and_indexed(self) -> None:
        self.assertEqual(duplicate_runtime_symbols(), {})

        symbols = runtime_symbol_index()
        self.assertIn("GML_TYPE_UNDEFINED", symbols)
        self.assertIn("GMLHandle", symbols)
        self.assertIn("gml_asset_get_index", symbols)
        self.assertEqual(symbols["gml_asset_get_index"].segment_name, "15_asset_registry.gd")

    def test_runtime_symbol_extraction_indexes_public_helpers(self) -> None:
        public_helpers = [
            symbol
            for symbol in iter_runtime_segment_symbols()
            if symbol.kind == "static_func" and symbol.name.startswith("gml_")
        ]

        self.assertGreater(len(public_helpers), 100)
        indexed_symbols = runtime_symbol_index()
        for symbol in public_helpers:
            self.assertEqual(indexed_symbols[symbol.name], symbol)

    def test_runtime_api_index_links_manifest_metadata_to_segments(self) -> None:
        api_index = runtime_api_index()

        asset_entry = api_index["asset_get_index"]
        self.assertEqual(asset_entry.segment_name, "15_asset_registry.gd")
        self.assertEqual(asset_entry.runtime_symbol, "gml_asset_get_index")
        self.assertEqual(asset_entry.status, "implemented")
        self.assertIn("manual.gamemaker.io", asset_entry.docs_url)
        self.assertIn("tests/test_asset_registry.py", asset_entry.test_modules)

        layer_entry = api_index["layer_exists"]
        self.assertEqual(layer_entry.segment_name, "11_layers.gd")
        self.assertEqual(layer_entry.runtime_symbol, "gml_layer_exists")
        self.assertIn("tests/test_layers_runtime_godot.py", layer_entry.test_modules)

    def test_runtime_api_index_assigns_segments_to_discovered_runtime_symbols(self) -> None:
        missing_segments: list[str] = []
        for api_name, api_entry in runtime_api_index().items():
            if api_entry.runtime_symbol is not None and (
                api_entry.segment_name is None or not api_entry.test_modules
            ):
                missing_segments.append(api_name)

        self.assertEqual(missing_segments, [])

    def test_manifest_segment_owner_modules_resolve_to_declared_segments(self) -> None:
        for api_entry in iter_gml_api_entries():
            if api_entry.owner_module.startswith(RUNTIME_SEGMENT_MODULE_PREFIX):
                with self.subTest(api=api_entry.name, owner_module=api_entry.owner_module):
                    self.assertIsNotNone(runtime_segment_for_owner_module(api_entry.owner_module))


if __name__ == "__main__":
    unittest.main()
