"""Split screen: up to four sessions side by side in one tab."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from cherminal.config import ProfileStore, SessionProfile


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    from cherminal.gui.app import MainWindow
    from cherminal.gui.terminal import TerminalWidget
    monkeypatch.setattr(TerminalWidget, "connect_session", lambda self: None)
    w = MainWindow(ProfileStore(tmp_path, site_roots=[]))
    yield w
    w.disconnect_all()
    w.deleteLater()


def _profile(name):
    return SessionProfile(name=name, transport="telnet", host=f"{name.lower()}.example")


def _menu_texts(term):
    """The context menu's entries, without showing it."""
    from PyQt6.QtWidgets import QMenu
    seen = []
    orig = QMenu.exec

    def fake_exec(menu, *a, **k):
        for act in menu.actions():
            seen.append((act.text(), act.isEnabled()))
            if act.menu():
                seen.extend((f"  {s.text()}", s.isEnabled()) for s in act.menu().actions())
    QMenu.exec = fake_exec
    try:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QContextMenuEvent
        term.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1)))
    finally:
        QMenu.exec = orig
    return dict(seen)


def test_split_up_to_four_panes(win):
    from cherminal.gui.split import SplitView
    a = win.open_session(_profile("Alpha"))
    assert win.tabs.count() == 1 and win._term() is a
    menu = _menu_texts(a)
    assert menu["Split screen"] and "  With another session…" in menu
    assert "Close this pane" not in menu

    b = win.split_session(a)                         # same session again, beside it
    view = win.tabs.currentWidget()
    assert isinstance(view, SplitView) and win.tabs.count() == 1
    assert view.terms() == [a, b] and win._term() is b
    assert b.session.profile.host == "alpha.example"
    assert win.tabs.tabText(0) == "Alpha | Alpha"
    assert "Close this pane" in _menu_texts(b)

    c = win.split_session(b)
    d = win.split_session(c)
    assert view.terms() == [a, b, c, d]
    # Two rows of two.
    rows = view._rows
    assert rows.count() == 2 and [rows.widget(i).count() for i in range(2)] == [2, 2]
    win.show()
    assert all(t.isVisible() for t in (a, b, c, d))
    assert win.split_session(d) is None              # full
    assert len(view.terms()) == 4
    menu = _menu_texts(d)
    assert not menu["Split screen (4 panes is the most)"]
    assert not win.split_action.isEnabled() and win.close_pane_action.isEnabled()


def test_active_pane_drives_the_window(win):
    a = win.open_session(_profile("Alpha"))
    b = win.split_session(a)
    view = win.tabs.currentWidget()
    view.set_active(a)
    assert win._term() is a
    win.next_pane()
    assert win._term() is b
    win.next_pane()
    assert win._term() is a


def test_close_pane_and_tab(win):
    a = win.open_session(_profile("Alpha"))
    b = win.split_session(a)
    c = win.split_session(b)
    view = win.tabs.currentWidget()
    closed = []
    b.shutdown = lambda: closed.append("b")
    win.close_pane(b)
    assert view.terms() == [a, c] and closed == ["b"]
    assert win._term() is c
    win.close_pane(c)
    assert view.terms() == [a] and win.tabs.tabText(0) == "Alpha"
    assert not win.close_pane_action.isEnabled()
    win.close_pane(a)                                # the last pane closes the tab
    assert win.tabs.count() == 0


def test_close_tab_shuts_every_pane(win):
    a = win.open_session(_profile("Alpha"))
    b = win.split_session(a)
    closed = []
    a.shutdown = lambda: closed.append("a")
    b.shutdown = lambda: closed.append("b")
    win.close_tab(0)
    assert sorted(closed) == ["a", "b"] and win.tabs.count() == 0


def test_reconnect_keeps_the_pane_in_place(win):
    a = win.open_session(_profile("Alpha"))
    b = win.split_session(a)
    view = win.tabs.currentWidget()
    view.set_active(a)
    win.reconnect()
    new = view.terms()[0]
    assert new is not a and view.terms()[1] is b and win._term() is new
    assert win.tabs.count() == 1


def test_split_with_another_session(win, monkeypatch):
    from cherminal.gui import app as app_mod
    a = win.open_session(_profile("Alpha"))

    class Chooser:
        def __init__(self, *a, **k):
            self.chosen = _profile("Bravo")

        def exec(self):
            return True
    monkeypatch.setattr(app_mod, "SessionManager", Chooser)
    b = win.split_session(a, "choose")
    assert b.session.profile.name == "Bravo"
    assert win.tabs.tabText(0) == "Alpha | Bravo"


def test_limited_users_split_only_their_own_session(app, tmp_path, monkeypatch):
    from cherminal.gui.app import MainWindow
    from cherminal.gui.terminal import TerminalWidget
    monkeypatch.setattr(TerminalWidget, "connect_session", lambda self: None)
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]), limited=True)
    a = win.open_session(_profile("Alpha"))
    menu = _menu_texts(a)
    assert "  With this session" in menu and "  With another session…" not in menu
    assert win.split_session(a, "choose") is None
    assert win.split_session(a) is not None
    win.disconnect_all()


def test_terminal_put_in_a_tab_by_hand_can_split(win, tmp_path):
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    t = TerminalWidget(Session(_profile("Alpha"), win.store))
    win.tabs.addTab(t, "Alpha")
    win.tabs.setCurrentWidget(t)
    assert win._term() is t
    n = win.split_session(t)
    assert n is not None and win.tabs.currentWidget().terms() == [t, n]
