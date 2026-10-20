"""IND$FILE (DFT) file transfers against a fake TSO host."""

import socket
import threading
import time

import pytest

from cherminal import policy
from cherminal.config import ProfileStore, SessionProfile
from cherminal.emulation.indfile import DFTTransfer, TransferOptions
from cherminal.session import Session
from cherminal.transport.telnet import BINARY, DO, EOR, IAC, SB, SE, TTYPE, WILL
from test_ibm3270 import addr, e, emu, record

EOR_CMD = 0xEF

# TSO READY with a command line at the bottom (as ISPF option 6 would have).
READY = (b"\xf5\xc3" + b"\x11" + addr(0, 0) + b"\x1d\x60" + e("READY")
         + b"\x11" + addr(22, 0) + b"\x1d\x60" + e("===>") + b"\x1d\x40" + b"\x13"
         + b"\x11" + addr(23, 79) + b"\x1d\x60")


def sf(body: bytes) -> bytes:
    return (len(body) + 2).to_bytes(2, "big") + body


def wsf(*fields: bytes) -> bytes:
    return b"\xf3" + b"".join(fields)


def open_req(name: bytes, recsz: int | None = None) -> bytes:
    if recsz is None:                                     # 0x23: download / message
        return sf(b"\xd0\x00\x12" + bytes(23) + name)
    return sf(b"\xd0\x00\x12" + bytes(25) + recsz.to_bytes(2, "big") + bytes(2) + name)


def data_insert(data: bytes) -> bytes:
    return sf(b"\xd0\x47\x04\xc0\x80\x61" + (len(data) + 5).to_bytes(2, "big") + data)


INSERT, SET_CURSOR = sf(b"\xd0\x47\x11"), sf(b"\xd0\x45\x11")
GET, CLOSE = sf(b"\xd0\x46\x11"), sf(b"\xd0\x41\x12")
OPEN_ACK = b"\x88\x00\x05\xd0\x00\x09"
CLOSE_ACK = b"\x88\x00\x05\xd0\x41\x09"


def ack(n: int) -> bytes:
    return b"\x88\x00\x0b\xd0\x47\x05\x63\x06" + n.to_bytes(4, "big")


def message(text: bytes) -> list[bytes]:
    return [wsf(open_req(b"FT:MSG ")), wsf(INSERT, data_insert(text)), wsf(CLOSE)]


# --------------------------------------------------------------- unit level


def test_commands_for_tso_cics_and_vm():
    assert TransferOptions(True, "'CHAD.DATA'", "f", recfm="F", lrecl=80, blksize=3120,
                           space_units="cylinders", primary=2, secondary=1).command() == \
        "IND$FILE PUT 'CHAD.DATA' ASCII CRLF RECFM(F) LRECL(80) BLKSIZE(3120) " \
        "SPACE(2,1) CYLINDERS"
    assert TransferOptions(True, "X", "f", space_units="avblock", primary=10,
                           avblock=800, ascii=False).command() == \
        "IND$FILE PUT X SPACE(10) AVBLOCK(800)"
    assert TransferOptions(False, "REPORT", "f", host="cics").command() == \
        "IND$FILE GET REPORT (ASCII CRLF"
    assert TransferOptions(True, "PAYROLL", "f", host="cics", ascii=False,
                           append=True).command() == "IND$FILE PUT PAYROLL (BINARY NOCRLF APPEND"
    assert TransferOptions(True, "PROFILE EXEC A", "f", host="vm", recfm="V",
                           lrecl=255).command() == \
        "IND$FILE PUT PROFILE EXEC A (ASCII CRLF RECFM V LRECL 255"
    assert TransferOptions(False, "'A.B'", "f", recfm="F", lrecl=80).command() == \
        "IND$FILE GET 'A.B' ASCII CRLF"                    # allocation is for PUT only
    with pytest.raises(ValueError):
        TransferOptions(True, "", "f")
    with pytest.raises(ValueError):
        TransferOptions(True, "X", "f", host="ims")


def test_ascii_translation_round_trip(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("Grüße, €100\nzweite Zeile\n", encoding="utf-8")
    up = DFTTransfer(TransferOptions(True, "X", str(src)), "cp1140")
    host = up.file.data
    assert host.endswith(b"Zeile\r\n") and b"\r\n" in host
    down = DFTTransfer(TransferOptions(False, "X", str(tmp_path / "out.txt")), "cp1140")
    assert down._from_host(host + b"\x1a").decode() == "Grüße, €100\nzweite Zeile\n"
    down.finish(True, "")


def test_dft_receive_state_machine(tmp_path):
    out = tmp_path / "got.bin"
    progress, done = [], []
    t = DFTTransfer(TransferOptions(False, "X", str(out), ascii=False), "cp037",
                    lambda n, total: progress.append(n), lambda ok, m: done.append((ok, m)))
    assert t.handle(open_req(b"FT:DATA")) == OPEN_ACK
    assert t.handle(INSERT) is None
    assert t.handle(data_insert(b"\x00\x01\xff")) == ack(1)
    assert t.handle(data_insert(b"abc")) == ack(2)
    assert t.handle(CLOSE) == CLOSE_ACK
    assert t.handle(open_req(b"FT:MSG ")) == OPEN_ACK
    assert t.handle(data_insert(b"TRANS03 File transfer complete$")) == ack(1)
    assert done == [(True, "TRANS03 File transfer complete")]
    assert out.read_bytes() == b"\x00\x01\xffabc" and progress == [3, 6]
    assert t.handle(CLOSE) is None                        # x3270 leaves it unanswered


def test_dft_send_eof_and_cancel(tmp_path):
    src = tmp_path / "up.bin"
    src.write_bytes(bytes(range(256)) * 40)               # 10 240 bytes: three buffers
    t = DFTTransfer(TransferOptions(True, "X", str(src), ascii=False))
    assert t.handle(open_req(b"FT:DATA", recsz=80)) == OPEN_ACK
    got = b""
    for n in range(1, 4):
        reply = t.handle(GET)
        assert reply[:12] == b"\x88" + reply[1:3] + b"\xd0\x46\x05\x63\x06" + n.to_bytes(4, "big")
        assert reply[12:15] == b"\xc0\x80\x61"
        size = int.from_bytes(reply[15:17], "big") - 5
        assert int.from_bytes(reply[1:3], "big") == len(reply) - 1
        got += reply[17:17 + size]
    assert got == src.read_bytes()
    assert t.handle(GET) == b"\x88\x00\x09\xd0\x46\x08\x69\x04\x22\x00"   # end of file
    t.finish(True, "")
    # Cancelling: the next request is answered with an error.
    t = DFTTransfer(TransferOptions(True, "X", str(src), ascii=False))
    t.handle(open_req(b"FT:DATA", recsz=80))
    t.cancel()
    assert t.handle(GET) == b"\x88\x00\x09\xd0\x46\x08\x69\x04\x01\x00"
    # Cancelling before the host answered at all ends it at once.
    done = []
    t = DFTTransfer(TransferOptions(True, "X", str(src)), on_done=lambda ok, m: done.append(ok))
    t.cancel()
    assert done == [False] and t.finished


def test_start_types_the_command_and_presses_enter(tmp_path):
    em, screen, sent = emu()
    em.feed(record(READY))
    em.cursor = 0                                         # anywhere: it finds the field
    em.start_transfer(TransferOptions(False, "'CHAD.JCL(TEST)'", str(tmp_path / "t")))
    cmd = e("IND$FILE GET 'CHAD.JCL(TEST)' ASCII CRLF")
    assert sent[-1] == b"\x7d" + sent[-1][1:3] + b"\x11" + addr(22, 6) + cmd
    assert em.locked
    with pytest.raises(ValueError):
        em.start_transfer(TransferOptions(False, "X", str(tmp_path / "u")))
    em.abort_transfer("gone")
    # A screen with no field long enough is refused before anything is sent.
    em2, _, sent2 = emu()
    em2.feed(record(b"\xf5\xc3\x1d\x60" + e("MENU") + b"\x1d\x40\x00\x00\x1d\x60"))
    with pytest.raises(ValueError, match="long enough"):
        em2.start_transfer(TransferOptions(False, "X", str(tmp_path / "v")))
    assert sent2 == []


# ------------------------------------------------------- against a fake host


class FakeTSO(threading.Thread):
    """Negotiates TN3270, shows READY, then plays IND$FILE's side of the
    transfer the command asks for."""

    def __init__(self, download: bytes = b"", msg: bytes = b"TRANS03 File transfer complete$"):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.download, self.msg = download, msg
        self.command = ""
        self.uploaded = b""
        self.replies: list[bytes] = []
        self.finished = threading.Event()
        self.error = None

    def _record(self) -> bytes:
        while IAC_EOR not in self.buf:
            chunk = self.conn.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        rec, self.buf = self.buf.split(IAC_EOR, 1)
        rec = rec.replace(b"\xff\xff", b"\xff")
        while rec[:1] == b"\xff":                          # leftover negotiation
            rec = rec[3:]
        return rec

    def _send(self, data: bytes) -> None:
        self.conn.sendall(record(data))

    def _expect(self, want: bytes) -> bytes:
        got = self._record()
        self.replies.append(got)
        assert got == want, (got, want)
        return got

    def run(self):
        try:
            self.conn, _ = self.srv.accept()
            self.conn.settimeout(10)
            self.conn.sendall(bytes([IAC, DO, TTYPE, IAC, SB, TTYPE, 1, IAC, SE, IAC, DO, EOR,
                                     IAC, WILL, EOR, IAC, DO, BINARY, IAC, WILL, BINARY]))
            self.buf = b""
            while bytes([IAC, SE]) not in self.buf[self.buf.find(b"IBM-"):]:
                self.buf += self.conn.recv(4096)
            self.buf = b""
            self._send(READY)
            enter = self._record()
            self.command = enter[6:].decode("cp037")
            if " PUT " in self.command:
                self._upload()
            else:
                self._downloads()
            for rec in message(self.msg):
                self._send(rec)
                if b"FT:MSG" in rec:
                    self._expect(OPEN_ACK)
                elif rec.endswith(b"$"):
                    self._expect(ack(1))
            self._send(b"\xf1\xc2" + e("READY"))
        except Exception as ex:                            # noqa: BLE001 - reported by the test
            self.error = ex
        finally:
            self.finished.set()

    def _downloads(self):
        self._send(wsf(open_req(b"FT:DATA")))
        self._expect(OPEN_ACK)
        chunks = [self.download[i:i + 1000] for i in range(0, len(self.download), 1000)]
        for n, chunk in enumerate(chunks, 1):
            self._send(wsf(INSERT, data_insert(chunk)))
            self._expect(ack(n))
        self._send(wsf(CLOSE))
        self._expect(CLOSE_ACK)

    def _upload(self):
        self._send(wsf(open_req(b"FT:DATA", recsz=80)))
        self._expect(OPEN_ACK)
        n = 1
        while True:
            self._send(wsf(SET_CURSOR, GET))
            got = self._record()
            if got == b"\x88\x00\x09\xd0\x46\x08\x69\x04\x22\x00":
                break
            if got[4:6] == b"\x46\x08":                      # error: cancelled
                self.replies.append(got)
                self.msg = b"TRANS13 Error in file transfer: file transfer canceled$"
                break
            assert got[4:12] == b"\x46\x05\x63\x06" + n.to_bytes(4, "big"), got[:20]
            self.uploaded += got[17:17 + int.from_bytes(got[15:17], "big") - 5]
            n += 1
            if b"STOP" in self.uploaded and not self.replies:
                self.replies.append(b"paused")
                time.sleep(0.5)                            # time for the user to cancel
        self._send(wsf(CLOSE))
        self._expect(CLOSE_ACK)


IAC_EOR = bytes([IAC, EOR_CMD])


def _connect(tmp_path, host):
    profile = SessionProfile(name="tso", transport="telnet", host="127.0.0.1", port=host.port,
                             emulation="ibm3278-2")
    s = Session(profile, ProfileStore(tmp_path, site_roots=[]))
    s.connect()
    deadline = time.monotonic() + 5
    while "===>" not in s.screen.text() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "===>" in s.screen.text()
    return s


def _run(s, opts, host, **kw):
    done = threading.Event()
    result = {}

    def finished(ok, msg):
        result.update(ok=ok, msg=msg)
        done.set()

    progress = []
    s.start_transfer(opts, on_progress=lambda n, t: progress.append((n, t)),
                     on_done=finished, **kw)
    assert done.wait(10), "transfer did not finish"
    assert host.finished.wait(5)
    assert host.error is None, host.error
    return result, progress


def test_receive_from_tso(tmp_path):
    text = "".join(f"RECORD {i:04d} " + "X" * 60 + "\r\n" for i in range(100))
    host = FakeTSO(download=text.encode("latin-1"))
    host.start()
    s = _connect(tmp_path, host)
    try:
        out = tmp_path / "report.txt"
        result, progress = _run(s, TransferOptions(False, "'CHAD.REPORT'", str(out)), host)
        assert result == {"ok": True, "msg": "TRANS03 File transfer complete"}
        assert host.command == "IND$FILE GET 'CHAD.REPORT' ASCII CRLF"
        assert out.read_text() == text.replace("\r\n", "\n")
        assert progress[-1] == (len(text), 0)
        deadline = time.monotonic() + 2
        while s.emulation.locked and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not s.emulation.locked                     # READY unlocked the keyboard
    finally:
        s.disconnect()


def test_send_binary_to_cics(tmp_path):
    data = bytes(range(256)) * 50
    src = tmp_path / "payload.bin"
    src.write_bytes(data)
    host = FakeTSO()
    host.start()
    s = _connect(tmp_path, host)
    try:
        result, progress = _run(s, TransferOptions(True, "PAYLOAD", str(src), host="cics",
                                                   ascii=False), host)
        assert result["ok"]
        assert host.command == "IND$FILE PUT PAYLOAD (BINARY NOCRLF"
        assert host.uploaded == data
        assert progress[-1] == (len(data), len(data))
    finally:
        s.disconnect()


def test_cancel_an_upload(tmp_path):
    src = tmp_path / "big.txt"
    src.write_text("STOP\n" + "line\n" * 5000)
    host = FakeTSO()
    host.start()
    s = _connect(tmp_path, host)
    try:
        done = threading.Event()
        result = {}
        s.start_transfer(TransferOptions(True, "'CHAD.BIG'", str(src)),
                         on_progress=lambda n, t: s.cancel_transfer() if n else None,
                         on_done=lambda ok, msg: (result.update(ok=ok, msg=msg), done.set()))
        assert done.wait(10)
        assert not result["ok"] and "canceled" in result["msg"]
        assert any(r[4:10] == b"\x46\x08\x69\x04\x01\x00" for r in host.replies)
    finally:
        s.disconnect()


def test_transfer_policy(tmp_path, monkeypatch):
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2"),
                ProfileStore(tmp_path, site_roots=[]))
    s.connected = True
    put = TransferOptions(True, "X", str(tmp_path / "a"))
    get = TransferOptions(False, "X", str(tmp_path / "a"))
    try:
        policy.set_current(policy.Policy.from_dict({"file_upload": False}))
        with pytest.raises(policy.PolicyError, match="sending"):
            s.start_transfer(put)
        policy.set_current(policy.Policy.from_dict({"file_download": False}))
        with pytest.raises(policy.PolicyError, match="receiving"):
            s.start_transfer(get)
        # Limited mode: off unless the policy allows it explicitly...
        policy.set_current(policy.Policy())
        with pytest.raises(policy.PolicyError):
            s.start_transfer(get, limited=True)
        assert not policy.Policy.from_dict({"limited": True}).file_transfer(False)
        # ...and then only straight into the Downloads folder.
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "Downloads").mkdir()
        policy.set_current(policy.Policy.from_dict({"limited": True, "file_download": True}))
        assert policy.current().file_transfer(False) and not policy.current().file_transfer(True)
        with pytest.raises(policy.PolicyError, match="Downloads"):
            s.start_transfer(get)
        s.emulation.locked = True                          # past the policy: a host check
        with pytest.raises(ValueError, match="locked"):
            s.start_transfer(TransferOptions(False, "X", str(tmp_path / "Downloads" / "a")))
    finally:
        policy.set_current(policy.Policy())
    with pytest.raises(policy.PolicyError, match="file_download must be"):
        policy.Policy.from_dict({"file_download": "yes"})
    vt = Session(SessionProfile(transport="ssh", host="h"), ProfileStore(tmp_path, site_roots=[]))
    assert not vt.can_transfer and s.can_transfer


# ------------------------------------------------------------------ dialog


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_transfer_dialog_receives_a_file(app, tmp_path):
    from PyQt6.QtWidgets import QApplication

    from cherminal.gui.terminal import TerminalWidget
    from cherminal.gui.transfer import TransferDialog
    host = FakeTSO(download=b"HELLO FROM TSO\r\n")
    host.start()
    s = _connect(tmp_path, host)
    try:
        term = TerminalWidget(s)
        dlg = TransferDialog(term)
        dlg.receive.setChecked(True)
        dlg.host_type.setCurrentIndex(dlg.host_type.findData("cics"))
        dlg.host_file.setText("HELLO")
        out = tmp_path / "hello.txt"
        dlg.local_file.setText(str(out))
        assert dlg.preview.text() == "Command: IND$FILE GET HELLO (ASCII CRLF"
        assert not dlg.alloc.isVisibleTo(dlg)              # allocation is for PUT only
        dlg.send.setChecked(True)
        dlg.host_type.setCurrentIndex(0)
        assert dlg.alloc.isVisibleTo(dlg)
        dlg.receive.setChecked(True)
        dlg.host_type.setCurrentIndex(dlg.host_type.findData("cics"))
        dlg.start()
        assert dlg.running and dlg.close_button.text() == "Cancel"
        deadline = time.monotonic() + 10
        while dlg.running and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        assert dlg.status.text() == "Done: TRANS03 File transfer complete"
        assert out.read_text() == "HELLO FROM TSO\n"
    finally:
        s.disconnect()


def test_transfer_dialog_limited_mode(app, tmp_path, monkeypatch):
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.gui.transfer import TransferDialog
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "upload.txt").write_text("x")
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2"),
                ProfileStore(tmp_path, site_roots=[]))
    try:
        policy.set_current(policy.Policy.from_dict({"file_upload": True}))
        dlg = TransferDialog(TerminalWidget(s, limited=True), limited=True)
        assert dlg.can_send and not dlg.can_receive and dlg.send.isChecked()
        assert dlg.local_file.findText("upload.txt") >= 0        # a list, not a browser
        dlg.local_file.setEditText("upload.txt")
        assert dlg._local() == str(tmp_path / "Downloads" / "upload.txt")
    finally:
        policy.set_current(policy.Policy())


def test_session_menu_transfer_item(app, tmp_path):
    from cherminal.gui.app import MainWindow
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]))
    assert not win.transfer_action.isVisible()
    term = win.open_session(SessionProfile(name="mf", transport="telnet", host="127.0.0.1",
                                           port=1, emulation="ibm3278-2"))
    assert win.transfer_action.isVisible()
    win.close_tab(0)
    assert not win.transfer_action.isVisible()
    term.session.disconnect()
