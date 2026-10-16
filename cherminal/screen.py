"""Character-cell screen model shared by every emulation.

The screen knows nothing about escape sequences; emulations translate the
host byte stream into calls on this class.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Colour values: None means the profile's default fg/bg, 0-255 an indexed
# colour, and a (r, g, b) tuple a direct colour.
Color = int | tuple[int, int, int] | None


@dataclass(frozen=True, slots=True)
class Attr:
    fg: Color = None
    bg: Color = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    blink: bool = False
    reverse: bool = False
    invisible: bool = False

    def with_(self, **changes) -> "Attr":
        return replace(self, **changes)


DEFAULT_ATTR = Attr()


@dataclass(slots=True)
class Cell:
    char: str = " "
    attr: Attr = DEFAULT_ATTR


def _blank_line(cols: int, attr: Attr = DEFAULT_ATTR) -> list[Cell]:
    # Erased cells keep only the background colour, as VT terminals do.
    fill = DEFAULT_ATTR if attr.bg is None else Attr(bg=attr.bg)
    return [Cell(" ", fill) for _ in range(cols)]


@dataclass(slots=True)
class SavedCursor:
    x: int = 0
    y: int = 0
    attr: Attr = DEFAULT_ATTR
    origin_mode: bool = False
    autowrap: bool = True
    charsets: tuple = ()
    gl: int = 0


class Screen:
    def __init__(self, cols: int = 80, rows: int = 24, scrollback: int = 2000):
        self.cols = cols
        self.rows = rows
        self.scrollback_limit = scrollback
        self.scrollback: list[list[Cell]] = []
        self.title = ""
        self.reset()

    # ----------------------------------------------------------------- state

    def reset(self) -> None:
        self.lines = [_blank_line(self.cols) for _ in range(self.rows)]
        self._alt_saved: list[list[Cell]] | None = None
        self.x = 0
        self.y = 0
        self.attr = DEFAULT_ATTR
        self.top = 0
        self.bottom = self.rows - 1
        self.origin_mode = False
        self.autowrap = True
        self.insert_mode = False
        self.cursor_visible = True
        self.reverse_screen = False
        self.wrap_pending = False
        self.tabstops = set(range(8, self.cols, 8))
        self.saved = SavedCursor()
        self.dirty = True

    @property
    def using_alt_screen(self) -> bool:
        return self._alt_saved is not None

    def resize(self, cols: int, rows: int) -> None:
        if cols == self.cols and rows == self.rows:
            return
        for line in self.lines:
            if len(line) < cols:
                line.extend(_blank_line(cols - len(line)))
            else:
                del line[cols:]
        if rows < self.rows:
            # Keep the cursor row on screen by pushing top lines to scrollback.
            excess = max(0, self.y - (rows - 1))
            for line in self.lines[:excess]:
                self._push_scrollback(line)
            self.lines = self.lines[excess:excess + rows]
            self.y -= excess
        while len(self.lines) < rows:
            self.lines.append(_blank_line(cols))
        self.cols, self.rows = cols, rows
        self.top, self.bottom = 0, rows - 1
        self.x = min(self.x, cols - 1)
        self.y = min(self.y, rows - 1)
        self.tabstops = {t for t in self.tabstops if t < cols} | set(
            range(((max(self.tabstops, default=0) // 8) + 1) * 8, cols, 8))
        self.wrap_pending = False
        self.dirty = True

    # --------------------------------------------------------------- writing

    def put_char(self, ch: str) -> None:
        if self.wrap_pending:
            self.wrap_pending = False
            self.carriage_return()
            self.linefeed()
        line = self.lines[self.y]
        if self.insert_mode:
            line.insert(self.x, Cell(ch, self.attr))
            del line[self.cols:]
        else:
            line[self.x] = Cell(ch, self.attr)
        if self.x >= self.cols - 1:
            if self.autowrap:
                self.wrap_pending = True
        else:
            self.x += 1
        self.dirty = True

    def write_text(self, text: str) -> None:
        for ch in text:
            self.put_char(ch)

    # -------------------------------------------------------- cursor motion

    def _row_limits(self) -> tuple[int, int]:
        return (self.top, self.bottom) if self.origin_mode else (0, self.rows - 1)

    def cursor_to(self, row: int, col: int) -> None:
        """Absolute 0-based position, relative to the margin in origin mode."""
        lo, hi = self._row_limits()
        self.y = max(lo, min(hi, row + (self.top if self.origin_mode else 0)))
        self.x = max(0, min(self.cols - 1, col))
        self.wrap_pending = False
        self.dirty = True

    def cursor_row(self, row: int) -> None:
        self.cursor_to(row, self.x)

    def cursor_col(self, col: int) -> None:
        self.x = max(0, min(self.cols - 1, col))
        self.wrap_pending = False
        self.dirty = True

    def cursor_up(self, n: int = 1) -> None:
        lo = self.top if self.y >= self.top else 0
        self.y = max(lo, self.y - n)
        self.wrap_pending = False
        self.dirty = True

    def cursor_down(self, n: int = 1) -> None:
        hi = self.bottom if self.y <= self.bottom else self.rows - 1
        self.y = min(hi, self.y + n)
        self.wrap_pending = False
        self.dirty = True

    def cursor_forward(self, n: int = 1) -> None:
        self.cursor_col(self.x + n)

    def cursor_back(self, n: int = 1) -> None:
        self.cursor_col(self.x - n)

    def carriage_return(self) -> None:
        self.x = 0
        self.wrap_pending = False
        self.dirty = True

    def backspace(self) -> None:
        if self.x > 0:
            self.x -= 1
        self.wrap_pending = False
        self.dirty = True

    def linefeed(self) -> None:
        if self.y == self.bottom:
            self.scroll_up(1)
        elif self.y < self.rows - 1:
            self.y += 1
        self.wrap_pending = False
        self.dirty = True

    def reverse_index(self) -> None:
        if self.y == self.top:
            self.scroll_down(1)
        elif self.y > 0:
            self.y -= 1
        self.wrap_pending = False
        self.dirty = True

    def tab(self, n: int = 1) -> None:
        for _ in range(n):
            nxt = [t for t in self.tabstops if t > self.x]
            self.x = min(nxt) if nxt else self.cols - 1
        self.wrap_pending = False
        self.dirty = True

    def back_tab(self, n: int = 1) -> None:
        for _ in range(n):
            prev = [t for t in self.tabstops if t < self.x]
            self.x = max(prev) if prev else 0
        self.wrap_pending = False
        self.dirty = True

    def set_tabstop(self) -> None:
        self.tabstops.add(self.x)

    def clear_tabstop(self, all_stops: bool = False) -> None:
        if all_stops:
            self.tabstops.clear()
        else:
            self.tabstops.discard(self.x)

    def save_cursor(self, **extra) -> None:
        self.saved = SavedCursor(self.x, self.y, self.attr, self.origin_mode,
                                 self.autowrap, **extra)

    def restore_cursor(self) -> SavedCursor:
        s = self.saved
        self.x = min(s.x, self.cols - 1)
        self.y = min(s.y, self.rows - 1)
        self.attr = s.attr
        self.origin_mode = s.origin_mode
        self.autowrap = s.autowrap
        self.wrap_pending = False
        self.dirty = True
        return s

    # ------------------------------------------------------------ scrolling

    def _push_scrollback(self, line: list[Cell]) -> None:
        if self.scrollback_limit <= 0:
            return
        self.scrollback.append(line)
        if len(self.scrollback) > self.scrollback_limit:
            del self.scrollback[: len(self.scrollback) - self.scrollback_limit]

    def set_margins(self, top: int, bottom: int) -> None:
        top = max(0, top)
        bottom = min(self.rows - 1, bottom)
        if top >= bottom:
            return
        self.top, self.bottom = top, bottom
        self.cursor_to(0, 0)

    def scroll_up(self, n: int = 1) -> None:
        n = min(n, self.bottom - self.top + 1)
        for _ in range(n):
            line = self.lines.pop(self.top)
            # Only full-screen scrolls on the main screen feed scrollback.
            if self.top == 0 and not self.using_alt_screen:
                self._push_scrollback(line)
            self.lines.insert(self.bottom, _blank_line(self.cols, self.attr))
        self.dirty = True

    def scroll_down(self, n: int = 1) -> None:
        n = min(n, self.bottom - self.top + 1)
        for _ in range(n):
            self.lines.pop(self.bottom)
            self.lines.insert(self.top, _blank_line(self.cols, self.attr))
        self.dirty = True

    # -------------------------------------------------------------- editing

    def erase_in_display(self, mode: int = 0) -> None:
        if mode == 0:
            self.erase_in_line(0)
            for y in range(self.y + 1, self.rows):
                self.lines[y] = _blank_line(self.cols, self.attr)
        elif mode == 1:
            self.erase_in_line(1)
            for y in range(0, self.y):
                self.lines[y] = _blank_line(self.cols, self.attr)
        elif mode in (2, 3):
            for y in range(self.rows):
                self.lines[y] = _blank_line(self.cols, self.attr)
            if mode == 3:
                self.scrollback.clear()
        self.dirty = True

    def erase_in_line(self, mode: int = 0) -> None:
        line = self.lines[self.y]
        blank = _blank_line(self.cols, self.attr)
        if mode == 0:
            line[self.x:] = blank[self.x:]
        elif mode == 1:
            line[: self.x + 1] = blank[: self.x + 1]
        elif mode == 2:
            line[:] = blank
        self.wrap_pending = False
        self.dirty = True

    def erase_chars(self, n: int = 1) -> None:
        line = self.lines[self.y]
        end = min(self.cols, self.x + n)
        line[self.x:end] = _blank_line(end - self.x, self.attr)
        self.dirty = True

    def insert_chars(self, n: int = 1) -> None:
        line = self.lines[self.y]
        n = min(n, self.cols - self.x)
        line[self.x:self.x] = _blank_line(n, self.attr)
        del line[self.cols:]
        self.dirty = True

    def delete_chars(self, n: int = 1) -> None:
        line = self.lines[self.y]
        n = min(n, self.cols - self.x)
        del line[self.x:self.x + n]
        line.extend(_blank_line(n, self.attr))
        self.dirty = True

    def insert_lines(self, n: int = 1) -> None:
        if not (self.top <= self.y <= self.bottom):
            return
        n = min(n, self.bottom - self.y + 1)
        for _ in range(n):
            self.lines.pop(self.bottom)
            self.lines.insert(self.y, _blank_line(self.cols, self.attr))
        self.x = 0
        self.dirty = True

    def delete_lines(self, n: int = 1) -> None:
        if not (self.top <= self.y <= self.bottom):
            return
        n = min(n, self.bottom - self.y + 1)
        for _ in range(n):
            self.lines.pop(self.y)
            self.lines.insert(self.bottom, _blank_line(self.cols, self.attr))
        self.x = 0
        self.dirty = True

    def fill_with(self, ch: str) -> None:
        """DECALN-style fill of the whole screen."""
        self.lines = [[Cell(ch) for _ in range(self.cols)] for _ in range(self.rows)]
        self.dirty = True

    # ------------------------------------------------------------ alt screen

    def enter_alt_screen(self) -> None:
        if self._alt_saved is None:
            self._alt_saved = self.lines
            self.lines = [_blank_line(self.cols) for _ in range(self.rows)]
            self.dirty = True

    def leave_alt_screen(self) -> None:
        if self._alt_saved is not None:
            self.lines = self._alt_saved
            self._alt_saved = None
            self.dirty = True

    # ---------------------------------------------------------------- views

    def line_text(self, y: int) -> str:
        return "".join(c.char for c in self.lines[y]).rstrip()

    def text(self) -> str:
        """Visible screen as plain text with trailing blanks trimmed (tests, copy)."""
        return "\n".join(self.line_text(y) for y in range(self.rows)).rstrip("\n")
