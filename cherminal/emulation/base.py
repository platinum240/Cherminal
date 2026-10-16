"""Common interface for emulations."""

from __future__ import annotations

import codecs
from typing import Callable

from ..screen import Screen


class Emulation:
    """Turns host output into screen operations.

    Subclasses implement :meth:`feed_text`. Replies to the host (device
    attributes, cursor reports, answerback) go through ``reply``.
    """

    name = "base"
    term_type = "dumb"          # value for $TERM / SSH pty request
    telnet_type = "DUMB"        # Telnet TTYPE (RFC 1091) answer
    keymap = "vt100"            # built-in keymap this emulation starts from

    def __init__(self, screen: Screen, reply: Callable[[bytes], None] | None = None,
                 encoding: str = "utf-8", answerback: str = ""):
        self.screen = screen
        self.reply = reply or (lambda data: None)
        self.answerback = answerback
        self.encoding = encoding
        self._decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        # Modes that change what keys send; read by the keymap layer.
        self.app_cursor = False
        self.app_keypad = False
        self.bracketed_paste = False
        self.on_bell: Callable[[], None] = lambda: None

    def feed(self, data: bytes) -> None:
        self.feed_text(self._decoder.decode(data))

    def feed_text(self, text: str) -> None:
        raise NotImplementedError

    def send(self, text: str) -> None:
        self.reply(text.encode(self.encoding, errors="replace"))

    def reset(self) -> None:
        self.screen.reset()
        self.app_cursor = False
        self.app_keypad = False
        self.bracketed_paste = False
