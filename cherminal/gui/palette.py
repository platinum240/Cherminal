"""The command palette (Ctrl+K, ⌘K on a Mac) for IBM 3270 and 5250 tabs.

A search box over the screen that finds transactions and macros, the keys
the screen lists, screens visited in this session, and Cherminal's own
actions. Choosing a transaction types it the way a person would; nothing
here sends anything the user couldn't send from the keyboard.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
)

SECTIONS = ("Transactions", "Macros", "Keys on this screen", "Recent screens", "Actions")
RECENT_SHOWN = 6                # recent screens listed before anything is typed


class Item(NamedTuple):
    section: str
    label: str
    detail: str
    run: Callable[[], None]


def rank(query: str, item: Item) -> int | None:
    """How well ``item`` matches ``query``, lower is better; None if it doesn't.
    Every word typed must appear in the label or detail."""
    words = query.lower().split()
    label, detail = item.label.lower(), item.detail.lower()
    text = f"{label} {detail}"
    if not all(w in text for w in words):
        return None
    if not words:
        return 3
    first = words[0]
    if label.startswith(first):
        return 0
    if any(part.startswith(first) for part in label.split()):
        return 1
    return 2


def matches(query: str, items: list[Item]) -> list[Item]:
    """The items to list for ``query``, by section, best matches first."""
    order = {name: i for i, name in enumerate(SECTIONS)}
    found = []
    shown: dict[str, int] = {}
    for n, item in enumerate(items):
        score = rank(query, item)
        if score is None:
            continue
        if not query.strip() and item.section == "Recent screens":
            shown[item.section] = shown.get(item.section, 0) + 1
            if shown[item.section] > RECENT_SHOWN:
                continue
        found.append((order.get(item.section, len(order)), score, n, item))
    return [item for *_, item in sorted(found, key=lambda f: f[:3])]


STYLE = """
CommandPalette { background: palette(window); border: 1px solid palette(mid);
                 border-radius: 8px; }
CommandPalette QLineEdit { padding: 6px 8px; font-size: 115%; }
CommandPalette QListWidget { border: none; background: transparent; }
CommandPalette QToolButton { border: none; padding: 4px 8px; font-size: 115%; }
"""


class CommandPalette(QFrame):
    """A search box and a list, shown over the top of a terminal. Esc, the ✕
    or a click anywhere outside it closes it; that click goes no further,
    so it never presses a button or moves the cursor behind the palette."""

    def __init__(self, term, items: list[Item]):
        super().__init__(term)
        self._closing = False               # closed by a click: swallow its release too
        self.term = term
        self.items = items
        self.setStyleSheet(STYLE)
        self.field = QLineEdit(placeholderText="Search transactions, macros, screens and "
                                               "actions")
        self.field.setClearButtonEnabled(True)
        self.field.textChanged.connect(self._fill)
        self.field.installEventFilter(self)
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.itemClicked.connect(lambda it: self._run(it))
        close = QToolButton(text="✕", toolTip="Close (Esc)")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(lambda: self.close_palette())
        top = QHBoxLayout()
        top.addWidget(self.field, 1)
        top.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(top)
        lay.addWidget(self.list)
        QApplication.instance().installEventFilter(self)
        self._fill("")
        self._place()
        self.show()
        self.raise_()
        self.field.setFocus()

    def _place(self) -> None:
        width = min(560, max(240, self.term.width() - 32))
        rows = max(1, self.list.count())
        wanted = (self.field.sizeHint().height() + rows * max(16, self.list.sizeHintForRow(0))
                  + 32)
        height = min(wanted, 420, max(120, self.term.height() - 48))
        self.setGeometry((self.term.width() - width) // 2, 24, width, height)

    def _fill(self, query: str) -> None:
        self.list.clear()
        section = None
        for item in matches(query, self.items):
            if item.section != section:
                section = item.section
                head = QListWidgetItem(section)
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                font = head.font()
                font.setBold(True)
                head.setFont(font)
                self.list.addItem(head)
            row = QListWidgetItem(f"{item.label}    {item.detail}" if item.detail
                                  else item.label)
            row.setData(Qt.ItemDataRole.UserRole, item)
            self.list.addItem(row)
        self._step(1, from_top=True)
        if self.list.count() == 0:
            empty = QListWidgetItem("Nothing matches")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        if self.isVisible():
            self._place()

    def _step(self, delta: int, from_top: bool = False) -> None:
        """Move the highlight to the next choosable row, skipping headings."""
        n = self.list.count()
        row = -1 if from_top else self.list.currentRow()
        for _ in range(n):
            row += delta
            if not 0 <= row < n:
                return
            if self.list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.list.setCurrentRow(row)
                return

    def chosen(self) -> Item | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def eventFilter(self, obj, event) -> bool:
        if obj is self.field and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._step(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run(self.list.currentItem())
                return True
            if key == Qt.Key.Key_Escape:
                self.close_palette()
                return True
        kind = event.type()
        if self._closing:
            if kind == QEvent.Type.MouseButtonRelease:
                self._finish()
                return True                 # the rest of the click that closed it
            return False
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick) \
                and not self._inside(event.globalPosition().toPoint()):
            self.close_palette(click=True)
            return True
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.close_palette()            # Esc wherever the focus is
            return True
        return super().eventFilter(obj, event)

    def _inside(self, global_pos) -> bool:
        return self.isVisible() and self.rect().contains(self.mapFromGlobal(global_pos))

    def _run(self, it: QListWidgetItem | None) -> None:
        item = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
        if item is None:
            return
        self.close_palette()
        item.run()

    def close_palette(self, click: bool = False) -> None:
        if self._closing:
            return
        self.hide()
        if self.term.command_palette is self:
            self.term.command_palette = None
        self.term.setFocus()
        if click:
            self._closing = True            # wait for the mouse button to come up
        else:
            self._finish()

    def _finish(self) -> None:
        QApplication.instance().removeEventFilter(self)
        self._closing = False
        self.deleteLater()
