import socket
import threading

import paramiko
import pytest

from cherminal.transport.ssh import SSHTransport


class PasswordServer(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        ok = (username, password) == ("chad", "secret")
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_pty_request(self, *args):
        return True

    def check_channel_shell_request(self, channel):
        channel.send(b"welcome\r\n")
        return True


@pytest.fixture
def ssh_server():
    host_key = paramiko.RSAKey.generate(2048)
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    transports = []

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(host_key)
            t.start_server(server=PasswordServer())
            transports.append(t)

    threading.Thread(target=serve, daemon=True).start()
    yield port
    srv.close()
    for t in transports:
        t.close()


def test_password_prompt_when_no_keys_or_agent(ssh_server, tmp_path, monkeypatch):
    # A workstation with no ~/.ssh keys and no agent running.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return "secret"

    t = SSHTransport("127.0.0.1", ssh_server, "chad", known_hosts=tmp_path / "known_hosts",
                     ask_password=ask, confirm_host_key=lambda *a: True)
    got, closed = [], []
    ready = threading.Event()
    t.on_data = lambda d: (got.append(d), ready.set())
    t.on_close = lambda r: (closed.append(r), ready.set())
    t.open()
    assert ready.wait(10)
    t.close()
    assert closed == [] or not closed[0].startswith("SSHException"), closed
    assert prompts == ["Password for chad@127.0.0.1:"]
    assert b"welcome" in b"".join(got)


def test_login_prompt_asks_user_and_password(ssh_server, tmp_path, monkeypatch):
    # The workstation user ("bob") is not the host login ("chad").
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USER", "bob")
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    asked = []
    answers = iter([("chad", "wrong"), ("chad", "secret")])

    def ask_login(host, user, error):
        asked.append((host, user, error))
        return next(answers)

    t = SSHTransport("127.0.0.1", ssh_server, "", known_hosts=tmp_path / "known_hosts",
                     confirm_host_key=lambda *a: True, ask_login=ask_login,
                     ask_password=lambda p: pytest.fail("password-only prompt used"))
    got, closed = [], []
    ready = threading.Event()
    t.on_data = lambda d: (got.append(d), ready.set())
    t.on_close = lambda r: (closed.append(r), ready.set())
    t.open()
    assert ready.wait(10)
    t.close()
    assert b"welcome" in b"".join(got), closed
    # First prompt suggests no user (not the workstation's); the retry says why.
    assert asked == [("127.0.0.1", "", ""), ("127.0.0.1", "chad", "Login incorrect. Try again.")]


def test_login_prompt_cancel(ssh_server, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    t = SSHTransport("127.0.0.1", ssh_server, "chad", known_hosts=tmp_path / "known_hosts",
                     confirm_host_key=lambda *a: True, ask_login=lambda *a: None)
    closed = []
    ready = threading.Event()
    t.on_close = lambda r: (closed.append(r), ready.set())
    t.open()
    assert ready.wait(10)
    assert "cancelled" in closed[0]


def test_profile_wires_login_prompt():
    from cherminal.config import SessionProfile
    from cherminal.transport import from_profile
    ask = lambda *a: None  # noqa: E731
    on = from_profile(SessionProfile(transport="ssh", host="h", ask_login=True), ask_login=ask)
    off = from_profile(SessionProfile(transport="ssh", host="h"), ask_login=ask)
    assert on.ask_login is ask and off.ask_login is None
