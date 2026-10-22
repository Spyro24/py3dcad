"""Non-modal tool-properties windows for PY3DCAD."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple, List

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


@dataclass
class _PaletteLayout:
    """Computed rectangles for the sketch palette."""

    panel: pygame.Rect
    title: pygame.Rect
    minimize: pygame.Rect
    options: pygame.Rect
    line_types: List[pygame.Rect] = field(default_factory=list)
    look_at: pygame.Rect = field(
        default_factory=lambda: pygame.Rect(0, 0, 0, 0)
    )
    option_rows: List[Tuple[int, pygame.Rect, pygame.Rect]] = field(
        default_factory=list
    )
    status: pygame.Rect = field(
        default_factory=lambda: pygame.Rect(0, 0, 0, 0)
    )
    finish: pygame.Rect = field(
        default_factory=lambda: pygame.Rect(0, 0, 0, 0)
    )


class SketchPaletteWindow:
    """Sketch Palette panel shown while a sketch is being edited.

    The panel is anchored below the orientation cube and contains the options
    that are relevant while sketching: line style, camera alignment, display
    toggles, constraint status and the finish action. On short viewports the
    body scrolls instead of growing past the viewport bounds.
    """

    CUBE_SIZE = 92
    CUBE_MARGIN = 12
    CUBE_GAP = 12
    PANEL_WIDTH = 322
    TITLE_HEIGHT = 32
    OPTIONS_HEIGHT = 24
    LINE_ROW_HEIGHT = 40
    LOOK_ROW_HEIGHT = 28
    OPTION_ROW_HEIGHT = 22
    STATUS_HEIGHT = 46
    FINISH_HEIGHT = 32

    # Line type: key, label
    LINE_TYPES = [
        ("normal", "Solid"),
        ("dashed", "Dashed"),
        ("dashdot", "Dash-dot"),
        ("construction", "Construction"),
    ]

    # Display toggles: key, label, default
    OPTION_ROWS = [
        ("sketch_grid", "Sketch Grid", True),
        ("snap", "Snap", True),
        ("slice", "Slice", False),
        ("profile", "Profile", True),
        ("points", "Points", True),
        ("dimensions", "Dimensions", True),
        ("constraints", "Constraints", True),
        ("projected", "Projected Geometries", True),
        ("construction", "Construction Geometries", True),
        ("3d_sketch", "3D Sketch", False),
    ]

    def __init__(self) -> None:
        self.visible = False
        self.minimized = False
        self.options_expanded = True
        self.scale = 1.0
        self.current_line_type = "normal"
        self.options: Dict[str, bool] = {
            key: default for key, _label, default in self.OPTION_ROWS
        }
        self._scroll = 0
        self._hover_minimize = False
        self._hover_options = False
        self._hover_linetype = -1
        self._hover_look = False
        self._hover_option = -1
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
        self.accent_hover = pygame.Color(88, 155, 255)
        self.success = pygame.Color(82, 205, 132)
        self.field_bg = pygame.Color(35, 37, 46)
        self.field_hover_bg = pygame.Color(52, 58, 72)
        self.header_bg = pygame.Color(42, 44, 52)
        self.header_hover_bg = pygame.Color(50, 52, 60)
        self.scrollbar_color = pygame.Color(70, 70, 82)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_title = None
        self._font_text = None
        self._font_small = None
        self._reset_hover()

    def open(self, line_type: str = "normal") -> None:
        self.visible = True
        self.minimized = False
        self.options_expanded = True
        self.current_line_type = line_type
        self._scroll = 0
        self._reset_hover()

    def close(self) -> None:
        self.visible = False
        self._reset_hover()

    def _reset_hover(self) -> None:
        self._hover_minimize = False
        self._hover_options = False
        self._hover_linetype = -1
        self._hover_look = False
        self._hover_option = -1
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

    def _fixed_bottom_height(self) -> int:
        """Height of the status field, finish button and bottom padding."""
        return (
            self._s(self.STATUS_HEIGHT) + self._s(8)
            + self._s(self.FINISH_HEIGHT) + self._s(12)
        )

    def _body_content_height(self) -> int:
        """Scrollable content between the title bar and the fixed footer."""
        height = 4 + self.OPTIONS_HEIGHT + 4
        if self.options_expanded:
            height += self.LINE_ROW_HEIGHT + 4
            height += self.LOOK_ROW_HEIGHT + 4
            height += self.OPTION_ROW_HEIGHT * len(self.OPTION_ROWS) + 8
        return self._s(height)

    def _content_height(self) -> int:
        """Full height of the panel content at the current scale."""
        if self.minimized:
            return self._s(self.TITLE_HEIGHT)
        return (
            self._s(self.TITLE_HEIGHT) + self._body_content_height()
            + self._fixed_bottom_height()
        )

    def panel_rect(self, region: Rect) -> pygame.Rect:
        margin = self._s(self.CUBE_MARGIN)
        width = min(
            self._s(self.PANEL_WIDTH),
            max(1, region.w - margin * 2),
        )
        y = (
            region.y + margin + self._s(self.CUBE_SIZE)
            + self._s(self.CUBE_GAP)
        )
        min_visible = self._s(self.TITLE_HEIGHT + 8)
        y = min(y, region.bottom - margin - min_visible)
        y = max(region.y + margin, y)
        if self.minimized:
            height = self._s(self.TITLE_HEIGHT)
        else:
            available = region.bottom - margin - y
            height = min(
                self._content_height(),
                max(self._s(self.TITLE_HEIGHT), available),
            )
        return pygame.Rect(
            region.right - margin - width,
            y,
            width,
            max(self._s(self.TITLE_HEIGHT), height),
        )

    def _body_rect(self, panel: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(
            panel.x + 1,
            panel.y + self._s(self.TITLE_HEIGHT),
            panel.w - 2,
            max(
                0,
                panel.h - self._s(self.TITLE_HEIGHT)
                - self._fixed_bottom_height(),
            ),
        )

    def _max_scroll(self, region: Rect) -> int:
        panel = self.panel_rect(region)
        body = self._body_rect(panel)
        return max(0, self._body_content_height() - body.h)

    def _layout(self, region: Rect) -> _PaletteLayout:
        self._init_fonts()
        panel = self.panel_rect(region)
        self._scroll = max(0, min(self._scroll, self._max_scroll(region)))

        title = pygame.Rect(
            panel.x + self._s(8),
            panel.y + self._s(4),
            panel.w - self._s(16),
            self._s(self.TITLE_HEIGHT - 8),
        )
        minimize = pygame.Rect(
            title.x, title.y, self._s(26), title.h
        )
        body_top = panel.y + self._s(self.TITLE_HEIGHT)
        options = pygame.Rect(
            panel.x + self._s(8),
            body_top + self._s(4) - self._scroll,
            panel.w - self._s(16),
            self._s(self.OPTIONS_HEIGHT),
        )
        layout = _PaletteLayout(
            panel=panel, title=title, minimize=minimize, options=options
        )
        if self.minimized:
            return layout

        y = options.bottom + self._s(4)
        if self.options_expanded:
            size = self._s(36)
            gap = self._s(6)
            total = size * len(self.LINE_TYPES) + gap * (len(self.LINE_TYPES) - 1)
            start_x = panel.right - self._s(14) - total
            layout.line_types = [
                pygame.Rect(
                    start_x + index * (size + gap),
                    y + self._s(2),
                    size,
                    size,
                )
                for index in range(len(self.LINE_TYPES))
            ]
            y += self._s(self.LINE_ROW_HEIGHT) + self._s(4)

            layout.look_at = pygame.Rect(
                panel.right - self._s(14) - self._s(22),
                y + self._s(3),
                self._s(22),
                self._s(22),
            )
            y += self._s(self.LOOK_ROW_HEIGHT) + self._s(4)

            for index, (_key, _label, _default) in enumerate(self.OPTION_ROWS):
                row = pygame.Rect(
                    panel.x + self._s(8),
                    y,
                    panel.w - self._s(16),
                    self._s(self.OPTION_ROW_HEIGHT),
                )
                box = pygame.Rect(
                    panel.right - self._s(16) - self._s(14),
                    row.centery - self._s(7),
                    self._s(14),
                    self._s(14),
                )
                layout.option_rows.append((index, row, box))
                y += self._s(self.OPTION_ROW_HEIGHT)

        finish_height = self._s(self.FINISH_HEIGHT)
        layout.finish = pygame.Rect(
            panel.right - self._s(16) - min(
                self._s(120), panel.w - self._s(32)
            ),
            panel.bottom - self._s(12) - finish_height,
            min(self._s(120), panel.w - self._s(32)),
            finish_height,
        )
        layout.status = pygame.Rect(
            panel.x + self._s(16),
            layout.finish.y - self._s(8) - self._s(self.STATUS_HEIGHT),
            panel.w - self._s(32),
            self._s(self.STATUS_HEIGHT),
        )
        return layout

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def update_hover(self, pos: Tuple[int, int], region: Rect) -> bool:
        self._reset_hover()
        if not self.visible:
            return False

        layout = self._layout(region)
        if not layout.panel.collidepoint(pos):
            return False

        self._hover_minimize = layout.minimize.collidepoint(pos)
        if self.minimized:
            return True

        self._hover_finish = False
        body = self._body_rect(layout.panel)
        if body.h > 0:
            self._hover_finish = layout.finish.collidepoint(pos)
        if not body.collidepoint(pos):
            return True

        self._hover_options = layout.options.collidepoint(pos)
        if not self.options_expanded:
            return True

        for index, rect in enumerate(layout.line_types):
            if rect.collidepoint(pos):
                self._hover_linetype = index
                break
        self._hover_look = layout.look_at.collidepoint(pos)
        for index, row, _box in layout.option_rows:
            if not body.contains(row):
                continue
            if row.collidepoint(pos):
                self._hover_option = index
                break
        return True

    def _toggle_options(self) -> None:
        self.options_expanded = not self.options_expanded
        self._scroll = 0

    def _toggle_option(self, index: int) -> None:
        key = self.OPTION_ROWS[index][0]
        self.options[key] = not self.options[key]

    def _scroll_by(self, amount: int, region: Rect) -> None:
        maximum = self._max_scroll(region)
        self._scroll = max(0, min(maximum, self._scroll + amount))

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

        if event.type == pygame.MOUSEMOTION:
            inside = self.update_hover(event.pos, region)
            if inside:
                return SketchPaletteAction.CONSUMED
            return SketchPaletteAction.NONE

        if event.type == pygame.MOUSEWHEEL:
            panel = self.panel_rect(region)
            if not panel.collidepoint(pygame.mouse.get_pos()):
                return SketchPaletteAction.NONE
            self._scroll_by(-event.y * self._s(36), region)
            return SketchPaletteAction.CONSUMED

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            layout = self._layout(region)
            panel = layout.panel
            if not panel.collidepoint(event.pos):
                return SketchPaletteAction.NONE

            if layout.minimize.collidepoint(event.pos):
                self.minimized = not self.minimized
                self._reset_hover()
                return SketchPaletteAction.MINIMIZE

            if self.minimized:
                return SketchPaletteAction.CONSUMED

            body = self._body_rect(panel)
            if body.h <= 0:
                return SketchPaletteAction.CONSUMED

            if layout.finish.collidepoint(event.pos):
                self.close()
                return SketchPaletteAction.FINISH_SKETCH

            if body.collidepoint(event.pos):
                if layout.options.collidepoint(event.pos):
                    self._toggle_options()
                    return SketchPaletteAction.CONSUMED

                if self.options_expanded:
                    for index, rect in enumerate(layout.line_types):
                        if rect.collidepoint(event.pos):
                            self.current_line_type = self.LINE_TYPES[index][0]
                            return SketchPaletteAction.LINETYPE_CHANGED

                    if layout.look_at.collidepoint(event.pos):
                        return SketchPaletteAction.LOOK_AT

                    for index, row, _box in layout.option_rows:
                        if not body.contains(row):
                            continue
                        if row.collidepoint(event.pos):
                            self._toggle_option(index)
                            return SketchPaletteAction.CONSUMED

            return SketchPaletteAction.CONSUMED

        return SketchPaletteAction.NONE

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, region: Rect) -> None:
        if not self.visible:
            return
        self._init_fonts()
        layout = self._layout(region)
        panel = layout.panel

        pygame.draw.rect(
            surface, self.panel_bg, panel, border_radius=self._s(6)
        )

        title_fill = (
            self.header_hover_bg if self._hover_minimize else self.title_bg
        )
        pygame.draw.rect(
            surface, title_fill, layout.title,
            border_radius=self._s(4),
        )
        cx, cy = layout.minimize.center
        pygame.draw.line(
            surface, self.text_primary,
            (cx - self._s(5), cy), (cx + self._s(5), cy),
            max(1, self._s(2)),
        )
        title = self._font_title.render(
            "SKETCH PALETTE", True, self.text_primary
        )
        surface.blit(
            title,
            title.get_rect(
                midleft=(layout.title.x + self._s(32), layout.title.centery)
            ),
        )

        if not self.minimized:
            body = self._body_rect(panel)
            if body.h > 0:
                previous_clip = surface.get_clip()
                surface.set_clip(body.clip(previous_clip))
                self._draw_body(surface, layout)
                surface.set_clip(previous_clip)
                self._draw_status(surface, layout.status)
                self._draw_finish(surface, layout.finish)
                self._draw_scrollbar(surface, layout, region)

        pygame.draw.rect(
            surface, self.border_color, panel,
            width=1, border_radius=self._s(6),
        )

    def _draw_body(
        self, surface: pygame.Surface, layout: _PaletteLayout
    ) -> None:
        panel = layout.panel
        options = layout.options
        opt_fill = (
            self.header_hover_bg if self._hover_options else self.header_bg
        )
        pygame.draw.rect(
            surface, opt_fill, options, border_radius=self._s(4)
        )
        cx = options.x + self._s(12)
        cy = options.centery
        if self.options_expanded:
            points = [
                (cx - self._s(4), cy - self._s(2)),
                (cx + self._s(4), cy - self._s(2)),
                (cx, cy + self._s(3)),
            ]
        else:
            points = [
                (cx - self._s(2), cy - self._s(4)),
                (cx - self._s(2), cy + self._s(4)),
                (cx + self._s(3), cy),
            ]
        pygame.draw.polygon(surface, self.text_secondary, points)
        opt_text = self._font_text.render(
            "Options", True, self.text_secondary
        )
        surface.blit(
            opt_text,
            opt_text.get_rect(
                midleft=(options.x + self._s(24), options.centery)
            ),
        )

        if self.options_expanded:
            self._draw_linetype_row(surface, layout)
            self._draw_look_at_row(surface, layout)
            self._draw_option_rows(surface, layout)

    def _draw_linetype_row(
        self, surface: pygame.Surface, layout: _PaletteLayout
    ) -> None:
        panel = layout.panel
        label = self._font_text.render(
            "Linetype", True, self.text_secondary
        )
        first = layout.line_types[0]
        surface.blit(
            label,
            label.get_rect(
                midleft=(panel.x + self._s(16), first.centery)
            ),
        )
        for index, rect in enumerate(layout.line_types):
            key = self.LINE_TYPES[index][0]
            active = key == self.current_line_type
            hovered = index == self._hover_linetype
            if active:
                fill = self.accent
            elif hovered:
                fill = self.field_hover_bg
            else:
                fill = self.field_bg
            pygame.draw.rect(
                surface, fill, rect, border_radius=self._s(3)
            )
            pygame.draw.rect(
                surface,
                self.accent_hover if active else self.border_color,
                rect,
                width=1,
                border_radius=self._s(3),
            )
            if active:
                color = pygame.Color(255, 255, 255)
            elif key == "construction":
                color = self.success
            else:
                color = self.text_primary
            self._draw_line_type_symbol(surface, rect.center, key, color)

    def _draw_look_at_row(
        self, surface: pygame.Surface, layout: _PaletteLayout
    ) -> None:
        panel = layout.panel
        rect = layout.look_at
        label = self._font_text.render(
            "Look At", True, self.text_secondary
        )
        surface.blit(
            label,
            label.get_rect(
                midleft=(panel.x + self._s(16), rect.centery)
            ),
        )
        color = self.text_primary if self._hover_look else self.text_secondary
        self._draw_look_at_icon(surface, rect.center, color)

    def _draw_option_rows(
        self, surface: pygame.Surface, layout: _PaletteLayout
    ) -> None:
        panel = layout.panel
        body = self._body_rect(panel)
        for index, row, box in layout.option_rows:
            if not body.contains(row):
                continue
            key = self.OPTION_ROWS[index][0]
            checked = self.options.get(key, False)
            hovered = index == self._hover_option
            color = (
                self.text_primary if checked or hovered
                else self.text_secondary
            )
            if hovered:
                pygame.draw.rect(
                    surface, self.header_bg, row,
                    border_radius=self._s(3),
                )
            text_x = panel.x + self._s(16)
            max_width = box.x - text_x - self._s(12)
            label = self._font_text.render(
                self._fit_text(
                    self._font_text, self.OPTION_ROWS[index][1], max_width
                ),
                True,
                color,
            )
            surface.blit(
                label, label.get_rect(midleft=(text_x, row.centery))
            )
            self._draw_checkbox(surface, box, checked, hovered)

    def _draw_status(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        if rect.w <= 0:
            return
        pygame.draw.rect(
            surface, self.field_bg, rect, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, self.border_color, rect,
            width=1, border_radius=self._s(4),
        )
        label = self._font_small.render(
            "Sketch Status", True, self.text_secondary
        )
        surface.blit(
            label,
            label.get_rect(
                midleft=(rect.x + self._s(10), rect.y + self._s(11))
            ),
        )
        value = self._font_text.render(
            "Fully constrained", True, self.success
        )
        surface.blit(
            value,
            value.get_rect(
                midleft=(
                    rect.x + self._s(10),
                    rect.bottom - self._s(13),
                )
            ),
        )

    def _draw_finish(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        if rect.w <= 0:
            return
        fill = self.accent_hover if self._hover_finish else self.accent
        pygame.draw.rect(surface, fill, rect, border_radius=self._s(4))
        text = self._font_text.render(
            "Finish Sketch", True, pygame.Color(255, 255, 255)
        )
        surface.blit(text, text.get_rect(center=rect.center))

    def _draw_scrollbar(
        self, surface: pygame.Surface, layout: _PaletteLayout, region: Rect
    ) -> None:
        maximum = self._max_scroll(region)
        if maximum <= 0:
            return
        body = self._body_rect(layout.panel)
        if body.h <= 0:
            return
        content = self._body_content_height()
        thumb_h = max(
            self._s(18),
            int(body.h * body.h / max(1, content)),
        )
        thumb_h = min(body.h, thumb_h)
        travel = body.h - thumb_h
        thumb_y = body.y + int(travel * self._scroll / maximum)
        thumb = pygame.Rect(
            layout.panel.right - self._s(5),
            thumb_y + self._s(2),
            self._s(3),
            max(1, thumb_h - self._s(4)),
        )
        pygame.draw.rect(
            surface, self.scrollbar_color, thumb,
            border_radius=self._s(2),
        )

    def _draw_checkbox(
        self, surface: pygame.Surface, rect: pygame.Rect,
        checked: bool, hovered: bool,
    ) -> None:
        pygame.draw.rect(
            surface, self.field_bg, rect, border_radius=self._s(3)
        )
        border = self.accent if hovered else (
            self.text_muted if checked else self.border_color
        )
        pygame.draw.rect(
            surface, border, rect, width=1, border_radius=self._s(3)
        )
        if not checked:
            return
        pad = self._s(3)
        points = [
            (rect.x + pad, rect.centery),
            (rect.centerx - self._s(1), rect.bottom - pad - self._s(1)),
            (rect.right - pad, rect.y + pad + self._s(1)),
        ]
        pygame.draw.lines(
            surface, self.text_primary, False, points,
            max(1, self._s(2)),
        )

    def _draw_line_type_symbol(
        self, surface: pygame.Surface, center: Tuple[int, int],
        line_type: str, color: pygame.Color,
    ) -> None:
        """Draw a line type symbol at center."""
        cx, cy = center
        w = self._s(18)
        thickness = max(2, self._s(2))

        if line_type == "normal":
            pygame.draw.line(
                surface, color,
                (cx - w // 2, cy), (cx + w // 2, cy), thickness,
            )
        elif line_type == "dashed":
            dash_w = w // 3
            gap = self._s(3)
            for index in range(3):
                x0 = cx - w // 2 + index * (dash_w + gap)
                pygame.draw.line(
                    surface, color, (x0, cy), (x0 + dash_w, cy), thickness,
                )
        elif line_type == "dashdot":
            pygame.draw.line(
                surface, color,
                (cx - w // 2, cy), (cx - w // 6, cy), thickness,
            )
            pygame.draw.circle(
                surface, color, (cx, cy), max(1, self._s(2))
            )
            pygame.draw.line(
                surface, color,
                (cx + w // 6, cy), (cx + w // 2, cy), thickness,
            )
        else:
            pygame.draw.line(
                surface, color,
                (cx - w // 2, cy + self._s(3)),
                (cx + w // 2, cy - self._s(3)),
                thickness,
            )
            pygame.draw.line(
                surface, color,
                (cx, cy - self._s(4)), (cx, cy + self._s(2)),
                max(1, self._s(2)),
            )
            for offset in (-self._s(6), self._s(6)):
                pygame.draw.line(
                    surface, color,
                    (cx + offset, cy - self._s(1)),
                    (cx + offset, cy + self._s(1)),
                    max(1, self._s(2)),
                )

    def _draw_look_at_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        width = self._s(18)
        height = self._s(13)
        body = pygame.Rect(
            cx - width // 2, cy - height // 2, width, height
        )
        pygame.draw.rect(
            surface, color, body, width=max(1, self._s(1)),
            border_radius=self._s(2),
        )
        pygame.draw.circle(
            surface, color, (cx + self._s(1), cy),
            max(1, self._s(3)), max(1, self._s(1)),
        )
        pygame.draw.line(
            surface, color,
            (cx - self._s(2), body.y),
            (cx + self._s(2), body.y),
            max(1, self._s(2)),
        )

    def _fit_text(
        self, font: pygame.font.Font, text: str, max_width: int
    ) -> str:
        if font.size(text)[0] <= max_width:
            return text
        ellipsis = "..."
        available = max_width - font.size(ellipsis)[0]
        if available <= 0:
            return ellipsis
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if font.size(text[:mid])[0] <= available:
                low = mid
            else:
                high = mid - 1
        return text[:low] + ellipsis
