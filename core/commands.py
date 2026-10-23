"""Undoable document editing commands."""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from .document import Document
from .sketch import (
    Extrude,
    Measurement,
    PlaneFrame,
    Point,
    Sketch,
    aligned_edge_endpoint,
    normalize_edge_constraint,
    normalize_plane,
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


class AddPointCommand(Command):
    """Add a point to a sketch."""

    kind = "point"
    timeline_visible = False

    def __init__(self, document: Document, sketch: Sketch, point: Point) -> None:
        self.document = document
        self.sketch = sketch
        self.point = point
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
        self.point = point
        self.previous_points: Optional[List[Point]] = None
        self.next_points: Optional[List[Point]] = None
        if 0 <= index < len(sketch.points):
            self.previous_points = list(sketch.points)
            next_points = list(sketch.points)
            next_points[index] = point
            sketch.constrain_axis_changes(next_points, [index])
            self.next_points = next_points

    @property
    def label(self) -> str:
        return "Move Point"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self.next_points is None:
            return
        self.sketch.points[:] = self.next_points
        self.document.dirty = True

    def undo(self) -> None:
        if self.previous_points is None:
            return
        self.sketch.points[:] = self.previous_points
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
        self.start = start
        self.end = end
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
                    start, end, constraint
                )
                self.previous_points = list(sketch.points)
                next_points = list(sketch.points)
                next_points[first] = start
                next_points[second] = aligned_end
                sketch.constrain_axis_changes(
                    next_points, [first, second]
                )
                self.next_points = next_points

    @property
    def label(self) -> str:
        return "Move Edge"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self.next_points is None:
            return
        self.sketch.points[:] = self.next_points
        self.document.dirty = True

    def undo(self) -> None:
        if self.previous_points is None:
            return
        self.sketch.points[:] = self.previous_points
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
                self.previous_points = list(sketch.points)
                next_points = list(sketch.points)
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
                self.next_points = next_points

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
            self.sketch.points[:] = self.next_points
        self.sketch.edge_constraints[self.index] = self.constraint
        self.document.dirty = True

    def undo(self) -> None:
        if not 0 <= self.index < len(self.sketch.edges):
            return
        if self.previous_points is not None:
            self.sketch.points[:] = self.previous_points
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
    ) -> None:
        self.document = document
        self.sketch = sketch
        self.measurement = Measurement(
            measurement_kind, first, second
        )
        self.index: Optional[int] = None

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
        if self.index is None:
            self.index = len(self.sketch.measurements)
        self.index = min(self.index, len(self.sketch.measurements))
        self.sketch.measurements.insert(self.index, self.measurement)
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
        self.start = start
        self.constraint = normalize_edge_constraint(constraint)
        self.end = aligned_edge_endpoint(
            start, end, self.constraint
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


class AddExtrudeCommand(Command):
    """Extrude a sketch into a solid feature."""

    kind = "extrude"

    def __init__(self, document: Document, sketch: Sketch, height: float = 20.0) -> None:
        self.document = document
        self.sketch = sketch
        self.height = height
        self.feature: Optional[Extrude] = None

    @property
    def label(self) -> str:
        return self.feature.name if self.feature is not None else "Extrude"

    @property
    def sketch_id(self) -> Optional[int]:
        return self.sketch.id

    def do(self) -> None:
        if self.feature is None:
            self.feature = Extrude(
                self.document.new_id(), self._next_name(), self.sketch.id, self.height
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
