"""Interactive orbitable sketch viewport for PY3DCAD."""

from typing import Callable, Optional, Sequence, Tuple

import pygame

from ..document import Document
from ..faces import Face, edge_for_ref, face_for_ref
from ..render import OrbitCamera, SceneRenderer
from ..sketch import PlaneLike, Point
from .layout import Rect


class Viewport:
    """Draws the scene with pan, orbit and zoom controls."""

    def __init__(self) -> None:
        self.ui_scale = 1.0
        self.camera = OrbitCamera()
        self.renderer = SceneRenderer()
        self.show_origin = True
        self.show_orientation_cube = True
        self._panning = False
        self._orbiting = False
        self._last_mouse = (0, 0)

        self._font: Optional[pygame.font.Font] = None
        self._font_small: Optional[pygame.font.Font] = None

    # ------------------------------------------------------------------
    # Camera compatibility properties
    # ------------------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self.camera.zoom

    @zoom.setter
    def zoom(self, value: float) -> None:
        self.camera.set_zoom(value)

    @property
    def pan_x(self) -> float:
        return self.camera.pan_x

    @pan_x.setter
    def pan_x(self, value: float) -> None:
        self.camera.pan_x = value

    @property
    def pan_y(self) -> float:
        return self.camera.pan_y

    @pan_y.setter
    def pan_y(self, value: float) -> None:
        self.camera.pan_y = value

    @property
    def yaw(self) -> float:
        return self.camera.yaw

    @yaw.setter
    def yaw(self, value: float) -> None:
        self.camera.yaw = value

    @property
    def pitch(self) -> float:
        return self.camera.pitch

    @pitch.setter
    def pitch(self, value: float) -> None:
        self.camera.pitch = value

    def set_origin_visible(self, visible: bool) -> None:
        self.show_origin = bool(visible)
        self.renderer.show_origin = self.show_origin

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.ui_scale) < 1e-6:
            return
        self.ui_scale = scale
        self._font = None
        self._font_small = None
        self.renderer.set_scale(scale)

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.ui_scale)))

    def _init_fonts(self) -> None:
        if self._font is not None:
            return
        self._font = pygame.font.SysFont("Segoe UI", self._s(13), bold=True)
        self._font_small = pygame.font.SysFont("Segoe UI", self._s(12))

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def project(
        self, point: Sequence[float], region: Rect
    ) -> Tuple[float, float]:
        return self.camera.project(point, region.center)

    def unproject_plane(
        self, pos: Tuple[int, int], region: Rect
    ) -> Point:
        """Map a screen position onto the Z=0 sketch plane (world mm)."""
        return self.camera.unproject_plane(pos, region.center)

    def unproject_on_plane(
        self, pos: Tuple[int, int], region: Rect, plane: PlaneLike
    ) -> Optional[Point]:
        """Map a screen position onto a sketch plane in local mm."""
        return self.camera.unproject_on_plane(pos, region.center, plane)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(
        self,
        surface: pygame.Surface,
        region: Rect,
        document: Document,
        active_tool: Optional[str] = None,
        selected_profiles: int = 0,
        preview_document: Optional[Document] = None,
        ghost_faces: Sequence[Face] = (),
        highlight_features: Sequence[int] = (),
    ) -> None:
        self._init_fonts()
        self.renderer.show_origin = self.show_origin
        pygame.draw.rect(
            surface, self.renderer.palette.background, region.rect
        )
        previous_clip = surface.get_clip()
        surface.set_clip(region.rect)

        self.renderer.draw(
            surface, region.rect, document, self.camera,
            preview_document=preview_document,
            ghost_faces=ghost_faces,
            highlight_features=highlight_features,
        )
        if self.show_orientation_cube:
            self.renderer.draw_orientation_cube(
                surface, region.rect, self.camera
            )
        self._draw_hud(
            surface, region, document, active_tool, selected_profiles
        )

        surface.set_clip(previous_clip)

    def _draw_hud(
        self, surface: pygame.Surface, region: Rect, document: Document,
        active_tool: Optional[str] = None, selected_profiles: int = 0,
    ) -> None:
        active = document.sketch(document.active_sketch_id)
        if active is not None:
            status = (
                f"{active.name}  ·  {active.display_plane}  ·  "
                f"{len(active.points)} points"
            )
            if active.lines:
                line_word = "line" if len(active.lines) == 1 else "lines"
                status += f"  ·  {len(active.lines)} {line_word}"
            if active.circles:
                circle_word = (
                    "circle" if len(active.circles) == 1 else "circles"
                )
                status += f"  ·  {len(active.circles)} {circle_word}"
            if active.projected_points:
                status += (
                    f"  ·  {len(active.projected_points)} projected"
                )
            profile_count = len(active.closed_loops())
            if active_tool == "extrude":
                hint = (
                    "Drag the blue arrow to set the distance"
                    "  ·  Enter to apply  ·  Esc to cancel"
                )
            elif active_tool == "line":
                hint = "Click to draw a line  ·  Esc to deselect"
            elif active_tool == "rectangle":
                hint = (
                    "Click one corner, then the opposite corner"
                    "  ·  Esc to deselect"
                )
            elif active_tool == "circle":
                hint = (
                    "Click the centre, then a point on the circle"
                    "  ·  Esc to deselect"
                )
            elif active_tool == "project":
                hint = (
                    "Click a solid edge or vertex to project it into the"
                    " sketch  ·  Esc to deselect"
                )
            elif active_tool != "point":
                if profile_count == 0:
                    hint = (
                        "No tool selected  ·  click Point or Line to draw"
                        "  ·  draw a closed loop to extrude"
                    )
                elif selected_profiles == 0:
                    hint = (
                        "No tool selected  ·  click inside a closed loop"
                        " to select it for extrude"
                    )
                else:
                    hint = (
                        "Closed loop selected  ·  Ctrl+click to add more"
                        "  ·  E to extrude"
                    )
            elif profile_count == 0:
                hint = (
                    "Click to place points  ·  draw a closed loop"
                    " to extrude"
                )
            elif selected_profiles == 0:
                hint = (
                    "Click to place points  ·  select a closed loop"
                    " for extrude"
                )
            else:
                hint = (
                    "Click to place points  ·  E to extrude selected loops"
                    "  ·  Esc to deselect"
                )
        else:
            status = document.name
            edge_count = len(document.selected_edges)
            face_count = len(document.selected_faces)
            if edge_count > 1:
                hint = (
                    f"{edge_count} edges selected"
                    "  ·  Ctrl+click to add or remove"
                )
            elif document.selected_edge is not None:
                edge = edge_for_ref(document, document.selected_edge)
                label = edge.label if edge is not None else "Edge"
                hint = (
                    f"{label} selected"
                    "  ·  Ctrl+click to add more"
                    "  ·  click empty space to deselect"
                )
            elif face_count > 1:
                hint = (
                    f"{face_count} faces selected"
                    "  ·  Ctrl+click to add or remove"
                    "  ·  S to sketch on the last face"
                )
            elif document.selected_face is not None:
                face = face_for_ref(document, document.selected_face)
                label = face.label if face is not None else "Face"
                hint = (
                    f"{label} selected"
                    "  ·  Ctrl+click to add more"
                    "  ·  S to sketch  ·  click empty space to deselect"
                )
            elif document.selected_plane is None:
                hint = "Click a plane or face to select it  ·  then press S to sketch"
            else:
                hint = (
                    f"{document.selected_plane} Plane selected"
                    "  ·  S to sketch  ·  click empty space to deselect"
                )

        color = self.renderer.palette.text_muted
        status_surf = self._font.render(status, True, color)
        surface.blit(
            status_surf,
            (region.x + self._s(12), region.y + self._s(10)),
        )
        hint_surf = self._font_small.render(hint, True, color)
        surface.blit(
            hint_surf,
            (
                region.x + self._s(12),
                region.bottom - hint_surf.get_height() - self._s(10),
            ),
        )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    @staticmethod
    def _shift_held(event: pygame.event.Event) -> bool:
        if getattr(event, "mod", 0) & pygame.KMOD_SHIFT:
            return True
        return bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)

    @staticmethod
    def _additive_held(event: pygame.event.Event) -> bool:
        """Return whether a click should add to the current selection."""
        modifiers = getattr(event, "mod", 0) | pygame.key.get_mods()
        return bool(
            modifiers
            & (pygame.KMOD_CTRL | pygame.KMOD_META | pygame.KMOD_SHIFT)
        )

    def handle_event(
        self,
        event: pygame.event.Event,
        region: Rect,
        document: Document,
        on_add_point: Optional[Callable[[Point], None]],
    ) -> bool:
        if event.type == pygame.MOUSEWHEEL:
            if not region.collidepoint(pygame.mouse.get_pos()):
                return False
            self.camera.zoom_by(1.12 ** event.y)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN:
            if not region.collidepoint(event.pos):
                return False
            if event.button == 2:
                self._orbiting = self._shift_held(event)
                self._panning = not self._orbiting
                self._last_mouse = event.pos
                return True
            if event.button == 1:
                sketch = document.sketch(document.active_sketch_id)
                if sketch is not None and on_add_point is not None:
                    world = self.unproject_on_plane(
                        event.pos, region, sketch.frame()
                    )
                    if world is not None:
                        on_add_point(
                            (round(world[0]), round(world[1]))
                        )
                    return True
                additive = self._additive_held(event)
                edge_hit = self.renderer.pick_edge(
                    event.pos, region.rect, document, self.camera
                )
                if edge_hit is not None:
                    feature_id, edge_index, _ = edge_hit
                    document.select_edge(
                        (feature_id, edge_index), additive
                    )
                    return True
                face_hit = self.renderer.pick_face(
                    event.pos, region.rect, document, self.camera
                )
                if face_hit is not None:
                    feature_id, face_index, _ = face_hit
                    document.select_face(
                        (feature_id, face_index), additive
                    )
                    return True
                plane = None
                if self.show_origin:
                    plane = self.renderer.pick_origin_plane(
                        event.pos, region.rect, self.camera
                    )
                if plane is not None:
                    document.clear_selection()
                    document.selected_plane = plane
                    document.active_sketch_id = None
                    return True
                document.clear_selection()
                return False

        if event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            if self._panning or self._orbiting:
                self._panning = False
                self._orbiting = False
                return True

        if event.type == pygame.MOUSEMOTION and self._orbiting:
            dx = event.pos[0] - self._last_mouse[0]
            dy = event.pos[1] - self._last_mouse[1]
            self.camera.orbit(dx, dy)
            self._last_mouse = event.pos
            return True

        if event.type == pygame.MOUSEMOTION and self._panning:
            dx = event.pos[0] - self._last_mouse[0]
            dy = event.pos[1] - self._last_mouse[1]
            self.camera.pan(dx, dy)
            self._last_mouse = event.pos
            return True

        return False
