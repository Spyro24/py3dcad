"""Shared fixtures for the PY3DCAD test suite."""

from __future__ import annotations

from typing import Tuple

from core.commands import CommandStack
from core.document import Document
from core.sketch import Sketch


def new_sketch() -> Tuple[Document, Sketch, CommandStack]:
    """Return a document with one empty, active sketch and its command stack."""
    document = Document(id=1)
    sketch = Sketch(id=1, name="Sketch1")
    document.sketches.append(sketch)
    document.active_sketch_id = sketch.id
    return document, sketch, CommandStack()
