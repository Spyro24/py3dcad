"""Tests for the coincident sketch constraint.

A coincidence links two points.  The first point is the anchor: it can be
moved and the second point follows it.  The second point cannot be moved on
its own; dragging it snaps it back onto the anchor.
"""

from __future__ import annotations

from typing import Tuple

from core.commands import (
    AddCoincidentCommand,
    AddPointCommand,
    CommandStack,
    MovePointCommand,
)
from core.document import Document
from core.sketch import Sketch

from .harness import check


def _new_sketch() -> Tuple[Document, Sketch, CommandStack]:
    """Return a document with one empty sketch and its command stack."""
    document = Document(id=1)
    sketch = Sketch(id=1, name="Sketch1")
    document.sketches.append(sketch)
    document.active_sketch_id = sketch.id
    return document, sketch, CommandStack()


def test_coincident_second_point_follows_the_first() -> None:
    """Only the first point moves; the coincident second point follows it."""
    document, sketch, stack = _new_sketch()
    stack.execute(AddPointCommand(document, sketch, (0.0, 0.0)))  # p1
    stack.execute(AddPointCommand(document, sketch, (5.0, 5.0)))  # p2

    # p1 anchors the coincidence, so p2 is pulled onto it immediately.
    stack.execute(
        AddCoincidentCommand(document, sketch, ("point", 0), ("point", 1))
    )
    check(
        sketch.points[0] == sketch.points[1],
        "coincidence did not bring p2 onto p1",
    )

    # Moving p1 carries p2 along.
    stack.execute(MovePointCommand(document, sketch, 0, (10.0, 10.0)))
    check(
        sketch.points[0] == (10.0, 10.0),
        f"p1 did not move: {tuple(sketch.points[0])}",
    )
    check(
        sketch.points[1] == sketch.points[0],
        f"p2 did not follow p1: {tuple(sketch.points[1])}",
    )


def test_coincident_follower_cannot_move_the_anchor() -> None:
    """Moving p2 must not move p1, and p2 stays fixed to p1."""
    document, sketch, stack = _new_sketch()
    stack.execute(AddPointCommand(document, sketch, (0.0, 0.0)))  # p1
    stack.execute(AddPointCommand(document, sketch, (5.0, 5.0)))  # p2

    # p1 anchors the coincidence; p2 is the follower.
    stack.execute(
        AddCoincidentCommand(document, sketch, ("point", 0), ("point", 1))
    )
    anchor_before = tuple(sketch.points[0])

    # Drag p2 away; it must snap back and leave p1 untouched.
    stack.execute(MovePointCommand(document, sketch, 1, (99.0, 99.0)))
    check(
        tuple(sketch.points[0]) == anchor_before,
        f"p1 moved while dragging p2: {tuple(sketch.points[0])}",
    )
    check(
        sketch.points[1] == sketch.points[0],
        f"p2 left p1: {tuple(sketch.points[1])}",
    )
