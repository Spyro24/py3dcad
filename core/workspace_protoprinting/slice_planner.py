"""Slice planning and print preparation."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import math


class SliceMethod(Enum):
    """Slice algorithms."""
    WACCI = "WACCI"
    WITH_WALLS = "WITH_WALLS"
    CANCELLATION = "CANCELLATION"
    MARCHING_CUBES = "MARCHING_CUBES"


class SupportStyle(Enum):
    """Support structure styles."""
    TREE = "tree"
    FLAT = "flat"
    CONICAL = "conical"
    CUSTOM = "custom"


@dataclass
class SliceSettings:
    """Slicing configuration settings."""
    # Slice method
    algorithm: SliceMethod = SliceMethod.WACCI
    
    # Slice parameters
    layer_height: float = 0.2
    initial_layer_height: Optional[float] = None
    max_layer_height: float = 0.5
    min_layer_height: float = 0.05
    
    # Material specific
    material: str = "PLA"
    infill_extrusion_width: float = 0.6
    perimeter_extrusion_width: float = 0.4
    
    # Quality settings
    quality: str = "normal"  # normal, high, draft
    support_enabled: bool = True
    support_style: SupportStyle = SupportStyle.TREE
    support_density: float = 0.3
    overhang_threshold: float = 45.0
    infill_density: float = 0.2
    
    # Optimization
    enable_optimization: bool = True
    optimize_for_speed: bool = False
    optimize_for_quality: bool = False
    
    # Special parameters
    ironing_enabled: bool = False
    adaptive_layer_height: bool = False
    sparse_infill: bool = False

    # Mesh and extrusion settings used by the document slicer
    model_resolution: float = 1.0
    non_planar: bool = False
    extrusion_width: float = 0.4
    print_speed: float = 60.0
    travel_speed: float = 120.0
    nozzle_temperature: float = 200.0
    bed_temperature: float = 60.0
    filament_diameter: float = 1.75


@dataclass
class SliceLayer:
    """One planar (or conformal) layer produced by the slicer."""

    index: int
    z: float
    perimeters: List[List[Tuple[float, float, float]]] = field(
        default_factory=list
    )
    infill: List[List[Tuple[float, float, float]]] = field(
        default_factory=list
    )

    @property
    def paths(self) -> List[List[Tuple[float, float, float]]]:
        """Return every toolpath in printing order."""
        return [*self.perimeters, *self.infill]


@dataclass
class SliceResult:
    """Result of a slicing operation."""
    success: bool = False
    total_layers: int = 0
    total_thickness: float = 0.0
    estimated_time: float = 0.0
    gcode_size: int = 0
    estimated_filament: float = 0.0
    
    # Errors
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Slice data
    layer_heights: List[float] = field(default_factory=list)
    toolpaths: Dict[int, List[Tuple[float, float, float]]] = field(default_factory=dict)
    support_paths: Dict[int, List[Tuple[float, float, float]]] = field(default_factory=dict)

    # Data produced by the document slicer
    layers: List[SliceLayer] = field(default_factory=list)
    non_planar_paths: List[List[Tuple[float, float, float]]] = field(
        default_factory=list
    )
    mesh_triangles: int = 0
    resolution: float = 1.0
    non_planar: bool = False
    gcode: str = ""
    gcode_path: str = ""


@dataclass
class PrintRegion:
    """A print region definition."""
    name: str
    bounds: Tuple[float, float, float, float, float, float]  # xmin, ymin, zmin, xmax, ymax, zmax
    material: str = "PLA"
    bed_type: str = "build_plate_1"
    temperature: float = 60.0
    is_active: bool = True
    
    # Region-specific settings
    custom_layer_height: Optional[float] = None
    custom_infill: Optional[float] = None
    custom_speed: Optional[float] = None


class SlicePlanner:
    """Handles 3D model slicing and preparation for printing."""
    
    def __init__(self):
        self.available_algorithms = list(SliceMethod)
        self.available_support_styles = list(SupportStyle)
        self.material_profiles: Dict[str, Dict[str, float]] = self._load_material_profiles()
    
    def _load_material_profiles(self) -> Dict[str, Dict[str, float]]:
        """Load material-specific slicing profiles."""
        return {
            "PLA": {
                "layer_height": 0.2,
                "bed_temp": 60.0,
                "nozzle_temp": 200.0,
                "infill_speed": 60.0,
                "perimeter_speed": 40.0,
            },
            "ABS": {
                "layer_height": 0.2,
                "bed_temp": 80.0,
                "nozzle_temp": 250.0,
                "infill_speed": 50.0,
                "perimeter_speed": 35.0,
            },
            "PETG": {
                "layer_height": 0.25,
                "bed_temp": 75.0,
                "nozzle_temp": 240.0,
                "infill_speed": 55.0,
                "perimeter_speed": 40.0,
            },
            "Nylon": {
                "layer_height": 0.15,
                "bed_temp": 85.0,
                "nozzle_temp": 260.0,
                "infill_speed": 45.0,
                "perimeter_speed": 30.0,
            },
            "TPU": {
                "layer_height": 0.3,
                "bed_temp": 50.0,
                "nozzle_temp": 220.0,
                "infill_speed": 35.0,
                "perimeter_speed": 25.0,
            },
        }
    
    def slice_model(
        self,
        model_file: str,
        settings: SliceSettings,
        regions: Optional[List[PrintRegion]] = None
    ) -> SliceResult:
        """Slice a 3D model for printing."""
        result = SliceResult()
        
        try:
            # Validate settings
            errors = self._validate_settings(settings)
            if errors:
                result.errors.extend(errors)
                return result
            
            # Load model (simplified)
            model_bounds = self._load_model_bounds(model_file)
            if not model_bounds:
                result.errors.append("Failed to load model file")
                return result
            
            # Calculate layers
            layers = self._calculate_layers(model_bounds, settings)
            result.layer_heights = layers
            result.total_layers = len(layers)
            result.total_thickness = sum(layers)
            
            # Generate toolpaths (simplified)
            toolpaths = self._generate_toolpaths(model_file, settings, layers)
            result.toolpaths = toolpaths
            
            # Generate support structures
            support_paths = self._generate_support(model_file, settings, layers)
            result.support_paths = support_paths
            
            # Calculate estimates
            result.estimated_time = self._estimate_print_time(layers, settings)
            result.estimated_filament = self._estimate_filament(toolpaths, settings)
            
            result.success = True
            
            # Generate warnings
            warnings = self._generate_warnings(model_bounds, settings)
            result.warnings.extend(warnings)
            
        except Exception as e:
            result.errors.append(f"Slicing failed: {str(e)}")
        
        return result
    
    def _validate_settings(self, settings: SliceSettings) -> List[str]:
        """Validate slice settings."""
        errors = []
        
        if settings.layer_height <= 0:
            errors.append("Layer height must be positive")
        
        if settings.max_layer_height <= settings.layer_height:
            errors.append("Max layer height must be greater than layer height")
        
        if settings.min_layer_height >= settings.layer_height:
            errors.append("Min layer height must be less than layer height")
        
        if settings.infill_density < 0 or settings.infill_density > 1:
            errors.append("Infill density must be between 0 and 1")
        
        if settings.support_density < 0 or settings.support_density > 1:
            errors.append("Support density must be between 0 and 1")
        
        return errors
    
    def _load_model_bounds(self, model_file: str) -> Optional[Tuple[float, float, float, float, float, float]]:
        """Load model bounds from file (simplified implementation)."""
        # In a real implementation, this would load the actual 3D model
        # For now, return a sample bounding box
        return (0.0, 0.0, 0.0, 100.0, 100.0, 50.0)
    
    def _calculate_layers(
        self, 
        bounds: Tuple[float, float, float, float, float, float],
        settings: SliceSettings
    ) -> List[float]:
        """Calculate layer heights for slicing."""
        zmin, zmax = bounds[2], bounds[5]
        total_height = zmax - zmin
        
        if settings.adaptive_layer_height:
            # Adaptive layer height calculation (simplified)
            layers = []
            remaining_height = total_height
            current_z = zmin
            
            while remaining_height > 0:
                layer_thickness = min(
                    settings.max_layer_height,
                    max(settings.min_layer_height, settings.layer_height)
                )
                layer_thickness = min(layer_thickness, remaining_height)
                layers.append(layer_thickness)
                remaining_height -= layer_thickness
                current_z += layer_thickness
            
            return layers
        else:
            # Standard slicing
            num_layers = int(math.ceil(total_height / settings.layer_height))
            return [settings.layer_height] * num_layers
    
    def _generate_toolpaths(
        self,
        model_file: str,
        settings: SliceSettings,
        layers: List[float]
    ) -> Dict[int, List[Tuple[float, float, float]]]:
        """Generate toolpaths for slicing (simplified implementation)."""
        # In a real implementation, this would generate actual G-code paths
        # For now, return empty paths for all layers
        return {layer_idx: [] for layer_idx in range(len(layers))}
    
    def _generate_support(
        self,
        model_file: str,
        settings: SliceSettings,
        layers: List[float]
    ) -> Dict[int, List[Tuple[float, float, float]]]:
        """Generate support structure paths (simplified implementation)."""
        # In a real implementation, this would generate actual support paths
        # For now, return empty support for all layers
        return {layer_idx: [] for layer_idx in range(len(layers))}
    
    def _estimate_print_time(
        self, 
        layers: List[float], 
        settings: SliceSettings
    ) -> float:
        """Estimate print time based on layers and settings."""
        # Simplified time estimation
        time_per_layer = 30.0  # seconds per layer
        setup_time = 120.0  # setup time in seconds
        
        total_time = setup_time + (len(layers) * time_per_layer)
        
        # Adjust for speed optimizations
        if settings.enable_optimization:
            if settings.optimize_for_speed:
                total_time *= 0.85
            elif settings.optimize_for_quality:
                total_time *= 1.15
        
        return total_time / 60.0  # Convert to minutes
    
    def _estimate_filament(
        self,
        toolpaths: Dict[int, List[Tuple[float, float, float]]],
        settings: SliceSettings
    ) -> float:
        """Estimate filament usage based on toolpaths."""
        # Simplified filament estimation
        volume_per_layer = 1000.0  # cubic mm per layer (simplified)
        total_volume = sum(volume_per_layer for _ in toolpaths)
        
        # Convert volume to length (assuming 1.75mm diameter filament)
        filament_area = math.pi * (0.875) ** 2
        filament_length = total_volume / filament_area
        
        # Adjust for infill density
        filament_length *= settings.infill_density
        
        return filament_length / 1000.0  # Convert to meters
    
    def _generate_warnings(
        self,
        bounds: Tuple[float, float, float, float, float, float],
        settings: SliceSettings
    ) -> List[str]:
        """Generate warnings for slicing."""
        warnings = []
        
        zmin, zmax = bounds[2], bounds[5]
        total_height = zmax - zmin
        
        if total_height > 200:
            warnings.append("Model height exceeds recommended build volume")
        
        if settings.overhang_threshold < 45:
            warnings.append("Overhang threshold is aggressive - consider adding support")
        
        if settings.support_density < 0.2:
            warnings.append("Low support density may cause print failures")
        
        if settings.layer_height < 0.1:
            warnings.append("Very thin layers will significantly increase print time")
        
        return warnings
    
    def optimize_slicing(
        self,
        model_file: str,
        settings: SliceSettings,
        regions: List[PrintRegion]
    ) -> SliceResult:
        """Optimize slicing for multiple regions."""
        # Split model into regions and slice each region separately
        results = []
        
        for region in regions:
            region_settings = SliceSettings(
                algorithm=settings.algorithm,
                layer_height=settings.layer_height,
                material=settings.material,
                support_enabled=settings.support_enabled,
                support_style=settings.support_style,
                support_density=settings.support_density,
                infill_density=settings.infill_density,
            )
            
            if region.custom_layer_height:
                region_settings.layer_height = region.custom_layer_height
            if region.custom_infill:
                region_settings.infill_density = region.custom_infill
            if region.custom_speed:
                region_settings.enable_optimization = True
                # Adjust speeds (simplified)
            
            # Slice this region (simplified - would need actual model loading)
            result = SliceResult(
                success=True,
                total_layers=10,  # Simplified
                estimated_time=30.0,
                warnings=[f"Region {region.name} sliced successfully"]
            )
            results.append(result)
        
        # Merge results (simplified)
        merged_result = SliceResult()
        for result in results:
            merged_result.total_layers += result.total_layers
            merged_result.estimated_time += result.estimated_time
            merged_result.warnings.extend(result.warnings)
        
        merged_result.success = all(r.success for r in results)
        return merged_result


# Global slice planner instance
_slice_planner = SlicePlanner()


def get_slice_planner() -> SlicePlanner:
    """Get the global slice planner instance."""
    return _slice_planner