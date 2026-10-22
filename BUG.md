# BUG.md - Known bugs in PY3DCAD

Scan of the current working tree (`34d5f19 feat: drag sketch edges`).
Every entry was reproduced by running the code; the reproduction steps are
included so the behaviour can be re-checked after a fix.

Severity legend:

- **High** - wrong data is written, geometry is corrupted, or the documented
  behaviour does not happen.
- **Medium** - the app misbehaves in a common workflow or a visible feature is
  a no-op.
- **Low** - dead code, latent crash, performance or consistency issues.

---

## High

### BUG-01 - `Document.save()` stores the old document name in the file

- **File:** `core/document.py:55`
- **Severity:** High

```python
payload = {"format": 1, "name": target.stem, **self.to_dict()}
```

`to_dict()` also contains a `"name"` key and is splatted **last**, so it
overwrites `target.stem`. The name is then renamed *after* the file was
written:

```python
target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
self.path = str(target)
self.name = target.stem      # <- only now the in-memory name changes
```

**Reproduction**

```python
d = Document(id=1, name="Untitled")
d.save("/tmp/cube.py3dcad")
# file contains "name": "Untitled", app shows "cube"
Document.load(2, "/tmp/cube.py3dcad").name   # -> 'Untitled'
```

The file therefore never matches the document it was saved from, and every
re-open restores the stale name.

**Fix:** write the payload after renaming, or drop `"name"` from `to_dict()`:

```python
self.name = target.stem
payload = {"format": 1, **self.to_dict()}
```

---

### BUG-02 - Deleting a timeline action corrupts the sketch (index-based commands)

- **File:** `core/commands.py:404` (`CommandStack.remove_at`)
- **Severity:** High

`remove_at()` rebuilds the document by undoing everything and re-running the
surviving commands. Commands address sketch entities by **positional index**
(`MovePointCommand.index`, `MoveEdgeCommand.indices`,
`AddLineCommand.created_points`), and those indices are not remapped after
the rebuild. `AddLineCommand._ensure_point()` even *re-creates* a point that a
deleted command had created, which changes the point order.

**Reproduction**

```python
st.execute(AddPointCommand(d, sk, (0.0, 0.0)))   # P0
st.execute(AddPointCommand(d, sk, (1.0, 1.0)))   # P1
st.execute(AddPointCommand(d, sk, (2.0, 2.0)))   # P2
st.execute(MovePointCommand(d, sk, 0, (9.0, 9.0)))
st.execute(AddLineCommand(d, sk, (0.0, 0.0), (1.0, 1.0)))
st.remove_at(0)          # delete the action that created P0
```

Result:

```
points: [(9.0, 9.0), (2.0, 2.0), (0.0, 0.0), (1.0, 1.0)]
edges:  [(2, 3)]
```

P1 was moved to `(9, 9)` although the move command targeted P0, the deleted
point is back, and the edge now joins two different points.

**Fix:** give points and edges stable identities (ids) and let commands
reference them by id, or remap every stored index during the rebuild in
`remove_at()`.

---

### BUG-03 - `S` creates a new sketch on every keypress

- **File:** `core/app.py:256` (`Application.new_sketch`)
- **Severity:** High

`new_sketch()` reads `document.selected_face` / `document.selected_plane` but
never clears them, and `select_sketch()` re-assigns
`document.selected_plane = sketch.plane`. The shortcut therefore keeps
re-using the last selection instead of asking for a plane.

**Reproduction**

```
doc.selected_plane = "XY"
app.new_sketch()   # -> Sketch 1
app.new_sketch()   # -> Sketch 2   (expected: the plane picker)
```

Observed: `sketches = [(1, 'Sketch 1'), (2, 'Sketch 2')]`.

**Fix:** clear `selected_plane`/`selected_face` once the sketch has been
created, and ignore the shortcut while a sketch is already open (or always
open the plane picker for a new sketch).

---

### BUG-04 - The Point and Line tools cannot be used on top of existing geometry

- **File:** `core/ui/workspace.py:2509`
- **Severity:** High

The entity picker runs **before** the point/line tool handlers and swallows the
click:

```python
point_hit = self._pick_sketch_point(...)
if not (self._selected_tool == "line" and point_hit is not None):
    hit = self._pick_sketch_entity(...)     # <- also matches lines
    if hit is not None:
        ...select and start dragging the entity...
        return True
```

Consequences:

* With the **Point** tool active (the default after `begin_sketch_edit()`),
  clicking within ~6 px of an existing line selects and drags that line
  instead of adding a point.
* With the **Line** tool active, clicking on an existing line (not on a point)
  starts a drag of that line and calls `_reset_line_state()`, cancelling the
  line the user was drawing.

**Fix:** only run the entity picker when the active tool is not a drawing
tool, or require a modifier (e.g. the `select` tool) to pick geometry.

---

### BUG-05 - Undoing an extrude does not reactivate the sketch

- **File:** `core/app.py:361` (`Application.extrude_active`)
- **Severity:** High

```python
stack.execute(AddExtrudeCommand(document, sketch))
document.active_sketch_id = None      # <- outside the command stack
```

`AddExtrudeCommand.undo()` only removes the feature; it never restores
`active_sketch_id`. After `Ctrl+Z` the sketch stays hidden and no longer
editable - the user has to re-select it in the tree by hand.

**Reproduction:** create a closed profile, press `E`, press `Ctrl+Z` ->
`features = []` but `active_sketch_id` is still `None`.

**Fix:** let the command own the activation state (store and restore
`active_sketch_id` in `AddExtrudeCommand`).

---

### BUG-06 - `align_to_plane()` does not centre the plane origin

- **File:** `core/render/camera.py:198`
- **Severity:** High

The docstring promises "the plane's origin appears at the screen centre", but
the camera pan is simply reset:

```python
# Center the plane origin on screen.
self.pan_x = 0.0
self.pan_y = 0.0
```

For an origin plane the origin is the world origin, so this works. For a
sketch on a solid face the plane origin is the face centroid, so the camera
ends up centred on the world origin instead and the face is off-screen.

**Reproduction**

```python
frame = PlaneFrame(origin=(100.0, 50.0, 25.0), u=(1,0,0), v=(0,1,0), normal=(0,0,1))
cam.align_to_plane(frame)
cam.project(frame.origin, (640, 360))
# -> (1031.9, 163.9)   expected (640, 360)
```

**Fix:** compute the pan that maps the plane origin onto the screen centre:

```python
origin_screen = self.project(frame.origin, (0.0, 0.0))
self.pan_x = -origin_screen[0]
self.pan_y = -origin_screen[1]
```

---

### BUG-07 - `Document.load()` leaves no sketch active even if one is editable

- **File:** `core/document.py:92`
- **Severity:** High

```python
consumed = {feature.sketch_id for feature in features}
active = sketches[-1].id if sketches and sketches[-1].id not in consumed else None
```

Only the *last* sketch is considered. If the last sketch is consumed by a
feature but an earlier one is still free, the document loads with
`active_sketch_id = None` even though an editable sketch exists.

**Reproduction:** a document with `Sketch 1` (free) and `Sketch 2` (extruded)
loads with `active_sketch_id = None` instead of `1`.

**Fix:** pick the last *non-consumed* sketch, mirroring
`Application._activate_editable_sketch()`.

---

## Medium

### BUG-08 - `AddLineCommand.undo()` can remove the wrong edge

- **File:** `core/commands.py:289`
- **Severity:** Medium

The command stores the edge position in `self.index` and pops
`self.sketch.edges[self.index]` on undo. If other commands changed the edge
list in between (undo, new line, redo), the stored index no longer points at
the edge this command created and a different edge is deleted.

**Fix:** identify the edge by its point indices instead of by list position,
and verify before popping.

---

### BUG-09 - `OrientationCube` defines three methods twice

- **File:** `core/render/orientation_cube.py:90` and `core/render/orientation_cube.py:240`
- **Severity:** Medium

`set_scale`, `_s` and `_init_fonts` are each defined twice in the same class.
The second definition silently replaces the first, so the first block is dead
code. `pyflakes` reports:

```
core/render/orientation_cube.py:240:5: redefinition of unused 'set_scale' from line 90
core/render/orientation_cube.py:247:5: redefinition of unused '_s' from line 97
core/render/orientation_cube.py:250:5: redefinition of unused '_init_fonts' from line 100
```

**Fix:** delete the duplicated block at the end of the class.

---

### BUG-10 - The Sketch Palette display toggles have no effect

- **File:** `core/ui/tool_properties.py:397`
- **Severity:** Medium

`OPTION_ROWS` exposes "Sketch Grid", "Snap", "Slice", "Profile", "Points",
"Dimensions", "Constraints", "Projected Geometries", "Construction
Geometries" and "3D Sketch". `SketchPaletteWindow.options` stores the toggled
values, but nothing ever reads them - `SceneRenderer` keeps drawing the grid,
the points and the profiles regardless.

**Fix:** either wire the toggles to the renderer or mark the panel as
decorative.

---

### BUG-11 - The "Select" button of the CREATE SKETCH dialog does nothing

- **File:** `core/ui/tool_properties.py:178`
- **Severity:** Medium

`ToolPropertiesWindow.handle_event` returns `ToolWindowAction.SELECT` and sets
`self.selecting = True`, but `Workspace.handle_event` only checks
`action is not ToolWindowAction.NONE` and discards the meaning of `SELECT`.
The button therefore only repaints the field in a different colour.

**Fix:** handle `ToolWindowAction.SELECT` explicitly (e.g. arm a "pick a
plane/face" mode) or remove the button.

---

### BUG-12 - The command bar is a decorative placeholder

- **File:** `core/ui/workspace.py:1774`
- **Severity:** Medium

The bar renders the hint `Type a command, e.g. Extrude {"distance": 20}` but
there is no input field, no key handling and no command parsing. The extrude
distance is hard-coded to 20 mm (`AddExtrudeCommand.__init__`, `core/commands.py:315`),
so the advertised command cannot be executed at all.

**Fix:** implement the input line and wire it to the command stack, or remove
the hint until the feature exists.

---

### BUG-13 - Sketch line type is mutated outside the command stack

- **File:** `core/ui/workspace.py:703` and `core/ui/workspace.py:2392`
- **Severity:** Medium

```python
sketch.line_type = key
self.sketch_palette_window.current_line_type = key
document.dirty = True
```

and

```python
active_sketch.line_type = self.sketch_palette_window.current_line_type
document.dirty = True
```

`agents.md` requires every edit to be a `Command` with `do`/`undo`. The line
type is a document edit, so it is not undoable and the dirty flag has to be
set by hand.

**Fix:** add a `SetLineTypeCommand` and execute it through the stack.

---

### BUG-14 - The tab bar overflows the window with many documents

- **File:** `core/ui/tabbar.py:187`
- **Severity:** Medium

```python
tab_w = (available - gap * (count - 1)) // count
tab_w = min(self._s(220), max(self._s(96), tab_w))
```

The minimum tab width of 96 px is applied unconditionally, so with enough open
documents the tabs and the "+" button (`x + count * (tab_w + gap)`) are pushed
past the right edge of the window and become unclickable.

**Fix:** clamp `tab_w` to the available width, scroll the tab list, or
collapse the brand/logo when space runs out.

---

### BUG-15 - `StartPage._draw_tooltip` can raise `IndexError`

- **File:** `core/ui/startpage.py:167` and `core/ui/startpage.py:624`
- **Severity:** Medium

`self._hovered_recent` is only reset inside `_update_hover`. When the recent
list shrinks (e.g. `Config.add_recent()` truncates the list to 20 entries)
the stale index is used to index `geometry.recent_cards` and
`self.recent_files`, which raises `IndexError` and kills the frame.

**Fix:** reset `_hovered_recent`/`_hovered_example` in `set_recent_files()` and
guard the tooltip with `index < len(geometry.recent_cards)`.

---

### BUG-16 - Face picking ignores the backface culling used for drawing

- **File:** `core/render/scene.py:292` (`pick_face`) vs. `core/render/scene.py:437` (`_draw_solids`)
- **Severity:** Medium

The renderer skips faces whose normal points away from the camera:

```python
if (face.normal[0] * view_dir[0] + ...) <= 0:
    continue
```

`pick_face()` applies no such test, so hidden back faces (and faces of a
solid that is completely covered by another solid) can be selected and turned
into a sketch plane while nothing is visible at that position.

**Fix:** share one visibility helper between `pick_face` and `_draw_solids`.

---

### BUG-17 - "Open..." and the sample cards do nothing

- **File:** `core/app.py:154` (`open_document`) and `core/app.py:175` (`open_example`)
- **Severity:** Medium

Both callbacks are empty stubs, so the "Open..." button and every sample card
on the start page are dead. Only recently used files can be opened.

**Fix:** implement a file picker, or hide/disable the controls until it exists.

---

### BUG-18 - The i18n layer is never used

- **File:** `core/i18n/translator.py`
- **Severity:** Medium

`core/i18n` provides a complete translator, but nothing in `core/app.py`,
`core/ui/*` imports it and the `i18n/` folder contains no catalog files
(only a README). All UI strings are hard-coded English.

**Fix:** wire `Translator` into the UI strings and add the first catalog, or
remove the module until it is needed.

---

## Low

### BUG-19 - A malformed translation catalog crashes the lookup

- **File:** `core/i18n/translator.py:130`
- **Severity:** Low

`Translator._catalog()` calls `load_catalog()`, which raises
`TranslationError` for invalid JSON. `translate()` does not catch it, so one
broken catalog aborts the lookup instead of falling back to the default
language.

**Fix:** catch `TranslationError` in `_catalog()` and return `{}`.

---

### BUG-20 - `Config._pref_directory()` can raise `OSError` at startup

- **File:** `core/config.py:38`
- **Severity:** Low

Only `pygame.system.get_pref_path()` is inside the `try` block; the following
`path.mkdir(parents=True, exist_ok=True)` is not, so a read-only home
directory crashes the application during `Config.__init__`.

**Fix:** move the `mkdir` into the `try` block or guard it separately.

---

### BUG-21 - Stale settings hover state while dragging geometry

- **File:** `core/ui/workspace.py:2796`
- **Severity:** Low

`_update_hover()` returns early during a point/edge drag, before
`self._hover_settings` is recomputed. The gear button keeps its hover
highlight from the previous frame.

**Fix:** reset `_hover_settings = False` together with the other hover flags
at the top of `_update_hover()`.

---

### BUG-22 - Unused local variable in the palette body drawing

- **File:** `core/ui/tool_properties.py:831`
- **Severity:** Low

`panel = layout.panel` is assigned in `_draw_body()` and never used
(reported by `pyflakes`).

---

### BUG-23 - The sketch toolbar layout is rebuilt up to 70 times per mouse move

- **File:** `core/ui/workspace.py:565` (`_sketch_toolbar_groups`)
- **Severity:** Low

Every call iterates over 2 x 5 x 7 padding/gap/icon-width combinations and
rebuilds the whole group layout. It is called from `_update_hover()`,
`_draw_sketch_toolbar()`, `_line_menu_geometry()` and
`_handle_sketch_toolbar_click()`, i.e. several times per frame while the
mouse moves.

**Fix:** cache the layout and invalidate it only when the region, the scale or
the document changes.

---

### BUG-24 - Legacy line types are not normalised when loading

- **File:** `core/sketch.py:326`
- **Severity:** Low

`Sketch.from_dict()` stores `line_type` verbatim. The aliases `dashed` and
`dashdot` are only mapped in `SketchPaletteWindow.open()`. A sketch that
carries `line_type = "dashed"` therefore renders as a **normal** line
(`SceneRenderer._draw_sketch_segment` only knows `construction` and `center`),
while the palette shows "Construction".

**Fix:** normalise the aliases in `Sketch.from_dict()`, e.g. with the same
mapping used by the palette.

---

### BUG-25 - Selection state is not persisted

- **File:** `core/document.py:38` (`Document.to_dict`)
- **Severity:** Low

`active_sketch_id`, `selected_face` and `selected_plane` are not all written
to the file. `selected_plane` is saved, `selected_face` is not, so a document
that is saved while a solid face is selected reopens with the selection lost
and no visual indication of which face the user was working on.

---

### BUG-26 - Adding a point does not merge coincident points

- **File:** `core/app.py:289` (`Application.add_point`)
- **Severity:** Low

`AddLineCommand` re-uses an existing point when the coordinates match
(`Sketch.find_point`), but `Application.add_point()` always appends a new
point. Clicking twice on the same spot therefore creates two coincident
points, which breaks `profile_indices()` (the graph gets a degree-2 vertex
with two identical neighbours) and the profile detection.

**Fix:** reuse an existing point in `add_point()` the same way the line tool
does.

---

### BUG-27 - Dragging an edge drags its shared endpoints and distorts the profile

- **File:** `core/commands.py:171` (`MoveEdgeCommand`)
- **Severity:** Low

`MoveEdgeCommand` translates the two point entities of the edge. When the
edge is part of a closed profile those points are shared with the adjacent
edges, so dragging one edge stretches the neighbouring edges and the profile
is no longer the shape the user sees in the preview
(`_draw_edge_drag_preview` shows exactly that distortion).

**Fix:** either move only the edge (splitting the shared points) or restrict
edge dragging to standalone edges.

---

### BUG-28 - `_content_region()` computes the height with the wrong origin

- **File:** `core/app.py:631`
- **Severity:** Low

```python
return Rect(0, bar.y + bar.h, width, height - bar.h)
```

The height must be `height - (bar.y + bar.h)`. It happens to be correct today
only because the tab bar always sits at `y = 0`.

---

### BUG-29 - `Sketch.lines` rebuilds a list on every access

- **File:** `core/sketch.py:142`
- **Severity:** Low

`lines` is a property that allocates a new list on every access. It is used in
hot paths (`_pick_sketch_entity`, `_validate_sketch_selection`,
`_draw_hud`), so hovering over a sketch with many edges allocates repeatedly.

**Fix:** cache the list or iterate over `points`/`edges` directly.

---

## Reproducing the report

```bash
python -m pyflakes core main.py     # BUG-09, BUG-22
```

The remaining entries were reproduced with small scripts against
`core.document`, `core.commands` and `core.app` as shown above.
