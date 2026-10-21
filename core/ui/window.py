"""Window system for PY3DCAD."""

import pygame
from typing import Optional, Tuple


class Window:
    """Main application window using pygame-ce."""

    def __init__(
        self,
        title: str = "PY3DCAD",
        size: Tuple[int, int] = (1280, 720),
        flags: int = pygame.RESIZABLE,
    ) -> None:
        self.title = title
        self.size = size
        self.flags = flags
        self._surface: Optional[pygame.Surface] = None
        self._clock = pygame.time.Clock()
        self._running = False

    def create(self) -> None:
        """Initialize pygame and create the window surface."""
        pygame.init()
        pygame.display.set_caption(self.title)
        self._surface = pygame.display.set_mode(self.size, self.flags)

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
        pygame.display.flip()

    def handle_resize(self, event: pygame.event.Event) -> None:
        """Track the new window size; SDL2 resizes the existing surface itself.

        Calling pygame.display.set_mode() here would replace the window, so it
        must never be done on a resize event.
        """
        if event.type == pygame.VIDEORESIZE:
            self.size = (event.w, event.h)

    def close(self) -> None:
        """Clean up pygame resources."""
        pygame.quit()
        self._surface = None