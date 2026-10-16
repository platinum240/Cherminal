"""Telnet client (RFC 854) with BINARY, ECHO, SGA, TTYPE, NAWS and EOR options.

In TN3270 mode (RFC 1576) the session is binary both ways and framed in
records: incoming data keeps 0xFF doubled and each IAC EOR, so the 3270
emulation can find record boundaries, and each write is sent as one record.

``TelnetProtocol`` is the pure option-negotiation state machine, kept
separate from sockets so it can be tested directly.
"""

from __future__ import annotations

import socket
import ssl
import struct
from typing import Callable

from .base import Transport

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
NOP, BRK, AYT, GA, EOR_CMD = 241, 243, 246, 249, 239
BINARY, ECHO, SGA, TTYPE, EOR, NAWS = 0, 1, 3, 24, 25, 31
TTYPE_IS, TTYPE_SEND = 0, 1

WE_SUPPORT = {BINARY, SGA, TTYPE, NAWS}     # options we will enable locally
THEY_MAY = {BINARY, ECHO, SGA}              # options the server may enable
# TN3270: no NAWS (the screen size comes from the terminal type).
WE_SUPPORT_3270 = {BINARY, SGA, TTYPE, EOR}
THEY_MAY_3270 = {BINARY, SGA, EOR}

_DATA, _IAC, _VERB, _SB, _SB_IAC, _CR = range(6)


class TelnetProtocol:
    def __init__(self, send: Callable[[bytes], None], term_type: str = "VT220",
                 cols: int = 80, rows: int = 24, tn3270: bool = False):
        self.send = send
        self.term_type = term_type
        self.tn3270 = tn3270
        self.we_support = WE_SUPPORT_3270 if tn3270 else WE_SUPPORT
        self.they_may = THEY_MAY_3270 if tn3270 else THEY_MAY
        self.cols, self.rows = cols, rows
        self.local: set[int] = set()     # options enabled on our side (WILL acked)
        self.remote: set[int] = set()    # options enabled on the server side
        self._asked: set[tuple[int, int]] = set()   # (verb, opt) we sent unprompted
        self._state = _DATA
        self._verb = 0
        self._sb = bytearray()

    @property
    def server_echoes(self) -> bool:
        return ECHO in self.remote

    def start(self) -> None:
        """Offer the options a terminal client normally wants."""
        offers = ((WILL, TTYPE), (WILL, NAWS), (DO, SGA), (DO, ECHO))
        if self.tn3270:
            # TN3270 hosts lead the negotiation, and some (Hercules) expect
            # exact replies to their own requests, so offer nothing.
            offers = ()
        for verb, opt in offers:
            self._asked.add((verb, opt))
            self._send_cmd(verb, opt)

    # ------------------------------------------------------------- outgoing

    def _send_cmd(self, verb: int, opt: int) -> None:
        self.send(bytes([IAC, verb, opt]))

    def encode(self, data: bytes) -> bytes:
        data = data.replace(b"\xff", b"\xff\xff")
        if self.tn3270:
            return data + bytes([IAC, EOR_CMD])
        if BINARY not in self.local:
            # NVT rule: a bare CR is sent as CR NUL.
            out = bytearray()
            for i, b in enumerate(data):
                out.append(b)
                if b == 0x0d and (i + 1 >= len(data) or data[i + 1] != 0x0a):
                    out.append(0)
            data = bytes(out)
        return data

    def send_naws(self) -> None:
        if NAWS in self.local:
            payload = struct.pack(">HH", self.cols, self.rows).replace(b"\xff", b"\xff\xff")
            self.send(bytes([IAC, SB, NAWS]) + payload + bytes([IAC, SE]))

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.send_naws()

    def brk(self) -> bytes:
        return bytes([IAC, BRK])

    # ------------------------------------------------------------- incoming

    def receive(self, data: bytes) -> bytes:
        """Consume bytes from the server; return the application data."""
        out = bytearray()
        for b in data:
            st = self._state
            if st == _DATA:
                if b == IAC:
                    self._state = _IAC
                elif b == 0x0d and BINARY not in self.remote and not self.tn3270:
                    out.append(b)
                    self._state = _CR
                else:
                    out.append(b)
            elif st == _CR:
                self._state = _DATA
                if b == 0:
                    continue          # CR NUL -> CR
                if b == IAC:
                    self._state = _IAC
                else:
                    out.append(b)
            elif st == _IAC:
                if b == IAC:
                    out += b"\xff\xff" if self.tn3270 else b"\xff"
                    self._state = _DATA
                elif b == EOR_CMD and self.tn3270:
                    out += bytes([IAC, EOR_CMD])
                    self._state = _DATA
                elif b in (DO, DONT, WILL, WONT):
                    self._verb = b
                    self._state = _VERB
                elif b == SB:
                    self._sb.clear()
                    self._state = _SB
                else:
                    self._state = _DATA   # NOP, GA, DM, ...
            elif st == _VERB:
                self._negotiate(self._verb, b)
                self._state = _DATA
            elif st == _SB:
                if b == IAC:
                    self._state = _SB_IAC
                else:
                    self._sb.append(b)
            elif st == _SB_IAC:
                if b == SE:
                    self._subnegotiation(bytes(self._sb))
                    self._state = _DATA
                else:
                    if b == IAC:
                        self._sb.append(IAC)
                    self._state = _SB
        return bytes(out)

    def _negotiate(self, verb: int, opt: int) -> None:
        # Reply only on a change of state, so negotiation cannot loop.
        if verb == DO:
            if opt in self.we_support:
                if opt not in self.local:
                    self.local.add(opt)
                    if (WILL, opt) in self._asked:
                        self._asked.discard((WILL, opt))   # it acks our offer
                    else:
                        self._send_cmd(WILL, opt)
                if opt == NAWS:
                    self.send_naws()
            else:
                self._send_cmd(WONT, opt)
        elif verb == DONT:
            self._asked.discard((WILL, opt))
            if opt in self.local:
                self.local.discard(opt)
                self._send_cmd(WONT, opt)
        elif verb == WILL:
            if opt in self.they_may:
                if opt not in self.remote:
                    self.remote.add(opt)
                    if (DO, opt) in self._asked:
                        self._asked.discard((DO, opt))
                    else:
                        self._send_cmd(DO, opt)
            else:
                self._send_cmd(DONT, opt)
        elif verb == WONT:
            self._asked.discard((DO, opt))
            if opt in self.remote:
                self.remote.discard(opt)
                self._send_cmd(DONT, opt)

    def _subnegotiation(self, sb: bytes) -> None:
        if len(sb) >= 2 and sb[0] == TTYPE and sb[1] == TTYPE_SEND:
            self.send(bytes([IAC, SB, TTYPE, TTYPE_IS]) + self.term_type.encode("ascii")
                      + bytes([IAC, SE]))


class TelnetTransport(Transport):
    def __init__(self, host: str, port: int = 23, term_type: str = "VT220",
                 timeout: float = 15.0, tn3270: bool = False, tls: bool = False,
                 tls_verify: bool = True):
        super().__init__()
        self.host, self.port, self.timeout = host, port, timeout
        self.tls, self.tls_verify = tls, tls_verify
        self.sock: socket.socket | None = None
        self.proto = TelnetProtocol(self._raw_send, term_type, tn3270=tn3270)

    def _raw_send(self, data: bytes) -> None:
        if self.sock:
            self.sock.sendall(data)

    def _open(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.tls:
            ctx = ssl.create_default_context()
            if not self.tls_verify:
                # Many mainframes use certificates from an in-house CA.
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            try:
                sock = ctx.wrap_socket(sock, server_hostname=self.host)
            except (OSError, ssl.SSLError):
                sock.close()
                raise
        self.sock = sock
        self.sock.settimeout(None)
        self.proto.cols, self.proto.rows = self.cols, self.rows
        self.proto.start()

    def _read(self) -> bytes:
        while True:
            raw = self.sock.recv(65536)
            if not raw:
                return b""
            data = self.proto.receive(raw)
            if data:
                return data

    def _write(self, data: bytes) -> None:
        self._raw_send(self.proto.encode(data))

    def resize(self, cols: int, rows: int) -> None:
        super().resize(cols, rows)
        if self.sock:
            self.proto.resize(cols, rows)

    def send_break(self) -> None:
        self._raw_send(self.proto.brk())

    @property
    def server_echoes(self) -> bool:
        return self.proto.server_echoes

    def _close(self) -> None:
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
