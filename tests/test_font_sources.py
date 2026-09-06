import os
import platform
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.conversion import font_sources
from src.conversion.font_sources import resolve_system_font_source


class TestFindSystemFont(unittest.TestCase):
    """Test the resolve_system_font_source helper function."""

    def setUp(self):
        self.font_dir = tempfile.mkdtemp()
        self.font_file = os.path.join(self.font_dir, "MyFont.ttf")
        with open(self.font_file, "wb") as f:
            f.write(b"\x00" * 32)

    def tearDown(self):
        shutil.rmtree(self.font_dir)

    @patch('src.conversion.font_sources.system_font_directories')
    def test_finds_exact_match(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.font_dir]
        result = resolve_system_font_source("MyFont")
        self.assertEqual(result, self.font_file)

    @patch('src.conversion.font_sources.system_font_directories')
    def test_finds_case_insensitive(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.font_dir]
        result = resolve_system_font_source("myfont")
        self.assertEqual(result, self.font_file)

    @patch('src.conversion.font_sources.system_font_directories')
    def test_finds_with_regular_suffix(self, mock_dirs: Mock) -> None:
        regular_font = os.path.join(self.font_dir, "TestFont-Regular.ttf")
        with open(regular_font, "wb") as f:
            f.write(b"\x00" * 32)
        mock_dirs.return_value = [self.font_dir]
        result = resolve_system_font_source("TestFont")
        self.assertEqual(result, regular_font)

    @patch('src.conversion.font_sources.system_font_directories')
    def test_returns_none_when_not_found(self, mock_dirs: Mock) -> None:
        mock_dirs.return_value = [self.font_dir]
        result = resolve_system_font_source("NoSuchFont")
        self.assertIsNone(result)


class TestFontSourceSelection(unittest.TestCase):
    def test_bundled_filename_grammar(self) -> None:
        cases = {
            "Family.TTF": "family.ttf", r"nested\Font Name.OTF": "font_name.otf",
            "nested/123.woff2": "_123.woff2", "?.ttc": "resource.ttc",
            "Family.OTC": "family.otc", "Family.WOFF": "family.woff",
            "": None, "/Family.ttf": None, r"\Family.ttf": None, "C:Family.ttf": None,
            "C:/Family.ttf": None, "./Family.ttf": None, "../Family.ttf": None,
            "nested//Family.ttf": None, "nested/../Family.ttf": None, "nested/./Family.ttf": None,
            "Family.ttf/": None, ".ttf": None, "Family": None, "Family.fon": None,
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(font_sources.bundled_font_output_filename(source), expected)

    def test_directory_and_walk_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "z_first"
            second = Path(directory) / "a_second"
            nested = first / "z_nested"
            later = first / "a_later"
            for folder in (first, second, nested, later):
                folder.mkdir(exist_ok=True)
                (folder / "Family.ttf").write_bytes(b"first-match-input")
            (nested / "Family-Regular.otf").write_bytes(b"alternate-match")
            walk: list[tuple[str, list[str], list[str]]] = [
                (str(nested), [], ["Family.ttf", "Family-Regular.otf"]),
                (str(later), [], ["Family.ttf"]),
            ]
            with patch("src.conversion.font_sources.system_font_directories", return_value=[str(first), str(second)]):
                with patch("src.conversion.font_sources.os.walk", return_value=walk) as walking:
                    selected = resolve_system_font_source("Family")
                self.assertEqual(selected, str(nested / "Family.ttf"))
                walking.assert_called_once_with(str(first))

    def test_suffix_case_and_extension_rules(self) -> None:
        cases = (
            ("MY FAMILY.TTF", "my family", True), ("MyFamily.otf", "My Family", True),
            ("My Family-Regular.ttc", "MyFamily", True), ("MyFamily-Normal.otc", "MyFamily", True),
            ("MyFamily_regular.woff", "MyFamily", True), ("MyFamily_normal.WOFF2", "MyFamily", True),
            ("MyFamilyBold.ttf", "MyFamily", False), ("OtherMyFamily.ttf", "MyFamily", False),
            ("MyFamily.fon", "MyFamily", False), ("Straße.ttf", "STRASSE", False),
            ("Straße.ttf", "STRAẞE", True),
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch("src.conversion.font_sources.system_font_directories", return_value=[directory]):
                for filename, family, matches in cases:
                    path = Path(directory) / filename
                    path.write_bytes(b"font-source")
                    with self.subTest(filename=filename, family=family):
                        self.assertEqual(resolve_system_font_source(family), str(path) if matches else None)
                    path.unlink()

    def test_platform_directory_selection(self) -> None:
        windows = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            windows.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
        mac = ["/Library/Fonts", "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
        linux = ["/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.local/share/fonts"), os.path.expanduser("~/.fonts")]
        host = {"Windows": windows, "Darwin": mac}.get(platform.system(), linux)
        self.assertEqual(font_sources.system_font_directories(), [path for path in host if os.path.isdir(path)])
        expanded = {path: os.path.expanduser(path)
                    for path in ("~/Library/Fonts", "~/.local/share/fonts", "~/.fonts")}
        with patch.dict(os.environ, {"WINDIR": "wind", "LOCALAPPDATA": "local"}, clear=True):
            modeled = (
                ("Windows", [os.path.join("wind", "Fonts"), os.path.join("local", "Microsoft", "Windows", "Fonts")]),
                ("Darwin", mac), ("Linux", linux), ("Other", linux),
            )
            for system, candidates in modeled:
                # Preserve native expanduser results while testing the explicit platform branch.
                with (
                    patch("src.conversion.font_sources.platform.system", return_value=system),
                    patch("src.conversion.font_sources.os.path.expanduser", side_effect=expanded.__getitem__),
                    patch("src.conversion.font_sources.os.path.isdir", return_value=True) as is_directory,
                ):
                    actual = font_sources.system_font_directories()
                    is_directory.return_value = False
                    self.assertEqual(font_sources.system_font_directories(), [])
                self.assertEqual(actual, candidates)
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.conversion.font_sources.platform.system", return_value="Windows"):
                with patch("src.conversion.font_sources.os.path.isdir", return_value=True):
                    self.assertEqual(font_sources.system_font_directories(), [os.path.join(r"C:\Windows", "Fonts")])
