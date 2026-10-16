"""Main window: tabbed sessions, menus and the function-key (macro) bar."""

from __future__ import annotations

import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QApplication, QFontDialog, QLabel, QMainWindow, QMessageBox,
                             QTabWidget, QToolBar)

from .. import __version__
from ..config import ProfileStore, SessionProfile
from ..keymap import Binding
from ..session import Session
from .dialogs import SessionEditor, SessionManager
from .terminal import TerminalWidget


class MainWindow(QMainWindow):
    def __init__(self, store: ProfileStore):
        super().__init__()
        self.store = store
        self.setWindowTitle("Cherminal")
        self.tabs = QTabWidget(tabsClosable=True, movable=True, documentMode=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.fkey_bar = QToolBar("Function keys")
        self.fkey_bar.setObjectName("fkeys")
        self.addToolBar(self.fkey_bar)
        self._build_menus()

    # -------------------------------------------------------------- menus

    def _action(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            # Ctrl+Shift shortcuts stay out of the way of host control keys.
            act.setShortcut(QKeySequence(shortcut))
        menu.addAction(act)
        return act

    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._action(f, "&Sessions…", self.open_manager, "Ctrl+Shift+O")
        self._action(f, "&Quick connect…", self.quick_connect, "Ctrl+Shift+N")
        self._action(f, "&Local shell", lambda: self.open_session(
            SessionProfile(name="Local shell", transport="local", emulation="xterm")),
            "Ctrl+Shift+T")
        f.addSeparator()
        self._action(f, "&Edit this session…", self.edit_current)
        self._action(f, "&Close tab", lambda: self.close_tab(self.tabs.currentIndex()),
                     "Ctrl+Shift+W")
        self._action(f, "E&xit", self.close, "Ctrl+Shift+Q")
        e = mb.addMenu("&Edit")
        self._action(e, "&Copy", lambda: self._term() and self._term().copy())
        self._action(e, "&Paste", lambda: self._term() and self._term().paste())
        v = mb.addMenu("&View")
        self._action(v, "&Font…", self.choose_font)
        self.scale_action = self._action(v, "&Scale text to window", self.toggle_scale)
        self.scale_action.setCheckable(True)
        self._action(v, "Show &function-key bar",
                     lambda: self.fkey_bar.setVisible(not self.fkey_bar.isVisible()))
        s = mb.addMenu("&Session")
        self._action(s, "&Reconnect", self.reconnect)
        self._action(s, "&Disconnect", lambda: self._term() and self._term().session.disconnect())
        self._action(s, "Send &Break", lambda: self._run("break"))
        self._action(s, "&Reset terminal", lambda: self._run("reset"))
        h = mb.addMenu("&Help")
        self._action(h, "&About Cherminal", lambda: QMessageBox.about(
            self, "About Cherminal",
            f"Cherminal {__version__}\nTerminal emulation for host connections on Linux."))

    # ------------------------------------------------------------ sessions

    def _term(self) -> TerminalWidget | None:
        return self.tabs.currentWidget()

    def _run(self, action: str) -> None:
        term = self._term()
        if term:
            term.session.run_binding(Binding("action", action))
            term.update()

    def open_session(self, profile: SessionProfile) -> None:
        try:
            session = Session(profile, self.store)
        except ValueError as e:
            QMessageBox.warning(self, "Session", f"Cannot open {profile.name}: {e}")
            return
        term = TerminalWidget(session)
        idx = self.tabs.addTab(term, profile.name)
        term.title_changed.connect(lambda t, w=term: self._set_tab_title(w, t))
        term.status_changed.connect(lambda text, w=term: self._set_status(w, text))
        self.tabs.setCurrentIndex(idx)
        if self.tabs.count() == 1:
            self.resize(term.sizeHint().width() + 20, term.sizeHint().height() + 100)
        term.setFocus()
        term.connect_session()

    def _set_tab_title(self, term, title: str) -> None:
        idx = self.tabs.indexOf(term)
        if idx >= 0:
            name = term.session.profile.name
            self.tabs.setTabText(idx, f"{name}: {title}" if title else name)

    def _set_status(self, term, text: str) -> None:
        if term is self._term():
            self.status.setText(text)

    def _tab_changed(self, _idx: int) -> None:
        term = self._term()
        self.fkey_bar.clear()
        if not term:
            self.status.setText("")
            return
        self.status.setText(term.status_text())
        self.scale_action.setChecked(term.resize_mode == "scale")
        for name in term.session.profile.macros:
            act = self.fkey_bar.addAction(name)
            act.triggered.connect(lambda _=False, n=name, t=term: (t.session.run_macro(n),
                                                                   t.setFocus()))
        self.fkey_bar.setVisible(bool(term.session.profile.macros))
        term.setFocus()

    def close_tab(self, idx: int) -> None:
        term = self.tabs.widget(idx)
        if term is None:
            return
        term.session.disconnect()
        self.tabs.removeTab(idx)
        term.deleteLater()

    def open_manager(self) -> None:
        dlg = SessionManager(self.store, self)
        if dlg.exec() and dlg.chosen:
            self.open_session(dlg.chosen)

    def quick_connect(self) -> None:
        dlg = SessionEditor(SessionProfile(name="Quick connect"), self.store,
                            connect_only=True, parent=self)
        if dlg.exec() and dlg.result_profile:
            self.open_session(dlg.result_profile)

    def edit_current(self) -> None:
        term = self._term()
        if not term:
            return
        dlg = SessionEditor(term.session.profile, self.store, parent=self)
        if dlg.exec() and dlg.result_profile:
            if QMessageBox.question(self, "Session saved",
                                    "Reconnect now to apply the changes?") \
                    == QMessageBox.StandardButton.Yes:
                idx = self.tabs.currentIndex()
                self.close_tab(idx)
                self.open_session(dlg.result_profile)

    def reconnect(self) -> None:
        term = self._term()
        if term:
            profile = term.session.profile
            self.close_tab(self.tabs.currentIndex())
            self.open_session(profile)

    def choose_font(self) -> None:
        term = self._term()
        if not term:
            return
        font, ok = QFontDialog.getFont(term.term_font, self, "Terminal font",
                                       QFontDialog.FontDialogOption.MonospacedFonts)
        if ok:
            term.set_base_font(font.family(), font.pointSizeF())

    def toggle_scale(self) -> None:
        term = self._term()
        if term:
            term.set_resize_mode("scale" if self.scale_action.isChecked() else "grow")
            self.status.setText(term.status_text())

    def disconnect_all(self) -> None:
        for i in range(self.tabs.count()):
            self.tabs.widget(i).session.disconnect()

    def closeEvent(self, event) -> None:
        self.disconnect_all()
        super().closeEvent(event)


def run(profiles: list[SessionProfile], store: ProfileStore, show_manager: bool) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Cherminal")
    win = MainWindow(store)
    # Every way out (last window closed, Ctrl+C, kill, logout) closes the
    # connections cleanly rather than leaving it to process teardown.
    app.aboutToQuit.connect(win.disconnect_all)

    def on_signal(signum, frame):
        win.disconnect_all()
        app.quit()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    # Python only runs signal handlers when it gets control back from Qt.
    tick = QTimer(interval=250)
    tick.timeout.connect(lambda: None)
    tick.start()
    win.resize(820, 520)
    win.show()
    for p in profiles:
        win.open_session(p)
    if show_manager:
        win.open_manager()
    return app.exec()
