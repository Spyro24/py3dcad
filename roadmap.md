# Roadmap - PY3DCAD (Python + pygame-ce)

## Workspaces
[ ] Design
[ ] Animation
[ ] Rendering
[ ] Prototyping (3dprint)
[ ] CAM

## Tools
workspaces/design/sketch/create
[x] Point
[x] Line
[ ] Midpoint Line
[ ] Poly line
[x] 2 Point Rectangle
[ ] Center Rectangle
[ ] 3 Point Rectangle
[ ] Rounded Rectangle
[x] Center Diameter Circle
[ ] 2 Point Circle
[ ] 3 Point Circle
[ ] 2 Tangent Circle
[ ] 3 Tangent Circle
workspaces/design/sketch/constrain
[x] Sketch Dimension
[x] Horizontal/Vertical
[x] Coincident
[ ] Tangent
[ ] Equal
[ ] Parallel
[ ] Perpendicular
[ ] Fix/UnFix
[ ] Midpoint
[ ] Concentric
[ ] Colliniear
[ ] Symmetry
[ ] Autoconstrain
workspaces/design/solid
[x] Create Sketch2d
[x] Extrude
[x] Fillet
[ ] Champfer

## M1 - Foundation
- Window, main loop, event handling
- 2D viewport with pan and zoom
- Basic side panel

## M2 - Model and Parameters
- Named parameters with units
- Feature tree with dependencies
- Recompute on change (topological order, dirty flags)
- Undo/redo via commands

## M3 - Sketching
- Lines, circles, rectangles
- Basic constraints (fixed, distance)
- Sketch edits driven by parameters

## M4 - Features
- Extrude a sketch into a solid
- Hole feature
- Edit a feature's parameters and see the result update

## M5 - 3D View
- Projection of triangles into pygame
- Wireframe view
- Simple shaded view with rotation
- Replace the temporary viewport renderer with a native PyOpenGL pipeline:
  tessellate concave faces and holes, use depth buffering, and render
  selection, outlines, sketches, and previews without pygame framebuffer
  compositing. Validate it against complex saved-model regression cases.

## M6 - Files and Export
- Save and load as versioned JSON
- Export to SVG (2D) and STL (3D)

## M7 - Polish
- Parameter expressions (AST whitelist)
- Keyboard shortcuts
- Error messages in the UI
