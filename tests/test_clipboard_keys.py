"""Copy and paste keys: Ctrl+C/Ctrl+V on Linux and Windows, Command on a Mac.

Ctrl+C copies only while text is selected; otherwise it is still the host's
interrupt (0x03). Ctrl+V pastes unless the session turns that off.
"""

import os

import pytest
from PyQt6 import QtGui
from PyQt6.QtCore import QEvent, Qt

from cherminal import system
from cherminal.config import ProfileStore, SessionProfile
from cherminal.session import Session
from cherminal.transport.base import Transport

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
K, M = Qt.Key, Qt.KeyboardModifier


class FakeTransport(Transport):
    def __init__(self):
        super().__init__()
        self.sent = bytearray()

    def write(self, data):
        self.sent += data


@pytest.fixture
def pc(monkeypatch):
    monkeypatch.setattr(system, "IS_MAC", False)


def make(tmp_path, **kw):
    t = FakeTransport()
    s = Session(SessionProfile(**kw), ProfileStore(tmp_path, site_roots=[]), transport=t)
    actions = []
    s.on_action = actions.append
    return s, t, actions


@pytest.mark.parametrize("emulation", ["vt220", "xterm", "scoansi", "tvi950", "wyse60", "ibm3278-2", "ibm3179-2"])
def test_ctrl_v_pastes_and_ctrl_c_copies_only_a_selection(pc, tmp_path, emulation):
    s, t, actions = make(tmp_path, emulation=emulation, transport="telnet", host="h")
    assert s.key("Ctrl+V", "\x16")
    assert actions == ["paste"]
    s.has_selection = lambda: True
    assert s.key("Ctrl+C", "\x03")
    assert actions == ["paste", "copy"]
    assert b"\x03" not in t.sent and b"\x16" not in t.sent


def test_ctrl_c_interrupts_with_nothing_selected(pc, tmp_path):
    s, t, actions = make(tmp_path, emulation="ansi")
    assert s.key("Ctrl+C", "\x03")
    assert bytes(t.sent) == b"\x03" and actions == []


def test_setting_off_sends_both_to_the_host(pc, tmp_path):
    s, t, actions = make(tmp_path, emulation="tvi950", ctrl_copy_paste=False)
    s.has_selection = lambda: True
    s.key("Ctrl+C", "\x03")
    s.key("Ctrl+V", "\x16")
    assert bytes(t.sent) == b"\x03\x16" and actions == []
    s.key("Ctrl+Shift+V", "\x16")           # the terminal-style keys still work
    assert actions == ["paste"]


def test_session_keys_win(pc, tmp_path):
    s, t, actions = make(tmp_path, keys={"Ctrl+V": "^V"})
    s.key("Ctrl+V", "\x16")
    assert bytes(t.sent) == b"\x16" and actions == []


def test_setting_round_trips(tmp_path):
    assert "ctrl_copy_paste" not in SessionProfile(name="a").to_dict()
    p = SessionProfile.from_dict(SessionProfile(name="a", ctrl_copy_paste=False).to_dict())
    assert p.ctrl_copy_paste is False


def test_mac_leaves_ctrl_to_the_host(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "IS_MAC", True)
    s, t, actions = make(tmp_path)
    s.key("Ctrl+V", "\x16")
    assert bytes(t.sent) == b"\x16" and actions == []


def test_mac_command_c_and_v_in_the_terminal(monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication

    from cherminal.gui.terminal import TerminalWidget
    app = QApplication.instance() or QApplication([])  # noqa: F841 (kept alive)
    monkeypatch.setattr(system, "IS_MAC", True)
    profile = SessionProfile(transport="telnet", host="127.0.0.1", emulation="xterm")
    term = TerminalWidget(Session(profile, ProfileStore(tmp_path, site_roots=[])))
    done = []
    monkeypatch.setattr(term, "do_action", done.append)
    monkeypatch.setattr(term.session, "key", lambda *a: pytest.fail("Command reached the host"))
    for key, action in ((K.Key_V, "paste"), (K.Key_C, "copy")):
        # Qt reports Command as Control on a Mac.
        override = QtGui.QKeyEvent(QEvent.Type.ShortcutOverride, key, M.ControlModifier)
        assert term.event(override) and override.isAccepted()   # the menu does not also fire
        term.keyPressEvent(QtGui.QKeyEvent(QEvent.Type.KeyPress, key, M.ControlModifier))
    assert done == ["paste", "copy"]
    # Command+Shift+V, Command+Option+C and Control+V (Meta) are not the clipboard keys.
    for mods in (M.ControlModifier | M.ShiftModifier, M.ControlModifier | M.AltModifier,
                 M.MetaModifier):
        ev = QtGui.QKeyEvent(QEvent.Type.ShortcutOverride, K.Key_V, mods)
        assert term._mac_clipboard_key(ev) == ""


def test_terminal_paste_reaches_the_host(monkeypatch, tmp_path, pc):
    from PyQt6.QtWidgets import QApplication

    from cherminal.gui.terminal import TerminalWidget
    app = QApplication.instance() or QApplication([])  # noqa: F841 (kept alive)
    t = FakeTransport()
    session = Session(SessionProfile(emulation="ansi"), ProfileStore(tmp_path, site_roots=[]),
                      transport=t)
    term = TerminalWidget(session)
    QtGui.QGuiApplication.clipboard().setText("hello")
    term.keyPressEvent(QtGui.QKeyEvent(QEvent.Type.KeyPress, K.Key_V, M.ControlModifier, "\x16"))
    assert bytes(t.sent) == b"hello"
