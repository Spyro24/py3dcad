"""A tiny, dependency-free test harness for the PY3DCAD test suite.

Tests are plain functions that take no arguments.  A test passes by returning
normally: :data:`PASS_COUNT` grows by one and nothing is printed.  A test fails
by raising an exception, which is reported with the test name and the reason.

Typical use::

    from .harness import check

    def test_something() -> None:
        check(value == expected, "value did not match")
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Tuple

Test = Callable[[], None]

#: Number of tests that have passed in the current run.
PASS_COUNT = 0
#: Number of tests that have failed in the current run.
FAIL_COUNT = 0


class TestFailure(AssertionError):
    """Raised when a test's expectation is not met."""


def check(condition: bool, message: str) -> None:
    """Fail the running test with ``message`` unless ``condition`` holds."""
    if not condition:
        raise TestFailure(message)


def run_tests(tests: Iterable[Test]) -> Tuple[int, int]:
    """Run ``tests``, print every failure and return ``(passed, failed)``."""
    global PASS_COUNT, FAIL_COUNT
    PASS_COUNT = 0
    FAIL_COUNT = 0
    for test in tests:
        try:
            test()
        except Exception as error:  # noqa: BLE001 - report any failure
            FAIL_COUNT += 1
            print(f"FAILED: {test.__name__}: {error}")
        else:
            PASS_COUNT += 1
    return PASS_COUNT, FAIL_COUNT
