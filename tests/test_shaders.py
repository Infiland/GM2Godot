import os
import sys
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.shaders import ShaderConverter

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
        self.logs = []

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
        self.logs = []
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


class TestShaderConverterSubfolders(unittest.TestCase):
    """Test that shaders respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

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

        expected = os.path.join(self.godot_dir, "shaders", "Effects", "sh_blur.gdshader")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected shader at {expected}")


if __name__ == "__main__":
    unittest.main()
