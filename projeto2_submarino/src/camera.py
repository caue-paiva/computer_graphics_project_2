"""Câmera em primeira pessoa estilo "fly", com limites de movimento.

Esta câmera é a "olho do jogador" da cena: o mouse altera a direção
para onde ela está apontando (yaw/pitch) e o teclado a translada no
espaço de mundo.  Toda a matemática é em coordenadas de mundo, em
metros, e ângulos são guardados em radianos.

Conceitos importantes:
    * yaw   — rotação em torno do eixo vertical (Y).  Define para que
              lado a câmera está virada no plano horizontal.  Aumenta
              no sentido anti-horário visto de cima (regra da mão
              direita com Y para cima).
    * pitch — rotação em torno do eixo lateral (X local).  Define se
              a câmera olha para cima ou para baixo.  É limitado a
              ±89° para evitar o "gimbal flip" (problema clássico em
              que pitch a 90° colapsa o yaw e o frame da câmera).

Toda chamada de ``move`` é seguida de ``clamp`` para que a câmera
nunca escape do volume útil da cena (não atravesse o chão de areia
nem ultrapasse o domo do skybox).  Esses limites também impedem que
a câmera vá para regiões onde o plano de corte distante começaria
a "cortar" o cenário visivelmente.
"""

from __future__ import annotations

import math

import numpy as np

from utils import look_at


class Camera:
    def __init__(
        self,
        position: tuple[float, float, float] = (0.0, 4.0, 30.0),
        yaw: float = -math.pi / 2,
        pitch: float = -0.15,
        speed: float = 14.0,
        sensitivity: float = 0.0025,
        bounds_xz: tuple[float, float] = (-100.0, 100.0),
        bounds_y: tuple[float, float] = (0.4, 60.0),
    ) -> None:
        # Posição é guardada em float32 porque é o que enviamos para o
        # shader (matriz de visão) — manter o mesmo tipo evita conversões
        # implícitas em cada frame.
        self.position = np.asarray(position, dtype=np.float32)
        self.yaw = yaw
        self.pitch = pitch
        # Velocidade em metros por segundo (aplicada com dt no `move`).
        self.speed = speed
        # Quantos radianos de yaw/pitch a câmera ganha por pixel de
        # mouse.  0.0025 rad/pixel ≈ ~0.143°/pixel, valor confortável
        # para uma janela 1280×720 sem precisar arrastar muito.
        self.sensitivity = sensitivity
        # Caixa axis-aligned em coordenadas de mundo na qual a câmera
        # pode se mover (bounds_xz é aplicado tanto a X quanto a Z).
        self.bounds_xz = bounds_xz
        self.bounds_y = bounds_y
        # "Up" do mundo é fixo: usamos Y para cima em toda a cena.
        self.world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    def forward(self) -> np.ndarray:
        # Conversão clássica de yaw/pitch para vetor unitário 3D em
        # coordenadas esféricas alinhadas com o frame do mundo:
        #     forward.x = cos(yaw) * cos(pitch)
        #     forward.y = sin(pitch)
        #     forward.z = sin(yaw) * cos(pitch)
        # Como yaw e pitch são limitados, o vetor nunca degenera, mas
        # fazemos a normalização explícita para blindar contra erros
        # acumulados em float32 ao longo de muitos frames.
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        f = np.array([cy * cp, sp, sy * cp], dtype=np.float32)
        return f / np.linalg.norm(f)

    def right(self) -> np.ndarray:
        # "right" = forward × world_up.  Isso devolve o eixo local X da
        # câmera perpendicular ao "para frente" e paralelo ao plano
        # XZ — exatamente o que queremos para movimento lateral (A/D).
        f = self.forward()
        r = np.cross(f, self.world_up)
        n = np.linalg.norm(r)
        # Caso de borda: se a câmera estivesse olhando exatamente para
        # cima ou para baixo, forward seria paralelo a world_up e o
        # produto vetorial daria zero.  Como limitamos pitch a ±89°
        # isso na prática nunca acontece, mas devolvemos um vetor
        # "right" canônico para não retornar NaN.
        if n < 1e-6:
            return np.array([1.0, 0.0, 0.0], dtype=np.float32)
        return r / n

    def add_yaw_pitch(self, dyaw: float, dpitch: float) -> None:
        # `dyaw` e `dpitch` chegam em pixels de mouse; convertemos para
        # radianos multiplicando pela sensibilidade.
        self.yaw += dyaw * self.sensitivity
        self.pitch += dpitch * self.sensitivity
        # Trava do pitch para evitar o "gimbal flip": se o pitch chega
        # a ±90° o vetor right colapsa no eixo Y e o controle fica
        # confuso (a câmera começa a girar em torno de si mesma).  89°
        # mantém o comportamento natural sem deixar o jogador "virar
        # a cabeça do avesso".
        max_pitch = math.radians(89.0)
        self.pitch = max(-max_pitch, min(max_pitch, self.pitch))

    def move(self, fwd: float, side: float, vertical: float, dt: float) -> None:
        # Atalho: se nenhum botão direcional foi pressionado, evitamos
        # cálculos de matriz e idas a numpy desnecessárias.
        if fwd == 0.0 and side == 0.0 and vertical == 0.0:
            return
        f = self.forward()
        # Projetamos o "para frente" no plano XZ para que andar em W/S
        # NÃO mude a altura da câmera, mesmo que o jogador esteja
        # olhando para cima ou para baixo.  Sem essa projeção, andar
        # com o pitch inclinado faria o piloto "voar" subindo o tempo
        # todo (comportamento típico de jogo de tiro fica esquisito
        # para explorar uma cena estática).
        f_xz = np.array([f[0], 0.0, f[2]], dtype=np.float32)
        n = np.linalg.norm(f_xz)
        if n > 1e-6:
            f_xz /= n
        r = self.right()
        # `delta` em metros: fwd/side/vertical são valores em [-1, 1]
        # vindos do `_process_held_keys`, e speed*dt traduz para metros
        # por frame.  O movimento vertical é livre (não projetado) —
        # Space sobe e Shift desce em linha reta.
        delta = (f_xz * fwd + r * side) * (self.speed * dt)
        delta[1] += vertical * self.speed * dt
        self.position = self.position + delta
        self.clamp()

    def clamp(self) -> None:
        # Trava a posição dentro dos limites configurados para que a
        # câmera nunca afunde no chão de areia nem suba mais alto que
        # o domo de céu.  Mesmo intervalo em X e Z (bounds_xz) já é
        # suficiente porque a cena é aproximadamente quadrada.
        x_lo, x_hi = self.bounds_xz
        y_lo, y_hi = self.bounds_y
        self.position[0] = float(np.clip(self.position[0], x_lo, x_hi))
        self.position[1] = float(np.clip(self.position[1], y_lo, y_hi))
        self.position[2] = float(np.clip(self.position[2], x_lo, x_hi))

    def view_matrix(self) -> np.ndarray:
        # `look_at` constrói a matriz de visão olhando da posição atual
        # para um ponto a uma unidade na direção de forward.  Esse é o
        # padrão para câmeras tipo FPS: o "alvo" se move junto com a
        # câmera para que ela sempre olhe na direção apontada pelos
        # ângulos yaw/pitch.
        return look_at(self.position, self.position + self.forward(), self.world_up)
