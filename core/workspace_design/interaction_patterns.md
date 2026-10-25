# Interaction Patterns

## Mouse Interactions

### Viewport

#### Navigation
| Action | Mouse | Modifier | Cursor |
|--------|-------|----------|--------|
| Orbit | Middle drag | - | 🔄 |
| Pan | Middle drag | Shift | 🤚 |
| Zoom | Wheel | - | 🔍 |
| Zoom | Middle drag | Ctrl | 🔍 |
| Frame All | Double-click MMB | - | - |
| Frame Selection | F key | - | - |

#### Selection
| Action | Mouse | Modifier | Behavior |
|--------|-------|----------|----------|
| Select | Left click | - | Single select |
| Multi-select | Left click | Ctrl | Toggle |
| Range select | Left drag | - | Box select (L→R: enclosed) |
| Crossing select | Left drag | - | Box select (R→L: crossing) |
| Select through | Left click | Alt | Deep select |
| Deselect | Left click | - | Empty space |
| Context menu | Right click | - | On selection |

#### Sketch Editing
| Action | Mouse | Tool | Behavior |
|--------|-------|------|----------|
| Place point | Left click | Point | Add point at cursor |
| Start line | Left click | Line | Set start point |
| End line | Left click | Line | Set end point, create line |
| Preview line | Move | Line | Show rubber band |
| Drag point | Left drag | Select | Move point |
| Drag edge | Left drag | Select | Move edge (both points) |
| Select entity | Left click | Select | Select point/line |
| Box select | Left drag | Select | Select multiple |
| Constraint | Left click | Constraint | Apply to selected edge |

#### Snap Indicators
- Endpoint: Square ✓
- Midpoint: Triangle ◬
- Center: Circle ◎
- Intersection: X ✗
- On segment: Perpendicular ⊥
- Grid: Dot ●

### Toolbar

#### Buttons
| Action | Mouse | Behavior |
|--------|-------|----------|
| Click | Left click | Activate tool |
| Hold | Left hold | Show tooltip (500ms) |
| Dropdown | Left click caret | Open menu |
| Menu item | Left click | Select option |

#### Mode Tabs
| Action | Mouse | Behavior |
|--------|-------|----------|
| Click | Left click | Switch mode |
| Hover | Move | Highlight tab |

### Document Tree

#### Navigation
| Action | Mouse | Behavior |
|--------|-------|----------|
| Select | Left click | Select node |
| Expand | Left click ▶ | Expand folder |
| Collapse | Left click ▼ | Collapse folder |
| Multi-select | Left click + Ctrl | Toggle |
| Range select | Left click + Shift | Select range |
| Edit name | Double-click label | Inline edit |
| Drag | Left drag | Reorder / Create feature |
| Context menu | Right click | Node actions |

#### Drag & Drop Targets
| Source | Target | Action |
|--------|--------|--------|
| Sketch | Body folder | Create extrude |
| Sketch | Feature | Create feature from sketch |
| Feature | Feature | Reorder history |
| Body | Body | Reorder bodies |

### Timeline

#### Playback
| Action | Mouse | Behavior |
|--------|-------|----------|
| Play | Click ▶ | Start playback |
| Pause | Click ⏸ | Pause playback |
| Step | Click ◀/▶ | Step back/forward |
| Jump | Click entry | Jump to position |
| Scrub | Drag position | Scrub through history |
| Speed | Drag slider | Change playback speed |

#### Entries
| Action | Mouse | Behavior |
|--------|-------|----------|
| Jump | Left click | Jump to position |
| Context | Right click | Entry menu |
| Select | Left click | Highlight entry |

### Dialogs & Windows

| Action | Mouse | Behavior |
|--------|-------|----------|
| Move | Drag title bar | Reposition |
| Close | Click ✕ | Close dialog |
| Resize | Drag edges | Resize (future) |
| Tab | Click tab | Switch tab |
| Input | Click field | Focus |
| Dropdown | Click ▼ | Open options |
| Slider | Drag handle | Change value |
| Checkbox | Click box | Toggle |
| Radio | Click circle | Select option |

## Keyboard Interactions

### Global Shortcuts

| Shortcut | Action | Context |
|----------|--------|---------|
| Ctrl+N | New document | Global |
| Ctrl+O | Open document | Global |
| Ctrl+S | Save document | Global |
| Ctrl+Shift+S | Save As | Global |
| Ctrl+, | Settings | Global |
| Ctrl++ | Zoom UI in | Global |
| Ctrl+- | Zoom UI out | Global |
| Ctrl+0 | Reset UI zoom | Global |
| F11 | Fullscreen | Global |

### Editing Shortcuts

| Shortcut | Action | Context |
|----------|--------|---------|
| S | Sketch tool | Document |
| E | Extrude | Document |
| L | Line tool | Sketch |
| P | Point tool | Sketch |
| F | Finish sketch | Sketch |
| V | Select tool | Sketch |
| Escape | Deselect tool | Sketch |
| Delete | Delete selected | Sketch/Tree |
| Ctrl+Z | Undo | Document |
| Ctrl+Y / Ctrl+Shift+Z | Redo | Document |
| Ctrl+A | Select all | Tree/Viewport |

### Viewport Navigation

| Shortcut | Action |
|----------|--------|
| MMB drag | Orbit |
| Shift+MMB drag | Pan |
| Wheel | Zoom |
| F | Frame all |
| Ctrl+1 | Front view |
| Ctrl+2 | Back view |
| Ctrl+3 | Left view |
| Ctrl+4 | Right view |
| Ctrl+5 | Top view |
| Ctrl+6 | Bottom view |
| Ctrl+7 | Isometric |
| Space + drag | Pan (alternate) |

### Timeline

| Shortcut | Action |
|----------|--------|
| ← | Step back |
| → | Step forward |
| Home | Jump to start |
| End | Jump to end |
| Space | Play/Pause |
| Delete | Delete selected entry |

### Tree Navigation

| Shortcut | Action |
|----------|--------|
| ↑ / ↓ | Navigate |
| ← | Collapse / Go to parent |
| → | Expand / Go to child |
| Enter | Activate / Edit name |
| F2 | Rename |
| Space | Toggle visibility |
| Delete | Delete |
| Ctrl+C / Ctrl+V | Copy/Paste |

### Text Input

| Shortcut | Action |
|----------|--------|
| Ctrl+A | Select all |
| Ctrl+C | Copy |
| Ctrl+X | Cut |
| Ctrl+V | Paste |
| Home / End | Line start/end |
| Ctrl+← / Ctrl+→ | Word navigation |
| Shift+arrows | Extend selection |
| Escape | Cancel / Blur |
| Enter | Confirm |

## Touch Interactions (Future)

### Viewport
| Gesture | Action |
|---------|--------|
| One finger drag | Orbit |
| Two finger drag | Pan |
| Pinch | Zoom |
| Double tap | Frame selection |
| Long press | Context menu |

### Toolbar
| Gesture | Action |
|---------|--------|
| Tap | Activate tool |
| Long press | Tooltip / Dropdown |

### Tree
| Gesture | Action |
|---------|--------|
| Tap | Select |
| Double tap | Edit / Activate |
| Swipe left | Collapse |
| Swipe right | Expand |
| Long press | Context menu |

### Timeline
| Gesture | Action |
|---------|--------|
| Swipe horizontal | Scroll |
| Tap entry | Jump |
| Long press entry | Context menu |

## Interaction States

### Button States
```
Default → Hover → Active → Focus → Disabled
```

### Selection States
```
None → Hover → Selected → Active (editing)
```

### Drag States
```
Idle → Potential (threshold) → Dragging → Drop/Abort
```

### Tool States
```
Inactive → Active → Drawing (line) → Complete
```

## Feedback Patterns

### Visual Feedback
- **Hover**: Background highlight, cursor change
- **Active**: Pressed appearance, border change
- **Focus**: Outline ring (2px accent)
- **Selected**: Background color, border
- **Disabled**: 50% opacity, no interaction
- **Loading**: Spinner, disabled state
- **Error**: Red border, shake animation
- **Success**: Green flash, checkmark

### Cursor Types
| Cursor | Use Case |
|--------|----------|
| Default | General |
| Pointer | Buttons, links |
| Crosshair | Sketch drawing |
| Move | Dragging objects |
| Grab/Grabbing | Panning |
| Zoom-in/out | Zoom controls |
| Not-allowed | Disabled, invalid drop |
| Context-menu | Right-click available |
| Text | Text input |
| Col-resize | Splitter |
| Row-resize | Splitter |

### Tooltips
- Delay: 500ms
- Position: Below element, centered
- Offset: 8px
- Max width: 300px
- Dismiss: Mouse leave, click, Escape

### Notifications (Future)
- Toast: Top-right, auto-dismiss (3s)
- Inline: In context, dismissible
- Modal: Blocking, requires action

## Drag & Drop

### Visual Feedback
- **Drag source**: Semi-transparent ghost
- **Drop target**: Highlight border, background
- **Valid drop**: Green accent border
- **Invalid drop**: Red border, not-allowed cursor
- **Drag image**: Custom preview (icon + label)

### Data Transfer
```
Internal: JSON {type, id, data}
External: Text (future), File (future)
```

## Accessibility

### Keyboard Focus
- Visible focus ring on all interactive elements
- Logical tab order (left→right, top→bottom)
- Focus trap in modals
- Restore focus on close

### Screen Readers
- ARIA labels on all controls
- Live regions for status changes
- Role attributes (button, tab, treeitem, etc.)
- State attributes (aria-selected, aria-expanded)

### Reduced Motion
- Disable animations
- Instant transitions
- No auto-play

### High Contrast
- System color integration
- Border-based focus (not color-only)
- Pattern + color for states

## Error Handling

### Input Validation
- Real-time: On blur, show inline error
- Submit: Validate all, focus first error
- Clear: On input change

### Operation Errors
- Toast notification
- Console log
- Document remains valid (transactions)

### Recovery
- Undo available for most actions
- Auto-save draft (future)
- Crash recovery dialog (future)

## Performance

### Event Handling
- Debounce: Resize, scroll (100ms)
- Throttle: Mouse move, drag (16ms)
- Passive listeners: Scroll, touch
- Capture: Drag, modal focus

### Rendering
- Dirty rect invalidation
- 60fps target
- Frame budget: 16ms
- Profiling markers