"""Menu options and selectable table rows on block-mode screens.

Modern view makes two common panel layouts clickable:

- **Menus**: lines that start with an option number (``1  Browse``,
  ``2. Work with jobs``) on a screen with an ``Option ===>`` style input
  field. Clicking one types its number into that field.
- **Lists**: rows that start with a short input field, the "Sel" or "Opt"
  column, followed by text. Clicking a row puts the cursor in its field;
  double-clicking types the screen's own select code (``S``, ``1=Select``,
  ``5=Display``) and presses Enter.

Kept free of Qt so it can be tested on sample screens, like
:mod:`.hotspots`. Nothing here is sent anywhere: the terminal turns a
choice into the same keys a person would type.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from .base import InputField


class MenuOption(NamedTuple):
    row: int
    start: int          # first column of the option number
    end: int            # one past the end of its text
    code: str           # what to type, e.g. "2"


class ListRow(NamedTuple):
    row: int
    start: int
    end: int
    field: InputField   # the selection field at the start of the row


class Choices(NamedTuple):
    options: list[MenuOption]
    command: InputField | None      # where an option number is typed
    rows: list[ListRow]
    select: str                     # the code that opens a row; "" if none is safe

    def at(self, row: int, col: int) -> MenuOption | ListRow | None:
        for item in (*self.options, *self.rows):
            if item.row == row and item.start <= col < item.end:
                return item
        return None


NONE = Choices([], None, [], "")

# Text just before an option field: "Option ===>", "Selection or command",
# "COMMAND ==>", or a bare "===>" (IBM i puts the words on the line above).
_PROMPT = re.compile(r"(?:={2,}>|-{2,}>|\b(?:option|selection|command|choice)\b[\s.:]*)\s*$",
                     re.IGNORECASE)
# "  1  Settings", " 2. Work with jobs": one or two digits, then a word.
_OPTION = re.compile(r"^(\s{0,12})(\d{1,2})\.?\s{1,8}(?=[A-Za-z])")
# Codes that only look at a row. Never one that changes or deletes it.
_SAFE_WORDS = ("select", "display", "view", "browse", "open", "show")
_CODE_EQ = re.compile(r"(?<![\w=])([A-Za-z0-9])\s*=\s*([A-Za-z]+)")
# "Type S beside an order to view it": only when the sentence says it looks.
_TYPE_CODE = re.compile(r"\b(?:type|enter|put)\s+(?:an?\s+)?['\"]?([A-Za-z0-9])['\"]?\s+"
                        r"(?:beside|next to|by|in front of|on|against)\b[^.\n]*?"
                        r"\b(?:select|view|display|browse|open|show)", re.IGNORECASE)
MAX_SELECT_WIDTH = 2        # a "Sel" column is one or two characters wide
MAX_SELECT_COL = 8          # and sits at the left of the row


def find_choices(lines: list[str], fields: list[InputField]) -> Choices:
    """The menu options and list rows on a screen, given its text and input fields."""
    field_rows = {f.row for f in fields}
    command = next((f for f in fields if f.length >= 2
                    and _PROMPT.search(lines[f.row][:f.col])), None)

    options = []
    if command is not None:
        for row, text in enumerate(lines):
            if row in field_rows:
                continue
            m = _OPTION.match(text)
            if m:
                options.append(MenuOption(row, m.start(2), len(text.rstrip()), m.group(2)))
        if len(options) < 2 or len({o.code for o in options}) != len(options):
            options = []

    rows = []
    for f in fields:
        if f.length > MAX_SELECT_WIDTH or f.col > MAX_SELECT_COL:
            continue
        text = lines[f.row]
        rest = text[f.col + f.length:]
        if rest.strip():
            rows.append(ListRow(f.row, f.col, len(text.rstrip()), f))
    if len(rows) < 2:
        rows = []
    return Choices(options, command, rows, select_code("\n".join(lines)) if rows else "")


def select_code(text: str) -> str:
    """The code a screen says opens a row: ``1=Select``, ``5=Display``,
    ``Type S beside an order to view it``. "" when the screen only offers codes that change
    things (2=Change, 4=Delete), so a double-click never does that."""
    found = {}
    for m in _CODE_EQ.finditer(text):
        word = m.group(2).lower()
        if word in _SAFE_WORDS and word not in found:
            found[word] = m.group(1).upper()
    for word in _SAFE_WORDS:
        if word in found:
            return found[word]
    m = _TYPE_CODE.search(text)
    return m.group(1).upper() if m else ""
