"""Baked GameMaker font atlases rendered as Godot BMFont descriptors."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import unittest

from PIL import Image

from src.conversion.font_atlas import (
    GameMakerFontAtlasMetadata,
    GameMakerFontAtlasPlan,
    GameMakerFontGlyph,
    bmfont_base,
    bmfont_fixed_size,
    build_font_atlas_image,
    font_atlas_image_name,
    font_registry_metadata,
    parse_gamemaker_font_atlas_metadata,
    plan_gamemaker_font_atlas,
    render_bmfont_import_config,
    render_bmfont_text,
    render_skipped_import_config,
)
from src.conversion.json_values import JsonObject, validate_json_value
from tests.gamemaker_font_reference import (
    FA_CENTER,
    FA_MIDDLE,
    ReferenceQuad,
    SyntheticFont,
    write_gamemaker_font,
)

_BMFONT_FIELD = re.compile(r'(\w+)=("[^"]*"|\S+)')


def _json_object(document: dict[str, object]) -> JsonObject:
    value = validate_json_value(document, source_path="test.yy")
    assert isinstance(value, dict)
    return value


def _bmfont_records(text: str) -> list[tuple[str, dict[str, str]]]:
    records: list[tuple[str, dict[str, str]]] = []
    for line in text.splitlines():
        tag, _separator, rest = line.partition(" ")
        fields = {key: value.strip('"') for key, value in _BMFONT_FIELD.findall(rest)}
        records.append((tag, fields))
    return records


def _bmfont_record(text: str, tag: str) -> dict[str, str]:
    matches = [fields for record_tag, fields in _bmfont_records(text) if record_tag == tag]
    assert len(matches) == 1, (tag, matches)
    return matches[0]


def _bmfont_chars(text: str) -> dict[int, dict[str, int]]:
    return {
        int(fields["id"]): {key: int(value) for key, value in fields.items()}
        for tag, fields in _bmfont_records(text)
        if tag == "char"
    }


def _bmfont_kernings(text: str) -> dict[tuple[int, int], int]:
    return {
        (int(fields["first"]), int(fields["second"])): int(fields["amount"])
        for tag, fields in _bmfont_records(text)
        if tag == "kerning"
    }


def _metadata(document: dict[str, object]) -> GameMakerFontAtlasMetadata:
    metadata = parse_gamemaker_font_atlas_metadata(_json_object(document))
    assert metadata is not None
    return metadata


def _glyph_document(**fields: object) -> dict[str, object]:
    glyph: dict[str, object] = {"x": 1, "y": 1, "w": 4, "h": 6, "shift": 5, "offset": 0}
    glyph.update(fields)
    return glyph


class FontAtlasTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.project_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.project_dir)

    def _plan(self, font: SyntheticFont) -> GameMakerFontAtlasPlan:
        assert font.atlas_path is not None
        plan = plan_gamemaker_font_atlas(_metadata(font.document), font.atlas_path)
        assert plan is not None
        return plan


class TestParseGameMakerFontAtlasMetadata(FontAtlasTestCase):
    def test_reads_glyph_map_in_code_order_with_metrics(self) -> None:
        font = write_gamemaker_font(
            self.project_dir,
            "fnt_ui",
            codes=(90, 32, 65, 66),
            ascender=9,
            ascender_offset=2,
            size=10.5,
        )

        metadata = _metadata(font.document)

        self.assertEqual([glyph.code for glyph in metadata.glyphs], [32, 65, 66, 90])
        for glyph in metadata.glyphs:
            source = font.glyphs[glyph.code]
            self.assertEqual(
                (glyph.x, glyph.y, glyph.width, glyph.height, glyph.shift, glyph.offset),
                (source.x, source.y, source.w, source.h, source.shift, source.offset),
            )
        self.assertEqual(metadata.line_height, max(glyph.h for glyph in font.glyphs.values()))
        self.assertEqual((metadata.ascender, metadata.ascender_offset), (9, 2))
        self.assertEqual(metadata.size, 10.5)
        self.assertEqual(metadata.font_name, "Synthetic Sans")
        self.assertEqual(metadata.rejected_glyph_keys, ())

    def test_declared_line_height_wins_over_glyph_cells(self) -> None:
        font = write_gamemaker_font(self.project_dir, "fnt_ui", line_height=21)

        self.assertEqual(_metadata(font.document).line_height, 21)

    def test_reads_gamemaker_2_2_glyph_list_layouts(self) -> None:
        keyed = _metadata(
            {
                "glyphs": [
                    {"Key": 66, "Value": _glyph_document(x=9, shift=7)},
                    {"Key": 65, "Value": _glyph_document(offset=-1)},
                ]
            }
        )
        plain = _metadata({"glyphs": [_glyph_document(character=67, w=3)]})

        self.assertEqual([glyph.code for glyph in keyed.glyphs], [65, 66])
        self.assertEqual((keyed.glyphs[0].offset, keyed.glyphs[1].x, keyed.glyphs[1].shift), (-1, 9, 7))
        self.assertEqual([(glyph.code, glyph.width) for glyph in plain.glyphs], [(67, 3)])

    def test_accepts_integral_numbers_and_numeric_strings(self) -> None:
        metadata = _metadata(
            {"glyphs": {"65": _glyph_document(x="3", y=2.0, w=" 4 ", shift=5.0)}, "lineHeight": "12"}
        )

        self.assertEqual(
            (metadata.glyphs[0].x, metadata.glyphs[0].y, metadata.glyphs[0].width, metadata.glyphs[0].shift),
            (3, 2, 4, 5),
        )
        self.assertEqual(metadata.line_height, 12)

    def test_rejects_invalid_glyph_entries_and_keeps_valid_ones(self) -> None:
        metadata = _metadata(
            {
                "glyphs": {
                    "65": _glyph_document(),
                    "66": _glyph_document(w=-1),
                    "67": _glyph_document(x=1.5),
                    "68": _glyph_document(shift=True),
                    "69": {"x": 1, "y": 1, "w": 2, "h": 2, "shift": 3},
                    "0": _glyph_document(),
                    "not-a-code": _glyph_document(),
                    "70": "glyph",
                }
            }
        )

        self.assertEqual([glyph.code for glyph in metadata.glyphs], [65])
        self.assertEqual(
            sorted(metadata.rejected_glyph_keys),
            ["0", "66", "67", "68", "69", "70", "not-a-code"],
        )

    def test_fonts_without_usable_glyph_data_have_no_atlas_metadata(self) -> None:
        empty: tuple[object, ...] = ({}, [], None, {"65": _glyph_document(h=-2)})
        for glyphs in empty:
            with self.subTest(glyphs=glyphs):
                self.assertIsNone(
                    parse_gamemaker_font_atlas_metadata(_json_object({"glyphs": glyphs}))
                )

    def test_kerning_pairs_follow_apply_kerning_and_present_glyphs(self) -> None:
        kerning = ((65, 86, -2), (86, 65, 0), (65, 300, -1), (84, 111, 3))
        kerned = self._plan(
            write_gamemaker_font(self.project_dir, "fnt_kerned", kerning=kerning, apply_kerning=True)
        )
        unkerned = self._plan(
            write_gamemaker_font(self.project_dir, "fnt_plain", kerning=kerning, apply_kerning=False)
        )

        self.assertEqual(
            [(pair.first, pair.second, pair.amount) for pair in kerned.kerning_pairs],
            [(65, 86, -2), (84, 111, 3)],
        )
        self.assertEqual(len(unkerned.metadata.kerning_pairs), 4)
        self.assertEqual(unkerned.kerning_pairs, ())

    def test_font_registry_metadata_keeps_points_and_bitmap_flag(self) -> None:
        document = _json_object(
            {"fontName": "Roboto", "size": 11.5, "bold": True, "italic": 0, "usesSDF": True}
        )

        self.assertEqual(
            font_registry_metadata(document, bitmap=True),
            {
                "font_name": "Roboto",
                "size": 11.5,
                "bold": True,
                "italic": False,
                "sdf": True,
                "bitmap": True,
            },
        )
        self.assertEqual(font_registry_metadata({}, bitmap=False)["size"], 12.0)

    def test_atlas_image_name_matches_gamemaker_layout(self) -> None:
        self.assertEqual(font_atlas_image_name("fonts/fnt_ui/fnt_ui.yy"), "fnt_ui.png")


class TestPlanGameMakerFontAtlas(FontAtlasTestCase):
    def test_plan_reads_image_header_and_keeps_inside_glyphs(self) -> None:
        font = write_gamemaker_font(self.project_dir, "fnt_ui", codes=(65, 66))
        assert font.atlas_path is not None
        document = dict(font.document)
        document["glyphs"] = {
            "65": _glyph_document(x=1, y=1, w=4, h=6),
            "66": _glyph_document(x=250, y=1, w=8, h=6),
        }

        plan = plan_gamemaker_font_atlas(_metadata(document), font.atlas_path)

        assert plan is not None
        with Image.open(font.atlas_path) as atlas:
            self.assertEqual((plan.image_width, plan.image_height), atlas.size)
        self.assertEqual(plan.image_mode, "RGBA")
        self.assertEqual([glyph.code for glyph in plan.glyphs], [65])
        self.assertEqual(plan.out_of_bounds_glyph_codes, (66,))

    def test_missing_unreadable_or_mismatched_atlas_has_no_plan(self) -> None:
        font = write_gamemaker_font(self.project_dir, "fnt_ui", codes=(65,))
        metadata = _metadata(font.document)
        unreadable = os.path.join(self.project_dir, "broken.png")
        with open(unreadable, "wb") as handle:
            handle.write(b"not a png")
        tiny = os.path.join(self.project_dir, "tiny.png")
        Image.new("RGBA", (2, 2)).save(tiny)

        self.assertIsNone(plan_gamemaker_font_atlas(metadata, os.path.join(self.project_dir, "absent.png")))
        self.assertIsNone(plan_gamemaker_font_atlas(metadata, unreadable))
        self.assertIsNone(plan_gamemaker_font_atlas(metadata, tiny))


class TestRenderBMFont(FontAtlasTestCase):
    def test_descriptor_encodes_gamemaker_glyph_table(self) -> None:
        font = write_gamemaker_font(
            self.project_dir,
            "fnt_ui",
            kerning=((65, 86, -2), (84, 111, 1)),
            apply_kerning=True,
            ascender=10,
            ascender_offset=3,
            line_height=15,
            size=12.5,
        )
        plan = self._plan(font)

        text = render_bmfont_text(plan, "fnt_ui.png")

        info = _bmfont_record(text, "info")
        common = _bmfont_record(text, "common")
        self.assertEqual((info["face"], info["size"], info["unicode"]), ("Synthetic Sans", "13", "1"))
        self.assertEqual((info["padding"], info["spacing"], info["outline"]), ("0,0,0,0", "0,0", "0"))
        self.assertEqual(
            (common["lineHeight"], common["base"], common["pages"], common["packed"]),
            ("15", "10", "1", "0"),
        )
        self.assertEqual((int(common["scaleW"]), int(common["scaleH"])), (plan.image_width, plan.image_height))
        self.assertEqual(_bmfont_record(text, "page"), {"id": "0", "file": "fnt_ui.png"})
        self.assertEqual(_bmfont_record(text, "chars"), {"count": str(len(font.glyphs))})
        chars = _bmfont_chars(text)
        self.assertEqual(set(chars), set(font.glyphs))
        for code, glyph in font.glyphs.items():
            self.assertEqual(
                chars[code],
                {
                    "id": code,
                    "x": glyph.x,
                    "y": glyph.y,
                    "width": glyph.w,
                    "height": glyph.h,
                    "xoffset": glyph.offset,
                    "yoffset": -3,
                    "xadvance": glyph.shift,
                    "page": 0,
                    "chnl": 15,
                },
            )
        self.assertEqual(_bmfont_record(text, "kernings"), {"count": "2"})
        self.assertEqual(_bmfont_kernings(text), {(65, 86): -2, (84, 111): 1})

    def test_unkerned_descriptor_has_no_kerning_block(self) -> None:
        font = write_gamemaker_font(self.project_dir, "fnt_ui", kerning=((65, 86, -2),))

        text = render_bmfont_text(self._plan(font), "page.png")

        self.assertNotIn("kerning", text)

    def test_sdf_spread_moves_glyph_origins_like_the_runner(self) -> None:
        plan = self._plan(
            write_gamemaker_font(
                self.project_dir,
                "fnt_ui",
                codes=(65,),
                uses_sdf=True,
                sdf_spread=4,
                ascender_offset=1,
            )
        )

        char = _bmfont_chars(render_bmfont_text(plan, "page.png"))[65]

        self.assertEqual((char["xoffset"], char["yoffset"]), (plan.glyphs[0].offset - 4, -5))

    def test_face_name_is_sanitized(self) -> None:
        plan = self._plan(
            write_gamemaker_font(
                self.project_dir,
                "fnt_ui",
                codes=(65,),
                overrides={"fontName": 'Odd "Face"\n'},
            )
        )

        self.assertEqual(_bmfont_record(render_bmfont_text(plan, "page.png"), "info")["face"], "Odd Face")

    def test_fixed_size_rounds_gamemaker_points_half_up(self) -> None:
        for size, expected in ((12.0, 12), (12.5, 13), (11.49, 11), (0.2, 1)):
            with self.subTest(size=size):
                metadata = _metadata({"glyphs": {"65": _glyph_document()}, "size": size})
                self.assertEqual(bmfont_fixed_size(metadata), expected)

    def test_base_is_ascender_when_it_fits_the_line(self) -> None:
        for ascender, line_height, expected in ((9, 14, 9), (0, 14, 14), (20, 14, 14), (14, 14, 14)):
            with self.subTest(ascender=ascender, line_height=line_height):
                metadata = _metadata(
                    {"glyphs": {"65": _glyph_document()}, "ascender": ascender, "lineHeight": line_height}
                )
                self.assertEqual(bmfont_base(metadata), expected)

    def test_descriptor_places_glyphs_where_gamemaker_draws_them(self) -> None:
        """Godot puts a BMFont glyph at pen + (xoffset, yoffset - base) from the baseline."""
        font = write_gamemaker_font(
            self.project_dir,
            "fnt_ui",
            kerning=((65, 86, -2), (86, 65, 1), (84, 111, -1)),
            apply_kerning=True,
            ascender=8,
            ascender_offset=2,
        )
        plan = self._plan(font)
        text = render_bmfont_text(plan, "page.png")
        chars = _bmfont_chars(text)
        kernings = _bmfont_kernings(text)
        common = _bmfont_record(text, "common")
        base = int(common["base"])
        line_height = int(common["lineHeight"])
        reference = font.reference()
        sample = "AVA To\nVAT ~|"

        expected = reference.quads(17.5, 40.25, sample, halign=FA_CENTER, valign=FA_MIDDLE)

        actual: list[ReferenceQuad] = []
        for line, (line_x, line_y) in zip(
            reference.split(sample),
            reference.line_origins(sample, halign=FA_CENTER, valign=FA_MIDDLE),
            strict=True,
        ):
            pen_x = math.ceil(17.5 + line_x - 0.5)
            baseline = math.ceil(40.25 + line_y - 0.5) + base
            previous: int | None = None
            for char in line:
                code = ord(char)
                if previous is not None:
                    pen_x += kernings.get((previous, code), 0)
                previous = code
                glyph = chars[code]
                if glyph["width"] * glyph["height"]:
                    actual.append(
                        ReferenceQuad(
                            code=code,
                            left=pen_x + glyph["xoffset"],
                            top=baseline + glyph["yoffset"] - base,
                            w=glyph["width"],
                            h=glyph["height"],
                            atlas_x=glyph["x"],
                            atlas_y=glyph["y"],
                        )
                    )
                pen_x += glyph["xadvance"]
        self.assertEqual(actual, expected)
        self.assertEqual(line_height, reference.line_height)

    def test_import_settings_keep_native_glyph_size(self) -> None:
        config = render_bmfont_import_config('res://fonts/ui "font".fnt')

        self.assertIn('importer="font_data_bmfont"\n', config)
        self.assertIn('type="FontFile"\n', config)
        self.assertIn(f"source_file={json.dumps('res://fonts/ui \"font\".fnt')}\n", config)
        self.assertIn("scaling_mode=0\n", config)
        self.assertIn("fallbacks=[]\n", config)
        self.assertEqual(render_skipped_import_config(), '[remap]\n\nimporter="skip"\n')


class TestBuildFontAtlasImage(FontAtlasTestCase):
    def _plan_for_image(self, image: Image.Image, **document: object) -> GameMakerFontAtlasPlan:
        path = os.path.join(self.project_dir, "page.png")
        image.save(path)
        fields: dict[str, object] = {"glyphs": {"65": _glyph_document(x=0, y=0, w=1, h=1)}}
        fields.update(document)
        plan = plan_gamemaker_font_atlas(_metadata(fields), path)
        assert plan is not None
        return plan

    def test_rgba_atlas_is_copied_unchanged(self) -> None:
        self.assertIsNone(build_font_atlas_image(self._plan_for_image(Image.new("RGBA", (4, 4)))))

    def test_other_png_modes_become_rgba_with_identical_pixels(self) -> None:
        source = Image.new("LA", (4, 4), (255, 0))
        source.putpixel((1, 1), (255, 200))
        source.putpixel((2, 1), (128, 255))

        converted = build_font_atlas_image(self._plan_for_image(source))

        assert converted is not None
        self.assertEqual(converted.mode, "RGBA")
        self.assertEqual(converted.tobytes(), source.convert("RGBA").tobytes())

    def test_sdf_distance_is_resolved_to_native_size_coverage(self) -> None:
        distances = (0, 100, 120, 128, 135, 160, 255)
        source = Image.new("RGBA", (len(distances), 1), (255, 255, 255, 0))
        for column, distance in enumerate(distances):
            source.putpixel((column, 0), (255, 255, 255, distance))

        converted = build_font_atlas_image(
            self._plan_for_image(source, usesSDF=True, sdfSpread=8)
        )

        # The runner's shader smooths over 0.4 / sdfSpread around the 0.5 edge.
        assert converted is not None
        self.assertEqual(
            [converted.getpixel((column, 0)) for column in range(len(distances))],
            [(255, 255, 255, alpha) for alpha in (0, 0, 28, 135, 227, 255, 255)],
        )

    def test_sdf_distance_in_colour_channels_is_used_when_alpha_is_flat(self) -> None:
        source = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
        source.putpixel((1, 0), (255, 255, 255, 255))

        converted = build_font_atlas_image(self._plan_for_image(source, usesSDF=True, sdfSpread=4))

        assert converted is not None
        pixels = [converted.getpixel((column, 0)) for column in range(2)]
        self.assertEqual(pixels, [(255, 255, 255, 0), (255, 255, 255, 255)])

    def test_glyph_cells_can_reference_the_whole_image(self) -> None:
        plan = self._plan_for_image(
            Image.new("RGBA", (3, 2)),
            glyphs={"65": _glyph_document(x=0, y=0, w=3, h=2)},
        )

        self.assertEqual(
            plan.glyphs,
            (GameMakerFontGlyph(code=65, x=0, y=0, width=3, height=2, shift=5, offset=0),),
        )


if __name__ == "__main__":
    unittest.main()
