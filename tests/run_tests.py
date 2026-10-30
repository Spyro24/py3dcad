"""Run the PY3DCAD test suite.

Usage::

    python3 tests/run_tests.py

Every module named ``test_*.py`` in this package is imported and each
``test_*`` function is run.  Failures are printed as they happen; the final
line reports how many tests passed and failed.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests  # noqa: E402
from tests import harness  # noqa: E402


def _collect_tests() -> List[harness.Test]:
    """Import every ``test_*`` module and collect its test functions."""
    collected: List[harness.Test] = []
    seen: set = set()
    for module_info in pkgutil.iter_modules(tests.__path__):
        if not module_info.name.startswith("test_"):
            continue
        module = importlib.import_module(f"tests.{module_info.name}")
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            candidate = getattr(module, name)
            if callable(candidate) and candidate not in seen:
                seen.add(candidate)
                collected.append(candidate)
    return collected


def main() -> int:
    """Run all discovered tests and return a process exit code."""
    passed, failed = harness.run_tests(_collect_tests())
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
