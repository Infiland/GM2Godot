from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.fonts import FontConverter
from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import require_exact_godot


def _write_font_input(root: Path) -> tuple[Path, Path]:
    source, output = root / "source", root / "output"
    font = source / "fonts/fnt_runtime/fnt_runtime.yy"
    font.parent.mkdir(parents=True)
    font.write_text(json.dumps({
        "resourceType": "GMFont", "name": "fnt_runtime", "fontName": "monospace",
        "size": 23, "bold": True, "italic": True, "AntiAlias": 1, "includeTTF": False,
    }), encoding="utf-8")
    (source / "FontRuntime.yyp").write_text(json.dumps({
        "resourceType": "GMProject", "resources": [
            {"id": {"name": "fnt_runtime", "path": "fonts/fnt_runtime/fnt_runtime.yy"}},
        ], "RoomOrderNodes": [],
    }), encoding="utf-8")
    output.mkdir()
    (output / "project.godot").write_text('[application]\nconfig/name="FontRuntimeContract"\n', encoding="utf-8")
    return source, output


def _write_font_probe(output: Path) -> None:
    (output / "font_probe.gd").write_text(textwrap.dedent('''\
        extends SceneTree
        const GML = preload("res://gm2godot/gml_runtime.gd")
        const Registry = preload("res://gm2godot/gml_asset_registry.gd")

        func _initialize():
            var entries = Registry.gml_asset_registry_entries()
            assert(entries.size() == 1)
            assert(entries[0]["name"] == "fnt_runtime")
            assert(entries[0]["godot_path"] == "res://fonts/fnt_runtime.tres")
            var font = load(entries[0]["godot_path"])
            assert(font is SystemFont)
            assert(font.font_names == PackedStringArray(["monospace"]))
            assert(font.font_italic)
            assert(font.font_weight == 700)
            assert(font.antialiasing == TextServer.FONT_ANTIALIASING_GRAY)
            var selected = GML.gml_asset_get_index("fnt_runtime")
            assert(selected == entries[0]["id"])
            assert(selected >= 0)
            GML.gml_draw_set_font(selected)
            assert(GML.gml_draw_get_font() == selected)
            var sample = "WWW iii Font 0123456789"
            var measured = GML.gml_string_width(sample)
            var expected = font.get_string_size(sample, HORIZONTAL_ALIGNMENT_LEFT, -1, ThemeDB.fallback_font_size).x
            assert(expected > 0.0)
            assert(is_equal_approx(measured, expected))
            GML.gml_draw_set_font(-1)
            assert(GML.gml_draw_get_font() == -1)
            print("CONVERTED_FONT_RUNTIME_OK")
            quit(0)
        '''), encoding="utf-8")


class TestConvertedFontRuntime(unittest.TestCase):
    def test_converted_system_font_is_selected_and_measured(self) -> None:
        godot = require_exact_godot()
        with tempfile.TemporaryDirectory() as directory:
            source, output = _write_font_input(Path(directory))
            logs: list[str] = []
            with patch("src.conversion.font_sources.system_font_directories", return_value=[]):
                converter = FontConverter(source, output, log_callback=logs.append, max_workers=1)
                converter.convert_all()
                registry = AssetRegistryConverter(source, output, log_callback=logs.append)
                registry_path = registry.convert_all()
            self.assertEqual(converter.conversion_step_result().resources, ConversionCounts(1, 1, 1))
            self.assertEqual(Path(registry_path), output / "gm2godot/gml_asset_registry.gd")
            self.assertTrue((output / "fonts/fnt_runtime.tres").is_file())
            write_gml_runtime(str(output))
            _write_font_probe(output)
            environment = {**os.environ, "HOME": str(output)}
            imported = subprocess.run(
                [godot, "--headless", "--log-file", str(output / "import.log"), "--path", str(output),
                 "--editor", "--import", "--quit"],
                capture_output=True, text=True, timeout=30, check=False, env=environment,
            )
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            ran = subprocess.run(
                [godot, "--headless", "--log-file", str(output / "runtime.log"), "--path", str(output),
                 "--script", "res://font_probe.gd"],
                capture_output=True, text=True, timeout=20, check=False, env=environment,
            )
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn("CONVERTED_FONT_RUNTIME_OK", ran.stdout + ran.stderr)
