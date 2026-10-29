"""Project solid shapes onto a sketch plane.

Projected geometry is shape-defined: a straight body edge becomes a sketch
line, a circular fillet edge becomes a two-point sketch arc with a bulge,
and a round body edge becomes a sketch circle.  Tessellation points are only
used to recognise the underlying shape, never stored as sketch geometry.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple, TYPE_CHECKING

from .sketch import Extrude, ProjectionSource, Sketch

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import Document

Point2 = Tuple[float, float]
Point3 = Tuple[float, float, float]

# Sketch coordinates are exact enough for profile topology; a small epsilon
# absorbs floating-point noise from dot products and tessellated circles.
BIND_TOLERANCE = 1e-5
# A tessellated arc is exact to well below this fraction of its radius.
FIT_TOLERANCE = 2e-5


@dataclass
class ProjectionPlan:
    """Exact shapes one picked body edge contributes to a sketch."""

    points: List[Tuple[ProjectionSource, Point2]] = field(
        default_factory=list
    )
    # (start source, end source, bulge or None for a straight line)
    segments: List[
        Tuple[ProjectionSource, ProjectionSource, Optional[float]]
    ] = field(default_factory=list)
    # (centre source, source sketch circle index or -1, radius)
    circles: List[Tuple[ProjectionSource, int, float]] = field(
        default_factory=list
    )


def feature_extent(feature: Extrude) -> Tuple[float, float]:
    """Return the feature's body range along its sketch normal."""
    if feature.slices:
        low = min(entry.z0 for entry in feature.slices)
        high = max(entry.z1 for entry in feature.slices)
    else:
        low = feature.start
        high = feature.start + feature.height
    if high < low:
        low, high = high, low
    return low, high


def frame_coordinates(
    sketch: Sketch, point: Sequence[float]
) -> Tuple[float, float, float]:
    """Express a world point in the sketch's local U, V and normal axes."""
    frame = sketch.frame()
    offset = (
        point[0] - frame.origin[0],
        point[1] - frame.origin[1],
        point[2] - frame.origin[2],
    )
    return (
        _dot(offset, frame.u),
        _dot(offset, frame.v),
        _dot(offset, frame.normal),
    )


def project_to_sketch(
    sketch: Sketch, point: Sequence[float]
) -> Point2:
    """Project a world point onto the sketch plane."""
    u, v, _ = frame_coordinates(sketch, point)
    return (u, v)


def find_feature(
    document: "Document", feature_id: int
) -> Optional[Extrude]:
    """Return the feature with ``feature_id``, if it still exists."""
    return next(
        (
            feature for feature in document.features
            if feature.id == feature_id
        ),
        None,
    )


def projection_source(
    document: "Document", feature_id: int, point: Sequence[float]
) -> Optional[ProjectionSource]:
    """Describe a world vertex as a re-resolvable projection source."""
    feature = find_feature(document, feature_id)
    if feature is None:
        return None
    sketch = document.sketch(feature.sketch_id)
    if sketch is None:
        return None
    u, v, height = frame_coordinates(sketch, point)
    low, high = feature_extent(feature)
    span = high - low
    z_fraction = (
        min(1.0, max(0.0, (height - low) / span))
        if span > 1e-9 else 0.0
    )
    bind, index, t = ("world", -1, 0.0)
    # Combined bodies store baked slices, so their regions no longer follow
    # the owning sketch.  Their height fraction alone is the stable anchor.
    if not feature.slices:
        bind, index, t = _source_binding(sketch, u, v)
    return ProjectionSource(
        feature.id, u, v, z_fraction, bind, index, t
    )


def _source_binding(
    sketch: Sketch, u: float, v: float
) -> Tuple[str, int, float]:
    """Find the sketch entity a projected vertex was generated from."""
    point = (u, v)
    for index, candidate in enumerate(sketch.points):
        if sketch.is_projected_point(index):
            continue
        if _distance(point, candidate) <= BIND_TOLERANCE:
            return "point", index, 0.0
    best: Optional[Tuple[float, int, float]] = None
    for index, (start, end) in enumerate(sketch.edges):
        if sketch.is_projected_edge(index):
            continue
        first = sketch.points[start]
        second = sketch.points[end]
        dx = second[0] - first[0]
        dy = second[1] - first[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-18:
            continue
        t = (
            (u - first[0]) * dx + (v - first[1]) * dy
        ) / length_squared
        t = min(1.0, max(0.0, t))
        closest = (first[0] + dx * t, first[1] + dy * t)
        distance = _distance(point, closest)
        if distance > BIND_TOLERANCE:
            continue
        if best is None or distance < best[0]:
            best = (distance, index, t)
    if best is not None:
        return "edge", best[1], best[2]
    for index, circle in enumerate(sketch.circles):
        radius = circle.radius
        if radius <= 1e-9:
            continue
        dx = u - circle.midPoint[0]
        dy = v - circle.midPoint[1]
        if abs(math.hypot(dx, dy) - radius) <= BIND_TOLERANCE:
            return "circle", index, math.atan2(dy, dx)
    return "world", -1, 0.0


def resolve_source(
    document: "Document", source: ProjectionSource
) -> Optional[Point3]:
    """Return the current world position described by a source."""
    feature = find_feature(document, source.feature_id)
    if feature is None:
        return None
    sketch = document.sketch(feature.sketch_id)
    if sketch is None:
        return None
    if feature.slices:
        # Slices are baked boolean results; their sketch may no longer drive
        # the body, so only the stored local position is stable.
        point = (source.u, source.v)
    else:
        point = _source_local(sketch, source)
    if point is None:
        return None
    low, high = feature_extent(feature)
    height = low + (high - low) * source.z_fraction
    frame = sketch.frame()
    u, v = point
    return (
        frame.origin[0]
        + frame.u[0] * u + frame.v[0] * v + frame.normal[0] * height,
        frame.origin[1]
        + frame.u[1] * u + frame.v[1] * v + frame.normal[1] * height,
        frame.origin[2]
        + frame.u[2] * u + frame.v[2] * v + frame.normal[2] * height,
    )


def _source_local(
    sketch: Sketch, source: ProjectionSource
) -> Optional[Point2]:
    """Return the local U/V position for a source's binding."""
    if source.bind == "point":
        if 0 <= source.index < len(sketch.points):
            point = sketch.points[source.index]
            return (point[0], point[1])
        return None
    if source.bind == "edge":
        if not 0 <= source.index < len(sketch.edges):
            return None
        if sketch.edge_bulge(source.index) is not None:
            return None
        start, end = sketch.edges[source.index]
        if not (
            0 <= start < len(sketch.points)
            and 0 <= end < len(sketch.points)
        ):
            return None
        first = sketch.points[start]
        second = sketch.points[end]
        t = min(1.0, max(0.0, source.t))
        return (
            first[0] + (second[0] - first[0]) * t,
            first[1] + (second[1] - first[1]) * t,
        )
    if source.bind == "circle":
        if not 0 <= source.index < len(sketch.circles):
            return None
        circle = sketch.circles[source.index]
        radius = circle.radius
        return (
            circle.midPoint[0] + radius * math.cos(source.t),
            circle.midPoint[1] + radius * math.sin(source.t),
        )
    return (source.u, source.v)


def refresh_sketch(document: "Document", sketch: Sketch) -> None:
    """Move every projected point and circle to its current source."""
    for link in sketch.projected_points:
        if not 0 <= link.point < len(sketch.points):
            continue
        world = resolve_source(document, link.source)
        if world is None:
            continue
        sketch.points[link.point].set_pos(project_to_sketch(sketch, world))
    center_indices: dict = {}
    if sketch.projected_circles:
        for index, point in enumerate(sketch.points):
            center_indices.setdefault(id(point), index)
    for link in sketch.projected_circles:
        if not 0 <= link.circle < len(sketch.circles):
            continue
        world = resolve_source(document, link.center)
        if world is None:
            continue
        circle = sketch.circles[link.circle]
        center = project_to_sketch(sketch, world)
        center_index = center_indices.get(id(circle.midPoint))
        if center_index is not None:
            sketch.points[center_index].set_pos(center)
        circle.diameter = 2.0 * _circle_radius(
            document, link.center.feature_id,
            link.source_circle, link.radius,
        )
    # Measurements may reference projected geometry.  Re-apply them after
    # the projected points move so the free side keeps the measured value.
    if sketch.measurements:
        sketch.enforce_measurements(sketch.points)


def refresh_document_projections(document: "Document") -> None:
    """Refresh projected entities in every sketch."""
    for sketch in document.sketches:
        if sketch.projected_points or sketch.projected_circles:
            refresh_sketch(document, sketch)


def _circle_radius(
    document: "Document",
    feature_id: int,
    source_circle: int,
    fallback: float,
) -> float:
    """Return the current source radius, or the stored baked radius."""
    if source_circle < 0:
        return fallback
    feature = find_feature(document, feature_id)
    if feature is None or feature.slices:
        return fallback
    sketch = document.sketch(feature.sketch_id)
    if sketch is None or not 0 <= source_circle < len(sketch.circles):
        return fallback
    return sketch.circles[source_circle].radius


def projected_point(
    document: "Document",
    sketch: Sketch,
    feature_id: int,
    point: Sequence[float],
) -> Optional[Tuple[ProjectionSource, Point2]]:
    """Plan one projected point and its source, or None if unresolved."""
    source = projection_source(document, feature_id, point)
    if source is None:
        return None
    return source, project_to_sketch(sketch, point)


def projected_shape(
    document: "Document",
    sketch: Sketch,
    feature_id: int,
    chain: Sequence[Sequence[float]],
    edge_start: Sequence[float],
    edge_end: Sequence[float],
) -> ProjectionPlan:
    """Plan the exact line, arc or circle for one picked body edge."""
    plan = ProjectionPlan()
    if len(chain) < 2:
        return plan
    unique: List[Tuple[Point3, Point2]] = []
    for world in chain:
        current = tuple(map(float, world))
        if unique and _distance3(current, unique[-1][0]) <= 1e-9:
            continue
        unique.append((current, project_to_sketch(sketch, current)))
    if len(unique) < 2:
        return plan
    closed = _distance3(unique[0][0], unique[-1][0]) <= 1e-9
    if closed:
        body = unique[:-1]
        if len(body) < 3:
            return plan
        _plan_circle(document, sketch, feature_id, body, plan)
        if plan.circles:
            return plan
        loop = _closed_loop(body, edge_start, edge_end)
    else:
        loop = unique
    if len(loop) < 2:
        return plan
    # Recognise straight and circular runs in 3D: an obliquely projected
    # arc is an ellipse, so splitting the projected polyline would mistake
    # its segments for short lines.
    world_loop = [world for world, _ in loop]
    primitives = _split_primitives(world_loop)
    picked = _picked_segment(world_loop, edge_start, edge_end)
    if picked is None:
        picked = 0
    primitive = _primitive_at(primitives, picked)
    if primitive is None:
        return plan
    kind, start, end = primitive
    _plan_primitive(
        document, sketch, feature_id, loop, kind, start, end, plan
    )
    return plan


def _closed_loop(
    body: Sequence[Tuple[Point3, Point2]],
    edge_start: Sequence[float],
    edge_end: Sequence[float],
) -> List[Tuple[Point3, Point2]]:
    """Rotate a closed chain so the seam is not inside the picked primitive.

    ``_edge_run_points`` starts a closed chain at the picked edge, which
    would otherwise split that edge's arc or line in two at the seam.
    """
    loop = list(body) + [body[0]]
    world_loop = [world for world, _ in loop]
    primitives = _split_primitives(world_loop)
    picked = _picked_segment(world_loop, edge_start, edge_end)
    if picked is None:
        return loop
    primitive = _primitive_at(primitives, picked)
    if primitive is None:
        return loop
    _, start, end = primitive
    if start != 0 or end >= len(body):
        return loop
    rotated = list(body[end:]) + list(body[:end])
    return rotated + [rotated[0]]


def _plan_circle(
    document: "Document",
    sketch: Sketch,
    feature_id: int,
    loop: Sequence[Tuple[Point3, Point2]],
    plan: ProjectionPlan,
) -> None:
    """Plan one exact sketch circle for a closed circular body edge."""
    fit = _fit_circle([local for _, local in loop])
    if fit is None:
        return
    center, radius, error = fit
    if radius <= 1e-9 or error > FIT_TOLERANCE * max(1.0, radius):
        return
    world_center = _world_on_plane(sketch, loop[0][0], center)
    center_source = projection_source(
        document, feature_id, world_center
    )
    if center_source is None:
        return
    source_circle = _consistent_circle_binding(
        document, feature_id, loop
    )
    current = _circle_radius(
        document, feature_id, source_circle, radius
    )
    plan.circles.append((center_source, source_circle, current))


def _plan_primitive(
    document: "Document",
    sketch: Sketch,
    feature_id: int,
    loop: Sequence[Tuple[Point3, Point2]],
    kind: str,
    start: int,
    end: int,
    plan: ProjectionPlan,
) -> None:
    """Turn one line or arc run into two linked endpoints and a segment."""
    if not (0 <= start < end < len(loop)):
        return
    first = projection_source(document, feature_id, loop[start][0])
    second = projection_source(document, feature_id, loop[end][0])
    if first is None or second is None or first.key() == second.key():
        return
    start_local = project_to_sketch(sketch, loop[start][0])
    end_local = project_to_sketch(sketch, loop[end][0])
    if _distance(start_local, end_local) <= 1e-9:
        return
    bulge = None
    if kind == "arc":
        bulge = _projected_bulge(sketch, loop[start:end + 1])
    plan.points.append((first, start_local))
    plan.points.append((second, end_local))
    plan.segments.append((first, second, bulge))


def _projected_bulge(
    sketch: Sketch, run: Sequence[Tuple[Point3, Point2]]
) -> Optional[float]:
    """Define an arc from its projected start, midpoint and end.

    The midpoint is the geometric middle of the 3D run, not a tessellation
    index.  Only those three points are projected; a circle through them
    gives the sketch bulge even when the true projection is an ellipse.
    """
    midpoint = _arc_midpoint(run)
    if midpoint is None:
        return None
    first = project_to_sketch(sketch, run[0][0])
    middle = project_to_sketch(sketch, midpoint)
    last = project_to_sketch(sketch, run[-1][0])
    fit = _fit_circle([first, middle, last])
    if fit is None:
        return None
    return _sweep_bulge([first, middle, last], fit[0])


def _arc_midpoint(
    run: Sequence[Tuple[Point3, Point2]]
) -> Optional[Point3]:
    """Return the angular midpoint of a 3D arc run.

    Angles are accumulated along the run, so uneven tessellation cannot
    pull the midpoint toward a densely sampled part of the arc.
    """
    if len(run) < 3:
        return None
    circle = _circle_through(run[0][0], run[1][0], run[2][0])
    if circle is None:
        return None
    center, radius, normal = circle
    first = _subtract3(run[0][0], center)
    length = math.sqrt(_dot(first, first))
    if length <= 1e-12:
        return None
    axis_u = tuple(component / length for component in first)
    axis_v = _cross3(normal, axis_u)
    angles = []
    for point, _ in run:
        offset = _subtract3(point, center)
        angles.append(math.atan2(
            _dot(offset, axis_v), _dot(offset, axis_u)
        ))
    sweep = 0.0
    for first_angle, second_angle in zip(angles, angles[1:]):
        sweep += (second_angle - first_angle + math.pi) % math.tau - math.pi
    if abs(sweep) <= 1e-9:
        return None
    middle = angles[0] + sweep * 0.5
    return tuple(
        center[axis] + radius * (
            math.cos(middle) * axis_u[axis]
            + math.sin(middle) * axis_v[axis]
        )
        for axis in range(3)
    )


def _world_on_plane(
    sketch: Sketch, reference: Sequence[float], local: Point2
) -> Point3:
    """Lift a sketch-local point to the height of a body edge."""
    frame = sketch.frame()
    height = (
        (reference[0] - frame.origin[0]) * frame.normal[0]
        + (reference[1] - frame.origin[1]) * frame.normal[1]
        + (reference[2] - frame.origin[2]) * frame.normal[2]
    )
    return (
        frame.origin[0] + frame.u[0] * local[0]
        + frame.v[0] * local[1] + frame.normal[0] * height,
        frame.origin[1] + frame.u[1] * local[0]
        + frame.v[1] * local[1] + frame.normal[1] * height,
        frame.origin[2] + frame.u[2] * local[0]
        + frame.v[2] * local[1] + frame.normal[2] * height,
    )


def _split_primitives(
    points: Sequence[Point3],
) -> List[Tuple[str, int, int]]:
    """Split a 3D polyline into maximal straight and circular-arc runs."""
    runs: List[Tuple[str, int, int]] = []
    index = 0
    count = len(points)
    while index < count - 1:
        line_end = index + 1
        while line_end < count - 1 and _collinear(
            points[index], points[line_end], points[line_end + 1]
        ):
            line_end += 1
        if line_end - index >= 2:
            runs.append(("line", index, line_end))
            index = line_end
            continue
        arc_end = _arc_run(points, index)
        if arc_end is not None:
            runs.append(("arc", index, arc_end))
            index = arc_end
            continue
        runs.append(("line", index, index + 1))
        index += 1
    return runs


def _arc_run(
    points: Sequence[Point3], start: int
) -> Optional[int]:
    """Return the inclusive end of a circular run, or None."""
    count = len(points)
    if start + 2 >= count:
        return None
    circle = _circle_through(
        points[start], points[start + 1], points[start + 2]
    )
    if circle is None:
        return None
    center, radius, normal = circle
    end = start + 2
    tolerance = FIT_TOLERANCE * max(1.0, radius)
    while end < count - 1 and _on_circle(
        points[end + 1], center, radius, normal, tolerance
    ):
        end += 1
    if end - start >= 3:
        return end
    if end - start == 2 and _uniform_arc(points[start:start + 3]):
        return end
    return None


def _primitive_at(
    runs: Sequence[Tuple[str, int, int]], segment: int
) -> Optional[Tuple[str, int, int]]:
    """Return the primitive containing one chain segment."""
    for kind, start, end in runs:
        if start <= segment < end:
            return kind, start, end
    return None


def _picked_segment(
    points: Sequence[Point3],
    edge_start: Sequence[float],
    edge_end: Sequence[float],
) -> Optional[int]:
    """Locate the picked body edge inside its smooth chain."""
    first = tuple(round(float(value), 6) for value in edge_start)
    second = tuple(round(float(value), 6) for value in edge_end)
    rounded = [
        tuple(round(value, 6) for value in point) for point in points
    ]
    for index in range(len(rounded) - 1):
        current = rounded[index]
        following = rounded[index + 1]
        if (current == first and following == second) or (
            current == second and following == first
        ):
            return index
    return None


def _consistent_circle_binding(
    document: "Document",
    feature_id: int,
    loop: Sequence[Tuple[Point3, Point2]],
) -> int:
    """Return the source sketch circle a full round edge came from."""
    feature = find_feature(document, feature_id)
    sketch = (
        document.sketch(feature.sketch_id) if feature is not None else None
    )
    if feature is None or sketch is None:
        return -1
    counts: dict = {}
    # Stored slices are baked, so only unsliced features bind to circles.
    if feature.slices:
        return -1
    for world, _ in loop:
        u, v, _ = frame_coordinates(sketch, world)
        bind, index, _ = _source_binding(sketch, u, v)
        if bind == "circle":
            counts[index] = counts.get(index, 0) + 1
    if not counts:
        return -1
    index, count = max(counts.items(), key=lambda item: item[1])
    return index if count * 2 >= len(loop) else -1


def _collinear(first: Point3, second: Point3, third: Point3) -> bool:
    """Return whether three 3D points continue one straight segment."""
    forward = _subtract3(second, first)
    following = _subtract3(third, second)
    scale = math.sqrt(_dot(forward, forward)) * math.sqrt(
        _dot(following, following)
    )
    if scale <= 1e-18:
        return True
    cross = _cross3(forward, following)
    return (
        math.sqrt(_dot(cross, cross)) <= 1e-6 * scale
        and _dot(forward, following) > 0
    )


def _circle_through(
    first: Point3, second: Point3, third: Point3
) -> Optional[Tuple[Point3, float, Point3]]:
    """Return the circumcircle of three 3D points, or None if collinear."""
    forward = _subtract3(second, first)
    following = _subtract3(third, first)
    normal = _cross3(forward, following)
    area = _dot(normal, normal)
    if area <= 1e-18:
        return None
    forward_sq = _dot(forward, forward)
    following_sq = _dot(following, following)
    forward_dot = _dot(forward, following)
    alpha = following_sq * (forward_sq - forward_dot) / (2.0 * area)
    beta = forward_sq * (following_sq - forward_dot) / (2.0 * area)
    center = tuple(
        first[axis] + forward[axis] * alpha + following[axis] * beta
        for axis in range(3)
    )
    offset = _subtract3(center, first)
    radius = math.sqrt(_dot(offset, offset))
    if radius <= 1e-12:
        return None
    length = math.sqrt(area)
    unit = tuple(component / length for component in normal)
    return center, radius, unit


def _on_circle(
    point: Point3,
    center: Point3,
    radius: float,
    normal: Point3,
    tolerance: float,
) -> bool:
    """Return whether a 3D point lies on a circle within tolerance."""
    offset = _subtract3(point, center)
    radial = math.sqrt(_dot(offset, offset))
    return (
        abs(radial - radius) <= tolerance
        and abs(_dot(offset, normal)) <= tolerance
    )


def _fit_circle(
    points: Sequence[Point2],
) -> Optional[Tuple[Point2, float, float]]:
    """Least-squares circle fit plus its maximum radial error."""
    if len(points) < 3:
        return None
    count = len(points)
    sx = sy = sxx = syy = sxy = sz = sxz = syz = 0.0
    for x, y in points:
        z = x * x + y * y
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y
        sz += z
        sxz += x * z
        syz += y * z
    determinant = (
        sxx * (syy * count - sy * sy)
        - sxy * (sxy * count - sy * sx)
        + sx * (sxy * sy - syy * sx)
    )
    if abs(determinant) <= 1e-12:
        return None
    a = (
        sxz * (syy * count - sy * sy)
        - sxy * (syz * count - sy * sz)
        + sx * (syz * sy - syy * sz)
    ) / determinant
    b = (
        sxx * (syz * count - sy * sz)
        - sxz * (sxy * count - sy * sx)
        + sx * (sxy * sz - syz * sx)
    ) / determinant
    c = (
        sxx * (syy * sz - syz * sy)
        - sxy * (sxy * sz - syz * sx)
        + sxz * (sxy * sy - syy * sx)
    ) / determinant
    center = (a * 0.5, b * 0.5)
    radius_squared = c + center[0] ** 2 + center[1] ** 2
    if radius_squared <= 0.0:
        return None
    radius = math.sqrt(radius_squared)
    error = max(
        abs(_distance(center, point) - radius) for point in points
    )
    return center, radius, error


def _uniform_arc(points: Sequence[Point3]) -> bool:
    """Return whether a two-segment run looks like a sampled arc."""
    if len(points) != 3:
        return False
    first = _distance3(points[0], points[1])
    second = _distance3(points[1], points[2])
    if first <= 1e-9 or second <= 1e-9:
        return False
    if max(first, second) > min(first, second) * 1.1:
        return False
    return _turn_angle(points) > math.radians(1.0)


def _turn_angle(points: Sequence[Point3]) -> float:
    """Return the absolute direction change at the middle 3D point."""
    forward = _subtract3(points[1], points[0])
    following = _subtract3(points[2], points[1])
    cross = _cross3(forward, following)
    return abs(math.atan2(
        math.sqrt(_dot(cross, cross)), _dot(forward, following)
    ))


def _sweep_bulge(
    points: Sequence[Point2], center: Point2
) -> Optional[float]:
    """Return tan(sweep / 4) for a sampled arc, preserving direction."""
    angles = [
        math.atan2(point[1] - center[1], point[0] - center[0])
        for point in points
    ]
    sweep = 0.0
    for first, second in zip(angles, angles[1:]):
        sweep += (second - first + math.pi) % math.tau - math.pi
    if abs(sweep) <= 1e-6 or abs(sweep) >= math.tau - 1e-6:
        return None
    return math.tan(sweep * 0.25)


def _dot(first: Sequence[float], second: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _distance(first: Point2, second: Sequence[float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _distance3(first: Sequence[float], second: Sequence[float]) -> float:
    return math.sqrt(
        (first[0] - second[0]) ** 2
        + (first[1] - second[1]) ** 2
        + (first[2] - second[2]) ** 2
    )


def _subtract3(first: Sequence[float], second: Sequence[float]) -> Point3:
    return (
        first[0] - second[0],
        first[1] - second[1],
        first[2] - second[2],
    )


def _cross3(first: Sequence[float], second: Sequence[float]) -> Point3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )