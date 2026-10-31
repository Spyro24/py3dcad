# Printing Workspace - PY3DCAD

The Printing Workspace is a specialized workspace within PY3DCAD designed for 3D printing workflows and preparation. It provides comprehensive tools for managing print jobs, slicing models, generating support structures, and configuring printers.

## Overview

The Printing Workspace enables users to:
- Create and manage 3D printing jobs
- Slice 3D models for printing
- Generate support structures
- Configure and manage 3D printers
- Monitor print progress
- Optimize print parameters for specific materials and technologies

## Components

### 1. Print Manager

The Print Manager handles the lifecycle of 3D printing jobs, from creation to completion. It manages:

- **Print Jobs**: Create, track, and manage individual print jobs
- **Job Status**: Track progress from pending to completed
- **Parameter Management**: Configure print parameters for different materials and technologies
- **Job History**: Maintain a history of completed and failed jobs

**Key Features**:
- Create new print jobs with custom parameters
- Update job status and progress
- Generate G-code for printing
- Calculate material usage and print time estimates

### 2. Slice Planner

The Slice Planner handles the slicing of 3D models for 3D printing. It provides:

- **Multiple Slicing Algorithms**: WACCI, WITH_WALLS, CANCELLATION, and MARCHING_CUBES
- **Adaptive Layer Height**: Automatically adjust layer thickness based on model complexity
- **Region Slicing**: Slice models in multiple regions for parallel processing
- **Toolpath Generation**: Generate optimized toolpaths for printing
- **Print Time and Material Estimation**: Calculate estimated print time and filament usage

**Key Features**:
- Support for multiple slicing algorithms
- Adaptive layer height optimization
- Regional slicing for complex models
- Print time and material estimation

### 3. Support Generator

The Support Generator creates support structures for 3D printed parts. It includes:

- **Overhang Detection**: Automatically detect overhangs that require support
- **Multiple Support Styles**: Tree, conical, helical, and custom support structures
- **Support Optimization**: Optimize support structures for print time and quality
- **Material-Specific Support**: Support structures optimized for different printing materials

**Key Features**:
- Automatic overhang detection
- Multiple support structure styles
- Support optimization for print time
- Material-specific support generation

### 4. Printer Configuration

The Printer Configuration manages 3D printer profiles and settings. It provides:

- **Printer Profiles**: Store and manage printer configurations
- **Material Management**: Manage supported materials and their properties
- **Print Mode Configuration**: Configure standard, silent, and manual print modes
- **Statistics Tracking**: Track print statistics and metrics
- **Import/Export**: Import and export printer configurations

**Key Features**:
- Comprehensive printer profile management
- Material-specific settings
- Print mode configuration
- Print statistics tracking
- Configuration import/export

### 5. UI Integration

The UI Integration provides the user interface components for the Printing Workspace:

- **Workspace Selector**: Toggle the printing workspace on and off
- **Tabbed Interface**: Navigate between jobs, slicing, support, and settings
- **Dialog Windows**: Create, configure, and manage print jobs and settings
- **Visual Feedback**: Provide visual feedback for print job status and progress
- **Responsive Design**: Adapt to different screen sizes and scales

**Key Features**:
- Workspace toggle functionality
- Tab-based navigation
- Dialog windows for job and settings management
- Visual feedback for print job status
- Responsive UI design

## Usage Examples

### Creating a Print Job

```python
from core.workspace_protoprinting.print_manager import get_print_manager

print_manager = get_print_manager()

job = print_manager.create_print_job(
    name="Test Part",
    model_file="models/test_part.stl",
    parameters={
        "layer_height": 0.2,
        "infill_density": 0.2,
        "support_material": True,
    }
)
```

### Slicing a Model

```python
from core.workspace_protoprinting.slice_planner import get_slice_planner, PrintRegion

slice_planner = get_slice_planner()

settings = slice_planner.SliceSettings(
    layer_height=0.2,
    material="PLA",
    support_enabled=True,
)

region = PrintRegion(
    name="Main Region",
    bounds=(0.0, 0.0, 0.0, 100.0, 100.0, 50.0),
)

result = slice_planner.slice_model("models/test_part.stl", settings, [region])
```

### Generating Support Structures

```python
from core.workspace_protoprinting.support_generator import get_support_generator, SupportGeneratorSettings

 support_generator = get_support_generator()

settings = SupportGeneratorSettings(
    enabled=True,
    type="tree",
    thickness=0.4,
    density=0.3,
)

overhangs = support_generator.detect_overhangs("models/test_part.stl", 0.2)
support_result = support_generator.generate_support(overhangs, settings, 0.2)
```

### Managing Printers

```python
from core.workspace_protoprinting.printer_config import get_printer_manager

printer_manager = get_printer_manager()

# Add a new printer
from core.workspace_protoprinting.printer_config import PrinterProfile, PrinterCapabilities, PrinterType

capabilities = PrinterCapabilities(
    build_volume=(210.0, 210.0, 250.0),
    nozzle_diameter=0.4,
    supported_materials=["PLA", "ABS", "PETG"],
)

printer = PrinterProfile(
    name="My Printer",
    type=PrinterType.FDM,
    capabilities=capabilities,
)

printer_manager.add_printer(printer)
```

## Integration with PY3DCAD

The Printing Workspace integrates seamlessly with the PY3DCAD application through:

- **Application Integration**: The workspace can be accessed and controlled from the main PY3DCAD application
- **Model Access**: Access 3D models from within the PY3DCAD environment
- **Print Workflow**: Complete print workflow from model import to print completion
- **Settings Integration**: Configure print settings from within the PY3DCAD settings

## Technical Specifications

### Dependencies

- Python 3.11+
- Standard library: `dataclasses`, `typing`, `json`, `math`, `enum`
- PY3DCAD Core: Integration with PY3DCAD application framework

### Data Structures

- **PrintJob**: Represents a single 3D printing job
- **PrintParameters**: Configuration for printing parameters
- **SliceSettings**: Configuration for slicing operations
- **SliceResult**: Results of slicing operations
- **SupportStructure**: Generated support structures
- **PrinterProfile**: Printer configuration profiles
- **PrintJobConfig**: Print job configuration

### File Formats

- **G-code**: Output for 3D printers
- **STL**: Standard 3D model format
- **JSON**: Configuration file format

## Architecture

The Printing Workspace follows a modular architecture with clear separation of concerns:

- **Model Layer**: Data structures and business logic
- **Service Layer**: Core functionality (print management, slicing, support generation)
- **Integration Layer**: UI integration and application-specific functionality
- **Presentation Layer**: User interface components

This architecture allows for easy extension and customization of the printing workspace functionality.

## Development Guidelines

### Adding New Features

1. **Model Layer**: Define new data structures in the appropriate dataclasses
2. **Service Layer**: Implement new functionality in the service classes
3. **Integration Layer**: Add integration code in the UI integration module
4. **Presentation Layer**: Add UI components in the UI integration module

### Testing

The Printing Workspace includes comprehensive tests that verify:
- Print job management functionality
- Slicing operations
- Support structure generation
- Printer configuration
- UI integration

### Code Style

- Follow PEP 8 style guidelines
- Use type hints for all function signatures
- Write docstrings for all public methods and classes
- Keep classes under 40 lines (as per PY3DCAD guidelines)
- Use semantic commits for version control

## Future Enhancements

Potential future enhancements for the Printing Workspace include:

- **Advanced Slicing Algorithms**: Implement more sophisticated slicing algorithms
- **Machine Learning**: Use machine learning to optimize print parameters
- **Cloud Integration**: Integrate with cloud printing services
- **Real-time Monitoring**: Monitor print progress in real-time
- **Multi-Printer Management**: Manage multiple 3D printers
- **Print Queue Management**: Manage print queues for multiple printers
- **Cost Tracking**: Track printing costs and material usage
- **Performance Analytics**: Analyze print performance and optimize settings

## Conclusion

The Printing Workspace provides a comprehensive solution for 3D printing workflows within the PY3DCAD application. It integrates seamlessly with the existing PY3DCAD framework while providing powerful tools for managing, slicing, and optimizing 3D printing jobs. The modular architecture allows for easy extension and customization to meet specific printing requirements.

This workspace demonstrates the extensibility of PY3DCAD and its ability to support specialized workflows like 3D printing while maintaining the core principles of the PY3DCAD architecture.