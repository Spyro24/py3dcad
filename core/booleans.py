"""Boolean operations between prismatic bodies.

The model stores solids as stacks of constant cross-sections along the
sketch-plane normal.  This module detects the body an extrusion touches and
combines the two stacks slice by slice in 2D, so no 3D CSG library is needed.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

from .profiles import (
    Region, build_regions, region_difference, region_intersection,
    region_union, split_loop_at_points,
)
from .sketch import Extrude, ExtrudeSlice, PlaneFrame

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import Document
    from .sketch import Sketch

Point2 = Tuple[float, float]
Group = List[List[float]]
Operation = str

OPERATION_LABELS = {
    "new_body": "New Body",
    "join": "Join",
    "cut": "Cut",
    "intersect": "Intersect",
}
TOLERANCE = 1e-6


@dataclass(frozen=True)
class _FrameMap:
    """Map local sketch coordinates from one parallel plane to another."""

    origin_u: float
    origin_v: float
    u_u: float
    u_v: float
    v_u: float
    v_v: float
    z_origin: float
    z_scale: float

    def point(self, point: Sequence[float]) -> Point2:
        x, y = float(point[0]), float(point[1])
        return (
            self.origin_u + x * self.u_u + y * self.v_u,
            self.origin_v + x * self.u_v + y * self.v_v,
        )

    def z(self, value: float) -> float:
        return self.z_origin + value * self.z_scale


def _dot(first: Sequence[float], second: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _frame_mapping(
    source: PlaneFrame, target: PlaneFrame
) -> Optional[_FrameMap]:
    """Return a local-to-local map for two parallel planes."""
    if abs(_dot(source.normal, target.normal)) < 1.0 - 1e-6:
        return None
    delta = tuple(source.origin[index] - target.origin[index] for index in range(3))
    return _FrameMap(
        origin_u=_dot(delta, target.u),
        origin_v=_dot(delta, target.v),
        u_u=_dot(source.u, target.u),
        u_v=_dot(source.u, target.v),
        v_u=_dot(source.v, target.u),
        v_v=_dot(source.v, target.v),
        z_origin=_dot(delta, target.normal),
        z_scale=_dot(source.normal, target.normal),
    )


def _map_groups(groups: Sequence[Group], mapping: _FrameMap) -> List[Group]:
    mapped: List[Group] = []
    for group in groups:
        loops = [
            [mapping.point(point) for point in loop]
            for loop in group if len(loop) >= 3
        ]
        if loops:
            mapped.append(loops)
    return mapped


def _map_stack(
    stack: Sequence[ExtrudeSlice],
    source: PlaneFrame,
    target: PlaneFrame,
) -> List[ExtrudeSlice]:
    """Express a z-stack in another parallel sketch frame."""
    mapping = _frame_mapping(source, target)
    if mapping is None:
        return []
    result: List[ExtrudeSlice] = []
    for entry in stack:
        z0, z1 = sorted((mapping.z(entry.z0), mapping.z(entry.z1)))
        regions = _map_groups(entry.regions, mapping)
        if regions and z1 - z0 > TOLERANCE:
            result.append(ExtrudeSlice(z0, z1, regions))
    return _normalize(result)


def feature_stack(
    document: "Document", feature: Extrude, target: PlaneFrame
) -> List[ExtrudeSlice]:
    """Return a feature's solid as z-slices in ``target``'s local frame."""
    sketch = document.sketch(feature.sketch_id)
    if sketch is None:
        return []
    source = sketch.frame()
    mapping = _frame_mapping(source, target)
    if mapping is None:
        return []
    if feature.slices:
        return _map_stack(feature.slices, source, target)
    profiles = feature.resolve_profiles(sketch)
    if not profiles:
        return []
    pairs = build_regions(profiles, feature.resolve_cuts(sketch))
    groups = [[outer, *holes] for outer, holes in pairs]
    z0, z1 = sorted((feature.start, feature.start + feature.height))
    if not groups or z1 - z0 <= TOLERANCE:
        return []
    return [ExtrudeSlice(z0, z1, _map_groups(groups, mapping))]


def build_tool_stack(
    document: "Document",
    sketch: "Sketch",
    height: float,
    start: float,
    profiles: Sequence[Sequence[int]],
    regions: Sequence[Sequence[Sequence[int]]],
    cuts: Sequence[Sequence[int]],
) -> List[ExtrudeSlice]:
    """Build the extrusion that the user is about to apply."""
    tool = Extrude(
        0, "Tool", sketch.id, height,
        [list(profile) for profile in profiles],
        [list(cut) for cut in cuts],
        [[list(loop) for loop in region] for region in regions],
    )
    loops = tool.resolve_profiles(sketch)
    if not loops:
        return []
    pairs = build_regions(loops, tool.resolve_cuts(sketch))
    groups = [[outer, *holes] for outer, holes in pairs]
    z0, z1 = sorted((start, start + height))
    if not groups or z1 - z0 <= TOLERANCE:
        return []
    return [ExtrudeSlice(z0, z1, groups)]


def _normalize(stack: Sequence[ExtrudeSlice]) -> List[ExtrudeSlice]:
    """Sort slices and drop empty or reversed intervals."""
    result = [
        entry for entry in stack
        if entry.regions and entry.z1 - entry.z0 > TOLERANCE
    ]
    result.sort(key=lambda entry: entry.z0)
    return result


def _bounds(
    stack: Sequence[ExtrudeSlice],
) -> Optional[Tuple[float, float, float, float, float, float]]:
    points = [
        point
        for entry in stack
        for group in entry.regions
        for loop in group
        for point in loop
    ]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [entry.z0 for entry in stack] + [entry.z1 for entry in stack]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _overlap_score(
    first: Sequence[ExtrudeSlice], second: Sequence[ExtrudeSlice]
) -> Optional[float]:
    """Score the 3D bounding-box overlap, counting touching as overlap."""
    first_bounds = _bounds(first)
    second_bounds = _bounds(second)
    if first_bounds is None or second_bounds is None:
        return None
    overlaps = [
        min(first_bounds[index + 3], second_bounds[index + 3])
        - max(first_bounds[index], second_bounds[index])
        for index in range(3)
    ]
    extent = max(
        first_bounds[index + 3] - first_bounds[index] for index in range(3)
    )
    tolerance = max(TOLERANCE, extent * 1e-5)
    if any(value < -tolerance for value in overlaps):
        return None
    return math.prod(max(0.0, value) + tolerance for value in overlaps)


def plan_boolean(
    document: "Document",
    tool: Sequence[ExtrudeSlice],
    tool_frame: PlaneFrame,
    operation: Operation,
) -> Tuple[Optional[Extrude], List[ExtrudeSlice], Optional[str]]:
    """Find the body an extrusion touches and compute its boolean result."""
    label = OPERATION_LABELS.get(operation, operation)
    if operation not in OPERATION_LABELS or operation == "new_body":
        return None, [], f"Unknown operation: {operation}"
    if not tool:
        return None, [], "Select a profile to extrude"
    best: Optional[Tuple[float, Extrude]] = None
    for feature in document.features:
        stack = feature_stack(document, feature, tool_frame)
        score = _overlap_score(tool, stack)
        if score is None:
            continue
        if best is None or score > best[0]:
            best = (score, feature)
    if best is None:
        return None, [], f"No body found to {label}"
    target = best[1]
    if target.fillets:
        return None, [], f"{label} needs a body without fillets"
    sketch = document.sketch(target.sketch_id)
    if sketch is None:
        return None, [], f"No body found to {label}"
    frame = sketch.frame()
    tool_in_target = _map_stack(tool, tool_frame, frame)
    if not tool_in_target:
        return None, [], f"{label} needs a body on a parallel plane"
    target_stack = feature_stack(document, target, frame)
    result = combine_stacks(target_stack, tool_in_target, operation)
    if not result:
        return None, [], "The operation removes all material"
    if _regions_key_stack(result) == _regions_key_stack(target_stack):
        if operation == "cut":
            return None, [], "The extrusion does not cut the body"
        if operation == "join":
            return None, [], "The extrusion adds no material"
    return target, result, None


def combine_stacks(
    target: Sequence[ExtrudeSlice],
    tool: Sequence[ExtrudeSlice],
    operation: Operation,
) -> List[ExtrudeSlice]:
    """Combine two z-stacks and split shared boundaries for a closed mesh."""
    boundaries = _unique_values([
        value
        for entry in (*target, *tool)
        for value in (entry.z0, entry.z1)
    ])
    result: List[ExtrudeSlice] = []
    for z0, z1 in zip(boundaries, boundaries[1:]):
        if z1 - z0 <= TOLERANCE:
            continue
        middle = (z0 + z1) * 0.5
        first = _regions_at(target, middle)
        second = _regions_at(tool, middle)
        regions = _apply(operation, first, second)
        if regions:
            result.append(ExtrudeSlice(z0, z1, regions))
    merged = _merge_slices(result)
    _split_shared_boundaries(merged)
    return merged


def _apply(
    operation: Operation, first: List[Group], second: List[Group]
) -> List[Group]:
    first_pairs = _pairs(first)
    second_pairs = _pairs(second)
    if operation == "join":
        pairs = region_union(first_pairs, second_pairs)
    elif operation == "cut":
        pairs = region_difference(first_pairs, second_pairs)
    else:
        pairs = region_intersection(first_pairs, second_pairs)
    return _groups(pairs)


def _pairs(groups: Sequence[Group]) -> List[Region]:
    return [
        (group[0], [loop for loop in group[1:] if len(loop) >= 3])
        for group in groups if group
    ]


def _groups(pairs: Sequence[Region]) -> List[Group]:
    return [
        [outer, *[hole for hole in holes if len(hole) >= 3]]
        for outer, holes in pairs if len(outer) >= 3
    ]


def _regions_at(
    stack: Sequence[ExtrudeSlice], z: float
) -> List[Group]:
    for entry in stack:
        if entry.z0 - TOLERANCE <= z <= entry.z1 + TOLERANCE:
            return [group for group in entry.regions if group]
    return []


def _unique_values(values: Sequence[float]) -> List[float]:
    ordered = sorted(values)
    result: List[float] = []
    for value in ordered:
        if not result or abs(value - result[-1]) > TOLERANCE:
            result.append(value)
    return result


def _regions_key(groups: Sequence[Group]) -> Tuple:
    regions = []
    for group in groups:
        loops = [
            tuple(sorted(
                (round(float(x), 6), round(float(y), 6)) for x, y in loop
            ))
            for loop in group if len(loop) >= 3
        ]
        if loops:
            regions.append(tuple(sorted(loops)))
    return tuple(sorted(regions))


def _regions_key_stack(stack: Sequence[ExtrudeSlice]) -> Tuple:
    return tuple(
        (round(entry.z0, 6), round(entry.z1, 6), _regions_key(entry.regions))
        for entry in stack
    )


def _merge_slices(stack: Sequence[ExtrudeSlice]) -> List[ExtrudeSlice]:
    merged: List[ExtrudeSlice] = []
    for entry in stack:
        if (
            merged
            and abs(merged[-1].z1 - entry.z0) <= TOLERANCE
            and _regions_key(merged[-1].regions) == _regions_key(entry.regions)
        ):
            merged[-1] = ExtrudeSlice(
                merged[-1].z0, entry.z1, merged[-1].regions
            )
        else:
            merged.append(entry)
    return merged


def _split_shared_boundaries(stack: Sequence[ExtrudeSlice]) -> None:
    """Add every cap vertex to the side loops that share it.

    Boolean caps can introduce vertices in the middle of a side-wall edge.
    Splitting all slice loops by the same point set keeps every shared edge
    exactly coincident, so the rendered mesh has no T-junctions.
    """
    points: Dict[Tuple[float, float], Point2] = {}
    for entry in stack:
        for group in entry.regions:
            for loop in group:
                for point in loop:
                    points[(round(point[0], 7), round(point[1], 7))] = (
                        float(point[0]), float(point[1])
                    )
    for lower, upper in zip(stack, stack[1:]):
        if abs(lower.z1 - upper.z0) > TOLERANCE:
            continue
        lower_only = region_difference(
            _pairs(lower.regions), _pairs(upper.regions)
        )
        upper_only = region_difference(
            _pairs(upper.regions), _pairs(lower.regions)
        )
        for pairs in (lower_only, upper_only):
            for outer, holes in pairs:
                for loop in (outer, *holes):
                    for point in loop:
                        points[(round(point[0], 7), round(point[1], 7))] = (
                            float(point[0]), float(point[1])
                        )
    if not points:
        return
    all_points = list(points.values())
    for entry in stack:
        entry.regions = [
            [
                split_loop_at_points(loop, all_points)
                for loop in group if len(loop) >= 3
            ]
            for group in entry.regions
        ]
        entry.regions = [group for group in entry.regions if group]
