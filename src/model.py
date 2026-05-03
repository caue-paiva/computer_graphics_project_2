"""Wavefront .obj loader + GPU upload, with multi-material support.

Parses position+UV (`v`, `vt`, `f`) and reads `mtllib`/`usemtl`. Each
`usemtl` switch starts a new sub-mesh that draws with its own diffuse
texture. Faces with more than 3 vertices are fan-triangulated.

Each unique (v_idx, vt_idx) pair becomes one GPU vertex (deduplicated
via a dict). Normals are read from `vn` lines but ignored at draw time
because this assignment forbids lighting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import ctypes
import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
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
    glDrawElements,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenVertexArrays,
    glVertexAttribPointer,
)

from texture import load_texture_2d


@dataclass
class _Material:
    name: str
    diffuse_map: str | None = None  # path relative to the .mtl directory


def _parse_mtl(mtl_path: Path) -> dict[str, _Material]:
    materials: dict[str, _Material] = {}
    if not mtl_path.exists():
        return materials
    current: _Material | None = None
    for raw in mtl_path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        head = parts[0].lower()
        if head == "newmtl":
            current = _Material(name=parts[1].strip() if len(parts) > 1 else "")
            materials[current.name] = current
        elif head == "map_kd" and current is not None and len(parts) > 1:
            current.diffuse_map = parts[1].strip()
    return materials


def ctypes_offset(byte_offset: int):
    """Return a void-pointer offset suitable for glVertexAttribPointer."""
    return ctypes.c_void_p(byte_offset)


@dataclass
class SubMesh:
    """Slice of a model that shares one material/texture."""
    diffuse_tex: int
    index_offset: int  # offset (in indices) into the parent EBO
    index_count: int
    material_name: str = ""


@dataclass
class Model:
    """A whole imported model.

    A single VAO holds positions+UVs interleaved; the EBO is split into
    one or more `SubMesh` slices. We bind once and issue a glDrawElements
    per submesh with its own texture.
    """
    vao: int
    submeshes: list[SubMesh] = field(default_factory=list)
    name: str = ""

    @classmethod
    def load_obj(cls, obj_path: str | Path, fallback_texture: str | Path | None = None) -> "Model":
        obj_p = Path(obj_path)
        verts: list[tuple[float, float, float]] = []
        uvs: list[tuple[float, float]] = []
        materials: dict[str, _Material] = {}

        # `material_runs` is a list of (material_name, [face, face, ...]) where
        # each face is a list of (v_idx, vt_idx) pairs. We start with an
        # implicit "default" run for files that have no usemtl directive.
        material_runs: list[tuple[str | None, list[list[tuple[int, int]]]]] = [(None, [])]

        for raw in obj_p.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            head, *rest = line.split()
            if head == "v" and len(rest) >= 3:
                verts.append((float(rest[0]), float(rest[1]), float(rest[2])))
            elif head == "vt" and len(rest) >= 2:
                uvs.append((float(rest[0]), float(rest[1])))
            elif head == "mtllib" and rest:
                # File name may itself contain spaces.
                mtl_ref = " ".join(rest)
                materials.update(_parse_mtl(obj_p.parent / mtl_ref))
            elif head == "usemtl" and rest:
                # Material names can contain spaces (e.g. 'Main mat A'),
                # so rejoin every token after `usemtl`.
                mat_name = " ".join(rest)
                if material_runs[-1][0] is None and not material_runs[-1][1]:
                    # First usemtl: replace the default empty bucket.
                    material_runs[-1] = (mat_name, [])
                else:
                    material_runs.append((mat_name, []))
            elif head == "f" and len(rest) >= 3:
                tokens: list[tuple[int, int]] = []
                for tok in rest:
                    parts = tok.split("/")
                    vi = int(parts[0])
                    ti = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                    if vi < 0:
                        vi = len(verts) + vi + 1
                    if ti < 0:
                        ti = len(uvs) + ti + 1
                    tokens.append((vi, ti))
                # Fan-triangulate n-gons.
                for i in range(1, len(tokens) - 1):
                    material_runs[-1][1].append([tokens[0], tokens[i], tokens[i + 1]])

        # Deduplicate (v_idx, vt_idx) pairs into GPU vertices.
        gpu_verts: list[float] = []
        index_map: dict[tuple[int, int], int] = {}
        all_indices: list[int] = []
        submesh_specs: list[tuple[str | None, int, int]] = []  # (mat, offset, count)

        for mat_name, faces in material_runs:
            if not faces:
                continue
            offset = len(all_indices)
            for tri in faces:
                for vi, ti in tri:
                    key = (vi, ti)
                    if key not in index_map:
                        px, py, pz = verts[vi - 1]
                        if ti and ti - 1 < len(uvs):
                            u, v = uvs[ti - 1]
                        else:
                            u, v = 0.0, 0.0
                        gpu_verts.extend([px, py, pz, u, v])
                        index_map[key] = len(index_map)
                    all_indices.append(index_map[key])
            submesh_specs.append((mat_name, offset, len(all_indices) - offset))

        if not all_indices:
            raise RuntimeError(f"{obj_p}: no faces parsed")

        # Upload to a single VAO/VBO/EBO.
        vao = int(glGenVertexArrays(1))
        vbo = int(glGenBuffers(1))
        ebo = int(glGenBuffers(1))
        glBindVertexArray(vao)

        vbo_data = np.asarray(gpu_verts, dtype=np.float32)
        ebo_data = np.asarray(all_indices, dtype=np.uint32)

        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, vbo_data.nbytes, vbo_data, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, ebo_data.nbytes, ebo_data, GL_STATIC_DRAW)

        stride = 5 * 4  # x, y, z, u, v
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, None)
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes_offset(3 * 4))
        glBindVertexArray(0)

        # Resolve a texture per submesh.
        cached_textures: dict[str, int] = {}

        def resolve_texture(mat_name: str | None) -> int:
            mat = materials.get(mat_name) if mat_name else None
            tex_path: Path | None = None
            if mat and mat.diffuse_map:
                tex_path = obj_p.parent / mat.diffuse_map
            elif fallback_texture:
                tex_path = Path(fallback_texture)
            key = str(tex_path) if tex_path else "<missing>"
            if key in cached_textures:
                return cached_textures[key]
            tex_id = load_texture_2d(tex_path) if tex_path else load_texture_2d("")
            cached_textures[key] = tex_id
            return tex_id

        submeshes = [
            SubMesh(
                diffuse_tex=resolve_texture(mat),
                index_offset=offset,
                index_count=count,
                material_name=mat or "",
            )
            for mat, offset, count in submesh_specs
        ]

        print(
            f"[model] {obj_p.name}: gpu_verts={len(gpu_verts) // 5} "
            f"indices={len(all_indices)} submeshes={len(submeshes)} "
            f"materials={[s.material_name for s in submeshes]}"
        )
        return cls(vao=vao, submeshes=submeshes, name=obj_p.stem)


def draw_model(model: Model) -> None:
    """Bind the VAO once and draw each submesh with its own texture."""
    glBindVertexArray(model.vao)
    glActiveTexture(GL_TEXTURE0)
    for sub in model.submeshes:
        glBindTexture(GL_TEXTURE_2D, sub.diffuse_tex)
        # Index offset is in *bytes* for glDrawElements.
        glDrawElements(
            GL_TRIANGLES,
            sub.index_count,
            GL_UNSIGNED_INT,
            ctypes_offset(sub.index_offset * 4),
        )
    glBindVertexArray(0)
