# Workspace Architecture

## Overview

The PY3DCAD workspace is the main document editing interface. It follows a classic CAD application layout with distinct regions for different functions.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Tab Bar                                │
│  [Document Tabs]                                    [Scale]  │
├─────────────────────────────────────────────────────────────┤
│                      Toolbar                                  │
│  [Workspace] [Mode Tabs] [Sketch Toolbar] [Settings]         │
├─────────────────┬────────────────────────────────────────────┤
│ Document Tree   │              Viewport                      │
│                 │                                            │
│  [Feature Tree] │         3D Scene                           │
│                 │                                            │
├─────────────────┼────────────────────────────────────────────┤
│                 │         Command Bar (optional)             │
│                 │                                            │
├─────────────────┴────────────────────────────────────────────┤
│                        Timeline                                │
│  [History Entries]                              [Play/Pause] │
└─────────────────────────────────────────────────────────────┘
```

## Core Classes

### Workspace (`core/ui/workspace.py`)

Main workspace controller handling:
- Toolbar rendering and interaction
- Document tree rendering
- Sketch editing interactions (points, lines, constraints)
- Line preview during drawing
- Selection and highlighting
- Constraint visualization
- Timeline rendering
- Tool windows (Create Sketch, Sketch Palette)

### UILayout (`core/ui/layout.py`)

Layout calculator that:
- Computes region rectangles based on window size
- Handles DPI scaling
- Manages command bar visibility
- Provides region access by name

### Viewport (`core/ui/viewport.py`)

3D view component:
- Camera management (orbit, pan, zoom)
- Origin planes/axes rendering
- Orientation cube
- Sketch plane visualization
- Face/edge/vertex highlighting
- Mouse-to-world projection

## Data Flow

```
User Input → Workspace.handle_event()
    ↓
Application callbacks (on_add_line, on_move_point, etc.)
    ↓
CommandStack.execute(Command)
    ↓
Document mutation
    ↓
Workspace.draw() → Viewport.draw() → Scene rendering
```

## Editing Modes

### Solid Mode (Default)
- Feature-based modeling
- Sketch → Extrude workflow
- History timeline visible
- Document tree shows features

### Sketch Mode
- Active when editing a sketch
- Sketch toolbar visible
- 2D drawing tools (line, point, constraints)
- Palette window for line type/constraints
- Camera aligned to sketch plane

### Other Modes (Placeholders)
- SURFACE, MESH, SHEET METAL, PLASTIC, UTILITIES
- Currently share Solid mode UI

## State Management

Workspace maintains:
- `_active_mode_name`: Current mode tab
- `_selected_tool`: Active sketch tool (line, point, etc.)
- `_line_start`, `_line_preview`: Line drawing state
- `_selected_sketch_entity`: Currently selected point/line
- `_drag_point_index`, `_drag_edge_index`: Drag operations
- `_hover_*`: Hover states for tooltips/highlighting
- `_sketch_toolbar_visible`: Computed from document state

## Extension Points

To add a new sketch tool:
1. Add to `ACTIVE_SKETCH_TOOLS` and `SKETCH_INTERACTIVE_ACTIONS`
2. Add to `SKETCH_GROUPS` with icon drawing in `_draw_action_icon`
3. Handle in `_handle_sketch_toolbar_click`
4. Implement drawing in `_draw_line_preview` or similar
5. Add callbacks to `Workspace.__init__` and `Application`

To add a new mode:
1. Add to `MODES` tuple
2. Update `_modes()` to show conditionally
3. Add mode-specific toolbar in `_draw_action_group`
4. Handle mode switching in `_draw_modes` click handling