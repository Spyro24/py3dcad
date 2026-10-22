# STYLE.md - PY3DCAD Visual Style

This document describes the visual language of the PY3DCAD desktop UI. It is
the reference for new screens and components. It reflects the current pygame-ce
implementation; when in doubt, match the closest existing component first and
use the tokens below.

Related documents: [`agents.md`](agents.md) (engineering rules),
[`roadmap.md`](roadmap.md) (product scope).

## 1. Design principles

- **Dark, technical, calm.** The interface is a neutral charcoal shell around a
  bright 3D viewport. Colour is reserved for state, geometry axes and feature
  kinds.
- **Surface steps, not shadows.** Depth comes from layered greys, 1 px borders
  and rounded corners. There are no drop shadows, gradients or glass effects.
- **Quiet chrome, clear content.** Toolbars and panels use muted labels; the
  active document and active tool carry the accent colour, while selected
  geometry adds the warm geometry-selection overlay.
- **Hand-drawn, code-built.** All icons and previews are drawn with pygame
  primitives. The app ships no image or icon assets.
- **Everything scales.** UI scale is a user setting (0.75x to 2.0x). Every
  geometry value and font size is multiplied by the current scale.
- **Immediate feedback.** Hover, selection, disabled and applied states are
  always visible. Motion is functional only.

## 2. Colour tokens

Values are `RGB(r, g, b)` as used in the code. Hex is provided for reference.
Use the canonical value from this table for new work; do not invent one-off
colours.

### Surfaces

| Token | RGB | Hex | Usage |
| --- | --- | --- | --- |
| `window` | 20, 20, 25 | `#141419` | Window backdrop behind all regions |
| `viewport` | 24, 24, 30 | `#18181E` | 3D viewport background |
| `tab_bar` | 24, 24, 29 | `#18181D` | Document tab bar |
| `start_page` | 26, 26, 30 | `#1A1A1E` | Start page background |
| `panel` | 31, 31, 37 | `#1F1F25` | Toolbar, document tree, command bar, timeline |
| `surface_raised` | 38, 38, 45 | `#26262D` | Cards, headers, hovered controls, dialog panels |
| `surface_hover` | 40, 40, 47 | `#28282F` | Card and tab hover |
| `surface_active` | 48, 48, 56 | `#303038` | Active tab, hovered dialog control |
| `field` | 27, 27, 33 | `#1B1B21` | Text inputs, checkbox wells, unapplied history boxes |
| `toolbar_surface` | 34, 34, 40 | `#222228` | Inactive tabs |
| `overlay` | 0, 0, 0 @ 150 alpha | - | Modal backdrop; dims the whole window |

### Borders and dividers

| Token | RGB | Hex | Usage |
| --- | --- | --- | --- |
| `border` | 50, 50, 58 | `#32323A` | Default 1 px border and separators |
| `border_soft` | 52, 52, 60 | `#34343C` | Tab bar and toolbar separators |
| `border_strong` | 64, 64, 74 | `#40404A` | Modal dialog borders |
| `divider` | 48, 48, 55 | `#303037` | Start-page section dividers |

### Text

| Token | RGB | Hex | Usage |
| --- | --- | --- | --- |
| `text_primary` | 230, 230, 235 | `#E6E6EB` | Titles, active labels, primary actions |
| `text_secondary` | 202, 205, 212 | `#CACDD4` | Tree rows, card paths, body text |
| `text_muted` | 125, 125, 136 | `#7D7D88` | Inactive tabs, hints, placeholders, disabled labels |

Slight per-component variants exist (for example 225, 225, 230 or
232, 232, 237). Treat the table as canonical and converge on it when touching a
component.

### Accent and state

| Token | RGB | Hex | Usage |
| --- | --- | --- | --- |
| `accent` | 59, 130, 246 | `#3B82F6` | Active tab underline, focus, primary button, playhead |
| `accent_hover` | 88, 155, 255 | `#589BFF` | Hovered primary button |
| `selection` | 44, 94, 154 | `#2C5E9A` | Selected tree row / origin plane |
| `error` | 235, 100, 100 | `#EB6464` | Validation errors |
| `disabled` | 82, 82, 92 | `#52525C` | Disabled icons |
| `tree_hover` | 45, 45, 54 | `#2D2D36` | Hover on an active tree row |

### Feature kinds

Feature and action icons use a small semantic palette. Keep these colours
consistent across the toolbar, document tree and timeline.

| Kind | RGB | Hex |
| --- | --- | --- |
| `sketch` | 82, 205, 132 | `#52CD84` |
| `extrude` | 78, 148, 235 | `#4E94EB` |
| `point` | 105, 178, 242 | `#69B2F2` |
| `neutral` | 150, 150, 160 | `#9696A0` |

### 3D scene

| Token | RGB | Hex | Usage |
| --- | --- | --- | --- |
| `scene_background` | 24, 24, 30 | `#18181E` | Viewport clear colour |
| `grid` | 38, 38, 45 | `#26262D` | Minor grid lines |
| `grid_major` | 46, 46, 54 | `#2E2E36` | Major grid lines |
| `axis_x` | 200, 70, 70 | `#C84646` | X axis |
| `axis_y` | 70, 180, 90 | `#46B45A` | Y axis (up) |
| `axis_z` | 70, 110, 220 | `#466EDC` | Z axis |
| `origin_plane` | 255, 224, 180 | `#FFE0B4` | Origin plane fill |
| `origin_plane_selected` | 255, 193, 110 | `#FFC16E` | Hovered / selected origin plane |
| `geometry_hover` | 255, 224, 180 | `#FFE0B4` | Hovered sketch point or line |
| `geometry_selection` | 255, 193, 110 | `#FFC16E` | Selected sketch point or line |
| `sketch_line` | 120, 145, 185 | `#7891B9` | Inactive sketch geometry |
| `active_geometry` | 59, 130, 246 | `#3B82F6` | Active sketch, selection |
| `solid_edge` | 55, 55, 65 | `#373741` | Solid silhouette and edges |

Technical preview thumbnails on the start page intentionally invert to a light
drawing-sheet look: background 232, 232, 234, grid 207, 207, 211, shape fills
198/158/128, edges 78, 78, 84, axes 210, 70, 70 / 70, 170, 70 / 70, 100, 220.

## 3. Typography

- UI face: **Segoe UI** (`pygame.font.SysFont("Segoe UI", ...)`).
- Monospace: **Consolas**, only for file paths and editable path text.
- Do not add other font families without a design discussion.
- All sizes are base sizes multiplied by UI scale. Rebuild cached fonts whenever
  `set_scale()` runs.

| Role | Size | Weight | Where |
| --- | --- | --- | --- |
| Dialog title | 18 | Bold | Save and Settings dialogs |
| Brand | 16 | Bold | Tab bar and start page wordmark |
| Section / primary button | 15 | Regular | "Recent", "Samples", "New Design", "Open..." |
| Card name | 14 | Regular | Recent and sample cards |
| Body / label | 13 | Regular | Dialogs, tabs; bold for toolbar labels |
| Mode tab | 12 | Bold | `SOLID`, `SURFACE`, ... |
| Small | 11-12 | Regular | Hints, tooltips, status lines, timeline labels |
| Caption | 10 | Bold | `CREATE`, compact uppercase captions |
| Mono | 13 | Regular | File path input |

Guidelines:

- Uppercase is reserved for tool modes and compact group captions
  (`SOLID`, `CREATE`, `CREATE SKETCH`).
- Page actions and section headings use title case (`New Design`, `Recent`,
  `Save Document`).
- Hints and descriptions use sentence case.
- Append a space and `*` to dirty document names (`Untitled *`).
- Use `...` for actions that open another surface (`Open...`).
- Show shortcuts in parentheses after a label: `Sketch  (S)`.
- Separate inline facts with a middle dot: `sketch-1 · XY Plane · 4 points`.

## 4. Spacing and geometry

Use a 4 px grid with a 2 px half-step for fine optical alignment. Common values:
`2, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32`.

### Layout regions (base size at 1.0x)

| Region | Size | Notes |
| --- | --- | --- |
| Tab bar | 36 high | Full width, top |
| Toolbar | 104 high | Full width, below tab bar |
| Document tree | 280 wide | Left sidebar with 4 px outer margin |
| Viewport | remainder | Right of the tree, 4 px margin |
| Command bar | 36 high | Full width, above timeline |
| Timeline | 84 high | Full width, bottom |
| Viewport margin | 4 | Gap at the outer edges |

### Component metrics

| Component | Metric |
| --- | --- |
| Document tab | 96-220 wide x 28 high, 4 gap, radius 5 |
| Tab close button | 14 x 14, inset 8 from tab edge |
| New-tab (`+`) button | 30 x 28, 4 gap after the last tab |
| Workspace tile | 152 wide, full toolbar height minus 8 |
| Toolbar mode tab | 24 high |
| Toolbar action button | 40 x 38, 6 gap |
| Grouped sketch tool button | 30 high, 22-62 wide; labels under `CREATE` |
| Line-style menu | 190 wide, 28 px rows, radius 6 |
| Settings button | 28 x 28 |
| Tree root row | 34 high, radius 3 |
| Tree child row | 28 high, radius 3, 22 indent |
| Timeline control | 26 x 26 |
| Timeline action box | 30 x 30, 1 gap, minimum 14 |
| Start-page action button | 180 x 66 (min 2 columns), radius 6 |
| Start-page card | target column 272 wide, radius 6 |
| Start-page margin / gap | 16 / 16, section gap 24 |
| Floating tool panel | 322 x 158, radius 6 |
| Sketch palette | 322 wide, radius 6; 36 line-style buttons, 22 option rows; body scrolls on short viewports |
| Save dialog | 620 x 200, radius 8 |
| Settings dialog | 440 x 196, radius 8 |

### Radii and strokes

- `3` px: tree rows, checkboxes, small chips.
- `4` px: tooltips, inputs, timeline controls.
- `5` px: document tabs, toolbar buttons, workspace icon.
- `6` px: cards, primary buttons, workspace tile, floating panels.
- `8` px: modal dialogs.
- Borders are 1 px. Active markers, playheads and selected outlines use 2 px.
- Never use shadows, glows or feathered edges.

## 5. UI scale

- Scale steps are `0.75, 0.875, 1.0, 1.125, 1.25, 1.5, 1.75, 2.0`.
- Every dimension goes through a local `_s(value)` helper:
  `max(1, int(round(value * scale)))`.
- Font sizes, paddings, radii, icon sizes, hit targets and timeline boxes all
  scale. Hit targets must never fall below 1 px.
- On scale change, invalidate cached fonts, previews and layout rectangles.
- Content is clipped to its own region while drawing. Nothing may paint outside
  its region except modal overlays and popups that intentionally escape.

## 6. Components

### Tab bar

- Dark bar with the `PY3DCAD` wordmark at the left, then a vertical divider.
- One rounded tab per document. Active tab is one surface step lighter and has a
  2 px accent underline. Hover lightens the tab.
- Dirty documents show `*`. Close is an `x` glyph that brightens on hover.
- The `+` tab follows the last tab (or the "Start" label) and uses the same
  hover surface. It creates a new document.
- With no documents, show the muted "Start" label and the `+` button.

### Toolbar

- Left: workspace tile with icon, `DESIGN` and the muted `workspace` sublabel.
- Centre: uppercase mode tabs. The active mode uses primary text and a 2 px
  underline; inactive modes are muted.
- Mode tabs are clickable. Hover adds the raised surface. Switching modes while
  a sketch is open only changes the visible tool group: the sketch stays
  active, its palette stays visible, and the `SKETCH` tab remains available.
  Leaving `SKETCH` disarms the current sketch tool so a hidden tool cannot draw
  from another mode. Use `Finish Sketch` to end sketch editing.
- While a sketch is being edited, a `SKETCH` tab is prepended and becomes the
  active mode. It uses the green `sketch` kind colour for its label and
  underline; the normal mode tabs remain muted.
- Below the modes: square action buttons. Normal mode shows Sketch and Extrude
  under the bold `CREATE` caption. Extrude stays in the solid tools.
- Sketch editing uses a full grouped command bar: `CREATE`, `MODIFY`, `PATTERN`,
  `CONSTRAINTS`, `INSPECT`, `INSERT`, `SELECT`, `FINISH SKETCH`. Groups are
  separated by 1 px vertical rules and carry a bold uppercase caption at the
  bottom. Group captions are plain labels, not dropdown menus. `CREATE` shows
  labelled tools with dropdown carets; `Line` and `Point` are active. Other
  grouped tools are neutral placeholders for future tools. `FINISH SKETCH`
  stays at the far right with a green check and two-line green caption.
- The `Line` caret opens a compact line-style menu (`Line`,
  `Construction Line`, `Centerline`). Choosing a style selects the Line tool,
  updates the sketch and palette line type, and closes the menu. Clicking
  outside the menu dismisses it.
- Point is selected when sketch editing begins. Point places standalone
  vertices and never connects them; Line draws chained two-click segments
  between points. Every segment references two point entities, so its
  endpoints stay visible and moving one endpoint moves every attached segment.
  Only a closed loop of edges is an extrusion profile. Hover adds the raised
  surface plus a 1 px border; the selected tool gets a 2 px accent border.
- Sketch entities are directly editable. With Point or no tool armed, clicking
  a point selects it and starts a drag; releasing after movement commits one
  undoable move. Clicking a line selects it and starts an edge drag with any
  tool; dragging translates the edge by moving both endpoint entities, so
  attached segments follow. Releasing after movement commits one hidden
  undoable move. Points take hit-test priority over lines, and clicking empty
  space clears the selection before the active Point or Line tool acts. Hover
  outlines sketch points and lines in `geometry_hover`; selection uses a
  thicker `geometry_selection` outline.
- With the Line tool armed, clicking an existing point snaps to it and starts
  or continues the chain instead of starting a point drag. This keeps shared
  segment endpoints connected while drawing. Clicking or dragging a line
  selects or moves the edge instead of starting a line chain.
- `Esc` deselects the current sketch tool, clears the entity selection and
  cancels an in-progress line, point drag or edge drag. It does not leave
  sketch mode or close the sketch palette. Click Point or Line to draw again.
  Clicking `Finish Sketch` ends sketch editing and restores the solid tools.
- Right: gear icon button, 28 x 28. Tooltips use `field`-dark background,
  1 px border and 8 px horizontal / 4 px vertical padding.

### Document tree

- Flat rows, no scrollbars or shadows. Root document row uses the selection
  colour; other selected rows use a lighter grey.
- Hover uses the raised header surface. Selected plane uses `selection`.
- Disclosure triangles, folder, cube, plane and gear glyphs are drawn inline.
- Use 22 px indentation for children and keep text on a common baseline.

### Viewport

- Dark neutral background with a subtle two-tone grid. Axes are the only
  saturated colours by default.
- HUD: document or sketch status at top-left (13 bold, muted); contextual hint at
  bottom-left (12, muted). Keep hints to one line and use `·` separators.
- Selection always wins over base geometry colour: active sketch and selected
  faces use `accent`; selected sketch points and lines use
  `geometry_selection`, and their hover state uses `geometry_hover`.

### Timeline

- Panel background with a top border. Transport controls on the left, then a
  light vertical separator, then one box per history action.
- Only top-level document actions belong here: sketch creation and solid
  features. Sketch-internal edits such as points, lines and point moves stay
  undoable but are omitted from the timeline. Transport previous/next steps
  between these visible actions.
- Applied actions use the lighter history surface; future actions use `field`.
  Hover lightens applied boxes. The selected action gets a 2 px accent border.
- The playhead is a 2 px accent line with a 3 px dot.
- Feature icons use the semantic kind colours.
- Idle hint: `No actions yet  —  create a sketch to start the history`.
  Keyboard hints sit at the bottom-left in small muted text.

### Command bar

- Single line, 36 high. Accent `>` prompt, muted placeholder, muted
  `Roll History Marker  n / m` status right-aligned. The `n / m` values count
  timeline-visible actions, not hidden sketch edits.
- Truncate the placeholder with an ellipsis rather than wrapping or clipping
  mid-glyph.

### Start page

- One muted background with content on a 4 px grid.
- Primary action: solid accent, white text and icon, no border contrast needed.
  Secondary action: card surface, primary text, border turns accent on hover.
- Cards: raised surface, 1 px border, radius 6, preview on top, two to three
  lines of text below. Hover raises the surface and turns the border accent.
- Preview thumbnails are cached per size and scale. Use the light technical
  drawing style rather than a dark screenshot.
- Sections are introduced by a muted 15 px label. Empty recent state shows the
  muted hint `No recent documents yet`.
- Scrolling is content-only; the action buttons scroll with the content.

### Dialogs

- Modal: draw a full-window `(0, 0, 0, 150)` overlay before the panel.
- Panel: `surface_raised` fill, `border_strong` 1 px outline, radius 8, centred.
- Title at 18 bold, 18-24 px inner padding.
- Inputs: `field` background, radius 4, accent 1 px border when focused.
- Errors are `error` coloured, small, and placed under the field.
- Settings uses a custom checkbox: 18 x 18, radius 3, accent fill when checked.

### Floating tool windows

- Non-modal panels anchored in the viewport, radius 6, `surface_raised` fill and
  1 px border. They never block viewport picking outside the panel.
- Fields and buttons use the darker `field` / `button` surfaces with accent
  hover/selection. Labels are 12 px; titles are 12 px bold and uppercase.
- The sketch palette uses an inset rounded title bar, a collapsible `Options`
  header, semantic line-style buttons (normal, construction, center),
  right-aligned checkboxes and a full-width status field. `Finish Sketch` is a
  filled accent button. Its body scrolls when the viewport is too short.

## 7. Iconography

- Draw icons with `pygame.draw` primitives; do not add image assets.
- Outline icons use 1-2 px strokes in `text_muted` or `text_primary`. Filled
  icons are reserved for feature kinds (sketch, extrude, point).
- Standard sizes: 14 (close), 18-24 (inline glyphs), 28-34 (toolbar buttons).
- Keep icons optically centred and scale them through `_s()`.
- Do not mix filled and outline icons within the same control group.
- Use the accent only for state, never to decorate a neutral icon.

## 8. Interaction states

| State | Treatment |
| --- | --- |
| Default | Base surface, `text_secondary` or `text_muted` |
| Hover | One surface step lighter; accent border for cards and secondary buttons |
| Active / selected | `accent` underline or 2 px border, `selection` fill for tree rows, or `geometry_selection` outline for sketch entities |
| Geometry hover | `geometry_hover` ring or line overlay, one step thinner than selection |
| Focus | `accent` 1 px border around inputs and fields |
| Disabled | `disabled` icons or `text_muted` labels; no hover response |
| Applied (history) | Lighter history surface; future actions stay dark |
| Dirty document | `*` suffix on the tab and tree name |

- Hover state is derived from the last mouse motion and cleared when the pointer
  leaves the component.
- Click targets include the whole row or button rectangle, not only the glyph.
- Avoid hover effects on non-interactive text.

## 9. Content and tone

- Labels are short, concrete and verb-led where possible: `New Design`,
  `Open...`, `Select`, `Finish Sketch`, `Extrude`.
- Hints explain the next action and the relevant shortcut:
  `Click a plane or face to select it  ·  then press S to sketch`.
  In sketch mode, `Esc` means deselect: use
  `Click to place points  ·  draw a closed loop to extrude`,
  `Click to draw a line  ·  Esc to deselect`, and
  `No tool selected  ·  click Point or Line to draw` when no tool is active.
- Use `·` between facts and `—` only for a longer pause in hints.
- Keep empty-state copy calm and instructive; never use exclamation marks.
- Units are millimetres, with Y up. Do not show unit suffixes in chrome labels
  unless the value is editable.

## 10. Implementation rules

- Model code must not import pygame; style and drawing stay in `core/ui` and
  `core/render`.
- Use the local `_s()` helper for every pixel value. Avoid raw literals in draw
  code except for 0/1 special cases.
- Reuse the palette tokens; do not add a colour inline in a draw method.
- Draw through the component's existing surface and clip; restore the previous
  clip after drawing.
- Fit text with the existing ellipsis helper instead of letting it overflow.
- Rebuild fonts and caches in `set_scale()`.
- Prefer `pygame.Rect` helpers and the shared `Rect` wrapper for layout.
- Keep functions focused and under roughly 40 lines, as required by
  [`agents.md`](agents.md).

## 11. Checklist for new UI

- [ ] Uses only the tokens in section 2.
- [ ] Type role comes from section 3; no new font family.
- [ ] All dimensions pass through `_s()`.
- [ ] Hover, active, disabled and focus states are defined where relevant.
- [ ] Content is clipped to its region and text is fitted or truncated.
- [ ] Radii and strokes match section 4 (no new values without reason).
- [ ] Icons are drawn with primitives and remain readable at 0.75x and 2.0x.
- [ ] Dark shell, light technical previews, accent reserved for state.
- [ ] No shadows, gradients, animations or image dependencies.
- [ ] Strings follow the capitalisation and tone rules in section 9.

## 12. Where the style lives

| Area | File |
| --- | --- |
| Tab bar, tabs, `+` button | `core/ui/tabbar.py` |
| Start page, buttons, cards, previews | `core/ui/startpage.py` |
| Toolbar, tree, command bar, timeline | `core/ui/workspace.py` |
| Viewport HUD and background | `core/ui/viewport.py` |
| Scene palette, grid, axes, solids | `core/render/scene.py` |
| Modal dialogs | `core/ui/save_dialog.py`, `core/ui/settings_dialog.py` |
| Floating tool panels | `core/ui/tool_properties.py` |
| Layout regions and spacing | `core/ui/layout.py` |
| Scale steps and preferences | `core/app.py`, `core/config.py` |

Palette values are currently repeated per component. When adding a component,
copy the canonical values from this document rather than introducing a new
shade. A shared theme module is a reasonable future refactor, but is not
required to follow this guide.
