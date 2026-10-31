"""Tests for switching workspaces from the toolbar selector."""

from __future__ import annotations

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from core.ui.layout import Rect
from core.ui.workspace import Workspace

from .harness import check


def _new_workspace() -> Workspace:
    """Return a workspace with no-op callbacks for selector tests."""
    noop = lambda *args, **kwargs: None  # noqa: E731
    return Workspace(
        on_new_sketch=noop,
        on_extrude=noop,
        on_add_point=noop,
        on_add_line=noop,
        on_add_circle=noop,
        on_add_rectangle=noop,
        on_move_point=noop,
        on_move_edge=noop,
        on_set_edge_constraint=noop,
        on_add_coincident=noop,
        on_select_sketch=noop,
        on_history_jump=noop,
        on_history_delete=noop,
        on_history_play=noop,
    )


def test_workspace_selector_lists_printing_workspace() -> None:
    """The selector offers both the design and printing workspaces."""
    workspace = _new_workspace()
    keys = [key for key, _ in workspace.WORKSPACE_MENU_ITEMS]

    check(Workspace.DESIGN_WORKSPACE in keys, "design is missing")
    check(Workspace.PRINTING_WORKSPACE in keys, "printing is missing")


def test_workspace_selector_switches_to_printing() -> None:
    """Selecting printing shows its UI and returning restores design."""
    workspace = _new_workspace()

    check(
        workspace.active_workspace == Workspace.DESIGN_WORKSPACE,
        "design should be the initial workspace",
    )
    check(
        workspace.set_workspace(Workspace.PRINTING_WORKSPACE),
        "printing workspace was rejected",
    )
    check(
        workspace.active_workspace == Workspace.PRINTING_WORKSPACE,
        "printing was not activated",
    )
    check(
        workspace.printing_ui.visible,
        "printing UI stayed hidden",
    )
    check(
        workspace.set_workspace(Workspace.DESIGN_WORKSPACE),
        "design workspace was rejected",
    )
    check(
        workspace.active_workspace == Workspace.DESIGN_WORKSPACE,
        "design was not restored",
    )
    check(
        not workspace.printing_ui.visible,
        "printing UI stayed visible",
    )
    check(
        not workspace.set_workspace("UNKNOWN"),
        "unknown workspace should be rejected",
    )


def test_workspace_selector_menu_has_a_row_per_workspace() -> None:
    """The dropdown lays out one clickable row for each workspace."""
    workspace = _new_workspace()
    toolbar = Rect(0, 36, 1280, 104)

    _, rows, selector = workspace._workspace_menu_geometry(toolbar)

    check(
        len(rows) == len(workspace.WORKSPACE_MENU_ITEMS),
        "menu row count does not match workspace count",
    )
    check(selector.w > 0, "workspace selector has no width")
