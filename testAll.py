"""Run every PY3DCAD test from the project root.

Usage::

    python3 testAll.py

Successful tests stay silent; only failures are printed, each with its reason.
The last line reports the pass/fail rate.  The process exits non-zero when any
test fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import harness  # noqa: E402
from tests.run_tests import collect_tests  # noqa: E402


def main() -> int:
    """Run the whole suite and print the final pass/fail rate."""
    passed, failed = harness.run_tests(collect_tests())
    total = passed + failed
    pass_rate = (passed / total * 100.0) if total else 0.0
    fail_rate = (failed / total * 100.0) if total else 0.0
    print(
        f"passed {passed}, failed {failed} of {total} "
        f"-> pass rate {pass_rate:.1f}%, fail rate {fail_rate:.1f}%"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
