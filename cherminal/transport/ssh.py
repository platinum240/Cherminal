"""SSH via paramiko: key, agent and password/keyboard-interactive auth."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .base import Transport, tcp_keepalive

# ask_password(prompt) -> password or None to give up
PasswordPrompt = Callable[[str], "str | None"]
# ask_login(host, suggested_user, error) -> (user, password) or None to give up
LoginPrompt = Callable[[str, str, str], "tuple[str, str] | None"]
# confirm_host_key(host, key_type, sha256_fingerprint, changed) -> accept?
HostKeyPrompt = Callable[[str, str, str, bool], bool]
# progress(file_name, bytes_done, bytes_total) -> False to cancel
UploadProgress = Callable[[str, int, int], bool]
# replace(remote_path) -> overwrite an existing file?
ReplacePrompt = Callable[[str], bool]


class UploadCancelled(Exception):
    pass


def fingerprint(key) -> str:
    import base64
    import hashlib
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class SSHTransport(Transport):
    def __init__(self, host: str, port: int = 22, username: str = "",
                 identity_file: str = "", term: str = "vt220",
                 known_hosts: Path | None = None,
                 ask_password: PasswordPrompt | None = None,
                 confirm_host_key: HostKeyPrompt | None = None,
                 ask_login: LoginPrompt | None = None):
        super().__init__()
        self.host, self.port = host, port
        self.username = username or os.environ.get("USER", "")
        self.identity_file = os.path.expanduser(identity_file) if identity_file else None
        self.term = term
        self.known_hosts = known_hosts
        self.ask_password = ask_password or (lambda prompt: None)
        self.confirm_host_key = confirm_host_key or (lambda *a: False)
        # Set when the session asks for user name and password together, for
        # people whose host login differs from their workstation login.
        self.ask_login = ask_login
        if ask_login:
            self.username = username
        self.client = None
        self.chan = None

    def _open(self) -> None:
        import paramiko

        transport_self = self

        class AskPolicy(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                if not transport_self.confirm_host_key(
                        hostname, key.get_name(), fingerprint(key), False):
                    raise paramiko.SSHException(f"host key for {hostname} was not accepted")
                client.get_host_keys().add(hostname, key.get_name(), key)
                if transport_self.known_hosts:
                    transport_self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
                    client.save_host_keys(str(transport_self.known_hosts))

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.known_hosts and self.known_hosts.exists():
            client.load_host_keys(str(self.known_hosts))
        client.set_missing_host_key_policy(AskPolicy())

        password = None
        error = ""
        for attempt in range(4):
            if self.ask_login:
                if self._closing:
                    raise OSError("closed")
                login = self.ask_login(self.host, self.username, error)
                if login is None:
                    raise OSError("authentication cancelled")
                self.username, password = login
            try:
                # With a login prompt, sign in only as the person typed:
                # no agent or default keys that belong to the workstation user.
                client.connect(self.host, self.port, username=self.username,
                               password=password, key_filename=self.identity_file,
                               allow_agent=not self.ask_login,
                               look_for_keys=password is None and not self.ask_login,
                               timeout=15, banner_timeout=15, auth_timeout=30)
                break
            except paramiko.BadHostKeyException as e:
                raise OSError(f"host key for {self.host} has CHANGED (possible spoofing); "
                              f"refusing to connect. Offered key: {fingerprint(e.key)}") from e
            except paramiko.SSHException as e:
                # paramiko raises a plain SSHException, not an
                # AuthenticationException, when it had nothing to try (no
                # keys, no agent, no password yet). Both mean: ask for one.
                no_methods = "No authentication methods available" in str(e)
                if not (isinstance(e, paramiko.AuthenticationException) or no_methods):
                    raise
                if attempt == 3:
                    raise OSError("authentication failed")
                if self._closing:
                    raise OSError("closed")
                if self.ask_login:
                    error = "Login incorrect. Try again."
                    continue
                password = self.ask_password(f"Password for {self.username}@{self.host}:")
                if password is None:
                    raise OSError("authentication cancelled")
        self.client = client
        if self._closing:
            return
        if self.keepalive:
            ssh = client.get_transport()
            ssh.set_keepalive(self.keepalive)      # paramiko sends the keep-alives itself
            tcp_keepalive(ssh.sock, self.keepalive)
        self.chan = client.invoke_shell(term=self.term, width=self.cols, height=self.rows)

    def _read(self) -> bytes:
        data = self.chan.recv(65536)
        if not data and self.chan.exit_status == -1 and not self._closing:
            # The shell ended without an exit status: the connection broke.
            raise OSError("the connection to the host was lost")
        return data

    def _write(self, data: bytes) -> None:
        self.chan.sendall(data)

    def resize(self, cols: int, rows: int) -> None:
        super().resize(cols, rows)
        if self.chan:
            self.chan.resize_pty(width=cols, height=rows)

    def upload(self, paths: list[str], remote_dir: str = "",
               progress: UploadProgress | None = None,
               replace: ReplacePrompt | None = None) -> list[str]:
        """Copy local files to the host over SFTP on this connection.

        Uses the already authenticated, host-key-checked SSH connection, so
        nothing is sent anywhere the session isn't already connected to. Only
        the file's own name is used on the host (no local folders), and an
        existing file is replaced only if ``replace`` says so. Returns the
        remote paths written.
        """
        import posixpath
        import stat
        if not self.client or not self.client.get_transport() \
                or not self.client.get_transport().is_active():
            raise OSError("not connected")
        progress = progress or (lambda *a: True)
        replace = replace or (lambda path: False)
        written = []
        with self.client.open_sftp() as sftp:
            home = sftp.normalize(".")
            target = remote_dir.strip() or home
            if target == "~" or target.startswith("~/"):
                target = posixpath.join(home, target[2:])
            elif not target.startswith("/"):
                target = posixpath.join(home, target)
            if not stat.S_ISDIR(sftp.stat(target).st_mode):
                raise OSError(f"{target} is not a folder on {self.host}")
            for path in paths:
                name = os.path.basename(path)
                if not os.path.isfile(path):
                    raise OSError(f"{name} is not a file")
                remote = posixpath.join(target, name)
                exists = True
                try:
                    sftp.stat(remote)
                except FileNotFoundError:
                    exists = False
                if exists and not replace(remote):
                    continue

                def cb(done, total, name=name):
                    if not progress(name, done, total):
                        raise UploadCancelled()
                # Write beside the target and rename at the end, so a cancelled
                # or broken upload never leaves half a file in its place.
                part = remote + ".part"
                try:
                    sftp.put(path, part, callback=cb)
                except BaseException:
                    try:
                        sftp.remove(part)
                    except OSError:
                        pass
                    raise
                try:
                    sftp.posix_rename(part, remote)
                except OSError:
                    if exists:
                        sftp.remove(remote)
                    sftp.rename(part, remote)
                written.append(remote)
        return written

    def _close(self) -> None:
        if self.client:
            self.client.close()
