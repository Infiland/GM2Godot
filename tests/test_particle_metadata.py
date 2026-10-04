from __future__ import annotations

import unittest
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.particle_assets import (
    normalize_particle_system_asset,
    render_particle_system_resource,
)
from src.conversion.particle_metadata import ParticleSystemDescriptor


def _objects(value: JsonValue) -> list[JsonObject]:
    assert isinstance(value, list)
    result: list[JsonObject] = []
    for item in value:
        assert isinstance(item, dict)
        result.append(item)
    return result


class TestParticleMetadata(unittest.TestCase):
    def test_normalizer_consumes_typed_system_descriptor(self) -> None:
        with patch("src.conversion.particle_assets.ParticleSystemDescriptor", wraps=ParticleSystemDescriptor) as constructor:
            result = normalize_particle_system_asset({"name": "spark"})
        self.assertEqual(constructor.call_count, 1)
        self.assertEqual(result["name"], "spark")
        self.assertEqual(result["types"], [])

    def test_modern_emitters_supply_embedded_types_only_without_explicit_types(self) -> None:
        emitter: JsonObject = {"name": "embedded", "texture": 12}
        modern = normalize_particle_system_asset({"emitters": [emitter]})
        legacy = normalize_particle_system_asset({"particleTypes": [{"name": "explicit"}], "emitters": [emitter]})
        self.assertEqual(_objects(modern["types"])[0]["name"], "embedded")
        self.assertEqual(_objects(legacy["types"])[0]["name"], "explicit")
        self.assertEqual(len(_objects(legacy["types"])), 1)

    def test_null_and_malformed_explicit_store_preserve_types_fallback(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, {})
        for value in values:
            with self.subTest(value=value):
                result = normalize_particle_system_asset({"particleTypes": value, "types": [{"name": "fallback"}]})
                self.assertEqual(_objects(result["types"])[0]["name"], "fallback")
        result = normalize_particle_system_asset({"particleTypes": [], "types": [{"name": "ignored"}]})
        self.assertEqual(result["types"], [])

    def test_first_present_numeric_alias_does_not_fall_through_after_bad_value(self) -> None:
        result = normalize_particle_system_asset({"particleTypes": [{"sizeMin": "bad", "size_min": 7}]})
        self.assertEqual(_objects(result["types"])[0]["size_min"], 1.0)

    def test_bool_nonfinite_and_bad_string_keep_particle_fallbacks(self) -> None:
        for value in (True, None, float("nan"), float("inf"), "bad"):
            with self.subTest(type=type(value).__name__):
                result = normalize_particle_system_asset({"xorigin": value})
                self.assertEqual(result["xorigin"], 0.0)

    def test_huge_integer_overflow_remains_uncaught_particle_policy(self) -> None:
        with self.assertRaises(OverflowError):
            normalize_particle_system_asset({"xorigin": 10**10000})

    def test_spawn_unknown_id_and_preset_keep_exact_child_identity(self) -> None:
        child: JsonObject = {"unknown": [None, False, {"value": 3}]}
        result = normalize_particle_system_asset({"particleTypes": [{"spawnOnDeathId": child, "spawnOnDeathGMPreset": child}]})
        spawn = _objects(result["types"])[0]["spawn_on_death"]
        assert isinstance(spawn, dict)
        self.assertIs(spawn["id"], child)
        self.assertIs(spawn["preset"], child)

    def test_deep_unknown_spawn_reference_needs_no_family_graph_walk(self) -> None:
        source = '{"particleTypes":[{"spawnOnDeathId":' + '[' * 400 + 'null' + ']' * 400 + '}],}'
        data = decode_gamemaker_json(source, source_path="particles/deep.yy").value
        assert isinstance(data, dict)
        child = _objects(data["particleTypes"])[0]["spawnOnDeathId"]
        result = normalize_particle_system_asset(data)
        spawn = _objects(result["types"])[0]["spawn_on_death"]
        assert isinstance(spawn, dict)
        self.assertIs(spawn["id"], child)

    def test_nonfinite_unknown_spawn_reference_fails_at_renderer(self) -> None:
        result = normalize_particle_system_asset({"particleTypes": [{"spawnOnDeathId": float("nan")}]})
        with self.assertRaises(ValueError):
            render_particle_system_resource("spark", "particles/spark.yy", result)

    def test_emitter_region_bounds_and_numeric_aliases_keep_owner_normalization(self) -> None:
        result = normalize_particle_system_asset({"emitters": [{"regionX": "10", "regionY": "20", "regionW": -4, "regionH": -6, "emitCount": "2.5"}]})
        emitter = _objects(result["emitters"])[0]
        self.assertEqual(emitter["number"], 2.5)
        self.assertEqual(emitter["region"], {"xmin": 8.0, "xmax": 12.0, "ymin": 17.0, "ymax": 23.0, "shape": "rectangle", "distribution": "linear"})
