# Timeline Design

## Overview

The timeline is the horizontal history bar at the bottom of the workspace showing the document's action history with playback controls.

## Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ [Position: 5/12]  ▶  ▶▶  ⏸  ⏹  [0.35s/step]                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  │
│ │ +  │ │ Sketch │ │ Line   │ │ Line   │ │Extrude │ │Fillet  │ │Sketch2 │  │
│ │New │ │  on XY │ │  (2)   │ │  (3)   │ │ 10mm   │ │ 2mm    │ │on Face │  │
│ └────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘  │
│    0        1         2         3         4         5         6             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

### Playback Controls (Left)
| Button | Icon | Action | Shortcut |
|--------|------|--------|----------|
| Jump to Start | ⏮ | Position = 0 | Home |
| Step Back | ◀ | Position - 1 | ← |
| Play/Pause | ▶/⏸ | Toggle playback | Space |
| Step Forward | ▶ | Position + 1 | → |
| Jump to End | ⏭ | Position = Total | End |
| Stop | ⏹ | Stop, return to end | Escape |

### Position Indicator
- Format: `Position: {current}/{total}`
- Updates on every change
- Click to enter position number (future)

### Speed Control
- Slider or dropdown: 0.1s - 2.0s per step
- Default: 0.35s
- Persisted in config

### History Entries
Horizontal scrollable list of action chips

## Entry Chip Design

### Visual States

| State | Background | Border | Text | Icon |
|-------|------------|--------|------|------|
| Past (executed) | Header bg | 1px border | Primary | Kind color |
| Current (position) | Accent (10%) | 2px accent | Accent | Accent |
| Future (undone) | Panel bg (50%) | 1px border | Muted | Muted |
| Hover | Header bg | 1px accent | Primary | Kind color |
| Selected (click) | Accent (20%) | 2px accent | Accent | Accent |
| Error | Error (10%) | 2px error | Error | Error |

### Chip Content

```
┌─────────────────────────────────┐
│ ● Extrude 10mm                  │  ← Icon + Label
│    Sketch1 → Body1              │  ← Subtitle (optional)
└─────────────────────────────────┘
```

- Width: Auto (min 80px, max 200px scaled)
- Height: 56px scaled (2 lines) or 36px (compact)
- Border radius: 4px scaled
- Padding: 8px horizontal, 4px vertical

### Icons by Command Kind

| Kind | Icon | Color |
|------|------|-------|
| new_document | 📄 | #3B82F6 |
| add_sketch | ✎ | #3B82F6 |
| add_line | ⎯ | #3B82F6 |
| add_point | ● | #3B82F6 |
| add_extrude | ⟶ | #FB923C |
| add_revolve | ⟳ | #FB923C |
| add_fillet | ⌐ | #4ADE80 |
| add_chamfer | ⌓ | #4ADE80 |
| move_point | ⤳ | #A855F7 |
| move_edge | ⤳ | #A855F7 |
| set_constraint | ⫯ | #A855F7 |
| delete | 🗑 | #EF4444 |

### Subtitle Rules

- Sketch: Plane/Face reference
- Extrude/Revolve: Sketch name + result
- Fillet/Chamfer: Edge count + radius
- Move: Entity type + count
- Constraint: Type + edge count

## Interaction

### Click Entry
- Jump to that position
- Equivalent to `history_jump(index)`
- Updates document state immediately

### Right-Click Entry
Context menu:
- Jump Here
- Delete This Action
- Delete This & Future
- Suppress This Action
- Rename Label (custom label)
- Copy as Script (future)

### Drag Entry
- Drag to reorder (future - changes history)
- Visual feedback during drag
- Drop between entries

### Scroll
- Mouse wheel: Horizontal scroll
- Shift+Wheel: Horizontal scroll (alternative)
- Auto-scroll during playback
- Scroll to current position on jump

### Keyboard
| Key | Action |
|-----|--------|
| ← | Step back |
| → | Step forward |
| Home | Jump to start |
| End | Jump to end |
| Space | Play/Pause |
| Delete | Delete selected entry |
| Enter | Jump to selected entry |

## Playback

### Algorithm
```
while playing:
    wait(step_duration)
    if position < total:
        jump_to(position + 1)
        skip invisible entries
    else:
        playing = false
```

### Invisible Entries
- Commands with `timeline_visible = False`
- Skipped during playback
- Still clickable in timeline
- Shown with ghost style

### Loop Mode (Future)
- Toggle: Loop / Once / Ping-pong
- Loop: Jump to 0 after end
- Once: Stop at end
- Ping-pong: Reverse at ends

## Synchronization

### Document → Timeline
- On command execute: Add entry, scroll to end
- On undo/redo: Update position marker
- On jump: Update position, highlight entry
- On delete: Remove entry, renumber

### Timeline → Document
- Click: `history_jump(index)`
- Delete: `history_delete(index)`
- Play: `toggle_playback()`

### Viewport/Tree → Timeline
- Selection in viewport: Highlight related entries
- Select sketch in tree: Highlight sketch entry
- Select feature: Highlight feature entry

## Data Model

```python
@dataclass
class HistoryEntry:
    kind: str              # Command kind
    label: str             # Display label
    timeline_visible: bool # Show in timeline
    # Derived from command:
    icon: str
    color: Color
    subtitle: str
    index: int             # Position in full history
```

## Filtering (Future)

- Filter by: Kind, Date, User (multi-user)
- Search by label
- Show only errors
- Show only suppressed

## Compact Mode

- Height: 36px scaled
- Single line: `● Extrude 10mm`
- No subtitle
- Smaller chips (min 60px)

## Responsive Behavior

- Minimum visible entries: 3
- Ellipsis (...) when truncated (future)
- Scrollbar: Thin, auto-hide
- Touch: Swipe to scroll

## Accessibility

- ARIA labels for each entry
- Keyboard focus visible
- Screen reader announces position changes
- High contrast borders
- Reduced motion: Instant jumps (no animation)

## Performance

- Virtualized rendering (only visible + buffer)
- Max 100 entries rendered at once
- Debounced scroll events
- Entry pool reuse (object pool)

## Future Features

- Branching history (alternatives)
- Bookmarks/named positions
- Macro recording overlay
- Collaborative playback (multi-user)
- Timeline comparison (diff)
- Export timeline as script/video