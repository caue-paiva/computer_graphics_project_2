"""Texture loading helpers (PIL -> OpenGL).

We always upload as RGBA and let OpenGL build mipmaps. A 1x1 magenta
fallback texture is generated on missing files to keep the renderer
running when an asset is mis-pathed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE,
    GL_LINEAR,
    GL_LINEAR_MIPMAP_LINEAR,
    GL_REPEAT,
    GL_RGBA,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_UNSIGNED_BYTE,
    glBindTexture,
    glGenTextures,
    glGenerateMipmap,
    glTexImage2D,
    glTexParameteri,
)
from PIL import Image


_FALLBACK_RGBA = bytes([255, 0, 200, 255])


def _gen_2d(rgba: bytes, width: int, height: int, wrap: int) -> int:
    tex_id = int(glGenTextures(1))
    glBindTexture(GL_TEXTURE_2D, tex_id)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba)
    glGenerateMipmap(GL_TEXTURE_2D)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrap)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrap)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glBindTexture(GL_TEXTURE_2D, 0)
    return tex_id


def load_texture_2d(path: str | Path, wrap_repeat: bool = True, flip_y: bool = True) -> int:
    """Load a 2D texture from disk; returns a GL texture id.

    By default we flip the image vertically because PIL decodes PNG/JPG
    with row 0 at the top while glTexImage2D expects row 0 at the
    bottom. Combined with the per-asset UV flipping done at conversion
    time, this gives a consistent OpenGL-style sampling.
    """
    p = Path(path)
    wrap = GL_REPEAT if wrap_repeat else GL_CLAMP_TO_EDGE

    if not p.exists():
        print(f"[texture] WARN missing {p} -> using magenta fallback")
        return _gen_2d(_FALLBACK_RGBA, 1, 1, wrap)

    try:
        img = Image.open(p).convert("RGBA")
        if flip_y:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        data = np.asarray(img, dtype=np.uint8).tobytes()
        return _gen_2d(data, img.width, img.height, wrap)
    except Exception as exc:
        print(f"[texture] ERROR {p}: {exc} -> using magenta fallback")
        return _gen_2d(_FALLBACK_RGBA, 1, 1, wrap)
