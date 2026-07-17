import json
import os
import sys
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.shaders import ShaderConverter
from src.conversion.asset_output_paths import build_asset_output_paths

SAMPLE_FSH = """\
precision highp float;
varying vec2 v_vTexcoord;
varying vec4 v_vColour;
uniform sampler2D gm_BaseTexture;

void main()
{
    vec4 col = texture2D(gm_BaseTexture, v_vTexcoord);
    gl_FragColor = col * v_vColour;
}
"""


class TestShaderConverterBasic(unittest.TestCase):
    """Test ShaderConverter converts .fsh files to .gdshader."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        shaders_dir = os.path.join(self.gm_dir, "shaders")
        os.makedirs(shaders_dir)

        self.fsh_path = os.path.join(shaders_dir, "test_shader.fsh")
        with open(self.fsh_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_FSH)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return ShaderConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_creates_gdshader_file(self):
        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

    def test_gl_fragcolor_converted_to_color(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("gl_FragColor", content)
        self.assertIn("COLOR", content)

    def test_texture2d_converted_to_texture(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("texture2D", content)
        self.assertIn("texture(", content)

    def test_precision_replaced_with_shader_type(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("precision highp float", content)
        self.assertIn("shader_type canvas_item", content)

    def test_main_replaced_with_fragment(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("void main()", content)
        self.assertIn("void fragment()", content)

    def test_gm_base_texture_replaced(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("gm_BaseTexture", content)
        self.assertIn("TEXTURE", content)


class TestShaderConverterEmpty(unittest.TestCase):
    """No shaders directory should not crash."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        # No shaders directory created

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_no_shaders_dir_no_crash(self):
        converter = ShaderConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise
        self.assertTrue(len(self.logs) > 0,
                        "Expected log message when shaders directory missing")


class TestShaderGeneratedPathCollisions(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        for resource_name, marker in (("shdGlow", "MARKER_ONE"), ("shd_glow", "MARKER_TWO")):
            shader_dir = os.path.join(self.gm_dir, "shaders", resource_name)
            os.makedirs(shader_dir)
            with open(os.path.join(shader_dir, resource_name + ".yy"), "w", encoding="utf-8") as yy_file:
                yy_file.write(
                    '{"name":"' + resource_name
                    + '","parent":{"name":"Shaders","path":"folders/Shaders.yy"}}'
                )
            with open(os.path.join(shader_dir, resource_name + ".fsh"), "w", encoding="utf-8") as shader_file:
                shader_file.write(SAMPLE_FSH + "\n// " + marker + "\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_emitted_shaders_match_collision_safe_registry_paths(self) -> None:
        converter = ShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        paths = build_asset_output_paths(self.gm_dir, self.godot_dir)["shaders"]
        self.assertEqual(len({path.casefold() for path in paths.values()}), 2)
        contents: list[str] = []
        for resource_name in ("shdGlow", "shd_glow"):
            output_path = os.path.join(
                self.godot_dir,
                *paths[resource_name].removeprefix("res://").split("/"),
            )
            with open(output_path, encoding="utf-8") as shader_file:
                contents.append(shader_file.read())
        self.assertIn("MARKER_ONE", contents[0])
        self.assertIn("MARKER_TWO", contents[1])


class TestShaderAssetOwnershipAndStages(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_shader_asset(
        self,
        resource_name: str,
        *,
        vertex_source: str | None = None,
        fragment_source: str | None = None,
    ) -> str:
        shader_dir = os.path.join(self.gm_dir, "shaders", resource_name)
        os.makedirs(shader_dir)
        yy_path = os.path.join(shader_dir, resource_name + ".yy")
        with open(yy_path, "w", encoding="utf-8") as yy_file:
            json.dump(
                {
                    "name": resource_name,
                    "resourceType": "GMShader",
                    "parent": {
                        "name": "Shaders",
                        "path": "folders/Shaders.yy",
                    },
                },
                yy_file,
            )
        if vertex_source is not None:
            with open(
                os.path.join(shader_dir, resource_name + ".vsh"),
                "w",
                encoding="utf-8",
            ) as vertex_file:
                vertex_file.write(vertex_source)
        if fragment_source is not None:
            with open(
                os.path.join(shader_dir, resource_name + ".fsh"),
                "w",
                encoding="utf-8",
            ) as fragment_file:
                fragment_file.write(fragment_source)
        return f"shaders/{resource_name}/{resource_name}.yy"

    def _write_yyp(self, resources: list[tuple[str, str]]) -> None:
        with open(
            os.path.join(self.gm_dir, "ShaderOwnership.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "%Name": "Shader Ownership",
                    "resources": [
                        {"id": {"name": name, "path": path}}
                        for name, path in resources
                    ],
                },
                project_file,
            )

    def _convert(self) -> None:
        ShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=2,
        ).convert_all()

    def test_dual_stage_asset_publishes_one_complete_shader(self) -> None:
        vertex_source = """\
precision highp float;
varying vec2 v_shared;
uniform float amount;

void main()
{
    v_shared = vec2(amount);
}
// VERTEX_MARKER
"""
        fragment_source = """\
precision mediump float;
varying vec2 v_shared;
uniform float amount;

void main()
{
    gl_FragColor = vec4(v_shared, amount, 1.0);
}
// FRAGMENT_MARKER
"""
        shader_path = self._write_shader_asset(
            "shdPair",
            vertex_source=vertex_source,
            fragment_source=fragment_source,
        )
        self._write_yyp([("shdPair", shader_path)])

        self._convert()

        resource_path = build_asset_output_paths(
            self.gm_dir,
            self.godot_dir,
        )["shaders"]["shdPair"]
        output_path = os.path.join(
            self.godot_dir,
            *resource_path.removeprefix("res://").split("/"),
        )
        with open(output_path, encoding="utf-8") as shader_file:
            content = shader_file.read()

        self.assertEqual(content.count("shader_type canvas_item;"), 1)
        self.assertEqual(content.count("varying vec2 v_shared;"), 1)
        self.assertEqual(content.count("uniform float amount;"), 1)
        self.assertEqual(content.count("void vertex()"), 1)
        self.assertEqual(content.count("void fragment()"), 1)
        self.assertIn("VERTEX_MARKER", content)
        self.assertIn("FRAGMENT_MARKER", content)
        self.assertNotIn("precision ", content)

    def test_yyp_ownership_excludes_orphan_normalized_path_collision(self) -> None:
        referenced_path = self._write_shader_asset(
            "shdGlow",
            fragment_source=SAMPLE_FSH + "\n// REFERENCED_MARKER\n",
        )
        self._write_shader_asset(
            "shd_glow",
            fragment_source=SAMPLE_FSH + "\n// ORPHAN_MARKER\n",
        )
        self._write_yyp([("shdGlow", referenced_path)])

        self._convert()

        paths = build_asset_output_paths(self.gm_dir, self.godot_dir)["shaders"]
        self.assertEqual(set(paths), {"shdGlow"})
        output_path = os.path.join(
            self.godot_dir,
            *paths["shdGlow"].removeprefix("res://").split("/"),
        )
        with open(output_path, encoding="utf-8") as shader_file:
            content = shader_file.read()
        self.assertIn("REFERENCED_MARKER", content)
        self.assertNotIn("ORPHAN_MARKER", content)
        generated_shaders = [
            os.path.join(root, filename)
            for root, _directories, filenames in os.walk(
                os.path.join(self.godot_dir, "shaders")
            )
            for filename in filenames
            if filename.endswith(".gdshader")
        ]
        self.assertEqual(generated_shaders, [output_path])


class TestShaderConverterSubfolders(unittest.TestCase):
    """Test that shaders respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create a shader in a named directory with a .yy specifying subfolder
        shader_dir = os.path.join(self.gm_dir, "shaders", "sh_blur")
        os.makedirs(shader_dir)
        with open(os.path.join(shader_dir, "sh_blur.fsh"), "w") as f:
            f.write(SAMPLE_FSH)
        with open(os.path.join(shader_dir, "sh_blur.yy"), "w") as f:
            f.write('{"name": "sh_blur", "parent": {"name": "Effects", "path": "folders/Shaders/Effects.yy",},}')

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_shader_in_subfolder(self):
        converter = ShaderConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "shaders", "effects", "sh_blur.gdshader")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected shader at {expected}")


if __name__ == "__main__":
    unittest.main()
