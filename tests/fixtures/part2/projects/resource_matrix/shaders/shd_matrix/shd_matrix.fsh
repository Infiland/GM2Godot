precision highp float;
varying vec2 v_vTexcoord;
varying vec4 v_vColour;
uniform sampler2D gm_BaseTexture;
uniform vec4 tint;

void main() {
    gl_FragColor = texture2D(gm_BaseTexture, v_vTexcoord) * v_vColour * tint;
}
