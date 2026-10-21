"""Non-modal tool-properties windows for PY3DCAD."""

from enum import Enum
from typing import Optional, Tuple

import pygame

from .layout import Rect


class ToolWindowAction(Enum):
    """Result of passing an event to a tool-properties window."""

    NONE = "none"
    CONSUMED = "consumed"
    SELECT = "select"
    CANCEL = "cancel"


class ToolPropertiesWindow:
    """A small properties panel anchored below the orientation cube.

    The window is deliberately non-modal. While it is open the user can still
    pick geometry in the viewport or the document tree. The owning workspace
    receives ``SELECT`` and ``CANCEL`` actions and decides what they mean for
    the active tool.
    """

    CUBE_SIZE = 92
    CUBE_MARGIN = 12
    PANEL_WIDTH = 322
    PANEL_HEIGHT = 158
    CUBE_GAP = 12

    def __init__(
        self,
        title: str,
        property_label: str,
        select_label: str = "Select",
        cancel_label: str = "Cancel",
    ) -> None:
        self.title = title
        self.property_label = property_label
        self.select_label = select_label
        self.cancel_label = cancel_label
        self.visible = False
        self.selecting = False
        self.scale = 1.0
        self._hover_select = False
        self._hover_cancel = False
        self._font_title: Optional[pygame.font.Font] = None
        self._font_text: Optional[pygame.font.Font] = None

        self.panel_bg = pygame.Color(38, 40, 48)
        self.title_bg = pygame.Color(48, 50, 60)
        self.border_color = pygame.Color(50, 50, 58)
        self.text_primary = pygame.Color(225, 225, 230)
        self.text_secondary = pygame.Color(202, 205, 212)
        self.text_muted = pygame.Color(125, 125, 136)
        self.accent = pygame.Color(59, 130, 246)
        self.field_bg = pygame.Color(35, 37, 46)
        self.field_hover_bg = pygame.Color(52, 58, 72)
        self.field_active_bg = pygame.Color(49, 77, 115)
        self.button_bg = pygame.Color(44, 47, 57)
        self.button_hover_bg = pygame.Color(58, 61, 72)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_title = None
        self._font_text = None
        self._hover_select = False
        self._hover_cancel = False

    def open(self) -> None:
        self.visible = True
        self.selecting = False
        self._hover_select = False
        self._hover_cancel = False

    def close(self) -> None:
        self.visible = False
        self.selecting = False
        self._hover_select = False
        self._hover_cancel = False

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _init_fonts(self) -> None:
        if self._font_title is not None:
            return
        self._font_title = pygame.font.SysFont(
            "Segoe UI", self._s(12), bold=True
        )
        self._font_text = pygame.font.SysFont("Segoe UI", self._s(12))

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def panel_rect(self, region: Rect) -> pygame.Rect:
        margin = self._s(self.CUBE_MARGIN)
        width = min(
            self._s(self.PANEL_WIDTH),
            max(1, region.w - margin * 2),
        )
        height = self._s(self.PANEL_HEIGHT)
        return pygame.Rect(
            region.right - margin - width,
            region.y + margin + self._s(self.CUBE_SIZE) + self._s(
                self.CUBE_GAP
            ),
            width,
            height,
        )

    def select_rect(self, region: Rect) -> pygame.Rect:
        panel = self.panel_rect(region)
        width = self._s(112)
        height = self._s(28)
        center_y = panel.y + self._s(34) + self._s(26)
        return pygame.Rect(
            panel.right - self._s(16) - width,
            center_y - height // 2,
            width,
            height,
        )

    def cancel_rect(self, region: Rect) -> pygame.Rect:
        panel = self.panel_rect(region)
        width = self._s(80)
        height = self._s(30)
        return pygame.Rect(
            panel.right - self._s(16) - width,
            panel.bottom - self._s(16) - height,
            width,
            height,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def update_hover(self, pos: Tuple[int, int], region: Rect) -> bool:
        """Update button hover state and report whether the panel is hovered."""
        if not self.visible:
            self._hover_select = False
            self._hover_cancel = False
            return False
        panel = self.panel_rect(region)
        if not panel.collidepoint(pos):
            self._hover_select = False
            self._hover_cancel = False
            return False
        self._hover_select = self.select_rect(region).collidepoint(pos)
        self._hover_cancel = self.cancel_rect(region).collidepoint(pos)
        return True

    def handle_event(
        self, event: pygame.event.Event, region: Rect
    ) -> ToolWindowAction:
        if not self.visible:
            return ToolWindowAction.NONE

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return ToolWindowAction.CANCEL
            return ToolWindowAction.NONE

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            panel = self.panel_rect(region)
            if not panel.collidepoint(event.pos):
                return ToolWindowAction.NONE
            if self.select_rect(region).collidepoint(event.pos):
                self.selecting = True
                return ToolWindowAction.SELECT
            if self.cancel_rect(region).collidepoint(event.pos):
                self.close()
                return ToolWindowAction.CANCEL
            return ToolWindowAction.CONSUMED

        return ToolWindowAction.NONE

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, region: Rect) -> None:
        if not self.visible:
            return
        self._init_fonts()

        panel = self.panel_rect(region)
        title_height = self._s(34)
        pygame.draw.rect(
            surface, self.panel_bg, panel, border_radius=self._s(6)
        )
        pygame.draw.rect(
            surface, self.title_bg,
            (panel.x, panel.y, panel.w, title_height),
            border_top_left_radius=self._s(6),
            border_top_right_radius=self._s(6),
        )
        pygame.draw.rect(
            surface, self.border_color, panel,
            width=1, border_radius=self._s(6),
        )
        pygame.draw.line(
            surface, self.border_color,
            (panel.x, panel.y + title_height),
            (panel.right, panel.y + title_height),
        )

        minus_y = panel.y + title_height // 2
        pygame.draw.line(
            surface, self.text_primary,
            (panel.x + self._s(14), minus_y),
            (panel.x + self._s(22), minus_y),
            self._s(2),
        )
        title = self._font_title.render(
            self.title, True, self.text_primary
        )
        surface.blit(
            title,
            title.get_rect(
                midleft=(panel.x + self._s(30), minus_y)
            ),
        )

        select_rect = self.select_rect(region)
        label = self._font_text.render(
            self.property_label, True, self.text_secondary
        )
        surface.blit(
            label,
            label.get_rect(
                midleft=(panel.x + self._s(16), select_rect.centery)
            ),
        )

        if self.selecting:
            select_fill = self.field_active_bg
        elif self._hover_select:
            select_fill = self.field_hover_bg
        else:
            select_fill = self.field_bg
        pygame.draw.rect(
            surface, select_fill, select_rect,
            border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.accent, select_rect,
            width=self._s(2), border_radius=self._s(4),
        )
        self._draw_cursor_icon(
            surface,
            (select_rect.x + self._s(18), select_rect.centery),
            self.text_primary,
        )
        select_text = self._font_text.render(
            self.select_label, True, self.text_primary
        )
        surface.blit(
            select_text,
            select_text.get_rect(
                midleft=(select_rect.x + self._s(32), select_rect.centery)
            ),
        )

        self._draw_info_icon(
            surface,
            (panel.x + self._s(21), panel.bottom - self._s(23)),
            self.text_muted,
        )

        cancel_rect = self.cancel_rect(region)
        cancel_fill = (
            self.button_hover_bg
            if self._hover_cancel
            else self.button_bg
        )
        pygame.draw.rect(
            surface, cancel_fill, cancel_rect,
            border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.border_color, cancel_rect,
            width=1, border_radius=self._s(4),
        )
        cancel_text = self._font_text.render(
            self.cancel_label, True, self.text_primary
        )
        surface.blit(
            cancel_text, cancel_text.get_rect(center=cancel_rect.center)
        )

    def _draw_cursor_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        points = [
            (cx - self._s(3), cy - self._s(6)),
            (cx + self._s(5), cy + self._s(2)),
            (cx + self._s(1), cy + self._s(2)),
            (cx + self._s(3), cy + self._s(6)),
            (cx + self._s(1), cy + self._s(7)),
            (cx - self._s(1), cy + self._s(3)),
            (cx - self._s(4), cy + self._s(5)),
        ]
        pygame.draw.polygon(surface, color, points)

    def _draw_info_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        radius = self._s(8)
        pygame.draw.circle(
            surface, color, center, radius, max(1, self._s(1))
        )
        pygame.draw.circle(
            surface, color, (cx, cy - self._s(3)), self._s(1)
        )
        pygame.draw.line(
            surface, color,
            (cx, cy - self._s(1)), (cx, cy + self._s(4)),
            max(1, self._s(1)),
        )
