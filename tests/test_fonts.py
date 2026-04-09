import json
import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.fonts import FontConverter, _find_system_font


MINIMAL_FONT_YY = {
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


def _make_font_yy(base_dir, font_name, overrides=None):
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


class TestFontConverterSystemFont(unittest.TestCase):
    """Test that fonts not found on system produce SystemFont .tres files."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []
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

    def test_logs_warning_for_missing_font(self):
        converter = self._make_converter()
        converter.convert_all()
        warnings = [l for l in self.logs if "Warning:" in l or "warning:" in l.lower()]
        self.assertTrue(len(warnings) > 0,
                        "Expected a warning when font is not found on system")


class TestFontConverterBold(unittest.TestCase):
    """Test that bold fonts produce font_weight = 700."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []
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
        self.logs = []
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
        expected = os.path.join(self.godot_dir, "fonts", "CustomFont.ttf")
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


class TestFontConverterTTFMissing(unittest.TestCase):
    """Test fallback to SystemFont when TTF file is missing and font not on system."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []
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


class TestFontConverterSystemFontLookup(unittest.TestCase):
    """Test that fonts found on the system are copied as font files."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.fake_font_dir = tempfile.mkdtemp()
        self.logs = []

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
    def test_copies_system_font(self, mock_dirs):
        mock_dirs.return_value = [self.fake_font_dir]
        converter = FontConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        expected = os.path.join(self.godot_dir, "fonts", "fnt_sysfont.ttf")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected system font copied to {expected}")

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_no_tres_when_system_font_found(self, mock_dirs):
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
    def test_finds_exact_match(self, mock_dirs):
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("MyFont")
        self.assertEqual(result, self.font_file)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_finds_case_insensitive(self, mock_dirs):
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("myfont")
        self.assertEqual(result, self.font_file)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_finds_with_regular_suffix(self, mock_dirs):
        regular_font = os.path.join(self.font_dir, "TestFont-Regular.ttf")
        with open(regular_font, "wb") as f:
            f.write(b"\x00" * 32)
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("TestFont")
        self.assertEqual(result, regular_font)

    @patch('src.conversion.fonts._get_system_font_dirs')
    def test_returns_none_when_not_found(self, mock_dirs):
        mock_dirs.return_value = [self.font_dir]
        result = _find_system_font("NoSuchFont")
        self.assertIsNone(result)


class TestFontConverterMissingFolder(unittest.TestCase):
    """No fonts/ directory in GM project should not crash."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

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
        self.logs = []
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


if __name__ == "__main__":
    unittest.main()
