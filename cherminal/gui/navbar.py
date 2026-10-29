"""Modern view's bar above the screen: the breadcrumb, and screen history.

On the live screen it shows where you are, from the screens' own titles
(``Main menu › Customer list › Customer inquiry``). Earlier steps open the
screen as it was when you left it. While a past screen is shown, the bar
steps through the history, copies the screen or its table, and goes back
to the live screen.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

STYLE = """
NavBar { border-bottom: 1px solid palette(mid); }
NavBar QToolButton { border: none; padding: 2px 4px; }
NavBar QToolButton:hover { text-decoration: underline; }
NavBar QLabel#sep { color: palette(placeholder-text); }
NavBar QLabel#here { font-weight: bold; }
NavBar QPushButton { padding: 2px 10px; }
"""


def _clock(when: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(when))


class NavBar(QWidget):
    def __init__(self, term):
        super().__init__(term)
        self.term = term
        self.setStyleSheet(STYLE)
        self.setAutoFillBackground(True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 3, 8, 3)
        self.lay.setSpacing(4)
        self._shown: tuple | None = None
        # A fixed height, so the screen below doesn't move as the bar changes.
        self.setFixedHeight(QPushButton("Ag").sizeHint().height() + 6)
        self.hide()

    def refresh(self) -> None:
        term = self.term
        if not term.modern:
            self.hide()
            return
        history = term.session.history.items
        if term.viewing is not None:
            snap = history[term.viewing]
            state = ("history", term.viewing, len(history), snap.title)
        else:
            state = ("live", tuple(term.trail.titles), len(history))
        if state != self._shown:
            self._shown = state
            self._clear()
            if state[0] == "history":
                self._history(term.viewing, history)
            else:
                self._crumbs(term.trail.titles, bool(history))
        self.show()

    def _clear(self) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()                    # gone now, not when Qt gets round to deleting it
                w.deleteLater()

    def _button(self, text: str, slot, tip: str = "", push: bool = False):
        b = QPushButton(text, self) if push else QToolButton(self, text=text)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(lambda _=False: slot())
        self.lay.addWidget(b)
        return b

    def _sep(self) -> None:
        self.lay.addWidget(QLabel("›", self, objectName="sep"))

    def _crumbs(self, titles: list[str], has_history: bool) -> None:
        term = self.term
        self.lay.addWidget(QLabel(term.session.profile.name, self))
        for i, title in enumerate(titles):
            self._sep()
            if i == len(titles) - 1:
                self.lay.addWidget(QLabel(title, self, objectName="here"))
            elif term.history_index(title) is not None:
                self._button(title, lambda t=title: term.view_history(term.history_index(t)),
                             f"Show {title} as you left it")
            else:
                self.lay.addWidget(QLabel(title, self))
        self.lay.addStretch(1)
        if has_history:
            self._button("History", lambda: term.view_history(-1),
                         "Screens from this session, kept in memory only")
        key = term.key_hint("palette")
        self._button(f"Go to…  {key}" if key else "Go to…", term.open_palette,
                     "Transactions, macros, screens and actions")

    def _history(self, index: int, history: list) -> None:
        term = self.term
        snap = history[index]
        older = self._button("‹", lambda: term.view_history(index - 1), "Older screen")
        older.setEnabled(index > 0)
        newer = self._button("›", lambda: term.view_history(index + 1), "Newer screen")
        newer.setEnabled(index < len(history) - 1)
        self.lay.addWidget(QLabel(f"{snap.title or 'Untitled screen'} · {_clock(snap.when)}"
                                  f" · {index + 1} of {len(history)}", self,
                                  objectName="here"))
        self.lay.addStretch(1)
        self._button("Copy screen text", term.copy_screen, push=True)
        csv = self._button("Export table as CSV", term.export_table, push=True)
        csv.setEnabled(bool(term.tables()))
        self._button("Back to live screen  Esc", term.view_live, push=True)
