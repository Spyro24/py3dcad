# Toolbar Design

## Structure

The toolbar has three main sections:

```
┌─────────────────────────────────────────────────────────────────┐
│  Workspace Label    Mode Tabs              Sketch Tools    ⚙  │
│  DESIGN ▼           SOLID | SURFACE | ...  [Groups...]      │
└─────────────────────────────────────────────────────────────────┘
```

## Workspace Label

- Fixed left section (152px scaled + 8px margins)
- "DESIGN" label with dropdown caret
- "workspace" sublabel
- Click opens workspace menu (future)

## Mode Tabs

Dynamic tabs based on document state:

### No Active Sketch
```
SOLID  SURFACE  MESH  SHEET METAL  PLASTIC  UTILITIES
```

### Active Sketch
```
SKETCH  SOLID  SURFACE  MESH  SHEET METAL  PLASTIC  UTILITIES
```

- SKETCH tab auto-selected when sketch active
- Tabs truncate with reduced padding if too wide
- Active tab: colored underline (accent for SKETCH, white for others)
- Hover: subtle background highlight

## Sketch Toolbar (SKETCH Mode Only)

Organized into captioned groups:

### Group Structure

```python
SKETCH_GROUPS = (
    ("CREATE", [
        ("line", "Line", True),           # Dropdown for line types
        ("rectangle", "Rectangle", True), # Dropdown
        ("circle", "Circle", True),       # Dropdown
        ("arc", "Arc", True),             # Dropdown
        ("slot", "Slot", True),           # Dropdown
        ("polygon", "Polygon", True),     # Dropdown
        ("spline", "Spline", True),       # Dropdown
        ("point", "Point", False),
    ]),
    ("MODIFY", [
        ("fillet", None, False),
        ("trim", None, False),
    ]),
    ("PATTERN", [
        ("linear_pattern", None, True),
        ("circular_pattern", None, True),
    ]),
    ("CONSTRAINTS", [
        ("constraint_auto", "V/H", True), # Dropdown for constraint types
    ]),
    ("INSPECT", [
        ("measure", None, True),
        ("section_view", None, False),
    ]),
    ("INSERT", [
        ("insert_part", None, True),
        ("insert_sketch", None, False),
    ]),
    ("SELECT", [
        ("select", None, True),
    ]),
    ("FINISH SKETCH", [
        ("finish_sketch", None, False),
    ]),
)
```

### Responsive Layout

Groups automatically compact:
1. Try full labels with icons (30px)
2. Try compact labels (shorter text)
3. Try smaller icons (28, 26, 24, 22px)
4. Reduce padding/gaps
5. Drop middle groups, keep FINISH SKETCH visible

### Visual States

| State | Background | Border | Icon Color |
|-------|------------|--------|------------|
| Default | Transparent | None | Category color |
| Hover | Header bg | 1px border | Category color |
| Active | Header bg | 2px accent | Accent |
| Placeholder | Transparent | None | Secondary text |

### Category Colors

- **CREATE** tools: Accent blue (#3B82F6)
- **MODIFY**: Orange (#FB923C)
- **PATTERN**: Green (#4ADE80)
- **CONSTRAINTS**: Accent blue (when active)
- **INSPECT**: Purple (#A855F7)
- **INSERT**: Cyan (#22D3EE)
- **SELECT**: Green (#4ADE80)
- **FINISH SKETCH**: Accent blue

## Action Buttons (Non-Sketch Modes)

Two primary actions:

```
[Sketch] [Extrude]
```

- **Sketch**: Always enabled, opens plane selector
- **Extrude**: Enabled when sketch has ≥3 profile points

## Settings Button

- Top-right of toolbar (28px scaled)
- Gear icon
- Opens settings dialog
- Tooltip on hover

## Dropdown Menus

### Line Type Dropdown
Triggered by caret on Line tool:
- Normal
- Construction Line
- Centerline

### Constraint Dropdown
Triggered by caret on V/H tool:
- Auto (Vertical/Horizontal)
- Vertical Only
- Horizontal Only

### Pattern Dropdowns
On Linear/Circular Pattern tools (future)

## Tooltips

- Show on hover after 500ms
- Tool name + shortcut (e.g., "Line (L)")
- Positioned below toolbar, centered on button
- Dark background, light text, rounded corners

## Keyboard Shortcuts

| Tool | Shortcut |
|------|----------|
| Sketch | S |
| Extrude | E |
| Line | L |
| Point | P |
| Finish Sketch | F |
| Select | V |
| Escape | Deselect tool |

## Adding New Tools

1. Add action name to `ACTIVE_SKETCH_TOOLS` if interactive
2. Add to `SKETCH_INTERACTIVE_ACTIONS` if click-drag tool
3. Add to `SKETCH_CONSTRAINT_ACTIONS` if constraint tool
4. Add entry to `SKETCH_GROUPS` with (action, label, has_dropdown)
5. Add icon in `_draw_action_icon()`
6. Add color in `_kind_color()`
7. Handle click in `_handle_sketch_toolbar_click()`
8. Implement drawing/editing logic

## Future Improvements

- Customizable toolbar layout
- Tool search/filter
- Contextual tool groups
- Ribbon-style tabbed toolbar
- Touch-friendly sizing option