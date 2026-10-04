from __future__ import annotations

import sys
import tempfile
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from scripts.build_application_assets import application_asset_inputs, copy_application_assets
from src import application_resources, localization

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def packaged_resource_fixture() -> Generator[tuple[Path, Path], None, None]:
    with tempfile.TemporaryDirectory(prefix="gm2godot-resource-test-") as raw_root:
        root = Path(raw_root)
        build = root / "build"
        copy_application_assets(PROJECT_ROOT, build)
        packaged = build / "src" / "application_assets"
        user_directory = root / "preferences"
        with (
            mock.patch("src.application_resources.packaged_application_asset_base", return_value=str(packaged)),
            mock.patch("src.application_resources.application_preferences_directory", return_value=str(user_directory)),
        ):
            yield packaged, user_directory


class ApplicationResourcesTests(unittest.TestCase):
    def test_build_copies_canonical_payloads_without_rewriting_sources(self) -> None:
        inputs = application_asset_inputs(PROJECT_ROOT)
        before = {relative: (PROJECT_ROOT / relative).read_bytes() for relative in inputs}
        with tempfile.TemporaryDirectory(prefix="gm2godot-resource-copy-") as raw_build:
            outputs = copy_application_assets(PROJECT_ROOT, Path(raw_build))
            packaged = Path(raw_build) / "src" / "application_assets"
            self.assertEqual({path.relative_to(packaged) for path in outputs}, set(inputs))
            for relative, expected in before.items():
                with self.subTest(relative=relative):
                    self.assertEqual((packaged / relative).read_bytes(), expected)
                    self.assertEqual((PROJECT_ROOT / relative).read_bytes(), expected)
            self.assertFalse((packaged / "Languages" / "template").exists())
            self.assertFalse((packaged / "main.py").exists())

    def test_source_and_frozen_roots_keep_their_existing_preference_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-root-layout-") as raw_root:
            root = Path(raw_root)
            source = root / "source"
            source.mkdir()
            absent_package = root / "no-package-assets"
            user_directory = root / "preferences"
            with (
                mock.patch("src.application_resources.packaged_application_asset_base", return_value=str(absent_package)),
                mock.patch("src.application_resources.application_preferences_directory", return_value=str(user_directory)),
            ):
                source_base = str(source)
                self.assertIs(application_resources.application_resource_base(source_base), source_base)
                self.assertEqual(
                    application_resources.language_preference_read_path(source_base), str(source / "Current Language")
                )
                self.assertEqual(
                    application_resources.language_preference_write_path(source_base), str(source / "Current Language")
                )
                self.assertFalse(user_directory.exists())
            frozen = root / "frozen"
            frozen.mkdir()
            with (
                mock.patch.object(sys, "frozen", True, create=True),
                mock.patch.object(sys, "_MEIPASS", str(frozen), create=True),
                mock.patch("src.localization.application_resource_base", side_effect=AssertionError("frozen fallback")),
            ):
                self.assertEqual(localization.get_base_path(), str(frozen))

    def test_source_missing_preference_still_fails_before_catalog_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-missing-language-") as raw_root:
            source = Path(raw_root)
            languages = source / "Languages"
            languages.mkdir()
            (languages / "eng.json").write_text('{"Language": "English"}', encoding="utf-8")
            with mock.patch("src.localization.get_base_path", return_value=str(source)):
                with self.assertRaises(FileNotFoundError):
                    localization.get_localized("Language")

    def test_packaged_default_read_does_not_create_user_state(self) -> None:
        with packaged_resource_fixture() as (packaged, user_directory):
            self.assertEqual(application_resources.application_resource_base("unrelated/source"), str(packaged))
            self.assertEqual(
                application_resources.language_preference_read_path(str(packaged)), str(packaged / "Current Language")
            )
            self.assertEqual(localization.get_localized("Language"), "English")
            self.assertFalse(user_directory.exists())

    def test_installed_language_round_trip_keeps_packaged_payloads_unchanged(self) -> None:
        with packaged_resource_fixture() as (packaged, user_directory):
            payloads = {path: path.read_bytes() for path in packaged.rglob("*") if path.is_file()}
            write_path = Path(application_resources.language_preference_write_path(str(packaged)))
            self.assertEqual(write_path, user_directory / "Current Language")
            write_path.write_text("de", encoding="utf-8")
            self.assertEqual(application_resources.language_preference_read_path(str(packaged)), str(write_path))
            self.assertEqual(localization.get_localized("Language"), "Deutsch")
            write_path.write_text("missing-catalog", encoding="utf-8")
            self.assertEqual(localization.get_localized("Language"), "English")
            for path, expected in payloads.items():
                with self.subTest(path=path.relative_to(packaged)):
                    self.assertEqual(path.read_bytes(), expected)

    def test_installed_unreadable_user_preference_keeps_the_read_error(self) -> None:
        with packaged_resource_fixture() as (packaged, user_directory):
            user_directory.mkdir()
            preference = user_directory / "Current Language"
            preference.mkdir()
            self.assertEqual(application_resources.language_preference_read_path(str(packaged)), str(preference))
            with self.assertRaises(OSError):
                localization.get_localized("Language")


if __name__ == "__main__":
    unittest.main()
