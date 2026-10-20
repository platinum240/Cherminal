"""Transport interface: a bidirectional byte pipe to the host."""

from __future__ import annotations

import socket
import threading
from typing import Callable


def tcp_keepalive(sock: socket.socket, seconds: int) -> None:
    """Have the kernel probe an idle connection after ``seconds``, so a host
    or network that has gone away is noticed (and NAT and firewall entries
    stay open) even when nothing is being typed."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for name, value in (("TCP_KEEPIDLE", seconds), ("TCP_KEEPINTVL", max(5, seconds // 3)),
                        ("TCP_KEEPCNT", 3)):
        if hasattr(socket, name):
            sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)


class Transport:
    """Subclasses implement ``_open``, ``_read`` (blocking), ``_write``, ``_close``.

    ``on_open``, ``on_data`` and ``on_close`` are called from the reader
    thread; GUI code must marshal them onto its own thread.
    """

    def __init__(self):
        self.on_data: Callable[[bytes], None] = lambda data: None
        self.on_open: Callable[[], None] = lambda: None
        self.on_close: Callable[[str], None] = lambda reason: None
        self._thread: threading.Thread | None = None
        self._closing = False
        self.cols, self.rows = 80, 24
        self.keepalive = 0          # seconds between keep-alives; 0 = off
        # True when the connection ended in an error (dropped, reset, timed
        # out) rather than the host closing it, such as after logging off.
        self.failed = False
        self._stop = threading.Event()

    def open(self, cols: int = 80, rows: int = 24) -> None:
        """Connect and start reading, both on a background thread.

        ``on_open`` fires once connected; failures arrive via ``on_close``.
        """
        self.cols, self.rows = cols, rows
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        reason = "connection closed"
        try:
            self._open()
            if self._closing:
                # Closed while still connecting: drop the late connection.
                self._close()
                return
            self.on_open()
            if self.keepalive and type(self)._keepalive is not Transport._keepalive:
                threading.Thread(target=self._keepalive_loop, daemon=True).start()
            while not self._closing:
                data = self._read()
                if not data:
                    break
                self.on_data(data)
        except OSError as e:
            if not self._closing:
                reason = str(e) or type(e).__name__
                self.failed = True
        except Exception as e:  # surface library errors instead of dying silently
            reason = f"{type(e).__name__}: {e}"
            self.failed = True
        self._stop.set()
        self.on_close(reason)

    def _keepalive_loop(self) -> None:
        while not self._stop.wait(self.keepalive):
            if self._closing:
                return
            try:
                self._keepalive()
            except OSError:
                return              # the reader notices the broken connection

    def write(self, data: bytes) -> None:
        if data and not self._closing:
            self._write(data)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows

    def send_break(self) -> None:
        pass

    def close(self) -> None:
        self._closing = True
        self._stop.set()
        try:
            self._close()
        except OSError:
            pass

    # subclass hooks
    def _open(self) -> None:
        raise NotImplementedError

    def _read(self) -> bytes:
        raise NotImplementedError

    def _write(self, data: bytes) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    def _keepalive(self) -> None:
        """Send something harmless to keep an idle connection open."""
