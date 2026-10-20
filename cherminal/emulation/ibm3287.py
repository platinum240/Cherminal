"""IBM 3287 printer session (TN3270E printer LU, RFC 2355).

The host prints to a printer LU: SNA character string (SCS, LU type 1) or
3270 data stream records (LU type 3, or a local non-SNA 3287 such as a
Hercules console printer, which needs no TN3270E). Both are decoded into
plain text, pages separated by form feeds, and a finished job goes to
``on_job``; the GUI sends it to the session's printer. A job ends at the
host's PRINT-EOJ or UNBIND, or after :data:`EOJ_IDLE` seconds without data
(:meth:`tick`). There is no keyboard; the tab shows a status view.

SCS support: printable EBCDIC, NL, CR, LF, FF, HT, VT, BS, IRS, GE, SA,
TRN (transparent bytes, kept when printable), SHF (line width, left margin,
tab stops) and SVF (page length, margins, vertical tabs); other control
codes print as a space, as with x3270's pr3287. DBCS is not decoded.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from ..screen import DEFAULT_ATTR, Cell
from . import tn3270e
from .base import Emulation
from .ibm3270 import (COMMANDS, CMD_EW, CMD_EWA, CMD_W, CMD_WSF, EUA, FA_DISPLAY,
                      FA_HIDDEN, GE, IAC, EOR, IC, MAX_RECORD, MF, PT, RA, SA, SBA, SF, SFE,
                      decode_address)

EOJ_IDLE = 5.0                  # seconds without data that end a job

# SCS control codes.
SCS_BS, SCS_CR, SCS_ENP, SCS_FF, SCS_HT, SCS_INP, SCS_IRS, SCS_NL = (
    0x16, 0x0D, 0x14, 0x0C, 0x05, 0x24, 0x1E, 0x15)
SCS_VT, SCS_VCS, SCS_LF, SCS_GE, SCS_SA, SCS_TRN, SCS_SET, SCS_SO, SCS_SI = (
    0x0B, 0x04, 0x25, 0x08, 0x28, 0x35, 0x2B, 0x0E, 0x0F)
SCS_SHF, SCS_SVF = 0xC1, 0xC2
MAX_MPP, MAX_MPL = 132, 108

WCC_START_PRINT = 0x08
WCC_LINE_LENGTH = {0x00: 0, 0x10: 40, 0x20: 64, 0x30: 80}   # 0: honour NL/EM/FF orders
LU3_SIZE = 132 * 27             # the largest buffer a 3287 is written as
ORDER_NL, ORDER_EM, ORDER_FF, ORDER_CR = 0x15, 0x19, 0x0C, 0x0D


class SCSPrinter:
    """A virtual SCS printer: bytes in, text out (pages split by form feeds)."""

    def __init__(self, encoding: str = "cp037"):
        self.encoding = encoding
        self.out: list[str] = []
        self.pending = b""            # an order split across records
        self.reset()

    def reset(self) -> None:
        self.mpp, self.lm, self.htabs = MAX_MPP, 1, set()
        self.mpl, self.tm, self.bm, self.vtabs = 1, 1, 1, set()
        self.pp, self.line = 1, 1
        self.linebuf: dict[int, str] = {}

    def _dump_line(self, reset_pp: bool = True, always: bool = True) -> None:
        if self.linebuf or always:
            last = max(self.linebuf, default=0)
            self.out.append("".join(self.linebuf.get(i, " ") for i in range(1, last + 1))
                            + "\n")
            self.line += 1
        self.linebuf = {}
        if reset_pp:
            self.pp = self.lm

    def _formfeed(self) -> None:
        self.out.append("\f")
        self.line = self.tm

    def _add(self, ch: str) -> None:
        if self.mpl > 1 and self.line > self.bm:
            self._formfeed()                       # past the bottom margin
        if self.pp > self.mpp:
            self._dump_line()                      # past the right margin
        if ch != " ":
            self.linebuf[self.pp] = ch
        self.pp += 1

    def feed(self, data: bytes) -> None:
        data, self.pending = self.pending + data, b""
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            need = {SCS_GE: 2, SCS_SA: 3, SCS_TRN: 2, SCS_SET: 3}.get(b, 1)
            if i + need > n or (b == SCS_TRN and i + 2 + data[i + 1] > n) \
                    or (b == SCS_SET and i + 2 + data[i + 2] > n):
                self.pending = data[i:]            # wait for the rest of the order
                return
            if b == SCS_BS:
                self.pp = max(1, self.pp - 1)
            elif b == SCS_CR:
                self.pp = self.lm
            elif b == SCS_FF:
                if self.linebuf:
                    self._dump_line(always=False)
                self.pp = self.lm
                self._formfeed()
            elif b == SCS_HT:
                stops = [t for t in sorted(self.htabs) if t > self.pp]
                if stops:
                    self.pp = stops[0]
                else:
                    self._add(" ")
            elif b in (SCS_NL, SCS_IRS):
                self._dump_line()
            elif b == SCS_VT and any(t > self.line for t in self.vtabs):
                target = min(t for t in self.vtabs if t > self.line)
                self._dump_line(reset_pp=False)
                while self.line < target:
                    self.out.append("\n")
                    self.line += 1
            elif b in (SCS_VT, SCS_VCS, SCS_LF):
                self._dump_line(reset_pp=False)
            elif b == SCS_GE:
                self._add(" ")
                i += 1
            elif b == SCS_SA:
                i += 2
            elif b == SCS_TRN:
                count = data[i + 1]
                raw = data[i + 2:i + 2 + count].decode("latin-1")
                for ch in raw:
                    if ch.isprintable():
                        self._add(ch)
                i += 1 + count
            elif b == SCS_SET:
                self._set(data[i + 1], data[i + 3:i + 2 + data[i + 2]])
                i += 1 + data[i + 2]
            elif b in (SCS_ENP, SCS_INP, SCS_SO, SCS_SI):
                pass
            elif b < 0x40:
                self._add(" ")                     # a stray control code
            else:
                self._add(bytes([b]).decode(self.encoding, errors="replace"))
            i += 1

    def _set(self, kind: int, args: bytes) -> None:
        if kind == SCS_SHF:                        # MPP, LM, RM, tab stops
            self.mpp, self.lm, self.htabs = MAX_MPP, 1, set()
            if args:
                self.mpp = args[0] if 0 < args[0] <= MAX_MPP else MAX_MPP
            if len(args) > 1:
                self.lm = args[1] if 1 <= args[1] < self.mpp else 1
            self.htabs = {t for t in args[3:] if 1 <= t <= self.mpp}
        elif kind == SCS_SVF:                      # MPL, TM, BM, tab stops
            self.mpl, self.tm, self.bm, self.vtabs = 1, 1, 1, set()
            if args:
                self.mpl = args[0] if 0 < args[0] <= MAX_MPL else 1
                self.bm = self.mpl
            if len(args) > 1:
                self.tm = args[1] if 1 <= args[1] < self.mpl else 1
            if len(args) > 2:
                self.bm = args[2] if self.tm <= args[2] < self.mpl else self.mpl
            self.vtabs = {t for t in args[3:] if 1 <= t <= MAX_MPL}

    def take(self) -> str:
        """The job so far, ending any half-printed line."""
        if self.linebuf:
            self._dump_line()
        text, self.out = "".join(self.out), []
        self.pp, self.line = self.lm, 1
        return text


def lu3_text(buf: list[int], fa: list[int | None], high: int, wcc: int,
             encoding: str) -> str:
    """Print a 3270 buffer the way the WCC asks: fixed-width lines, or (line
    length 0) following the NL, CR, FF and EM orders in the data."""
    width = WCC_LINE_LENGTH[wcc & 0x30]
    hidden = False
    chars: list[str] = []
    for p in range(high):
        if fa[p] is not None:
            hidden = fa[p] & FA_DISPLAY == FA_HIDDEN
            chars.append(" " if width else "")
            continue
        c = buf[p]
        if width:
            chars.append(" " if hidden or c < 0x40 else bytes([c]).decode(encoding, "replace"))
        elif c == ORDER_EM:
            break
        elif c in (ORDER_NL, ORDER_FF, ORDER_CR):
            chars.append({ORDER_NL: "\n", ORDER_FF: "\f", ORDER_CR: "\r"}[c])
        elif c >= 0x40:
            chars.append(" " if hidden else bytes([c]).decode(encoding, "replace"))
    if width:
        text = "".join(chars)
        lines = [text[i:i + width].rstrip() for i in range(0, len(text), width)]
    else:
        lines = []
        for line in "".join(chars).split("\n"):
            line = line.rsplit("\r", 1)[-1] if "\r" in line else line   # CR: overprint
            while len(line) > MAX_MPP:
                lines.append(line[:MAX_MPP])
                line = line[MAX_MPP:]
            lines.append(line.rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


class IBM3287(Emulation):
    """IBM 3287 model 1 printer."""

    name = "ibm3287-1"
    term_type = telnet_type = "IBM-3287-1"
    keymap = "ibm3270"
    block_mode = True           # a TN3270 connection; keys never reach the host
    fixed_size = True
    printer = True
    tn3270 = True

    def __init__(self, screen, reply=None, encoding: str = "cp037", answerback: str = ""):
        super().__init__(screen, reply, encoding=encoding, answerback=answerback)
        screen.scrollback_limit = 0
        self.e = tn3270e.Framing(self.reply)
        self.on_status = lambda: None
        self.on_job: Callable[[str], None] = lambda text: None
        self.printer_name = ""          # shown in the status view
        self.print_result = ""          # what happened to the last job, from the GUI
        self.scs = SCSPrinter(encoding)
        self._rec, self._rec_dropped, self._iac = bytearray(), False, False
        self.lu_name = ""
        self.state = "waiting for the host"
        self.jobs = 0
        self.last_job, self.last_job_time = "", ""
        self._job: list[str] = []       # text of the job being received
        self._last_data = 0.0
        self._lu3_reset()
        self._render()

    @property
    def status(self) -> str:
        return f"Printer · {self.state}" + (" · printing" if self.job_open else "")

    @property
    def job_open(self) -> bool:
        return bool(self._job) or bool(self.scs.out) or bool(self.scs.linebuf)

    # -------------------------------------------------------------- host

    def set_tn3270e(self, device_type: str, lu_name: str, functions: tuple[int, ...]) -> None:
        self.e.start(functions)
        self.lu_name = lu_name
        self.state = "connected"
        self._render()

    def notice(self, text: str) -> None:
        self.end_job()                  # print what arrived before the line dropped
        self.state = text
        self._render()

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
            elif b == IAC:
                self._iac = True
                continue
            if len(self._rec) >= MAX_RECORD:
                self._rec.clear()
                self._rec_dropped = True
            self._rec.append(b)

    def feed_text(self, text: str) -> None:
        pass

    def _host_record(self, rec: bytes) -> None:
        if self.state != "connected":
            self.state = "connected"
        self._last_data = time.monotonic()
        if not self.e.active:
            self._lu3(rec)                  # plain TN3270: a local (non-SNA) 3287
        else:
            split = self.e.split(rec)
            if split:
                dtype, data = split
                if dtype == tn3270e.DT_SCS_DATA:
                    self.scs.feed(data)
                elif dtype == tn3270e.DT_3270_DATA:
                    self._lu3(data)
                elif dtype in (tn3270e.DT_PRINT_EOJ, tn3270e.DT_UNBIND):
                    self.end_job()
                elif dtype == tn3270e.DT_BIND_IMAGE:
                    self.scs.reset()
            self.e.ack()
        self._render()

    def tick(self, now: float | None = None) -> None:
        """End a job the host left open for :data:`EOJ_IDLE` seconds."""
        now = time.monotonic() if now is None else now
        if self.job_open and now - self._last_data >= EOJ_IDLE:
            self.end_job()

    def end_job(self) -> None:
        if self.scs.out or self.scs.linebuf:
            self._job.append(self.scs.take())
        text, self._job = "".join(self._job), []
        if text.strip():
            self.jobs += 1
            self.last_job = text
            self.last_job_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.on_job(text)
        self._render()

    # ------------------------------------------------- 3270 data (LU type 3)

    def _lu3_reset(self) -> None:
        self.buf = [0] * LU3_SIZE
        self.fa: list[int | None] = [None] * LU3_SIZE
        self.ba = self.high = 0

    def _lu3(self, rec: bytes) -> None:
        cmd = COMMANDS.get(rec[0]) if rec else None
        if cmd == CMD_WSF:
            if len(rec) > 4 and rec[3] == 0x01 and rec[5:6] in (b"\x02", b"\x03"):
                self.reply(self._query_reply())     # Read Partition Query
            return
        if cmd not in (CMD_W, CMD_EW, CMD_EWA) or len(rec) < 2:
            return
        if cmd != CMD_W:
            self._lu3_reset()
        wcc, data, n = rec[1], rec[2:], LU3_SIZE
        i, ba = 0, self.ba
        while i < len(data):
            b = data[i]
            if b == SF and i + 1 < len(data):
                self.fa[ba], self.buf[ba] = data[i + 1] & 0x3F, 0
                ba, i = (ba + 1) % n, i + 2
            elif b in (SFE, MF) and i + 1 < len(data):
                pairs = data[i + 2:i + 2 + 2 * data[i + 1]]
                if b == SFE:
                    attr = next((v for t, v in zip(pairs[::2], pairs[1::2]) if t == 0xC0), 0)
                    self.fa[ba], self.buf[ba] = attr & 0x3F, 0
                ba, i = (ba + 1) % n, i + 2 + 2 * data[i + 1]
            elif b == SBA and i + 2 < len(data):
                ba, i = decode_address(data[i + 1], data[i + 2]) % n, i + 3
            elif b in (IC, PT):
                i += 1
            elif b == SA:
                i += 3
            elif b in (RA, EUA) and i + 2 < len(data):
                stop = decode_address(data[i + 1], data[i + 2]) % n
                step = 3
                ch = 0
                if b == RA and i + 3 < len(data):
                    ch, step = data[i + 3], 4
                    if ch == GE and i + 4 < len(data):
                        ch, step = data[i + 4], 5
                first = True
                while first or ba != stop:
                    first = False
                    self.fa[ba], self.buf[ba] = None, ch
                    self.high = max(self.high, ba + 1)
                    ba = (ba + 1) % n
                i += step
            else:
                if b == GE and i + 1 < len(data):
                    i += 1
                    b = data[i]
                self.fa[ba], self.buf[ba] = None, b
                self.high = max(self.high, ba + 1)
                ba, i = (ba + 1) % n, i + 1
            self.high = max(self.high, ba)
        self.ba = ba
        if wcc & WCC_START_PRINT:
            self._job.append(lu3_text(self.buf, self.fa, self.high, wcc, self.encoding))

    def _query_reply(self) -> bytes:
        def sf(qcode: int, body: bytes) -> bytes:
            return (len(body) + 4).to_bytes(2, "big") + bytes([0x81, qcode]) + body
        usable = (bytes([0x01, 0x00]) + (132).to_bytes(2, "big") + (27).to_bytes(2, "big")
                  + bytes([0x01, 0x00, 0x0A, 0x02, 0xE5, 0x00, 0x02, 0x00, 0x6F, 0x09, 0x0C])
                  + LU3_SIZE.to_bytes(2, "big"))
        return bytes([0x88]) + sf(0x80, bytes([0x80, 0x81])) + sf(0x81, usable)

    # ---------------------------------------------------------- keyboard

    def type_text(self, text: str) -> None:
        pass                            # a printer has no keyboard

    def do_action(self, name: str) -> bool:
        return False

    def reset(self) -> None:
        self.screen.reset()

    # --------------------------------------------------------- rendering

    def _render(self) -> None:
        s = self.screen
        if (s.cols, s.rows) != (80, 24):
            s.resize(80, 24)
        lu = self.lu_name or "any LU"
        jobs = f"{self.jobs} job{'s' * (self.jobs != 1)} printed"
        rows = [f" Printer session — {lu} — {self.state} — {jobs}",
                f" Printing to {self.printer_name or 'the default printer'}"
                + ("  ·  receiving a job…" if self.job_open else ""),
                f" {self.print_result}" if self.print_result else "", ""]
        if self.last_job:
            rows.append(f" Last job, {self.last_job_time}:")
            body = self.last_job.replace("\f", "\n").split("\n")
            rows += ["   " + line.replace("\t", " ") for line in body[:24 - len(rows) - 1]]
        else:
            rows.append(" No jobs yet. Jobs from the host print without asking.")
        for y in range(24):
            text = rows[y] if y < len(rows) else ""
            text = text[:80].ljust(80)
            s.lines[y] = [Cell(ch, DEFAULT_ATTR) for ch in text]
        s.y, s.x = 0, 0
        s.cursor_visible = False
        s.dirty = True
        self.on_status()

