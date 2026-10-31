"""Tests for mesh generation, slicing and G-code output."""

from __future__ import annotations

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from core.document import Document
from core.sketch import Extrude, Sketch
from core.workspace_protoprinting.gcode_generator import generate_gcode
from core.workspace_protoprinting.slice_planner import SliceSettings
from core.workspace_protoprinting.slicer import (
    mesh_from_document,
    slice_document,
    slice_triangles,
)

from .harness import check


def box_document(width: float = 20.0, height: float = 10.0) -> Document:
    """Return a document containing one rectangular prism."""
    document = Document(id=1)
    document.sketches.append(Sketch(
        id=1,
        name="Box",
        points=[(0.0, 0.0), (width, 0.0), (width, width), (0.0, width)],
        edges=[(0, 1), (1, 2), (2, 3), (3, 0)],
        plane="XY",
    ))
    document.features.append(Extrude(
        id=1,
        name="Box",
        sketch_id=1,
        height=height,
        profiles=[[0, 1, 2, 3]],
    ))
    return document


def test_mesh_resolution_controls_triangle_count() -> None:
    """A finer model resolution produces a denser, valid mesh."""
    document = box_document()
    coarse = mesh_from_document(document, 2.0)
    fine = mesh_from_document(document, 1.0)

    check(len(coarse) >= 12, "coarse mesh is missing faces")
    check(len(fine) > len(coarse), "finer mesh was not denser")
    for triangle in fine[:200]:
        check(len(triangle) == 3, "triangle does not have three points")
        check(
            len({tuple(point) for point in triangle}) == 3,
            "triangle has duplicate points",
        )


def test_slicer_builds_layers_perimeters_and_infill() -> None:
    """Slicing a box yields one contour and infill per layer."""
    document = box_document(height=10.0)
    settings = SliceSettings(
        layer_height=1.0,
        model_resolution=1.0,
        infill_density=0.2,
        extrusion_width=0.4,
    )

    result = slice_document(document, settings)

    check(result.success, f"slicing failed: {result.errors}")
    check(result.total_layers == 10, f"expected 10 layers, got {result.total_layers}")
    check(result.mesh_triangles > 0, "mesh triangle count was not recorded")
    check(bool(result.layers[0].perimeters), "first layer has no perimeter")
    check(bool(result.layers[0].infill), "first layer has no infill")
    check(result.estimated_filament > 0.0, "filament estimate is zero")


def test_gcode_generator_emits_complete_program() -> None:
    """Generated G-code contains setup, layers and shutdown commands."""
    document = box_document(height=5.0)
    settings = SliceSettings(
        layer_height=1.0,
        model_resolution=2.0,
        infill_density=0.2,
    )
    result = slice_document(document, settings)

    gcode = generate_gcode(result, settings)

    for token in ("G21", "G90", "M82", "G28", "M104", "M140", "M84"):
        check(token in gcode, f"missing {token}")
    check(gcode.count(";LAYER:") == 5, "layer markers do not match layers")
    check("G1 X" in gcode and " E" in gcode, "no extrusion moves")
    check(gcode.rstrip().endswith("end of PY3DCAD gcode"), "no program end")


def test_non_planar_paths_follow_the_surface() -> None:
    """Non-planar toolpaths vary Z across the top surface."""
    ramp = [
        ((0.0, 0.0, 0.0), (20.0, 0.0, 10.0), (20.0, 20.0, 10.0)),
        ((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), (0.0, 20.0, 0.0)),
    ]
    settings = SliceSettings(
        layer_height=1.0,
        model_resolution=0.5,
        infill_density=0.0,
        non_planar=True,
    )

    result = slice_triangles(ramp, settings)
    heights = [
        point[2]
        for path in result.non_planar_paths
        for point in path
    ]

    check(result.success, f"slicing failed: {result.errors}")
    check(bool(result.non_planar_paths), "no non-planar paths were produced")
    check(
        max(heights) - min(heights) > 1.0,
        "non-planar paths do not follow the surface height",
    )
    gcode = generate_gcode(result, settings)
    check(";NONPLANAR_TOP" in gcode, "G-code has no non-planar section")
    check(" Z" in gcode, "non-planar moves have no Z coordinate")
