"""Colour schemes and the xterm 256-colour palette."""

from __future__ import annotations

from dataclasses import dataclass

ANSI_16 = [
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
]


def palette_256() -> list[tuple[int, int, int]]:
    pal = list(ANSI_16)
    steps = [0, 95, 135, 175, 215, 255]
    pal += [(steps[r], steps[g], steps[b]) for r in range(6) for g in range(6) for b in range(6)]
    pal += [(8 + 10 * i,) * 3 for i in range(24)]
    return pal


@dataclass(frozen=True)
class Scheme:
    name: str
    fg: tuple[int, int, int]
    bg: tuple[int, int, int]
    bold: tuple[int, int, int] | None = None
    cursor: tuple[int, int, int] = (0, 200, 0)


SCHEMES = {s.name: s for s in (
    Scheme("classic", (229, 229, 229), (0, 0, 0), (255, 255, 255)),
    Scheme("white", (0, 0, 0), (255, 255, 255), cursor=(0, 0, 160)),
    Scheme("green", (51, 255, 102), (0, 20, 0), (160, 255, 180), (51, 255, 102)),
    Scheme("amber", (255, 176, 0), (20, 10, 0), (255, 210, 100), (255, 176, 0)),
    Scheme("blue", (255, 255, 255), (0, 0, 128), cursor=(255, 255, 0)),
)}
