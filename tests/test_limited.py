import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from cherminal import __main__ as cli  # noqa: E402
from cherminal.config import ProfileStore, SessionProfile  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def menu_items(win, title):
    for act in win.menuBar().actions():
        if act.text().replace("&", "") == title:
            return [a.text().replace("&", "") for a in act.menu().actions() if a.text()]
    return None


def all_shortcuts(win):
    return {a.shortcut().toString() for m in win.menuBar().actions()
            for a in m.menu().actions() if not a.shortcut().isEmpty()}


def test_limited_file_menu(app, tmp_path):
    from cherminal.gui.app import MainWindow
    store = ProfileStore(tmp_path, site_roots=[])
    full = MainWindow(store)
    assert "Local shell" in menu_items(full, "File")
    limited = MainWindow(store, limited=True)
    assert menu_items(limited, "File") == ["Close tab", "Exit"]
    # Their shortcuts are gone too, not just the menu entries.
    assert {"Ctrl+Shift+O", "Ctrl+Shift+N", "Ctrl+Shift+T"} & all_shortcuts(limited) == set()
    assert {"Ctrl+Shift+W", "Ctrl+Shift+Q"} <= all_shortcuts(limited)


def test_limited_session_picker(app, tmp_path):
    from cherminal.gui.dialogs import SessionManager
    store = ProfileStore(tmp_path, site_roots=[])
    store.save(SessionProfile(name="Mainframe A", transport="telnet", host="mf"))
    store.save(SessionProfile(name="Shell", transport="local"))
    dlg = SessionManager(store, limited=True)
    buttons = [b.text() for b in dlg.findChildren(QtWidgets.QPushButton)]
    assert sorted(buttons) == ["Close", "Connect"]
    names = [dlg.list.item(i).data(0x0100).name for i in range(dlg.list.count())]
    assert names == ["Mainframe A"]


def test_cli_passes_limited(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "none"))
    monkeypatch.delenv("CHERMINAL_SITE_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    ProfileStore().save(SessionProfile(name="Mainframe A", transport="telnet", host="mf"))
    seen = {}
    import cherminal.gui.app as gui_app
    monkeypatch.setattr(gui_app, "run", lambda profiles, store, show_manager, limited=False:
                        seen.update(names=[p.name for p in profiles], limited=limited) or 0)
    assert cli.main(["--limited", "Mainframe A"]) == 0
    assert seen == {"names": ["Mainframe A"], "limited": True}
