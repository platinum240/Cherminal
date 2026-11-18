"""Split screen: up to four sessions side by side in one tab.

Panes fill a grid in reading order: two sit side by side, a third starts a
second row, and a fourth completes the 2 x 2 grid. Each row and the rows
themselves are splitters, so the user can drag the dividers. The pane last
clicked (or typed in) is the active one; the window's menus, status bar and
function keys follow it, and a thin highlight marks it while there is more
than one pane.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QSplitter, QVBoxLayout, QWidget

MAX_PANES = 4
COLUMNS = 2


class _Pane(QFrame):
    """A thin frame round one terminal that lights up when it is active."""

    def __init__(self, term: QWidget):
        super().__init__()
        self.term = term
        self.setObjectName("splitPane")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        lay.addWidget(term)
        term.show()                 # a terminal taken out of a tab comes hidden
        self.set_active(False, single=True)

    def set_active(self, active: bool, single: bool) -> None:
        if single:
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.setStyleSheet("")
            return
        self.layout().setContentsMargins(2, 2, 2, 2)
        colour = self.palette().highlight().color().name() if active else "transparent"
        self.setStyleSheet(f"#splitPane {{ border: 2px solid {colour}; }}")


class SplitView(QWidget):
    """One tab's worth of terminals, laid out in a grid of up to four."""

    active_changed = pyqtSignal(object)       # the TerminalWidget that now has focus

    def __init__(self, first: QWidget):
        super().__init__()
        self._panes: list[_Pane] = []
        self.active: QWidget | None = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._rows: QSplitter | None = None
        self._watcher = _FocusWatcher(self)
        self.add(first)

    # ------------------------------------------------------------- queries

    def terms(self) -> list[QWidget]:
        return [p.term for p in self._panes]

    def count(self) -> int:
        return len(self._panes)

    def can_split(self) -> bool:
        return self.count() < MAX_PANES

    def __contains__(self, term) -> bool:
        return any(p.term is term for p in self._panes)

    # ------------------------------------------------------------- changes

    def add(self, term: QWidget, after: QWidget | None = None) -> bool:
        """Add a pane (after ``after``, or at the end); False if the grid is full."""
        if not self.can_split():
            return False
        pane = _Pane(term)
        idx = self._index(after) + 1 if after is not None and after in self else len(self._panes)
        self._panes.insert(idx, pane)
        term.installEventFilter(self._watcher)
        self._relayout()
        self.set_active(term)
        return True

    def remove(self, term: QWidget) -> None:
        """Take a pane out; the terminal is the caller's to shut down."""
        if term not in self:
            return
        idx = self._index(term)
        pane = self._panes.pop(idx)
        term.removeEventFilter(self._watcher)
        term.setParent(None)
        pane.setParent(None)
        pane.deleteLater()
        self._relayout()
        if self._panes:
            nxt = self._panes[min(idx, len(self._panes) - 1)].term
            self.set_active(nxt)
            nxt.setFocus()
        else:
            self.active = None

    def replace(self, old: QWidget, new: QWidget) -> None:
        """Put a new terminal where an old one was (reconnect, edited session)."""
        if old not in self:
            return
        idx = self._index(old)
        old.removeEventFilter(self._watcher)
        old.setParent(None)
        self._panes[idx].setParent(None)
        self._panes[idx].deleteLater()
        self._panes[idx] = _Pane(new)
        new.installEventFilter(self._watcher)
        self._relayout()
        self.set_active(new)

    def set_active(self, term: QWidget) -> None:
        if term not in self:
            return
        changed = term is not self.active
        self.active = term
        single = len(self._panes) == 1
        for p in self._panes:
            p.set_active(p.term is term, single)
        if changed:
            self.active_changed.emit(term)

    def focus_next(self, step: int = 1) -> None:
        """Move to the next (or previous) pane."""
        if len(self._panes) > 1 and self.active is not None:
            nxt = self._panes[(self._index(self.active) + step) % len(self._panes)].term
            self.set_active(nxt)
            nxt.setFocus()

    # ------------------------------------------------------------ internals

    def _index(self, term) -> int:
        return next(i for i, p in enumerate(self._panes) if p.term is term)

    def _relayout(self) -> None:
        """Rebuild the splitters for the current number of panes."""
        old = self._rows
        for p in self._panes:
            p.setParent(None)
        rows = QSplitter(Qt.Orientation.Vertical)
        rows.setChildrenCollapsible(False)
        for start in range(0, len(self._panes), COLUMNS):
            row = QSplitter(Qt.Orientation.Horizontal)
            row.setChildrenCollapsible(False)
            for p in self._panes[start:start + COLUMNS]:
                row.addWidget(p)
                p.show()
            rows.addWidget(row)
        # Even shares; the user can drag the dividers afterwards.
        rows.setSizes([1000] * rows.count())
        for i in range(rows.count()):
            row = rows.widget(i)
            row.setSizes([1000] * row.count())
        self._lay.addWidget(rows)
        self._rows = rows
        if old is not None:
            old.setParent(None)
            old.deleteLater()
        single = len(self._panes) == 1
        for p in self._panes:
            p.set_active(p.term is self.active, single)


class _FocusWatcher(QObject):
    """Marks a pane active when its terminal gets the keyboard focus."""

    def __init__(self, view: SplitView):
        super().__init__(view)
        self.view = view

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.FocusIn:
            self.view.set_active(obj)
        return False
