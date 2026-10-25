# Color System

## Palette

### Core Colors (Dark Theme - Default)

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| `bg_primary` | `#141419` | 20, 20, 25 | Window background |
| `bg_panel` | `#1F1F25` | 31, 31, 37 | Panels, toolbars, dialogs |
| `bg_header` | `#26262D` | 38, 38, 45 | Headers, active tabs, hover rows |
| `bg_hover` | `#2D2D36` | 45, 45, 54 | Hover states |
| `bg_selected` | `#2C5E9A` | 44, 94, 154 | Tree selection, active items |
| `bg_input` | `#1A1A20` | 26, 26, 32 | Input fields |
| `border` | `#32323A` | 50, 50, 58 | Borders, dividers |
| `border_focus` | `#3B82F6` | 59, 130, 246 | Focus rings, active borders |
| `text_primary` | `#E1E1E6` | 225, 225, 230 | Primary text |
| `text_secondary` | `#CACDD4` | 202, 205, 212 | Secondary text |
| `text_muted` | `#7D7D88` | 125, 125, 136 | Muted text, placeholders |
| `text_disabled` | `#5A5A66` | 90, 90, 102 | Disabled text |
| `accent` | `#3B82F6` | 59, 130, 246 | Primary actions, links, focus |
| `accent_hover` | `#2563EB` | 37, 99, 235 | Accent hover |
| `accent_light` | `#3B82F626` | 59, 130, 246 (15%) | Accent backgrounds |
| `success` | `#4ADE80` | 74, 222, 128 | Success states, valid |
| `warning` | `#FBBF24` | 251, 191, 36 | Warnings |
| `error` | `#EF4444` | 239, 68, 68 | Errors, destructive actions |
| `error_light` | `#EF444426` | 239, 68, 68 (15%) | Error backgrounds |

### Semantic Colors (Geometry)

| Name | Hex | Usage |
|------|-----|-------|
| `geom_vertex` | `#FFC16E` | Selected vertices, sketch points |
| `geom_edge` | `#FFC16E` | Selected edges, sketch lines |
| `geom_face` | `#3B82F64D` | Selected faces (30% opacity) |
| `geom_hover` | `#FFE0B4` | Hover highlight |
| `geom_constraint_h` | `#3B82F6` | Horizontal constraint glyph |
| `geom_constraint_v` | `#3B82F6` | Vertical constraint glyph |
| `geom_construction` | `#8B8B9A` | Construction geometry |
| `geom_centerline` | `#8B8B9A` | Centerline geometry |
| `geom_origin_x` | `#EF4444` | X axis / Red |
| `geom_origin_y` | `#4ADE80` | Y axis / Green |
| `geom_origin_z` | `#3B82F6` | Z axis / Blue |
| `geom_grid_major` | `#2A2A33` | Major grid lines |
| `geom_grid_minor` | `#1E1E24` | Minor grid lines |
| `geom_sketch_plane` | `#3B82F61A` | Active sketch plane tint (10%) |

### Tool Category Colors

| Category | Color | Hex |
|----------|-------|-----|
| Create | Accent Blue | `#3B82F6` |
| Modify | Orange | `#FB923C` |
| Pattern | Green | `#4ADE80` |
| Constraints | Accent Blue | `#3B82F6` |
| Inspect | Purple | `#A855F7` |
| Insert | Cyan | `#22D3EE` |
| Select | Green | `#4ADE80` |
| Finish | Accent Blue | `#3B82F6` |

## Light Theme (Future)

| Name | Dark | Light |
|------|------|-------|
| `bg_primary` | `#141419` | `#F5F5F7` |
| `bg_panel` | `#1F1F25` | `#FFFFFF` |
| `bg_header` | `#26262D` | `#EAEAED` |
| `bg_hover` | `#2D2D36` | `#E0E0E5` |
| `bg_selected` | `#2C5E9A` | `#D6E4F0` |
| `border` | `#32323A` | `#D1D1D6` |
| `text_primary` | `#E1E1E6` | `#1D1D1F` |
| `text_secondary` | `#CACDD4` | `#424245` |
| `text_muted` | `#7D7D88` | `#8E8E93` |

## Usage Guidelines

### Backgrounds
- Primary: Main window, viewport
- Panel: Toolbars, sidebars, dialogs, menus
- Header: Active tabs, selected tree nodes, table headers
- Input: Text fields, dropdowns

### Text
- Primary: Body text, labels, titles
- Secondary: Descriptions, subtitles, metadata
- Muted: Placeholders, disabled, hints
- Disabled: Non-interactive elements

### Borders
- Default: Panel edges, dividers, input fields
- Focus: Active input, selected items, keyboard focus
- Error: Invalid input, failed operations

### Accent
- Primary buttons
- Links
- Active states
- Progress indicators
- Selection highlights (thin)

### Geometry
- Vertex/Edge selection: Gold (`#FFC16E`) - visible on both light/dark
- Face selection: Blue with transparency
- Hover: Lighter gold
- Constraints: Accent blue
- Construction: Muted gray
- Origin axes: Standard RGB (colorblind safe)

## Accessibility

### Contrast Ratios (WCAG AA)
| Combination | Ratio | Status |
|-------------|-------|--------|
| text_primary / bg_primary | 14.2:1 | ✅ AAA |
| text_secondary / bg_primary | 11.1:1 | ✅ AAA |
| text_muted / bg_primary | 4.8:1 | ✅ AA |
| accent / bg_primary | 6.2:1 | ✅ AA |
| text_primary / bg_selected | 7.8:1 | ✅ AAA |
| geom_vertex / bg_primary | 5.9:1 | ✅ AA |

### Color Blindness
- No red/green only distinctions
- Origin axes: RGB distinct in all CVD types
- Selection gold distinct from all
- Error uses red + icon, not color alone
- Success uses green + checkmark

### High Contrast Mode (Future)
```
bg_primary: #000000
bg_panel: #000000
text_primary: #FFFFFF
text_secondary: #CCCCCC
accent: #FFFF00
border: #FFFFFF
geom_vertex: #FFFF00
geom_edge: #FFFF00
```

## Implementation

### Python (pygame.Color)

```python
# In Workspace.__init__
self.panel_bg = pygame.Color(31, 31, 37)      # #1F1F25
self.header_bg = pygame.Color(38, 38, 45)     # #26262D
self.border_color = pygame.Color(50, 50, 58)  # #32323A
self.text_primary = pygame.Color(225, 225, 230)  # #E1E1E6
self.text_secondary = pygame.Color(202, 205, 212)  # #CACDD4
self.text_muted = pygame.Color(125, 125, 136)  # #7D7D88
self.accent = pygame.Color(59, 130, 246)      # #3B82F6
self.tree_selection = pygame.Color(44, 94, 154)  # #2C5E9A
self.geometry_selection = pygame.Color(255, 193, 110)  # #FFC16E
self.geometry_hover = pygame.Color(255, 224, 180)  # #FFE0B4
```

### CSS Variables (Future Web)

```css
:root {
  --bg-primary: #141419;
  --bg-panel: #1F1F25;
  --bg-header: #26262D;
  --bg-hover: #2D2D36;
  --bg-selected: #2C5E9A;
  --border: #32323A;
  --border-focus: #3B82F6;
  --text-primary: #E1E1E6;
  --text-secondary: #CACDD4;
  --text-muted: #7D7D88;
  --accent: #3B82F6;
  --success: #4ADE80;
  --warning: #FBBF24;
  --error: #EF4444;
  --geom-vertex: #FFC16E;
  --geom-face: #3B82F64D;
}
```

### Theme Switching (Future)

```python
class ThemeManager:
    def __init__(self):
        self.themes = {
            "dark": DarkTheme(),
            "light": LightTheme(),
            "high_contrast": HighContrastTheme(),
        }
        self.current = "dark"
    
    def get_color(self, name: str) -> pygame.Color:
        return self.themes[self.current].colors[name]
```

## Design Tokens

### Spacing (scaled)
| Token | Base | Scaled (1.0x) |
|-------|------|---------------|
| space_xs | 2 | 2px |
| space_sm | 4 | 4px |
| space_md | 8 | 8px |
| space_lg | 12 | 12px |
| space_xl | 16 | 16px |
| space_2xl | 24 | 24px |

### Border Radius
| Token | Base |
|-------|------|
| radius_sm | 3px |
| radius_md | 4px |
| radius_lg | 6px |
| radius_xl | 8px |
| radius_full | 9999px |

### Shadows (Future)
| Token | Value |
|-------|-------|
| shadow_sm | 0 1px 2px rgba(0,0,0,0.3) |
| shadow_md | 0 4px 6px rgba(0,0,0,0.4) |
| shadow_lg | 0 10px 15px rgba(0,0,0,0.5) |
| shadow_focus | 0 0 0 2px var(--accent) |

### Transitions
| Token | Value |
|-------|-------|
| transition_fast | 100ms ease |
| transition_normal | 200ms ease |
| transition_slow | 300ms ease |

## Adding New Colors

1. Add to appropriate section above
2. Add to `Workspace.__init__` as `self.name`
3. Add to light theme table
4. Verify contrast ratios
5. Test with color blindness simulator
6. Document usage in this file