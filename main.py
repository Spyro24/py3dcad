"""Main entry point for PY3DCAD."""

import sys

from core.app import Application
from core.ui import Window

APP_NAME = "PY3DCAD"


def main() -> int:
    """Create the window and run the application."""
    window = Window(title=APP_NAME, size=(1280, 720))
    window.create()
    Application(window).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
