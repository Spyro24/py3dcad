"""Print job management and 3D printing workflows."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json


class PrintStatus(Enum):
    """Print job status."""
    PENDING = "pending"
    SLICING = "slicing"
    READY = "ready"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"


class LayerTechnology(Enum):
    """3D printing layer technologies."""
    FDM = "FDM"
    SLA = "SLA"
    SLS = "SLS"
    DLP = "DLP"
    MJF = "MJF"
    BindJet = "BindJet"


@dataclass
class PrintParameters:
    """3D printing parameters for a print job."""
    # Machine settings
    machine_id: str = "default_printer"
    technology: LayerTechnology = LayerTechnology.FDM
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


class PrintManager:
    """Manages 3D printing workflows and print jobs."""
    
    def __init__(self):
        self.jobs: Dict[str, PrintJob] = {}
        self.available_machines: List[str] = ["default_printer"]
        self.available_materials: List[str] = ["PLA", "ABS", "PETG", "TPU", "Nylon"]
        self.available_technologies: List[LayerTechnology] = list(LayerTechnology)
    
    def create_print_job(
        self, 
        name: str, 
        model_file: str,
        parameters: Optional[PrintParameters] = None
    ) -> PrintJob:
        """Create a new print job."""
        import time
        job_id = f"job_{int(time.time())}"
        
        job = PrintJob(
            job_id=job_id,
            name=name,
            file_path=model_file,
            model_file=model_file,
            parameters=parameters or PrintParameters(),
            created_at=time.time()
        )
        
        self.jobs[job_id] = job
        return job
    
    def get_job(self, job_id: str) -> Optional[PrintJob]:
        """Get a print job by ID."""
        return self.jobs.get(job_id)
    
    def list_jobs(self) -> List[PrintJob]:
        """List all print jobs."""
        return list(self.jobs.values())
    
    def update_job_status(self, job_id: str, status: PrintStatus) -> bool:
        """Update a print job's status."""
        job = self.get_job(job_id)
        if job is None:
            return False
        
        job.status = status
        if status == PrintStatus.PRINTING:
            job.started_at = time.time()
        elif status == PrintStatus.COMPLETED:
            job.completed_at = time.time()
            import time
            job.progress = 100.0
        
        return True
    
    def update_job_progress(self, job_id: str, progress: float, layer: int) -> bool:
        """Update a print job's progress."""
        job = self.get_job(job_id)
        if job is None:
            return False
        
        job.progress = min(100.0, max(0.0, progress))
        job.current_layer = layer
        return True
    
    def generate_gcode(self, job_id: str, output_path: str) -> bool:
        """Generate G-code for a print job."""
        job = self.get_job(job_id)
        if job is None:
            return False
        
        # TODO: Implement actual G-code generation
        job.gcode_path = output_path
        job.status = PrintStatus.READY
        
        return True
    
    def get_print_recommendations(
        self, 
        model_dimensions: Tuple[float, float, float],
        material: str,
        technology: LayerTechnology
    ) -> PrintParameters:
        """Generate print parameter recommendations based on model and material."""
        params = PrintParameters()
        params.material = material
        params.technology = technology
        
        # Adjust layer height based on technology
        if technology == LayerTechnology.SLA:
            params.layer_height = 0.025
        elif technology == LayerTechnology.DLP:
            params.layer_height = 0.05
        elif technology == LayerTechnology.SLS:
            params.layer_height = 0.1
        
        # Adjust infill based on material strength requirements
        if material in ["Nylon", "Carbon Fiber"]:
            params.infill_density = 0.3
        elif material == "PLA":
            params.infill_density = 0.15
        
        return params


# Global print manager instance
_print_manager = PrintManager()


def get_print_manager() -> PrintManager:
    """Get the global print manager instance."""
    return _print_manager