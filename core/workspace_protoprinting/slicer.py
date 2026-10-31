"""Mesh generation and slicing for the printing workspace.

The module is pure geometry: it never imports pygame.  Faces are turned into
a watertight triangle mesh at the requested model resolution, the mesh is
sliced into planar contours, and optional non-planar top-surface paths follow
the real surface height.

Coordinates are millimetres with Z up, matching the printer workspace.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import math
from typing import Dict, List, Optional, Sequence, Tuple

from ..document import Document
from ..faces import Face, iter_solid_faces
from .slice_planner import SliceLayer, SliceResult, SliceSettings

Point2 = Tuple[float, float]
Point3 = Tuple[float, float, float]
Triangle = Tuple[Point3, Point3, Point3]

MIN_RESOLUTION = 0.05
MAX_RESOLUTION = 10.0
MAX_MESH_TRIANGLES = 200_000
EPSILON = 1e-9


# ---------------------------------------------------------------------------
# Mesh generation
# ---------------------------------------------------------------------------


def clamp_resolution(value: float) -> float:
    """Clamp a model resolution to the supported range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(number):
        return 1.0
    return max(MIN_RESOLUTION, min(MAX_RESOLUTION, number))


def mesh_from_document(
    document: Document, resolution: float = 1.0
) -> List[Triangle]:
    """Triangulate every solid face of ``document``.

    ``resolution`` is the maximum triangle edge length in millimetres.  Long
    triangles are split until they meet it or the global triangle budget is
    reached, so a finer resolution produces a denser mesh for slicing.
    """
    step = clamp_resolution(resolution)
    triangles: List[Triangle] = []
    for _, _, face in iter_solid_faces(document):
        triangles.extend(_triangulate_face(face))
    return _refine_triangles(triangles, step)


def _triangulate_face(face: Face) -> List[Triangle]:
    """Triangulate one planar face, preserving holes."""
    outer = list(face.vertices)
    if len(outer) < 3:
        return []
    holes = [list(hole) for hole in face.holes if len(hole) >= 3]

    normal = _face_normal(outer)
    u_axis = _perpendicular(outer, normal)
    if u_axis is None:
        return _fan_triangles(outer)
    v_axis = _cross(normal, u_axis)

    def project(point: Point3) -> Point2:
        return (
            _dot(point, u_axis),
            _dot(point, v_axis),
        )

    outer_2d = [project(point) for point in outer]
    holes_2d = [[project(point) for point in hole] for hole in holes]
    if _signed_area(outer_2d) < 0.0:
        outer.reverse()
        outer_2d.reverse()
        holes.reverse()
        holes_2d.reverse()
    for hole, hole_2d in zip(holes, holes_2d):
        if _signed_area(hole_2d) > 0.0:
            hole.reverse()
            hole_2d.reverse()

    combined_2d = list(outer_2d)
    combined_3d = list(outer)
    for hole, hole_2d in sorted(
        zip(holes, holes_2d),
        key=lambda item: max(point[0] for point in item[1]),
        reverse=True,
    ):
        combined_2d, combined_3d = _bridge_hole(
            combined_2d, combined_3d, hole_2d, hole
        )

    indices = _ear_clip(combined_2d)
    return [
        (combined_3d[a], combined_3d[b], combined_3d[c])
        for a, b, c in indices
    ]


def _bridge_hole(
    polygon_2d: List[Point2],
    polygon_3d: List[Point3],
    hole_2d: List[Point2],
    hole_3d: List[Point3],
) -> Tuple[List[Point2], List[Point3]]:
    """Connect one hole to the outer polygon with a two-way bridge."""
    start = max(range(len(hole_2d)), key=lambda index: hole_2d[index][0])
    hole_x, hole_y = hole_2d[start]
    best: Optional[Tuple[float, int, float]] = None
    for index in range(len(polygon_2d)):
        a = polygon_2d[index]
        b = polygon_2d[(index + 1) % len(polygon_2d)]
        if (a[1] > hole_y) == (b[1] > hole_y):
            continue
        factor = (hole_y - a[1]) / (b[1] - a[1])
        crossing = a[0] + factor * (b[0] - a[0])
        if crossing < hole_x - EPSILON:
            continue
        if best is None or crossing < best[0]:
            best = (crossing, index, factor)

    ordered_2d = hole_2d[start:] + hole_2d[:start + 1]
    ordered_3d = hole_3d[start:] + hole_3d[:start + 1]

    if best is None:
        # Degenerate fallback: bridge to the nearest outer vertex.
        nearest = min(
            range(len(polygon_2d)),
            key=lambda index: (
                (polygon_2d[index][0] - hole_x) ** 2
                + (polygon_2d[index][1] - hole_y) ** 2
            ),
        )
        polygon_2d = (
            polygon_2d[:nearest + 1]
            + ordered_2d
            + [polygon_2d[nearest]]
            + polygon_2d[nearest + 1:]
        )
        polygon_3d = (
            polygon_3d[:nearest + 1]
            + ordered_3d
            + [polygon_3d[nearest]]
            + polygon_3d[nearest + 1:]
        )
        return polygon_2d, polygon_3d

    crossing, edge, factor = best
    bridge_2d = (crossing, hole_y)
    bridge_3d = _lerp(polygon_3d[edge], polygon_3d[(edge + 1) % len(polygon_3d)], factor)
    bridge = [bridge_2d] + ordered_2d + [bridge_2d]
    bridge3 = [bridge_3d] + ordered_3d + [bridge_3d]
    polygon_2d = polygon_2d[:edge + 1] + bridge + polygon_2d[edge + 1:]
    polygon_3d = polygon_3d[:edge + 1] + bridge3 + polygon_3d[edge + 1:]
    return polygon_2d, polygon_3d


def _ear_clip(polygon: Sequence[Point2]) -> List[Tuple[int, int, int]]:
    """Triangulate a weakly simple CCW polygon with ear clipping."""
    count = len(polygon)
    if count < 3:
        return []
    remaining = list(range(count))
    triangles: List[Tuple[int, int, int]] = []
    guard = 0
    while len(remaining) > 3 and guard < count * count:
        guard += 1
        ear = _find_ear(polygon, remaining)
        if ear is not None:
            triangles.append(ear)
            remaining.remove(ear[1])
            continue
        collinear = _find_collinear(polygon, remaining)
        if collinear is not None:
            remaining.pop(collinear)
            continue
        for index in range(1, len(remaining) - 1):
            triangles.append((
                remaining[0], remaining[index], remaining[index + 1]
            ))
        remaining = []
        break
    if len(remaining) == 3:
        triangles.append((remaining[0], remaining[1], remaining[2]))
    return triangles


def _find_ear(
    polygon: Sequence[Point2], remaining: List[int]
) -> Optional[Tuple[int, int, int]]:
    count = len(remaining)
    for position in range(count):
        i0 = remaining[position - 1]
        i1 = remaining[position]
        i2 = remaining[(position + 1) % count]
        a, b, c = polygon[i0], polygon[i1], polygon[i2]
        if _cross_2d(a, b, c) <= EPSILON:
            continue
        blocked = False
        for index in remaining:
            if index in (i0, i1, i2):
                continue
            point = polygon[index]
            if _same_point(point, a) or _same_point(point, b) or _same_point(point, c):
                continue
            if _point_in_triangle(point, a, b, c):
                blocked = True
                break
        if not blocked:
            return (i0, i1, i2)
    return None


def _find_collinear(
    polygon: Sequence[Point2], remaining: List[int]
) -> Optional[int]:
    for position in range(len(remaining)):
        i0 = remaining[position - 1]
        i1 = remaining[position]
        i2 = remaining[(position + 1) % len(remaining)]
        if abs(_cross_2d(polygon[i0], polygon[i1], polygon[i2])) <= EPSILON:
            return position
    return None


def _refine_triangles(
    triangles: Sequence[Triangle], resolution: float
) -> List[Triangle]:
    """Split triangles until their longest edge fits ``resolution``."""
    limit = resolution * resolution
    refined: List[Triangle] = []
    stack = list(triangles)
    while stack:
        triangle = stack.pop()
        if len(refined) + len(stack) >= MAX_MESH_TRIANGLES:
            refined.append(triangle)
            continue
        a, b, c = triangle
        edges = (
            (0, _distance_squared(a, b), a, b, c),
            (1, _distance_squared(b, c), b, c, a),
            (2, _distance_squared(c, a), c, a, b),
        )
        longest = max(edges, key=lambda item: item[1])
        if longest[1] <= limit:
            refined.append(triangle)
            continue
        _, _, first, second, opposite = longest
        middle = _midpoint(first, second)
        stack.append((first, middle, opposite))
        stack.append((middle, second, opposite))
    return refined


# ---------------------------------------------------------------------------
# Slicing
# ---------------------------------------------------------------------------


def slice_document(
    document: Document, settings: SliceSettings
) -> SliceResult:
    """Build the document mesh and slice it with ``settings``."""
    result = SliceResult(
        resolution=clamp_resolution(settings.model_resolution),
        non_planar=settings.non_planar,
    )
    if document is None or not document.features:
        result.errors.append("No model geometry to slice")
        return result
    triangles = mesh_from_document(document, settings.model_resolution)
    if not triangles:
        result.errors.append("The model has no closed solid to slice")
        return result
    result.mesh_triangles = len(triangles)
    return slice_triangles(triangles, settings, result)


def slice_triangles(
    triangles: Sequence[Triangle],
    settings: SliceSettings,
    result: Optional[SliceResult] = None,
) -> SliceResult:
    """Slice a triangle soup into contours and infill toolpaths."""
    result = result or SliceResult()
    result.resolution = clamp_resolution(settings.model_resolution)
    result.non_planar = settings.non_planar
    result.mesh_triangles = len(triangles)

    errors = _validate_settings(settings)
    if errors:
        result.errors.extend(errors)
        return result
    if not triangles:
        result.errors.append("The mesh is empty")
        return result

    bottom = min(point[2] for triangle in triangles for point in triangle)
    top = max(point[2] for triangle in triangles for point in triangle)
    if top - bottom <= EPSILON:
        result.errors.append("The model has no height to slice")
        return result

    heights = _layer_heights(bottom, top, settings)
    buckets = _bucket_triangles(triangles, heights)
    total_length = 0.0
    for index, height in enumerate(heights):
        segments = _slice_segments(buckets[index], height)
        loops = _stitch_loops(segments)
        layer = SliceLayer(index=index, z=height)
        for loop in loops:
            closed = [*loop, loop[0]]
            layer.perimeters.append(
                [(x, y, height) for x, y in closed]
            )
            total_length += _polyline_length(layer.perimeters[-1])
        for path in _infill_paths(
            loops, settings.extrusion_width, settings.infill_density, height
        ):
            layer.infill.append(path)
            total_length += _polyline_length(path)
        result.layers.append(layer)
        result.layer_heights.append(
            height - heights[index - 1] if index else height - bottom
        )

    result.total_layers = len(result.layers)
    result.total_thickness = sum(result.layer_heights)
    if settings.non_planar:
        result.non_planar_paths = _non_planar_paths(triangles, settings)
        total_length += sum(
            _polyline_length(path) for path in result.non_planar_paths
        )

    filament_area = math.pi * (settings.filament_diameter * 0.5) ** 2
    filament_volume = (
        total_length
        * settings.extrusion_width
        * max(settings.layer_height, 0.01)
    )
    result.estimated_filament = (
        filament_volume / filament_area / 1000.0
        if filament_area > 0.0 else 0.0
    )
    travel = len(result.layers) * 5.0
    result.estimated_time = (
        total_length / max(settings.print_speed, 1.0) + travel
    ) / 60.0
    result.success = True
    if settings.layer_height < 0.1:
        result.warnings.append(
            "Layer height below 0.1 mm significantly increases print time"
        )
    if settings.non_planar:
        result.warnings.append(
            "Non-planar top surfaces require a printer with Z-lift support"
        )
    return result


def _validate_settings(settings: SliceSettings) -> List[str]:
    errors: List[str] = []
    if settings.layer_height <= 0.0:
        errors.append("Layer height must be positive")
    if settings.extrusion_width <= 0.0:
        errors.append("Extrusion width must be positive")
    if not 0.0 <= settings.infill_density <= 1.0:
        errors.append("Infill density must be between 0 and 1")
    return errors


def _layer_heights(
    bottom: float, top: float, settings: SliceSettings
) -> List[float]:
    """Return the world Z of every layer plane."""
    first = settings.initial_layer_height or settings.layer_height
    first = max(0.01, min(first, top - bottom))
    heights: List[float] = []
    height = bottom + first
    while height <= top + 1e-7:
        heights.append(round(height, 6))
        height += settings.layer_height
    if not heights:
        heights.append(top)
    return heights


def _bucket_triangles(
    triangles: Sequence[Triangle], heights: Sequence[float]
) -> List[List[Triangle]]:
    """Assign triangles to the layers whose plane crosses them."""
    buckets: List[List[Triangle]] = [[] for _ in heights]
    for triangle in triangles:
        low = min(point[2] for point in triangle)
        high = max(point[2] for point in triangle)
        if high - low <= EPSILON:
            continue
        start = max(0, bisect_left(heights, low - EPSILON))
        end = min(len(heights), bisect_right(heights, high + EPSILON))
        for index in range(start, end):
            buckets[index].append(triangle)
    return buckets


def _slice_segments(
    triangles: Sequence[Triangle], height: float
) -> List[Tuple[Point2, Point2]]:
    """Intersect triangles with one horizontal plane."""
    segments: List[Tuple[Point2, Point2]] = []
    for triangle in triangles:
        points: List[Point2] = []
        for index in range(3):
            a = triangle[index]
            b = triangle[(index + 1) % 3]
            if (a[2] < height <= b[2]) or (b[2] < height <= a[2]):
                factor = (height - a[2]) / (b[2] - a[2])
                points.append((
                    a[0] + factor * (b[0] - a[0]),
                    a[1] + factor * (b[1] - a[1]),
                ))
        if len(points) == 2 and _distance_squared_2d(points[0], points[1]) > 1e-12:
            segments.append((points[0], points[1]))
    return segments


def _stitch_loops(
    segments: Sequence[Tuple[Point2, Point2]]
) -> List[List[Point2]]:
    """Join line segments into closed contour loops."""
    if not segments:
        return []
    nodes: Dict[Tuple[int, int], List[Tuple[int, Point2]]] = {}
    for index, (start, end) in enumerate(segments):
        nodes.setdefault(_node_key(start), []).append((index, end))
        nodes.setdefault(_node_key(end), []).append((index, start))

    used = [False] * len(segments)
    loops: List[List[Point2]] = []
    for seed in range(len(segments)):
        if used[seed]:
            continue
        used[seed] = True
        start, end = segments[seed]
        loop = [start, end]
        current = end
        while True:
            if len(loop) > 3 and _node_key(current) == _node_key(start):
                loop.pop()
                loops.append(_simplify_loop(loop))
                break
            options = [
                (index, point)
                for index, point in nodes.get(_node_key(current), ())
                if not used[index]
            ]
            if not options:
                break
            if len(options) > 1:
                previous = loop[-2]
                options.sort(
                    key=lambda item: _straightness(previous, current, item[1]),
                    reverse=True,
                )
            index, point = options[0]
            used[index] = True
            loop.append(point)
            current = point
    return [loop for loop in loops if len(loop) >= 3]


def _infill_paths(
    loops: Sequence[Sequence[Point2]],
    width: float,
    density: float,
    height: float,
) -> List[List[Point3]]:
    """Generate alternating horizontal infill spans clipped by the loops."""
    if not loops or density <= 0.0 or width <= 0.0:
        return []
    spacing = max(width, width / max(0.05, density))
    xs = [point[0] for loop in loops for point in loop]
    ys = [point[1] for loop in loops for point in loop]
    if not xs:
        return []
    paths: List[List[Point3]] = []
    row = 0
    y = min(ys) + spacing * 0.5
    while y < max(ys) - 1e-9:
        crossings: List[float] = []
        for loop in loops:
            for index in range(len(loop)):
                a = loop[index]
                b = loop[(index + 1) % len(loop)]
                if (a[1] > y) != (b[1] > y):
                    crossings.append(
                        a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                    )
        crossings.sort()
        for index in range(0, len(crossings) - 1, 2):
            start, end = crossings[index], crossings[index + 1]
            if end - start <= width * 0.5:
                continue
            if row % 2:
                start, end = end, start
            paths.append([
                (start, y, height),
                (end, y, height),
            ])
        row += 1
        y += spacing
    return paths


def _non_planar_paths(
    triangles: Sequence[Triangle], settings: SliceSettings
) -> List[List[Point3]]:
    """Generate top-surface paths whose Z follows the real mesh height."""
    samples = _height_map(triangles, settings.model_resolution)
    if not samples:
        return []
    xmin, ymin, step, heights, width, rows = samples
    paths: List[List[Point3]] = []
    max_delta = max(2.0, step * 2.0)
    for row in range(rows):
        run: List[Point3] = []
        for column in range(width):
            height = heights[row][column]
            if not math.isfinite(height):
                if len(run) >= 2:
                    paths.append(run)
                run = []
                continue
            point = (
                xmin + column * step,
                ymin + row * step,
                height + settings.layer_height,
            )
            if run and abs(point[2] - run[-1][2]) > max_delta:
                if len(run) >= 2:
                    paths.append(run)
                run = []
            run.append(point)
        if len(run) >= 2:
            paths.append(run)
    return paths


def _height_map(
    triangles: Sequence[Triangle], resolution: float
) -> Optional[
    Tuple[float, float, float, List[List[float]], int, int]
]:
    """Rasterise the highest mesh surface onto a regular XY grid."""
    xs = [point[0] for triangle in triangles for point in triangle]
    ys = [point[1] for triangle in triangles for point in triangle]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if xmax - xmin <= EPSILON or ymax - ymin <= EPSILON:
        return None
    step = max(
        clamp_resolution(resolution),
        max(xmax - xmin, ymax - ymin) / 200.0,
    )
    width = int(math.ceil((xmax - xmin) / step)) + 1
    rows = int(math.ceil((ymax - ymin) / step)) + 1
    heights = [[float("-inf")] * width for _ in range(rows)]
    for triangle in triangles:
        a, b, c = triangle
        area = _cross_2d(
            (a[0], a[1]), (b[0], b[1]), (c[0], c[1])
        )
        if abs(area) <= EPSILON:
            continue
        low_x = max(0, int(math.floor((min(a[0], b[0], c[0]) - xmin) / step)))
        high_x = min(
            width - 1,
            int(math.ceil((max(a[0], b[0], c[0]) - xmin) / step)),
        )
        low_y = max(0, int(math.floor((min(a[1], b[1], c[1]) - ymin) / step)))
        high_y = min(
            rows - 1,
            int(math.ceil((max(a[1], b[1], c[1]) - ymin) / step)),
        )
        for row in range(low_y, high_y + 1):
            y = ymin + row * step
            for column in range(low_x, high_x + 1):
                x = xmin + column * step
                z = _triangle_height(a, b, c, x, y)
                if z is not None and z > heights[row][column]:
                    heights[row][column] = z
    return xmin, ymin, step, heights, width, rows


def _triangle_height(
    a: Point3, b: Point3, c: Point3, x: float, y: float
) -> Optional[float]:
    """Return the triangle's Z at ``(x, y)``, or ``None`` when outside."""
    area = _cross_2d(
        (a[0], a[1]), (b[0], b[1]), (c[0], c[1])
    )
    if abs(area) <= EPSILON:
        return None
    wa = _cross_2d((x, y), (b[0], b[1]), (c[0], c[1])) / area
    wb = _cross_2d((a[0], a[1]), (x, y), (c[0], c[1])) / area
    wc = 1.0 - wa - wb
    if wa < -1e-6 or wb < -1e-6 or wc < -1e-6:
        return None
    return wa * a[2] + wb * b[2] + wc * c[2]


# ---------------------------------------------------------------------------
# Small geometry helpers
# ---------------------------------------------------------------------------


def _face_normal(points: Sequence[Point3]) -> Point3:
    nx = ny = nz = 0.0
    for index in range(len(points)):
        current = points[index]
        following = points[(index + 1) % len(points)]
        nx += (current[1] - following[1]) * (current[2] + following[2])
        ny += (current[2] - following[2]) * (current[0] + following[0])
        nz += (current[0] - following[0]) * (current[1] + following[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= EPSILON:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _perpendicular(
    points: Sequence[Point3], normal: Point3
) -> Optional[Point3]:
    for index in range(1, len(points)):
        edge = _subtract(points[index], points[0])
        projected = _subtract(edge, _scale(normal, _dot(edge, normal)))
        length = math.sqrt(_dot(projected, projected))
        if length > EPSILON:
            return _scale(projected, 1.0 / length)
    return None


def _fan_triangles(points: Sequence[Point3]) -> List[Triangle]:
    return [
        (points[0], points[index], points[index + 1])
        for index in range(1, len(points) - 1)
    ]


def _simplify_loop(points: List[Point2]) -> List[Point2]:
    """Drop duplicate and collinear contour points."""
    cleaned: List[Point2] = []
    for point in points:
        if not cleaned or _distance_squared_2d(cleaned[-1], point) > 1e-12:
            cleaned.append(point)
    if len(cleaned) < 3:
        return cleaned
    changed = True
    while changed and len(cleaned) > 3:
        changed = False
        for index in range(len(cleaned)):
            previous = cleaned[index - 1]
            current = cleaned[index]
            following = cleaned[(index + 1) % len(cleaned)]
            if abs(_cross_2d(previous, current, following)) <= 1e-9:
                cleaned.pop(index)
                changed = True
                break
    return cleaned


def _polyline_length(points: Sequence[Point3]) -> float:
    return sum(
        math.sqrt(
            (points[index][0] - points[index - 1][0]) ** 2
            + (points[index][1] - points[index - 1][1]) ** 2
            + (points[index][2] - points[index - 1][2]) ** 2
        )
        for index in range(1, len(points))
    )


def _node_key(point: Point2) -> Tuple[int, int]:
    return (round(point[0] * 1e5), round(point[1] * 1e5))


def _straightness(
    previous: Point2, current: Point2, following: Point2
) -> float:
    ax, ay = current[0] - previous[0], current[1] - previous[1]
    bx, by = following[0] - current[0], following[1] - current[1]
    length = math.hypot(ax, ay) * math.hypot(bx, by)
    if length <= EPSILON:
        return -1.0
    return (ax * bx + ay * by) / length


def _signed_area(points: Sequence[Point2]) -> float:
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _point_in_triangle(
    point: Point2, a: Point2, b: Point2, c: Point2
) -> bool:
    d1 = _cross_2d(point, a, b)
    d2 = _cross_2d(point, b, c)
    d3 = _cross_2d(point, c, a)
    negative = d1 < -EPSILON or d2 < -EPSILON or d3 < -EPSILON
    positive = d1 > EPSILON or d2 > EPSILON or d3 > EPSILON
    return not (negative and positive)


def _cross_2d(a: Point2, b: Point2, c: Point2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _same_point(a: Point2, b: Point2) -> bool:
    return abs(a[0] - b[0]) <= EPSILON and abs(a[1] - b[1]) <= EPSILON


def _distance_squared(a: Point3, b: Point3) -> float:
    return (
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


def _distance_squared_2d(a: Point2, b: Point2) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _midpoint(a: Point3, b: Point3) -> Point3:
    return (
        (a[0] + b[0]) * 0.5,
        (a[1] + b[1]) * 0.5,
        (a[2] + b[2]) * 0.5,
    )


def _lerp(a: Point3, b: Point3, factor: float) -> Point3:
    return (
        a[0] + (b[0] - a[0]) * factor,
        a[1] + (b[1] - a[1]) * factor,
        a[2] + (b[2] - a[2]) * factor,
    )


def _subtract(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(point: Point3, factor: float) -> Point3:
    return (point[0] * factor, point[1] * factor, point[2] * factor)


def _dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Point3, b: Point3) -> Point3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
