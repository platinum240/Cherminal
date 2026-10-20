import socket
import threading
import time

import pytest

from cherminal.config import ProfileStore, SessionProfile
from cherminal.emulation import create
from cherminal.emulation.ibm5250 import (AID_ENTER, ESC, FLAG_ATN, FLAG_SRQ, OP_CANCEL_INVITE,
                                         OP_MSG_ON, OP_NOOP, OP_PUT_GET, OP_RESTORE, OP_SAVE)
from cherminal.screen import Screen
from cherminal.session import Session
from cherminal.transport.telnet import (BINARY, DO, EOR, IAC, NEW_ENVIRON, SB, SE, TTYPE, WILL,
                                        WONT, TelnetProtocol)

EOR_CMD = 0xEF
CLEAR, WTD, READ_MDT, READ_INPUT, READ_MDT_ALT = 0x40, 0x11, 0x52, 0x42, 0x82
SOH, RA, SBA, IC, SF = 0x01, 0x02, 0x11, 0x13, 0x1D


def e(text: str) -> bytes:
    return text.encode("cp037")


def gds(data: bytes, opcode: int = OP_PUT_GET, flags: int = 0) -> bytes:
    return ((len(data) + 10).to_bytes(2, "big") + b"\x12\xa0\x00\x00\x04"
            + bytes([flags, 0, opcode]) + data)


def record(data: bytes, opcode: int = OP_PUT_GET) -> bytes:
    return gds(data, opcode).replace(b"\xff", b"\xff\xff") + bytes([IAC, EOR_CMD])


def sba(row: int, col: int) -> bytes:
    return bytes([SBA, row, col])


def sf(row: int, col: int, attr: int, length: int, ffw: int | None = None) -> bytes:
    """SBA to the attribute position, then Start of Field."""
    word = b"" if ffw is None else ffw.to_bytes(2, "big")
    return sba(row, col) + bytes([SF]) + word + bytes([attr]) + length.to_bytes(2, "big")


def wtd(orders: bytes, cc1: int = 0x00, cc2: int = 0x00) -> bytes:
    return bytes([ESC, WTD, cc1, cc2]) + orders


def read(cmd: int = READ_MDT) -> bytes:
    return bytes([ESC, cmd, 0x00, 0x00])


# An IBM i style sign-on panel: a monocase user field and a non-display
# password field, the cursor in the user field, then Read MDT Fields.
SIGNON = (bytes([ESC, CLEAR])
          + wtd(bytes([SOH, 7, 0, 0, 0, 24, 0, 0, 0])
                + sba(1, 35) + b"\x22" + e("Sign On") + b"\x20"
                + sba(6, 17) + b"\x20" + e("User . . . . . .")
                + sf(6, 52, 0x24, 10, 0x4020) + sba(6, 63) + b"\x20"
                + sba(7, 17) + b"\x20" + e("Password . . . .")
                + sf(7, 52, 0x27, 10, 0x4000) + sba(7, 63) + b"\x20"
                + bytes([IC, 6, 53]))
          + read())

USER, PASSWORD = 5 * 80 + 52, 6 * 80 + 52        # first data positions


def cells(screen, row, start, end) -> str:
    return "".join(c.char for c in screen.lines[row][start:end])


def emu(name="ibm3179-2"):
    sent = []
    screen = Screen(80, 24)
    em = create(name, screen, sent.append)
    return em, screen, sent


def signed_on(name="ibm3179-2"):
    em, screen, sent = emu(name)
    em.feed(record(SIGNON))
    return em, screen, sent


def test_signon_screen_renders():
    em, screen, _ = signed_on()
    assert cells(screen, 0, 35, 42) == "Sign On"
    assert screen.lines[0][35].attr.fg == 15          # 0x22 high intensity: white on colour
    assert cells(screen, 5, 17, 33) == "User . . . . . ."
    assert screen.lines[5][52].attr.underline          # 0x24 underlined input field
    assert (screen.y, screen.x) == (5, 52)             # IC row 6 col 53
    assert not em.locked and em.read_cmd == READ_MDT
    assert [f.start for f in em.fields] == [USER, PASSWORD]


def test_typing_enter_reply_and_hidden_password():
    em, screen, sent = signed_on()
    em.type_text("qsecofr")
    assert cells(screen, 5, 52, 59) == "QSECOFR"      # monocase field
    em.do_action("tab")
    assert em.cursor == PASSWORD
    em.type_text("secret")
    assert "secret" not in screen.text()               # non-display: never on screen
    assert cells(screen, 6, 52, 58) == "      "
    em.do_action("enter")
    assert em.locked and "X SYSTEM" in em.status
    assert sent == [gds(bytes([7, 59, AID_ENTER])
                        + sba(6, 53) + e("QSECOFR") + sba(7, 53) + e("secret"))]
    em.type_text("x")                                  # locked until the host answers
    assert cells(screen, 5, 52, 60) == "QSECOFR "
    em.feed(record(read()))
    assert not em.locked


def test_only_modified_fields_sent_and_f_keys():
    em, _, sent = signed_on()
    em.do_action("tab")
    em.type_text("pw")
    em.do_action("f3")
    assert sent[-1] == gds(bytes([7, 55, 0x33]) + sba(7, 53) + e("pw"))
    em.feed(record(read()))                            # unlocking puts the cursor home
    em.do_action("f24")
    assert sent[-1][10:13] == bytes([6, 53, 0xBC])
    em.feed(record(read()))
    em.do_action("roll-up")
    assert sent[-1][12] == 0xF5
    em.feed(record(read()))
    em.do_action("help")                               # no field data with Help
    assert sent[-1] == gds(bytes([6, 53, 0xF3]))


def test_read_input_fields_vs_read_mdt():
    em, _, sent = emu()
    screen = (bytes([ESC, CLEAR]) + wtd(sf(2, 1, 0x24, 4, 0x4000) + sf(3, 1, 0x24, 4, 0x4000)
                                        + bytes([IC, 2, 2])))
    em.feed(record(screen + read(READ_INPUT)))
    em.do_action("enter")
    assert sent[-1] == gds(bytes([2, 2, AID_ENTER]))   # nothing changed: no data
    em.feed(record(read(READ_INPUT)))
    em.type_text("ab")
    em.do_action("enter")
    # Read Input Fields: every field, full length, nulls as blanks, no SBA.
    assert sent[-1] == gds(bytes([2, 4, AID_ENTER]) + e("ab  ") + e("    "))
    em.feed(record(screen + read(READ_MDT)))
    em.type_text("ab")
    em.do_action("enter")
    assert sent[-1] == gds(bytes([2, 4, AID_ENTER]) + sba(2, 2) + e("ab"))
    em.feed(record(screen + read(READ_MDT_ALT)))
    em.type_text("a")
    em.do_action("right")
    em.type_text("b")
    em.do_action("enter")
    # Read MDT Alternate keeps embedded nulls.
    assert sent[-1] == gds(bytes([2, 5, AID_ENTER]) + sba(2, 2) + e("a") + b"\x00" + e("b"))


def test_orders_ra_ea_td_and_mc():
    em, screen, _ = emu()
    em.feed(record(bytes([ESC, CLEAR]) + wtd(
        sba(1, 1) + bytes([RA, 1, 10]) + e("-")
        + sba(2, 1) + e("ABCDEFGH") + sba(2, 3) + bytes([0x03, 2, 5, 1])   # EA to 2,5
        + sba(3, 1) + bytes([0x10, 0, 3]) + e("TDX")
        + bytes([0x14, 4, 7]), cc2=0x08)))
    assert cells(screen, 0, 0, 11) == "-" * 10 + " "
    assert screen.line_text(1)[:8] == "AB   FGH"
    assert screen.line_text(2)[:3] == "TDX"
    assert (screen.y, screen.x) == (3, 6)


def test_display_attributes_mono_and_colour():
    data = record(bytes([ESC, CLEAR]) + wtd(
        sba(1, 1) + b"\x21" + e("R") + b"\x22" + e("H") + b"\x28" + e("C")
        + b"\x3a" + e("B") + b"\x2a" + e("K") + b"\x2f" + e("SECRET") + b"\x20" + e("N")))
    em, screen, _ = emu("ibm5251-11")
    em.feed(data)
    line = screen.lines[0]
    assert line[1].attr.reverse and line[1].attr.fg == 10
    assert line[3].attr.bold and line[3].attr.fg == 10    # mono: high intensity is bold
    assert line[7].attr.blink
    assert cells(screen, 0, 11, 17) == "      "         # non-display
    assert line[18].char == "N" and not line[18].attr.invisible
    em, screen, _ = emu("ibm3179-2")
    em.feed(data)
    line = screen.lines[0]
    assert line[3].attr.fg == 15 and not line[3].attr.bold   # colour: white
    assert line[5].attr.fg == 9                          # red
    assert line[7].attr.fg == 12                         # blue
    assert line[9].attr.fg == 9 and line[9].attr.blink   # red blink
    assert "SECRET" not in screen.text()


def test_write_error_code_inhibits_until_reset():
    em, screen, _ = signed_on()
    before = screen.line_text(23)
    em.feed(record(bytes([ESC, 0x21]) + b"\x22" + e("CPF1120 User QSECOFR does not exist.")
                   + b"\x20" + read()))
    assert "CPF1120" in screen.line_text(23)
    assert "X II" in em.status and "CPF1120" in em.status
    em.type_text("a")
    assert cells(screen, 5, 52, 53) == " "             # input inhibited
    em.do_action("reset")
    assert screen.line_text(23) == before              # error line restored
    em.type_text("a")
    assert cells(screen, 5, 52, 53) == "A"


def test_operator_errors_need_reset():
    em, _, _ = signed_on()
    em.cursor = 0
    em.type_text("x")
    assert "protected" in em.status
    em.do_action("home")
    em.type_text("x")                                  # still inhibited
    assert em.buf[USER] == 0
    em.do_action("reset")
    em.type_text("x")
    assert em.buf[USER] == e("X")[0]


def test_signed_numeric_field_minus_and_numeric_rules():
    em, screen, sent = emu()
    em.feed(record(bytes([ESC, CLEAR]) + wtd(
        sf(2, 10, 0x24, 6, 0x4700) + sf(3, 10, 0x24, 4, 0x4500) + bytes([IC, 2, 11])) + read()))
    em.type_text("a")
    assert "Digits only" in em.status
    em.do_action("reset")
    em.type_text("12")
    em.do_action("field-minus")
    assert cells(screen, 1, 10, 16) == "   12-"            # right-adjusted, sign shown
    assert em.cursor == 2 * 80 + 10                      # moved to the next field
    em.do_action("enter")
    # The sign position is not sent; the last digit carries the D zone.
    assert sent[-1] == gds(bytes([3, 11, AID_ENTER]) + sba(2, 11) + e("   1") + b"\xd2")
    em.feed(record(read()))
    assert em.cursor == 80 + 10                        # back at the IC address
    em.type_text("7")
    em.do_action("field-plus")
    assert cells(screen, 1, 10, 16) == "    7 "


def test_field_exit_right_adjust_zero_fill_and_dup():
    em, screen, _ = emu()
    em.feed(record(bytes([ESC, CLEAR]) + wtd(
        sf(2, 1, 0x24, 5, 0x4305) + sf(3, 1, 0x24, 5, 0x5000) + bytes([IC, 2, 2])) + read()))
    em.type_text("42")
    em.do_action("field-exit")
    assert cells(screen, 1, 1, 6) == "00042"
    em.type_text("A")
    em.do_action("dup")
    assert cells(screen, 2, 1, 6) == "A****"
    assert em.cursor == 80 + 1                         # on to the next field (wrapping)
    em.do_action("dup")                                # not dup-enabled
    assert "Dup" in em.status


def test_auto_enter_and_field_exit_required():
    em, _, sent = emu()
    em.feed(record(bytes([ESC, CLEAR]) + wtd(
        sf(2, 1, 0x24, 2, 0x4080) + sf(3, 1, 0x24, 2, 0x4040) + bytes([IC, 2, 2])) + read()))
    em.type_text("ab")                                 # filling an auto-enter field sends it
    assert sent and sent[-1][12] == AID_ENTER
    em.feed(record(read()))
    em.do_action("tab")
    em.type_text("cd")
    assert em.cursor == 2 * 80 + 2                     # stays on the last position
    em.type_text("e")
    assert "Field Exit" in em.status


def test_mandatory_enter_blocks_enter():
    em, _, sent = emu()
    em.feed(record(bytes([ESC, CLEAR]) + wtd(sf(2, 1, 0x24, 3, 0x4008)) + read()))
    em.do_action("enter")
    assert not sent and "Mandatory" in em.status


def test_cc1_resets_mdt_and_nulls_fields():
    em, _, sent = signed_on()
    em.type_text("abc")
    em.feed(record(wtd(b"", cc1=0x40) + read()))         # reset MDT on non-bypass fields
    assert not em.fields[0].mdt and em.buf[USER] == e("A")[0]
    em.do_action("enter")
    assert sent[-1] == gds(bytes([6, 53, AID_ENTER]))
    em.feed(record(read()))
    em.type_text("x")
    em.feed(record(wtd(b"", cc1=0x80) + read()))         # null fields with MDT on
    assert em.buf[USER] == 0


def test_save_and_restore_screen():
    em, screen, sent = signed_on()
    em.type_text("bob")
    em.feed(record(b"", OP_SAVE))
    saved = sent[-1]
    assert saved[9] == OP_SAVE
    em.feed(record(bytes([ESC, CLEAR]) + wtd(e("SYSTEM REQUEST")) + read()))
    assert "Sign On" not in screen.text()
    em.feed(record(saved[10:], OP_RESTORE))
    assert cells(screen, 0, 35, 42) == "Sign On"
    assert cells(screen, 5, 52, 55) == "BOB"
    assert [f.start for f in em.fields] == [USER, PASSWORD]
    assert em.fields[0].mdt and not em.locked
    assert em.cursor == USER + 3
    em.type_text("!")                                  # editing continues where it was
    assert cells(screen, 5, 52, 56) == "BOB!"


def test_wide_model_clear_unit_alternate():
    em, screen, sent = emu("ibm3477-fc")
    em.feed(record(bytes([ESC, 0x20, 0x00])
                   + wtd(sba(27, 120) + e("WIDE") + sf(2, 1, 0x24, 5, 0x4000) + bytes([IC, 2, 2]))
                   + read()))
    assert (screen.cols, screen.rows) == (132, 27)
    assert screen.line_text(26)[119:123] == "WIDE"
    em.type_text("x")
    em.do_action("enter")
    assert sent[-1] == gds(bytes([2, 3, AID_ENTER]) + sba(2, 2) + e("x"))
    em.feed(record(bytes([ESC, CLEAR])))
    assert (screen.cols, screen.rows) == (80, 24)
    small, s2, _ = emu("ibm3179-2")                   # a 24x80 model stays 24x80
    small.feed(record(bytes([ESC, 0x20, 0x00])))
    assert (s2.cols, s2.rows) == (80, 24)


def test_query_reply():
    em, _, sent = emu("ibm3477-fc")
    em.feed(record(bytes([ESC, 0xF3, 0x00, 0x05, 0xD9, 0x70, 0x00])))
    reply = sent[-1]
    assert reply[2:4] == b"\x12\xa0" and reply[9] == OP_NOOP
    body = reply[10:]
    assert body[:3] == b"\x00\x00\x88"
    assert int.from_bytes(body[3:5], "big") == len(body) - 3 == 58
    assert body[5:8] == b"\xd9\x70\x80"
    assert body[29] == 0x01
    assert body[30:34] == e("3477") and body[34:37] == e("0FC")
    em2, _, sent2 = emu("ibm5251-11")
    em2.feed(record(bytes([ESC, 0xF3, 0x00, 0x05, 0xD9, 0x70, 0x00])))
    assert sent2[-1][40:47] == e("5251011")


def test_roll_read_screen_and_opcodes():
    em, screen, sent = emu()
    em.feed(record(bytes([ESC, CLEAR]) + wtd(sba(2, 1) + e("TWO") + sba(3, 1) + e("THREE"))))
    em.feed(record(bytes([ESC, 0x23, 0x01, 2, 4])))       # roll rows 2-4 up one line
    assert screen.line_text(1).startswith("THREE") and screen.line_text(2).strip() == ""
    em.feed(record(bytes([ESC, 0x62])))
    assert sent[-1][9] == OP_NOOP and len(sent[-1]) == 10 + 1920
    em.feed(record(b"", OP_MSG_ON))
    assert "Message waiting" in em.status
    em.feed(record(b"", OP_CANCEL_INVITE))
    assert sent[-1] == gds(b"", OP_CANCEL_INVITE)


def test_attention_and_sysreq_use_header_flags():
    em, _, sent = signed_on()
    em.do_action("attn")
    assert sent[-1] == gds(b"", OP_NOOP, FLAG_ATN)
    em.do_action("sysreq")
    assert sent[-1] == gds(b"", OP_NOOP, FLAG_SRQ)


def test_split_records_and_ff_bytes():
    em, screen, _ = emu()
    data = record(bytes([ESC, CLEAR]) + wtd(e("A") + b"\xff" + e("B")))
    for b in data:
        em.feed(bytes([b]))
    assert screen.line_text(0)[:3] == "A" + b"\xff".decode("cp037") + "B"


def test_profile_rules_device_name_and_keymap(tmp_path):
    with pytest.raises(ValueError, match="TN5250"):
        SessionProfile(transport="ssh", emulation="ibm3179-2")
    with pytest.raises(ValueError, match="device name"):
        SessionProfile(transport="telnet", host="h", emulation="ibm3179-2",
                       device_name="bad-name")
    with pytest.raises(ValueError, match="device name"):
        SessionProfile(transport="telnet", host="h", emulation="ibm3179-2",
                       device_name="TOOLONGNAME1")
    p = SessionProfile(transport="telnet", host="h", emulation="ibm3179-2", tls=True,
                       device_name="QPADEV@1", enter_sends="crlf")
    assert p.effective_port == 992
    assert SessionProfile.from_dict(p.to_dict()).device_name == "QPADEV@1"
    km = ProfileStore(tmp_path, site_roots=[]).build_keymap(p)
    assert km.lookup("Enter").value == "enter"
    assert km.lookup("KeypadEnter").value == "field-exit"
    assert km.lookup("KeypadMinus").value == "field-minus"
    assert km.lookup("Shift+F3").value == "f15"
    assert km.lookup("PageDown").value == "roll-up"
    assert km.lookup("Escape").value == "reset"


def test_new_environ_devname():
    out = []
    proto = TelnetProtocol(out.append, "IBM-3179-2", tn3270=True, device_name="WS01")
    proto.receive(bytes([IAC, DO, NEW_ENVIRON]))
    assert b"".join(out) == bytes([IAC, WILL, NEW_ENVIRON])
    out.clear()
    # IBM i asks for its variables (here with an IBMRSEED it would use for passwords).
    proto.receive(bytes([IAC, SB, NEW_ENVIRON, 1, 0, 3]) + b"IBMRSEED" + bytes(8)
                  + bytes([IAC, SE]))
    assert b"".join(out) == (bytes([IAC, SB, NEW_ENVIRON, 0, 3]) + b"DEVNAME" + b"\x01"
                             + b"WS01" + bytes([IAC, SE]))
    # Without a device name the option is refused, as before.
    out2 = []
    plain = TelnetProtocol(out2.append, "IBM-3179-2", tn3270=True)
    plain.receive(bytes([IAC, DO, NEW_ENVIRON]))
    assert out2 == [bytes([IAC, WONT, NEW_ENVIRON])]


class FakeIBMi(threading.Thread):
    """Negotiates TN5250 like IBM i, sends a sign-on panel, keeps the reply record."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.term_type = None
        self.environ = None
        self.reply = None
        self.got_reply = threading.Event()

    def _until(self, conn, buf, marker):
        while marker not in buf:
            buf += conn.recv(4096)
        return buf

    def run(self):
        conn, _ = self.srv.accept()
        conn.settimeout(10)
        conn.sendall(bytes([IAC, DO, NEW_ENVIRON, IAC, DO, TTYPE]))
        buf = self._until(conn, b"", bytes([IAC, WILL, TTYPE]))
        conn.sendall(bytes([IAC, SB, NEW_ENVIRON, 1, 0, 3, IAC, SE,
                            IAC, SB, TTYPE, 1, IAC, SE]))
        buf = self._until(conn, buf, b"IBM-")
        buf = self._until(conn, buf[buf.index(b"IBM-"):], bytes([IAC, SE]))
        self.term_type = buf[:buf.index(bytes([IAC, SE]))].decode()
        conn.sendall(bytes([IAC, DO, EOR, IAC, WILL, EOR, IAC, DO, BINARY, IAC, WILL, BINARY]))
        conn.sendall(record(SIGNON))
        buf = b""
        while True:
            buf += conn.recv(4096)
            if b"\x12\xa0" in buf and buf.endswith(bytes([IAC, EOR_CMD])):
                break
        self.environ = buf
        start = buf.index(b"\x12\xa0") - 2
        self.reply = buf[start:-2].replace(b"\xff\xff", b"\xff")
        self.got_reply.set()
        conn.close()


def test_session_against_fake_ibm_i(tmp_path):
    host = FakeIBMi()
    host.start()
    profile = SessionProfile(name="i", transport="telnet", host="127.0.0.1", port=host.port,
                             emulation="ibm3179-2", device_name="CHERM01")
    session = Session(profile, ProfileStore(tmp_path, site_roots=[]))
    updated = threading.Event()
    session.connect(on_update=updated.set)
    try:
        deadline = time.monotonic() + 5
        while "Sign On" not in session.screen.text() and time.monotonic() < deadline:
            updated.wait(0.1)
            updated.clear()
        assert "Sign On" in session.screen.text()
        assert host.term_type == "IBM-3179-2"
        session.key("A", "a")
        session.key("Tab")
        session.key("X", "x")
        session.key("Enter")
        assert host.got_reply.wait(5)
        assert host.reply == gds(bytes([7, 54, AID_ENTER]) + sba(6, 53) + e("A")
                                 + sba(7, 53) + e("x"))
        assert session.emulation.locked
    finally:
        session.disconnect()


def test_new_environ_devname_over_the_wire(tmp_path):
    """The DEVNAME reply reaches the host before the TTYPE answer is used."""
    host = FakeIBMi()
    host.start()
    seen = []
    from cherminal.transport.telnet import TelnetTransport
    t = TelnetTransport("127.0.0.1", host.port, term_type="IBM-3477-FC", tn3270=True,
                        device_name="CHERM02")
    orig = t._raw_send

    def spy(data):
        seen.append(data)
        orig(data)

    t._raw_send = spy
    t.proto.send = spy
    got = []
    t.on_data = got.append
    t.open(80, 24)
    try:
        deadline = time.monotonic() + 5
        while not got and time.monotonic() < deadline:
            time.sleep(0.05)
        wire = b"".join(seen)
        assert b"DEVNAME\x01CHERM02" in wire
        assert host.term_type == "IBM-3477-FC"
    finally:
        t.close()


@pytest.fixture
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PyQt6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_editor_device_name_only_for_5250(qapp, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    store = ProfileStore(tmp_path, site_roots=[])
    ed = SessionEditor(SessionProfile(name="i", transport="telnet", host="h",
                                      emulation="ibm3179-2", device_name="WS01"), store)
    assert ed._form.isRowVisible(ed.device_name)
    ed.device_name.setText("ws02")
    assert ed._build().device_name == "WS02"
    ed.emulation.setCurrentText("ibm3278-2")
    assert not ed._form.isRowVisible(ed.device_name)
    assert ed._build().device_name == ""
    ed.emulation.setCurrentText("ibm3477-fc")
    ed.transport.setCurrentText("ssh")
    assert not ed._form.isRowVisible(ed.device_name)


def test_keyboard_editor_offers_5250_keys(qapp, tmp_path):
    from cherminal.gui.keyboard import KeyboardEditor
    store = ProfileStore(tmp_path, site_roots=[])
    p = SessionProfile(transport="telnet", host="h", emulation="ibm3179-2")
    ed = KeyboardEditor(store.build_keymap(p), {}, block_mode=True, family="ibm5250",
                        store=store, base_name="ibm5250")
    ed.buttons["F3"].click()
    assert ed.default_label.text() == "F3"
    assert "Field Exit" in ed.labels.values() and "Attention" in ed.labels.values()


def test_terminal_widget_shows_5250_oia(qapp, tmp_path):
    from cherminal.gui.terminal import TerminalWidget
    store = ProfileStore(tmp_path, site_roots=[])
    session = Session(SessionProfile(name="i", transport="telnet", host="h",
                                     emulation="ibm3477-fc"), store)
    term = TerminalWidget(session)
    session.feed(record(SIGNON))
    assert "006/053" in term.status_text()
    session.key("Q", "q")
    session.key("Enter")
    assert "X SYSTEM" in term.status_text()
    term.resize(800, 300)
    assert not term.grab().isNull()
