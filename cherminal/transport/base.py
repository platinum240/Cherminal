"""Transport interface: a bidirectional byte pipe to the host."""

from __future__ import annotations

import threading
from typing import Callable


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
            while not self._closing:
                data = self._read()
                if not data:
                    break
                self.on_data(data)
        except OSError as e:
            if not self._closing:
                reason = str(e)
        except Exception as e:  # surface library errors instead of dying silently
            reason = f"{type(e).__name__}: {e}"
        self.on_close(reason)

    def write(self, data: bytes) -> None:
        if data and not self._closing:
            self._write(data)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows

    def send_break(self) -> None:
        pass

    def close(self) -> None:
        self._closing = True
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
