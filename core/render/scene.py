"""Scene rendering for sketches and extruded solids."""

import math
from dataclasses import dataclass
from typing import (
    Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple,
)

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
from .edges import FaceEdgeCache, FaceEdgeEntry
from .orientation_cube import OrientationCube

# Draws the solid layer and returns whether it did so (the OpenGL path).
SolidDrawer = Callable[
    [pygame.Surface, pygame.Rect, Document, OrbitCamera, Sequence[int]],
    bool,
]

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
    constrained: Color = (245, 245, 248)
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
        self._label_cache: Dict[Tuple[str, Color], pygame.Surface] = {}
        self._ghost_surface: Optional[pygame.Surface] = None
        self.edge_cache = FaceEdgeCache()
        self._constraint_cache: Dict[
            int,
            Tuple[
                Sketch,
                Tuple[object, ...],
                Tuple[Set[int], Set[int], Set[int]],
            ],
        ] = {}
        # Constraint display options
        self.constraint_options: Dict[str, bool] = {
            "constrained_lines": True,
            "constrained_circles": True,
            "constraint_dim_lines": True,
            "coincident_constraints": True,
            "equal_constraints": True,
            "measurement_annotations": True,
        }

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.ui_scale) < 1e-6:
            return
        self.ui_scale = scale
        self._font_small = None
        self._label_cache.clear()
        self.orientation_cube.set_scale(scale)

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.ui_scale)))

    @staticmethod
    def _layer_bounds(
        rect: pygame.Rect,
        groups: Sequence[Sequence[Point2]],
        pad: int = 0,
    ) -> Optional[pygame.Rect]:
        """Return the part of the viewport that the given polygons touch."""
        xs = [point[0] for group in groups for point in group]
        ys = [point[1] for group in groups for point in group]
        if not xs:
            return None
        left = math.floor(min(xs)) - pad
        top = math.floor(min(ys)) - pad
        right = math.ceil(max(xs)) + pad
        bottom = math.ceil(max(ys)) + pad
        bounds = pygame.Rect(left, top, right - left, bottom - top).clip(rect)
        if bounds.width <= 0 or bounds.height <= 0:
            return None
        return bounds

    @staticmethod
    def _local(points: Sequence[Point2], origin: Tuple[int, int]) -> List[Point2]:
        """Shift screen points into the coordinate space of a layer."""
        ox, oy = origin
        return [(x - ox, y - oy) for x, y in points]

    def _gizmo_factor(self, camera: OrbitCamera) -> float:
        reference = ORIGIN_GIZMO_SCALE * self.ui_scale
        current = PROJECTION_SCALE * camera.zoom
        return reference / current if current else 1.0

    def _project_origin_gizmo(
        self,
        camera: OrbitCamera,
        center: Point2,
        point: Tuple[float, float, float],
        origin: Optional[Point2] = None,
        factor: Optional[float] = None,
    ) -> Point2:
        """Project origin-gizmo geometry at a fixed screen size."""
        if origin is None:
            origin = camera.project((0.0, 0.0, 0.0), center)
        projected = camera.project(point, center)
        if factor is None:
            factor = self._gizmo_factor(camera)
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
        draw_solids: bool = True,
        solid_drawer: Optional[SolidDrawer] = None,
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
        if draw_solids:
            self._draw_solid_layer(
                surface, rect, preview_document or document, camera,
                highlight_features, solid_drawer,
            )
        if draw_solids and ghost_faces:
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
        factor = self._gizmo_factor(camera)
        items: List[Tuple[str, float, List[Point2]]] = []
        for name, vertices in ORIGIN_PLANE_GEOMETRY:
            polygon = [
                self._project_origin_gizmo(
                    camera, center, vertex, origin, factor
                )
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
        # reversed() keeps the original tie-break: the last equal hit wins.
        return max(reversed(hits), key=lambda item: item[1])[0]

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
        # reversed() keeps the original tie-break: the last equal hit wins.
        _, feature_id, face_index, face = max(
            reversed(hits), key=lambda item: item[0]
        )
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
        _, _, feature_id, edge_index, edge = min(
            hits, key=lambda item: (item[0], item[1])
        )
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
        items = self._project_origin_planes(rect, camera)
        items.sort(key=lambda item: item[1])
        width = max(1, self._s(2))
        for name, _, polygon in items:
            selected = name == selected_plane
            color = (
                self.palette.origin_plane_selected
                if selected else self.palette.origin_plane
            )
            fill = (*color, 210 if selected else 175)
            bounds = self._layer_bounds(rect, [polygon], pad=width)
            if bounds is None:
                continue
            layer = pygame.Surface(bounds.size, pygame.SRCALPHA)
            local_polygon = self._local(polygon, bounds.topleft)
            pygame.draw.polygon(layer, fill, local_polygon)
            if selected:
                pygame.draw.polygon(
                    layer, (*self.palette.active, 235),
                    local_polygon, width,
                )
            surface.blit(layer, bounds.topleft)

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
            key = (label, color)
            text = self._label_cache.get(key)
            if text is None:
                text = self._font_small.render(label, True, color)
                self._label_cache[key] = text
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

    def _draw_solid_layer(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
        highlight_features: Sequence[int],
        solid_drawer: Optional[SolidDrawer],
    ) -> None:
        """Draw solids through the hardware path, else in software."""
        if solid_drawer is not None and solid_drawer(
            surface, rect, document, camera, highlight_features
        ):
            self._draw_solid_overlays(surface, rect, document, camera)
            return
        self._draw_solids(
            surface, rect, document, camera, highlight_features
        )

    def _draw_solid_overlays(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> None:
        """Draw selection highlights on top of a hardware solid layer."""
        active = document.sketch(document.active_sketch_id)
        if active is not None and active.is_custom_plane:
            return
        center = rect.center
        view = camera.view_direction()
        selected = set(document.selected_faces)
        if selected:
            polygons: List[Tuple[List[Point2], List[List[Point2]]]] = []
            for feature_id, face_index, face in iter_solid_faces(document):
                if (feature_id, face_index) not in selected:
                    continue
                if sum(
                    face.normal[index] * view[index] for index in range(3)
                ) <= 0:
                    continue
                polygons.append((
                    [
                        camera.project(vertex, center)
                        for vertex in face.vertices
                    ],
                    [
                        [
                            camera.project(vertex, center)
                            for vertex in hole
                        ]
                        for hole in face.holes
                    ],
                ))
            if polygons:
                self._draw_face_selection(surface, rect, polygons)
        for reference in document.selected_edges:
            edge = edge_for_ref(document, reference)
            if edge is not None:
                self._draw_edge_selection(surface, rect, camera, edge)

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
            is_side = face.label.startswith("Side face")
            # Depth is only needed for drawn panels and for side panels, which
            # feed the silhouette pass even when they face away.
            if not front and not is_side:
                continue
            depth = camera.depth(face.vertices)
            if is_side:
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
        projected = [
            (
                self._ghost_polygon(face.vertices, rect, camera),
                [self._ghost_polygon(hole, rect, camera) for hole in face.holes],
            )
            for face in ordered
        ]
        self._ghost_fills(overlay, projected)
        self._ghost_outlines(overlay, projected)
        surface.blit(overlay, rect.topleft)

    def _ghost_fills(
        self,
        overlay: pygame.Surface,
        projected: Sequence[Tuple[List[Point2], List[List[Point2]]]],
    ) -> None:
        fill = (*self.palette.ghost_fill, 78)
        for polygon, holes in projected:
            if len(polygon) < 3:
                continue
            pygame.draw.polygon(overlay, fill, polygon)
            for hole_polygon in holes:
                if len(hole_polygon) >= 3:
                    pygame.draw.polygon(overlay, (0, 0, 0, 0), hole_polygon)

    def _ghost_outlines(
        self,
        overlay: pygame.Surface,
        projected: Sequence[Tuple[List[Point2], List[List[Point2]]]],
    ) -> None:
        edge = (*self.palette.ghost_edge, 190)
        width = max(1, self._s(1))
        for polygon, holes in projected:
            if len(polygon) < 3:
                continue
            pygame.draw.lines(overlay, edge, True, polygon, width)
            for hole_polygon in holes:
                if len(hole_polygon) >= 3:
                    pygame.draw.lines(overlay, edge, True, hole_polygon, width)

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
        """Return one rounded mesh key per face edge, built once per face."""
        return self.edge_cache.edges(face)

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
        bounds = self._layer_bounds(rect, [polygon])
        if bounds is None:
            return
        layer = pygame.Surface(bounds.size, pygame.SRCALPHA)
        pygame.draw.polygon(layer, color, self._local(polygon, bounds.topleft))
        for hole in holes:
            pygame.draw.polygon(
                layer, (0, 0, 0, 0), self._local(hole, bounds.topleft)
            )
        surface.blit(layer, bounds.topleft)

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
        width = max(1, self._s(2))
        groups = [polygon for polygon, _ in faces]
        groups.extend(hole for _, holes in faces for hole in holes)
        bounds = self._layer_bounds(rect, groups, pad=width)
        if bounds is None:
            return
        origin = bounds.topleft
        layer = pygame.Surface(bounds.size, pygame.SRCALPHA)
        local_polygons = [self._local(polygon, origin) for polygon, _ in faces]
        local_holes = [
            [self._local(hole, origin) for hole in holes] for _, holes in faces
        ]
        for local_polygon in local_polygons:
            pygame.draw.polygon(layer, (*self.palette.active, 62), local_polygon)
        for holes in local_holes:
            for local_hole in holes:
                pygame.draw.polygon(layer, (0, 0, 0, 0), local_hole)
        for loop in union_profiles(local_polygons):
            pygame.draw.polygon(layer, (*self.palette.active, 245), loop, width)
        for holes in local_holes:
            for local_hole in holes:
                pygame.draw.polygon(
                    layer, (*self.palette.active, 245), local_hole, width
                )
        surface.blit(layer, origin)

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
            if sketch.id != document.active_sketch_id:
                # A finished sketch is only a profile source: show its closed
                # loops and hide the construction/open edges and points.
                self._draw_closed_sketch_loops(
                    surface, document, sketch, camera, center
                )
                continue
            color = self._sketch_color(document, sketch)
            _, constrained_edges, constrained_circles = self._constraints(sketch)
            frame = sketch.frame()
            show_equal = self.constraint_options.get(
                "equal_constraints", True
            )
            # Collect the entities taking part in equalities once per sketch
            # instead of rescanning the constraint list inside every loop.
            equality_edges: Set[int] = set()
            equality_circles: Set[int] = set()
            for equal in sketch.equals:
                if equal.first[0] == "line" and equal.second[0] == "line":
                    equality_edges.add(equal.first[1])
                    equality_edges.add(equal.second[1])
                elif equal.first[0] == "circle" and equal.second[0] == "circle":
                    equality_circles.add(equal.first[1])
                    equality_circles.add(equal.second[1])

            for index in range(len(sketch.edges)):
                # Determine if edge should be shown based on constraint options
                show_edge = True
                is_constrained = index in constrained_edges

                # Special handling for equal constraints
                if is_constrained:
                    if not show_equal:
                        show_edge = False
                    elif index in equality_edges:
                        show_edge = self.constraint_options.get(
                            "constrained_lines", True
                        )

                line_color = (
                    self.palette.projection
                    if sketch.is_projected_edge(index) else (
                        self.palette.constrained
                        if is_constrained and show_edge
                        else color
                    )
                )
                screen = [
                    camera.project(point_on_plane(frame, point), center)
                    for point in sketch.edge_points(index)
                ]
                for start_point, end_point in zip(screen, screen[1:]):
                    self._draw_sketch_segment(
                        surface, line_color, start_point, end_point,
                        sketch.line_type,
                    )
            
            for index, circle in enumerate(sketch.circles):
                is_constrained = index in constrained_circles
                show_circle = True

                if is_constrained:
                    if not show_equal:
                        show_circle = False
                    elif index in equality_circles:
                        show_circle = self.constraint_options.get(
                            "constrained_circles", True
                        )

                circle_color = (
                    self.palette.projection
                    if sketch.is_projected_circle(index) else (
                        self.palette.constrained
                        if is_constrained and show_circle
                        else color
                    )
                )
                self._draw_sketch_circle(
                    surface, circle_color, frame, circle, camera, center
                )

    def _draw_closed_sketch_loops(
        self,
        surface: pygame.Surface,
        document: Document,
        sketch: Sketch,
        camera: OrbitCamera,
        center: Tuple[int, int],
    ) -> None:
        """Draw only the closed profiles of a sketch that is not edited."""
        color = self._sketch_color(document, sketch)
        frame = sketch.frame()
        width = max(1, self._s(2))
        for loop in sketch.closed_loops():
            points = [
                camera.project(point_on_plane(frame, point), center)
                for point in sketch.loop_points(loop)
            ]
            if len(points) < 2:
                continue
            if sketch.line_type == "normal":
                pygame.draw.lines(surface, color, True, points, width)
                continue
            for start_point, end_point in zip(
                points, points[1:] + points[:1]
            ):
                self._draw_sketch_segment(
                    surface, color, start_point, end_point,
                    sketch.line_type,
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
            if sketch.id != document.active_sketch_id:
                # Finished sketches expose closed profiles only; their
                # control points belong to the editor.
                continue
            color = self._sketch_color(document, sketch)
            constrained_points, _, _ = self._constraints(sketch)
            frame = sketch.frame()
            
            # Get all points involved in coincidence constraints
            coincidence_points = set()
            for coincidence in sketch.coincidences:
                if coincidence.first[0] == "point" and coincidence.second[0] == "point":
                    coincidence_points.add(coincidence.first[1])
                    coincidence_points.add(coincidence.second[1])
                elif coincidence.first[0] == "point" and coincidence.second[0] == "origin":
                    coincidence_points.add(coincidence.first[1])
                elif coincidence.first[0] == "origin" and coincidence.second[0] == "point":
                    coincidence_points.add(coincidence.second[1])
            
            for index, (x, y) in enumerate(sketch.points):
                # Determine if point should be shown based on constraint options
                show_point = True
                is_constrained = index in constrained_points
                
                # Special handling for coincidence constraints
                if is_constrained:
                    if self.constraint_options.get("coincident_constraints", True):
                        # Show if it's in coincidence constraints
                        if index in coincidence_points:
                            show_point = self.constraint_options.get("constrained_lines", True)
                    else:
                        show_point = False
                
                point_color = (
                    self.palette.projection
                    if sketch.is_projected_point(index) else (
                        self.palette.constrained
                        if is_constrained and show_point
                        else color
                    )
                )
                self._draw_sketch_point(surface, point_color, camera, frame, (x, y), center, radius)

    def _draw_sketch_point(self, surface: pygame.Surface, color: Color, camera: OrbitCamera, frame: PlaneFrame, point: Point2, center: Tuple[int, int], radius: int) -> None:
        projected = camera.project(point_on_plane(frame, point), center)
        center_point = (int(projected[0]), int(projected[1]))
        pygame.draw.circle(surface, color, center_point, radius)
        pygame.draw.circle(surface, self.palette.edge, center_point, radius, 1)

    def _constraints(
        self, sketch: Sketch
    ) -> Tuple[Set[int], Set[int], Set[int]]:
        """Return the cached degree-of-freedom status for a sketch.

        The cache survives frames and is keyed by the sketch's constraint
        signature, so it is only recomputed after a real geometry edit.
        """
        signature = sketch.constraint_signature()
        cached = self._constraint_cache.get(id(sketch))
        if cached is not None and cached[0] is sketch and cached[1] == signature:
            return cached[2]
        status = sketch.constrained_entities()
        self._constraint_cache[id(sketch)] = (sketch, signature, status)
        return status

    def _sketch_color(
        self, document: Document, sketch: Sketch
    ) -> Color:
        """Return the colour for an active or merely selected sketch."""
        if sketch.id in (
            document.active_sketch_id,
            document.selected_sketch_id,
        ):
            return self.palette.active
        return self.palette.sketch

    @staticmethod
    def _visible_sketches(document: Document) -> Iterator[Sketch]:
        """Yield sketches that are visible or currently being edited."""
        for sketch in document.sketches:
            if sketch.visible or sketch.id == document.active_sketch_id:
                yield sketch

    def pick_sketch(
        self,
        pos: Point2,
        rect: pygame.Rect,
        document: Document,
        camera: OrbitCamera,
    ) -> Optional[int]:
        """Return the visible sketch nearest to a screen position."""
        if document.active_sketch_id is not None:
            return None
        center = rect.center
        tolerance = float(self._s(7))
        best: Optional[Tuple[float, int]] = None
        for sketch in self._visible_sketches(document):
            frame = sketch.frame()
            # Finished sketches only render closed loops, so only those
            # outlines may be picked.
            for loop in sketch.closed_loops():
                screen = [
                    camera.project(point_on_plane(frame, point), center)
                    for point in sketch.loop_points(loop)
                ]
                for start, end in zip(screen, screen[1:] + screen[:1]):
                    distance = self._point_segment_distance(pos, start, end)
                    if distance <= tolerance and (
                        best is None or distance < best[0]
                    ):
                        best = (distance, sketch.id)
        return best[1] if best is not None else None
