import os

import pytest

from cherminal import policy
from cherminal.config import ProfileStore, SessionProfile, split_host_port
from cherminal.emulation.base import InputField
from cherminal.emulation.hotspots import ScreenKey, screen_keys
from cherminal.keymap import Keymap
from test_ibm3270 import LOGON, addr, e, record
from test_ibm3270 import emu as emu3270
from test_ibm5250 import PASSWORD, USER
from test_ibm5250 import signed_on as signed_on_5250

# ------------------------------------------------------------ screen keys


def test_screen_keys_from_the_last_rows():
    lines = ["MAIN MENU  F1=Help in the title row is too high up", "", "",
             " Command ===> ____",
             " F1=Help  F3=Exit  PF7 = Back  F8=Forward  PA1  Press ENTER  F12=Cancel",
             " CLEAR to end   PF03 ==> End   F3=Quit"]
    assert screen_keys(lines) == [
        ScreenKey("pf1", "Help"), ScreenKey("pf3", "Exit"), ScreenKey("pf7", "Back"),
        ScreenKey("pf8", "Forward"), ScreenKey("pa1", ""), ScreenKey("pf12", "Cancel"),
        ScreenKey("clear", "")]                     # Enter is always on the bar; F3 once
    assert screen_keys(["nothing here"] * 24) == []


def test_key_for_finds_the_keyboard_key():
    km = Keymap.builtin("ibm3270", mac=False)
    assert km.key_for("pf3") == "F3"
    assert km.key_for("pf13") == "Shift+F1"         # not F13, which few keyboards have
    assert km.key_for("pa1") == "Alt+F1"
    assert km.key_for("enter") == "Enter"
    assert km.key_for("nothing") == ""
    km5250 = Keymap.builtin("ibm5250", mac=False)
    assert km5250.key_for("pf3") == "F3"            # 5250 binds action:f3
    assert km5250.key_for("attn") == "Pause"
    km.update({"F3": "action:pf15"})
    assert km.key_for("pf3") == ""


# ------------------------------------------------------------- input fields


def test_3270_input_fields_and_click():
    em, screen, _ = emu3270()
    em.feed(record(LOGON))
    fields = em.input_fields()
    assert fields == [InputField(0, 13, 8), InputField(1, 16, 8, hidden=True)]
    assert em.click(1 * 80 + 18)                    # into the password field
    assert (screen.y, screen.x) == (1, 18)
    assert not em.click(1 * 80 + 2)                 # protected label: the cursor stays
    assert (screen.y, screen.x) == (1, 18)
    em.type_text("A")
    assert em.input_fields()[1].modified
    em.do_action("enter")
    assert em.locked and not em.click(12)           # waiting for the host


def test_3270_numeric_field_and_wrapping_field():
    em, _, _ = emu3270()
    em.feed(record(b"\xf5\xc3" + b"\x11" + addr(0, 74) + b"\x1d\x50" + b"\x00" * 9
                   + b"\x1d\x60"))
    # A numeric field from row 1 col 76 runs on to row 2: one box per row.
    assert em.input_fields() == [InputField(0, 75, 5, numeric=True),
                                 InputField(1, 0, 4, numeric=True)]


def test_3270_unformatted_screen_clicks_anywhere():
    em, screen, _ = emu3270()
    assert em.input_fields() == []
    assert em.click(5 * 80 + 9) and (screen.y, screen.x) == (5, 9)


def test_5250_input_fields_and_click():
    em, screen, _ = signed_on_5250()
    assert em.input_fields() == [InputField(5, 52, 10), InputField(6, 52, 10, hidden=True)]
    assert em.click(PASSWORD + 3) and em.cursor == PASSWORD + 3
    assert not em.click(5 * 80 + 20)                # "User . . ." is not a field
    assert em.cursor == PASSWORD + 3
    assert em.click(USER) and (screen.y, screen.x) == (5, 52)


def test_character_mode_has_no_fields(term):
    vt, screen, _ = term("vt220")
    assert vt.input_fields() == [] and not vt.click(10)


# ----------------------------------------------------------- settings


def test_policy_decides_the_starting_view():
    allowed, default, off = (policy.Policy.from_dict({"modern_view": v})
                             for v in ("allowed", "default", "off"))
    assert [allowed.modern(v) for v in ("", "classic", "modern")] == [False, False, True]
    assert [default.modern(v) for v in ("", "classic", "modern")] == [True, False, True]
    assert [off.modern(v) for v in ("", "classic", "modern")] == [False, False, False]
    assert policy.Policy().modern_view == "allowed"
    with pytest.raises(policy.PolicyError, match="modern_view"):
        policy.Policy.from_dict({"modern_view": "sometimes"})


def test_profile_view_and_port_checks():
    assert SessionProfile(emulation="ibm3278-2", transport="telnet", view="modern").view
    assert "view" not in SessionProfile().to_dict()
    with pytest.raises(ValueError, match="view"):
        SessionProfile(view="fancy")
    with pytest.raises(ValueError, match="port"):
        SessionProfile(transport="telnet", port=70000)
    assert SessionProfile(transport="telnet", host="mf", port=2323).effective_port == 2323


def test_split_host_port():
    assert split_host_port("mainframe.example.com:2323") == ("mainframe.example.com", 2323)
    assert split_host_port(" 10.1.2.3:23 ") == ("10.1.2.3", 23)
    assert split_host_port("mainframe") == ("mainframe", 0)
    assert split_host_port("fe80::1") == ("fe80::1", 0)            # IPv6, no port
    assert split_host_port("host:99999") == ("host:99999", 0)       # left for the user to fix


# ------------------------------------------------------------------ GUI

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


PANEL = (b"\xf5\xc3"
         + b"\x11" + addr(3, 1) + b"\x1d\x60" + e("Customer number . .")
         + b"\x1d\x50" + b"\x13" + b"\x00" * 10 + b"\x1d\x60"
         + b"\x11" + addr(20, 1) + b"\x1d\x60" + e("Command ===>")
         + b"\x1d\x40" + b"\x00" * 40 + b"\x1d\x60"
         + b"\x11" + addr(22, 1) + e("F1=Help  F3=Exit  F12=Cancel"))


def _term(tmp_path, **kw):
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2", **kw),
                ProfileStore(tmp_path, site_roots=[]))
    sent = []
    s._reply = sent.append
    s.emulation.reply = sent.append
    s.feed(record(PANEL))
    term = TerminalWidget(s)
    term.resize(900, 600)
    term._fit_font()
    return term, sent


def test_classic_unless_chosen(app, tmp_path):
    term, _ = _term(tmp_path)
    assert term.can_be_modern and not term.modern
    term, _ = _term(tmp_path, view="modern")
    assert term.modern
    policy.set_current(policy.Policy.from_dict({"modern_view": "off"}))
    term, _ = _term(tmp_path, view="modern")
    assert not term.modern


def test_set_modern_spaces_rows_and_paints_fields(app, tmp_path):
    term, _ = _term(tmp_path)
    classic_ch = term.ch
    term.set_modern(True)
    term._fit_font()
    assert term.modern
    assert term.ch > term.cw * 1.5 and term.ch * 24 <= term.height()
    assert term.ch / term.cw > classic_ch / term.cw
    term.grab()                                     # paints the field boxes without error
    term.set_modern(False)
    assert not term.modern


def test_click_moves_the_cursor_only_in_modern_view(app, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QMouseEvent
    from test_hotspots import _mouse
    T = QMouseEvent.Type
    term, _ = _term(tmp_path)
    s = term.session.screen
    start = (s.y, s.x)
    _mouse(term, T.MouseButtonPress, 20, 20, Qt.MouseButton.LeftButton)
    _mouse(term, T.MouseButtonRelease, 20, 20, Qt.MouseButton.LeftButton)
    assert (s.y, s.x) == start                      # classic: unchanged behaviour
    term.set_modern(True)
    term._fit_font()
    _mouse(term, T.MouseButtonPress, 20, 20, Qt.MouseButton.LeftButton)
    _mouse(term, T.MouseButtonRelease, 20, 20, Qt.MouseButton.LeftButton)
    assert (s.y, s.x) == (20, 20)
    _mouse(term, T.MouseButtonPress, 3, 3, Qt.MouseButton.LeftButton)    # a label
    _mouse(term, T.MouseButtonRelease, 3, 3, Qt.MouseButton.LeftButton)
    assert (s.y, s.x) == (20, 20)


def test_key_bar_buttons_press_keys(app, tmp_path):
    from PyQt6.QtWidgets import QPushButton

    from cherminal.gui.keybar import KeyBar, KeyButton
    term, sent = _term(tmp_path)
    bar = KeyBar()
    bar.set_terminal(term)
    assert bar.isHidden()                           # classic: no bar
    term.set_modern(True)
    assert not bar.isHidden()
    buttons = {b.label.text(): b for b in bar.findChildren(KeyButton)}
    assert list(buttons) == ["Help", "Exit", "Cancel", "Send"]
    assert buttons["Exit"].hint.text() == "F3" and buttons["Send"].hint.text() == "Enter"
    more = [b for b in bar.findChildren(QPushButton) if b.text() == "More keys"][0]
    names = [a.text().split("\t")[0] for a in more.menu().actions()]
    assert names[:4] == ["PA1", "PA2", "PA3", "Clear"] and names[-1] == "PF keys"
    buttons["Exit"].click()
    assert sent and sent[-1][:1] == b"\xf3"         # PF3's AID
    term.session.emulation.do_action("reset")
    buttons["Send"].click()
    assert sent[-1][:1] == b"\x7d"                  # Enter


def test_main_window_switch(app, tmp_path):
    from cherminal.gui.app import MainWindow
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]))
    term, _ = _term(tmp_path)
    term.connect_session = lambda: None
    win.tabs.addTab(term, "mf")
    win._tab_changed(0)
    assert win.modern_action.isVisible() and not win.modern_action.isChecked()
    win.modern_action.setChecked(True)
    win.toggle_modern()
    assert term.modern and not win.keybar.isHidden()
    vt = _vt(tmp_path)
    win.tabs.addTab(vt, "unix")
    win.tabs.setCurrentWidget(vt)
    assert not win.modern_action.isVisible() and win.keybar.isHidden()


def _vt(tmp_path):
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    return TerminalWidget(Session(SessionProfile(), ProfileStore(tmp_path, site_roots=[])))


def test_editor_port_and_view(app, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    ed = SessionEditor(SessionProfile(name="mf", transport="telnet", host="h",
                                      emulation="ibm3278-2"),
                       ProfileStore(tmp_path, site_roots=[]))
    assert ed.port.specialValueText() == "default (23)"
    ed.tls.setChecked(True)
    assert ed.port.specialValueText() == "default (992)"
    ed.tls.setChecked(False)
    ed.host.setText("mainframe.example.com:2323")
    built = ed._build()
    assert (built.host, built.port, built.view) == ("mainframe.example.com", 2323, "")
    ed.host.setText("mainframe.example.com")
    ed.port.setValue(2323)
    ed.view.setCurrentIndex(ed.view.findData("modern"))
    built = ed._build()
    assert (built.host, built.port, built.view) == ("mainframe.example.com", 2323, "modern")
