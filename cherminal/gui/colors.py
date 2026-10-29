"""Colour schemes and the xterm 256-colour palette."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import PALETTE_NAMES  # noqa: F401  (names for a session's [palette])

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


RGB = tuple[int, int, int]



@dataclass(frozen=True)
class Scheme:
    name: str
    fg: RGB
    bg: RGB
    bold: RGB | None = None
    cursor: RGB = (0, 200, 0)
    min_contrast: float = 1.0          # WCAG contrast ratio every colour is held to


SCHEMES = {s.name: s for s in (
    Scheme("classic", (229, 229, 229), (0, 0, 0), (255, 255, 255)),
    Scheme("white", (0, 0, 0), (255, 255, 255), cursor=(0, 0, 160)),
    Scheme("green", (51, 255, 102), (0, 20, 0), (160, 255, 180), (51, 255, 102)),
    Scheme("amber", (255, 176, 0), (20, 10, 0), (255, 210, 100), (255, 176, 0)),
    Scheme("blue", (255, 255, 255), (0, 0, 128), cursor=(255, 255, 0)),
    # High contrast: WCAG AAA (7:1) is enforced for every colour the host uses.
    Scheme("high-contrast", (255, 255, 255), (0, 0, 0), (255, 255, 255), (255, 255, 0), 7.0),
    Scheme("high-contrast-light", (0, 0, 0), (255, 255, 255), (0, 0, 0), (0, 0, 200), 7.0),
    Scheme("yellow-on-black", (255, 255, 0), (0, 0, 0), (255, 255, 160), (255, 255, 255), 7.0),
    Scheme("black-on-yellow", (0, 0, 0), (255, 255, 160), (0, 0, 0), (0, 0, 200), 7.0),
    # Modern view's themes: softer than black and white, with every host
    # colour held to WCAG AA so red still reads as red on either.
    Scheme("graphite", (226, 228, 233), (35, 38, 45), (255, 255, 255), (110, 160, 255), 4.5),
    Scheme("paper", (32, 35, 43), (250, 250, 248), (0, 0, 0), (47, 107, 216), 4.5),
)}


def parse_hex(value: str) -> RGB:
    """``#rrggbb`` -> (r, g, b); raises ValueError."""
    v = value.strip().lstrip("#")
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        raise ValueError(f"colour must look like #rrggbb, not {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def to_hex(rgb: RGB) -> str:
    return "#%02x%02x%02x" % rgb


def luminance(rgb: RGB) -> float:
    """WCAG 2 relative luminance."""
    def chan(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: RGB, b: RGB) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ensure_contrast(fg: RGB, bg: RGB, ratio: float) -> RGB:
    """Lighten or darken ``fg`` just enough to reach ``ratio`` against ``bg``.

    Keeps the colour's hue where it can, so red stays reddish, and goes all
    the way to white or black only when nothing in between is enough.
    """
    if ratio <= 1 or contrast(fg, bg) >= ratio:
        return fg
    best = None
    for target in ((255, 255, 255), (0, 0, 0)):
        for step in range(1, 21):
            t = step / 20
            mixed = tuple(round(f + (g - f) * t) for f, g in zip(fg, target))
            if contrast(mixed, bg) >= ratio:
                if best is None or step < best[0]:
                    best = (step, mixed)
                break
    if best:
        return best[1]
    white, black = (255, 255, 255), (0, 0, 0)
    return white if contrast(white, bg) >= contrast(black, bg) else black


@dataclass(frozen=True)
class Colors:
    """Everything the terminal paints with, after a session's own settings."""
    fg: RGB
    bg: RGB
    bold: RGB | None
    cursor: RGB
    palette: tuple[RGB, ...]
    min_contrast: float


def modern_scheme(theme: str, dark_desktop: bool) -> str | None:
    """The scheme Modern view paints with; None keeps the session's own."""
    if theme == "session":
        return None
    if theme == "auto":
        return "graphite" if dark_desktop else "paper"
    return theme


def resolve(profile) -> Colors:
    """The scheme, then the session's own colours, palette and contrast."""
    sch = SCHEMES.get(profile.color_scheme, SCHEMES["classic"])
    pal = palette_256()
    for name, value in profile.palette.items():
        pal[PALETTE_NAMES.index(name)] = parse_hex(value)
    fg = parse_hex(profile.fg_color) if profile.fg_color else sch.fg
    return Colors(
        fg=fg,
        bg=parse_hex(profile.bg_color) if profile.bg_color else sch.bg,
        bold=None if profile.fg_color else sch.bold,
        cursor=parse_hex(profile.cursor_color) if profile.cursor_color else sch.cursor,
        palette=tuple(pal),
        min_contrast=profile.min_contrast or sch.min_contrast,
    )
