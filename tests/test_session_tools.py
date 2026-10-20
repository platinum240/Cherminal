import os
import re
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PyQt6.QtGui import QDragEnterEvent  # noqa: E402

from cherminal.config import ProfileStore, SessionProfile  # noqa: E402
from cherminal.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def terminal(tmp_path, **kw):
    from cherminal.gui.terminal import TerminalWidget
    store = ProfileStore(tmp_path, site_roots=[])
    return TerminalWidget(Session(SessionProfile(**kw), store))


def test_search_up_down_and_wrap(app, tmp_path):
    term = terminal(tmp_path)
    lines = [f"line {i} {'ERROR disk' if i in (5, 40) else 'ok'}" for i in range(60)]
    term.session.feed("\r\n".join(lines).encode())
    assert term.find("error")                                 # up from the bottom
    assert term.selected_text() == "ERROR"
    hit40 = term.match
    assert term.find("error")                                 # further up
    assert term.match[0] < hit40[0] and term.scroll_offset > 0
    assert term.find("error")                                 # wraps to the bottom one
    assert term.match == hit40
    assert term.find("error", backwards=False)                # down wraps to the top one
    assert term.match[0] < hit40[0]
    assert not term.find("error", case=True)
    assert term.find("ERROR", case=True)


def test_search_whole_word_regex_and_hidden_text(app, tmp_path):
    term = terminal(tmp_path)
    term.session.feed(b"cat catalog\r\nuser 42 \x1b[8msecret\x1b[0m\r\n")
    term.clear_match()
    assert term.find("cat", whole=True)
    assert term.match[1:] == (0, 3)
    assert not term.find("talo", whole=True)
    term.clear_match()
    assert term.find(r"user \d+", regex=True)
    assert term.selected_text() == "user 42"
    assert not term.find("secret")                            # invisible text is not searched
    with pytest.raises(re.error):
        term.find("(", regex=True)
    assert not term.find("(")                                 # literal (no error) unless regex


def test_search_bar(app, tmp_path):
    from cherminal.gui.search import SearchBar
    term = terminal(tmp_path)
    term.session.feed(b"alpha\r\nbeta\r\nalpha\r\n")
    bar = SearchBar()
    bar.set_terminal(term)
    bar.open()
    bar.field.setText("alpha")                                # searches as you type
    assert term.match[0] == 2
    bar.find(backwards=True)
    assert term.match[0] == 0
    bar.regex.setChecked(True)
    bar.field.setText("[")
    assert bar.result.text().startswith("Invalid expression")
    bar.field.setText("zzz")
    assert bar.result.text() == "Not found"
    bar.close_bar()
    assert term.match is None and not bar.isVisible()


def test_session_colours_are_one_off(app, tmp_path):
    from cherminal.gui.dialogs import SessionColoursDialog
    term = terminal(tmp_path, color_scheme="classic")
    saved = term.session.profile
    dlg = SessionColoursDialog(saved, None)
    assert dlg.override() is None                             # unchanged: no override
    dlg.panel.scheme.setCurrentText("yellow-on-black")
    dlg.panel.min_contrast.setCurrentIndex(dlg.panel.min_contrast.findData(7.0))
    term.set_colour_override(dlg.override())
    assert term.colors.bg == (0, 0, 0) and term.colors.min_contrast == 7
    assert term.session.profile.color_scheme == "classic"     # saved session untouched
    again = SessionColoursDialog(saved, term.colour_override)
    assert again.panel.scheme.currentText() == "yellow-on-black"
    again.panel.load(saved)                                   # "Use the session's colours"
    term.set_colour_override(again.override())
    assert term.colour_override is None and term.colors.min_contrast != 7


def test_reconnect_keeps_one_off_colours(app, tmp_path):
    from cherminal.gui.app import MainWindow
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]))
    term = win.open_session(SessionProfile(name="x", transport="telnet", host="127.0.0.1",
                                           port=1))
    term.set_colour_override({"color_scheme": "high-contrast"})
    win.reconnect()
    assert win._term().colour_override == {"color_scheme": "high-contrast"}
    menus = {a.text().replace("&", ""): [b.text().replace("&", "") for b in a.menu().actions()]
             for a in win.menuBar().actions()}
    assert "Search…" in menus["Edit"] and "Colours for this session…" in menus["View"]
    win.disconnect_all()


def drag_accepted(term, path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    ev = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    ev.ignore()
    term.dragEnterEvent(ev)
    return ev.isAccepted()


def test_drop_only_when_enabled_for_ssh(app, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    off = terminal(tmp_path, transport="ssh", host="h")
    on = terminal(tmp_path, transport="ssh", host="h", file_transfer=True)
    telnet = terminal(tmp_path, transport="telnet", host="h", file_transfer=True)
    assert not off.acceptDrops() and not drag_accepted(off, f)
    assert on.acceptDrops() and drag_accepted(on, f)
    assert not telnet.acceptDrops() and not drag_accepted(telnet, f)


def test_upload_runs_through_transport(app, tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("x")
    term = terminal(tmp_path, transport="ssh", host="h", file_transfer=True, upload_dir="~/in")
    calls = []

    class FakeSSH:
        def upload(self, paths, remote_dir, progress, replace):
            calls.append((paths, remote_dir))
            progress("a.txt", 1, 1)
            return ["/home/u/in/a.txt"]

    term.session.transport = FakeSSH()
    term.session.connected = True
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        lambda *a: QtWidgets.QMessageBox.StandardButton.Yes)
    messages = []
    term.message.connect(messages.append)
    term.upload_files([str(f), str(tmp_path)])
    for _ in range(200):
        app.processEvents()
        if messages:
            break
        time.sleep(0.01)
    assert calls == [([str(f)], "~/in")]                      # the folder was skipped
    assert messages == ["Uploaded 1 file to /home/u/in"]


def test_editor_file_transfer_tab(app, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    store = ProfileStore(tmp_path, site_roots=[])
    ed = SessionEditor(SessionProfile(name="s", host="h", file_transfer=True,
                                      upload_dir="/tmp/in"), store)
    assert ed.file_transfer.isChecked() and ed.upload_dir.text() == "/tmp/in"
    p = ed._build()
    assert p.file_transfer and p.upload_dir == "/tmp/in"
    ed.transport.setCurrentText("telnet")
    assert ed.transfer_box.isHidden() and not ed.transfer_ssh_only.isHidden()
    new = SessionEditor(SessionProfile(name="t", host="h"), store)
    assert not new.file_transfer.isChecked() and not new.upload_dir.isEnabled()


def test_context_menu_has_copy_paste_search(app, tmp_path, monkeypatch):
    from PyQt6.QtGui import QContextMenuEvent
    seen = []
    monkeypatch.setattr(QtWidgets.QMenu, "exec",
                        lambda self, *a: seen.extend(x.text() for x in self.actions() if x.text()))
    for kw, upload in (({}, False), ({"transport": "ssh", "host": "h", "file_transfer": True}, True)):
        seen.clear()
        term = terminal(tmp_path, **kw)
        term.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1)))
        assert seen[:4] == ["Copy", "Paste", "Search…", "Colours for this session…"]
        assert ("Upload files…" in seen) == upload
