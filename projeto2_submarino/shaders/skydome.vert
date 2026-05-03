#version 330 core

layout(location = 0) in vec3 aPos;

uniform mat4 uView;
uniform mat4 uProj;

out vec3 vDir;

void main() {
    // Anchor the dome to the camera so you can never reach its border.
    mat4 view = uView;
    view[0][3] = 0.0;
    view[1][3] = 0.0;
    view[2][3] = 0.0;
    vDir = aPos;
    vec4 pos = uProj * view * vec4(aPos, 1.0);
    // Keep z = w so the dome sits at the far plane.
    gl_Position = pos.xyww;
}
