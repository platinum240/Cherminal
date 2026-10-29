"""Main window: tabbed sessions, menus and the function-key (macro) bar."""

from __future__ import annotations

import signal
import sys

from PyQt6.QtCore import QLoggingCategory, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QApplication, QFontDialog, QLabel, QMainWindow, QMessageBox,
                             QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import __version__, policy, system
from ..config import ProfileStore, SessionProfile
from ..desktop import APP_ID, entry_installed
from ..keymap import Binding
from ..session import Session
from .dialogs import SessionColoursDialog, SessionEditor, SessionManager
from .icons import app_icon, logo
from .keybar import KeyBar
from .search import SearchBar
from .terminal import TerminalWidget


# Ctrl+Shift shortcuts stay out of the way of host control keys. On macOS
# Qt reads Ctrl in a shortcut as Command, which never reaches the host, so
# the menus use the usual Mac keys there (Cmd+T, Cmd+W, Cmd+C...).
MAC_SHORTCUTS = {"Ctrl+Shift+O": "Ctrl+O", "Ctrl+Shift+N": "Ctrl+N", "Ctrl+Shift+T": "Ctrl+T",
                 "Ctrl+Shift+W": "Ctrl+W", "Ctrl+Shift+Q": "Ctrl+Q", "Ctrl+Shift+F": "Ctrl+F",
                 "Ctrl+Shift+P": "Ctrl+P", "mac:copy": "Ctrl+C", "mac:paste": "Ctrl+V"}


def menu_shortcut(key: str, mac: bool | None = None) -> str:
    """A menu shortcut for this platform; ``mac:`` ones exist only on macOS."""
    if system.IS_MAC if mac is None else mac:
        return MAC_SHORTCUTS.get(key, key)
    return "" if key.startswith("mac:") else key


class MainWindow(QMainWindow):
    def __init__(self, store: ProfileStore, limited: bool = False):
        super().__init__()
        self.store = store
        # Limited: users can only use the sessions they are given; no editing,
        # new connections or local shell.
        self.limited = limited
        self.setWindowTitle(f"Cherminal {__version__}")
        self.tabs = QTabWidget(tabsClosable=True, movable=True, documentMode=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.search = SearchBar()
        self.keybar = KeyBar()
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.keybar)
        lay.addWidget(self.search)
        self.setCentralWidget(central)
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
        if shortcut and (key := menu_shortcut(shortcut)):
            act.setShortcut(QKeySequence(key))
        menu.addAction(act)
        return act

    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        if not self.limited:
            self._action(f, "&Sessions…", self.open_manager, "Ctrl+Shift+O")
            self._action(f, "&Quick connect…", self.quick_connect, "Ctrl+Shift+N")
            if policy.current().local_shell:
                self._action(f, "&Local shell", lambda: self.open_session(
                    SessionProfile(name="Local shell", transport="local", emulation="xterm")),
                    "Ctrl+Shift+T")
            f.addSeparator()
            self._action(f, "&Edit this session…", self.edit_current)
        self._action(f, "&Close tab", lambda: self.close_tab(self.tabs.currentIndex()),
                     "Ctrl+Shift+W")
        self._action(f, "E&xit", self.close, "Ctrl+Shift+Q")
        e = mb.addMenu("&Edit")
        self._action(e, "&Copy", lambda: self._term() and self._term().copy(), "mac:copy")
        self._action(e, "&Paste", lambda: self._term() and self._term().paste(), "mac:paste")
        e.addSeparator()
        self._action(e, "&Search…", self.open_search, "Ctrl+Shift+F")
        v = mb.addMenu("&View")
        self._action(v, "&Font…", self.choose_font)
        self._action(v, "&Colours for this session…", self.session_colours)
        self.scale_action = self._action(v, "&Scale text to window", self.toggle_scale)
        self.scale_action.setCheckable(True)
        self._action(v, "Show &function-key bar",
                     lambda: self.fkey_bar.setVisible(not self.fkey_bar.isVisible()))
        # Modern view for IBM 3270/5250 tabs: in the View menu and beside the tabs.
        self.modern_action = self._action(v, "&Modern view", self.toggle_modern, "Ctrl+Shift+M")
        self.modern_action.setCheckable(True)
        self.modern_button = QToolButton(text="Modern view", autoRaise=True)
        self.modern_button.setDefaultAction(self.modern_action)
        self.modern_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.tabs.setCornerWidget(self.modern_button, Qt.Corner.TopRightCorner)
        self._show_modern_switch(None)
        s = mb.addMenu("&Session")
        self._action(s, "&Reconnect", self.reconnect)
        self._action(s, "&Disconnect", lambda: self._term() and self._term().user_disconnect())
        self._action(s, "Send &Break", lambda: self._run("break"))
        self._action(s, "&Print screen…", lambda: self._term() and self._term().print_screen(),
                     "Ctrl+Shift+P")
        self._action(s, "&Reset terminal", lambda: self._run("reset"))
        s.addSeparator()
        self.transfer_action = self._action(s, "&Transfer file…", self.transfer_file)
        self.transfer_action.setVisible(False)          # IBM 3270 display sessions only
        h = mb.addMenu("&Help")
        self._action(h, "&About Cherminal", self.about)

    def transfer_file(self) -> None:
        """IND$FILE send or receive for the current 3270 session."""
        term = self._term()
        if not term or not term.session.can_transfer:
            return
        rules = policy.current()
        if not (rules.file_transfer(True, self.limited)
                or rules.file_transfer(False, self.limited)):
            QMessageBox.information(self, "Transfer file",
                                    "File transfer is not allowed on this computer.")
            return
        from .transfer import TransferDialog
        TransferDialog(term, limited=self.limited, parent=self).exec()
        term.setFocus()

    def about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("About Cherminal")
        dark = self.palette().window().color().lightness() < 128
        box.setIconPixmap(logo(dark))
        box.setText(f"Cherminal {__version__}")
        box.setInformativeText("Terminal emulation for host connections on "
                               f"{'macOS' if system.IS_MAC else 'Linux'}.")
        box.exec()

    # ------------------------------------------------------------ sessions

    def _term(self) -> TerminalWidget | None:
        return self.tabs.currentWidget()

    def _run(self, action: str) -> None:
        term = self._term()
        if term:
            term.session.run_binding(Binding("action", action))
            term.update()

    def open_session(self, profile: SessionProfile,
                     colours: dict | None = None) -> TerminalWidget | None:
        try:
            session = Session(profile, self.store)
        except ValueError as e:
            QMessageBox.warning(self, "Session", f"Cannot open {profile.name}: {e}")
            return None
        term = TerminalWidget(session, limited=self.limited)
        if colours:
            term.set_colour_override(colours)
        term.find_requested.connect(self.open_search)
        term.colours_requested.connect(self.session_colours)
        term.message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        idx = self.tabs.addTab(term, profile.name)
        term.title_changed.connect(lambda t, w=term: self._set_tab_title(w, t))
        term.status_changed.connect(lambda text, w=term: self._set_status(w, text))
        self.tabs.setCurrentIndex(idx)
        if self.tabs.count() == 1:
            self.resize(term.sizeHint().width() + 20, term.sizeHint().height() + 100)
        term.setFocus()
        term.connect_session()
        return term

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
        self.search.set_terminal(term)
        self.keybar.set_terminal(term)
        self._show_modern_switch(term)
        self.transfer_action.setVisible(bool(term and term.session.can_transfer))
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
        term.shutdown()
        self.tabs.removeTab(idx)
        term.deleteLater()

    def open_manager(self) -> None:
        dlg = SessionManager(self.store, self, limited=self.limited)
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
            profile, colours, modern = term.session.profile, term.colour_override, term.modern
            self.close_tab(self.tabs.currentIndex())
            new = self.open_session(profile, colours)
            if new:
                new.set_modern(modern)
                self._show_modern_switch(new)
                self.keybar.refresh()

    def open_search(self) -> None:
        if self._term():
            self.search.set_terminal(self._term())
            self.search.open()

    def session_colours(self) -> None:
        """One-off colours for the current tab; the saved session is untouched."""
        term = self._term()
        if not term:
            return
        dlg = SessionColoursDialog(term.session.profile, term.colour_override, self)
        if dlg.exec():
            term.set_colour_override(dlg.override())
        term.setFocus()

    def _show_modern_switch(self, term) -> None:
        """The Modern view switch is there for IBM 3270/5250 display tabs,
        unless the site policy turns Modern view off."""
        usable = bool(term and term.can_be_modern) and policy.current().modern_view != "off"
        self.modern_action.setVisible(usable)
        self.modern_button.setVisible(usable)
        self.modern_action.setChecked(bool(term and term.modern))

    def toggle_modern(self) -> None:
        term = self._term()
        if term and term.can_be_modern and policy.current().modern_view != "off":
            term.set_modern(self.modern_action.isChecked())
            self.keybar.refresh()
            term.setFocus()

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
            self.tabs.widget(i).shutdown()

    def closeEvent(self, event) -> None:
        self.disconnect_all()
        super().closeEvent(event)


def run(profiles: list[SessionProfile], store: ProfileStore, show_manager: bool,
        limited: bool = False) -> int:
    QApplication.setApplicationName("Cherminal")
    # The desktop file name ties windows to cherminal.desktop (menu entry and
    # taskbar icon). Qt registers it with the desktop portal at start-up, so
    # it is set before the QApplication exists, and only when that file is
    # installed: otherwise the portal answers "App info not found".
    if entry_installed():
        QApplication.setDesktopFileName(APP_ID)
    else:
        # Without the file the portal can only refuse (Qt may still register
        # a name it derives from the program); that is harmless, so don't
        # print it on every start. `cherminal --install-desktop` adds the file.
        QLoggingCategory.setFilterRules("qt.qpa.services.warning=false")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    win = MainWindow(store, limited=limited)
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
