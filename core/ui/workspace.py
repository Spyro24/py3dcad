"""Document workspace drawing for PY3DCAD."""

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Set, Tuple

import pygame

from ..document import Document
from ..faces import Edge, Face, edge_for_ref
from ..preview import ExtrudePreview, FilletPreview
from ..profiles import (
    build_regions, intersect_loops, loop_cuts_selection, point_in_polygon,
    union_profiles,
)
from ..render.camera import PROJECTION_SCALE
from ..sketch import (
    Measurement,
    Point,
    Sketch,
    aligned_edge_endpoint,
    point_on_plane,
)
from .layout import Rect, UILayout
from .tool_properties import (
    ExtrudeWindow,
    ExtrudeWindowAction,
    FilletWindow,
    FilletWindowAction,
    SketchPaletteAction,
    SketchPaletteWindow,
    ToolPropertiesWindow,
    ToolWindowAction,
)
from .viewport import Viewport


@dataclass
class HistoryEntry:
    """One action in the document history."""

    kind: str
    label: str
    timeline_visible: bool = True


ARROW_SNAP_PIXELS = 3.0
MEASURE_DOUBLE_CLICK_MS = 400
MEASURE_DOUBLE_CLICK_PIXELS = 6.0


def _arrow_snap_step(world_per_pixel: float) -> float:
    """Choose a round arrow step that stays aimable at the current zoom.

    When the view is zoomed out one pixel covers a large distance, so a
    continuous drag jumps through many values.  A coarser round step makes
    the handle land on readable values instead.
    """
    target = max(world_per_pixel, 1e-6) * ARROW_SNAP_PIXELS
    exponent = 10.0 ** math.floor(math.log10(target))
    for factor in (1.0, 2.0, 5.0, 10.0):
        step = factor * exponent
        if step >= target:
            return step
    return 10.0 * exponent


def _snap_to_step(value: float, step: float) -> float:
    """Round a value to the nearest multiple of ``step``."""
    if step <= 1e-9:
        return value
    return math.copysign(
        math.floor(abs(value) / step + 0.5) * step, value
    )


@dataclass
class _ExtrudeArrowDrag:
    """Screen and model anchors captured when an extrude drag starts."""

    start_pos: Tuple[int, int]
    base_height: float
    base_half: float
    screen_axis: Tuple[float, float]
    symmetric: bool
    snap_step: float


@dataclass
class _FilletArrowDrag:
    """Screen anchors captured when a fillet radius drag starts."""

    start_pos: Tuple[int, int]
    base_radius: float
    screen_axis: Tuple[float, float]
    snap_step: float


@dataclass
class ToolbarItem:
    """One button inside a grouped sketch toolbar."""

    action: str
    rect: pygame.Rect
    label: Optional[str] = None
    placeholder: bool = False
    dropdown: bool = False
    enabled: bool = True


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
        "rectangle": "Rectangle",
        "circle": "Circle",
        "point": "Point",
        "project": "Project",
        "align_x": "Align Sketch X",
        "finish_sketch": "Finish Sketch",
        "extrude": "Extrude",
        "fillet": "Fillet",
        "constraint_auto": "Auto Constraint",
        "constraint_coincident": "Coincident",
        "measure": "Auto Measurement",
    }
    TOOL_SHORTCUTS = {"sketch": "S", "extrude": "E"}
    SOLID_GROUPS = (
        ("CREATE", ("sketch", "extrude")),
        ("MODIFY", ("fillet",)),
    )
    FILLET_RADIUS = 2.0
    SKETCH_CONSTRAINT_ACTIONS = (
        "constraint_auto", "constraint_coincident", "measure",
    )
    SKETCH_INTERACTIVE_ACTIONS = (
        "line", "rectangle", "circle", "point", "project", "align_x",
        *SKETCH_CONSTRAINT_ACTIONS
    )
    MODES = ("SOLID", "SURFACE", "MESH", "SHEET METAL", "PLASTIC", "UTILITIES")
    ACTIVE_MODE = "SOLID"
    SKETCH_MODE = "SKETCH"
    ORIGIN_PLANES = ("XY Plane", "YZ Plane", "ZX Plane")
    ORIGIN_PLANE_KEYS = ("XY", "YZ", "ZX")

    # Caption, (action, visible label, dropdown caret)
    SKETCH_GROUPS = (
        ("CREATE", (
            ("line", "Line", True),
            ("rectangle", "Rectangle", False),
            ("circle", "Circle", True),
            ("arc", "Arc", True),
            ("slot", "Slot", True),
            ("polygon", "Polygon", True),
            ("spline", "Spline", True),
            ("point", "Point", False),
            ("project", "Project", False),
            ("align_x", "Align X", False),
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
            ("constraint_auto", "V/H", True),
            ("constraint_coincident", "Coincident", False),
            ("measure", "Measure", True),
        )),
        ("INSPECT", (
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
    ACTIVE_SKETCH_TOOLS = (
        "line", "rectangle", "point", "project", "align_x", "measure",
        "finish_sketch",
    )
    LINE_MENU_ITEMS = (
        ("normal", "Line"),
        ("construction", "Construction Line"),
        ("center", "Centerline"),
    )
    CONSTRAINT_MENU_ITEMS = (
        ("vertical", "Vertical Only"),
        ("horizontal", "Horizontal Only"),
    )
    MEASURE_MENU_ITEMS = (
        ("angle", "Angle Only"),
        ("distance", "Distance Only"),
        ("diameter", "Diameter Only"),
    )

    def __init__(
        self,
        on_new_sketch: Callable[[], None],
        on_extrude: Callable[..., Optional[str]],
        on_add_point: Callable[[Point], None],
        on_add_line: Callable[[Point, Point, Optional[str]], None],
        on_add_circle: Callable[[Point, float], None],
        on_add_rectangle: Callable[[Point, Point], None],
        on_move_point: Callable[[int, Point], None],
        on_move_edge: Callable[[int, Point, Point], None],
        on_set_edge_constraint: Callable[[int, str], None],
        on_add_coincident: Callable[
            [Tuple[str, int], Tuple[str, int]], None
        ],
        on_select_sketch: Callable[[int], None],
        on_history_jump: Callable[[int], None],
        on_history_delete: Callable[[int], None],
        on_history_play: Callable[[], None],
        on_settings: Optional[Callable[[], None]] = None,
        on_add_measurement: Optional[
            Callable[
                [
                    str,
                    Tuple[str, int],
                    Tuple[str, int],
                    Optional[float],
                    Optional[float],
                ],
                None,
            ]
        ] = None,
        on_set_measurement_placement: Optional[
            Callable[[int, float], None]
        ] = None,
        on_set_measurement_value: Optional[
            Callable[[int, float], None]
        ] = None,
        on_fillet: Optional[
            Callable[[float], Optional[str]]
        ] = None,
        on_delete_sketch: Optional[
            Callable[[Optional[Tuple[str, int]], List[List[int]]], bool]
        ] = None,
        on_project_point: Optional[
            Callable[[int, Tuple[float, float, float]], None]
        ] = None,
        on_project_edge: Optional[
            Callable[[int, int], None]
        ] = None,
        on_align_sketch_x: Optional[
            Callable[[int, int], None]
        ] = None,
    ) -> None:
        self.on_new_sketch = on_new_sketch
        self.on_extrude = on_extrude
        self.on_add_point = on_add_point
        self.on_add_line = on_add_line
        self.on_add_circle = on_add_circle
        self.on_add_rectangle = on_add_rectangle
        self.on_move_point = on_move_point
        self.on_move_edge = on_move_edge
        self.on_set_edge_constraint = on_set_edge_constraint
        self.on_add_coincident = on_add_coincident
        self.on_select_sketch = on_select_sketch
        self.on_history_jump = on_history_jump
        self.on_history_delete = on_history_delete
        self.on_history_play = on_history_play
        self.on_settings = on_settings
        self.on_add_measurement = on_add_measurement
        self.on_set_measurement_placement = (
            on_set_measurement_placement
        )
        self.on_set_measurement_value = on_set_measurement_value
        self.on_fillet = on_fillet
        self.on_delete_sketch = on_delete_sketch
        self.on_project_point = on_project_point
        self.on_project_edge = on_project_edge
        self.on_align_sketch_x = on_align_sketch_x

        self.scale = 1.0
        self.viewport = Viewport()
        self._hover_tool: Optional[str] = None
        self._hover_mode: Optional[str] = None
        self._active_mode_name = self.ACTIVE_MODE
        self._selected_tool: Optional[str] = None
        self._line_start: Optional[Point] = None
        self._line_preview: Optional[Point] = None
        self._circle_center: Optional[Point] = None
        self._circle_preview: Optional[Tuple[Point, float]] = None
        self._rectangle_start: Optional[Point] = None
        self._rectangle_preview: Optional[Point] = None
        self._line_menu_open = False
        self._line_menu_hover = -1
        self._constraint_menu_open = False
        self._constraint_menu_hover = -1
        self._constraint_tool: Optional[str] = None
        self._measure_menu_open = False
        self._measure_menu_hover = -1
        self._measure_tool: Optional[str] = None
        self._measure_selection: List[Tuple[str, int]] = []
        self._measure_click_time = 0
        self._measure_click_pos: Optional[Tuple[int, int]] = None
        self._measure_click_hit: Optional[Tuple[str, int]] = None
        self._coincident_selection: List[Tuple[str, int]] = []
        self._measurement_label_rects: List[
            Tuple[int, pygame.Rect]
        ] = []
        self._hover_measurement_index: Optional[int] = None
        self._drag_measurement_index: Optional[int] = None
        self._drag_measurement_original: Optional[float] = None
        self._drag_measurement_current: Optional[float] = None
        self._drag_measurement_grab_delta = 0.0
        self._drag_measurement_start_pos: Optional[Tuple[int, int]] = None
        self._drag_measurement_moved = False
        self._editing_measurement_index: Optional[int] = None
        self._measurement_edit_text = ""
        self._measurement_edit_error = ""
        self._measurement_edit_rect: Optional[pygame.Rect] = None
        self._measurement_edit_pristine = False
        self._selected_sketch_entity: Optional[Tuple[str, int]] = None
        self._hover_sketch_entity: Optional[Tuple[str, int]] = None
        # Solid reference geometry previewed by the projection tool.
        self._hover_project_vertex: Optional[
            Tuple[int, Tuple[float, float, float]]
        ] = None
        self._hover_project_edge: Optional[Tuple[int, int, Edge]] = None
        # A selection is a list of arrangement regions.  Each region is a
        # tuple of loop indices; a single loop is a one-element tuple and
        # overlapping loops form their intersection (for example a lens).
        self._selected_regions: List[Tuple[int, ...]] = []
        self._hover_region: Optional[Tuple[int, ...]] = None
        self._loop_surface: Optional[pygame.Surface] = None
        self._drag_point_index: Optional[int] = None
        self._drag_point_origin: Optional[Point] = None
        self._drag_point_current: Optional[Point] = None
        self._drag_edge_index: Optional[int] = None
        self._drag_edge_origin: Optional[Tuple[Point, Point]] = None
        self._drag_edge_anchor: Optional[Point] = None
        self._drag_edge_current: Optional[Tuple[Point, Point]] = None
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
        self.fillet_window = FilletWindow()
        self.extrude_window = ExtrudeWindow()
        self._extrude_preview: Optional[ExtrudePreview] = None
        self._extrude_arrow_drag: Optional[_ExtrudeArrowDrag] = None
        self._fillet_preview: Optional[FilletPreview] = None
        self._fillet_arrow_drag: Optional[_FilletArrowDrag] = None
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
        self.error_color = pygame.Color(235, 100, 100)

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
        self._measurement_label_rects.clear()
        self._hover_measurement_index = None
        self._drag_measurement_index = None
        self._drag_measurement_original = None
        self._drag_measurement_current = None
        self._drag_measurement_grab_delta = 0.0
        self._drag_measurement_start_pos = None
        self._drag_measurement_moved = False
        self._editing_measurement_index = None
        self._measurement_edit_text = ""
        self._measurement_edit_error = ""
        self._measurement_edit_rect = None
        self._measurement_edit_pristine = False
        self.create_sketch_window.set_scale(scale)
        self.sketch_palette_window.set_scale(scale)
        self.fillet_window.set_scale(scale)
        self.extrude_window.set_scale(scale)
        self._font_label = None
        self._font_small = None
        self._font_tab = None
        self._font_caption = None

    def set_orientation_cube_visible(self, visible: bool) -> None:
        self.viewport.show_orientation_cube = bool(visible)

    def fillet_preview_radius(self) -> Optional[float]:
        """Return the radius to preview, or None when no fillet is open."""
        if not self.fillet_window.visible:
            return None
        return self.fillet_window.radius()

    @staticmethod
    def _fillet_label(document: Document) -> str:
        """Describe how many edges the fillet panel will act on."""
        count = len(document.selected_edges)
        if count == 0:
            return "No edge selected"
        if count == 1:
            return "Edge selected"
        return f"{count} edges selected"

    def open_extrude(self, document: Document) -> bool:
        """Open the extrude property panel for the current sketch selection."""
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return False
        regions = self.selected_regions(sketch)
        if not regions:
            return False
        self.create_sketch_window.close()
        self.fillet_window.close()
        self._extrude_arrow_drag = None
        self._extrude_preview = None
        # A sketch drawn on a face is normally a modification of the body
        # under it, so start with Join instead of creating a second body.
        self.extrude_window.operation = (
            "join" if sketch.is_custom_plane else "new_body"
        )
        self.extrude_window.open(len(regions))
        return True

    def _apply_extrude(self, document: Document) -> None:
        """Read the panel values and send them to the model."""
        window = self.extrude_window
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            window.set_error("Open a sketch to extrude")
            return
        regions = self.selected_regions(sketch)
        if not regions:
            window.set_error("Select at least one profile")
            return
        distance = window.distance_value()
        if distance is None:
            window.set_error("Enter a distance greater than zero")
            return
        if self.on_extrude is None:
            window.set_error("Extrude is unavailable")
            return
        symmetric = window.is_symmetric()
        height = distance if symmetric or not window.reverse else -distance
        start = -distance * 0.5 if symmetric else 0.0
        error = self.on_extrude(
            regions=regions,
            cuts=self.selected_cut_profiles(sketch),
            height=height,
            start=start,
            operation=window.operation,
            taper=window.taper_value() or 0.0,
        )
        if error:
            window.set_error(error)
            return
        window.close()
        self._extrude_arrow_drag = None
        self._extrude_preview = None

    def set_origin_visible(self, visible: bool) -> None:
        """Show or hide the origin planes, axes and marker."""
        self._origin_visible = bool(visible)
        self.viewport.set_origin_visible(self._origin_visible)

    def begin_sketch_edit(self) -> None:
        """Start sketch editing with the point tool selected."""
        self._active_mode_name = self.SKETCH_MODE
        self.fillet_window.close()
        self._selected_tool = "point"
        self._constraint_tool = None
        self._clear_measure_state()
        self._reset_line_state()
        self._clear_sketch_selection()

    def deselect_tool(self) -> None:
        """Clear the current sketch tool without leaving sketch mode."""
        self._selected_tool = None
        self._constraint_tool = None
        self._clear_measure_state()
        self._reset_line_state()
        self._clear_sketch_selection()

    def _clear_measure_state(self) -> None:
        """Stop the measurement tool and discard pending entity picks."""
        self._measure_tool = None
        self._measure_selection.clear()
        self._coincident_selection.clear()
        self._reset_measure_click()
        self._measure_menu_open = False
        self._measure_menu_hover = -1
        self._drag_measurement_index = None
        self._drag_measurement_original = None
        self._drag_measurement_current = None
        self._drag_measurement_grab_delta = 0.0
        self._drag_measurement_start_pos = None
        self._drag_measurement_moved = False
        self._editing_measurement_index = None
        self._measurement_edit_text = ""
        self._measurement_edit_error = ""
        self._measurement_edit_rect = None
        self._measurement_edit_pristine = False

    def _clear_sketch_selection(self) -> None:
        self._selected_sketch_entity = None
        self._hover_sketch_entity = None
        self._selected_regions.clear()
        self._hover_region = None
        self._drag_point_index = None
        self._drag_point_origin = None
        self._drag_point_current = None
        self._drag_edge_index = None
        self._drag_edge_origin = None
        self._drag_edge_anchor = None
        self._drag_edge_current = None

    def delete_sketch_selection(self, document: Document) -> bool:
        """Delete the selected point, edge, circle or closed profile."""
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return False
        entity = self._selected_sketch_entity
        if entity is not None:
            kind, index = entity
            limit = self._sketch_entity_limit(sketch, kind)
            if limit is None or not 0 <= index < limit:
                entity = None
        if entity is None and self.on_delete_sketch is None:
            return False
        loops = sketch.closed_loops()
        chosen = set()
        for region in self._valid_selected_regions(sketch):
            valid = [
                index for index in region if 0 <= index < len(loops)
            ]
            if not valid:
                continue
            # A click inside nested loops selects their arrangement region.
            # Deleting the innermost loop removes the object under the
            # cursor instead of the container around it.
            chosen.add(
                min(valid, key=lambda index: sketch.loop_area(loops[index]))
            )
        targets = [list(loops[index]) for index in sorted(chosen)]
        if entity is None and not targets:
            return False
        if self.on_delete_sketch is None:
            return False
        if not self.on_delete_sketch(entity, targets):
            return False
        self._clear_sketch_selection()
        self._clear_measure_state()
        return True

    def _select_sketch_region(
        self, region: Tuple[int, ...], mods: int
    ) -> None:
        """Select or Ctrl-toggle an arrangement region of sketch loops."""
        if mods & pygame.KMOD_CTRL:
            if region in self._selected_regions:
                self._selected_regions.remove(region)
            else:
                self._selected_regions.append(region)
            self._selected_sketch_entity = None
            self._hover_sketch_entity = None
        else:
            self._clear_sketch_selection()
            self._selected_regions = [region]
            self._hover_region = region
        self._reset_line_state()

    def _reset_line_state(self) -> None:
        self._line_start = None
        self._line_preview = None
        self._circle_center = None
        self._circle_preview = None
        self._rectangle_start = None
        self._rectangle_preview = None
        self._line_menu_open = False
        self._line_menu_hover = -1
        self._constraint_menu_open = False
        self._constraint_menu_hover = -1
        self._measure_menu_open = False
        self._measure_menu_hover = -1

    def _select_tool(self, tool: Optional[str]) -> None:
        self._selected_tool = tool
        self._constraint_tool = None
        self._clear_measure_state()
        self._reset_line_state()
        self._clear_sketch_selection()

    def _auto_constraints_enabled(self) -> bool:
        """Return whether new lines snap automatically to the axes."""
        return (
            self._constraint_tool not in ("vertical", "horizontal")
            and self.sketch_palette_window.options.get("constraints", True)
        )

    def _set_auto_constraints(self, enabled: bool) -> None:
        """Enable or disable automatic axis snapping."""
        self.sketch_palette_window.options["constraints"] = enabled

    def open_create_sketch_dialog(self) -> None:
        """Ask the user to choose a plane before creating a sketch."""
        self.fillet_window.close()
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
        document.selected_edge = None
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
        preview_document: Optional[Document] = None,
        ghost_faces: Sequence[Face] = (),
        extrude_preview: Optional[ExtrudePreview] = None,
        fillet_preview: Optional[FilletPreview] = None,
    ) -> None:
        self._init_fonts()
        self._sync_history_document(document)
        self._extrude_preview = extrude_preview
        self._fillet_preview = fillet_preview
        self.fillet_window.set_radius_limit(
            fillet_preview.max_radius if fillet_preview else None
        )
        self._draw_toolbar(surface, layout.toolbar, document)
        self._draw_tree(surface, layout.document_tree, document)
        highlight: Tuple[int, ...] = ()
        if extrude_preview is not None:
            highlight = extrude_preview.highlight
        self.viewport.draw(
            surface,
            layout.viewport,
            document,
            "extrude" if self.extrude_window.visible else self._selected_tool,
            len(self._valid_selected_regions(
                document.sketch(document.active_sketch_id)
            )),
            preview_document=preview_document,
            ghost_faces=ghost_faces,
            highlight_features=highlight,
        )
        self._draw_sketch_loops(surface, layout.viewport, document)
        self._draw_line_preview(surface, layout.viewport, document)
        self._draw_rectangle_preview(surface, layout.viewport, document)
        self._draw_circle_preview(surface, layout.viewport, document)
        self._draw_sketch_selection(surface, layout.viewport, document)
        self._draw_projection_hover(surface, layout.viewport)
        self._draw_extrude_arrow(surface, layout.viewport)
        self._draw_fillet_arrow(surface, layout.viewport)
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
            if self.extrude_window.visible:
                self.extrude_window.set_profile_count(
                    len(self.selected_regions(active_sketch))
                )
                self.extrude_window.draw(surface, layout.viewport)
            else:
                self.sketch_palette_window.draw(surface, layout.viewport)
        else:
            if self.extrude_window.visible:
                self.extrude_window.close()
            self.create_sketch_window.draw(surface, layout.viewport)
            self.fillet_window.set_edge_label(
                self._fillet_label(document)
            )
            self.fillet_window.draw(surface, layout.viewport)
        self._draw_line_menu(surface, layout.toolbar, document)
        self._draw_constraint_menu(surface, layout.toolbar, document)
        self._draw_measure_menu(surface, layout.toolbar, document)

    def _draw_dropdown_panel(
        self,
        surface: pygame.Surface,
        geometry: Tuple[Rect, List[pygame.Rect], Optional[pygame.Rect]],
        items: Tuple[Tuple[str, str], ...],
        hover: int,
        selected_key: Optional[str],
    ) -> None:
        panel, rows, _ = geometry
        pygame.draw.rect(
            surface, self.panel_bg, panel, border_radius=self._s(6)
        )
        pygame.draw.rect(
            surface, self.border_color, panel, width=1,
            border_radius=self._s(6),
        )
        for index, ((key, label), rect) in enumerate(zip(items, rows)):
            hovered = index == hover
            selected = key == selected_key
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
            text = self._font_small.render(label, True, color)
            surface.blit(
                text,
                text.get_rect(
                    midleft=(rect.x + self._s(12), rect.centery)
                ),
            )

    def _draw_constraint_menu(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        if not self._constraint_menu_open:
            return
        geometry = self._constraint_menu_geometry(region, document)
        if geometry is None:
            return
        self._draw_dropdown_panel(
            surface, geometry, self.CONSTRAINT_MENU_ITEMS,
            self._constraint_menu_hover, self._constraint_tool,
        )

    def _draw_measure_menu(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        if not self._measure_menu_open:
            return
        geometry = self._measure_menu_geometry(region, document)
        if geometry is None:
            return
        self._draw_dropdown_panel(
            surface, geometry, self.MEASURE_MENU_ITEMS,
            self._measure_menu_hover, self._measure_tool,
        )

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
            self._constraint_tool = None
            self._clear_measure_state()
            self._reset_line_state()
            self._clear_sketch_selection()
            self.close_create_sketch_dialog()
        if document.active_sketch_id != self._selection_sketch_id:
            self._selection_sketch_id = document.active_sketch_id
            self._constraint_tool = None
            self._clear_measure_state()
            self._reset_line_state()
            self._clear_sketch_selection()
        active = document.sketch(document.active_sketch_id)
        if active is None:
            self._selected_tool = None
            self._constraint_tool = None
            self._clear_measure_state()
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
            limit = self._sketch_entity_limit(sketch, kind)
            if limit is None or not 0 <= index < limit:
                self._clear_sketch_selection()
        hovered = self._hover_sketch_entity
        if hovered is not None:
            kind, index = hovered
            limit = self._sketch_entity_limit(sketch, kind)
            if limit is None or not 0 <= index < limit:
                self._hover_sketch_entity = None
        if (
            self._drag_point_index is not None
            and not 0 <= self._drag_point_index < len(sketch.points)
        ):
            self._clear_sketch_selection()
        if (
            self._drag_edge_index is not None
            and not 0 <= self._drag_edge_index < len(sketch.edges)
        ):
            self._clear_sketch_selection()
        loops = sketch.closed_loops()
        self._selected_regions = [
            tuple(index for index in region if 0 <= index < len(loops))
            for region in self._selected_regions
        ]
        self._selected_regions = [
            region for region in self._selected_regions if region
        ]
        if (
            self._hover_region is not None
            and any(
                not 0 <= index < len(loops)
                for index in self._hover_region
            )
        ):
            self._hover_region = None

    @staticmethod
    def _sketch_entity_limit(
        sketch: Sketch, kind: str
    ) -> Optional[int]:
        if kind == "point":
            return len(sketch.points)
        if kind == "line":
            return len(sketch.lines)
        return None

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

    def _solid_toolbar_groups(
        self, region: Rect, document: Document
    ) -> List[ToolbarGroupLayout]:
        """Lay out the grouped command bar for solid modelling."""
        sketch = document.sketch(document.active_sketch_id)
        enabled = {
            "sketch": True,
            "extrude": bool(self._valid_selected_regions(sketch)),
            "fillet": True,
        }
        x = self._content_x(region)
        y = region.y + self._s(42)
        width = self._s(40)
        height = self._s(38)
        gap = self._s(6)
        groups: List[ToolbarGroupLayout] = []
        for caption, actions in self.SOLID_GROUPS:
            first_x = x
            items: List[ToolbarItem] = []
            for action in actions:
                active = enabled.get(action, True)
                items.append(ToolbarItem(
                    action,
                    pygame.Rect(x, y, width, height),
                    placeholder=not active,
                    enabled=active,
                ))
                x += width + gap
            groups.append(ToolbarGroupLayout(
                caption,
                pygame.Rect(first_x, y, x - gap - first_x, height),
                items,
            ))
            x += self._s(18)
        return groups

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
            label_group = caption in ("CREATE", "CONSTRAINTS")
            finish_group = caption == "FINISH SKETCH"
            widths: List[int] = []
            for action, label, dropdown in specs:
                if label_group and not compact and label:
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
                        label
                        if (create_group or caption == "CONSTRAINTS")
                        and not compact
                        else None
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
        if not item.dropdown:
            return None
        if item.label is None:
            # Compact toolbar: use the right edge of the icon as the caret.
            return pygame.Rect(
                item.rect.right - self._s(10),
                item.rect.y,
                self._s(10),
                item.rect.h,
            )
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

    def _toolbar_dropdown_hit_rect(
        self, item: ToolbarItem
    ) -> Optional[pygame.Rect]:
        """Return the clickable label/caret area that opens a dropdown."""
        caret = self._toolbar_dropdown_rect(item)
        if caret is None:
            return None
        if item.label is None:
            return caret
        self._init_fonts()
        label_width = self._font_small.size(item.label)[0]
        height = self._font_small.get_height()
        label_rect = pygame.Rect(
            item.rect.centerx - label_width // 2,
            item.rect.bottom + self._s(8) - height // 2,
            label_width,
            height,
        )
        return label_rect.union(caret).inflate(self._s(2), self._s(2))

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

    def _constraint_toolbar_item(
        self, region: Rect, document: Document
    ) -> Optional[ToolbarItem]:
        for group in self._sketch_toolbar_groups(region, document):
            for item in group.items:
                if item.action == "constraint_auto":
                    return item
        return None

    def _constraint_menu_geometry(
        self, region: Rect, document: Document
    ) -> Optional[Tuple[Rect, List[pygame.Rect], Optional[pygame.Rect]]]:
        item = self._constraint_toolbar_item(region, document)
        if item is None:
            return None
        return self._dropdown_menu_geometry(
            item, self.CONSTRAINT_MENU_ITEMS
        )

    def _dropdown_menu_geometry(
        self,
        item: ToolbarItem,
        items: Tuple[Tuple[str, str], ...],
    ) -> Tuple[Rect, List[pygame.Rect], Optional[pygame.Rect]]:
        self._init_fonts()
        padding = self._s(6)
        row_height = self._s(28)
        max_label = max(
            self._font_small.size(label)[0]
            for _, label in items
        )
        item_count = len(items)
        width = max(item.rect.w, max_label + padding * 2)
        panel = pygame.Rect(
            item.rect.x,
            item.rect.bottom + self._s(4),
            width,
            padding * 2 + item_count * row_height,
        )
        panel.x = max(panel.x, self._s(4))
        if panel.right > self._s(1280):
            panel.x = self._s(1280) - panel.w - self._s(4)
        rows = [
            pygame.Rect(
                panel.x + padding,
                panel.y + padding + index * row_height,
                panel.w - padding * 2,
                row_height,
            )
            for index in range(item_count)
        ]
        return panel, rows, self._toolbar_dropdown_rect(item)

    def _constraint_menu_index_at(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> int:
        geometry = self._constraint_menu_geometry(region, document)
        if geometry is None:
            return -1
        _, rows, _ = geometry
        for index, rect in enumerate(rows):
            if rect.collidepoint(pos):
                return index
        return -1

    def _measure_toolbar_item(
        self, region: Rect, document: Document
    ) -> Optional[ToolbarItem]:
        for group in self._sketch_toolbar_groups(region, document):
            for item in group.items:
                if item.action == "measure":
                    return item
        return None

    def _measure_menu_geometry(
        self, region: Rect, document: Document
    ) -> Optional[Tuple[Rect, List[pygame.Rect], Optional[pygame.Rect]]]:
        item = self._measure_toolbar_item(region, document)
        if item is None:
            return None
        return self._dropdown_menu_geometry(
            item, self.MEASURE_MENU_ITEMS
        )

    def _measure_menu_index_at(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> int:
        geometry = self._measure_menu_geometry(region, document)
        if geometry is None:
            return -1
        _, rows, _ = geometry
        for index, rect in enumerate(rows):
            if rect.collidepoint(pos):
                return index
        return -1

    def _activate_measure_tool(
        self, kind: str, document: Document
    ) -> None:
        """Arm automatic, angle-only, or distance-only measurement."""
        self._measure_tool = kind
        self._constraint_tool = None
        self._selected_tool = None
        self._measure_selection.clear()
        self._reset_line_state()
        self._clear_sketch_selection()
        self._measure_menu_open = False
        self._measure_menu_hover = -1

    def _choose_measure(self, index: int, document: Document) -> None:
        if not 0 <= index < len(self.MEASURE_MENU_ITEMS):
            return
        key, _ = self.MEASURE_MENU_ITEMS[index]
        self._activate_measure_tool(key, document)

    def _activate_constraint_tool(
        self, kind: str, document: Document
    ) -> None:
        """Arm a constraint tool and apply it to the current selection."""
        self._constraint_tool = kind
        self._clear_measure_state()
        if kind == "auto":
            self._set_auto_constraints(True)
        elif kind == "coincident":
            # A selected point becomes the first half of the pair, so the
            # user only has to pick the second point (or the origin).
            selected = self._selected_sketch_entity
            if selected is not None and selected[0] == "point":
                self._coincident_selection.append(selected)
                self._selected_sketch_entity = None
        # Constraint tools replace drawing tools but keep the selection so it
        # can be constrained immediately and the next edge can be picked.
        self._selected_tool = None
        self._reset_line_state()
        self._apply_constraint_tool(document)

    def _apply_constraint_tool(self, document: Document) -> bool:
        if self._constraint_tool == "auto":
            return self._apply_auto_constraint(document)
        if self._constraint_tool in ("vertical", "horizontal"):
            return self._apply_edge_constraint(
                self._constraint_tool, document
            )
        if self._constraint_tool == "coincident":
            return self._apply_coincident(document)
        return False

    def _apply_coincident(self, document: Document) -> bool:
        """Constrain the two picked points or point/origin pair."""
        if len(self._coincident_selection) != 2:
            return False
        first, second = self._coincident_selection
        self._coincident_selection.clear()
        if self.on_add_coincident is not None:
            self.on_add_coincident(first, second)
        return True

    def _choose_constraint(self, index: int, document: Document) -> None:
        if not 0 <= index < len(self.CONSTRAINT_MENU_ITEMS):
            return
        key, _ = self.CONSTRAINT_MENU_ITEMS[index]
        self._activate_constraint_tool(key, document)
        self._constraint_menu_open = False
        self._constraint_menu_hover = -1
        document.dirty = True

    def _handle_sketch_toolbar_click(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> bool:
        for group in self._sketch_toolbar_groups(region, document):
            if group.finish and group.rect.collidepoint(pos):
                document.active_sketch_id = None
                self._selected_tool = None
                self._constraint_tool = None
                self._clear_measure_state()
                self._reset_line_state()
                self._clear_sketch_selection()
                self.sketch_palette_window.close()
                return True
            for item in group.items:
                if item.action == "constraint_auto":
                    dropdown_hit = self._toolbar_dropdown_hit_rect(item)
                    if (
                        dropdown_hit is not None
                        and dropdown_hit.collidepoint(pos)
                    ):
                        self._line_menu_open = False
                        self._measure_menu_open = False
                        self._constraint_menu_open = not self._constraint_menu_open
                        self._constraint_menu_hover = -1
                        return True
                    if item.rect.collidepoint(pos):
                        # The main V/H button arms the automatic constraint
                        # tool; selecting an edge then constrains it.
                        self._activate_constraint_tool("auto", document)
                        self._constraint_menu_open = False
                        self._constraint_menu_hover = -1
                        document.dirty = True
                        return True
                    continue
                if item.action == "constraint_coincident":
                    if item.rect.collidepoint(pos):
                        self._constraint_menu_open = False
                        self._constraint_menu_hover = -1
                        self._activate_constraint_tool(
                            "coincident", document
                        )
                        document.dirty = True
                        return True
                    continue
                if item.action == "measure":
                    dropdown_hit = self._toolbar_dropdown_hit_rect(item)
                    if (
                        dropdown_hit is not None
                        and dropdown_hit.collidepoint(pos)
                    ):
                        self._line_menu_open = False
                        self._constraint_menu_open = False
                        self._measure_menu_open = not self._measure_menu_open
                        self._measure_menu_hover = -1
                        return True
                    if item.rect.collidepoint(pos):
                        self._activate_measure_tool("auto", document)
                        return True
                    continue
                if item.action not in (
                    "line", "rectangle", "circle", "point", "project",
                    "align_x",
                ):
                    continue
                if item.action == "line":
                    caret = self._toolbar_dropdown_rect(item)
                    if caret is not None and caret.collidepoint(pos):
                        self._constraint_menu_open = False
                        self._measure_menu_open = False
                        self._line_menu_open = not self._line_menu_open
                        self._line_menu_hover = -1
                        return True
                if not self._toolbar_item_hit_rect(item).collidepoint(pos):
                    continue
                self._select_tool(item.action)
                return True
        return False

    def _apply_auto_constraint(self, document: Document) -> bool:
        """Apply horizontal or vertical to the selected edge by its angle."""
        sketch = document.sketch(document.active_sketch_id)
        selected = self._selected_sketch_entity
        if (
            sketch is None
            or selected is None
            or selected[0] != "line"
            or not 0 <= selected[1] < len(sketch.lines)
        ):
            return False
        start, end = sketch.lines[selected[1]]
        constraint = (
            "horizontal"
            if abs(end[0] - start[0]) >= abs(end[1] - start[1])
            else "vertical"
        )
        return self._apply_edge_constraint(constraint, document)

    def _apply_edge_constraint(
        self, constraint: str, document: Document
    ) -> bool:
        sketch = document.sketch(document.active_sketch_id)
        selected = self._selected_sketch_entity
        if (
            sketch is None
            or selected is None
            or selected[0] != "line"
            or constraint not in ("vertical", "horizontal")
            or not 0 <= selected[1] < len(sketch.edges)
        ):
            return False
        self.on_set_edge_constraint(selected[1], constraint)
        return True

    def _measure_click(
        self, document: Document, hit: Tuple[str, int]
    ) -> None:
        """Add an entity to the pending measurement pair."""
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        if hit[0] == "circle":
            if self._measure_tool not in ("auto", "diameter"):
                return
            self._selected_sketch_entity = None
            self._hover_sketch_entity = hit
            self._reset_line_state()
            self._commit_measurement(
                sketch, "diameter", hit, hit
            )
            return
        if self._measure_tool == "diameter":
            return
        if self._measure_tool == "angle" and hit[0] != "line":
            return
        if hit in self._measure_selection:
            self._measure_selection.remove(hit)
        else:
            if len(self._measure_selection) >= 2:
                self._measure_selection.clear()
            self._measure_selection.append(hit)
        self._selected_sketch_entity = None
        self._hover_sketch_entity = hit
        self._reset_line_state()
        if len(self._measure_selection) != 2:
            return
        first, second = self._measure_selection
        kind = self._resolve_measurement_kind(sketch, first, second)
        if kind is None:
            # Angle-only mode needs two edges with one shared vertex.
            self._measure_selection = [first]
            return
        self._commit_measurement(sketch, kind, first, second)

    def _commit_measurement(
        self,
        sketch: Sketch,
        kind: str,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> bool:
        """Freeze the current geometry into a new persistent measurement."""
        value = self._measurement_value_from_geometry(
            sketch, kind, first, second
        )
        if value is None:
            self._measure_selection.clear()
            return False
        if self.on_add_measurement is not None:
            placement = self._default_measurement_placement(
                sketch, kind, first, second
            )
            self.on_add_measurement(
                kind, first, second, placement, value
            )
        self._measure_selection.clear()
        # A completed measurement ends the click gesture, so a following
        # click cannot be mistaken for the second half of a double click.
        self._reset_measure_click()
        return True

    def _reset_measure_click(self) -> None:
        """Forget the last measure click so the next one starts a gesture."""
        self._measure_click_time = 0
        self._measure_click_pos = None
        self._measure_click_hit = None

    def _measure_is_double_click(
        self, pos: Tuple[int, int], hit: Tuple[str, int]
    ) -> bool:
        """Track measure clicks and report a fast repeat on the same entity."""
        now = pygame.time.get_ticks()
        previous_pos = self._measure_click_pos
        near = (
            previous_pos is not None
            and math.hypot(
                pos[0] - previous_pos[0], pos[1] - previous_pos[1]
            ) <= self._s(MEASURE_DOUBLE_CLICK_PIXELS)
        )
        double = (
            hit == self._measure_click_hit
            and near
            and now - self._measure_click_time <= MEASURE_DOUBLE_CLICK_MS
        )
        self._measure_click_time = now
        self._measure_click_pos = pos
        self._measure_click_hit = hit
        return double

    def _dimension_line(
        self, document: Document, hit: Tuple[str, int]
    ) -> bool:
        """Measure a line's length from its two endpoints in one gesture."""
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= hit[1] < len(sketch.edges):
            return False
        start, end = sketch.edges[hit[1]]
        if start == end:
            return False
        first = ("point", start)
        second = ("point", end)
        self._selected_sketch_entity = None
        self._hover_sketch_entity = hit
        self._reset_line_state()
        return self._commit_measurement(
            sketch, "distance", first, second
        )

    def _coincident_click(
        self,
        document: Document,
        pos: Tuple[int, int],
        region: Rect,
        sketch: Sketch,
    ) -> None:
        """Add or remove one point/origin pick for the coincident tool."""
        ref = self._pick_coincident_ref(pos, region, sketch)
        if ref is None:
            self._coincident_selection.clear()
            self._clear_sketch_selection()
            return
        if ref in self._coincident_selection:
            self._coincident_selection.remove(ref)
        else:
            if len(self._coincident_selection) >= 2:
                self._coincident_selection.clear()
            self._coincident_selection.append(ref)
        self._selected_sketch_entity = None
        self._hover_sketch_entity = (
            ref if ref[0] == "point" else None
        )
        self._reset_line_state()
        if len(self._coincident_selection) == 2:
            self._apply_coincident(document)

    def _pick_coincident_ref(
        self,
        pos: Tuple[int, int],
        region: Rect,
        sketch: Sketch,
    ) -> Optional[Tuple[str, int]]:
        """Pick a sketch point or the projected document origin."""
        index = self._pick_sketch_point(pos, region, sketch)
        if index is not None:
            return ("point", index)
        if self.viewport.show_origin:
            screen = self._project_sketch_point(
                sketch, sketch.origin_point(), region
            )
            if math.hypot(
                pos[0] - screen[0], pos[1] - screen[1]
            ) <= self._s(9):
                return ("origin", -1)
        return None

    def _resolve_measurement_kind(
        self,
        sketch: Sketch,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> Optional[str]:
        if self._measure_tool == "angle":
            return (
                "angle"
                if self._angle_geometry(sketch, first, second) is not None
                else None
            )
        if self._measure_tool == "distance":
            return "distance"
        if self._measure_tool == "diameter":
            return "diameter" if first[0] == "circle" else None
        if self._angle_geometry(sketch, first, second) is not None:
            return "angle"
        return "distance"

    def _diameter_geometry(
        self,
        sketch: Sketch,
        first: Tuple[str, int],
    ) -> Optional[Tuple[float, Point, Point]]:
        return sketch.diameter_geometry(first)

    def _angle_geometry(
        self,
        sketch: Sketch,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> Optional[Tuple[float, Point, Point, Point]]:
        return sketch.angle_geometry(first, second)

    def _distance_geometry(
        self,
        sketch: Sketch,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> Optional[Tuple[float, Point, Point]]:
        return sketch.distance_geometry(first, second)

    def _measurement_span_geometry(
        self,
        sketch: Sketch,
        kind: str,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> Optional[Tuple[float, Point, Point]]:
        """Return the two measured points for a distance-like annotation."""
        if kind == "diameter":
            return self._diameter_geometry(sketch, first)
        return self._distance_geometry(sketch, first, second)

    @staticmethod
    def _measurement_axis(
        first_point: Point, second_point: Point
    ) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
        """Return direction, left normal and length of a measured span."""
        delta_x = second_point[0] - first_point[0]
        delta_y = second_point[1] - first_point[1]
        length = math.hypot(delta_x, delta_y)
        if length <= 1e-9:
            return (1.0, 0.0), (0.0, 1.0), 0.0
        direction = (delta_x / length, delta_y / length)
        return (
            direction,
            (-direction[1], direction[0]),
            length,
        )

    @staticmethod
    def _sketch_centroid(sketch: Sketch) -> Point:
        if not sketch.points:
            return (0.0, 0.0)
        count = len(sketch.points)
        return (
            sum(point[0] for point in sketch.points) / count,
            sum(point[1] for point in sketch.points) / count,
        )

    def _measurement_value_from_geometry(
        self,
        sketch: Sketch,
        kind: str,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> Optional[float]:
        """Compute the initial value once, when a measurement is created."""
        return sketch.measurement_value(kind, first, second)

    def _default_measurement_placement(
        self,
        sketch: Sketch,
        kind: str,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> float:
        if kind == "angle":
            return self._default_angle_placement(
                sketch, first, second
            )
        return self._default_distance_placement(
            sketch, kind, first, second
        )

    def _default_distance_placement(
        self,
        sketch: Sketch,
        kind: str,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> float:
        geometry = self._measurement_span_geometry(
            sketch, kind, first, second
        )
        if geometry is None:
            return 5.0
        distance, first_point, second_point = geometry
        _, normal, _ = self._measurement_axis(
            first_point, second_point
        )
        midpoint = (
            (first_point[0] + second_point[0]) / 2,
            (first_point[1] + second_point[1]) / 2,
        )
        centroid = self._sketch_centroid(sketch)
        outward = (
            normal[0] * (midpoint[0] - centroid[0])
            + normal[1] * (midpoint[1] - centroid[1])
        )
        if abs(outward) < 1e-9:
            if abs(normal[1]) >= abs(normal[0]):
                sign = 1.0 if normal[1] >= 0 else -1.0
            else:
                sign = 1.0 if normal[0] >= 0 else -1.0
        else:
            sign = 1.0 if outward > 0 else -1.0
        magnitude = (
            5.0 if distance <= 1e-9
            else max(3.0, min(12.0, distance * 0.08))
        )
        return sign * magnitude

    def _default_angle_placement(
        self,
        sketch: Sketch,
        first: Tuple[str, int],
        second: Tuple[str, int],
    ) -> float:
        geometry = self._angle_geometry(sketch, first, second)
        if geometry is None:
            return 10.0
        _, vertex, first_point, second_point = geometry
        first_length = math.hypot(
            first_point[0] - vertex[0],
            first_point[1] - vertex[1],
        )
        second_length = math.hypot(
            second_point[0] - vertex[0],
            second_point[1] - vertex[1],
        )
        shorter = min(first_length, second_length)
        return max(5.0, min(18.0, shorter * 0.2))

    def _measurement_current_placement(
        self,
        sketch: Sketch,
        index: int,
        measurement: Measurement,
    ) -> Optional[float]:
        if (
            self._drag_measurement_index == index
            and self._drag_measurement_current is not None
        ):
            return self._drag_measurement_current
        if measurement.placement is not None:
            return measurement.placement
        return self._default_measurement_placement(
            sketch,
            measurement.kind,
            measurement.first,
            measurement.second,
        )

    def _measurement_placement_from_cursor(
        self,
        sketch: Sketch,
        index: int,
        world: Point,
    ) -> Optional[float]:
        if not 0 <= index < len(sketch.measurements):
            return None
        measurement = sketch.measurements[index]
        if measurement.kind in ("distance", "diameter"):
            geometry = self._measurement_span_geometry(
                sketch, measurement.kind,
                measurement.first, measurement.second,
            )
            if geometry is None:
                return None
            _, first_point, second_point = geometry
            _, normal, _ = self._measurement_axis(
                first_point, second_point
            )
            midpoint = (
                (first_point[0] + second_point[0]) / 2,
                (first_point[1] + second_point[1]) / 2,
            )
            return (
                (world[0] - midpoint[0]) * normal[0]
                + (world[1] - midpoint[1]) * normal[1]
            )
        if measurement.kind == "angle":
            geometry = self._angle_geometry(
                sketch, measurement.first, measurement.second
            )
            if geometry is None:
                return None
            _, vertex, _, _ = geometry
            return max(
                1.0,
                math.hypot(
                    world[0] - vertex[0],
                    world[1] - vertex[1],
                ),
            )
        return None

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
        sketch = document.sketch(document.active_sketch_id)
        selected_constraint: Optional[str] = None
        selected = self._selected_sketch_entity
        if (
            sketch is not None
            and selected is not None
            and selected[0] == "line"
            and 0 <= selected[1] < len(sketch.edges)
        ):
            selected_constraint = sketch.edge_constraint(selected[1])
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
                    item.action in (
                        "line", "rectangle", "circle", "point", "project",
                        "align_x",
                    )
                    and self._selected_tool == item.action
                ) or (
                    selected_constraint is not None
                    and item.action == f"constraint_{selected_constraint}"
                ) or (
                    item.action == "constraint_auto"
                    and self._constraint_tool in (
                        "auto", "vertical", "horizontal"
                    )
                ) or (
                    item.action == "constraint_coincident"
                    and self._constraint_tool == "coincident"
                ) or (
                    item.action == "measure"
                    and self._measure_tool is not None
                )
                item_hover = (
                    item.action in self.SKETCH_INTERACTIVE_ACTIONS
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
                elif (
                    active
                    and item.action in self.SKETCH_CONSTRAINT_ACTIONS
                ):
                    item_color = self.accent
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

    def _draw_rectangle_preview(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        if (
            self._selected_tool != "rectangle"
            or self._rectangle_start is None
            or self._rectangle_preview is None
        ):
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not self._sketch_toolbar_visible(document):
            return
        start = self._rectangle_start
        end = self._rectangle_preview
        if start[0] == end[0] or start[1] == end[1]:
            return
        corners = (
            start,
            (end[0], start[1]),
            end,
            (start[0], end[1]),
        )
        screen = [
            self._project_sketch_point(sketch, point, region)
            for point in corners
        ]
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        pygame.draw.lines(
            surface, self.accent, True, screen, self._s(2)
        )
        pygame.draw.circle(
            surface, self.accent,
            (round(screen[0][0]), round(screen[0][1])), self._s(3),
        )
        surface.set_clip(previous_clip)

    def _draw_circle_preview(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        preview = self._circle_preview
        if (
            self._selected_tool != "circle"
            or preview is None
            or not self._sketch_toolbar_visible(document)
        ):
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        center, diameter = preview
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        if diameter > 0:
            screen_points = self._circle_screen_points(
                sketch, center, diameter, region
            )
            pygame.draw.lines(
                surface, self.accent, True, screen_points, self._s(2)
            )
        screen_center = self._project_sketch_point(sketch, center, region)
        pygame.draw.circle(
            surface, self.accent,
            (round(screen_center[0]), round(screen_center[1])),
            self._s(3),
        )
        surface.set_clip(previous_clip)

    def _circle_screen_points(
        self,
        sketch: Sketch,
        center: Point,
        diameter: float,
        region: Rect,
        segments: int = 48,
    ) -> List[Tuple[float, float]]:
        radius = diameter / 2.0
        points: List[Tuple[float, float]] = []
        for index in range(segments):
            angle = 2.0 * math.pi * index / segments
            world = (
                center[0] + radius * math.cos(angle),
                center[1] + radius * math.sin(angle),
            )
            points.append(
                self._project_sketch_point(sketch, world, region)
            )
        return points

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
        for index in range(len(sketch.edges)):
            screen = [
                self._project_sketch_point(sketch, point, region)
                for point in sketch.edge_points(index)
            ]
            for screen_start, screen_end in zip(screen, screen[1:]):
                distance = self._distance_to_segment(
                    pos, screen_start, screen_end
                )
                if distance <= nearest_distance:
                    nearest_line = index
                    nearest_distance = distance
        if nearest_line is not None:
            return "line", nearest_line
        return None

    def _pick_sketch_circle(
        self, pos: Tuple[int, int], region: Rect, sketch: Sketch
    ) -> Optional[int]:
        """Return the circle under the cursor, preferring the innermost."""
        nearest: Optional[int] = None
        nearest_radius = float("inf")
        for index, circle in enumerate(sketch.circles):
            if sketch.is_projected_circle(index):
                continue
            radius = circle.diameter / 2.0
            if radius <= 0.0:
                continue
            center = self._project_sketch_point(
                sketch, circle.midPoint, region
            )
            edge = self._project_sketch_point(
                sketch,
                (
                    circle.midPoint[0] + radius,
                    circle.midPoint[1],
                ),
                region,
            )
            screen_radius = math.hypot(
                edge[0] - center[0], edge[1] - center[1]
            )
            if screen_radius <= 0.0:
                continue
            distance = math.hypot(
                pos[0] - center[0], pos[1] - center[1]
            )
            if (
                distance <= screen_radius + self._s(6)
                and screen_radius < nearest_radius
            ):
                nearest = index
                nearest_radius = screen_radius
        return nearest

    def _pick_sketch_region(
        self, pos: Tuple[int, int], region: Rect, sketch: Sketch
    ) -> Optional[Tuple[int, ...]]:
        """Return every closed loop that contains the cursor.

        The intersection of all returned loops is the arrangement region
        under the cursor.  A single loop is a plain profile; several loops
        describe an overlap such as the lens where a circle crosses a
        rectangle.  Containers are kept on purpose so that the cutters can
        exclude loops that already bound the picked region.
        """
        world = self.viewport.unproject_on_plane(
            pos, region, sketch.frame()
        )
        if world is None:
            return None
        hits: List[int] = []
        for index, loop in enumerate(sketch.closed_loops()):
            circle = sketch.circle_for_loop(loop)
            if circle is not None:
                center = circle.midPoint
                distance = math.hypot(
                    world[0] - center[0], world[1] - center[1]
                )
                if distance <= circle.radius:
                    hits.append(index)
            else:
                if point_in_polygon(world, sketch.loop_points(loop)):
                    hits.append(index)
        return tuple(hits) if hits else None

    def _circle_loop_at_point(
        self, sketch: Sketch, point_index: int
    ) -> Optional[int]:
        """Return the circle loop whose midpoint is the given point."""
        if not 0 <= point_index < len(sketch.points):
            return None
        point = sketch.points[point_index]
        for index, loop in enumerate(sketch.closed_loops()):
            circle = sketch.circle_for_loop(loop)
            if circle is not None and circle.midPoint is point:
                return index
        return None

    def selected_profiles(self, sketch: Sketch) -> List[List[int]]:
        """Return the point loops involved in the current selection.

        This is the legacy single-loop view.  Use :meth:`selected_regions`
        for extrusion so that overlapping loops keep their arrangement
        region (for example a lens) instead of being unioned.
        """
        loops = sketch.closed_loops()
        indices: Set[int] = set()
        for region in self._valid_selected_regions(sketch):
            indices.update(region)
        return [list(loops[index]) for index in sorted(indices)]

    def selected_regions(self, sketch: Sketch) -> List[List[List[int]]]:
        """Return the selected arrangement regions as lists of loops."""
        loops = sketch.closed_loops()
        regions: List[List[List[int]]] = []
        for region in self._valid_selected_regions(sketch):
            region_loops = [list(loops[index]) for index in region]
            if region_loops:
                regions.append(region_loops)
        return regions

    def selected_cut_profiles(self, sketch: Sketch) -> List[List[int]]:
        """Return unselected loops that carve material out of the selection."""
        valid = self._valid_selected_regions(sketch)
        if not valid:
            return []
        loops = sketch.closed_loops()
        selected = {index for region in valid for index in region}
        selected_polygons: List[List[Point]] = []
        for region in valid:
            selected_polygons.extend(self._region_polygons(sketch, region))
        if not selected_polygons:
            return []
        selected_union = union_profiles(selected_polygons)
        cuts: List[List[int]] = []
        for index, loop in enumerate(loops):
            if index in selected:
                continue
            polygon = sketch.loop_points(loop)
            if len(polygon) < 3:
                continue
            if loop_cuts_selection(polygon, selected_union):
                cuts.append(list(loop))
        return cuts

    def _region_polygons(
        self, sketch: Sketch, region: Tuple[int, ...]
    ) -> List[List[Point]]:
        """Return the arrangement region bounded by the given loops."""
        loops = sketch.closed_loops()
        polygons = [
            sketch.loop_points(loops[index])
            for index in region
            if 0 <= index < len(loops)
        ]
        polygons = [polygon for polygon in polygons if len(polygon) >= 3]
        if not polygons:
            return []
        return intersect_loops(polygons)

    def _face_regions(
        self, sketch: Sketch, regions: List[Tuple[int, ...]]
    ) -> List[Tuple[List[Point], List[List[Point]]]]:
        """Return ``(outer, holes)`` faces for the given arrangement regions."""
        loops = sketch.closed_loops()
        selected = {index for region in regions for index in region}
        polygons: List[List[Point]] = []
        for region in regions:
            polygons.extend(self._region_polygons(sketch, region))
        if not polygons:
            return []
        selected_union = union_profiles(polygons)
        cutters: List[List[Point]] = []
        for index, loop in enumerate(loops):
            if index in selected:
                continue
            polygon = sketch.loop_points(loop)
            if len(polygon) < 3:
                continue
            if loop_cuts_selection(polygon, selected_union):
                cutters.append(polygon)
        return build_regions(polygons, cutters)

    def _valid_selected_regions(
        self, sketch: Optional[Sketch]
    ) -> List[Tuple[int, ...]]:
        if sketch is None:
            return []
        count = len(sketch.closed_loops())
        regions: List[Tuple[int, ...]] = []
        for region in self._selected_regions:
            filtered = tuple(
                index for index in region if 0 <= index < count
            )
            if filtered:
                regions.append(filtered)
        return regions

    def _draw_sketch_loops(
        self, surface: pygame.Surface, region: Rect, document: Document
    ) -> None:
        """Fill selected and hovered sketch faces, cutting out nested holes."""
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        loops = sketch.closed_loops()
        selected_regions = self._valid_selected_regions(sketch)
        hovered = self._hover_region
        if not selected_regions and hovered is None:
            return
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        overlay = self._loop_surface
        if overlay is None or overlay.get_size() != region.rect.size:
            overlay = pygame.Surface(region.rect.size, pygame.SRCALPHA)
            self._loop_surface = overlay
        overlay.fill((0, 0, 0, 0))
        selected_faces = self._face_regions(sketch, selected_regions)
        # While the extrude panel is open the live solid preview replaces the
        # flat yellow selection fill.
        if not self.extrude_window.visible:
            for outer, holes in selected_faces:
                self._draw_region_fill(
                    overlay, sketch, outer, holes, region,
                    self.geometry_selection, 70,
                )
            if (
                hovered is not None
                and hovered not in selected_regions
                and all(0 <= index < len(loops) for index in hovered)
            ):
                for outer, holes in self._face_regions(sketch, [hovered]):
                    self._draw_region_fill(
                        overlay, sketch, outer, holes, region,
                        self.geometry_hover, 45,
                    )
        surface.blit(overlay, region.rect.topleft)
        for outer, holes in selected_faces:
            self._draw_region_outline(
                surface, sketch, outer, holes, region,
                self.geometry_selection, 2,
            )
        surface.set_clip(previous_clip)

    def _draw_extrude_arrow(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        """Draw the distance handle at the end of a pending extrusion."""
        self._draw_handle_arrow(
            surface, region, self._extrude_arrow_points(region)
        )

    def _draw_fillet_arrow(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        """Draw the radius handle that points into the pending fillet."""
        self._draw_handle_arrow(
            surface, region, self._fillet_arrow_points(region)
        )

    def _draw_handle_arrow(
        self,
        surface: pygame.Surface,
        region: Rect,
        points: Optional[
            Tuple[Tuple[float, float], Tuple[float, float]]
        ],
    ) -> None:
        if points is None:
            return
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        start, end = points
        color = self.accent
        width = max(2, self._s(2))
        pygame.draw.line(surface, color, start, end, width)
        radius = max(3, self._s(3))
        pygame.draw.circle(surface, color, start, radius)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1.0:
            pygame.draw.circle(surface, color, end, max(4, self._s(5)))
            surface.set_clip(previous_clip)
            return
        unit_x, unit_y = dx / length, dy / length
        head = min(self._s(13), length * 0.7)
        wing = head * 0.45
        left = (
            end[0] - unit_x * head - unit_y * wing,
            end[1] - unit_y * head + unit_x * wing,
        )
        right = (
            end[0] - unit_x * head + unit_y * wing,
            end[1] - unit_y * head - unit_x * wing,
        )
        pygame.draw.polygon(surface, color, [end, left, right])
        pygame.draw.circle(
            surface, pygame.Color(235, 242, 255), end, max(2, self._s(2))
        )
        surface.set_clip(previous_clip)

    def _extrude_arrow_points(
        self, region: Rect
    ) -> Optional[
        Tuple[Tuple[float, float], Tuple[float, float]]
    ]:
        preview = self._extrude_preview
        if (
            preview is None
            or preview.handle_start is None
            or preview.handle_end is None
        ):
            return None
        return (
            self.viewport.project(preview.handle_start, region),
            self.viewport.project(preview.handle_end, region),
        )

    def _fillet_arrow_points(
        self, region: Rect
    ) -> Optional[
        Tuple[Tuple[float, float], Tuple[float, float]]
    ]:
        preview = self._fillet_preview
        if (
            preview is None
            or preview.handle_start is None
            or preview.handle_end is None
        ):
            return None
        return (
            self.viewport.project(preview.handle_start, region),
            self.viewport.project(preview.handle_end, region),
        )

    def _draw_region_fill(
        self,
        overlay: pygame.Surface,
        sketch: Sketch,
        outer: List[Point],
        holes: List[List[Point]],
        region: Rect,
        color: pygame.Color,
        alpha: int,
    ) -> None:
        polygon = self._project_polygon(sketch, outer, region)
        if len(polygon) < 3:
            return
        local = [
            (point[0] - region.rect.x, point[1] - region.rect.y)
            for point in polygon
        ]
        pygame.draw.polygon(
            overlay, (color.r, color.g, color.b, alpha), local
        )
        for hole in holes:
            local_hole = self._local_polygon(sketch, hole, region)
            if len(local_hole) >= 3:
                pygame.draw.polygon(overlay, (0, 0, 0, 0), local_hole)

    def _draw_region_outline(
        self,
        surface: pygame.Surface,
        sketch: Sketch,
        outer: List[Point],
        holes: List[List[Point]],
        region: Rect,
        color: pygame.Color,
        width: int,
    ) -> None:
        width = max(1, self._s(width))
        polygon = self._project_polygon(sketch, outer, region)
        if len(polygon) >= 3:
            pygame.draw.lines(surface, color, True, polygon, width)
        for hole in holes:
            hole_polygon = self._project_polygon(sketch, hole, region)
            if len(hole_polygon) >= 3:
                pygame.draw.lines(
                    surface, color, True, hole_polygon, width
                )

    def _local_polygon(
        self, sketch: Sketch, points: List[Point], region: Rect
    ) -> List[Tuple[float, float]]:
        return [
            (point[0] - region.rect.x, point[1] - region.rect.y)
            for point in self._project_polygon(sketch, points, region)
        ]

    def _project_polygon(
        self, sketch: Sketch, points: List[Point], region: Rect
    ) -> List[Tuple[float, float]]:
        return [
            self._project_sketch_point(sketch, point, region)
            for point in points
        ]

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
        if self._measure_tool is not None:
            for entity in self._measure_selection:
                self._draw_sketch_entity_highlight(
                    surface, sketch, region, entity,
                    self.geometry_selection, True,
                )
        if self._constraint_tool == "coincident":
            for entity in self._coincident_selection:
                if entity[0] == "point":
                    self._draw_sketch_entity_highlight(
                        surface, sketch, region, entity,
                        self.geometry_selection, True,
                    )
                else:
                    self._draw_origin_pick_highlight(
                        surface, sketch, region
                    )
        self._draw_sketch_constraints(surface, sketch, region)
        self._draw_sketch_coincidences(surface, sketch, region)
        self._draw_sketch_measurements(surface, sketch, region)
        if selected is not None and not (
            self._drag_edge_index is not None
            and selected == ("line", self._drag_edge_index)
        ):
            self._draw_sketch_entity_highlight(
                surface, sketch, region, selected, self.geometry_selection, True
            )
        self._draw_point_drag_preview(surface, sketch, region)
        self._draw_edge_drag_preview(surface, sketch, region)
        surface.set_clip(previous_clip)

    def _draw_sketch_constraints(
        self, surface: pygame.Surface, sketch: Sketch, region: Rect
    ) -> None:
        if not self.sketch_palette_window.options.get(
            "constraints", True
        ):
            return
        for index, (start, end) in enumerate(sketch.lines):
            constraint = sketch.edge_constraint(index)
            if constraint is None:
                continue
            screen_start = self._project_sketch_point(
                sketch, start, region
            )
            screen_end = self._project_sketch_point(
                sketch, end, region
            )
            midpoint = (
                (screen_start[0] + screen_end[0]) / 2,
                (screen_start[1] + screen_end[1]) / 2,
            )
            if constraint == "horizontal":
                anchor = (
                    midpoint[0], midpoint[1] - self._s(12)
                )
                glyph = "H"
            else:
                anchor = (
                    midpoint[0] + self._s(14), midpoint[1]
                )
                glyph = "V"
            if not region.collidepoint(anchor):
                continue
            label = self._font_small.render(
                glyph, True, self.accent
            )
            box = label.get_rect(center=(
                round(anchor[0]), round(anchor[1])
            ))
            box.inflate_ip(self._s(6), self._s(2))
            pygame.draw.rect(
                surface, self.header_bg, box,
                border_radius=self._s(3),
            )
            pygame.draw.rect(
                surface, self.border_color, box,
                width=1, border_radius=self._s(3),
            )
            surface.blit(label, label.get_rect(center=box.center))

    def _draw_sketch_coincidences(
        self, surface: pygame.Surface, sketch: Sketch, region: Rect
    ) -> None:
        """Draw a small marker on every point taking part in a coincidence."""
        if not self.sketch_palette_window.options.get(
            "constraints", True
        ):
            return
        seen: set = set()
        for coincidence in sketch.coincidences:
            for ref in (coincidence.first, coincidence.second):
                if ref in seen:
                    continue
                seen.add(ref)
                if ref[0] == "point":
                    if not 0 <= ref[1] < len(sketch.points):
                        continue
                    world = sketch.points[ref[1]]
                else:
                    if not self.viewport.show_origin:
                        continue
                    world = sketch.origin_point()
                screen = self._project_sketch_point(
                    sketch, world, region
                )
                anchor = (
                    screen[0] + self._s(11),
                    screen[1] - self._s(11),
                )
                if not region.collidepoint(anchor):
                    continue
                label = self._font_small.render("C", True, self.accent)
                box = label.get_rect(center=(
                    round(anchor[0]), round(anchor[1])
                ))
                box.inflate_ip(self._s(6), self._s(2))
                pygame.draw.rect(
                    surface, self.header_bg, box,
                    border_radius=self._s(3),
                )
                pygame.draw.rect(
                    surface, self.border_color, box,
                    width=1, border_radius=self._s(3),
                )
                surface.blit(
                    label, label.get_rect(center=box.center)
                )

    def _draw_origin_pick_highlight(
        self, surface: pygame.Surface, sketch: Sketch, region: Rect
    ) -> None:
        """Ring the projected document origin while it is picked."""
        screen = self._project_sketch_point(
            sketch, sketch.origin_point(), region
        )
        pygame.draw.circle(
            surface, self.geometry_selection,
            (round(screen[0]), round(screen[1])),
            self._s(9), width=max(1, self._s(2)),
        )

    def _draw_sketch_measurements(
        self, surface: pygame.Surface, sketch: Sketch, region: Rect
    ) -> None:
        self._measurement_label_rects = []
        self._measurement_edit_rect = None
        if not self.sketch_palette_window.options.get("dimensions", True):
            return
        for index, measurement in enumerate(sketch.measurements):
            if measurement.kind in ("distance", "diameter"):
                result = self._draw_distance_measurement(
                    surface, sketch, region, index, measurement
                )
            else:
                result = self._draw_angle_measurement(
                    surface, sketch, region, index, measurement
                )
            if result is None:
                continue
            anchor, text = result
            if not region.collidepoint(anchor):
                continue
            if index == self._editing_measurement_index:
                box = self._draw_measurement_editor(
                    surface, region, anchor, measurement
                )
            else:
                box = self._draw_measurement_label(
                    surface, anchor, text, index
                )
            self._measurement_label_rects.append((index, box))

    def _draw_distance_measurement(
        self,
        surface: pygame.Surface,
        sketch: Sketch,
        region: Rect,
        index: int,
        measurement: Measurement,
    ) -> Optional[Tuple[Tuple[float, float], str]]:
        geometry = self._measurement_span_geometry(
            sketch, measurement.kind,
            measurement.first, measurement.second,
        )
        if geometry is None:
            return None
        value, first_point, second_point = geometry
        display_value = (
            measurement.value
            if measurement.value is not None
            else value
        )
        offset = self._measurement_current_placement(
            sketch, index, measurement
        )
        if offset is None:
            offset = self._default_distance_placement(
                sketch, measurement.kind,
                measurement.first, measurement.second,
            )
        _, normal, _ = self._measurement_axis(
            first_point, second_point
        )
        dimension_first = (
            first_point[0] + normal[0] * offset,
            first_point[1] + normal[1] * offset,
        )
        dimension_second = (
            second_point[0] + normal[0] * offset,
            second_point[1] + normal[1] * offset,
        )
        screen_first = self._project_sketch_point(
            sketch, first_point, region
        )
        screen_second = self._project_sketch_point(
            sketch, second_point, region
        )
        screen_dimension_first = self._project_sketch_point(
            sketch, dimension_first, region
        )
        screen_dimension_second = self._project_sketch_point(
            sketch, dimension_second, region
        )
        self._draw_extension_line(
            surface, screen_first, screen_dimension_first
        )
        self._draw_extension_line(
            surface, screen_second, screen_dimension_second
        )
        color = self.text_secondary
        thickness = max(1, self._s(1))
        if screen_dimension_first == screen_dimension_second:
            pygame.draw.circle(
                surface, color,
                (round(screen_dimension_first[0]),
                 round(screen_dimension_first[1])),
                max(1, self._s(2)),
            )
        else:
            pygame.draw.line(
                surface, color,
                screen_dimension_first, screen_dimension_second,
                thickness,
            )
            self._draw_dimension_arrow(
                surface, screen_dimension_first,
                screen_dimension_second, color,
            )
            self._draw_dimension_arrow(
                surface, screen_dimension_second,
                screen_dimension_first, color,
            )
        screen_midpoint = (
            (screen_dimension_first[0] + screen_dimension_second[0]) / 2,
            (screen_dimension_first[1] + screen_dimension_second[1]) / 2,
        )
        measured_midpoint = (
            (screen_first[0] + screen_second[0]) / 2,
            (screen_first[1] + screen_second[1]) / 2,
        )
        label_x = screen_midpoint[0] - measured_midpoint[0]
        label_y = screen_midpoint[1] - measured_midpoint[1]
        label_length = math.hypot(label_x, label_y)
        if label_length <= 1e-6:
            step_point = (
                first_point[0] + normal[0] * (offset + 1.0),
                first_point[1] + normal[1] * (offset + 1.0),
            )
            screen_step = self._project_sketch_point(
                sketch, step_point, region
            )
            label_x = screen_step[0] - screen_midpoint[0]
            label_y = screen_step[1] - screen_midpoint[1]
            label_length = math.hypot(label_x, label_y)
        if label_length <= 1e-6:
            label_x, label_y, label_length = 0.0, -1.0, 1.0
        normal_x = label_x / label_length
        normal_y = label_y / label_length
        text = (
            f"Ø{display_value:.2f}"
            if measurement.kind == "diameter"
            else f"{display_value:.2f}"
        )
        label_width, label_height = self._font_small.size(text)
        half_width = (label_width + self._s(10)) / 2
        half_height = (label_height + self._s(4)) / 2
        gap = (
            abs(normal_x) * (half_width + self._s(3))
            + abs(normal_y) * (half_height + self._s(3))
        )
        anchor = (
            screen_midpoint[0] + normal_x * gap,
            screen_midpoint[1] + normal_y * gap,
        )
        return anchor, text

    def _draw_angle_measurement(
        self,
        surface: pygame.Surface,
        sketch: Sketch,
        region: Rect,
        index: int,
        measurement: Measurement,
    ) -> Optional[Tuple[Tuple[float, float], str]]:
        geometry = self._angle_geometry(
            sketch, measurement.first, measurement.second
        )
        if geometry is None:
            return None
        value, vertex, first_point, second_point = geometry
        display_value = (
            measurement.value
            if measurement.value is not None
            else value
        )
        radius = self._measurement_current_placement(
            sketch, index, measurement
        )
        if radius is None:
            radius = self._default_angle_placement(
                sketch, measurement.first, measurement.second
            )
        radius = max(1.0, radius)
        first_angle = math.atan2(
            first_point[1] - vertex[1],
            first_point[0] - vertex[0],
        )
        second_angle = math.atan2(
            second_point[1] - vertex[1],
            second_point[0] - vertex[0],
        )
        sweep = (
            second_angle - first_angle + math.pi
        ) % math.tau - math.pi
        segments = 24
        points: List[Tuple[float, float]] = []
        for step in range(segments + 1):
            angle = first_angle + sweep * step / segments
            world_point = (
                vertex[0] + radius * math.cos(angle),
                vertex[1] + radius * math.sin(angle),
            )
            points.append(
                self._project_sketch_point(
                    sketch, world_point, region
                )
            )
        color = self.text_secondary
        thickness = max(1, self._s(1))
        if any(point != points[0] for point in points[1:]):
            pygame.draw.lines(
                surface, color, False, points, thickness
            )
            self._draw_dimension_arrow(
                surface, points[0], points[1], color
            )
            self._draw_dimension_arrow(
                surface, points[-1], points[-2], color
            )
        anchor = points[len(points) // 2]
        return anchor, f"{display_value:.1f}°"

    def _draw_extension_line(
        self,
        surface: pygame.Surface,
        origin: Tuple[float, float],
        target: Tuple[float, float],
    ) -> None:
        delta_x = target[0] - origin[0]
        delta_y = target[1] - origin[1]
        length = math.hypot(delta_x, delta_y)
        gap = self._s(3)
        overshoot = self._s(5)
        if length <= gap + overshoot:
            return
        direction_x = delta_x / length
        direction_y = delta_y / length
        start = (
            origin[0] + direction_x * gap,
            origin[1] + direction_y * gap,
        )
        end = (
            target[0] + direction_x * overshoot,
            target[1] + direction_y * overshoot,
        )
        pygame.draw.line(
            surface, self.text_muted, start, end,
            max(1, self._s(1)),
        )

    def _draw_dimension_arrow(
        self,
        surface: pygame.Surface,
        tip: Tuple[float, float],
        toward: Tuple[float, float],
        color: pygame.Color,
    ) -> None:
        delta_x = tip[0] - toward[0]
        delta_y = tip[1] - toward[1]
        length = math.hypot(delta_x, delta_y)
        if length <= 1e-6:
            return
        direction_x = delta_x / length
        direction_y = delta_y / length
        arrow_length = min(float(self._s(7)), length * 0.45)
        if arrow_length <= 1.0:
            return
        half_width = max(1.0, arrow_length * 0.34)
        base_x = tip[0] - direction_x * arrow_length
        base_y = tip[1] - direction_y * arrow_length
        perpendicular_x = -direction_y
        perpendicular_y = direction_x
        pygame.draw.polygon(
            surface,
            color,
            [
                (round(tip[0]), round(tip[1])),
                (
                    round(base_x + perpendicular_x * half_width),
                    round(base_y + perpendicular_y * half_width),
                ),
                (
                    round(base_x - perpendicular_x * half_width),
                    round(base_y - perpendicular_y * half_width),
                ),
            ],
        )

    def _draw_measurement_label(
        self,
        surface: pygame.Surface,
        anchor: Tuple[float, float],
        text: str,
        index: int,
    ) -> pygame.Rect:
        label = self._font_small.render(text, True, self.text_primary)
        box = label.get_rect(center=(
            round(anchor[0]), round(anchor[1])
        ))
        box.inflate_ip(self._s(10), self._s(4))
        pygame.draw.rect(
            surface, self.panel_bg, box, border_radius=self._s(3)
        )
        active = (
            self._hover_measurement_index == index
            or self._drag_measurement_index == index
        )
        pygame.draw.rect(
            surface,
            self.accent if active else self.border_color,
            box,
            width=1,
            border_radius=self._s(3),
        )
        surface.blit(label, label.get_rect(center=box.center))
        return box

    def _draw_measurement_editor(
        self,
        surface: pygame.Surface,
        region: Rect,
        anchor: Tuple[float, float],
        measurement: Measurement,
    ) -> pygame.Rect:
        suffix = "°" if measurement.kind == "angle" else ""
        text_surface = self._font_small.render(
            self._measurement_edit_text, True, self.text_primary
        )
        suffix_surface = (
            self._font_small.render(suffix, True, self.text_secondary)
            if suffix else None
        )
        padding = self._s(9)
        cursor_gap = self._s(2)
        cursor_width = max(1, self._s(1))
        content_width = text_surface.get_width() + cursor_gap * 2 + cursor_width
        if suffix_surface is not None:
            content_width += suffix_surface.get_width()
        box = pygame.Rect(
            0, 0,
            max(self._s(88), content_width + padding * 2),
            self._s(25),
        )
        box.center = (round(anchor[0]), round(anchor[1]))
        pygame.draw.rect(
            surface, self.panel_bg, box, border_radius=self._s(3)
        )
        pygame.draw.rect(
            surface, self.accent, box, width=max(1, self._s(2)),
            border_radius=self._s(3),
        )
        text_x = box.x + padding
        surface.blit(
            text_surface,
            text_surface.get_rect(x=text_x, centery=box.centery),
        )
        text_x += text_surface.get_width() + cursor_gap
        if (pygame.time.get_ticks() // 500) % 2 == 0:
            pygame.draw.line(
                surface, self.text_primary,
                (text_x, box.y + self._s(5)),
                (text_x, box.bottom - self._s(5)),
                cursor_width,
            )
        text_x += cursor_width + cursor_gap
        if suffix_surface is not None:
            surface.blit(
                suffix_surface,
                suffix_surface.get_rect(
                    x=text_x, centery=box.centery
                ),
            )
        if self._measurement_edit_error:
            hint_text = self._measurement_edit_error
            hint_color = self.error_color
        else:
            hint_text = "Enter to apply  ·  Esc to cancel"
            hint_color = self.text_muted
        hint = self._font_small.render(hint_text, True, hint_color)
        hint_rect = hint.get_rect()
        hint_rect.centerx = box.centerx
        hint_rect.y = box.y - hint_rect.height - self._s(4)
        if hint_rect.y < region.y + self._s(2):
            hint_rect.y = box.bottom + self._s(4)
        hint_rect.x = max(
            region.x + self._s(2),
            min(hint_rect.x, region.right - hint_rect.width - self._s(2)),
        )
        surface.blit(hint, hint_rect)
        self._measurement_edit_rect = box
        return box

    def _measurement_label_at(
        self, pos: Tuple[int, int]
    ) -> Optional[int]:
        for index, rect in reversed(self._measurement_label_rects):
            if rect.collidepoint(pos):
                return index
        return None

    def _start_measurement_drag(
        self,
        index: int,
        sketch: Sketch,
        pos: Tuple[int, int],
        region: Rect,
    ) -> None:
        if not 0 <= index < len(sketch.measurements):
            return
        measurement = sketch.measurements[index]
        current = self._measurement_current_placement(
            sketch, index, measurement
        )
        if current is None:
            return
        grab_delta = 0.0
        world = self.viewport.unproject_on_plane(
            pos, region, sketch.frame()
        )
        if world is not None:
            cursor_placement = self._measurement_placement_from_cursor(
                sketch, index, world
            )
            if cursor_placement is not None:
                grab_delta = current - cursor_placement
        self._clear_sketch_selection()
        self._drag_measurement_index = index
        self._drag_measurement_original = current
        self._drag_measurement_current = current
        self._drag_measurement_grab_delta = grab_delta
        self._drag_measurement_start_pos = pos
        self._drag_measurement_moved = False
        self._hover_measurement_index = index
        self._reset_line_state()

    def _finish_measurement_drag(self) -> bool:
        index = self._drag_measurement_index
        current = self._drag_measurement_current
        original = self._drag_measurement_original
        moved = self._drag_measurement_moved
        self._drag_measurement_index = None
        self._drag_measurement_original = None
        self._drag_measurement_current = None
        self._drag_measurement_grab_delta = 0.0
        self._drag_measurement_start_pos = None
        self._drag_measurement_moved = False
        if not moved or index is None or current is None:
            return moved
        if original is not None and abs(current - original) <= 1e-6:
            return moved
        if self.on_set_measurement_placement is not None:
            self.on_set_measurement_placement(index, current)
        return moved

    def _begin_measurement_edit(
        self, index: int, sketch: Sketch
    ) -> None:
        if not 0 <= index < len(sketch.measurements):
            return
        measurement = sketch.measurements[index]
        value = measurement.value
        if value is None:
            value = self._measurement_value_from_geometry(
                sketch,
                measurement.kind,
                measurement.first,
                measurement.second,
            )
        if value is None:
            return
        self._editing_measurement_index = index
        self._measurement_edit_text = (
            f"{value:.1f}" if measurement.kind == "angle"
            else f"{value:.2f}"
        )
        self._measurement_edit_error = ""
        self._measurement_edit_rect = None
        self._measurement_edit_pristine = True
        self._hover_measurement_index = index
        self._measure_selection.clear()
        self._reset_line_state()

    def _cancel_measurement_edit(self) -> None:
        self._editing_measurement_index = None
        self._measurement_edit_text = ""
        self._measurement_edit_error = ""
        self._measurement_edit_rect = None
        self._measurement_edit_pristine = False

    def _parse_measurement_edit_value(
        self, kind: str
    ) -> Optional[float]:
        text = self._measurement_edit_text.strip().replace(",", ".")
        if text.endswith("°"):
            text = text[:-1].strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        if not math.isfinite(value) or value < 0:
            return None
        if kind == "angle" and value > 180:
            return None
        if kind == "diameter" and value <= 0:
            return None
        return value

    def _commit_measurement_edit(self, document: Document) -> bool:
        index = self._editing_measurement_index
        if index is None:
            return False
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.measurements):
            self._cancel_measurement_edit()
            return False
        measurement = sketch.measurements[index]
        previous = measurement.value
        if self._measurement_edit_pristine and previous is not None:
            self._cancel_measurement_edit()
            return True
        value = self._parse_measurement_edit_value(measurement.kind)
        if value is None:
            if measurement.kind == "angle":
                self._measurement_edit_error = (
                    "Enter a value between 0 and 180"
                )
            else:
                self._measurement_edit_error = "Enter a positive number"
            return False
        self._cancel_measurement_edit()
        # Commit even when the number is unchanged: re-entering a stored
        # value is how an inconsistent sketch is brought back into line.
        if self.on_set_measurement_value is not None:
            self.on_set_measurement_value(index, value)
        return True

    def _handle_measurement_edit_event(
        self, event: pygame.event.Event, document: Document
    ) -> bool:
        if self._editing_measurement_index is None:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._cancel_measurement_edit()
            elif event.key in (
                pygame.K_RETURN, pygame.K_KP_ENTER
            ):
                self._commit_measurement_edit(document)
            elif event.key == pygame.K_BACKSPACE:
                self._measurement_edit_text = (
                    self._measurement_edit_text[:-1]
                )
                self._measurement_edit_error = ""
                self._measurement_edit_pristine = False
            elif event.key == pygame.K_DELETE:
                self._measurement_edit_text = ""
                self._measurement_edit_error = ""
                self._measurement_edit_pristine = False
            elif event.mod & pygame.KMOD_CTRL:
                return True
            elif event.unicode and (
                event.unicode.isdigit()
                or event.unicode in ".,-°"
            ):
                if self._measurement_edit_pristine:
                    self._measurement_edit_text = ""
                    self._measurement_edit_pristine = False
                if len(self._measurement_edit_text) < 12:
                    self._measurement_edit_text += event.unicode
                    self._measurement_edit_error = ""
            return True
        if event.type == pygame.MOUSEBUTTONDOWN:
            if (
                self._measurement_edit_rect is not None
                and self._measurement_edit_rect.collidepoint(
                    event.pos
                )
            ):
                return True
            self._commit_measurement_edit(document)
            return True
        if event.type in (
            pygame.MOUSEBUTTONUP,
            pygame.MOUSEMOTION,
            pygame.MOUSEWHEEL,
        ):
            return True
        return False

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
        sketch.constrain_axis_changes(preview_points, [index])
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

    def _draw_edge_drag_preview(
        self, surface: pygame.Surface, sketch: Sketch, region: Rect
    ) -> None:
        index = self._drag_edge_index
        current = self._drag_edge_current
        if (
            index is None
            or current is None
            or not 0 <= index < len(sketch.edges)
        ):
            return
        first, second = sketch.edges[index]
        preview_points = list(sketch.points)
        preview_points[first] = current[0]
        preview_points[second] = current[1]
        sketch.constrain_axis_changes(
            preview_points, [first, second]
        )
        for edge_index, (start, end) in enumerate(sketch.edges):
            if first not in (start, end) and second not in (start, end):
                continue
            screen_start = self._project_sketch_point(
                sketch, preview_points[start], region
            )
            screen_end = self._project_sketch_point(
                sketch, preview_points[end], region
            )
            pygame.draw.line(
                surface, self.geometry_selection,
                screen_start, screen_end,
                max(1, self._s(3 if edge_index == index else 1)),
            )
        for point in current:
            screen = self._project_sketch_point(sketch, point, region)
            pygame.draw.circle(
                surface, self.geometry_selection,
                (round(screen[0]), round(screen[1])),
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
        if not 0 <= index < len(sketch.edges):
            return
        screen = [
            self._project_sketch_point(sketch, point, region)
            for point in sketch.edge_points(index)
        ]
        width = max(1, self._s(3 if selected else 2))
        for screen_start, screen_end in zip(screen, screen[1:]):
            pygame.draw.line(
                surface, color, screen_start, screen_end, width,
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
        groups = self._solid_toolbar_groups(region, document)
        label_y = region.bottom - self._s(15)
        for index, group in enumerate(groups):
            for item in group.items:
                hovered = item.enabled and item.action == self._hover_tool
                if hovered:
                    pygame.draw.rect(
                        surface, self.header_bg, item.rect,
                        border_radius=self._s(5),
                    )
                    pygame.draw.rect(
                        surface, self.border_color, item.rect,
                        width=self._s(1),
                        border_radius=self._s(5),
                    )
                color = (
                    self._kind_color(item.action) if item.enabled
                    else pygame.Color(82, 82, 92)
                )
                self._draw_action_icon(
                    surface, item.rect, item.action, color
                )
            caption = self._font_caption.render(
                group.caption, True, self.text_primary
            )
            surface.blit(
                caption,
                caption.get_rect(
                    center=(group.rect.centerx, label_y)
                ),
            )
            if index < len(groups) - 1:
                separator_x = group.rect.right + self._s(9)
                pygame.draw.line(
                    surface, self.border_color,
                    (separator_x, group.rect.top),
                    (separator_x, region.bottom - self._s(8)),
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
        if self._line_menu_open or self._measure_menu_open:
            return
        if self._hover_tool not in self.TOOL_LABELS:
            return
        action = self._hover_tool
        text = self.TOOL_LABELS[action]
        if (
            action == "constraint_auto"
            and self._constraint_tool in ("vertical", "horizontal")
        ):
            text = f"{self._constraint_tool.title()} Constraint"
        elif action == "measure" and self._measure_tool in (
            "angle", "distance", "diameter"
        ):
            text = f"{self._measure_tool.title()} Measurement"
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
        if kind == "fillet":
            return pygame.Color(251, 146, 60)
        if kind in ("line", "rectangle", "circle", "point"):
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
        elif kind == "constraint_auto":
            thickness = max(1, self._s(2))
            top = cy - radius // 2
            bottom = cy + radius // 2
            hx0 = cx - radius
            hx1 = cx - radius // 3
            pygame.draw.line(
                surface, color, (hx0, top), (hx0, bottom), thickness
            )
            pygame.draw.line(
                surface, color, (hx1, top), (hx1, bottom), thickness
            )
            pygame.draw.line(
                surface, color, (hx0, cy), (hx1, cy), thickness
            )
            vx0 = cx + radius // 3
            vx1 = cx + radius
            vxm = (vx0 + vx1) // 2
            pygame.draw.lines(
                surface, color, False,
                [(vx0, top), (vxm, bottom), (vx1, top)],
                thickness,
            )
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
        elif kind == "constraint_coincident":
            thickness = max(1, self._s(2))
            pygame.draw.circle(
                surface, color, (cx - radius // 2, cy), max(1, self._s(2))
            )
            pygame.draw.circle(
                surface, color, (cx + radius // 2, cy), max(1, self._s(2))
            )
            pygame.draw.line(
                surface, color,
                (cx - radius // 2, cy), (cx + radius // 2, cy),
                thickness,
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
        elif kind == "align_x":
            thickness = max(1, self._s(2))
            axis_y = cy + radius // 3
            pygame.draw.line(
                surface, color,
                (cx - radius, axis_y), (cx + radius, axis_y), thickness,
            )
            pygame.draw.lines(
                surface, color, False,
                [(cx + radius - self._s(4), axis_y - self._s(3)),
                 (cx + radius, axis_y),
                 (cx + radius - self._s(4), axis_y + self._s(3))],
                thickness,
            )
            pygame.draw.line(
                surface, self.text_muted,
                (cx - radius // 2, cy - radius),
                (cx + radius // 3, cy - radius // 2),
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

    def _handle_extrude_arrow_event(
        self, event: pygame.event.Event, region: Rect
    ) -> bool:
        """Start or update a drag of the extrusion distance handle."""
        if self._extrude_arrow_drag is not None:
            if event.type == pygame.MOUSEMOTION:
                self._drag_extrude_arrow(event.pos)
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._extrude_arrow_drag = None
                return True
            return False
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.extrude_window.visible
            and region.collidepoint(event.pos)
            and self._extrude_arrow_hit(event.pos, region)
        ):
            return self._begin_extrude_arrow_drag(event.pos, region)
        return False

    def _arrow_hit(
        self,
        pos: Tuple[int, int],
        points: Optional[
            Tuple[Tuple[float, float], Tuple[float, float]]
        ],
    ) -> bool:
        if points is None:
            return False
        start, end = points
        if math.hypot(pos[0] - end[0], pos[1] - end[1]) <= self._s(15):
            return True
        return (
            self._distance_to_segment(pos, start, end) <= self._s(7)
        )

    def _extrude_arrow_hit(
        self, pos: Tuple[int, int], region: Rect
    ) -> bool:
        return self._arrow_hit(pos, self._extrude_arrow_points(region))

    def _arrow_screen_axis(
        self,
        start: Sequence[float],
        end: Sequence[float],
        region: Rect,
    ) -> Optional[Tuple[float, float]]:
        """Return the screen direction of a model-space arrow."""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 1e-9:
            return None
        axis = (dx / length, dy / length, dz / length)
        anchor = self.viewport.project(start, region)
        unit = self.viewport.project(
            (
                start[0] + axis[0],
                start[1] + axis[1],
                start[2] + axis[2],
            ),
            region,
        )
        screen_axis = (unit[0] - anchor[0], unit[1] - anchor[1])
        projection_scale = PROJECTION_SCALE * self.viewport.camera.zoom
        if math.hypot(*screen_axis) < max(0.5, projection_scale * 0.15):
            # Viewed straight down the normal the projected arrow collapses to
            # a dot.  Fall back to a vertical drag so the handle stays usable.
            screen_axis = (0.0, -projection_scale)
        if math.hypot(*screen_axis) <= 1e-6:
            return None
        return screen_axis

    def _begin_extrude_arrow_drag(
        self, pos: Tuple[int, int], region: Rect
    ) -> bool:
        preview = self._extrude_preview
        distance = self.extrude_window.distance_value()
        if (
            preview is None
            or preview.handle_start is None
            or preview.handle_end is None
            or distance is None
        ):
            return False
        screen_axis = self._arrow_screen_axis(
            preview.handle_start, preview.handle_end, region
        )
        if screen_axis is None:
            return False
        world_per_pixel = 1.0 / max(1e-6, math.hypot(*screen_axis))
        self._extrude_arrow_drag = _ExtrudeArrowDrag(
            start_pos=pos,
            base_height=preview.height,
            base_half=distance * 0.5,
            screen_axis=screen_axis,
            symmetric=self.extrude_window.is_symmetric(),
            snap_step=_arrow_snap_step(world_per_pixel),
        )
        return True

    def _handle_fillet_arrow_event(
        self, event: pygame.event.Event, region: Rect
    ) -> bool:
        """Start or update a drag of the fillet radius handle."""
        if self._fillet_arrow_drag is not None:
            if event.type == pygame.MOUSEMOTION:
                self._drag_fillet_arrow(event.pos)
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._fillet_arrow_drag = None
                return True
            return False
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.fillet_window.visible
            and region.collidepoint(event.pos)
            and self._arrow_hit(
                event.pos, self._fillet_arrow_points(region)
            )
        ):
            return self._begin_fillet_arrow_drag(event.pos, region)
        return False

    def _begin_fillet_arrow_drag(
        self, pos: Tuple[int, int], region: Rect
    ) -> bool:
        preview = self._fillet_preview
        radius = self.fillet_window.radius()
        if (
            preview is None
            or preview.handle_start is None
            or preview.handle_end is None
            or radius is None
        ):
            return False
        screen_axis = self._arrow_screen_axis(
            preview.handle_start, preview.handle_end, region
        )
        if screen_axis is None:
            return False
        world_per_pixel = 1.0 / max(1e-6, math.hypot(*screen_axis))
        self._fillet_arrow_drag = _FilletArrowDrag(
            start_pos=pos,
            base_radius=radius,
            screen_axis=screen_axis,
            snap_step=_arrow_snap_step(world_per_pixel),
        )
        return True

    def _drag_fillet_arrow(self, pos: Tuple[int, int]) -> None:
        drag = self._fillet_arrow_drag
        if drag is None:
            return
        dx = pos[0] - drag.start_pos[0]
        dy = pos[1] - drag.start_pos[1]
        sx, sy = drag.screen_axis
        denominator = sx * sx + sy * sy
        if denominator <= 1e-9:
            return
        world = (dx * sx + dy * sy) / denominator
        # Snap the change instead of the absolute radius so grabbing a small
        # fillet at low zoom cannot jump it to an unrelated round value.
        radius = drag.base_radius + _snap_to_step(world, drag.snap_step)
        limit = self.fillet_window.radius_limit
        if limit is not None:
            radius = min(radius, limit)
        self.fillet_window.set_radius_value(max(0.05, radius))

    def _drag_extrude_arrow(self, pos: Tuple[int, int]) -> None:
        drag = self._extrude_arrow_drag
        if drag is None:
            return
        dx = pos[0] - drag.start_pos[0]
        dy = pos[1] - drag.start_pos[1]
        sx, sy = drag.screen_axis
        denominator = sx * sx + sy * sy
        if denominator <= 1e-9:
            return
        world = (dx * sx + dy * sy) / denominator
        if drag.symmetric:
            total = _snap_to_step(
                drag.base_half * 2.0 + world * 2.0, drag.snap_step
            )
            self.extrude_window.set_distance_value(
                max(drag.snap_step, total)
            )
            return
        signed = _snap_to_step(
            drag.base_height + world, drag.snap_step
        )
        self.extrude_window.set_distance_value(abs(signed))
        self.extrude_window.reverse = signed < 0.0

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

        # A drag on the viewport handle must keep receiving motion even when
        # the pointer crosses the property panel.
        if (
            self._extrude_arrow_drag is not None
            and self._handle_extrude_arrow_event(event, layout.viewport)
        ):
            return True
        if not self.fillet_window.visible:
            self._fillet_arrow_drag = None
        if (
            self._fillet_arrow_drag is not None
            and self._handle_fillet_arrow_event(event, layout.viewport)
        ):
            return True

        # The extrude panel owns keyboard input while it is open, so typing a
        # distance never reaches the sketch tools or the application shortcuts.
        if self.extrude_window.visible:
            action = self.extrude_window.handle_event(
                event, layout.viewport
            )
            if action is ExtrudeWindowAction.APPLY:
                self._apply_extrude(document)
                return True
            if action is not ExtrudeWindowAction.NONE:
                if not self.extrude_window.visible:
                    self._extrude_arrow_drag = None
                return True
        else:
            self._extrude_arrow_drag = None

        if self._handle_extrude_arrow_event(event, layout.viewport):
            return True

        if self._handle_fillet_arrow_event(event, layout.viewport):
            return True

        if self._handle_measurement_edit_event(event, document):
            return True

        if (
            event.type == pygame.KEYDOWN
            and event.key == pygame.K_DELETE
            and active_sketch is not None
            and self.delete_sketch_selection(document)
        ):
            return True

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

        if (
            self._constraint_menu_open
            and event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
        ):
            geometry = self._constraint_menu_geometry(layout.toolbar, document)
            if geometry is not None:
                panel, item_rects, caret = geometry
                if panel.collidepoint(event.pos):
                    for index, rect in enumerate(item_rects):
                        if rect.collidepoint(event.pos):
                            self._choose_constraint(index, document)
                            break
                    return True
                if caret is not None and caret.collidepoint(event.pos):
                    self._constraint_menu_open = False
                    self._constraint_menu_hover = -1
                    return True
            self._constraint_menu_open = False
            self._constraint_menu_hover = -1
            item = self._constraint_toolbar_item(layout.toolbar, document)
            if item is not None and item.rect.collidepoint(event.pos):
                self._activate_constraint_tool("auto", document)
                document.dirty = True
            return True

        if (
            self._measure_menu_open
            and event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
        ):
            geometry = self._measure_menu_geometry(layout.toolbar, document)
            if geometry is not None:
                panel, item_rects, caret = geometry
                if panel.collidepoint(event.pos):
                    for index, rect in enumerate(item_rects):
                        if rect.collidepoint(event.pos):
                            self._choose_measure(index, document)
                            break
                    return True
                if caret is not None and caret.collidepoint(event.pos):
                    self._measure_menu_open = False
                    self._measure_menu_hover = -1
                    return True
            self._measure_menu_open = False
            self._measure_menu_hover = -1
            item = self._measure_toolbar_item(layout.toolbar, document)
            if item is not None and item.rect.collidepoint(event.pos):
                self._activate_measure_tool("auto", document)
            return True

        # Commit a drag before any panel can consume the release.
        if (
            event.type == pygame.MOUSEBUTTONUP
            and event.button == 1
            and self._drag_measurement_index is not None
        ):
            index = self._drag_measurement_index
            moved = self._finish_measurement_drag()
            if not moved and index is not None:
                sketch = document.sketch(document.active_sketch_id)
                if sketch is not None:
                    self._begin_measurement_edit(index, sketch)
            return True
        if (
            event.type == pygame.MOUSEBUTTONUP
            and event.button == 1
            and self._drag_point_index is not None
        ):
            self._finish_point_drag(document)
            return True
        if (
            event.type == pygame.MOUSEBUTTONUP
            and event.button == 1
            and self._drag_edge_index is not None
        ):
            self._finish_edge_drag(document)
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
                    self._constraint_tool = None
                    self._clear_measure_state()
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
            fillet_action = self.fillet_window.handle_event(
                event, layout.viewport
            )
            if fillet_action is FilletWindowAction.APPLY:
                radius = self.fillet_window.radius()
                if radius is None:
                    self.fillet_window.set_error(
                        "Enter a radius greater than zero"
                    )
                elif self.on_fillet is not None:
                    error = self.on_fillet(radius)
                    if error:
                        self.fillet_window.set_error(error)
                    else:
                        self.fillet_window.set_error("")
                else:
                    self.fillet_window.set_error(
                        "Fillet is unavailable"
                    )
                return True
            if fillet_action is not FilletWindowAction.NONE:
                if not self.fillet_window.visible:
                    self._fillet_arrow_drag = None
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
                if mode != self.ACTIVE_MODE:
                    self.fillet_window.close()
                self._hover_mode = None
                if (
                    previous_mode == self.SKETCH_MODE
                    and mode != self.SKETCH_MODE
                ):
                    # Keep the sketch open, but do not leave a hidden sketch
                    # tool armed while another mode is visible.
                    selected_regions = list(self._selected_regions)
                    self._selected_tool = None
                    self._constraint_tool = None
                    self._clear_measure_state()
                    self._reset_line_state()
                    self._clear_sketch_selection()
                    self._selected_regions = selected_regions
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
                for group in self._solid_toolbar_groups(
                    layout.toolbar, document
                ):
                    for item in group.items:
                        if (
                            item.enabled
                            and item.rect.collidepoint(event.pos)
                        ):
                            self._run_tool(item.action, document)
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
                            document.selected_edge = None
                            document.active_sketch_id = None
                            self._selected_tool = None
                            self._constraint_tool = None
                            self._clear_measure_state()
                            self._reset_line_state()
                            self._clear_sketch_selection()
                        return True
                    if kind == "sketch":
                        self.on_select_sketch(item_id)
                        return True
                if not hit_row:
                    document.selected_plane = None
                    document.selected_face = None
                    document.selected_edge = None
                    return True

        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self._sketch_toolbar_visible(document)
            and layout.viewport.collidepoint(event.pos)
        ):
            sketch = document.sketch(document.active_sketch_id)
            if sketch is not None:
                if self._selected_tool == "project":
                    self._project_at(
                        event.pos, layout.viewport, document
                    )
                    return True
                if self._selected_tool == "align_x":
                    self._align_x_at(
                        event.pos, layout.viewport, document
                    )
                    return True
                if self._selected_tool == "rectangle":
                    point = self._rectangle_corner(
                        event.pos, layout.viewport, sketch
                    )
                    if point is not None:
                        self._clear_sketch_selection()
                        start = self._rectangle_start
                        if start is None:
                            self._rectangle_start = point
                            self._rectangle_preview = point
                        elif (
                            point[0] != start[0]
                            and point[1] != start[1]
                        ):
                            self.on_add_rectangle(start, point)
                            self._rectangle_start = None
                            self._rectangle_preview = None
                    return True
                if self._selected_tool == "circle":
                    snap_index = self._pick_sketch_point(
                        event.pos, layout.viewport, sketch
                    )
                    if snap_index is not None:
                        point: Optional[Point] = sketch.points[snap_index]
                    else:
                        world = self.viewport.unproject_on_plane(
                            event.pos, layout.viewport, sketch.frame()
                        )
                        point = (
                            (round(world[0]), round(world[1]))
                            if world is not None else None
                        )
                    if point is not None:
                        self._clear_sketch_selection()
                        center = self._circle_center
                        if center is None:
                            self._circle_center = point
                            self._circle_preview = (point, 0.0)
                        else:
                            diameter = 2.0 * math.hypot(
                                point[0] - center[0],
                                point[1] - center[1],
                            )
                            if diameter > 0:
                                self.on_add_circle(center, diameter)
                                self._circle_center = None
                                self._circle_preview = None
                    return True
                label_index = self._measurement_label_at(event.pos)
                if label_index is not None:
                    self._start_measurement_drag(
                        label_index, sketch, event.pos,
                        layout.viewport,
                    )
                    return True
                if self._constraint_tool == "coincident":
                    self._coincident_click(
                        document, event.pos, layout.viewport, sketch
                    )
                    return True
                if self._measure_tool is not None:
                    if self._measure_tool == "diameter":
                        circle_index = self._pick_sketch_circle(
                            event.pos, layout.viewport, sketch
                        )
                        if circle_index is not None:
                            self._measure_click(
                                document, ("circle", circle_index)
                            )
                        else:
                            self._measure_selection.clear()
                            self._clear_sketch_selection()
                            self._reset_measure_click()
                        return True
                    hit = self._pick_sketch_entity(
                        event.pos, layout.viewport, sketch
                    )
                    if (
                        hit is None
                        and self._measure_tool == "auto"
                    ):
                        circle_index = self._pick_sketch_circle(
                            event.pos, layout.viewport, sketch
                        )
                        if circle_index is not None:
                            hit = ("circle", circle_index)
                    if hit is not None:
                        if (
                            hit[0] == "line"
                            and self._measure_tool in ("auto", "distance")
                            and self._measure_is_double_click(
                                event.pos, hit
                            )
                        ):
                            self._dimension_line(document, hit)
                        else:
                            self._measure_click(document, hit)
                    else:
                        self._measure_selection.clear()
                        self._clear_sketch_selection()
                        self._reset_measure_click()
                    return True
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
                        region_hit: Optional[Tuple[int, ...]] = None
                        if (
                            kind == "point"
                            and self._selected_tool is None
                            and self._constraint_tool is None
                        ):
                            # A circle centre is also a draggable point.  A
                            # plain click selects the circle face; pressing and
                            # dragging still moves the centre.
                            loop_hit = self._circle_loop_at_point(
                                sketch, index
                            )
                            if loop_hit is not None:
                                region_hit = (loop_hit,)
                        if region_hit is not None:
                            mods = getattr(event, "mod", 0)
                            if not mods:
                                mods = pygame.key.get_mods()
                            self._select_sketch_region(region_hit, mods)
                            if not sketch.is_projected_point(index):
                                self._drag_point_index = index
                                self._drag_point_origin = sketch.points[index]
                                self._drag_point_current = sketch.points[index]
                            return True
                        self._clear_sketch_selection()
                        self._selected_sketch_entity = hit
                        self._hover_sketch_entity = hit
                        self._reset_line_state()
                        if (
                            kind == "line"
                            and self._constraint_tool is not None
                        ):
                            self._apply_constraint_tool(document)
                            return True
                        if kind == "point":
                            if not sketch.is_projected_point(index):
                                self._drag_point_index = index
                                self._drag_point_origin = sketch.points[index]
                                self._drag_point_current = sketch.points[index]
                        elif not sketch.is_projected_edge(index):
                            self._start_edge_drag(
                                index, sketch, event.pos, layout.viewport
                            )
                        return True
                    region_hit = None
                    if (
                        self._selected_tool is None
                        and self._constraint_tool is None
                    ):
                        region_hit = self._pick_sketch_region(
                            event.pos, layout.viewport, sketch
                        )
                    if region_hit is not None:
                        mods = getattr(event, "mod", 0)
                        if not mods:
                            mods = pygame.key.get_mods()
                        self._select_sketch_region(region_hit, mods)
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
                snapped = snap_index is not None
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
                    else:
                        point, constraint = self._auto_axis_point(
                            sketch, self._line_start, point,
                            layout.viewport, snapped,
                        )
                        if point != self._line_start:
                            self.on_add_line(
                                self._line_start, point, constraint
                            )
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

    def _start_edge_drag(
        self, index: int, sketch: Sketch, pos: Tuple[int, int], region: Rect
    ) -> None:
        if not 0 <= index < len(sketch.edges):
            return
        anchor = self.viewport.unproject_on_plane(
            pos, region, sketch.frame()
        )
        if anchor is None:
            return
        start, end = sketch.lines[index]
        self._drag_edge_index = index
        self._drag_edge_origin = (start, end)
        self._drag_edge_anchor = (anchor[0], anchor[1])
        self._drag_edge_current = (start, end)

    def _finish_edge_drag(self, document: Document) -> None:
        index = self._drag_edge_index
        current = self._drag_edge_current
        origin = self._drag_edge_origin
        self._drag_edge_index = None
        self._drag_edge_origin = None
        self._drag_edge_anchor = None
        self._drag_edge_current = None
        if index is None or current is None or origin is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.edges):
            return
        if current == origin:
            return
        self.on_move_edge(index, current[0], current[1])

    def _rectangle_corner(
        self, pos: Tuple[int, int], region: Rect, sketch: Sketch
    ) -> Optional[Point]:
        """Return the snapped or free sketch corner under the cursor."""
        index = self._pick_sketch_point(pos, region, sketch)
        if index is not None:
            point = sketch.points[index]
            return (point[0], point[1])
        world = self.viewport.unproject_on_plane(
            pos, region, sketch.frame()
        )
        if world is None:
            return None
        return (round(world[0]), round(world[1]))

    def _auto_axis_point(
        self,
        sketch: Sketch,
        start: Point,
        point: Point,
        region: Rect,
        snapped: bool,
    ) -> Tuple[Point, Optional[str]]:
        if not self._auto_constraints_enabled():
            return point, None
        if snapped:
            if start[1] == point[1] and start[0] != point[0]:
                return point, "horizontal"
            if start[0] == point[0] and start[1] != point[1]:
                return point, "vertical"
            return point, None
        start_screen = self._project_sketch_point(sketch, start, region)
        x_screen = self._project_sketch_point(
            sketch, (start[0] + 1, start[1]), region
        )
        y_screen = self._project_sketch_point(
            sketch, (start[0], start[1] + 1), region
        )
        pixels_per_x = max(
            math.hypot(
                x_screen[0] - start_screen[0],
                x_screen[1] - start_screen[1],
            ),
            1e-6,
        )
        pixels_per_y = max(
            math.hypot(
                y_screen[0] - start_screen[0],
                y_screen[1] - start_screen[1],
            ),
            1e-6,
        )
        tolerance = self._s(6)
        tolerance_x = tolerance / pixels_per_x
        tolerance_y = tolerance / pixels_per_y
        dx = abs(point[0] - start[0])
        dy = abs(point[1] - start[1])
        if dy <= tolerance_y and dx > tolerance_x:
            return (
                aligned_edge_endpoint(start, point, "horizontal"),
                "horizontal",
            )
        if dx <= tolerance_x and dy > tolerance_y:
            return (
                aligned_edge_endpoint(start, point, "vertical"),
                "vertical",
            )
        return point, None

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

    def _update_projection_hover(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> None:
        """Remember which solid vertex or edge the projection tool will use."""
        self._hover_project_vertex = None
        self._hover_project_edge = None
        renderer = self.viewport.renderer
        camera = self.viewport.camera
        vertex = renderer.pick_vertex(
            pos, region.rect, document, camera
        )
        if vertex is not None:
            self._hover_project_vertex = vertex
            return
        edge = renderer.pick_edge(
            pos, region.rect, document, camera
        )
        if edge is not None:
            resolved = edge_for_ref(document, (edge[0], edge[1]))
            self._hover_project_edge = (
                edge[0], edge[1], resolved or edge[2]
            )

    def _draw_projection_hover(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        """Outline the solid vertex or edge the projection tool will copy."""
        if (
            self._selected_tool != "project"
            or (
                self._hover_project_vertex is None
                and self._hover_project_edge is None
            )
        ):
            return
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect.clip(previous_clip))
        camera = self.viewport.camera
        center = region.rect.center
        if self._hover_project_edge is not None:
            _, _, edge = self._hover_project_edge
            screen = [
                camera.project(point, center) for point in edge.chain
            ]
            if len(screen) >= 2:
                pygame.draw.lines(
                    surface, self.geometry_hover, False, screen,
                    self._s(3),
                )
        if self._hover_project_vertex is not None:
            _, vertex = self._hover_project_vertex
            screen = camera.project(vertex, center)
            pygame.draw.circle(
                surface, self.geometry_hover,
                (round(screen[0]), round(screen[1])),
                self._s(6), width=max(1, self._s(2)),
            )
            pygame.draw.circle(
                surface, self.geometry_hover,
                (round(screen[0]), round(screen[1])),
                max(1, self._s(2)),
            )
        surface.set_clip(previous_clip)

    def _project_at(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> None:
        """Project the exact solid vertex or edge under the cursor."""
        renderer = self.viewport.renderer
        camera = self.viewport.camera
        vertex = renderer.pick_vertex(
            pos, region.rect, document, camera
        )
        if vertex is not None and self.on_project_point is not None:
            self._clear_sketch_selection()
            self.on_project_point(vertex[0], vertex[1])
            return
        edge = renderer.pick_edge(
            pos, region.rect, document, camera
        )
        if edge is not None and self.on_project_edge is not None:
            self._clear_sketch_selection()
            self.on_project_edge(edge[0], edge[1])

    def _align_x_at(
        self, pos: Tuple[int, int], region: Rect, document: Document
    ) -> None:
        """Align the sketch X axis with the solid edge under the cursor."""
        edge = self.viewport.renderer.pick_edge(
            pos, region.rect, document, self.viewport.camera
        )
        if edge is not None and self.on_align_sketch_x is not None:
            self._clear_sketch_selection()
            self.on_align_sketch_x(edge[0], edge[1])

    def _run_tool(self, action: str, document: Document) -> None:
        if action == "sketch":
            self.on_new_sketch()
        elif action == "extrude":
            self.open_extrude(document)
        elif action == "fillet":
            self.create_sketch_window.close()
            self.fillet_window.open(
                self.FILLET_RADIUS,
                self._fillet_label(document),
            )
        elif action == "measure":
            self._activate_measure_tool("auto", document)
        elif action == "finish_sketch":
            document.active_sketch_id = None
            self._selected_tool = None
            self._constraint_tool = None
            self._clear_measure_state()
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
        self._hover_region = None
        self._hover_measurement_index = None
        self._hover_project_vertex = None
        self._hover_project_edge = None
        if self._line_menu_open:
            self._line_menu_hover = self._line_menu_index_at(
                pos, layout.toolbar, document
            )
        else:
            self._line_menu_hover = -1
        if self._constraint_menu_open:
            self._constraint_menu_hover = self._constraint_menu_index_at(
                pos, layout.toolbar, document
            )
        else:
            self._constraint_menu_hover = -1
        if self._measure_menu_open:
            self._measure_menu_hover = self._measure_menu_index_at(
                pos, layout.toolbar, document
            )
        else:
            self._measure_menu_hover = -1
        sketch = document.sketch(document.active_sketch_id)
        if self._drag_measurement_index is not None and sketch is not None:
            index = self._drag_measurement_index
            if self._drag_measurement_start_pos is not None:
                delta_x = pos[0] - self._drag_measurement_start_pos[0]
                delta_y = pos[1] - self._drag_measurement_start_pos[1]
                threshold = self._s(4)
                if (
                    delta_x * delta_x + delta_y * delta_y
                    > threshold * threshold
                ):
                    self._drag_measurement_moved = True
            if layout.viewport.collidepoint(pos) and 0 <= index < len(
                sketch.measurements
            ):
                world = self.viewport.unproject_on_plane(
                    pos, layout.viewport, sketch.frame()
                )
                if world is not None:
                    placement = self._measurement_placement_from_cursor(
                        sketch, index, world
                    )
                    if placement is not None:
                        placement += self._drag_measurement_grab_delta
                        if sketch.measurements[index].kind == "angle":
                            placement = max(1.0, placement)
                        self._drag_measurement_current = placement
            self._hover_measurement_index = index
            self._hover_sketch_entity = None
            self._line_preview = None
            return
        if layout.viewport.collidepoint(pos):
            self._hover_measurement_index = self._measurement_label_at(pos)
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
        if self._drag_edge_index is not None and sketch is not None:
            if layout.viewport.collidepoint(pos):
                world = self.viewport.unproject_on_plane(
                    pos, layout.viewport, sketch.frame()
                )
                anchor = self._drag_edge_anchor
                origin = self._drag_edge_origin
                if world is not None and anchor is not None and origin is not None:
                    delta_x = round(world[0] - anchor[0])
                    delta_y = round(world[1] - anchor[1])
                    self._drag_edge_current = (
                        (
                            origin[0][0] + delta_x,
                            origin[0][1] + delta_y,
                        ),
                        (
                            origin[1][0] + delta_x,
                            origin[1][1] + delta_y,
                        ),
                    )
            self._hover_sketch_entity = (
                "line", self._drag_edge_index
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
            snapped = snap_index is not None
            if snap_index is not None:
                preview = sketch.points[snap_index]
            else:
                world = self.viewport.unproject_on_plane(
                    pos, layout.viewport, sketch.frame()
                )
                preview = (
                    (round(world[0]), round(world[1]))
                    if world is not None
                    else None
                )
            if preview is not None and self._line_start is not None:
                preview, _ = self._auto_axis_point(
                    sketch, self._line_start, preview,
                    layout.viewport, snapped,
                )
            self._line_preview = preview
        else:
            self._line_preview = None
        if (
            self._selected_tool == "circle"
            and sketch is not None
            and layout.viewport.collidepoint(pos)
        ):
            snap_index = self._pick_sketch_point(
                pos, layout.viewport, sketch
            )
            if snap_index is not None:
                preview = sketch.points[snap_index]
            else:
                world = self.viewport.unproject_on_plane(
                    pos, layout.viewport, sketch.frame()
                )
                preview = (
                    (round(world[0]), round(world[1]))
                    if world is not None else None
                )
            center = self._circle_center
            if preview is not None and center is not None:
                diameter = 2.0 * math.hypot(
                    preview[0] - center[0],
                    preview[1] - center[1],
                )
                self._circle_preview = (center, diameter)
            else:
                self._circle_preview = (
                    (preview, 0.0) if preview is not None else None
                )
        else:
            self._circle_preview = None
        if (
            self._selected_tool == "rectangle"
            and sketch is not None
            and layout.viewport.collidepoint(pos)
        ):
            preview = self._rectangle_corner(
                pos, layout.viewport, sketch
            )
            self._rectangle_preview = (
                preview if self._rectangle_start is not None else None
            )
        else:
            self._rectangle_preview = None
        if self.create_sketch_window.update_hover(pos, layout.viewport):
            return
        if self.extrude_window.update_hover(pos, layout.viewport):
            return
        if self.fillet_window.update_hover(pos, layout.viewport):
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
                    if item.action not in self.SKETCH_INTERACTIVE_ACTIONS:
                        continue
                    if self._toolbar_item_hit_rect(item).collidepoint(pos):
                        self._hover_tool = item.action
                        break
                if self._hover_tool is not None:
                    break
        else:
            for group in self._solid_toolbar_groups(
                layout.toolbar, document
            ):
                for item in group.items:
                    if item.enabled and item.rect.collidepoint(pos):
                        self._hover_tool = item.action
                        break
                if self._hover_tool is not None:
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
            and self._hover_measurement_index is None
        ):
            self._hover_sketch_entity = self._pick_sketch_entity(
                pos, layout.viewport, sketch
            )
            if (
                self._hover_sketch_entity is not None
                and self._hover_sketch_entity[0] == "point"
                and self._selected_tool is None
                and self._constraint_tool is None
            ):
                loop_hit = self._circle_loop_at_point(
                    sketch, self._hover_sketch_entity[1]
                )
                if loop_hit is not None:
                    self._hover_sketch_entity = None
                    self._hover_region = (loop_hit,)
            if (
                self._hover_sketch_entity is None
                and self._hover_region is None
                and self._selected_tool is None
                and self._constraint_tool is None
            ):
                self._hover_region = self._pick_sketch_region(
                    pos, layout.viewport, sketch
                )

        if (
            self._selected_tool == "project"
            and self._sketch_toolbar_visible(document)
            and layout.viewport.collidepoint(pos)
        ):
            self._update_projection_hover(
                pos, layout.viewport, document
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
