"""Cached mesh-edge keys shared by the software and OpenGL renderers.

Rounding every endpoint of a tessellated body on every frame is expensive, so
keys are built once per face and cached for as long as the face object lives.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from ..faces import Face

FaceEdgeKey = Tuple[Tuple[float, ...], Tuple[float, ...]]
FaceEdgeEntry = Optional[Tuple[FaceEdgeKey, bool]]


def edge_key(
    start: Sequence[float], end: Sequence[float]
) -> FaceEdgeKey:
    """Return a direction-independent key for one mesh edge."""
    first = tuple(round(value, 6) for value in start)
    second = tuple(round(value, 6) for value in end)
    return (first, second) if first <= second else (second, first)


class FaceEdgeCache:
    """Build and cache the mesh-edge keys of faces."""

    def __init__(self, limit: int = 4096) -> None:
        self._entries: Dict[int, Tuple[Face, List[FaceEdgeEntry]]] = {}
        self._limit = limit

    def edges(self, face: Face) -> List[FaceEdgeEntry]:
        """Return one rounded key per face edge, aligned with its vertices.

        Degenerate edges map to ``None``; the second element of each entry is
        ``True`` when the edge is a smooth tessellation seam.
        """
        cached = self._entries.get(id(face))
        if cached is not None and cached[0] is face:
            return cached[1]
        count = len(face.vertices)
        sharp = face.sharp_edges
        entries: List[FaceEdgeEntry] = []
        for index in range(count):
            start = face.vertices[index]
            end = face.vertices[(index + 1) % count]
            if start == end:
                entries.append(None)
                continue
            is_smooth = (
                sharp is not None
                and index < len(sharp)
                and not sharp[index]
            )
            entries.append((edge_key(start, end), is_smooth))
        if len(self._entries) >= self._limit:
            self._entries.clear()
        # Holding the face keeps its id unique for as long as the entry lives.
        self._entries[id(face)] = (face, entries)
        return entries
