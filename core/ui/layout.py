"""UI layout system for PY3DCAD."""

import pygame
from dataclasses import dataclass
from typing import Optional
from .window import Window


@dataclass
class LayoutConfig:
    """Configuration for UI layout dimensions."""
    tab_bar_height: int = 36
    toolbar_height: int = 104
    command_bar_height: int = 36
    timeline_height: int = 84
    sidebar_width: int = 280
    viewport_margin: int = 4


class Rect:
    """Simple rectangle helper for layout calculations."""
    
    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
    
    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.w, self.h)

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def centerx(self) -> int:
        return self.x + self.w // 2

    @property
    def centery(self) -> int:
        return self.y + self.h // 2

    @property
    def center(self) -> tuple[int, int]:
        return (self.centerx, self.centery)

    def collidepoint(self, x: int, y: Optional[int] = None) -> bool:
        if y is None:
            x, y = x
        return self.x <= x < self.right and self.y <= y < self.bottom

    def __repr__(self) -> str:
        return f"Rect({self.x}, {self.y}, {self.w}, {self.h})"


class UILayout:
    """Manages the application UI layout regions."""
    
    def __init__(self, config: Optional[LayoutConfig] = None):
        self.config = config or LayoutConfig()
        self.show_command_bar = True
        self.scale = 1.0
        
        # Layout regions
        self.tab_bar = Rect(0, 0, 0, 0)
        self.toolbar = Rect(0, 0, 0, 0)
        self.document_tree = Rect(0, 0, 0, 0)
        self.viewport = Rect(0, 0, 0, 0)
        self.command_bar = Rect(0, 0, 0, 0)
        self.timeline = Rect(0, 0, 0, 0)

    def set_scale(self, scale: float) -> None:
        self.scale = max(0.5, min(2.5, scale))

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))
    
    def update(self, window: Window) -> None:
        """Recalculate all layout regions based on window size."""
        w, h = window.get_size()
        c = self.config
        m = self._s(c.viewport_margin)
        tab_h = self._s(c.tab_bar_height)
        toolbar_h = self._s(c.toolbar_height)
        timeline_h = self._s(c.timeline_height)
        command_h = self._s(c.command_bar_height)
        sidebar_w = self._s(c.sidebar_width)
        
        # Top bars (span full width)
        y = 0
        self.tab_bar = Rect(0, y, w, tab_h)
        y += tab_h
        
        self.toolbar = Rect(0, y, w, toolbar_h)
        y += toolbar_h
        
        # Bottom bars (span full width)
        bottom_y = h
        self.timeline = Rect(0, bottom_y - timeline_h, w, timeline_h)
        bottom_y -= timeline_h
        
        if self.show_command_bar:
            self.command_bar = Rect(0, bottom_y - command_h, w, command_h)
            bottom_y -= command_h
        else:
            self.command_bar = Rect(0, bottom_y, w, 0)
        
        # Left sidebar (document tree)
        self.document_tree = Rect(
            m, y, sidebar_w - 2 * m, bottom_y - y - m
        )
        
        # Right viewport (3D view)
        viewport_x = sidebar_w + m
        viewport_w = w - viewport_x - m
        viewport_h = bottom_y - y - m
        self.viewport = Rect(viewport_x, y, viewport_w, viewport_h)
    
    def get_region(self, name: str) -> Rect:
        """Get a layout region by name."""
        regions = {
            "tab_bar": self.tab_bar,
            "toolbar": self.toolbar,
            "document_tree": self.document_tree,
            "viewport": self.viewport,
            "command_bar": self.command_bar,
            "timeline": self.timeline,
        }
        return regions.get(name, Rect(0, 0, 0, 0))
    
    def toggle_command_bar(self) -> None:
        """Toggle command bar visibility."""
        self.show_command_bar = not self.show_command_bar
    
    def set_command_bar_visible(self, visible: bool) -> None:
        """Set command bar visibility."""
        self.show_command_bar = visible