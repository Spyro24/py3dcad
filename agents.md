# AGENTS.md - PY3DCAD (Python + pygame-ce)

## Goal
PY3DCAD: sketches and features driven by named parameters. UI in pygame-ce only.

## Stack
- Python 3.11+, `pygame-ce` (`import pygame`). No Qt/Tk. Numpy only if approved.

## Rules
- Model logic must not import pygame. UI reads the model and sends commands.
- Every edit is a Command with do/undo. Undo/redo via stacks.
- Feature = `{id, type, params, deps}`. Recompute in topological order, dirty flags only.
- Params: named floats with units. Expressions via AST whitelist, never `eval`.
- World units: mm, Y up. Screen transform is isolated in one place.
- 3D = project triangles to 2D and draw with pygame; no 3D libs.
- Type hints on public functions. Functions under ~40 lines. No global state.
- Save format: JSON with `"format": 1`.
- The objects are Volumetric objects, the rendered mesh of them has to be water thight
- calculations have to be effiecient
- use semantic commits

## Workflow
- Run: `python main.py`
- Run all tests: `python3 testAll.py`
- A commit may only happen when all tests pass (`python3 testAll.py` reports `failed 0`).
- Done = app runs without errors and the change works as described.
- commit your changes as the system user before a new feature is requested

## Don'ts
- No new dependencies without asking.
- Don't touch unrelated files.
- Don't dump large files or outputs into the chat.
