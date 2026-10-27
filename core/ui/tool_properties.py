"""Non-modal tool-properties windows for PY3DCAD."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple, List

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
        ("normal", "Normal"),
        ("construction", "Construction"),
        ("center", "Center"),
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
        self.centerline = pygame.Color(235, 180, 90)
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
        aliases = {"dashed": "construction", "dashdot": "center"}
        line_type = aliases.get(line_type, line_type)
        valid = {key for key, _label in self.LINE_TYPES}
        self.current_line_type = line_type if line_type in valid else "normal"
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
                return SketchPaletteAction.CONSUMED
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
            elif key == "center":
                color = self.centerline
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
        elif line_type == "construction":
            dash_w = w // 3
            gap = self._s(3)
            for index in range(3):
                x0 = cx - w // 2 + index * (dash_w + gap)
                pygame.draw.line(
                    surface, color, (x0, cy), (x0 + dash_w, cy), thickness,
                )
        else:
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


class FilletWindowAction(Enum):
    """Result of passing an event to the fillet window."""

    NONE = "none"
    CONSUMED = "consumed"
    APPLY = "apply"
    CANCEL = "cancel"


class FilletWindow:
    """Small panel for entering the radius of a solid-edge fillet."""

    CUBE_SIZE = 92
    CUBE_MARGIN = 12
    CUBE_GAP = 12
    PANEL_WIDTH = 322
    PANEL_HEIGHT = 196

    def __init__(self) -> None:
        self.visible = False
        self.scale = 1.0
        self.value = "2"
        self.radius_limit: Optional[float] = None
        self.error = ""
        self.edge_label = "No edge selected"
        self.focused = False
        self._hover_apply = False
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
        self.error_color = pygame.Color(235, 100, 100)
        self.field_bg = pygame.Color(35, 37, 46)
        self.field_hover_bg = pygame.Color(52, 58, 72)
        self.button_bg = pygame.Color(44, 47, 57)
        self.button_hover_bg = pygame.Color(58, 61, 72)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_title = None
        self._font_text = None
        self._hover_apply = False
        self._hover_cancel = False

    def open(self, radius: float, edge_label: str) -> None:
        self.visible = True
        self.value = f"{radius:g}"
        self.radius_limit = None
        self.error = ""
        self.edge_label = edge_label
        self.focused = True
        self._hover_apply = False
        self._hover_cancel = False

    def close(self) -> None:
        self.visible = False
        self.focused = False
        self.radius_limit = None
        self._hover_apply = False
        self._hover_cancel = False

    def set_edge_label(self, label: str) -> None:
        self.edge_label = label

    def set_radius_limit(self, limit: Optional[float]) -> None:
        """Store the largest radius the selected edge can carry."""
        self.radius_limit = (
            float(limit) if limit is not None and limit > 1e-9 else None
        )
        if self.focused or self.radius_limit is None:
            return
        try:
            value = float(self.value)
        except ValueError:
            return
        if value > self.radius_limit:
            # Keep the visible field in step with the clamped handle.
            self.set_radius_value(self.radius_limit)

    def set_error(self, message: str) -> None:
        self.error = message

    def radius(self) -> Optional[float]:
        """Return the entered radius, or None when it is not valid."""
        try:
            value = float(self.value)
        except ValueError:
            return None
        if self.radius_limit is not None:
            value = min(value, self.radius_limit)
        return value if value > 0.0 else None

    def set_radius_value(self, value: float) -> None:
        """Update the radius from the viewport drag handle."""
        self.value = f"{max(0.01, value):.3f}".rstrip("0").rstrip(".")
        self.error = ""

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

    def field_rect(self, region: Rect) -> pygame.Rect:
        panel = self.panel_rect(region)
        width = self._s(112)
        height = self._s(28)
        return pygame.Rect(
            panel.right - self._s(16) - width,
            panel.y + self._s(76),
            width,
            height,
        )

    def apply_rect(self, region: Rect) -> pygame.Rect:
        panel = self.panel_rect(region)
        width = self._s(96)
        height = self._s(28)
        return pygame.Rect(
            panel.right - self._s(16) - width,
            panel.bottom - self._s(14) - height,
            width,
            height,
        )

    def cancel_rect(self, region: Rect) -> pygame.Rect:
        apply_rect = self.apply_rect(region)
        width = self._s(80)
        return pygame.Rect(
            apply_rect.x - self._s(8) - width,
            apply_rect.y,
            width,
            apply_rect.h,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def update_hover(self, pos: Tuple[int, int], region: Rect) -> bool:
        """Update button hover state and report whether the panel is hovered."""
        if not self.visible:
            self._hover_apply = False
            self._hover_cancel = False
            return False
        panel = self.panel_rect(region)
        if not panel.collidepoint(pos):
            self._hover_apply = False
            self._hover_cancel = False
            return False
        self._hover_apply = self.apply_rect(region).collidepoint(pos)
        self._hover_cancel = self.cancel_rect(region).collidepoint(pos)
        return True

    def handle_event(
        self, event: pygame.event.Event, region: Rect
    ) -> FilletWindowAction:
        if not self.visible:
            return FilletWindowAction.NONE

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return FilletWindowAction.CANCEL
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._submit()
            if event.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
                self.error = ""
                return FilletWindowAction.CONSUMED
            character = event.unicode
            if character and (
                character in "0123456789"
                or (character == "." and "." not in self.value)
            ):
                self.value += character
                self.error = ""
                return FilletWindowAction.CONSUMED
            return FilletWindowAction.CONSUMED

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            panel = self.panel_rect(region)
            if not panel.collidepoint(event.pos):
                self.focused = False
                return FilletWindowAction.NONE
            if self.field_rect(region).collidepoint(event.pos):
                self.focused = True
                return FilletWindowAction.CONSUMED
            if self.apply_rect(region).collidepoint(event.pos):
                return self._submit()
            if self.cancel_rect(region).collidepoint(event.pos):
                self.close()
                return FilletWindowAction.CANCEL
            self.focused = False
            return FilletWindowAction.CONSUMED

        return FilletWindowAction.NONE

    def _submit(self) -> FilletWindowAction:
        radius = self.radius()
        if radius is None:
            self.error = "Enter a radius greater than zero"
            return FilletWindowAction.CONSUMED
        if self.radius_limit is not None:
            # Show the clamped value so the field agrees with the body.
            self.set_radius_value(radius)
        self.error = ""
        return FilletWindowAction.APPLY

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
            "FILLET", True, self.text_primary
        )
        surface.blit(
            title,
            title.get_rect(
                midleft=(panel.x + self._s(30), minus_y)
            ),
        )

        edge = self._font_text.render(
            self.edge_label, True, self.text_secondary
        )
        surface.blit(
            edge,
            edge.get_rect(
                midleft=(panel.x + self._s(16), panel.y + self._s(56))
            ),
        )
        label = self._font_text.render(
            "Radius", True, self.text_secondary
        )
        field = self.field_rect(region)
        surface.blit(
            label,
            label.get_rect(midleft=(panel.x + self._s(16), field.centery)),
        )

        pygame.draw.rect(
            surface,
            self.field_hover_bg if self.focused else self.field_bg,
            field, border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.accent, field,
            width=self._s(2), border_radius=self._s(4),
        )
        value = self._font_text.render(
            self.value, True, self.text_primary
        )
        surface.blit(
            value,
            value.get_rect(
                midleft=(field.x + self._s(10), field.centery)
            ),
        )
        if self.focused and (pygame.time.get_ticks() // 500) % 2 == 0:
            cursor_x = field.x + self._s(10) + value.get_width() + self._s(2)
            pygame.draw.line(
                surface, self.text_primary,
                (cursor_x, field.y + self._s(6)),
                (cursor_x, field.bottom - self._s(6)),
                max(1, self._s(1)),
            )
        unit = self._font_text.render("mm", True, self.text_muted)
        surface.blit(
            unit,
            unit.get_rect(
                midright=(field.right - self._s(10), field.centery)
            ),
        )

        if self.error:
            message = self._font_text.render(
                self.error, True, self.error_color
            )
        else:
            message = self._font_text.render(
                "Enter to apply  ·  Esc to cancel",
                True, self.text_muted,
            )
        surface.blit(
            message,
            message.get_rect(
                midleft=(panel.x + self._s(16), panel.y + self._s(122))
            ),
        )

        apply_rect = self.apply_rect(region)
        pygame.draw.rect(
            surface,
            pygame.Color(88, 155, 255)
            if self._hover_apply else self.accent,
            apply_rect, border_radius=self._s(4),
        )
        apply_text = self._font_text.render(
            "Apply", True, pygame.Color(255, 255, 255)
        )
        surface.blit(
            apply_text,
            apply_text.get_rect(center=apply_rect.center),
        )

        cancel_rect = self.cancel_rect(region)
        pygame.draw.rect(
            surface,
            self.button_hover_bg if self._hover_cancel else self.button_bg,
            cancel_rect, border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.border_color, cancel_rect,
            width=1, border_radius=self._s(4),
        )
        cancel_text = self._font_text.render(
            "Cancel", True, self.text_primary
        )
        surface.blit(
            cancel_text,
            cancel_text.get_rect(center=cancel_rect.center),
        )


class ExtrudeWindowAction(Enum):
    """Result of passing an event to the extrude window."""

    NONE = "none"
    CONSUMED = "consumed"
    APPLY = "apply"
    CANCEL = "cancel"


@dataclass(frozen=True)
class _PanelMetrics:
    """Resolved vertical layout for the extrude panel in one viewport."""

    panel: pygame.Rect
    rows_top: int
    row_height: int
    field_height: int
    status_y: int
    hint_y: Optional[int]
    buttons_y: int


class ExtrudeWindow:
    """Property panel for a new extrusion and its boolean operation."""

    CUBE_SIZE = 92
    CUBE_MARGIN = 12
    CUBE_GAP = 12
    PANEL_WIDTH = 344
    TITLE_HEIGHT = 34
    ROW_HEIGHT = 32
    HINT_MIN_ROW = 28
    MIN_ROW_HEIGHT = 22
    FIELD_INSET = 6
    FIELD_WIDTH = 176
    MENU_ROW_HEIGHT = 26

    START_ITEMS = (("profile_plane", "Profile Plane"),)
    DIRECTION_ITEMS = (("one_side", "One Side"), ("symmetric", "Symmetric"))
    EXTENT_ITEMS = (("distance", "Distance"),)
    OPERATION_ITEMS = (
        ("new_body", "New Body"),
        ("join", "Join"),
        ("cut", "Cut"),
        ("intersect", "Intersect"),
    )
    ROW_KEYS = (
        ("profiles", 0),
        ("thin", 1),
        ("start", 2),
        ("direction", 3),
        ("reverse", 4),
        ("extent", 5),
        ("distance", 6),
        ("taper", 7),
        ("operation", 8),
    )

    def __init__(self) -> None:
        self.visible = False
        self.scale = 1.0
        self.distance = "20"
        self.taper = "0"
        self.start = "profile_plane"
        self.direction = "one_side"
        self.extent = "distance"
        self.operation = "new_body"
        self.thin = False
        self.reverse = False
        self.profile_count = 1
        self.error = ""
        self.focused: Optional[str] = "distance"
        self._replace_text = True
        self._open_menu: Optional[str] = None
        self._menu_hover = -1
        self._hover_dropdown: Optional[str] = None
        self._hover_apply = False
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
        self.error_color = pygame.Color(235, 100, 100)
        self.field_bg = pygame.Color(35, 37, 46)
        self.field_hover_bg = pygame.Color(52, 58, 72)
        self.button_bg = pygame.Color(44, 47, 57)
        self.button_hover_bg = pygame.Color(58, 61, 72)
        self.selection_bg = pygame.Color(45, 75, 125)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_title = None
        self._font_text = None
        self._open_menu = None
        self._hover_apply = False
        self._hover_cancel = False

    def open(self, profile_count: int) -> None:
        self.visible = True
        self.profile_count = max(1, int(profile_count))
        # Never reopen with an emptied field that would block Apply.
        if self.distance_value() is None:
            self.distance = "20"
        if self.taper_value() is None:
            self.taper = "0"
        self.error = ""
        self.focused = "distance"
        self._replace_text = True
        self._open_menu = None
        self._menu_hover = -1
        self._hover_dropdown = None
        self._hover_apply = False
        self._hover_cancel = False

    def close(self) -> None:
        self.visible = False
        self.error = ""
        self._open_menu = None
        self._menu_hover = -1
        self._hover_dropdown = None
        self.focused = None
        self._hover_apply = False
        self._hover_cancel = False

    def set_profile_count(self, count: int) -> None:
        self.profile_count = max(0, int(count))

    def set_error(self, message: str) -> None:
        self.error = message

    def distance_value(self) -> Optional[float]:
        """Return the entered distance, or None when it is not valid."""
        try:
            value = float(self.distance)
        except ValueError:
            return None
        return value if value > 0.0 else None

    def set_distance_value(self, value: float) -> None:
        """Update the distance from a viewport drag handle."""
        self.distance = f"{max(0.05, value):.2f}".rstrip("0").rstrip(".")
        self._replace_text = False
        self.error = ""

    def taper_value(self) -> Optional[float]:
        """Return the entered taper angle in degrees, or None when invalid."""
        try:
            value = float(self.taper)
        except ValueError:
            return None
        return value if -89.0 < value < 89.0 else None

    def is_symmetric(self) -> bool:
        return self.direction == "symmetric"

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _init_fonts(self) -> None:
        if self._font_title is not None:
            return
        self._font_title = pygame.font.SysFont(
            "Segoe UI", self._s(12), bold=True
        )
        self._font_text = pygame.font.SysFont("Segoe UI", self._s(12))

    def _row_size(
        self, available: int, minimum: Optional[int] = None
    ) -> Tuple[int, int, bool]:
        """Choose a row height for the space below the orientation cube.

        Short viewports drop the keyboard hint line first, then compress the
        rows, so the operation field and the buttons never overlap.
        """
        rows = len(self.ROW_KEYS)
        maximum = self._s(self.ROW_HEIGHT)
        hinted = (available - self._s(138)) // rows
        if hinted >= self._s(self.HINT_MIN_ROW):
            row = min(maximum, hinted)
            return row, row - self._s(self.FIELD_INSET), True
        floor = self._s(self.MIN_ROW_HEIGHT) if minimum is None else minimum
        row = (available - self._s(118)) // rows
        row = max(floor, min(maximum, row))
        field = max(1, min(row, row - self._s(self.FIELD_INSET)))
        return row, field, False

    def _stack(
        self, row: int, hinted: bool
    ) -> Tuple[int, int, Optional[int], int, int]:
        """Return row, status, hint and button offsets and total height."""
        rows_top = self._s(self.TITLE_HEIGHT) + self._s(10)
        status_y = rows_top + row * len(self.ROW_KEYS) + self._s(15)
        hint_y = status_y + self._s(20) if hinted else None
        buttons_y = (
            hint_y if hint_y is not None else status_y
        ) + self._s(17)
        return rows_top, status_y, hint_y, buttons_y, buttons_y + self._s(42)

    def _metrics(self, region: Rect) -> _PanelMetrics:
        """Lay out rows, status and buttons so they always stay separate."""
        margin = self._s(self.CUBE_MARGIN)
        width = min(self._s(self.PANEL_WIDTH), max(1, region.w - margin * 2))
        natural_top = (
            region.y + margin + self._s(self.CUBE_SIZE)
            + self._s(self.CUBE_GAP)
        )
        bottom_limit = region.bottom - margin
        available = max(1, bottom_limit - natural_top)
        row, field, hinted = self._row_size(available)
        offsets = self._stack(row, hinted)
        rows_top, status_y, hint_y, buttons_y, height = offsets
        top = natural_top
        if height > available:
            # A very short viewport also overlaps the orientation cube rather
            # than letting the buttons spill into the timeline.
            hard_available = region.h - margin * 2
            row, field, hinted = self._row_size(
                hard_available, minimum=self._s(9)
            )
            offsets = self._stack(row, hinted)
            rows_top, status_y, hint_y, buttons_y, height = offsets
            top = region.y + margin
            if height > hard_available:
                top = max(region.y + margin, bottom_limit - height)
        panel = pygame.Rect(
            region.right - margin - width, top, width, height
        )
        return _PanelMetrics(
            panel,
            panel.y + rows_top,
            row,
            field,
            panel.y + status_y,
            panel.y + hint_y if hint_y is not None else None,
            panel.y + buttons_y,
        )

    def panel_rect(self, region: Rect) -> pygame.Rect:
        return self._metrics(region).panel

    def field_rect(self, region: Rect, index: int) -> pygame.Rect:
        metrics = self._metrics(region)
        top = metrics.rows_top + index * metrics.row_height
        top += (metrics.row_height - metrics.field_height) // 2
        return pygame.Rect(
            metrics.panel.right - self._s(16) - self._s(self.FIELD_WIDTH),
            top,
            self._s(self.FIELD_WIDTH),
            metrics.field_height,
        )

    def apply_rect(self, region: Rect) -> pygame.Rect:
        metrics = self._metrics(region)
        width = self._s(96)
        height = self._s(28)
        return pygame.Rect(
            metrics.panel.right - self._s(16) - width,
            metrics.buttons_y,
            width,
            height,
        )

    def cancel_rect(self, region: Rect) -> pygame.Rect:
        apply_rect = self.apply_rect(region)
        width = self._s(80)
        return pygame.Rect(
            apply_rect.x - self._s(8) - width,
            apply_rect.y,
            width,
            apply_rect.h,
        )

    def menu_rect(self, region: Rect, key: str) -> pygame.Rect:
        index = dict(self.ROW_KEYS).get(key)
        items = self._menu_items(key)
        if index is None or not items:
            return pygame.Rect(0, 0, 0, 0)
        field = self.field_rect(region, index)
        panel = self.panel_rect(region)
        metrics = self._metrics(region)
        height = self._s(self.MENU_ROW_HEIGHT) * len(items)
        top = field.bottom + self._s(2)
        if top + height > panel.bottom - self._s(6):
            # Open upwards over the rows, matching their boundaries so no
            # label is drawn half-hidden behind the list.
            bottom = field.y - self._s(2)
            top = bottom - height
            if self._menu_edge_cuts_field(top, region, index):
                top = self._snap_menu(top, metrics, upward=True)
            return pygame.Rect(field.x, top, field.w, bottom - top)
        bottom = top + height
        if self._menu_edge_cuts_field(bottom, region, index):
            bottom = self._snap_menu(bottom, metrics, upward=False)
        return pygame.Rect(field.x, top, field.w, bottom - top)

    def _menu_edge_cuts_field(
        self, y: int, region: Rect, skip: int
    ) -> bool:
        """Return whether a menu edge would slice through a visible field."""
        for index in range(len(self.ROW_KEYS)):
            if index == skip:
                continue
            field = self.field_rect(region, index)
            if field.top < y < field.bottom:
                return True
        return False

    def _snap_menu(
        self, y: int, metrics: _PanelMetrics, upward: bool
    ) -> int:
        """Move a menu edge to the nearest row boundary."""
        row = max(1, metrics.row_height)
        offset = y - metrics.rows_top
        remainder = offset % row
        if not remainder:
            return y
        return y - remainder if upward else y + (row - remainder)

    def _menu_items(self, key: str) -> Sequence[Tuple[str, str]]:
        return {
            "start": self.START_ITEMS,
            "direction": self.DIRECTION_ITEMS,
            "extent": self.EXTENT_ITEMS,
            "operation": self.OPERATION_ITEMS,
        }.get(key, ())

    def _current_value(self, key: str) -> str:
        return str(getattr(self, key, ""))

    def _set_value(self, key: str, value: str) -> None:
        if key in ("start", "direction", "extent", "operation"):
            setattr(self, key, value)
        self.error = ""

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def update_hover(self, pos: Tuple[int, int], region: Rect) -> bool:
        """Update hover state and report whether the panel or menu is hovered."""
        if not self.visible:
            self._hover_apply = False
            self._hover_cancel = False
            self._hover_dropdown = None
            return False
        panel = self.panel_rect(region)
        if self._open_menu is not None:
            self._menu_hover = self._menu_index_at(pos, region)
            if self._menu_hover >= 0:
                self._hover_dropdown = self._open_menu
                return True
        self._menu_hover = -1
        self._hover_apply = self.apply_rect(region).collidepoint(pos)
        self._hover_cancel = self.cancel_rect(region).collidepoint(pos)
        self._hover_dropdown = None
        for key, index in self.ROW_KEYS:
            if not self._menu_items(key):
                continue
            if self.field_rect(region, index).collidepoint(pos):
                self._hover_dropdown = key
                break
        return panel.collidepoint(pos)

    def handle_event(
        self, event: pygame.event.Event, region: Rect
    ) -> ExtrudeWindowAction:
        if not self.visible:
            return ExtrudeWindowAction.NONE
        if self._open_menu is not None:
            return self._handle_menu_event(event, region)
        if event.type == pygame.KEYDOWN:
            return self._handle_key(event)
        if event.type == pygame.MOUSEMOTION:
            return (
                ExtrudeWindowAction.CONSUMED
                if self.update_hover(event.pos, region) else
                ExtrudeWindowAction.NONE
            )
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_click(event.pos, region)
        return ExtrudeWindowAction.NONE

    def _handle_menu_event(
        self, event: pygame.event.Event, region: Rect
    ) -> ExtrudeWindowAction:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._open_menu = None
                self._menu_hover = -1
            return ExtrudeWindowAction.CONSUMED
        if event.type == pygame.MOUSEMOTION:
            self._menu_hover = self._menu_index_at(event.pos, region)
            return ExtrudeWindowAction.CONSUMED
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            index = self._menu_index_at(event.pos, region)
            if index >= 0 and self._open_menu is not None:
                items = self._menu_items(self._open_menu)
                self._set_value(self._open_menu, items[index][0])
            self._open_menu = None
            self._menu_hover = -1
            return ExtrudeWindowAction.CONSUMED
        return ExtrudeWindowAction.CONSUMED

    def _menu_index_at(self, pos: Tuple[int, int], region: Rect) -> int:
        if self._open_menu is None:
            return -1
        items = self._menu_items(self._open_menu)
        rect = self.menu_rect(region, self._open_menu)
        if not rect.collidepoint(pos):
            return -1
        index = (pos[1] - rect.y) // max(1, self._s(self.MENU_ROW_HEIGHT))
        return index if 0 <= index < len(items) else -1

    def _handle_key(self, event: pygame.event.Event) -> ExtrudeWindowAction:
        if event.key == pygame.K_ESCAPE:
            self.close()
            return ExtrudeWindowAction.CANCEL
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._submit()
        if event.key == pygame.K_TAB:
            self.focused = (
                "taper" if self.focused == "distance" else "distance"
            )
            self._replace_text = True
            self.error = ""
            return ExtrudeWindowAction.CONSUMED
        if event.key == pygame.K_BACKSPACE:
            if self.focused is not None:
                setattr(self, self.focused, getattr(self, self.focused)[:-1])
                self._replace_text = False
                self.error = ""
            return ExtrudeWindowAction.CONSUMED
        character = event.unicode
        if character and self.focused is not None:
            current = "" if self._replace_text else getattr(self, self.focused)
            if self._accept_character(character, current):
                setattr(self, self.focused, current + character)
                self._replace_text = False
                self.error = ""
        return ExtrudeWindowAction.CONSUMED

    def _accept_character(self, character: str, current: str) -> bool:
        if character.isdigit():
            return True
        if character == "-":
            return self.focused == "taper" and not current
        return character == "." and "." not in current

    def _handle_click(
        self, pos: Tuple[int, int], region: Rect
    ) -> ExtrudeWindowAction:
        panel = self.panel_rect(region)
        if not panel.collidepoint(pos):
            self.focused = None
            return ExtrudeWindowAction.NONE
        if self.apply_rect(region).collidepoint(pos):
            return self._submit()
        if self.cancel_rect(region).collidepoint(pos):
            self.close()
            return ExtrudeWindowAction.CANCEL
        for key, index in self.ROW_KEYS:
            if not self.field_rect(region, index).collidepoint(pos):
                continue
            if key in ("distance", "taper"):
                self.focused = key
                self._replace_text = True
                self.error = ""
            elif key == "thin":
                self.thin = not self.thin
                self.error = ""
            elif key == "reverse":
                self.reverse = not self.reverse
                self.error = ""
            elif self._menu_items(key):
                self._open_menu = key
                self._menu_hover = -1
                self.focused = None
            return ExtrudeWindowAction.CONSUMED
        self.focused = None
        return ExtrudeWindowAction.CONSUMED

    def _submit(self) -> ExtrudeWindowAction:
        if self.distance_value() is None:
            self.error = "Enter a distance greater than zero"
            return ExtrudeWindowAction.CONSUMED
        if self.taper_value() is None:
            self.error = "Taper must be between -89 and 89 degrees"
            return ExtrudeWindowAction.CONSUMED
        if self.thin:
            self.error = "Thin feature is not supported yet"
            return ExtrudeWindowAction.CONSUMED
        if abs(self.taper_value() or 0.0) > 1e-9:
            self.error = "Taper is not supported yet"
            return ExtrudeWindowAction.CONSUMED
        self.error = ""
        return ExtrudeWindowAction.APPLY

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, region: Rect) -> None:
        if not self.visible:
            return
        self._init_fonts()
        panel = self.panel_rect(region)
        pygame.draw.rect(
            surface, self.panel_bg, panel, border_radius=self._s(6)
        )
        pygame.draw.rect(
            surface, self.title_bg,
            (panel.x, panel.y, panel.w, self._s(self.TITLE_HEIGHT)),
            border_top_left_radius=self._s(6),
            border_top_right_radius=self._s(6),
        )
        pygame.draw.rect(
            surface, self.border_color, panel,
            width=1, border_radius=self._s(6),
        )
        self._draw_title(surface, panel)
        self._draw_rows(surface, region)
        self._draw_status(surface, region)
        self._draw_buttons(surface, region)
        if self._open_menu is not None:
            self._draw_menu(surface, region, self._open_menu)

    def _draw_title(
        self, surface: pygame.Surface, panel: pygame.Rect
    ) -> None:
        y = panel.y + self._s(self.TITLE_HEIGHT) // 2
        pygame.draw.line(
            surface, self.text_primary,
            (panel.x + self._s(14), y), (panel.x + self._s(22), y),
            self._s(2),
        )
        title = self._font_title.render("EXTRUDE", True, self.text_primary)
        surface.blit(
            title, title.get_rect(midleft=(panel.x + self._s(30), y))
        )
        pygame.draw.line(
            surface, self.border_color,
            (panel.x, panel.y + self._s(self.TITLE_HEIGHT)),
            (panel.right, panel.y + self._s(self.TITLE_HEIGHT)),
        )

    def _draw_rows(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        panel = self.panel_rect(region)
        labels = {
            "profiles": "Profiles",
            "thin": "Thin Feature",
            "start": "Start",
            "direction": "Direction",
            "reverse": "Reverse",
            "extent": "Extent Type",
            "distance": "Distance",
            "taper": "Taper Angle",
            "operation": "Operation",
        }
        for key, index in self.ROW_KEYS:
            field = self.field_rect(region, index)
            label = self._font_text.render(
                labels[key], True, self.text_secondary
            )
            surface.blit(
                label,
                label.get_rect(
                    midleft=(panel.x + self._s(16), field.centery)
                ),
            )
            if key == "profiles":
                self._draw_chip(surface, field)
            elif key in ("thin", "reverse"):
                checked = self.thin if key == "thin" else self.reverse
                box = pygame.Rect(
                    field.right - self._s(18),
                    field.centery - self._s(9),
                    self._s(18), self._s(18),
                )
                self._draw_checkbox(surface, box, checked)
            elif key in ("distance", "taper"):
                self._draw_number_field(surface, field, key)
            else:
                self._draw_dropdown(surface, field, key)

    def _draw_chip(
        self, surface: pygame.Surface, field: pygame.Rect
    ) -> None:
        pygame.draw.rect(
            surface, self.field_bg, field, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, self.border_color, field,
            width=1, border_radius=self._s(4),
        )
        count = self.profile_count
        text = f"{count} profile" + ("" if count == 1 else "s")
        label = self._font_text.render(text, True, self.text_secondary)
        surface.blit(
            label, label.get_rect(midleft=(field.x + self._s(10), field.centery))
        )

    def _draw_checkbox(
        self, surface: pygame.Surface, box: pygame.Rect, checked: bool
    ) -> None:
        pygame.draw.rect(
            surface, self.field_bg, box, border_radius=self._s(3)
        )
        pygame.draw.rect(
            surface, self.accent if checked else self.border_color, box,
            width=self._s(2) if checked else 1,
            border_radius=self._s(3),
        )
        if checked:
            pygame.draw.lines(
                surface, self.text_primary, False,
                [
                    (box.x + self._s(4), box.centery),
                    (box.x + self._s(8), box.bottom - self._s(5)),
                    (box.right - self._s(4), box.y + self._s(5)),
                ],
                max(1, self._s(2)),
            )

    def _draw_dropdown(
        self, surface: pygame.Surface, field: pygame.Rect, key: str
    ) -> None:
        hovered = self._hover_dropdown == key or self._open_menu == key
        pygame.draw.rect(
            surface,
            self.field_hover_bg if hovered else self.field_bg,
            field, border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.accent if self._open_menu == key else self.border_color,
            field, width=1, border_radius=self._s(4),
        )
        label = self._menu_label(key, self._current_value(key))
        text = self._font_text.render(label, True, self.text_primary)
        surface.blit(
            text, text.get_rect(midleft=(field.x + self._s(10), field.centery))
        )
        cx = field.right - self._s(12)
        cy = field.centery
        pygame.draw.polygon(
            surface, self.text_muted,
            [(cx - self._s(4), cy - self._s(2)),
             (cx + self._s(4), cy - self._s(2)),
             (cx, cy + self._s(3))],
        )

    def _menu_label(self, key: str, value: str) -> str:
        for item_value, label in self._menu_items(key):
            if item_value == value:
                return label
        return value

    def _draw_number_field(
        self, surface: pygame.Surface, field: pygame.Rect, key: str
    ) -> None:
        focused = self.focused == key
        pygame.draw.rect(
            surface, self.field_hover_bg if focused else self.field_bg,
            field, border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.accent if focused else self.border_color,
            field, width=self._s(2) if focused else 1,
            border_radius=self._s(4),
        )
        value = self._font_text.render(
            getattr(self, key), True, self.text_primary
        )
        value_rect = value.get_rect(
            midleft=(field.x + self._s(10), field.centery)
        )
        replacing = focused and self._replace_text and bool(getattr(self, key))
        if replacing:
            pygame.draw.rect(
                surface, self.selection_bg,
                value_rect.inflate(self._s(4), self._s(2)),
                border_radius=self._s(2),
            )
        surface.blit(value, value_rect)
        unit = "mm" if key == "distance" else "°"
        unit_text = self._font_text.render(unit, True, self.text_muted)
        surface.blit(
            unit_text,
            unit_text.get_rect(midright=(field.right - self._s(10), field.centery)),
        )
        if (
            focused and not replacing
            and (pygame.time.get_ticks() // 500) % 2 == 0
        ):
            cursor_x = field.x + self._s(10) + value.get_width() + self._s(2)
            pygame.draw.line(
                surface, self.text_primary,
                (cursor_x, field.y + self._s(6)),
                (cursor_x, field.bottom - self._s(6)),
                max(1, self._s(1)),
            )

    def _draw_status(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        metrics = self._metrics(region)
        panel = metrics.panel
        if self.operation == "new_body":
            message = "Creates a new independent body"
        else:
            message = "Target: the body this extrusion touches"
        color = self.text_muted
        if self.error:
            message = self.error
            color = self.error_color
        text = self._font_text.render(message, True, color)
        surface.blit(
            text,
            text.get_rect(midleft=(panel.x + self._s(16), metrics.status_y)),
        )
        if metrics.hint_y is None:
            return
        hint = self._font_text.render(
            "Enter to apply  ·  Esc to cancel", True, self.text_muted
        )
        surface.blit(
            hint,
            hint.get_rect(midleft=(panel.x + self._s(16), metrics.hint_y)),
        )

    def _draw_buttons(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        apply_rect = self.apply_rect(region)
        pygame.draw.rect(
            surface,
            pygame.Color(88, 155, 255)
            if self._hover_apply else self.accent,
            apply_rect, border_radius=self._s(4),
        )
        apply_text = self._font_text.render(
            "Apply", True, pygame.Color(255, 255, 255)
        )
        surface.blit(
            apply_text, apply_text.get_rect(center=apply_rect.center)
        )
        cancel_rect = self.cancel_rect(region)
        pygame.draw.rect(
            surface,
            self.button_hover_bg if self._hover_cancel else self.button_bg,
            cancel_rect, border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.border_color, cancel_rect,
            width=1, border_radius=self._s(4),
        )
        cancel_text = self._font_text.render(
            "Cancel", True, self.text_primary
        )
        surface.blit(
            cancel_text, cancel_text.get_rect(center=cancel_rect.center)
        )

    def _draw_menu(
        self, surface: pygame.Surface, region: Rect, key: str
    ) -> None:
        rect = self.menu_rect(region, key)
        items = self._menu_items(key)
        if rect.w <= 0 or not items:
            return
        pygame.draw.rect(
            surface, self.panel_bg, rect, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, self.border_color, rect,
            width=1, border_radius=self._s(4),
        )
        row_height = self._s(self.MENU_ROW_HEIGHT)
        current = self._current_value(key)
        for index, (value, label) in enumerate(items):
            row = pygame.Rect(
                rect.x + self._s(2),
                rect.y + index * row_height + self._s(2),
                rect.w - self._s(4),
                row_height - self._s(3),
            )
            if index == self._menu_hover:
                pygame.draw.rect(
                    surface, self.field_hover_bg, row,
                    border_radius=self._s(3),
                )
            color = (
                self.accent if value == current
                else (self.text_primary if index == self._menu_hover
                      else self.text_secondary)
            )
            text = self._font_text.render(label, True, color)
            surface.blit(
                text,
                text.get_rect(
                    midleft=(row.x + self._s(10), row.centery)
                ),
            )
