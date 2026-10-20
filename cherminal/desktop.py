"""The desktop menu entry (cherminal.desktop) and its icons.

Desktops find an application's name and icon through its .desktop file.
A pip install doesn't add one, so ``cherminal --install-desktop`` writes it
and the logo into the user's own folders under ~/.local/share.
"""

from __future__ import annotations

import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path

APP_ID = "cherminal"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def data_dirs() -> list[Path]:
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [data_home()] + [Path(d) for d in dirs.split(":") if d]


def entry_installed() -> bool:
    """True when the desktop can find cherminal.desktop (menu entry installed)."""
    return any((d / "applications" / f"{APP_ID}.desktop").is_file() for d in data_dirs())


def _exec_path() -> str:
    path = os.environ.get("APPIMAGE") or shutil.which("cherminal") or os.path.abspath(sys.argv[0])
    return f'"{path}"' if " " in path else path


def install(share: Path | None = None) -> Path:
    """Write the menu entry and icons; returns the .desktop file's path."""
    share = share or data_home()
    res = files("cherminal") / "resources"
    for size in ICON_SIZES:
        dest = share / f"icons/hicolor/{size}x{size}/apps/{APP_ID}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((res / f"cherminal-{size}.png").read_bytes())
    svg = share / f"icons/hicolor/scalable/apps/{APP_ID}.svg"
    svg.parent.mkdir(parents=True, exist_ok=True)
    svg.write_bytes((res / "cherminal.svg").read_bytes())
    entry = share / "applications" / f"{APP_ID}.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Cherminal\n"
        "Comment=Terminal emulator for host connections\n"
        f"Exec={_exec_path()} %U\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=System;TerminalEmulator;\n"
        f"StartupWMClass={APP_ID}\n")
    return entry
