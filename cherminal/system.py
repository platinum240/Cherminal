"""Where things live on each operating system, and its defaults.

Linux follows the XDG folders (``~/.config``, ``~/.local/state``, ``/etc``).
macOS uses its own: ``~/Library/Application Support/Cherminal`` for sessions
and keymaps, ``~/Library/Logs/Cherminal`` for session logs and
``/Library/Application Support/Cherminal`` for what an administrator
deploys. The XDG environment variables still win on macOS when they are
set, so scripts and tests behave the same everywhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"

# Bundle identifier of the macOS app, and the name of its managed
# preferences (the domain a Jamf or other MDM configuration profile sets).
MAC_BUNDLE_ID = "io.github.platinum240.cherminal"
MAC_SITE_DIR = Path("/Library/Application Support/Cherminal")
MAC_MANAGED_PREFS = Path("/Library/Managed Preferences")

# "Monospace" is fontconfig's name for the default fixed-width font. macOS
# has no such alias, so session files keep saying "Monospace" (they move
# between Linux and Mac unchanged) and it is read as Menlo there.
GENERIC_MONO = "Monospace"
MAC_MONO = "Menlo"


def font_family(family: str) -> str:
    """The font to ask Qt for when a session names ``family``."""
    if IS_MAC and family in ("", GENERIC_MONO):
        return MAC_MONO
    return family or GENERIC_MONO


def config_dir() -> Path:
    """The user's own sessions, keymaps and known_hosts."""
    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]) / "cherminal"
    xdg = Path.home() / ".config" / "cherminal"
    if IS_MAC:
        mac = Path.home() / "Library" / "Application Support" / "Cherminal"
        # A ~/.config/cherminal copied over from Linux is used as it is,
        # until Cherminal has made its own folder.
        return xdg if xdg.is_dir() and not mac.exists() else mac
    return xdg


def log_dir() -> Path:
    """Where session logs go unless the site policy says otherwise."""
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"]) / "cherminal" / "logs"
    if IS_MAC:
        return Path.home() / "Library" / "Logs" / "Cherminal"
    return Path.home() / ".local" / "state" / "cherminal" / "logs"


def site_config_dirs() -> list[Path]:
    """The system's shared setup folders, after $CHERMINAL_SITE_DIR."""
    if IS_MAC and not os.environ.get("XDG_CONFIG_DIRS"):
        return [MAC_SITE_DIR]
    xdg = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    return [Path(d) / "cherminal" for d in xdg.split(":") if d]


def policy_path() -> Path:
    """The site policy file (TOML)."""
    return MAC_SITE_DIR / "policy.toml" if IS_MAC else Path("/etc/cherminal/policy.toml")


def managed_prefs_paths(user: str) -> list[Path]:
    """macOS managed preferences for Cherminal, computer-wide first then the
    user's own; later ones win. Empty on Linux."""
    if not IS_MAC:
        return []
    name = f"{MAC_BUNDLE_ID}.plist"
    return [MAC_MANAGED_PREFS / name, MAC_MANAGED_PREFS / user / name]
