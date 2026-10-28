"""Scene rendering for sketches and extruded solids."""

import math
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

import pygame

from ..document import Document
from ..faces import (
    Color, Edge, Face, edge_for_ref, edge_visible, iter_solid_edges,
    iter_solid_faces,
)
from ..profiles import union_profiles
from ..sketch import (
    Circle, PlaneFrame, Sketch, circle_polygon, plane_frame, point_on_plane,
)
from .camera import OrbitCamera, Point2, PROJECTION_SCALE
from .orientation_cube import OrientationCube

FaceEdgeKey = Tuple[Tuple[float, ...], Tuple[float, ...]]
FaceEdgeEntry = Optional[Tuple[FaceEdgeKey, bool]]

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
    projection: Color = (196, 140, 255)
    text_muted: Color = (125, 125, 136)
    edge: Color = (55, 55, 65)
    edge_selected: Color = (255, 193, 110)
    preview_selected: Color = (255, 193, 110)
    ghost_fill: Color = (225, 64, 64)
    ghost_edge: Color = (255, 120, 120)
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
        self._hole_surface: Optional[pygame.Surface] = None
        self._ghost_surface: Optional[pygame.Surface] = None
        self._edge_key_cache: Dict[
            int, Tuple[Face, List[FaceEdgeEntry]]
        ] = {}

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
        preview_document: Optional[Document] = None,
        ghost_faces: Sequence[Face] = (),
        highlight_features: Sequence[int] = (),
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
        self._draw_solids(
            surface, rect, preview_document or document, camera,
            highlight_features,
        )
        if ghost_faces:
            self._draw_ghost_solids(
                surface, rect, ghost_faces, camera
            )
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
            if not self._point_in_polygon(pos, polygon):
                continue
            if any(
                self._point_in_polygon(
                    pos,
                    [camera.project(vertex, center) for vertex in hole],
                )
                for hole in face.holes
            ):
                continue
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

    def pick_edge(
        self,
        pos: Point2,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> Optional[Tuple[int, int, Edge]]:
        """Return the solid edge nearest to a screen position."""
        center = rect.center
        view = camera.view_direction()
        tolerance = float(self._s(6))
        hits: List[Tuple[float, float, int, int, Edge]] = []
        for feature_id, edge_index, edge in iter_solid_edges(document):
            if not edge_visible(edge, view):
                continue
            start = camera.project(edge.start, center)
            end = camera.project(edge.end, center)
            distance = self._point_segment_distance(pos, start, end)
            if distance > tolerance:
                continue
            hits.append((
                distance,
                -camera.depth((edge.start, edge.end)),
                feature_id,
                edge_index,
                edge,
            ))
        if not hits:
            return None
        hits.sort(key=lambda item: (item[0], item[1]))
        _, _, feature_id, edge_index, edge = hits[0]
        return feature_id, edge_index, edge

    def pick_vertex(
        self,
        pos: Point2,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> Optional[Tuple[int, Tuple[float, float, float]]]:
        """Return the solid vertex nearest to a screen position."""
        center = rect.center
        tolerance = float(self._s(8))
        view = camera.view_direction()
        hits: List[
            Tuple[float, float, int, Tuple[float, float, float]]
        ] = []
        seen: Set[Tuple[float, ...]] = set()
        for feature_id, _, edge in iter_solid_edges(document):
            if not edge_visible(edge, view):
                continue
            for vertex in (edge.start, edge.end):
                key = tuple(round(value, 6) for value in vertex)
                if key in seen:
                    continue
                seen.add(key)
                screen = camera.project(vertex, center)
                distance = math.hypot(
                    pos[0] - screen[0], pos[1] - screen[1]
                )
                if distance > tolerance:
                    continue
                hits.append((
                    distance,
                    -camera.depth((vertex,)),
                    feature_id,
                    vertex,
                ))
        if not hits:
            return None
        hits.sort(key=lambda item: (item[0], item[1]))
        _, _, feature_id, vertex = hits[0]
        return feature_id, vertex

    @staticmethod
    def _point_segment_distance(
        pos: Point2, start: Point2, end: Point2
    ) -> float:
        """Return the pixel distance from a point to a line segment."""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-9:
            return math.hypot(pos[0] - start[0], pos[1] - start[1])
        t = (
            (pos[0] - start[0]) * dx + (pos[1] - start[1]) * dy
        ) / length_squared
        t = max(0.0, min(1.0, t))
        closest = (start[0] + dx * t, start[1] + dy * t)
        return math.hypot(pos[0] - closest[0], pos[1] - closest[1])

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

    def _preview_color(self, color: Color) -> Color:
        """Blend a body colour toward the active extrusion highlight."""
        base = self.palette.preview_selected
        return (
            round(color[0] * 0.3 + base[0] * 0.7),
            round(color[1] * 0.3 + base[1] * 0.7),
            round(color[2] * 0.3 + base[2] * 0.7),
        )

    def _draw_solids(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
        highlight_features: Sequence[int] = (),
    ) -> None:
        center = rect.center
        view_dir = camera.view_direction()
        highlighted = set(highlight_features)
        faces: List[
            Tuple[
                float, int, int, List[Point2], List[List[Point2]], Color,
                Optional[Tuple[bool, ...]],
            ]
        ] = []
        # Every mesh edge remembers which side of the solid it is on.  A
        # smooth seam whose two faces disagree is the silhouette of a curved
        # run, so the rounded corner reads as a corner instead of a smear.
        sides: Dict[
            Tuple[Tuple[float, ...], Tuple[float, ...]],
            List[Tuple[bool, float]],
        ] = {}
        smooth: Set[Tuple[Tuple[float, ...], Tuple[float, ...]]] = set()
        # Smooth seams have no outline, so a rasterization gap between the two
        # fills would show the background straight through the solid.  Keep
        # the projected span and colour of every visible smooth edge so the
        # nearer panel can seal it after both fills are down.
        seams: Dict[
            Tuple[Tuple[float, ...], Tuple[float, ...]],
            List[Tuple[float, Color, Point2, Point2]],
        ] = {}
        for feature_id, face_index, face in iter_solid_faces(document):
            front = (face.normal[0] * view_dir[0] +
                     face.normal[1] * view_dir[1] +
                     face.normal[2] * view_dir[2]) > 0
            depth = camera.depth(face.vertices)
            if face.label.startswith("Side face"):
                self._collect_edge_sides(
                    face, front, depth, sides, smooth
                )
            # Backface culling: skip faces facing away from camera
            if not front:
                continue
            polygon = [
                camera.project(vertex, center)
                for vertex in face.vertices
            ]
            holes = [
                [camera.project(vertex, center) for vertex in hole]
                for hole in face.holes
            ]
            color = (
                self._preview_color(face.color)
                if feature_id in highlighted else face.color
            )
            faces.append((
                depth,
                feature_id,
                face_index,
                polygon,
                holes,
                color,
                face.sharp_edges,
            ))
            sharp = face.sharp_edges
            if sharp is None:
                continue
            count = len(face.vertices)
            keys = self._face_edge_keys(face)
            for index in range(count):
                if index >= len(sharp) or sharp[index]:
                    continue
                entry = keys[index]
                if entry is None:
                    continue
                seams.setdefault(entry[0], []).append((
                    depth,
                    color,
                    polygon[index],
                    polygon[(index + 1) % count],
                ))

        faces.sort(key=lambda item: item[0])
        width = self._s(1)
        active = document.sketch(document.active_sketch_id)
        show_highlight = not (
            active is not None and active.is_custom_plane
        )
        selected: List[Tuple[List[Point2], List[List[Point2]]]] = []
        selected_faces = set(document.selected_faces)
        # Silhouette edges travel with the front panel they belong to.  A face
        # nearer to the camera is painted afterwards, so it hides a silhouette
        # that lies behind it, such as the wall of a concave notch covered by
        # the cap it was cut into.
        items: List[Tuple[float, int, object]] = [
            (item[0], 0, item) for item in faces
        ]
        items.extend(
            (depth, 1, edge)
            for depth, edge in self._silhouette_edges(
                center, camera, sides, smooth
            )
        )
        # Only an edge shared by two visible panels can be a crack through the
        # solid.  Sealing it at the nearer panel's depth keeps it underneath
        # that panel, so a later fill or crease outlines stays authoritative.
        for owners in seams.values():
            if len(owners) != 2:
                continue
            near = max(owners, key=lambda owner: owner[0])
            items.append((near[0], -1, near[1:]))
        items.sort(key=lambda item: (item[0], item[1]))
        for _, kind, payload in items:
            if kind == 1:
                start, end = payload  # type: ignore[misc]
                pygame.draw.line(
                    surface, self.palette.edge, start, end, width
                )
                continue
            if kind == -1:
                color, start, end = payload  # type: ignore[misc]
                pygame.draw.line(surface, color, start, end, width)
                continue
            (
                _, feature_id, face_index, polygon, holes, color, sharp_edges
            ) = payload  # type: ignore[misc]
            if len(polygon) < 3:
                continue
            if holes:
                self._draw_face_with_holes(
                    surface, rect, polygon, holes, color
                )
            else:
                pygame.draw.polygon(surface, color, polygon)
            self._draw_face_outline(
                surface, polygon, sharp_edges, width, holes
            )
            if (
                show_highlight
                and (feature_id, face_index) in selected_faces
            ):
                selected.append((polygon, holes))

        if selected:
            self._draw_face_selection(surface, rect, selected)
        if show_highlight:
            for reference in document.selected_edges:
                edge = edge_for_ref(document, reference)
                if edge is not None:
                    self._draw_edge_selection(surface, rect, camera, edge)

    def _draw_ghost_solids(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        faces: Sequence[Face],
        camera: OrbitCamera,
    ) -> None:
        """Draw removed material as a translucent red volume."""
        overlay = self._ghost_surface
        if overlay is None or overlay.get_size() != rect.size:
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            self._ghost_surface = overlay
        overlay.fill((0, 0, 0, 0))
        view_dir = camera.view_direction()
        # Only the outside of the removed volume belongs to the preview.  Its
        # inner faces lie on the surviving body, so drawing them would paint
        # the result red instead of showing the old, removed surface.
        visible = [
            face for face in faces
            if (
                face.normal[0] * view_dir[0]
                + face.normal[1] * view_dir[1]
                + face.normal[2] * view_dir[2]
            ) > 0.0
        ]
        ordered = sorted(
            visible, key=lambda face: camera.depth(face.vertices)
        )
        self._ghost_fills(overlay, ordered, rect, camera)
        self._ghost_outlines(overlay, ordered, rect, camera)
        surface.blit(overlay, rect.topleft)

    def _ghost_fills(
        self,
        overlay: pygame.Surface,
        faces: Sequence[Face],
        rect: pygame.Rect,
        camera: OrbitCamera,
    ) -> None:
        fill = (*self.palette.ghost_fill, 78)
        for face in faces:
            polygon = self._ghost_polygon(face.vertices, rect, camera)
            if len(polygon) < 3:
                continue
            pygame.draw.polygon(overlay, fill, polygon)
            for hole in face.holes:
                hole_polygon = self._ghost_polygon(hole, rect, camera)
                if len(hole_polygon) >= 3:
                    pygame.draw.polygon(
                        overlay, (0, 0, 0, 0), hole_polygon
                    )

    def _ghost_outlines(
        self,
        overlay: pygame.Surface,
        faces: Sequence[Face],
        rect: pygame.Rect,
        camera: OrbitCamera,
    ) -> None:
        edge = (*self.palette.ghost_edge, 190)
        width = max(1, self._s(1))
        for face in faces:
            polygon = self._ghost_polygon(face.vertices, rect, camera)
            if len(polygon) < 3:
                continue
            pygame.draw.lines(overlay, edge, True, polygon, width)
            for hole in face.holes:
                hole_polygon = self._ghost_polygon(hole, rect, camera)
                if len(hole_polygon) >= 3:
                    pygame.draw.lines(
                        overlay, edge, True, hole_polygon, width
                    )

    @staticmethod
    def _ghost_polygon(
        points: Sequence[Sequence[float]],
        rect: pygame.Rect,
        camera: OrbitCamera,
    ) -> List[Point2]:
        """Project ghost geometry into overlay-local coordinates."""
        polygon: List[Point2] = []
        for point in points:
            x, y = camera.project(point, rect.center)
            polygon.append((x - rect.x, y - rect.y))
        return polygon

    @staticmethod
    def _edge_key(
        start: Sequence[float], end: Sequence[float]
    ) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
        """Return a direction-independent key for one mesh edge."""
        first = tuple(round(value, 6) for value in start)
        second = tuple(round(value, 6) for value in end)
        return (first, second) if first <= second else (second, first)

    def _collect_edge_sides(
        self,
        face: Face,
        front: bool,
        depth: float,
        sides: Dict[
            Tuple[Tuple[float, ...], Tuple[float, ...]],
            List[Tuple[bool, float]],
        ],
        smooth: Set[Tuple[Tuple[float, ...], Tuple[float, ...]]],
    ) -> None:
        """Record the facing and depth of both panels along every edge."""
        for entry in self._face_edge_keys(face):
            if entry is None:
                continue
            key, is_smooth = entry
            sides.setdefault(key, []).append((front, depth))
            if is_smooth:
                smooth.add(key)

    def _face_edge_keys(self, face: Face) -> List[FaceEdgeEntry]:
        """Return one rounded mesh key per face edge, built once per face.

        Rounding every endpoint of a tessellated body on every frame is the
        single most expensive step of drawing a sliced body, so the keys
        travel with the face.  Entries are aligned with ``face.vertices``;
        degenerate edges map to ``None``.  Faces are rebuilt whenever their
        slices change, so a cached list always matches its face.
        """
        cached = self._edge_key_cache.get(id(face))
        if cached is not None and cached[0] is face:
            return cached[1]
        count = len(face.vertices)
        sharp = face.sharp_edges
        entries: List[FaceEdgeEntry] = []
        for index in range(count):
            start = face.vertices[index]
            end = face.vertices[(index + 1) % count]
            if start == end:
                entries.append(None)
                continue
            is_smooth = (
                sharp is not None
                and index < len(sharp)
                and not sharp[index]
            )
            entries.append((self._edge_key(start, end), is_smooth))
        if len(self._edge_key_cache) > 4096:
            self._edge_key_cache.clear()
        # Holding the face keeps its id unique for as long as the entry lives.
        self._edge_key_cache[id(face)] = (face, entries)
        return entries

    def _silhouette_edges(
        self,
        center: Point2,
        camera: OrbitCamera,
        sides: Dict[
            Tuple[Tuple[float, ...], Tuple[float, ...]],
            List[Tuple[bool, float]],
        ],
        smooth: Set[Tuple[Tuple[float, ...], Tuple[float, ...]]],
    ) -> List[Tuple[float, Tuple[Point2, Point2]]]:
        """Return the curved runs where the solid turns away from the camera.

        Tessellation seams stay invisible, but the seam that separates a
        visible panel from a hidden one is the silhouette of a rounded
        corner and has to be drawn.  Each edge carries the depth of the front
        panel it bounds, so the caller can sort it with the face fills.
        """
        silhouettes: List[Tuple[float, Tuple[Point2, Point2]]] = []
        for key in smooth:
            owners = sides.get(key)
            if not owners:
                continue
            visible = [depth for front, depth in owners if front]
            if not visible or len(visible) == len(owners):
                continue
            silhouettes.append((
                max(visible),
                (
                    camera.project(key[0], center),
                    camera.project(key[1], center),
                ),
            ))
        return silhouettes

    def _draw_edge_selection(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        camera: OrbitCamera,
        edge: Edge,
    ) -> None:
        """Highlight a selected solid edge in the geometry selection colour."""
        center = rect.center
        width = max(2, self._s(3))
        points = [camera.project(point, center) for point in edge.chain]
        if len(points) < 2:
            return
        pygame.draw.lines(
            surface, self.palette.edge_selected, False, points, width
        )

    def _draw_face_with_holes(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        polygon: List[Point2],
        holes: List[List[Point2]],
        color: Color,
    ) -> None:
        """Fill a cap face with transparent holes cut out of it."""
        overlay = self._hole_surface
        if overlay is None or overlay.get_size() != rect.size:
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            self._hole_surface = overlay
        overlay.fill((0, 0, 0, 0))
        local = [
            (point[0] - rect.x, point[1] - rect.y) for point in polygon
        ]
        pygame.draw.polygon(overlay, color, local)
        for hole in holes:
            local_hole = [
                (point[0] - rect.x, point[1] - rect.y) for point in hole
            ]
            pygame.draw.polygon(overlay, (0, 0, 0, 0), local_hole)
        surface.blit(overlay, rect.topleft)

    def _draw_face_outline(
        self,
        surface: pygame.Surface,
        polygon: List[Point2],
        sharp_edges: Optional[Tuple[bool, ...]],
        width: int,
        holes: Sequence[List[Point2]] = (),
    ) -> None:
        """Draw real face edges, skipping smooth tessellation seams."""
        if sharp_edges is None:
            pygame.draw.polygon(surface, self.palette.edge, polygon, width)
            for hole in holes:
                if len(hole) >= 3:
                    pygame.draw.polygon(
                        surface, self.palette.edge, hole, width
                    )
            return
        count = min(len(polygon), len(sharp_edges))
        for index in range(count):
            if not sharp_edges[index]:
                continue
            pygame.draw.line(
                surface,
                self.palette.edge,
                polygon[index],
                polygon[(index + 1) % count],
                width,
            )

    def _draw_face_selection(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        faces: List[Tuple[List[Point2], List[List[Point2]]]],
    ) -> None:
        overlay = self._face_surface
        if overlay is None or overlay.get_size() != rect.size:
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            self._face_surface = overlay
        overlay.fill((0, 0, 0, 0))
        local_faces = [([(point[0] - rect.x, point[1] - rect.y) for point in polygon], [[(point[0] - rect.x, point[1] - rect.y) for point in hole] for hole in holes]) for polygon, holes in faces]
        for local_polygon, _ in local_faces:
            pygame.draw.polygon(overlay, (*self.palette.active, 62), local_polygon)
        for _, local_holes in local_faces:
            for local_hole in local_holes:
                pygame.draw.polygon(overlay, (0, 0, 0, 0), local_hole)
        for loop in union_profiles([polygon for polygon, _ in local_faces]):
            pygame.draw.polygon(
                overlay, (*self.palette.active, 245), loop,
                max(1, self._s(2)),
            )
        for _, local_holes in local_faces:
            for local_hole in local_holes:
                pygame.draw.polygon(
                    overlay, (*self.palette.active, 245), local_hole,
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
            for index, (start, end) in enumerate(sketch.edges):
                line_color = (
                    self.palette.projection
                    if sketch.is_projected_edge(index) else color
                )
                start_point = camera.project(
                    point_on_plane(frame, sketch.points[start]), center
                )
                end_point = camera.project(
                    point_on_plane(frame, sketch.points[end]), center
                )
                self._draw_sketch_segment(
                    surface, line_color, start_point, end_point,
                    sketch.line_type,
                )
            for circle in sketch.circles:
                self._draw_sketch_circle(
                    surface, color, frame, circle, camera, center
                )

    def _draw_sketch_circle(self, surface: pygame.Surface, color: Color, frame: PlaneFrame, circle: Circle, camera: OrbitCamera, center: Tuple[int, int]) -> None:
        local_points = circle_polygon(circle)
        if not local_points:
            return
        points = [
            camera.project(point_on_plane(frame, local), center)
            for local in local_points
        ]
        pygame.draw.lines(
            surface, color, True, points, max(1, self._s(2))
        )

    def _draw_sketch_segment(
        self, surface: pygame.Surface, color: Color,
        start: Point2, end: Point2, line_type: str,
    ) -> None:
        width = self._s(2)
        if line_type == "construction":
            self._draw_dashed_line(
                surface, color, start, end, width,
                dash=self._s(5), gap=self._s(3),
            )
        elif line_type == "center":
            self._draw_dashed_line(
                surface, color, start, end, width,
                dash=self._s(12), gap=self._s(4),
            )
        else:
            pygame.draw.line(surface, color, start, end, width)

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
            for index, (x, y) in enumerate(sketch.points):
                point_color = (
                    self.palette.projection
                    if sketch.is_projected_point(index) else color
                )
                self._draw_sketch_point(surface, point_color, camera, frame, (x, y), center, radius)

    def _draw_sketch_point(self, surface: pygame.Surface, color: Color, camera: OrbitCamera, frame: PlaneFrame, point: Point2, center: Tuple[int, int], radius: int) -> None:
        projected = camera.project(point_on_plane(frame, point), center)
        center_point = (int(projected[0]), int(projected[1]))
        pygame.draw.circle(surface, color, center_point, radius)
        pygame.draw.circle(surface, self.palette.edge, center_point, radius, 1)

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
