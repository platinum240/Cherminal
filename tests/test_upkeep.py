"""Keep-alives, dropped connections, auto-reconnect and the idle timeout."""

import os
import socket
import struct
import threading
import time

import pytest

from cherminal import policy
from cherminal.config import ProfileStore, SessionProfile
from cherminal.policy import Policy, PolicyError
from cherminal.session import Session
from cherminal.transport.telnet import IAC, NOP, TelnetTransport


@pytest.fixture(autouse=True)
def no_policy():
    yield
    policy.set_current(Policy())


def session(tmp_path, **kw):
    kw.setdefault("transport", "telnet")
    kw.setdefault("host", "127.0.0.1")
    return Session(SessionProfile(**kw), ProfileStore(tmp_path, site_roots=[]))


class Host:
    """A Telnet host that records what it receives; ``drop()`` resets the
    connection (as a dead network or a firewall would), ``logoff()`` closes it."""

    def __init__(self):
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.port = self.srv.getsockname()[1]
        self.conns, self.received = [], bytearray()
        self.accepted = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.conns.append(conn)
            conn.sendall(b"login: ")
            self.accepted.set()
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn):
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                return
            if not data:
                return
            self.received += data

    def drop(self):
        reset(self.conns[-1])

    def logoff(self):
        self.conns[-1].shutdown(socket.SHUT_RDWR)
        self.conns[-1].close()

    def close(self):
        self.srv.close()
        for c in self.conns:
            c.close()


def reset(conn):
    """Close with a TCP reset. Waking the reader thread first lets the close happen now."""
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    try:
        conn.shutdown(socket.SHUT_RD)
    except OSError:
        pass
    time.sleep(0.05)
    conn.close()


@pytest.fixture
def host():
    h = Host()
    yield h
    h.close()


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def connect(s):
    closed = []
    s.connect(on_closed=closed.append)
    assert wait(lambda: s.connected)
    return closed


def test_defaults():
    p = SessionProfile()
    assert p.idle_timeout == 15 and p.keepalive == 60 and not p.auto_reconnect
    assert not {"idle_timeout", "keepalive", "auto_reconnect"} & set(p.to_dict())
    with pytest.raises(ValueError, match="negative"):
        SessionProfile(idle_timeout=-1)


def test_policy_settings(tmp_path):
    path = tmp_path / "policy.toml"
    path.write_text("max_idle_timeout = 10\nauto_reconnect = false\n")
    rules = policy.read(path)
    assert rules.max_idle_timeout == 10 and not rules.auto_reconnect
    assert rules.idle_timeout(15) == 10          # longer than allowed: capped
    assert rules.idle_timeout(0) == 10           # "never" is not allowed either
    assert rules.idle_timeout(5) == 5            # shorter is fine
    assert Policy().idle_timeout(0) == 0
    for text, msg in (("max_idle_timeout = -1", "whole number"),
                      ("max_idle_timeout = true", "whole number"),
                      ('auto_reconnect = "no"', "true or false")):
        path.write_text(text)
        with pytest.raises(PolicyError, match=msg):
            policy.read(path)


def test_telnet_keepalive_sends_nop_and_sets_tcp_keepalive(host):
    t = TelnetTransport("127.0.0.1", host.port)
    t.keepalive = 1
    t.open()
    assert host.accepted.wait(5) and wait(lambda: t.sock is not None)
    assert t.sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
    if hasattr(socket, "TCP_KEEPIDLE"):
        assert t.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == 1
    assert wait(lambda: bytes([IAC, NOP]) in host.received, 4)
    t.close()


def test_keepalive_off(host):
    t = TelnetTransport("127.0.0.1", host.port)
    t.open()
    assert host.accepted.wait(5) and wait(lambda: t.sock is not None)
    assert not t.sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
    t.close()


def test_profile_keepalive_reaches_transport(tmp_path):
    from cherminal.transport import from_profile
    assert from_profile(SessionProfile(transport="telnet", host="h", keepalive=30)).keepalive == 30
    assert from_profile(SessionProfile(transport="telnet", host="h", keepalive=0)).keepalive == 0


def test_drop_versus_logoff(tmp_path, host):
    s = session(tmp_path, port=host.port)
    closed = connect(s)
    host.drop()
    assert wait(lambda: closed)
    assert s.dropped                              # broken: may reconnect
    s.forget_transport()
    closed = connect(s)
    host.logoff()
    assert wait(lambda: closed)
    assert not s.dropped                          # the host ended it: stay closed


def test_ssh_drop_versus_exit(tmp_path, monkeypatch):
    paramiko = pytest.importorskip("paramiko")
    from test_file_transfer import Server
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    key = paramiko.RSAKey.generate(2048)
    srv = socket.create_server(("127.0.0.1", 0))
    chans = []

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(key)
            t.start_server(server=Server())
            chans.append((t, t.accept(10)))

    threading.Thread(target=serve, daemon=True).start()
    s = session(tmp_path, transport="ssh", port=srv.getsockname()[1], username="chad")
    try:
        for exit_cleanly in (False, True):
            opened = len([c for c in chans if c[1]])
            s.forget_transport()
            closed = []
            s.connect(ask_password=lambda p: "secret", confirm_host_key=lambda *a: True,
                      on_closed=closed.append)
            assert wait(lambda: s.connected, 15)
            # (paramiko connects twice: once to learn it needs a password)
            assert wait(lambda: len([c for c in chans if c[1]]) > opened)
            t, chan = chans[-1]
            if exit_cleanly:
                chan.send_exit_status(0)
                chan.close()
            else:
                t.close()                         # the link goes away
            assert wait(lambda: closed, 10)
            assert s.dropped is not exit_cleanly, closed
    finally:
        s.disconnect()
        srv.close()


def test_idle_time(tmp_path, monkeypatch):
    s = session(tmp_path)
    clock = [1000.0]
    monkeypatch.setattr("cherminal.session.time.monotonic", lambda: clock[0])
    s.touch()
    clock[0] += 14 * 60
    assert s.idle_left() == 60
    s.key("a", "a")                               # typing resets the clock
    assert s.idle_left() == 15 * 60
    assert session(tmp_path, idle_timeout=0).idle_left() is None
    policy.set_current(Policy(max_idle_timeout=5))
    assert session(tmp_path, idle_timeout=0).idle_limit == 5


def test_no_idle_timeout_for_printers_or_during_transfers(tmp_path):
    printer = session(tmp_path, emulation="ibm3287-1")
    printer.last_input -= 3600
    assert printer.idle_left() is None
    display = session(tmp_path, emulation="ibm3278-2")
    display.last_input -= 3600

    class Busy:
        finished = False

    display.emulation.transfer = Busy()
    assert display.idle_left() is None            # a long transfer is not idleness
    display.emulation.transfer.finished = True
    assert display.idle_left() == 15 * 60         # and it counted as activity


def test_auto_reconnect_needs_session_and_policy(tmp_path):
    assert not session(tmp_path).may_reconnect
    assert session(tmp_path, auto_reconnect=True).may_reconnect
    policy.set_current(Policy(auto_reconnect=False))
    assert not session(tmp_path, auto_reconnect=True).may_reconnect


# ------------------------------------------------------------------ GUI

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(app, cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def terminal(tmp_path, **kw):
    from cherminal.gui.terminal import TerminalWidget
    return TerminalWidget(session(tmp_path, **kw))


def press_enter(term):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    term.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                 Qt.KeyboardModifier.NoModifier, "\r"))


def test_idle_disconnect_blanks_screen(app, tmp_path, host):
    term = terminal(tmp_path, port=host.port, idle_timeout=1)
    messages = []
    term.message.connect(messages.append)
    term.connect_session()
    assert pump(app, lambda: term.session.connected and "login" in term.session.screen.text())
    term.session.feed(b"\r\nACCOUNT 4417 BALANCE 120.00\r\n" * 40)
    term.session.last_input -= 30                 # 30 s left: warn once
    term.check_idle()
    term.check_idle()
    assert len(messages) == 1 and "disconnects in" in messages[0]
    term.session.last_input -= 31
    term.check_idle()
    text = term.session.screen.text()
    assert not term.session.connected and term.ended
    assert "4417" not in text and not term.session.screen.scrollback
    assert "Disconnected after 1 minutes without input" in text
    assert host.accepted.wait(1)
    host.accepted.clear()
    press_enter(term)                             # Enter signs in again
    assert host.accepted.wait(5)
    assert pump(app, lambda: term.session.connected)
    term.shutdown()


def test_auto_reconnect_after_drop(app, tmp_path, host, monkeypatch):
    import cherminal.gui.terminal as tw
    monkeypatch.setattr(tw, "RETRY_DELAYS", (0,))
    term = terminal(tmp_path, port=host.port, auto_reconnect=True)
    messages = []
    term.message.connect(messages.append)
    term.connect_session()
    assert pump(app, lambda: term.session.connected)
    host.drop()
    assert pump(app, lambda: len(host.conns) == 2 and term.session.connected)
    assert "Reconnecting in 0 seconds (try 1 of 10)" in term.session.screen.text()
    assert pump(app, lambda: "Reconnected" in messages)
    assert term.retries == 0
    host.logoff()                                 # logging off is not a drop
    assert pump(app, lambda: term.ended)
    assert "Press Enter to reconnect" in term.session.screen.text()
    time.sleep(0.2)
    app.processEvents()
    assert len(host.conns) == 2
    term.shutdown()


def test_no_auto_reconnect_unless_enabled(app, tmp_path, host):
    for kw, rules in (({}, Policy()), ({"auto_reconnect": True}, Policy(auto_reconnect=False))):
        policy.set_current(rules)
        term = terminal(tmp_path, port=host.port, **kw)
        term.connect_session()
        assert pump(app, lambda: term.session.connected)
        before = len(host.conns)
        host.drop()
        assert pump(app, lambda: term.ended)
        assert not term._retry_timer.isActive() and term.retries == 0
        assert len(host.conns) == before
        term.shutdown()


def test_gives_up_after_max_tries(app, tmp_path, monkeypatch):
    import cherminal.gui.terminal as tw
    monkeypatch.setattr(tw, "RETRY_DELAYS", (0,))
    monkeypatch.setattr(tw, "MAX_RETRIES", 3)
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    term = terminal(tmp_path, port=port, auto_reconnect=True)
    term.connect_session()
    conn, _ = srv.accept()
    assert pump(app, lambda: term.session.connected)
    srv.close()                                   # the host is gone for good
    reset(conn)
    assert pump(app, lambda: "Could not reconnect after 3 tries" in term.session.screen.text())
    assert term.retries == 0 and term.ended
    term.shutdown()


def test_editor_upkeep_tab(app, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    store = ProfileStore(tmp_path, site_roots=[])
    ed = SessionEditor(SessionProfile(name="s", host="h"), store)
    assert ed.idle_timeout.value() == 15 and ed.keepalive.value() == 60
    assert not ed.auto_reconnect.isChecked()
    ed.idle_timeout.setValue(0)
    ed.auto_reconnect.setChecked(True)
    p = ed._build()
    assert p.idle_timeout == 0 and p.auto_reconnect
    policy.set_current(Policy(max_idle_timeout=10, auto_reconnect=False))
    ed = SessionEditor(SessionProfile(name="s", host="h", idle_timeout=0, auto_reconnect=True),
                       store)
    assert ed.idle_timeout.value() == 10 and ed.idle_timeout.maximum() == 10
    assert not ed.auto_reconnect.isEnabled()
    p = ed._build()
    assert p.idle_timeout == 10 and p.auto_reconnect   # the saved choice is kept
