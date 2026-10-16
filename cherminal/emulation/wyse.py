"""Wyse 50 / Wyse 60 native-mode emulation.

Commands follow the published Wyse 50/60 programmer guides. Attributes are
handled the Wyse 60 "non-embedded" way: ``ESC G n`` changes the attribute
of characters written after it rather than occupying a screen cell. Items
marked UNVERIFIED should be checked against a manual or real terminal.
"""

from __future__ import annotations

from .base import Emulation

# How many argument characters follow each ESC command. "CR" / "DEL" / "C"
# mean "read up to and including that terminator".
_ARGS = {
    "=": 2, "G": 1, "`": 1, "A": 2, "H": 1, ".": 1, "e": 1,
    "a": "C", "F": "\r", "z": "\x7f",
}


class Wyse50(Emulation):
    name = "wyse50"
    term_type = "wy50"
    telnet_type = "WY50"
    keymap = "wyse"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("encoding", "latin-1")
        super().__init__(*args, **kwargs)
        self._seq: str | None = None
        self.graphics = False

    def reset(self) -> None:
        super().reset()
        self._seq = None
        self.graphics = False

    def feed_text(self, text: str) -> None:
        for ch in text:
            if self._seq is not None:
                self._collect(ch)
            elif ch == "\x1b":
                self._seq = ""
            elif ord(ch) < 0x20:
                self._control(ord(ch))
            elif ch != "\x7f":
                self.screen.put_char(ch)

    # ------------------------------------------------------------ controls

    def _control(self, o: int) -> None:
        s = self.screen
        if o == 0x07:
            self.on_bell()
        elif o == 0x08:
            s.backspace()
        elif o == 0x09:
            s.tab()
        elif o == 0x0a:
            s.linefeed()
        elif o == 0x0b:
            s.cursor_up()
        elif o == 0x0c:
            s.cursor_forward()
        elif o == 0x0d:
            s.carriage_return()
        elif o == 0x1e:
            s.cursor_to(0, 0)
        elif o == 0x1a:
            self._clear()
        elif o == 0x1f:
            s.carriage_return()
            s.linefeed()
        elif o == 0x05 and self.answerback:
            self.send(self.answerback)

    def _clear(self) -> None:
        s = self.screen
        s.attr = s.attr.__class__()
        s.cursor_to(0, 0)
        s.erase_in_display(2)

    # ------------------------------------------------------------- escapes

    def _collect(self, ch: str) -> None:
        self._seq += ch
        cmd, args = self._seq[0], self._seq[1:]
        need = _ARGS.get(cmd, 0)
        if isinstance(need, int):
            if len(args) < need:
                return
        elif not args.endswith(need):
            return
        self._seq = None
        self._dispatch(cmd, args)

    def _dispatch(self, cmd: str, args: str) -> None:
        s = self.screen
        if cmd == "=":
            s.cursor_to(ord(args[0]) - 32, ord(args[1]) - 32)
        elif cmd == "a":
            # ESC a rrR cccC, decimal and 1-based.
            row, _, col = args[:-1].partition("R")
            if row.isdigit() and col.isdigit():
                s.cursor_to(int(row) - 1, int(col) - 1)
        elif cmd in "*+;:":
            self._clear()
        elif cmd in "Tt":
            s.erase_in_line(0)
        elif cmd in "Yy":
            s.erase_in_display(0)
        elif cmd == "E":
            x = s.x
            s.insert_lines(1)
            s.x = x
        elif cmd == "R":
            x = s.x
            s.delete_lines(1)
            s.x = x
        elif cmd == "Q":
            s.insert_chars(1)
        elif cmd == "W":
            s.delete_chars(1)
        elif cmd == "q":
            s.insert_mode = True
        elif cmd == "r":
            s.insert_mode = False
        elif cmd == "G":
            self._attribute(args)
        elif cmd == "`":
            if args == "0":
                s.cursor_visible = False
            elif args == "1":
                s.cursor_visible = True
            s.dirty = True
        elif cmd == "j":
            s.reverse_index()
        elif cmd == "i":
            s.tab()
        elif cmd == "I":
            s.back_tab()
        elif cmd == "1":
            s.set_tabstop()
        elif cmd == "2":
            s.clear_tabstop()
        elif cmd == "0":
            s.clear_tabstop(all_stops=True)
        elif cmd == "{":
            s.cursor_to(0, 0)
        elif cmd == "?":
            # UNVERIFIED: reply format for "read cursor address".
            self.send(chr(s.y + 32) + chr(s.x + 32) + "\r")
        elif cmd == "H":
            if args == "\x02":
                self.graphics = True
            elif args == "\x03":
                self.graphics = False
        elif cmd == "b":
            s.reverse_screen = True   # UNVERIFIED
            s.dirty = True
        elif cmd == "d":
            s.reverse_screen = False  # UNVERIFIED
            s.dirty = True
        # ESC F (status line), ESC z (program function key), protect modes,
        # keyboard lock and cursor shape are accepted and ignored for now.

    def _attribute(self, code: str) -> None:
        v = ord(code) - 0x30
        if v < 0:
            return
        s = self.screen
        s.attr = s.attr.__class__(
            invisible=bool(v & 1), blink=bool(v & 2), reverse=bool(v & 4),
            underline=bool(v & 8), dim=bool(v & 0x40))


class Wyse60(Wyse50):
    name = "wyse60"
    term_type = "wy60"
    telnet_type = "WY60"


class TVI925(Wyse50):
    # The Wyse 50 command set grew out of the TeleVideo 9xx one; the
    # common subset is shared. UNVERIFIED beyond that subset.
    name = "tvi925"
    term_type = "tvi925"
    telnet_type = "TVI925"


class TVI950(TVI925):
    name = "tvi950"
    term_type = "tvi950"
    telnet_type = "TVI950"


class ADM3A(Wyse50):
    """Lear Siegler ADM-3A style: control-key cursor motion and ESC = addressing."""
    name = "adm3a"
    term_type = "adm3a"
    telnet_type = "ADM3A"
