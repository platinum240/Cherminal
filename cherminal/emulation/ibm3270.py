"""IBM 3278/3279 display (TN3270, RFC 1576/2355) with extended attributes.

A 3270 is a block-mode terminal: the host writes whole screens of fields,
the user edits the unprotected fields locally, and an attention key (Enter,
PF, PA, Clear) sends the modified fields back in one record. So unlike the
character-mode emulations, typing never goes straight to the host; the
session hands keys to :meth:`type_text` and :meth:`do_action` instead.

Records arrive framed as the Telnet layer passes them: data bytes with 0xFF
doubled and each record ended by IAC EOR. Each :meth:`reply` call sends one
record; the Telnet layer adds the IAC EOR.

IND$FILE file transfers (DFT mode) are in :mod:`.indfile`.

References: IBM GA23-0059 "3270 Data Stream Programmer's Reference",
RFC 1576 (TN3270), RFC 2355 (TN3270E: used when the session names an LU,
with the record headers in :mod:`.tn3270e`).
"""

from __future__ import annotations

from ..screen import DEFAULT_ATTR, Attr, Cell
from . import indfile, tn3270e
from .base import Emulation, InputField, row_spans

# The largest 3270 data stream record kept. A full 27x132 screen with every
# order is well under 64 KB; anything bigger is broken and is thrown away.
MAX_RECORD = 1024 * 1024

IAC, EOR = 0xFF, 0xEF

# Commands, local (CCW) and SNA codes.
CMD_W, CMD_EW, CMD_EWA, CMD_RB, CMD_RM, CMD_RMA, CMD_EAU, CMD_WSF = range(8)
COMMANDS = {
    0xF1: CMD_W, 0x01: CMD_W, 0xF5: CMD_EW, 0x05: CMD_EW, 0x7E: CMD_EWA, 0x0D: CMD_EWA,
    0xF2: CMD_RB, 0x02: CMD_RB, 0xF6: CMD_RM, 0x06: CMD_RM, 0x6E: CMD_RMA, 0x0E: CMD_RMA,
    0x6F: CMD_EAU, 0x0F: CMD_EAU, 0xF3: CMD_WSF, 0x11: CMD_WSF,
}

# Orders.
SF, SFE, SBA, SA, MF, IC, PT, RA, EUA, GE = 0x1D, 0x29, 0x11, 0x28, 0x2C, 0x13, 0x05, 0x3C, 0x12, 0x08

# Write control character bits.
WCC_RESET_MDT, WCC_KB_RESTORE, WCC_ALARM = 0x01, 0x02, 0x04

# Field attribute bits.
FA_PROTECT, FA_NUMERIC, FA_DISPLAY, FA_MDT = 0x20, 0x10, 0x0C, 0x01
FA_INTENSE, FA_HIDDEN = 0x08, 0x0C

# Extended attribute types and values.
XA_ALL, XA_HIGHLIGHT, XA_FG, XA_CHARSET, XA_BG, XA_TRANSPARENCY, XA_FIELD = (
    0x00, 0x41, 0x42, 0x43, 0x45, 0x46, 0xC0)
HL_BLINK, HL_REVERSE, HL_UNDERSCORE, HL_INTENSIFY = 0xF1, 0xF2, 0xF4, 0xF8

# Attention identifiers.
AID_NONE, AID_ENTER, AID_CLEAR, AID_SF = 0x60, 0x7D, 0x6D, 0x88
AID_PA = {1: 0x6C, 2: 0x6E, 3: 0x6B}
AID_PF = dict(zip(range(1, 25), [0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0x7A,
                                 0x7B, 0x7C, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8,
                                 0xC9, 0x4A, 0x4B, 0x4C]))
SHORT_READ = {AID_CLEAR, *AID_PA.values()}

# What a numeric field accepts from the keyboard (the 3270 numeric lock).
NUMERIC_KEYS = frozenset("0123456789.,-")

# 6-bit values as sent in 12-bit addresses and field attributes.
CODE_TABLE = bytes([
    0x40, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F,
    0x50, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F,
    0x60, 0x61, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F,
    0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F,
])

# 3279 colours -> palette index (bright variants read well on a dark background).
COLORS = {0xF1: 12, 0xF2: 9, 0xF3: 13, 0xF4: 10, 0xF5: 14, 0xF6: 11, 0xF7: 15}
# Base colour mode, by (protected, intensified).
BASE_COLORS = {(False, False): 10, (False, True): 9, (True, False): 12, (True, True): 15}


def decode_address(b1: int, b2: int) -> int:
    if b1 & 0xC0 == 0:                      # 14-bit binary
        return ((b1 & 0x3F) << 8) | b2
    return ((b1 & 0x3F) << 6) | (b2 & 0x3F)


def encode_address(addr: int, size: int) -> bytes:
    if size > 4096:
        return bytes([(addr >> 8) & 0x3F, addr & 0xFF])
    return bytes([CODE_TABLE[(addr >> 6) & 0x3F], CODE_TABLE[addr & 0x3F]])


class IBM3270(Emulation):
    """IBM 3278 model 2 (24 x 80) with 3279 colour and extended highlighting."""

    name = "ibm3278-2"
    term_type = "IBM-3278-2-E"
    telnet_type = "IBM-3278-2-E"
    keymap = "ibm3270"
    family = "ibm3270"
    block_mode = True       # keys are edited locally and sent by attention keys
    fixed_size = True       # the host sets the grid; the window scales to it
    tn3270 = True           # the IBM 3270 family: TN3270(E), LU names
    alternate = (80, 24)    # cols, rows for Erase/Write Alternate

    def __init__(self, screen, reply=None, encoding: str = "cp037", answerback: str = ""):
        super().__init__(screen, reply, encoding=encoding, answerback=answerback)
        screen.scrollback_limit = 0
        # Every reply goes through the TN3270E framing (a no-op until agreed).
        self.e = tn3270e.Framing(self.reply)
        self.reply = self._reply_record
        self.lu_name = ""
        self._rec = bytearray()
        self._rec_dropped = False
        self._iac = False
        self.on_status = lambda: None
        self.transfer: indfile.DFTTransfer | None = None     # IND$FILE in progress
        self.reset()

    # ----------------------------------------------------------- state

    def reset(self) -> None:
        """Power-on: default size, empty unformatted buffer, keyboard unlocked."""
        self._size(80, 24)
        self.cursor = 0
        self.locked = False
        self.lock_reason = ""
        self.insert = False
        self.aid = AID_NONE
        self.message = ""
        self._render()

    def _size(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        n = cols * rows
        self.buf = [0] * n               # EBCDIC codes, 0 = null
        self.fa: list[int | None] = [None] * n  # field attribute at this position
        self.fx = [(0, 0, 0)] * n        # field extended attrs (fg, bg, highlight)
        self.cx = [(0, 0, 0)] * n        # character attrs from Set Attribute
        self.screen.resize(cols, rows)

    @property
    def size(self) -> int:
        return self.cols * self.rows

    @property
    def status(self) -> str:
        """Operator information area, shown in the status bar."""
        parts = []
        if self.locked:
            parts.append(f"X {self.lock_reason}")
        if self.insert:
            parts.append("Insert")
        if self.message:
            parts.append(self.message)
        if self.lu_name:
            parts.append(f"LU {self.lu_name}")
        r, c = divmod(self.cursor, self.cols)
        parts.append(f"{r + 1:03d}/{c + 1:03d}")
        return "  ".join(parts)

    def notice(self, text: str) -> None:
        self.message = text
        self.on_status()

    # ------------------------------------------------------- fields

    def field_start(self, pos: int) -> int | None:
        """Position of the attribute of the field holding ``pos``, or None if unformatted."""
        for i in range(self.size):
            p = (pos - i) % self.size
            if self.fa[p] is not None:
                return p
        return None

    def _formatted(self) -> bool:
        return any(a is not None for a in self.fa)

    def _protected(self, pos: int) -> bool:
        if self.fa[pos] is not None:
            return True
        start = self.field_start(pos)
        return start is not None and bool(self.fa[start] & FA_PROTECT)

    def _field_range(self, start: int) -> range:
        """Data positions of the field whose attribute is at ``start`` (may wrap)."""
        end = start + 1
        while end < start + self.size and self.fa[end % self.size] is None:
            end += 1
        return range(start + 1, end)

    def _fields(self) -> list[int]:
        return [p for p, a in enumerate(self.fa) if a is not None]

    def input_fields(self) -> list[InputField]:
        out = []
        for start in self._fields():
            fa = self.fa[start]
            if fa & FA_PROTECT:
                continue
            out += row_spans([p % self.size for p in self._field_range(start)], self.cols,
                             numeric=bool(fa & FA_NUMERIC),
                             hidden=fa & FA_DISPLAY == FA_HIDDEN, modified=bool(fa & FA_MDT))
        return out

    def click(self, pos: int) -> bool:
        if self.locked or not 0 <= pos < self.size or \
                (self._formatted() and self._protected(pos)):
            return False
        self.cursor = pos
        self._render()
        return True

    def _next_unprotected(self, pos: int) -> int:
        """First data position of the next unprotected field after ``pos``."""
        for i in range(1, self.size + 1):
            p = (pos + i) % self.size
            a = self.fa[p]
            if a is not None and not a & FA_PROTECT and self.fa[(p + 1) % self.size] is None:
                return (p + 1) % self.size
        return 0 if not self._formatted() else pos

    # --------------------------------------------------------- incoming

    def feed(self, data: bytes) -> None:
        for b in data:
            if self._iac:
                self._iac = False
                if b == EOR:
                    rec, self._rec = bytes(self._rec), bytearray()
                    if rec and not self._rec_dropped:
                        self._host_record(rec)
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
        pass  # 3270 data is binary; see feed()

    def set_tn3270e(self, device_type: str, lu_name: str, functions: tuple[int, ...]) -> None:
        """TN3270E was agreed: records now carry headers. Called by the session."""
        self.e.start(functions)
        self.lu_name = lu_name
        self.on_status()

    def _host_record(self, rec: bytes) -> None:
        if not self.e.active:
            self.process(rec)
            return
        split = self.e.split(rec)
        if split and split[0] == tn3270e.DT_3270_DATA and split[1]:
            self.process(split[1])
        self.e.ack()                    # nothing else to say (SSCP-LU, NVT: ignored)

    def _reply_record(self, data: bytes) -> None:
        self.e.send(self.e.wrap(data) if self.e.active else data)

    def process(self, rec: bytes) -> None:
        """Run one host record (a command and its data)."""
        cmd = COMMANDS.get(rec[0])
        if cmd in (CMD_W, CMD_EW, CMD_EWA):
            if cmd == CMD_EW:
                self._erase(80, 24)
            elif cmd == CMD_EWA:
                self._erase(*self.alternate)
            self._write(rec[1:], cmd != CMD_W)
        elif cmd == CMD_RB:
            self.reply(self._read_buffer(self.aid))
        elif cmd in (CMD_RM, CMD_RMA):
            self.reply(self._read_modified(self.aid))
        elif cmd == CMD_EAU:
            self._erase_all_unprotected()
        elif cmd == CMD_WSF:
            self._structured_fields(rec[1:])
        self._render()

    def _erase(self, cols: int, rows: int) -> None:
        self._size(cols, rows)
        self.cursor = 0

    def _write(self, data: bytes, erased: bool) -> None:
        if not data:
            return
        wcc = data[0]
        if wcc & WCC_RESET_MDT:
            for p in self._fields():
                self.fa[p] &= ~FA_MDT
        ba = 0 if erased else self.cursor
        cattr = (0, 0, 0)
        last_was_text = False
        i, n = 1, len(data)
        while i < n:
            b = data[i]
            order_text = False
            if b == SF and i + 1 < n:
                self._set_field(ba, data[i + 1], (0, 0, 0))
                ba = (ba + 1) % self.size
                i += 2
            elif b == SFE and i + 1 < n:
                count = data[i + 1]
                fa, fx = self._ext_pairs(data[i + 2:i + 2 + 2 * count], 0, (0, 0, 0))
                self._set_field(ba, fa, fx)
                ba = (ba + 1) % self.size
                i += 2 + 2 * count
            elif b == MF and i + 1 < n:
                count = data[i + 1]
                if self.fa[ba] is not None:
                    self.fa[ba], self.fx[ba] = self._ext_pairs(
                        data[i + 2:i + 2 + 2 * count], self.fa[ba], self.fx[ba])
                ba = (ba + 1) % self.size
                i += 2 + 2 * count
            elif b == SBA and i + 2 < n:
                ba = decode_address(data[i + 1], data[i + 2]) % self.size
                i += 3
            elif b == IC:
                self.cursor = ba
                i += 1
            elif b == PT:
                if last_was_text:
                    # After text, PT nulls the rest of the field.
                    while self.fa[ba] is None and ba != 0:
                        self._put(ba, 0, cattr)
                        ba = (ba + 1) % self.size
                ba = self._pt_target(ba)
                i += 1
            elif b == RA and i + 3 < n:
                stop = decode_address(data[i + 1], data[i + 2]) % self.size
                ch, step = data[i + 3], 4
                if ch == GE and i + 4 < n:
                    ch, step = data[i + 4], 5
                first = True
                while first or ba != stop:
                    first = False
                    self._put(ba, ch, cattr)
                    ba = (ba + 1) % self.size
                i += step
                order_text = True
            elif b == EUA and i + 2 < n:
                stop = decode_address(data[i + 1], data[i + 2]) % self.size
                first = True
                while first or ba != stop:
                    first = False
                    if not self._protected(ba):
                        self.buf[ba], self.cx[ba] = 0, (0, 0, 0)
                    ba = (ba + 1) % self.size
                i += 3
            elif b == SA and i + 2 < n:
                cattr = self._char_attr(cattr, data[i + 1], data[i + 2])
                i += 3
            elif b == GE and i + 1 < n:
                self._put(ba, data[i + 1], cattr)
                ba = (ba + 1) % self.size
                i += 2
                order_text = True
            else:
                self._put(ba, b, cattr)
                ba = (ba + 1) % self.size
                i += 1
                order_text = True
            last_was_text = order_text
        if wcc & WCC_KB_RESTORE:
            self.locked = False
            self.lock_reason = ""
            self.aid = AID_NONE
        if wcc & WCC_ALARM:
            self.on_bell()

    def _pt_target(self, ba: int) -> int:
        """Program Tab: next unprotected field's first position, or 0 at the end."""
        p = ba
        while True:
            a = self.fa[p]
            if a is not None and not a & FA_PROTECT:
                return (p + 1) % self.size
            p += 1
            if p >= self.size:
                return 0

    def _put(self, pos: int, ch: int, cattr) -> None:
        self.fa[pos] = None
        self.buf[pos] = ch
        self.cx[pos] = cattr

    def _set_field(self, pos: int, attr: int, fx) -> None:
        self.fa[pos] = attr & 0x3F
        self.fx[pos] = fx
        self.buf[pos] = 0
        self.cx[pos] = (0, 0, 0)

    @staticmethod
    def _ext_pairs(pairs: bytes, fa: int, fx):
        fg, bg, hl = fx
        for t, v in zip(pairs[::2], pairs[1::2]):
            if t == XA_FIELD:
                fa = v & 0x3F
            elif t == XA_FG:
                fg = v
            elif t == XA_BG:
                bg = v
            elif t == XA_HIGHLIGHT:
                hl = v
            elif t == XA_ALL:
                fg = bg = hl = 0
        return fa, (fg, bg, hl)

    @staticmethod
    def _char_attr(cattr, t: int, v: int):
        fg, bg, hl = cattr
        if t == XA_ALL:
            return (0, 0, 0)
        if t == XA_FG:
            fg = v
        elif t == XA_BG:
            bg = v
        elif t == XA_HIGHLIGHT:
            hl = v
        return (fg, bg, hl)

    def _erase_all_unprotected(self) -> None:
        for p in range(self.size):
            if not self._protected(p):
                self.buf[p], self.cx[p] = 0, (0, 0, 0)
        for p in self._fields():
            if not self.fa[p] & FA_PROTECT:
                self.fa[p] &= ~FA_MDT
        self.cursor = self._next_unprotected(self.size - 1)
        self.locked = False
        self.lock_reason = ""
        self.aid = AID_NONE

    # ------------------------------------------------ structured fields

    def _structured_fields(self, data: bytes) -> None:
        i = 0
        while i + 3 <= len(data):
            length = (data[i] << 8) | data[i + 1]
            if length == 0:
                length = len(data) - i        # "to the end of the record"
            if length < 3:
                return
            sf = data[i + 2:i + length]
            sfid, body = sf[0], sf[1:]
            if sfid == 0x01 and len(body) >= 2 and body[1] in (0x02, 0x03):
                self.reply(self._query_reply())           # Read Partition Query (List)
            elif sfid == 0x01 and len(body) >= 2:
                # Read Partition RB/RM/RMA for the implicit partition.
                kind = {0xF2: CMD_RB, 0xF6: CMD_RM, 0x6E: CMD_RMA}.get(body[1])
                if kind == CMD_RB:
                    self.reply(self._read_buffer(self.aid))
                elif kind is not None:
                    self.reply(self._read_modified(self.aid))
            elif sfid == indfile.SF_TRANSFER:               # IND$FILE (DFT)
                self._transfer_data(data[i:i + length])
            elif sfid == 0x40 and len(body) >= 2:          # Outbound 3270DS
                cmd = COMMANDS.get(body[1])
                if cmd == CMD_EW:
                    self._erase(80, 24)
                elif cmd == CMD_EWA:
                    self._erase(*self.alternate)
                if cmd in (CMD_W, CMD_EW, CMD_EWA):
                    self._write(body[2:], cmd != CMD_W)
                elif cmd == CMD_EAU:
                    self._erase_all_unprotected()
            i += length

    def _query_reply(self) -> bytes:
        cols, rows = self.alternate

        def sf(qcode: int, body: bytes) -> bytes:
            return (len(body) + 4).to_bytes(2, "big") + bytes([0x81, qcode]) + body

        usable = (bytes([0x01, 0x00]) + cols.to_bytes(2, "big") + rows.to_bytes(2, "big")
                  + bytes([0x01, 0x00, 0x0A, 0x02, 0xE5, 0x00, 0x02, 0x00, 0x6F, 0x09, 0x0C])
                  + (cols * rows).to_bytes(2, "big"))
        color = bytes([0x00, 0x08, 0x00, 0xF4]) + b"".join(
            bytes([c, c]) for c in range(0xF1, 0xF8))
        highlight = bytes([0x05, 0x00, 0xF0, 0xF1, 0xF1, 0xF2, 0xF2, 0xF4, 0xF4, 0xF8, 0xF8])
        modes = bytes([0x00, 0x01, 0x02])
        implicit = bytes([0x00, 0x00, 0x0B, 0x01, 0x00, 0x00, 0x50, 0x00, 0x18]) + \
            cols.to_bytes(2, "big") + rows.to_bytes(2, "big")
        # Distributed Data Management: tells IND$FILE to use DFT transfers.
        ddm = bytes(2) + indfile.BUFFER_SIZE.to_bytes(2, "big") * 2 + bytes([0x01, 0x01])
        replies = [(0x81, usable), (0x86, color), (0x87, highlight), (0x88, modes),
                   (0x95, ddm), (0xA6, implicit)]
        summary = sf(0x80, bytes([0x80] + [q for q, _ in replies]))
        return bytes([AID_SF]) + summary + b"".join(sf(q, b) for q, b in replies)

    # ---------------------------------------------------- file transfer

    def start_transfer(self, opts: indfile.TransferOptions, on_progress=None,
                       on_done=None) -> indfile.DFTTransfer:
        """Type the IND$FILE command into the input field and press Enter.

        Raises ValueError when it cannot start (keyboard locked, no input
        field, field too short) and OSError when the local file can't be
        opened; the host then drives the transfer through :meth:`process`.
        """
        if self.transfer and not self.transfer.finished:
            raise ValueError("a file transfer is already running")
        if self.locked:
            raise ValueError("the keyboard is locked; wait for the host or press Reset")
        command = opts.command()
        if self._prime_field() < len(command):
            raise ValueError("there is no input field long enough for the IND$FILE command "
                             "on this screen; go to a TSO READY prompt, a CICS transaction "
                             "screen or the CMS command line first")

        def done(ok: bool, message: str) -> None:
            self.message = "" if ok else "X File transfer"
            (on_done or (lambda ok, message: None))(ok, message)

        self.transfer = indfile.DFTTransfer(opts, self.encoding,
                                            on_progress or (lambda done, total: None), done)
        for ch in command:
            # $ is typed as X'5B' whatever the code page: IND$FILE's own name.
            self._type_code(0x5B) if ch == "$" else self._type_char(ch)
        self._attention(AID_ENTER)
        self._render()
        return self.transfer

    def abort_transfer(self, reason: str) -> None:
        """End a transfer locally, e.g. when the connection drops."""
        if self.transfer and not self.transfer.finished:
            self.transfer.finish(False, reason)

    def _prime_field(self) -> int:
        """Empty the input field at or after the cursor and put the cursor at
        its start (like x3270 before a transfer); returns its length."""
        if not self._formatted():
            for p in range(self.cursor, self.size):
                self.buf[p] = 0
            return self.size - self.cursor
        pos = self.cursor
        if self._protected(pos):
            pos = self._next_unprotected(pos)
            if self._protected(pos):
                return 0                            # no input fields at all
        start = self.field_start(pos)
        span = [p % self.size for p in self._field_range(start)]
        for p in span:
            self.buf[p], self.cx[p] = 0, (0, 0, 0)
        self.cursor = span[0] if span else pos
        return len(span)

    def _transfer_data(self, sf: bytes) -> None:
        if self.transfer is None:
            return                                  # no transfer of ours: ignore
        reply = self.transfer.handle(sf)
        if reply:
            self.aid = AID_SF
            self.reply(reply)

    # ----------------------------------------------------------- reading

    def _header(self, aid: int) -> bytearray:
        return bytearray([aid]) + encode_address(self.cursor, self.size)

    def _read_modified(self, aid: int) -> bytes:
        if aid == AID_SF and self.transfer and self.transfer.saved:
            return self.transfer.saved          # the host lost an IND$FILE reply
        if aid in SHORT_READ:
            return bytes([aid])
        out = self._header(aid)
        fields = self._fields()
        if not fields:
            out += bytes(b for b in self.buf if b)
            return bytes(out)
        for start in fields:
            if not self.fa[start] & FA_MDT:
                continue
            first = (start + 1) % self.size
            out += bytes([SBA]) + encode_address(first, self.size)
            out += bytes(self.buf[p % self.size] for p in self._field_range(start)
                         if self.buf[p % self.size])
        return bytes(out)

    def _read_buffer(self, aid: int) -> bytes:
        out = self._header(aid)
        for p in range(self.size):
            if self.fa[p] is not None:
                out += bytes([SF, CODE_TABLE[self.fa[p] & 0x3F]])
            else:
                out.append(self.buf[p])
        return bytes(out)

    # -------------------------------------------------------- keyboard

    def _refuse(self, reason: str) -> bool:
        self.message = f"X {reason}"
        self.on_bell()
        self._render()
        return False

    def type_text(self, text: str) -> None:
        for ch in text:
            if ch in "\r\n":
                self.do_action("newline")
            elif ch == "\t":
                self.do_action("tab")
            elif not self._type_char(ch):
                break
        self._render()

    def paste_text(self, text: str) -> int:
        """Type pasted text into the input fields; returns the characters placed.

        Text fills the field the cursor is in and runs on into the next
        unprotected field when one fills up; a line break moves to the first
        input field on a following row, like Newline. Protected text is
        skipped, never overtyped. Pasting stops, with the usual OIA message,
        at a character a field refuses (a letter in a numeric field: X NUM),
        and when the screen has no input fields left below the cursor, so it
        never wraps round to the top and overtypes what was pasted first.
        """
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while len(lines) > 1 and not lines[-1]:
            lines.pop()                             # a trailing line break
        placed, advanced = 0, False  # advanced: the last character filled a field
        self._paste_full = False
        for i, line in enumerate(lines):
            if i and not advanced and not self._paste_newline():
                if any(lines[i:]):
                    self._refuse("Overflow")
                break
            advanced = False
            for ch in line:
                step = self._paste_char(ch)
                if step is None:
                    break
                placed += step[0]
                advanced = step[1]
            else:
                continue
            break
        self._render()
        return placed

    def _paste_char(self, ch: str) -> tuple[int, bool] | None:
        """(characters placed, moved to the next field), or None to stop."""
        if self._paste_full:
            return self._refuse("Overflow") or None
        if ch == "\t":
            nxt = self._next_input(self.cursor)
            if nxt is None:
                return self._refuse("Overflow") or None
            self.cursor = nxt
            return 0, False
        pos = self.cursor
        if self._formatted() and self._protected(pos):
            nxt = self._next_input(pos)
            if nxt is None:
                return self._refuse("Overflow") or None
            self.cursor = pos = nxt
        if not self._type_char(ch):
            return None
        if self.cursor <= pos:                      # wrapped past the bottom
            self.cursor, self._paste_full = pos, True
            return 1, True
        if self._formatted() and self._protected(self.cursor):
            nxt = self._next_input(pos)             # field full: on to the next one
            if nxt is not None:
                self.cursor = nxt
                return 1, True
        return 1, self.cursor != pos + 1            # an autoskip field jumped ahead

    def _next_input(self, pos: int) -> int | None:
        """First data position of the next input field after ``pos``, not
        wrapping past the bottom of the screen; None when there is none."""
        if not self._formatted():
            return pos + 1 if pos + 1 < self.size else None
        for p in range(pos + 1, self.size - 1):
            a = self.fa[p]
            if a is not None and not a & FA_PROTECT and self.fa[p + 1] is None:
                return p + 1
        return None

    def _paste_newline(self) -> bool:
        row_start = (self.cursor // self.cols + 1) * self.cols
        if row_start >= self.size:
            return False
        nxt = row_start if not self._formatted() else self._next_input(row_start - 1)
        if nxt is None:
            return False
        self.cursor = nxt
        return True

    def _type_char(self, ch: str) -> bool:
        if self.locked:
            return self._refuse(self.lock_reason)
        try:
            code = ch.encode(self.encoding)
        except UnicodeEncodeError:
            return self._refuse("Symbol")
        if len(code) != 1 or code[0] < 0x40:
            return self._refuse("Symbol")
        return self._type_code(code[0], ch)

    def _type_code(self, code: int, ch: str = "") -> bool:
        """Put one EBCDIC character at the cursor, as the keyboard would."""
        pos = self.cursor
        if self._protected(pos):
            return self._refuse("Protected")
        start = self.field_start(pos)
        if start is not None and self.fa[start] & FA_NUMERIC and ch and ch not in NUMERIC_KEYS:
            return self._refuse("NUM")             # numeric lock: digits, . , - only
        if self.insert:
            span = [p % self.size for p in (self._field_range(start) if start is not None
                                            else range(self.size))]
            tail = span[span.index(pos):]
            if self.buf[tail[-1]] not in (0, 0x40):
                return self._refuse("Overflow")
            for a, b in zip(reversed(tail[1:]), reversed(tail[:-1])):
                self.buf[a], self.cx[a] = self.buf[b], self.cx[b]
        self.buf[pos] = code
        self.message = ""
        if start is not None:
            self.fa[start] |= FA_MDT
        nxt = (pos + 1) % self.size
        a = self.fa[nxt]
        if a is not None and a & FA_PROTECT and a & FA_NUMERIC:
            nxt = self._next_unprotected(nxt)       # autoskip field: jump ahead
        self.cursor = nxt
        return True

    def do_action(self, name: str) -> bool:
        """Run a 3270 key; returns False for names this emulation does not know."""
        n = self.size
        if name == "reset":
            self.locked, self.lock_reason, self.insert, self.message = False, "", False, ""
        elif name in ("enter", "clear") or name[:2] in ("pf", "pa"):
            aid = {"enter": AID_ENTER, "clear": AID_CLEAR}.get(name)
            if aid is None:
                try:
                    num = int(name[2:])
                except ValueError:
                    return False
                aid = (AID_PF if name.startswith("pf") else AID_PA).get(num)
                if aid is None:
                    return False
            self._attention(aid)
        elif name in ("up", "down", "left", "right"):
            step = {"up": -self.cols, "down": self.cols, "left": -1, "right": 1}[name]
            self.cursor = (self.cursor + step) % n
        elif name == "tab":
            self.cursor = self._next_unprotected(self.cursor)
        elif name == "backtab":
            self.cursor = self._prev_unprotected(self.cursor)
        elif name == "home":
            self.cursor = self._next_unprotected(n - 1) if self._formatted() else 0
        elif name == "newline":
            row_start = (self.cursor // self.cols + 1) % self.rows * self.cols
            first = row_start if not self._formatted() else None
            if first is None:
                first = self._next_unprotected((row_start - 1) % n)
            self.cursor = first
        elif name == "field-end":
            self._field_end()
        elif name == "insert":
            self.insert = not self.insert
        elif name in ("erase", "delete", "erase-eof", "erase-input"):
            if self.locked:
                return self._refuse(self.lock_reason) or True
            if name == "erase-input":
                self._erase_input()
            elif self._protected(self.cursor):
                return self._refuse("Protected") or True
            else:
                self._edit(name)
        else:
            return False
        self._render()
        return True

    def _prev_unprotected(self, pos: int) -> int:
        start = self.field_start(pos)
        if start is not None and not self.fa[start] & FA_PROTECT \
                and pos != (start + 1) % self.size and self.fa[pos] is None:
            return (start + 1) % self.size          # start of this field first
        for i in range(2, self.size + 2):
            p = (pos - i) % self.size
            a = self.fa[p]
            if a is not None and not a & FA_PROTECT and self.fa[(p + 1) % self.size] is None:
                return (p + 1) % self.size
        return 0 if not self._formatted() else pos

    def _field_end(self) -> None:
        start = self.field_start(self.cursor)
        if start is None or self._protected(self.cursor):
            return
        span = [p % self.size for p in self._field_range(start)]
        last = start
        for p in span:
            if self.buf[p] not in (0, 0x40):
                last = p
        nxt = (last + 1) % self.size
        self.cursor = nxt if self.fa[nxt] is None else last

    def _edit(self, name: str) -> None:
        pos = self.cursor
        start = self.field_start(pos)
        span = [p % self.size for p in (self._field_range(start) if start is not None
                                        else range(self.size))]
        idx = span.index(pos)
        if name == "erase":                       # delete the character to the left
            if idx == 0:
                return
            idx -= 1
            pos = span[idx]
            self.cursor = pos
        if name in ("erase", "delete"):
            tail = span[idx:]
            for a, b in zip(tail, tail[1:]):
                self.buf[a], self.cx[a] = self.buf[b], self.cx[b]
            self.buf[tail[-1]] = 0
        else:                                      # erase-eof
            for p in span[idx:]:
                self.buf[p] = 0
        if start is not None:
            self.fa[start] |= FA_MDT

    def _erase_input(self) -> None:
        if not self._formatted():
            self.buf = [0] * self.size
            self.cursor = 0
            return
        for start in self._fields():
            if not self.fa[start] & FA_PROTECT:
                for p in self._field_range(start):
                    self.buf[p % self.size] = 0
                self.fa[start] &= ~FA_MDT
        self.cursor = self._next_unprotected(self.size - 1)

    def _attention(self, aid: int) -> None:
        if self.locked:
            self._refuse(self.lock_reason)
            return
        if aid == AID_CLEAR:
            self._erase(80, 24)
        self.aid = aid
        self.locked, self.lock_reason, self.insert, self.message = True, "System", False, ""
        self.reply(self._read_modified(aid))

    # -------------------------------------------------------- rendering

    def _render(self) -> None:
        s = self.screen
        if (s.cols, s.rows) != (self.cols, self.rows):
            s.resize(self.cols, self.rows)
        field_attr, fx = None, (0, 0, 0)
        start = self.field_start(self.size - 1)
        if start is not None:
            field_attr, fx = self.fa[start], self.fx[start]
        for p in range(self.size):
            y, x = divmod(p, self.cols)
            if self.fa[p] is not None:
                field_attr, fx = self.fa[p], self.fx[p]
                s.lines[y][x] = Cell(" ", self._attr(field_attr, fx, (0, 0, 0)))
                continue
            code = self.buf[p]
            if code < 0x40 or (field_attr is not None and field_attr & FA_DISPLAY == FA_HIDDEN):
                # Hidden fields (passwords) never reach the screen, so copy can't leak them.
                ch = " "
            else:
                ch = bytes([code]).decode(self.encoding, errors="replace")
            s.lines[y][x] = Cell(ch, self._attr(field_attr, fx, self.cx[p]))
        s.y, s.x = divmod(self.cursor, self.cols)
        s.cursor_visible = True
        s.dirty = True
        self.on_status()

    @staticmethod
    def _attr(field_attr: int | None, fx, cx) -> Attr:
        if field_attr is None:
            return DEFAULT_ATTR.with_(fg=BASE_COLORS[(False, False)])
        protected = bool(field_attr & FA_PROTECT)
        display = field_attr & FA_DISPLAY
        intense = display == FA_INTENSE
        fg = cx[0] or fx[0]
        bg = cx[1] or fx[1]
        hl = cx[2] or fx[2]
        return Attr(
            fg=COLORS.get(fg, BASE_COLORS[(protected, intense)]),
            bg=COLORS.get(bg),
            bold=intense or hl == HL_INTENSIFY,
            blink=hl == HL_BLINK,
            reverse=hl == HL_REVERSE,
            underline=hl == HL_UNDERSCORE,
            invisible=display == FA_HIDDEN,
        )


class IBM3278Model3(IBM3270):
    """IBM 3278 model 3: 32 x 80 alternate screen."""
    name = "ibm3278-3"
    term_type = telnet_type = "IBM-3278-3-E"
    alternate = (80, 32)


class IBM3278Model4(IBM3270):
    """IBM 3278 model 4: 43 x 80 alternate screen."""
    name = "ibm3278-4"
    term_type = telnet_type = "IBM-3278-4-E"
    alternate = (80, 43)


class IBM3278Model5(IBM3270):
    """IBM 3278 model 5: 27 x 132 alternate screen."""
    name = "ibm3278-5"
    term_type = telnet_type = "IBM-3278-5-E"
    alternate = (132, 27)
