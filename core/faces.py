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
Point2 = Tuple[float, float]
FaceRef = Tuple[int, int]
EdgeRef = Tuple[int, int]

# Side panels whose normals differ by less than this angle are one smooth face.
SMOOTH_ANGLE = math.radians(20.0)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import Document
    from .sketch import Extrude, Fillet


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
    fillets: Optional[
        Tuple[Sequence[Sequence[float]], Sequence[Sequence[float]]]
    ] = None,
) -> List[Face]:
    """Build top, bottom and side faces for a sketch extruded along its normal.

    ``holes`` are inner boundaries of the profile.  They are cut out of both
    caps and become inward-facing side walls.  ``fillets`` optionally holds
    the cap-edge fillet radii at the base and at the extruded end, one list
    per loop (the outer profile followed by each hole).
    """
    if fillets is not None:
        fillets = _clamp_fillet_loops(points, holes, fillets, height)
    faces, _ = _prism_faces_with_runs(points, height, plane, holes, fillets)
    return faces


def _clamp_fillet_loops(
    points: Sequence[Sequence[float]],
    holes: Sequence[Sequence[Sequence[float]]],
    fillets: Tuple[
        Sequence[Sequence[float]], Sequence[Sequence[float]]
    ],
    height: float,
) -> Tuple[List[List[float]], List[List[float]]]:
    """Clamp cap fillet radii for a plain, unrounded prism."""
    loops = [points, *(hole for hole in holes if len(hole) >= 3)]
    clamped: Tuple[List[List[float]], List[List[float]]] = ([], [])
    for index, loop in enumerate(loops):
        zero = fillets[0][index] if index < len(fillets[0]) else ()
        top = fillets[1][index] if index < len(fillets[1]) else ()
        zero, top = _clamp_rim_radii(loop, zero, top, height)
        clamped[0].append(zero)
        clamped[1].append(top)
    return clamped


def _prism_faces_with_runs(
    points: Sequence[Sequence[float]],
    height: float,
    plane: PlaneLike = "XY",
    holes: Sequence[Sequence[Sequence[float]]] = (),
    fillets: Optional[
        Tuple[Sequence[Sequence[float]], Sequence[Sequence[float]]]
    ] = None,
) -> Tuple[List[Face], List[int]]:
    """Return the prism faces together with smooth-run lengths for indexing."""
    if len(points) < 3:
        return [], []
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

    loops = [(points, base, top, False)]
    loops.extend(
        (hole, base_hole, top_hole, True)
        for hole, base_hole, top_hole in zip(inner, base_holes, top_holes)
    )
    zero_radii = _fillet_radii(fillets, 0, len(loops))
    height_radii = _fillet_radii(fillets, 1, len(loops))

    far_cap = _map_points(
        _cap_loop(loops[0][0], height_radii[0], False), frame
    )
    far_cap = _offset_points(far_cap, frame.normal, height)
    far_holes = tuple(
        _offset_points(
            _map_points(
                _cap_loop(loop[0], height_radii[index], True), frame
            ),
            frame.normal,
            height,
        )
        for index, loop in enumerate(loops)
        if index > 0
    )
    near_cap = _map_points(
        _cap_loop(loops[0][0], zero_radii[0], False), frame
    )
    near_holes = tuple(
        _map_points(
            _cap_loop(loop[0], zero_radii[index], True), frame
        )
        for index, loop in enumerate(loops)
        if index > 0
    )

    faces = [
        Face(
            far_cap, (190, 190, 198), cap_normal, top_label,
            holes=far_holes,
        ),
        Face(
            tuple(reversed(near_cap)),
            (105, 105, 114),
            other_cap_normal,
            bottom_label,
            holes=tuple(
                tuple(reversed(hole)) for hole in near_holes
            ),
        ),
    ]
    runs = [1, 1]

    axis = _unit(_subtract(top[0], base[0])) if top else (0.0, 0.0, 0.0)
    for index, (loop, base_loop, top_loop, inward_loop) in enumerate(loops):
        inward, outward = _loop_normals(loop, frame, inward_loop)
        loop_faces = _side_faces(
            loop,
            base_loop,
            top_loop,
            frame,
            inward=inward_loop,
            bottom_offsets=zero_radii[index],
            top_offsets=height_radii[index],
        )
        faces.extend(loop_faces)
        runs.append(len(loop_faces))

        for end in (0, 1):
            radii = zero_radii[index] if end == 0 else height_radii[index]
            cap_points = base_loop if end == 0 else top_loop
            cap_outward = (
                other_cap_normal if end == 0 else cap_normal
            )
            into_solid = axis if end == 0 else _scale(axis, -1.0)
            count = len(loop)
            for segment, radius in enumerate(radii):
                if radius <= 1e-9:
                    continue
                following = (segment + 1) % count
                span_x = loop[following][0] - loop[segment][0]
                span_y = loop[following][1] - loop[segment][1]
                span_length = math.hypot(span_x, span_y)
                direction = (
                    (span_x / span_length, span_y / span_length)
                    if span_length > 1e-9 else (0.0, 0.0)
                )
                # Where a neighbouring segment is also filleted the strips
                # meet along the intersection curve of their two cylinders.
                # The cap corner is the miter of the two offset lines, which
                # lies forward along the edge at a convex corner but behind
                # it at a concave one (the inside of a hole), so the trim is
                # signed rather than a plain radius.
                start_trim = _edge_trim(
                    loop, inward, segment, radii[segment - 1], radius,
                    direction,
                )
                end_trim = -_edge_trim(
                    loop, inward, following, radius, radii[following],
                    direction,
                )
                strip = _rim_strip(
                    loop, cap_points, inward, outward, frame, segment,
                    radius, into_solid, cap_outward,
                    start_trim, end_trim,
                )
                faces.extend(strip)
                runs.append(len(strip))

            count = len(loop)
            for segment, radius in enumerate(radii):
                if radius <= 1e-9:
                    continue
                if (
                    _turn_angle(loop, segment) < SMOOTH_ANGLE
                    and radii[segment - 1] <= 1e-9
                ):
                    patch = _runout_patch(
                        cap_points, inward, outward, frame, segment,
                        radius, True, into_solid, cap_outward,
                    )
                    faces.extend(patch)
                    runs.append(len(patch))
                following = (segment + 1) % count
                if (
                    _turn_angle(loop, following) < SMOOTH_ANGLE
                    and radii[following] <= 1e-9
                ):
                    patch = _runout_patch(
                        cap_points, inward, outward, frame, segment,
                        radius, False, into_solid, cap_outward,
                    )
                    faces.extend(patch)
                    runs.append(len(patch))

        # Adjacent cap fillets meet along their cylinder intersection curves,
        # which the signed ring trims above already follow.  This holds for
        # convex corners and for the concave corners inside a hole alike.
    return faces, runs


def _turn_angle(points: Sequence[Point2], vertex: int) -> float:
    """Return the direction change at a loop vertex in radians."""
    count = len(points)
    previous = points[(vertex - 1) % count]
    current = points[vertex]
    following = points[(vertex + 1) % count]
    incoming = (current[0] - previous[0], current[1] - previous[1])
    outgoing = (following[0] - current[0], following[1] - current[1])
    incoming_length = math.hypot(*incoming)
    outgoing_length = math.hypot(*outgoing)
    if incoming_length < 1e-9 or outgoing_length < 1e-9:
        return 0.0
    cross = (
        incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    ) / (incoming_length * outgoing_length)
    dot = (
        incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    ) / (incoming_length * outgoing_length)
    return abs(math.atan2(cross, dot))


def _fillet_radii(
    fillets: Optional[
        Tuple[Sequence[Sequence[float]], Sequence[Sequence[float]]]
    ],
    end: int,
    count: int,
) -> List[List[float]]:
    """Return per-segment fillet radii for one end of every loop."""
    radii: List[List[float]] = []
    values = fillets[end] if fillets is not None else ()
    for index in range(count):
        loop = values[index] if index < len(values) else ()
        radii.append([float(value) for value in loop])
    return radii


def _cap_loop(
    points: Sequence[Point2],
    radii: Sequence[float],
    inward_loop: bool = False,
) -> List[Point2]:
    """Inset a cap loop along the profile segments that carry a fillet.

    Each filleted segment moves its boundary line inward by its radius.  At a
    vertex where both neighbouring segments are filleted the two offset lines
    meet in a miter point; using the raw offset endpoints instead would make
    the cap polygon cross itself at every corner.
    """
    count = len(points)
    if count < 3:
        return list(points)
    inward = _loop_inward_2d(points, inward_loop)
    result: List[Point2] = []
    for index in range(count):
        previous = (index - 1) % count
        previous_radius = (
            radii[previous] if previous < len(radii) else 0.0
        )
        following_radius = radii[index] if index < len(radii) else 0.0
        if previous_radius <= 1e-9 and following_radius <= 1e-9:
            _append_point(result, points[index])
        elif previous_radius <= 1e-9:
            offset = (
                points[index][0] + inward[index][0] * following_radius,
                points[index][1] + inward[index][1] * following_radius,
            )
            if _turn_angle(points, index) < SMOOTH_ANGLE:
                # A fillet running out onto a sharp edge keeps the sharp
                # corner on the cap so the runout triangle is filled.
                _append_point(result, points[index])
                _append_point(result, offset)
            else:
                _append_point(result, offset)
        elif following_radius <= 1e-9:
            offset = (
                points[index][0] + inward[previous][0] * previous_radius,
                points[index][1] + inward[previous][1] * previous_radius,
            )
            if _turn_angle(points, index) < SMOOTH_ANGLE:
                _append_point(result, offset)
                _append_point(result, points[index])
            else:
                _append_point(result, offset)
        else:
            start = (
                points[previous][0]
                + inward[previous][0] * previous_radius,
                points[previous][1]
                + inward[previous][1] * previous_radius,
            )
            start_direction = (
                points[index][0] - points[previous][0],
                points[index][1] - points[previous][1],
            )
            end = (
                points[index][0] + inward[index][0] * following_radius,
                points[index][1] + inward[index][1] * following_radius,
            )
            end_direction = (
                points[(index + 1) % count][0] - points[index][0],
                points[(index + 1) % count][1] - points[index][1],
            )
            cross = (
                start_direction[0] * end_direction[1]
                - start_direction[1] * end_direction[0]
            )
            if abs(cross) < 1e-12:
                # Collinear neighbours: either offset point is on the same
                # line, so a midpoint keeps the loop stable.
                _append_point(result, (
                    (start[0] + end[0]) * 0.5,
                    (start[1] + end[1]) * 0.5,
                ))
                continue
            amount = (
                (end[0] - start[0]) * end_direction[1]
                - (end[1] - start[1]) * end_direction[0]
            ) / cross
            _append_point(result, (
                start[0] + start_direction[0] * amount,
                start[1] + start_direction[1] * amount,
            ))
    if len(result) < 3:
        return list(points)
    return result


def _append_point(points: List[Point2], point: Point2) -> None:
    """Append a point unless it repeats the previous one."""
    if points:
        last = points[-1]
        if (
            abs(last[0] - point[0]) <= 1e-9
            and abs(last[1] - point[1]) <= 1e-9
        ):
            return
    points.append(point)


def _clamp_rim_radii(
    points: Sequence[Point2],
    zero_radii: Sequence[float],
    height_radii: Sequence[float],
    height: float,
) -> Tuple[List[float], List[float]]:
    """Keep cap fillets small enough for the loop and the extrusion."""
    count = len(points)
    lengths = [
        math.hypot(
            points[(index + 1) % count][0] - points[index][0],
            points[(index + 1) % count][1] - points[index][1],
        )
        for index in range(count)
    ]
    limit = 0.45 * abs(height)
    clamped_zero: List[float] = []
    clamped_height: List[float] = []
    for index in range(count):
        local = min(
            limit,
            0.45 * lengths[index],
            0.45 * lengths[index - 1],
            0.45 * lengths[(index + 1) % count],
        )
        local = max(0.0, local)
        clamped_zero.append(
            min(float(zero_radii[index]), local)
            if index < len(zero_radii) else 0.0
        )
        clamped_height.append(
            min(float(height_radii[index]), local)
            if index < len(height_radii) else 0.0
        )
    return clamped_zero, clamped_height


def _loop_inward_2d(
    points: Sequence[Point2], inward_loop: bool = False
) -> List[Point2]:
    """Return the material-inward unit normal for each profile segment."""
    area = _loop_area(points)
    orientation = 1.0 if area >= 0.0 else -1.0
    direction = -1.0 if inward_loop else 1.0
    inward: List[Point2] = []
    count = len(points)
    for index in range(count):
        nxt = (index + 1) % count
        dx = points[nxt][0] - points[index][0]
        dy = points[nxt][1] - points[index][1]
        local_x, local_y = (
            (dy, -dx) if orientation > 0.0 else (-dy, dx)
        )
        length = math.hypot(local_x, local_y)
        if length < 1e-9:
            inward.append((0.0, 0.0))
            continue
        inward.append((
            -local_x / length * direction,
            -local_y / length * direction,
        ))
    return inward


def _loop_normals(
    points: Sequence[Point2],
    frame: PlaneFrame,
    inward_loop: bool = False,
) -> Tuple[List[Point2], List[Point3]]:
    """Return the material-inward 2D and outward 3D normal per segment."""
    inward = _loop_inward_2d(points, inward_loop)
    outward = [
        _map_direction((-direction[0], -direction[1]), frame)
        for direction in inward
    ]
    return inward, outward


def _map_direction(direction: Point2, frame: PlaneFrame) -> Point3:
    """Map a local profile direction onto its 3D plane frame."""
    return _unit((
        frame.u[0] * direction[0] + frame.v[0] * direction[1],
        frame.u[1] * direction[0] + frame.v[1] * direction[1],
        frame.u[2] * direction[0] + frame.v[2] * direction[1],
    ))


def _edge_trim(
    points: Sequence[Point2],
    inward: Sequence[Point2],
    vertex: int,
    previous_radius: float,
    following_radius: float,
    direction: Point2,
) -> float:
    """Return the signed distance from a vertex to the cap miter.

    The result is measured along ``direction`` (the unit vector of the edge
    being built) and is only meaningful when both neighbouring segments carry
    a fillet.  It is positive at a convex corner, where the inset cap corner
    lies ahead of the vertex, and negative at a concave corner, where the two
    offset lines meet behind it.
    """
    if previous_radius <= 1e-9 or following_radius <= 1e-9:
        return 0.0
    if _turn_angle(points, vertex) < SMOOTH_ANGLE:
        return 0.0
    miter = _miter_point(
        points, inward, vertex, previous_radius, following_radius
    )
    return (
        (miter[0] - points[vertex][0]) * direction[0]
        + (miter[1] - points[vertex][1]) * direction[1]
    )


def _rim_strip(
    points: Sequence[Point2],
    cap_points: Sequence[Point3],
    inward: Sequence[Point2],
    outward: Sequence[Point3],
    frame: PlaneFrame,
    segment: int,
    radius: float,
    into_solid: Point3,
    cap_outward: Point3,
    start_trim: float = 0.0,
    end_trim: float = 0.0,
    steps: int = 6,
) -> List[Face]:
    """Build the quarter-round face along one filleted cap edge.

    ``start_trim`` and ``end_trim`` are the radii of fillets on the adjacent
    segments.  They pull the ring endpoints inward along the edge so two
    fillets meeting at a corner share their intersection curve instead of
    overlapping and rising above the cap.
    """
    count = len(points)
    start = cap_points[segment]
    end = cap_points[(segment + 1) % count]
    span = _subtract(end, start)
    length = _length(span)
    direction = _scale(span, 1.0 / length) if length > 1e-9 else (0.0, 0.0, 0.0)
    inward_3d = _map_direction(inward[segment], frame)
    limit = 0.45 * length
    rings: List[Tuple[Point3, Point3]] = []
    for step in range(steps + 1):
        theta = math.pi * 0.5 * step / steps
        amount_in = radius * (1.0 - math.cos(theta))
        amount_up = radius * (1.0 - math.sin(theta))
        trim = 1.0 - math.cos(theta)
        first_trim = start_trim * trim
        last_trim = end_trim * trim
        if first_trim + last_trim > limit:
            scale = limit / (first_trim + last_trim)
            first_trim *= scale
            last_trim *= scale
        ring_start = (
            start[0] + direction[0] * first_trim,
            start[1] + direction[1] * first_trim,
            start[2] + direction[2] * first_trim,
        )
        ring_end = (
            end[0] - direction[0] * last_trim,
            end[1] - direction[1] * last_trim,
            end[2] - direction[2] * last_trim,
        )
        offset = (
            inward_3d[0] * amount_in + into_solid[0] * amount_up,
            inward_3d[1] * amount_in + into_solid[1] * amount_up,
            inward_3d[2] * amount_in + into_solid[2] * amount_up,
        )
        rings.append((
            (
                ring_start[0] + offset[0],
                ring_start[1] + offset[1],
                ring_start[2] + offset[2],
            ),
            (
                ring_end[0] + offset[0],
                ring_end[1] + offset[1],
                ring_end[2] + offset[2],
            ),
        ))

    faces: List[Face] = []
    for step in range(steps):
        theta = math.pi * 0.5 * (step + 0.5) / steps
        vertices = (
            rings[step][0],
            rings[step + 1][0],
            rings[step + 1][1],
            rings[step][1],
        )
        normal = _blend_normal(
            outward[segment], cap_outward, theta, vertices
        )
        faces.append(Face(
            vertices,
            _normal_color(normal),
            normal,
            "Fillet face",
            (False, False, False, False),
        ))
    return faces


def _miter_point(
    points: Sequence[Point2],
    inward: Sequence[Point2],
    vertex: int,
    previous_radius: float,
    following_radius: float,
) -> Point2:
    """Return where two offset profile lines meet at a vertex."""
    count = len(points)
    previous = (vertex - 1) % count
    start = (
        points[previous][0] + inward[previous][0] * previous_radius,
        points[previous][1] + inward[previous][1] * previous_radius,
    )
    start_direction = (
        points[vertex][0] - points[previous][0],
        points[vertex][1] - points[previous][1],
    )
    end = (
        points[vertex][0] + inward[vertex][0] * following_radius,
        points[vertex][1] + inward[vertex][1] * following_radius,
    )
    end_direction = (
        points[(vertex + 1) % count][0] - points[vertex][0],
        points[(vertex + 1) % count][1] - points[vertex][1],
    )
    cross = (
        start_direction[0] * end_direction[1]
        - start_direction[1] * end_direction[0]
    )
    if abs(cross) < 1e-12:
        return (
            (start[0] + end[0]) * 0.5,
            (start[1] + end[1]) * 0.5,
        )
    amount = (
        (end[0] - start[0]) * end_direction[1]
        - (end[1] - start[1]) * end_direction[0]
    ) / cross
    return (
        start[0] + start_direction[0] * amount,
        start[1] + start_direction[1] * amount,
    )


def _runout_patch(
    cap_points: Sequence[Point3],
    inward: Sequence[Point2],
    outward: Sequence[Point3],
    frame: PlaneFrame,
    segment: int,
    radius: float,
    at_start: bool,
    into_solid: Point3,
    cap_outward: Point3,
    steps: int = 6,
) -> List[Face]:
    """Close a cap fillet where it fades out onto a sharp edge.

    This only happens at a smooth junction, such as where a top fillet that
    follows a rounded vertical corner meets an unfilleted top edge.  A flat
    side panel cannot cover the wedge there, so a small fan from the corner
    to the fillet's end ring closes it.
    """
    count = len(cap_points)
    if at_start:
        point = cap_points[segment]
        adjacent = (segment - 1) % count
    else:
        point = cap_points[(segment + 1) % count]
        adjacent = (segment + 1) % count
    inward_3d = _map_direction(inward[segment], frame)
    ring: List[Point3] = []
    for step in range(steps + 1):
        theta = math.pi * 0.5 * step / steps
        amount_in = radius * (1.0 - math.cos(theta))
        amount_up = radius * (1.0 - math.sin(theta))
        ring.append((
            point[0] + inward_3d[0] * amount_in + into_solid[0] * amount_up,
            point[1] + inward_3d[1] * amount_in + into_solid[1] * amount_up,
            point[2] + inward_3d[2] * amount_in + into_solid[2] * amount_up,
        ))
    reference = _unit((
        outward[adjacent][0] + cap_outward[0],
        outward[adjacent][1] + cap_outward[1],
        outward[adjacent][2] + cap_outward[2],
    ))
    if _length(reference) < 0.5:
        reference = cap_outward
    faces: List[Face] = []
    for step in range(steps):
        vertices = (point, ring[step], ring[step + 1])
        normal = _oriented_normal(vertices, reference)
        faces.append(Face(
            vertices,
            _normal_color(normal),
            normal,
            "Fillet runout",
            (False, False, False),
        ))
    return faces


def _blend_normal(
    side_outward: Point3,
    cap_outward: Point3,
    theta: float,
    vertices: Sequence[Point3],
) -> Point3:
    """Return the outward normal at one step of a quarter-round fillet."""
    cosine = math.cos(theta)
    sine = math.sin(theta)
    reference = _unit((
        side_outward[0] * cosine + cap_outward[0] * sine,
        side_outward[1] * cosine + cap_outward[1] * sine,
        side_outward[2] * cosine + cap_outward[2] * sine,
    ))
    if _length(reference) < 0.5:
        reference = cap_outward
    return _oriented_normal(vertices, reference)


def _oriented_normal(
    vertices: Sequence[Point3], reference: Point3
) -> Point3:
    """Return a polygon normal facing the same way as ``reference``."""
    normal = _unit(_polygon_normal(vertices))
    if _length(normal) < 0.5:
        return _unit(reference)
    if _dot(normal, reference) < 0.0:
        normal = _scale(normal, -1.0)
    return normal


def _normal_color(normal: Point3) -> Color:
    """Shade a fillet face from its outward normal."""
    light = _unit((0.35, 0.25, 0.9))
    shade = int(115 + 45 * (0.65 + 0.35 * abs(_dot(_unit(normal), light))))
    return (shade, shade, shade + 8)


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


def _corner_cut(
    vertex: Point3,
    into_dir: Point3,
    inward_adjacent: Point3,
    axis_out: Point3,
    adjacent_radius: float,
    own_radius: float,
    steps: int = 6,
) -> List[Point3]:
    """Return the panel boundary where a neighbouring cap fillet ends.

    A cap fillet that stops at a sharp corner cuts back into the side panel
    that meets it there.  This returns the quarter-circle cross-section of
    that fillet, projected onto the panel, from the vertical edge up to the
    panel's own rim.  An empty list means the neighbouring fillet does not
    reach past this panel's rim, so the corner stays sharp.
    """
    if adjacent_radius <= own_radius + 1e-9:
        return []
    along = _dot(inward_adjacent, into_dir)
    if along <= 1e-9:
        return []
    ratio = max(0.0, min(1.0, own_radius / adjacent_radius))
    theta_max = math.asin(max(0.0, min(1.0, 1.0 - ratio)))
    if theta_max <= 1e-6:
        return []
    points: List[Point3] = []
    for step in range(steps + 1):
        theta = theta_max * step / steps
        horizontal = adjacent_radius * along * (1.0 - math.cos(theta))
        depth = adjacent_radius * (1.0 - math.sin(theta))
        points.append((
            vertex[0] + into_dir[0] * horizontal - axis_out[0] * depth,
            vertex[1] + into_dir[1] * horizontal - axis_out[1] * depth,
            vertex[2] + into_dir[2] * horizontal - axis_out[2] * depth,
        ))
    return points


def _side_faces(
    points: Sequence[Sequence[float]],
    base: Sequence[Point3],
    top: Sequence[Point3],
    frame: PlaneFrame,
    inward: bool = False,
    bottom_offsets: Optional[Sequence[float]] = None,
    top_offsets: Optional[Sequence[float]] = None,
) -> List[Face]:
    """Build side faces with outward normals regardless of profile winding.

    ``bottom_offsets`` and ``top_offsets`` trim each panel inwards along the
    extrusion axis where a cap-edge fillet replaces the sharp rim.
    """
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

    axis = (0.0, 0.0, 0.0)
    if base and top:
        delta = _subtract(top[0], base[0])
        length = _length(delta)
        if length > 1e-9:
            axis = _scale(delta, 1.0 / length)

    # A vertical edge is a smooth tessellation seam when the adjacent side
    # normals are close; curved surfaces then render without mesh lines.
    smooth = [
        _angle_between(normals[index - 1], normals[index]) < SMOOTH_ANGLE
        for index in range(count)
    ]

    inward_2d = _loop_inward_2d(points, inward)
    faces: List[Face] = []
    for index in range(count):
        nxt = (index + 1) % count
        bottom_offset = (
            float(bottom_offsets[index])
            if bottom_offsets is not None else 0.0
        )
        top_offset = (
            float(top_offsets[index])
            if top_offsets is not None else 0.0
        )
        bottom = (
            base[index][0] + axis[0] * bottom_offset,
            base[index][1] + axis[1] * bottom_offset,
            base[index][2] + axis[2] * bottom_offset,
        )
        bottom_next = (
            base[nxt][0] + axis[0] * bottom_offset,
            base[nxt][1] + axis[1] * bottom_offset,
            base[nxt][2] + axis[2] * bottom_offset,
        )
        upper = (
            top[index][0] - axis[0] * top_offset,
            top[index][1] - axis[1] * top_offset,
            top[index][2] - axis[2] * top_offset,
        )
        upper_next = (
            top[nxt][0] - axis[0] * top_offset,
            top[nxt][1] - axis[1] * top_offset,
            top[nxt][2] - axis[2] * top_offset,
        )

        prev = (index - 1) % count
        forward = _unit(_subtract(top[nxt], top[index]))
        backward = _scale(forward, -1.0)
        bottom_axis_out = _scale(axis, -1.0)
        top_axis_out = axis

        start_bottom: List[Point3] = []
        start_top: List[Point3] = []
        end_bottom: List[Point3] = []
        end_top: List[Point3] = []
        if bottom_offsets is not None:
            if _turn_angle(points, index) >= SMOOTH_ANGLE:
                start_bottom = _corner_cut(
                    base[index], forward,
                    _map_direction(inward_2d[prev], frame),
                    bottom_axis_out,
                    float(bottom_offsets[prev]), bottom_offset,
                )
            if _turn_angle(points, nxt) >= SMOOTH_ANGLE:
                end_bottom = _corner_cut(
                    base[nxt], backward,
                    _map_direction(inward_2d[nxt], frame),
                    bottom_axis_out,
                    float(bottom_offsets[nxt]), bottom_offset,
                )
        if top_offsets is not None:
            if _turn_angle(points, index) >= SMOOTH_ANGLE:
                start_top = _corner_cut(
                    top[index], forward,
                    _map_direction(inward_2d[prev], frame),
                    top_axis_out,
                    float(top_offsets[prev]), top_offset,
                )
            if _turn_angle(points, nxt) >= SMOOTH_ANGLE:
                end_top = _corner_cut(
                    top[nxt], backward,
                    _map_direction(inward_2d[nxt], frame),
                    top_axis_out,
                    float(top_offsets[nxt]), top_offset,
                )

        poly: List[Point3] = []
        flags: List[bool] = []

        def append(point: Point3, flag: bool) -> None:
            if poly and _length(_subtract(poly[-1], point)) <= 1e-9:
                return
            flags.append(flag)
            poly.append(point)

        if start_bottom:
            poly.append(start_bottom[0])
            for point in start_bottom[1:]:
                append(point, False)
        else:
            poly.append(bottom)

        bottom_sharp = bottom_offset <= 1e-9
        if end_bottom:
            before = len(flags)
            for point in reversed(end_bottom):
                append(point, False)
            if len(flags) > before:
                flags[before] = bottom_sharp
        else:
            append(bottom_next, bottom_sharp)

        # The edge that runs up from here is the shared vertical edge with
        # the next panel; the face grouping code identifies it as edge 1.
        shared_start = len(poly) - 1
        if end_top:
            append(end_top[0], not smooth[nxt])
            for point in end_top[1:]:
                append(point, False)
        else:
            append(upper_next, not smooth[nxt])

        top_sharp = top_offset <= 1e-9
        if start_top:
            before = len(flags)
            for point in reversed(start_top):
                append(point, False)
            if len(flags) > before:
                flags[before] = top_sharp
        else:
            append(upper, top_sharp)
        flags.append(not smooth[index])

        if len(poly) < 3 or len(flags) != len(poly):
            continue
        # Rotate the closed loop so the shared vertical edge is edge 1.
        shift = (shared_start - 1) % len(poly)
        poly = poly[shift:] + poly[:shift]
        flags = flags[shift:] + flags[:shift]
        faces.append(
            Face(
                tuple(poly),
                _side_color(points[index], points[nxt]),
                normals[index],
                f"Side face {index + 1}",
                tuple(flags),
            )
        )
    return faces


def vertical_edge_corner(
    edge: Edge, frame: PlaneFrame
) -> Optional[Point2]:
    """Return the local profile corner of a vertical edge, if it has one."""
    direction = _subtract(edge.end, edge.start)
    length = _length(direction)
    if length < 1e-9:
        return None
    if abs(_dot(_scale(direction, 1.0 / length), frame.normal)) < 0.999:
        return None
    midpoint = edge.midpoint
    offset = (
        midpoint[0] - frame.origin[0],
        midpoint[1] - frame.origin[1],
        midpoint[2] - frame.origin[2],
    )
    return (_dot(offset, frame.u), _dot(offset, frame.v))


def profile_has_corner(
    document: "Document",
    feature: "Extrude",
    corner: Point2,
    tolerance: float = 1e-4,
) -> bool:
    """Return whether a local corner exists on the feature's profile."""
    sketch = document.sketch(feature.sketch_id)
    if sketch is None:
        return False
    profiles = feature.resolve_profiles(sketch)
    if not profiles:
        return False
    for outer, holes in build_regions(
        profiles, feature.resolve_cuts(sketch)
    ):
        for loop in (outer, *holes):
            for x, y in loop:
                if (
                    abs(x - corner[0]) <= tolerance
                    and abs(y - corner[1]) <= tolerance
                ):
                    return True
    return False


def _apply_fillets(
    outer: Sequence[Point2],
    holes: Sequence[Sequence[Point2]],
    fillets: Sequence["Fillet"],
) -> Tuple[List[Point2], List[List[Point2]]]:
    """Round the profile corners selected for a vertical-edge fillet."""
    vertical = [fillet for fillet in fillets if fillet.kind == "vertical"]
    rounded_outer = _round_loop(outer, vertical)
    rounded_holes = [
        _round_loop(hole, vertical) for hole in holes
    ]
    return rounded_outer, rounded_holes


def _round_loop(
    points: Sequence[Point2], fillets: Sequence["Fillet"]
) -> List[Point2]:
    """Replace selected convex corners of a loop with tangent arcs."""
    radii = _corner_radii(points, fillets)
    if not radii:
        return list(points)
    orientation = 1.0 if _loop_area(points) >= 0.0 else -1.0
    result: List[Point2] = []
    count = len(points)
    for index in range(count):
        radius = radii.get(index)
        if radius is None:
            result.append(points[index])
            continue
        arc = _corner_arc(
            points[index - 1],
            points[index],
            points[(index + 1) % count],
            radius,
            orientation,
        )
        result.extend(arc if arc is not None else [points[index]])
    return result


def _corner_radii(
    points: Sequence[Point2], fillets: Sequence["Fillet"]
) -> Dict[int, float]:
    """Map loop vertex indices to the radius stored for their corner."""
    radii: Dict[int, float] = {}
    for fillet in fillets:
        if fillet.kind != "vertical":
            continue
        u, v, radius = fillet.u, fillet.v, fillet.radius
        if radius <= 0.0:
            continue
        for index, (x, y) in enumerate(points):
            if abs(x - u) <= 1e-4 and abs(y - v) <= 1e-4:
                radii[index] = radius
                break
    return radii


def rim_fillet_radii(
    loop: Sequence[Point2],
    fillets: Sequence["Fillet"],
    kind: str,
    tolerance: float = 1e-4,
) -> List[float]:
    """Return per-segment radii for cap fillets on one profile loop."""
    count = len(loop)
    radii = [0.0] * count
    for fillet in fillets:
        if fillet.kind != kind or fillet.radius <= 0.0:
            continue
        for index in range(count):
            start = loop[index]
            end = loop[(index + 1) % count]
            if _point_segment_distance(
                (fillet.u, fillet.v), start, end
            ) <= tolerance:
                radii[index] = max(radii[index], fillet.radius)
                break
    return radii


def _vertical_radius_limits(
    loop: Sequence[Point2], fillets: Sequence["Fillet"]
) -> List[float]:
    """Return the cap radius each profile segment can carry at a corner.

    A cap fillet that wraps around a rounded vertical corner becomes a torus.
    Its radius has to stay below the vertical corner radius or the inset cap
    loop would turn inside out.
    """
    count = len(loop)
    limits = [float("inf")] * count
    for fillet in fillets:
        if fillet.kind != "vertical" or fillet.radius <= 0.0:
            continue
        for vertex, (x, y) in enumerate(loop):
            if (
                abs(x - fillet.u) <= 1e-4
                and abs(y - fillet.v) <= 1e-4
            ):
                limit = 0.9 * fillet.radius
                for segment in ((vertex - 1) % count, vertex):
                    limits[segment] = min(limits[segment], limit)
                break
    return limits


def _rounded_segment_sources(
    original: Sequence[Point2],
    rounded: Sequence[Point2],
    tolerance: float = 1e-5,
) -> List[int]:
    """Map each rounded-loop segment to its source profile segment.

    Straight pieces return the original segment index.  Pieces belonging to a
    rounded vertical corner return ``~vertex`` so callers can combine the two
    cap fillets that meet there.
    """
    count = len(rounded)
    if count < 3 or len(original) < 3:
        return list(range(count))
    sources: List[int] = []
    for index in range(count):
        start = rounded[index]
        end = rounded[(index + 1) % count]
        midpoint = ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5)
        best_segment = 0
        best_distance = float("inf")
        for segment in range(len(original)):
            distance = _point_segment_distance(
                midpoint,
                original[segment],
                original[(segment + 1) % len(original)],
            )
            if distance < best_distance:
                best_distance = distance
                best_segment = segment
        if best_distance <= tolerance:
            sources.append(best_segment)
            continue
        vertex = min(
            range(len(original)),
            key=lambda candidate: math.hypot(
                midpoint[0] - original[candidate][0],
                midpoint[1] - original[candidate][1],
            ),
        )
        sources.append(~vertex)
    return sources


def _expand_rim_radii(
    original_radii: Sequence[float], sources: Sequence[int]
) -> List[float]:
    """Spread per-profile-segment cap radii over a rounded loop."""
    expanded: List[float] = []
    for source in sources:
        if source >= 0:
            expanded.append(
                float(original_radii[source])
                if source < len(original_radii) else 0.0
            )
            continue
        vertex = ~source
        previous = (
            float(original_radii[(vertex - 1) % len(original_radii)])
            if original_radii else 0.0
        )
        following = (
            float(original_radii[vertex % len(original_radii)])
            if original_radii else 0.0
        )
        values = [value for value in (previous, following) if value > 0.0]
        expanded.append(min(values) if values else 0.0)
    return expanded


def profile_segment_key(
    document: "Document",
    feature: "Extrude",
    point: Point2,
    tolerance: float = 1e-4,
) -> Optional[Tuple[Point2, Point2]]:
    """Return a stable key for the profile segment under a local point."""
    sketch = document.sketch(feature.sketch_id)
    if sketch is None:
        return None
    profiles = feature.resolve_profiles(sketch)
    if not profiles:
        return None
    for outer, holes in build_regions(
        profiles, feature.resolve_cuts(sketch)
    ):
        for loop in (outer, *holes):
            for index in range(len(loop)):
                start = loop[index]
                end = loop[(index + 1) % len(loop)]
                if _point_segment_distance(
                    point, start, end
                ) <= tolerance:
                    first = (round(start[0], 6), round(start[1], 6))
                    second = (round(end[0], 6), round(end[1], 6))
                    return (
                        (first, second) if first <= second
                        else (second, first)
                    )
    return None


def _point_segment_distance(
    point: Point2, start: Point2, end: Point2
) -> float:
    """Return the distance from a point to a line segment."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared < 1e-18:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    amount = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length_squared
    amount = max(0.0, min(1.0, amount))
    closest = (
        start[0] + dx * amount,
        start[1] + dy * amount,
    )
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def _corner_arc(
    previous: Point2,
    corner: Point2,
    following: Point2,
    radius: float,
    orientation: float,
) -> Optional[List[Point2]]:
    """Build a tangent arc replacing one convex loop corner."""
    incoming = (corner[0] - previous[0], corner[1] - previous[1])
    outgoing = (following[0] - corner[0], following[1] - corner[1])
    incoming_length = math.hypot(*incoming)
    outgoing_length = math.hypot(*outgoing)
    if incoming_length < 1e-9 or outgoing_length < 1e-9:
        return None

    u = (incoming[0] / incoming_length, incoming[1] / incoming_length)
    v = (outgoing[0] / outgoing_length, outgoing[1] / outgoing_length)
    cross = u[0] * v[1] - u[1] * v[0]
    if cross * orientation <= 1e-9:
        return None
    dot = max(-1.0, min(1.0, -(u[0] * v[0] + u[1] * v[1])))
    angle = math.acos(dot)
    if angle <= 1e-6 or angle >= math.pi - 1e-6:
        return None

    tangent = radius / math.tan(angle * 0.5)
    tangent = min(
        tangent, 0.5 * min(incoming_length, outgoing_length)
    )
    if tangent <= 1e-9:
        return None
    actual_radius = tangent * math.tan(angle * 0.5)

    start = (
        corner[0] - u[0] * tangent,
        corner[1] - u[1] * tangent,
    )
    end = (
        corner[0] + v[0] * tangent,
        corner[1] + v[1] * tangent,
    )
    inward = (
        orientation * -u[1],
        orientation * u[0],
    )
    center = (
        start[0] + inward[0] * actual_radius,
        start[1] + inward[1] * actual_radius,
    )

    start_angle = math.atan2(
        start[1] - center[1], start[0] - center[0]
    )
    end_angle = math.atan2(
        end[1] - center[1], end[0] - center[0]
    )
    if orientation > 0.0:
        while end_angle <= start_angle:
            end_angle += math.tau
    else:
        while end_angle >= start_angle:
            end_angle -= math.tau

    sweep = abs(end_angle - start_angle)
    steps = max(2, int(math.ceil(sweep / (math.pi / 12.0))))
    arc = [start]
    for step in range(1, steps):
        amount = step / steps
        angle_now = start_angle + (end_angle - start_angle) * amount
        arc.append((
            center[0] + actual_radius * math.cos(angle_now),
            center[1] + actual_radius * math.sin(angle_now),
        ))
    arc.append(end)
    return arc


def _loop_area(points: Sequence[Point2]) -> float:
    """Return the signed area of a closed polygon."""
    area = 0.0
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        area += x1 * y2 - x2 * y1
    return area * 0.5


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
            original_loops = [outer, *inner]
            rounded_outer, rounded_holes = _apply_fillets(
                outer, inner, feature.fillets
            )
            rounded_loops = [rounded_outer, *rounded_holes]
            # The cap at the base is "bottom" for a positive extrusion and
            # "top" for a negative one; the extruded end is the opposite.
            base_kind = "bottom" if feature.height >= 0 else "top"
            end_kind = "top" if feature.height >= 0 else "bottom"
            base_radii: List[List[float]] = []
            end_radii: List[List[float]] = []
            for original, rounded in zip(original_loops, rounded_loops):
                sources = _rounded_segment_sources(original, rounded)
                base = rim_fillet_radii(
                    original, feature.fillets, base_kind
                )
                end = rim_fillet_radii(
                    original, feature.fillets, end_kind
                )
                # Clamp against the original profile so tiny tessellation
                # segments of a rounded vertical corner do not shrink it.
                base, end = _clamp_rim_radii(
                    original, base, end, feature.height
                )
                limits = _vertical_radius_limits(
                    original, feature.fillets
                )
                base = [
                    min(value, limit)
                    for value, limit in zip(base, limits)
                ]
                end = [
                    min(value, limit)
                    for value, limit in zip(end, limits)
                ]
                base_radii.append(_expand_rim_radii(base, sources))
                end_radii.append(_expand_rim_radii(end, sources))
            faces, runs = _prism_faces_with_runs(
                rounded_outer,
                feature.height,
                sketch.frame(),
                rounded_holes,
                (base_radii, end_radii),
            )
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
