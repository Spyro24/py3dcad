"""G-code generation for sliced print jobs."""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from .slice_planner import SliceResult, SliceSettings

Point3 = Tuple[float, float, float]


def generate_gcode(result: SliceResult, settings: SliceSettings) -> str:
    """Turn a slice result into absolute-position Marlin-style G-code."""
    lines: List[str] = [
        "; PY3DCAD slicer",
        f"; layer_height={settings.layer_height:.3f}mm",
        f"; model_resolution={settings.model_resolution:.3f}mm",
        f"; non_planar={'1' if settings.non_planar else '0'}",
        f"; triangles={result.mesh_triangles}",
        "G21 ; millimetres",
        "G90 ; absolute positioning",
        "M82 ; absolute extrusion",
        f"M140 S{settings.bed_temperature:.0f} ; bed temperature",
        f"M104 S{settings.nozzle_temperature:.0f} ; nozzle temperature",
        f"M190 S{settings.bed_temperature:.0f} ; wait for bed",
        f"M109 S{settings.nozzle_temperature:.0f} ; wait for nozzle",
        "G28 ; home all axes",
        "G92 E0",
        "M106 S255 ; part cooling fan",
    ]
    extrusion = _extrusion_per_mm(settings)
    current = 0.0
    for layer in result.layers:
        lines.append(f";LAYER:{layer.index} Z{layer.z:.3f}")
        lines.append(f"G0 Z{layer.z:.3f} F{settings.travel_speed * 60:.0f}")
        for path in layer.perimeters:
            current = _emit_path(
                lines, path, settings, extrusion, current, planar=True
            )
        for path in layer.infill:
            current = _emit_path(
                lines, path, settings, extrusion, current, planar=True
            )
    for path in result.non_planar_paths:
        lines.append(";NONPLANAR_TOP")
        current = _emit_path(
            lines, path, settings, extrusion, current, planar=False
        )
    lines.extend([
        f"G1 E{max(0.0, current - 1.0):.5f} F{settings.print_speed * 60:.0f}",
        "G92 E0",
        "M107 ; fan off",
        "M104 S0 ; nozzle off",
        "M140 S0 ; bed off",
        "G28 X Y ; park",
        "M84 ; motors off",
        "; end of PY3DCAD gcode",
    ])
    return "\n".join(lines) + "\n"


def _emit_path(
    lines: List[str],
    path: Sequence[Point3],
    settings: SliceSettings,
    extrusion: float,
    current: float,
    planar: bool,
) -> float:
    """Append one toolpath and return the new absolute extrusion total."""
    if len(path) < 2:
        return current
    first = path[0]
    travel = f"G0 X{first[0]:.3f} Y{first[1]:.3f}"
    if not planar:
        travel += f" Z{first[2]:.3f}"
    lines.append(f"{travel} F{settings.travel_speed * 60:.0f}")
    previous = first
    for point in path[1:]:
        distance = math.sqrt(
            (point[0] - previous[0]) ** 2
            + (point[1] - previous[1]) ** 2
            + ((point[2] - previous[2]) ** 2 if not planar else 0.0)
        )
        current += distance * extrusion
        z_part = "" if planar else f" Z{point[2]:.3f}"
        lines.append(
            f"G1 X{point[0]:.3f} Y{point[1]:.3f}{z_part} "
            f"E{current:.5f} F{settings.print_speed * 60:.0f}"
        )
        previous = point
    return current


def _extrusion_per_mm(settings: SliceSettings) -> float:
    """Return filament length per travelled millimetre."""
    filament_area = math.pi * (settings.filament_diameter * 0.5) ** 2
    if filament_area <= 0.0:
        return 0.0
    return (
        settings.extrusion_width * settings.layer_height / filament_area
    )
