"""Session editor, session manager and key capture dialogs."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPainter
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout,
                             QHeaderView, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                             QWidget)

from .. import emulation, policy
from ..config import BUNDLE_SUFFIX, TRANSPORTS, ProfileStore, SessionProfile
from ..keymap import Binding, normalize_key
from .colors import (PALETTE_NAMES, SCHEMES, contrast, ensure_contrast, palette_256,
                     parse_hex, resolve, to_hex)
from .keys import key_name

ENCODINGS = ["", "utf-8", "latin-1", "cp437", "cp850", "cp852", "cp866", "cp1250", "cp1251",
             "cp1252", "iso8859-2", "iso8859-5", "iso8859-7", "iso8859-15", "koi8-r",
             "hp-roman8", "mac-roman", "ascii"]
BAUDS = [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400]


class KeyCaptureDialog(QDialog):
    """Press a key; returns its Cherminal name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Press a key")
        self.key = ""
        label = QLabel("Press the key or key combination to map.\n(Esc alone cancels.)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.addWidget(label)
        self.resize(320, 120)

    def focusNextPrevChild(self, next: bool) -> bool:
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        named = key_name(event)
        if named is None or not named[0]:
            return
        if named[0] == "Escape":
            self.reject()
            return
        self.key = named[0]
        self.accept()


class _PairTable(QWidget):
    """Two-column editable table (key/name -> value) with add/remove buttons."""

    def __init__(self, headers: tuple[str, str], capture: bool, parent=None):
        super().__init__(parent)
        self.capture = capture
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        add = QPushButton("Capture key…" if capture else "Add")
        remove = QPushButton("Remove")
        add.clicked.connect(self._add)
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        lay.addLayout(buttons)

    def _add(self) -> None:
        name = "macro"
        if self.capture:
            dlg = KeyCaptureDialog(self)
            if not dlg.exec():
                return
            name = dlg.key
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).text() == name:
                    self.table.setCurrentCell(r, 1)
                    self.table.editItem(self.table.item(r, 1))
                    return
        self.add_row(name, "")
        self.table.setCurrentCell(self.table.rowCount() - 1, 1)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 1))

    def add_row(self, key: str, value: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(key))
        self.table.setItem(r, 1, QTableWidgetItem(value))

    def set_items(self, items: dict[str, str]) -> None:
        self.table.setRowCount(0)
        for k, v in items.items():
            self.add_row(k, v)

    def items(self) -> dict[str, str]:
        out = {}
        for r in range(self.table.rowCount()):
            k = self.table.item(r, 0).text().strip()
            v = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            if k:
                out[k] = v
        return out


class ColorButton(QPushButton):
    """A swatch that opens a colour picker. Empty value means "use the default"."""

    changed = pyqtSignal()

    def __init__(self, default: tuple[int, int, int] = (0, 0, 0), label: str = ""):
        super().__init__()
        self.value = ""
        self.default = default
        self.label = label
        self.setMinimumWidth(110)
        self.clicked.connect(self._pick)
        self._show()

    def set_value(self, value: str, default=None) -> None:
        self.value = value
        if default is not None:
            self.default = default
        self._show()

    def rgb(self) -> tuple[int, int, int]:
        return parse_hex(self.value) if self.value else self.default

    def _show(self) -> None:
        r, g, b = self.rgb()
        ink = "#000000" if contrast((r, g, b), (0, 0, 0)) > contrast((r, g, b), (255, 255, 255)) \
            else "#ffffff"
        self.setText(self.value or "default")
        self.setStyleSheet(f"background: {to_hex((r, g, b))}; color: {ink}")
        self.setToolTip(f"{self.label}: {to_hex((r, g, b))}" if self.label else to_hex((r, g, b)))

    def _pick(self) -> None:
        color = QColorDialog.getColor(QColor(*self.rgb()), self, self.label or "Colour")
        if color.isValid():
            self.set_value(color.name())
            self.changed.emit()

    def reset(self) -> None:
        self.set_value("")
        self.changed.emit()


class ColorPreview(QWidget):
    """Sample text in the colours a session will use, contrast rules applied."""

    SAMPLE = [("Normal text  ", None, False), ("Bold", None, True)]

    def __init__(self):
        super().__init__()
        self.colors = None
        self.setMinimumHeight(110)

    def set_colors(self, colors) -> None:
        self.colors = colors
        self.update()

    def paintEvent(self, event) -> None:
        c = self.colors
        if c is None:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(*c.bg))
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        p.setFont(font)
        line = p.fontMetrics().height()

        def ink(rgb):
            return QColor(*ensure_contrast(rgb, c.bg, c.min_contrast))

        x = 8
        for text, idx, bold in self.SAMPLE:
            font.setBold(bold)
            p.setFont(font)
            p.setPen(ink(c.bold if bold and c.bold else c.fg))
            p.drawText(x, line, text)
            x += p.fontMetrics().horizontalAdvance(text)
        font.setBold(False)
        p.setFont(font)
        for row, base in enumerate((0, 8)):
            x = 8
            for i in range(8):
                name = PALETTE_NAMES[base + i].replace("bright-", "")
                p.setPen(ink(c.palette[base + i]))
                p.drawText(x, line * (row + 2) + 4, name)
                x += p.fontMetrics().horizontalAdvance(name + " ")
        ratio = contrast(c.fg, c.bg)
        grade = "AAA" if ratio >= 7 else "AA" if ratio >= 4.5 else "below AA"
        p.setPen(ink(c.fg))
        p.drawText(8, line * 4 + 8, f"Text contrast {ratio:.1f}:1 ({grade})")
        p.fillRect(8, line * 4 + 14, 10, line, QColor(*c.cursor))
        p.end()


class LoginDialog(QDialog):
    """User name and password together, for hosts where the login isn't the
    workstation's own."""

    def __init__(self, host: str, user: str = "", error: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Log in to {host}")
        self.user = QLineEdit(user)
        self.password = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        form = QFormLayout(self)
        if error:
            note = QLabel(error)
            note.setStyleSheet("color: #c00000; font-weight: bold")
            form.addRow(note)
        form.addRow("User name", self.user)
        form.addRow("Password", self.password)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Log in")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        (self.password if user else self.user).setFocus()

    def _accept(self) -> None:
        if self.user.text().strip():
            self.accept()
        else:
            self.user.setFocus()

    def credentials(self) -> tuple[str, str]:
        return self.user.text().strip(), self.password.text()


class ColoursPanel(QWidget):
    """Scheme, text/background/cursor, host colours and minimum contrast.

    Used for a session's saved colours and for one-off changes to an open one.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.scheme = QComboBox()
        self.scheme.addItems(list(SCHEMES))
        self.fg_color = ColorButton(label="Text colour")
        self.bg_color = ColorButton(label="Background")
        self.cursor_color = ColorButton(label="Cursor")
        self.min_contrast = QComboBox()
        for label, value in (("Scheme default", 0.0), ("Off", 1.0),
                             ("4.5:1 (WCAG AA)", 4.5), ("7:1 (WCAG AAA, high contrast)", 7.0)):
            self.min_contrast.addItem(label, value)
        self.min_contrast.setToolTip("Lightens or darkens any colour the host uses that is "
                                     "too faint against the background.")
        f.addRow("Scheme", self.scheme)
        for label, button in (("Text", self.fg_color), ("Background", self.bg_color),
                              ("Cursor", self.cursor_color)):
            row = QHBoxLayout()
            row.addWidget(button)
            reset = QPushButton("Use scheme's")
            reset.clicked.connect(button.reset)
            row.addWidget(reset)
            row.addStretch()
            f.addRow(label, row)
        f.addRow("Minimum contrast", self.min_contrast)
        lay.addLayout(f)
        lay.addWidget(QLabel("Host colours (click to change)"))
        grid = QGridLayout()
        defaults = palette_256()
        self.palette_buttons = {}
        for i, name in enumerate(PALETTE_NAMES):
            b = ColorButton(defaults[i], label=name)
            b.setMinimumWidth(60)
            b.setToolTip(name)
            self.palette_buttons[name] = b
            grid.addWidget(QLabel(name), (i // 8) * 2, i % 8)
            grid.addWidget(b, (i // 8) * 2 + 1, i % 8)
            b.changed.connect(self._update_preview)
        lay.addLayout(grid)
        reset_pal = QPushButton("Reset host colours")
        reset_pal.clicked.connect(self._reset_palette)
        lay.addWidget(reset_pal, alignment=Qt.AlignmentFlag.AlignLeft)
        self.preview = ColorPreview()
        lay.addWidget(self.preview)
        lay.addStretch()
        for b in (self.fg_color, self.bg_color, self.cursor_color):
            b.changed.connect(self._update_preview)
        self.scheme.currentTextChanged.connect(self._update_preview)
        self.min_contrast.currentIndexChanged.connect(self._update_preview)

    def load(self, p: SessionProfile) -> None:
        self.scheme.setCurrentText(p.color_scheme)
        self.fg_color.set_value(p.fg_color)
        self.bg_color.set_value(p.bg_color)
        self.cursor_color.set_value(p.cursor_color)
        self.min_contrast.setCurrentIndex(max(0, self.min_contrast.findData(float(p.min_contrast))))
        for name, b in self.palette_buttons.items():
            b.set_value(p.palette.get(name, ""))
        self._update_preview()

    def settings(self) -> dict:
        return dict(
            color_scheme=self.scheme.currentText(), fg_color=self.fg_color.value,
            bg_color=self.bg_color.value, cursor_color=self.cursor_color.value,
            min_contrast=self.min_contrast.currentData(),
            palette={n: b.value for n, b in self.palette_buttons.items() if b.value})

    def _reset_palette(self) -> None:
        for b in self.palette_buttons.values():
            b.set_value("")
        self._update_preview()

    def _update_preview(self, *_) -> None:
        if not hasattr(self, "preview"):
            return
        sch = SCHEMES.get(self.scheme.currentText(), SCHEMES["classic"])
        self.fg_color.set_value(self.fg_color.value, sch.fg)
        self.bg_color.set_value(self.bg_color.value, sch.bg)
        self.cursor_color.set_value(self.cursor_color.value, sch.cursor)
        self.preview.set_colors(resolve(replace(SessionProfile(), **self.settings())))


def colour_settings(p: SessionProfile) -> dict:
    return dict(color_scheme=p.color_scheme, fg_color=p.fg_color, bg_color=p.bg_color,
                cursor_color=p.cursor_color, min_contrast=float(p.min_contrast),
                palette=dict(p.palette))


class SessionColoursDialog(QDialog):
    """Change an open session's colours until its window closes, without
    touching the saved session (e.g. for one user's eyesight on a shared PC)."""

    def __init__(self, saved: SessionProfile, current: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Colours for this session")
        self.saved = saved
        note = QLabel("These colours apply to this window until it is closed. "
                      "The saved session is not changed.")
        note.setWordWrap(True)
        self.panel = ColoursPanel()
        self.panel.load(replace(saved, **current) if current else saved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        back = buttons.addButton("Use the session's colours",
                                 QDialogButtonBox.ButtonRole.ResetRole)
        back.clicked.connect(lambda: self.panel.load(saved))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.panel)
        lay.addWidget(buttons)

    def override(self) -> dict | None:
        """The one-off colours, or None when they match the saved session."""
        chosen = self.panel.settings()
        return None if chosen == colour_settings(self.saved) else chosen


class SessionEditor(QDialog):
    """Edit a profile. ``connect_only`` turns it into a Quick Connect dialog."""

    def __init__(self, profile: SessionProfile, store: ProfileStore, connect_only=False,
                 parent=None):
        super().__init__(parent)
        self.store = store
        self.original_name = profile.name
        self.result_profile: SessionProfile | None = None
        self.setWindowTitle("Quick connect" if connect_only else f"Session: {profile.name}")
        tabs = QTabWidget()
        tabs.addTab(self._connection_tab(), "Connection")
        tabs.addTab(self._terminal_tab(), "Terminal")
        self.colours = ColoursPanel()
        tabs.addTab(self.colours, "Colours")
        tabs.addTab(self._keyboard_tab(), "Keyboard && macros")
        self.transfer_tab = self._transfer_tab()
        tabs.addTab(self.transfer_tab, "File transfer")
        tabs.addTab(self._printing_tab(), "Printing")
        tabs.addTab(self._upkeep_tab(), "Idle && reconnect")
        tabs.addTab(self._logging_tab(), "Logging")
        self.tabs = tabs
        buttons = QDialogButtonBox()
        if connect_only:
            buttons.addButton("Connect", QDialogButtonBox.ButtonRole.AcceptRole)
            self.save_box = QCheckBox("Save as a session")
            buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        else:
            self.save_box = None
            buttons.setStandardButtons(QDialogButtonBox.StandardButton.Save
                                       | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        bottom = QHBoxLayout()
        if self.save_box:
            bottom.addWidget(self.save_box)
        bottom.addStretch()
        bottom.addWidget(buttons)
        lay.addLayout(bottom)
        self._load(profile)
        self.resize(560, 520)

    # -------------------------------------------------------------- tabs

    def _connection_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.name = QLineEdit()
        self.transport = QComboBox()
        self.transport.addItems([t for t in TRANSPORTS if t in policy.current().allowed_transports])
        self.transport.currentTextChanged.connect(self._transport_changed)
        self.host = QLineEdit()
        self.port = QSpinBox(maximum=65535, specialValueText="default")
        self.tls = QCheckBox("Use TLS (port 992 by default)")
        self.tls_verify = QCheckBox("Check the host's certificate")
        self.username = QLineEdit()
        self.ask_login = QCheckBox("Ask for user name and password when connecting")
        self.ask_login.setToolTip("For users whose login on this host isn't their "
                                  "workstation login. The user name above is filled in "
                                  "as a suggestion.")
        self.identity = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_key)
        ident_row = QHBoxLayout()
        ident_row.addWidget(self.identity)
        ident_row.addWidget(browse)
        self.command = QLineEdit(placeholderText="default: your login shell")
        self.serial_device = QLineEdit()
        self.baud = QComboBox(editable=True)
        self.baud.addItems([str(b) for b in BAUDS])
        self.data_bits = QComboBox()
        self.data_bits.addItems(["5", "6", "7", "8"])
        self.parity = QComboBox()
        self.parity.addItems(["none", "even", "odd", "mark", "space"])
        self.stop_bits = QComboBox()
        self.stop_bits.addItems(["1", "1.5", "2"])
        self.flow = QComboBox()
        self.flow.addItems(["none", "xonxoff", "rtscts"])
        self._rows = {}
        for label, widget, kinds in (
                ("Name", self.name, None), ("Connection", self.transport, None),
                ("Host", self.host, {"ssh", "telnet"}), ("Port", self.port, {"ssh", "telnet"}),
                ("Security", self.tls, {"telnet"}), ("", self.tls_verify, {"telnet"}),
                ("User", self.username, {"ssh"}), ("Login", self.ask_login, {"ssh"}),
                ("Private key", ident_row, {"ssh"}),
                ("Command", self.command, {"local"}),
                ("Device", self.serial_device, {"serial"}), ("Baud", self.baud, {"serial"}),
                ("Data bits", self.data_bits, {"serial"}), ("Parity", self.parity, {"serial"}),
                ("Stop bits", self.stop_bits, {"serial"}), ("Flow control", self.flow, {"serial"})):
            f.addRow(label, widget)
            if kinds:
                self._rows[label] = (widget, kinds)
        self._form = f
        return w

    def _terminal_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.emulation = QComboBox()
        self.emulation.addItems(list(emulation.EMULATIONS))
        self.encoding = QComboBox(editable=True)
        self.encoding.addItems(ENCODINGS)
        self.encoding.setItemText(0, "")
        self.encoding.lineEdit().setPlaceholderText("emulation default")
        self.cols = QSpinBox(minimum=20, maximum=400)
        self.rows = QSpinBox(minimum=5, maximum=200)
        self.scrollback = QSpinBox(minimum=0, maximum=1_000_000, singleStep=1000)
        self.font_family = QFontComboBox()
        self.font_family.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self.font_size = QSpinBox(minimum=5, maximum=72)
        self.answerback = QLineEdit()
        self.local_echo = QCheckBox("Echo typed characters locally")
        self.enter_sends = QComboBox()
        self.enter_sends.addItems(["cr", "crlf", "lf"])
        self.resize_mode = QComboBox()
        self.resize_mode.addItem("Scale the text to fit", "scale")
        self.resize_mode.addItem("Add rows and columns", "grow")
        for label, widget in (("Emulation", self.emulation), ("Character set", self.encoding),
                              ("Columns", self.cols), ("Rows", self.rows),
                              ("Scrollback lines", self.scrollback), ("Font", self.font_family),
                              ("Font size", self.font_size),
                              ("Answerback", self.answerback), ("Enter sends", self.enter_sends),
                              ("When the window resizes", self.resize_mode),
                              ("", self.local_echo)):
            f.addRow(label, widget)
        return w

    def _keyboard_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        self.keymap = QComboBox()
        self.keymap.addItem("(emulation default)", "")
        for name in self.store.keymap_names():
            self.keymap.addItem(name, name)
        self.backspace = QComboBox()
        for label, value in (("keymap default", ""), ("DEL (^?)", "del"), ("Backspace (^H)", "bs")):
            self.backspace.addItem(label, value)
        f.addRow("Keymap", self.keymap)
        f.addRow("Backspace sends", self.backspace)
        lay.addLayout(f)
        visual = QPushButton("Keyboard map…")
        visual.setToolTip("Remap keys by clicking them on a picture of the keyboard")
        visual.clicked.connect(self._open_keyboard_map)
        lay.addWidget(visual, alignment=Qt.AlignmentFlag.AlignLeft)
        hint = QLabel("Values use \\e for Esc, \\r Enter, \\xHH bytes, ^A control keys, or "
                      "action:paste / action:copy / action:break / action:macro:NAME. "
                      "IBM 3270 keys: action:enter, action:pf1-pf24, action:pa1-pa3, "
                      "action:clear, action:reset and the others in the README.")
        hint.setWordWrap(True)
        hint.setFont(QFont(hint.font().family(), max(7, hint.font().pointSize() - 1)))
        lay.addWidget(QLabel("Key overrides for this session"))
        self.keys = _PairTable(("Key", "Sends"), capture=True)
        lay.addWidget(self.keys)
        lay.addWidget(QLabel("Macros (shown on the function-key bar)"))
        self.macros = _PairTable(("Name", "Sends"), capture=False)
        lay.addWidget(self.macros)
        lay.addWidget(hint)
        return w

    def _transfer_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.file_transfer = QCheckBox("Allow uploading files by dropping them on the window")
        self.upload_dir = QLineEdit(placeholderText="the user's home folder")
        self.file_transfer.toggled.connect(self.upload_dir.setEnabled)
        self.transfer_box = QWidget()
        box = QVBoxLayout(self.transfer_box)
        box.setContentsMargins(0, 0, 0, 0)
        f = QFormLayout()
        f.addRow(self.file_transfer)
        f.addRow("Upload to folder", self.upload_dir)
        box.addLayout(f)
        note = QLabel(
            "SSH sessions only. Off unless you turn it on here. Files go over the same "
            "encrypted SFTP connection as the session, to the host whose key was checked "
            "when it connected, signed in as the session's user. The user confirms each "
            "upload, files on the host are only replaced after asking, and folders are not "
            "copied. A folder starting with ~/ is inside the user's home folder.")
        note.setWordWrap(True)
        box.addWidget(note)
        lay.addWidget(self.transfer_box)
        self.transfer_ssh_only = QLabel("File transfer is only available for SSH connections.")
        lay.addWidget(self.transfer_ssh_only)
        lay.addStretch()
        return w

    def _printing_tab(self) -> QWidget:
        from .printing import printer_names
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        self.printer = QComboBox(editable=True)
        self.printer.addItem("(choose when printing)", "")
        for name in printer_names():
            self.printer.addItem(name, name)
        self.printer.setToolTip("A printer set here is used without asking, which suits "
                                "shared and limited-mode machines. Type a CUPS printer "
                                "name if it isn't listed on this machine.")
        self.host_print = QCheckBox("Let the host print to it (VT passthrough printing)")
        f.addRow("Printer", self.printer)
        f.addRow(self.host_print)
        lay.addLayout(f)
        note = QLabel("Print Screen (the Print key, Ctrl+Shift+P, Session › Print screen "
                      "or the right-click menu) prints what is on the screen, hidden fields "
                      "left blank. With no printer chosen here it asks each time and can "
                      "also save a PDF. Passthrough jobs (ESC [ 5 i … ESC [ 4 i from the host) "
                      "go to the printer unchanged through CUPS.")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        return w

    def _upkeep_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        rules = policy.current()
        self.idle_timeout = QSpinBox(minimum=0, maximum=24 * 60, suffix=" minutes",
                                     specialValueText="Never")
        self.idle_timeout.setToolTip("Disconnect when nobody has typed or clicked in the "
                                     "session for this long. The screen is blanked and "
                                     "Enter connects again.")
        if rules.max_idle_timeout:
            self.idle_timeout.setRange(1, rules.max_idle_timeout)
            self.idle_timeout.setToolTip(f"This computer's policy allows at most "
                                         f"{rules.max_idle_timeout} minutes.")
        self.keepalive = QSpinBox(minimum=0, maximum=3600, suffix=" seconds",
                                  specialValueText="Off")
        self.keepalive.setToolTip("Send a keep-alive this often when the session is quiet, "
                                  "so firewalls don't drop it and a dead connection is "
                                  "noticed.")
        self.auto_reconnect = QCheckBox("Reconnect automatically if the connection drops")
        if not rules.auto_reconnect:
            self.auto_reconnect.setEnabled(False)
            self.auto_reconnect.setToolTip("Turned off by this computer's policy")
        f.addRow("Disconnect when idle for", self.idle_timeout)
        f.addRow("Keep-alive every", self.keepalive)
        f.addRow(self.auto_reconnect)
        lay.addLayout(f)
        note = QLabel("Typing and clicking count as activity; output from the host does not. "
                      "A minute before an idle disconnect the status bar warns. Reconnecting "
                      "happens only when the connection breaks, not when you log off or the "
                      "idle timeout closes it, and it asks for a password again if the "
                      "session needs one.")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        return w

    def _logging_tab(self) -> QWidget:
        from ..sessionlog import log_dir
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        rules = policy.current()
        self.log_session = QCheckBox("Keep a log of this session's text")
        self.log_file_kb = QSpinBox(minimum=16, maximum=1024 * 1024, singleStep=256,
                                    suffix=" KB")
        self.log_keep = QSpinBox(minimum=0, maximum=99, suffix=" older files")
        self.log_session.toggled.connect(self._log_toggled)
        if rules.session_logging != "allowed":
            self.log_session.setEnabled(False)
            self.log_session.setToolTip("Set by this computer's policy")
        f.addRow(self.log_session)
        f.addRow("Start a new file at", self.log_file_kb)
        f.addRow("Keep", self.log_keep)
        lay.addLayout(f)
        note = QLabel(
            f"Logs go to {log_dir()}. The log has what the screen showed: lines as they "
            f"scroll up and, on IBM screens, each screen as it is sent. Hidden fields such "
            f"as passwords are left blank and keystrokes are never logged. Old files are "
            f"deleted by themselves, and all session logs together are kept under "
            f"{rules.log_total_mb} MB.")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        return w

    def _log_toggled(self, on: bool) -> None:
        self.log_file_kb.setEnabled(on)
        self.log_keep.setEnabled(on)

    def _open_keyboard_map(self) -> None:
        from .keyboard import KeyboardEditor
        try:
            profile = replace(self._build(), keys={})
            base = self.store.build_keymap(profile)
        except (ValueError, LookupError) as e:
            QMessageBox.warning(self, "Keyboard map", str(e))
            return
        emu = emulation.EMULATIONS[profile.emulation]
        dlg = KeyboardEditor(base, self.keys.items(), block_mode=emu.block_mode,
                             macros=list(self.macros.items()), store=self.store,
                             base_name=profile.keymap or emu.keymap, parent=self)
        if dlg.exec():
            self.keys.set_items(dlg.overrides)

    # ------------------------------------------------------------ data

    def _transport_changed(self, kind: str) -> None:
        for widget, kinds in self._rows.values():
            self._form.setRowVisible(widget, kind in kinds)
        if hasattr(self, "transfer_tab"):
            ssh = kind == "ssh"
            self.transfer_box.setVisible(ssh)
            self.transfer_ssh_only.setVisible(not ssh)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Private key", "~/.ssh")
        if path:
            self.identity.setText(path)

    def _load(self, p: SessionProfile) -> None:
        self.name.setText(p.name)
        self.transport.setCurrentText(p.transport)
        self._transport_changed(p.transport)
        self.host.setText(p.host)
        self.port.setValue(p.port)
        self.tls.setChecked(p.tls)
        self.tls_verify.setChecked(p.tls_verify)
        rules = policy.current()
        locked = "Required by this computer's policy"
        if rules.require_tls:
            self.tls.setChecked(True)
            self.tls.setEnabled(False)
            self.tls.setToolTip(locked)
        if rules.require_tls_verify:
            self.tls_verify.setChecked(True)
            self.tls_verify.setEnabled(False)
            self.tls_verify.setToolTip(locked)
        self.username.setText(p.username)
        self.ask_login.setChecked(p.ask_login)
        self.file_transfer.setChecked(p.file_transfer)
        self.upload_dir.setText(p.upload_dir)
        self.upload_dir.setEnabled(p.file_transfer)
        self.identity.setText(p.identity_file)
        self.command.setText(p.command)
        self.serial_device.setText(p.serial_device)
        self.baud.setCurrentText(str(p.baud))
        self.data_bits.setCurrentText(str(p.data_bits))
        self.parity.setCurrentText(p.parity)
        self.stop_bits.setCurrentText(f"{p.stop_bits:g}")
        self.flow.setCurrentText(p.flow_control)
        self.emulation.setCurrentText(p.emulation)
        self.encoding.setCurrentText(p.encoding)
        self.cols.setValue(p.cols)
        self.rows.setValue(p.rows)
        self.scrollback.setValue(p.scrollback)
        self.font_family.setCurrentFont(QFont(p.font_family))
        self.font_size.setValue(p.font_size)
        self.colours.load(p)
        self.answerback.setText(p.answerback)
        self.local_echo.setChecked(p.local_echo)
        self.enter_sends.setCurrentText(p.enter_sends)
        self.resize_mode.setCurrentIndex(max(0, self.resize_mode.findData(p.resize_mode)))
        self.keymap.setCurrentIndex(max(0, self.keymap.findData(p.keymap)))
        self.backspace.setCurrentIndex(max(0, self.backspace.findData(p.backspace)))
        idx = self.printer.findData(p.printer)
        if idx < 0 and p.printer:
            self.printer.addItem(p.printer, p.printer)
            idx = self.printer.count() - 1
        self.printer.setCurrentIndex(max(0, idx))
        self.host_print.setChecked(p.host_print)
        self._loaded = p           # settings the policy decides are saved unchanged
        self.idle_timeout.setValue(rules.idle_timeout(p.idle_timeout))
        self.keepalive.setValue(p.keepalive)
        self.auto_reconnect.setChecked(p.auto_reconnect and rules.auto_reconnect)
        self.log_session.setChecked(rules.logging(p.log_session))
        self.log_file_kb.setValue(p.log_file_kb)
        self.log_keep.setValue(p.log_keep)
        self._log_toggled(self.log_session.isChecked())
        self.keys.set_items(p.keys)
        self.macros.set_items(p.macros)

    def _build(self) -> SessionProfile:
        keys = {}
        for k, v in self.keys.items().items():
            keys[normalize_key(k)] = v
            if v:
                Binding.parse(v)
        for v in self.macros.items().values():
            Binding.parse(v)
        return SessionProfile(
            name=self.name.text().strip() or "Untitled", transport=self.transport.currentText(),
            host=self.host.text().strip(), port=self.port.value(),
            tls=self.tls.isChecked(), tls_verify=self.tls_verify.isChecked(),
            username=self.username.text().strip(), ask_login=self.ask_login.isChecked(),
            file_transfer=self.file_transfer.isChecked(),
            upload_dir=self.upload_dir.text().strip(),
            identity_file=self.identity.text().strip(),
            command=self.command.text().strip(), serial_device=self.serial_device.text().strip(),
            baud=int(self.baud.currentText()), data_bits=int(self.data_bits.currentText()),
            parity=self.parity.currentText(), stop_bits=float(self.stop_bits.currentText()),
            flow_control=self.flow.currentText(), emulation=self.emulation.currentText(),
            encoding=self.encoding.currentText().strip(), cols=self.cols.value(),
            rows=self.rows.value(), scrollback=self.scrollback.value(),
            font_family=self.font_family.currentFont().family(),
            font_size=self.font_size.value(), **self.colours.settings(),
            keymap=self.keymap.currentData(), backspace=self.backspace.currentData(),
            answerback=self.answerback.text(), local_echo=self.local_echo.isChecked(),
            enter_sends=self.enter_sends.currentText(),
            resize_mode=self.resize_mode.currentData(), printer=self._printer_name(),
            host_print=self.host_print.isChecked(), idle_timeout=self.idle_timeout.value(),
            keepalive=self.keepalive.value(),
            auto_reconnect=(self.auto_reconnect.isChecked() if self.auto_reconnect.isEnabled()
                            else self._loaded.auto_reconnect),
            log_session=(self.log_session.isChecked() if self.log_session.isEnabled()
                         else self._loaded.log_session), log_file_kb=self.log_file_kb.value(),
            log_keep=self.log_keep.value(), keys=keys, macros=self.macros.items())

    def _printer_name(self) -> str:
        text = self.printer.currentText().strip()
        if self.printer.currentIndex() >= 0 and self.printer.itemText(
                self.printer.currentIndex()) == text:
            return self.printer.currentData() or ""
        return text                              # typed in by hand

    def _accept(self) -> None:
        try:
            profile = self._build()
            if profile.encoding:
                "".encode(profile.encoding)
            if profile.transport in ("ssh", "telnet") and not profile.host:
                raise ValueError("enter a host name")
        except (ValueError, LookupError) as e:
            QMessageBox.warning(self, "Check settings", str(e))
            return
        if self.save_box is None or self.save_box.isChecked():
            self.store.save(profile, old_name=self.original_name)
        self.result_profile = profile
        self.accept()


class SessionManager(QDialog):
    """Saved sessions: connect, create, edit, duplicate, delete, import, export."""

    ORIGIN_LABEL = {"user": "", "shared": "  [shared]", "customised": "  [shared, edited here]"}

    def __init__(self, store: ProfileStore, parent=None, limited: bool = False):
        super().__init__(parent)
        self.store = store
        self.limited = limited
        self.chosen: SessionProfile | None = None
        self.setWindowTitle("Sessions")
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda _: self._connect())
        buttons = QVBoxLayout()
        actions = [("Connect", self._connect)]
        if not limited:
            actions += [("New…", self._new), ("Edit…", self._edit),
                        ("Duplicate", self._duplicate), ("Delete", self._delete), (None, None),
                        ("Import…", self._import), ("Export…", self._export)]
        for label, slot in actions:
            if label is None:
                buttons.addSpacing(12)
                continue
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        lay = QHBoxLayout(self)
        lay.addWidget(self.list, 1)
        lay.addLayout(buttons)
        self.resize(560, 380)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for p in self.store.list():
            if self.limited and p.transport == "local":
                continue                # limited mode never offers a local shell
            if p.transport not in policy.current().allowed_transports:
                continue
            where = {"local": "local shell", "serial": p.serial_device}.get(p.transport, p.host)
            item = QListWidgetItem(f"{p.name}    —    {p.transport} {where} · {p.emulation}"
                                   + self.ORIGIN_LABEL[self.store.origin(p.name)])
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _current(self) -> SessionProfile | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected(self) -> list[SessionProfile]:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def _connect(self) -> None:
        self.chosen = self._current()
        if self.chosen:
            self.accept()

    def _new(self) -> None:
        if SessionEditor(SessionProfile(), self.store, parent=self).exec():
            self.refresh()

    def _edit(self) -> None:
        p = self._current()
        if p and SessionEditor(p, self.store, parent=self).exec():
            self.refresh()

    def _duplicate(self) -> None:
        p = self._current()
        if p:
            copy = SessionProfile.from_dict({**p.to_dict(), "name": p.name + " copy"})
            self.store.save(copy)
            self.refresh()

    def _delete(self) -> None:
        p = self._current()
        if not p:
            return
        origin = self.store.origin(p.name)
        if origin == "shared":
            QMessageBox.information(self, "Delete session",
                                    f"“{p.name}” comes from the shared setup, so it can only "
                                    "be removed there.")
            return
        question = (f"Discard your changes to “{p.name}” and go back to the shared version?"
                    if origin == "customised" else f"Delete the saved session “{p.name}”?")
        if QMessageBox.question(self, "Delete session", question) \
                == QMessageBox.StandardButton.Yes:
            self.store.delete(p.name)
            self.refresh()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import sessions", "",
                                              f"Cherminal sessions (*{BUNDLE_SUFFIX});;"
                                              "All files (*)")
        if not path:
            return
        try:
            names = self.store.import_bundle(path)
        except (OSError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "Import sessions", f"Could not import {path}: {e}")
            return
        self.refresh()
        QMessageBox.information(self, "Import sessions",
                                "Imported: " + (", ".join(names) or "no sessions"))

    def _export(self) -> None:
        profiles = self._selected()
        if not profiles:
            return
        default = (profiles[0].slug if len(profiles) == 1 else "sessions") + BUNDLE_SUFFIX
        path, _ = QFileDialog.getSaveFileName(self, "Export sessions", default,
                                              f"Cherminal sessions (*{BUNDLE_SUFFIX})")
        if not path:
            return
        if not path.endswith(BUNDLE_SUFFIX):
            path += BUNDLE_SUFFIX
        try:
            self.store.export_bundle([p.name for p in profiles], path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Export sessions", f"Could not export: {e}")
