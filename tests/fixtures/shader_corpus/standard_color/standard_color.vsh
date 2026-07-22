precision highp float;

attribute
    vec3
    in_Position;
attribute vec4 in_Colour;
attribute vec2 in_TextureCoord;

varying vec2
    v_vTexcoord;
varying vec4 v_vColour;

uniform float x_offset,
              weights[2];

void main()
{
    vec4 local_position = vec4(
        in_Position.xy + vec2(x_offset * weights[0], 0.0),
        in_Position.z,
        1.0
    );
    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION] * local_position;
    v_vTexcoord = in_TextureCoord;
    v_vColour = in_Colour;
}
