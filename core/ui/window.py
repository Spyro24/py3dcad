"""Window system for PY3DCAD."""

import os

import pygame
from typing import Optional, Tuple


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
            os.environ.get("PY3DCAD_RENDERER", "").lower() == "opengl"
            if use_opengl is None else use_opengl
        )
        self._surface: Optional[pygame.Surface] = None
        self._opengl = False
        self._gl = None
        self._present_texture = 0
        self._clock = pygame.time.Clock()
        self._running = False

    def create(self) -> None:
        """Initialize pygame and create the window surface."""
        pygame.init()
        pygame.display.set_caption(self.title)
        if self.use_opengl:
            self._create_opengl_window()
        if self._surface is None:
            self._surface = pygame.display.set_mode(self.size, self.flags)

    def _create_opengl_window(self) -> None:
        """Create the optional OpenGL display without risking the fallback."""
        try:
            from OpenGL import GL

            pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
            pygame.display.set_mode(
                self.size, self.flags | pygame.OPENGL | pygame.DOUBLEBUF
            )
            self._gl = GL
            self._opengl = bool(GL.glGetString(GL.GL_VERSION))
            if self._opengl:
                self._surface = pygame.Surface(self.size).convert_alpha()
        except Exception:
            self._opengl = False
            self._gl = None

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
        """Update the display."""
        if self._opengl:
            self._present_canvas()
        pygame.display.flip()

    def _present_canvas(self) -> None:
        """Upload the pygame UI canvas as the final OpenGL screen layer."""
        if self._surface is None or self._gl is None:
            return
        gl = self._gl
        width, height = self._surface.get_size()
        if not self._present_texture:
            self._present_texture = gl.glGenTextures(1)
        gl.glViewport(0, 0, width, height)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._present_texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        pixels = pygame.image.tostring(self._surface, "RGBA", True)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, width, height, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixels,
        )
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(-1, 1, -1, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        gl.glColor4f(1.0, 1.0, 1.0, 1.0)
        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0, 0); gl.glVertex2f(-1, -1)
        gl.glTexCoord2f(1, 0); gl.glVertex2f(1, -1)
        gl.glTexCoord2f(1, 1); gl.glVertex2f(1, 1)
        gl.glTexCoord2f(0, 1); gl.glVertex2f(-1, 1)
        gl.glEnd()
        gl.glDisable(gl.GL_TEXTURE_2D)

    def handle_resize(self, event: pygame.event.Event) -> None:
        """Track size and recreate the canvas when the GL context changes."""
        if event.type == pygame.VIDEORESIZE:
            self.size = (event.w, event.h)
            if self._opengl:
                pygame.display.set_mode(
                    self.size, self.flags | pygame.OPENGL | pygame.DOUBLEBUF
                )
                self._surface = pygame.Surface(self.size).convert_alpha()
                self._present_texture = 0

    def close(self) -> None:
        """Clean up pygame resources."""
        pygame.quit()
        self._surface = None
        self._present_texture = 0
