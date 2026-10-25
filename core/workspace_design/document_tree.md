# Document Tree Design

## Overview

The Document Tree (feature tree) is the left sidebar showing the hierarchical structure of the document: sketches, features, bodies, and origin elements.

## Structure

```
┌─────────────────────────────────┐
│ ▼ Origin                        │
│   □ XY Plane                    │
│   □ YZ Plane                    │
│   □ ZX Plane                    │
│   □ Origin                      │
├─────────────────────────────────┤
│ ▼ Sketches                      │
│   ▶ Sketch1 (XY Plane)          │
│   ▶ Sketch2 (Face<Extrude1>)    │
├─────────────────────────────────┤
│ ▼ Bodies                        │
│   ▶ Body1                       │
│     ▼ Extrude1                  │
│       □ Sketch1                 │
│       ↑ 10.00 mm                │
├─────────────────────────────────┤
│ ▼ Construction                  │
│   □ Plane1 (Offset from XY)     │
│   □ Axis1 (Through points)      │
└─────────────────────────────────┘
```

## Node Types

### Origin (Root)
- Always present, non-deletable
- Expandable/collapsible
- Children: Planes, Axes, Origin Point

### Origin Plane
- XY, YZ, ZX planes
- Checkbox for visibility
- Click to select for sketch
- Right-click: Rename, Hide, Create Sketch

### Origin Axis
- X, Y, Z axes
- Checkbox for visibility
- Click to select

### Origin Point
- Single point at (0,0,0)
- Checkbox for visibility

### Sketches Folder
- Contains all sketches
- Auto-expands when sketch created
- Right-click: New Sketch, Import DXF

### Sketch Node
```
Sketch1 (XY Plane)     ← Name + plane/face reference
├── Profile 1          ← Closed loops (auto-detected)
├── Profile 2
└── Construction       ← Construction geometry
```

- Icon indicates plane type (XY/YZ/ZX/Face)
- Bold when active
- Right-click: Edit, Rename, Delete, Suppress, Create Feature

### Bodies Folder
- Contains solid bodies
- Auto-expands when body created

### Body Node
```
Body1
├── Extrude1           ← Feature that created body
│   ├── Sketch1        ← Consumed sketch (reference)
│   └── Distance: 10mm ← Parameter
├── Fillet1
│   └── Radius: 2mm
└── Chamfer1
    └── Distance: 1mm
```

- Features listed in creation order
- Drag to reorder (changes history)
- Right-click: Rollback here, Delete, Suppress

### Feature Node
```
Extrude1
├── Sketch1 (consumed)
├── Direction: Blind
├── Distance: 10.00 mm
├── Draft: 0°
└── Result: New Body
```

- Shows key parameters
- Expandable for full parameters
- Right-click: Edit Feature, Rollback, Delete, Suppress

### Construction Folder
- Reference geometry (planes, axes, points, coordinate systems)
- Non-parametric (no history)

## Visual Design

### Indentation
- Level 0: 0px
- Level 1: 16px scaled
- Level 2: 32px scaled
- Level 3: 48px scaled

### Row Height
- 24px scaled
- Compact mode: 20px scaled (future)

### Icons
| Type | Icon | Size |
|------|------|------|
| Folder closed | ▶ | 12px |
| Folder open | ▼ | 12px |
| Sketch | ✎ | 14px |
| Body | ◈ | 14px |
| Extrude | ⟶ | 14px |
| Revolve | ⟳ | 14px |
| Fillet | ⌐ | 14px |
| Plane | ▢ | 14px |
| Axis | ⬌ | 14px |
| Point | ● | 14px |
| Visible | ☑ | 12px |
| Hidden | ☐ | 12px |
| Active | ◆ | 10px (overlay) |

### Colors
| State | Background | Text | Icon |
|-------|------------|------|------|
| Default | Transparent | Primary | Secondary |
| Hover | Header bg | Primary | Primary |
| Selected | Tree selection | White | White |
| Active Sketch | Tree selection | Accent | Accent |
| Suppressed | Transparent | Muted | Muted |
| Error | Transparent | Red | Red |

### Expand/Collapse
- Click ▶/▼ to toggle
- Double-click node label: Edit name (sketches, features)
- Alt+Click: Expand/collapse all children

## Interaction

### Selection
- Single click: Select node
- Ctrl+Click: Toggle multi-select
- Shift+Click: Range select
- Click viewport: Sync selection

### Drag & Drop
- Sketch → Body folder: Create feature
- Feature → Feature: Reorder history
- Body → Body: Reorder bodies
- Sketch → Sketch: Reorder (visual only)

### Context Menu (Right-Click)

#### Sketch
- Edit Sketch
- Rename
- Create Extrude
- Create Revolve
- Suppress
- Delete
- Duplicate
- Export DXF

#### Feature
- Edit Feature
- Rollback Here
- Suppress
- Delete
- Move Up/Down
- Copy/Paste

#### Body
- Show/Hide
- Rename
- Delete
- Export STEP/STL

#### Origin Plane
- Create Sketch
- Hide/Show
- Rename (custom planes only)

### Keyboard Navigation
| Key | Action |
|-----|--------|
| ↑/↓ | Navigate |
| ←/→ | Collapse/Expand |
| Enter | Edit name / Activate sketch |
| Delete | Delete selected |
| F2 | Rename |
| Space | Toggle visibility |
| Ctrl+A | Select all |
| Escape | Clear selection |

## Synchronization

### Viewport → Tree
- Click geometry: Highlight corresponding node
- Select face: Show consuming feature
- Select sketch entity: Highlight sketch node

### Tree → Viewport
- Click node: Highlight in viewport
- Double-click sketch: Enter edit mode
- Checkbox: Toggle visibility

### History → Tree
- Rollback: Gray out future features
- Play: Animate feature creation
- Position indicator on timeline matches tree

## Data Model

```python
class TreeNode:
    id: str                    # Unique identifier
    type: TreeNodeType         # Origin, Sketch, Feature, Body, etc.
    label: str                 # Display name
    icon: str                  # Icon identifier
    children: List[TreeNode]   # Child nodes
    expanded: bool             # Expand state
    visible: bool              # Visibility checkbox
    selected: bool             # Selection state
    active: bool               # Active sketch/feature
    suppressed: bool           # Suppressed state
    data: Any                  # Associated document object
```

## Filtering & Search (Future)

- Filter box at top of tree
- Filter by: Name, Type, State (suppressed, error)
- Highlight matches in tree
- "Show only selected" mode

## Performance

- Virtualized rendering (only visible rows)
- Lazy expansion (load children on expand)
- Debounced viewport sync (100ms)
- Incremental updates on document change

## Accessibility

- Full keyboard navigation
- Screen reader labels for all nodes
- High contrast mode support
- Focus indicators
- ARIA roles for web version (future)