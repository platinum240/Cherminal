"""The window's look: Graphite, Paper, follow the desktop, or Classic."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from cherminal.config import ProfileStore, SessionProfile


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def make_win(app, monkeypatch):
    from cherminal.gui.app import MainWindow
    from cherminal.gui.terminal import TerminalWidget
    monkeypatch.setattr(TerminalWidget, "connect_session", lambda self: None)
    made = []

    def make(store):
        w = MainWindow(store)
        made.append(w)
        return w
    yield make
    for w in made:
        w.set_appearance("classic", save=False)       # leave the app as other tests expect
        w.disconnect_all()
        w.deleteLater()


def test_system_follows_the_desktop():
    from cherminal.gui import appearance
    assert appearance.resolve("system", dark=True).name == "graphite"
    assert appearance.resolve("system", dark=False).name == "paper"
    assert appearance.resolve("paper", dark=True).name == "paper"
    assert appearance.resolve("classic", dark=True) is None


def test_close_icons_ship_with_the_app(app):
    from pathlib import Path
    from cherminal.gui import appearance
    for theme in appearance.THEMES.values():
        css = appearance.stylesheet(theme)
        for name in (f"tab-close-{theme.name}.svg", "tab-close-hover.svg", "check.svg"):
            assert name in css
            assert Path(str(appearance.RESOURCES / name)).is_file()
        assert "\\" not in css.split("url(")[1].split(")")[0]     # forward slashes, even on Windows


def test_status_line_dot_and_dividers():
    from cherminal.gui.appearance import THEMES, status_html
    g = THEMES["graphite"]
    on = status_html("Connected · TELNET wms:23 · VT220 · 80×24", g)
    assert g.ok in on and on.count("│") == 3 and ">Connected<" in on
    off = status_html("Not connected · TELNET <host>:23", g)
    assert g.ok not in off and "&lt;host&gt;" in off
    assert status_html("", g) == ""


def test_settings_round_trip(tmp_path):
    store = ProfileStore(tmp_path, site_roots=[])
    assert store.settings() == {}
    store.save_setting("appearance", "paper")
    assert ProfileStore(tmp_path, site_roots=[]).settings() == {"appearance": "paper"}
    store.settings_path.write_text("not = [valid")
    assert store.settings() == {}


def test_window_uses_and_saves_the_appearance(make_win, tmp_path, app):
    store = ProfileStore(tmp_path, site_roots=[])
    store.save_setting("appearance", "paper")
    win = make_win(store)
    assert win.appearance == "paper" and win.theme.name == "paper"
    assert win.appearance_actions["paper"].isChecked()
    assert "tab-close-paper.svg" in app.styleSheet()
    assert not win.tabs.tabBar().drawBase()
    assert "#sessionTabs" in app.styleSheet()      # dialogs' tabs are left alone

    win.set_appearance("graphite")
    assert store.settings()["appearance"] == "graphite"
    assert app.palette().window().color().name() == "#16181d"

    term = win.open_session(SessionProfile(name="Host", transport="telnet", host="h.example"))
    assert "●" in win.status.text() and "Not connected" in win.status_plain

    win.set_appearance("classic")
    assert app.styleSheet() == ""
    assert win.status.text() == term.status_text()
    assert win.tabs.tabBar().drawBase()


def test_roomy_close_button_closes_its_own_tab(make_win, tmp_path):
    from PyQt6.QtWidgets import QTabBar, QToolButton
    from cherminal.gui.appearance import CLOSE_MARGIN, CLOSE_SIZE
    store = ProfileStore(tmp_path, site_roots=[])
    store.save_setting("appearance", "graphite")
    win = make_win(store)
    for name in ("One", "Two", "Three"):
        win.open_session(SessionProfile(name=name, transport="telnet", host="h.example"))
    bar = win.tabs.tabBar()
    holder = bar.tabButton(1, QTabBar.ButtonPosition.RightSide)
    button = holder.findChild(QToolButton, "tabClose")
    assert button.width() == CLOSE_SIZE and holder.layout().contentsMargins().right() == CLOSE_MARGIN[2]
    button.click()
    assert [win.tabs.tabText(i) for i in range(win.tabs.count())] == ["One", "Three"]
    bar.moveTab(1, 0)                                   # dragged tabs keep the right button
    bar.tabButton(0, QTabBar.ButtonPosition.RightSide).findChild(QToolButton, "tabClose").click()
    assert [win.tabs.tabText(i) for i in range(win.tabs.count())] == ["One"]

    win.set_appearance("classic")                       # the desktop's own button comes back
    stock = bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
    assert stock is not None and stock.objectName() != "tabClose" and not stock.findChild(QToolButton, "tabClose")
    win.set_appearance("paper")
    assert bar.tabButton(0, QTabBar.ButtonPosition.RightSide).findChild(QToolButton, "tabClose")


def test_unknown_setting_falls_back_to_the_desktop(make_win, tmp_path):
    store = ProfileStore(tmp_path, site_roots=[])
    store.save_setting("appearance", "purple")
    assert make_win(store).appearance == "system"
