"""Tiny shader helper.

Wraps `glCreateShader / glShaderSource / glCompileShader / glLinkProgram`
and exposes friendly setters for uniforms, all using the modern
programmable pipeline. No fixed-function calls anywhere.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from OpenGL.GL import (
    GL_COMPILE_STATUS,
    GL_FALSE,
    GL_FRAGMENT_SHADER,
    GL_LINK_STATUS,
    GL_TRUE,
    GL_VERTEX_SHADER,
    glAttachShader,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteShader,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glShaderSource,
    glUniform1f,
    glUniform1i,
    glUniform3f,
    glUniformMatrix4fv,
    glUseProgram,
)


class ShaderError(RuntimeError):
    pass


def _compile(stage: int, source: str, label: str) -> int:
    shader = glCreateShader(stage)
    glShaderSource(shader, source)
    glCompileShader(shader)
    status = glGetShaderiv(shader, GL_COMPILE_STATUS)
    if status == GL_FALSE:
        log = glGetShaderInfoLog(shader).decode(errors="ignore")
        glDeleteShader(shader)
        raise ShaderError(f"{label} failed to compile:\n{log}")
    return shader


class Program:
    """A linked vertex+fragment program with a uniform cache."""

    def __init__(self, vert_src: str, frag_src: str, label: str = "shader") -> None:
        vs = _compile(GL_VERTEX_SHADER, vert_src, f"{label} vert")
        fs = _compile(GL_FRAGMENT_SHADER, frag_src, f"{label} frag")

        self.id = glCreateProgram()
        glAttachShader(self.id, vs)
        glAttachShader(self.id, fs)
        glLinkProgram(self.id)
        if glGetProgramiv(self.id, GL_LINK_STATUS) == GL_FALSE:
            log = glGetProgramInfoLog(self.id).decode(errors="ignore")
            raise ShaderError(f"{label} link failed:\n{log}")
        glDeleteShader(vs)
        glDeleteShader(fs)
        self._uniform_cache: dict[str, int] = {}

    @classmethod
    def from_files(cls, vert_path: str | Path, frag_path: str | Path, label: str = "shader") -> "Program":
        vert_src = Path(vert_path).read_text()
        frag_src = Path(frag_path).read_text()
        return cls(vert_src, frag_src, label=label)

    def use(self) -> None:
        glUseProgram(self.id)

    def _loc(self, name: str) -> int:
        if name not in self._uniform_cache:
            self._uniform_cache[name] = glGetUniformLocation(self.id, name)
        return self._uniform_cache[name]

    def set_int(self, name: str, value: int) -> None:
        glUniform1i(self._loc(name), int(value))

    def set_float(self, name: str, value: float) -> None:
        glUniform1f(self._loc(name), float(value))

    def set_vec3(self, name: str, x: float, y: float, z: float) -> None:
        glUniform3f(self._loc(name), float(x), float(y), float(z))

    def set_mat4(self, name: str, mat: np.ndarray) -> None:
        loc = self._loc(name)
        if loc < 0:
            return
        arr = np.ascontiguousarray(mat, dtype=np.float32)
        glUniformMatrix4fv(loc, 1, GL_TRUE, arr)
