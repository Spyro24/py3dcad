"""Scene rendering for sketches and extruded solids."""

import math
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import pygame

from ..document import Document
from ..faces import Color, Face, iter_solid_faces
from ..sketch import PlaneFrame, Sketch, plane_frame, point_on_plane
from .camera import OrbitCamera, Point2, PROJECTION_SCALE
from .orientation_cube import OrientationCube

GRID_STEP = 10.0
ORIGIN_GIZMO_SCALE = 0.9
ORIGIN_PLANE_HALF = 46.0
ORIGIN_PLANE_GAP = 12.0
ORIGIN_PLANE_GEOMETRY = (
    (
        "XY",
        (
            (ORIGIN_PLANE_GAP, ORIGIN_PLANE_GAP, 0.0),
            (ORIGIN_PLANE_HALF, ORIGIN_PLANE_GAP, 0.0),
            (ORIGIN_PLANE_HALF, ORIGIN_PLANE_HALF, 0.0),
            (ORIGIN_PLANE_GAP, ORIGIN_PLANE_HALF, 0.0),
        ),
    ),
    (
        "YZ",
        (
            (0.0, ORIGIN_PLANE_GAP, ORIGIN_PLANE_GAP),
            (0.0, ORIGIN_PLANE_HALF, ORIGIN_PLANE_GAP),
            (0.0, ORIGIN_PLANE_HALF, ORIGIN_PLANE_HALF),
            (0.0, ORIGIN_PLANE_GAP, ORIGIN_PLANE_HALF),
        ),
    ),
    (
        "ZX",
        (
            (ORIGIN_PLANE_GAP, 0.0, ORIGIN_PLANE_GAP),
            (ORIGIN_PLANE_HALF, 0.0, ORIGIN_PLANE_GAP),
            (ORIGIN_PLANE_HALF, 0.0, ORIGIN_PLANE_HALF),
            (ORIGIN_PLANE_GAP, 0.0, ORIGIN_PLANE_HALF),
        ),
    ),
)


@dataclass(frozen=True)
class ScenePalette:
    """Colours used by the viewport renderer."""

    background: Color = (24, 24, 30)
    grid: Color = (38, 38, 45)
    grid_major: Color = (46, 46, 54)
    x_axis: Color = (200, 70, 70)
    y_axis: Color = (70, 180, 90)
    z_axis: Color = (70, 110, 220)
    origin_plane: Color = (255, 224, 180)
    origin_plane_selected: Color = (255, 193, 110)
    origin_marker: Color = (205, 210, 220)
    origin_marker_edge: Color = (80, 85, 95)
    sketch: Color = (120, 145, 185)
    active: Color = (59, 130, 246)
    text_muted: Color = (125, 125, 136)
    edge: Color = (55, 55, 65)
    cube_top: Color = (145, 145, 155)
    cube_bottom: Color = (82, 82, 92)
    cube_side: Color = (122, 122, 132)
    cube_side_dark: Color = (104, 104, 114)
    cube_text: Color = (28, 28, 34)
    cube_edge: Color = (22, 22, 28)


class SceneRenderer:
    """Draws the document's scene into a viewport rectangle."""

    def __init__(self, palette: Optional[ScenePalette] = None) -> None:
        self.palette = palette or ScenePalette()
        self.ui_scale = 1.0
        self.show_origin = True
        self.orientation_cube = OrientationCube()
        self._font_small: Optional[pygame.font.Font] = None
        self._plane_surface: Optional[pygame.Surface] = None
        self._face_surface: Optional[pygame.Surface] = None

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.ui_scale) < 1e-6:
            return
        self.ui_scale = scale
        self._font_small = None
        self.orientation_cube.set_scale(scale)

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.ui_scale)))

    def _project_origin_gizmo(
        self,
        camera: OrbitCamera,
        center: Point2,
        point: Tuple[float, float, float],
        origin: Optional[Point2] = None,
    ) -> Point2:
        """Project origin-gizmo geometry at a fixed screen size."""
        if origin is None:
            origin = camera.project((0.0, 0.0, 0.0), center)
        projected = camera.project(point, center)
        reference = ORIGIN_GIZMO_SCALE * self.ui_scale
        current = PROJECTION_SCALE * camera.zoom
        factor = reference / current if current else 1.0
        return (
            origin[0] + (projected[0] - origin[0]) * factor,
            origin[1] + (projected[1] - origin[1]) * factor,
        )

    def _init_fonts(self) -> None:
        if self._font_small is not None:
            return
        self._font_small = pygame.font.SysFont(
            "Segoe UI", self._s(12)
        )

    def draw(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> None:
        self._init_fonts()
        active = document.sketch(document.active_sketch_id)
        custom_active = active is not None and active.is_custom_plane
        if not custom_active:
            self._draw_grid(
                surface, rect, camera, self._grid_plane(document)
            )
        if self.show_origin:
            self._draw_origin_planes(
                surface, rect, camera, document.selected_plane
            )
            self._draw_axes(surface, rect, camera)
            self._draw_origin_marker(surface, rect, camera)
        self._draw_sketch_lines(surface, rect, document, camera)
        self._draw_solids(surface, rect, document, camera)
        if custom_active:
            # A face sketch lives on top of its solid, so its local grid and
            # the sketch itself must render after the solid faces.
            self._draw_grid(surface, rect, camera, active.frame())
            self._draw_sketch_lines(
                surface, rect, document, camera, only_active=True
            )
        self._draw_sketch_points(surface, rect, document, camera)

    def draw_orientation_cube(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        camera: OrbitCamera,
    ) -> None:
        self.orientation_cube.draw(surface, rect, camera, self.palette)

    @staticmethod
    def _grid_plane(document: Document) -> PlaneFrame:
        """Return the local grid plane for the sketch being edited.

        The grid belongs to a sketch, not to the document or the current tree
        selection. When no sketch is active the neutral world XY grid is used.
        """
        sketch = document.sketch(document.active_sketch_id)
        if sketch is not None:
            return sketch.frame()
        return plane_frame("XY")

    def _draw_grid(
        self, surface: pygame.Surface, rect: pygame.Rect,
        camera: OrbitCamera, plane: PlaneFrame,
    ) -> None:
        bounds = self._visible_bounds(rect, camera, plane)
        if bounds is None:
            return
        min_u, min_v, max_u, max_v = bounds
        span = max(max_u - min_u, max_v - min_v)
        step = GRID_STEP
        while span / step > 160:
            step *= 2

        center = rect.center
        start_u = int(min_u // step) * step
        start_v = int(min_v // step) * step
        color = self.palette.grid
        major = self.palette.grid_major

        u = start_u
        while u <= max_u:
            p1 = camera.project(
                point_on_plane(plane, (u, min_v)), center
            )
            p2 = camera.project(
                point_on_plane(plane, (u, max_v)), center
            )
            pygame.draw.line(
                surface, major if abs(u) < 1e-6 else color, p1, p2, 1
            )
            u += step

        v = start_v
        while v <= max_v:
            p1 = camera.project(
                point_on_plane(plane, (min_u, v)), center
            )
            p2 = camera.project(
                point_on_plane(plane, (max_u, v)), center
            )
            pygame.draw.line(
                surface, major if abs(v) < 1e-6 else color, p1, p2, 1
            )
            v += step

    def _visible_bounds(
        self, rect: pygame.Rect, camera: OrbitCamera,
        plane: PlaneFrame = plane_frame("XY"),
    ) -> Optional[Tuple[float, float, float, float]]:
        """Return the visible local bounds on a sketch plane."""
        _, _, _, normal = plane_frame(plane)
        view = camera.view_direction()
        facing = abs(
            normal[0] * view[0]
            + normal[1] * view[1]
            + normal[2] * view[2]
        )
        if facing < 0.08:
            return None

        center = rect.center
        corners = [
            camera.unproject_on_plane(
                (rect.left, rect.top), center, plane
            ),
            camera.unproject_on_plane(
                (rect.right, rect.top), center, plane
            ),
            camera.unproject_on_plane(
                (rect.left, rect.bottom), center, plane
            ),
            camera.unproject_on_plane(
                (rect.right, rect.bottom), center, plane
            ),
        ]
        if any(point is None for point in corners):
            return None
        xs = [point[0] for point in corners if point is not None]
        ys = [point[1] for point in corners if point is not None]
        min_u, max_u = min(xs), max(xs)
        min_v, max_v = min(ys), max(ys)
        span = max(max_u - min_u, max_v - min_v)
        if span > 6000.0:
            return None
        return min_u, min_v, max_u, max_v

    def _project_origin_planes(
        self, rect: pygame.Rect, camera: OrbitCamera
    ) -> List[Tuple[str, float, List[Point2]]]:
        """Project the three selectable origin planes to screen space."""
        center = rect.center
        origin = camera.project((0.0, 0.0, 0.0), center)
        items: List[Tuple[str, float, List[Point2]]] = []
        for name, vertices in ORIGIN_PLANE_GEOMETRY:
            polygon = [
                self._project_origin_gizmo(camera, center, vertex, origin)
                for vertex in vertices
            ]
            items.append((name, camera.depth(vertices), polygon))
        return items

    def pick_origin_plane(
        self, pos: Point2, rect: pygame.Rect, camera: OrbitCamera
    ) -> Optional[str]:
        """Return the frontmost origin plane under a screen position."""
        if not self.show_origin:
            return None
        hits = [
            item
            for item in self._project_origin_planes(rect, camera)
            if self._point_in_polygon(pos, item[2])
        ]
        if not hits:
            return None
        hits.sort(key=lambda item: item[1])
        return hits[-1][0]

    def pick_face(
        self,
        pos: Point2,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> Optional[Tuple[int, int, Face]]:
        """Return the frontmost extruded-solid face under a screen position."""
        center = rect.center
        hits: List[Tuple[float, int, int, Face]] = []
        for feature_id, face_index, face in iter_solid_faces(document):
            polygon = [
                camera.project(vertex, center) for vertex in face.vertices
            ]
            if len(polygon) < 3:
                continue
            if self._point_in_polygon(pos, polygon):
                hits.append((
                    camera.depth(face.vertices),
                    feature_id,
                    face_index,
                    face,
                ))
        if not hits:
            return None
        hits.sort(key=lambda item: item[0])
        _, feature_id, face_index, face = hits[-1]
        return feature_id, face_index, face

    @staticmethod
    def _point_in_polygon(pos: Point2, polygon: List[Point2]) -> bool:
        x, y = pos
        inside = False
        count = len(polygon)
        for index in range(count):
            x1, y1 = polygon[index]
            x2, y2 = polygon[(index + 1) % count]
            if (y1 > y) != (y2 > y):
                crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < crossing_x:
                    inside = not inside
        return inside

    def _draw_origin_planes(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        camera: OrbitCamera,
        selected_plane: Optional[str] = None,
    ) -> None:
        overlay = self._plane_surface
        if overlay is None or overlay.get_size() != rect.size:
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            self._plane_surface = overlay

        items = self._project_origin_planes(rect, camera)
        items.sort(key=lambda item: item[1])
        for name, _, polygon in items:
            local_polygon = [
                (point[0] - rect.x, point[1] - rect.y)
                for point in polygon
            ]
            selected = name == selected_plane
            color = (
                self.palette.origin_plane_selected
                if selected else self.palette.origin_plane
            )
            fill = (*color, 210 if selected else 175)
            overlay.fill((0, 0, 0, 0))
            pygame.draw.polygon(overlay, fill, local_polygon)
            if selected:
                pygame.draw.polygon(
                    overlay, (*self.palette.active, 235),
                    local_polygon, max(1, self._s(2)),
                )
            surface.blit(overlay, rect.topleft)

    def _draw_axes(
        self, surface: pygame.Surface, rect: pygame.Rect, camera: OrbitCamera
    ) -> None:
        center = rect.center
        origin = camera.project((0, 0, 0), center)
        length = 60.0
        for axis, color, label in (
            ((1, 0, 0), self.palette.x_axis, "X"),
            ((0, 1, 0), self.palette.y_axis, "Y"),
            ((0, 0, 1), self.palette.z_axis, "Z"),
        ):
            end = self._project_origin_gizmo(
                camera,
                center,
                (
                    axis[0] * length,
                    axis[1] * length,
                    axis[2] * length,
                ),
                origin,
            )
            self._draw_dashed_line(surface, color, origin, end)
            text = self._font_small.render(label, True, color)
            surface.blit(text, (end[0] + 4, end[1] - 6))

    def _draw_dashed_line(
        self,
        surface: pygame.Surface,
        color: Color,
        start: Point2,
        end: Point2,
        width: int = 2,
        dash: int = 9,
        gap: int = 5,
    ) -> None:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0.0:
            return
        ux = dx / length
        uy = dy / length
        reach = 0.0
        while reach < length:
            stop = min(reach + dash, length)
            pygame.draw.line(
                surface,
                color,
                (start[0] + ux * reach, start[1] + uy * reach),
                (start[0] + ux * stop, start[1] + uy * stop),
                width,
            )
            reach += dash + gap

    def _draw_origin_marker(
        self, surface: pygame.Surface, rect: pygame.Rect, camera: OrbitCamera
    ) -> None:
        origin = camera.project((0, 0, 0), rect.center)
        radius = max(4, self._s(5))
        pygame.draw.circle(surface, self.palette.origin_marker, origin, radius)
        pygame.draw.circle(
            surface,
            self.palette.origin_marker_edge,
            origin,
            radius,
            max(1, self._s(1)),
        )

    def _draw_solids(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> None:
        center = rect.center
        faces: List[
            Tuple[float, int, int, List[Point2], Color]
        ] = []
        for feature_id, face_index, face in iter_solid_faces(document):
            polygon = [
                camera.project(vertex, center)
                for vertex in face.vertices
            ]
            faces.append((
                camera.depth(face.vertices),
                feature_id,
                face_index,
                polygon,
                face.color,
            ))

        faces.sort(key=lambda item: item[0])
        width = self._s(1)
        active = document.sketch(document.active_sketch_id)
        show_highlight = not (
            active is not None and active.is_custom_plane
        )
        selected: List[List[Point2]] = []
        for _, feature_id, face_index, polygon, color in faces:
            if len(polygon) < 3:
                continue
            pygame.draw.polygon(surface, color, polygon)
            pygame.draw.polygon(surface, self.palette.edge, polygon, width)
            if (
                show_highlight
                and (feature_id, face_index) == document.selected_face
            ):
                selected.append(polygon)

        for polygon in selected:
            self._draw_face_selection(surface, rect, polygon)

    def _draw_face_selection(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        polygon: List[Point2],
    ) -> None:
        overlay = self._face_surface
        if overlay is None or overlay.get_size() != rect.size:
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            self._face_surface = overlay
        overlay.fill((0, 0, 0, 0))
        local_polygon = [
            (point[0] - rect.x, point[1] - rect.y) for point in polygon
        ]
        pygame.draw.polygon(
            overlay, (*self.palette.active, 62), local_polygon
        )
        pygame.draw.polygon(
            overlay, (*self.palette.active, 245), local_polygon,
            max(1, self._s(2)),
        )
        surface.blit(overlay, rect.topleft)

    def _draw_sketch_lines(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
        only_active: bool = False,
    ) -> None:
        center = rect.center
        for sketch in self._visible_sketches(document):
            if only_active and sketch.id != document.active_sketch_id:
                continue
            color = (
                self.palette.active
                if sketch.id == document.active_sketch_id
                else self.palette.sketch
            )
            frame = sketch.frame()
            points = [
                camera.project(point_on_plane(frame, (x, y)), center)
                for x, y in sketch.points
            ]
            if len(points) >= 2:
                pygame.draw.lines(
                    surface, color, len(points) >= 3, points, self._s(2)
                )

    def _draw_sketch_points(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> None:
        center = rect.center
        radius = self._s(3)
        for sketch in self._visible_sketches(document):
            color = (
                self.palette.active
                if sketch.id == document.active_sketch_id
                else self.palette.sketch
            )
            frame = sketch.frame()
            for x, y in sketch.points:
                point = camera.project(
                    point_on_plane(frame, (x, y)), center
                )
                center_point = (int(point[0]), int(point[1]))
                pygame.draw.circle(
                    surface, color, center_point, radius
                )
                pygame.draw.circle(
                    surface, self.palette.edge, center_point, radius, 1
                )

    @staticmethod
    def _visible_sketches(document: Document) -> Iterator[Sketch]:
        """Hide sketches consumed by a feature unless they are being edited."""
        consumed = {feature.sketch_id for feature in document.features}
        for sketch in document.sketches:
            if (
                sketch.id in consumed
                and sketch.id != document.active_sketch_id
            ):
                continue
            yield sketch
