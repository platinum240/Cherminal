"""A live session: profile + screen + emulation + keymap + transport.

GUI-independent so the key and data paths can be tested without Qt.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from . import emulation, policy
from .sessionlog import SessionLog, audit, duration, line_text, open_log
from .config import ProfileStore, SessionProfile
from .keymap import Binding, Keymap
from .screen import Screen
from .transport import Transport, from_profile


class Session:
    def __init__(self, profile: SessionProfile, store: ProfileStore | None = None,
                 transport: Transport | None = None):
        policy.current().check(profile)    # PolicyError (a ValueError) if not allowed
        self.profile = profile
        self.store = store or ProfileStore()
        self.encoding = profile.effective_encoding
        self.screen = Screen(profile.cols, profile.rows, profile.scrollback)
        self.emulation = emulation.create(profile.emulation, self.screen, self._reply,
                                          encoding=self.encoding,
                                          answerback=profile.answerback)
        self.emulation.host_print = profile.host_print
        if self.emulation.printer:
            self.emulation.printer_name = profile.printer
        self.keymap: Keymap = self.store.build_keymap(profile)
        self.transport = transport
        self.connected = False
        # Emulation state is touched from the reader thread and the UI thread.
        self.lock = threading.RLock()
        self.on_action: Callable[[str], None] = lambda name: None
        self.last_input = time.monotonic()
        self.dropped = False            # the last connection broke rather than ended
        self.started: float | None = None
        self.log: SessionLog | None = None
        self.log_error = ""

    # -------------------------------------------------------------- wiring

    def connect(self, ask_password=None, confirm_host_key=None, ask_login=None,
                on_update: Callable[[], None] = lambda: None,
                on_closed: Callable[[str], None] = lambda reason: None) -> None:
        if self.transport is None:
            self.transport = from_profile(self.profile, ask_password, confirm_host_key,
                                          ask_login)
        t = self.transport
        self.dropped = False

        def opened():
            self.connected = True
            self.started = time.monotonic()
            audit("connected", self.profile)
            self._start_log()
            if self.emulation.printer:
                self.notice("connected")        # the printer's status view
            on_update()

        def data(chunk: bytes):
            self.feed(chunk)
            on_update()

        def closed(reason: str):
            was = self.connected
            self.connected = False
            self.dropped = was and t.failed
            if hasattr(self.emulation, "abort_transfer"):
                with self.lock:
                    self.emulation.abort_transfer(f"The connection closed: {reason}")
            if was:
                audit("disconnected", self.profile, f"{reason}; after {duration(self.started)}",
                      failed=t.failed)
                self._stop_log(f"disconnected: {reason}")
            else:
                audit("connect-failed", self.profile, reason, failed=True)
            on_closed(reason)

        t.on_open, t.on_data, t.on_close = opened, data, closed
        if hasattr(t, "on_tn3270e") and hasattr(self.emulation, "set_tn3270e"):
            t.on_tn3270e = self._tn3270e
        t.open(self.screen.cols, self.screen.rows)

    def _tn3270e(self, device_type: str, lu_name: str, functions) -> None:
        with self.lock:
            self.emulation.set_tn3270e(device_type, lu_name, functions)

    def disconnect(self, reason: str = "closed by the user") -> None:
        if self.transport:
            t = self.transport
            # Stop callbacks first: the UI that would receive them may be going away.
            t.on_open, t.on_data, t.on_close = (lambda: None), (lambda data: None), (lambda r: None)
            t.close()
        if self.connected:
            audit("disconnected", self.profile, f"{reason}; after {duration(self.started)}")
            self._stop_log(f"disconnected: {reason}")
        self.connected = False

    def forget_transport(self) -> None:
        """Drop the finished connection so ``connect`` makes a new one."""
        self.disconnect()
        self.transport = None

    # ----------------------------------------------------------- idle time

    def touch(self) -> None:
        self.last_input = time.monotonic()

    @property
    def idle_limit(self) -> int:
        """Minutes without input before the session is closed; 0 = never."""
        return policy.current().idle_timeout(self.profile.idle_timeout)

    def idle_left(self, now: float | None = None) -> float | None:
        """Seconds until the idle timeout, or None when there is none."""
        if not self.idle_limit:
            return None
        now = time.monotonic() if now is None else now
        return self.idle_limit * 60 - (now - self.last_input)

    @property
    def may_reconnect(self) -> bool:
        return self.profile.auto_reconnect and policy.current().auto_reconnect

    # ------------------------------------------------------------- logging

    def _start_log(self) -> None:
        try:
            log = open_log(self.profile)
        except OSError as e:
            self.log_error = f"cannot write the session log: {e.strerror or e}"
            return
        if log is None:
            return
        p = self.profile
        where = {"local": "local shell", "serial": p.serial_device}.get(
            p.transport, f"{p.host}:{p.effective_port}")
        with self.lock:
            log.mark(f"{p.name}: connected to {where} ({p.transport}, {p.emulation})")
            self.log = log
            self.screen.on_line_done = lambda line: log.write(line_text(line))

    def _stop_log(self, why: str) -> None:
        with self.lock:
            log, self.log = self.log, None
            if log is None:
                return
            self.screen.on_line_done = None
            try:
                lines = [line_text(line) for line in self.screen.lines]
                if self.emulation.block_mode:
                    log.screen(lines)
                else:
                    while lines and not lines[-1]:
                        lines.pop()
                    for line in lines:      # what was left on the screen
                        log.write(line)
                log.mark(why)
            except OSError:
                pass
            finally:
                log.close()

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.emulation.feed(data)

    def notice(self, text: str) -> None:
        with self.lock:
            self.emulation.notice(text)

    def _reply(self, data: bytes) -> None:
        if self.log is not None and self.emulation.block_mode:
            # Block mode: keep each screen as the user sent it to the host
            # (called under the lock, from the emulation).
            try:
                self.log.screen([line_text(line) for line in self.screen.lines])
            except OSError:
                pass
        if self.transport:
            self.transport.write(data)

    # --------------------------------------------------------------- input

    def send_text(self, text: str) -> None:
        self.touch()
        if self.emulation.block_mode:
            with self.lock:
                self.emulation.type_text(text)   # edits the screen; Enter sends it
            return
        data = text.encode(self.encoding, errors="replace")
        if self.profile.local_echo:
            self.feed(data)
        if self.transport:
            self.transport.write(data)

    def paste(self, text: str) -> None:
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if self.emulation.block_mode:
            paste = getattr(self.emulation, "paste_text", None)
            if paste is None:
                self.send_text(text.rstrip("\r"))
            else:
                with self.lock:
                    paste(text)                 # fills input fields, skips protected ones
            return
        if self.emulation.bracketed_paste:
            text = "\x1b[200~" + text + "\x1b[201~"
        self.send_text(text)

    def key(self, name: str, text: str = "") -> bool:
        """Handle a key press. ``text`` is what the key types if unmapped.

        Returns True if the key was consumed.
        """
        self.touch()
        binding = self.keymap.lookup(name, self.emulation.app_cursor, self.emulation.app_keypad)
        if binding is None:
            if not text:
                return False
            if name.startswith("Alt+") and len(text) == 1:
                if self.emulation.block_mode:
                    return False
                text = "\x1b" + text  # Alt as Meta
            self.send_text(text)
            return True
        self.run_binding(binding)
        return True

    def run_binding(self, binding: Binding, depth: int = 0) -> None:
        self.touch()
        if binding.kind == "send":
            self.send_text(binding.value)
        elif self.emulation.block_mode and self._block_action(binding.value):
            pass
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

    def _block_action(self, name: str) -> bool:
        with self.lock:
            return self.emulation.do_action(name)

    def run_macro(self, name: str, depth: int = 0) -> None:
        if name in self.profile.macros:
            self.run_binding(Binding.parse(self.profile.macros[name]), depth)

    # -------------------------------------------------------- file transfer

    @property
    def can_transfer(self) -> bool:
        """An IBM 3270 display session, which can run IND$FILE."""
        return hasattr(self.emulation, "start_transfer")

    def start_transfer(self, opts, limited: bool = False, on_progress=None, on_done=None):
        """Start an IND$FILE transfer (see emulation.indfile), within the site
        policy. In limited mode the local file must sit directly in
        :func:`transfer_folder`."""
        if not self.can_transfer:
            raise ValueError("file transfer needs an IBM 3270 display session")
        rules = policy.current()
        if not rules.file_transfer(opts.send, limited):
            raise policy.PolicyError("sending files to the host is not allowed on this computer"
                                     if opts.send else
                                     "receiving files from the host is not allowed on this "
                                     "computer")
        if limited or rules.limited:
            local = Path(opts.local_file)
            if (local.resolve().parent != transfer_folder().resolve()
                    or local.name.startswith(".")):
                raise policy.PolicyError(f"in limited mode files can only be transferred "
                                         f"to and from {transfer_folder()}")
        if not self.connected:
            raise ValueError("connect to the host first")
        with self.lock:
            return self.emulation.start_transfer(opts, on_progress, on_done)

    def cancel_transfer(self) -> None:
        with self.lock:
            t = getattr(self.emulation, "transfer", None)
            if t and not t.finished:
                t.cancel()

    def resize(self, cols: int, rows: int) -> None:
        if self.emulation.fixed_size:
            return
        with self.lock:
            self.screen.resize(cols, rows)
        if self.transport:
            self.transport.resize(cols, rows)


def transfer_folder() -> Path:
    """Where limited-mode file transfers read and write: ~/Downloads."""
    return Path.home() / "Downloads"
