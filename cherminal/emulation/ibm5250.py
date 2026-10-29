"""IBM 5250 display station (TN5250, RFC 1205/2877/4777) for IBM i (AS/400).

Like a 3270, a 5250 is block mode: the host writes a screen and a format
table of input fields, the user edits the fields locally, and an AID key
(Enter, F1-F24, Roll Up/Down, Help, ...) sends the cursor position and the
changed fields back. Typing never goes straight to the host; the session
hands keys to :meth:`type_text` and :meth:`do_action`.

Records arrive framed by the Telnet layer as for TN3270 (0xFF doubled, each
record ended by IAC EOR). Each record is a 5250 GDS record: a 10-byte header
(length, record type 0x12A0, flow type, header length 4, flags, reserved,
opcode) and then a data stream of ESC-prefixed commands. Each :meth:`reply`
call sends one record; the Telnet layer adds the IAC EOR.

The display buffer holds EBCDIC bytes; bytes 0x20-0x3F are display
attributes, which take a screen position, show as a blank and colour what
follows. Non-display (password) fields are rendered as blanks so they never
reach the screen, the clipboard, search or a printout.

References: IBM SC30-3533 "5494 Remote Control Unit Functions Reference"
(the 5250 data stream), RFC 1205 (TN5250), RFC 2877 and RFC 4777 (TN5250
enhancements, NEW-ENVIRON device names).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..screen import DEFAULT_ATTR, Attr, Cell
from .base import Emulation, InputField, row_spans
from .ibm3270 import EOR, IAC, MAX_RECORD

# GDS record header.
RECORD_TYPE = b"\x12\xa0"
HEADER_LEN = 10
FLAG_ERR, FLAG_ATN, FLAG_SRQ, FLAG_TRQ, FLAG_HLP = 0x80, 0x40, 0x04, 0x02, 0x01
(OP_NOOP, OP_INVITE, OP_OUTPUT, OP_PUT_GET, OP_SAVE, OP_RESTORE, OP_READ_IMMEDIATE,
 _OP_RESERVED, OP_READ_SCREEN, _OP_RESERVED2, OP_CANCEL_INVITE, OP_MSG_ON, OP_MSG_OFF) = range(13)

# Commands, each after an ESC.
ESC = 0x04
CMD_CLEAR_UNIT, CMD_CLEAR_UNIT_ALT, CMD_CLEAR_FORMAT = 0x40, 0x20, 0x50
CMD_WTD, CMD_WEC, CMD_WEC_WINDOW = 0x11, 0x21, 0x22
CMD_READ_INPUT, CMD_READ_MDT, CMD_READ_MDT_ALT = 0x42, 0x52, 0x82
CMD_READ_SCREEN, CMD_READ_IMMEDIATE, CMD_READ_IMMEDIATE_ALT = 0x62, 0x72, 0x83
CMD_SAVE, CMD_RESTORE, CMD_ROLL, CMD_WSF = 0x02, 0x12, 0x23, 0xF3
READS = (CMD_READ_INPUT, CMD_READ_MDT, CMD_READ_MDT_ALT)

# Write To Display orders.
SOH, RA, EA, TD, SBA, WEA, IC, MC, WDSF, SF = (0x01, 0x02, 0x03, 0x10, 0x11, 0x12, 0x13,
                                               0x14, 0x15, 0x1D)

# Attention identifiers.
AID_NONE, AID_ENTER, AID_HELP, AID_ROLL_DOWN, AID_ROLL_UP = 0x00, 0xF1, 0xF3, 0xF4, 0xF5
AID_PRINT, AID_RECORD_BS, AID_CLEAR, AID_SF = 0xF6, 0xF8, 0xBD, 0x88
AID_F = {**{i: 0x30 + i for i in range(1, 13)}, **{i: 0xB0 + i - 12 for i in range(13, 25)}}
NO_DATA_AIDS = {AID_HELP, AID_PRINT, AID_RECORD_BS, AID_CLEAR}
NAMED_AIDS = {"enter": AID_ENTER, "help": AID_HELP, "roll-down": AID_ROLL_DOWN,
              "roll-up": AID_ROLL_UP, "print": AID_PRINT, "record-backspace": AID_RECORD_BS,
              "clear": AID_CLEAR}

# Characters with a meaning of their own in an input field.
NULL, BLANK, ZERO, MINUS, DUP, FIELD_MARK = 0x00, 0x40, 0xF0, 0x60, 0x1C, 0x1E

# Field format word (FFW) bits.
FFW_BYPASS, FFW_DUP, FFW_MDT = 0x2000, 0x1000, 0x0800
FFW_AUTO_ENTER, FFW_FER, FFW_MONOCASE, FFW_ME = 0x0080, 0x0040, 0x0020, 0x0008
SHIFT_ALPHA_ONLY, SHIFT_NUMERIC_ONLY, SHIFT_DIGITS_ONLY, SHIFT_SIGNED = 1, 3, 5, 7
ADJUST_ZERO, ADJUST_BLANK, MANDATORY_FILL = 5, 6, 7

# Display attribute bits (0x20-0x3F). Lowest three bits all on = non-display.
A_REVERSE, A_HIGH, A_UNDERLINE, A_BLINK, A_COLSEP, A_NONDISPLAY = 1, 2, 4, 8, 0x10, 7
# Colour displays turn intensity / blink / column separator into colours
# (palette index; bright variants read well on a dark background).
GREEN, WHITE, RED, TURQUOISE, YELLOW, PINK, BLUE = 10, 15, 9, 14, 11, 13, 12
COLORS = {0x00: GREEN, 0x02: WHITE, 0x08: RED, 0x0A: RED, 0x10: TURQUOISE, 0x12: YELLOW,
          0x18: PINK, 0x1A: BLUE}

VALID_CHARS = {
    SHIFT_ALPHA_ONLY: set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz,.- "),
    SHIFT_NUMERIC_ONLY: set("0123456789+-,. "),
    SHIFT_DIGITS_ONLY: set("0123456789"),
    SHIFT_SIGNED: set("0123456789"),
}


@dataclass
class Field:
    """One entry of the format table: an input field."""
    start: int                   # first data position
    length: int
    ffw: int
    attr: int | None = None
    fcw: list[int] = field(default_factory=list)

    @property
    def end(self) -> int:
        return self.start + self.length - 1

    @property
    def shift(self) -> int:
        return (self.ffw >> 8) & 0x07

    @property
    def adjust(self) -> int:
        return self.ffw & 0x07

    @property
    def signed(self) -> bool:
        return self.shift == SHIFT_SIGNED

    @property
    def bypass(self) -> bool:
        return bool(self.ffw & FFW_BYPASS)

    @property
    def mdt(self) -> bool:
        return bool(self.ffw & FFW_MDT)

    @property
    def data(self) -> range:
        """Positions the user types in (a signed numeric field keeps its last for the sign)."""
        return range(self.start, self.end if self.signed and self.length > 1 else self.end + 1)


class IBM5250(Emulation):
    """IBM 3179 model 2: 24 x 80 colour display station."""

    name = "ibm3179-2"
    term_type = telnet_type = "IBM-3179-2"
    keymap = "ibm5250"
    family = "ibm5250"
    block_mode = True       # keys are edited locally and sent by AID keys
    fixed_size = True       # the host sets the grid; the window scales to it
    color = True
    alternate = (80, 24)    # cols, rows for Clear Unit Alternate

    def __init__(self, screen, reply=None, encoding: str = "cp037", answerback: str = ""):
        super().__init__(screen, reply, encoding=encoding, answerback=answerback)
        screen.scrollback_limit = 0
        self._rec = bytearray()
        self._rec_dropped = False
        self._iac = False
        self.on_status = lambda: None
        self.reset()

    # ----------------------------------------------------------- state

    def reset(self) -> None:
        """Power-on: 24 x 80, empty buffer, no fields, keyboard unlocked."""
        self._clear(80, 24)
        self.locked = False          # X SYSTEM: waiting for the host
        self.inhibited = ""          # operator error or host error message; Reset clears
        self.insert = False
        self.msg_wait = False
        self.message = ""
        self._render()

    def _clear(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.buf = [NULL] * (cols * rows)
        self.fields: list[Field] = []
        self.cursor = 0
        self.home_pos: int | None = None      # IC address: where Home goes
        self._pending_ic: int | None = None   # cursor position for the next unlock
        self.read_cmd: int | None = None      # Read Input / MDT command waiting for an AID
        self.error_row = rows - 1
        self.cmd_mask = 0                     # SOH: F keys (bit 0 = F1) that return no data
        self._error_line: tuple[int, list[int]] | None = None
        self._fer_at: int | None = None       # field exit required at this position
        self.screen.resize(cols, rows)

    @property
    def size(self) -> int:
        return self.cols * self.rows

    @property
    def status(self) -> str:
        """Operator information area, shown in the status bar."""
        parts = []
        if self.inhibited:
            parts.append(f"X II {self.inhibited} (Reset)")
        elif self.locked:
            parts.append("X SYSTEM")
        if self.insert:
            parts.append("Insert")
        if self.msg_wait:
            parts.append("Message waiting")
        if self.message:
            parts.append(self.message)
        r, c = divmod(self.cursor, self.cols)
        parts.append(f"{r + 1:03d}/{c + 1:03d}")
        return "  ".join(parts)

    def notice(self, text: str) -> None:
        self.message = text
        self.on_status()

    # ------------------------------------------------------- fields

    def field_at(self, pos: int) -> Field | None:
        for f in self.fields:
            if f.start <= pos <= f.end:
                return f
        return None

    def input_fields(self) -> list[InputField]:
        out = []
        for f in self._input_fields():
            hidden = f.attr is not None and f.attr & A_NONDISPLAY == A_NONDISPLAY
            out += row_spans(list(range(f.start, f.end + 1)), self.cols,
                             numeric=f.shift in (SHIFT_NUMERIC_ONLY, SHIFT_DIGITS_ONLY,
                                                 SHIFT_SIGNED),
                             hidden=hidden, modified=f.mdt)
        return out

    def click(self, pos: int) -> bool:
        f = self.field_at(pos)
        if self.locked or self.inhibited or f is None or f.bypass:
            return False
        self.cursor = min(pos, f.data[-1]) if len(f.data) else f.start
        self._fer_at = None
        self._render()
        return True

    def _input_fields(self) -> list[Field]:
        return [f for f in self.fields if not f.bypass]

    def _next_field(self, pos: int) -> int:
        """First position of the next non-bypass field after ``pos`` (wraps)."""
        fields = self._input_fields()
        if not fields:
            return pos
        for f in fields:
            if f.start > pos:
                return f.start
        return fields[0].start

    def _prev_field(self, pos: int) -> int:
        f = self.field_at(pos)
        if f is not None and not f.bypass and pos != f.start:
            return f.start                    # start of this field first
        fields = self._input_fields()
        if not fields:
            return pos
        for f in reversed(fields):
            if f.start < pos:
                return f.start
        return fields[-1].start

    def _home(self) -> int:
        if self.home_pos is not None:
            return self.home_pos
        fields = self._input_fields()
        return fields[0].start if fields else 0

    # --------------------------------------------------------- incoming

    def feed(self, data: bytes) -> None:
        for b in data:
            if self._iac:
                self._iac = False
                if b == EOR:
                    rec, self._rec = bytes(self._rec), bytearray()
                    if rec and not self._rec_dropped:
                        self.process(rec)
                    self._rec_dropped = False
                    continue
                self._keep(b)                # IAC IAC -> one 0xFF
            elif b == IAC:
                self._iac = True
            else:
                self._keep(b)

    def _keep(self, b: int) -> None:
        if len(self._rec) >= MAX_RECORD:
            # Oversized record: stop holding it and drop it at its EOR.
            self._rec.clear()
            self._rec_dropped = True
        self._rec.append(b)

    def feed_text(self, text: str) -> None:
        pass  # 5250 data is binary; see feed()

    def process(self, rec: bytes) -> None:
        """Run one Telnet record: one or more GDS records."""
        while len(rec) >= HEADER_LEN and rec[2:4] == RECORD_TYPE:
            length = int.from_bytes(rec[0:2], "big")
            if not HEADER_LEN <= length <= len(rec):
                length = len(rec)
            var = max(rec[6], 4)               # variable header length, normally 4
            flags, opcode = rec[7], rec[6 + var - 1] if 6 + var <= length else OP_NOOP
            self._record(opcode, flags, rec[6 + var:length])
            rec = rec[length:]
        self._render()

    def _record(self, opcode: int, flags: int, data: bytes) -> None:
        if opcode == OP_CANCEL_INVITE:
            self.read_cmd = None
            self.locked = True
            self._send(OP_CANCEL_INVITE, b"")
        elif opcode == OP_MSG_ON:
            self.msg_wait = True
        elif opcode == OP_MSG_OFF:
            self.msg_wait = False
        elif opcode == OP_SAVE:
            self._send(OP_SAVE, self._save_data())
        elif opcode == OP_READ_IMMEDIATE:
            self._send_fields(AID_NONE, CMD_READ_IMMEDIATE)
        elif opcode == OP_READ_SCREEN:
            self._send(OP_NOOP, bytes(self.buf))
        if opcode in (OP_NOOP, OP_INVITE, OP_OUTPUT, OP_PUT_GET, OP_RESTORE, OP_SAVE):
            self._stream(data)

    def _addr(self, row: int, col: int) -> int:
        """Buffer position of a 1-based row and column, kept on the screen."""
        row = min(max(row, 1), self.rows)
        col = min(max(col, 1), self.cols)
        return (row - 1) * self.cols + col - 1

    def _stream(self, data: bytes) -> None:
        i, n = 0, len(data)
        while i < n:
            if data[i] != ESC or i + 1 >= n:
                i += 1                           # stray byte between commands
                continue
            cmd, i = data[i + 1], i + 2
            if cmd == CMD_CLEAR_UNIT:
                self._clear_unit(80, 24)
            elif cmd == CMD_CLEAR_UNIT_ALT:
                i += 1                           # parameter byte
                self._clear_unit(*self.alternate)
            elif cmd == CMD_CLEAR_FORMAT:
                self.fields = []
                self.read_cmd = None
                self.locked = True
            elif cmd == CMD_WTD:
                cc1, cc2 = (data[i:i + 2] + b"\0\0")[:2]
                i = self._wtd(data, i + 2, cc1, cc2)
            elif cmd in (CMD_WEC, CMD_WEC_WINDOW):
                i = self._wec(data, i + (2 if cmd == CMD_WEC_WINDOW else 0))
            elif cmd in READS:
                cc1, cc2 = (data[i:i + 2] + b"\0\0")[:2]
                i += 2
                self._cc1(cc1)
                self.read_cmd = cmd
                self._unlock()
                self._cc2(cc2)
            elif cmd in (CMD_READ_IMMEDIATE, CMD_READ_IMMEDIATE_ALT):
                self._send_fields(AID_NONE, cmd)
            elif cmd == CMD_READ_SCREEN:
                self._send(OP_NOOP, bytes(self.buf))
            elif cmd == CMD_SAVE:
                self._send(OP_SAVE, self._save_data())
            elif cmd == CMD_RESTORE:
                pass                             # the saved data stream follows
            elif cmd == CMD_ROLL and i + 3 <= n:
                self._roll(data[i], data[i + 1], data[i + 2])
                i += 3
            elif cmd == CMD_WSF:
                i = self._wsf(data, i)
            # Anything else is skipped up to the next ESC.

    def _clear_unit(self, cols: int, rows: int) -> None:
        self._clear(cols, rows)
        self.inhibited = ""
        self.insert = False
        self.locked = True

    # Write To Display ------------------------------------------------

    def _cc1(self, cc1: int) -> None:
        """Control character 1: lock the keyboard, reset MDTs, null fields."""
        top = cc1 & 0xE0
        if not top:
            return
        self.locked = True
        nonbypass = self._input_fields()
        if top in (0x80, 0xA0):
            for f in nonbypass:
                if f.mdt:
                    self._null(f)
        elif top in (0xC0, 0xE0):
            for f in nonbypass:
                self._null(f)
        if top in (0x40, 0xA0, 0xC0):
            for f in nonbypass:
                f.ffw &= ~FFW_MDT
        elif top in (0x60, 0xE0):
            for f in self.fields:
                f.ffw &= ~FFW_MDT

    def _cc2(self, cc2: int) -> None:
        """Control character 2: message light, alarm, keyboard unlock."""
        if cc2 & 0x01:
            self.msg_wait = True
        if cc2 & 0x02:
            self.msg_wait = False
        if cc2 & 0x04:
            self.on_bell()
        if cc2 & 0x08:
            self._unlock()

    def _unlock(self) -> None:
        if self.locked or self._pending_ic is not None:
            self.cursor = self._pending_ic if self._pending_ic is not None else self._home()
        self._pending_ic = None
        self.locked = False

    def _null(self, f: Field) -> None:
        for p in range(f.start, f.end + 1):
            self.buf[p] = NULL

    def _put(self, pos: int, b: int) -> None:
        # Control codes other than null, Dup and Field Mark show as nulls.
        self.buf[pos % self.size] = b if b >= 0x20 or b in (DUP, FIELD_MARK) else NULL

    def _wtd(self, data: bytes, i: int, cc1: int, cc2: int) -> int:
        self._cc1(cc1)
        ba = self.cursor
        n = len(data)
        ic = None
        while i < n:
            b = data[i]
            if b == ESC:
                break
            if b == SOH and i + 1 < n:
                ln = min(data[i + 1], 7)
                self._soh(data[i + 2:i + 2 + ln])
                i += 2 + ln
            elif b == RA and i + 3 < n:
                stop = self._addr(data[i + 1], data[i + 2])
                while ba <= stop:
                    self._put(ba, data[i + 3])
                    ba += 1
                i += 4
            elif b == EA and i + 3 < n:
                stop = self._addr(data[i + 1], data[i + 2])
                while ba <= stop:
                    self.buf[ba] = NULL
                    ba += 1
                i += 3 + max(data[i + 3], 1)     # the length byte counts itself
            elif b == TD and i + 2 < n:
                ln = int.from_bytes(data[i + 1:i + 3], "big")
                for c in data[i + 3:i + 3 + ln]:
                    self._put(ba, c)
                    ba = (ba + 1) % self.size
                i += 3 + ln
            elif b in (SBA, IC, MC) and i + 2 < n:
                pos = self._addr(data[i + 1], data[i + 2])
                if b == SBA:
                    ba = pos
                else:
                    ic = pos
                    if b == IC:
                        self.home_pos = pos
                i += 3
            elif b == WEA:
                i += 3                           # extended attributes: not shown
            elif b == WDSF and i + 2 < n:
                i += 1 + max(int.from_bytes(data[i + 1:i + 3], "big"), 2)
            elif b == SF:
                i, ba = self._sf(data, i + 1, ba)
            else:
                self._put(ba, b)
                ba = (ba + 1) % self.size
                i += 1
            ba %= self.size
        if ic is not None:
            self._pending_ic = ic
            if not self.locked:
                self.cursor = ic
                self._pending_ic = None
        self._cc2(cc2)
        return i

    def _soh(self, header: bytes) -> None:
        """Start of Header: clears the format table; error line and command keys."""
        self.fields = []
        self.home_pos = None
        self.locked = True
        self.error_row = self.rows - 1
        if len(header) >= 4 and 1 <= header[3] <= self.rows:
            self.error_row = header[3] - 1
        self.cmd_mask = int.from_bytes(header[4:7], "big") if len(header) >= 7 else 0

    def _sf(self, data: bytes, i: int, ba: int) -> tuple[int, int]:
        """Start of Field: [FFW [FCW...]] attribute length. Returns (i, address)."""
        n = len(data)
        ffw = None
        fcw = []
        if i + 1 < n and data[i] & 0xC0 == 0x40:
            ffw = (data[i] << 8) | data[i + 1]
            i += 2
            while i + 1 < n and data[i] & 0xC0 == 0x80:
                fcw.append((data[i] << 8) | data[i + 1])
                i += 2
        attr = None
        if i < n and 0x20 <= data[i] <= 0x3F:
            attr = data[i]
            i += 1
        length = int.from_bytes(data[i:i + 2], "big")
        i += 2
        if attr is not None:
            self.buf[ba] = attr                 # the attribute takes the position before the field
            ba = (ba + 1) % self.size
        if ffw is not None and length:
            length = min(length, self.size - ba)
            self.fields = [f for f in self.fields if f.start != ba]
            self.fields.append(Field(ba, length, ffw, attr, fcw))
            self.fields.sort(key=lambda f: f.start)
        return i, ba

    def _wec(self, data: bytes, i: int) -> int:
        """Write Error Code: a message on the error line; input inhibited until Reset."""
        row = self.error_row
        line = slice(row * self.cols, (row + 1) * self.cols)
        if self._error_line is None:
            self._error_line = (row, self.buf[line])
        ba = row * self.cols
        n = len(data)
        while i < n and data[i] != ESC:
            b = data[i]
            if b in (IC, MC, SBA) and i + 2 < n:
                if b != SBA:
                    self.cursor = self._addr(data[i + 1], data[i + 2])
                i += 3
                continue
            self._put(ba, b)
            ba = (ba + 1) % self.size
            i += 1
        text = bytes(c if c >= 0x40 else BLANK for c in self.buf[line])
        self.inhibited = " ".join(text.decode(self.encoding, errors="replace").split()) \
            or "Error"
        self.on_bell()
        return i

    def _roll(self, how: int, top: int, bottom: int) -> None:
        count = how & 0x1F
        top, bottom = min(max(top, 1), self.rows) - 1, min(max(bottom, 1), self.rows) - 1
        if not count or top > bottom:
            return
        rows = [self.buf[r * self.cols:(r + 1) * self.cols] for r in range(top, bottom + 1)]
        blank = [[NULL] * self.cols for _ in range(min(count, len(rows)))]
        if how & 0x80:                          # roll down
            rows = (blank + rows)[:len(rows)]
        else:
            rows = (rows + blank)[-len(rows):]
        for r, line in zip(range(top, bottom + 1), rows):
            self.buf[r * self.cols:(r + 1) * self.cols] = line

    def _wsf(self, data: bytes, i: int) -> int:
        """Write Structured Field: answers the 5250 Query; skips the rest."""
        n = len(data)
        while i + 4 <= n and data[i] != ESC:
            length = int.from_bytes(data[i:i + 2], "big")
            if length < 4:
                return n
            if data[i + 2] == 0xD9 and data[i + 3] == 0x70:
                self._send(OP_NOOP, self._query_reply())
            i += length
        return i

    def _query_reply(self) -> bytes:
        """Describe the display station, as a 5494-attached 5250 emulator would."""
        _, dev, model = (self.telnet_type.split("-") + ["", ""])[:3]
        wide = self.alternate == (132, 27)
        body = (bytes([0xD9, 0x70, 0x80])
                + b"\x06\x00"                    # controller: another 5250 emulator
                + b"\x01\x01\x00"                # code level
                + bytes(16)
                + b"\x01"                        # a display
                + dev[:4].rjust(4, "0").encode("cp037")
                + model[:3].rjust(3, "0").encode("cp037")
                + b"\x02\x00\x00"                # standard keyboard
                + b"\x00\x61\x50\x00"            # serial number
                + b"\x01\x00"                    # up to 256 input fields
                + b"\x00\x00\x00"
                + bytes([0x01, 0x30 if wide else 0x10, 0, 0, 0])   # 27x132 capable or 24x80
                + bytes(7))
        return b"\x00\x00" + bytes([AID_SF]) + (len(body) + 2).to_bytes(2, "big") + body

    # ----------------------------------------------------------- replies

    def _send(self, opcode: int, data: bytes, flags: int = 0) -> None:
        header = ((len(data) + HEADER_LEN).to_bytes(2, "big") + RECORD_TYPE
                  + bytes([0x00, 0x00, 0x04, flags, 0x00, opcode]))
        self.reply(header + data)

    def _field_bytes(self, f: Field, cmd: int) -> bytes:
        vals = [self.buf[p] for p in f.data]
        if f.signed and f.length > 1 and self.buf[f.end] == MINUS:
            # Negative: the last digit carries the sign in its zone.
            for k in range(len(vals) - 1, -1, -1):
                if 0xF0 <= vals[k] <= 0xF9:
                    vals[k] = 0xD0 | (vals[k] & 0x0F)
                    break
        if cmd in (CMD_READ_MDT, CMD_READ_MDT_ALT, CMD_READ_IMMEDIATE_ALT):
            while vals and vals[-1] == NULL:     # trailing nulls are not sent
                vals.pop()
        if cmd not in (CMD_READ_MDT_ALT, CMD_READ_IMMEDIATE_ALT):
            vals = [BLANK if v == NULL else v for v in vals]
        return bytes(vals)

    def _send_fields(self, aid: int, cmd: int | None) -> None:
        cmd = cmd or CMD_READ_MDT
        r, c = divmod(self.cursor, self.cols)
        out = bytearray([r + 1, c + 1, aid])
        send = aid not in NO_DATA_AIDS
        for num, code in AID_F.items():
            if aid == code and self.cmd_mask >> (num - 1) & 1:
                send = False                     # a "command attention" key: no data
        everything = cmd in (CMD_READ_INPUT, CMD_READ_IMMEDIATE)
        if everything and not any(f.mdt for f in self.fields):
            send = False                         # nothing changed: cursor and AID only
        if send:
            for f in self.fields:
                if everything:
                    out += self._field_bytes(f, cmd)
                elif f.mdt:
                    fr, fc = divmod(f.start, self.cols)
                    out += bytes([SBA, fr + 1, fc + 1]) + self._field_bytes(f, cmd)
        self._send(OP_PUT_GET, bytes(out))

    def _save_data(self) -> bytes:
        """A data stream that redraws this screen, for the host to keep and send back."""
        out = bytearray([ESC, CMD_CLEAR_UNIT] if (self.cols, self.rows) == (80, 24)
                        else [ESC, CMD_CLEAR_UNIT_ALT, 0x00])
        unlocked = not self.locked and self.read_cmd is None
        out += bytes([ESC, CMD_WTD, 0x00, 0x08 if unlocked else 0x00])
        out += bytes([SOH, 7, 0, 0, 0, self.error_row + 1]) + self.cmd_mask.to_bytes(3, "big")
        out += bytes([SBA, 1, 1])
        starts = {f.start: f for f in self.fields}
        for p, b in enumerate(self.buf):
            f = starts.get(p)
            if f is not None:                    # SF without attribute: the byte before is it
                out.append(SF)
                out += f.ffw.to_bytes(2, "big")
                for w in f.fcw:
                    out += w.to_bytes(2, "big")
                out += f.length.to_bytes(2, "big")
            out.append(b)
        r, c = divmod(self.cursor, self.cols)
        out += bytes([IC, r + 1, c + 1])
        if self.read_cmd is not None:
            out += bytes([ESC, self.read_cmd, 0x00, 0x00])
        return bytes(out)

    # -------------------------------------------------------- keyboard

    def _error(self, reason: str) -> bool:
        """An operator error: input is inhibited until Reset, as on a real 5250."""
        self.inhibited = reason
        self.on_bell()
        self._render()
        return False

    def _can_type(self) -> bool:
        if self.inhibited:
            self.on_bell()
            return False
        if self.locked:
            self.message = "Wait for the host"
            self.on_bell()
            return False
        return True

    def type_text(self, text: str) -> None:
        for ch in text:
            if ch in "\r\n":
                self.do_action("newline")
            elif ch == "\t":
                self.do_action("tab")
            elif not self._type_char(ch):
                break
        self._render()

    def _type_char(self, ch: str) -> bool:
        if not self._can_type():
            return False
        pos = self.cursor
        f = self.field_at(pos)
        if f is None or f.bypass:
            return self._error("Cursor in protected area")
        if pos not in f.data:
            return self._error("Cursor in sign position")
        if self._fer_at == pos:
            return self._error("Field Exit key required")
        allowed = VALID_CHARS.get(f.shift)
        if allowed is not None and ch not in allowed:
            return self._error({SHIFT_ALPHA_ONLY: "Alphabetic only field",
                                SHIFT_NUMERIC_ONLY: "Numeric only field"}.get(
                f.shift, "Digits only field"))
        if f.ffw & FFW_MONOCASE:
            ch = ch.upper()
        try:
            code = ch.encode(self.encoding)
        except UnicodeEncodeError:
            return self._error("Character not in the host's code page")
        if len(code) != 1 or code[0] < 0x40:
            return self._error("Character not in the host's code page")
        if not self._store(f, pos, code[0]):
            return False
        self._advance(f, pos)
        return True

    def _store(self, f: Field, pos: int, code: int) -> bool:
        span = list(f.data)
        if self.insert:
            tail = span[span.index(pos):]
            if self.buf[tail[-1]] not in (NULL, BLANK):
                return self._error("No room to insert")
            for a, b in zip(reversed(tail[1:]), reversed(tail[:-1])):
                self.buf[a] = self.buf[b]
        self.buf[pos] = code
        self.message = ""
        f.ffw |= FFW_MDT
        return True

    def _advance(self, f: Field, pos: int) -> None:
        """Cursor after a character was typed at ``pos``."""
        if pos != f.data[-1]:
            self.cursor = pos + 1
        elif f.ffw & FFW_FER:
            self._fer_at = pos                   # stay; Field Exit (or Enter) moves on
        elif f.ffw & FFW_AUTO_ENTER:
            self._exit(f, False)
            self._aid(AID_ENTER)
        else:
            self.cursor = self._next_field(pos)

    def do_action(self, name: str) -> bool:
        """Run a 5250 key; returns False for names this emulation does not know."""
        if name not in ("reset", "insert"):
            self._fer_at = None                  # any other key ends "Field Exit required"
        n = self.size
        if name == "reset":
            if self._error_line is not None:
                row, line = self._error_line
                self.buf[row * self.cols:(row + 1) * self.cols] = line
                self._error_line = None
            self.inhibited, self.insert, self.message = "", False, ""
        elif name == "attn":
            self._send(OP_NOOP, b"", FLAG_ATN)
        elif name == "sysreq":
            self._send(OP_NOOP, b"", FLAG_SRQ)
        elif name in NAMED_AIDS or re.fullmatch(r"p?f\d+", name):
            aid = NAMED_AIDS.get(name) or AID_F.get(int(name.lstrip("pf")))
            if aid is None:
                return False
            self._aid(aid)
        elif name in ("up", "down", "left", "right"):
            step = {"up": -self.cols, "down": self.cols, "left": -1, "right": 1}[name]
            self.cursor = (self.cursor + step) % n
        elif name == "tab":
            self.cursor = self._next_field(self.cursor)
        elif name == "backtab":
            self.cursor = self._prev_field(self.cursor)
        elif name == "home":
            self.cursor = self._home()
        elif name == "newline":
            row_start = (self.cursor // self.cols + 1) % self.rows * self.cols
            fields = self._input_fields()
            later = [f.start for f in fields if f.start >= row_start]
            self.cursor = (later or [f.start for f in fields] or [row_start])[0]
        elif name == "field-end":
            self._field_end()
        elif name == "insert":
            self.insert = not self.insert
        elif name in ("field-exit", "field-plus", "field-minus", "dup", "field-mark",
                      "erase", "delete", "erase-eof", "erase-input"):
            if self._can_type():
                self._edit_key(name)
        else:
            return False
        self._render()
        return True

    def _field_end(self) -> None:
        f = self.field_at(self.cursor)
        if f is None or f.bypass:
            return
        last = None
        for p in f.data:
            if self.buf[p] not in (NULL, BLANK):
                last = p
        self.cursor = f.start if last is None else min(last + 1, f.data[-1])

    def _edit_key(self, name: str) -> None:
        if name == "erase-input":
            for f in self._input_fields():
                self._null(f)
                f.ffw &= ~FFW_MDT
            self.cursor = self._home()
            return
        pos = self.cursor
        f = self.field_at(pos)
        if name == "erase" and (f is None or f.bypass or pos == f.start):
            self.cursor = (pos - 1) % self.size  # backspace outside a field just moves
            return
        if f is None or f.bypass:
            self._error("Cursor in protected area")
            return
        span = list(f.data)
        idx = span.index(pos) if pos in span else len(span)
        if name in ("erase", "delete"):
            if name == "erase":
                idx -= 1
                self.cursor = span[idx]
            tail = span[idx:]
            for a, b in zip(tail, tail[1:]):
                self.buf[a] = self.buf[b]
            if tail:
                self.buf[tail[-1]] = NULL
            f.ffw |= FFW_MDT
        elif name == "erase-eof":
            for p in span[idx:]:
                self.buf[p] = NULL
            f.ffw |= FFW_MDT
        elif name == "dup":
            if not f.ffw & FFW_DUP:
                self._error("Dup key not allowed in this field")
                return
            for p in span[idx:]:
                self.buf[p] = DUP
            f.ffw |= FFW_MDT
            self.cursor = self._next_field(pos)
        elif name == "field-mark":
            if not f.ffw & FFW_DUP or pos not in span:
                self._error("Field Mark key not allowed in this field")
                return
            if self._store(f, pos, FIELD_MARK):
                self._advance(f, pos)
        elif name == "field-minus" and not f.signed and f.shift != SHIFT_NUMERIC_ONLY:
            self._error("Field- key allowed only in numeric fields")
        else:                                    # field exit, Field+, Field-
            self._fer_at = None
            self._exit(f, name == "field-minus", idx)
            if f.ffw & FFW_AUTO_ENTER:
                self._aid(AID_ENTER)
            else:
                self.cursor = self._next_field(f.start)

    def _exit(self, f: Field, negative: bool, idx: int | None = None) -> None:
        """Field Exit: null the rest of the field, right-adjust, set the sign."""
        span = list(f.data)
        for p in span[len(span) if idx is None else idx:]:
            self.buf[p] = NULL
        if f.adjust in (ADJUST_ZERO, ADJUST_BLANK) or f.signed or \
                (negative and f.shift == SHIFT_NUMERIC_ONLY):
            vals = [self.buf[p] for p in span]
            while vals and vals[-1] in (NULL, BLANK):
                vals.pop()
            fill = ZERO if f.adjust == ADJUST_ZERO else BLANK
            vals = [fill] * (len(span) - len(vals)) + vals
            for p, v in zip(span, vals):
                self.buf[p] = v
        if f.signed and f.length > 1:
            self.buf[f.end] = MINUS if negative else NULL
        elif negative and span and 0xF0 <= self.buf[span[-1]] <= 0xF9:
            self.buf[span[-1]] = 0xD0 | (self.buf[span[-1]] & 0x0F)
        f.ffw |= FFW_MDT

    def _aid(self, aid: int) -> None:
        if not self._can_type():
            return
        if aid not in NO_DATA_AIDS:
            for f in self._input_fields():
                filled = [self.buf[p] not in (NULL,) for p in f.data]
                if f.ffw & FFW_ME and not f.mdt:
                    self.cursor = f.start
                    self._error("Mandatory enter field")
                    return
                if f.adjust == MANDATORY_FILL and f.mdt and not all(filled):
                    self.cursor = f.start
                    self._error("Mandatory fill field")
                    return
        self._send_fields(aid, self.read_cmd)
        self.read_cmd = None
        self.locked, self.insert, self.message = True, False, ""
        self._fer_at = None

    # -------------------------------------------------------- rendering

    def _render(self) -> None:
        s = self.screen
        if (s.cols, s.rows) != (self.cols, self.rows):
            s.resize(self.cols, self.rows)
        attr = self._attr(0x20)
        hidden = False
        for p, b in enumerate(self.buf):
            y, x = divmod(p, self.cols)
            if 0x20 <= b <= 0x3F:
                # An attribute: shows as a blank and applies to what follows.
                attr = self._attr(b)
                hidden = b & A_NONDISPLAY == A_NONDISPLAY
                s.lines[y][x] = Cell(" ", DEFAULT_ATTR.with_(fg=attr.fg))
                continue
            if hidden or b == NULL or b < 0x40 and b not in (DUP, FIELD_MARK):
                # Non-display fields (passwords) never reach the screen.
                ch = " "
            elif b == DUP:
                ch = "*"
            elif b == FIELD_MARK:
                ch = ";"
            else:
                ch = bytes([b]).decode(self.encoding, errors="replace")
            s.lines[y][x] = Cell(ch, attr)
        s.y, s.x = divmod(self.cursor, self.cols)
        s.cursor_visible = True
        s.dirty = True
        self.on_status()

    def _attr(self, a: int) -> Attr:
        invisible = a & A_NONDISPLAY == A_NONDISPLAY
        if self.color:
            # Colour displays: intensity, blink and column separator pick the colour.
            return Attr(fg=COLORS[a & 0x1A], blink=a & 0x1A == 0x0A and not invisible,
                        reverse=bool(a & A_REVERSE) and not invisible,
                        underline=bool(a & A_UNDERLINE) and not invisible, invisible=invisible)
        if invisible:
            return Attr(fg=GREEN, invisible=True)
        return Attr(fg=GREEN, bold=bool(a & A_HIGH), blink=bool(a & A_BLINK),
                    reverse=bool(a & A_REVERSE), underline=bool(a & A_UNDERLINE))


class IBM5251(IBM5250):
    """IBM 5251 model 11: 24 x 80 monochrome display station."""
    name = "ibm5251-11"
    term_type = telnet_type = "IBM-5251-11"
    color = False


class IBM3477FC(IBM5250):
    """IBM 3477 model FC: 27 x 132 colour display station."""
    name = "ibm3477-fc"
    term_type = telnet_type = "IBM-3477-FC"
    alternate = (132, 27)
