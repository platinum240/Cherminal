"""Clickable key names on block-mode screens (3270 hotspots).

Mainframe panels list their keys as text: ``PF3=Exit``, ``F12 = Cancel``,
``PA1``, ``Press ENTER``. :func:`find_hotspots` finds those in one screen
line and names the attention key each one stands for, so a click can press
it. Kept free of Qt so it can be tested on sample screens and shared by
other block-mode emulations: names come back as ``enter``, ``clear``,
``pf1``-``pf24`` and ``pa1``-``pa3``, the 3270 action names; ``F3=Exit``
(the 5250 and CUA spelling) is ``pf3`` too.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Hotspot(NamedTuple):
    start: int          # first column
    end: int            # one past the last column
    action: str         # e.g. "pf3"


# PF3=Exit, PF3 = Exit, F3=Exit, PF03 ==> Exit (the label is one word).
# A bare "PF3" counts too, but a bare "F3" does not: too many other things
# (hex, field names, F1 the help key in prose) look like it.
_KEY = re.compile(
    r"(?<![\w$#@])(?:"
    r"(?P<pf>PF|F)(?P<n>\d{1,2})(?: *(?P<eq>=+>?) *[^\s=,;]+)?"
    r"|PA(?P<pa>[1-3])(?: *=+>? *[^\s=,;]+)?"
    r"|(?P<word>ENTER|CLEAR)(?: *=+>? *[^\s=,;]+)?"
    r")(?![\w$#@])")


def find_hotspots(line: str) -> list[Hotspot]:
    """Hotspots in one line of screen text, left to right."""
    found = []
    for m in _KEY.finditer(line):
        if m.group("pf"):
            n = int(m.group("n"))
            if not 1 <= n <= 24:
                continue
            if m.group("pf") == "F" and not m.group("eq"):
                continue
            action = f"pf{n}"
        elif m.group("pa"):
            action = f"pa{m.group('pa')}"
        else:
            action = m.group("word").lower()
        found.append(Hotspot(m.start(), m.end(), action))
    return found


def hotspot_at(line: str, col: int) -> Hotspot | None:
    """The hotspot covering column ``col`` of ``line``, if any."""
    for spot in find_hotspots(line):
        if spot.start <= col < spot.end:
            return spot
    return None
