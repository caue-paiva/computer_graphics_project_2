"""Montagem da cena e ordem de renderização.

Este módulo é o "diretor de cena" do projeto: é onde o submarino, o
chão de areia, o cardume de peixes, os corais, a beluga, a orca e
todos os elementos de cabine (cadeira, mesa, joystick, estação de
monitoramento) são posicionados no espaço de mundo.

Cada objeto da cena é um ``Object3D``, que combina um ``Model``
(geometria + texturas, carregada de um .obj) com uma transformação
afim (translação, rotação Y e escala).  No fim do construtor da
classe ``Scene`` temos uma lista ``self.objects`` que o método
``draw`` percorre todo frame para renderizar.

Decisões de design relevantes
-----------------------------

* **Chão interno seguindo o casco.**  Em vez de usar um retângulo
  plano para o piso da cabine, geramos uma faixa de quads cuja
  largura é determinada amostrando os vértices do casco do
  submarino em cada fatia de Z.  Isso garante que o piso ocupe o
  comprimento todo do submarino sem furar a casca curva da proa /
  popa (ver ``make_hull_following_floor``).

* **Decoração procedural do chão de areia.**  Corais, pedras e algas
  são plotados em uma grade 2D que cobre todos os 400×400 metros do
  piso externo.  Usamos uma RNG semeada (``seed=42``) para garantir
  que a distribuição seja reprodutível entre execuções, mas variada
  o suficiente para parecer natural.  Há uma "exclusion box" no
  centro para impedir que decoração apareça embaixo/em cima do
  submarino.

* **Cardume de peixes-palhaço.**  Mesma ideia do decor, mas em 3D:
  a Y dos peixes é amostrada num intervalo (1.5..9 m) para que
  fiquem flutuando na coluna d'água em alturas diferentes.

* **Animais individuais (orca + beluga).**  Posicionados manualmente
  para criar marcos visuais — orca em um lado, beluga no outro,
  ambas em escalas que respeitam a bbox real dos modelos.  A escala
  da orca e a rotação da beluga são animáveis pelo teclado (ver
  ``adjust_orca_scale`` e ``rotate_beluga_step``).

Convenções de unidades:
    * todas as posições estão em metros, no espaço de mundo;
    * todas as rotações estão em radianos (uso de ``math.radians``
      ao usar literais em graus para clareza);
    * +Y é "para cima", o chão de areia está em Y=0.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_DEPTH_TEST,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_LEQUAL,
    GL_LESS,
    GL_STATIC_DRAW,
    GL_TEXTURE0,
    GL_TEXTURE_2D,
    GL_TRIANGLES,
    GL_UNSIGNED_INT,
    glActiveTexture,
    glBindBuffer,
    glBindTexture,
    glBindVertexArray,
    glBufferData,
    glDepthFunc,
    glDrawElements,
    glEnable,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenVertexArrays,
    glVertexAttribPointer,
)

import utils
from model import Model, SubMesh, ctypes_offset, draw_model
from shader import Program
from texture import load_texture_2d


# --------------------------------------------------------------------------- #
#  Primitivas geométricas geradas em runtime (vão direto para a GPU como       #
#  ``Model`` de uma única submalha — sem passar por arquivo .obj).             #
# --------------------------------------------------------------------------- #


def _make_textured_model(
    positions_uvs: list[float],
    indices: list[int],
    diffuse_path: str,
    wrap_repeat: bool = True,
    name: str = "primitive",
) -> Model:
    """Constrói um ``Model`` com uma única submalha a partir de listas crus de vértices e índices.

    O formato esperado de ``positions_uvs`` é uma lista achatada onde
    cada vértice ocupa 5 floats consecutivos: [x, y, z, u, v].  Os
    ``indices`` referenciam esses vértices (3 por triângulo).

    Sobe os dados para o GPU em três objetos OpenGL:
        * VAO (Vertex Array Object) — guarda a configuração dos
          atributos para que ``draw`` só precise dar bind no VAO;
        * VBO (Vertex Buffer Object) — buffer com os vértices;
        * EBO (Element Buffer Object) — buffer com os índices.

    Uso típico: chãos, paredes, domo do céu — geometria simples que
    não justifica um arquivo .obj separado.
    """
    # Cria os três objetos de uma vez.  ``glGen*`` recebe quantidade
    # e devolve IDs; convertemos para int para evitar surpresas com
    # numpy.uint32 em chamadas futuras de bind.
    vao = int(glGenVertexArrays(1))
    vbo = int(glGenBuffers(1))
    ebo = int(glGenBuffers(1))
    glBindVertexArray(vao)

    # Sobe os arrays para o GPU.  ``GL_STATIC_DRAW`` indica que os
    # buffers não serão reescritos depois, o que pode ajudar o driver
    # a colocá-los em memória mais rápida.
    vbo_data = np.asarray(positions_uvs, dtype=np.float32)
    ebo_data = np.asarray(indices, dtype=np.uint32)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, vbo_data.nbytes, vbo_data, GL_STATIC_DRAW)
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, ebo_data.nbytes, ebo_data, GL_STATIC_DRAW)

    # Layout do vértice: 5 floats por vértice = 20 bytes de stride.
    # Atributo 0 (location=0 no shader) = posição (3 floats, offset 0).
    # Atributo 1 (location=1 no shader) = UV       (2 floats, offset 12).
    stride = 5 * 4
    glEnableVertexAttribArray(0)
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, None)
    glEnableVertexAttribArray(1)
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes_offset(3 * 4))
    glBindVertexArray(0)

    # Carrega a textura difusa e empacota tudo em um Model com uma
    # única submalha — assim o ``draw_model`` lida com primitivas e
    # com modelos importados da mesma forma.
    tex = load_texture_2d(diffuse_path, wrap_repeat=wrap_repeat)
    sub = SubMesh(diffuse_tex=tex, index_offset=0, index_count=len(indices), material_name=name)
    return Model(vao=vao, submeshes=[sub], name=name)


def make_floor(size: float, tex_path: str, tile: float, y: float = 0.0) -> Model:
    """Constrói um chão quadrado plano centrado na origem.

    ``size`` é o lado do quadrado em metros; ``y`` é a altura em que
    o chão fica.  ``tile`` controla quantas vezes a textura se
    repete em cada eixo — para uma areia que pareça natural num
    plano de 400 m, costumamos usar tile=40 (a textura 4K então
    fica com escala "metros" e não "quilômetros").
    """
    h = size / 2.0
    # 4 vértices, com UVs que vão de 0 até ``tile`` para fazer a
    # textura repetir esse número de vezes (depende de wrap_repeat=True).
    verts = [
        -h, y, -h, 0.0, 0.0,
         h, y, -h, tile, 0.0,
         h, y,  h, tile, tile,
        -h, y,  h, 0.0, tile,
    ]
    # Dois triângulos cobrindo o quadrado, ambos com normal +Y.
    inds = [0, 1, 2, 0, 2, 3]
    return _make_textured_model(verts, inds, tex_path, name="floor")


def make_rect_floor(
    sx: float,
    sz: float,
    tex_path: str,
    tile_x: float = 1.0,
    tile_z: float = 1.0,
    y: float = 0.0,
    name: str = "rect_floor",
) -> Model:
    """Chão retangular alinhado aos eixos, centrado na origem.

    Variante de ``make_floor`` que aceita lados X e Z diferentes e
    fatores de tile independentes em cada eixo.  Útil para superfícies
    longas e estreitas (ex.: corredor interno do submarino), onde
    aplicar o mesmo tile nos dois eixos faria a textura aparecer
    "esticada" na direção mais curta.  A normal aponta para +Y.
    """
    hx, hz = sx / 2.0, sz / 2.0
    verts = [
        -hx, y, -hz, 0.0,    0.0,
         hx, y, -hz, tile_x, 0.0,
         hx, y,  hz, tile_x, tile_z,
        -hx, y,  hz, 0.0,    tile_z,
    ]
    inds = [0, 1, 2, 0, 2, 3]
    return _make_textured_model(verts, inds, tex_path, name=name)


def make_hull_following_floor(
    obj_path: str,
    sub_scale: float,
    sub_translation_y: float,
    target_y_world: float,
    margin: float,
    tex_path: str,
    tile_density_x: float = 0.5,  # repetições da textura por metro em X
    tile_density_z: float = 0.5,  # repetições da textura por metro em Z
    z_band: float = 0.18,
    name: str = "hull_floor",
) -> Model:
    """Constrói um piso interno que segue o contorno da parede do casco do submarino.

    O problema é o seguinte: o casco do submarino é uma forma orgânica
    com seção transversal variável (mais largo no meio, afilado na
    proa/popa).  Se colocássemos um retângulo plano como piso, ele:

        * ou seria curto demais (sobraria casco vazio nas pontas);
        * ou seria longo demais e atravessaria a parede curva nas
          pontas, ficando com bordas visíveis "saindo" do submarino.

    A solução implementada aqui é amostrar o próprio .obj do casco:
    para cada fatia inteira em Z, olhamos os vértices que estão
    perto de uma altura alvo e pegamos o ``max |X|``.  Esse valor é a
    meia-largura da parede interna naquela fatia; subtraindo
    ``margin`` (em metros) obtemos a meia-largura "segura" para o
    piso.  Em seguida, ligamos as fatias com tiras de quads —
    resultado é um piso de contorno orgânico que cobre o submarino
    inteiro sem atravessar o casco.

    Parâmetros importantes:
        ``sub_scale`` / ``sub_translation_y`` — devem ser idênticos à
            transformação aplicada ao submarino na cena, para que a
            amostragem aconteça em coordenadas comparáveis.
        ``target_y_world`` — altura desejada do piso, em metros.
        ``margin`` — folga de segurança em relação à parede.  50 cm
            é confortável para evitar que a triangulação linear
            entre fatias adjacentes corte a casca em curvas
            apertadas.

    A malha é gerada já em coordenadas de mundo, então o caller
    desenha esse Model com matriz modelo identidade.
    """
    # Para amostrar o .obj precisamos converter o alvo de Y mundial
    # para o sistema local do modelo (Y_local = (Y_world - dy) / s).
    target_y_local = (target_y_world - sub_translation_y) / sub_scale

    # Para cada fatia inteira de Z (em metros, no espaço de mundo)
    # guardamos o maior |X| (também em mundo) entre os vértices do
    # casco que ficam perto da altura alvo.  Esse "perto" é
    # controlado por ``z_band`` / 0.15 abaixo: o objetivo é incluir
    # apenas vértices da parede interna na altura desejada e ignorar
    # piso, teto e outras estruturas do casco.
    bins: dict[int, float] = {}
    with open(obj_path) as fin:
        for ln in fin:
            if not ln.startswith("v "):
                continue
            _, sx, sy, sz = ln.split()[:4]
            x_local = float(sx)
            y_local = float(sy)
            z_local = float(sz)
            # ±0.15 unidades locais ≈ ±0.15 m após escalonado pelo
            # ``sub_scale``.  Estreitar mais a banda gera buracos
            # nas amostras; alargar pega vértices acima/abaixo do
            # piso e estraga a forma.
            if abs(y_local - target_y_local) > 0.15:
                continue
            z_world = z_local * sub_scale
            x_world = abs(x_local * sub_scale)
            zi = round(z_world)
            if x_world > bins.get(zi, 0.0):
                bins[zi] = x_world

    if not bins:
        raise RuntimeError(
            f"make_hull_following_floor: no hull vertices found near "
            f"Y_local={target_y_local:.2f} (Y_world={target_y_world})"
        )

    # Constrói a tira de fatias.  Ignoramos fatias onde a parede
    # interna ficaria estreita demais para produzir um piso
    # razoável: nas extremidades da proa/popa o casco fecha em
    # menos de 1 m, e como conectamos fatias adjacentes por linhas
    # retas (interpolação linear entre amostras), uma curva bem
    # apertada ainda atravessaria o casco.  Cortar em
    # ``min_half_width=1.5`` mantém o piso bem dentro da curvatura.
    min_half_width = 1.5
    samples: list[tuple[float, float]] = []  # (z_world, half_width)
    for zi in sorted(bins):
        hw = bins[zi] - margin
        if hw < min_half_width:
            continue
        samples.append((float(zi), hw))

    if len(samples) < 2:
        raise RuntimeError("make_hull_following_floor: too few usable Z slices")

    # UVs ao longo de Z aumentam linearmente conforme avançamos no
    # comprimento — assim a textura de metal escovado tile-a sem
    # deformação proporcional ao tamanho do piso.
    z_first = samples[0][0]
    z_last = samples[-1][0]
    total_len_z = z_last - z_first
    print(
        f"[scene] hull-following floor: {len(samples)} slices, "
        f"Z∈[{z_first:.0f},{z_last:.0f}] ({total_len_z:.0f}m), "
        f"max half-width={max(hw for _, hw in samples):.2f}m"
    )

    # Cada fatia gera 2 vértices: borda esquerda e borda direita
    # do piso naquele Z.  V (vertical do UV) cresce com Z,
    # U (horizontal do UV) vai de 0 ao dobro da meia-largura
    # multiplicado pela densidade — assim a textura tile-a por
    # metro real de piso, em vez de esticar pela largura variável.
    verts: list[float] = []
    for z, hw in samples:
        v_v = (z - z_first) * tile_density_z
        u_l = 0.0
        u_r = (2.0 * hw) * tile_density_x
        # Borda esquerda
        verts.extend([-hw, 0.0, z, u_l, v_v])
        # Borda direita
        verts.extend([+hw, 0.0, z, u_r, v_v])

    # Conecta cada par de fatias adjacentes com 2 triângulos formando
    # um quad.  A ordem dos vértices (winding) foi escolhida para
    # que a normal aponte para +Y (cima), de modo que a cabine veja
    # o lado correto do piso.
    inds: list[int] = []
    for i in range(len(samples) - 1):
        a = 2 * i           # borda esquerda da fatia atual
        b = 2 * i + 1       # borda direita  da fatia atual
        c = 2 * (i + 1)     # borda esquerda da próxima fatia
        d = 2 * (i + 1) + 1 # borda direita  da próxima fatia
        inds.extend([a, b, d, a, d, c])

    return _make_textured_model(verts, inds, tex_path, name=name)


def make_box(
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
    tex_path: str,
    tile: float = 1.0,
    inward_normals: bool = False,
) -> Model:
    """Caixa alinhada aos eixos.

    Útil para paredes/cabines.  Se ``inward_normals=True``, o winding
    de cada face é invertido para que as normais apontem para
    *dentro* da caixa — isso é o que torna possível ficar dentro
    dela e ver as paredes (porque o face culling padrão descartaria
    triângulos voltados para fora).
    """
    # Limites dos seis lados em coordenadas de mundo.
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    z0, z1 = cz - sz / 2, cz + sz / 2
    t = tile
    # 24 vértices (4 por face), com UVs cobrindo cada face de [0,t].
    verts = [
        # face +X
        x1, y0, z0, 0, 0, x1, y0, z1, t, 0, x1, y1, z1, t, t, x1, y1, z0, 0, t,
        # face -X
        x0, y0, z1, 0, 0, x0, y0, z0, t, 0, x0, y1, z0, t, t, x0, y1, z1, 0, t,
        # face +Y (topo)
        x0, y1, z0, 0, 0, x1, y1, z0, t, 0, x1, y1, z1, t, t, x0, y1, z1, 0, t,
        # face -Y (base)
        x0, y0, z1, 0, 0, x1, y0, z1, t, 0, x1, y0, z0, t, t, x0, y0, z0, 0, t,
        # face +Z
        x1, y0, z1, 0, 0, x0, y0, z1, t, 0, x0, y1, z1, t, t, x1, y1, z1, 0, t,
        # face -Z
        x0, y0, z0, 0, 0, x1, y0, z0, t, 0, x1, y1, z0, t, t, x0, y1, z0, 0, t,
    ]
    # Padrão do quad: 2 triângulos = (0,1,2) + (0,2,3).  Para inverter
    # o winding (e portanto a normal), invertemos a ordem dos vértices.
    base = [0, 1, 2, 0, 2, 3]
    inds: list[int] = []
    for face in range(6):
        offs = face * 4
        if inward_normals:
            inds.extend(base[2 - i] + offs for i in range(3))
            inds.extend(base[5 - i] + offs for i in range(3))
        else:
            inds.extend(idx + offs for idx in base)
    return _make_textured_model(verts, inds, tex_path, name="box")


def make_sky_sphere(radius: float = 250.0, segments: int = 48, rings: int = 24) -> tuple[int, int]:
    """Esfera usada pelo shader de panorama (skybox).

    Geramos uma esfera UV-mapeada centrada na origem.  O shader
    ``skydome.frag`` usa as coordenadas do vértice (em espaço de
    mundo) para amostrar o panorama equirretangular, então não
    precisamos de UVs no buffer — só precisamos do atributo de
    posição.

    Retorna ``(vao, n_indices)`` para que o caller possa fazer o
    drawcall direto sem encapsular num ``Model`` (a esfera tem
    pipeline próprio: shader e textura diferentes do "basic").

    Parâmetros:
        radius   — raio da esfera (em metros).  250 m fica longe
                   o bastante de qualquer câmera para parecer
                   uma cobertura "infinita" do céu.
        segments — divisões longitudinais (eixo theta).
        rings    — divisões latitudinais (eixo phi).
    """
    verts: list[float] = []
    inds: list[int] = []
    # Geração paramétrica: para cada (phi, theta) calculamos o ponto
    # na esfera com a clássica conversão para coordenadas esféricas.
    # Phi vai de 0 (polo norte) a pi (polo sul).
    for r in range(rings + 1):
        phi = math.pi * r / rings
        for s in range(segments + 1):
            theta = 2.0 * math.pi * s / segments
            x = math.sin(phi) * math.cos(theta) * radius
            y = math.cos(phi) * radius
            z = math.sin(phi) * math.sin(theta) * radius
            verts.extend([x, y, z])
    # Conecta cada quad da grade phi×theta com 2 triângulos.  O
    # winding é escolhido para que as normais apontem para DENTRO
    # da esfera, já que a câmera fica no centro (vemos o "lado de
    # dentro" do domo).
    for r in range(rings):
        for s in range(segments):
            i0 = r * (segments + 1) + s
            i1 = i0 + 1
            i2 = i0 + (segments + 1)
            i3 = i2 + 1
            inds.extend([i0, i2, i1, i1, i2, i3])

    vao = int(glGenVertexArrays(1))
    vbo = int(glGenBuffers(1))
    ebo = int(glGenBuffers(1))
    glBindVertexArray(vao)
    vbo_data = np.asarray(verts, dtype=np.float32)
    ebo_data = np.asarray(inds, dtype=np.uint32)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, vbo_data.nbytes, vbo_data, GL_STATIC_DRAW)
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, ebo_data.nbytes, ebo_data, GL_STATIC_DRAW)

    # Apenas o atributo de posição (location=0); UV/normal não vão
    # para o shader do skydome (ele recalcula o UV por pixel).
    stride = 3 * 4
    glEnableVertexAttribArray(0)
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, None)
    glBindVertexArray(0)
    return vao, len(inds)


# --------------------------------------------------------------------------- #
#  Descrição da cena                                                          #
# --------------------------------------------------------------------------- #


@dataclass
class Object3D:
    """Combina um ``Model`` (geometria) com uma transformação afim no espaço de mundo.

    Cada objeto da cena (submarino, peixe, coral, cadeira, ...) é
    representado por uma instância desta dataclass.  Os campos
    ``translation`` / ``rotation_y`` / ``scale_xyz`` cobrem 99 % dos
    casos; quando precisamos de transformações fora do padrão
    (ex.: pivôs especiais, transformações dependentes do tempo)
    usamos os hooks ``extra_rotation`` / ``extra_translation``, que
    são funções sem argumento que devolvem uma matriz 4x4 a ser
    multiplicada na composição.

    Ordem de composição (igual à convenção OpenGL clássica):

        M = T_world * (T_extra) * R_y * (R_extra) * S

    A multiplicação à direita do vetor (``M @ v``) executa primeiro
    a escala, depois rotações, e por último a translação — que é o
    comportamento intuitivo "escalar/girar em torno da origem
    local, depois posicionar no mundo".
    """

    model: Model
    translation: tuple[float, float, float]
    rotation_y: float = 0.0  # radianos
    scale_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0)
    extra_rotation: callable | None = None  # fábrica opcional de matriz
    extra_translation: callable | None = None
    # Multiplicador global das UVs (deixado em 1.0 por padrão; o
    # shader ``basic`` usa esse valor para repetir/contrair texturas
    # sem precisar reupload do VBO).
    uv_tile: float = 1.0

    def model_matrix(self) -> np.ndarray:
        # T_world × (T_extra) × R_y × (R_extra) × S — ver docstring acima.
        m = utils.translate(*self.translation)
        if self.extra_translation is not None:
            m = m @ self.extra_translation()
        m = m @ utils.rotate_y(self.rotation_y)
        if self.extra_rotation is not None:
            m = m @ self.extra_rotation()
        m = m @ utils.scale(*self.scale_xyz)
        return m


@dataclass
class SceneState:
    """Estado dinâmico da cena, alterado por inputs do teclado.

    Dataclass simples que centraliza os valores que mudam ao longo
    do tempo em resposta ao usuário.  Mantemos isso separado dos
    objetos para deixar claro o que é "configuração estática"
    (posição inicial, escala-base) versus "estado interativo".
    """

    # Multiplicador acumulado da escala da orca, controlado pelas
    # teclas '['/']'.  ``orca_obj.scale_xyz = orca_base_scale * factor``.
    orca_scale_factor: float = 1.0
    # Yaw acumulado aplicado ENCIMA da rotação base da beluga.
    # Cada toque em R adiciona ``BELUGA_ROTATION_STEP``; cada toque
    # em Q subtrai.  Manter o estado acumulado (e não recalcular a
    # rotação a partir do tempo) garante que o ângulo só muda em
    # resposta a input — não há rotação contínua.
    beluga_rotation_angle: float = 0.0


class Scene:
    def __init__(self) -> None:
        # ---- Programas de shader -----------------------------------
        # ``basic``  — vertex+fragment shader simples com 1 textura
        #              difusa.  É usado para tudo que tem geometria
        #              com UV: chão, modelos importados, paredes...
        # ``skydome`` — shader específico do panorama equirretangular
        #              do céu/oceano.  Recebe só posição (sem UV) e
        #              calcula a amostragem da textura por pixel.
        self.basic = Program.from_files(
            utils.asset("shaders", "basic.vert"),
            utils.asset("shaders", "basic.frag"),
            label="basic",
        )
        self.sky_program = Program.from_files(
            utils.asset("shaders", "skydome.vert"),
            utils.asset("shaders", "skydome.frag"),
            label="skydome",
        )

        # ------ Domo do céu e chão de areia externo ------
        # A esfera grande (raio 250 m) envolve toda a cena.  É a
        # primeira coisa desenhada a cada frame, com depth func
        # GL_LEQUAL para que o resto da cena sobrescreva os pixels
        # que estão na frente dela.
        self.sky_vao, self.sky_indices = make_sky_sphere(radius=250.0)
        self.sky_tex = load_texture_2d(
            utils.asset("assets", "texturas", "skybox", "skyrender.png"),
            wrap_repeat=False,
            # ``skyrender.png`` foi exportado com origem na quina
            # superior-esquerda, e o shader do skydome assume origem
            # na quina inferior-esquerda.  É o único asset do projeto
            # que precisa de flip vertical no carregamento.
            flip_y=True,
        )

        sand_path = utils.asset("assets", "texturas", "chao_externo", "coast_sand_05_diff_4k.jpg")
        metal_path = utils.asset("assets", "texturas", "interior", "metal_brushed.jpg")

        # Chão de areia externo: 400×400 m centrado na origem, com a
        # textura tile-ada 40 vezes (≈ 1 tile a cada 10 m).  Isso
        # mantém a textura "areia de praia" em escala realista —
        # se aplicássemos tile=1 a textura ficaria gigante (1 grão
        # ocuparia 10 m).
        self.outdoor_floor = make_floor(size=400.0, tex_path=sand_path, tile=40.0, y=0.0)

        # Piso interno em metal escovado que *segue a seção transversal
        # interna do casco* na altura Y_world = 3.5 m.  Ver doc de
        # ``make_hull_following_floor``: amostramos os vértices do .obj
        # do submarino para descobrir a meia-largura da parede a cada
        # fatia de Z, e construímos uma faixa de quads que cabe
        # naturalmente dentro do casco.  Resultado: um corredor de
        # metal que vai da popa até a proa, afilando junto com o
        # próprio submarino.
        # As paredes da cabine não estão habilitadas — só precisamos
        # do piso para que cada prop interno tenha onde se apoiar.
        self.cabin_walls = None
        self.indoor_floor = make_hull_following_floor(
            obj_path=utils.asset("assets", "modelos", "submarino", "submarino.obj"),
            sub_scale=2.5,
            sub_translation_y=5.55,
            target_y_world=3.5,
            # 50 cm de folga em relação à parede interna evitam que
            # qualquer borda do piso "espete" para fora do casco
            # devido à interpolação linear entre fatias.
            margin=0.50,
            tex_path=metal_path,
            tile_density_x=0.5,
            tile_density_z=0.5,
            name="indoor_floor",
        )
        # Translação aplicada na hora de desenhar (a malha já foi
        # gerada centrada em XZ, mas com Y=0; aqui levantamos para 3.5).
        self.indoor_floor_offset = (0.0, 3.5, 0.0)

        # ------ Modelos importados (.obj por modelo) ------
        # Pequeno helper para encurtar a chamada de ``Model.load_obj``,
        # já que todos os modelos seguem o padrão
        # ``assets/modelos/<nome>/<nome>.obj``.
        def load(name: str) -> Model:
            path = utils.asset("assets", "modelos", name, f"{name}.obj")
            return Model.load_obj(path)

        models = {
            "submarino": load("submarino"),
            "coral": load("coral"),
            "pedra": load("pedra"),
            "alga": load("alga"),
            "cadeira": load("cadeira"),
            "estacao": load("estacao"),
            "mesa": load("mesa"),
            "joystick": load("joystick_2"),
            "peixe_palhaco": load("peixe_palhaco"),
            "orca": load("orca"),
            "beluga": load("beluga"),
        }

        # ------ Posicionamento dos objetos no mundo ------
        # Lista única — o ``draw`` percorre na ordem de inserção.
        self.objects: list[Object3D] = []

        # Submarino: AABB do .obj base é
        #     X∈[-1.82, +1.82] (largura)
        #     Y∈[-1.82, +4.86] (altura, com Y=0 na "linha d'água")
        #     Z∈[-10.07, +8.66] (comprimento, popa em -Z, proa em +Z)
        # O modelo já está em metros, então só multiplicamos por 2.5
        # para que a câmera tenha espaço confortável de andar dentro
        # (tipicamente queremos largura útil > 4 m, com 2.5× temos
        # ~9 m de largura externa e ~6 m úteis dentro).
        SUB_SCALE = 2.5
        self.submarine_scale = SUB_SCALE
        sub_length = (8.66 + 10.07) * SUB_SCALE   # ao longo de Z
        sub_width = (1.82 * 2) * SUB_SCALE        # ao longo de X
        sub_height = (4.86 + 1.82) * SUB_SCALE    # ao longo de Y
        # ``+1.0`` levanta o submarino do leito de areia para criar a
        # ilusão de flutuação/repouso ligeiramente acima do solo.
        sub_y = 1.82 * SUB_SCALE + 1.0
        print(
            f"[scene] submarine scale={SUB_SCALE} -> length≈{sub_length:.1f}m "
            f"width≈{sub_width:.1f}m height≈{sub_height:.1f}m"
        )
        self.objects.append(Object3D(
            model=models["submarino"],
            translation=(0.0, sub_y, 0.0),
            rotation_y=0.0,
            scale_xyz=(SUB_SCALE, SUB_SCALE, SUB_SCALE),
        ))

        # Decoração procedural do leito marinho (corais + pedras + algas).
        # Cobre todo o piso externo (400×400 m), com uma célula de 10 m
        # de lado.  Preenchemos só uma célula a cada ``cell_step`` em
        # cada eixo — ``cell_step=3`` significa 1 a cada 9 células
        # (≈ 11 % do leito), o que dá uma cobertura "respirável" sem
        # encher demais o chão.  As _count_range que aceitam (0,1)
        # adicionam ainda outra camada de aleatoriedade dentro de cada
        # célula populada.
        self._populate_decor_grid(
            models=models,
            cell_size=10.0,
            x_range=(-200.0, 200.0),
            z_range=(-200.0, 200.0),
            cell_step=3,
            # Caixa de exclusão centrada na origem, do tamanho do
            # submarino: nenhum decor é gerado dentro dessa área para
            # não atravessar o casco.
            sub_exclusion_half=(6.0, 25.0),
            reserved_cells=(),
            coral_scale_range=(0.045, 0.110),
            pedra_scale_range=(0.10, 0.32),
            alga_scale_range=(0.5, 1.4),
            coral_count_range=(0, 1),
            pedra_count_range=(0, 1),
            alga_count_range=(0, 1),
            min_pair_distance=2.5,
            seed=42,
        )

        # ------ Animais marinhos (cardume + orca + beluga) ------
        #
        # Bounding boxes aproximadas (só geometria visível, ignorando
        # planos de fundo de Material descartados no pipeline):
        #     peixe_palhaco : 3.2 × 1.8 × 1.1 m (X=corpo, Y=vert., Z=largura)
        #     orca          : 4.0 × 2.5 × 2.1 m (X=corpo apontando +X)
        #     beluga        : 10 × 12 × 32 m   (Z=corpo apontando -Z, +offset Y)

        # Cardume de peixes-palhaço espalhado por todo o leito.
        # ``cell_step=6`` faz 1 célula a cada 6 ser populada (~3 % do
        # total), com 1 a 2 peixes por célula em alturas entre 1.5 e
        # 9 m da água.  Resultado: cardume que parece "naturalmente
        # aglomerado" em vez de uma malha uniforme.
        self._populate_fish_grid(
            models=models,
            model_key="peixe_palhaco",
            cell_size=10.0,
            x_range=(-200.0, 200.0),
            z_range=(-200.0, 200.0),
            cell_step=6,
            count_range=(1, 3),                   # randint(1,3) -> 1 ou 2
            sub_exclusion_half=(6.0, 25.0),
            y_range=(1.5, 9.0),
            scale_range=(0.35, 0.60),
            seed=137,
        )

        # Orca solitária nadando em altura média, num canto da cena.
        # O modelo .obj aponta para +X, então rotacionamos 180°+30°
        # para que olhe aproximadamente em direção ao submarino com
        # uma leve inclinação lateral.  É o ALVO de ESCALA controlada
        # pelas teclas '['/']'.
        self.orca_base_scale = 1.7
        self.orca_obj = Object3D(
            model=models["orca"],
            translation=(45.0, 14.0, 25.0),
            rotation_y=math.radians(180.0 + 30.0),
            scale_xyz=(self.orca_base_scale,) * 3,
        )
        self.objects.append(self.orca_obj)

        # Beluga grande no lado oposto.  O modelo aponta para -Z e o
        # centro do corpo (mid-Y do AABB) está em Y_local ≈ 10.75,
        # então deslocamos por -10*scale para que a profundidade
        # vertical da baleia fique aproximadamente centrada na altura
        # alvo de ~12 m.  É o ALVO de ROTAÇÃO controlada pelas
        # teclas R/Q.
        beluga_scale = 0.16
        beluga_y_offset = -10.0 * beluga_scale
        self.beluga_obj = Object3D(
            model=models["beluga"],
            translation=(-35.0, 12.0 + beluga_y_offset, -15.0),
            rotation_y=math.radians(-45.0),
            scale_xyz=(beluga_scale, beluga_scale, beluga_scale),
        )
        # Yaw "base" usado como referência para o ângulo acumulado em
        # ``state.beluga_rotation_angle``: a rotação final da beluga é
        # sempre ``base + acumulado``.
        self.beluga_base_rotation_y = self.beluga_obj.rotation_y
        self.objects.append(self.beluga_obj)

        # ============================================================
        #  Cabine de comando (interior do submarino)
        # ============================================================
        # A cabine principal fica próxima à PROA (Z+).  Em
        # coordenadas de mundo, o casco vai de Z ≈ -25 (popa) até
        # Z ≈ +21.6 (proa) com a escala SUB_SCALE=2.5.  O piso
        # interno (hull-following) cobre ~Z ∈ [-22, +20], mas as
        # extremidades em Z são estreitas: por volta de Z=+18 a
        # meia-largura cai para 3.14 m e em Z=+20 já são só 2.6 m.
        # Por isso colocamos a cadeira em Z=+16 e a estação um
        # pouco à frente (Z=+18.6) — quase na proa, mas com folga
        # confortável para o joystick e a vista do piloto.

        # ---- Cadeira do piloto -------------------------------------
        # ``cadeira.obj`` (Sci-fi Chair 2) AABB local:
        #     X∈[-1.69, +1.71]  Y∈[-0.14, +6.36]  Z∈[-5.19, -1.65]
        #     tamanho ≈ (3.40, 6.50, 3.54)
        # Em escala 0.25 ficamos com ~0.85 m de largura, ~1.6 m de
        # altura, ~0.88 m de profundidade — proporção humana de
        # cadeira de comando.  Como o AABB em Z é todo negativo
        # (centro local Z ≈ -3.42), compensamos a translação:
        #     chair_y = piso - Y_local_base * scale  (faz a base
        #         da cadeira pousar exatamente no piso)
        #     chair_z = alvo_world - Z_local_center * scale (faz o
        #         centro da cadeira coincidir com o alvo no mundo)
        cockpit_chair_z = 16.0
        chair_scale = 0.25
        chair_floor_y = 3.5
        chair_local_base_y = -0.14
        chair_local_center_z = (-5.19 + -1.65) / 2.0  # ≈ -3.42
        chair_y = chair_floor_y - chair_local_base_y * chair_scale
        chair_z = cockpit_chair_z - chair_local_center_z * chair_scale
        self.objects.append(Object3D(
            model=models["cadeira"],
            # ``+2.0`` desloca a cadeira mais para a proa, encostando
            # a costas no fim do corredor para deixar mais espaço de
            # ergonomia entre cadeira e console.
            translation=(0.0, chair_y, chair_z + 2.0),
            # Rotação 0: o "para frente" do modelo já é +Z (modelo
            # foi exportado encarando para a proa).
            rotation_y=math.radians(0.0),
            scale_xyz=(chair_scale, chair_scale, chair_scale),
        ))

        # ---- Estação de monitoramento (console à frente da cadeira) -
        # ``estacao.obj`` é composta de duas submalhas:
        #     'table'           Y∈[0, 0.76]  (mesa de 76 cm de altura)
        #     'hologram_glass'  X∈[-0.33,-0.29]  Y∈[0.76, 1.41]
        #         (uma "parede" vertical fina, a tela holográfica
        #          colada na borda esquerda da mesa)
        # AABB total: X∈[-0.45,+0.57]  Y∈[0.00,+1.41]  Z∈[-1.01,+1.01].
        # Modelo já está em metros, então escala 1.0 funciona.
        #
        # Truque importante: aplicando rotação Y=+90° à matriz, o
        # vetor (x,y,z) vira (z, y, -x).  Isso significa que o lado
        # -X local do glass (X ≈ -0.31) é mapeado para +Z mundo
        # (≈ +0.31), ou seja, a tela holográfica fica virada para
        # a POPA (longe do piloto).  A tampa principal — entre
        # X_world ∈ [-1.01,+1.01] no eixo girado — fica virada para
        # +Z mundo, ou seja, para o piloto (que está em Z menor).
        # Isso deixa a frente da mesa livre para apoiar o joystick
        # em pé, totalmente visível pela cadeira.
        self.objects.append(Object3D(
            model=models["estacao"],
            translation=(0.0, 3.5, chair_z + 2.6),
            rotation_y=math.radians(90.0),
            scale_xyz=(1.0, 1.0, 1.0),
        ))

        # ---- Console sci-fi adicional na POPA ----------------------
        # Mesa de comando posicionada do lado oposto à cadeira
        # (Z = -10), formando uma "segunda estação" para tripulante
        # ou apenas decorando o fundo do corredor.
        # ``mesa.obj`` AABB (em milímetros, exportado do Cinema 4D):
        #     X∈[-408.01, +407.06]   Y∈[-6.20, +707.46]   Z∈[-639.11, +639.11]
        # Escala 0.002 (mm → m, com pequeno ajuste): ~1.63 m de
        # largura, ~1.43 m de altura, ~2.56 m de profundidade — um
        # console sci-fi proporcional à largura interna do
        # submarino (~9 m externos, ~6 m úteis).
        # A "frente" do modelo aponta para +Z local; rotacionamos
        # 180° para que a parte de operação fique virada de volta
        # para a cadeira (ou seja, para +Z mundo, na direção da proa).
        mesa_scale = 0.002
        mesa_floor_y = 3.5
        mesa_local_base_y = -6.201
        mesa_local_center_z = 0.0  # AABB já é simétrica em Z
        mesa_world_z = -10.0
        mesa_y = mesa_floor_y - mesa_local_base_y * mesa_scale
        mesa_z = mesa_world_z - mesa_local_center_z * mesa_scale
        self.objects.append(Object3D(
            model=models["mesa"],
            translation=(0.0, mesa_y, mesa_z),
            rotation_y=math.radians(180.0),
            scale_xyz=(mesa_scale, mesa_scale, mesa_scale),
        ))

        # ---- Joystick em cima da estação de monitoramento -----------
        # Modelo ``joystick_2`` — .obj com 13 materiais de cor sólida
        # (gerados pelo pipeline ``per_material_color_textures`` a
        # partir do .fbx original).
        # AABB local (unidades do 3ds Max ≈ centímetros):
        #     X∈[-3.05, +3.05]   Y∈[0.00, +8.43]   Z∈[-5.39, +5.39]
        # A base já está em Y=0, então o modelo "em pé" não precisa
        # de extra_rotation.  Em escala 0.04: ~24 cm de largura,
        # ~34 cm de altura, ~43 cm de profundidade — porte realista
        # de joystick UAV de mesa.  Posicionado em cima da tampa
        # frontal da monitoring station (Y=4.10 m, encaixado na
        # superfície da mesa).
        joystick_scale = 0.04
        joystick_local_center_x = 0.0    # AABB simétrico em X
        joystick_local_base_y = 0.0      # base já em Y=0
        joystick_local_center_z = 0.0    # AABB simétrico em Z
        joystick_target_x = 0.0
        joystick_target_base_y = 4.10
        joystick_target_z = chair_z + 2.10
        self.objects.append(Object3D(
            model=models["joystick"],
            translation=(
                # Mesma fórmula da cadeira: alvo no mundo - centro
                # local * escala, garantindo que o centro do AABB
                # encoste exatamente no ponto desejado.
                joystick_target_x - joystick_local_center_x * joystick_scale,
                joystick_target_base_y - joystick_local_base_y * joystick_scale,
                joystick_target_z - joystick_local_center_z * joystick_scale,
            ),
            rotation_y=0.0,
            scale_xyz=(joystick_scale, joystick_scale, joystick_scale),
        ))

        # Estado interativo (escala da orca, rotação da beluga).
        self.state = SceneState()

        # Habilita teste de profundidade para que objetos atrás de
        # outros sejam descartados pelo z-buffer.  ``GL_LESS`` é o
        # padrão: só desenha se o pixel novo for mais perto.
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)

    # ============================================================
    #  Decoração procedural do exterior (corais + pedras + algas)
    # ============================================================

    def _populate_decor_grid(
        self,
        models: dict,
        cell_size: float,
        x_range: tuple,
        z_range: tuple,
        sub_exclusion_half: tuple,
        reserved_cells: tuple,
        coral_scale_range: tuple,
        pedra_scale_range: tuple,
        min_pair_distance: float,
        seed: int,
        cell_step: int = 1,
        coral_count_range: tuple = (1, 1),
        pedra_count_range: tuple = (1, 1),
        alga_scale_range: tuple = (0.4, 1.2),
        alga_count_range: tuple = (0, 0),
    ) -> None:
        """Espalha corais, pedras e algas pelo leito marinho usando uma grade 2D.

        A área 2D definida por ``x_range`` × ``z_range`` (em metros, no
        plano XZ do mundo) é dividida em células quadradas de lado
        ``cell_size``.  Apenas uma célula a cada ``cell_step`` em cada
        eixo é populada — então ``cell_step=3`` resulta em
        aproximadamente 1/9 das células ocupadas, deixando o resto
        do chão "respirar".

        Células ignoradas:
            * as que estão dentro da caixa de exclusão do submarino
              (centradas em |x| < ``sub_exclusion_half[0]`` AND
              |z| < ``sub_exclusion_half[1]``);
            * as listadas explicitamente em ``reserved_cells``
              (mecanismo legado para reservar posições de objetos
              especiais — atualmente vazio).

        Para cada célula populada sorteamos quantos corais, pedras e
        algas serão colocados (``randint`` com extremos inclusivos
        em cada *_count_range).  Faixas que incluem 0 permitem que
        a célula fique sem aquele tipo de objeto, ex.:
        ``coral_count_range=(0, 1)`` deixa ~50 % de chance de
        nenhum coral.  ``alga_count_range`` tem padrão ``(0, 0)``
        para que callers que não passam algas as ignorem.

        Parâmetros geométricos por objeto sorteados na célula:
            * jitter de XZ a partir do centro: ±35 % do ``cell_size``
              (definido localmente como ``jitter = cell_size * 0.35``);
            * escala uniforme dentro do range correspondente;
            * rotação Y aleatória em [0°, 360°).

        Quando uma célula tem coral E pedra, a primeira pedra é
        re-amostrada até 6 vezes para tentar ficar a pelo menos
        ``min_pair_distance`` metros do primeiro coral — assim
        evitamos pares "encavalados" que ficariam visualmente
        ruins.  Como é "best-effort", se as 6 tentativas falharem,
        a posição final ainda é aceita (raríssimo, dado o jitter).

        ``seed`` controla a RNG: mesmo seed ⇒ mesmo layout entre
        execuções (importante para os scripts de render terem
        screenshots reproduzíveis).
        """
        # RNG dedicada para que o seed só afete a decoração (não
        # interfere com o cardume nem com outras chamadas de
        # ``random``).
        rng = random.Random(seed)

        x0, x1 = x_range
        z0, z1 = z_range
        # Quantidade de células em cada eixo, arredondada para o
        # inteiro mais próximo.  ``max(1, ...)`` garante pelo menos
        # 1 célula caso o intervalo seja menor que ``cell_size``.
        nx = max(1, int(round((x1 - x0) / cell_size)))
        nz = max(1, int(round((z1 - z0) / cell_size)))
        cell_step = max(1, int(cell_step))

        # Alinha a "fase" do step para que a célula central da grade
        # (a do submarino) caia em uma posição mantida — isso evita
        # o caso degenerado em que a célula central seria pulada e
        # decoração apareceria espelhada em volta.
        ix_offset = (nx // 2) % cell_step
        iz_offset = (nz // 2) % cell_step

        sx_half, sz_half = sub_exclusion_half
        # Pré-calcula os centros das células reservadas para checar
        # com uma comparação de igualdade aproximada (1e-3 m).
        reserved_centers = []
        for rx, rz in reserved_cells:
            ix = int((rx - x0) // cell_size)
            iz = int((rz - z0) // cell_size)
            cx = x0 + (ix + 0.5) * cell_size
            cz = z0 + (iz + 0.5) * cell_size
            reserved_centers.append((cx, cz))

        # Quanto cada objeto pode "passear" do centro da célula.
        # 35 % do tamanho da célula evita encostar nas vizinhas e
        # mantém a sensação de grade visual sem ficar quadriculado.
        jitter = cell_size * 0.35
        coral_min, coral_max = coral_count_range
        pedra_min, pedra_max = pedra_count_range
        alga_min, alga_max = alga_count_range
        # Contadores apenas para o log de diagnóstico no fim.
        placed_coral = 0
        placed_pedra = 0
        placed_alga = 0
        empty_cells = 0
        skipped_sub = 0
        skipped_reserved = 0
        skipped_step = 0

        for ix in range(nx):
            for iz in range(nz):
                # Pula células fora da fase do step.
                if (ix - ix_offset) % cell_step != 0 \
                        or (iz - iz_offset) % cell_step != 0:
                    skipped_step += 1
                    continue

                # Centro mundial da célula atual.
                cx = x0 + (ix + 0.5) * cell_size
                cz = z0 + (iz + 0.5) * cell_size

                # Pula se cair em cima do submarino (caixa de exclusão).
                if abs(cx) < sx_half and abs(cz) < sz_half:
                    skipped_sub += 1
                    continue
                # Pula se for célula reservada.
                if any(abs(cx - rcx) < 1e-3 and abs(cz - rcz) < 1e-3
                       for rcx, rcz in reserved_centers):
                    skipped_reserved += 1
                    continue

                # Sorteia quantos objetos cada célula vai ter.
                n_coral = rng.randint(coral_min, coral_max)
                n_pedra = rng.randint(pedra_min, pedra_max)
                n_alga = rng.randint(alga_min, alga_max)

                # Coloca os corais primeiro e memoriza a posição do
                # primeiro para usar como "âncora" na separação
                # mínima com a primeira pedra.
                first_coral_xz: tuple[float, float] | None = None
                for _ in range(n_coral):
                    coral_x = cx + rng.uniform(-jitter, jitter)
                    coral_z = cz + rng.uniform(-jitter, jitter)
                    coral_s = rng.uniform(*coral_scale_range)
                    coral_rot = rng.uniform(0.0, 360.0)
                    self.objects.append(Object3D(
                        model=models["coral"],
                        translation=(coral_x, 0.0, coral_z),
                        rotation_y=math.radians(coral_rot),
                        scale_xyz=(coral_s, coral_s, coral_s),
                    ))
                    if first_coral_xz is None:
                        first_coral_xz = (coral_x, coral_z)
                    placed_coral += 1

                for k in range(n_pedra):
                    pedra_x = cx + rng.uniform(-jitter, jitter)
                    pedra_z = cz + rng.uniform(-jitter, jitter)
                    # Apenas a PRIMEIRA pedra da célula é afastada
                    # do primeiro coral.  As subsequentes ficam
                    # livres para se aglomerar (formando "pilhas"
                    # naturais de pedras), porque exigir distância
                    # mínima entre todas deixaria o resultado
                    # rígido demais.
                    if k == 0 and first_coral_xz is not None:
                        for _ in range(6):
                            if (pedra_x - first_coral_xz[0]) ** 2 \
                                    + (pedra_z - first_coral_xz[1]) ** 2 \
                                    >= min_pair_distance ** 2:
                                break
                            pedra_x = cx + rng.uniform(-jitter, jitter)
                            pedra_z = cz + rng.uniform(-jitter, jitter)
                    pedra_s = rng.uniform(*pedra_scale_range)
                    pedra_rot = rng.uniform(0.0, 360.0)
                    self.objects.append(Object3D(
                        model=models["pedra"],
                        translation=(pedra_x, 0.0, pedra_z),
                        rotation_y=math.radians(pedra_rot),
                        scale_xyz=(pedra_s, pedra_s, pedra_s),
                    ))
                    placed_pedra += 1

                # Algas: mesma lógica de jitter+escala+yaw aleatórios
                # dos corais/pedras, sem regra de distância mínima
                # (algas tendem a crescer em tufos juntos, então
                # sobreposição parcial é bem-vinda).
                for _ in range(n_alga):
                    alga_x = cx + rng.uniform(-jitter, jitter)
                    alga_z = cz + rng.uniform(-jitter, jitter)
                    alga_s = rng.uniform(*alga_scale_range)
                    alga_rot = rng.uniform(0.0, 360.0)
                    self.objects.append(Object3D(
                        model=models["alga"],
                        translation=(alga_x, 0.0, alga_z),
                        rotation_y=math.radians(alga_rot),
                        scale_xyz=(alga_s, alga_s, alga_s),
                    ))
                    placed_alga += 1

                if n_coral == 0 and n_pedra == 0 and n_alga == 0:
                    empty_cells += 1

        # Log compacto com a estatística da geração.  Útil para
        # ajustar parâmetros (ex.: se "empty_cells" estiver alto
        # demais, é sinal de que os _count_range ficaram conservadores
        # e o leito está vazio).
        print(
            f"[scene] decor grid: {nx}x{nz} cells (step={cell_step}), "
            f"placed {placed_coral} corais + {placed_pedra} pedras "
            f"+ {placed_alga} algas "
            f"(skipped {skipped_sub} sub, {skipped_reserved} reserved, "
            f"{skipped_step} by step, {empty_cells} empty)"
        )

    def _populate_fish_grid(
        self,
        models: dict,
        model_key: str,
        cell_size: float,
        x_range: tuple,
        z_range: tuple,
        cell_step: int,
        count_range: tuple,
        sub_exclusion_half: tuple,
        y_range: tuple,
        scale_range: tuple,
        seed: int,
    ) -> None:
        """Espalha um cardume de peixes flutuando na coluna d'água, em padrão de grade.

        Igual a ``_populate_decor_grid``, mas para peixes em vez de
        decoração de chão.  A diferença principal é que cada peixe
        ganha também uma altura Y aleatória no intervalo ``y_range``,
        em vez de ficar fixado em Y=0.  Resultado: cardume visual
        natural com peixes em diferentes profundidades.

            * A área XZ ``x_range`` × ``z_range`` é dividida em
              células de ``cell_size`` metros de lado.
            * Uma célula a cada ``cell_step`` (em cada eixo) é
              populada; as demais ficam vazias para que o cardume
              pareça aglomerado em vez de uniformemente denso.
            * Em cada célula populada, são jogados de
              ``count_range[0]`` a ``count_range[1]`` peixes
              (extremos inclusivos, lembrando que ``randint`` é
              fechado-fechado) com:
                  - jitter de XZ a partir do centro (40 % de
                    ``cell_size``);
                  - Y aleatório uniforme em ``y_range``;
                  - escala uniforme em ``scale_range``;
                  - rotação Y aleatória em [0°, 360°).
            * Células cujo centro cai dentro da caixa de exclusão
              do submarino (``|x| < sub_exclusion_half[0]`` AND
              ``|z| < sub_exclusion_half[1]``) são puladas, evitando
              peixes nadando dentro do casco.
        """
        # RNG dedicada (seed independente do decor grid).
        rng = random.Random(seed)

        x0, x1 = x_range
        z0, z1 = z_range
        nx = max(1, int(round((x1 - x0) / cell_size)))
        nz = max(1, int(round((z1 - z0) / cell_size)))
        cell_step = max(1, int(cell_step))

        # Mesma técnica de fase do decor grid: centra a fase em
        # torno da origem do mundo.
        ix_offset = (nx // 2) % cell_step
        iz_offset = (nz // 2) % cell_step

        sx_half, sz_half = sub_exclusion_half
        n_min, n_max = count_range
        y_min, y_max = y_range
        s_min, s_max = scale_range
        # Jitter um pouco maior (40 %) que o do decor (35 %) porque
        # peixes nadando podem se aproximar mais das vizinhas sem
        # parecer artificial — eles não estão "ancorados" no chão.
        jitter = cell_size * 0.40
        placed = 0
        skipped_sub = 0

        for ix in range(nx):
            for iz in range(nz):
                # Pula células fora da fase.
                if (ix - ix_offset) % cell_step != 0 \
                        or (iz - iz_offset) % cell_step != 0:
                    continue

                cx = x0 + (ix + 0.5) * cell_size
                cz = z0 + (iz + 0.5) * cell_size

                # Caixa de exclusão do submarino.
                if abs(cx) < sx_half and abs(cz) < sz_half:
                    skipped_sub += 1
                    continue

                count = rng.randint(n_min, n_max)
                for _ in range(count):
                    fx = cx + rng.uniform(-jitter, jitter)
                    fz = cz + rng.uniform(-jitter, jitter)
                    # Y aleatório dentro do intervalo de natação.
                    fy = rng.uniform(y_min, y_max)
                    fs = rng.uniform(s_min, s_max)
                    frot = rng.uniform(0.0, 360.0)
                    self.objects.append(Object3D(
                        model=models[model_key],
                        translation=(fx, fy, fz),
                        rotation_y=math.radians(frot),
                        scale_xyz=(fs, fs, fs),
                    ))
                    placed += 1

        print(
            f"[scene] fish grid ({model_key}): {nx}x{nz} cells "
            f"(step={cell_step}), placed {placed} fish "
            f"(skipped {skipped_sub} sub)"
        )

    # ============================================================
    #  Hooks de teclado (chamados a partir de ``main._process_held_keys``)
    # ============================================================

    def adjust_orca_scale(self, factor: float) -> None:
        """Multiplica a escala atual da orca por ``factor`` (com clamp).

        Cada toque em '[' / ']' chama este método com ``1/1.10`` e
        ``1.10``, respectivamente — então a escala cresce/decresce
        de forma geométrica enquanto a tecla é segurada.  O fator
        acumulado é travado entre 0.3× e 3.0× para evitar:

            * orcas microscópicas que somem na cena;
            * orcas gigantes que dominam o frame e atravessam
              outros modelos.
        """
        # Clamp do fator acumulado entre 0.3 e 3.0.
        self.state.orca_scale_factor = max(0.3, min(3.0, self.state.orca_scale_factor * factor))
        # Aplica no objeto: ``base_scale`` × ``factor`` em todos os eixos.
        s = self.orca_base_scale * self.state.orca_scale_factor
        self.orca_obj.scale_xyz = (s, s, s)

    # Passo padrão de rotação: π/6 ≈ 30°.  Doze toques completam
    # uma volta inteira (360°), o que dá granularidade suficiente
    # para apontar a beluga em qualquer direção principal sem
    # precisar de "fine control".
    BELUGA_ROTATION_STEP = math.pi / 6

    def rotate_beluga_step(self, delta: float | None = None) -> None:
        """Rotaciona a beluga em um passo fixo de yaw a cada toque de tecla.

        Cada chamada adiciona ``delta`` (por padrão
        ``BELUGA_ROTATION_STEP``, ≈ 30°) ao ângulo acumulado da
        beluga.  Para girar no sentido contrário, basta passar um
        ``delta`` negativo (é o que ``main.py`` faz para a tecla Q).

        A rotação real do objeto é sempre ``base + acumulado``, de
        forma que o estado pode ser zerado depois sem precisar
        recalcular a orientação do modelo.
        """
        step = self.BELUGA_ROTATION_STEP if delta is None else delta
        self.state.beluga_rotation_angle += step
        # ``rotation_y`` é lido pelo ``model_matrix`` no próximo
        # ``draw``, então a mudança aparece no próximo frame.
        self.beluga_obj.rotation_y = (
            self.beluga_base_rotation_y + self.state.beluga_rotation_angle
        )

    def update(self, dt: float) -> None:
        # Nenhuma animação contínua: toda atualização de estado é
        # disparada diretamente por eventos discretos de teclado
        # (``adjust_orca_scale`` e ``rotate_beluga_step``).
        # Mantemos o método para preservar a interface do loop
        # principal (``self.scene.update(dt)`` em main.py) e
        # facilitar a adição futura de animações temporais.
        return

    # ============================================================
    #  Renderização
    # ============================================================

    def draw(self, view: np.ndarray, proj: np.ndarray) -> None:
        # ---- 1) Domo do céu --------------------------------------
        # O domo é desenhado primeiro com depth func ``GL_LEQUAL``
        # (em vez do ``GL_LESS`` padrão).  Isso é necessário porque
        # o shader do skydome gera profundidade igual ao plano
        # distante (z_ndc = 1), e queremos que esses pixels passem
        # pelo teste para preencher o "fundo".  Em seguida
        # restauramos GL_LESS para o resto da cena.
        glDepthFunc(GL_LEQUAL)
        self.sky_program.use()
        self.sky_program.set_mat4("uView", view)
        self.sky_program.set_mat4("uProj", proj)
        self.sky_program.set_int("uPanorama", 0)
        # Ativa unidade de textura 0 e amarra o panorama nela.
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.sky_tex)
        glBindVertexArray(self.sky_vao)
        glDrawElements(GL_TRIANGLES, self.sky_indices, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glDepthFunc(GL_LESS)

        # ---- 2) Pisos e paredes da cabine ------------------------
        # A partir daqui usamos o programa "basic" (uma textura
        # difusa por submalha).  Setamos os uniforms compartilhados
        # uma única vez para evitar repetição em cada draw call.
        self.basic.use()
        self.basic.set_mat4("uView", view)
        self.basic.set_mat4("uProj", proj)
        self.basic.set_int("uDiffuse", 0)
        self.basic.set_float("uUVTile", 1.0)

        # Chão de areia externo: matriz identidade porque a
        # geometria já foi gerada em coordenadas de mundo.
        self.basic.set_mat4("uModel", utils.identity())
        draw_model(self.outdoor_floor)

        # Piso interno do submarino: aplica apenas a translação Y
        # configurada (a malha já vem com X/Z em coords de mundo).
        if self.indoor_floor is not None:
            self.basic.set_mat4("uModel", utils.translate(*self.indoor_floor_offset))
            draw_model(self.indoor_floor)

        # Paredes da cabine: atualmente desligadas, mas o suporte
        # fica preparado caso queiramos habilitar uma "casca" interna.
        if self.cabin_walls is not None:
            self.basic.set_mat4("uModel", utils.identity())
            draw_model(self.cabin_walls)

        # ---- 3) Modelos importados (.obj) ------------------------
        # Cada Object3D constrói sua matriz a partir da composição
        # T * R_y * S (mais hooks opcionais), e o drawcall abaixo
        # aplica essa matriz como ``uModel``.
        for obj in self.objects:
            self.basic.set_mat4("uModel", obj.model_matrix())
            self.basic.set_float("uUVTile", obj.uv_tile)
            draw_model(obj.model)
