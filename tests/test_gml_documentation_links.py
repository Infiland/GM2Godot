from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit

from src.conversion.gml_runtime import runtime_api_index
from src.conversion.gml_transpiler import (
    get_gml_api_entry,
    get_gml_manual_scope_entry,
    iter_gml_api_entries,
    iter_gml_function_descriptors,
    iter_gml_manual_scope_entries,
)
from src.conversion.gml_transpiler_parts.gml_api_manifest import (
    GAMEMAKER_LTS_MANUAL_ROOT,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
EVIDENCE_TOPICS_PATH = FIXTURE_ROOT / "gamemaker_lts_2026_evidence_topics.txt"
OFFICIAL_TOPICS_PATH = FIXTURE_ROOT / "gamemaker_lts_2026_official_topics.txt"
PROVENANCE_PATH = (
    FIXTURE_ROOT / "gamemaker_lts_2026_evidence_topics.provenance.json"
)
EXPECTED_MANUAL_COMMIT = "bb7dc2165b6bd77eedfe4dd5afe3445ef53a4601"
EXPECTED_MANUAL_ROOT_TREE = "5eb4b897d120cc35456aef1253a05d798cb124e2"
EXPECTED_MANUAL_CONTENTS_TREE = "705a8aa0dad952998bef9be0890d9c90b3e4b0f0"
EXPECTED_OFFICIAL_TOPICS_SHA256 = (
    "ac92f570f7659d4fdfa3af7777affc90774aa9a9e801e23b11723fc9001830d4"
)

KNOWN_MISSING_LTS_TOPICS = {
    "GameMaker_Language/GML_Overview/Preprocessor.htm",
    "GameMaker_Language/GML_Reference/Array_Functions/Array_Functions.htm",
    "GameMaker_Language/GML_Reference/Cameras_And_Display/display_set_orientation.htm",
    "GameMaker_Language/GML_Reference/Drawing/Shaders/Shaders.htm",
    "GameMaker_Language/GML_Reference/Variable_Functions/Array_Functions/Array_Functions.htm",
}


def _all_evidence_urls() -> set[str]:
    urls = {entry.docs_url for entry in iter_gml_api_entries()}
    urls.update(entry.docs_url for entry in iter_gml_function_descriptors())
    urls.update(entry.docs_url for entry in iter_gml_manual_scope_entries())
    urls.update(entry.docs_url for entry in runtime_api_index().values())
    return urls


def _relative_lts_topic(url: str) -> str:
    if not url.startswith(GAMEMAKER_LTS_MANUAL_ROOT):
        raise AssertionError(f"not a GameMaker LTS manual URL: {url}")
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment:
        raise AssertionError(f"manual evidence URL must name one exact topic: {url}")
    return unquote(url.removeprefix(GAMEMAKER_LTS_MANUAL_ROOT))


class TestGMLDocumentationLinks(unittest.TestCase):
    def test_all_generated_evidence_uses_pinned_verified_lts_topics(self) -> None:
        fixture_bytes = EVIDENCE_TOPICS_PATH.read_bytes()
        fixture_topics = fixture_bytes.decode("utf-8").splitlines()
        official_bytes = OFFICIAL_TOPICS_PATH.read_bytes()
        official_topics = official_bytes.decode("utf-8").splitlines()
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(fixture_topics, sorted(fixture_topics))
        self.assertEqual(len(fixture_topics), len(set(fixture_topics)))
        self.assertEqual(official_topics, sorted(official_topics))
        self.assertEqual(len(official_topics), len(set(official_topics)))
        self.assertEqual(
            provenance["repository"],
            "https://github.com/YoYoGames/GameMaker-Manual",
        )
        self.assertEqual(provenance["ref"], "2026.0.0-main")
        self.assertEqual(provenance["commit"], EXPECTED_MANUAL_COMMIT)
        self.assertEqual(provenance["root_tree"], EXPECTED_MANUAL_ROOT_TREE)
        self.assertEqual(
            provenance["contents_tree"], EXPECTED_MANUAL_CONTENTS_TREE
        )
        self.assertEqual(provenance["official_topic_count"], len(official_topics))
        self.assertEqual(len(official_topics), 3311)
        self.assertEqual(
            provenance["official_topics_sha256"],
            EXPECTED_OFFICIAL_TOPICS_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(official_bytes).hexdigest(),
            EXPECTED_OFFICIAL_TOPICS_SHA256,
        )
        self.assertEqual(provenance["evidence_topic_count"], len(fixture_topics))
        self.assertEqual(
            provenance["evidence_topics_sha256"],
            hashlib.sha256(fixture_bytes).hexdigest(),
        )

        generated_topics = {_relative_lts_topic(url) for url in _all_evidence_urls()}
        self.assertEqual(generated_topics, set(fixture_topics))
        self.assertTrue(generated_topics.issubset(set(official_topics)))
        self.assertTrue(generated_topics.isdisjoint(KNOWN_MISSING_LTS_TOPICS))
        self.assertTrue(set(official_topics).isdisjoint(KNOWN_MISSING_LTS_TOPICS))

    def test_array_evidence_uses_exact_lts_topics_or_documented_alias(self) -> None:
        exact_page_names = (
            "array_push",
            "array_create",
            "array_length_1d",
            "array_resize",
            "array_pop",
            "array_insert",
            "array_delete",
            "array_shuffle",
            "array_copy",
            "array_concat",
            "array_contains",
            "array_find_index",
            "array_map",
            "array_filter",
            "array_reduce",
        )
        for name in exact_page_names:
            with self.subTest(api=name):
                entry = get_gml_api_entry(name)
                self.assertIsNotNone(entry)
                assert entry is not None
                self.assertEqual(
                    entry.docs_url,
                    GAMEMAKER_LTS_MANUAL_ROOT
                    + f"GameMaker_Language/GML_Reference/Variable_Functions/{name}.htm",
                )

        alias = get_gml_api_entry("array_push_back")
        self.assertIsNotNone(alias)
        assert alias is not None
        self.assertEqual(
            alias.docs_url,
            GAMEMAKER_LTS_MANUAL_ROOT
            + "GameMaker_Language/GML_Reference/Variable_Functions/Array_Functions.htm",
        )
        self.assertIn("compatibility alias", alias.notes)
        self.assertIn("no dedicated array_push_back API page", alias.notes)

    def test_shader_evidence_uses_exact_lts_topics(self) -> None:
        shader_page_names = (
            "shader_set",
            "shader_reset",
            "shader_get_name",
            "shader_is_compiled",
            "shader_get_uniform",
            "shader_get_sampler_index",
            "shader_set_uniform_f",
            "shader_set_uniform_i",
            "shader_set_uniform_f_array",
            "shader_set_uniform_i_array",
            "shader_set_uniform_matrix",
            "shader_enable_corner_id",
        )
        for name in shader_page_names:
            with self.subTest(api=name):
                entry = get_gml_api_entry(name)
                self.assertIsNotNone(entry)
                assert entry is not None
                self.assertEqual(
                    entry.docs_url,
                    GAMEMAKER_LTS_MANUAL_ROOT
                    + f"GameMaker_Language/GML_Reference/Asset_Management/Shaders/{name}.htm",
                )

        texture_set_stage = get_gml_api_entry("texture_set_stage")
        self.assertIsNotNone(texture_set_stage)
        assert texture_set_stage is not None
        self.assertEqual(
            texture_set_stage.docs_url,
            GAMEMAKER_LTS_MANUAL_ROOT
            + "GameMaker_Language/GML_Reference/Drawing/Textures/texture_set_stage.htm",
        )

    def test_scope_and_extension_fallbacks_are_explicit(self) -> None:
        preprocessor = get_gml_manual_scope_entry("language_preprocessor_macros")
        arrays = get_gml_manual_scope_entry("reference_array_functions")
        display_orientation = get_gml_api_entry("display_set_orientation")

        self.assertIsNotNone(preprocessor)
        self.assertIsNotNone(arrays)
        self.assertIsNotNone(display_orientation)
        assert preprocessor is not None
        assert arrays is not None
        assert display_orientation is not None

        self.assertEqual(
            preprocessor.docs_url,
            GAMEMAKER_LTS_MANUAL_ROOT
            + "GameMaker_Language/GML_Overview/Variables/Constants.htm",
        )
        self.assertIn("compatibility extensions", preprocessor.notes)
        self.assertEqual(
            arrays.docs_url,
            GAMEMAKER_LTS_MANUAL_ROOT
            + "GameMaker_Language/GML_Reference/Variable_Functions/Array_Functions.htm",
        )
        self.assertEqual(
            display_orientation.docs_url,
            GAMEMAKER_LTS_MANUAL_ROOT
            + "GameMaker_Language/GML_Reference/Cameras_And_Display/Cameras_And_Display.htm",
        )
        self.assertIn("No GameMaker LTS 2026 API page", display_orientation.notes)
        self.assertIn("compatibility extension", display_orientation.notes)


if __name__ == "__main__":
    unittest.main()
