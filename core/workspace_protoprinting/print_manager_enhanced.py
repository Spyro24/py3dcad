"""Enhanced print manager with JSON configuration and layer height validation."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json
import os


class PrintStatus(Enum):
    """Print job status."""
    PENDING = "pending"
    SLICING = "slicing"
    READY = "ready"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"


class LayerHeightWarning(Enum):
    """Layer height warning levels."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class PrintParameters:
    """3D printing parameters for a print job."""
    # Machine settings
    machine_id: str = "default_printer"
    build_plate: str = "build_plate_1"
    
    # Material settings
    material: str = "PLA"
    filament_diameter: float = 1.75
    layer_height: float = 0.2
    infill_density: float = 0.2
    
    # Process settings
    print_speed: float = 60.0
    nozzle_temperature: float = 200.0
    bed_temperature: float = 60.0
    
    # Print quality
    resolution: str = "normal"
    support_material: bool = True
    raft_enabled: bool = False
    
    # Print area
    max_print_volume: Tuple[float, float, float] = (200.0, 200.0, 200.0)


@dataclass
class PrintJob:
    """A 3D printing job."""
    job_id: str
    name: str
    file_path: str
    model_file: str
    status: PrintStatus = PrintStatus.PENDING
    parameters: PrintParameters = field(default_factory=PrintParameters)
    
    # Progress tracking
    progress: float = 0.0
    current_layer: int = 0
    total_layers: int = 0
    
    # Results
    gcode_path: Optional[str] = None
    print_time: Optional[float] = None
    material_used: Optional[float] = None
    
    # Metadata
    created_at: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class PrinterInfo:
    """Printer information from JSON configuration."""
    id: str
    name: str
    type: str
    status: str
    capabilities: Dict
    default_settings: Dict
    material_profiles: Dict
    location: str
    last_maintenance: str
    next_maintenance: str


@dataclass
class PrinterSettings:
    """Global printer settings."""
    default_printer: str
    layer_height_warning_threshold: float
    max_preview_layers: int
    save_directory: str
    auto_save_enabled: bool
    backup_enabled: bool


class EnhancedPrintManager:
    """Enhanced print manager with JSON configuration and layer height validation."""
    
    def __init__(self, config_path: str = None):
        self.jobs: Dict[str, PrintJob] = {}
        self.available_machines: List[str] = ["default_printer"]
        self.available_materials: List[str] = ["PLA", "ABS", "PETG", "Nylon", "TPU"]
        
        # Load configuration
        self.config_path = config_path or os.path.join(
            os.path.dirname(__file__), "printers.json"
        )
        self.printer_info: Dict[str, PrinterInfo] = {}
        self.printer_settings: Optional[PrinterSettings] = None
        self._load_configuration()
    
    def _load_configuration(self):
        """Load printer configuration from JSON file."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                
                # Load printer info
                self.printer_info = {}
                for printer_data in data.get("printers", []):
                    printer = PrinterInfo(**printer_data)
                    self.printer_info[printer.id] = printer
                
                # Load settings
                settings_data = data.get("settings", {})
                self.printer_settings = PrinterSettings(**settings_data)
                
                print(f"✓ Loaded configuration from {self.config_path}")
                print(f"✓ Loaded {len(self.printer_info)} printers")
                print(f"✓ Warning threshold: {self.printer_settings.layer_height_warning_threshold}mm")
            else:
                print(f"⚠ Configuration file not found: {self.config_path}")
                self._create_default_configuration()
        except Exception as e:
            print(f"⚠ Failed to load configuration: {e}")
            self._create_default_configuration()
    
    @property
    def printer_settings_dict(self):
        """Get printer settings as a dictionary for compatibility."""
        return {
            "default_printer": self.printer_settings.default_printer,
            "layer_height_warning_threshold": self.printer_settings.layer_height_warning_threshold,
            "max_preview_layers": self.printer_settings.max_preview_layers,
            "save_directory": self.printer_settings.save_directory,
            "auto_save_enabled": self.printer_settings.auto_save_enabled,
            "backup_enabled": self.printer_settings.backup_enabled,
        }
    
    @property
    def printer_settings_dict(self):
        """Get printer settings as a dictionary for compatibility."""
        return self.printer_settings.__dict__ if self.printer_settings else {}
    
    def _create_default_configuration(self):
        """Create default configuration if JSON file is missing."""
        print("⚠ Creating default configuration")
        
        # Default printer info
        self.printer_info = {
            "default_printer": PrinterInfo(
                id="default_printer",
                name="Default Printer",
                type="FDM",
                status="ready",
                capabilities={"build_volume": (200.0, 200.0, 200.0)},
                default_settings={"layer_height": 0.2},
                material_profiles={"PLA": {}},
                location="unknown",
                last_maintenance="unknown",
                next_maintenance="unknown"
            )
        }
        
        # Default settings
        self.printer_settings = PrinterSettings(
            default_printer="default_printer",
            layer_height_warning_threshold=0.1,
            max_preview_layers=10,
            save_directory="/tmp",
            auto_save_enabled=True,
            backup_enabled=True
        )
    
    def create_print_job(
        self, 
        name: str, 
        model_file: str,
        parameters: Optional[PrintParameters] = None
    ) -> Optional[PrintJob]:
        """Create a new print job with validation."""
        if not name.strip():
            print("⚠ Job name cannot be empty")
            return None
        
        if not model_file.strip():
            print("⚠ Model file cannot be empty")
            return None
        
        # Validate parameters
        params = parameters or PrintParameters()
        warnings = self._validate_parameters(params)
        
        if warnings:
            print("⚠ Parameter warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        
        # Create job
        import time
        job_id = f"job_{int(time.time())}"
        
        job = PrintJob(
            job_id=job_id,
            name=name,
            file_path=model_file,
            model_file=model_file,
            parameters=params,
            created_at=time.time()
        )
        
        self.jobs[job_id] = job
        
        print(f"✓ Created print job: {job.name} (ID: {job.job_id})")
        if warnings:
            print(f"  Job status: {job.status.value} (with warnings)")
        
        return job
    
    def _validate_parameters(self, params: PrintParameters) -> List[str]:
        """Validate print parameters and return warnings/errors."""
        warnings = []
        
        # Check layer height
        layer_warning = self._get_layer_height_warning(params.layer_height)
        if layer_warning == LayerHeightWarning.WARNING:
            warnings.append(
                f"Layer height {params.layer_height}mm is below recommended minimum 0.1mm"
            )
        elif layer_warning == LayerHeightWarning.ERROR:
            warnings.append(
                f"Layer height {params.layer_height}mm is too low and may cause print issues"
            )
        
        # Check other parameters
        if params.layer_height <= 0:
            warnings.append("Layer height must be positive")
        
        if params.max_print_volume[0] <= 0:
            warnings.append("Build volume dimensions must be positive")
        
        if params.infill_density < 0 or params.infill_density > 1:
            warnings.append("Infill density must be between 0 and 1")
        
        if params.print_speed <= 0:
            warnings.append("Print speed must be positive")
        
        return warnings
    
    def _get_layer_height_warning(self, layer_height: float) -> LayerHeightWarning:
        """Get warning level for layer height."""
        if self.printer_settings is None:
            return LayerHeightWarning.WARNING
        
        if layer_height < 0.05:
            return LayerHeightWarning.ERROR
        elif layer_height < self.printer_settings.layer_height_warning_threshold:
            return LayerHeightWarning.WARNING
        else:
            return LayerHeightWarning.OK
    
    def get_printer_info(self, printer_id: str) -> Optional[PrinterInfo]:
        """Get printer information by ID."""
        return self.printer_info.get(printer_id)
    
    def __getitem__(self, key: str) -> PrinterInfo:
        """Allow dictionary-style access to printer info."""
        return self.printer_info[key]
    
    def get(self, key: str, default=None) -> PrinterInfo:
        """Allow get method for compatibility with dict-style access."""
        return self.printer_info.get(key, default)
    
    def list_printers(self) -> List[PrinterInfo]:
        """List all available printers."""
        return list(self.printer_info.values())
    
    def get_printer(self, printer_id: str) -> Optional[PrintJob]:
        """Get a print job by ID."""
        return self.jobs.get(printer_id)
    
    def list_jobs(self) -> List[PrintJob]:
        """List all print jobs."""
        return list(self.jobs.values())
    
    def update_job_status(self, job_id: str, status: PrintStatus) -> bool:
        """Update a print job's status."""
        job = self.get_printer(job_id)
        if job is None:
            return False
        
        job.status = status
        if status == PrintStatus.PRINTING:
            import time
            job.started_at = time.time()
        elif status == PrintStatus.COMPLETED:
            import time
            job.completed_at = time.time()
            job.progress = 100.0
        
        return True
    
    def update_job_progress(self, job_id: str, progress: float, layer: int) -> bool:
        """Update a print job's progress."""
        job = self.get_printer(job_id)
        if job is None:
            return False
        
        job.progress = min(100.0, max(0.0, progress))
        job.current_layer = layer
        return True
    
    def get_recommended_parameters(
        self,
        model_dimensions: Tuple[float, float, float],
        material: str,
        technology: str
    ) -> PrintParameters:
        """Generate recommended print parameters based on model and material."""
        params = PrintParameters()
        params.material = material
        
        # Get printer info for recommendations
        if self.printer_settings and self.printer_info:
            default_printer_id = self.printer_settings.default_printer
            default_printer = self.printer_info.get(default_printer_id)
            
            if default_printer and material in default_printer.material_profiles:
                material_profile = default_printer.material_profiles[material]
                
                if "layer_height" in material_profile:
                    params.layer_height = material_profile["layer_height"]
                if "bed_temp" in material_profile:
                    params.bed_temperature = material_profile["bed_temp"]
                if "nozzle_temp" in material_profile:
                    params.nozzle_temperature = material_profile["nozzle_temp"]
                if "infill_speed" in material_profile:
                    params.print_speed = material_profile["infill_speed"]
        
        return params


# Global enhanced print manager instance
_enhanced_print_manager = EnhancedPrintManager()


def get_enhanced_print_manager() -> EnhancedPrintManager:
    """Get the global enhanced print manager instance."""
    return _enhanced_print_manager