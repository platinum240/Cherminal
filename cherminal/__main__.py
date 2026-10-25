"""Command line entry point.

    cherminal                         open the session manager
    cherminal "Warehouse Box"         open a saved session
    cherminal --ssh user@host[:port]  ad hoc connections
    cherminal --telnet host[:port] -e wyse60
    cherminal --serial /dev/ttyUSB0 --baud 9600
    cherminal --local
    cherminal --list                  print saved sessions
    cherminal --export site.cherminal "Mainframe A" "Mainframe B"
    cherminal --import site.cherminal
    cherminal --limited "Mainframe A"  locked down: File menu is Close tab / Exit only
    cherminal --install-desktop       add Cherminal to the desktop menu with its icon
    cherminal --check-policy FILE     check a site policy file (.toml or .plist) before deploying it

An administrator's policy in /etc/cherminal/policy.toml (on macOS,
/Library/Application Support/Cherminal/policy.toml or managed preferences;
see cherminal.policy) applies to every start and cannot be turned off from
the command line.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from . import __version__, emulation, policy, system
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
    ap.add_argument("--export", metavar="FILE",
                    help="save the named sessions (all if none named) and their keymaps "
                         "to one file, then exit")
    ap.add_argument("--import", dest="import_", metavar="FILE", action="append",
                    help="add the sessions and keymaps in FILE, replacing same-named ones")
    ap.add_argument("--limited", action="store_true",
                    help="lock the menus: no session editing, new connections or local "
                         "shell; File offers only Close tab and Exit")
    ap.add_argument("--install-desktop", action="store_true",
                    help="add a menu entry and the Cherminal icon under ~/.local/share")
    ap.add_argument("--check-policy", metavar="FILE",
                    help="check a site policy file, print the settings it enforces, then exit")
    ap.add_argument("--version", action="version", version=f"cherminal {__version__}")
    args = ap.parse_args(argv)
    if args.check_policy:
        try:
            rules = policy.read(Path(args.check_policy))
        except policy.PolicyError as e:
            print(f"cherminal: {e}", file=sys.stderr)
            return 2
        print(f"{args.check_policy} is valid. Settings it enforces:")
        print(rules.describe())
        return 0
    try:
        # A broken policy stops Cherminal rather than letting it run unrestricted.
        policy.set_current(policy.load())
    except policy.PolicyError as e:
        print(f"cherminal: {e}", file=sys.stderr)
        print("cherminal: not starting until the site policy is fixed; ask your administrator",
              file=sys.stderr)
        return 2
    rules = policy.current()
    limited = args.limited or rules.limited
    if args.install_desktop:
        if system.IS_MAC:
            print("cherminal: not needed on macOS; drag Cherminal.app to Applications instead",
                  file=sys.stderr)
            return 0
        from .desktop import install
        print(f"installed {install()}")
        return 0

    store = ProfileStore()
    if args.list:
        for p in store.list():
            print(f"{p.name}\t{p.transport}\t{p.host or p.serial_device}\t{p.emulation}"
                  f"\t{store.origin(p.name)}")
        return 0
    try:
        if args.export:
            names = args.sessions or [p.name for p in store.list()]
            store.export_bundle(names, args.export)
            print(f"exported {len(names)} session(s) to {args.export}")
            return 0
        for path in args.import_ or []:
            names = store.import_bundle(path)
            print(f"imported {', '.join(names) or 'no sessions'} from {path}")
        if args.import_ and not args.sessions:
            return 0
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        print(f"cherminal: {e}", file=sys.stderr)
        return 2
    try:
        profiles = build_profiles(args, store)
        for p in profiles:
            rules.check(p)
    except (FileNotFoundError, ValueError) as e:
        print(f"cherminal: {e}", file=sys.stderr)
        return 2

    from .gui.app import run
    return run(profiles, store, show_manager=not profiles, limited=limited)


if __name__ == "__main__":
    sys.exit(main())
