"""Saved session profiles and keymap files.

Everything lives under ``$XDG_CONFIG_HOME/cherminal`` (``~/.config/cherminal``):

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

from . import emulation
from .keymap import BUILTIN, Keymap

TRANSPORTS = ("ssh", "telnet", "serial", "local")
DEFAULT_PORTS = {"ssh": 22, "telnet": 23}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "cherminal"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "session"


@dataclass
class SessionProfile:
    name: str = "New session"
    transport: str = "ssh"
    host: str = ""
    port: int = 0                     # 0 = transport default
    username: str = ""
    identity_file: str = ""           # SSH private key
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
    keymap: str = ""                  # "" = emulation's built-in keymap
    backspace: str = ""               # "" | "del" | "bs"
    answerback: str = ""
    local_echo: bool = False
    enter_sends: str = "cr"           # cr | crlf | lf
    keys: dict[str, str] = field(default_factory=dict)
    macros: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(f"transport must be one of {', '.join(TRANSPORTS)}")
        if self.emulation not in emulation.EMULATIONS:
            raise ValueError(f"unknown emulation {self.emulation!r}")
        if self.backspace not in ("", "del", "bs"):
            raise ValueError("backspace must be 'del' or 'bs'")
        if self.enter_sends not in ("cr", "crlf", "lf"):
            raise ValueError("enter_sends must be cr, crlf or lf")

    @property
    def effective_port(self) -> int:
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


class ProfileStore:
    def __init__(self, root: Path | None = None):
        self.root = root or config_dir()

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def keymaps_dir(self) -> Path:
        return self.root / "keymaps"

    def list(self) -> list[SessionProfile]:
        profiles = []
        for path in sorted(self.sessions_dir.glob("*.toml")):
            try:
                profiles.append(self.load_file(path))
            except (ValueError, tomllib.TOMLDecodeError, TypeError):
                continue  # a broken file should not hide the others
        return sorted(profiles, key=lambda p: p.name.lower())

    @staticmethod
    def load_file(path: Path) -> SessionProfile:
        with open(path, "rb") as f:
            return SessionProfile.from_dict(tomllib.load(f))

    def load(self, name: str) -> SessionProfile:
        path = self.sessions_dir / f"{slugify(name)}.toml"
        if not path.exists():
            raise FileNotFoundError(f"no saved session named {name!r}")
        return self.load_file(path)

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
        (self.sessions_dir / f"{slugify(name)}.toml").unlink(missing_ok=True)

    # --------------------------------------------------------------- keymaps

    def keymap_names(self) -> list[str]:
        user = [p.stem for p in self.keymaps_dir.glob("*.toml")]
        return sorted(set(BUILTIN) | set(user))

    def load_keymap_layers(self, name: str, _seen: set[str] | None = None) -> Keymap:
        """Resolve a keymap by name, following ``inherit`` chains."""
        seen = _seen or set()
        if name in seen:
            raise ValueError(f"keymap inheritance loop at {name!r}")
        seen.add(name)
        path = self.keymaps_dir / f"{name}.toml"
        if not path.exists():
            return Keymap.builtin(name)
        with open(path, "rb") as f:
            data = tomllib.load(f)
        base = data.get("inherit", "vt220")
        km = self.load_keymap_layers(base, seen)
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
        if profile.backspace == "bs":
            km.update({"Backspace": "^H"})
        elif profile.backspace == "del":
            km.update({"Backspace": "^?"})
        enter = {"cr": "\\r", "crlf": "\\r\\n", "lf": "\\n"}[profile.enter_sends]
        km.update({"Enter": enter, "KeypadEnter": enter})
        km.update(profile.keys)
        return km
