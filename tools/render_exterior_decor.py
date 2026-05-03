"""Render multiple exterior views to validate coral/rock/treasure layout.

Outputs to build/exterior_<view>.png
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import glfw
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_RGBA,
    GL_UNSIGNED_BYTE,
    glClear,
    glClearColor,
    glEnable,
    glReadPixels,
    glViewport,
)
from PIL import Image

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from camera import Camera  # noqa: E402
from scene import Scene  # noqa: E402
from utils import perspective  # noqa: E402


VIEWS = [
    # name, position, yaw_deg, pitch
    ("topdown",   (0.0,  60.0,  0.0),  -90.0, -1.55),
    ("iso_ne",    (45.0, 25.0,  45.0), -135.0, -0.35),
    ("iso_sw",    (-45.0, 22.0, -45.0),  45.0, -0.35),
    ("low_east",  (50.0,  6.0,  10.0), -170.0, -0.05),
    ("low_west",  (-50.0, 6.0,  -10.0),  10.0, -0.05),
    ("close_side", (22.0,  3.5,  14.0), -150.0, -0.20),
]


def main() -> int:
    if not glfw.init():
        return 1
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)

    W, H = 1280, 720
    win = glfw.create_window(W, H, "exterior-decor", None, None)
    if not win:
        glfw.terminate()
        return 1
    glfw.make_context_current(win)

    glClearColor(0.02, 0.05, 0.10, 1.0)
    glEnable(GL_DEPTH_TEST)
    glViewport(0, 0, W, H)

    scene = Scene()
    proj = perspective(60.0, W / H, 0.1, 600.0)
    out_dir = Path(__file__).resolve().parent.parent / "build"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, pos, yaw_deg, pitch in VIEWS:
        cam = Camera(position=pos, yaw=math.radians(yaw_deg), pitch=pitch)

        for _ in range(2):
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            scene.draw(cam.view_matrix(), proj)
            glfw.swap_buffers(win)
            glfw.poll_events()

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        scene.draw(cam.view_matrix(), proj)
        pixels = glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE)
        glfw.swap_buffers(win)

        img = Image.frombytes("RGBA", (W, H), pixels).transpose(Image.FLIP_TOP_BOTTOM)
        out = out_dir / f"exterior_{name}.png"
        img.save(out)
        print(f"[render] wrote {out}")

    glfw.destroy_window(win)
    glfw.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
