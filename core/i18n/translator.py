"""Load and query JSON translation catalogs."""

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

DEFAULT_TRANSLATIONS_DIR = Path(__file__).resolve().parents[2] / "i18n"

PathLike = Union[str, Path]


class TranslationError(Exception):
    """Raised when a translation catalog cannot be read or parsed."""


class _SafeValues(dict):
    """Leave unknown placeholders in the text instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format(text: str, values: Mapping[str, Any]) -> str:
    try:
        return text.format_map(_SafeValues(values))
    except (IndexError, ValueError):
        return text


def _flatten(data: Mapping[str, Any], prefix: str = "") -> Dict[str, str]:
    catalog: Dict[str, str] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            catalog.update(_flatten(value, name))
        elif isinstance(value, str):
            catalog[name] = value
        else:
            raise TranslationError(
                f"Translation {name!r} must be a string, got {type(value).__name__}"
            )
    return catalog


def load_catalog(path: PathLike) -> Dict[str, str]:
    """Read one JSON catalog and flatten nested objects to dotted keys."""
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as error:
        raise TranslationError(f"Cannot read translation file {source}: {error}") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise TranslationError(f"Invalid JSON in {source}: {error}") from error
    if not isinstance(payload, dict):
        raise TranslationError(f"Translation file {source} must contain a JSON object")
    return _flatten(payload)


def available_languages(directory: Optional[PathLike] = None) -> List[str]:
    """Return the locale codes of all JSON files in a translation folder."""
    folder = Path(directory) if directory is not None else DEFAULT_TRANSLATIONS_DIR
    if not folder.is_dir():
        return []
    return sorted(
        path.stem
        for path in folder.glob("*.json")
        if path.is_file() and not path.name.startswith(".")
    )


class Translator:
    """Look up translated strings with fallback and placeholder support."""

    def __init__(
        self,
        directory: Optional[PathLike] = None,
        language: str = "en",
        fallback_language: str = "en",
    ) -> None:
        self.directory = (
            Path(directory) if directory is not None else DEFAULT_TRANSLATIONS_DIR
        )
        self.fallback_language = fallback_language
        self.language = (
            self.resolve_language(language)
            or self.resolve_language(fallback_language)
            or language
        )
        self._catalogs: Dict[str, Dict[str, str]] = {}

    def resolve_language(self, language: str) -> Optional[str]:
        """Find the catalog file for a locale such as ``de`` or ``de-DE``."""
        normalized = language.replace("-", "_").lower()
        candidates = [language, normalized, normalized.split("_")[0]]
        for candidate in candidates:
            if (self.directory / f"{candidate}.json").is_file():
                return candidate
        for path in self.directory.glob("*.json"):
            if path.is_file() and path.stem.lower() == normalized:
                return path.stem
        return None

    def available_languages(self) -> List[str]:
        return available_languages(self.directory)

    def set_language(self, language: str) -> bool:
        """Switch language; returns False when no matching catalog exists."""
        resolved = self.resolve_language(language)
        if resolved is None:
            return False
        self._catalog(resolved)
        self.language = resolved
        return True

    def reload(self) -> None:
        """Drop cached catalogs so edited JSON files are read again."""
        self._catalogs.clear()

    def translate(self, key: str, **values: Any) -> str:
        """Translate a dotted key, falling back to the default language."""
        text = self._catalog(self.language).get(key)
        if text is None and self.fallback_language:
            text = self._catalog(self.fallback_language).get(key)
        if text is None:
            return key
        return _format(text, values)

    def _catalog(self, language: str) -> Dict[str, str]:
        resolved = self.resolve_language(language)
        if resolved is None:
            return {}
        if resolved not in self._catalogs:
            self._catalogs[resolved] = load_catalog(self.directory / f"{resolved}.json")
        return self._catalogs[resolved]
