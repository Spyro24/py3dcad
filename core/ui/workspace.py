"""Document workspace drawing for PY3DCAD."""

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import pygame

from ..document import Document
from ..sketch import Point
from .layout import Rect, UILayout
from .tool_properties import ToolPropertiesWindow, ToolWindowAction, SketchPaletteWindow, SketchPaletteAction
from .viewport import Viewport


@dataclass
class HistoryEntry:
    """One action shown in the timeline."""

    kind: str
    label: str


class Workspace:
    """Draws the document workspace and routes editing interactions."""

    TOOL_LABELS = {"sketch": "Sketch", "extrude": "Extrude"}
    TOOL_SHORTCUTS = {"sketch": "S", "extrude": "E"}
    MODES = ("SOLID", "SURFACE", "MESH", "SHEET METAL", "PLASTIC", "UTILITIES")
    ACTIVE_MODE = "SOLID"
    ORIGIN_PLANES = ("XY Plane", "YZ Plane", "ZX Plane")
    ORIGIN_PLANE_KEYS = ("XY", "YZ", "ZX")

    def __init__(
        self,
        on_new_sketch: Callable[[], None],
        on_extrude: Callable[[], None],
        on_add_point: Callable[[Point], None],
        on_select_sketch: Callable[[int], None],
        on_history_jump: Callable[[int], None],
        on_history_delete: Callable[[int], None],
        on_history_play: Callable[[], None],
        on_settings: Optional[Callable[[], None]] = None,
    ) -> None:
        self.on_new_sketch = on_new_sketch
        self.on_extrude = on_extrude
        self.on_add_point = on_add_point
        self.on_select_sketch = on_select_sketch
        self.on_history_jump = on_history_jump
        self.on_history_delete = on_history_delete
        self.on_history_play = on_history_play
        self.on_settings = on_settings

        self.scale = 1.0
        self.viewport = Viewport()
        self._hover_tool: Optional[str] = None
        self._hover_sketch: Optional[int] = None
        self._hover_plane: Optional[int] = None
        self._hover_control: Optional[str] = None
        self._hover_action: Optional[int] = None
        self._hover_settings = False
        self._hover_origin = False
        self._hover_origin_eye = False
        self._hover_sketches_folder = False
        self._selected_action: Optional[int] = None
        self._origin_expanded = True
        self._origin_visible = True
        self._sketches_expanded = True
        self.create_sketch_window = ToolPropertiesWindow(
            title="CREATE SKETCH",
            property_label="Plane",
        )
        self.sketch_palette_window = SketchPaletteWindow()
        self._history_document: Optional[int] = None
        self._mouse_pos: Tuple[int, int] = (0, 0)

        self._font_label: Optional[pygame.font.Font] = None
        self._font_small: Optional[pygame.font.Font] = None
        self._font_tab: Optional[pygame.font.Font] = None
        self._font_caption: Optional[pygame.font.Font] = None

        self.panel_bg = pygame.Color(31, 31, 37)
        self.header_bg = pygame.Color(38, 38, 45)
        self.border_color = pygame.Color(50, 50, 58)
        self.text_primary = pygame.Color(225, 225, 230)
        self.text_secondary = pygame.Color(202, 205, 212)
        self.text_muted = pygame.Color(125, 125, 136)
        self.accent = pygame.Color(59, 130, 246)
        self.tree_selection = pygame.Color(44, 94, 154)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self.viewport.set_scale(scale)
        self._hover_tool = None
        self._hover_sketch = None
        self._hover_plane = None
        self._hover_control = None
        self._hover_action = None
        self._hover_settings = False
        self._hover_origin = False
        self._hover_origin_eye = False
        self._hover_sketches_folder = False
        self.create_sketch_window.set_scale(scale)
        self.sketch_palette_window.set_scale(scale)
        self._font_label = None
        self._font_small = None
        self._font_tab = None
        self._font_caption = None

    def set_orientation_cube_visible(self, visible: bool) -> None:
        self.viewport.show_orientation_cube = bool(visible)

    def set_origin_visible(self, visible: bool) -> None:
        """Show or hide the origin planes, axes and marker."""
        self._origin_visible = bool(visible)
        self.viewport.set_origin_visible(self._origin_visible)

    def open_create_sketch_dialog(self) -> None:
        """Ask the user to choose a plane before creating a sketch."""
        self.create_sketch_window.open()

    def close_create_sketch_dialog(self) -> None:
        self.create_sketch_window.close()

    def _finish_create_sketch(
        self,
        document: Document,
        plane: Optional[str] = None,
        face_ref: Optional[Tuple[int, int]] = None,
    ) -> None:
        """Use the chosen plane or face and create the sketch immediately."""
        if face_ref is not None:
            document.selected_face = face_ref
            document.selected_plane = None
        else:
            document.selected_plane = plane
            document.selected_face = None
        document.active_sketch_id = None
        self.close_create_sketch_dialog()
        self.on_new_sketch()

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _init_fonts(self) -> None:
        if self._font_label is not None:
            return
        self._font_label = pygame.font.SysFont("Segoe UI", self._s(13), bold=True)
        self._font_small = pygame.font.SysFont("Segoe UI", self._s(12))
        self._font_tab = pygame.font.SysFont("Segoe UI", self._s(12), bold=True)
        self._font_caption = pygame.font.SysFont("Segoe UI", self._s(10), bold=True)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(
        self,
        surface: pygame.Surface,
        layout: UILayout,
        document: Document,
        history: List[HistoryEntry],
        full_history: List[HistoryEntry],
        position: int,
        playing: bool,
    ) -> None:
        self._init_fonts()
        self._sync_history_document(document)
        self._draw_toolbar(surface, layout.toolbar, document)
        self._draw_tree(surface, layout.document_tree, document)
        self.viewport.draw(surface, layout.viewport, document)
        if layout.command_bar.w > 0:
            self._draw_command_bar(
                surface, layout.command_bar, position, len(history)
            )
        self._draw_timeline(
            surface, layout.timeline, history, full_history, position, playing
        )
        active_sketch = document.sketch(document.active_sketch_id)
        if active_sketch is not None:
            self.sketch_palette_window.draw(surface, layout.viewport)
        else:
            self.create_sketch_window.draw(surface, layout.viewport)

    def _sync_history_document(self, document: Document) -> None:
        if document.id != self._history_document:
            self._history_document = document.id
            self._selected_action = None
            self._hover_action = None
            self._hover_control = None
            self._hover_sketches_folder = False
            self._sketches_expanded = True
            self.close_create_sketch_dialog()

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _workspace_rect(self, region: Rect) -> pygame.Rect:
        return pygame.Rect(
            region.x + self._s(8),
            region.y + self._s(8),
            self._s(152),
            region.h - self._s(16),
        )

    def _content_x(self, region: Rect) -> int:
        return self._workspace_rect(region).right + self._s(20)

    def _settings_rect(self, region: Rect) -> pygame.Rect:
        size = self._s(28)
        return pygame.Rect(
            region.right - self._s(10) - size,
            region.y + self._s(10),
            size,
            size,
        )

    def _mode_rects(
        self, region: Rect
    ) -> List[Tuple[str, pygame.Rect]]:
        self._init_fonts()
        start = self._content_x(region)
        right_limit = self._settings_rect(region).left - self._s(8)
        available = right_limit - start
        label_widths = [self._font_tab.size(mode)[0] for mode in self.MODES]
        padding = self._s(20)
        gap = self._s(6)
        for candidate_padding, candidate_gap in (
            (20, 6), (16, 4), (12, 2), (8, 1),
        ):
            padding = self._s(candidate_padding)
            gap = self._s(candidate_gap)
            total = sum(
                width + padding for width in label_widths
            ) + gap * (len(label_widths) - 1)
            if total <= available:
                break

        x = start
        y = region.y + self._s(10)
        height = self._s(24)
        tabs: List[Tuple[str, pygame.Rect]] = []
        for mode, label_width in zip(self.MODES, label_widths):
            width = label_width + padding
            rect = pygame.Rect(x, y, width, height)
            if rect.right > right_limit:
                break
            tabs.append((mode, rect))
            x += width + gap
        return tabs

    def _toolbar_buttons(
        self, region: Rect, document: Document
    ) -> List[Tuple[str, pygame.Rect, bool]]:
        sketch = document.sketch(document.active_sketch_id)
        extrude_ready = sketch is not None and len(sketch.points) >= 3
        states = (
            ("sketch", True),
            ("extrude", extrude_ready),
        )
        buttons: List[Tuple[str, pygame.Rect, bool]] = []
        x = self._content_x(region)
        y = region.y + self._s(42)
        width = self._s(40)
        height = self._s(38)
        for action, enabled in states:
            buttons.append((
                action, pygame.Rect(x, y, width, height), enabled,
            ))
            x += width + self._s(6)
        return buttons

    def _draw_toolbar(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        pygame.draw.rect(surface, self.panel_bg, region.rect)
        pygame.draw.line(
            surface, self.border_color,
            (region.x, region.bottom - 1), (region.right, region.bottom - 1),
        )
        self._draw_workspace(surface, region)
        workspace = self._workspace_rect(region)
        divider_x = workspace.right + self._s(10)
        pygame.draw.line(
            surface, self.border_color,
            (divider_x, region.y + self._s(12)),
            (divider_x, region.bottom - self._s(12)),
        )
        self._draw_modes(surface, region)
        self._draw_action_group(surface, region, document)
        self._draw_settings_button(surface, region)
        self._draw_tool_tooltip(surface, region)
        self._draw_settings_tooltip(surface, region)

    def _draw_workspace(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        rect = self._workspace_rect(region)
        pygame.draw.rect(
            surface, self.header_bg, rect, border_radius=self._s(6)
        )
        pygame.draw.rect(
            surface, self.border_color, rect, width=1,
            border_radius=self._s(6),
        )
        icon_size = self._s(34)
        icon_rect = pygame.Rect(
            rect.x + self._s(12),
            rect.centery - icon_size // 2,
            icon_size,
            icon_size,
        )
        self._draw_workspace_icon(surface, icon_rect)

        text_x = icon_rect.right + self._s(10)
        design = self._font_label.render("DESIGN", True, self.text_primary)
        design_y = rect.centery - self._s(11)
        surface.blit(
            design, design.get_rect(midleft=(text_x, design_y))
        )
        caret_x = text_x + design.get_width() + self._s(6)
        pygame.draw.polygon(surface, self.text_muted, [
            (caret_x, design_y - self._s(2)),
            (caret_x + self._s(7), design_y - self._s(2)),
            (caret_x + self._s(3), design_y + self._s(3)),
        ])
        sublabel = self._font_small.render(
            "workspace", True, self.text_muted
        )
        surface.blit(
            sublabel, sublabel.get_rect(
                midleft=(text_x, rect.centery + self._s(9))
            ),
        )

    def _draw_workspace_icon(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        pygame.draw.rect(
            surface, pygame.Color(238, 238, 244), rect,
            border_radius=self._s(5),
        )
        cx, cy = rect.center
        top = (cx, cy - self._s(7))
        left = (cx - self._s(5), cy + self._s(7))
        right = (cx + self._s(5), cy + self._s(7))
        pygame.draw.lines(
            surface, self.accent, False, [left, top, right], self._s(2)
        )
        pygame.draw.circle(surface, self.accent, top, self._s(2))

    def _draw_modes(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        for mode, rect in self._mode_rects(region):
            active = mode == self.ACTIVE_MODE
            color = self.text_primary if active else self.text_muted
            label = self._font_tab.render(mode, True, color)
            surface.blit(label, label.get_rect(
                center=(rect.centerx, rect.centery - self._s(1))
            ))
            if active:
                half = label.get_width() // 2 + self._s(2)
                y = rect.bottom - self._s(2)
                pygame.draw.line(
                    surface, self.text_primary,
                    (rect.centerx - half, y),
                    (rect.centerx + half, y),
                    self._s(2),
                )

    def _draw_action_group(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        buttons = self._toolbar_buttons(region, document)
        for action, rect, enabled in buttons:
            hovered = enabled and action == self._hover_tool
            if hovered:
                pygame.draw.rect(
                    surface, self.header_bg, rect,
                    border_radius=self._s(5),
                )
                pygame.draw.rect(
                    surface, self.border_color, rect, width=1,
                    border_radius=self._s(5),
                )
            color = (
                self._kind_color(action) if enabled
                else pygame.Color(82, 82, 92)
            )
            self._draw_action_icon(surface, rect, action, color)

        if not buttons:
            return
        left = buttons[0][1].left
        right = buttons[-1][1].right
        center_x = (left + right) // 2
        label = self._font_caption.render("CREATE", True, self.text_primary)
        label_y = region.bottom - self._s(15)
        label_width = label.get_width() + self._s(9)
        label_rect = label.get_rect(
            midleft=(center_x - label_width // 2, label_y)
        )
        surface.blit(label, label_rect)
        caret_x = label_rect.right + self._s(3)
        pygame.draw.polygon(surface, self.text_muted, [
            (caret_x, label_y - self._s(1)),
            (caret_x + self._s(6), label_y - self._s(1)),
            (caret_x + self._s(3), label_y + self._s(3)),
        ])
        pygame.draw.line(
            surface, self.border_color,
            (right + self._s(14), buttons[0][1].top),
            (right + self._s(14), region.bottom - self._s(8)),
        )

    def _draw_settings_button(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        rect = self._settings_rect(region)
        if self._hover_settings:
            pygame.draw.rect(
                surface, self.header_bg, rect,
                border_radius=self._s(5),
            )
            pygame.draw.rect(
                surface, self.border_color, rect, width=1,
                border_radius=self._s(5),
            )
        color = self.text_primary if self._hover_settings else self.text_muted
        self._draw_gear_icon(surface, rect.center, color)

    def _draw_tool_tooltip(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        if self._hover_tool not in self.TOOL_LABELS:
            return
        action = self._hover_tool
        text = (
            f"{self.TOOL_LABELS[action]}  "
            f"({self.TOOL_SHORTCUTS[action]})"
        )
        label = self._font_small.render(text, True, self.text_primary)
        padding_x = self._s(8)
        padding_y = self._s(4)
        width = label.get_width() + padding_x * 2
        height = label.get_height() + padding_y * 2
        x = self._mouse_pos[0] + self._s(16)
        if x + width > surface.get_width() - self._s(4):
            x = self._mouse_pos[0] - width - self._s(16)
        x = max(region.x + self._s(4), x)
        y = self._mouse_pos[1] - height // 2
        y = max(region.y + self._s(40), y)
        y = min(y, region.bottom - height - self._s(4))
        box = pygame.Rect(x, y, width, height)
        pygame.draw.rect(
            surface, pygame.Color(18, 18, 24), box,
            border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.border_color, box, width=1,
            border_radius=self._s(4),
        )
        surface.blit(label, label.get_rect(center=box.center))

    def _draw_settings_tooltip(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        if not self._hover_settings:
            return
        label = self._font_small.render(
            "Settings  (Ctrl+,)", True, self.text_primary
        )
        padding_x = self._s(8)
        padding_y = self._s(4)
        width = label.get_width() + padding_x * 2
        height = label.get_height() + padding_y * 2
        anchor = self._settings_rect(region)
        x = anchor.centerx - width // 2
        x = max(region.x + self._s(4), x)
        x = min(x, region.right - width - self._s(4))
        y = anchor.bottom + self._s(6)
        if y + height > region.bottom - self._s(4):
            y = anchor.top - height - self._s(6)
        box = pygame.Rect(x, y, width, height)
        pygame.draw.rect(
            surface, pygame.Color(18, 18, 24), box,
            border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.border_color, box, width=1,
            border_radius=self._s(4),
        )
        surface.blit(label, label.get_rect(center=box.center))

    def _tree_rows(
        self, region: Rect, document: Document
    ) -> List[Tuple[str, int, pygame.Rect]]:
        """Return (kind, id, rect) rows for the document browser."""
        rows: List[Tuple[str, int, pygame.Rect]] = []
        x = region.x + self._s(4)
        width = region.w - self._s(8)
        y = region.y + self._s(4)

        root_height = self._s(34)
        rows.append((
            "document", document.id,
            pygame.Rect(x, y, width, root_height),
        ))
        y += root_height + self._s(2)

        child_height = self._s(28)
        for kind in ("settings", "views", "origin"):
            rows.append((
                kind, 0, pygame.Rect(x, y, width, child_height),
            ))
            y += child_height + self._s(1)
            if kind == "origin" and self._origin_expanded:
                for index in range(len(self.ORIGIN_PLANES)):
                    rows.append((
                        "origin_plane", index,
                        pygame.Rect(x, y, width, child_height),
                    ))
                    y += child_height + self._s(1)

        y += self._s(5)
        if document.sketches:
            rows.append((
                "sketches", 0, pygame.Rect(x, y, width, child_height),
            ))
            y += child_height + self._s(1)
            if self._sketches_expanded:
                indent = self._s(22)
                for sketch in document.sketches:
                    rows.append((
                        "sketch", sketch.id,
                        pygame.Rect(
                            x + indent, y, width - indent, child_height
                        ),
                    ))
                    y += child_height + self._s(1)
        return rows

    def _origin_eye_rect(self, row: pygame.Rect) -> pygame.Rect:
        """Return the clickable visibility-toggle area on the Origin row."""
        center_x = row.x + self._s(52)
        width = self._s(24)
        return pygame.Rect(
            center_x - width // 2,
            row.y + self._s(3),
            width,
            row.height - self._s(6),
        )

    def _draw_tree(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        pygame.draw.rect(surface, self.panel_bg, region.rect)
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect)
        for kind, item_id, rect in self._tree_rows(region, document):
            self._draw_tree_row(surface, rect, kind, item_id, document)
        surface.set_clip(previous_clip)

    def _draw_tree_row(
        self, surface: pygame.Surface, rect: pygame.Rect,
        kind: str, item_id: int, document: Document,
    ) -> None:
        active = kind == "sketch" and item_id == document.active_sketch_id
        selected_plane = (
            kind == "origin_plane"
            and document.selected_plane
            == self.ORIGIN_PLANE_KEYS[item_id]
        )
        hovered = (
            (kind == "sketch" and item_id == self._hover_sketch)
            or (kind == "origin_plane" and item_id == self._hover_plane)
            or (kind == "origin" and self._hover_origin)
            or (kind == "sketches" and self._hover_sketches_folder)
        )
        if kind == "document":
            pygame.draw.rect(
                surface, self.tree_selection, rect,
                border_radius=self._s(3),
            )
        elif active or selected_plane:
            pygame.draw.rect(
                surface,
                self.tree_selection if selected_plane
                else pygame.Color(45, 45, 54),
                rect,
                border_radius=self._s(3),
            )
        elif hovered:
            pygame.draw.rect(
                surface, self.header_bg, rect,
                border_radius=self._s(3),
            )

        root = kind == "document"
        text_x, label = self._tree_entry(
            surface, rect, kind, item_id, document,
            active or selected_plane or root,
        )
        color = (
            self.text_primary
            if active or selected_plane or root
            else self.text_secondary
        )
        available = rect.right - text_x - self._s(8)
        text = self._fit_text(
            self._font_small, label, color, available,
        )
        surface.blit(
            text, text.get_rect(x=text_x, centery=rect.centery)
        )

    def _tree_entry(
        self, surface: pygame.Surface, rect: pygame.Rect,
        kind: str, item_id: int, document: Document, selected: bool,
    ) -> Tuple[int, str]:
        """Draw a row's leading glyphs and return its text position/label."""
        icon_color = (
            pygame.Color(175, 180, 192)
            if not selected else pygame.Color(205, 215, 230)
        )
        if kind == "document":
            disclosure_x = rect.x + self._s(10)
            self._draw_disclosure(
                surface, (disclosure_x, rect.centery), True,
                pygame.Color(190, 210, 235),
            )
            self._draw_target_icon(
                surface, (rect.x + self._s(34), rect.centery),
                pygame.Color(120, 185, 255),
            )
            self._draw_cube_icon(
                surface, (rect.x + self._s(56), rect.centery),
                self._s(7), pygame.Color(200, 212, 228),
            )
            label = document.name + (" *" if document.dirty else "")
            return rect.x + self._s(76), label

        if kind == "origin_plane":
            self._draw_plane_icon(
                surface, (rect.x + self._s(52), rect.centery), icon_color,
            )
            return rect.x + self._s(74), self.ORIGIN_PLANES[item_id]

        if kind == "sketches":
            self._draw_disclosure(
                surface, (rect.x + self._s(28), rect.centery),
                self._sketches_expanded, icon_color,
            )
            self._draw_folder_icon(
                surface, (rect.x + self._s(52), rect.centery), icon_color,
            )
            return rect.x + self._s(74), "Sketches"

        self._draw_disclosure(
            surface, (rect.x + self._s(28), rect.centery),
            self._origin_expanded if kind == "origin" else False,
            icon_color,
        )
        icon_x = rect.x + self._s(52)
        if kind == "settings":
            self._draw_gear_icon(surface, (icon_x, rect.centery), icon_color)
            return rect.x + self._s(74), "Document Settings"
        if kind == "views":
            self._draw_folder_icon(surface, (icon_x, rect.centery), icon_color)
            return rect.x + self._s(74), "Named Views"
        if kind == "origin":
            eye_color = (
                self.text_primary
                if self._hover_origin_eye
                else (icon_color if self._origin_visible else self.text_muted)
            )
            self._draw_eye_icon(
                surface, (icon_x, rect.centery), eye_color,
                visible=self._origin_visible,
            )
            self._draw_origin_icon(
                surface, (icon_x + self._s(22), rect.centery), icon_color,
            )
            return rect.x + self._s(96), "Origin"
        if kind == "sketch":
            sketch = document.sketch(item_id)
            label = sketch.name if sketch else "Sketch"
            if sketch is not None:
                label += f"  ({len(sketch.points)} pts)"
            pygame.draw.rect(
                surface,
                self.accent if selected else pygame.Color(100, 150, 190),
                (icon_x - self._s(4), rect.centery - self._s(4),
                 self._s(8), self._s(8)),
                border_radius=self._s(2),
            )
            return rect.x + self._s(74), label

        return rect.x + self._s(74), ""

    def _draw_disclosure(
        self, surface: pygame.Surface, center: Tuple[int, int],
        expanded: bool, color: pygame.Color,
    ) -> None:
        cx, cy = center
        size = self._s(4)
        if expanded:
            points = [
                (cx - size, cy - size // 2),
                (cx + size, cy - size // 2),
                (cx, cy + size),
            ]
        else:
            points = [
                (cx - size // 2, cy - size),
                (cx + size // 2, cy),
                (cx - size // 2, cy + size),
            ]
        pygame.draw.polygon(surface, color, points)

    def _draw_target_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        pygame.draw.circle(
            surface, color, center, self._s(6), width=self._s(2)
        )
        pygame.draw.circle(surface, color, center, self._s(2))

    def _draw_cube_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        radius: int, color: pygame.Color,
    ) -> None:
        cx, cy = center
        top = (cx, cy - radius)
        upper_left = (cx - radius, cy - radius // 2)
        upper_right = (cx + radius, cy - radius // 2)
        middle = (cx, cy)
        left_bottom = (cx - radius, cy + radius // 2)
        right_bottom = (cx + radius, cy + radius // 2)
        bottom = (cx, cy + radius)
        width = max(1, self._s(1))
        pygame.draw.lines(
            surface, color, True,
            [top, upper_right, middle, upper_left], width,
        )
        pygame.draw.lines(
            surface, color, False,
            [upper_left, left_bottom, bottom, right_bottom, upper_right],
            width,
        )
        pygame.draw.line(surface, color, middle, bottom, width)

    def _draw_gear_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        outer = self._s(7)
        inner = self._s(5)
        points = []
        for index in range(16):
            angle = index * math.pi / 8 - math.pi / 2
            radius = outer if index % 2 == 0 else inner
            points.append((
                cx + math.cos(angle) * radius,
                cy + math.sin(angle) * radius,
            ))
        pygame.draw.polygon(surface, color, points)
        pygame.draw.circle(surface, self.panel_bg, center, self._s(2))

    def _draw_folder_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        left = cx - self._s(6)
        top = cy - self._s(5)
        points = [
            (left, top + self._s(3)),
            (left + self._s(3), top),
            (left + self._s(6), top),
            (left + self._s(7), top + self._s(3)),
            (left + self._s(12), top + self._s(3)),
            (left + self._s(12), top + self._s(10)),
            (left, top + self._s(10)),
        ]
        pygame.draw.polygon(surface, color, points)

    def _draw_plane_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        half_w = self._s(7)
        half_h = self._s(4)
        points = [
            (cx - half_w, cy + self._s(1)),
            (cx - self._s(2), cy - half_h),
            (cx + half_w, cy - self._s(1)),
            (cx + self._s(2), cy + half_h),
        ]
        width = max(1, self._s(1))
        pygame.draw.polygon(surface, color, points, width)
        pygame.draw.line(
            surface, color,
            (cx - self._s(3), cy - self._s(1)),
            (cx + self._s(3), cy + self._s(1)),
            width,
        )

    def _draw_origin_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color,
    ) -> None:
        cx, cy = center
        radius = self._s(6)
        width = max(1, self._s(1))
        pygame.draw.line(
            surface, color, center, (cx, cy - radius), width
        )
        pygame.draw.line(
            surface, color, center,
            (cx - radius, cy + radius // 2), width,
        )
        pygame.draw.line(
            surface, color, center,
            (cx + radius, cy + radius // 2), width,
        )
        pygame.draw.circle(surface, color, center, self._s(1))

    def _draw_eye_icon(
        self, surface: pygame.Surface, center: Tuple[int, int],
        color: pygame.Color, visible: bool = True,
    ) -> None:
        cx, cy = center
        width = self._s(14)
        height = self._s(7)
        stroke = max(1, self._s(1))
        if visible:
            pygame.draw.ellipse(
                surface, color,
                pygame.Rect(cx - width // 2, cy - height // 2, width, height),
                width=stroke,
            )
            pygame.draw.circle(surface, color, center, self._s(2))
        else:
            pygame.draw.arc(
                surface, color,
                pygame.Rect(cx - width // 2, cy - height // 2, width, height),
                0.15 * math.pi, 0.85 * math.pi, stroke,
            )
            pygame.draw.line(
                surface, color,
                (cx - self._s(6), cy + self._s(5)),
                (cx + self._s(6), cy - self._s(5)),
                stroke,
            )

    def _draw_command_bar(
        self, surface: pygame.Surface, region: Rect,
        position: int, total: int,
    ) -> None:
        pygame.draw.rect(surface, self.panel_bg, region.rect)
        pygame.draw.line(
            surface, self.border_color,
            (region.x, region.y), (region.right, region.y),
        )

        status = f"Roll History Marker   {position} / {total}"
        status_surface = self._font_small.render(status, True, self.text_muted)
        status_x = region.right - status_surface.get_width() - self._s(12)

        prompt = self._font_small.render(">", True, self.accent)
        prompt_x = region.x + self._s(12)
        surface.blit(prompt, prompt.get_rect(x=prompt_x, centery=region.centery))

        available = status_x - prompt_x - prompt.get_width() - self._s(24)
        placeholder = self._font_small.render(
            'Type a command, e.g. Extrude {"distance": 20}',
            True, self.text_muted,
        )
        if placeholder.get_width() > available:
            placeholder = self._fit_text(
                self._font_small,
                'Type a command, e.g. Extrude {"distance": 20}',
                self.text_muted, max(0, available),
            )
        surface.blit(
            placeholder,
            placeholder.get_rect(
                x=prompt_x + prompt.get_width() + self._s(10),
                centery=region.centery,
            ),
        )
        surface.blit(status_surface, status_surface.get_rect(
            x=status_x, centery=region.centery,
        ))

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def _timeline_geometry(
        self, region: Rect, count: int
    ) -> Tuple[
        List[Tuple[str, pygame.Rect]], int, int,
        List[pygame.Rect], int, int, int, int,
    ]:
        """Return controls, separator, boxes and their measurements."""
        button = self._s(26)
        gap = self._s(4)
        x = region.x + self._s(12)
        y = region.centery - button // 2
        controls: List[Tuple[str, pygame.Rect]] = []
        for action in ("start", "prev", "play", "next", "end"):
            controls.append((action, pygame.Rect(x, y, button, button)))
            x += button + gap

        x += self._s(2)
        separator_x = x
        x += self._s(10)
        boxes_start = x

        box_height = self._s(30)
        box_width = self._s(30)
        box_gap = self._s(1)
        step = box_width + box_gap
        available = max(0, region.right - self._s(12) - boxes_start)
        if count > 0 and count * step - box_gap > available:
            step = max(self._s(16), available // count)
            box_width = max(self._s(14), step - box_gap)
        box_y = region.centery - box_height // 2 - self._s(3)
        boxes = [
            pygame.Rect(boxes_start + index * step, box_y, box_width, box_height)
            for index in range(count)
        ]
        return controls, separator_x, boxes_start, boxes, box_width, step, box_y, box_height

    def _draw_timeline(
        self, surface: pygame.Surface, region: Rect,
        history: List[HistoryEntry], full_history: List[HistoryEntry],
        position: int, playing: bool,
    ) -> None:
        pygame.draw.rect(surface, self.panel_bg, region.rect)
        pygame.draw.line(
            surface, self.border_color,
            (region.x, region.y), (region.right, region.y),
        )
        if self._selected_action is not None and self._selected_action >= len(history):
            self._selected_action = None

        total = len(history)
        full_total = len(full_history)
        (
            controls, separator_x, boxes_start, boxes,
            _, _, box_y, box_height,
        ) = self._timeline_geometry(region, total)

        pygame.draw.line(
            surface, pygame.Color(195, 195, 202),
            (separator_x, region.y + self._s(16)),
            (separator_x, region.bottom - self._s(16)),
            self._s(2),
        )

        for action, rect in controls:
            enabled = self._control_enabled(action, full_total, position)
            hovered = enabled and action == self._hover_control
            if hovered:
                pygame.draw.rect(
                    surface, self.header_bg, rect, border_radius=self._s(4)
                )
            self._draw_control(surface, rect, action, enabled, playing)

        if not history:
            hint = self._font_small.render(
                "No actions yet  —  create a sketch to start the history",
                True, self.text_muted,
            )
            surface.blit(hint, hint.get_rect(
                x=boxes_start, centery=region.centery,
            ))
        else:
            for index, rect in enumerate(boxes):
                self._draw_action_box(
                    surface, rect, history[index],
                    applied=index < self._full_to_filtered_position(position, full_history),
                    selected=index == self._selected_action,
                    hovered=index == self._hover_action,
                )

            filtered_pos = self._full_to_filtered_position(position, full_history)
            if filtered_pos <= 0:
                marker_x = boxes[0].left - self._s(2)
            elif filtered_pos >= total:
                marker_x = boxes[-1].right + self._s(2)
            else:
                marker_x = (boxes[filtered_pos - 1].right + boxes[filtered_pos].left) // 2
            pygame.draw.line(
                surface, self.accent,
                (marker_x, box_y - self._s(5)),
                (marker_x, box_y + box_height + self._s(5)),
                self._s(2),
            )
            pygame.draw.circle(
                surface, self.accent,
                (marker_x, box_y - self._s(5)), self._s(3),
            )

        if self._hover_action is not None and self._hover_action < total:
            hint_text = history[self._hover_action].label
        else:
            hint_text = (
                "Click to roll  ·  new action inserts here  ·  "
                "Del / right-click removes"
            )
        hint = self._fit_text(
            self._font_small, hint_text, self.text_muted,
            region.w - self._s(24),
        )
        surface.blit(hint, (
            region.x + self._s(12),
            region.bottom - hint.get_height() - self._s(10),
        ))

    @staticmethod
    def _control_enabled(action: str, total: int, position: int) -> bool:
        if action in ("start", "prev"):
            return position > 0
        if action in ("next", "end"):
            return position < total
        return total > 0

    def _draw_control(
        self, surface: pygame.Surface, rect: pygame.Rect,
        action: str, enabled: bool, playing: bool,
    ) -> None:
        color = self.text_primary if enabled else self.text_muted
        size = self._s(4)
        cx, cy = rect.center

        def triangle(direction: int, offset: int = 0) -> None:
            points = [
                (cx + offset - direction * size, cy - size),
                (cx + offset - direction * size, cy + size),
                (cx + offset + direction * size, cy),
            ]
            pygame.draw.polygon(surface, color, points)

        if action == "start":
            pygame.draw.line(
                surface, color,
                (rect.x + self._s(7), cy - size - self._s(1)),
                (rect.x + self._s(7), cy + size + self._s(1)),
                self._s(2),
            )
            triangle(-1, self._s(3))
        elif action == "prev":
            triangle(-1)
        elif action == "play":
            if playing:
                width = self._s(4)
                pygame.draw.rect(
                    surface, color,
                    (cx - width - self._s(1), cy - size, width, size * 2),
                )
                pygame.draw.rect(
                    surface, color,
                    (cx + self._s(1), cy - size, width, size * 2),
                )
            else:
                triangle(1)
        elif action == "next":
            triangle(1)
        elif action == "end":
            triangle(1, -self._s(3))
            pygame.draw.line(
                surface, color,
                (rect.right - self._s(7), cy - size - self._s(1)),
                (rect.right - self._s(7), cy + size + self._s(1)),
                self._s(2),
            )

    def _draw_action_box(
        self, surface: pygame.Surface, rect: pygame.Rect,
        entry: HistoryEntry, applied: bool, selected: bool, hovered: bool,
    ) -> None:
        if applied:
            background = pygame.Color(43, 43, 52)
            border = pygame.Color(65, 65, 76)
        else:
            background = pygame.Color(27, 27, 33)
            border = pygame.Color(45, 45, 54)
        if hovered:
            background = pygame.Color(55, 55, 66) if applied else pygame.Color(36, 36, 44)
        pygame.draw.rect(surface, background, rect)
        if selected:
            pygame.draw.rect(surface, self.accent, rect, width=self._s(2))
        else:
            pygame.draw.rect(surface, border, rect, width=1)

        color = self._kind_color(entry.kind) if applied else pygame.Color(78, 78, 88)
        self._draw_action_icon(surface, rect, entry.kind, color)

    @staticmethod
    def _kind_color(kind: str) -> pygame.Color:
        if kind == "sketch":
            return pygame.Color(82, 205, 132)
        if kind == "extrude":
            return pygame.Color(78, 148, 235)
        if kind == "point":
            return pygame.Color(105, 178, 242)
        return pygame.Color(150, 150, 160)

    def _draw_action_icon(
        self, surface: pygame.Surface, rect: pygame.Rect,
        kind: str, color: pygame.Color,
    ) -> None:
        cx, cy = rect.center
        radius = max(self._s(4), min(rect.w, rect.h) // 2 - self._s(6))
        if kind == "sketch":
            triangle = [
                (cx, cy - radius),
                (cx - radius, cy + radius),
                (cx + radius, cy + radius),
            ]
            pygame.draw.polygon(surface, color, triangle)
            inner = [
                (cx, cy - radius + self._s(4)),
                (cx - radius + self._s(4), cy + radius - self._s(2)),
                (cx + radius - self._s(4), cy + radius - self._s(2)),
            ]
            inner_color = pygame.Color(
                max(0, color.r // 3),
                min(255, color.g // 3 + 10),
                max(0, color.b // 3),
            )
            pygame.draw.polygon(surface, inner_color, inner)
        elif kind == "extrude":
            top = (cx, cy - radius)
            right = (cx + radius, cy - radius // 2)
            middle = (cx, cy)
            left = (cx - radius, cy - radius // 2)
            bottom = (cx, cy + radius)
            pygame.draw.polygon(surface, color, [top, right, middle, left])
            dark = pygame.Color(color.r // 2 + 25, color.g // 2 + 25, color.b // 2 + 25)
            pygame.draw.polygon(
                surface, dark,
                [left, middle, bottom, (cx - radius, cy + radius // 2)],
            )
            pygame.draw.polygon(
                surface, color,
                [middle, right, (cx + radius, cy + radius // 2), bottom],
            )
            pygame.draw.polygon(
                surface, pygame.Color(20, 20, 26),
                [top, right, middle, left], width=1,
            )
        elif kind == "point":
            dot = max(1, self._s(2))
            gap = max(self._s(4), self._s(5))
            for row in (-1, 1):
                for column in (-1, 0, 1):
                    pygame.draw.rect(
                        surface, color,
                        (cx + column * gap - dot, cy + row * gap - dot,
                         dot * 2, dot * 2),
                    )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def handle_event(
        self,
        event: pygame.event.Event,
        layout: UILayout,
        document: Document,
        history: List[HistoryEntry],
        full_history: List[HistoryEntry],
        position: int,
    ) -> bool:
        self._init_fonts()
        self._sync_history_document(document)

        active_sketch = document.sketch(document.active_sketch_id)

        # Handle sketch palette window when a sketch is being edited
        if active_sketch is not None:
            action = self.sketch_palette_window.handle_event(
                event, layout.viewport
            )
            if action is not SketchPaletteAction.NONE:
                if action == SketchPaletteAction.LOOK_AT:
                    self.viewport.camera.align_to_plane(active_sketch.frame())
                elif action == SketchPaletteAction.FINISH_SKETCH:
                    document.active_sketch_id = None
                    self.sketch_palette_window.close()
                elif action == SketchPaletteAction.LINETYPE_CHANGED:
                    if active_sketch is not None:
                        active_sketch.line_type = self.sketch_palette_window.current_line_type
                        document.dirty = True
                elif action == SketchPaletteAction.MINIMIZE:
                    # Minimize/expand handled internally
                    pass
                return True

        # Handle create sketch dialog when no active sketch
        if active_sketch is None:
            action = self.create_sketch_window.handle_event(
                event, layout.viewport
            )
            if action is not ToolWindowAction.NONE:
                return True

        if event.type == pygame.MOUSEMOTION:
            self._update_hover(
                event.pos, layout, document, history, position,
            )

        if event.type == pygame.KEYDOWN and event.key == pygame.K_DELETE:
            if self._selected_action is not None and self._selected_action < len(history):
                full_index = self._filtered_to_full_index(self._selected_action, history, full_history)
                self._selected_action = None
                self.on_history_delete(full_index)
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and layout.timeline.collidepoint(event.pos):
            if event.button == 1 and self._handle_timeline_click(
                event.pos, layout.timeline, history, full_history, position
            ):
                return True
            if event.button == 3:
                _, _, _, boxes, _, _, _, _ = self._timeline_geometry(
                    layout.timeline, len(history)
                )
                for index, rect in enumerate(boxes):
                    if rect.collidepoint(event.pos):
                        full_index = self._filtered_to_full_index(index, history, full_history)
                        self._selected_action = None
                        self.on_history_delete(full_index)
                        return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._settings_rect(layout.toolbar).collidepoint(event.pos):
                if self.on_settings is not None:
                    self.on_settings()
                return True
            for action, rect, enabled in self._toolbar_buttons(
                layout.toolbar, document
            ):
                if enabled and rect.collidepoint(event.pos):
                    self._run_tool(action)
                    return True
            if layout.document_tree.collidepoint(event.pos):
                hit_row = False
                for kind, item_id, rect in self._tree_rows(
                    layout.document_tree, document
                ):
                    if not rect.collidepoint(event.pos):
                        continue
                    hit_row = True
                    if kind == "origin":
                        if self._origin_eye_rect(rect).collidepoint(event.pos):
                            self.set_origin_visible(not self._origin_visible)
                            return True
                        self._origin_expanded = not self._origin_expanded
                        self._hover_origin = False
                        return True
                    if kind == "sketches":
                        self._sketches_expanded = not self._sketches_expanded
                        self._hover_sketches_folder = False
                        return True
                    if kind == "origin_plane":
                        plane = self.ORIGIN_PLANE_KEYS[item_id]
                        if self.create_sketch_window.visible:
                            self._finish_create_sketch(document, plane)
                        else:
                            document.selected_plane = plane
                            document.selected_face = None
                            document.active_sketch_id = None
                        return True
                    if kind == "sketch":
                        self.on_select_sketch(item_id)
                        return True
                if not hit_row:
                    document.selected_plane = None
                    document.selected_face = None
                    return True

        handled = self.viewport.handle_event(
            event, layout.viewport, document, self.on_add_point
        )
        if self.create_sketch_window.visible and active_sketch is None:
            if document.selected_face is not None:
                self._finish_create_sketch(
                    document, face_ref=document.selected_face
                )
            elif document.selected_plane is not None:
                self._finish_create_sketch(
                    document, document.selected_plane
                )
        return handled

    def _filtered_to_full_index(
        self,
        filtered_index: int,
        filtered_history: List[HistoryEntry],
        full_history: List[HistoryEntry],
    ) -> int:
        """Map a filtered history index to the corresponding full history index."""
        if filtered_index >= len(filtered_history):
            return len(full_history)
        target = filtered_history[filtered_index]
        # Find the matching entry in full_history at or after the previous match.
        match_count = 0
        for i, entry in enumerate(full_history):
            if entry.kind == "point":
                continue
            if match_count == filtered_index:
                return i
            match_count += 1
        return len(full_history)

    def _full_to_filtered_position(
        self,
        full_position: int,
        full_history: List[HistoryEntry],
    ) -> int:
        """Map a full history position to the filtered position for the marker."""
        # Count non-point entries up to (but not including) full_position.
        return sum(
            1 for entry in full_history[:full_position] if entry.kind != "point"
        )

    def _handle_timeline_click(
        self, pos: Tuple[int, int], region: Rect,
        history: List[HistoryEntry], full_history: List[HistoryEntry], position: int,
    ) -> bool:
        controls, _, boxes_start, boxes, _, _, _, _ = self._timeline_geometry(
            region, len(history)
        )
        full_total = len(full_history)
        for action, rect in controls:
            if rect.collidepoint(pos):
                self._selected_action = None
                self._run_history_control(action, full_total, position)
                return True

        for index, rect in enumerate(boxes):
            if rect.collidepoint(pos):
                full_index = self._filtered_to_full_index(index, history, full_history)
                self._selected_action = index
                self.on_history_jump(full_index + 1)
                return True

        boxes_center_y = region.centery
        if abs(pos[1] - boxes_center_y) <= self._s(20):
            if boxes and pos[0] > boxes[-1].right:
                self._selected_action = None
                self.on_history_jump(full_total)
                return True
            if pos[0] < boxes_start:
                self._selected_action = None
                self.on_history_jump(0)
                return True
        return False

    def _run_history_control(self, action: str, total: int, position: int) -> None:
        if action == "start":
            self.on_history_jump(0)
        elif action == "prev":
            self.on_history_jump(max(0, position - 1))
        elif action == "play":
            self.on_history_play()
        elif action == "next":
            self.on_history_jump(min(total, position + 1))
        elif action == "end":
            self.on_history_jump(total)

    def _run_tool(self, action: str) -> None:
        if action == "sketch":
            self.on_new_sketch()
        elif action == "extrude":
            self.on_extrude()

    def _update_hover(
        self, pos: Tuple[int, int], layout: UILayout,
        document: Document, history: List[HistoryEntry], position: int,
    ) -> None:
        self._mouse_pos = pos
        self._hover_tool = None
        self._hover_sketch = None
        self._hover_plane = None
        self._hover_control = None
        self._hover_action = None
        self._hover_origin = False
        self._hover_origin_eye = False
        self._hover_sketches_folder = False
        if self.create_sketch_window.update_hover(pos, layout.viewport):
            return
        self._hover_settings = self._settings_rect(
            layout.toolbar
        ).collidepoint(pos)
        for action, rect, enabled in self._toolbar_buttons(
            layout.toolbar, document
        ):
            if enabled and rect.collidepoint(pos):
                self._hover_tool = action
                break
        for kind, item_id, rect in self._tree_rows(layout.document_tree, document):
            if not rect.collidepoint(pos):
                continue
            if kind == "sketch":
                self._hover_sketch = item_id
            elif kind == "origin_plane":
                self._hover_plane = item_id
            elif kind == "sketches":
                self._hover_sketches_folder = True
            elif kind == "origin":
                self._hover_origin = True
                self._hover_origin_eye = self._origin_eye_rect(
                    rect
                ).collidepoint(pos)

        if layout.timeline.collidepoint(pos):
            controls, _, _, boxes, _, _, _, _ = self._timeline_geometry(
                layout.timeline, len(history)
            )
            for action, rect in controls:
                if rect.collidepoint(pos):
                    self._hover_control = action
                    return
            for index, rect in enumerate(boxes):
                if rect.collidepoint(pos):
                    self._hover_action = index
                    return

    def _fit_text(
        self, font: pygame.font.Font, text: str,
        color: pygame.Color, max_width: int,
    ) -> pygame.Surface:
        if font.size(text)[0] <= max_width:
            return font.render(text, True, color)
        ellipsis = "..."
        available = max_width - font.size(ellipsis)[0]
        if available <= 0:
            return font.render(ellipsis, True, color)
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if font.size(text[:mid])[0] <= available:
                low = mid
            else:
                high = mid - 1
        return font.render(text[:low] + ellipsis, True, color)
