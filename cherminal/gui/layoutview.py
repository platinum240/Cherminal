"""Draws a screen through a custom layout (see :mod:`cherminal.layouts`).

The form is real widgets over the screen's card: a title, the screen's
input fields as text boxes, values in cards (money right-aligned, status
codes as coloured badges) and tables as tables. Typing in a box types into
the same 3270/5250 field; Enter, the function keys and the key bar work
as on the screen itself, so the host can't tell the difference.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QKeyEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..layouts import Entry, FormView, LayoutError
from .colors import ensure_contrast

TONES = {"good": (34, 139, 84), "warn": (178, 112, 0), "bad": (200, 52, 52),
         "info": (47, 107, 216), "muted": None}
# Keys that belong to the host, not the text box: they go to the terminal.
HOST_KEYS = {Qt.Key.Key_Escape, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Pause,
             Qt.Key.Key_Print, Qt.Key.Key_SysReq, Qt.Key.Key_Clear}


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(x * (1 - t) + y * t) for x, y in zip(a, b))


def _css(rgb) -> str:
    return "rgb({},{},{})".format(*rgb)


class FieldBox(QLineEdit):
    """A text box for one screen input field."""

    def __init__(self, form: LayoutView, entry: Entry):
        super().__init__()
        self.form = form
        self.field = entry.field
        self.setMaxLength(entry.field.length)
        if entry.field.hidden:
            self.setEchoMode(QLineEdit.EchoMode.Password)
        self.textEdited.connect(lambda text: form.term.layout_type(self.field, text))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.form.term.press_key("enter")
        elif key == Qt.Key.Key_Tab or key == Qt.Key.Key_Backtab:
            self.form.step_focus(self, key == Qt.Key.Key_Tab)
        elif (Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35 or key in HOST_KEYS
              or (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                  and key == Qt.Key.Key_K)):
            self.form.term.keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.form.term.layout_focus(self.field)


class LayoutView(QScrollArea):
    """The form for the current screen; rebuilt when the layout or the shape
    of the screen changes, otherwise only its text is updated."""

    def __init__(self, term):
        super().__init__(term)
        self.term = term
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._shape: tuple | None = None
        self._labels: list[tuple[QLabel, Entry]] = []
        self._boxes: list[FieldBox] = []
        self._tables: list[QTableWidget] = []
        self.hide()

    # ------------------------------------------------------------ colours

    def _theme(self) -> dict:
        c = self.term.colors
        fg, bg = c.fg, c.bg
        accent = ensure_contrast(c.cursor, bg, 3.0)
        return {"fg": fg, "bg": bg, "panel": _mix(bg, fg, 0.035), "line": _mix(bg, fg, 0.14),
                "label": ensure_contrast(_mix(bg, fg, 0.55), bg, 4.5), "accent": accent}

    def _style(self, t: dict) -> str:
        return f"""
        LayoutView, LayoutView > QWidget > QWidget#form {{ background: {_css(t['bg'])}; }}
        QWidget#form QLabel {{ color: {_css(t['fg'])}; background: transparent; }}
        QLabel#title {{ font-size: {self._pt(1.6)}pt; font-weight: 600; }}
        QLabel#sub, QLabel#label, QLabel#foot {{ color: {_css(t['label'])}; }}
        QLabel#cardtitle {{ color: {_css(t['label'])}; font-size: {self._pt(0.85)}pt;
                           font-weight: 600; }}
        QLabel#foot {{ font-size: {self._pt(0.85)}pt; }}
        QFrame#card {{ background: {_css(t['panel'])}; border: 1px solid {_css(t['line'])};
                      border-radius: 10px; }}
        QLineEdit {{ background: {_css(t['bg'])}; color: {_css(t['fg'])};
                    border: 1px solid {_css(t['line'])}; border-radius: 6px; padding: 4px 8px; }}
        QLineEdit:focus {{ border: 2px solid {_css(t['accent'])}; padding: 3px 7px; }}
        QTableWidget {{ background: transparent; color: {_css(t['fg'])}; border: none;
                       gridline-color: transparent;
                       selection-background-color: {_css(_mix(t['bg'], t['accent'], 0.18))};
                       selection-color: {_css(t['fg'])}; }}
        QTableWidget::item {{ border-bottom: 1px solid {_css(t['line'])}; padding: 4px 6px; }}
        QHeaderView {{ background: transparent; border: none; }}
        QHeaderView::section {{ background: transparent; color: {_css(t['label'])};
                               border: none; border-bottom: 1px solid {_css(t['line'])};
                               padding: 4px 6px; font-weight: 600; }}
        """

    def _pt(self, scale: float) -> str:
        return f"{self.font().pointSizeF() * scale:.1f}"

    def _badge(self, text: str, tone: str, t: dict) -> QWidget:
        rgb = TONES.get(tone)
        ink = ensure_contrast(rgb, t["panel"], 4.5) if rgb else t["label"]
        fill = _mix(t["panel"], rgb or t["label"], 0.14)
        b = QLabel(f"● {text.capitalize()}" if text else "")
        b.setStyleSheet(f"color: {_css(ink)}; background: {_css(fill)}; border-radius: 9px;"
                        " padding: 1px 9px; font-weight: 600;")
        cell = QWidget()                    # a pill the size of its text, not the column
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(b)
        lay.addStretch(1)
        return cell

    # ------------------------------------------------------------- build

    def show_form(self, form: FormView) -> None:
        shape = (form.layout.name, form.layout.source, len(form.header),
                 tuple((name, len(entries), tuple(e.field is not None for e in entries))
                       for name, entries in form.cards),
                 tuple(len(t.rows) for t in form.tables), self.term.colors)
        if shape != self._shape:
            self._shape = shape
            self._build(form)
        self._fill(form)
        self.show()

    def _build(self, form: FormView) -> None:
        t = self._theme()
        self.setStyleSheet(self._style(t))
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._mono = mono
        self._labels, self._boxes, self._tables = [], [], []
        page = QWidget(objectName="form")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        # Title, subtitle, and header fields (Customer no.) to the right.
        head = QHBoxLayout()
        names = QVBoxLayout()
        self._title = QLabel(objectName="title")
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        names.addWidget(self._title)
        self._sub = QLabel(objectName="sub")
        names.addWidget(self._sub)
        head.addLayout(names, 1)
        for entry in form.header:
            head.addWidget(QLabel(entry.label, objectName="label"))
            head.addWidget(self._value_widget(entry, t))
        lay.addLayout(head)
        # Cards of values, two to a row.
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (name, entries) in enumerate(form.cards):
            card = QFrame(objectName="card")
            body = QGridLayout(card)
            body.setContentsMargins(14, 12, 14, 12)
            body.setHorizontalSpacing(14)
            body.setVerticalSpacing(8)
            row = 0
            if name:
                body.addWidget(QLabel(name.upper(), objectName="cardtitle"), 0, 0, 1, 2)
                row = 1
            for entry in entries:
                body.addWidget(QLabel(entry.label, objectName="label"), row, 0)
                body.addWidget(self._value_widget(entry, t), row, 1)
                row += 1
            body.setColumnStretch(1, 1)
            grid.addWidget(card, i // 2, i % 2)
        lay.addLayout(grid)
        for table in form.tables:
            card = QFrame(objectName="card")
            body = QVBoxLayout(card)
            body.setContentsMargins(14, 12, 14, 12)
            if table.title:
                body.addWidget(QLabel(table.title.upper(), objectName="cardtitle"))
            body.addWidget(self._table(table))
            lay.addWidget(card)
        lay.addStretch(1)
        self._foot = QLabel(objectName="foot")
        lay.addWidget(self._foot)
        self.setWidget(page)

    def _value_widget(self, entry: Entry, t: dict) -> QWidget:
        if entry.field is not None:
            box = FieldBox(self, entry)
            box.setFont(self._mono)
            box.setMinimumWidth(box.fontMetrics().horizontalAdvance("M") * min(
                entry.field.length + 2, 40))
            self._boxes.append(box)
            return box
        label = QLabel()
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if entry.kind in ("money", "number"):
            label.setFont(self._mono)
        self._labels.append((label, entry))
        return label

    def _table(self, table) -> QTableWidget:
        w = QTableWidget(len(table.rows), len(table.columns))
        for c, column in enumerate(table.columns):
            head = QTableWidgetItem(column.name)
            right = column.kind in ("money", "number")
            head.setTextAlignment((Qt.AlignmentFlag.AlignRight if right else
                                   Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
            w.setHorizontalHeaderItem(c, head)
        w.verticalHeader().hide()
        w.setShowGrid(False)
        w.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        w.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        w.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        w.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        w.horizontalHeader().setHighlightSections(False)
        rows = [r for r, _ in table.rows]
        if table.select:
            w.setCursor(Qt.CursorShape.PointingHandCursor)
            w.setToolTip(f"Double-click a row to open it ({table.select[1]} and Enter)")
            w.cellClicked.connect(lambda r, _c: self.term.layout_row(rows[r], table.select))
            w.cellDoubleClicked.connect(
                lambda r, _c: self.term.layout_row(rows[r], table.select, send=True))
        self._tables.append(w)
        return w

    # -------------------------------------------------------------- fill

    def _fill(self, form: FormView) -> None:
        t = self._theme()
        title = form.title
        if title.isupper():
            title = title.title()           # HARGREAVES SUPPLY CO -> Hargreaves Supply Co
        self._title.setText(title)
        self._sub.setText(form.subtitle)
        self._sub.setVisible(bool(form.subtitle))
        entries = [e for e in form.header] + [e for _, es in form.cards for e in es]
        boxes = iter(self._boxes)
        labels = iter(self._labels)
        for entry in entries:
            if entry.field is not None:
                box = next(boxes)
                box.field = entry.field
                if not box.hasFocus() and box.text() != entry.text:
                    box.setText(entry.text)
            else:
                label, _ = next(labels)
                if entry.tone:
                    rgb = TONES.get(entry.tone)
                    ink = ensure_contrast(rgb, t["panel"], 4.5) if rgb else t["label"]
                    fill = _mix(t["panel"], rgb or t["label"], 0.14)
                    label.setText(f"● {entry.text.capitalize()}" if entry.text else "")
                    label.setStyleSheet(f"color: {_css(ink)}; background: {_css(fill)};"
                                        " border-radius: 9px; padding: 1px 9px;"
                                        " font-weight: 600;")
                    label.setMaximumWidth(label.sizeHint().width())
                else:
                    label.setText(entry.text)
                    if entry.kind == "money":
                        font = QFont(self._mono)
                        font.setBold(True)
                        label.setFont(font)
        for w, table in zip(self._tables, form.tables):
            for r, (_, cells) in enumerate(table.rows):
                for c, cell in enumerate(cells):
                    if cell.kind == "badge":
                        w.setCellWidget(r, c, self._badge(cell.text, cell.tone, t))
                        continue
                    item = w.item(r, c)
                    if item is None:
                        item = QTableWidgetItem()
                        w.setItem(r, c, item)
                    item.setText(cell.text)
                    if cell.kind in ("money", "number"):
                        item.setFont(self._mono)
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter)
            height = w.horizontalHeader().height() + sum(w.rowHeight(i)
                                                         for i in range(w.rowCount())) + 4
            w.setFixedHeight(height)
        source = form.layout.source or "a layout rule"
        self._foot.setText(f"Drawn from {source} · {form.layout.describe_match()}")

    # ------------------------------------------------------------ focus

    def step_focus(self, box: FieldBox, forward: bool) -> None:
        if not self._boxes:
            return
        i = self._boxes.index(box) if box in self._boxes else -1
        nxt = self._boxes[(i + (1 if forward else -1)) % len(self._boxes)]
        nxt.setFocus()
        nxt.selectAll()

    def focus_first(self) -> None:
        if self._boxes:
            self._boxes[0].setFocus()


class MakeLayoutDialog(QDialog):
    """Make layout from this screen: a starting rule to edit and save."""

    def __init__(self, term, text: str, parent=None):
        super().__init__(parent or term)
        self.term = term
        self.setWindowTitle("Make layout from this screen")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        intro = QLabel("A starting layout rule for this screen. Check how it recognises the "
                       "screen (match), rename the labels and pick kinds and badges, then "
                       "save it. Rows and columns count from 1. To share it, copy the file "
                       "to the layouts folder of a shared setup folder.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.name = QLineEdit(term.screen_title_text() or "new-layout")
        form.addRow("File name", self.name)
        lay.addLayout(form)
        self.text = QPlainTextEdit(text)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(self.text, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: rgb(200,52,52);")
        self.error.hide()
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.saved = None

    def save(self) -> None:
        try:
            self.saved = self.term.session.store.save_layout(self.name.text().strip()
                                                             or "new-layout",
                                                             self.text.toPlainText())
        except (LayoutError, OSError) as e:
            self.error.setText(f"Not saved: {e}")
            self.error.show()
            return
        self.accept()
