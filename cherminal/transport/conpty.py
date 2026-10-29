"""Local shell or program on Windows, on a pseudo-console (ConPTY) through
the pywinpty package. The Unix version is in local."""

from __future__ import annotations

import os
import shlex

from .base import Transport
from .local import login_shell


def split_command(command: str) -> list[str]:
    """Split a Windows command line, keeping backslashes in paths and taking
    the quotes off quoted arguments ("C:\\Program Files\\…")."""
    return [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a
            for a in shlex.split(command, posix=False)]


class ConPtyTransport(Transport):
    def __init__(self, command: str = "", term: str = "xterm"):
        super().__init__()
        self.argv = split_command(command) if command else login_shell()
        self.term = term
        self.proc = None

    def _open(self) -> None:
        from winpty import PtyProcess

        env = dict(os.environ, TERM=self.term)
        self.proc = PtyProcess.spawn(self.argv, env=env, dimensions=(self.rows, self.cols))

    def _read(self) -> bytes:
        # The pseudo-console speaks UTF-8 whatever the console code page is;
        # pywinpty hands it over decoded, so it goes back to bytes here.
        while not self._closing:
            try:
                text = self.proc.read(65536)
            except (EOFError, OSError):
                return b""          # the shell has exited
            if text:
                return text.encode("utf-8")
        return b""

    def _write(self, data: bytes) -> None:
        try:
            self.proc.write(data.decode("utf-8", errors="replace"))
        except EOFError:
            pass                    # exited; the reader reports it

    def resize(self, cols: int, rows: int) -> None:
        super().resize(cols, rows)
        if self.proc is not None:
            self.proc.setwinsize(rows, cols)

    def _close(self) -> None:
        if self.proc is not None:
            proc, self.proc = self.proc, None
            try:
                proc.close(force=True)
            except (OSError, EOFError):
                pass
