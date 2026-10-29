"""Undoable document editing commands."""

import copy
import math
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence, Tuple

from .booleans import OPERATION_LABELS, fillet_slices_body
from .document import Document
from .sketch import (
    Extrude,
    ExtrudeSlice,
    Fillet,
    Measurement,
    PlaneFrame,
    Point,
    Point3,
    ProjectedCircle,
    ProjectedEdge,
    ProjectedPoint,
    ProjectionSource,
    Sketch,
    aligned_edge_endpoint,
    normalize_edge_constraint,
    normalize_measurement_placement,
    normalize_measurement_value,
    normalize_plane,
)
from .projection import projected_point, projected_shape
from .solver.objects import circle2d, point2d


def _copy_points(points: List[Point]) -> List[Point]:
    """Return independent point objects for a command snapshot."""
    return [point2d(point) for point in points]


def _dot3(first: Sequence[float], second: Sequence[float]) -> float:
    """Return the dot product of two 3D vectors."""
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _cross3(first: Point3, second: Point3) -> Point3:
    """Return the cross product of two 3D vectors."""
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _unit3(vector: Point3) -> Optional[Point3]:
    """Return a unit vector, or None for a degenerate direction."""
    length = math.sqrt(_dot3(vector, vector))
    if length <= 1e-9:
        return None
    return (
        vector[0] / length,
        vector[1] / length,
        vector[2] / length,
    )


def _aligned_frame(
    frame: PlaneFrame, direction: Point3
) -> Optional[PlaneFrame]:
    """Return a frame whose local X axis follows ``direction``."""
    normal = _unit3(frame.normal)
    if normal is None:
        return None
    offset = _dot3(direction, normal)
    planar = (
        direction[0] - normal[0] * offset,
        direction[1] - normal[1] * offset,
        direction[2] - normal[2] * offset,
    )
    direction_length = math.sqrt(_dot3(direction, direction))
    planar_length = math.sqrt(_dot3(planar, planar))
    if planar_length <= 1e-6 * max(1.0, direction_length):
        return None
    u_axis = _unit3(planar)
    if u_axis is None:
        return None
    if _dot3(u_axis, frame.u) < 0.0:
        u_axis = (-u_axis[0], -u_axis[1], -u_axis[2])
    v_axis = _unit3(_cross3(normal, u_axis))
    if v_axis is None:
        return None
    u_axis = _unit3(_cross3(v_axis, normal))
    if u_axis is None:
        return None
    return PlaneFrame(
        frame.origin, u_axis, v_axis, normal, frame.label
    )


class Command(ABC):
    """Base class for an undoable edit."""

    kind: str = "action"
    timeline_visible: bool = True

    @property
    def label(self) -> str:
        """Human readable name shown in the timeline."""
        return self.kind.title()

    @property
    def sketch_id(self) -> Optional[int]:
        """Sketch this action belongs to, when applicable."""
        return None

    @abstractmethod
    def do(self) -> None:
        """Apply the edit."""

    @abstractmethod
    def undo(self) -> None:
        """Revert the edit."""


class AddSketchCommand(Command):
    """Create a new empty sketch."""

    kind = "sketch"

    def __init__(
        self,
        document: Document,
        plane: str = "XY",
        frame: Optional[PlaneFrame] = None,
        label: Optional[str] = None,
    ) -> None:
        self.document = document
        self.plane = normalize_plane(plane)
        self.frame = frame
        self.plane_label = label or (
            frame.label if frame is not None else None
        )
        self.sketch: Optional[Sketch] = None

    @property
    def label(self) -> str:
        return self.sketch.name if self.sketch is not None else "Sketch"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id if self.sketch is not None else None

    def do(self) -> None:
        if self.sketch is None:
            frame = self.frame
            self.sketch = Sketch(
                self.document.new_id(),
                self._next_name(),
                plane=self.plane,
                plane_label=self.plane_label if frame is not None else None,
                plane_origin=frame.origin if frame is not None else None,
                plane_u=frame.u if frame is not None else None,
                plane_v=frame.v if frame is not None else None,
                plane_normal=frame.normal if frame is not None else None,
            )
        if self.sketch not in self.document.sketches:
            self.document.sketches.append(self.sketch)
        self.document.dirty = True

    def undo(self) -> None:
        if self.sketch is not None and self.sketch in self.document.sketches:
            self.document.sketches.remove(self.sketch)
        self.document.dirty = True

    def _next_name(self) -> str:
        names = {sketch.name for sketch in self.document.sketches}
        index = 1
        while f"Sketch {index}" in names:
            index += 1
        return f"Sketch {index}"


class AlignSketchXCommand(Command):
    """Rotate a sketch's local X axis to follow an existing solid edge."""

    kind = "align_sketch_x"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        direction: Point3,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.before = (
            sketch.plane,
            sketch.plane_label,
            sketch.plane_origin,
            sketch.plane_u,
            sketch.plane_v,
            sketch.plane_normal,
        )
        self.display_label = sketch.display_plane
        self.frame = _aligned_frame(sketch.frame(), direction)

    @property
    def label(self) -> str:
        return "Align Sketch X"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    @property
    def is_valid(self) -> bool:
        """Return whether the picked direction lies in the sketch plane."""
        return self.frame is not None

    def do(self) -> None:
        if self.frame is None:
            return
        self.sketch.plane_label = self.display_label
        self.sketch.plane_origin = self.frame.origin
        self.sketch.plane_u = self.frame.u
        self.sketch.plane_v = self.frame.v
        self.sketch.plane_normal = self.frame.normal
        self.document.refresh_projections()
        self.document.dirty = True

    def undo(self) -> None:
        (
            self.sketch.plane,
            self.sketch.plane_label,
            self.sketch.plane_origin,
            self.sketch.plane_u,
            self.sketch.plane_v,
            self.sketch.plane_normal,
        ) = self.before
        self.document.refresh_projections()
        self.document.dirty = True


class AddPointCommand(Command):
    """Add a point to a sketch."""

    kind = "point"
    timeline_visible = False

    def __init__(self, document: Document, sketch: Sketch, point: Point) -> None:
        self.document = document
        self.sketch = sketch
        self.point = point2d(point)
        self.index: Optional[int] = None

    @property
    def label(self) -> str:
        return f"Point {self.point[0]:g}, {self.point[1]:g}"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        self.index = self.sketch.add_point(self.point)
        self.document.dirty = True

    def undo(self) -> None:
        if self.index is not None and 0 <= self.index < len(
            self.sketch.points
        ):
            edge_map = self.sketch.remove_point(self.index)
            self.document.remap_sketch_points(
                self.sketch, self.index, edge_map
            )
            self.document.recompute()
        self.document.dirty = True


class MovePointCommand(Command):
    """Move an existing sketch point and its axis-constrained neighbours."""

    kind = "move_point"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        index: int,
        point: Point,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.index = index
        self.point = point2d(point)
        self.previous_points: Optional[List[Point]] = None
        self.next_points: Optional[List[Point]] = None
        if 0 <= index < len(sketch.points):
            self.previous_points = _copy_points(sketch.points)
            next_points = _copy_points(sketch.points)
            next_points[index] = self.point
            sketch.constrain_axis_changes(next_points, [index])
            self.next_points = sketch.enforced_points(
                next_points
            )

    @property
    def label(self) -> str:
        return "Move Point"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self.next_points is None:
            return
        self.sketch.apply_point_positions(self.next_points)
        self.document.recompute()
        self.document.dirty = True

    def undo(self) -> None:
        if self.previous_points is None:
            return
        self.sketch.apply_point_positions(self.previous_points)
        self.document.recompute()
        self.document.dirty = True


class MoveEdgeCommand(Command):
    """Translate a sketch edge by moving both of its point entities."""

    kind = "move_edge"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        index: int,
        start: Point,
        end: Point,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.index = index
        self.start = point2d(start)
        self.end = point2d(end)
        self.previous_points: Optional[List[Point]] = None
        self.next_points: Optional[List[Point]] = None
        if 0 <= index < len(sketch.edges):
            first, second = sketch.edges[index]
            if (
                0 <= first < len(sketch.points)
                and 0 <= second < len(sketch.points)
            ):
                constraint = sketch.edge_constraint(index)
                aligned_end = aligned_edge_endpoint(
                    self.start, self.end, constraint
                )
                self.previous_points = _copy_points(sketch.points)
                next_points = _copy_points(sketch.points)
                next_points[first] = self.start
                next_points[second] = aligned_end
                sketch.constrain_axis_changes(
                    next_points, [first, second]
                )
                self.next_points = sketch.enforced_points(
                    next_points
                )

    @property
    def label(self) -> str:
        return "Move Edge"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self.next_points is None:
            return
        self.sketch.apply_point_positions(self.next_points)
        self.document.recompute()
        self.document.dirty = True

    def undo(self) -> None:
        if self.previous_points is None:
            return
        self.sketch.apply_point_positions(self.previous_points)
        self.document.recompute()
        self.document.dirty = True


class SetEdgeConstraintCommand(Command):
    """Apply or replace a horizontal or vertical edge constraint."""

    kind = "constraint"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        index: int,
        constraint: str,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.index = index
        self.constraint = normalize_edge_constraint(constraint)
        self.previous_constraint = sketch.edge_constraint(index)
        self.previous_points: Optional[List[Point]] = None
        self.next_points: Optional[List[Point]] = None
        if (
            self.constraint is not None
            and 0 <= index < len(sketch.edges)
        ):
            first, second = sketch.edges[index]
            if (
                0 <= first < len(sketch.points)
                and 0 <= second < len(sketch.points)
            ):
                self.previous_points = _copy_points(sketch.points)
                next_points = _copy_points(sketch.points)
                next_points[second] = aligned_edge_endpoint(
                    next_points[first],
                    next_points[second],
                    self.constraint,
                )
                sketch.constrain_axis_changes(
                    next_points,
                    [second],
                    [first, second],
                    excluded_edges=[index],
                )
                sketch.edge_constraints[index] = self.constraint
                try:
                    self.next_points = sketch.enforced_points(
                        next_points
                    )
                finally:
                    sketch.edge_constraints[index] = (
                        self.previous_constraint
                    )

    @property
    def label(self) -> str:
        return "Edge Constraint"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self.constraint is None or not 0 <= self.index < len(
            self.sketch.edges
        ):
            return
        if self.next_points is not None:
            self.sketch.apply_point_positions(self.next_points)
        self.sketch.edge_constraints[self.index] = self.constraint
        self.document.recompute()
        self.document.dirty = True

    def undo(self) -> None:
        if not 0 <= self.index < len(self.sketch.edges):
            return
        if self.previous_points is not None:
            self.sketch.apply_point_positions(self.previous_points)
        self.sketch.edge_constraints[self.index] = (
            self.previous_constraint
        )
        self.document.recompute()
        self.document.dirty = True


class AddMeasurementCommand(Command):
    """Add a persistent distance or angle annotation to a sketch."""

    kind = "measurement"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        measurement_kind: str,
        first: Tuple[str, int],
        second: Tuple[str, int],
        placement: Optional[float] = None,
        value: Optional[float] = None,
    ) -> None:
        self.document = document
        self.sketch = sketch
        normalized_value = normalize_measurement_value(value)
        if normalized_value is None:
            normalized_value = sketch.measurement_value(
                measurement_kind, first, second
            )
        self.measurement = Measurement(
            measurement_kind,
            first,
            second,
            normalize_measurement_placement(placement),
            normalized_value,
        )
        self.index: Optional[int] = None
        self.previous_points: Optional[List[Point]] = None
        self.next_points: Optional[List[Point]] = None
        self.has_applied = False

    @property
    def label(self) -> str:
        return "Measurement"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self.measurement.kind not in ("distance", "angle"):
            return
        for ref_kind, ref_index in (
            self.measurement.first, self.measurement.second
        ):
            limit = (
                len(self.sketch.points) if ref_kind == "point"
                else len(self.sketch.edges)
            )
            if ref_kind not in ("point", "line"):
                return
            if not 0 <= ref_index < limit:
                return
        if not self.has_applied:
            self.previous_points = _copy_points(self.sketch.points)
            self.has_applied = True
        if self.index is None:
            self.index = len(self.sketch.measurements)
        self.index = min(self.index, len(self.sketch.measurements))
        self.sketch.measurements.insert(self.index, self.measurement)
        if self.next_points is None:
            self.next_points = self.sketch.enforced_points(
                self.sketch.points
            )
        self.sketch.apply_point_positions(self.next_points)
        self.document.recompute()
        self.document.dirty = True

    def undo(self) -> None:
        if self.index is None:
            return
        if (
            self.index < len(self.sketch.measurements)
            and self.sketch.measurements[self.index] == self.measurement
        ):
            self.sketch.measurements.pop(self.index)
        else:
            try:
                self.sketch.measurements.remove(self.measurement)
            except ValueError:
                pass
        if self.previous_points is not None:
            self.sketch.apply_point_positions(self.previous_points)
        self.document.recompute()
        self.document.dirty = True


class SetMeasurementPlacementCommand(Command):
    """Move a measurement annotation without changing its geometry."""

    kind = "measurement_placement"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        index: int,
        placement: Optional[float],
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.index = index
        self.placement = normalize_measurement_placement(placement)
        self.previous: Optional[float] = None
        self.has_previous = False

    @property
    def label(self) -> str:
        return "Move Measurement"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def _replace(self, placement: Optional[float]) -> None:
        if not 0 <= self.index < len(self.sketch.measurements):
            return
        measurement = self.sketch.measurements[self.index]
        self.sketch.measurements[self.index] = Measurement(
            measurement.kind,
            measurement.first,
            measurement.second,
            placement,
            measurement.value,
        )
        self.document.dirty = True

    def do(self) -> None:
        if not 0 <= self.index < len(self.sketch.measurements):
            return
        if not self.has_previous:
            self.previous = self.sketch.measurements[
                self.index
            ].placement
            self.has_previous = True
        self._replace(self.placement)

    def undo(self) -> None:
        if not self.has_previous:
            return
        self._replace(self.previous)


class SetMeasurementValueCommand(Command):
    """Set the user-owned value of a measurement annotation."""

    kind = "measurement_value"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        index: int,
        value: Optional[float],
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.index = index
        self.value = normalize_measurement_value(value)
        self.previous: Optional[float] = None
        self.previous_points: Optional[List[Point]] = None
        self.next_points: Optional[List[Point]] = None
        self.has_previous = False
        self.has_applied = False

    @property
    def label(self) -> str:
        return "Edit Measurement"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def _replace(self, value: Optional[float]) -> None:
        if not 0 <= self.index < len(self.sketch.measurements):
            return
        measurement = self.sketch.measurements[self.index]
        self.sketch.measurements[self.index] = Measurement(
            measurement.kind,
            measurement.first,
            measurement.second,
            measurement.placement,
            value,
        )
        self.document.dirty = True

    def do(self) -> None:
        if (
            self.value is None
            or not 0 <= self.index < len(self.sketch.measurements)
        ):
            return
        measurement = self.sketch.measurements[self.index]
        if measurement.kind == "angle" and self.value > 180:
            return
        if not self.has_applied:
            self.previous = measurement.value
            self.previous_points = _copy_points(self.sketch.points)
            self.has_previous = True
            self.has_applied = True
            self._replace(self.value)
            next_points = _copy_points(self.sketch.points)
            self.sketch.enforce_measurements(next_points)
            self.next_points = next_points
        else:
            self._replace(self.value)
        if self.next_points is not None:
            self.sketch.apply_point_positions(self.next_points)
        self.document.recompute()
        self.document.dirty = True

    def undo(self) -> None:
        if not self.has_previous:
            return
        self._replace(self.previous)
        if self.previous_points is not None:
            self.sketch.apply_point_positions(self.previous_points)
        self.document.recompute()
        self.document.dirty = True


class AddLineCommand(Command):
    """Add a straight line segment to a sketch."""

    kind = "line"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        start: Point,
        end: Point,
        constraint: Optional[str] = None,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.start = point2d(start)
        self.constraint = normalize_edge_constraint(constraint)
        self.end = aligned_edge_endpoint(
            self.start, end, self.constraint
        )
        self.index: Optional[int] = None
        self.created_points: List[int] = []

    @property
    def label(self) -> str:
        return "Line"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def _ensure_point(self, point: Point) -> int:
        index = self.sketch.find_point(point)
        if index is not None:
            return index
        index = self.sketch.add_point(point)
        self.created_points.append(index)
        return index

    def do(self) -> None:
        self.created_points = []
        if self.start == self.end:
            return
        start_index = self._ensure_point(self.start)
        end_index = self._ensure_point(self.end)
        if start_index == end_index:
            return
        if self.index is None:
            self.index = len(self.sketch.edges)
        self.index = min(self.index, len(self.sketch.edges))
        self.sketch.edges.insert(
            self.index, (start_index, end_index)
        )
        self.sketch.edge_constraints.insert(
            self.index, self.constraint
        )
        self.sketch.edge_bulges.insert(self.index, None)
        self.document.dirty = True

    def undo(self) -> None:
        if (
            self.index is not None
            and self.index < len(self.sketch.edges)
        ):
            self.sketch.edges.pop(self.index)
            if self.index < len(self.sketch.edge_constraints):
                self.sketch.edge_constraints.pop(self.index)
            if self.index < len(self.sketch.edge_bulges):
                self.sketch.edge_bulges.pop(self.index)
        referenced = {
            index
            for edge in self.sketch.edges
            for index in edge
        }
        for index in sorted(self.created_points, reverse=True):
            if (
                index < len(self.sketch.points)
                and index not in referenced
            ):
                edge_map = self.sketch.remove_point(index)
                self.document.remap_sketch_points(
                    self.sketch, index, edge_map
                )
        self.created_points = []
        self.document.recompute()
        self.document.dirty = True


class AddRectangleCommand(Command):
    """Add a rectangle as four points and four axis-constrained edges."""

    kind = "rectangle"
    timeline_visible = False

    # Edge order walks the corners, so the alternating constraints keep the
    # two horizontal and two vertical sides locked to the sketch axes.
    CONSTRAINTS = ("horizontal", "vertical", "horizontal", "vertical")

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        first: Point,
        opposite: Point,
    ) -> None:
        self.document = document
        self.sketch = sketch
        start = point2d(first)
        end = point2d(opposite)
        self.corners = (
            start,
            point2d((end[0], start[1])),
            end,
            point2d((start[0], end[1])),
        )
        self.index: Optional[int] = None
        self.created_points: List[int] = []

    @property
    def label(self) -> str:
        return "Rectangle"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def _ensure_point(self, point: Point) -> int:
        index = self.sketch.find_point(point)
        if index is not None:
            return index
        index = self.sketch.add_point(point)
        self.created_points.append(index)
        return index

    def do(self) -> None:
        self.created_points = []
        if (
            self.corners[0] == self.corners[2]
            or self.corners[0][0] == self.corners[2][0]
            or self.corners[0][1] == self.corners[2][1]
        ):
            return
        indices = [self._ensure_point(point) for point in self.corners]
        if len(set(indices)) != 4:
            return
        if self.index is None:
            self.index = len(self.sketch.edges)
        self.index = min(self.index, len(self.sketch.edges))
        for offset in range(4):
            edge_index = self.index + offset
            self.sketch.edges.insert(
                edge_index,
                (indices[offset], indices[(offset + 1) % 4]),
            )
            self.sketch.edge_constraints.insert(
                edge_index, self.CONSTRAINTS[offset]
            )
            self.sketch.edge_bulges.insert(edge_index, None)
        self.document.dirty = True

    def undo(self) -> None:
        if self.index is not None:
            end = min(self.index + 4, len(self.sketch.edges))
            removed = end - self.index
            if removed > 0:
                del self.sketch.edges[self.index:end]
                constraint_end = min(
                    self.index + removed,
                    len(self.sketch.edge_constraints),
                )
                del self.sketch.edge_constraints[
                    self.index:constraint_end
                ]
                bulge_end = min(
                    self.index + removed,
                    len(self.sketch.edge_bulges),
                )
                del self.sketch.edge_bulges[self.index:bulge_end]
        referenced = {
            index
            for edge in self.sketch.edges
            for index in edge
        }
        for index in sorted(self.created_points, reverse=True):
            if (
                index < len(self.sketch.points)
                and index not in referenced
            ):
                edge_map = self.sketch.remove_point(index)
                self.document.remap_sketch_points(
                    self.sketch, index, edge_map
                )
        self.created_points = []
        self.document.recompute()
        self.document.dirty = True


class AddProjectionCommand(Command):
    """Project solid shapes into a sketch as linked exact geometry.

    A straight edge becomes a two-point line, a round fillet edge becomes a
    two-point arc with a bulge, and a circular body edge becomes a sketch
    circle.  Tessellated body chains only identify the shape; they are never
    copied into the sketch as geometry.
    """

    kind = "project"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        feature_id: int,
        points: Sequence[Point3] = (),
        chains: Sequence[Sequence[Point3]] = (),
        edge: Optional[Tuple[Sequence[float], Sequence[float]]] = None,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.feature_id = feature_id
        self.points = [tuple(map(float, point)) for point in points]
        self.chains = [
            [tuple(map(float, point)) for point in chain]
            for chain in chains
        ]
        self.edge = (
            None if edge is None else (
                tuple(map(float, edge[0])),
                tuple(map(float, edge[1])),
            )
        )
        self._before = None
        (
            self._plan_points,
            self._plan_segments,
            self._plan_circles,
        ) = self._build_plan()

    def _build_plan(
        self,
    ) -> Tuple[
        List[Tuple[ProjectionSource, Point]],
        List[Tuple[ProjectionSource, ProjectionSource, Optional[float]]],
        List[Tuple[ProjectionSource, int, float]],
    ]:
        """Collect exact shapes for every requested point and edge."""
        points: List[Tuple[ProjectionSource, Point]] = []
        segments: List[
            Tuple[ProjectionSource, ProjectionSource, Optional[float]]
        ] = []
        circles: List[Tuple[ProjectionSource, int, float]] = []
        seen_points: set = set()
        seen_segments: set = set()
        seen_circles: set = set()
        for world in self.points:
            planned = projected_point(
                self.document, self.sketch, self.feature_id, world
            )
            if planned is None or planned[0].key() in seen_points:
                continue
            seen_points.add(planned[0].key())
            points.append(planned)
        for chain in self.chains:
            edge = self.edge
            if edge is None:
                edge = (chain[0], chain[-1])
            plan = projected_shape(
                self.document, self.sketch, self.feature_id,
                chain, edge[0], edge[1],
            )
            for source, local in plan.points:
                if source.key() in seen_points:
                    continue
                seen_points.add(source.key())
                points.append((source, local))
            for start, end, bulge in plan.segments:
                pair = frozenset((start.key(), end.key()))
                if pair in seen_segments:
                    continue
                seen_segments.add(pair)
                segments.append((start, end, bulge))
            for center, source_circle, radius in plan.circles:
                key = _projected_circle_identity(
                    center, source_circle, radius
                )
                if key in seen_circles:
                    continue
                seen_circles.add(key)
                circles.append((center, source_circle, radius))
        return points, segments, circles

    @property
    def has_targets(self) -> bool:
        """Return whether the plan adds anything the sketch lacks."""
        existing_points = {
            link.source.key() for link in self.sketch.projected_points
        }
        existing_edges = {
            frozenset((link.start.key(), link.end.key()))
            for link in self.sketch.projected_edges
        }
        existing_circles = {
            _projected_circle_identity(
                link.center, link.source_circle, link.radius
            )
            for link in self.sketch.projected_circles
        }
        if any(
            source.key() not in existing_points
            for source, _ in self._plan_points
        ):
            return True
        if any(
            frozenset((start.key(), end.key())) not in existing_edges
            for start, end, _ in self._plan_segments
        ):
            return True
        return any(
            _projected_circle_identity(center, source_circle, radius)
            not in existing_circles
            for center, source_circle, radius in self._plan_circles
        )

    @property
    def label(self) -> str:
        count = len(self._plan_segments) + len(self._plan_circles)
        if count == 0:
            return "Project Point"
        if count == 1:
            if self._plan_circles:
                return "Project Circle"
            return "Project Edge"
        return f"Project {count} Edges"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        sketch = self.sketch
        if self._before is None:
            self._before = (
                len(sketch.points),
                len(sketch.edges),
                len(sketch.edge_constraints),
                len(sketch.edge_bulges),
                len(sketch.circles),
                len(sketch.projected_points),
                len(sketch.projected_edges),
                len(sketch.projected_circles),
            )
        points = self._add_points()
        self._add_segments(points)
        self._add_circles()
        self.document.dirty = True

    def _add_points(self) -> dict:
        """Add planned endpoints and return their source-to-index map."""
        sketch = self.sketch
        points = {
            link.source.key(): link.point
            for link in sketch.projected_points
            if 0 <= link.point < len(sketch.points)
        }
        for source, local in self._plan_points:
            key = source.key()
            if key in points:
                continue
            index = sketch.add_point(local)
            sketch.projected_points.append(ProjectedPoint(index, source))
            points[key] = index
        return points

    def _add_segments(self, points: dict) -> None:
        """Append exact lines and bulged arcs between planned points."""
        sketch = self.sketch
        sources = {source.key(): source for source, _ in self._plan_points}
        joined = {
            frozenset((link.start.key(), link.end.key()))
            for link in sketch.projected_edges
        }
        for start, end, bulge in self._plan_segments:
            first = points.get(start.key())
            second = points.get(end.key())
            if first is None or second is None or first == second:
                continue
            pair = frozenset((start.key(), end.key()))
            if pair in joined:
                continue
            if (first, second) in sketch.edges or (
                second, first
            ) in sketch.edges:
                continue
            index = len(sketch.edges)
            sketch.edges.append((first, second))
            sketch.edge_constraints.append(None)
            sketch.edge_bulges.append(bulge)
            sketch.projected_edges.append(ProjectedEdge(
                index, self.feature_id,
                sources[start.key()], sources[end.key()], bulge,
            ))
            joined.add(pair)

    def _add_circles(self) -> None:
        """Append each planned round edge as one real sketch circle."""
        sketch = self.sketch
        existing = {
            _projected_circle_identity(
                link.center, link.source_circle, link.radius
            )
            for link in sketch.projected_circles
        }
        for center, source_circle, radius in self._plan_circles:
            key = _projected_circle_identity(
                center, source_circle, radius
            )
            if key in existing or radius <= 0.0:
                continue
            sketch.add_circle((center.u, center.v), radius * 2.0)
            sketch.projected_circles.append(ProjectedCircle(
                len(sketch.circles) - 1, center, source_circle, radius
            ))
            existing.add(key)

    def undo(self) -> None:
        if self._before is None:
            return
        sketch = self.sketch
        (
            point_count, edge_count, constraint_count, bulge_count,
            circle_count, projected_point_count, projected_edge_count,
            projected_circle_count,
        ) = self._before
        del sketch.projected_circles[projected_circle_count:]
        del sketch.projected_edges[projected_edge_count:]
        del sketch.projected_points[projected_point_count:]
        if len(sketch.circles) > circle_count:
            del sketch.circles[circle_count:]
        if len(sketch.edges) > edge_count:
            del sketch.edges[edge_count:]
        if len(sketch.edge_constraints) > constraint_count:
            del sketch.edge_constraints[constraint_count:]
        if len(sketch.edge_bulges) > bulge_count:
            del sketch.edge_bulges[bulge_count:]
        if len(sketch.points) > point_count:
            del sketch.points[point_count:]
        self.document.dirty = True


def _projected_circle_identity(
    center: ProjectionSource, source_circle: int, radius: float
) -> Tuple[object, ...]:
    """Return a stable dedupe key for projected circles."""
    if source_circle >= 0:
        return (center.key(), source_circle)
    return (center.key(), round(radius, 6))


class AddCircleCommand(Command):
    """Add a circle to a sketch."""

    kind = "circle"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        center: Point,
        diameter: float,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.center = point2d(center)
        self.diameter = float(diameter)
        self.index: Optional[int] = None
        self.circle: Optional[circle2d] = None
        self.created_points: List[int] = []

    @property
    def label(self) -> str:
        return "Circle"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        self.created_points = []
        if self.diameter <= 0:
            return
        center_index = self.sketch.point_index(self.center)
        if center_index is not None and any(
            circle.midPoint is self.sketch.points[center_index]
            for circle in self.sketch.circles
        ):
            # Concentric circles need distinct midpoint points so each closed
            # loop can be identified by its point index.
            center_index = None
        if center_index is None:
            center_index = self.sketch.add_point(self.center)
            self.created_points.append(center_index)
        self.circle = circle2d(
            self.sketch.points[center_index], self.diameter
        )
        if self.index is None:
            self.index = len(self.sketch.circles)
        self.index = min(self.index, len(self.sketch.circles))
        self.sketch.circles.insert(self.index, self.circle)
        self.document.dirty = True

    def undo(self) -> None:
        if self.circle is None:
            return
        if (
            self.index is not None
            and 0 <= self.index < len(self.sketch.circles)
            and self.sketch.circles[self.index] is self.circle
        ):
            self.sketch.circles.pop(self.index)
        elif self.circle in self.sketch.circles:
            self.sketch.circles.remove(self.circle)
        referenced = {
            index
            for edge in self.sketch.edges
            for index in edge
        }
        for index in sorted(self.created_points, reverse=True):
            if not 0 <= index < len(self.sketch.points):
                continue
            point = self.sketch.points[index]
            if index in referenced:
                continue
            if any(
                circle.midPoint is point
                for circle in self.sketch.circles
            ):
                continue
            edge_map = self.sketch.remove_point(index)
            self.document.remap_sketch_points(
                self.sketch, index, edge_map
            )
        self.created_points = []
        self.document.recompute()
        self.document.dirty = True


class DeleteSketchEntitiesCommand(Command):
    """Delete points, edges or closed loops from a sketch.

    Deletion can remove several edges and points at once, so the command
    keeps one snapshot of the sketch state instead of trying to replay each
    individual removal in reverse.
    """

    kind = "delete"
    timeline_visible = False

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        entity: Optional[Tuple[str, int]] = None,
        loops: Optional[List[List[int]]] = None,
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.entity = entity
        self.loops = [list(loop) for loop in (loops or [])]
        self._before = None
        self._before_features = None
        self.edge_indices: List[int] = []
        self.point_indices: List[int] = []
        self._plan()

    def _plan(self) -> None:
        """Work out which edges and points the selection covers."""
        sketch = self.sketch
        edges = set()
        points = set()
        candidates = set()

        if self.entity is not None:
            kind, index = self.entity
            if kind == "point" and 0 <= index < len(sketch.points):
                points.add(index)
            elif kind == "line" and 0 <= index < len(sketch.edges):
                edges.add(index)
                candidates.update(sketch.edges[index])

        for loop in self.loops:
            if not loop:
                continue
            circle = sketch.circle_for_loop(loop)
            if circle is not None:
                midpoint = sketch.point_index(circle.midPoint)
                if midpoint is not None:
                    points.add(midpoint)
                continue
            following = loop[1:] + loop[:1]
            for first, second in zip(loop, following):
                if first == second:
                    continue
                for edge_index, (start, end) in enumerate(sketch.edges):
                    if edge_index in edges:
                        continue
                    if (
                        (start == first and end == second)
                        or (start == second and end == first)
                    ):
                        edges.add(edge_index)
                        break
            candidates.update(loop)

        edges = {
            index for index in edges if 0 <= index < len(sketch.edges)
        }
        points = {
            index for index in points if 0 <= index < len(sketch.points)
        }
        candidates = {
            index
            for index in candidates
            if 0 <= index < len(sketch.points)
        }

        # Endpoints that no surviving edge or circle uses disappear with the
        # geometry that owned them.  A free point elsewhere is untouched.
        remaining = [
            edge
            for index, edge in enumerate(sketch.edges)
            if index not in edges
        ]
        used = {index for edge in remaining for index in edge}
        for circle in sketch.circles:
            midpoint = sketch.point_index(circle.midPoint)
            if midpoint is not None and midpoint not in points:
                used.add(midpoint)
        points |= candidates - used - points

        self.edge_indices = sorted(edges)
        self.point_indices = sorted(points)

    @property
    def has_targets(self) -> bool:
        return bool(self.edge_indices or self.point_indices)

    @property
    def label(self) -> str:
        return "Delete"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self._before is None:
            self._before = copy.deepcopy((
                self.sketch.points,
                self.sketch.edges,
                self.sketch.edge_constraints,
                self.sketch.edge_bulges,
                self.sketch.circles,
                self.sketch.measurements,
                self.sketch.projected_points,
                self.sketch.projected_edges,
                self.sketch.projected_circles,
            ))
            self._before_features = [
                (
                    feature,
                    copy.deepcopy(feature.profiles),
                    copy.deepcopy(feature.regions),
                    copy.deepcopy(feature.cuts),
                    copy.deepcopy(feature.fillets),
                    feature.fallback,
                )
                for feature in self.document.features_for_sketch(
                    self.sketch
                )
            ]
        for index in sorted(self.edge_indices, reverse=True):
            self.sketch.remove_edge(index)
            self.document.remap_sketch_edges(self.sketch, index)
        for index in sorted(self.point_indices, reverse=True):
            edge_map = self.sketch.remove_point(index)
            self.document.remap_sketch_points(
                self.sketch, index, edge_map
            )
        self.document.recompute()
        self.document.dirty = True

    def undo(self) -> None:
        if self._before is None:
            return
        (
            points, edges, constraints, bulges, circles, measurements,
            projected_points, projected_edges, projected_circles,
        ) = copy.deepcopy(self._before)
        self.sketch.points = points
        self.sketch.edges = edges
        self.sketch.edge_constraints = constraints
        self.sketch.edge_bulges = bulges
        self.sketch.circles = circles
        self.sketch.measurements = measurements
        self.sketch.projected_points = projected_points
        self.sketch.projected_edges = projected_edges
        self.sketch.projected_circles = projected_circles
        for feature, profiles, regions, cuts, fillets, fallback in (
            self._before_features or []
        ):
            feature.profiles = copy.deepcopy(profiles)
            feature.regions = copy.deepcopy(regions)
            feature.cuts = copy.deepcopy(cuts)
            feature.fillets = copy.deepcopy(fillets)
            feature.fallback = fallback
        self.document.recompute()
        self.document.dirty = True


class AddExtrudeCommand(Command):
    """Extrude one or more selected sketch faces into a solid feature."""

    kind = "extrude"

    def __init__(
        self,
        document: Document,
        sketch: Sketch,
        height: float = 20.0,
        profiles: Optional[List[List[int]]] = None,
        cuts: Optional[List[List[int]]] = None,
        regions: Optional[List[List[List[int]]]] = None,
        start: float = 0.0,
        operation: str = "new_body",
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.height = height
        self.start = start
        self.operation = operation
        if profiles is None and regions is None:
            profiles = [sketch.profile_indices()]
        self.profiles = [
            list(profile)
            for profile in (profiles or [])
            if len(sketch.loop_points(profile)) >= 3
        ]
        self.cuts = [
            list(cut)
            for cut in (cuts or [])
            if len(sketch.loop_points(cut)) >= 3
        ]
        self.regions: List[List[List[int]]] = []
        for region in regions or []:
            loops = [
                list(loop)
                for loop in region
                if len(sketch.loop_points(loop)) >= 3
            ]
            if loops:
                self.regions.append(loops)
        self.feature: Optional[Extrude] = None

    @property
    def label(self) -> str:
        return self.feature.name if self.feature is not None else "Extrude"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if not self.profiles and not self.regions:
            return
        if self.feature is None:
            self.feature = Extrude(
                self.document.new_id(),
                self._next_name(),
                self.sketch.id,
                self.height,
                [list(profile) for profile in self.profiles],
                [list(cut) for cut in self.cuts],
                [
                    [list(loop) for loop in region]
                    for region in self.regions
                ],
                start=self.start,
                operation=self.operation,
            )
        if self.feature not in self.document.features:
            self.document.features.append(self.feature)
        self.document.dirty = True

    def undo(self) -> None:
        if self.feature is not None and self.feature in self.document.features:
            self.document.features.remove(self.feature)
        self.document.dirty = True

    def _next_name(self) -> str:
        names = {feature.name for feature in self.document.features}
        index = 1
        while f"Extrude {index}" in names:
            index += 1
        return f"Extrude {index}"


class BooleanExtrudeCommand(Command):
    """Replace a touched body with the result of a boolean extrusion."""

    kind = "extrude"

    def __init__(
        self,
        document: Document,
        target: Extrude,
        slices: List[ExtrudeSlice],
        operation: str,
    ) -> None:
        self.document = document
        self.target = target
        self.operation = operation
        self.slices = [
            ExtrudeSlice(
                entry.z0,
                entry.z1,
                [
                    [
                        [(float(x), float(y)) for x, y in loop]
                        for loop in group
                    ]
                    for group in entry.regions
                ],
                smooth_z0=entry.smooth_z0,
                smooth_z1=entry.smooth_z1,
            )
            for entry in slices
        ]
        self._before_slices: Optional[List[ExtrudeSlice]] = None
        self._before_operation: Optional[str] = None

    @property
    def label(self) -> str:
        name = OPERATION_LABELS.get(self.operation, self.operation)
        return f"{self.target.name} · {name}"

    def do(self) -> None:
        if self._before_slices is None:
            self._before_slices = copy.deepcopy(self.target.slices)
            self._before_operation = self.target.operation
        self.target.slices = copy.deepcopy(self.slices)
        self.target.operation = self.operation
        self.document.dirty = True

    def undo(self) -> None:
        if self._before_slices is not None:
            self.target.slices = copy.deepcopy(self._before_slices)
        if self._before_operation is not None:
            self.target.operation = self._before_operation
        self.document.dirty = True


class AddFilletCommand(Command):
    """Round one edge of an extruded solid."""

    kind = "fillet"

    def __init__(
        self,
        document: Document,
        feature: Extrude,
        kind: str,
        u: float,
        v: float,
        radius: float,
    ) -> None:
        self.document = document
        self.feature = feature
        self.fillet = Fillet(kind, float(u), float(v), float(radius))
        self._before_slices: Optional[List[ExtrudeSlice]] = None

    @property
    def label(self) -> str:
        return f"Fillet {self.fillet.radius:g} mm"

    def do(self) -> None:
        if self.feature.slices:
            # A cut or joined body keeps its slices as the source of truth,
            # so the rounding is baked into them instead of a prism profile.
            if self._before_slices is None:
                self._before_slices = copy.deepcopy(self.feature.slices)
            rounded = fillet_slices_body(
                self.feature.slices, self.fillet
            )
            if rounded is None:
                return
            self.feature.slices = rounded
        elif not any(
            entry is self.fillet for entry in self.feature.fillets
        ):
            sketch = self.document.sketch(self.feature.sketch_id)
            if sketch is not None:
                self.fillet.bind(sketch)
            self.feature.fillets.append(self.fillet)
        self.document.recompute()
        self.document.dirty = True

    def undo(self) -> None:
        if self._before_slices is not None:
            self.feature.slices = copy.deepcopy(self._before_slices)
        self.feature.fillets[:] = [
            entry
            for entry in self.feature.fillets
            if entry is not self.fillet
        ]
        self.document.recompute()
        self.document.dirty = True


class CompositeCommand(Command):
    """Run several edits as a single undoable action."""

    def __init__(
        self,
        commands: Sequence[Command],
        label: Optional[str] = None,
    ) -> None:
        self.commands = list(commands)
        self._label = label

    @property
    def kind(self) -> str:
        return self.commands[0].kind if self.commands else "action"

    @property
    def label(self) -> str:
        if self._label is not None:
            return self._label
        if len(self.commands) == 1:
            return self.commands[0].label
        return f"{self.kind.title()} ({len(self.commands)} changes)"

    @property
    def sketch_id(self) -> Optional[int]:
        ids = {command.sketch_id for command in self.commands}
        return ids.pop() if len(ids) == 1 else None

    @property
    def timeline_visible(self) -> bool:
        return any(command.timeline_visible for command in self.commands)

    def do(self) -> None:
        for command in self.commands:
            command.do()

    def undo(self) -> None:
        for command in reversed(self.commands):
            command.undo()


class CommandStack:
    """Undo and redo stacks for one document."""

    def __init__(self) -> None:
        self._undo: List[Command] = []
        self._redo: List[Command] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def position(self) -> int:
        """Number of applied actions; the timeline roll marker."""
        return len(self._undo)

    def history(self) -> List[Command]:
        """All actions in chronological order, including undone ones."""
        return list(self._undo) + list(reversed(self._redo))

    def execute(self, command: Command) -> None:
        command.do()
        self._undo.append(command)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        command = self._redo.pop()
        command.do()
        self._undo.append(command)
        return True

    def jump_to(self, position: int) -> None:
        """Roll the history marker to a number of applied actions."""
        target = max(0, min(len(self.history()), position))
        while len(self._undo) > target:
            self.undo()
        while len(self._undo) < target and self._redo:
            self.redo()

    def remove_at(self, index: int) -> Optional[int]:
        """Delete an action and rebuild the document from the remaining ones.

        Deleting a sketch also removes every action that belongs to it, since
        sketch geometry and features cannot exist without their sketch.
        Returns the new roll-marker position, or ``None`` when the index is
        invalid.
        """
        history = self.history()
        if not 0 <= index < len(history):
            return None

        removed = {index}
        target = history[index]
        if target.kind == "sketch" and target.sketch_id is not None:
            sketch_id = target.sketch_id
            for position, command in enumerate(history):
                if command.sketch_id == sketch_id:
                    removed.add(position)

        old_position = self.position
        removed_applied = sum(1 for position in removed if position < old_position)
        kept = [command for position, command in enumerate(history) if position not in removed]

        # Rebuild from a clean document so index-based point commands and
        # feature dependencies stay consistent after the deletion.
        while self._undo:
            self.undo()
        self._undo.clear()
        self._redo.clear()
        for command in kept:
            command.do()
            self._undo.append(command)

        new_position = max(0, min(len(kept), old_position - removed_applied))
        self.jump_to(new_position)
        return new_position
