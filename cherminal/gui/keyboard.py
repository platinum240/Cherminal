"""A clickable picture of a PC keyboard for remapping keys.

Click a key (or press it), pick what it does, and the change is kept as a
session key override; the whole set can also be saved as a keymap file to
share. Shift, Ctrl and Alt on the picture switch which layer is shown, so
"Shift+F3" is edited by latching Shift and clicking F3.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QVBoxLayout, QWidget)

from ..keymap import Binding, Keymap, format_notation, normalize_key, parse_notation

MOD = "<mod>"     # a modifier key on the picture: toggles a layer, not bindable
OFF = "<off>"     # drawn for shape (Caps Lock, Num Lock) but not bindable

# (label, key name, width in key units); None is a quarter-key gap.
MAIN_ROWS = [
    [("Esc", "Escape", 1), (None, None, 1)]
    + [(f"F{i}", f"F{i}", 1) for i in range(1, 5)] + [(None, None, 0.5)]
    + [(f"F{i}", f"F{i}", 1) for i in range(5, 9)] + [(None, None, 0.5)]
    + [(f"F{i}", f"F{i}", 1) for i in range(9, 13)],
    [(c, c, 1) for c in "`1234567890-="] + [("Backspace", "Backspace", 2)],
    [("Tab", "Tab", 1.5)] + [(c, c, 1) for c in "QWERTYUIOP[]"] + [("\\", "\\", 1.5)],
    [("Caps", OFF, 1.75)] + [(c, c, 1) for c in "ASDFGHJKL;'"] + [("Enter", "Enter", 2.25)],
    [("Shift", MOD, 2.25)] + [(c, c, 1) for c in "ZXCVBNM,./"] + [("Shift", MOD, 2.75)],
    [("Ctrl", MOD, 1.5), (None, None, 1), ("Alt", MOD, 1.5), ("Space", "Space", 6),
     ("Alt", MOD, 1.5), (None, None, 1), ("Ctrl", MOD, 1.5)],
]
# (label, key name, x, y, w, h) in key units, right of the main block.
NAV = [("PrtSc", "Print", 0, 0, 1, 1), ("Pause", "Pause", 2, 0, 1, 1),
       ("Ins", "Insert", 0, 1, 1, 1), ("Home", "Home", 1, 1, 1, 1), ("PgUp", "PageUp", 2, 1, 1, 1),
       ("Del", "Delete", 0, 2, 1, 1), ("End", "End", 1, 2, 1, 1), ("PgDn", "PageDown", 2, 2, 1, 1),
       ("↑", "Up", 1, 4, 1, 1), ("←", "Left", 0, 5, 1, 1), ("↓", "Down", 1, 5, 1, 1),
       ("→", "Right", 2, 5, 1, 1)]
KEYPAD = [("Num", OFF, 0, 1, 1, 1), ("/", "KeypadDivide", 1, 1, 1, 1),
          ("*", "KeypadMultiply", 2, 1, 1, 1), ("-", "KeypadMinus", 3, 1, 1, 1),
          ("7", "Keypad7", 0, 2, 1, 1), ("8", "Keypad8", 1, 2, 1, 1), ("9", "Keypad9", 2, 2, 1, 1),
          ("+", "KeypadPlus", 3, 2, 1, 2),
          ("4", "Keypad4", 0, 3, 1, 1), ("5", "Keypad5", 1, 3, 1, 1), ("6", "Keypad6", 2, 3, 1, 1),
          ("1", "Keypad1", 0, 4, 1, 1), ("2", "Keypad2", 1, 4, 1, 1), ("3", "Keypad3", 2, 4, 1, 1),
          ("Enter", "KeypadEnter", 3, 4, 1, 2),
          ("0", "Keypad0", 0, 5, 2, 1), (".", "KeypadDecimal", 2, 5, 1, 1)]

# What Shift turns each US-layout key into; Cherminal names shifted
# punctuation by the character it types, so Shift+1 is "Shift+!".
US_SHIFTED = dict(zip("`1234567890-=[]\\;',./", "~!@#$%^&*()_+{}|:\"<>?"))

GENERAL_ACTIONS = [("copy", "Copy"), ("paste", "Paste"), ("break", "Send Break"),
                   ("scroll-up", "Scroll back"), ("scroll-down", "Scroll forward"),
                   ("reset", "Reset terminal"), ("print-screen", "Print screen")]
IBM3270_ACTIONS = (
    [("enter", "Enter"), ("clear", "Clear"), ("reset", "Reset (unlock keyboard)"),
     ("newline", "New line"), ("tab", "Next field"), ("backtab", "Previous field"),
     ("home", "First input field"), ("field-end", "End of field"), ("insert", "Insert mode"),
     ("erase", "Erase left"), ("delete", "Delete"), ("erase-eof", "Erase to end of field"),
     ("erase-input", "Erase all input"), ("up", "Cursor up"), ("down", "Cursor down"),
     ("left", "Cursor left"), ("right", "Cursor right")]
    + [(f"pa{i}", f"PA{i}") for i in range(1, 4)]
    + [(f"pf{i}", f"PF{i}") for i in range(1, 25)]
    + [("copy", "Copy"), ("paste", "Paste"), ("print-screen", "Print screen")])

DEFAULT, PLAIN, SEND = "<default>", "<plain>", "<send>"

# Shorter names that fit on a key cap.
CAP_LABELS = {"reset": "Reset", "erase": "Erase", "tab": "Next fld", "backtab": "Prev fld",
              "home": "1st fld", "field-end": "End fld", "insert": "Insert",
              "erase-eof": "Erase EOF", "erase-input": "Erase inp", "newline": "New line",
              "up": "↑", "down": "↓", "left": "←", "right": "→", "scroll-up": "Scroll ↑",
              "scroll-down": "Scroll ↓", "break": "Break", "print-screen": "Print"}


def describe(value: str | None, labels: dict[str, str]) -> str:
    """Short text for a key cap: what the binding does."""
    if value is None:
        return ""
    if value.startswith("action:"):
        name = value[len("action:"):]
        if name.startswith("macro:"):
            return "▶ " + name[len("macro:"):]
        return labels.get(name, name)
    return format_notation(parse_notation(value))


class KeyboardEditor(QDialog):
    """Edit key overrides on a picture of the keyboard.

    ``base`` is the keymap without this session's overrides; ``overrides`` is
    the session's ``[keys]`` table. Read :attr:`overrides` after ``exec()``.
    """

    UNIT = 46

    def __init__(self, base: Keymap, overrides: dict[str, str], *, block_mode: bool = False,
                 macros: list[str] = (), store=None, base_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard map")
        self.base = base
        self.overrides = {normalize_key(k): v for k, v in overrides.items()}
        self.store, self.base_name = store, base_name
        actions = IBM3270_ACTIONS if block_mode else GENERAL_ACTIONS
        actions = actions + [(f"macro:{m}", f"Macro: {m}") for m in macros]
        self.actions = actions
        self.labels = dict(actions)
        self.mods = {"Ctrl": False, "Alt": False, "Shift": False}
        self.buttons: dict[str, QPushButton] = {}     # base key name -> button
        self.mod_buttons: list[tuple[str, QPushButton]] = []
        self.current: str | None = None                # full name, e.g. "Shift+F3"
        self._loading = False

        lay = QVBoxLayout(self)
        hint = QLabel("Click a key, then choose what it does. Latch Shift, Ctrl "
                      "or Alt on the picture to edit those combinations. Orange keys are "
                      "changed for this session; blue keys do something special by default.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addWidget(self._keyboard())
        lay.addWidget(self._editor())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        if store is not None:
            share = buttons.addButton("Save as keymap…", QDialogButtonBox.ButtonRole.ActionRole)
            share.clicked.connect(self._save_keymap)
        reset_all = buttons.addButton("Reset all", QDialogButtonBox.ButtonRole.ResetRole)
        reset_all.clicked.connect(self._reset_all)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._refresh()
        self.select("Enter")

    # ------------------------------------------------------------ picture

    def _keyboard(self) -> QWidget:
        u = self.UNIT
        board = QWidget()
        board.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        y = 0
        for r, row in enumerate(MAIN_ROWS):
            x = 0.0
            for label, name, width in row:
                if label is not None:
                    self._key(board, label, name, QRect(int(x * u), int(y), int(width * u) - 3,
                                                        u - 3))
                x += width
            y += u + (u // 3 if r == 0 else 0)
        top = u + u // 3
        for items, x0, y0 in ((NAV, 15.5, 0), (KEYPAD, 19, 0)):
            for label, name, x, ky, w, h in items:
                ytop = 0 if (items is NAV and ky == 0) else top + (ky - 1) * u
                self._key(board, label, name, QRect(int((x0 + x) * u), ytop,
                                                    int(w * u) - 3, int(h * u) - 3))
        board.setFixedSize(int(23.2 * u), top + 5 * u)
        return board

    def _key(self, parent, label: str, name: str, rect: QRect) -> None:
        b = QPushButton(parent)
        b.setGeometry(rect)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if name == MOD:
            b.setText(label)
            b.setCheckable(True)
            b.toggled.connect(lambda on, m=label: self._toggle_mod(m, on))
            self.mod_buttons.append((label, b))
        elif name == OFF:
            b.setText(label)
            b.setEnabled(False)
        else:
            b.setProperty("label", label)
            b.clicked.connect(lambda _=False, n=name: self.select(self._full(n)))
            self.buttons[name] = b

    def _toggle_mod(self, mod: str, on: bool) -> None:
        if self._loading:
            return
        self.mods[mod] = on
        self._loading = True
        for m, b in self.mod_buttons:        # left and right keys move together
            if m == mod:
                b.setChecked(on)
        self._loading = False
        self._refresh()
        if self.current:
            base = self.current.split("+")[-1] if not self.current.endswith("++") else "+"
            self.select(self._full(self._unshift(base)))

    @staticmethod
    def _unshift(base: str) -> str:
        for plain, shifted in US_SHIFTED.items():
            if base == shifted:
                return plain
        return base

    def _full(self, base: str) -> str:
        """The key name for ``base`` with the latched modifiers."""
        if self.mods["Shift"] and base in US_SHIFTED:
            base = US_SHIFTED[base]
        parts = [m for m in ("Ctrl", "Alt", "Shift") if self.mods[m]]
        return normalize_key("+".join(parts + [base]))

    def binding(self, name: str) -> tuple[str | None, bool]:
        """(value, overridden) for a full key name."""
        if name in self.overrides:
            return self.overrides[name] or None, True
        return self.base.bindings.get(name), False

    def _refresh(self) -> None:
        for base, b in self.buttons.items():
            name = self._full(base)
            value, overridden = self.binding(name)
            cap = b.property("label")
            short = describe(value, {**self.labels, **CAP_LABELS})
            b.setText(cap + ("\n" + short[:9] if value else ""))
            b.setToolTip(f"{name}: {describe(value, self.labels) or 'types its character'}"
                         + (" (changed)" if overridden else ""))
            border = "2px solid #000" if name == self.current else "1px solid #888"
            if overridden:
                bg = "#ffb347"
            elif value:
                bg = "#cfe3ff"
            else:
                bg = "#f4f4f4"
            b.setStyleSheet(f"QPushButton {{ background: {bg}; color: #000; border: {border};"
                            f" border-radius: 4px; font-size: 10px; }}")

    # --------------------------------------------------------------- editor

    def _editor(self) -> QGroupBox:
        box = QGroupBox("Selected key")
        f = QFormLayout(box)
        self.key_label = QLabel()
        self.key_label.setStyleSheet("font-weight: bold")
        self.default_label = QLabel()
        self.choice = QComboBox()
        self.choice.addItem("Default", DEFAULT)
        self.choice.addItem("Type its character (no special meaning)", PLAIN)
        self.choice.addItem("Send text or codes…", SEND)
        for value, label in self.actions:
            self.choice.addItem(label, "action:" + value)
        self.choice.currentIndexChanged.connect(self._changed)
        self.text = QLineEdit(placeholderText=r"e.g. \e[11~  or  ^AK\r  or  LOGON")
        self.text.textEdited.connect(self._changed)
        find = QPushButton("Find a key by pressing it…")
        find.clicked.connect(self._find_by_pressing)
        row = QHBoxLayout()
        row.addWidget(self.key_label)
        row.addStretch()
        row.addWidget(find)
        f.addRow("Key", row)
        f.addRow("Default", self.default_label)
        f.addRow("Does", self.choice)
        f.addRow("Sends", self.text)
        return box

    def select(self, name: str) -> None:
        self.current = name
        value, overridden = self.binding(name)
        default = self.base.bindings.get(name)
        self._loading = True
        self.key_label.setText(name)
        self.default_label.setText(describe(default, self.labels) or "types its character")
        if not overridden:
            self.choice.setCurrentIndex(0)
            self.text.setText("")
        elif value is None:
            self.choice.setCurrentIndex(self.choice.findData(PLAIN))
            self.text.setText("")
        elif value.startswith("action:"):
            idx = self.choice.findData(value)
            if idx < 0:
                self.choice.addItem(value[len("action:"):], value)
                idx = self.choice.count() - 1
            self.choice.setCurrentIndex(idx)
            self.text.setText("")
        else:
            self.choice.setCurrentIndex(self.choice.findData(SEND))
            self.text.setText(value)
        self.text.setEnabled(self.choice.currentData() == SEND)
        self._loading = False
        self._refresh()

    def _changed(self, *_) -> None:
        if self._loading or not self.current:
            return
        data = self.choice.currentData()
        self.text.setEnabled(data == SEND)
        if data == DEFAULT:
            self.overrides.pop(self.current, None)
        elif data == PLAIN:
            self.overrides[self.current] = ""
        elif data == SEND:
            value = self.text.text()
            try:
                Binding.parse(value)
            except ValueError:
                self.text.setStyleSheet("background: #ffd0d0")
                return
            self.text.setStyleSheet("")
            if value:
                self.overrides[self.current] = value
            else:
                self.overrides.pop(self.current, None)
        else:
            self.overrides[self.current] = data
        self._refresh()

    def _reset_all(self) -> None:
        self.overrides.clear()
        self.select(self.current or "Enter")

    def _save_keymap(self) -> None:
        name, ok = QInputDialog.getText(self, "Save as keymap",
                                        "Keymap name (lower-case letters, digits, -):")
        if not ok or not name.strip():
            return
        try:
            path = self.store.save_keymap(name.strip(), dict(self.overrides),
                                          inherit=self.base_name)
        except ValueError as e:
            QMessageBox.warning(self, "Save as keymap", str(e))
            return
        QMessageBox.information(self, "Save as keymap",
                                f"Saved {path.stem}. Choose it as the Keymap of any session, "
                                "or share it in a session file.")

    # ----------------------------------------------------------- keyboard

    def _find_by_pressing(self) -> None:
        from .dialogs import KeyCaptureDialog
        dlg = KeyCaptureDialog(self)
        if dlg.exec() and dlg.key:
            self.show_key(dlg.key)

    def show_key(self, name: str) -> None:
        """Select a key by its full name, latching the modifiers it uses."""
        name = normalize_key(name)
        parts = name[:-2].split("+") + ["+"] if name.endswith("++") else name.split("+")
        mods = set(parts[:-1])
        self._loading = True
        for m in self.mods:
            self.mods[m] = m in mods
        for m, b in self.mod_buttons:
            b.setChecked(self.mods[m])
        self._loading = False
        self.select(name)
