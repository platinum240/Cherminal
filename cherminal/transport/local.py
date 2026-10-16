"""Local shell or program on a pseudo-terminal."""

from __future__ import annotations

import fcntl
import os
import pty
import shlex
import signal
import struct
import termios

from .base import Transport


class LocalTransport(Transport):
    def __init__(self, command: str = "", term: str = "xterm"):
        super().__init__()
        self.argv = shlex.split(command) if command else [os.environ.get("SHELL", "/bin/sh")]
        self.term = term
        self.pid = 0
        self.fd = -1

    def _open(self) -> None:
        pid, fd = pty.fork()
        if pid == 0:  # child
            os.environ["TERM"] = self.term
            os.environ["COLUMNS"] = str(self.cols)
            os.environ["LINES"] = str(self.rows)
            try:
                os.execvp(self.argv[0], self.argv)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.resize(self.cols, self.rows)

    def _read(self) -> bytes:
        try:
            return os.read(self.fd, 65536)
        except OSError:
            return b""  # EIO when the child exits

    def _write(self, data: bytes) -> None:
        os.write(self.fd, data)

    def resize(self, cols: int, rows: int) -> None:
        super().resize(cols, rows)
        if self.fd >= 0:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def send_break(self) -> None:
        if self.fd >= 0:
            termios.tcsendbreak(self.fd, 0)

    def _close(self) -> None:
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGHUP)
                os.waitpid(self.pid, os.WNOHANG)
            except (ProcessLookupError, ChildProcessError):
                pass
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
