"""Gera os screenshots usados no README de entrega.

Sobe a Scene em uma janela GLFW oculta, posiciona a câmera em vários
pontos relevantes (vistas externas, vistas internas da cabine,
close-ups dos animais interativos e uma visualização em wireframe) e
salva cada frame como PNG em ``build/report/``.

Resolução padrão: 1600x900 (16:9 confortável para README).

Uso:
    python tools/render_for_report.py
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
    GL_FILL,
    GL_FRONT_AND_BACK,
    GL_LINE,
    GL_RGBA,
    GL_UNSIGNED_BYTE,
    glClear,
    glClearColor,
    glEnable,
    glPolygonMode,
    glReadPixels,
    glViewport,
)
from PIL import Image

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from camera import Camera  # noqa: E402
from scene import Scene  # noqa: E402
from utils import perspective  # noqa: E402


# Cada view é (nome, posição, yaw_deg, pitch, wireframe)
VIEWS = [
    # ---------- "Capa" e visões panorâmicas externas ----------
    ("hero",              (38.0, 17.0,  38.0),  -135.0, -0.25, False),
    ("exterior_iso_ne",   (50.0, 24.0,  50.0),  -135.0, -0.32, False),
    ("exterior_topdown",  ( 0.0, 80.0,   0.0),   -90.0, -1.55, False),
    ("exterior_low_side", (45.0,  5.5,   0.0),  -180.0, -0.05, False),

    # ---------- Animais interativos ----------
    ("orca_close",        (52.0, 16.0,  30.0),  -150.0, -0.18, False),
    # Beluga em (-35, 10.4, -15), modelo grande (~5 m no eixo Z após
    # escala 0.16).  Câmera próxima e a leste-norte para enquadrar
    # o corpo inteiro.
    ("beluga_close",      (-25.0, 12.5,  -8.0),  -145.0, -0.10, False),
    # Cardume: a célula procedural (cx=5, cz=65) está fora da
    # exclusion box e tem 1-2 peixes-palhaço com jitter ±4 m;
    # a câmera fica colada nessa região, baixa e olhando para +Z.
    ("school_close",      ( 5.0,  4.0,  55.0),    90.0, -0.05, False),

    # ---------- Decoração procedural ----------
    # Vista lateral baixa de uma região cheia de corais + algas +
    # pedras (longe do submarino, fora da exclusion box).
    ("decor_close",       (-40.0,  4.0, -40.0),  -135.0, -0.19, False),

    # ---------- Interior ----------
    # POV do piloto: dentro do casco, atrás da cadeira, olhando para a
    # proa (joystick + estação holográfica em primeiro plano).
    ("interior_pilot_pov",( 0.0,  5.0,  16.0),    90.0, -0.10, False),
    # Vista 3/4 da estação de comando (cadeira + estação + joystick),
    # de dentro do submarino.  Câmera ligeiramente lateral, dentro
    # do raio interno do casco (~4.5 m), olhando para a proa.
    ("interior_chair",    (-2.0,  5.0,  14.0),    68.0, -0.18, False),
    # Console sci-fi de comando na popa (oposto ao piloto).
    ("interior_back",     ( 0.0,  5.0,  -4.0),   -90.0, -0.10, False),

    # ---------- Wireframe (requisito do edital) ----------
    ("wireframe",         (45.0, 22.0,  45.0),  -135.0, -0.32, True),
]


def main() -> int:
    if not glfw.init():
        return 1
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    glfw.window_hint(glfw.VISIBLE, False)

    W, H = 1600, 900
    win = glfw.create_window(W, H, "render-for-report", None, None)
    if not win:
        glfw.terminate()
        return 1
    glfw.make_context_current(win)

    glClearColor(0.02, 0.05, 0.10, 1.0)
    glEnable(GL_DEPTH_TEST)
    glViewport(0, 0, W, H)

    scene = Scene()
    proj = perspective(60.0, W / H, 0.1, 600.0)
    out_dir = Path(__file__).resolve().parent.parent / "build" / "report"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, pos, yaw_deg, pitch, wireframe in VIEWS:
        # As bounds da câmera default cobrem tudo que precisamos
        # (x,z em [-100,100], y em [0.4, 60]); como nossas posições
        # estão dentro desse intervalo, não precisamos sobrescrever.
        cam = Camera(position=pos, yaw=math.radians(yaw_deg), pitch=pitch)

        # Liga/desliga wireframe pra esse frame.
        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if wireframe else GL_FILL)

        # 2 frames "de aquecimento" para garantir que mipmaps e estado
        # do driver estejam estáveis antes de capturar.
        for _ in range(2):
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            scene.draw(cam.view_matrix(), proj)
            glfw.swap_buffers(win)
            glfw.poll_events()

        # Frame final: lê o framebuffer e salva como PNG.
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        scene.draw(cam.view_matrix(), proj)
        pixels = glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE)
        glfw.swap_buffers(win)

        img = Image.frombytes("RGBA", (W, H), pixels).transpose(Image.FLIP_TOP_BOTTOM)
        out = out_dir / f"{name}.png"
        img.save(out)
        print(f"[render] wrote {out.name}  ({W}x{H}, wireframe={wireframe})")

    # Restaura modo fill para não afetar usos futuros do contexto.
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
    glfw.destroy_window(win)
    glfw.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
