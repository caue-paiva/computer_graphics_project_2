"""Headless-ish smoke test: open a hidden GLFW window, build the scene,
render a single frame, then exit. Used to verify there are no runtime
errors in shader compilation, asset loading or buffer setup before
launching the full app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import glfw
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    glClear,
    glClearColor,
    glEnable,
    glViewport,
)


SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from camera import Camera  # noqa: E402
from scene import Scene  # noqa: E402
from utils import perspective  # noqa: E402


def main() -> int:
    if not glfw.init():
        print("FAIL: glfw.init")
        return 1
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)

    win = glfw.create_window(640, 360, "smoke", None, None)
    if not win:
        glfw.terminate()
        print("FAIL: glfw.create_window")
        return 1
    glfw.make_context_current(win)

    glClearColor(0.0, 0.0, 0.0, 1.0)
    glEnable(GL_DEPTH_TEST)
    glViewport(0, 0, 640, 360)

    print("[smoke] building scene…")
    scene = Scene()
    cam = Camera(position=(0.0, 4.0, 28.0))
    proj = perspective(60.0, 640.0 / 360.0, 0.1, 600.0)

    print("[smoke] drawing 1 frame…")
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    scene.draw(cam.view_matrix(), proj)
    glfw.swap_buffers(win)
    glfw.poll_events()

    glfw.destroy_window(win)
    glfw.terminate()
    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
