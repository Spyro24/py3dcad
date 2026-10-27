"""Sketch and feature models for PY3DCAD."""

import math
from dataclasses import dataclass, field
from typing import (
    Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union,
)

from .profiles import intersect_loops, polygon_area
from .solver.objects import circle2d, line2d, point2d

Point = point2d
Line = line2d
Circle = circle2d
Point3 = Tuple[float, float, float]

EDGE_CONSTRAINTS = ("horizontal", "vertical")
MEASUREMENT_KINDS = ("distance", "angle")
MEASUREMENT_REF_KINDS = ("point", "line")
CIRCLE_SEGMENTS = 48


def circle_polygon(circle: Circle, segments: int = CIRCLE_SEGMENTS) -> List[Point]:
    """Return a closed polygon that approximates a circle."""
    radius = circle.diameter / 2.0
    if radius <= 0.0 or segments < 3:
        return []
    center = circle.midPoint
    return [
        (
            center[0] + radius * math.cos(2.0 * math.pi * index / segments),
            center[1] + radius * math.sin(2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    ]


def _strip_loop_spikes(loop: List[int]) -> List[int]:
    """Remove zero-area detours from a face traversal."""
    cleaned: List[int] = []
    for index in loop:
        if cleaned and cleaned[-1] == index:
            continue
        if len(cleaned) >= 2 and cleaned[-2] == index:
            cleaned.pop()
            continue
        cleaned.append(index)
    while len(cleaned) >= 3 and cleaned[0] == cleaned[-2]:
        cleaned.pop()
        cleaned.pop(0)
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    return cleaned


def normalize_measurement_kind(value: Any) -> Optional[str]:
    """Return a supported measurement kind or None."""
    if isinstance(value, str):
        value = value.lower()
        if value in MEASUREMENT_KINDS:
            return value
    return None


def normalize_measurement_ref(value: Any) -> Optional[Tuple[str, int]]:
    """Return a supported measurement entity reference or None."""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    kind = str(value[0]).lower()
    if kind not in MEASUREMENT_REF_KINDS:
        return None
    try:
        index = int(value[1])
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    return kind, index


def normalize_measurement_placement(value: Any) -> Optional[float]:
    """Return a finite measurement placement value or None.

    Distance placements are a signed perpendicular offset from the
    measured points; angle placements are the radius of the arc.
    ``None`` means the annotation uses a computed default position.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def normalize_measurement_value(value: Any) -> Optional[float]:
    """Return a finite, non-negative measurement value or None.

    Distance values are stored in sketch units; angle values are stored in
    degrees.  Unlike placements, these values are owned by the user and are
    never recomputed from the geometry after creation.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return result


def normalize_edge_constraint(value: Any) -> Optional[str]:
    """Return a supported edge constraint key or None."""
    if isinstance(value, str):
        value = value.lower()
        if value in EDGE_CONSTRAINTS:
            return value
    return None


def aligned_edge_endpoint(
    start: Point, end: Point, constraint: Optional[str]
) -> Point:
    """Return an endpoint aligned to an axis, preserving edge length."""
    constraint = normalize_edge_constraint(constraint)
    if constraint is None:
        return point2d(end)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = max(1, int(round(math.hypot(dx, dy))))
    if constraint == "horizontal":
        direction = 1 if dx >= 0 else -1
        return point2d((start[0] + direction * length, start[1]))
    direction = 1 if dy >= 0 else -1
    return point2d((start[0], start[1] + direction * length))

PLANE_KEYS = ("XY", "YZ", "ZX")
PLANE_NAMES = {
    "XY": "XY Plane",
    "YZ": "YZ Plane",
    "ZX": "ZX Plane",
}
PLANE_FRAMES: Dict[str, Tuple[Point3, Point3, Point3, Point3]] = {
    # origin, local X/u axis, local Y/v axis, outward normal
    "XY": (
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
    ),
    "YZ": (
        (0.0, 0.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 0.0),
    ),
    "ZX": (
        (0.0, 0.0, 0.0), (0.0, 0.0, 1.0),
        (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
    ),
}


@dataclass(frozen=True)
class PlaneFrame:
    """An arbitrary sketch plane with local U/V axes and a normal."""

    origin: Point3
    u: Point3
    v: Point3
    normal: Point3
    label: str = "Plane"

    def __iter__(self) -> Iterator[Point3]:
        """Allow unpacking like the legacy fixed-plane tuples."""
        yield self.origin
        yield self.u
        yield self.v
        yield self.normal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "origin": list(self.origin),
            "u": list(self.u),
            "v": list(self.v),
            "normal": list(self.normal),
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlaneFrame":
        def point(key: str, default: Point3) -> Point3:
            raw = data.get(key, default)
            if not isinstance(raw, (list, tuple)) or len(raw) < 3:
                raise ValueError(f"Invalid plane vector: {key}")
            return (float(raw[0]), float(raw[1]), float(raw[2]))

        return cls(
            origin=point("origin", (0.0, 0.0, 0.0)),
            u=point("u", (1.0, 0.0, 0.0)),
            v=point("v", (0.0, 1.0, 0.0)),
            normal=point("normal", (0.0, 0.0, 1.0)),
            label=str(data.get("label") or "Plane"),
        )


PlaneLike = Union[str, PlaneFrame]


def normalize_plane(plane: Any) -> str:
    """Return a supported origin-plane key, defaulting to XY."""
    value = str(plane or "XY").upper()
    return value if value in PLANE_FRAMES else "XY"


def plane_frame(plane: PlaneLike = "XY") -> PlaneFrame:
    """Return an origin, U axis, V axis and normal for a sketch plane."""
    if isinstance(plane, PlaneFrame):
        return plane
    key = normalize_plane(plane)
    origin, u_axis, v_axis, normal = PLANE_FRAMES[key]
    return PlaneFrame(origin, u_axis, v_axis, normal, PLANE_NAMES[key])


def point_on_plane(
    plane: PlaneLike, point: Point, offset: float = 0.0
) -> Point3:
    """Map a 2D sketch point into 3D space on its sketch plane."""
    frame = plane_frame(plane)
    origin, u_axis, v_axis, normal = (
        frame.origin, frame.u, frame.v, frame.normal,
    )
    x, y = point
    return (
        origin[0] + u_axis[0] * x + v_axis[0] * y + normal[0] * offset,
        origin[1] + u_axis[1] * x + v_axis[1] * y + normal[1] * offset,
        origin[2] + u_axis[2] * x + v_axis[2] * y + normal[2] * offset,
    )


@dataclass(frozen=True)
class Measurement:
    """A persistent distance or angle annotation between two entities."""

    kind: str
    first: Tuple[str, int]
    second: Tuple[str, int]
    # User-controlled annotation placement.  Distance measurements store a
    # signed perpendicular offset from the measured points; angle
    # measurements store the arc radius.  None selects a computed default
    # for older documents.
    placement: Optional[float] = None
    # User-owned measurement value.  Distance values use sketch units and
    # angle values use degrees.  The engine sets this once when the
    # measurement is created and only the user may change it afterwards.
    value: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "first": [self.first[0], self.first[1]],
            "second": [self.second[0], self.second[1]],
            "placement": self.placement,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Measurement"]:
        if not isinstance(data, dict):
            return None
        kind = normalize_measurement_kind(data.get("kind"))
        first = normalize_measurement_ref(data.get("first"))
        second = normalize_measurement_ref(data.get("second"))
        if kind is None or first is None or second is None:
            return None
        return cls(
            kind,
            first,
            second,
            normalize_measurement_placement(data.get("placement")),
            normalize_measurement_value(data.get("value")),
        )


@dataclass
class Sketch:
    """A named set of points on a plane, in millimetres.

    Origin-plane sketches keep their ``plane`` key.  Sketches created on a
    solid face additionally carry a custom ``PlaneFrame``; the ``plane`` key
    remains as a backwards-compatible fallback and serialisation anchor.
    """

    id: int
    name: str
    points: List[Point] = field(default_factory=list)
    plane: str = "XY"
    plane_label: Optional[str] = None
    plane_origin: Optional[Point3] = None
    plane_u: Optional[Point3] = None
    plane_v: Optional[Point3] = None
    plane_normal: Optional[Point3] = None
    line_type: str = "normal"
    edges: List[Tuple[int, int]] = field(default_factory=list)
    edge_constraints: List[Optional[str]] = field(default_factory=list)
    circles: List[Circle] = field(default_factory=list)
    measurements: List[Measurement] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.points = [point2d(point) for point in self.points]
        circles = [
            circle
            for circle in (
                self._normalize_circle(item) for item in self.circles
            )
            if circle is not None
        ]
        self.circles = []
        self.edges = [
            (start, end)
            for start, end in self.edges
            if (
                0 <= start < len(self.points)
                and 0 <= end < len(self.points)
                and start != end
            )
        ]
        constraints = [
            normalize_edge_constraint(value)
            for value in self.edge_constraints[:len(self.edges)]
        ]
        constraints.extend(
            [None] * (len(self.edges) - len(constraints))
        )
        self.edge_constraints = constraints
        measurements: List[Measurement] = []
        for item in self.measurements:
            if isinstance(item, Measurement):
                measurement = item
            elif isinstance(item, dict):
                measurement = Measurement.from_dict(item)
            else:
                measurement = None
            if measurement is None:
                continue
            kind = normalize_measurement_kind(measurement.kind)
            first = normalize_measurement_ref(measurement.first)
            second = normalize_measurement_ref(measurement.second)
            if kind is None or first is None or second is None:
                continue
            refs_valid = True
            for ref_kind, ref_index in (first, second):
                limit = (
                    len(self.points) if ref_kind == "point"
                    else len(self.edges)
                )
                if not 0 <= ref_index < limit:
                    refs_valid = False
                    break
            if refs_valid:
                measurements.append(
                    Measurement(
                        kind,
                        first,
                        second,
                        normalize_measurement_placement(
                            measurement.placement
                        ),
                        normalize_measurement_value(
                            measurement.value
                        ),
                    )
                )
        self.measurements = measurements
        # Older documents did not store a measurement value.  Freeze one
        # from the current geometry exactly once so the engine never
        # overwrites a measurement afterwards.
        for index, measurement in enumerate(self.measurements):
            if measurement.value is not None:
                continue
            value = self.measurement_value(
                measurement.kind,
                measurement.first,
                measurement.second,
            )
            if value is None:
                continue
            self.measurements[index] = Measurement(
                measurement.kind,
                measurement.first,
                measurement.second,
                measurement.placement,
                value,
            )
        # Bind circles first so their midpoints exist as regular points
        # before measurement enforcement runs on the point list.
        self.circles = self._bind_circles(circles)
        # A loaded sketch may predate dimension enforcement.  Make its
        # stored values authoritative immediately, without a command.
        self.enforce_measurements(self.points)

    def _bind_circles(self, circles: Iterable[Circle]) -> List[Circle]:
        """Make each circle midpoint a regular point of the sketch.

        Each circle gets its own point, even when several circles share a
        centre, so every circle loop can be identified by its point index.
        """
        bound: List[Circle] = []
        used: set = set()
        for circle in circles:
            index: Optional[int] = None
            for candidate, existing in enumerate(self.points):
                if candidate not in used and existing is circle.midPoint:
                    index = candidate
                    break
            if index is None:
                for candidate, existing in enumerate(self.points):
                    if candidate not in used and existing == circle.midPoint:
                        index = candidate
                        break
            if index is None:
                index = self.add_point(circle.midPoint)
            circle.midPoint = self.points[index]
            used.add(index)
            bound.append(circle)
        return bound

    def apply_point_positions(self, positions: Iterable[Point]) -> None:
        """Copy positions into existing points without replacing them.

        Circles hold references to their midpoint objects, so commands must
        move the existing point rather than swap in a new object.
        """
        for point, position in zip(self.points, positions):
            point.set_pos(position)

    def measurement_entity_points(
        self,
        ref: Tuple[str, int],
        points: Optional[List[Point]] = None,
    ) -> Optional[Tuple[Point, Point]]:
        """Return the endpoints used by a point or line measurement ref."""
        source = self.points if points is None else points
        kind, index = ref
        if kind == "point":
            if 0 <= index < len(source):
                point = source[index]
                return point, point
            return None
        if kind == "line":
            if 0 <= index < len(self.edges):
                start, end = self.edges[index]
                if (
                    0 <= start < len(source)
                    and 0 <= end < len(source)
                ):
                    return source[start], source[end]
        return None

    @staticmethod
    def closest_point_on_segment(
        point: Point, start: Point, end: Point
    ) -> Point:
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        length_squared = delta_x * delta_x + delta_y * delta_y
        if length_squared <= 1e-12:
            return point2d(start)
        factor = (
            (point[0] - start[0]) * delta_x
            + (point[1] - start[1]) * delta_y
        ) / length_squared
        factor = max(0.0, min(1.0, factor))
        return point2d((
            start[0] + factor * delta_x,
            start[1] + factor * delta_y,
        ))

    @classmethod
    def segments_closest_points(
        cls,
        first_start: Point,
        first_end: Point,
        second_start: Point,
        second_end: Point,
    ) -> Tuple[Point, Point]:
        intersection = cls.segments_intersection(
            first_start, first_end, second_start, second_end
        )
        if intersection is not None:
            return intersection, intersection
        candidates = [
            (
                first_start,
                cls.closest_point_on_segment(
                    first_start, second_start, second_end
                ),
            ),
            (
                first_end,
                cls.closest_point_on_segment(
                    first_end, second_start, second_end
                ),
            ),
            (
                cls.closest_point_on_segment(
                    second_start, first_start, first_end
                ),
                second_start,
            ),
            (
                cls.closest_point_on_segment(
                    second_end, first_start, first_end
                ),
                second_end,
            ),
        ]
        return min(
            candidates,
            key=lambda pair: math.hypot(
                pair[1][0] - pair[0][0],
                pair[1][1] - pair[0][1],
            ),
        )

    @staticmethod
    def segments_intersection(
        first_start: Point,
        first_end: Point,
        second_start: Point,
        second_end: Point,
    ) -> Optional[Point]:
        epsilon = 1e-9

        def cross(
            ax: float, ay: float, bx: float, by: float
        ) -> float:
            return ax * by - ay * bx

        def orientation(a: Point, b: Point, c: Point) -> float:
            return cross(
                b[0] - a[0], b[1] - a[1],
                c[0] - a[0], c[1] - a[1],
            )

        def on_segment(a: Point, b: Point, point: Point) -> bool:
            return (
                min(a[0], b[0]) - epsilon
                <= point[0] <= max(a[0], b[0]) + epsilon
                and min(a[1], b[1]) - epsilon
                <= point[1] <= max(a[1], b[1]) + epsilon
            )

        first_cross = orientation(
            first_start, first_end, second_start
        )
        second_cross = orientation(
            first_start, first_end, second_end
        )
        third_cross = orientation(
            second_start, second_end, first_start
        )
        fourth_cross = orientation(
            second_start, second_end, first_end
        )
        if (
            (first_cross > epsilon and second_cross < -epsilon)
            or (first_cross < -epsilon and second_cross > epsilon)
        ) and (
            (third_cross > epsilon and fourth_cross < -epsilon)
            or (third_cross < -epsilon and fourth_cross > epsilon)
        ):
            delta_x = first_end[0] - first_start[0]
            delta_y = first_end[1] - first_start[1]
            other_x = second_end[0] - second_start[0]
            other_y = second_end[1] - second_start[1]
            denominator = cross(delta_x, delta_y, other_x, other_y)
            if abs(denominator) <= epsilon:
                return None
            factor = cross(
                second_start[0] - first_start[0],
                second_start[1] - first_start[1],
                other_x,
                other_y,
            ) / denominator
            return point2d((
                first_start[0] + factor * delta_x,
                first_start[1] + factor * delta_y,
            ))
        if (
            abs(first_cross) <= epsilon
            and on_segment(first_start, first_end, second_start)
        ):
            return point2d(second_start)
        if (
            abs(second_cross) <= epsilon
            and on_segment(first_start, first_end, second_end)
        ):
            return point2d(second_end)
        if (
            abs(third_cross) <= epsilon
            and on_segment(second_start, second_end, first_start)
        ):
            return point2d(first_start)
        if (
            abs(fourth_cross) <= epsilon
            and on_segment(second_start, second_end, first_end)
        ):
            return point2d(first_end)
        return None

    def angle_geometry(
        self,
        first: Tuple[str, int],
        second: Tuple[str, int],
        points: Optional[List[Point]] = None,
    ) -> Optional[Tuple[float, Point, Point, Point]]:
        """Return angle, shared vertex, and rays, if the edges meet."""
        source = self.points if points is None else points
        if first[0] != "line" or second[0] != "line":
            return None
        if not (
            0 <= first[1] < len(self.edges)
            and 0 <= second[1] < len(self.edges)
        ):
            return None
        first_edge = self.edges[first[1]]
        second_edge = self.edges[second[1]]
        shared = set(first_edge) & set(second_edge)
        if len(shared) != 1:
            return None
        vertex_index = next(iter(shared))
        first_far = (
            first_edge[0]
            if first_edge[1] == vertex_index
            else first_edge[1]
        )
        second_far = (
            second_edge[0]
            if second_edge[1] == vertex_index
            else second_edge[1]
        )
        if first_far == vertex_index or second_far == vertex_index:
            return None
        vertex = source[vertex_index]
        first_point = source[first_far]
        second_point = source[second_far]
        first_x = first_point[0] - vertex[0]
        first_y = first_point[1] - vertex[1]
        second_x = second_point[0] - vertex[0]
        second_y = second_point[1] - vertex[1]
        first_length = math.hypot(first_x, first_y)
        second_length = math.hypot(second_x, second_y)
        if first_length <= 1e-9 or second_length <= 1e-9:
            return None
        cosine = (
            first_x * second_x + first_y * second_y
        ) / (first_length * second_length)
        cosine = max(-1.0, min(1.0, cosine))
        angle = math.degrees(math.acos(cosine))
        return angle, vertex, first_point, second_point

    def distance_geometry(
        self,
        first: Tuple[str, int],
        second: Tuple[str, int],
        points: Optional[List[Point]] = None,
    ) -> Optional[Tuple[float, Point, Point]]:
        """Return the shortest distance and the measured points."""
        first_points = self.measurement_entity_points(first, points)
        second_points = self.measurement_entity_points(second, points)
        if first_points is None or second_points is None:
            return None
        if first[0] == "point" and second[0] == "point":
            first_point = first_points[0]
            second_point = second_points[0]
        elif first[0] == "point":
            first_point = first_points[0]
            second_point = self.closest_point_on_segment(
                first_point, second_points[0], second_points[1]
            )
        elif second[0] == "point":
            second_point = second_points[0]
            first_point = self.closest_point_on_segment(
                second_point, first_points[0], first_points[1]
            )
        else:
            first_point, second_point = self.segments_closest_points(
                first_points[0], first_points[1],
                second_points[0], second_points[1],
            )
        distance = math.hypot(
            second_point[0] - first_point[0],
            second_point[1] - first_point[1],
        )
        return distance, first_point, second_point

    def measurement_value(
        self,
        kind: str,
        first: Tuple[str, int],
        second: Tuple[str, int],
        points: Optional[List[Point]] = None,
    ) -> Optional[float]:
        """Return the value for a measurement from the geometry."""
        if kind == "angle":
            geometry = self.angle_geometry(first, second, points)
        elif kind == "distance":
            geometry = self.distance_geometry(first, second, points)
        else:
            return None
        return geometry[0] if geometry is not None else None

    def measurement_residual(
        self, measurement: Measurement, points: List[Point]
    ) -> Optional[float]:
        """Return target minus current for one measurement, if usable."""
        if measurement.value is None:
            return None
        current = self.measurement_value(
            measurement.kind,
            measurement.first,
            measurement.second,
            points,
        )
        if current is None:
            return None
        target = measurement.value
        if measurement.kind == "angle" and target > 180:
            target = 360.0 - target
        return target - current

    def measurement_max_error(self, points: List[Point]) -> float:
        """Return the largest absolute measurement residual."""
        maximum = 0.0
        for measurement in self.measurements:
            residual = self.measurement_residual(measurement, points)
            if residual is not None:
                maximum = max(maximum, abs(residual))
        return maximum

    def enforce_measurements(
        self,
        points: List[Point],
        iterations: int = 48,
        tolerance: float = 1e-6,
    ) -> bool:
        """Project points until all fixed measurement values are satisfied."""
        if not self.measurements or len(points) != len(self.points):
            return True
        # The projection helpers replace point objects.  Keep the caller's
        # originals alive so circles and other references stay bound to the
        # same point instances, then copy the final positions back into them.
        originals = list(points)
        try:
            for _ in range(max(1, iterations)):
                projected = False
                before_projection = list(points)
                for measurement in self.measurements:
                    residual = self.measurement_residual(
                        measurement, points
                    )
                    if residual is None or abs(residual) <= tolerance:
                        continue
                    if measurement.kind == "distance":
                        changed = self._project_distance(
                            points, measurement, residual
                        )
                        projected = projected or changed
                    elif measurement.kind == "angle":
                        changed = self._project_angle(
                            points, measurement, residual
                        )
                        projected = projected or changed
                if not projected:
                    return (
                        self.measurement_max_error(points)
                        <= tolerance
                    )
                # A projection may move only part of an axis-constrained
                # edge.  Snap the other endpoints by translating the whole
                # group by the correction instead of anchoring it to an
                # arbitrary first point, which would undo the projection.
                self.constrain_axis_changes(
                    points,
                    range(len(points)),
                    previous=before_projection,
                )
                if self.measurement_max_error(points) <= tolerance:
                    return True
            return self.measurement_max_error(points) <= tolerance
        finally:
            for index, original in enumerate(originals):
                original.set_pos(points[index])
                points[index] = original

    def enforced_points(self, points: List[Point]) -> List[Point]:
        """Return a copy of points with measurement constraints applied."""
        result = [point2d(point) for point in points]
        self.enforce_measurements(result)
        return result

    def _project_distance(
        self,
        points: List[Point],
        measurement: Measurement,
        residual: float,
    ) -> bool:
        geometry = self.distance_geometry(
            measurement.first, measurement.second, points
        )
        if geometry is None or abs(residual) <= 1e-12:
            return False
        current, first_point, second_point = geometry
        if current > 1e-9:
            direction_x = (
                second_point[0] - first_point[0]
            ) / current
            direction_y = (
                second_point[1] - first_point[1]
            ) / current
        else:
            direction_x, direction_y = (
                self._distance_separation_direction(
                    points, measurement, first_point, second_point
                )
            )
        first_group = self._measurement_side_points(
            points, measurement.first, first_point
        )
        second_group = self._measurement_side_points(
            points, measurement.second, second_point
        )
        if (
            measurement.first[0] == "line"
            and measurement.second[0] == "line"
            and self._lines_parallel(points, measurement)
        ):
            first_group = self._edge_point_indices(
                measurement.first
            )
            second_group = self._edge_point_indices(
                measurement.second
            )
        if not first_group and not second_group:
            return False
        if set(first_group) & set(second_group):
            return False
        if first_group and second_group:
            first_weight = second_weight = 0.5
        elif first_group:
            first_weight, second_weight = 1.0, 0.0
        else:
            first_weight, second_weight = 0.0, 1.0
        offsets: Dict[int, Tuple[float, float]] = {}
        self._add_offsets(
            offsets,
            first_group,
            -direction_x * residual * first_weight,
            -direction_y * residual * first_weight,
        )
        self._add_offsets(
            offsets,
            second_group,
            direction_x * residual * second_weight,
            direction_y * residual * second_weight,
        )
        self._apply_point_offsets(points, offsets)
        return True

    def _measurement_side_points(
        self,
        points: List[Point],
        ref: Tuple[str, int],
        closest: Point,
    ) -> List[int]:
        kind, index = ref
        if kind == "point":
            return [index] if 0 <= index < len(points) else []
        if kind != "line" or not 0 <= index < len(self.edges):
            return []
        start, end = self.edges[index]
        if not (
            0 <= start < len(points)
            and 0 <= end < len(points)
        ):
            return []
        start_point = points[start]
        end_point = points[end]
        if math.hypot(
            closest[0] - start_point[0],
            closest[1] - start_point[1],
        ) <= 1e-7:
            return [start]
        if math.hypot(
            closest[0] - end_point[0],
            closest[1] - end_point[1],
        ) <= 1e-7:
            return [end]
        return [start, end]

    def _edge_point_indices(
        self, ref: Tuple[str, int]
    ) -> List[int]:
        if ref[0] != "line" or not 0 <= ref[1] < len(self.edges):
            return []
        start, end = self.edges[ref[1]]
        if not (
            0 <= start < len(self.points)
            and 0 <= end < len(self.points)
        ):
            return []
        return [start, end]

    def _lines_parallel(
        self,
        points: List[Point],
        measurement: Measurement,
    ) -> bool:
        first = self.measurement_entity_points(
            measurement.first, points
        )
        second = self.measurement_entity_points(
            measurement.second, points
        )
        if first is None or second is None:
            return False
        first_x = first[1][0] - first[0][0]
        first_y = first[1][1] - first[0][1]
        second_x = second[1][0] - second[0][0]
        second_y = second[1][1] - second[0][1]
        first_length = math.hypot(first_x, first_y)
        second_length = math.hypot(second_x, second_y)
        if first_length <= 1e-9 or second_length <= 1e-9:
            return False
        cross = abs(
            first_x * second_y - first_y * second_x
        ) / (first_length * second_length)
        return cross <= 1e-7

    def _distance_separation_direction(
        self,
        points: List[Point],
        measurement: Measurement,
        first_point: Point,
        second_point: Point,
    ) -> Tuple[float, float]:
        for ref in (measurement.first, measurement.second):
            if ref[0] != "line":
                continue
            entity = self.measurement_entity_points(ref, points)
            if entity is None:
                continue
            delta_x = entity[1][0] - entity[0][0]
            delta_y = entity[1][1] - entity[0][1]
            length = math.hypot(delta_x, delta_y)
            if length > 1e-9:
                return -delta_y / length, delta_x / length
        delta_x = second_point[0] - first_point[0]
        delta_y = second_point[1] - first_point[1]
        length = math.hypot(delta_x, delta_y)
        if length > 1e-9:
            return delta_x / length, delta_y / length
        return 1.0, 0.0

    def _project_angle(
        self,
        points: List[Point],
        measurement: Measurement,
        residual: float,
    ) -> bool:
        geometry = self.angle_geometry(
            measurement.first, measurement.second, points
        )
        if geometry is None or abs(residual) <= 1e-12:
            return False
        current, vertex, first_point, second_point = geometry
        target = measurement.value
        if target is None:
            return False
        if target > 180:
            target = 360.0 - target
        delta = math.radians(target - current)
        if abs(delta) <= 1e-12:
            return False
        first_edge = self.edges[measurement.first[1]]
        second_edge = self.edges[measurement.second[1]]
        shared = set(first_edge) & set(second_edge)
        if len(shared) != 1:
            return False
        vertex_index = next(iter(shared))
        first_far = (
            first_edge[0]
            if first_edge[1] == vertex_index
            else first_edge[1]
        )
        second_far = (
            second_edge[0]
            if second_edge[1] == vertex_index
            else second_edge[1]
        )
        first_x = first_point[0] - vertex[0]
        first_y = first_point[1] - vertex[1]
        second_x = second_point[0] - vertex[0]
        second_y = second_point[1] - vertex[1]
        cross = first_x * second_y - first_y * second_x
        sign = 1.0 if cross >= 0 else -1.0
        half = sign * delta / 2.0
        first_rotated = self._rotate_vector(
            first_x, first_y, -half
        )
        second_rotated = self._rotate_vector(
            second_x, second_y, half
        )
        points[first_far] = point2d((
            vertex[0] + first_rotated[0],
            vertex[1] + first_rotated[1],
        ))
        points[second_far] = point2d((
            vertex[0] + second_rotated[0],
            vertex[1] + second_rotated[1],
        ))
        return True

    @staticmethod
    def _rotate_vector(
        delta_x: float, delta_y: float, angle: float
    ) -> Tuple[float, float]:
        cosine = math.cos(angle)
        sine = math.sin(angle)
        return (
            delta_x * cosine - delta_y * sine,
            delta_x * sine + delta_y * cosine,
        )

    @staticmethod
    def _add_offsets(
        offsets: Dict[int, Tuple[float, float]],
        indices: Iterable[int],
        delta_x: float,
        delta_y: float,
    ) -> None:
        for index in indices:
            previous = offsets.get(index, (0.0, 0.0))
            offsets[index] = (
                previous[0] + delta_x,
                previous[1] + delta_y,
            )

    @staticmethod
    def _apply_point_offsets(
        points: List[Point],
        offsets: Dict[int, Tuple[float, float]],
    ) -> None:
        for index, (delta_x, delta_y) in offsets.items():
            if 0 <= index < len(points):
                point = points[index]
                points[index] = point2d((
                    point[0] + delta_x,
                    point[1] + delta_y,
                ))

    def edge_constraint(self, index: int) -> Optional[str]:
        """Return the axis constraint for an edge, if any."""
        if 0 <= index < len(self.edge_constraints):
            return self.edge_constraints[index]
        return None

    def constrain_axis_changes(
        self,
        points: List[Point],
        changed: Iterable[int],
        locked: Optional[Iterable[int]] = None,
        excluded_edges: Optional[Iterable[int]] = None,
        previous: Optional[List[Point]] = None,
    ) -> None:
        """Enforce all axis constraints after points have been changed.

        Horizontal constraints make the y-coordinates of their endpoints
        equal, and vertical constraints do the same for x-coordinates.  Each
        connected group is therefore solved independently for the affected
        axis.  ``locked`` lists the preferred anchor points in priority
        order; the first anchor in a group provides its target coordinate.
        Remaining points in the group follow, which keeps every constraint
        satisfied even when several previously constrained edges meet.

        Edges in ``excluded_edges`` are ignored, allowing an edge's old
        constraint to be replaced without it fighting the new alignment.

        When ``previous`` is supplied, the group is translated by the mean
        displacement of its moved points instead of being pinned to one
        anchor.  Measurement enforcement uses this so that moving one
        corner of a constrained edge moves the whole edge rather than being
        snapped back to the other, stationary corner.
        """
        count = len(points)
        if count == 0:
            return
        changed_order = list(changed)
        locked_order = (
            list(locked) if locked is not None else list(changed_order)
        )
        excluded = set(excluded_edges or ())

        horizontal = list(range(count))
        vertical = list(range(count))

        def root(parent: List[int], index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def join(parent: List[int], first: int, second: int) -> None:
            first_root = root(parent, first)
            second_root = root(parent, second)
            if first_root != second_root:
                parent[second_root] = first_root

        for index, (first, second) in enumerate(self.edges):
            if index in excluded:
                continue
            if not (
                0 <= first < count
                and 0 <= second < count
            ):
                continue
            constraint = self.edge_constraint(index)
            if constraint == "horizontal":
                join(horizontal, first, second)
            elif constraint == "vertical":
                join(vertical, first, second)

        for parent, axis in ((horizontal, 1), (vertical, 0)):
            groups: Dict[int, List[int]] = {}
            for index in range(count):
                groups.setdefault(root(parent, index), []).append(index)
            for members in groups.values():
                member_set = set(members)
                target: Optional[float] = None
                anchor = members[0]
                for index in locked_order:
                    if index in member_set:
                        anchor = index
                        break
                else:
                    for index in changed_order:
                        if index in member_set:
                            anchor = index
                            break
                if previous is not None and len(previous) == count:
                    shifts = [
                        points[index][axis] - previous[index][axis]
                        for index in members
                        if abs(
                            points[index][axis]
                            - previous[index][axis]
                        ) > 1e-12
                    ]
                    if shifts:
                        target = (
                            previous[anchor][axis]
                            + sum(shifts) / len(shifts)
                        )
                if target is None:
                    target = points[anchor][axis]
                for index in members:
                    point = points[index]
                    points[index] = point2d((
                        (target, point[1])
                        if axis == 0
                        else (point[0], target)
                    ))

    @property
    def lines(self) -> List[Line]:
        """Return edges as live line geometry objects."""
        return [
            line2d((self.points[start], self.points[end]))
            for start, end in self.edges
        ]

    def closed_loops(self) -> List[List[int]]:
        """Return every closed profile as a point-index loop.

        Edge loops are ordered point indices (three or more).  A circle is a
        one-element loop holding its midpoint index, so circles can be picked
        and extruded like any other closed profile.  Adjacent edge faces stay
        separate here; :func:`core.profiles.union_profiles` merges them when
        the user selects several for an extrude.
        """
        loops = self._edge_loops()
        loops.extend(self._circle_loops())
        return loops

    def _circle_loops(self) -> List[List[int]]:
        loops: List[List[int]] = []
        for circle in self.circles:
            if circle.diameter <= 0.0:
                continue
            index = self.point_index(circle.midPoint)
            if index is not None:
                loops.append([index])
        return loops

    def _edge_loops(self) -> List[List[int]]:
        if len(self.edges) < 3:
            return []
        adjacency: Dict[int, List[int]] = {}
        for start, end in self.edges:
            if start == end:
                continue
            adjacency.setdefault(start, []).append(end)
            adjacency.setdefault(end, []).append(start)
        self._prune_leaves(adjacency)
        if len(adjacency) < 3:
            return []
        for node, neighbors in adjacency.items():
            origin = self.points[node]
            neighbors.sort(key=lambda other: math.atan2(
                self.points[other][1] - origin[1],
                self.points[other][0] - origin[0],
            ))

        visited: set[Tuple[int, int]] = set()
        loops: List[List[int]] = []
        for start, neighbors in adjacency.items():
            for neighbor in neighbors:
                if (start, neighbor) in visited:
                    continue
                loop = self._trace_face(
                    start, neighbor, adjacency, visited
                )
                if loop is None:
                    continue
                cleaned = _strip_loop_spikes(loop)
                if (
                    len(cleaned) < 3
                    or len(set(cleaned)) != len(cleaned)
                ):
                    continue
                points = [self.points[index] for index in cleaned]
                if polygon_area(points) > 1e-9:
                    loops.append(cleaned)
        return loops

    @staticmethod
    def _prune_leaves(adjacency: Dict[int, List[int]]) -> None:
        """Drop tree branches that cannot belong to a closed face."""
        pending = [
            node for node, neighbors in adjacency.items()
            if len(neighbors) < 2
        ]
        while pending:
            node = pending.pop()
            neighbors = adjacency.pop(node, None)
            if neighbors is None:
                continue
            for neighbor in neighbors:
                if neighbor not in adjacency:
                    continue
                if node in adjacency[neighbor]:
                    adjacency[neighbor].remove(node)
                if len(adjacency[neighbor]) < 2:
                    pending.append(neighbor)

    @staticmethod
    def _trace_face(
        start: int,
        first: int,
        adjacency: Dict[int, List[int]],
        visited: set[Tuple[int, int]],
    ) -> Optional[List[int]]:
        """Walk the half-edge face that keeps the interior on the left."""
        loop: List[int] = []
        current = start
        following = first
        while True:
            if (current, following) in visited:
                return None
            visited.add((current, following))
            loop.append(current)
            neighbors = adjacency.get(following, [])
            if current not in neighbors:
                return None
            index = neighbors.index(current)
            next_vertex = neighbors[(index - 1) % len(neighbors)]
            current, following = following, next_vertex
            if current == start:
                return loop if following == first else None

    def profile_indices(self) -> List[int]:
        """Return the first closed profile, or an empty list."""
        loops = self.closed_loops()
        return loops[0] if loops else []

    def profile_points(self) -> List[Point]:
        """Return the ordered points of the first extrudable profile."""
        return self.loop_points(self.profile_indices())

    def point_index(self, point: Point) -> Optional[int]:
        """Return the index of a point, preferring object identity."""
        for index, existing in enumerate(self.points):
            if existing is point:
                return index
        return self.find_point(point)

    def circle_for_loop(self, loop: Sequence[int]) -> Optional[Circle]:
        """Return the circle represented by a one-index loop."""
        if len(loop) != 1:
            return None
        index = loop[0]
        if not 0 <= index < len(self.points):
            return None
        point = self.points[index]
        for circle in self.circles:
            if circle.midPoint is point:
                return circle
        for circle in self.circles:
            if circle.midPoint == point:
                return circle
        return None

    def loop_points(self, loop: Sequence[int]) -> List[Point]:
        """Return the polygon for an edge loop or a circle loop."""
        circle = self.circle_for_loop(loop)
        if circle is not None:
            return circle_polygon(circle)
        if len(loop) < 3:
            return []
        if any(not 0 <= index < len(self.points) for index in loop):
            return []
        return [self.points[index] for index in loop]

    def loop_area(self, loop: Sequence[int]) -> float:
        """Return the area of an edge loop or circle loop."""
        circle = self.circle_for_loop(loop)
        if circle is not None:
            return math.pi * circle.radius * circle.radius
        points = self.loop_points(loop)
        if len(points) < 3:
            return 0.0
        return abs(polygon_area(points))

    def find_point(self, point: Point) -> Optional[int]:
        """Find an existing point by its coordinates."""
        for index, existing in enumerate(self.points):
            if existing == point:
                return index
        return None

    def add_point(self, point: Point) -> int:
        """Append a standalone point."""
        index = len(self.points)
        self.points.append(point2d(point))
        return index

    def remove_point(self, index: int) -> None:
        """Remove a point, its edges, and measurements that depend on them."""
        if not 0 <= index < len(self.points):
            return
        removed_point = self.points.pop(index)
        self.circles = [
            circle for circle in self.circles
            if circle.midPoint is not removed_point
        ]
        shifted: List[Tuple[int, int]] = []
        constraints: List[Optional[str]] = []
        edge_map: Dict[int, int] = {}
        for edge_index, (start, end) in enumerate(self.edges):
            if start == index or end == index:
                continue
            edge_map[edge_index] = len(shifted)
            shifted.append((
                start if start < index else start - 1,
                end if end < index else end - 1,
            ))
            constraints.append(self.edge_constraint(edge_index))
        self.edges = shifted
        self.edge_constraints = constraints

        measurements: List[Measurement] = []
        for measurement in self.measurements:
            first = self._remap_measurement_ref(
                measurement.first, index, edge_map
            )
            second = self._remap_measurement_ref(
                measurement.second, index, edge_map
            )
            if first is not None and second is not None:
                measurements.append(
                    Measurement(
                        measurement.kind,
                        first,
                        second,
                        measurement.placement,
                        measurement.value,
                    )
                )
        self.measurements = measurements

    def remove_edge(self, index: int) -> None:
        """Remove one edge and any measurement that depends on it."""
        if not 0 <= index < len(self.edges):
            return
        del self.edges[index]
        if index < len(self.edge_constraints):
            del self.edge_constraints[index]
        measurements: List[Measurement] = []
        for measurement in self.measurements:
            first = self._remap_removed_edge_ref(
                measurement.first, index
            )
            second = self._remap_removed_edge_ref(
                measurement.second, index
            )
            if first is not None and second is not None:
                measurements.append(
                    Measurement(
                        measurement.kind,
                        first,
                        second,
                        measurement.placement,
                        measurement.value,
                    )
                )
        self.measurements = measurements

    @staticmethod
    def _remap_removed_edge_ref(
        ref: Tuple[str, int], removed: int
    ) -> Optional[Tuple[str, int]]:
        """Shift a line measurement past a deleted edge."""
        kind, index = ref
        if kind != "line":
            return ref
        if index == removed:
            return None
        return (kind, index - 1 if index > removed else index)

    @staticmethod
    def _remap_measurement_ref(
        ref: Tuple[str, int],
        removed_point: int,
        edge_map: Dict[int, int],
    ) -> Optional[Tuple[str, int]]:
        kind, index = ref
        if kind == "point":
            if index == removed_point:
                return None
            return (kind, index - 1 if index > removed_point else index)
        if kind == "line":
            mapped = edge_map.get(index)
            return (kind, mapped) if mapped is not None else None
        return None

    @staticmethod
    def _normalize_circle(value: Any) -> Optional[Circle]:
        """Return a valid circle from a stored or in-memory value."""
        if isinstance(value, circle2d):
            center = value.midPoint
            diameter = value.diameter
        elif isinstance(value, dict):
            center = value.get("center", value.get("midPoint"))
            diameter = value.get("diameter")
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            center = value[0]
            diameter = value[1]
        else:
            return None
        if not isinstance(center, (list, tuple, point2d)) or len(center) < 2:
            return None
        try:
            center_point = point2d(center)
            diameter_value = float(diameter)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(diameter_value) or diameter_value <= 0:
            return None
        return circle2d(center_point, diameter_value)

    @property
    def is_custom_plane(self) -> bool:
        return all(
            value is not None
            for value in (
                self.plane_origin,
                self.plane_u,
                self.plane_v,
                self.plane_normal,
            )
        )

    @property
    def display_plane(self) -> str:
        if self.plane_label:
            return self.plane_label
        return PLANE_NAMES[normalize_plane(self.plane)]

    def frame(self) -> PlaneFrame:
        if self.is_custom_plane:
            return PlaneFrame(
                self.plane_origin,  # type: ignore[arg-type]
                self.plane_u,  # type: ignore[arg-type]
                self.plane_v,  # type: ignore[arg-type]
                self.plane_normal,  # type: ignore[arg-type]
                self.plane_label or "Face",
            )
        return plane_frame(self.plane)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "plane": normalize_plane(self.plane),
            "points": [[x, y] for x, y in self.points],
            "edges": [
                [start, end] for start, end in self.edges
            ],
            "edge_constraints": list(self.edge_constraints),
            "circles": [
                {
                    "center": [circle.midPoint[0], circle.midPoint[1]],
                    "diameter": circle.diameter,
                }
                for circle in self.circles
            ],
            "measurements": [
                measurement.to_dict()
                for measurement in self.measurements
            ],
            "line_type": self.line_type,
            # Kept for older readers; edges are the source of truth.
            "lines": [
                [[start[0], start[1]], [end[0], end[1]]]
                for start, end in self.lines
            ],
        }
        if self.is_custom_plane:
            data["plane_frame"] = self.frame().to_dict()
            data["plane_label"] = self.plane_label or "Face"
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Sketch":
        points: List[Point] = []
        for raw in data.get("points", []):
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                try:
                    points.append((float(raw[0]), float(raw[1])))
                except (TypeError, ValueError):
                    continue

        plane_label: Optional[str] = None
        plane_origin: Optional[Point3] = None
        plane_u: Optional[Point3] = None
        plane_v: Optional[Point3] = None
        plane_normal: Optional[Point3] = None
        frame_data = data.get("plane_frame")
        if isinstance(frame_data, dict):
            try:
                frame = PlaneFrame.from_dict(frame_data)
            except (TypeError, ValueError):
                frame = None
            if frame is not None:
                plane_origin = frame.origin
                plane_u = frame.u
                plane_v = frame.v
                plane_normal = frame.normal
                plane_label = str(
                    data.get("plane_label") or frame.label or "Face"
                )

        line_type = str(data.get("line_type", "normal"))
        edges: List[Tuple[int, int]] = []
        constraints: List[Optional[str]] = []
        raw_edges = data.get("edges")
        raw_profile = data.get("profile")
        raw_constraints = data.get("edge_constraints")
        if not isinstance(raw_constraints, (list, tuple)):
            raw_constraints = []
        if isinstance(raw_edges, (list, tuple)):
            for raw_index, raw in enumerate(raw_edges):
                if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                    continue
                try:
                    start = int(raw[0])
                    end = int(raw[1])
                except (TypeError, ValueError):
                    continue
                if (
                    0 <= start < len(points)
                    and 0 <= end < len(points)
                    and start != end
                ):
                    edges.append((start, end))
                    constraint = (
                        raw_constraints[raw_index]
                        if raw_index < len(raw_constraints)
                        else None
                    )
                    constraints.append(
                        normalize_edge_constraint(constraint)
                    )
            # Older point-profile sketches stored their loop separately.
            cls._add_loop_edges(
                edges, cls._valid_profile(raw_profile, len(points))
            )
        else:
            # Legacy sketches draw a profile through their ordered points
            # and store extra edge coordinates separately.
            if isinstance(raw_profile, (list, tuple)):
                profile = cls._valid_profile(raw_profile, len(points))
            else:
                profile = list(range(len(points)))
            cls._add_loop_edges(edges, profile)
            raw_lines = data.get("lines", [])
            if not isinstance(raw_lines, (list, tuple)):
                raw_lines = []
            for raw in raw_lines:
                if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                    continue
                try:
                    start = (float(raw[0][0]), float(raw[0][1]))
                    end = (float(raw[1][0]), float(raw[1][1]))
                except (TypeError, ValueError, IndexError):
                    continue
                start_index = cls._find_or_add_point(points, start)
                end_index = cls._find_or_add_point(points, end)
                cls._add_edge(edges, start_index, end_index)

        constraints.extend([None] * (len(edges) - len(constraints)))
        circles: List[Circle] = []
        raw_circles = data.get("circles", [])
        if isinstance(raw_circles, (list, tuple)):
            for raw in raw_circles:
                circle = cls._normalize_circle(raw)
                if circle is not None:
                    circles.append(circle)
        measurements: List[Measurement] = []
        raw_measurements = data.get("measurements", [])
        if isinstance(raw_measurements, (list, tuple)):
            for raw in raw_measurements:
                measurement = Measurement.from_dict(raw)
                if measurement is not None:
                    measurements.append(measurement)
        return cls(
            id=int(data.get("id", 0)),
            name=str(data.get("name", "Sketch")),
            points=points,
            plane=normalize_plane(data.get("plane", "XY")),
            plane_label=plane_label,
            plane_origin=plane_origin,
            plane_u=plane_u,
            plane_v=plane_v,
            plane_normal=plane_normal,
            line_type=line_type,
            edges=edges,
            edge_constraints=constraints[:len(edges)],
            circles=circles,
            measurements=measurements,
        )

    @staticmethod
    def _valid_profile(raw: Any, point_count: int) -> List[int]:
        if not isinstance(raw, (list, tuple)):
            return []
        profile: List[int] = []
        for item in raw:
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if (
                0 <= index < point_count
                and index not in profile
            ):
                profile.append(index)
        return profile

    @classmethod
    def _add_loop_edges(
        cls, edges: List[Tuple[int, int]], profile: List[int]
    ) -> None:
        if len(profile) < 2:
            return
        pairs = list(zip(profile, profile[1:]))
        if len(profile) >= 3:
            pairs.append((profile[-1], profile[0]))
        for start, end in pairs:
            cls._add_edge(edges, start, end)

    @staticmethod
    def _add_edge(
        edges: List[Tuple[int, int]], start: int, end: int
    ) -> None:
        if start == end:
            return
        key = (min(start, end), max(start, end))
        if any(
            (min(a, b), max(a, b)) == key for a, b in edges
        ):
            return
        edges.append((start, end))

    @staticmethod
    def _find_or_add_point(points: List[Point], point: Point) -> int:
        for index, existing in enumerate(points):
            if existing == point:
                return index
        points.append(point2d(point))
        return len(points) - 1


@dataclass
class Fillet:
    """A rounded solid edge stored in the sketch's local 2D coordinates.

    ``kind`` is ``"vertical"`` for a corner of the extruded profile,
    ``"top"`` or ``"bottom"`` for an edge of the matching cap.  ``(u, v)``
    is the profile corner for a vertical fillet and the midpoint of the
    profile segment for a cap fillet.
    """

    kind: str = "vertical"
    u: float = 0.0
    v: float = 0.0
    radius: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "u": self.u,
            "v": self.v,
            "radius": self.radius,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Fillet"]:
        if isinstance(data, dict):
            kind = str(data.get("kind", "vertical"))
            try:
                u = float(data.get("u", 0.0))
                v = float(data.get("v", 0.0))
                radius = float(data.get("radius", 0.0))
            except (TypeError, ValueError):
                return None
        elif isinstance(data, (list, tuple)) and len(data) >= 3:
            # Version 1 stored only vertical fillets as [u, v, radius].
            kind = "vertical"
            try:
                u = float(data[0])
                v = float(data[1])
                radius = float(data[2])
            except (TypeError, ValueError):
                return None
        else:
            return None
        if kind not in ("vertical", "top", "bottom"):
            kind = "vertical"
        if radius <= 0.0:
            return None
        return cls(kind, u, v, radius)


@dataclass
class ExtrudeSlice:
    """One constant cross-section interval of a combined solid body."""

    z0: float
    z1: float
    # Each region is ``[outer, *holes]`` in the owning sketch's local XY.
    regions: List[List[List[float]]] = field(default_factory=list)
    # True where this slice continues a sampled curved surface instead of
    # ending on a real cap.  The renderer keeps those interfaces seam-free.
    smooth_z0: bool = False
    smooth_z1: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "z0": self.z0,
            "z1": self.z1,
            "regions": [
                [
                    [[float(x), float(y)] for x, y in loop]
                    for loop in region
                ]
                for region in self.regions
            ],
        }
        if self.smooth_z0:
            data["smooth_z0"] = True
        if self.smooth_z1:
            data["smooth_z1"] = True
        return data

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ExtrudeSlice"]:
        if not isinstance(data, dict):
            return None
        try:
            z0 = float(data.get("z0", 0.0))
            z1 = float(data.get("z1", 0.0))
        except (TypeError, ValueError):
            return None
        regions: List[List[List[float]]] = []
        for raw_region in data.get("regions", []):
            if not isinstance(raw_region, (list, tuple)):
                continue
            region: List[List[float]] = []
            for raw_loop in raw_region:
                loop: List[List[float]] = []
                for point in raw_loop if isinstance(raw_loop, (list, tuple)) else []:
                    if not isinstance(point, (list, tuple)) or len(point) < 2:
                        loop = []
                        break
                    try:
                        loop.append([float(point[0]), float(point[1])])
                    except (TypeError, ValueError):
                        loop = []
                        break
                if len(loop) >= 3:
                    region.append(loop)
            if region:
                regions.append(region)
        if not regions or abs(z1 - z0) <= 1e-9:
            return None
        if z1 < z0:
            z0, z1 = z1, z0
        return cls(
            z0, z1, regions,
            bool(data.get("smooth_z0", False)),
            bool(data.get("smooth_z1", False)),
        )


@dataclass
class Extrude:
    """A prism created by extruding closed sketch faces along its normal."""

    id: int
    name: str
    sketch_id: int
    height: float = 20.0
    profiles: List[List[int]] = field(default_factory=list)
    cuts: List[List[int]] = field(default_factory=list)
    # Each region is a list of loops whose intersection is extruded.  This
    # represents arrangement regions such as the lens where a circle crosses
    # a rectangle, which cannot be stored as a single sketch loop.
    regions: List[List[List[int]]] = field(default_factory=list)
    # Rounded profile corners and cap edges.
    fillets: List[Fillet] = field(default_factory=list)
    # Offset of the base cap from the sketch plane along the normal.
    start: float = 0.0
    # Boolean operation that created or last modified this body.
    operation: str = "new_body"
    # A combined body stores its finished z-slices instead of one prism.
    slices: List[ExtrudeSlice] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "extrude",
            "name": self.name,
            "sketch": self.sketch_id,
            "height": self.height,
            "start": self.start,
            "operation": self.operation,
            "profiles": [list(loop) for loop in self.profiles],
            "cuts": [list(loop) for loop in self.cuts],
            "regions": [
                [list(loop) for loop in region] for region in self.regions
            ],
            "fillets": [fillet.to_dict() for fillet in self.fillets],
            "slices": [entry.to_dict() for entry in self.slices],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Extrude":
        return cls(
            id=int(data.get("id", 0)),
            name=str(data.get("name", "Extrude")),
            sketch_id=int(data.get("sketch", 0)),
            height=float(data.get("height", 20.0)),
            profiles=cls._parse_loops(data.get("profiles", [])),
            cuts=cls._parse_loops(data.get("cuts", [])),
            regions=cls._parse_regions(data.get("regions", [])),
            fillets=cls._parse_fillets(data.get("fillets", [])),
            start=float(data.get("start", 0.0)),
            operation=str(data.get("operation", "new_body")),
            slices=cls._parse_slices(data.get("slices", [])),
        )

    @staticmethod
    def _parse_slices(raw_slices: Any) -> List[ExtrudeSlice]:
        slices: List[ExtrudeSlice] = []
        if not isinstance(raw_slices, (list, tuple)):
            return slices
        for raw_slice in raw_slices:
            entry = ExtrudeSlice.from_dict(raw_slice)
            if entry is not None:
                slices.append(entry)
        return slices

    @staticmethod
    def _parse_fillets(raw_fillets: Any) -> List[Fillet]:
        fillets: List[Fillet] = []
        if not isinstance(raw_fillets, (list, tuple)):
            return fillets
        for raw_fillet in raw_fillets:
            fillet = Fillet.from_dict(raw_fillet)
            if fillet is not None:
                fillets.append(fillet)
        return fillets

    @classmethod
    def _parse_regions(cls, raw_regions: Any) -> List[List[List[int]]]:
        regions: List[List[List[int]]] = []
        if not isinstance(raw_regions, (list, tuple)):
            return regions
        for raw_region in raw_regions:
            if not isinstance(raw_region, (list, tuple)):
                continue
            region = cls._parse_loops(raw_region)
            if region:
                regions.append(region)
        return regions

    @staticmethod
    def _parse_loops(raw_profiles: Any) -> List[List[int]]:
        profiles: List[List[int]] = []
        if not isinstance(raw_profiles, (list, tuple)):
            return profiles
        for raw_loop in raw_profiles:
            if not isinstance(raw_loop, (list, tuple)):
                continue
            loop: List[int] = []
            for value in raw_loop:
                try:
                    loop.append(int(value))
                except (TypeError, ValueError):
                    loop = []
                    break
            if loop:
                profiles.append(loop)
        return profiles

    def resolve_profiles(self, sketch: Sketch) -> List[List[Point]]:
        """Return the selected profiles as polygons, including circles."""
        loops: List[List[Point]] = []
        for profile in self.profiles:
            points = sketch.loop_points(profile)
            if len(points) >= 3:
                loops.append(points)
        for region in self.regions:
            polygons: List[List[Point]] = []
            for loop in region:
                points = sketch.loop_points(loop)
                if len(points) >= 3:
                    polygons.append(points)
            if polygons:
                loops.extend(intersect_loops(polygons))
        if loops or self.profiles or self.regions:
            return loops
        fallback = sketch.profile_points()
        return [fallback] if len(fallback) >= 3 else []

    def resolve_cuts(self, sketch: Sketch) -> List[List[Point]]:
        """Return the overlapping profiles that cut the selected material."""
        loops: List[List[Point]] = []
        for cut in self.cuts:
            points = sketch.loop_points(cut)
            if len(points) >= 3:
                loops.append(points)
        return loops
