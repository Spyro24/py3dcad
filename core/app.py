"""Application shell for PY3DCAD."""

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame

from .commands import (
    AddCircleCommand,
    AddExtrudeCommand,
    AddFilletCommand,
    AddLineCommand,
    AddMeasurementCommand,
    AddPointCommand,
    AddProjectionCommand,
    AddRectangleCommand,
    AddSketchCommand,
    BooleanExtrudeCommand,
    CommandStack,
    CompositeCommand,
    DeleteSketchEntitiesCommand,
    MoveEdgeCommand,
    MovePointCommand,
    SetEdgeConstraintCommand,
    SetMeasurementPlacementCommand,
    SetMeasurementValueCommand,
)
from .booleans import build_tool_stack, plan_boolean
from .config import Config, format_opened
from .document import Document
from .faces import (
    edge_for_ref, face_for_ref, max_fillet_radius, profile_has_corner,
    profile_segment_key, stack_cap_segment_key, stack_has_corner,
    vertical_edge_corner,
)
from .preview import (
    ExtrudePreview, FilletPreview, FilletTarget, build_extrude_preview,
    build_fillet_preview, common_fillet_radius,
)
from .sketch import (
    Extrude,
    Point,
    Sketch,
    normalize_measurement_placement,
    normalize_measurement_value,
)
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
UI_SCALE_MIN = 0.75
UI_SCALE_MAX = 2.0
UI_SCALE_STEP = 0.125


def _plane_offset(point, frame) -> float:
    """Return how far a point lies along a sketch plane's normal."""
    return (
        (point[0] - frame.origin[0]) * frame.normal[0]
        + (point[1] - frame.origin[1]) * frame.normal[1]
        + (point[2] - frame.origin[2]) * frame.normal[2]
    )


def _stack_cap_side(
    feature: Extrude, offset: float
) -> Tuple[Optional[str], float]:
    """Return which cap of a sliced body lies at a local plane offset."""
    zmin = min(entry.z0 for entry in feature.slices)
    zmax = max(entry.z1 for entry in feature.slices)
    if abs(offset - zmax) <= 1e-4:
        return "top", zmax
    if abs(offset - zmin) <= 1e-4:
        return "bottom", zmin
    return None, offset


def _resolve_fillet_ref(
    document: Document, reference: Optional[Tuple[int, int]], radius: float
) -> Tuple[Optional[str], Optional[FilletTarget]]:
    """Turn one selected edge reference into a fillet without editing it.

    Returns ``(error, target)``.  Applying a fillet and the live preview both
    use this so they can never disagree about what edge is about to change.
    """
    if reference is None:
        return "Select a solid edge first", None
    feature = next(
        (
            candidate
            for candidate in document.features
            if candidate.id == reference[0]
        ),
        None,
    )
    edge = edge_for_ref(document, reference)
    sketch = (
        document.sketch(feature.sketch_id)
        if feature is not None else None
    )
    if feature is None or edge is None or sketch is None:
        return "Select a solid edge first", None
    frame = sketch.frame()
    delta = (
        edge.end[0] - edge.start[0],
        edge.end[1] - edge.start[1],
        edge.end[2] - edge.start[2],
    )
    length = math.hypot(*delta)
    if length < 1e-9:
        return "Select a solid edge first", None
    along_axis = abs(
        (delta[0] * frame.normal[0]
         + delta[1] * frame.normal[1]
         + delta[2] * frame.normal[2]) / length
    )
    if along_axis > 0.999:
        corner = vertical_edge_corner(edge, frame)
        has_corner = (
            corner is not None
            and (
                stack_has_corner(feature.slices, corner)
                if feature.slices
                else profile_has_corner(document, feature, corner)
            )
        )
        if not has_corner or corner is None:
            return "Edge is already filleted", None
        kind = "vertical"
        segment_key = None
        u, v = corner
    else:
        start_offset = _plane_offset(edge.start, frame)
        end_offset = _plane_offset(edge.end, frame)
        if abs(start_offset - end_offset) > 1e-4:
            return "Fillet needs a solid edge", None
        midpoint = edge.midpoint
        offset = (
            midpoint[0] - frame.origin[0],
            midpoint[1] - frame.origin[1],
            midpoint[2] - frame.origin[2],
        )
        u = (
            offset[0] * frame.u[0]
            + offset[1] * frame.u[1]
            + offset[2] * frame.u[2]
        )
        v = (
            offset[0] * frame.v[0]
            + offset[1] * frame.v[1]
            + offset[2] * frame.v[2]
        )
        if feature.slices:
            kind, cap_z = _stack_cap_side(feature, start_offset)
            if kind is None:
                return "Fillet needs a solid edge", None
            segment_key = stack_cap_segment_key(
                feature.slices, cap_z, (u, v)
            )
        else:
            segment_key = profile_segment_key(
                document, feature, (u, v)
            )
        if segment_key is None:
            return "Edge is already filleted", None
        if not feature.slices:
            # The cap on the positive-normal side is the top face.
            center = feature.start + feature.height * 0.5
            kind = (
                "top"
                if (start_offset + end_offset) * 0.5 > center
                else "bottom"
            )
    if radius <= 0.0:
        return "Enter a radius greater than zero", None
    if feature.slices:
        duplicate = False
    elif kind == "vertical":
        duplicate = any(
            fillet.kind == "vertical"
            and abs(fillet.u - u) <= 1e-4
            and abs(fillet.v - v) <= 1e-4
            for fillet in feature.fillets
        )
    else:
        duplicate = any(
            fillet.kind == kind
            and profile_segment_key(
                document, feature, (fillet.u, fillet.v)
            ) == segment_key
            for fillet in feature.fillets
        )
    if duplicate:
        return "Edge is already filleted", None
    return None, FilletTarget(feature, kind, u, v)


def _resolve_fillets(
    document: Document, radius: float
) -> Tuple[Optional[str], List[FilletTarget]]:
    """Resolve every selected edge, skipping duplicates and dead references."""
    if not document.selected_edges:
        return "Select a solid edge first", []
    targets: List[FilletTarget] = []
    seen = set()
    error: Optional[str] = None
    for reference in document.selected_edges:
        ref_error, target = _resolve_fillet_ref(document, reference, radius)
        if target is None:
            error = error or ref_error
            continue
        if max_fillet_radius(
            document, target.feature, target.kind, target.u, target.v
        ) is None:
            error = error or "Edge cannot be filleted"
            continue
        key = (
            target.feature.id, target.kind,
            round(target.u, 4), round(target.v, 4),
        )
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
    if not targets:
        return error or "Select a solid edge first", []
    return None, targets


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
        self.tab_bar = TabBar(
            self.select_document, self.close_document, self.new_document
        )
        self.workspace = Workspace(
            on_new_sketch=self.new_sketch,
            on_extrude=self.extrude_active,
            on_add_point=self.add_point,
            on_add_line=self.add_line,
            on_add_circle=self.add_circle,
            on_add_rectangle=self.add_rectangle,
            on_project_point=self.project_point,
            on_project_edge=self.project_edge,
            on_move_point=self.move_point,
            on_move_edge=self.move_edge,
            on_set_edge_constraint=self.set_edge_constraint,
            on_select_sketch=self.select_sketch,
            on_history_jump=self.history_jump,
            on_history_delete=self.history_delete,
            on_history_play=self.toggle_playback,
            on_settings=self.open_settings,
            on_add_measurement=self.add_measurement,
            on_set_measurement_placement=self.set_measurement_placement,
            on_set_measurement_value=self.set_measurement_value,
            on_fillet=self.add_fillet,
            on_delete_sketch=self.delete_sketch_entities,
        )
        self.save_dialog = SaveDialog(self._save_to)
        self.settings_dialog = SettingsDialog(self._set_orientation_cube)

        self.documents: List[Document] = []
        self.active_id: Optional[int] = None
        self._next_id = 1
        self._stacks: Dict[int, CommandStack] = {}
        self._playing = False
        self._play_accumulator = 0.0
        self._fillet_preview_cache = None
        self._fillet_limit_cache = None
        self._extrude_preview_cache = None

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
            HistoryEntry(
                command.kind,
                command.label,
                command.timeline_visible,
            )
            for command in stack.history()
        ]

    def _sync_active_sketch(self, document: Document) -> None:
        if (
            document.active_sketch_id is not None
            and document.sketch(document.active_sketch_id) is None
        ):
            document.active_sketch_id = None
            self.workspace.sketch_palette_window.close()
        if document.selected_faces:
            document.selected_faces = [
                reference for reference in document.selected_faces
                if face_for_ref(document, reference) is not None
            ]
        if document.selected_edges:
            document.selected_edges = [
                reference for reference in document.selected_edges
                if edge_for_ref(document, reference) is not None
            ]

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
            self.workspace.begin_sketch_edit()
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
            self.workspace.begin_sketch_edit()
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

    def add_line(
        self, start: Point, end: Point,
        constraint: Optional[str] = None,
    ) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or start == end:
            return
        stack.execute(
            AddLineCommand(document, sketch, start, end, constraint)
        )

    def add_rectangle(
        self, first: Point, opposite: Point
    ) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        if first[0] == opposite[0] or first[1] == opposite[1]:
            return
        stack.execute(
            AddRectangleCommand(document, sketch, first, opposite)
        )

    def project_point(
        self, feature_id: int, point: Tuple[float, float, float]
    ) -> None:
        """Project one solid vertex into the active sketch."""
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        document.refresh_projections()
        command = AddProjectionCommand(
            document, sketch, feature_id, points=[point]
        )
        if command.has_targets:
            stack.execute(command)

    def project_edge(self, feature_id: int, edge_index: int) -> None:
        """Project one solid edge (including smooth runs) into the sketch."""
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return
        edge = edge_for_ref(document, (feature_id, edge_index))
        if edge is None:
            return
        document.refresh_projections()
        command = AddProjectionCommand(
            document, sketch, feature_id, chains=[edge.chain]
        )
        if command.has_targets:
            stack.execute(command)

    def add_circle(self, center: Point, diameter: float) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or diameter <= 0:
            return
        stack.execute(
            AddCircleCommand(document, sketch, center, diameter)
        )

    def delete_sketch_entities(
        self,
        entity: Optional[Tuple[str, int]],
        loops: List[List[int]],
    ) -> bool:
        """Delete the selected sketch geometry as one undoable action."""
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return False
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return False
        command = DeleteSketchEntitiesCommand(
            document, sketch, entity, loops
        )
        if not command.has_targets:
            return False
        stack.execute(command)
        return True

    def move_point(self, index: int, point: Point) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.points):
            return
        if sketch.is_projected_point(index):
            return
        if sketch.points[index] == point:
            return
        stack.execute(MovePointCommand(document, sketch, index, point))

    def move_edge(
        self, index: int, start: Point, end: Point
    ) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.edges):
            return
        if sketch.is_projected_edge(index):
            return
        first, second = sketch.edges[index]
        if (
            not 0 <= first < len(sketch.points)
            or not 0 <= second < len(sketch.points)
        ):
            return
        if (
            sketch.points[first] == start
            and sketch.points[second] == end
        ):
            return
        stack.execute(
            MoveEdgeCommand(document, sketch, index, start, end)
        )

    def set_edge_constraint(
        self, index: int, constraint: str
    ) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.edges):
            return
        if sketch.is_projected_edge(index):
            return
        if constraint not in ("horizontal", "vertical"):
            return
        if sketch.edge_constraint(index) == constraint:
            return
        stack.execute(
            SetEdgeConstraintCommand(
                document, sketch, index, constraint
            )
        )

    def add_measurement(
        self,
        measurement_kind: str,
        first: tuple[str, int],
        second: tuple[str, int],
        placement: Optional[float] = None,
        value: Optional[float] = None,
    ) -> None:
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or measurement_kind not in (
            "distance", "angle"
        ):
            return
        if placement is not None:
            normalized = normalize_measurement_placement(placement)
            if normalized is None:
                return
            placement = normalized
        if value is not None:
            normalized = normalize_measurement_value(value)
            if normalized is None:
                return
            value = normalized
        for entity_kind, index in (first, second):
            if entity_kind == "point":
                if not 0 <= index < len(sketch.points):
                    return
                if sketch.is_projected_point(index):
                    return
            elif entity_kind == "line":
                if not 0 <= index < len(sketch.edges):
                    return
                if sketch.is_projected_edge(index):
                    return
            else:
                return
        stack.execute(
            AddMeasurementCommand(
                document,
                sketch,
                measurement_kind,
                first,
                second,
                placement,
                value,
            )
        )

    def set_measurement_placement(
        self, index: int, placement: float
    ) -> None:
        """Update only the user-controlled annotation placement."""
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.measurements):
            return
        normalized = normalize_measurement_placement(placement)
        if normalized is None:
            return
        if sketch.measurements[index].placement == normalized:
            return
        stack.execute(
            SetMeasurementPlacementCommand(
                document, sketch, index, normalized
            )
        )

    def set_measurement_value(self, index: int, value: float) -> None:
        """Set a measurement value; the engine never overwrites it."""
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None or not 0 <= index < len(sketch.measurements):
            return
        normalized = normalize_measurement_value(value)
        if normalized is None:
            return
        measurement = sketch.measurements[index]
        if measurement.kind == "angle" and normalized > 180:
            return
        stack.execute(
            SetMeasurementValueCommand(
                document, sketch, index, normalized
            )
        )

    def extrude_active(
        self,
        profiles: Optional[List[List[int]]] = None,
        regions: Optional[List[List[List[int]]]] = None,
        cuts: Optional[List[List[int]]] = None,
        height: float = 20.0,
        start: float = 0.0,
        operation: str = "new_body",
        taper: float = 0.0,
    ) -> Optional[str]:
        """Extrude the selected sketch regions, returning an error text."""
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return "No active document"
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return "Open a sketch to extrude"
        document.refresh_projections()
        if abs(height) <= 1e-9:
            return "Enter a distance greater than zero"
        if abs(taper) > 1e-9:
            return "Taper is not supported yet"
        if profiles is None:
            profiles = []
        if regions is None:
            regions = []
        if not profiles and not regions:
            regions = self.workspace.selected_regions(sketch)
        if cuts is None:
            cuts = self.workspace.selected_cut_profiles(sketch)
        valid = [
            list(profile)
            for profile in (profiles or [])
            if len(sketch.loop_points(profile)) >= 3
        ]
        valid_regions = [
            [list(loop) for loop in region]
            for region in (regions or [])
            if region
            and all(len(sketch.loop_points(loop)) >= 3 for loop in region)
        ]
        valid_cuts = [
            list(cut)
            for cut in cuts
            if len(sketch.loop_points(cut)) >= 3
        ]
        if not valid and not valid_regions:
            return "Select a profile to extrude"
        if operation == "new_body":
            stack.execute(
                AddExtrudeCommand(
                    document, sketch, height=height, profiles=valid,
                    regions=valid_regions, cuts=valid_cuts,
                    start=start, operation=operation,
                )
            )
        else:
            error = self._boolean_extrude(
                document, stack, sketch, valid, valid_regions,
                valid_cuts, height, start, operation,
            )
            if error is not None:
                return error
        # The sketch is now consumed by the feature; hide it until selected again.
        document.active_sketch_id = None
        document.selected_edge = None
        document.selected_face = None
        self.workspace.sketch_palette_window.close()
        self.workspace.extrude_window.close()
        return None

    def _boolean_extrude(
        self,
        document: Document,
        stack: CommandStack,
        sketch: Sketch,
        profiles: List[List[int]],
        regions: List[List[List[int]]],
        cuts: List[List[int]],
        height: float,
        start: float,
        operation: str,
    ) -> Optional[str]:
        """Apply Join, Cut or Intersect to the body the tool touches."""
        tool = build_tool_stack(
            document, sketch, height, start, profiles, regions, cuts
        )
        target, slices, error = plan_boolean(
            document, tool, sketch.frame(), operation
        )
        if error is not None:
            return error
        if target is None:
            return "No body found"
        stack.execute(
            BooleanExtrudeCommand(document, target, slices, operation)
        )
        return None

    def add_fillet(self, radius: float) -> Optional[str]:
        """Round every selected solid edge, returning an error text."""
        self._playing = False
        document = self.active_document()
        stack = self._active_stack()
        if document is None or stack is None:
            return "No active document"
        error, targets = _resolve_fillets(document, radius)
        if error is not None or not targets:
            return error or "Select a solid edge first"
        limit = common_fillet_radius(document, targets)
        if limit is None:
            return "Edge is already filleted"
        radius = min(radius, limit)
        commands = [
            AddFilletCommand(
                document, target.feature, target.kind,
                target.u, target.v, radius,
            )
            for target in targets
        ]
        if len(commands) == 1:
            command = commands[0]
        else:
            command = CompositeCommand(
                commands,
                f"Fillet {radius:g} mm on {len(commands)} edges",
            )
        stack.execute(command)
        document.clear_selection()
        return None

    def fillet_preview(self, radius: float) -> Optional[FilletPreview]:
        """Return a throwaway document with the pending fillet applied.

        The real document stays untouched so the tree, history and undo
        stack keep describing the model the user actually has.  Only the
        solid rendering is swapped for the preview.  The removed wedge is
        drawn as a red ghost so the sharp edge and the rounded surface are
        visible at the same time.
        """
        document = self.active_document()
        if document is None:
            return None
        snapshot = tuple(
            (
                candidate.id,
                candidate.sketch_id,
                candidate.height,
                len(candidate.fillets),
                tuple(
                    (entry.z0, entry.z1, len(entry.regions))
                    for entry in candidate.slices
                ),
            )
            for candidate in document.features
        )
        selection_key = (
            document.id,
            tuple(document.selected_edges),
            snapshot,
        )
        key = (*selection_key, radius)
        cached = self._fillet_preview_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        self._fillet_preview_cache = (key, None)
        error, targets = _resolve_fillets(document, radius)
        if error is not None or not targets:
            return None
        cached_limit = self._fillet_limit_cache
        if cached_limit is not None and cached_limit[0] == selection_key:
            limit = cached_limit[1]
        else:
            limit = common_fillet_radius(document, targets)
            self._fillet_limit_cache = (selection_key, limit)
        preview = build_fillet_preview(document, targets, radius, limit)
        self._fillet_preview_cache = (key, preview)
        return preview

    def extrude_preview(
        self, document: Optional[Document] = None
    ) -> Optional[ExtrudePreview]:
        """Return a throwaway document for the pending extrude panel state."""
        if document is None:
            document = self.active_document()
        window = self.workspace.extrude_window
        if document is None or not window.visible:
            return None
        sketch = document.sketch(document.active_sketch_id)
        if sketch is None:
            return None
        distance = window.distance_value()
        taper = window.taper_value()
        if distance is None or taper is None or window.thin:
            return None
        if abs(taper) > 1e-9:
            return None
        regions = self.workspace.selected_regions(sketch)
        if not regions:
            return None
        symmetric = window.is_symmetric()
        height = distance if symmetric or not window.reverse else -distance
        start = -distance * 0.5 if symmetric else 0.0
        key = self._extrude_preview_key(
            document, sketch, regions, height, start,
            window.operation,
        )
        cached = self._extrude_preview_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        cuts = self.workspace.selected_cut_profiles(sketch)
        preview = build_extrude_preview(
            document, sketch, height, start, [], regions, cuts,
            window.operation,
        )
        self._extrude_preview_cache = (key, preview)
        return preview

    @staticmethod
    def _extrude_preview_key(
        document: Document,
        sketch: Sketch,
        regions: List[List[List[int]]],
        height: float,
        start: float,
        operation: str,
    ) -> Tuple:
        """Fingerprint every input that can change the preview."""
        features = tuple(
            (
                feature.id,
                feature.sketch_id,
                round(feature.start, 9),
                round(feature.height, 9),
                len(feature.fillets),
                tuple(
                    (
                        round(entry.z0, 9),
                        round(entry.z1, 9),
                        len(entry.regions),
                    )
                    for entry in feature.slices
                ),
            )
            for feature in document.features
        )
        return (
            document.id,
            sketch.id,
            len(sketch.points),
            len(sketch.edges),
            len(sketch.circles),
            tuple(
                tuple(tuple(loop) for loop in region)
                for region in regions
            ),
            round(height, 9),
            round(start, 9),
            operation,
            features,
        )

    def select_sketch(self, sketch_id: int) -> None:
        document = self.active_document()
        if document is not None:
            sketch = document.sketch(sketch_id)
            if sketch is not None:
                document.active_sketch_id = sketch_id
                document.selected_face = None
                document.selected_edge = None
                document.selected_plane = (
                    None if sketch.is_custom_plane else sketch.plane
                )
                self._align_camera_to_active_sketch(document)
                self.workspace.begin_sketch_edit()
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
        history = stack.history()
        target = min(stack.position + 1, total)
        while (
            target < total
            and not history[target - 1].timeline_visible
        ):
            target += 1
        stack.jump_to(target)
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
        if self.tab_bar.handle_event(
            event, self.layout.tab_bar, self.documents, self.active_id
        ):
            return
        if self.documents:
            document = self.active_document()
            if document is not None:
                stack = self._active_stack()
                full_history = self._history_entries(stack)
                filtered_history = [
                    entry
                    for entry in full_history
                    if entry.timeline_visible
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
        if self.workspace.extrude_window.visible:
            return False
        if key == pygame.K_s:
            self.new_sketch()
            return True
        if key == pygame.K_e:
            self.workspace.open_extrude(document)
            return True
        if key == pygame.K_y:
            self.redo()
            return True
        if key == pygame.K_ESCAPE and document.active_sketch_id is not None:
            self.workspace.deselect_tool()
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
            document.refresh_projections()
            stack = self._active_stack()
            full_history = self._history_entries(stack)
            filtered_history = [
                entry
                for entry in full_history
                if entry.timeline_visible
            ]
            radius = self.workspace.fillet_preview_radius()
            extrude_preview = self.extrude_preview(document)
            fillet_preview = None
            if extrude_preview is not None:
                preview = extrude_preview.document
                ghost_faces = extrude_preview.ghost_faces
            else:
                if radius is not None:
                    fillet_preview = self.fillet_preview(radius)
                preview = (
                    fillet_preview.document if fillet_preview else None
                )
                ghost_faces = (
                    fillet_preview.ghost_faces if fillet_preview else ()
                )
            self.workspace.draw(
                surface,
                self.layout,
                document,
                filtered_history,
                full_history,
                stack.position if stack else 0,
                self._playing,
                preview_document=preview,
                ghost_faces=ghost_faces,
                extrude_preview=extrude_preview,
                fillet_preview=fillet_preview,
            )
        else:
            self.start_page.draw(surface, self._content_region())

        self.tab_bar.draw(surface, self.layout.tab_bar, self.documents, self.active_id)
        self.save_dialog.draw(surface, Rect(0, 0, *self.window.get_size()))
        self.settings_dialog.draw(surface, Rect(0, 0, *self.window.get_size()))
