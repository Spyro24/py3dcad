"""Window system for PY3DCAD.

The window can run on a native OpenGL context so the viewport can use
PyOpenGL for solid rendering.  In that mode pygame draws the whole UI into an
offscreen canvas and the canvas is presented as a fullscreen texture each
frame.  If the context cannot be created the window falls back to a plain
pygame surface, which keeps the application usable everywhere.
"""

import os
from typing import Optional, Tuple

import pygame

BACKGROUND = (20, 20, 25)


def _surface_to_bytes(surface: pygame.Surface) -> bytes:
    """Read a surface as flipped RGBA bytes, across pygame versions."""
    to_bytes = getattr(pygame.image, "tobytes", None)
    if to_bytes is not None:
        return to_bytes(surface, "RGBA", True)
    return pygame.image.tostring(surface, "RGBA", True)


class Window:
    """Main application window using pygame-ce."""

    def __init__(
        self,
        title: str = "PY3DCAD",
        size: Tuple[int, int] = (1280, 720),
        flags: int = pygame.RESIZABLE,
        use_opengl: Optional[bool] = None,
    ) -> None:
        self.title = title
        self.size = size
        self.flags = flags
        self.use_opengl = (
            True if use_opengl is None else bool(use_opengl)
        )
        self.opengl = False
        self._surface: Optional[pygame.Surface] = None
        self._gl = None
        self._present_texture = 0
        self._present_size = (0, 0)
        self._clock = pygame.time.Clock()
        self._running = False

    @staticmethod
    def _opengl_requested() -> bool:
        """Allow the renderer to be disabled from the environment."""
        value = os.environ.get("PY3DCAD_RENDERER", "").strip().lower()
        return value != "pygame"

    def create(self) -> None:
        """Initialize pygame and create the window surface."""
        pygame.init()
        pygame.display.set_caption(self.title)
        use_opengl = self.use_opengl and self._opengl_requested()
        if not (use_opengl and self._create_opengl_window()):
            self.opengl = False
            self._surface = pygame.display.set_mode(self.size, self.flags)

    def _create_opengl_window(self) -> bool:
        """Create the OpenGL display, or report that it is unavailable."""
        try:
            from OpenGL import GL

            pygame.display.gl_set_attribute(
                pygame.GL_DOUBLEBUFFER, 1
            )
            pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
            pygame.display.set_mode(
                self.size, self.flags | pygame.OPENGL | pygame.DOUBLEBUF
            )
            if not GL.glGetString(GL.GL_VERSION):
                raise RuntimeError("no OpenGL context")
        except Exception:
            self._gl = None
            return False
        self._gl = GL
        self.opengl = True
        self._surface = pygame.Surface(self.size)
        return True

    @property
    def surface(self) -> pygame.Surface:
        """Get the window surface for drawing."""
        if self._surface is None:
            raise RuntimeError("Window not created. Call create() first.")
        return self._surface

    @property
    def running(self) -> bool:
        return self._running

    @running.setter
    def running(self, value: bool) -> None:
        self._running = value

    def get_size(self) -> Tuple[int, int]:
        """Get current window size."""
        if self._surface is None:
            return self.size
        return self._surface.get_size()

    def tick(self, fps: int = 60) -> float:
        """Limit frame rate and return delta time in seconds."""
        return self._clock.tick(fps) / 1000.0

    def flip(self) -> None:
        """Present the canvas and update the display."""
        if self.opengl:
            self._present_canvas()
        pygame.display.flip()

    def _present_canvas(self) -> None:
        """Draw the pygame canvas over the whole OpenGL window."""
        if self._surface is None or self._gl is None:
            return
        gl = self._gl
        get_size = getattr(pygame.display, "get_window_size", None)
        window_size = get_size() if get_size is not None else self.size
        if window_size[0] < 1 or window_size[1] < 1:
            return
        width, height = window_size
        gl.glViewport(0, 0, width, height)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_FOG)
        gl.glColor4f(1.0, 1.0, 1.0, 1.0)
        gl.glClearColor(*[channel / 255 for channel in BACKGROUND], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, 1, 0, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()

        if not self._present_texture:
            self._present_texture = gl.glGenTextures(1)
        canvas_size = self._surface.get_size()
        pixels = _surface_to_bytes(self._surface)
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._present_texture)
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR
        )
        if canvas_size != self._present_size:
            gl.glTexImage2D(
                gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, canvas_size[0],
                canvas_size[1], 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixels,
            )
            self._present_size = canvas_size
        else:
            gl.glTexSubImage2D(
                gl.GL_TEXTURE_2D, 0, 0, 0, canvas_size[0], canvas_size[1],
                gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixels,
            )
        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0, 0)
        gl.glVertex2f(0, 0)
        gl.glTexCoord2f(1, 0)
        gl.glVertex2f(1, 0)
        gl.glTexCoord2f(1, 1)
        gl.glVertex2f(1, 1)
        gl.glTexCoord2f(0, 1)
        gl.glVertex2f(0, 1)
        gl.glEnd()
        gl.glDisable(gl.GL_TEXTURE_2D)

    def handle_resize(self, event: pygame.event.Event) -> None:
        """Track the new window size managed by SDL2."""
        if event.type == pygame.VIDEORESIZE:
            self.size = (event.w, event.h)
            if self.opengl:
                self._surface = pygame.Surface(self.size)
                self._present_size = (0, 0)

    def close(self) -> None:
        """Clean up pygame resources."""
        pygame.quit()
        self._surface = None
        self._gl = None
        self._present_texture = 0
        self._present_size = (0, 0)
