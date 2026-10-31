"""Sketch and feature models for PY3DCAD."""

import math
from dataclasses import dataclass, field
from typing import (
    Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple,
    Union, TYPE_CHECKING,
)

from .profiles import intersect_loops, polygon_area
from .solver.objects import circle2d, line2d, point2d

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import Document

Point = point2d
Line = line2d
Circle = circle2d
Point3 = Tuple[float, float, float]

EDGE_CONSTRAINTS = ("horizontal", "vertical")
MEASUREMENT_KINDS = ("distance", "angle", "diameter")
MEASUREMENT_REF_KINDS = ("point", "line", "circle")
COINCIDENT_REF_KINDS = ("point", "origin")
EQUAL_REF_KINDS = ("line", "circle")
CIRCLE_SEGMENTS = 48


def _rank_and_fixed_columns(
    rows: Sequence[Sequence[float]], columns: int
) -> Tuple[int, Set[int]]:
    """Return a Jacobian's rank and the columns whose removal lowers it.

    A variable column has no remaining degree of freedom ("is fixed") when
    deleting it drops the rank by one.  Over the reals that holds exactly for
    pivot columns whose reduced row-echelon row is a unit vector, so a single
    Gauss-Jordan reduction answers the whole query instead of re-ranking the
    matrix once per column.
    """
    matrix = [
        list(row[:columns])
        for row in rows
        if any(abs(value) > 1e-9 for value in row)
    ]
    pivot_columns: List[int] = []
    rank = 0
    for column in range(columns):
        pivot = next(
            (
                row for row in range(rank, len(matrix))
                if abs(matrix[row][column]) > 1e-8
            ),
            None,
        )
        if pivot is None:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        scale = matrix[rank][column]
        matrix[rank] = [value / scale for value in matrix[rank]]
        for row in range(len(matrix)):
            if row == rank:
                continue
            factor = matrix[row][column]
            if abs(factor) > 1e-8:
                matrix[row] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(matrix[row], matrix[rank])
                ]
        pivot_columns.append(column)
        rank += 1
        if rank == len(matrix):
            break
    free_columns = [
        column for column in range(columns)
        if column not in set(pivot_columns)
    ]
    fixed = {
        pivot
        for position, pivot in enumerate(pivot_columns)
        if all(
            abs(matrix[position][column]) <= 1e-8
            for column in free_columns
        )
    }
    return rank, fixed


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


def normalize_bulge(value: Any) -> Optional[float]:
    """Return a finite, meaningful bulge or ``None`` for a straight edge."""
    try:
        bulge = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(bulge) or abs(bulge) < 1e-12:
        return None
    return bulge


def bulge_arc_points(
    start: Point, end: Point, bulge: float,
    max_step: float = math.pi / 24.0,
) -> List[Point]:
    """Sample an exact circular bulge edge, including both endpoints.

    A bulge is ``tan(sweep / 4)``: positive runs counter-clockwise from
    ``start`` to ``end`` and negative runs clockwise.  The shape itself is
    stored by the two points and the bulge; sampling only feeds display,
    area and volume rebuilds.
    """
    first = point2d(start)
    second = point2d(end)
    chord = math.hypot(second[0] - first[0], second[1] - first[1])
    if chord <= 1e-12 or abs(bulge) <= 1e-12:
        return [first, second]
    sweep = 4.0 * math.atan(bulge)
    if abs(sweep) >= math.tau - 1e-9:
        return [first, second]
    mid_x = (first[0] + second[0]) * 0.5
    mid_y = (first[1] + second[1]) * 0.5
    dx = (second[0] - first[0]) / chord
    dy = (second[1] - first[1]) / chord
    offset = (chord * 0.5) / math.tan(sweep * 0.5)
    center_x = mid_x - dy * offset
    center_y = mid_y + dx * offset
    radius = chord / (2.0 * abs(math.sin(sweep * 0.5)))
    start_angle = math.atan2(first[1] - center_y, first[0] - center_x)
    steps = max(2, int(math.ceil(abs(sweep) / max_step)))
    points: List[Point] = [first]
    for step in range(1, steps):
        angle = start_angle + sweep * step / steps
        points.append(point2d((
            center_x + radius * math.cos(angle),
            center_y + radius * math.sin(angle),
        )))
    points.append(second)
    return points


def _first_positions(order: Sequence[int]) -> Dict[int, int]:
    """Map each index to the position of its first occurrence in ``order``."""
    positions: Dict[int, int] = {}
    for position, index in enumerate(order):
        positions.setdefault(index, position)
    return positions


def _pick_anchor(
    members: Sequence[int], *rankings: Dict[int, int]
) -> int:
    """Return the member earliest in the first ranking that contains any."""
    for rank in rankings:
        hits = [member for member in members if member in rank]
        if hits:
            return min(hits, key=rank.__getitem__)
    return members[0]


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


def normalize_coincident_ref(value: Any) -> Optional[Tuple[str, int]]:
    """Return a point or document-origin reference for a coincidence.

    The document origin is a world-space point rather than a sketch point,
    so it is stored as ``("origin", -1)`` and projected into the sketch
    plane whenever the constraint is solved.
    """
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    kind = str(value[0]).lower()
    if kind == "origin":
        return ("origin", -1)
    if kind not in COINCIDENT_REF_KINDS:
        return None
    try:
        index = int(value[1])
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    return kind, index


def normalize_equal_ref(value: Any) -> Optional[Tuple[str, int]]:
    """Return a line or circle reference for an equality constraint."""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    kind = str(value[0]).lower()
    if kind not in EQUAL_REF_KINDS:
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
    """A persistent distance, angle, or diameter annotation."""

    kind: str
    first: Tuple[str, int]
    second: Tuple[str, int]
    # User-controlled annotation placement.  Distance and diameter
    # measurements store a signed perpendicular offset from the measured
    # points; angle measurements store the arc radius.  None selects a
    # computed default for older documents.
    placement: Optional[float] = None
    # User-owned measurement value.  Distance and diameter values use
    # sketch units and angle values use degrees.  The engine sets this once
    # when the measurement is created and only the user may change it
    # afterwards.
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


@dataclass(frozen=True)
class Coincident:
    """A persistent coincidence between two points or a point and origin.

    ``first`` and ``second`` are ``("point", index)`` references or
    ``("origin", -1)`` for the document origin projected onto the sketch.
    The origin is never moved; a coincidence with it pins the other point.
    """

    first: Tuple[str, int]
    second: Tuple[str, int]

    def key(self) -> Tuple[object, ...]:
        """Return an order-independent identity for duplicate detection."""
        return tuple(sorted((self.first, self.second)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "first": [self.first[0], self.first[1]],
            "second": [self.second[0], self.second[1]],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Coincident"]:
        if not isinstance(data, dict):
            return None
        first = normalize_coincident_ref(data.get("first"))
        second = normalize_coincident_ref(data.get("second"))
        if first is None or second is None or first == second:
            return None
        if first[0] == "origin" and second[0] == "origin":
            return None
        return cls(first, second)


@dataclass(frozen=True)
class Equal:
    """Keep two lines the same length or two circles the same diameter.

    ``first`` and ``second`` are ``("line", edge index)`` or
    ``("circle", circle index)`` references.  Both references must be the
    same kind: equal length and equal diameter use different units, so a
    mixed pair is rejected by :meth:`Sketch._normalize_equals`.
    """

    first: Tuple[str, int]
    second: Tuple[str, int]

    def key(self) -> Tuple[object, ...]:
        """Return an order-independent identity for duplicate detection."""
        return tuple(sorted((self.first, self.second)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "first": [self.first[0], self.first[1]],
            "second": [self.second[0], self.second[1]],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Equal"]:
        if not isinstance(data, dict):
            return None
        first = normalize_equal_ref(data.get("first"))
        second = normalize_equal_ref(data.get("second"))
        if first is None or second is None or first == second:
            return None
        if first[0] != second[0]:
            return None
        return cls(first, second)


@dataclass(frozen=True)
class ProjectionSource:
    """Where a projected sketch entity comes from on the solid.

    The source keeps the feature, the position in that feature's sketch
    frame (``u``/``v``), and how far along the body height it sits
    (``z_fraction``).  When the feature's sketch or height changes, the
    projected entity is rebuilt from these values.  ``bind`` optionally ties
    a coordinate to a live sketch point, edge or circle so moving the source
    profile moves the projection with it.
    """

    feature_id: int
    u: float
    v: float
    z_fraction: float
    bind: str = "world"
    index: int = -1
    t: float = 0.0

    def key(self) -> Tuple[object, ...]:
        """Return a stable identity for sharing endpoints between edges."""
        return (
            self.feature_id,
            round(self.u, 6),
            round(self.v, 6),
            round(self.z_fraction, 6),
            self.bind,
            self.index,
            round(self.t, 6),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature_id,
            "u": self.u,
            "v": self.v,
            "z": self.z_fraction,
            "bind": self.bind,
            "index": self.index,
            "t": self.t,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ProjectionSource"]:
        if not isinstance(data, dict):
            return None
        try:
            feature_id = int(data.get("feature", -1))
            u = float(data.get("u", 0.0))
            v = float(data.get("v", 0.0))
            z_fraction = float(data.get("z", 0.0))
            index = int(data.get("index", -1))
            t = float(data.get("t", 0.0))
        except (TypeError, ValueError):
            return None
        if not all(
            math.isfinite(value) for value in (u, v, z_fraction, t)
        ):
            return None
        bind = str(data.get("bind", "world"))
        if bind not in ("world", "point", "edge", "circle"):
            bind = "world"
        return cls(
            feature_id,
            u,
            v,
            min(1.0, max(0.0, z_fraction)),
            bind,
            index,
            t,
        )


@dataclass(frozen=True)
class ProjectedPoint:
    """A sketch point whose position follows one solid vertex."""

    point: int
    source: ProjectionSource

    def to_dict(self) -> Dict[str, Any]:
        return {"point": self.point, "source": self.source.to_dict()}

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ProjectedPoint"]:
        if not isinstance(data, dict):
            return None
        try:
            point = int(data.get("point", -1))
        except (TypeError, ValueError):
            return None
        source = ProjectionSource.from_dict(data.get("source"))
        if point < 0 or source is None:
            return None
        return cls(point, source)


@dataclass(frozen=True)
class ProjectedEdge:
    """A sketch edge whose endpoints follow a solid edge.

    ``bulge`` keeps circular fillet edges exact: the two endpoint sources
    define a real arc instead of a run of tessellation chords.
    """

    edge: int
    feature_id: int
    start: ProjectionSource
    end: ProjectionSource
    bulge: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge": self.edge,
            "feature": self.feature_id,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "bulge": self.bulge,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ProjectedEdge"]:
        if not isinstance(data, dict):
            return None
        try:
            edge = int(data.get("edge", -1))
            feature_id = int(data.get("feature", -1))
        except (TypeError, ValueError):
            return None
        start = ProjectionSource.from_dict(data.get("start"))
        end = ProjectionSource.from_dict(data.get("end"))
        if edge < 0 or feature_id < 0 or start is None or end is None:
            return None
        return cls(
            edge, feature_id, start, end,
            normalize_bulge(data.get("bulge")),
        )


@dataclass(frozen=True)
class ProjectedCircle:
    """A sketch circle whose centre and radius follow a solid circle."""

    circle: int
    center: ProjectionSource
    source_circle: int = -1
    radius: float = 0.0

    def key(self) -> Tuple[object, ...]:
        """Return a stable identity for repeated projections."""
        return (
            self.center.key(),
            self.source_circle,
            round(self.radius, 6),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "circle": self.circle,
            "center": self.center.to_dict(),
            "source_circle": self.source_circle,
            "radius": self.radius,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ProjectedCircle"]:
        if not isinstance(data, dict):
            return None
        try:
            circle = int(data.get("circle", -1))
            source_circle = int(data.get("source_circle", -1))
            radius = float(data.get("radius", 0.0))
        except (TypeError, ValueError):
            return None
        center = ProjectionSource.from_dict(data.get("center"))
        if (
            circle < 0 or center is None
            or not math.isfinite(radius) or radius < 0.0
        ):
            return None
        return cls(circle, center, source_circle, radius)


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
    # Visibility is a document setting, so a sketch can stay in the tree
    # after it has been consumed by a feature without cluttering the view.
    visible: bool = True
    edges: List[Tuple[int, int]] = field(default_factory=list)
    edge_constraints: List[Optional[str]] = field(default_factory=list)
    # A bulge is tan(sweep / 4) for an exact circular arc.  Straight edges
    # keep ``None`` so ordinary lines stay plain two-point shapes.
    edge_bulges: List[Optional[float]] = field(default_factory=list)
    circles: List[Circle] = field(default_factory=list)
    measurements: List[Measurement] = field(default_factory=list)
    coincidences: List[Coincident] = field(default_factory=list)
    equals: List[Equal] = field(default_factory=list)
    # Projected entities are ordinary points and edges that also remember
    # the solid vertex/edge they came from.  ``refresh_projections`` moves
    # them whenever the source geometry changes.
    projected_points: List[ProjectedPoint] = field(default_factory=list)
    projected_edges: List[ProjectedEdge] = field(default_factory=list)
    projected_circles: List[ProjectedCircle] = field(default_factory=list)
    # Memoised degree-of-freedom analysis.  The renderer asks for this on
    # every frame, so it is cached against a geometry/constraint signature and
    # only recomputed when the sketch actually changes.
    _dof_signature: Optional[Tuple[object, ...]] = field(
        default=None, init=False, repr=False, compare=False
    )
    _dof_cache: Optional[Tuple[Set[int], Set[int], Set[int]]] = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self.points = [point2d(point) for point in self.points]
        self.visible = bool(self.visible)
        circles = [
            circle
            for circle in (
                self._normalize_circle(item) for item in self.circles
            )
            if circle is not None
        ]
        self.circles = []
        raw_bulges = list(self.edge_bulges)
        edges: List[Tuple[int, int]] = []
        bulges: List[Optional[float]] = []
        for index, (start, end) in enumerate(self.edges):
            if not (
                0 <= start < len(self.points)
                and 0 <= end < len(self.points)
                and start != end
            ):
                continue
            edges.append((start, end))
            bulges.append(
                raw_bulges[index] if index < len(raw_bulges) else None
            )
        self.edges = edges
        self.edge_bulges = [normalize_bulge(value) for value in bulges]
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
                if ref_kind == "point":
                    limit = len(self.points)
                elif ref_kind == "line":
                    limit = len(self.edges)
                else:
                    limit = len(circles)
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
        # Bind circles first so their midpoints exist as regular points
        # before measurement and coincidence enforcement runs.
        self.circles = self._bind_circles(circles)
        # Older documents did not store a measurement value.  Freeze one
        # from the current geometry exactly once so the engine never
        # overwrites a measurement afterwards.  This runs after binding so
        # diameter measurements can read the rebuilt circle list.
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
        self.coincidences = self._normalize_coincidences(
            self.coincidences
        )
        self.equals = self._normalize_equals(self.equals)
        self.projected_points = [
            link
            for link in (
                item if isinstance(item, ProjectedPoint)
                else ProjectedPoint.from_dict(item)
                for item in self.projected_points
            )
            if link is not None and 0 <= link.point < len(self.points)
        ]
        self.projected_edges = [
            link
            for link in (
                item if isinstance(item, ProjectedEdge)
                else ProjectedEdge.from_dict(item)
                for item in self.projected_edges
            )
            if link is not None and 0 <= link.edge < len(self.edges)
        ]
        self.projected_circles = [
            link
            for link in (
                item if isinstance(item, ProjectedCircle)
                else ProjectedCircle.from_dict(item)
                for item in self.projected_circles
            )
            if link is not None and 0 <= link.circle < len(self.circles)
        ]
        # A loaded sketch may predate dimension enforcement.  Make its
        # stored values authoritative immediately, without a command.
        self.enforce_measurements(self.points)

    def _normalize_coincidences(
        self, items: Iterable[Any]
    ) -> List[Coincident]:
        """Keep only valid, distinct coincidence constraints."""
        result: List[Coincident] = []
        seen: set = set()
        for item in items:
            coincidence = (
                item if isinstance(item, Coincident)
                else Coincident.from_dict(item)
            )
            if coincidence is None:
                continue
            refs_valid = True
            for kind, index in (
                coincidence.first, coincidence.second
            ):
                if kind == "point" and not 0 <= index < len(self.points):
                    refs_valid = False
                    break
            if not refs_valid:
                continue
            key = coincidence.key()
            if key in seen:
                continue
            seen.add(key)
            result.append(coincidence)
        return result

    def _normalize_equals(self, items: Iterable[Any]) -> List[Equal]:
        """Keep only valid, distinct equality constraints."""
        result: List[Equal] = []
        seen: set = set()
        for item in items:
            equal = item if isinstance(item, Equal) else Equal.from_dict(item)
            if equal is None:
                continue
            first, second = equal.first, equal.second
            if first[0] != second[0]:
                continue
            limit = (
                len(self.edges) if first[0] == "line"
                else len(self.circles)
            )
            if not (
                0 <= first[1] < limit and 0 <= second[1] < limit
            ):
                continue
            key = equal.key()
            if key in seen:
                continue
            seen.add(key)
            result.append(equal)
        return result

    def _bind_circles(self, circles: Iterable[Circle]) -> List[Circle]:
        """Make each circle midpoint a regular point of the sketch.

        Each circle gets its own point, even when several circles share a
        centre, so every circle loop can be identified by its point index.
        """
        bound: List[Circle] = []
        used: set = set()
        by_identity: Dict[int, List[int]] = {}
        for candidate, existing in enumerate(self.points):
            by_identity.setdefault(id(existing), []).append(candidate)
        for circle in circles:
            index: Optional[int] = next(
                (
                    candidate
                    for candidate in by_identity.get(id(circle.midPoint), ())
                    if candidate not in used
                ),
                None,
            )
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
    def parallel_segment_distance(
        first_start: Point,
        first_end: Point,
        second_start: Point,
        second_end: Point,
    ) -> Optional[Tuple[float, Point, Point]]:
        """Return the perpendicular distance between two parallel segments.

        The measured points are placed on a perpendicular through the
        middle of the first segment, so the annotation shows the true gap
        between the lines even when their spans do not overlap.
        """
        first_dx = first_end[0] - first_start[0]
        first_dy = first_end[1] - first_start[1]
        second_dx = second_end[0] - second_start[0]
        second_dy = second_end[1] - second_start[1]
        first_length = math.hypot(first_dx, first_dy)
        second_length = math.hypot(second_dx, second_dy)
        if first_length <= 1e-9 or second_length <= 1e-9:
            return None
        cross = abs(
            first_dx * second_dy - first_dy * second_dx
        ) / (first_length * second_length)
        if cross > 1e-7:
            return None
        normal_x = -first_dy / first_length
        normal_y = first_dx / first_length
        signed = (
            (second_start[0] - first_start[0]) * normal_x
            + (second_start[1] - first_start[1]) * normal_y
        )
        if abs(signed) <= 1e-9:
            # Collinear segments have no gap to measure; the caller falls
            # back to the closest-point distance so disjoint spans still
            # report the real separation.
            return None
        middle_x = (first_start[0] + first_end[0]) * 0.5
        middle_y = (first_start[1] + first_end[1]) * 0.5
        first_point = point2d((middle_x, middle_y))
        second_point = point2d((
            middle_x + normal_x * signed,
            middle_y + normal_y * signed,
        ))
        return abs(signed), first_point, second_point

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
        # Parallel lines have no meaningful angle.  Treating them as an
        # angle measurement would freeze a 0 or 180 degree value and make
        # the distance tool pick the wrong kind for collinear edges.
        cross = abs(
            first_x * second_y - first_y * second_x
        ) / (first_length * second_length)
        if cross <= 1e-7:
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
        if first[0] == "line" and second[0] == "line":
            parallel = self.parallel_segment_distance(
                first_points[0], first_points[1],
                second_points[0], second_points[1],
            )
            if parallel is not None:
                return parallel
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

    def diameter_geometry(
        self,
        ref: Tuple[str, int],
        points: Optional[List[Point]] = None,
    ) -> Optional[Tuple[float, Point, Point]]:
        """Return a circle's diameter and the two ends of that diameter."""
        if ref[0] != "circle" or not 0 <= ref[1] < len(self.circles):
            return None
        circle = self.circles[ref[1]]
        if not math.isfinite(circle.diameter) or circle.diameter <= 0.0:
            return None
        center: Point = circle.midPoint
        if points is not None:
            center_index = self.point_index(circle.midPoint)
            if center_index is not None and center_index < len(points):
                center = points[center_index]
        radius = circle.diameter / 2.0
        return (
            circle.diameter,
            point2d((center[0] - radius, center[1])),
            point2d((center[0] + radius, center[1])),
        )

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
        elif kind == "diameter":
            geometry = self.diameter_geometry(first, points)
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

    def edge_length(
        self, index: int, points: Optional[List[Point]] = None
    ) -> Optional[float]:
        """Return an edge's length, or None when the edge is invalid."""
        if not 0 <= index < len(self.edges):
            return None
        source = self.points if points is None else points
        start, end = self.edges[index]
        if not (
            0 <= start < len(source) and 0 <= end < len(source)
        ):
            return None
        delta_x = source[end][0] - source[start][0]
        delta_y = source[end][1] - source[start][1]
        return math.hypot(delta_x, delta_y)

    def equal_value(
        self, ref: Tuple[str, int], points: Optional[List[Point]] = None
    ) -> Optional[float]:
        """Return the length or diameter an equality reference measures."""
        if ref[0] == "line":
            return self.edge_length(ref[1], points)
        if ref[0] == "circle" and 0 <= ref[1] < len(self.circles):
            return self.circles[ref[1]].diameter
        return None

    def equal_residual(
        self, equal: Equal, points: List[Point]
    ) -> Optional[float]:
        """Return first minus second for one equality constraint."""
        first = self.equal_value(equal.first, points)
        second = self.equal_value(equal.second, points)
        if first is None or second is None:
            return None
        return first - second

    def equal_max_error(self, points: List[Point]) -> float:
        """Return the largest absolute equality residual."""
        maximum = 0.0
        for equal in self.equals:
            residual = self.equal_residual(equal, points)
            if residual is not None:
                maximum = max(maximum, abs(residual))
        return maximum

    def constraint_max_error(self, points: List[Point]) -> float:
        """Return the largest residual across measurements and equalities."""
        return max(
            self.measurement_max_error(points),
            self.equal_max_error(points),
        )

    def _equal_fixed_refs(
        self, fixed_points: Optional[Set[int]] = None
    ) -> Set[Tuple[str, int]]:
        """Return references whose size cannot be changed by the solver.

        Projected lines and circles follow the solid.  A line whose two
        endpoints are both projected is equally fixed even without an edge
        projection link.
        """
        if fixed_points is None:
            fixed_points = self.projected_point_indices()
        fixed: Set[Tuple[str, int]] = {
            ("line", link.edge) for link in self.projected_edges
            if 0 <= link.edge < len(self.edges)
        }
        fixed.update(
            ("circle", link.circle) for link in self.projected_circles
            if 0 <= link.circle < len(self.circles)
        )
        # A diameter measurement owns its circle's size just like a
        # projection does; equality must treat it as the fixed side.
        fixed.update(
            ("circle", measurement.first[1])
            for measurement in self.measurements
            if (
                measurement.kind == "diameter"
                and measurement.value is not None
                and measurement.first[0] == "circle"
                and 0 <= measurement.first[1] < len(self.circles)
            )
        )
        for index, (start, end) in enumerate(self.edges):
            if (
                start in fixed_points
                and end in fixed_points
                and ("line", index) not in fixed
            ):
                fixed.add(("line", index))
        # A point-to-point distance between an edge's endpoints fixes its
        # length, so equality must use that length as the target instead of
        # averaging it away.
        measured_pairs = {
            frozenset((measurement.first[1], measurement.second[1]))
            for measurement in self.measurements
            if (
                measurement.kind == "distance"
                and measurement.value is not None
                and measurement.first[0] == "point"
                and measurement.second[0] == "point"
                and measurement.first[1] != measurement.second[1]
            )
        }
        if measured_pairs:
            fixed.update(
                ("line", index)
                for index, (start, end) in enumerate(self.edges)
                if frozenset((start, end)) in measured_pairs
            )
        return fixed

    def _project_equals(self, points: List[Point]) -> bool:
        """Move geometry so every equality constraint holds.

        Lines are adjusted symmetrically along their own direction; circles
        are resized directly.  Projected references stay put and donate the
        whole correction to the free side.  The work is linear in the number
        of equality constraints and allocates only one offset map per pass.
        """
        if not self.equals:
            return False
        fixed_points = self.projected_point_indices()
        fixed = self._equal_fixed_refs(fixed_points)
        changed = self._project_equal_circles(fixed)
        if self._project_equal_lines(points, fixed, fixed_points):
            changed = True
        return changed

    @staticmethod
    def _equal_target(
        first_value: float,
        second_value: float,
        first_fixed: bool,
        second_fixed: bool,
    ) -> float:
        """Return the size both equal references should adopt."""
        if first_fixed:
            return first_value
        if second_fixed:
            return second_value
        return (first_value + second_value) * 0.5

    def _project_equal_circles(
        self, fixed: Set[Tuple[str, int]]
    ) -> bool:
        """Resize free circles until their equality pairs match."""
        targets: Dict[int, float] = {}
        changed = False
        for equal in self.equals:
            if equal.first[0] != "circle" or equal.second[0] != "circle":
                continue
            first, second = equal.first[1], equal.second[1]
            if not (
                0 <= first < len(self.circles)
                and 0 <= second < len(self.circles)
            ):
                continue
            first_fixed = ("circle", first) in fixed
            second_fixed = ("circle", second) in fixed
            if first_fixed and second_fixed:
                continue
            first_value = self.circles[first].diameter
            second_value = self.circles[second].diameter
            target = self._equal_target(
                first_value, second_value, first_fixed, second_fixed
            )
            if target <= 1e-12:
                continue
            if (
                not first_fixed
                and abs(first_value - target) > 1e-9
            ):
                targets[first] = target
                changed = True
            if (
                not second_fixed
                and abs(second_value - target) > 1e-9
            ):
                targets[second] = target
                changed = True
        for index, target in targets.items():
            self.circles[index].change_diameter(target)
        return changed

    def _project_equal_lines(
        self,
        points: List[Point],
        fixed: Set[Tuple[str, int]],
        fixed_points: Set[int],
    ) -> bool:
        """Move line endpoints until their equality pairs match."""
        offsets: Dict[int, Tuple[float, float]] = {}
        changed = False
        for equal in self.equals:
            if equal.first[0] != "line" or equal.second[0] != "line":
                continue
            first, second = equal.first[1], equal.second[1]
            first_value = self.edge_length(first, points)
            second_value = self.edge_length(second, points)
            if first_value is None or second_value is None:
                continue
            first_fixed = ("line", first) in fixed
            second_fixed = ("line", second) in fixed
            if first_fixed and second_fixed:
                continue
            target = self._equal_target(
                first_value, second_value, first_fixed, second_fixed
            )
            if target <= 1e-12:
                continue
            if (
                not first_fixed
                and abs(first_value - target) > 1e-9
                and self._offset_edge_length(
                    offsets, points, first, target - first_value,
                    fixed_points,
                )
            ):
                changed = True
            if (
                not second_fixed
                and abs(second_value - target) > 1e-9
                and self._offset_edge_length(
                    offsets, points, second, target - second_value,
                    fixed_points,
                )
            ):
                changed = True
        if offsets:
            self._apply_point_offsets(points, offsets)
        return changed

    def _offset_edge_length(
        self,
        offsets: Dict[int, Tuple[float, float]],
        points: List[Point],
        index: int,
        delta: float,
        fixed: Set[int],
    ) -> bool:
        """Add the endpoint offsets that change an edge length by ``delta``."""
        if not 0 <= index < len(self.edges):
            return False
        start, end = self.edges[index]
        if not (
            0 <= start < len(points) and 0 <= end < len(points)
        ):
            return False
        delta_x = points[end][0] - points[start][0]
        delta_y = points[end][1] - points[start][1]
        length = math.hypot(delta_x, delta_y)
        if length <= 1e-12 or abs(delta) <= 1e-12:
            return False
        direction_x = delta_x / length
        direction_y = delta_y / length
        start_fixed = start in fixed
        end_fixed = end in fixed
        if start_fixed and end_fixed:
            return False
        if start_fixed:
            self._add_offsets(
                offsets, [end],
                direction_x * delta, direction_y * delta,
            )
        elif end_fixed:
            self._add_offsets(
                offsets, [start],
                -direction_x * delta, -direction_y * delta,
            )
        else:
            half = delta * 0.5
            self._add_offsets(
                offsets, [start],
                -direction_x * half, -direction_y * half,
            )
            self._add_offsets(
                offsets, [end],
                direction_x * half, direction_y * half,
            )
        return True

    def _apply_diameter_measurements(self) -> None:
        """Resize circles to their stored diameter measurement values.

        Circles are not made of movable sketch points, so their diameter is
        enforced directly instead of through the point projection loop.
        """
        for measurement in self.measurements:
            if measurement.kind != "diameter":
                continue
            if measurement.value is None:
                continue
            ref = measurement.first
            if ref[0] != "circle" or not 0 <= ref[1] < len(self.circles):
                continue
            if measurement.value <= 0.0:
                continue
            self.circles[ref[1]].change_diameter(measurement.value)

    def enforce_measurements(
        self,
        points: List[Point],
        iterations: int = 48,
        tolerance: float = 1e-6,
    ) -> bool:
        """Project points until measurements and equalities are satisfied."""
        if len(points) != len(self.points):
            return True
        has_equals = bool(self.equals)
        # Coincidences and equalities are hard constraints and must hold
        # even when a sketch has no measurements at all (for example right
        # after load).
        if self.coincidences or has_equals:
            self.constrain_axis_changes(points, range(len(points)))
        if not self.measurements and not has_equals:
            return True
        self._apply_diameter_measurements()
        # The projection helpers replace point objects.  Keep the caller's
        # originals alive so circles and other references stay bound to the
        # same point instances, then copy the final positions back into them.
        originals = list(points)
        try:
            for _ in range(max(1, iterations)):
                projected = False
                before_projection = list(points)
                # If no constraint moves a point in this pass, every residual
                # was taken from the unchanged points, so ``worst`` is exact.
                worst = 0.0
                for measurement in self.measurements:
                    residual = self.measurement_residual(
                        measurement, points
                    )
                    if residual is not None:
                        worst = max(worst, abs(residual))
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
                if has_equals:
                    projected = self._project_equals(points) or projected
                    worst = max(worst, self.equal_max_error(points))
                if not projected:
                    return worst <= tolerance
                # A projection may move only part of an axis-constrained
                # edge.  Snap the other endpoints by translating the whole
                # group by the correction instead of anchoring it to an
                # arbitrary first point, which would undo the projection.
                self.constrain_axis_changes(
                    points,
                    range(len(points)),
                    previous=before_projection,
                )
                if self.constraint_max_error(points) <= tolerance:
                    return True
            return self.constraint_max_error(points) <= tolerance
        finally:
            for index, original in enumerate(originals):
                original.set_pos(points[index])
                points[index] = original

    def coincident_anchor(self, index: int) -> Optional[int]:
        """Return the point that anchors ``index`` in a coincidence, if any.

        A coincidence is directed: its first reference is the anchor and the
        second reference follows it.  When ``index`` is the follower of a
        point/point coincidence this returns the anchor's index so callers can
        keep the anchor fixed while the follower snaps onto it.  Coincidences
        with the document origin are handled by the origin pinning rules, so
        they return ``None`` here.
        """
        for coincidence in self.coincidences:
            first, second = coincidence.first, coincidence.second
            if (
                second[0] == "point"
                and second[1] == index
                and first[0] == "point"
                and 0 <= first[1] < len(self.points)
            ):
                return first[1]
        return None

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
        # Projected points follow the solid and cannot be moved to satisfy a
        # measurement.  Drop them so the free side takes the whole correction.
        fixed = self.projected_point_indices()
        first_group = [
            index for index in first_group if index not in fixed
        ]
        second_group = [
            index for index in second_group if index not in fixed
        ]
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
        # A projected far point is fixed by the solid.  Rotate the free ray
        # by the whole correction instead of sharing it between both rays.
        fixed = self.projected_point_indices()
        first_movable = first_far not in fixed
        second_movable = second_far not in fixed
        if not first_movable and not second_movable:
            return False
        if first_movable and second_movable:
            first_angle, second_angle = -half, half
        elif first_movable:
            first_angle, second_angle = -2.0 * half, 0.0
        else:
            first_angle, second_angle = 0.0, 2.0 * half
        first_rotated = self._rotate_vector(
            first_x, first_y, first_angle
        )
        second_rotated = self._rotate_vector(
            second_x, second_y, second_angle
        )
        if first_movable:
            points[first_far] = point2d((
                vertex[0] + first_rotated[0],
                vertex[1] + first_rotated[1],
            ))
        if second_movable:
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

    def _add_length_derivative(
        self, equation: List[float], edge_index: int, scale: float
    ) -> bool:
        """Add the exact length derivative of one edge to a Jacobian row."""
        if not 0 <= edge_index < len(self.edges):
            return False
        start, end = self.edges[edge_index]
        if not (
            0 <= start < len(self.points)
            and 0 <= end < len(self.points)
        ):
            return False
        delta_x = self.points[end][0] - self.points[start][0]
        delta_y = self.points[end][1] - self.points[start][1]
        length = math.hypot(delta_x, delta_y)
        if length <= 1e-12:
            return False
        unit_x = scale * delta_x / length
        unit_y = scale * delta_y / length
        equation[start * 2] -= unit_x
        equation[start * 2 + 1] -= unit_y
        equation[end * 2] += unit_x
        equation[end * 2 + 1] += unit_y
        return True

    def constraint_signature(self) -> Tuple[object, ...]:
        """Return a hashable snapshot of everything the DOF analysis reads."""
        return (
            self.geometry_signature(),
            tuple(self.edge_constraints),
            tuple(
                (coincidence.first, coincidence.second)
                for coincidence in self.coincidences
            ),
            tuple(
                (equal.first, equal.second) for equal in self.equals
            ),
            tuple(
                (m.kind, m.first, m.second, m.value)
                for m in self.measurements
            ),
            tuple(sorted(self.projected_point_indices())),
            tuple(sorted(link.edge for link in self.projected_edges)),
            tuple(sorted(link.circle for link in self.projected_circles)),
        )

    def constrained_entities(self) -> Tuple[Set[int], Set[int], Set[int]]:
        """Return point, edge and circle indices with no free DOF left.

        The result is memoised against :meth:`constraint_signature` because
        the viewport asks for it on every frame while the sketch is unchanged.
        """
        signature = self.constraint_signature()
        if self._dof_signature == signature and self._dof_cache is not None:
            return self._dof_cache
        result = self._compute_constrained_entities()
        self._dof_signature = signature
        self._dof_cache = result
        return result

    def _compute_constrained_entities(
        self,
    ) -> Tuple[Set[int], Set[int], Set[int]]:
        """Classify fixed entities from the linearised constraint equations.

        A coordinate is fixed when removing its column lowers the equation
        rank; this correctly distinguishes a merely horizontal line from one
        whose position and length are also constrained.
        """
        point_count = len(self.points)
        circle_count = len(self.circles)
        columns = point_count * 2 + circle_count
        if not columns:
            return set(), set(), set()

        def row() -> List[float]:
            return [0.0] * columns

        rows: List[List[float]] = []

        def fixed_point(index: int) -> None:
            if not 0 <= index < point_count:
                return
            for axis in range(2):
                equation = row()
                equation[index * 2 + axis] = 1.0
                rows.append(equation)

        for index in self.projected_point_indices():
            fixed_point(index)
        for projection in self.projected_edges:
            if 0 <= projection.edge < len(self.edges):
                fixed_point(self.edges[projection.edge][0])
                fixed_point(self.edges[projection.edge][1])
        for projection in self.projected_circles:
            if 0 <= projection.circle < circle_count:
                center = self.point_index(self.circles[projection.circle].midPoint)
                if center is not None:
                    fixed_point(center)
                equation = row()
                equation[point_count * 2 + projection.circle] = 1.0
                rows.append(equation)
        for coincidence in self.coincidences:
            first, second = coincidence.first, coincidence.second
            if first[0] == second[0] == "point":
                for axis in range(2):
                    equation = row()
                    equation[first[1] * 2 + axis] = 1.0
                    equation[second[1] * 2 + axis] = -1.0
                    rows.append(equation)
            else:
                reference = second if first[0] == "origin" else first
                if reference[0] == "point":
                    fixed_point(reference[1])
        for index, (first, second) in enumerate(self.edges):
            constraint = self.edge_constraint(index)
            if constraint is None:
                continue
            equation = row()
            axis = 1 if constraint == "horizontal" else 0
            equation[first * 2 + axis] = 1.0
            equation[second * 2 + axis] = -1.0
            rows.append(equation)
        for measurement in self.measurements:
            if measurement.value is None:
                continue
            if measurement.kind == "diameter" and measurement.first[0] == "circle":
                index = measurement.first[1]
                if 0 <= index < circle_count:
                    equation = row()
                    equation[point_count * 2 + index] = 1.0
                    rows.append(equation)
                continue
            value = self.measurement_value(
                measurement.kind, measurement.first, measurement.second
            )
            if value is None:
                continue
            equation = row()
            # Nudge one coordinate at a time on a single working copy instead
            # of rebuilding every point for every column.
            working = [point2d(point) for point in self.points]
            for column in range(point_count * 2):
                delta_x = 1e-5 if column % 2 == 0 else 0.0
                delta_y = 1e-5 if column % 2 else 0.0
                target = working[column // 2]
                target.move((delta_x, delta_y))
                changed = self.measurement_value(
                    measurement.kind, measurement.first,
                    measurement.second, working,
                )
                if changed is not None:
                    equation[column] = (changed - value) / 1e-5
                target.move((-delta_x, -delta_y))
            rows.append(equation)
        for equal in self.equals:
            kind = equal.first[0]
            if kind != equal.second[0]:
                continue
            equation = row()
            first, second = equal.first[1], equal.second[1]
            if kind == "circle":
                if (
                    0 <= first < circle_count
                    and 0 <= second < circle_count
                ):
                    equation[point_count * 2 + first] = 1.0
                    equation[point_count * 2 + second] = -1.0
                    rows.append(equation)
                continue
            if not (
                0 <= first < len(self.edges)
                and 0 <= second < len(self.edges)
            ):
                continue
            if not (
                self._add_length_derivative(equation, first, 1.0)
                and self._add_length_derivative(equation, second, -1.0)
            ):
                continue
            rows.append(equation)
        # A single reduction returns both the rank and the fully-determined
        # coordinates, so the expensive per-column re-ranking is gone.
        _, fixed = _rank_and_fixed_columns(rows, columns)
        points = {
            index for index in range(point_count)
            if index * 2 in fixed and index * 2 + 1 in fixed
        }
        edges = {
            index for index, (first, second) in enumerate(self.edges)
            if first in points and second in points
        }
        circles = {
            index for index, circle in enumerate(self.circles)
            if self.point_index(circle.midPoint) in points
            and point_count * 2 + index in fixed
        }
        return points, edges, circles

    def edge_constraint(self, index: int) -> Optional[str]:
        """Return the axis constraint for an edge, if any."""
        if 0 <= index < len(self.edge_constraints):
            return self.edge_constraints[index]
        return None

    def edge_is_aligned(
        self, index: int, constraint: str
    ) -> bool:
        """Return whether an edge already satisfies an axis constraint."""
        if not 0 <= index < len(self.edges):
            return False
        first, second = self.edges[index]
        if not (
            0 <= first < len(self.points)
            and 0 <= second < len(self.points)
        ):
            return False
        start = self.points[first]
        end = self.points[second]
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        tolerance = 1e-6 * max(
            1.0, math.hypot(delta_x, delta_y)
        )
        if constraint == "horizontal":
            return abs(delta_y) <= tolerance
        if constraint == "vertical":
            return abs(delta_x) <= tolerance
        return False

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
        equal, and vertical constraints do the same for x-coordinates.
        Coincident points share both coordinates, so they join the same
        groups on both axes; a coincidence with the document origin pins its
        group to the projected origin.  Each connected group is therefore
        solved independently for the affected axis.  ``locked`` lists the
        preferred anchor points in priority order; the first anchor in a
        group provides its target coordinate.  Remaining points in the group
        follow, which keeps every constraint satisfied even when several
        previously constrained edges meet.

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
        # Projected points follow the solid body.  They are reference
        # geometry, so constraints must anchor to them instead of moving
        # them; otherwise the next projection refresh would undo the edit.
        projected = {
            index for index in self.projected_point_indices()
            if 0 <= index < count
        }

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

        origin_points: set = set()
        for coincidence in self.coincidences:
            first, second = coincidence.first, coincidence.second
            if first[0] == "point" and second[0] == "point":
                if (
                    0 <= first[1] < count
                    and 0 <= second[1] < count
                ):
                    join(horizontal, first[1], second[1])
                    join(vertical, first[1], second[1])
                continue
            point_ref = (
                second if first[0] == "origin" else first
            )
            if point_ref[0] == "point" and 0 <= point_ref[1] < count:
                origin_points.add(point_ref[1])

        origin = self.origin_point() if origin_points else None
        locked_rank = _first_positions(locked_order)
        changed_rank = _first_positions(changed_order)
        for parent, axis in ((horizontal, 1), (vertical, 0)):
            groups: Dict[int, List[int]] = {}
            for index in range(count):
                groups.setdefault(root(parent, index), []).append(index)
            for members in groups.values():
                target: Optional[float] = None
                anchor = _pick_anchor(members, locked_rank, changed_rank)
                fixed_members = [
                    index for index in members if index in projected
                ]
                if origin is not None and any(
                    index in origin_points for index in members
                ):
                    target = origin[axis]
                elif fixed_members:
                    # A projected point is already positioned by the solid.
                    # Align the free members of its group to it and leave the
                    # projected point itself untouched.
                    fixed_anchor = _pick_anchor(
                        fixed_members, locked_rank, changed_rank
                    )
                    target = points[fixed_anchor][axis]
                elif previous is not None and len(previous) == count:
                    shifts = [
                        points[index][axis] - previous[index][axis]
                        for index in members
                        if index not in projected
                        and abs(
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
                    if index in projected:
                        continue
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
        by_identity: Dict[int, int] = {}
        for index, existing in enumerate(self.points):
            by_identity.setdefault(id(existing), index)
        for circle in self.circles:
            if circle.diameter <= 0.0:
                continue
            index = by_identity.get(id(circle.midPoint))
            if index is None:
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

    def loop_is_closed(self, loop: Sequence[int]) -> bool:
        """Return whether a profile loop still has every edge it needs.

        Deleting a sketch edge must invalidate any feature profile that used
        it.  Point-index loops alone would keep describing the old polygon.
        """
        if len(loop) == 1:
            return self.circle_for_loop(loop) is not None
        if len(loop) < 3:
            return False
        pairs = set()
        for start, end in self.edges:
            pairs.add((start, end))
            pairs.add((end, start))
        count = len(loop)
        return all(
            (loop[index], loop[(index + 1) % count]) in pairs
            for index in range(count)
        )

    def geometry_signature(self) -> Tuple[object, ...]:
        """Return a hashable snapshot used to detect sketch edits."""
        return (
            tuple(
                (round(point[0], 6), round(point[1], 6))
                for point in self.points
            ),
            tuple(self.edges),
            tuple(self.edge_bulges),
            tuple(
                (
                    round(circle.midPoint[0], 6),
                    round(circle.midPoint[1], 6),
                    round(circle.diameter, 6),
                )
                for circle in self.circles
            ),
        )

    def loop_points(self, loop: Sequence[int]) -> List[Point]:
        """Return the boundary polygon for an edge loop or a circle loop.

        Circular bulges contribute sampled points here only so area, picking
        and the volume rebuild can consume the exact shape; the stored edge
        itself remains one two-point arc.
        """
        circle = self.circle_for_loop(loop)
        if circle is not None:
            return circle_polygon(circle)
        if len(loop) < 3:
            return []
        if any(not 0 <= index < len(self.points) for index in loop):
            return []
        points: List[Point] = []
        bulges = self._bulge_lookup()
        for offset, index in enumerate(loop):
            following = loop[(offset + 1) % len(loop)]
            start = self.points[index]
            points.append(start)
            bulge = bulges.get((index, following))
            if bulge is not None:
                samples = bulge_arc_points(
                    start, self.points[following], bulge
                )
                points.extend(samples[1:-1])
        return points

    def edge_bulge(self, index: int) -> Optional[float]:
        """Return the circular bulge of one edge, or ``None`` if straight."""
        if not 0 <= index < len(self.edge_bulges):
            return None
        return self.edge_bulges[index]

    def edge_points(self, index: int) -> List[Point]:
        """Return the display/rebuild polyline for one exact edge shape."""
        if not 0 <= index < len(self.edges):
            return []
        start, end = self.edges[index]
        bulge = self.edge_bulge(index)
        if bulge is None:
            return [self.points[start], self.points[end]]
        return bulge_arc_points(
            self.points[start], self.points[end], bulge
        )

    def edge_bulge_between(
        self, first: int, second: int
    ) -> Optional[float]:
        """Return the bulge when an edge joins two loop points."""
        for index, (start, end) in enumerate(self.edges):
            bulge = self.edge_bulge(index)
            if bulge is None:
                continue
            if start == first and end == second:
                return bulge
            if start == second and end == first:
                return -bulge
        return None

    def loop_area(self, loop: Sequence[int]) -> float:
        """Return the exact area of an edge loop or circle loop.

        Bulged edges contribute their true circular segment area instead of
        the chord approximation used for display sampling.
        """
        circle = self.circle_for_loop(loop)
        if circle is not None:
            return math.pi * circle.radius * circle.radius
        if len(loop) < 3:
            return 0.0
        if any(not 0 <= index < len(self.points) for index in loop):
            return 0.0
        area = polygon_area([self.points[index] for index in loop])
        bulges = self._bulge_lookup()
        for offset, index in enumerate(loop):
            following = loop[(offset + 1) % len(loop)]
            bulge = bulges.get((index, following))
            if bulge is not None:
                area += self._circular_segment_area(index, following, bulge)
        return abs(area)

    def _bulge_lookup(self) -> Dict[Tuple[int, int], float]:
        """Map each directed edge to its signed bulge.

        Same answers as :meth:`edge_bulge_between`: a reversed edge yields
        the negated bulge, and the first edge in order wins for each pair.
        """
        lookup: Dict[Tuple[int, int], float] = {}
        for index, (start, end) in enumerate(self.edges):
            bulge = self.edge_bulge(index)
            if bulge is None:
                continue
            lookup.setdefault((start, end), bulge)
            lookup.setdefault((end, start), -bulge)
        return lookup

    def _segment_area(self, first: int, second: int) -> float:
        """Return the signed circular segment area of a bulged edge."""
        bulge = self.edge_bulge_between(first, second)
        if bulge is None:
            return 0.0
        return self._circular_segment_area(first, second, bulge)

    def _circular_segment_area(
        self, first: int, second: int, bulge: float
    ) -> float:
        """Return the signed circular segment area for a known bulge."""
        start = self.points[first]
        end = self.points[second]
        chord = math.hypot(
            end[0] - start[0], end[1] - start[1]
        )
        if chord <= 1e-12:
            return 0.0
        sweep = 4.0 * math.atan(bulge)
        radius = chord / (2.0 * abs(math.sin(sweep * 0.5)))
        return 0.5 * radius * radius * (sweep - math.sin(sweep))

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

    def add_circle(self, center: Point, diameter: float) -> Circle:
        """Append a circle and bind its midpoint to a regular sketch point."""
        index = self.add_point(center)
        circle = Circle(self.points[index], diameter)
        self.circles.append(circle)
        return circle

    def remove_point(self, index: int) -> Dict[int, int]:
        """Remove a point, its edges, and measurements that depend on them.

        Returns the surviving edge index map so features can keep their
        references valid after the deletion shifted the edge list.
        """
        if not 0 <= index < len(self.points):
            return {}
        removed_point = self.points.pop(index)
        circles: List[Circle] = []
        circle_map: Dict[int, int] = {}
        for circle_index, circle in enumerate(self.circles):
            if circle.midPoint is removed_point:
                continue
            circle_map[circle_index] = len(circles)
            circles.append(circle)
        self.circles = circles
        shifted: List[Tuple[int, int]] = []
        constraints: List[Optional[str]] = []
        bulges: List[Optional[float]] = []
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
            bulges.append(self.edge_bulge(edge_index))
        self.edges = shifted
        self.edge_constraints = constraints
        self.edge_bulges = bulges

        measurements: List[Measurement] = []
        for measurement in self.measurements:
            first = self._remap_measurement_ref(
                measurement.first, index, edge_map, circle_map
            )
            second = self._remap_measurement_ref(
                measurement.second, index, edge_map, circle_map
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
        self.coincidences = self._remap_removed_point_coincidences(
            index
        )
        self.equals = self._remap_removed_point_equals(
            edge_map, circle_map
        )
        self._remap_projected_points(index, edge_map, circle_map)
        return edge_map

    def _remap_removed_point_equals(
        self,
        edge_map: Dict[int, int],
        circle_map: Dict[int, int],
    ) -> List[Equal]:
        """Keep equality references valid after a point is removed."""
        result: List[Equal] = []
        for equal in self.equals:
            # Ensure both references are the same kind (line-line or circle-circle)
            if equal.first[0] != equal.second[0]:
                continue
                
            # Select the appropriate mapping based on reference type
            mapping = edge_map if equal.first[0] == "line" else circle_map
            
            first = mapping.get(equal.first[1])
            second = mapping.get(equal.second[1])
            if first is None or second is None:
                continue
            result.append(Equal(
                (equal.first[0], first),
                (equal.second[0], second),
            ))
        return result

    def _remap_removed_point_coincidences(
        self, removed: int
    ) -> List[Coincident]:
        """Drop or shift coincidences after a point is deleted."""
        result: List[Coincident] = []
        for coincidence in self.coincidences:
            first = self._shift_coincident_ref(
                coincidence.first, removed
            )
            second = self._shift_coincident_ref(
                coincidence.second, removed
            )
            if first is None or second is None or first == second:
                continue
            if first[0] == "origin" and second[0] == "origin":
                continue
            result.append(Coincident(first, second))
        return result

    @staticmethod
    def _shift_coincident_ref(
        ref: Tuple[str, int], removed: int
    ) -> Optional[Tuple[str, int]]:
        """Shift one coincidence reference past a deleted point."""
        kind, index = ref
        if kind != "point":
            return ref
        if index == removed:
            return None
        return (kind, index - 1 if index > removed else index)

    def select_constraints(
        self,
        constraint_kind: Optional[str] = None,
        target_type: Optional[str] = None,
        target_index: Optional[int] = None,
    ) -> List[Union[Coincident, Equal, Measurement]]:
        """Select constraints based on criteria.
        
        Args:
            constraint_kind: Filter by constraint type ('coincident', 'equal', 'measurement').
                           If None, include all constraint types.
            target_type: Filter by target type ('point', 'line', 'circle').
                        If None, include all target types.
            target_index: Filter by target index. If None, include all indices.
                        
        Returns:
            List of constraints matching the criteria
        """
        result: List[Union[Coincident, Equal, Measurement]] = []
        
        # Select coincidences
        for constraint in self.coincidences:
            if constraint_kind is not None and constraint_kind != "coincident":
                continue
            if target_type and constraint.first[0] != target_type and constraint.second[0] != target_type:
                continue
            if target_index and constraint.first[1] != target_index and constraint.second[1] != target_index:
                continue
            result.append(constraint)
                
        # Select equalities
        for constraint in self.equals:
            if constraint_kind is not None and constraint_kind != "equal":
                continue
            if target_type and constraint.first[0] != target_type and constraint.second[0] != target_type:
                continue
            if target_index and constraint.first[1] != target_index and constraint.second[1] != target_index:
                continue
            result.append(constraint)
                
        # Select measurements
        for constraint in self.measurements:
            if constraint_kind is not None and constraint_kind != "measurement":
                continue
            if target_type and constraint.first[0] != target_type and constraint.second[0] != target_type:
                continue
            if target_index and constraint.first[1] != target_index and constraint.second[1] != target_index:
                continue
            result.append(constraint)
                
        return result

    def remove_constraints(
        self,
        constraint_kind: Optional[str] = None,
        target_type: Optional[str] = None,
        target_index: Optional[int] = None,
        specific_constraints: Optional[List[Union[Coincident, Equal, Measurement]]] = None,
    ) -> int:
        """Remove constraints based on criteria or specific constraints.
        
        Args:
            constraint_kind: Remove by constraint type ('coincident', 'equal', 'measurement').
                           If None, remove all constraint types.
            target_type: Remove constraints involving this target type ('point', 'line', 'circle').
                        If None, remove all target types.
            target_index: Remove constraints involving this target index. If None, remove all indices.
            specific_constraints: Remove these specific constraints
            
        Returns:
            Number of constraints removed
        """
        removed_count = 0
        
        if specific_constraints:
            # Remove specific constraints
            for constraint in specific_constraints:
                if isinstance(constraint, Coincident):
                    try:
                        self.coincidences.remove(constraint)
                        removed_count += 1
                    except ValueError:
                        pass
                elif isinstance(constraint, Equal):
                    try:
                        self.equals.remove(constraint)
                        removed_count += 1
                    except ValueError:
                        pass
                elif isinstance(constraint, Measurement):
                    try:
                        self.measurements.remove(constraint)
                        removed_count += 1
                    except ValueError:
                        pass
            return removed_count
            
        # Remove by criteria
        remaining_coincidences: List[Coincident] = []
        remaining_equals: List[Equal] = []
        remaining_measurements: List[Measurement] = []
        
        for constraint in self.coincidences:
            if constraint_kind is not None and constraint_kind != "coincident":
                remaining_coincidences.append(constraint)
                continue
            if target_type and constraint.first[0] != target_type and constraint.second[0] != target_type:
                remaining_coincidences.append(constraint)
                continue
            if target_index and constraint.first[1] != target_index and constraint.second[1] != target_index:
                remaining_coincidences.append(constraint)
                continue
                
        for constraint in self.equals:
            if constraint_kind is not None and constraint_kind != "equal":
                remaining_equals.append(constraint)
                continue
            if target_type and constraint.first[0] != target_type and constraint.second[0] != target_type:
                remaining_equals.append(constraint)
                continue
            if target_index and constraint.first[1] != target_index and constraint.second[1] != target_index:
                remaining_equals.append(constraint)
                continue
                
        for constraint in self.measurements:
            if constraint_kind is not None and constraint_kind != "measurement":
                remaining_measurements.append(constraint)
                continue
            if target_type and constraint.first[0] != target_type and constraint.second[0] != target_type:
                remaining_measurements.append(constraint)
                continue
            if target_index and constraint.first[1] != target_index and constraint.second[1] != target_index:
                remaining_measurements.append(constraint)
                continue
                
        removed_count += len(self.coincidences) - len(remaining_coincidences)
        removed_count += len(self.equals) - len(remaining_equals)
        removed_count += len(self.measurements) - len(remaining_measurements)
        
        self.coincidences = remaining_coincidences
        self.equals = remaining_equals
        self.measurements = remaining_measurements
        
        return removed_count

    def remove_edge(self, index: int) -> None:
        """Remove one edge and any measurement that depends on it."""
        if not 0 <= index < len(self.edges):
            return
        del self.edges[index]
        if index < len(self.edge_constraints):
            del self.edge_constraints[index]
        if index < len(self.edge_bulges):
            del self.edge_bulges[index]
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
        self.equals = self._remap_removed_edge_equals(index)
        self._shift_projected_edges(index)

    def _remap_removed_edge_equals(self, index: int) -> List[Equal]:
        """Drop or shift equality references after an edge is deleted."""
        result: List[Equal] = []
        for equal in self.equals:
            first_kind = equal.first[0]
            second_kind = equal.second[0]
            
            # Skip equalities that reference the removed edge
            if first_kind == "line" and equal.first[1] == index:
                continue
            if second_kind == "line" and equal.second[1] == index:
                continue
                
            # For line-line equality, adjust indices
            if first_kind == "line" and second_kind == "line":
                first = equal.first[1]
                second = equal.second[1]
                if first == index or second == index:
                    continue
                result.append(Equal(
                    ("line", first - 1 if first > index else first),
                    ("line", second - 1 if second > index else second),
                ))
            # For line-circle or circle-line equality, adjust line index only
            elif first_kind == "line" or second_kind == "line":
                result.append(equal)
            # For circle-circle equality, keep both unchanged
            else:
                result.append(equal)
                
        return result

    def _remap_projected_points(
        self,
        removed_point: int,
        edge_map: Dict[int, int],
        circle_map: Dict[int, int],
    ) -> None:
        """Keep projection links valid after a point is removed."""
        links: List[ProjectedPoint] = []
        for link in self.projected_points:
            if link.point == removed_point:
                continue
            index = link.point - 1 if link.point > removed_point else link.point
            links.append(ProjectedPoint(index, link.source))
        self.projected_points = links
        self._remap_projected_edges(edge_map)
        self._remap_projected_circles(circle_map)

    def _remap_projected_edges(
        self, edge_map: Dict[int, int]
    ) -> None:
        edges: List[ProjectedEdge] = []
        for link in self.projected_edges:
            mapped = edge_map.get(link.edge)
            if mapped is not None:
                edges.append(ProjectedEdge(
                    mapped, link.feature_id, link.start, link.end,
                    link.bulge,
                ))
        self.projected_edges = edges

    def _remap_projected_circles(
        self, circle_map: Dict[int, int]
    ) -> None:
        circles: List[ProjectedCircle] = []
        for link in self.projected_circles:
            mapped = circle_map.get(link.circle)
            if mapped is not None:
                circles.append(ProjectedCircle(
                    mapped, link.center, link.source_circle, link.radius
                ))
        self.projected_circles = circles

    def _shift_projected_edges(self, removed: int) -> None:
        """Drop a deleted projected edge and shift later links down."""
        edges: List[ProjectedEdge] = []
        for link in self.projected_edges:
            if link.edge == removed:
                continue
            index = link.edge - 1 if link.edge > removed else link.edge
            edges.append(ProjectedEdge(
                index, link.feature_id, link.start, link.end,
                link.bulge,
            ))
        self.projected_edges = edges

    def is_projected_point(self, index: int) -> bool:
        """Return whether a sketch point follows solid geometry.

        A projected circle's centre is owned by the circle link rather than
        a point link, but it must behave like any other projected entity.
        """
        if any(link.point == index for link in self.projected_points):
            return True
        if not 0 <= index < len(self.points):
            return False
        point = self.points[index]
        return any(
            0 <= link.circle < len(self.circles)
            and self.circles[link.circle].midPoint is point
            for link in self.projected_circles
        )

    def is_projected_edge(self, index: int) -> bool:
        """Return whether a sketch edge follows solid geometry."""
        return any(link.edge == index for link in self.projected_edges)

    def projected_point_indices(self) -> Set[int]:
        """Return every point index that is fixed by a projection link."""
        indices = {
            link.point for link in self.projected_points
            if 0 <= link.point < len(self.points)
        }
        for link in self.projected_circles:
            if not 0 <= link.circle < len(self.circles):
                continue
            center = self.circles[link.circle].midPoint
            for index, point in enumerate(self.points):
                if point is center:
                    indices.add(index)
                    break
        return indices

    def is_projected_circle(self, index: int) -> bool:
        """Return whether a sketch circle follows solid geometry."""
        return any(link.circle == index for link in self.projected_circles)

    def is_circle_constrained_by_equality(self, index: int) -> bool:
        """Return whether a circle is part of an equality constraint."""
        for equal in self.equals:
            if equal.first[0] == "circle" and equal.first[1] == index:
                return True
            if equal.second[0] == "circle" and equal.second[1] == index:
                return True
        return False

    def is_point_constrained_by_coincidence(self, index: int) -> bool:
        """Return whether a point is part of a coincidence constraint."""
        for coincidence in self.coincidences:
            if coincidence.first[0] == "point" and coincidence.first[1] == index:
                return True
            if coincidence.second[0] == "point" and coincidence.second[1] == index:
                return True
        return False

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
        circle_map: Dict[int, int],
    ) -> Optional[Tuple[str, int]]:
        kind, index = ref
        if kind == "point":
            if index == removed_point:
                return None
            return (kind, index - 1 if index > removed_point else index)
        if kind == "line":
            mapped = edge_map.get(index)
            return (kind, mapped) if mapped is not None else None
        if kind == "circle":
            mapped = circle_map.get(index)
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

    def origin_point(self) -> Point:
        """Return the document origin projected into the sketch plane.

        The projection is expressed in the sketch's local U/V coordinates,
        so a coincidence with the origin pins a point to world (0, 0, 0)
        even when the sketch sits on a face away from the document origin.
        """
        frame = self.frame()
        origin = frame.origin
        return point2d((
            -(
                origin[0] * frame.u[0]
                + origin[1] * frame.u[1]
                + origin[2] * frame.u[2]
            ),
            -(
                origin[0] * frame.v[0]
                + origin[1] * frame.v[1]
                + origin[2] * frame.v[2]
            ),
        ))

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
            "edge_bulges": list(self.edge_bulges),
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
            "coincidences": [
                coincidence.to_dict()
                for coincidence in self.coincidences
            ],
            "equals": [
                equal.to_dict() for equal in self.equals
            ],
            "projected_points": [
                link.to_dict() for link in self.projected_points
            ],
            "projected_edges": [
                link.to_dict() for link in self.projected_edges
            ],
            "projected_circles": [
                link.to_dict() for link in self.projected_circles
            ],
            "line_type": self.line_type,
            "visible": bool(self.visible),
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
        bulges: List[Optional[float]] = []
        raw_edges = data.get("edges")
        raw_profile = data.get("profile")
        raw_constraints = data.get("edge_constraints")
        raw_bulges = data.get("edge_bulges")
        if not isinstance(raw_constraints, (list, tuple)):
            raw_constraints = []
        if not isinstance(raw_bulges, (list, tuple)):
            raw_bulges = []
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
                    bulge = (
                        raw_bulges[raw_index]
                        if raw_index < len(raw_bulges)
                        else None
                    )
                    bulges.append(normalize_bulge(bulge))
            # Older point-profile sketches stored their loop separately.
            before = len(edges)
            cls._add_loop_edges(
                edges, cls._valid_profile(raw_profile, len(points))
            )
            bulges.extend([None] * (len(edges) - before))
        else:
            # Legacy sketches draw a profile through their ordered points
            # and store extra edge coordinates separately.
            if isinstance(raw_profile, (list, tuple)):
                profile = cls._valid_profile(raw_profile, len(points))
            else:
                profile = list(range(len(points)))
            before = len(edges)
            cls._add_loop_edges(edges, profile)
            bulges.extend([None] * (len(edges) - before))
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
                before = len(edges)
                cls._add_edge(edges, start_index, end_index)
                bulges.extend([None] * (len(edges) - before))

        constraints.extend([None] * (len(edges) - len(constraints)))
        bulges = bulges[:len(edges)]
        bulges.extend([None] * (len(edges) - len(bulges)))
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
        coincidences: List[Coincident] = []
        raw_coincidences = data.get("coincidences", [])
        if isinstance(raw_coincidences, (list, tuple)):
            for raw in raw_coincidences:
                coincidence = Coincident.from_dict(raw)
                if coincidence is not None:
                    coincidences.append(coincidence)
        equals: List[Equal] = []
        raw_equals = data.get("equals", [])
        if isinstance(raw_equals, (list, tuple)):
            for raw in raw_equals:
                equal = Equal.from_dict(raw)
                if equal is not None:
                    equals.append(equal)
        projected_points: List[ProjectedPoint] = []
        raw_projected_points = data.get("projected_points", [])
        if isinstance(raw_projected_points, (list, tuple)):
            for raw in raw_projected_points:
                link = ProjectedPoint.from_dict(raw)
                if link is not None:
                    projected_points.append(link)
        projected_edges: List[ProjectedEdge] = []
        raw_projected_edges = data.get("projected_edges", [])
        if isinstance(raw_projected_edges, (list, tuple)):
            for raw in raw_projected_edges:
                link = ProjectedEdge.from_dict(raw)
                if link is not None:
                    projected_edges.append(link)
        projected_circles: List[ProjectedCircle] = []
        raw_projected_circles = data.get("projected_circles", [])
        if isinstance(raw_projected_circles, (list, tuple)):
            for raw in raw_projected_circles:
                link = ProjectedCircle.from_dict(raw)
                if link is not None:
                    projected_circles.append(link)
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
            visible=bool(data.get("visible", True)),
            edges=edges,
            edge_constraints=constraints[:len(edges)],
            edge_bulges=bulges,
            circles=circles,
            measurements=measurements,
            coincidences=coincidences,
            equals=equals,
            projected_points=projected_points,
            projected_edges=projected_edges,
            projected_circles=projected_circles,
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
        # Same rules as _add_edge, with one set of known edges instead of a
        # full scan of ``edges`` for every new pair.
        known = {(min(a, b), max(a, b)) for a, b in edges}
        for start, end in pairs:
            key = (min(start, end), max(start, end))
            if start == end or key in known:
                continue
            known.add(key)
            edges.append((start, end))

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

    ``point``/``edge`` remember which sketch entity produced the fillet.
    They keep the rounding on its source when the sketch is edited, instead
    of leaving it at a stale coordinate.  Older files without them are
    rebound from ``(u, v)`` on the first recompute.
    """

    kind: str = "vertical"
    u: float = 0.0
    v: float = 0.0
    radius: float = 0.0
    point: Optional[int] = None
    edge: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "kind": self.kind,
            "u": self.u,
            "v": self.v,
            "radius": self.radius,
        }
        if self.point is not None:
            data["point"] = self.point
        if self.edge is not None:
            data["edge"] = self.edge
        return data

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
            point = _optional_index(data.get("point"))
            edge = _optional_index(data.get("edge"))
        elif isinstance(data, (list, tuple)) and len(data) >= 3:
            # Version 1 stored only vertical fillets as [u, v, radius].
            kind = "vertical"
            try:
                u = float(data[0])
                v = float(data[1])
                radius = float(data[2])
            except (TypeError, ValueError):
                return None
            point = None
            edge = None
        else:
            return None
        if kind not in ("vertical", "top", "bottom"):
            kind = "vertical"
        if radius <= 0.0:
            return None
        return cls(kind, u, v, radius, point, edge)

    def bind(self, sketch: Sketch) -> None:
        """Remember the sketch point or edge that produced this fillet."""
        if self.point is not None or self.edge is not None:
            return
        if self.kind == "vertical":
            self.point = _point_near(sketch, (self.u, self.v))
        else:
            self.edge = _edge_near(sketch, (self.u, self.v))

    def refresh(self, sketch: Sketch) -> bool:
        """Move the fillet with its source; return False when it is gone."""
        self.bind(sketch)
        if self.point is not None:
            if not 0 <= self.point < len(sketch.points):
                self.point = None
                return self.edge is not None
            point = sketch.points[self.point]
            self.u = float(point[0])
            self.v = float(point[1])
            return True
        if self.edge is not None:
            if not 0 <= self.edge < len(sketch.edges):
                self.edge = None
                return False
            samples = sketch.edge_points(self.edge)
            if not samples:
                return False
            if len(samples) == 2:
                self.u = (samples[0][0] + samples[1][0]) * 0.5
                self.v = (samples[0][1] + samples[1][1]) * 0.5
            else:
                middle = samples[len(samples) // 2]
                self.u = float(middle[0])
                self.v = float(middle[1])
            return True
        return True


def _optional_index(value: Any) -> Optional[int]:
    """Parse an optional non-negative entity index."""
    if value is None or isinstance(value, bool):
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def _point_near(
    sketch: Sketch, point: Point, tolerance: float = 1e-4
) -> Optional[int]:
    """Return the sketch point at one local coordinate."""
    for index, existing in enumerate(sketch.points):
        if (
            abs(existing[0] - point[0]) <= tolerance
            and abs(existing[1] - point[1]) <= tolerance
        ):
            return index
    return None


def _edge_near(
    sketch: Sketch, point: Point, tolerance: float = 1e-4
) -> Optional[int]:
    """Return the sketch edge that passes through one local coordinate."""
    for index in range(len(sketch.edges)):
        samples = sketch.edge_points(index)
        for first, second in zip(samples, samples[1:]):
            if _segment_distance(point, first, second) <= tolerance:
                return index
    return None


def _segment_distance(
    point: Point, first: Point, second: Point
) -> float:
    """Return the distance from a point to a line segment."""
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return math.hypot(point[0] - first[0], point[1] - first[1])
    amount = (
        (point[0] - first[0]) * dx + (point[1] - first[1]) * dy
    ) / length_squared
    amount = min(1.0, max(0.0, amount))
    return math.hypot(
        point[0] - (first[0] + dx * amount),
        point[1] - (first[1] + dy * amount),
    )


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
class BooleanSource:
    """The tool extrusion that produced one boolean operation.

    Keeping the tool parameters lets a combined body be rebuilt when either
    the body's sketch or the tool's sketch is edited.  Loops are point
    indices in the tool sketch, just like ``Extrude.profiles``.
    """

    sketch_id: int
    height: float = 20.0
    start: float = 0.0
    profiles: List[List[int]] = field(default_factory=list)
    regions: List[List[List[int]]] = field(default_factory=list)
    cuts: List[List[int]] = field(default_factory=list)
    operation: str = "join"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sketch": self.sketch_id,
            "height": self.height,
            "start": self.start,
            "operation": self.operation,
            "profiles": [list(loop) for loop in self.profiles],
            "regions": [
                [list(loop) for loop in region] for region in self.regions
            ],
            "cuts": [list(loop) for loop in self.cuts],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BooleanSource"]:
        if not isinstance(data, dict):
            return None
        try:
            sketch_id = int(data.get("sketch", -1))
            height = float(data.get("height", 20.0))
            start = float(data.get("start", 0.0))
        except (TypeError, ValueError):
            return None
        if sketch_id < 0:
            return None
        return cls(
            sketch_id,
            height,
            start,
            Extrude._parse_loops(data.get("profiles", [])),
            Extrude._parse_regions(data.get("regions", [])),
            Extrude._parse_loops(data.get("cuts", [])),
            str(data.get("operation", "join")),
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
    # Boolean tools that produced ``slices``, in application order.  Empty
    # for a plain prism or for older files whose booleans were baked.
    booleans: List[BooleanSource] = field(default_factory=list)
    # Fillets applied after a boolean was baked into the slices.
    slices_fillets: List[Fillet] = field(default_factory=list)
    # Legacy files may name no profile and rely on the sketch's first loop.
    # Once a profile is deleted the feature must stay empty instead of
    # silently extruding whatever geometry is left.
    fallback: bool = True
    # Signature of the inputs that produced ``slices``; None forces a replay.
    _boolean_state: Optional[Tuple[object, ...]] = field(
        default=None, repr=False, compare=False
    )

    def to_dict(self) -> Dict[str, Any]:
        data = {
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
        if self.booleans:
            data["booleans"] = [
                source.to_dict() for source in self.booleans
            ]
        if self.slices_fillets:
            data["slices_fillets"] = [
                fillet.to_dict() for fillet in self.slices_fillets
            ]
        if not self.fallback:
            data["fallback"] = False
        return data

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
            booleans=cls._parse_booleans(data.get("booleans", [])),
            slices_fillets=cls._parse_fillets(
                data.get("slices_fillets", [])
            ),
            fallback=bool(data.get("fallback", True)),
        )

    @staticmethod
    def _parse_booleans(raw_sources: Any) -> List[BooleanSource]:
        sources: List[BooleanSource] = []
        if not isinstance(raw_sources, (list, tuple)):
            return sources
        for raw_source in raw_sources:
            source = BooleanSource.from_dict(raw_source)
            if source is not None:
                sources.append(source)
        return sources

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
            if not sketch.loop_is_closed(profile):
                continue
            points = sketch.loop_points(profile)
            if len(points) >= 3:
                loops.append(points)
        for region in self.regions:
            if not all(sketch.loop_is_closed(loop) for loop in region):
                continue
            polygons: List[List[Point]] = []
            for loop in region:
                points = sketch.loop_points(loop)
                if len(points) >= 3:
                    polygons.append(points)
            if polygons:
                loops.extend(intersect_loops(polygons))
        if loops or self.profiles or self.regions:
            return loops
        if not self.fallback:
            return []
        fallback = sketch.profile_points()
        return [fallback] if len(fallback) >= 3 else []

    def resolve_cuts(self, sketch: Sketch) -> List[List[Point]]:
        """Return the overlapping profiles that cut the selected material."""
        loops: List[List[Point]] = []
        for cut in self.cuts:
            if not sketch.loop_is_closed(cut):
                continue
            points = sketch.loop_points(cut)
            if len(points) >= 3:
                loops.append(points)
        return loops

    def recompute(self, document: "Document", sketch: Sketch) -> None:
        """Re-derive feature state from the current sketch geometry.

        Feature loops are point indices, so they are remapped when points are
        deleted.  Fillets also keep a source reference and follow the corner
        or edge they were placed on instead of staying at a stale coordinate.
        A body that was combined by a boolean is rebuilt from its stored tool
        sources so editing either sketch updates the finished shape.
        """
        self.fillets = [
            fillet for fillet in self.fillets
            if fillet.refresh(sketch)
        ]
        self._contact_face_cache = None
        if self.booleans:
            self._recompute_booleans(document)

    def _recompute_booleans(self, document: "Document") -> None:
        """Replay stored boolean tools when their input geometry changed."""
        state = self._boolean_signature(document)
        if state == self._boolean_state:
            return
        self._boolean_state = state
        from .booleans import fillet_slices_body, replay_booleans

        stack = replay_booleans(document, self)
        if stack is None:
            return
        for fillet in self.slices_fillets if stack else ():
            rounded = fillet_slices_body(stack, fillet)
            if rounded is not None:
                stack = rounded
        self.slices = stack

    def _boolean_signature(self, document: "Document") -> Tuple[object, ...]:
        """Return everything that affects a combined body's shape."""
        parts: List[object] = [
            _sketch_signature(document, self.sketch_id),
            round(self.height, 6),
            round(self.start, 6),
            tuple(tuple(loop) for loop in self.profiles),
            tuple(
                tuple(tuple(loop) for loop in region)
                for region in self.regions
            ),
            tuple(tuple(loop) for loop in self.cuts),
            tuple(_fillet_signature(fillet) for fillet in self.fillets),
            tuple(
                _fillet_signature(fillet)
                for fillet in self.slices_fillets
            ),
        ]
        for source in self.booleans:
            parts.append((
                source.sketch_id,
                round(source.height, 6),
                round(source.start, 6),
                source.operation,
                tuple(tuple(loop) for loop in source.profiles),
                tuple(
                    tuple(tuple(loop) for loop in region)
                    for region in source.regions
                ),
                tuple(tuple(loop) for loop in source.cuts),
                _sketch_signature(document, source.sketch_id),
            ))
        return tuple(parts)

    def remap_boolean_points(
        self,
        sketch_id: int,
        removed: int,
        edge_map: Dict[int, int],
    ) -> None:
        """Keep a stored boolean tool valid after a point is deleted."""
        changed = False
        for source in self.booleans:
            if source.sketch_id != sketch_id:
                continue
            source.profiles = _remap_loops(source.profiles, removed)
            source.regions = _remap_regions(source.regions, removed)
            source.cuts = _remap_loops(source.cuts, removed)
            changed = True
        if changed:
            self._boolean_state = None

    def remap_boolean_edges(self, sketch_id: int) -> None:
        """Force a boolean replay after a tool sketch loses an edge."""
        if any(
            source.sketch_id == sketch_id for source in self.booleans
        ):
            self._boolean_state = None

    def remap_point(self, removed: int, edge_map: Dict[int, int]) -> None:
        """Drop or shift feature references after one sketch point vanishes."""
        counts = (len(self.profiles), len(self.regions))
        self.profiles = _remap_loops(self.profiles, removed)
        self.regions = _remap_regions(self.regions, removed)
        self.cuts = _remap_loops(self.cuts, removed)
        if counts != (len(self.profiles), len(self.regions)):
            self.fallback = False
        fillets: List[Fillet] = []
        for fillet in self.fillets:
            if fillet.point is not None:
                if fillet.point == removed:
                    continue
                if fillet.point > removed:
                    fillet.point -= 1
            if fillet.edge is not None:
                mapped = edge_map.get(fillet.edge)
                if mapped is None:
                    continue
                fillet.edge = mapped
            fillets.append(fillet)
        self.fillets = fillets
        self._contact_face_cache = None

    def remap_edge(self, sketch: Sketch, removed: int) -> None:
        """Drop or shift cap fillets after one sketch edge vanishes."""
        fillets: List[Fillet] = []
        for fillet in self.fillets:
            if fillet.edge is not None:
                if fillet.edge == removed:
                    continue
                if fillet.edge > removed:
                    fillet.edge -= 1
            fillets.append(fillet)
        self.fillets = fillets
        self._prune_open_loops(sketch)
        self._contact_face_cache = None

    def _prune_open_loops(self, sketch: Sketch) -> None:
        """Drop profiles and regions whose boundary lost a sketch edge."""
        profiles = [
            loop for loop in self.profiles
            if sketch.loop_is_closed(loop)
        ]
        regions: List[List[List[int]]] = []
        for region in self.regions:
            if all(sketch.loop_is_closed(loop) for loop in region):
                regions.append(region)
        cuts = [
            loop for loop in self.cuts
            if sketch.loop_is_closed(loop)
        ]
        if (
            len(profiles) != len(self.profiles)
            or len(regions) != len(self.regions)
        ):
            self.fallback = False
        self.profiles = profiles
        self.regions = regions
        self.cuts = cuts


def _sketch_signature(
    document: "Document", sketch_id: int
) -> Optional[Tuple[object, ...]]:
    """Return a sketch's geometry and plane signature, or None if gone."""
    sketch = document.sketch(sketch_id)
    if sketch is None:
        return None
    return (
        tuple(tuple(axis) for axis in sketch.frame()),
        sketch.geometry_signature(),
    )


def _fillet_signature(fillet: Fillet) -> Tuple[object, ...]:
    """Return a hashable snapshot of one fillet."""
    return (
        fillet.kind,
        round(fillet.u, 6),
        round(fillet.v, 6),
        round(fillet.radius, 6),
    )


def _remap_loop(
    loop: Sequence[int], removed: int
) -> Optional[List[int]]:
    """Return a loop with shifted indices, or None if it lost a point."""
    if removed in loop:
        return None
    return [
        index - 1 if index > removed else index for index in loop
    ]


def _remap_loops(
    loops: Sequence[Sequence[int]], removed: int
) -> List[List[int]]:
    """Remap profile loops after one point is removed."""
    mapped: List[List[int]] = []
    for loop in loops:
        result = _remap_loop(loop, removed)
        if result is not None:
            mapped.append(result)
    return mapped


def _remap_regions(
    regions: Sequence[Sequence[Sequence[int]]], removed: int
) -> List[List[List[int]]]:
    """Remap arrangement regions, dropping any region that lost a point."""
    mapped: List[List[List[int]]] = []
    for region in regions:
        loops: List[List[int]] = []
        for loop in region:
            result = _remap_loop(loop, removed)
            if result is None:
                loops = []
                break
            loops.append(result)
        if loops:
            mapped.append(loops)
    return mapped
