"""Tests for the equal sketch constraint.

An equality links two lines (equal length) or two circles (equal diameter).
Two free lines meet in the middle, so both adopt the same length.
"""

from __future__ import annotations

from core.commands import AddEqualCommand, AddLineCommand

from .fixtures import new_sketch
from .harness import check

#: Floating-point slack when comparing measured geometry.
TOLERANCE = 1e-9


def test_equal_constraint_makes_two_lines_the_same_length() -> None:
    """Two lines linked by an equal constraint end up the same length."""
    document, sketch, stack = new_sketch()
    stack.execute(
        AddLineCommand(document, sketch, (0.0, 0.0), (10.0, 0.0))
    )
    stack.execute(
        AddLineCommand(document, sketch, (0.0, 5.0), (30.0, 5.0))
    )

    stack.execute(
        AddEqualCommand(document, sketch, ("line", 0), ("line", 1))
    )
    check(len(sketch.equals) == 1, "equal constraint was not recorded")

    first = sketch.edge_length(0)
    second = sketch.edge_length(1)
    check(
        first is not None and second is not None,
        "line length unavailable",
    )
    check(
        abs(first - second) <= TOLERANCE,
        f"lines are not equal: {first} vs {second}",
    )
