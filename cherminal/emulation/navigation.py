"""Finding your way round block-mode screens: titles, history and tables.

Modern view uses these for the breadcrumb above the screen, the history of
screens visited in this session, and copying a screen's table as CSV.

- :func:`screen_title` reads a screen's own title line ("Work with Active
  Jobs", "ISPF Primary Option Menu"), skipping panel ids, dates and times.
- :class:`Trail` turns the titles of the screens visited into a breadcrumb:
  going back to a screen already on the trail drops what came after it.
- :class:`ScreenHistory` keeps the screens of this session in memory, as the
  user last saw each one before pressing Enter or a PF key. Hidden fields
  (passwords) are blanked before a screen is kept, and nothing is written
  to disk.
- :func:`find_tables` finds column-aligned tables, and :func:`table_csv`
  writes one as CSV.

Kept free of Qt so it can be tested on sample screens, like :mod:`.choices`.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import NamedTuple

from ..screen import Cell
from .base import InputField

HISTORY_LIMIT = 50              # screens kept per session
TRAIL_LIMIT = 5                 # titles on the breadcrumb
TITLE_ROWS = 3                  # the title is on one of the first rows

# A chunk of text: words with single spaces between them.
_CHUNK = re.compile(r"\S+(?: \S+)*")
# Chunks on a title row that are not the title.
_NOISE = re.compile(r"""^(?:
      [\d/.:-]+(?:\s*[AP]M)?                    # 10/29/26, 15:09:41, 3:09 PM
    | (?:row|line|page|col(?:umn)?|record)\s+\d.*   # Row 1 of 20, Page 2
    | (?:more|bottom|top)\b.*                   # More: +, Bottom of data
    | (?:scroll|command|option)\b.*             # Scroll ===> PAGE
    | .*={2,}>.*
    )$""", re.IGNORECASE | re.VERBOSE)
# A rule between a table's header and its rows: dashes, equals signs.
_RULE = re.compile(r"^\s*[-=_*+|. ]*[-=]{3,}[-=_*+|. ]*$")
# Key and option hints: "F3=Exit", "2=Change", "PF7 = Back".
_HINT = re.compile(r"(?<!\S)(?:PF|F)?\w{1,2}\s?=\s?[A-Za-z]")


def _masked(lines: list[str], fields: list[InputField]) -> list[str]:
    """The screen's text with input fields blanked: a title is the host's text."""
    rows = [list(line) for line in lines]
    for f in fields:
        row = rows[f.row]
        for c in range(f.col, min(len(row), f.col + f.length)):
            row[c] = " "
    return ["".join(r) for r in rows]


def _tidy(title: str) -> str:
    title = title.strip(" .:-=*")
    letters = [c for c in title if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        title = title.capitalize()          # "CUSTOMER INQUIRY" -> "Customer inquiry"
    return title


def screen_title(lines: list[str], fields: list[InputField] = ()) -> str:
    """The screen's title, from the text on its first rows; "" if none stands out."""
    text = _masked(lines[:TITLE_ROWS], [f for f in fields if f.row < TITLE_ROWS])
    cols = max((len(t) for t in lines), default=80)
    best, best_score = "", 0.0
    for row, line in enumerate(text):
        for m in _CHUNK.finditer(line):
            chunk = m.group().strip(" .:-=*")
            letters = sum(c.isalpha() for c in chunk)
            if letters < 3 or _NOISE.match(chunk) or _HINT.search(chunk):
                continue
            words = len(chunk.split())
            score = min(len(chunk), 40) - 4 * row
            if words >= 2:
                score += 20
            if any(c.isdigit() for c in chunk):
                score -= 15                 # panel and system ids: ISR@PRIM, SYS0001
            middle = (m.start() + m.end()) / 2
            if abs(middle - cols / 2) < cols / 5:
                score += 10                 # titles are usually centred
            if score > best_score:
                best, best_score = chunk, score
    return _tidy(best)


class Trail:
    """The titles of the screens on the way to this one, for the breadcrumb."""

    def __init__(self, limit: int = TRAIL_LIMIT):
        self.limit = limit
        self.titles: list[str] = []

    def visit(self, title: str) -> None:
        if not title or (self.titles and self.titles[-1] == title):
            return
        if title in self.titles:            # back to an earlier screen (PF3, PF12)
            del self.titles[self.titles.index(title) + 1:]
        else:
            self.titles.append(title)
            del self.titles[:-self.limit]

    def clear(self) -> None:
        self.titles.clear()


@dataclass
class Snapshot:
    title: str
    when: float                     # time.time() when it was kept
    lines: list[list[Cell]]         # hidden fields blanked
    text: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, screen, fields: list[InputField], when: float) -> Snapshot:
        lines = [[Cell(" ", c.attr) if c.attr.invisible else Cell(c.char, c.attr)
                  for c in line] for line in screen.lines]
        text = ["".join(c.char for c in line) for line in lines]
        return cls(screen_title(text, fields), when, lines, text)

    @property
    def blank(self) -> bool:
        return not any(t.strip() for t in self.text)


class ScreenHistory:
    """This session's screens, oldest first, in memory only."""

    def __init__(self, limit: int = HISTORY_LIMIT):
        self.limit = limit
        self.items: list[Snapshot] = []

    def add(self, snap: Snapshot) -> None:
        if snap.blank:
            return
        if self.items and self.items[-1].text == snap.text:
            return                      # the same screen sent twice (Enter on an error)
        self.items.append(snap)
        del self.items[:-self.limit]

    def clear(self) -> None:
        self.items.clear()

    def __len__(self) -> int:
        return len(self.items)


def screen_text(lines: list[str]) -> str:
    """A screen as plain text, trailing blanks and blank last rows trimmed."""
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


# ------------------------------------------------------------------- tables


class Table(NamedTuple):
    top: int                        # row of the header
    bottom: int                     # last data row
    header: list[str]
    rows: list[list[str]]

    @property
    def size(self) -> int:
        return len(self.rows) * len(self.header)


def _table_row(line: str) -> bool:
    """Could this line be a row of a table: two or more chunks of text, and
    not a line of key or option hints or a command line?"""
    if len(_CHUNK.findall(line)) < 2 or "===>" in line or "-->" in line:
        return False
    return len(_HINT.findall(line)) < 2


def _spans(rows: list[str]) -> list[list[int]]:
    """Column spans [start, end): runs of positions where some row has text."""
    width = max((len(r) for r in rows), default=0)
    used = [any(i < len(r) and r[i] != " " for r in rows) for i in range(width)]
    spans, start = [], None
    for i, u in enumerate(used + [False]):
        if u and start is None:
            start = i
        elif not u and start is not None:
            spans.append([start, i])
            start = None
    return spans


def _table(lines: list[str], rows: list[int]) -> Table | None:
    head, data = rows[0], rows[1:]
    if len(data) < 2:
        return None
    body = [lines[r] for r in data]
    spans = _spans(body)
    # Rows of a table line up: their text falls into about as many columns
    # as the fullest row has chunks. Lines of loose text don't.
    if len(spans) > max(len(_CHUNK.findall(r)) for r in body) + 1:
        return None
    names: dict[int, list[str]] = {}
    for m in _CHUNK.finditer(lines[head]):
        start, end = m.start(), m.end()
        overlap = [(min(end, b) - max(start, a), i) for i, (a, b) in enumerate(spans)]
        size, i = max(overlap, default=(0, -1))
        if size <= 0:                   # a column the rows leave empty, e.g. "Opt"
            spans.append([start, end])
            i = len(spans) - 1
        names.setdefault(i, []).append(m.group())
    order = sorted(range(len(spans)), key=lambda i: spans[i][0])
    if len(order) < 2:
        return None
    header = [" ".join(names.get(i, [])) for i in order]
    cells = [[line[spans[i][0]:spans[i][1]].strip() for i in order] for line in body]
    return Table(head, data[-1], header, cells)


def find_tables(lines: list[str]) -> list[Table]:
    """Tables on a screen: a header row and two or more rows whose text lines
    up in columns. Hidden fields should already be blank in ``lines``."""
    tables, run = [], []
    for row, line in enumerate(lines + [""]):
        if _RULE.match(line) and line.strip():
            continue                    # a rule under the header doesn't end the table
        if _table_row(line):
            run.append(row)
            continue
        if len(run) >= 3:
            table = _table(lines, run)
            if table is not None:
                tables.append(table)
        run = []
    return tables


def _cell(value: str) -> str:
    """Keep a spreadsheet from running a value as a formula; -12.50 stays a number."""
    if value[:1] in ("=", "@", "\t", "\r") or (
            value[:1] in ("+", "-") and not re.fullmatch(r"[+-][\d.,]+", value)):
        return "'" + value
    return value


def table_csv(table: Table) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([_cell(v) for v in table.header])
    for row in table.rows:
        w.writerow([_cell(v) for v in row])
    return out.getvalue()
