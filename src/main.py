"""Ponto de entrada do programa.

Este módulo é responsável por:

    * abrir uma janela com GLFW e criar um contexto OpenGL 3.3 core
      (sem nada de pipeline fixo: só shaders, VAOs e uniforms);
    * carregar a cena (``Scene``) e a câmera (``Camera``);
    * rodar o loop principal: ler teclado/mouse, atualizar estado,
      renderizar, trocar buffers (vsync ligado).

Como executar a aplicação a partir da raiz do projeto (``projeto2_submarino``):

    source .venv/bin/activate
    python src/main.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import glfw
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT,
    GL_CULL_FACE,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_FILL,
    GL_FRONT_AND_BACK,
    GL_LINE,
    glClear,
    glClearColor,
    glDisable,
    glEnable,
    glPolygonMode,
    glViewport,
)

# Adiciona o diretório `src/` ao `sys.path` para que os módulos
# irmãos (camera, scene, utils, model, shader, texture) possam ser
# importados como ``from camera import Camera`` mesmo quando este
# arquivo é chamado como script (``python src/main.py``).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from camera import Camera  # noqa: E402
from scene import Scene  # noqa: E402
from utils import perspective  # noqa: E402


WINDOW_W = 1280
WINDOW_H = 720
TITLE = "Projeto 2: Submarino 3D"


class App:
    def __init__(self) -> None:
        # ---- Inicialização do GLFW e criação da janela --------------
        if not glfw.init():
            raise RuntimeError("glfw.init() failed")
        # Pedimos um contexto OpenGL 3.3 Core: sem pipeline fixo
        # (sem glRotate/glPushMatrix/glBegin etc.).  ``FORWARD_COMPAT``
        # é exigido em macOS para obter de fato 3.3+ ao invés de cair
        # em 2.1.  Sem essas dicas o driver poderia abrir um contexto
        # legacy onde os shaders não funcionariam como esperado.
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)

        self.window = glfw.create_window(WINDOW_W, WINDOW_H, TITLE, None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("glfw.create_window failed")
        # ``make_context_current`` torna esta janela o destino das
        # chamadas OpenGL feitas a partir desta thread.
        glfw.make_context_current(self.window)
        # swap_interval(1) = vsync: limita o swap à taxa de atualização
        # do monitor para evitar tearing e gastar GPU à toa.
        glfw.swap_interval(1)

        # ---- Captura de input ---------------------------------------
        # CURSOR_DISABLED esconde o ponteiro e o "trava" no centro,
        # permitindo movimento ilimitado do mouse para look around (estilo FPS).
        glfw.set_input_mode(self.window, glfw.CURSOR, glfw.CURSOR_DISABLED)
        # Eventos discretos (PRESS/RELEASE) caem em ``_on_key``.  Já as
        # teclas de movimento são lidas em polling todo frame em
        # ``_process_held_keys`` para que segurar produza movimento
        # contínuo proporcional a dt.
        glfw.set_key_callback(self.window, self._on_key)
        glfw.set_cursor_pos_callback(self.window, self._on_mouse_move)
        glfw.set_framebuffer_size_callback(self.window, self._on_resize)

        # ---- Estado inicial do OpenGL -------------------------------
        # Cor de fundo no tom "fundo do mar" caso algum pixel do
        # framebuffer não seja coberto pelo domo do céu.
        glClearColor(0.02, 0.05, 0.10, 1.0)
        glEnable(GL_DEPTH_TEST)
        # Vários modelos importados têm winding inconsistente entre as
        # faces (alguns triângulos CW, outros CCW).  Habilitar
        # face culling deixaria buracos visíveis.  Como a cena é
        # pequena, é mais simples desabilitar o culling do que tentar
        # corrigir o winding modelo a modelo.
        glDisable(GL_CULL_FACE)

        # ---- Cena + câmera -----------------------------------------
        self.scene = Scene()
        # Posição inicial colocada de propósito do lado de fora do
        # submarino (X+, Z+) e olhando para a origem (yaw ≈ -150°)
        # para que a primeira renderização já mostre o submarino e o
        # cardume sem precisar mover a câmera.
        self.camera = Camera(position=(35.0, 12.0, 35.0), yaw=math.radians(-150.0), pitch=-0.10)

        # ---- Estado de loop / input --------------------------------
        # Marcador para calcular dt (delta-time) a cada frame.
        self.last_time = time.perf_counter()
        # Última posição lida do cursor; ``None`` na primeira chamada
        # para evitar um jump de yaw/pitch gigante no primeiro evento.
        self.last_mouse: tuple[float, float] | None = None
        self.wireframe = False

        # Rate-limit de teclas que ficam disparando enquanto seguradas.
        # Sem esse limite, segurar a tecla por meio segundo a 60 FPS
        # aplicaria 30 incrementos seguidos, o que faria a orca
        # saturar a escala instantaneamente e a beluga girar como uma
        # hélice.  0.12 s entre disparos (~8 Hz) dá uma sensação suave.
        self._last_lbracket_press = 0.0   # diminuir orca "["
        self._last_rbracket_press = 0.0   # aumentar  orca "]"
        self._last_r_press = 0.0          # beluga: passo no sentido positivo "R"
        self._last_q_press = 0.0          # beluga: passo no sentido negativo "Q"
        self._last_t_press = 0.0          # cadeira: translação +Z "T"
        self._last_g_press = 0.0          # cadeira: translação -Z "G"
        self._last_f_press = 0.0          # cadeira: translação +X "F"
        self._last_h_press = 0.0          # cadeira: translação -X "H"

    # ---------------- callbacks ---------------- #

    def _on_resize(self, _win, w: int, h: int) -> None:
        # Reconfigura o viewport quando a janela é redimensionada.
        # ``max(1, ...)`` evita viewport de tamanho zero ao minimizar
        # a janela (alguns drivers reclamam de w=0/h=0).  A nova
        # razão de aspecto é recalculada por frame em ``run`` para
        # manter a projeção consistente com o framebuffer atual.
        glViewport(0, 0, max(1, w), max(1, h))

    def _on_key(self, _win, key, _scan, action, _mods) -> None:
        # Aqui só nos importam eventos discretos (toggle/quit). As
        # teclas que disparam continuamente (movimento, escala,
        # rotação) são lidas via polling em ``_process_held_keys``.
        if action != glfw.PRESS:
            return
        if key == glfw.KEY_ESCAPE:
            # Sinaliza ao loop principal que pode encerrar.
            glfw.set_window_should_close(self.window, True)
        elif key == glfw.KEY_P:
            # Alterna entre preenchimento e wireframe.  Útil para
            # depurar sobreposição de geometria e densidade da malha.
            self.wireframe = not self.wireframe
            glPolygonMode(
                GL_FRONT_AND_BACK,
                GL_LINE if self.wireframe else GL_FILL,
            )
            print(f"[input] wireframe={'ON' if self.wireframe else 'OFF'}")

    def _on_mouse_move(self, _win, x: float, y: float) -> None:
        # Primeira amostra: armazenamos sem aplicar delta para evitar
        # que a posição inicial do cursor (canto da tela) seja tratada
        # como movimento e gere uma rotação enorme no frame 0.
        if self.last_mouse is None:
            self.last_mouse = (x, y)
            return
        lx, ly = self.last_mouse
        dx = x - lx
        # Invertemos o eixo Y do mouse: subir o mouse deve fazer a
        # câmera olhar para cima (em coordenadas de tela, Y cresce
        # para baixo, então `ly - y` dá o sinal correto).
        dy = ly - y
        self.last_mouse = (x, y)
        self.camera.add_yaw_pitch(dx, dy)

    # ---------------- per-frame helpers ---------------- #

    def _process_held_keys(self, dt: float) -> None:
        """Lê o teclado todo frame e aplica os comandos contínuos.

        Diferente de ``_on_key`` (que só vê PRESS/RELEASE pontuais),
        aqui usamos polling: toda vez que entramos no loop, perguntamos
        se cada tecla relevante está pressionada *agora*.  Isso é o
        que viabiliza:

            * andar enquanto W/A/S/D estão segurados, com velocidade
              proporcional a dt para ficar independente do FPS;
            * ramps suaves nas teclas de escala/rotação enquanto
              seguradas, controlados pelo ``rate-limit`` de 0.12 s
              entre disparos.
        """
        win = self.window
        # Composição vetorial: cada eixo é -1, 0 ou 1 conforme as
        # teclas opostas.  ``camera.move`` projeta isso na frente/lado
        # da câmera e converte em metros via ``speed * dt``.
        fwd = side = vert = 0.0
        if glfw.get_key(win, glfw.KEY_W) == glfw.PRESS:
            fwd += 1.0
        if glfw.get_key(win, glfw.KEY_S) == glfw.PRESS:
            fwd -= 1.0
        if glfw.get_key(win, glfw.KEY_A) == glfw.PRESS:
            side -= 1.0
        if glfw.get_key(win, glfw.KEY_D) == glfw.PRESS:
            side += 1.0
        if glfw.get_key(win, glfw.KEY_SPACE) == glfw.PRESS:
            vert += 1.0
        if glfw.get_key(win, glfw.KEY_LEFT_SHIFT) == glfw.PRESS:
            vert -= 1.0
        self.camera.move(fwd, side, vert, dt)

        now = time.perf_counter()

        # Escala da orca: ']' aumenta, '[' diminui.  Cada disparo
        # multiplica o fator de escala atual por 1.10 (ou 1/1.10),
        # então o crescimento é geométrico: segurar a tecla por
        # ~2 s ramp-a a escala em ~1.10^16 ≈ 4.6×, mas o ``adjust_orca_scale``
        # trava o fator entre 0.3× e 3.0× para manter a cena legível.
        if glfw.get_key(win, glfw.KEY_RIGHT_BRACKET) == glfw.PRESS:
            if now - self._last_rbracket_press > 0.12:
                self.scene.adjust_orca_scale(1.10)
                self._last_rbracket_press = now
        if glfw.get_key(win, glfw.KEY_LEFT_BRACKET) == glfw.PRESS:
            if now - self._last_lbracket_press > 0.12:
                self.scene.adjust_orca_scale(1.0 / 1.10)
                self._last_lbracket_press = now

        # Rotação da beluga: passo discreto de 30° por toque, mas que
        # se repete enquanto a tecla estiver segurada (rate-limit).  R
        # gira em um sentido (delta padrão positivo) e Q no outro
        # (passamos -BELUGA_ROTATION_STEP).  Os dois caminhos
        # acumulam no mesmo `state.beluga_rotation_angle`, então
        # alternar Q/R cancela cliques anteriores em vez de criar
        # eixos de rotação independentes.
        if glfw.get_key(win, glfw.KEY_R) == glfw.PRESS:
            if now - self._last_r_press > 0.12:
                self.scene.rotate_beluga_step()
                self._last_r_press = now
        if glfw.get_key(win, glfw.KEY_Q) == glfw.PRESS:
            if now - self._last_q_press > 0.12:
                self.scene.rotate_beluga_step(-self.scene.BELUGA_ROTATION_STEP)
                self._last_q_press = now

        # Translação da cadeira: T=+Z, G=-Z, F=+X, H=-X.
        step = self.scene.CHAIR_TRANSLATE_STEP
        if glfw.get_key(win, glfw.KEY_T) == glfw.PRESS:
            if now - self._last_t_press > 0.12:
                self.scene.translate_chair_step(dz=step)
                self._last_t_press = now
        if glfw.get_key(win, glfw.KEY_G) == glfw.PRESS:
            if now - self._last_g_press > 0.12:
                self.scene.translate_chair_step(dz=-step)
                self._last_g_press = now
        if glfw.get_key(win, glfw.KEY_F) == glfw.PRESS:
            if now - self._last_f_press > 0.12:
                self.scene.translate_chair_step(dx=step)
                self._last_f_press = now
        if glfw.get_key(win, glfw.KEY_H) == glfw.PRESS:
            if now - self._last_h_press > 0.12:
                self.scene.translate_chair_step(dx=-step)
                self._last_h_press = now

    # ---------------- main loop ---------------- #

    def run(self) -> None:
        # Loop clássico de aplicação interativa: enquanto a janela
        # estiver aberta, processa input → atualiza estado → renderiza.
        while not glfw.window_should_close(self.window):
            # ``dt`` em segundos é a base para todo movimento contínuo.
            # ``min(dt, 0.1)`` impede saltos enormes se o programa
            # tiver travado (ex.: depurador, sistema sob carga): sem
            # esse limite, um pulo de 1 s de dt teleportaria a câmera
            # para fora do cenário em um único frame.
            now = time.perf_counter()
            dt = min(now - self.last_time, 0.1)
            self.last_time = now

            self._process_held_keys(dt)
            self.scene.update(dt)

            # Recalculamos a projeção a cada frame porque o
            # ``aspect`` pode mudar quando a janela é redimensionada.
            # near=0.1 e far=600 abrem espaço suficiente para incluir
            # o domo do céu (≈ 250 m de raio) sem perder precisão de
            # z-buffer perto da câmera.
            w, h = glfw.get_framebuffer_size(self.window)
            aspect = w / max(1, h)
            proj = perspective(60.0, aspect, 0.1, 600.0)
            view = self.camera.view_matrix()

            # Limpa cor + profundidade antes de cada draw call sequence.
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            self.scene.draw(view, proj)

            # Double-buffering: o frame que acabamos de desenhar fica
            # visível só após o swap.  ``poll_events`` despacha as
            # mensagens da fila do SO (callbacks de teclado/mouse).
            glfw.swap_buffers(self.window)
            glfw.poll_events()

        # Liberação dos recursos do GLFW na saída do loop.
        glfw.terminate()


def main() -> int:
    # Imprime os controles no terminal para o usuário não precisar
    # adivinhar o que cada tecla faz na primeira execução.
    GREEN = "\033[32m"
    RESET = "\033[0m"
    controls = (
        "[main] controls: WASD + Space/Shift, mouse look, P=wireframe, "
        "[ or ] orca scale, R/Q beluga rotate, T/G/F/H chair translate, Esc"
    )
    print("[main] starting submarine scene")
    print(f"{GREEN}{controls}{RESET}")
    app = App()
    # Repete os controles após os logs de carregamento para facilitar a leitura.
    print(f"{GREEN}{controls}{RESET}")
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
