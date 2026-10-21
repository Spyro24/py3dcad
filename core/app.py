"""Application shell for PY3DCAD."""

import json
from pathlib import Path
from typing import Dict, List, Optional

import pygame

from .commands import AddExtrudeCommand, AddPointCommand, AddSketchCommand, CommandStack
from .config import Config, format_opened
from .document import Document
from .faces import face_for_ref
from .sketch import Point
from .ui import (
    Window,
    UILayout,
    StartPage,
    RecentFile,
    TabBar,
    Workspace,
    SaveDialog,
    SettingsDialog,
    HistoryEntry,
)
from .ui.layout import Rect

SCALE_STEPS = (0.75, 0.875, 1.0, 1.125, 1.25, 1.5, 1.75, 2.0)


class Application:
    """Owns the window, documents, UI components and event loop."""

    def __init__(self, window: Window) -> None:
        self.window = window
        self.config = Config()

        self.layout = UILayout()
        self.start_page = StartPage(
            on_new_document=self.new_document,
            on_open_document=self.open_document,
            on_open_recent=self.open_recent,
            on_open_example=self.open_example,
        )
        self.tab_bar = TabBar(self.select_document, self.close_document)
        self.workspace = Workspace(
            on_new_sketch=self.new_sketch,
            on_extrude=self.extrude_active,
            on_add_point=self.add_point,
            on_select_sketch=self.select_sketch,
            on_history_jump=self.history_jump,
            on_history_delete=self.history_delete,
            on_history_play=self.toggle_playback,
            on_settings=self.open_settings,
        )
        self.save_dialog = SaveDialog(self._save_to)
        self.settings_dialog = SettingsDialog(self._set_orientation_cube)

        self.documents: List[Document] = []
        self.active_id: Optional[int] = None
        self._next_id = 1
        self._stacks: Dict[int, CommandStack] = {}
        self._playing = False
        self._play_accumulator = 0.0

        self._scale_index = self._nearest_scale_index(self.config.ui_scale)
        self._apply_scale(save=False)
        self.workspace.set_orientation_cube_visible(
            self.config.show_orientation_cube
        )
        self._refresh_recent()

    # ------------------------------------------------------------------
    # Scaling
    # ------------------------------------------------------------------

    @property
    def scale(self) -> float:
        return SCALE_STEPS[self._scale_index]

    @staticmethod
    def _nearest_scale_index(scale: float) -> int:
        return min(
            range(len(SCALE_STEPS)),
            key=lambda index: abs(SCALE_STEPS[index] - scale),
        )

    def _apply_scale(self, save: bool = True) -> None:
        scale = self.scale
        self.layout.set_scale(scale)
        self.start_page.set_scale(scale)
        self.tab_bar.set_scale(scale)
        self.workspace.set_scale(scale)
        self.save_dialog.set_scale(scale)
        self.settings_dialog.set_scale(scale)
        self.layout.update(self.window)
        if save:
            self.config.ui_scale = scale
            self.config.save()

    def _change_scale(self, direction: int) -> None:
        index = max(0, min(len(SCALE_STEPS) - 1, self._scale_index + direction))
        if index != self._scale_index:
            self._scale_index = index
            self._apply_scale()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def open_settings(self) -> None:
        if self.save_dialog.active:
            return
        self.settings_dialog.open(self.config.show_orientation_cube)

    def _set_orientation_cube(self, visible: bool) -> None:
        self.config.show_orientation_cube = bool(visible)
        self.config.save()
        self.workspace.set_orientation_cube_visible(visible)

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def _unique_name(self) -> str:
        existing = {document.name for document in self.documents}
        name = "Untitled"
        index = 2
        while name in existing:
            name = f"Untitled {index}"
            index += 1
        return name

    def new_document(self) -> None:
        self._playing = False
        document = Document(id=self._next_id, name=self._unique_name())
        self._next_id += 1
        self.documents.append(document)
        self._stacks[document.id] = CommandStack()
        self.active_id = document.id

    def open_document(self) -> None:
        # A file picker is not part of this milestone; use Ctrl+S for saving.
        return

    def open_recent(self, path: str) -> None:
        self._playing = False
        for document in self.documents:
            if document.path == path:
                self.active_id = document.id
                return
        try:
            document = Document.load(self._next_id, path)
        except (OSError, ValueError, json.JSONDecodeError):
            return
        self._next_id += 1
        self.documents.append(document)
        self._stacks[document.id] = CommandStack()
        self.active_id = document.id
        self.config.add_recent(document.name, path)
        self._refresh_recent()

    def open_example(self, path: str) -> None:
        return

    def select_document(self, document_id: int) -> None:
        self._playing = False
        self.active_id = document_id

    def close_document(self, document_id: int) -> None:
        self._playing = False
        index = next(
            (i for i, doc in enumerate(self.documents) if doc.id == document_id),
            None,
        )
        if index is None:
            return
        self.documents.pop(index)
        self._stacks.pop(document_id, None)
        if self.active_id != document_id:
            return
        if self.documents:
            self.active_id = self.documents[min(index, len(self.documents) - 1)].id
        else:
            self.active_id = None

    def active_document(self) -> Optional[Document]:
        return next(
            (doc for doc in self.documents if doc.id == self.active_id), None
        )

    def _active_stack(self) -> Optional[CommandStack]:
        document = self.active_document()
        if document is None:
            return None
        return self._stacks.get(document.id)

    @staticmethod
    def _history_entries(stack: Optional[CommandStack]) -> List[HistoryEntry]:
        if stack is None:
            return []
        return [
            HistoryEntry(command.kind, command.label)
            for command in stack.history()
            if command.kind != "point"
        ]

    def _sync_active_sketch(self, document: Document) -> None:
        if (
            document.active_sketch_id is not None
            and document.sketch(document.active_sketch_id) is None
        ):
            document.active_sketch_id = None
            self.workspace.sketch_palette_window.close()
        if (
            document.selected_face is not None
            and face_for_ref(document, document.selected_face) is None
        ):
            document.selected_face = None

    def _activate_editable_sketch(self, document: Document) -> None:
        """After rolling back, resume the latest sketch that is not consumed."""
        if document.active_sketch_id is not None:
            return
        consumed = {feature.sketch_id for feature in document.features}
        editable = [
            sketch for sketch in document.sketches
            if sketch.id not in consumed
        ]
        if editable:
            document.active_sketch_id = editable[-1].id
            self._align_camera_to_active_sketch(document)
            sketch = document.sketch(document.active_sketch_id)
            self.workspace.sketch_palette_window.open(sketch.line_type if sketch else "normal")

    # ------------------------------------------------------------------
    # Editing (all in memory, saving is never required)
    # ------------------------------------------------------------------

    def new_sketch(self) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        if document.selected_face is not None:
            face = face_for_ref(document, document.selected_face)
            if face is None:
                document.selected_face = None
                self.workspace.open_create_sketch_dialog()
                return
            command = AddSketchCommand(
                document,
                "XY",
                frame=face.to_plane_frame(),
                label=face.label,
            )
        elif document.selected_plane is not None:
            command = AddSketchCommand(
                document, document.selected_plane
            )
        else:
            self.workspace.open_create_sketch_dialog()
            return
        stack.execute(command)
        self.workspace.close_create_sketch_dialog()
        if command.sketch is not None:
            document.active_sketch_id = command.sketch.id
            self._align_camera_to_active_sketch(document)
            self.workspace.sketch_palette_window.open(command.sketch.line_type)

    def add_point(self, point: Point) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        stack.execute(AddPointCommand(document, sketch, point))

    def extrude_active(self) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or len(sketch.points) < 3:
            return
        stack.execute(AddExtrudeCommand(document, sketch))
        # The sketch is now consumed by the feature; hide it until selected again.
        document.active_sketch_id = None
        self.workspace.sketch_palette_window.close()

    def select_sketch(self, sketch_id: int) -> None:
        document = self.active_document()
        if document is not None:
            sketch = document.sketch(sketch_id)
            if sketch is not None:
                document.active_sketch_id = sketch_id
                document.selected_face = None
                document.selected_plane = (
                    None if sketch.is_custom_plane else sketch.plane
                )
                self._align_camera_to_active_sketch(document)
                self.workspace.sketch_palette_window.open(sketch.line_type)

    def _align_camera_to_active_sketch(self, document: Document) -> None:
        sketch = document.sketch(document.active_sketch_id)
        if sketch is not None:
            self.workspace.viewport.camera.align_to_plane(sketch.frame())

    def undo(self) -> None:
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        self._playing = False
        if stack.undo():
            self._sync_active_sketch(document)

    def redo(self) -> None:
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        self._playing = False
        if stack.redo():
            self._sync_active_sketch(document)

    # ------------------------------------------------------------------
    # History timeline
    # ------------------------------------------------------------------

    def history_jump(self, position: int) -> None:
        """Roll the document to a position in its action history."""
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        self._playing = False
        stack.jump_to(position)
        self._sync_active_sketch(document)
        self._activate_editable_sketch(document)

    def history_delete(self, index: int) -> None:
        """Delete a timeline action and rebuild the remaining history."""
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        self._playing = False
        if stack.remove_at(index) is not None:
            self._sync_active_sketch(document)
            self._activate_editable_sketch(document)

    def toggle_playback(self) -> None:
        """Play or pause the history timeline."""
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        total = len(stack.history())
        if total == 0:
            return
        if self._playing:
            self._playing = False
            return
        if stack.position >= total:
            stack.jump_to(0)
            self._sync_active_sketch(document)
        self._playing = True
        self._play_accumulator = 0.0

    def _update_playback(self, delta: float) -> None:
        if not self._playing:
            return
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            self._playing = False
            return
        total = len(stack.history())
        if total == 0 or stack.position >= total:
            self._playing = False
            return
        self._play_accumulator += delta
        if self._play_accumulator < 0.35:
            return
        self._play_accumulator = 0.0
        stack.jump_to(stack.position + 1)
        self._sync_active_sketch(document)
        if stack.position >= total:
            self._playing = False

    def _refresh_recent(self) -> None:
        files: List[RecentFile] = []
        for entry in self.config.recent_entries():
            path = str(entry.get("path", ""))
            if not path:
                continue
            name = str(entry.get("name") or Path(path).stem)
            opened = ""
            try:
                if entry.get("opened_at"):
                    opened = format_opened(float(entry["opened_at"]))
            except (TypeError, ValueError):
                opened = ""
            files.append(
                RecentFile(
                    name=name,
                    path=path,
                    opened=opened,
                    preview_kind="cube",
                )
            )
        self.start_page.set_recent_files(files)

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save_active(self) -> None:
        document = self.active_document()
        if document is None:
            return
        if document.path:
            error = self._save_to(document.path)
            if error:
                print(error)
        else:
            self.save_dialog.open(self._default_save_path(document))

    @staticmethod
    def _default_save_path(document: Document) -> str:
        documents = Path.home() / "Documents"
        base = documents if documents.is_dir() else Path.home()
        return str(base / "PY3DCAD" / f"{document.name}.py3dcad")

    def _save_to(self, path: str) -> Optional[str]:
        document = self.active_document()
        if document is None:
            return "No active document."
        try:
            document.save(path)
        except OSError as error:
            return str(error)
        self.config.add_recent(document.name, document.path or path)
        self._refresh_recent()
        return None

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.window.running = True
        while self.window.running:
            delta = self.window.tick(60)
            for event in pygame.event.get():
                self._handle_event(event)
            self._update_playback(delta)
            self._draw()
            self.window.flip()
        self.window.close()

    def _handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.window.running = False
            return
        if event.type == pygame.VIDEORESIZE:
            self.window.handle_resize(event)
            self.layout.update(self.window)
            return
        if self.settings_dialog.active:
            self.settings_dialog.handle_event(
                event, Rect(0, 0, *self.window.get_size())
            )
            return
        if self.save_dialog.active:
            self.save_dialog.handle_event(event)
            return
        if event.type == pygame.KEYDOWN:
            if event.mod & pygame.KMOD_CTRL:
                if self._handle_ctrl_key(event.key, bool(event.mod & pygame.KMOD_SHIFT)):
                    return
                return
            if self.documents and self._handle_edit_key(event.key):
                return
        if self.documents:
            if self.tab_bar.handle_event(
                event, self.layout.tab_bar, self.documents, self.active_id
            ):
                return
            document = self.active_document()
            if document is not None:
                stack = self._active_stack()
                full_history = [
                    HistoryEntry(command.kind, command.label)
                    for command in stack.history()
                ] if stack else []
                filtered_history = [
                    entry for entry in full_history if entry.kind != "point"
                ]
                self.workspace.handle_event(
                    event,
                    self.layout,
                    document,
                    filtered_history,
                    full_history,
                    stack.position if stack else 0,
                )
        else:
            self.start_page.handle_event(event, self._content_region())

    def _handle_edit_key(self, key: int) -> bool:
        document = self.active_document()
        if document is None:
            return False
        if key == pygame.K_s:
            self.new_sketch()
            return True
        if key == pygame.K_e:
            self.extrude_active()
            return True
        if key == pygame.K_y:
            self.redo()
            return True
        if key == pygame.K_ESCAPE and document.active_sketch_id is not None:
            document.active_sketch_id = None
            self.workspace.sketch_palette_window.close()
            return True
        return False

    def _handle_ctrl_key(self, key: int, shift: bool = False) -> bool:
        if key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self._change_scale(1)
            return True
        if key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self._change_scale(-1)
            return True
        if key == pygame.K_s:
            self.save_active()
            return True
        if key == pygame.K_COMMA:
            self.open_settings()
            return True
        if key == pygame.K_z:
            self.redo() if shift else self.undo()
            return True
        if key == pygame.K_y:
            self.redo()
            return True
        return False

    def _content_region(self) -> Rect:
        bar = self.layout.tab_bar
        width, height = self.window.get_size()
        return Rect(0, bar.y + bar.h, width, height - bar.h)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        surface = self.window.surface
        surface.fill(pygame.Color(20, 20, 25))
        self.layout.update(self.window)

        document = self.active_document()
        if document is not None:
            stack = self._active_stack()
            full_history = [
                HistoryEntry(command.kind, command.label)
                for command in stack.history()
            ] if stack else []
            filtered_history = [
                entry for entry in full_history if entry.kind != "point"
            ]
            self.workspace.draw(
                surface,
                self.layout,
                document,
                filtered_history,
                full_history,
                stack.position if stack else 0,
                self._playing,
            )
        else:
            self.start_page.draw(surface, self._content_region())

        self.tab_bar.draw(
            surface, self.layout.tab_bar, self.documents, self.active_id
        )
        self.save_dialog.draw(surface, Rect(0, 0, *self.window.get_size()))
        self.settings_dialog.draw(
            surface, Rect(0, 0, *self.window.get_size())
        )
