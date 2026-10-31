"""Printer metadata loaded from the placeholder ``printers.json`` file.

The JSON file is intentionally treated as placeholder data: replacing it with
real printer information requires no code changes.  Loading is defensive, so a
missing or partly filled file still leaves the printing workspace usable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_BUILD_VOLUME = (200.0, 200.0, 200.0)
DEFAULT_LAYER_HEIGHT = 0.2
DEFAULT_WARNING_THRESHOLD = 0.1


@dataclass(frozen=True)
class PrinterInfo:
    """Normalised printer information shown by the printing workspace."""

    id: str
    name: str
    kind: str
    status: str
    build_volume: Tuple[float, float, float]
    nozzle_diameter: float
    min_layer_height: float
    max_layer_height: float
    materials: Tuple[str, ...]
    default_layer_height: float
    location: str = ""
    last_maintenance: str = ""
    next_maintenance: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrinterInfo":
        """Build printer information from one JSON object."""
        capabilities = data.get("capabilities") or {}
        settings = data.get("default_settings") or {}
        materials = capabilities.get("supported_materials") or ()
        return cls(
            id=str(data.get("id") or data.get("name") or "printer"),
            name=str(data.get("name") or "Printer"),
            kind=str(data.get("type") or "FDM"),
            status=str(data.get("status") or "ready"),
            build_volume=_read_volume(
                capabilities.get("build_volume")
            ),
            nozzle_diameter=_number(
                capabilities.get("nozzle_diameter"), 0.4
            ),
            min_layer_height=_number(
                capabilities.get("min_layer_height"), 0.05
            ),
            max_layer_height=_number(
                capabilities.get("max_layer_height"), 0.5
            ),
            materials=tuple(str(item) for item in materials),
            default_layer_height=_number(
                settings.get("layer_height"), DEFAULT_LAYER_HEIGHT
            ),
            location=str(data.get("location") or ""),
            last_maintenance=str(data.get("last_maintenance") or ""),
            next_maintenance=str(data.get("next_maintenance") or ""),
        )


@dataclass(frozen=True)
class PrinterCatalog:
    """All printers and global settings read from ``printers.json``."""

    printers: Tuple[PrinterInfo, ...]
    settings: Dict[str, Any] = field(default_factory=dict)

    def get(self, printer_id: str) -> Optional[PrinterInfo]:
        """Return a printer by ID, or ``None`` when it is unknown."""
        for printer in self.printers:
            if printer.id == printer_id:
                return printer
        return None

    @property
    def default_id(self) -> str:
        """Return the configured or first printer ID."""
        configured = str(self.settings.get("default_printer") or "")
        if configured and self.get(configured) is not None:
            return configured
        return self.printers[0].id if self.printers else ""

    def default_printer(self) -> PrinterInfo:
        """Return the configured default printer or a fallback."""
        printer = self.get(self.default_id)
        if printer is not None:
            return printer
        return _fallback_printer()

    @property
    def warning_threshold(self) -> float:
        """Return the smallest layer height considered safe."""
        value = _number(
            self.settings.get("layer_height_warning_threshold"),
            DEFAULT_WARNING_THRESHOLD,
        )
        # The product requirement is a warning below 0.1 mm.  A lower value in
        # the placeholder JSON must not silently relax that safety threshold.
        return max(DEFAULT_WARNING_THRESHOLD, value)


def _number(value: Any, fallback: float) -> float:
    """Convert ``value`` to a finite float, or return ``fallback``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _read_volume(value: Any) -> Tuple[float, float, float]:
    """Read a build volume from a dict, sequence or missing value."""
    if isinstance(value, dict):
        return (
            _number(value.get("width"), DEFAULT_BUILD_VOLUME[0]),
            _number(value.get("depth"), DEFAULT_BUILD_VOLUME[1]),
            _number(value.get("height"), DEFAULT_BUILD_VOLUME[2]),
        )
    if isinstance(value, Sequence) and not isinstance(value, str):
        if len(value) >= 3:
            return (
                _number(value[0], DEFAULT_BUILD_VOLUME[0]),
                _number(value[1], DEFAULT_BUILD_VOLUME[1]),
                _number(value[2], DEFAULT_BUILD_VOLUME[2]),
            )
    return DEFAULT_BUILD_VOLUME


def _fallback_printer() -> PrinterInfo:
    """Return a usable printer when the placeholder file cannot be read."""
    return PrinterInfo(
        id="placeholder_printer",
        name="Placeholder Printer",
        kind="FDM",
        status="ready",
        build_volume=DEFAULT_BUILD_VOLUME,
        nozzle_diameter=0.4,
        min_layer_height=0.05,
        max_layer_height=0.5,
        materials=("PLA",),
        default_layer_height=DEFAULT_LAYER_HEIGHT,
    )


def _fallback_catalog() -> PrinterCatalog:
    """Return a one-printer catalog for a missing configuration file."""
    return PrinterCatalog((_fallback_printer(),), {})


def read_printer_catalog(path: Path) -> Optional[PrinterCatalog]:
    """Read a printer catalog, returning ``None`` when it is unusable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    entries: List[Dict[str, Any]] = [
        entry for entry in data.get("printers", ())
        if isinstance(entry, dict)
    ]
    printers = tuple(PrinterInfo.from_dict(entry) for entry in entries)
    if not printers:
        return None
    settings = data.get("settings")
    return PrinterCatalog(
        printers,
        settings if isinstance(settings, dict) else {},
    )


def load_printer_catalog(
    path: Optional[Path] = None,
) -> PrinterCatalog:
    """Load printer information from JSON, falling back to a placeholder."""
    config_path = path or Path(__file__).with_name("printers.json")
    catalog = read_printer_catalog(config_path)
    return catalog if catalog is not None else _fallback_catalog()
