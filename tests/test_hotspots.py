import os

import pytest

from cherminal.emulation.hotspots import find_hotspots, hotspot_at

ISPF = " F1=Help    F2=Split   F3=Exit    F5=Rfind   F7=Up      F8=Down    F12=Cancel"
CICS = "PF3 = Exit   PF7 Back  PA1  Press ENTER to continue, CLEAR to end   PF24=Retrieve"


def spots(line):
    return [(line[s.start:s.end], s.action) for s in find_hotspots(line)]


def test_ispf_function_key_line():
    assert spots(ISPF) == [("F1=Help", "pf1"), ("F2=Split", "pf2"), ("F3=Exit", "pf3"),
                           ("F5=Rfind", "pf5"), ("F7=Up", "pf7"), ("F8=Down", "pf8"),
                           ("F12=Cancel", "pf12")]


def test_cics_style_keys_and_words():
    assert spots(CICS) == [("PF3 = Exit", "pf3"), ("PF7", "pf7"), ("PA1", "pa1"),
                           ("ENTER", "enter"), ("CLEAR", "clear"),
                           ("PF24=Retrieve", "pf24")]


def test_things_that_are_not_keys():
    line = "F3 is bare, XPF3, PF3X, PF25=x, PA4, ENTERED, Enter here, F0=x, PF3=Exit."
    assert spots(line) == [("PF3=Exit.", "pf3")]
    assert spots("TSO1 ===> IKJ56700A ENTER USERID -") == [("ENTER", "enter")]
    assert spots("") == []


def test_hotspot_at_columns():
    spot = hotspot_at(ISPF, ISPF.index("F3=Exit") + 4)
    assert spot.action == "pf3" and ISPF[spot.start:spot.end] == "F3=Exit"
    assert hotspot_at(ISPF, ISPF.index("F3=Exit") - 1) is None
    assert hotspot_at(ISPF, len(ISPF) + 5) is None


# ------------------------------------------------------------------ GUI

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _term(tmp_path, **kw):
    from cherminal.config import ProfileStore, SessionProfile
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    from test_ibm3270 import addr, e, record
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2", **kw),
                ProfileStore(tmp_path, site_roots=[]))
    sent = []
    s._reply = sent.append
    s.emulation.reply = sent.append
    s.feed(record(b"\xf5\xc3\x11" + addr(22, 0) + b"\x1d\x60" + e(" PF3=Exit  PF8=Down")))
    term = TerminalWidget(s)
    term.resize(800, 480)
    term._fit_font()
    return term, sent


def _mouse(term, kind, col, row, button=None):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    pos = QPointF(term.offset_x + col * term.cw + 2, term.offset_y + row * term.ch + 2)
    b = button or Qt.MouseButton.NoButton
    event = QMouseEvent(kind, pos, pos, b, b if kind != QMouseEvent.Type.MouseButtonRelease
                        else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    {QMouseEvent.Type.MouseMove: term.mouseMoveEvent,
     QMouseEvent.Type.MouseButtonPress: term.mousePressEvent,
     QMouseEvent.Type.MouseButtonRelease: term.mouseReleaseEvent}[kind](event)


def test_click_on_hotspot_sends_the_key(app, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QMouseEvent
    T = QMouseEvent.Type
    term, sent = _term(tmp_path)
    assert term.hasMouseTracking()
    _mouse(term, T.MouseMove, 4, 22)
    assert term._hot == (22, 2, 10, "pf3")
    assert term.cursor().shape() == Qt.CursorShape.PointingHandCursor
    term.grab()                                        # paints the underline
    _mouse(term, T.MouseMove, 40, 22)
    assert term._hot is None and term.cursor().shape() == Qt.CursorShape.IBeamCursor
    _mouse(term, T.MouseButtonPress, 13, 22, Qt.MouseButton.LeftButton)
    _mouse(term, T.MouseButtonRelease, 13, 22, Qt.MouseButton.LeftButton)
    assert sent and sent[-1][:1] == b"\xf8"            # PF8's AID
    assert term.session.emulation.locked


def test_drag_from_hotspot_selects_instead(app, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QMouseEvent
    T = QMouseEvent.Type
    term, sent = _term(tmp_path)
    _mouse(term, T.MouseButtonPress, 3, 22, Qt.MouseButton.LeftButton)
    _mouse(term, T.MouseMove, 9, 22, Qt.MouseButton.LeftButton)
    _mouse(term, T.MouseButtonRelease, 9, 22, Qt.MouseButton.LeftButton)
    assert sent == [] and term.selected_text() == "F3=Exi"


def test_hotspots_can_be_turned_off(app, tmp_path):
    from PyQt6.QtGui import QMouseEvent
    term, sent = _term(tmp_path, hotspots=False)
    assert not term.hasMouseTracking()
    _mouse(term, QMouseEvent.Type.MouseMove, 4, 22)
    assert term._hot is None


def test_editor_hotspots_checkbox(app, tmp_path):
    from cherminal.config import ProfileStore, SessionProfile
    from cherminal.gui.dialogs import SessionEditor
    ed = SessionEditor(SessionProfile(name="mf", transport="telnet", host="h",
                                      emulation="ibm3278-2", hotspots=False),
                       ProfileStore(tmp_path, site_roots=[]))
    assert not ed.hotspots.isChecked() and ed._build().hotspots is False
    ed.hotspots.setChecked(True)
    assert ed._build().hotspots is True
    assert "hotspots" not in SessionProfile().to_dict()
