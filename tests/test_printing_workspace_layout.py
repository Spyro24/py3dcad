"""Tests for the printing workspace layout and layer-height validation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from core.document import Document
from core.sketch import Extrude, Sketch
from core.ui.layout import Rect
from core.workspace_protoprinting.printer_catalog import load_printer_catalog
from core.workspace_protoprinting.ui_integration import (
    LAYER_HEIGHT_WARNING_THRESHOLD,
    LayerHeightWarning,
    PrintingWorkspaceUI,
)

from .harness import check


def test_printer_catalog_reads_placeholder_json() -> None:
    """Printer data and global settings come from the JSON file."""
    catalog = load_printer_catalog()

    check(len(catalog.printers) >= 1, "no printers were loaded")
    printer = catalog.default_printer()
    check(bool(printer.name), "default printer has no name")
    check(
        all(size > 0 for size in printer.build_volume),
        "printer build volume is not positive",
    )
    check(
        catalog.warning_threshold >= LAYER_HEIGHT_WARNING_THRESHOLD,
        "warning threshold relaxed below 0.1 mm",
    )


def test_layer_height_below_point_one_warns() -> None:
    """Every value below 0.1 mm is a warning; 0.1 mm is safe."""
    ui = PrintingWorkspaceUI()

    check(
        ui.set_layer_height(0.09) is LayerHeightWarning.WARNING,
        "0.09 mm did not warn",
    )
    check(
        ui.set_layer_height(0.1) is LayerHeightWarning.OK,
        "0.1 mm should be safe",
    )
    check(
        ui.set_layer_height(0.0) is LayerHeightWarning.ERROR,
        "zero layer height should be an error",
    )


def test_layer_height_warning_message_names_the_threshold() -> None:
    """The warning explains the 0.1 mm minimum."""
    ui = PrintingWorkspaceUI()
    ui.set_layer_height(0.05)

    message = ui.layer_height_warning_message

    check("Warning" in message, "warning label is missing")
    check("0.10" in message, "warning does not name the threshold")


def test_printing_content_uses_quarter_half_quarter_columns() -> None:
    """The viewport is the middle half; each side panel is a quarter."""
    ui = PrintingWorkspaceUI()
    left, middle, right = ui._column_rects(Rect(0, 100, 1000, 500))

    check(left.w == 250, f"left panel width was {left.w}")
    check(middle.w == 500, f"viewport width was {middle.w}")
    check(right.w == 250, f"right panel width was {right.w}")
    check(middle.x == left.right, "viewport does not start after left panel")
    check(right.x == middle.right, "right panel does not follow viewport")


def test_selecting_printer_adopts_its_default_layer_height() -> None:
    """Printer selection replaces the layer height with the JSON default."""
    ui = PrintingWorkspaceUI()
    printer = ui.printer_info["sla_printer_001"]

    check(
        ui.set_selected_printer(printer.id),
        "known printer was rejected",
    )
    check(ui.selected_printer == printer.id, "printer was not selected")
    check(
        abs(ui.selected_layer_height - printer.default_layer_height) < 1e-9,
        "printer default layer height was not adopted",
    )


def test_load_printer_config_replaces_catalog() -> None:
    """A loaded config replaces printers and adopts its default settings."""
    ui = PrintingWorkspaceUI()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "custom_printers.json"
        path.write_text(
            json.dumps({
                "printers": [{
                    "id": "custom_printer",
                    "name": "Custom Printer",
                    "type": "SLA",
                    "status": "ready",
                    "capabilities": {
                        "build_volume": {
                            "width": 100.0,
                            "depth": 120.0,
                            "height": 140.0,
                        },
                        "supported_materials": ["RESIN"],
                    },
                    "default_settings": {"layer_height": 0.05},
                }],
            }),
            encoding="utf-8",
        )

        error = ui.load_printer_config(str(path))

        check(error == "", f"valid config was rejected: {error}")
        check(str(ui.config_path) == str(path), "config path was not stored")

    check(
        [printer.id for printer in ui.catalog.printers] == ["custom_printer"],
        "catalog was not replaced",
    )
    check(ui.selected_printer == "custom_printer", "printer was not selected")
    check(
        abs(ui.selected_layer_height - 0.05) < 1e-9,
        "loaded default layer height was not adopted",
    )


def test_load_printer_config_rejects_unusable_file() -> None:
    """A missing or malformed config leaves the current catalog untouched."""
    ui = PrintingWorkspaceUI()
    before = [printer.id for printer in ui.catalog.printers]

    error = ui.load_printer_config("/definitely/not/here/printers.json")

    check(error != "", "missing config did not report an error")
    check(
        [printer.id for printer in ui.catalog.printers] == before,
        "failed load changed the catalog",
    )


def test_settings_tab_opens_load_config_dialog() -> None:
    """The settings tab exposes a button that opens the config dialog."""
    ui = PrintingWorkspaceUI()
    region = Rect(0, 100, 1000, 500)
    ui.set_active_tab("settings")
    button = ui._settings_load_button_rect(region)

    check(button.w > 0 and button.h > 0, "load button has no size")
    check(ui._handle_click(button.center, region), "click was not handled")
    check(ui.show_load_config_dialog, "config dialog did not open")


def _box_document() -> Document:
    document = Document(id=1)
    document.sketches.append(Sketch(
        id=1,
        name="Box",
        points=[(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        edges=[(0, 1), (1, 2), (2, 3), (3, 0)],
        plane="XY",
    ))
    document.features.append(Extrude(
        id=1,
        name="Box",
        sketch_id=1,
        height=5.0,
        profiles=[[0, 1, 2, 3]],
    ))
    return document


def test_slicing_tab_edits_resolution_and_non_planar() -> None:
    """The slicing tab accepts a resolution value and toggles non-planar."""
    ui = PrintingWorkspaceUI()
    region = Rect(0, 100, 1000, 500)
    ui.set_active_tab("slicing")
    field, toggle, _ = ui._slicing_controls(region)

    check(ui._handle_click(field.center, region), "field click was not handled")
    check(ui._resolution_focus, "resolution field did not focus")
    for character in "0.6":
        ui._handle_resolution_key(pygame.event.Event(
            pygame.KEYDOWN, key=0, unicode=character, mod=0
        ))
    ui._handle_resolution_key(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0
    ))
    check(
        abs(ui.model_resolution - 0.6) < 1e-9,
        f"resolution was {ui.model_resolution}",
    )

    ui._handle_click(toggle.center, region)
    check(ui.non_planar, "non-planar toggle did not turn on")
    ui._handle_click(toggle.center, region)
    check(not ui.non_planar, "non-planar toggle did not turn off")


def test_slicing_button_generates_gcode_from_the_document() -> None:
    """The Slice Model button meshes, slices and writes G-code."""
    ui = PrintingWorkspaceUI()
    ui.set_document(_box_document())
    ui.set_layer_height(1.0)
    ui.set_model_resolution(2.0)

    result = ui.slice_model()

    check(result is not None, "slicing returned no result")
    check(result.success, f"slicing failed: {result.errors}")
    check(bool(result.gcode), "no G-code was generated")
    check(bool(ui.slice_status), "no slice status was reported")
    check(not ui.slice_error, f"unexpected slice error: {ui.slice_error}")
    check(
        Path(result.gcode_path).exists(),
        "G-code file was not written",
    )
    Path(result.gcode_path).unlink(missing_ok=True)
