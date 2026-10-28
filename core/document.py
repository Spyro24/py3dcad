"""Document model for PY3DCAD."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sketch import Extrude, Sketch, normalize_plane


def _update_refs(
    references: List[Tuple[int, int]],
    reference: Tuple[int, int],
    additive: bool,
) -> List[Tuple[int, int]]:
    """Return the selection after a click, toggling when it is additive."""
    if not additive:
        return [reference]
    if reference in references:
        return [item for item in references if item != reference]
    return [*references, reference]


@dataclass
class Document:
    """An editable in-memory document; saving is optional and never required."""

    id: int
    name: str = "Untitled"
    path: Optional[str] = None
    sketches: List[Sketch] = field(default_factory=list)
    features: List[Extrude] = field(default_factory=list)
    dirty: bool = False
    next_id: int = 1
    active_sketch_id: Optional[int] = None
    selected_plane: Optional[str] = None
    # The full multi-selection.  ``selected_face``/``selected_edge`` expose
    # the primary (most recently added) reference for single-target tools.
    selected_faces: List[Tuple[int, int]] = field(default_factory=list)
    selected_edges: List[Tuple[int, int]] = field(default_factory=list)

    @property
    def saved(self) -> bool:
        return self.path is not None

    @property
    def selected_face(self) -> Optional[Tuple[int, int]]:
        """Return the most recently selected face, if any."""
        return self.selected_faces[-1] if self.selected_faces else None

    @selected_face.setter
    def selected_face(self, reference: Optional[Tuple[int, int]]) -> None:
        self.selected_faces = [] if reference is None else [reference]

    @property
    def selected_edge(self) -> Optional[Tuple[int, int]]:
        """Return the most recently selected edge, if any."""
        return self.selected_edges[-1] if self.selected_edges else None

    @selected_edge.setter
    def selected_edge(self, reference: Optional[Tuple[int, int]]) -> None:
        self.selected_edges = [] if reference is None else [reference]

    def select_face(
        self, reference: Tuple[int, int], additive: bool = False
    ) -> None:
        """Select a solid face, optionally adding to the current selection."""
        self.selected_faces = _update_refs(
            self.selected_faces, reference, additive
        )
        self.selected_edges = []
        self.selected_plane = None
        self.active_sketch_id = None

    def select_edge(
        self, reference: Tuple[int, int], additive: bool = False
    ) -> None:
        """Select a solid edge, optionally adding to the current selection."""
        self.selected_edges = _update_refs(
            self.selected_edges, reference, additive
        )
        self.selected_faces = []
        self.selected_plane = None
        self.active_sketch_id = None

    def clear_selection(self) -> None:
        """Drop every viewport selection."""
        self.selected_faces = []
        self.selected_edges = []
        self.selected_plane = None

    def new_id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def sketch(self, sketch_id: Optional[int]) -> Optional[Sketch]:
        return next((s for s in self.sketches if s.id == sketch_id), None)

    def refresh_projections(self) -> None:
        """Move projected sketch geometry to its current solid sources."""
        from .projection import refresh_document_projections

        refresh_document_projections(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "selected_plane": (
                normalize_plane(self.selected_plane)
                if self.selected_plane is not None else None
            ),
            "sketches": [sketch.to_dict() for sketch in self.sketches],
            "features": [feature.to_dict() for feature in self.features],
        }

    def save(self, path: str) -> None:
        """Write the document as versioned JSON and adopt the file's name."""
        self.refresh_projections()
        target = Path(path).expanduser()
        if target.suffix.lower() != ".py3dcad":
            target = target.with_suffix(".py3dcad")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": 1, "name": target.stem, **self.to_dict()}
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.path = str(target)
        self.name = target.stem
        self.dirty = False

    @classmethod
    def load(cls, doc_id: int, path: str) -> "Document":
        """Load a document from a JSON file."""
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("format") != 1:
            raise ValueError(f"Unsupported document format: {payload.get('format')!r}")

        sketches: List[Sketch] = []
        for entry in payload.get("sketches", []):
            if isinstance(entry, dict):
                try:
                    sketches.append(Sketch.from_dict(entry))
                except (TypeError, ValueError):
                    continue

        features: List[Extrude] = []
        for entry in payload.get("features", []):
            if not isinstance(entry, dict) or entry.get("type") != "extrude":
                continue
            try:
                features.append(Extrude.from_dict(entry))
            except (TypeError, ValueError):
                continue

        highest = max(
            [0]
            + [sketch.id for sketch in sketches]
            + [feature.id for feature in features]
        )
        consumed = {feature.sketch_id for feature in features}
        active = sketches[-1].id if sketches and sketches[-1].id not in consumed else None
        name = str(payload.get("name") or source.stem)
        return cls(
            id=doc_id,
            name=name,
            path=str(source),
            sketches=sketches,
            features=features,
            dirty=False,
            next_id=highest + 1,
            active_sketch_id=active,
            selected_plane=(
                normalize_plane(payload["selected_plane"])
                if payload.get("selected_plane") else None
            ),
        )
