"""UI integration for the printing workspace."""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pygame

from ..document import Document
from ..ui.layout import Rect
from .gcode_generator import generate_gcode
from .print_manager import (
    PrintJob,
    PrintParameters,
    PrintStatus,
    get_print_manager,
)
from .printer_catalog import (
    PrinterCatalog,
    PrinterInfo,
    load_printer_catalog,
    read_printer_catalog,
)
from .printer_config import get_printer_manager
from .slicer import clamp_resolution, slice_document
from .slice_planner import (
    SliceResult,
    SliceSettings,
    get_slice_planner,
)
from .support_generator import (
    SupportGeneratorSettings,
    get_support_generator,
)

ViewportDraw = Callable[[pygame.Surface, Rect], None]


class LayerHeightWarning(Enum):
    """How safe the selected layer height is."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


LAYER_HEIGHT_WARNING_THRESHOLD = 0.1
MAX_LAYER_HEIGHT = 1.0
LAYER_HEIGHT_PRESETS = (0.05, 0.1, 0.2, 0.3)
TABS = (
    ("Jobs", "jobs"),
    ("Slicing", "slicing"),
    ("Support", "support"),
    ("Settings", "settings"),
)


class PrintingWorkspaceUI:
    """Draws the printing workspace and routes its input."""

    def __init__(self) -> None:
        self.print_manager = get_print_manager()
        self.printer_manager = get_printer_manager()
        self.slice_planner = get_slice_planner()
        self.support_generator = get_support_generator()
        self.config_path = Path(__file__).with_name("printers.json")
        self.catalog: PrinterCatalog = load_printer_catalog(self.config_path)

        self.visible = False
        self.active_tab = "jobs"
        default_printer = self.catalog.default_printer()
        self.selected_printer = default_printer.id
        self.selected_job: Optional[PrintJob] = None
        self.show_job_dialog = False
        self.show_slice_dialog = False
        self.show_support_dialog = False
        self.show_settings_dialog = False
        self.show_load_config_dialog = False
        self.load_config_path = str(self.config_path)
        self.load_config_error = ""

        self.selected_layer_height = default_printer.default_layer_height
        self.layer_height_warning = LayerHeightWarning.OK
        self._layer_height_text = f"{self.selected_layer_height:.3f}"
        self._layer_height_focus = False
        self._layer_height_replace = True
        self._refresh_layer_height_warning()

        self.model_resolution = 1.0
        self._resolution_text = f"{self.model_resolution:.2f}"
        self._resolution_focus = False
        self._resolution_replace = True
        self.non_planar = False
        self.document: Optional[Document] = None
        self.last_slice_result: Optional[SliceResult] = None
        self.slice_status = ""
        self.slice_error = ""

        self.new_job_name = ""
        self.new_job_file = ""
        self._scale = 1.0
        self._hover_tab: Optional[str] = None
        self._hover_printer: Optional[str] = None
        self._hover_job: Optional[str] = None
        self._hover_preset = -1
        self._hover_action: Optional[str] = None
        self._viewport_draw: Optional[ViewportDraw] = None

        self._font_small: Optional[pygame.font.Font] = None
        self._font_normal: Optional[pygame.font.Font] = None
        self._font_large: Optional[pygame.font.Font] = None

        self.bg_color = pygame.Color(26, 26, 30)
        self.card_bg = pygame.Color(35, 35, 40)
        self.header_bg = pygame.Color(43, 43, 50)
        self.border_color = pygame.Color(52, 52, 60)
        self.accent = pygame.Color(59, 130, 246)
        self.text_primary = pygame.Color(230, 230, 235)
        self.text_secondary = pygame.Color(176, 176, 184)
        self.text_muted = pygame.Color(130, 130, 140)
        self.error_color = pygame.Color(235, 100, 100)
        self.success_color = pygame.Color(52, 211, 153)
        self.warning_color = pygame.Color(251, 146, 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def printer_info(self) -> Dict[str, PrinterInfo]:
        """Return the configured printers keyed by ID."""
        return {printer.id: printer for printer in self.catalog.printers}

    @property
    def printer_settings(self) -> Dict:
        """Return the global settings block from the placeholder JSON."""
        return dict(self.catalog.settings)

    @property
    def selected_printer_info(self) -> Optional[PrinterInfo]:
        """Return the currently selected printer."""
        return self.catalog.get(self.selected_printer)

    @property
    def layer_height_warning_message(self) -> str:
        """Return a warning or error message for the current layer height."""
        threshold = self.catalog.warning_threshold
        if self.layer_height_warning is LayerHeightWarning.ERROR:
            return "Enter a layer height above 0 mm."
        if self.layer_height_warning is LayerHeightWarning.WARNING:
            return (
                f"Warning: {self.selected_layer_height:.3f} mm is below "
                f"{threshold:.2f} mm."
            )
        return ""

    def set_scale(self, scale: float) -> None:
        """Set UI scale and refresh cached fonts."""
        if abs(scale - self._scale) < 1e-6:
            return
        self._scale = scale
        self._font_small = None
        self._font_normal = None
        self._font_large = None

    def toggle_visibility(self) -> None:
        """Toggle the visibility of the printing workspace."""
        self.visible = not self.visible
        if not self.visible:
            self.close_all_dialogs()

    def is_visible(self) -> bool:
        """Return whether the printing workspace is visible."""
        return self.visible

    def set_active_tab(self, tab: str) -> None:
        """Set the active tab."""
        if tab in {key for _, key in TABS}:
            self.active_tab = tab
            self._layer_height_focus = False
            self._resolution_focus = False

    def set_selected_printer(self, printer_id: str) -> bool:
        """Select a printer and adopt its default layer height."""
        printer = self.catalog.get(printer_id)
        if printer is None:
            return False
        self.selected_printer = printer.id
        self.set_layer_height(printer.default_layer_height)
        return True

    def set_layer_height(self, value: float) -> LayerHeightWarning:
        """Select a layer height and return the resulting warning level."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        if not math.isfinite(number):
            number = 0.0
        self.selected_layer_height = max(
            0.0, min(MAX_LAYER_HEIGHT, number)
        )
        self._layer_height_text = f"{self.selected_layer_height:.3f}"
        self._layer_height_replace = False
        return self._refresh_layer_height_warning()

    # ------------------------------------------------------------------
    # Model resolution and non-planar slicing
    # ------------------------------------------------------------------

    def set_document(self, document: Optional[Document]) -> None:
        """Remember the active design document for slicing."""
        self.document = document

    def set_model_resolution(self, value: float) -> float:
        """Select the maximum mesh triangle edge length in millimetres."""
        self.model_resolution = clamp_resolution(value)
        self._resolution_text = f"{self.model_resolution:.2f}"
        self._resolution_replace = False
        return self.model_resolution

    def set_non_planar(self, enabled: bool) -> None:
        """Enable or disable conformal top-surface printing."""
        self.non_planar = bool(enabled)

    def _focus_resolution(self) -> None:
        self._resolution_focus = True
        self._layer_height_focus = False
        self._resolution_replace = True
        self._resolution_text = f"{self.model_resolution:.2f}"

    def _commit_resolution_text(self) -> None:
        try:
            value = float(self._resolution_text)
        except ValueError:
            value = self.model_resolution
        if not math.isfinite(value) or value <= 0.0:
            value = self.model_resolution
        self.set_model_resolution(value)
        self._resolution_focus = False

    def _handle_resolution_key(self, event: pygame.event.Event) -> bool:
        """Edit the model resolution field."""
        if event.key == pygame.K_ESCAPE:
            self._resolution_focus = False
            self._resolution_text = f"{self.model_resolution:.2f}"
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_resolution_text()
            return True
        if event.key == pygame.K_BACKSPACE:
            if self._resolution_replace:
                self._resolution_text = ""
                self._resolution_replace = False
            else:
                self._resolution_text = self._resolution_text[:-1]
            return True
        character = getattr(event, "unicode", "")
        if character and (character.isdigit() or character == "."):
            if self._resolution_replace:
                self._resolution_text = character
                self._resolution_replace = False
            elif len(self._resolution_text) < 6:
                self._resolution_text += character
        return True

    # ------------------------------------------------------------------
    # Printer configuration
    # ------------------------------------------------------------------

    def open_load_config_dialog(self) -> None:
        """Open the dialog used to pick a printer config file."""
        self.show_load_config_dialog = True
        self.load_config_path = str(self.config_path)
        self.load_config_error = ""
        self._layer_height_focus = False
        self._resolution_focus = False

    def close_load_config_dialog(self) -> None:
        """Close the printer config dialog."""
        self.show_load_config_dialog = False
        self.load_config_error = ""

    def load_printer_config(self, path: str) -> str:
        """Load printer config from ``path``.

        Returns an empty string on success, or a message describing why the
        file could not be used.  The current catalog is left untouched when
        loading fails.
        """
        text = path.strip()
        if not text:
            return "Please enter a config file path."
        config_path = Path(text).expanduser()
        catalog = read_printer_catalog(config_path)
        if catalog is None:
            return "Could not read a printer config from that file."
        self.catalog = catalog
        self.config_path = config_path
        printer = catalog.get(self.selected_printer)
        if printer is None:
            printer = catalog.default_printer()
        self.set_selected_printer(printer.id)
        self.close_load_config_dialog()
        return ""

    def _handle_load_config_key(self, event: pygame.event.Event) -> bool:
        """Edit the config path field or submit the dialog."""
        if event.key == pygame.K_ESCAPE:
            self.close_load_config_dialog()
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.load_config_error = self.load_printer_config(
                self.load_config_path
            )
            return True
        if event.key == pygame.K_BACKSPACE:
            self.load_config_path = self.load_config_path[:-1]
            self.load_config_error = ""
            return True
        character = getattr(event, "unicode", "")
        if (
            character
            and character.isprintable()
            and len(self.load_config_path) < 300
        ):
            self.load_config_path += character
            self.load_config_error = ""
        return True

    # ------------------------------------------------------------------
    # Print jobs and slicing
    # ------------------------------------------------------------------

    def open_new_job_dialog(self) -> None:
        """Open the new print job dialog."""
        self.show_job_dialog = True
        self.new_job_name = ""
        self.new_job_file = ""

    def close_job_dialog(self) -> None:
        """Close the new print job dialog."""
        self.show_job_dialog = False

    def create_print_job(self) -> Optional[PrintJob]:
        """Create a print job using the selected printer and layer height."""
        if not self.new_job_name.strip():
            return None
        parameters = PrintParameters(
            machine_id=self.selected_printer,
            layer_height=self.selected_layer_height,
        )
        job = self.print_manager.create_print_job(
            name=self.new_job_name,
            model_file=self.new_job_file,
            parameters=parameters,
        )
        if job is not None:
            self.close_job_dialog()
        return job

    def open_slice_dialog(self) -> None:
        """Open the slice configuration dialog."""
        self.show_slice_dialog = True

    def close_slice_dialog(self) -> None:
        """Close the slice configuration dialog."""
        self.show_slice_dialog = False

    def slice_model(self) -> Optional[SliceResult]:
        """Mesh and slice the active document with the current settings.

        The generated G-code is written next to the selected job (or to
        ``/tmp/py3dcad_slice.gcode`` when no job is selected).
        """
        self.slice_status = ""
        self.slice_error = ""
        document = self.document
        if document is None or not document.features:
            self.slice_error = "No model geometry to slice."
            return None

        material = (
            self.selected_job.parameters.material
            if self.selected_job is not None else "PLA"
        )
        profile = self.slice_planner.material_profiles.get(material, {})
        settings = SliceSettings(
            layer_height=self.selected_layer_height,
            material=material,
            support_enabled=True,
            enable_optimization=True,
            infill_density=0.2,
            model_resolution=self.model_resolution,
            non_planar=self.non_planar,
            extrusion_width=0.4,
            print_speed=60.0,
            travel_speed=120.0,
            nozzle_temperature=profile.get("nozzle_temp", 200.0),
            bed_temperature=profile.get("bed_temp", 60.0),
        )
        result = slice_document(document, settings)
        self.last_slice_result = result
        if not result.success:
            self.slice_error = (
                "; ".join(result.errors) or "Slicing failed."
            )
            return result

        result.gcode = generate_gcode(result, settings)
        result.gcode_size = len(result.gcode.encode("utf-8"))
        path = (
            f"/tmp/{self.selected_job.job_id}.gcode"
            if self.selected_job is not None
            else "/tmp/py3dcad_slice.gcode"
        )
        try:
            Path(path).write_text(result.gcode, encoding="utf-8")
        except OSError as error:
            self.slice_error = f"Could not write G-code: {error}"
            return result
        result.gcode_path = path
        if self.selected_job is not None:
            self.selected_job.status = PrintStatus.READY
            self.selected_job.gcode_path = path
        self.slice_status = (
            f"{result.total_layers} layers | "
            f"{result.mesh_triangles} triangles | "
            f"{len(result.gcode.splitlines())} G-code lines"
        )
        self._resolution_focus = False
        return result

    def open_support_dialog(self) -> None:
        """Open the support generation dialog."""
        self.show_support_dialog = True

    def close_support_dialog(self) -> None:
        """Close the support generation dialog."""
        self.show_support_dialog = False

    def generate_support(self) -> Optional[SliceResult]:
        """Generate supports for the selected job."""
        if self.selected_job is None:
            return None
        settings = SupportGeneratorSettings(
            enabled=True,
            type="tree",
            thickness=0.4,
            density=0.3,
            max_overhang_angle=45.0,
        )
        result = self.support_generator.generate_support(
            overhangs=[],
            settings=settings,
            layer_height=self.selected_layer_height,
        )
        self.close_support_dialog()
        return result

    def close_all_dialogs(self) -> None:
        """Close every printing dialog."""
        self.show_job_dialog = False
        self.show_slice_dialog = False
        self.show_support_dialog = False
        self.show_settings_dialog = False
        self.close_load_config_dialog()

    def select_job(self, job: PrintJob) -> None:
        """Select a print job."""
        self.selected_job = job

    # ------------------------------------------------------------------
    # Layer height helpers
    # ------------------------------------------------------------------

    def _refresh_layer_height_warning(self) -> LayerHeightWarning:
        """Recompute the warning level for the selected layer height."""
        value = self.selected_layer_height
        threshold = self.catalog.warning_threshold
        if value <= 0.0:
            warning = LayerHeightWarning.ERROR
        elif value < threshold - 1e-9:
            warning = LayerHeightWarning.WARNING
        else:
            warning = LayerHeightWarning.OK
        self.layer_height_warning = warning
        return warning

    def _focus_layer_height(self) -> None:
        """Focus the numeric field and select its contents."""
        self._layer_height_focus = True
        self._resolution_focus = False
        self._layer_height_replace = True
        self._layer_height_text = f"{self.selected_layer_height:.3f}"

    def _commit_layer_height_text(self) -> None:
        """Commit the typed layer height, reverting invalid input."""
        try:
            value = float(self._layer_height_text)
        except ValueError:
            value = self.selected_layer_height
        if math.isfinite(value) and 0.0 < value <= MAX_LAYER_HEIGHT:
            self.selected_layer_height = value
        elif value <= 0.0:
            self.selected_layer_height = 0.0
        self._layer_height_text = f"{self.selected_layer_height:.3f}"
        self._layer_height_focus = False
        self._refresh_layer_height_warning()

    def _preview_layer_height_text(self) -> None:
        """Apply a valid in-progress value so the warning updates live."""
        try:
            value = float(self._layer_height_text)
        except ValueError:
            return
        if not math.isfinite(value):
            return
        self.selected_layer_height = max(
            0.0, min(MAX_LAYER_HEIGHT, value)
        )
        self._refresh_layer_height_warning()

    def _handle_layer_height_key(self, event: pygame.event.Event) -> bool:
        """Edit the focused layer height field."""
        if event.key == pygame.K_ESCAPE:
            self._layer_height_focus = False
            self._layer_height_text = f"{self.selected_layer_height:.3f}"
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_layer_height_text()
            return True
        if event.key == pygame.K_BACKSPACE:
            if self._layer_height_replace:
                self._layer_height_text = ""
                self._layer_height_replace = False
            else:
                self._layer_height_text = self._layer_height_text[:-1]
            self._preview_layer_height_text()
            return True
        character = getattr(event, "unicode", "")
        if character and (character.isdigit() or character == "."):
            if self._layer_height_replace:
                self._layer_height_text = character
                self._layer_height_replace = False
            elif len(self._layer_height_text) < 7:
                self._layer_height_text += character
            self._preview_layer_height_text()
        return True

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self._scale)))

    def _init_fonts(self) -> None:
        if self._font_small is not None:
            return
        self._font_small = pygame.font.SysFont(
            "Segoe UI", self._s(12)
        )
        self._font_normal = pygame.font.SysFont(
            "Segoe UI", self._s(14)
        )
        self._font_large = pygame.font.SysFont(
            "Segoe UI", self._s(16), bold=True
        )

    def _toolbar_buttons(self, region: Rect) -> List[Tuple[str, str, Rect]]:
        """Return tab buttons as ``(label, tab, rect)`` tuples."""
        toolbar_y = region.y + self._s(50)
        height = self._s(40)
        width = region.w // len(TABS)
        return [
            (
                label,
                tab,
                Rect(
                    region.x + index * width,
                    toolbar_y,
                    width,
                    height,
                ),
            )
            for index, (label, tab) in enumerate(TABS)
        ]

    def _content_rect(self, region: Rect) -> Rect:
        top = region.y + self._s(90)
        return Rect(region.x, top, region.w, max(0, region.bottom - top))

    def _column_rects(
        self, region: Rect
    ) -> Tuple[Rect, Rect, Rect]:
        """Split the content into left 1/4, middle 1/2 and right 1/4."""
        content = self._content_rect(region)
        left_width = content.w // 4
        right_width = content.w // 4
        middle_width = content.w - left_width - right_width
        left = Rect(content.x, content.y, left_width, content.h)
        middle = Rect(
            content.x + left_width, content.y, middle_width, content.h
        )
        right = Rect(middle.right, content.y, right_width, content.h)
        return left, middle, right

    def _layer_height_geometry(
        self, region: Rect
    ) -> Tuple[Rect, List[Rect]]:
        left, _, _ = self._column_rects(region)
        padding = self._s(12)
        field_y = left.y + self._s(52)
        field = Rect(
            left.x + padding,
            field_y,
            left.w - padding * 2 - self._s(30),
            self._s(30),
        )
        preset_y = field.bottom + self._s(10)
        gap = self._s(5)
        preset_width = (
            left.w - padding * 2 - gap * (len(LAYER_HEIGHT_PRESETS) - 1)
        ) // len(LAYER_HEIGHT_PRESETS)
        presets = [
            Rect(
                left.x + padding + index * (preset_width + gap),
                preset_y,
                preset_width,
                self._s(24),
            )
            for index in range(len(LAYER_HEIGHT_PRESETS))
        ]
        return field, presets

    def _left_tab_rect(self, region: Rect) -> Rect:
        left, _, _ = self._column_rects(region)
        padding = self._s(12)
        _, presets = self._layer_height_geometry(region)
        top = presets[-1].bottom + self._s(48)
        return Rect(
            left.x + padding,
            top,
            left.w - padding * 2,
            max(0, left.bottom - top - self._s(12)),
        )

    def _bottom_button_rect(self, region: Rect) -> Rect:
        tab = self._left_tab_rect(region)
        return Rect(
            tab.x,
            tab.bottom - self._s(48),
            tab.w,
            self._s(36),
        )

    def _settings_load_button_rect(self, region: Rect) -> Rect:
        """Return the Load Printer Config button inside the settings tab."""
        return self._bottom_button_rect(region)

    def _slicing_controls(
        self, region: Rect
    ) -> Tuple[Rect, Rect, int]:
        """Return the resolution field, non-planar toggle and info top."""
        return self._slicing_controls_in_tab(self._left_tab_rect(region))

    def _slicing_controls_in_tab(
        self, tab: Rect
    ) -> Tuple[Rect, Rect, int]:
        """Return slicing controls for an already computed tab rectangle."""
        field = Rect(
            tab.x,
            tab.y + self._s(32),
            tab.w - self._s(34),
            self._s(28),
        )
        toggle = Rect(
            tab.x,
            field.bottom + self._s(12),
            tab.w,
            self._s(22),
        )
        return field, toggle, toggle.bottom + self._s(10)

    def _printer_rows(
        self, region: Rect
    ) -> List[Tuple[PrinterInfo, Rect]]:
        _, _, right = self._column_rects(region)
        padding = self._s(12)
        y = right.y + self._s(38)
        row_height = self._s(26)
        rows = []
        for printer in self.catalog.printers:
            rows.append((
                printer,
                Rect(
                    right.x + padding,
                    y,
                    right.w - padding * 2,
                    row_height,
                ),
            ))
            y += row_height + self._s(4)
        return rows

    def _job_rows(
        self, region: Rect, limit: int = 8
    ) -> List[Tuple[PrintJob, Rect]]:
        return self._job_rows_in_area(self._left_tab_rect(region), limit)

    def _job_rows_in_area(
        self, area: Rect, limit: int = 8
    ) -> List[Tuple[PrintJob, Rect]]:
        row_height = self._s(30)
        rows = []
        for index, job in enumerate(self.print_manager.list_jobs()[-limit:]):
            y = area.y + self._s(28) + index * (row_height + self._s(4))
            if y + row_height > area.bottom:
                break
            rows.append((job, Rect(area.x, y, area.w, row_height)))
        return rows

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_event(
        self, event: pygame.event.Event, region: Rect
    ) -> bool:
        """Handle printing workspace input."""
        if not self.visible:
            return False
        if event.type == pygame.KEYDOWN and self.show_load_config_dialog:
            return self._handle_load_config_key(event)
        if event.type == pygame.KEYDOWN and self._layer_height_focus:
            return self._handle_layer_height_key(event)
        if event.type == pygame.KEYDOWN and self._resolution_focus:
            return self._handle_resolution_key(event)
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos, region)
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self._dialog_open():
                self.close_all_dialogs()
                return True
            if self._layer_height_focus:
                self._layer_height_focus = False
                return True
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_click(event.pos, region)
        return False

    def _dialog_open(self) -> bool:
        return any((
            self.show_job_dialog,
            self.show_slice_dialog,
            self.show_support_dialog,
            self.show_settings_dialog,
            self.show_load_config_dialog,
        ))

    def _handle_click(
        self, pos: Tuple[int, int], region: Rect
    ) -> bool:
        """Route one left click to a printing workspace control."""
        if self._dialog_open():
            return True
        for _, tab, rect in self._toolbar_buttons(region):
            if rect.collidepoint(pos):
                self.set_active_tab(tab)
                return True
        field, presets = self._layer_height_geometry(region)
        if field.collidepoint(pos):
            self._focus_layer_height()
            return True
        for index, rect in enumerate(presets):
            if rect.collidepoint(pos):
                self.set_layer_height(LAYER_HEIGHT_PRESETS[index])
                return True
        for printer, rect in self._printer_rows(region):
            if rect.collidepoint(pos):
                self.set_selected_printer(printer.id)
                return True
        if self.active_tab == "jobs":
            for job, rect in self._job_rows(region):
                if rect.collidepoint(pos):
                    self.select_job(job)
                    return True
        if self.active_tab == "slicing":
            field, toggle, _ = self._slicing_controls(region)
            if field.collidepoint(pos):
                self._focus_resolution()
                return True
            if toggle.collidepoint(pos):
                self.set_non_planar(not self.non_planar)
                return True
            if self._bottom_button_rect(region).collidepoint(pos):
                self.slice_model()
                return True
        if self.active_tab == "support":
            if self._bottom_button_rect(region).collidepoint(pos):
                self.generate_support()
                return True
        if self.active_tab == "settings":
            if self._settings_load_button_rect(region).collidepoint(pos):
                self.open_load_config_dialog()
                return True
        self._layer_height_focus = False
        self._resolution_focus = False
        return True

    def _update_hover(
        self, pos: Tuple[int, int], region: Rect
    ) -> None:
        """Update hover highlights for every interactive control."""
        self._hover_tab = None
        self._hover_printer = None
        self._hover_job = None
        self._hover_preset = -1
        self._hover_action = None
        for _, tab, rect in self._toolbar_buttons(region):
            if rect.collidepoint(pos):
                self._hover_tab = tab
                break
        for planner, rect in self._printer_rows(region):
            if rect.collidepoint(pos):
                self._hover_printer = planner.id
                break
        _, presets = self._layer_height_geometry(region)
        for index, rect in enumerate(presets):
            if rect.collidepoint(pos):
                self._hover_preset = index
                break
        if self.active_tab == "jobs":
            for job, rect in self._job_rows(region):
                if rect.collidepoint(pos):
                    self._hover_job = job.job_id
                    break
        if self.active_tab in ("slicing", "support"):
            if self._bottom_button_rect(region).collidepoint(pos):
                self._hover_action = self.active_tab
        if self.active_tab == "settings":
            if self._settings_load_button_rect(region).collidepoint(pos):
                self._hover_action = "load_config"

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(
        self,
        surface: pygame.Surface,
        region: Rect,
        viewport_draw: Optional[ViewportDraw] = None,
    ) -> None:
        """Draw the printing workspace."""
        if not self.visible:
            return
        self._init_fonts()
        self._viewport_draw = viewport_draw
        pygame.draw.rect(surface, self.bg_color, region.rect)
        self._draw_header(surface, region)
        self._draw_toolbar(surface, region)
        self._draw_content(surface, region, viewport_draw)
        if self.show_job_dialog:
            self._draw_new_job_dialog(surface, region)
        if self.show_slice_dialog:
            self._draw_slice_dialog(surface, region)
        if self.show_support_dialog:
            self._draw_support_dialog(surface, region)
        if self.show_load_config_dialog:
            self._draw_load_config_dialog(surface, region)

    def _draw_header(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        height = self._s(50)
        header = Rect(region.x, region.y, region.w, height)
        pygame.draw.rect(surface, self.card_bg, header.rect)
        title = self._font_large.render(
            "Printing Workspace", True, self.text_primary
        )
        surface.blit(
            title, (region.x + self._s(16), region.y + self._s(15))
        )
        printer = self.selected_printer_info
        if printer is not None:
            label = self._font_normal.render(
                printer.name, True, self.text_secondary
            )
            surface.blit(
                label,
                (
                    region.x + region.w // 4,
                    region.y + self._s(17),
                ),
            )
            status = self._font_small.render(
                printer.status, True, self._get_printer_status_color(
                    printer.status
                ),
            )
            surface.blit(
                status,
                (
                    region.right - self._s(16) - status.get_width(),
                    region.y + self._s(18),
                ),
            )

    def _draw_toolbar(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        for label, tab, rect in self._toolbar_buttons(region):
            active = self.active_tab == tab
            hovered = self._hover_tab == tab and not active
            background = (
                self.accent if active
                else (self.card_bg if hovered else self.bg_color)
            )
            pygame.draw.rect(surface, background, rect.rect)
            color = (
                pygame.Color(255, 255, 255)
                if active else self.text_primary
            )
            text = self._font_normal.render(label, True, color)
            surface.blit(text, text.get_rect(center=rect.center))
        _, _, right = self._column_rects(region)
        pygame.draw.line(
            surface,
            self.border_color,
            (region.x, right.y - 1),
            (region.right, right.y - 1),
        )

    def _draw_content(
        self,
        surface: pygame.Surface,
        region: Rect,
        viewport_draw: Optional[ViewportDraw],
    ) -> None:
        left, middle, right = self._column_rects(region)
        self._draw_left_panel(surface, region, left)
        self._draw_viewport(surface, middle, viewport_draw)
        self._draw_right_panel(surface, region, right)

    def _draw_left_panel(
        self, surface: pygame.Surface, region: Rect, panel: Rect
    ) -> None:
        pygame.draw.rect(surface, self.card_bg, panel.rect)
        pygame.draw.line(
            surface, self.border_color,
            (panel.right - 1, panel.y), (panel.right - 1, panel.bottom),
        )
        caption = self._font_small.render(
            "PRINT SETTINGS", True, self.text_secondary
        )
        surface.blit(
            caption, (panel.x + self._s(12), panel.y + self._s(12))
        )
        self._draw_layer_height_control(surface, region)
        tab = self._left_tab_rect(region)
        if self.active_tab == "jobs":
            self._draw_jobs_tab(surface, tab, tab.y, tab.h)
        elif self.active_tab == "slicing":
            self._draw_slicing_tab(surface, tab, tab.y, tab.h)
        elif self.active_tab == "support":
            self._draw_support_tab(surface, tab, tab.y, tab.h)
        else:
            self._draw_settings_tab(surface, tab, tab.y, tab.h)

    def _draw_layer_height_control(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        field, presets = self._layer_height_geometry(region)
        label = self._font_small.render(
            "LAYER HEIGHT", True, self.text_secondary
        )
        surface.blit(label, (field.x, field.y - self._s(20)))
        border = self.accent if self._layer_height_focus else self.border_color
        pygame.draw.rect(
            surface, self.bg_color, field.rect, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, border, field.rect, width=1,
            border_radius=self._s(4),
        )
        text = (
            self._layer_height_text
            if self._layer_height_focus
            else f"{self.selected_layer_height:.3f}"
        )
        if self._layer_height_focus:
            text += "_"
        value = self._font_normal.render(text, True, self.text_primary)
        surface.blit(value, (field.x + self._s(8), field.y + self._s(7)))
        unit = self._font_small.render("mm", True, self.text_muted)
        surface.blit(unit, (field.right + self._s(6), field.y + self._s(9)))

        for index, (preset, rect) in enumerate(
            zip(LAYER_HEIGHT_PRESETS, presets)
        ):
            selected = abs(self.selected_layer_height - preset) < 1e-6
            hovered = self._hover_preset == index
            color = (
                self.accent if selected
                else (self.border_color if hovered else self.bg_color)
            )
            pygame.draw.rect(
                surface, color, rect.rect, border_radius=self._s(3)
            )
            pygame.draw.rect(
                surface, self.border_color, rect.rect, width=1,
                border_radius=self._s(3),
            )
            text_color = (
                self.text_primary if selected else self.text_secondary
            )
            preset_text = self._font_small.render(
                f"{preset:.2f}", True, text_color
            )
            surface.blit(
                preset_text, preset_text.get_rect(center=rect.center)
            )

        message = self.layer_height_warning_message
        if message:
            color = (
                self.error_color
                if self.layer_height_warning is LayerHeightWarning.ERROR
                else self.warning_color
            )
            warning = self._font_small.render(message, True, color)
            surface.blit(warning, (field.x, presets[-1].bottom + self._s(8)))

    def _draw_jobs_tab(
        self,
        surface: pygame.Surface,
        region: Rect,
        y: int,
        height: int,
    ) -> None:
        title = self._font_small.render("JOBS", True, self.text_secondary)
        surface.blit(title, (region.x, y))
        jobs = self._job_rows_in_area(
            region, len(self.print_manager.list_jobs())
        )
        if not jobs:
            empty = self._font_small.render(
                "No print jobs yet", True, self.text_muted
            )
            surface.blit(empty, (region.x, y + self._s(28)))
            return
        for job, rect in jobs:
            selected = self.selected_job is job
            hovered = self._hover_job == job.job_id
            if selected or hovered:
                pygame.draw.rect(
                    surface, self.header_bg, rect.rect,
                    border_radius=self._s(3),
                )
            name = self._font_small.render(
                job.name, True, self.text_primary
            )
            surface.blit(name, (rect.x + self._s(6), rect.y + self._s(6)))
            status = self._font_small.render(
                job.status.value, True, self._get_status_color(job.status)
            )
            surface.blit(
                status,
                (rect.right - status.get_width() - self._s(6), rect.y + self._s(6)),
            )

    def _draw_slicing_tab(
        self,
        surface: pygame.Surface,
        region: Rect,
        y: int,
        height: int,
    ) -> None:
        title = self._font_small.render(
            "SLICING", True, self.text_secondary
        )
        surface.blit(title, (region.x, y))

        field, toggle, info_y = self._slicing_controls_in_tab(region)
        label = self._font_small.render(
            "MODEL RESOLUTION", True, self.text_muted
        )
        surface.blit(label, (field.x, field.y - self._s(18)))
        border = (
            self.accent if self._resolution_focus else self.border_color
        )
        pygame.draw.rect(
            surface, self.bg_color, field.rect, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, border, field.rect, width=1, border_radius=self._s(4)
        )
        text = (
            self._resolution_text
            if self._resolution_focus
            else f"{self.model_resolution:.2f}"
        )
        if self._resolution_focus:
            text += "_"
        rendered = self._font_normal.render(text, True, self.text_primary)
        surface.blit(
            rendered, (field.x + self._s(8), field.y + self._s(6))
        )
        unit = self._font_small.render("mm", True, self.text_muted)
        surface.blit(unit, (field.right + self._s(6), field.y + self._s(8)))

        box = pygame.Rect(
            toggle.x, toggle.y + self._s(3),
            self._s(14), self._s(14),
        )
        pygame.draw.rect(surface, self.bg_color, box, border_radius=self._s(2))
        pygame.draw.rect(
            surface, self.border_color, box, width=1,
            border_radius=self._s(2),
        )
        if self.non_planar:
            pygame.draw.rect(
                surface, self.accent, box.inflate(-6, -6),
                border_radius=self._s(1),
            )
        toggle_label = self._font_small.render(
            "Non-planar top surfaces", True, self.text_primary
        )
        surface.blit(
            toggle_label,
            (toggle.x + self._s(20), toggle.y + self._s(3)),
        )

        job_name = (
            self.selected_job.name
            if self.selected_job is not None else "No job selected"
        )
        triangles = (
            str(self.last_slice_result.mesh_triangles)
            if self.last_slice_result is not None else "-"
        )
        lines = (
            ("Job", job_name),
            ("Triangles", triangles),
            ("Non-planar", "On" if self.non_planar else "Off"),
        )
        self._draw_info_lines(surface, region, info_y, lines)

        status_y = region.bottom - self._s(66)
        status = self.slice_error or self.slice_status
        if status:
            color = self.error_color if self.slice_error else self.success_color
            text = self._font_small.render(status, True, color)
            previous_clip = surface.get_clip()
            surface.set_clip(region.rect)
            surface.blit(text, (region.x, status_y))
            surface.set_clip(previous_clip)

        self._draw_action_button(
            surface,
            region,
            "Slice Model",
            self._hover_action == "slicing",
        )

    def _draw_support_tab(
        self,
        surface: pygame.Surface,
        region: Rect,
        y: int,
        height: int,
    ) -> None:
        title = self._font_small.render(
            "SUPPORT", True, self.text_secondary
        )
        surface.blit(title, (region.x, y))
        lines = (
            ("Type", "Tree"),
            ("Density", "30%"),
            ("Thickness", "0.4 mm"),
            ("Max overhang", "45 deg"),
        )
        self._draw_info_lines(surface, region, y + self._s(26), lines)
        self._draw_action_button(
            surface,
            region,
            "Generate Support",
            self._hover_action == "support",
        )

    def _draw_settings_tab(
        self,
        surface: pygame.Surface,
        region: Rect,
        y: int,
        height: int,
    ) -> None:
        title = self._font_small.render(
            "WORKSPACE SETTINGS", True, self.text_secondary
        )
        surface.blit(title, (region.x, y))
        settings = self.catalog.settings
        lines = (
            ("Printers", str(len(self.catalog.printers))),
            ("Warning below", f"{self.catalog.warning_threshold:.2f} mm"),
            ("Save folder", str(settings.get("save_directory", "-"))),
            ("Auto save", "On" if settings.get("auto_save_enabled") else "Off"),
            ("Config file", self.config_path.name),
        )
        self._draw_info_lines(surface, region, y + self._s(26), lines)
        self._draw_action_button(
            surface,
            region,
            "Load Printer Config",
            self._hover_action == "load_config",
        )

    def _draw_info_lines(
        self,
        surface: pygame.Surface,
        region: Rect,
        y: int,
        lines: Tuple[Tuple[str, str], ...],
    ) -> None:
        for label, value in lines:
            label_text = self._font_small.render(
                label, True, self.text_muted
            )
            value_text = self._font_small.render(
                value, True, self.text_primary
            )
            surface.blit(label_text, (region.x, y))
            surface.blit(value_text, (region.x, y + self._s(16)))
            y += self._s(34)

    def _draw_action_button(
        self,
        surface: pygame.Surface,
        region: Rect,
        label: str,
        hovered: bool,
    ) -> None:
        button = Rect(
            region.x,
            region.bottom - self._s(48),
            region.w,
            self._s(36),
        )
        color = self.accent if hovered else self.card_bg
        pygame.draw.rect(
            surface, color, button.rect, border_radius=self._s(4)
        )
        pygame.draw.rect(
            surface, self.border_color, button.rect, width=1,
            border_radius=self._s(4),
        )
        text = self._font_normal.render(label, True, self.text_primary)
        surface.blit(text, text.get_rect(center=button.center))

    def _draw_right_panel(
        self, surface: pygame.Surface, region: Rect, panel: Rect
    ) -> None:
        pygame.draw.rect(surface, self.card_bg, panel.rect)
        pygame.draw.line(
            surface, self.border_color,
            (panel.x, panel.y), (panel.x, panel.bottom),
        )
        caption = self._font_small.render(
            "PRINTERS", True, self.text_secondary
        )
        surface.blit(
            caption, (panel.x + self._s(12), panel.y + self._s(12))
        )
        rows = self._printer_rows(region)
        for printer, rect in rows:
            selected = printer.id == self.selected_printer
            hovered = printer.id == self._hover_printer
            if selected or hovered:
                pygame.draw.rect(
                    surface, self.header_bg, rect.rect,
                    border_radius=self._s(3),
                )
            name = self._font_small.render(
                printer.name, True,
                self.accent if selected else self.text_primary,
            )
            surface.blit(name, (rect.x + self._s(5), rect.y + self._s(5)))
        if rows:
            detail_y = rows[-1][1].bottom + self._s(12)
            self._draw_printer_details(surface, panel, detail_y)

    def _draw_printer_details(
        self, surface: pygame.Surface, panel: Rect, y: int
    ) -> None:
        printer = self.selected_printer_info
        if printer is None:
            return
        title = self._font_small.render(
            "SELECTED PRINTER", True, self.text_secondary
        )
        surface.blit(title, (panel.x + self._s(12), y))
        y += self._s(20)
        volume = printer.build_volume
        lines = (
            ("Type", printer.kind),
            ("Status", printer.status),
            (
                "Build volume",
                f"{volume[0]:.0f} x {volume[1]:.0f} x {volume[2]:.0f} mm",
            ),
            ("Nozzle", f"{printer.nozzle_diameter:.3f} mm"),
            (
                "Layer range",
                f"{printer.min_layer_height:.2f} - "
                f"{printer.max_layer_height:.2f} mm",
            ),
            ("Materials", ", ".join(printer.materials[:3]) or "-"),
            ("Location", printer.location or "-"),
        )
        for label, value in lines:
            label_text = self._font_small.render(
                label, True, self.text_muted
            )
            value_text = self._font_small.render(
                value, True, self.text_primary
            )
            surface.blit(label_text, (panel.x + self._s(12), y))
            surface.blit(
                value_text,
                (panel.x + panel.w // 2, y),
            )
            y += self._s(22)

    def _draw_viewport(
        self,
        surface: pygame.Surface,
        region: Rect,
        viewport_draw: Optional[ViewportDraw],
    ) -> None:
        pygame.draw.rect(surface, self.bg_color, region.rect)
        if viewport_draw is not None:
            viewport_draw(surface, region)
        else:
            self._draw_viewport_placeholder(surface, region)
        pygame.draw.rect(
            surface, self.border_color, region.rect, width=1
        )
        self._draw_viewport_labels(surface, region)

    def _draw_viewport_placeholder(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        center = region.center
        width = region.w // 2
        height = region.h // 3
        bed = pygame.Rect(
            center[0] - width // 2,
            center[1] - height // 2,
            width,
            height,
        )
        pygame.draw.rect(surface, self.card_bg, bed, border_radius=self._s(6))
        pygame.draw.rect(surface, self.accent, bed, width=1)
        for step in range(1, 4):
            x = bed.x + bed.w * step // 4
            y = bed.y + bed.h * step // 4
            pygame.draw.line(
                surface, self.border_color,
                (x, bed.y), (x, bed.bottom),
            )
            pygame.draw.line(
                surface, self.border_color,
                (bed.x, y), (bed.right, y),
            )
        text = self._font_normal.render(
            "No model loaded", True, self.text_secondary
        )
        surface.blit(text, text.get_rect(center=center))

    def _draw_viewport_labels(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        bar = Rect(
            region.x, region.y, region.w, self._s(26)
        )
        pygame.draw.rect(surface, self.card_bg, bar.rect)
        title = self._font_small.render(
            "PRINT PREVIEW", True, self.text_secondary
        )
        surface.blit(
            title, (bar.x + self._s(10), bar.y + self._s(6))
        )
        printer = self.selected_printer_info
        if printer is not None:
            volume = printer.build_volume
            label = self._font_small.render(
                f"Bed {volume[0]:.0f} x {volume[1]:.0f} x {volume[2]:.0f} mm",
                True, self.text_muted,
            )
            surface.blit(
                label,
                (bar.right - label.get_width() - self._s(10), bar.y + self._s(6)),
            )
        message = self.layer_height_warning_message
        if message:
            color = (
                self.error_color
                if self.layer_height_warning is LayerHeightWarning.ERROR
                else self.warning_color
            )
            warning = self._font_small.render(message, True, color)
            surface.blit(
                warning,
                (
                    region.x + self._s(10),
                    region.bottom - warning.get_height() - self._s(8),
                ),
            )

    # ------------------------------------------------------------------
    # Dialogs kept for API compatibility
    # ------------------------------------------------------------------

    def _draw_dialog_shell(
        self,
        surface: pygame.Surface,
        region: Rect,
        width: int,
        height: int,
        title: str,
    ) -> Rect:
        overlay = pygame.Surface(region.rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surface.blit(overlay, region.rect.topleft)
        dialog = Rect(
            region.x + (region.w - width) // 2,
            region.y + (region.h - height) // 2,
            width,
            height,
        )
        pygame.draw.rect(
            surface, self.card_bg, dialog.rect,
            border_radius=self._s(8),
        )
        pygame.draw.rect(
            surface, self.border_color, dialog.rect, width=1,
            border_radius=self._s(8),
        )
        text = self._font_large.render(title, True, self.text_primary)
        surface.blit(
            text, (dialog.x + self._s(20), dialog.y + self._s(20))
        )
        return dialog

    def _draw_new_job_dialog(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        dialog = self._draw_dialog_shell(
            surface, region, self._s(420), self._s(300), "New Print Job"
        )
        lines = (
            ("Job name", self.new_job_name or "-"),
            ("File", self.new_job_file or "-"),
            ("Printer", self.selected_printer_info.name
             if self.selected_printer_info else "-"),
            ("Layer height", f"{self.selected_layer_height:.3f} mm"),
        )
        y = dialog.y + self._s(64)
        for label, value in lines:
            label_text = self._font_small.render(
                label, True, self.text_muted
            )
            value_text = self._font_small.render(
                value, True, self.text_primary
            )
            surface.blit(label_text, (dialog.x + self._s(20), y))
            surface.blit(value_text, (dialog.x + self._s(20), y + self._s(16)))
            y += self._s(42)
        hint = self._font_small.render(
            "Close with Escape", True, self.text_muted
        )
        surface.blit(
            hint,
            (dialog.right - hint.get_width() - self._s(20),
             dialog.bottom - self._s(28)),
        )

    def _draw_slice_dialog(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        dialog = self._draw_dialog_shell(
            surface, region, self._s(420), self._s(260), "Slice Model"
        )
        self._draw_dialog_settings(surface, dialog)
        message = self.layer_height_warning_message
        if message:
            warning = self._font_small.render(
                message, True, self.warning_color
            )
            surface.blit(
                warning, (dialog.x + self._s(20), dialog.bottom - self._s(54))
            )

    def _draw_support_dialog(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        dialog = self._draw_dialog_shell(
            surface, region, self._s(420), self._s(260),
            "Generate Support",
        )
        lines = (
            ("Type", "Tree"),
            ("Density", "30%"),
            ("Thickness", "0.4 mm"),
            ("Max overhang", "45 deg"),
        )
        y = dialog.y + self._s(64)
        for label, value in lines:
            label_text = self._font_small.render(
                label, True, self.text_muted
            )
            value_text = self._font_small.render(
                value, True, self.text_primary
            )
            surface.blit(label_text, (dialog.x + self._s(20), y))
            surface.blit(
                value_text,
                (dialog.x + dialog.w // 2, y),
            )
            y += self._s(28)

    def _draw_load_config_dialog(
        self, surface: pygame.Surface, region: Rect
    ) -> None:
        """Draw the path input used to load a printer config file."""
        width = min(
            self._s(640), max(self._s(320), region.w - self._s(40))
        )
        dialog = self._draw_dialog_shell(
            surface, region, width, self._s(214), "Load Printer Config"
        )
        label = self._font_small.render(
            "Config file path", True, self.text_muted
        )
        surface.blit(
            label, (dialog.x + self._s(20), dialog.y + self._s(56))
        )
        field = Rect(
            dialog.x + self._s(20),
            dialog.y + self._s(76),
            dialog.w - self._s(40),
            self._s(34),
        )
        pygame.draw.rect(
            surface, self.bg_color, field.rect,
            border_radius=self._s(4),
        )
        pygame.draw.rect(
            surface, self.border_color, field.rect, width=1,
            border_radius=self._s(4),
        )
        previous_clip = surface.get_clip()
        surface.set_clip(field.rect.inflate(-self._s(8), 0))
        path_text = self._font_small.render(
            self.load_config_path + "_", True, self.text_primary
        )
        surface.blit(
            path_text, (field.x + self._s(8), field.y + self._s(9))
        )
        surface.set_clip(previous_clip)
        hint = self._font_small.render(
            "Enter to load - Escape to cancel", True, self.text_muted
        )
        surface.blit(
            hint, (dialog.x + self._s(20), dialog.y + self._s(124))
        )
        if self.load_config_error:
            error = self._font_small.render(
                self.load_config_error, True, self.error_color
            )
            surface.blit(
                error, (dialog.x + self._s(20), dialog.y + self._s(152))
            )

    def _draw_dialog_settings(
        self, surface: pygame.Surface, dialog: Rect
    ) -> None:
        lines = (
            ("Layer height", f"{self.selected_layer_height:.3f} mm"),
            ("Material", "PLA"),
            ("Support", "Enabled"),
            ("Printer", self.selected_printer_info.name
             if self.selected_printer_info else "-"),
        )
        y = dialog.y + self._s(64)
        for label, value in lines:
            label_text = self._font_small.render(
                label, True, self.text_muted
            )
            value_text = self._font_small.render(
                value, True, self.text_primary
            )
            surface.blit(label_text, (dialog.x + self._s(20), y))
            surface.blit(
                value_text, (dialog.x + dialog.w // 2, y)
            )
            y += self._s(28)

    # ------------------------------------------------------------------
    # Colours
    # ------------------------------------------------------------------

    def _get_status_color(self, status: PrintStatus) -> pygame.Color:
        """Get a colour for a print job status."""
        colors = {
            PrintStatus.PENDING: pygame.Color(255, 204, 0),
            PrintStatus.SLICING: self.accent,
            PrintStatus.READY: self.success_color,
            PrintStatus.PRINTING: pygame.Color(139, 92, 246),
            PrintStatus.COMPLETED: pygame.Color(16, 185, 129),
            PrintStatus.FAILED: self.error_color,
        }
        return colors.get(status, self.text_secondary)

    def _get_job_row_color(self, job: PrintJob) -> pygame.Color:
        """Get a row tint for a print job."""
        colors = {
            PrintStatus.PRINTING: pygame.Color(59, 130, 246, 30),
            PrintStatus.COMPLETED: pygame.Color(16, 185, 129, 30),
            PrintStatus.FAILED: pygame.Color(239, 68, 68, 30),
        }
        return colors.get(job.status, self.bg_color)

    def _get_printer_status_color(self, status: str) -> pygame.Color:
        """Get a colour for a printer status string."""
        colors = {
            "ready": self.success_color,
            "printing": self.accent,
            "error": self.error_color,
            "maintenance": self.warning_color,
        }
        return colors.get(status.lower(), self.text_secondary)


_printing_ui = PrintingWorkspaceUI()


def get_printing_ui() -> PrintingWorkspaceUI:
    """Return the global printing workspace UI instance."""
    return _printing_ui
