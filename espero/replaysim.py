"""#62: replaysim (research/PREREGISTRATION_REPLAYSIM.md).

The frozen rule and its criteria, pure: arrays in, numbers out, no I/O. research/replaysim.py fetches
and prints.
"""
from __future__ import annotations

HURDLE_BPS = 18.0   # replace with the measured round trip from espero.costs before the first run


def rule():
    """The registered rule. Written after the pre-registration is committed, never the other way."""
    raise NotImplementedError("#62: write the rule after committing its pre-registration")
