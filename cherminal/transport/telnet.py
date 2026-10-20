"""Telnet client (RFC 854) with BINARY, ECHO, SGA, TTYPE, NAWS, EOR and NEW-ENVIRON.

In record mode, for TN3270 (RFC 1576) and TN5250 (RFC 1205), the session is
binary both ways and framed in records: incoming data keeps 0xFF doubled and
each IAC EOR, so the emulation can find record boundaries, and each write is
sent as one record. For TN5250 a workstation device name can be given; it is
sent as the NEW-ENVIRON (RFC 1572) user variable DEVNAME (RFC 4777).

TN3270E (RFC 2355) is negotiated only when asked for: for a 3287 printer
session, or a display session with an LU name. The protocol then agrees the
device type (and CONNECTs to the named LU) and the functions; the records
that follow carry the 5-byte TN3270E header, which the emulation reads and
writes itself (see ``on_tn3270e``).

``TelnetProtocol`` is the pure option-negotiation state machine, kept
separate from sockets so it can be tested directly.
"""

from __future__ import annotations

import socket
import ssl
import struct
from typing import Callable

from .base import Transport, tcp_keepalive

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
NOP, BRK, AYT, GA, EOR_CMD = 241, 243, 246, 249, 239
BINARY, ECHO, SGA, TTYPE, EOR, NAWS, NEW_ENVIRON = 0, 1, 3, 24, 25, 31, 39
TTYPE_IS, TTYPE_SEND = 0, 1
ENV_IS, ENV_SEND = 0, 1
ENV_VAR, ENV_VALUE, ENV_ESC, ENV_USERVAR = 0, 1, 2, 3

WE_SUPPORT = {BINARY, SGA, TTYPE, NAWS}     # options we will enable locally
THEY_MAY = {BINARY, ECHO, SGA}              # options the server may enable
MAX_SUBNEGOTIATION = 4096                   # bytes of one IAC SB ... IAC SE kept
# TN3270: no NAWS (the screen size comes from the terminal type).
WE_SUPPORT_3270 = {BINARY, SGA, TTYPE, EOR}
THEY_MAY_3270 = {BINARY, SGA, EOR}

_DATA, _IAC, _VERB, _SB, _SB_IAC, _CR = range(6)

# TN3270E (RFC 2355): option, subnegotiation codes, functions, reject reasons.
TN3270E = 40
E_ASSOCIATE, E_CONNECT, E_DEVICE_TYPE, E_FUNCTIONS, E_IS, E_REASON, E_REJECT, E_REQUEST, \
    E_SEND = range(9)
F_BIND_IMAGE, F_DATA_STREAM_CTL, F_RESPONSES, F_SCS_CTL_CODES, F_SYSREQ = range(5)
FUNCTIONS_DISPLAY = (F_RESPONSES,)
FUNCTIONS_PRINTER = (F_BIND_IMAGE, F_DATA_STREAM_CTL, F_RESPONSES, F_SCS_CTL_CODES)
REJECT_REASONS = {
    0: "the LU is not available to this connection", 1: "the LU is already in use",
    2: "the associated display is not known", 3: "the host does not know that LU name",
    4: "the host does not support that device type", 5: "the LU is not that device type",
    6: "unknown error", 7: "the host does not support that request"}


class TelnetProtocol:
    def __init__(self, send: Callable[[bytes], None], term_type: str = "VT220",
                 cols: int = 80, rows: int = 24, tn3270: bool = False,
                 device_name: str = "", tn3270e: bool = False, lu_name: str = "",
                 functions: tuple[int, ...] = FUNCTIONS_DISPLAY):
        self.send = send
        self.term_type = term_type
        self.tn3270 = tn3270            # record mode: TN3270 or TN5250
        self.device_name = device_name
        self.we_support = WE_SUPPORT_3270 if tn3270 else WE_SUPPORT
        if tn3270 and device_name:
            self.we_support = self.we_support | {NEW_ENVIRON}
        # TN3270E: offered only when wanted, so other 3270 sessions stay as they were.
        if tn3270 and tn3270e:
            self.we_support = self.we_support | {TN3270E}
        self.lu_name = lu_name
        self.functions = tuple(functions)
        self.tn3270e_active = False
        self.device_type = ""
        # Called once TN3270E is agreed: (device type, LU name, functions).
        self.on_tn3270e: Callable[[str, str, tuple[int, ...]], None] = lambda d, lu, f: None
        self.error = ""           # set when the host refuses the device; ends the session
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
            # TN3270/TN5250 hosts lead the negotiation, and some (Hercules)
            # expect exact replies to their own requests, so offer nothing.
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
                elif len(self._sb) < MAX_SUBNEGOTIATION:
                    self._sb.append(b)      # past the limit the rest is dropped
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
        if sb[:1] == bytes([TN3270E]):
            self._tn3270e(sb[1:])
            return
        if len(sb) >= 2 and sb[0] == TTYPE and sb[1] == TTYPE_SEND:
            self.send(bytes([IAC, SB, TTYPE, TTYPE_IS]) + self.term_type.encode("ascii")
                      + bytes([IAC, SE]))
        elif len(sb) >= 2 and sb[0] == NEW_ENVIRON and sb[1] == ENV_SEND \
                and NEW_ENVIRON in self.local:
            # Only the device name is sent: no user or password (no auto sign-on).
            env = bytes([ENV_USERVAR]) + _env_escape(b"DEVNAME") + bytes([ENV_VALUE]) + \
                _env_escape(self.device_name.encode("ascii"))
            self.send(bytes([IAC, SB, NEW_ENVIRON, ENV_IS]) + env + bytes([IAC, SE]))

    # ------------------------------------------------------------ TN3270E

    def _send_e(self, *parts) -> None:
        body = b"".join(p if isinstance(p, bytes) else bytes([p]) for p in parts)
        self.send(bytes([IAC, SB, TN3270E]) + body.replace(b"\xff", b"\xff\xff")
                  + bytes([IAC, SE]))

    def _tn3270e(self, sb: bytes) -> None:
        if sb[:2] == bytes([E_SEND, E_DEVICE_TYPE]):
            connect = (bytes([E_CONNECT]) + self.lu_name.encode("ascii")) if self.lu_name else b""
            self._send_e(E_DEVICE_TYPE, E_REQUEST, self.term_type.encode("ascii"), connect)
        elif sb[:2] == bytes([E_DEVICE_TYPE, E_IS]):
            device, _, lu = sb[2:].partition(bytes([E_CONNECT]))
            self.device_type = device.decode("ascii", "replace")
            self.lu_name = lu.decode("ascii", "replace")
            self._send_e(E_FUNCTIONS, E_REQUEST, bytes(self.functions))
        elif sb[:2] == bytes([E_DEVICE_TYPE, E_REJECT]):
            code = sb[3] if len(sb) > 3 and sb[2] == E_REASON else 6
            what = f"LU {self.lu_name}" if self.lu_name else self.term_type
            self.error = (f"the host refused {what}: "
                          f"{REJECT_REASONS.get(code, 'unknown error')}")
        elif sb[:2] == bytes([E_FUNCTIONS, E_IS]):
            self._tn3270e_agreed(tuple(sb[2:]))
        elif sb[:2] == bytes([E_FUNCTIONS, E_REQUEST]):
            theirs = tuple(sb[2:])
            if set(theirs) <= set(self.functions):
                self._send_e(E_FUNCTIONS, E_IS, bytes(theirs))   # a subset: agree
                self._tn3270e_agreed(theirs)
            else:
                self._send_e(E_FUNCTIONS, E_REQUEST,
                             bytes(f for f in theirs if f in self.functions))

    def _tn3270e_agreed(self, functions: tuple[int, ...]) -> None:
        self.tn3270e_active = True
        self.functions = functions
        self.on_tn3270e(self.device_type, self.lu_name, functions)


def _env_escape(text: bytes) -> bytes:
    """Escape NEW-ENVIRON control bytes (and double IAC) inside a name or value."""
    out = bytearray()
    for b in text:
        if b in (ENV_VAR, ENV_VALUE, ENV_ESC, ENV_USERVAR):
            out.append(ENV_ESC)
        out.append(b)
        if b == IAC:
            out.append(IAC)
    return bytes(out)


class TelnetTransport(Transport):
    def __init__(self, host: str, port: int = 23, term_type: str = "VT220",
                 timeout: float = 15.0, tn3270: bool = False, tls: bool = False,
                 tls_verify: bool = True, ca_file: str = "", device_name: str = "",
                 tn3270e: bool = False, lu_name: str = "", printer: bool = False):
        super().__init__()
        self.host, self.port, self.timeout = host, port, timeout
        self.tls, self.tls_verify = tls, tls_verify
        self.ca_file = ca_file        # extra CA certificates (e.g. an in-house CA)
        self.sock: socket.socket | None = None
        self.proto = TelnetProtocol(self._raw_send, term_type, tn3270=tn3270,
                                    device_name=device_name,
                                    tn3270e=tn3270e, lu_name=lu_name,
                                    functions=FUNCTIONS_PRINTER if printer
                                    else FUNCTIONS_DISPLAY)

    @property
    def on_tn3270e(self):
        return self.proto.on_tn3270e

    @on_tn3270e.setter
    def on_tn3270e(self, callback) -> None:
        self.proto.on_tn3270e = callback

    def _raw_send(self, data: bytes) -> None:
        if self.sock:
            self.sock.sendall(data)

    def _open(self) -> None:
        ctx = None
        if self.tls:
            ctx = ssl.create_default_context()
            if self.ca_file:
                # An in-house CA, so its mainframes can be checked rather than
                # having to turn checking off.
                ctx.load_verify_locations(cafile=self.ca_file)
            if not self.tls_verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.keepalive:
            tcp_keepalive(sock, self.keepalive)
        if ctx:
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
            if self.proto.error:
                raise OSError(self.proto.error)
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

    def _keepalive(self) -> None:
        self._raw_send(bytes([IAC, NOP]))   # ignored by every Telnet and TN3270 host

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
