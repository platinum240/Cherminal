"""Site policy: settings an administrator enforces and users cannot change.

The policy is one TOML file at ``/etc/cherminal/policy.toml``, owned by root
and deployed with the rest of a thin client's configuration (for example
from Elux Scout). Unlike the site folders in ``config``, its location is
fixed: no environment variable or command-line option can point Cherminal
elsewhere, so a user cannot start it without the policy.

Every setting is optional and the defaults change nothing, so an empty or
missing file behaves exactly like no policy. A file that exists but cannot
be read or has a mistake in it stops Cherminal from starting rather than
running unrestricted; check a file before deploying it with
``cherminal --check-policy FILE``.

    limited = true                    # same as --limited, always on
    allowed_transports = ["telnet", "ssh"]
    file_upload = false               # no SFTP upload, even where a session enables it
    print_to_file = false             # Print screen offers printers only, never PDF
    require_tls = false               # Telnet/TN3270 only over TLS
    require_tls_verify = false        # TLS sessions must check the host's certificate
    tls_ca_file = "/etc/cherminal/ca.pem"   # extra CA certificates to trust for TLS
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

POLICY_PATH = Path("/etc/cherminal/policy.toml")
TRANSPORTS = ("ssh", "telnet", "serial", "local")


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    limited: bool = False
    allowed_transports: tuple[str, ...] = TRANSPORTS
    file_upload: bool = True
    print_to_file: bool = True
    require_tls: bool = False
    require_tls_verify: bool = False
    tls_ca_file: str = ""
    source: str = field(default="", compare=False)   # where it was read from

    @classmethod
    def from_dict(cls, data: dict, source: str = "") -> "Policy":
        known = {f.name for f in fields(cls)} - {"source"}
        unknown = set(data) - known
        if unknown:
            raise PolicyError(f"unknown policy setting(s): {', '.join(sorted(unknown))}")
        for key in ("limited", "file_upload", "print_to_file", "require_tls",
                    "require_tls_verify"):
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
        if "tls_ca_file" in values and not isinstance(values["tls_ca_file"], str):
            raise PolicyError("tls_ca_file must be a file path")
        return cls(**values, source=source)

    @property
    def active(self) -> bool:
        return self != Policy()

    @property
    def local_shell(self) -> bool:
        return "local" in self.allowed_transports and not self.limited

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

    def describe(self) -> str:
        lines = [f"{f.name} = {getattr(self, f.name)!r}" for f in fields(self)
                 if f.name != "source"]
        return "\n".join(lines)


def read(path: Path) -> Policy:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise PolicyError(f"{path}: {e}") from e
    except OSError as e:
        raise PolicyError(f"{path}: cannot read the policy ({e.strerror or e})") from e
    try:
        return Policy.from_dict(data, source=str(path))
    except PolicyError as e:
        raise PolicyError(f"{path}: {e}") from e


def load(path: Path | None = None) -> Policy:
    """The policy at ``path`` (default POLICY_PATH); no file means no restrictions."""
    path = path or POLICY_PATH
    try:
        path.stat()
    except FileNotFoundError:
        return Policy()
    except OSError as e:          # e.g. a folder users may not look in
        raise PolicyError(f"{path}: cannot read the policy ({e.strerror or e})") from e
    return read(path)


_current = Policy()


def current() -> Policy:
    return _current


def set_current(policy: Policy) -> None:
    global _current
    _current = policy
