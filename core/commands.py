"""Undoable document editing commands."""

from abc import ABC, abstractmethod
from typing import List, Optional

from .document import Document
from .sketch import Extrude, PlaneFrame, Point, Sketch, normalize_plane


class Command(ABC):
    """Base class for an undoable edit."""

    kind: str = "action"

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
        if self.index is None:
            self.index = len(self.sketch.points)
        self.index = min(self.index, len(self.sketch.points))
        self.sketch.points.insert(self.index, self.point)
        self.document.dirty = True

    def undo(self) -> None:
        if self.index is not None and self.index < len(self.sketch.points):
            self.sketch.points.pop(self.index)
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
        points and extrusions cannot exist without their sketch.  Returns the
        new roll-marker position, or ``None`` when the index is invalid.
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
