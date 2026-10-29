"""Session logs that clean up after themselves, and the connection audit log."""

import errno
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cherminal import policy, sessionlog
from cherminal.config import ProfileStore, SessionProfile
from cherminal.policy import Policy, PolicyError
from cherminal.session import Session
from cherminal.sessionlog import SessionLog
from cherminal.transport import Transport


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    yield
    policy.set_current(Policy())


class FakeHost(Transport):
    """Connects at once and records what the session sends."""

    def __init__(self):
        super().__init__()
        self.sent = bytearray()

    def open(self, cols=80, rows=24):
        self.on_open()

    def _write(self, data):
        self.sent += data

    def _close(self):
        pass

    def drop(self, reason="connection reset"):
        self.failed = True
        self.on_close(reason)


def session(tmp_path, **kw):
    kw.setdefault("transport", "telnet")
    kw.setdefault("host", "mainframe.example.com")
    kw.setdefault("name", "Payroll")
    host = FakeHost()
    s = Session(SessionProfile(**kw), ProfileStore(tmp_path, site_roots=[]), transport=host)
    return s, host


def log_text(tmp_path, name="payroll"):
    return (tmp_path / "state/cherminal/logs" / f"{name}.log").read_text()


def test_logging_is_off_by_default(tmp_path):
    s, _ = session(tmp_path)
    s.connect()
    s.feed(b"hello\r\n")
    s.disconnect()
    assert not (tmp_path / "state/cherminal/logs").exists()
    p = SessionProfile()
    assert not p.log_session and p.log_file_kb == 1024 and p.log_keep == 2


def test_vt_session_log_hides_hidden_text(tmp_path):
    s, _ = session(tmp_path, log_session=True, rows=5)
    s.connect()
    s.feed(b"login: chad\r\nPassword: \x1b[8mhunter2\x1b[0m\r\n")
    s.feed(b"".join(b"line %d\r\n" % i for i in range(10)))
    s.send_text("typed secret")                   # keystrokes are not logged
    s.disconnect()
    text = log_text(tmp_path)
    assert "Payroll: connected to mainframe.example.com:23 (telnet, vt220)" in text
    assert "login: chad" in text and "line 0" in text and "line 9" in text
    assert "hunter2" not in text and "typed secret" not in text
    assert text.count("line 9") == 1              # the screen at the end is written once
    assert "disconnected: closed by the user ====" in text
    path = tmp_path / "state/cherminal/logs/payroll.log"
    if sys.platform != "win32":                   # Windows has ACLs, not modes
        assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_log_survives_a_drop_and_reconnect(tmp_path):
    s, host = session(tmp_path, log_session=True)
    s.connect()
    s.feed(b"first connection\r\n")
    host.drop()
    assert s.dropped and s.log is None
    s.transport = FakeHost()
    s.connect()
    s.feed(b"second connection\r\n")
    s.disconnect()
    text = log_text(tmp_path)
    assert text.index("first connection") < text.index("disconnected: connection reset") \
        < text.index("second connection")
    assert text.count("connected to") == 2


def test_block_mode_logs_each_screen_sent(tmp_path):
    from test_ibm3270 import LOGON, record
    s, host = session(tmp_path, emulation="ibm3278-2", log_session=True)
    s.connect()
    s.feed(record(LOGON))
    s.send_text("CHAD")
    s.key("Tab")
    s.send_text("hunter2")
    s.key("Enter")
    s.key("Enter")                                # same screen again: not repeated
    s.disconnect()
    text = log_text(tmp_path)
    assert "USERID===>CHAD" in text.replace(" ", "")
    assert "PASSWORD  ===>" in text and "hunter2" not in text
    assert text.count("---- screen at") == 1


def test_rotation_keeps_a_few_small_files(tmp_path):
    folder = tmp_path / "logs"
    log = SessionLog(folder, "s", max_bytes=1000, keep=2, total_bytes=10**6)
    for i in range(500):
        log.write(f"line {i:04d} " + "x" * 20)
    log.close()
    names = sorted(os.listdir(folder))
    assert names == ["s.log", "s.log.1", "s.log.2"]
    assert all((folder / n).stat().st_size <= 1100 for n in names)
    assert "line 0499" in (folder / "s.log").read_text()
    assert "line 0000" not in "".join((folder / n).read_text() for n in names)


def test_keep_zero_keeps_only_the_current_file(tmp_path):
    folder = tmp_path / "logs"
    log = SessionLog(folder, "s", max_bytes=200, keep=0, total_bytes=10**6)
    for i in range(50):
        log.write("x" * 30)
    log.close()
    assert os.listdir(folder) == ["s.log"]


def test_folder_is_held_under_its_total(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    for i, name in enumerate(["old.log.2", "old.log.1", "other.log", "notes.txt"]):
        (folder / name).write_bytes(b"x" * 4000)
        os.utime(folder / name, (1000 + i, 1000 + i))
    log = SessionLog(folder, "s", max_bytes=1000, keep=2, total_bytes=9000)
    assert sorted(os.listdir(folder)) == ["notes.txt", "old.log.1", "other.log", "s.log"]
    for _ in range(100):
        log.write("y" * 50)
    log.close()
    logs = [f for f in folder.iterdir() if ".log" in f.name]
    assert sum(f.stat().st_size for f in logs) <= 9000 + 1100
    assert (folder / "notes.txt").exists()          # only log files are touched


def test_full_disk_stops_logging_not_the_session(tmp_path, monkeypatch):
    s, _ = session(tmp_path, log_session=True, rows=3)
    s.connect()

    def full(*a):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(s.log._file, "write", full)
    s.feed(b"".join(b"line %d\r\n" % i for i in range(10)))
    assert "No space left" in s.log.error
    assert s.screen.line_text(1) == "line 9"
    s.disconnect()


def test_policy_controls_logging(tmp_path):
    path = tmp_path / "policy.toml"
    path.write_text('session_logging = "always"\nlog_dir = "' + tmp_path.as_posix()
                    + '/central/%u"\nlog_total_mb = 2\naudit_log = true\n')
    rules = policy.read(path)
    assert rules.session_logging == "always" and rules.log_total_mb == 2 and rules.audit_log
    policy.set_current(rules)
    s, _ = session(tmp_path)                      # logging off in the session, forced on
    s.connect()
    s.disconnect()
    user = sessionlog._user()
    assert (tmp_path / "central" / user / "payroll.log").exists()
    assert s.log is None
    policy.set_current(Policy(session_logging="never"))
    s, _ = session(tmp_path, name="Other", log_session=True)
    s.connect()
    assert s.log is None
    for text, msg in (('session_logging = "sometimes"', "session_logging"),
                      ("log_total_mb = 0", "whole number"), ("log_dir = 5", "path")):
        path.write_text(text)
        with pytest.raises(PolicyError, match=msg):
            policy.read(path)


def test_audit_log(tmp_path, monkeypatch):
    syslog = pytest.importorskip("syslog")
    lines = []
    monkeypatch.setattr(syslog, "openlog", lambda *a: None)
    monkeypatch.setattr(syslog, "syslog", lambda prio, msg: lines.append((prio, msg)))
    s, host = session(tmp_path)
    s.connect()
    s.disconnect()
    assert lines == []                            # off unless the policy turns it on
    policy.set_current(Policy(audit_log=True))
    s, host = session(tmp_path)
    s.connect()
    s.send_text("hunter2")
    host.drop()
    s.transport = FailingHost()
    s.connect()
    assert [m.split("event=")[1].split()[0] for _, m in lines] == \
        ["connected", "disconnected", "connect-failed"]
    user = sessionlog._user()
    assert lines[0] == (syslog.LOG_INFO, f"user={user} session='Payroll' transport=telnet "
                                         f"host=mainframe.example.com:23 event=connected")
    assert "connection reset; after 0h00m00s" in lines[1][1]
    assert lines[1][0] == lines[2][0] == syslog.LOG_WARNING
    assert "refused" in lines[2][1]
    assert not any("hunter2" in m for _, m in lines)


class FailingHost(FakeHost):
    def open(self, cols=80, rows=24):
        self.failed = True
        self.on_close("connection refused")


def test_editor_logging_tab(tmp_path):
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841
    from cherminal.gui.dialogs import SessionEditor
    store = ProfileStore(tmp_path, site_roots=[])
    ed = SessionEditor(SessionProfile(name="s", host="h"), store)
    assert not ed.log_session.isChecked() and not ed.log_file_kb.isEnabled()
    ed.log_session.setChecked(True)
    ed.log_file_kb.setValue(256)
    ed.log_keep.setValue(1)
    p = ed._build()
    assert p.log_session and p.log_file_kb == 256 and p.log_keep == 1
    policy.set_current(Policy(session_logging="always"))
    ed = SessionEditor(SessionProfile(name="s", host="h"), store)
    assert ed.log_session.isChecked() and not ed.log_session.isEnabled()
    assert not ed._build().log_session            # the policy decides; the file is unchanged
