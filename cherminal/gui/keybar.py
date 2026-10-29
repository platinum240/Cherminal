"""Modern view key bar: the keys a 3270/5250 screen lists, as buttons.

Panels list their keys as text on the last rows (``F3=Exit  F7=Back``).
The bar under the screen turns them into buttons named in words, with the
keyboard key beside each, plus Send (Enter) and a More keys menu for the
keys a screen never lists: PA1, Clear, Attention, SysReq and so on.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from ..emulation.hotspots import ScreenKey

# Keys a screen rarely lists, by emulation family: (action, name).
MORE_KEYS = {
    "ibm3270": [("pa1", "PA1"), ("pa2", "PA2"), ("pa3", "PA3"), ("clear", "Clear"),
                ("erase-input", "Erase input"), ("reset", "Reset")],
    "ibm5250": [("help", "Help"), ("attn", "Attention"), ("sysreq", "System request"),
                ("print", "Print"), ("roll-down", "Roll down"), ("roll-up", "Roll up"),
                ("clear", "Clear"), ("erase-input", "Erase input"), ("reset", "Reset")],
}

STYLE = """
KeyBar { border-top: 1px solid palette(mid); }
KeyBar QPushButton { padding: 0; min-height: 26px; }
KeyBar QPushButton#more { padding: 0 22px 0 10px; }
KeyBar QPushButton#send { background: palette(highlight); color: palette(highlighted-text);
                          border: 1px solid palette(highlight); border-radius: 4px; }
KeyBar QPushButton#send QLabel { color: palette(highlighted-text); }
KeyBar QLabel#hint { border: 1px solid palette(mid); border-radius: 3px; padding: 0 4px;
                     color: palette(placeholder-text); font-size: 85%; }
KeyBar QPushButton#send QLabel#hint { border-color: palette(highlighted-text); }
"""


def key_name(action: str) -> str:
    """What to call a key the screen names without a label: "PF3", "PA1", "Clear"."""
    if action[:2] in ("pf", "pa"):
        return action.upper()
    return action.replace("-", " ").capitalize()


class KeyButton(QPushButton):
    """A button with the key's name and, beside it, the keyboard key."""

    def __init__(self, label: str, hint: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 3, 8, 3)
        lay.setSpacing(8)
        self.label = QLabel(label)
        lay.addWidget(self.label)
        self.hint = QLabel(hint, objectName="hint")
        self.hint.setVisible(bool(hint))
        lay.addWidget(self.hint)
        for w in (self.label, self.hint):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumSize(lay.sizeHint())
        # Keys keep going to the terminal; a button never takes the focus.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class KeyBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.term = None
        self._shown: tuple | None = None        # what the buttons were built from
        self.setStyleSheet(STYLE)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 6, 8, 6)
        self.lay.setSpacing(6)
        self.hide()

    def set_terminal(self, term) -> None:
        if self.term is not None:
            try:
                self.term.screen_changed.disconnect(self.refresh)
            except TypeError:
                pass
        self.term = term
        self._shown = None
        if term is not None:
            term.screen_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        term = self.term
        if term is None or not term.modern:
            self.hide()
            return
        keys = term.screen_keys()
        state = (tuple(keys), term.session.emulation.family)
        if state != self._shown:
            self._shown = state
            self._build(keys, term.session.emulation.family)
        self.show()

    def _build(self, keys: list[ScreenKey], family: str) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()                    # gone now, not when Qt gets round to deleting it
                w.deleteLater()
        for key in keys:
            self.lay.addWidget(self._button(key.label or key_name(key.action), key.action))
        more = QPushButton("More keys", self, objectName="more")
        more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        menu = QMenu(more)
        listed = {k.action for k in keys}
        for action, name in MORE_KEYS.get(family, []):
            if action in listed:
                continue
            hint = self.term.key_hint(action)
            act = menu.addAction(f"{name}\t{hint}" if hint else name)
            act.triggered.connect(lambda _=False, a=action: self._press(a))
        pf = menu.addMenu("PF keys" if family == "ibm3270" else "Function keys")
        for n in range(1, 25):
            action = f"pf{n}"
            hint = self.term.key_hint(action)
            name = f"PF{n}" if family == "ibm3270" else f"F{n}"
            act = pf.addAction(f"{name}\t{hint}" if hint else name)
            act.triggered.connect(lambda _=False, a=action: self._press(a))
        more.setMenu(menu)
        self.lay.addWidget(more)
        self.lay.addStretch(1)
        send = self._button("Send", "enter")
        send.setObjectName("send")
        self.lay.addWidget(send)

    def _button(self, label: str, action: str) -> KeyButton:
        b = KeyButton(label, self.term.key_hint(action), self)
        b.setToolTip(f"Press {key_name(action)}" if action != "enter" else "Press Enter")
        b.clicked.connect(lambda _=False, a=action: self._press(a))
        return b

    def _press(self, action: str) -> None:
        if self.term is not None:
            self.term.press_key(action)
