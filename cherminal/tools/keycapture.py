"""Record what another terminal emulator sends for each key.

Run this on a Linux box, connect to it from the emulator you want to match
(for example TinyTerm on Windows) with Telnet, and press each key it asks
for. The result is a Cherminal keymap file, so Cherminal can reproduce that
emulator's keyboard exactly without anyone looking inside its code.

    cherminal-keycapture --port 2323 --name tinyterm-wyse60 --inherit wyse

Press Space to skip a key you do not have, or Ctrl+] to finish early and
save what was captured so far.
"""

from __future__ import annotations

import argparse
import select
import socket
import sys
from pathlib import Path

import tomli_w

from ..config import ProfileStore, slugify
from ..keymap import BUILTIN, format_notation

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
ECHO, SGA, TTYPE = 1, 3, 24

DEFAULT_KEYS = (
    [f"F{i}" for i in range(1, 13)]
    + [f"Shift+F{i}" for i in range(1, 13)]
    + [f"Ctrl+F{i}" for i in range(1, 13)]
    + ["Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown",
       "Insert", "Delete", "Backspace", "Tab", "Shift+Tab", "Enter", "Escape",
       "KeypadEnter", "KeypadPlus", "KeypadMinus", "KeypadMultiply", "KeypadDivide",
       "KeypadDecimal"] + [f"Keypad{i}" for i in range(10)]
)
FINISH = b"\x1d"     # Ctrl+]
SKIP = b" "


class Capture:
    """Server side of a minimal Telnet session: character mode, no echo."""

    def __init__(self, conn: socket.socket):
        self.conn = conn
        self.term_type = ""
        self._buf = bytearray()

    def negotiate(self) -> None:
        # We echo nothing and want one character at a time.
        self.conn.sendall(bytes([IAC, WILL, ECHO, IAC, WILL, SGA, IAC, DO, TTYPE]))
        self.read_for(0.8)
        if self.term_type == "":
            self.conn.sendall(bytes([IAC, SB, TTYPE, 1, IAC, SE]))
            self.read_for(0.8)

    def say(self, text: str) -> None:
        self.conn.sendall(text.replace("\n", "\r\n").encode("ascii", "replace"))

    def read_for(self, idle: float) -> bytes:
        """Read until ``idle`` seconds pass with no data; return user bytes."""
        out = bytearray()
        while True:
            ready, _, _ = select.select([self.conn], [], [], idle)
            if not ready:
                return bytes(out)
            chunk = self.conn.recv(4096)
            if not chunk:
                raise ConnectionError("client disconnected")
            out += self._strip_telnet(chunk)

    def read_key(self, idle: float = 0.35) -> bytes:
        while True:
            select.select([self.conn], [], [])   # wait for the first byte
            data = self.read_for(idle)
            if data:
                return data

    def _strip_telnet(self, chunk: bytes) -> bytes:
        data = self._buf + chunk
        self._buf = bytearray()
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b != IAC:
                # Telnet clients send CR NUL / CR LF for Enter; keep the CR.
                if b == 0 and out[-1:] == b"\r":
                    i += 1
                    continue
                out.append(b)
                i += 1
                continue
            if i + 1 >= len(data):
                self._buf = bytearray(data[i:])
                break
            cmd = data[i + 1]
            if cmd == IAC:
                out.append(IAC)
                i += 2
            elif cmd in (DO, DONT, WILL, WONT):
                if i + 2 >= len(data):
                    self._buf = bytearray(data[i:])
                    break
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i)
                if end < 0:
                    self._buf = bytearray(data[i:])
                    break
                sb = data[i + 2:end]
                if len(sb) > 2 and sb[0] == TTYPE and sb[1] == 0:
                    self.term_type = sb[2:].decode("ascii", "replace")
                i = end + 2
            else:
                i += 2
        return bytes(out)


def run(conn: socket.socket, keys: list[str]) -> tuple[dict[str, str], str]:
    cap = Capture(conn)
    cap.negotiate()
    cap.say("\nCherminal key capture"
            + (f" (your terminal reports itself as {cap.term_type})" if cap.term_type else "")
            + "\nPress each key when asked. Space skips a key, Ctrl+] finishes.\n\n")
    captured: dict[str, str] = {}
    for key in keys:
        cap.say(f"Press {key}: ")
        data = cap.read_key()
        if data == FINISH:
            cap.say("finished\n")
            break
        if data == SKIP:
            cap.say("skipped\n")
            continue
        text = format_notation(data.decode("latin-1"))
        captured[key] = text
        cap.say(text + "\n")
    cap.say(f"\nCaptured {len(captured)} keys. You can disconnect now.\n")
    return captured, cap.term_type


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="0.0.0.0", help="address to listen on")
    ap.add_argument("--port", type=int, default=2323)
    ap.add_argument("--name", required=True, help="keymap name to save, e.g. tinyterm-wyse60")
    ap.add_argument("--inherit", default="vt220", choices=sorted(BUILTIN),
                    help="built-in keymap for keys you skip")
    ap.add_argument("--keys", help="comma-separated key names to ask for (default: a full PC keyboard)")
    ap.add_argument("--output", type=Path, help="write here instead of the Cherminal keymaps folder")
    args = ap.parse_args(argv)
    keys = [k.strip() for k in args.keys.split(",")] if args.keys else DEFAULT_KEYS

    with socket.create_server((args.host, args.port), reuse_port=False) as srv:
        print(f"Listening on {args.host}:{args.port}; telnet here from the emulator to capture.")
        conn, addr = srv.accept()
        print(f"Connection from {addr[0]}")
        with conn:
            try:
                captured, term_type = run(conn, keys)
            except ConnectionError as e:
                print(f"Stopped: {e}", file=sys.stderr)
                return 1

    doc = {"inherit": args.inherit, "keys": captured}
    if term_type:
        doc["captured_from"] = term_type
    if args.output:
        path = args.output
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        store = ProfileStore()
        store.keymaps_dir.mkdir(parents=True, exist_ok=True)
        path = store.keymaps_dir / f"{slugify(args.name)}.toml"
    with open(path, "wb") as f:
        tomli_w.dump(doc, f)
    print(f"Saved {len(captured)} keys to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
