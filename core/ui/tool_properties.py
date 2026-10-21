"""Non-modal tool-properties windows for PY3DCAD."""

from enum import Enum
from typing import Optional, Tuple, List

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


class SketchPaletteAction(Enum):
    NONE = "none"
    CONSUMED = "consumed"
    MINIMIZE = "minimize"
    LINETYPE_CHANGED = "linetype_changed"
    LOOK_AT = "look_at"
    FINISH_SKETCH = "finish_sketch"


class SketchPaletteWindow:
    """Sketch Palette window shown while a sketch is being edited.

    Anchored below the orientation cube. Contains:
    - Title bar: "SKETCH PALETTE" with minimize button on the left
    - Options: collapsible section header
    - Linetype: three icon buttons (solid, dash-dot, dashed)
    - Look At: label with icon button on the right
    - Sketch Status: read-only field "Fully constrained"
    - Finish Sketch: primary button at bottom right
    """

    CUBE_SIZE = 92
    CUBE_MARGIN = 12
    PANEL_WIDTH = 322
    PANEL_HEIGHT = 280
    CUBE_GAP = 12

    # Line type: key, tooltip
    LINE_TYPES = [
        ("normal", "Solid"),
        ("dashdot", "Dash-dot"),
        ("dashed", "Dashed"),
    ]

    def __init__(self) -> None:
        self.visible = False
        self.minimized = False
        self.scale = 1.0
        self.current_line_type = "normal"
        self._hover_minimize = False
        self._hover_options = False
        self._hover_linetype = -1
        self._hover_look = False
        self._hover_finish = False
        self._font_title: Optional[pygame.font.Font] = None
        self._font_text: Optional[pygame.font.Font] = None
        self._font_small: Optional[pygame.font.Font] = None

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
        self.header_bg = pygame.Color(42, 44, 52)
        self.header_hover_bg = pygame.Color(50, 52, 60)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_title = None
        self._font_text = None
        self._font_small = None
        self._hover_minimize = False
        self._hover_options = False
        self._hover_linetype = -1
        self._hover_look = False
        self._hover_finish = False

    def open(self, line_type: str = "normal") -> None:
        self.visible = True
        self.minimized = False
        self.current_line_type = line_type
        self._hover_minimize = False
        self._hover_options = False
        self._hover_linetype = -1
        self._hover_look = False
        self._hover_finish = False

    def close(self) -> None:
        self.visible = False
        self._hover_minimize = False
        self._hover_options = False
        self._hover_linetype = -1
        self._hover_look = False
        self._hover_finish = False

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _init_fonts(self) -> None:
        if self._font_title is not None:
            return
        self._font_title = pygame.font.SysFont(
            "Segoe UI", self._s(12), bold=True
        )
        self._font_text = pygame.font.SysFont("Segoe UI", self._s(12))
        self._font_small = pygame.font.SysFont("Segoe UI", self._s(11))

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def panel_rect(self, region: Rect) -> pygame.Rect:
        margin = self._s(self.CUBE_MARGIN)
        width = min(
            self._s(self.PANEL_WIDTH),
            max(1, region.w - margin * 2),
        )
        height = self._s(self.PANEL_HEIGHT if not self.minimized else 40)
        return pygame.Rect(
            region.right - margin - width,
            region.y + margin + self._s(self.CUBE_SIZE) + self._s(
                self.CUBE_GAP
            ),
            width,
            height,
        )

    def minimize_rect(self, region: Rect) -> pygame.Rect:
        """Minimize button on the left of title bar."""
        panel = self.panel_rect(region)
        size = self._s(20)
        return pygame.Rect(
            panel.x + self._s(8),
            panel.y + (self._s(34) - size) // 2,
            size,
            size,
        )

    def options_rect(self, region: Rect) -> pygame.Rect:
        """Options collapsible header."""
        panel = self.panel_rect(region)
        return pygame.Rect(
            panel.x,
            panel.y + self._s(34),
            panel.w,
            self._s(30),
        )

    def line_type_rects(self, region: Rect) -> List[pygame.Rect]:
        """Three equal icon buttons in a row."""
        panel = self.panel_rect(region)
        btn_size = self._s(36)
        gap = self._s(8)
        total_w = 3 * btn_size + 2 * gap
        start_x = panel.x + (panel.w - total_w) // 2
        y = panel.y + self._s(34) + self._s(30) + self._s(12)
        rects = []
        for i in range(3):
            rects.append(pygame.Rect(
                start_x + i * (btn_size + gap),
                y,
                btn_size,
                btn_size,
            ))
        return rects

    def look_at_rect(self, region: Rect) -> Tuple[pygame.Rect, pygame.Rect]:
        """Returns (label_rect, button_rect) for Look At row."""
        panel = self.panel_rect(region)
        y = panel.y + self._s(34) + self._s(30) + self._s(12) + self._s(36) + self._s(16)
        label_rect = pygame.Rect(
            panel.x + self._s(16),
            y,
            panel.w - self._s(16) * 2 - self._s(40),
            self._s(28),
        )
        btn_rect = pygame.Rect(
            panel.right - self._s(16) - self._s(28),
            y,
            self._s(28),
            self._s(28),
        )
        return label_rect, btn_rect

    def status_rect(self, region: Rect) -> pygame.Rect:
        """Sketch Status read-only field."""
        panel = self.panel_rect(region)
        label_rect, _ = self.look_at_rect(region)
        y = label_rect.bottom + self._s(8)
        return pygame.Rect(
            panel.x + self._s(16),
            y,
            panel.w - self._s(32),
            self._s(28),
        )

    def finish_rect(self, region: Rect) -> pygame.Rect:
        """Finish Sketch button at bottom right."""
        panel = self.panel_rect(region)
        btn_width = self._s(120)
        btn_height = self._s(32)
        return pygame.Rect(
            panel.right - self._s(16) - btn_width,
            panel.bottom - self._s(16) - btn_height,
            btn_width,
            btn_height,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def update_hover(self, pos: Tuple[int, int], region: Rect) -> bool:
        if not self.visible:
            self._hover_minimize = False
            self._hover_options = False
            self._hover_linetype = -1
            self._hover_look = False
            self._hover_finish = False
            return False
        panel = self.panel_rect(region)
        if not panel.collidepoint(pos):
            self._hover_minimize = False
            self._hover_options = False
            self._hover_linetype = -1
            self._hover_look = False
            self._hover_finish = False
            return False

        if self.minimized:
            self._hover_minimize = self.minimize_rect(region).collidepoint(pos)
            return self._hover_minimize

        self._hover_minimize = self.minimize_rect(region).collidepoint(pos)
        self._hover_options = self.options_rect(region).collidepoint(pos)
        self._hover_linetype = -1
        for i, rect in enumerate(self.line_type_rects(region)):
            if rect.collidepoint(pos):
                self._hover_linetype = i
                break
        _, look_btn = self.look_at_rect(region)
        self._hover_look = look_btn.collidepoint(pos)
        self._hover_finish = self.finish_rect(region).collidepoint(pos)
        return True

    def handle_event(
        self, event: pygame.event.Event, region: Rect
    ) -> SketchPaletteAction:
        if not self.visible:
            return SketchPaletteAction.NONE

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return SketchPaletteAction.FINISH_SKETCH
            return SketchPaletteAction.NONE

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            panel = self.panel_rect(region)
            if not panel.collidepoint(event.pos):
                return SketchPaletteAction.NONE

            if self.minimized:
                if self.minimize_rect(region).collidepoint(event.pos):
                    self.minimized = False
                    return SketchPaletteAction.MINIMIZE
                return SketchPaletteAction.CONSUMED

            if self.minimize_rect(region).collidepoint(event.pos):
                self.minimized = True
                return SketchPaletteAction.MINIMIZE

            if self.options_rect(region).collidepoint(event.pos):
                # Toggle options collapse (placeholder)
                return SketchPaletteAction.CONSUMED

            for i, rect in enumerate(self.line_type_rects(region)):
                if rect.collidepoint(event.pos):
                    self.current_line_type = self.LINE_TYPES[i][0]
                    return SketchPaletteAction.LINETYPE_CHANGED

            _, look_btn = self.look_at_rect(region)
            if look_btn.collidepoint(event.pos):
                return SketchPaletteAction.LOOK_AT

            if self.finish_rect(region).collidepoint(event.pos):
                self.close()
                return SketchPaletteAction.FINISH_SKETCH

            return SketchPaletteAction.CONSUMED

        return SketchPaletteAction.NONE

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, region: Rect) -> None:
        if not self.visible:
            return
        self._init_fonts()

        panel = self.panel_rect(region)
        title_height = self._s(34)

        # Panel background
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

        # Minimize button (left)
        min_rect = self.minimize_rect(region)
        min_fill = self.header_hover_bg if self._hover_minimize else self.title_bg
        pygame.draw.rect(
            surface, min_fill, min_rect, border_radius=self._s(3)
        )
        pygame.draw.rect(
            surface, self.border_color, min_rect,
            width=1, border_radius=self._s(3),
        )
        # Minimize icon: horizontal line
        cx, cy = min_rect.center
        pygame.draw.line(
            surface, self.text_primary,
            (cx - self._s(5), cy), (cx + self._s(5), cy),
            self._s(2)
        )

        # Title
        title = self._font_title.render(
            "SKETCH PALETTE", True, self.text_primary
        )
        surface.blit(
            title,
            title.get_rect(
                midleft=(panel.x + self._s(36), panel.y + title_height // 2)
            ),
        )

        if self.minimized:
            return

        # Options header (collapsible)
        opt_rect = self.options_rect(region)
        opt_fill = self.header_hover_bg if self._hover_options else self.header_bg
        pygame.draw.rect(
            surface, opt_fill, opt_rect, border_radius=0
        )
        pygame.draw.line(
            surface, self.border_color,
            (opt_rect.x, opt_rect.bottom),
            (opt_rect.right, opt_rect.bottom),
        )
        opt_text = self._font_text.render(
            "Options", True, self.text_secondary
        )
        surface.blit(
            opt_text,
            opt_text.get_rect(midleft=(opt_rect.x + self._s(16), opt_rect.centery))
        )
        # Chevron down
        cx = opt_rect.right - self._s(20)
        cy = opt_rect.centery
        pygame.draw.polygon(surface, self.text_muted, [
            (cx - self._s(4), cy - self._s(2)),
            (cx + self._s(4), cy - self._s(2)),
            (cx, cy + self._s(3)),
        ])

        # Linetype: three icon buttons
        line_type_rects = self.line_type_rects(region)
        for i, (key, tooltip) in enumerate(self.LINE_TYPES):
            rect = line_type_rects[i]
            is_active = key == self.current_line_type
            is_hovered = i == self._hover_linetype

            if is_active:
                fill = self.field_active_bg
            elif is_hovered:
                fill = self.field_hover_bg
            else:
                fill = self.field_bg
            pygame.draw.rect(
                surface, fill, rect, border_radius=self._s(4)
            )
            border_color = self.accent if is_active else self.border_color
            border_width = self._s(2) if is_active else 1
            pygame.draw.rect(
                surface, border_color, rect,
                width=border_width, border_radius=self._s(4)
            )
            self._draw_line_type_symbol(surface, rect.center, key, self.text_primary)

        # Look At row
        label_rect, look_btn = self.look_at_rect(region)
        look_text = self._font_text.render(
            "Look At", True, self.text_secondary
        )
        surface.blit(
            look_text, look_text.get_rect(midleft=(label_rect.x, label_rect.centery))
        )
        # Look At icon button
        look_fill = self.button_hover_bg if self._hover_look else self.button_bg
        pygame.draw.rect(
            surface, look_fill, look_btn, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, self.border_color, look_btn,
            width=1, border_radius=self._s(4),
        )
        self._draw_view_icon(surface, look_btn.center, self.text_primary)

        # Sketch Status read-only field
        status_rect = self.status_rect(region)
        pygame.draw.rect(
            surface, self.field_bg, status_rect, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, self.border_color, status_rect,
            width=1, border_radius=self._s(4),
        )
        status_label = self._font_small.render(
            "Status", True, self.text_muted
        )
        surface.blit(
            status_label,
            status_label.get_rect(midleft=(status_rect.x + self._s(8), status_rect.y + self._s(6)))
        )
        status_val = self._font_text.render(
            "Fully constrained", True, self.text_primary
        )
        surface.blit(
            status_val,
            status_val.get_rect(midleft=(status_rect.x + self._s(8), status_rect.bottom - self._s(8)))
        )

        # Finish Sketch button (bottom right)
        finish_rect = self.finish_rect(region)
        finish_fill = self.field_active_bg if self._hover_finish else self.button_bg
        pygame.draw.rect(
            surface, finish_fill, finish_rect, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, self.accent, finish_rect,
            width=self._s(2), border_radius=self._s(4),
        )
        finish_text = self._font_text.render(
            "Finish Sketch", True, self.text_primary
        )
        surface.blit(
            finish_text, finish_text.get_rect(center=finish_rect.center)
        )

    def _draw_line_type_symbol(
        self, surface: pygame.Surface, center: Tuple[int, int],
        line_type: str, color: pygame.Color,
    ) -> None:
        """Draw a line type symbol (icon) at center."""
        cx, cy = center
        w = self._s(18)

        if line_type == "normal":
            # Solid horizontal line
            pygame.draw.line(
                surface, color,
                (cx - w // 2, cy), (cx + w // 2, cy),
                max(2, self._s(2))
            )
        elif line_type == "dashdot":
            # Dash-dot pattern: long - dot - long
            pygame.draw.line(surface, color,
                (cx - w // 2, cy), (cx - w // 6, cy), max(2, self._s(2)))
            pygame.draw.circle(surface, color, (cx, cy), max(1, self._s(2)))
            pygame.draw.line(surface, color,
                (cx + w // 6, cy), (cx + w // 2, cy), max(2, self._s(2)))
        elif line_type == "dashed":
            # Dashed: three dashes
            dash_w = w // 3
            gap = self._s(3)
            for i in range(3):
                x0 = cx - w // 2 + i * (dash_w + gap)
                pygame.draw.line(
                    surface, color,
                    (x0, cy), (x0 + dash_w, cy),
                    max(2, self._s(2))
                )

    def _draw_view_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        s = self._s(6)
        # Camera body
        pygame.draw.rect(
            surface, color,
            (cx - s, cy - s // 2, self._s(12), s),
            max(1, self._s(1))
        )
        # Lens
        pygame.draw.circle(
            surface, color, (cx + self._s(5), cy), s // 2 + 1,
            max(1, self._s(1))
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