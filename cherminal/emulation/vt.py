"""DEC VT family and ANSI emulations.

One ECMA-48 style state machine (after the well-known DEC parser state
diagram) serves VT100, VT220, SCO ANSI, the Linux console and xterm. The
variants differ in device-attribute replies, $TERM names, default
character set and a handful of private sequences.
"""

from __future__ import annotations

from ..screen import Attr
from .base import Emulation

# DEC Special Graphics (line drawing), selected with ESC ( 0.
DEC_GRAPHICS = {
    "`": "◆", "a": "▒", "b": "␉", "c": "␌", "d": "␍", "e": "␊", "f": "°",
    "g": "±", "h": "␤", "i": "␋", "j": "┘", "k": "┐", "l": "┌", "m": "└",
    "n": "┼", "o": "⎺", "p": "⎻", "q": "─", "r": "⎼", "s": "⎽", "t": "├",
    "u": "┤", "v": "┴", "w": "┬", "x": "│", "y": "≤", "z": "≥", "{": "π",
    "|": "≠", "}": "£", "~": "·",
}
UK_CHARSET = {"#": "£"}

# SCO / PC colour order -> ANSI colour order.
PC_TO_ANSI = [0, 4, 2, 6, 1, 5, 3, 7]

GROUND, ESCAPE, ESC_INTER, CSI_PARAM, OSC, DCS, CHARSET = range(7)


class VTEmulation(Emulation):
    name = "vt220"
    term_type = "vt220"
    telnet_type = "VT220"
    keymap = "vt220"
    primary_da = "\x1b[?62;1;2;6;7;8;9c"
    secondary_da = "\x1b[>1;10;0c"
    sco_private = False   # CSI = ... colour sequences and CSI s/u

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.c1_controls = self.encoding.replace("_", "-").lower() not in ("utf-8", "utf8")
        self._reset_parser()
        self.charsets = ["B", "B", "B", "B"]
        self.gl = 0
        self.single_shift: int | None = None
        self.newline_mode = False

    def _reset_parser(self) -> None:
        self.state = GROUND
        self.params = ""
        self.inter = ""
        self.osc = ""
        self.charset_slot = 0

    def reset(self) -> None:
        super().reset()
        self._reset_parser()
        self.charsets = ["B", "B", "B", "B"]
        self.gl = 0
        self.single_shift = None
        self.newline_mode = False

    # --------------------------------------------------------------- input

    # Printer controller mode (VT102+ "passthrough" printing): everything
    # between ESC [ 5 i and ESC [ 4 i goes to the local printer untouched.
    # It is cut out at the byte level so printer codes (PCL, PostScript)
    # survive whatever the session's character set is.
    PRINT_ON, PRINT_OFF = b"\x1b[5i", b"\x1b[4i"
    host_print = True

    def feed(self, data: bytes) -> None:
        data = self._held + data
        self._held = b""
        while data:
            mark = self.PRINT_OFF if self.printing else self.PRINT_ON
            i = data.find(mark)
            if i < 0:
                keep = next((k for k in range(len(mark) - 1, 0, -1)
                             if data.endswith(mark[:k])), 0)
                self._held = data[len(data) - keep:] if keep else b""
                self._route(data[:len(data) - keep])
                return
            self._route(data[:i])
            data = data[i + len(mark):]
            if self.printing:
                job, self._print_job = bytes(self._print_job), bytearray()
                self.printing = False
                if job:
                    self.on_print_data(job)
            else:
                self.printing = self.host_print

    def _route(self, data: bytes) -> None:
        if self.printing:
            self._print_job += data
        elif data:
            super().feed(data)

    def feed_text(self, text: str) -> None:
        for ch in text:
            self._feed_char(ch)

    def _feed_char(self, ch: str) -> None:
        o = ord(ch)
        state = self.state

        # Controls are honoured in every state except string collection.
        if state not in (OSC, DCS):
            if o < 0x20 and o != 0x1b:
                self._execute(o)
                return
            if o == 0x7f:
                return
            if o == 0x1b:
                # ESC always starts a new sequence, abandoning any partial one.
                self.state = ESCAPE
                self.inter = ""
                return
            if self.c1_controls and 0x80 <= o <= 0x9f:
                self._c1(o)
                return

        if state == GROUND:
            self._print(ch)
        elif state == ESCAPE:
            self._escape(ch)
        elif state == ESC_INTER:
            if 0x20 <= o <= 0x2f:
                self.inter += ch
            else:
                self._esc_dispatch(self.inter, ch)
        elif state == CHARSET:
            self.charsets[self.charset_slot] = ch
            self.state = GROUND
        elif state == CSI_PARAM:
            if 0x30 <= o <= 0x3f:
                self.params += ch
            elif 0x20 <= o <= 0x2f:
                self.inter += ch
            elif 0x40 <= o <= 0x7e:
                self.state = GROUND
                self._csi_dispatch(self.params, self.inter, ch)
        elif state == OSC:
            if o == 0x07 or (self.c1_controls and o == 0x9c):
                self._osc_dispatch(self.osc)
                self.state = GROUND
            elif o == 0x1b:
                # ESC \ (ST) ends the string; the backslash is swallowed below.
                self._osc_dispatch(self.osc)
                self.state = ESCAPE
                self.inter = ""
            else:
                self.osc += ch
        elif state == DCS:
            # Device control strings (DECUDK, sixel, ...) are not supported yet.
            if o == 0x1b or (self.c1_controls and o == 0x9c):
                self.state = ESCAPE if o == 0x1b else GROUND
                self.inter = ""

    def _c1(self, o: int) -> None:
        mapping = {0x84: "D", 0x85: "E", 0x88: "H", 0x8d: "M", 0x8e: "N", 0x8f: "O"}
        if o == 0x9b:
            self._enter_csi()
        elif o == 0x9d:
            self.state, self.osc = OSC, ""
        elif o == 0x90:
            self.state = DCS
        elif o in mapping:
            self._esc_dispatch("", mapping[o])

    def _enter_csi(self) -> None:
        self.state = CSI_PARAM
        self.params = ""
        self.inter = ""

    # ------------------------------------------------------------ printing

    def _print(self, ch: str) -> None:
        slot = self.single_shift if self.single_shift is not None else self.gl
        self.single_shift = None
        cs = self.charsets[slot]
        if cs == "0":
            ch = DEC_GRAPHICS.get(ch, ch)
        elif cs == "A":
            ch = UK_CHARSET.get(ch, ch)
        self.screen.put_char(ch)

    def _execute(self, o: int) -> None:
        s = self.screen
        if o == 0x07:
            self.on_bell()
        elif o == 0x08:
            s.backspace()
        elif o == 0x09:
            s.tab()
        elif o in (0x0a, 0x0b, 0x0c):
            s.linefeed()
            if self.newline_mode:
                s.carriage_return()
        elif o == 0x0d:
            s.carriage_return()
        elif o == 0x0e:
            self.gl = 1
        elif o == 0x0f:
            self.gl = 0
        elif o == 0x05:
            if self.answerback:
                self.send(self.answerback)
        elif o in (0x18, 0x1a):
            self.state = GROUND  # CAN / SUB abort a sequence

    # ------------------------------------------------------------- escapes

    def _escape(self, ch: str) -> None:
        o = ord(ch)
        if ch == "[":
            self._enter_csi()
        elif ch == "]":
            self.state, self.osc = OSC, ""
        elif ch == "P":
            self.state = DCS
        elif ch in "()*+":
            self.state = CHARSET
            self.charset_slot = "()*+".index(ch)
        elif 0x20 <= o <= 0x2f:
            self.inter = ch
            self.state = ESC_INTER
        else:
            self._esc_dispatch("", ch)

    def _esc_dispatch(self, inter: str, ch: str) -> None:
        self.state = GROUND
        s = self.screen
        if inter == "#":
            if ch == "8":
                s.fill_with("E")
            return
        if inter:
            return
        if ch == "7":
            s.save_cursor(charsets=tuple(self.charsets), gl=self.gl)
        elif ch == "8":
            saved = s.restore_cursor()
            if saved.charsets:
                self.charsets = list(saved.charsets)
                self.gl = saved.gl
        elif ch == "D":
            s.linefeed()
        elif ch == "E":
            s.carriage_return()
            s.linefeed()
        elif ch == "M":
            s.reverse_index()
        elif ch == "H":
            s.set_tabstop()
        elif ch == "c":
            self.reset()
        elif ch == "=":
            self.app_keypad = True
        elif ch == ">":
            self.app_keypad = False
        elif ch == "N":
            self.single_shift = 2
        elif ch == "O":
            self.single_shift = 3
        elif ch == "n":
            self.gl = 2
        elif ch == "o":
            self.gl = 3
        elif ch == "Z":
            self.send(self.primary_da)
        # ESC \ (string terminator) and anything unknown: ignore.

    def _osc_dispatch(self, data: str) -> None:
        num, _, text = data.partition(";")
        if num in ("0", "2"):
            self.screen.title = text
            self.screen.dirty = True

    # ----------------------------------------------------------------- CSI

    @staticmethod
    def _parse_params(raw: str) -> list[int]:
        out = []
        for part in raw.split(";") if raw else []:
            part = part.split(":")[0]
            out.append(int(part) if part.isdigit() else 0)
        return out

    def _csi_dispatch(self, raw: str, inter: str, final: str) -> None:
        s = self.screen
        private = ""
        if raw and raw[0] in "?<=>":
            private, raw = raw[0], raw[1:]
        p = self._parse_params(raw)

        def arg(i: int = 0, default: int = 1) -> int:
            v = p[i] if i < len(p) else 0
            return v if v else default

        if inter == "!" and final == "p":       # DECSTR soft reset
            s.insert_mode = False
            s.origin_mode = False
            s.autowrap = True
            s.cursor_visible = True
            s.attr = Attr()
            s.top, s.bottom = 0, s.rows - 1
            self.app_cursor = self.app_keypad = False
            return
        if inter:
            return                               # DECSCUSR etc.: ignored

        if private == "?":
            if final in "hl":
                for mode in p:
                    self._dec_mode(mode, final == "h")
            return
        if private == ">":
            if final == "c":
                self.send(self.secondary_da)
            return
        if private == "=":
            if self.sco_private:
                self._sco_private(p, final)
            return

        if final == "A":
            s.cursor_up(arg())
        elif final in "Be":
            s.cursor_down(arg())
        elif final in "Ca":
            s.cursor_forward(arg())
        elif final == "D":
            s.cursor_back(arg())
        elif final == "E":
            s.cursor_down(arg())
            s.carriage_return()
        elif final == "F":
            s.cursor_up(arg())
            s.carriage_return()
        elif final in "G`":
            s.cursor_col(arg() - 1)
        elif final in "Hf":
            s.cursor_to(arg(0) - 1, arg(1) - 1)
        elif final == "d":
            s.cursor_row(arg() - 1)
        elif final == "I":
            s.tab(arg())
        elif final == "Z":
            s.back_tab(arg())
        elif final == "J":
            s.erase_in_display(arg(0, 0))
        elif final == "K":
            s.erase_in_line(arg(0, 0))
        elif final == "L":
            s.insert_lines(arg())
        elif final == "M":
            s.delete_lines(arg())
        elif final == "P":
            s.delete_chars(arg())
        elif final == "@":
            s.insert_chars(arg())
        elif final == "X":
            s.erase_chars(arg())
        elif final == "S":
            s.scroll_up(arg())
        elif final == "T":
            s.scroll_down(arg())
        elif final == "b":
            prev = s.lines[s.y][s.x - 1].char if s.x > 0 else " "
            s.write_text(prev * arg())
        elif final == "m":
            self._sgr(raw)
        elif final == "r":
            s.set_margins(arg(0) - 1, arg(1, s.rows) - 1)
        elif final == "s":
            s.save_cursor(charsets=tuple(self.charsets), gl=self.gl)
        elif final == "u":
            s.restore_cursor()
        elif final == "g":
            mode = arg(0, 0)
            if mode == 0:
                s.clear_tabstop()
            elif mode == 3:
                s.clear_tabstop(all_stops=True)
        elif final == "c":
            if arg(0, 0) == 0:
                self.send(self.primary_da)
        elif final == "n":
            if arg(0, 0) == 5:
                self.send("\x1b[0n")
            elif arg(0, 0) == 6:
                row = s.y - (s.top if s.origin_mode else 0)
                self.send(f"\x1b[{row + 1};{s.x + 1}R")
        elif final in "hl":
            on = final == "h"
            for mode in p:
                if mode == 4:
                    s.insert_mode = on
                elif mode == 20:
                    self.newline_mode = on
        # Media copy (i) and anything else: ignored for now.

    def _dec_mode(self, mode: int, on: bool) -> None:
        s = self.screen
        if mode == 1:
            self.app_cursor = on
        elif mode == 5:
            s.reverse_screen = on
            s.dirty = True
        elif mode == 6:
            s.origin_mode = on
            s.cursor_to(0, 0)
        elif mode == 7:
            s.autowrap = on
        elif mode == 25:
            s.cursor_visible = on
            s.dirty = True
        elif mode in (47, 1047):
            s.enter_alt_screen() if on else s.leave_alt_screen()
        elif mode == 1048:
            s.save_cursor() if on else s.restore_cursor()
        elif mode == 1049:
            if on:
                s.save_cursor()
                s.enter_alt_screen()
                s.erase_in_display(2)
            else:
                s.leave_alt_screen()
                s.restore_cursor()
        elif mode == 66:
            self.app_keypad = on
        elif mode == 2004:
            self.bracketed_paste = on

    def _sgr(self, raw: str) -> None:
        s = self.screen
        parts = raw.split(";") if raw else ["0"]
        vals = [int(x.split(":")[0]) if x.split(":")[0].isdigit() else 0 for x in parts]
        a = s.attr
        i = 0
        while i < len(vals):
            v = vals[i]
            if v == 0:
                a = Attr()
            elif v == 1:
                a = a.with_(bold=True)
            elif v == 2:
                a = a.with_(dim=True)
            elif v == 3:
                a = a.with_(italic=True)
            elif v == 4:
                a = a.with_(underline=True)
            elif v in (5, 6):
                a = a.with_(blink=True)
            elif v == 7:
                a = a.with_(reverse=True)
            elif v == 8:
                a = a.with_(invisible=True)
            elif v == 22:
                a = a.with_(bold=False, dim=False)
            elif v == 23:
                a = a.with_(italic=False)
            elif v == 24:
                a = a.with_(underline=False)
            elif v == 25:
                a = a.with_(blink=False)
            elif v == 27:
                a = a.with_(reverse=False)
            elif v == 28:
                a = a.with_(invisible=False)
            elif 30 <= v <= 37:
                a = a.with_(fg=v - 30)
            elif v == 39:
                a = a.with_(fg=None)
            elif 40 <= v <= 47:
                a = a.with_(bg=v - 40)
            elif v == 49:
                a = a.with_(bg=None)
            elif 90 <= v <= 97:
                a = a.with_(fg=v - 90 + 8)
            elif 100 <= v <= 107:
                a = a.with_(bg=v - 100 + 8)
            elif v in (38, 48) and i + 1 < len(vals):
                key = "fg" if v == 38 else "bg"
                if vals[i + 1] == 5 and i + 2 < len(vals):
                    a = a.with_(**{key: vals[i + 2] & 0xFF})
                    i += 2
                elif vals[i + 1] == 2 and i + 4 < len(vals):
                    a = a.with_(**{key: tuple(c & 0xFF for c in vals[i + 2:i + 5])})
                    i += 4
            i += 1
        s.attr = a

    def _sco_private(self, p: list[int], final: str) -> None:
        # SCO console: CSI = Pn F / G set foreground / background (PC colour order).
        if not p:
            return
        n = p[0] & 0x0F
        colour = PC_TO_ANSI[n & 7] + (8 if n & 8 else 0)
        if final == "F":
            self.screen.attr = self.screen.attr.with_(fg=colour)
        elif final == "G":
            self.screen.attr = self.screen.attr.with_(bg=colour)


class VT100(VTEmulation):
    name = "vt100"
    term_type = "vt100"
    telnet_type = "VT100"
    keymap = "vt100"
    primary_da = "\x1b[?1;2c"
    secondary_da = ""


class VT220(VTEmulation):
    pass


class AnsiSCO(VTEmulation):
    name = "ansi"
    term_type = "scoansi"
    telnet_type = "ANSI"
    keymap = "ansi"
    sco_private = True
    primary_da = "\x1b[?1;2c"


class LinuxConsole(VTEmulation):
    name = "linux"
    term_type = "linux"
    telnet_type = "LINUX"
    keymap = "linux"
    primary_da = "\x1b[?6c"


class Xterm(VTEmulation):
    name = "xterm"
    term_type = "xterm-256color"
    telnet_type = "XTERM"
    keymap = "xterm"
    primary_da = "\x1b[?62;22c"
    secondary_da = "\x1b[>0;276;0c"


class VT320(VTEmulation):
    name = "vt320"
    term_type = "vt320"
    telnet_type = "VT320"
    primary_da = "\x1b[?63;1;2;6;7;8;9c"


class VT420(VTEmulation):
    name = "vt420"
    term_type = "vt420"
    telnet_type = "VT420"
    primary_da = "\x1b[?64;1;2;6;7;8;9c"


class AT386(AnsiSCO):
    # UNVERIFIED: treated as SCO ANSI with the AT386 terminal name.
    name = "at386"
    term_type = "at386"
    telnet_type = "AT386"
