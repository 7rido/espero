"""`approx(want)`: equal to a number within a tolerance, as pytest's `approx` reads, with no pytest needed.

The test suite runs under `unittest discover` (scripts/check.sh and CI), where a test written as a plain
function is never collected. The files converted from that style keep their `x == approx(y)` assertions
through this class, so they read as before and need nothing pytest installs.
"""
from __future__ import annotations

from typing import Any


class approx:  # noqa: N801 - reads as pytest.approx does
    def __init__(self, want: Any, rel: float = 1e-6, abs: float = 1e-12):  # noqa: A002 - pytest's keyword
        self.want, self.rel, self.abs = want, rel, abs

    def __eq__(self, got: Any) -> bool:
        w = float(self.want)
        return abs(float(got) - w) <= max(self.rel * abs(w), self.abs)

    def __ne__(self, got: Any) -> bool:
        return not self.__eq__(got)

    def __repr__(self) -> str:
        return f"approx({self.want!r} ± rel {self.rel}, abs {self.abs})"
