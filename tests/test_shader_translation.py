from __future__ import annotations

import unittest

from src.conversion.shader_translation import (
    ShaderStageSource,
    translate_gamemaker_shader,
)


VERTEX_PREAMBLE = """\
attribute vec3 in_Position;
attribute vec4 in_Colour;
attribute vec2 in_TextureCoord;
varying vec2 v_uv;
varying vec4 v_color;
"""


class TestGameMakerShaderTranslation(unittest.TestCase):
    def test_translates_multiline_comma_and_array_declarations(self) -> None:
        vertex = """\
precision highp float;
attribute
    highp vec3
    in_Position;
attribute vec4 in_Colour;
attribute vec2 in_TextureCoord;
varying highp vec2
    v_uv,
    v_offsets[2];
varying vec4 v_color;
uniform float amount,
    weights[3];
const float gain = 1.0,
    bias = 0.25;

void main()
{
    vec4 local_position = vec4(in_Position.xy + vec2(amount), in_Position.z, 1.0);
    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION] * local_position;
    v_uv = in_TextureCoord;
    v_offsets[0] = in_TextureCoord + vec2(weights[0]);
    v_offsets[1] = in_TextureCoord + vec2(weights[1]);
    v_color = in_Colour * gain + vec4(bias);
}
"""
        fragment = """\
precision mediump float;
varying highp vec2 v_uv, v_offsets[2];
varying vec4 v_color;
uniform float amount, weights[3];
uniform sampler2D
    gm_BaseTexture,
    overlay;

void main()
{
    vec4 base = texture2D(gm_BaseTexture, v_uv + v_offsets[0] * amount);
    gl_FragColor = base * v_color + texture2D(overlay, v_offsets[1]) * weights[2];
}
"""

        result = translate_gamemaker_shader(
            (
                ShaderStageSource("vertex", vertex),
                ShaderStageSource("fragment", fragment),
            )
        )

        self.assertEqual(result.issues, ())
        self.assertIsNotNone(result.source)
        source = result.source or ""
        self.assertNotIn("attribute", source)
        self.assertNotIn("gm_BaseTexture", source)
        self.assertNotIn("gm_Matrices", source)
        self.assertNotIn("gl_Position", source)
        self.assertNotIn("gl_FragColor", source)
        self.assertNotIn("texture2D", source)
        self.assertEqual(source.count("varying highp vec2 v_uv;"), 1)
        self.assertEqual(source.count("varying highp vec2 v_offsets[2];"), 1)
        self.assertEqual(source.count("uniform float amount;"), 1)
        self.assertEqual(source.count("uniform float weights[3];"), 1)
        self.assertIn("uniform sampler2D overlay;", source)
        self.assertIn("const float gain = 1.0;", source)
        self.assertIn("const float bias = 0.25;", source)
        self.assertIn("VERTEX = (local_position).xy;", source)
        self.assertIn("vec3(VERTEX, 0.0).xy", source)
        self.assertIn("v_uv = UV;", source)
        self.assertIn("v_color = COLOR", source)
        self.assertIn("COLOR = base * v_color", source)
        self.assertIn("texture(TEXTURE, v_uv", source)

    def test_maps_supported_matrix_constants_without_time_name_heuristics(
        self,
    ) -> None:
        vertex = VERTEX_PREAMBLE + """\
uniform float u_fTime;
void main()
{
    mat4 world = gm_Matrices[MATRIX_WORLD];
    mat4 view = gm_Matrices[MATRIX_VIEW];
    mat4 projection = gm_Matrices[MATRIX_PROJECTION];
    mat4 world_view = gm_Matrices[MATRIX_WORLD_VIEW];
    vec4 local_position = vec4(in_Position.xy + vec2(u_fTime), 0.0, 1.0);
    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION] * local_position;
    v_uv = in_TextureCoord;
    v_color = in_Colour;
}
"""
        fragment = """\
varying vec2 v_uv;
varying vec4 v_color;
uniform float u_fTime;
void main()
{
    gl_FragColor = v_color * texture2D(gm_BaseTexture, v_uv + vec2(u_fTime));
}
"""

        result = translate_gamemaker_shader(
            (
                ShaderStageSource("vertex", vertex),
                ShaderStageSource("fragment", fragment),
            )
        )

        self.assertEqual(result.issues, ())
        source = result.source or ""
        self.assertIn("mat4 world = MODEL_MATRIX;", source)
        self.assertIn("mat4 view = CANVAS_MATRIX;", source)
        self.assertIn("mat4 projection = SCREEN_MATRIX;", source)
        self.assertIn(
            "mat4 world_view = (CANVAS_MATRIX * MODEL_MATRIX);",
            source,
        )
        self.assertEqual(source.count("uniform float u_fTime;"), 1)
        self.assertGreaterEqual(source.count("u_fTime"), 3)
        self.assertNotIn("TIME", source)

    def test_accepts_explicit_projection_view_world_position_chain(self) -> None:
        vertex = """\
attribute vec3 in_Position;
void main()
{
    gl_Position =
        gm_Matrices[MATRIX_PROJECTION]
        * gm_Matrices[MATRIX_VIEW]
        * gm_Matrices[MATRIX_WORLD]
        * vec4(in_Position, 1.0);
}
"""
        result = translate_gamemaker_shader(
            (ShaderStageSource("vertex", vertex),)
        )

        self.assertEqual(result.issues, ())
        self.assertIn(
            "VERTEX = (vec4 ( vec3(VERTEX, 0.0) , 1.0 )).xy;",
            result.source or "",
        )

    def test_rejects_custom_and_normal_attributes_when_referenced(self) -> None:
        vertex = """\
attribute vec3 in_Position;
attribute vec3 in_Normal;
attribute vec2 in_CustomTexcoord;
void main()
{
    vec2 offset = in_Normal.xy + in_CustomTexcoord;
    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION]
        * vec4(in_Position.xy + offset, 0.0, 1.0);
}
"""

        result = translate_gamemaker_shader(
            (ShaderStageSource("vertex", vertex),)
        )

        self.assertIsNone(result.source)
        self.assertEqual(
            {issue.code for issue in result.issues},
            {"GM2GD-SHADER-ATTRIBUTE-UNSUPPORTED"},
        )
        self.assertEqual(
            {issue.construct for issue in result.issues},
            {"in_Normal", "in_CustomTexcoord"},
        )

    def test_rejects_clip_space_position_without_supported_matrix_chain(
        self,
    ) -> None:
        vertex = """\
attribute vec3 in_Position;
void main()
{
    gl_Position = vec4(in_Position, 1.0);
}
"""

        result = translate_gamemaker_shader(
            (ShaderStageSource("vertex", vertex),)
        )

        self.assertIsNone(result.source)
        issue = next(
            issue
            for issue in result.issues
            if issue.code == "GM2GD-SHADER-POSITION-UNSUPPORTED"
        )
        self.assertEqual((issue.line, issue.column), (4, 19))
        self.assertIn("world/view/projection", issue.message)

    def test_rejects_unlinked_fragment_varying(self) -> None:
        fragment = """\
varying vec2 v_uv;
void main()
{
    gl_FragColor = texture2D(gm_BaseTexture, v_uv);
}
"""

        result = translate_gamemaker_shader(
            (ShaderStageSource("fragment", fragment),)
        )

        self.assertIsNone(result.source)
        self.assertEqual(
            [issue.code for issue in result.issues],
            ["GM2GD-SHADER-VARYING-UNLINKED"],
        )
        self.assertEqual(result.issues[0].construct, "v_uv")

    def test_rejects_incompatible_cross_stage_declarations(self) -> None:
        vertex = """\
attribute vec3 in_Position;
varying vec2 v_uv;
uniform float amount;
void main()
{
    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION] * vec4(in_Position, 1.0);
    v_uv = vec2(amount);
}
"""
        fragment = """\
varying vec3 v_uv;
uniform vec2 amount;
void main()
{
    gl_FragColor = vec4(v_uv, amount.x);
}
"""

        result = translate_gamemaker_shader(
            (
                ShaderStageSource("vertex", vertex),
                ShaderStageSource("fragment", fragment),
            )
        )

        self.assertIsNone(result.source)
        conflicts = [
            issue
            for issue in result.issues
            if issue.code == "GM2GD-SHADER-DECLARATION-CONFLICT"
        ]
        self.assertEqual(
            {issue.construct for issue in conflicts},
            {"v_uv", "amount"},
        )

    def test_rejects_godot_builtin_names_and_scalar_matrix_constructors(
        self,
    ) -> None:
        fragment = """\
const float PI = 3.14159265359;
const mat4 colour_matrix = mat4(
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0
);
void main()
{
    mat2 local_matrix = mat2(1.0, 0.0, 0.0, 1.0);
    gl_FragColor = vec4(local_matrix[0], PI, colour_matrix[0][0]);
}
"""

        result = translate_gamemaker_shader(
            (ShaderStageSource("fragment", fragment),)
        )

        self.assertIsNone(result.source)
        self.assertIn(
            "GM2GD-SHADER-DECLARATION-UNSUPPORTED",
            {issue.code for issue in result.issues},
        )
        self.assertIn(
            "GM2GD-SHADER-CONSTRUCTOR-UNSUPPORTED",
            {issue.code for issue in result.issues},
        )

    def test_rejects_preprocessor_directive(self) -> None:
        fragment = """\
#define OUTPUT_COLOUR vec4(1.0)
void main()
{
    gl_FragColor = OUTPUT_COLOUR;
}
"""

        result = translate_gamemaker_shader(
            (ShaderStageSource("fragment", fragment),)
        )

        self.assertIsNone(result.source)
        self.assertEqual(
            {issue.code for issue in result.issues},
            {"GM2GD-SHADER-CONSTRUCT-UNSUPPORTED"},
        )

    def test_rejects_stage_builtin_access_inside_fragment_helper(self) -> None:
        fragment = """\
vec4 sample_base(vec2 uv)
{
    return texture2D(gm_BaseTexture, uv);
}
void main()
{
    gl_FragColor = sample_base(vec2(0.5));
}
"""

        result = translate_gamemaker_shader(
            (ShaderStageSource("fragment", fragment),)
        )

        self.assertIsNone(result.source)
        helper_issues = [
            issue
            for issue in result.issues
            if issue.code == "GM2GD-SHADER-HELPER-UNSUPPORTED"
        ]
        self.assertEqual(len(helper_issues), 1, helper_issues)
        self.assertEqual(
            helper_issues[0].construct,
            "sample_base:gm_BaseTexture",
        )

    def test_declaration_like_comments_do_not_change_parser_results(self) -> None:
        vertex = """\
// attribute vec3 fake;
/* varying vec4 also_fake, second_fake[2]; */
attribute vec3 in_Position;
void main()
{
    // gl_Position = vec4(0.0);
    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION] * vec4(in_Position, 1.0);
}
"""

        result = translate_gamemaker_shader(
            (ShaderStageSource("vertex", vertex),)
        )

        self.assertEqual(result.issues, ())
        source = result.source or ""
        self.assertIn("// attribute vec3 fake;", source)
        self.assertIn("/* varying vec4 also_fake, second_fake[2]; */", source)
        self.assertIn("// gl_Position = vec4(0.0);", source)


if __name__ == "__main__":
    unittest.main()
