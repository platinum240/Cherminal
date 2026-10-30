import os
import posixpath
import socket
import threading

import paramiko
import pytest

from cherminal.config import SessionProfile
from cherminal.transport.ssh import SSHTransport, UploadCancelled


class Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if password == "secret" else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_pty_request(self, *args):
        return True

    def check_channel_shell_request(self, channel):
        channel.send(b"$ ")
        return True


def make_sftp(root):
    """A minimal SFTP server whose "/" is ``root`` and whose home is /home/username."""

    class Handle(paramiko.SFTPHandle):
        def stat(self):
            return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))

    class SFTP(paramiko.SFTPServerInterface):
        def _local(self, path):
            return os.path.join(root, self.canonicalize(path).lstrip("/"))

        def canonicalize(self, path):
            if not path.startswith("/"):
                path = "/home/username/" + path
            return posixpath.normpath(path)

        def stat(self, path):
            try:
                return paramiko.SFTPAttributes.from_stat(os.stat(self._local(path)))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)

        lstat = stat

        def open(self, path, flags, attr):
            try:
                fd = os.open(self._local(path), flags, 0o644)
                f = os.fdopen(fd, "rb+" if flags & os.O_RDWR else "wb" if flags & os.O_WRONLY else "rb")
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            h = Handle(flags)
            h.readfile = h.writefile = f
            h.filename = self._local(path)
            return h

        def remove(self, path):
            try:
                os.remove(self._local(path))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def rename(self, old, new):
            if os.path.exists(self._local(new)):
                return paramiko.SFTP_FAILURE
            os.rename(self._local(old), self._local(new))
            return paramiko.SFTP_OK

        def posix_rename(self, old, new):
            os.replace(self._local(old), self._local(new))
            return paramiko.SFTP_OK

    return SFTP


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "host"
    (root / "home/username/inbox").mkdir(parents=True)
    host_key = paramiko.RSAKey.generate(2048)
    srv = socket.create_server(("127.0.0.1", 0))
    transports = []

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(host_key)
            t.set_subsystem_handler("sftp", paramiko.SFTPServer, make_sftp(str(root)))
            t.start_server(server=Server())
            transports.append(t)

    threading.Thread(target=serve, daemon=True).start()
    yield srv.getsockname()[1], root
    srv.close()
    for t in transports:
        t.close()


def connect(port, tmp_path):
    t = SSHTransport("127.0.0.1", port, "username", known_hosts=tmp_path / "known_hosts",
                     ask_password=lambda p: "secret", confirm_host_key=lambda *a: True)
    ready = threading.Event()
    t.on_data = lambda d: ready.set()
    t.on_close = lambda r: ready.set()
    t.open()
    assert ready.wait(10)
    return t


def test_upload_to_home_and_folder(host, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    port, root = host
    src = tmp_path / "local"
    src.mkdir()
    (src / "report.txt").write_bytes(b"hello\n" * 1000)
    t = connect(port, tmp_path)
    seen = []
    try:
        assert t.upload([str(src / "report.txt")],
                        progress=lambda n, d, total: seen.append((n, d, total)) or True) \
            == ["/home/username/report.txt"]
        assert (root / "home/username/report.txt").read_bytes() == b"hello\n" * 1000
        assert seen[-1] == ("report.txt", 6000, 6000)
        assert t.upload([str(src / "report.txt")], "~/inbox") == ["/home/username/inbox/report.txt"]
        assert t.upload([str(src / "report.txt")], "/home/username/inbox") == []   # exists: kept
        with pytest.raises(OSError, match="not a folder"):
            t.upload([str(src / "report.txt")], "report.txt")
        with pytest.raises(OSError, match="not a file"):
            t.upload([str(src)])
    finally:
        t.close()


def test_replace_and_cancel_keep_existing_file(host, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    port, root = host
    (root / "home/username/data.csv").write_bytes(b"old")
    new = tmp_path / "data.csv"
    new.write_bytes(b"x" * 200_000)
    t = connect(port, tmp_path)
    try:
        asked = []
        with pytest.raises(UploadCancelled):
            t.upload([str(new)], replace=lambda p: asked.append(p) or True,
                     progress=lambda n, d, total: d < 50_000)
        assert asked == ["/home/username/data.csv"]
        assert (root / "home/username/data.csv").read_bytes() == b"old"
        assert sorted(os.listdir(root / "home/username")) == ["data.csv", "inbox"]
        t.upload([str(new)], replace=lambda p: True)
        assert (root / "home/username/data.csv").read_bytes() == b"x" * 200_000
    finally:
        t.close()


def test_file_transfer_is_off_by_default():
    p = SessionProfile(transport="ssh", host="h")
    assert not p.file_transfer
    assert "file_transfer" not in p.to_dict()
