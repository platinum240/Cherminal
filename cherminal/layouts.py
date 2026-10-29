"""Custom layouts: rules that redraw a known 3270/5250 screen as a form.

A layout rule recognises a screen by text at known positions, then says how
to draw it: a title, labelled values (money as money, status codes as
coloured badges), the screen's input fields as boxes, and its tables as
tables. Rules are TOML files in a ``layouts`` folder, the user's own or a
shared setup folder's, like sessions and keymaps::

    # layouts/customer-inquiry.toml
    [screen]
    name = "Customer inquiry"
    match = [{ row = 1, col = 2, text = "CUST01" }]
    title = { row = 5, col = 22, len = 30 }       # the customer name

    [[field]]
    label = "Customer no."
    at = { row = 4, col = 22, len = 10 }
    place = "header"

    [[value]]
    label = "Account status"
    at = { row = 9, col = 22, len = 8 }
    badges = { ACTIVE = "good", HOLD = "warn", CLOSED = "muted" }

    [[table]]
    rows = "12-15"
    select = { col = 3, action = "S" }
    columns = ["Order", "Date", "Amount:money", "Status:badge"]

Rows and columns count from 1, as on the status line. A rule only changes
what is drawn: the host gets the same keys and field data either way, and a
screen no rule matches keeps the generic Modern view.

Kept free of Qt so rules can be tested on sample screens.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .emulation.base import InputField
from .emulation.choices import select_code
from .emulation.navigation import _CHUNK, _spans, find_tables, screen_title

KINDS = ("text", "money", "number", "badge")
TONES = ("good", "warn", "bad", "info", "muted")
PLACES = ("header", "body")


class LayoutError(ValueError):
    pass


@dataclass(frozen=True)
class Pos:
    row: int                    # 1-based
    col: int                    # 1-based
    len: int

    def read(self, lines: list[str]) -> str:
        if not 0 < self.row <= len(lines):
            return ""
        return lines[self.row - 1][self.col - 1:self.col - 1 + self.len].strip()


@dataclass(frozen=True)
class Match:
    row: int
    text: str
    col: int = 0                # 0: anywhere on the row

    def found(self, lines: list[str]) -> bool:
        if not 0 < self.row <= len(lines):
            return False
        line = lines[self.row - 1]
        if self.col:
            return line[self.col - 1:self.col - 1 + len(self.text)] == self.text
        return self.text in line


@dataclass(frozen=True)
class Item:
    """A [[field]] (typed into) or [[value]] (read only) on the form."""
    label: str
    at: Pos
    editable: bool
    place: str = "body"         # "header": beside the title
    card: str = ""              # cards group values; "" = the first card
    kind: str = "text"
    badges: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Column:
    name: str
    kind: str = "text"
    col: int = 0                # 0: found from where the rows' text lines up
    len: int = 0


@dataclass(frozen=True)
class TableRule:
    first: int                  # 1-based screen rows, inclusive
    last: int
    columns: list[Column]
    title: str = ""
    select: tuple[int, str] | None = None     # (1-based column of the field, code)
    badges: dict = field(default_factory=dict)


@dataclass
class Layout:
    name: str
    match: list[Match]
    title: Pos | None = None
    subtitle: Pos | None = None
    items: list[Item] = field(default_factory=list)
    tables: list[TableRule] = field(default_factory=list)
    session: str = ""           # only for the session with this name; "" = any
    source: str = ""            # the file it came from, for the footnote

    def matches(self, lines: list[str], session: str = "") -> bool:
        if self.session and self.session != session:
            return False
        return bool(self.match) and all(m.found(lines) for m in self.match)

    def describe_match(self) -> str:
        m = self.match[0]
        return f"matched {m.text} at row {m.row}"


# --------------------------------------------------------------- reading


def _int(data: dict, key: str, where: str, low: int = 1) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < low:
        raise LayoutError(f"{where}: {key} must be a whole number, {low} or more")
    return value


def _pos(data, where: str) -> Pos:
    if not isinstance(data, dict):
        raise LayoutError(f"{where} must look like {{ row = 4, col = 22, len = 10 }}")
    return Pos(_int(data, "row", where), _int(data, "col", where), _int(data, "len", where))


def _badges(data, where: str) -> dict:
    if not isinstance(data, dict):
        raise LayoutError(f"{where}: badges must look like {{ ACTIVE = \"good\" }}")
    bad = [t for t in data.values() if t not in TONES]
    if bad:
        raise LayoutError(f"{where}: badge colours are {', '.join(TONES)}, not {bad[0]!r}")
    return {str(k).strip().upper(): v for k, v in data.items()}


def _kind(value: str, where: str) -> str:
    if value not in KINDS:
        raise LayoutError(f"{where}: kind must be one of {', '.join(KINDS)}")
    return value


def _column(spec, where: str) -> Column:
    if isinstance(spec, str):               # "Amount:money"
        name, _, kind = spec.partition(":")
        return Column(name.strip(), _kind(kind.strip() or "text", where))
    if isinstance(spec, dict) and isinstance(spec.get("name"), str):
        col = _int(spec, "col", where) if "col" in spec else 0
        length = _int(spec, "len", where) if "len" in spec else 0
        if bool(col) != bool(length):
            raise LayoutError(f"{where}: give a column both col and len, or neither")
        return Column(spec["name"], _kind(spec.get("kind", "text"), where), col, length)
    raise LayoutError(f"{where}: a column is \"Name\", \"Name:kind\" or "
                      "{ name = \"Name\", col = 8, len = 10 }")


def _rows(value, where: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", str(value))
    if not m:
        raise LayoutError(f"{where}: rows must look like \"12-15\"")
    first, last = int(m.group(1)), int(m.group(2) or m.group(1))
    if not 0 < first <= last:
        raise LayoutError(f"{where}: rows must run from a smaller to a larger row number")
    return first, last


def parse(data: dict, source: str = "") -> Layout:
    """A layout from a rule file's TOML data; LayoutError says what is wrong."""
    where = source or "layout"
    known = {"screen", "field", "value", "table"}
    if set(data) - known:
        raise LayoutError(f"{where}: unknown section(s) {', '.join(sorted(set(data) - known))}")
    screen = data.get("screen")
    if not isinstance(screen, dict) or not isinstance(screen.get("name"), str):
        raise LayoutError(f"{where}: needs a [screen] with a name")
    match = []
    for i, m in enumerate(screen.get("match", [])):
        w = f"{where}: match {i + 1}"
        if not isinstance(m, dict) or not isinstance(m.get("text"), str) or not m["text"]:
            raise LayoutError(f"{w} must look like {{ row = 1, col = 2, text = \"CUST01\" }}")
        match.append(Match(_int(m, "row", w), m["text"],
                           _int(m, "col", w) if "col" in m else 0))
    if not match:
        raise LayoutError(f"{where}: [screen] needs match = [...] to recognise the screen")
    layout = Layout(screen["name"], match, source=Path(source).name if source else "",
                    session=str(screen.get("session", "")))
    if "title" in screen:
        layout.title = _pos(screen["title"], f"{where}: title")
    if "subtitle" in screen:
        layout.subtitle = _pos(screen["subtitle"], f"{where}: subtitle")
    for section, editable in (("field", True), ("value", False)):
        for i, spec in enumerate(data.get(section, [])):
            w = f"{where}: {section} {i + 1}"
            if not isinstance(spec, dict) or not isinstance(spec.get("label"), str):
                raise LayoutError(f"{w} needs a label")
            place = spec.get("place", "body")
            if place not in PLACES:
                raise LayoutError(f"{w}: place must be header or body")
            layout.items.append(Item(
                spec["label"], _pos(spec.get("at"), f"{w}: at"), editable, place,
                str(spec.get("card", "")), _kind(spec.get("kind", "text"), w),
                _badges(spec.get("badges", {}), w)))
    for i, spec in enumerate(data.get("table", [])):
        w = f"{where}: table {i + 1}"
        if not isinstance(spec, dict) or "rows" not in spec or not spec.get("columns"):
            raise LayoutError(f"{w} needs rows = \"12-15\" and columns = [...]")
        first, last = _rows(spec["rows"], w)
        select = None
        if "select" in spec:
            sel = spec["select"]
            if not isinstance(sel, dict) or not isinstance(sel.get("action"), str):
                raise LayoutError(f"{w}: select must look like {{ col = 3, action = \"S\" }}")
            select = (_int(sel, "col", w), sel["action"])
        layout.tables.append(TableRule(first, last, [_column(c, w) for c in spec["columns"]],
                                       str(spec.get("title", "")), select,
                                       _badges(spec.get("badges", {}), w)))
    return layout


def load(path: Path) -> Layout:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise LayoutError(f"{path.name}: {e}") from e
    return parse(data, str(path))


def find(layouts: list[Layout], lines: list[str], session: str = "") -> Layout | None:
    """The first rule that matches the screen."""
    return next((lay for lay in layouts if lay.matches(lines, session)), None)


# --------------------------------------------------------------- drawing


@dataclass
class Entry:
    label: str
    text: str
    kind: str
    tone: str = ""              # a badge's colour, "" if not a badge
    field: InputField | None = None   # editable: the screen field it types into


@dataclass
class Cell:
    text: str
    kind: str
    tone: str = ""


@dataclass
class TableView:
    title: str
    columns: list[Column]
    rows: list[tuple[int, list[Cell]]]        # (0-based screen row, cells)
    select: tuple[int, str] | None


@dataclass
class FormView:
    """What a layout shows for one screen: everything the painter needs."""
    layout: Layout
    title: str
    subtitle: str
    header: list[Entry]
    cards: list[tuple[str, list[Entry]]]
    tables: list[TableView]


def _tone(text: str, badges: dict, kind: str) -> str:
    if badges:
        return badges.get(text.upper(), "muted" if kind == "badge" else "")
    return "info" if kind == "badge" and text else ""


def _field_at(fields: list[InputField], pos: Pos) -> InputField | None:
    row, col = pos.row - 1, pos.col - 1
    return next((f for f in fields if f.row == row and f.col <= col < f.col + f.length), None)


def _cells(rule: TableRule, lines: list[str], fields: list[InputField]) -> list[tuple[int, list]]:
    rows = [r - 1 for r in range(rule.first, rule.last + 1) if r - 1 < len(lines)]
    text = {}
    for r in rows:
        line = list(lines[r])
        if rule.select:                     # the selection field isn't a column
            sel = _field_at(fields, Pos(r + 1, rule.select[0], 1))
            start, end = (sel.col, sel.col + sel.length) if sel else (rule.select[0] - 1,
                                                                       rule.select[0])
            for c in range(start, min(end, len(line))):
                line[c] = " "
        text[r] = "".join(line)
    rows = [r for r in rows if text[r].strip()]
    explicit = all(c.col for c in rule.columns)
    spans = _spans([text[r] for r in rows])
    out = []
    for r in rows:
        line = text[r]
        if explicit:
            values = [line[c.col - 1:c.col - 1 + c.len].strip() for c in rule.columns]
        elif len(spans) == len(rule.columns):
            values = [line[a:b].strip() for a, b in spans]
        else:                               # columns don't line up: split on wide gaps
            values = [m.group() for m in _CHUNK.finditer(line)]
            values = (values + [""] * len(rule.columns))[:len(rule.columns)]
        out.append((r, [Cell(v, c.kind, _tone(v, rule.badges, c.kind) if c.kind == "badge"
                             else "") for v, c in zip(values, rule.columns)]))
    return out


def view(layout: Layout, lines: list[str], fields: list[InputField]) -> FormView:
    """Read a matched screen through its layout. ``lines`` should have hidden
    fields blanked, as the terminal's text always does."""
    title = layout.title.read(lines) if layout.title else ""
    subtitle = layout.subtitle.read(lines) if layout.subtitle else ""
    header, cards = [], {}
    for item in layout.items:
        fld = _field_at(fields, item.at) if item.editable else None
        text = item.at.read(lines)
        entry = Entry(item.label, text, item.kind,
                      _tone(text, item.badges, item.kind) if item.badges or item.kind ==
                      "badge" else "", fld)
        if item.editable and fld is None:
            entry.kind = item.kind              # no field there now: show it read-only
        if item.place == "header":
            header.append(entry)
        else:
            cards.setdefault(item.card, []).append(entry)
    tables = [TableView(rule.title, rule.columns, _cells(rule, lines, fields), rule.select)
              for rule in layout.tables]
    return FormView(layout, title or layout.name, subtitle, header, list(cards.items()), tables)


# --------------------------------------------------- make from a screen


_LEADER = re.compile(r"^(?P<label>\S(?:.*?\S)?)\s*(?:(?:\s?\.){2,}\s?:?|:)\s+(?P<value>\S.*?)\s*$")
_MONEY = re.compile(r"^[-+$£€]?\s?[\d,]+\.\d{2}-?$")
_ID = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9#@$]{3,10}$")


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _clean(label: str) -> str:
    return re.sub(r"[\s.:=>-]+$", "", label).strip() or "Field"


def make(lines: list[str], fields: list[InputField], name: str = "") -> str:
    """A starting rule for this screen, as TOML text to edit and save."""
    masked = [list(line) for line in lines]
    for f in fields:
        for c in range(f.col, min(len(masked[f.row]), f.col + f.length)):
            masked[f.row][c] = " "
    text = ["".join(r) for r in masked]
    title = screen_title(text, fields)
    name = name or title or "New layout"
    # Recognise it by an id near the top (CUST01, SYS0001 is no good: it's on
    # every screen of that system), else by its title.
    match = None
    for row in range(min(3, len(text))):
        for m in _CHUNK.finditer(text[row]):
            if _ID.match(m.group()) and m.start() < 12:
                match = (row + 1, m.start() + 1, m.group())
                break
        if match:
            break
    if match is None and title:
        for row in range(min(3, len(text))):
            raw = text[row]
            for m in _CHUNK.finditer(raw):
                if m.group().strip(" .:-=*").lower() == title.lower():
                    match = (row + 1, m.start() + 1, m.group())
                    break
            if match:
                break
    out = ["# Made from a screen by Cherminal. Rows and columns count from 1.",
           "# Check the match, rename the labels, then save it in your layouts folder",
           "# (or a shared setup folder's layouts/ for everyone).", "", "[screen]",
           f"name = {_q(name)}"]
    if match:
        out.append(f"match = [{{ row = {match[0]}, col = {match[1]}, text = {_q(match[2])} }}]")
    else:
        out.append('match = [{ row = 1, col = 1, text = "CHANGE ME" }]')
    tables = find_tables(text)
    table_rows = {r for t in tables for r in range(t.top, t.bottom + 1)}
    field_rows = {f.row for f in fields}
    first = True
    for f in fields:
        if f.row in table_rows:
            continue
        before = [m.group() for m in _CHUNK.finditer(text[f.row][:f.col])]
        label = _clean(before[-1]) if before else f"Field {f.row + 1}:{f.col + 1}"
        out += ["", "[[field]]", f"label = {_q(label)}",
                f"at = {{ row = {f.row + 1}, col = {f.col + 1}, len = {f.length} }}"]
        if first:
            out.append('place = "header"')
            first = False
    for row, line in enumerate(text):
        if row < 1 or row in table_rows or row in field_rows or row >= len(text) - 2:
            continue
        m = _LEADER.match(line.strip()) if line.strip() else None
        if not m or "=" in m.group("value"):
            continue
        offset = len(line) - len(line.lstrip())
        value = m.group("value")
        start = offset + m.start("value")
        out += ["", "[[value]]", f"label = {_q(_clean(m.group('label')))}",
                f"at = {{ row = {row + 1}, col = {start + 1}, len = {len(value)} }}"]
        if _MONEY.match(value):
            out.append('kind = "money"')
    code = select_code("\n".join(text))
    for t in tables:
        cols = []
        for i, head in enumerate(t.header):
            values = [r[i] for r in t.rows if r[i]]
            if not values:
                continue                    # e.g. "Opt": the selection fields, empty
            money = all(_MONEY.match(v) for v in values)
            cols.append(_q(f"{head or f'Column {i + 1}'}{':money' if money else ''}"))
        out += ["", "[[table]]", f"rows = \"{t.top + 2}-{t.bottom + 1}\"",
                f"columns = [{', '.join(cols)}]"]
        sel = next((f for f in fields if t.top < f.row <= t.bottom and f.length <= 2), None)
        if sel is not None and code:
            out.append(f"select = {{ col = {sel.col + 1}, action = {_q(code)} }}")
    return "\n".join(out) + "\n"
