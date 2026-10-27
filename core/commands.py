"""Undoable document editing commands."""

import copy
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from .booleans import OPERATION_LABELS, fillet_slices_body
from .document import Document
from .sketch import (
    Extrude,
    ExtrudeSlice,
    Fillet,
    Measurement,
    PlaneFrame,
    Point,
    Sketch,
    aligned_edge_endpoint,
    normalize_edge_constraint,
    normalize_measurement_placement,
    normalize_measurement_value,
    normalize_plane,
)
from .solver.objects import circle2d, point2d


def _copy_points(points: List[Point]) -> List[Point]:
    """Return independent point objects for a command snapshot."""
    return [point2d(point) for point in points]


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
        if self.index is not None:
            self.sketch.remove_point(self.index)
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
        self.document.dirty = True

    def undo(self) -> None:
        if self.previous_points is None:
            return
        self.sketch.apply_point_positions(self.previous_points)
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
        self.document.dirty = True

    def undo(self) -> None:
        if self.previous_points is None:
            return
        self.sketch.apply_point_positions(self.previous_points)
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
        self.document.dirty = True

    def undo(self) -> None:
        if not 0 <= self.index < len(self.sketch.edges):
            return
        if self.previous_points is not None:
            self.sketch.apply_point_positions(self.previous_points)
        self.sketch.edge_constraints[self.index] = (
            self.previous_constraint
        )
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
        self.document.dirty = True

    def undo(self) -> None:
        if not self.has_previous:
            return
        self._replace(self.previous)
        if self.previous_points is not None:
            self.sketch.apply_point_positions(self.previous_points)
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
        self.document.dirty = True

    def undo(self) -> None:
        if (
            self.index is not None
            and self.index < len(self.sketch.edges)
        ):
            self.sketch.edges.pop(self.index)
            if self.index < len(self.sketch.edge_constraints):
                self.sketch.edge_constraints.pop(self.index)
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
                self.sketch.remove_point(index)
        self.created_points = []
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
                self.sketch.remove_point(index)
        self.created_points = []
        self.document.dirty = True


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
            self.sketch.remove_point(index)
        self.created_points = []
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
                self.sketch.circles,
                self.sketch.measurements,
            ))
        for index in sorted(self.edge_indices, reverse=True):
            self.sketch.remove_edge(index)
        for index in sorted(self.point_indices, reverse=True):
            self.sketch.remove_point(index)
        self.document.dirty = True

    def undo(self) -> None:
        if self._before is None:
            return
        (
            points, edges, constraints, circles, measurements
        ) = copy.deepcopy(self._before)
        self.sketch.points = points
        self.sketch.edges = edges
        self.sketch.edge_constraints = constraints
        self.sketch.circles = circles
        self.sketch.measurements = measurements
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
            self.feature.fillets.append(self.fillet)
        self.document.dirty = True

    def undo(self) -> None:
        if self._before_slices is not None:
            self.feature.slices = copy.deepcopy(self._before_slices)
        self.feature.fillets[:] = [
            entry
            for entry in self.feature.fillets
            if entry is not self.fillet
        ]
        self.document.dirty = True


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
