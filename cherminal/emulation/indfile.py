"""IND$FILE file transfer, DFT mode (Write Structured Field "Transfer Data").

The user's command (``IND$FILE PUT 'USER.DATA' ASCII CRLF``) is typed into
the host's input field and sent with Enter, as x3270 does. The host program
then drives the transfer with structured fields of type 0xD0: an Open (for
the data, "FT:DATA"), Get requests that the terminal answers with file data
(send to host) or Data Inserts that it acknowledges (receive from host), a
Close, and finally a second Open/Insert/Close carrying the result message
("FT:MSG", e.g. ``TRANS03 File transfer complete``). Hosts only use DFT when
the terminal's query reply lists Distributed Data Management (0x95), which
:mod:`.ibm3270` always includes; the older CUT mode is not supported.

In ASCII mode IND$FILE translates between EBCDIC and its own fixed "ASCII"
table; that table is undone here and the session's code page applied, so a
local text file is UTF-8 whatever the host's language. CRLF adds CR LF at
record ends on the host's side; locally lines end in LF (and any ^Z is
dropped). Binary moves bytes untouched. DBCS text is not converted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import BinaryIO, Callable

SF_TRANSFER = 0xD0
AID_SF = 0x88

# Host requests.
TR_OPEN_REQ, TR_CLOSE_REQ = 0x0012, 0x4112
TR_SET_CUR_REQ, TR_GET_REQ, TR_INSERT_REQ, TR_DATA_INSERT = 0x4511, 0x4611, 0x4711, 0x4704
# Terminal replies.
TR_OPEN_REPLY, TR_CLOSE_REPLY = 0x0009, 0x4109
TR_GET_REPLY, TR_NORMAL_REPLY, TR_ERROR_REPLY = 0x4605, 0x4705, 0x08
TR_RECNUM_HDR, TR_ERROR_HDR, TR_NOT_COMPRESSED, TR_BEGIN_DATA = 0x6306, 0x6904, 0xC080, 0x61
TR_ERR_EOF, TR_ERR_CMDFAIL = 0x2200, 0x0100

BUFFER_SIZE = 4096            # INLIM/OUTLIM in the DDM query reply
HOST_TYPES = ("tso", "cics", "vm")
RECFMS = ("", "F", "V", "U")
SPACE_UNITS = ("", "tracks", "cylinders", "avblock")

# IND$FILE's own fixed EBCDIC <-> "ASCII" tables (as x3270 has them).
FT2ASC = bytes.fromhex(
    "000102039c09867f978d0a0b0c0d0e0f101112139d8508871819928f1c1d1e1f"
    "808182838400171b88898a8b8c050607909116939495960498999a9b14159e1a"
    "20a0a1a2a3a4a5a6a7a85b2e3c282b5d26a9aaabacadaeafb0b121242a293b5e"
    "2d2fb2b3b4b5b6b7b8b97c2c255f3e3fbabbbcbdbebfc0c1c2603a2340273d22"
    "c3616263646566676869c4c5c6c7c8c9ca6a6b6c6d6e6f707172cbcccdcecfd0"
    "d17e737475767778797ad2d3d4d5d6d7d8d9dadbdcdddedfe0e1e2e3e4e5e6e7"
    "7b414243444546474849e8e9eaebeced7d4a4b4c4d4e4f505152eeeff0f1f2f3"
    "5c9f535455565758595af4f5f6f7f8f930313233343536373839fafbfcfdfeff")
ASC2FT = bytes.fromhex(
    "00010203372d2e2f16050a0b0c0d0e0f101112133c3d322618193f271c1d1e1f"
    "405a7f7b5b6c507d4d5d5c4e6b604b61f0f1f2f3f4f5f6f7f8f97a5e4c7e6e6f"
    "7cc1c2c3c4c5c6c7c8c9d1d2d3d4d5d6d7d8d9e2e3e4e5e6e7e8e94ae04f5f6d"
    "79818283848586878889919293949596979899a2a3a4a5a6a7a8a9c06ad0a107"
    "202122232415061728292a2b2c090a1b30311a333435360838393a3b04143ee1"
    "4142434445464748495152535455565758596263646566676869707172737475"
    "767778808a8b8c8d8e8f909a9b9c9d9e9fa0aaabacadaeafb0b1b2b3b4b5b6b7"
    "b8b9babbbcbdbebfcacbcccdcecfdadbdcdddedfeaebecedeeeffafbfcfdfeff")


@dataclass
class TransferOptions:
    send: bool                    # True: PUT a local file to the host; False: GET
    host_file: str                # TSO 'USER.DATA' / CICS name / VM "FN FT FM"
    local_file: str
    host: str = "tso"             # tso | cics | vm
    ascii: bool = True            # text with code page translation; False = binary
    crlf: bool = True             # records end in CR LF (ASCII only)
    append: bool = False          # PUT: add to the host file; GET: to the local file
    recfm: str = ""               # PUT to TSO/VM: "" (host default), F, V or U
    lrecl: int = 0
    blksize: int = 0              # TSO only
    space_units: str = ""         # TSO: "" (default), tracks, cylinders or avblock
    primary: int = 0
    secondary: int = 0
    avblock: int = 0

    def __post_init__(self) -> None:
        if self.host not in HOST_TYPES:
            raise ValueError(f"host type must be one of {', '.join(HOST_TYPES)}")
        if self.recfm not in RECFMS or self.space_units not in SPACE_UNITS:
            raise ValueError("unknown record format or space unit")
        if not self.host_file.strip() or not self.local_file:
            raise ValueError("give both a host file and a local file")
        if any(c in self.host_file for c in "\r\n"):
            raise ValueError("the host file name cannot have line breaks")

    def command(self) -> str:
        """The IND$FILE command, as typed on the host (x3270's rules)."""
        tso, cics, vm = (self.host == h for h in HOST_TYPES)
        parts = ["IND$FILE", "PUT" if self.send else "GET", self.host_file.strip()]
        opts = []
        if self.ascii:
            opts.append("ASCII")
        elif cics:
            opts.append("BINARY")
        if self.ascii and self.crlf:
            opts.append("CRLF")
        elif cics:
            opts.append("NOCRLF")
        if self.append and self.send:
            opts.append("APPEND")
        if self.send and tso:
            if self.recfm:
                opts.append(f"RECFM({self.recfm})")
                if self.lrecl:
                    opts.append(f"LRECL({self.lrecl})")
                if self.blksize:
                    opts.append(f"BLKSIZE({self.blksize})")
            if self.space_units and self.primary:
                space = f"SPACE({self.primary}" + (f",{self.secondary}" if self.secondary
                                                   else "") + ")"
                opts.append(space)
                opts.append(f"AVBLOCK({self.avblock})" if self.space_units == "avblock"
                            else self.space_units.upper())
        elif self.send and vm and self.recfm in ("F", "V"):
            opts += ["RECFM", self.recfm] + (["LRECL", str(self.lrecl)] if self.lrecl else [])
        if not tso and opts:
            opts[0] = "(" + opts[0]          # CICS and CMS options follow a parenthesis
        return " ".join(parts + opts)


def _sf(body: bytes) -> bytes:
    """An inbound Transfer Data structured field, AID included."""
    return bytes([AID_SF]) + (len(body) + 3).to_bytes(2, "big") + bytes([SF_TRANSFER]) + body


class DFTTransfer:
    """One IND$FILE transfer. :meth:`handle` takes each 0xD0 structured field
    from the host and returns the reply record (or None).

    ``on_progress(bytes_done, bytes_total)`` (total 0 when unknown) and
    ``on_done(ok, message)`` are called from whichever thread feeds the
    emulation.
    """

    def __init__(self, opts: TransferOptions, encoding: str = "cp037",
                 on_progress: Callable[[int, int], None] = lambda done, total: None,
                 on_done: Callable[[bool, str], None] = lambda ok, message: None):
        self.opts = opts
        self.encoding = encoding
        self.on_progress, self.on_done = on_progress, on_done
        self.total = 0
        if opts.send:
            if opts.ascii:
                with open(opts.local_file, "rb") as f:
                    raw = f.read()
                self.file: BinaryIO = _Buffer(self._to_host(raw))
            else:
                self.file = open(opts.local_file, "rb")
            self.total = self.file.size if opts.ascii else os.fstat(self.file.fileno()).st_size
        else:
            self.file = open(opts.local_file, "ab" if opts.append else "wb")
        self.state = "started"        # started -> data -> message -> done
        self.message_mode = False
        self.recnum = 1
        self.done = 0
        self.cancelled = False
        self.eof = False
        self.saved = b""              # last Get reply, resent on Read Modified
        self.finished = False

    # ------------------------------------------------------------- control

    def cancel(self) -> None:
        """Stop at the host's next request; before the host started, stop now."""
        if self.state == "started":
            self.finish(False, "Transfer cancelled")
        else:
            self.cancelled = True

    def finish(self, ok: bool, message: str) -> None:
        if self.finished:
            return
        self.finished = True
        self.state = "done"
        try:
            self.file.close()
        except OSError:
            pass
        self.on_done(ok, message)

    # ------------------------------------------------------------ host side

    def handle(self, sf: bytes) -> bytes | None:
        """``sf`` is one structured field from its length bytes on."""
        if self.finished or len(sf) < 5:
            return None
        length = int.from_bytes(sf[:2], "big") or len(sf)
        req = int.from_bytes(sf[3:5], "big")
        if req == TR_OPEN_REQ:
            name = sf[max(5, length - 7):length].decode("ascii", "replace").strip()
            self.message_mode = name == "FT:MSG"
            self.state = "message" if self.message_mode else "data"
            self.recnum = 1
            return _sf(TR_OPEN_REPLY.to_bytes(2, "big"))
        if req in (TR_INSERT_REQ, TR_SET_CUR_REQ):
            return None
        if req == TR_DATA_INSERT:
            return self._data_insert(sf)
        if req == TR_GET_REQ:
            return self._get()
        if req == TR_CLOSE_REQ:
            return _sf(TR_CLOSE_REPLY.to_bytes(2, "big"))
        return None

    def _abort(self, req: int) -> bytes:
        self.cancelled = False
        self.message_mode = False
        self.state = "aborting"
        return _sf(bytes([req >> 8, TR_ERROR_REPLY]) + TR_ERROR_HDR.to_bytes(2, "big")
                   + TR_ERR_CMDFAIL.to_bytes(2, "big"))

    def _ack(self) -> bytes:
        reply = _sf(TR_NORMAL_REPLY.to_bytes(2, "big") + TR_RECNUM_HDR.to_bytes(2, "big")
                    + self.recnum.to_bytes(4, "big"))
        self.recnum += 1
        return reply

    def _data_insert(self, sf: bytes) -> bytes:
        if self.cancelled and not self.message_mode:
            return self._abort(TR_DATA_INSERT)
        size = max(0, int.from_bytes(sf[8:10], "big") - 5)
        data = sf[10:10 + size]
        if self.message_mode:
            # The result: "TRANS03 File transfer complete$". Like x3270, the
            # transfer ends here and the host's last Close is not answered.
            reply = self._ack()
            text = data.decode("latin-1").split("$")[0].strip()
            self.finish(text.startswith(("TRANS03", "TRANS04")), text)
            return reply
        if data:
            try:
                self.file.write(self._from_host(data) if self.opts.ascii else data)
            except OSError as e:
                self.finish(False, f"Cannot write {self.opts.local_file}: {e.strerror or e}")
                return self._abort(TR_DATA_INSERT)
            self.done += len(data)
            self.on_progress(self.done, 0)
        return self._ack()

    def _get(self) -> bytes:
        if self.cancelled:
            return self._abort(TR_GET_REQ)
        chunk = b"" if self.eof else self.file.read(BUFFER_SIZE - 27)
        if chunk:
            reply = _sf(TR_GET_REPLY.to_bytes(2, "big") + TR_RECNUM_HDR.to_bytes(2, "big")
                        + self.recnum.to_bytes(4, "big") + TR_NOT_COMPRESSED.to_bytes(2, "big")
                        + bytes([TR_BEGIN_DATA]) + (len(chunk) + 5).to_bytes(2, "big") + chunk)
            self.recnum += 1
            self.done += len(chunk)
            self.on_progress(self.done, self.total)
        else:
            self.eof = True
            reply = _sf(bytes([TR_GET_REQ >> 8, TR_ERROR_REPLY]) + TR_ERROR_HDR.to_bytes(2, "big")
                        + TR_ERR_EOF.to_bytes(2, "big"))
        self.saved = reply
        return reply

    # ------------------------------------------------------- translation

    def _from_host(self, data: bytes) -> bytes:
        """Host ASCII -> local UTF-8: undo IND$FILE's table, apply the code page."""
        out = []
        for c in data:
            if self.opts.crlf and c in (0x0D, 0x1A):
                continue                          # CR LF -> LF, and drop ^Z
            if c < 0x20 or (0x80 <= c < 0xA0 and c != 0x9F):
                out.append(chr(c))                # control codes pass through
            elif c == 0xFF:
                out.append("\x9f")                # IND$FILE's X'FF'
            else:
                out.append(bytes([ASC2FT[c]]).decode(self.encoding, "replace"))
        return "".join(out).encode("utf-8")

    def _to_host(self, raw: bytes) -> bytes:
        """Local UTF-8 -> host ASCII (the reverse of :meth:`_from_host`)."""
        text = raw.decode("utf-8", "replace")
        out = bytearray()
        last_cr = False
        for ch in text:
            u = ord(ch)
            if self.opts.crlf and ch == "\n" and not last_cr:
                out.append(0x0D)
            last_cr = ch == "\r"
            if u < 0x20 or 0x80 <= u < 0x9F:
                out.append(u)
            elif u == 0x9F:
                out.append(0xFF)
            else:
                try:
                    code = ch.encode(self.encoding)
                except UnicodeEncodeError:
                    code = "?".encode(self.encoding)
                out.append(FT2ASC[code[0]] if len(code) == 1 else 0x3F)
        return bytes(out)


class _Buffer:
    """A translated upload held in memory, read like a file."""

    def __init__(self, data: bytes):
        self.data, self.pos, self.size = data, 0, len(data)

    def read(self, n: int) -> bytes:
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.data = b""
