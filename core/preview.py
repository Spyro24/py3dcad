"""Live previews for geometry operations, without any UI dependencies."""

import copy
from dataclasses import dataclass, replace
from typing import Optional, Sequence, Tuple

from .booleans import (
    build_tool_stack, combine_stacks, feature_stack, plan_boolean,
)
from .document import Document
from .faces import Face, stacked_faces
from .sketch import (
    Extrude, ExtrudeSlice, Point3, Sketch, point_on_plane,
)

Point2 = Tuple[float, float]


@dataclass
class ExtrudePreview:
    """A throwaway result document plus the volume an operation removes.

    ``ghost_faces`` describes material that exists before the operation but
    not afterwards.  The viewport draws it as transparent red so a cut or
    intersection reads as a removal, while ``document`` shows the surviving
    solid in the normal body colours.
    """

    document: Document
    ghost_faces: Tuple[Face, ...] = ()
    handle_start: Optional[Point3] = None
    handle_end: Optional[Point3] = None
    normal: Point3 = (0.0, 0.0, 1.0)
    height: float = 0.0


def build_extrude_preview(
    document: Document,
    sketch: Sketch,
    height: float,
    start: float,
    profiles: Sequence[Sequence[int]],
    regions: Sequence[Sequence[Sequence[int]]],
    cuts: Sequence[Sequence[int]],
    operation: str,
) -> Optional[ExtrudePreview]:
    """Return the solid an extrusion would produce and its removed volume."""
    tool = build_tool_stack(
        document, sketch, height, start, profiles, regions, cuts
    )
    if not tool:
        return None
    center = _stack_center(tool)
    if center is None:
        return None
    frame = sketch.frame()
    handle_start = point_on_plane(frame, center, start)
    handle_end = point_on_plane(frame, center, start + height)
    preview = copy.copy(document)
    preview.selected_face = None
    preview.selected_edge = None
    if operation == "new_body":
        preview.features = list(document.features)
        feature_id = max(
            (feature.id for feature in document.features), default=0
        ) + 1
        preview.features.append(Extrude(
            feature_id,
            "Preview",
            sketch.id,
            height=height,
            start=start,
            operation="new_body",
            slices=tool,
        ))
        return ExtrudePreview(
            preview, (), handle_start, handle_end, frame.normal, height
        )
    target, result, error = plan_boolean(
        document, tool, frame, operation
    )
    if error is not None or target is None:
        return None
    target_sketch = document.sketch(target.sketch_id)
    if target_sketch is None:
        return None
    target_frame = target_sketch.frame()
    before = feature_stack(document, target, target_frame)
    removed = combine_stacks(before, result, "cut")
    ghost_faces = tuple(
        stacked_faces(removed, target_frame)[0]
    ) if removed else ()
    preview.features = [
        replace(
            feature,
            slices=result if feature.id == target.id else feature.slices,
            operation=(
                operation if feature.id == target.id
                else feature.operation
            ),
        )
        for feature in document.features
    ]
    return ExtrudePreview(
        preview, ghost_faces, handle_start, handle_end,
        frame.normal, height,
    )


def _stack_center(
    stack: Sequence[ExtrudeSlice],
) -> Optional[Point2]:
    """Return the middle of a z-stack's cross-section bounds."""
    points = [
        point
        for entry in stack
        for group in entry.regions
        for loop in group
        for point in loop
    ]
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return ((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5)
