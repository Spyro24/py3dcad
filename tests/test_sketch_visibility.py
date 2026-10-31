"""Tests for sketch visibility and post-edit sketch selection."""

from __future__ import annotations

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from core.commands import CommandStack, SetSketchVisibilityCommand
from core.document import Document
from core.render.scene import SceneRenderer
from core.sketch import Extrude, Sketch
from core.ui.layout import Rect, UILayout
from core.ui.workspace import Workspace

from .harness import check


def _document() -> Document:
    """Return a document with one visible and one hidden sketch."""
    document = Document(id=1)
    document.sketches = [
        Sketch(id=1, name="Sketch1", visible=True),
        Sketch(id=2, name="Sketch2", visible=False),
    ]
    return document


def _new_workspace(on_select=None, on_edit=None, on_visibility=None) -> Workspace:
    """Return a workspace with small recording callbacks for tree tests."""
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
        on_select_sketch=on_select or noop,
        on_history_jump=noop,
        on_history_delete=noop,
        on_history_play=noop,
        on_edit_sketch=on_edit,
        on_set_sketch_visibility=on_visibility,
    )


def test_sketch_visibility_defaults_to_visible() -> None:
    """New sketches are visible unless a document hides them."""
    check(Sketch(id=1, name="Sketch").visible, "new sketch should be visible")
    loaded = Sketch.from_dict({"id": 2, "name": "Old"})
    check(loaded.visible, "older sketches should load as visible")


def test_sketch_visibility_round_trips() -> None:
    """The visibility flag survives saving and loading."""
    sketch = Sketch(id=1, name="Hidden", visible=False)
    data = sketch.to_dict()

    check(data["visible"] is False, "visibility was not saved")
    check(not Sketch.from_dict(data).visible, "visibility was not restored")


def test_document_select_sketch_is_not_active_edit() -> None:
    """A finished sketch can be selected while the editor stays closed."""
    document = _document()
    document.select_sketch(2)

    check(document.selected_sketch_id == 2, "sketch was not selected")
    check(document.selected_sketch is document.sketches[1], "wrong sketch")
    check(document.active_sketch_id is None, "selection opened the editor")
    check(not document.selected_faces, "face selection was kept")
    check(not document.selected_edges, "edge selection was kept")
    check(document.selected_plane is None, "plane selection was kept")


def test_other_selections_clear_the_selected_sketch() -> None:
    """Selecting solids or clearing the viewport drops the sketch selection."""
    document = _document()
    document.select_sketch(1)
    document.select_face((7, 0))
    check(document.selected_sketch_id is None, "face kept the sketch selected")

    document.select_sketch(1)
    document.clear_selection()
    check(document.selected_sketch_id is None, "clear left a sketch selected")


def test_visibility_toggle_is_undoable() -> None:
    """Hiding and showing a sketch goes through the command stack."""
    document = _document()
    stack = CommandStack()
    sketch = document.sketches[0]

    stack.execute(SetSketchVisibilityCommand(document, sketch, False))
    check(not sketch.visible, "sketch was not hidden")

    check(stack.undo(), "undo was rejected")
    check(sketch.visible, "undo did not show the sketch")


def test_scene_visibility_ignores_consumed_features() -> None:
    """Visible sketches render even after a feature consumes them."""
    document = _document()
    document.features.append(
        Extrude(id=1, name="Extrude1", sketch_id=1, height=10.0)
    )

    visible = {sketch.id for sketch in SceneRenderer._visible_sketches(document)}
    check(visible == {1}, "hidden sketch or consumed sketch was wrong")

    document.active_sketch_id = 2
    visible = {sketch.id for sketch in SceneRenderer._visible_sketches(document)}
    check(visible == {1, 2}, "active sketch should stay visible while edited")


def test_finishing_a_sketch_keeps_it_selected() -> None:
    """Finishing closes the editor but leaves the sketch selected for tools."""
    document = _document()
    document.active_sketch_id = 1
    workspace = _new_workspace()

    workspace._finish_sketch(document)

    check(document.active_sketch_id is None, "sketch editor stayed open")
    check(document.selected_sketch_id == 1, "finished sketch was not selected")


def test_tree_single_click_selects_and_eye_toggles() -> None:
    """A tree click selects; the eye toggles visibility without editing."""
    pygame.font.init()
    document = _document()
    selected = []
    visibility = []
    workspace = _new_workspace(
        on_select=selected.append,
        on_visibility=lambda sketch_id, visible: visibility.append(
            (sketch_id, visible)
        ),
    )
    layout = UILayout()
    layout.document_tree = Rect(0, 0, 280, 600)

    rows = workspace._tree_rows(layout.document_tree, document)
    row = next(rect for kind, item, rect in rows
               if kind == "sketch" and item == 1)
    click = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": row.center}
    )
    workspace.handle_event(click, layout, document, [], [], 0)
    check(selected == [1], "single click did not select the sketch")

    eye = workspace._sketch_eye_rect(row)
    click = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": eye.center}
    )
    workspace.handle_event(click, layout, document, [], [], 0)
    check(visibility == [(1, False)], "eye did not hide the sketch")
