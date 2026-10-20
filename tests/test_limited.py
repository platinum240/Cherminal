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


def context_menu_items(term, monkeypatch):
    seen = []
    monkeypatch.setattr(QtWidgets.QMenu, "exec",
                        lambda menu, *a: seen.extend(x.text() for x in menu.actions() if x.text()))
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent
    term.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1)))
    return seen


def upload_session(tmp_path):
    from cherminal.session import Session
    return Session(SessionProfile(name="Box", transport="ssh", host="h", file_transfer=True),
                   ProfileStore(tmp_path, site_roots=[]))


def test_limited_has_no_file_chooser(app, tmp_path, monkeypatch):
    from cherminal.gui.terminal import TerminalWidget
    assert "Upload files…" in context_menu_items(TerminalWidget(upload_session(tmp_path)),
                                                 monkeypatch)
    term = TerminalWidget(upload_session(tmp_path), limited=True)
    assert "Upload files…" not in context_menu_items(term, monkeypatch)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames",
                        lambda *a, **k: pytest.fail("file chooser opened in limited mode"))
    term.choose_upload()


def test_policy_turns_off_upload(app, tmp_path):
    from cherminal import policy
    from cherminal.gui.terminal import TerminalWidget
    policy.set_current(policy.Policy(file_upload=False))
    term = TerminalWidget(upload_session(tmp_path))
    assert not term.transfer_enabled and not term.acceptDrops()


@pytest.mark.parametrize("limited, rules, allowed", [
    (False, {}, True),
    (True, {}, False),
    (False, {"print_to_file": False}, False),
])
def test_print_to_file_allowed(app, tmp_path, monkeypatch, limited, rules, allowed):
    from cherminal import policy
    from cherminal.gui import printing
    from cherminal.gui.terminal import TerminalWidget
    policy.set_current(policy.Policy(**rules))
    seen = {}
    monkeypatch.setattr(printing, "print_screen",
                        lambda term, parent, allow_file: seen.update(allow=allow_file))
    TerminalWidget(upload_session(tmp_path), limited=limited).print_screen()
    assert seen == {"allow": allowed}


def test_print_dialog_hides_pdf(app, tmp_path, monkeypatch):
    from PyQt6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog
    from cherminal.gui import printing
    from cherminal.gui.terminal import TerminalWidget
    options = []

    def fake_exec(dlg):
        options.append(dlg.testOption(QAbstractPrintDialog.PrintDialogOption.PrintToFile))
        return 0
    monkeypatch.setattr(QPrintDialog, "exec", fake_exec)
    monkeypatch.setattr(printing, "printer_names", lambda: ["office"])
    term = TerminalWidget(upload_session(tmp_path))
    assert not printing.print_screen(term, None, allow_file=False)
    assert not printing.print_screen(term, None, allow_file=True)
    assert options == [False, True]


def test_no_printer_and_no_pdf_says_so(app, tmp_path, monkeypatch):
    from cherminal.gui import printing
    from cherminal.gui.terminal import TerminalWidget
    warned = []
    monkeypatch.setattr(printing, "printer_names", lambda: [])
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    term = TerminalWidget(upload_session(tmp_path))
    assert not printing.print_screen(term, None, allow_file=False)
    assert warned == ["No printer is set up on this computer."]


def test_policy_hides_local_shell_and_transports(app, tmp_path):
    from cherminal import policy
    from cherminal.gui.app import MainWindow
    from cherminal.gui.dialogs import SessionEditor, SessionManager
    policy.set_current(policy.Policy(allowed_transports=("telnet", "ssh"),
                                     require_tls_verify=True))
    store = ProfileStore(tmp_path, site_roots=[])
    assert "Local shell" not in menu_items(MainWindow(store), "File")
    store.save(SessionProfile(name="Mainframe A", transport="telnet", host="mf"))
    store.save(SessionProfile(name="Modem", transport="serial"))
    names = [i.data(0x0100).name for i in
             (lambda d: [d.list.item(n) for n in range(d.list.count())])(SessionManager(store))]
    assert names == ["Mainframe A"]
    ed = SessionEditor(SessionProfile(name="x", transport="telnet", host="mf", tls=True,
                                      tls_verify=False), store)
    assert [ed.transport.itemText(i) for i in range(ed.transport.count())] == ["ssh", "telnet"]
    assert ed.tls_verify.isChecked() and not ed.tls_verify.isEnabled()
    assert ed.tls.isEnabled()
