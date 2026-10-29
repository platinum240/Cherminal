"""Site policy: settings an administrator enforces and users cannot change.

The policy is one TOML file at ``/etc/cherminal/policy.toml``, owned by root
and deployed with the rest of a thin client's configuration (for example
from Elux Scout). Unlike the site folders in ``config``, its location is
fixed: no environment variable or command-line option can point Cherminal
elsewhere, so a user cannot start it without the policy.

On macOS the file is ``/Library/Application Support/Cherminal/policy.toml``,
and the same settings can also come from managed preferences: a
configuration profile from Jamf or another MDM for the preference domain
``io.github.platinum240.cherminal``, which macOS writes to
``/Library/Managed Preferences``. Settings there override the file's, and a
profile for one user overrides one for the whole computer.

Every setting is optional and the defaults change nothing, so an empty or
missing file behaves exactly like no policy. A file that exists but cannot
be read or has a mistake in it stops Cherminal from starting rather than
running unrestricted; check a file before deploying it with
``cherminal --check-policy FILE``.

In limited mode (``limited = true`` here, or ``--limited``) IND$FILE
transfers are off unless the file sets ``file_upload = true`` or
``file_download = true`` explicitly, and even then they only read and write
files directly in the user's Downloads folder, chosen by name: no file
browser opens.

    limited = true                    # same as --limited, always on
    allowed_transports = ["telnet", "ssh"]
    file_upload = false               # no SFTP upload or IND$FILE send, even where enabled
    file_download = false             # no IND$FILE receive from a mainframe
    print_to_file = false             # Print screen offers printers only, never PDF
    require_tls = false               # Telnet/TN3270 only over TLS
    require_tls_verify = false        # TLS sessions must check the host's certificate
    tls_ca_file = "/etc/cherminal/ca.pem"   # extra CA certificates to trust for TLS
    max_idle_timeout = 15             # minutes; sessions may be shorter, never longer or off
    auto_reconnect = false            # no reconnecting by itself after a dropped connection
    session_logging = "allowed"       # "allowed", "never" or "always"
    log_dir = "/var/log/cherminal/%u" # where session logs go (%u = user name)
    log_total_mb = 10                 # session logs never take more than this in all
    audit_log = true                  # connection log to syslog/journald (never keystrokes)
    ssh_known_hosts_only = true       # SSH only to hosts whose keys the administrator added
    modern_view = "allowed"           # 3270/5250 Modern view: "off", "allowed" or "default"
    screen_history = true             # Modern view keeps this session's screens in memory
"""

from __future__ import annotations

import getpass
import plistlib
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from xml.parsers.expat import ExpatError

from . import system

POLICY_PATH = system.policy_path()
TRANSPORTS = ("ssh", "telnet", "serial", "local")
LOGGING = ("allowed", "never", "always")
MODERN_VIEW = ("off", "allowed", "default")


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    limited: bool = False
    allowed_transports: tuple[str, ...] = TRANSPORTS
    file_upload: bool = True
    file_download: bool = True
    print_to_file: bool = True
    require_tls: bool = False
    require_tls_verify: bool = False
    tls_ca_file: str = ""
    max_idle_timeout: int = 0         # minutes; 0 = sessions decide
    auto_reconnect: bool = True       # sessions may reconnect by themselves
    session_logging: str = "allowed"
    log_dir: str = ""
    log_total_mb: int = 10
    audit_log: bool = False
    ssh_known_hosts_only: bool = False   # refuse SSH hosts whose keys aren't known
    modern_view: str = "allowed"      # "off": classic only; "default": modern unless chosen
    screen_history: bool = True       # Modern view may keep past screens (in memory only)
    source: str = field(default="", compare=False)   # where it was read from
    given: frozenset = field(default=frozenset(), compare=False)   # settings in the file

    @classmethod
    def from_dict(cls, data: dict, source: str = "") -> "Policy":
        known = {f.name for f in fields(cls)} - {"source", "given"}
        unknown = set(data) - known
        if unknown:
            raise PolicyError(f"unknown policy setting(s): {', '.join(sorted(unknown))}")
        for key in ("limited", "file_upload", "file_download", "print_to_file", "require_tls",
                    "require_tls_verify", "auto_reconnect", "audit_log", "ssh_known_hosts_only",
                    "screen_history"):
            if key in data and not isinstance(data[key], bool):
                raise PolicyError(f"{key} must be true or false")
        values = dict(data)
        if "allowed_transports" in values:
            kinds = values["allowed_transports"]
            if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
                raise PolicyError("allowed_transports must be a list such as [\"ssh\", \"telnet\"]")
            bad = [k for k in kinds if k not in TRANSPORTS]
            if bad:
                raise PolicyError(f"allowed_transports: unknown transport(s) {', '.join(bad)}; "
                                  f"use {', '.join(TRANSPORTS)}")
            values["allowed_transports"] = tuple(kinds)
        for key in ("tls_ca_file", "log_dir"):
            if key in values and not isinstance(values[key], str):
                raise PolicyError(f"{key} must be a path")
        for key, low in (("max_idle_timeout", 0), ("log_total_mb", 1)):
            if key in values and (not isinstance(values[key], int)
                                  or isinstance(values[key], bool) or values[key] < low):
                raise PolicyError(f"{key} must be a whole number, {low} or more")
        if values.get("session_logging", "allowed") not in LOGGING:
            raise PolicyError(f"session_logging must be one of {', '.join(LOGGING)}")
        if values.get("modern_view", "allowed") not in MODERN_VIEW:
            raise PolicyError(f"modern_view must be one of {', '.join(MODERN_VIEW)}")
        return cls(**values, source=source, given=frozenset(data))

    @property
    def active(self) -> bool:
        return self != Policy()

    @property
    def local_shell(self) -> bool:
        return "local" in self.allowed_transports and not self.limited

    def file_transfer(self, send: bool, limited: bool = False) -> bool:
        """May an IND$FILE transfer go this way (send = to the host)? In
        limited mode only if the policy file allows it in so many words."""
        key = "file_upload" if send else "file_download"
        if not getattr(self, key):
            return False
        if limited or self.limited:
            return key in self.given
        return True

    def check(self, profile) -> None:
        """Raise PolicyError if the policy does not allow this session."""
        if profile.transport not in self.allowed_transports:
            raise PolicyError(f"{profile.transport} connections are not allowed on this "
                              f"computer")
        if self.limited and profile.transport == "local":
            raise PolicyError("a local shell is not allowed on this computer")
        if profile.transport == "telnet":
            if self.require_tls and not profile.tls:
                raise PolicyError("this computer only allows Telnet over TLS; turn on "
                                  "Use TLS in the session")
            if self.require_tls_verify and profile.tls and not profile.tls_verify:
                raise PolicyError("this computer requires checking the host's certificate; "
                                  "turn on Check the host's certificate in the session")

    def idle_timeout(self, minutes: int) -> int:
        """A session's idle timeout in minutes (0 = none) after the policy's cap."""
        if self.max_idle_timeout and (not minutes or minutes > self.max_idle_timeout):
            return self.max_idle_timeout
        return minutes

    def modern(self, view: str) -> bool:
        """Does a session whose view setting is ``view`` start in Modern view?"""
        if self.modern_view == "off":
            return False
        return view == "modern" or (not view and self.modern_view == "default")

    def logging(self, wanted: bool) -> bool:
        return {"never": False, "always": True}.get(self.session_logging, wanted)

    def describe(self) -> str:
        lines = [f"{f.name} = {getattr(self, f.name)!r}" for f in fields(self)
                 if f.name not in ("source", "given")]
        return "\n".join(lines)


def _read_data(path: Path) -> dict:
    """The settings in a policy file: TOML, or a property list (XML or
    binary) as macOS managed preferences are."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise PolicyError(f"{path}: cannot read the policy ({e.strerror or e})") from e
    plist = path.suffix == ".plist" or raw.lstrip().startswith((b"<?xml", b"bplist"))
    try:
        data = plistlib.loads(raw) if plist else tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, plistlib.InvalidFileException, ExpatError,
            ValueError) as e:
        raise PolicyError(f"{path}: {e}") from e
    if plist:
        if not isinstance(data, dict):
            raise PolicyError(f"{path}: the property list must be a dictionary of settings")
        # Profiles may carry their own bookkeeping keys next to the settings.
        data = {k: v for k, v in data.items() if not k.startswith("Payload")}
    return data


def read(path: Path) -> Policy:
    data = _read_data(path)
    try:
        return Policy.from_dict(data, source=str(path))
    except PolicyError as e:
        raise PolicyError(f"{path}: {e}") from e


def managed_prefs_paths() -> list[Path]:
    """macOS managed preferences that apply to this user (none on Linux)."""
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = ""
    paths = system.managed_prefs_paths(user)
    return paths if user else paths[:1]


def _exists(path: Path) -> bool:
    try:
        path.stat()
    except FileNotFoundError:
        return False
    except OSError as e:          # e.g. a folder users may not look in
        raise PolicyError(f"{path}: cannot read the policy ({e.strerror or e})") from e
    return True


def load(path: Path | None = None) -> Policy:
    """The policy at ``path`` (default POLICY_PATH) with any macOS managed
    preferences on top; no file and no preferences mean no restrictions."""
    found = [p for p in [path or POLICY_PATH] + managed_prefs_paths() if _exists(p)]
    if not found:
        return Policy()
    if len(found) == 1:
        return read(found[0])
    data: dict = {}
    for p in found:
        data.update(_read_data(p))
    source = ", ".join(str(p) for p in found)
    try:
        return Policy.from_dict(data, source=source)
    except PolicyError as e:
        raise PolicyError(f"{source}: {e}") from e


_current = Policy()


def current() -> Policy:
    return _current


def set_current(policy: Policy) -> None:
    global _current
    _current = policy
