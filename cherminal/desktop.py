"""The desktop menu entry (cherminal.desktop) and its icons.

Desktops find an application's name and icon through its .desktop file.
A pip install doesn't add one, so ``cherminal --install-desktop`` writes it
and the logo into the user's own folders under ~/.local/share, together with
a MIME type for TinyTERM's ``.tpx`` session files so that double-clicking
one opens it in Cherminal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

APP_ID = "cherminal"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
TPX_MIME = "application/x-tinyterm-session"
MIME_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="{TPX_MIME}">
    <comment>TinyTERM session</comment>
    <sub-class-of type="text/plain"/>
    <glob pattern="*.tpx"/>
    <magic priority="60">
      <match type="string" offset="0" value="[TERM.emu]"/>
      <match type="string" offset="0" value="[term.emu]"/>
    </magic>
  </mime-type>
</mime-info>
"""


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def data_dirs() -> list[Path]:
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [data_home()] + [Path(d) for d in dirs.split(os.pathsep) if d]


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
        f"Exec={_exec_path()} %F\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=System;TerminalEmulator;\n"
        f"MimeType={TPX_MIME};\n"
        f"StartupWMClass={APP_ID}\n")
    mime = share / "mime" / "packages" / f"{APP_ID}.xml"
    mime.parent.mkdir(parents=True, exist_ok=True)
    mime.write_text(MIME_XML)
    # Refresh the desktop's caches when the tools are there; without them the
    # files still take effect at the next login on most desktops.
    for cmd in (["update-mime-database", str(share / "mime")],
                ["update-desktop-database", str(entry.parent)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False, capture_output=True)
    return entry
