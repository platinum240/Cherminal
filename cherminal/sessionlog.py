"""Session logs (the text of a session, kept in files that clean up after
themselves) and the connection audit log (to syslog/journald).

Thin clients have little disk, so a session log never grows without limit:
each session writes ``<session>.log`` until it reaches ``log_file_kb``, then
starts a new one and keeps only ``log_keep`` older files. On top of that the
whole log folder is held under ``log_total_mb`` (10 MB unless the site policy
says otherwise) by deleting the oldest files of any session.

What goes in a log is what the screen showed: lines as they scroll off the
top and, for IBM block-mode screens, each screen as it was sent to the host.
Hidden text (password fields) is written as blanks, and keystrokes are never
recorded, so a password typed at a prompt that doesn't echo it is not logged.
"""

from __future__ import annotations

import getpass
import os
import time
from datetime import datetime
from pathlib import Path

from . import policy, system


def log_dir() -> Path:
    """The site policy's ``log_dir`` (``%u`` = user name), else
    ``$XDG_STATE_HOME/cherminal/logs`` (``~/.local/state/cherminal/logs``;
    ``~/Library/Logs/Cherminal`` on macOS)."""
    configured = policy.current().log_dir
    if configured:
        return Path(os.path.expanduser(configured.replace("%u", _user())))
    return system.log_dir()


def _user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return str(os.getuid())


def line_text(line) -> str:
    return "".join(" " if c.attr.invisible else c.char for c in line).rstrip()


class SessionLog:
    def __init__(self, folder: Path, name: str, max_bytes: int, keep: int, total_bytes: int):
        self.folder = folder
        self.path = folder / f"{name}.log"
        self.max_bytes, self.keep, self.total_bytes = max_bytes, keep, total_bytes
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._file = None
        self.error = ""              # why logging stopped (e.g. the disk is full)
        self._last_screen: list[str] | None = None
        self._open()
        self._trim_folder()

    def _open(self) -> None:
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        # Line buffered: a power cut or crash loses at most the current line.
        self._file = os.fdopen(fd, "a", encoding="utf-8", errors="replace", buffering=1)

    def write(self, text: str) -> None:
        if self._file is None:
            return
        try:
            self._file.write(text + "\n")
            if self._file.tell() >= self.max_bytes:
                self._rotate()
        except OSError as e:
            # Never let a full disk break the session: stop logging instead.
            self.error = f"session logging stopped: {e.strerror or e}"
            self.close()

    def mark(self, text: str) -> None:
        self.write(f"==== {datetime.now():%Y-%m-%d %H:%M:%S} {text} ====")

    def screen(self, lines: list[str]) -> None:
        """A whole screen (block mode), skipped if it hasn't changed."""
        while lines and not lines[-1]:
            lines = lines[:-1]
        if not lines or lines == self._last_screen:
            return
        self._last_screen = lines
        self.write(f"---- screen at {datetime.now():%H:%M:%S} ----")
        for line in lines:
            self.write(line)

    def _rotate(self) -> None:
        self._file.close()
        for i in range(self.keep, 0, -1):
            older = self.path.with_name(f"{self.path.name}.{i}")
            if i == self.keep:
                older.unlink(missing_ok=True)
            else:
                newer = older.with_name(f"{self.path.name}.{i + 1}")
                if older.exists():
                    older.rename(newer)
        if self.keep:
            self.path.rename(self.path.with_name(f"{self.path.name}.1"))
        else:
            self.path.unlink(missing_ok=True)
        self._open()
        self._trim_folder()

    def _trim_folder(self) -> None:
        """Delete the oldest log files, of any session, until the folder fits."""
        files = []
        for f in self.folder.iterdir():
            if ".log" in f.name and f.is_file() and f != self.path:
                st = f.stat()
                files.append((st.st_mtime, st.st_size, f))
        used = sum(size for _, size, _ in files) + self.path.stat().st_size
        for _, size, f in sorted(files):
            if used <= self.total_bytes:
                break
            f.unlink(missing_ok=True)
            used -= size

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None


def open_log(profile) -> SessionLog | None:
    """The session's log if logging is on for it (the policy may force it on
    or off), else None."""
    rules = policy.current()
    if not rules.logging(profile.log_session):
        return None
    return SessionLog(log_dir(), profile.slug, profile.log_file_kb * 1024, profile.log_keep,
                      rules.log_total_mb * 1024 * 1024)


# ------------------------------------------------------------------ audit

_opened = False


def audit(event: str, profile, detail: str = "", failed: bool = False) -> None:
    """One line per connection event to syslog/journald when the site policy
    has ``audit_log = true``: who, which session and host, what happened.
    Never anything typed or shown in the session."""
    if not policy.current().audit_log:
        return
    try:
        import syslog
    except ImportError:            # not a Unix system
        return
    global _opened
    if not _opened:
        syslog.openlog("cherminal", syslog.LOG_PID, syslog.LOG_AUTH)
        _opened = True
    where = {"local": "local", "serial": profile.serial_device}.get(
        profile.transport, f"{profile.host}:{profile.effective_port}")
    message = (f"user={_user()} session={profile.name!r} transport={profile.transport} "
               f"host={where} event={event}")
    if detail:
        message += f" detail={detail!r}"
    syslog.syslog(syslog.LOG_WARNING if failed else syslog.LOG_INFO, message)


def duration(started: float | None) -> str:
    if started is None:
        return ""
    secs = int(time.monotonic() - started)
    return f"{secs // 3600}h{secs // 60 % 60:02d}m{secs % 60:02d}s"
