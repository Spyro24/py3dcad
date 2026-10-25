# UI Layout System

## Layout Configuration

```python
@dataclass
class LayoutConfig:
    tab_bar_height: int = 36
    toolbar_height: int = 104
    command_bar_height: int = 36
    timeline_height: int = 84
    sidebar_width: int = 280
    viewport_margin: int = 4
```

All dimensions are scaled by `UILayout.scale` (0.5x to 2.5x).

## Region Layout Order

1. **Tab Bar** - Top, full width
2. **Toolbar** - Below tab bar, full width
3. **Timeline** - Bottom, full width
4. **Command Bar** - Above timeline (optional), full width
5. **Document Tree** - Left sidebar, between toolbar and bottom bars
6. **Viewport** - Right side, remaining space

## Coordinate System

All regions use `Rect` helper class with:
- `x, y, w, h` - Integer coordinates
- Properties: `left, top, right, bottom, centerx, centery, center`
- `rect` property returns `pygame.Rect`
- `collidepoint(x, y)` for hit testing

## Scaling

```python
def _s(self, value: float) -> int:
    return max(1, int(round(value * self.scale)))
```

- Minimum 1 pixel for any dimension
- Rounded to nearest integer
- Applied to all layout dimensions, fonts, and UI elements

## Region Access

```python
layout.get_region("tab_bar")      # TabBar region
layout.get_region("toolbar")      # Toolbar region
layout.get_region("document_tree") # Sidebar region
layout.get_region("viewport")     # 3D view region
layout.get_region("command_bar")  # Command input region
layout.get_region("timeline")     # History timeline region
```

## Responsive Behavior

### Minimum Sizes
- Viewport: Minimum 200×200 pixels
- Document Tree: Fixed width (280px scaled)
- Timeline: Fixed height (84px scaled)

### Command Bar Toggle
- `layout.toggle_command_bar()` - Toggle visibility
- `layout.set_command_bar_visible(bool)` - Set explicitly
- When hidden, viewport expands downward

### Window Resize
- `layout.update(window)` recalculates all regions
- Called on `pygame.VIDEORESIZE` event
- Preserves sidebar width, distributes remaining space

## Region Details

### Tab Bar (`tab_bar`)
- Height: 36px scaled
- Full window width
- Contains document tabs and scale control

### Toolbar (`toolbar`)
- Height: 104px scaled
- Full window width
- Left: Workspace label + mode tabs
- Center: Sketch toolbar or action buttons
- Right: Settings button

### Document Tree (`document_tree`)
- Width: 280px scaled minus margins
- Height: Toolbar bottom to timeline top minus margins
- Left margin: 4px scaled
- Contains feature/sketch hierarchy

### Viewport (`viewport`)
- X: Sidebar right edge + margin
- Width: Window right edge - viewport X - margin
- Height: Toolbar bottom to command bar/timeline top - margin
- 3D scene rendering area

### Command Bar (`command_bar`)
- Height: 36px scaled (when visible)
- Full window width
- Above timeline
- Text input for commands

### Timeline (`timeline`)
- Height: 84px scaled
- Full window width
- Bottom of window
- History entries with playback controls

## Custom Layouts

To create a custom layout:
1. Subclass `LayoutConfig` with new dimensions
2. Pass to `UILayout(config)`
3. Or modify `layout.config` and call `layout.update(window)`

## Testing Layout

```python
layout = UILayout()
layout.set_scale(1.5)
layout.update(window)

# Verify regions
assert layout.viewport.w > 200
assert layout.document_tree.w == layout._s(280) - 2 * layout._s(4)
```