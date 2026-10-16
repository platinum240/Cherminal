"""The terminal view: paints a Session's screen and feeds it keystrokes."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QClipboard, QColor, QFont, QFontMetrics, QFontMetricsF, QGuiApplication, QKeyEvent,
                         QMouseEvent, QPainter, QWheelEvent)
from PyQt6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox, QWidget

from ..screen import Attr
from ..session import Session
from .colors import SCHEMES, palette_256
from .keys import key_name

PALETTE = palette_256()


class _Bridge(QObject):
    """Carries transport callbacks from the reader thread to the UI thread."""
    updated = pyqtSignal()
    closed = pyqtSignal(str)
    prompt = pyqtSignal(str, object)


class TerminalWidget(QWidget):
    title_changed = pyqtSignal(str)
    status_changed = pyqtSignal(str)

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session
        self.scheme = SCHEMES.get(session.profile.color_scheme, SCHEMES["classic"])
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.resize_mode = session.profile.resize_mode
        self.offset_x = self.offset_y = 0     # centres the grid in scale mode
        self.set_base_font(session.profile.font_family, session.profile.font_size)

        self.scroll_offset = 0                 # lines scrolled back into history
        self.sel_start: tuple[int, int] | None = None   # (absolute line, col)
        self.sel_end: tuple[int, int] | None = None
        self._last_title = ""

        self.bridge = _Bridge()
        self.bridge.updated.connect(self._on_update)
        self.bridge.closed.connect(self._on_closed)
        self.bridge.prompt.connect(self._on_prompt, Qt.ConnectionType.BlockingQueuedConnection)
        # Coalesce bursts of host output into at most ~60 repaints a second.
        self._repaint = QTimer(self, singleShot=True, interval=16)
        self._repaint.timeout.connect(self.update)
        session.on_action = self.do_action
        session.emulation.on_bell = QApplication.beep

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
        font = QFont(family)
        font.setPointSizeF(size)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setFixedPitch(True)
        self.term_font = font
        self.bold_font = QFont(font)
        self.bold_font.setBold(True)
        fm = QFontMetrics(font)
        self.cw = max(1, fm.horizontalAdvance("M"))
        self.ch = max(1, fm.height())
        self.ascent = fm.ascent()
        self.updateGeometry()
        self.update()

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
        w100, h100 = fm.horizontalAdvance("M"), fm.height()
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
            confirm_host_key=lambda host, kind, fp, changed: self._ask(
                "hostkey", f"The authenticity of host {host} can't be established.\n"
                           f"{kind} key fingerprint is {fp}.\n\nTrust this host and continue?"),
            on_update=self.bridge.updated.emit,
            on_closed=self.bridge.closed.emit)

    def _ask(self, kind: str, prompt: str):
        box = {"kind": kind, "result": None}
        self.bridge.prompt.emit(prompt, box)    # blocks until answered
        return box["result"]

    def _on_prompt(self, prompt: str, box: dict) -> None:
        if box["kind"] == "password":
            text, ok = QInputDialog.getText(self, "Password", prompt, QLineEdit.EchoMode.Password)
            box["result"] = text if ok else None
        else:
            answer = QMessageBox.question(self, "Unknown host key", prompt)
            box["result"] = answer == QMessageBox.StandardButton.Yes

    def _on_update(self) -> None:
        s = self.session.screen
        if (s.cols, s.rows) != getattr(self, "_last_grid", (s.cols, s.rows)):
            self._apply_resize()            # the host changed the screen size
        self._last_grid = (s.cols, s.rows)
        if not self._repaint.isActive():
            self._repaint.start()
        title = self.session.screen.title
        if title != self._last_title:
            self._last_title = title
            self.title_changed.emit(title)
        self.status_changed.emit(self.status_text())

    def _on_closed(self, reason: str) -> None:
        self.session.notice(reason)
        self.status_changed.emit(f"Disconnected: {reason}")
        self.update()

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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        named = key_name(event)
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
        elif name == "scroll-up":
            self.scroll_by(self.session.screen.rows // 2)
        elif name == "scroll-down":
            self.scroll_by(-(self.session.screen.rows // 2))

    def paste(self, mode=None) -> None:
        cb = QGuiApplication.clipboard()
        text = cb.text(mode or QClipboard.Mode.Clipboard)
        if text:
            self.session.paste(text)

    def copy(self) -> None:
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.sel_start = self.sel_end = self._cell_at(event.position())
            self.update()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.paste(QClipboard.Mode.Selection)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.sel_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.sel_end = self._cell_at(event.position())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        text = self.selected_text()
        if text:
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

    def _color(self, value, default) -> QColor:
        if value is None:
            return QColor(*default)
        if isinstance(value, tuple):
            return QColor(*value)
        return QColor(*PALETTE[value])

    def _colors(self, attr: Attr, selected: bool, screen_reverse: bool):
        sch = self.scheme
        fg_value = attr.fg
        if attr.bold and isinstance(fg_value, int) and fg_value < 8:
            fg_value += 8     # classic "bold is bright"
        fg = self._color(fg_value, sch.bold if attr.bold and sch.bold else sch.fg)
        bg = self._color(attr.bg, sch.bg)
        if attr.reverse != screen_reverse:
            fg, bg = bg, fg
        if selected:
            fg, bg = bg, fg
        if attr.dim:
            fg = fg.darker(150)
        if attr.invisible:
            fg = bg
        return fg, bg

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        sch = self.scheme
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
            if s.cursor_visible and self.scroll_offset == 0:
                rect = QRect(s.x * self.cw, s.y * self.ch, self.cw, self.ch)
                cursor = QColor(*sch.cursor)
                if self.hasFocus():
                    p.fillRect(rect, cursor)
                    cell = s.lines[s.y][s.x]
                    p.setPen(QColor(*sch.bg))
                    p.setFont(self.term_font)
                    p.drawText(rect.x(), rect.y() + self.ascent, cell.char)
                else:
                    p.setPen(cursor)
                    p.drawRect(rect.adjusted(0, 0, -1, -1))
        p.end()

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
