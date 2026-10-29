"""Optional PyOpenGL renderer for solid faces.

The application UI is still drawn by pygame.  This renderer draws the costly
solid layer into an OpenGL framebuffer and composites the result back onto the
pygame canvas.  Keeping the boundary here makes PyOpenGL entirely optional.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import pygame

from ..document import Document
from ..faces import Face, iter_solid_faces
from .camera import OrbitCamera
from .scene import ScenePalette


class OpenGLRenderer:
    """Render visible solid faces with PyOpenGL when a context is available."""

    def __init__(self, palette: Optional[ScenePalette] = None) -> None:
        self.palette = palette or ScenePalette()
        self.available = False
        self._size = (0, 0)
        self._framebuffer = 0
        self._texture = 0
        self._depth_buffer = 0
        try:
            from OpenGL import GL

            self.gl = GL
            self.available = bool(GL.glGetString(GL.GL_VERSION))
        except Exception:
            self.gl = None

    def draw(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
        highlight_features: Sequence[int] = (),
    ) -> bool:
        """Composite the OpenGL solid layer, returning whether it was drawn."""
        if not self.available or rect.width < 1 or rect.height < 1:
            return False
        try:
            if not all(self._supports_face(face) for _, _, face in iter_solid_faces(document)):
                return False
            self._ensure_target(rect.size)
            self._rect = rect
            pixels = self._render_pixels(document, camera, highlight_features)
            layer = pygame.image.fromstring(pixels, rect.size, "RGBA", True)
            surface.blit(layer, rect.topleft)
            return True
        except Exception:
            # A driver reset must not make the CAD application unusable.
            self.available = False
            return False

    def _ensure_target(self, size: Tuple[int, int]) -> None:
        if size == self._size:
            return
        gl = self.gl
        if self._framebuffer:
            gl.glDeleteFramebuffers(1, [self._framebuffer])
            gl.glDeleteTextures([self._texture])
            gl.glDeleteRenderbuffers(1, [self._depth_buffer])
        width, height = size
        self._framebuffer = gl.glGenFramebuffers(1)
        self._texture = gl.glGenTextures(1)
        self._depth_buffer = gl.glGenRenderbuffers(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, width, height, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None,
        )
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._depth_buffer)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, width, height)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._framebuffer)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D,
            self._texture, 0,
        )
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT, gl.GL_RENDERBUFFER,
            self._depth_buffer,
        )
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("OpenGL framebuffer is incomplete")
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        self._size = size

    def _render_pixels(
        self,
        document: Document,
        camera: OrbitCamera,
        highlight_features: Sequence[int],
    ) -> bytes:
        gl = self.gl
        width, height = self._size
        faces = list(iter_solid_faces(document))
        depths = [camera.depth(face.vertices) for _, _, face in faces if face.vertices]
        far = min(depths, default=0.0)
        near = max(depths, default=1.0)
        span = max(near - far, 1e-6)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._framebuffer)
        gl.glViewport(0, 0, width, height)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, width, 0, height, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        highlighted = set(highlight_features)
        view = camera.view_direction()
        for feature_id, _, face in faces:
            if len(face.vertices) < 3 or face.holes:
                continue
            if sum(face.normal[index] * view[index] for index in range(3)) <= 0:
                continue
            color = self._color(face, feature_id in highlighted)
            depth = camera.depth(face.vertices)
            z = 1.0 - 2.0 * (depth - far) / span
            self._draw_face(face, camera, color, z)
        pixels = gl.glReadPixels(0, 0, width, height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        return pixels

    def _draw_face(
        self, face: Face, camera: OrbitCamera, color: Tuple[int, int, int], z: float
    ) -> None:
        """Draw a convex mesh panel; complex caps stay on the pygame path."""
        gl = self.gl
        gl.glColor4ub(*color, 255)
        gl.glBegin(gl.GL_TRIANGLE_FAN)
        for vertex in face.vertices:
            x, y = camera.project(vertex, self._rect.center)
            gl.glVertex3f(x - self._rect.x, self._size[1] - (y - self._rect.y), z)
        gl.glEnd()

    @staticmethod
    def _supports_face(face: Face) -> bool:
        """Return whether the fixed-function path can fill this face safely."""
        if face.holes or len(face.vertices) < 3:
            return not face.holes
        signs = []
        vertices = face.vertices
        for index, vertex in enumerate(vertices):
            previous = vertices[index - 1]
            following = vertices[(index + 1) % len(vertices)]
            first = tuple(vertex[axis] - previous[axis] for axis in range(3))
            second = tuple(following[axis] - vertex[axis] for axis in range(3))
            cross = (
                first[1] * second[2] - first[2] * second[1],
                first[2] * second[0] - first[0] * second[2],
                first[0] * second[1] - first[1] * second[0],
            )
            signed = sum(cross[axis] * face.normal[axis] for axis in range(3))
            if abs(signed) > 1e-8:
                signs.append(signed > 0.0)
        return not signs or all(sign == signs[0] for sign in signs)

    def _color(self, face: Face, highlighted: bool) -> Tuple[int, int, int]:
        if not highlighted:
            return face.color
        base = self.palette.preview_selected
        return tuple(round(channel * 0.3 + accent * 0.7) for channel, accent in zip(face.color, base))
