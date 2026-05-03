"""Utilitários de matemática: matrizes 4x4 para o pipeline moderno do OpenGL.

Construímos todas as matrizes (translação, rotação, escala, projeção
e visão) em numpy e enviamos para os shaders como uniforms ``mat4``.
Isso é diferente do OpenGL antigo, que mantinha "stacks" globais de
matrizes (``glPushMatrix``/``glRotate``/``glTranslate``/...).  No
core profile 3.3 essas funções não existem mais — o programa é
responsável por montar a matriz de transformação que vai ao shader.

Convenções adotadas em todo o projeto:
    * Matrizes 4x4 ``float32``, em layout **column-major** quando vistas
      como matemática: a multiplicação canônica é ``M @ v``, com `v`
      como vetor coluna.  Internamente o numpy guarda em row-major,
      então ao subir para o GPU usamos ``transpose=GL_TRUE`` — assim o
      shader recebe o layout mat4 padrão do GLSL.
    * Sistema right-handed (regra da mão direita), com **+Y para cima**,
      ``-Z`` para a frente da câmera e ``+X`` para a direita.  Esse é o
      mesmo convite usado pela função ``look_at`` clássica do OpenGL.
    * Ângulos sempre em radianos.  Helpers que recebem grau (``perspective``)
      indicam isso explicitamente no nome do parâmetro (``fov_deg``).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# Raiz do projeto = diretório que contém ``src/``.  Resolvido a partir
# do caminho do próprio arquivo para funcionar independentemente do
# cwd em que o script for executado.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def asset(*parts: str) -> str:
    """Devolve o caminho absoluto para um arquivo de asset.

    Recebe os componentes relativos à raiz do projeto e retorna a
    string concatenada.  Exemplo:

        asset("assets", "modelos", "submarino", "submarino.obj")
        # -> "<repo>/projeto2_submarino/assets/modelos/submarino/submarino.obj"

    Centralizar a resolução aqui evita usar caminhos relativos espalhados
    pelo código (que dependeriam do cwd atual).
    """
    return str(PROJECT_ROOT.joinpath(*parts))


def identity() -> np.ndarray:
    # Identidade 4x4 em float32.  Usada como ``uModel`` para qualquer
    # malha já posicionada em coordenadas de mundo (ex.: chãos e domo).
    return np.identity(4, dtype=np.float32)


def translate(tx: float, ty: float, tz: float) -> np.ndarray:
    # Matriz de translação canônica:
    #     | 1 0 0 tx |
    #     | 0 1 0 ty |
    #     | 0 0 1 tz |
    #     | 0 0 0  1 |
    # Aplicada via ``T @ v``, desloca um ponto pelo vetor (tx, ty, tz).
    m = np.identity(4, dtype=np.float32)
    m[0, 3] = tx
    m[1, 3] = ty
    m[2, 3] = tz
    return m


def scale(sx: float, sy: float | None = None, sz: float | None = None) -> np.ndarray:
    # Conveniência: escala uniforme se apenas ``sx`` for passado.
    # Útil porque a maioria dos modelos do projeto é escalada
    # uniformemente (não esticamos a geometria).
    if sy is None:
        sy = sx
    if sz is None:
        sz = sx
    m = np.identity(4, dtype=np.float32)
    m[0, 0] = sx
    m[1, 1] = sy
    m[2, 2] = sz
    return m


def rotate_x(angle_rad: float) -> np.ndarray:
    # Rotação em torno do eixo X (pitch).  Vista olhando o eixo X da
    # origem para fora, o sentido positivo é anti-horário (gira Y em
    # direção a Z).
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    m = np.identity(4, dtype=np.float32)
    m[1, 1] = c
    m[1, 2] = -s
    m[2, 1] = s
    m[2, 2] = c
    return m


def rotate_y(angle_rad: float) -> np.ndarray:
    # Rotação em torno do eixo Y (yaw).  Esta é a rotação mais usada
    # nos objetos da cena, já que o "para cima" do mundo é Y e quase
    # todo modelo é colocado em pé.  Sentido positivo: anti-horário
    # visto de cima (de +Y para a origem).
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    m = np.identity(4, dtype=np.float32)
    m[0, 0] = c
    m[0, 2] = s
    m[2, 0] = -s
    m[2, 2] = c
    return m


def rotate_z(angle_rad: float) -> np.ndarray:
    # Rotação em torno do eixo Z (roll).  Praticamente não usada nesta
    # cena — incluída por completude do toolkit.
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    m = np.identity(4, dtype=np.float32)
    m[0, 0] = c
    m[0, 1] = -s
    m[1, 0] = s
    m[1, 1] = c
    return m


def perspective(fov_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    """Matriz de projeção perspectiva right-handed.

    Mapeia o frustum de visão (uma pirâmide truncada com base no
    ``near`` e topo no ``far``) para o cubo de coordenadas
    normalizadas que o OpenGL espera após o clip stage:
    ``[-1, 1]`` em X/Y e ``[-1, 1]`` em Z (faixa padrão de
    ``gl_DepthRange``).

    Parâmetros:
        fov_deg: campo de visão vertical, em graus.  60° é o usado em
                 ``main.py`` — confortável e sem distorção exagerada.
        aspect:  razão largura/altura do framebuffer (ex.: 1280/720).
        near:    distância do plano próximo (em metros).  Tem que ser
                 > 0; valores muito pequenos pioram a precisão do
                 z-buffer e causam z-fighting longe.
        far:     distância do plano distante.  Definir generoso o
                 bastante para incluir o domo do céu (≈ 250 m).
    """
    # f = 1/tan(fov/2): controla a "abertura" vertical da câmera.
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    # X/Y são divididos por aspect para compensar janelas não-quadradas;
    # caso contrário um círculo apareceria como elipse esticada.
    m[0, 0] = f / aspect
    m[1, 1] = f
    # Mapeamento Z não-linear que coloca near em z_ndc=-1 e far em +1,
    # respeitando a divisão homogênea por w (= -z_eye).
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    # Coloca -z_eye em w para a divisão perspectiva acontecer no clip.
    m[3, 2] = -1.0
    return m


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    """Matriz de visão (view matrix) right-handed olhando de ``eye`` para ``target``.

    O resultado leva pontos do espaço de mundo para o espaço de
    câmera, onde a câmera fica na origem olhando para -Z.  É o mesmo
    formato gerado pelo antigo ``gluLookAt``.
    """
    eye = np.asarray(eye, dtype=np.float32)
    target = np.asarray(target, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)

    # f = "para frente" da câmera (vetor unitário do olho ao alvo).
    f = target - eye
    f /= np.linalg.norm(f)
    # s = "para o lado direito" da câmera, perpendicular a f e a up.
    # Multiplicação cruzada na ordem (f, up) garante o sentido correto
    # em right-handed (s = f × up).
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    # u = up real da câmera, recomputado a partir de s e f para
    # garantir ortogonalidade mesmo se o caller passou um up
    # ligeiramente desalinhado.
    u = np.cross(s, f)

    # Monta a matriz: as três primeiras linhas são os eixos da câmera
    # (s/u/-f) e a quarta coluna remove a posição do olho com
    # produto escalar (translação no espaço de câmera).
    m = np.identity(4, dtype=np.float32)
    m[0, 0:3] = s
    m[1, 0:3] = u
    m[2, 0:3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m
