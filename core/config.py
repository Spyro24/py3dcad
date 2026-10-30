"""Application configuration stored in the user's preference folder."""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pygame


def format_opened(timestamp: float) -> str:
    """Format a timestamp as a short relative time label."""
    delta = max(0.0, time.time() - timestamp)
    if delta < 60:
        return "Opened just now"
    if delta < 3600:
        return f"Opened {int(delta // 60)} min ago"
    if delta < 86400:
        hours = int(delta // 3600)
        return f"Opened {hours} hour{'s' if hours != 1 else ''} ago"
    if delta < 7 * 86400:
        days = int(delta // 86400)
        return f"Opened {days} day{'s' if days != 1 else ''} ago"
    return "Opened " + time.strftime("%Y-%m-%d", time.localtime(timestamp))


class Config:
    """Loads and saves PY3DCAD preferences and the recent file list."""

    def __init__(self, author: str = "spyro24", app: str = "py3dcad") -> None:
        self.directory = self._pref_directory(author, app)
        self.path = self.directory / "config.json"
        self.ui_scale: float = 1.0
        self.show_orientation_cube: bool = True
        self.use_opengl: bool = True
        self.recent: List[Dict[str, Any]] = []
        self.load()

    def _pref_directory(self, author: str, app: str) -> Path:
        try:
            path = Path(pygame.system.get_pref_path(author, app))
        except Exception:
            path = Path.home() / f".{app}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        try:
            self.ui_scale = float(data.get("ui_scale", 1.0))
        except (TypeError, ValueError):
            self.ui_scale = 1.0
        value = data.get("show_orientation_cube", True)
        self.show_orientation_cube = value if isinstance(value, bool) else True
        value = data.get("use_opengl", True)
        self.use_opengl = value if isinstance(value, bool) else True
        entries = data.get("recent", [])
        if isinstance(entries, list):
            self.recent = [entry for entry in entries if isinstance(entry, dict)]

    def save(self) -> None:
        data = {
            "format": 1,
            "ui_scale": self.ui_scale,
            "show_orientation_cube": self.show_orientation_cube,
            "use_opengl": self.use_opengl,
            "recent": self.recent[:20],
        }
        try:
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def add_recent(self, name: str, path: str) -> None:
        self.recent = [entry for entry in self.recent if entry.get("path") != path]
        self.recent.insert(0, {"name": name, "path": path, "opened_at": time.time()})
        self.recent = self.recent[:20]
        self.save()

    def recent_entries(self) -> List[Dict[str, Any]]:
        return list(self.recent)
