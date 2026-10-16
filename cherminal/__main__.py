"""Command line entry point.

    cherminal                         open the session manager
    cherminal "Warehouse Box"         open a saved session
    cherminal --ssh user@host[:port]  ad hoc connections
    cherminal --telnet host[:port] -e wyse60
    cherminal --serial /dev/ttyUSB0 --baud 9600
    cherminal --local
    cherminal --list                  print saved sessions
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, emulation
from .config import ProfileStore, SessionProfile


def _host_port(value: str) -> tuple[str, str, int]:
    user, _, rest = value.rpartition("@")
    # One colon means host:port; more means a bare IPv6 address.
    host, port = rest.split(":") if rest.count(":") == 1 else (rest, "")
    return user, host, int(port) if port else 0


def build_profiles(args, store: ProfileStore) -> list[SessionProfile]:
    common = {}
    if args.emulation:
        common["emulation"] = args.emulation
    profiles = [store.load(name) for name in args.sessions]
    if args.ssh:
        user, host, port = _host_port(args.ssh)
        profiles.append(SessionProfile(name=host, transport="ssh", host=host, port=port,
                                       username=user, **common))
    if args.telnet:
        _, host, port = _host_port(args.telnet)
        profiles.append(SessionProfile(name=host, transport="telnet", host=host, port=port,
                                       **common))
    if args.serial:
        profiles.append(SessionProfile(name=args.serial, transport="serial",
                                       serial_device=args.serial, baud=args.baud, **common))
    if args.local:
        common.setdefault("emulation", "xterm")
        profiles.append(SessionProfile(name="Local shell", transport="local", **common))
    return profiles


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cherminal", description="Cherminal terminal emulator")
    ap.add_argument("sessions", nargs="*", help="saved session names to open")
    ap.add_argument("--ssh", metavar="[USER@]HOST[:PORT]")
    ap.add_argument("--telnet", metavar="HOST[:PORT]")
    ap.add_argument("--serial", metavar="DEVICE")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--local", action="store_true", help="open a local shell")
    ap.add_argument("-e", "--emulation", choices=list(emulation.EMULATIONS))
    ap.add_argument("--list", action="store_true", help="list saved sessions and exit")
    ap.add_argument("--version", action="version", version=f"cherminal {__version__}")
    args = ap.parse_args(argv)

    store = ProfileStore()
    if args.list:
        for p in store.list():
            print(f"{p.name}\t{p.transport}\t{p.host or p.serial_device}\t{p.emulation}")
        return 0
    try:
        profiles = build_profiles(args, store)
    except (FileNotFoundError, ValueError) as e:
        print(f"cherminal: {e}", file=sys.stderr)
        return 2

    from .gui.app import run
    return run(profiles, store, show_manager=not profiles)


if __name__ == "__main__":
    sys.exit(main())
