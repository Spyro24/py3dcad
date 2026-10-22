"""Sketch and feature models for PY3DCAD."""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

Point = Tuple[float, float]
Point3 = Tuple[float, float, float]

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

    def __post_init__(self) -> None:
        self.edges = [
            (start, end)
            for start, end in self.edges
            if (
                0 <= start < len(self.points)
                and 0 <= end < len(self.points)
                and start != end
            )
        ]

    @property
    def lines(self) -> List[Tuple[Point, Point]]:
        """Return edge endpoints as coordinate pairs."""
        return [
            (self.points[start], self.points[end])
            for start, end in self.edges
        ]

    def profile_indices(self) -> List[int]:
        """Return a simple closed edge loop, or an empty list."""
        if len(self.edges) < 3:
            return []
        adjacency: Dict[int, List[int]] = {}
        for start, end in self.edges:
            adjacency.setdefault(start, []).append(end)
            adjacency.setdefault(end, []).append(start)

        seen: set[int] = set()
        for start in adjacency:
            if start in seen:
                continue
            component = self._graph_component(start, adjacency, seen)
            if len(component) < 3:
                continue
            if any(len(adjacency[node]) != 2 for node in component):
                continue
            loop = self._trace_cycle(start, adjacency)
            if len(loop) == len(component) and len(loop) >= 3:
                return loop
        return []

    @staticmethod
    def _graph_component(
        start: int,
        adjacency: Dict[int, List[int]],
        seen: set[int],
    ) -> List[int]:
        component: List[int] = []
        stack = [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        return component

    @staticmethod
    def _trace_cycle(
        start: int, adjacency: Dict[int, List[int]]
    ) -> List[int]:
        loop = [start]
        previous: Optional[int] = None
        current = start
        while True:
            neighbors = adjacency[current]
            nxt = (
                neighbors[0]
                if neighbors[0] != previous
                else neighbors[1]
            )
            if nxt == start:
                break
            if nxt in loop:
                return []
            loop.append(nxt)
            previous, current = current, nxt
        return loop

    def profile_points(self) -> List[Point]:
        """Return the ordered points of the extrudable edge loop."""
        return [
            self.points[index] for index in self.profile_indices()
        ]

    def find_point(self, point: Point) -> Optional[int]:
        """Find an existing point by its coordinates."""
        for index, existing in enumerate(self.points):
            if existing == point:
                return index
        return None

    def add_point(self, point: Point) -> int:
        """Append a standalone point."""
        index = len(self.points)
        self.points.append(point)
        return index

    def remove_point(self, index: int) -> None:
        """Remove a point and any edges that referenced it."""
        if not 0 <= index < len(self.points):
            return
        self.points.pop(index)
        shifted: List[Tuple[int, int]] = []
        for start, end in self.edges:
            if start == index or end == index:
                continue
            shifted.append((
                start if start < index else start - 1,
                end if end < index else end - 1,
            ))
        self.edges = shifted

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
        raw_edges = data.get("edges")
        raw_profile = data.get("profile")
        if isinstance(raw_edges, (list, tuple)):
            for raw in raw_edges:
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
        points.append(point)
        return len(points) - 1


@dataclass
class Extrude:
    """A prism created by extruding a closed sketch along its normal."""

    id: int
    name: str
    sketch_id: int
    height: float = 20.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "extrude",
            "name": self.name,
            "sketch": self.sketch_id,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Extrude":
        return cls(
            id=int(data.get("id", 0)),
            name=str(data.get("name", "Extrude")),
            sketch_id=int(data.get("sketch", 0)),
            height=float(data.get("height", 20.0)),
        )
