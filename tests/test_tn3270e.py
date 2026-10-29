"""TN3270E negotiation, LU names, and the 3287 printer session."""

import os
import socket
import sys
import threading
import time

import pytest

from cherminal.config import ProfileStore, SessionProfile
from cherminal.emulation import create
from cherminal.emulation.ibm3287 import SCSPrinter, lu3_text
from cherminal.screen import Screen
from cherminal.session import Session
from cherminal.transport.telnet import (DO, DONT, IAC, SB, SE, TN3270E, TTYPE, WILL, WONT,
                                        TelnetProtocol)
from test_ibm3270 import LOGON, addr, e, record

EOR_CMD = 0xEF


def sb(*parts) -> bytes:
    body = b"".join(p if isinstance(p, bytes) else bytes([p]) for p in parts)
    return bytes([IAC, SB, TN3270E]) + body + bytes([IAC, SE])


# --------------------------------------------------------------- negotiation


def test_printer_negotiation_bytes():
    out, agreed = [], []
    p = TelnetProtocol(out.append, "IBM-3287-1", tn3270=True, tn3270e=True, lu_name="PRT001",
                       functions=(0, 1, 2, 3))
    p.on_tn3270e = lambda *a: agreed.append(a)
    p.receive(bytes([IAC, DO, TN3270E]))
    assert out.pop() == bytes([IAC, WILL, TN3270E])
    p.receive(sb(8, 2))                                   # SEND DEVICE-TYPE
    assert out.pop() == sb(2, 7, b"IBM-3287-1", 1, b"PRT001")
    p.receive(sb(2, 4, b"IBM-3287-1", 1, b"PRT001"))       # DEVICE-TYPE IS ... CONNECT
    assert out.pop() == sb(3, 7, bytes([0, 1, 2, 3]))      # FUNCTIONS REQUEST
    p.receive(sb(3, 4, bytes([1, 2, 3])))                 # FUNCTIONS IS
    assert out == [] and agreed == [("IBM-3287-1", "PRT001", (1, 2, 3))]
    assert p.tn3270e_active


def test_functions_counter_proposals_and_rejects():
    out, agreed = [], []
    p = TelnetProtocol(out.append, "IBM-3278-2-E", tn3270=True, tn3270e=True)
    p.on_tn3270e = lambda *a: agreed.append(a)
    p.receive(bytes([IAC, DO, TN3270E]) + sb(8, 2))
    assert out[-1] == sb(2, 7, b"IBM-3278-2-E")            # no LU: no CONNECT
    p.receive(sb(2, 4, b"IBM-3278-2-E", 1, b"TCP00042"))
    assert out[-1] == sb(3, 7, bytes([2]))                 # displays ask for RESPONSES
    p.receive(sb(3, 7, bytes([2, 4])))                     # host wants SYSREQ as well
    assert out[-1] == sb(3, 7, bytes([2])) and not agreed
    p.receive(sb(3, 7, b""))                               # host offers none: agree
    assert out[-1] == sb(3, 4, b"") and agreed == [("IBM-3278-2-E", "TCP00042", ())]
    bad = TelnetProtocol(out.append, "IBM-3287-1", tn3270=True, tn3270e=True, lu_name="NOPE")
    bad.receive(bytes([IAC, DO, TN3270E]) + sb(8, 2) + sb(2, 6, 5, 3))
    assert bad.error == "the host refused LU NOPE: the host does not know that LU name"


def test_plain_tn3270_still_refuses_tn3270e():
    out = []
    p = TelnetProtocol(out.append, "IBM-3278-2-E", tn3270=True)
    p.receive(bytes([IAC, DO, TN3270E]))
    assert out == [bytes([IAC, WONT, TN3270E])]


def test_lu_name_profile_rules(tmp_path):
    assert SessionProfile(transport="telnet", emulation="ibm3278-2", lu_name="tso#1").lu_name \
        == "TSO#1"
    for bad in ("TOOLONG99", "LU-1", "LU 1"):
        with pytest.raises(ValueError, match="LU name"):
            SessionProfile(transport="telnet", emulation="ibm3278-2", lu_name=bad)
    from cherminal.transport import from_profile
    t = from_profile(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2"))
    assert TN3270E not in t.proto.we_support                # nothing changes without an LU
    t = from_profile(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2",
                                    lu_name="TSO1"))
    assert TN3270E in t.proto.we_support and t.proto.lu_name == "TSO1"
    t = from_profile(SessionProfile(transport="telnet", host="h", emulation="ibm3287-1"))
    assert TN3270E in t.proto.we_support and t.proto.functions == (0, 1, 2, 3)
    assert t.proto.term_type == "IBM-3287-1"
    with pytest.raises(ValueError):
        SessionProfile(transport="ssh", emulation="ibm3287-1")


# ------------------------------------------------------- display with headers


def test_display_records_carry_headers():
    sent = []
    em = create("ibm3278-2", Screen(80, 24), sent.append)
    em.set_tn3270e("IBM-3278-2-E", "TSO1", (2,))
    assert "LU TSO1" in em.status
    em.feed(record(b"\x00\x00\x02\x00\x07" + LOGON))      # 3270-DATA, ALWAYS-RESPONSE
    assert sent == [b"\x02\x00\x00\x00\x07\x00"]          # positive response, DEVICE-END
    assert "USERID" in em.screen.text()
    em.type_text("me")
    em.do_action("enter")
    assert sent[-1][:5] == b"\x00\x00\x00\x00\x00" and sent[-1][5:6] == b"\x7d"
    em.feed(record(b"\x00\x00\x02\x00\x08\xf6"))          # Read Modified, response wanted
    assert sent[-2] == b"\x02\x00\x00\x00\x08\x00"         # response first, then the data
    assert sent[-1][:5] == b"\x00\x00\x00\x00\x01"         # our sequence number moved on
    em.feed(record(b"\x07\x00\x00\x00\x09" + e("USS")))   # SSCP-LU-DATA: ignored
    assert "USS" not in em.screen.text()


# ------------------------------------------------------------ SCS and LU3


def scs(text: str) -> bytes:
    return text.encode("cp037")


def test_scs_decoding():
    p = SCSPrinter()
    p.feed(scs("HELLO") + b"\x15" + scs("WORLD") + b"\x0d" + scs("_____") + b"\x15")
    p.feed(scs("A") + b"\x05" + scs("B") + b"\x25" + scs("C") + b"\x15")
    p.feed(b"\x2b\xc1\x04\x14\x05\x00\x0d" + scs("left margin") + b"\x15")  # SHF: LM 5, CR
    p.feed(b"\x2b\xc1\x05\x50\x01\x00\x0a\x0d" + scs("x") + b"\x05" + scs("tab") + b"\x15")
    p.feed(b"\x0c" + scs("PAGE 2") + b"\x35\x03\x1b(s" + b"\x16" + scs("!") + b"\x00\x15")
    # CR then underscores overprint WORLD's columns (the last character wins).
    assert p.take() == ("HELLO\n_____\n"
                        "A B\n   C\n"        # HT with no stops is a space; LF keeps the column
                        "    left margin\n"
                        "x        tab\n"     # tab stop at column 10
                        "\fPAGE 2(!\n")      # TRN, then BS overprints


def test_scs_long_lines_wrap_and_orders_split_across_records():
    p = SCSPrinter()
    p.feed(b"\x2b\xc1\x02\x0a")                           # SHF: 10 columns
    p.feed(scs("0123456789AB") + b"\x2b")                 # the next order is split
    p.feed(b"\xc1\x02\x50" + scs("12") + b"\x35")
    p.feed(b"\x02AB\x15")
    assert p.take() == "0123456789\nAB12AB\n"


def test_lu3_print_formats():
    buf, fa = [0] * 200, [None] * 200
    text = e("LINE ONE") + b"\x15" + e("LINE TWO") + b"\x0c" + e("PAGE") + b"\x19" + e("NOT")
    buf[:len(text)] = list(text)
    assert lu3_text(buf, fa, len(text), 0x08, "cp037") == "LINE ONE\nLINE TWO\fPAGE\n"
    buf, fa = [0x40] * 120, [None] * 120
    buf[0:5] = list(e("HELLO"))
    fa[50] = 0x2C                                         # a hidden field: not printed
    buf[51:57] = list(e("SECRET"))
    fa[80] = 0x20                                         # protected, visible again
    buf[81:88] = list(e("VISIBLE"))
    assert lu3_text(buf, fa, 120, 0x18, "cp037") == "HELLO\n\n VISIBLE\n"   # 40 columns


def test_printer_emulation_jobs():
    em = create("ibm3287-1", Screen(80, 24), lambda d: None)
    assert em.printer and not em.job_open
    jobs = []
    em.on_job = jobs.append
    em.set_tn3270e("IBM-3287-1", "PRT001", (0, 1, 2, 3))
    em.feed(record(b"\x01\x00\x00\x00\x01" + scs("PAYROLL REPORT") + b"\x15"))
    assert em.job_open and jobs == []
    em.feed(record(b"\x08\x00\x00\x00\x02"))               # PRINT-EOJ
    assert jobs == ["PAYROLL REPORT\n"] and em.jobs == 1
    text = em.screen.text()
    assert "Printer session — PRT001 — connected — 1 job printed" in text
    assert "PAYROLL REPORT" in text
    # LU3 data, then the idle timeout ends the job.
    em.feed(record(b"\x00\x00\x00\x00\x03" + b"\xf5\x48" + e("LU3 PAGE")))
    em.tick(time.monotonic() + 1)
    assert len(jobs) == 1
    em.tick(time.monotonic() + 6)
    assert jobs[-1] == "LU3 PAGE\n" and em.jobs == 2
    em.notice("connection closed")
    assert "connection closed" in em.screen.text()


# ------------------------------------------------------------- fake hosts


class FakeTN3270EHost(threading.Thread):
    """Negotiates TN3270E (device type, CONNECT, functions) and then sends
    ``records`` (each given its TN3270E header), collecting what comes back."""

    def __init__(self, records: list[bytes], accept_lu: str | None = None):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.records = records
        self.accept_lu = accept_lu
        self.request = b""
        self.functions = b""
        self.got = b""
        self.done = threading.Event()

    def _until(self, conn, marker: bytes) -> bytes:
        buf = b""
        while marker not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def run(self):
        conn, _ = self.srv.accept()
        conn.settimeout(10)
        try:
            conn.sendall(bytes([IAC, DO, TN3270E]))
            self._until(conn, bytes([IAC, WILL, TN3270E]))
            conn.sendall(sb(8, 2))
            buf = self._until(conn, bytes([IAC, SE]))
            self.request = buf[buf.index(bytes([IAC, SB])):]
            device = self.request[5:].split(bytes([1]))[0].split(bytes([IAC]))[0]
            lu = self.request.split(bytes([1]))[1][:-2] if b"\x01" in self.request[5:] \
                else b"PRT0042"
            if self.accept_lu is not None and lu.decode() != self.accept_lu:
                conn.sendall(sb(2, 6, 5, 3))
                conn.recv(100)
                return
            conn.sendall(sb(2, 4, device, 1, lu))
            buf = self._until(conn, bytes([IAC, SE]))
            self.functions = buf[buf.index(bytes([IAC, SB])) + 5:-2]
            conn.sendall(sb(3, 4, self.functions))
            for rec in self.records:
                conn.sendall(record(rec))
                time.sleep(0.05)
            conn.settimeout(1)
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    self.got += chunk
            except OSError:
                pass
        finally:
            self.done.set()
            conn.close()


def _wait(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.02)
    return cond()


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.skipif(sys.platform == "win32", reason="CUPS lp; Windows uses the spooler")
def test_printer_session_job_reaches_lp(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    from cherminal.gui.terminal import TerminalWidget
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "lp").write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/args\ncat > {tmp_path}/job\n')
    (bin_dir / "lp").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    job = (b"\x2b\xc1\x02\x50" + scs("MONTHLY STATEMENT") + b"\x15\x15"
           + scs("ACCOUNT 12345") + b"\x05" + scs("BALANCE 99.00") + b"\x15\x0c"
           + scs("PAGE 2") + b"\x15")
    host = FakeTN3270EHost([b"\x03\x00\x00\x00\x00" + bytes(10),           # BIND-IMAGE
                            b"\x01\x00\x02\x00\x01" + job[:20],             # SCS, response
                            b"\x01\x00\x02\x00\x02" + job[20:],
                            b"\x08\x00\x00\x00\x03"])                       # PRINT-EOJ
    host.start()
    profile = SessionProfile(name="Payroll printer", transport="telnet", host="127.0.0.1",
                             port=host.port, emulation="ibm3287-1", lu_name="PRT001",
                             printer="front-desk")
    s = Session(profile, ProfileStore(tmp_path, site_roots=[]))
    term = TerminalWidget(s)
    term.connect_session()
    try:
        assert _wait(lambda: (QApplication.processEvents() or (tmp_path / "job").exists()))
        assert host.request == sb(2, 7, b"IBM-3287-1", 1, b"PRT001")
        assert host.functions == bytes([0, 1, 2, 3])
        _wait(lambda: QApplication.processEvents() or (tmp_path / "job").stat().st_size > 0)
        assert (tmp_path / "job").read_text() == ("MONTHLY STATEMENT\n\nACCOUNT 12345 "
                                                  "BALANCE 99.00\n\fPAGE 2\n")
        args = (tmp_path / "args").read_text().split()
        assert args[:2] == ["-s", "-t"] and args[-2:] == ["-d", "front-desk"]
        assert "PRT001" in args
        _wait(lambda: QApplication.processEvents() or "Printed" in s.emulation.print_result)
        text = s.screen.text()
        assert "PRT001 — connected — 1 job printed" in text and "MONTHLY STATEMENT" in text
        assert host.done.wait(5)
        assert b"\x02\x00\x00\x00\x01\x00" in host.got and b"\x02\x00\x00\x00\x02\x00" in host.got
        term.grab()
    finally:
        s.disconnect()


def test_display_session_connects_to_named_lu(tmp_path):
    host = FakeTN3270EHost([b"\x00\x00\x00\x00\x00" + LOGON], accept_lu="TSO0001")
    host.start()
    s = Session(SessionProfile(name="tso", transport="telnet", host="127.0.0.1", port=host.port,
                               emulation="ibm3278-2", lu_name="tso0001"),
                ProfileStore(tmp_path, site_roots=[]))
    s.connect()
    try:
        assert _wait(lambda: "USERID" in s.screen.text())
        assert host.request == sb(2, 7, b"IBM-3278-2-E", 1, b"TSO0001")
        assert "LU TSO0001" in s.emulation.status
        s.key("Enter")
        assert host.done.wait(5)
        assert b"\x00\x00\x00\x00\x00\x7d" in host.got
    finally:
        s.disconnect()


def test_refused_lu_closes_with_the_reason(tmp_path):
    host = FakeTN3270EHost([], accept_lu="OTHER")
    host.start()
    s = Session(SessionProfile(transport="telnet", host="127.0.0.1", port=host.port,
                               emulation="ibm3287-1", lu_name="PRT9"),
                ProfileStore(tmp_path, site_roots=[]))
    closed = []
    s.connect(on_closed=closed.append)
    try:
        assert _wait(lambda: closed)
        assert closed[0] == "the host refused LU PRT9: the host does not know that LU name"
    finally:
        s.disconnect()


def test_editor_lu_field(app, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    ed = SessionEditor(SessionProfile(name="p", transport="telnet", host="h",
                                      emulation="ibm3287-1", lu_name="PRT001"),
                       ProfileStore(tmp_path, site_roots=[]))
    assert ed._form.isRowVisible(ed.lu_name) and ed._build().lu_name == "PRT001"
    ed.emulation.setCurrentText("vt220")
    assert not ed._form.isRowVisible(ed.lu_name)
    ed.emulation.setCurrentText("ibm3278-2")
    ed.lu_name.setText("tso1")
    assert ed._build().lu_name == "TSO1"
    ed.transport.setCurrentText("ssh")
    assert not ed._form.isRowVisible(ed.lu_name)
