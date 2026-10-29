"""Common interface for emulations."""

from __future__ import annotations

import codecs
from typing import Callable, NamedTuple

from ..screen import Screen


# Upper bounds on what a host can make the parsers hold in memory. Real
# sequences are far shorter; without a limit an endless one (a broken host, or
# a binary file shown on screen) grows until the client freezes.
MAX_SEQUENCE = 4096          # one escape / control sequence or string, in characters


class InputField(NamedTuple):
    """The part of one block-mode input field on one row (a field that wraps
    onto the next row comes back as two)."""
    row: int
    col: int
    length: int
    numeric: bool = False       # the host only takes numbers here
    hidden: bool = False        # non-display, e.g. a password
    modified: bool = False      # typed in since the host sent it


def row_spans(positions: list[int], cols: int, **flags) -> list[InputField]:
    """Split consecutive screen positions into one InputField per row."""
    out: list[InputField] = []
    for p in positions:
        row, col = divmod(p, cols)
        last = out[-1] if out else None
        if last and last.row == row and last.col + last.length == col:
            out[-1] = last._replace(length=last.length + 1)
        else:
            out.append(InputField(row, col, 1, **flags))
    return out


class Emulation:
    """Turns host output into screen operations.

    Subclasses implement :meth:`feed_text`. Replies to the host (device
    attributes, cursor reports, answerback) go through ``reply``.
    """

    name = "base"
    term_type = "dumb"          # value for $TERM / SSH pty request
    telnet_type = "DUMB"        # Telnet TTYPE (RFC 1091) answer
    keymap = "vt100"            # built-in keymap this emulation starts from
    family = ""                 # "ibm3270" / "ibm5250" for the IBM block-mode terminals
    block_mode = False          # True: keys edit a local buffer (see ibm3270)
    fixed_size = False          # True: the host sets the grid; the window can't resize it
    printer = False             # True: a printer session (3287), no keyboard

    def __init__(self, screen: Screen, reply: Callable[[bytes], None] | None = None,
                 encoding: str = "utf-8", answerback: str = ""):
        self.screen = screen
        self.reply = reply or (lambda data: None)
        # Block mode, Modern view: a key a field doesn't accept shows a hint
        # beside it, (position, text), instead of beeping or inhibiting input.
        self.soft_errors = False
        self.field_error: tuple[int, str] | None = None
        self.answerback = answerback
        self.encoding = encoding
        self._decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        # Modes that change what keys send; read by the keymap layer.
        self.app_cursor = False
        self.app_keypad = False
        self.bracketed_paste = False
        self.on_bell: Callable[[], None] = lambda: None
        # Block mode: called just before Enter, a PF key or Clear sends the
        # screen, while it still shows what the user saw (screen history).
        self.on_aid: Callable[[], None] = lambda: None
        # Host-initiated print jobs (raw bytes for the local printer).
        self.on_print_data: Callable[[bytes], None] = lambda data: None
        self.printing = False
        self._print_job = bytearray()
        self._held = b""

    def feed(self, data: bytes) -> None:
        self.feed_text(self._decoder.decode(data))

    def feed_text(self, text: str) -> None:
        raise NotImplementedError

    def send(self, text: str) -> None:
        self.reply(text.encode(self.encoding, errors="replace"))

    def notice(self, text: str) -> None:
        """Show a message from Cherminal itself, such as a disconnect."""
        self.feed_text(f"\r\n[Cherminal: {text}]\r\n")

    def input_fields(self) -> list[InputField]:
        """Where the user can type, for a block-mode screen (none otherwise)."""
        return []

    def click(self, pos: int) -> bool:
        """Move the cursor to screen position ``pos`` if the user can type
        there; returns whether it moved. Character-mode hosts own their cursor."""
        return False

    def reset(self) -> None:
        self.screen.reset()
        self.app_cursor = False
        self.app_keypad = False
        self.bracketed_paste = False
        self.printing = False
        self._print_job = bytearray()
