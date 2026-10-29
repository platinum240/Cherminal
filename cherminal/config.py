"""Saved session profiles and keymap files.

Everything lives under ``$XDG_CONFIG_HOME/cherminal`` (``~/.config/cherminal``;
``~/Library/Application Support/Cherminal`` on macOS, see ``system``):

* ``sessions/<slug>.toml`` - one profile per file
* ``keymaps/<name>.toml``  - reusable keymaps (``inherit`` + ``[keys]``)
* ``known_hosts``          - SSH host keys accepted from Cherminal
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w

from . import emulation, system
from .keymap import BUILTIN, Keymap

TRANSPORTS = ("ssh", "telnet", "serial", "local")
DEFAULT_PORTS = {"ssh": 22, "telnet": 23}
OPTION_KEYS = ("alt", "left-alt", "text")
VIEWS = ("", "classic", "modern")      # "" = what the site policy says (classic if nothing)
MODERN_THEMES = ("auto", "graphite", "paper", "session")


PALETTE_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
                 "bright-black", "bright-red", "bright-green", "bright-yellow",
                 "bright-blue", "bright-magenta", "bright-cyan", "bright-white"]


def _check_hex(value: str) -> None:
    v = value.lstrip("#")
    if not value.startswith("#") or len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        raise ValueError(f"colour must look like #rrggbb, not {value!r}")


def config_dir() -> Path:
    return system.config_dir()


def split_host_port(text: str) -> tuple[str, int]:
    """``mainframe.example.com:2323`` -> (host, 2323); port 0 when none is given.
    More than one colon is a bare IPv6 address, which has no port."""
    text = text.strip()
    host, sep, port = text.rpartition(":")
    if sep and host and ":" not in host and port.isdigit() and 0 < int(port) <= 65535:
        return host, int(port)
    return text, 0


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "session"


@dataclass
class SessionProfile:
    name: str = "New session"
    transport: str = "ssh"
    host: str = ""
    port: int = 0                     # 0 = transport default
    tls: bool = False                 # telnet: TLS (e.g. TN3270 on port 992)
    tls_verify: bool = True           # check the host's certificate
    device_name: str = ""             # TN5250: workstation device name (NEW-ENVIRON DEVNAME)
    lu_name: str = ""                 # 3270: TN3270E CONNECT to this LU (printer or display)
    username: str = ""
    identity_file: str = ""           # SSH private key
    ask_login: bool = False           # SSH: ask for user name and password on connect
    file_transfer: bool = False       # SSH: upload files dropped on the window (SFTP)
    upload_dir: str = ""              # SSH: where dropped files go; "" = home folder
    command: str = ""                 # local: program to run (default $SHELL)
    serial_device: str = "/dev/ttyUSB0"
    baud: int = 9600
    data_bits: int = 8
    parity: str = "none"              # none | even | odd | mark | space
    stop_bits: float = 1
    flow_control: str = "none"        # none | xonxoff | rtscts
    emulation: str = "vt220"
    encoding: str = ""                # "" = emulation default
    cols: int = 80
    rows: int = 24
    scrollback: int = 2000
    font_family: str = "Monospace"
    font_size: int = 11
    color_scheme: str = "classic"
    fg_color: str = ""                # "#rrggbb" text colour; "" = scheme's
    bg_color: str = ""                # "#rrggbb" background; "" = scheme's
    cursor_color: str = ""            # "#rrggbb" cursor; "" = scheme's
    min_contrast: float = 0           # WCAG ratio for all text (4.5 AA, 7 AAA); 0 = scheme's
    palette: dict[str, str] = field(default_factory=dict)   # e.g. blue = "#6fa8ff"
    keymap: str = ""                  # "" = emulation's built-in keymap
    backspace: str = ""               # "" | "del" | "bs"
    option_key: str = "left-alt"      # macOS Option: alt | left-alt | text (types characters)
    answerback: str = ""
    local_echo: bool = False
    enter_sends: str = "cr"           # cr | crlf | lf
    keypad_enter_sends: str = ""      # "" = as the host asks (ESC O M in keypad
                                      # application mode, else enter_sends) | cr | crlf | lf
    resize_mode: str = "scale"        # scale: keep cols x rows, fit the font
                                      # grow: keep the font, add rows/columns
    printer: str = ""                 # "" = choose in the print dialog each time
    host_print: bool = True           # VT: host may print via ESC [ 5 i (passthrough)
    keepalive: int = 60               # seconds between keep-alives; 0 = off
    auto_reconnect: bool = False      # reconnect by itself if the connection drops
    idle_timeout: int = 15            # minutes without input before disconnecting; 0 = never
    log_session: bool = False         # capture the session's text to a log file
    log_file_kb: int = 1024           # start a new log file at this size
    log_keep: int = 2                 # older log files kept; older ones are deleted
    hotspots: bool = True             # 3270: click PF3=Exit and other key names on screen
    view: str = ""                    # 3270/5250: "classic" or "modern"; "" = site default
    modern_theme: str = "auto"        # Modern view colours: auto (follows the desktop),
                                      # graphite, paper, or session (its own colours)
    keys: dict[str, str] = field(default_factory=dict)
    macros: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(f"transport must be one of {', '.join(TRANSPORTS)}")
        self.emulation = emulation.ALIASES.get(self.emulation, self.emulation)
        if self.emulation not in emulation.EMULATIONS:
            raise ValueError(f"unknown emulation {self.emulation!r}")
        if self.backspace not in ("", "del", "bs"):
            raise ValueError("backspace must be 'del' or 'bs'")
        if self.option_key not in OPTION_KEYS:
            raise ValueError(f"option_key must be one of {', '.join(OPTION_KEYS)}")
        if self.view not in VIEWS:
            raise ValueError("view must be classic or modern")
        if self.modern_theme not in MODERN_THEMES:
            raise ValueError(f"modern_theme must be one of {', '.join(MODERN_THEMES)}")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535 (0 = the usual port)")
        if self.enter_sends not in ("cr", "crlf", "lf"):
            raise ValueError("enter_sends must be cr, crlf or lf")
        if self.keypad_enter_sends not in ("", "cr", "crlf", "lf"):
            raise ValueError("keypad_enter_sends must be cr, crlf, lf or empty")
        self.lu_name = self.lu_name.strip().upper()
        if self.lu_name and not re.fullmatch(r"[A-Z0-9@#$]{1,8}", self.lu_name):
            raise ValueError("an LU name is 1 to 8 letters, digits, @, # or $")
        if self.resize_mode not in ("scale", "grow"):
            raise ValueError("resize_mode must be scale or grow")
        for key in ("fg_color", "bg_color", "cursor_color"):
            if getattr(self, key):
                _check_hex(getattr(self, key))
        for name, value in self.palette.items():
            if name not in PALETTE_NAMES:
                raise ValueError(f"unknown palette colour {name!r}")
            _check_hex(value)
        if not (self.min_contrast == 0 or 1 <= self.min_contrast <= 21):
            raise ValueError("min_contrast must be 0 (scheme default) or between 1 and 21")
        for key in ("keepalive", "idle_timeout", "log_keep"):
            if getattr(self, key) < 0:
                raise ValueError(f"{key} cannot be negative")
        if self.log_file_kb < 16:
            raise ValueError("log_file_kb must be at least 16")
        emu = emulation.EMULATIONS[self.emulation]
        if emu.block_mode and self.transport != "telnet":
            kind = "TN5250" if emu.family == "ibm5250" else "TN3270"
            raise ValueError(f"{self.emulation} needs a telnet ({kind}) connection")
        if self.device_name and not re.fullmatch(r"[A-Z0-9@#$_]{1,10}", self.device_name):
            raise ValueError("device name must be up to 10 characters: A-Z, 0-9, @ # $ _")

    @property
    def effective_port(self) -> int:
        if not self.port and self.transport == "telnet" and self.tls:
            return 992
        return self.port or DEFAULT_PORTS.get(self.transport, 0)

    @property
    def effective_encoding(self) -> str:
        return self.encoding or emulation.DEFAULT_ENCODING[self.emulation]

    @property
    def slug(self) -> str:
        return slugify(self.name)

    # ---------------------------------------------------------- (de)serialise

    @classmethod
    def from_dict(cls, data: dict) -> "SessionProfile":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown profile setting(s): {', '.join(sorted(unknown))}")
        return cls(**data)

    def to_dict(self) -> dict:
        defaults = SessionProfile()
        out = {}
        for key, value in asdict(self).items():
            # Always write identity fields; skip other defaults to keep files short.
            if key in ("name", "transport", "emulation") or value != getattr(defaults, key):
                out[key] = value
        return out


BUNDLE_SUFFIX = ".cherminal"
BUNDLE_FORMAT = 1


def site_dirs() -> list[Path]:
    """Shared, read-only setup folders, highest priority first.

    * ``$CHERMINAL_SITE_DIR`` - one or more folders (``:``-separated), e.g. a share
    * ``cherminal-config/`` next to the AppImage, so a copied folder travels with it
    * ``cherminal/`` in each ``$XDG_CONFIG_DIRS`` folder (default ``/etc/xdg``;
      on macOS ``/Library/Application Support/Cherminal``)
    """
    dirs = [Path(d) for d in os.environ.get("CHERMINAL_SITE_DIR", "").split(":") if d]
    if os.environ.get("APPIMAGE"):
        dirs.append(Path(os.environ["APPIMAGE"]).parent / "cherminal-config")
    return dirs + system.site_config_dirs()


def read_bundle(path: Path) -> tuple[list[SessionProfile], dict[str, dict]]:
    """A bundle is one TOML file of ``[[session]]`` tables plus the ``[keymap.NAME]``
    tables they use, so a connection and its key mappings move as one file."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if data.get("cherminal_bundle", 0) > BUNDLE_FORMAT:
        raise ValueError(f"{path.name} needs a newer Cherminal")
    profiles = [SessionProfile.from_dict(s) for s in data.get("session", [])]
    for name in data.get("keymap", {}):
        if name != slugify(name):
            raise ValueError(f"keymap name {name!r} must be lower-case letters, digits and -")
    keymaps = {name: {"inherit": km.get("inherit", "vt220"), "keys": km.get("keys", {})}
               for name, km in data.get("keymap", {}).items()}
    return profiles, keymaps


class ProfileStore:
    """The user's own sessions and keymaps, layered over the shared site folders.

    Reads look in the user folder first, then each site folder; writes only ever
    go to the user folder, so a user's edit shadows the shared copy and deleting
    it brings the shared one back.
    """

    def __init__(self, root: Path | None = None, site_roots: list[Path] | None = None):
        self.root = root or config_dir()
        if site_roots is None:
            site_roots = site_dirs() if root is None else []
        self.site_roots = [r for r in site_roots if r.resolve() != self.root.resolve()]

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def keymaps_dir(self) -> Path:
        return self.root / "keymaps"

    # ------------------------------------------------------- site folders

    def _site(self) -> tuple[dict[str, SessionProfile], dict[str, dict]]:
        """Sessions and keymaps from the site folders, by slug / name.

        Re-read on every call so a change on a share shows up without a restart.
        """
        sessions: dict[str, SessionProfile] = {}
        keymaps: dict[str, dict] = {}
        for root in reversed(self.site_roots):          # higher priority wins
            for path in sorted(root.glob("*" + BUNDLE_SUFFIX)):
                try:
                    profiles, kms = read_bundle(path)
                except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
                    continue
                sessions.update({p.slug: p for p in profiles})
                keymaps.update(kms)
            for path in sorted((root / "sessions").glob("*.toml")):
                try:
                    sessions[path.stem] = self.load_file(path)
                except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
                    continue
            for path in sorted((root / "keymaps").glob("*.toml")):
                try:
                    with open(path, "rb") as f:
                        keymaps[path.stem] = tomllib.load(f)
                except (OSError, tomllib.TOMLDecodeError):
                    continue
        return sessions, keymaps

    def origin(self, name: str) -> str:
        """``user``, ``shared`` (site only) or ``customised`` (user copy of a shared one)."""
        slug = slugify(name)
        shared = slug in self._site()[0]
        if (self.sessions_dir / f"{slug}.toml").exists():
            return "customised" if shared else "user"
        return "shared" if shared else "user"

    # ----------------------------------------------------------- sessions

    def list(self) -> list[SessionProfile]:
        by_slug = dict(self._site()[0])
        for path in sorted(self.sessions_dir.glob("*.toml")):
            try:
                by_slug[path.stem] = self.load_file(path)
            except (ValueError, tomllib.TOMLDecodeError, TypeError):
                continue  # a broken file should not hide the others
        return sorted(by_slug.values(), key=lambda p: p.name.lower())

    @staticmethod
    def load_file(path: Path) -> SessionProfile:
        with open(path, "rb") as f:
            return SessionProfile.from_dict(tomllib.load(f))

    def load(self, name: str) -> SessionProfile:
        path = self.sessions_dir / f"{slugify(name)}.toml"
        if path.exists():
            return self.load_file(path)
        shared = self._site()[0].get(slugify(name))
        if shared is None:
            raise FileNotFoundError(f"no saved session named {name!r}")
        return shared

    def save(self, profile: SessionProfile, old_name: str | None = None) -> Path:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / f"{profile.slug}.toml"
        tmp = path.with_suffix(".toml.tmp")
        with open(tmp, "wb") as f:
            tomli_w.dump(profile.to_dict(), f)
        os.replace(tmp, path)
        if old_name and slugify(old_name) != profile.slug:
            (self.sessions_dir / f"{slugify(old_name)}.toml").unlink(missing_ok=True)
        return path

    def delete(self, name: str) -> None:
        """Remove the user's copy. A shared session stays (or comes back)."""
        (self.sessions_dir / f"{slugify(name)}.toml").unlink(missing_ok=True)

    # --------------------------------------------------------------- keymaps

    def keymap_names(self) -> list[str]:
        user = [p.stem for p in self.keymaps_dir.glob("*.toml")]
        return sorted(set(BUILTIN) | set(user) | set(self._site()[1]))

    def _keymap_data(self, name: str, site: dict[str, dict]) -> dict | None:
        path = self.keymaps_dir / f"{name}.toml"
        if path.exists():
            with open(path, "rb") as f:
                return tomllib.load(f)
        return site.get(name)

    def load_keymap_layers(self, name: str, _seen: set[str] | None = None,
                           _site: dict[str, dict] | None = None) -> Keymap:
        """Resolve a keymap by name, following ``inherit`` chains."""
        seen = _seen or set()
        if name in seen:
            raise ValueError(f"keymap inheritance loop at {name!r}")
        seen.add(name)
        site = self._site()[1] if _site is None else _site
        data = self._keymap_data(name, site)
        if data is None:
            return Keymap.builtin(name)
        km = self.load_keymap_layers(data.get("inherit", "vt220"), seen, site)
        km.update(data.get("keys", {}))
        return km

    def save_keymap(self, name: str, keys: dict[str, str], inherit: str) -> Path:
        if name in BUILTIN:
            raise ValueError(f"{name!r} is a built-in keymap; save under another name")
        self.keymaps_dir.mkdir(parents=True, exist_ok=True)
        path = self.keymaps_dir / f"{slugify(name)}.toml"
        with open(path, "wb") as f:
            tomli_w.dump({"inherit": inherit, "keys": keys}, f)
        return path

    def build_keymap(self, profile: SessionProfile) -> Keymap:
        """Built-in table -> named keymap file -> profile settings -> profile [keys]."""
        default = emulation.EMULATIONS[profile.emulation].keymap
        km = self.load_keymap_layers(profile.keymap or default)
        if emulation.EMULATIONS[profile.emulation].block_mode:
            # 3270/5250 keys are actions, not bytes; Enter/Backspace settings don't apply.
            km.update(profile.keys)
            return km
        if profile.backspace == "bs":
            km.update({"Backspace": "^H"})
        elif profile.backspace == "del":
            km.update({"Backspace": "^?"})
        ends = {"cr": "\\r", "crlf": "\\r\\n", "lf": "\\n"}
        enter = ends[profile.enter_sends]
        km.update({"Enter": enter, "KeypadEnter": enter})
        if "Shift+Enter" not in km.bindings:
            km.update({"Shift+Enter": enter})    # else Shift+Enter would type a bare CR
        if profile.keypad_enter_sends:
            # A fixed choice also wins over keypad application mode's ESC O M.
            pad = ends[profile.keypad_enter_sends]
            km.update({"KeypadEnter": pad, "kp:KeypadEnter": pad})
        km.update(profile.keys)
        return km

    # --------------------------------------------------------------- bundles

    def export_bundle(self, names: list[str], path: Path) -> Path:
        """Write sessions, and every non-built-in keymap they use, to one file."""
        profiles = [self.load(n) for n in names]
        site = self._site()[1]
        keymaps: dict[str, dict] = {}
        for p in profiles:
            name = p.keymap
            while name and name not in keymaps:
                data = self._keymap_data(name, site)
                if data is None:
                    break                   # built-in: every copy of Cherminal has it
                keymaps[name] = {"inherit": data.get("inherit", "vt220"),
                                 "keys": data.get("keys", {})}
                name = keymaps[name]["inherit"]
        bundle = {"cherminal_bundle": BUNDLE_FORMAT,
                  "session": [p.to_dict() for p in profiles]}
        if keymaps:
            bundle["keymap"] = keymaps
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as f:
            tomli_w.dump(bundle, f)
        os.replace(tmp, path)
        return path

    def import_bundle(self, path: Path) -> list[str]:
        """Copy a bundle's sessions and keymaps into the user folder, replacing
        any with the same name. Returns the session names."""
        profiles, keymaps = read_bundle(Path(path))
        for name, data in keymaps.items():
            if name in BUILTIN:
                raise ValueError(f"bundle redefines built-in keymap {name!r}")
        for name, data in keymaps.items():
            self.save_keymap(name, data["keys"], data["inherit"])
        for p in profiles:
            self.save(p)
        return [p.name for p in profiles]
