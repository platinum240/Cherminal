"""A live session: profile + screen + emulation + keymap + transport.

GUI-independent so the key and data paths can be tested without Qt.
"""

from __future__ import annotations

import threading
from typing import Callable

from . import emulation
from .config import ProfileStore, SessionProfile
from .keymap import Binding, Keymap
from .screen import Screen
from .transport import Transport, from_profile


class Session:
    def __init__(self, profile: SessionProfile, store: ProfileStore | None = None,
                 transport: Transport | None = None):
        self.profile = profile
        self.store = store or ProfileStore()
        self.encoding = profile.effective_encoding
        self.screen = Screen(profile.cols, profile.rows, profile.scrollback)
        self.emulation = emulation.create(profile.emulation, self.screen, self._reply,
                                          encoding=self.encoding,
                                          answerback=profile.answerback)
        self.keymap: Keymap = self.store.build_keymap(profile)
        self.transport = transport
        self.connected = False
        # Emulation state is touched from the reader thread and the UI thread.
        self.lock = threading.RLock()
        self.on_action: Callable[[str], None] = lambda name: None

    # -------------------------------------------------------------- wiring

    def connect(self, ask_password=None, confirm_host_key=None,
                on_update: Callable[[], None] = lambda: None,
                on_closed: Callable[[str], None] = lambda reason: None) -> None:
        if self.transport is None:
            self.transport = from_profile(self.profile, ask_password, confirm_host_key)
        t = self.transport

        def opened():
            self.connected = True
            on_update()

        def data(chunk: bytes):
            self.feed(chunk)
            on_update()

        def closed(reason: str):
            self.connected = False
            on_closed(reason)

        t.on_open, t.on_data, t.on_close = opened, data, closed
        t.open(self.screen.cols, self.screen.rows)

    def disconnect(self) -> None:
        if self.transport:
            self.transport.close()
        self.connected = False

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.emulation.feed(data)

    def _reply(self, data: bytes) -> None:
        if self.transport:
            self.transport.write(data)

    # --------------------------------------------------------------- input

    def send_text(self, text: str) -> None:
        data = text.encode(self.encoding, errors="replace")
        if self.profile.local_echo:
            self.feed(data)
        if self.transport:
            self.transport.write(data)

    def paste(self, text: str) -> None:
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if self.emulation.bracketed_paste:
            text = "\x1b[200~" + text + "\x1b[201~"
        self.send_text(text)

    def key(self, name: str, text: str = "") -> bool:
        """Handle a key press. ``text`` is what the key types if unmapped.

        Returns True if the key was consumed.
        """
        binding = self.keymap.lookup(name, self.emulation.app_cursor, self.emulation.app_keypad)
        if binding is None:
            if not text:
                return False
            if name.startswith("Alt+") and len(text) == 1:
                text = "\x1b" + text  # Alt as Meta
            self.send_text(text)
            return True
        self.run_binding(binding)
        return True

    def run_binding(self, binding: Binding, depth: int = 0) -> None:
        if binding.kind == "send":
            self.send_text(binding.value)
        elif binding.value.startswith("macro:"):
            if depth < 8:  # macros may chain, but not loop forever
                self.run_macro(binding.value[len("macro:"):], depth + 1)
        elif binding.value == "break":
            if self.transport:
                self.transport.send_break()
        elif binding.value == "reset":
            with self.lock:
                self.emulation.reset()
        else:
            self.on_action(binding.value)

    def run_macro(self, name: str, depth: int = 0) -> None:
        if name in self.profile.macros:
            self.run_binding(Binding.parse(self.profile.macros[name]), depth)

    def resize(self, cols: int, rows: int) -> None:
        with self.lock:
            self.screen.resize(cols, rows)
        if self.transport:
            self.transport.resize(cols, rows)
