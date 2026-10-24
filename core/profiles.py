"""Pure 2D profile geometry for sketch loops and extruded solids."""

import math
from typing import Dict, List, Optional, Sequence, Set, Tuple

Point2 = Tuple[float, float]
Loop = List[Point2]
Segment = Tuple[Point2, Point2]

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
