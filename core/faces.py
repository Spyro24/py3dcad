"""Pure geometry for planar faces of extruded solids.

This module deliberately does not import pygame or the render layer so the
application model can resolve a selected face without pulling in the UI.
"""

import math
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple, TYPE_CHECKING

from .profiles import union_profiles
from .sketch import PlaneFrame, PlaneLike, Point3, plane_frame

Color = Tuple[int, int, int]
FaceRef = Tuple[int, int]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import Document


@dataclass(frozen=True)
class Face:
    """A planar polygon with a flat fill colour and outward normal."""

    vertices: Tuple[Point3, ...]
    color: Color
    normal: Point3 = (0.0, 0.0, 1.0)
    label: str = "Face"

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


def prism_faces(
    points: Sequence[Sequence[float]],
    height: float,
    plane: PlaneLike = "XY",
) -> List[Face]:
    """Build top, bottom and side faces for a sketch extruded along its normal."""
    if len(points) < 3:
        return []

    frame = plane_frame(plane)
    base = _map_points(points, frame)
    top = _offset_points(base, frame.normal, height)

    # The extrusion direction determines which cap points out of the solid.
    cap_normal = frame.normal if height >= 0 else _scale(frame.normal, -1.0)
    other_cap_normal = _scale(cap_normal, -1.0)
    if height >= 0:
        top_label, bottom_label = "Top face", "Bottom face"
    else:
        top_label, bottom_label = "Bottom face", "Top face"

    faces = [
        Face(top, (190, 190, 198), cap_normal, top_label),
        Face(
            tuple(reversed(base)),
            (105, 105, 114),
            other_cap_normal,
            bottom_label,
        ),
    ]
    faces.extend(_side_faces(points, base, top, frame))
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
) -> List[Face]:
    """Build side faces with outward normals regardless of profile winding."""
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += float(point[0]) * float(nxt[1]) - float(nxt[0]) * float(point[1])
    orientation = 1.0 if area >= 0.0 else -1.0

    faces: List[Face] = []
    count = len(base)
    for index in range(count):
        nxt = (index + 1) % count
        dx = float(points[nxt][0]) - float(points[index][0])
        dy = float(points[nxt][1]) - float(points[index][1])
        local_x, local_y = (dy, -dx) if orientation > 0 else (-dy, dx)
        side_normal = _unit((
            frame.u[0] * local_x + frame.v[0] * local_y,
            frame.u[1] * local_x + frame.v[1] * local_y,
            frame.u[2] * local_x + frame.v[2] * local_y,
        ))
        faces.append(
            Face(
                (base[index], base[nxt], top[nxt], top[index]),
                _side_color(points[index], points[nxt]),
                side_normal,
                f"Side face {index + 1}",
            )
        )
    return faces


def iter_solid_faces(
    document: "Document",
) -> Iterator[Tuple[int, int, Face]]:
    """Yield ``(feature_id, face_index, face)`` for every solid face."""
    for feature in document.features:
        sketch = document.sketch(feature.sketch_id)
        if sketch is None:
            continue
        profiles = feature.resolve_profiles(sketch)
        if not profiles:
            continue
        face_index = 0
        for profile in union_profiles(profiles):
            for face in prism_faces(
                profile, feature.height, sketch.frame()
            ):
                yield feature.id, face_index, face
                face_index += 1


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
