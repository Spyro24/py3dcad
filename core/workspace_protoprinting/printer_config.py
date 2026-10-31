"""Printer configuration and management for 3D printing workspace."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json


class PrinterStatus(Enum):
    """Printer status states."""
    IDLE = "idle"
    PRINTING = "printing"
    PAUSED = "paused"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class PrinterType(Enum):
    """3D printer types."""
    FDM = "FDM"
    SLA = "SLA"
    SLS = "SLS"
    DLP = "DLP"
    MJF = "MJF"
    BindJet = "BindJet"


class PrintMode(Enum):
    """Print modes."""
    STANDARD = "standard"
    SILENT = "silent"
    MANUAL = "manual"


@dataclass
class PrinterCapabilities:
    """3D printer capabilities."""
    # Build volume
    build_volume: Tuple[float, float, float] = (200.0, 200.0, 200.0)
    
    # Nozzle capabilities
    nozzle_diameter: float = 0.4
    nozzle_count: int = 1
    nozzle_temperature_range: Tuple[float, float] = (0.0, 300.0)
    
    # Bed capabilities
    bed_type: str = "heated_bed"
    bed_temperature_range: Tuple[float, float] = (0.0, 120.0)
    bed_surface: str = "aluminum"
    
    # Print speeds
    max_print_speed: float = 180.0
    max_layer_height: float = 0.5
    min_layer_height: float = 0.05
    
    # Materials supported
    supported_materials: List[str] = field(default_factory=lambda: ["PLA", "ABS", "PETG"])
    
    # Filament management
    filament_sensors: bool = True
    filament_detection_sensitivity: str = "high"
    
    # Sensor capabilities
    temperature_sensors: int = 4
    flow_rate_sensors: int = 2
    vibration_sensors: int = 2
    
    # Additional features
    auto_leveling: bool = True
    enclosure: bool = False
    air_filtration: bool = False
    dual_extrusion: bool = False


@dataclass
class PrinterProfile:
    """A printer profile configuration."""
    name: str
    type: PrinterType
    capabilities: PrinterCapabilities
    
    # Default settings
    default_layer_height: float = 0.2
    default_infill: float = 0.2
    default_print_speed: float = 60.0
    default_nozzle_temp: float = 200.0
    default_bed_temp: float = 60.0
    
    # Material defaults
    material_settings: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    # Quality presets
    quality_presets: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    # Metadata
    manufacturer: str = ""
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""


@dataclass
class PrintJobConfig:
    """Print job configuration."""
    # Job identification
    job_id: str
    printer_id: str
    file_path: str
    
    # Print settings
    layer_height: float = 0.2
    print_speed: float = 60.0
    nozzle_temperature: float = 200.0
    bed_temperature: float = 60.0
    
    # Quality settings
    resolution: str = "normal"
    infill_density: float = 0.2
    support_enabled: bool = True
    
    # Print process
    print_mode: PrintMode = PrintMode.STANDARD
    start_paused: bool = False
    auto_continue: bool = True
    
    # Monitoring
    temperature_tolerance: float = 2.0
    speed_tolerance: float = 5.0
    
    # Output
    output_file: Optional[str] = None
    gcode_preview: Optional[str] = None


@dataclass
class PrintStatistics:
    """Print statistics and metrics."""
    # Print job statistics
    total_prints: int = 0
    successful_prints: int = 0
    failed_prints: int = 0
    paused_prints: int = 0
    
    # Material usage
    total_filament_used: float = 0.0
    total_material_cost: float = 0.0
    material_by_type: Dict[str, float] = field(default_factory=dict)
    
    # Time statistics
    total_print_time: float = 0.0
    average_print_time: float = 0.0
    longest_print_time: float = 0.0
    shortest_print_time: float = 0.0
    
    # Quality statistics
    quality_rating_sum: float = 0.0
    quality_rating_count: int = 0
    
    # Printer uptime
    total_uptime: float = 0.0
    maintenance_intervals: int = 0


class PrinterManager:
    """Manages 3D printers and their configurations."""
    
    def __init__(self):
        self.printers: Dict[str, PrinterProfile] = {}
        self.print_jobs: Dict[str, PrintJobConfig] = {}
        self.statistics = PrintStatistics()
        
        # Load default printers
        self._load_default_printers()
    
    def _load_default_printers(self):
        """Load default printer profiles."""
        # FDM Printer profile
        fdm_capabilities = PrinterCapabilities(
            build_volume=(210.0, 210.0, 250.0),
            nozzle_diameter=0.4,
            nozzle_count=1,
            nozzle_temperature_range=(0.0, 300.0),
            bed_type="heated_bed",
            bed_temperature_range=(0.0, 120.0),
            bed_surface="glass",
            max_print_speed=180.0,
            max_layer_height=0.5,
            min_layer_height=0.05,
            supported_materials=["PLA", "ABS", "PETG", "Nylon", "TPU"],
        )
        
        fdm_printer = PrinterProfile(
            name="FDM_Printer",
            type=PrinterType.FDM,
            capabilities=fdm_capabilities,
            manufacturer="Generic",
            model="FDM-3DPrinter",
        )
        
        self.printers[fdm_printer.name] = fdm_printer
        
        # SLA Printer profile
        sla_capabilities = PrinterCapabilities(
            build_volume=(130.0, 73.0, 175.0),
            nozzle_diameter=0.025,  # 25 microns
            nozzle_count=1,
            nozzle_temperature_range=(0.0, 80.0),
            bed_type="heated_bed",
            bed_temperature_range=(0.0, 60.0),
            bed_surface="steel",
            max_print_speed=50.0,
            max_layer_height=0.025,
            min_layer_height=0.005,
            supported_materials=["PLA", "ABS", "Nylon", "Resin"],
        )
        
        sla_printer = PrinterProfile(
            name="SLA_Printer",
            type=PrinterType.SLA,
            capabilities=sla_capabilities,
            manufacturer="Generic",
            model="SLA-3DPrinter",
        )
        
        self.printers[sla_printer.name] = sla_printer
    
    def add_printer(self, profile: PrinterProfile):
        """Add a new printer profile."""
        self.printers[profile.name] = profile
    
    def get_printer(self, name: str) -> Optional[PrinterProfile]:
        """Get a printer profile by name."""
        return self.printers.get(name)
    
    def list_printers(self) -> List[PrinterProfile]:
        """List all printer profiles."""
        return list(self.printers.values())
    
    def remove_printer(self, name: str) -> bool:
        """Remove a printer profile."""
        if name in self.printers:
            del self.printers[name]
            return True
        return False
    
    def create_print_job(
        self,
        printer_name: str,
        file_path: str,
        config: Optional[PrintJobConfig] = None
    ) -> Optional[PrintJobConfig]:
        """Create a new print job."""
        printer = self.get_printer(printer_name)
        if printer is None:
            return None
        
        import time
        job_id = f"job_{int(time.time())}"
        
        if config is None:
            config = PrintJobConfig(
                job_id=job_id,
                printer_id=printer.name,
                file_path=file_path,
                layer_height=printer.default_layer_height,
                print_speed=printer.default_print_speed,
                nozzle_temperature=printer.default_nozzle_temp,
                bed_temperature=printer.default_bed_temp,
            )
        else:
            config.job_id = job_id
            config.printer_id = printer.name
        
        self.print_jobs[job_id] = config
        self.statistics.total_prints += 1
        
        return config
    
    def get_print_job(self, job_id: str) -> Optional[PrintJobConfig]:
        """Get a print job by ID."""
        return self.print_jobs.get(job_id)
    
    def list_print_jobs(self) -> List[PrintJobConfig]:
        """List all print jobs."""
        return list(self.print_jobs.values())
    
    def update_job_status(self, job_id: str, status: str) -> bool:
        """Update a print job's status."""
        job = self.get_print_job(job_id)
        if job is None:
            return False
        
        # In a real implementation, this would update the job status
        # For now, just update the statistics
        if status == "completed":
            self.statistics.successful_prints += 1
        elif status == "failed":
            self.statistics.failed_prints += 1
        elif status == "paused":
            self.statistics.paused_prints += 1
        
        return True
    
    def get_job_statistics(self) -> PrintStatistics:
        """Get current print job statistics."""
        return self.statistics
    
    def calculate_cost(self, job_id: str) -> Optional[float]:
        """Calculate the cost of a print job."""
        job = self.get_print_job(job_id)
        if job is None:
            return None
        
        # Get printer profile
        printer = self.get_printer(job.printer_id)
        if printer is None:
            return None
        
        # Get material cost (simplified)
        material_cost = 1.0  # $1 per gram
        
        # Get estimated filament usage (simplified)
        estimated_filament = 500.0  # grams
        
        total_cost = material_cost * estimated_filament
        
        return total_cost
    
    def export_printer_config(self, output_path: str) -> bool:
        """Export printer configurations to a file."""
        try:
            data = {
                "printers": [
                    {
                        "name": p.name,
                        "type": p.type.value,
                        "capabilities": {
                            "build_volume": p.capabilities.build_volume,
                            "nozzle_diameter": p.capabilities.nozzle_diameter,
                            "supported_materials": p.capabilities.supported_materials,
                        },
                    }
                    for p in self.printers.values()
                ],
            }
            
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            return True
        except Exception:
            return False
    
    def import_printer_config(self, input_path: str) -> bool:
        """Import printer configurations from a file."""
        try:
            with open(input_path, 'r') as f:
                data = json.load(f)
            
            # In a real implementation, this would reconstruct printer profiles
            # For now, just return success
            return True
        except Exception:
            return False


# Global printer manager instance
_printer_manager = PrinterManager()


def get_printer_manager() -> PrinterManager:
    """Get the global printer manager instance."""
    return _printer_manager