"""Compatibility re-export for solid face generation.

Face geometry now lives in :mod:`core.faces` so the application model can
inspect faces without importing pygame.  Renderer code may continue to import
``prism_faces`` and ``Face`` from here.
"""

from ..faces import Color, Face, prism_faces

__all__ = ["Color", "Face", "prism_faces"]
