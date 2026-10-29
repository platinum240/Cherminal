"""The terminal view: paints a Session's screen and feeds it keystrokes."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import replace

from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QClipboard, QColor, QCursor, QFont, QFontMetrics, QFontMetricsF,
                         QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent)
from PyQt6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QLineEdit, QMenu,
                             QMessageBox, QProgressDialog, QWidget)

from .. import policy, system
from ..emulation.hotspots import ScreenKey, hotspot_at, screen_keys
from ..keymap import Binding
from ..screen import Attr
from ..session import Session
from .colors import ensure_contrast, resolve
from .keys import key_name, option_is_alt

IDLE_CHECK_MS = 5000            # how often the idle timeout is checked
IDLE_WARNING = 60               # seconds of warning before an idle disconnect
RETRY_DELAYS = (2, 5, 10, 20, 30, 60)   # seconds between reconnect attempts
MAX_RETRIES = 10
MODERN_LINE_SPACING = 1.3       # Modern view: rows a little apart, so fields have room


class _Bridge(QObject):
    """Carries transport callbacks from the reader thread to the UI thread."""
    updated = pyqtSignal()
    closed = pyqtSignal(str)
    prompt = pyqtSignal(str, object)
    upload_progress = pyqtSignal(str, int, int)
    upload_done = pyqtSignal(str, object)       # error ("" = ok), remote paths
    print_data = pyqtSignal(bytes)              # a host passthrough print job
    print_job = pyqtSignal(str)                 # a 3287 printer session's decoded job


class TerminalWidget(QWidget):
    title_changed = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    message = pyqtSignal(str)                   # a passing note for the status bar
    find_requested = pyqtSignal()
    screen_changed = pyqtSignal()               # Modern view: the key bar may need updating
    colours_requested = pyqtSignal()

    def __init__(self, session: Session, parent=None, limited: bool = False):
        super().__init__(parent)
        self.session = session
        # Limited: no file choosers or saving to files, which would let users
        # browse and change the local disk.
        self.limited = limited
        self.colour_override: dict | None = None    # one-off colours, not saved
        self.colors = resolve(session.profile)
        self._contrast_cache: dict = {}
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.resize_mode = session.profile.resize_mode
        self.offset_x = self.offset_y = 0     # centres the grid in scale mode
        # Modern view (IBM 3270/5250 displays): boxed input fields, click to
        # move the cursor, and a key bar under the screen (see app.KeyBar).
        emu = session.emulation
        self.can_be_modern = emu.block_mode and not emu.printer
        self.modern = self.can_be_modern and policy.current().modern(session.profile.view)
        self.set_base_font(session.profile.font_family, session.profile.font_size)

        self.scroll_offset = 0                 # lines scrolled back into history
        self._alt_key = None                   # macOS: Option+key handled early (see event)
        self.sel_start: tuple[int, int] | None = None   # (absolute line, col)
        self.sel_end: tuple[int, int] | None = None
        self._last_title = ""
        self.match: tuple[int, int, int] | None = None   # (line, start col, end col)
        self.transfer_enabled = (session.profile.file_transfer
                                 and session.profile.transport == "ssh"
                                 and policy.current().file_upload)
        self.setAcceptDrops(self.transfer_enabled)
        # Block-mode screens: PF3=Exit and the like can be clicked.
        self.hotspots = (session.emulation.block_mode and session.profile.hotspots
                         and not session.emulation.printer)
        self.setMouseTracking(self.hotspots)
        self._hot: tuple[int, int, int, str] | None = None     # row, start, end, action
        self._hot_press: tuple[int, int, int, str] | None = None
        self._uploading = False
        self._cancel_upload = False

        self.bridge = _Bridge()
        self.bridge.updated.connect(self._on_update)
        self.bridge.closed.connect(self._on_closed)
        self.bridge.prompt.connect(self._on_prompt, Qt.ConnectionType.BlockingQueuedConnection)
        self.bridge.upload_progress.connect(self._on_upload_progress)
        self.bridge.upload_done.connect(self._on_upload_done)
        self.bridge.print_data.connect(self._on_print_data)
        session.emulation.on_print_data = self.bridge.print_data.emit
        if session.emulation.printer:
            # 3287 printer session: jobs print as they end, without asking; a
            # timer ends a job the host leaves open (see IBM3287.tick).
            self.bridge.print_job.connect(self._on_print_job, Qt.ConnectionType.QueuedConnection)
            session.emulation.on_job = self.bridge.print_job.emit
            self._eoj = QTimer(self, interval=1000)
            self._eoj.timeout.connect(self._printer_tick)
            self._eoj.start()
        # Coalesce bursts of host output into at most ~60 repaints a second.
        self._repaint = QTimer(self, singleShot=True, interval=16)
        self._repaint.timeout.connect(self.update)
        session.on_action = self.do_action
        session.emulation.on_bell = QApplication.beep
        # Connection upkeep: the idle timeout and reconnecting after a drop.
        self.ended = False              # the connection is over; Enter reconnects
        self.retries = 0
        self._idle_warned = False
        self._idle_timer = QTimer(self, interval=IDLE_CHECK_MS)
        self._idle_timer.timeout.connect(self.check_idle)
        self._idle_timer.start()
        self._retry_timer = QTimer(self, singleShot=True)
        self._retry_timer.timeout.connect(self.reconnect_now)

    # ------------------------------------------------------------ geometry

    def set_base_font(self, family: str, size: float) -> None:
        """The font chosen by the user; scale mode resizes from it to fit."""
        self.base_family, self.base_size = family, size
        self.set_font(family, size)
        if self.resize_mode == "scale" and self.isVisible():
            self._fit_font()

    def set_resize_mode(self, mode: str) -> None:
        self.resize_mode = mode
        if mode == "grow":
            self.set_font(self.base_family, self.base_size)
            self.offset_x = self.offset_y = 0
        self._apply_resize()

    def set_font(self, family: str, size: float) -> None:
        font = QFont(system.font_family(family))
        font.setPointSizeF(size)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setFixedPitch(True)
        self.term_font = font
        self.bold_font = QFont(font)
        self.bold_font.setBold(True)
        fm = QFontMetrics(font)
        self.cw = max(1, fm.horizontalAdvance("M"))
        self.ch = max(1, round(fm.height() * self._line_spacing()))
        self.ascent = fm.ascent() + (self.ch - fm.height()) // 2
        self.updateGeometry()
        self.update()

    def _line_spacing(self) -> float:
        return MODERN_LINE_SPACING if getattr(self, "modern", False) else 1.0

    def set_modern(self, on: bool) -> None:
        """Switch this tab between Classic and Modern view (the session file is untouched)."""
        on = on and self.can_be_modern
        if on == self.modern:
            return
        self.modern = on
        self.set_font(self.base_family, self.base_size)
        self._apply_resize()
        self.screen_changed.emit()

    def screen_keys(self) -> list[ScreenKey]:
        """The keys the current screen lists (F3=Exit...), for the key bar."""
        with self.session.lock:
            lines = [self._line_text(line) for line in self.session.screen.lines]
        return screen_keys(lines)

    def key_hint(self, action: str) -> str:
        """The keyboard key for ``action``, e.g. "F3", shown beside its button."""
        return self.session.keymap.key_for(action)

    def press_key(self, action: str) -> None:
        """A key bar button: press that host key as if it were typed."""
        self.session.touch()
        self.scroll_offset = 0
        self.clear_selection()
        if self.ended and action == "enter":
            self.reconnect_now()
        else:
            self.session.run_binding(Binding("action", action))
            self._on_update()
        self.setFocus()

    def sizeHint(self):
        return QSize(self.cw * self.session.screen.cols, self.ch * self.session.screen.rows)

    def resizeEvent(self, event) -> None:
        self._apply_resize()
        super().resizeEvent(event)

    def _apply_resize(self) -> None:
        if self.resize_mode == "scale" or self.session.emulation.fixed_size:
            self._fit_font()
            return
        cols = max(2, self.width() // self.cw)
        rows = max(2, self.height() // self.ch)
        s = self.session.screen
        if (cols, rows) != (s.cols, s.rows):
            self.session.resize(cols, rows)
            self.status_changed.emit(self.status_text())
        self.update()

    def _fit_font(self) -> None:
        """Scale mode: keep the host's grid and size the font to fill the window."""
        s = self.session.screen
        if self.width() < 10 or self.height() < 10:
            return
        ref = QFont(self.base_family)
        ref.setPointSizeF(100)
        ref.setStyleHint(QFont.StyleHint.TypeWriter)
        fm = QFontMetricsF(ref)
        w100, h100 = fm.horizontalAdvance("M"), fm.height() * self._line_spacing()
        size = 100 * min(self.width() / (s.cols * w100), self.height() / (s.rows * h100))
        size = max(4.0, int(size * 2) / 2)          # half-point steps
        self.set_font(self.base_family, size)
        # Integer cell metrics can round up; step down until the grid fits.
        while size > 4 and (self.cw * s.cols > self.width() or self.ch * s.rows > self.height()):
            size -= 0.5
            self.set_font(self.base_family, size)
        self.offset_x = max(0, (self.width() - self.cw * s.cols) // 2)
        self.offset_y = max(0, (self.height() - self.ch * s.rows) // 2)

    # ---------------------------------------------------------- connection

    def connect_session(self) -> None:
        self.status_changed.emit("Connecting…")
        self.session.connect(
            ask_password=lambda prompt: self._ask("password", prompt),
            ask_login=lambda host, user, error: self._ask("login", error, host=host, user=user),
            confirm_host_key=lambda host, kind, fp, changed: self._ask(
                "hostkey", f"The authenticity of host {host} can't be established.\n"
                           f"{kind} key fingerprint is {fp}.\n\nTrust this host and continue?"),
            on_update=self.bridge.updated.emit,
            on_closed=self.bridge.closed.emit)

    def _ask(self, kind: str, prompt: str, **extra):
        box = {"kind": kind, "result": None, **extra}
        self.bridge.prompt.emit(prompt, box)    # blocks until answered
        return box["result"]

    def _on_prompt(self, prompt: str, box: dict) -> None:
        if box["kind"] == "login":
            from .dialogs import LoginDialog
            dlg = LoginDialog(box["host"], box["user"], prompt, self)
            box["result"] = dlg.credentials() if dlg.exec() else None
        elif box["kind"] == "replace":
            answer = QMessageBox.question(self, "Replace file", prompt)
            box["result"] = answer == QMessageBox.StandardButton.Yes
        elif box["kind"] == "password":
            text, ok = QInputDialog.getText(self, "Password", prompt, QLineEdit.EchoMode.Password)
            box["result"] = text if ok else None
        else:
            answer = QMessageBox.question(self, "Unknown host key", prompt)
            box["result"] = answer == QMessageBox.StandardButton.Yes

    def _on_update(self) -> None:
        if self.session.connected and self.retries:
            self.retries = 0
            self.message.emit("Reconnected")
        log_error = self.session.log_error or (self.session.log and self.session.log.error)
        if log_error and log_error != getattr(self, "_shown_log_error", ""):
            self._shown_log_error = log_error
            self.message.emit(log_error.capitalize())
        s = self.session.screen
        if (s.cols, s.rows) != getattr(self, "_last_grid", (s.cols, s.rows)):
            self._apply_resize()            # the host changed the screen size
        self._last_grid = (s.cols, s.rows)
        if not self._repaint.isActive():
            self._repaint.start()
        if self.hotspots and self.underMouse():
            self._hover(self.mapFromGlobal(QCursor.pos()))      # the screen changed under it
        if self.modern:
            self.screen_changed.emit()
        title = self.session.screen.title
        if title != self._last_title:
            self._last_title = title
            self.title_changed.emit(title)
        self.status_changed.emit(self.status_text())

    def _on_closed(self, reason: str) -> None:
        self.ended = True
        left = self.session.idle_left()
        if left is not None and left <= 0:
            self.idle_disconnect()           # went idle while the link was down
            return
        self.session.notice(reason)
        if (self.session.dropped or self.retries) and self.session.may_reconnect \
                and self.retries < MAX_RETRIES:
            delay = RETRY_DELAYS[min(self.retries, len(RETRY_DELAYS) - 1)]
            self.retries += 1
            self.session.notice(f"Reconnecting in {delay} seconds (try {self.retries} of "
                                f"{MAX_RETRIES}). Press Enter to reconnect now.")
            self.status_changed.emit(f"Connection lost: {reason} · reconnecting in {delay} s")
            self._retry_timer.start(delay * 1000)
        else:
            if self.retries:
                self.session.notice(f"Could not reconnect after {self.retries} tries.")
                self.retries = 0
            self.session.notice("Press Enter to reconnect.")
            self.status_changed.emit(f"Disconnected: {reason}")
        self.update()

    def reconnect_now(self) -> None:
        """Connect again in this tab, keeping the screen and the session's log."""
        self._retry_timer.stop()
        self.ended = False
        self.session.forget_transport()
        if self.session.emulation.block_mode:
            with self.session.lock:
                self.session.emulation.reset()   # the host paints a fresh screen
        self.connect_session()

    def check_idle(self) -> None:
        if not self.session.connected:
            return
        left = self.session.idle_left()
        if left is None:
            return
        if left <= 0:
            self.idle_disconnect()
        elif left <= IDLE_WARNING:
            if not self._idle_warned:
                self._idle_warned = True
                self.message.emit(f"No input for a while: {self.session.profile.name} "
                                  f"disconnects in {int(left)} seconds unless a key is pressed")
        else:
            self._idle_warned = False

    def idle_disconnect(self) -> None:
        """Close the connection and blank the screen and scrollback, so an
        unattended terminal shows nothing."""
        minutes = self.session.idle_limit
        self._retry_timer.stop()
        self.retries = 0
        self.session.disconnect(reason=f"idle for {minutes} minutes")
        with self.session.lock:
            self.session.emulation.reset()
            self.session.screen.wipe()
        self.scroll_offset = 0
        self.clear_selection()
        self.ended = True
        self.session.notice(f"Disconnected after {minutes} minutes without input. "
                            f"Press Enter to reconnect.")
        self.status_changed.emit(f"Disconnected: no input for {minutes} minutes")
        self.message.emit(f"{self.session.profile.name} was disconnected after {minutes} "
                          f"minutes without input")
        self.update()

    def user_disconnect(self) -> None:
        self._retry_timer.stop()
        self.retries = 0
        if self.session.connected:
            self.session.disconnect()
            self.ended = True
            self.session.notice("Disconnected. Press Enter to reconnect.")
            self.status_changed.emit("Disconnected")
            self.update()

    def shutdown(self) -> None:
        """The tab is closing: stop the timers and the connection."""
        self._idle_timer.stop()
        self._retry_timer.stop()
        self.session.disconnect()

    def status_text(self) -> str:
        p = self.session.profile
        s = self.session.screen
        where = {"local": "local shell", "serial": p.serial_device}.get(
            p.transport, f"{p.host}:{p.effective_port}")
        state = "Connected" if self.session.connected else "Not connected"
        text = f"{state} · {p.transport.upper()} {where} · {p.emulation.upper()} · {s.cols}×{s.rows}"
        oia = getattr(self.session.emulation, "status", "")
        return f"{text} · {oia}" if oia else text

    # --------------------------------------------------------------- input

    def focusNextPrevChild(self, next: bool) -> bool:
        return False   # keep Tab for the host

    def event(self, event) -> bool:
        # macOS turns Option+letter into an accented character (or a dead key
        # that waits for the next one) before keyPressEvent sees it. When
        # Option is Alt, take the key at the shortcut stage, which comes first.
        if (system.IS_MAC and event.type() == QEvent.Type.ShortcutOverride
                and option_is_alt(event, self.session.profile.option_key)):
            self._alt_key = (event.key(), event.timestamp())
            self.keyPressEvent(event)
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.type() == QEvent.Type.KeyPress and self._alt_key == (event.key(),
                                                                       event.timestamp()):
            self._alt_key = None
            return                  # already handled as Option+key (see event)
        if self.ended and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.session.touch()
            self.reconnect_now()
            return
        named = key_name(event, self.session.profile.option_key, mac=system.IS_MAC)
        if named is None:
            return
        name, text = named
        self.scroll_offset = 0
        try:
            handled = self.session.key(name, text) if name else (self.session.send_text(text) or True)
        except ValueError:
            handled = bool(text) and (self.session.send_text(text) or True)
        if handled:
            self.clear_selection()
            if self.session.emulation.block_mode:
                self._on_update()           # local edit: repaint and refresh the OIA
        else:
            super().keyPressEvent(event)

    def inputMethodEvent(self, event) -> None:
        if event.commitString():
            self.session.send_text(event.commitString())

    def do_action(self, name: str) -> None:
        if name == "copy":
            self.copy()
        elif name == "paste":
            self.paste()
        elif name == "print-screen":
            self.print_screen()
        elif name == "scroll-up":
            self.scroll_by(self.session.screen.rows // 2)
        elif name == "scroll-down":
            self.scroll_by(-(self.session.screen.rows // 2))

    def paste(self, mode=None) -> None:
        cb = QGuiApplication.clipboard()
        text = cb.text(mode or QClipboard.Mode.Clipboard)
        if text:
            self.session.paste(text)
            if self.session.emulation.block_mode:
                self._on_update()               # a local edit: repaint and refresh the OIA

    def copy(self) -> None:
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    # -------------------------------------------------------------- colours

    def set_colour_override(self, settings: dict | None) -> None:
        """Colours for this window only; None goes back to the session's."""
        self.colour_override = settings
        profile = self.session.profile
        self.colors = resolve(replace(profile, **settings) if settings else profile)
        self._contrast_cache.clear()
        self.update()

    # ---------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        copy = menu.addAction("Copy", self.copy)
        copy.setEnabled(bool(self.selected_text()))
        paste = menu.addAction("Paste", self.paste)
        paste.setEnabled(bool(QGuiApplication.clipboard().text()))
        menu.addSeparator()
        menu.addAction("Search…", self.find_requested.emit)
        menu.addAction("Colours for this session…", self.colours_requested.emit)
        menu.addAction("Print screen…", self.print_screen)
        if self.transfer_enabled and not self.limited:
            menu.addSeparator()
            up = menu.addAction("Upload files…", self.choose_upload)
            up.setEnabled(self.session.connected and not self._uploading)
        menu.exec(event.globalPos())

    # --------------------------------------------------------------- search

    def _line_text(self, line) -> str:
        # Hidden text (passwords) is never matched.
        return "".join(" " if c.attr.invisible else c.char for c in line)

    def clear_match(self) -> None:
        if self.match is not None:
            self.match = None
            self.clear_selection()

    def find(self, pattern: str, *, backwards: bool = True, case: bool = False,
             whole: bool = False, regex: bool = False) -> bool:
        """Select the next match above (backwards) or below the current one.

        The first search starts from the bottom (up) or top (down) of the
        view and wraps around. Raises re.error for a bad expression.
        """
        expr = pattern if regex else re.escape(pattern)
        if whole:
            expr = rf"(?<!\w)(?:{expr})(?!\w)"
        rx = re.compile(expr, 0 if case else re.IGNORECASE)
        with self.session.lock:
            lines = [self._line_text(line) for line in self._all_lines()]
            rows = self.session.screen.rows
        n = len(lines)
        if not pattern or not n:
            return False
        history = n - rows
        first = history - self.scroll_offset
        if self.match:
            l0, c0 = self.match[0], self.match[1]
        elif backwards:
            l0, c0 = min(n - 1, first + rows - 1), 1 << 30
        else:
            l0, c0 = max(0, first), -1
        step = -1 if backwards else 1
        for k in range(n + 1):
            i = (l0 + step * k) % n
            found = [(m.start(), m.end()) for m in rx.finditer(lines[i]) if m.end() > m.start()]
            if k == 0:
                found = [m for m in found if (m[0] < c0 if backwards else m[0] > c0)]
            elif k == n:
                found = [m for m in found if (m[0] >= c0 if backwards else m[0] <= c0)]
            if found:
                start, end = found[-1] if backwards else found[0]
                self._show_match(i, start, end, history, rows)
                return True
        self.clear_match()
        return False

    def _show_match(self, line: int, start: int, end: int, history: int, rows: int) -> None:
        self.match = (line, start, end)
        self.sel_start, self.sel_end = (line, start), (line, end)
        first = history - self.scroll_offset
        if not first <= line < first + rows:
            self.scroll_offset = max(0, min(history, history - (line - rows // 2)))
        self.update()

    # ------------------------------------------------------------- printing

    def print_screen(self) -> None:
        from .printing import print_screen
        allow_file = not self.limited and policy.current().print_to_file
        if print_screen(self, self, allow_file=allow_file):
            self.message.emit("Screen sent to the printer")
        self.setFocus()

    def _printer_tick(self) -> None:
        with self.session.lock:
            self.session.emulation.tick()

    def _on_print_job(self, text: str) -> None:
        from .printing import print_text
        emu = self.session.emulation
        title = f"{self.session.profile.name} {emu.lu_name}".strip()
        result = print_text(text, self.session.profile.printer, title)
        with self.session.lock:
            emu.print_result = result
            emu._render()
        self.message.emit(result)
        self._on_update()

    def _on_print_data(self, data: bytes) -> None:
        from .printing import print_raw
        self.message.emit(print_raw(data, self.session.profile.printer, self))

    # -------------------------------------------------------- file transfer

    @staticmethod
    def _local_files(mime) -> list[str]:
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, event) -> None:
        if self.transfer_enabled and self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self.transfer_enabled and self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = self._local_files(event.mimeData())
        if self.transfer_enabled and paths:
            event.acceptProposedAction()
            self.upload_files(paths)

    def choose_upload(self) -> None:
        if self.limited:
            return                  # a file chooser can browse and change the disk
        paths, _ = QFileDialog.getOpenFileNames(self, "Upload files")
        if paths:
            self.upload_files(paths)

    def upload_files(self, paths: list[str]) -> None:
        p = self.session.profile
        transport = self.session.transport
        if not self.transfer_enabled:
            return
        if self._uploading:
            QMessageBox.information(self, "Upload", "An upload is already running.")
            return
        if not self.session.connected or not hasattr(transport, "upload"):
            QMessageBox.warning(self, "Upload", "Connect to the host first.")
            return
        files = [path for path in paths if os.path.isfile(path)]
        skipped = len(paths) - len(files)
        if not files:
            QMessageBox.warning(self, "Upload", "Only files can be uploaded, not folders.")
            return
        names = "\n".join(os.path.basename(f) for f in files[:10])
        if len(files) > 10:
            names += f"\n… and {len(files) - 10} more"
        where = p.upload_dir or "your home folder"
        text = f"Upload {len(files)} file{'s' * (len(files) != 1)} to {where} on {p.host}?\n\n{names}"
        if skipped:
            text += f"\n\n{skipped} folder{'s' * (skipped != 1)} will be skipped."
        if QMessageBox.question(self, "Upload", text) != QMessageBox.StandardButton.Yes:
            return
        self._uploading, self._cancel_upload = True, False
        self.progress = QProgressDialog("Uploading…", "Cancel", 0, 1000, self)
        self.progress.setWindowTitle("Upload")
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(lambda: setattr(self, "_cancel_upload", True))

        def progress(name, done, total):
            self.bridge.upload_progress.emit(name, done, total)
            return not self._cancel_upload

        def work():
            from ..transport.ssh import UploadCancelled
            try:
                written = transport.upload(
                    files, p.upload_dir, progress=progress,
                    replace=lambda path: self._ask(
                        "replace", f"{path} already exists on {p.host}. Replace it?"))
                self.bridge.upload_done.emit("", written)
            except UploadCancelled:
                self.bridge.upload_done.emit("cancelled", [])
            except Exception as e:          # noqa: BLE001 - shown to the user
                self.bridge.upload_done.emit(str(e) or type(e).__name__, [])

        threading.Thread(target=work, daemon=True, name="upload").start()

    def _on_upload_progress(self, name: str, done: int, total: int) -> None:
        if self._uploading and not self._cancel_upload:
            self.progress.setLabelText(f"Uploading {name}…")
            self.progress.setValue(done * 1000 // total if total else 1000)

    def _on_upload_done(self, error: str, written: list) -> None:
        self._uploading = False
        self.progress.reset()
        self.progress.deleteLater()
        if error == "cancelled":
            self.message.emit("Upload cancelled")
        elif error:
            QMessageBox.warning(self, "Upload", f"The upload failed: {error}")
        elif written:
            folder = os.path.dirname(written[0])
            self.message.emit(f"Uploaded {len(written)} file{'s' * (len(written) != 1)} "
                              f"to {folder}")
        else:
            self.message.emit("Nothing uploaded")
        self.setFocus()

    # ----------------------------------------------------------- scrollback

    def _all_lines(self):
        s = self.session.screen
        return (s.scrollback if not s.using_alt_screen else []) + s.lines

    def scroll_by(self, n: int) -> None:
        s = self.session.screen
        limit = 0 if s.using_alt_screen else len(s.scrollback)
        self.scroll_offset = max(0, min(limit, self.scroll_offset + n))
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.scroll_by(event.angleDelta().y() // 40)

    # ------------------------------------------------------------ selection

    def _cell_at(self, pos) -> tuple[int, int]:
        s = self.session.screen
        history = 0 if s.using_alt_screen else len(s.scrollback)
        row = max(0, min(s.rows - 1, (int(pos.y()) - self.offset_y) // self.ch))
        col = max(0, min(s.cols, (int(pos.x()) - self.offset_x) // self.cw))
        return history - self.scroll_offset + row, col

    # ------------------------------------------------------------- hotspots

    def _hotspot(self, pos) -> tuple[int, int, int, str] | None:
        """The clickable key name (PF3=Exit, ENTER, ...) under ``pos``."""
        if not self.hotspots or self.scroll_offset:
            return None
        s = self.session.screen
        x, y = int(pos.x()) - self.offset_x, int(pos.y()) - self.offset_y
        if x < 0 or y < 0:
            return None
        row, col = y // self.ch, x // self.cw
        if row >= s.rows or col >= s.cols:
            return None
        with self.session.lock:
            spot = hotspot_at(self._line_text(s.lines[row]), col)
        return (row, spot.start, spot.end, spot.action) if spot else None

    def _hover(self, pos) -> None:
        hot = self._hotspot(pos)
        if hot != self._hot:
            self._hot = hot
            self.setCursor(Qt.CursorShape.PointingHandCursor if hot
                           else Qt.CursorShape.IBeamCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hot:
            self._hot = None
            self.setCursor(Qt.CursorShape.IBeamCursor)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.session.touch()
        if event.button() == Qt.MouseButton.LeftButton:
            plain = event.modifiers() == Qt.KeyboardModifier.NoModifier
            self._hot_press = self._hotspot(event.position()) if plain else None
            self.match = None
            self.sel_start = self.sel_end = self._cell_at(event.position())
            self.update()
        elif (event.button() == Qt.MouseButton.MiddleButton
              and QGuiApplication.clipboard().supportsSelection()):
            self.paste(QClipboard.Mode.Selection)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.sel_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.sel_end = self._cell_at(event.position())
            self.update()
        elif self.hotspots and not event.buttons():
            self._hover(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        press, self._hot_press = self._hot_press, None
        if (press and event.button() == Qt.MouseButton.LeftButton and not self._sel_range()
                and self._hotspot(event.position()) == press):
            # A click (not a drag to select) on a key name presses that key.
            self.clear_selection()
            self.session.run_binding(Binding("action", press[3]))
            self._on_update()
            return
        if (self.modern and event.button() == Qt.MouseButton.LeftButton
                and not self._sel_range() and self.scroll_offset == 0):
            # Modern view: a click in an input field puts the cursor there.
            row, col = self._cell_at(event.position())
            with self.session.lock:
                moved = self.session.emulation.click(row * self.session.screen.cols + col)
            if moved:
                self._on_update()
        text = self.selected_text()
        # X11 and Wayland keep a primary selection for middle-click paste; macOS doesn't.
        if text and QGuiApplication.clipboard().supportsSelection():
            QGuiApplication.clipboard().setText(text, QClipboard.Mode.Selection)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        line_no, col = self._cell_at(event.position())
        lines = self._all_lines()
        if line_no >= len(lines):
            return
        chars = "".join(c.char for c in lines[line_no])
        start = end = min(col, len(chars) - 1)
        while start > 0 and not chars[start - 1].isspace():
            start -= 1
        while end < len(chars) and not chars[end].isspace():
            end += 1
        self.sel_start, self.sel_end = (line_no, start), (line_no, end)
        self.mouseReleaseEvent(event)
        self.update()

    def clear_selection(self) -> None:
        self.match = None
        if self.sel_start is not None:
            self.sel_start = self.sel_end = None
            self.update()

    def _sel_range(self):
        if self.sel_start is None or self.sel_start == self.sel_end:
            return None
        return tuple(sorted((self.sel_start, self.sel_end)))

    def selected_text(self) -> str:
        rng = self._sel_range()
        if not rng:
            return ""
        (l0, c0), (l1, c1) = rng
        with self.session.lock:
            lines = self._all_lines()
            out = []
            for n in range(l0, min(l1, len(lines) - 1) + 1):
                chars = "".join(c.char for c in lines[n])
                a = c0 if n == l0 else 0
                b = c1 if n == l1 else len(chars)
                out.append(chars[a:b].rstrip())
        return "\n".join(out)

    def _selected(self, line_no: int, col: int) -> bool:
        rng = self._sel_range()
        if not rng:
            return False
        return rng[0] <= (line_no, col) < rng[1]

    # ------------------------------------------------------------- painting

    def _rgb(self, value, default) -> tuple[int, int, int]:
        if value is None:
            return default
        if isinstance(value, tuple):
            return value
        return self.colors.palette[value]

    def _colors(self, attr: Attr, selected: bool, screen_reverse: bool):
        c = self.colors
        fg_value = attr.fg
        if attr.bold and isinstance(fg_value, int) and fg_value < 8:
            fg_value += 8     # classic "bold is bright"
        fg = self._rgb(fg_value, c.bold if attr.bold and c.bold else c.fg)
        bg = self._rgb(attr.bg, c.bg)
        if attr.reverse != screen_reverse:
            fg, bg = bg, fg
        if selected:
            fg, bg = bg, fg
        if attr.dim and c.min_contrast <= 1:
            fg = tuple(v * 2 // 3 for v in fg)
        if attr.invisible:
            return QColor(*bg), QColor(*bg)
        if c.min_contrast > 1:
            key = (fg, bg)
            if key not in self._contrast_cache:
                self._contrast_cache[key] = ensure_contrast(fg, bg, c.min_contrast)
            fg = self._contrast_cache[key]
        return QColor(*fg), QColor(*bg)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        sch = self.colors
        with self.session.lock:
            s = self.session.screen
            p.fillRect(self.rect(), QColor(*(sch.fg if s.reverse_screen else sch.bg)))
            p.translate(self.offset_x, self.offset_y)
            lines = self._all_lines()
            history = len(lines) - s.rows
            first = history - self.scroll_offset
            for row in range(s.rows):
                line_no = first + row
                if not (0 <= line_no < len(lines)):
                    continue
                self._paint_line(p, row, line_no, lines[line_no], s.reverse_screen)
            if self._hot and self.scroll_offset == 0:
                row, start, end, _ = self._hot
                if row < s.rows and end <= s.cols:
                    fg, _ = self._colors(s.lines[row][start].attr, False, s.reverse_screen)
                    p.setPen(fg)
                    y = row * self.ch + self.ch - 1
                    p.drawLine(start * self.cw, y, end * self.cw - 1, y)
            if self.modern and self.scroll_offset == 0:
                self._paint_fields(p, s)
            if s.cursor_visible and self.scroll_offset == 0:
                rect = QRect(s.x * self.cw, s.y * self.ch, self.cw, self.ch)
                cursor = QColor(*sch.cursor)
                if self.hasFocus():
                    p.fillRect(rect, cursor)
                    cell = s.lines[s.y][s.x]
                    p.setPen(QColor(*ensure_contrast(sch.bg, sch.cursor, 4.5)))
                    p.setFont(self.term_font)
                    p.drawText(rect.x(), rect.y() + self.ascent, cell.char)
                else:
                    p.setPen(cursor)
                    p.drawRect(rect.adjusted(0, 0, -1, -1))
        p.end()

    def _paint_fields(self, p: QPainter, s) -> None:
        """Modern view: a rounded box round each input field, a focus ring
        round the one holding the cursor."""
        sch = self.colors
        border = QColor(*(round(a * 0.45 + b * 0.55) for a, b in zip(sch.fg, sch.bg)))
        focus = QColor(*sch.cursor)
        cursor = (s.y, s.x)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pad = max(2.0, self.cw * 0.25)
        for f in self.session.emulation.input_fields():
            box = QRectF(f.col * self.cw - pad, f.row * self.ch + 1.5,
                         f.length * self.cw + 2 * pad, self.ch - 3)
            has_cursor = f.row == cursor[0] and f.col <= cursor[1] < f.col + f.length
            p.setPen(QPen(focus if has_cursor else border, 2 if has_cursor else 1))
            p.drawRoundedRect(box, 4, 4)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _paint_line(self, p: QPainter, row: int, line_no: int, line, screen_reverse: bool) -> None:
        y = row * self.ch
        col = 0
        n = len(line)
        while col < n:
            attr = line[col].attr
            sel = self._selected(line_no, col)
            start = col
            # Draw runs of identically styled cells together.
            while col < n and line[col].attr == attr and self._selected(line_no, col) == sel:
                col += 1
            fg, bg = self._colors(attr, sel, screen_reverse)
            rect = QRect(start * self.cw, y, (col - start) * self.cw, self.ch)
            p.fillRect(rect, bg)
            text = "".join(c.char for c in line[start:col])
            if text.strip():
                p.setFont(self.bold_font if attr.bold else self.term_font)
                p.setPen(fg)
                # Draw per cell so wide fallback glyphs cannot drift off the grid.
                for i, ch in enumerate(text):
                    if ch != " ":
                        p.drawText((start + i) * self.cw, y + self.ascent, ch)
            if attr.underline:
                p.setPen(fg)
                p.drawLine(rect.left(), y + self.ch - 1, rect.right(), y + self.ch - 1)
