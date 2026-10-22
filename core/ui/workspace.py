"""Document workspace drawing for PY3DCAD."""

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import pygame

from ..document import Document
from ..sketch import Point, Sketch, point_on_plane
from .layout import Rect, UILayout
from .tool_properties import ToolPropertiesWindow, ToolWindowAction, SketchPaletteWindow, SketchPaletteAction
from .viewport import Viewport


@dataclass
class HistoryEntry:
    """One action in the document history."""

    kind: str
    label: str
    timeline_visible: bool = True


@dataclass
class ToolbarItem:
    """One button inside a grouped sketch toolbar."""

    action: str
    rect: pygame.Rect
    label: Optional[str] = None
    placeholder: bool = False
    dropdown: bool = False


@dataclass
class ToolbarGroupLayout:
    """A captioned group of sketch toolbar buttons."""

    caption: str
    rect: pygame.Rect
    items: List[ToolbarItem]
    finish: bool = False


class Workspace:
    """Draws the document workspace and routes editing interactions."""

    TOOL_LABELS = {
        "sketch": "Sketch",
        "line": "Line",
        "point": "Point",
        "finish_sketch": "Finish Sketch",
        "extrude": "Extrude",
    }
    TOOL_SHORTCUTS = {"sketch": "S", "extrude": "E"}
    MODES = ("SOLID", "SURFACE", "MESH", "SHEET METAL", "PLASTIC", "UTILITIES")
    ACTIVE_MODE = "SOLID"
    SKETCH_MODE = "SKETCH"
    ORIGIN_PLANES = ("XY Plane", "YZ Plane", "ZX Plane")
    ORIGIN_PLANE_KEYS = ("XY", "YZ", "ZX")

    # Caption, (action, visible label, dropdown caret)
    SKETCH_GROUPS = (
        ("CREATE", (
            ("line", "Line", True),
            ("rectangle", "Rectangle", True),
            ("circle", "Circle", True),
            ("arc", "Arc", True),
            ("slot", "Slot", True),
            ("polygon", "Polygon", True),
            ("spline", "Spline", True),
            ("point", "Point", False),
        )),
        ("MODIFY", (
            ("fillet", None, False),
            ("trim", None, False),
        )),
        ("PATTERN", (
            ("linear_pattern", None, True),
            ("circular_pattern", None, True),
        )),
        ("CONSTRAINTS", (
            ("constraint_vertical", None, True),
            ("constraint_horizontal", None, False),
            ("constraint_perpendicular", None, False),
            ("constraint_tangent", None, False),
            ("constraint_equal", None, False),
            ("constraint_midpoint", None, False),
        )),
        ("INSPECT", (
            ("measure", None, True),
            ("section_view", None, False),
        )),
        ("INSERT", (
            ("insert_part", None, True),
            ("insert_sketch", None, False),
        )),
        ("SELECT", (
            ("select", None, True),
        )),
        ("FINISH SKETCH", (
            ("finish_sketch", None, False),
        )),
    )
    ACTIVE_SKETCH_TOOLS = ("line", "point", "finish_sketch")
    LINE_MENU_ITEMS = (
        ("normal", "Line"),
        ("construction", "Construction Line"),
        ("center", "Centerline"),
    )

    def __init__(
        self,
        on_new_sketch: Callable[[], None],
        on_extrude: Callable[[], None],
        on_add_point: Callable[[Point], None],
        on_add_line: Callable[[Point, Point], None],
        on_move_point: Callable[[int, Point], None],
        on_select_sketch: Callable[[int], None],
        on_history_jump: Callable[[int], None],
        on_history_delete: Callable[[int], None],
        on_history_play: Callable[[], None],
        on_settings: Optional[Callable[[], None]] = None,
    ) -> None:
        self.on_new_sketch = on_new_sketch
        self.on_extrude = on_extrude
        self.on_add_point = on_add_point
        self.on_add_line = on_add_line
        self.on_move_point = on_move_point
        self.on_select_sketch = on_select_sketch
        self.on_history_jump = on_history_jump
        self.on_history_delete = on_history_delete
        self.on_history_play = on_history_play
        self.on_settings = on_settings

        self.scale = 1.0
        self.viewport = Viewport()
        self._hover_tool: Optional[str] = None
        self._hover_mode: Optional[str] = None
        self._active_mode_name = self.ACTIVE_MODE
        self._selected_tool: Optional[str] = None
        self._line_start: Optional[Point] = None
        self._line_preview: Optional[Point] = None
        self._line_menu_open = False
        self._line_menu_hover = -1
        self._selected_sketch_entity: Optional[Tuple[str, int]] = None
        self._hover_sketch_entity: Optional[Tuple[str, int]] = None
        self._drag_point_index: Optional[int] = None
        self._drag_point_origin: Optional[Point] = None
        self._drag_point_current: Optional[Point] = None
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
        self._selection_sketch_id: Optional[int] = None
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
        self.geometry_selection = pygame.Color(255, 193, 110)
        self.geometry_hover = pygame.Color(255, 224, 180)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self.viewport.set_scale(scale)
        self._hover_tool = None
        self._hover_mode = None
        self._hover_sketch = None
        self._hover_plane = None
        self._hover_control = None
        self._hover_action = None
        self._hover_settings = False
        self._hover_origin = False
        self._hover_origin_eye = False
        self._hover_sketches_folder = False
        self._hover_sketch_entity = None
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

    def begin_sketch_edit(self) -> None:
        """Start sketch editing with the point tool selected."""
        self._active_mode_name = self.SKETCH_MODE
        self._selected_tool = "point"
        self._reset_line_state()
        self._clear_sketch_selection()

    def deselect_tool(self) -> None:
        """Clear the current sketch tool without leaving sketch mode."""
        self._selected_tool = None
        self._reset_line_state()
        self._clear_sketch_selection()

    def _clear_sketch_selection(self) -> None:
        self._selected_sketch_entity = None
        self._hover_sketch_entity = None
        self._drag_point_index = None
        self._drag_point_origin = None
        self._drag_point_current = None

    def _reset_line_state(self) -> None:
        self._line_start = None
        self._line_preview = None
        self._line_menu_open = False
        self._line_menu_hover = -1

    def _select_tool(self, tool: Optional[str]) -> None:
        self._selected_tool = tool
        self._reset_line_state()
        self._clear_sketch_selection()

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
        self.viewport.draw(
            surface,
            layout.viewport,
            document,
            self._selected_tool,
        )
        self._draw_line_preview(surface, layout.viewport, document)
        self._draw_sketch_selection(surface, layout.viewport, document)
        if layout.command_bar.w > 0:
            self._draw_command_bar(
                surface,
                layout.command_bar,
                self._full_to_filtered_position(position, full_history),
                len(history),
            )
        self._draw_timeline(
            surface, layout.timeline, history, full_history, position, playing
        )
        active_sketch = document.sketch(document.active_sketch_id)
        if active_sketch is not None:
            self.sketch_palette_window.draw(surface, layout.viewport)
        else:
            self.create_sketch_window.draw(surface, layout.viewport)
        self._draw_line_menu(surface, layout.toolbar, document)

    def _sync_history_document(self, document: Document) -> None:
        if document.id != self._history_document:
            self._history_document = document.id
            self._selected_action = None
            self._active_mode_name = (
                self.SKETCH_MODE
                if document.sketch(document.active_sketch_id) is not None
                else self.ACTIVE_MODE
            )
            self._hover_mode = None
            self._hover_action = None
            self._hover_control = None
            self._hover_sketches_folder = False
            self._sketches_expanded = True
            self._reset_line_state()
            self._clear_sketch_selection()
            self.close_create_sketch_dialog()
        if document.active_sketch_id != self._selection_sketch_id:
            self._selection_sketch_id = document.active_sketch_id
            self._reset_line_state()
            self._clear_sketch_selection()
        active = document.sketch(document.active_sketch_id)
        if active is None:
            self._selected_tool = None
            self._reset_line_state()
            self._clear_sketch_selection()
            if self._active_mode_name == self.SKETCH_MODE:
                self._active_mode_name = self.ACTIVE_MODE
        else:
            self._validate_sketch_selection(active)

    def _validate_sketch_selection(self, sketch: Sketch) -> None:
        """Drop selections and drags that no longer point at live geometry."""
        selected = self._selected_sketch_entity
        if selected is not None:
            kind, index = selected
            limit = (
                len(sketch.points) if kind == "point"
                else len(sketch.lines)
            )
            if kind not in ("point", "line") or not 0 <= index < limit:
                self._clear_sketch_selection()
        hovered = self._hover_sketch_entity
        if hovered is not None:
            kind, index = hovered
            limit = (
                len(sketch.points) if kind == "point"
                else len(sketch.lines)
            )
            if kind not in ("point", "line") or not 0 <= index < limit:
                self._hover_sketch_entity = None
        if (
            self._drag_point_index is not None
            and not 0 <= self._drag_point_index < len(sketch.points)
        ):
            self._clear_sketch_selection()

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

    @staticmethod
    def _modes(document: Document) -> Tuple[str, ...]:
        """Return the mode tabs for the document's current edit state."""
        if document.sketch(document.active_sketch_id) is not None:
            return (Workspace.SKETCH_MODE,) + Workspace.MODES
        return Workspace.MODES

    def _active_mode(self, document: Document) -> str:
        return self._active_mode_name

    def _sketch_toolbar_visible(self, document: Document) -> bool:
        return (
            document.sketch(document.active_sketch_id) is not None
            and self._active_mode_name == self.SKETCH_MODE
        )

    def _mode_rects(
        self, region: Rect, document: Document
    ) -> List[Tuple[str, pygame.Rect]]:
        self._init_fonts()
        modes = self._modes(document)
        start = self._content_x(region)
        right_limit = self._settings_rect(region).left - self._s(8)
        available = right_limit - start
        label_widths = [self._font_tab.size(mode)[0] for mode in modes]
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
        for mode, label_width in zip(modes, label_widths):
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
        extrude_ready = (
            sketch is not None and len(sketch.profile_points()) >= 3
        )
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

    def _build_sketch_toolbar(
        self, region: Rect, compact: bool, padding: int, gap: int,
        icon_width: int = 30,
    ) -> Tuple[List[ToolbarGroupLayout], int]:
        """Lay out the grouped sketch command bar and return its total width."""
        start = self._content_x(region)
        icon_height = self._s(30)
        icon_y = region.y + self._s(42)
        x = start
        groups: List[ToolbarGroupLayout] = []

        for caption, specs in self.SKETCH_GROUPS:
            create_group = caption == "CREATE"
            finish_group = caption == "FINISH SKETCH"
            widths: List[int] = []
            for action, label, dropdown in specs:
                if create_group and not compact and label:
                    caret = self._s(8) if dropdown else self._s(4)
                    widths.append(max(
                        self._s(30),
                        self._font_small.size(label)[0] + caret,
                    ))
                elif finish_group:
                    widths.append(self._s(max(36, icon_width)))
                else:
                    widths.append(self._s(icon_width))

            content_width = sum(widths) + gap * (len(widths) - 1)
            if finish_group:
                caption_width = max(
                    self._font_caption.size("FINISH")[0],
                    self._font_caption.size("SKETCH")[0],
                ) + self._s(10)
            else:
                caption_width = (
                    self._font_caption.size(caption)[0] + self._s(10)
                )
            group_width = max(content_width, caption_width) + padding * 2
            group_rect = pygame.Rect(
                x,
                region.y + self._s(38),
                group_width,
                region.h - self._s(44),
            )
            item_x = group_rect.x + (group_width - content_width) // 2
            items: List[ToolbarItem] = []
            for (action, label, dropdown), width in zip(specs, widths):
                items.append(ToolbarItem(
                    action=action,
                    rect=pygame.Rect(item_x, icon_y, width, icon_height),
                    label=(
                        label if create_group and not compact else None
                    ),
                    placeholder=action not in self.ACTIVE_SKETCH_TOOLS,
                    dropdown=dropdown,
                ))
                item_x += width + gap
            groups.append(ToolbarGroupLayout(
                caption=caption,
                rect=group_rect,
                items=items,
                finish=finish_group,
            ))
            x += group_width
        return groups, x - start

    def _sketch_toolbar_groups(
        self, region: Rect, document: Document
    ) -> List[ToolbarGroupLayout]:
        self._init_fonts()
        start = self._content_x(region)
        right_limit = self._settings_rect(region).left - self._s(8)
        available = right_limit - start
        last: List[ToolbarGroupLayout] = []
        for compact in (False, True):
            icon_widths = (30,) if not compact else (30, 28, 26, 24, 22)
            for icon_width in icon_widths:
                for padding, gap in (
                    (self._s(10), self._s(8)),
                    (self._s(7), self._s(6)),
                    (self._s(8), self._s(6)),
                    (self._s(8), self._s(4)),
                    (self._s(6), self._s(3)),
                    (self._s(4), self._s(2)),
                    (self._s(2), self._s(1)),
                ):
                    groups, total = self._build_sketch_toolbar(
                        region, compact, padding, gap, icon_width
                    )
                    last = groups
                    if total <= available:
                        return groups
        return self._fit_sketch_groups(last, start, available)

    def _fit_sketch_groups(
        self, groups: List[ToolbarGroupLayout], start: int, available: int
    ) -> List[ToolbarGroupLayout]:
        """Keep the finish group visible when the toolbar cannot fit it all."""
        if len(groups) <= 1:
            return groups
        finish = groups[-1]
        middle = list(groups[:-1])
        while (
            middle
            and sum(group.rect.w for group in middle) + finish.rect.w
            > available
        ):
            middle.pop()
        x = start
        for group in middle:
            self._move_toolbar_group(group, x - group.rect.x)
            x += group.rect.w
        finish_x = start + available - finish.rect.w
        self._move_toolbar_group(finish, finish_x - finish.rect.x)
        return middle + [finish]

    @staticmethod
    def _move_toolbar_group(group: ToolbarGroupLayout, dx: int) -> None:
        group.rect.x += dx
        for item in group.items:
            item.rect.x += dx

    def _toolbar_item_hit_rect(self, item: ToolbarItem) -> pygame.Rect:
        if item.label is None:
            return item.rect
        return pygame.Rect(
            item.rect.x,
            item.rect.y,
            item.rect.w,
            self._s(46),
        )

    def _toolbar_dropdown_rect(
        self, item: ToolbarItem
    ) -> Optional[pygame.Rect]:
        if item.label is None or not item.dropdown:
            return None
        self._init_fonts()
        label_width = self._font_small.size(item.label)[0]
        label_right = item.rect.centerx + label_width // 2
        caret_y = (
            item.rect.bottom + self._s(8)
            + self._font_small.get_height() // 2
        )
        return pygame.Rect(
            label_right + self._s(2) - self._s(5),
            caret_y - self._s(8),
            self._s(15),
            self._s(16),
        )

    def _line_menu_geometry(
        self, region: Rect, document: Document
    ) -> Optional[
        Tuple[pygame.Rect, List[pygame.Rect], Optional[pygame.Rect]]
    ]:
        if not self._sketch_toolbar_visible(document):
            return None
        line_item: Optional[ToolbarItem] = None
        for group in self._sketch_toolbar_groups(region, document):
            for item in group.items:
                if item.action == "line":
                    line_item = item
                    break
            if line_item is not None:
                break
        if line_item is None:
            return None
        padding = self._s(4)
        row_height = self._s(28)
        width = self._s(190)
        panel = pygame.Rect(
            line_item.rect.x - padding,
            region.bottom + self._s(2),
            width,
            row_height * len(self.LINE_MENU_ITEMS) + padding * 2,
        )
        panel.x = max(
            region.x + self._s(8),
            min(panel.x, region.right - panel.w - self._s(8)),
        )
        rows = [
            pygame.Rect(
                panel.x + padding,
                panel.y + padding + index * row_height,
                panel.w - padding * 2,
                row_height,
            )
            for index in range(len(self.LINE_MENU_ITEMS))
        ]
        return panel, rows, self._toolbar_dropdown_rect(line_item)

    def _line_menu_index_at(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> int:
        geometry = self._line_menu_geometry(region, document)
        if geometry is None:
            return -1
        _, rows, _ = geometry
        for index, rect in enumerate(rows):
            if rect.collidepoint(pos):
                return index
        return -1

    def _choose_line_type(self, index: int, document: Document) -> None:
        if not 0 <= index < len(self.LINE_MENU_ITEMS):
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        key, _ = self.LINE_MENU_ITEMS[index]
        sketch.line_type = key
        self.sketch_palette_window.current_line_type = key
        self._selected_tool = "line"
        self._line_start = None
        self._line_preview = None
        self._line_menu_open = False
        self._line_menu_hover = -1
        self._clear_sketch_selection()
        document.dirty = True

    def _handle_sketch_toolbar_click(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> bool:
        for group in self._sketch_toolbar_groups(region, document):
            if group.finish and group.rect.collidepoint(pos):
                document.active_sketch_id = None
                self._selected_tool = None
                self._reset_line_state()
                self._clear_sketch_selection()
                self.sketch_palette_window.close()
                return True
            for item in group.items:
                if item.action not in ("line", "point"):
                    continue
                if item.action == "line":
                    caret = self._toolbar_dropdown_rect(item)
                    if caret is not None and caret.collidepoint(pos):
                        self._line_menu_open = not self._line_menu_open
                        self._line_menu_hover = -1
                        return True
                if not self._toolbar_item_hit_rect(item).collidepoint(pos):
                    continue
                self._select_tool(item.action)
                return True
        return False

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
        self._draw_modes(surface, region, document)
        if self._sketch_toolbar_visible(document):
            self._draw_sketch_toolbar(surface, region, document)
        else:
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
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        active_mode = self._active_mode(document)
        for mode, rect in self._mode_rects(region, document):
            active = mode == active_mode
            hovered = mode == self._hover_mode and not active
            if hovered:
                pygame.draw.rect(
                    surface, self.header_bg, rect,
                    border_radius=self._s(3),
                )
            if active:
                color = (
                    self._kind_color("sketch")
                    if mode == self.SKETCH_MODE
                    else self.text_primary
                )
            elif hovered:
                color = self.text_secondary
            else:
                color = self.text_muted
            label = self._font_tab.render(mode, True, color)
            surface.blit(label, label.get_rect(
                center=(rect.centerx, rect.centery - self._s(1))
            ))
            if active:
                half = label.get_width() // 2 + self._s(2)
                y = rect.bottom - self._s(2)
                pygame.draw.line(
                    surface, color,
                    (rect.centerx - half, y),
                    (rect.centerx + half, y),
                    self._s(2),
                )

    def _draw_sketch_toolbar(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        groups = self._sketch_toolbar_groups(region, document)
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        for index, group in enumerate(groups):
            if index > 0:
                pygame.draw.line(
                    surface,
                    self.border_color,
                    (group.rect.x, region.y + self._s(40)),
                    (group.rect.x, region.bottom - self._s(6)),
                )
            if group.finish:
                hovered = self._hover_tool == "finish_sketch"
                color = self._kind_color("sketch")
            else:
                hovered = False
                color = self.text_secondary
            for item in group.items:
                active = (
                    item.action in ("line", "point")
                    and self._selected_tool == item.action
                )
                item_hover = (
                    item.action in ("line", "point")
                    and self._hover_tool == item.action
                ) or (
                    item.action == "finish_sketch"
                    and self._hover_tool == "finish_sketch"
                )
                if item.action == "line" and self._line_menu_open:
                    item_hover = True
                if active or item_hover:
                    pygame.draw.rect(
                        surface, self.header_bg, item.rect,
                        border_radius=self._s(5),
                    )
                    pygame.draw.rect(
                        surface,
                        self.accent if active else self.border_color,
                        item.rect,
                        width=self._s(2 if active else 1),
                        border_radius=self._s(5),
                    )
                if item.placeholder:
                    item_color = self.text_secondary
                elif item.action == "finish_sketch":
                    item_color = color
                else:
                    item_color = self._kind_color(item.action)
                self._draw_action_icon(
                    surface, item.rect, item.action, item_color
                )
                if item.label is not None:
                    self._draw_toolbar_tool_label(
                        surface, item, item_color, active or item_hover
                    )
            self._draw_group_caption(surface, region, group, hovered)
        surface.set_clip(previous_clip)

    def _draw_toolbar_tool_label(
        self, surface: pygame.Surface, item: ToolbarItem,
        color: pygame.Color, emphasize: bool,
    ) -> None:
        label_color = self.text_primary if emphasize else color
        label = self._font_small.render(
            item.label, True, label_color
        )
        y = item.rect.bottom + self._s(8)
        label_rect = label.get_rect(center=(item.rect.centerx, y))
        surface.blit(label, label_rect)
        if item.dropdown:
            self._draw_dropdown_caret(
                surface,
                label_rect.right + self._s(2),
                label_rect.centery,
                self.text_muted,
            )

    def _draw_group_caption(
        self, surface: pygame.Surface, region: Rect,
        group: ToolbarGroupLayout, hovered: bool,
    ) -> None:
        color = (
            self._kind_color("sketch") if group.finish
            else (self.text_primary if hovered else self.text_secondary)
        )
        if group.finish:
            for index, word in enumerate(("FINISH", "SKETCH")):
                label = self._font_caption.render(word, True, color)
                y = region.bottom - self._s(18 - index * 11)
                surface.blit(
                    label,
                    label.get_rect(center=(group.rect.centerx, y)),
                )
            return
        label = self._font_caption.render(group.caption, True, color)
        y = region.bottom - self._s(11)
        surface.blit(
            label,
            label.get_rect(center=(group.rect.centerx, y)),
        )

    def _draw_dropdown_caret(
        self, surface: pygame.Surface, x: int, y: int,
        color: pygame.Color,
    ) -> None:
        pygame.draw.polygon(surface, color, [
            (x, y - self._s(2)),
            (x + self._s(5), y - self._s(2)),
            (x + self._s(2), y + self._s(2)),
        ])

    def _draw_line_preview(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        if (
            self._selected_tool != "line"
            or self._line_start is None
            or self._line_preview is None
        ):
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not self._sketch_toolbar_visible(document):
            return
        frame = sketch.frame()
        center = region.center
        start = self.viewport.camera.project(
            point_on_plane(frame, self._line_start), center
        )
        end = self.viewport.camera.project(
            point_on_plane(frame, self._line_preview), center
        )
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        pygame.draw.line(
            surface, self.accent, start, end, self._s(2)
        )
        pygame.draw.circle(
            surface, self.accent,
            (round(start[0]), round(start[1])), self._s(3),
        )
        surface.set_clip(previous_clip)

    def _project_sketch_point(
        self, sketch: Sketch, point: Point, region: Rect
    ) -> Tuple[float, float]:
        return self.viewport.camera.project(
            point_on_plane(sketch.frame(), point), region.center
        )

    @staticmethod
    def _distance_to_segment(
        pos: Tuple[float, float],
        start: Tuple[float, float],
        end: Tuple[float, float],
    ) -> float:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-9:
            return math.hypot(pos[0] - start[0], pos[1] - start[1])
        t = (
            (pos[0] - start[0]) * dx
            + (pos[1] - start[1]) * dy
        ) / length_sq
        t = max(0.0, min(1.0, t))
        closest_x = start[0] + dx * t
        closest_y = start[1] + dy * t
        return math.hypot(pos[0] - closest_x, pos[1] - closest_y)

    def _pick_sketch_point(
        self, pos: Tuple[int, int], region: Rect, sketch: Sketch
    ) -> Optional[int]:
        point_limit = self._s(8)
        nearest_point: Optional[int] = None
        nearest_distance = float(point_limit)
        for index, point in enumerate(sketch.points):
            screen = self._project_sketch_point(sketch, point, region)
            distance = math.hypot(
                pos[0] - screen[0], pos[1] - screen[1]
            )
            if distance <= nearest_distance:
                nearest_point = index
                nearest_distance = distance
        return nearest_point

    def _pick_sketch_entity(
        self, pos: Tuple[int, int], region: Rect, sketch: Sketch
    ) -> Optional[Tuple[str, int]]:
        point_index = self._pick_sketch_point(pos, region, sketch)
        if point_index is not None:
            return "point", point_index

        line_limit = self._s(6)
        nearest_line: Optional[int] = None
        nearest_distance = float(line_limit)
        for index, (start, end) in enumerate(sketch.lines):
            screen_start = self._project_sketch_point(
                sketch, start, region
            )
            screen_end = self._project_sketch_point(
                sketch, end, region
            )
            distance = self._distance_to_segment(
                pos, screen_start, screen_end
            )
            if distance <= nearest_distance:
                nearest_line = index
                nearest_distance = distance
        if nearest_line is not None:
            return "line", nearest_line
        return None

    def _draw_sketch_selection(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not self._sketch_toolbar_visible(document):
            return
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        selected = self._selected_sketch_entity
        hovered = self._hover_sketch_entity
        if hovered is not None and hovered != selected:
            self._draw_sketch_entity_highlight(
                surface, sketch, region, hovered,
                self.geometry_hover, False,
            )
        if selected is not None:
            self._draw_sketch_entity_highlight(
                surface, sketch, region, selected, self.geometry_selection, True
            )
        self._draw_point_drag_preview(surface, sketch, region)
        surface.set_clip(previous_clip)

    def _draw_point_drag_preview(
        self, surface: pygame.Surface, sketch: Sketch, region: Rect
    ) -> None:
        index = self._drag_point_index
        current = self._drag_point_current
        if index is None or current is None or not 0 <= index < len(
            sketch.points
        ):
            return
        origin = self._drag_point_origin or sketch.points[index]
        if current == origin:
            return
        screen_origin = self._project_sketch_point(sketch, origin, region)
        screen_current = self._project_sketch_point(sketch, current, region)
        connected_edges = [
            (start, end)
            for start, end in sketch.edges
            if index in (start, end)
        ]
        if not connected_edges:
            pygame.draw.line(
                surface, self.geometry_selection,
                screen_origin, screen_current, max(1, self._s(1)),
            )
        preview_points = list(sketch.points)
        preview_points[index] = current
        profile = [
            self._project_sketch_point(sketch, preview_points[point_index], region)
            for point_index in sketch.profile
            if 0 <= point_index < len(preview_points)
        ]
        if len(profile) >= 2:
            pygame.draw.lines(
                surface, self.geometry_selection, len(profile) >= 3,
                profile, max(1, self._s(1)),
            )
        for start, end in connected_edges:
            screen_start = self._project_sketch_point(
                sketch, preview_points[start], region
            )
            screen_end = self._project_sketch_point(
                sketch, preview_points[end], region
            )
            pygame.draw.line(
                surface, self.geometry_selection,
                screen_start, screen_end, max(1, self._s(1)),
            )
        pygame.draw.circle(
            surface, self.geometry_selection,
            (round(screen_current[0]), round(screen_current[1])),
            self._s(5), width=max(1, self._s(2)),
        )

    def _draw_sketch_entity_highlight(
        self, surface: pygame.Surface, sketch: Sketch, region: Rect,
        entity: Tuple[str, int], color: pygame.Color, selected: bool,
    ) -> None:
        kind, index = entity
        if kind == "point":
            if not 0 <= index < len(sketch.points):
                return
            screen = self._project_sketch_point(
                sketch, sketch.points[index], region
            )
            pygame.draw.circle(
                surface, color,
                (round(screen[0]), round(screen[1])),
                self._s(8 if selected else 6),
                width=max(1, self._s(2 if selected else 1)),
            )
            return
        if not 0 <= index < len(sketch.lines):
            return
        start, end = sketch.lines[index]
        screen_start = self._project_sketch_point(sketch, start, region)
        screen_end = self._project_sketch_point(sketch, end, region)
        pygame.draw.line(
            surface, color, screen_start, screen_end,
            max(1, self._s(3 if selected else 2)),
        )

    def _draw_line_menu(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        if not self._line_menu_open:
            return
        active = document.sketch(document.active_sketch_id)
        if active is None:
            return
        geometry = self._line_menu_geometry(region, document)
        if geometry is None:
            return
        panel, rows, _ = geometry
        pygame.draw.rect(
            surface, self.panel_bg, panel, border_radius=self._s(6)
        )
        pygame.draw.rect(
            surface, self.border_color, panel, width=1,
            border_radius=self._s(6),
        )
        for index, ((key, label), rect) in enumerate(
            zip(self.LINE_MENU_ITEMS, rows)
        ):
            selected = active.line_type == key
            hovered = index == self._line_menu_hover
            if hovered:
                pygame.draw.rect(
                    surface, self.header_bg, rect,
                    border_radius=self._s(4),
                )
            if selected:
                pygame.draw.rect(
                    surface, self.accent,
                    pygame.Rect(
                        rect.x, rect.y + self._s(4),
                        self._s(2), rect.h - self._s(8),
                    ),
                    border_radius=self._s(1),
                )
            color = (
                self.accent if selected
                else (self.text_primary if hovered else self.text_secondary)
            )
            self._draw_line_type_sample(surface, rect, key, color)
            text = self._font_small.render(label, True, color)
            surface.blit(
                text,
                text.get_rect(
                    midleft=(rect.x + self._s(42), rect.centery)
                ),
            )

    def _draw_line_type_sample(
        self, surface: pygame.Surface, rect: pygame.Rect,
        key: str, color: pygame.Color,
    ) -> None:
        x1 = rect.x + self._s(10)
        x2 = x1 + self._s(26)
        y = rect.centery
        width = max(1, self._s(1))
        if key == "normal":
            pygame.draw.line(surface, color, (x1, y), (x2, y), width)
            return
        dash = self._s(4 if key == "construction" else 9)
        gap = self._s(3)
        x = x1
        while x < x2:
            stop = min(x + dash, x2)
            pygame.draw.line(surface, color, (x, y), (stop, y), width)
            x += dash + gap
        if key == "center":
            pygame.draw.circle(surface, color, ((x1 + x2) // 2, y), width)

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
                    surface, self.border_color, rect,
                    width=self._s(1),
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
        caption = "CREATE"
        label = self._font_caption.render(
            caption, True, self.text_primary
        )
        label_y = region.bottom - self._s(15)
        surface.blit(
            label,
            label.get_rect(center=(center_x, label_y)),
        )
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
        if self._line_menu_open:
            return
        if self._hover_tool not in self.TOOL_LABELS:
            return
        action = self._hover_tool
        text = self.TOOL_LABELS[action]
        shortcut = self.TOOL_SHORTCUTS.get(action)
        if shortcut is not None:
            text = f"{text}  ({shortcut})"
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
        if kind in ("sketch", "finish_sketch"):
            return pygame.Color(82, 205, 132)
        if kind == "extrude":
            return pygame.Color(78, 148, 235)
        if kind in ("line", "point"):
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
        elif kind == "finish_sketch":
            pygame.draw.lines(
                surface, color, False,
                [
                    (cx - radius, cy),
                    (cx - radius // 3, cy + radius // 2),
                    (cx + radius, cy - radius // 2),
                ],
                max(2, self._s(2)),
            )
        elif kind == "line":
            pygame.draw.line(
                surface, color,
                (cx - radius, cy + radius),
                (cx + radius, cy - radius),
                max(2, self._s(2)),
            )
        elif kind == "rectangle":
            pygame.draw.rect(
                surface, color,
                (cx - radius, cy - radius + 1,
                 radius * 2, radius * 2 - 2),
                max(1, self._s(2)), border_radius=self._s(2),
            )
        elif kind == "circle":
            pygame.draw.circle(
                surface, color, (cx, cy), radius,
                max(1, self._s(2)),
            )
        elif kind == "arc":
            pygame.draw.arc(
                surface, color,
                (cx - radius, cy - radius, radius * 2, radius * 2),
                math.pi * 0.15, math.pi * 0.85,
                max(1, self._s(2)),
            )
        elif kind == "slot":
            pygame.draw.rect(
                surface, color,
                (cx - radius, cy - radius // 2,
                 radius * 2, radius),
                max(1, self._s(2)),
                border_radius=max(1, radius // 2),
            )
        elif kind == "polygon":
            points = [
                (
                    cx + int(radius * math.cos(
                        -math.pi / 2 + index * math.pi / 3
                    )),
                    cy + int(radius * math.sin(
                        -math.pi / 2 + index * math.pi / 3
                    )),
                )
                for index in range(6)
            ]
            pygame.draw.polygon(
                surface, color, points, max(1, self._s(2))
            )
        elif kind == "spline":
            pygame.draw.lines(
                surface, color, False,
                [
                    (cx - radius, cy + radius // 2),
                    (cx - radius // 2, cy - radius // 2),
                    (cx, cy + radius // 2),
                    (cx + radius, cy - radius // 2),
                ],
                max(1, self._s(2)),
            )
        elif kind == "fillet":
            pygame.draw.lines(
                surface, color, False,
                [
                    (cx - radius, cy + radius),
                    (cx - radius, cy - radius // 3),
                    (cx, cy - radius),
                    (cx + radius, cy - radius),
                ],
                max(1, self._s(2)),
            )
        elif kind == "trim":
            pygame.draw.line(
                surface, color,
                (cx - radius, cy - radius),
                (cx + radius, cy + radius),
                max(1, self._s(2)),
            )
            pygame.draw.line(
                surface, color,
                (cx - radius, cy + radius),
                (cx + radius, cy - radius),
                max(1, self._s(2)),
            )
        elif kind == "linear_pattern":
            square = max(2, self._s(4))
            for index in range(3):
                offset = index * square
                pygame.draw.rect(
                    surface, color,
                    (cx - radius + offset, cy + radius - square - offset,
                     square, square),
                    max(1, self._s(1)),
                )
        elif kind == "circular_pattern":
            pygame.draw.circle(
                surface, color, (cx, cy), radius,
                max(1, self._s(1)),
            )
            dot = max(1, self._s(1))
            for index in range(8):
                angle = index * math.pi / 4
                point = (
                    cx + int(radius * math.cos(angle)),
                    cy + int(radius * math.sin(angle)),
                )
                pygame.draw.circle(surface, color, point, dot)
        elif kind == "constraint_vertical":
            pygame.draw.line(
                surface, color, (cx, cy - radius), (cx, cy + radius),
                max(1, self._s(2)),
            )
            pygame.draw.line(
                surface, self.text_muted,
                (cx - radius // 2, cy - radius),
                (cx + radius // 2, cy - radius),
                max(1, self._s(1)),
            )
        elif kind == "constraint_horizontal":
            pygame.draw.line(
                surface, color, (cx - radius, cy), (cx + radius, cy),
                max(1, self._s(2)),
            )
            pygame.draw.line(
                surface, self.text_muted,
                (cx - radius, cy - radius // 2),
                (cx - radius, cy + radius // 2),
                max(1, self._s(1)),
            )
        elif kind == "constraint_perpendicular":
            pygame.draw.lines(
                surface, color, False,
                [(cx - radius, cy + radius), (cx - radius, cy - radius),
                 (cx + radius, cy - radius)],
                max(1, self._s(2)),
            )
        elif kind == "constraint_tangent":
            pygame.draw.circle(
                surface, color, (cx - radius // 2, cy + radius // 2),
                radius // 2, max(1, self._s(1)),
            )
            pygame.draw.line(
                surface, color,
                (cx - radius, cy - radius // 2),
                (cx + radius, cy - radius // 2),
                max(1, self._s(1)),
            )
        elif kind == "constraint_equal":
            for offset in (-radius // 2, radius // 2):
                pygame.draw.line(
                    surface, color,
                    (cx - radius, cy + offset),
                    (cx + radius, cy + offset),
                    max(1, self._s(2)),
                )
        elif kind == "constraint_midpoint":
            pygame.draw.line(
                surface, color, (cx - radius, cy), (cx + radius, cy),
                max(1, self._s(1)),
            )
            pygame.draw.circle(
                surface, color, (cx, cy), max(1, self._s(2))
            )
        elif kind == "measure":
            pygame.draw.rect(
                surface, color,
                (cx - radius, cy - radius // 2,
                 radius * 2, radius),
                max(1, self._s(1)), border_radius=self._s(1),
            )
            for index in range(3):
                tick_x = cx - radius + (index + 1) * radius * 2 // 4
                pygame.draw.line(
                    surface, color,
                    (tick_x, cy - radius // 2),
                    (tick_x, cy),
                    max(1, self._s(1)),
                )
        elif kind == "section_view":
            pygame.draw.circle(
                surface, color, (cx - 1, cy - 1), radius - 2,
                max(1, self._s(2)),
            )
            pygame.draw.line(
                surface, color,
                (cx + radius // 2, cy + radius // 2),
                (cx + radius, cy + radius),
                max(1, self._s(2)),
            )
        elif kind == "insert_part":
            pygame.draw.rect(
                surface, color,
                (cx - radius, cy - radius // 2,
                 radius, radius),
                max(1, self._s(1)),
            )
            pygame.draw.lines(
                surface, color, False,
                [(cx + radius // 2, cy - radius),
                 (cx + radius, cy - radius // 2),
                 (cx + radius // 2, cy)],
                max(1, self._s(1)),
            )
        elif kind == "insert_sketch":
            pygame.draw.rect(
                surface, color,
                (cx - radius, cy - radius,
                 radius * 2, radius * 2),
                max(1, self._s(1)),
            )
            pygame.draw.line(
                surface, color, (cx, cy - radius // 2), (cx, cy + radius // 2),
                max(1, self._s(1)),
            )
            pygame.draw.line(
                surface, color, (cx - radius // 2, cy), (cx + radius // 2, cy),
                max(1, self._s(1)),
            )
        elif kind == "select":
            pygame.draw.polygon(surface, color, [
                (cx - radius, cy - radius),
                (cx - radius, cy + radius),
                (cx - radius // 3, cy + radius // 3),
                (cx + radius, cy + radius // 2),
            ])

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

        # A click outside the open line-style menu dismisses it without
        # activating the control underneath.
        if (
            self._line_menu_open
            and event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
        ):
            geometry = self._line_menu_geometry(layout.toolbar, document)
            if geometry is not None:
                panel, item_rects, caret = geometry
                if panel.collidepoint(event.pos):
                    for index, rect in enumerate(item_rects):
                        if rect.collidepoint(event.pos):
                            self._choose_line_type(index, document)
                            break
                    return True
                if caret is not None and caret.collidepoint(event.pos):
                    self._line_menu_open = False
                    self._line_menu_hover = -1
                    return True
            self._line_menu_open = False
            self._line_menu_hover = -1
            return True

        # Commit a point drag before any panel can consume the release.
        if (
            event.type == pygame.MOUSEBUTTONUP
            and event.button == 1
            and self._drag_point_index is not None
        ):
            self._finish_point_drag(document)
            return True

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
                    self._selected_tool = None
                    self._reset_line_state()
                    self._clear_sketch_selection()
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
            for mode, rect in self._mode_rects(layout.toolbar, document):
                if not rect.collidepoint(event.pos):
                    continue
                previous_mode = self._active_mode_name
                self._active_mode_name = mode
                self._hover_mode = None
                if (
                    previous_mode == self.SKETCH_MODE
                    and mode != self.SKETCH_MODE
                ):
                    # Keep the sketch open, but do not leave a hidden sketch
                    # tool armed while another mode is visible.
                    self._selected_tool = None
                    self._reset_line_state()
                    self._clear_sketch_selection()
                return True
            if self._settings_rect(layout.toolbar).collidepoint(event.pos):
                if self.on_settings is not None:
                    self.on_settings()
                return True
            if self._sketch_toolbar_visible(document):
                if self._handle_sketch_toolbar_click(
                    event.pos, layout.toolbar, document
                ):
                    return True
            else:
                for action, rect, enabled in self._toolbar_buttons(
                    layout.toolbar, document
                ):
                    if enabled and rect.collidepoint(event.pos):
                        self._run_tool(action, document)
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
                            self._selected_tool = None
                            self._reset_line_state()
                            self._clear_sketch_selection()
                        return True
                    if kind == "sketch":
                        self.on_select_sketch(item_id)
                        return True
                if not hit_row:
                    document.selected_plane = None
                    document.selected_face = None
                    return True

        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self._sketch_toolbar_visible(document)
            and layout.viewport.collidepoint(event.pos)
        ):
            sketch = document.sketch(document.active_sketch_id)
            if sketch is not None:
                point_hit = self._pick_sketch_point(
                    event.pos, layout.viewport, sketch
                )
                if not (
                    self._selected_tool == "line"
                    and point_hit is not None
                ):
                    hit = self._pick_sketch_entity(
                        event.pos, layout.viewport, sketch
                    )
                    if hit is not None:
                        kind, index = hit
                        self._clear_sketch_selection()
                        self._selected_sketch_entity = hit
                        self._hover_sketch_entity = hit
                        self._reset_line_state()
                        if kind == "point":
                            self._drag_point_index = index
                            self._drag_point_origin = sketch.points[index]
                            self._drag_point_current = sketch.points[index]
                        return True
                    self._clear_sketch_selection()

        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self._selected_tool == "line"
            and self._sketch_toolbar_visible(document)
            and layout.viewport.collidepoint(event.pos)
        ):
            sketch = document.sketch(document.active_sketch_id)
            if sketch is not None:
                point: Optional[Point] = None
                snap_index = self._pick_sketch_point(
                    event.pos, layout.viewport, sketch
                )
                if snap_index is not None:
                    point = sketch.points[snap_index]
                else:
                    world = self.viewport.unproject_on_plane(
                        event.pos, layout.viewport, sketch.frame()
                    )
                    if world is not None:
                        point = (round(world[0]), round(world[1]))
                if point is not None:
                    self._clear_sketch_selection()
                    if self._line_start is None:
                        self._line_start = point
                    elif point != self._line_start:
                        self.on_add_line(self._line_start, point)
                        self._line_start = point
                    self._line_preview = point
                return True

        add_point = (
            self.on_add_point
            if (
                self._selected_tool == "point"
                and self._sketch_toolbar_visible(document)
            )
            else None
        )
        handled = self.viewport.handle_event(
            event, layout.viewport, document, add_point
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
        # Find the matching visible entry in full_history.
        match_count = 0
        for i, entry in enumerate(full_history):
            if not entry.timeline_visible:
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
        # Count timeline-visible entries up to (but not including) full_position.
        return sum(
            1
            for entry in full_history[:full_position]
            if entry.timeline_visible
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
                self._run_history_control(
                    action, full_history, position
                )
                return True

        for index, rect in enumerate(boxes):
            if rect.collidepoint(pos):
                full_index = self._filtered_to_full_index(index, history, full_history)
                self._selected_action = index
                self.on_history_jump(
                    self._visible_action_end_position(
                        full_history, full_index
                    )
                )
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

    def _run_history_control(
        self, action: str, full_history: List[HistoryEntry], position: int
    ) -> None:
        total = len(full_history)
        if action == "start":
            self.on_history_jump(0)
        elif action == "prev":
            self.on_history_jump(
                self._previous_visible_jump(full_history, position)
            )
        elif action == "play":
            self.on_history_play()
        elif action == "next":
            self.on_history_jump(
                self._next_visible_jump(full_history, position)
            )
        elif action == "end":
            self.on_history_jump(total)

    def _previous_visible_jump(
        self, full_history: List[HistoryEntry], position: int
    ) -> int:
        """Target position after undoing the previous visible action."""
        for index in range(min(position, len(full_history)) - 1, -1, -1):
            if full_history[index].timeline_visible:
                return index
        return 0

    def _next_visible_jump(
        self, full_history: List[HistoryEntry], position: int
    ) -> int:
        """Target position after applying the next visible action."""
        for index in range(min(position, len(full_history)), len(full_history)):
            if full_history[index].timeline_visible:
                return index + 1
        return len(full_history)

    def _visible_action_end_position(
        self, full_history: List[HistoryEntry], action_index: int
    ) -> int:
        """State after an action, including its hidden sketch edits."""
        for index in range(action_index + 1, len(full_history)):
            if full_history[index].timeline_visible:
                return index
        return len(full_history)

    def _finish_point_drag(self, document: Document) -> None:
        index = self._drag_point_index
        current = self._drag_point_current
        self._drag_point_index = None
        self._drag_point_origin = None
        self._drag_point_current = None
        if index is None or current is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.points):
            return
        if sketch.points[index] == current:
            return
        self.on_move_point(index, current)

    def _run_tool(self, action: str, document: Document) -> None:
        if action == "sketch":
            self.on_new_sketch()
        elif action == "extrude":
            self.on_extrude()
        elif action == "finish_sketch":
            document.active_sketch_id = None
            self._selected_tool = None
            self._reset_line_state()
            self._clear_sketch_selection()
            self.sketch_palette_window.close()

    def _update_hover(
        self, pos: Tuple[int, int], layout: UILayout,
        document: Document, history: List[HistoryEntry], position: int,
    ) -> None:
        self._mouse_pos = pos
        self._hover_tool = None
        self._hover_mode = None
        self._hover_sketch = None
        self._hover_plane = None
        self._hover_control = None
        self._hover_action = None
        self._hover_origin = False
        self._hover_origin_eye = False
        self._hover_sketches_folder = False
        self._hover_sketch_entity = None
        if self._line_menu_open:
            self._line_menu_hover = self._line_menu_index_at(
                pos, layout.toolbar, document
            )
        else:
            self._line_menu_hover = -1
        sketch = document.sketch(document.active_sketch_id)
        if self._drag_point_index is not None and sketch is not None:
            if layout.viewport.collidepoint(pos):
                world = self.viewport.unproject_on_plane(
                    pos, layout.viewport, sketch.frame()
                )
                if world is not None:
                    self._drag_point_current = (
                        round(world[0]), round(world[1])
                    )
            self._hover_sketch_entity = (
                "point", self._drag_point_index
            )
            self._line_preview = None
            return
        if (
            self._selected_tool == "line"
            and sketch is not None
            and layout.viewport.collidepoint(pos)
        ):
            snap_index = self._pick_sketch_point(
                pos, layout.viewport, sketch
            )
            if snap_index is not None:
                self._line_preview = sketch.points[snap_index]
            else:
                world = self.viewport.unproject_on_plane(
                    pos, layout.viewport, sketch.frame()
                )
                self._line_preview = (
                    (round(world[0]), round(world[1]))
                    if world is not None
                    else None
                )
        else:
            self._line_preview = None
        if self.create_sketch_window.update_hover(pos, layout.viewport):
            return
        self._hover_settings = self._settings_rect(
            layout.toolbar
        ).collidepoint(pos)
        for mode, rect in self._mode_rects(layout.toolbar, document):
            if rect.collidepoint(pos):
                self._hover_mode = mode
                break
        if self._sketch_toolbar_visible(document):
            for group in self._sketch_toolbar_groups(
                layout.toolbar, document
            ):
                if group.finish and group.rect.collidepoint(pos):
                    self._hover_tool = "finish_sketch"
                    break
                for item in group.items:
                    if item.action not in ("line", "point"):
                        continue
                    if self._toolbar_item_hit_rect(item).collidepoint(pos):
                        self._hover_tool = item.action
                        break
                if self._hover_tool is not None:
                    break
        else:
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

        if (
            sketch is not None
            and self._sketch_toolbar_visible(document)
            and layout.viewport.collidepoint(pos)
        ):
            self._hover_sketch_entity = self._pick_sketch_entity(
                pos, layout.viewport, sketch
            )

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
