"""The search bar under the terminal: find text in the screen and scrollback."""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QKeyEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMenu, QToolButton, QWidget


class _Field(QLineEdit):
    """Enter searches up (towards older text), Shift+Enter down, Esc closes."""

    def __init__(self, bar: "SearchBar"):
        super().__init__(placeholderText="Search")
        self.bar = bar

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.bar.find(backwards=not event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        elif event.key() == Qt.Key.Key_Escape:
            self.bar.close_bar()
        else:
            super().keyPressEvent(event)


class SearchBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.term = None
        self.field = _Field(self)
        self.field.textChanged.connect(self._restart)
        up = QToolButton(toolTip="Search up (Enter)", autoRaise=True)
        up.setArrowType(Qt.ArrowType.UpArrow)
        up.clicked.connect(lambda: self.find(backwards=True))
        down = QToolButton(toolTip="Search down (Shift+Enter)", autoRaise=True)
        down.setArrowType(Qt.ArrowType.DownArrow)
        down.clicked.connect(lambda: self.find(backwards=False))
        self.result = QLabel()
        self.options = QToolButton(toolTip="Search options", autoRaise=True)
        icon = QIcon.fromTheme("configure", QIcon.fromTheme("preferences-system"))
        if icon.isNull():
            self.options.setText("⚙")
        else:
            self.options.setIcon(icon)
        self.options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.options)
        self.match_case = self._option(menu, "Match case")
        self.whole_word = self._option(menu, "Match whole word")
        self.regex = self._option(menu, "Regular expression")
        self.options.setMenu(menu)
        close = QToolButton(text="✕", toolTip="Close (Esc)", autoRaise=True)
        close.clicked.connect(self.close_bar)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addWidget(self.field, 1)
        for w in (up, down, self.result, self.options, close):
            lay.addWidget(w)
        self.hide()

    def _option(self, menu: QMenu, text: str) -> QAction:
        act = menu.addAction(text)
        act.setCheckable(True)
        act.toggled.connect(self._restart)
        return act

    def set_terminal(self, term) -> None:
        if self.term is not None and self.term is not term:
            self.term.clear_match()
        self.term = term

    def open(self) -> None:
        if self.term is not None:
            picked = self.term.selected_text()
            if picked and "\n" not in picked:
                self.field.setText(picked)
        self.show()
        self.field.setFocus()
        self.field.selectAll()

    def close_bar(self) -> None:
        self.hide()
        if self.term is not None:
            self.term.clear_match()
            self.term.setFocus()

    def _restart(self, *_) -> None:
        """New text or options: search again from the bottom of the view."""
        if self.term is not None:
            self.term.clear_match()
        if self.field.text():
            self.find(backwards=True)
        else:
            self._show_result("")

    def find(self, backwards: bool) -> bool:
        if self.term is None or not self.field.text():
            return False
        try:
            found = self.term.find(self.field.text(), backwards=backwards,
                                   case=self.match_case.isChecked(),
                                   whole=self.whole_word.isChecked(),
                                   regex=self.regex.isChecked())
        except re.error as e:
            self._show_result(f"Invalid expression: {e.msg}", error=True)
            return False
        self._show_result("" if found else "Not found", error=not found)
        return found

    def _show_result(self, text: str, error: bool = False) -> None:
        self.result.setText(text)
        self.field.setStyleSheet("QLineEdit { background: #ffd7d7; color: black; }"
                                 if error and self.field.text() else "")
