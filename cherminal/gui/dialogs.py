"""Session editor, session manager and key capture dialogs."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFontComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                             QWidget)

from .. import emulation
from ..config import BUNDLE_SUFFIX, TRANSPORTS, ProfileStore, SessionProfile
from ..keymap import Binding, normalize_key
from .colors import SCHEMES
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
        tabs.addTab(self._keyboard_tab(), "Keyboard && macros")
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
        self.transport.addItems(TRANSPORTS)
        self.transport.currentTextChanged.connect(self._transport_changed)
        self.host = QLineEdit()
        self.port = QSpinBox(maximum=65535, specialValueText="default")
        self.tls = QCheckBox("Use TLS (port 992 by default)")
        self.tls_verify = QCheckBox("Check the host's certificate")
        self.username = QLineEdit()
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
                ("User", self.username, {"ssh"}), ("Private key", ident_row, {"ssh"}),
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
        self.scheme = QComboBox()
        self.scheme.addItems(list(SCHEMES))
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
                              ("Font size", self.font_size), ("Colours", self.scheme),
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

    # ------------------------------------------------------------ data

    def _transport_changed(self, kind: str) -> None:
        for widget, kinds in self._rows.values():
            self._form.setRowVisible(widget, kind in kinds)

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
        self.username.setText(p.username)
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
        self.scheme.setCurrentText(p.color_scheme)
        self.answerback.setText(p.answerback)
        self.local_echo.setChecked(p.local_echo)
        self.enter_sends.setCurrentText(p.enter_sends)
        self.resize_mode.setCurrentIndex(max(0, self.resize_mode.findData(p.resize_mode)))
        self.keymap.setCurrentIndex(max(0, self.keymap.findData(p.keymap)))
        self.backspace.setCurrentIndex(max(0, self.backspace.findData(p.backspace)))
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
            username=self.username.text().strip(), identity_file=self.identity.text().strip(),
            command=self.command.text().strip(), serial_device=self.serial_device.text().strip(),
            baud=int(self.baud.currentText()), data_bits=int(self.data_bits.currentText()),
            parity=self.parity.currentText(), stop_bits=float(self.stop_bits.currentText()),
            flow_control=self.flow.currentText(), emulation=self.emulation.currentText(),
            encoding=self.encoding.currentText().strip(), cols=self.cols.value(),
            rows=self.rows.value(), scrollback=self.scrollback.value(),
            font_family=self.font_family.currentFont().family(),
            font_size=self.font_size.value(), color_scheme=self.scheme.currentText(),
            keymap=self.keymap.currentData(), backspace=self.backspace.currentData(),
            answerback=self.answerback.text(), local_echo=self.local_echo.isChecked(),
            enter_sends=self.enter_sends.currentText(),
            resize_mode=self.resize_mode.currentData(), keys=keys, macros=self.macros.items())

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

    def __init__(self, store: ProfileStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.chosen: SessionProfile | None = None
        self.setWindowTitle("Sessions")
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda _: self._connect())
        buttons = QVBoxLayout()
        for label, slot in (("Connect", self._connect), ("New…", self._new),
                            ("Edit…", self._edit), ("Duplicate", self._duplicate),
                            ("Delete", self._delete), (None, None),
                            ("Import…", self._import), ("Export…", self._export)):
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
