# Viewport Design

## Overview

The Viewport is the 3D rendering area showing the model, sketch planes, origin, and selection highlights.

## Camera System

### Camera Class (`core/render/camera.py`)

```python
class Camera:
    position: Vector3     # World position
    target: Vector3       # Look-at point
    up: Vector3           # Up vector (usually +Z)
    fov: float            # Field of view (degrees)
    aspect: float         # Width/height ratio
    near: float           # Near clip plane
    far: float            # Far clip plane
```

### Projection

- **Perspective**: Default, 45° FOV
- **Orthographic**: For 2D sketch editing (aligned to plane)

### Alignment

```python
camera.align_to_plane(frame: Frame)  # Align to sketch plane
camera.align_to_view("front")        # Standard views
camera.align_to_view("top")
camera.align_to_view("right")
camera.align_to_view("iso")          # Isometric
```

### Interaction

| Action | Mouse | Effect |
|--------|-------|--------|
| Orbit | Middle drag | Rotate around target |
| Pan | Shift+Middle drag | Translate target |
| Zoom | Wheel | Dolly camera |
| Zoom | Ctrl+Middle drag | Dolly camera |
| Frame All | F | Fit all geometry |

## Origin System

### Components

1. **Origin Marker** - Small coordinate axes at (0,0,0)
2. **Origin Planes** - XY, YZ, ZX planes with grid
3. **Origin Axes** - X, Y, Z lines through origin

### Visibility

- Toggle: `workspace.set_origin_visible(bool)`
- Per-plane visibility in document tree
- Planes fade at extreme zoom levels

### Visual Style

```
Plane:    Semi-transparent grid (10×10 major, 1×1 minor)
Axes:     X=Red, Y=Green, Z=Blue (RGB = XYZ)
Marker:   Small RGB tripod at origin
Labels:   "X", "Y", "Z" at axis ends
```

### Plane Selection

- Hover: Highlight plane edge, show label
- Click: Select plane for new sketch
- Selected: Bold outline, plane name in tree

## Sketch Visualization

### Active Sketch

- **Plane**: Semi-transparent tint matching sketch color
- **Grid**: Aligned to sketch frame, 10mm major lines
- **Geometry**: 
  - Points: Small circles (6px)
  - Lines: 2px wide, color by constraint
  - Construction: Dashed, muted color
  - Centerlines: Dash-dot, muted color

### Inactive Sketches

- Wireframe only
- Muted colors
- Selectable in document tree

### Profile Detection

- Closed loops highlighted
- Fill preview on hover
- Extrude button enabled when valid profile exists

## Selection & Highlighting

### Selection Types

| Type | Visual | Color |
|------|--------|-------|
| Vertex | Square + label | #FFC16E (gold) |
| Edge | Thick line | #FFC16E (gold) |
| Face | Transparent fill | #3B82F6 (blue, 30%) |
| Sketch Point | Circle + crosshair | #FFC16E |
| Sketch Line | Thick line | #FFC16E |

### Hover Highlight

- Softer version of selection color
- #FFE0B4 (light gold) for geometry
- Preview tooltip with name/type

### Multi-Selection

- Ctrl+Click to add/remove
- Box select (drag left→right: enclosed; right→left: crossing)
- Selection set shown in document tree

## Orientation Cube

### Location

- Top-right of viewport
- 60×60px scaled
- Semi-transparent background

### Faces

```
      +Y (Top)
      
-X (Left)  +Z (Front)  +X (Right)  -Z (Back)
      
      -Y (Bottom)
```

### Interaction

- Hover face: Highlight, show label
- Click face: Align camera to that view
- Click corner: Isometric view
- Drag: Free orbit (future)

### Visibility

- Toggle in settings
- Auto-hide when viewport < 400px wide

## Grid & Snapping

### World Grid

- Visible when no sketch active
- 10mm major, 1mm minor lines
- Fades with zoom
- Origin-aligned

### Sketch Grid

- Aligned to sketch plane
- 10mm major, 1mm minor
- Visible during sketch editing
- Snap to grid points (future)

### Snap Targets

- Endpoints
- Midpoints
- Centers
- Intersections
- Grid points
- On-segment (perpendicular)

## Rendering Pipeline

### Scene (`core/render/scene.py`)

```python
class Scene:
    meshes: List[Mesh]          # Solid bodies
    sketch_overlays: List[Overlay]  # Active sketch
    origin: Origin              # Origin system
    orientation_cube: Cube      # View cube
```

### Draw Order

1. Clear (dark background #141419)
2. World grid (if no sketch)
3. Origin planes/axes
4. Solid meshes (opaque)
5. Selected face highlights
6. Sketch plane (if active)
7. Sketch geometry
8. Sketch constraints (H/V glyphs)
9. Line preview (during drawing)
10. Drag previews
11. Orientation cube
12. HUD (coordinate display, etc.)

### Performance

- Frustum culling for meshes
- Level-of-detail for tessellation
- Instanced rendering for repeated features
- Dirty flags for minimal redraw

## Coordinate Display

### Status Bar (Bottom of Viewport)

```
X: 12.345  Y: -6.789  Z: 0.000  |  ΔX: 5.000  ΔY: 3.000  ΔZ: 0.000  |  100%
```

- Absolute cursor position (world)
- Delta from last click
- Zoom percentage

### Units

- Internal: Millimeters
- Display: Configurable (mm, cm, m, in, ft)
- Precision: 3 decimal places default

## Coordinate Systems

### World Space
- Right-handed: X right, Y up, Z out of screen
- Origin at (0,0,0)

### Screen Space
- Origin top-left
- X right, Y down
- Pixels (scaled by DPI)

### Sketch Space (UV)
- 2D coordinates on sketch plane
- Origin at sketch frame origin
- U = local X, V = local Y

### Conversions

```python
# World → Screen
screen = camera.project(world_point, viewport_center)

# Screen → World (on plane)
world = camera.unproject(screen_point, plane_frame)

# Sketch → World
world = sketch_frame.to_world(uv_point)

# World → Sketch
uv = sketch_frame.to_local(world_point)
```

## Visual Themes

### Dark (Default)
- Background: #141419
- Grid: #2A2A33 (major), #1E1E24 (minor)
- Text: #E1E1E6
- Selection: #FFC16E

### Light (Future)
- Background: #F5F5F7
- Grid: #E0E0E5 (major), #EAEAED (minor)
- Text: #1D1D1F
- Selection: #007AFF

## Accessibility

- High contrast mode (future)
- Color-blind safe palette
- Scalable UI (0.5x - 2.5x)
- Keyboard navigation for all viewport actions

## Future Features

- Real-time shadows
- Ambient occlusion
- PBR materials
- Section view cutting plane
- Exploded view animation
- Measurement tools overlay
- Annotation/dimension display