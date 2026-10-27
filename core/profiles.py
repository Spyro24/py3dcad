"""Pure 2D profile geometry for sketch loops and extruded solids."""

import math
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

Point2 = Tuple[float, float]
Loop = List[Point2]
Segment = Tuple[Point2, Point2]
Region = Tuple[Loop, List[Loop]]

_EPS = 1e-9


def polygon_area(points: Sequence[Sequence[float]]) -> float:
    """Return the signed area of a closed polygon."""
    count = len(points)
    if count < 3:
        return 0.0
    area = 0.0
    for index in range(count):
        x1, y1 = float(points[index][0]), float(points[index][1])
        x2, y2 = float(points[(index + 1) % count][0]), float(
            points[(index + 1) % count][1]
        )
        area += x1 * y2 - x2 * y1
    return area / 2.0


def point_in_polygon(
    point: Sequence[float], polygon: Sequence[Sequence[float]]
) -> bool:
    """Return whether a point lies inside or on a polygon."""
    if len(polygon) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    for index in range(len(polygon)):
        x1, y1 = float(polygon[index][0]), float(polygon[index][1])
        x2, y2 = float(polygon[(index + 1) % len(polygon)][0]), float(
            polygon[(index + 1) % len(polygon)][1]
        )
        if _point_on_segment((x, y), (x1, y1), (x2, y2)):
            return True
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing:
                inside = not inside
    return inside


def build_regions(
    loops: Sequence[Sequence[Sequence[float]]],
    cutters: Sequence[Sequence[Sequence[float]]] = (),
) -> List[Tuple[Loop, List[Loop]]]:
    """Return ``(outer, holes)`` regions for a set of closed profiles.

    Loops that touch or overlap are merged into one outer contour.  A loop
    nested inside another becomes a hole instead of being swallowed by the
    union; a loop nested inside that hole becomes a separate island.  The
    even/odd nesting depth decides whether a loop bounds material or void.

    ``cutters`` are profiles that overlap the selected material.  They carve
    their shape out of it, so selecting a rectangle that a circle partly
    covers keeps only the rectangle area outside the circle.
    """
    cleaned = _clean_loops(loops)
    if not cleaned:
        return []
    if not cutters:
        return _regions_from_loops(cleaned)
    cutter_loops = _clean_loops(cutters)
    if not cutter_loops:
        return _regions_from_loops(cleaned)
    regions = _regions_from_loops(cleaned)
    boundary = _difference_loops(cleaned, cutter_loops, regions)
    return _regions_from_loops(boundary) if boundary else []


def _clean_loops(
    loops: Sequence[Sequence[Sequence[float]]],
) -> List[Loop]:
    cleaned = [_clean_loop(loop) for loop in loops]
    cleaned = [
        loop for loop in cleaned
        if len(loop) >= 3 and abs(polygon_area(loop)) > _EPS
    ]
    return _unique_loops(cleaned)


def _regions_from_loops(cleaned: Sequence[Loop]) -> List[Tuple[Loop, List[Loop]]]:
    """Classify already-clean boundary loops into material and holes."""
    cleaned = _unique_loops(list(cleaned))
    if not cleaned:
        return []

    # Nesting depth follows the smallest enclosing loop, not a raw count:
    # overlapping outer loops must not make a nested profile look like an
    # island just because several loops contain it.
    order = sorted(
        range(len(cleaned)),
        key=lambda index: abs(polygon_area(cleaned[index])),
        reverse=True,
    )
    depths = [0] * len(cleaned)
    for position, index in enumerate(order):
        parents = [
            other_index
            for other_index in order[:position]
            if loop_inside(cleaned[index], cleaned[other_index])
        ]
        if not parents:
            continue
        parent = min(
            parents,
            key=lambda other_index: abs(polygon_area(cleaned[other_index])),
        )
        depths[index] = depths[parent] + 1

    outers = _union_components([
        loop for loop, depth in zip(cleaned, depths) if depth % 2 == 0
    ])
    holes = _union_components([
        loop for loop, depth in zip(cleaned, depths) if depth % 2 == 1
    ])

    regions: List[Tuple[Loop, List[Loop]]] = [
        (outer, []) for outer in outers
    ]
    for hole in holes:
        candidates = [
            region for region in regions if loop_inside(hole, region[0])
        ]
        if not candidates:
            # A hole without a containing outer contour is material of its own.
            regions.append((hole, []))
            continue
        target = min(
            candidates, key=lambda region: abs(polygon_area(region[0]))
        )
        target[1].append(hole)
    return regions


def _difference_loops(
    selected: Sequence[Loop],
    cutters: Sequence[Loop],
    regions: Sequence[Tuple[Loop, List[Loop]]],
) -> List[Loop]:
    """Return the boundary of ``selected`` material minus ``cutters``."""
    segments = _split_segments(list(selected) + list(cutters))
    if not segments:
        return []
    all_points = [point for segment in segments for point in segment]
    diagonal = _diagonal(all_points)
    sample = max(1e-7, diagonal * 1e-6)
    boundary: List[Segment] = []
    for start, end in segments:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= _EPS:
            continue
        middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        normal = (-dy / length, dx / length)
        left = (middle[0] + normal[0] * sample, middle[1] + normal[1] * sample)
        right = (
            middle[0] - normal[0] * sample,
            middle[1] - normal[1] * sample,
        )
        inside_left = _inside_regions(left, regions) and not _inside_union(
            left, cutters
        )
        inside_right = _inside_regions(right, regions) and not _inside_union(
            right, cutters
        )
        if inside_left == inside_right:
            continue
        boundary.append((start, end) if inside_left else (end, start))
    return _trace_loops(boundary)


def _inside_regions(
    point: Point2, regions: Sequence[Tuple[Loop, List[Loop]]]
) -> bool:
    for outer, holes in regions:
        if not point_in_polygon(point, outer):
            continue
        if any(point_in_polygon(point, hole) for hole in holes):
            continue
        return True
    return False


def intersect_loops(
    loops: Sequence[Sequence[Sequence[float]]],
) -> List[Loop]:
    """Return the boundary loops shared by every given profile.

    This is the arrangement region under a click that lies inside several
    overlapping loops, such as the lens where a circle crosses a rectangle.
    """
    cleaned = _clean_loops(loops)
    if not cleaned:
        return []
    if len(cleaned) == 1:
        return [cleaned[0]]
    segments = _split_segments(cleaned)
    if not segments:
        return []
    all_points = [point for segment in segments for point in segment]
    diagonal = _diagonal(all_points)
    sample = max(1e-7, diagonal * 1e-6)
    boundary: List[Segment] = []
    for start, end in segments:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= _EPS:
            continue
        middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        normal = (-dy / length, dx / length)
        left = (
            middle[0] + normal[0] * sample,
            middle[1] + normal[1] * sample,
        )
        right = (
            middle[0] - normal[0] * sample,
            middle[1] - normal[1] * sample,
        )
        inside_left = all(
            point_in_polygon(left, loop) for loop in cleaned
        )
        inside_right = all(
            point_in_polygon(right, loop) for loop in cleaned
        )
        if inside_left == inside_right:
            continue
        boundary.append((start, end) if inside_left else (end, start))
    return _trace_loops(boundary)


def region_union(
    first: Sequence[Region], second: Sequence[Region]
) -> List[Region]:
    """Return the area covered by either region set."""
    return _combine_regions(first, second, lambda a, b: a or b)


def region_difference(
    first: Sequence[Region], second: Sequence[Region]
) -> List[Region]:
    """Return the area of ``first`` that ``second`` does not cover."""
    return _combine_regions(first, second, lambda a, b: a and not b)


def region_intersection(
    first: Sequence[Region], second: Sequence[Region]
) -> List[Region]:
    """Return the area covered by both region sets."""
    return _combine_regions(first, second, lambda a, b: a and b)


def _combine_regions(
    first: Sequence[Region],
    second: Sequence[Region],
    predicate: Callable[[bool, bool], bool],
) -> List[Region]:
    """Combine two hole-aware region sets with a membership predicate."""
    regions_first = _regions_from_loops(_region_loops(first))
    regions_second = _regions_from_loops(_region_loops(second))
    if not regions_first and not regions_second:
        return []
    if not regions_first:
        return (
            regions_second
            if predicate(False, True) else []
        )
    if not regions_second:
        return (
            regions_first
            if predicate(True, False) else []
        )
    loops = [
        loop
        for region in regions_first + regions_second
        for loop in (region[0], *region[1])
    ]
    segments = _split_segments(loops)
    if not segments:
        return []
    all_points = [point for segment in segments for point in segment]
    sample = max(1e-7, _diagonal(all_points) * 1e-6)
    boundary: List[Segment] = []
    for start, end in segments:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= _EPS:
            continue
        middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        normal = (-dy / length, dx / length)
        left = (
            middle[0] + normal[0] * sample,
            middle[1] + normal[1] * sample,
        )
        right = (
            middle[0] - normal[0] * sample,
            middle[1] - normal[1] * sample,
        )
        inside_left = predicate(
            _inside_regions(left, regions_first),
            _inside_regions(left, regions_second),
        )
        inside_right = predicate(
            _inside_regions(right, regions_first),
            _inside_regions(right, regions_second),
        )
        if inside_left == inside_right:
            continue
        boundary.append((start, end) if inside_left else (end, start))
    return _regions_from_loops(_trace_loops(boundary))


def _region_loops(regions: Sequence[Region]) -> List[Loop]:
    """Flatten hole-aware regions into their boundary loops."""
    loops: List[Loop] = []
    for outer, holes in regions:
        if len(outer) >= 3:
            loops.append(outer)
        loops.extend(hole for hole in holes if len(hole) >= 3)
    return loops


def loop_intersects(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
) -> bool:
    """Return whether two loops overlap or touch along their boundaries."""
    if any(point_in_polygon(point, second) for point in first):
        return True
    if any(point_in_polygon(point, first) for point in second):
        return True
    for index, start in enumerate(first):
        end = first[(index + 1) % len(first)]
        for other_index, other_start in enumerate(second):
            other_end = second[(other_index + 1) % len(second)]
            if _segment_intersection(
                start, end, other_start, other_end
            ) is not None:
                return True
    return False


def loop_cuts_selection(
    cutter: Sequence[Sequence[float]],
    selected: Sequence[Sequence[Sequence[float]]],
) -> bool:
    """Return whether ``cutter`` should be subtracted from a selection.

    A cutter counts when it lies inside the selected material or overlaps it
    partly.  A loop that merely surrounds the whole selection is not a cutter;
    selecting an inner circle must keep the disk instead of cutting it away.
    """
    if len(cutter) < 3 or not selected:
        return False
    if any(loop_inside(cutter, loop) for loop in selected):
        return True
    if any(loop_inside(loop, cutter) for loop in selected):
        return False
    return any(loop_intersects(cutter, loop) for loop in selected)


def loop_inside(
    inner: Sequence[Sequence[float]],
    outer: Sequence[Sequence[float]],
) -> bool:
    """Return whether ``inner`` lies entirely inside ``outer``.

    Vertices and edge midpoints are sampled so a concave loop that crosses
    ``outer`` is not mistaken for a contained one.
    """
    if len(inner) < 3 or len(outer) < 3:
        return False
    for index, point in enumerate(inner):
        following = inner[(index + 1) % len(inner)]
        samples = (
            (float(point[0]), float(point[1])),
            (
                (float(point[0]) + float(following[0])) / 2.0,
                (float(point[1]) + float(following[1])) / 2.0,
            ),
        )
        for sample in samples:
            if not point_in_polygon(sample, outer):
                return False
    return True


def _union_components(loops: Sequence[Loop]) -> List[Loop]:
    """Union only loops that overlap or touch, keeping nesting levels apart."""
    if not loops:
        return []
    if len(loops) == 1:
        return union_profiles(loops)
    parent = list(range(len(loops)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    for first in range(len(loops)):
        for second in range(first + 1, len(loops)):
            if _loops_connected(loops[first], loops[second]):
                union(first, second)

    groups: Dict[int, List[Loop]] = {}
    for index, loop in enumerate(loops):
        groups.setdefault(find(index), []).append(loop)
    result: List[Loop] = []
    for group in groups.values():
        result.extend(union_profiles(group))
    return result


def _loops_connected(first: Loop, second: Loop) -> bool:
    """Return whether two loops share material rather than just nesting."""
    if loop_inside(first, second) or loop_inside(second, first):
        return False
    return loop_intersects(first, second)


def _unique_loops(loops: Sequence[Loop]) -> List[Loop]:
    """Drop loops that describe the same boundary as an earlier one."""
    seen: Set[Tuple[Point2, ...]] = set()
    result: List[Loop] = []
    for loop in loops:
        key = tuple(sorted(_point_key(point) for point in loop))
        if key in seen:
            continue
        seen.add(key)
        result.append(loop)
    return result


def union_profiles(
    loops: Sequence[Sequence[Sequence[float]]],
) -> List[Loop]:
    """Return the boundary loops of the union of filled profiles.

    Profiles that touch along an edge or overlap are merged, so only their
    outer contour remains.  Disjoint profiles stay separate loops.
    """
    cleaned = [_clean_loop(loop) for loop in loops]
    cleaned = [loop for loop in cleaned if len(loop) >= 3]
    if not cleaned:
        return []
    if len(cleaned) == 1:
        return cleaned

    segments = _split_segments(cleaned)
    if not segments:
        return []
    boundary = _boundary_edges(segments, cleaned)
    return _trace_loops(boundary)


def _clean_loop(loop: Sequence[Sequence[float]]) -> Loop:
    result: Loop = []
    for point in loop:
        current = (float(point[0]), float(point[1]))
        if not result or not _same_point(result[-1], current):
            result.append(current)
    if len(result) >= 2 and _same_point(result[0], result[-1]):
        result.pop()
    return _remove_collinear(result)


def simplify_loop(loop: Sequence[Sequence[float]]) -> Loop:
    """Return a loop without duplicate or collinear vertices."""
    return _clean_loop(loop)


def split_loop_at_points(
    loop: Sequence[Sequence[float]],
    points: Sequence[Sequence[float]],
) -> Loop:
    """Insert points that lie inside the edges of one closed loop.

    Boolean results remove collinear vertices while walls may keep them.
    Re-running this on both sides of a shared edge restores identical
    subdivisions and keeps the rendered mesh closed.
    """
    result: Loop = []
    count = len(loop)
    for index, raw_start in enumerate(loop):
        start = (float(raw_start[0]), float(raw_start[1]))
        raw_end = loop[(index + 1) % count]
        end = (float(raw_end[0]), float(raw_end[1]))
        result.append(start)
        inserted: List[Tuple[float, Point2]] = []
        for raw in points:
            point = (float(raw[0]), float(raw[1]))
            if _same_point(point, start) or _same_point(point, end):
                continue
            if not _point_on_segment(point, start, end):
                continue
            inserted.append((_segment_parameter(point, start, end), point))
        inserted.sort(key=lambda item: item[0])
        for _, point in inserted:
            if not _same_point(result[-1], point):
                result.append(point)
    if len(result) >= 2 and _same_point(result[0], result[-1]):
        result.pop()
    return result


def _remove_collinear(loop: Loop) -> Loop:
    """Drop points that only continue a straight boundary edge."""
    changed = True
    while changed and len(loop) >= 3:
        changed = False
        cleaned: Loop = []
        count = len(loop)
        for index, current in enumerate(loop):
            previous = loop[index - 1]
            following = loop[(index + 1) % count]
            dx1 = current[0] - previous[0]
            dy1 = current[1] - previous[1]
            dx2 = following[0] - current[0]
            dy2 = following[1] - current[1]
            cross = dx1 * dy2 - dy1 * dx2
            dot = dx1 * dx2 + dy1 * dy2
            if abs(cross) <= 1e-9 and dot > 0.0:
                changed = True
                continue
            cleaned.append(current)
        loop = cleaned
    return loop


def _split_segments(loops: Sequence[Loop]) -> List[Segment]:
    """Split all profile edges at shared vertices and intersections."""
    raw: List[Segment] = []
    vertices: List[Point2] = []
    for loop in loops:
        for index, point in enumerate(loop):
            raw.append((point, loop[(index + 1) % len(loop)]))
            vertices.append(point)

    unique: Dict[Tuple[Tuple[int, int], Tuple[int, int]], Segment] = {}
    for index, (start, end) in enumerate(raw):
        params = [0.0, 1.0]
        for vertex in vertices:
            if _point_on_segment(vertex, start, end):
                params.append(_segment_parameter(vertex, start, end))
        for other_index, (other_start, other_end) in enumerate(raw):
            if other_index == index:
                continue
            crossing = _segment_intersection(
                start, end, other_start, other_end
            )
            if crossing is not None:
                params.append(_segment_parameter(crossing, start, end))
        parameters = _unique_parameters(params)
        for lower, upper in zip(parameters, parameters[1:]):
            first = _lerp(start, end, lower)
            second = _lerp(start, end, upper)
            if _distance(first, second) <= _EPS:
                continue
            key = _segment_key(first, second)
            unique[key] = (first, second)
    return list(unique.values())


def _unique_parameters(params: Sequence[float]) -> List[float]:
    ordered = sorted(max(0.0, min(1.0, value)) for value in params)
    result: List[float] = []
    for value in ordered:
        if not result or abs(value - result[-1]) > 1e-9:
            result.append(value)
    return result


def _boundary_edges(
    segments: Sequence[Segment], loops: Sequence[Loop]
) -> List[Segment]:
    """Keep edges with union material on one side and empty space on the other."""
    all_points = [point for segment in segments for point in segment]
    diagonal = _diagonal(all_points)
    sample = max(1e-7, diagonal * 1e-6)
    boundary: List[Segment] = []
    for start, end in segments:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= _EPS:
            continue
        middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        normal = (-dy / length, dx / length)
        left = (middle[0] + normal[0] * sample, middle[1] + normal[1] * sample)
        right = (
            middle[0] - normal[0] * sample,
            middle[1] - normal[1] * sample,
        )
        inside_left = _inside_union(left, loops)
        inside_right = _inside_union(right, loops)
        if inside_left == inside_right:
            continue
        boundary.append((start, end) if inside_left else (end, start))
    return boundary


def _inside_union(point: Point2, loops: Sequence[Loop]) -> bool:
    return any(point_in_polygon(point, loop) for loop in loops)


def _trace_loops(edges: Sequence[Segment]) -> List[Loop]:
    outgoing: Dict[Point2, List[Point2]] = {}
    points: Dict[Point2, Point2] = {}
    for start, end in edges:
        start_key = _point_key(start)
        end_key = _point_key(end)
        points[start_key] = start
        points[end_key] = end
        outgoing.setdefault(start_key, []).append(end_key)

    used: Set[Tuple[Point2, Point2]] = set()
    loops: List[Loop] = []
    for start, end in edges:
        start_key = _point_key(start)
        end_key = _point_key(end)
        if (start_key, end_key) in used:
            continue
        keys: List[Point2] = []
        current = (start_key, end_key)
        closed = False
        while True:
            if current in used:
                break
            used.add(current)
            keys.append(current[0])
            if current[1] == start_key:
                closed = True
                break
            candidates = [
                candidate
                for candidate in outgoing.get(current[1], [])
                if (current[1], candidate) not in used
            ]
            if not candidates:
                break
            following = _next_edge(
                points[current[1]], points[current[0]], candidates, points,
            )
            current = (current[1], following)
        if not closed or len(keys) < 3:
            continue
        loop = _clean_loop([points[key] for key in keys])
        if len(loop) < 3 or len(set(loop)) != len(loop):
            continue
        if polygon_area(loop) < 0.0:
            loop.reverse()
        if abs(polygon_area(loop)) > _EPS:
            loops.append(loop)
    return loops


def _next_edge(
    origin: Point2,
    previous: Point2,
    candidates: Sequence[Point2],
    points: Dict[Point2, Point2],
) -> Point2:
    """Pick the boundary edge that keeps the union interior on the left."""
    reverse_angle = math.atan2(
        previous[1] - origin[1], previous[0] - origin[0]
    )
    best = candidates[0]
    best_turn = float("inf")
    for candidate in candidates:
        point = points[candidate]
        angle = math.atan2(point[1] - origin[1], point[0] - origin[0])
        turn = (reverse_angle - angle) % (2.0 * math.pi)
        if turn <= 1e-9:
            turn = 2.0 * math.pi
        if turn < best_turn:
            best = candidate
            best_turn = turn
    return best


def _segment_intersection(
    a: Point2, b: Point2, c: Point2, d: Point2
) -> Optional[Point2]:
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) <= _EPS:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        return _lerp(a, b, t)
    return None


def _segment_parameter(point: Point2, start: Point2, end: Point2) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= _EPS:
        return 0.0
    return ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq


def _point_on_segment(point: Point2, start: Point2, end: Point2) -> bool:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= _EPS:
        return _same_point(point, start)
    cross = abs(
        (point[0] - start[0]) * dy - (point[1] - start[1]) * dx
    )
    if cross > max(1e-7, length * 1e-7):
        return False
    dot = (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    return -1e-7 <= dot <= length * length + 1e-7


def _lerp(start: Point2, end: Point2, amount: float) -> Point2:
    return (
        start[0] + (end[0] - start[0]) * amount,
        start[1] + (end[1] - start[1]) * amount,
    )


def _distance(first: Point2, second: Point2) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


def _same_point(first: Point2, second: Point2) -> bool:
    return _distance(first, second) <= 1e-7


def _segment_key(first: Point2, second: Point2) -> Tuple[Point2, Point2]:
    first_key = _point_key(first)
    second_key = _point_key(second)
    return (
        (first_key, second_key)
        if first_key <= second_key
        else (second_key, first_key)
    )


def _point_key(point: Point2) -> Point2:
    return (round(point[0], 7), round(point[1], 7))


def _diagonal(points: Sequence[Point2]) -> float:
    if not points:
        return 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))
