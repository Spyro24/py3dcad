"""Document model for PY3DCAD."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sketch import Extrude, Sketch, normalize_plane


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
    selected_face: Optional[Tuple[int, int]] = None

    @property
    def saved(self) -> bool:
        return self.path is not None

    def new_id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def sketch(self, sketch_id: Optional[int]) -> Optional[Sketch]:
        return next((s for s in self.sketches if s.id == sketch_id), None)

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
