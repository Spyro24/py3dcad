"""Pure geometry for planar faces of extruded solids.

This module deliberately does not import pygame or the render layer so the
application model can resolve a selected face without pulling in the UI.
"""

import math
from dataclasses import dataclass
from typing import (
    Dict, Iterator, List, Optional, Sequence, Tuple, TYPE_CHECKING,
)

from .profiles import build_regions
from .sketch import PlaneFrame, PlaneLike, Point3, plane_frame

Color = Tuple[int, int, int]
FaceRef = Tuple[int, int]
EdgeRef = Tuple[int, int]

# Side panels whose normals differ by less than this angle are one smooth face.
SMOOTH_ANGLE = math.radians(20.0)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import Document


@dataclass(frozen=True)
class Face:
    """A planar polygon with a flat fill colour and outward normal."""

    vertices: Tuple[Point3, ...]
    color: Color
    normal: Point3 = (0.0, 0.0, 1.0)
    label: str = "Face"
    # ``None`` outlines every edge.  Side faces of curved surfaces list which
    # edges are real creases so tessellation seams are not drawn as mesh edges.
    sharp_edges: Optional[Tuple[bool, ...]] = None
    # Inner boundaries of a cap face (holes through the solid).
    holes: Tuple[Tuple[Point3, ...], ...] = ()

    def to_plane_frame(self) -> PlaneFrame:
        """Return an orthonormal sketch frame lying on this face."""
        normal = _unit(self.normal)
        if _length(normal) < 0.5:
            normal = _polygon_normal(self.vertices)

        origin = _average(self.vertices)

        u_axis: Optional[Point3] = None
        for index in range(1, len(self.vertices)):
            edge = _subtract(self.vertices[index], self.vertices[0])
            edge = _subtract(
                edge, _scale(normal, _dot(edge, normal))
            )
            length = _length(edge)
            if length > 1e-6:
                u_axis = _scale(edge, 1.0 / length)
                break

        if u_axis is None:
            u_axis = _perpendicular(normal)
        v_axis = _unit(_cross(normal, u_axis))
        if _length(v_axis) < 0.5:
            u_axis = _perpendicular(normal)
            v_axis = _unit(_cross(normal, u_axis))
        # Re-orthogonalise so the returned frame is stable after serialisation.
        u_axis = _unit(_cross(v_axis, normal))

        return PlaneFrame(origin, u_axis, v_axis, normal, self.label)


@dataclass(frozen=True)
class Edge:
    """A real edge between two vertices of a solid."""

    start: Point3
    end: Point3
    # Outward normals of the adjacent faces.  An edge is visible from a
    # direction when at least one adjacent face faces the viewer.
    normals: Tuple[Point3, ...] = ()
    label: str = "Edge"

    @property
    def midpoint(self) -> Point3:
        """Return the centre of the edge."""
        return (
            (self.start[0] + self.end[0]) * 0.5,
            (self.start[1] + self.end[1]) * 0.5,
            (self.start[2] + self.end[2]) * 0.5,
        )


def prism_faces(
    points: Sequence[Sequence[float]],
    height: float,
    plane: PlaneLike = "XY",
    holes: Sequence[Sequence[Sequence[float]]] = (),
) -> List[Face]:
    """Build top, bottom and side faces for a sketch extruded along its normal.

    ``holes`` are inner boundaries of the profile.  They are cut out of both
    caps and become inward-facing side walls.
    """
    if len(points) < 3:
        return []

    frame = plane_frame(plane)
    base = _map_points(points, frame)
    top = _offset_points(base, frame.normal, height)
    inner = [hole for hole in holes if len(hole) >= 3]
    base_holes = [_map_points(hole, frame) for hole in inner]
    top_holes = [
        _offset_points(hole, frame.normal, height) for hole in base_holes
    ]

    # The extrusion direction determines which cap points out of the solid.
    cap_normal = frame.normal if height >= 0 else _scale(frame.normal, -1.0)
    other_cap_normal = _scale(cap_normal, -1.0)
    if height >= 0:
        top_label, bottom_label = "Top face", "Bottom face"
    else:
        top_label, bottom_label = "Bottom face", "Top face"

    faces = [
        Face(
            top, (190, 190, 198), cap_normal, top_label,
            holes=tuple(top_holes),
        ),
        Face(
            tuple(reversed(base)),
            (105, 105, 114),
            other_cap_normal,
            bottom_label,
            holes=tuple(
                tuple(reversed(hole)) for hole in base_holes
            ),
        ),
    ]
    faces.extend(_side_faces(points, base, top, frame))
    for hole, base_hole, top_hole in zip(inner, base_holes, top_holes):
        faces.extend(
            _side_faces(hole, base_hole, top_hole, frame, inward=True)
        )
    return faces


def _map_points(
    points: Sequence[Sequence[float]], frame: PlaneFrame
) -> Tuple[Point3, ...]:
    origin, u_axis, v_axis = frame.origin, frame.u, frame.v
    return tuple(
        (
            origin[0] + u_axis[0] * float(x) + v_axis[0] * float(y),
            origin[1] + u_axis[1] * float(x) + v_axis[1] * float(y),
            origin[2] + u_axis[2] * float(x) + v_axis[2] * float(y),
        )
        for x, y in points
    )


def _offset_points(
    points: Sequence[Point3], normal: Point3, height: float
) -> Tuple[Point3, ...]:
    return tuple(
        (
            point[0] + normal[0] * height,
            point[1] + normal[1] * height,
            point[2] + normal[2] * height,
        )
        for point in points
    )


def _side_faces(
    points: Sequence[Sequence[float]],
    base: Sequence[Point3],
    top: Sequence[Point3],
    frame: PlaneFrame,
    inward: bool = False,
) -> List[Face]:
    """Build side faces with outward normals regardless of profile winding."""
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += float(point[0]) * float(nxt[1]) - float(nxt[0]) * float(point[1])
    orientation = 1.0 if area >= 0.0 else -1.0
    direction = -1.0 if inward else 1.0

    count = len(base)
    normals: List[Point3] = []
    for index in range(count):
        nxt = (index + 1) % count
        dx = float(points[nxt][0]) - float(points[index][0])
        dy = float(points[nxt][1]) - float(points[index][1])
        local_x, local_y = (dy, -dx) if orientation > 0 else (-dy, dx)
        normals.append(_unit((
            (frame.u[0] * local_x + frame.v[0] * local_y) * direction,
            (frame.u[1] * local_x + frame.v[1] * local_y) * direction,
            (frame.u[2] * local_x + frame.v[2] * local_y) * direction,
        )))

    # A vertical edge is a smooth tessellation seam when the adjacent side
    # normals are close; curved surfaces then render without mesh lines.
    smooth = [
        _angle_between(normals[index - 1], normals[index]) < SMOOTH_ANGLE
        for index in range(count)
    ]

    faces: List[Face] = []
    for index in range(count):
        nxt = (index + 1) % count
        faces.append(
            Face(
                (base[index], base[nxt], top[nxt], top[index]),
                _side_color(points[index], points[nxt]),
                normals[index],
                f"Side face {index + 1}",
                (True, not smooth[nxt], True, not smooth[index]),
            )
        )
    return faces


def iter_solid_faces(
    document: "Document",
) -> Iterator[Tuple[int, int, Face]]:
    """Yield ``(feature_id, face_index, face)`` for every solid face.

    Smooth side-face runs share one ``face_index`` so a tessellated cylinder
    selects and highlights as a single CAD face.  Nested profiles become holes
    through the solid instead of being merged into its outer contour.
    """
    for feature in document.features:
        sketch = document.sketch(feature.sketch_id)
        if sketch is None:
            continue
        profiles = feature.resolve_profiles(sketch)
        if not profiles:
            continue
        cuts = feature.resolve_cuts(sketch)
        face_index = 0
        for outer, holes in build_regions(profiles, cuts):
            inner = [hole for hole in holes if len(hole) >= 3]
            faces = prism_faces(
                outer, feature.height, sketch.frame(), inner
            )
            runs = [1, 1, len(outer)] + [len(hole) for hole in inner]
            groups = _face_groups(faces, runs)
            for face, group in zip(faces, groups):
                yield feature.id, face_index + group, face
            face_index += max(groups, default=-1) + 1


def _face_groups(
    faces: Sequence[Face], runs: Sequence[int]
) -> List[int]:
    """Give each face an index, merging smooth side runs within each loop."""
    groups: List[int] = []
    next_index = 0
    position = 0
    for length in runs:
        run = faces[position:position + length]
        position += length
        if not run:
            continue
        if run[0].sharp_edges is None:
            for _ in run:
                groups.append(next_index)
                next_index += 1
            continue
        run_groups = _side_run_groups(run)
        groups.extend(next_index + group for group in run_groups)
        next_index += max(run_groups, default=-1) + 1
    return groups


def _side_run_groups(faces: Sequence[Face]) -> List[int]:
    """Merge adjacent side panels whose shared edge is smooth."""
    if not faces:
        return []
    groups = [0]
    current = 0
    for index in range(1, len(faces)):
        sharp = faces[index - 1].sharp_edges
        if sharp is None or sharp[1]:
            current += 1
        groups.append(current)
    # A smooth run can wrap around from the last panel to the first.
    sharp = faces[-1].sharp_edges
    if len(faces) > 1 and sharp is not None and not sharp[1]:
        last = groups[-1]
        if last != 0:
            groups = [0 if group == last else group for group in groups]
            remap: Dict[int, int] = {}
            groups = [
                remap.setdefault(group, len(remap)) for group in groups
            ]
    return groups


def face_for_ref(
    document: "Document", reference: Optional[FaceRef]
) -> Optional[Face]:
    """Resolve a ``(feature_id, face_index)`` reference to live geometry."""
    if reference is None:
        return None
    feature_id, face_index = reference
    for current_id, index, face in iter_solid_faces(document):
        if current_id == feature_id and index == face_index:
            return face
    return None


def edge_for_ref(
    document: "Document", reference: Optional[EdgeRef]
) -> Optional[Edge]:
    """Resolve a ``(feature_id, edge_index)`` reference to live geometry."""
    if reference is None:
        return None
    feature_id, edge_index = reference
    for current_id, index, edge in iter_solid_edges(document):
        if current_id == feature_id and index == edge_index:
            return edge
    return None


def iter_solid_edges(
    document: "Document",
) -> Iterator[Tuple[int, int, Edge]]:
    """Yield ``(feature_id, edge_index, edge)`` for every real solid edge.

    Coincident edges shared by adjacent faces are merged.  Smooth
    tessellation seams are skipped so curved surfaces offer no fake edges.
    """
    feature_id: Optional[int] = None
    collected: Dict[
        Tuple[Tuple[float, ...], Tuple[float, ...]],
        Tuple[Point3, Point3, List[Point3]],
    ] = {}
    for current_id, _, face in iter_solid_faces(document):
        if current_id != feature_id:
            if feature_id is not None:
                yield from _feature_edges(feature_id, collected)
            feature_id = current_id
            collected = {}
        _collect_face_edges(face, collected)
    if feature_id is not None:
        yield from _feature_edges(feature_id, collected)


def edge_visible(edge: Edge, view_direction: Point3) -> bool:
    """Return whether an edge lies on a face visible from the camera."""
    if not edge.normals:
        return True
    return any(_dot(normal, view_direction) > 1e-6 for normal in edge.normals)


def _collect_face_edges(
    face: Face,
    collected: Dict[
        Tuple[Tuple[float, ...], Tuple[float, ...]],
        Tuple[Point3, Point3, List[Point3]],
    ],
) -> None:
    """Add the drawn edges of one face to a shared, de-duplicated set."""
    count = len(face.vertices)
    for index in range(count):
        sharp = face.sharp_edges
        if sharp is not None and index < len(sharp) and not sharp[index]:
            continue
        _add_edge(
            collected,
            face.vertices[index],
            face.vertices[(index + 1) % count],
            face.normal,
        )
    for hole in face.holes:
        hole_count = len(hole)
        for index in range(hole_count):
            _add_edge(
                collected,
                hole[index],
                hole[(index + 1) % hole_count],
                face.normal,
            )


def _add_edge(
    collected: Dict[
        Tuple[Tuple[float, ...], Tuple[float, ...]],
        Tuple[Point3, Point3, List[Point3]],
    ],
    start: Point3,
    end: Point3,
    normal: Point3,
) -> None:
    """Merge an edge into the per-feature set, keeping adjacent normals."""
    if _length(_subtract(start, end)) < 1e-9:
        return
    key = _edge_key(start, end)
    entry = collected.get(key)
    if entry is None:
        collected[key] = (start, end, [normal])
    elif not any(
        _dot(_unit(current), _unit(normal)) > 0.999
        for current in entry[2]
    ):
        entry[2].append(normal)


def _feature_edges(
    feature_id: int,
    collected: Dict[
        Tuple[Tuple[float, ...], Tuple[float, ...]],
        Tuple[Point3, Point3, List[Point3]],
    ],
) -> Iterator[Tuple[int, int, Edge]]:
    """Yield the merged edges of one feature with stable indices."""
    for index, (start, end, normals) in enumerate(collected.values()):
        yield feature_id, index, Edge(start, end, tuple(normals))


def _edge_key(
    start: Point3, end: Point3
) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """Return an order-independent key for a pair of edge endpoints."""
    first = tuple(round(value, 6) for value in start)
    second = tuple(round(value, 6) for value in end)
    return (first, second) if first <= second else (second, first)


def _side_color(a: Sequence[float], b: Sequence[float]) -> Color:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (135, 135, 143)
    nx, ny = dy / length, -dx / length
    light = 0.65 + 0.35 * abs(nx * 0.7 + ny * 0.3)
    shade = int(115 + 45 * light)
    return (shade, shade, shade + 8)


def _subtract(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(vector: Point3, factor: float) -> Point3:
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _angle_between(a: Point3, b: Point3) -> float:
    """Return the angle between two directions in radians."""
    dot = max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))
    return math.acos(dot)


def _cross(a: Point3, b: Point3) -> Point3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(vector: Point3) -> float:
    return math.sqrt(_dot(vector, vector))


def _unit(vector: Point3) -> Point3:
    length = _length(vector)
    if length < 1e-9:
        return (0.0, 0.0, 0.0)
    return _scale(vector, 1.0 / length)


def _average(vertices: Sequence[Point3]) -> Point3:
    if not vertices:
        return (0.0, 0.0, 0.0)
    count = float(len(vertices))
    return (
        sum(vertex[0] for vertex in vertices) / count,
        sum(vertex[1] for vertex in vertices) / count,
        sum(vertex[2] for vertex in vertices) / count,
    )


def _polygon_normal(vertices: Sequence[Point3]) -> Point3:
    if len(vertices) < 3:
        return (0.0, 0.0, 1.0)
    normal = _cross(
        _subtract(vertices[1], vertices[0]),
        _subtract(vertices[2], vertices[0]),
    )
    unit = _unit(normal)
    return unit if _length(unit) > 0.5 else (0.0, 0.0, 1.0)


def _perpendicular(normal: Point3) -> Point3:
    """Pick a unit vector perpendicular to ``normal``."""
    candidate: Point3
    if abs(normal[0]) < 0.9:
        candidate = (1.0, 0.0, 0.0)
    else:
        candidate = (0.0, 1.0, 0.0)
    vector = _cross(normal, candidate)
    if _length(vector) < 1e-6:
        vector = _cross(normal, (0.0, 0.0, 1.0))
    return _unit(vector)
