"""Enhanced UI integration for the printing workspace with JSON configuration and improved layout."""

import pygame
import json
import os
from typing import Callable, Optional, Dict, List
from enum import Enum
from dataclasses import dataclass
from .print_manager_enhanced import get_enhanced_print_manager, PrintJob, PrintParameters, PrintStatus
from .slice_planner import get_slice_planner, SliceSettings, SliceResult
from .support_generator import get_support_generator, SupportGeneratorSettings
from ..ui.layout import Rect


class LayerHeightWarning(Enum):
    """Layer height warning levels."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class PrintingWorkspaceUI:
    """Enhanced UI components for the printing workspace with improved layout."""
    
    def __init__(self):
        self.enhanced_print_manager = get_enhanced_print_manager()
        self.slice_planner = get_slice_planner()
        self.support_generator = get_support_generator()
        
        # Load printer configuration
        self.printer_info = self._load_printer_info()
        self.printer_settings = self._load_printer_settings()
        
        # UI state
        self.visible = False
        self.active_tab = "jobs"  # jobs, slicing, support, settings
        self.selected_printer = "fdm_printer_001"
        self.selected_job: Optional[PrintJob] = None
        self.show_job_dialog = False
        self.show_slice_dialog = False
        self.show_support_dialog = False
        self.show_settings_dialog = False
        
        # Input fields
        self.new_job_name = ""
        self.new_job_file = ""
        
        # Layer height selection
        self.selected_layer_height = 0.2
        self.layer_height_warning = LayerHeightWarning.OK
        
        # Font cache
        self._font_small: Optional[pygame.font.Font] = None
        self._font_normal: Optional[pygame.font.Font] = None
        self._font_large: Optional[pygame.font.Font] = None
        
        # Colors
        self.bg_color = pygame.Color(26, 26, 30)
        self.card_bg = pygame.Color(35, 35, 40)
        self.accent = pygame.Color(59, 130, 246)
        self.text_primary = pygame.Color(230, 230, 235)
        self.text_secondary = pygame.Color(176, 176, 184)
        self.text_muted = pygame.Color(130, 130, 140)
        self.error_color = pygame.Color(235, 100, 100)
        self.success_color = pygame.Color(52, 211, 153)
        self.warning_color = pygame.Color(251, 146, 60)
        
        # Icons (simplified)
        self.icons = {}
    
    def _load_printer_info(self) -> Dict[str, Dict]:
        """Load printer information from JSON file."""
        try:
            config_path = os.path.join(os.path.dirname(__file__), "printers.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    data = json.load(f)
                return {printer["id"]: printer for printer in data.get("printers", [])}
        except Exception as e:
            print(f"⚠ Failed to load printer info: {e}")
        
        return {}
    
    def _load_printer_settings(self) -> Dict:
        """Load printer settings from JSON file."""
        try:
            config_path = os.path.join(os.path.dirname(__file__), "printers.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    data = json.load(f)
                return data.get("settings", {})
        except Exception as e:
            print(f"⚠ Failed to load printer settings: {e}")
        
        return {}
    
    def _init_fonts(self):
        """Initialize fonts."""
        if self._font_small is not None:
            return
        
        self._font_small = pygame.font.SysFont("Segoe UI", 12)
        self._font_normal = pygame.font.SysFont("Segoe UI", 14)
        self._font_large = pygame.font.SysFont("Segoe UI", 16, bold=True)
    
    def set_scale(self, scale: float):
        """Set UI scale."""
        # Update font sizes based on scale
        self._init_fonts()
    
    def toggle_visibility(self):
        """Toggle the visibility of the printing workspace UI."""
        self.visible = not self.visible
        if not self.visible:
            self.close_all_dialogs()
    
    def is_visible(self) -> bool:
        """Check if the UI is visible."""
        return self.visible
    
    def set_active_tab(self, tab: str):
        """Set the active tab."""
        if tab in ["jobs", "slicing", "support", "settings"]:
            self.active_tab = tab
    
    def load_printer_config(self):
        """Load printer configuration from file."""
        try:
            import pygame
            from pygame import freetype
            
            # Create a simple file dialog (simplified)
            # In a real implementation, this would use a proper file dialog
            config_path = "select_printer_config.json"
            
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    data = json.load(f)
                
                # Update printer info
                new_printer_info = {}
                for printer_data in data.get("printers", []):
                    new_printer_info[printer_data["id"]] = printer_data
                
                self.printer_info = new_printer_info
                
                # Update selected printer to first available
                if self.printer_info:
                    self.selected_printer = list(self.printer_info.keys())[0]
                
                print(f"✓ Loaded printer configuration with {len(self.printer_info)} printers")
                return True
            else:
                print(f"⚠ Printer configuration file not found: {config_path}")
                return False
                
        except Exception as e:
            print(f"⚠ Failed to load printer configuration: {e}")
            return False
    
    def save_printer_config(self):
        """Save current printer configuration to file."""
        try:
            config_path = "printer_config_backup.json"
            
            # Create backup configuration
            backup_data = {
                "printers": list(self.printer_info.values()) if self.printer_info else [],
                "settings": self.printer_settings if hasattr(self, 'printer_settings') else {}
            }
            
            with open(config_path, 'w') as f:
                json.dump(backup_data, f, indent=2)
            
            print(f"✓ Saved printer configuration to {config_path}")
            return True
            
        except Exception as e:
            print(f"⚠ Failed to save printer configuration: {e}")
            return False
    
    def open_new_job_dialog(self):
        """Open the new print job dialog."""
        self.show_job_dialog = True
        self.new_job_name = ""
        self.new_job_file = ""
        self.selected_layer_height = self.enhanced_print_manager.printer_settings.get("layer_height_warning_threshold", 0.1) if self.enhanced_print_manager.printer_settings else 0.1
        self.layer_height_warning = self._get_layer_height_warning(self.selected_layer_height)
    
    def close_job_dialog(self):
        """Close the new print job dialog."""
        self.show_job_dialog = False
    
    def create_print_job(self) -> Optional[PrintJob]:
        """Create a new print job with validation."""
        if not self.new_job_name.strip():
            print("⚠ Job name cannot be empty")
            return None
        
        if not self.new_job_file.strip():
            print("⚠ Model file cannot be empty")
            return None
        
        # Create parameters with selected layer height
        params = PrintParameters()
        params.layer_height = self.selected_layer_height
        params.material = "PLA"  # Default material
        
        job = self.enhanced_print_manager.create_print_job(
            name=self.new_job_name,
            model_file=self.new_job_file,
            parameters=params,
        )
        
        if job:
            self.close_job_dialog()
        
        return job
    
    def open_slice_dialog(self):
        """Open the slice configuration dialog."""
        self.show_slice_dialog = True
    
    def close_slice_dialog(self):
        """Close the slice configuration dialog."""
        self.show_slice_dialog = False
    
    def slice_model(self) -> Optional[SliceResult]:
        """Slice the selected model."""
        if not self.selected_job:
            return None
        
        # Create slice settings (simplified)
        settings = SliceSettings(
            layer_height=self.selected_job.parameters.layer_height,
            material=self.selected_job.parameters.material,
            support_enabled=self.selected_job.parameters.support_material,
            enable_optimization=True,
        )
        
        result = self.slice_planner.slice_model(
            model_file=self.selected_job.model_file,
            settings=settings,
        )
        
        if result.success and result.gcode_size > 0:
            self.selected_job.status = PrintStatus.READY
            self.selected_job.gcode_path = f"/tmp/{self.selected_job.job_id}.gcode"
        
        self.close_slice_dialog()
        return result
    
    def open_support_dialog(self):
        """Open the support generation dialog."""
        self.show_support_dialog = True
    
    def close_support_dialog(self):
        """Close the support generation dialog."""
        self.show_support_dialog = False
    
    def generate_support(self) -> Optional[SliceResult]:
        """Generate support structures."""
        if not self.selected_job:
            return None
        
        # Create support settings (simplified)
        settings = SupportGeneratorSettings(
            enabled=True,
            type="tree",
            thickness=0.4,
            density=0.3,
            max_overhang_angle=45.0,
        )
        
        # Get overhangs (simplified - would detect from model)
        overhangs = []
        
        result = self.support_generator.generate_support(
            overhangs=overhangs,
            settings=settings,
            layer_height=self.selected_job.parameters.layer_height,
        )
        
        self.close_support_dialog()
        return result
    
    def close_all_dialogs(self):
        """Close all dialogs."""
        self.show_job_dialog = False
        self.show_slice_dialog = False
        self.show_support_dialog = False
        self.show_settings_dialog = False
    
    def select_job(self, job: PrintJob):
        """Select a print job."""
        self.selected_job = job
    
    def set_selected_printer(self, printer_id: str):
        """Set the selected printer."""
        if printer_id in self.printer_info:
            self.selected_printer = printer_id
    
    def _get_layer_height_warning(self, layer_height: float) -> LayerHeightWarning:
        """Get warning level for layer height."""
        if self.printer_settings is None:
            return LayerHeightWarning.WARNING
        
        threshold = self.printer_settings.get("layer_height_warning_threshold", 0.1)
        
        if layer_height < 0.05:
            return LayerHeightWarning.ERROR
        elif layer_height < threshold:
            return LayerHeightWarning.WARNING
        else:
            return LayerHeightWarning.OK
    
    def _get_warning_color(self, warning: LayerHeightWarning) -> pygame.Color:
        """Get color for layer height warning."""
        if warning == LayerHeightWarning.ERROR:
            return self.error_color
        elif warning == LayerHeightWarning.WARNING:
            return self.warning_color
        else:
            return self.success_color
    
    def draw(self, surface: pygame.Surface, region: Rect):
        """Draw the enhanced printing workspace UI with improved layout."""
        if not self.visible:
            return
        
        self._init_fonts()
        
        # Draw background
        pygame.draw.rect(surface, self.bg_color, region.rect)
        
        # Draw header
        self._draw_header(surface, region)
        
        # Draw toolbar
        self._draw_toolbar(surface, region)
        
        # Draw content area with improved 3-column layout
        self._draw_content(surface, region)
        
        # Draw dialogs
        if self.show_job_dialog:
            self._draw_new_job_dialog(surface, region)
        if self.show_slice_dialog:
            self._draw_slice_dialog(surface, region)
        if self.show_support_dialog:
            self._draw_support_dialog(surface, region)
    
    def _draw_header(self, surface: pygame.Surface, region: Rect):
        """Draw the header."""
        header_height = 50
        header_rect = Rect(region.x, region.y, region.w, header_height)
        
        pygame.draw.rect(surface, self.card_bg, header_rect.rect)
        
        # Title
        title = self._font_large.render("Printing Workspace", True, self.text_primary)
        surface.blit(title, (region.x + 20, region.y + 15))
        
        # Printer selection
        printer_label = self._font_normal.render("Printer:", True, self.text_secondary)
        surface.blit(printer_label, (region.x + 300, region.y + 20))
        
        if self.printer_info:
            printer = self.printer_info.get(self.selected_printer)
            if printer:
                printer_text = self._font_normal.render(printer["name"], True, self.text_primary)
                surface.blit(printer_text, (region.x + 350, region.y + 22))
        
        # Status indicator
        if self.selected_job:
            status_color = self._get_status_color(self.selected_job.status)
            status_text = self._font_normal.render(f"Job: {self.selected_job.name}", True, status_color)
            surface.blit(status_text, (region.x + region.w - 20 - status_text.get_width(), region.y + 15))
    
    def _draw_toolbar(self, surface: pygame.Surface, region: Rect):
        """Draw the toolbar."""
        toolbar_y = region.y + 50
        toolbar_height = 40
        
        # Create toolbar buttons
        buttons = [
            ("Jobs", "jobs", self.active_tab == "jobs"),
            ("Slicing", "slicing", self.active_tab == "slicing"),
            ("Support", "support", self.active_tab == "support"),
            ("Settings", "settings", self.active_tab == "settings"),
        ]
        
        button_width = region.w // len(buttons)
        
        for i, (label, tab, active) in enumerate(buttons):
            x = region.x + i * button_width
            button_rect = Rect(x, toolbar_y, button_width, toolbar_height)
            
            bg_color = self.accent if active else self.card_bg
            pygame.draw.rect(surface, bg_color, button_rect.rect)
            
            # Button text
            text_color = pygame.Color(255, 255, 255) if active else self.text_primary
            button_text = self._font_normal.render(label, True, text_color)
            text_rect = button_text.get_rect(center=button_rect.center)
            surface.blit(button_text, text_rect)
            
            # Click handler
            if button_rect.collidepoint(pygame.mouse.get_pos()):
                if pygame.mouse.get_pressed()[0]:
                    self.set_active_tab(tab)
    
    def _draw_content(self, surface: pygame.Surface, region: Rect):
        """Draw the main content area with improved 3-column layout."""
        content_y = region.y + 90
        content_height = region.h - content_y
        
        # Define columns (1/4, 1/2, 1/4)
        left_width = region.w // 4
        middle_width = region.w // 2
        right_width = region.w - left_width - middle_width
        
        # Draw left panel (settings)
        left_rect = Rect(region.x, content_y, left_width, content_height)
        pygame.draw.rect(surface, self.card_bg, left_rect.rect)
        self._draw_left_panel(surface, left_rect)
        
        # Draw middle panel (viewport - 3D printing workspace)
        middle_x = region.x + left_width
        middle_rect = Rect(middle_x, content_y, middle_width, content_height)
        pygame.draw.rect(surface, self.bg_color, middle_rect.rect)
        pygame.draw.rect(surface, self.accent, middle_rect.rect, width=2)
        self._draw_viewport(surface, middle_rect)
        
        # Draw right panel (additional settings)
        right_x = middle_x + middle_width
        right_rect = Rect(right_x, content_y, right_width, content_height)
        pygame.draw.rect(surface, self.card_bg, right_rect.rect)
        self._draw_right_panel(surface, right_rect)
        
        # Draw tab content in middle panel
        if self.active_tab == "jobs":
            self._draw_jobs_tab(surface, middle_rect)
        elif self.active_tab == "slicing":
            self._draw_slicing_tab(surface, middle_rect)
        elif self.active_tab == "support":
            self._draw_support_tab(surface, middle_rect)
        elif self.active_tab == "settings":
            self._draw_settings_tab(surface, middle_rect)
    
    def _draw_left_panel(self, surface: pygame.Surface, region: Rect):
        """Draw the left panel with basic controls."""
        padding = 10
        y = region.y + padding
        
        # Printer selector
        printer_label = self._font_normal.render("Printers:", True, self.text_primary)
        surface.blit(printer_label, (region.x + padding, y))
        
        y += 30
        if self.printer_info:
            for printer_id, printer in self.printer_info.items():
                color = self.accent if printer_id == self.selected_printer else self.text_primary
                name = self._font_small.render(printer["name"], True, color)
                surface.blit(name, (region.x + padding, y))
                y += 20
        
        # Material selector
        y += 20
        material_label = self._font_normal.render("Material:", True, self.text_primary)
        surface.blit(material_label, (region.x + padding, y))
        
        y += 30
        materials = ["PLA", "ABS", "PETG", "Nylon", "TPU"]
        for material in materials:
            mat_text = self._font_small.render(material, True, self.text_secondary)
            surface.blit(mat_text, (region.x + padding, y))
            y += 18
    
    def _draw_viewport(self, surface: pygame.Surface, region: Rect):
        """Draw the 3D viewport (middle panel)."""
        # Draw a 3D box representation
        center_x = region.x + region.w // 2
        center_y = region.y + region.h // 2
        
        # Draw 3D box outline
        pygame.draw.rect(surface, self.accent, (
            center_x - 50, center_y - 30, 100, 60
        ), width=2)
        
        # Draw perspective corners
        points = [
            (center_x - 50, center_y - 30),
            (center_x + 10, center_y - 30),
            (center_x + 50, center_y - 30),
            (center_x + 50, center_y + 30),
            (center_x + 10, center_y + 30),
            (center_x - 50, center_y + 30),
        ]
        
        # Draw 3D effect (simplified)
        for i in range(len(points) - 1):
            pygame.draw.line(surface, self.accent, points[i], points[i + 1], 2)
        
        # Draw label
        label = self._font_normal.render("3D Print Preview", True, self.text_primary)
        surface.blit(label, (center_x - label.get_width() // 2, center_y + 40))
        
        # Draw layer info
        if self.selected_job:
            layer_info = self._font_small.render(
                f"Layers: {self.selected_job.current_layer}/{self.selected_job.total_layers}",
                True, self.text_secondary
            )
            surface.blit(layer_info, (center_x - layer_info.get_width() // 2, center_y + 60))
    
    def _draw_right_panel(self, surface: pygame.Surface, region: Rect):
        """Draw the right panel with additional settings."""
        padding = 10
        y = region.y + padding
        
        # Printer status
        status_label = self._font_normal.render("Status:", True, self.text_primary)
        surface.blit(status_label, (region.x + padding, y))
        
        y += 30
        if self.printer_info:
            printer = self.printer_info.get(self.selected_printer)
            if printer:
                status = self._font_small.render(printer["status"], True, self._get_printer_status_color(printer["status"]))
                surface.blit(status, (region.x + padding, y))
        
        # Printer capabilities
        y += 40
        cap_label = self._font_normal.render("Capabilities:", True, self.text_primary)
        surface.blit(cap_label, (region.x + padding, y))
        
        y += 30
        if self.printer_info:
            printer = self.printer_info.get(self.selected_printer)
            if printer and "capabilities" in printer:
                caps = printer["capabilities"]
                if "build_volume" in caps:
                    vol = self._font_small.render(
                        f"Build: {caps['build_volume']['width']:.0f}x{caps['build_volume']['depth']:.0f}x{caps['build_volume']['height']:.0f}mm",
                        True, self.text_secondary
                    )
                    surface.blit(vol, (region.x + padding, y))
                    y += 20
                
                if "supported_materials" in caps:
                    mats = self._font_small.render(
                        f"Materials: {', '.join(caps['supported_materials'][:3])}",
                        True, self.text_secondary
                    )
                    surface.blit(mats, (region.x + padding, y))
    
    def _draw_jobs_tab(self, surface: pygame.Surface, region: Rect):
        """Draw the jobs tab in middle panel."""
        # Create a simple jobs list in the middle panel
        padding = 10
        y = region.y + padding
        
        # Title
        title = self._font_normal.render("Print Jobs", True, self.text_primary)
        surface.blit(title, (region.x + padding, y))
        
        y += 30
        
        # List jobs
        jobs = self.enhanced_print_manager.list_jobs()
        for job in jobs[:5]:  # Show only first 5 jobs
            # Job row
            row_height = 40
            pygame.draw.rect(surface, self.card_bg, (
                region.x + padding, y, region.w - 2 * padding, row_height
            ))
            
            # Job info
            name = self._font_small.render(job.name, True, self.text_primary)
            surface.blit(name, (region.x + padding + 5, y + 10))
            
            # Status
            status_color = self._get_status_color(job.status)
            status = self._font_small.render(job.status.value, True, status_color)
            surface.blit(status, (region.x + padding + 200, y + 10))
            
            # Progress
            progress = self._font_small.render(f"{job.progress:.0f}%", True, self.text_secondary)
            surface.blit(progress, (region.x + padding + 300, y + 10))
            
            y += row_height + 5
        
        # New job button
        y += 10
        button_rect = Rect(region.x + padding, y, region.w - 2 * padding, 35)
        pygame.draw.rect(surface, self.accent, button_rect.rect, border_radius=4)
        
        button_text = self._font_normal.render("New Print Job", True, pygame.Color(255, 255, 255))
        text_rect = button_text.get_rect(center=button_rect.center)
        surface.blit(button_text, text_rect)
    
    def _draw_slicing_tab(self, surface: pygame.Surface, region: Rect):
        """Draw the slicing tab in middle panel."""
        padding = 10
        y = region.y + padding
        
        # Title
        title = self._font_normal.render("Slicing", True, self.text_primary)
        surface.blit(title, (region.x + padding, y))
        
        y += 40
        
        # Layer height control
        layer_label = self._font_normal.render("Layer Height:", True, self.text_primary)
        surface.blit(layer_label, (region.x + padding, y))
        
        # Layer height slider
        slider_x = region.x + padding + 120
        slider_width = 200
        slider_height = 20
        
        # Slider background
        pygame.draw.rect(surface, self.text_muted, (
            slider_x, y + 5, slider_width, slider_height
        ))
        
        # Slider fill (simplified)
        fill_width = int((self.selected_layer_height / 0.5) * slider_width)
        pygame.draw.rect(surface, self.accent, (
            slider_x, y + 5, fill_width, slider_height
        ))
        
        # Layer height value
        layer_value = self._font_small.render(f"{self.selected_layer_height:.3f}mm", True, self.text_primary)
        surface.blit(layer_value, (slider_x + slider_width + 10, y + 5))
        
        # Warning indicator
        warning_color = self._get_warning_color(self.layer_height_warning)
        warning_text = self._font_small.render(
            f"Warning: {self.layer_height_warning.value}",
            True, warning_color
        )
        surface.blit(warning_text, (region.x + padding, y + 40))
        
        y += 70
        
        # Slice button
        button_rect = Rect(region.x + padding, y, region.w - 2 * padding, 40)
        pygame.draw.rect(surface, self.accent, button_rect.rect, border_radius=4)
        
        button_text = self._font_normal.render("Slice Model", True, pygame.Color(255, 255, 255))
        text_rect = button_text.get_rect(center=button_rect.center)
        surface.blit(button_text, text_rect)
    
    def _draw_support_tab(self, surface: pygame.Surface, region: Rect):
        """Draw the support tab in middle panel."""
        padding = 10
        y = region.y + padding
        
        # Title
        title = self._font_normal.render("Support Generation", True, self.text_primary)
        surface.blit(title, (region.x + padding, y))
        
        y += 40
        
        # Support settings
        settings = [
            ("Support Enabled:", "Yes"),
            ("Support Type:", "Tree"),
            ("Support Density:", "30%"),
            ("Support Thickness:", "0.4mm"),
            ("Max Overhang:", "45°"),
        ]
        
        for label, value in settings:
            label_text = self._font_small.render(label, True, self.text_secondary)
            value_text = self._font_small.render(value, True, self.text_primary)
            
            surface.blit(label_text, (region.x + padding, y))
            surface.blit(value_text, (region.x + padding + 150, y))
            
            y += 25
        
        y += 20
        
        # Generate support button
        button_rect = Rect(region.x + padding, y, region.w - 2 * padding, 40)
        pygame.draw.rect(surface, self.accent, button_rect.rect, border_radius=4)
        
        button_text = self._font_normal.render("Generate Support", True, pygame.Color(255, 255, 255))
        text_rect = button_text.get_rect(center=button_rect.center)
        surface.blit(button_text, text_rect)
    
    def _draw_settings_tab(self, surface: pygame.Surface, region: Rect):
        """Draw the settings tab in middle panel."""
        padding = 10
        y = region.y + padding
        
        # Title
        title = self._font_normal.render("Settings", True, self.text_primary)
        surface.blit(title, (region.x + padding, y))
        
        y += 40
        
        # Printer configuration section
        printer_section_label = self._font_normal.render("Printer Configuration:", True, self.text_primary)
        surface.blit(printer_section_label, (region.x + padding, y))
        
        y += 30
        
        # Current printer info
        current_printer_label = self._font_small.render("Current Printer:", True, self.text_secondary)
        surface.blit(current_printer_label, (region.x + padding, y))
        
        if self.printer_info:
            printer = self.printer_info.get(self.selected_printer)
            if printer:
                printer_name = self._font_normal.render(printer.get("name", "Unknown"), True, self.text_primary)
                surface.blit(printer_name, (region.x + padding + 120, y))
        
        y += 30
        
        # Load printer button
        load_button = Rect(region.x + padding, y, region.w - 2 * padding, 40)
        pygame.draw.rect(surface, self.accent, load_button.rect, border_radius=4)
        
        load_text = self._font_normal.render("Load Printer Config", True, pygame.Color(255, 255, 255))
        text_rect = load_text.get_rect(center=load_button.center)
        surface.blit(load_text, text_rect)
        
        # Save printer button
        y += 50
        save_button = Rect(region.x + padding, y, region.w - 2 * padding, 40)
        pygame.draw.rect(surface, self.accent, save_button.rect, border_radius=4)
        
        save_text = self._font_normal.render("Save Current Config", True, pygame.Color(255, 255, 255))
        text_rect = save_text.get_rect(center=save_button.center)
        surface.blit(save_text, text_rect)
        
        y += 50
        
        # Export button
        export_button = Rect(region.x + padding, y, region.w - 2 * padding, 40)
        pygame.draw.rect(surface, self.card_bg, export_button.rect, border_radius=4)
        pygame.draw.rect(surface, self.accent, export_button.rect, width=1, border_radius=4)
        
        export_text = self._font_normal.render("Export Config", True, self.accent)
        text_rect = export_text.get_rect(center=export_button.center)
        surface.blit(export_text, text_rect)
        
        # Handle button clicks
        if load_button.collidepoint(pygame.mouse.get_pos()):
            if pygame.mouse.get_pressed()[0]:
                self.load_printer_config()
        
        if save_button.collidepoint(pygame.mouse.get_pos()):
            if pygame.mouse.get_pressed()[0]:
                self.save_printer_config()
        
        if export_button.collidepoint(pygame.mouse.get_pos()):
            if pygame.mouse.get_pressed()[0]:
                # Simple export functionality
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    json.dump({
                        "printers": list(self.printer_info.values()) if self.printer_info else [],
                        "settings": self.printer_settings if hasattr(self, 'printer_settings') else {}
                    }, f, indent=2)
                print(f"✓ Exported printer configuration to {f.name}")
    
    def _draw_new_job_dialog(self, surface: pygame.Surface, region: Rect):
        """Draw the enhanced new print job dialog."""
        # Semi-transparent background
        overlay = pygame.Surface(region.rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surface.blit(overlay, region.rect.topleft)
        
        # Dialog box
        dialog_width = 500
        dialog_height = 400
        dialog_x = region.x + (region.w - dialog_width) // 2
        dialog_y = region.y + (region.h - dialog_height) // 2
        
        dialog_rect = Rect(dialog_x, dialog_y, dialog_width, dialog_height)
        pygame.draw.rect(surface, self.card_bg, dialog_rect.rect, border_radius=8)
        pygame.draw.rect(surface, self.border_color, dialog_rect.rect, width=1, border_radius=8)
        
        # Dialog title
        title_text = self._font_large.render("New Print Job", True, self.text_primary)
        surface.blit(title_text, (dialog_x + 20, dialog_y + 20))
        
        # Form fields
        current_y = dialog_y + 60
        
        # Job name
        self._draw_form_field(surface, dialog_x, current_y, "Job Name:", self.new_job_name)
        current_y += 60
        
        # File path
        self._draw_form_field(surface, dialog_x, current_y, "File Path:", self.new_job_file)
        current_y += 60
        
        # Printer selection
        self._draw_printer_selector(surface, dialog_x, current_y)
        current_y += 60
        
        # Material selection
        self._draw_material_selector(surface, dialog_x, current_y)
        current_y += 60
        
        # Layer height selection
        self._draw_layer_height_selector(surface, dialog_x, current_y)
        current_y += 80
        
        # Warnings
        if self.layer_height_warning != LayerHeightWarning.OK:
            warning_text = self._font_small.render(
                f"Warning: Layer height {self.selected_layer_height}mm is {self.layer_height_warning.value}. "
                "Values below 0.1mm may cause print issues.",
                True, self._get_warning_color(self.layer_height_warning)
            )
            surface.blit(warning_text, (dialog_x + 20, current_y))
            current_y += 40
        
        # Buttons
        button_y = dialog_y + dialog_height - 60
        button_width = 100
        button_height = 35
        
        # Create button
        create_button = Rect(dialog_x + dialog_width - 220, button_y, button_width, button_height)
        pygame.draw.rect(surface, self.accent, create_button.rect, border_radius=4)
        
        create_text = self._font_normal.render("Create", True, pygame.Color(255, 255, 255))
        text_rect = create_text.get_rect(center=create_button.center)
        surface.blit(create_text, text_rect)
        
        # Cancel button
        cancel_button = Rect(dialog_x + dialog_width - 100, button_y, button_width, button_height)
        pygame.draw.rect(surface, self.card_bg, cancel_button.rect, border_radius=4)
        pygame.draw.rect(surface, self.text_secondary, cancel_button.rect, width=1, border_radius=4)
        
        cancel_text = self._font_normal.render("Cancel", True, self.text_secondary)
        text_rect = cancel_text.get_rect(center=cancel_button.center)
        surface.blit(cancel_text, text_rect)
    
    def _draw_form_field(self, surface: pygame.Surface, x: int, y: int, label: str, value: str):
        """Draw a form field with label and value."""
        # Label
        label_text = self._font_normal.render(label, True, self.text_primary)
        surface.blit(label_text, (x + 20, y))
        
        # Field background
        field_rect = Rect(x + 20, y + 25, 460, 30)
        pygame.draw.rect(surface, self.bg_color, field_rect.rect, border_radius=4)
        pygame.draw.rect(surface, self.accent, field_rect.rect, width=1, border_radius=4)
        
        # Value text
        value_text = self._font_normal.render(value, True, self.text_primary)
        surface.blit(value_text, (field_rect.x + 10, field_rect.y + 8))
    
    def _draw_printer_selector(self, surface: pygame.Surface, x: int, y: int):
        """Draw printer selector."""
        # Label
        label_text = self._font_normal.render("Printer:", True, self.text_primary)
        surface.blit(label_text, (x + 20, y))
        
        # Printer dropdown
        dropdown_rect = Rect(x + 20, y + 25, 460, 30)
        pygame.draw.rect(surface, self.bg_color, dropdown_rect.rect, border_radius=4)
        pygame.draw.rect(surface, self.accent, dropdown_rect.rect, width=1, border_radius=4)
        
        # Printer name
        printer_name = "FDM Desktop Printer" if self.selected_printer == "fdm_printer_001" else "SLA High Resolution Printer"
        name_text = self._font_normal.render(printer_name, True, self.text_primary)
        surface.blit(name_text, (dropdown_rect.x + 10, dropdown_rect.y + 8))
        
        # Dropdown arrow
        arrow_points = [
            (dropdown_rect.x + dropdown_rect.w - 20, dropdown_rect.y + 15),
            (dropdown_rect.x + dropdown_rect.w - 10, dropdown_rect.y + 15),
            (dropdown_rect.x + dropdown_rect.w - 15, dropdown_rect.y + 20)
        ]
        pygame.draw.polygon(surface, self.text_primary, arrow_points)
    
    def _draw_material_selector(self, surface: pygame.Surface, x: int, y: int):
        """Draw material selector."""
        # Label
        label_text = self._font_normal.render("Material:", True, self.text_primary)
        surface.blit(label_text, (x + 20, y))
        
        # Material dropdown
        dropdown_rect = Rect(x + 20, y + 25, 460, 30)
        pygame.draw.rect(surface, self.bg_color, dropdown_rect.rect, border_radius=4)
        pygame.draw.rect(surface, self.accent, dropdown_rect.rect, width=1, border_radius=4)
        
        # Material name
        material_text = self._font_normal.render("PLA", True, self.text_primary)
        surface.blit(material_text, (dropdown_rect.x + 10, dropdown_rect.y + 8))
    
    def _draw_layer_height_selector(self, surface: pygame.Surface, x: int, y: int):
        """Draw layer height selector with validation."""
        # Label
        label_text = self._font_normal.render("Layer Height:", True, self.text_primary)
        surface.blit(label_text, (x + 20, y))
        
        # Slider background
        slider_x = x + 20
        slider_y = y + 25
        slider_width = 460
        slider_height = 30
        
        pygame.draw.rect(surface, self.text_muted, (
            slider_x, slider_y, slider_width, slider_height
        ), border_radius=4)
        
        # Slider fill
        fill_width = int((self.selected_layer_height / 0.5) * slider_width)
        pygame.draw.rect(surface, self.accent, (
            slider_x, slider_y, fill_width, slider_height
        ), border_radius=4)
        
        # Layer height value
        value_text = self._font_normal.render(f"{self.selected_layer_height:.3f}mm", True, self.text_primary)
        surface.blit(value_text, (slider_x + slider_width + 10, slider_y + 8))
        
        # Warning indicator
        warning_icon = self._font_small.render("⚠", True, self._get_warning_color(self.layer_height_warning))
        surface.blit(warning_icon, (slider_x + 10, slider_y + 8))
        
        # Presets
        preset_y = slider_y + 45
        presets = [0.1, 0.12, 0.15, 0.2, 0.3]
        
        for preset in presets:
            preset_rect = Rect(slider_x + (preset / 0.5) * slider_width - 20, preset_y, 40, 25)
            is_selected = abs(self.selected_layer_height - preset) < 0.01
            
            color = self.accent if is_selected else self.card_bg
            pygame.draw.rect(surface, color, preset_rect.rect, border_radius=3)
            pygame.draw.rect(surface, self.text_primary, preset_rect.rect, width=1, border_radius=3)
            
            preset_text = self._font_small.render(f"{preset:.2f}", True, self.text_primary)
            text_rect = preset_text.get_rect(center=preset_rect.center)
            surface.blit(preset_text, text_rect)
            
            # Add tooltip on hover
            if preset_rect.collidepoint(pygame.mouse.get_pos()):
                tooltip = self._font_small.render(
                    f"Layer height: {preset:.2f}mm",
                    True, self.text_secondary
                )
                surface.blit(tooltip, (preset_rect.x, preset_rect.y - 25))
    
    def _draw_slice_dialog(self, surface: pygame.Surface, region: Rect):
        """Draw the slice configuration dialog."""
        # Simplified dialog - in a real implementation, this would have more controls
        overlay = pygame.Surface(region.rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surface.blit(overlay, region.rect.topleft)
        
        dialog_width = 400
        dialog_height = 250
        dialog_x = region.x + (region.w - dialog_width) // 2
        dialog_y = region.y + (region.h - dialog_height) // 2
        
        dialog_rect = Rect(dialog_x, dialog_y, dialog_width, dialog_height)
        pygame.draw.rect(surface, self.card_bg, dialog_rect.rect, border_radius=8)
        pygame.draw.rect(surface, self.border_color, dialog_rect.rect, width=1, border_radius=8)
        
        title_text = self._font_large.render("Slice Model", True, self.text_primary)
        surface.blit(title_text, (dialog_x + 20, dialog_y + 20))
        
        # Slice settings
        settings_y = dialog_y + 60
        settings_text = [
            ("Layer Height:", f"{self.selected_layer_height:.3f}mm"),
            ("Material:", "PLA"),
            ("Support:", "Enabled"),
            ("Quality:", "Normal"),
        ]
        
        for label, value in settings_text:
            label_surf = self._font_normal.render(label, True, self.text_primary)
            value_surf = self._font_normal.render(value, True, self.text_secondary)
            
            surface.blit(label_surf, (dialog_x + 20, settings_y))
            surface.blit(value_surf, (dialog_x + 200, settings_y))
            
            settings_y += 30
        
        # Buttons
        button_y = dialog_y + dialog_height - 60
        button_width = 80
        button_height = 35
        
        # Slice button
        slice_button = Rect(dialog_x + dialog_width - 180, button_y, button_width, button_height)
        pygame.draw.rect(surface, self.accent, slice_button.rect, border_radius=4)
        
        slice_text = self._font_normal.render("Slice", True, pygame.Color(255, 255, 255))
        text_rect = slice_text.get_rect(center=slice_button.center)
        surface.blit(slice_text, text_rect)
        
        # Cancel button
        cancel_button = Rect(dialog_x + dialog_width - 80, button_y, button_width, button_height)
        pygame.draw.rect(surface, self.card_bg, cancel_button.rect, border_radius=4)
        pygame.draw.rect(surface, self.text_secondary, cancel_button.rect, width=1, border_radius=4)
        
        cancel_text = self._font_normal.render("Cancel", True, self.text_secondary)
        text_rect = cancel_text.get_rect(center=cancel_button.center)
        surface.blit(cancel_text, text_rect)
    
    def _draw_support_dialog(self, surface: pygame.Surface, region: Rect):
        """Draw the support generation dialog."""
        overlay = pygame.Surface(region.rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surface.blit(overlay, region.rect.topleft)
        
        dialog_width = 400
        dialog_height = 250
        dialog_x = region.x + (region.w - dialog_width) // 2
        dialog_y = region.y + (region.h - dialog_height) // 2
        
        dialog_rect = Rect(dialog_x, dialog_y, dialog_width, dialog_height)
        pygame.draw.rect(surface, self.card_bg, dialog_rect.rect, border_radius=8)
        pygame.draw.rect(surface, self.border_color, dialog_rect.rect, width=1, border_radius=8)
        
        title_text = self._font_large.render("Generate Support", True, self.text_primary)
        surface.blit(title_text, (dialog_x + 20, dialog_y + 20))
        
        # Support settings
        settings_y = dialog_y + 60
        settings_text = [
            ("Type:", "Tree"),
            ("Density:", "30%"),
            ("Thickness:", "0.4mm"),
            ("Max Angle:", "45°"),
        ]
        
        for label, value in settings_text:
            label_surf = self._font_normal.render(label, True, self.text_primary)
            value_surf = self._font_normal.render(value, True, self.text_secondary)
            
            surface.blit(label_surf, (dialog_x + 20, settings_y))
            surface.blit(value_surf, (dialog_x + 200, settings_y))
            
            settings_y += 30
        
        # Buttons
        button_y = dialog_y + dialog_height - 60
        button_width = 80
        button_height = 35
        
        # Generate button
        generate_button = Rect(dialog_x + dialog_width - 180, button_y, button_width, button_height)
        pygame.draw.rect(surface, self.accent, generate_button.rect, border_radius=4)
        
        generate_text = self._font_normal.render("Generate", True, pygame.Color(255, 255, 255))
        text_rect = generate_text.get_rect(center=generate_button.center)
        surface.blit(generate_text, text_rect)
        
        # Cancel button
        cancel_button = Rect(dialog_x + dialog_width - 80, button_y, button_width, button_height)
        pygame.draw.rect(surface, self.card_bg, cancel_button.rect, border_radius=4)
        pygame.draw.rect(surface, self.text_secondary, cancel_button.rect, width=1, border_radius=4)
        
        cancel_text = self._font_normal.render("Cancel", True, self.text_secondary)
        text_rect = cancel_text.get_rect(center=cancel_button.center)
        surface.blit(cancel_text, text_rect)
    
    def _get_status_color(self, status) -> pygame.Color:
        """Get color for a print status."""
        if status == PrintStatus.PENDING:
            return pygame.Color(255, 204, 0)  # Yellow
        elif status == PrintStatus.SLICING:
            return pygame.Color(59, 130, 246)  # Blue
        elif status == PrintStatus.READY:
            return pygame.Color(52, 211, 153)  # Green
        elif status == PrintStatus.PRINTING:
            return pygame.Color(139, 92, 246)  # Purple
        elif status == PrintStatus.COMPLETED:
            return pygame.Color(16, 185, 129)  # Teal
        elif status == PrintStatus.FAILED:
            return pygame.Color(239, 68, 68)  # Red
        else:
            return self.text_secondary
    
    def _get_printer_status_color(self, status: str) -> pygame.Color:
        """Get color for printer status."""
        status_lower = status.lower()
        if status_lower == "ready":
            return pygame.Color(52, 211, 153)  # Green
        elif status_lower == "printing":
            return pygame.Color(59, 130, 246)  # Blue
        elif status_lower == "error":
            return pygame.Color(239, 68, 68)  # Red
        elif status_lower == "maintenance":
            return pygame.Color(251, 146, 60)  # Orange
        else:
            return self.text_secondary
    
    def _draw_settings_button(self, surface: pygame.Surface, region: Rect):
        """Draw the settings button."""
        button_size = self._s(28)
        button_rect = Rect(
            region.right - self._s(10) - button_size,
            region.y + self._s(10),
            button_size,
            button_size
        )
        
        pygame.draw.rect(surface, self.card_bg, button_rect.rect, border_radius=self._s(5))
        pygame.draw.rect(surface, self.accent, button_rect.rect, width=1, border_radius=self._s(5))
        
        # Settings icon (simplified)
        icon_size = self._s(16)
        icon_x = button_rect.x + (button_rect.w - icon_size) // 2
        icon_y = button_rect.y + (button_rect.h - icon_size) // 2
        
        pygame.draw.rect(surface, self.accent, (
            icon_x, icon_y, icon_size, icon_size
        ))


# Global UI instance
_printing_ui_enhanced = PrintingWorkspaceUI()


def get_printing_ui_enhanced() -> PrintingWorkspaceUI:
    """Get the global enhanced printing workspace UI instance."""
    return _printing_ui_enhanced