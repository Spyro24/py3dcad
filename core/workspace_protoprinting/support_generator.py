"""Support structure generation for 3D printing."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import math


class SupportAnchor(Enum):
    """Types of support anchors."""
    OVERHANG = "overhang"
    WALL = "wall"
    BRIDGE = "bridge"
    COLUMN = "column"
    FILLET = "fillet"


class SupportType(Enum):
    """Support structure types."""
    STANDARD = "standard"
    TREE = "tree"
    CONICAL = "conical"
    HELICAL = "helical"
    CUSTOM = "custom"


@dataclass
class SupportStructure:
    """A support structure for 3D printing."""
    id: str
    name: str
    type: SupportType
    anchor_points: List[Tuple[float, float, float]]
    support_points: List[Tuple[float, float, float]]
    thickness: float = 0.4
    density: float = 0.3
    angle: float = 45.0
    max_overhang: float = 45.0
    
    # Metadata
    created_at: float = 0.0
    layer_indices: List[int] = field(default_factory=list)


@dataclass
class OverhangRegion:
    """An overhang region that needs support."""
    id: str
    boundary: List[Tuple[float, float, float]]
    centroid: Tuple[float, float, float]
    normal: Tuple[float, float, float]
    max_angle: float = 45.0
    size: float = 1.0
    
    # Analysis results
    anchor_points: List[Tuple[float, float, float]] = field(default_factory=list)
    required_support: List[Tuple[float, float, float]] = field(default_factory=list)
    complexity: float = 1.0


@dataclass
class SupportGeneratorSettings:
    """Settings for support generation."""
    # General settings
    enabled: bool = True
    type: SupportType = SupportType.TREE
    thickness: float = 0.4
    
    # Threshold settings
    max_overhang_angle: float = 45.0
    min_overhang_angle: float = 15.0
    max_bridge_length: float = 50.0
    
    # Quality settings
    density: float = 0.3
    min_support_size: float = 5.0
    max_support_density: float = 0.8
    
    # Structure settings
    anchor_style: str = "standard"
    adaptive_support: bool = True
    support_only_critical: bool = False
    
    # Advanced settings
    enable_branching: bool = True
    max_branch_angle: float = 30.0
    enable_optimization: bool = True
    optimize_for_printing_speed: bool = True


@dataclass
class SupportGenerationResult:
    """Result of support structure generation."""
    success: bool = False
    total_support_volume: float = 0.0
    total_support_mass: float = 0.0
    estimated_print_time_increase: float = 0.0
    
    # Generated structures
    supports: List[SupportStructure] = field(default_factory=list)
    overhangs: List[OverhangRegion] = field(default_factory=list)
    
    # Metadata
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Analysis
    analysis_time: float = 0.0
    generation_time: float = 0.0


class SupportGenerator:
    """Generates support structures for 3D printing."""
    
    def __init__(self):
        self.available_types = list(SupportType)
        self.available_anchors = list(SupportAnchor)
        self.material_profiles = self._load_material_profiles()
    
    def _load_material_profiles(self) -> Dict[str, Dict[str, float]]:
        """Load material-specific support profiles."""
        return {
            "PLA": {
                "support_thickness": 0.4,
                "max_overhang_angle": 45.0,
                "support_speed": 30.0,
                "support_temperature": 50.0,
            },
            "ABS": {
                "support_thickness": 0.4,
                "max_overhang_angle": 45.0,
                "support_speed": 30.0,
                "support_temperature": 60.0,
            },
            "PETG": {
                "support_thickness": 0.5,
                "max_overhang_angle": 40.0,
                "support_speed": 25.0,
                "support_temperature": 70.0,
            },
            "Nylon": {
                "support_thickness": 0.6,
                "max_overhang_angle": 35.0,
                "support_speed": 20.0,
                "support_temperature": 80.0,
            },
            "TPU": {
                "support_thickness": 0.3,
                "max_overhang_angle": 50.0,
                "support_speed": 40.0,
                "support_temperature": 40.0,
            },
        }
    
    def detect_overhangs(
        self,
        model_file: str,
        layer_height: float,
        angle_threshold: float = 45.0
    ) -> List[OverhangRegion]:
        """Detect overhang regions in a 3D model."""
        # In a real implementation, this would analyze the actual 3D model
        # For now, return sample overhang regions
        import time
        
        overhangs = []
        
        # Create some sample overhang regions
        for i in range(3):
            # Generate random overhang point (simplified)
            import random
            x = random.uniform(-50, 50)
            y = random.uniform(-50, 50)
            z = random.uniform(10, 50)
            
            # Create boundary (simplified square)
            boundary = [
                (x - 10, y - 10, z),
                (x + 10, y - 10, z),
                (x + 10, y + 10, z),
                (x - 10, y + 10, z),
            ]
            
            # Calculate centroid
            centroid = (
                sum(p[0] for p in boundary) / len(boundary),
                sum(p[1] for p in boundary) / len(boundary),
                sum(p[2] for p in boundary) / len(boundary)
            )
            
            # Calculate normal (simplified - assume upward)
            normal = (0.0, 0.0, 1.0)
            
            # Calculate max overhang angle
            max_angle = angle_threshold + random.uniform(0, 15)
            
            overhang = OverhangRegion(
                id=f"overhang_{i}",
                boundary=boundary,
                centroid=centroid,
                normal=normal,
                max_angle=max_angle,
                size=100.0,
                complexity=1.0 + i * 0.3,
            )
            
            overhangs.append(overhang)
        
        return overhangs
    
    def generate_support(
        self,
        overhangs: List[OverhangRegion],
        settings: SupportGeneratorSettings,
        layer_height: float,
        model_bounds: Optional[Tuple[float, float, float, float, float, float]] = None
    ) -> SupportGenerationResult:
        """Generate support structures for detected overhangs."""
        result = SupportGenerationResult()
        
        try:
            # Validate settings
            errors = self._validate_settings(settings)
            if errors:
                result.errors.extend(errors)
                return result
            
            # Check if support generation is enabled
            if not settings.enabled:
                return result
            
            # Process each overhang
            total_support_volume = 0.0
            total_support_mass = 0.0
            
            for i, overhang in enumerate(overhangs):
                # Check if this overhang needs support
                if overhang.max_angle <= settings.min_overhang_angle:
                    continue  # Too shallow, no support needed
                
                if overhang.max_angle > settings.max_overhang_angle:
                    overhang.max_angle = settings.max_overhang_angle
                
                if overhang.size < settings.min_support_size:
                    continue  # Too small, ignore
                
                # Generate support anchors
                anchors = self._generate_anchors(overhang, settings)
                overhang.anchor_points = anchors
                
                # Generate support structure
                support = self._generate_single_support(
                    overhang, anchors, settings, layer_height
                )
                
                if support:
                    result.supports.append(support)
                    
                    # Calculate support volume (simplified)
                    support_volume = self._calculate_support_volume(support, layer_height)
                    total_support_volume += support_volume
                    
                    # Calculate support mass (simplified)
                    support_mass = support_volume * 1.24  # Approx. density for PLA
                    total_support_mass += support_mass
                    
                    # Track overhang layers
                    layers_needed = self._calculate_layers_for_support(support, layer_height)
                    result.overhangs.append(overhang)
            
            result.total_support_volume = total_support_volume
            result.total_support_mass = total_support_mass
            result.estimated_print_time_increase = total_support_mass * 0.5  # seconds per gram
            result.success = True
            
            # Generate warnings
            warnings = self._generate_warnings(overhangs, result.supports, settings)
            result.warnings.extend(warnings)
            
        except Exception as e:
            result.errors.append(f"Support generation failed: {str(e)}")
        
        return result
    
    def _validate_settings(self, settings: SupportGeneratorSettings) -> List[str]:
        """Validate support generator settings."""
        errors = []
        
        if settings.thickness <= 0:
            errors.append("Support thickness must be positive")
        
        if settings.density < 0 or settings.density > 1:
            errors.append("Support density must be between 0 and 1")
        
        if settings.max_overhang_angle < settings.min_overhang_angle:
            errors.append("Max overhang angle must be greater than min overhang angle")
        
        if settings.max_support_density < settings.density:
            errors.append("Max support density must be greater than or equal to base density")
        
        return errors
    
    def _generate_anchors(
        self,
        overhang: OverhangRegion,
        settings: SupportGeneratorSettings
    ) -> List[Tuple[float, float, float]]:
        """Generate anchor points for support structures."""
        anchors = []
        
        # In a real implementation, this would calculate actual anchor points
        # based on the overhang geometry and settings
        # For now, return some sample anchors
        
        # Add base anchors (simplified)
        for i in range(3):
            import random
            anchor_x = overhang.centroid[0] + random.uniform(-5, 5)
            anchor_y = overhang.centroid[1] + random.uniform(-5, 5)
            anchor_z = overhang.centroid[2] - 5  # Below the overhang
            
            anchors.append((anchor_x, anchor_y, anchor_z))
        
        # If tree-style support, add branching anchors
        if settings.type == SupportType.TREE and settings.enable_branching:
            for anchor in anchors[:]:  # Iterate over copy
                # Add child anchors for tree structure
                import random
                for child in range(2):
                    child_x = anchor[0] + random.uniform(-10, 10)
                    child_y = anchor[1] + random.uniform(-10, 10)
                    child_z = anchor[2] + 10  # Above the parent
                    
                    anchors.append((child_x, child_y, child_z))
        
        return anchors
    
    def _generate_single_support(
        self,
        overhang: OverhangRegion,
        anchors: List[Tuple[float, float, float]],
        settings: SupportGeneratorSettings,
        layer_height: float
    ) -> Optional[SupportStructure]:
        """Generate a single support structure."""
        if not anchors:
            return None
        
        # Generate support points (simplified)
        support_points = []
        
        for anchor in anchors:
            # Add points along support lines
            for layer in range(5):  # 5 layers of support
                z = anchor[2] + (layer + 1) * layer_height
                
                # Add support point at this layer
                import random
                point_x = anchor[0] + random.uniform(-2, 2)
                point_y = anchor[1] + random.uniform(-2, 2)
                
                support_points.append((point_x, point_y, z))
        
        # Determine support type based on configuration
        support_type = SupportType.STANDARD
        if settings.type == SupportType.TREE and settings.enable_branching:
            support_type = SupportType.TREE
        elif settings.type == SupportType.CONICAL:
            support_type = SupportType.CONICAL
        
        import time
        support = SupportStructure(
            id=f"support_{overhang.id}",
            name=f"Support for {overhang.id}",
            type=support_type,
            anchor_points=anchors,
            support_points=support_points,
            thickness=settings.thickness,
            density=settings.density,
            angle=settings.max_overhang_angle,
            max_overhang=settings.max_overhang_angle,
            created_at=time.time(),
        )
        
        return support
    
    def _calculate_support_volume(
        self,
        support: SupportStructure,
        layer_height: float
    ) -> float:
        """Calculate volume of a support structure (simplified)."""
        # Simplified volume calculation
        # In a real implementation, this would use actual geometry
        base_area = math.pi * (support.thickness / 2) ** 2
        height = 50.0  # approximate height
        
        volume = base_area * height
        volume *= support.density
        
        return volume
    
    def _calculate_layers_for_support(
        self,
        support: SupportStructure,
        layer_height: float
    ) -> List[int]:
        """Calculate which layers the support spans."""
        # Simplified - return layers 1-10
        return list(range(1, 11))
    
    def _generate_warnings(
        self,
        overhangs: List[OverhangRegion],
        supports: List[SupportStructure],
        settings: SupportGeneratorSettings
    ) -> List[str]:
        """Generate warnings for support generation."""
        warnings = []
        
        if not overhangs:
            warnings.append("No overhangs detected - no support structures generated")
        
        if settings.density > 0.7:
            warnings.append("High support density may increase print time significantly")
        
        if settings.thickness < 0.3:
            warnings.append("Thin support structures may break during printing")
        
        if settings.max_overhang_angle > 60:
            warnings.append("Large overhang angles may cause print failures")
        
        if len(supports) > 10:
            warnings.append("Many support structures detected - consider optimizing for print time")
        
        return warnings
    
    def optimize_support(
        self,
        supports: List[SupportStructure],
        settings: SupportGeneratorSettings,
        target_time_reduction: float = 0.1
    ) -> List[SupportStructure]:
        """Optimize support structures to reduce print time."""
        optimized_supports = []
        
        for support in supports:
            # Create optimized version
            optimized_support = SupportStructure(
                id=support.id,
                name=support.name,
                type=support.type,
                anchor_points=support.anchor_points.copy(),
                support_points=support.support_points.copy(),
                thickness=support.thickness,
                density=support.density * 0.8,  # Reduce density
                angle=support.angle,
                max_overhang=support.max_overhang,
                created_at=support.created_at,
                layer_indices=support.layer_indices.copy(),
            )
            
            optimized_supports.append(optimized_support)
        
        return optimized_supports


# Global support generator instance
_support_generator = SupportGenerator()


def get_support_generator() -> SupportGenerator:
    """Get the global support generator instance."""
    return _support_generator