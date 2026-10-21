# Roadmap - PY3DCAD (Python + pygame-ce)

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

## M6 - Files and Export
- Save and load as versioned JSON
- Export to SVG (2D) and STL (3D)

## M7 - Polish
- Parameter expressions (AST whitelist)
- Keyboard shortcuts
- Error messages in the UI
