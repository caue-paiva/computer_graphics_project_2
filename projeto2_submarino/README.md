# Projeto 2 — Cenário Submarino 3D

> Trabalho da disciplina **SCC0250 – Computação Gráfica (USP, 2026.1)**.
>
> Este documento foi escrito para ser autossuficiente: lendo só o README dá pra entender **o que o projeto é, como rodar, como cada peça do código foi implementada e por que cada decisão foi tomada**. Se você é a dupla pegando o projeto agora, o roteiro é: ler a seção 1 pra contexto, depois seguir a ordem das seções 2 → 11, e usar a 12 como referência rápida quando precisar mexer em alguma coisa.

---

## Sumário

1. [O que é o projeto](#1-o-que-é-o-projeto)
2. [Tecnologias usadas](#2-tecnologias-usadas)
3. [Estrutura de diretórios](#3-estrutura-de-diretórios)
4. [Como rodar](#4-como-rodar)
5. [O que tem na cena](#5-o-que-tem-na-cena)
6. [Controles](#6-controles)
7. [Arquitetura do código (`src/`)](#7-arquitetura-do-código-src)
   - 7.1 `main.py` — bootstrap + loop principal
   - 7.2 `camera.py` — câmera FPS
   - 7.3 `utils.py` — matrizes 4×4
   - 7.4 `model.py` — loader de `.obj` + draw
   - 7.5 `shader.py` — wrapper de programs OpenGL
   - 7.6 `texture.py` — loader de texturas 2D
   - 7.7 `scene.py` — montagem e renderização da cena
8. [Shaders GLSL (`shaders/`)](#8-shaders-glsl-shaders)
9. [Pipeline de assets (`tools/build_assets.py`)](#9-pipeline-de-assets-toolsbuild_assetspy)
10. [Decisões de design & truques importantes](#10-decisões-de-design--truques-importantes)
11. [Scripts auxiliares (`tools/`)](#11-scripts-auxiliares-tools)
12. [Como adicionar / editar coisas (guia rápido)](#12-como-adicionar--editar-coisas-guia-rápido)
13. [Troubleshooting](#13-troubleshooting)
14. [Checklist do edital](#14-checklist-do-edital)

---

## 1. O que é o projeto

Um cenário 3D interativo onde o usuário "mergulha" em torno de um submarino amarelo apoiado num leito de areia. A câmera é em primeira pessoa estilo FPS (mouse + WASD + Space/Shift) e o usuário pode atravessar tudo livremente. O cenário inclui:

- **Exterior**: chão de areia 4K que se estende até o horizonte, skybox panorâmico oceânico, decoração procedural (corais, pedras e algas espalhados em uma grade que cobre toda a área), cardume de peixes-palhaço flutuando em alturas variadas, uma orca solitária e uma beluga grande.
- **Interior**: corredor metálico que **segue a curva real do casco do submarino** (cobre todo o comprimento da popa à proa) com cadeira sci-fi do piloto, estação de monitoramento + tela holográfica, joystick UAV apoiado em pé, e um console sci-fi de comando na popa.

Dois objetos da cena são interativos via teclado:
- A **orca** pode ter sua escala ampliada/reduzida com `]`/`[` (clamp em 0.3× a 3.0× do tamanho original).
- A **beluga** pode ser girada em torno do eixo vertical em qualquer sentido com `R`/`Q` (passos discretos de 30°, com auto-repeat enquanto a tecla é segurada).

Restrições do edital atendidas:
- OpenGL **3.3 core profile**, sem nenhuma chamada do pipeline fixo (`glRotate`, `glTranslate`, `glScale`, `glBegin/glEnd`, `glPushMatrix`, …).
- Toda transformação é montada como matriz 4×4 em `numpy` e enviada como uniform `mat4` para os shaders.
- **Sem iluminação dinâmica** — o pipeline é "unlit" (a cor de cada pixel vem direto da textura difusa amostrada).
- **Mais de 6 modelos `.obj`** importados e texturizados (são 11: submarino, coral, pedra, alga, cadeira, estação, mesa, joystick_2, peixe-palhaço, orca, beluga).
- Todos os modelos têm pelo menos uma textura difusa válida (mesmo aqueles cujo download original não trazia textura — mais sobre isso na seção 9).

---

## 2. Tecnologias usadas

| Ferramenta | Para quê |
|---|---|
| **Python 3.12** | Linguagem hospedeira. Importante: usamos especificamente 3.12 porque o `assimp_py` (lê `.fbx`/`.blend`) não tem wheel pra 3.13+ no momento. |
| **PyOpenGL** | Bindings do OpenGL 3.3 core (chamadas `gl*`). |
| **GLFW** (via `pyglfw`) | Cria a janela, contexto OpenGL, captura teclado/mouse. |
| **numpy** | Toda a álgebra linear (matrizes 4×4, vetores). Subimos os arrays direto pros shaders como uniforms. |
| **Pillow (PIL)** | Decodifica PNG/JPG das texturas e gera as texturas procedurais (chapa de metal, JPEGs sólidos por material). |
| **assimp_py** | Lê formatos não-`.obj` (`.fbx`, `.blend`) sem precisar do Blender desktop. Usado no pipeline de build, não no runtime. |

`requirements.txt` tem as versões fixadas. `pip install -r requirements.txt` cobre tudo.

---

## 3. Estrutura de diretórios

```
projeto_2/
├── objetos/                      <-- DOWNLOADS BRUTOS (uma pasta acima do projeto)
│   ├── alga/                     fonte .obj + textura difusa
│   ├── beluga/                   fonte .obj + .mtl
│   ├── cadeira/                  fonte .obj + .mtl multi-material
│   ├── joysticker_2/extracted/   fonte .fbx (input do build)
│   ├── monitoring-station/       fonte .obj + 2 PNGs Base color
│   ├── orca/                     fonte .obj + .mtl
│   ├── peixe_palhaco/obj_extracted/   fonte .obj + .mtl
│   └── table/                    fonte .obj zipado dentro do .fbx (HUDs embutidos)
│
└── projeto2_submarino/           <-- O PROJETO EM SI
    ├── README.md                 este arquivo
    ├── requirements.txt          dependências Python
    │
    ├── src/                      código de runtime
    │   ├── main.py               janela GLFW + loop principal + input
    │   ├── camera.py             câmera FPS (yaw/pitch + clamp)
    │   ├── utils.py              matrizes 4×4 (translate/rotate/scale/perspective/look_at)
    │   ├── model.py              carregador de .obj + draw_model
    │   ├── shader.py             wrapper de glCompileShader/glLinkProgram
    │   ├── texture.py            carregador de textura (PIL → glTexImage2D)
    │   └── scene.py              montagem da cena (objetos, decoração, animação)
    │
    ├── shaders/                  GLSL 330 core
    │   ├── basic.vert/.frag      pipeline padrão (textura difusa)
    │   └── skydome.vert/.frag    skybox panorâmico equirretangular
    │
    ├── assets/
    │   ├── modelos/              .obj + .mtl + texturas POR MODELO (gerados pelo build)
    │   │   ├── submarino/
    │   │   ├── coral/  pedra/  alga/
    │   │   ├── cadeira/  estacao/  mesa/  joystick_2/
    │   │   └── peixe_palhaco/  orca/  beluga/
    │   └── texturas/             texturas globais
    │       ├── chao_externo/coast_sand_05_diff_4k.jpg
    │       ├── interior/metal_brushed.jpg
    │       └── skybox/skyrender.png
    │
    ├── tools/                    pipeline + scripts auxiliares
    │   ├── build_assets.py       converte objetos/ + build/staging/ → assets/modelos/
    │   ├── smoke_test.py         monta a cena e renderiza 1 frame oculto
    │   └── render_exterior_decor.py   gera 6 PNGs de validação visual
    │
    └── build/                    saídas / arquivos intermediários
        ├── staging/              fontes brutas dos modelos que vêm já em .obj
        │   ├── coral/  pedra/  submarine_v2/  table/
        └── exterior_*.png        screenshots gerados por render_exterior_decor.py
```

**Importante:** `assets/modelos/` já está no commit, então **você não precisa rodar o build pra rodar o app**. O build só é necessário se quiser regerar tudo do zero (por exemplo, depois de trocar um modelo na pasta `objetos/`).

---

## 4. Como rodar

A partir da raiz do projeto (`projeto2_submarino/`):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1) (opcional) Regerar todos os assets do zero:
python tools/build_assets.py

# 2) Smoke test (sobe a cena, renderiza 1 frame oculto, sai):
python tools/smoke_test.py

# 3) Aplicação interativa:
python src/main.py
```

### Fluxo de dados (de download cru a pixel na tela)

```
        ┌─────────────────┐
        │   objetos/      │  downloads .obj/.fbx + texturas
        └────────┬────────┘
                 │
                 │  build_assets.py
                 │   (lê fontes, copia/converte/triangula,
                 │    gera .obj + .mtl + textura difusa)
                 ▼
        ┌────────────────────┐
        │ assets/modelos/    │  pronto pra rodar
        └────────┬───────────┘
                 │
                 │  Model.load_obj  (em src/model.py)
                 │   parsea .obj+.mtl, dedup vértices,
                 │   sobe VAO/VBO/EBO, carrega texturas
                 ▼
            ┌────────┐
            │  GPU   │  VAO + textures
            └────┬───┘
                 │
                 │  scene.draw(view, proj)
                 │   ativa shader, manda matrizes,
                 │   binda textura, glDrawElements
                 ▼
              [pixel]
```

---

## 5. O que tem na cena

### Exterior
- **Submarino amarelo** (1 modelo central), escala 2.5× → ~46.8 m de comprimento × 9.1 m de largura × 16.7 m de altura. Está apoiado a 1 m do leito de areia.
- **Decoração procedural do leito** — gerada em runtime a partir de uma RNG semeada (`seed=42`):
  - área coberta: 400 m × 400 m centrada na origem (todo o piso de areia);
  - grade de células de 10 m × 10 m (40 × 40 = 1.600 células);
  - apenas 1 célula a cada 3 (em cada eixo) é populada → ~178 células ativas (~11 %);
  - cada célula populada sorteia 0–1 coral, 0–1 pedra e 0–1 alga, com escala/rotação/jitter aleatórios;
  - células dentro da "caixa de exclusão" do submarino (|x| < 6 m AND |z| < 25 m) são ignoradas;
  - resultado típico: ~70 corais + ~90 pedras + ~90 algas (272 instâncias).
- **Cardume de peixes-palhaço** — gerado com a mesma técnica, mas em 3D:
  - cell_step 6 (densidade ~3% das células);
  - 1–2 peixes por célula populada;
  - altura aleatória `y ∈ [1.5, 9] m` (peixes flutuando em diferentes profundidades);
  - escala aleatória (0.35× a 0.60×).
  - resultado típico: ~92 peixes.
- **Orca solitária** em `(45, 14, 25)` com escala 1.7×, rotacionada 210° em yaw (olhando ~na direção do submarino). É o objeto interativo de **escala**.
- **Beluga grande** em `(-35, 12 + offset, -15)` com escala 0.16×, rotacionada -45°. É o objeto interativo de **rotação**.

### Interior (cabine de comando, dentro do casco)
- **Piso interno metálico** que segue a curva do casco do submarino (mais detalhes em §10.1) — cobre quase toda a extensão Z do submarino.
- **Cadeira sci-fi do piloto** centrada no eixo X, próxima da proa (Z ≈ 18), virada para +Z.
- **Estação de monitoramento** (`estacao.obj`) à frente da cadeira, com a tela holográfica voltada para a popa e a tampa principal voltada para o piloto, dando espaço para apoiar o joystick.
- **Joystick UAV** (`joystick_2.obj`, 13 materiais com cores sólidas distintas) apoiado em pé na tampa frontal da estação, escala 0.04× (~24×34×43 cm).
- **Console sci-fi adicional** na popa (`mesa.obj`), do lado oposto à cadeira, formando uma "segunda estação".

---

## 6. Controles

| Tecla | Ação |
|---|---|
| `W` / `S` | Andar para frente / para trás (projetado no plano XZ — não voa só por olhar pra cima) |
| `A` / `D` | Strafe lateral esquerda / direita |
| `Espaço` / `Shift esquerdo` | Subir / descer (livre, em linha reta) |
| Mouse | Olhar ao redor (yaw + pitch, cursor capturado) |
| `P` | Alternar wireframe ⇄ preenchido |
| `]` / `[` | **Aumentar / diminuir escala da orca** (rate-limited, segurar funciona) |
| `R` / `Q` | **Rotacionar a beluga** num sentido / no outro (rate-limited, segurar funciona) |
| `Esc` | Sair |

**Detalhe de implementação dos controles interativos:**
- `]` / `[` multiplicam o fator de escala atual da orca por **1.10** ou **1/1.10** a cada disparo. O fator acumulado é travado entre **0.3× e 3.0×** para a orca não desaparecer nem dominar a cena.
- `R` / `Q` adicionam ou subtraem **π/6 rad ≈ 30°** ao ângulo acumulado da beluga.
- Ambas as teclas têm **rate-limit de 0.12 s** (~8 disparos por segundo) — sem isso, segurar a tecla a 60 FPS aplicaria 30 incrementos por segundo e a orca encolheria/inflaria instantaneamente até o clamp.
- A câmera é **clampada** em `x, z ∈ [-100, 100]` e `y ∈ [0.4, 60]` para nunca furar o piso ou o céu.

---

## 7. Arquitetura do código (`src/`)

### 7.1 `main.py` — bootstrap + loop principal

Responsabilidades:
1. Inicializar GLFW pedindo um contexto **OpenGL 3.3 Core Profile** com `OPENGL_FORWARD_COMPAT=True` (necessário no macOS para de fato obter 3.3+).
2. Criar a janela 1280×720, capturar o cursor (`CURSOR_DISABLED` libera movimento ilimitado do mouse), instalar callbacks de teclado, mouse e resize.
3. Configurar o estado inicial do OpenGL: `glClearColor` em tom "fundo do mar", `GL_DEPTH_TEST` habilitado, `GL_CULL_FACE` **desabilitado** (vários `.obj` importados têm winding inconsistente entre faces; cull deixaria buracos).
4. Instanciar `Scene()` (que carrega todos os modelos) e `Camera(...)` (posicionada em `(35, 12, 35)`, olhando aproximadamente para a origem).
5. Rodar o loop:
   ```python
   while not should_close:
       dt = min(now - last_time, 0.1)   # clamp para sobreviver a hangs
       _process_held_keys(dt)            # WASD, Space/Shift, [/], R/Q
       scene.update(dt)
       proj = perspective(60°, aspect, 0.1, 600)
       view = camera.view_matrix()
       glClear(COLOR | DEPTH)
       scene.draw(view, proj)
       glfw.swap_buffers + poll_events
   ```
6. **Separação de eventos**: `_on_key` trata só PRESSES discretos (Esc, P para wireframe). Tudo que precisa repetir enquanto segurado é **lido por polling** todo frame em `_process_held_keys`. Isso é o que viabiliza movimento suave da câmera proporcional a `dt` e o auto-repeat das teclas interativas com rate-limit.

### 7.2 `camera.py` — câmera FPS

Câmera "fly" em primeira pessoa. Mantém:
- `position` (vec3 em metros);
- `yaw` e `pitch` em radianos;
- `speed = 14.0` m/s e `sensitivity = 0.0025` rad/pixel.

Funções principais:
- `forward()` — converte (yaw, pitch) em vetor 3D unitário com a fórmula esférica clássica:
  ```
  fwd.x = cos(yaw) * cos(pitch)
  fwd.y = sin(pitch)
  fwd.z = sin(yaw) * cos(pitch)
  ```
- `right()` — `forward × world_up`. Garante perpendicularidade ao plano XZ (movimento lateral horizontal).
- `add_yaw_pitch(dx, dy)` — recebe deltas em pixels do mouse, multiplica por sensitivity. **Pitch é travado em ±89°** para evitar gimbal flip (quando pitch = 90° o vetor right colapsa em Y).
- `move(fwd, side, vert, dt)` — projeta `forward` no plano XZ antes de aplicar `fwd`/`side` (assim WASD não faz a câmera "voar" se você estiver olhando pra cima); `vert` é livre e move a câmera direto em ±Y.
- `clamp()` — chamado depois de cada `move`; limita a posição às bounds passadas no construtor.
- `view_matrix()` — chama `look_at(eye, eye + forward, world_up)`.

### 7.3 `utils.py` — matrizes 4×4

Toda a álgebra linear do pipeline programável vive aqui. Convenções:
- Matrizes 4×4 `float32` em layout column-major (multiplicação canônica `M @ v` com `v` coluna).
- Sistema **right-handed** com **+Y up**, **-Z** para a frente da câmera.
- Ângulos em radianos.

Helpers:
- `identity()`, `translate(tx,ty,tz)`, `scale(sx,sy,sz)`, `rotate_x/y/z(rad)` — matrizes elementares.
- `perspective(fov_deg, aspect, near, far)` — projeção perspectiva right-handed que mapeia o frustum no cubo `[-1,1]³` (faixa padrão do `gl_DepthRange`).
- `look_at(eye, target, up)` — matriz de visão. Constrói os eixos `f = normalize(target-eye)`, `s = normalize(f × up)`, `u = s × f`, e empacota numa matriz 4×4 que leva pontos do mundo para o espaço de câmera.
- `asset(*parts)` — resolve um caminho de asset relativo à raiz do projeto (`<repo>/projeto2_submarino/...`).

Ao subir uma matriz pro shader, usamos `transpose=GL_TRUE` no `glUniformMatrix4fv` (`shader.set_mat4`) para que o GLSL receba o layout `mat4` padrão.

### 7.4 `model.py` — loader de `.obj` + draw

Classe principal: `Model.load_obj(path)`. Formato de arquivo suportado:
- Wavefront `.obj` com `v` (vertex), `vt` (UV), `f` (face), `mtllib`, `usemtl`. Normais (`vn`) são lidas mas ignoradas porque o pipeline é unlit.
- Multi-material via múltiplos `usemtl`: cada switch inicia uma **submalha** (`SubMesh`) que será desenhada com sua textura difusa específica.
- Faces de N vértices são fan-trianguladas (`v0, vi, v(i+1)`).
- Pares `(v_idx, vt_idx)` são **deduplicados** num dict para minimizar o tamanho do VBO (cada combinação única vira 1 vértice GPU).
- O `.mtl` (parseado em `_parse_mtl`) só lê `newmtl` e `map_Kd` — outros campos são ignorados.

Estrutura GPU resultante:
- **1 VAO** por modelo, com layout interleaved `[x, y, z, u, v]` (stride = 20 bytes).
- **1 EBO** por modelo, com índices `uint32`.
- **N texturas** (1 por material/submalha) carregadas via `texture.load_texture_2d`.

`draw_model(model)` faz `glBindVertexArray(model.vao)` uma vez e itera sobre cada submalha emitindo `glDrawElements(GL_TRIANGLES, count, GL_UNSIGNED_INT, offset)` com a textura correspondente bindada em `GL_TEXTURE0`.

### 7.5 `shader.py` — wrapper de programs OpenGL

Classe `Program` encapsula `glCreateShader / glShaderSource / glCompileShader / glAttachShader / glLinkProgram`. Aborta com `ShaderError` se a compilação ou link falhar (mostrando o log do driver).

Construtores:
- `Program(vert_src, frag_src, label)` — direto de strings.
- `Program.from_files(vert_path, frag_path, label)` — lê os arquivos e delega.

Setters de uniforms com **cache de localização**: `_loc(name)` consulta o location uma única vez e guarda no dicionário (chamadas subsequentes evitam o `glGetUniformLocation`). Helpers: `set_int`, `set_float`, `set_vec3`, `set_mat4`.

### 7.6 `texture.py` — loader de texturas 2D

Função `load_texture_2d(path, wrap_repeat=True, flip_y=True)`:
1. Abre a imagem com PIL e converte para RGBA.
2. Se `flip_y=True` (padrão), aplica flip vertical — necessário porque PIL decodifica com origem na quina superior-esquerda enquanto `glTexImage2D` espera origem na inferior-esquerda.
3. Sobe para o GPU como `GL_RGBA`/`GL_UNSIGNED_BYTE`, gera mipmaps e configura filtros: `GL_LINEAR_MIPMAP_LINEAR` (minificação trilinear) + `GL_LINEAR` (magnificação bilinear).
4. **Wrap mode**: `GL_REPEAT` para texturas tile-áveis (areia, metal); `GL_CLAMP_TO_EDGE` para texturas que não devem repetir (skybox).
5. **Fallback**: se o arquivo não existe ou falha, retorna uma textura **1×1 magenta** (`#FF00C8`) e imprime warning. Isso evita crash em desenvolvimento — qualquer modelo com textura faltando aparece magenta e fica óbvio o que precisa ser corrigido.

### 7.7 `scene.py` — montagem e renderização da cena

É o módulo maior do projeto (~600 linhas). Vou destrinchar por função:

#### 7.7.1 Primitivas geradas em runtime (não vêm de `.obj`)
- `_make_textured_model(positions_uvs, indices, diffuse_path, ...)` — encapsula a criação de VAO/VBO/EBO + carregamento de textura num `Model` de uma submalha. Reutilizado pelos helpers abaixo.
- `make_floor(size, tex, tile, y)` — quad plano centrado, na altura Y indicada, com tile UV configurável. Usado no chão de areia (size=400, tile=40 → 1 tile a cada 10 m).
- `make_rect_floor(sx, sz, tex, tile_x, tile_z, y)` — variante retangular com tile independente em cada eixo.
- `make_box(cx,cy,cz, sx,sy,sz, tex, tile, inward_normals)` — caixa AABB. `inward_normals=True` inverte o winding para que a câmera veja o lado de **dentro** (útil para cabines).
- `make_sky_sphere(radius, segments, rings)` — esfera UV-mapeada para o skybox. O winding é escolhido para que as normais apontem **para dentro** (a câmera fica no centro do domo). Retorna `(vao, n_indices)` para drawcall direto sem `Model`.
- `make_hull_following_floor(...)` — peça de engenharia da cena. Detalhada em §10.1.

#### 7.7.2 `Object3D` e `SceneState` (dataclasses)

```python
@dataclass
class Object3D:
    model: Model
    translation: tuple[float,float,float]
    rotation_y: float                    # radianos
    scale_xyz: tuple[float,float,float]
    extra_rotation: callable | None      # opcional: matriz extra (rotação)
    extra_translation: callable | None   # opcional: matriz extra (translação)
    uv_tile: float = 1.0
```

Cada objeto da cena é um `Object3D` que combina um `Model` (geometria + texturas) com uma transformação afim. A matriz modelo é montada em `model_matrix()`:

```
M = T_world * (T_extra) * R_y * (R_extra) * S
```

(ordem clássica: aplicar `M @ v` escala primeiro, gira em seguida, translada por último).

`SceneState` é uma dataclass minúscula com `orca_scale_factor: float` e `beluga_rotation_angle: float` — só os valores que o teclado altera.

#### 7.7.3 `Scene.__init__` — montagem da cena

1. **Programs**: carrega `basic` (geometria com textura) e `skydome` (skybox panorâmico).
2. **Skybox**: gera o domo com `make_sky_sphere(radius=250)` e carrega `skyrender.png` com `flip_y=True` (único asset que precisa de flip extra).
3. **Chão de areia externo**: `make_floor(size=400, tex=sand, tile=40, y=0)`.
4. **Piso interno hull-following**: chama `make_hull_following_floor` em Y=3.5 (mais sobre isso em §10.1).
5. **Carrega 11 modelos** via helper `load(name)` que faz `Model.load_obj("assets/modelos/<name>/<name>.obj")`.
6. **Posiciona o submarino** no centro com escala 2.5× e Y deslocado 1 m do leito.
7. **Decoração procedural** via `_populate_decor_grid` (corais + pedras + algas).
8. **Cardume** via `_populate_fish_grid` (peixes-palhaço em alturas variadas).
9. **Orca + Beluga** posicionadas manualmente como referência interativa, e guarda `self.orca_obj` / `self.beluga_obj` para conseguir mexer nelas pelos callbacks.
10. **Interior**: cadeira do piloto, estação de monitoramento, joystick em cima da estação, mesa de comando na popa.
11. Inicializa `self.state = SceneState()`.
12. Liga `GL_DEPTH_TEST` com `GL_LESS`.

Cada bloco de posicionamento de modelo usa o **AABB local do `.obj`** (lido visualmente uma vez e anotado como literal) para calcular a translação:
```
world_y = piso_y - aabb_local_min_y * scale
world_z = alvo_z - aabb_local_center_z * scale
```
Isso garante que a base do modelo encoste exatamente no piso (sem flutuar nem afundar) e o centro caia onde a gente quer no mundo.

#### 7.7.4 `_populate_decor_grid` — decoração procedural

Algoritmo:
```
para cada (ix, iz) na grade nx × nz:
    se (ix - offset_x) % cell_step != 0 ou (iz - offset_z) % cell_step != 0:
        pula                          # densidade
    cx, cz = centro mundial da célula
    se |cx| < sub_exclusion_x e |cz| < sub_exclusion_z:
        pula                          # exclusion box do submarino
    n_coral = randint(0, 1)           # ou outro range
    n_pedra = randint(0, 1)
    n_alga  = randint(0, 1)
    coloca cada um com:
        translação = centro ± uniform(-jitter, +jitter), com jitter = 35 % do cell_size
        escala uniforme em scale_range
        rotação_y uniforme em [0°, 360°)
    se houver coral E pedra na mesma célula:
        re-amostra a primeira pedra até 6 vezes pra ficar a >= min_pair_distance do coral
```

A RNG usa `random.Random(seed)` (não a global) para que a decoração seja reprodutível e não interfira com outros sorteios. `seed=42` para o decor, `seed=137` para o cardume.

#### 7.7.5 `_populate_fish_grid` — cardume

Mesma estrutura, com 3 diferenças:
1. Cada peixe ganha **`y` aleatório** em `y_range` (decoração tem `y=0`).
2. **`cell_step=6`** (densidade ainda menor — peixes são "marcantes").
3. **Sem regra de distância mínima** — peixes podem se aproximar entre si sem parecer artificial (eles se movem na coluna d'água).

#### 7.7.6 Hooks de teclado

```python
def adjust_orca_scale(self, factor: float) -> None:
    self.state.orca_scale_factor = clamp(self.state.orca_scale_factor * factor, 0.3, 3.0)
    s = self.orca_base_scale * self.state.orca_scale_factor
    self.orca_obj.scale_xyz = (s, s, s)

def rotate_beluga_step(self, delta: float | None = None) -> None:
    step = delta if delta is not None else self.BELUGA_ROTATION_STEP   # π/6
    self.state.beluga_rotation_angle += step
    self.beluga_obj.rotation_y = self.beluga_base_rotation_y + self.state.beluga_rotation_angle
```

Observação importante: a beluga acumula em **um único campo** `beluga_rotation_angle`. Por isso `R` (delta positivo) e `Q` (delta negativo) trabalham no mesmo eixo — apertar Q **cancela** cliques anteriores em R, em vez de criar uma rotação combinada estranha.

#### 7.7.7 `Scene.draw(view, proj)`

Ordem de renderização por frame:
1. **Skybox** primeiro com `glDepthFunc(GL_LEQUAL)` (em vez de `LESS`). Isso é necessário porque o `skydome.vert` força `gl_Position.z = w` (profundidade no plano distante), e queremos que esses pixels **passem** o teste para preencher o fundo. Depois restauramos `GL_LESS`.
2. **Chão externo + piso interno hull-following + paredes** (paredes desligadas no momento mas o suporte está pronto).
3. **Loop sobre `self.objects`**: para cada `Object3D`, calcula `model_matrix()`, manda como uniform `uModel`, manda `uUVTile`, e chama `draw_model(obj.model)` que internamente itera nas submalhas.

---

## 8. Shaders GLSL (`shaders/`)

Quatro arquivos, todos GLSL 330 core.

### 8.1 `basic.vert` / `basic.frag` — pipeline padrão

Vertex:
```glsl
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec2 aUV;
uniform mat4 uModel, uView, uProj;
out vec2 vUV;
void main() {
    vUV = aUV;
    gl_Position = uProj * uView * uModel * vec4(aPos, 1.0);
}
```

Fragment:
```glsl
in vec2 vUV;
out vec4 FragColor;
uniform sampler2D uDiffuse;
uniform float uUVTile;       // multiplica os UVs (1.0 padrão)
void main() {
    vec2 uv = vUV * uUVTile;
    FragColor = texture(uDiffuse, uv);
}
```

Pipeline unlit puro: a cor de saída é literalmente a amostragem da textura difusa naquele UV. **Sem iluminação, sem normais, sem lighting calculations**.

### 8.2 `skydome.vert` / `skydome.frag` — skybox panorâmico

Vertex:
```glsl
layout(location = 0) in vec3 aPos;
uniform mat4 uView, uProj;
out vec3 vDir;
void main() {
    mat4 view = uView;
    view[0][3] = view[1][3] = view[2][3] = 0.0;   // remove translação
    vDir = aPos;
    vec4 pos = uProj * view * vec4(aPos, 1.0);
    gl_Position = pos.xyww;                        // força z = w (plano distante)
}
```

Dois truques:
1. **Zerar a coluna de translação da matriz de visão**: faz com que o domo se mova junto com a câmera. Você nunca chega na "borda" do céu.
2. **`gl_Position = pos.xyww`**: sobrescreve Z com W, então após a divisão homogênea Z=1 (plano distante exatamente). Combinado com `GL_LEQUAL`, isso garante que o skybox apareça atrás de tudo.

Fragment:
```glsl
in vec3 vDir;
uniform sampler2D uPanorama;
const float PI = 3.14159265359;
void main() {
    vec3 d = normalize(vDir);
    float u = atan(d.z, d.x) / (2.0 * PI) + 0.5;       // longitude
    float v = 0.5 - asin(clamp(d.y, -1.0, 1.0)) / PI;  // latitude
    FragColor = texture(uPanorama, vec2(u, v));
}
```

Isso é o **mapeamento equirretangular padrão**: a direção do vértice (normalizada) é convertida em (longitude, latitude) e usada como UV pra amostrar uma imagem panorâmica `skyrender.png`. É o jeito mais simples de fazer skybox sem cubemap.

---

## 9. Pipeline de assets (`tools/build_assets.py`)

Este script é o "compilador de assets" do projeto. Ele lê os downloads brutos em `objetos/` e `build/staging/` e produz uma cópia limpa em `assets/modelos/` que o runtime consegue usar diretamente.

### 9.1 Por que precisamos disso?

Os modelos baixados de bancos como Sketchfab/CGTrader vêm em formatos e estados muito variados:
- alguns já em `.obj` com textura difusa pronta (caso fácil);
- alguns em `.obj` mas com `.mtl` multi-material apontando pra texturas que **não foram incluídas no download** (preciso sintetizar substitutas);
- alguns só em `.fbx`/`.blend` (formatos binários que o nosso loader simples de `.obj` não entende);
- alguns com texturas embutidas dentro do `.fbx` (preciso extrair sniffando os bytes);
- alguns sem nenhuma textura — só material com cor `Kd` plana (preciso gerar um JPEG sólido pra usar como textura).

`build_assets.py` resolve cada um desses casos com uma estratégia diferente. Ao final, todo modelo em `assets/modelos/<nome>/` segue o mesmo formato:
```
<nome>/
├── <nome>.obj         (geometria triangulada, com mtllib)
├── <nome>.mtl         (gerado pelo build, com map_Kd para cada material)
└── <nome>_*.{png,jpg} (1+ texturas difusas)
```

### 9.2 Estratégias implementadas

| Estratégia | Função no build_assets | Quem usa |
|---|---|---|
| **`.obj` + textura única** | `copy_obj_with_texture` | submarino, coral, pedra, alga |
| **`.obj` + `.mtl` multi-material com só `Kd`** | `copy_obj_with_kd_textures` | cadeira, peixe-palhaço, orca, beluga |
| **`.obj` + `.mtl` misto (`Kd` + `map_Kd`)** | `copy_obj_mixed_materials` | mesa sci-fi (HUDs reais + materiais sólidos) |
| **`.obj` multi-material + texturas separadas por material** | `copy_obj_multi_material` | estação de monitoramento (table + hologram_glass) |
| **`.fbx` com 13 materiais sem mapa de imagem** | `assimp_to_obj(..., per_material_color_textures=True)` | joystick_2 |

### 9.3 Detalhamento das estratégias

**`copy_obj_with_texture`**:
- Copia o `.obj` linha por linha, **dropando** os `mtllib`/`usemtl` originais e injetando os nossos no topo.
- Gera um `.mtl` mínimo (1 material) apontando pra textura escolhida.
- Copia a textura para a pasta de saída com nome canônico.

**`copy_obj_with_kd_textures`**:
- Lê o `.mtl` original via `parse_mtl_colors` para extrair Kd/Ke/Ks/Ka de cada material.
- Para cada material, gera uma textura **JPEG 4×4 sólida** com a cor `Kd` (clampada para >=0.06 para evitar materiais pretos invisíveis no pipeline unlit).
- Para materiais com **emissivo significativo** (`Ke` > 0.05), faz blend `0.85*Ke + 0.15*Kd` pra simular o glow da tela holográfica/painel.
- Suporta `skip_materials` para descartar geometria indesejada (usado no peixe-palhaço pra remover o plano de fundo de 30×30 m do template do Blender — `Material.005`).
- Copia o `.obj` mantendo os `usemtl` e ajustando o `mtllib`.

**`copy_obj_mixed_materials`** (mesa sci-fi):
- Mesma lógica do `_with_kd_textures`, mas se o material original tem `map_Kd` apontando pra um arquivo de imagem, **resolvemos esse arquivo** (procurando em `texture_search_dirs`) e copiamos a textura real em vez de gerar uma sólida.
- Para a mesa especificamente, as imagens (`futuristic-hud-15-.jpg` e `Hud 2.png`) **não estão no `.obj.zip`**, mas estão **embutidas no `.fbx.zip` companion**. O build extrai o FBX e **scaneia os bytes** procurando assinaturas PNG (`\x89PNG`) e JPEG (`\xFF\xD8\xFF`), copiando os blocos para `extracted_textures/`.

**`copy_obj_multi_material`** (estação):
- Para cada material original, recebemos uma tupla `(arquivo_textura_real, nome_destino)`.
- Copia o `.obj` mantendo os `usemtl`, escreve um `.mtl` com 1 bloco por material e copia as texturas.

**`assimp_to_obj` com `per_material_color_textures=True`** (joystick_2):
- Usa `assimp_py` para abrir o `.fbx` (nosso loader de `.obj` não entenderia).
- Mescla todas as malhas internas, triangula, gera um `.obj` único.
- Para cada material que o Assimp expôs, lê o `COLOR_DIFFUSE` (cor RGB do material) e gera uma textura sólida — assim o joystick mantém suas 13 cores distintas (verde, dourado, vários tons de cinza, branco).
- Aplica fallback de **mapeamento UV planar XZ** se o modelo vier sem UVs.

### 9.4 Outros utilitários no `build_assets.py`
- `make_brushed_metal_texture(path)` — sintetiza com numpy uma textura de chapa metálica escovada (usada como fallback para o piso interno se a textura externa não existir).
- `parse_mtl_colors`, `parse_mtl_full` — parsers de `.mtl` que respeitam nomes de material com espaços (`'Main mat A'`, `'Black  Reflection'`).
- `make_solid_color_texture(path, rgb)` — escreve uma JPEG 4×4 com a cor sólida indicada (usado pelas funções `_with_kd_textures` e `mixed_materials`).

### 9.5 Ordem de execução

`main()` no final do build executa, em ordem:
1. Cria a textura de chapa metálica compartilhada (`metal_brushed.jpg`).
2. Submarino (`copy_obj_with_texture`).
3. Joystick_2 (`assimp_to_obj` per-material).
4. Cadeira (`copy_obj_with_kd_textures`).
5. Coral, pedra (`copy_obj_with_texture`).
6. Mesa sci-fi (`copy_obj_mixed_materials` com extração das HUDs do FBX).
7. Estação (`copy_obj_multi_material`).
8. Alga (`copy_obj_with_texture`).
9. Peixe-palhaço, orca, beluga (`copy_obj_with_kd_textures`).

Cada bloco verifica `if src.exists()` e imprime warning se a fonte estiver faltando, mas continua com os próximos modelos. Isso facilita reprocessar só uma fonte alterada.

---

## 10. Decisões de design & truques importantes

### 10.1 Piso interno seguindo o casco (`make_hull_following_floor`)

**Problema**: o casco do submarino não é uma caixa — é uma forma orgânica que afina nas pontas (proa, popa). Um retângulo plano como piso ou:
- fica curto demais (sobra casco vazio nas pontas), ou
- fica longo demais e atravessa a casca curva, deixando bordas visíveis "saindo" do submarino.

**Solução**: amostrar o próprio `.obj` do casco para construir um piso de contorno orgânico. Algoritmo:

1. **Sample max |X| por fatia Z**: para cada vértice do `submarino.obj`, se `|y_local - target_y_local| < 0.15` (vértice está perto da altura alvo), pegamos `|x| * sub_scale` e atualizamos o máximo no bin de Z arredondado.
2. **Subtrair a margem**: `meia_largura_segura = max_|X| - margin`. Margem de 0.5 m garante folga em relação à parede.
3. **Filtrar fatias estreitas**: descartamos fatias com `meia_largura_segura < 1.5 m` (proa/popa onde a interpolação linear entre fatias adjacentes ainda atravessaria a casca curva).
4. **Ligar fatias com quads**: para cada par de fatias adjacentes em Z, criamos 2 vértices por fatia (borda esquerda e direita) e 2 triângulos formando um quad. Winding escolhido para que a normal aponte para +Y (cima).
5. **UVs**: V cresce com Z, U vai de 0 ao dobro da meia-largura × densidade (UVs por **metro real** de piso, não por largura — assim a textura tile-a sem deformação proporcional).

Resultado: corredor metálico que cobre ~42 m de comprimento, afinando suavemente nas pontas, sem buracos nem sobreposição com o casco.

### 10.2 Per-material color textures (joystick, cadeira, peixe-palhaço, orca, beluga)

**Problema**: vários modelos baixados não têm textura de imagem — só cores `Kd` definidas no `.mtl`. No pipeline antigo (fixed-function), o OpenGL respeitaria essas cores como material color. No core profile 3.3, **não existe mais conceito de material color** — só sampler.

**Solução**: para cada material `Kd`, gerar uma textura JPEG 4×4 sólida com aquela cor. O shader continua amostrando `texture(uDiffuse, uv)` normalmente; o resultado é o pixel sólido.

Variantes:
- Materiais com `Ke` (emissivo) significativo → blend `0.85*Ke + 0.15*Kd` para simular o brilho de telas/painéis (cadeira screen, etc.).
- `black_floor=0.06`: clamp pra evitar materiais com `Kd=(0,0,0)` ficarem invisíveis no pipeline unlit (sem light source pra revelar).
- `skip_materials`: alguns modelos vêm com geometria de "template" do Blender (planos de fundo de 30×30 m) — listamos pra dropar.

Resultado: o joystick mantém 13 cores distintas (verde + dourado + vários tons de cinza), a cadeira tem screen azul brilhante, e os animais marinhos têm cores realistas.

### 10.3 Decoração procedural do leito

Em vez de espalhar corais/pedras/algas manualmente (uma por uma na cena, tedioso e difícil de reproduzir), usamos uma **grade 2D** com RNG semeada:

```
área = 400m × 400m, dividida em células 10×10
  → 40×40 = 1600 células
densidade controlada por cell_step = 3
  → ~178 células ativas (1/9)
para cada célula ativa:
  sorteia 0-1 coral, 0-1 pedra, 0-1 alga
  com escala/rotação/posição (jitter 35%) aleatórias
```

Vantagens:
- **Reprodutível**: mesmo seed → mesma cena. Útil pra screenshots e pra debug.
- **Controlável**: ajustar `cell_step` muda a densidade global; ajustar os `*_count_range` ajusta densidade por célula.
- **Performance OK**: ~270 instâncias é mole pra GPU moderna.
- **Visualmente "natural"**: o jitter dentro da célula evita o look de grade. A regra de distância mínima entre coral e pedra evita pares encavalados.

### 10.4 Skybox dome anchored to camera

Um skybox típico é uma esfera enorme. Se a câmera puder se mover, ela eventualmente se aproxima da casca da esfera e o céu "encolhe" visualmente (paralaxe errada). Para evitar isso, o `skydome.vert` **zera a coluna de translação da matriz de visão antes de transformar os vértices**:

```glsl
view[0][3] = view[1][3] = view[2][3] = 0.0;
```

Efeito: o domo se move junto com a câmera. Equivalente a manter o domo centrado no olho do jogador o tempo todo. Combinado com `gl_Position = pos.xyww` (z forçado a w → z_ndc = 1, plano distante), o céu nunca interfere no z-buffer.

### 10.5 Rate-limited input

Usuários quase sempre apertam-e-seguram teclas em vez de tap-discreto. Sem rate-limit:
- segurar `]` por 0.5 s a 60 FPS = 30 incrementos de ×1.10 = ×17.4 → orca atinge o clamp instantaneamente;
- segurar `R` = beluga gira como hélice e impossível parar num ângulo legal.

A solução em `main._process_held_keys`:
```python
if key_pressed and (now - last_press) > 0.12:
    apply_action()
    last_press = now
```

0.12 s = 8.3 disparos por segundo. Suave o bastante pra parecer responsivo, lento o bastante pra não saturar.

### 10.6 Separação `_on_key` vs `_process_held_keys`

GLFW tem dois jeitos de ler teclado:
1. **Callback de eventos discretos** (`set_key_callback`): dispara em `PRESS` e `RELEASE`. Bom pra toggles únicos (Esc, P).
2. **Polling**: `glfw.get_key(window, KEY)` retorna o estado atual. Bom pra movimento contínuo (WASD).

Usamos os dois:
- `_on_key`: só Esc e P (wireframe).
- `_process_held_keys`: WASD, Espaço/Shift, e as teclas interativas (`[`, `]`, `R`, `Q`).

Misturar é importante: tentar fazer movimento WASD via callback dispara só em PRESS (uma única vez por toque), e fazer toggle via polling causaria múltiplos toggles enquanto a tecla é segurada.

### 10.7 Escolhas pragmáticas

- **`assimp_py`** em vez do Blender desktop (`bpy`): instala via pip em Python 3.12, abre `.fbx`/`.blend`/`.dae`/etc. sem precisar de Blender no sistema. Bem mais leve.
- **Sem face culling** (`glDisable(GL_CULL_FACE)`): vários `.obj` importados têm winding inconsistente entre as faces. Habilitar culling abriria buracos. Como a cena não é gigantesca, deixar ambos os lados desenharem é mais simples que tentar consertar o winding modelo a modelo.
- **Sem normais no shader**: o `.obj` traz `vn`, mas o pipeline unlit não usa. Atributo `aNormal` foi propositalmente omitido do VAO pra economizar memória GPU.
- **Texturas magenta como fallback**: qualquer `.mtl` apontando pra arquivo inexistente vira magenta `#FF00C8` na cena. Visualmente óbvio que algo está errado, mas o programa não crasha.

---

## 11. Scripts auxiliares (`tools/`)

### 11.1 `smoke_test.py` (~70 linhas)

Sobe uma janela GLFW **oculta** (`glfw.window_hint(VISIBLE, False)`), constrói a `Scene()` inteira, renderiza 1 frame e sai. Tempo de execução: ~3 segundos.

Pra que serve:
- Validar que **shaders compilam** (qualquer erro de GLSL aborta com mensagem do driver).
- Validar que **todos os `.obj` e texturas carregam** sem warnings.
- Validar que **VAOs/VBOs/EBOs sobem** ao GPU sem erro.
- **Não valida** input nem renderização correta visualmente — pra isso, abra o app e olhe.

Use sempre que mudar o `build_assets.py` ou alguma coisa em `scene.py`. Roda em CI também (sem precisar de monitor real).

### 11.2 `render_exterior_decor.py` (~95 linhas)

Igual ao smoke test, mas em vez de 1 frame só, gera **6 PNGs** em `build/`:
- `exterior_iso_ne.png` — vista isométrica nordeste
- `exterior_iso_sw.png` — vista isométrica sudoeste
- `exterior_low_east.png` — vista baixa do leste
- `exterior_low_west.png` — vista baixa do oeste
- `exterior_topdown.png` — vista de cima de toda a cena
- `exterior_close_side.png` — close-up de uma área lateral do submarino

Útil pra: ver o resultado da decoração procedural sem precisar abrir o app, comparar regressões visuais entre commits, validar que assets foram regerados corretamente.

---

## 12. Como adicionar / editar coisas (guia rápido)

### 12.1 Trocar a posição/escala de um modelo já existente
Edite `src/scene.py` no bloco do modelo (procure pelo comentário `# ---- <modelo> ----`). Os campos a mexer são `translation`, `rotation_y` e `scale_xyz` no `Object3D` correspondente. Não precisa rebuildar assets — é só rodar `python src/main.py`.

### 12.2 Adicionar um novo modelo da pasta `objetos/`
1. Coloque os arquivos brutos em `../objetos/<nome>/`.
2. Adicione um bloco no `tools/build_assets.py` chamando a função apropriada (ver §9.2 pra qual usar).
3. Rode `python tools/build_assets.py` — deve aparecer `[<estratégia>] <nome>: ...` no log.
4. Em `src/scene.py`, no dicionário `models = {...}`, adicione `"<nome>": load("<nome>")`.
5. Crie um `Object3D(model=models["<nome>"], translation=..., scale_xyz=..., rotation_y=...)` e dê `self.objects.append(...)`.
6. Rode `python tools/smoke_test.py` para garantir que não quebrou.

### 12.3 Adicionar uma nova interação de teclado
1. Em `src/scene.py`, adicione um campo no `SceneState` (se for estado acumulado) e crie um método `def do_thing(self, ...)`.
2. Em `src/main.py`:
   - Se for **toggle discreto**: em `_on_key`, adicione um `elif key == glfw.KEY_X: self.scene.do_thing()`.
   - Se for **contínuo enquanto segura**: em `__init__`, adicione `self._last_x_press = 0.0`. Em `_process_held_keys`, adicione o bloco `if glfw.get_key(...) == PRESS and now - self._last_x_press > 0.12: self.scene.do_thing(); self._last_x_press = now`.
3. Atualize o `print` de controles em `main()` e a tabela na seção 6 deste README.

### 12.4 Mudar a densidade da decoração
Em `src/scene.py`, no construtor da `Scene`, ajuste os parâmetros do `_populate_decor_grid`:
- `cell_step=3` → `2` para o dobro de densidade, `5` para metade.
- `coral_count_range=(0, 1)` → `(1, 2)` para forçar pelo menos 1 coral por célula.
- `seed=42` → outro número para um layout diferente (mantém reprodutibilidade).

### 12.5 Mudar shader (ex.: adicionar fog ou tint)
1. Edite `shaders/basic.frag` (adicione um `uniform vec3 uFogColor;` e mude o `FragColor`).
2. Em `src/scene.py` no `draw`, depois de `self.basic.use()`, adicione `self.basic.set_vec3("uFogColor", 0.1, 0.2, 0.3)`.
3. Rode `python tools/smoke_test.py`. Se a compilação do shader falhar, o erro do driver é mostrado em formato GLSL e geralmente aponta a linha exata.

---

## 13. Troubleshooting

| Sintoma | Causa provável | Como resolver |
|---|---|---|
| **Tela toda magenta para um modelo** | Textura difusa não encontrada no `.mtl` | Procure o warning `[texture] WARN missing ...` no terminal. Verifique se o build_assets passou sem erros. |
| **Modelo aparece preto/sem textura** | `.mtl` sem `map_Kd` válido | Rode `python tools/build_assets.py` para regenerá-lo. Se for um modelo novo, verifique se você usou a função correta (ver §9.2). |
| **Tela toda preta** | Câmera muito perto do plano `near` ou dentro do skybox | Mexa a câmera (WASD). Se persistir, verifique `near=0.1` e `far=600` no `perspective(...)` em `main.py`. |
| **`glfw.create_window` falha** | Falta hint de OpenGL Forward Compat (macOS) ou driver fora do dia | Verifique que `OPENGL_FORWARD_COMPAT=True` está no `App.__init__`. Atualize o driver gráfico. |
| **Performance baixa** | Muita decoração / cardume | Aumente `cell_step` no `_populate_decor_grid` e `_populate_fish_grid` em `scene.py`. |
| **`assimp_py` falha em instalar** | Python 3.13+ | Use Python 3.12 (não tem wheel pra 3.13 no momento). |
| **`[smoke] OK` mas o `main.py` quebra** | Algo no input ou na câmera | Rode com `python -X dev src/main.py` pra ver tracebacks completos. |
| **Wireframe (P) escapa do skybox** | Comportamento esperado | É exigência do edital mostrar a malha de tudo. O skydome também aparece como triângulos. |

---

## 14. Checklist do edital

| Requisito | Onde está atendido |
|---|---|
| OpenGL 3.3 core profile, sem fixed-function | `main.py` setando os hints; nenhum `glRotate/Translate/Scale/Begin/End/PushMatrix` em todo o repositório |
| ≥ 6 modelos `.obj` importados e texturizados | 11 modelos em `assets/modelos/` |
| Múltiplas texturas por modelo (multi-material) | `model.py` parseia `usemtl` e cria submalhas; visível em `joystick_2` (13 mat), `mesa` (8), `cadeira` (5), `peixe_palhaco` (5), `estacao` (2) |
| Câmera em primeira pessoa com WASD + mouse | `camera.py` + `main.py:_process_held_keys` |
| Pelo menos uma transformação interativa por teclado | Escala da orca (`[`/`]`) e rotação da beluga (`R`/`Q`) |
| Skybox / skydome | `make_sky_sphere` + `shaders/skydome.{vert,frag}` |
| Wireframe via `P` | `main.py:_on_key` chamando `glPolygonMode` |
| Sem iluminação | `basic.frag` é `FragColor = texture(...)` puro, sem light calc |
| Pipeline reproduzível | `tools/build_assets.py` regera tudo de `objetos/` + `build/staging/` em ~5 s |
| Documentação | Este README + comentários extensivos em todos os `.py` |

---

> Qualquer dúvida que esse README não cubra, abra os arquivos com os comentários em português — eles foram escritos no mesmo nível de detalhe que este README, mas com foco no "como" linha-a-linha em vez do "porquê" arquitetural. **`scene.py` em particular tem comentários linha por linha em cada bloco de posicionamento de modelo explicando os AABBs e por que cada offset de translação foi calculado daquele jeito.**
