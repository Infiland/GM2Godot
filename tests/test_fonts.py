# pyright: reportPrivateUsage=false

import json
import os
import sys
import shutil
import tempfile
import unittest
from typing import TypeAlias
from unittest.mock import Mock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.fonts import FontConverter, _find_system_font
from src.conversion.asset_output_paths import (
    build_asset_output_paths,
    resource_filesystem_path,
)
from src.conversion.diagnostics import ConversionDiagnostic, DiagnosticCollector


FontYY: TypeAlias = dict[str, object]


MINIMAL_FONT_YY: FontYY = {
    "$GMFont": "",
    "%Name": "fnt_test",
    "AntiAlias": 1,
    "bold": False,
    "canGenerateBitmap": True,
    "charset": 0,
    "first": 0,
    "fontName": "NonExistentTestFont99999",
    "glyphs": {},
    "glyphOperations": 0,
    "includeTTF": False,
    "italic": False,
    "kerningPairs": [],
    "last": 0,
    "lineHeight": 16,
    "maintainGms1Font": False,
    "name": "fnt_test",
    "parent": {"name": "Fonts", "path": "folders/Fonts.yy"},
    "ranges": [{"lower": 32, "upper": 127}],
    "regenerateBitmap": False,
    "resourceType": "GMFont",
    "resourceVersion": "2.0",
    "sampleText": "",
    "sdfSpread": 10,
    "size": 16.0,
    "styleName": "Regular",
    "textureGroupId": {"name": "Default", "path": "texturegroups/Default"},
    "TTFName": "",
    "usesSDF": False,
}


def _make_font_yy(base_dir: str, font_name: str, overrides: FontYY | None = None) -> str:
    """Create a font .yy file in the standard GM directory structure."""
    font_dir = os.path.join(base_dir, "fonts", font_name)
    os.makedirs(font_dir, exist_ok=True)
    data = dict(MINIMAL_FONT_YY)
    data["name"] = font_name
    data["%Name"] = font_name
    if overrides:
        data.update(overrides)
    yy_path = os.path.join(font_dir, f"{font_name}.yy")
    with open(yy_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return yy_path


def _write_font_yyp(base_dir: str, font_names: list[str]) -> None:
    with open(
        os.path.join(base_dir, "FontCollisionTest.yyp"),
        "w",
        encoding="utf-8",
    ) as project_file:
        json.dump(
            {
                "resources": [
                    {
                        "id": {
                            "name": font_name,
                            "path": f"fonts/{font_name}/{font_name}.yy",
                        }
                    }
                    for font_name in font_names
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
            project_file,
        )


class TestFontConverterSystemFont(unittest.TestCase):
    """Test that fonts not found on system produce SystemFont .tres files."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        _make_font_yy(self.gm_dir, "fnt_test", {
            "fontName": "NonExistentTestFont99999", "size": 16.0,
        })

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_creates_tres_file(self):
        converter = self._make_converter()
        converter.convert_all()
        expected = os.path.join(self.godot_dir, "fonts", "fnt_test.tres")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

    def test_tres_content(self):
        converter = self._make_converter()
        converter.convert_all()
        tres_path = os.path.join(self.godot_dir, "fonts", "fnt_test.tres")
        with open(tres_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('type="SystemFont"', content)
        self.assertIn('PackedStringArray("NonExistentTestFont99999")', content)
        self.assertIn("font_italic = false", content)
        self.assertIn("font_weight = 400", content)
        self.assertIn("antialiasing = 1", content)

    def test_logs_info_for_missing_font(self):
        converter = self._make_converter()
        converter.convert_all()
        info_logs = [l for l in self.logs if l.startswith("Info:")]
        warnings = [l for l in self.logs if l.startswith("Warning:")]
        self.assertTrue(info_logs,
                        "Expected an informational fallback log when font is not found on system")
        self.assertEqual(warnings, [])


class TestFontConverterBold(unittest.TestCase):
    """Test that bold fonts produce font_weight = 700."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        _make_font_yy(self.gm_dir, "fnt_bold", {
            "fontName": "NonExistentTestFont99999", "bold": True,
        })

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_bold_weight(self):
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        tres_path = os.path.join(self.godot_dir, "fonts", "fnt_bold.tres")
        with open(tres_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("font_weight = 700", content)


class TestFontConverterTTF(unittest.TestCase):
    """Test that fonts with includeTTF=true copy the TTF file."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        yy_path = _make_font_yy(self.gm_dir, "fnt_custom", {
            "fontName": "CustomFont",
            "includeTTF": True,
            "TTFName": "CustomFont.ttf",
        })
        ttf_path = os.path.join(os.path.dirname(yy_path), "CustomFont.ttf")
        with open(ttf_path, "wb") as f:
            f.write(b"\x00" * 128)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_copies_ttf(self):
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        expected = os.path.join(self.godot_dir, "fonts", "custom_font.ttf")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected TTF at {expected} after conversion")

    def test_no_tres_for_ttf(self):
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        tres_path = os.path.join(self.godot_dir, "fonts", "fnt_custom.tres")
        self.assertFalse(os.path.isfile(tres_path),
                         "Should not create .tres when TTF was copied")

    def test_bundled_ttf_retains_metadata_copy(self) -> None:
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        real_copy2 = shutil.copy2

        with patch("src.conversion.fonts.shutil.copy2", wraps=real_copy2) as copy2:
            converter.convert_all()

        copy2.assert_called_once()
        source_path, _staged_path = copy2.call_args.args
        self.assertEqual(source_path, os.path.realpath(os.path.join(
            self.gm_dir, "fonts", "fnt_custom", "CustomFont.ttf",
        )))

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_rejects_bundled_font_path_traversal_without_corrupting_project(
        self,
        _find_system_font: Mock,
    ) -> None:
        yy_path = os.path.join(
            self.gm_dir,
            "fonts",
            "fnt_custom",
            "fnt_custom.yy",
        )
        with open(yy_path, "r", encoding="utf-8") as font_yy_file:
            font_data = json.load(font_yy_file)
        font_data["TTFName"] = "../project.godot"
        with open(yy_path, "w", encoding="utf-8") as font_yy_file:
            json.dump(font_data, font_yy_file)

        malicious_source = os.path.join(self.gm_dir, "fonts", "project.godot")
        with open(malicious_source, "wb") as source_file:
            source_file.write(b"malicious replacement")
        destination_project = os.path.join(self.godot_dir, "project.godot")
        with open(destination_project, "wb") as project_file:
            project_file.write(b"original project")

        converter = FontConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        with open(destination_project, "rb") as project_file:
            self.assertEqual(project_file.read(), b"original project")
        self.assertTrue(os.path.isfile(os.path.join(self.godot_dir, "fonts", "fnt_custom.tres")))


class TestFontConverterTTFMissing(unittest.TestCase):
    """Test fallback to SystemFont when TTF file is missing and font not on system."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        _make_font_yy(self.gm_dir, "fnt_missing_ttf", {
            "fontName": "NonExistentTestFont99999",
            "includeTTF": True,
            "TTFName": "MissingFont.ttf",
        })

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_falls_back_to_system_font(self):
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        tres_path = os.path.join(self.godot_dir, "fonts", "fnt_missing_ttf.tres")
        self.assertTrue(os.path.isfile(tres_path),
                        "Should create SystemFont .tres as fallback")
        with open(tres_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('PackedStringArray("NonExistentTestFont99999")', content)
        fallback_logs = [l for l in self.logs if l.startswith("Info:")]
        warning_logs = [l for l in self.logs if l.startswith("Warning:")]
        self.assertTrue(fallback_logs)
        self.assertEqual(warning_logs, [])


class TestFontConverterSourcePathContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _make_converter(
        self,
        diagnostics: DiagnosticCollector | None = None,
    ) -> FontConverter:
        return FontConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )

    def _write_font_at(
        self,
        relative_path: str,
        font_name: str,
        overrides: FontYY | None = None,
    ) -> str:
        yy_path = os.path.join(self.gm_dir, *relative_path.split("/"))
        os.makedirs(os.path.dirname(yy_path), exist_ok=True)
        data = dict(MINIMAL_FONT_YY)
        data["name"] = font_name
        data["%Name"] = font_name
        if overrides:
            data.update(overrides)
        with open(yy_path, "w", encoding="utf-8") as yy_file:
            json.dump(data, yy_file)
        return yy_path

    def _write_yyp(self, resources: list[tuple[str, str]]) -> None:
        with open(
            os.path.join(self.gm_dir, "FontPaths.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "resources": [
                        {"id": {"name": name, "path": path}}
                        for name, path in resources
                    ],
                    "resourceType": "GMProject",
                },
                project_file,
            )

    @staticmethod
    def _rejections(
        diagnostics: DiagnosticCollector,
    ) -> list[ConversionDiagnostic]:
        return [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_uses_exact_declared_nested_font_yy_path(
        self,
        _find_system_font: Mock,
    ) -> None:
        declared_yy = self._write_font_at(
            "fonts/nested/custom_font.yy",
            "fnt_declared",
            {"fontName": "DeclaredNestedFamily"},
        )
        _make_font_yy(
            self.gm_dir,
            "fnt_declared",
            {"fontName": "ReconstructedDecoyFamily"},
        )
        self._write_yyp(
            [("fnt_declared", "fonts/nested/custom_font.yy")]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        self.assertEqual(converter.find_font_files(), [declared_yy])
        converter.convert_all()

        output_path = os.path.join(
            self.godot_dir,
            "fonts",
            "fnt_declared.tres",
        )
        with open(output_path, "r", encoding="utf-8") as output_file:
            output = output_file.read()
        self.assertIn("DeclaredNestedFamily", output)
        self.assertNotIn("ReconstructedDecoyFamily", output)
        self.assertEqual(self._rejections(diagnostics), [])

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_rejects_normalized_cross_family_manifest_path_and_keeps_safe_sibling(
        self,
        _find_system_font: Mock,
    ) -> None:
        font_name = "fnt_cross_family"
        self._write_font_at(
            "sprites/fnt_cross_family/decoy.yy",
            font_name,
            {"fontName": "CrossFamilyDecoy"},
        )
        safe_yy = self._write_font_at(
            "fonts/fnt_cross_family/safe.yy",
            font_name,
            {"fontName": "SafeFontFamily"},
        )
        self._write_yyp(
            [
                (
                    font_name,
                    "fonts/../sprites/fnt_cross_family/decoy.yy",
                ),
                (font_name, "fonts/fnt_cross_family/safe.yy"),
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        self.assertEqual(converter.find_font_files(), [safe_yy])
        converter.convert_all()

        output_path = os.path.join(
            self.godot_dir,
            "fonts",
            font_name + ".tres",
        )
        with open(output_path, "r", encoding="utf-8") as output_file:
            output = output_file.read()
        self.assertIn("SafeFontFamily", output)
        self.assertNotIn("CrossFamilyDecoy", output)
        rejected = self._rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "FontPaths.yyp")
        self.assertEqual(rejected[0].resource, font_name)
        self.assertEqual(rejected[0].resource_type, "font")
        self.assertEqual(
            rejected[0].manifest_entry,
            "resources[0].id.path",
        )

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_copies_normal_owner_relative_bundled_font(
        self,
        _find_system_font: Mock,
    ) -> None:
        yy_path = _make_font_yy(
            self.gm_dir,
            "fnt_owner_relative",
            {
                "fontName": "OwnerRelativeFamily",
                "includeTTF": True,
                "TTFName": "bundled/Owner Relative.otf",
            },
        )
        bundled_path = os.path.join(
            os.path.dirname(yy_path),
            "bundled",
            "Owner Relative.otf",
        )
        os.makedirs(os.path.dirname(bundled_path))
        with open(bundled_path, "wb") as bundled_file:
            bundled_file.write(b"owner-relative font")
        diagnostics = DiagnosticCollector()

        self._make_converter(diagnostics).convert_all()

        output_path = os.path.join(
            self.godot_dir,
            "fonts",
            "owner_relative.otf",
        )
        with open(output_path, "rb") as output_file:
            self.assertEqual(output_file.read(), b"owner-relative font")
        self.assertEqual(self._rejections(diagnostics), [])

    def test_rejects_disk_fallback_font_directory_link(self) -> None:
        outside_resource = os.path.join(self.outside_dir, "fnt_dir_link")
        os.makedirs(outside_resource)
        data = dict(MINIMAL_FONT_YY)
        data["name"] = "fnt_dir_link"
        with open(
            os.path.join(outside_resource, "fnt_dir_link.yy"),
            "w",
            encoding="utf-8",
        ) as yy_file:
            json.dump(data, yy_file)
        fonts_directory = os.path.join(self.gm_dir, "fonts")
        os.makedirs(fonts_directory)
        try:
            os.symlink(
                outside_resource,
                os.path.join(fonts_directory, "fnt_dir_link"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        diagnostics = DiagnosticCollector()

        font_files = self._make_converter(diagnostics).find_font_files()

        self.assertEqual(font_files, [])
        rejected = self._rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "fonts")
        self.assertEqual(rejected[0].resource, "fnt_dir_link")
        self.assertEqual(
            rejected[0].manifest_entry,
            "discovered font directory",
        )

    def test_rejects_disk_fallback_font_yy_link(self) -> None:
        outside_yy = os.path.join(self.outside_dir, "fnt_yy_link.yy")
        data = dict(MINIMAL_FONT_YY)
        data["name"] = "fnt_yy_link"
        with open(outside_yy, "w", encoding="utf-8") as yy_file:
            json.dump(data, yy_file)
        font_directory = os.path.join(
            self.gm_dir,
            "fonts",
            "fnt_yy_link",
        )
        os.makedirs(font_directory)
        try:
            os.symlink(
                outside_yy,
                os.path.join(font_directory, "fnt_yy_link.yy"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        diagnostics = DiagnosticCollector()

        font_files = self._make_converter(diagnostics).find_font_files()

        self.assertEqual(font_files, [])
        rejected = self._rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "fonts/fnt_yy_link")
        self.assertEqual(rejected[0].resource, "fnt_yy_link")
        self.assertEqual(rejected[0].manifest_entry, "discovered font .yy")

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_disk_fallback_rejects_contained_cross_family_font_yy_link(
        self,
        _find_system_font: Mock,
    ) -> None:
        linked_name = "fnt_cross_family_link"
        wrong_family_yy = self._write_font_at(
            "sprites/wrong_font/target.yy",
            linked_name,
            {"fontName": "WrongFamilyMarker"},
        )
        linked_directory = os.path.join(self.gm_dir, "fonts", linked_name)
        os.makedirs(linked_directory)
        safe_yy = self._write_font_at(
            "fonts/fnt_safe_sibling/fnt_safe_sibling.yy",
            "fnt_safe_sibling",
            {"fontName": "SafeSiblingMarker"},
        )
        try:
            os.symlink(
                wrong_family_yy,
                os.path.join(linked_directory, linked_name + ".yy"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        self.assertEqual(converter.find_font_files(), [safe_yy])
        converter.convert_all()

        safe_output = os.path.join(
            self.godot_dir,
            "fonts",
            "fnt_safe_sibling.tres",
        )
        with open(safe_output, "r", encoding="utf-8") as output_file:
            output = output_file.read()
        self.assertIn("SafeSiblingMarker", output)
        self.assertNotIn("WrongFamilyMarker", output)
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "fonts", linked_name + ".tres")
            )
        )
        rejected = self._rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, f"fonts/{linked_name}")
        self.assertEqual(rejected[0].resource, linked_name)
        self.assertEqual(rejected[0].resource_type, "font")
        self.assertEqual(rejected[0].manifest_entry, "discovered font .yy")

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_rejects_bundled_font_file_link_outside_project(
        self,
        _find_system_font: Mock,
    ) -> None:
        yy_path = _make_font_yy(
            self.gm_dir,
            "fnt_file_link",
            {
                "fontName": "LinkedFamily",
                "includeTTF": True,
                "TTFName": "LinkedFont.ttf",
            },
        )
        outside_font = os.path.join(self.outside_dir, "LinkedFont.ttf")
        with open(outside_font, "wb") as font_file:
            font_file.write(b"outside project font")
        try:
            os.symlink(
                outside_font,
                os.path.join(os.path.dirname(yy_path), "LinkedFont.ttf"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        diagnostics = DiagnosticCollector()

        self._make_converter(diagnostics).convert_all()

        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "fonts",
                    "fnt_file_link.tres",
                )
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "fonts", "linked_font.ttf")
            )
        )
        rejected = self._rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(
            rejected[0].source_path,
            "fonts/fnt_file_link/fnt_file_link.yy",
        )
        self.assertEqual(rejected[0].resource, "fnt_file_link")
        self.assertEqual(rejected[0].resource_type, "font")
        self.assertEqual(rejected[0].manifest_entry, "TTFName")

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_revalidates_bundled_font_immediately_before_copy(
        self,
        _find_system_font: Mock,
    ) -> None:
        yy_path = _make_font_yy(
            self.gm_dir,
            "fnt_late_swap",
            {
                "fontName": "LateSwapFamily",
                "includeTTF": True,
                "TTFName": "LateSwap.ttf",
            },
        )
        bundled_path = os.path.join(os.path.dirname(yy_path), "LateSwap.ttf")
        with open(bundled_path, "wb") as bundled_file:
            bundled_file.write(b"contained font")
        outside_font = os.path.join(self.outside_dir, "LateSwap.ttf")
        with open(outside_font, "wb") as outside_file:
            outside_file.write(b"outside font")
        probe_link = os.path.join(self.gm_dir, "font_symlink_probe")
        try:
            os.symlink(outside_font, probe_link)
            os.unlink(probe_link)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)
        real_output_destination = converter._font_output_destination

        def swap_before_copy(
            source_yy_path: str,
            font_name: str,
            output_filename: str,
        ) -> str:
            destination = real_output_destination(
                source_yy_path,
                font_name,
                output_filename,
            )
            os.unlink(bundled_path)
            os.symlink(outside_font, bundled_path)
            return destination

        with patch.object(
            converter,
            "_font_output_destination",
            side_effect=swap_before_copy,
        ):
            result = converter._process_font(yy_path)

        self.assertIs(result, False)
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "fonts", "late_swap.ttf")
            )
        )
        rejected = self._rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(
            rejected[0].source_path,
            "fonts/fnt_late_swap/fnt_late_swap.yy",
        )
        self.assertEqual(rejected[0].manifest_entry, "TTFName")

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_rejects_malformed_ttf_name_forms_with_owner_diagnostics(
        self,
        _find_system_font: Mock,
    ) -> None:
        outside_font = os.path.join(self.outside_dir, "Outside.ttf")
        with open(outside_font, "wb") as font_file:
            font_file.write(b"outside")
        malformed_names = {
            "fnt_traversal": os.path.relpath(
                outside_font,
                os.path.join(self.gm_dir, "fonts", "fnt_traversal"),
            ),
            "fnt_absolute": outside_font,
            "fnt_drive_absolute": r"C:\Games\Outside\Font.ttf",
            "fnt_drive_relative": r"C:Outside\Font.ttf",
            "fnt_unc": r"\\server\share\Font.ttf",
            "fnt_nul": "bad\0Font.ttf",
            "fnt_empty_segment": "nested//Font.ttf",
            "fnt_parent_segment": "nested/../Font.ttf",
            "fnt_wrong_extension": "Font.txt",
        }
        yy_paths = {
            font_name: _make_font_yy(
                self.gm_dir,
                font_name,
                {
                    "fontName": "UnavailableFamily",
                    "includeTTF": True,
                    "TTFName": ttf_name,
                },
            )
            for font_name, ttf_name in malformed_names.items()
        }
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        for font_name, yy_path in yy_paths.items():
            with self.subTest(font_name=font_name):
                self.assertEqual(converter._process_font(yy_path), font_name)
                self.assertTrue(
                    os.path.isfile(
                        os.path.join(
                            self.godot_dir,
                            "fonts",
                            font_name + ".tres",
                        )
                    )
                )

        rejected = self._rejections(diagnostics)
        self.assertEqual(len(rejected), len(malformed_names), rejected)
        self.assertEqual(
            {diagnostic.source_path for diagnostic in rejected},
            {
                f"fonts/{font_name}/{font_name}.yy"
                for font_name in malformed_names
            },
        )
        self.assertEqual(
            {diagnostic.resource for diagnostic in rejected},
            set(malformed_names),
        )
        self.assertTrue(
            all(diagnostic.resource_type == "font" for diagnostic in rejected)
        )
        self.assertTrue(
            all(diagnostic.manifest_entry == "TTFName" for diagnostic in rejected)
        )


class TestFontConverterSystemFontLookup(unittest.TestCase):
    """Test that fonts found on the system are copied as font files."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.fake_font_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create a fake system font file
        self.fake_ttf = os.path.join(self.fake_font_dir, "TestFont.ttf")
        with open(self.fake_ttf, "wb") as f:
            f.write(b"\x00" * 64)

        _make_font_yy(self.gm_dir, "fnt_sysfont", {"fontName": "TestFont"})

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.fake_font_dir)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_copies_system_font(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.fake_font_dir]
        diagnostics = DiagnosticCollector()
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        )
        converter.convert_all()
        expected = os.path.join(self.godot_dir, "fonts", "fnt_sysfont.ttf")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected system font copied to {expected}")
        self.assertEqual(
            TestFontConverterSourcePathContainment._rejections(diagnostics),
            [],
        )

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_no_tres_when_system_font_found(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.fake_font_dir]
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        tres_path = os.path.join(self.godot_dir, "fonts", "fnt_sysfont.tres")
        self.assertFalse(os.path.isfile(tres_path),
                         "Should not create .tres when system font was found and copied")

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_system_font_copy_does_not_propagate_protected_metadata(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.fake_font_dir]
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

        with patch(
            "src.conversion.fonts.shutil.copystat",
            side_effect=PermissionError("protected system flags"),
        ) as copystat:
            converter.convert_all()

        expected = os.path.join(self.godot_dir, "fonts", "fnt_sysfont.ttf")
        with open(expected, "rb") as copied_font:
            self.assertEqual(copied_font.read(), b"\x00" * 64)
        copystat.assert_not_called()
        self.assertEqual(self._partial_font_files(), [])

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_failed_system_font_copy_preserves_existing_file_and_cleans_partial(
        self,
        mock_dirs: Mock,
    ) -> None:
        mock_dirs.return_value = [self.fake_font_dir]
        output_dir = os.path.join(self.godot_dir, "fonts")
        os.makedirs(output_dir, exist_ok=True)
        destination = os.path.join(output_dir, "fnt_sysfont.ttf")
        with open(destination, "wb") as existing_font:
            existing_font.write(b"existing font")

        def fail_after_partial_copy(
            _source: str,
            staged_path: str,
            **_kwargs: object,
        ) -> None:
            with open(staged_path, "wb") as partial_font:
                partial_font.write(b"partial")
            raise OSError("copy interrupted")

        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        with (
            patch("src.conversion.fonts.shutil.copyfile", side_effect=fail_after_partial_copy),
            self.assertRaisesRegex(OSError, "copy interrupted"),
        ):
            converter.convert_all()

        with open(destination, "rb") as existing_font:
            self.assertEqual(existing_font.read(), b"existing font")
        self.assertEqual(self._partial_font_files(), [])

    def _partial_font_files(self) -> list[str]:
        output_dir = os.path.join(self.godot_dir, "fonts")
        if not os.path.isdir(output_dir):
            return []
        return [
            filename
            for filename in os.listdir(output_dir)
            if filename.startswith(".fnt_sysfont.ttf.") and filename.endswith(".part")
        ]


class TestFindSystemFont(unittest.TestCase):
    """Test the _find_system_font helper function."""

    def setUp(self):
        self.font_dir = tempfile.mkdtemp()
        self.font_file = os.path.join(self.font_dir, "MyFont.ttf")
        with open(self.font_file, "wb") as f:
            f.write(b"\x00" * 32)

    def tearDown(self):
        shutil.rmtree(self.font_dir)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_finds_exact_match(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("MyFont")
        self.assertEqual(result, self.font_file)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_finds_case_insensitive(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("myfont")
        self.assertEqual(result, self.font_file)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_finds_with_regular_suffix(self, mock_dirs: Mock) -> None:
        regular_font = os.path.join(self.font_dir, "TestFont-Regular.ttf")
        with open(regular_font, "wb") as f:
            f.write(b"\x00" * 32)
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("TestFont")
        self.assertEqual(result, regular_font)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_returns_none_when_not_found(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("NoSuchFont")
        self.assertIsNone(result)


class TestFontConverterCollisionSafeOutputs(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.system_font_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.system_font_dir)

    def _convert(self) -> None:
        FontConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=2,
        ).convert_all()

    def _font_paths(self) -> dict[str, str]:
        return build_asset_output_paths(
            self.gm_dir,
            self.godot_dir,
        )["fonts"]

    def _read_output(self, resource_path: str) -> bytes:
        output_path = resource_filesystem_path(self.godot_dir, resource_path)
        with open(output_path, "rb") as output_file:
            return output_file.read()

    def _write_system_font(self, filename: str, content: bytes) -> str:
        path = os.path.join(self.system_font_dir, filename)
        with open(path, "wb") as font_file:
            font_file.write(content)
        return path

    def test_bundled_font_collisions_emit_distinct_registry_paths(self) -> None:
        _write_font_yyp(self.gm_dir, ["fnt_a", "fnt_b"])
        first_yy = _make_font_yy(
            self.gm_dir,
            "fnt_a",
            {
                "fontName": "BundledOne",
                "includeTTF": True,
                "TTFName": "UI-Font.ttf",
            },
        )
        second_yy = _make_font_yy(
            self.gm_dir,
            "fnt_b",
            {
                "fontName": "BundledTwo",
                "includeTTF": True,
                "TTFName": "ui_font.TTF",
            },
        )
        with open(os.path.join(os.path.dirname(first_yy), "UI-Font.ttf"), "wb") as font:
            font.write(b"bundled one")
        with open(os.path.join(os.path.dirname(second_yy), "ui_font.TTF"), "wb") as font:
            font.write(b"bundled two")

        self._convert()
        paths = self._font_paths()

        self.assertEqual(paths["fnt_a"], "res://fonts/ui_font.ttf")
        self.assertEqual(paths["fnt_b"], "res://fonts/ui_font_2.ttf")
        self.assertEqual(self._read_output(paths["fnt_a"]), b"bundled one")
        self.assertEqual(self._read_output(paths["fnt_b"]), b"bundled two")

    @patch("src.conversion.fonts._find_system_font")
    def test_system_font_collisions_emit_distinct_registry_paths(
        self,
        find_system_font: Mock,
    ) -> None:
        _write_font_yyp(self.gm_dir, ["FontUI", "font_ui"])
        _make_font_yy(self.gm_dir, "FontUI", {"fontName": "SystemOne"})
        _make_font_yy(self.gm_dir, "font_ui", {"fontName": "SystemTwo"})
        system_paths = {
            "SystemOne": self._write_system_font("SystemOne.OTF", b"system one"),
            "SystemTwo": self._write_system_font("SystemTwo.OTF", b"system two"),
        }
        find_system_font.side_effect = system_paths.get

        self._convert()
        paths = self._font_paths()

        self.assertEqual(paths["font_ui"], "res://fonts/font_ui.otf")
        self.assertEqual(paths["FontUI"], "res://fonts/font_ui_2.otf")
        self.assertEqual(self._read_output(paths["font_ui"]), b"system two")
        self.assertEqual(self._read_output(paths["FontUI"]), b"system one")

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_system_font_fallback_collisions_emit_distinct_registry_paths(
        self,
        _find_system_font: Mock,
    ) -> None:
        _write_font_yyp(self.gm_dir, ["MenuFont", "menu_font"])
        _make_font_yy(self.gm_dir, "MenuFont", {"fontName": "MenuFamilyOne"})
        _make_font_yy(self.gm_dir, "menu_font", {"fontName": "MenuFamilyTwo"})

        self._convert()
        paths = self._font_paths()

        self.assertEqual(paths["menu_font"], "res://fonts/menu_font.tres")
        self.assertEqual(paths["MenuFont"], "res://fonts/menu_font_2.tres")
        self.assertIn(b'MenuFamilyTwo', self._read_output(paths["menu_font"]))
        self.assertIn(b'MenuFamilyOne', self._read_output(paths["MenuFont"]))

    @patch("src.conversion.fonts._find_system_font", return_value=None)
    def test_yyp_ownership_excludes_orphan_font_collision(
        self,
        _find_system_font: Mock,
    ) -> None:
        _write_font_yyp(self.gm_dir, ["FontUI"])
        _make_font_yy(self.gm_dir, "FontUI", {"fontName": "ReferencedFamily"})
        _make_font_yy(self.gm_dir, "font_ui", {"fontName": "OrphanFamily"})

        self._convert()
        paths = self._font_paths()

        self.assertEqual(paths, {"FontUI": "res://fonts/font_ui.tres"})
        self.assertIn(b"ReferencedFamily", self._read_output(paths["FontUI"]))
        self.assertNotIn(b"OrphanFamily", self._read_output(paths["FontUI"]))
        self.assertFalse(
            os.path.exists(os.path.join(self.godot_dir, "fonts", "font_ui_2.tres"))
        )


class TestFontConverterMissingFolder(unittest.TestCase):
    """No fonts/ directory in GM project should not crash."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_missing_fonts_no_crash(self):
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for missing fonts folder")


class TestFontConverterEmptyFolder(unittest.TestCase):
    """Empty fonts/ directory should not crash."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        os.makedirs(os.path.join(self.gm_dir, "fonts"))

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_empty_fonts_no_crash(self):
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for empty fonts folder")


class TestFontConverterSubfolders(unittest.TestCase):
    """Test that fonts respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        _make_font_yy(self.gm_dir, "fnt_ui", {
            "fontName": "NonExistentTestFont99999",
            "parent": {"name": "UI", "path": "folders/Fonts/UI.yy"},
        })

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_font_in_subfolder(self):
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "fonts", "ui", "fnt_ui.tres")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected font at {expected}")

    def test_root_level_font_stays_flat(self):
        """Font with root-level parent should remain in fonts/."""
        _make_font_yy(self.gm_dir, "fnt_root", {
            "fontName": "NonExistentTestFont99999",
            "parent": {"name": "Fonts", "path": "folders/Fonts.yy"},
        })
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "fonts", "fnt_root.tres")
        self.assertTrue(os.path.isfile(expected),
                        "Root-level font should stay in fonts/")


if __name__ == "__main__":
    unittest.main()
