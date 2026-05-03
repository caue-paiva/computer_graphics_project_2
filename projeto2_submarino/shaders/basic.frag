#version 330 core

in vec2 vUV;
out vec4 FragColor;

uniform sampler2D uDiffuse;
uniform float uUVTile;

void main() {
    vec2 uv = vUV * uUVTile;
    FragColor = texture(uDiffuse, uv);
}
