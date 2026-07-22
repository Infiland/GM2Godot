precision mediump float;

varying vec2 v_vTexcoord;
varying vec4 v_vColour;

uniform sampler2D
    gm_BaseTexture;
uniform vec4 tint,
             channel_weights[2];

void main()
{
    vec4 sampled = texture2D(gm_BaseTexture, v_vTexcoord);
    gl_FragColor = sampled * v_vColour * tint
        * mix(channel_weights[0], channel_weights[1], sampled.a);
}
