#version 330 core

in vec3 vDir;
out vec4 FragColor;

uniform sampler2D uPanorama;

const float PI = 3.14159265359;

void main() {
    vec3 d = normalize(vDir);
    // Equirectangular sampling: longitude on x, latitude on y.
    float u = atan(d.z, d.x) / (2.0 * PI) + 0.5;
    float v = 0.5 - asin(clamp(d.y, -1.0, 1.0)) / PI;
    FragColor = texture(uPanorama, vec2(u, v));
}
