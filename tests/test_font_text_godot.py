"""Converted GameMaker fonts import cleanly and lay text out like GameMaker.

The fixture converts synthetic GameMaker fonts (baked atlas plus glyph table)
with the real font converter and asset registry, then asks Godot for the
generated runtime's text metrics, line layout and glyph quads. Every value is
compared with ``tests.gamemaker_font_reference``, an independent model of the
GameMaker runner. When ``xvfb-run`` is available the same text is rendered
with the OpenGL renderer and compared with the reference pixel by pixel.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

from PIL import Image, ImageChops

from src.conversion.asset_registry import AssetRegistryConverter, render_asset_registry_script
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.fonts import FontConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.godot_validation import (
    GodotValidationReport,
    detect_godot_output_issues,
    validate_generated_godot_project,
)
from tests.gamemaker_font_reference import (
    FA_BOTTOM,
    FA_CENTER,
    FA_LEFT,
    FA_MIDDLE,
    FA_RIGHT,
    FA_TOP,
    GameMakerTextReference,
    ReferenceQuad,
    SyntheticFont,
    draw_reference_quads,
    write_font_project,
    write_gamemaker_font,
)
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_RESULT_PREFIX = "FONT_TEXT_RESULT "
_CANVAS_WIDTH = 800
_CANVAS_HEIGHT = 400
_LATIN = tuple(range(32, 127))
_SYSTEM_FONT = "fnt_system"


@dataclass(frozen=True)
class _TextCase:
    font: str
    x: float
    y: float
    text: str
    sep: int = -1
    width: int = -1
    halign: int = FA_LEFT
    valign: int = FA_TOP

    def to_json(self) -> dict[str, object]:
        return {
            "font": self.font,
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "sep": self.sep,
            "width": self.width,
            "halign": self.halign,
            "valign": self.valign,
        }


_CASES = (
    _TextCase("fnt_plain", 10.5, 12.25, "Hello, World!\nSecond line"),
    _TextCase("fnt_plain", 300.0, 60.0, "Centered text\r\nwith CRLF", halign=FA_CENTER, valign=FA_MIDDLE),
    _TextCase("fnt_plain", 780.49, 20.51, "Right \u00e9 and missing \u2603 glyphs", halign=FA_RIGHT),
    _TextCase(
        "fnt_plain",
        20.0,
        200.0,
        "the quick brown fox jumps over the lazy dog  and   spaces",
        sep=18,
        width=90,
        valign=FA_BOTTOM,
    ),
    _TextCase("fnt_kerned", 30.0, 230.0, "AVATAR To Vo AV VA V A"),
    _TextCase("fnt_kerned", 420.0, 230.0, "A\u0416A soft\u00adhyphen \u0436", halign=FA_CENTER),
    _TextCase(
        "fnt_kerned",
        780.0,
        320.0,
        "wrapped kerned AVAV text that wraps",
        sep=20,
        width=70,
        halign=FA_RIGHT,
        valign=FA_MIDDLE,
    ),
    _TextCase("fnt_sdf", 40.5, 330.0, "SDF text\nline two"),
)

_MEASURED_TEXTS: tuple[tuple[str, int, int], ...] = (
    ("", -1, -1),
    ("A", -1, -1),
    ("Hello World", -1, -1),
    ("a\nbb\nccc", -1, -1),
    ("\n", -1, -1),
    ("A\n", -1, -1),
    ("x\r\ny\n\rz", -1, -1),
    ("\u2603 missing", -1, -1),
    ("tab\there", -1, -1),
    ("the quick brown fox jumps over", -1, 40),
    ("the quick brown fox", 20, 40),
    ("  leading spaces", -1, 10),
    ("word", 7, 1),
    ("supercalifragilistic word", -1, 30),
    ("soft\u00adhyphen A\u0416", 0, 10000000),
)


def _write_probe(project_dir: Path, data_path: Path, output_dir: Path) -> None:
    script = textwrap.dedent(
        f"""\
        extends Node

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const DATA_PATH = {json.dumps(str(data_path))}
        const OUTPUT_DIR = {json.dumps(str(output_dir))}


        func _glyph_quad(ts, font_rid, font_size, index, pen):
        \tvar key = Vector2i(font_size, 0)
        \tvar size = ts.font_get_glyph_size(font_rid, key, index)
        \tif size.x <= 0.0 or size.y <= 0.0:
        \t\treturn null
        \tvar offset = ts.font_get_glyph_offset(font_rid, key, index)
        \tvar uv = ts.font_get_glyph_uv_rect(font_rid, key, index)
        \tvar origin = pen.floor() + offset
        \treturn [index, origin.x, origin.y, size.x, size.y, uv.position.x, uv.position.y]


        # Mirrors what Font.draw_string and Font.draw_char draw for a laid-out
        # line: shaped glyphs (or the line's own codes and pen offsets) placed
        # at the snapped baseline, each quad at the floored pen plus the glyph
        # offset of a fixed-size bitmap font.
        func _line_quads(layout, line, origin):
        \tvar ts = TextServerManager.get_primary_interface()
        \tvar font = layout["font"]
        \tvar font_size = int(layout["font_size"])
        \tvar font_rid = font.get_rids()[0]
        \tvar baseline = GMRuntime._gml_draw_text_line_baseline(origin, line, layout)
        \tvar quads = []
        \tvar codes = line["codes"]
        \tif typeof(codes) == TYPE_PACKED_INT32_ARRAY:
        \t\tvar offsets = line["offsets"]
        \t\tfor index in range(codes.size()):
        \t\t\tvar quad = _glyph_quad(ts, font_rid, font_size, codes[index], baseline + Vector2(offsets[index], 0.0))
        \t\t\tif quad != null:
        \t\t\t\tquads.append(quad)
        \t\treturn quads
        \tvar shaped = TextLine.new()
        \tshaped.add_string(line["text"], font, font_size)
        \tvar pen = baseline
        \tfor glyph in ts.shaped_text_get_glyphs(shaped.get_rid()):
        \t\tfor _repeat in range(int(glyph["repeat"])):
        \t\t\tif glyph["font_rid"] != font_rid:
        \t\t\t\tquads.append(["foreign glyph", glyph["index"]])
        \t\t\telse:
        \t\t\t\tvar quad = _glyph_quad(ts, font_rid, font_size, int(glyph["index"]), pen + glyph["offset"])
        \t\t\t\tif quad != null:
        \t\t\t\t\tquads.append(quad)
        \t\t\tpen.x += float(glyph["advance"])
        \treturn quads


        func _font_record(name):
        \tGMRuntime.gml_draw_set_font(GMRuntime.gml_asset_get_index(name))
        \tvar info = GMRuntime._gml_draw_font_info()
        \tvar font = info["font"]
        \tvar font_size = int(info["font_size"])
        \tvar record = {{
        \t\t"class": font.get_class(),
        \t\t"font_size": font_size,
        \t\t"bitmap": info["bitmap"],
        \t\t"fixed_size": int(font.fixed_size) if font is FontFile else 0,
        \t\t"ascent": font.get_ascent(font_size),
        \t\t"height": font.get_height(font_size),
        \t\t"system_fallback": bool(font.allow_system_fallback) if font is FontFile else null,
        \t}}
        \tif font is FontFile and font.fixed_size > 0:
        \t\tvar key = Vector2i(font_size, 0)
        \t\trecord["texture_count"] = font.get_texture_count(0, key)
        \t\tvar texture_path = OUTPUT_DIR.path_join(name + ".png")
        \t\tfont.get_texture_image(0, key, 0).save_png(texture_path)
        \t\trecord["texture"] = texture_path
        \treturn record


        func _ready():
        \tvar data = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
        \tvar result = {{"fonts": {{}}, "measures": [], "cases": []}}
        \tfor name in data["fonts"]:
        \t\tresult["fonts"][name] = _font_record(name)
        \tfor measure in data["measures"]:
        \t\tGMRuntime.gml_draw_set_font(GMRuntime.gml_asset_get_index(measure["font"]))
        \t\tvar text = measure["text"]
        \t\tresult["measures"].append([
        \t\t\tGMRuntime.gml_string_width(text),
        \t\t\tGMRuntime.gml_string_height(text),
        \t\t\tGMRuntime.gml_string_width_ext(text, measure["sep"], measure["width"]),
        \t\t\tGMRuntime.gml_string_height_ext(text, measure["sep"], measure["width"]),
        \t\t])
        \tfor case in data["cases"]:
        \t\tGMRuntime.gml_draw_set_font(GMRuntime.gml_asset_get_index(case["font"]))
        \t\tGMRuntime.gml_draw_set_halign(case["halign"])
        \t\tGMRuntime.gml_draw_set_valign(case["valign"])
        \t\tvar layout = GMRuntime._gml_draw_text_layout(case["text"], case["sep"], case["width"])
        \t\tvar origin = Vector2(case["x"], case["y"])
        \t\tvar lines = []
        \t\tvar quads = []
        \t\tfor line in layout["lines"]:
        \t\t\tlines.append([line["x"], line["y"], line["width"]])
        \t\t\tquads.append_array(_line_quads(layout, line, origin))
        \t\tresult["cases"].append({{"line_step": layout["line_step"], "lines": lines, "quads": quads}})
        \tprint({json.dumps(_RESULT_PREFIX)} + JSON.stringify(result))
        \tget_tree().quit(0)
        """
    )
    write_fixture_text(project_dir / "font_probe.gd", script)
    write_fixture_text(project_dir / "font_probe.tscn", _scene("font_probe.gd", "Node"))


def _write_renderer(project_dir: Path, data_path: Path) -> None:
    script = textwrap.dedent(
        f"""\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const DATA_PATH = {json.dumps(str(data_path))}


        func _draw():
        \tvar data = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
        \tdraw_rect(Rect2(0, 0, {_CANVAS_WIDTH}, {_CANVAS_HEIGHT}), Color.BLACK)
        \tfor case in data["cases"]:
        \t\tGMRuntime.gml_draw_set_font(GMRuntime.gml_asset_get_index(case["font"]))
        \t\tGMRuntime.gml_draw_set_halign(case["halign"])
        \t\tGMRuntime.gml_draw_set_valign(case["valign"])
        \t\tvar layout = GMRuntime._gml_draw_text_layout(case["text"], case["sep"], case["width"])
        \t\tGMRuntime._gml_draw_text_emit(get_canvas_item(), Vector2(case["x"], case["y"]), layout, Color.WHITE)
        """
    )
    write_fixture_text(project_dir / "font_render.gd", script)
    write_fixture_text(project_dir / "font_render.tscn", _scene("font_render.gd", "Node2D"))


def _scene(script_name: str, node_type: str) -> str:
    return (
        "[gd_scene load_steps=2 format=3]\n\n"
        f'[ext_resource type="Script" path="res://{script_name}" id="1"]\n\n'
        f'[node name="Probe" type="{node_type}"]\n'
        'script = ExtResource("1")\n'
    )


def _project_settings() -> str:
    return (
        "[application]\n"
        'config/name="FontTextGodot"\n'
        'run/main_scene="res://font_render.tscn"\n\n'
        "[display]\n"
        f"window/size/viewport_width={_CANVAS_WIDTH}\n"
        f"window/size/viewport_height={_CANVAS_HEIGHT}\n\n"
        "[rendering]\n"
        "textures/canvas_textures/default_texture_filter=0\n"
    )


def _quad_tuple(quad: ReferenceQuad) -> tuple[int, ...]:
    return (quad.code, quad.left, quad.top, quad.w, quad.h, quad.atlas_x, quad.atlas_y)


def _max_channel_difference(actual: Image.Image, expected: Image.Image) -> int:
    worst = 0
    for band in ImageChops.difference(actual, expected).split():
        high = band.getextrema()[1]
        if isinstance(high, (int, float)):
            worst = max(worst, int(high))
    return worst


class TestFontTextGodot(unittest.TestCase):
    godot_binary: ClassVar[str]
    workspace: ClassVar[tempfile.TemporaryDirectory[str]]
    gm_dir: ClassVar[Path]
    project_dir: ClassVar[Path]
    output_dir: ClassVar[Path]
    data_path: ClassVar[Path]
    fonts: ClassVar[dict[str, SyntheticFont]]
    references: ClassVar[dict[str, GameMakerTextReference]]
    conversion_diagnostics: ClassVar[list[tuple[str, str]]]
    validation: ClassVar[GodotValidationReport]
    probe_output: ClassVar[str]
    probe_returncode: ClassVar[int]
    result: ClassVar[dict[str, object]]

    @classmethod
    def setUpClass(cls) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            raise unittest.SkipTest("Godot binary not available")
        cls.godot_binary = godot_binary
        cls.workspace = tempfile.TemporaryDirectory()
        root = Path(cls.workspace.name)
        cls.gm_dir = root / "gm"
        cls.project_dir = root / "godot"
        cls.output_dir = root / "probe"
        cls.data_path = root / "cases.json"
        for directory in (cls.gm_dir, cls.project_dir, cls.output_dir):
            directory.mkdir()
        cls._write_gamemaker_project()
        cls._convert()
        cls._run_probe()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.workspace.cleanup()

    @classmethod
    def _write_gamemaker_project(cls) -> None:
        gm_dir = str(cls.gm_dir)
        cls.fonts = {
            "fnt_plain": write_gamemaker_font(
                gm_dir,
                "fnt_plain",
                codes=_LATIN + (0xE9,),
                ascender=10,
                ascender_offset=2,
            ),
            "fnt_kerned": write_gamemaker_font(
                gm_dir,
                "fnt_kerned",
                codes=_LATIN + (0xAD, 0x416, 0x436),
                seed=3,
                kerning=(
                    (65, 86, -2),
                    (86, 65, 1),
                    (84, 111, -1),
                    (32, 65, -2),
                    (86, 32, 1),
                    (65, 0x416, -1),
                    (0x416, 65, 2),
                ),
                apply_kerning=True,
                ascender=9,
                ascender_offset=1,
                line_height=15,
                size=12.5,
            ),
            "fnt_sdf": write_gamemaker_font(gm_dir, "fnt_sdf", seed=5, uses_sdf=True, sdf_spread=4),
            _SYSTEM_FONT: write_gamemaker_font(
                gm_dir,
                _SYSTEM_FONT,
                write_atlas=False,
                overrides={"glyphs": {}, "fontName": "NonExistentTestFont99999"},
            ),
        }
        cls.references = {
            name: font.reference() for name, font in cls.fonts.items() if name != _SYSTEM_FONT
        }
        write_font_project(gm_dir, list(cls.fonts))

    @classmethod
    def _convert(cls) -> None:
        diagnostics = DiagnosticCollector()
        FontConverter(
            str(cls.gm_dir),
            str(cls.project_dir),
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()
        cls.conversion_diagnostics = [
            (diagnostic.code, diagnostic.message) for diagnostic in diagnostics.diagnostics()
        ]
        entries = AssetRegistryConverter(
            str(cls.gm_dir),
            str(cls.project_dir),
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
        ).build_entries()
        write_fixture_text(
            cls.project_dir / "gm2godot" / "gml_asset_registry.gd",
            render_asset_registry_script(entries),
        )
        write_gml_runtime(str(cls.project_dir))
        write_fixture_text(cls.project_dir / "project.godot", _project_settings())
        cls.data_path.write_text(
            json.dumps(
                {
                    "fonts": list(cls.fonts),
                    "measures": [
                        {"font": font, "text": text, "sep": sep, "width": width}
                        for font in cls.references
                        for text, sep, width in _MEASURED_TEXTS
                    ],
                    "cases": [case.to_json() for case in _CASES],
                }
            ),
            encoding="utf-8",
        )
        _write_probe(cls.project_dir, cls.data_path, cls.output_dir)
        _write_renderer(cls.project_dir, cls.data_path)

    @classmethod
    def _run_probe(cls) -> None:
        cls.validation = validate_generated_godot_project(
            str(cls.project_dir),
            godot_binary=cls.godot_binary,
            timeout=180,
        )
        environment = dict(os.environ, HOME=str(cls.output_dir))
        completed = subprocess.run(
            [
                cls.godot_binary,
                "--headless",
                "--path",
                str(cls.project_dir),
                "--scene",
                "res://font_probe.tscn",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            env=environment,
        )
        cls.probe_returncode = completed.returncode
        cls.probe_output = completed.stdout + completed.stderr
        result: dict[str, object] = {}
        for line in cls.probe_output.splitlines():
            if line.startswith(_RESULT_PREFIX):
                result = json.loads(line.removeprefix(_RESULT_PREFIX))
        cls.result = result

    def _result_list(self, key: str) -> list[object]:
        self.assertIn(key, self.result, self.probe_output)
        value = self.result[key]
        assert isinstance(value, list)
        return cast(list[object], value)

    def _font_record(self, name: str) -> dict[str, object]:
        fonts = self.result.get("fonts")
        self.assertIsInstance(fonts, dict, self.probe_output)
        record = cast(dict[str, object], fonts)[name]
        assert isinstance(record, dict)
        return cast(dict[str, object], record)

    def test_converted_fonts_import_and_run_without_godot_issues(self) -> None:
        # Only the SDF font and the font without glyph data need a note.
        self.assertEqual(
            sorted(
                (code, "fnt_sdf" in message, _SYSTEM_FONT in message)
                for code, message in self.conversion_diagnostics
            ),
            [("GM2GD-FONT-SDF-BITMAP", True, False), ("GM2GD-WARNING", False, True)],
        )
        self.assertEqual(self.validation.status, "passed", self.validation.output)
        self.assertEqual(self.validation.output_issues, (), self.validation.output)
        self.assertIn("res://fonts/fnt_plain.fnt", self.validation.resource_paths)
        self.assertEqual(self.probe_returncode, 0, self.probe_output)
        self.assertEqual(detect_godot_output_issues(self.probe_output), (), self.probe_output)

    def test_bitmap_fonts_load_at_their_native_size(self) -> None:
        for name, font in self.fonts.items():
            if name == _SYSTEM_FONT:
                continue
            with self.subTest(font=name):
                record = self._font_record(name)
                reference = self.references[name]
                ascent = font.ascender if 0 < font.ascender <= reference.line_height else reference.line_height
                self.assertEqual(record["class"], "FontFile")
                self.assertEqual(record["bitmap"], True)
                self.assertEqual(record["fixed_size"], int(font.size + 0.5))
                self.assertEqual(record["font_size"], record["fixed_size"])
                self.assertEqual(record["ascent"], ascent)
                self.assertEqual(record["height"], reference.line_height)
                self.assertEqual(record["system_fallback"], False)
                self.assertEqual(record["texture_count"], 1)

    def test_bitmap_font_pages_keep_the_baked_glyph_pixels(self) -> None:
        for name in self.references:
            with self.subTest(font=name):
                record = self._font_record(name)
                texture_path = record["texture"]
                assert isinstance(texture_path, str)
                with Image.open(texture_path) as texture, Image.open(
                    self.project_dir / "fonts" / f"{name}.png"
                ) as page:
                    self.assertEqual(texture.size, page.size)
                    self.assertEqual(texture.convert("RGBA").tobytes(), page.convert("RGBA").tobytes())

    def test_fallback_font_uses_gamemaker_point_size(self) -> None:
        record = self._font_record(_SYSTEM_FONT)

        self.assertEqual(record["class"], "SystemFont")
        self.assertEqual(record["bitmap"], False)
        self.assertEqual(record["font_size"], 16)

    def test_string_metrics_match_gamemaker(self) -> None:
        measures = self._result_list("measures")
        expected_rows = [
            (font, text, sep, width)
            for font in self.references
            for text, sep, width in _MEASURED_TEXTS
        ]
        self.assertEqual(len(measures), len(expected_rows))
        for (font, text, sep, width), actual in zip(expected_rows, measures, strict=True):
            reference = self.references[font]
            with self.subTest(font=font, text=text, sep=sep, width=width):
                self.assertEqual(
                    actual,
                    [
                        reference.string_width(text),
                        reference.string_height(text),
                        reference.string_width(text, sep, width),
                        reference.string_height(text, sep, width),
                    ],
                )

    def test_text_layout_matches_gamemaker(self) -> None:
        cases = self._result_list("cases")
        self.assertEqual(len(cases), len(_CASES))
        for case, actual in zip(_CASES, cases, strict=True):
            assert isinstance(actual, dict)
            record = cast(dict[str, object], actual)
            reference = self.references[case.font]
            origins = reference.line_origins(
                case.text, sep=case.sep, line_width=case.width, halign=case.halign, valign=case.valign
            )
            lines = reference.split(case.text, case.width)
            with self.subTest(text=case.text):
                self.assertEqual(record["line_step"], reference.line_step(case.sep))
                self.assertEqual(
                    record["lines"],
                    [
                        [x, y, reference.text_width(line)]
                        for (x, y), line in zip(origins, lines, strict=True)
                    ],
                )

    def test_glyph_quads_land_where_gamemaker_draws_them(self) -> None:
        cases = self._result_list("cases")
        for case, actual in zip(_CASES, cases, strict=True):
            assert isinstance(actual, dict)
            quads = cast(dict[str, object], actual)["quads"]
            assert isinstance(quads, list)
            expected = self.references[case.font].quads(
                case.x,
                case.y,
                case.text,
                sep=case.sep,
                line_width=case.width,
                halign=case.halign,
                valign=case.valign,
            )
            with self.subTest(text=case.text):
                self.assertTrue(expected)
                self.assertEqual(
                    [tuple(cast(list[int], quad)) for quad in cast(list[object], quads)],
                    [_quad_tuple(quad) for quad in expected],
                )

    def test_rendered_text_matches_gamemaker_pixels(self) -> None:
        if shutil.which("xvfb-run") is None:
            self.skipTest("xvfb-run is not available for an OpenGL render")
        movie_dir = self.output_dir / "movie"
        movie_dir.mkdir(exist_ok=True)
        completed = subprocess.run(
            [
                "xvfb-run",
                "-a",
                "-s",
                f"-screen 0 {_CANVAS_WIDTH + 64}x{_CANVAS_HEIGHT + 64}x24",
                self.godot_binary,
                "--path",
                str(self.project_dir),
                "--rendering-driver",
                "opengl3",
                "--write-movie",
                str(movie_dir / "frame.png"),
                "--fixed-fps",
                "60",
                "--quit-after",
                "3",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=dict(os.environ, HOME=str(self.output_dir)),
        )
        frames = sorted(movie_dir.glob("frame*.png"))
        if not frames:
            self.skipTest("OpenGL rendering is unavailable: " + (completed.stdout + completed.stderr)[-2000:])

        expected = Image.new("RGBA", (_CANVAS_WIDTH, _CANVAS_HEIGHT), (0, 0, 0, 255))
        for case in _CASES:
            with Image.open(self.project_dir / "fonts" / f"{case.font}.png") as page:
                atlas = page.convert("RGBA")
            draw_reference_quads(
                expected,
                atlas,
                self.references[case.font].quads(
                    case.x,
                    case.y,
                    case.text,
                    sep=case.sep,
                    line_width=case.width,
                    halign=case.halign,
                    valign=case.valign,
                ),
            )
        with Image.open(frames[-1]) as frame:
            actual = frame.convert("RGB")
        self.assertEqual(actual.size, expected.size)
        # Blending may round differently between drivers; a misplaced glyph
        # differs by far more than a couple of levels.
        worst = _max_channel_difference(actual, expected.convert("RGB"))
        self.assertLessEqual(worst, 2, f"render differs from GameMaker by up to {worst} levels")


if __name__ == "__main__":
    unittest.main()
