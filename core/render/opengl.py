"""PyOpenGL solid renderer for the CAD viewport.

The pygame UI stays the authoritative canvas.  This renderer draws only the
solid layer into an offscreen OpenGL framebuffer with depth buffering, then
reads it back and composites it into the viewport rectangle.  Concave caps and
holes are tessellated; outlines are drawn with the same depth buffer so hidden
edges disappear.  A driver error simply disables the hardware path and the
software renderer takes over.
"""

from __future__ import annotations

import sys
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

from ..document import Document
from ..faces import Color, Face, iter_solid_faces
from .camera import OrbitCamera
from .edges import FaceEdgeCache, FaceEdgeKey, edge_key
from .scene import ScenePalette

Point3 = Tuple[float, float, float]
ScreenPoint = Tuple[float, float, float]


class OpenGLRenderer:
    """Render the visible solid faces with PyOpenGL when a context exists."""

    def __init__(
        self,
        palette: Optional[ScenePalette] = None,
        edge_cache: Optional[FaceEdgeCache] = None,
    ) -> None:
        self.palette = palette or ScenePalette()
        self.edge_cache = edge_cache or FaceEdgeCache()
        self.available = False
        self.ui_scale = 1.0
        self._rect = pygame.Rect(0, 0, 1, 1)
        self._size = (0, 0)
        self._framebuffer = 0
        self._texture = 0
        self._depth_buffer = 0
        try:
            from OpenGL import GL
            from OpenGL import GLU

            self.gl = GL
            self.glu = GLU
            self.available = bool(GL.glGetString(GL.GL_VERSION))
        except Exception:
            # No current context: the software renderer handles the solids.
            self.gl = None
            self.glu = None

    def set_scale(self, scale: float) -> None:
        self.ui_scale = scale

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
            rect = pygame.Rect(rect)
            self._ensure_target(rect.size)
            self._rect = rect
            pixels = self._render_pixels(
                document, camera, highlight_features
            )
            from_bytes = getattr(pygame.image, "frombytes", None)
            if from_bytes is not None:
                layer = from_bytes(pixels, rect.size, "RGBA", True)
            else:
                layer = pygame.image.fromstring(
                    pixels, rect.size, "RGBA", True
                )
            surface.blit(layer, rect.topleft)
            return True
        except Exception as error:
            # A driver reset must not make the CAD application unusable.
            print(f"PyOpenGL renderer disabled: {error}", file=sys.stderr)
            self.disable()
            return False

    def disable(self) -> None:
        """Stop using OpenGL and release its framebuffer resources."""
        self.available = False
        self._release()

    # ------------------------------------------------------------------
    # Framebuffer
    # ------------------------------------------------------------------

    def _ensure_target(self, size: Tuple[int, int]) -> None:
        if size == self._size:
            return
        gl = self.gl
        previous = gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING)
        self._release()
        width, height = size
        self._framebuffer = gl.glGenFramebuffers(1)
        self._texture = gl.glGenTextures(1)
        self._depth_buffer = gl.glGenRenderbuffers(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, width, height, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None,
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST
        )
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._depth_buffer)
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, width, height
        )
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._framebuffer)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D,
            self._texture, 0,
        )
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT, gl.GL_RENDERBUFFER,
            self._depth_buffer,
        )
        complete = gl.glCheckFramebufferStatus(
            gl.GL_FRAMEBUFFER
        ) == gl.GL_FRAMEBUFFER_COMPLETE
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous)
        if not complete:
            raise RuntimeError("OpenGL framebuffer is incomplete")
        self._size = size

    def _release(self) -> None:
        if not self.gl or not self._framebuffer:
            self._size = (0, 0)
            return
        gl = self.gl
        try:
            gl.glDeleteFramebuffers(1, [self._framebuffer])
            gl.glDeleteTextures([self._texture])
            gl.glDeleteRenderbuffers(1, [self._depth_buffer])
        except Exception:
            pass
        finally:
            self._framebuffer = 0
            self._texture = 0
            self._depth_buffer = 0
            self._size = (0, 0)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_pixels(
        self,
        document: Document,
        camera: OrbitCamera,
        highlight_features: Sequence[int],
    ) -> bytes:
        gl = self.gl
        width, height = self._size
        view = camera.view_direction()
        faces: List[Tuple[int, Face, bool]] = []
        edges: Dict[FaceEdgeKey, Tuple[Point3, Point3]] = {}
        smooth_sides: Dict[FaceEdgeKey, List[bool]] = {}
        drawn: set[FaceEdgeKey] = set()
        far = None
        near = None
        for feature_id, _, face in iter_solid_faces(document):
            if len(face.vertices) < 3:
                continue
            front = self._front_facing(face, view)
            faces.append((feature_id, face, front))
            for vertex in face.vertices:
                depth = self._depth(vertex, view)
                far = depth if far is None else min(far, depth)
                near = depth if near is None else max(near, depth)
            self._collect_face_edges(
                face, front, drawn, smooth_sides, edges
            )
        far = 0.0 if far is None else far
        near = 0.0 if near is None else near
        span = max(near - far, 1e-6)
        for key, sides in smooth_sides.items():
            if all(sides) and key in edges:
                drawn.add(key)
        highlighted = set(highlight_features)

        previous = gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._framebuffer)
        gl.glViewport(0, 0, width, height)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_BLEND)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, width, 0, height, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()

        gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glPolygonOffset(1.0, 1.0)
        for feature_id, face, front in faces:
            if not front:
                continue
            color = self._color(face, feature_id in highlighted)
            self._draw_face(face, color, camera, view, far, span)
        gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_LINE_SMOOTH)
        gl.glHint(gl.GL_LINE_SMOOTH_HINT, gl.GL_NICEST)
        gl.glLineWidth(float(max(1, int(round(self.ui_scale)))))
        gl.glColor4ub(*self.palette.edge, 255)
        gl.glBegin(gl.GL_LINES)
        for key in drawn:
            start, end = edges[key]
            gl.glVertex3f(*self._screen_point(
                start, camera, view, far, span
            ))
            gl.glVertex3f(*self._screen_point(
                end, camera, view, far, span
            ))
        gl.glEnd()
        gl.glDisable(gl.GL_LINE_SMOOTH)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_DEPTH_TEST)

        pixels = gl.glReadPixels(
            0, 0, width, height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE
        )
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous)
        return pixels

    @staticmethod
    def _front_facing(face: Face, view: Point3) -> bool:
        normal = face.normal
        return (
            normal[0] * view[0]
            + normal[1] * view[1]
            + normal[2] * view[2]
        ) > 0

    @staticmethod
    def _depth(point: Point3, view: Point3) -> float:
        return (
            point[0] * view[0]
            + point[1] * view[1]
            + point[2] * view[2]
        )

    def _collect_face_edges(
        self,
        face: Face,
        front: bool,
        drawn: set[FaceEdgeKey],
        smooth_sides: Dict[FaceEdgeKey, List[bool]],
        edges: Dict[FaceEdgeKey, Tuple[Point3, Point3]],
    ) -> None:
        """Classify one face's edges as outlines and smooth seams."""
        vertices = face.vertices
        count = len(vertices)
        entries = self.edge_cache.edges(face)
        outline_all = face.sharp_edges is None
        for index, entry in enumerate(entries):
            if entry is None:
                continue
            key, smooth = entry
            edges.setdefault(key, (
                vertices[index], vertices[(index + 1) % count]
            ))
            if outline_all or not smooth:
                drawn.add(key)
            if smooth:
                sides = smooth_sides.setdefault(key, [False, False])
                sides[0 if front else 1] = True
        for hole in face.holes:
            hole_count = len(hole)
            for index in range(hole_count):
                start = hole[index]
                end = hole[(index + 1) % hole_count]
                if start == end:
                    continue
                key = edge_key(start, end)
                edges.setdefault(key, (start, end))
                drawn.add(key)

    def _screen_point(
        self,
        point: Point3,
        camera: OrbitCamera,
        view: Point3,
        far: float,
        span: float,
    ) -> ScreenPoint:
        x, y = camera.project(point, self._rect.center)
        depth = self._depth(point, view)
        return (
            x - self._rect.x,
            self._size[1] - (y - self._rect.y),
            -1.0 + 2.0 * (depth - far) / span,
        )

    def _draw_face(
        self,
        face: Face,
        color: Color,
        camera: OrbitCamera,
        view: Point3,
        far: float,
        span: float,
    ) -> None:
        """Fill one face, tessellating concave contours and holes."""
        gl = self.gl
        outer = [
            self._screen_point(point, camera, view, far, span)
            for point in face.vertices
        ]
        holes = [
            [
                self._screen_point(point, camera, view, far, span)
                for point in hole
            ]
            for hole in face.holes
        ]
        gl.glColor4ub(*color, 255)
        if not holes and self._is_convex(outer):
            gl.glBegin(gl.GL_TRIANGLE_FAN)
            for point in outer:
                gl.glVertex3f(*point)
            gl.glEnd()
            return
        self._tessellate(outer, holes)

    def _tessellate(
        self, outer: Sequence[ScreenPoint], holes: Sequence[Sequence[ScreenPoint]]
    ) -> None:
        gl = self.gl
        glu = self.glu
        tessellator = glu.gluNewTess()

        def begin(mode: int) -> None:
            gl.glBegin(mode)

        def vertex(point: ScreenPoint) -> None:
            gl.glVertex3f(*point)

        def combine(
            coordinates: ScreenPoint, _data, _weights
        ) -> ScreenPoint:
            return tuple(coordinates)

        glu.gluTessCallback(tessellator, glu.GLU_TESS_BEGIN, begin)
        glu.gluTessCallback(tessellator, glu.GLU_TESS_VERTEX, vertex)
        glu.gluTessCallback(tessellator, glu.GLU_TESS_END, gl.glEnd)
        glu.gluTessCallback(tessellator, glu.GLU_TESS_COMBINE, combine)
        glu.gluTessProperty(
            tessellator, glu.GLU_TESS_WINDING_RULE, glu.GLU_TESS_WINDING_ODD
        )
        glu.gluTessBeginPolygon(tessellator, None)
        for contour in (outer, *holes):
            glu.gluTessBeginContour(tessellator)
            for point in contour:
                glu.gluTessVertex(tessellator, point, point)
            glu.gluTessEndContour(tessellator)
        glu.gluTessEndPolygon(tessellator)
        glu.gluDeleteTess(tessellator)

    @staticmethod
    def _is_convex(points: Sequence[ScreenPoint]) -> bool:
        """Return whether a projected polygon can be drawn as a fan."""
        count = len(points)
        if count < 3:
            return False
        sign = 0
        for index in range(count):
            ax, ay = points[index][0], points[index][1]
            bx, by = points[(index + 1) % count][0], points[(index + 1) % count][1]
            cx, cy = points[(index + 2) % count][0], points[(index + 2) % count][1]
            cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
            if abs(cross) < 1e-7:
                continue
            current = 1 if cross > 0 else -1
            if sign == 0:
                sign = current
            elif current != sign:
                return False
        return True

    def _color(self, face: Face, highlighted: bool) -> Color:
        if not highlighted:
            return face.color
        base = self.palette.preview_selected
        return tuple(
            round(channel * 0.3 + accent * 0.7)
            for channel, accent in zip(face.color, base)
        )
