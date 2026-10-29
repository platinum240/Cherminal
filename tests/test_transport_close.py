import os
import socket
import sys
import threading
import time

import pytest

from cherminal.transport.base import Transport
from cherminal.transport.local import LocalTransport
from cherminal.transport.telnet import TelnetTransport


class SlowConnect(Transport):
    """Connects only when ``release`` is set, like a slow SSH handshake."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.connected = False
        self.torn_down = threading.Event()

    def _open(self):
        self.release.wait(5)
        self.connected = True

    def _read(self):
        time.sleep(0.05)
        return b"x"

    def _write(self, data):
        pass

    def _close(self):
        if self.connected:
            self.connected = False
            self.torn_down.set()


def test_close_during_connect_tears_down_late_connection():
    t = SlowConnect()
    opened, data = [], []
    t.on_open = lambda: opened.append(1)
    t.on_data = data.append
    t.open()
    t.close()                 # user closes the tab while still connecting
    t.release.set()           # ...and the connection completes afterwards
    t._thread.join(2)
    assert not t._thread.is_alive()
    assert t.torn_down.is_set() and not t.connected
    assert opened == [] and data == []


def test_telnet_close_ends_reader_and_socket():
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    accepted = []
    threading.Thread(target=lambda: accepted.append(srv.accept()[0]), daemon=True).start()
    t = TelnetTransport("127.0.0.1", port)
    opened, closed = threading.Event(), threading.Event()
    t.on_open = opened.set
    t.on_close = lambda reason: closed.set()
    t.open()
    # Connected on our side too: the server can accept before the client's
    # connect returns, and a close while connecting ends without on_close.
    assert opened.wait(2)
    deadline = time.time() + 2
    while not accepted and time.time() < deadline:
        time.sleep(0.01)
    t.close()
    assert closed.wait(2)
    conn = accepted[0]
    conn.settimeout(2)
    # The server sees the client's negotiation, then EOF once we close.
    while conn.recv(1024):
        pass
    conn.close()
    srv.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix pseudo-terminal")
def test_local_shell_is_hung_up_on_close():
    t = LocalTransport("sleep 30")
    t.open()
    deadline = time.time() + 2
    while not t.pid and time.time() < deadline:
        time.sleep(0.01)
    pid = t.pid
    t.close()
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            done = pid        # already reaped by close()
        if done:
            break
        time.sleep(0.02)
    assert done == pid
