"""Where things live on each operating system, and its defaults.

Linux follows the XDG folders (``~/.config``, ``~/.local/state``, ``/etc``).
macOS uses its own: ``~/Library/Application Support/Cherminal`` for sessions
and keymaps, ``~/Library/Logs/Cherminal`` for session logs and
``/Library/Application Support/Cherminal`` for what an administrator
deploys. Windows uses ``%APPDATA%\\Cherminal`` for sessions and keymaps,
``%LOCALAPPDATA%\\Cherminal\\Logs`` for session logs and
``%ProgramData%\\Cherminal`` for what an administrator deploys. The XDG
environment variables still win on macOS and Windows when they are set, so
scripts and tests behave the same everywhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# Bundle identifier of the macOS app, and the name of its managed
# preferences (the domain a Jamf or other MDM configuration profile sets).
MAC_BUNDLE_ID = "io.github.platinum240.cherminal"
MAC_SITE_DIR = Path("/Library/Application Support/Cherminal")
MAC_MANAGED_PREFS = Path("/Library/Managed Preferences")
# Windows groups the app's windows under one taskbar button by this ID; the
# installer's Start menu shortcut carries the same one.
WINDOWS_APP_ID = MAC_BUNDLE_ID

# "Monospace" is fontconfig's name for the default fixed-width font. macOS
# has no such alias, so session files keep saying "Monospace" (they move
# between Linux and Mac unchanged) and it is read as Menlo there.
GENERIC_MONO = "Monospace"
MAC_MONO = "Menlo"
WINDOWS_MONO = "Consolas"


def name() -> str:
    """The operating system's name, as users know it."""
    return "macOS" if IS_MAC else "Windows" if IS_WINDOWS else "Linux"


def font_family(family: str) -> str:
    """The font to ask Qt for when a session names ``family``."""
    if family in ("", GENERIC_MONO):
        if IS_MAC:
            return MAC_MONO
        if IS_WINDOWS:
            return WINDOWS_MONO
    return family or GENERIC_MONO


def _windows_folder(variable: str, fallback: str) -> Path:
    """A Windows known folder from its environment variable (%APPDATA% and
    the like), or where it normally is when the variable is missing."""
    value = os.environ.get(variable)
    return Path(value or fallback)


def program_data() -> Path:
    """%ProgramData% (normally C:\\ProgramData), asked of Windows itself: the
    environment variable is the user's to change, and the site policy must
    not move where a user points it."""
    if sys.platform == "win32":
        try:
            return Path(_known_folder("62AB5D82-FDC1-4DC3-A9DD-070D1D495D97"))
        except OSError:
            return Path(r"C:\ProgramData")
    return _windows_folder("ProgramData", r"C:\ProgramData")     # tests on other systems


def _known_folder(guid: str) -> str:
    """A Windows known folder's path (SHGetKnownFolderPath)."""
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(guid)
    folder = GUID(u.time_low, u.time_mid, u.time_hi_version,
                  (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    path = ctypes.c_wchar_p()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None,
                                                         ctypes.byref(path))
    try:
        if result != 0 or not path.value:
            raise OSError(f"SHGetKnownFolderPath failed ({result & 0xFFFFFFFF:#x})")
        return path.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)


def windows_site_dir() -> Path:
    """Where an administrator puts shared sessions, keymaps and the policy."""
    return program_data() / "Cherminal"


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
    if IS_WINDOWS:
        return _windows_folder("APPDATA", str(Path.home() / "AppData" / "Roaming")) / "Cherminal"
    return xdg


def log_dir() -> Path:
    """Where session logs go unless the site policy says otherwise."""
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"]) / "cherminal" / "logs"
    if IS_MAC:
        return Path.home() / "Library" / "Logs" / "Cherminal"
    if IS_WINDOWS:
        local = _windows_folder("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return local / "Cherminal" / "Logs"
    return Path.home() / ".local" / "state" / "cherminal" / "logs"


def site_config_dirs() -> list[Path]:
    """The system's shared setup folders, after $CHERMINAL_SITE_DIR."""
    if not os.environ.get("XDG_CONFIG_DIRS"):
        if IS_MAC:
            return [MAC_SITE_DIR]
        if IS_WINDOWS:
            return [windows_site_dir()]
    xdg = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    return [Path(d) / "cherminal" for d in xdg.split(os.pathsep) if d]


def policy_path() -> Path:
    """The site policy file (TOML)."""
    if IS_MAC:
        return MAC_SITE_DIR / "policy.toml"
    if IS_WINDOWS:
        return windows_site_dir() / "policy.toml"
    return Path("/etc/cherminal/policy.toml")


def system_known_hosts() -> Path:
    """The SSH host keys every user trusts (OpenSSH's system-wide file)."""
    if IS_WINDOWS:
        return program_data() / "ssh" / "ssh_known_hosts"
    return Path("/etc/ssh/ssh_known_hosts")


def default_serial_device() -> str:
    return "COM1" if IS_WINDOWS else "/dev/ttyUSB0"


def managed_prefs_paths(user: str) -> list[Path]:
    """macOS managed preferences for Cherminal, computer-wide first then the
    user's own; later ones win. Empty on Linux."""
    if not IS_MAC:
        return []
    name = f"{MAC_BUNDLE_ID}.plist"
    return [MAC_MANAGED_PREFS / name, MAC_MANAGED_PREFS / user / name]
