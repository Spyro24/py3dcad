"""Live previews for geometry operations, without any UI dependencies."""

import copy
import math
from dataclasses import dataclass, replace
from typing import Optional, Sequence, Tuple

from .booleans import (
    build_tool_stack, combine_stacks, feature_stack, fillet_slices_body,
    plan_boolean,
)
from .document import Document
from .faces import (
    Edge, Face, edge_for_ref, max_fillet_radius, stacked_faces,
    stack_cap_common_radius_limit,
)
from .sketch import (
    Extrude, ExtrudeSlice, Fillet, Point3, Sketch, point_on_plane,
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
    # Bodies that the extrusion is creating or modifying, highlighted while
    # the tool is open.
    highlight: Tuple[int, ...] = ()


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
            preview, (), handle_start, handle_end, frame.normal, height,
            highlight=(feature_id,),
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
        highlight=() if operation == "cut" else (target.id,),
    )


@dataclass(frozen=True)
class FilletTarget:
    """One resolved edge that a fillet can round."""

    feature: Extrude
    kind: str
    u: float
    v: float


@dataclass
class FilletPreview:
    """A throwaway filleted document and the material the fillet removes.

    The removed volume is the wedge between the old sharp edge and the new
    rounded surface.  Drawing it in transparent red shows the state before
    the fillet while ``document`` shows the state after it.
    """

    document: Document
    ghost_faces: Tuple[Face, ...] = ()
    handle_start: Optional[Point3] = None
    handle_end: Optional[Point3] = None
    normal: Point3 = (0.0, 0.0, 1.0)
    radius: float = 0.0
    # Largest radius the selected edge can carry; the UI stops the handle
    # and the entered value here instead of pointing past the body.
    max_radius: Optional[float] = None


def _clone_preview(document: Document) -> Document:
    """Copy a document so fillets can be applied without touching the model."""
    preview = copy.copy(document)
    preview.features = [
        replace(candidate, fillets=list(candidate.fillets))
        for candidate in document.features
    ]
    return preview


def _apply_fillets(
    preview: Document, targets: Sequence[FilletTarget], radius: float
) -> bool:
    """Round every target in ``preview``; return False if any edge refuses."""
    copies = {candidate.id: candidate for candidate in preview.features}
    for target in targets:
        copy_feature = copies.get(target.feature.id)
        if copy_feature is None:
            return False
        limit = max_fillet_radius(
            preview, copy_feature, target.kind, target.u, target.v
        )
        if limit is not None and limit + 1e-9 < radius:
            return False
        fillet = Fillet(target.kind, target.u, target.v, radius)
        if copy_feature.slices:
            rounded = fillet_slices_body(copy_feature.slices, fillet)
            if rounded is None:
                return False
            copy_feature.slices = rounded
        else:
            copy_feature.fillets.append(fillet)
    return True


def _fits_fillets(
    document: Document, targets: Sequence[FilletTarget], radius: float
) -> bool:
    """Return whether all targets accept the same radius on a scratch copy."""
    return _apply_fillets(_clone_preview(document), targets, radius)


def common_fillet_radius(
    document: Document,
    targets: Sequence[FilletTarget],
) -> Optional[float]:
    """Return the largest radius every selected edge can share.

    A single edge only has its own limit, but several edges on one body share
    material: two full rounds on adjacent corners would consume the straight
    run between them twice.  Applying the fillets in sequence and shrinking
    the shared radius until they all fit keeps the result watertight.
    """
    if not targets:
        return None
    limits = [
        max_fillet_radius(
            document, target.feature, target.kind, target.u, target.v
        )
        for target in targets
    ]
    known = [limit for limit in limits if limit is not None]
    if not known:
        return None
    radius = min(known)
    # Cap fillets each consume a band of the wall height, so their shared
    # limit follows directly from the available height.  That avoids the much
    # slower sequential build-and-bisect search for cap-only selections.
    cap_groups: dict[Tuple[int, str], list[FilletTarget]] = {}
    for target in targets:
        if target.kind in ("top", "bottom") and target.feature.slices:
            cap_groups.setdefault(
                (target.feature.id, target.kind), []
            ).append(target)
    for (feature_id, kind), group in cap_groups.items():
        feature = next(
            candidate for candidate in document.features
            if candidate.id == feature_id
        )
        cap_limit = stack_cap_common_radius_limit(
            feature.slices, kind,
            [(target.u, target.v) for target in group],
        )
        if cap_limit is not None:
            radius = min(radius, cap_limit)
    if radius <= 1e-9:
        return None
    # A single cap group is fully described by the band limit above.
    if len(cap_groups) == 1 and all(
        target.kind in ("top", "bottom") and target.feature.slices
        for target in targets
    ):
        return radius
    if _fits_fillets(document, targets, radius):
        return radius
    low, high = 0.0, radius
    for _ in range(24):
        middle = (low + high) * 0.5
        if _fits_fillets(document, targets, middle):
            low = middle
        else:
            high = middle
    return low if low > 1e-6 else None


def build_fillet_preview(
    document: Document,
    targets: Sequence[FilletTarget],
    radius: float,
    limit: Optional[float] = None,
) -> Optional[FilletPreview]:
    """Return the rounded body and the material the fillet would remove."""
    if limit is None:
        limit = common_fillet_radius(document, targets)
    if limit is None or radius <= 1e-9:
        return None
    radius = min(radius, limit)
    preview = _clone_preview(document)
    if not _apply_fillets(preview, targets, radius):
        return None
    before = {}
    frames = {}
    # Resolve every feature before touching the preview so the ghost is the
    # difference between the untouched body and all fillets at once.
    for target in targets:
        if target.feature.id in before:
            continue
        sketch = document.sketch(target.feature.sketch_id)
        if sketch is None:
            continue
        frame = sketch.frame()
        frames[target.feature.id] = frame
        before[target.feature.id] = feature_stack(
            document, target.feature, frame
        )
    ghost: list[Face] = []
    for feature_id, before_stack in before.items():
        copy_feature = next(
            candidate for candidate in preview.features
            if candidate.id == feature_id
        )
        after_stack = feature_stack(
            preview, copy_feature, frames[feature_id]
        )
        removed = (
            combine_stacks(before_stack, after_stack, "cut")
            if before_stack and after_stack else []
        )
        if removed:
            ghost.extend(stacked_faces(removed, frames[feature_id])[0])
    # Selected edges keep their order, so the last target is the primary one
    # the radius arrow points at.
    primary = targets[-1]
    primary_frame = document.sketch(primary.feature.sketch_id)
    normal = (
        primary_frame.frame().normal if primary_frame is not None
        else (0.0, 0.0, 1.0)
    )
    handle = _fillet_handle(
        edge_for_ref(document, document.selected_edge),
        primary.kind,
        normal,
        radius,
    )
    # The user is seeing the result, not the old edge, so no stale selection
    # highlight may cover the preview.
    preview.selected_edges = []
    preview.selected_faces = []
    start, end, direction = handle if handle is not None else (
        None, None, normal,
    )
    return FilletPreview(
        preview, tuple(ghost), start, end, direction, radius, limit,
    )


def _fillet_handle(
    edge: Optional[Edge],
    kind: str,
    cap_normal: Point3,
    radius: float,
) -> Optional[Tuple[Point3, Point3, Point3]]:
    """Return the radius arrow that points from an edge into the body."""
    if edge is None or radius <= 1e-9:
        return None
    direction = _fillet_direction(edge, kind, cap_normal)
    if direction is None:
        return None
    start = edge.midpoint
    end = (
        start[0] + direction[0] * radius,
        start[1] + direction[1] * radius,
        start[2] + direction[2] * radius,
    )
    return start, end, direction


def _fillet_direction(
    edge: Edge, kind: str, cap_normal: Point3,
) -> Optional[Point3]:
    """Return the inward direction the fillet cuts away from ``edge``."""
    normals = [
        normal for normal in edge.normals if _length(normal) > 1e-9
    ]
    if not normals:
        return None
    if kind == "vertical":
        total = (
            sum(normal[0] for normal in normals),
            sum(normal[1] for normal in normals),
            sum(normal[2] for normal in normals),
        )
        direction = _unit((-total[0], -total[1], -total[2]))
    else:
        sideways = [
            normal for normal in normals
            if abs(_dot(_unit(normal), cap_normal)) < 0.9
        ]
        if not sideways:
            return None
        wall = _unit(sideways[0])
        inward = (-wall[0], -wall[1], -wall[2])
        direction = _unit(
            _subtract_scale(
                inward, cap_normal, _dot(inward, cap_normal)
            )
        )
    if _length(direction) < 0.5:
        return None
    edge_direction = _unit((
        edge.end[0] - edge.start[0],
        edge.end[1] - edge.start[1],
        edge.end[2] - edge.start[2],
    ))
    flattened = _unit(
        _subtract_scale(
            direction, edge_direction, _dot(direction, edge_direction)
        )
    )
    return flattened if _length(flattened) > 0.5 else None


def _unit(vector: Point3) -> Point3:
    length = _length(vector)
    if length <= 1e-9:
        return (0.0, 0.0, 0.0)
    return (
        vector[0] / length,
        vector[1] / length,
        vector[2] / length,
    )


def _length(vector: Point3) -> float:
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def _dot(first: Point3, second: Point3) -> float:
    return (
        first[0] * second[0]
        + first[1] * second[1]
        + first[2] * second[2]
    )


def _subtract_scale(
    vector: Point3, axis: Point3, amount: float,
) -> Point3:
    return (
        vector[0] - axis[0] * amount,
        vector[1] - axis[1] * amount,
        vector[2] - axis[2] * amount,
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
