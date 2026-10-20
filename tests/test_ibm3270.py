import socket
import threading
import time

import pytest

from cherminal.config import ProfileStore, SessionProfile
from cherminal.emulation import create
from cherminal.emulation.ibm3270 import decode_address, encode_address
from cherminal.screen import Screen
from cherminal.session import Session
from cherminal.transport.telnet import (BINARY, DO, EOR, IAC, SB, SE, TTYPE, WILL,
                                        TelnetProtocol)

EOR_CMD = 0xEF


def e(text: str) -> bytes:
    return text.encode("cp037")


def addr(row: int, col: int, cols: int = 80) -> bytes:
    return encode_address(row * cols + col, 24 * 80)


def record(data: bytes) -> bytes:
    return data.replace(b"\xff", b"\xff\xff") + bytes([IAC, EOR_CMD])


# A logon panel: protected label, an input field with the cursor in it, a
# protected end marker, and a hidden password field.
LOGON = (b"\xf5\xc3"                                   # Erase/Write, WCC restore + reset MDT
         + b"\x11" + addr(0, 0) + b"\x1d\xf8" + e("USERID ===>")   # SF autoskip+intense
         + b"\x1d\x40" + b"\x13" + b"\x00" * 8                     # SF unprotected, IC
         + b"\x1d\x60"                                              # SF protected
         + b"\x11" + addr(1, 0) + b"\x1d\x60" + e("PASSWORD  ===>")
         + b"\x1d\x4c" + b"\x00" * 8 + b"\x1d\x60")                 # SF unprot hidden


def cells(screen, row, start, end) -> str:
    return "".join(c.char for c in screen.lines[row][start:end])


def emu(name="ibm3278-2"):
    sent = []
    screen = Screen(80, 24)
    em = create(name, screen, sent.append)
    return em, screen, sent


def test_addresses():
    assert addr(1, 0) == b"\xc1\x50"          # row 2 col 1 in IBM's address table
    assert addr(0, 7) == b"\x40\xc7"
    assert decode_address(0xC1, 0x50) == 80
    assert decode_address(0x07, 0x80) == 0x780  # 14-bit form
    assert encode_address(5000, 27 * 200) == bytes([5000 >> 8, 5000 & 0xFF])


def test_write_fields_and_render():
    em, screen, _ = emu()
    em.feed(record(LOGON))
    assert screen.line_text(0).startswith(" USERID ===>")
    assert screen.line_text(1).startswith(" PASSWORD  ===>")
    assert (screen.y, screen.x) == (0, 13)              # IC put the cursor in the field
    assert screen.lines[0][1].attr.bold                 # intensified label
    assert not em.locked


def test_typing_and_enter_sends_modified_fields():
    em, screen, sent = emu()
    em.feed(record(LOGON))
    em.type_text("tso1")
    assert cells(screen, 0, 13, 17) == "tso1"
    em.do_action("tab")                                 # to the password field
    assert em.cursor == 80 + 16
    em.type_text("secret")
    assert screen.lines[1][16].attr.invisible           # hidden field stays hidden
    assert "secret" not in screen.text()                 # and can't be copied
    em.do_action("enter")
    assert em.locked
    first = 13
    expected = (b"\x7d" + encode_address(80 + 22, 1920)
                + b"\x11" + encode_address(first, 1920) + e("tso1")
                + b"\x11" + encode_address(80 + 16, 1920) + e("secret"))
    assert sent == [expected]
    # Locked until the host restores the keyboard.
    em.type_text("x")
    assert cells(screen, 0, 13, 17) == "tso1"
    em.feed(record(b"\xf1\xc2"))                       # Write, WCC keyboard restore
    assert not em.locked


def test_protected_and_overflow():
    em, screen, _ = emu()
    em.feed(record(LOGON))
    em.cursor = 3
    em.type_text("Z")
    assert "Protected" in em.status
    assert screen.line_text(0).startswith(" USERID")
    em.cursor = 13
    em.type_text("12345678")                           # fills the field
    em.cursor = 13
    em.do_action("insert")
    em.type_text("0")
    assert "Overflow" in em.status


def test_editing_keys():
    em, screen, _ = emu()
    em.feed(record(LOGON))
    em.type_text("abcd")
    em.do_action("erase")                               # backspace deletes left
    assert cells(screen, 0, 13, 17) == "abc "
    em.do_action("left")
    em.do_action("left")
    em.do_action("delete")
    assert cells(screen, 0, 13, 17) == "ac  "
    em.do_action("insert")
    em.type_text("b")
    assert cells(screen, 0, 13, 17) == "abc "
    em.do_action("erase-eof")
    assert cells(screen, 0, 13, 17) == "ab  "
    em.do_action("erase-input")
    assert cells(screen, 0, 13, 17) == "    "
    assert em.cursor == 13


def test_short_read_keys_and_clear():
    em, screen, sent = emu()
    em.feed(record(LOGON))
    em.do_action("pa1")
    assert sent[-1] == b"\x6c"
    em.feed(record(b"\xf1\xc2"))
    em.do_action("clear")
    assert sent[-1] == b"\x6d"
    assert screen.text().strip() == ""
    em.feed(record(b"\xf1\xc2"))
    em.do_action("pf3")
    assert sent[-1][:1] == b"\xf3"
    em.feed(record(b"\xf1\xc2"))
    em.do_action("pf24")
    assert sent[-1][:1] == b"\x4c"


def test_read_buffer_and_read_modified_commands():
    em, _, sent = emu()
    em.feed(record(LOGON))
    em.type_text("A")
    em.feed(record(b"\xf6"))                           # Read Modified
    assert sent[-1] == b"\x60" + encode_address(14, 1920) + b"\x11" + \
        encode_address(13, 1920) + e("A")
    em.feed(record(b"\xf2"))                           # Read Buffer
    rb = sent[-1]
    assert rb[:3] == b"\x60" + encode_address(14, 1920)
    assert rb[3:5] == b"\x1d\xf8"                     # SF + the protected, intense attribute
    assert len(rb) == 3 + 1920 + 6                    # every position, 6 SF orders add a byte


def test_repeat_and_erase_unprotected_orders():
    em, screen, _ = emu()
    em.feed(record(b"\xf5\xc2" + b"\x3c" + addr(0, 10) + e("-") + b"\x11" + addr(2, 0)
                   + b"\x3c" + addr(3, 0) + e("=")))
    assert screen.line_text(0)[:10] == "-" * 10
    assert screen.line_text(2) == "=" * 80
    em.feed(record(b"\xf1\xc2\x11" + addr(0, 0) + b"\x12" + addr(0, 5)))
    assert screen.line_text(0)[:10] == "     -----"   # unformatted: all unprotected


def test_extended_attributes_and_colors():
    em, screen, _ = emu()
    em.feed(record(b"\xf5\xc2" + b"\x29\x02\xc0\x60\x42\xf6" + e("YELLOW")
                   + b"\x28\x41\xf2" + e("R") + b"\x28\x00\x00" + e("n")))
    assert screen.lines[0][1].attr.fg == 11            # yellow
    assert screen.lines[0][7].attr.reverse
    assert not screen.lines[0][8].attr.reverse
    em.feed(record(b"\xf5\xc2\x1d\x40" + e("in") + b"\x1d\xe8" + e("PROT")))
    assert screen.lines[0][1].attr.fg == 10            # base colour: unprotected green
    assert screen.lines[0][4].attr.fg == 15            # protected intensified white


def test_erase_write_alternate_sizes():
    em, screen, _ = emu("ibm3278-4")
    em.feed(record(b"\x7e\xc2" + e("BIG")))
    assert (screen.cols, screen.rows) == (80, 43)
    em.feed(record(b"\xf5\xc2"))
    assert (screen.cols, screen.rows) == (80, 24)
    em5, s5, _ = emu("ibm3278-5")
    em5.feed(record(b"\x7e\xc2"))
    assert (s5.cols, s5.rows) == (132, 27)


def test_query_reply():
    em, _, sent = emu("ibm3278-4")
    em.feed(record(b"\xf3\x00\x05\x01\xff\x02"))      # WSF Read Partition Query
    reply = sent[-1]
    assert reply[0] == 0x88
    i, qcodes = 1, []
    while i < len(reply):
        length = int.from_bytes(reply[i:i + 2], "big")
        assert reply[i + 2] == 0x81
        qcodes.append(reply[i + 3])
        if reply[i + 3] == 0x81:                       # usable area: 80 x 43
            body = reply[i + 4:i + length]
            assert int.from_bytes(body[2:4], "big") == 80
            assert int.from_bytes(body[4:6], "big") == 43
        i += length
    assert i == len(reply)
    assert qcodes == [0x80, 0x81, 0x86, 0x87, 0x88, 0xA6]


def test_split_records_and_ff_bytes():
    em, screen, _ = emu()
    data = record(b"\xf5\xc2" + e("A") + b"\xff" + e("B"))
    for b in data:
        em.feed(bytes([b]))
    assert screen.line_text(0)[:3] == "A" + b"\xff".decode("cp037") + "B"


def test_unformatted_screen_typing():
    em, screen, sent = emu()
    em.feed(record(b"\xf5\xc2"))
    em.type_text("logon")
    em.do_action("enter")
    assert sent[-1] == b"\x7d" + encode_address(5, 1920) + e("logon")


def test_profile_rules_and_keymap(tmp_path):
    with pytest.raises(ValueError):
        SessionProfile(transport="ssh", emulation="ibm3278-2")
    p = SessionProfile(transport="telnet", host="h", emulation="ibm3278-2", tls=True,
                       enter_sends="crlf", backspace="bs", keys={"Ctrl+R": "action:reset"})
    assert p.effective_port == 992
    km = ProfileStore(tmp_path, site_roots=[]).build_keymap(p)
    assert km.lookup("Enter").value == "enter"         # enter_sends doesn't apply
    assert km.lookup("Backspace").value == "erase"
    assert km.lookup("Shift+F3").value == "pf15"
    assert km.lookup("Ctrl+R").value == "reset"


def test_tn3270_telnet_framing():
    out = []
    proto = TelnetProtocol(out.append, "IBM-3278-2-E", tn3270=True)
    proto.start()
    assert out == []                                    # the host leads
    proto.receive(bytes([IAC, DO, EOR, IAC, WILL, EOR, IAC, DO, 39]))
    assert b"".join(out) == bytes([IAC, WILL, EOR, IAC, DO, EOR, IAC, 252, 39])
    data = proto.receive(bytes([IAC, DO, BINARY, IAC, WILL, BINARY, 0xF5, 0x0D, 0x00,
                                IAC, IAC, IAC, EOR_CMD]))
    assert data == bytes([0xF5, 0x0D, 0x00, IAC, IAC, IAC, EOR_CMD])
    assert proto.encode(b"\x7d\xff") == b"\x7d\xff\xff" + bytes([IAC, EOR_CMD])


class FakeMainframe(threading.Thread):
    """Negotiates TN3270 like a host would, sends LOGON, returns the reply record."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.term_type = None
        self.reply = None
        self.got_reply = threading.Event()

    def run(self):
        conn, _ = self.srv.accept()
        conn.settimeout(10)
        conn.sendall(bytes([IAC, DO, TTYPE, IAC, SB, TTYPE, 1, IAC, SE,
                            IAC, DO, EOR, IAC, WILL, EOR, IAC, DO, BINARY, IAC, WILL, BINARY]))
        buf = b""
        while b"IBM-" not in buf or bytes([IAC, SE]) not in buf[buf.index(b"IBM-"):]:
            buf += conn.recv(4096)
        start = buf.index(b"IBM-")
        self.term_type = buf[start:buf.index(bytes([IAC, SE]), start)].decode()
        conn.sendall(record(LOGON))
        buf = b""
        while True:
            buf += conn.recv(4096)
            # Skip leftover negotiation; the reply starts with the Enter AID.
            if b"\x7d" in buf and buf.endswith(bytes([IAC, EOR_CMD])):
                break
        self.reply = buf[buf.index(b"\x7d"):-2].replace(b"\xff\xff", b"\xff")
        self.got_reply.set()
        conn.close()


def test_session_against_fake_mainframe(tmp_path):
    host = FakeMainframe()
    host.start()
    profile = SessionProfile(name="mf", transport="telnet", host="127.0.0.1", port=host.port,
                             emulation="ibm3278-2")
    session = Session(profile, ProfileStore(tmp_path, site_roots=[]))
    updated = threading.Event()
    session.connect(on_update=updated.set)
    try:
        deadline = time.monotonic() + 5
        while "USERID" not in session.screen.text() and time.monotonic() < deadline:
            updated.wait(0.1)
            updated.clear()
        assert "USERID" in session.screen.text()
        assert host.term_type == "IBM-3278-2-E"
        session.key("T", "t")
        session.key("Tab")
        session.key("X", "x")
        session.key("Enter")
        assert host.got_reply.wait(5)
        assert host.reply.startswith(b"\x7d")
        assert e("t") in host.reply and e("x") in host.reply
    finally:
        session.disconnect()


@pytest.fixture
def tls_server(tmp_path):
    """A one-shot TLS server with a self-signed certificate; yields its port."""
    import shutil
    import ssl
    import subprocess
    if not shutil.which("openssl"):
        pytest.skip("openssl not installed")
    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=mainframe.test", "-keyout", key, "-out", cert],
                   check=True, capture_output=True)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)
    got = []

    def serve():
        for _ in range(2):
            try:
                conn, _ = srv.accept()
                with ctx.wrap_socket(conn, server_side=True) as tls:
                    tls.sendall(record(b"\xf5\xc2" + e("SECURE")))
                    got.append(tls.recv(100))
            except (OSError, ssl.SSLError):
                continue

    threading.Thread(target=serve, daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()


def test_tls_connection(tls_server, tmp_path):
    from cherminal.transport.telnet import TelnetTransport
    store = ProfileStore(tmp_path, site_roots=[])

    # A self-signed certificate is refused when checking is on...
    closed = []
    t = TelnetTransport("127.0.0.1", tls_server, tn3270=True, tls=True)
    t.on_close = closed.append
    t.open(80, 24)
    deadline = time.monotonic() + 5
    while not closed and time.monotonic() < deadline:
        time.sleep(0.05)
    assert closed and "certificate" in closed[0].lower()

    # ...and accepted when the profile turns it off.
    p = SessionProfile(name="s", transport="telnet", host="127.0.0.1", port=tls_server,
                       emulation="ibm3278-2", tls=True, tls_verify=False)
    session = Session(p, store)
    session.connect()
    try:
        deadline = time.monotonic() + 5
        while "SECURE" not in session.screen.text() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert "SECURE" in session.screen.text()
    finally:
        session.disconnect()


# A form with three input fields: two 5-character fields on row 3 (between
# protected labels), a numeric field on row 5 and an 8-character field on
# the last row.
FORM = (b"\xf5\xc3"
        + b"\x11" + addr(2, 0) + b"\x1d\x60" + e("A") + b"\x1d\x40" + b"\x13" + b"\x00" * 5
        + b"\x1d\x60" + e("B") + b"\x1d\x40" + b"\x00" * 5 + b"\x1d\x60"
        + b"\x11" + addr(4, 0) + b"\x1d\x60" + e("NUM") + b"\x1d\x50" + b"\x00" * 4
        + b"\x1d\x60"
        + b"\x11" + addr(23, 0) + b"\x1d\x60" + e("CMD") + b"\x1d\x40" + b"\x00" * 8
        + b"\x1d\x60" + e("END"))


def test_paste_fills_fields_and_wraps_into_the_next():
    em, screen, _ = emu()
    em.feed(record(FORM))
    assert em.cursor == 2 * 80 + 3
    assert em.paste_text("abcdefgh") == 8               # 5 in field A, 3 run on into B
    assert cells(screen, 2, 3, 8) == "abcde"
    assert cells(screen, 2, 8, 11) == " B "              # the protected label is untouched
    assert cells(screen, 2, 11, 16) == "fgh  "
    assert em.cursor == 2 * 80 + 14


def test_paste_newline_moves_to_the_next_rows_field():
    em, screen, _ = emu()
    em.feed(record(FORM))
    assert em.paste_text("ab\r\n123\nlogon\n") == 10
    assert cells(screen, 2, 3, 8) == "ab   "
    assert cells(screen, 2, 11, 16) == "     "         # B is on the same row: skipped
    assert cells(screen, 4, 5, 9) == "123 "
    assert cells(screen, 23, 5, 13) == "logon   "
    # A line that exactly fills its field does not skip a field at its line break.
    em.do_action("erase-input")
    assert em.paste_text("12345\nxyz") == 8
    assert cells(screen, 2, 3, 8) == "12345" and cells(screen, 2, 11, 14) == "xyz"


def test_paste_respects_numeric_fields():
    em, screen, _ = emu()
    em.feed(record(FORM))
    assert em.paste_text("a\n12x4") == 3                # stops at the letter
    assert cells(screen, 4, 5, 9) == "12  "
    assert "X NUM" in em.status
    em.cursor = 4 * 80 + 5
    em.type_text("z")                                   # typing obeys the same rule
    assert cells(screen, 4, 5, 6) == "1"


def test_paste_stops_when_input_fields_run_out():
    em, screen, sent = emu()
    em.feed(record(FORM))
    em.cursor = 23 * 80 + 5
    assert em.paste_text("0123456789") == 8
    assert cells(screen, 23, 5, 13) == "01234567"
    assert screen.line_text(23).endswith("END")         # protected text never overtyped
    assert cells(screen, 2, 3, 8) == "     "           # no wrap round to the top field
    assert "Overflow" in em.status
    # Pasting from a protected position starts in the next input field.
    em.do_action("erase-input")
    em.cursor = 0
    assert em.paste_text("hi") == 2 and cells(screen, 2, 3, 5) == "hi"
    assert sent == []                                   # paste never sends anything


def test_paste_unformatted_screen_and_session_hook(tmp_path):
    em, screen, _ = emu()
    em.feed(record(b"\xf5\xc2"))
    em.cursor = 23 * 80 + 78
    assert em.paste_text("abcd") == 2                   # stops at the bottom right
    assert screen.line_text(23).endswith("ab")
    assert screen.line_text(0).strip() == ""
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2"),
                ProfileStore(tmp_path, site_roots=[]))
    s.feed(record(LOGON))
    s.paste("tso1\nsecret\n")
    assert cells(s.screen, 0, 13, 17) == "tso1"
    assert s.emulation.buf[80 + 16:80 + 22] == list(e("secret"))
