"""Project solid vertices and edges onto a sketch plane.

Projected sketch entities are ordinary points and edges so they can be used
in profiles and dimensions.  Each one also carries a :class:`ProjectionSource`
that describes where it came from.  Re-resolving those sources after the
model changes lets the projection follow the solid without rerunning the
whole feature tree.
"""

import math
from typing import Optional, Sequence, Tuple, TYPE_CHECKING

from .sketch import (
    Extrude, ProjectionSource, Sketch,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import Document

Point2 = Tuple[float, float]
Point3 = Tuple[float, float, float]

# Sketch coordinates are exact enough for profile topology; a small epsilon
# absorbs floating-point noise from dot products and tessellated circles.
BIND_TOLERANCE = 1e-5


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
    """Move every projected point to its current source position."""
    for link in sketch.projected_points:
        if not 0 <= link.point < len(sketch.points):
            continue
        world = resolve_source(document, link.source)
        if world is None:
            continue
        sketch.points[link.point].set_pos(project_to_sketch(sketch, world))


def refresh_document_projections(document: "Document") -> None:
    """Refresh projected entities in every sketch."""
    for sketch in document.sketches:
        if sketch.projected_points:
            refresh_sketch(document, sketch)


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


def projected_segments(
    document: "Document",
    sketch: Sketch,
    feature_id: int,
    chain: Sequence[Sequence[float]],
) -> Tuple[
    list[Tuple[ProjectionSource, Point2]],
    list[Tuple[ProjectionSource, ProjectionSource]],
]:
    """Plan the points and edges for one picked solid edge chain."""
    points: list[Tuple[ProjectionSource, Point2]] = []
    segments: list[Tuple[ProjectionSource, ProjectionSource]] = []
    if len(chain) < 2:
        return points, segments
    sources = [
        projection_source(document, feature_id, vertex)
        for vertex in chain
    ]
    projected = [
        project_to_sketch(sketch, vertex) for vertex in chain
    ]
    used: set = set()
    for index in range(len(sources) - 1):
        start = sources[index]
        end = sources[index + 1]
        if start is None or end is None:
            continue
        if _distance(projected[index], projected[index + 1]) <= 1e-9:
            continue
        segments.append((start, end))
        used.add(start.key())
        used.add(end.key())
    seen: set = set()
    for vertex, source in zip(chain, sources):
        if source is None:
            continue
        key = source.key()
        if key not in used or key in seen:
            continue
        seen.add(key)
        points.append((source, project_to_sketch(sketch, vertex)))
    return points, segments


def _dot(first: Sequence[float], second: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _distance(first: Point2, second: Sequence[float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])
