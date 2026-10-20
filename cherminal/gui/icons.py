"""The Cherminal logo: the window and taskbar icon, and the About box."""

from __future__ import annotations

from importlib.resources import files

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap

RESOURCES = files("cherminal") / "resources"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addFile(str(RESOURCES / f"cherminal-{size}.png"), QSize(size, size))
    return icon


def logo(dark: bool, width: int = 360) -> QPixmap:
    """The icon with the name beside it, for a light or dark background."""
    name = "cherminal-logo-dark.png" if dark else "cherminal-logo-light.png"
    pix = QPixmap(str(RESOURCES / name))
    return pix.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
