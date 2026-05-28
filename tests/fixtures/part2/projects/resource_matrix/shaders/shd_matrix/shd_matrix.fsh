precision highp float;
varying vec2 v_vTexcoord;
uniform sampler2D gm_BaseTexture;

void main() {
    gl_FragColor = texture2D(gm_BaseTexture, v_vTexcoord);
}
